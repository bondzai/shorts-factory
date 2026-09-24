"""The eleven hand-built stages, one function each.

Each returns (segments, runway, lanes_for) and fills `style` with what it
built. They predate the section kit (stagekit) and are kept exactly as they
were measured: every published clip replays through them.
"""

from __future__ import annotations

import math
import random

import pymunk

from ..stagekit import _peg as peg, _rocker as rocker, _spinner as spinner, _wall as wall
from .model import ROCK_AMPLITUDE, TIP_GAP, Style

def build_zigzag(space, w, h, rng, style):
    """Zigzag ramps steep enough that the marbles never come to rest.

    A shallow ramp looks fine in a screenshot and stalls in the solver — at a
    slope of 0.15 the marbles stop dead after four seconds, so the slope is held
    near 0.4 whatever else changes. Ramp count and span move together: span is
    derived from the slope, so more ramps means shorter ones and the total path
    length — and the clip's duration — stays where QC wants it.
    """
    # Five was in this list until a forced test stalled 12 times out of 12.
    ramps = rng.choice([6, 7, 8, 9])
    slope = rng.uniform(0.37, 0.44)
    top, bottom = h - 80.0, 40.0
    step = (top - bottom) / ramps
    span = min(step / slope, w - 90.0)
    mirrored = rng.random() < 0.5
    segments = []
    for i in range(ramps):
        y = top - i * step
        starts_left = (i % 2 == 0) != mirrored
        a, b = ((26.0, y), (26.0 + span, y - step)) if starts_left else ((w - 26.0, y), (w - 26.0 - span, y - step))
        wall(space, a, b, thickness=style.thickness / 2)
        segments.append((a, b))
    runway = span * 0.62
    lanes = lambda count: [(45.0 + i * (runway / max(count - 1, 1))) if not mirrored else w - (45.0 + i * (runway / max(count - 1, 1))) for i in range(count)]
    return segments, runway, lanes


def build_pegboard(space, w, h, rng, style):
    """A Galton board: rows of pegs, offset row to row, nothing to rest on.

    Nothing here can stall — a peg is a point, not a ledge — so the only tuning
    is pace, done with gravity rather than geometry.
    """
    rows = rng.randint(7, 10)
    cols = rng.randint(5, 7)
    r = rng.uniform(6.5, 9.5)
    top, bottom = h * 0.80, h * 0.20
    pitch = (w - 60.0) / cols
    for i in range(rows):
        y = top - (top - bottom) * i / max(rows - 1, 1)
        offset = pitch / 2 if i % 2 else 0.0
        for j in range(cols + (0 if i % 2 else 1)):
            x = 30.0 + offset + j * pitch
            if 12 < x < w - 12:
                peg(space, x, y, r)
                style.circles.append((x, y, r))
    return [], w * 0.6, lambda count: [w * 0.2 + (w * 0.6) * i / max(count - 1, 1) for i in range(count)]


def build_bumpers(space, w, h, rng, style):
    """Pinball: big elastic bumpers in a staggered lattice, two guides at the bottom.

    Dense enough that no marble falls straight through; the first version had
    eight bumpers and every marble found the gap.
    """
    rows = rng.randint(6, 8)
    cols = 4
    top, bottom = h * 0.80, h * 0.26
    pitch = (w - 40.0) / cols
    for i in range(rows):
        y = top - (top - bottom) * i / max(rows - 1, 1)
        offset = pitch / 2 if i % 2 else 0.0
        for j in range(cols + (0 if i % 2 else 1)):
            x = 20.0 + offset + j * pitch + rng.uniform(-8, 8)
            if 18 < x < w - 18:
                r = rng.uniform(13.0, 19.0)
                peg(space, x, y + rng.uniform(-6, 6), r, elasticity=0.9)
                style.circles.append((x, y, r))
    segments = [((26.0, h * 0.22), (w * 0.40, h * 0.10)), ((w - 26.0, h * 0.22), (w * 0.60, h * 0.10))]
    for a, b in segments:
        wall(space, a, b, thickness=style.thickness / 2)
    return segments, w * 0.6, lambda count: [w * 0.2 + (w * 0.6) * i / max(count - 1, 1) for i in range(count)]


