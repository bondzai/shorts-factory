"""Putting one space together: walls, a stage, its add-ons, the marbles."""

from __future__ import annotations

import logging
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
from .registry import BUILDERS, MECHANICS, STAGES, STAGE_GRAVITY
from .transform import mirror
from ..mechanics import MAX_ENTRANTS, Rig

log = logging.getLogger(__name__)

# What a cast entrant's traits may say (docs/08, "Cast"). Nudges, not a
# script: channels/<id>/cast.toml is tuned against the balance gate
# (`factory stage-qa --cast <id>`), where every regular wins 10-45%.
#   radius_mult   x the seed's radius for that marble
#   friction      the marble's shape friction (default 0.22, see make_ball)
#   mass_mult     x mass, and so x moment
#   jitter        a seeded random kick every frame; see simulate.JITTER_G
#   force_immune  magnets (and future fields) skip it
#   charge        a marble's share of a pair force (mechanics.Rig.pair_force), default 1
TRAITS = frozenset({"radius_mult", "friction", "mass_mult", "jitter", "force_immune", "charge"})
_warned: set[str] = set()


def known_traits(traits: dict) -> dict:
    """The traits physics understands; anything else is logged once and dropped."""
    for name in sorted(set(traits) - TRAITS):
        if name not in _warned:
            _warned.add(name)
            log.warning("physics ignores unknown cast trait %r (knows %s)", name, sorted(TRAITS))
    return {k: v for k, v in traits.items() if k in TRAITS}


def build_race(space: pymunk.Space, w: int, h: int, rng: random.Random, stage: str | None = None,
                background: str | None = None, lineup: list | None = None, cast: list | None = None,
                rig: Rig | None = None):
    """A stage from the registry, dressed by the active theme.

    Everything a viewer can see in a single frame is varied: which stage, the
    backdrop, how thick the structure is, how many marbles and how big. What
    stays fixed is what keeps the solver honest — slopes, throat widths, pace.

    `rig` is the round's mechanics (see generators/mechanics.py): sections
    register on it while the stage is built, and the round's params may ask
    for a start grid, a mirrored layout, another round's layout, a surface
    friction, or a level `section` mechanic. With nothing asked for, every
    draw below is the one it always was.
    """
    theme = themes.active()
    style = Style()
    knobs = rig.params if rig is not None else {}
    if rig is not None:
        style.rig = rig
    # A round that re-runs another round's layout (`round_params: [.., {layout: 0}]`)
    # builds the stage from that round's seed and draws its marbles from its own.
    srng = random.Random(int(knobs["layout_seed"])) if knobs.get("layout_seed") is not None else rng
    style.background, style.structure = srng.choice(theme.palettes)
    if background:
        # A person chose it, so it wins over the theme's palette — the theme's
        # marbles, caption colour and decoration still apply.
        style.background = parse_hex(background)
        style.structure = structure_for(style.background)
    style.thickness = srng.randint(8, 15)
    style.theme, style.decoration, style.caption = theme.id, theme.decoration, theme.caption
    picked = (pick(srng, {k: v for k, v in STAGES.items() if v > 0})
              if stage is None or knobs.get("layout_picked") else None)
    style.stage = stage or picked
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

    segments, runway, lanes_for = BUILDERS[style.stage](space, w, h, srng, style)
    add_spinners(space, w, h, srng, style)
    segments = list(segments) + style.lane_wedges
    add_finish_gate(space, w, h, srng, style)

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
    traits: list[dict] = [{}] * count
    if cast:
        # A season's entrants: exactly these, in this order, in their own
        # colours. The draws above are still made, so lanes, radii and launch
        # come off the seed's stream exactly as they would without a cast.
        colours = [(e["id"], parse_hex(e["color"])) for e in cast]
        traits = [known_traits(dict(e.get("traits") or {})) for e in cast]
        count = len(cast)
    if count > MAX_ENTRANTS:
        raise ValueError(f"stage {style.stage!r} has no room for {count} marbles; "
                         f"a race holds at most {MAX_ENTRANTS}")
    lanes = lanes_for(count)
    rows: list[float] | None = None
    if cast and count > 1:
        # The field is not the seed's to choose, so where the stage's runway
        # is too short for it (a nine-ramp zigzag has 137 px) the lanes run on
        # past it at the least spacing that keeps two of the biggest marbles
        # apart, still inside the walls; past those the stage is full.
        widest = max(float(t.get("radius_mult", 1.0)) for t in traits)
        biggest = base_radius * MARBLE_SPREAD[1] * widest
        need = 2.2 * biggest
        if abs(lanes[1] - lanes[0]) < need:
            step = need if lanes[-1] >= lanes[0] else -need
            lanes = [lanes[0] + i * step for i in range(count)]
            if not all(biggest + 6 <= x <= w - biggest - 6 for x in lanes):
                # One row cannot hold them: a start grid, rows staggered.
                lanes, rows = start_grid(space, w, h, count, biggest, need, style.stage)
    if rows is None:
        rng.shuffle(lanes)
    else:
        _shuffle_grid(rng, lanes, rows)

    balls = []
    for k, ((name, color), x, trait) in enumerate(zip(colours[:count], lanes, traits)):
        y = h - 30.0 if rows is None else rows[k]
        radius = base_radius * rng.uniform(*MARBLE_SPREAD)
        if trait:
            ball = make_ball(space, (x, y), radius * float(trait.get("radius_mult", 1.0)), tuple(color),
                             name, friction=float(trait.get("friction", 0.22)),
                             mass_mult=float(trait.get("mass_mult", 1.0)))
            ball.traits = trait
        else:
            ball = make_ball(space, (x, y), radius, tuple(color), name)
        ball.body.velocity = (rng.uniform(-20, 20), -130.0)  # already moving on frame one
        balls.append(ball)
    if cast:
        for ball, entrant in zip(balls, cast):
            ball.team = entrant.get("team")
    if rig is not None:
        segments = _rig_after_marbles(space, w, h, style, segments, balls, rig)
    return balls, segments, style


