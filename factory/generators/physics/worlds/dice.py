"""World 6, the dice track: a die on screen, rolled by the seed, then a door
that does what the die said.

Every level here is the same promise kept four ways. A die is drawn — a real
face with pips, tumbling, then set — and only after it has landed does the
track change: a gate opens the lane it picked, a blocker goes, the start gate
lets the field go in the order it rolled. A viewer who watches the die can
call what the track will do before it does it, which is the whole point:
the die is the mechanism, so it has to be legible, and it has to be honest.

Honest means docs/08 rule 2.4. Every face comes from `rig.rng` — the seed's
own stream for mechanics, apart from the build's — and nothing reads an
entrant's identity to choose it. The loaded die (L56) always lands on the
hardest lane, which is the same for everybody. The handicap die (L58) draws
among the entrants in the order they stand on screen. The one rule that names
a marble (L59's back marker, the standings leader at plan time) is a rule the
level declares, never a draw; it takes no die.

The geometry is the stage kit's (`stagekit.dicegate`, `runway`, `diceblock`,
`surfaceramps`); what it built is on `style.dice`. The mechanics below only
register doors, dice, holds and surfaces on the round's rig (docs/10).

Timing: the clip opens 0.6 s into the simulation (render.skip_start_s), so a
die rolled at the start rolls at ROLL_AT, just after, and is seen whole. A
field waiting behind a door is a hold (`rig.hold`), not a stall.
"""

from __future__ import annotations

import math

from ...mechanics import SURFACES
from ...stagekit import dice_record

ROLL_AT = 0.65  # s: first frame after the opening skip
ROLL_S = 1.1  # the tumble
OPEN_AFTER = 0.35  # the die sits set this long before its door moves
TUMBLE_FRAMES = 3  # a face every 3 frames while it rolls
GOLD = (236, 190, 72)
# A surface die's faces: ice, sand, plain — painted, so the face says it.
SURFACE_FACES = {1: "ice", 2: "sand", 3: "plain"}
SURFACE_TINTS = {"1": [196, 228, 248], "2": [222, 190, 128]}
SAND_DAMPING = 0.55  # the stock 1.4 holds a marble under the stall speed at gravity -30
HEAD_START_S = 1.2


# --- the die ---------------------------------------------------------------------------------

