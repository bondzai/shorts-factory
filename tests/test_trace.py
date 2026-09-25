"""Traces, outcomes, casts and the story check of the physics generator.

The encoder is stubbed out: these are about what is drawn and measured, and
the frames that would have gone to ffmpeg are exactly what a redraw must
reproduce.
"""

import logging
import math

import pytest

from factory import settings, stage_qa
from factory.generators import physics
from factory.generators.physics import outcome as physics_outcome
from factory.series import story, trace

CAST = [
    {"id": "blaze", "name": "Blaze", "color": "#E84C4A", "traits": {"friction": 0.12, "mass_mult": 0.9}},
    {"id": "tide", "name": "Tide", "color": "#378ADD", "traits": {"friction": 0.30}},
    {"id": "volt", "name": "Volt", "color": "#F2C230", "traits": {"jitter": 1.0}},
    {"id": "moss", "name": "Moss", "color": "#97C459", "traits": {}},
]
SAMPLES = 5


@pytest.fixture
def no_ffmpeg(sandbox, monkeypatch):
    """Keep what would have been encoded: the frame count, and a few frames
    spread over the clip (at a stride, so both rounds are sampled)."""
    seen = {"count": 0, "frames": {}}

    def encode_frames(frames, *, out_path, src_size, out_size, fps):
        for i, frame in enumerate(frames):
            seen["frames"][i] = frame if i % 97 == 13 else None
            seen["count"] += 1
        out_path.write_bytes(b"")
        return out_path

    monkeypatch.setattr(physics.sandbox.encoder, "encode_frames", encode_frames)
    monkeypatch.setattr(physics.sandbox.encoder, "mux", lambda video, audio, out: out)
    return seen


def _race(tmp_path, name="clip", seed=7, **params):
    return physics.generate(seed=seed, variant="marble_race",
                            params={"stage": "zigzag", "rounds": 2, **params}, work_dir=tmp_path / name)


def test_the_same_seed_writes_a_byte_identical_trace(no_ffmpeg, tmp_path):
    a, b = _race(tmp_path, "a"), _race(tmp_path, "b")
    for name in (trace.NPZ, trace.JSON):
        assert (a.trace_path.parent / name).read_bytes() == (b.trace_path.parent / name).read_bytes()
    arrays, meta = trace.read(a.trace_path)
    assert len(meta["rounds"]) == 2 and meta["seed"] == 7
    assert arrays["round0_positions"].dtype.name == "float64"
    assert arrays["round0_positions"].shape[1:] == (len(meta["entrant_ids"]), 2)
    assert "kinematics" not in meta["rounds"][0]["style"]


