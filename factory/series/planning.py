"""`season plan`: season levels into make-clip tasks, and the `levels` rows
that say what became of each.

A level's task carries everything the generator needs to build it without the
season file: generator, variant, the level's params, the cast in the level's
entrant order, the story, and the ids that tie the clip back to the level.
No Idea agent is involved: the season file is the plan.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from .. import db, logs
from .cast import Cast, level_number
from .check import Problem
from .season import Level, Season, directory

#: Level statuses in the `levels` table.
PLANNED, RENDERED, FAILED = "planned", "rendered", "failed"
#: Keys a level's params may carry into a make-clip task. Mirrors the task
#: kind's parameters (tasks.KINDS) without importing the task layer.
PARAM_KEYS = frozenset({"stage", "section", "rounds", "background", "max_story_attempts", "prefer_pool"})


def parse_levels(text: str) -> list[str]:
    """"L01..L10", "L03,L05" or a mix ("L01..L03,L07") into level ids, in order."""
    out: list[str] = []
    for part in (p.strip() for p in text.split(",")):
        if not part:
            continue
        if ".." in part:
            a, b = (s.strip() for s in part.split("..", 1))
            lo, hi = level_number(a), level_number(b)
            if hi < lo:
                raise ValueError(f"{part}: the range runs backwards")
            width = len(a) - 1
            out += [f"L{n:0{width}d}" for n in range(lo, hi + 1)]
        else:
            level_number(part)  # raises with the reason
            out.append(part)
    if not out:
        raise ValueError(f"no levels in {text!r}")
    return list(dict.fromkeys(out))


def register(conn: sqlite3.Connection, season: Season) -> None:
    """Record the season in `seasons` (on check and on plan)."""
    conn.execute(
        "INSERT OR REPLACE INTO seasons (channel_id, id, title, file) VALUES (?, ?, ?, ?)",
        (season.channel, season.id, season.title, str(directory(season.channel) / f"{season.id}.yaml")),
    )
    conn.commit()


def level_row(conn: sqlite3.Connection, channel_id: str, season_id: str, level_id: str):
    return conn.execute(
        "SELECT * FROM levels WHERE channel_id = ? AND season_id = ? AND id = ?",
        (channel_id, season_id, level_id),
    ).fetchone()


def task_params(level: Level, season: Season, cast: Cast | None) -> dict[str, Any]:
    params: dict[str, Any] = {"generator": level.generator, "variant": level.variant, **level.params}
    if level.entrants:
        if cast is None:
            raise ValueError("the level names entrants and the channel has no cast.toml")
        params["cast"] = [
            {"id": e.id, "name": e.name, "color": e.color, "traits": dict(e.traits)}
            for e in (cast.get(who) for who in level.entrants)
        ]
    params["story"] = {"must": dict(level.story.must), "prefer": dict(level.story.prefer)}
    params.update(level_id=level.id, season_id=season.id, format=level.format)
    return params


def refusal(conn: sqlite3.Connection, season: Season, level: Level, *, replan: bool,
            problems: list[Problem]) -> str | None:
    """Why this level may not be planned now, or None."""
    if level.status == "blocked":
        return f"blocked: {level.blocked_on or 'no reason given'}"
    if level.status == "needs_input" or level.missing_input():
        return f"needs operator input: {', '.join(level.missing_input()) or 'see the season file'}"
    mine = [p.message for p in problems if p.severity == "error" and p.level_id in (None, level.id)]
    if mine:
        return f"season check: {mine[0]}" + (f" (+{len(mine) - 1} more)" if len(mine) > 1 else "")
    extra = sorted(set(level.params) - PARAM_KEYS)
    if extra:
        return f"params {extra} are not carried by a make-clip task"
    row = level_row(conn, season.channel, season.id, level.id)
    if row is not None and row["status"] != FAILED and not replan:
        where = f"clip {row['clip_id']}" if row["clip_id"] else f"task #{row['task_id']}"
        return f"already {row['status']} ({where}); --replan to queue it again"
    return None


def plan(
    conn: sqlite3.Connection,
    channel,
    season: Season,
    level_ids: list[str],
    cast: Cast | None,
    *,
    problems: list[Problem] | None = None,
    replan: bool = False,
    by: str = "human",
) -> list[dict[str, Any]]:
    """Queue one make-clip task per plannable level; say why for the rest.

    `channel` is the Channel the season belongs to; `problems` is the output
    of `check.check` for this season, so a level with errors is refused.
    Returns one dict per level: {level, queued, task_id, reason}.
    """
    if season.channel != channel.id:
        raise ValueError(f"season {season.id} belongs to {season.channel}, not {channel.id}")
    unknown = [i for i in level_ids if i not in {lv.id for lv in season.levels}]
    if unknown:
        raise ValueError(f"no level {', '.join(unknown)} in season {season.id}")
    register(conn, season)
    out: list[dict[str, Any]] = []
    for level_id in level_ids:
        level = season.level(level_id)
        reason = refusal(conn, season, level, replan=replan, problems=problems or [])
        if reason is None and not channel.allows(level.generator, level.variant):
            reason = f"{channel.id} does not allow {level.generator}/{level.variant}"
        if reason is None:
            try:
                params = task_params(level, season, cast)
            except (KeyError, ValueError) as exc:
                reason = str(exc)
        if reason is not None:
            out.append({"level": level_id, "queued": False, "task_id": None, "reason": reason})
            continue
        old = level_row(conn, channel.id, season.id, level_id)
        if old is not None and old["task_id"]:
            # A replan supersedes a task nobody has started.
            conn.execute("UPDATE tasks SET status = 'cancelled', finished_at = ? WHERE id = ? "
                         "AND status = 'queued'", (db.now(), old["task_id"]))
        task_id = db.enqueue_task(conn, channel.id, "make-clip", params, by=by)
        conn.execute(
            """INSERT OR REPLACE INTO levels (channel_id, season_id, id, date, clip_id, task_id, status, reason)
               VALUES (?, ?, ?, ?, NULL, ?, ?, NULL)""",
            (channel.id, season.id, level_id, level.date.isoformat(), task_id, PLANNED),
        )
        conn.commit()
        logs.event("task.queued", channel=channel.id, kind="make-clip", count=1, by=by,
                   params={k: v for k, v in params.items() if k != "cast"}, level=level_id,
                   season=season.id)
        out.append({"level": level_id, "queued": True, "task_id": task_id, "reason": None})
    return out


def _level_ids(params: dict[str, Any]) -> tuple[str, str] | None:
    level_id, season_id = params.get("level_id"), params.get("season_id")
    return (season_id, level_id) if level_id and season_id else None


def mark(conn: sqlite3.Connection, channel_id: str, params: dict[str, Any] | str | None,
         clip_id: str, status: str, reason: str | None = None) -> bool:
    """Tie a level clip's render (or its failure) to the level row.

    A no-op for a clip that is not a season level. The row is created if the
    task was queued some other way (an agent passing level ids itself).
    """
    if isinstance(params, str):
        params = json.loads(params or "{}")
    ids = _level_ids(params or {})
    if ids is None:
        return False
    season_id, level_id = ids
    if level_row(conn, channel_id, season_id, level_id) is None:
        conn.execute("INSERT INTO levels (channel_id, season_id, id, status) VALUES (?, ?, ?, ?)",
                     (channel_id, season_id, level_id, status))
    conn.execute(
        "UPDATE levels SET clip_id = ?, status = ?, reason = ? WHERE channel_id = ? AND season_id = ? AND id = ?",
        (clip_id, status, reason, channel_id, season_id, level_id),
    )
    conn.commit()
    return True
