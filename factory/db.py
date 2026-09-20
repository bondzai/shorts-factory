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


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def migrate(conn: sqlite3.Connection) -> list[str]:
    """Bring a database written before channels existed up to date.

    Runs on every connect and does nothing when there is nothing to do. A fresh
    database gets the right shape straight from schema.sql; this exists for the
    one already holding published clips.
    """
    from .channels import DEFAULT_ID

    done: list[str] = []
    for table in ("clips", "digests"):
        if "channel_id" not in _columns(conn, table):
            conn.execute(
                f"ALTER TABLE {table} ADD COLUMN channel_id TEXT NOT NULL DEFAULT '{DEFAULT_ID}'"
            )
            done.append(f"{table}.channel_id added")

    if "purged_at" not in _columns(conn, "clips"):
        conn.execute("ALTER TABLE clips ADD COLUMN purged_at TEXT")
        done.append("clips.purged_at added")

    if "proposals_json" not in _columns(conn, "digests"):
        conn.execute("ALTER TABLE digests ADD COLUMN proposals_json TEXT NOT NULL DEFAULT '[]'")
        done.append("digests.proposals_json added")

    has_channel = conn.execute(
        "SELECT 1 FROM channels WHERE id = ?", (DEFAULT_ID,)
    ).fetchone()
    orphans = conn.execute(
        "SELECT COUNT(*) n FROM clips WHERE channel_id IS NULL OR channel_id = ''"
    ).fetchone()["n"]
    clips_exist = conn.execute("SELECT COUNT(*) n FROM clips").fetchone()["n"]

    if not has_channel and (clips_exist or orphans):
        driver = settings.load().raw["publish"]["driver"]
        conn.execute(
            """INSERT INTO channels
               (id, created_at, name, handle, platform, driver, variants_json, cadence, active, note)
               VALUES (?, ?, 'Main channel', NULL, 'youtube', ?, '[]', 1, 1,
                       'created by migration from a single-channel database')""",
            (DEFAULT_ID, now(), driver),
        )
        done.append("default channel created")
    if orphans:
        conn.execute(
            "UPDATE clips SET channel_id = ? WHERE channel_id IS NULL OR channel_id = ''",
            (DEFAULT_ID,),
        )
        done.append(f"{orphans} clips adopted")
    if done:
        conn.commit()
    return done


def connect() -> sqlite3.Connection:
    cfg = settings.load()
    cfg.ensure_dirs()
    conn = sqlite3.connect(cfg.db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    # The web UI, the CLI and an agent over MCP are three processes on one file.
    # WAL lets readers work while one writer holds the lock; the busy timeout
    # makes a second writer wait its turn instead of failing outright.
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 10000")
    conn.executescript(SCHEMA.read_text())
    migrate(conn)
    return conn


def insert_clip(
    conn: sqlite3.Connection,
    *,
    channel_id: str,
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
           (id, channel_id, created_at, generator, variant, seed, params_json,
            hook, plan_why, status)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'planned')""",
        (
            clip_id, channel_id, now(), generator, variant, seed,
            json.dumps(params), hook, plan_why,
        ),
    )
    conn.commit()
    return clip_id


_ALLOWED_COLUMNS = {
    "status", "video_path", "render_desc", "facts_json",
    "duration_s", "width", "height", "fps",
    "loudness_lufs", "phash", "sameness", "title", "description",
    "hashtags_json", "qc_json", "reject_reason", "platform", "remote_id",
    "published_at", "views", "avg_view_pct", "swipe_away_pct", "likes",
    "metrics_at", "purged_at",
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


def by_status(
    conn: sqlite3.Connection, channel_id: str, status: str, limit: int = 100
) -> list[sqlite3.Row]:
    return conn.execute(
        """SELECT * FROM clips WHERE channel_id = ? AND status = ?
           ORDER BY created_at LIMIT ?""",
        (channel_id, status, limit),
    ).fetchall()


def recent(conn: sqlite3.Connection, channel_id: str, limit: int = 10) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM clips WHERE channel_id = ? ORDER BY created_at DESC LIMIT ?",
        (channel_id, limit),
    ).fetchall()


def known_phashes(
    conn: sqlite3.Connection, channel_id: str, exclude: str | None = None
) -> list[str]:
    """Sameness is judged within a channel — two channels may share a look.

    Only clips that can still reach the platform count. The gate exists for
    the inauthentic-content policy, which is about what gets uploaded; a clip
    that QC threw out is one the platform never sees. Counting it did real
    damage: a funnel_drop scored 0.984 against a rejected funnel and 0.731
    against everything that could ship, and was refused for resembling a clip
    that does not exist anywhere but this table. Every rejection was quietly
    shrinking the channel's future.
    """
    rows = conn.execute(
        "SELECT id, phash FROM clips"
        " WHERE channel_id = ? AND phash IS NOT NULL"
        "   AND status NOT IN ('qc_rejected', 'failed')",
        (channel_id,),
    ).fetchall()
    return [r["phash"] for r in rows if r["id"] != exclude]


def status_counts(conn: sqlite3.Connection, channel_id: str) -> dict[str, int]:
    rows = conn.execute(
        "SELECT status, COUNT(*) n FROM clips WHERE channel_id = ? GROUP BY status",
        (channel_id,),
    ).fetchall()
    return {r["status"]: r["n"] for r in rows}


def spend(conn: sqlite3.Connection, channel_id: str | None = None) -> float:
    if channel_id:
        row = conn.execute(
            "SELECT SUM(cost_usd) s FROM clips WHERE channel_id = ?", (channel_id,)
        ).fetchone()
    else:
        row = conn.execute("SELECT SUM(cost_usd) s FROM clips").fetchone()
    return round(row["s"] or 0.0, 4)


def published_with_metrics(conn: sqlite3.Connection, channel_id: str) -> list[sqlite3.Row]:
    return conn.execute(
        """SELECT * FROM clips
           WHERE channel_id = ? AND status = 'published' AND views IS NOT NULL
           ORDER BY published_at""",
        (channel_id,),
    ).fetchall()


def record_digest(
    conn: sqlite3.Connection,
    *,
    channel_id: str,
    n_published: int,
    body: str,
    rules_applied: bool,
    proposals: list[str] | None = None,
) -> None:
    conn.execute(
        """INSERT INTO digests
           (channel_id, created_at, n_published, body, proposals_json, rules_applied)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (
            channel_id, now(), n_published, body,
            json.dumps(proposals or []), int(rules_applied),
        ),
    )
    conn.commit()


