"""A channel's recurring entrants: `channels/<id>/cast.toml`.

Colours and traits are data for the generator; `bio` is prose for a copy
brain and is never parsed. Unknown traits are kept here and ignored (with a
warning) by a generator that does not support them.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

from pydantic import BaseModel, Field, field_validator

from .. import settings

LEVEL_ID = re.compile(r"^L(\d+)$")


class Entrant(BaseModel):
    id: str
    name: str
    color: str  # "#RRGGBB"
    traits: dict[str, float | bool] = Field(default_factory=dict)
    bio: str = ""
    debut: str = "L01"
    scores: bool = True

    @field_validator("id")
    @classmethod
    def _id(cls, v: str) -> str:
        if not re.fullmatch(r"[a-z][a-z0-9_]*", v):
            raise ValueError(f"entrant id {v!r}: lower-case letters, digits and _ only")
        return v

    @field_validator("color")
    @classmethod
    def _color(cls, v: str) -> str:
        if not re.fullmatch(r"#[0-9A-Fa-f]{6}", v):
            raise ValueError(f"colour {v!r} is not #RRGGBB")
        return v.upper()

    @property
    def rgb(self) -> tuple[int, int, int]:
        return tuple(int(self.color[i:i + 2], 16) for i in (1, 3, 5))  # type: ignore[return-value]

    def debuted_by(self, level_id: str) -> bool:
        return level_number(level_id) >= level_number(self.debut)


class Cast(BaseModel):
    entrants: list[Entrant]

    def get(self, entrant_id: str) -> Entrant:
        for e in self.entrants:
            if e.id == entrant_id:
                return e
        raise KeyError(f"no entrant {entrant_id!r} in the cast; have {[e.id for e in self.entrants]}")

    def ids(self) -> list[str]:
        return [e.id for e in self.entrants]


def level_number(level_id: str) -> int:
    m = LEVEL_ID.match(level_id)
    if not m:
        raise ValueError(f"not a level id: {level_id!r} (expected L01, L02, …)")
    return int(m.group(1))


def path_for(channel_id: str) -> Path:
    return settings.ROOT / "channels" / channel_id / "cast.toml"


def load(channel_id: str) -> Cast | None:
    """The channel's cast, or None when it has none."""
    path = path_for(channel_id)
    if not path.exists():
        return None
    data = tomllib.loads(path.read_text())
    return Cast(entrants=[Entrant(**e) for e in data.get("entrant", [])])
