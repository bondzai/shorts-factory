"""World 9, Color Roulette Gates (Season 0, L81-L90): gates that know colours.

Every gate in this world is one piece used eight ways: a funnel down to a
wide, level bar across its throat — a `rig.door` — that is solid for some
marbles and not for others. The bar says which, in the colours themselves:
shut, it is drawn in the colour (or colours) that may pass, on a pale rim,
with lamps of those colours under the funnel's arms, clear of the marbles
queued on it; a reverse gate is drawn pale with its lamp crossed out; open to
everyone it is the faint line every open door is (render_mech, "colour
gates"). A marble whose colour is lit drops straight through; everyone else
rests on the bar and waits.

The sections here (`colourgate`; `icegate`, whose arms are World 5's ice;
`boxgate`, with room for a penalty box under its bar) build the geometry
and record a `Gate` on the rig; a level's mechanic sets each gate's `rule(frame) -> (mode, ids)`:

  "only", ids    shut for everyone but `ids` (the colour the gate picked)
  "block", ids   open for everyone but `ids` (the leader it locked out)
  "open", []     open for everyone

The mechanics (registered in physics/registry.py, beside weight-0 stages):

  random-colour-gate    one gate lights a seeded colour as the field reaches
                        it; that colour flies through, the rest wait a seeded
                        2-3 s and then it opens for everyone (L81)
  three-colour-gates    three such gates in sequence, three different
                        colours, shorter waits (L82)
  leader-lockout-gate   as the field reaches it the gate shuts for the
                        leader's colour only, for a seeded 2.5-3.5 s (L83)
  alliance-gate         two seeded colours pass, the rest wait (L84)
  cycling-colour-gate   the gate lights every colour in turn, one a second,
                        in a seeded order; arrive on yours and you are
                        through (L85, and L89's seeding track)
  colour-trapdoor-gate  World 2's trapdoor panel as a gate: each time it
                        opens it lights one seeded colour; that colour rolls
                        over the lid, anyone else on it drops out (L86)
  snow-colour-gates     a random gate and a cycling gate on an ice track (L87)
  gate-breaker          a cycling gate that breaks under momentum: any marble
                        that hits it shut with mass x speed over the bar's
                        strength smashes it open for good and serves a
                        penalty in the box under it (L88)
  all-gates-snow        random, reverse and cycling gates and a trapdoor gate
                        on ice (L90)

Docs/08 rule 2.4 holds throughout. A colour comes from `rig.rng`, drawn over
the field in the order it stands, so every colour is as likely as any other;
the reverse gate reads *where* the leader is, never who; the breaking rule is
mass times speed for everyone, and only a heavy marble usually has enough.

Nothing here edits the simulation. A gate never shuts through a marble that is
already passing (`Gate.crossing`), and every gate has an end: a lit gate opens for
everyone after its wait, a reverse gate after its lock, a cycling gate lights
every colour in turn, and as a last resort any gate opens for everyone once
a marble has waited GIVE_UP_S on its bar (docs/06 counts how often).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Callable

from ... import stagekit
from ...mechanics import _seg_dist, rig_of
from ...stagekit import MARBLE_R, _wall, marble_room
from . import ice_sand
from . import trapdoor as w2

# The bar across the throat, as a share of the width: wide enough that a
# marble waiting on it (or locked out on it) leaves room beside it for one
# that may pass, and for every colour to have a marble resting on the bar.
BAR_SHARE = 0.40
# The funnel's arms, at least: past the 0.46 a marble can rest on.
ARM_SLOPE = 0.50
ARM_DROP = 0.45  # how far under the band's top the arms start, in marble rooms
# How far the lamps sit outside the throat, under the funnel's arms: dead
# space no marble can reach, so the lamps are never hidden by the queue.
LAMP_OUT = 44.0
# A lit gate holds everyone else this long after the first marble reaches it.
HOLD_S = (2.0, 3.0)
HOLD_SHORT_S = (1.4, 2.0)   # three in a row (L82), and the final's gates
LOCK_S = (2.5, 3.5)         # the reverse gate's lock
CYCLE_S = 1.0               # one colour a second
# The last resort: a gate opens for good once any marble has sat on (or
# queued over) its bar this long. Past anything the rules above ask for: a
# cycling gate lights six colours in six seconds, and a marble stacked on
# another can miss its colour once.
GIVE_UP_S = 15.0


@dataclass
class Gate:
    """One colour gate: the bar from (x0, y) to (x1, y), under a funnel whose
    mouth is at `top`. `rule` is the level's; `look` is how it is drawn."""

    index: int
    x0: float
    x1: float
    y: float
    top: float
    cx: float
    look: str = "pass"
    rule: Callable[[Any], tuple[str, list[str]]] | None = None
    near: float | None = None        # when the first marble came into the funnel
    arrived: float | None = None     # when the first marble reached the bar
    mode: str = "only"
    ids: list[str] = field(default_factory=list)
    crossing: set = field(default_factory=set)
    since: dict = field(default_factory=dict)  # marble -> when it came onto the bar
    gave_up: bool = False
    door: Any = None
    said: set = field(default_factory=set)

    @property
    def name(self) -> str:
        return f"cgate{self.index}"


