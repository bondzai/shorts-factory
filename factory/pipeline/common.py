"""What every stage needs: what a stage returns, and whose channel it is."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from .. import channels
from ..channels import Channel


@dataclass
class StageOutcome:
    clip_id: str
    status: str
    detail: str
    cost_usd: float = 0.0


def qc_enabled() -> bool:
    """Whether a clip is judged as it is made, or waits for `factory qc`."""
    from .. import settings

    return bool(settings.load().raw.get("qc", {}).get("enabled", True))


def sample_times(duration: float) -> list[float]:
    return [
        min(0.3, duration / 10),
        duration * 0.35,
        duration * 0.7,
        max(0.0, duration - 0.35),
    ]


def resolve(conn: sqlite3.Connection, channel: Channel | str | None) -> Channel:
    if isinstance(channel, Channel):
        return channel
    return channels.resolve(conn, channel)
