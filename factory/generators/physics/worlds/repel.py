"""World 8, Repel Race (Season 0, L71-L80): marbles that push each other apart.

Every level here is one force, `Rig.pair_force`: every pair of marbles
pushes apart (or, on L76, pulls together) along the line between them, a
multiple of the stage's gravity at contact and nothing past REACH times their
summed radii — the magnet's softened law, so a push is felt before contact
and never flings anything across the frame. Two choices made it honest:

- **Equal and opposite** (`newton=True`). A pair's two forces are the same
  size, so the heavier marble of a pair is shoved less. Each marble's share
  of the force is its cast trait `charge` (default 1): Ember's is the
  biggest, so a pair with Ember in it pushes hardest, and its mass is why it
  gives way least.
- **Not a field Ember ignores** (`skip_immune=False`). Ember is immune to
  magnets and wind (its `force_immune`). Marble-to-marble repulsion is
  neither: it is the other marbles, so Ember feels it like everyone else,
  scaled by its mass.

The force is drawn (`rig.effect("field")`): facing arcs between two marbles
that brighten as they close, a dotted tether when they pull. A push nobody
can see reads as marbles bouncing off air.

The geometry is here too: a corridor one marble wide (`corridor`, built by
the mechanic from the marbles' own radii, so it is one wide whatever the
seed drew), two lanes that merge (`twinlanes` + `merge`), a funnel with pits
at its edges (`edgepits`), a single long ramp (`ramp`), and a lane for the
blocker (`lane`). Nothing here reads who a marble is (docs/08 rule 2.4): the
one rule that picks a marble, L74's blocker, picks the heaviest by mass — a
property the level declares, never a name.
"""

from __future__ import annotations

import math

from ... import stagekit
from ...mechanics import rig_of
from ...stagekit import _peg, _wall, marble_room

# The push: STRENGTH x gravity at the law's peak, felt out to REACH x the
# pair's summed radii (the law is ~0.44 of its peak at contact).
STRENGTH = 1.6
REACH = 3.0
SOFT = 1.0
SHOW_REACH = 2.3  # the drawn field: where the push is strong enough to see
# L73: off for the first half, then a jolt (KICK for KICK_S) and the push.
SWITCH_AT = 0.5
KICK = 6.0
KICK_S = 0.35
PACK_PULL = 0.3  # L73's first half: the pull that keeps the pack tight (x gravity)
PACK_REACH = 5.0
# L76: the pull (a negative strength).
PULL = 1.2
THICK = 5.0  # a corridor wall's radius (pymunk)
CORRIDOR_SLOPE = 0.22
CORRIDOR_GAP = 2.3  # inner width, in radii of the biggest marble: one wide, no passing
MERGE_SLOPE = 0.5  # shallow: two marbles arriving together stand off, and one is pushed back
# L78's lane pegs: bumper-sized and lively, so two marbles in two lanes take
# turns in front (small pegs: 1.1-1.4 lead changes a race).
LANE_PEG_R = (7.0, 9.0)
LANE_BOUNCE = 0.62
LANE_ROW = (66.0, 76.0)  # px between peg rows in a lane
CORRIDOR_FRICTION = 0.1
LANE_ROOMS = 2.7  # L74's lane, in marble rooms: two abreast only just
LANE_HOPPER = 0.9  # its funnel's slope: steep, so nothing waits on it
HOPPER_SLOPE = 0.5


def repel(rig, strength: float | None = None, *, when: str | None = None, sign: int = 1) -> None:
    """Every pair of marbles pushes apart (`sign` -1: pulls together), drawn."""
    s = float(rig.knob("strength", strength if strength is not None else STRENGTH))
    rig.pair_force(sign * s, reach=float(rig.knob("reach", REACH)), soft=SOFT, trait="charge",
                   when=when, skip_immune=False, newton=True)
    rig.effect("field", clock=when, reach=min(SHOW_REACH, float(rig.knob("reach", REACH))), sign=sign)


# --- geometry ------------------------------------------------------------------------------

def _record(style) -> dict:
    return rig_of(style).__dict__.setdefault("repel", {})


def corridor_band(space, w, top, bottom, rng, style):
    """A band kept for a one-marble-wide corridor. The walls are the
    mechanic's (`build_corridor`): only it knows the marbles' radii, and a
    corridor sized for the biggest marble a seed can draw lets two of the
    smallest pass. The section builds it for the biggest marble the kit
    draws (`stagekit.MARBLE_R`), so the stage races without its mechanic; the
    mechanic rebuilds it for the marbles actually racing."""
    _record(style)["corridor"] = (top, bottom)
    build_corridor(rig_of(style), space, style, None, w)
    return []


