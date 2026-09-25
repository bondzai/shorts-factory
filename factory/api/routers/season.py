"""The Season screen: the channel's levels, what became of each, the table,
and the one button that queues the next levels.

Everything here goes through factory/seasons.py, the same functions `factory
season …` and the MCP season tools call, so the three cannot disagree. The
reads never write: problems are computed from the file without registering
the season (only planning registers it).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ... import db, seasons, settings
from ...series import check as check_mod
from ..common import resolve

router = APIRouter()

#: A level the Plan button may queue: the file says ready and nothing
#: (or only a failure) has come of it yet.
PLANNABLE = ("ready", "failed")


def _no_season(exc: Exception) -> HTTPException:
    return HTTPException(404, str(exc))


def _problems(ch, season_id: str | None) -> list[dict[str, Any]]:
    try:
        season, cast = seasons.load(ch, season_id)
    except Exception as exc:  # the file does not load: one error, as `season check` says it
        return [{"level_id": None, "severity": "error", "message": str(exc)}]
    allow = bool(settings.load().raw.get("series", {}).get("allow_identity_constraints", False))
    problems = check_mod.check(season, cast, stages=seasons.known_stages(), allow_identity=allow,
                               channel_variants=ch.variants)
    return [p.as_dict() for p in problems]


def plannable(level: dict[str, Any]) -> bool:
    return (level["file_status"] == "ready" and not level["missing_input"]
            and level["status"] in PLANNABLE)


@router.get("/api/season")
def season_status(channel: str | None = None, season: str | None = None) -> dict[str, Any]:
    """Every level with its clip, the counts, the copy path, and the problems."""
    with db.connect() as conn:
        ch = resolve(conn, channel)
        try:
            out = seasons.status(conn, ch, season)
        except (FileNotFoundError, ValueError) as exc:
            raise _no_season(exc) from None
    for lv in out["levels"]:
        lv["plannable"] = plannable(lv)
    return {
        **out,
        "channel": ch.id,
        "worlds": list(dict.fromkeys(lv["world"] for lv in out["levels"])),
        "next_ready": [lv["id"] for lv in out["levels"] if lv["plannable"]][:10],
        "problems": _problems(ch, out["season"]),
    }


@router.get("/api/season/standings")
def season_standings(channel: str | None = None, season: str | None = None,
                     after: str | None = None) -> dict[str, Any]:
    with db.connect() as conn:
        ch = resolve(conn, channel)
        try:
            return seasons.standings_view(conn, ch, season, after=after)
        except (FileNotFoundError, ValueError) as exc:
            raise _no_season(exc) from None


@router.get("/api/season/level/{level_id}")
def season_level(level_id: str, channel: str | None = None, season: str | None = None) -> dict[str, Any]:
    with db.connect() as conn:
        ch = resolve(conn, channel)
        try:
            return seasons.get_level(conn, ch, level_id, season)
        except (FileNotFoundError, KeyError, ValueError) as exc:
            raise _no_season(exc) from None


class PlanLevels(BaseModel):
    channel: str | None = None
    season: str | None = None
    #: "L02..L04", "L03,L05", or a list of ids.
    levels: str | list[str]
    replan: bool = False


@router.post("/api/season/plan")
def season_plan(body: PlanLevels) -> dict[str, Any]:
    """Queue one make-clip task per level; say why for each one refused."""
    levels = body.levels if isinstance(body.levels, str) else ",".join(body.levels)
    with db.connect() as conn:
        ch = resolve(conn, body.channel)
        try:
            results = seasons.plan(conn, ch, levels, season_id=body.season, replan=body.replan, by="human")
        except (FileNotFoundError, KeyError, ValueError) as exc:
            raise HTTPException(400, str(exc)) from None
    return {"results": results, "queued": sum(1 for r in results if r["queued"])}
