from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol


@dataclass
class PublishResult:
    platform: str
    remote_id: str | None
    note: str


@dataclass
class Metrics:
    views: int | None = None
    likes: int | None = None
    avg_view_pct: float | None = None
    swipe_away_pct: float | None = None
    extra: dict[str, Any] = field(default_factory=dict)


class Publisher(Protocol):
    name: str

    def publish(
        self,
        *,
        clip_id: str,
        video_path: Path,
        title: str,
        description: str,
        hashtags: list[str],
    ) -> PublishResult: ...

    def fetch_metrics(self, remote_id: str) -> Metrics: ...


def get(name: str, channel) -> Publisher:
    """Drivers are per channel: separate output folder, separate credentials."""
    if name == "manual":
        from .manual import ManualPublisher

        return ManualPublisher(channel)
    if name == "youtube":
        from .youtube import YouTubePublisher

        return YouTubePublisher(channel)
    raise KeyError(f"unknown publish driver {name!r}: use 'manual' or 'youtube'")
