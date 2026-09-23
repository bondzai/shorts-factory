"""Six stages, one registry, and the old name still understood.

Every stage is measured, not trusted: a builder that looks right in a still
can stall in the solver or finish under the QC floor. The seeds here are
few, because the suite must stay fast; the 24-seed measurement is in the
commit message and README.
"""

import json

import pytest

from factory import channels, db, settings, tasks
from factory.generators import physics

W, H, FPS = 540, 960, 30
SEEDS = (9000, 9053, 9106, 9159, 9212, 9265)


def test_every_stage_is_registered_everywhere():
    names = set(physics.STAGES)
    assert names == set(physics.BUILDERS) == set(physics.STAGE_GRAVITY) == set(physics.STAGE_NOUN) == set(physics.STAGE_BLURB)
    assert names >= {"zigzag", "pegboard", "bumpers", "funnels", "gauntlet", "cascade"}
    assert set(physics.SPINNER_STAGES) <= names and set(physics.SPINNER_ROWS) == set(physics.SPINNER_STAGES)
    assert set(physics.WHEEL_STAGES) <= names and not (set(physics.WHEEL_STAGES) & set(physics.SPINNER_STAGES))
    assert abs(sum(physics.STAGES.values()) - 1.0) < 1e-6


@pytest.mark.parametrize("stage", sorted(physics.STAGES))
def test_each_stage_finishes_inside_the_window(sandbox, stage):
    """Through the retry loop, every seed here ends with a winner and a
    duration QC will accept."""
    cfg = settings.load().render
    floor, ceiling = float(settings.load().qc["min_seconds"]), float(cfg["max_seconds"])
    for seed in SEEDS:
        r = physics.run_round(seed, "marble_race", {"stage": stage}, cfg, W, H, FPS)
        assert r["winner"] is not None, (stage, seed)
        assert floor <= r["duration_s"] <= ceiling + 2, (stage, seed, r["duration_s"])
        assert r["style"].stage == stage


def test_spinning_bars_only_where_they_belong():
    for stage in physics.STAGES:
        sim = None
        for seed in SEEDS:
            try:
                sim = physics.simulate(seed=seed, variant="marble_race", sim_w=W, sim_h=H, fps=FPS, max_frames=30, stage=stage)
                break
            except physics.Stalled:
                continue
        assert sim is not None
        style = sim[6]
        spec = physics.STAGE_BY_ID[stage]
        if spec.composed:
            # A composed stage's bars come from its sections, never the add-on.
            has_bars = any(name in ("spinners", "wheel") for name, _ in spec.parts)
            assert bool(style.spinners) == has_bars, (stage, len(style.spinners))
            continue
        wheel = physics.WHEEL_STAGES.get(stage, 0)
        lo, hi = physics.SPINNER_STAGES.get(stage, (wheel, wheel))
        assert lo <= len(style.spinners) <= hi, (stage, len(style.spinners))


def test_the_gauntlet_bars_are_gates_that_span_the_lane():
    sim = physics.simulate(seed=9000, variant="marble_race", sim_w=W, sim_h=H, fps=FPS, max_frames=30, stage="gauntlet")
    style = sim[6]
    left = min(a[0] for a, b in style.lane); right = max(a[0] for a, b in style.lane)
    for x, y, half, omega, phase in style.spinners:
        assert 2 * half >= 0.7 * (right - left)
        assert left < x < right


def test_cascade_wall_gaps_clear_the_largest_marble():
    """The first cascade wedged 13 seeds in 24: its wall gaps were narrower
    than a big marble. A gap must clear the largest radius twice over."""
    for seed in SEEDS:
        try:
            sim = physics.simulate(seed=seed, variant="marble_race", sim_w=W, sim_h=H, fps=FPS, max_frames=30, stage="cascade")
        except physics.Stalled:
            continue
        balls, segments = sim[2], sim[3]
        biggest = max(b.radius for b in balls)
        peaks = [b for a, b in segments if b[0] < W / 2 and a[0] > 40]  # left ends of peak ramps
        for end in peaks:
            assert end[0] - 14.0 >= 2 * biggest * 1.05, (seed, end[0], biggest)


def test_the_stage_text_names_every_stage():
    gen = physics.PhysicsSandbox()
    for stage in physics.STAGES:
        style = physics.Style(); style.stage = stage; style.circles = [(0, 0, 1)] * 4
        text = physics.stage_text({"style": style, "segments": [None] * 6})
        assert text and "{" not in text


