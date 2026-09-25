"""What one row of bulk work is, and what came of it.

Every source (a file, an agent over MCP, the console) produces the same
`JobSpec`; nothing downstream can tell where a row came from.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class Hints(BaseModel):
    """Words the operator would like; the clip's copy starts from them and the
    channel's rules still decide what ships."""

    model_config = ConfigDict(extra="forbid")
    title: str | None = Field(None, max_length=120)
    hook: str | None = Field(None, max_length=60)
    pin: str | None = Field(None, max_length=200)
    desc: str | None = Field(None, max_length=300)

    def compact(self) -> dict[str, str]:
        return {k: v for k, v in self.model_dump().items() if v}


class JobSpec(BaseModel):
    """One row. Either an ad-hoc clip (generator, variant, stage…) or a season
    level (`level`: "L05", or a range "L02..L05" that expands to one row each)."""

    model_config = ConfigDict(extra="forbid")
    kind: Literal["make-clip"] = "make-clip"
    generator: str = "physics"
    variant: str = "marble_race"
    stage: str | None = None
    seed: int | None = Field(None, ge=0)
    background: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)  # other generator knobs, e.g. rounds
    count: int = Field(1, ge=1, le=50)
    priority: int = Field(0, ge=0, le=100)
    level: str | None = None
    brief: str | None = Field(None, max_length=600)  # what the operator wants, in words
    hints: Hints | None = None
    ref: str | None = Field(None, max_length=80)  # the row's own key: importing it twice queues it once


@dataclass
class Row:
    """A row as read, before and after it became a JobSpec."""

    number: int  # 1-based position in the source, as a person would count it
    raw: dict[str, Any]
    spec: JobSpec | None = None
    problems: list[str] = field(default_factory=list)


@dataclass
class RowResult:
    row: int
    ref: str | None
    level: str | None
    queued: bool
    task_ids: list[int]
    reason: str | None


@dataclass
class Receipt:
    batch_id: str | None
    source: str
    dry_run: bool
    rows: list[RowResult]
    note: str | None = None

    @property
    def accepted(self) -> int:
        return sum(1 for r in self.rows if r.reason is None)

    @property
    def refused(self) -> int:
        return sum(1 for r in self.rows if r.reason is not None)

    def as_dict(self) -> dict[str, Any]:
        return {"batch_id": self.batch_id, "source": self.source, "dry_run": self.dry_run,
                "accepted": self.accepted, "refused": self.refused, "note": self.note,
                "rows": [asdict(r) for r in self.rows]}


Mode = Literal["all", "partial"]
