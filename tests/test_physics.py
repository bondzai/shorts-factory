"""Simulation-only tests. Nothing here touches ffmpeg."""

import pytest

from factory.generators import physics

W, H, FPS = 540, 960, 30


def simulate(seed, variant="marble_race", frames=90, course="zigzag"):
    # Pinned to the zigzag course: these tests are about ramps. The other
    # courses have their own tests below.
    return physics.PhysicsSandbox()._simulate(
        seed=seed, variant=variant, sim_w=W, sim_h=H, fps=FPS, max_frames=frames,
        course=course if variant == "marble_race" else None,
    )


def test_same_seed_gives_the_same_run():
    a = simulate(4242)[0]
    b = simulate(4242)[0]
    assert a == b


def test_different_seeds_diverge():
    assert simulate(4242)[0][-1] != simulate(4243)[0][-1]


def test_marbles_are_moving_on_the_first_frame():
    states = simulate(4242)[0]
    assert states[0] != states[1]


def test_impacts_stay_inside_the_clip():
    states, impacts, *_ = simulate(4242)
    duration = len(states) / FPS
    assert impacts, "a marble course with no impacts would be silent"
    assert all(0 <= impact.t < duration for impact in impacts)


def test_nothing_escapes_the_walls():
    states, _, balls, *_ = simulate(4242, frames=200)
    for frame in states:
        for x, y in frame:
            assert -50 <= x <= W + 50
            assert -200 <= y <= H + 200


def test_a_wedged_race_raises_rather_than_returning_a_dead_clip(monkeypatch):
    # Force every marble to be seen as motionless.
    monkeypatch.setattr(physics, "STALL_SPEED", 10_000.0)
    with pytest.raises(physics._Stalled):
        simulate(4242, frames=200)


def test_a_settled_funnel_just_ends():
    monkeypatch_speed = physics.STALL_SPEED
    try:
        physics.STALL_SPEED = 10_000.0
        states, *_ = simulate(4242, variant="funnel_drop", frames=200)
    finally:
        physics.STALL_SPEED = monkeypatch_speed
    assert 0 < len(states) < 200


# --- variety ------------------------------------------------------------------
# Two independent judges called the old race template-like: the perceptual hash
# (0.875 and 0.914 between consecutive clips, against a 0.88 reject line) and an
# agent shown four frames. These pin the fix.

def _look(seed):
    states, _, balls, segments, _, _, style, _ = simulate(seed, frames=40)
    return {
        "ramps": len(segments),
        "marbles": len(balls),
        "background": style.background,
        "thickness": style.thickness,
        "colours": tuple(b.color for b in balls),
    }


def test_the_look_changes_between_seeds():
    looks = [_look(s) for s in (4100, 4211, 4322, 13, 7932, 23770)]
    assert len({l["background"] for l in looks}) > 1
    assert len({l["ramps"] for l in looks}) > 1
    assert len({l["thickness"] for l in looks}) > 1


def test_the_look_is_still_fixed_by_the_seed():
    assert _look(4100) == _look(4100)


def test_marble_count_fits_the_runway():
    """A nine-ramp course has short ramps; five marbles would start stacked."""
    for seed in (4100, 4211, 4322, 13, 7932, 23770, 991, 1234):
        look = _look(seed)
        assert 3 <= look["marbles"] <= 5
        assert len(set(look["colours"])) == look["marbles"]


def test_five_ramp_courses_are_not_offered():
    """Forced to five, every one of twelve seeds stalled. It is not a choice."""
    assert 5 not in (6, 7, 8, 9)
    looks = [_look(s)["ramps"] for s in (4100, 4211, 4322, 13, 7932, 23770)]
    assert all(r in (6, 7, 8, 9) for r in looks)


def test_a_course_finishing_under_the_qc_floor_is_refused(monkeypatch):
    from factory import settings

    raw = settings.load().raw
    monkeypatch.setitem(raw, "qc", {**raw["qc"], "min_seconds": 999})
    with pytest.raises(physics._Stalled, match="floor"):
        simulate(4242, frames=600)


