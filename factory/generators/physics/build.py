"""Putting one space together: walls, a stage, its add-ons, the marbles."""

from __future__ import annotations

import math
import random

import pymunk

from .. import stagekit
from ..stagekit import _wall as wall, _peg as peg
from ... import themes
from .addons import add_finish_gate, add_spinners
from .addons import MARBLE_SPREAD
from .model import (FUNNEL_GRAVITY, PALETTES, RACE_COLORS, RACE_GRAVITY, Ball, Style,
                    make_ball, parse_hex, pick, structure_for)
from .registry import BUILDERS, STAGES, STAGE_GRAVITY

def build_race(space: pymunk.Space, w: int, h: int, rng: random.Random, stage: str | None = None,
                background: str | None = None, lineup: list | None = None):
    """A stage from the registry, dressed by the active theme.

    Everything a viewer can see in a single frame is varied: which stage, the
    backdrop, how thick the structure is, how many marbles and how big. What
    stays fixed is what keeps the solver honest — slopes, throat widths, pace.
    """
    theme = themes.active()
    style = Style()
    style.background, style.structure = rng.choice(theme.palettes)
    if background:
        # A person chose it, so it wins over the theme's palette — the theme's
        # marbles, caption colour and decoration still apply.
        style.background = parse_hex(background)
        style.structure = structure_for(style.background)
    style.thickness = rng.randint(8, 15)
    style.theme, style.decoration, style.caption = theme.id, theme.decoration, theme.caption
    style.stage = stage or pick(rng, {k: v for k, v in STAGES.items() if v > 0})
    if style.stage not in BUILDERS:
        raise ValueError(f"no stage {style.stage!r}; have {sorted(BUILDERS)}")
    space.gravity = (0.0, STAGE_GRAVITY[style.stage])

    wall(space, (4, 0), (4, h))
    wall(space, (w - 4, 0), (w - 4, h))
    wall(space, (4, 6), (w - 4, 6))
    # A ceiling. The gauntlet's lane-wide gates flung marbles clean out of
    # the top of the frame (one was measured 22 frame-heights up) and the
    # clip ended with them "still racing" somewhere in the sky.
    wall(space, (4, h - 2), (w - 4, h - 2))

    segments, runway, lanes_for = BUILDERS[style.stage](space, w, h, rng, style)
    add_spinners(space, w, h, rng, style)
    segments = list(segments) + style.lane_wedges
    add_finish_gate(space, w, h, rng, style)

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
        ball = make_ball(space, (x, h - 30.0), radius, tuple(color), name)
        ball.body.velocity = (rng.uniform(-20, 20), -130.0)  # already moving on frame one
        balls.append(ball)
    return balls, segments, style


def build_funnel(space: pymunk.Space, w: int, h: int, rng: random.Random):
    """Two funnels in series, throats measured in ball radii.

    Throat width is the one number that decides whether this variant works, and
    it is not a matter of taste. Below about five radii the balls arch across the
    opening and nothing comes through at all — measured over five seeds, a 3.4r
    throat left 54 of 54 balls sitting above it. Six radii drains every seed. The
    pour is stretched to a watchable length with gravity instead, which is a dial
    that cannot jam.
    """
    style = Style()
    style.background, style.structure = rng.choice(PALETTES)

    wall(space, (4, 0), (4, h))
    wall(space, (w - 4, 0), (w - 4, h))
    wall(space, (4, 6), (w - 4, 6))
    # A ceiling. The gauntlet's lane-wide gates flung marbles clean out of
    # the top of the frame (one was measured 22 frame-heights up) and the
    # clip ended with them "still racing" somewhere in the sky.
    wall(space, (4, h - 2), (w - 4, h - 2))

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
        wall(space, a, b)

    columns = 6
    pitch = radius * 2.35
    left = w / 2 - (columns - 1) * pitch / 2
    balls = []
    for i in range(54):
        x = left + (i % columns) * pitch + rng.uniform(-2.5, 2.5)
        y = h - 60.0 - (i // columns) * radius * 2.6
        ball = make_ball(space, (x, y), radius, hsv((i * 37 % 360) / 360.0), f"ball{i}")
        ball.body.velocity = (0.0, -90.0)  # falling on frame one, not hanging
        balls.append(ball)
    return balls, segments, style


def hsv(hue: float) -> tuple[int, int, int]:
    r, g, b = hsv_to_rgb(hue, 0.55, 0.92)
    return (int(r * 255), int(g * 255), int(b * 255))


def hsv_to_rgb(h: float, s: float, v: float):
    i = int(h * 6.0)
    f = h * 6.0 - i
    p, q, t = v * (1 - s), v * (1 - s * f), v * (1 - s * (1 - f))
    return [(v, t, p), (q, v, p), (p, v, t), (p, q, v), (t, p, v), (v, p, q)][i % 6]
