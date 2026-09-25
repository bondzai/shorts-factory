"""Mechanics: what a section can do besides being in the way.

The stage kit's sections are shapes. The worlds after World 1 need things a
shape cannot say: a pit that takes a marble out of the race, a magnet that
flips at halfway, ice, a gate only one colour may pass, marbles that push
each other apart, a blackout. This module is the one place those live, as
hooks on a **rig** — one per simulated round — that a section reaches with
`rig_of(style)`:

    def timer_trap(space, w, top, bottom, rng, style):     # a stagekit section
        rig = rig_of(style)
        rig.at("trap_open", t=rig.knob("open_at", 6.0), before=False, after=True)
        rig.out_zone((x0, bottom, x1, top), when="trap_open", event="trap_catch")
        ...

Four rules keep it honest (docs/10-mechanics.md says them at length):

1. **Opt-in.** A rig nobody registers anything on does nothing: the
   simulation takes exactly the path it took before this module existed,
   and a race without mechanics is byte-identical (tests/test_mechanics.py
   pins it).
2. **Deterministic.** A mechanism's random choices come from `rig.rng`, a
   stream derived from the round's seed and nothing else, so adding a
   mechanic never moves the build's own draws.
3. **Recorded.** Everything that changes over time is a *clock*, evaluated
   once a frame from state and recorded, so the renderers — live or redrawn
   from a trace — read a value, never re-run pymunk.
4. **Never steered** (docs/08 rule 2.4). A clock may react to the race —
   who leads, how far along it is — but nothing here may take an entrant's
   identity as a reason. `rig.rng` may pick a colour; a section may not pick
   *the* colour that makes a named marble lose.

Coordinates are pymunk's (y up). Times are seconds from the start of the
simulation, before the opening skip; the recording shifts to the clip's clock.
"""

from __future__ import annotations

import json
import math
import random
from dataclasses import dataclass, field
from typing import Any, Callable

import pymunk

RIG_SALT = 0x3C6EF372
MAX_ENTRANTS = 12  # one collision bit each, below DOOR_BIT; also a readable field
DOOR_BIT = 1 << 20
ALL_BITS = 0xFFFFFFFF
FINISH_Y = 110.0  # where a race's line is, in sim px from the bottom (simulate.py)

# Surfaces: friction on a segment, damping (1/s) inside a region. Ice is
# nearly frictionless and bouncier; sand grips and drags; a cobweb only drags.
SURFACES: dict[str, dict[str, Any]] = {
    "ice": {"friction": 0.02, "elasticity": 0.55, "damping": 0.0},
    "sand": {"friction": 0.95, "elasticity": 0.12, "damping": 1.4},
    "cobweb": {"friction": None, "elasticity": None, "damping": 3.0},
    "thin_ice": {"friction": 0.03, "elasticity": 0.40, "damping": 0.0},
    "mud": {"friction": 0.80, "elasticity": 0.08, "damping": 2.2},
    # Ice going soft (World 5's melting rounds): grips some, drags some.
    "slush": {"friction": 0.35, "elasticity": 0.20, "damping": 0.25},
}


@dataclass
class Frame:
    """What a clock or a hook sees once a frame, before the step."""

    frame: int
    t: float
    progress: float  # 0..1: how far the leader has come, never goes back
    names: list[str]
    positions: list[tuple[float, float]]
    alive: list[bool]  # False once eliminated
    finished: set[str]
    leader: int | None  # index of the lowest marble still racing
    values: dict[str, Any]  # every clock's value this frame (those evaluated so far)
    rig: "Rig"

    def value(self, name: str, default: Any = None) -> Any:
        return self.values.get(name, default)


@dataclass
class _Zone:
    kind: str
    rect: tuple[float, float, float, float] | None = None
    poly: list[tuple[float, float]] | None = None
    when: str | None = None
    out: bool = False
    event: str | None = None
    label: str = "out"
    damping: float = 0.0
    friction: float | None = None
    first_only: bool = False
    victim: int | None = None
    show: bool = True
    appear: bool = False  # drawn only while `when` is truthy (a surface a die rolls)

    def contains(self, x: float, y: float) -> bool:
        if self.rect is not None:
            x0, y0, x1, y1 = self.rect
            return min(x0, x1) <= x <= max(x0, x1) and min(y0, y1) <= y <= max(y0, y1)
        return _in_poly(x, y, self.poly or [])


@dataclass
class _Breakable:
    shape: Any
    a: tuple[float, float]
    b: tuple[float, float]
    kind: str
    thickness: float
    need: float  # mass-seconds of contact it takes
    load: float = 0.0
    cracked: int | None = None
    broke: int | None = None


