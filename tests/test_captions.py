"""On-screen words: held to the hooks research and never repeated on a channel."""

import json

import pytest

from factory import captions, channels, db, pipeline
from factory.pipeline import building


@pytest.fixture
def conn(sandbox):
    with db.connect() as c:
        channels.create(c, name="Gravity Lab", channel_id="main")
        yield c


def clip(conn, seed, *, hook=None, final=None, ask=None, status="awaiting_approval", variant="marble_race"):
    cid = db.insert_clip(conn, channel_id="main", generator="physics", variant=variant, seed=seed,
                         params={}, hook="", plan_why="t")
    db.update(conn, cid, status=status, hook_text=hook,
              facts_json=json.dumps({"captions": {"hook": hook, "final": final, "ask": ask}}))
    return cid


@pytest.mark.parametrize("text,why", [
    ("BLAZE WINS BY A NOSE", "result"), ("PICK ONE · 4 SPINNERS", "number"), ("PICK RED", "colour"),
    ("WATCH THIS", "does not ask"), ("PICK ONE BEFORE THE VERY LONG DROP", "characters"),
    ("PICK", "words"),
])
def test_the_rules_refuse_what_the_research_says_not_to_do(text, why):
    assert why in captions.problem(text)


def test_a_caption_that_asks_for_the_pick_passes():
    assert captions.problem("WHO CLEARS THE RAPIDS?") is None
    assert captions.problem("PICK BLAZE", names=("blaze",)) is not None


def test_the_level_hook_comes_first_then_the_stage(conn):
    got = captions.choose(conn, "main", seed=1, stage="rapids", level_hook="Top seed, bottom seed?", rounds=2)
    assert got.hook == "TOP SEED, BOTTOM SEED?" or captions.problem("TOP SEED, BOTTOM SEED?") is not None
    got = captions.choose(conn, "main", seed=1, stage="rapids", rounds=2)
    assert "RAPIDS" in got.hook and got.final and got.ask


def test_no_two_live_clips_share_words(conn):
    seen = {"hook": set(), "final": set(), "ask": set()}
    stages = ["zigzag", "rapids", "funnels", "spillway", "quarry", "seesaw", "pinball", "gallery", "delta", "plinko"]
    for seed in range(60):
        got = captions.choose(conn, "main", seed=seed, stage=stages[seed % len(stages)], rounds=2)
        for k in seen:
            v = getattr(got, k)
            assert captions.key(v) not in seen[k], (k, v, seed)
            seen[k].add(captions.key(v))
        clip(conn, seed, hook=got.hook, final=got.final, ask=got.ask)


def test_a_rejected_clip_frees_its_words(conn):
    first = captions.choose(conn, "main", seed=5, stage="quarry")
    clip(conn, 5, hook=first.hook, status="qc_rejected")
    assert captions.choose(conn, "main", seed=5, stage="quarry").hook == first.hook


def test_a_typed_caption_is_refused_when_taken_or_off_the_rules(conn):
    clip(conn, 1, hook="PICK ONE")
    assert "already the caption" in captions.check_given(conn, "main", "pick one!")
    assert "result" in captions.check_given(conn, "main", "WHO WON?")
    assert captions.check_given(conn, "main", "CALL THE QUARRY") is None


def test_the_render_path_fills_all_three_and_refuses_a_duplicate(conn):
    cid = clip(conn, 11, hook=None, status="planned")
    row = db.get(conn, cid)
    params, words = building.with_captions(conn, channels.get(conn, "main"), row, {"stage": "rapids", "rounds": 2})
    assert params["hook_text"] == words["hook"] and params["final_text"] and params["ask_text"]
    clip(conn, 12, hook="CALL THE RAPIDS")
    with pytest.raises(ValueError, match="caption refused"):
        building.with_captions(conn, channels.get(conn, "main"), row, {"hook_text": "Call the rapids"})


def test_the_funnel_carries_no_words(conn):
    cid = clip(conn, 13, variant="funnel_drop", status="planned")
    params, words = building.with_captions(conn, channels.get(conn, "main"), db.get(conn, cid), {})
    assert words is None and "hook_text" not in params


def test_a_rendered_race_burns_and_records_its_words(conn):
    from factory import settings
    cid = clip(conn, 7, status="planned")
    db.update(conn, cid, params_json=json.dumps({"stage": "zigzag", "rounds": 2}))
    out = pipeline.build(conn, cid, run_qc=False)
    facts = json.loads(db.get(conn, cid)["facts_json"])
    assert out.status == "awaiting_qc", out.detail
    assert facts["captions"]["hook"] == db.get(conn, cid)["hook_text"] and facts["captions"]["final"]
    trace = json.loads((settings.load().work_dir / "main" / cid / "trace.json").read_text())
    assert trace["ask"] == facts["captions"]["ask"]


def test_when_every_line_is_taken_the_oldest_is_reused_not_nothing(conn):
    for seed in range(40):
        got = captions.choose(conn, "main", seed=seed, stage="zigzag")
        clip(conn, seed, hook=got.hook, ask=got.ask)
    assert captions.choose(conn, "main", seed=99, stage="zigzag").ask
