"""API tests. Nothing here calls an agent, so nothing here costs money."""

import threading

import pytest
from fastapi.testclient import TestClient

from factory import channels, db, web
from factory.models import APPROVED, AWAITING_APPROVAL, QC_REJECTED

CH = "gravity-lab"
OTHER = "hodl-tales"


@pytest.fixture
def client(sandbox):
    web.JOB.name = None
    web.JOB.channel_id = None
    web.JOB.log = []
    with db.connect() as conn:
        channels.create(conn, name="Gravity Lab", channel_id=CH)
    with TestClient(web.app) as test_client:
        yield test_client


def queued_clip(channel_id=CH, seed=7, **overrides) -> str:
    with db.connect() as conn:
        clip_id = db.insert_clip(
            conn,
            channel_id=channel_id,
            generator="physics",
            variant="marble_race",
            seed=seed,
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


def add_channel(client, name="HODL Tales", channel_id=OTHER):
    return client.post("/api/channels", json={"name": name, "id": channel_id})


def test_index_serves_the_page(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "shorts factory" in response.text


def test_state_defaults_to_the_only_channel(client):
    body = client.get("/api/state").json()
    assert body["channel"]["id"] == CH
    assert body["queue"] == []
    assert body["spend_usd"] == 0.0
    assert body["job"]["running"] is False


def test_queue_carries_what_the_reviewer_needs(client):
    clip_id = queued_clip()
    item = client.get(f"/api/state?channel={CH}").json()["queue"][0]
    assert item["id"] == clip_id
    assert item["hashtags"] == ["#shorts", "#marblerace"]
    assert item["qc"]["hook_strength"] == 4


def test_channels_can_be_created_over_the_api(client):
    response = add_channel(client)
    assert response.status_code == 200
    assert response.json()["id"] == OTHER
    ids = [c["id"] for c in client.get("/api/channels").json()["channels"]]
    assert ids == [CH, OTHER]


def test_a_duplicate_channel_is_refused(client):
    add_channel(client)
    assert add_channel(client).status_code == 400


def test_each_channel_sees_only_its_own_queue(client):
    mine = queued_clip(CH, seed=1)
    add_channel(client)
    theirs = queued_clip(OTHER, seed=2)

    assert [c["id"] for c in client.get(f"/api/state?channel={CH}").json()["queue"]] == [mine]
    assert [c["id"] for c in client.get(f"/api/state?channel={OTHER}").json()["queue"]] == [theirs]


def test_state_needs_a_channel_once_there_are_two(client):
    add_channel(client)
    assert client.get("/api/state").status_code == 404


def test_an_unknown_channel_is_a_404(client):
    assert client.get("/api/state?channel=nope").status_code == 404


def test_editing_a_channel(client):
    response = client.patch(f"/api/channels/{CH}", json={"handle": "@gravitylabii"})
    assert response.status_code == 200
    assert response.json()["handle"] == "@gravitylabii"


def test_pausing_a_channel_frees_the_default(client):
    add_channel(client)
    client.patch(f"/api/channels/{OTHER}", json={"active": False})
    assert client.get("/api/state").json()["channel"]["id"] == CH


def test_approve_moves_the_clip(client):
    clip_id = queued_clip()
    assert client.post(f"/api/clip/{clip_id}/approve").json()["status"] == APPROVED
    body = client.get(f"/api/state?channel={CH}").json()
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


def test_one_job_at_a_time_across_every_channel(client):
    add_channel(client)
    release = threading.Event()
    web.JOB.start("slow", CH, lambda emit: release.wait(2))
    try:
        response = client.post("/api/build", json={"channel": OTHER})
        assert response.status_code == 409
        assert CH in response.json()["detail"]
    finally:
        release.set()


def test_library_filters_and_exposes_modules(client):
    queued_clip(seed=1)
    body = client.get(f"/api/clips?channel={CH}").json()
    assert len(body["clips"]) == 1
    assert "physics" in body["modules"]
    assert client.get(f"/api/clips?channel={CH}&status=published").json()["clips"] == []
    assert len(client.get(f"/api/clips?channel={CH}&q=marble").json()["clips"]) == 1
    assert client.get(f"/api/clips?channel={CH}&q=zzzz").json()["clips"] == []


def test_analytics_is_empty_until_metrics_exist(client):
    queued_clip(seed=1)
    body = client.get(f"/api/analytics?channel={CH}").json()
    assert body["n_with_metrics"] == 0


def test_rules_round_trip(client):
    original = client.get(f"/api/rules?channel={CH}").json()
    assert "Hook" in original["text"]
    client.put("/api/rules", json={"channel": CH, "text": "# replaced\n"})
    assert client.get(f"/api/rules?channel={CH}").json()["text"] == "# replaced\n"


def test_accepting_a_proposal_needs_the_markers(client):
    client.put("/api/rules", json={"channel": CH, "text": "# no markers here\n"})
    response = client.post("/api/rules/accept", json={"channel": CH, "rules": ["be better"]})
    assert response.status_code == 400


def test_accepting_a_proposal_appends_one_rule(client):
    body = client.post(
        "/api/rules/accept", json={"channel": CH, "rules": ["State the margin in the title."]}
    ).json()
    assert body["applied"] == 1
    assert "State the margin in the title." in body["text"]


def test_rules_are_per_channel(client):
    add_channel(client)
    client.put("/api/rules", json={"channel": CH, "text": "# gravity only\n"})
    assert "gravity only" not in client.get(f"/api/rules?channel={OTHER}").json()["text"]


def test_runs_endpoint_lists_history(client):
    with db.connect() as conn:
        run = db.start_run(conn, CH, "build")
        db.finish_run(conn, run, status="ok", detail="2 reached the queue")
    runs = client.get(f"/api/runs?channel={CH}").json()["runs"]
    assert runs[0]["detail"] == "2 reached the queue"