@dataclass
class _Door:
    shape: Any
    a: tuple[float, float]
    b: tuple[float, float]
    closed: str | None
    passes: Any  # None, a list of entrant ids, or a clock name
    color: tuple[int, int, int] | None
    filter_now: Any = None


@dataclass
class _Wall:
    body: Any
    a: tuple[float, float]
    b: tuple[float, float]
    offset: str  # clock name whose value is [dx, dy]


@dataclass
class _PairForce:
    strength: float
    reach: float
    soft: float
    trait: str
    when: str | None
    skip_immune: bool = True
    newton: bool = False


class Rig:
    """One round's mechanics. Built empty by the simulation; sections and a
    level's `section` mechanic register on it; the simulation drives it."""

    def __init__(self, *, seed: int = 0, w: float = 540, h: float = 960, fps: int = 30,
                 params: dict | None = None, round_index: int = 0):
        self.seed, self.w, self.h, self.fps = seed, w, h, fps
        self.params = dict(params or {})
        self.round = round_index
        self._rng: random.Random | None = None
        self.mirrored = False
        # registrations
        self.clocks: list[tuple[str, Callable[[Frame], Any]]] = []
        self.zones: list[_Zone] = []
        self.surfaces: list[dict] = []
        self.breakables: list[_Breakable] = []
        self.doors: list[_Door] = []
        self.walls: list[_Wall] = []
        self.forces: list[_PairForce] = []
        self.effects: list[dict] = []
        self.hooks: list[Callable[[Frame], None]] = []
        self.magnet_clock: str | None = None
        self.magnet_tracker: str | None = None
        self.finish_y: float | None = FINISH_Y
        # Clocks that hold the field on purpose (a start gate, a dice hold):
        # while one is truthy a field at rest is waiting, not stalled.
        self.holds: list[str] = []
        # A mechanic may cut the clip to fewer rounds than `params.rounds`
        # (a die that sets the round count); read by sandbox.race_rounds.
        self.clip_rounds: int | None = None
        fmt = self.params.get("format")
        self.elimination = fmt in ("elimination", "last_standing")
        self.win = str(self.params.get("win") or ("last_standing" if fmt == "last_standing" else "first_across"))
        if self.win not in ("first_across", "last_standing"):
            raise ValueError(f"win {self.win!r}: use first_across or last_standing")
        # run state
        self.space: pymunk.Space | None = None
        self.balls: list = []
        self.names: list[str] = []
        self.alive: list[bool] = []
        self.gone: dict[str, int] = {}
        self.events: list[tuple[int, str, int | None, dict]] = []
        self.timeline: dict[str, list[list]] = {}
        self.values: dict[str, Any] = {}
        self.progress = 0.0
        self.finished: set[str] = set()
        self._base_friction: list[float] = []
        self._inside: list[list[bool]] = []
        self._frame = 0
        self._gravity = 0.0

    # --- what a section reads ------------------------------------------------------

    @property
    def rng(self) -> random.Random:
        """The mechanics' own random stream: from the seed, apart from the build's."""
        if self._rng is None:
            self._rng = random.Random((self.seed ^ RIG_SALT) + 7 * self.round)
        return self._rng

    def knob(self, name: str, default: Any = None) -> Any:
        """A section's setting from the level: `params.mechanics.<name>`."""
        table = self.params.get("mechanics") or {}
        return table.get(name, default) if isinstance(table, dict) else default

    @property
    def live(self) -> bool:
        """Anything registered. A rig that is not live changes nothing."""
        return bool(self.clocks or self.zones or self.surfaces or self.breakables or self.doors
                    or self.walls or self.forces or self.effects or self.hooks or self.magnet_clock
                    or self.magnet_tracker
                    or self.finish_y != FINISH_Y or self.elimination or self.holds)

    def _pt(self, p) -> tuple[float, float]:
        return (float(p[0]), float(p[1]))

    # --- clocks --------------------------------------------------------------------

    def clock(self, name: str, fn: Callable[[Frame], Any]) -> str:
        """A value that changes over the race, evaluated once a frame (in the
        order registered) and recorded. `fn(frame) -> JSON value`."""
        if any(n == name for n, _ in self.clocks):
            raise ValueError(f"clock {name!r} is already registered")
        self.clocks.append((name, fn))
        return name

    def at(self, name: str, *, t: float | None = None, progress: float | None = None,
           before: Any = False, after: Any = True) -> str:
        """`before` until time t (s) or race fraction `progress`, then `after`."""
        if (t is None) == (progress is None):
            raise ValueError("at() wants exactly one of t or progress")
        if t is not None:
            return self.clock(name, lambda f: after if f.t >= t else before)
        return self.clock(name, lambda f: after if f.progress >= progress else before)

    def cycle(self, name: str, period: float, *, on: float = 0.5, phase: float = 0.0,
              values: tuple = (True, False)) -> str:
        """values[0] for the first `on` share of every `period` s, values[1] after."""
        return self.clock(name, lambda f: values[0] if ((f.t / period + phase) % 1.0) < on else values[1])

    def window(self, name: str, *, t0: float | None = None, t1: float | None = None,
               p0: float | None = None, p1: float | None = None) -> str:
        """True inside a time window [t0, t1) or a race-fraction window [p0, p1)."""
        if t0 is not None:
            return self.clock(name, lambda f: t0 <= f.t < (t1 if t1 is not None else math.inf))
        return self.clock(name, lambda f: (p0 or 0.0) <= f.progress < (p1 if p1 is not None else math.inf))

    def countdown(self, name: str, t: float) -> str:
        """Whole seconds left until t (ceil), then None: what an on-screen timer shows."""
        return self.clock(name, lambda f: math.ceil(t - f.t - 1e-9) if f.t < t else None)

    def on_frame(self, fn: Callable[[Frame], None]) -> None:
        """A hook run once a frame after the clocks, before the step. It may
        move kinematic bodies or call `emit`; it may not read identities to
        decide a result (docs/08 rule 2.4)."""
        self.hooks.append(fn)

    def hold(self, clock: str) -> str:
        """The field is held on purpose while `clock` is truthy (a closed
        start gate, a die still rolling): the stall check does not count
        those frames, because marbles waiting behind a door are not wedged."""
        self.holds.append(clock)
        return clock

    @property
    def holding(self) -> bool:
        return any(self.values.get(c) for c in self.holds)

    def emit(self, kind: str, index: int | None = None, **data) -> None:
        """An Event at the current frame (its kind is the section's to name)."""
        self.events.append((self._frame, kind, index, data))

    # --- elimination -----------------------------------------------------------------

    def out_zone(self, rect=None, *, poly=None, when: str | None = None, event: str | None = None,
                 label: str = "out", show: bool = True) -> None:
        """A region that takes a marble out of the race: once a marble's centre
        is inside (while clock `when` is truthy, or always) it is removed from
        the simulation at that frame, with an `eliminated` event (and `event`
        too, e.g. "trap_catch"). `rect` is (x0, y0, x1, y1)."""
        self.zones.append(_Zone(kind=label, rect=self._rect(rect), poly=self._poly(poly), when=when,
                                out=True, event=event, label=label, show=show))

    def eliminate(self, index: int, *, by: str = "out", event: str | None = None) -> None:
        """Take marble `index` out now (a hook may call this)."""
        if not self.alive[index]:
            return
        ball = self.balls[index]
        self.alive[index] = False
        self.gone[self.names[index]] = self._frame
        if self.space is not None:
            shapes = list(ball.body.shapes)
            self.space.remove(ball.body, *shapes)
        self.events.append((self._frame, "eliminated", index, {"by": by}))
        if event:
            self.events.append((self._frame, event, index, {}))

    # --- surfaces --------------------------------------------------------------------

    def surface(self, space, a, b, kind: str = "ice", *, thickness: float = 6.0,
                friction: float | None = None) -> Any:
        """A static segment with its own friction (ice, sand, mud...), drawn
        with the surface's texture."""
        spec = SURFACES[kind]
        a, b = self._pt(a), self._pt(b)
        seg = pymunk.Segment(space.static_body, a, b, thickness)
        seg.elasticity = spec["elasticity"] if spec["elasticity"] is not None else 0.46
        seg.friction = friction if friction is not None else (spec["friction"] if spec["friction"] is not None else 0.30)
        space.add(seg)
        self.surfaces.append({"a": list(a), "b": list(b), "kind": kind, "thickness": thickness})
        return seg

    def zone(self, rect=None, *, poly=None, kind: str = "sand", damping: float | None = None,
             friction: float | None = None, first_only: bool = False, when: str | None = None,
             event: str | None = None, show: bool = True, appear: bool = False) -> None:
        """A region that drags whoever is in it: `damping` (1/s, default the
        surface's) on velocity every substep, and the marble's own friction
        set to `friction` while inside. `first_only`: only the first marble to
        enter is ever affected (a cobweb), with `event` when it is caught.
        `appear`: drawn only while `when` is truthy, so a surface that is
        rolled for mid-race is not on screen before the roll."""
        spec = SURFACES.get(kind, {})
        self.zones.append(_Zone(kind=kind, rect=self._rect(rect), poly=self._poly(poly), when=when,
                                damping=float(damping if damping is not None else spec.get("damping") or 0.0),
                                friction=friction if friction is not None else None,
                                first_only=first_only, event=event, label=kind, show=show, appear=appear))

    def breakable(self, space, a, b, *, kind: str = "thin_ice", hold: tuple[float, float] = (0.8, 2.0),
                  thickness: float = 5.0) -> Any:
        """A segment that breaks under load: it takes a seeded amount of
        contact (seconds x mass, in units of a mid-sized marble) from
        `hold`, then is gone, with a `broke` event. Cracks show at half."""
        spec = SURFACES.get(kind, SURFACES["thin_ice"])
        a, b = self._pt(a), self._pt(b)
        seg = pymunk.Segment(space.static_body, a, b, thickness)
        seg.elasticity = spec["elasticity"] or 0.4
        seg.friction = spec["friction"] if spec["friction"] is not None else 0.3
        space.add(seg)
        self.breakables.append(_Breakable(seg, a, b, kind, thickness, self.rng.uniform(*hold)))
        return seg

    # --- per-entrant filters and forces ---------------------------------------------

    def door(self, space, a, b, *, closed: str | None = None, passes: Any = None,
             color: tuple[int, int, int] | None = None, thickness: float = 6.0) -> Any:
        """A barrier some marbles go through. Solid while clock `closed` is
        truthy (always, if None) — except for the entrants in `passes`: a list
        of ids, or a clock whose value is one. `color` lights it."""
        a, b = self._pt(a), self._pt(b)
        seg = pymunk.Segment(space.static_body, a, b, thickness)
        seg.elasticity, seg.friction = 0.46, 0.30
        space.add(seg)
        self.doors.append(_Door(seg, a, b, closed, passes, tuple(color) if color else None))
        return seg

    def pair_force(self, strength: float, *, reach: float = 4.0, soft: float = 1.0,
                   trait: str = "charge", when: str | None = None, skip_immune: bool = True,
                   newton: bool = False) -> None:
        """Every pair of marbles pushes apart (strength > 0) or pulls together
        (< 0), in multiples of the stage's gravity at contact, falling to zero
        at `reach` x the pair's summed radii (the magnet's softened law). Each
        marble's share is its cast trait `trait` (default 1). `when`: a clock
        whose value (bool or number) scales it. force_immune marbles skip it
        unless `skip_immune` is False (World 8: marble-to-marble repulsion is
        not a field an immune marble ignores). `newton`: the pair's forces
        are equal and opposite, so each marble's share of the push goes as
        the other's mass over their mean (two equal marbles move as without
        it; the heavier of a pair moves less)."""
        self.forces.append(_PairForce(float(strength), float(reach), float(soft), trait, when,
                                      bool(skip_immune), bool(newton)))

    def magnet_polarity(self, clock: str) -> None:
        """Every magnet's pull times this clock's value: 1 pulls, -1 pushes.
        The value may also be a list, one number per magnet in
        `style.magnets` order, so one magnet can push while the rest pull."""
        self.magnet_clock = clock

    def magnet_track(self, clock: str) -> None:
        """Magnets that move: the clock's value is a list, one [x, y] per
        magnet in `style.magnets` order (None: where it was built). The field
        is where the clock says, and so is the drawing and the `launched`
        test. Carrying the core is the section's job (a kinematic body)."""
        self.magnet_tracker = clock

    def moving_wall(self, space, a, b, offset: str, *, thickness: float = 6.0) -> Any:
        """A wall that moves by clock `offset`'s value [dx, dy] (px): walls
        closing in, a pusher. Kinematic, so it shoves what it meets."""
        a, b = self._pt(a), self._pt(b)
        body = pymunk.Body(body_type=pymunk.Body.KINEMATIC)
        body.position = (0.0, 0.0)
        seg = pymunk.Segment(body, a, b, thickness)
        seg.elasticity, seg.friction = 0.40, 0.30
        space.add(body, seg)
        self.walls.append(_Wall(body, a, b, offset))
        return body

    # --- the look ------------------------------------------------------------------

    def effect(self, kind: str, **data) -> None:
        """A render effect: "blackout" (clock=...: marbles hidden while it is
        truthy, sound goes on), "countdown" (clock=..., at=(x, y): the clock's
        value drawn as a number), "die" (clock=... or value=..., at=(x, y),
        size=px, layer="top"|"under", tints={face: rgb}: a die face; the
        clock's value is None (not drawn), a face number, or {"f": face,
        "s": "roll"|"set"|"lit"|"dim"}), "prop" (clock=..., at=(x, y), radius=,
        color=[r, g, b]: a marble drawn there while the clock is truthy — a
        picture with no body, never an entrant), "field" (clock=..., reach=k,
        sign=1 | -1: while the clock is truthy (always, with none) every pair
        of marbles closer than k x their summed radii is drawn with the pair
        force between them — facing arcs that brighten as they close when it
        pushes, a dotted tether when it pulls; World 8). Both renderers draw
        them."""
        if kind not in ("blackout", "countdown", "die", "prop", "field"):
            raise ValueError(f"no effect {kind!r}; have blackout, countdown, die, prop, field")
        if "at" in data:
            data["at"] = list(self._pt(data["at"]))
        self.effects.append({"kind": kind, **data})

    def no_finish_line(self) -> None:
        """A stage with no line (an arena): the result is who is left."""
        self.finish_y = None

    # --- geometry helpers ------------------------------------------------------------

    def _rect(self, rect):
        if rect is None:
            return None
        x0, y0, x1, y1 = (float(v) for v in rect)
        return (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))

    def _poly(self, poly):
        return [self._pt(p) for p in poly] if poly else None

    def mirror_registered(self) -> None:
        """Reflect everything registered about x = w/2: the round's `mirror`,
        applied once the stage, its sections, the level's mechanic and the
        marbles are all in place (physics/build.py), so none of them has to
        know. Register nothing after it."""
        w = self.w
        for z in self.zones:
            if z.rect is not None:
                x0, y0, x1, y1 = z.rect
                z.rect = (w - x1, y0, w - x0, y1)
            if z.poly:
                z.poly = [(w - x, y) for x, y in z.poly]
        for s in self.surfaces:
            s["a"], s["b"] = [w - s["a"][0], s["a"][1]], [w - s["b"][0], s["b"][1]]
        for br in self.breakables:
            br.a, br.b = (w - br.a[0], br.a[1]), (w - br.b[0], br.b[1])
        for d in self.doors:
            d.a, d.b = (w - d.a[0], d.a[1]), (w - d.b[0], d.b[1])
        for e in self.effects:
            if "at" in e:
                e["at"] = [w - e["at"][0], e["at"][1]]
        if self.walls:
            raise ValueError("a moving wall cannot be mirrored; register it after the mirror")
        self.mirrored = True

    # --- driven by the simulation ----------------------------------------------------

    def bind(self, balls: list) -> None:
        """The marbles are placed: give each a collision bit if a door needs it."""
        if len(balls) > MAX_ENTRANTS:
            raise ValueError(f"{len(balls)} marbles; a race holds at most {MAX_ENTRANTS}")
        self.balls = balls
        self.names = [b.name for b in balls]
        self.alive = [True] * len(balls)
        self._inside = [[False] * len(balls) for _ in self.zones]
        self._base_friction = [next(iter(b.body.shapes)).friction for b in balls]
        if self.doors:
            for i, b in enumerate(balls):
                for shape in b.body.shapes:
                    shape.filter = pymunk.ShapeFilter(categories=1 << i, mask=ALL_BITS)

    def start(self, space, gravity: float) -> None:
        self.space = space
        self._gravity = gravity
        self._start_y = max((b.body.position.y for b in self.balls), default=self.h)

    def _progress(self, positions) -> tuple[float, int | None]:
        live = [i for i, ok in enumerate(self.alive) if ok and self.names[i] not in self.finished]
        if not live:
            return self.progress, None
        leader = min(live, key=lambda i: positions[i][1])
        end = self.finish_y if self.finish_y is not None else 0.0
        span = max(self._start_y - end, 1.0)
        return max(self.progress, min(1.0, (self._start_y - positions[leader][1]) / span)), leader

    def before_frame(self, frame: int) -> None:
        self._frame = frame
        positions = [(b.body.position.x, b.body.position.y) for b in self.balls]
        self.progress, leader = self._progress(positions)
        ctx = Frame(frame=frame, t=frame / self.fps, progress=self.progress, names=self.names,
                    positions=positions, alive=list(self.alive), finished=set(self.finished),
                    leader=leader, values=self.values, rig=self)
        for name, fn in self.clocks:
            value = fn(ctx)
            value = json.loads(json.dumps(value))  # what the trace will hold, exactly
            self.values[name] = value
            line = self.timeline.setdefault(name, [])
            if not line or line[-1][1] != value:
                line.append([frame, value])
        for hook in self.hooks:
            hook(ctx)
        for d in self.doors:
            solid = True if d.closed is None else bool(self.values.get(d.closed))
            passes = self.values.get(d.passes) if isinstance(d.passes, str) else d.passes
            through = 0
            for who in passes or ():
                if who in self.names:
                    through |= 1 << self.names.index(who)
            mask = (ALL_BITS & ~through) if solid else 0
            if d.filter_now != mask:
                d.shape.filter = pymunk.ShapeFilter(categories=DOOR_BIT, mask=mask)
                d.filter_now = mask
        for w in self.walls:
            dx, dy = self.values.get(w.offset) or (0.0, 0.0)
            here = w.body.position
            w.body.velocity = ((dx - here.x) * self.fps, (dy - here.y) * self.fps)
        # Surfaces with friction: a marble's own friction while it is inside.
        for zi, z in enumerate(self.zones):
            if z.out:
                continue
            on = z.when is None or bool(self.values.get(z.when))
            for i, (x, y) in enumerate(positions):
                inside = on and self.alive[i] and z.contains(x, y)
                if inside and z.first_only:
                    if z.victim is None:
                        z.victim = i
                        if z.event:
                            self.events.append((frame, z.event, i, {}))
                    inside = z.victim == i
                self._inside[zi][i] = inside
        if any(z.friction is not None for z in self.zones if not z.out):
            for i, b in enumerate(self.balls):
                want = self._base_friction[i]
                for zi, z in enumerate(self.zones):
                    if not z.out and z.friction is not None and self._inside[zi][i]:
                        want = z.friction
                for shape in b.body.shapes:
                    if shape.friction != want:
                        shape.friction = want

    @property
    def pushes(self) -> bool:
        """Whether the substep force path is needed."""
        return bool(self.forces or self.magnet_clock or self.magnet_tracker
                    or any(z.damping for z in self.zones if not z.out))

    def substep(self, style, immune: list[bool], gravity_mag: float, pull_cap: float, dt: float) -> None:
        """Forces for one substep: magnets (with polarity), pair forces, drag.
        `body.force` is set, not accumulated, as the magnet code always did."""
        n = len(self.balls)
        ax, ay = [0.0] * n, [0.0] * n
        pos = [b.body.position for b in self.balls]
        polarity = self.values.get(self.magnet_clock, 1) if self.magnet_clock else 1
        if style.magnets and (isinstance(polarity, list) or self.magnet_tracker):
            # Per-magnet polarity or moving magnets: each field times its own
            # sign, at its own place; the sum capped at the strongest |sign|.
            track = self.values.get(self.magnet_tracker) if self.magnet_tracker else None
            from .stagekit import magnet_accel
            fields = []
            for k, (mx, my, _core, soft, reach, pull) in enumerate(style.magnets):
                raw = (polarity[k] if k < len(polarity) else 1) if isinstance(polarity, list) else polarity
                sign = _sign(raw)
                if track and k < len(track) and track[k] is not None:
                    mx, my = track[k]
                if sign:
                    fields.append((mx, my, soft, reach, pull * gravity_mag * sign, abs(sign)))
            cap = pull_cap * max((f[5] for f in fields), default=0.0)
            for i in range(n):
                if immune[i] or not self.alive[i]:
                    continue
                px, py = pos[i]
                sx = sy = 0.0
                for mx, my, soft, reach, peak, _ in fields:
                    dax, day = magnet_accel(mx - px, my - py, soft, reach, peak)
                    sx += dax
                    sy += day
                total = math.hypot(sx, sy)
                if total > cap:
                    sx, sy = sx * cap / total, sy * cap / total
                ax[i], ay[i] = sx, sy
        elif style.magnets:
            sign = 1.0
            if self.magnet_clock:
                value = self.values.get(self.magnet_clock, 1)
                sign = float(value) if not isinstance(value, bool) else (1.0 if value else 0.0)
            from .stagekit import magnet_accel  # stagekit imports this module
            for i in range(n):
                if immune[i] or not self.alive[i]:
                    continue
                px, py = pos[i]
                sx = sy = 0.0
                for mx, my, _core, soft, reach, pull in style.magnets:
                    dax, day = magnet_accel(mx - px, my - py, soft, reach, pull * gravity_mag)
                    sx += dax
                    sy += day
                total = math.hypot(sx, sy)
                if total > pull_cap:
                    sx, sy = sx * pull_cap / total, sy * pull_cap / total
                ax[i], ay[i] = sx * sign, sy * sign
        for f in self.forces:
            scale = 1.0
            if f.when:
                value = self.values.get(f.when)
                scale = (1.0 if value else 0.0) if isinstance(value, bool) or value is None else float(value)
            if not scale:
                continue
            from .stagekit import magnet_accel
            for i in range(n):
                if not self.alive[i]:
                    continue
                for j in range(i + 1, n):
                    if not self.alive[j]:
                        continue
                    ri, rj = self.balls[i].radius, self.balls[j].radius
                    soft, reach = f.soft * (ri + rj), f.reach * (ri + rj)
                    qi = float(self.balls[i].traits.get(f.trait, 1.0))
                    qj = float(self.balls[j].traits.get(f.trait, 1.0))
                    peak = f.strength * scale * qi * qj * gravity_mag
                    # magnet_accel pulls toward (dx, dy); a positive strength repels.
                    dax, day = magnet_accel(pos[j].x - pos[i].x, pos[j].y - pos[i].y, soft, reach, -peak)
                    ki = kj = 1.0
                    if f.newton:
                        mi, mj = self.balls[i].body.mass, self.balls[j].body.mass
                        ki, kj = 2 * mj / (mi + mj), 2 * mi / (mi + mj)
                    if not (immune[i] and f.skip_immune):
                        ax[i] += dax * ki
                        ay[i] += day * ki
                    if not (immune[j] and f.skip_immune):
                        ax[j] -= dax * kj
                        ay[j] -= day * kj
        for i, b in enumerate(self.balls):
            if not self.alive[i]:
                continue
            if style.magnets or self.forces:
                b.body.force = (b.body.mass * ax[i], b.body.mass * ay[i])
            drag = sum(z.damping for zi, z in enumerate(self.zones) if not z.out and self._inside[zi][i])
            if drag:
                b.body.velocity = b.body.velocity * math.exp(-drag * dt)

    def after_frame(self, frame: int) -> None:
        """Out-zones and breakables, from where the marbles are after the step."""
        for z in self.zones:
            if not z.out or (z.when is not None and not self.values.get(z.when)):
                continue
            for i, b in enumerate(self.balls):
                if self.alive[i] and self.names[i] not in self.finished and z.contains(*b.body.position):
                    self.eliminate(i, by=z.label, event=z.event)
        for br in self.breakables:
            if br.broke is not None:
                continue
            touching = [i for i, b in enumerate(self.balls) if self.alive[i]
                        and _seg_dist(b.body.position, br.a, br.b) <= b.radius + br.thickness + 1.5]
            if not touching:
                continue
            br.load += sum(self.balls[i].body.mass for i in touching) / (1.6 * self.fps)
            if br.cracked is None and br.load >= br.need / 2:
                br.cracked = frame
            if br.load >= br.need:
                br.broke = frame
                if self.space is not None:
                    self.space.remove(br.shape)
                self.events.append((frame, "broke", touching[0], {"kind": br.kind}))

    def mark_finished(self, name: str) -> None:
        self.finished.add(name)

    @property
    def contenders(self) -> list[int]:
        return [i for i, ok in enumerate(self.alive) if ok and self.names[i] not in self.finished]

    @property
    def all_gone(self) -> bool:
        return bool(self.balls) and not any(self.alive)

    # --- recorded --------------------------------------------------------------------

    def snapshot(self, skip: int = 0) -> dict:
        """Everything the renderers need, on the clip's clock (frames after
        the opening skip), as plain JSON: this is `style.mech`."""
        at = lambda f: None if f is None else max(0, f - skip)  # noqa: E731
        mech: dict[str, Any] = {}
        if self.timeline:
            clocks = {}
            for name, line in self.timeline.items():
                kept = [p for p in line if p[0] >= skip]
                earlier = [p for p in line if p[0] < skip]
                if earlier and (not kept or kept[0][0] > skip):
                    kept.insert(0, [skip, earlier[-1][1]])
                clocks[name] = [[p[0] - skip, p[1]] for p in kept]
            mech["clocks"] = clocks
        zones = [{"kind": z.kind, "out": z.out, "when": z.when,
                  **({"rect": list(z.rect)} if z.rect else {"poly": [list(p) for p in z.poly or []]}),
                  **({"appear": True} if z.appear else {})}
                 for z in self.zones if z.show]
        if zones:
            mech["zones"] = zones
        if self.surfaces:
            mech["surfaces"] = self.surfaces
        if self.breakables:
            mech["breakables"] = [{"a": list(b.a), "b": list(b.b), "kind": b.kind, "thickness": b.thickness,
                                   "cracked": at(b.cracked), "broke": at(b.broke)} for b in self.breakables]
        if self.doors:
            mech["doors"] = [{"a": list(d.a), "b": list(d.b), "closed": d.closed,
                              "passes": d.passes, "color": list(d.color) if d.color else None}
                             for d in self.doors]
        if self.walls:
            mech["walls"] = [{"a": list(w.a), "b": list(w.b), "offset": w.offset} for w in self.walls]
        if self.gone:
            mech["gone"] = {name: at(f) for name, f in self.gone.items()}
        if self.effects:
            mech["effects"] = self.effects
        if self.magnet_clock:
            mech["magnet_clock"] = self.magnet_clock
        if self.magnet_tracker:
            mech["magnet_track"] = self.magnet_tracker
        if self.finish_y is None:
            mech["no_finish"] = True
        return json.loads(json.dumps(mech, sort_keys=True))

    def shifted_events(self, skip: int) -> list[tuple[int, str, int | None, dict]]:
        return [(max(0, f - skip), kind, i, data) for f, kind, i, data in self.events]


