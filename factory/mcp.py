"""MCP server: lets Claude, Codex or any MCP client drive the factory.

Three things shaped this file.

The tools are a thin skin over `pipeline`, the same seam the CLI and the web UI
use. Nothing here reaches past it into the database, so a tool can never leave a
clip in a state the other two surfaces cannot read.

**Approve and publish are off by default.** The whole design rests on a human
watching the first second of a clip before it goes out; an agent that can
approve its own work removes exactly that. Start the server with
`--allow-publish` when you want to hand that over, and know what you are
handing over. Everything up to the review queue is always available, because
planning and rendering are reversible and cost cents.

Every call is logged with `actor="mcp"`, so `factory logs` answers "what did the
agent do last night" without asking the agent.
"""

from __future__ import annotations

import json
import os
from typing import Any

from . import analytics, channels, db, feedback, generators, llm, logs, pipeline
from .agents import analyst
from .models import AWAITING_APPROVAL

ALLOW_PUBLISH_ENV = "FACTORY_MCP_ALLOW_PUBLISH"


def _publishing_allowed() -> bool:
    return os.environ.get(ALLOW_PUBLISH_ENV, "").lower() in {"1", "true", "yes"}


def _credentials_missing() -> bool:
    """True when no Anthropic credential resolved.

    Worth its own check because it is the likeliest reason an agent's first call
    fails, and the SDK hides the message of an unexpected exception — without
    this the agent is told only "Error executing tool plan_clips".
    """
    return not llm.has_credentials()


def resolve_channel_id(conn, channel):
    from .channels import resolve

    return resolve(conn, channel).id


def _clip_summary(row) -> dict[str, Any]:
    import json

    return {
        "id": row["id"],
        "channel": row["channel_id"],
        "status": row["status"],
        "generator": row["generator"],
        "variant": row["variant"],
        "seed": row["seed"],
        "title": row["title"],
        "description": row["description"],
        "hashtags": json.loads(row["hashtags_json"] or "[]"),
        "shows": row["render_desc"],
        "duration_s": row["duration_s"],
        "loudness_lufs": row["loudness_lufs"],
        "sameness": row["sameness"],
        "qc": json.loads(row["qc_json"] or "null"),
        "video_path": row["video_path"],
        "cost_usd": row["cost_usd"],
        "hook_text": row["hook_text"],
        "comment_prompt": row["comment_prompt"],
        "title_history": json.loads(row["title_history_json"] or "[]"),
        "published_at": row["published_at"],
        "views": row["views"],
        "avg_view_pct": row["avg_view_pct"],
        "swipe_away_pct": row["swipe_away_pct"],
    }


# The task this server process is holding, per channel. One `factory mcp`
# process is one agent, so this is that agent's own task — and it is what
# lets two agents work one channel at once without answering for each
# other's parameters.
HELD: dict[str, int] = {}


# An agent's batch is smaller and never outranks what the operator queued.
MCP_BATCH_ROWS = 50
MCP_BATCH_PRIORITY = 5


def agent_name(given: str) -> str:
    """One short lowercase word per agent. Sessions of the same tool used to
    call themselves five different things ("Claude (Opus 5) queue worker",
    "claude-opus-5-queue-main"), and the Team screen showed five strangers.
    Anything after the first word is a description, not a name."""
    import re

    first = re.sub(r"[^a-z0-9]+", " ", (given or "").lower()).split()
    return (first[0] if first else "agent")[:24]


