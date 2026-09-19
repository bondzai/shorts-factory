"""Reusable agent instructions, rendered against the live database.

A prompt retyped into a chat window each session drifts: it forgets what was
published last week, it repeats advice that the numbers have since contradicted,
and no two runs get the same brief. So the prose lives in prompts/*.md, in git,
and the facts are substituted at render time from the database.

The split mirrors the MCP surface: the file supplies judgement, this module
supplies arithmetic.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from . import analytics, channels, db, generators, settings


def prompts_dir() -> Path:
    override = settings.ROOT / "prompts"
    if override.exists():
        return override
    return Path(__file__).resolve().parents[1] / "prompts"


def available() -> list[str]:
    return sorted(p.stem for p in prompts_dir().glob("*.md") if p.stem != "README")


def _recent(conn: sqlite3.Connection, channel_id: str, limit: int = 12) -> str:
    rows = conn.execute(
        """
        SELECT generator, variant, seed, title, status, views, avg_view_pct
        FROM clips WHERE channel_id = ?
        ORDER BY id DESC LIMIT ?
        """,
        (channel_id, limit),
    ).fetchall()
    if not rows:
        return "Nothing made on this channel yet."
    lines = []
    for row in rows:
        performance = ""
        if row["views"] is not None:
            performance = f" — {row['views']} views"
            if row["avg_view_pct"] is not None:
                performance += f", {row['avg_view_pct']:.0f}% average viewed"
        lines.append(
            f"- {row['generator']}/{row['variant']} seed {row['seed']} "
            f"[{row['status']}] {row['title'] or '(no title yet)'}{performance}"
        )
    return "\n".join(lines)


def _retention(conn: sqlite3.Connection, channel_id: str) -> str:
    rows = conn.execute(
        """
        SELECT title, views, avg_view_pct FROM clips
        WHERE channel_id = ? AND views IS NOT NULL
        ORDER BY views DESC
        """,
        (channel_id,),
    ).fetchall()
    if not rows:
        return (
            "No clip on this channel has metrics yet, so nothing below is "
            "evidence. Treat any advice about hooks as a hypothesis."
        )
    lines = [
        f"- {row['title'] or '(untitled)'}: {row['views']} views"
        + (f", {row['avg_view_pct']:.0f}% average viewed" if row["avg_view_pct"] is not None else "")
        for row in rows[:8]
    ]
    return f"Measured on this channel (n = {len(rows)}):\n" + "\n".join(lines)


def context(conn: sqlite3.Connection, channel_id: str | None = None) -> dict[str, Any]:
    channel = channels.resolve(conn, channel_id)
    cfg = settings.load()
    catalogue = generators.catalogue(channel.variants or None)
    return {
        "channel": channel.id,
        "channel_name": channel.name,
        "modules": catalogue or "(no modules enabled on this channel)",
        "rules": channel.rules().strip(),
        "recent": _recent(conn, channel.id),
        "retention": _retention(conn, channel.id),
        "max_sameness": cfg.raw["qc"]["max_sameness"],
        "min_seconds": cfg.raw["qc"]["min_seconds"],
        "max_seconds": cfg.raw["qc"]["max_seconds"],
        "target_lufs": cfg.raw["qc"].get("target_lufs", -14),
    }


def render(name: str, channel_id: str | None = None) -> str:
    path = prompts_dir() / f"{name}.md"
    if not path.exists():
        raise ValueError(f"no playbook {name!r}; have {available() or 'none'}")
    text = path.read_text(encoding="utf-8")
    with db.connect() as conn:
        values = context(conn, channel_id)
    try:
        return text.format(**values)
    except KeyError as exc:
        raise ValueError(
            f"{path.name} asks for {exc} which the factory does not know; "
            f"available: {sorted(values)}"
        ) from None
