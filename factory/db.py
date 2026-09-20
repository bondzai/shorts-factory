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

    conn.execute("""CREATE TABLE IF NOT EXISTS tasks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_id  TEXT NOT NULL DEFAULT 'main' REFERENCES channels (id),
    kind        TEXT NOT NULL,
    params_json TEXT NOT NULL DEFAULT '{}',
    status      TEXT NOT NULL DEFAULT 'queued',
    priority    INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL,
    created_by  TEXT,
    claimed_at  TEXT,
    claimed_by  TEXT,
    finished_at TEXT,
    result_json TEXT,
    error       TEXT,
    clip_id     TEXT
);""")

    conn.execute(
        """CREATE TABLE IF NOT EXISTS settings (
               section TEXT NOT NULL, key TEXT NOT NULL, value_json TEXT NOT NULL,
               updated_at TEXT NOT NULL, PRIMARY KEY (section, key))"""
    )

    if "purged_at" not in _columns(conn, "clips"):
        conn.execute("ALTER TABLE clips ADD COLUMN purged_at TEXT")
        done.append("clips.purged_at added")

    # The two levers Studio's own analysis points at, plus the record that
    # makes pulling one of them measurable.
    for column, ddl in (
        ("deleted_at", "TEXT"),  # the bin: hidden, files kept, restorable
        ("hook_text", "TEXT"),
        ("comment_prompt", "TEXT"),
        ("title_history_json", "TEXT NOT NULL DEFAULT '[]'"),
    ):
        if column not in _columns(conn, "clips"):
            conn.execute(f"ALTER TABLE clips ADD COLUMN {column} {ddl}")
            done.append(f"clips.{column} added")

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
    "params_json", "hook_text", "comment_prompt", "title_history_json", "deleted_at",
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
        """SELECT * FROM clips WHERE channel_id = ? AND status = ? AND deleted_at IS NULL
           ORDER BY created_at LIMIT ?""",
        (channel_id, status, limit),
    ).fetchall()


def recent(conn: sqlite3.Connection, channel_id: str, limit: int = 10) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM clips WHERE channel_id = ? AND deleted_at IS NULL ORDER BY created_at DESC LIMIT ?",
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
        # A binned clip is off the table unless it already shipped: YouTube
        # does not know about the bin.
        "SELECT id, phash FROM clips"
        " WHERE channel_id = ? AND phash IS NOT NULL"
        "   AND status NOT IN ('qc_rejected', 'failed')"
        "   AND (deleted_at IS NULL OR status = 'published')",
        (channel_id,),
    ).fetchall()
    return [r["phash"] for r in rows if r["id"] != exclude]


