"""World 5, Ice vs Sand (Season 0, L41-L50): terrain a marble feels.

Every section in the kit before this one changed a race by being in the
way. These change it by what the way is *made of*: ice (friction 0.02 —
a marble slides, never rolls, and keeps all the speed it gets) and sand
(a gripping surface under a layer that drags, `SAND_DRAG` per second on
velocity). The same ramp is a different race in each, and that difference
is the whole world.

Every piece of terrain is laid by `_layer`: the solid surface
(`rig.surface`, drawn in the surface's colour) and, on top of it, a strip
the depth of a marble (`rig.zone`) that carries the texture — the ice
sheen, the sand grain — and, for sand, the drag. A friction change nobody
can see reads as a glitch; a marble visibly wading through a sand layer
does not.

Geometry comes from the build's `rng`, so a round that re-runs another's
layout (`round_params: [.., {layout: 0}]`) gets the same track; what a
mechanism decides at random (which ice melts, how much weight thin ice
takes) comes from `rig.rng`, per docs/10.

Sections here register into `stagekit.SECTIONS` when this module is
imported, which `physics/registry.py` does before it composes the World 5
stages.
"""

from __future__ import annotations

import math

from ... import stagekit
from ...mechanics import rig_of

# Drag (1/s on velocity) inside each terrain's layer. Sand is the kit's 1.4
# at full depth in a pit, and lighter where it is a coat on a ramp: a marble
# in the layer reaches (2/3) g sin(slope) / drag and stays there, and at the
# kit's 1.4 on a 0.4 ramp that is a crawl a viewer reads as a stall.
SAND_DRAG = 0.75
SLUSH_DRAG = 0.4
LAYER_DRAG = {"ice": 0.0, "sand": SAND_DRAG, "slush": SLUSH_DRAG}
TRAIL = {"sand": 2.0}
# Slush grips: every marble rolls in it, whatever its own friction (a zone's
# `friction`), so what melting takes away is the slide, the same for all.
SLUSH_GRIP = 0.6
# How deep the textured layer over a surface is, as a fraction of the width:
# a marble's diameter and a little, so a rolling marble's centre is inside it
# and a marble in the air above it is not.
LAYER = 0.075
# Floor slopes. Ice is shallow — nothing slows a marble on it, so a steep ice
# floor is over before anyone sees it — and sand is steep, because on sand
# the drag, not the slope, sets the pace.
ICE_SLOPE = 0.38
SAND_SLOPE = 0.50
STRIPE_SLOPE = 0.34
STRIPE_TRAIL = 3.0  # fresh sand on the stripes is heavier: 1.5 lead changes at 2.0, 2.1 at 3.0 (96 seeds)
DUNE_SLOPE = 0.50
# How far a V's throat sits off centre, as a share of the width, drawn per
# row, so the two ways down the split under it differ in length; how far that
# split's point sits from under the throat (a hair, so which way a marble goes
# is how it came out, and the field divides); and, after a pit or the bowl —
# a straight drop — clear of it, because a marble dropped dead onto the point
# sat balanced there (sand grips). Measured over 96 seeds: with the point a
# marble's half-width off every throat the stripes stage split nobody and the
# lead changed 1.4 times a race; under the throat, 1.7.
OFFSET = 0.07
APEX_SHIFT = (0.0, 0.01)
DROP_SHIFT = (0.035, 0.06)


def _lerp(a, b, u):
    return (a[0] + (b[0] - a[0]) * u, a[1] + (b[1] - a[1]) * u)


def _layer(rig, space, w, style, a, b, kind, *, drag=None, friction=None, show=True, trail=None):
    """One strip of terrain: the surface, and the layer over it that shows
    what it is and (sand, slush) drags whoever is in it."""
    rig.surface(space, a, b, kind, thickness=style.thickness / 2, friction=friction)
    d = w * LAYER
    poly = [a, b, (b[0], b[1] + d), (a[0], a[1] + d)]
    rig.zone(poly=poly, kind=kind, damping=LAYER_DRAG.get(kind, 0.0) if drag is None else drag, show=show,
             friction=SLUSH_GRIP if kind == "slush" else None)
    trail = TRAIL.get(kind) if trail is None else trail
    if trail:
        # Fresh sand: the first marble through a patch breaks the trail and
        # wades through TRAIL more; everyone after it runs in its track. The
        # patch reacts to arrival order, never to who (docs/08 rule 2.4).
        rig.zone(poly=poly, kind=kind, damping=trail, first_only=True, show=False)


