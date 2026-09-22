"""Physics sandbox generator — the first module in the slot.

Two variants, both fully determined by the seed:

  marble_race  four marbles race a zigzag stage, first to the bottom wins
  funnel_drop  a stream of small balls pours through a funnel

Impacts are detected from per-frame velocity changes rather than pymunk's
collision callbacks, because the callback API moved between pymunk 6 and 7 and
this only needs to know that something hit something hard.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

import pymunk
from PIL import Image, ImageDraw

from .. import audio, render, settings, themes
from . import stagekit
from .base import GeneratedClip, register
from .stagekit import _peg, _rocker, _spinner, _wall  # noqa: F401  (re-exported: tests and older code import them from here)

SUBSTEPS = 4
# Gravity is a dial, not a physical constant. The race runs slowly on purpose:
# at earth-like gravity the marbles finish a 960px stage in under three
# seconds, which is too short to publish and too fast to be pleasant.
RACE_GRAVITY = -600.0
FUNNEL_GRAVITY = -260.0
IMPACT_DV = 22.0  # velocity change that counts as a hit, in sim px/s
MAX_IMPACTS_PER_FRAME = 2  # 54 balls landing at once is a wash, not a sound
STALL_SPEED = 12.0  # below this, in sim px/s, nothing is moving any more
MAX_ATTEMPTS = 5  # a stalled race is retried on a derived seed, not abandoned
PACE_SLOWER, PACE_QUICKER = 0.72, 1.18  # gravity factors the retry loop leans by
POST_WIN_S = 0.8  # how long the race keeps running after the runner-up crosses
# The longest it waits for a runner-up after the winner. Cutting 1.3 s after
# the winner left three of four viewers — the ones who backed another marble —
# with no result at all, and QC rejected the clip as a runaway. The pay-off
# for a bet is seeing your marble arrive, even second.
POST_WIN_MAX_S = 2.8
CLOSE_RACE_S = 1.0  # a runner-up inside this gets the margin on screen
FINAL_CAPTION = "FINAL · RUN IT BACK"  # what the second round opens on: a rematch, no arithmetic



class _Stalled(RuntimeError):
    """The simulation came to rest before anything interesting happened."""


RACE_COLORS = [
    ("red", (232, 76, 74)),
    ("blue", (55, 138, 221)),
    ("amber", (239, 159, 39)),
    ("green", (151, 196, 89)),
    ("violet", (150, 122, 224)),
]
BACKGROUND = (18, 18, 26)
STRUCTURE = (58, 58, 74)

# Backdrops, each (background, structure). Two independent judges — the
# perceptual hash and an agent looking at four frames — both called the old
# single-palette race template-like, and both were right: every seed differed
# only in ramp slope and finishing order, neither of which shows in a still.
# These change what a viewer sees before anything moves.
PALETTES = [
    ((18, 18, 26), (58, 58, 74)),
    ((22, 24, 29), (65, 71, 79)),
    ((23, 18, 28), (67, 58, 77)),
    ((16, 26, 22), (52, 71, 63)),
    ((14, 17, 24), (51, 60, 74)),
    ((26, 20, 17), (74, 60, 50)),
]


# Stages: the shape of the descent. Each is a different picture to the
# perceptual hash, which is what a variant's capacity is made of, and a
# different question to the viewer. Weights are how often a random seed lands
# on each; a task can name one.
# A fourth stage, wedges (chevrons staggered like pegs), was built and cut:
# marbles balanced on an apex, wedged between an arm and the next row's wall
# lip, or sat in a wall corner — three traps, and fixing one opened another.
# Measured 7 finishes in 24 at best. The three below each finish 19 of 24
# inside the QC window with no seed stuck.
# Weights lean toward the stages that measured dramatic. The cascade is the
# outlier and it is honest to say so: 1 lead change, the half-way leader
# wins almost every time, and the eventual winner has been last at some
# point in only 6% of runs. Marbles pick a side at the first peak and mostly
# keep it. It still ships, at a low weight, because it looks unlike anything
# else on the channel — but it wants redesigning, not reweighting.
# Pace is gravity, not geometry: each stage was measured over 24 seeds and
# its gravity set so the median finish lands mid-window (see README).
# Weights, gravity, nouns and blurbs now live on each Stage in STAGE_SPECS.
# Which stages get rotating bars, and how many. Measured: on the zigzag a bar
# knocked marbles back up the ramp until 10 seeds in 24 never finished; among
# pegs it reads as a glitch. In an open field it is one more thing to bounce
# off. The gauntlet is nothing but bars.
# Stages whose builder places its own turning bars (the pinwheel's two
# crossed arms) say so with Stage.wheel, so _add_spinners leaves them alone
# and the tests know how many to expect.
ROCK_AMPLITUDE = 0.42  # radians, either way
# Fastest a marble may move, in sim px/s. Free fall down the whole frame
# reaches about 1600; anything past this came from a kinematic bar pinching
# a marble against a wall, which is not a hit, it is a glitch.
MAX_SPEED = 1900.0
TIP_GAP = 0.15  # of the width between the tips of neighbouring sieve bars: past the biggest marble, with air



@dataclass
class _Style:
    """What the clip looks like, as opposed to how it behaves."""

    background: tuple[int, int, int] = BACKGROUND
    structure: tuple[int, int, int] = STRUCTURE
    thickness: int = 12
    circles: list[tuple[float, float, float]] = field(default_factory=list)  # pegs, bumpers
    stage: str = "zigzag"
    theme: str = "default"
    decoration: str = "none"
    caption: tuple[int, int, int] = (255, 255, 255)
    seed: int = 0
    spinners: list[tuple[float, float, float, float, float]] = field(default_factory=list)  # x, y, half-length, rad/s, phase
    gates: list[tuple[tuple[float, float], tuple[float, float]]] = field(default_factory=list)  # the run-in throat
    rockers: list[tuple[float, float, float, float, float]] = field(default_factory=list)  # x, y, half, rad/s, phase
    drums: list[tuple[float, float, float, float]] = field(default_factory=list)  # x, y, r, rad/s
    kinematics: list = field(default_factory=list)  # (kind, body, params) driven per frame
    lane: list[tuple[tuple[float, float], tuple[float, float]]] = field(default_factory=list)  # the gauntlet's two verticals
    lane_wedges: list[tuple[tuple[float, float], tuple[float, float]]] = field(default_factory=list)  # gauntlet wall wedges beside each bar
    belts: list[tuple[tuple[float, float], tuple[float, float], float]] = field(default_factory=list)  # a, b, px/s along a→b


@dataclass
class _Ball:
    body: pymunk.Body
    radius: float
    color: tuple[int, int, int]
    name: str


def _ball(space: pymunk.Space, pos, radius, color, name, friction=0.22) -> _Ball:
    # Friction is deliberately low. Chipmunk multiplies the two coefficients, and
    # anything near realistic lets a marble come to rest perched on the rounded
    # end cap of a ramp — four of them then stack behind it and the clip is dead
    # in the water at four seconds. Low friction means they slide off instead.
    mass = 1.0 + radius / 40.0
    body = pymunk.Body(mass, pymunk.moment_for_circle(mass, 0, radius))
    body.position = pos
    shape = pymunk.Circle(body, radius)
    shape.elasticity = 0.52
    shape.friction = friction
    space.add(body, shape)
    return _Ball(body=body, radius=radius, color=color, name=name)


def _seconds(value: float) -> str:
    """0.04 must not read as 0.0: a photo finish is the best thing a race can do."""
    return f"{value:.2f} seconds" if value < 0.1 else f"{value:.1f} seconds"


def _pick(rng: random.Random, weights: dict[str, float]) -> str:
    total = sum(weights.values())
    roll = rng.uniform(0, total)
    for name, weight in weights.items():
        roll -= weight
        if roll <= 0:
            return name
    return next(iter(weights))


def _stage_zigzag(space, w, h, rng, style):
    """Zigzag ramps steep enough that the marbles never come to rest.

    A shallow ramp looks fine in a screenshot and stalls in the solver — at a
    slope of 0.15 the marbles stop dead after four seconds, so the slope is held
    near 0.4 whatever else changes. Ramp count and span move together: span is
    derived from the slope, so more ramps means shorter ones and the total path
    length — and the clip's duration — stays where QC wants it.
    """
    # Five was in this list until a forced test stalled 12 times out of 12.
    ramps = rng.choice([6, 7, 8, 9])
    slope = rng.uniform(0.37, 0.44)
    top, bottom = h - 80.0, 40.0
    step = (top - bottom) / ramps
    span = min(step / slope, w - 90.0)
    mirrored = rng.random() < 0.5
    segments = []
    for i in range(ramps):
        y = top - i * step
        starts_left = (i % 2 == 0) != mirrored
        a, b = ((26.0, y), (26.0 + span, y - step)) if starts_left else ((w - 26.0, y), (w - 26.0 - span, y - step))
        _wall(space, a, b, thickness=style.thickness / 2)
        segments.append((a, b))
    runway = span * 0.62
    lanes = lambda count: [(45.0 + i * (runway / max(count - 1, 1))) if not mirrored else w - (45.0 + i * (runway / max(count - 1, 1))) for i in range(count)]
    return segments, runway, lanes


def _stage_pegboard(space, w, h, rng, style):
    """A Galton board: rows of pegs, offset row to row, nothing to rest on.

    Nothing here can stall — a peg is a point, not a ledge — so the only tuning
    is pace, done with gravity rather than geometry.
    """
    rows = rng.randint(7, 10)
    cols = rng.randint(5, 7)
    r = rng.uniform(6.5, 9.5)
    top, bottom = h * 0.80, h * 0.20
    pitch = (w - 60.0) / cols
    for i in range(rows):
        y = top - (top - bottom) * i / max(rows - 1, 1)
        offset = pitch / 2 if i % 2 else 0.0
        for j in range(cols + (0 if i % 2 else 1)):
            x = 30.0 + offset + j * pitch
            if 12 < x < w - 12:
                _peg(space, x, y, r)
                style.circles.append((x, y, r))
    return [], w * 0.6, lambda count: [w * 0.2 + (w * 0.6) * i / max(count - 1, 1) for i in range(count)]


def _stage_bumpers(space, w, h, rng, style):
    """Pinball: big elastic bumpers in a staggered lattice, two guides at the bottom.

    Dense enough that no marble falls straight through; the first version had
    eight bumpers and every marble found the gap.
    """
    rows = rng.randint(6, 8)
    cols = 4
    top, bottom = h * 0.80, h * 0.26
    pitch = (w - 40.0) / cols
    for i in range(rows):
        y = top - (top - bottom) * i / max(rows - 1, 1)
        offset = pitch / 2 if i % 2 else 0.0
        for j in range(cols + (0 if i % 2 else 1)):
            x = 20.0 + offset + j * pitch + rng.uniform(-8, 8)
            if 18 < x < w - 18:
                r = rng.uniform(13.0, 19.0)
                _peg(space, x, y + rng.uniform(-6, 6), r, elasticity=0.9)
                style.circles.append((x, y, r))
    segments = [((26.0, h * 0.22), (w * 0.40, h * 0.10)), ((w - 26.0, h * 0.22), (w * 0.60, h * 0.10))]
    for a, b in segments:
        _wall(space, a, b, thickness=style.thickness / 2)
    return segments, w * 0.6, lambda count: [w * 0.2 + (w * 0.6) * i / max(count - 1, 1) for i in range(count)]


def _stage_funnels(space, w, h, rng, style):
    """Three or four funnels in series, throats offset left and right.

    Each funnel is two ramps meeting at a gap; the marbles converge, jostle for
    the throat, and spill out in a new order. The throat is measured in
    marble radii, because an arch of marbles across a narrow throat is the one
    thing that stalls a funnel: below about three radii it happens.
    """
    funnels = rng.choice([3, 4])
    top, bottom = h * 0.82, h * 0.16
    step = (top - bottom) / funnels
    segments = []
    for i in range(funnels):
        y_top = top - i * step
        y_throat = y_top - step * 0.62
        cx = w * rng.choice([0.34, 0.5, 0.66]) if i else w * 0.5
        gap = w * rng.uniform(0.17, 0.21)  # about 3.5-4 radii of the largest marble
        left = ((14.0, y_top), (cx - gap / 2, y_throat))
        right = ((w - 14.0, y_top), (cx + gap / 2, y_throat))
        for a, b in (left, right):
            _wall(space, a, b, thickness=style.thickness / 2)
            segments.append((a, b))
    return segments, w * 0.7, lambda count: [w * 0.15 + (w * 0.7) * i / max(count - 1, 1) for i in range(count)]


def _stage_gauntlet(space, w, h, rng, style):
    """A lane that narrows to two thirds of the frame with nothing in it but
    spinning bars, stacked. The bars are added by _add_spinners; here only the
    lane, so a marble knocked sideways comes back to the bars instead of
    dropping past them along the wall.
    """
    inset = w * rng.uniform(0.12, 0.17)
    segments = [((6.0, h * 0.86), (inset, h * 0.74)), ((w - 6.0, h * 0.86), (w - inset, h * 0.74)),
                ((inset, h * 0.74), (inset, h * 0.12)), ((w - inset, h * 0.74), (w - inset, h * 0.12))]
    for a, b in segments:
        _wall(space, a, b, thickness=style.thickness / 2)
    style.lane = segments[2:]
    # A few pegs between the bars, alternating sides, so a marble the bars
    # miss is still slowed.
    # Centre only: the pegs that sat at 0.28/0.72 of the lane were under the
    # bar tips, and a marble wedged between peg and tip stayed there.
    for frac in (0.16, 0.25, 0.35, 0.45, 0.55, 0.65):
        x = inset + (w - 2 * inset) * 0.5 + rng.uniform(-12, 12)
        r = rng.uniform(9.0, 12.0)
        _peg(space, x, h * frac, r, elasticity=0.75)
        style.circles.append((x, h * frac, r))
    lane = w - 2 * inset
    return segments, lane * 0.8, lambda count: [inset + lane * 0.1 + lane * 0.8 * i / max(count - 1, 1) for i in range(count)]


def _stage_cascade(space, w, h, rng, style):
    """Chutes that split and rejoin: a row of ramps meeting in the middle (a
    V, one gap), then a row parting from the middle (a peak, two gaps), and
    so on down. A marble picks a side at every peak and meets the others
    again at every V, so the order keeps changing. The peak is a short flat
    cap, not a point, so nothing balances on it.
    """
    rows = rng.choice([5, 6])
    top, bottom = h * 0.84, h * 0.14
    step = (top - bottom) / rows
    drop = step * 0.55
    gap = w * rng.uniform(0.16, 0.20)
    segments = []
    for i in range(rows):
        y = top - i * step
        if i % 2 == 0:  # V: walls in, gap in the middle
            pairs = [((14.0, y), (w / 2 - gap / 2, y - drop)), ((w - 14.0, y), (w / 2 + gap / 2, y - drop))]
        else:  # peak: from the middle out, a whole gap left at each wall
            # The cap is a short ramp, not a shelf: a flat cap is a ledge a
            # marble rests on, a point is an apex it balances on (measured,
            # both). Tilted, it sheds whatever lands on it.
            cap = w * 0.06
            tilt = 1 if rng.random() < 0.5 else -1
            cap_a, cap_b = (w / 2 - cap, y + tilt * cap * 0.4), (w / 2 + cap, y - tilt * cap * 0.4)
            pairs = [(cap_a, (gap + 14.0, y - drop)), (cap_b, (w - gap - 14.0, y - drop)), (cap_a, cap_b)]
        for a, b in pairs:
            _wall(space, a, b, thickness=style.thickness / 2)
            segments.append((a, b))
    return segments, w * 0.7, lambda count: [w * 0.15 + (w * 0.7) * i / max(count - 1, 1) for i in range(count)]


def _stage_pinwheel(space, w, h, rng, style):
    """One big wheel with four arms in the middle of the frame, and a ring of
    pegs around it. The wheel is what the eye lands on; it sweeps a marble
    aside, holds another, and the pegs below sort out the difference."""
    cx, cy = w / 2 + rng.uniform(-w * 0.06, w * 0.06), h * rng.uniform(0.50, 0.58)
    half = w * rng.uniform(0.26, 0.32)
    omega = rng.choice([-1, 1]) * rng.uniform(0.9, 1.4)
    phase = rng.uniform(0, 3.14)
    for extra in (0.0, math.pi / 2):
        _spinner(space, cx, cy, half, omega, phase + extra, style.thickness / 2)
        style.spinners.append((cx, cy, half, omega, phase + extra))
    # Pegs above and below the wheel, sparse, never inside its sweep.
    r = rng.uniform(7.0, 10.0)
    for y_frac in (0.84, 0.78, 0.72, 0.66, 0.40, 0.34, 0.28, 0.22, 0.16):
        cols = 5 if int(y_frac * 100) % 4 == 0 else 6
        for j in range(cols):
            x = 30.0 + (w - 60.0) * (j + (0.5 if cols == 4 else 0)) / max(cols - (0 if cols == 4 else 1), 1)
            y = h * y_frac
            if math.hypot(x - cx, y - cy) > half + 40:
                _peg(space, x, y, r)
                style.circles.append((x, y, r))
    return [], w * 0.6, lambda count: [w * 0.2 + (w * 0.6) * i / max(count - 1, 1) for i in range(count)]


def _stage_sieve(space, w, h, rng, style):
    """Rows of short bars with gaps between them, each bar tilted so nothing
    rests on it. Offsets alternate row to row, so a marble that drops
    through one gap lands on a bar in the next.

    The pocket, seen rather than guessed: a marble wedges between the low
    tip of one bar and the high tip of the next, and with four bars a row
    the tips were 67px apart against a 60px marble. So the gap between tips
    is what is sized, and the bar takes what is left of the pitch. Two other
    fixes were tried first and measured worse: sloping the outer bars inward
    made a V with the next bar in (11 of 20 finished), and leaving out the
    bars near the walls opened a free-fall channel that finished under the
    QC floor (7 of 24).
    """
    # Four to six rows, not six to eight: at eight the rows were 82px apart
    # and a 60px marble wedged between a bar and the dipped end of the bar
    # in the row above, at the walls where those ends meet (46% of marbles
    # ended the clip there, measured).
    rows = rng.randint(3, 4)
    per_row = rng.choice([3, 4])
    # The bottom row stays above the run-in throat, for the same reason the
    # drums do: at 0.22h the last stuck marbles were pinned between a bar
    # and a throat arm. Three or four rows over this height keeps the rows
    # at least 134px apart, past the wedge a 60px marble finds at 82px.
    top, bottom = h * 0.84, h * 0.42
    pitch = w / per_row
    segments = []
    for i in range(rows):
        y = top - (top - bottom) * i / max(rows - 1, 1)
        offset = pitch / 2 if i % 2 else 0.0
        direction = 1 if i % 2 else -1  # every bar in a row slopes the same way
        for j in range(per_row + 1):
            cx = offset + j * pitch
            span = pitch - max(pitch * rng.uniform(0.50, 0.62), TIP_GAP * w)
            a_x, b_x = cx - span / 2, cx + span / 2
            if b_x < 6 or a_x > w - 6:
                continue
            # A tip that stops short of a wall needs the same clearance as a
            # tip facing another tip: the last stuck marble, r=21, sat at
            # x=509 against a tip that ended 41px from the wall.
            if a_x >= 6 and a_x < TIP_GAP * w:
                a_x = TIP_GAP * w
            if b_x <= w - 6 and b_x > w - TIP_GAP * w:
                b_x = w - TIP_GAP * w
            if b_x - a_x < 24:
                continue
            span = b_x - a_x
            # A bar that meets a wall has its wall end high, whichever way
            # the row slopes: sloping down into the wall makes a corner a
            # marble rolls into and stays in (seen at x=30 and x=506).
            direction_here = 1 if a_x < 6 else (-1 if b_x > w - 6 else direction)
            tilt = direction_here * rng.uniform(0.42, 0.55) * span
            a, b = (a_x, y + tilt / 2), (b_x, y - tilt / 2)
            _wall(space, a, b, thickness=style.thickness / 2, friction=0.12)
            segments.append((a, b))
    return segments, w * 0.6, lambda count: [w * 0.2 + (w * 0.6) * i / max(count - 1, 1) for i in range(count)]


def _stage_pachinko(space, w, h, rng, style):
    """Pegs on concentric arcs around a central bumper: a marble is thrown
    outward by the bumper and then filtered back in by the arcs."""
    cx, cy = w / 2, h * rng.uniform(0.60, 0.68)
    big = w * rng.uniform(0.07, 0.09)
    _peg(space, cx, cy, big, elasticity=0.85)
    style.circles.append((cx, cy, big))
    r = rng.uniform(6.5, 9.0)
    for ring, radius in enumerate([w * 0.22, w * 0.36, w * 0.50, w * 0.64]):
        n = 5 + ring * 3
        for k in range(n):
            ang = math.pi + math.pi * (k + 0.5) / n  # the lower half only, an arc that opens downward
            x, y = cx + radius * math.cos(ang), cy + radius * math.sin(ang)
            if 14 < x < w - 14 and 130 < y < h * 0.9:
                _peg(space, x, y, r)
                style.circles.append((x, y, r))
    return [], w * 0.6, lambda count: [w * 0.2 + (w * 0.6) * i / max(count - 1, 1) for i in range(count)]


def _stage_rockers(space, w, h, rng, style):
    """Planks that rock on a pivot, tipping one way and then the other, in
    staggered rows. A marble that lands on a plank rides it down and is
    thrown off the low end — which end that is depends on when it arrived."""
    rows = rng.randint(4, 5)
    top, bottom = h * 0.80, h * 0.26
    clear = w * 0.12  # a plank tip never comes closer to a wall than this: a marble and air
    segments = []
    for i in range(rows):
        y = top - (top - bottom) * i / max(rows - 1, 1)
        count = 2 if i % 2 == 0 else 3
        for j in range(count):
            x = w * (j + 0.5) / count + (w * 0.08 if i % 2 else 0) * rng.choice([-1, 1]) * 0.3
            half = w * rng.uniform(0.11, 0.15)
            # Eight seeds were measured with a marble pinned at x = 0.06 w,
            # jittering between a plank tip and the wall for the whole clip.
            half = min(half, x - clear, w - clear - x)
            omega = rng.uniform(1.0, 1.8)
            phase = rng.uniform(0, 6.283)
            body = _rocker(space, x, y, half, omega, phase, style.thickness / 2)
            style.rockers.append((x, y, half, omega, phase))
            style.kinematics.append(("rocker", body, (omega, phase)))
            # The hub is a bump, not just a drawing: a marble that lands on
            # the pivot of a symmetric rocker sits there rocking with it.
            _peg(space, x, y, style.thickness * 0.9, elasticity=0.5)
        # Deflectors on both walls under each row: whatever a plank throws
        # at the wall is turned back to the middle instead of sliding down it.
        if i < rows - 1:
            yd = y - (top - bottom) / max(rows - 1, 1) * 0.55
            for a, b in (((6.0, yd + w * 0.07), (w * 0.11, yd)), ((w - 6.0, yd + w * 0.07), (w - w * 0.11, yd))):
                _wall(space, a, b, thickness=style.thickness / 2)
                segments.append((a, b))
    return segments, w * 0.6, lambda count: [w * 0.2 + (w * 0.6) * i / max(count - 1, 1) for i in range(count)]


def _stage_drums(space, w, h, rng, style):
    """Large spinning drums, staggered. A marble that lands on one is carried
    round by friction and let go on the far side, so the drum's direction
    decides which way it heads next.

    Every drum is sized from the gaps around it — to its neighbours in the
    row, to the walls, and to the rows above and below — each of which has
    to clear the biggest marble with air. Three versions were measured
    before this one: drums turning toward each other made a pinch; a
    3-drum row's outer drum sat 31px from the wall; and rows 160px apart
    with 110px drums left 50px between rows, less than a marble, where 68%
    of them ended the clip. Three-drum rows come out small, two-drum rows
    big, and every drum in a row turns the same way.
    """
    rows = rng.randint(4, 5)
    # The bottom row stays above the run-in throat: at 0.24h the lowest
    # drums overlapped the throat's mouth and pinned marbles between a drum
    # and an arm — every stuck marble in the diagnostic sat at that height.
    top, bottom = h * 0.84, h * 0.44
    row_gap = (top - bottom) / max(rows - 1, 1)
    for i in range(rows):
        y = top - (top - bottom) * i / max(rows - 1, 1)
        count = 2 if i % 2 == 0 else 3
        r = min(w * rng.uniform(0.06, 0.11), (w / (count + 1) - w * 0.13) / 2, (row_gap - w * 0.14) / 2)
        direction = rng.choice([-1, 1])
        for j in range(count):
            x = w * (j + 1) / (count + 1)
            omega = direction * rng.uniform(1.6, 2.6)
            body = pymunk.Body(body_type=pymunk.Body.KINEMATIC)
            body.position = (x, y)
            body.angular_velocity = omega
            shape = pymunk.Circle(body, r)
            shape.elasticity = 0.25
            shape.friction = 0.9
            space.add(body, shape)
            style.drums.append((x, y, r, omega))
    return [], w * 0.6, lambda count: [w * 0.2 + (w * 0.6) * i / max(count - 1, 1) for i in range(count)]


@dataclass(frozen=True)
class Stage:
    """Everything the factory knows about one stage, in one place.

    Before this, a stage lived in seven dictionaries and a describe table,
    and adding one meant editing all of them and hoping a test caught the
    one you missed. Now a stage is one entry; the old names below are
    derived from the list and stay only because other code reads them.

    weight   share of random picks among live stages. 0 = trial: a trial
             stage renders when a task names it, and is never picked at
             random. `factory stage-qa` is what promotes a stage.
    gravity  pace; tuned so the median finish lands mid-window.
    parts    for a composed stage, the sections it stacks (see stagekit).
    """

    id: str
    build: Any
    gravity: float
    noun: str
    blurb: str
    describe: Any
    weight: float = 0.0
    spinners: tuple[int, int] | None = None
    spinner_rows: tuple[float, ...] = ()
    wheel: int = 0
    gate: bool = False
    parts: tuple = ()

    @property
    def live(self) -> bool:
        return self.weight > 0

    @property
    def composed(self) -> bool:
        return bool(self.parts)


def _obstacles(style, segments) -> int:
    return len(style.circles) or len(segments)


def _composed(id_, parts, *, gravity, noun, blurb, weight=0.0, gate=False):
    """A stage stacked from stagekit sections. With the finish throat the
    stack stops above the throat's mouth (0.31 h) with a marble's room to
    spare — the drums and sieve stages learned what a section overlapping
    the throat does."""
    build = stagekit.compose(list(parts), bottom_frac=0.36 if gate else 0.20)
    return Stage(
        id=id_, build=build, gravity=gravity, noun=noun, blurb=blurb,
        describe=lambda style, segments, _p=tuple(parts): stagekit.describe_parts(_p),
        weight=weight, gate=gate, parts=tuple(parts),
    )


STAGE_SPECS: list[Stage] = [
    Stage("zigzag", _stage_zigzag, -600.0, "ramps", "ramps — fast, the classic",
          lambda s, g: f"a {_obstacles(s, g)}-ramp zigzag stage", weight=0.16),
    Stage("pegboard", _stage_pegboard, -110.0, "pegs", "pegs — a slow rattle down a Galton board",
          lambda s, g: f"a pegboard of {_obstacles(s, g)} pegs", weight=0.12),
    Stage("bumpers", _stage_bumpers, -95.0, "bumpers", "bumpers and spinning bars — the busiest frame",
          lambda s, g: f"a field of {_obstacles(s, g)} bumpers", weight=0.14,
          spinners=(3, 4), spinner_rows=(0.26, 0.40, 0.54, 0.68), gate=True),
    Stage("funnels", _stage_funnels, -45.0, "funnels", "stacked funnels — every throat is a bottleneck",
          lambda s, g: f"{_obstacles(s, g) // 2} stacked funnels", weight=0.09),
    # No bar at 0.70, where the funnel dumps the field onto it: it juggled
    # the field for a whole clip.
    Stage("gauntlet", _stage_gauntlet, -55.0, "spinners", "a lane of spinning bars — nothing else in the way",
          lambda s, g: "a narrow gauntlet", weight=0.09,
          spinners=(4, 5), spinner_rows=(0.20, 0.30, 0.40, 0.50, 0.60), gate=True),
    Stage("cascade", _stage_cascade, -200.0, "chutes", "chutes that split and rejoin — the marbles keep swapping sides",
          lambda s, g: f"a cascade of {_obstacles(s, g)} chutes", weight=0.03),
    Stage("pinwheel", _stage_pinwheel, -40.0, "arms", "one big four-armed wheel in the middle, pegs around it",
          lambda s, g: f"a four-armed pinwheel among {_obstacles(s, g)} pegs", weight=0.09, wheel=2),
    Stage("sieve", _stage_sieve, -60.0, "bars", "rows of short tilted bars with gaps — a sieve the marbles fall through",
          lambda s, g: f"a sieve of {_obstacles(s, g)} tilted bars", weight=0.09, gate=True),
    Stage("pachinko", _stage_pachinko, -70.0, "pegs", "pegs on arcs around a central bumper, like a pachinko board",
          lambda s, g: f"a pachinko board of {_obstacles(s, g)} pegs", weight=0.07),
    Stage("rockers", _stage_rockers, -150.0, "planks", "planks that rock on a pivot — tip one way, then the other",
          lambda s, g: f"{len(s.rockers)} rocking planks", weight=0.06),
    Stage("drums", _stage_drums, -40.0, "drums", "big spinning drums that carry a marble sideways before it drops",
          lambda s, g: f"{len(s.drums)} spinning drums", weight=0.06, gate=True),
    # --- composed from stagekit sections. Trial (weight 0) until stage-qa passes them.
    # COMPOSED-STAGES-BEGIN
    # Gravity from `factory stage-qa --calibrate`; weight 0.05 each once the
    # stage passed every gate on 48 fresh seeds (2026-09-23, docs/06). arcade
    # stays trial: its lead changed 1.1 times a race against a gate of 1.5.
    _composed("arcade", [("bumpers", 1.1), ("spinners", 1.2), ("pegs", 1.0)], gravity=-30.0, noun="bumpers",
              blurb="bumpers, then a row of spinning bars, then pegs", gate=True),
    _composed("plinko", [("pegs", 1.0), ("wheel", 1.6), ("pegs", 1.0)], gravity=-31.0, noun="pegs",
              blurb="pegs, a big four-armed wheel, then more pegs", gate=True, weight=0.05),
    _composed("switchback", [("ramps", 1.2), ("belts", 1.0), ("ramps", 1.0)], gravity=-60.0, noun="ramps",
              blurb="zigzag ramps with a band of conveyor belts in the middle", gate=True, weight=0.05),
    _composed("seesaw", [("rockers", 1.2), ("pegs", 1.0), ("funnel", 1.0)], gravity=-30.0, noun="planks",
              blurb="rocking planks, then pegs, then a funnel", weight=0.05),
    _composed("rapids", [("ramps", 0.9), ("chutes", 1.5), ("bumpers", 1.0)], gravity=-30.0, noun="chutes",
              blurb="ramps, split-and-rejoin chutes, then bumpers", weight=0.05),
    _composed("carnival", [("pegs", 0.7), ("wheel", 1.4), ("spinners", 1.3), ("pegs", 0.7)], gravity=-30.0, noun="arms",
              blurb="pegs, a big wheel, a row of spinning bars, then pegs", gate=True, weight=0.05),
    _composed("quarry", [("sieve", 1.4), ("funnel", 1.0), ("pegs", 1.0)], gravity=-30.0, noun="bars",
              blurb="a sieve, a funnel, then pegs", weight=0.05),
    _composed("tumble", [("funnel", 1.0), ("drums", 1.4), ("pegs", 1.0)], gravity=-30.0, noun="drums",
              blurb="a funnel dropping the field onto spinning drums, then pegs", weight=0.05),
    _composed("labyrinth", [("ramps", 1.0), ("sieve", 1.3), ("chutes", 1.5)], gravity=-30.0, noun="bars",
              blurb="ramps, a sieve, then split-and-rejoin chutes", weight=0.05),
    _composed("orchard", [("pegs", 1.0), ("rockers", 1.3), ("pegs", 1.0)], gravity=-30.0, noun="planks",
              blurb="pegs, rocking planks, then more pegs", gate=True, weight=0.05),
    _composed("pinball", [("bumpers", 1.1), ("rockers", 1.2), ("funnel", 0.9)], gravity=-30.0, noun="bumpers",
              blurb="bumpers, rocking planks, then a funnel", weight=0.05),
    _composed("gallery", [("pegs", 1.0), ("sieve", 1.3), ("funnel", 1.0)], gravity=-44.0, noun="pegs",
              blurb="pegs, a sieve of tilted bars, then a funnel", weight=0.05),
    _composed("spillway", [("chutes", 1.5), ("pegs", 1.0), ("funnel", 0.9)], gravity=-30.0, noun="chutes",
              blurb="split-and-rejoin chutes, pegs, then a funnel", weight=0.05),
    # COMPOSED-STAGES-END
]

STAGE_BY_ID: dict[str, Stage] = {st.id: st for st in STAGE_SPECS}
_LIVE_TOTAL = sum(st.weight for st in STAGE_SPECS if st.live)
# Derived names, kept because web, tasks and the tests read them.
STAGES = {st.id: (st.weight / _LIVE_TOTAL if st.live else 0.0) for st in STAGE_SPECS}
LIVE_STAGES = [st.id for st in STAGE_SPECS if st.live]
STAGE_GRAVITY = {st.id: st.gravity for st in STAGE_SPECS}
STAGE_NOUN = {st.id: st.noun for st in STAGE_SPECS}
STAGE_BLURB = {st.id: st.blurb for st in STAGE_SPECS}
SPINNER_STAGES = {st.id: st.spinners for st in STAGE_SPECS if st.spinners}
SPINNER_ROWS = {st.id: st.spinner_rows for st in STAGE_SPECS if st.spinners}
WHEEL_STAGES = {st.id: st.wheel for st in STAGE_SPECS if st.wheel}
GATE_STAGES = tuple(st.id for st in STAGE_SPECS if st.gate)
_STAGES = {st.id: st.build for st in STAGE_SPECS}


def parse_hex(value: str) -> tuple[int, int, int]:
    """'#1a2b3c' -> (26, 43, 60). Loud about anything else."""
    text = str(value).strip().lstrip("#")
    if len(text) != 6 or any(c not in "0123456789abcdefABCDEF" for c in text):
        raise ValueError(f"backdrop must be a hex colour like #1a2b3c, not {value!r}")
    return tuple(int(text[i : i + 2], 16) for i in (0, 2, 4))


def _structure_for(background: tuple[int, int, int]) -> tuple[int, int, int]:
    """Ramps and pegs a step lighter than a dark backdrop, darker than a light one."""
    light = sum(background) / 3 > 128
    delta = -46 if light else 42
    return tuple(max(0, min(255, c + delta)) for c in background)


# A throat in the run-in to the line. Measured over 20 seeds a stage:
# without it only 10-20% of races on most stages finished inside a second of
# each other, because whoever got clear early stayed clear.
#
# A turning bar was tried here first and made things worse (the half-way
# leader went on to win 75% of the time on the zigzag, up from 60%): a bar
# deflects whoever meets it, at random, and deflection spreads a field out.
# What brings a field together is a queue. They arrive, they wait, they
# jostle for the gap, and the order they come out in is not the order they
# went in — which is both halves of what this is for.
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


def _add_spinners(space, w, h, rng, style):
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
        _spinner(space, x, y, half, omega, phase, style.thickness / 2)
        style.spinners.append((x, y, half, omega, phase))
        side = -side


def _add_finish_gate(space, w, h, rng, style) -> None:
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
        _wall(space, a, b, thickness=style.thickness / 2)
        style.gates.append((a, b))


def _build_race(space: pymunk.Space, w: int, h: int, rng: random.Random, stage: str | None = None,
                background: str | None = None, lineup: list | None = None):
    """A stage from the registry, dressed by the active theme.

    Everything a viewer can see in a single frame is varied: which stage, the
    backdrop, how thick the structure is, how many marbles and how big. What
    stays fixed is what keeps the solver honest — slopes, throat widths, pace.
    """
    theme = themes.active()
    style = _Style()
    style.background, style.structure = rng.choice(theme.palettes)
    if background:
        # A person chose it, so it wins over the theme's palette — the theme's
        # marbles, caption colour and decoration still apply.
        style.background = parse_hex(background)
        style.structure = _structure_for(style.background)
    style.thickness = rng.randint(8, 15)
    style.theme, style.decoration, style.caption = theme.id, theme.decoration, theme.caption
    style.stage = stage or _pick(rng, {k: v for k, v in STAGES.items() if v > 0})
    if style.stage not in _STAGES:
        raise ValueError(f"no stage {style.stage!r}; have {sorted(_STAGES)}")
    space.gravity = (0.0, STAGE_GRAVITY[style.stage])

    _wall(space, (4, 0), (4, h))
    _wall(space, (w - 4, 0), (w - 4, h))
    _wall(space, (4, 6), (w - 4, 6))
    # A ceiling. The gauntlet's lane-wide gates flung marbles clean out of
    # the top of the frame (one was measured 22 frame-heights up) and the
    # clip ended with them "still racing" somewhere in the sky.
    _wall(space, (4, h - 2), (w - 4, h - 2))

    segments, runway, lanes_for = _STAGES[style.stage](space, w, h, rng, style)
    _add_spinners(space, w, h, rng, style)
    segments = list(segments) + style.lane_wedges
    _add_finish_gate(space, w, h, rng, style)

    # Identical marbles keep their starting order for the whole run, which kills
    # the only question the clip asks. Varying the radius makes them overtake,
    # and the lane order is shuffled so the seed decides who starts in front.
    base_radius = w * rng.uniform(0.036, 0.050)
    room = int(runway // (base_radius * 2.5)) + 1
    count = max(3, min(rng.choice([3, 4, 5]), room, len(theme.marbles)))

    colours = list(theme.marbles)
    rng.shuffle(colours)
    if lineup:
        # The final is run by the marbles that ran the heat, in the same colours.
        colours, count = list(lineup), len(lineup)
    lanes = lanes_for(count)
    rng.shuffle(lanes)

    balls = []
    for (name, color), x in zip(colours[:count], lanes):
        radius = base_radius * rng.uniform(*MARBLE_SPREAD)
        ball = _ball(space, (x, h - 30.0), radius, tuple(color), name)
        ball.body.velocity = (rng.uniform(-20, 20), -130.0)  # already moving on frame one
        balls.append(ball)
    return balls, segments, style


def _build_funnel(space: pymunk.Space, w: int, h: int, rng: random.Random):
    """Two funnels in series, throats measured in ball radii.

    Throat width is the one number that decides whether this variant works, and
    it is not a matter of taste. Below about five radii the balls arch across the
    opening and nothing comes through at all — measured over five seeds, a 3.4r
    throat left 54 of 54 balls sitting above it. Six radii drains every seed. The
    pour is stretched to a watchable length with gravity instead, which is a dial
    that cannot jam.
    """
    style = _Style()
    style.background, style.structure = rng.choice(PALETTES)

    _wall(space, (4, 0), (4, h))
    _wall(space, (w - 4, 0), (w - 4, h))
    _wall(space, (4, 6), (w - 4, 6))
    # A ceiling. The gauntlet's lane-wide gates flung marbles clean out of
    # the top of the frame (one was measured 22 frame-heights up) and the
    # clip ended with them "still racing" somewhere in the sky.
    _wall(space, (4, h - 2), (w - 4, h - 2))

    radius = w * 0.022
    upper_gap = radius * rng.uniform(5.6, 6.4)
    lower_gap = radius * rng.uniform(5.1, 5.9)
    segments = [
        ((16.0, h * 0.78), (w / 2 - upper_gap / 2, h * 0.46)),
        ((w - 16.0, h * 0.78), (w / 2 + upper_gap / 2, h * 0.46)),
        ((16.0, h * 0.34), (w / 2 - lower_gap / 2, h * 0.13)),
        ((w - 16.0, h * 0.34), (w / 2 + lower_gap / 2, h * 0.13)),
    ]
    for a, b in segments:
        _wall(space, a, b)

    columns = 6
    pitch = radius * 2.35
    left = w / 2 - (columns - 1) * pitch / 2
    balls = []
    for i in range(54):
        x = left + (i % columns) * pitch + rng.uniform(-2.5, 2.5)
        y = h - 60.0 - (i // columns) * radius * 2.6
        ball = _ball(space, (x, y), radius, _hsv((i * 37 % 360) / 360.0), f"ball{i}")
        ball.body.velocity = (0.0, -90.0)  # falling on frame one, not hanging
        balls.append(ball)
    return balls, segments, style


def _hsv(hue: float) -> tuple[int, int, int]:
    r, g, b = _hsv_to_rgb(hue, 0.55, 0.92)
    return (int(r * 255), int(g * 255), int(b * 255))


def _hsv_to_rgb(h: float, s: float, v: float):
    i = int(h * 6.0)
    f = h * 6.0 - i
    p, q, t = v * (1 - s), v * (1 - s * f), v * (1 - s * (1 - f))
    return [(v, t, p), (q, v, p), (p, v, t), (p, q, v), (t, p, v), (v, p, q)][i % 6]


class PhysicsSandbox:
    name = "physics"
    variants = ["marble_race", "funnel_drop"]
    ready = True
    blurb = (
        "Deterministic 2D physics. marble_race: four coloured marbles race a "
        "zigzag ramp stage, one wins. funnel_drop: dozens of small balls pour "
        "through a funnel. No prior knowledge needed, holds attention to the end."
    )

    def generate(
        self, *, seed: int, variant: str, params: dict[str, Any], work_dir: Path
    ) -> GeneratedClip:
        if variant not in self.variants:
            raise ValueError(f"{self.name}: unknown variant {variant!r}")
        cfg = settings.load().render
        out_w, out_h = int(cfg["width"]), int(cfg["height"])
        scale = float(cfg["render_scale"])
        sim_w, sim_h = int(out_w * scale), int(out_h * scale)
        fps = int(cfg["fps"])

        rounds_wanted = int(params.get("rounds", cfg.get("rounds", 1))) if variant == "marble_race" else 1
        rounds = [self._round(seed, variant, params, cfg, sim_w, sim_h, fps)]
        if rounds_wanted >= 2:
            # The final: same marbles, a different stage, a seed derived from
            # this one so the whole clip is still one number.
            heat = rounds[0]
            lineup = [(b.name, b.color) for b in heat["balls"]]
            other = [c for c in LIVE_STAGES if c != heat["style"].stage] or list(LIVE_STAGES)
            final_stage = params.get("final_stage") or random.Random(seed ^ 0x5F3759DF).choice(other)
            rounds.append(self._round(seed + 104729, variant, {**params, "stage": final_stage},
                                      cfg, sim_w, sim_h, fps, lineup=lineup))

        clip_dir = work_dir
        clip_dir.mkdir(parents=True, exist_ok=True)

        # Captions: the heat states its measured stake; the final restates the
        # structure, never a result — the viewer just saw the heat, and naming
        # its winner again is one more word that is not a stake.
        hook_text = (params.get("hook_text") or "").strip() or self._default_hook(variant, rounds[0])
        overlays = [self._overlay(variant, sim_w, sim_h, fps, text=hook_text)]
        if len(rounds) > 1:
            overlays.append(self._overlay(variant, sim_w, sim_h, fps, text=FINAL_CAPTION))

        impacts: list[audio.Impact] = []
        offset = 0.0
        for r in rounds:
            impacts += [audio.Impact(im.t + offset, im.strength, im.index, im.pan) for im in r["impacts"]]
            offset += r["duration_s"]
        duration_s = offset
        wav = audio.render_wav(impacts, duration_s, clip_dir / "audio.wav")

        def all_frames():
            for r, overlay in zip(rounds, overlays):
                yield from self._frames(r["states"], r["balls"], r["segments"], sim_w, sim_h,
                                        overlay=overlay, style=r["style"],
                                        ask=self._closing_ask(sim_w, sim_h, fps),
                                        winner_frame=r["winner_frame"], winner=r["winner"],
                                        impacts=r["impacts"], fps=fps)

        silent = render.encode_frames(
            all_frames(), out_path=clip_dir / "video.mp4",
            src_size=(sim_w, sim_h), out_size=(out_w, out_h), fps=fps,
        )
        final = render.mux(silent, wav, clip_dir / "clip.mp4")

        last = rounds[-1]
        balls, style = last["balls"], last["style"]
        if variant == "marble_race":
            names = ", ".join(b.name for b in rounds[0]["balls"])
            themed = "" if style.theme == "default" else f" Styled for {style.theme}."
            parts = []
            for i, r in enumerate(rounds):
                label = ("The heat" if i == 0 else "The final") if len(rounds) > 1 else f"{len(r['balls'])} marbles ({names}) race"
                if len(rounds) > 1:
                    label += f" runs down {self._stage_text(r)}"
                else:
                    label += f" down {self._stage_text(r)}"
                if r["winner"]:
                    gap = (f", {_seconds(r['margin_s'])} ahead of {r['runner_up']}" if r["runner_up"]
                           else f"; no other marble crosses in the next {POST_WIN_MAX_S} seconds")
                    parts.append(f"{label}. The {r['winner']} marble reaches the bottom first, at "
                                 f"{r['winner_frame'] / fps:.1f} seconds{gap}.")
                else:
                    parts.append(f"{label}; none reaches the bottom within {r['duration_s']:.1f} seconds.")
            head = f"Two rounds, same {len(rounds[0]['balls'])} marbles ({names}). " if len(rounds) > 1 else ""
            description = head + " ".join(parts) + themed
        else:
            description = (
                f"{len(balls)} small coloured balls pour through a narrow funnel throat "
                f"over {duration_s:.1f} seconds, clicking as they jam and release."
            )

        return GeneratedClip(
            video_path=final,
            duration_s=duration_s,
            description=description,
            facts={
                "variant": variant,
                "seed": seed,
                "rounds": [
                    {"stage": r["style"].stage, "winner": r["winner"], "margin_s": r["margin_s"],
                     "runner_up": r["runner_up"], "finishes": r["finish_s"], "seconds": round(r["duration_s"], 2),
                     "obstacles": len(r["style"].circles) or len(r["segments"]), "spinners": len(r["style"].spinners),
                     "gate": bool(r["style"].gates)}
                    for r in rounds
                ],
                "winner": last["winner"],
                "impacts": len(impacts),
                "objects": len(balls),
                "ramps": len(last["segments"]),
                "stage": style.stage,
                "obstacles": len(style.circles) or len(last["segments"]),
                "theme": style.theme,
                "palette": style.background,
                "backdrop": "#%02x%02x%02x" % rounds[0]["style"].background,
                "sim_attempts": sum(r["attempts"] for r in rounds),
                "finishes": last["finish_s"],
                "runner_up": last["runner_up"],
                "margin_s": last["margin_s"],
                "hook_text": hook_text,
            },
        )

    def _stage_text(self, r) -> str:
        style, segments = r["style"], r["segments"]
        obstacles = len(style.circles) or len(segments)
        base = STAGE_BY_ID[style.stage].describe(style, segments)
        if style.spinners:
            base += f" with {len(style.spinners)} spinning bar{'s' if len(style.spinners) > 1 else ''}"
        if style.gates:
            base += " and a throat in the run-in to the line"
        return base

    def _round(self, seed, variant, params, cfg, sim_w, sim_h, fps, lineup=None) -> dict:
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
                sim = self._simulate(
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
                    raise _Stalled(f"no winner in {max_frames / fps:.1f}s")
                break
            except _Stalled as exc:
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

    def _simulate(
        self, *, seed: int, variant: str, sim_w: int, sim_h: int, fps: int, max_frames: int,
        stage: str | None = None, background: str | None = None, lineup: list | None = None,
        pace: float = 1.0, min_frames: int | None = None,
    ):
        """Run the physics only. Raises _Stalled when a race goes nowhere, or
        finishes before min_frames (the QC floor, by default)."""
        rng = random.Random(seed)
        space = pymunk.Space()
        if variant == "marble_race":
            space.gravity = (0.0, RACE_GRAVITY)
            balls, segments, style = _build_race(space, sim_w, sim_h, rng, stage, background, lineup)
            space.gravity = (0.0, space.gravity.y * pace)
            style.seed = seed
            finish_y: float | None = 110.0
        else:
            space.gravity = (0.0, FUNNEL_GRAVITY)
            balls, segments, style = _build_funnel(space, sim_w, sim_h, rng)
            finish_y = None

        dt = 1.0 / (fps * SUBSTEPS)
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
            if max(b.body.velocity.length for b in balls) < STALL_SPEED:
                stalled += 1
            else:
                stalled = 0
            if stalled > fps * 1.5:
                if finish_y is None:
                    break
                raise _Stalled(f"no winner by {frame / fps:.1f}s")
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
                raise _Stalled(
                    f"finished in {len(states) / fps:.1f}s, under the {need / fps:.1f}s floor"
                )

        return states, impacts, balls, segments, winner, winner_frame, style, finishes

    def _default_hook(self, variant: str, round_: dict | None) -> str:
        """The opening caption: two or three words that make the viewer pick a
        marble. Not the result, and not the stage's spec sheet either —
        "PICK ONE · 4 SPINNERS" made a viewer read arithmetic in the one
        second they give us. The pick is the whole job: a viewer who has
        chosen a side stays to see it lose or win.

        The bank lives in config (overlay.marble_race, captions separated by
        "|"), so the operator edits it on the Settings page; one is chosen
        per seed so consecutive clips do not open on the same words.
        """
        cfg = settings.load().raw.get("overlay", {})
        bank = [c.strip() for c in str(cfg.get(variant) or "").split("|") if c.strip()]
        if not bank:
            return ""
        if variant == "marble_race" and round_ and len(bank) > 1:
            seed = getattr(round_["style"], "seed", 0) or 0
            return bank[random.Random(seed).randrange(len(bank))]
        return bank[0]

    def _closing_ask(self, sim_w: int, sim_h: int, fps: int):
        """What the clip asks for once the result is in.

        The opening caption asks the viewer to pick; this asks them to say
        what they picked, and it runs in the second the race keeps going
        after the winner crosses, where there is nothing left to give away
        and nothing left to compete with.
        """
        cfg = settings.load().raw.get("overlay", {})
        text = str(cfg.get("cta") or "").strip()
        seconds = float(cfg.get("cta_seconds", 0) or 0)
        if not text or seconds <= 0:
            return None
        from ..brand import _font

        probe = ImageDraw.Draw(Image.new("RGB", (1, 1)))
        size = int(sim_w * float(cfg.get("size", 0.072)) * 0.8)
        while True:
            font = _font(size)
            width = probe.textlength(text, font=font)
            if width <= sim_w * 0.90 or size <= 12:
                break
            size -= 2
        return text, font, (sim_w - width) / 2, sim_h * 0.30, int(seconds * fps)

    def _overlay(self, variant: str, sim_w: int, sim_h: int, fps: int, text: str | None = None):
        """Opening caption, or None. Returns (text, font, x, y, last_frame)."""
        cfg = settings.load().raw.get("overlay", {})
        if text is None:
            text = (cfg.get(variant) or "").strip()
        if not text:
            return None
        from ..brand import _font

        probe = ImageDraw.Draw(Image.new("RGB", (1, 1)))
        # Shrink until it fits: "FINAL · GREEN TOOK THE HEAT" at the race's
        # caption size ran off both edges of the frame.
        size = int(sim_w * float(cfg.get("size", 0.072)))
        while True:
            font = _font(size)
            text_width = probe.textlength(text, font=font)
            if text_width <= sim_w * 0.90 or size <= 14:
                break
            size -= 2
        # Two constraints squeeze this: the objects all start at the top of
        # frame and spend the caption's whole life up there, and Shorts covers
        # the bottom ~15% and right ~12% with its own UI. That leaves the lower
        # third but above the UI.
        return (
            text,
            font,
            (sim_w - text_width) / 2,
            sim_h * 0.70,
            int(float(cfg.get("seconds", 0)) * fps),
        )

    def _frames(
        self, states, balls, segments, sim_w, sim_h, overlay=None, style=None,
        winner_frame=None, winner=None, ask=None, impacts=None, fps=30,
    ) -> Iterator[bytes]:
        """One frame renderer or the other, by `render.engine`. Same inputs,
        same physics; pygame adds motion to every object."""
        from . import fx

        if fx.engine() == "pygame":
            yield from self._frames_pygame(states, balls, segments, sim_w, sim_h, overlay=overlay, style=style,
                                           winner_frame=winner_frame, winner=winner, ask=ask,
                                           impacts=impacts or [], fps=fps)
            return
        yield from self._frames_pil(states, balls, segments, sim_w, sim_h, overlay=overlay, style=style,
                                    winner_frame=winner_frame, winner=winner, ask=ask)

    def _frames_pygame(
        self, states, balls, segments, sim_w, sim_h, overlay=None, style=None,
        winner_frame=None, winner=None, ask=None, impacts=(), fps=30,
    ) -> Iterator[bytes]:
        """The race with the juice: every object moves in its own way.

        Marble      squash along the hit on every impact (the audio's impact
                    list drives it, so nothing is re-simulated), a fading
                    trail, a rolling highlight, a flash on a hard hit.
        Spinners,   a glow that scales with how fast they turn, so a viewer
        drums       reads the danger before a marble reaches it.
        Gates       pulse once when a marble passes the throat.
        Sparks      on hard impacts, in the marble's colour.
        Finish      the chequer flashes, the winner gets rings and a burst.
        Words       the caption slides up and settles; the ask pops in.
        """
        import pygame
        from . import fx

        fx.init()
        style = style or _Style()
        finish_line = style.stage in STAGES
        winner_index = next((i for i, b in enumerate(balls) if b.name == winner), None)
        rng = random.Random(style.seed * 17 + 3)
        by_frame: dict[int, list] = {}
        for im in impacts:
            by_frame.setdefault(int(round(im.t * fps)), []).append(im)
        anim = [fx.Ball(trail_len=7) for _ in balls]
        sparks = fx.Particles(rng, gravity=420.0, decay=2.2)
        confetti = fx.Particles(rng, gravity=260.0, decay=0.7)
        gate_pulse = 0.0
        finish_flash = 0.0
        fy = sim_h - 110.0
        Y = lambda y: sim_h - y  # physics is y-up; the screen is y-down
        cap_surface = fx.text_surface(overlay[0], overlay[1].size, sim_w * 0.9, colour=style.caption) if overlay else None
        ask_surface = fx.text_surface(ask[0], ask[1].size, sim_w * 0.9, colour=style.caption) if ask else None
        structure_hi = fx.lighten(style.structure, 60)
        gate_col = fx.lighten(style.structure, 34)

        surface = pygame.Surface((sim_w, sim_h))
        for frame_index, positions in enumerate(states):
            t = frame_index / fps
            dt = 1.0 / fps
            # --- events → animation state
            for im in by_frame.get(frame_index, []):
                i = im.index
                if i >= len(balls):
                    continue
                x, y = positions[i]
                # direction of the squash: away from where it was heading
                prev = states[frame_index - 1][i] if frame_index else (x, y)
                dx, dy = x - prev[0], Y(y) - Y(prev[1])
                norm = math.hypot(dx, dy) or 1.0
                anim[i].hit(im.strength, (dx / norm, dy / norm))
                if im.strength > 0.45:
                    sparks.burst(x, Y(y), fx.lighten(balls[i].color, 40), int(2 + im.strength * 6),
                                 speed=(60, 200 * im.strength + 60), size=(1.2, 2.6))
            for i, (x, y) in enumerate(positions):
                anim[i].step(x, Y(y), balls[i].radius)
                if style.gates:
                    throat = min(b[1] for _, b in style.gates)
                    prev_y = states[frame_index - 1][i][1] if frame_index else y
                    if prev_y > throat >= y:
                        gate_pulse = 1.0
            if winner_frame is not None and frame_index == winner_frame and winner_index is not None:
                wx, wy = positions[winner_index]
                for colour, count in (((255, 210, 80), 34), ((255, 255, 255), 26), ((120, 200, 255), 22), ((255, 120, 140), 22)):
                    confetti.burst(wx, Y(wy), colour, count, speed=(140, 360), size=(2.4, 4.2), arc=(-math.pi, 0), life=1.3)
                finish_flash = 1.0
            sparks.step(dt); confetti.step(dt)
            gate_pulse *= 0.86
            finish_flash *= 0.9

            # --- draw
            surface.fill(style.background)
            if finish_line:
                cell = 14
                lift = int(70 + 120 * finish_flash)
                for k in range(0, sim_w, cell):
                    shade = style.structure if (k // cell) % 2 == 0 else fx.lighten(style.structure, lift)
                    pygame.draw.rect(surface, shade, (k, fy - 4, cell, 8))
                if finish_flash > 0.05:
                    band = pygame.Surface((sim_w, 24), pygame.SRCALPHA); band.fill((255, 255, 255, int(120 * finish_flash)))
                    surface.blit(band, (0, fy - 12))
            if style.decoration != "none":
                _decorate_pygame(surface, style, frame_index, sim_w, sim_h)
            for i, ball in enumerate(balls):
                anim[i].draw_trail(surface, ball.radius, ball.color, alpha=48)
            # moving structure, each with a glow that says how fast it turns
            for sx, sy, half, omega, phase, *bias in style.rockers:
                angle = (bias[0] if bias else 0.0) + ROCK_AMPLITUDE * math.sin(omega * t + phase)
                dx, dy = math.cos(angle) * half, math.sin(angle) * half
                fx.capped_line(surface, (sx - dx, Y(sy - dy)), (sx + dx, Y(sy + dy)), style.thickness, structure_hi)
                fx.disc(surface, sx, Y(sy), style.thickness * 0.9, style.structure)
            for sx, sy, r, omega in style.drums:
                fx.soft(surface, sx, Y(sy), r * 1.18, (*structure_hi, int(min(80, 18 + abs(omega) * 10))), width=3)
                fx.disc(surface, sx, Y(sy), r, fx.lighten(style.structure, 22))
                for k in range(3):
                    angle = omega * t + k * 2.094
                    fx.capped_line(surface, (sx, Y(sy)), (sx + math.cos(angle) * r * 0.9, Y(sy + math.sin(angle) * r * 0.9)),
                                   max(2, style.thickness // 2), structure_hi)
                fx.disc(surface, sx, Y(sy), style.thickness * 0.6, style.structure)
            for sx, sy, half, omega, phase in style.spinners:
                angle = phase + omega * t
                dx, dy = math.cos(angle) * half, math.sin(angle) * half
                fx.soft(surface, sx, Y(sy), half * 1.04, (*structure_hi, int(min(70, 16 + abs(omega) * 12))), width=3)
                # a ghost of where the bar just was, so the spin has a direction
                ga = angle - omega * dt * 2.5
                gx, gy = math.cos(ga) * half, math.sin(ga) * half
                ghost = pygame.Surface((sim_w, sim_h), pygame.SRCALPHA)
                pygame.draw.line(ghost, (*structure_hi, 70), (sx - gx, Y(sy - gy)), (sx + gx, Y(sy + gy)), style.thickness)
                surface.blit(ghost, (0, 0))
                fx.capped_line(surface, (sx - dx, Y(sy - dy)), (sx + dx, Y(sy + dy)), style.thickness, structure_hi)
                fx.disc(surface, sx, Y(sy), style.thickness * 0.9, style.structure)
            for a, b, speed in style.belts:
                fx.capped_line(surface, (a[0], Y(a[1])), (b[0], Y(b[1])), style.thickness, fx.lighten(style.structure, 26))
                for mx, my, ux, uy in _belt_marks(a, b, speed, t):
                    # a chevron riding on the belt, pointing the way it runs
                    tip = (mx + ux * 6, Y(my + uy * 6))
                    nx, ny = -uy, ux
                    back_a = (mx - ux * 3 + nx * 4, Y(my - uy * 3 + ny * 4))
                    back_b = (mx - ux * 3 - nx * 4, Y(my - uy * 3 - ny * 4))
                    pygame.draw.polygon(surface, fx.lighten(style.structure, 110), [tip, back_a, back_b])
            for a, b in style.gates:
                col = fx.lighten(gate_col, int(120 * gate_pulse))
                fx.capped_line(surface, (a[0], Y(a[1])), (b[0], Y(b[1])), style.thickness, col)
                if gate_pulse > 0.05:
                    fx.soft(surface, b[0], Y(b[1]), style.thickness * (1.5 + 2 * (1 - gate_pulse)), (255, 255, 255, int(120 * gate_pulse)), width=2)
            for a, b in segments:
                fx.capped_line(surface, (a[0], Y(a[1])), (b[0], Y(b[1])), style.thickness, style.structure)
            for cx, cy, r in style.circles:
                fx.disc(surface, cx, Y(cy), r, style.structure)
                fx.disc(surface, cx - r * 0.25, Y(cy) - r * 0.35, r * 0.22, fx.lighten(style.structure, 40))
            for i, (ball, (x, y)) in enumerate(zip(balls, positions)):
                anim[i].draw(surface, x, Y(y), ball.radius, ball.color)
                if winner_index == i and winner_frame is not None and frame_index >= winner_frame:
                    fx.winner_rings(surface, x, Y(y), ball.radius, (frame_index - winner_frame) / fps)
            sparks.draw(surface); confetti.draw(surface)
            if cap_surface is not None:
                fx.caption_in(surface, cap_surface, sim_w / 2, overlay[3] + cap_surface.get_height() / 2, frame_index, overlay[4], fps, rise=sim_h * 0.04)
            if ask_surface is not None and winner_frame is not None:
                fx.pop_in(surface, ask_surface, sim_w / 2, ask[3], frame_index - winner_frame, ask[4], fps)
            yield fx.to_bytes(surface)

    def _frames_pil(
        self, states, balls, segments, sim_w, sim_h, overlay=None, style=None,
        winner_frame=None, winner=None, ask=None,
    ) -> Iterator[bytes]:
        style = style or _Style()
        finish_line = style.stage in STAGES  # races have one; the funnel does not
        winner_index = next((i for i, b in enumerate(balls) if b.name == winner), None)
        burst_rng = random.Random(style.seed * 17 + 3)
        burst = [(burst_rng.uniform(-1, 1), burst_rng.uniform(0.2, 1.0), burst_rng.uniform(0, 6.283),
                  burst_rng.choice([(255, 210, 80), (255, 255, 255), (120, 200, 255), (255, 120, 140)]))
                 for _ in range(46)]
        for frame_index, positions in enumerate(states):
            image = Image.new("RGB", (sim_w, sim_h), style.background)
            draw = ImageDraw.Draw(image)
            if finish_line:
                # A chequered band at the finish: the question the clip asks, drawn.
                fy = sim_h - 110.0
                cell = 14
                for k in range(0, sim_w, cell):
                    shade = style.structure if (k // cell) % 2 == 0 else tuple(min(255, c + 70) for c in style.structure)
                    draw.rectangle([k, fy - 4, k + cell, fy + 4], fill=shade)
            # Trails: where each marble just was, fading into the backdrop.
            for ball, index in zip(balls, range(len(balls))):
                for back in range(6, 0, -1):
                    j = frame_index - back * 2
                    if j < 0:
                        continue
                    px, py = states[j][index]
                    mix = 0.08 + 0.05 * (6 - back)
                    colour = tuple(int(bg + (c - bg) * mix) for c, bg in zip(ball.color, style.background))
                    r = ball.radius * (0.35 + 0.08 * (6 - back))
                    draw.ellipse([px - r, sim_h - py - r, px + r, sim_h - py + r], fill=colour)
            t = frame_index / 30.0
            for sx, sy, half, omega, phase, *bias in style.rockers:
                angle = (bias[0] if bias else 0.0) + ROCK_AMPLITUDE * math.sin(omega * t + phase)
                dx, dy = math.cos(angle) * half, math.sin(angle) * half
                draw.line([(sx - dx, sim_h - (sy - dy)), (sx + dx, sim_h - (sy + dy))],
                          fill=tuple(min(255, c + 60) for c in style.structure), width=style.thickness)
                hub = style.thickness * 0.9
                draw.ellipse([sx - hub, sim_h - sy - hub, sx + hub, sim_h - sy + hub], fill=style.structure)
            for sx, sy, r, omega in style.drums:
                draw.ellipse([sx - r, sim_h - sy - r, sx + r, sim_h - sy + r],
                             fill=tuple(min(255, c + 22) for c in style.structure))
                for k in range(3):  # spokes, so the spin can be seen
                    angle = omega * t + k * 2.094
                    draw.line([(sx, sim_h - sy), (sx + math.cos(angle) * r * 0.9, sim_h - (sy + math.sin(angle) * r * 0.9))],
                              fill=tuple(min(255, c + 70) for c in style.structure), width=max(2, style.thickness // 2))
            for sx, sy, half, omega, phase in style.spinners:
                angle = phase + omega * t
                dx, dy = math.cos(angle) * half, math.sin(angle) * half
                draw.line([(sx - dx, sim_h - (sy - dy)), (sx + dx, sim_h - (sy + dy))],
                          fill=tuple(min(255, c + 60) for c in style.structure), width=style.thickness)
                hub = style.thickness * 0.9
                draw.ellipse([sx - hub, sim_h - sy - hub, sx + hub, sim_h - sy + hub], fill=style.structure)
            for a, b, speed in style.belts:
                draw.line([(a[0], sim_h - a[1]), (b[0], sim_h - b[1])],
                          fill=tuple(min(255, c + 26) for c in style.structure), width=style.thickness)
                for mx, my, ux, uy in _belt_marks(a, b, speed, t):
                    nx, ny = -uy, ux
                    draw.polygon([(mx + ux * 6, sim_h - (my + uy * 6)),
                                  (mx - ux * 3 + nx * 4, sim_h - (my - uy * 3 + ny * 4)),
                                  (mx - ux * 3 - nx * 4, sim_h - (my - uy * 3 - ny * 4))],
                                 fill=tuple(min(255, c + 110) for c in style.structure))
            for a, b in style.gates:
                draw.line([(a[0], sim_h - a[1]), (b[0], sim_h - b[1])],
                          fill=tuple(min(255, c + 34) for c in style.structure), width=style.thickness)
            for a, b in segments:
                draw.line(
                    [(a[0], sim_h - a[1]), (b[0], sim_h - b[1])],
                    fill=style.structure,
                    width=style.thickness,
                )
            for cx, cy, r in style.circles:
                iy = sim_h - cy
                draw.ellipse([cx - r, iy - r, cx + r, iy + r], fill=style.structure)
                draw.ellipse([cx - r * 0.45, iy - r * 0.55, cx - r * 0.05, iy - r * 0.15],
                             fill=tuple(min(255, c + 40) for c in style.structure))
            if style.decoration != "none":
                _decorate(draw, style, frame_index, sim_w, sim_h)
            for ball, (x, y) in zip(balls, positions):
                iy = sim_h - y
                r = ball.radius
                draw.ellipse([x - r, iy - r, x + r, iy + r], fill=ball.color)
                draw.ellipse(
                    [x - r * 0.42, iy - r * 0.55, x - r * 0.06, iy - r * 0.19],
                    fill=tuple(min(255, c + 60) for c in ball.color),
                )
            if winner_frame is not None and winner_index is not None and 0 <= frame_index - winner_frame < 40:
                # The win: a burst from where the winner crossed, one second of it.
                age = (frame_index - winner_frame) / 40.0
                wx, wy = positions[winner_index]
                for ux, uy, spin, colour in burst:
                    dist = 26 + age * 170
                    x = wx + ux * dist
                    y = sim_h - (wy + uy * dist * (1 - age * 0.6) + 30 * age)
                    r = 2.6 * (1 - age) + 0.6
                    draw.ellipse([x - r, y - r, x + r, y + r], fill=colour)
            if overlay is not None:
                text, font, tx, ty, last = overlay
                if frame_index < last:
                    # Fade over the final third rather than cutting, which reads
                    # as a dropped frame.
                    fade = min(1.0, (last - frame_index) / max(1, last / 3))
                    mix = 0.25 + 0.75 * fade
                    draw.text((tx, ty), text, font=font,
                              fill=tuple(int(c * mix) for c in style.caption))
            if ask is not None and winner_frame is not None and frame_index >= winner_frame:
                text, font, ax, ay, span = ask
                age = frame_index - winner_frame
                if age < span:
                    # Fades in rather than appearing, so it does not read as a
                    # different clip spliced on.
                    mix = min(1.0, 0.3 + age / max(1, span / 3))
                    draw.text((ax, ay), text, font=font,
                              fill=tuple(int(c * mix) for c in style.caption))
            yield image.tobytes()


def _belt_marks(a, b, speed: float, t: float, spacing: float = 26.0):
    """Where the chevrons on a belt are at time t: evenly spaced along a→b
    and sliding at the belt's speed, so the belt reads as moving and the
    fast one reads as fast. Returns (x, y, ux, uy) in physics coordinates."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    length = math.hypot(dx, dy) or 1.0
    ux, uy = dx / length, dy / length
    shift = (t * speed) % spacing
    marks, d = [], shift
    while d < length - 4:
        marks.append((a[0] + ux * d, a[1] + uy * d, ux, uy))
        d += spacing
    return marks


