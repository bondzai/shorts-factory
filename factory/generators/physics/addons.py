"""What is added to a stage after its own builder has run.

The spinning bars some hand-built stages take, and the throat in the run-in
to the line. Both read the registry to decide whether this stage wants them.
"""

from __future__ import annotations

import random

import pymunk

from ..stagekit import _wall as wall, _peg as peg, _spinner as spinner, marble_room
from .model import Style
from .registry import GATE_STAGES, SPINNER_ROWS, SPINNER_STAGES, STAGE_BY_ID, TWIN_STAGES

# How much the marbles differ in size. This was +/-12%, with a comment
# saying identical marbles keep their starting order and never overtake.
# Measured over 20 seeds on three stages at four spreads, that is not what
# happens: identical marbles change the lead MORE often (zigzag 5.5 -> 6.0,
# bumpers 4.0 -> 5.0), and the spread was instead deciding the race before
# it started — the smallest marble won 60% of zigzags against a 33% chance,
# because a smaller marble is quicker through everything. Halved, which
# halves that bias and leaves the overtaking alone.
MARBLE_SPREAD = (0.94, 1.06)
FINISH_GATE_CHANCE = 0.72
# Only where it measured better, over 20 seeds a stage:
#
#   bumpers    half-way leader wins 50% -> 20%, came from last 60% -> 70%
#   gauntlet   half-way leader wins 47% -> 20%, came from last 42% -> 75%
#
# and not on the rest, for reasons the numbers gave rather than taste:
# the zigzag already changes the lead five to seven times on its own and a
# throat turns that into a queue (60% -> 76%); the pegboard traded a little
# surprise for most of its close finishes (40% -> 5%); the funnels stage is
# already a series of throats and one more read as noise (60% -> 72%).
#   pinwheel   half-way leader wins 75% -> 20%, came from last 35% -> 60%
#   sieve      70% -> 57%, came from last 35% -> 50%
#   drums      85% -> 65%
# The pinwheel came off the list after five unattended renders: with the
# throat, 15 of 20 seeds finish and 47% of marbles end the clip stuck in the
# pocket where a throat arm meets the peg above it; without it, 20 of 20
# and 5%. The surprise it bought (75% -> 20%) was bought with dead marbles.
# GATE_STAGES is derived from Stage.gate in the registry.
GATE_HEIGHT = 0.085  # of the frame above the line: close enough that nothing re-spreads
GATE_GAP = (0.17, 0.21)  # of the width; about 3-3.7 of the largest marble
GATE_GAP_COMPOSED = (0.21, 0.24)  # past two marbles side by side: no arch
GATE_RISE_COMPOSED = 0.16  # of the height, arm mouth over throat: slope about 0.5
# rad/s of the gauntlet's gates. Measured over 18 seeds: 0.7-1.1 never
# stalled but the field arrived one at a time; 1.1-1.6 gave photo finishes
# and two stalls; 1.0-1.5 gave both — no stalls, a runner-up on 8 of 18.
GAUNTLET_OMEGA = (1.0, 1.5)
# SPINNER_ROWS is derived from Stage.spinner_rows in the registry.

# --- the twin finish ----------------------------------------------------------
# The single throat gathers the field and then hands the race to whoever is in
# front of the queue. A twin finish asks one more question after that: the run-in
# forks, and the bounce that picks a side is the last thing that happens before
# the line. Turned on per stage with Stage.twin in the registry.
TWIN_GAP = (0.175, 0.205)  # of the width, EACH exit; floored at a marble's room below
TWIN_HALF = 0.075          # of the width, half the divider's base: 40 px on a 540 px frame
TWIN_RISE = 0.055          # of the height, the crown over the throat line: 53 px
# Half the crown, as a fraction of the width. A divider has to shed what lands
# on it, and docs/04 has both ways of getting that wrong measured on the
# cascade: a flat cap is a ledge a marble rests on, a bare point is an apex it
# balances on. The chutes section's answer is a short cap tilted at 0.4, which
# is the slope every stage in the kit holds its ramps at, so the crown here is
# the same shape at a quarter of the size.
TWIN_CAP = 0.028
TWIN_TILT = 0.4
# Tighter than the single throat's 0.42-0.58: the fork is three times as wide
# as one throat (2 x 0.19 w + 0.15 w = 0.53 w), so its outer tips would leave
# the frame at that spread.
TWIN_CENTRE = (0.46, 0.54)


