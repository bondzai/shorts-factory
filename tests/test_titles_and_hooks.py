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

def test_every_crossing_is_recorded_not_only_the_first(sandbox):
    """Through _round, not _simulate: a bare simulation is one attempt, and
    whether a given seed finishes on its first try moves whenever the
    geometry does."""
    from factory import settings

    r = physics.PhysicsSandbox()._round(33, "marble_race", {}, settings.load().render, W, H, FPS)
    winner, winner_frame, finishes = r["winner"], r["winner_frame"], r["finishes"]
    assert winner in finishes
    assert finishes[winner] == winner_frame
    assert all(f >= winner_frame for f in finishes.values())


def _round(spinners=0, circles=0, segments=0):
    style = physics._Style()
    style.spinners = [(0, 0, 0, 0, 0)] * spinners
    style.circles = [(0, 0, 0)] * circles
    return {"style": style, "segments": [None] * segments, "margin_s": 0.04}


def _bank(sandbox):
    from factory import settings
    return [c.strip() for c in settings.load().raw["overlay"]["marble_race"].split("|")]


def test_the_opening_caption_asks_for_a_pick_and_never_states_the_course(sandbox):
    gen = physics.PhysicsSandbox()
    bank = _bank(sandbox)
    assert "PICK ONE" in bank and len(bank) >= 5
    for r in (_round(spinners=4, circles=31), _round(circles=75), _round(segments=8)):
        text = gen._default_hook("marble_race", r)
        assert text in bank
        assert not any(ch.isdigit() for ch in text)
        assert "DECIDED" not in text and "0.04" not in text


def test_the_caption_rotates_by_seed_and_is_fixed_by_it(sandbox):
    gen = physics.PhysicsSandbox()
    def hook(seed):
        r = _round(spinners=3); r["style"].seed = seed
        return gen._default_hook("marble_race", r)
    assert hook(7301) == hook(7301)
    assert len({hook(s) for s in range(40)}) > 1


def test_an_empty_bank_means_no_caption(sandbox, monkeypatch):
    from factory import settings
    raw = settings.load().raw
    monkeypatch.setitem(raw, "overlay", {**raw["overlay"], "marble_race": ""})
    assert physics.PhysicsSandbox()._default_hook("marble_race", _round(spinners=2)) == ""


def test_the_funnel_is_left_alone(sandbox):
    assert physics.PhysicsSandbox()._default_hook("funnel_drop", _round(spinners=2)) == ""


def test_a_caption_passed_in_wins_over_the_default(sandbox):
    overlay = physics.PhysicsSandbox()._overlay("marble_race", W, H, FPS, text="HOLD ON")
    assert overlay[0] == "HOLD ON"


# --- retitle keeps the gauge --------------------------------------------------

def test_retitle_snapshots_the_numbers_the_old_title_earned(channel):
    clip_id = clip(PUBLISHED, published_at="2026-09-19T00:00:00Z", views=715,
                   avg_view_pct=76.2, swipe_away_pct=74.5)
    with db.connect() as conn:
        out = pipeline.retitle(conn, clip_id, "Pick your marble: red, blue or green",
                               by="human", why="stake in the first four words")
        row = db.get(conn, clip_id)
    history = json.loads(row["title_history_json"])
    assert out["changes"] == 1 and out["needs_manual_update"] is True
    assert history[0]["title"] == "Which of these four marbles reaches the bottom first?"
    assert history[0]["views"] == 715 and history[0]["swipe_away_pct"] == 74.5
    assert row["title"] == "Pick your marble: red, blue or green"


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
        # A race has to finish to be a clip now, so the shortest real one:
        # seed 33 on bumpers crosses at 9.7s.
        return original(seed=seed, variant=variant,
                        params={**params, "max_seconds": 12, "stage": "bumpers"}, work_dir=work_dir)

    monkeypatch.setattr(real, "generate", generate)