def rig_of(style) -> Rig:
    """The rig a section registers on. The simulation attaches one to the
    style before the stage is built; a builder called on its own (a test, a
    preview) gets a fresh one so a section never has to ask."""
    rig = getattr(style, "rig", None)
    if rig is None:
        rig = Rig(seed=getattr(style, "seed", 0) or 0)
        style.rig = rig
    return rig


# --- reading a recording (both renderers) -------------------------------------------------

def clock_at(mech: dict, name: str | None, frame: int, default: Any = None) -> Any:
    """A recorded clock's value at a frame of the clip."""
    if not name:
        return default
    line = (mech.get("clocks") or {}).get(name)
    if not line:
        return default
    value = default
    for f, v in line:
        if f > frame:
            break
        value = v
    return value


def hidden(mech: dict, name: str, frame: int) -> bool:
    """Not drawn: eliminated by this frame, or inside a blackout."""
    gone = (mech.get("gone") or {}).get(name)
    return (gone is not None and frame >= gone) or blackout(mech, frame)


def blackout(mech: dict, frame: int) -> bool:
    return any(e["kind"] == "blackout" and clock_at(mech, e.get("clock"), frame) for e in mech.get("effects") or ())


def door_state(mech: dict, door: dict, frame: int) -> tuple[bool, list[str]]:
    """(closed, who passes) at a frame."""
    closed = True if door.get("closed") is None else bool(clock_at(mech, door["closed"], frame))
    passes = door.get("passes")
    if isinstance(passes, str):
        passes = clock_at(mech, passes, frame) or []
    return closed, list(passes or [])


