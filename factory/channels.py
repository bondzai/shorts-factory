"""Channels: the dimension everything else hangs off.

A channel owns its clips, its rules file, its publish driver and its
credentials. Two channels sharing one rules file would be worse than useless —
what a marble audience rewards says nothing about a crypto one — so the rules
live per channel on disk at channels/<id>/rules.md.

The id is internal and never changes; rename the display name freely.
"""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import settings

DEFAULT_ID = "main"

RULES_TEMPLATE = """# Rules for {name}

Read by the Idea and Metadata agents on every run for this channel, and
rewritten by the Analyst once there is enough data to justify a change.

## Hook (first 1.5 seconds)

- Motion must already be happening on frame 1. No static intro.
- Whatever the viewer is asked to predict must be visible immediately.

## Title (English)

- 40-70 characters, sentence case, no stacked punctuation.
- No Thai characters in the title, description, or hashtags.

## Hashtags

- 3 to 5 tags: one format tag (#shorts), one niche tag, the rest specific.

## Variety

- Do not repeat the same variant more than twice in any 7 consecutive clips.

## Learned rules

<!-- analyst:begin -->
<!-- The Analyst appends findings here. Empty until n is large enough. -->
<!-- analyst:end -->
"""


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    if not slug:
        raise ValueError(f"cannot make an id from {text!r}")
    return slug[:40]


@dataclass(frozen=True)
class Channel:
    id: str
    name: str
    handle: str | None
    platform: str
    driver: str
    variants: list[str]
    cadence: int
    active: bool
    note: str | None

    @property
    def dir(self) -> Path:
        return settings.load().channels_dir / self.id

    @property
    def rules_path(self) -> Path:
        return self.dir / "rules.md"

    @property
    def token_path(self) -> Path:
        """Where this channel's OAuth token lives. One per channel, never shared."""
        return self.dir / "token.json"

    def rules(self) -> str:
        """Read the rules, seeding the file the first time it is needed."""
        path = self.rules_path
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            legacy = settings.ROOT / "rules.md"
            if self.id == DEFAULT_ID and legacy.exists():
                path.write_text(legacy.read_text())
            else:
                path.write_text(RULES_TEMPLATE.format(name=self.name))
        return path.read_text()

    def allows(self, generator: str, variant: str) -> bool:
        return not self.variants or f"{generator}/{variant}" in self.variants

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "handle": self.handle,
            "platform": self.platform,
            "driver": self.driver,
            "variants": self.variants,
            "cadence": self.cadence,
            "active": self.active,
            "note": self.note,
        }


def _row_to_channel(row: sqlite3.Row) -> Channel:
    return Channel(
        id=row["id"],
        name=row["name"],
        handle=row["handle"],
        platform=row["platform"],
        driver=row["driver"],
        variants=json.loads(row["variants_json"] or "[]"),
        cadence=row["cadence"],
        active=bool(row["active"]),
        note=row["note"],
    )


def create(
    conn: sqlite3.Connection,
    *,
    name: str,
    channel_id: str | None = None,
    handle: str | None = None,
    platform: str = "youtube",
    driver: str | None = None,
    variants: list[str] | None = None,
    cadence: int = 1,
    note: str | None = None,
) -> Channel:
    from . import db

    channel_id = channel_id or slugify(name)
    if conn.execute("SELECT 1 FROM channels WHERE id = ?", (channel_id,)).fetchone():
        raise ValueError(f"channel {channel_id!r} already exists")
    driver = driver or settings.load().raw["publish"]["driver"]
    conn.execute(
        """INSERT INTO channels
           (id, created_at, name, handle, platform, driver, variants_json, cadence, active, note)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?)""",
        (
            channel_id, db.now(), name, handle, platform, driver,
            json.dumps(variants or []), cadence, note,
        ),
    )
    conn.commit()
    channel = get(conn, channel_id)
    channel.rules()  # seed the file so it exists before the first run
    return channel


_EDITABLE = {"name", "handle", "platform", "driver", "cadence", "active", "note", "variants_json"}


def edit(conn: sqlite3.Connection, channel_id: str, **fields: Any) -> Channel:
    if "variants" in fields:
        fields["variants_json"] = json.dumps(fields.pop("variants"))
    unknown = set(fields) - _EDITABLE
    if unknown:
        raise ValueError(f"not editable: {sorted(unknown)}")
    if not fields:
        return get(conn, channel_id)
    assignments = ", ".join(f"{k} = ?" for k in fields)
    conn.execute(
        f"UPDATE channels SET {assignments} WHERE id = ?", (*fields.values(), channel_id)
    )
    conn.commit()
    return get(conn, channel_id)


def get(conn: sqlite3.Connection, channel_id: str) -> Channel:
    row = conn.execute("SELECT * FROM channels WHERE id = ?", (channel_id,)).fetchone()
    if row is None:
        known = [r["id"] for r in conn.execute("SELECT id FROM channels").fetchall()]
        raise KeyError(f"no channel {channel_id!r}; have {known}")
    return _row_to_channel(row)


def all_channels(conn: sqlite3.Connection, *, active_only: bool = False) -> list[Channel]:
    sql = "SELECT * FROM channels"
    if active_only:
        sql += " WHERE active = 1"
    sql += " ORDER BY created_at"
    return [_row_to_channel(r) for r in conn.execute(sql).fetchall()]


def resolve(conn: sqlite3.Connection, channel_id: str | None) -> Channel:
    """Pick the channel to act on: the named one, or the only active one."""
    if channel_id:
        return get(conn, channel_id)
    active = all_channels(conn, active_only=True)
    if len(active) == 1:
        return active[0]
    if not active:
        raise ValueError("no active channels; run `factory channels add` first")
    names = ", ".join(c.id for c in active)
    raise ValueError(f"several active channels ({names}); pass --channel")
