"""Title ideas: the model proposes, the server decides what the operator sees."""

import json

import pytest

from factory import channels, db, pipeline, settings
from factory.agents import titles as title_agent
from factory.agents.titles import TitleIdea, TitleIdeas

FACTS = {
    "variant": "marble_race", "seed": 7, "stage": "plinko",
    "lineup": ["red", "blue", "green"], "stage_words": "a band of pegs, then a four-armed wheel",
    "rounds": [{"stage": "plinko", "winner": "green", "finishes": {"green": 10.4, "red": 11.5}}],
    "winner": "green", "finishes": {"green": 10.4, "red": 11.5}, "runner_up": "red", "margin_s": 1.04,
}


@pytest.fixture
def clip(sandbox):
    with db.connect() as conn:
        db.migrate(conn)
        channels.create(conn, name="Main", channel_id="main")
        cid = db.insert_clip(conn, channel_id="main", generator="physics", variant="marble_race", seed=7, params={}, hook="", plan_why="t")
        db.update(conn, cid, status="awaiting_approval", title="Pick your marble at the plinko: red, blue or green",
                  facts_json=json.dumps(FACTS))
        older = db.insert_clip(conn, channel_id="main", generator="physics", variant="marble_race", seed=8, params={}, hook="", plan_why="t")
        db.update(conn, older, status="published", title="Call it now at the wheel: amber, blue or violet")
    return cid


@pytest.fixture
def client(sandbox):
    from fastapi.testclient import TestClient

    from factory import web

    return TestClient(web.app)


def propose(*ideas):
    def fake(**kwargs):
        return TitleIdeas(ideas=[TitleIdea(angle=a, title=t, caption=c, why="w") for a, t, c in ideas]), 0.001
    return fake


def test_every_idea_goes_through_the_gates_and_what_fell_is_named(clip, monkeypatch):
    monkeypatch.setattr(title_agent, "suggest", propose(
        ("pick", "Pick one at the wheel: red, blue or green", None),           # kept
        ("curiosity", "Only one gets out. Red, blue or green?", "DON'T BLINK"),  # kept
        ("stakes", "Green wins by a hair on the plinko", None),                 # names the winner
        ("challenge", "Call it now before the wheel does", None),               # opens like a used title
        ("series", "Run it back: same three, the wheel 🔥", None),              # emoji, switch off
    ))
    with db.connect() as conn:
        out = pipeline.title_ideas(conn, clip, captions=True)
    assert [i["angle"] for i in out["ideas"]] == ["pick", "curiosity"]
    assert out["ideas"][1]["caption"] == "DON'T BLINK"
    reasons = {d["angle"]: d["why"] for d in out["dropped"]}
    assert "result" in reasons["stakes"]
    assert "already used" in reasons["challenge"]
    assert "emoji" in reasons["series"]


def test_the_emoji_switch_lets_one_through(clip, monkeypatch):
    monkeypatch.setitem(settings.load().raw.setdefault("titles", {}), "emoji", True)
    monkeypatch.setattr(title_agent, "suggest", propose(("series", "Run it back: same three, the wheel 🔥", None)))
    with db.connect() as conn:
        assert len(pipeline.title_ideas(conn, clip)["ideas"]) == 1


def test_two_ideas_with_the_same_opening_count_once(clip, monkeypatch):
    monkeypatch.setattr(title_agent, "suggest", propose(
        ("pick", "Bet on one down the sieve: red, blue or green", None),
        ("challenge", "Bet on one down the wheel before it turns", None),
    ))
    with db.connect() as conn:
        out = pipeline.title_ideas(conn, clip)
    assert len(out["ideas"]) == 1 and "already used" in out["dropped"][0]["why"]


def test_the_feed_line_and_the_floor_are_enforced(clip, monkeypatch):
    monkeypatch.setattr(title_agent, "suggest", propose(
        ("pick", "Which one is yours on the four-armed wheel: red, blue or green today", None),
        ("stakes", "Three go in", None),
    ))
    with db.connect() as conn:
        out = pipeline.title_ideas(conn, clip)
    assert out["ideas"] == [] and all("characters" in d["why"] for d in out["dropped"])


def test_applying_an_idea_keeps_the_angle_with_the_old_title(clip, monkeypatch, client):
    from factory import llm
    monkeypatch.setattr(llm, "readiness", lambda: {"metadata": {"ok": True}})
    monkeypatch.setattr(title_agent, "suggest", propose(("curiosity", "Only one gets out. Red, blue or green?", None)))
    ideas = client.post(f"/api/clip/{clip}/titles").json()["ideas"]
    assert ideas[0]["angle"] == "curiosity"
    r = client.patch(f"/api/clip/{clip}/text", json={"title": ideas[0]["title"], "why": "angle: curiosity"})
    assert r.status_code == 200
    with db.connect() as conn:
        history = json.loads(db.get(conn, clip)["title_history_json"])
    assert history[-1]["why"] == "angle: curiosity" and history[-1]["title"].startswith("Pick your marble")


def test_a_brain_that_is_down_says_so_instead_of_500(clip, monkeypatch, client):
    from factory import llm
    monkeypatch.setattr(llm, "readiness", lambda: {"metadata": {"ok": False, "why": "ollama is not answering at http://localhost:11434/v1"}})
    r = client.post(f"/api/clip/{clip}/titles")
    assert r.status_code == 503 and "not answering" in r.json()["detail"]
    monkeypatch.setattr(llm, "readiness", lambda: {"metadata": {"ok": True}})
    def boom(**kwargs):
        raise ConnectionError("refused")
    monkeypatch.setattr(title_agent, "suggest", boom)
    r = client.post(f"/api/clip/{clip}/titles")
    assert r.status_code == 502 and "ConnectionError" in r.json()["detail"]
