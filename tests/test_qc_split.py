"""Making a clip and judging it are separate: with QC off a clip stops, made
and titled, as awaiting QC, and `run_qc` judges it later without re-rendering."""

import pytest

from factory import channels, db, llm, pipeline, settings
from factory.agents import qc
from factory.models import AWAITING_APPROVAL, AWAITING_QC, QCVerdict


def _qc(monkeypatch, on: bool):
    monkeypatch.setitem(settings.load().raw.setdefault("qc", {}), "enabled", on)


@pytest.fixture
def made(sandbox, monkeypatch):
    """One planned race, built with QC off."""
    _qc(monkeypatch, False)
    monkeypatch.setattr(qc, "review", lambda **kw: pytest.fail("QC ran while it was off"))
    with db.connect() as conn:
        channels.create(conn, name="Main", channel_id="main")
        cid = db.insert_clip(conn, channel_id="main", generator="physics", variant="marble_race",
                             seed=7, params={"stage": "zigzag"}, hook="", plan_why="t")
        out = pipeline.build(conn, cid)
    return cid, out


def test_with_qc_off_a_clip_stops_made_and_titled(made):
    cid, out = made
    assert out.status == AWAITING_QC
    with db.connect() as conn:
        row = db.get(conn, cid)
    assert row["status"] == AWAITING_QC and row["title"] and db.video_file(row).exists()


def test_run_qc_judges_it_later_without_re_rendering(made, monkeypatch):
    cid, _ = made
    _qc(monkeypatch, True)
    monkeypatch.setattr(llm, "readiness", lambda agents=llm.AGENTS: {a: {"ok": True} for a in agents})
    monkeypatch.setattr(qc, "review", lambda **kw: (QCVerdict(verdict="pass", hook_strength=4, looks_templated=False,
                                                              policy_risk="low", reasons=["ok"]), 0.0))
    monkeypatch.setattr(pipeline.building, "render_stage", lambda *a, **k: pytest.fail("re-rendered"))
    with db.connect() as conn:
        title = db.get(conn, cid)["title"]
        outcomes = pipeline.run_qc(conn, "main")
        row = db.get(conn, cid)
    assert [o.status for o in outcomes] == [AWAITING_APPROVAL]
    assert row["status"] == AWAITING_APPROVAL and row["title"] == title


def test_run_qc_refuses_without_a_qc_brain(made, monkeypatch):
    monkeypatch.setattr(llm, "readiness", lambda agents=llm.AGENTS: {a: {"ok": False, "why": "not pulled"} for a in agents})
    with db.connect() as conn, pytest.raises(ValueError, match="QC brain is not ready: not pulled"):
        pipeline.run_qc(conn, "main")


def test_making_clips_needs_no_qc_brain_while_qc_is_off(sandbox, monkeypatch):
    monkeypatch.setattr(llm, "readiness", lambda agents=llm.AGENTS: {a: {"ok": False, "why": "down"} for a in agents})
    monkeypatch.setitem(settings.load().raw["llm"], "metadata_source", "template")
    _qc(monkeypatch, False)
    assert llm.can_make_clips()
    _qc(monkeypatch, True)
    assert not llm.can_make_clips()


def test_agent_metadata_lands_in_awaiting_qc_when_qc_is_off(sandbox, monkeypatch):
    from factory.models import Metadata, RENDERED

    _qc(monkeypatch, False)
    with db.connect() as conn:
        channels.create(conn, name="Main", channel_id="main")
        cid = db.insert_clip(conn, channel_id="main", generator="physics", variant="marble_race",
                             seed=9, params={}, hook="", plan_why="t")
        db.update(conn, cid, status=RENDERED)
        pipeline.attach_metadata(conn, cid, Metadata(
            title="Pick one — four go down the zigzag", description="Four marbles race down the zigzag.",
            hashtags=["#shorts", "#marblerace", "#satisfying"], rationale="test"))
        assert db.get(conn, cid)["status"] == AWAITING_QC
