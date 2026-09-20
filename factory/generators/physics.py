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
from .base import GeneratedClip, register

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
POST_WIN_S = 1.3  # how long the race keeps running after the winner crosses
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
STAGES = {"zigzag": 0.26, "pegboard": 0.20, "bumpers": 0.22, "funnels": 0.14, "gauntlet": 0.13, "cascade": 0.05}
# Pace is gravity, not geometry: each stage was measured over 24 seeds and
# its gravity set so the median finish lands mid-window (see README).
STAGE_GRAVITY = {"zigzag": -600.0, "pegboard": -110.0, "bumpers": -95.0,
                 "funnels": -45.0, "gauntlet": -55.0, "cascade": -200.0}
STAGE_NOUN = {"zigzag": "ramps", "pegboard": "pegs", "bumpers": "bumpers",
              "funnels": "funnels", "gauntlet": "spinners", "cascade": "chutes"}
# Which stages get rotating bars, and how many. Measured: on the zigzag a bar
# knocked marbles back up the ramp until 10 seeds in 24 never finished; among
# pegs it reads as a glitch. In an open field it is one more thing to bounce
# off. The gauntlet is nothing but bars.
SPINNER_STAGES = {"bumpers": (3, 4), "gauntlet": (5, 6)}
STAGE_BLURB = {
    "zigzag": "ramps — fast, the classic",
    "pegboard": "pegs — a slow rattle down a Galton board",
    "bumpers": "bumpers and spinning bars — the busiest frame",
    "funnels": "stacked funnels — every throat is a bottleneck",
    "gauntlet": "a lane of spinning bars — nothing else in the way",
    "cascade": "chutes that split and rejoin — the marbles keep swapping sides",
}


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
    lane: list[tuple[tuple[float, float], tuple[float, float]]] = field(default_factory=list)  # the gauntlet's two verticals


@dataclass
class _Ball:
    body: pymunk.Body
    radius: float
    color: tuple[int, int, int]
    name: str


def _wall(space: pymunk.Space, a, b, thickness=6.0, friction=0.30) -> None:
    seg = pymunk.Segment(space.static_body, a, b, thickness)
    seg.elasticity = 0.46
    seg.friction = friction
    space.add(seg)


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


def _peg(space: pymunk.Space, x: float, y: float, r: float, elasticity: float = 0.62) -> None:
    shape = pymunk.Circle(space.static_body, r, offset=(x, y))
    shape.elasticity = elasticity
    shape.friction = 0.12
    space.add(shape)


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
    for i, frac in enumerate((0.16, 0.25, 0.35, 0.45, 0.55, 0.65)):
        for side in (0.28, 0.72) if i % 2 else (0.5,):
            x = inset + (w - 2 * inset) * side + rng.uniform(-12, 12)
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


_STAGES = {"zigzag": _stage_zigzag, "pegboard": _stage_pegboard, "bumpers": _stage_bumpers,
           "funnels": _stage_funnels, "gauntlet": _stage_gauntlet, "cascade": _stage_cascade}


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


def _spinner(space: pymunk.Space, x: float, y: float, half: float, omega: float, phase: float, thickness: float) -> None:
    body = pymunk.Body(body_type=pymunk.Body.KINEMATIC)
    body.position = (x, y)
    body.angle = phase
    body.angular_velocity = omega
    shape = pymunk.Segment(body, (-half, 0), (half, 0), thickness)
    shape.elasticity = 0.72
    shape.friction = 0.10
    space.add(body, shape)


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
GATE_STAGES = ("bumpers", "gauntlet")
GATE_HEIGHT = 0.085  # of the frame above the line: close enough that nothing re-spreads
GATE_GAP = (0.17, 0.21)  # of the width; about 3-3.7 of the largest marble
SPINNER_ROWS = {"bumpers": (0.26, 0.40, 0.54, 0.68), "gauntlet": (0.20, 0.30, 0.40, 0.50, 0.60, 0.70)}  # heights, frame fractions


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
            half = (lane_r - lane_l) * rng.uniform(0.36, 0.42)
            omega = rng.choice([-1, 1]) * rng.uniform(0.9, 1.5)
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
    mouth = throat + h * 0.11
    centre = w * rng.uniform(0.42, 0.58)
    gap = w * rng.uniform(*GATE_GAP)
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
    style.stage = stage or _pick(rng, STAGES)
    if style.stage not in _STAGES:
        raise ValueError(f"no stage {style.stage!r}; have {sorted(_STAGES)}")
    space.gravity = (0.0, STAGE_GRAVITY[style.stage])

    _wall(space, (4, 0), (4, h))
    _wall(space, (w - 4, 0), (w - 4, h))
    _wall(space, (4, 6), (w - 4, 6))

    segments, runway, lanes_for = _STAGES[style.stage](space, w, h, rng, style)
    _add_spinners(space, w, h, rng, style)
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
            other = [c for c in STAGES if c != heat["style"].stage] or list(STAGES)
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
                                        winner_frame=r["winner_frame"], winner=r["winner"])

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
                           else f"; no other marble crosses in the next {POST_WIN_S} seconds")
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
        base = {
            "zigzag": f"a {obstacles}-ramp zigzag stage",
            "pegboard": f"a pegboard of {obstacles} pegs",
            "bumpers": f"a field of {obstacles} bumpers",
            "funnels": f"{obstacles // 2} stacked funnels",
            "gauntlet": "a narrow gauntlet",
            "cascade": f"a cascade of {obstacles} chutes",
        }[style.stage]
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
            if winner_frame is not None and frame >= winner_frame + int(fps * POST_WIN_S):
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
        size = int(sim_w * 0.072)
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
        winner_frame=None, winner=None,
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
            for sx, sy, half, omega, phase in style.spinners:
                angle = phase + omega * t
                dx, dy = math.cos(angle) * half, math.sin(angle) * half
                draw.line([(sx - dx, sim_h - (sy - dy)), (sx + dx, sim_h - (sy + dy))],
                          fill=tuple(min(255, c + 60) for c in style.structure), width=style.thickness)
                hub = style.thickness * 0.9
                draw.ellipse([sx - hub, sim_h - sy - hub, sx + hub, sim_h - sy + hub], fill=style.structure)
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
            yield image.tobytes()


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


register(PhysicsSandbox())
