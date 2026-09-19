"""Simulation-only tests. Nothing here touches ffmpeg."""

import pytest

from factory.generators import physics

W, H, FPS = 540, 960, 30


def simulate(seed, variant="marble_race", frames=90):
    return physics.PhysicsSandbox()._simulate(
        seed=seed, variant=variant, sim_w=W, sim_h=H, fps=FPS, max_frames=frames
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
    states, _, balls, segments, _, _, style = simulate(seed, frames=40)
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
