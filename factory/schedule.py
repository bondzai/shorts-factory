"""When to upload, and what to paste when you do.

The factory does not upload on a manual channel; a person does, from a phone
or Studio. So two things are computed here for that person: the next good
slot (in their own time, with the audience's time beside it) and the text to
paste, laid out under headings so nothing lands in the wrong box.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from . import settings

AUDIENCE_TZ = "America/New_York"  # the US evening is what best_time is chosen for
LEAD_MINUTES = 10  # a slot closer than this is already gone


def _publish() -> dict:
    return settings.load().raw.get("publish", {})


def timezone() -> ZoneInfo:
    try:
        return ZoneInfo(str(_publish().get("timezone") or "Asia/Bangkok"))
    except Exception:
        return ZoneInfo("Asia/Bangkok")


def parse_hhmm(text: str | None, default: tuple[int, int]) -> tuple[int, int]:
    try:
        h, m = str(text or "").strip().split(":")
        h, m = int(h), int(m)
        if 0 <= h < 24 and 0 <= m < 60:
            return h, m
    except (ValueError, AttributeError):
        pass
    return default


def next_slot(now: datetime | None = None) -> datetime:
    """The next occurrence of publish.best_time, at least LEAD_MINUTES away."""
    tz = timezone()
    now = (now or datetime.now(tz)).astimezone(tz)
    h, m = parse_hhmm(_publish().get("best_time"), (6, 0))
    slot = now.replace(hour=h, minute=m, second=0, microsecond=0)
    if slot < now + timedelta(minutes=LEAD_MINUTES):
        slot += timedelta(days=1)
    return slot


def describe(slot: datetime) -> str:
    local = slot.strftime("%a %Y-%m-%d %H:%M")
    audience = slot.astimezone(ZoneInfo(AUDIENCE_TZ)).strftime("%a %H:%M")
    return f"{local} {timezone().key} (= {audience} New York, US evening)"


def upload_text(conn: sqlite3.Connection, clip_id: str, now: datetime | None = None) -> dict:
    """Everything the upload form asks for, under the heading it belongs to."""
    from . import db

    row = db.get(conn, clip_id)
    if row is None:
        raise ValueError(f"no clip {clip_id}")
    facts = json.loads(row["facts_json"] or "{}")
    hashtags = json.loads(row["hashtags_json"] or "[]")
    slot = next_slot(now)
    meta = [f"clip {row['id']}", f"{row['generator']}/{row['variant']}", f"seed {row['seed']}"]
    if facts.get("course"):
        meta.append(f"course {facts['course']}")
    if row["duration_s"]:
        meta.append(f"{row['duration_s']:.1f} s")
    if row["hook_text"]:
        meta.append(f"opening caption \u201c{row['hook_text']}\u201d")
    if facts.get("theme") and facts["theme"] != "default":
        meta.append(f"theme {facts['theme']}")
    sections = [
        ("TITLE", row["title"] or ""),
        ("DESCRIPTION", row["description"] or ""),
        ("HASHTAGS", " ".join(hashtags)),
        ("PINNED COMMENT", row["comment_prompt"] or "(none)"),
        ("SCHEDULE", describe(slot)),
        ("METADATA", " \u00b7 ".join(meta)),
    ]
    text = "\n\n".join(f"{name}\n{body}" for name, body in sections)
    return {"text": text, "schedule": slot.isoformat(), "schedule_text": describe(slot), "sections": dict(sections)}