def test_rehook_keeps_a_queued_clip_in_the_queue(channel, tmp_path, monkeypatch):
    seen = []
    fake_generate(monkeypatch, tmp_path, seen)
    monkeypatch.setitem(__import__("factory.settings").settings.load().raw["qc"], "min_seconds", 1)
    clip_id = clip(AWAITING_APPROVAL)
    with db.connect() as conn:
        outcome = pipeline.rehook(conn, clip_id, "CALL IT NOW")
        row = db.get(conn, clip_id)
    assert seen and seen[-1]["hook_text"] == "CALL IT NOW"
    assert outcome.status == AWAITING_APPROVAL, outcome.detail
    assert row["hook_text"] == "CALL IT NOW"
    assert json.loads(row["params_json"])["hook_text"] == "CALL IT NOW"


def test_a_person_recaptioning_an_approved_clip_keeps_it_approved(channel, tmp_path, monkeypatch):
    """The approver is the one editing; sending it back to themselves is a hoop."""
    seen = []
    fake_generate(monkeypatch, tmp_path, seen)
    monkeypatch.setitem(__import__("factory.settings").settings.load().raw["qc"], "min_seconds", 1)
    clip_id = clip(APPROVED)
    with db.connect() as conn:
        outcome = pipeline.rehook(conn, clip_id, "CALL IT NOW", by="human")
    assert outcome.status == APPROVED, outcome.detail


def test_an_agent_recaptioning_an_approved_clip_sends_it_back(channel, tmp_path, monkeypatch):
    seen = []
    fake_generate(monkeypatch, tmp_path, seen)
    monkeypatch.setitem(__import__("factory.settings").settings.load().raw["qc"], "min_seconds", 1)
    clip_id = clip(APPROVED)
    with db.connect() as conn:
        outcome = pipeline.rehook(conn, clip_id, "CALL IT NOW", by="agent")
    assert outcome.status == AWAITING_APPROVAL, outcome.detail


def test_rehook_refuses_a_published_clip(channel):
    clip_id = clip(PUBLISHED, published_at="2026-09-19T00:00:00Z")
    with db.connect() as conn:
        with pytest.raises(ValueError, match="published"):
            pipeline.rehook(conn, clip_id, "CALL IT NOW")


def test_metadata_with_a_new_caption_re_renders_and_keeps_the_prompt(channel, tmp_path, monkeypatch):
    from factory.models import Metadata

    seen = []
    fake_generate(monkeypatch, tmp_path, seen)
    monkeypatch.setitem(__import__("factory.settings").settings.load().raw["qc"], "min_seconds", 1)
    clip_id = clip(RENDERED, hook_text="PICK ONE")
    meta = Metadata(
        title="Pick your marble: red, blue or green",
        description="Four marbles, eight ramps, green by 0.4 seconds.",
        hashtags=["#shorts", "#physics", "#marblerace"], rationale="t",
        hook_text="CALL IT NOW", comment_prompt="Which colour did you back?",
    )
    with db.connect() as conn:
        pipeline.attach_metadata(conn, clip_id, meta)
        row = db.get(conn, clip_id)
    assert seen and seen[-1]["hook_text"] == "CALL IT NOW"
    assert row["comment_prompt"] == "Which colour did you back?"
    assert row["title"] == "Pick your marble: red, blue or green"


def test_metadata_without_a_caption_does_not_re_render(channel, tmp_path, monkeypatch):
    from factory.models import Metadata

    seen = []
    fake_generate(monkeypatch, tmp_path, seen)
    clip_id = clip(RENDERED, hook_text="PICK ONE")
    meta = Metadata(title="Pick your marble: red, blue or green",
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
        "clip_id": clip_id, "title": "Pick your marble: red, blue or green",
        "why": "stake first",
    }))
    payload = result[1] if isinstance(result, tuple) else result
    text = json.dumps(payload, default=str)
    assert "needs_manual_update" in text and "true" in text.lower()


def test_the_retitle_playbook_lists_published_clips_worst_first(channel):
    from factory import playbooks

    clip(PUBLISHED, published_at="2026-09-19T00:00:00Z", views=715, avg_view_pct=76.2,
         swipe_away_pct=74.5, hook_text="PICK ONE")
    text = playbooks.render("retitle", CH)
    assert "74% swiped away" in text
    assert "caption “PICK ONE”" in text