def gates_of(rig) -> list[Gate]:
    """The round's colour gates, in the order the stage built them (top first)."""
    if not hasattr(rig, "colour_gates"):
        rig.colour_gates = []
    return rig.colour_gates


def _contenders(f) -> list[int]:
    return [i for i in range(len(f.names)) if f.alive[i] and f.names[i] not in f.finished]


def _radius(f, i: int) -> float:
    return f.rig.balls[i].radius


def _pos(f, i: int) -> tuple[float, float]:
    """Where marble i is, in the coordinates the gate was built in (a
    mirrored round reflects what the rig recorded, not the Gate)."""
    x, y = f.positions[i]
    return (f.rig.w - x, y) if f.rig.mirrored else (x, y)


def _state(f, g: Gate, big: float, thick: float) -> bool:
    """Evaluate gate g this frame; returns whether its bar is shut. Sets
    g.mode / g.ids and the marbles now crossing it."""
    live = _contenders(f)
    pos = {i: _pos(f, i) for i in live}
    if g.near is None and any(pos[i][1] <= g.top + big for i in live):
        g.near = f.t
    if g.arrived is None and any(g.x0 - big <= pos[i][0] <= g.x1 + big and pos[i][1] <= g.y + big * 2.2
                                 for i in live):
        g.arrived = f.t
    mode, ids = (g.rule(f) if g.rule else _default(f, g))
    # The last resort: a marble that has been on (or queued over) the bar
    # for GIVE_UP_S without getting through opens it for good.
    for i in live:
        x, y = pos[i]
        if g.x0 - big <= x <= g.x1 + big and g.y < y <= g.y + big * 5:
            g.since.setdefault(i, f.t)
        else:
            g.since.pop(i, None)
    if g.gave_up or any(f.t - t0 >= GIVE_UP_S for t0 in g.since.values()):
        g.gave_up = True
        mode, ids = "open", []
    # Who may go through the bar now, by the rule; and anyone already in it
    # stays passing until clear, so the bar never shuts through a marble.
    if mode == "open":
        may = set(range(len(f.names)))
    elif mode == "only":
        may = {i for i, n in enumerate(f.names) if n in ids}
    else:
        may = {i for i, n in enumerate(f.names) if n not in ids}
    a, b = (g.x0, g.y), (g.x1, g.y)
    keep = set()
    for i in live:
        d = _seg_dist(pos[i], a, b)
        touch = _radius(f, i) + thick + 3.0
        if d <= touch and (i in may or i in g.crossing):
            keep.add(i)
    g.crossing = keep
    g.mode, g.ids = mode, list(ids)
    return mode != "open"


def _default(f, g: Gate) -> tuple[str, list[str]]:
    """A gate raced without a mechanic cycles every colour, a second each."""
    return "only", [f.names[int(f.t / CYCLE_S) % len(f.names)]]


