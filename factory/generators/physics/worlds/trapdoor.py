"""World 2, Trapdoor Roulette (Season 0, L11-L20): panels that take a marble out.

The stage kit's `trap` holds a marble and lets it go. This world's trapdoor
is the other kind: a **panel** — a lid over a pit — that, while it is open,
drops whoever lands on it out of the race. Everything in World 2 is one
panel used ten ways, so the look is learned once: a light lid in a dark box,
the box's rim lighting red while the lid is open.

A panel is built by a stagekit section here (`trap1`, `trap2`, `trap3`: one,
two or three panels at the foot of a band, pegs above) and opened by a
level's mechanic, which sets each panel's `opener(frame) -> bool`. Nothing
here edits the simulation: a panel is a `rig.door` (the lid, solid while its
`shut` clock is true), two `rig.out_zone`s (the pit, `trap_catch`), static
walls, and two recorded clocks. With no mechanic a panel cycles on a seeded
clock, so a stage named on its own still races.

The mechanics (registered in physics/registry.py, weight-0 stages beside them):

  timer-trap          one panel, opened at a hidden seeded time (L11)
  trap-timer-overlay  the same, with the countdown drawn over the pit (L18)
  trap-sequence       three panels in sequence, each opening as the leader
                      comes down to it: early arrivals find it open (L12)
  finish-trapdoor     a panel under the run-in's throat, open for a moment
                      once the first marble is through the throat (L13)
  fake-panels         six panels alike; two are real, open and stay open (L14)
  leader-sensor-trap  a row of three: when the leader crosses the halfway
                      sensor, the panel under it opens (L15)
  spiral-bowl-reverse a bowl draining into a centre trapdoor; no line, the
                      last one in wins (L16)
  relay-legs          team relay: the second marble waits in a pen at the
                      halfway gate and is let out when its teammate reaches
                      it; one panel per leg (L17)
  five-trapdoors      five panels on their own cycles (L19)
  trap-gauntlet       seven panels on staggered cycles (L20)

Docs/08 rule 2.4 holds throughout: an opener reads the clock, how far the
race has come, or where the leader is — never who anyone is. The relay reads
which team a marble runs for, because a relay is a rule every team races
under, not a reason for one of them to lose.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from ... import stagekit
from ...mechanics import rig_of
from ...stagekit import MARBLE_R, _cornered, _peg, _wall, marble_room

# --- the panel ---------------------------------------------------------------------------

# A lid's rise over its run. A shut lid is a floor a marble must leave, and
# 0.46 is the slope the kit has seen marbles rest on; half again is shed.
LID_SLOPE = 0.5
# The pit's depth, in radii of the biggest marble. It only has to take a
# marble's centre below the lid line to count it out, and a deep box is a
# tall obstacle for everyone who goes round it.
PIT_DEPTH = 1.5
# Every lid the same colour, whatever it is for: a painted panel has to look
# exactly like a real one until a real one opens.
LID_TINT = 0.45
# Stagekit's rule for a gap a marble must pass: marble_room. The gaps beside
# and between panels are that plus a margin, because a lid sheds marbles into
# them two at a time.
GAP_SPARE = 1.12
# The bowl's slope where it meets the drain: past the 0.46 a marble rests
# on, so nothing waits anywhere in the bowl but on the drain's lid.
BOWL_LIP = 0.55
# Mud on the bowl's lower slopes, out to the curve's BOWL_MUD-th of five
# points, dragging at BOWL_DRAG per second (sand is 1.4, mud 2.2).
BOWL_MUD = 2
BOWL_DRAG = 1.6


@dataclass
class Panel:
    """One trapdoor: a lid over a pit, opened by `opener` (a level's mechanic)
    or, with none, by its seeded default cycle."""

    index: int
    x0: float
    x1: float
    lid: float      # y of the lid's low edge: the pit's mouth
    bottom: float   # y of the pit's floor
    rise: float     # the lid's high point above `lid`
    shape: str      # "roof" (high in the middle), "left" (low at x0), "right" (low at x1)
    row: int        # which band of panels, top first
    default: tuple[float, float, float] = (3.5, 0.35, 0.0)  # period s, open share, phase
    opener: Callable[[Any], bool] | None = None
    # Whether an open lid waits for a marble that is falling through it
    # (see `_is_open`); a mechanic may say when it should not.
    holds: Callable[[Any], bool] | None = None
    opened: bool = False
    waiting: set | None = None  # marbles an open lid is waiting for (`_is_open`)

    @property
    def cx(self) -> float:
        return (self.x0 + self.x1) / 2

    def surface(self, x: float) -> float:
        """The lid's height at x (inside [x0, x1])."""
        u = (x - self.x0) / max(self.x1 - self.x0, 1e-9)
        if self.shape == "roof":
            return self.lid + self.rise * (1.0 - abs(2.0 * u - 1.0))
        if self.shape == "left":
            return self.lid + self.rise * u
        if self.shape == "right":
            return self.lid + self.rise * (1.0 - u)
        return self.lid

    @property
    def top(self) -> float:
        return self.lid + self.rise

    @property
    def open_clock(self) -> str:
        return f"trapdoor{self.index}_open"

    @property
    def shut_clock(self) -> str:
        return f"trapdoor{self.index}_shut"


def panels_of(rig) -> list[Panel]:
    """The round's panels, in the order the stage built them (top band first)."""
    if not hasattr(rig, "trapdoors"):
        rig.trapdoors = []
    return rig.trapdoors


def cycling(period: float, share: float, phase: float, *, after: float = 0.0) -> Callable[[Any], bool]:
    """Open for the first `share` of every `period` seconds, offset by `phase`
    (0..1), and never before `after` seconds."""
    return lambda f: f.t >= after and ((f.t / period) + phase) % 1.0 < share


# No panel that opens on a clock or on the leader opens before this
# (simulation seconds; the clip opens 0.6 s in): a panel right under the
# start grid otherwise took marbles before the opening caption was off the
# screen — five of twelve gone in the gauntlet's first second — which is a
# lottery, not a race.
GRACE_S = 2.5


def _mix(a, b, share: float) -> tuple[int, int, int]:
    return tuple(int(round(x + (y - x) * share)) for x, y in zip(a, b))  # type: ignore[return-value]


def _announce(f) -> None:
    """`trap_opened` the first time each panel opens: a mechanism event, no one's result."""
    for p in panels_of(f.rig):
        if not p.opened and f.values.get(p.open_clock):
            p.opened = True
            f.rig.emit("trap_opened", None, panel=p.index)


def panel(space, w: float, style, x0: float, x1: float, bottom: float, shape: str, row: int) -> list:
    """Build one panel with its pit's floor at `bottom`; returns the pit's walls."""
    rig = rig_of(style)
    big = w * MARBLE_R
    lid = bottom + big * PIT_DEPTH
    run = (x1 - x0) / (2 if shape == "roof" else 1)
    rise = run * LID_SLOPE
    p = Panel(0, x0, x1, lid, bottom, rise, shape, row,
              default=(rig.rng.uniform(3.0, 4.0), 0.35, rig.rng.random()))
    left_top = lid + (rise if shape == "right" else 0.0)
    right_top = lid + (rise if shape == "left" else 0.0)
    t = style.thickness / 2
    walls = [((x0, left_top), (x0, bottom)), ((x0, bottom), (x1, bottom)), ((x1, bottom), (x1, right_top))]
    for a, b in walls:
        _wall(space, a, b, thickness=t)
    if shape == "roof":
        lids = [((x0, lid), (p.cx, lid + rise)), ((p.cx, lid + rise), (x1, lid))]
    elif shape == "left":
        lids = [((x0, lid), (x1, lid + rise))]
    else:
        lids = [((x0, lid + rise), (x1, lid))]
    _install(space, style, p, lids, t)
    return walls


def _install(space, style, p: Panel, lids: list, t: float) -> None:
    """Give a built pit its lid and its clocks, and arm it.

    The lid is a door, solid while `trapdoorN_shut`. Its opener is read
    through `trapdoorN_open`, which a level's mechanic sets after the stage
    is built; until one does, the panel cycles on its seeded default. The
    pit gets two out-zones. Drawn: the pit inside its walls, the rim lit
    while the lid is open. Not drawn and always armed: the whole mouth from
    wall centre to wall centre — a marble whose centre is below the lid line
    between the walls has fallen in, whether the lid is open now or shut on
    top of it. (Inset to the walls' faces, the bowl's drain let two marbles
    jam across its mouth, each hung on a wall's top edge just outside it.)"""
    rig = rig_of(style)
    panels = panels_of(rig)
    p.index = len(panels)
    panels.append(p)
    if len(panels) == 1:
        rig.on_frame(_announce)
    reach = rig.w * MARBLE_R + t + 2.0
    rig.clock(p.open_clock, lambda f, p=p: _is_open(f, p, reach))
    rig.clock(p.shut_clock, lambda f, p=p: not f.values.get(p.open_clock))
    colour = _mix(style.structure, (255, 255, 255), LID_TINT)
    for a, b in lids:
        rig.door(space, a, b, closed=p.shut_clock, color=colour, thickness=t)
    rig.out_zone((p.x0 + t + 1, p.bottom + t + 1, p.x1 - t - 1, p.lid - 1), when=p.open_clock,
                 event="trap_catch", label="trapdoor")
    rig.out_zone((p.x0, p.bottom, p.x1, p.lid - 1), event="trap_catch", label="trapdoor", show=False)


def _is_open(f, p: Panel, reach: float) -> bool:
    """The panel's opener, except that an open lid does not shut on a marble
    that is falling through it.

    At the gravity these stages run at (-30 to -45 px/s^2) a marble sitting
    on a lid needs 1.1-1.4 s to drop its centre below the lid line once the
    lid goes, and a lid that shut before then closed *through* the marble,
    which the solver resolves by shoving it back up on top. A marble on a
    cycling lid was lifted that way every cycle and crept along it for the
    rest of the race (the relay's first leg, seen at 8 s of 11). So when a
    lid is due to shut, the marbles still racing that are over the pit and
    within a marble of the lid are noted, and it stays open until they are
    through (or gone off it): whoever the lid was open under goes through.
    Only those: a first version held it open for anyone over the pit, and a
    stream arriving through the finish throat kept it open until all four
    were gone. `holds` lets a mechanic turn the wait off (the bowl, once its
    race is decided)."""
    want = bool(p.opener(f)) if p.opener else cycling(*p.default, after=GRACE_S)(f)
    if want or not f.values.get(p.open_clock):
        p.waiting = None
        return want
    if p.holds is not None and not p.holds(f):
        p.waiting = None
        return False

    def over(i: int) -> bool:
        x, y = f.positions[i]
        return (f.alive[i] and f.names[i] not in f.finished and p.x0 <= x <= p.x1
                and p.lid - reach <= y <= p.surface(x) + reach)

    if p.waiting is None:
        p.waiting = {i for i in range(len(f.positions)) if over(i)}
    p.waiting = {i for i in p.waiting if over(i)}
    if p.waiting:
        return True
    p.waiting = None
    return False


def _row(style) -> int:
    panels = panels_of(rig_of(style))
    return (max(p.row for p in panels) + 1) if panels else 0


def _pegs(space, w, top, low, rng, style, keep=()) -> None:
    """Offset rows of pegs from `top` down to `low`, at the pegs section's
    clearances, leaving out any peg inside a keep-out box (x0, y0, x1, y1)
    grown by its own radius."""
    room = marble_room(w)
    through = w * MARBLE_R * 2 * 1.1
    r = rng.uniform(6.5, 9.5)
    height = top - low
    if height < 0:
        return
    rows = max(1, int(height // rng.uniform(66, 72)) + 1)
    cols = max(3, min(rng.randint(6, 7), int((w - 60.0) // (through + 2 * r))))
    pitch = (w - 60.0) / cols
    for i in range(rows):
        y = top - height * i / max(rows - 1, 1) if rows > 1 else (top + low) / 2
        offset = pitch / 2 if i % 2 else 0.0
        for j in range(cols + (0 if i % 2 else 1)):
            x = 30.0 + offset + j * pitch
            if _cornered(x, r, w, room):
                continue
            if any(x0 - r <= x <= x1 + r and y0 - r <= y <= y1 + r for x0, y0, x1, y1 in keep):
                continue
            _peg(space, x, y, r)
            style.circles.append((x, y, r))


def _band(space, w, top, bottom, rng, style, layout) -> list:
    """Panels at the foot of the band (`layout`: [(x0, x1, shape)]), pegs
    above them. Nothing beside a pit, where its lid sheds marbles: a peg one
    marble's room out from a pit wall still made a cradle, and four of eight
    marbles stacked into it against the lid and stayed there (seen on L11's
    first stage). So a pit keeps two rooms clear either side, all the way
    down."""
    row = _row(style)
    segments = []
    for x0, x1, shape in layout:
        segments += panel(space, w, style, x0, x1, bottom, shape, row)
    mine = [p for p in panels_of(rig_of(style)) if p.row == row]
    room = marble_room(w)
    keep = [(p.x0 - 2 * room, p.bottom - room, p.x1 + 2 * room, p.top + room) for p in mine]
    _pegs(space, w, top, bottom, rng, style, keep)
    return segments


def trap1(space, w, top, bottom, rng, style):
    """One wide panel off centre, a roof lid, open bypass either side."""
    pw = w * rng.uniform(0.32, 0.36)
    cx = w * rng.uniform(0.40, 0.60)
    return _band(space, w, top, bottom, rng, style, [(cx - pw / 2, cx + pw / 2, "roof")])


def trap1wide(space, w, top, bottom, rng, style):
    """One wide panel, for a band straight under the start: marbles let go
    above it land on its lid rather than falling two seconds through open
    air past a narrower one (trapstairs, whose first band has no room for
    pegs above its panel)."""
    pw = w * rng.uniform(0.46, 0.50)
    cx = w * rng.uniform(0.46, 0.54)
    return _band(space, w, top, bottom, rng, style, [(cx - pw / 2, cx + pw / 2, "roof")])


def trap2(space, w, top, bottom, rng, style):
    """Two panels, a gap beside each wall and one between them."""
    pw = w * rng.uniform(0.23, 0.25)
    shift = w * rng.uniform(-0.01, 0.01)
    return _band(space, w, top, bottom, rng, style,
                 [(w * 0.29 + shift - pw / 2, w * 0.29 + shift + pw / 2, "roof"),
                  (w * 0.71 + shift - pw / 2, w * 0.71 + shift + pw / 2, "roof")])


def trap3(space, w, top, bottom, rng, style):
    """Three panels wall to wall with two gaps: the only ways past are the
    gaps and the lids. The outer lids fall toward the middle — a lid that
    fell toward a wall would be a corner."""
    room = marble_room(w)
    gap = room * GAP_SPARE + style.thickness
    lo, hi = 11.0, w - 11.0
    pw = (hi - lo - 2 * gap) / 3
    nudge = rng.uniform(-0.04, 0.04) * pw
    a = (lo, lo + pw + nudge)
    b = (a[1] + gap, a[1] + gap + pw - 2 * nudge)
    c = (b[1] + gap, hi)
    return _band(space, w, top, bottom, rng, style,
                 [(a[0], a[1], "right"), (b[0], b[1], "roof"), (c[0], c[1], "left")])


# --- the relay station ---------------------------------------------------------------------

@dataclass
class Pen:
    index: int
    x0: float
    x1: float
    floor: float
    door: Any = None         # the rig's door record, coloured once a team is in it
    team: str | None = None
    runner: int | None = None  # leg one's marble
    anchor: int | None = None  # leg two's marble, waiting in the pen
    open: bool = True
    settled: bool = False


def pens_of(rig) -> list[Pen]:
    if not hasattr(rig, "relay_pens"):
        rig.relay_pens = []
    return rig.relay_pens


def relaystation(space, w, top, bottom, rng, style):
    """The halfway gate, and under it four pens across the frame whose floors
    open one at a time. Without the relay mechanic the gate is off and the
    pens stand open: four lanes."""
    rig = rig_of(style)
    big = w * MARBLE_R
    t = style.thickness / 2
    # Above the pens, the gate's zone: taller than a marble resting on a
    # pen's post reaches (radius + post), so nothing can sit on a post
    # outside it. Below, a pen a marble and a bit tall.
    pen_top = top - big * 1.5
    floor = pen_top - (big * 2 + 12.0)
    if floor < bottom:
        raise ValueError(f"the relay station needs {top - floor:.0f} px of band; it has {top - bottom:.0f}")
    lo, hi = 11.0, w - 11.0
    xs = [lo + (hi - lo) * k / 4 for k in range(5)]
    segments = []
    for x in xs:
        a, b = (x, pen_top), (x, floor)
        _wall(space, a, b, thickness=t)
        segments.append((a, b))
    rig.clock("relay_on", lambda f: bool(getattr(f.rig, "relay_live", False)))
    for k in range(4):
        pen = Pen(k, xs[k], xs[k + 1], floor)
        pens_of(rig).append(pen)
        name = f"pen{k}_shut"
        rig.clock(name, lambda f, pen=pen: not pen.open)
        rig.door(space, (xs[k], floor), (xs[k + 1], floor), closed=name, thickness=t)
        pen.door = rig.doors[-1]
    # The gate: a marble whose centre comes down to the pens' tops is home
    # from its leg. A line across the frame, lit in each team's colour as it
    # hands over.
    rig.out_zone((8.0, pen_top + 2.0, w - 8.0, top), when="relay_on", event="handed_off",
                 label="handoff", show=False)
    rig.clock("relay_gate_shut", lambda f: False)
    rig.clock("relay_tagged", lambda f: list(getattr(f.rig, "relay_tagged", [])))
    rig.door(space, (8.0, top), (w - 8.0, top), closed="relay_gate_shut", passes="relay_tagged",
             color=(236, 236, 240), thickness=t)
    return segments


# --- the bowl --------------------------------------------------------------------------------

def bowl(space, w, top, bottom, rng, style):
    """A bowl the width of the frame draining through a trapdoor at its centre.

    The sides are a curve in five pieces, steepening toward the walls, so a
    marble that comes down fast runs over the drain, up the far side and
    back: it circles the drain before the drain takes it. Mud on the lower
    slopes — drawn, a zone that drags — is what lets it settle. Without it
    two marbles swung across a bowl that loses almost nothing for eight
    seconds, crossing the lid each time it was shut, and the race never
    ended. The drain's lid itself is bare, so what falls through falls at
    the stage's gravity.
    """
    rig = rig_of(style)
    big = w * MARBLE_R
    room = marble_room(w)
    # Wide enough for two at once: at one marble's room and a bit, two
    # arriving together jammed across it.
    hole = room * rng.uniform(1.55, 1.7)
    cx = w * rng.uniform(0.47, 0.53)
    t = style.thickness / 2
    rim = bottom + big * PIT_DEPTH  # the lid's height, and the curve's lowest point
    height = min(top - rim, w * 0.55)
    segments = []
    sides = []
    for side in (-1, 1):
        edge = cx + side * hole / 2
        wall_x = 11.0 if side < 0 else w - 11.0
        span = abs(wall_x - edge)
        # A curve from the drain (u = 0) to the wall (u = 1), steepening
        # outward: y = rim + height * (lip * u + (1 - lip) * u * u), with
        # `lip` holding the slope at the drain to BOWL_LIP. A bowl whose
        # bottom flattens out is a floor: the first one parked every marble
        # on it, short of the drain.
        lip = min(1.0, BOWL_LIP * span / height)
        pts = []
        for k in range(6):
            u = k / 5
            pts.append((edge + side * span * u, rim + height * (lip * u + (1 - lip) * u * u)))
        for a, b in zip(pts, pts[1:]):
            _wall(space, a, b, thickness=t)
            segments.append((a, b))
        sides.append(pts)
    # The mud: over each lower slope, from the drain's lip out to the curve's
    # third point, a marble's depth deep.
    for pts in sides:
        lip_pt, far = pts[0], pts[BOWL_MUD]
        depth = big * 2.2
        rig.zone(poly=[lip_pt, *pts[1:BOWL_MUD + 1], (far[0], far[1] + depth), (lip_pt[0], lip_pt[1] + depth)],
                 kind="mud", damping=BOWL_DRAG)
    x0, x1 = cx - hole / 2, cx + hole / 2
    walls = [((x0, rim), (x0, bottom)), ((x0, bottom), (x1, bottom)), ((x1, bottom), (x1, rim))]
    for a, b in walls:
        _wall(space, a, b, thickness=t)
    segments += walls
    p = Panel(0, x0, x1, rim, bottom, 0.0, "flat", _row(style),
              default=(rig.rng.uniform(2.6, 3.0), 0.55, rig.rng.random()))
    _install(space, style, p, [((x0, rim), (x1, rim))], t)
    # The bowl's own rule, whatever mechanic comes: once one marble is left
    # the drain stays shut under it (spiral_bowl sets the same).
    p.opener = lambda f, c=cycling(*p.default): c(f) and _racing(f)
    p.holds = _racing
    return segments


def _racing(f) -> bool:
    """More than one marble still in the race."""
    return sum(1 for ok in f.alive if ok) > 1


# --- stages that need more than a stack -------------------------------------------------------

def finish_build(parts):
    """A stack of sections, then a throat of its own and a panel under it,
    just above the line: the run-in *is* the trapdoor.

    The throat sits higher than the kit's (0.30 h, not 0.20 h): a marble on
    the lid must be clear of the line — its bottom above y = 110 while its
    centre is above the lid — and must fall clear of the throat's tips onto
    the lid, not be wedged between them."""
    inner = stagekit.compose(list(parts), bottom_frac=0.48)

    def build(space, w, h, rng, style):
        segments, runway, lanes = inner(space, w, h, rng, style)
        big = w * MARBLE_R
        throat = h * 0.30
        mouth = throat + h * 0.16
        centre = w * rng.uniform(0.42, 0.58)
        gap = w * rng.uniform(0.26, 0.29)
        t = style.thickness / 2
        for side in (-1, 1):
            a = (w / 2 + side * w * 0.62, mouth)
            b = (centre + side * gap / 2, throat)
            _wall(space, a, b, thickness=t)
            style.gates.append((a, b))
        pw = gap + big * 1.6
        low = 110.0 + big + 10.0   # a marble on the lid has not crossed
        shape = "left" if rng.random() < 0.5 else "right"
        slope = 0.5
        rig = rig_of(style)
        x0, x1 = centre - pw / 2, centre + pw / 2
        rise = pw * slope
        # No floor of its own: the pit's walls stand on the frame's floor.
        p = Panel(0, x0, x1, low, 10.0, rise, shape, _row(style),
                  default=(rig.rng.uniform(3.0, 4.0), 0.3, rig.rng.random()))
        left_top = low + (rise if shape == "right" else 0.0)
        right_top = low + (rise if shape == "left" else 0.0)
        walls = [((x0, left_top), (x0, 14.0)), ((x1, 14.0), (x1, right_top))]
        for a, b in walls:
            _wall(space, a, b, thickness=t)
        lid = ((x0, low), (x1, low + rise)) if shape == "left" else ((x0, low + rise), (x1, low))
        _install(space, style, p, [lid], t)
        # Its own rule without a mechanic too (no draws: the mechanic's stay put).
        p.opener = _through_throat(throat, 0.2, 1.6)
        rig.finish_throat = throat
        return list(segments) + walls, runway, lanes

    build.parts = tuple(parts)  # type: ignore[attr-defined]
    return build


def bowl_build(parts):
    """A stack whose last band is the bowl, reaching nearly to the floor: an
    arena has no line to keep clear of."""
    inner = stagekit.compose(list(parts), bottom_frac=0.05)

    def build(space, w, h, rng, style):
        rig = rig_of(style)
        rig.no_finish_line()
        # With no line the only result is who is left: a race named on this
        # stage without a format is decided that way too.
        if not rig.elimination:
            rig.elimination, rig.win = True, "last_standing"
        return inner(space, w, h, rng, style)

    build.parts = tuple(parts)  # type: ignore[attr-defined]
    return build


def grid_build(parts, *, top_frac: float = 0.84):
    """A stack with a throat (the kit's `gate`) that starts lower, leaving
    the top of the frame to a start grid: twelve marbles start in two rows,
    and the second row sits at y = 873, where the kit's usual stack (content
    from y = 832, pegs up to 9.5 px round) is in the way."""
    return stagekit.compose(list(parts), top_frac=top_frac, bottom_frac=0.36)


# --- the level mechanics -------------------------------------------------------------------------

def _need(rig, what: str) -> list[Panel]:
    panels = panels_of(rig)
    if not panels:
        raise ValueError(f"{what} needs a stage with trapdoor panels (docs/06, World 2)")
    return panels


def _num(rig, name: str, lo: float, hi: float) -> float:
    """A knob if the level sets one, else a seeded draw in [lo, hi]."""
    value = rig.knob(name)
    return float(value) if value is not None else rig.rng.uniform(lo, hi)


def timer_trap(rig, space, style, balls, w, h, *, show: bool | None = None,
               span_range: tuple[float, float] = (3.0, 4.2)):
    """Every panel springs at one hidden, seeded moment and stays open for
    a seeded span (knobs `open_at`, `open_for`). `show_timer` (or the
    overlay mechanic) draws the countdown above the pit."""
    panels = _need(rig, "timer-trap")
    at = _num(rig, "open_at", 5.0, 7.5)
    span = _num(rig, "open_for", *span_range)
    for p in panels:
        p.opener = lambda f, at=at, span=span: at <= f.t < at + span
    if show if show is not None else rig.knob("show_timer", False):
        rig.countdown("trap_in", at)
        p = panels[0]
        rig.effect("countdown", clock="trap_in", at=(p.cx, p.top + w * 0.13))


def timer_overlay(rig, space, style, balls, w, h):
    """The timer trap with its countdown on screen (L18). Open longer than
    L11's: L18 races four marbles, not eight, and with the same window the
    trap took nobody in 44% of races (docs/06, World 2)."""
    timer_trap(rig, space, style, balls, w, h, show=True, span_range=(4.5, 5.5))


def trap_sequence(rig, space, style, balls, w, h):
    """Each panel opens when the leader comes down to it, for a seeded
    moment, then shuts: whoever arrives first finds it open. The race's
    lead is the trigger (docs/08 rule 2.4 allows reacting to it); nothing
    reads who leads."""
    panels = _need(rig, "trap-sequence")
    reach = w * MARBLE_R * 3.0
    for p in panels:
        delay = _num(rig, "delay", 0.0, 0.35)
        span = _num(rig, "open_for", 1.2, 1.8)
        state: dict[str, float | None] = {"at": None}

        def opener(f, p=p, state=state, delay=delay, span=span):
            if state["at"] is None:
                near = [f.positions[i][1] for i in range(len(f.names))
                        if f.alive[i] and f.names[i] not in f.finished]
                if near and min(near) <= p.top + reach:
                    # never inside GRACE_S: the top door is under the start
                    state["at"] = max(f.t, GRACE_S)
            at = state["at"]
            return at is not None and at + delay <= f.t < at + delay + span

        p.opener = opener


def finish_trapdoor(rig, space, style, balls, w, h):
    """The panel under the throat opens a moment after the first marble
    comes through the throat, for a moment (knobs `delay`, `open_for`)."""
    panels = _need(rig, "finish-trapdoor")
    throat = getattr(rig, "finish_throat", None)
    if throat is None:
        raise ValueError("finish-trapdoor needs the trapline stage (a throat with a panel under it)")
    p = panels[-1]
    delay = _num(rig, "delay", 0.0, 0.4)
    span = _num(rig, "open_for", 1.3, 1.9)
    p.opener = _through_throat(throat, delay, span)
    for q in panels[:-1]:
        q.opener = lambda f: False


def _through_throat(throat: float, delay: float, span: float) -> Callable[[Any], bool]:
    """Open `delay` s after the first marble racing is through the throat, for `span` s."""
    state: dict[str, float | None] = {"at": None}

    def opener(f):
        if state["at"] is None:
            if any(f.alive[i] and f.names[i] not in f.finished and f.positions[i][1] <= throat
                   for i in range(len(f.names))):
                state["at"] = f.t
        at = state["at"]
        return at is not None and at + delay <= f.t < at + delay + span

    return opener


def fake_panels(rig, space, style, balls, w, h):
    """Six panels alike; `real` of them (default two, chosen by the seed)
    open at their own hidden moment and stay open, the rest are painted on
    and never do. Until the first real one opens, nothing on screen tells
    them apart: the same lid, the same pit, the same dim rim."""
    panels = _need(rig, "fake-panels")
    real = int(rig.knob("real", 2))
    chosen = set(rig.rng.sample(range(len(panels)), min(real, len(panels))))
    for p in panels:
        if p.index in chosen:
            at = _num(rig, "first_open", 2.0, 3.5)
            p.opener = lambda f, at=at: f.t >= at
        else:
            p.opener = lambda f: False
    rig.real_panels = sorted(chosen)


def leader_sensor(rig, space, style, balls, w, h):
    """A sensor line just above the middle row of panels: the frame the
    leader crosses it, the panel under the leader's x opens for a moment.
    Where the leader is is the mechanism; who it is never enters."""
    panels = _need(rig, "leader-sensor-trap")
    row = [p for p in panels if p.row == min(q.row for q in panels)]
    sensor = max(p.top for p in row) + w * MARBLE_R * 2.2
    span = _num(rig, "open_for", 2.2, 2.8)
    state: dict[str, Any] = {"at": None, "panel": None}
    rig.clock("sensor_shut", lambda f: False)
    rig.door(space, (8.0, sensor), (w - 8.0, sensor), closed="sensor_shut", color=(232, 92, 92),
             thickness=style.thickness / 2)

    def watch(f):
        if state["at"] is not None or f.leader is None:
            return
        y = f.positions[f.leader][1]
        if y <= sensor:
            x = f.positions[f.leader][0]
            if f.rig.mirrored:
                x = w - x  # panels are recorded as built, before a mirror
            state["at"] = f.t
            state["panel"] = min(row, key=lambda p: 0.0 if p.x0 <= x <= p.x1 else min(abs(x - p.x0), abs(x - p.x1))).index
            f.rig.emit("sensor_tripped", None, panel=state["panel"])

    rig.on_frame(watch)
    for p in panels:
        p.opener = lambda f, p=p: (state["panel"] == p.index and state["at"] is not None
                                   and state["at"] <= f.t < state["at"] + span)
    rig.sensor_y = sensor


def spiral_bowl(rig, space, style, balls, w, h):
    """The bowl's drain opens on a cycle (knobs `period`, `open_share`).

    Both halves of the cycle are measured. Open has to be long enough for a
    marble resting on the lid to fall below it: from rest at the stage's
    gravity (-45) that is 1.1 s, and a first version open for 0.65 s let go
    of nothing in 48 races. Shut has to stay under the 1.5 s the simulation
    calls a stall once everything left is sitting on the lid."""
    panels = _need(rig, "spiral-bowl-reverse")
    period = _num(rig, "period", 2.6, 3.0)
    share = float(rig.knob("open_share", 0.55))
    phase = rig.rng.random()
    cycle = cycling(period, share, phase)
    for p in panels:
        # Once one is left the race is decided, and the drain stays shut
        # under the winner rather than taking it too.
        p.opener = lambda f: cycle(f) and _racing(f)
        p.holds = _racing
    rig.no_finish_line()


def relay_legs(rig, space, style, balls, w, h):
    """A team relay. Each team's first marble (`.1`) runs leg one from the
    top; its teammate waits in a pen at the halfway gate, one pen per team
    (which pen is the seed's). When leg one reaches the gate it hands over —
    it leaves the race there — and the pen's floor opens. A team whose first
    marble falls through leg one's panel never hands over, and its teammate
    is out with it. Legs have one panel each; they cycle."""
    pens = pens_of(rig)
    panels = _need(rig, "relay-legs")
    if not pens:
        raise ValueError("relay-legs needs the relay stage (a halfway gate with pens)")
    teams: dict[str, list[int]] = {}
    for i, b in enumerate(balls):
        if getattr(b, "team", None):
            teams.setdefault(b.team, []).append(i)
    if not teams or any(len(v) != 2 for v in teams.values()):
        raise ValueError("relay-legs needs teams of two (params.teams: {id: 2, ...})")
    if len(teams) > len(pens):
        raise ValueError(f"relay-legs has {len(pens)} pens for {len(teams)} teams")
    order = list(range(len(pens)))
    rig.rng.shuffle(order)
    rig.relay_live = True
    rig.relay_tagged = []
    for (team, idx), k in zip(sorted(teams.items()), order):
        runner, anchor = sorted(idx, key=lambda i: balls[i].name)
        pen = pens[k]
        pen.team, pen.runner, pen.anchor, pen.open = team, runner, anchor, False
        pen.door.color = tuple(balls[anchor].color)
        body = balls[anchor].body
        body.position = ((pen.x0 + pen.x1) / 2, pen.floor + balls[anchor].radius + 4.0)
        body.velocity = (0.0, 0.0)
    for p in panels:
        p.opener = cycling(rig.rng.uniform(2.6, 3.2), float(rig.knob("open_share", 0.45)), rig.rng.random(),
                           after=GRACE_S)

    def hand_over(f):
        r = f.rig
        for pen in pens:
            if pen.team is None or pen.settled or r.alive[pen.runner]:
                continue
            pen.settled = True
            how = next((d.get("by") for _, kind, i, d in r.events if kind == "eliminated" and i == pen.runner), None)
            if how == "handoff":
                pen.open = True
                r.relay_tagged.append(r.names[pen.runner])
            else:
                r.eliminate(pen.anchor, by="relay", event="relay_dropped")

    rig.on_frame(hand_over)


def five_trapdoors(rig, space, style, balls, w, h):
    """Every panel on its own seeded cycle (knob `open_share`), shut for the
    first GRACE_S: the question is when to arrive, not where. The share is
    where two measured failures meet: with two marbles, doors open more of
    the time decide the race at the first fall and the survivor walks home
    alone (0.60: a runner-up in 44% of races), and doors open less of the
    time catch nobody (0.25: a catch in 13 of 48). At 0.45 a catch happens
    in two races of five and the second marble still arrives in most."""
    panels = _need(rig, "five-trapdoors")
    share = float(rig.knob("open_share", 0.45))
    for p in panels:
        p.opener = cycling(rig.rng.uniform(2.4, 3.4), share, rig.rng.random(), after=GRACE_S)


def trap_gauntlet(rig, space, style, balls, w, h):
    """Every panel cycles, and each band's cycle runs a beat behind the band
    above it: the doors open in a wave that follows the field down."""
    panels = _need(rig, "trap-gauntlet")
    share = float(rig.knob("open_share", 0.30))
    period = _num(rig, "period", 2.6, 3.2)
    wave = rig.rng.random()
    for p in panels:
        phase = (wave - p.row * 0.28 + rig.rng.uniform(-0.08, 0.08)) % 1.0
        p.opener = cycling(period, share, phase, after=GRACE_S)


# --- registration ------------------------------------------------------------------------------

SECTIONS = {"trap1": trap1, "trap1wide": trap1wide, "trap2": trap2, "trap3": trap3, "relaystation": relaystation, "bowl": bowl}
SECTION_WORDS = {
    "trap1": "a trapdoor panel", "trap1wide": "a wide trapdoor panel", "trap2": "two trapdoor panels", "trap3": "a row of three trapdoor panels",
    "relaystation": "a halfway gate with a pen for each team", "bowl": "a bowl draining into a trapdoor",
}
stagekit.SECTIONS.update(SECTIONS)
stagekit.SECTION_WORDS.update(SECTION_WORDS)
