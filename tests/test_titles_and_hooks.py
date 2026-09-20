"""The two levers Studio's analysis points at, and the gauge on one of them.

76% of viewers swipe before a race resolves. The caption in the first second
and the title are what they decide on, and until now one was a config constant
and the other froze the moment an agent wrote it.
"""

import json

import pytest
from fastapi.testclient import TestClient

from factory import channels, db, pipeline, web
from factory.generators import physics
from factory.models import APPROVED, AWAITING_APPROVAL, PUBLISHED, QC_REJECTED, RENDERED

CH = "gravity-lab"
W, H, FPS = 540, 960, 30


@pytest.fixture
def channel(sandbox):
    with db.connect() as conn:
        db.migrate(conn)
        channels.create(conn, name="Gravity Lab", channel_id=CH)
        conn.commit()
    return CH


def clip(status=AWAITING_APPROVAL, **fields):
    with db.connect() as conn:
        clip_id = db.insert_clip(
            conn, channel_id=CH, generator="physics", variant="marble_race",
            seed=33, params={}, hook="", plan_why="test",
        )
        db.update(conn, clip_id, status=status,
                  title="Which of these four marbles reaches the bottom first?",
                  hashtags_json='["#shorts"]', **fields)
    return clip_id


# --- the caption comes from the race ------------------------------------------

def test_every_crossing_is_recorded_not_only_the_first():
    states, _, balls, _, winner, winner_frame, _, finishes = physics.PhysicsSandbox()._simulate(
        seed=33, variant="marble_race", sim_w=W, sim_h=H, fps=FPS, max_frames=900,
    )
    assert winner in finishes
    assert finishes[winner] == winner_frame
    assert all(f >= winner_frame for f in finishes.values())


def test_a_close_race_puts_its_margin_on_screen():
    gen = physics.PhysicsSandbox()
    assert gen._default_hook("marble_race", 0.4) == "DECIDED BY 0.4s"
    assert gen._default_hook("marble_race", 0.03) == "DECIDED BY 0.03s"


def test_a_runaway_race_falls_back_to_the_config_line(sandbox):
    gen = physics.PhysicsSandbox()
    assert gen._default_hook("marble_race", None) == "WHICH ONE WINS?"
    assert gen._default_hook("marble_race", 2.5) == "WHICH ONE WINS?"


def test_the_funnel_is_left_alone(sandbox):
    assert physics.PhysicsSandbox()._default_hook("funnel_drop", 0.2) == ""


def test_a_caption_passed_in_wins_over_the_default(sandbox):
    overlay = physics.PhysicsSandbox()._overlay("marble_race", W, H, FPS, text="HOLD ON")
    assert overlay[0] == "HOLD ON"


# --- retitle keeps the gauge --------------------------------------------------

def test_retitle_snapshots_the_numbers_the_old_title_earned(channel):
    clip_id = clip(PUBLISHED, published_at="2026-09-19T00:00:00Z", views=715,
                   avg_view_pct=76.2, swipe_away_pct=74.5)
    with db.connect() as conn:
        out = pipeline.retitle(conn, clip_id, "This marble race is decided by 0.4 seconds",
                               by="human", why="stake in the first four words")
        row = db.get(conn, clip_id)
    history = json.loads(row["title_history_json"])
    assert out["changes"] == 1 and out["needs_manual_update"] is True
    assert history[0]["title"] == "Which of these four marbles reaches the bottom first?"
    assert history[0]["views"] == 715 and history[0]["swipe_away_pct"] == 74.5
    assert row["title"] == "This marble race is decided by 0.4 seconds"


def test_retitle_refuses_what_every_title_here_refuses(channel):
    clip_id = clip()
    with db.connect() as conn:
        with pytest.raises(ValueError, match="20-90"):
            pipeline.retitle(conn, clip_id, "too short")
        with pytest.raises(ValueError, match="already"):
            pipeline.retitle(conn, clip_id, "Which of these four marbles reaches the bottom first?")


def test_an_unpublished_retitle_needs_no_trip_to_studio(channel):
    clip_id = clip(AWAITING_APPROVAL)
    with db.connect() as conn:
        out = pipeline.retitle(conn, clip_id, "Eight ramps and one marble ahead at the line")
    assert out["needs_manual_update"] is False


# --- rehook re-burns the caption without touching the race -------------------

def fake_generate(monkeypatch, tmp_path, seen):
    """Stand in for physics: record the params, hand back a real tiny mp4."""
    from factory import generators as gens

    real = gens.get("physics")
    original = real.generate  # bound now, or the wrapper calls itself forever

    def generate(*, seed, variant, params, work_dir):
        seen.append(params)
        return original(seed=seed, variant=variant,
                        params={**params, "max_seconds": 4}, work_dir=work_dir)

    monkeypatch.setattr(real, "generate", generate)


