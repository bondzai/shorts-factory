"""The brains are configuration, and configuration must not be able to lie.

A provider the page says is ready must actually be callable; a setting
changed on the page must be the one the next render reads; a text-only model
must never be assigned to judge frames.
"""

import json
import sqlite3
import types

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel

from factory import channels, db, llm, settings, web

CH = "gravity-lab"


# --- overrides: config.toml underneath, the database on top ------------------

def test_an_override_in_the_database_wins_over_the_file(tmp_path):
    (tmp_path / "config.toml").write_text(
        '[paths]\ndb = "data/f.db"\nwork = "w"\nout = "o"\n[qc]\nmax_sameness = 0.88\n[llm]\nmodel = "claude-opus-5"\n[render]\nfps = 30\n'
    )
    (tmp_path / "data").mkdir()
    conn = sqlite3.connect(tmp_path / "data" / "f.db")
    conn.execute("CREATE TABLE settings (section TEXT, key TEXT, value_json TEXT, updated_at TEXT, PRIMARY KEY (section, key))")
    conn.execute("INSERT INTO settings VALUES ('qc', 'max_sameness', '0.93', 'now')")
    conn.commit(); conn.close()
    cfg = settings.from_root(tmp_path)
    assert cfg.raw["qc"]["max_sameness"] == 0.93
    assert cfg.base["qc"]["max_sameness"] == 0.88
    assert ("qc", "max_sameness") in cfg.overrides


def test_no_database_yet_means_no_overrides_and_no_error(tmp_path):
    (tmp_path / "config.toml").write_text('[paths]\ndb = "data/f.db"\nwork = "w"\nout = "o"\n[qc]\nmax_sameness = 0.88\n[llm]\nmodel = "m"\n')
    assert settings.from_root(tmp_path).overrides == {}


def test_every_schema_entry_exists_in_config_toml(sandbox):
    cfg = settings.load()
    for f in settings.SCHEMA:
        assert f["key"] in cfg.raw[f["section"]], f"{f['section']}.{f['key']} is in SCHEMA but not config.toml"


# --- providers and assignment -------------------------------------------------

def test_a_bare_model_name_still_means_anthropic(sandbox, monkeypatch):
    monkeypatch.setitem(settings.load().raw["llm"], "agents", {"qc": "claude-opus-5"})
    assert llm.assignment("qc") == "anthropic/claude-opus-5"


def test_an_unknown_provider_names_the_known_ones(sandbox, monkeypatch):
    monkeypatch.setitem(settings.load().raw["llm"], "agents", {"qc": "nope/model"})
    with pytest.raises(ValueError, match="anthropic"):
        llm.resolve("qc")


def test_anthropic_image_blocks_become_data_urls_for_openai():
    blocks = [{"type": "text", "text": "look"}, *llm.image_blocks([b"\x89PNG"])]
    out = llm._to_openai_content(blocks)
    assert out[0] == {"type": "text", "text": "look"}
    assert out[1]["type"] == "image_url"
    assert out[1]["image_url"]["url"].startswith("data:image/png;base64,")


def test_a_text_only_provider_cannot_be_given_the_frames(sandbox, monkeypatch):
    monkeypatch.setitem(settings.load().raw["llm"], "providers", [
        {"id": "groq", "kind": "openai", "base_url": "https://x/v1", "api_key_env": None, "vision": False}])
    monkeypatch.setitem(settings.load().raw["llm"], "agents", {"qc": "groq/llama"})
    assert llm.readiness()["qc"]["ok"] is False
    assert "images" in llm.readiness()["qc"]["why"]


def test_a_missing_key_is_reported_by_variable_name(sandbox, monkeypatch):
    monkeypatch.delenv("DEFINITELY_UNSET_KEY", raising=False)
    monkeypatch.setitem(settings.load().raw["llm"], "providers", [
        {"id": "x", "kind": "openai", "base_url": "https://x/v1", "api_key_env": "DEFINITELY_UNSET_KEY"}])
    monkeypatch.setitem(settings.load().raw["llm"], "agents", {a: "x/m" for a in llm.AGENTS})
    r = llm.readiness()
    assert all(not v["ok"] for v in r.values())
    assert "DEFINITELY_UNSET_KEY" in r["idea"]["why"]
    assert llm.has_credentials() is False


def test_a_local_endpoint_needs_no_key_and_costs_nothing(sandbox, monkeypatch):
    monkeypatch.setitem(settings.load().raw["llm"], "providers", [
        {"id": "ollama", "kind": "openai", "base_url": "http://localhost:11434/v1", "api_key_env": None}])
    monkeypatch.setitem(settings.load().raw["llm"], "agents", {a: "ollama/qwen" for a in llm.AGENTS})
    monkeypatch.setattr(llm, "local_models", lambda p: ["qwen"])  # serving it
    r = llm.readiness()
    assert all(v["ok"] and v["free"] for v in r.values())
    assert llm.usd(types.SimpleNamespace(prompt_tokens=1_000_000, completion_tokens=1_000_000), "qwen", llm.provider("ollama")) == 0.0


# --- structured output over the OpenAI shape, with one retry ------------------

class Verdict(BaseModel):
    verdict: str
    score: int


def fake_openai(replies):
    calls = []

    def create(**kwargs):
        calls.append(kwargs)
        text = replies.pop(0)
        return types.SimpleNamespace(
            choices=[types.SimpleNamespace(message=types.SimpleNamespace(content=text), finish_reason="stop")],
            usage=types.SimpleNamespace(prompt_tokens=10, completion_tokens=5),
        )
    client = types.SimpleNamespace(chat=types.SimpleNamespace(completions=types.SimpleNamespace(create=create)))
    return client, calls