def test_a_stamped_then_rejected_clip_is_not_published_anywhere(channel):
    """The first funnel was stamped published_at and rejected afterwards. It
    then appeared in the retitle playbook as a live clip with no metrics, and
    Codex duly reasoned about it. Status is the truth; the timestamp is history."""
    from factory import playbooks

    clip_id = clip(QC_REJECTED, published_at="2026-09-19T13:58:50+00:00")
    text = playbooks.render("retitle", CH)
    assert clip_id not in text
    with db.connect() as conn:
        out = pipeline.retitle(conn, clip_id, "Eight ramps and one marble ahead at the line")
    assert out["published"] is False and out["needs_manual_update"] is False


# --- reject has an undo now ---------------------------------------------------

def test_a_rejected_clip_can_go_back_to_the_queue(channel, tmp_path):
    video = tmp_path / "clip.mp4"; video.write_bytes(b"x")
    clip_id = clip(QC_REJECTED, reject_reason="rejected in review", video_path=str(video))
    with db.connect() as conn:
        pipeline.restore(conn, clip_id)
        row = db.get(conn, clip_id)
    assert row["status"] == AWAITING_APPROVAL and row["reject_reason"] is None


def test_a_measured_rejection_does_not_come_back_by_asking(channel, tmp_path):
    video = tmp_path / "clip.mp4"; video.write_bytes(b"x")
    clip_id = clip(QC_REJECTED, reject_reason="too similar to an existing clip: 0.91 > 0.88",
                   video_path=str(video))
    with db.connect() as conn:
        with pytest.raises(ValueError, match="measured gate"):
            pipeline.restore(conn, clip_id)


def test_restore_is_on_the_web_too(client, tmp_path):
    video = tmp_path / "clip.mp4"; video.write_bytes(b"x")
    clip_id = clip(QC_REJECTED, reject_reason="rejected in review", video_path=str(video))
    assert client.post(f"/api/clip/{clip_id}/restore").status_code == 200
    assert client.get(f"/api/state?channel={CH}").json()["queue"][0]["id"] == clip_id


# --- the upload step, on one screen -------------------------------------------

def test_download_names_the_file_after_the_title(client, tmp_path):
    """The file you find in the upload dialog is the one you meant: the
    title, not clip.mp4 twelve times and not a seed you have to look up."""
    video = tmp_path / "clip.mp4"; video.write_bytes(b"\x00" * 16)
    clip_id = clip(APPROVED, video_path=str(video))
    r = client.get(f"/api/clip/{clip_id}/video?download=1")
    assert r.status_code == 200
    assert "Which-of-these-four-marbles-reaches-the-bottom-first.mp4" in r.headers["content-disposition"]
    untitled = clip(APPROVED, video_path=str(video))
    with db.connect() as conn:
        db.update(conn, untitled, title=None)
    r = client.get(f"/api/clip/{untitled}/video?download=1")
    assert f"marble_race-33-{untitled[:6]}.mp4" in r.headers["content-disposition"]


def test_marking_one_clip_uploaded_publishes_just_that_one(client, tmp_path):
    video = tmp_path / "clip.mp4"; video.write_bytes(b"\x00" * 16)
    a = clip(APPROVED, video_path=str(video), description="d")
    b = clip(APPROVED, video_path=str(video), description="d")
    r = client.post(f"/api/clip/{a}/publish")
    assert r.status_code == 200, r.text
    with db.connect() as conn:
        assert db.get(conn, a)["status"] == PUBLISHED
        assert db.get(conn, b)["status"] == APPROVED


def test_only_an_approved_clip_can_be_marked_uploaded(client):
    clip_id = clip(AWAITING_APPROVAL)
    assert client.post(f"/api/clip/{clip_id}/publish").status_code == 400


# --- the bin ------------------------------------------------------------------

def test_a_binned_clip_leaves_every_list_but_keeps_its_file(client, tmp_path):
    video = tmp_path / "clip.mp4"; video.write_bytes(b"\x00" * 16)
    clip_id = clip(QC_REJECTED, video_path=str(video))
    assert client.post("/api/clips/bin", json={"ids": [clip_id]}).status_code == 200
    assert client.get(f"/api/clips?channel={CH}").json()["clips"] == []
    assert client.get(f"/api/clips?channel={CH}&bin=1").json()["clips"][0]["id"] == clip_id
    assert client.get(f"/api/state?channel={CH}").json()["counts"] == {}
    assert video.exists()


