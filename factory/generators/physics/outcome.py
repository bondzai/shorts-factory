"""What a race produced, measured from the simulation alone.

Everything here reads positions per frame, the balls' plain data and the
style, so it gives the same answer on a live round as on one loaded back
from a trace. Nothing draws and nothing simulates.
"""

from __future__ import annotations

import math

from ...series.outcome import Event, Outcome, Placement
from .. import stagekit
from .registry import STAGE_GRAVITY

# The lead is sampled every LEAD_SAMPLE frames over the race — up to the
# winner's crossing — exactly as stage QA counts it (`stage_qa._leads`), so the
# number a season's story asks for is the number the stage gate was set on.
LEAD_SAMPLE = 15

# `launched`: inside a magnet's reach, a marble's speed rises by at least
# LAUNCH_G_S x the stage's gravity (px/s) within LAUNCH_WINDOW frames, measured
# from the slowest frame in the window. Gravity plus the strongest field today
# (pull 1.0 x gravity) can add at most 2 g x 0.27 s = 0.53 g-s in that window,
# so a rise of 1.2 g-s takes the field slinging a marble off something. On
# lodestone it fires in 10 of 96 races (seeds 700-795); on a stage without
# magnets it cannot fire. One event per marble per visit to a field.
LAUNCH_G_S = 1.2
LAUNCH_WINDOW = 8

# `trap_catch`: a marble in a trapdoor's pit (stage QA's `_in_pit`) that makes
# less than its own radius of headway over TRAP_HOLD_FRAMES — it is sitting on
# the door, not falling through the pit. Measured on trapdoor, 48 seeds: 27 of
# 50 pit visits are holds, and 21 races have at least one.
TRAP_HOLD_FRAMES = 15


def lead_changes(race, gone: dict[int, int] | None = None) -> list[tuple[int, int]]:
    """(frame, new leader's index) for every change of the lowest marble,
    sampled as stage QA samples it. `race` ends at the winner's crossing.
    `gone` (index -> frame) leaves out marbles already eliminated: one frozen
    at the bottom of a pit is not leading anything."""
    leader, out = None, []
    for frame in range(0, len(race), LEAD_SAMPLE):
        ys = [y for _, y in race[frame]]
        racing = [i for i in range(len(ys)) if not gone or gone.get(i, frame + 1) > frame]
        if not racing:
            break
        now = min(racing, key=lambda i: ys[i])
        if leader is not None and now != leader:
            out.append((frame, now))
        leader = now
    return out


def race_of(round_: dict):
    """The race part of a round: up to and including the winner's crossing."""
    states = round_["states"]
    end = round_["winner_frame"] if round_["winner_frame"] is not None else len(states) - 1
    return states[: end + 1]


def launches(states, style, fps: int) -> list[tuple[int, int]]:
    """(frame, index) for each marble flung inside a magnet's field."""
    if not style.magnets:
        return []
    need = LAUNCH_G_S * abs(STAGE_GRAVITY.get(style.stage, 0.0))
    out = []
    for i in range(len(states[0]) if states else 0):
        speeds = [0.0] + [math.dist(states[f][i], states[f - 1][i]) * fps for f in range(1, len(states))]
        armed = True
        for f in range(1, len(states)):
            x, y = states[f][i]
            inside = any(math.hypot(x - m[0], y - m[1]) <= m[4] for m in style.magnets)
            if not inside:
                armed = True
                continue
            if armed and f >= LAUNCH_WINDOW and speeds[f] - min(speeds[f - LAUNCH_WINDOW:f]) >= need:
                out.append((f, i))
                armed = False
    return out


def trap_catches(states, radii, style, sim_w: float, gone: dict[int, int] | None = None) -> list[tuple[int, int]]:
    """(frame, index) for each marble a trapdoor held: the frame the hold began.
    An eliminated marble is judged only up to its elimination (it stands
    still after that because it is gone, not because it is held)."""
    if not style.traps:
        return []
    from ... import stage_qa  # the pit test stage QA's `held` uses; lazily, it imports physics

    big = sim_w * stagekit.MARBLE_R
    out = []
    for i, radius in enumerate(radii):
        until = (gone or {}).get(i, len(states))
        inside = [any(stage_qa._in_pit(s[i], t, big) for t in style.traps) for s in states[:until]]
        f = 0
        while f < len(inside):
            if not inside[f]:
                f += 1
                continue
            end = f
            while end < len(inside) and inside[end]:
                end += 1
            hold = next((k for k in range(f, end - TRAP_HOLD_FRAMES)
                         if states[k][i][1] - states[k + TRAP_HOLD_FRAMES][i][1] < radius), None)
            if hold is not None:
                out.append((hold, i))
            f = end
    return out


