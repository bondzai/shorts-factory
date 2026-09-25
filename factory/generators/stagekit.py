"""Stage kit: the parts a race stage is built from, and the way to stack them.

A stage used to be one hand-written function per look. That gave eleven
good stages and no way to make a twelfth without writing a twelfth
function, re-deriving every clearance by hand, and re-learning where
marbles get stuck. This module splits a stage into **sections**: each
section fills one horizontal band of the frame with one kind of obstacle,
and `compose` stacks bands top to bottom. A new stage is a list:

    compose([(pegs, 1.0), (drums, 1.2), (funnel, 1.0)])

What makes that safe is the one rule every section keeps: **nothing solid
within `margin` of its band's top or bottom edge.** Two neighbouring
sections are then at least two margins apart — more than the largest
marble — so a pocket cannot form between the parts of two different
sections. Every clearance inside a section is sized from the marble too
(`marble_room`), which is the lesson all eleven hand-written stages taught
the hard way: sieve tips, drum rows, rocker tips, gauntlet pockets.

Whether a stack of sections actually races — finishes in the window, no
marble parked, a runner-up that arrives — is not decided here. It is
measured by `factory.stage_qa`, and a stage that fails stays in trial.

Coordinates are pymunk's: y grows upward, the finish line is near the
bottom of the frame. Every section appends what it built to `style`, so
both renderers draw it without knowing which section made it.
"""

from __future__ import annotations

import math
from typing import Callable

import pymunk

# --- primitives (moved here unchanged from physics.py) ---------------------------------


def _wall(space: pymunk.Space, a, b, thickness=6.0, friction=0.30) -> None:
    seg = pymunk.Segment(space.static_body, a, b, thickness)
    seg.elasticity = 0.46
    seg.friction = friction
    space.add(seg)


def _peg(space: pymunk.Space, x: float, y: float, r: float, elasticity: float = 0.62) -> None:
    shape = pymunk.Circle(space.static_body, r, offset=(x, y))
    shape.elasticity = elasticity
    shape.friction = 0.12
    space.add(shape)


def _spinner(space: pymunk.Space, x: float, y: float, half: float, omega: float, phase: float, thickness: float,
             elasticity: float = 0.72) -> None:
    body = pymunk.Body(body_type=pymunk.Body.KINEMATIC)
    body.position = (x, y)
    body.angle = phase
    body.angular_velocity = omega
    shape = pymunk.Segment(body, (-half, 0), (half, 0), thickness)
    shape.elasticity = elasticity
    shape.friction = 0.10
    space.add(body, shape)


# Spinning bars in a composed stage are deader and slower than the hand-built
# stages' (0.72, 1.4-2.4 rad/s). Those run at gravity -95; composed stages run
# near -30, where a bar hitting a marble upward at 150 px/s sends it 375 px
# back up the frame (stage QA: marbles at y 830-876 with nowhere to go).
BAR_BOUNCE = 0.35


def _rocker(space, x, y, half, omega, phase, thickness):
    body = pymunk.Body(body_type=pymunk.Body.KINEMATIC)
    body.position = (x, y)
    shape = pymunk.Segment(body, (-half, 0), (half, 0), thickness)
    shape.elasticity = 0.40
    shape.friction = 0.30
    space.add(body, shape)
    return body


def _drum(space, x, y, r, omega) -> None:
    body = pymunk.Body(body_type=pymunk.Body.KINEMATIC)
    body.position = (x, y)
    body.angular_velocity = omega
    shape = pymunk.Circle(body, r)
    shape.elasticity = 0.25
    shape.friction = 0.9
    space.add(body, shape)


def _magnet(space, x: float, y: float, core: float) -> None:
    """A magnet's solid core: a peg, so the field has something to sit in.

    The core is what keeps the force honest as well as visible. A marble's
    centre can never come closer than `core + marble radius`, so the part of
    the falloff curve nearest the singularity is unreachable by construction —
    the softening below is the second line of defence, not the only one."""
    _peg(space, x, y, core, elasticity=0.50)


# --- the magnet's force law -----------------------------------------------------------
#
# Every other obstacle in this kit is a shape: it changes a marble's path by
# being in the way. A magnet is the first that reaches out, so a path stops
# being a function of geometry alone.
#
#   a(r) = peak * ( soft^2/(soft^2 + r^2) - soft^2/(soft^2 + reach^2) )
#
# A plain inverse square was the obvious first try and is wrong here twice
# over. It goes to infinity at r = 0, and pymunk steps in finite slices (four
# a frame): one step taken a few px from the centre is an impulse big enough
# to put a marble through a wall. And cutting a force off at `reach` leaves a
# step for the solver to ring on. So the law is softened — the soft^2 terms
# bound it near the centre — and shifted, the second term bringing it to
# exactly zero at `reach` rather than to a cliff.
#
# `soft` is the closest a marble's centre can come to the core's centre, which
# is where the curve has to be well behaved, because it is the only place near
# the centre a marble can ever be.
#
# PEAK PULL = 1.0 gravity, and that is what this was measured for. It is held
# as a multiple of the stage's own gravity, so it scales with pace and with
# the retry loop's gravity lean instead of needing retuning per stage.
# Measured on a rig of one core in an empty frame at composed gravity (-30), a
# marble dropped past it at 15 offsets, every run done twice — field on and
# field off — so each number is a difference, over four placements: mid-frame,
# a legal wall gap, over the floor, and over the shallowest 0.37 ramp slope.
#
#   peak pull   marbles captured and held
#   1.0         0/15 in all four placements
#   1.5         0/15 in all four placements
#   2.0         0/15 in all four placements
#   2.5         1/15, over the ramp        <- the knee
#   3.0         3/15
#   3.5         4/15, and 2/15 over the floor
#
# 1.0 is well under half the pull at which the first marble was ever held, and
# at 1.0 the pull can by construction never exceed the weight it fights: a
# magnet cannot lift a marble or hold one against a surface. What it buys is
# 15-26 px of median sideways travel and up to 281 px at its widest, against a
# 57 px marble — a quarter of a marble to five marbles off line. Top speed
# stayed 222-263 px/s at every pull tried, against ~232 for free fall down this
# frame, and no marble left the frame in any of the 360 runs: nothing is flung.
# (Re-measured at the final core size. A wider core moved the knee out from 2.0
# to 2.5, because the marble's centre can no longer get as near the middle of
# the field — the geometry does part of the capping.)
MAGNET_PULL = 1.0
# Field radius in units of `soft`. At this distance the shifted law is already
# zero, so `reach` is a real edge rather than a fade. 2.9 rather than 3.2 so a
# pair still fits in a row two reaches apart once the core is big enough to
# show its poles: at 3.2 the pair needed 342 px of the 333 px legal span and
# fell back to a single magnet.
MAGNET_REACH = 2.9


def magnet_accel(dx, dy, soft: float, reach: float, peak: float):
    """Acceleration toward a magnet (dx, dy) away, in px/s^2. See above."""
    r2 = dx * dx + dy * dy
    if r2 >= reach * reach or r2 < 1e-12:
        return 0.0, 0.0
    s2 = soft * soft
    shape = s2 / (s2 + r2) - s2 / (s2 + reach * reach)
    if shape <= 0.0:
        return 0.0, 0.0
    a = peak * shape
    r = math.sqrt(r2)
    return a * dx / r, a * dy / r
def _trapdoor(space, x, y, length: float, thickness: float):
    """The floor of a holding pit, hinged at (x, y) and reaching `length` to
    the right. The segment starts at the body's origin so the body's angle
    *is* the door's angle about its hinge — which is what makes the pinch
    impossible: the one corner where the door meets static structure is the
    hinge itself, and a gap that opens from zero cannot close on a marble."""
    body = pymunk.Body(body_type=pymunk.Body.KINEMATIC)
    body.position = (x, y)
    shape = pymunk.Segment(body, (0, 0), (length, 0), thickness)
    # A door, not a bumper: 0.30 against the walls' 0.46. A marble dropped on
    # a level door at gravity -30 still bounced 40 px at the walls' value,
    # which is most of the way back out of the pit.
    shape.elasticity = 0.30
    shape.friction = 0.40
    space.add(body, shape)
    return body


