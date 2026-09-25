"""The feedback loop: what the numbers taught this channel.

The operator reads YouTube Studio by hand. Numbers typed into a clip row say
what happened; they do not say what to do about it, and the Analyst's rules
need thirty published clips before it will speak. A lesson is the step in
between: one observation ("the caption that names a colour gets swiped
away"), the evidence behind it, the clips it came from, what to change, and
whether that change is being tried, was kept, or was dropped.

Only an adopted lesson travels. It is appended to every rendered playbook
(beside the operator's Directions) and handed to the copy and title brains —
so a hunch recorded on a Tuesday never becomes a rule by accident, and a rule
that earned its place is never forgotten by the next session.

The linked clips' numbers are copied into the lesson when they are linked.
Metrics are overwritten when Studio is read again next week; the evidence a
lesson was adopted on should not move under it.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from . import db

SOURCES = ("manual", "analyst", "agent")
AREAS = ("title", "hook", "caption", "stage", "length", "pacing", "skills", "other")
STATUSES = ("open", "testing", "adopted", "dropped")
# The areas the copy and title brains are shown: the words on and around a clip.
COPY_AREAS = ("title", "hook", "caption")
TEXT_FIELDS = ("observation", "evidence", "action", "result")
EDITABLE = (*TEXT_FIELDS, "area", "status", "source", "clip_ids")
MAX_TEXT = 4000
MAX_CLIPS = 50

AREA_WORDS = {
    "title": "Titles", "hook": "Hooks", "caption": "Captions", "stage": "Stages",
    "length": "Length", "pacing": "Pacing", "skills": "Skills", "other": "Other",
}


def _choice(field: str, value: Any, allowed: tuple[str, ...]) -> str:
    v = str(value or "").strip().lower()
    if v not in allowed:
        raise ValueError(f"{field} must be one of {', '.join(allowed)}; got {value!r}")
    return v


def _text(field: str, value: Any, *, required: bool = False) -> str:
    v = "" if value is None else str(value).strip()
    if required and not v:
        raise ValueError(f"{field} is required: say what the numbers showed")
    if len(v) > MAX_TEXT:
        raise ValueError(f"{field} is {len(v)} characters; keep it under {MAX_TEXT}")
    return v


def _clip_ids(conn: sqlite3.Connection, channel_id: str, value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        value = [v for v in value.replace(",", " ").split()]
    if not isinstance(value, (list, tuple)):
        raise ValueError("clip_ids must be a list of clip ids")
    ids = list(dict.fromkeys(str(v).strip() for v in value if str(v).strip()))
    if len(ids) > MAX_CLIPS:
        raise ValueError(f"at most {MAX_CLIPS} clips per lesson; got {len(ids)}")
    for cid in ids:
        row = db.get(conn, cid)
        if row is None:
            raise ValueError(f"no clip {cid}")
        if row["channel_id"] != channel_id:
            raise ValueError(f"clip {cid} is on channel {row['channel_id']}, not {channel_id}")
    return ids


def _stage(facts: dict[str, Any]) -> str | None:
    rounds = facts.get("rounds") or []
    return (rounds[0].get("stage") if rounds else None) or facts.get("stage") or facts.get("course")


def snapshot(conn: sqlite3.Connection, clip_ids: list[str]) -> dict[str, dict[str, Any]]:
    """Each clip's numbers and words as they stand now, keyed by clip id.
    Clips that do not exist are skipped, not invented."""
    out: dict[str, dict[str, Any]] = {}
    for cid in clip_ids:
        row = db.get(conn, cid)
        if row is None:
            continue
        facts = json.loads(row["facts_json"] or "{}")
        out[cid] = {
            "title": row["title"],
            "hook_text": row["hook_text"],
            "level_id": row["level_id"],
            "variant": row["variant"],
            "stage": _stage(facts),
            "status": row["status"],
            "views": row["views"],
            "avg_view_pct": row["avg_view_pct"],
            "swipe_away_pct": row["swipe_away_pct"],
            "likes": row["likes"],
            "metrics_at": row["metrics_at"],
            "taken_at": db.now(),
        }
    return out


def as_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "channel_id": row["channel_id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "created_by": row["created_by"],
        "source": row["source"],
        "area": row["area"],
        "observation": row["observation"],
        "evidence": row["evidence"],
        "clip_ids": json.loads(row["clip_ids"] or "[]"),
        "action": row["action"],
        "status": row["status"],
        "result": row["result"],
        "metrics": json.loads(row["metrics_json"] or "{}"),
    }


def get(conn: sqlite3.Connection, feedback_id: int) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM feedback WHERE id = ?", (int(feedback_id),)).fetchone()
    return as_dict(row) if row else None


def create(
    conn: sqlite3.Connection,
    channel_id: str,
    *,
    observation: str,
    area: str = "other",
    evidence: str = "",
    clip_ids: list[str] | None = None,
    action: str = "",
    status: str = "open",
    result: str = "",
    source: str = "manual",
    created_by: str | None = None,
) -> dict[str, Any]:
    observation = _text("observation", observation, required=True)
    area = _choice("area", area, AREAS)
    status = _choice("status", status, STATUSES)
    source = _choice("source", source, SOURCES)
    ids = _clip_ids(conn, channel_id, clip_ids)
    now = db.now()
    cur = conn.execute(
        """INSERT INTO feedback (channel_id, created_at, updated_at, created_by, source, area,
               observation, evidence, clip_ids, action, status, result, metrics_json)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (channel_id, now, now, created_by, source, area, observation,
         _text("evidence", evidence), json.dumps(ids), _text("action", action), status,
         _text("result", result), json.dumps(snapshot(conn, ids))),
    )
    conn.commit()
    return get(conn, cur.lastrowid)  # type: ignore[return-value]