def test_unbin_puts_it_back_exactly_where_it_was(client):
    clip_id = clip(AWAITING_APPROVAL)
    client.post("/api/clips/bin", json={"ids": [clip_id]})
    assert client.get(f"/api/state?channel={CH}").json()["queue"] == []
    client.post("/api/clips/unbin", json={"ids": [clip_id]})
    assert client.get(f"/api/state?channel={CH}").json()["queue"][0]["id"] == clip_id


def test_destroy_only_works_from_the_bin_and_then_removes_the_files(client, tmp_path):
    work = tmp_path / "work"; work.mkdir(); video = work / "clip.mp4"; video.write_bytes(b"x")
    clip_id = clip(QC_REJECTED, video_path=str(video))
    assert client.post("/api/clips/destroy", json={"ids": [clip_id]}).status_code == 400
    client.post("/api/clips/bin", json={"ids": [clip_id]})
    assert client.post("/api/clips/destroy", json={"ids": [clip_id]}).status_code == 200
    assert not work.exists()
    with db.connect() as conn:
        assert db.get(conn, clip_id) is None


def test_a_binned_published_clip_still_guards_sameness(channel):
    """YouTube has it whether the page shows it or not."""
    clip_id = clip(PUBLISHED, phash="f" * 64, published_at="2026-09-19T00:00:00Z")
    binned = clip(QC_REJECTED, phash="e" * 64)
    with db.connect() as conn:
        pipeline.bin_clips(conn, [clip_id, binned])
        assert db.known_phashes(conn, CH) == ["f" * 64]


def test_a_clip_can_be_read_in_full_without_downloading(client, tmp_path):
    video = tmp_path / "clip.mp4"; video.write_bytes(b"\x00" * 2048)
    clip_id = clip(PUBLISHED, video_path=str(video), published_at="2026-09-19T00:00:00Z",
                   facts_json='{"winner": "green", "margin_s": 0.4}', views=715)
    body = client.get(f"/api/clip/{clip_id}").json()
    assert body["facts"]["margin_s"] == 0.4
    assert body["file"]["exists"] is True and body["file"]["mb"] == 0.0
    assert body["views"] == 715
    assert client.get("/api/clip/nope").status_code == 404


# --- a chosen backdrop, and directions that ride on every playbook -----------

def test_a_chosen_backdrop_wins_over_the_theme_and_is_recorded():
    from factory.generators import physics

    *_, style, _ = physics.PhysicsSandbox()._simulate(
        seed=4242, variant="marble_race", sim_w=540, sim_h=960, fps=30, max_frames=3,
        stage="zigzag", background="#102030")
    assert style.background == (16, 32, 48)
    assert style.structure != style.background
    with pytest.raises(ValueError, match="hex"):
        physics.parse_hex("blue")


def test_a_task_with_a_bad_backdrop_is_refused_at_enqueue(channel):
    from factory import tasks

    with db.connect() as conn:
        with pytest.raises(ValueError, match="hex"):
            tasks.enqueue(conn, CH, "make-clip", {"variant": "marble_race", "background": "navy"})
        ids = tasks.enqueue(conn, CH, "make-clip", {"variant": "marble_race", "background": "#0a0a14"})
        assert json.loads(db.tasks(conn, CH)[0]["params_json"])["background"] == "#0a0a14"


def test_rehook_can_change_the_backdrop_and_go_back_to_the_theme(channel, tmp_path, monkeypatch):
    seen = []
    fake_generate(monkeypatch, tmp_path, seen)
    monkeypatch.setitem(__import__("factory.settings").settings.load().raw["qc"], "min_seconds", 1)
    clip_id = clip(AWAITING_APPROVAL, hook_text="PICK ONE")
    with db.connect() as conn:
        pipeline.rehook(conn, clip_id, "PICK ONE", background="#123456")
        assert seen[-1]["background"] == "#123456"
        pipeline.rehook(conn, clip_id, "PICK ONE", background="")
        assert "background" not in seen[-1]


