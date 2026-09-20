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


def test_tasks_and_runs_and_logs_use_the_same_shape(client):
    t = client.get(f"/api/tasks?channel={CH}&kind=make-clip").json()
    assert t["total"] == 3 and len(t["items"]) == 3 and "page_size" in t
    r = client.get(f"/api/runs?channel={CH}").json()
    assert set(r) >= {"items", "total", "page", "page_size"}
    l = client.get(f"/api/logs?channel={CH}&page_size=25").json()
    assert set(l) >= {"items", "total", "page", "page_size"}