def placements(round_: dict, running: list[str]) -> list[Placement]:
    """Finishers by crossing frame, then the rest by the lowest point they
    reached, then the eliminated, the last one out first. The marble an
    elimination race was decided on by survival ranks first. Ties share a
    rank (1, 1, 3)."""
    finishes, balls, states = round_["finishes"], round_["balls"], round_["states"]
    gone = round_.get("gone") or {}
    survivor = round_.get("winner") if round_.get("win_by") == "survival" else None
    keyed = []
    for i, ball in enumerate(balls):
        if ball.name in finishes:
            keyed.append(((0, finishes[ball.name]), ball.name, round_["finish_s"][ball.name], "finished"))
        elif ball.name in gone:
            keyed.append(((2, -gone[ball.name]), ball.name, None, "eliminated"))
        elif ball.name == survivor:
            keyed.append(((0, -1), ball.name, None, "running"))
        else:
            lowest = min(s[i][1] for s in states) - ball.radius
            keyed.append(((1, lowest), ball.name, None, "running" if ball.name in running else "stopped"))
    keyed.sort(key=lambda k: k[0])
    return [Placement(entrant_id=name, rank=1 + sum(1 for other in keyed if other[0] < key),
                      time_s=time_s, status=status)
            for key, name, time_s, status in keyed]


def build(rounds: list[dict], fps: int, sim_w: float, running: list[str]) -> Outcome:
    """The Outcome of a marble race: placements and margin from the last
    round, lead changes summed over every round, events on the clip's clock.
    `running` is who was still on the move when the last round cut."""
    events: list[Event] = []
    total_leads = 0
    offset = 0.0
    for n, r in enumerate(rounds):
        names = [b.name for b in r["balls"]]
        gone = {names.index(name): f for name, f in (r.get("gone") or {}).items()}
        at = lambda frame: round(offset + frame / fps, 3)  # noqa: E731
        events.append(Event(t_s=round(offset, 3), kind="round_start", data={"round": n}))
        changes = lead_changes(race_of(r), gone)
        total_leads += len(changes)
        events += [Event(t_s=at(f), kind="lead_change", entrant_id=names[i], data={"round": n}) for f, i in changes]
        events += [Event(t_s=at(f), kind="finish", entrant_id=name, data={"round": n})
                   for name, f in sorted(r["finishes"].items(), key=lambda kv: (kv[1], kv[0]))]
        events += [Event(t_s=at(f), kind="trap_catch", entrant_id=names[i], data={"round": n})
                   for f, i in trap_catches(r["states"], [b.radius for b in r["balls"]], r["style"], sim_w, gone)]
        events += [Event(t_s=at(f), kind="launched", entrant_id=names[i], data={"round": n})
                   for f, i in launches(r["states"], r["style"], fps)]
        # What a round's mechanics emitted: `eliminated`, `broke`, and any
        # kind a world names (docs/10-mechanics.md, "Event kinds").
        events += [Event(t_s=at(f), kind=kind, entrant_id=None if i is None else names[i],
                         data={**data, "round": n})
                   for f, kind, i, data in r.get("mech_events") or ()]
        offset += r["duration_s"]
    order = {"round_start": 0, "lead_change": 1, "trap_catch": 2, "launched": 3, "eliminated": 4, "finish": 5}
    events.sort(key=lambda e: (e.t_s, order.get(e.kind, 9), e.entrant_id or ""))
    last = rounds[-1]
    facts = {"rounds": [{"stage": r["style"].stage, "winner": r["winner"], "margin_s": r["margin_s"]}
                        for r in rounds],
             "entrants": len(last["balls"])}
    # Only what happened is added, so a plain race's outcome is what it was.
    if last.get("gone"):
        facts["eliminations"] = len(last["gone"])
    teams = {b.name: b.team for b in last["balls"] if getattr(b, "team", None)}
    if teams:
        facts["teams"] = teams
    if last.get("format", "race") != "race":
        facts["win"] = last.get("win_by")
    return Outcome(
        format=last.get("format", "race"),
        placements=placements(last, running),
        margin_s=last["margin_s"],
        lead_changes=total_leads,
        events=events,
        facts=facts,
    )
