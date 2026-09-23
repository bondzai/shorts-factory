"""Composable stages: the registry, the sections' clearances, and QA.

The clearances are the lessons the hand-built stages taught one stuck marble
at a time; here they are asserted for every section, so a section cannot
quietly lose one. Whether a stack actually races is `factory stage-qa`'s
job over many seeds; the suite runs a small smoke of it.
"""

import json
import math
import random

import pymunk
import pytest

from factory import stage_qa
from factory.generators import physics, stagekit

W, H = 540, 960
BIG = W * stagekit.MARBLE_R  # largest marble radius the race builder makes


def build(section, top=700.0, bottom=400.0, seed=1):
    space = pymunk.Space()
    style = physics.Style()
    segments = stagekit.SECTIONS[section](space, W, top, bottom, random.Random(seed), style)
    return style, segments


# --- the registry ------------------------------------------------------------------

def test_one_registry_every_derived_name_agrees():
    ids = [st.id for st in physics.STAGE_SPECS]
    assert len(ids) == len(set(ids))
    for derived in (physics.STAGES, physics.STAGE_GRAVITY, physics.STAGE_NOUN, physics.STAGE_BLURB, physics.BUILDERS):
        assert set(derived) == set(ids)
    assert abs(sum(physics.STAGES.values()) - 1.0) < 1e-9
    assert set(physics.LIVE_STAGES) == {st.id for st in physics.STAGE_SPECS if st.weight > 0}


def test_ten_composed_stages_are_live():
    composed_live = [st.id for st in physics.STAGE_SPECS if st.composed and st.live]
    assert len(composed_live) >= 10, composed_live


def test_a_trial_stage_renders_when_named_but_is_never_picked_at_random(monkeypatch):
    """Weight 0 is trial: named in a task it races, left to the seed it never comes up."""
    trial = "labyrinth"
    monkeypatch.setitem(physics.STAGES, trial, 0.0)
    picked = set()
    for seed in range(200):
        sim = physics.simulate(seed=seed, variant="marble_race", sim_w=W, sim_h=H, fps=30, max_frames=2)
        picked.add(sim[6].stage)
    assert trial not in picked and len(picked) > 10
    sim = physics.simulate(seed=5, variant="marble_race", sim_w=W, sim_h=H, fps=30, max_frames=2, stage=trial)
    assert sim[6].stage == trial


def test_every_composed_stage_names_real_sections_and_describes_itself():
    for st in physics.STAGE_SPECS:
        if not st.composed:
            continue
        assert all(name in stagekit.SECTIONS for name, _ in st.parts)
        text = st.describe(physics.Style(), [])
        assert text.startswith("a stage of ") and ", then " in text


# --- clearances every section keeps ---------------------------------------------------

@pytest.mark.parametrize("section", sorted(stagekit.SECTIONS))
def test_nothing_solid_outside_the_band(section):
    """What keeps two stacked sections from making a pocket between them."""
    top, bottom = 700.0, 400.0
    for seed in range(6):
        style, segments = build(section, top, bottom, seed)
        for x, y, r in style.circles:
            assert bottom - r - 1 <= y <= top + r + 1, (section, y)
        for a, b in list(segments) + [(a, b) for a, b, _ in style.belts]:
            for p in (a, b):
                assert bottom - 1 <= p[1] <= top + 1, (section, p)
        for x, y, r, _ in style.drums:
            assert y - r >= bottom - 1 and y + r <= top + 1, (section, y, r)
        for x, y, half, *_ in style.spinners:
            assert y - half >= bottom - 1 and y + half <= top + 1, (section, y, half)
        for x, y, half, omega, phase, *bias in style.rockers:
            rise = math.sin(physics.ROCK_AMPLITUDE + abs(bias[0] if bias else 0)) * half
            assert y + rise <= top + 1 and y - rise >= bottom - 1, (section, y, rise)
        for x, y, core, *_ in style.magnets:
            assert bottom - core - 1 <= y <= top + core + 1, (section, y)


def test_pegs_leave_a_marble_between_them_and_no_corner_at_the_walls():
    for seed in range(12):
        style, _ = build("pegs", seed=seed)
        rows: dict[float, list] = {}
        for x, y, r in style.circles:
            rows.setdefault(round(y, 3), []).append((x, r))
            left, right = x - r - 7.0, (W - 7.0) - (x + r)
            assert not (0 < left < stagekit.marble_room(W)) and not (0 < right < stagekit.marble_room(W))
        for pegs in rows.values():
            pegs.sort()
            for (x1, r1), (x2, r2) in zip(pegs, pegs[1:]):
                assert x2 - x1 - r1 - r2 >= 2 * BIG * 1.05, (seed, x1, x2)
        ys = sorted(rows)
        for y1, y2 in zip(ys, ys[1:]):
            assert y2 - y1 >= 66 - 1e-6, (seed, y1, y2)  # the three-peg cup


