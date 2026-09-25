"""The Season screen's API: levels, standings, one level, and Plan.
Nothing here renders or calls an agent."""

import pytest
from fastapi.testclient import TestClient

from factory import channels, db, web

from test_season import CH, level, write_season


@pytest.fixture
def client(sandbox):
    web.JOB.name = None
    with db.connect() as conn:
        channels.create(conn, name="Main", channel_id=CH)
    levels = [level(n) for n in range(1, 6)]
    levels[3] = level(4, status="blocked", blocked_on="WP7 trapdoor")
    write_season(sandbox, levels)
    with TestClient(web.app) as c:
        yield c


def test_season_lists_levels_with_what_became_of_them(client):
    body = client.get(f"/api/season?channel={CH}").json()
    assert body["season"] == "s0" and body["channel"] == CH
    ids = [lv["id"] for lv in body["levels"]]
    assert ids == ["L01", "L02", "L03", "L04", "L05"]
    blocked = body["levels"][3]
    assert blocked["status"] == "blocked" and blocked["blocked_on"] == "WP7 trapdoor"
    assert not blocked["plannable"]
    assert body["next_ready"] == ["L01", "L02", "L03", "L05"]
    assert body["worlds"] == ["gravity"]
    assert body["problems"] == []


def test_reading_the_season_writes_nothing(client):
    client.get(f"/api/season?channel={CH}")
    with db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) n FROM seasons").fetchone()["n"] == 0


def test_plan_queues_ready_levels_and_says_why_for_the_rest(client):
    out = client.post("/api/season/plan", json={"channel": CH, "levels": ["L01", "L04"]}).json()
    assert out["queued"] == 1
    by_level = {r["level"]: r for r in out["results"]}
    assert by_level["L01"]["queued"] and by_level["L01"]["task_id"]
    assert "blocked" in by_level["L04"]["reason"]
    body = client.get(f"/api/season?channel={CH}").json()
    l01 = body["levels"][0]
    assert l01["status"] == "planned" and not l01["plannable"]
    assert body["next_ready"][0] == "L02"
    again = client.post("/api/season/plan", json={"channel": CH, "levels": "L01..L02"}).json()
    assert [r["queued"] for r in again["results"]] == [False, True]


def test_plan_refuses_an_unknown_level(client):
    r = client.post("/api/season/plan", json={"channel": CH, "levels": "L99"})
    assert r.status_code == 400 and "L99" in r.json()["detail"]


def test_standings_and_one_level(client):
    table = client.get(f"/api/season/standings?channel={CH}").json()
    assert table["season"] == "s0"
    assert all(r["races"] == 0 and r["points"] == 0 for r in table["table"])
    lv = client.get(f"/api/season/level/L02?channel={CH}").json()
    assert lv["id"] == "L02" and lv["definition"]["id"] == "L02"


def test_a_channel_without_a_season_is_a_404(client):
    with db.connect() as conn:
        channels.create(conn, name="Other", channel_id="other")
    r = client.get("/api/season?channel=other")
    assert r.status_code == 404 and "no season file" in r.json()["detail"]