def _chutes(space, w, top, bottom, rng, style, lay, slope=0.42):
    """The `chutes` section's split-and-rejoin rows, clearance for clearance,
    each ramp laid as terrain by `lay(row, side, high, low)` (side 0 left, 1
    right). A V gathers the field to a centre throat; a peak splits it to the
    two walls. What a marble meets on the way down is decided at the peak by
    a bounce, and the two sides need not be the same ground: that is where a
    terrain race changes order. (Full-width floors were tried first: on one
    long ramp of ice everybody slides at the same speed, single file, and
    the lead changed 0.4-0.8 times a race.)

    `slope` is what a V's ramps aim for, and it sets how many rows the band
    holds: shallow ice gets more, shorter rows (a marble on steep ice is
    through a band before anyone sees it), steep sand fewer (on sand the
    drag, not the slope, sets the pace, and a shallow sand ramp is a stall).
    The drop from one row's throat to the next row's top is a marble's room
    at least, as the chutes section learned.

    A band starts with a split when the section above let the field go
    through a throat or a gap (`rig.w5_exit`), with the point under it: a V
    under a throat is a hole under a hole, and the first sand-pit stage had
    a marble fall straight through three of them and finish in 4.4 s. A band
    that ends on a V says where its throat is, for the section below."""
    rig = rig_of(style)
    height = top - bottom
    room = stagekit.marble_room(w)
    gap = max(w * rng.uniform(0.16, 0.20), room)
    entry = getattr(rig, "w5_exit", None)
    start_peak = entry in ("centre", "drop")
    want = (w / 2 - gap / 2 - 14.0) * slope
    rows = max(1, round(height / (want + room * 1.2)))
    step = height / rows
    drop = max(min(want, step - room), step * 0.3)
    if rows == 1:
        # One row has no row under it inside the band: the next section is two
        # margins away, past any marble. A squeezed band otherwise laid its sand
        # at 0.14 and the terrain stage parked 64 marbles in 123 on it.
        drop = min(want, height)
    cx = getattr(rig, "w5_exit_x", None) or w / 2
    for i in range(rows):
        y = top - i * step
        if (i % 2 == 0) != start_peak:
            cx = w / 2 + w * rng.uniform(-OFFSET, OFFSET)
            sides = [((14.0, y), (cx - gap / 2, y - drop)), ((w - 14.0, y), (cx + gap / 2, y - drop))]
        else:
            # A point, not the chutes' tilted cap: a tilted cap sends the
            # whole field the same way (seen: all four right at every split),
            # and so does a point well off to one side of the throat above.
            shift = DROP_SHIFT if i == 0 and entry == "drop" else APEX_SHIFT
            apex = (cx + w * rng.choice([-1, 1]) * rng.uniform(*shift), y)
            sides = [(apex, (gap + 14.0, y - drop)), (apex, (w - gap - 14.0, y - drop))]
        for side, (a, b) in enumerate(sides):
            lay(i, side, a, b)
    last_is_v = ((rows - 1) % 2 == 0) != start_peak
    rig.w5_exit, rig.w5_exit_x = ("centre", cx) if last_is_v else ("walls", None)
    return []


def _patches(rig, space, w, style, a, b, patches, trail=None):
    for u0, u1, kind, *rest in patches:
        _layer(rig, space, w, style, _lerp(a, b, u0), _lerp(a, b, u1), kind, friction=rest[0] if rest else None,
               trail=trail if kind == "sand" else None)


# --- ice, sand, and the two together -----------------------------------------------------

# Ice that melts (L45): `mechanics.melt` 0..1, one value a round. Each ramp is
# three patches; each patch is slush with probability `melt` (rig.rng: which
# patches go is the mechanism's roll, not the layout's), and the ice that is
# left grips more as it goes soft.
ICE_FRICTION = 0.02
WET_ICE_FRICTION = 0.12