def _install(space, style, g: Gate, lamps: list) -> None:
    rig = rig_of(style)
    gates = gates_of(rig)
    g.index = len(gates)
    gates.append(g)
    big = rig.w * MARBLE_R * 1.1
    thick = style.thickness / 2
    n = g.name

    def shut(f, g=g):
        return _state(f, g, big, thick)

    def passes(f, g=g):
        if g.mode == "open":
            return list(f.names)
        if g.mode == "only":
            base = [x for x in f.names if x in g.ids]
        else:
            base = [x for x in f.names if x not in g.ids]
        return sorted(set(base) | {f.names[i] for i in g.crossing}, key=f.names.index)

    def lit(f, g=g):
        return [] if g.mode == "open" else list(g.ids)

    def waiting(f, g=g):
        """Marbles resting on (or queued over) a shut bar that may not pass:
        the field held on purpose, not stalled."""
        if g.mode == "open":
            return False
        through = set(passes(f))
        for i in _contenders(f):
            x, y = _pos(f, i)
            if g.x0 - big <= x <= g.x1 + big and g.y < y <= g.y + big * 5 and f.names[i] not in through:
                return True
        return False

    rig.clock(n + "_shut", shut)
    rig.clock(n + "_pass", passes)
    rig.clock(n + "_lit", lit)
    rig.clock(n + "_wait", waiting)
    rig.hold(n + "_wait")
    rig.door(space, (g.x0, g.y), (g.x1, g.y), closed=n + "_shut", passes=n + "_pass", lights=n + "_lit",
             look=g.look, lamps=lamps, thickness=thick)
    g.door = rig.doors[-1]
    if len(gates) == 1:
        rig.on_frame(_announce)


def _announce(f) -> None:
    """Mechanism events, once each: `gate_lit` when a gate first lights a
    colour (the colour on screen, not a result), `gate_locked` for a reverse
    gate, `gate_opened` when it opens for everyone."""
    for g in gates_of(f.rig):
        if g.near is None:
            continue
        if g.mode == "only" and g.ids and "lit" not in g.said:
            g.said.add("lit")
            f.rig.emit("gate_lit", None, gate=g.index, colours=list(g.ids))
        if g.mode == "block" and g.ids and "locked" not in g.said:
            g.said.add("locked")
            f.rig.emit("gate_locked", None, gate=g.index)
        if g.mode == "open" and "opened" not in g.said:
            g.said.add("opened")
            f.rig.emit("gate_opened", None, gate=g.index)


# --- the sections ------------------------------------------------------------------------------

def _gate(space, w, top, bottom, rng, style, *, ice: bool = False, foot: float = 0.0):
    rig = rig_of(style)
    cx = w * rng.uniform(0.45, 0.55)
    # The arms start under the band's top: the section above ends two margins
    # up, and an arm reaching all the way made a cradle with a peg over it
    # (L89, seed 747: a marble sat under a peg on the arm for 30 s).
    top -= marble_room(w) * ARM_DROP
    bottom += foot
    # A short band gets a wider bar rather than shallower arms.
    longest = (top - bottom) / ARM_SLOPE
    bar = max(w * BAR_SHARE, (w - 28.0) - 2 * longest + 2 * abs(cx - w / 2))
    if bar > w * 0.64:
        raise ValueError(f"a colour gate needs more band than {top - bottom:.0f} px")
    x0, x1 = cx - bar / 2, cx + bar / 2
    run = max(x0 - 14.0, (w - 14.0) - x1)
    # The bar sits on the band's foot, so the section under it is always two
    # margins down and a tall band's spare height is air above the arms.
    # (Rarely, a marble through the open bar near an end still bounces off a
    # peg under it into the hollow under an arm and wedges there: a few marbles
    # in 2,880 uncut in docs/06. Lips at the bar's ends to stop it made the
    # bar a chute that jammed far more often, so there are none.)
    y = bottom
    top = y + run * ARM_SLOPE
    arms = [((14.0, top), (x0, y)), ((w - 14.0, top), (x1, y))]
    segments = []
    for a, b in arms:
        if ice:
            ice_sand._layer(rig, space, w, style, a, b, "ice")
        else:
            _wall(space, a, b, thickness=style.thickness / 2)
            segments.append((a, b))
    lamps = [(x0 - LAMP_OUT, y - 4.0), (x1 + LAMP_OUT, y - 4.0)]
    _install(space, style, Gate(0, x0, x1, y, top, cx), lamps)
    # For World 5's ramps under it: the field comes down through the bar.
    rig.w5_exit, rig.w5_exit_x = "drop", cx
    return segments


def colourgate(space, w, top, bottom, rng, style):
    """A funnel down to a wide colour-gate bar across its throat."""
    return _gate(space, w, top, bottom, rng, style)