@pytest.mark.parametrize("engine", ["pygame", "pil"])
def test_a_redraw_is_the_shipped_frame(no_ffmpeg, tmp_path, engine):
    settings.load().raw["render"]["engine"] = engine
    clip = _race(tmp_path, cast=CAST)
    shipped = {i: f for i, f in no_ffmpeg["frames"].items() if f is not None}
    arrays = trace.read(clip.trace_path)[0]
    # Shipped frames per round: the presentation's time map when there is one.
    heat = len(arrays["round0_timemap"] if "round0_timemap" in arrays else arrays["round0_positions"])
    # Five spread over the clip, at least one in each round.
    picks = sorted(shipped)[:: max(1, len(shipped) // SAMPLES)][:SAMPLES]
    assert any(i < heat for i in picks) and any(i >= heat for i in picks)

    redrawn = list(physics.PhysicsSandbox().redraw(clip.trace_path.parent))
    assert len(redrawn) == no_ffmpeg["count"]
    for i in picks:
        assert redrawn[i] == shipped[i], f"frame {i} differs"
    one = picks[-1]
    assert physics.redraw_frame(clip.trace_path.parent, 1 if one >= heat else 0,
                                one - heat if one >= heat else one) == shipped[one]


def test_a_cast_race_is_run_by_the_cast(no_ffmpeg, tmp_path):
    clip = _race(tmp_path, cast=CAST)
    ids = [e["id"] for e in CAST]
    arrays, meta = trace.read(clip.trace_path)
    assert meta["entrant_ids"] == ids
    assert [tuple(c) for c in arrays["colors"]] == [physics.parse_hex(e["color"]) for e in CAST]
    assert clip.facts["cast"] == ids
    assert clip.facts["winner"] in ids
    assert all(r["winner"] in ids for r in clip.facts["rounds"])
    assert {p.entrant_id for p in clip.outcome.placements} == set(ids)
    assert clip.facts["outcome"]["placements"][0]["entrant_id"] == clip.outcome.placements[0].entrant_id


def test_the_outcome_is_the_last_round_and_the_whole_clip(no_ffmpeg, tmp_path):
    clip = _race(tmp_path)
    o = clip.outcome
    assert o.format == "race" and o.margin_s == clip.facts["margin_s"]
    assert o.winner == clip.facts["winner"]
    ranks = [p.rank for p in o.placements]
    assert ranks == sorted(ranks) and ranks[0] == 1
    finished = [p for p in o.placements if p.status == "finished"]
    assert [p.entrant_id for p in finished] == list(clip.facts["finishes"])
    assert {p.status for p in o.placements} <= {"finished", "running", "stopped"}
    starts = [e for e in o.events if e.kind == "round_start"]
    assert [e.data["round"] for e in starts] == [0, 1]
    assert starts[1].t_s == pytest.approx(clip.facts["rounds"][0]["seconds"], abs=0.01)
    assert sum(1 for e in o.events if e.kind == "lead_change") == o.lead_changes
    assert clip.facts["story_attempts"] == 0 and clip.facts["story_seed"] == 7


def test_lead_changes_are_counted_the_way_stage_qa_counts_them(sandbox):
    cfg = settings.load().render
    for stage, seed in (("zigzag", 3), ("plinko", 11), ("funnels", 4)):
        r = physics.run_round(seed, "marble_race", {"stage": stage}, cfg, 540, 960, 30)
        race = physics_outcome.race_of(r)
        assert len(physics_outcome.lead_changes(race)) == stage_qa._leads(race)[0]


def test_placements_share_a_rank_on_a_tie():
    class B:
        def __init__(self, name):
            self.name, self.radius = name, 10.0

    r = {"finishes": {"a": 40, "b": 40, "c": 52}, "finish_s": {"a": 1.33, "b": 1.33, "c": 1.73},
         "balls": [B("a"), B("b"), B("c"), B("d"), B("e")],
         "states": [[(0, 500), (0, 500), (0, 500), (0, 300), (0, 200)]]}
    got = [(p.entrant_id, p.rank, p.status) for p in physics_outcome.placements(r, running=["d"])]
    assert got == [("a", 1, "finished"), ("b", 1, "finished"), ("c", 3, "finished"),
                   ("e", 4, "stopped"), ("d", 5, "running")]


def test_a_marble_flung_inside_a_field_is_launched(sandbox):
    """The threshold on lodestone: some races launch someone and most do not."""
    cfg = settings.load().render
    launched = 0
    for seed in range(700, 730):
        r = physics.run_round(seed, "marble_race", {"stage": "lodestone"}, cfg, 540, 960, 30)
        hits = physics_outcome.launches(r["states"], r["style"], 30)
        for f, i in hits:
            x, y = r["states"][f][i]
            assert any(math.hypot(x - m[0], y - m[1]) <= m[4] for m in r["style"].magnets)
        launched += bool(hits)
    assert 1 <= launched <= 15
    flat = physics.run_round(700, "marble_race", {"stage": "zigzag"}, cfg, 540, 960, 30)
    assert physics_outcome.launches(flat["states"], flat["style"], 30) == []


def test_a_launch_is_a_jump_past_the_threshold():
    style = physics.Style(stage="lodestone", magnets=[(0.0, 0.0, 10.0, 20.0, 1000.0, 1.0)])
    need = physics_outcome.LAUNCH_G_S * abs(physics.STAGE_GRAVITY["lodestone"])

    def states(jump):  # steady 10 px/s, then one frame `jump` px/s faster
        pos, out = 0.0, []
        for f in range(20):
            pos -= (10.0 + (jump if f == 15 else 0.0)) / 30
            out.append([(pos, 0.0)])
        return out

    assert physics_outcome.launches(states(need * 1.05), style, 30) == [(15, 0)]
    assert physics_outcome.launches(states(need * 0.95), style, 30) == []


def test_a_trapdoor_holding_a_marble_is_a_catch(sandbox):
    cfg = settings.load().render
    caught = 0
    for seed in range(700, 712):
        r = physics.run_round(seed, "marble_race", {"stage": "trapdoor"}, cfg, 540, 960, 30)
        caught += bool(physics_outcome.trap_catches(r["states"], [b.radius for b in r["balls"]], r["style"], 540))
    assert caught >= 2


def test_traits_change_the_race_and_unknown_ones_are_ignored_once(sandbox, caplog):
    cfg = settings.load().render
    plain = [dict(e, traits={}) for e in CAST]
    base = physics.run_round(5, "marble_race", {"stage": "zigzag", "cast": plain}, cfg, 540, 960, 30)
    assert [b.name for b in base["balls"]] == [e["id"] for e in CAST]
    tuned = physics.run_round(5, "marble_race", {"stage": "zigzag", "cast": CAST}, cfg, 540, 960, 30)
    assert base["states"][40] != tuned["states"][40]
    # Same lanes and launch: traits draw nothing from the seed's stream.
    import random

    import pymunk
    spawn = lambda cast: [tuple(b.body.position) + tuple(b.body.velocity)  # noqa: E731
                          for b in physics.build_race(pymunk.Space(), 540, 960, random.Random(5), "zigzag",
                                                      cast=cast)[0]]
    assert spawn(plain) == spawn(CAST)
    blaze = tuned["balls"][0]
    assert blaze.body.mass == pytest.approx((1.0 + blaze.radius / 40.0) * 0.9)

    physics.build._warned.discard("zap")
    odd = [dict(e, traits={"zap": 2}) for e in plain]
    with caplog.at_level(logging.WARNING):
        again = physics.run_round(5, "marble_race", {"stage": "zigzag", "cast": odd}, cfg, 540, 960, 30)
        physics.run_round(6, "marble_race", {"stage": "zigzag", "cast": odd}, cfg, 540, 960, 30)
    assert again["states"] == base["states"]
    assert sum("zap" in m for m in caplog.messages) == 1
    assert physics.PhysicsSandbox.supported_traits == physics.TRAITS


def test_force_immune_marbles_ignore_magnets(sandbox):
    cfg = settings.load().render
    plain = [dict(e, traits={}) for e in CAST]
    immune = [dict(e, traits={"force_immune": True}) for e in CAST]
    run = lambda cast, stage: physics.simulate(seed=12, variant="marble_race", sim_w=540, sim_h=960, fps=30,  # noqa: E731
                                               max_frames=240, stage=stage, cast=cast)[0]
    assert run(plain, "lodestone") != run(immune, "lodestone")
    assert run(plain, "zigzag") == run(immune, "zigzag")


def test_stage_qa_counts_a_casts_wins(sandbox):
    rep = stage_qa.run("funnels", range(700, 704), cast=CAST)
    assert sum(rep.wins.values()) == rep.finished and set(rep.wins) <= {e["id"] for e in CAST}
    row, outside = stage_qa.balance(rep, [e["id"] for e in CAST], scoring={"blaze", "tide", "volt"})
    assert row.startswith("| `funnels` | ") and "(guest)" in row
    assert all(not o.startswith("moss") for o in outside)


def test_a_cast_too_big_for_the_stage_is_refused(sandbox):
    cfg = settings.load().render
    crowd = [{"id": f"m{i}", "name": f"M{i}", "color": "#808080"} for i in range(14)]
    with pytest.raises(ValueError, match="no room"):
        physics.run_round(5, "marble_race", {"stage": "zigzag", "cast": crowd}, cfg, 540, 960, 30)


def test_story_seeds_never_rerun_another_attempts_simulation():
    from factory.generators.physics.model import MAX_ATTEMPTS

    reach = {a * 7919 + b for a in range(MAX_ATTEMPTS) for b in (0, 104729)}
    used = [{physics.story_seed(1000, k) + d for d in reach} for k in range(200)]
    assert len(set().union(*used)) == sum(len(u) for u in used)
    assert physics.story_seed(1000, 0) == 1000


def test_the_story_check_renders_a_race_that_meets_the_must(no_ffmpeg, tmp_path):
    clip = _race(tmp_path, cast=CAST, story={"must": {"lead_changes": ">=8"}, "prefer": {"margin_s": "<=0.5"}},
                 prefer_pool=2, level_id="L01", season_id="s0", format="race")
    assert not story.failures(clip.outcome, {"lead_changes": ">=8"})
    assert clip.facts["story_attempts"] >= 1
    assert clip.facts["story_seed"] == physics.story_seed(7, (clip.facts["story_seed"] - 7) // physics.STORY_STRIDE)
    assert trace.read(clip.trace_path)[1]["seed"] == clip.facts["story_seed"]
    # The same task gives the same choice.
    again = _race(tmp_path, "again", cast=CAST, story={"must": {"lead_changes": ">=8"}, "prefer": {"margin_s": "<=0.5"}},
                  prefer_pool=2)
    assert again.facts["story_seed"] == clip.facts["story_seed"]


def test_a_story_no_seed_can_meet_fails_loudly(no_ffmpeg, tmp_path):
    with pytest.raises(physics.StoryUnsatisfiable, match=r"^story_unsatisfiable: .*lead_changes.* 3 attempts"):
        _race(tmp_path, story={"must": {"lead_changes": ">=999"}}, max_story_attempts=3)
    assert issubclass(physics.StoryUnsatisfiable, RuntimeError)


def test_a_funnel_is_not_a_competition(no_ffmpeg, tmp_path):
    clip = physics.generate(seed=3, variant="funnel_drop", params={}, work_dir=tmp_path / "f")
    assert clip.outcome is None and clip.facts["outcome"] is None
    assert clip.trace_path.exists()
