"""World 4, Halloween Cup: Haunted Maze (Season 0, L31-L38).

The maze is rows of forks. A **split** is a roof: the field drops onto its
point and goes left or right, down one of two corridors toward the frame's
walls. Each corridor ends in a fork: the way on is a gap in the floor short
of the wall, a turn down; the corridor itself carries straight on past it
into a blind end under a low roof. That is the dead end, and a marble that
rolls into it is out of the race (`rig.out_zone`, `dead_end`, drawn as a dark
pit with a red rim). A **join** is a V that gathers both sides back to one
gap in the middle, over the next split. So every split is two ways down,
which way is the bounce's, and each way ends at a dead end.

Who takes a dead end is physics: a marble that comes down a corridor too
fast carries over the gap and into it; one that arrives slower turns down.
How many do depends on the gap's width against the corridor's pace, which is
the stage's (drawn from the seed), never on who is coming (docs/08 rule 2.4).

Why rows of forks and not a stack of long corridors, which was built first
and reads more like a maze in a still: corridors wall to wall cost their
whole fall in the frame's height, so only three fit, and a corridor is
single file. Its lead changed 0.9-1.2 times a race with the four regulars
(the gate is 1.5), however the fork, the slope and the band under it were
tuned. Two ways down every split is what the chutes section taught the kit:
the field divides and comes back together in a new order.

The rest of World 4 is mechanics laid over the maze or over stages that
exist (registered in physics/registry.py):

  haunted-maze        the maze, nothing added (L31)
  fog-blackout        the frame goes dark while the leader crosses the middle
                      of the course, at least FOG_MIN and at most FOG_MAX
                      seconds; marbles hidden, sound on, the veil lifts as
                      the leader comes out (`rig.effect("blackout")`). L32
  rolling-pumpkins    some bumpers are pumpkins: still until a marble touches
                      one, then let go to roll down the course (L33)
  cobweb-strip        a web in the maze's middle gap that holds the first
                      marble into it, then tears (`zone(first_only)`). L34
  coffin-trapdoor     World 2's panel under a funnel, as a coffin: it opens a
                      moment after the first marble reaches its lid and shuts
                      for good once it holds one (L36)
  haunted-maze-final  maze, fog, pumpkins, web and a cycling coffin (L37)
  maze-time-trial     the maze with a par clock on screen, for one marble (L38)

Events, all about the mechanism: `dead_end` (with `eliminated`),
`pumpkin_rolled`, `webbed`, `fog_down`, `fog_lifted`; the coffin is World 2's
panel and reports `trap_catch` and `trap_opened`.
"""

from __future__ import annotations

import math

import pymunk

from ... import stagekit
from ...mechanics import FINISH_Y, rig_of
from ...stagekit import MARBLE_R, _wall, marble_room
from . import trapdoor as w2

# --- the maze ------------------------------------------------------------------------------

# A split's corridors fall at this slope from the point to the wall.
SPLIT_SLOPE = 0.30
# A join's arms, from the walls down to its middle gap: steeper, so nothing
# dawdles on the way back to the middle (the kit's ramps: 0.37-0.44).
JOIN_SLOPE = 0.38
# The join's middle gap, as a share of the width (chutes: 0.16-0.20); never
# under marble_room.
JOIN_GAP = (0.17, 0.20)
# The split's point: a short tilted cap, as the chutes section's, so nothing
# balances on it; half its length, as a share of the width, and its tilt.
CAP = 0.06
CAP_TILT = 0.4
# Headroom under a split's corridors' ends, in units of marble_room, plus the
# walls' thickness.
HEADROOM = 1.05
# The dead end: how far the corridor carries on past the fork, in rooms, to
# the wall; and its roof, in radii of the biggest marble over the floor.
ALCOVE = 1.0
ROOF = 2.6
# The fork's gap, as a share of marble_room. Every marble fits through it; how
# many roll over it is what the maze asks.
FORK = (1.10, 1.25)
# The out zone starts this many radii past the gap's far lip, so a marble that
# clips the lip and drops back into the gap is not counted out.
LIP_GRACE = 0.7


def maze_of(rig) -> list[dict]:
    """The rows the maze sections built, top first: {"kind", "y", "low", "forks"}."""
    if not hasattr(rig, "maze"):
        rig.maze = []
    return rig.maze