def build_server():
    from mcp.server.mcpserver import MCPServer
    # The SDK swallows the message of any exception it did not expect, so a
    # plain PermissionError would reach the agent as "Error executing tool" with
    # no way to learn what to do about it. ToolError keeps its own text.
    from mcp.server.mcpserver.exceptions import ToolError

    server = MCPServer(
        name="shorts-factory",
        instructions=(
            "Drives a short-video pipeline. Typical loop: list_channels, "
            "plan_clips, build_clips, then review_queue and read each clip's QC "
            "verdict. Approving and publishing are disabled unless the operator "
            "started this server with --allow-publish; when they are disabled, "
            "report what is waiting and let the human decide. Every clip is "
            "reproducible from its seed, so a rejected clip costs one seed."
        ),
    )

    @server.tool(description="List channels with their queue depth, modules and spend.")
    def list_channels() -> list[dict[str, Any]]:
        with db.connect() as conn:
            out = []
            for channel in channels.all_channels(conn):
                counts = db.status_counts(conn, channel.id)
                out.append(
                    {
                        **channel.as_dict(),
                        "counts": counts,
                        "waiting": counts.get(AWAITING_APPROVAL, 0),
                        "spend_usd": db.spend(conn, channel.id),
                    }
                )
        logs.event("mcp.call", actor="mcp", tool="list_channels")
        return out

    @server.tool(description="List the generator modules a channel may draw on.")
    def list_modules(channel: str | None = None) -> dict[str, list[str]]:
        with db.connect() as conn:
            ch = channels.resolve(conn, channel)
            return generators.available(ch.variants)

    def _require_credentials() -> None:
        if _credentials_missing():
            logs.event("mcp.refused", level="error", actor="mcp", reason="no credentials")
            raise ToolError(
                "no Anthropic credential is visible to this server, so the Idea, "
                "Metadata and QC agents cannot run. The operator needs to put "
                "ANTHROPIC_API_KEY=... in the repository's .env file, or set it "
                "in this MCP server's env block. Nothing was spent."
            )

    @server.tool(
        description=(
            "Ask the Idea agent for new clip plans on a channel. Costs a few "
            "cents. Nothing is rendered yet."
        )
    )
    def plan_clips(count: int = 1, channel: str | None = None) -> dict[str, Any]:
        if count < 1 or count > 10:
            raise ToolError("count must be between 1 and 10")
        _require_credentials()
        with db.connect() as conn:
            ch = channels.resolve(conn, channel)
            run = db.start_run(conn, ch.id, "plan")
            logs.event("mcp.call", actor="mcp", tool="plan_clips", channel=ch.id, count=count)
            try:
                ids, cost = pipeline.plan(conn, ch, count)
            except Exception as exc:
                db.finish_run(conn, run, status="failed", detail=str(exc))
                raise
            db.finish_run(conn, run, status="ok", detail=f"{len(ids)} planned", cost_usd=cost)
            return {
                "channel": ch.id,
                "planned": [_clip_summary(db.get(conn, i)) for i in ids],
                "cost_usd": round(cost, 6),
            }

    @server.tool(
        description=(
            "Render, title and QC every planned clip on a channel. Slow: a few "
            "seconds of CPU per clip. Returns what reached the review queue and "
            "what QC threw out, with reasons."
        )
    )
    def build_clips(channel: str | None = None, limit: int = 5) -> dict[str, Any]:
        _require_credentials()
        with db.connect() as conn:
            ch = channels.resolve(conn, channel)
            run = db.start_run(conn, ch.id, "build")
            logs.event("mcp.call", actor="mcp", tool="build_clips", channel=ch.id)
            outcomes = pipeline.build_all(conn, ch, limit=limit)
            passed = [o for o in outcomes if o.status == AWAITING_APPROVAL]
            cost = sum(o.cost_usd for o in outcomes)
            db.finish_run(
                conn, run, status="ok",
                detail=f"{len(passed)}/{len(outcomes)} reached the queue", cost_usd=cost,
            )
            return {
                "channel": ch.id,
                "reached_queue": len(passed),
                "results": [
                    {"clip": o.clip_id, "status": o.status, "detail": o.detail}
                    for o in outcomes
                ],
                "cost_usd": round(cost, 6),
            }

    @server.tool(
        description=(
            "Clips waiting for a human decision, with their QC verdict and the "
            "path to the rendered file so it can be watched."
        )
    )
    def review_queue(channel: str | None = None) -> list[dict[str, Any]]:
        with db.connect() as conn:
            ch = channels.resolve(conn, channel)
            return [_clip_summary(r) for r in pipeline.queue(conn, ch)]

    # --- the path that needs no Anthropic key -------------------------------
    #
    # render_clip / submit_metadata / submit_qc let the calling agent be the
    # brain. Nothing here calls a model, so none of it needs a credential.

    @server.tool(
        description=(
            "Render one clip. No model is called and no credential is needed — "
            "this is pure simulation. Returns the measurements, four frames for "
            "you to look at (the opening, two middle points and the end), and "
            "recent_on_this_channel: what the last few clips here were, which "
            "is what submit_qc's looks_templated is asking you to compare "
            "against. Read the channel's rules first, then write the title "
            "yourself with submit_metadata and score the hook with submit_qc."
        )
    )
    def render_clip(
        variant: str,
        seed: int | None = None,
        hook: str = "",
        channel: str | None = None,
        generator: str = "physics",
        stage: str | None = None,
        background: str | None = None,
        course: str | None = None,
    ) -> list[Any]:
        """stage: for physics/marble_race, one of zigzag, pegboard, bumpers,
        funnels, gauntlet, cascade; omit to let the seed choose (course is the
        old name and still accepted). background: a hex colour for the backdrop, e.g.
        #102030; omit for the theme's palette. A task's instructions say when
        to pass either."""
        from mcp.server.mcpserver.utilities.types import Image

        from . import tasks as task_queue

        with db.connect() as conn:
            try:
                channel_id = resolve_channel_id(conn, channel)
                # A held task's parameters win: omitted ones are filled in,
                # changed ones are refused (see tasks.held_params).
                _, use = task_queue.held_params(conn, channel_id, {
                    "variant": variant, "seed": seed, "generator": generator,
                    "stage": stage or course, "background": background,
                }, HELD.get(channel_id))
                clip_id, frames, facts = pipeline.create_and_render(
                    conn, channel, variant=use["variant"], generator=use["generator"] or "physics",
                    seed=use["seed"], hook=hook,
                    # A season task also carries cast, story and level ids; they
                    # ride along from the held task untouched.
                    params=task_queue.clip_params(use) or None,
                )
                task_id = db.attach_clip_to_claimed_task(
                    conn, channel_id, clip_id, HELD.get(channel_id))
                if task_id:
                    logs.event("task.step", channel=resolve_channel_id(conn, channel), task=task_id,
                               clip=clip_id, step="rendered")
            except (ValueError, KeyError, RuntimeError) as exc:
                # A stalled seed raises RuntimeError with the reason in it;
                # without this the agent saw "Error executing tool" and
                # blamed the stage.
                raise ToolError(str(exc)) from None
        logs.event("mcp.call", actor="mcp", tool="render_clip", clip=clip_id,
                   variant=variant)
        summary = {
            "clip_id": clip_id,
            "measured": facts,
            "note": (
                "hard_failures is measured here from the file, not taken from "
                "you. Anything listed there rejects the clip whatever you score "
                "the hook."
            ),
        }
        return [json.dumps(summary, indent=1, default=str)] + [
            Image(data=frame, format="png").to_image_content() for frame in frames
        ]

    @server.tool(
        description=(
            "Store the title, description and hashtags you wrote for a rendered "
            "clip. English only, 20-90 characters, 3 to 5 hashtags — the same "
            "validation this project's own metadata agent is held to."
        )
    )
    def submit_metadata(
        clip_id: str,
        title: str,
        description: str,
        hashtags: list[str],
        hook_text: str | None = None,
        comment_prompt: str | None = None,
    ) -> dict[str, Any]:
        """hook_text re-renders the clip with that caption burned in (same seed,
        same race) when it differs from what render_clip used. comment_prompt is
        a question to pin as the first comment; only one the clip answers."""
        from pydantic import ValidationError

        from .models import Metadata

        try:
            meta = Metadata(
                title=title, description=description, hashtags=hashtags,
                rationale="written by an external agent",
                hook_text=hook_text, comment_prompt=comment_prompt,
            )
        except ValidationError as exc:
            raise ToolError(f"metadata rejected: {exc}") from None
        with db.connect() as conn:
            try:
                pipeline.attach_metadata(conn, clip_id, meta)
            except ValueError as exc:
                raise ToolError(str(exc)) from None
        logs.event("mcp.call", actor="mcp", tool="submit_metadata", clip=clip_id)
        with db.connect() as conn:
            row = db.get(conn, clip_id)
        out = {
            "clip": clip_id, "status": row["status"], "title": meta.title,
            "hook_text": row["hook_text"], "comment_prompt": row["comment_prompt"],
        }
        if row["status"] == "awaiting_qc":
            out["next"] = ("QC is off on this server: do not call submit_qc. Call finish_task; "
                           "the clip waits as awaiting_qc until QC is turned on.")
        return out

    @server.tool(
        description=(
            "Change a clip's title. The old title and the metrics at the moment "
            "of the change are kept, so the next metrics pull reads as "
            "before/after rather than as one blurred number. Works on published "
            "clips; on a manual-driver channel the new title also has to be "
            "typed into Studio, and the result says so. 20-90 characters. Say "
            "why in `why` — it is what the next reviewer reads."
        )
    )
    def retitle(clip_id: str, title: str, why: str) -> dict[str, Any]:
        with db.connect() as conn:
            try:
                out = pipeline.retitle(conn, clip_id, title, by="agent", why=why)
            except ValueError as exc:
                raise ToolError(str(exc)) from None
        logs.event("mcp.call", actor="mcp", tool="retitle", clip=clip_id)
        return out

    @server.tool(
        description=(
            "Score a rendered clip and send it to the review queue, or reject "
            "it.\n\n"
            "looks_templated asks ONE narrow question: would a viewer of THIS "
            "channel feel they had already seen this clip, compared against the "
            "recent_on_this_channel list render_clip gave you? It is not asking "
            "whether the format is common elsewhere on the internet. A marble "
            "race is a well-worn genre and that is fine — set it true only when "
            "this particular clip repeats this channel's own recent output. "
            "Setting it true rejects the clip.\n\n"
            "hook_strength is whether a viewer who did not choose this clip "
            "would keep watching past the first frame, 1 to 5.\n\n"
            "Your judgment is combined with measurements taken here: aspect "
            "ratio, duration, loudness and perceptual similarity to earlier "
            "clips are checked against the file whatever you say, and any "
            "failure rejects it. Be strict on the hook — rejecting a mediocre "
            "clip costs one seed."
        )
    )
    def submit_qc(
        clip_id: str,
        verdict: str,
        hook_strength: int,
        looks_templated: bool,
        policy_risk: str,
        reasons: list[str],
    ) -> dict[str, Any]:
        from pydantic import ValidationError

        from .models import QCVerdict

        try:
            parsed = QCVerdict(
                verdict=verdict, hook_strength=hook_strength,
                looks_templated=looks_templated, policy_risk=policy_risk,
                reasons=reasons,
            )
        except ValidationError as exc:
            raise ToolError(f"verdict rejected: {exc}") from None
        with db.connect() as conn:
            try:
                passed, reason = pipeline.apply_qc(conn, clip_id, parsed)
            except ValueError as exc:
                raise ToolError(str(exc)) from None
        logs.event("mcp.call", actor="mcp", tool="submit_qc", clip=clip_id,
                   passed=passed)
        return {
            "clip": clip_id,
            "status": "awaiting_approval" if passed else "qc_rejected",
            "reason": reason or None,
        }

    @server.tool(
        description=(
            "Clips made while QC was off, waiting to be judged. Look at each "
            "with look_at_clip, then submit_qc — the same verdict as when QC "
            "runs at make time."
        )
    )
    def qc_pending(channel: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
        from .models import AWAITING_QC

        with db.connect() as conn:
            channel_id = resolve_channel_id(conn, channel)
            return [_clip_summary(r) for r in db.by_status(conn, channel_id, AWAITING_QC, limit)]

    @server.tool(
        description=(
            "Four frames of an already rendered clip (the opening, two middle "
            "points and the end) with its measurements — what render_clip "
            "returned when it was made, for judging it later."
        )
    )
    def look_at_clip(clip_id: str) -> list[Any]:
        from mcp.server.mcpserver.utilities.types import Image

        from . import render

        with db.connect() as conn:
            row = db.get(conn, clip_id)
            if row is None:
                raise ToolError(f"no clip {clip_id}")
            video = db.video_file(row)
            if video is None or not video.exists():
                raise ToolError(f"{clip_id} has no file on disk")
            frames = render.sample_frames(video, pipeline.common.sample_times(row["duration_s"]))
            summary = _clip_summary(row)
        return [json.dumps(summary, indent=1, default=str)] + [
            Image(data=f, format="png").to_image_content() for f in frames
        ]

    @server.tool(
        description=(
            "What can be ordered on a channel, for turning an operator's brief "
            "(a list, a plan, a file they gave you) into jobs for enqueue_batch: "
            "the modules and stages, the cast, the season's levels that are ready "
            "and why the others are blocked, the job schema and the limits. Read "
            "the bulk-brief playbook first."
        )
    )
    def batch_options(channel: str | None = None) -> dict[str, Any]:
        from . import batch as bulk, seasons
        from .generators import physics
        from .series import cast as cast_mod, season as season_mod

        with db.connect() as conn:
            ch = channels.resolve(conn, channel)
            modules = generators.available(ch.variants)
            out: dict[str, Any] = {
                "channel": ch.id,
                "modules": [{"generator": g, "variants": v, "about": generators.get(g).blurb}
                            for g, v in modules.items()],
                "stages": [{"id": s, "about": physics.STAGE_BLURB.get(s), "live": s in physics.LIVE_STAGES}
                           for s in sorted(physics.STAGE_BY_ID)],
                "job_schema": bulk.JobSpec.model_json_schema(),
                "limits": {"rows": MCP_BATCH_ROWS, "priority": MCP_BATCH_PRIORITY, "dry_run_default": True},
            }
            cast = cast_mod.load(ch.id)
            if cast:
                out["cast"] = [{"id": e.id, "name": e.name, "bio": e.bio, "debut": e.debut, "scores": e.scores}
                               for e in cast.entrants]
            if season_mod.seasons(ch.id):
                view = seasons.status(conn, ch)
                levels = view.get("levels", [])
                out["season"] = {
                    "id": view.get("season"),
                    "ready": [{"level": lv["id"], "date": lv.get("date"), "world": lv.get("world"),
                               "note": lv.get("note")} for lv in levels if lv.get("status") == "ready"][:40],
                    "blocked": [{"level": lv["id"], "waits_for": lv.get("blocked_on")}
                                for lv in levels if lv.get("status") == "blocked"][:20],
                    "needs_input": [{"level": lv["id"], "fill": lv.get("missing_input")}
                                    for lv in levels if lv.get("status") == "needs_input"],
                    "counts": view.get("counts"),
                }
        return out

    @server.tool(
        description=(
            "Queue many make-clip jobs at once. Each job is either a season level "
            "({level: 'L05'} or a range 'L02..L05') or an ad-hoc clip ({generator, "
            "variant, stage, count, ...}); either may carry `brief` (what the "
            "operator wants, in words) and `hints` ({title, hook, pin, desc}) for "
            "whoever makes it. Dry run by default: call once to see the receipt, "
            "show it to the operator, then again with dry_run=false. All rows or "
            "none unless partial=true. Give every row a `ref` so a retry cannot "
            "queue it twice."
        )
    )
    def enqueue_batch(jobs: list[dict[str, Any]], agent: str = "agent", channel: str | None = None,
                      dry_run: bool = True, partial: bool = False, batch_ref: str | None = None) -> dict[str, Any]:
        from . import batch as bulk

        with db.connect() as conn:
            try:
                ch = channels.resolve(conn, channel)
                ctx = bulk.context(conn, ch, max_priority=MCP_BATCH_PRIORITY)
                receipt = bulk.service(max_rows=MCP_BATCH_ROWS).submit(
                    ctx, bulk.ListSource(jobs, name=f"mcp:{agent_name(agent)}"), by=agent_name(agent),
                    dry_run=dry_run, partial=partial, ref=batch_ref)
            except ValueError as exc:
                raise ToolError(str(exc)) from None
        logs.event("mcp.call", actor="mcp", tool="enqueue_batch", rows=len(jobs), dry_run=dry_run,
                   accepted=receipt.accepted, refused=receipt.refused)
        return receipt.as_dict()

    @server.tool(description="Everything known about one clip.")
    def get_clip(clip_id: str) -> dict[str, Any]:
        with db.connect() as conn:
            row = db.get(conn, clip_id)
            if row is None:
                raise ValueError(f"no clip {clip_id}")
            return _clip_summary(row)

    @server.tool(
        description=(
            "Reject a clip with a reason. Always available: throwing work away "
            "is safe, and the seed can be re-rolled."
        )
    )
    def reject_clip(clip_id: str, reason: str) -> dict[str, str]:
        with db.connect() as conn:
            pipeline.reject(conn, clip_id, reason)
        logs.event("mcp.call", actor="mcp", tool="reject_clip", clip=clip_id, reason=reason)
        return {"clip": clip_id, "status": "qc_rejected"}

    @server.tool(
        description=(
            "Approve a clip for publishing. Refused unless the operator started "
            "this server with --allow-publish."
        )
    )
    def approve_clip(clip_id: str) -> dict[str, str]:
        if not _publishing_allowed():
            logs.event(
                "mcp.refused", level="warn", actor="mcp", tool="approve_clip", clip=clip_id
            )
            raise ToolError(
                "approving is disabled on this server. A human watches the first "
                "second before a clip goes out; that is the point of the gate. "
                "Report what is waiting instead. The operator can restart with "
                "--allow-publish to hand it over."
            )
        with db.connect() as conn:
            pipeline.approve(conn, clip_id)
        logs.event("mcp.call", actor="mcp", tool="approve_clip", clip=clip_id)
        return {"clip": clip_id, "status": "approved"}

    @server.tool(
        description=(
            "Publish every approved clip on a channel. Refused unless the "
            "operator started this server with --allow-publish."
        )
    )
    def publish_approved(channel: str | None = None) -> dict[str, Any]:
        if not _publishing_allowed():
            logs.event("mcp.refused", level="warn", actor="mcp", tool="publish_approved")
            raise ToolError(
                "publishing is disabled on this server. The operator can restart "
                "it with --allow-publish to hand that over."
            )
        with db.connect() as conn:
            ch = channels.resolve(conn, channel)
            outcomes = pipeline.publish_approved(conn, ch)
        logs.event("mcp.call", actor="mcp", tool="publish_approved", channel=ch.id)
        return {
            "channel": ch.id,
            "results": [
                {"clip": o.clip_id, "status": o.status, "detail": o.detail}
                for o in outcomes
            ],
        }

    @server.tool(description="Performance aggregates for a channel, with n on every group.")
    def get_analytics(channel: str | None = None) -> dict[str, Any]:
        with db.connect() as conn:
            ch = channels.resolve(conn, channel)
            return analytics.summary(conn, ch.id)

    @server.tool(description="Record metrics for a published clip, as shown in Studio.")
    def set_metrics(
        clip_id: str,
        views: int,
        avg_view_pct: float,
        swipe_away_pct: float,
        likes: int = 0,
    ) -> dict[str, str]:
        with db.connect() as conn:
            pipeline.set_metrics(
                conn, clip_id, views=views, avg_view_pct=avg_view_pct,
                swipe_away_pct=swipe_away_pct, likes=likes,
            )
        logs.event("mcp.call", actor="mcp", tool="set_metrics", clip=clip_id, views=views)
        return {"clip": clip_id, "status": "recorded"}

    # Lessons from the numbers (factory/feedback.py). An agent may read them
    # and propose one; only the operator adopts a lesson, because an adopted
    # lesson is appended to every playbook and shown to the copy brain.
    # Deleting stays on the console and the CLI.
    @server.tool(
        description=(
            "List the channel's lessons from the numbers: what the metrics showed, the "
            "evidence, linked clips (with their numbers frozen when linked), what to change, "
            "and status (open | testing | adopted | dropped). Newest first. Filter by status, "
            "area (title | hook | caption | stage | length | pacing | skills | other) or clip."
        )
    )
    def list_feedback(channel: str | None = None, status: str | None = None, area: str | None = None,
                      clip: str | None = None, limit: int = 50) -> dict[str, Any]:
        with db.connect() as conn:
            ch = channels.resolve(conn, channel)
            try:
                items, total = feedback.list_(conn, ch.id, status=status, area=area, clip=clip)
            except ValueError as exc:
                raise ToolError(str(exc)) from None
        return {"channel": ch.id, "total": total, "items": items[:max(1, min(limit, 200))]}

    @server.tool(
        description=(
            "Propose a lesson from the numbers. It is recorded as open, source agent: the "
            "operator decides whether to test or adopt it. `observation` is what the numbers "
            "showed (required); `evidence` the metric and values, e.g. 'swipe-away 62% on L03 vs "
            "48% channel median'; `clip_ids` the clips it came from; `action` what to change or test."
        )
    )
    def add_feedback(observation: str, area: str = "other", evidence: str = "",
                     clip_ids: list[str] | None = None, action: str = "",
                     channel: str | None = None, agent: str = "agent") -> dict[str, Any]:
        with db.connect() as conn:
            ch = channels.resolve(conn, channel)
            try:
                out = feedback.create(conn, ch.id, observation=observation, area=area, evidence=evidence,
                                      clip_ids=clip_ids, action=action, status="open", source="agent",
                                      created_by=agent_name(agent))
            except ValueError as exc:
                raise ToolError(str(exc)) from None
        logs.event("mcp.call", actor="mcp", tool="add_feedback", channel=ch.id, id=out["id"])
        return out

    @server.tool(
        description=(
            "Edit a lesson's observation, evidence, action or result, or move it between open "
            "and testing (or drop it). Adopting a lesson is the operator's decision and is refused here."
        )
    )
    def update_feedback(feedback_id: int, observation: str | None = None, evidence: str | None = None,
                        action: str | None = None, result: str | None = None,
                        status: str | None = None) -> dict[str, Any]:
        if status is not None and status.strip().lower() == "adopted":
            raise ToolError("an agent may propose a lesson but not adopt it; the operator adopts on the Feedback screen")
        with db.connect() as conn:
            current = feedback.get(conn, feedback_id)
            if current is None:
                raise ToolError(f"no lesson {feedback_id}")
            if status is not None and current["status"] == "adopted":
                raise ToolError("this lesson is adopted; only the operator changes its status")
            try:
                out = feedback.update(conn, feedback_id, observation=observation, evidence=evidence,
                                      action=action, result=result, status=status)
            except ValueError as exc:
                raise ToolError(str(exc)) from None
        logs.event("mcp.call", actor="mcp", tool="update_feedback", channel=out["channel_id"], id=feedback_id)
        return out

    @server.tool(description="Read a channel's rules file.")
    def read_rules(channel: str | None = None) -> dict[str, str]:
        with db.connect() as conn:
            ch = channels.resolve(conn, channel)
            return {"channel": ch.id, "text": ch.rules()}

    @server.tool(
        description=(
            "Append one rule to a channel's rules file. Prefer proposing a rule "
            "to the human over writing it: rules compound, and a wrong one is "
            "applied to every future clip."
        )
    )
    def append_rule(rule: str, channel: str | None = None) -> dict[str, Any]:
        with db.connect() as conn:
            ch = channels.resolve(conn, channel)
            ch.rules()
            applied = analyst.apply_rules([rule], ch.rules_path)
        logs.event("mcp.call", actor="mcp", tool="append_rule", channel=ch.id, rule=rule)
        return {"channel": ch.id, "applied": applied}

    @server.tool(
        description=(
            "Fetch your own instructions for a task, filled in from the live "
            "database: the channel's rules, what it has made recently, how those "
            "clips performed, and the current hard gates. Call this before "
            "starting work rather than relying on a prompt pasted from an "
            "earlier session, which will be out of date. Omit `name` to list "
            "the playbooks."
        )
    )
    def playbook(name: str | None = None, channel: str | None = None) -> str:
        from . import playbooks

        if name is None:
            return "\n".join(playbooks.available())
        try:
            return playbooks.render(name, channel)
        except ValueError as exc:
            raise ToolError(str(exc)) from None

    @server.tool(
        description=(
            "Claim the next task in the queue and get its full instructions — the "
            "playbook for that kind of task with this task's parameters on top. "
            "Say who you are in `agent` so the queue shows it. Returns task=null "
            "when nothing is waiting. Do the task, then call finish_task. Never "
            "claim a second task before finishing the first."
        )
    )
    def next_task(agent: str = "agent", channel: str | None = None) -> dict[str, Any]:
        from . import tasks

        agent = agent_name(agent)
        with db.connect() as conn:
            row = db.claim_task(conn, agent, channel_id=channel)
            if row is None:
                return {"task": None, "message": "the queue is empty — nothing to do"}
            text = tasks.instructions(conn, row)
            if row["kind"] == "make-clip":
                HELD[row["channel_id"]] = int(row["id"])
            logs.event("task.claimed", channel=row["channel_id"], task=row["id"], kind=row["kind"], by=agent)
            logs.event("mcp.call", actor="mcp", tool="next_task", task=row["id"])
            return {"task": tasks.as_dict(row), "instructions": text}

    @server.tool(
        description=(
            "Report a claimed task done (ok=true, with a one-line summary and the "
            "clip_id if one was made) or not doable (ok=false, with the error). A "
            "task left claimed is released back to the queue after 45 minutes."
        )
    )
    def finish_task(
        task_id: int, ok: bool = True, summary: str = "", clip_id: str | None = None,
        error: str | None = None,
    ) -> dict[str, Any]:
        from . import tasks

        with db.connect() as conn:
            try:
                row = db.finish_task(conn, task_id, ok=ok, result={"summary": summary} if summary else None,
                                     error=error, clip_id=clip_id)
            except ValueError as exc:
                raise ToolError(str(exc)) from None
            if HELD.get(row["channel_id"]) == task_id:
                del HELD[row["channel_id"]]
            logs.event("task.finished", channel=row["channel_id"], task=task_id, kind=row["kind"],
                       status=row["status"], by=row["claimed_by"], error=error)
            logs.event("mcp.call", actor="mcp", tool="finish_task", task=task_id)
            return tasks.as_dict(row)

    @server.tool(description="The task queue: what is waiting, claimed, done or failed.")
    def list_tasks(status: str | None = None, channel: str | None = None) -> list[dict[str, Any]]:
        from . import tasks

        with db.connect() as conn:
            return [tasks.as_dict(r) for r in db.tasks(conn, channel, status)]

    # --- seasons (docs/08): read and build only ------------------------------

    @server.tool(
        description=(
            "Check a channel's season file against its cast and the series rules "
            "(schema, debut order, identity predicates, anti-repetition, dates, "
            "copy-hint placeholders). Returns problems, blocked levels and levels "
            "waiting for operator input."
        )
    )
    def season_check(channel: str | None = None, season: str | None = None) -> dict[str, Any]:
        from . import seasons

        with db.connect() as conn:
            ch = channels.resolve(conn, channel)
            out = seasons.check(conn, ch, season)
        logs.event("mcp.call", actor="mcp", tool="season_check", channel=ch.id)
        return {
            "season": out["season"], "levels": out["levels"],
            "errors": [p.as_dict() for p in out["problems"] if p.severity == "error"],
            "warnings": [p.as_dict() for p in out["problems"] if p.severity == "warning"],
            "blocked": [{"level": i, "blocked_on": why} for i, why in out["blocked"]],
            "needs_input": [{"level": i, "missing": m} for i, m in out["needs_input"]],
        }

    @server.tool(
        description=(
            "Queue make-clip tasks for season levels, e.g. levels=\"L01..L03\" or "
            "\"L03,L05\". Refuses blocked levels, levels waiting for operator "
            "input, levels with season-check errors and levels already planned "
            "(replan=true queues those again). Nothing is rendered here; the "
            "tasks are worked like any other. Same rules as `factory season plan`."
        )
    )
    def season_plan(levels: str, channel: str | None = None, season: str | None = None,
                    replan: bool = False) -> list[dict[str, Any]]:
        from . import seasons

        with db.connect() as conn:
            ch = channels.resolve(conn, channel)
            try:
                out = seasons.plan(conn, ch, levels, season_id=season, replan=replan, by="mcp")
            except (ValueError, KeyError, FileNotFoundError) as exc:
                raise ToolError(str(exc)) from None
        logs.event("mcp.call", actor="mcp", tool="season_plan", channel=ch.id, levels=levels)
        return out

    @server.tool(
        description=(
            "The season table: points, wins and races per entrant, from approved "
            "and published level clips. after=\"L20\" gives the table as it stood "
            "once L20 was counted."
        )
    )
    def get_standings(channel: str | None = None, season: str | None = None,
                      after: str | None = None) -> dict[str, Any]:
        from . import seasons

        with db.connect() as conn:
            ch = channels.resolve(conn, channel)
            try:
                return seasons.standings_view(conn, ch, season, after=after)
            except (ValueError, KeyError, FileNotFoundError) as exc:
                raise ToolError(str(exc)) from None

    @server.tool(
        description=(
            "One season level: its definition from the season file, what became "
            "of it (task, clip, status, failure reason, story attempts, copy "
            "source, points) and the standings before it."
        )
    )
    def get_level(level: str, channel: str | None = None, season: str | None = None) -> dict[str, Any]:
        from . import seasons

        with db.connect() as conn:
            ch = channels.resolve(conn, channel)
            try:
                return seasons.get_level(conn, ch, level, season)
            except (ValueError, KeyError, FileNotFoundError) as exc:
                raise ToolError(str(exc)) from None

    @server.tool(
        description=(
            "For a season level clip: what you may use to write its title, hook "
            "(opening caption), pinned comment and first description line — the "
            "race without its result, the standings before it, the plan's hints, "
            "the cast, recent copy — plus the placeholders each field allows and "
            "the rules submit_copy enforces. Write numbers only as placeholders."
        )
    )
    def propose_copy(clip_id: str) -> dict[str, Any]:
        from .agents import copy as copy_agent
        from .series import copywriter

        with db.connect() as conn:
            row = db.get(conn, clip_id)
            if row is None:
                raise ToolError(f"no clip {clip_id}")
            try:
                s = copywriter.gather(conn, clip_id)
                fb, _ = copywriter.fallback(s)
            except ValueError as exc:
                raise ToolError(str(exc)) from None
            rules = channels.get(conn, row["channel_id"]).rules()
        logs.event("mcp.call", actor="mcp", tool="propose_copy", clip=clip_id)
        return {"clip": clip_id, "inputs": copywriter.inputs(s, rules),
                "rules": copy_agent.SYSTEM, "fallback": fb}

    @server.tool(
        description=(
            "Store copy for a season level clip, through the same validator the "
            "copy brain is held to. All four fields must pass or nothing is "
            "applied and the reasons come back. An empty hook keeps the render's "
            "caption; a hook is recorded, never burned here."
        )
    )
    def submit_copy(clip_id: str, title: str, hook: str, pin: str, desc_line1: str) -> dict[str, Any]:
        from .series import copywriter

        with db.connect() as conn:
            try:
                out = copywriter.submit(conn, clip_id, {"title": title, "hook": hook, "pin": pin,
                                                        "desc_line1": desc_line1}, by="agent")
            except ValueError as exc:
                raise ToolError(str(exc)) from None
        logs.event("mcp.call", actor="mcp", tool="submit_copy", clip=clip_id, applied=out["applied"])
        return out

    @server.tool(description="Recent pipeline events, newest first.")
    def recent_logs(
        limit: int = 50,
        channel: str | None = None,
        level: str | None = None,
        event: str | None = None,
    ) -> list[dict[str, Any]]:
        return logs.read(limit=limit, channel=channel, level=level, event_name=event)

    return server


def serve(allow_publish: bool = False) -> None:
    if allow_publish:
        os.environ[ALLOW_PUBLISH_ENV] = "1"
    os.environ.setdefault("FACTORY_ACTOR", "mcp")
    logs.event("mcp.started", actor="mcp", allow_publish=allow_publish)
    build_server().run(transport="stdio")
