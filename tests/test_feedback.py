"""The feedback loop: lessons recorded from the numbers, and the adopted ones
reaching the brains. Nothing here calls a model."""

import json

import pytest
from fastapi.testclient import TestClient

from factory import channels, db, feedback, mcp, pipeline, playbooks, web
from factory.models import PUBLISHED
from test_copy import CH as COPY_CH, season_clip  # noqa: F401 - a level clip with its season, reused

CH = "gravity-lab"


@pytest.fixture
def channel(sandbox):
    with db.connect() as conn:
        channels.create(conn, name="Gravity Lab", channel_id=CH)
    return CH


def published(channel_id=CH, views=1000, avg=70.0, swipe=40.0, title="Pick one: red, blue or green", level="L03"):
    with db.connect() as conn:
        clip_id = db.insert_clip(conn, channel_id=channel_id, generator="physics", variant="marble_race",
                                 seed=3, params={}, hook="h", plan_why="t")
        db.update(conn, clip_id, status=PUBLISHED, title=title, hook_text="PICK ONE", level_id=level,
                  facts_json=json.dumps({"rounds": [{"stage": "lodestone"}]}))
        pipeline.set_metrics(conn, clip_id, views=views, avg_view_pct=avg, swipe_away_pct=swipe, likes=4)
    return clip_id


# --- the service ---------------------------------------------------------------

def test_create_get_list_update_delete(channel):
    a = published()
    with db.connect() as conn:
        one = feedback.create(conn, CH, observation="Captions naming a colour get swiped",
                              area="caption", evidence="swipe-away 62% on L03 vs 48% median",
                              clip_ids=[a], action="Use a verb, not a colour")
        two = feedback.create(conn, CH, observation="Shorter races hold better", area="length")
        assert one["status"] == "open" and one["source"] == "manual" and one["clip_ids"] == [a]
        assert feedback.get(conn, one["id"])["evidence"].startswith("swipe-away")

        items, total = feedback.list_(conn, CH)
        assert total == 2 and [i["id"] for i in items] == [two["id"], one["id"]]  # newest first
        assert [i["id"] for i in feedback.list_(conn, CH, area="caption")[0]] == [one["id"]]
        assert [i["id"] for i in feedback.list_(conn, CH, clip=a)[0]] == [one["id"]]

        out = feedback.update(conn, one["id"], status="adopted", result="swipe-away down to 45%")
        assert out["status"] == "adopted" and out["result"] == "swipe-away down to 45%"
        assert feedback.update(conn, one["id"], status="open")["status"] == "open"  # free transitions
        assert feedback.list_(conn, CH, status="open")[1] == 2
        assert feedback.counts(conn, CH) == {"open": 2, "testing": 0, "adopted": 0, "dropped": 0}

        assert feedback.delete(conn, two["id"]) is True
        assert feedback.get(conn, two["id"]) is None
        assert feedback.delete(conn, two["id"]) is False


def test_the_snapshot_is_frozen_when_a_clip_is_linked(channel):
    a = published(views=1000, swipe=62.0)
    b = published(views=50, swipe=80.0, title="Another", level="L04")
    with db.connect() as conn:
        lesson = feedback.create(conn, CH, observation="x", clip_ids=[a])
        snap = lesson["metrics"][a]
        assert snap["views"] == 1000 and snap["swipe_away_pct"] == 62.0
        assert snap["level_id"] == "L03" and snap["stage"] == "lodestone" and snap["hook_text"] == "PICK ONE"

        # Studio is read again: the clip's numbers move, the lesson's do not.
        pipeline.set_metrics(conn, a, views=9000, avg_view_pct=80, swipe_away_pct=30)
        assert feedback.get(conn, lesson["id"])["metrics"][a]["views"] == 1000
        # Linking another clip snapshots only the new one.
        out = feedback.update(conn, lesson["id"], clip_ids=[a, b])
        assert out["metrics"][a]["views"] == 1000 and out["metrics"][b]["views"] == 50
        # Unlinking drops its snapshot.
        out = feedback.update(conn, lesson["id"], clip_ids=[b])
        assert list(out["metrics"]) == [b]
        # The live snapshot shows today's numbers.
        assert feedback.snapshot(conn, [a])[a]["views"] == 9000