def twinlanes(space, w, top, bottom, rng, style):
    """Two lanes split by a wall down the middle of the band, each with its
    own offset rows of pegs (two, then one), so each marble's way down is its
    own and the lead goes back and forth. A level that wants a lane per
    starting side from the very top (L78) runs the wall on up to the ceiling
    in its mechanic (`lane_split`)."""
    _record(style)["twinlanes_top"] = top
    _wall(space, (w / 2, top), (w / 2, bottom), thickness=THICK)
    # The last row stays a marble's room over the band's bottom: a row on
    # it, over the merge's arm starting at the wall below, made a cradle
    # of peg, arm and wall (L78, seed 712).
    low = bottom + marble_room(w) * 1.2
    height = top - low
    rows = max(2, int(height // rng.uniform(LANE_ROW[0], LANE_ROW[1])) + 1)
    r = rng.uniform(LANE_PEG_R[0], LANE_PEG_R[1])
    for side in (0, 1):
        x0, x1 = (10.0, w / 2 - THICK) if side == 0 else (w / 2 + THICK, w - 10.0)
        span = x1 - x0
        shift = rng.uniform(-8, 8)
        for i in range(rows):
            y = top - height * i / max(rows - 1, 1) - (height / max(rows - 1, 1) / 2 if side else 0.0)
            if y < low - 1.0:
                continue
            xs = [x0 + span * 0.28 + shift, x0 + span * 0.72 + shift] if (i + side) % 2 == 0 else [x0 + span / 2 + shift]
            for x in xs:
                _peg(space, x, y, r, elasticity=LANE_BOUNCE)
                style.circles.append((x, y, r))
    return [((w / 2, top), (w / 2, bottom))]


def style_h(style) -> float:
    return float(getattr(rig_of(style), "h", 960) or 960)


def edgepits(space, w, top, bottom, rng, style):
    """A funnel whose walls stop short of the frame's walls: at each edge a
    pit mouth a marble drops into and is out of the race. Pegs over it."""
    room = marble_room(w)
    mouth = room * rng.uniform(0.95, 1.1)
    cx = w / 2 + rng.uniform(-0.04, 0.04) * w
    gap = w * rng.uniform(0.20, 0.22)
    x_left, x_right = 10.0 + mouth, w - 10.0 - mouth
    run = max(cx - gap / 2 - x_left, x_right - (cx + gap / 2))
    drop = min(top - bottom - 20.0, run * 0.46)
    throat = top - drop
    lip = 26.0  # a short rim on the pit side so a marble on the wall's end is not balanced
    segs = [((x_left, top + lip * 0.0), (cx - gap / 2, throat)), ((x_right, top), (cx + gap / 2, throat))]
    for a, b in segs:
        _wall(space, a, b, thickness=style.thickness / 2)
    pits = _record(style).setdefault("pits", [])
    depth = min(drop, 90.0)
    pits.append((7.0, top - depth, x_left - style.thickness / 2, top + 10.0))
    pits.append((x_right + style.thickness / 2, top - depth, w - 7.0, top + 10.0))
    return segs


def ramp(space, w, top, bottom, rng, style):
    """One long ramp across the band, from one wall toward the other, slope
    0.32-0.38: World 8's ramps, where the heaviest marble is weakest."""
    height = top - bottom
    slope = rng.uniform(0.32, 0.38)
    span = min(height / slope, w - 90.0)
    rec = _record(style)
    k = rec.get("ramps", 0)
    rec["ramps"] = k + 1
    starts_left = (k % 2 == 0) != (rng.random() < 0.5)
    y = (top + bottom) / 2 + span * slope / 2
    a, b = ((26.0, y), (26.0 + span, y - span * slope)) if starts_left else \
        ((w - 26.0, y), (w - 26.0 - span, y - span * slope))
    _wall(space, a, b, thickness=style.thickness / 2)
    return [(a, b)]


def lane(space, w, top, bottom, rng, style):
    """A lane LANE_ROOMS marbles' room wide down the middle of the band, fed
    by a steep funnel from both walls: room to get round a marble, not much
    more. L74's blocker starts in its mouth."""
    room = marble_room(w)
    width = room * LANE_ROOMS
    x0, x1 = w / 2 - width / 2, w / 2 + width / 2
    mouth = max(bottom + room, top - (x0 - 14.0) * LANE_HOPPER)
    segs = [((14.0, top), (x0, mouth)), ((w - 14.0, top), (x1, mouth)),
            ((x0, mouth), (x0, bottom)), ((x1, mouth), (x1, bottom))]
    for a, b in segs:
        _wall(space, a, b, thickness=style.thickness / 2)
    _record(style)["lane"] = (x0, x1, mouth, bottom)
    return segs


def merge_band(space, w, top, bottom, rng, style):
    """A band kept for the merge: a funnel from both walls into a throat one
    marble wide (`build_merge`), built for the kit's biggest marble and
    rebuilt by the mechanic from the marbles' radii."""
    _record(style).setdefault("merges", []).append((top, bottom))
    build_merge(rig_of(style), space, style, None, w)
    return []


SECTIONS = {"corridor": corridor_band, "twinlanes": twinlanes, "edgepits": edgepits, "ramp": ramp, "lane": lane,
            "merge": merge_band}
SECTION_WORDS = {
    "corridor": "a corridor one marble wide",
    "twinlanes": "two lanes of pegs split by a wall",
    "edgepits": "a funnel with a pit at each edge",
    "ramp": "a long ramp",
    "lane": "a lane two marbles wide",
    "merge": "a merge one marble wide",
}
stagekit.SECTIONS.update(SECTIONS)
stagekit.SECTION_WORDS.update(SECTION_WORDS)


def _fallback_r(w: float) -> float:
    return w * stagekit.MARBLE_R


def _clear(rig, space, key: str) -> list:
    """Take out the doors an earlier build of this geometry registered (the
    section's, sized for the kit's biggest marble), so the mechanic's build
    for the marbles racing replaces it."""
    rec = rig.__dict__.setdefault("repel", {})  # what `_record(style)` reads
    for door in rec.pop(key, []):
        if door in rig.doors:
            rig.doors.remove(door)
            if door.shape in space.shapes:
                space.remove(door.shape)
    return rec.setdefault(key, [])


def build_corridor(rig, space, style, balls, w) -> dict:
    """The corridor's walls, one marble wide for the marbles actually racing:
    a hopper from both walls to an opening in the middle, a pocket under it,
    then legs of slope CORRIDOR_SLOPE turning at the frame's walls, as many as
    the band holds. Each wall is a `rig.door` that is always shut (a door is
    the one wall a mechanic can add once the marbles exist), in the
    structure's colour."""
    band = _record(style).get("corridor")
    if band is None:
        raise ValueError("this mechanic needs a stage with the corridor section")
    top, bottom = band
    r = max(b.radius for b in balls) if balls else _fallback_r(w)
    inner = CORRIDOR_GAP * r
    s = float(rig.knob("slope", CORRIDOR_SLOPE))
    doors = _clear(rig, space, "corridor_doors")
    cos = 1.0 / math.hypot(1.0, s)
    g = (inner + 2 * THICK) / cos  # floor to ceiling, centrelines, vertically
    colour = tuple(style.structure)
    walls: list = []

    def wall(a, b):
        seg = rig.door(space, a, b, color=colour, thickness=THICK)
        doors.append(rig.doors[-1])
        # Smooth: in a tube a marble touches floor and ceiling, and at the
        # kit's 0.30 the queue behind the hopper crawled (parked 15%).
        seg.friction = float(rig.knob("wall_friction", CORRIDOR_FRICTION))
        walls.append((a, b))

    left_face, right_face = 10.0, w - 10.0  # the frame walls' inner faces
    xo0, xo1 = w / 2 - inner / 2, w / 2 + inner / 2
    y_open = top - HOPPER_SLOPE * (xo0 - 14.0)
    wall((14.0, top), (xo0 - THICK, y_open))
    wall((w - 14.0, top), (xo1 + THICK, y_open))
    # The pocket under the opening: a back wall under the left lip; the first
    # leg's floor runs right from it, its ceiling from the right lip.
    x_start, going = xo0 - THICK, 1
    yf = y_open - g - 0.4 * r
    x_ceil = xo1 + THICK
    wall((xo0 - THICK, y_open), (xo0 - THICK, yf))
    wall((x_ceil, y_open), (x_ceil, yf + g - s * (x_ceil - x_start)))
    legs = 0
    while True:
        outer = right_face if going > 0 else left_face
        x_end = outer - going * (inner + 2 * THICK)
        y_end = yf - s * abs(x_end - x_start)
        floor = lambda x, _x0=x_start, _y0=yf: _y0 - s * abs(x - _x0)  # noqa: E731
        wall((x_start, yf), (x_end, y_end))
        # The ceiling runs on to the frame's wall, closing the turn above.
        wall((x_ceil, floor(x_ceil) + g), (outer, floor(outer) + g))
        legs += 1
        # The turn: down the shaft to a floor that starts at the frame's wall
        # and passes under this leg's end with a wall's room to spare.
        under = y_end - 2 * THICK - 4.0 - g
        shaft = abs(outer - x_end)
        y_next = under + s * shaft
        run_next = right_face - left_face - inner - 2 * THICK
        if y_next - s * run_next - THICK < bottom:
            break
        x_start, yf, x_ceil, going = outer, y_next, x_end, -going
    rec = _record(style)
    rec["corridor_walls"] = walls
    rec["corridor_legs"] = legs
    rec["corridor_inner"] = inner
    rec["corridor_entry"] = y_open
    return rec


def build_merge(rig, space, style, balls, w) -> dict:
    """Each merge band: a funnel from both walls into a throat CORRIDOR_GAP
    radii of the biggest marble wide, with a short neck under it — one at a
    time. Built here because only the mechanic knows the marbles' radii."""
    bands = _record(style).get("merges")
    if not bands:
        raise ValueError("this mechanic needs a stage with the merge section")
    r = max(b.radius for b in balls) if balls else _fallback_r(w)
    inner = CORRIDOR_GAP * r
    colour = tuple(style.structure)
    doors = _clear(rig, space, "merge_doors")
    rec = _record(style)
    offsets = rec.setdefault("merge_offsets", [])
    throats = []
    for k, (top, bottom) in enumerate(bands):
        # Off the middle by a seeded few px: a throat drops every marble on
        # the same line, and a peg straight under it balanced one (seed 707).
        # Drawn once, so a rebuild keeps the place and the stream.
        if k >= len(offsets):
            offsets.append(rig.rng.choice((-1, 1)) * rig.rng.uniform(14.0, 24.0))
        cx = w / 2 + offsets[k]
        x0, x1 = cx - inner / 2 - THICK, cx + inner / 2 + THICK
        run_l, run_r = x0 - 14.0, w - 14.0 - x1
        y = max(bottom + 1.4 * r, top - MERGE_SLOPE * max(run_l, run_r))
        neck = min(1.4 * r, y - bottom)
        for a, b in (((14.0, y + MERGE_SLOPE * run_l), (x0, y)), ((w - 14.0, y + MERGE_SLOPE * run_r), (x1, y)),
                     ((x0, y), (x0, y - neck)), ((x1, y), (x1, y - neck))):
            rig.door(space, a, b, color=colour, thickness=THICK)
            doors.append(rig.doors[-1])
        throats.append((x0, x1, y))
    rec = _record(style)
    rec["merge_throats"] = throats
    return rec


# --- the mechanics a level names (`params.section`) -------------------------------------------

def marble_repulsion(rig, space, style, balls, w, h):
    """L71: every marble pushes every other apart, all race."""
    repel(rig)


def single_file_corridor(rig, space, style, balls, w, h):
    """L72: a corridor one marble wide for the lower two thirds of the
    stage, and the push, which keeps a gap between the marbles in it."""
    build_corridor(rig, space, style, balls, w)
    repel(rig)


def repulsion_switch(rig, space, style, balls, w, h):
    """L73: until the leader is SWITCH_AT of the way down, a pull (PACK_PULL
    x gravity at the peak, felt out to PACK_REACH x the pair's radii, drawn
    as tethers) that keeps the field a tight pack; then it lets go, and the
    push comes on with a jolt (KICK x the push for KICK_S s), with a
    `repulsion_on` event at the switch."""
    at = float(rig.knob("switch_at", SWITCH_AT))
    kick, kick_s = float(rig.knob("kick", KICK)), float(rig.knob("kick_s", KICK_S))
    state: dict = {}

    def on(f):
        if f.progress < at:
            return 0
        if "t" not in state:
            state["t"] = f.t
            rig.emit("repulsion_on", None, at=at)
        return kick if f.t - state["t"] < kick_s else 1

    rig.clock("packing", lambda f: f.progress < at)
    rig.clock("repulsion", on)
    reach = float(rig.knob("pack_reach", PACK_REACH))
    rig.pair_force(-float(rig.knob("pack_pull", PACK_PULL)), reach=reach, soft=SOFT, trait="charge",
                   when="packing", skip_immune=False, newton=True)
    rig.effect("field", clock="packing", reach=min(SHOW_REACH, reach), sign=-1)
    repel(rig, when="repulsion")


def repulsion_bumpers(rig, space, style, balls, w, h):
    """L75: the push, on the pinball stage (bumpers, rocking planks, funnel)."""
    repel(rig)


def marble_attraction(rig, space, style, balls, w, h):
    """L76: the pull instead of the push (PULL x gravity at the peak): a
    marble close behind another is pulled on toward it, and the one in front
    is pulled back — the slipstream the level is about."""
    repel(rig, float(rig.knob("pull", PULL)), sign=-1)


def lane_split(rig, space, style, w, h) -> None:
    """The lanes' wall on up from the twinlanes band to the ceiling, so each
    marble keeps the lane on its starting side from the first frame."""
    top = _record(style).get("twinlanes_top")
    if top is None:
        raise ValueError("merge-point needs a stage with the twinlanes section")
    rig.door(space, (w / 2, h - 2), (w / 2, top), color=tuple(style.structure), thickness=THICK)


def merge_point(rig, space, style, balls, w, h):
    """L78: two lanes, one marble each, merging through a gap one marble
    wide, and the push at the merge: on while two marbles are both in a merge
    band (its funnel down to the bottom of its neck), off elsewhere. The first
    into the gap takes it; the push shoves the second back up the funnel.
    Only at the merge: a leader below the gap pushing up on the one above it
    held that one over the gap for seconds (L78, seeds 712 and 727)."""
    lane_split(rig, space, style, w, h)
    rec = build_merge(rig, space, style, balls, w)
    bands = [(top, x0, x1, y) for (top, _bottom), (x0, x1, y) in zip(rec["merges"], rec["merge_throats"])]
    r = max(b.radius for b in balls)

    def at_merge(f):
        for top, _x0, _x1, y in bands:
            low = y - 1.4 * r - r
            inside = [i for i, (px, py) in enumerate(f.positions)
                      if f.alive[i] and f.names[i] not in f.finished and low <= py <= top + r]
            if len(inside) >= 2:
                return True
        return False

    rig.clock("merging", at_merge)
    repel(rig, when="merging")


def repulsion_gauntlet(rig, space, style, balls, w, h):
    """L79: the push on a stage of funnels with a pit at each edge: a marble
    in a pit is out (`pitted`)."""
    pits = _record(style).get("pits")
    if not pits:
        raise ValueError("repulsion-gauntlet needs a stage with the edgepits section")
    for rect in pits:
        rig.out_zone(rect, event="pitted", label="pit")
    repel(rig)


def repel_final(rig, space, style, balls, w, h):
    """L80: the push on a stage of three long ramps."""
    repel(rig)


def heaviest(balls) -> int:
    """The heaviest marble in the field, by mass (ties: the first). A
    property the level's rule names, never an identity."""
    return max(range(len(balls)), key=lambda i: (balls[i].body.mass, -i))


def heavy_blocker(rig, space, style, balls, w, h):
    """L74: the heaviest marble takes the start slot nearest the middle —
    straight over the lane's mouth — so it drops into the lane first and
    the others have to get round it; then the push. With `ahead` (in its
    radii) it starts that far down inside the mouth instead. The ramps
    under the lane are where it is slow (its friction, cast.toml)."""
    rec = _record(style).get("lane")
    if rec is None:
        raise ValueError("heavy-blocker needs a stage with the lane section")
    x0, x1, mouth, _bottom = rec
    k = heaviest(balls)
    big = balls[k]
    ahead = rig.knob("ahead")
    if ahead is not None:
        big.body.position = (w / 2, mouth + big.radius * float(ahead))
        big.body.velocity = (0.0, -60.0)
    else:
        mid = min(range(len(balls)), key=lambda i: abs(balls[i].body.position.x - w / 2))
        if mid != k:
            a, b = balls[k].body, balls[mid].body
            a.position, b.position = b.position, a.position
    rig.emit("blocker_set", k)
    repel(rig)