def start_grid(space, w: float, h: float, count: int, biggest: float, need: float,
               stage: str) -> tuple[list[float], list[float]]:
    """Lanes and row heights for a field one row cannot hold: rows of lanes
    `need` apart, each row most of a lane below the one above it and offset
    by half a lane, so no marble sits straight above another. A grid that
    reaches into the stage's structure is refused, loudly: a marble spawned
    inside a peg is a launch, not a start."""
    lo, hi = biggest + 6, w - biggest - 6
    per_row = int((hi - lo) // need) + 1
    rows_n = -(-count // per_row)
    per_row = -(-count // rows_n)  # balance the rows
    xs: list[float] = []
    ys: list[float] = []
    for r in range(rows_n):
        n = min(per_row, count - len(xs))
        span = (n - 1) * need
        stagger = (need / 4 if r % 2 else -need / 4) if rows_n > 1 else 0.0
        left = min(max((w - span) / 2 + stagger, lo), hi - span)
        y = h - 30.0 - r * need * 0.9
        for k in range(n):
            xs.append(left + k * need)
            ys.append(y)
    def frame_wall(shape) -> bool:
        # The side walls and the ceiling: the first row has always started
        # against the ceiling, so touching it is not what is being asked.
        if not isinstance(shape, pymunk.Segment):
            return False
        a, b = shape.a, shape.b
        return (a.x == b.x and a.x in (4, w - 4)) or (a.y == b.y and a.y >= h - 3)

    for x, y in zip(xs, ys):
        hits = [q for q in space.point_query((x, y), biggest + 2.0, pymunk.ShapeFilter())
                if not frame_wall(q.shape)]
        if hits:
            raise ValueError(f"stage {stage!r} has no room for {count} marbles: a start grid of "
                             f"{rows_n} rows reaches its structure at y={y:.0f}")
    return xs, ys


def _shuffle_grid(rng: random.Random, xs: list[float], ys: list[float]) -> None:
    """Who starts where is the seed's: one shuffle of the grid's slots."""
    slots = list(zip(xs, ys))
    rng.shuffle(slots)
    xs[:], ys[:] = [s[0] for s in slots], [s[1] for s in slots]


def _rig_after_marbles(space, w, h, style, segments, balls, rig: Rig) -> list:
    """What a round's params ask of the mechanics once the field is placed:
    the level's `section` mechanic, a mirror image of all of it, a surface
    friction, the marbles' filters. Returns the (possibly mirrored) segments.

    The mirror comes last so that nothing built before it — stage, sections'
    registrations, the mechanic's, the marbles — has to know about it."""
    section = rig.params.get("section")
    spec = MECHANICS.get(section) if section else None
    if spec is not None:
        spec.apply(rig, space, style, balls, w, h)
    elif section and section not in _warned:
        _warned.add(section)
        log.warning("physics has no mechanic %r; the race runs without it", section)
    if rig.params.get("mirror"):
        segments = mirror(space, style, segments, w)
        rig.mirror_registered()
        for ball in balls:
            p, v = ball.body.position, ball.body.velocity
            ball.body.position, ball.body.velocity = (w - p.x, p.y), (-v.x, v.y)
    mult = rig.params.get("friction")
    if mult is not None:
        # A round's surface friction (`round_params: [.., {friction: 0.5}]`):
        # every static surface, the stage's and the mechanics', times this.
        for shape in space.static_body.shapes:
            shape.friction = shape.friction * float(mult)
    rig.bind(balls)
    return segments


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
