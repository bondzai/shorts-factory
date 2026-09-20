"""The queue is the contract between the person and whichever brain shows up.

What matters: order is honoured, a task cannot be taken twice, an abandoned
claim comes back, and the instructions an agent gets are the playbook plus
exactly the parameters the person chose.
"""

import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from factory import channels, db, tasks, web

CH = "gravity-lab"


@pytest.fixture
def conn(sandbox):
    with db.connect() as c:
        db.migrate(c)
        channels.create(c, name="Gravity Lab", channel_id=CH)
        c.commit()
        yield c


def test_tasks_come_out_in_priority_then_arrival_order(conn):
    a = tasks.enqueue(conn, CH, "plan-week")[0]
    b = tasks.enqueue(conn, CH, "review", priority=5)[0]
    c = tasks.enqueue(conn, CH, "retitle")[0]
    assert db.claim_task(conn, "x")["id"] == b
    assert db.claim_task(conn, "x")["id"] == a
    assert db.claim_task(conn, "x")["id"] == c
    assert db.claim_task(conn, "x") is None


def test_a_claimed_task_cannot_be_claimed_again_until_it_goes_stale(conn):
    tid = tasks.enqueue(conn, CH, "plan-week")[0]
    assert db.claim_task(conn, "first")["id"] == tid
    assert db.claim_task(conn, "second") is None
    conn.execute("UPDATE tasks SET claimed_at = datetime('now', '-2 hours') WHERE id = ?", (tid,))
    conn.commit()
    again = db.claim_task(conn, "second")
    assert again["id"] == tid and again["claimed_by"] == "second"


def test_finishing_records_the_outcome_and_only_from_claimed(conn):
    tid = tasks.enqueue(conn, CH, "make-clip", {"variant": "marble_race"})[0]
    with pytest.raises(ValueError, match="not claimed"):
        db.finish_task(conn, tid, ok=True)
    db.claim_task(conn, "codex")
    row = db.finish_task(conn, tid, ok=True, result={"summary": "made it"}, clip_id="abc")
    assert row["status"] == "done" and row["clip_id"] == "abc"
    assert json.loads(row["result_json"])["summary"] == "made it"


def test_cancel_only_touches_open_tasks(conn):
    tid = tasks.enqueue(conn, CH, "review")[0]
    db.cancel_task(conn, tid)
    with pytest.raises(ValueError, match="already"):
        db.cancel_task(conn, tid)


def test_instructions_are_the_playbook_with_the_parameters_on_top(conn):
    tid = tasks.enqueue(conn, CH, "make-clip", {"variant": "marble_race", "seed": 33})[0]
    row = db.claim_task(conn, "codex")
    text = tasks.instructions(conn, row)
    assert f"Task #{tid}" in text
    assert "- variant: marble_race" in text and "- seed: 33" in text
    assert "finish_task" in text
    assert "# Make one clip for Gravity Lab" in text


def test_a_variant_the_channel_does_not_allow_is_refused_at_enqueue(conn):
    channels.edit(conn, CH, variants=["physics/marble_race"])
    with pytest.raises(ValueError, match="does not allow"):
        tasks.enqueue(conn, CH, "make-clip", {"generator": "physics", "variant": "funnel_drop"})


def test_several_clips_cannot_share_one_fixed_seed(conn):
    with pytest.raises(ValueError, match="seed"):
        tasks.enqueue(conn, CH, "make-clip", {"variant": "marble_race", "seed": 5}, count=3)


def test_the_builtin_worker_only_takes_what_it_can_do(conn, monkeypatch):
    from factory import llm, pipeline

    monkeypatch.setattr(llm, "has_credentials", lambda: True)
    monkeypatch.setattr(pipeline, "build", lambda c, clip_id: pipeline.StageOutcome(clip_id, "awaiting_approval", "ok", 0.01))
    tasks.enqueue(conn, CH, "retitle")
    tasks.enqueue(conn, CH, "make-clip", {"variant": "marble_race"}, count=2)
    done = tasks.work(conn)
    assert [t["kind"] for t in done] == ["make-clip", "make-clip"]
    assert all(t["status"] == "done" and t["clip_id"] for t in done)
    assert db.tasks(conn, CH, "queued")[0]["kind"] == "retitle"


