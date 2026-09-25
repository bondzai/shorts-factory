"""Bulk work for the queue: many make-clip jobs from a file, an agent or the
console, checked together and written together (docs/02, "Bulk work").

    source (csv/json/yaml/list) -> JobSpec rows -> expanders -> validators -> sink

`build(conn, channel)` wires the defaults; callers that need a different rule
set (MCP caps rows and priority) pass their own.
"""

from __future__ import annotations

import sqlite3

from .. import generators, settings
from ..channels import Channel
from ..series import cast as cast_mod, check as check_mod, season as season_mod
from .context import BatchContext
from .service import BatchService, LevelRange
from .sink import TaskSink
from .sources import SOURCES, CsvSource, JsonSource, ListSource, YamlSource, source_for
from .spec import Hints, JobSpec, Receipt
from .validators import DEFAULT

__all__ = ["BatchContext", "BatchService", "Hints", "JobSpec", "Receipt", "ListSource", "CsvSource",
           "JsonSource", "YamlSource", "SOURCES", "source_for", "context", "service", "LevelRange"]


def context(conn: sqlite3.Connection, channel: Channel, *, max_priority: int = 100) -> BatchContext:
    from ..generators import physics

    season = cast = None
    problems: list = []
    if season_mod.seasons(channel.id):
        season, cast = season_mod.load(channel.id), cast_mod.load(channel.id)
        allow = bool(settings.load().raw.get("series", {}).get("allow_identity_constraints", False))
        problems = check_mod.check(season, cast, stages=set(physics.STAGE_BY_ID), allow_identity=allow,
                                   channel_variants=channel.variants)
    used = {r[0] for r in conn.execute("SELECT seed FROM clips WHERE channel_id = ?", (channel.id,))}
    refs = {r[0] for r in conn.execute(
        "SELECT ref FROM tasks WHERE channel_id = ? AND ref IS NOT NULL AND status != 'cancelled'", (channel.id,))}
    return BatchContext(conn=conn, channel=channel, modules=generators.available(channel.variants),
                        stages=set(physics.STAGE_BY_ID), season=season, cast=cast, season_problems=problems,
                        used_seeds=used, known_refs=refs, max_priority=max_priority)


def service(*, max_rows: int = 500) -> BatchService:
    return BatchService(DEFAULT, TaskSink(), (LevelRange(),), max_rows=max_rows)