def latest_digest(conn: sqlite3.Connection, channel_id: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM digests WHERE channel_id = ? ORDER BY id DESC LIMIT 1",
        (channel_id,),
    ).fetchone()


def search_clips(
    conn: sqlite3.Connection,
    channel_id: str,
    *,
    status: str | None = None,
    generator: str | None = None,
    variant: str | None = None,
    query: str | None = None,
    limit: int = 200,
) -> list[sqlite3.Row]:
    sql = "SELECT * FROM clips WHERE channel_id = ?"
    args: list[Any] = [channel_id]
    if status:
        sql += " AND status = ?"
        args.append(status)
    if generator:
        sql += " AND generator = ?"
        args.append(generator)
    if variant:
        sql += " AND variant = ?"
        args.append(variant)
    if query:
        sql += " AND (title LIKE ? OR id LIKE ? OR render_desc LIKE ?)"
        args.extend([f"%{query}%"] * 3)
    sql += " ORDER BY created_at DESC LIMIT ?"
    args.append(limit)
    return conn.execute(sql, args).fetchall()


def start_run(conn: sqlite3.Connection, channel_id: str, kind: str) -> int:
    cursor = conn.execute(
        "INSERT INTO runs (channel_id, started_at, kind, status) VALUES (?, ?, ?, 'running')",
        (channel_id, now(), kind),
    )
    conn.commit()
    return int(cursor.lastrowid)


def finish_run(
    conn: sqlite3.Connection,
    run_id: int,
    *,
    status: str,
    detail: str = "",
    log: str = "",
    cost_usd: float = 0.0,
) -> None:
    conn.execute(
        """UPDATE runs SET ended_at = ?, status = ?, detail = ?, log = ?, cost_usd = ?
           WHERE id = ?""",
        (now(), status, detail, log, cost_usd, run_id),
    )
    conn.commit()
    # Every surface finishes a run through here, so one hook covers the CLI,
    # the web UI, an agent over MCP and cron alike.
    row = conn.execute(
        "SELECT channel_id, kind FROM runs WHERE id = ?", (run_id,)
    ).fetchone()
    if row is None:
        return
    from . import notify

    try:
        notify.run_finished(
            channel_id=row["channel_id"],
            kind=row["kind"],
            status=status,
            detail=detail,
            cost_usd=cost_usd,
            waiting=status_counts(conn, row["channel_id"]).get("awaiting_approval", 0),
        )
    except Exception:  # pragma: no cover - notifying must never fail a run
        pass


def recent_runs(
    conn: sqlite3.Connection, channel_id: str | None = None, limit: int = 20
) -> list[sqlite3.Row]:
    if channel_id:
        return conn.execute(
            "SELECT * FROM runs WHERE channel_id = ? ORDER BY id DESC LIMIT ?",
            (channel_id, limit),
        ).fetchall()
    return conn.execute("SELECT * FROM runs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()


def rows_to_dicts(rows: Iterable[sqlite3.Row]) -> list[dict[str, Any]]:
    return [dict(r) for r in rows]
