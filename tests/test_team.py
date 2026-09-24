"""The team overview: who is working, on what, and what they did today."""

from datetime import datetime, timedelta, timezone

from factory import channels, db, logs, team
from factory.models import AWAITING_APPROVAL, QC_REJECTED


def setup(conn):
    db.migrate(conn)
    channels.create(conn, name="Gravity Lab", channel_id="main")
    channels.create(conn, name="HODL Tales", channel_id="hodl")


def clip(conn, channel, seed, status):
    cid = db.insert_clip(conn, channel_id=channel, generator="physics", variant="marble_race", seed=seed, params={}, hook="", plan_why="t")
    db.update(conn, cid, status=status, title=f"Pick one {seed}")
    db.add_cost(conn, cid, 0.01)
    return cid


def test_members_come_from_the_tasks_they_claimed(sandbox):
    with db.connect() as conn:
        setup(conn)
        # claude is holding a task on main, with a clip already rendered
        t1 = db.enqueue_task(conn, "main", "make-clip", {"stage": "rockers"}, by="human")
        db.claim_task(conn, "claude-opus-5", channel_id="main")
        c1 = clip(conn, "main", 1, "rendered")
        db.attach_clip_to_claimed_task(conn, "main", c1)
        # codex finished one on hodl earlier today, and it passed QC
        db.enqueue_task(conn, "hodl", "make-clip", {}, by="human")
        db.claim_task(conn, "codex", channel_id="hodl")
        c2 = clip(conn, "hodl", 2, AWAITING_APPROVAL)
        db.finish_task(conn, 2, ok=True, result={"summary": "rendered"}, clip_id=c2)
        # and one that failed QC
        db.enqueue_task(conn, "hodl", "make-clip", {}, by="human")
        db.claim_task(conn, "codex", channel_id="hodl")
        c3 = clip(conn, "hodl", 3, QC_REJECTED)
        db.finish_task(conn, 3, ok=True, clip_id=c3)
        db.enqueue_task(conn, "main", "make-clip", {}, by="human")  # still queued
        view = team.overview(conn)

    names = {m["name"]: m for m in view["members"]}
    assert list(names) == ["claude-opus-5", "codex"]  # working first
    claude = names["claude-opus-5"]
    assert claude["state"] == "working" and claude["task"]["id"] == t1
    assert [t["id"] for t in claude["tasks"]] == [t1] and claude["tasks"][0]["doing"] == claude["doing"]
    assert claude["doing"].startswith("#1 make-clip on main — at rendered, step 2 of 5")
    assert claude["channels"] == ["main"]
    codex = names["codex"]
    assert codex["state"] == "ready" and codex["task"] is None
    assert codex["today"] == {"done": 2, "failed": 0, "clips": 2, "passed_qc": 1, "rejected_qc": 1, "cost_usd": 0.02}
    assert [r["id"] for r in codex["recent"]] == [3, 2]
    assert view["totals"] == {"working": 1, "queued": 1, "to_decide": 1, "to_upload": 0}
    assert view["you"]["waiting"] == 1 and view["you"]["state"] == "needed"
    by_id = {c["id"]: c for c in view["channels"]}
    assert by_id["hodl"]["phases"]["to_review"] == 1 and by_id["main"]["phases"]["queued"] == 1


def test_an_agent_unseen_for_hours_is_away_and_after_two_weeks_gone(sandbox):
    now = datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc)
    with db.connect() as conn:
        setup(conn)
        for name, ago in (("fresh", timedelta(minutes=5)), ("stale", timedelta(hours=2)), ("gone", timedelta(hours=20)), ("old", timedelta(days=20))):
            db.enqueue_task(conn, "main", "make-clip", {}, by="human")
            row = db.claim_task(conn, name, channel_id="main")
            db.finish_task(conn, row["id"], ok=True)
            conn.execute("UPDATE tasks SET finished_at = ?, claimed_at = ? WHERE id = ?",
                         ((now - ago).isoformat(), (now - ago).isoformat(), row["id"]))
        conn.commit()
        view = team.overview(conn, now=now)
    states = {m["name"]: m["state"] for m in view["members"]}
    assert states == {"fresh": "ready", "stale": "idle", "gone": "away"}


def test_the_feed_reads_events_out_loud(sandbox):
    with db.connect() as conn:
        setup(conn)
        logs.event("task.claimed", channel="main", task=7, kind="make-clip", by="claude")
        logs.event("clip.qc", channel="main", clip="abcdef123", passed=True, by="claude")
        logs.event("clip.approved", channel="main", clip="abcdef123", title="x")
        logs.event("mcp.call", actor="mcp", tool="get_clip")  # noise, not in the feed
        view = team.overview(conn)
    lines = [f["line"] for f in view["feed"]]
    assert lines[:3] == ["you approved abcdef", "claude passed abcdef in QC", "claude picked up #7 make-clip"]
    assert all(f["event"] != "mcp.call" for f in view["feed"])
    assert view["you"]["today"]["approved"] == 1


def test_the_api_serves_it(sandbox):
    from fastapi.testclient import TestClient
    from factory import web

    with db.connect() as conn:
        setup(conn)
    with TestClient(web.app) as client:
        body = client.get("/api/team").json()
        assert body["members"] == [] and body["you"]["state"] == "clear"
        assert {c["id"] for c in body["channels"]} == {"main", "hodl"}
        alerts = client.get("/api/notify").json()
        assert "sinks" in alerts and alerts["daily_at"]


def test_two_sessions_of_one_tool_are_one_member_holding_two_tasks(sandbox):
    with db.connect() as conn:
        setup(conn)
        for ch in ("main", "hodl"):
            db.enqueue_task(conn, ch, "make-clip", {}, by="human")
            db.claim_task(conn, "claude", channel_id=ch)
        view = team.overview(conn)
    (m,) = view["members"]
    assert m["state"] == "working" and len(m["tasks"]) == 2
    assert {t["channel_id"] for t in m["tasks"]} == {"main", "hodl"}
    assert view["totals"]["working"] == 2