def _belt(space, a, b, speed: float, thickness: float) -> None:
    """A conveyor: a static segment whose surface moves at `speed` px/s
    along a→b. pymunk applies it through friction, so the belt is grippy."""
    seg = pymunk.Segment(space.static_body, a, b, thickness)
    seg.elasticity = 0.20
    seg.friction = 1.0
    dx, dy = b[0] - a[0], b[1] - a[1]
    length = math.hypot(dx, dy) or 1.0
    # surface_velocity is how the surface moves relative to the body; a
    # marble on top is dragged along with it.
    seg.surface_velocity = (dx / length * speed, dy / length * speed)
    space.add(seg)


# --- sizing ------------------------------------------------------------------------------

# The biggest marble the race builder can make, as a fraction of the width:
# base radius up to 0.050 w, times the size spread's top of 1.06.
MARBLE_R = 0.053
# How far a rocking plank tips either way, in radians. Lives here because the
# rockers section and both renderers need it and neither owns the other.
ROCK_AMPLITUDE = 0.42


# --- the holding trap's clock ------------------------------------------------------------
#
# The door swings down about its hinge and comes back, on a clock that runs
# whatever the marbles do. Release is the mechanism's job, not the seed's: at
# TRAP_SWING the door has left the pit's bore all but empty (see `trap`), so
# there is nothing under a held marble to hold it. The phases are fractions of
# one period — closed, swinging open, open, swinging shut.
TRAP_SWING = 1.45  # rad; cos 1.45 = 0.12, so the door blocks an eighth of the bore when open
# The four phases, measured rather than chosen:
#
#   closed   the hold, and the shortest phase, because it is the only one a
#            marble waits through.
#   opening  quick: the door is out from under the marble in under a second.
#   open     by far the longest, and the number the whole section turns on.
#            A marble let go at the door plane is still inside the arc the
#            door sweeps — radius `bore` about the hinge — until it has
#            fallen past it, which from rest at gravity -30 takes about 2.6 s.
#            While this phase was shorter than that, *every* marble the pit
#            let go was still in the arc when the door started back, and the
#            door caught it: 5 of the 6 throws measured over 16 seeds
#            happened between -1.41 and -1.15 rad, in the first tenth of the
#            closing sweep, and carried marbles 84-150 px back up the frame.
#            A marble that has to fall into the pit twice makes no headway,
#            which is what `stage_qa.stuck` is for, and rightly.
#   closing  slow, because it is the only sweep that can bat anything: it
#            cannot pinch — the hinge sees to that — but its tip meets a
#            marble head on. At 0.22 of the period (a tip peaking at 167-190
#            px/s) 21 of 119 unfinished marbles ended up parked above the
#            pit. Opening is free to be quick: the door drops away from
#            whatever is on it.
TRAP_PHASES = (0.12, 0.13, 0.45, 0.30)  # closed, opening, open, closing
# Per trap, from the seed. Set by the open phase above: at 0.45 of the period
# the bore is clear for 2.9-3.2 s against the 2.6 s a marble needs to fall out
# of the door's arc. The hold is the closed phase plus that fall, so it stays
# a beat even though the cycle is long — and the closing tip peaks at 85-95
# px/s, under half what it was when this section parked marbles.
TRAP_PERIOD = (6.4, 7.2)


def _ease(x: float) -> float:
    """Smoothstep. A door that starts and stops dead flicks whatever is on it;
    the sweep has to begin and end at rest."""
    return x * x * (3.0 - 2.0 * x)


def trap_angle(t: float, period: float, phase: float) -> float:
    """Where a trap door is at time t: 0 level (holding), -TRAP_SWING open.

    The one function the solver and both renderers read, so the door a viewer
    sees is the door the marble sat on.
    """
    closed, opening, held, _closing = TRAP_PHASES
    u = ((t / period) + phase) % 1.0
    if u < closed:
        return 0.0
    u -= closed
    if u < opening:
        return -TRAP_SWING * _ease(u / opening)
    u -= opening
    if u < held:
        return -TRAP_SWING
    return -TRAP_SWING * (1.0 - _ease((u - held) / _closing))


def marble_room(w: float) -> float:
    """A gap a marble passes through with air: its diameter plus a quarter."""
    return w * MARBLE_R * 2 * 1.25


def margin(w: float) -> float:
    """What a section keeps clear at its band's top and bottom edges. Two
    neighbouring sections are two margins apart: 0.12 w, 65 px on a 540 px
    frame, past the biggest marble's 57 px."""
    return w * 0.06


def _centred_lanes(w: float, share: float = 0.6):
    lo = w * (1 - share) / 2
    return lambda count: [lo + (w * share) * i / max(count - 1, 1) for i in range(count)]


# --- sections: each fills the band (top, bottom) and returns drawn segments -------------
#
# Signature: section(space, w, top, bottom, rng, style) -> list[segment]
# `top` and `bottom` are already inset by the margin, so a section may put
# things right on them. Circles, spinners, drums, rockers and belts go on
# `style`; plain walls are returned so the renderer draws them.


