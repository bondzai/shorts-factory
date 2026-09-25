"""World 7, Harvest Cup: Shrinking Arena (Season 0, L61-L70, and L77).

No finish line: a low-domed floor with a low wall at each end and a pit
beyond them. The walls close in, a step at a time, and the floor behind them
falls away. A marble that goes over a wall is over the pit and out; the last
one left on the floor wins (`format: last_standing`). Built in the physics
generator rather than battle.py, so an arena has the cast, trace, renderers,
presentation and standings every other world has.

Built on the core hooks (docs/10), nothing else:

- the walls are two `rig.moving_wall`s, their offsets clocks (`arena_left`,
  `arena_right`) that move a step every STEP_EVERY_S seconds. Each step is a
  slam: in OVERSHOOT of a marble past the step and back in SLAM_S, harder
  step by step. The slams are what keep an arena fair: with the walls only
  squeezing, the smallest marble won 37 of 46 (a squeeze lifts the bigger of
  two); knocked about, size stops deciding it (docs/06, World 7);
- the floor is a row of narrow tiles, each a `rig.door` that opens for good
  once the wall has gone past it, so the floor outside the walls is gone;
- the pit is one `rig.out_zone` under the floor, drawn dark;
- the walls are low (WALL_H of the biggest marble racing) and close to a
  last gap of FINAL_GAP of its diameter: one marble fits, two cannot sit side
  by side, and the one on top is above the walls with nothing to hold it. A
  marble whose centre goes out past a wall's line is out that frame
  (`pitted`), and the race is judged once the field has landed
  (`rig.unsettled`); an arena whose last two went out together is retried on
  a derived seed (`rig.survivor_needed`), so every clip ends with one left;
- `rig.hold` while the walls still have a step to make: a field resting
  between two steps is waiting for the walls, not wedged. Once they have
  stopped a field at rest is a stall, as anywhere else.

The walls stop the moment the race is decided (one marble left, or one team
on a team arena), so nothing takes the survivor after its win.

Sizes come from the marbles racing: the mechanic calls `fit(rig, balls)`,
which sets the walls' height and the last gap from the biggest marble and
seats the field in rows over the floor (the kit's start row spans the whole
frame, pits and all). A stage raced without a mechanic fits itself on its
first frame.

What each level adds (the mechanics, registered in physics/registry.py):

  shrinking-walls    L61  the arena and nothing else
  king-of-the-hill   L62  a hill in the middle; the walls stop after three
                          steps, and whoever holds the hill then wins (below)
  arena-trapdoors    L63  two World 2 panels in the floor, cycling
  arena-pushers      L64  the walls jab: a quick punch inward and back
  team-arena         L65  teams of two; a team survives while either is left
  ice-arena          L66  World 5's ice on the floor
  centre-magnet      L67  a World 3 magnet under the middle of the floor
  sudden-death-duel  L68  two marbles in the arena with trapdoors
  fan-arena-shape    L69  a W-shaped floor (the fan-vote stand-in)
  mega-arena         L70  walls, pushers and trapdoors, ten marbles
  repulsion-arena    L77  World 8's push between every pair of marbles

The camera: a `view` clock records the box worth showing (the walls, the
floor, the countdown), which present.py holds after the opening.

Nothing here reads who a marble is (docs/08 rule 2.4): the hill's holder is a
position, the jabs and panels are seeded clocks, the seats are the build's
shuffle.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import pymunk

from ...mechanics import rig_of
from ...stagekit import MARBLE_R, _wall
from . import trapdoor as w2

# --- the arena's numbers --------------------------------------------------------------------

FLOOR_FRAC = 0.34        # the floor's height, of the frame
PIT_ROOMS = 1.4          # the pit beyond each wall, in diameters of the kit's biggest marble
# The kit's radii (fractions of the width): base 0.036-0.050, spread
# 0.94-1.06, and a cast's radius_mult 0.95-1.1.
KIT_R_MAX = 0.050 * 1.06 * 1.1
KIT_R_MIN = 0.036 * 0.94 * 0.95
FIRST_STEP_S = 3.0       # the first step (simulation seconds; the clip opens 0.6 s in)
STEP_EVERY_S = 3.0
STEPS = 6
SLAM_S = 0.25            # how long a step's move takes
OVERSHOOT = 1.2          # a step's slam goes this much of the biggest diameter past, and back
WALL_H = 0.8             # the walls' height, in diameters of the biggest marble racing
FINAL_GAP = 1.3          # the last gap between the walls' faces, in the same
COUNT_AT = 3.4           # the countdown, this many of the kit's biggest diameters over the floor
VIEW_ROOM = 1.2          # the camera's margin past each wall, in the same
TILE = 12.0              # the floor's tiles, px: finer than a wall is thick
SEAT_DROP = 2.5          # the field's first row, this many diameters over the floor's top
SEAT_PITCH = 2.3         # between seats, in radii of the biggest marble
# The drop out of the arena: a marble whose centre is this many biggest-kit
# diameters under the floor is out.
PIT_DROP = 0.9
UNSETTLED = 0.35         # off the floor by this much of the biggest diameter: not landed yet
HOLD_AFTER_S = 0.6       # the hold runs this long past the last step's move
# `launched`: a marble a moving wall shoves to at least LAUNCH_V px/s more
# than its slowest speed of the last LAUNCH_FRAMES frames, while touching it.
LAUNCH_V = 260.0
LAUNCH_FRAMES = 4
LAUNCH_COOLDOWN_S = 1.0

# Pushers (L64, L68, L70): a wall's jab, inward and back, on a seeded cycle per
# wall. Depth in diameters of the biggest marble racing; never closer than
# JAB_KEEP diameters to the other wall.
JAB_DEPTH = 0.9
JAB_IN_S, JAB_HOLD_S, JAB_OUT_S = 0.10, 0.12, 0.45
JAB_PERIOD = (2.2, 2.9)
JAB_KEEP = 1.05
JAB_FROM_S = 2.5
# The floor's trapdoors (L63, L70): World 2's panel, from this many seconds, open this share of a cycle.
TRAP_FROM_S = 2.5
TRAP_SHARE = 0.35

# What a stage does when a level names no mechanic, and what its mechanics
# start from (a level's `mechanics` knobs win over both).
SHAPE_DEFAULTS = {
    # The panels catch early: half slams, a later first step, panels from
    # 9 s (a field of three to five; L63's seven start them at 7 s; docs/06).
    "trap": {"overshoot": 0.5, "first_step": 4.0, "trap_from": 9.0, "trap_share": 0.25},
}

# The hill (L62): a top a marble wide and a bit (a shallow cup), slopes that shed.
HILL_TOP = 1.5           # plateau, in the kit's biggest diameter
HILL_H = 0.55            # height, in the same
HILL_SLOPE = 0.5
HILL_DIP = 0.2            # the top's cup, in the kit's biggest diameter
HILL_MOVES = 3           # the walls move three times, then stop
HILL_GOLD = (236, 190, 70)

# The W floor (L69's stand-in): two valleys either side of a middle ridge.
W_SLOPE = 0.2
W_VALLEY = 0.5           # the valleys, half-way from the middle to the walls
# Every other arena's floor: a low dome, so a marble rolls to a wall, where the
# next slam finds it, instead of resting in the middle.
DOME_SLOPE = 0.15


def _ease(u: float) -> float:
    u = min(1.0, max(0.0, u))
    return u * u * (3.0 - 2.0 * u)


@dataclass
class Arena:
    shape: str
    w: float
    h: float
    cx: float
    fy: float
    xl0: float           # the left wall's centre at the start
    xr0: float
    t: float             # the walls' and tiles' radius
    slope: float         # the floor's slope away from the middle (the dome's is < 0)
    walls: list = field(default_factory=list)      # the rig's _Wall records, left then right
    steps: int = STEPS
    moves: int = STEPS   # moves made before the walls stop (the hill: fewer)
    first: float = FIRST_STEP_S
    every: float = STEP_EVERY_S
    travel: float = 0.0  # each wall's whole way in, set by `fit`
    d_max: float = 0.0   # the biggest marble racing, diameter
    fitted: bool = False
    team_survival: bool = False
    jabs: list | None = None   # per wall: (period, phase)
    last_d: list = field(default_factory=lambda: [0.0, 0.0])  # each wall's way in, last frame
    hill: tuple | None = None  # (x0, x1, top y, base half-width)
    stop_at: float | None = None
    tiles: list = field(default_factory=list)  # (side, x_far, x_near)
    floor_shapes: list = field(default_factory=list)  # the static middle of the floor
    slam: float = SLAM_S
    overshoot: float = 0.0
    jab_from: float = JAB_FROM_S
    jab_depth: float = JAB_DEPTH
    valley: float = 0.0  # the W floor (L69): the valleys' distance from the middle
    ramp: bool = True

    # -- geometry --------------------------------------------------------

    def floor_y(self, x: float) -> float:
        if self.valley:
            return self.fy + self.slope * abs(abs(x - self.cx) - self.valley)
        return self.fy + self.slope * abs(x - self.cx)

    def step_d(self, t: float) -> float:
        """How far each wall has come in at time t (before any jab)."""
        if not self.fitted or self.travel <= 0:
            return 0.0
        step = self.travel / self.steps
        d = 0.0
        for k in range(self.moves):
            tk = self.first + k * self.every
            if t <= tk:
                break
            u = (t - tk) / self.slam
            d += step * _ease(u)
            if u < 1.0:
                # The slam: in past the step and back, so what it meets is hit.
                # Harder each step: the first ones only shove.
                ramp = (k + 1) / self.moves if self.ramp else 1.0
                d += self.overshoot * ramp * self.d_max * math.sin(math.pi * u)
        return d

    def last_move_end(self) -> float:
        return self.first + (self.moves - 1) * self.every + self.slam

    def gap(self, d_left: float, d_right: float) -> float:
        """The gap between the walls' faces."""
        return (self.xr0 - d_right) - (self.xl0 + d_left) - 2 * self.t

    def jab(self, side: int, t: float, d: float) -> float:
        if not self.jabs or t < self.jab_from:
            return 0.0
        period, phase = self.jabs[side]
        u = ((t / period) + phase) % 1.0 * period
        if u < JAB_IN_S:
            k = _ease(u / JAB_IN_S)
        elif u < JAB_IN_S + JAB_HOLD_S:
            k = 1.0
        elif u < JAB_IN_S + JAB_HOLD_S + JAB_OUT_S:
            k = 1.0 - _ease((u - JAB_IN_S - JAB_HOLD_S) / JAB_OUT_S)
        else:
            return 0.0
        room = max(0.0, (self.gap(d, d) - JAB_KEEP * self.d_max) / 2)
        return min(self.jab_depth * self.d_max, room) * k


