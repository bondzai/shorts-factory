"""The physics itself: one round, and the retry loop around it.

Nothing here draws or writes: it returns positions per frame, the impacts
that were heard, and the finish arithmetic the rest of the clip is built on.
"""

from __future__ import annotations

import math
import random

import pymunk

from ... import audio, settings
from ..mechanics import Rig, expand_teams
from ..stagekit import magnet_accel
from .build import build_funnel, build_race
from .registry import MECHANICS
from .model import (FUNNEL_GRAVITY, IMPACT_DV, MAX_ATTEMPTS, MAX_IMPACTS_PER_FRAME, MAX_SPEED, PACE_QUICKER,
                    PACE_SLOWER, POST_WIN_MAX_S, POST_WIN_S, RACE_GRAVITY, ROCK_AMPLITUDE,
                    STALL_SPEED, SUBSTEPS, Stalled, trap_angle)

# A `jitter` trait's kick, per frame, as a fraction of what the stage's
# gravity adds to a marble's speed in that frame, times the trait's value;
# the direction is uniform. Scaled to gravity because the stages run from
# -30 to -600: a kick in px/s that nudges on the zigzag would throw a marble
# across a -30 pegboard. The kicks come from their own stream, derived from
# the seed, so the build's draws are untouched.
JITTER_G = 0.5
_JITTER_SALT = 0x6A177E4

def run_round(seed, variant, params, cfg, sim_w, sim_h, fps, lineup=None, *,
              post_win_s: float | None = None, post_win_max_s: float | None = None,
              round_index: int = 0) -> dict:
    """One simulated race, opened mid-action, with its finish arithmetic."""
    if params.get("teams"):
        # Two (or three) marbles a persona: `blaze.1`, `blaze.2`, shaded.
        params = {**params, "cast": expand_teams(params.get("cast"), params["teams"])}
    stage = params.get("stage") or params.get("course")
    if not stage and params.get("section") in MECHANICS:
        stage = MECHANICS[params["section"]].stage
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
                fps=fps, max_frames=max_frames, stage=stage,
                background=params.get("background"), lineup=lineup, cast=params.get("cast"),
                pace=pace, min_frames=min_frames,
                post_win_max_s=POST_WIN_MAX_S if post_win_max_s is None else post_win_max_s,
                post_win_s=POST_WIN_S if post_win_s is None else post_win_s,
                params=params, round_index=round_index,
            )
            rig = sim[6].rig
            if variant == "marble_race" and sim[4] is None and not (rig is not None and rig.all_gone):
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
    fmt = params.get("format") if params.get("format") in ("elimination", "last_standing") else "race"
    gone: dict[str, int] = {}
    mech_events: list = []
    rig = style.rig
    if rig is not None and rig.live:
        # What the mechanics did, on the clip's clock: drawn from style.mech,
        # counted from `gone` and the events.
        style.mech = rig.snapshot(skip)
        gone = dict(style.mech.get("gone") or {})
        mech_events = rig.shifted_events(skip)
    return {
        "states": states, "impacts": impacts, "balls": balls, "segments": segments, "style": style,
        "winner": winner, "winner_frame": winner_frame, "finishes": finishes, "finish_s": finish_s,
        "runner_up": runner_up, "margin_s": margin_s, "duration_s": duration_s, "attempts": attempt + 1,
        "format": fmt, "gone": gone, "mech_events": mech_events, "stage_picked": not stage,
        "win_by": ("survival" if winner is not None and winner not in finishes else "finish") if winner else None,
    }