def ice_ramps(space, w, top, bottom, rng, style):
    """Split-and-rejoin ramps of ice: nothing grips, everything slides and
    keeps its speed. With `mechanics.melt` some of it has gone to slush."""
    rig = rig_of(style)
    melt = float(rig.knob("melt", 0.0) or 0.0)

    def lay(row, side, a, b):
        out = []
        for k in range(3):
            if melt and rig.rng.random() < melt:
                out.append((k / 3, (k + 1) / 3, "slush"))
            else:
                out.append((k / 3, (k + 1) / 3, "ice", ICE_FRICTION + (WET_ICE_FRICTION - ICE_FRICTION) * melt))
        _patches(rig, space, w, style, a, b, out)

    return _chutes(space, w, top, bottom, rng, style, lay, ICE_SLOPE)


def sand_ramps(space, w, top, bottom, rng, style):
    """Split-and-rejoin ramps under a coat of sand: the marbles roll, and wade."""
    rig = rig_of(style)
    return _chutes(space, w, top, bottom, rng, style,
                   lambda row, side, a, b: _layer(rig, space, w, style, a, b, "sand"), SAND_SLOPE)


def striped_ramps(space, w, top, bottom, rng, style):
    """Split-and-rejoin ramps striped ice, sand, ice...: speed built on one
    stripe is spent on the next, and the two sides of a split are striped
    out of step, so the marble on the ice is beside the one in the sand."""
    rig = rig_of(style)

    def lay(row, side, a, b):
        n = rng.choice([2, 3])
        cuts = [0.0] + sorted(rng.uniform(k / n - 0.06, k / n + 0.06) for k in range(1, n)) + [1.0]
        _patches(rig, space, w, style, a, b,
                 [(cuts[k], cuts[k + 1], "ice" if (k + row + side) % 2 == 0 else "sand") for k in range(n)], STRIPE_TRAIL)

    return _chutes(space, w, top, bottom, rng, style, lay, STRIPE_SLOPE)


# --- the soft sand pit (L44) ---------------------------------------------------------------

# The pit is a funnel of sand, all of it the drag layer. Whoever gets there
# first sinks deepest: the first marble into the pit (arrival order — a
# mechanism, never an identity) wades through PIT_DRAG + PIT_FIRST, everyone
# after it through PIT_DRAG alone, because the first one packed it down.
PIT_DRAG = 0.55
PIT_FIRST = 1.1


def sand_pit(space, w, top, bottom, rng, style):
    """A funnel whose basin is soft sand; the first marble in sinks deepest."""
    rig = rig_of(style)
    cx = w * rng.uniform(0.40, 0.60)
    gap = w * rng.uniform(0.21, 0.24)
    run = max(cx - gap / 2 - 14.0, w - 14.0 - (cx + gap / 2))
    drop = min(top - bottom, max(run * 0.50, (top - bottom) * 0.7))
    throat = top - drop
    left, right = ((14.0, top), (cx - gap / 2, throat)), ((w - 14.0, top), (cx + gap / 2, throat))
    for a, b in (left, right):
        rig.surface(space, a, b, "sand", thickness=style.thickness / 2)
    basin = [(14.0, top), (cx - gap / 2, throat), (cx + gap / 2, throat), (w - 14.0, top)]
    rig.zone(poly=basin, kind="sand", damping=PIT_DRAG)
    rig.zone(poly=basin, kind="sand", damping=PIT_FIRST, first_only=True, event="sank", show=False)
    # A cap over the throat, so nothing drops through the pit without going
    # into the sand: a marble's room above the throat, and a marble's room
    # plus from either arm.
    room = stagekit.marble_room(w)
    cap_y = throat + room * 1.15
    half = gap * 0.45
    peak = (cx, cap_y + half * 0.9)
    rig.surface(space, (cx - half, cap_y), peak, "sand", thickness=style.thickness / 2)
    rig.surface(space, peak, (cx + half, cap_y), "sand", thickness=style.thickness / 2)
    rig.w5_pit ={"left": left, "right": right, "throat": throat, "top": top}
    rig.w5_exit, rig.w5_exit_x = "drop", cx
    return []


# --- the ski jump (L43) -----------------------------------------------------------------

