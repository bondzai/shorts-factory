"""Themes are data a person edits, so the validation is the product."""

from datetime import date

import pytest
from fastapi.testclient import TestClient

from factory import channels, db, themes, web

CH = "gravity-lab"


def test_the_calendar_picks_the_theme_and_wraps_the_year(sandbox):
    assert themes.active(date(2026, 6, 1)).id == "default"
    assert themes.active(date(2026, 10, 20)).id == "halloween"
    assert themes.active(date(2026, 12, 30)).id == "newyear"
    assert themes.active(date(2027, 1, 2)).id == "newyear"


def test_a_forced_theme_beats_the_calendar(sandbox, monkeypatch):
    from factory import settings

    monkeypatch.setitem(settings.load().raw["themes"], "force", "songkran")
    assert themes.active(date(2026, 12, 25)).id == "songkran"


def test_a_theme_needs_three_named_marbles_and_real_colours():
    base = themes.DEFAULT_THEMES[1]
    with pytest.raises(ValueError, match="three"):
        themes.from_dict({**base, "marbles": base["marbles"][:2]})
    with pytest.raises(ValueError, match="0-255"):
        themes.from_dict({**base, "caption": [300, 0, 0]})
    with pytest.raises(ValueError, match="distinct"):
        themes.from_dict({**base, "marbles": [["red", [1, 1, 1]], ["red", [2, 2, 2]], ["blue", [3, 3, 3]]]})
    with pytest.raises(ValueError, match="MM-DD"):
        themes.from_dict({**base, "window": ["13-01", "01-05"]})


@pytest.fixture
def client(sandbox):
    web.JOB.name = None; web.JOB.channel_id = None; web.JOB.log = []
    with db.connect() as conn:
        db.migrate(conn)
        channels.create(conn, name="Gravity Lab", channel_id=CH)
        conn.commit()
    with TestClient(web.app) as c:
        yield c


def test_themes_edited_on_the_page_are_validated_and_stored(client):
    body = client.get("/api/themes").json()
    assert body["active"] in [t["id"] for t in body["themes"]]
    bad = [dict(body["themes"][0], caption=[999, 0, 0])]
    assert client.put("/api/themes", json={"themes": bad, "force": ""}).status_code == 400
    ok = client.put("/api/themes", json={"themes": body["themes"], "force": "christmas"})
    assert ok.status_code == 200 and ok.json()["force"] == "christmas"
    with db.connect() as conn:
        assert db.overrides(conn)[("themes", "force")] == "christmas"


def test_the_docs_include_a_reference_that_cannot_go_stale(client):
    pages = client.get("/api/docs").json()["pages"]
    ids = [p["id"] for p in pages]
    assert "01-start-here" in ids and ids[-1] == "reference"
    reference = pages[-1]["text"]
    assert "`max_sameness`" in reference and "`make-clip`" in reference and "`pegboard`" in reference
    assert "factory tasks" in reference


def test_a_task_can_name_a_course_and_a_bad_one_is_refused(client):
    r = client.post("/api/tasks", json={"channel": CH, "kind": "make-clip", "params": {"variant": "marble_race", "course": "pegboard"}})
    assert r.status_code == 200
    r = client.post("/api/tasks", json={"channel": CH, "kind": "make-clip", "params": {"variant": "marble_race", "course": "wedges"}})
    assert r.status_code == 400 and "zigzag" in r.json()["detail"]
