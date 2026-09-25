"""A season file: `channels/<id>/season/<season>.yaml`.

This module is the schema and the loader. Checking a season against its
cast and the anti-repetition rules, and planning levels into tasks, live in
`series.check` and `series.planning`.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field

from .. import settings
from .outcome import Format

LevelStatus = Literal["ready", "blocked", "needs_input"]


class Story(BaseModel):
    must: dict[str, Any] = Field(default_factory=dict)
    prefer: dict[str, Any] = Field(default_factory=dict)


class CopyHints(BaseModel):
    """Seeds for the copy brain, never published as they stand."""

    angle: str | None = None
    title: str | None = None
    hook: str | None = None
    pin: str | None = None
    desc: str | None = None
    pin_type: str | None = None


class Level(BaseModel):
    id: str
    date: dt.date
    world: str
    generator: str = "physics"
    variant: str = "marble_race"
    params: dict[str, Any] = Field(default_factory=dict)
    entrants: list[str] = Field(default_factory=list)
    format: Format = "race"
    final: bool = False
    story: Story = Field(default_factory=Story)
    copy_: CopyHints = Field(default_factory=CopyHints, alias="copy")
    rematch_of: str | None = None
    status: LevelStatus = "ready"
    blocked_on: str | None = None
    operator_input: dict[str, Any] = Field(default_factory=dict)  # value None = still to fill
    note: str | None = None

    model_config = {"populate_by_name": True}

    def missing_input(self) -> list[str]:
        return [k for k, v in self.operator_input.items() if v in (None, "")]


class Season(BaseModel):
    id: str
    title: str
    channel: str
    scoring: str = "default"
    keywords: list[str] = []
    footer: str | None = None
    levels: list[Level]

    def level(self, level_id: str) -> Level:
        for lv in self.levels:
            if lv.id == level_id:
                return lv
        raise KeyError(f"no level {level_id!r} in season {self.id}")


def directory(channel_id: str) -> Path:
    return settings.ROOT / "channels" / channel_id / "season"


def seasons(channel_id: str) -> list[str]:
    d = directory(channel_id)
    return sorted(p.stem for p in d.glob("*.yaml")) if d.exists() else []


def load(channel_id: str, season_id: str | None = None) -> Season:
    """A channel's season; without an id, the only one it has."""
    have = seasons(channel_id)
    if not have:
        raise FileNotFoundError(f"{channel_id} has no season file in {directory(channel_id)}")
    if season_id is None:
        if len(have) > 1:
            raise ValueError(f"{channel_id} has several seasons {have}; name one")
        season_id = have[0]
    path = directory(channel_id) / f"{season_id}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"no season {season_id!r} for {channel_id}; have {have}")
    return Season(**yaml.safe_load(path.read_text()))
