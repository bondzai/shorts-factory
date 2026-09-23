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


SECTIONS: dict[str, Callable] = {
    "pegs": pegs, "bumpers": bumpers, "funnel": funnel, "ramps": ramps, "sieve": sieve,
    "drums": drums, "rockers": rockers, "spinners": spinners, "wheel": wheel, "chutes": chutes,
    "belts": belts,
}

# How a section reads in a sentence, for the render's plain description.
SECTION_WORDS = {
    "pegs": "a band of pegs", "bumpers": "bumpers", "funnel": "a funnel", "ramps": "zigzag ramps",
    "sieve": "a sieve of tilted bars", "drums": "spinning drums", "rockers": "rocking planks",
    "spinners": "spinning bars", "wheel": "a four-armed wheel", "chutes": "split-and-rejoin chutes",
    "belts": "conveyor belts",
}


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