def test_invalid_json_gets_one_retry_with_the_error(sandbox, monkeypatch):
    client, calls = fake_openai(['{"verdict": "pass"}', '```json\n{"verdict": "pass", "score": 4}\n```'])
    p = llm.Provider(id="ollama", kind="openai", base_url="http://x/v1", api_key_env=None, json_mode="object")
    monkeypatch.setattr(llm, "_openai_client", lambda _p: client)
    result, cost = llm._parse_openai(p, "qwen", Verdict, "sys", "content", 100, None)
    assert result.score == 4
    assert cost == 0.0
    assert len(calls) == 2
    assert "not valid" in calls[1]["messages"][-1]["content"]
    assert calls[0]["response_format"] == {"type": "json_object"}


def test_two_bad_replies_fail_loudly_with_the_provider_named(sandbox, monkeypatch):
    client, _ = fake_openai(["nonsense", "still nonsense"])
    p = llm.Provider(id="ollama", kind="openai", base_url="http://x/v1", api_key_env=None)
    monkeypatch.setattr(llm, "_openai_client", lambda _p: client)
    with pytest.raises(ValueError, match="ollama/qwen"):
        llm._parse_openai(p, "qwen", Verdict, "sys", "content", 100, None)


# --- the page ---------------------------------------------------------------

@pytest.fixture
def client(sandbox):
    web.JOB.name = None; web.JOB.channel_id = None; web.JOB.log = []
    with db.connect() as conn:
        db.migrate(conn)
        channels.create(conn, name="Gravity Lab", channel_id=CH)
        conn.commit()
    with TestClient(web.app) as c:
        yield c


def test_settings_are_listed_with_their_defaults(client):
    body = client.get("/api/settings").json()
    field = next(f for f in body["fields"] if f["key"] == "max_sameness")
    assert field["default"] == field["value"] and field["overridden"] is False


def test_an_out_of_range_setting_is_refused_with_the_bounds(client):
    r = client.put("/api/settings", json={"section": "qc", "key": "max_sameness", "value": 3})
    assert r.status_code == 400 and "between" in r.json()["detail"]
    assert client.put("/api/settings", json={"section": "qc", "key": "nope", "value": 1}).status_code == 404


def test_a_setting_changed_on_the_page_lands_in_the_database_and_can_be_reset(client):
    assert client.put("/api/settings", json={"section": "qc", "key": "max_sameness", "value": "0.91"}).status_code == 200
    with db.connect() as conn:
        assert db.overrides(conn)[("qc", "max_sameness")] == 0.91
    assert client.delete("/api/settings/qc/max_sameness").status_code == 200
    with db.connect() as conn:
        assert ("qc", "max_sameness") not in db.overrides(conn)


def test_brains_refuse_a_blind_provider_for_qc(client):
    r = client.put("/api/brains", json={
        "providers": [{"id": "groq", "kind": "openai", "base_url": "https://x/v1", "vision": False}],
        "agents": {"qc": "groq/llama"},
    })
    assert r.status_code == 400 and "images" in r.json()["detail"]


def test_brains_are_saved_as_overrides(client):
    r = client.put("/api/brains", json={
        "providers": [{"id": "ollama", "kind": "openai", "base_url": "http://localhost:11434/v1", "vision": True}],
        "agents": {"idea": "ollama/qwen", "metadata": "ollama/qwen", "qc": "ollama/qwen2.5vl", "analyst": "ollama/qwen"},
    })
    assert r.status_code == 200, r.text
    with db.connect() as conn:
        o = db.overrides(conn)
    assert o[("llm", "agents")]["qc"] == "ollama/qwen2.5vl"
    assert o[("llm", "providers")][0]["id"] == "ollama"


def test_the_test_button_reports_what_the_provider_said(client, monkeypatch):
    monkeypatch.setattr(llm, "test_provider", lambda pid, model=None: {"ok": True, "model": model, "latency_ms": 12, "reply": "ok"})
    r = client.post("/api/brains/test", json={"provider": "anthropic", "model": "claude-sonnet-5"})
    assert r.json()["ok"] is True and r.json()["model"] == "claude-sonnet-5"


def test_a_local_provider_is_ready_only_when_it_is_serving_the_model(sandbox, monkeypatch):
    """`factory brains` said ok for ollama with the server down and the model
    never pulled; the first clip found out the hard way."""
    monkeypatch.setitem(settings.load().raw["llm"], "providers", [
        {"id": "ollama", "kind": "openai", "base_url": "http://localhost:11434/v1", "api_key_env": None, "vision": True}])
    monkeypatch.setitem(settings.load().raw["llm"], "agents", {a: "ollama/qwen2.5vl:7b" for a in llm.AGENTS})
    monkeypatch.setattr(llm, "local_models", lambda p: None)
    assert "not answering" in llm.readiness()["qc"]["why"]
    monkeypatch.setattr(llm, "local_models", lambda p: ["llama3.1:8b"])
    assert "pull it first" in llm.readiness()["qc"]["why"]
    monkeypatch.setattr(llm, "local_models", lambda p: ["qwen2.5vl:7b"])
    assert llm.readiness()["qc"] == {"ok": True, "provider": "ollama", "model": "qwen2.5vl:7b", "why": None, "free": True}
