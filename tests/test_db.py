import sqlite3

import pytest

from factory import db
from factory.models import AWAITING_APPROVAL, PLANNED


@pytest.fixture
def conn():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.executescript(db.SCHEMA.read_text())
    yield connection
    connection.close()


def _insert(conn, seed=7, generator="physics", variant="marble_race"):
    return db.insert_clip(
        conn,
        generator=generator,
        variant=variant,
        seed=seed,
        params={},
        hook="marbles already rolling",
        plan_why="first clip",
    )


def test_insert_starts_planned(conn):
    clip_id = _insert(conn)
    row = db.get(conn, clip_id)
    assert row["status"] == PLANNED
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


def test_known_phashes_excludes_the_clip_itself(conn):
    a = _insert(conn, seed=1)
    b = _insert(conn, seed=2)
    db.update(conn, a, phash="a" * 64)
    db.update(conn, b, phash="b" * 64)
    assert db.known_phashes(conn, exclude=a) == ["b" * 64]


def test_status_counts(conn):
    _insert(conn, seed=1)
    second = _insert(conn, seed=2)
    db.update(conn, second, status=AWAITING_APPROVAL)
    assert db.status_counts(conn) == {PLANNED: 1, AWAITING_APPROVAL: 1}
