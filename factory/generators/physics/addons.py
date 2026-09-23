"""What is added to a stage after its own builder has run.

The spinning bars some hand-built stages take, and the throat in the run-in
to the line. Both read the registry to decide whether this stage wants them.
"""

from __future__ import annotations

import random

import pymunk

from ..stagekit import _wall as wall, _peg as peg, _spinner as spinner
from .model import Style
from .registry import GATE_STAGES, SPINNER_ROWS, SPINNER_STAGES, STAGE_BY_ID

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
    if style.stage not in GATE_STAGES or rng.random() > FINISH_GATE_CHANCE:
        return
    throat = h * GATE_HEIGHT + 110.0
    spec = STAGE_BY_ID.get(style.stage)
    composed = spec is not None and spec.composed
    # Composed stages run at low gravity, where the hand-built arms (slope
    # 0.34) are barely downhill: marbles sat on them for the last eight
    # seconds of a clip. Their arms are steeper.
    mouth = throat + h * (GATE_RISE_COMPOSED if composed else 0.11)
    centre = w * rng.uniform(0.42, 0.58)
    # A composed stage gets a wider throat. At 0.17-0.21 w two marbles can
    # arch across it; stage QA found 27 of switchback's 28 stuck marbles
    # jostling there, and it is where bumpers parks its marbles too. The
    # hand-built stages keep theirs so their seeds replay unchanged.
    gap = w * rng.uniform(*(GATE_GAP_COMPOSED if composed else GATE_GAP))
    for side in (-1, 1):
        a = (w / 2 + side * w * 0.62, mouth)  # past the wall, so nothing goes round
        b = (centre + side * gap / 2, throat)
        wall(space, a, b, thickness=style.thickness / 2)
        style.gates.append((a, b))
