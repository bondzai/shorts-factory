"""Ball battle: it ends, it is fair, and the facts tell the truth."""

from collections import Counter

import pytest

from factory import pipeline
from factory.generators import battle

W, H, FPS = 540, 960, 30


def run(seed, seconds=22.0, n=4):
    style = battle.Style(seed=seed)
    gen = battle.BallBattle()
    return gen._simulate(seed, W, H, FPS, seconds, style, n), style


def test_it_is_registered_and_ready():
    from factory import generators
    assert generators.all_generators()["battle"].ready is True
    assert "battle" in generators.available(None)


def test_a_seed_is_deterministic():
    (a, *_), _ = run(11)
    (b, *_), _ = run(11)
    assert a == b


def test_it_ends_with_one_standing_and_names_the_eliminated_in_order():
    (states, impacts, winner, winner_frame, eliminated, timed_out), style = run(3)
    names = {f.name for f in style.fighters}
    assert winner in names
    assert len(states) / FPS <= 22.0 + 1e-6
    if not timed_out:
        assert len(eliminated) == 3 and winner not in [n for n, _ in eliminated]
        assert [fr for _, fr in eliminated] == sorted(fr for _, fr in eliminated)
        assert len(states) - 1 - winner_frame <= int(FPS * battle.POST_WIN_S) + 1
    assert impacts and all(0 <= i.t <= len(states) / FPS for i in impacts)


def test_health_only_goes_down_and_a_dead_ball_stays_dead():
    (states, *_), _ = run(5)
    for i in range(4):
        hp = [s[i][3] for s in states]
        assert all(b <= a + 1e-9 for a, b in zip(hp, hp[1:]))
        alive = [s[i][4] for s in states]
        assert all(not (not a and b) for a, b in zip(alive, alive[1:]))


def test_most_seeds_finish_inside_the_cap():
    finished = sum(1 for seed in range(12) if not run(seed)[0][5])
    assert finished >= 8, f"only {finished}/12 seeds finished before the cap"


def test_no_colour_is_favoured():
    """Fair means the winner's colour is the seed's, not the module's."""
    wins = Counter(run(seed)[0][2] for seed in range(24))
    assert max(wins.values()) <= 12, wins


def test_facts_drive_the_spoiler_gate(sandbox):
    facts = {"winner": "red", "finishes": {"blue": 5.0, "amber": 9.2, "green": 12.0, "red": 13.4}}
    assert pipeline.spoiler(facts, title="Red survives the arena") is not None
    assert pipeline.spoiler(facts, title="Pick a fighter: red, blue, amber or green") is None


def test_frames_are_the_right_size(sandbox):
    (states, _, winner, winner_frame, *_), style = run(7, seconds=2.0)
    frames = list(battle.BallBattle()._frames(states[:10], style, W, H, FPS, "PICK A FIGHTER", winner, winner_frame))
    assert len(frames) == 10 and all(len(f) == W * H * 3 for f in frames)


def test_the_default_hook_comes_from_the_bank(sandbox):
    hook = battle.BallBattle()._default_hook(1)
    assert hook and hook == hook.upper()
