"""What a competition produced, in a form the series layer can read.

A generator that is not a competition returns no Outcome and every series
feature skips it.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

Format = Literal["race", "elimination", "last_standing", "score"]
Status = Literal["finished", "running", "stopped", "eliminated", "out"]


class Placement(BaseModel):
    entrant_id: str
    rank: int  # 1 = winner; ties share a rank
    time_s: float | None = None  # crossing time; None if it did not finish
    status: Status = "finished"


class Event(BaseModel):
    t_s: float
    kind: str  # generator-defined: lead_change, finish, trap_catch, launched, round_start, ...
    entrant_id: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)


class Outcome(BaseModel):
    format: Format
    placements: list[Placement]
    margin_s: float | None = None  # winner vs runner-up
    lead_changes: int = 0
    events: list[Event] = Field(default_factory=list)
    facts: dict[str, Any] = Field(default_factory=dict)  # extra measured values copy may cite

    @property
    def winner(self) -> str | None:
        firsts = [p.entrant_id for p in self.placements if p.rank == 1]
        return firsts[0] if len(firsts) == 1 else None

    def rank_of(self, entrant_id: str) -> int | None:
        return next((p.rank for p in self.placements if p.entrant_id == entrant_id), None)

    def without_winner(self) -> dict[str, Any]:
        """What a copy brain may see: everything but who won and the order.

        Placements, finish events and anything naming an entrant's result are
        dropped; counts and mechanism events stay.
        """
        # relay_dropped: a relay team out because its first leg fell (World 2)
        hidden = {"finish", "eliminated", "trap_catch", "relay_dropped"}
        return {
            "format": self.format,
            "entrants": len(self.placements),
            "finishers": sum(1 for p in self.placements if p.status == "finished"),
            "margin_s": self.margin_s,
            "lead_changes": self.lead_changes,
            "events": [{"t_s": e.t_s, "kind": e.kind} for e in self.events if e.kind not in hidden],
        }
