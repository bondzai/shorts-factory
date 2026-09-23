"""Stage 6: out of the door, through whichever driver the channel uses.

On the manual driver this is the "I uploaded it" button; on the YouTube
driver it is the upload itself. Either way the clip ends up with a remote id,
which is what lets stage 7 find its numbers again.
"""

from __future__ import annotations

import json
import sqlite3

from .. import channels, db, logs
from .. import publish as drivers
from ..channels import Channel
from ..models import APPROVED, PUBLISHED
from .common import StageOutcome, resolve


def publish_one(conn: sqlite3.Connection, clip_id: str) -> StageOutcome:
    """Publish one approved clip through its channel's driver.

    On the manual driver this is the "I uploaded it" button: the file and its
    text are copied to the publish queue and the clip is marked published, so
    metrics can be attached to it later.
    """
    row = db.get(conn, clip_id)
    if row is None or row["status"] != APPROVED:
        raise ValueError(f"{clip_id} is not approved")
    ch = channels.get(conn, row["channel_id"])
    driver = drivers.get(ch.driver, ch)
    try:
        result = driver.publish(
            clip_id=row["id"],
            video_path=db.video_file(row),
            title=row["title"],
            description=row["description"],
            hashtags=json.loads(row["hashtags_json"] or "[]"),
            # The question the clip asks belongs under the clip, and the slot
            # is the one the rest of the factory already agreed on.
            comment=row["comment_prompt"],
        )
        db.update(
            conn, row["id"], status=PUBLISHED, platform=result.platform,
            remote_id=result.remote_id, published_at=db.now(),
        )
        logs.event(
            "clip.published", channel=ch.id, clip=row["id"],
            platform=result.platform, remote_id=result.remote_id,
            title=row["title"], driver=ch.driver,
        )
        return StageOutcome(row["id"], PUBLISHED, result.note)
    except Exception as exc:
        logs.event(
            "clip.publish_failed", level="error", channel=ch.id,
            clip=row["id"], error=str(exc),
        )
        return StageOutcome(row["id"], APPROVED, f"publish failed: {exc}")


def publish_approved(
    conn: sqlite3.Connection, channel: Channel | str | None, *, dry_run: bool = False
) -> list[StageOutcome]:
    ch = resolve(conn, channel)
    results = []
    for row in db.by_status(conn, ch.id, APPROVED):
        if dry_run:
            results.append(
                StageOutcome(row["id"], APPROVED, f"would publish via {ch.driver}")
            )
            continue
        results.append(publish_one(conn, row["id"]))
    return results
