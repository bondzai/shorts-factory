"""The team, as its manager sees it.

Every other screen is one channel and one kind of thing: clips, tasks, events.
This is the view across all of it — who is working right now, on what, how
far along, and what each of them got done today — read off the tables that
already exist. Nothing new is recorded; an agent that vanished is simply one
whose last task is old.

A member is anything that has ever claimed a task (an agent over MCP by the
name it gave `next_task`, or the built-in worker) plus you, whose work is the
deciding. The feed is the event log filtered to the lines a manager would
want read out loud.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any

from . import channels, db, logs, tasks
from .models import APPROVED, AWAITING_APPROVAL, PUBLISHED, QC_REJECTED

IDLE_AFTER = timedelta(minutes=30)      # no task held and nothing done: idle
AWAY_AFTER = timedelta(hours=12)        # nothing for half a day: away
ROSTER_DAYS = 14                        # a name unseen this long drops off

FEED_EVENTS = {
    "task.queued", "task.claimed", "task.finished", "clip.rendered", "clip.described",
    "clip.qc", "clip.approved", "clip.rejected", "clip.published", "clip.failed", "clip.retitled",
    "clip.binned", "notify.daily", "telegram.started", "worker.started", "worker.exited", "worker.failed",
}


def _parse(iso: str | None) -> datetime | None:
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _state(held: bool, last_seen: datetime | None, now: datetime) -> str:
    if held:
        return "working"
    if last_seen is None or now - last_seen > AWAY_AFTER:
        return "away"
    if now - last_seen > IDLE_AFTER:
        return "idle"
    return "ready"


def describe(e: dict[str, Any], names: dict[str, str] | None = None) -> str:
    """One spoken line per event, for the feed. `names` maps a clip id to the
    agent whose task it is, so a step the pipeline stamped as "agent" is read
    with the name that claimed the work."""
    f = e
    who = f.get("by") or ("an agent" if f.get("actor") == "mcp" else "you")
    if who in ("agent", "an agent") and names and f.get("clip") in names:
        who = names[f["clip"]]
    clip = (f.get("clip") or "")[:6]
    name = f.get("event")
    if name == "task.queued":
        n = f.get("count") or 1
        return f"{who} queued {n} {f.get('kind')} task{'s' if n != 1 else ''}"
    if name == "task.claimed":
        return f"{who} picked up #{f.get('task')} {f.get('kind')}"
    if name == "task.finished":
        return f"{who} finished #{f.get('task')}" + ("" if f.get("status") == "done" else f" — FAILED: {f.get('error') or ''}")
    if name == "clip.rendered":
        return f"{who} rendered {clip}" + (f" ({float(f['duration_s']):.1f}s)" if f.get("duration_s") else "")
    if name == "clip.described":
        return f"{who} titled {clip}: “{(f.get('title') or '')[:60]}”"
    if name == "clip.qc":
        return f"{who} passed {clip} in QC" if f.get("passed") else f"{who} rejected {clip} in QC"
    if name == "clip.approved":
        return f"you approved {clip}"
    if name == "clip.rejected":
        return f"you rejected {clip}" + (f" — {f.get('reason')}" if f.get("reason") else "")
    if name == "clip.published":
        return f"published {clip}: {(f.get('title') or '')[:60]}"
    if name == "clip.failed":
        return f"{clip} FAILED at {f.get('stage')}: {f.get('error')}"
    if name == "clip.retitled":
        return f"{who} retitled {clip}"
    if name == "clip.binned":
        return f"you binned {clip}"
    if name == "notify.daily":
        return "daily upload reminder sent"
    if name == "telegram.started":
        return "Telegram bot is listening"
    if name == "worker.started":
        return f"{f.get('agent')} worker started on {f.get('channel')} (run {f.get('run')})"
    if name == "worker.exited":
        return f"{f.get('agent')} worker on {f.get('channel')} finished" + ("" if not f.get("code") else f" with exit code {f.get('code')}")
    if name == "worker.failed":
        return f"could not start {f.get('agent')} on {f.get('channel')}: {f.get('error')}"
    return name or ""


def overview(conn: sqlite3.Connection, *, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    since = (now - timedelta(days=ROSTER_DAYS)).isoformat()
    day_start = now.astimezone(_local_tz()).replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc).isoformat()

    rows = conn.execute(
        """SELECT t.*, c.status AS clip_status, c.cost_usd AS clip_cost, c.title AS clip_title
           FROM tasks t LEFT JOIN clips c ON c.id = t.clip_id
           WHERE t.claimed_by IS NOT NULL AND COALESCE(t.finished_at, t.claimed_at) >= ?
           ORDER BY COALESCE(t.finished_at, t.claimed_at) DESC, t.id DESC""",
        (since,),
    ).fetchall()

    members: dict[str, dict[str, Any]] = {}
    clip_owner = {r["clip_id"]: r["claimed_by"] for r in rows if r["clip_id"]}
    for r in rows:
        m = members.setdefault(r["claimed_by"], {
            "name": r["claimed_by"], "kind": "builtin" if r["claimed_by"] == "factory-work" else "agent",
            "task": None, "tasks": [], "last_seen": None, "channels": set(),
            "today": {"done": 0, "failed": 0, "clips": 0, "passed_qc": 0, "rejected_qc": 0, "cost_usd": 0.0},
            "recent": [],
        })
        seen = _parse(r["finished_at"]) or _parse(r["claimed_at"])
        if seen and (m["last_seen"] is None or seen > m["last_seen"]):
            m["last_seen"] = seen
        m["channels"].add(r["channel_id"])
        if r["status"] == "claimed":
            # Two sessions of the same tool are one member holding two tasks
            # — a worker per channel is the normal way to run in parallel.
            held = tasks.as_dict(r)
            m["tasks"].append(held)
            if m["task"] is None:
                m["task"] = held
        else:
            if len(m["recent"]) < 6:
                result = json.loads(r["result_json"]) if r["result_json"] else {}
                m["recent"].append({
                    "id": r["id"], "kind": r["kind"], "channel_id": r["channel_id"], "status": r["status"],
                    "finished_at": r["finished_at"], "clip_id": r["clip_id"], "title": r["clip_title"],
                    "summary": (result or {}).get("summary") or r["error"] or "",
                })
            if (r["finished_at"] or "") >= day_start:
                t = m["today"]
                t["done" if r["status"] == "done" else "failed"] += 1
                if r["clip_id"]:
                    t["clips"] += 1
                    t["cost_usd"] += float(r["clip_cost"] or 0)
                    if r["clip_status"] in (AWAITING_APPROVAL, APPROVED, PUBLISHED):
                        t["passed_qc"] += 1
                    elif r["clip_status"] == QC_REJECTED:
                        t["rejected_qc"] += 1

    out_members = []
    for m in members.values():
        task = m["task"]
        m["tasks"].sort(key=lambda t: t["claimed_at"] or "")
        for held in m["tasks"]:
            current = next((s for s in held["steps"] if s["state"] == "current"), None)
            done_steps = len([s for s in held["steps"] if s["state"] == "done"])
            held["doing"] = (f"#{held['id']} {held['kind']} on {held['channel_id']} — at {current['name'] if current else '…'}, "
                             f"step {done_steps + 1} of {len(held['steps'])}")
        out_members.append({
            **m,
            "channels": sorted(m["channels"]),
            "last_seen": m["last_seen"].isoformat() if m["last_seen"] else None,
            "state": _state(task is not None, m["last_seen"], now),
            "doing": m["tasks"][0]["doing"] if m["tasks"] else None,
            "today": {**m["today"], "cost_usd": round(m["today"]["cost_usd"], 4)},
        })
    order = {"working": 0, "ready": 1, "idle": 2, "away": 3}
    out_members.sort(key=lambda m: (order[m["state"]], m["name"]))

    # You: the deciding. What waits, and what you settled today.
    waiting = conn.execute("SELECT COUNT(*) FROM clips WHERE status = ? AND deleted_at IS NULL", (AWAITING_APPROVAL,)).fetchone()[0]
    to_upload = conn.execute("SELECT COUNT(*) FROM clips WHERE status = ? AND deleted_at IS NULL", (APPROVED,)).fetchone()[0]
    events = logs.read(limit=600, days=2)
    decided_today = [e for e in events if e.get("event") in ("clip.approved", "clip.rejected", "clip.published")
                     and e.get("actor") != "mcp" and (e.get("at") or "") >= day_start]
    you = {
        "name": "you", "kind": "you", "state": "needed" if waiting else "clear",
        "waiting": waiting, "to_upload": to_upload,
        "today": {
            "approved": len([e for e in decided_today if e["event"] == "clip.approved"]),
            "rejected": len([e for e in decided_today if e["event"] == "clip.rejected"]),
            "published": len([e for e in decided_today if e["event"] == "clip.published"]),
        },
    }

    chans = []
    for ch in channels.all_channels(conn):
        _, _, phases = db.work(conn, ch.id, page=1, page_size=1)
        chans.append({"id": ch.id, "name": ch.name, "active": ch.active, "phases": phases,
                      "spend_usd": round(db.spend(conn, ch.id), 4)})

    feed = [{"at": e["at"], "event": e["event"], "channel": e.get("channel"), "clip": e.get("clip"),
             "level": e.get("level"), "line": describe(e, clip_owner)}
            for e in events if e.get("event") in FEED_EVENTS][:40]

    queued = conn.execute("SELECT COUNT(*) FROM tasks WHERE status = 'queued'").fetchone()[0]
    return {
        "at": now.isoformat(),
        "members": out_members,
        "you": you,
        "channels": chans,
        "feed": feed,
        "totals": {
            "working": sum(len(m["tasks"]) for m in out_members),
            "queued": queued, "to_decide": waiting, "to_upload": to_upload,
        },
    }


def _local_tz():
    from . import schedule
    return schedule.timezone()
