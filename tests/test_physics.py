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
