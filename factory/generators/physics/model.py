"""What a race is made of: the constants, the style bag, and a marble.

The lowest layer of the physics generator. It knows nothing about stages,
rendering or the pipeline, so everything else may import it and it imports
nothing back.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

import pymunk

from .. import stagekit
from ..stagekit import ROCK_AMPLITUDE, TRAP_SWING, trap_angle  # noqa: F401  (re-exported: the renderers draw with them)

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



class Stalled(RuntimeError):
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
# crossed arms) say so with Stage.wheel, so add_spinners leaves them alone
# and the tests know how many to expect.
# Fastest a marble may move, in sim px/s. Free fall down the whole frame
# reaches about 1600; anything past this came from a kinematic bar pinching
# a marble against a wall, which is not a hit, it is a glitch.
MAX_SPEED = 1900.0
TIP_GAP = 0.15  # of the width between the tips of neighbouring sieve bars: past the biggest marble, with air



@dataclass
class Style:
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
    traps: list[tuple[float, float, float, float, float, float]] = field(default_factory=list)  # hinge x, hinge y, bore, depth, period s, phase


@dataclass
class Ball:
    body: pymunk.Body
    radius: float
    color: tuple[int, int, int]
    name: str


def make_ball(space: pymunk.Space, pos, radius, color, name, friction=0.22) -> Ball:
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
    return Ball(body=body, radius=radius, color=color, name=name)


def seconds(value: float) -> str:
    """0.04 must not read as 0.0: a photo finish is the best thing a race can do."""
    return f"{value:.2f} seconds" if value < 0.1 else f"{value:.1f} seconds"


def pick(rng: random.Random, weights: dict[str, float]) -> str:
    total = sum(weights.values())
    roll = rng.uniform(0, total)
    for name, weight in weights.items():
        roll -= weight
        if roll <= 0:
            return name
    return next(iter(weights))


def parse_hex(value: str) -> tuple[int, int, int]:
    """'#1a2b3c' -> (26, 43, 60). Loud about anything else."""
    text = str(value).strip().lstrip("#")
    if len(text) != 6 or any(c not in "0123456789abcdefABCDEF" for c in text):
        raise ValueError(f"backdrop must be a hex colour like #1a2b3c, not {value!r}")
    return tuple(int(text[i : i + 2], 16) for i in (0, 2, 4))


def structure_for(background: tuple[int, int, int]) -> tuple[int, int, int]:
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