def build_funnels(space, w, h, rng, style):
    """Three or four funnels in series, throats offset left and right.

    Each funnel is two ramps meeting at a gap; the marbles converge, jostle for
    the throat, and spill out in a new order. The throat is measured in
    marble radii, because an arch of marbles across a narrow throat is the one
    thing that stalls a funnel: below about three radii it happens.
    """
    funnels = rng.choice([3, 4])
    top, bottom = h * 0.82, h * 0.16
    step = (top - bottom) / funnels
    segments = []
    for i in range(funnels):
        y_top = top - i * step
        y_throat = y_top - step * 0.62
        cx = w * rng.choice([0.34, 0.5, 0.66]) if i else w * 0.5
        gap = w * rng.uniform(0.17, 0.21)  # about 3.5-4 radii of the largest marble
        left = ((14.0, y_top), (cx - gap / 2, y_throat))
        right = ((w - 14.0, y_top), (cx + gap / 2, y_throat))
        for a, b in (left, right):
            wall(space, a, b, thickness=style.thickness / 2)
            segments.append((a, b))
    return segments, w * 0.7, lambda count: [w * 0.15 + (w * 0.7) * i / max(count - 1, 1) for i in range(count)]


def build_gauntlet(space, w, h, rng, style):
    """A lane that narrows to two thirds of the frame with nothing in it but
    spinning bars, stacked. The bars are added by add_spinners; here only the
    lane, so a marble knocked sideways comes back to the bars instead of
    dropping past them along the wall.
    """
    inset = w * rng.uniform(0.12, 0.17)
    segments = [((6.0, h * 0.86), (inset, h * 0.74)), ((w - 6.0, h * 0.86), (w - inset, h * 0.74)),
                ((inset, h * 0.74), (inset, h * 0.12)), ((w - inset, h * 0.74), (w - inset, h * 0.12))]
    for a, b in segments:
        wall(space, a, b, thickness=style.thickness / 2)
    style.lane = segments[2:]
    # A few pegs between the bars, alternating sides, so a marble the bars
    # miss is still slowed.
    # Centre only: the pegs that sat at 0.28/0.72 of the lane were under the
    # bar tips, and a marble wedged between peg and tip stayed there.
    for frac in (0.16, 0.25, 0.35, 0.45, 0.55, 0.65):
        x = inset + (w - 2 * inset) * 0.5 + rng.uniform(-12, 12)
        r = rng.uniform(9.0, 12.0)
        peg(space, x, h * frac, r, elasticity=0.75)
        style.circles.append((x, h * frac, r))
    lane = w - 2 * inset
    return segments, lane * 0.8, lambda count: [inset + lane * 0.1 + lane * 0.8 * i / max(count - 1, 1) for i in range(count)]


def build_cascade(space, w, h, rng, style):
    """Chutes that split and rejoin: a row of ramps meeting in the middle (a
    V, one gap), then a row parting from the middle (a peak, two gaps), and
    so on down. A marble picks a side at every peak and meets the others
    again at every V, so the order keeps changing. The peak is a short flat
    cap, not a point, so nothing balances on it.
    """
    rows = rng.choice([5, 6])
    top, bottom = h * 0.84, h * 0.14
    step = (top - bottom) / rows
    drop = step * 0.55
    gap = w * rng.uniform(0.16, 0.20)
    segments = []
    for i in range(rows):
        y = top - i * step
        if i % 2 == 0:  # V: walls in, gap in the middle
            pairs = [((14.0, y), (w / 2 - gap / 2, y - drop)), ((w - 14.0, y), (w / 2 + gap / 2, y - drop))]
        else:  # peak: from the middle out, a whole gap left at each wall
            # The cap is a short ramp, not a shelf: a flat cap is a ledge a
            # marble rests on, a point is an apex it balances on (measured,
            # both). Tilted, it sheds whatever lands on it.
            cap = w * 0.06
            tilt = 1 if rng.random() < 0.5 else -1
            cap_a, cap_b = (w / 2 - cap, y + tilt * cap * 0.4), (w / 2 + cap, y - tilt * cap * 0.4)
            pairs = [(cap_a, (gap + 14.0, y - drop)), (cap_b, (w - gap - 14.0, y - drop)), (cap_a, cap_b)]
        for a, b in pairs:
            wall(space, a, b, thickness=style.thickness / 2)
            segments.append((a, b))
    return segments, w * 0.7, lambda count: [w * 0.15 + (w * 0.7) * i / max(count - 1, 1) for i in range(count)]