def test_directions_are_appended_to_every_playbook_and_to_task_instructions(channel):
    from factory import playbooks, tasks

    with db.connect() as conn:
        db.set_override(conn, "directions", CH, {"avoid": "no emoji, ever", "audience": ""})
        text = playbooks.render("make-clip", CH)
        assert "Directions from the operator" in text and "no emoji, ever" in text
        assert "Who watches" not in text  # empty fields stay out
        tid = tasks.enqueue(conn, CH, "retitle")[0]
        row = db.claim_task(conn, "codex")
        assert "no emoji, ever" in tasks.instructions(conn, row)


def test_directions_round_trip_on_the_page(client):
    r = client.put("/api/directions", json={"channel": CH, "values": {"title_style": "sentence case"}})
    assert r.status_code == 200
    assert next(f for f in r.json()["fields"] if f["key"] == "title_style")["value"] == "sentence case"
    assert client.put("/api/directions", json={"channel": CH, "values": {"nope": "x"}}).status_code == 400


# --- the spoiler gate ------------------------------------------------------------
# A title that contains the result has already paid the viewer out. Checked
# against the render's facts, so it is a measurement, not taste.

FACTS = {"winner": "amber", "finishes": {"amber": 15.4, "violet": 15.5, "blue": 16.1},
         "rounds": [{"winner": "blue"}, {"winner": "amber"}]}


def meta(**over):
    from factory.models import Metadata
    base = dict(title="Pick your marble: amber, violet or blue", description="Three marbles, two rounds. A photo finish.",
                hashtags=["#shorts", "#marblerace", "#satisfying"], rationale="t")
    return Metadata(**{**base, **over})


def test_a_title_that_names_the_final_winner_is_refused(channel):
    clip_id = clip(RENDERED, facts_json=json.dumps(FACTS))
    with db.connect() as conn, pytest.raises(ValueError, match="title names the winner \\(amber\\)"):
        pipeline.attach_metadata(conn, clip_id, meta(title="Amber runs the 75-peg final against two others"))


def test_the_heat_winner_is_a_result_too(channel):
    clip_id = clip(RENDERED, facts_json=json.dumps(FACTS))
    with db.connect() as conn, pytest.raises(ValueError, match="hook_text names the winner \\(blue\\)"):
        pipeline.attach_metadata(conn, clip_id, meta(hook_text="BLUE TAKES HEAT"))


def test_the_pinned_comment_and_first_sentence_are_checked_but_not_the_rest(channel):
    clip_id = clip(RENDERED, facts_json=json.dumps(FACTS))
    with db.connect() as conn, pytest.raises(ValueError, match="comment_prompt"):
        pipeline.attach_metadata(conn, clip_id, meta(comment_prompt="Did amber deserve it?"))
    with db.connect() as conn:  # the description may say it after the first sentence
        pipeline.attach_metadata(conn, clip_id, meta(description="Two rounds, one photo finish. Amber takes it by 0.04s."))
        assert db.get(conn, clip_id)["title"].startswith("Pick your marble")


def test_naming_the_whole_lineup_gives_nothing_away(channel):
    clip_id = clip(RENDERED, facts_json=json.dumps(FACTS))
    with db.connect() as conn:
        pipeline.attach_metadata(conn, clip_id, meta(title="Violet, blue or amber: who did you back?",
                                                     comment_prompt="Amber, blue or violet — which did you back?"))
    with db.connect() as conn, pytest.raises(ValueError, match="comment_prompt names the winner"):
        pipeline.attach_metadata(conn, clip_id, meta(comment_prompt="Blue or violet — which did you back?"))


def test_a_colour_that_did_not_win_is_fine_and_so_is_a_substring(channel):
    clip_id = clip(RENDERED, facts_json=json.dumps(FACTS))
    with db.connect() as conn:
        pipeline.attach_metadata(conn, clip_id, meta(title="Can violet hold on for 75 pegs this time?",
                                                     comment_prompt="Bluebird or violet — which did you back?"))