def arena_of(rig) -> Arena:
    a = getattr(rig, "arena", None)
    if a is None:
        raise ValueError("this mechanic needs an arena stage (docs/06, World 7)")
    return a


def _decided(f, a: Arena) -> bool:
    """One marble left, or (a team arena) one team."""
    live = [i for i in range(len(f.names)) if f.alive[i] and f.names[i] not in f.finished]
    if len(live) <= 1:
        return True
    if a.team_survival:
        balls = f.rig.balls
        return len({getattr(balls[i], "team", None) or f.names[i] for i in live}) <= 1
    return False


def _unsettled(f, a: Arena) -> bool:
    """A marble still racing is off the floor: in the air, on another's back
    or on a wall's top (its centre more than UNSETTLED of the biggest
    marble's diameter over where it would rest on the floor). Who is left is
    judged once everyone has landed."""
    balls = f.rig.balls
    for i, (x, y) in enumerate(f.positions):
        if f.alive[i] and f.names[i] not in f.finished:
            rest = a.floor_y(x) + a.t + balls[i].radius
            if a.hill is not None and abs(x - a.cx) < a.hill[3]:
                rest = max(rest, a.hill[2] + a.t + balls[i].radius)
            if y > rest + UNSETTLED * a.d_max:
                return True
    return False