def build_pinwheel(space, w, h, rng, style):
    """One big wheel with four arms in the middle of the frame, and a ring of
    pegs around it. The wheel is what the eye lands on; it sweeps a marble
    aside, holds another, and the pegs below sort out the difference."""
    cx, cy = w / 2 + rng.uniform(-w * 0.06, w * 0.06), h * rng.uniform(0.50, 0.58)
    half = w * rng.uniform(0.26, 0.32)
    omega = rng.choice([-1, 1]) * rng.uniform(0.9, 1.4)
    phase = rng.uniform(0, 3.14)
    for extra in (0.0, math.pi / 2):
        spinner(space, cx, cy, half, omega, phase + extra, style.thickness / 2)
        style.spinners.append((cx, cy, half, omega, phase + extra))
    # Pegs above and below the wheel, sparse, never inside its sweep.
    r = rng.uniform(7.0, 10.0)
    for y_frac in (0.84, 0.78, 0.72, 0.66, 0.40, 0.34, 0.28, 0.22, 0.16):
        cols = 5 if int(y_frac * 100) % 4 == 0 else 6
        for j in range(cols):
            x = 30.0 + (w - 60.0) * (j + (0.5 if cols == 4 else 0)) / max(cols - (0 if cols == 4 else 1), 1)
            y = h * y_frac
            if math.hypot(x - cx, y - cy) > half + 40:
                peg(space, x, y, r)
                style.circles.append((x, y, r))
    return [], w * 0.6, lambda count: [w * 0.2 + (w * 0.6) * i / max(count - 1, 1) for i in range(count)]


def build_sieve(space, w, h, rng, style):
    """Rows of short bars with gaps between them, each bar tilted so nothing
    rests on it. Offsets alternate row to row, so a marble that drops
    through one gap lands on a bar in the next.

    The pocket, seen rather than guessed: a marble wedges between the low
    tip of one bar and the high tip of the next, and with four bars a row
    the tips were 67px apart against a 60px marble. So the gap between tips
    is what is sized, and the bar takes what is left of the pitch. Two other
    fixes were tried first and measured worse: sloping the outer bars inward
    made a V with the next bar in (11 of 20 finished), and leaving out the
    bars near the walls opened a free-fall channel that finished under the
    QC floor (7 of 24).
    """
    # Four to six rows, not six to eight: at eight the rows were 82px apart
    # and a 60px marble wedged between a bar and the dipped end of the bar
    # in the row above, at the walls where those ends meet (46% of marbles
    # ended the clip there, measured).
    rows = rng.randint(3, 4)
    per_row = rng.choice([3, 4])
    # The bottom row stays above the run-in throat, for the same reason the
    # drums do: at 0.22h the last stuck marbles were pinned between a bar
    # and a throat arm. Three or four rows over this height keeps the rows
    # at least 134px apart, past the wedge a 60px marble finds at 82px.
    top, bottom = h * 0.84, h * 0.42
    pitch = w / per_row
    segments = []
    for i in range(rows):
        y = top - (top - bottom) * i / max(rows - 1, 1)
        offset = pitch / 2 if i % 2 else 0.0
        direction = 1 if i % 2 else -1  # every bar in a row slopes the same way
        for j in range(per_row + 1):
            cx = offset + j * pitch
            span = pitch - max(pitch * rng.uniform(0.50, 0.62), TIP_GAP * w)
            a_x, b_x = cx - span / 2, cx + span / 2
            if b_x < 6 or a_x > w - 6:
                continue
            # A tip that stops short of a wall needs the same clearance as a
            # tip facing another tip: the last stuck marble, r=21, sat at
            # x=509 against a tip that ended 41px from the wall.
            if a_x >= 6 and a_x < TIP_GAP * w:
                a_x = TIP_GAP * w
            if b_x <= w - 6 and b_x > w - TIP_GAP * w:
                b_x = w - TIP_GAP * w
            if b_x - a_x < 24:
                continue
            span = b_x - a_x
            # A bar that meets a wall has its wall end high, whichever way
            # the row slopes: sloping down into the wall makes a corner a
            # marble rolls into and stays in (seen at x=30 and x=506).
            direction_here = 1 if a_x < 6 else (-1 if b_x > w - 6 else direction)
            tilt = direction_here * rng.uniform(0.42, 0.55) * span
            a, b = (a_x, y + tilt / 2), (b_x, y - tilt / 2)
            wall(space, a, b, thickness=style.thickness / 2, friction=0.12)
            segments.append((a, b))
    return segments, w * 0.6, lambda count: [w * 0.2 + (w * 0.6) * i / max(count - 1, 1) for i in range(count)]