# The kicker's lip, as a slope. A lip that turned up (0.45) made the kicker a
# hollow, and on ice a marble that reached it slowly sat in it: 2 of the 18
# parked marbles in the first 48 seeds. A table tipped just down still throws
# the field clear across the landing at the in-run's speed.
KICK = -0.06
LANDING_DRAG = 0.5
LANDING_TRAIL = 1.0


def ice_launch(space, w, top, bottom, rng, style):
    """An ice in-run into a kicker, and a sand slope to land on.

    A collector sends every marble to the in-run, whichever lane it started
    in. The in-run is ice, so a marble reaches the lip with every bit
    of speed the drop gave it and flies; the landing is a sand slope that runs
    back *toward* the lip, so the farther a marble flies the more sand it has
    to wade back through. A long jump is not a lead.
    """
    rig = rig_of(style)
    flip = rng.random() < 0.5
    X = (lambda x: w - x) if flip else (lambda x: x)  # noqa: E731

    def P(x, y):
        return (X(x), y)

    c_lo = 0.42 * w
    c_drop = 0.35 * (w - 14.0 - c_lo)
    xk = 0.50 * w
    in_slope = rng.uniform(0.52, 0.60)
    y_in = top - c_drop + 20.0
    y_k = y_in - in_slope * (xk - 14.0)
    lip = (xk + 0.06 * w, y_k + 0.06 * w * KICK)
    land_slope = 0.40
    y_hi = y_k - 12.0
    land_lo_x = 0.20 * w
    y_lo = y_hi - land_slope * (w - 14.0 - land_lo_x)  # the band is sized for it (registry: skijump)
    _layer(rig, space, w, style, P(w - 14.0, top), P(c_lo, top - c_drop), "ice")
    _layer(rig, space, w, style, P(14.0, y_in), P(xk, y_k), "ice")
    _layer(rig, space, w, style, P(xk, y_k), P(*lip), "ice")
    _layer(rig, space, w, style, P(w - 14.0, y_hi), P(land_lo_x, y_lo), "sand", drag=LANDING_DRAG,
           trail=LANDING_TRAIL)

    lip_x, lip_y = X(lip[0]), lip[1]
    sign = -1.0 if flip else 1.0
    seen: set[int] = set()
    last: dict[int, float] = {}

    def launched(frame):
        # A marble crossing the lip's line outward, level with the lip: it
        # has left the kicker. Once a marble.
        for i, (x, y) in enumerate(frame.positions):
            before = last.get(i)
            last[i] = x
            if i in seen or before is None or not frame.alive[i]:
                continue
            if sign * (before - lip_x) < 0 <= sign * (x - lip_x) and lip_y - 10 <= y <= lip_y + 70:
                seen.add(i)
                frame.rig.emit("launched", i)

    rig.on_frame(launched)
    rig.w5_exit, rig.w5_exit_x = "walls", None
    return []


# --- thin ice (L46) ----------------------------------------------------------------------

# How much weight a thin-ice panel takes before it goes, in the rig's units
# (contact-seconds x mass / 1.6): drawn per panel from `rig.rng`, so where
# the ice gives is the seed's, never anyone's to choose.
THIN_HOLD = (0.15, 0.7)
THIN_AT = (0.12, 0.22)   # where on its ramp a panel starts, from the high end
THIN_LENGTH = 0.42       # of the ramp: wider than a marble's room, so a marble falls through
THIN_SLOPE = 0.30


def thin_ice(space, w, top, bottom, rng, style):
    """Split-and-rejoin ramps of ice where, in every row, one side has a
    panel of thin ice over cold water. A panel takes a seeded amount of
    weight and goes; whoever is on it then drops into the water and is out.
    Which side of a split has the panel is plain to see; when it goes is
    not."""
    rig = rig_of(style)
    lip = 2.0 + style.thickness / 2
    thin = {}

    def lay(row, side, a, b):
        if row not in thin:
            thin[row] = rng.randrange(2)
        if side != thin[row]:
            _layer(rig, space, w, style, a, b, "ice")
            return
        u0 = rng.uniform(*THIN_AT)
        u1 = u0 + THIN_LENGTH
        pa, pb = _lerp(a, b, u0), _lerp(a, b, u1)
        _layer(rig, space, w, style, a, pa, "ice")
        _layer(rig, space, w, style, pb, b, "ice")
        rig.breakable(space, pa, pb, kind="thin_ice", hold=THIN_HOLD, thickness=style.thickness / 2)
        # The water: right under the panel, so only a marble that has gone
        # through the ice is ever in it — and on the upper half of a ramp,
        # where the row below is a full marble's room and more further down.
        rig.out_zone(poly=[(pa[0], pa[1] - lip), (pb[0], pb[1] - lip),
                           (pb[0], pb[1] - lip - 46.0), (pa[0], pa[1] - lip - 46.0)],
                     event="fell_through", label="thin ice")

    return _chutes(space, w, top, bottom, rng, style, lay, THIN_SLOPE)