@pytest.mark.parametrize("fields, why", [
    ({"observation": "  "}, "observation is required"),
    ({"observation": "x", "area": "vibes"}, "area must be one of"),
    ({"observation": "x", "status": "done"}, "status must be one of"),
    ({"observation": "x", "source": "boss"}, "source must be one of"),
    ({"observation": "x", "clip_ids": ["nope"]}, "no clip nope"),
    ({"observation": "x" * 5000}, "keep it under"),
])
def test_validation_says_what_is_wrong(channel, fields, why):
    with db.connect() as conn, pytest.raises(ValueError, match=why):
        feedback.create(conn, CH, **fields)


def test_a_clip_from_another_channel_is_refused(channel):
    with db.connect() as conn:
        channels.create(conn, name="Other", channel_id="other")
    elsewhere = published(channel_id="other")
    with db.connect() as conn, pytest.raises(ValueError, match="is on channel other"):
        feedback.create(conn, CH, observation="x", clip_ids=[elsewhere])


# --- the loop closes -----------------------------------------------------------------

def test_only_adopted_lessons_reach_the_playbook(channel):
    with db.connect() as conn:
        adopted = feedback.create(conn, CH, observation="Colour captions get swiped", area="caption",
                                  action="Open with a verb", evidence="62% vs 48%", status="adopted")
        feedback.create(conn, CH, observation="HUNCH-OPEN", area="title", action="TRY-OPEN")
        feedback.create(conn, CH, observation="HUNCH-TESTING", area="stage", status="testing")
        feedback.create(conn, CH, observation="HUNCH-DROPPED", area="stage", status="dropped")
    text = playbooks.render("make-clip", CH)
    assert "## What the numbers taught this channel" in text
    assert "**Captions.**" in text and "Open with a verb" in text and "62% vs 48%" in text
    for word in ("HUNCH-OPEN", "TRY-OPEN", "HUNCH-TESTING", "HUNCH-DROPPED"):
        assert word not in text
    with db.connect() as conn:
        feedback.update(conn, adopted["id"], status="dropped")
    assert "What the numbers taught" not in playbooks.render("make-clip", CH)


def test_adopted_copy_lessons_reach_the_copy_brain(season_clip):
    from factory.series import copywriter

    clip_id, _ = season_clip
    with db.connect() as conn:
        feedback.create(conn, COPY_CH, observation="Questions in titles hold", area="title",
                        action="End the title on a question", status="adopted")
        feedback.create(conn, COPY_CH, observation="Stage lesson", area="stage", action="STAGE-ONLY",
                        status="adopted")
        feedback.create(conn, COPY_CH, observation="OPEN-ONE", area="hook", action="NOT-YET")
        s = copywriter.gather(conn, clip_id)
    got = copywriter.inputs(s, rules="")
    assert "End the title on a question" in got["adopted_lessons"]
    assert "STAGE-ONLY" not in got["adopted_lessons"]  # not a words area
    assert "NOT-YET" not in got["adopted_lessons"]


def test_adopted_copy_lessons_reach_the_title_brain(channel, monkeypatch):
    from factory.agents import titles as title_agent
    from factory.agents.titles import TitleIdea, TitleIdeas

    seen = {}

    def fake(**kwargs):
        seen.update(kwargs)
        return TitleIdeas(ideas=[TitleIdea(angle="pick", title="Pick one at the wheel: red, blue or green", caption=None, why="w")]), 0.0

    monkeypatch.setattr(title_agent, "suggest", fake)
    a = published()
    with db.connect() as conn:
        feedback.create(conn, CH, observation="o", area="hook", action="Name the stake early", status="adopted")
        feedback.create(conn, CH, observation="o", area="title", action="STILL-TESTING", status="testing")
        pipeline.title_ideas(conn, a)
    assert "Name the stake early" in seen["lessons"] and "STILL-TESTING" not in seen["lessons"]


# --- the API -------------------------------------------------------------------------

@pytest.fixture
def client(channel):
    with TestClient(web.app) as c:
        yield c