def _decorate(draw, style: _Style, frame: int, w: int, h: int) -> None:
    """Seasonal particles, deterministic from the seed so a re-render matches.

    Cheap on purpose: a few dozen dots that fall, rise or twinkle. They sit
    behind the marbles and never touch the physics.
    """
    rng = random.Random(style.seed * 31 + 7)
    kind = style.decoration
    count = {"snow": 70, "embers": 40, "sparks": 55, "drops": 60}.get(kind, 0)
    t = frame / 30.0
    for i in range(count):
        x0 = rng.uniform(0, w)
        y0 = rng.uniform(0, h)
        speed = rng.uniform(22, 60)
        size = rng.uniform(1.2, 3.2)
        phase = rng.uniform(0, 6.283)
        if kind == "snow":
            x = (x0 + math.sin(t * 0.8 + phase) * 12) % w
            y = (y0 + t * speed) % h
            draw.ellipse([x - size, y - size, x + size, y + size], fill=(226, 232, 244))
        elif kind == "embers":
            x = (x0 + math.sin(t * 1.4 + phase) * 8) % w
            y = (y0 - t * speed) % h
            glow = int(150 + 100 * (0.5 + 0.5 * math.sin(t * 5 + phase)))
            draw.ellipse([x - size, y - size, x + size, y + size], fill=(255, glow, 40))
        elif kind == "sparks":
            twinkle = 0.5 + 0.5 * math.sin(t * 6 + phase)
            if twinkle > 0.45:
                s2 = size * twinkle
                draw.ellipse([x0 - s2, y0 - s2, x0 + s2, y0 + s2], fill=(240, 205, 90))
        elif kind == "drops":
            y = (y0 + t * speed * 3) % h
            draw.line([(x0, y), (x0, y + size * 4)], fill=(150, 205, 240), width=1)


