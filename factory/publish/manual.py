"""Manual driver — the default, and what weeks 1-2 should use.

Nothing is uploaded. The approved clip and its metadata are copied into
data/out/publish-queue/ so you upload by hand. You want to watch the first
few dozen clips leave the building before you hand an API key to a cron job.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

from .. import settings
from .base import Metrics, PublishResult


def _slug(text: str, limit: int = 48) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:limit] or "clip"


class ManualPublisher:
    name = "manual"

    def publish(
        self,
        *,
        clip_id: str,
        video_path: Path,
        title: str,
        description: str,
        hashtags: list[str],
    ) -> PublishResult:
        queue = settings.load().out_dir / "publish-queue"
        queue.mkdir(parents=True, exist_ok=True)
        stem = f"{clip_id}-{_slug(title)}"
        shutil.copy2(video_path, queue / f"{stem}.mp4")
        (queue / f"{stem}.txt").write_text(
            f"{title}\n\n{description}\n\n{' '.join(hashtags)}\n"
        )
        return PublishResult(
            platform="manual",
            remote_id=None,
            note=f"copied to {queue / (stem + '.mp4')}",
        )

    def fetch_metrics(self, remote_id: str) -> Metrics:
        raise NotImplementedError(
            "the manual driver cannot read metrics; enter them with "
            "`factory set-metrics` or switch [publish] driver to 'youtube'"
        )