def _inside(w: float, thickness: float) -> tuple[float, float]:
    """Where a row meets the frame walls (their inner faces)."""
    return 10.0 + thickness * 0.25, w - 10.0 - thickness * 0.25


def maze(space, w, top, bottom, rng, style):
    """Join, split, join, split ... down the band. The field enters through
    a join (the start row is spread across the frame, and a dead end straight
    under it would be a lottery before the race began)."""
    rig = rig_of(style)
    room = marble_room(w)
    big = w * MARBLE_R
    t = style.thickness / 2
    lo, hi = _inside(w, style.thickness)
    mid = w / 2
    s = float(rig.knob("split_slope", SPLIT_SLOPE))
    widths = rig.knob("fork")
    fork_lo, fork_hi = (float(widths[0]), float(widths[1])) if widths else FORK
    alcove = room * ALCOVE
    gapc = room * HEADROOM + 2 * t
    segments = []
    rows = maze_of(rig)

    def join(y):
        gap = max(w * rng.uniform(*JOIN_GAP), room)
        low = y - JOIN_SLOPE * (mid - gap / 2 - lo)
        rows.append({"kind": "join", "y": y, "low": low, "gap": gap, "forks": []})
        return [((lo, y), (mid - gap / 2, low)), ((hi, y), (mid + gap / 2, low))], low

    def split(y):
        cap = w * CAP
        tilt = 1 if rng.random() < 0.5 else -1
        a, b = (mid - cap, y + tilt * cap * CAP_TILT), (mid + cap, y - tilt * cap * CAP_TILT)
        pieces = [(a, b)]
        forks = []
        low = y
        roof = big * ROOF
        for side, (px, py) in ((-1, a), (1, b)):
            wall_x = lo if side < 0 else hi

            def at(x, px=px, py=py):
                return py - s * abs(x - px)  # the corridor's floor at x

            gap = room * rng.uniform(fork_lo, fork_hi)
            far = wall_x - side * alcove    # the gap's far lip: the dead end starts here
            near = far - side * gap         # the gap's near lip
            end = at(wall_x)
            pieces += [((px, py), (near, at(near))), ((far, at(far)), (wall_x, end)),
                       ((wall_x, end + roof), (far, at(far) + roof))]  # the dead end's roof
            x0 = far + side * (LIP_GRACE * big)
            rig.out_zone(poly=[(x0, at(x0) - t), (wall_x, end - t), (wall_x, end + roof - t), (x0, at(x0) + roof - t)],
                         event="dead_end", label="dead_end")
            forks.append({"side": side, "near": near, "far": far, "gap": gap, "y": at(near)})
            low = min(low, end)
        rows.append({"kind": "split", "y": y, "low": low, "forks": forks})
        return pieces, low

    y = top
    kind = "join"
    while True:
        pieces, low = (join if kind == "join" else split)(y)
        for a, b in pieces:
            _wall(space, a, b, thickness=t)
            segments.append((a, b))
        # The next row starts headroom under this one's lowest point, if its
        # own fall still fits in the band. Under a join's gap the split's
        # point sits a marble's room down (the chutes' lesson: less, and a
        # marble wedges between the V's tips and the cap).
        nxt = "split" if kind == "join" else "join"
        y = low - (room + 2 * t if kind == "join" else gapc)
        fall = s * (mid - lo) if nxt == "split" else JOIN_SLOPE * (mid - lo) * 0.8
        if y - fall < bottom:
            break
        kind = nxt
    return segments


# --- the coffin ------------------------------------------------------------------------------

WOOD = (132, 88, 52)       # the coffin's lid
COFFIN_GAP = (0.20, 0.23)  # the funnel's throat over it, as a share of the width (the funnel section's)
COFFIN_SLOPE = 0.46        # the funnel's longer arm; nothing rests on it
# The lid is the throat's width plus this many radii, so all of the throat is
# over it: at 1.6 a marble through the throat's edge with a sideways kick
# missed the lid, and the coffin took nobody in 5 of 48 semifinals.
COFFIN_OVER = 2.4


