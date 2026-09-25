"""Standings: points from approved level clips, and head-to-head from results.

One `results` row per approved (or published) level clip, written on approve
and removed on anything that takes the clip out of that state. `recompute`
rebuilds the rows from the clips alone, so the table can always be checked
against — and repaired from — the clips' own outcomes. Head-to-head is never
stored; it is read off the results.

Scoring (docs/08 §4 Standings), overridable in `channels/<id>/scoring.toml`:

    race, score         points by rank: 3 / 2 / 1, then 0; a non-finisher scores 0
    elimination,
    last_standing       one point per entrant outlasted (ranked below)
    final: true         points times final_multiplier (2)

Ranks are the generator's: a guest (`scores = false`) keeps its place in the
race but earns nothing and is not in the table.
"""

from __future__ import annotations

import json
import sqlite3
import tomllib
from dataclasses import dataclass, field
from typing import Any

from .. import db, logs, settings
from . import cast as cast_mod, season as season_mod
from .cast import Cast, level_number
from .outcome import Outcome

SCORING_FILE = "scoring.toml"
COUNTED = ("approved", "published")


@dataclass
class Scoring:
    rank_points: dict[str, list[float]] = field(
        default_factory=lambda: {"race": [3, 2, 1], "score": [3, 2, 1]})
    per_outlasted: dict[str, float] = field(
        default_factory=lambda: {"elimination": 1, "last_standing": 1})
    final_multiplier: float = 2
    finishers_only: bool = True  # race/score: a non-finisher scores nothing

    def points(self, outcome: Outcome, *, final: bool, guests: set[str]) -> dict[str, float]:
        mult = self.final_multiplier if final else 1
        out: dict[str, float] = {}
        for p in outcome.placements:
            if p.entrant_id in guests:
                continue
            if outcome.format in self.rank_points:
                table = self.rank_points[outcome.format]
                earned = table[p.rank - 1] if 1 <= p.rank <= len(table) else 0
                if self.finishers_only and p.status != "finished":
                    earned = 0
            else:
                per = self.per_outlasted.get(outcome.format, 1)
                earned = per * sum(1 for q in outcome.placements if q.rank > p.rank)
            out[p.entrant_id] = _num(earned * mult)
        return out


def _num(x: float) -> float | int:
    return int(x) if float(x).is_integer() else round(float(x), 3)


def scoring(channel_id: str, name: str = "default") -> Scoring:
    """The channel's scoring: defaults, then scoring.toml's top level, then
    its `[scheme.<name>]` table when the season names a scheme."""
    s = Scoring()
    path = settings.ROOT / "channels" / channel_id / SCORING_FILE
    if not path.exists():
        return s
    data = tomllib.loads(path.read_text())
    layers = [data]
    if name != "default":
        scheme = (data.get("scheme") or {}).get(name)
        if scheme is None:
            raise ValueError(f"{path} has no [scheme.{name}]")
        layers.append(scheme)
    for layer in layers:
        for fmt in ("race", "score"):
            if isinstance(layer.get(fmt), dict) and "points" in layer[fmt]:
                s.rank_points[fmt] = [float(x) for x in layer[fmt]["points"]]
        for fmt in ("elimination", "last_standing"):
            if isinstance(layer.get(fmt), dict) and "per_outlasted" in layer[fmt]:
                s.per_outlasted[fmt] = float(layer[fmt]["per_outlasted"])
        if "final_multiplier" in layer:
            s.final_multiplier = float(layer["final_multiplier"])
        if "finishers_only" in layer:
            s.finishers_only = bool(layer["finishers_only"])
    return s


# --- which clips count -----------------------------------------------------

def _level_of(row) -> tuple[str, str] | None:
    """(season_id, level_id) of a level clip, else None."""
    params = json.loads(row["params_json"] or "{}")
    level_id = row["level_id"] or params.get("level_id")
    season_id = params.get("season_id")
    return (season_id, level_id) if level_id and season_id else None


def _counts(row) -> bool:
    return row["status"] in COUNTED and not row["deleted_at"]