# --- dunes (L47) -------------------------------------------------------------------------

# A dune's back, as a share of the slope a straight ramp would have (before
# the profile is scaled to the ramp's drop), and the drag in its sand.
DUNE_BACK = (0.22, 0.34)
DUNE_DRAG = 0.6


def dunes(space, w, top, bottom, rng, style):
    """Split-and-rejoin ramps made of sand dunes: a gentle back and a steep
    slip face, twice or three times a ramp, and never the same on both
    sides of a split — which side is quicker is not something you can see.
    Always downhill (there is no hollow for a marble to settle in), but a
    face flings a fast marble off its crest and a back slows whoever lands
    on it."""
    rig = rig_of(style)

    def lay(row, side, a, b):
        ridges = rng.choice([2, 3])
        backs = [rng.uniform(*DUNE_BACK) for _ in range(ridges)]
        faces = [rng.uniform(0.75, 1.05) for _ in range(ridges)]
        cuts = [rng.uniform(0.55, 0.72) for _ in range(ridges)]
        run = (b[0] - a[0]) / ridges
        raw = sum(abs(run) * (c * bk + (1 - c) * f) for bk, f, c in zip(backs, faces, cuts))
        scale = (a[1] - b[1]) / raw  # the dunes come down exactly the ramp's drop
        x, y = a
        for bk, f, c in zip(backs, faces, cuts):
            crest = (x + run * c, y - abs(run) * c * bk * scale)
            foot = (crest[0] + run * (1 - c), crest[1] - abs(run) * (1 - c) * f * scale)
            _layer(rig, space, w, style, (x, y), crest, "sand", drag=DUNE_DRAG)
            _layer(rig, space, w, style, crest, foot, "sand", drag=DUNE_DRAG)
            x, y = foot

    return _chutes(space, w, top, bottom, rng, style, lay, DUNE_SLOPE)


# --- the ice bowl and its sand chute (L48) --------------------------------------------------

# A marble drops through the bowl's floor only once it is slow enough not to
# jump the gap; the bowl bleeds speed at BOWL_DRAG (ice itself takes none).
BOWL_DRAG = 0.22
BOWL_SEGMENTS = 28