# --- the stage -------------------------------------------------------------------------------

def arena_build(shape: str = "dome"):
    """A stage builder: the arena, with a pit either side and the floor at
    FLOOR_FRAC of the frame. `shape`: dome (the arena), trap (the dome with a
    trapdoor panel each side of the middle), hill (a flat floor with a hill
    in the middle, L62), w (two valleys and a ridge, L69)."""

    def build(space, w, h, rng, style):
        rig = rig_of(style)
        rig.no_finish_line()
        # With no line the only result is who is left.
        if not rig.elimination:
            rig.elimination, rig.win = True, "last_standing"
        return _build(space, w, h, rng, style, rig, shape)

    build.parts = ()  # type: ignore[attr-defined]
    return build


def _build(space, w, h, rng, style, rig, shape):
    big = w * KIT_R_MAX * 2
    t = style.thickness / 2
    pit = big * PIT_ROOMS
    cx = w / 2 + rng.uniform(-0.01, 0.01) * w
    fy = h * FLOOR_FRAC
    xl0, xr0 = 8.0 + pit + t, w - 8.0 - pit - t
    if shape not in ("dome", "trap", "hill", "w"):
        raise ValueError(f"no arena shape {shape!r}")
    a = Arena(shape, w, h, cx, fy, xl0, xr0, t, -DOME_SLOPE if shape in ("dome", "trap") else 0.0)
    if shape == "w":
        a.slope = W_SLOPE
        a.valley = (xr0 - xl0) / 2 * W_VALLEY
    rig.arena = a
    segments: list = []

    # The middle of the floor never opens: the walls stop short of it.
    inner = w * KIT_R_MIN * 2 * FINAL_GAP / 2
    keep: list[tuple[float, float]] = []   # spans the tiles leave to something else
    if shape == "hill":
        top = big * HILL_TOP
        hh = big * HILL_H
        base = top / 2 + hh / HILL_SLOPE
        a.hill = (cx - top / 2, cx + top / 2, fy + hh, base)
        pts = [(cx - base, fy), (cx - top / 2, fy + hh), (cx + top / 2, fy + hh), (cx + base, fy)]
        for p, q in ((pts[0], pts[1]), (pts[2], pts[3])):
            _wall(space, p, q, thickness=t)
            segments.append((p, q))
        # The top, lit: the hill a marble holds. A shallow cup, so a marble
        # that gets up there can stay unless it is knocked off.
        dip = (cx, fy + hh - big * float(rig.knob("hill_dip", HILL_DIP)))
        for p, q in ((pts[1], dip), (dip, pts[2])):
            rig.door(space, p, q, color=HILL_GOLD, thickness=t)
        inner = max(inner, base)
        rig.on_frame(_judge(a))
        rig.clock("hill_held", lambda f: a.stop_at is not None and f.t >= a.stop_at)
    if shape == "trap":
        # Two World 2 panels, one each side of the middle, where the walls
        # reach at their third step: a marble can be caught on either until
        # the wall goes past it, and then the lid is gone with the floor.
        pw = big * 1.35
        span = (xr0 - xl0) / 2
        for side in (-1, 1):
            c = cx + side * span * rng.uniform(0.40, 0.46)
            x0, x1 = c - pw / 2, c + pw / 2
            segments += _panel(space, w, style, rig, a, x0, x1)
            keep.append((x0, x1))
    lo, hi = cx - inner, cx + inner
    # The middle of the floor, static, broken where the floor's slope turns.
    xs = sorted({lo, hi, *(x for x in (cx,) if lo < x < hi)})
    for x0, x1 in zip(xs, xs[1:]):
        p, q = (x0, a.floor_y(x0)), (x1, a.floor_y(x1))
        seg = pymunk.Segment(space.static_body, p, q, t)
        seg.elasticity, seg.friction = 0.46, 0.30
        space.add(seg)
        a.floor_shapes.append(seg)
        segments.append((p, q))
    _tiles(space, style, rig, a, lo, hi, keep)

    # The walls. Built a marble high; `fit` sets their height from the field.
    rig.clock("arena_unsettled", lambda f: a.fitted and _unsettled(f, a))
    rig.unsettled = "arena_unsettled"
    rig.survivor_needed = True
    rig.clock("arena_decided", lambda f: a.fitted and not f.values.get("arena_unsettled") and _decided(f, a))
    for side, x0 in ((0, xl0), (1, xr0)):
        y0 = a.floor_y(x0)
        name = "arena_left" if side == 0 else "arena_right"
        rig.moving_wall(space, (x0, y0), (x0, y0 + big * WALL_H), name, thickness=t)
        a.walls.append(rig.walls[-1])
        rig.clock(name, lambda f, side=side: _wall_offset(f, a, side))
    for k, (side, far, near) in enumerate(a.tiles):
        rig.clock(f"arena_tile{k}", lambda f, side=side, near=near: not _passed(f, a, side, near))
    # (The hill's walls stop early and the field waits for the stop.)
    rig.clock("arena_closing", lambda f: a.fitted and not f.values.get("arena_decided")
              and f.t < (a.stop_at if a.stop_at is not None else a.last_move_end() + HOLD_AFTER_S))
    rig.hold("arena_closing")
    # Whole seconds to the walls' next move, over the arena.
    rig.clock("arena_next", lambda f: _next_in(f, a))
    rig.effect("countdown", clock="arena_next", at=(cx, fy + big * COUNT_AT))
    # What the camera holds after the opening (present.py): the walls, the
    # floor, the countdown, closing in with the walls.
    rig.clock("view", lambda f: _view(f, a))
    # The pit: under the floor, the whole width.
    low = min(a.floor_y(xl0), a.floor_y(cx)) - big * PIT_DROP
    rig.out_zone((8.0, 8.0, w - 8.0, low), event="pitted", label="pit")
    rig.on_frame(lambda f: _first_frame(f, a))
    rig.on_frame(lambda f: _over_wall(f, a))
    rig.on_frame(_launch_watch(a))
    span = xr0 - xl0 - 2 * t

    def lanes(count):
        m = span * 0.12
        x0, x1 = xl0 + t + m, xr0 - t - m
        return [x0 + (x1 - x0) * i / max(count - 1, 1) for i in range(count)] if count > 1 else [cx]

    return segments, span * 0.76, lanes