def roll(rig, name: str, face: int, *, faces: int = 3, at: float | None = None, when=None,
         pos=(60.0, 880.0), size: float = 60.0, layer: str = "top", tints: dict | None = None) -> str:
    """A die on screen: clock `name` is its face (None until it rolls,
    tumbling, then set), `<name>_set` turns true when it lands and
    `<name>_open` OPEN_AFTER later. It rolls at time `at`, or on the first
    frame `when(frame)` holds (the leader nearing a gate: the race's
    progress, never who). The tumble's faces are drawn from `rig.rng` here,
    at registration, so the stream is the same whatever the race does."""
    fps = rig.fps
    n = max(TUMBLE_FRAMES, int(round(ROLL_S * fps)))
    seq, prev = [], None
    for _ in range(n // TUMBLE_FRAMES + 1):
        prev = rig.rng.choice([k for k in range(1, faces + 1) if k != prev])
        seq.append(prev)
    if faces > 1 and seq[-1] == face:
        # Land on a change: the last tumbling face is never the result.
        seq[-1] = next(k for k in range(1, faces + 1) if k != face and (len(seq) < 2 or k != seq[-2]))
    state: dict = {"start": None, "said": False}

    def die(f):
        if state["start"] is None and ((at is not None and f.t >= at) or (when is not None and when(f))):
            state["start"] = f.frame
        if state["start"] is None:
            return None
        k = f.frame - state["start"]
        if k < n:
            return {"f": seq[min(k // TUMBLE_FRAMES, len(seq) - 1)], "s": "roll"}
        return {"f": face, "s": "set"}

    rig.clock(name, die)
    rig.clock(name + "_set", lambda f: state["start"] is not None and f.frame - state["start"] >= n)
    rig.clock(name + "_open", lambda f: state["start"] is not None
              and f.frame - state["start"] >= n + int(round(OPEN_AFTER * fps)))

    def said(f):
        if not state["said"] and f.value(name + "_set"):
            state["said"] = True
            rig.emit("rolled", None, face=face, die=name)

    rig.on_frame(said)
    rig.effect("die", clock=name, at=pos, size=size, layer=layer, **({"tints": tints} if tints else {}))
    return name


def marker(rig, name: str, face: int, die: str, *, lit: bool, pos, size: float = 26.0,
           layer: str = "under", dim_others: bool = True) -> None:
    """A small fixed die face labelling what a die can pick (a lane, a
    blocker, a marble's cup): plain until the die lands, then lit if it was
    picked and dimmed if not."""
    after = "lit" if lit else ("dim" if dim_others else "set")
    rig.clock(name, lambda f: {"f": face, "s": after if f.value(die + "_set") else "set"})
    rig.effect("die", clock=name, at=pos, size=size, layer=layer)


def _leader_below(y: float):
    """A trigger: the leader (the lowest marble still racing) is below y."""
    return lambda f: f.leader is not None and f.positions[f.leader][1] < y


# --- a gate ------------------------------------------------------------------------------------

def gate(rig, space, style, k: int, *, loaded: bool = False, at: float | None = None, when=None,
         die_size: float = 60.0) -> int:
    """Gate k of the stage: its die picks a lane (1 left, 2 middle, 3 right);
    the hold door across the throat opens once it has landed, with the flap
    for that lane solid (neither, for the middle). Returns the lane index.
    `loaded`: the die lands on the lane with the shelves (the long way)."""
    g = dice_record(style)["gates"][k]
    lane = g["kinds"].index("shelves") if loaded and "shelves" in g["kinds"] else rig.rng.randrange(3)
    name = f"gate{k}"
    if at is None and when is None:
        # The leader has reached the hold: the field gathers while it rolls.
        when = _leader_below(g["throat"] + 60.0)
    roll(rig, name, lane + 1, at=at, when=when, pos=g["die"], size=die_size)
    rig.clock(name + "_hold", lambda f: not f.value(name + "_open"))
    # Held on purpose only once the die is rolling: before that nobody is at the gate.
    rig.clock(name + "_wait", lambda f: f.value(name) is not None and not f.value(name + "_open"))
    rig.hold(name + "_wait")
    # The section's doors, re-clocked: the die, not the plain wait, opens the
    # throat, and the lane it picked is the one whose doors shut.
    if g["plain"] + "_wait" in rig.holds:
        rig.holds.remove(g["plain"] + "_wait")
    g["hold_door"].closed, g["hold_door"].color = name + "_hold", GOLD
    for j, doors in enumerate(g["path_doors"]):
        for door in doors:
            door.closed, door.color = (name + "_set" if j == lane else "dice_never"), GOLD
    for j, pos in enumerate(g["marks"]):
        marker(rig, f"{name}_lane{j}", j + 1, name, lit=j == lane, pos=pos, size=24.0)
    state = {"open": False}

    def opened(f):
        if not state["open"] and f.value(name + "_open"):
            state["open"] = True
            rig.emit("gate_opened", None, lane=lane + 1, gate=k)

    rig.on_frame(opened)
    return lane


# --- a start gate on the runway, and cups ----------------------------------------------------

def _slots(style, balls, order: list[int]):
    """Positions on the runway (and its closed door) for the marbles in
    `order`, front first: the front marble against the left wall, each next
    one a marble's width further up the slope. Returns (index, x, y, slot
    centre on the ramp line)."""
    rw = dice_record(style)["runway"]
    if rw is None:
        raise ValueError("a grid start needs a stage with a runway")
    (ax, ay), (dx, dy) = rw["a"], rw["b"]
    length = math.hypot(ax - dx, ay - dy)
    ux, uy = (ax - dx) / length, (ay - dy) / length
    nx, ny = (-uy, ux) if ux > 0 else (uy, -ux)  # the ramp's upward normal, either way it rises
    big = max(b.radius for b in balls)
    thick = style.thickness / 2
    out = []
    for k, i in enumerate(order):
        s = 1.6 * big + 6.0 + k * (2 * big + 3.0)  # the front one clear of the lip
        r = balls[i].radius
        cx, cy = dx + ux * s, dy + uy * s
        out.append((i, cx + nx * (r + thick + 1.0), cy + ny * (r + thick + 1.0), (cx, cy), (nx, ny)))
    return out


def grid(rig, space, style, balls, *, dice: bool = True, back: str | None = None) -> list[int]:
    """The field lined up on the runway behind its door. With `dice`, every
    marble rolls a die (drawn above its slot) and the highest roll starts at
    the front, ties in a seeded order; `back` (an entrant id the level names
    as a rule) starts last and rolls nothing. Without `dice` the order is a
    seeded shuffle. The door opens once every die has landed."""
    n = len(balls)
    names = [b.name for b in balls]
    rolls = [rig.rng.randint(1, 6) for _ in balls]
    ties = [rig.rng.random() for _ in balls]
    racing = [i for i in range(n) if names[i] != back]
    if dice:
        order = sorted(racing, key=lambda i: (-rolls[i], ties[i]))
    else:
        order = sorted(racing, key=lambda i: ties[i])
    order += [i for i in range(n) if names[i] == back]
    last = None
    for k, (i, x, y, _c, _n) in enumerate(_slots(style, balls, order)):
        ball = balls[i]
        ball.body.position = (x, y)
        ball.body.velocity = (0.0, 0.0)
        ball.body.angular_velocity = 0.0
        if dice and names[i] != back:
            big = max(b.radius for b in balls)
            last = roll(rig, f"grid{k}", rolls[i], faces=6, at=ROLL_AT + 0.06 * k,
                        pos=(x, y + big + 30.0), size=34.0)
    rw = dice_record(style)["runway"]
    opens = (last + "_open") if last else None
    if opens is None:
        rig.at("grid_go", t=ROLL_AT + 0.4, before=False, after=True)
        opens = "grid_go"
    rig.clock("grid_hold", lambda f: not f.value(opens))
    rig.hold("grid_hold")
    for a, b in ((rw["a"], rw["b"]), rw["lip"]):
        rig.door(space, a, b, closed="grid_hold", color=GOLD)
    return order


def cups(rig, space, balls, *, closed: str, passes: dict | None = None) -> None:
    """A start gate for a field in its ordinary start row: a V of two door
    segments under every marble, closed while `closed` is truthy. `passes`
    maps a marble index to a clock of ids let through early (a head start).
    The marbles are set down at rest in their cups."""
    for i, b in enumerate(balls):
        x, y = b.body.position
        vy = y - b.radius - 10.0
        for a, c in (((x - 36.0, vy + 18.0), (x, vy)), ((x, vy), (x + 36.0, vy + 18.0))):
            rig.door(space, a, c, closed=closed, passes=(passes or {}).get(i), color=GOLD)
        b.body.velocity = (0.0, 0.0)
        b.body.angular_velocity = 0.0
    rig.hold(closed)


# --- the level mechanics ---------------------------------------------------------------------
# apply(rig, space, style, balls, w, h), registered in physics/registry.py.

def dice_gate_paths(rig, space, style, balls, w, h):
    """L51: a dice gate picks one of three lanes each run; every gate on the
    stage has its own die (the first rolls at the start, the rest as the
    leader nears them)."""
    loaded = bool(rig.knob("loaded", False))
    for k in range(len(dice_record(style)["gates"])):
        gate(rig, space, style, k, loaded=loaded, at=ROLL_AT if k == 0 else None)


def loaded_dice(rig, space, style, balls, w, h):
    """L56: the same gates, and every die lands on the hardest lane (the
    shelves). The same for everyone: it is the lane that is chosen, not a
    marble."""
    for k in range(len(dice_record(style)["gates"])):
        gate(rig, space, style, k, loaded=True, at=ROLL_AT if k == 0 else None)


def dice_start_grid(rig, space, style, balls, w, h):
    """L52: every marble rolls; the highest starts at the front of the grid."""
    grid(rig, space, style, balls, dice=True)


def handicap_back_start(rig, space, style, balls, w, h):
    """L59: the grid is rolled as L52's, except the level's `back_marker`
    (mechanics knob: an entrant id, the standings leader at plan time — a
    rule the level declares) starts last and rolls nothing."""
    back = rig.knob("back_marker")
    grid(rig, space, style, balls, dice=True, back=str(back) if back else None)


def dice_remove_obstacle(rig, space, style, balls, w, h):
    """L53: six blockers, each labelled with a die face; the die removes one.
    The field waits in its start cups until the die has landed."""
    blocks = dice_record(style)["blocks"]
    if len(blocks) != 6:
        raise ValueError("dice-remove-obstacle needs a stage with six blockers (diceblock)")
    face = rig.rng.randint(1, 6)
    roll(rig, "block_die", face, faces=6, at=ROLL_AT, pos=(38.0, h - 62.0), size=50.0)
    rig.clock("block_on", lambda f: not f.value("block_die_set"))
    rig.clock("start_hold", lambda f: not f.value("block_die_open"))
    for k, (a, b, door) in enumerate(blocks):
        # The section built each blocker as a door that is always shut; the
        # die's face is the one that opens.
        door.closed = "block_on" if k + 1 == face else None
        door.color = GOLD
        mid = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2 + 22.0)
        marker(rig, f"block{k}", k + 1, "block_die", lit=k + 1 == face, pos=mid, size=24.0,
               layer="top", dim_others=False)
    cups(rig, space, balls, closed="start_hold")

    state = {"said": False}

    def removed(f):
        if not state["said"] and f.value("block_die_set"):
            state["said"] = True
            rig.emit("blocker_removed", None, blocker=face)

    rig.on_frame(removed)


def dice_gates_duel(rig, space, style, balls, w, h):
    """L54: three dice gates in a row on one track, each with its own die.
    A later gate's die rolls as soon as the leader is through the gate
    above, so it lands while the field falls to it: three full holds made
    the clip run 21 s at the median."""
    gates = dice_record(style)["gates"]
    for k in range(len(gates)):
        gate(rig, space, style, k, at=ROLL_AT if k == 0 else None,
             when=None if k == 0 else _leader_below(gates[k - 1]["throat"] - 30.0), die_size=48.0)


def dice_round_count(rig, space, style, balls, w, h):
    """L55: in the heat, a die with faces one to three sets how many rounds
    the clip runs (`rig.clip_rounds`; the level asks for three at most). The
    field waits on the runway, in a seeded order, until it lands. Later
    rounds start from the runway with no die."""
    if rig.round == 0:
        count = rig.rng.randint(1, 3)
        rig.clip_rounds = count
        roll(rig, "rounds_die", count, faces=3, at=ROLL_AT, pos=(w * 0.5, h - 70.0), size=64.0)
        _hold_runway(rig, space, style, balls, "rounds_die_open")
    else:
        rig.at("go", t=ROLL_AT, before=False, after=True)
        _hold_runway(rig, space, style, balls, "go")


def _hold_runway(rig, space, style, balls, opens: str) -> None:
    order = sorted(range(len(balls)), key=lambda i: rig.rng.random())
    for i, x, y, _c, _n in _slots(style, balls, order):
        balls[i].body.position = (x, y)
        balls[i].body.velocity = (0.0, 0.0)
        balls[i].body.angular_velocity = 0.0
    rig.clock("runway_hold", lambda f: not f.value(opens))
    rig.hold("runway_hold")
    rw = dice_record(style)["runway"]
    for a, b in ((rw["a"], rw["b"]), rw["lip"]):
        rig.door(space, a, b, closed="runway_hold", color=GOLD)


def surface_die(rig, name: str, band: tuple[float, float], w: float, *, at=None, when=None,
                pos, size: float = 44.0) -> str:
    """A die with painted faces (ice, sand, plain) whose landing lays that
    surface over a band: a zone that appears when the die lands. Ice sets a
    marble's own friction to nothing while it is inside; sand drags."""
    face = rig.rng.randint(1, 3)
    roll(rig, name, face, at=at, when=when, pos=pos, size=size, tints=SURFACE_TINTS)
    top, bottom = band
    rect = (7.0, bottom - 20.0, w - 7.0, top + 20.0)
    kind = SURFACE_FACES[face]
    if kind == "ice":
        rig.zone(rect, kind="ice", friction=0.0, damping=0.0, when=name + "_set", appear=True)
    elif kind == "sand":
        rig.zone(rect, kind="sand", damping=SAND_DAMPING, friction=SURFACES["sand"]["friction"],
                 when=name + "_set", appear=True)
    return kind


def dice_surface(rig, space, style, balls, w, h):
    """L57: each ramp band's surface is rolled live — ice, sand or plain. The
    first band's die rolls at the start while the field waits in its cups;
    each later band's rolls as the leader comes within reach of it."""
    bands = dice_record(style)["bands"]
    for k, band in enumerate(bands):
        pos = (34.0, band[0] - 10.0)
        if k == 0:
            surface_die(rig, f"surface{k}", band, w, at=ROLL_AT, pos=pos)
        else:
            surface_die(rig, f"surface{k}", band, w, when=_leader_below(band[0] + 190.0), pos=pos)
    if bands:
        rig.clock("start_hold", lambda f: not f.value("surface0_open"))
        cups(rig, space, balls, closed="start_hold")


def handicap_start(rig, space, style, balls, w, h):
    """L58: the field waits in its start cups; a die numbered for the cups,
    left to right as they stand on screen, picks one marble, whose cup lets
    it go `head_start_s` (knob, default 1.2 s) before everyone else's. A draw
    among the entrants: which marble, the seed says."""
    n = len(balls)
    screen = sorted(range(n), key=lambda i: balls[i].body.position.x)
    pick = rig.rng.randrange(n)  # a place in the screen order, not an entrant
    chosen = screen[pick]
    head = float(rig.knob("head_start_s", HEAD_START_S))
    roll(rig, "head_die", pick + 1, faces=n, at=ROLL_AT, pos=(36.0, h - 60.0), size=48.0)
    fps = rig.fps
    state = {"at": None}

    def go_all(f):
        if state["at"] is None and f.value("head_die_open"):
            state["at"] = f.frame
            rig.emit("head_start", chosen)
        return state["at"] is None or f.frame - state["at"] < int(round(head * fps))

    rig.clock("start_hold", go_all)
    name = balls[chosen].name
    rig.clock("head_pass", lambda f: [name] if f.value("head_die_open") else [])
    for rank, i in enumerate(screen):
        x, _ = balls[i].body.position
        marker(rig, f"cup{rank}", rank + 1, "head_die", lit=i == chosen, pos=(x, h - 96.0), size=22.0,
               layer="top")
    cups(rig, space, balls, closed="start_hold", passes={chosen: "head_pass"})


def dice_final(rig, space, style, balls, w, h):
    """L60, every dice mechanic at once: a rolled grid on the runway, a die
    for how many rounds (heat only), and the dice gate's path die together
    with a surface die for its lanes, both rolled as the leader nears it."""
    grid(rig, space, style, balls, dice=True)
    if rig.round == 0:
        count = rig.rng.randint(1, 3)
        rig.clip_rounds = count
        # Past the back of the grid, clear of the grid's own dice.
        back_right = dice_record(style)["runway"]["a"][0] > w / 2
        roll(rig, "rounds_die", count, faces=3, at=ROLL_AT, pos=(w - 56.0 if back_right else 56.0, h - 64.0),
             size=56.0)
    g = dice_record(style)["gates"][0]
    near = _leader_below(g["throat"] + 60.0)
    gate(rig, space, style, 0, when=near)
    surface_die(rig, "lanes_surface", (g["lane_top"], g["lane_bottom"]), w, when=near,
                pos=(g["die"][0] + 72.0, g["die"][1] - 26.0), size=40.0)