def coffin(space, w, top, bottom, rng, style):
    """A funnel whose throat is straight over one World 2 panel, a roof lid
    over a pit, drawn in wood: everyone comes through the throat onto the lid
    and slides off one side of it, unless it is open."""
    rig = rig_of(style)
    big = w * MARBLE_R
    room = marble_room(w)
    t = style.thickness / 2
    cx = w * rng.uniform(0.42, 0.58)
    gap = w * rng.uniform(*COFFIN_GAP)
    pw = gap + big * COFFIN_OVER
    x0, x1 = cx - pw / 2, cx + pw / 2
    lid_top = bottom + big * w2.PIT_DEPTH + (pw / 2) * w2.LID_SLOPE
    throat = lid_top + room * 1.0
    lo, hi = _inside(w, style.thickness)
    arm = max(cx - gap / 2 - lo, hi - cx - gap / 2)
    # As steep as COFFIN_SLOPE if the band allows; a band a few px short (the
    # final's, on some seeds) takes a slightly shallower arm, never under
    # the funnel section's 0.45 floor less a little.
    rise = min(COFFIN_SLOPE * arm, top - throat)
    if rise < 0.40 * arm:
        raise ValueError(f"the coffin needs {throat + 0.40 * arm - bottom:.0f} px of band; it has {top - bottom:.0f}")
    segments = []
    for side in (-1, 1):
        # From the wall, both arms rising to the same height: the shorter
        # one is the steeper. A clipped, shallow arm was a shelf that held a
        # marble and two pumpkins for the rest of a final.
        b = (cx + side * gap / 2, throat)
        a = (lo if side < 0 else hi, throat + rise)
        _wall(space, a, b, thickness=t)
        segments.append((a, b))
    before = len(rig.doors)
    segments += w2.panel(space, w, style, x0, x1, bottom, "roof", w2._row(style))
    for d in rig.doors[before:]:
        d.color = WOOD
    rig.coffin = w2.panels_of(rig)[-1]
    return segments


HAUNTED = (("maze", 1.0),)
COFFIN = (("pegs", 0.8), ("coffin", 1.6), ("pegs", 0.7))
FINAL = (("maze", 1.45), ("coffin", 1.0))

SECTIONS = {"maze": maze, "coffin": coffin}
SECTION_WORDS = {"maze": "a maze of forks, each way ending at a dead end",
                 "coffin": "a funnel onto a coffin trapdoor"}
stagekit.SECTIONS.update(SECTIONS)
stagekit.SECTION_WORDS.update(SECTION_WORDS)


# --- the mechanics ----------------------------------------------------------------------------

def _num(rig, name: str, lo: float, hi: float) -> float:
    """A knob if the level sets one, else a seeded draw in [lo, hi]."""
    value = rig.knob(name)
    return float(value) if value is not None else rig.rng.uniform(lo, hi)


def _rows(rig, what: str) -> list[dict]:
    rows = maze_of(rig)
    if not rows:
        raise ValueError(f"{what} needs a stage with the maze (docs/06, World 4)")
    return rows


def haunted_maze(rig, space, style, balls, w, h):
    """The maze as built: its dead ends are the stage's. Named so a level says
    what it races and a stage without the maze is refused, not raced plain."""
    _rows(rig, "haunted-maze")


# The fog: how long the frame stays dark, whatever the leader does.
FOG_MIN, FOG_MAX = 1.6, 2.4


def fog(rig, *, start: float, end: float) -> str:
    """Dark from the frame the leader has come `start` of the way down until
    it has come `end` of the way — never shorter than FOG_MIN nor longer than
    FOG_MAX seconds. Only how far the race has come starts and ends it."""
    state: dict = {"on": None, "off": None}

    def clock(f):
        if state["off"] is not None:
            return False
        if state["on"] is None:
            if f.progress >= start:
                state["on"] = f.t
                f.rig.emit("fog_down", None)
                return True
            return False
        dark = f.t - state["on"]
        if dark >= FOG_MAX or (dark >= FOG_MIN and f.progress >= end):
            state["off"] = f.t
            f.rig.emit("fog_lifted", None)
            return False
        return True

    rig.clock("fog", clock)
    rig.effect("blackout", clock="fog")
    return "fog"


def fog_blackout(rig, space, style, balls, w, h):
    """L32: lights out over the middle of the course (knobs `fog_from`,
    `fog_to`: race fractions)."""
    fog(rig, start=float(rig.knob("fog_from", 0.50)), end=float(rig.knob("fog_to", 0.80)))