def test_chutes_leave_a_marble_under_every_throat():
    for seed in range(8):
        _, segments = build("chutes", top=800, bottom=300, seed=seed)
        tops = sorted({round(max(a[1], b[1])) for a, b in segments}, reverse=True)
        lows = sorted({round(min(a[1], b[1])) for a, b in segments}, reverse=True)
        # the lowest point of one row to the highest point of the next
        for low, next_top in zip(lows, tops[1:]):
            if next_top < low:
                assert low - next_top >= stagekit.marble_room(W) * 0.6, (seed, low, next_top)


def test_spinner_sweeps_never_meet_and_clear_the_walls():
    for seed in range(8):
        style, _ = build("spinners", top=800, bottom=300, seed=seed)
        bars = style.spinners
        for i, (x1, y1, h1, *_) in enumerate(bars):
            assert x1 - h1 >= stagekit.marble_room(W) * 0.9 and x1 + h1 <= W - stagekit.marble_room(W) * 0.9
            for x2, y2, h2, *_ in bars[i + 1:]:
                assert math.hypot(x2 - x1, y2 - y1) - h1 - h2 >= 2 * BIG, (seed,)


def test_belts_carry_toward_their_open_end():
    for seed in range(6):
        style, _ = build("belts", seed=seed)
        for a, b, speed in style.belts:
            assert speed > 0 and b[1] < a[1]  # downhill toward b
            assert abs(a[0] - 10.0) < 1 or abs(a[0] - (W - 10.0)) < 1  # starts at a wall
            gap = min(b[0], W - b[0])
            assert gap >= stagekit.marble_room(W)  # open end leaves room to drop


# --- the magnet: the kit's one force ---------------------------------------------------

def test_magnet_cores_clear_the_walls_and_no_two_fields_overlap():
    """Two things the pull being safe rests on. A core closer to a wall than a
    marble is the pocket `_cornered` names; two overlapping fields would sum
    past the one gravity the cap was measured at."""
    for seed in range(12):
        style, _ = build("magnets", top=800, bottom=300, seed=seed)
        assert style.magnets, seed
        room = stagekit.marble_room(W)
        for x, y, core, soft, reach, pull in style.magnets:
            assert x - core - 7.0 >= room - 1e-6, (seed, x, core)
            assert (W - 7.0) - (x + core) >= room - 1e-6, (seed, x, core)
            assert pull == stagekit.MAGNET_PULL
            assert soft == pytest.approx(core + W * stagekit.MARBLE_R)
        for i, (x1, y1, _c1, _s1, r1, _p1) in enumerate(style.magnets):
            for x2, y2, _c2, _s2, r2, _p2 in style.magnets[i + 1:]:
                assert math.hypot(x2 - x1, y2 - y1) >= r1 + r2 - 1e-6, (seed, x1, x2)


def test_the_pull_is_bounded_everywhere_and_is_exactly_zero_at_reach():
    """A naive 1/r^2 goes to infinity at the centre and a discrete solver turns
    that into a marble through a wall. Bounded near the centre, and shifted so
    it reaches zero at `reach` rather than stepping off a cliff."""
    soft, reach, peak = 44.6, 142.7, 30.0
    at = lambda r: math.hypot(*stagekit.magnet_accel(r, 0.0, soft, reach, peak))
    assert at(0.0) == 0.0                      # no direction at dead centre
    assert at(1e-6) <= peak and at(0.5) <= peak
    values = [at(r) for r in range(1, int(reach))]
    assert max(values) <= peak                 # bounded by the cap everywhere
    assert values == sorted(values, reverse=True)   # and monotonic
    assert at(reach) == 0.0 and at(reach + 10) == 0.0 and at(reach * 4) == 0.0
    # the shift is what makes the edge smooth: nearly nothing left just inside
    assert at(reach - 1.0) < peak * 0.01


def test_a_magnet_pulls_a_marble_off_its_line_and_cannot_hold_it():
    """The feature and its limit in one drop. Measured at peak pull 1.0 g: the
    marble ends tens of px off the line it would have fallen down, and still
    gets to the floor -- a magnet that can be out-pulled by gravity cannot
    hold anything against a surface."""
    def drop(magnet: bool):
        space = pymunk.Space()
        space.gravity = (0.0, -30.0)
        floor = pymunk.Segment(space.static_body, (0, 6), (W, 6), 6.0)
        floor.elasticity, floor.friction = 0.46, 0.30
        space.add(floor)
        core, my = 16.0, 480.0
        soft = core + W * stagekit.MARBLE_R
        reach = soft * stagekit.MAGNET_REACH
        stagekit._magnet(space, W / 2, my, core)
        radius = W * stagekit.MARBLE_R
        ball = physics.make_ball(space, (W / 2 + 60.0, 900.0), radius, (255, 0, 0), "red")
        ball.body.velocity = (0.0, -130.0)
        for _ in range(30 * 20):
            for _ in range(4):
                if magnet:
                    ax, ay = stagekit.magnet_accel(W / 2 - ball.body.position.x,
                                                   my - ball.body.position.y, soft, reach,
                                                   stagekit.MAGNET_PULL * 30.0)
                    ball.body.force = (ball.body.mass * ax, ball.body.mass * ay)
                space.step(1.0 / (30 * 4))
        return ball.body.position

    pulled, free = drop(True), drop(False)
    assert abs(pulled.x - free.x) > 10.0, (pulled.x, free.x)   # off its line
    assert pulled.y < 6.0 + 3 * W * stagekit.MARBLE_R          # and down at the floor


