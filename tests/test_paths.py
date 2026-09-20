"""Where a clip's file is, once the project folder has moved.

Rows used to store absolute paths. Moving the checkout from one folder to
another left every clip pointing at a directory that no longer existed,
and the same happens between the host and /app in the container.
"""

import sqlite3
from pathlib import Path

from factory import channels, db, settings


def test_a_relative_path_resolves_under_root(sandbox):
    assert db.video_file({"video_path": "data/work/main/abc/clip.mp4"}) == settings.ROOT / "data/work/main/abc/clip.mp4"


def test_an_old_absolute_path_that_is_gone_is_retried_under_root(sandbox):
    old = "/Users/someone/Library/Application Support/x/shorts-factory/data/work/main/abc/clip.mp4"
    assert db.video_file({"video_path": old}) == settings.ROOT / "data/work/main/abc/clip.mp4"


def test_an_absolute_path_that_exists_is_kept(sandbox, tmp_path):
    f = tmp_path / "clip.mp4"; f.write_bytes(b"x")
    assert db.video_file({"video_path": str(f)}) == f


def test_nothing_stored_is_none(sandbox):
    assert db.video_file({"video_path": None}) is None


def test_the_writer_stores_relative_to_root(sandbox):
    inside = settings.ROOT / "data" / "work" / "main" / "zzz" / "clip.mp4"
    assert db.relative_video_path(inside) == "data/work/main/zzz/clip.mp4"
    assert db.relative_video_path(Path("/elsewhere/clip.mp4")) == "/elsewhere/clip.mp4"


def test_migrate_rewrites_old_absolute_rows_once(sandbox):
    with db.connect() as conn:
        db.migrate(conn)
        channels.create(conn, name="Main", channel_id="main")
        cid = db.insert_clip(conn, channel_id="main", generator="physics", variant="marble_race", seed=1, params={}, hook="", plan_why="t")
        conn.execute("UPDATE clips SET video_path = ? WHERE id = ?",
                     ("/old/place/shorts-factory/data/work/main/%s/clip.mp4" % cid, cid))
        conn.commit()
        done = db.migrate(conn)
        assert any("video paths" in d for d in done)
        assert db.get(conn, cid)["video_path"] == f"data/work/main/{cid}/clip.mp4"
        assert not any("video paths" in d for d in db.migrate(conn))  # idempotent