# Pumpkins. Mass in units of a mid-sized marble's (1 + r/40 = 1.6): heavy
# enough that a knock sets one rolling rather than flying.
PUMPKIN_MASS = 2.0
# A pumpkin's skin is slick. At the kit's 0.45 a loose pumpkin came to rest
# on a rocking plank and marbles stacked against it there.
PUMPKIN_FRICTION = 0.06
PUMPKIN_COLOUR = (236, 124, 28)


def pumpkin(rig, space, x: float, y: float, r: float) -> None:
    """A pumpkin at (x, y): a kinematic body — a bumper — until a marble
    touches it, then a dynamic one that rolls where the course takes it. It
    leaves the course when it drops past the line or into a dead end, as a
    marble would. Drawn as a prop that follows its body (`track`)."""
    body = pymunk.Body(body_type=pymunk.Body.KINEMATIC)
    body.position = (x, y)
    shape = pymunk.Circle(body, r)
    shape.mass = PUMPKIN_MASS * (r / 16.0) ** 2
    shape.elasticity, shape.friction = 0.55, PUMPKIN_FRICTION
    space.add(body, shape)
    if not hasattr(rig, "pumpkins"):
        rig.pumpkins = []
        rig.on_frame(_pumpkins)
    k = len(rig.pumpkins)
    rec = {"body": body, "shape": shape, "r": r, "loose": False, "gone": False}
    rig.pumpkins.append(rec)
    name = f"pumpkin{k}"
    rig.clock(name, lambda f, rec=rec: None if rec["gone"]
              else [round(rec["body"].position.x, 1), round(rec["body"].position.y, 1)])
    rig.effect("prop", clock=name, track=True, look="pumpkin", radius=r, color=list(PUMPKIN_COLOUR))


def _pumpkins(f) -> None:
    rig = f.rig
    outs = [z for z in rig.zones if z.out and z.when is None]
    for k, rec in enumerate(rig.pumpkins):
        if rec["gone"]:
            continue
        body = rec["body"]
        x, y = body.position
        if not rec["loose"]:
            for i, (bx, by) in enumerate(f.positions):
                if f.alive[i] and math.hypot(bx - x, by - y) <= rec["r"] + rig.balls[i].radius + 2.0:
                    body.body_type = pymunk.Body.DYNAMIC
                    rec["loose"] = True
                    rig.emit("pumpkin_rolled", None, pumpkin=k)
                    break
            continue
        if y < FINISH_Y + rec["r"] or any(z.contains(x, y) for z in outs):
            rig.space.remove(body, rec["shape"])
            rec["gone"] = True


def rolling_pumpkins(rig, space, style, balls, w, h):
    """L33: `pumpkins` (default 4) of the stage's bumpers, drawn by the seed,
    become pumpkins of the same size in the same place."""
    if not style.circles:
        raise ValueError("rolling-pumpkins needs a stage with bumpers")
    n = min(int(rig.knob("pumpkins", 4)), len(style.circles))
    picked = rig.rng.sample(range(len(style.circles)), n)
    for k in sorted(picked, reverse=True):
        x, y, r = style.circles.pop(k)
        for shape in list(space.static_body.shapes):
            if (isinstance(shape, pymunk.Circle) and abs(shape.radius - r) < 1e-6
                    and abs(shape.offset.x - x) < 1e-6 and abs(shape.offset.y - y) < 1e-6):
                space.remove(shape)
                break
        pumpkin(rig, space, x, y, r)


WEB_DRAG = 3.5   # 1/s on the caught marble's velocity (a sand pit is 1.4)
WEB_HOLD = 2.2   # s the web holds its marble before it tears


