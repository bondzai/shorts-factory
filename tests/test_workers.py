"""Workers started from the console: spawn, log, stop, auto, restore."""

import sys
import time

import pytest

from factory import channels, db, workers

# A stand-in agent: prints the first line of its prompt, sleeps a moment, exits.
FAKE = [sys.executable, "-c",
        "import sys,time; print('fake agent got:', sys.argv[1].splitlines()[0]); sys.stdout.flush(); time.sleep(float(sys.argv[2])); sys.exit(int(sys.argv[3]))",
        workers.PROMPT, "0.3", "0"]


@pytest.fixture
def manager(sandbox, monkeypatch):
    monkeypatch.setitem(workers.COMMANDS, "fake", list(FAKE))
    monkeypatch.setattr(workers, "POLL_S", 0.05)
    monkeypatch.setattr(workers, "RESPAWN_BACKOFF_S", 0.1)
    with db.connect() as conn:
        db.migrate(conn)
        channels.create(conn, name="Main", channel_id="main")
    m = workers.Manager()
    yield m
    for w in list(m.workers.values()):
        m.stop(w.channel_id)


def wait_for(cond, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.05)
    return False


def test_start_runs_the_agent_with_the_rendered_prompt_and_logs_it(manager):
    w = manager.start("main", agent="fake")
    assert w.running and w.runs == 1 and w.state() == "running"
    assert wait_for(lambda: not w.running)
    manager.status()
    assert w.last_exit == 0 and w.state() == "stopped"
    assert any("fake agent got: # Work the queue on Main" in ln for ln in w.tail())


def test_an_unknown_or_missing_agent_is_refused_with_the_fix(manager, monkeypatch):
    with pytest.raises(ValueError, match="no agent"):
        manager.start("main", agent="nope")
    monkeypatch.setitem(workers.COMMANDS, "ghost", ["definitely-not-a-binary-xyz", workers.PROMPT])
    with pytest.raises(ValueError, match="not on the server's PATH"):
        manager.start("main", agent="ghost")


def test_stop_terminates_a_running_agent(manager, monkeypatch):
    monkeypatch.setitem(workers.COMMANDS, "slow", FAKE[:3] + [workers.PROMPT, "30", "0"])
    w = manager.start("main", agent="slow")
    assert w.running
    manager.stop("main")
    assert not w.running and w.auto is False


def test_auto_starts_only_when_the_queue_has_work_and_again_after_it_exits(manager):
    w = manager.start("main", agent="fake", auto=True)
    assert wait_for(lambda: not w.running)
    manager.tick()
    assert w.runs == 1 and w.state() == "waiting"  # queue empty: nothing more
    with db.connect() as conn:
        db.enqueue_task(conn, "main", "make-clip", {}, by="human")
    time.sleep(0.15)  # past the backoff
    manager.tick()
    assert w.runs == 2 and w.running


def test_auto_is_remembered_across_a_restart(manager):
    manager.start("main", agent="fake", auto=True)
    fresh = workers.Manager()
    fresh.restore()
    assert "main" in fresh.workers and fresh.workers["main"].auto and fresh.workers["main"].agent == "fake"
    manager.stop("main")
    again = workers.Manager()
    again.restore()
    assert "main" not in again.workers


def test_integration_hands_over_every_form(sandbox):
    it = workers.integration("main")
    assert it["claude_code"].startswith("claude mcp add --scope user shorts-factory -- ")
    assert it["mcp_json"]["mcpServers"]["shorts-factory"]["args"] == ["mcp"]
    assert "[mcp_servers.shorts-factory]" in it["codex_toml"]
    assert it["cowork"] == "bin/cowork --channel main --unattended"


def test_the_api_reports_and_refuses_like_the_manager(sandbox, monkeypatch):
    from fastapi.testclient import TestClient
    from factory import web

    monkeypatch.setitem(workers.COMMANDS, "fake", list(FAKE))
    with db.connect() as conn:
        db.migrate(conn)
        channels.create(conn, name="Main", channel_id="main")
    with TestClient(web.app) as client:
        body = client.get("/api/workers?channel=main").json()
        assert "fake" in body["agents"] and body["available"]["fake"] is True
        assert body["integration"]["cowork"].endswith("--channel main --unattended")
        out = client.post("/api/workers/start", json={"channel": "main", "agent": "fake"}).json()
        assert out["worker"]["state"] == "running" and out["worker"]["agent"] == "fake"
        assert client.post("/api/workers/start", json={"channel": "main", "agent": "nope"}).status_code == 400
        client.post("/api/workers/stop", json={"channel": "main"})
        assert client.get("/api/workers/main/log").json()["channel"] == "main"
    workers.MANAGER.stop("main")


def test_claude_is_run_with_only_the_factory_mcp_server(sandbox):
    cmd = workers.COMMANDS["claude"]
    assert "--strict-mcp-config" in cmd and "--mcp-config" in cmd and workers.MCP_JSON in cmd
    import json
    cfg = json.loads(workers.mcp_config_json())
    assert list(cfg["mcpServers"]) == ["shorts-factory"] and cfg["mcpServers"]["shorts-factory"]["args"] == ["mcp"]