def add_spinners(space, w, h, rng, style):
    """Rotating bars stacked down the open middle of the stage.

    A still frame of ramps is a diagram; a bar turning through the marbles is
    a thing happening, and several of them make every frame busy. They are
    kinematic — nothing a marble does slows them — so they cannot be trapped,
    only strike. Rows alternate left and right of centre so the marbles weave
    rather than meet a wall of bars. Not on the pegboard: a bar sweeping
    through a field of pegs reads as a glitch, not a mechanism.
    """
    if style.stage not in SPINNER_STAGES:
        return
    count = rng.randint(*SPINNER_STAGES[style.stage])
    rows_all = SPINNER_ROWS[style.stage]
    rows = sorted(rng.sample(rows_all, min(count, len(rows_all))))
    side = rng.choice([-1, 1])
    for row in rows:
        y = h * row + rng.uniform(-h * 0.02, h * 0.02)
        if style.stage == "gauntlet":
            # Gates, not obstacles: each bar spans most of the lane, so a
            # marble has to wait for the bar to turn before it can drop
            # through. With short bars every seed fell straight past them.
            lane_l = min(a[0] for a, b in style.lane) if style.lane else 0.0
            lane_r = max(a[0] for a, b in style.lane) if style.lane else w
            x = (lane_l + lane_r) / 2 + rng.uniform(-w * 0.02, w * 0.02)
            half = (lane_r - lane_l) * rng.uniform(0.34, 0.40)
            omega = rng.choice([-1, 1]) * rng.uniform(*GAUNTLET_OMEGA)
            # The pocket between a bar's tip and the lane wall is where
            # every gauntlet non-finisher was measured (x = 400-416 with the
            # wall at 458): the tip kept knocking the marble back up into
            # it. A wedge on each wall at the bar's height fills the pocket,
            # so the only way down is through the sweep — which is the gate.
            for wall, sign in ((lane_l, 1), (lane_r, -1)):
                tip = wall + sign * (lane_r - lane_l) * 0.5 - sign * half
                inner = tip + sign * 4.0  # just short of the sweep
                # Solid, and with its apex below the bar: two thin edges let
                # a pinched marble tunnel inside, and an apex level with the
                # bar was a point a marble balanced on. Apex under the bar,
                # the tip sweeps whatever rests there back into the lane.
                apex = (inner, y - h * 0.03)
                top_, bot_ = (wall, y + h * 0.06), (wall, y - h * 0.06)
                poly = pymunk.Poly(space.static_body, [top_, apex, bot_])
                poly.elasticity, poly.friction = 0.46, 0.30
                space.add(poly)
                style.lane_wedges += [(top_, apex), (apex, bot_)]
        else:
            x = w * (0.5 + side * rng.uniform(0.04, 0.12))
            half = w * rng.uniform(0.09, 0.13)
            omega = rng.choice([-1, 1]) * rng.uniform(1.4, 2.4)
        phase = rng.uniform(0, 3.14)
        spinner(space, x, y, half, omega, phase, style.thickness / 2)
        style.spinners.append((x, y, half, omega, phase))
        side = -side