def test_the_builtin_worker_refuses_without_a_ready_brain(conn, monkeypatch):
    from factory import llm

    monkeypatch.setattr(llm, "has_credentials", lambda: False)
    tasks.enqueue(conn, CH, "make-clip", {"variant": "marble_race"})
    with pytest.raises(ValueError, match="external agent"):
        tasks.work(conn)


# --- over MCP -----------------------------------------------------------------

def call(server, name, args):
    result = asyncio.run(server.call_tool(name, args))
    return json.dumps(result, default=str)


def test_an_agent_pulls_instructions_and_reports_back(conn):
    from factory import mcp

    tid = tasks.enqueue(conn, CH, "make-clip", {"variant": "marble_race"})[0]
    server = mcp.build_server()
    text = call(server, "next_task", {"agent": "codex"})
    assert f"Task #{tid}" in text and "Make one clip" in text
    assert "queue is empty" in call(server, "next_task", {"agent": "codex"})
    text = call(server, "finish_task", {"task_id": tid, "ok": True, "summary": "done", "clip_id": "abc"})
    assert '"status": "done"' in text.replace("\\", "")
    with db.connect() as c:
        assert db.tasks(c, CH)[0]["claimed_by"] == "codex"


# --- the page ---------------------------------------------------------------

@pytest.fixture
def client(conn):
    web.JOB.name = None; web.JOB.channel_id = None; web.JOB.log = []
    with TestClient(web.app) as c:
        yield c


def test_the_page_adds_several_at_once_and_counts_them(client):
    r = client.post("/api/tasks", json={"channel": CH, "kind": "make-clip", "params": {"variant": "marble_race"}, "count": 3})
    assert r.status_code == 200 and len(r.json()["ids"]) == 3
    assert client.get(f"/api/state?channel={CH}").json()["tasks"] == {"queued": 3}
    body = client.get(f"/api/tasks?channel={CH}").json()
    assert len(body["tasks"]) == 3 and "make-clip" in body["kinds"]
    assert client.delete(f"/api/tasks/{body['tasks'][0]['id']}").status_code == 200


def test_the_standing_prompt_renders(client):
    r = client.get(f"/api/playbook/work?channel={CH}")
    assert r.status_code == 200 and "next_task" in r.json()["text"]


# --- steps are read, not written ---------------------------------------------

def test_a_render_while_holding_a_task_becomes_that_task_s_clip(conn):
    from factory import logs

    tid = tasks.enqueue(conn, CH, "make-clip", {"variant": "marble_race"})[0]
    db.claim_task(conn, "codex")
    clip_id = db.insert_clip(conn, channel_id=CH, generator="physics", variant="marble_race",
                             seed=1, params={}, hook="", plan_why="t")
    assert db.attach_clip_to_claimed_task(conn, CH, clip_id) == tid
    logs.event("clip.rendered", channel=CH, clip=clip_id, by="agent")
    logs.event("clip.described", channel=CH, clip=clip_id, by="agent")
    row = conn.execute("SELECT * FROM tasks WHERE id = ?", (tid,)).fetchone()
    names = [(s["name"], s["state"]) for s in tasks.steps(row)]
    assert names == [("claimed", "done"), ("rendered", "done"), ("described", "done"),
                     ("qc", "current"), ("finished", "pending")]
    assert tasks.steps(row)[3]["by"] == "codex"