def _tiles(space, style, rig, a: Arena, lo: float, hi: float, keep) -> None:
    """The floor from each wall's start in to the middle, as tiles: a door
    each, shut until the wall has gone past it. Tiles open from the outside
    in, so what is left is always one floor between the walls."""
    colour = tuple(style.structure)
    for side in (0, 1):
        start = a.xl0 - a.t if side == 0 else a.xr0 + a.t
        end = lo if side == 0 else hi
        n = max(1, int(math.ceil(abs(end - start) / TILE)))
        edges = [start + (end - start) * k / n for k in range(n + 1)]
        cuts = [x for k0, k1 in keep for x in (k0, k1) if min(start, end) < x < max(start, end)]
        if a.valley:
            cuts += [x for x in (a.cx - a.valley, a.cx + a.valley) if min(start, end) < x < max(start, end)]
        edges = sorted(set(edges + cuts), reverse=end < start)
        for far, near in zip(edges, edges[1:]):
            x0, x1 = min(far, near), max(far, near)
            if any(k0 - 0.5 <= x0 and x1 <= k1 + 0.5 for k0, k1 in keep):
                continue  # a panel's lid is the floor here
            rig.door(space, (far, a.floor_y(far)), (near, a.floor_y(near)), closed=f"arena_tile{len(a.tiles)}",
                     color=colour, thickness=a.t)
            a.tiles.append((side, far, near))