def add_finish_gate(space, w, h, rng, style) -> None:
    """One slow bar across the run-in, on most seeds.

    Left to itself a marble that gets clear early stays clear, and the clip
    has nothing left to say after five seconds. The gate is the one place
    where the race regroups: the leader waits for it to turn, the others
    arrive, and they go through as a pack. What comes out the other side is
    a finish nobody could call — which is the thing worth watching.
    """
    if style.stage not in GATE_STAGES:
        return
    twin = style.stage in TWIN_STAGES
    # A twin finish is the whole point of the stages that ask for one, so it is
    # on every seed. The single throat stays on 72% of them, which is where it
    # was measured — and the roll is only taken on that path, so every seed a
    # gated stage has already rendered replays unchanged.
    if not twin and rng.random() > FINISH_GATE_CHANCE:
        return
    throat = h * GATE_HEIGHT + 110.0
    spec = STAGE_BY_ID.get(style.stage)
    composed = spec is not None and spec.composed
    # Composed stages run at low gravity, where the hand-built arms (slope
    # 0.34) are barely downhill: marbles sat on them for the last eight
    # seconds of a clip. Their arms are steeper.
    mouth = throat + h * (GATE_RISE_COMPOSED if composed else 0.11)
    if twin:
        _twin_finish(space, w, h, rng, style, throat, mouth)
        return
    centre = w * rng.uniform(0.42, 0.58)
    # A composed stage gets a wider throat. At 0.17-0.21 w two marbles can
    # arch across it; stage QA found 27 of switchback's 28 stuck marbles
    # jostling there, and it is where bumpers parks its marbles too. The
    # hand-built stages keep theirs so their seeds replay unchanged.
    gap = w * rng.uniform(*(GATE_GAP_COMPOSED if composed else GATE_GAP))
    _arms(space, w, style, throat, mouth, centre, gap / 2)


def _arms(space, w, style, throat: float, mouth: float, centre: float, inner: float) -> None:
    """The run-in's two outer ramps, from off-frame down to `inner` px either
    side of `centre`. Shared by the single throat and the twin finish, which
    differ only in where the arms stop and what sits between them."""
    for side in (-1, 1):
        a = (w / 2 + side * w * 0.62, mouth)  # past the wall, so nothing goes round
        b = (centre + side * inner, throat)
        wall(space, a, b, thickness=style.thickness / 2)
        style.gates.append((a, b))


def _twin_finish(space, w, h, rng, style, throat: float, mouth: float) -> None:
    """Two exits instead of one, split by a wedge on the throat line.

    What this buys: the single throat decides the race at the back of a
    queue, several seconds before the line. Here the field still queues, but
    the wedge splits it at the last moment, and neither exit is faster than
    the other — so the bounce that picks a side is the last thing that
    happens, and it happens on camera.

    Neither exit is a dead end, and that is geometry rather than luck: the
    only thing the arms and the wedge reach down to is `throat`, which is
    h * 0.085 + 110 = 192 px on a 960 px frame, and the finish line is at
    110. Below the wedge's base there is nothing but the 82 px of open frame
    both exits empty into, so a marble through either side is past the line.
    """
    room = marble_room(w)
    # Centre to centre, so both segment radii come out of it: two walls
    # `style.thickness / 2` thick leave `gap - style.thickness` clear, and
    # what has to clear a marble is the clear width. 0.175 w is 94 px on a
    # 540 px frame, 80 px clear against a 72 px marble_room and a 57 px
    # marble — the same clearance the throat ships with.
    gap = max(w * rng.uniform(*TWIN_GAP), room + style.thickness)
    half = w * TWIN_HALF
    centre = w * rng.uniform(*TWIN_CENTRE)
    _arms(space, w, style, throat, mouth, centre, half + gap)
    cap, crown = w * TWIN_CAP, throat + h * TWIN_RISE
    tilt = rng.choice([-1, 1])
    cap_a = (centre - cap, crown + tilt * cap * TWIN_TILT)
    cap_b = (centre + cap, crown - tilt * cap * TWIN_TILT)
    base_a, base_b = (centre - half, throat), (centre + half, throat)
    # Solid, not three thin edges: the gauntlet's wall wedges were edges
    # first and a pinched marble tunnelled inside one. The flanks come out at
    # a slope of 1.8-2.3, four times the 0.4 a marble is known to rest on.
    poly = pymunk.Poly(space.static_body, [cap_a, cap_b, base_b, base_a])
    poly.elasticity, poly.friction = 0.46, 0.30
    space.add(poly)
    # Drawn as the gate it is part of, so both renderers light it up and pulse
    # it when a marble crosses without knowing a twin finish exists.
    style.gates += [(cap_a, cap_b), (cap_a, base_a), (cap_b, base_b), (base_a, base_b)]
