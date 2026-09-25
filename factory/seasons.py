"""The series layer as the surfaces use it: `factory season …` and the MCP
season tools call these, so the two cannot disagree.

This is where the generator layer's knowledge (the physics stage ids) meets
the series package, which never imports a generator itself.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from . import db, settings
from .channels import Channel
from .series import cast as cast_mod, check as check_mod, planning, season as season_mod, standings


def known_stages() -> set[str]:
    from .generators.physics import STAGE_BY_ID

    return set(STAGE_BY_ID)


def redraw(meta: dict, trace_dir, raw: bool = False):
    """A trace's frames from the generator that wrote it (long-form's Redraw).
    `raw`: the race without the short's presentation (camera, slow-mo, HUD),
    for a generator that has one."""
    from . import generators

    gen = generators.get(meta["generator"])
    if not hasattr(gen, "redraw"):
        raise ValueError(f"generator {meta['generator']!r} cannot redraw from a trace")
    if raw and "presentation" in meta:
        return gen.redraw(trace_dir, raw=True)
    return gen.redraw(trace_dir)


def load(ch: Channel, season_id: str | None = None):
    """(season, cast) for a channel."""
    return season_mod.load(ch.id, season_id), cast_mod.load(ch.id)


def check(conn: sqlite3.Connection, ch: Channel, season_id: str | None = None) -> dict[str, Any]:
    """Problems and blocked levels. A file that does not load is one error."""
    try:
        season, cast = load(ch, season_id)
    except Exception as exc:  # yaml, pydantic, toml, missing file: all the same to the reader
        return {"season": season_id, "problems": [check_mod.Problem(None, "error", str(exc))],
                "blocked": [], "needs_input": [], "levels": 0, "season_obj": None, "cast": None}
    allow = bool(settings.load().raw.get("series", {}).get("allow_identity_constraints", False))
    problems = check_mod.check(season, cast, stages=known_stages(), allow_identity=allow,
                               channel_variants=ch.variants)
    planning.register(conn, season)
    return {
        "season": season.id, "problems": problems, "levels": len(season.levels),
        "blocked": [(lv.id, lv.blocked_on) for lv in season.levels if lv.status == "blocked"],
        "needs_input": [(lv.id, lv.missing_input()) for lv in season.levels if lv.status == "needs_input"],
        "season_obj": season, "cast": cast,
    }


def plan(conn: sqlite3.Connection, ch: Channel, levels: str, *, season_id: str | None = None,
         replan: bool = False, by: str = "human") -> list[dict[str, Any]]:
    checked = check(conn, ch, season_id)
    season = checked["season_obj"]
    if season is None:
        raise ValueError(f"season file does not load: {checked['problems'][0].message}")
    return planning.plan(conn, ch, season, planning.parse_levels(levels), checked["cast"],
                         problems=checked["problems"], replan=replan, by=by)


def season_id_for(ch: Channel, season_id: str | None) -> str:
    if season_id:
        return season_id
    return season_mod.load(ch.id).id


def level_view(conn: sqlite3.Connection, ch: Channel, level, season_id: str) -> dict[str, Any]:
    """A level with what became of it: its row, its clip, its result."""
    row = planning.level_row(conn, ch.id, season_id, level.id)
    out: dict[str, Any] = {
        "id": level.id, "date": level.date.isoformat(), "world": level.world,
        "file_status": level.status, "blocked_on": level.blocked_on,
        "missing_input": level.missing_input(), "note": level.note,
        "status": row["status"] if row else level.status,
        "reason": row["reason"] if row else None,
        "task_id": row["task_id"] if row else None,
        "clip_id": row["clip_id"] if row else None,
        "clip_status": None, "story_attempts": None, "copy_source": None, "points": None,
    }
    clip = db.get(conn, row["clip_id"]) if row and row["clip_id"] else None
    if clip is not None:
        facts = json.loads(clip["facts_json"] or "{}")
        out.update(clip_status=clip["status"] + (" (binned)" if clip["deleted_at"] else ""),
                   story_attempts=facts.get("story_attempts"), copy_source=facts.get("copy_source"),
                   title=clip["title"])
    res = conn.execute("SELECT points_json FROM results WHERE channel_id = ? AND season_id = ? AND level_id = ?",
                       (ch.id, season_id, level.id)).fetchone()
    if res:
        out["points"] = json.loads(res["points_json"])
    return out


def status(conn: sqlite3.Connection, ch: Channel, season_id: str | None = None) -> dict[str, Any]:
    season = season_mod.load(ch.id, season_id)
    levels = [level_view(conn, ch, lv, season.id) for lv in season.levels]
    counts: dict[str, int] = {}
    for lv in levels:
        key = lv["clip_status"] or lv["status"]
        counts[key] = counts.get(key, 0) + 1
    copy: dict[str, int] = {}
    for lv in levels:
        if lv["copy_source"]:
            copy[lv["copy_source"]] = copy.get(lv["copy_source"], 0) + 1
    return {"season": season.id, "title": season.title, "levels": levels, "counts": counts,
            "copy_sources": copy}


def standings_view(conn: sqlite3.Connection, ch: Channel, season_id: str | None = None, *,
                   after: str | None = None, recompute: bool = False) -> dict[str, Any]:
    """The table; `after` L20 means including L20 (before L21)."""
    sid = season_id_for(ch, season_id)
    if recompute:
        standings.recompute(conn, ch.id, sid)
    before = None
    if after:
        before = f"L{cast_mod.level_number(after) + 1:0{len(after) - 1}d}"
    return {"season": sid, "after": after, "table": standings.table(conn, ch.id, sid, before_level=before)}


def get_level(conn: sqlite3.Connection, ch: Channel, level_id: str, season_id: str | None = None) -> dict[str, Any]:
    season = season_mod.load(ch.id, season_id)
    level = season.level(level_id)
    return {"season": season.id, "definition": level.model_dump(mode="json", by_alias=True),
            **level_view(conn, ch, level, season.id),
            "standings_before": standings.table(conn, ch.id, season.id, before_level=level_id)}