def _panel(space, w, style, rig, a: Arena, x0: float, x1: float) -> list:
    """A World 2 panel in the floor: a lid that follows the floor over a pit
    a marble deep."""
    big = w * MARBLE_R
    t = a.t
    y0, y1 = a.floor_y(x0), a.floor_y(x1)
    low = min(y0, y1)
    bottom = low - big * w2.PIT_DEPTH
    walls = [((x0, y0), (x0, bottom)), ((x0, bottom), (x1, bottom)), ((x1, bottom), (x1, y1))]
    for p, q in walls:
        _wall(space, p, q, thickness=t)
    shape = "flat" if abs(y1 - y0) < 0.5 else ("left" if y0 < y1 else "right")
    panel = w2.Panel(0, x0, x1, low, bottom, abs(y1 - y0), shape, w2._row(style),
                     default=(rig.rng.uniform(3.0, 4.0), 0.35, rig.rng.random()))
    w2._install(space, style, panel, [((x0, y0), (x1, y1))], t)
    side = 0 if (x0 + x1) / 2 < a.cx else 1
    near = x1 if side == 0 else x0
    # Its own rule: cycling (World 2's seeded default) while the race is on,
    # and open for good once the wall has gone past it.
    panel.opener = lambda f, c=w2.cycling(*panel.default, after=w2.GRACE_S): (
        _passed(f, a, side, near) or (c(f) and not _decided(f, a)))
    panel.holds = lambda f: not _decided(f, a)
    return walls


def _offsets(f, a: Arena, side: int) -> float:
    key = "arena_left" if side == 0 else "arena_right"
    v = f.values.get(key)
    return float(v[0]) * (1 if side == 0 else -1) if v else 0.0


def _passed(f, a: Arena, side: int, near: float) -> bool:
    """The wall has stepped past x `near` on its way in (a jab is a punch,
    not a step: the floor it passes over stays)."""
    d = min(_offsets(f, a, side), a.step_d(f.t)) if a.fitted else 0.0
    return (a.xl0 + d >= near) if side == 0 else (a.xr0 - d <= near)


def _wall_offset(f, a: Arena, side: int) -> list[float]:
    """Where a wall is: its steps in, plus a jab (pushers), and still from
    the frame the race is decided."""
    if a.fitted and f.values.get("arena_decided"):
        d = a.last_d[side]
    else:
        d = a.step_d(f.t)
        d += a.jab(side, f.t, d)
        a.last_d[side] = d
    x0 = a.xl0 if side == 0 else a.xr0
    x = x0 + d if side == 0 else x0 - d
    return [round(x - x0, 3), round(a.floor_y(x) - a.floor_y(x0), 3)]


def _view(f, a: Arena) -> list[float]:
    """The box worth showing, physics px: the walls where their steps have
    put them, a marble's room either side, from under the floor to the
    countdown."""
    big = a.w * KIT_R_MAX * 2
    d = a.step_d(f.t) if a.fitted else 0.0
    room = big * VIEW_ROOM
    x0 = max(0.0, a.xl0 + d - a.t - room)
    x1 = min(a.w, a.xr0 - d + a.t + room)
    low = min(a.floor_y(a.xl0 + d), a.floor_y(a.cx), a.floor_y(a.xr0 - d)) - big * 0.8
    return [round(x0, 1), round(low, 1), round(x1, 1), round(a.fy + big * (COUNT_AT + 0.8), 1)]