def _sign(value: Any) -> float:
    """A polarity clock's value as a number: True 1, False/None 0."""
    if isinstance(value, bool) or value is None:
        return 1.0 if value else 0.0
    return float(value)


def magnets_at(style, mech: dict | None, frame: int) -> list[tuple]:
    """Every magnet at a frame of the clip, as the renderers draw it and
    `launched` measures it: (x, y, core, soft, reach, pull, polarity), with a
    moving magnet where its track says and each magnet's own polarity."""
    polarity = (clock_at(mech, mech.get("magnet_clock"), frame, 1) or 0) if mech else 1
    track = clock_at(mech, mech.get("magnet_track"), frame) if mech else None
    out = []
    for k, (mx, my, core, soft, reach, pull) in enumerate(style.magnets):
        p = (polarity[k] if k < len(polarity) else 1) if isinstance(polarity, list) else polarity
        if track and k < len(track) and track[k] is not None:
            mx, my = track[k]
        out.append((mx, my, core, soft, reach, pull, p or 0))
    return out


def wall_offset(mech: dict, wall: dict, frame: int) -> tuple[float, float]:
    dx, dy = clock_at(mech, wall["offset"], frame) or (0.0, 0.0)
    return float(dx), float(dy)


def _in_poly(x: float, y: float, poly) -> bool:
    inside = False
    n = len(poly)
    for k in range(n):
        (x1, y1), (x2, y2) = poly[k], poly[(k + 1) % n]
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / ((y2 - y1) or 1e-12) + x1:
            inside = not inside
    return inside