def test_the_api_does_full_crud(client):
    a = published()
    r = client.post("/api/feedback", json={"channel": CH, "observation": "Swiped early", "area": "hook",
                                           "clip_ids": [a], "evidence": "62%"})
    assert r.status_code == 200, r.text
    lesson = r.json()
    assert lesson["source"] == "manual" and lesson["created_by"] == "operator"
    assert lesson["metrics"][a]["views"] == 1000

    body = client.get("/api/feedback", params={"channel": CH, "area": "hook"}).json()
    assert body["total"] == 1 and body["counts"]["open"] == 1 and "hook" in body["areas"]
    assert client.get(f"/api/feedback/{lesson['id']}").json()["observation"] == "Swiped early"

    r = client.patch(f"/api/feedback/{lesson['id']}", json={"status": "adopted", "action": "Verb first"})
    assert r.json()["status"] == "adopted"
    assert client.get("/api/feedback", params={"channel": CH, "status": "adopted"}).json()["total"] == 1

    assert client.delete(f"/api/feedback/{lesson['id']}").json() == {"deleted": lesson["id"]}
    assert client.get(f"/api/feedback/{lesson['id']}").status_code == 404
    assert client.delete(f"/api/feedback/{lesson['id']}").status_code == 404


def test_the_api_answers_bad_input_with_a_clear_400(client):
    r = client.post("/api/feedback", json={"channel": CH, "observation": ""})
    assert r.status_code == 400 and "observation is required" in r.json()["detail"]
    r = client.post("/api/feedback", json={"channel": CH, "observation": "x", "area": "vibes"})
    assert r.status_code == 400 and "area must be one of" in r.json()["detail"]
    r = client.get("/api/feedback", params={"channel": CH, "status": "done"})
    assert r.status_code == 400
    lesson = client.post("/api/feedback", json={"channel": CH, "observation": "x"}).json()
    r = client.patch(f"/api/feedback/{lesson['id']}", json={"clip_ids": ["missing"]})
    assert r.status_code == 400 and "no clip missing" in r.json()["detail"]
    assert client.patch("/api/feedback/99999", json={"status": "open"}).status_code == 404


def test_the_evidence_preview_is_the_live_snapshot(client):
    a = published(views=321)
    body = client.get("/api/feedback/evidence", params={"clips": a}).json()
    assert body["clips"][a]["views"] == 321 and body["clips"][a]["title"].startswith("Pick one")
    assert client.get("/api/feedback/evidence", params={"clips": "nope"}).status_code == 400


# --- MCP and CLI -----------------------------------------------------------------------

@pytest.mark.anyio
async def test_an_agent_may_propose_but_not_adopt(channel):
    from mcp.server.mcpserver.exceptions import ToolError

    server = mcp.build_server()
    names = {t.name for t in await server.list_tools()}
    assert {"list_feedback", "add_feedback", "update_feedback"} <= names
    assert "delete_feedback" not in names

    await server.call_tool("add_feedback", {"observation": "Stage X swipes", "area": "stage",
                                            "channel": CH, "agent": "Claude worker"})
    with db.connect() as conn:
        (lesson,), _ = feedback.list_(conn, CH)
    assert lesson["source"] == "agent" and lesson["status"] == "open" and lesson["created_by"] == "claude"

    await server.call_tool("update_feedback", {"feedback_id": lesson["id"], "status": "testing",
                                               "action": "Try stage Y"})
    with pytest.raises(ToolError, match="not adopt"):
        await server.call_tool("update_feedback", {"feedback_id": lesson["id"], "status": "adopted"})
    with db.connect() as conn:
        got = feedback.get(conn, lesson["id"])
        assert got["status"] == "testing" and got["action"] == "Try stage Y"
        feedback.update(conn, lesson["id"], status="adopted")
    with pytest.raises(ToolError, match="only the operator"):
        await server.call_tool("update_feedback", {"feedback_id": lesson["id"], "status": "dropped"})


def test_the_cli_lists_adds_edits_and_removes(channel, capsys):
    from factory.cli import main

    a = published()
    assert main(["--channel", CH, "feedback", "add", "Hooks with a verb hold", "--area", "hook",
                 "--clips", a, "--action", "Verb first"]) == 0
    with db.connect() as conn:
        (lesson,), _ = feedback.list_(conn, CH)
    assert lesson["clip_ids"] == [a] and lesson["created_by"] == "cli"
    assert main(["--channel", CH, "feedback", "edit", str(lesson["id"]), "--status", "adopted"]) == 0
    assert main(["--channel", CH, "feedback", "list", "--status", "adopted"]) == 0
    assert "Hooks with a verb hold" in capsys.readouterr().out
    assert main(["--channel", CH, "feedback", "rm", str(lesson["id"])]) == 0
    with db.connect() as conn:
        assert feedback.list_(conn, CH)[1] == 0