def _next_in(f, a: Arena):
    if not a.fitted or f.values.get("arena_decided"):
        return None
    for k in range(a.moves):
        tk = a.first + k * a.every
        if f.t < tk:
            return math.ceil(tk - f.t - 1e-9) if tk - f.t <= a.every else None
    if a.stop_at is not None and f.t < a.stop_at:
        return math.ceil(a.stop_at - f.t - 1e-9)
    return None


def _over_wall(f, a: Arena) -> None:
    """A marble whose centre has gone out past a wall's line is over it,
    with no floor under it: out (`pitted`, by `pit`) that frame, not a
    second later at the bottom of the pit, so a race is decided by who is
    left on the floor."""
    if not a.fitted:
        return
    xl = a.xl0 + _offsets(f, a, 0)
    xr = a.xr0 - _offsets(f, a, 1)
    for i, (x, _y) in enumerate(f.positions):
        if f.alive[i] and (x < xl or x > xr):
            f.rig.eliminate(i, by="pit", event="pitted")


def _judge(a: Arena):
    """The hill's rule (L62). At `a.stop_at` the marble holding the hill
    wins and everyone else is out (`by: hill`), with a `walls_stopped` event.

    Holds, measured: of the marbles whose centre is over the hill's lit top
    and within a marble of it (on the top, not riding someone's back), the
    one nearest its middle; if none is on the top, the marble nearest the
    top's middle point."""
    state = {"done": False}

    def judge(f):
        if state["done"] or a.stop_at is None or f.t < a.stop_at:
            return
        state["done"] = True
        live = [i for i in range(len(f.names)) if f.alive[i]]
        if not live:
            return
        x0, x1, top, _base = a.hill
        mid = (x0 + x1) / 2
        radii = [b.radius for b in f.rig.balls]
        on_top = [i for i in live if x0 <= f.positions[i][0] <= x1
                  and f.positions[i][1] <= top + a.t + radii[i] + radii[i]]
        pool = on_top or live
        holder = min(pool, key=lambda i: (math.hypot(f.positions[i][0] - mid, f.positions[i][1] - top), i))
        f.rig.emit("walls_stopped", None, on_top=len(on_top))
        for i in live:
            if i != holder:
                f.rig.eliminate(i, by="hill")

    return judge


def _first_frame(f, a: Arena) -> None:
    if not a.fitted:
        fit(f.rig, None, f.rig.balls, seat=False)


def _launch_watch(a: Arena):
    """`launched`: a marble a moving wall shoves hard (LAUNCH_V px/s over its
    slowest speed of the last few frames) while touching it."""
    speeds: dict[int, list[float]] = {}
    last: dict[int, float] = {}
    where = {0: None, 1: None}

    def watch(f):
        rig = f.rig
        moving = []
        for side, wl in enumerate(a.walls):
            off = f.values.get(wl.offset) or [0.0, 0.0]
            before = where[side]
            where[side] = off
            if before is not None and math.dist(off, before) > 0.5:
                moving.append((side, wl, off))
        for i, b in enumerate(rig.balls):
            if not f.alive[i]:
                continue
            v = b.body.velocity.length
            hist = speeds.setdefault(i, [])
            hist.append(v)
            if len(hist) > LAUNCH_FRAMES + 1:
                hist.pop(0)
            if not moving or f.t - last.get(i, -9.0) < LAUNCH_COOLDOWN_S:
                continue
            if v - min(hist) < LAUNCH_V:
                continue
            px, py = f.positions[i]
            for side, wl, off in moving:
                ax, ay = wl.a[0] + off[0], wl.a[1] + off[1]
                bx, by = wl.b[0] + off[0], wl.b[1] + off[1]
                if _seg_dist(px, py, ax, ay, bx, by) <= b.radius + a.t + 6.0:
                    last[i] = f.t
                    rig.emit("launched", i)
                    break

    return watch


def _seg_dist(px, py, ax, ay, bx, by) -> float:
    dx, dy = bx - ax, by - ay
    l2 = dx * dx + dy * dy
    u = 0.0 if l2 == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / l2))
    return math.hypot(px - (ax + u * dx), py - (ay + u * dy))


# --- fitting the arena to the field ------------------------------------------------------------

def _knob(rig, name: str, default):
    """A level's knob, else the mechanic's default for it (`rig.w7_defaults`), else `default`."""
    return rig.knob(name, getattr(rig, "w7_defaults", {}).get(name, default))