def boxgate(space, w, top, bottom, rng, style):
    """A colour gate with room under its bar for a penalty box (L88)."""
    return _gate(space, w, top, bottom, rng, style, foot=marble_room(w) * BOX_FOOT)


def icegate(space, w, top, bottom, rng, style):
    """The same gate with arms of ice: the field slides in fast (L87, L90)."""
    return _gate(space, w, top, bottom, rng, style, ice=True)


# --- the level mechanics -------------------------------------------------------------------------

def _need(rig, what: str, n: int = 1) -> list[Gate]:
    gates = gates_of(rig)
    if len(gates) < n:
        raise ValueError(f"{what} needs a stage with {n} colour gate{'s' if n > 1 else ''} "
                         f"(docs/06, World 9); it has {len(gates)}")
    return gates


def _num(rig, name: str, lo: float, hi: float) -> float:
    value = rig.knob(name)
    return float(value) if value is not None else rig.rng.uniform(lo, hi)


def _names(balls) -> list[str]:
    return [b.name for b in balls]


def lit_rule(colours: list[str], hold: float) -> Callable:
    """Shut and unlit until the field comes into the funnel; then lit for
    `colours` (they pass), until `hold` seconds after the first marble
    reached the bar; then open for everyone."""
    def rule(f):
        g = rule.gate
        if g.near is None:
            return "only", []
        if g.arrived is None or f.t - g.arrived < hold:
            return "only", colours
        return "open", []
    return rule


def lock_rule(hold: float) -> Callable:
    """Open until the field reaches it; then shut for the leader's colour
    alone — the lowest marble still racing at that frame, whoever it is —
    for `hold` seconds; then open."""
    state: dict = {"locked": None}

    def rule(f):
        g = rule.gate
        if g.near is None:
            return "open", []
        if state["locked"] is None:
            state["locked"] = [f.names[f.leader]] if f.leader is not None else []
        if g.arrived is None or f.t - g.arrived < hold:
            return "block", state["locked"]
        return "open", []
    return rule


def cycle_rule(order: list[str], period: float, phase: float) -> Callable:
    """Every colour in turn, `period` seconds each, from the start."""
    def rule(f):
        k = int(f.t / period + phase) % len(order)
        return "only", [order[k]]
    return rule


def _set(g: Gate, rule: Callable, look: str = "pass") -> None:
    rule.gate = g
    g.rule = rule
    g.look = look
    g.door.look = look


def random_colour_gate(rig, space, style, balls, w, h, *, gate: int = 0, hold=HOLD_S) -> None:
    """One seeded colour; it passes, everyone else waits (knob `hold`)."""
    gates = _need(rig, "random-colour-gate", gate + 1)
    colour = rig.rng.choice(_names(balls))
    _set(gates[gate], lit_rule([colour], _num(rig, "hold", *hold)))


def three_colour_gates(rig, space, style, balls, w, h) -> None:
    """Three gates, three different seeded colours (one each)."""
    gates = _need(rig, "three-colour-gates", 3)
    names = _names(balls)
    colours = rig.rng.sample(names, min(3, len(names)))
    for k, g in enumerate(gates[:3]):
        _set(g, lit_rule([colours[k % len(colours)]], _num(rig, "hold", *HOLD_SHORT_S)))


def leader_lockout_gate(rig, space, style, balls, w, h, *, gate: int = 0, hold=LOCK_S) -> None:
    """The gate shuts for the leader's colour as the field reaches it."""
    gates = _need(rig, "leader-lockout-gate", gate + 1)
    _set(gates[gate], lock_rule(_num(rig, "lock", *hold)), look="block")


def alliance_gate(rig, space, style, balls, w, h) -> None:
    """Two seeded colours pass together; the rest wait."""
    gates = _need(rig, "alliance-gate")
    colours = rig.rng.sample(_names(balls), 2)
    _set(gates[0], lit_rule(colours, _num(rig, "hold", *HOLD_S)))


def cycling_colour_gate(rig, space, style, balls, w, h, *, gate: int = 0) -> None:
    """Every colour in a seeded order, one a second (knob `period`)."""
    gates = _need(rig, "cycling-colour-gate", gate + 1)
    order = _names(balls)
    rig.rng.shuffle(order)
    period = float(rig.knob("period", CYCLE_S))
    _set(gates[gate], cycle_rule(order, period, rig.rng.random()))


