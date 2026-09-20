"""Every list on the page answers the same shape: items, total, page, page_size."""

import pytest
from fastapi.testclient import TestClient

from factory import channels, db, tasks, web
from factory.models import AWAITING_APPROVAL

CH = "gravity-lab"


@pytest.fixture
def client(sandbox):
    web.JOB.name = None; web.JOB.channel_id = None; web.JOB.log = []
    with db.connect() as conn:
        db.migrate(conn)
        channels.create(conn, name="Gravity Lab", channel_id=CH)
        for i in range(30):
            cid = db.insert_clip(conn, channel_id=CH, generator="physics", variant="marble_race",
                                 seed=i, params={}, hook="", plan_why="t")
            db.update(conn, cid, status=AWAITING_APPROVAL, title=f"Clip number {i:02d} of thirty", views=i)
        tasks.enqueue(conn, CH, "make-clip", {"variant": "marble_race"}, count=3)
        tasks.enqueue(conn, CH, "retitle")
        conn.commit()
    with TestClient(web.app) as c:
        yield c


def test_clips_page_by_the_contract(client):
    body = client.get(f"/api/clips?channel={CH}&page=2&page_size=25").json()
    assert body["total"] == 30 and body["page"] == 2 and body["page_size"] == 25
    assert len(body["items"]) == 5 and body["clips"] == body["items"]


def test_an_unknown_page_size_falls_back_and_an_unknown_sort_is_ignored(client):
    body = client.get(f"/api/clips?channel={CH}&page_size=7&sort=DROP&dir=asc").json()
    assert body["page_size"] == 25 and len(body["items"]) == 25


def test_sorting_by_a_whitelisted_field(client):
    up = client.get(f"/api/clips?channel={CH}&sort=views&dir=asc").json()["items"]
    down = client.get(f"/api/clips?channel={CH}&sort=views&dir=desc").json()["items"]
    assert up[0]["views"] == 0 and down[0]["views"] == 29


def test_search_narrows_and_total_follows(client):
    body = client.get(f"/api/clips?channel={CH}&q=number 0").json()
    assert body["total"] == 10 and len(body["items"]) == 10


def test_work_is_tasks_and_clips_in_one_list(client):
    """A task until it has a clip, the clip from then on: 30 clips and 4
    tasks without clips make 34 rows, each saying which it is."""
    body = client.get(f"/api/work?channel={CH}&page_size=50").json()
    assert body["total"] == 34 and len(body["items"]) == 34
    kinds = {i["row_kind"] for i in body["items"]}
    assert kinds == {"task", "clip"}
    assert all(i["key"] for i in body["items"]) and len({i["key"] for i in body["items"]}) == 34
    stages = {s["id"]: s["count"] for s in body["stages"]}
    assert stages == {"queued": 4, "to_review": 30}
    queued = client.get(f"/api/work?channel={CH}&stage=queued").json()
    assert queued["total"] == 4 and all(i["row_kind"] == "task" and i["stage"] == "queued" for i in queued["items"])
    found = client.get(f"/api/work?channel={CH}&q=number 07").json()
    assert found["total"] == 1 and found["items"][0]["row_kind"] == "clip"
    by_title = client.get(f"/api/work?channel={CH}&sort=title&dir=asc&page_size=25").json()
    assert by_title["items"][0]["title"].startswith("Clip number 00")


def test_a_task_with_a_clip_shows_once_as_the_clip(client):
    with db.connect() as conn:
        row = db.claim_task(conn, "x", channel_id=CH)
        cid = db.insert_clip(conn, channel_id=CH, generator="physics", variant="marble_race", seed=99, params={}, hook="", plan_why="t")
        assert db.attach_clip_to_claimed_task(conn, CH, cid) == row["id"]
        conn.commit()
    body = client.get(f"/api/work?channel={CH}&page_size=50").json()
    assert body["total"] == 34  # one task became one clip; nothing doubled
    assert not any(i["row_kind"] == "task" and i["id"] == row["id"] for i in body["items"])


def test_tasks_and_runs_and_logs_use_the_same_shape(client):
    t = client.get(f"/api/tasks?channel={CH}&kind=make-clip").json()
    assert t["total"] == 3 and len(t["items"]) == 3 and "page_size" in t
    r = client.get(f"/api/runs?channel={CH}").json()
    assert set(r) >= {"items", "total", "page", "page_size"}
    l = client.get(f"/api/logs?channel={CH}&page_size=25").json()
    assert set(l) >= {"items", "total", "page", "page_size"}