def _seg_dist(p, a, b) -> float:
    px, py = p
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    length2 = dx * dx + dy * dy
    u = 0.0 if length2 == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length2))
    return math.hypot(px - (ax + u * dx), py - (ay + u * dy))


# --- teams -----------------------------------------------------------------------------------

def shade(color: tuple[int, int, int], k: int) -> tuple[int, int, int]:
    """The k-th marble of a team (1-based): the persona's colour, then a
    lighter one, a darker one, then lighter and darker again, so twins read
    apart at a glance and still read as one team."""
    steps = [0.0, 0.42, -0.38, 0.62, -0.55, 0.25]
    s = steps[(k - 1) % len(steps)]
    if s >= 0:
        return tuple(int(round(c + (255 - c) * s)) for c in color)  # type: ignore[return-value]
    return tuple(int(round(c * (1 + s))) for c in color)  # type: ignore[return-value]


def expand_teams(cast: list[dict] | None, teams: dict | None) -> list[dict] | None:
    """`teams: {blaze: 2, tide: 2}` -> two marbles per persona, ids `blaze.1`,
    `blaze.2`, colours shaded, each carrying `team`. A persona the table does
    not name runs one marble (still `moss.1`, so every id reads the same way)."""
    if not teams or not cast:
        return cast
    unknown = sorted(set(teams) - {e["id"] for e in cast})
    if unknown:
        raise ValueError(f"teams names {unknown}, who are not in the race")
    out = []
    for e in cast:
        n = int(teams.get(e["id"], 1))
        if n < 1:
            raise ValueError(f"teams: {e['id']} needs at least one marble")
        base = e["color"]
        rgb = tuple(int(str(base).lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
        for k in range(1, n + 1):
            out.append({**e, "id": f"{e['id']}.{k}", "color": "#%02X%02X%02X" % shade(rgb, k), "team": e["id"]})
    if len(out) > MAX_ENTRANTS:
        raise ValueError(f"teams make {len(out)} marbles; a race holds at most {MAX_ENTRANTS}")
    return out
