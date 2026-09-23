"""The physics itself: one round, and the retry loop around it.

Nothing here draws or writes: it returns positions per frame, the impacts
that were heard, and the finish arithmetic the rest of the clip is built on.
"""

from __future__ import annotations

import math
import random

import pymunk

from ... import audio, settings
from ..stagekit import magnet_accel
from .build import build_funnel, build_race
from .model import (FUNNEL_GRAVITY, IMPACT_DV, MAX_ATTEMPTS, MAX_IMPACTS_PER_FRAME, MAX_SPEED, PACE_QUICKER,
                    PACE_SLOWER, POST_WIN_MAX_S, POST_WIN_S, RACE_GRAVITY, ROCK_AMPLITUDE,
                    STALL_SPEED, SUBSTEPS, Stalled)

def run_round(seed, variant, params, cfg, sim_w, sim_h, fps, lineup=None) -> dict:
    """One simulated race, opened mid-action, with its finish arithmetic."""
    max_frames = int(float(params.get("max_seconds", cfg["max_seconds"])) * fps)
    skip = int(float(params.get("skip_start_s", cfg.get("skip_start_s", 0))) * fps)
    # The QC floor applies to what ships, which is after the skip.
    min_frames = int(float(settings.load().qc["min_seconds"]) * fps) + skip
    # About one race seed in six wedges a marble or finishes under the
    # floor. Rather than burn the seed, derive the next attempt from it —
    # still fully determined by `seed` — and lean gravity the way the
    # failure points: slower after a too-fast finish, quicker after a
    # stall. Pace is what each stage's gravity was tuned by anyway.
    pace = 1.0
    for attempt in range(MAX_ATTEMPTS):
        try:
            sim = simulate(
                seed=seed + attempt * 7919, variant=variant, sim_w=sim_w, sim_h=sim_h,
                fps=fps, max_frames=max_frames, stage=params.get("stage") or params.get("course"),
                background=params.get("background"), lineup=lineup, pace=pace, min_frames=min_frames,
            )
            if variant == "marble_race" and sim[4] is None:
                # Ran out of frames with nobody across the line. A marble
                # rattling against a spinning bar never drops below
                # STALL_SPEED, so the speed check misses it: measured on a
                # bumpers seed that jittered for 18 seconds and shipped.
                # (A progress-based check was tried and cut: it burned 6
                # of 24 seeds that would have finished.)
                raise Stalled(f"no winner in {max_frames / fps:.1f}s")
            break
        except Stalled as exc:
            if attempt == MAX_ATTEMPTS - 1:
                raise RuntimeError(
                    f"{variant} seed {seed} stalled on every one of {MAX_ATTEMPTS} attempts ({exc})"
                ) from None
            pace *= PACE_SLOWER if "under the" in str(exc) else PACE_QUICKER
    states, impacts, balls, segments, winner, winner_frame, style, finishes = sim
    # Open mid-action: drop the gate. Everything time-based shifts with it.
    skip = max(0, min(skip, max(0, len(states) - fps * 2)))
    if skip:
        states = states[skip:]
        impacts = [audio.Impact(im.t - skip / fps, im.strength, im.index, im.pan) for im in impacts if im.t >= skip / fps]
        winner_frame = None if winner_frame is None else max(0, winner_frame - skip)
        finishes = {name: max(0, f - skip) for name, f in finishes.items()}
    duration_s = len(states) / fps
    impacts = [im for im in impacts if im.t < duration_s]
    finish_s = {name: round(f / fps, 2) for name, f in sorted(finishes.items(), key=lambda kv: kv[1])}
    order = list(finish_s)
    runner_up = order[1] if len(order) > 1 else None
    margin_s = round(finish_s[order[1]] - finish_s[order[0]], 2) if runner_up else None
    return {
        "states": states, "impacts": impacts, "balls": balls, "segments": segments, "style": style,
        "winner": winner, "winner_frame": winner_frame, "finishes": finishes, "finish_s": finish_s,
        "runner_up": runner_up, "margin_s": margin_s, "duration_s": duration_s, "attempts": attempt + 1,
    }