# --- courses ------------------------------------------------------------------
# Each course was measured over 24 seeds before it was allowed in; these pin
# the shape, not the numbers — the numbers live in the README.

def test_every_offered_course_builds_and_moves():
    for course in physics.COURSES:
        states, impacts, balls, segments, *_ , style, _ = simulate(4242, frames=60, course=course)
        assert style.course == course
        assert states[0] != states[1], f"{course}: nothing moved on frame one"
        assert impacts, f"{course}: silent"


def test_pegboard_and_bumpers_are_circles_not_ramps():
    *_, style, _ = simulate(4242, frames=5, course="pegboard")
    assert style.circles and len(style.circles) >= 30
    *_, style, _ = simulate(4242, frames=5, course="bumpers")
    assert style.circles and 20 <= len(style.circles) <= 40


def test_an_unknown_course_names_the_known_ones():
    with pytest.raises(ValueError, match="zigzag"):
        simulate(1, frames=5, course="wedges")


def test_the_seed_picks_the_course_when_none_is_given():
    seen = set()
    for seed in range(40):
        *_, style, _ = physics.PhysicsSandbox()._simulate(
            seed=seed, variant="marble_race", sim_w=W, sim_h=H, fps=FPS, max_frames=3)
        seen.add(style.course)
    assert seen == set(physics.COURSES)


def test_the_theme_dresses_the_race(monkeypatch):
    from datetime import date
    from factory import themes, settings

    monkeypatch.setitem(settings.load().raw.setdefault("themes", {}), "force", "christmas")
    *_, balls, _, _, _, style, _ = simulate(4242, frames=5)
    assert style.theme == "christmas" and style.decoration == "snow"
    assert {b.name for b in balls} <= {"red", "green", "gold", "white", "blue"}


# --- two rounds, and the things that make a still frame move -----------------

def test_the_final_is_run_by_the_marbles_that_ran_the_heat():
    from factory import settings

    gen = physics.PhysicsSandbox(); cfg = settings.load().render
    heat = gen._round(7100, "marble_race", {}, cfg, W, H, FPS)
    lineup = [(b.name, b.color) for b in heat["balls"]]
    other = [c for c in physics.COURSES if c != heat["style"].course][0]
    final = gen._round(7100 + 104729, "marble_race", {"course": other}, cfg, W, H, FPS, lineup=lineup)
    assert [b.name for b in final["balls"]] == [b.name for b in heat["balls"]]
    assert final["style"].course != heat["style"].course


def test_spinners_live_only_in_the_bumper_field():
    """On the zigzag a bar knocked marbles back up the ramp until 10 seeds in
    24 never finished; among pegs it reads as a glitch. Measured, then pinned."""
    for course in physics.COURSES:
        *_, style, _ = simulate(4242, frames=3, course=course)
        assert bool(style.spinners) == (course == "bumpers"), course


def test_opening_mid_action_shifts_every_clock_together():
    from factory import settings

    gen = physics.PhysicsSandbox(); cfg = dict(settings.load().render)
    whole = gen._round(4242, "marble_race", {"skip_start_s": 0}, cfg, W, H, FPS)
    cut = gen._round(4242, "marble_race", {"skip_start_s": 1.0}, cfg, W, H, FPS)
    assert len(cut["states"]) == len(whole["states"]) - FPS
    assert cut["winner_frame"] == whole["winner_frame"] - FPS
    assert cut["margin_s"] == whole["margin_s"]
    assert all(im.t >= 0 for im in cut["impacts"])


def test_a_long_caption_shrinks_to_fit_the_frame(sandbox):
    gen = physics.PhysicsSandbox()
    short = gen._overlay("marble_race", W, H, FPS, text="RED BY 0.4s")
    long = gen._overlay("marble_race", W, H, FPS, text="FINAL · VIOLET TOOK THE HEAT")
    assert long[1].size < short[1].size
    assert long[2] >= 0  # left edge inside the frame


def test_a_photo_finish_is_not_written_as_zero_seconds():
    assert physics._seconds(0.04) == "0.04 seconds"
    assert physics._seconds(1.24) == "1.2 seconds"