def pegs(space, w, top, bottom, rng, style):
    """A Galton band: offset rows of small pegs. A peg is a point, never a
    ledge — but two pegs closer than a marble are a cradle, and a peg closer
    to a wall than a marble is a corner. The first pegs section had both
    (49 px between pegs against a 57 px marble; 14 px from the wall) and
    parked a marble in one of them in four races out of ten. So the pitch
    leaves a marble's room between pegs, and a peg that would leave less
    than that to a wall is left out."""
    height = top - bottom
    # Rows at least 66 px apart, one row if the band cannot hold two. Two
    # rows 40 px apart (a squeezed band on the carnival stage) made a cup of
    # three pegs — two above, the offset one below — and a marble that fell
    # into it at the top of the frame sat there all race: 36 of 64 unfinished
    # marbles, seen on the contact sheet. The old pegboard's rows are 58-82
    # px apart, which is where its own parked marbles come from.
    spacing = rng.uniform(66, 82)
    rows = max(1, int(height // spacing) + 1)
    r = rng.uniform(6.5, 9.5)
    room = marble_room(w)
    # Between pegs a marble's diameter and a tenth is enough to fall through;
    # the full marble_room made the band so sparse that marbles dropped
    # straight through it (three stages finished under the QC floor).
    through = w * MARBLE_R * 2 * 1.1
    cols = max(3, min(rng.randint(5, 7), int((w - 60.0) // (through + 2 * r))))
    pitch = (w - 60.0) / cols
    for i in range(rows):
        y = top - height * i / max(rows - 1, 1) if rows > 1 else (top + bottom) / 2
        offset = pitch / 2 if i % 2 else 0.0
        for j in range(cols + (0 if i % 2 else 1)):
            x = 30.0 + offset + j * pitch
            if _cornered(x, r, w, room):
                continue
            _peg(space, x, y, r)
            style.circles.append((x, y, r))
    return []


def _cornered(x: float, r: float, w: float, room: float) -> bool:
    """A round obstacle that leaves a gap to a wall too small to pass and
    too big to be flush: a pocket. (The walls' inner faces are at x = 7 and
    x = w - 7.)"""
    left, right = x - r - 7.0, (w - 7.0) - (x + r)
    return 0.0 < left < room or 0.0 < right < room


def bumpers(space, w, top, bottom, rng, style):
    """Big elastic bumpers in a staggered lattice: the busiest band."""
    height = top - bottom
    rows = max(2, int(height // 78) + 1)
    cols = 4
    pitch = (w - 40.0) / cols
    for i in range(rows):
        y = top - height * i / max(rows - 1, 1)
        offset = pitch / 2 if i % 2 else 0.0
        for j in range(cols + (0 if i % 2 else 1)):
            x = 20.0 + offset + j * pitch + rng.uniform(-8, 8)
            r = rng.uniform(13.0, 19.0)
            yy = y + rng.uniform(-6, 6)
            if not _cornered(x, r, w, marble_room(w)):
                # 0.75, not the hand-built stage's 0.9: at the low gravity a
                # composed stage runs at, 0.9 juggled a marble in place on a
                # bumper for seconds — moving, going nowhere.
                _peg(space, x, yy, r, elasticity=0.75)
                style.circles.append((x, yy, r))
    return []


def funnel(space, w, top, bottom, rng, style):
    """Two ramps from the walls to one throat, sized in radii of the biggest
    marble (below three an arch of marbles stalls it), the slope held at
    0.45 or steeper whatever the band's height."""
    cx = w * rng.uniform(0.40, 0.60)
    # 4.2-4.8 radii: at 3.5-4 two marbles arched across the throat (seen once
    # in sixteen races on the seesaw stage).
    gap = w * rng.uniform(0.20, 0.23)
    run = max(cx - gap / 2 - 14.0, w - 14.0 - (cx + gap / 2))
    drop = min(top - bottom, max(run * 0.48, (top - bottom) * 0.7))
    throat = top - drop
    segments = [((14.0, top), (cx - gap / 2, throat)), ((w - 14.0, top), (cx + gap / 2, throat))]
    for a, b in segments:
        _wall(space, a, b, thickness=style.thickness / 2)
    return segments


def ramps(space, w, top, bottom, rng, style):
    """Zigzag ramps, slope 0.37-0.44: steep enough that nothing comes to rest
    (at 0.15 marbles stop dead). Count follows the band; span follows slope."""
    height = top - bottom
    count = max(2, int(height // rng.uniform(95, 130)))
    slope = rng.uniform(0.37, 0.44)
    step = height / count
    span = min(step / slope, w - 90.0)
    mirrored = rng.random() < 0.5
    segments = []
    for i in range(count):
        y = top - i * step
        starts_left = (i % 2 == 0) != mirrored
        a, b = ((26.0, y), (26.0 + span, y - step)) if starts_left else ((w - 26.0, y), (w - 26.0 - span, y - step))
        _wall(space, a, b, thickness=style.thickness / 2)
        segments.append((a, b))
    return segments


def sieve(space, w, top, bottom, rng, style):
    """Rows of short tilted bars with gaps. The gap between tips, and between
    a tip and a wall, is what is sized (TIP_GAP): the first sieve's tips were
    67px apart against a 60px marble. Rows at least 134px apart."""
    tip_gap = max(0.15 * w, marble_room(w))
    per_row = rng.choice([3, 4])
    pitch = w / per_row
    # Rows sit inset by the most a tilted bar can reach above or below its
    # row, so no bar is ever cut to fit. (Clamping the tilt instead flattened
    # the edge rows to 4 px over 84 — a ledge; eight of fifteen parked
    # marbles on the labyrinth sat on one.)
    reach = 0.55 * (pitch - tip_gap) / 2 + 2
    top, bottom = top - reach, bottom + reach
    height = max(top - bottom, 0.0)
    rows = max(1, min(4, int(height // 140) + 1))
    segments = []
    for i in range(rows):
        y = top - height * i / max(rows - 1, 1) if rows > 1 else (top + bottom) / 2
        offset = pitch / 2 if i % 2 else 0.0
        direction = 1 if i % 2 else -1
        for j in range(per_row + 1):
            cx = offset + j * pitch
            span = pitch - max(pitch * rng.uniform(0.50, 0.62), tip_gap)
            a_x, b_x = cx - span / 2, cx + span / 2
            if b_x < 6 or a_x > w - 6:
                continue
            if 6 <= a_x < tip_gap:
                a_x = tip_gap
            if w - tip_gap < b_x <= w - 6:
                b_x = w - tip_gap
            if b_x - a_x < 24:
                continue
            span = b_x - a_x
            here = 1 if a_x < 6 else (-1 if b_x > w - 6 else direction)
            tilt = here * rng.uniform(0.42, 0.55) * span
            a, b = (a_x, y + tilt / 2), (b_x, y - tilt / 2)
            _wall(space, a, b, thickness=style.thickness / 2, friction=0.12)
            segments.append((a, b))
    return segments


def drums(space, w, top, bottom, rng, style):
    """Rows of big spinning drums; every drum is sized from the gaps around
    it — neighbours, walls, band edges — each clearing a marble with air.
    Every drum in a row turns the same way (opposed drums made a pinch)."""
    height = top - bottom
    rows = max(1, int(height // 200))
    row_gap = height / rows
    for i in range(rows):
        y = top - row_gap * (i + 0.5)
        count = 2 if i % 2 == 0 else 3
        r = min(w * rng.uniform(0.06, 0.11), (w / (count + 1) - w * 0.13) / 2, (row_gap - w * 0.14) / 2)
        if r < w * 0.035:
            continue
        direction = rng.choice([-1, 1])
        for j in range(count):
            x = w * (j + 1) / (count + 1)
            omega = direction * rng.uniform(1.6, 2.6)
            _drum(space, x, y, r, omega)
            style.drums.append((x, y, r, omega))
    return []


def rockers(space, w, top, bottom, rng, style):
    """Rows of planks rocking on a pivot. Tips keep a marble from the walls,
    the hub is a real peg, and deflectors under each row send what a plank
    throws at a wall back to the middle (all three measured in the rockers
    stage, where marbles sat jittering against a wall at x = 0.06 w)."""
    height = top - bottom
    rows = max(1, int(height // 150))
    row_gap = height / rows
    # A tip keeps a marble's room and air from the wall. At 0.12 w the gap
    # was 61 px against a 57 px marble, and the agent's QA found one wedged
    # there for half a race while the plank jiggled it — moving, so the
    # "still" test missed it.
    clear = marble_room(w) + w * 0.02
    segments = []
    for i in range(rows):
        y = top - row_gap * (i + 0.5)
        count = 2 if i % 2 == 0 else 3
        for j in range(count):
            x = w * (j + 0.5) / count + (w * 0.08 if i % 2 else 0) * rng.choice([-1, 1]) * 0.3
            # Rocking about a tilt, not about level: about level a marble on
            # the pivot is rolled one way then back and stays (seen on the
            # seesaw stage). Outer planks tilt with the outer tip high, so
            # they drain toward the middle and never toward a wall; a middle
            # plank tilts either way. (Positive angle lifts the right tip.)
            sign = -1 if j == 0 else 1 if j == count - 1 else rng.choice([-1, 1])
            # 0.24-0.32: at 0.12-0.20 a plank at gravity -30 tossed a marble
            # back and forth faster than the average tilt could drain it.
            bias = sign * rng.uniform(0.24, 0.32)
            half = min(w * rng.uniform(0.11, 0.15), x - clear, w - clear - x)
            # A rocking tip rises sin(amplitude + bias) * half: keep that inside the row.
            half = min(half, (row_gap / 2 - 6) / math.sin(ROCK_AMPLITUDE + abs(bias)))
            omega = rng.uniform(1.0, 1.8)
            phase = rng.uniform(0, 6.283)
            body = _rocker(space, x, y, half, omega, phase, style.thickness / 2)
            style.rockers.append((x, y, half, omega, phase, bias))
            style.kinematics.append(("rocker", body, (omega, phase, bias)))
            _peg(space, x, y, style.thickness * 0.9, elasticity=0.5)
        # No wall deflectors under the row. The hand-built rockers stage
        # needed them because its tips reached the walls; here the tips keep
        # a marble's room and the outer planks drain inward, and a deflector
        # only made a pocket under the plank tip (11 of pinball's 18 stuck
        # marbles sat on one).
    return segments


def spinners(space, w, top, bottom, rng, style):
    """Pairs of spinning bars, one each side, turning opposite ways. The gap
    between the two sweeps and between a sweep and a wall both clear a
    marble, and rows are far enough apart that no two sweeps come within a
    marble of each other — two kinematic bars meeting is a pinch, not a hit."""
    height = top - bottom
    half = w * rng.uniform(0.10, 0.125)
    rows = max(1, int(height // (2 * half + marble_room(w) + 20)))
    row_gap = height / rows
    # The sweep stays inside its row: in a squeezed band it reached 33 px
    # past the band's edge, 31 px from the next section — less than a marble.
    half = min(half, row_gap / 2)
    for i in range(rows):
        y = top - row_gap * (i + 0.5)
        direction = rng.choice([-1, 1])
        for k, x_frac in enumerate((0.30, 0.70)):
            x = w * x_frac + rng.uniform(-w * 0.02, w * 0.02)
            omega = direction * (1 if k == 0 else -1) * rng.uniform(0.9, 1.4)
            phase = rng.uniform(0, 3.14)
            _spinner(space, x, y, half, omega, phase, style.thickness / 2, elasticity=BAR_BOUNCE)
            style.spinners.append((x, y, half, omega, phase))
    return []


def wheel(space, w, top, bottom, rng, style):
    """One four-armed wheel in the middle of the band."""
    height = top - bottom
    half = min(w * rng.uniform(0.24, 0.30), height / 2)
    cx, cy = w / 2 + rng.uniform(-w * 0.04, w * 0.04), (top + bottom) / 2
    omega = rng.choice([-1, 1]) * rng.uniform(0.9, 1.4)
    phase = rng.uniform(0, 3.14)
    for extra in (0.0, math.pi / 2):
        _spinner(space, cx, cy, half, omega, phase + extra, style.thickness / 2, elasticity=BAR_BOUNCE)
        style.spinners.append((cx, cy, half, omega, phase + extra))
    return []


def chutes(space, w, top, bottom, rng, style):
    """Split-and-rejoin chutes: a V (one gap, centre), then a peak (a gap at
    each wall, a tilted cap so nothing balances). Gaps are a marble's room at
    least — the first cascade wedged 13 seeds in 24 — and so is the drop from
    one row's throat to the next row's top: at 45 px, less than a marble,
    marbles wedged between a V's tips and the cap under it (the old cascade
    parks one marble in five there, measured)."""
    height = top - bottom
    room = marble_room(w)
    rows = max(1, int(height // 150))
    step = height / rows
    drop = max(min(step * 0.6, step - room), step * 0.3)
    gap = max(w * rng.uniform(0.16, 0.20), room)
    segments = []
    for i in range(rows):
        y = top - i * step
        if i % 2 == 0:
            pairs = [((14.0, y), (w / 2 - gap / 2, y - drop)), ((w - 14.0, y), (w / 2 + gap / 2, y - drop))]
        else:
            cap = w * 0.06
            tilt = 1 if rng.random() < 0.5 else -1
            cap_a, cap_b = (w / 2 - cap, y + tilt * cap * 0.4), (w / 2 + cap, y - tilt * cap * 0.4)
            pairs = [(cap_a, (gap + 14.0, y - drop)), (cap_b, (w - gap - 14.0, y - drop)), (cap_a, cap_b)]
        for a, b in pairs:
            _wall(space, a, b, thickness=style.thickness / 2)
            segments.append((a, b))
    return segments


def belts(space, w, top, bottom, rng, style):
    """Conveyor belts: near-flat shelves from alternate walls whose surface
    carries a marble toward the open end. Each belt runs at its own speed,
    so the marble that lands on the fast one gains — the order changes on
    the flat, where nothing else in the kit changes it. A shallow tilt the
    same way means a belt can slow a marble but never hold it."""
    height = top - bottom
    count = max(1, int(height // 95))
    step = height / max(count, 1)
    start_left = rng.random() < 0.5
    segments = []
    for i in range(count):
        y = top - step * (i + 0.2)
        from_left = (i % 2 == 0) == start_left
        length = w * rng.uniform(0.66, 0.74)
        # A belt drags a marble through friction only, and a marble gets about
        # a third of the belt's speed that way (measured: 100 px/s belt, 33
        # px/s marble). At a tilt of 0.10 marbles crawled across the switchback
        # belt at 20 px/s for seconds — moving, so not "parked", but dead on
        # screen. The tilt does the carrying; the speed decides who gains.
        tilt = length * 0.17
        speed = rng.uniform(90.0, 170.0)
        a, b = ((10.0, y), (10.0 + length, y - tilt)) if from_left else ((w - 10.0, y), (w - 10.0 - length, y - tilt))
        _belt(space, a, b, speed, style.thickness / 2)
        style.belts.append((a, b, speed))
    return segments


def magnets(space, w, top, bottom, rng, style):
    """Magnets: a solid core with a field around it that pulls a marble off
    its line as it passes. The kit's only force — everything else here works
    by being in the way.

    Two placements are measured rather than chosen. A core keeps `marble_room`
    from both walls, because a round obstacle closer than that to a wall is
    the pocket `_cornered` names and the pegs section learned the hard way.
    And rows are put two full `reach`s apart, so no point in the band lies
    inside two fields at once: overlapping fields would sum past the one
    gravity the pull was measured safe at. (The simulation clamps the sum
    anyway — the spacing means the clamp should never have to act.)

    One magnet a row, alternating side to side, so the pull is across the
    fall rather than along it: a marble is tugged one way, then the other way
    a row later, and which side it is on when it arrives is what changed."""
    height = top - bottom
    room = marble_room(w)
    # Big enough that the two poles on the core read at full frame size; at
    # 0.026-0.034 w the split was only legible zoomed in.
    core = w * rng.uniform(0.038, 0.046)
    soft = core + w * MARBLE_R
    reach = soft * MAGNET_REACH
    # Fields that never overlap: centres two reaches apart. A band too short
    # for two still gets one.
    rows = max(1, int(height // (2 * reach)))
    row_gap = height / rows
    # The core has to clear both walls by a marble's room, which is what
    # leaves it somewhere to sit: on a 540 px frame, x in 94..446.
    lo = 7.0 + room + core
    hi = w - 7.0 - room - core
    if lo >= hi:
        return []
    for i in range(rows):
        y = top - row_gap * (i + 0.5)
        # A pair in the row when the frame is wide enough to hold two fields
        # two reaches apart (540 px leaves 351 px of legal span against the
        # 277 px two fields need), otherwise one in the middle. A pair is what
        # makes the band read: a marble down the middle is pulled equally both
        # ways and goes straight, and anything off centre picks a side.
        span = hi - lo
        if span >= 2 * reach:
            first = lo + rng.uniform(0.0, span - 2 * reach)
            xs = [first, first + 2 * reach]
            if rng.random() < 0.5:
                xs.reverse()
        else:
            xs = [(lo + hi) / 2]
        for x in xs:
            if _cornered(x, core, w, room):
                continue
            _magnet(space, x, y, core)
            style.magnets.append((x, y, core, soft, reach, MAGNET_PULL))
    return []


# Where the pit's mouth may sit, as a fraction of the width, before the
# clearance below is applied. The first trap fed the pit off a long ramp from
# one frame wall, which put it on the critical path: half the field went in,
# and with 2.1 marbles held a race the nearest non-winner had been in the pit
# on 9 of the 10 seeds that finished with no runner-up at all. The mouth is
# now the whole catch — a marble has to fall into it — and it is placed off
# to one side, so what the trap does is catch somebody rather than sort
# everybody.
TRAP_PLACE = (0.30, 0.44)


def trap(space, w, top, bottom, rng, style):
    """A holding trap: a pit with a floor that swings away on a clock.

    Every other section changes the order the marbles are in; this one stops
    a marble. A lead built in the first five seconds is what makes the second
    half of a clip worthless, and a marble that goes into the pit in front
    comes out behind — the reset that keeps a race worth watching to the end.

    The pit is three static pieces and one moving one: two walls a bore apart
    at the bottom, leaning out to a wider mouth, and a door hinged at the foot
    of the left wall. The door is kinematic and runs on `trap_angle`, so the
    release is the mechanism's, not the seed's: at -TRAP_SWING the door
    reaches only bore*cos(1.45) = an eighth of the bore across, leaving 0.88
    of it open — more than a marble — and there is nothing else under the pit.
    A pit that *usually* lets go would be the three-peg cup with extra steps.

    Three things are sized rather than chosen:

    * **The bore.** marble_room and a sixth. Below that the open door still
      blocks more than the air a marble needs; above it the pit stops catching
      anything, because a marble crosses it faster than it falls into it.
    * **The depth.** 2.1 radii of the biggest marble. Marbles drop in at
      about 80 px/s and bounce at 0.30 x 0.46; at 1.5 radii they came back
      out of the pit on the first bounce, and at 2.3 the fall clear after the
      door opens added most of a second to every hold.
    * **The lean.** Both walls meet the mouth at 67 degrees rather than
      square, for the reason the cascade's flat cap was cut: a wall that ends
      square ends in a knob, and a marble that arrives slowly balances on it.
      A 67 degree face sheds one either into the pit or past it, and there is
      nothing anywhere on the pit for a marble to come to rest on.

    **What the pit is not**: a funnel. The first version fed it off a long
    ramp from one frame wall, which put it on the critical path — half the
    field went in, 2.1 marbles were held a race, and on 9 of the 10 seeds
    that finished with no runner-up at all the nearest non-winner had been in
    the pit. The ramp was also where the parked marbles were: 5 in 39, none
    of them in the pit, all of them on or beside the ramp. There is no ramp
    now. The mouth is bore + two leans wide, a quarter of the frame, and it
    is placed off centre (TRAP_PLACE), so a marble has to fall into it: the
    trap catches somebody rather than sorting everybody, and both sides of it
    are open bypass far wider than a marble.

    The rest of the band is pegs, at the `pegs` section's own clearances and
    kept a marble's room clear of the pit and of everything the door sweeps.
    They are not decoration. A band that is a pit and otherwise empty air is
    a band marbles fall straight through: the stage then finished in 7.0-10.6
    s on 9 of 16 seeds, under the 10.6 s QC floor, and burned a retry on each
    one. With the pegs in, the same seeds run 12-13 s and the field arrives
    at the pit spread out rather than in a bunch.
    """
    room = marble_room(w)
    big = w * MARBLE_R
    bore = room * 1.18
    depth = big * 2.1
    lean = depth * 0.42  # 67 degrees: past the 0.46 slope anything rests on
    # The door hangs bore*sin(TRAP_SWING) below its hinge when open, and
    # nothing solid may leave the band: that is what fixes the pit's height.
    fy = bottom + bore * math.sin(TRAP_SWING) + 4.0
    mouth = fy + depth
    # A pit with no air above its mouth is a pit nothing can fall into. Rather
    # than shrink it past what a marble needs, build nothing: compose() is
    # free to give this section a small share, and a squeezed trap is the
    # squeezed sieve all over again.
    if mouth > top - room * 0.5:
        return []
    # A mouth lip closer to a frame wall than a marble is the pocket
    # `_cornered` names, and it is not a near miss: at 0.20 w the left lip
    # stood 40 px off the wall against a 52 px marble and one sat in the gap
    # for the last eight seconds of a clip, dead still.
    edge = 13.0 + room + bore / 2 + lean
    cx = min(max(w * rng.uniform(*TRAP_PLACE), edge), w - edge)
    if rng.random() < 0.5:
        cx = w - cx  # either side of the frame, so the stage is not one-handed
    hinge = cx - bore / 2
    # The near wall stops at the hinge — anything below it is inside the
    # door's own sweep — while the far wall carries on a little past the
    # door's tip, so a marble coming down its outside face falls clear
    # instead of landing on the tip.
    segments = [((hinge - lean, mouth), (hinge, fy)),
                ((hinge + bore, fy - big * 0.4), (hinge + bore + lean, mouth))]
    for a, b in segments:
        _wall(space, a, b, thickness=style.thickness / 2)
    period = rng.uniform(*TRAP_PERIOD)
    phase = rng.random()
    body = _trapdoor(space, hinge, fy, bore, style.thickness / 2)
    body.angle = trap_angle(0.0, period, phase)
    style.traps.append((hinge, fy, bore, depth, period, phase))
    style.kinematics.append(("trapdoor", body, (period, phase)))
    _pegs_around(space, w, top, bottom, rng, style, hinge, fy, bore, depth, lean)
    return segments


def _pegs_around(space, w, top, bottom, rng, style, hinge, fy, bore, depth, lean) -> None:
    """Fill the band around a pit with pegs, keeping a marble's room from it.

    The clearances are the pegs section's, for the same reasons: rows 66 px
    apart or more (the three-peg cup), a marble's diameter and a tenth
    between pegs in a row (the cradle), and nothing that leaves a wall gap
    too small to pass (the corner). The pit's keep-out is everything a marble
    could be caught against — the mouth, the walls, and the quarter circle
    the door sweeps below the hinge — grown by a marble's room.
    """
    room = marble_room(w)
    through = w * MARBLE_R * 2 * 1.1
    r = rng.uniform(6.5, 9.5)
    height = top - bottom
    # Tighter than the pegs section's 66-82 and 5-7, at the same floors. This
    # band has a pit taking a quarter of it out, and the sparser field let
    # marbles run the gap beside the pit and arrive at the throat together:
    # over five 16-seed sets the loose density parked 6 of 37 on one of them
    # against a 12% ceiling, and this one parks 0-4 of 36-40 on all five. It
    # buys nothing on pace — first try is 12, 14, 9, 9, 13 either way — that
    # is the pegs being here at all, not how many of them there are.
    rows = max(1, int(height // rng.uniform(66, 72)) + 1)
    cols = max(3, min(rng.randint(6, 7), int((w - 60.0) // (through + 2 * r))))
    pitch = (w - 60.0) / cols
    # The keep-out: the pit's own box, and the door's arc under the hinge.
    keep_x = (hinge - lean - room - r, hinge + bore + lean + room + r)
    keep_y = (fy - bore - room - r, fy + depth + room + r)
    for i in range(rows):
        y = top - height * i / max(rows - 1, 1) if rows > 1 else (top + bottom) / 2
        offset = pitch / 2 if i % 2 else 0.0
        for j in range(cols + (0 if i % 2 else 1)):
            x = 30.0 + offset + j * pitch
            if keep_x[0] <= x <= keep_x[1] and keep_y[0] <= y <= keep_y[1]:
                continue
            if _cornered(x, r, w, room):
                continue
            _peg(space, x, y, r)
            style.circles.append((x, y, r))


SECTIONS: dict[str, Callable] = {
    "pegs": pegs, "bumpers": bumpers, "funnel": funnel, "ramps": ramps, "sieve": sieve,
    "drums": drums, "rockers": rockers, "spinners": spinners, "wheel": wheel, "chutes": chutes,
    "belts": belts, "magnets": magnets, "trap": trap,
}

# How a section reads in a sentence, for the render's plain description.
SECTION_WORDS = {
    "pegs": "a band of pegs", "bumpers": "bumpers", "funnel": "a funnel", "ramps": "zigzag ramps",
    "sieve": "a sieve of tilted bars", "drums": "spinning drums", "rockers": "rocking planks",
    "spinners": "spinning bars", "wheel": "a four-armed wheel", "chutes": "split-and-rejoin chutes",
    "belts": "conveyor belts", "magnets": "magnets that pull the marbles off line",
    "trap": "a trapdoor pit that holds a marble and lets it go",
}


# --- World 6: dice track ------------------------------------------------------------------
#
# The dice sections are geometry only. What a die does to them — which path
# opens, which blocker goes, when the start gate lets go — is the level's
# mechanic (physics/worlds/dice.py), which reads what these record on
# `style.dice` and registers the doors on the round's rig. A gap a mechanic
# never closes is open, so a dice stage raced without its mechanic is still a
# stage that drains.


def dice_record(style) -> dict:
    """What the dice sections built, for the mechanic. Not a Style field, so
    never stored: the renderers draw the doors and dice the rig records."""
    rec = getattr(style, "dice", None)
    if rec is None:
        rec = {"gates": [], "runway": None, "blocks": [], "bands": []}
        style.dice = rec
    return rec


# A dice gate's lanes, from easy to hard. The die picks a lane; which lane
# holds which is the seed's, so every face of the die can be the hard one.
LANE_KINDS = ("open", "pegs", "shelves")
GATE_WAIT = 1.45  # s a gate holds the leader with no die: what a die takes to roll and land
GATE_SLOPE = 0.48  # the funnel's walls (the funnel section's floor, 0.45, plus air)


def _waited(y: float, wait: float):
    """A gate's plain clock: "idle" (shut) until the leader is below y, then
    True (shut, holding) for `wait` seconds, then False (open)."""
    state: dict = {"at": None}

    def fn(f):
        if state["at"] is None:
            if f.leader is None or f.positions[f.leader][1] >= y:
                return "idle"
            state["at"] = f.t
        return f.t - state["at"] < wait

    return fn
FLAP_SLOPE = 0.45  # a flap that sends the field to a side lane: steeper than anything rests on


def _dice_gate(space, w, top, lane_bottom, rng, style, *, slope=GATE_SLOPE, flap=FLAP_SLOPE, depth=1.0,
               fill=True):
    """One dice gate: a funnel to a centre throat with a hold door across it,
    two flaps under the throat, and three lanes. The mechanic makes one flap
    solid (left or right lane) or neither (the middle lane falls straight
    through): the throat gathers the whole field, so wherever a marble
    arrives from, it takes the lane the die chose.

    Sizes, all from the marble: the throat is the funnel section's (0.21 w,
    past the arch width); the middle lane is the throat and 30 px each side;
    a flap's high end starts past the throat's far lip, so nothing that comes
    through can miss it, and its low end runs 34 px past the divider so a
    marble rolling off it falls clear of the divider's top; each divider's
    top sits on its flap's line, so a solid flap has no seam to catch on."""
    thick = style.thickness / 2
    cx, g = w / 2, w * 0.21
    room = marble_room(w)
    run = cx - g / 2 - 14.0
    y_throat = top - run * slope
    d = g / 2 + 30.0  # the middle lane's half width
    hi_x = g / 2 + 6.0  # how far past the centre a flap's high end starts
    lo_x = d + 34.0  # how far the other way its low end reaches
    if y_throat - room * depth - (hi_x + lo_x) * flap < lane_bottom:
        return []  # no room for a gate: build none rather than one that leaves the band (as trap does)
    segments = [((14.0, top), (cx - g / 2, y_throat)), ((w - 14.0, top), (cx + g / 2, y_throat))]
    for a, b in segments:
        _wall(space, a, b, thickness=thick)
    # A solid flap and the throat's far lip make a second throat; 18 px under
    # the throat left it 65 px across and the field queued there for seconds.
    y_hi = y_throat - room * depth
    y_lo = y_hi - (hi_x + lo_x) * flap
    y_div = y_hi - (hi_x + d) * flap - 2.0
    # The doors that make each lane the only way down, one set per face: a
    # side lane is its flap plus a fence from the far lip down to the flap's
    # high end (with the flap that deep, a marble would otherwise slip out
    # under the far lip); the middle lane is a chute from both lips to the
    # divider tops. The mechanic makes one set solid.
    lip_l, lip_r = (cx - g / 2, y_throat), (cx + g / 2, y_throat)
    paths = [
        [((cx + hi_x, y_hi), (cx - lo_x, y_lo)), (lip_r, (cx + hi_x, y_hi))],
        [(lip_l, (cx - d, y_div)), (lip_r, (cx + d, y_div))],
        [((cx - hi_x, y_hi), (cx + lo_x, y_lo)), (lip_l, (cx - hi_x, y_hi))],
    ]
    for x in (cx - d, cx + d):
        _wall(space, (x, y_div), (x, lane_bottom), thickness=thick)
        segments.append(((x, y_div), (x, lane_bottom)))
    lanes = [(7.0, cx - d), (cx - d, cx + d), (cx + d, w - 7.0)]
    kinds = list(LANE_KINDS)
    rng.shuffle(kinds)
    if fill:
        for (x0, x1), kind in zip(lanes, kinds):
            segments += _lane(space, w, x0, x1, y_lo - room * 0.9, lane_bottom + room * 0.3, kind, rng, style)
    # The doors are the section's, so a gate is a gate with or without a die:
    # the hold shuts the throat until the leader has waited there GATE_WAIT s,
    # and every lane door is open, so the field takes the middle lane. A dice
    # mechanic re-clocks them (physics/worlds/dice.py).
    from .mechanics import rig_of  # mechanics imports this module lazily; this way round is safe

    rig = rig_of(style)
    rec = dice_record(style)
    name = f"gate{len(rec['gates'])}_plain"
    hold = ((cx - g / 2, y_throat), (cx + g / 2, y_throat))
    rig.clock(name, _waited(y_throat + 60.0, GATE_WAIT))
    rig.clock(name + "_wait", lambda f, _n=name: bool(f.value(_n)) and f.value(_n) != "idle")
    rig.hold(name + "_wait")
    rig.door(space, *hold, closed=name)
    hold_door = rig.doors[-1]
    if not any(n == "dice_never" for n, _ in rig.clocks):
        rig.clock("dice_never", lambda f: False)
    path_doors = []
    for doors in paths:
        path_doors.append([])
        for a, b in doors:
            rig.door(space, a, b, closed="dice_never")
            path_doors[-1].append(rig.doors[-1])
    rec["gates"].append({
        "top": top, "throat": y_throat, "hold": hold, "hold_door": hold_door, "path_doors": path_doors,
        "plain": name, "paths": paths, "lanes": lanes, "kinds": kinds if fill else ["open"] * 3,
        "lane_top": y_div, "lane_bottom": lane_bottom, "flap_low": y_lo,
        # Where the gate's die sits: under the left funnel wall, clear of every path.
        "die": (54.0, top - 74.0 * slope - 50.0),
        "marks": [((x0 + x1) / 2, y_div - 26.0) for x0, x1 in lanes],
    })
    return segments


def _lane(space, w, x0, x1, top, bottom, kind, rng, style):
    """A lane's contents. `open` is a clear drop; `pegs` a column of single
    pegs down the lane's middle (a peg leaves a marble's room either side);
    `shelves` alternate shelves from the lane's walls — the long way down,
    with a marble's room at every tip and under every shelf."""
    room = marble_room(w)
    thick = style.thickness / 2
    segments = []
    if kind == "pegs":
        r, y, k = 8.0, top - 10.0, 0
        while y > bottom + 10.0:
            x = (x0 + x1) / 2 + (6.0 if k % 2 else -6.0)
            _peg(space, x, y, r)
            style.circles.append((x, y, r))
            y -= 78.0
            k += 1
    elif kind == "shelves":
        span = (x1 - x0) - room * 1.08
        if span < 30:
            return segments
        drop = span * 0.42
        pitch = drop + room * 1.05
        y, left = top, rng.random() < 0.5
        while y - drop > bottom:
            a, b = (((x0 + 3.0, y), (x0 + 3.0 + span, y - drop)) if left
                    else ((x1 - 3.0, y), (x1 - 3.0 - span, y - drop)))
            _wall(space, a, b, thickness=thick)
            segments.append((a, b))
            y -= pitch
            left = not left
    return segments


def dicegate(space, w, top, bottom, rng, style):
    """One dice gate filling the band: funnel, hold, flaps, three lanes."""
    return _dice_gate(space, w, top, bottom, rng, style)


def dicetriple(space, w, top, bottom, rng, style):
    """Three dice gates stacked in one band, for a small field (a duel):
    shallower funnels and flaps (still past the 0.37 anything rests on) and
    lanes that are only a drop, so three fit where one full gate would."""
    each = (top - bottom) / 3
    segments = []
    for k in range(3):
        t = top - k * each
        segments += _dice_gate(space, w, t, t - each + 10.0, rng, style, slope=0.40, flap=0.40, depth=0.6,
                               fill=False)
    return segments


RUNWAY_SLOPE = 0.20


def runway(space, w, top, bottom, rng, style):
    """A start grid: a ramp rising to the right, slope 0.40 (the ramps
    section's), with a lip at its low end, across the middle of the frame.
    It is only a place: the mechanic makes it a door, lines the field up on
    it front (low, against the lip) to back, and drops the whole ramp at
    once, so the back of the grid starts highest and has the longest way
    down. Not against a wall: the pegs keep a marble's room from the walls,
    and a front marble let go there fell the height of the frame untouched.
    A stage raced without a mechanic has no ramp here at all."""
    slope = RUNWAY_SLOPE
    run = min(w * 0.68, (top - bottom) / slope)
    # Which side the front is on is the seed's: whatever the bands below do
    # to one side of the frame, it is not always the front's side.
    side = 1 if rng.random() < 0.5 else -1
    x_lo = w * 0.16 if side > 0 else w * 0.84
    low = (x_lo, top - run * slope)
    dice_record(style)["runway"] = {"a": (x_lo + side * run, top), "b": low, "slope": slope,
                                    "lip": (low, (x_lo, low[1] + 40.0))}
    return []


def diceblock(space, w, top, bottom, rng, style):
    """Six blockers in three rows of two — a floating pair, a pair off the
    walls draining inward, a floating pair — each a tilted bar registered as
    a door that is always shut, so a die (the level's mechanic) can take one
    away and a race without one still has all six. The gaps beside a
    floating bar and past a wall bar's tip are the sieve's tip gap or more;
    rows are a marble's room apart past the tilt."""
    from .mechanics import rig_of  # mechanics imports this module lazily; this way round is safe
    tip_gap = max(0.15 * w, marble_room(w))
    span = 130.0
    tilt = span * 0.36
    if top - bottom < 2 * (tilt + marble_room(w)):
        return []
    blocks = []
    for i, y in enumerate((top - tilt / 2, (top + bottom) / 2, bottom + tilt / 2)):
        if i == 1:
            reach = min(span, (w - 14.0 - tip_gap * 2.5) / 2)
            blocks.append(((7.0, y + tilt / 2), (7.0 + reach, y - tilt / 2)))
            blocks.append(((w - 7.0, y + tilt / 2), (w - 7.0 - reach, y - tilt / 2)))
        else:
            gap = (w - 14.0 - 2 * span) / 3
            first = 1 if rng.random() < 0.5 else -1
            for k, s in enumerate((first, -first)):
                x0 = 7.0 + gap + k * (span + gap)
                blocks.append(((x0, y + s * tilt / 2), (x0 + span, y - s * tilt / 2)))
    rig = rig_of(style)
    record = []
    for a, b in blocks:
        rig.door(space, a, b, thickness=style.thickness / 2)
        record.append((a, b, rig.doors[-1]))  # the mechanic sets a door's clock and colour
    dice_record(style)["blocks"] = record
    return []


def surfaceramps(space, w, top, bottom, rng, style):
    """The ramps section, with its band recorded so a die can roll its surface."""
    segments = ramps(space, w, top, bottom, rng, style)
    dice_record(style)["bands"].append((top, bottom))
    return segments


# Appended to the tables above rather than written into them.
SECTIONS.update({"dicegate": dicegate, "dicetriple": dicetriple, "runway": runway, "diceblock": diceblock,
                 "surfaceramps": surfaceramps})
SECTION_WORDS.update({
    "dicegate": "a dice gate that opens one of three paths", "dicetriple": "three dice gates",
    "runway": "a start ramp behind a gate", "diceblock": "six blockers a die can remove",
    "surfaceramps": "zigzag ramps whose surface a die rolls",
})


def compose(parts: list[tuple[str, float]], *, top_frac: float = 0.90, bottom_frac: float = 0.20):
    """A stage builder from sections stacked top to bottom.

    `parts` is [(section name, share of the height), ...]. Bands get heights
    in proportion to their shares, each is inset by `margin`, and the
    marbles start spread across the middle 60% of the width above the first.
    """
    for name, _ in parts:
        if name not in SECTIONS:
            raise ValueError(f"no section {name!r}; have {sorted(SECTIONS)}")
    total = sum(share for _, share in parts)

    def build(space, w, h, rng, style):
        top, bottom = h * top_frac, h * bottom_frac
        m = margin(w)
        segments = []
        y = top
        for name, share in parts:
            band = (top - bottom) * share / total
            segments += SECTIONS[name](space, w, y - m, y - band + m, rng, style)
            y -= band
        return segments, w * 0.6, _centred_lanes(w)

    build.parts = tuple(parts)  # type: ignore[attr-defined]
    return build


def describe_parts(parts) -> str:
    words = [SECTION_WORDS[name] for name, _ in parts]
    return "a stage of " + ", then ".join(words)


# --- World 3, polarity swap: magnets that do more than pull ------------------------------
#
# Every section below keeps the magnet's measured law (`magnet_accel`, peak
# MAGNET_PULL) and changes where a field is, how far it reaches, or — through
# the round's rig (generators/mechanics.py) — which way and how hard it acts
# over time. What a magnet *does* over time is a level's mechanic
# (physics/worlds/polarity.py); what is here is geometry. Each section notes
# on the rig which magnets it made (`magnet_roles`), so a mechanic can flip
# the band's magnets without flipping the arm's.

def magnet_roles(style) -> dict[int, str]:
    """Magnet index -> the role a World 3 section gave it (none: "band")."""
    from .mechanics import rig_of
    return rig_of(style).__dict__.setdefault("magnet_roles", {})


def _add_magnet(space, style, x, y, core, soft, reach, role, *, solid=True) -> int:
    if solid:
        _magnet(space, x, y, core)
    style.magnets.append((x, y, core, soft, reach, MAGNET_PULL))
    k = len(style.magnets) - 1
    magnet_roles(style)[k] = role
    return k


# Two walls' fields meet in the middle: each reaches past the centre line by
# a little, so a marble down the middle is pulled both ways at once and one
# off centre is pulled harder by the nearer wall. Where they overlap the sum
# is capped at the one gravity the pull was measured safe at.
TUG_REACH = 3.5


def tug(space, w, top, bottom, rng, style):
    """A tug of war: one magnet on each wall, level with each other, fields
    wide enough to meet in the middle. The racing line bends toward
    whichever wall a marble drifted to."""
    room = marble_room(w)
    core = w * rng.uniform(0.040, 0.046)
    soft = core + w * MARBLE_R
    reach = soft * TUG_REACH
    y = (top + bottom) / 2 + rng.uniform(-0.1, 0.1) * (top - bottom)
    lo = 7.0 + room + core
    for x in (lo, w - lo):
        _add_magnet(space, style, x, y, core, soft, reach, "tug")
    return []


def side_magnets(space, w, top, bottom, rng, style):
    """Magnets down one side of the frame (the left; a mirrored round puts
    them on the right). At least two rows, a reach or more apart,
    alternating between the wall and most of a reach in from it, so the left
    half is all field and the right half is none. Neighbouring fields
    overlap a little; the sum is capped at the measured one gravity."""
    height = top - bottom
    room = marble_room(w)
    core = w * rng.uniform(0.038, 0.044)
    soft = core + w * MARBLE_R
    reach = soft * MAGNET_REACH
    lo = 7.0 + room + core
    inner = min(lo + reach * 0.85, w / 2 - core - room / 2)
    rows = max(2, int(height // reach))
    gap = height / rows
    for i in range(rows):
        x = lo if i % 2 == 0 else inner
        _add_magnet(space, style, x, top - gap * (i + 0.5), core, soft, reach, "side")
    return []


def detour(space, w, top, bottom, rng, style):
    """The track splits in two lanes. One is shielded — no field reaches it
    — and longer, a ledge sending it across; the other is short, a straight
    drop past magnets on its outer wall. Which side is which is the seed's.

    The magnets sit a marble's room off the outer wall and their reach stops
    short of the divider, so the shielded lane is field-free by geometry, not
    by a rule the force law would have to know about."""
    mid = w / 2
    t = style.thickness / 2
    room = marble_room(w)
    # A peak on top of the divider: nothing balances on an apex.
    peak = 34.0
    segments = [((mid - peak, top - peak), (mid, top)), ((mid, top), (mid + peak, top - peak)),
                ((mid, top), (mid, bottom))]
    for a, b in segments:
        _wall(space, a, b, thickness=t)
    magnet_side = -1 if rng.random() < 0.5 else 1  # -1: magnets in the left lane
    # The shielded lane: ledges from alternate walls (one, in the band the
    # detour stage gives it), each past the lane's middle so a marble off one
    # tip lands on the next, leaving more than a marble's room to the
    # opposite wall. Steep, 0.70, because the long way has to be a real
    # choice: at 0.40, two ledges, the shielded lane won 0 races in 48 and
    # at 0.60 6; at 0.70 (with the magnet lane pulling 4x, polarity.py) it
    # wins 17 of 48 with 92 of 192 marbles through it.
    outer = 7.0 if magnet_side > 0 else w - 7.0
    lane = abs(mid - outer)
    span = min(lane * 0.6, lane - room * 1.3)
    slope = 0.70
    drop = span * slope
    pitch = drop + room * 0.8  # a ledge clears the next one's tip by a marble and a half
    count = max(1, int((top - peak - room * 0.6 - bottom) // pitch))
    y = top - peak - room * 0.6
    for i in range(count):
        start = outer if i % 2 == 0 else mid
        toward = 1 if start < (outer + mid) / 2 else -1
        a = (start + toward * 3.0, y)
        b = (start + toward * (3.0 + span), y - drop)
        _wall(space, a, b, thickness=t)
        segments.append((a, b))
        y -= pitch
    # The magnet lane: cores a marble's room off the outer wall, rows a reach
    # and a quarter apart; the reach ends short of the divider.
    core = w * rng.uniform(0.038, 0.044)
    soft = core + w * MARBLE_R
    x = 7.0 + room + core if magnet_side < 0 else w - 7.0 - room - core
    reach = min(soft * MAGNET_REACH, abs(mid - x) - t - 6.0)
    rows = max(2, int((top - bottom) // (reach * 1.25)))
    gap = (top - bottom) / rows
    for i in range(rows):
        _add_magnet(space, style, x, top - gap * (i + 0.5), core, soft, reach, "lane")
    return segments


# The arm's fields are shorter than a fixed magnet's: they sweep, and at the
# full MAGNET_REACH the tips reached into the peg bands above and below the
# arm and held marbles against the pegs there (stage QA: 13 of 88 parked).
ARM_REACH = 2.3


def arm(space, w, top, bottom, rng, style):
    """A rotating magnet arm: one long bar turning about the middle of the
    band with a magnet's core on each tip, so the field sweeps the track.
    A marble the tip meets on its way up rides it backward.

    The bar is a kinematic body like a spinner's, and it is drawn as one.
    The fields move with its tips (`Rig.magnet_track`), read off the body
    every frame, so the drawing, the force and `launched` agree. The tips
    clear both walls by a marble's room at every angle."""
    from .mechanics import rig_of
    from .. import settings

    rig = rig_of(style)
    height = top - bottom
    room = marble_room(w)
    core = w * rng.uniform(0.036, 0.040)
    cx, cy = w / 2, (top + bottom) / 2
    half = max(40.0, min(w / 2 - 7.0 - room - core, height / 2 - core))
    omega = rng.choice([-1, 1]) * rng.uniform(0.55, 0.75)
    phase = rng.uniform(0.0, 2 * math.pi)
    body = pymunk.Body(body_type=pymunk.Body.KINEMATIC)
    body.position = (cx, cy)
    body.angle = phase
    body.angular_velocity = omega
    bar = pymunk.Segment(body, (-half, 0), (half, 0), style.thickness / 2)
    bar.elasticity, bar.friction = BAR_BOUNCE, 0.30
    space.add(body, bar)
    for side in (-1, 1):
        tip = pymunk.Circle(body, core, offset=(side * half, 0))
        tip.elasticity, tip.friction = 0.50, 0.12
        space.add(tip)
    # The renderers draw a spinner at phase + omega * t on the clip's clock,
    # which starts `skip_start_s` into the simulation; the bar is drawn where
    # the body is by starting its drawn phase that far on.
    skip_s = float(rig.params.get("skip_start_s", settings.load().render.get("skip_start_s", 0)))
    style.spinners.append((cx, cy, half, omega, phase + omega * skip_s))
    soft = core + w * MARBLE_R
    reach = soft * ARM_REACH
    moving = rig.__dict__.setdefault("moving_magnets", [])
    for side in (-1, 1):
        x, y = body.local_to_world((side * half, 0))
        k = _add_magnet(space, style, x, y, core, soft, reach, "arm", solid=False)
        moving.append((k, body, side * half))
    if rig.magnet_tracker is None:
        def where(frame, _style=style, _moving=moving):
            out = [None] * len(_style.magnets)
            for k, b, off in _moving:
                px, py = b.local_to_world((off, 0))
                out[k] = [round(px, 2), round(py, 2)]
            return out
        rig.clock("magnet_track", where)
        rig.magnet_track("magnet_track")
    return []


# A clump magnet's field reaches most of the way across the frame, so a
# grip catches marbles wherever they come down. How strong it is, and when,
# is the level's (`magnet-clump`): left alone it pulls like any other.
CLUMP_REACH = 0.40  # of the width


def clump(space, w, top, bottom, rng, style):
    """One big magnet in the middle of the band, with a field that reaches
    most of the way to both walls: what a level's grip (`magnet-clump`)
    makes strong enough to hold the whole field in one clump."""
    core = w * rng.uniform(0.046, 0.052)
    soft = core + w * MARBLE_R
    reach = w * CLUMP_REACH
    x = w / 2 + rng.uniform(-0.03, 0.03) * w
    y = (top + bottom) / 2
    _add_magnet(space, style, x, y, core, soft, reach, "clump")
    return []


SECTIONS.update({"tug": tug, "side-magnets": side_magnets, "detour": detour, "arm": arm, "clump": clump})
SECTION_WORDS.update({
    "tug": "a magnet on each wall pulling against the other",
    "side-magnets": "magnets down one side",
    "detour": "a split into a shielded lane and a magnet lane",
    "arm": "a rotating magnet arm",
    "clump": "one big magnet that can grab the whole field",
})

