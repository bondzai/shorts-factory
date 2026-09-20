"""The upload slot, the paste-ready text, and the daily reminder."""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from factory import channels, db, notify, schedule
from factory.models import APPROVED

BKK = ZoneInfo("Asia/Bangkok")


def test_the_next_slot_is_today_if_far_enough_away_else_tomorrow(sandbox):
    early = datetime(2026, 9, 21, 4, 0, tzinfo=BKK)
    assert schedule.next_slot(early) == datetime(2026, 9, 21, 6, 0, tzinfo=BKK)
    late = datetime(2026, 9, 21, 5, 55, tzinfo=BKK)  # inside the lead time
    assert schedule.next_slot(late) == datetime(2026, 9, 22, 6, 0, tzinfo=BKK)
    after = datetime(2026, 9, 21, 12, 0, tzinfo=BKK)
    assert schedule.next_slot(after) == datetime(2026, 9, 22, 6, 0, tzinfo=BKK)


def test_the_slot_is_described_in_both_clocks(sandbox):
    text = schedule.describe(datetime(2026, 9, 21, 6, 0, tzinfo=BKK))
    assert text.startswith("Mon 2026-09-21 06:00 Asia/Bangkok")
    assert "Sun 19:00 New York" in text  # EDT: UTC-4 against UTC+7


def test_upload_text_has_every_heading_in_order(sandbox):
    with db.connect() as conn:
        db.migrate(conn)
        channels.create(conn, name="Main", channel_id="main")
        cid = db.insert_clip(conn, channel_id="main", generator="physics", variant="marble_race", seed=7301, params={}, hook="", plan_why="t")
        db.update(conn, cid, status=APPROVED, title="Pick your marble: red, green or blue", description="Three marbles run 31 bumpers. Green wins by 0.3s.",
                  hashtags_json='["#shorts", "#marblerace"]', comment_prompt="Red, green or blue — which did you back?", hook_text="CALL IT NOW", duration_s=12.5,
                  facts_json='{"course": "bumpers", "theme": "default"}')
        out = schedule.upload_text(conn, cid, now=datetime(2026, 9, 21, 4, 0, tzinfo=BKK))
    text = out["text"]
    order = [text.index(h) for h in ("TITLE\n", "DESCRIPTION\n", "HASHTAGS\n", "PINNED COMMENT\n", "SCHEDULE\n", "METADATA\n")]
    assert order == sorted(order)
    assert "TITLE\nPick your marble: red, green or blue" in text
    assert "HASHTAGS\n#shorts #marblerace" in text
    assert "SCHEDULE\nMon 2026-09-21 06:00 Asia/Bangkok" in text
    assert "course bumpers" in text and "seed 7301" in text and "CALL IT NOW" in text
    assert out["sections"]["PINNED COMMENT"].startswith("Red, green or blue")


def test_upload_text_names_a_missing_clip(sandbox):
    with db.connect() as conn:
        db.migrate(conn)
        with pytest.raises(ValueError, match="no clip"):
            schedule.upload_text(conn, "nope")


def test_the_daily_reminder_counts_approved_clips_and_sends_once(sandbox, monkeypatch):
    monkeypatch.setenv("FACTORY_WEBHOOK_URL", "https://example.invalid/hook")
    posted = []
    monkeypatch.setattr(notify, "post", lambda event, text, **f: posted.append((event, text)) or True)
    with db.connect() as conn:
        db.migrate(conn)
        channels.create(conn, name="Main", channel_id="main")
        assert notify.daily_text(conn) is None  # nothing approved: no reminder
        for i in range(4):
            cid = db.insert_clip(conn, channel_id="main", generator="physics", variant="marble_race", seed=i, params={}, hook="", plan_why="t")
            db.update(conn, cid, status=APPROVED, title=f"Pick your marble number {i}")
        conn.commit()
        text = notify.daily_text(conn)
    assert text.startswith("[main] 4 approved, ready to upload:") and "(+1 more)" in text and "Next slot:" in text
    assert notify.daily() is True
    assert notify.daily() is False  # already sent today
    assert notify.daily(force=True) is True
    assert [e for e, _ in posted] == ["notify.daily", "notify.daily"]


def test_due_reads_the_configured_minute(sandbox, monkeypatch):
    monkeypatch.setattr(notify, "_config", lambda: {"daily_at": "05:45", "webhook_url": "x"})
    assert notify.due(datetime(2026, 9, 21, 5, 44, tzinfo=BKK)) is False
    assert notify.due(datetime(2026, 9, 21, 5, 45, tzinfo=BKK)) is True
    assert notify.due(datetime(2026, 9, 21, 9, 0, tzinfo=BKK)) is True  # late is still due, once
    monkeypatch.setattr(notify, "_config", lambda: {"daily_at": "", "webhook_url": "x"})
    assert notify.due(datetime(2026, 9, 21, 9, 0, tzinfo=BKK)) is False