def test_the_magnet_stage_is_the_same_race_twice():
    """A force applied per substep is a new way to lose determinism: the same
    seed has to give the same positions, or a re-render is a different clip."""
    runs = [physics.simulate(seed=4242, variant="marble_race", sim_w=W, sim_h=H, fps=30,
                             max_frames=120, stage="lodestone") for _ in range(2)]
    assert runs[0][6].magnets == runs[1][6].magnets
    assert runs[0][0] == runs[1][0]


def test_a_marble_on_a_belt_moves_the_way_the_belt_runs():
    space = pymunk.Space(); space.gravity = (0, -120)
    stagekit._belt(space, (0, 0), (400, 0), 120.0, 4)
    body = pymunk.Body(1, pymunk.moment_for_circle(1, 0, 20)); body.position = (100, 25)
    shape = pymunk.Circle(body, 20); shape.friction = 0.22; space.add(body, shape)
    for _ in range(240):
        space.step(1 / 120)
    assert body.position.x > 120


# --- the rocker bias ------------------------------------------------------------------

def test_composed_rockers_rock_about_a_tilt_and_legacy_ones_about_level():
    style, _ = build("rockers", seed=3)
    assert all(len(r) == 6 and abs(r[5]) >= 0.24 for r in style.rockers)
    sim = physics.simulate(seed=9000, variant="marble_race", sim_w=W, sim_h=H, fps=30, max_frames=10, stage="rockers")
    assert all(len(r) == 5 for r in sim[6].rockers)


# --- QA -----------------------------------------------------------------------------

def test_qa_measures_and_judges(sandbox):
    rep = stage_qa.run("zigzag", [9000, 9053])
    assert rep.seeds == 2 and rep.finished == 2 and len(rep.durations) == 2
    assert rep.out == 0
    row = rep.row()
    assert row.startswith("| `zigzag` |")


def test_qa_gates_name_what_failed():
    rep = stage_qa.Report(stage="x", gravity=-40, seeds=10, finished=8, first_try=2, runner_up=1,
                          parked=5, others=10, out=1, durations=[9.0] * 8, leads=[0] * 8)
    problems = " ".join(rep.problems())
    for word in ("finishes 8/10", "first try 2/10", "runner-up 1/8", "parked 5/10", "1 out of frame", "median 9.0s", "lead changes 0.0"):
        assert word in problems
    assert not rep.passed


def test_gravity_override_is_put_back(sandbox):
    before = physics.STAGE_GRAVITY["plinko"]
    with stage_qa.gravity("plinko", -123.0):
        assert physics.STAGE_GRAVITY["plinko"] == -123.0
    assert physics.STAGE_GRAVITY["plinko"] == before


def test_the_report_is_a_table_with_every_stage(sandbox):
    reps = [stage_qa.Report(stage="a", gravity=-40, seeds=1, finished=1, first_try=1, runner_up=1, durations=[14.0], leads=[3])]
    text = stage_qa.report_markdown(reps, 1)
    assert "| `a` | hand-built | trial |" in text and "| stage | built from | status | gravity |" in text


# --- re-renders keep their stage ---------------------------------------------------------

def test_a_rehook_pins_the_stages_the_clip_raced_on(sandbox, monkeypatch):
    from factory import channels, db, pipeline
    from factory.pipeline import building

    seen = {}

    def fake_render(conn, ch, clip_id, params, by="human"):
        seen.update(params)
        raise RuntimeError("stop here")

    monkeypatch.setattr(building, "render_stage", fake_render)
    with db.connect() as conn:
        db.migrate(conn)
        channels.create(conn, name="Main", channel_id="main")
        cid = db.insert_clip(conn, channel_id="main", generator="physics", variant="marble_race", seed=7, params={}, hook="", plan_why="t")
        db.update(conn, cid, status="awaiting_approval",
                  facts_json=json.dumps({"rounds": [{"stage": "cascade"}, {"stage": "drums"}]}))
        pipeline.rehook(conn, cid, "CALL IT NOW")
    assert seen["stage"] == "cascade" and seen["final_stage"] == "drums"


def test_no_sieve_bar_is_flat():
    """A flat bar is a ledge. The first sieve section flattened its edge rows."""
    for seed in range(12):
        _, segments = build("sieve", seed=seed)
        for a, b in segments:
            run, rise = abs(b[0] - a[0]), abs(b[1] - a[1])
            assert rise >= 0.40 * run, (seed, a, b)