# --- the old name --------------------------------------------------------------

def test_course_is_still_accepted_as_the_old_name_for_stage(sandbox):
    with db.connect() as conn:
        db.migrate(conn)
        channels.create(conn, name="Main", channel_id="main")
        tasks.enqueue(conn, "main", "make-clip", {"course": "bumpers", "seed": 5})
        row = db.claim_task(conn, "t", channel_id="main")
        assert json.loads(row["params_json"])["stage"] == "bumpers"
        _, use = tasks.held_params(conn, "main", {"stage": None, "seed": None})
        assert use["stage"] == "bumpers"
        conn.execute("UPDATE tasks SET params_json = ? WHERE id = ?", (json.dumps({"course": "pegboard"}), row["id"]))
        _, use = tasks.held_params(conn, "main", {"stage": None})
        assert use["stage"] == "pegboard"


def test_an_unknown_stage_is_refused_at_enqueue(sandbox):
    with db.connect() as conn:
        db.migrate(conn)
        channels.create(conn, name="Main", channel_id="main")
        with pytest.raises(ValueError, match="no stage"):
            tasks.enqueue(conn, "main", "make-clip", {"stage": "moon"})


def test_old_facts_with_course_read_as_stage_on_the_page():
    from factory.api.common import facts_for_page
    assert facts_for_page({"course": "zigzag", "theme": "default", "seed": 1}) == {"stage": "zigzag", "theme": "default"}
    assert facts_for_page({"stage": "funnels"}) == {"stage": "funnels"}


# --- the run-in throat, and what it is allowed to touch ------------------------

def test_the_throat_is_only_on_the_stages_it_measured_better_on():
    assert set(physics.GATE_STAGES) <= set(physics.STAGES)
    # The zigzag already changes the lead five to seven times on its own; a
    # throat turned that into a queue and the half-way leader started winning
    # 76% of them. Leaving it alone is the measurement, not a preference.
    assert "zigzag" not in physics.GATE_STAGES


def test_a_gated_stage_sometimes_gets_one_and_an_ungated_stage_never_does():
    def gated(stage, seeds):
        out = 0
        for seed in seeds:
            for attempt in range(4):
                try:
                    sim = physics.simulate(
                        seed=seed + attempt * 7919, variant="marble_race", sim_w=W, sim_h=H,
                        fps=FPS, max_frames=40, stage=stage)
                except physics.Stalled:
                    continue
                out += bool(sim[6].gates)
                break
        return out

    seeds = [9000 + i * 53 for i in range(20)]
    assert gated("bumpers", seeds) > 0
    assert gated("zigzag", seeds) == 0
    assert gated("pegboard", seeds) == 0


def test_the_throat_sits_in_the_run_in_and_clears_the_biggest_marble():
    for seed in [9000 + i * 53 for i in range(30)]:
        try:
            sim = physics.simulate(seed=seed, variant="marble_race", sim_w=W,
                                                     sim_h=H, fps=FPS, max_frames=40, stage="bumpers")
        except physics.Stalled:
            continue
        balls, style = sim[2], sim[6]
        if not style.gates:
            continue
        ends = [b for a, b in style.gates]
        ys = [y for _, y in ends]
        # Above the line (110) and well below where the marbles start.
        assert all(110 < y < H * 0.5 for y in ys), ys
        gap = abs(ends[0][0] - ends[1][0])
        assert gap > 2 * max(b.radius for b in balls) * 1.4, (seed, gap)


def test_the_marbles_are_near_enough_the_same_size():
    """The spread used to be +/-12% and the smallest marble won 60% of
    zigzags against a 33% chance: the race was decided when the sizes were
    drawn. Identical marbles were measured to change the lead more often,
    not less, so nothing was lost by halving it."""
    lo, hi = physics.MARBLE_SPREAD
    assert hi - lo <= 0.13, (lo, hi)
    assert lo < 1.0 < hi


def test_a_throat_is_named_in_the_clip_text_when_there_is_one():
    gen = physics.PhysicsSandbox()
    style = physics.Style()
    style.stage, style.circles = "bumpers", [(0, 0, 1)] * 30
    assert "throat" not in physics.stage_text({"style": style, "segments": []})
    style.gates.append(((0.0, 200.0), (100.0, 200.0)))
    assert "throat" in physics.stage_text({"style": style, "segments": []})
