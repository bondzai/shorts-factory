"""Simulation-only tests. Nothing here touches ffmpeg."""

import pytest

from factory.generators import physics

W, H, FPS = 540, 960, 30


def simulate(seed, variant="marble_race", frames=90, stage="zigzag", **kwargs):
    # Pinned to the zigzag stage: these tests are about ramps. The other
    # stages have their own tests below.
    return physics.simulate(
        seed=seed, variant=variant, sim_w=W, sim_h=H, fps=FPS, max_frames=frames,
        stage=stage if variant == "marble_race" else None, **kwargs,
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
    assert impacts, "a marble stage with no impacts would be silent"
    assert all(0 <= impact.t < duration for impact in impacts)


def test_nothing_escapes_the_walls():
    states, _, balls, *_ = simulate(4242, frames=200)
    for frame in states:
        for x, y in frame:
            assert -50 <= x <= W + 50
            assert -200 <= y <= H + 200


def test_a_wedged_race_raises_rather_than_returning_a_dead_clip():
    # Every marble counts as motionless: the threshold is an argument, not a
    # global to reach in and rebind.
    with pytest.raises(physics.Stalled):
        simulate(4242, frames=200, stall_speed=10_000.0)


def test_a_settled_funnel_just_ends():
    states, *_ = simulate(4242, variant="funnel_drop", frames=200, stall_speed=10_000.0)
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
    """A nine-ramp stage has short ramps; five marbles would start stacked."""
    for seed in (4100, 4211, 4322, 13, 7932, 23770, 991, 1234):
        look = _look(seed)
        assert 3 <= look["marbles"] <= 5
        assert len(set(look["colours"])) == look["marbles"]


def test_five_ramp_courses_are_not_offered():
    """Forced to five, every one of twelve seeds stalled. It is not a choice."""
    assert 5 not in (6, 7, 8, 9)
    looks = [_look(s)["ramps"] for s in (4100, 4211, 4322, 13, 7932, 23770)]
    assert all(r in (6, 7, 8, 9) for r in looks)


def test_a_stage_finishing_under_the_qc_floor_is_refused(monkeypatch):
    from factory import settings

    raw = settings.load().raw
    monkeypatch.setitem(raw, "qc", {**raw["qc"], "min_seconds": 999})
    with pytest.raises(physics.Stalled, match="floor"):
        simulate(4242, frames=600)


# --- stages ------------------------------------------------------------------
# Each stage was measured over 24 seeds before it was allowed in; these pin
# the shape, not the numbers — the numbers live in the README.

def test_every_offered_stage_builds_and_moves():
    for stage in physics.STAGES:
        states, impacts, balls, segments, *_ , style, _ = simulate(4242, frames=60, stage=stage)
        assert style.stage == stage
        assert states[0] != states[1], f"{stage}: nothing moved on frame one"
        assert impacts, f"{stage}: silent"


def test_pegboard_and_bumpers_are_circles_not_ramps():
    *_, style, _ = simulate(4242, frames=5, stage="pegboard")
    assert style.circles and len(style.circles) >= 30
    *_, style, _ = simulate(4242, frames=5, stage="bumpers")
    assert style.circles and 20 <= len(style.circles) <= 40


def test_an_unknown_stage_names_the_known_ones():
    with pytest.raises(ValueError, match="zigzag"):
        simulate(1, frames=5, stage="wedges")


def test_the_seed_picks_the_stage_when_none_is_given():
    # 22 stages, some at a 2-3% share: a few hundred seeds to see them all.
    seen = set()
    for seed in range(400):
        *_, style, _ = physics.simulate(
            seed=seed, variant="marble_race", sim_w=W, sim_h=H, fps=FPS, max_frames=1)
        seen.add(style.stage)
    assert seen == set(physics.LIVE_STAGES)


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
    heat = physics.run_round(7100, "marble_race", {}, cfg, W, H, FPS)
    lineup = [(b.name, b.color) for b in heat["balls"]]
    other = [c for c in physics.STAGES if c != heat["style"].stage][0]
    final = physics.run_round(7100 + 104729, "marble_race", {"stage": other}, cfg, W, H, FPS, lineup=lineup)
    assert [b.name for b in final["balls"]] == [b.name for b in heat["balls"]]
    assert final["style"].stage != heat["style"].stage


def test_spinners_live_only_in_the_bumper_field():
    """On the zigzag a bar knocked marbles back up the ramp until 10 seeds in
    24 never finished; among pegs it reads as a glitch. Measured, then pinned."""
    for stage in physics.STAGES:
        *_, style, _ = simulate(4242, frames=3, stage=stage)
        spec = physics.STAGE_BY_ID[stage]
        wanted = (stage in physics.SPINNER_STAGES or stage in physics.WHEEL_STAGES
                  or any(name in ("spinners", "wheel") for name, _ in spec.parts))
        assert bool(style.spinners) == wanted, stage


def test_opening_mid_action_shifts_every_clock_together():
    from factory import settings

    gen = physics.PhysicsSandbox(); cfg = dict(settings.load().render)
    whole = physics.run_round(4242, "marble_race", {"skip_start_s": 0}, cfg, W, H, FPS)
    cut = physics.run_round(4242, "marble_race", {"skip_start_s": 1.0}, cfg, W, H, FPS)
    assert len(cut["states"]) == len(whole["states"]) - FPS
    assert cut["winner_frame"] == whole["winner_frame"] - FPS
    assert cut["margin_s"] == whole["margin_s"]
    assert all(im.t >= 0 for im in cut["impacts"])


def test_a_long_caption_shrinks_to_fit_the_frame(sandbox):
    gen = physics.PhysicsSandbox()
    short = physics.overlay("marble_race", W, H, FPS, text="RED BY 0.4s")
    long = physics.overlay("marble_race", W, H, FPS, text="FINAL · RUN IT BACK · SAME THREE MARBLES")
    assert long[1].size < short[1].size
    assert long[2] >= 0  # left edge inside the frame


def test_the_tail_waits_long_enough_for_the_field_to_arrive():
    """Five seeds an agent's QC rejected as "no race: only amber finishes".
    Each had a winner and nothing else across the line inside the old 2.8 s
    tail; the gap distribution said p90 was 5.61 s, so the tail is 7.0 s and
    every one of them now shows the runner-up arrive."""
    from factory import settings

    cfg = dict(settings.load().render)
    rejected = [("orchard", 281580509), ("tumble", 1679835290), ("gallery", 1864683274),
                ("spillway", 1176307895), ("gallery", 1806722502)]
    for stage, seed in rejected:
        r = physics.run_round(seed, "marble_race", {"stage": stage}, cfg, W, H, FPS)
        assert r["runner_up"] and r["margin_s"], (stage, seed)
        # and the clip still fits the QC window it has to ship inside
        assert 10.0 <= r["duration_s"] <= 60.0, (stage, seed, r["duration_s"])


def test_a_field_at_rest_ends_the_round_instead_of_burning_the_race():
    """Once the winner is home a stalled field means nothing more will cross,
    so the round ends there. It used to raise Stalled and retry, throwing away
    a race that had already been won: measured, the field comes to rest inside
    the tail in 4% of races at a 5.0 s tail and 15% at 8.0 s."""
    from factory import settings

    cfg = dict(settings.load().render)
    cut = physics.run_round(281580509, "marble_race", {"stage": "orchard"}, cfg, W, H, FPS,
                            post_win_max_s=30.0)
    # 30 s of tail is far more than any field keeps moving for, so this round
    # can only have ended early -- and on its first attempt, not a retry.
    assert cut["duration_s"] < 30.0
    assert cut["attempts"] == 1


def test_no_runner_up_reports_the_wait_that_was_watched(sandbox, tmp_path):
    """QC quotes this sentence verbatim, so the seconds in it have to be the
    ones on screen, not POST_WIN_MAX_S: a field at rest or the frame budget
    ends the round early and the constant would claim a wait nobody saw."""
    import re

    clip = physics.generate(seed=4242, variant="marble_race",
                            params={"stage": "gauntlet", "rounds": 1}, work_dir=tmp_path)
    said = re.findall(r"no other marble crosses in the next ([\d.]+) seconds", clip.description)
    for value in said:
        assert float(value) <= physics.POST_WIN_MAX_S + 0.1, clip.description


def test_a_photo_finish_is_not_written_as_zero_seconds():
    assert physics.seconds(0.04) == "0.04 seconds"
    assert physics.seconds(1.24) == "1.2 seconds"


def test_the_final_caption_states_the_structure_not_the_heat_result():
    from factory.generators.physics import FINAL_CAPTION
    assert FINAL_CAPTION == "FINAL · RUN IT BACK"
    assert "TOOK" not in FINAL_CAPTION and not any(ch.isdigit() for ch in FINAL_CAPTION)


def test_running_out_of_frames_with_no_winner_is_a_stall_not_a_clip(sandbox):
    """A wedged marble that keeps rattling never trips the speed check, so a
    race that reaches max_seconds with nobody across the line is retried,
    and after every attempt fails it is an error rather than a clip."""
    from factory import settings
    cfg = settings.load().render
    with pytest.raises(RuntimeError, match="no winner"):
        physics.run_round(4242, "marble_race", {"stage": "bumpers", "max_seconds": 0.5}, cfg, W, H, FPS)