def simulate(*, seed: int, variant: str, sim_w: int, sim_h: int, fps: int, max_frames: int,
    stage: str | None = None, background: str | None = None, lineup: list | None = None,
    pace: float = 1.0, min_frames: int | None = None, stall_speed: float = STALL_SPEED,
):
    """Run the physics only. Raises Stalled when a race goes nowhere, or
    finishes before min_frames (the QC floor, by default)."""
    rng = random.Random(seed)
    space = pymunk.Space()
    if variant == "marble_race":
        space.gravity = (0.0, RACE_GRAVITY)
        balls, segments, style = build_race(space, sim_w, sim_h, rng, stage, background, lineup)
        space.gravity = (0.0, space.gravity.y * pace)
        style.seed = seed
        finish_y: float | None = 110.0
    else:
        space.gravity = (0.0, FUNNEL_GRAVITY)
        balls, segments, style = build_funnel(space, sim_w, sim_h, rng)
        finish_y = None

    dt = 1.0 / (fps * SUBSTEPS)
    # The magnet's pull is a multiple of the stage's own gravity, which is
    # fixed for the run by the time the build and the pace lean are done.
    gravity_mag = abs(space.gravity.y)
    pull_cap = max((m[5] for m in style.magnets), default=0.0) * gravity_mag
    states: list[list[tuple[float, float]]] = []
    impacts: list[audio.Impact] = []
    previous = [(b.body.velocity.x, b.body.velocity.y) for b in balls]
    winner: str | None = None
    winner_frame: int | None = None
    finishes: dict[str, int] = {}
    stalled = 0

    for frame in range(max_frames):
        for ball in balls:
            v = ball.body.velocity
            if v.length > MAX_SPEED:
                ball.body.velocity = v * (MAX_SPEED / v.length)
        for kind, body, params in style.kinematics:
            if kind == "rocker":
                omega, phase, *rest = params
                t = frame / fps
                body.angle = (rest[0] if rest else 0.0) + ROCK_AMPLITUDE * math.sin(omega * t + phase)
                body.angular_velocity = ROCK_AMPLITUDE * omega * math.cos(omega * t + phase)
        for _ in range(SUBSTEPS):
            # Magnets are applied per substep, not per frame: the force depends
            # on where the marble is, and at four substeps a frame a marble
            # crosses a good part of a field between frames. Applied once a
            # frame the pull is stale by the time it matters, and the same seed
            # gives a visibly different race at a different substep count.
            # `body.force` is set, not accumulated, so nothing carries over.
            if style.magnets:
                for ball in balls:
                    px, py = ball.body.position
                    ax = ay = 0.0
                    for mx, my, _core, soft, reach, pull in style.magnets:
                        dax, day = magnet_accel(mx - px, my - py, soft, reach, pull * gravity_mag)
                        ax += dax
                        ay += day
                    # Fields are placed two reaches apart so they cannot overlap,
                    # but a stack is composed at run time and this is the cheap
                    # guarantee that the measured cap holds however they land.
                    total = math.hypot(ax, ay)
                    if total > pull_cap:
                        ax, ay = ax * pull_cap / total, ay * pull_cap / total
                    ball.body.force = (ball.body.mass * ax, ball.body.mass * ay)
            space.step(dt)

        frame_impacts = []
        for i, ball in enumerate(balls):
            vx, vy = ball.body.velocity
            dv = math.hypot(vx - previous[i][0], vy - previous[i][1])
            previous[i] = (vx, vy)
            if dv > IMPACT_DV:
                frame_impacts.append(
                    audio.Impact(
                        t=frame / fps,
                        strength=min(1.0, dv / 900.0),
                        index=i,
                        pan=(ball.body.position.x / sim_w) * 2 - 1,
                    )
                )
        frame_impacts.sort(key=lambda im: -im.strength)
        impacts.extend(frame_impacts[:MAX_IMPACTS_PER_FRAME])
        states.append([(b.body.position.x, b.body.position.y) for b in balls])

        # Everything coming to rest ends the pour, but in a race it means a
        # marble is wedged and the clip is dead.
        if max(b.body.velocity.length for b in balls) < stall_speed:
            stalled += 1
        else:
            stalled = 0
        if stalled > fps * 1.5:
            if finish_y is None:
                break
            raise Stalled(f"no winner by {frame / fps:.1f}s")
        if finish_y is not None:
            # Every crossing is recorded, not only the first: the gap to
            # the runner-up is what the opening caption is built from.
            for ball in balls:
                if ball.name in finishes:
                    continue
                if ball.body.position.y - ball.radius <= finish_y:
                    finishes[ball.name] = frame
                    if winner is None:
                        winner, winner_frame = ball.name, frame
        if winner_frame is not None:
            second = sorted(finishes.values())[1] if len(finishes) > 1 else None
            if second is not None and frame >= second + int(fps * POST_WIN_S):
                break
            if frame >= winner_frame + int(fps * POST_WIN_MAX_S):
                break

    # Varying the stage changed the duration spread as well as the look,
    # and a short stage can now finish under the QC floor. The generator
    # knows that floor, so it burns the seed here rather than handing QC a
    # clip it is certain to reject.
    # Only judge a race that actually finished: a run cut off by max_frames
    # has no meaningful duration yet, and short runs are exactly what the
    # tests use.
    if finish_y is not None and winner_frame is not None:
        need = min_frames if min_frames is not None else int(float(settings.load().qc["min_seconds"]) * fps)
        if len(states) < need:
            raise Stalled(
                f"finished in {len(states) / fps:.1f}s, under the {need / fps:.1f}s floor"
            )

    return states, impacts, balls, segments, winner, winner_frame, style, finishes
