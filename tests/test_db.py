import sqlite3

import pytest

from factory import channels, db
from factory.models import AWAITING_APPROVAL, PLANNED

CH = "gravity-lab"
OTHER = "hodl-tales"


@pytest.fixture
def conn(sandbox):
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.executescript(db.SCHEMA.read_text())
    channels.create(connection, name="Gravity Lab", channel_id=CH)
    channels.create(connection, name="HODL Tales", channel_id=OTHER)
    yield connection
    connection.close()


def _insert(conn, channel_id=CH, seed=7):
    return db.insert_clip(
        conn,
        channel_id=channel_id,
        generator="physics",
        variant="marble_race",
        seed=seed,
        params={},
        hook="marbles already rolling",
        plan_why="first clip",
    )


def test_insert_starts_planned(conn):
    clip_id = _insert(conn)
    row = db.get(conn, clip_id)
    assert row["status"] == PLANNED
    assert row["channel_id"] == CH
    assert row["cost_usd"] == 0


def test_update_moves_the_row_forward(conn):
    clip_id = _insert(conn)
    db.update(conn, clip_id, status=AWAITING_APPROVAL, title="Which marble wins?")
    row = db.get(conn, clip_id)
    assert row["status"] == AWAITING_APPROVAL
    assert row["title"] == "Which marble wins?"


def test_update_refuses_unknown_columns(conn):
    clip_id = _insert(conn)
    with pytest.raises(ValueError):
        db.update(conn, clip_id, nonsense=1)


def test_cost_accumulates(conn):
    clip_id = _insert(conn)
    db.add_cost(conn, clip_id, 0.01)
    db.add_cost(conn, clip_id, 0.02)
    assert db.get(conn, clip_id)["cost_usd"] == pytest.approx(0.03)


def test_queries_never_cross_channels(conn):
    mine = _insert(conn, CH, seed=1)
    theirs = _insert(conn, OTHER, seed=2)
    db.update(conn, mine, status=AWAITING_APPROVAL)
    db.update(conn, theirs, status=AWAITING_APPROVAL)

    assert [r["id"] for r in db.by_status(conn, CH, AWAITING_APPROVAL)] == [mine]
    assert [r["id"] for r in db.recent(conn, OTHER)] == [theirs]
    assert db.status_counts(conn, CH) == {AWAITING_APPROVAL: 1}


def test_sameness_history_is_per_channel(conn):
    mine = _insert(conn, CH, seed=1)
    theirs = _insert(conn, OTHER, seed=2)
    db.update(conn, mine, phash="a" * 64)
    db.update(conn, theirs, phash="b" * 64)
    assert db.known_phashes(conn, CH) == ["a" * 64]
    assert db.known_phashes(conn, CH, exclude=mine) == []


def test_spend_splits_by_channel_and_totals(conn):
    mine = _insert(conn, CH, seed=1)
    theirs = _insert(conn, OTHER, seed=2)
    db.add_cost(conn, mine, 0.10)
    db.add_cost(conn, theirs, 0.25)
    assert db.spend(conn, CH) == pytest.approx(0.10)
    assert db.spend(conn) == pytest.approx(0.35)


def test_runs_are_recorded_and_scoped(conn):
    run = db.start_run(conn, CH, "build")
    db.finish_run(conn, run, status="ok", detail="2 reached the queue", cost_usd=0.03)
    db.start_run(conn, OTHER, "plan")
    mine = db.recent_runs(conn, CH)
    assert len(mine) == 1
    assert mine[0]["status"] == "ok"
    assert mine[0]["detail"] == "2 reached the queue"
    assert len(db.recent_runs(conn)) == 2


def test_migration_adopts_clips_from_a_single_channel_database(sandbox):
    old = sqlite3.connect(":memory:")
    old.row_factory = sqlite3.Row
    old.executescript(
        """CREATE TABLE clips (id TEXT PRIMARY KEY, created_at TEXT NOT NULL,
             generator TEXT NOT NULL, variant TEXT, seed INTEGER NOT NULL,
             params_json TEXT NOT NULL, status TEXT NOT NULL, phash TEXT,
             cost_usd REAL NOT NULL DEFAULT 0);
           CREATE TABLE digests (id INTEGER PRIMARY KEY AUTOINCREMENT,
             created_at TEXT NOT NULL, n_published INTEGER NOT NULL,
             body TEXT NOT NULL, rules_applied INTEGER NOT NULL DEFAULT 0);
           INSERT INTO clips (id, created_at, generator, variant, seed, params_json, status)
             VALUES ('old1', '2026-09-01', 'physics', 'marble_race', 1, '{}', 'published');"""
    )
    old.executescript(
        "CREATE TABLE IF NOT EXISTS channels (id TEXT PRIMARY KEY, created_at TEXT NOT NULL,"
        " name TEXT NOT NULL, handle TEXT, platform TEXT NOT NULL DEFAULT 'youtube',"
        " driver TEXT NOT NULL DEFAULT 'manual', variants_json TEXT NOT NULL DEFAULT '[]',"
        " cadence INTEGER NOT NULL DEFAULT 1, active INTEGER NOT NULL DEFAULT 1, note TEXT);"
    )

    steps = db.migrate(old)
    assert any("channel_id added" in s for s in steps)
    assert any("default channel created" in s for s in steps)

    row = old.execute("SELECT channel_id FROM clips WHERE id = 'old1'").fetchone()
    assert row["channel_id"] == channels.DEFAULT_ID
    assert db.migrate(old) == []
    old.close()