def build_pachinko(space, w, h, rng, style):
    """Pegs on concentric arcs around a central bumper: a marble is thrown
    outward by the bumper and then filtered back in by the arcs."""
    cx, cy = w / 2, h * rng.uniform(0.60, 0.68)
    big = w * rng.uniform(0.07, 0.09)
    peg(space, cx, cy, big, elasticity=0.85)
    style.circles.append((cx, cy, big))
    r = rng.uniform(6.5, 9.0)
    for ring, radius in enumerate([w * 0.22, w * 0.36, w * 0.50, w * 0.64]):
        n = 5 + ring * 3
        for k in range(n):
            ang = math.pi + math.pi * (k + 0.5) / n  # the lower half only, an arc that opens downward
            x, y = cx + radius * math.cos(ang), cy + radius * math.sin(ang)
            if 14 < x < w - 14 and 130 < y < h * 0.9:
                peg(space, x, y, r)
                style.circles.append((x, y, r))
    return [], w * 0.6, lambda count: [w * 0.2 + (w * 0.6) * i / max(count - 1, 1) for i in range(count)]


def build_rockers(space, w, h, rng, style):
    """Planks that rock on a pivot, tipping one way and then the other, in
    staggered rows. A marble that lands on a plank rides it down and is
    thrown off the low end — which end that is depends on when it arrived."""
    rows = rng.randint(4, 5)
    top, bottom = h * 0.80, h * 0.26
    clear = w * 0.12  # a plank tip never comes closer to a wall than this: a marble and air
    segments = []
    for i in range(rows):
        y = top - (top - bottom) * i / max(rows - 1, 1)
        count = 2 if i % 2 == 0 else 3
        for j in range(count):
            x = w * (j + 0.5) / count + (w * 0.08 if i % 2 else 0) * rng.choice([-1, 1]) * 0.3
            half = w * rng.uniform(0.11, 0.15)
            # Eight seeds were measured with a marble pinned at x = 0.06 w,
            # jittering between a plank tip and the wall for the whole clip.
            half = min(half, x - clear, w - clear - x)
            omega = rng.uniform(1.0, 1.8)
            phase = rng.uniform(0, 6.283)
            body = rocker(space, x, y, half, omega, phase, style.thickness / 2)
            style.rockers.append((x, y, half, omega, phase))
            style.kinematics.append(("rocker", body, (omega, phase)))
            # The hub is a bump, not just a drawing: a marble that lands on
            # the pivot of a symmetric rocker sits there rocking with it.
            peg(space, x, y, style.thickness * 0.9, elasticity=0.5)
        # Deflectors on both walls under each row: whatever a plank throws
        # at the wall is turned back to the middle instead of sliding down it.
        if i < rows - 1:
            yd = y - (top - bottom) / max(rows - 1, 1) * 0.55
            for a, b in (((6.0, yd + w * 0.07), (w * 0.11, yd)), ((w - 6.0, yd + w * 0.07), (w - w * 0.11, yd))):
                wall(space, a, b, thickness=style.thickness / 2)
                segments.append((a, b))
    return segments, w * 0.6, lambda count: [w * 0.2 + (w * 0.6) * i / max(count - 1, 1) for i in range(count)]


def build_drums(space, w, h, rng, style):
    """Large spinning drums, staggered. A marble that lands on one is carried
    round by friction and let go on the far side, so the drum's direction
    decides which way it heads next.

    Every drum is sized from the gaps around it — to its neighbours in the
    row, to the walls, and to the rows above and below — each of which has
    to clear the biggest marble with air. Three versions were measured
    before this one: drums turning toward each other made a pinch; a
    3-drum row's outer drum sat 31px from the wall; and rows 160px apart
    with 110px drums left 50px between rows, less than a marble, where 68%
    of them ended the clip. Three-drum rows come out small, two-drum rows
    big, and every drum in a row turns the same way.
    """
    rows = rng.randint(4, 5)
    # The bottom row stays above the run-in throat: at 0.24h the lowest
    # drums overlapped the throat's mouth and pinned marbles between a drum
    # and an arm — every stuck marble in the diagnostic sat at that height.
    top, bottom = h * 0.84, h * 0.44
    row_gap = (top - bottom) / max(rows - 1, 1)
    for i in range(rows):
        y = top - (top - bottom) * i / max(rows - 1, 1)
        count = 2 if i % 2 == 0 else 3
        r = min(w * rng.uniform(0.06, 0.11), (w / (count + 1) - w * 0.13) / 2, (row_gap - w * 0.14) / 2)
        direction = rng.choice([-1, 1])
        for j in range(count):
            x = w * (j + 1) / (count + 1)
            omega = direction * rng.uniform(1.6, 2.6)
            body = pymunk.Body(body_type=pymunk.Body.KINEMATIC)
            body.position = (x, y)
            body.angular_velocity = omega
            shape = pymunk.Circle(body, r)
            shape.elasticity = 0.25
            shape.friction = 0.9
            space.add(body, shape)
            style.drums.append((x, y, r, omega))
    return [], w * 0.6, lambda count: [w * 0.2 + (w * 0.6) * i / max(count - 1, 1) for i in range(count)]