def test_retitle_runs_the_same_gate(channel):
    clip_id = clip(PUBLISHED, facts_json=json.dumps(FACTS))
    with db.connect() as conn, pytest.raises(ValueError, match="names the winner"):
        pipeline.retitle(conn, clip_id, "Amber runs the 75-peg final against two", why="test")


def test_result_language_is_refused_even_without_a_name(channel):
    clip_id = clip(RENDERED, facts_json=json.dumps(FACTS))
    for title in ("Decided by 0.7s in the heat, then a final on 8 ramps",
                  "A photo finish on 75 pegs after a heat",
                  "Three marbles and an upset on the pegboard",
                  "Which marble takes it by a nose on 59 pegs"):
        with db.connect() as conn, pytest.raises(ValueError, match="tells the result"):
            pipeline.attach_metadata(conn, clip_id, meta(title=title))
    with db.connect() as conn, pytest.raises(ValueError, match="hook_text tells the result"):
        pipeline.attach_metadata(conn, clip_id, meta(hook_text="DECIDED BY 0.04s"))
    with db.connect() as conn:  # the scene, present tense, a pick: fine
        pipeline.attach_metadata(conn, clip_id, meta(title="Pick your marble: amber, violet or blue",
                                                     hook_text="BET ON ONE",
                                                     description="Three marbles run 31 bumpers. Amber wins by 0.04s."))


def test_the_hooks_skill_rides_on_every_playbook(channel):
    from factory import playbooks
    assert "hooks" in playbooks.skills()
    assert "skill-hooks" not in playbooks.available()
    for name in ("make-clip", "retitle", "work"):
        text = playbooks.render(name, CH)
        assert "Never name the winner" in text and "Never tell the result" in text


def test_the_description_can_be_edited_within_the_same_bounds_and_gate(channel):
    client = TestClient(web.app)
    clip_id = clip(AWAITING_APPROVAL, facts_json=json.dumps(FACTS), description="Three marbles, two rounds. Amber takes it.")
    r = client.patch(f"/api/clip/{clip_id}/text", json={"description": "Pick a marble and watch it through 75 pegs. Amber wins by 0.04s."})
    assert r.status_code == 200 and r.json()["description"].startswith("Pick a marble")
    with db.connect() as conn:
        assert db.get(conn, clip_id)["description"].startswith("Pick a marble")
    assert client.patch(f"/api/clip/{clip_id}/text", json={"description": "too short"}).status_code == 400
    r = client.patch(f"/api/clip/{clip_id}/text", json={"description": "Amber wins the final by a hair. Then more."})
    assert r.status_code == 400 and "names the winner" in r.json()["detail"]


# --- the first two seconds, and the ask at the end -----------------------------

def test_the_opening_caption_is_drawn_big_enough_to_read_at_arm_s_length(sandbox):
    """Studio's number is that three of four viewers leave before the race
    resolves, so the one thing on screen in that second is sized to be read,
    not to be tasteful."""
    from factory import settings

    gen = physics.PhysicsSandbox()
    text, font, x, y, last = gen._overlay("marble_race", W, H, FPS, text="PICK ONE")
    assert font.size >= W * 0.10, font.size
    assert x >= 0 and last > 0
    assert float(settings.load().raw["overlay"]["size"]) >= 0.10


def test_the_closing_ask_exists_and_turns_off_when_emptied(sandbox, monkeypatch):
    from factory import settings

    gen = physics.PhysicsSandbox()
    ask = gen._closing_ask(W, H, FPS)
    assert ask is not None
    text, font, x, y, span = ask
    assert "COMMENT" in text.upper() and span > 0
    # Out of the way of Shorts' own UI along the bottom.
    assert y < H * 0.5

    raw = settings.load().raw
    monkeypatch.setitem(raw, "overlay", {**raw["overlay"], "cta": ""})
    assert gen._closing_ask(W, H, FPS) is None


def test_the_closing_ask_cannot_appear_before_the_result(sandbox):
    """It is drawn from winner_frame onward. Any earlier and it would be
    telling the viewer the race is about to end."""
    import inspect

    source = inspect.getsource(physics.PhysicsSandbox._frames)
    assert "frame_index >= winner_frame" in source