def status_counts(conn: sqlite3.Connection, channel_id: str) -> dict[str, int]:
    rows = conn.execute(
        "SELECT status, COUNT(*) n FROM clips WHERE channel_id = ? AND deleted_at IS NULL GROUP BY status",
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
           WHERE channel_id = ? AND deleted_at IS NULL AND status = 'published' AND views IS NOT NULL
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


# --- paging: the one shape every list on the page uses --------------------------
# A list endpoint takes page/page_size/sort and answers {items, total, page,
# page_size}. Sort fields are whitelisted per table: the page never sends SQL.

PAGE_SIZES = (25, 50, 100)
CLIP_SORTS = {"created_at", "title", "status", "views", "avg_view_pct", "swipe_away_pct", "sameness", "duration_s"}
TASK_SORTS = {"id", "kind", "status", "created_at", "claimed_by"}
WORK_SORTS = {"created_at", "title", "phase", "views", "avg_view_pct", "swipe_away_pct"}
# One vocabulary for where a piece of work is, whether it is still a task or
# already a clip. Ordered the way work moves. Called a phase, because a stage
# is what the marbles run down.
PHASES = ["queued", "rendering", "to_review", "approved", "published", "rejected", "failed", "cancelled", "done"]
_CLIP_PHASE = ("CASE status WHEN 'planned' THEN 'queued' WHEN 'rendered' THEN 'rendering' "
               "WHEN 'described' THEN 'rendering' WHEN 'awaiting_approval' THEN 'to_review' "
               "WHEN 'qc_rejected' THEN 'rejected' ELSE status END")
_TASK_PHASE = "CASE status WHEN 'claimed' THEN 'rendering' ELSE status END"
RUN_SORTS = {"id", "kind", "status", "started_at", "cost_usd"}


def page_args(page: int | None, page_size: int | None) -> tuple[int, int]:
    size = page_size if page_size in PAGE_SIZES else PAGE_SIZES[0]
    return max(1, int(page or 1)), size


def _order(sort: str | None, direction: str | None, allowed: set[str], default: str) -> str:
    field = sort if sort in allowed else default
    return f" ORDER BY {field} {'ASC' if direction == 'asc' else 'DESC'}, id DESC"


def search_clips(
    conn: sqlite3.Connection,
    channel_id: str,
    *,
    status: str | None = None,
    generator: str | None = None,
    variant: str | None = None,
    query: str | None = None,
    limit: int = 200,
    binned: bool = False,
    sort: str | None = None,
    direction: str | None = None,
    page: int | None = None,
    page_size: int | None = None,
) -> list[sqlite3.Row] | tuple[list[sqlite3.Row], int]:
    """Rows, or (rows, total) when a page is asked for."""
    sql = "SELECT * FROM clips WHERE channel_id = ? AND deleted_at IS " + ("NOT NULL" if binned else "NULL")
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
    if page is None:
        sql += " ORDER BY created_at DESC LIMIT ?"
        args.append(limit)
        return conn.execute(sql, args).fetchall()
    total = conn.execute(sql.replace("SELECT *", "SELECT COUNT(*)", 1), args).fetchone()[0]
    p, size = page_args(page, page_size)
    rows = conn.execute(sql + _order(sort, direction, CLIP_SORTS, "created_at") + " LIMIT ? OFFSET ?",
                        args + [size, (p - 1) * size]).fetchall()
    return rows, total


# --- the task queue: what agents will do next ---------------------------------
# A task is a unit of work any brain can pick up: an external agent over MCP
# with `next_task`, or `factory work` with the built-in agents. Same table,
# same instructions, so switching brains changes nothing about the work.

TASK_QUEUED, TASK_CLAIMED, TASK_DONE, TASK_FAILED, TASK_CANCELLED = (
    "queued", "claimed", "done", "failed", "cancelled")


def enqueue_task(
    conn: sqlite3.Connection, channel_id: str, kind: str, params: dict[str, Any],
    *, by: str = "human", priority: int = 0,
) -> int:
    cur = conn.execute(
        """INSERT INTO tasks (channel_id, kind, params_json, status, priority, created_at, created_by)
           VALUES (?, ?, ?, 'queued', ?, ?, ?)""",
        (channel_id, kind, json.dumps(params), priority, now(), by),
    )
    conn.commit()
    return int(cur.lastrowid)


def release_stale_tasks(conn: sqlite3.Connection, minutes: int = 45) -> int:
    """An agent that claimed a task and vanished must not hold it forever."""
    cur = conn.execute(
        """UPDATE tasks SET status = 'queued', claimed_at = NULL, claimed_by = NULL
           WHERE status = 'claimed' AND claimed_at < datetime('now', ?)""",
        (f"-{minutes} minutes",),
    )
    conn.commit()
    return cur.rowcount


def claim_task(
    conn: sqlite3.Connection, worker: str, *, channel_id: str | None = None,
    kinds: list[str] | None = None,
) -> sqlite3.Row | None:
    release_stale_tasks(conn)
    sql = "SELECT * FROM tasks WHERE status = 'queued'"
    args: list[Any] = []
    if channel_id:
        sql += " AND channel_id = ?"; args.append(channel_id)
    if kinds:
        sql += f" AND kind IN ({','.join('?' * len(kinds))})"; args.extend(kinds)
    sql += " ORDER BY priority DESC, id LIMIT 1"
    row = conn.execute(sql, args).fetchone()
    if row is None:
        return None
    # The UPDATE re-checks status so two workers cannot take the same task.
    cur = conn.execute(
        "UPDATE tasks SET status = 'claimed', claimed_at = ?, claimed_by = ? WHERE id = ? AND status = 'queued'",
        (now(), worker, row["id"]),
    )
    conn.commit()
    if cur.rowcount != 1:
        return claim_task(conn, worker, channel_id=channel_id, kinds=kinds)
    return conn.execute("SELECT * FROM tasks WHERE id = ?", (row["id"],)).fetchone()


def claimed_make_clip(conn: sqlite3.Connection, channel_id: str) -> sqlite3.Row | None:
    """The make-clip task an agent is holding on this channel, oldest first."""
    return conn.execute(
        """SELECT * FROM tasks WHERE channel_id = ? AND status = 'claimed'
           AND kind = 'make-clip' ORDER BY claimed_at LIMIT 1""",
        (channel_id,),
    ).fetchone()


def attach_clip_to_claimed_task(conn: sqlite3.Connection, channel_id: str, clip_id: str) -> int | None:
    """When an agent renders while holding a make-clip task, that render is the
    task's clip. Attached at render time so the step tracker can show progress
    before the agent reports; the agent's own finish_task confirms it."""
    row = conn.execute(
        """SELECT id FROM tasks WHERE channel_id = ? AND status = 'claimed'
           AND kind = 'make-clip' AND clip_id IS NULL ORDER BY claimed_at LIMIT 1""",
        (channel_id,),
    ).fetchone()
    if row is None:
        return None
    conn.execute("UPDATE tasks SET clip_id = ? WHERE id = ?", (clip_id, row["id"]))
    conn.commit()
    return int(row["id"])


def finish_task(
    conn: sqlite3.Connection, task_id: int, *, ok: bool, result: Any = None,
    error: str | None = None, clip_id: str | None = None,
) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    if row is None:
        raise ValueError(f"no task {task_id}")
    if row["status"] != TASK_CLAIMED:
        raise ValueError(f"task {task_id} is {row['status']}, not claimed")
    conn.execute(
        """UPDATE tasks SET status = ?, finished_at = ?, result_json = ?, error = ?,
                            clip_id = COALESCE(?, clip_id)
           WHERE id = ?""",
        (TASK_DONE if ok else TASK_FAILED, now(), json.dumps(result), error, clip_id, task_id),
    )
    conn.commit()
    return conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()


def cancel_task(conn: sqlite3.Connection, task_id: int) -> None:
    row = conn.execute("SELECT status FROM tasks WHERE id = ?", (task_id,)).fetchone()
    if row is None:
        raise ValueError(f"no task {task_id}")
    if row["status"] not in (TASK_QUEUED, TASK_CLAIMED):
        raise ValueError(f"task {task_id} is already {row['status']}")
    conn.execute("UPDATE tasks SET status = 'cancelled', finished_at = ? WHERE id = ?", (now(), task_id))
    conn.commit()


def delete_tasks(conn: sqlite3.Connection, task_ids: list[int]) -> list[int]:
    """Remove task rows. A claimed task is cancelled first so nothing is
    working on a row that no longer exists; the clips it made are untouched."""
    done = []
    for task_id in task_ids:
        row = conn.execute("SELECT id, status FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if row is None:
            continue
        conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        done.append(int(task_id))
    conn.commit()
    return done


def clear_finished_tasks(conn: sqlite3.Connection, channel_id: str) -> int:
    cur = conn.execute(
        "DELETE FROM tasks WHERE channel_id = ? AND status IN ('done', 'failed', 'cancelled')", (channel_id,)
    )
    conn.commit()
    return cur.rowcount


def tasks(
    conn: sqlite3.Connection, channel_id: str | None = None, status: str | None = None, limit: int = 100,
    *, kind: str | None = None, query: str | None = None, sort: str | None = None, direction: str | None = None,
    page: int | None = None, page_size: int | None = None,
) -> list[sqlite3.Row] | tuple[list[sqlite3.Row], int]:
    sql = "SELECT * FROM tasks WHERE 1 = 1"
    args: list[Any] = []
    if channel_id:
        sql += " AND channel_id = ?"; args.append(channel_id)
    if status:
        sql += " AND status = ?"; args.append(status)
    if kind:
        sql += " AND kind = ?"; args.append(kind)
    if query:
        sql += " AND (params_json LIKE ? OR result_json LIKE ? OR error LIKE ? OR claimed_by LIKE ?)"
        args.extend([f"%{query}%"] * 4)
    if page is None:
        sql += " ORDER BY CASE status WHEN 'claimed' THEN 0 WHEN 'queued' THEN 1 ELSE 2 END, priority DESC, id DESC LIMIT ?"
        args.append(limit)
        return conn.execute(sql, args).fetchall()
    total = conn.execute(sql.replace("SELECT *", "SELECT COUNT(*)", 1), args).fetchone()[0]
    p, size = page_args(page, page_size)
    order = (" ORDER BY CASE status WHEN 'claimed' THEN 0 WHEN 'queued' THEN 1 ELSE 2 END, priority DESC, id DESC"
             if not sort else _order(sort, direction, TASK_SORTS, "id"))
    rows = conn.execute(sql + order + " LIMIT ? OFFSET ?", args + [size, (p - 1) * size]).fetchall()
    return rows, total


def work(
    conn: sqlite3.Connection, channel_id: str, *, phase: str | None = None, variant: str | None = None,
    query: str | None = None, sort: str | None = None, direction: str | None = None,
    page: int | None = None, page_size: int | None = None,
) -> tuple[list[sqlite3.Row], int, dict[str, int]]:
    """Every piece of work on a channel as one list: a task until it has a
    clip, the clip from then on. A task is what was asked for and a clip is
    what came of it, and showing them on two screens made the reader work
    out which one to look at. Returns (rows, total, count per phase); each
    row carries row_kind ('task' | 'clip') and the id of the underlying row."""
    base = f"""
        WITH w AS (
            SELECT 'clip' AS row_kind, id AS id, NULL AS task_id, id AS clip_id, status,
                   {_CLIP_PHASE} AS phase, title, variant, created_at,
                   views, avg_view_pct, swipe_away_pct,
                   COALESCE(title, '') || ' ' || id || ' ' || COALESCE(render_desc, '') AS haystack
            FROM clips WHERE channel_id = ? AND deleted_at IS NULL
            UNION ALL
            SELECT 'task', 't' || id, id, NULL, status,
                   {_TASK_PHASE}, kind || ' ' || params_json, json_extract(params_json, '$.variant'), created_at,
                   NULL, NULL, NULL,
                   kind || ' ' || params_json || ' ' || COALESCE(result_json, '') || ' ' || COALESCE(error, '') || ' ' || COALESCE(claimed_by, '')
            FROM tasks WHERE channel_id = ? AND clip_id IS NULL
        )
        SELECT * FROM w WHERE 1 = 1"""
    args: list[Any] = [channel_id, channel_id]
    counts = {r["phase"]: r["n"] for r in conn.execute(
        base.replace("SELECT * FROM w WHERE 1 = 1", "SELECT phase, COUNT(*) n FROM w GROUP BY phase"), args)}
    if phase:
        base += " AND phase = ?"; args.append(phase)
    if variant:
        base += " AND variant = ?"; args.append(variant)
    if query:
        base += " AND haystack LIKE ?"; args.append(f"%{query}%")
    total = conn.execute(base.replace("SELECT * FROM w", "SELECT COUNT(*) FROM w", 1), args).fetchone()[0]
    p, size = page_args(page, page_size)
    order = _order(sort, direction, WORK_SORTS, "created_at").replace(", id DESC", ", row_kind DESC, id DESC")
    rows = conn.execute(base + order + " LIMIT ? OFFSET ?", args + [size, (p - 1) * size]).fetchall()
    return rows, total, counts


def get_task(conn: sqlite3.Connection, task_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()


def task_counts(conn: sqlite3.Connection, channel_id: str) -> dict[str, int]:
    rows = conn.execute(
        "SELECT status, COUNT(*) n FROM tasks WHERE channel_id = ? GROUP BY status", (channel_id,)
    ).fetchall()
    return {r["status"]: r["n"] for r in rows}


def overrides(conn: sqlite3.Connection) -> dict[tuple[str, str], Any]:
    rows = conn.execute("SELECT section, key, value_json FROM settings").fetchall()
    return {(r["section"], r["key"]): json.loads(r["value_json"]) for r in rows}


def set_override(conn: sqlite3.Connection, section: str, key: str, value: Any) -> None:
    conn.execute(
        """INSERT INTO settings (section, key, value_json, updated_at) VALUES (?, ?, ?, ?)
           ON CONFLICT(section, key) DO UPDATE SET value_json = excluded.value_json,
                                                  updated_at = excluded.updated_at""",
        (section, key, json.dumps(value), now()),
    )
    conn.commit()


def clear_override(conn: sqlite3.Connection, section: str, key: str) -> None:
    conn.execute("DELETE FROM settings WHERE section = ? AND key = ?", (section, key))
    conn.commit()


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


def runs_page(
    conn: sqlite3.Connection, channel_id: str, *, status: str | None = None, kind: str | None = None,
    sort: str | None = None, direction: str | None = None, page: int | None = None, page_size: int | None = None,
) -> tuple[list[sqlite3.Row], int]:
    sql = "SELECT * FROM runs WHERE channel_id = ?"
    args: list[Any] = [channel_id]
    if status:
        sql += " AND status = ?"; args.append(status)
    if kind:
        sql += " AND kind = ?"; args.append(kind)
    total = conn.execute(sql.replace("SELECT *", "SELECT COUNT(*)", 1), args).fetchone()[0]
    p, size = page_args(page, page_size)
    rows = conn.execute(sql + _order(sort, direction, RUN_SORTS, "id") + " LIMIT ? OFFSET ?",
                        args + [size, (p - 1) * size]).fetchall()
    return rows, total


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
