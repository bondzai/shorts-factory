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

import os
from typing import Any

from . import analytics, channels, db, generators, logs, pipeline
from .agents import analyst
from .models import AWAITING_APPROVAL

ALLOW_PUBLISH_ENV = "FACTORY_MCP_ALLOW_PUBLISH"


def _publishing_allowed() -> bool:
    return os.environ.get(ALLOW_PUBLISH_ENV, "").lower() in {"1", "true", "yes"}


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

    @server.tool(
        description=(
            "Ask the Idea agent for new clip plans on a channel. Costs a few "
            "cents. Nothing is rendered yet."
        )
    )
    def plan_clips(count: int = 1, channel: str | None = None) -> dict[str, Any]:
        if count < 1 or count > 10:
            raise ValueError("count must be between 1 and 10")
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
