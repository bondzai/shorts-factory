"""Everything a check needs to know about the channel, gathered once per batch."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from typing import Any

from ..channels import Channel
from .spec import JobSpec


@dataclass
class BatchContext:
    conn: sqlite3.Connection
    channel: Channel
    modules: dict[str, list[str]]  # ready generator -> variants this channel allows
    stages: set[str]
    season: Any = None  # series.season.Season, when the channel has one
    cast: Any = None
    season_problems: list = field(default_factory=list)
    used_seeds: set[int] = field(default_factory=set)
    known_refs: set[str] = field(default_factory=set)
    max_priority: int = 100
    # rows accepted so far in this batch, so two rows cannot claim one seed, ref or level
    seen_seeds: set[int] = field(default_factory=set)
    seen_refs: set[str] = field(default_factory=set)
    seen_levels: set[str] = field(default_factory=set)

    def remember(self, spec: JobSpec) -> None:
        if spec.seed is not None:
            self.seen_seeds.add(spec.seed)
        if spec.ref:
            self.seen_refs.add(spec.ref)
        if spec.level:
            self.seen_levels.add(spec.level)