def web(rig, row: dict, w: float) -> None:
    """A web across a join's gap. The first marble into it is caught and
    dragged (`webbed`); WEB_HOLD seconds later the web tears and is gone.
    Arrival order is the mechanism, never who arrives."""
    big = w * MARBLE_R
    mid = w / 2
    half = row["gap"] / 2 + big * 0.4
    rect = (mid - half, row["low"] - big * 1.8, mid + half, row["low"] + big * 0.9)
    hold = float(rig.knob("web_hold", WEB_HOLD))
    rig.zone(rect, kind="cobweb", damping=float(rig.knob("web_drag", WEB_DRAG)), first_only=True,
             when="web", event="webbed", appear=True)
    zone = rig.zones[-1]
    state: dict = {"caught": None}

    def clock(f):
        if zone.victim is not None and state["caught"] is None:
            state["caught"] = f.t
        return state["caught"] is None or f.t - state["caught"] < hold

    rig.clock("web", clock)


def cobweb_strip(rig, space, style, balls, w, h):
    """L34: the web in the maze's second join, the middle of the course."""
    joins = [r for r in _rows(rig, "cobweb-strip") if r["kind"] == "join"]
    web(rig, joins[min(1, len(joins) - 1)], w)


def _coffin(rig, what: str):
    p = getattr(rig, "coffin", None)
    if p is None:
        raise ValueError(f"{what} needs a stage with the coffin (docs/06, World 4)")
    return p


def coffin_trapdoor(rig, space, style, balls, w, h):
    """L36: the coffin opens `delay` seconds (seeded, knob) after the first
    marble reaches its lid and stays open until it holds one; then it shuts
    for good. Whoever is on the lid or comes through the throat while it is
    open goes in — the first to arrive only if it is still there."""
    p = _coffin(rig, "coffin-trapdoor")
    big = w * MARBLE_R
    delay = _num(rig, "delay", 0.1, 0.5)
    state: dict = {"at": None, "caught": False}

    def caught(f):
        if not state["caught"]:
            state["caught"] = any(kind == "trap_catch" for _, kind, _, _ in f.rig.events)
        return state["caught"]

    def opener(f):
        if caught(f):
            return False
        if state["at"] is None:
            # A marble coming down onto the lid. (Waiting for one squarely
            # on it was tried: marbles glance off the roof's slopes, and the
            # coffin then opened in fewer races, not more.)
            if any(f.alive[i] and p.x0 <= x <= p.x1 and y <= p.top + big * 2.0
                   for i, (x, y) in enumerate(f.positions)):
                state["at"] = max(f.t, w2.GRACE_S)
            return False
        return f.t >= state["at"] + delay

    p.opener = opener
    p.holds = lambda f: not caught(f)


def haunted_final(rig, space, style, balls, w, h):
    """L37: everything at once. Pumpkins on the first join's arms, the fog
    over the middle of the maze, the web in its second join, and the coffin
    under the run-in on a cycle of its own (two finalists: a coffin sure to
    take one would decide the final by itself)."""
    rows = _rows(rig, "haunted-maze-final")
    p = _coffin(rig, "haunted-maze-final")
    joins = [r for r in rows if r["kind"] == "join"]
    t = style.thickness / 2
    first = joins[0]
    lo, hi = _inside(w, style.thickness)
    r = w * 0.03
    for side in (-1, 1):
        # On the arm, most of the way in from the wall, resting on it.
        wall_x = lo if side < 0 else hi
        x = wall_x - side * (w / 2 - lo) * 0.62
        y = first["y"] - JOIN_SLOPE * abs(x - wall_x) + (r + t) * math.hypot(1.0, JOIN_SLOPE)
        pumpkin(rig, space, x, y, r)
    fog(rig, start=float(rig.knob("fog_from", 0.30)), end=float(rig.knob("fog_to", 0.55)))
    if len(joins) > 1:
        web(rig, joins[1], w)
    share = float(rig.knob("open_share", 0.35))
    p.opener = w2.cycling(_num(rig, "period", 2.6, 3.2), share, rig.rng.random(), after=w2.GRACE_S)


PAR_S = 13.8  # the time trial's par, sim seconds: the clock on screen counts down to it


def maze_time_trial(rig, space, style, balls, w, h):
    """L38: the maze for one marble, and a par clock on screen counting down
    to a fixed time (knob `par`), the same for every run: no other clip's
    time is carried here."""
    _rows(rig, "maze-time-trial")
    par = float(rig.knob("par", PAR_S))
    rig.countdown("par", par)
    # Under the line, in the strip nothing races through: the top of the
    # frame is the captions'.
    rig.effect("countdown", clock="par", at=(w / 2, FINISH_Y * 0.5))
