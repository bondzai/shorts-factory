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

from . import analytics, channels, db, generators, llm, logs, pipeline
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
    ) -> list[Any]:
        from mcp.server.mcpserver.utilities.types import Image

        with db.connect() as conn:
            try:
                clip_id, frames, facts = pipeline.create_and_render(
                    conn, channel, variant=variant, generator=generator,
                    seed=seed, hook=hook,
                )
            except (ValueError, KeyError) as exc:
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
        return {
            "clip": clip_id, "status": row["status"], "title": meta.title,
            "hook_text": row["hook_text"], "comment_prompt": row["comment_prompt"],
        }

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