# --- the trapdoor gate (World 2's panel, lit) ----------------------------------------------------

TRAP_OPEN = (2.4, 3.2)   # the panel's cycle, s
TRAP_SHARE = 0.40        # of it open
FINAL_TRAP_SHARE = 0.25  # the final is a race: its trapdoor gate opens less


def colour_trapdoor(rig, space, style, balls, w, h, *, share: float | None = None) -> None:
    """Every trapdoor panel on the stage becomes a colour gate. It cycles
    (shut for World 2's first GRACE_S), and each time it opens it lights one
    colour, drawn from the seed for that opening: that colour's marble rolls
    over the lid as if it were shut, anyone else on it drops into the pit and
    is out. The lid is one door, re-clocked: always solid, passing nobody
    while it is shut and everyone but the lit colour while it is open."""
    panels = w2.panels_of(rig)
    if not panels:
        raise ValueError("colour-trapdoor-gate needs a stage with trapdoor panels (docs/06, World 2)")
    names = _names(balls)
    share = float(rig.knob("open_share", TRAP_SHARE)) if share is None else share
    for p in panels:
        period = rig.rng.uniform(*TRAP_OPEN)
        phase = rig.rng.random()
        picks = [rig.rng.choice(names) for _ in range(40)]  # one per opening, drawn up front
        p.opener = w2.cycling(period, share, phase, after=w2.GRACE_S)
        lit_name, pass_name = f"trapdoor{p.index}_lit", f"trapdoor{p.index}_pass"
        latch = {"n": 0, "now": None}

        def lit(f, p=p, picks=picks, latch=latch):
            # Latched when the lid opens, so a lid held open for a marble
            # falling through it keeps the colour it opened with.
            if not f.values.get(p.open_clock):
                latch["now"] = None
                return []
            if latch["now"] is None:
                latch["now"] = picks[latch["n"] % len(picks)]
                latch["n"] += 1
            return [latch["now"]]

        def passes(f, lit_name=lit_name):
            colour = f.values.get(lit_name) or []
            return [] if not colour else [x for x in f.names if x not in colour]

        rig.clock(lit_name, lit)
        rig.clock(pass_name, passes)
        for d in rig.doors:
            if d.closed == p.shut_clock:
                d.closed, d.passes, d.lights, d.look = None, pass_name, lit_name, "pass"


# --- the breaking gate (L88) ---------------------------------------------------------------------

# What it takes to break the bar: mass x speed into it, in the units of
# make_ball's mass (1.3-1.9 for the regulars, 2.7 for a heavy marble) and
# px/s down. Measured over 48 seeds (docs/06, World 9): at 120 everyone broke
# it about as often; at 200 the heavy marble broke it in 10 of the 20 races
# where it went; at 260 (with L88's box under the bar), in all 10 of 10.
BREAK_P = 260.0
BOX_FOOT = 1.9  # the room under a breaking gate's bar, in marble rooms: the box and air under it
PENALTY_S = 2.5