def simulate(*, seed: int, variant: str, sim_w: int, sim_h: int, fps: int, max_frames: int,
    stage: str | None = None, background: str | None = None, lineup: list | None = None,
    pace: float = 1.0, min_frames: int | None = None, stall_speed: float = STALL_SPEED,
    post_win_s: float = POST_WIN_S, post_win_max_s: float = POST_WIN_MAX_S, cast: list | None = None,
    params: dict | None = None, round_index: int = 0,
):
    """Run the physics only. Raises Stalled when a race goes nowhere, or
    finishes before min_frames (the QC floor, by default).

    `params` reach the round's mechanics rig (generators/mechanics.py). A rig
    nothing registers on is not `live`, and then every line below runs
    exactly as it did before the rig existed."""
    rng = random.Random(seed)
    space = pymunk.Space()
    rig: Rig | None = None
    if variant == "marble_race":
        space.gravity = (0.0, RACE_GRAVITY)
        rig = Rig(seed=seed, w=sim_w, h=sim_h, fps=fps, params=params, round_index=round_index)
        balls, segments, style = build_race(space, sim_w, sim_h, rng, stage, background, lineup, cast, rig=rig)
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
    jitter = [float(b.traits.get("jitter", 0.0)) for b in balls]
    jitter_rng = random.Random(seed ^ _JITTER_SALT) if any(jitter) else None
    kick = JITTER_G * gravity_mag / fps
    immune = [bool(b.traits.get("force_immune")) for b in balls]
    live = rig is not None and rig.live
    if live:
        rig.start(space, gravity_mag)
        finish_y = rig.finish_y
    settled: int | None = None  # live only: the frame nobody was left racing

    for frame in range(max_frames):
        if live:
            rig.before_frame(frame)
        if jitter_rng is not None:
            for k, (ball, amount) in enumerate(zip(balls, jitter)):
                if amount and live and not rig.alive[k]:
                    jitter_rng.uniform(0.0, 2 * math.pi)  # the stream stays in step
                elif amount:
                    angle = jitter_rng.uniform(0.0, 2 * math.pi)
                    v = ball.body.velocity
                    ball.body.velocity = (v.x + math.cos(angle) * kick * amount,
                                          v.y + math.sin(angle) * kick * amount)
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
            elif kind == "trapdoor":
                # The door's angle is a piecewise clock, so its rate comes from
                # where it will be next frame rather than from a derivative:
                # the dwells are flat and the sweeps ease in and out, and
                # pymunk only needs the rate to get the friction right on a
                # marble sliding off a door that is already moving.
                period, phase = params
                t = frame / fps
                body.angle = trap_angle(t, period, phase)
                body.angular_velocity = (trap_angle(t + 1.0 / fps, period, phase) - body.angle) * fps
        for _ in range(SUBSTEPS):
            # Magnets are applied per substep, not per frame: the force depends
            # on where the marble is, and at four substeps a frame a marble
            # crosses a good part of a field between frames. Applied once a
            # frame the pull is stale by the time it matters, and the same seed
            # gives a visibly different race at a different substep count.
            # `body.force` is set, not accumulated, so nothing carries over.
            if live and rig.pushes:
                # The same magnet law, times a polarity clock, plus the pair
                # forces and drag zones a section registered.
                rig.substep(style, immune, gravity_mag, pull_cap, dt)
            elif style.magnets:
                for ball, skip_field in zip(balls, immune):
                    if skip_field:
                        continue
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
            if live and not rig.alive[i]:
                continue  # out of the race: out of the space, and silent
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
        if live:
            # Out-zones and breakables act on where the step left everyone. An
            # eliminated marble keeps its last position in the states (the
            # trace's arrays are one shape) and is not drawn from its frame on.
            rig.after_frame(frame)

        # Everything coming to rest ends the pour, but in a race it means a
        # marble is wedged and the clip is dead.
        moving = [b for k, b in enumerate(balls) if rig.alive[k]] if live else balls
        if moving and max(b.body.velocity.length for b in moving) < stall_speed:
            stalled += 1
        else:
            stalled = 0
        if stalled > fps * 1.5:
            # A stall before anyone crosses is a wedged marble and the clip is
            # dead. After the winner it is the opposite: the field has come to
            # rest, so nothing more will cross and there is nothing left to
            # wait for. Raising here burned a race that had already been won,
            # and the longer tail is exactly the stretch where a strung-out
            # field settles: measured, the field comes to rest inside the tail
            # in 1% of races at 2.8 s, 4% at 5.0 s and 15% at 8.0 s. Retrying
            # those handed back a worse race — keeping them is worth 20 more
            # runner-ups in 733 on its own.
            if finish_y is None or winner_frame is not None:
                break
            raise Stalled(f"no winner by {frame / fps:.1f}s")
        if finish_y is not None:
            # Every crossing is recorded, not only the first: the gap to
            # the runner-up is what the opening caption is built from.
            for k, ball in enumerate(balls):
                if ball.name in finishes or (live and not rig.alive[k]):
                    continue
                if ball.body.position.y - ball.radius <= finish_y:
                    finishes[ball.name] = frame
                    if live:
                        rig.mark_finished(ball.name)
                    if winner is None and not (live and rig.elimination and rig.win == "last_standing"):
                        winner, winner_frame = ball.name, frame
        if live:
            # The elimination formats (docs/10): the race is decided when one
            # marble is left, or — first_across — by the first across the line.
            contenders = rig.contenders
            if rig.elimination and winner is None:
                if rig.win == "last_standing" and len(contenders) <= 1 and (finishes or contenders):
                    first = min(finishes, key=lambda n: (finishes[n], n)) if finishes else None
                    winner, winner_frame = first or rig.names[contenders[0]], frame
                elif rig.win == "first_across" and len(contenders) == 1 and rig.gone and len(balls) > 1:
                    winner, winner_frame = rig.names[contenders[0]], frame
            if settled is None and not contenders and (winner_frame is not None or rig.all_gone):
                settled = frame
            if settled is not None and frame >= settled + int(fps * post_win_s):
                break
            if (rig.elimination and rig.win == "last_standing" and winner_frame is not None
                    and frame >= winner_frame + int(fps * post_win_s)):
                break
        if winner_frame is not None:
            second = sorted(finishes.values())[1] if len(finishes) > 1 else None
            if second is not None and frame >= second + int(fps * post_win_s):
                break
            if frame >= winner_frame + int(fps * post_win_max_s):
                break

    # Varying the stage changed the duration spread as well as the look,
    # and a short stage can now finish under the QC floor. The generator
    # knows that floor, so it burns the seed here rather than handing QC a
    # clip it is certain to reject.
    # Only judge a race that actually finished: a run cut off by max_frames
    # has no meaningful duration yet, and short runs are exactly what the
    # tests use.
    decided = winner_frame is not None or (live and rig.all_gone)
    if (finish_y is not None or live) and decided:
        need = min_frames if min_frames is not None else int(float(settings.load().qc["min_seconds"]) * fps)
        if len(states) < need:
            raise Stalled(
                f"finished in {len(states) / fps:.1f}s, under the {need / fps:.1f}s floor"
            )

    return states, impacts, balls, segments, winner, winner_frame, style, finishes