def update(conn: sqlite3.Connection, feedback_id: int, **fields: Any) -> dict[str, Any]:
    """Change any field. Status moves freely (a dropped lesson can come back).
    A clip newly linked is snapshotted now; one already linked keeps the
    numbers it had when it was linked; one unlinked loses its snapshot."""
    current = get(conn, feedback_id)
    if current is None:
        raise ValueError(f"no lesson {feedback_id}")
    unknown = set(fields) - set(EDITABLE)
    if unknown:
        raise ValueError(f"cannot change {', '.join(sorted(unknown))}; editable: {', '.join(EDITABLE)}")
    sets: dict[str, Any] = {}
    for key, value in fields.items():
        if value is None:
            continue
        if key == "observation":
            sets[key] = _text(key, value, required=True)
        elif key in TEXT_FIELDS:
            sets[key] = _text(key, value)
        elif key == "area":
            sets[key] = _choice(key, value, AREAS)
        elif key == "status":
            sets[key] = _choice(key, value, STATUSES)
        elif key == "source":
            sets[key] = _choice(key, value, SOURCES)
        elif key == "clip_ids":
            ids = _clip_ids(conn, current["channel_id"], value)
            kept = {cid: snap for cid, snap in current["metrics"].items() if cid in ids}
            kept.update(snapshot(conn, [cid for cid in ids if cid not in kept]))
            sets["clip_ids"] = json.dumps(ids)
            sets["metrics_json"] = json.dumps({cid: kept[cid] for cid in ids if cid in kept})
    if sets:
        sets["updated_at"] = db.now()
        conn.execute(
            f"UPDATE feedback SET {', '.join(f'{k} = ?' for k in sets)} WHERE id = ?",
            [*sets.values(), int(feedback_id)],
        )
        conn.commit()
    return get(conn, feedback_id)  # type: ignore[return-value]


def delete(conn: sqlite3.Connection, feedback_id: int) -> bool:
    cur = conn.execute("DELETE FROM feedback WHERE id = ?", (int(feedback_id),))
    conn.commit()
    return cur.rowcount > 0


def list_(
    conn: sqlite3.Connection,
    channel_id: str,
    *,
    status: str | None = None,
    area: str | None = None,
    clip: str | None = None,
    query: str | None = None,
    page: int | None = None,
    page_size: int | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """Newest first. (items, total); without a page, every match."""
    sql = "SELECT * FROM feedback WHERE channel_id = ?"
    args: list[Any] = [channel_id]
    if status:
        sql += " AND status = ?"
        args.append(_choice("status", status, STATUSES))
    if area:
        sql += " AND area = ?"
        args.append(_choice("area", area, AREAS))
    if clip:
        sql += " AND EXISTS (SELECT 1 FROM json_each(feedback.clip_ids) WHERE value = ?)"
        args.append(clip)
    if query:
        sql += " AND (observation LIKE ? OR evidence LIKE ? OR action LIKE ? OR result LIKE ?)"
        args.extend([f"%{query}%"] * 4)
    total = conn.execute(sql.replace("SELECT *", "SELECT COUNT(*)", 1), args).fetchone()[0]
    sql += " ORDER BY created_at DESC, id DESC"
    if page is not None:
        p, size = db.page_args(page, page_size)
        sql += " LIMIT ? OFFSET ?"
        args.extend([size, (p - 1) * size])
    return [as_dict(r) for r in conn.execute(sql, args).fetchall()], total


def counts(conn: sqlite3.Connection, channel_id: str) -> dict[str, int]:
    rows = conn.execute(
        "SELECT status, COUNT(*) n FROM feedback WHERE channel_id = ? GROUP BY status", (channel_id,)
    ).fetchall()
    found = {r["status"]: r["n"] for r in rows}
    return {s: found.get(s, 0) for s in STATUSES}


def adopted(conn: sqlite3.Connection, channel_id: str, areas: tuple[str, ...] | None = None) -> list[dict[str, Any]]:
    items, _ = list_(conn, channel_id, status="adopted")
    return [i for i in items if areas is None or i["area"] in areas]


def adopted_text(conn: sqlite3.Connection, channel_id: str, areas: tuple[str, ...] | None = None) -> str:
    """Adopted lessons as a short markdown block, grouped by area; "" when
    there are none. Open, testing and dropped lessons never appear."""
    items = adopted(conn, channel_id, areas)
    if not items:
        return ""
    lines = ["", "## What the numbers taught this channel", "",
             "Lessons the operator adopted after reading the channel's numbers. "
             "Follow them unless the facts of this clip make one impossible.", ""]
    for area in AREAS:
        group = [i for i in items if i["area"] == area]
        if not group:
            continue
        lines.append(f"**{AREA_WORDS[area]}.**")
        for i in reversed(group):  # oldest first within an area: the order they were learned
            line = f"- {i['action'] or i['observation']}"
            if i["action"]:
                line += f" (because: {i['observation']}"
                line += f"; {i['evidence']})" if i["evidence"] else ")"
            elif i["evidence"]:
                line += f" ({i['evidence']})"
            lines.append(line)
        lines.append("")
    return "\n".join(lines)