def test_rehook_keeps_a_queued_clip_in_the_queue(channel, tmp_path, monkeypatch):
    seen = []
    fake_generate(monkeypatch, tmp_path, seen)
    monkeypatch.setitem(__import__("factory.settings").settings.load().raw["qc"], "min_seconds", 1)
    clip_id = clip(AWAITING_APPROVAL)
    with db.connect() as conn:
        outcome = pipeline.rehook(conn, clip_id, "DECIDED BY 0.4s")
        row = db.get(conn, clip_id)
    assert seen and seen[-1]["hook_text"] == "DECIDED BY 0.4s"
    assert outcome.status == AWAITING_APPROVAL, outcome.detail
    assert row["hook_text"] == "DECIDED BY 0.4s"
    assert json.loads(row["params_json"])["hook_text"] == "DECIDED BY 0.4s"


def test_rehook_sends_an_approved_clip_back_for_another_look(channel, tmp_path, monkeypatch):
    seen = []
    fake_generate(monkeypatch, tmp_path, seen)
    monkeypatch.setitem(__import__("factory.settings").settings.load().raw["qc"], "min_seconds", 1)
    clip_id = clip(APPROVED)
    with db.connect() as conn:
        outcome = pipeline.rehook(conn, clip_id, "DECIDED BY 0.4s")
    assert outcome.status == AWAITING_APPROVAL, outcome.detail


def test_rehook_refuses_a_published_clip(channel):
    clip_id = clip(PUBLISHED, published_at="2026-09-19T00:00:00Z")
    with db.connect() as conn:
        with pytest.raises(ValueError, match="published"):
            pipeline.rehook(conn, clip_id, "DECIDED BY 0.4s")


def test_metadata_with_a_new_caption_re_renders_and_keeps_the_prompt(channel, tmp_path, monkeypatch):
    from factory.models import Metadata

    seen = []
    fake_generate(monkeypatch, tmp_path, seen)
    monkeypatch.setitem(__import__("factory.settings").settings.load().raw["qc"], "min_seconds", 1)
    clip_id = clip(RENDERED, hook_text="WHICH ONE WINS?")
    meta = Metadata(
        title="This marble race is decided by 0.4 seconds",
        description="Four marbles, eight ramps, green by 0.4 seconds.",
        hashtags=["#shorts", "#physics", "#marblerace"], rationale="t",
        hook_text="DECIDED BY 0.4s", comment_prompt="Which colour did you back?",
    )
    with db.connect() as conn:
        pipeline.attach_metadata(conn, clip_id, meta)
        row = db.get(conn, clip_id)
    assert seen and seen[-1]["hook_text"] == "DECIDED BY 0.4s"
    assert row["comment_prompt"] == "Which colour did you back?"
    assert row["title"] == "This marble race is decided by 0.4 seconds"


def test_metadata_without_a_caption_does_not_re_render(channel, tmp_path, monkeypatch):
    from factory.models import Metadata

    seen = []
    fake_generate(monkeypatch, tmp_path, seen)
    clip_id = clip(RENDERED, hook_text="WHICH ONE WINS?")
    meta = Metadata(title="This marble race is decided by 0.4 seconds",
                    description="Four marbles, eight ramps, green by 0.4 seconds.",
                    hashtags=["#shorts", "#physics", "#marblerace"], rationale="t")
    with db.connect() as conn:
        pipeline.attach_metadata(conn, clip_id, meta)
    assert seen == []


# --- the surfaces -------------------------------------------------------------

@pytest.fixture
def client(channel):
    web.JOB.name = None
    web.JOB.channel_id = None
    web.JOB.log = []
    with TestClient(web.app) as c:
        yield c


def test_the_review_page_can_change_a_title_and_a_prompt(client):
    clip_id = clip(AWAITING_APPROVAL)
    r = client.patch(f"/api/clip/{clip_id}/text", json={
        "title": "Eight ramps and one marble ahead at the line",
        "comment_prompt": "Which colour did you back?",
    })
    assert r.status_code == 200, r.text
    body = client.get(f"/api/clips?channel={CH}").json()["clips"][0]
    assert body["title"] == "Eight ramps and one marble ahead at the line"
    assert body["comment_prompt"] == "Which colour did you back?"
    assert len(body["title_history"]) == 1


def test_a_bad_title_is_a_400_not_a_500(client):
    clip_id = clip(AWAITING_APPROVAL)
    r = client.patch(f"/api/clip/{clip_id}/text", json={"title": "nope"})
    assert r.status_code == 400
    assert "20-90" in r.json()["detail"]


def test_the_mcp_tool_is_the_same_retitle(channel):
    import asyncio

    from factory import mcp

    clip_id = clip(PUBLISHED, published_at="2026-09-19T00:00:00Z", views=715)
    server = mcp.build_server()
    result = asyncio.run(server.call_tool("retitle", {
        "clip_id": clip_id, "title": "This marble race is decided by 0.4 seconds",
        "why": "stake first",
    }))
    payload = result[1] if isinstance(result, tuple) else result
    text = json.dumps(payload, default=str)
    assert "needs_manual_update" in text and "true" in text.lower()


def test_the_retitle_playbook_lists_published_clips_worst_first(channel):
    from factory import playbooks

    clip(PUBLISHED, published_at="2026-09-19T00:00:00Z", views=715, avg_view_pct=76.2,
         swipe_away_pct=74.5, hook_text="WHICH ONE WINS?")
    text = playbooks.render("retitle", CH)
    assert "74% swiped away" in text
    assert "caption “WHICH ONE WINS?”" in text
