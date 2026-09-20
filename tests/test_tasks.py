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