def gate_breaker(rig, space, style, balls, w, h) -> None:
    """A cycling colour gate that breaks. A marble that meets the bar while
    it is shut for it, with mass x speed into the bar of `strength` or more
    (knob; BREAK_P), smashes it: the bar is gone for good, for everyone, and
    the breaker drops into a penalty box under it — a floor only it lands
    on — for `penalty` s (knob; PENALTY_S), a countdown over the box. The
    rule is the same for every marble; only a heavy one usually has the
    momentum."""
    gates = _need(rig, "gate-breaker")
    g = gates[0]
    order = _names(balls)
    rig.rng.shuffle(order)
    cycle = cycle_rule(order, float(rig.knob("period", CYCLE_S)), rig.rng.random())
    strength = float(rig.knob("strength", BREAK_P))
    penalty = float(rig.knob("penalty", PENALTY_S))
    thick = style.thickness / 2
    state: dict = {"broke": None, "by": None, "last": {}, "landed": None, "peak": {}}

    def rule(f):
        if state["broke"] is not None:
            return "open", []
        return cycle(f)

    _set(g, rule)

    def watch(f):
        last = state["last"]
        if state["broke"] is None:
            shut_for = set(f.names) - set(g.ids) if g.mode == "only" else set()
            for i in _contenders(f):
                x, y = _pos(f, i)
                prev = last.get(i)
                if prev is None or f.names[i] not in shut_for or i in g.crossing:
                    continue
                vy = (prev[1] - y) * f.rig.fps  # speed down, into the bar
                r = _radius(f, i)
                if not (g.x0 - r * 0.5 <= x <= g.x1 + r * 0.5) or not (0 < y - g.y <= r + thick + vy / f.rig.fps + 2):
                    continue
                hit = f.rig.balls[i].body.mass * vy
                state["peak"][i] = max(state["peak"].get(i, 0.0), hit)  # what docs/06 measures
                if vy > 0 and hit >= strength:
                    state["broke"], state["by"] = f.t, i
                    f.rig.emit("gate_broken", i, gate=g.index)
                    break
        state["last"] = {i: _pos(f, i) for i in range(len(f.names))}

    rig.on_frame(watch)
    # The penalty box: a floor a marble's room under the bar that only the
    # breaker stands on, for `penalty` seconds from when it lands.
    floor_y = g.y - marble_room(w) * 1.25

    def box_lit(f):
        i = state["by"]
        if i is None or not f.alive[i]:
            return []
        x, y = _pos(f, i)
        if state["landed"] is None and y < floor_y:
            return []  # it went past the box (never seen): no penalty, and no hold with nobody in it
        if state["landed"] is None and y <= floor_y + _radius(f, i) + thick + 3.0 and g.x0 <= x <= g.x1:
            state["landed"] = f.t
        if state["landed"] is not None and f.t - state["landed"] >= penalty:
            return []
        return [f.names[i]]

    def box_pass(f):
        held = f.values.get("penalty_lit") or []
        return [x for x in f.names if x not in held]

    def box_left(f):
        if state["landed"] is None or not f.values.get("penalty_lit"):
            return None
        return max(1, math.ceil(penalty - (f.t - state["landed"]) - 1e-9))

    rig.clock("penalty_lit", box_lit)
    rig.clock("penalty_pass", box_pass)
    rig.clock("penalty_left", box_left)
    rig.clock("penalty_shut", lambda f: bool(f.values.get("penalty_lit")))
    rig.hold("penalty_shut")
    rig.door(space, (g.x0, floor_y), (g.x1, floor_y), closed="penalty_shut", passes="penalty_pass",
             lights="penalty_lit", look="block", lamps=[(g.x0 - LAMP_OUT, floor_y)], thickness=thick)
    rig.effect("countdown", clock="penalty_left", at=(g.x1 + LAMP_OUT, floor_y))
    rig.breaker = state


# --- the snow levels -----------------------------------------------------------------------------

def snow_colour_gates(rig, space, style, balls, w, h) -> None:
    """The snow track: a random-colour gate, then a cycling gate, on ice."""
    _need(rig, "snow-colour-gates", 2)
    random_colour_gate(rig, space, style, balls, w, h, gate=0, hold=HOLD_SHORT_S)
    cycling_colour_gate(rig, space, style, balls, w, h, gate=1)


def all_gates_snow(rig, space, style, balls, w, h) -> None:
    """The final: a random-colour gate, a reverse gate and a cycling gate on
    ice, and a trapdoor gate between them."""
    _need(rig, "all-gates-snow", 3)
    random_colour_gate(rig, space, style, balls, w, h, gate=0, hold=HOLD_SHORT_S)
    leader_lockout_gate(rig, space, style, balls, w, h, gate=1, hold=HOLD_SHORT_S)
    cycling_colour_gate(rig, space, style, balls, w, h, gate=2)
    if w2.panels_of(rig):
        colour_trapdoor(rig, space, style, balls, w, h, share=float(rig.knob("open_share", FINAL_TRAP_SHARE)))


# --- registration ------------------------------------------------------------------------------

SECTIONS = {"colourgate": colourgate, "icegate": icegate, "boxgate": boxgate}
SECTION_WORDS = {"colourgate": "a colour gate", "icegate": "a colour gate on ice",
                 "boxgate": "a colour gate with a penalty box under it"}
stagekit.SECTIONS.update(SECTIONS)
stagekit.SECTION_WORDS.update(SECTION_WORDS)