def fit(rig, space, balls, *, seat: bool = True, **defaults) -> Arena:
    """Size the arena from the marbles racing: the walls WALL_H of the biggest
    marble's diameter high, their last gap FINAL_GAP of it; and (`seat`) the
    field seated in rows over the floor, in the order the build shuffled it."""
    a = arena_of(rig)
    rig.w7_defaults = {**SHAPE_DEFAULTS.get(a.shape, {}), **defaults}
    r_max = max(b.radius for b in balls)
    a.d_max = 2 * r_max
    a.slam = float(_knob(rig, "slam_s", SLAM_S))
    a.overshoot = float(_knob(rig, "overshoot", OVERSHOOT))
    a.ramp = bool(_knob(rig, "ramp", True))
    a.every = float(_knob(rig, "step_every", STEP_EVERY_S))
    a.first = float(_knob(rig, "first_step", FIRST_STEP_S))
    a.steps = a.moves = int(_knob(rig, "steps", STEPS))
    bounce = _knob(rig, "wall_bounce", None)
    for wl in a.walls:
        ax, ay = wl.a
        top = (ax, ay + a.d_max * float(_knob(rig, "wall_h", WALL_H)))
        wl.b = top
        for shape in wl.body.shapes:
            shape.unsafe_set_endpoints(wl.a, top)
            if bounce is not None:
                shape.elasticity = float(bounce)
    last = a.xr0 - a.xl0 - 2 * a.t
    want = float(_knob(rig, "final_gap", FINAL_GAP)) * a.d_max
    a.travel = max(0.0, (last - want) / 2)
    if a.hill is not None:
        # The hill: HILL_MOVES steps, ending a marble's room and a bit from
        # each foot of the hill, then the stop on the next step's beat.
        a.moves = int(_knob(rig, "moves", HILL_MOVES))
        a.stop_at = a.first + a.moves * a.every
        base = a.hill[3]
        want = 2 * base + 2 * float(_knob(rig, "foot_room", 1.3)) * a.d_max
        a.travel = max(0.0, (last - want) / 2) * a.steps / a.moves
    if w2.panels_of(rig):
        _arm_panels(rig, a)
    a.fitted = True
    if seat:
        _seat(a, balls, r_max)
    return a