def ice_bowl(space, w, top, bottom, rng, style):
    """A half-pipe of ice the width of the frame, with a gap in its floor.

    Everything that falls in swings from side to side; a marble crossing the
    gap fast jumps it, and one that has slowed drops through into what is
    below. When a marble gets out is how much speed it has lost, and a
    collision in the bowl can give speed as easily as take it.
    """
    rig = rig_of(style)
    radius = min((w - 20.0) / 2, top - bottom)
    cx, cy = w / 2, top
    gap_half = math.asin(min(0.9, stagekit.marble_room(w) * 0.56 / radius))
    # The gap takes in the bowl's lowest point: a marble that has lost its speed
    # settles there, so it always drops out. (Off to one side, the first bowl
    # kept every slowed marble resting on the ice beside the gap.)
    centre = -math.pi / 2 + rng.uniform(-0.5, 0.5) * gap_half
    pts = []
    for k in range(BOWL_SEGMENTS + 1):
        a = math.pi + math.pi * k / BOWL_SEGMENTS
        pts.append((a, (cx + radius * math.cos(a), cy + radius * math.sin(a))))
    # Snap the gap's edges onto the arc so the floor ends exactly there.
    lo_a, hi_a = centre - gap_half, centre + gap_half
    for (a0, p0), (a1, p1) in zip(pts, pts[1:]):
        # Angles here run pi..2pi; centre is in -pi..0, so shift it.
        s0, s1 = a0 - 2 * math.pi, a1 - 2 * math.pi
        left = (s0, s1 if s1 <= lo_a else lo_a) if s0 < lo_a else None
        right = (s0 if s0 >= hi_a else hi_a, s1) if s1 > hi_a else None
        for part in (left, right):
            if part and part[1] - part[0] > 1e-6:
                a = (cx + radius * math.cos(part[0]), cy + radius * math.sin(part[0]))
                b = (cx + radius * math.cos(part[1]), cy + radius * math.sin(part[1]))
                rig.surface(space, a, b, "ice", thickness=style.thickness / 2)
    # A roof over the gap, so nothing falls straight through from the start:
    # an inverted V of ice, high enough over the floor for a marble to pass
    # under it with room.
    gx, gy = cx + radius * math.cos(centre), cy + radius * math.sin(centre)
    room = stagekit.marble_room(w)
    roof_y = gy + room + 30.0
    half = room * 0.75
    rig.surface(space, (gx - half, roof_y), (gx, roof_y + half * 0.9), "ice", thickness=style.thickness / 2)
    rig.surface(space, (gx, roof_y + half * 0.9), (gx + half, roof_y), "ice", thickness=style.thickness / 2)
    bowl = [p for _, p in pts] + [(cx + radius, cy)]
    rig.zone(poly=bowl, kind="ice", damping=BOWL_DRAG)
    rig.w5_exit, rig.w5_exit_x = "drop", gx
    return []


def sand_chute(space, w, top, bottom, rng, style):
    """The bowl's exit: a sand chute, split-and-rejoin ramps under sand."""
    return sand_ramps(space, w, top, bottom, rng, style)


# --- the watcher (L50) ---------------------------------------------------------------------

WATCHER_COLOUR = (150, 122, 224)  # the cast's #967AE0, drawn and never entered


def sideline_watcher(rig, space, style, balls, w, h):
    """A purple marble watching from the sidelines at the end: a picture, not
    an entrant. It has no body, no name, no place in the result; it appears
    once the race is most of the way down, sitting in the dead corner under
    the sand pit's longer arm where no marble can reach."""
    pit = getattr(rig, "w5_pit", None)
    if pit is None:
        raise ValueError("sideline-watcher needs a stage with a sand pit")
    (lx0, ly0), (lx1, ly1) = pit["left"]
    (rx0, ry0), (rx1, ry1) = pit["right"]
    r = w * 0.042
    # Under the longer arm, a marble's width off the wall.
    if abs(lx1 - lx0) >= abs(rx1 - rx0):
        x = lx0 + 2.2 * r
        arm_y = ly0 + (ly1 - ly0) * (x - lx0) / (lx1 - lx0)
    else:
        x = rx0 - 2.2 * r
        arm_y = ry0 + (ry1 - ry0) * (x - rx0) / (rx1 - rx0)
    y = arm_y - r - style.thickness - 10.0
    at = float(rig.knob("watch_from", 0.8))
    rig.at("watcher", progress=at, before=False, after=True)
    rig.effect("prop", clock="watcher", at=(x, y), radius=r, color=list(WATCHER_COLOUR))


# --- registration --------------------------------------------------------------------------

SECTIONS = {
    "ice_ramps": ice_ramps, "sand_ramps": sand_ramps, "striped_ramps": striped_ramps,
    "sand_pit": sand_pit, "ice_launch": ice_launch, "thin_ice": thin_ice, "dunes": dunes,
    "ice_bowl": ice_bowl, "sand_chute": sand_chute,
}
SECTION_WORDS = {
    "ice_ramps": "ramps of ice", "sand_ramps": "ramps under sand", "striped_ramps": "ramps striped ice and sand",
    "sand_pit": "a soft sand pit", "ice_launch": "an ice ramp that launches onto sand",
    "thin_ice": "ice ramps with thin panels over water", "dunes": "sand dunes",
    "ice_bowl": "an ice bowl with a gap in its floor", "sand_chute": "a sand chute",
}
stagekit.SECTIONS.update(SECTIONS)
stagekit.SECTION_WORDS.update(SECTION_WORDS)