def test_a_queued_task_has_no_current_step_and_a_done_one_has_none_pending(conn):
    tid = tasks.enqueue(conn, CH, "retitle")[0]
    row = conn.execute("SELECT * FROM tasks WHERE id = ?", (tid,)).fetchone()
    assert all(s["state"] == "pending" for s in tasks.steps(row))
    db.claim_task(conn, "codex")
    db.finish_task(conn, tid, ok=True, result={"summary": "nothing to retitle"})
    row = conn.execute("SELECT * FROM tasks WHERE id = ?", (tid,)).fetchone()
    assert [s["state"] for s in tasks.steps(row)] == ["done", "done"]
    assert tasks.steps(row)[-1]["note"] == "done"


def test_tasks_can_be_deleted_and_finished_ones_cleared(client):
    ids = client.post("/api/tasks", json={"channel": CH, "kind": "make-clip", "params": {"variant": "marble_race"}, "count": 3}).json()["ids"]
    with db.connect() as conn:
        db.claim_task(conn, "x"); db.finish_task(conn, ids[0], ok=True)
    assert client.post("/api/tasks/cancel", json={"ids": [ids[1]]}).json()["cancelled"] == [ids[1]]
    assert client.post("/api/tasks/clear", json={"channel": CH}).json()["cleared"] == 2
    assert client.post("/api/tasks/delete", json={"ids": [ids[2], 9999]}).json()["deleted"] == [ids[2]]
    assert client.get(f"/api/tasks?channel={CH}").json()["total"] == 0


def test_a_held_task_fixes_the_render_parameters(sandbox):
    """Told seed 7301, an agent rendered a random seed and reported the task
    done. The server fills in what the agent omits and refuses what it changes."""
    from factory import tasks
    with db.connect() as conn:
        db.migrate(conn)
        channels.create(conn, name="Main", channel_id="main")
        tasks.enqueue(conn, "main", "make-clip", {"generator": "physics", "variant": "marble_race", "seed": 7301, "course": "bumpers"})
        conn.commit()
        assert tasks.held_params(conn, "main", {"seed": None})[0] is None  # nothing claimed yet
        task = db.claim_task(conn, "test", channel_id="main")
        task_id, use = tasks.held_params(conn, "main", {"variant": "marble_race", "seed": None, "generator": "physics", "course": None, "background": None})
        assert task_id == task["id"] and use["seed"] == 7301 and use["course"] == "bumpers"
        with pytest.raises(ValueError, match="asks for seed=7301; you passed 2005185816"):
            tasks.held_params(conn, "main", {"seed": 2005185816})
        with pytest.raises(ValueError, match="course"):
            tasks.held_params(conn, "main", {"seed": 7301, "course": "zigzag"})
        assert "do not change the seed" in tasks.instructions(conn, task)


def test_a_named_seed_is_rendered_as_named_even_if_a_binned_clip_had_it(sandbox, monkeypatch):
    """Three tasks asked for seed 7301 and got random races: the server
    re-rolled any seed a clip had ever carried, including binned ones."""
    from factory import pipeline
    with db.connect() as conn:
        db.migrate(conn)
        channels.create(conn, name="Main", channel_id="main")
        old = db.insert_clip(conn, channel_id="main", generator="physics", variant="marble_race", seed=7301, params={}, hook="", plan_why="t")
        pipeline.bin_clips(conn, [old])
        seen = {}
        def fake_stage(conn_, ch, clip_id, params, by):
            seen["seed"] = db.get(conn_, clip_id)["seed"]
            raise RuntimeError("stop here")
        monkeypatch.setattr(pipeline, "_render_stage", fake_stage)
        with pytest.raises(RuntimeError, match="stop here"):
            pipeline.create_and_render(conn, "main", variant="marble_race", seed=7301)
        assert seen["seed"] == 7301
        with pytest.raises(RuntimeError, match="stop here"):
            pipeline.create_and_render(conn, "main", variant="marble_race")
        assert seen["seed"] != 7301  # unnamed: still avoids a taken seed
