"""API tests. Nothing here calls an agent, so nothing here costs money."""

import copy
import threading

import pytest
from fastapi.testclient import TestClient

from factory import db, settings, web
from factory.models import APPROVED, AWAITING_APPROVAL, QC_REJECTED


@pytest.fixture
def client(tmp_path, monkeypatch):
    fake = settings.Settings(copy.deepcopy(settings.load().raw))
    monkeypatch.setattr(settings, "ROOT", tmp_path)
    monkeypatch.setattr(settings, "load", lambda: fake)
    web.JOB.name = None
    web.JOB.log = []
    with TestClient(web.app) as test_client:
        yield test_client


def queued_clip(**overrides) -> str:
    with db.connect() as conn:
        clip_id = db.insert_clip(
            conn,
            generator="physics",
            variant="marble_race",
            seed=7,
            params={},
            hook="marbles already rolling",
            plan_why="test",
        )
        fields = {
            "status": AWAITING_APPROVAL,
            "title": "Which marble reaches the bottom first?",
            "hashtags_json": '["#shorts", "#marblerace"]',
            "qc_json": '{"hook_strength": 4, "policy_risk": "low", "reasons": ["moving"]}',
        }
        fields.update(overrides)
        db.update(conn, clip_id, **fields)
    return clip_id


def test_index_serves_the_page(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "shorts factory" in response.text


def test_state_is_empty_at_first(client):
    body = client.get("/api/state").json()
    assert body["counts"] == {}
    assert body["queue"] == []
    assert body["spend_usd"] == 0.0
    assert body["job"]["running"] is False


def test_queue_carries_what_the_reviewer_needs(client):
    clip_id = queued_clip()
    body = client.get("/api/state").json()
    assert len(body["queue"]) == 1
    item = body["queue"][0]
    assert item["id"] == clip_id
    assert item["title"].startswith("Which marble")
    assert item["hashtags"] == ["#shorts", "#marblerace"]
    assert item["qc"]["hook_strength"] == 4


def test_approve_moves_the_clip(client):
    clip_id = queued_clip()
    assert client.post(f"/api/clip/{clip_id}/approve").json()["status"] == APPROVED
    body = client.get("/api/state").json()
    assert body["queue"] == []
    assert [c["id"] for c in body["approved"]] == [clip_id]


def test_reject_records_the_reason(client):
    clip_id = queued_clip()
    client.post(f"/api/clip/{clip_id}/reject", json={"reason": "hook is dead"})
    with db.connect() as conn:
        row = db.get(conn, clip_id)
    assert row["status"] == QC_REJECTED
    assert "hook is dead" in row["reject_reason"]


def test_approving_twice_is_refused(client):
    clip_id = queued_clip()
    client.post(f"/api/clip/{clip_id}/approve")
    assert client.post(f"/api/clip/{clip_id}/approve").status_code == 400


def test_video_404s_when_there_is_no_render(client):
    clip_id = queued_clip()
    assert client.get(f"/api/clip/{clip_id}/video").status_code == 404


def test_video_410s_when_the_file_was_deleted(client):
    clip_id = queued_clip(video_path="/tmp/definitely-not-here.mp4")
    assert client.get(f"/api/clip/{clip_id}/video").status_code == 410


def test_metrics_can_be_entered_by_hand(client):
    clip_id = queued_clip()
    response = client.post(
        f"/api/clip/{clip_id}/metrics",
        json={"views": 4120, "avg_view_pct": 71.4, "swipe_away_pct": 23.0},
    )
    assert response.status_code == 200
    with db.connect() as conn:
        row = db.get(conn, clip_id)
    assert row["views"] == 4120
    assert row["swipe_away_pct"] == 23.0


def test_only_one_job_runs_at_a_time(client):
    release = threading.Event()
    web.JOB.start("slow", lambda emit: release.wait(2))
    try:
        assert client.post("/api/build").status_code == 409
        assert client.get("/api/state").json()["job"]["name"] == "slow"
    finally:
        release.set()