def _seat(a: Arena, balls, r_max: float) -> None:
    pitch = SEAT_PITCH * r_max
    lo = a.xl0 + a.t + r_max * 1.4
    hi = a.xr0 - a.t - r_max * 1.4
    per_row = max(1, int((hi - lo) // pitch) + 1)
    n = len(balls)
    rows = -(-n // per_row)
    per_row = -(-n // rows)
    slots = []
    y0 = a.floor_y(a.cx) + a.t + r_max + SEAT_DROP * 2 * r_max
    for r in range(rows):
        k = min(per_row, n - len(slots))
        span = (k - 1) * pitch
        stagger = (pitch / 4 if r % 2 else -pitch / 4) if rows > 1 else 0.0
        left = min(max(a.cx - span / 2 + stagger, lo), hi - span)
        for j in range(k):
            slots.append((left + j * pitch, y0 + r * pitch * 0.9))
    # The build shuffled who starts where (its lanes, or its grid): keep
    # that order, read top row first, left to right.
    order = sorted(range(n), key=lambda i: (-round(balls[i].body.position.y), balls[i].body.position.x))
    for i, (x, y) in zip(order, slots):
        balls[i].body.position = (x, y)


# --- the mechanics a level names (`params.section`) -------------------------------------------

def shrinking_walls(rig, space, style, balls, w, h):
    """L61: the walls close a step every three seconds until one is left."""
    fit(rig, space, balls)


def king_of_the_hill(rig, space, style, balls, w, h):
    """L62: a hill in the middle (the `arenahill` stage, whose own rule it is:
    `_judge`). The walls move HILL_MOVES times, pushing the field up its
    slopes, then stop on the beat of the step that would have come next (a
    countdown shows it); the marble holding the hill then wins and everyone
    else is out (`by: hill`)."""
    if arena_of(rig).hill is None:
        raise ValueError("king-of-the-hill needs the arenahill stage")
    fit(rig, space, balls)


def arena_trapdoors(rig, space, style, balls, w, h):
    """L63: the arena with a trapdoor panel each side of the middle (the
    `arenatrap` stage's own; World 2's panel), cycling on seeded clocks."""
    if not w2.panels_of(rig):
        raise ValueError("arena-trapdoors needs the arenatrap stage")
    # The stage's own defaults (SHAPE_DEFAULTS["trap"]), the panels from 7 s:
    # seven marbles crowd the floor and last longer.
    fit(rig, space, balls, trap_from=7.0)


def _pushers(rig, a: Arena) -> None:
    a.jabs = [(rig.rng.uniform(*JAB_PERIOD), rig.rng.random()) for _ in range(2)]
    a.jab_from = float(_knob(rig, "jab_from", JAB_FROM_S))
    a.jab_depth = float(_knob(rig, "jab_depth", JAB_DEPTH))


def _arm_panels(rig, a: Arena) -> None:
    """The floor's panels cycle on their seeded clocks from `trap_from`
    seconds, open `trap_share` of each cycle, and open for good once a wall
    has gone past them; shut once the race is decided."""
    after = float(_knob(rig, "trap_from", TRAP_FROM_S))
    share = float(_knob(rig, "trap_share", TRAP_SHARE))
    for p in w2.panels_of(rig):
        period, _share, phase = p.default
        side = 0 if p.cx < a.cx else 1
        near = p.x1 if side == 0 else p.x0
        cyc = w2.cycling(period, share, phase, after=after)
        p.opener = lambda f, cyc=cyc, side=side, near=near: (
            _passed(f, a, side, near) or (cyc(f) and not _decided(f, a)))


def arena_pushers(rig, space, style, balls, w, h):
    """L64: the walls hit back: from 6 s each wall jabs in (a third of a
    marble in JAB_IN_S) and back, on its own seeded cycle. The jabs are the
    hits, so the steps themselves do not slam."""
    a = fit(rig, space, balls, overshoot=0.0, jab_from=6.0, jab_depth=0.35)
    _pushers(rig, a)


def team_arena(rig, space, style, balls, w, h):
    """L65: teams (params.teams). A team survives while either of its marbles
    is on the floor; the round is decided when one team is left."""
    if not any(getattr(b, "team", None) for b in balls):
        raise ValueError("team-arena needs teams (params.teams: {id: 2, ...})")
    a = fit(rig, space, balls)
    a.team_survival = True
    rig.team_survival = True


def ice_arena(rig, space, style, balls, w, h):
    """L66: the floor is ice (World 5's `ice`: friction 0.02, bouncier),
    drawn with its sheen. Walls push, marbles slide."""
    from ...mechanics import SURFACES
    # On ice a slam sends a marble a long way: half the plain arena's.
    a = fit(rig, space, balls, overshoot=0.6)
    ice = SURFACES["ice"]
    for shape in [d.shape for d in rig.doors] + a.floor_shapes:
        shape.friction, shape.elasticity = ice["friction"], ice["elasticity"]
    depth = a.d_max * 0.35
    xs = [a.xl0 - a.t, a.cx, a.xr0 + a.t]
    rig.zone(poly=[(x, a.floor_y(x) + a.t) for x in xs] + [(x, a.floor_y(x) - depth) for x in reversed(xs)],
             kind="ice", damping=0.0)


def centre_magnet(rig, space, style, balls, w, h):
    """L67: a magnet under the middle of the floor (World 3's law, pull 1 x
    gravity at its peak), reaching most of the way to the walls: every
    marble is dragged in toward the middle while the walls close."""
    from ...stagekit import MAGNET_PULL
    a = fit(rig, space, balls)
    core = w * 0.045
    soft = core + w * MARBLE_R
    reach = float(rig.knob("reach", 0.42)) * w
    y = a.fy - a.t - core - 2.0
    style.magnets.append((a.cx, y, core, soft, reach, float(rig.knob("pull", MAGNET_PULL))))


def sudden_death_duel(rig, space, style, balls, w, h):
    """L68: two marbles in the arena with trapdoors (the `arenatrap` stage):
    the first one out loses. The walls alone gave the heavier marble of the
    pair 75-90% of duels (it wins every shove) and the panels alone gave the
    lighter one 69%; together, with the panels from 9 s, it is a duel
    (docs/06, World 7)."""
    fit(rig, space, balls, overshoot=0.6, first_step=FIRST_STEP_S, trap_from=9.0, trap_share=0.25)


def fan_arena_shape(rig, space, style, balls, w, h):
    """L69: the arena on a W-shaped floor (the `arenaw` stage: two valleys
    either side of a ridge), a stand-in for the fan-voted shape; the walls
    ride the floor down into the valleys and up onto the ridge."""
    fit(rig, space, balls)


def mega_arena(rig, space, style, balls, w, h):
    """L70: walls, pushers and trapdoors (the `arenatrap` stage, jabbing)."""
    if not w2.panels_of(rig):
        raise ValueError("mega-arena needs the arenatrap stage")
    # Ten marbles: no slams on the steps (the jabs hit), the stage's later
    # first step, panels from 7 s and jabs from 6 s (docs/06, World 7).
    a = fit(rig, space, balls, overshoot=0.0, trap_from=7.0, jab_from=6.0, jab_depth=0.35)
    _pushers(rig, a)


def repulsion_arena(rig, space, style, balls, w, h):
    """L77: World 8's push between every pair of marbles (`repel`, drawn) in
    the shrinking arena."""
    from .repel import repel
    fit(rig, space, balls)
    repel(rig)