def _decorate_pygame(surface, style: _Style, frame: int, w: int, h: int) -> None:
    """The seasonal particles, drawn with pygame; same seed, same positions."""
    from . import fx

    rng = random.Random(style.seed * 31 + 7)
    kind = style.decoration
    count = {"snow": 70, "embers": 40, "sparks": 55, "drops": 60}.get(kind, 0)
    t = frame / 30.0
    for _ in range(count):
        x0 = rng.uniform(0, w)
        y0 = rng.uniform(0, h)
        speed = rng.uniform(22, 60)
        size = rng.uniform(1.2, 3.2)
        phase = rng.uniform(0, 6.283)
        if kind == "snow":
            fx.soft(surface, (x0 + math.sin(t * 0.8 + phase) * 12) % w, (y0 + t * speed) % h, size, (226, 232, 244, 220))
        elif kind == "embers":
            glow = int(150 + 100 * (0.5 + 0.5 * math.sin(t * 5 + phase)))
            fx.soft(surface, (x0 + math.sin(t * 1.4 + phase) * 8) % w, (y0 - t * speed) % h, size * 1.6, (255, glow, 40, 160))
        elif kind == "sparks":
            twinkle = 0.5 + 0.5 * math.sin(t * 6 + phase)
            if twinkle > 0.45:
                fx.soft(surface, x0, y0, size * twinkle, (240, 205, 90, 230))
        elif kind == "drops":
            y = (y0 + t * speed * 3) % h
            fx.capped_line(surface, (x0, y), (x0, y + size * 4), 1, (150, 205, 240))


register(PhysicsSandbox())