def _outcome(row) -> Outcome | None:
    facts = json.loads(row["facts_json"] or "{}")
    raw = facts.get("outcome")
    return Outcome.model_validate(raw) if raw else None


def _season_level(channel_id: str, season_id: str, level_id: str):
    try:
        s = season_mod.load(channel_id, season_id)
        return s, s.level(level_id)
    except (FileNotFoundError, KeyError, ValueError):
        return None, None


def _guests(c: Cast | None) -> set[str]:
    return {e.id for e in c.entrants if not e.scores} if c else set()


def guard(conn: sqlite3.Connection, clip_id: str) -> None:
    """Refuse to count a second clip for a level that already has one."""
    row = db.get(conn, clip_id)
    ids = _level_of(row) if row is not None else None
    if ids is None:
        return
    other = conn.execute(
        """SELECT clip_id FROM results WHERE channel_id = ? AND season_id = ? AND level_id = ?
           AND clip_id != ?""", (row["channel_id"], *ids, clip_id)).fetchone()
    if other:
        raise ValueError(f"level {ids[1]} already counts clip {other['clip_id']}; "
                         "reject or bin that one first")


def record(conn: sqlite3.Connection, clip_id: str) -> dict[str, Any] | None:
    """Write the results row for an approved level clip. Returns its points,
    or None when the clip is not a level clip with an outcome."""
    row = db.get(conn, clip_id)
    if row is None:
        raise ValueError(f"no clip {clip_id}")
    ids = _level_of(row)
    if ids is None:
        return None
    outcome = _outcome(row)
    if outcome is None:
        logs.event("standings.skipped", level="warn", channel=row["channel_id"], clip=clip_id,
                   reason="level clip has no outcome in its facts")
        return None
    guard(conn, clip_id)
    season_id, level_id = ids
    season, level = _season_level(row["channel_id"], season_id, level_id)
    rules = scoring(row["channel_id"], season.scoring if season else "default")
    points = rules.points(outcome, final=bool(level and level.final),
                          guests=_guests(cast_mod.load(row["channel_id"])))
    conn.execute(
        """INSERT OR REPLACE INTO results
           (clip_id, channel_id, season_id, level_id, outcome_json, points_json, approved_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (clip_id, row["channel_id"], season_id, level_id, outcome.model_dump_json(),
         json.dumps(points, sort_keys=True), db.now()),
    )
    conn.commit()
    logs.event("standings.recorded", channel=row["channel_id"], clip=clip_id, level=level_id,
               season=season_id, points=points)
    return points


def drop(conn: sqlite3.Connection, clip_id: str) -> bool:
    cur = conn.execute("DELETE FROM results WHERE clip_id = ?", (clip_id,))
    conn.commit()
    return cur.rowcount > 0


def sync(conn: sqlite3.Connection, clip_id: str) -> None:
    """Make the clip's result row match its state: counted clips have one,
    every other clip (or a clip that is gone) has none."""
    row = db.get(conn, clip_id)
    if row is None or not _counts(row):
        if drop(conn, clip_id) and row is not None:
            logs.event("standings.dropped", channel=row["channel_id"], clip=clip_id, status=row["status"])
        return
    record(conn, clip_id)


def recompute(conn: sqlite3.Connection, channel_id: str, season_id: str) -> int:
    """Rebuild the season's results from its approved and published clips.

    One clip per level: a published one before an approved one, then the
    oldest. Returns how many rows were written.
    """
    conn.execute("DELETE FROM results WHERE channel_id = ? AND season_id = ?", (channel_id, season_id))
    conn.commit()
    rows = conn.execute(
        f"""SELECT * FROM clips WHERE channel_id = ? AND level_id IS NOT NULL AND deleted_at IS NULL
            AND status IN ({','.join('?' * len(COUNTED))})
            ORDER BY CASE status WHEN 'published' THEN 0 ELSE 1 END, created_at""",
        (channel_id, *COUNTED),
    ).fetchall()
    written, seen = 0, set()
    for row in rows:
        ids = _level_of(row)
        if ids is None or ids[0] != season_id or ids[1] in seen:
            continue
        if record(conn, row["id"]) is not None:
            seen.add(ids[1])
            written += 1
    logs.event("standings.recomputed", channel=channel_id, season=season_id, results=written)
    return written


# --- reading ----------------------------------------------------------------

def results(conn: sqlite3.Connection, channel_id: str, season_id: str, *,
            before_level: str | None = None) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM results WHERE channel_id = ? AND season_id = ?", (channel_id, season_id)
    ).fetchall()
    cut = level_number(before_level) if before_level else None
    out = []
    for r in rows:
        n = level_number(r["level_id"])
        if cut is not None and n >= cut:
            continue
        out.append({"clip_id": r["clip_id"], "level_id": r["level_id"], "number": n,
                    "outcome": Outcome.model_validate_json(r["outcome_json"]),
                    "points": json.loads(r["points_json"])})
    return sorted(out, key=lambda r: r["number"])


def table(conn: sqlite3.Connection, channel_id: str, season_id: str, *,
          before_level: str | None = None) -> list[dict[str, Any]]:
    """Rows {entrant_id, name, points, wins, races}: points desc, wins desc, id.

    `before_level` counts only levels numbered below it. Regulars with no
    result yet appear with zeros once they have debuted (by `before_level`,
    or by the latest level with a result or a plan). Guests never appear.
    """
    c = cast_mod.load(channel_id)
    guests = _guests(c)
    rows: dict[str, dict[str, Any]] = {}

    def entry(eid: str) -> dict[str, Any]:
        if eid not in rows:
            name = eid
            if c is not None:
                try:
                    name = c.get(eid).name
                except KeyError:
                    pass
            rows[eid] = {"entrant_id": eid, "name": name, "points": 0, "wins": 0, "races": 0}
        return rows[eid]

    got = results(conn, channel_id, season_id, before_level=before_level)
    for r in got:
        for p in r["outcome"].placements:
            if p.entrant_id in guests:
                continue
            e = entry(p.entrant_id)
            e["races"] += 1
            e["points"] = _num(e["points"] + r["points"].get(p.entrant_id, 0))
            if p.rank == 1:
                e["wins"] += 1
    if c is not None:
        if before_level:
            debuted = lambda e: e.debuted_by(before_level)  # noqa: E731
        else:
            planned = [level_number(x["id"]) for x in conn.execute(
                "SELECT id FROM levels WHERE channel_id = ? AND season_id = ?", (channel_id, season_id))]
            latest = max([r["number"] for r in got] + planned, default=0)
            debuted = lambda e: level_number(e.debut) <= latest  # noqa: E731
        for e in c.entrants:
            if e.scores and debuted(e):
                entry(e.id)
    return sorted(rows.values(), key=lambda e: (-e["points"], -e["wins"], e["entrant_id"]))


def h2h(conn: sqlite3.Connection, channel_id: str, season_id: str, a: str, b: str, *,
        before_level: str | None = None) -> tuple[int, int]:
    """Of the counted races both ran: times a ranked ahead of b, and b of a."""
    a_ahead = b_ahead = 0
    for r in results(conn, channel_id, season_id, before_level=before_level):
        ra, rb = r["outcome"].rank_of(a), r["outcome"].rank_of(b)
        if ra is None or rb is None:
            continue
        if ra < rb:
            a_ahead += 1
        elif rb < ra:
            b_ahead += 1
    return a_ahead, b_ahead


def summary_line(conn: sqlite3.Connection, channel_id: str, season_id: str, *,
                 before_level: str | None = None, top: int = 4) -> str:
    """One line for a notification: "Blaze 9 · Tide 7 · Volt 4 · Moss 2"."""
    rows = table(conn, channel_id, season_id, before_level=before_level)
    if not rows:
        return "no results yet"
    line = " · ".join(f"{r['name']} {r['points']}" for r in rows[:top])
    return line + (f" · +{len(rows) - top} more" if len(rows) > top else "")


def level_of_clip(row) -> tuple[str, str] | None:
    """(season_id, level_id) of a clip row, or None when it is not a level clip."""
    return _level_of(row)
