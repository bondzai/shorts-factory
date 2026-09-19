from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from . import settings

SCHEMA = Path(__file__).resolve().parent / "schema.sql"


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_id() -> str:
    return uuid.uuid4().hex[:12]


def connect() -> sqlite3.Connection:
    cfg = settings.load()
    cfg.ensure_dirs()
    conn = sqlite3.connect(cfg.db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA.read_text())
    return conn


def insert_clip(
    conn: sqlite3.Connection,
    *,
    generator: str,
    variant: str,
    seed: int,
    params: dict[str, Any],
    hook: str,
    plan_why: str,
) -> str:
    clip_id = new_id()
    conn.execute(
        """INSERT INTO clips
           (id, created_at, generator, variant, seed, params_json, hook, plan_why, status)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'planned')""",
        (clip_id, now(), generator, variant, seed, json.dumps(params), hook, plan_why),
    )
    conn.commit()
    return clip_id


_ALLOWED_COLUMNS = {
    "status", "video_path", "render_desc", "facts_json",
    "duration_s", "width", "height", "fps",
    "loudness_lufs", "phash", "sameness", "title", "description",
    "hashtags_json", "qc_json", "reject_reason", "platform", "remote_id",
    "published_at", "views", "avg_view_pct", "swipe_away_pct", "likes",
    "metrics_at",
}


def update(conn: sqlite3.Connection, clip_id: str, **fields: Any) -> None:
    unknown = set(fields) - _ALLOWED_COLUMNS
    if unknown:
        raise ValueError(f"not updatable: {sorted(unknown)}")
    assignments = ", ".join(f"{k} = ?" for k in fields)
    conn.execute(
        f"UPDATE clips SET {assignments} WHERE id = ?",
        (*fields.values(), clip_id),
    )
    conn.commit()


def add_cost(conn: sqlite3.Connection, clip_id: str, usd: float) -> None:
    conn.execute("UPDATE clips SET cost_usd = cost_usd + ? WHERE id = ?", (usd, clip_id))
    conn.commit()


def get(conn: sqlite3.Connection, clip_id: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM clips WHERE id = ?", (clip_id,)).fetchone()


def by_status(conn: sqlite3.Connection, status: str, limit: int = 100) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM clips WHERE status = ? ORDER BY created_at LIMIT ?",
        (status, limit),
    ).fetchall()


def recent(conn: sqlite3.Connection, limit: int = 10) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM clips ORDER BY created_at DESC LIMIT ?", (limit,)
    ).fetchall()


def known_phashes(conn: sqlite3.Connection, exclude: str | None = None) -> list[str]:
    rows = conn.execute(
        "SELECT id, phash FROM clips WHERE phash IS NOT NULL"
    ).fetchall()
    return [r["phash"] for r in rows if r["id"] != exclude]


def status_counts(conn: sqlite3.Connection) -> dict[str, int]:
    rows = conn.execute("SELECT status, COUNT(*) n FROM clips GROUP BY status").fetchall()
    return {r["status"]: r["n"] for r in rows}


def published_with_metrics(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        """SELECT * FROM clips
           WHERE status = 'published' AND views IS NOT NULL
           ORDER BY published_at"""
    ).fetchall()


def record_digest(
    conn: sqlite3.Connection, *, n_published: int, body: str, rules_applied: bool
) -> None:
    conn.execute(
        "INSERT INTO digests (created_at, n_published, body, rules_applied) VALUES (?, ?, ?, ?)",
        (now(), n_published, body, int(rules_applied)),
    )
    conn.commit()


def rows_to_dicts(rows: Iterable[sqlite3.Row]) -> list[dict[str, Any]]:
    return [dict(r) for r in rows]
