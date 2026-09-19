import sqlite3

import pytest

from factory import channels, db, gc, pipeline, settings

CH = "gravity-lab"


@pytest.fixture
def conn(sandbox):
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.executescript(db.SCHEMA.read_text())
    channels.create(connection, name="Gravity Lab", channel_id=CH)
    yield connection
    connection.close()


def make_clip_files(sandbox, clip_id, *, with_final=True):
    clip_dir = settings.load().work_dir / CH / clip_id
    clip_dir.mkdir(parents=True, exist_ok=True)
    (clip_dir / "video.mp4").write_bytes(b"x" * 3000)
    (clip_dir / "audio.wav").write_bytes(b"y" * 2000)
    if with_final:
        (clip_dir / "clip.mp4").write_bytes(b"z" * 1000)
    return clip_dir


def insert(conn, clip_id_seed=1, **fields):
    clip_id = db.insert_clip(
        conn, channel_id=CH, generator="physics", variant="marble_race",
        seed=clip_id_seed, params={}, hook="h", plan_why="w",
    )
    if fields:
        db.update(conn, clip_id, **fields)
    return clip_id


# --- intermediates -----------------------------------------------------------

def test_intermediates_go_once_the_mux_exists(sandbox):
    clip_dir = make_clip_files(sandbox, "abc")
    swept = gc.sweep_intermediates(clip_dir)
    assert swept.files == 2
    assert swept.bytes_freed == 5000
    assert not (clip_dir / "video.mp4").exists()
    assert (clip_dir / "clip.mp4").exists()


def test_intermediates_are_kept_when_the_mux_is_missing(sandbox):
    clip_dir = make_clip_files(sandbox, "abc", with_final=False)
    assert gc.sweep_intermediates(clip_dir).files == 0
    assert (clip_dir / "video.mp4").exists()


def test_sweeping_twice_is_harmless(sandbox):
    clip_dir = make_clip_files(sandbox, "abc")
    gc.sweep_intermediates(clip_dir)
    assert gc.sweep_intermediates(clip_dir).files == 0


# --- settled clips -----------------------------------------------------------

def test_a_fresh_rejected_clip_is_left_alone(conn, sandbox):
    clip_dir = make_clip_files(sandbox, "fresh")
    insert(conn, status="qc_rejected", video_path=str(clip_dir / "clip.mp4"))
    assert gc.sweep_clips(conn).clips == []
    assert (clip_dir / "clip.mp4").exists()


def test_an_old_rejected_clip_is_removed_and_marked(conn, sandbox):
    clip_dir = make_clip_files(sandbox, "old")
    clip_id = insert(conn, status="qc_rejected", video_path=str(clip_dir / "clip.mp4"))
    conn.execute("UPDATE clips SET created_at = datetime('now', '-30 days') WHERE id = ?", (clip_id,))
    swept = gc.sweep_clips(conn)
    assert swept.clips == [clip_id]
    assert not (clip_dir / "clip.mp4").exists()
    assert db.get(conn, clip_id)["purged_at"] is not None


def test_a_queued_clip_is_never_swept(conn, sandbox):
    clip_dir = make_clip_files(sandbox, "waiting")
    clip_id = insert(conn, status="awaiting_approval", video_path=str(clip_dir / "clip.mp4"))
    conn.execute("UPDATE clips SET created_at = datetime('now', '-99 days') WHERE id = ?", (clip_id,))
    assert gc.sweep_clips(conn).clips == []
    assert (clip_dir / "clip.mp4").exists()


def test_dry_run_deletes_nothing(conn, sandbox):
    clip_dir = make_clip_files(sandbox, "old")
    clip_id = insert(conn, status="qc_rejected", video_path=str(clip_dir / "clip.mp4"))
    conn.execute("UPDATE clips SET created_at = datetime('now', '-30 days') WHERE id = ?", (clip_id,))
    swept = gc.sweep_clips(conn, dry_run=True)
    assert swept.clips == [clip_id]
    assert (clip_dir / "clip.mp4").exists()
    assert db.get(conn, clip_id)["purged_at"] is None


def test_a_purged_clip_is_not_swept_again(conn, sandbox):
    clip_dir = make_clip_files(sandbox, "old")
    clip_id = insert(conn, status="qc_rejected", video_path=str(clip_dir / "clip.mp4"))
    conn.execute("UPDATE clips SET created_at = datetime('now', '-30 days') WHERE id = ?", (clip_id,))
    gc.sweep_clips(conn)
    assert gc.sweep_clips(conn).clips == []


def test_negative_retention_keeps_forever(conn, sandbox, monkeypatch):
    raw = settings.load().raw
    monkeypatch.setitem(raw, "retention", {"rejected_days": -1, "published_days": -1})
    clip_dir = make_clip_files(sandbox, "old")
    clip_id = insert(conn, status="qc_rejected", video_path=str(clip_dir / "clip.mp4"))
    conn.execute("UPDATE clips SET created_at = datetime('now', '-99 days') WHERE id = ?", (clip_id,))
    assert gc.sweep_clips(conn).clips == []


def test_sweeping_is_scoped_to_one_channel(conn, sandbox):
    channels.create(conn, name="HODL", channel_id="hodl")
    mine = make_clip_files(sandbox, "mine")
    clip_id = insert(conn, status="qc_rejected", video_path=str(mine / "clip.mp4"))
    conn.execute("UPDATE clips SET created_at = datetime('now', '-30 days') WHERE id = ?", (clip_id,))
    assert gc.sweep_clips(conn, channel_id="hodl").clips == []
    assert gc.sweep_clips(conn, channel_id=CH).clips == [clip_id]


# --- resume ------------------------------------------------------------------

def test_stuck_finds_clips_between_stages(conn):
    rendered = insert(conn, 1, status="rendered")
    described = insert(conn, 2, status="described")
    insert(conn, 3, status="planned")
    insert(conn, 4, status="awaiting_approval")
    assert {r["id"] for r in pipeline.stuck(conn, CH)} == {rendered, described}


def test_failed_clips_are_opt_in(conn):
    failed = insert(conn, 1, status="failed")
    assert pipeline.stuck(conn, CH) == []
    assert [r["id"] for r in pipeline.stuck(conn, CH, include_failed=True)] == [failed]


def test_stuck_does_not_cross_channels(conn):
    channels.create(conn, name="HODL", channel_id="hodl")
    insert(conn, 1, status="rendered")
    assert pipeline.stuck(conn, "hodl") == []


def test_a_purged_clip_cannot_reuse_its_render(conn, sandbox):
    """The file is gone, so resume must re-render rather than trust the row."""
    clip_dir = make_clip_files(sandbox, "purged")
    clip_id = insert(
        conn, status="rendered", video_path=str(clip_dir / "clip.mp4"),
        duration_s=17.4, purged_at=db.now(),
    )
    row = db.get(conn, clip_id)
    assert row["purged_at"] is not None
    assert row["duration_s"] == 17.4
