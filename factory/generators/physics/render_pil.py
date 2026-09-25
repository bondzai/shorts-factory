"""The original renderer: still frames drawn with PIL.

Kept because it is what every published clip was drawn with; `render.engine`
picks between this and the pygame one.
"""

from __future__ import annotations

import math
import random

from PIL import Image, ImageDraw

from ..mechanics import hidden, magnets_at
from . import render_mech
from .model import ROCK_AMPLITUDE, Style, trap_angle
from .registry import STAGES

def frames_pil(states, balls, segments, sim_w, sim_h, overlay=None, style=None,
    winner_frame=None, winner=None, ask=None,
) -> Iterator[bytes]:
    style = style or Style()
    # What the mechanics recorded; empty for a race without any, and then
    # every branch that reads it is skipped.
    mech = getattr(style, "mech", None) or {}
    colours = {b.name: b.color for b in balls}
    finish_line = style.stage in STAGES and not mech.get("no_finish")  # races have one; the funnel does not
    winner_index = next((i for i, b in enumerate(balls) if b.name == winner), None)
    burst_rng = random.Random(style.seed * 17 + 3)
    burst = [(burst_rng.uniform(-1, 1), burst_rng.uniform(0.2, 1.0), burst_rng.uniform(0, 6.283),
              burst_rng.choice([(255, 210, 80), (255, 255, 255), (120, 200, 255), (255, 120, 140)]))
             for _ in range(46)]
    for frame_index, positions in enumerate(states):
        image = Image.new("RGB", (sim_w, sim_h), style.background)
        draw = ImageDraw.Draw(image)
        if finish_line:
            # A chequered band at the finish: the question the clip asks, drawn.
            fy = sim_h - 110.0
            cell = 14
            for k in range(0, sim_w, cell):
                shade = style.structure if (k // cell) % 2 == 0 else tuple(min(255, c + 70) for c in style.structure)
                draw.rectangle([k, fy - 4, k + cell, fy + 4], fill=shade)
        if mech:
            render_mech.pil_under(draw, style, mech, frame_index, frame_index / 30.0, sim_h)
        # Trails: where each marble just was, fading into the backdrop.
        for ball, index in zip(balls, range(len(balls))):
            if mech and hidden(mech, ball.name, frame_index):
                continue
            for back in range(6, 0, -1):
                j = frame_index - back * 2
                if j < 0:
                    continue
                px, py = states[j][index]
                mix = 0.08 + 0.05 * (6 - back)
                colour = tuple(int(bg + (c - bg) * mix) for c, bg in zip(ball.color, style.background))
                r = ball.radius * (0.35 + 0.08 * (6 - back))
                draw.ellipse([px - r, sim_h - py - r, px + r, sim_h - py + r], fill=colour)
        t = frame_index / 30.0
        for sx, sy, half, omega, phase, *bias in style.rockers:
            angle = (bias[0] if bias else 0.0) + ROCK_AMPLITUDE * math.sin(omega * t + phase)
            dx, dy = math.cos(angle) * half, math.sin(angle) * half
            draw.line([(sx - dx, sim_h - (sy - dy)), (sx + dx, sim_h - (sy + dy))],
                      fill=tuple(min(255, c + 60) for c in style.structure), width=style.thickness)
            hub = style.thickness * 0.9
            draw.ellipse([sx - hub, sim_h - sy - hub, sx + hub, sim_h - sy + hub], fill=style.structure)
        for sx, sy, r, omega in style.drums:
            draw.ellipse([sx - r, sim_h - sy - r, sx + r, sim_h - sy + r],
                         fill=tuple(min(255, c + 22) for c in style.structure))
            for k in range(3):  # spokes, so the spin can be seen
                angle = omega * t + k * 2.094
                draw.line([(sx, sim_h - sy), (sx + math.cos(angle) * r * 0.9, sim_h - (sy + math.sin(angle) * r * 0.9))],
                          fill=tuple(min(255, c + 70) for c in style.structure), width=max(2, style.thickness // 2))
        for hx, hy, bore, depth, period, phase in style.traps:
            angle = trap_angle(t, period, phase)
            ex, ey = hx + math.cos(angle) * bore, hy + math.sin(angle) * bore
            # Brighter than the pit's own walls: the door is the part that
            # moves, and a viewer has to read which one it is before it does.
            draw.line([(hx, sim_h - hy), (ex, sim_h - ey)],
                      fill=tuple(min(255, c + 60) for c in style.structure), width=style.thickness)
            hub = style.thickness * 0.8
            draw.ellipse([hx - hub, sim_h - hy - hub, hx + hub, sim_h - hy + hub], fill=style.structure)
        for sx, sy, half, omega, phase in style.spinners:
            angle = phase + omega * t
            dx, dy = math.cos(angle) * half, math.sin(angle) * half
            draw.line([(sx - dx, sim_h - (sy - dy)), (sx + dx, sim_h - (sy + dy))],
                      fill=tuple(min(255, c + 60) for c in style.structure), width=style.thickness)
            hub = style.thickness * 0.9
            draw.ellipse([sx - hub, sim_h - sy - hub, sx + hub, sim_h - sy + hub], fill=style.structure)
        for a, b, speed in style.belts:
            draw.line([(a[0], sim_h - a[1]), (b[0], sim_h - b[1])],
                      fill=tuple(min(255, c + 26) for c in style.structure), width=style.thickness)
            for mx, my, ux, uy in belt_marks(a, b, speed, t):
                nx, ny = -uy, ux
                draw.polygon([(mx + ux * 6, sim_h - (my + uy * 6)),
                              (mx - ux * 3 + nx * 4, sim_h - (my - uy * 3 + ny * 4)),
                              (mx - ux * 3 - nx * 4, sim_h - (my - uy * 3 - ny * 4))],
                             fill=tuple(min(255, c + 110) for c in style.structure))
        for mx, my, core, _soft, reach, _pull, polarity in magnets_at(style, mech, frame_index):
            # A magnet is drawn as what it is: a solid core, and the field it
            # pulls with. The rings are where the force actually reaches, so
            # the picture and the physics agree — an obstacle a viewer cannot
            # see moving marbles would read as a bug, not a feature.
            iy = sim_h - my
            draw.ellipse([mx - reach, iy - reach, mx + reach, iy + reach],
                         outline=tuple(min(255, c + 7) for c in style.structure), width=1)
            # Long, narrow arrows converging on the core. Short wide ones were
            # tried and read as markers sitting on the ring — the eye saw an
            # orbit, not a pull. Length is what carries the direction.
            for px, py, ux, uy in magnet_marks(mx, my, reach, t, polarity=polarity):
                nx, ny = -uy, ux
                draw.polygon([(px + ux * 17, sim_h - (py + uy * 17)),
                              (px - ux * 2 + nx * 4, sim_h - (py - uy * 2 + ny * 4)),
                              (px - ux * 2 - nx * 4, sim_h - (py - uy * 2 - ny * 4))],
                             fill=tuple(min(255, c + 78) for c in style.structure))
            # Two poles, split like a bar magnet's: the light half against the
            # dark is what makes the core a magnet and not another peg.
            draw.pieslice([mx - core, iy - core, mx + core, iy + core], 180, 360,
                          fill=tuple(min(255, c + 110) for c in style.structure))
            draw.pieslice([mx - core, iy - core, mx + core, iy + core], 0, 180,
                          fill=tuple(min(255, c + 14) for c in style.structure))
        for a, b in style.gates:
            draw.line([(a[0], sim_h - a[1]), (b[0], sim_h - b[1])],
                      fill=tuple(min(255, c + 34) for c in style.structure), width=style.thickness)
        for a, b in segments:
            draw.line(
                [(a[0], sim_h - a[1]), (b[0], sim_h - b[1])],
                fill=style.structure,
                width=style.thickness,
            )
        for cx, cy, r in style.circles:
            iy = sim_h - cy
            draw.ellipse([cx - r, iy - r, cx + r, iy + r], fill=style.structure)
            draw.ellipse([cx - r * 0.45, iy - r * 0.55, cx - r * 0.05, iy - r * 0.15],
                         fill=tuple(min(255, c + 40) for c in style.structure))
        if mech:
            render_mech.pil_over(draw, style, mech, frame_index, sim_h, colours)
        if style.decoration != "none":
            decorate(draw, style, frame_index, sim_w, sim_h)
        if mech:
            render_mech.pil_field(draw, style, mech, frame_index, positions, balls, sim_h)
        for ball, (x, y) in zip(balls, positions):
            if mech and hidden(mech, ball.name, frame_index):
                continue
            iy = sim_h - y
            r = ball.radius
            draw.ellipse([x - r, iy - r, x + r, iy + r], fill=ball.color)
            draw.ellipse(
                [x - r * 0.42, iy - r * 0.55, x - r * 0.06, iy - r * 0.19],
                fill=tuple(min(255, c + 60) for c in ball.color),
            )
        if winner_frame is not None and winner_index is not None and 0 <= frame_index - winner_frame < 40:
            # The win: a burst from where the winner crossed, one second of it.
            age = (frame_index - winner_frame) / 40.0
            wx, wy = positions[winner_index]
            for ux, uy, spin, colour in burst:
                dist = 26 + age * 170
                x = wx + ux * dist
                y = sim_h - (wy + uy * dist * (1 - age * 0.6) + 30 * age)
                r = 2.6 * (1 - age) + 0.6
                draw.ellipse([x - r, y - r, x + r, y + r], fill=colour)
        if mech:
            image = render_mech.pil_top(image, style, mech, frame_index, sim_w, sim_h)
            draw = ImageDraw.Draw(image)
        if overlay is not None:
            text, font, tx, ty, last = overlay
            if frame_index < last:
                # Fade over the final third rather than cutting, which reads
                # as a dropped frame.
                fade = min(1.0, (last - frame_index) / max(1, last / 3))
                mix = 0.25 + 0.75 * fade
                draw.text((tx, ty), text, font=font,
                          fill=tuple(int(c * mix) for c in style.caption))
        if ask is not None and winner_frame is not None and frame_index >= winner_frame:
            text, font, ax, ay, span = ask
            age = frame_index - winner_frame
            if age < span:
                # Fades in rather than appearing, so it does not read as a
                # different clip spliced on.
                mix = min(1.0, 0.3 + age / max(1, span / 3))
                draw.text((ax, ay), text, font=font,
                          fill=tuple(int(c * mix) for c in style.caption))
        yield image.tobytes()


def belt_marks(a, b, speed: float, t: float, spacing: float = 26.0):
    """Where the chevrons on a belt are at time t: evenly spaced along a→b
    and sliding at the belt's speed, so the belt reads as moving and the
    fast one reads as fast. Returns (x, y, ux, uy) in physics coordinates."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    length = math.hypot(dx, dy) or 1.0
    ux, uy = dx / length, dy / length
    shift = (t * speed) % spacing
    marks, d = [], shift
    while d < length - 4:
        marks.append((a[0] + ux * d, a[1] + uy * d, ux, uy))
        d += spacing
    return marks


def magnet_marks(mx: float, my: float, reach: float, t: float, count: int = 12, polarity: float = 1):
    """Where a magnet's chevrons are at time t: evenly spaced around the edge
    of the field and pointing inward, at the centre.

    Concentric rings alone were tried first and read as a target or an orbit
    diagram, not as a magnet — on the contact sheet the marbles looked like
    they were in orbit rather than being pulled. Inward chevrons say which way
    the force goes, and they say it in the vocabulary the kit already uses:
    a belt draws the same chevron pointing the way it runs. Returns
    (x, y, ux, uy) in physics coordinates, ux/uy being the inward direction.

    A magnet whose polarity clock says it pushes (`polarity` < 0) draws the
    same chevrons turned outward, starting a chevron's length inside the
    ring so they end on it; at 0 (switched off) there are none."""
    marks = []
    if polarity < 0:
        for k in range(count):
            angle = t * 0.6 + k * 2 * math.pi / count
            px, py = mx + math.cos(angle) * (reach - 17), my + math.sin(angle) * (reach - 17)
            marks.append((px, py, math.cos(angle), math.sin(angle)))
        return marks
    if polarity == 0:
        return marks
    for k in range(count):
        angle = t * 0.6 + k * 2 * math.pi / count   # a slow turn, so it reads as live
        px, py = mx + math.cos(angle) * reach, my + math.sin(angle) * reach
        marks.append((px, py, -math.cos(angle), -math.sin(angle)))
    return marks


def decorate(draw, style: Style, frame: int, w: int, h: int) -> None:
    """Seasonal particles, deterministic from the seed so a re-render matches.

    Cheap on purpose: a few dozen dots that fall, rise or twinkle. They sit
    behind the marbles and never touch the physics.
    """
    rng = random.Random(style.seed * 31 + 7)
    kind = style.decoration
    count = {"snow": 70, "embers": 40, "sparks": 55, "drops": 60}.get(kind, 0)
    t = frame / 30.0
    for i in range(count):
        x0 = rng.uniform(0, w)
        y0 = rng.uniform(0, h)
        speed = rng.uniform(22, 60)
        size = rng.uniform(1.2, 3.2)
        phase = rng.uniform(0, 6.283)
        if kind == "snow":
            x = (x0 + math.sin(t * 0.8 + phase) * 12) % w
            y = (y0 + t * speed) % h
            draw.ellipse([x - size, y - size, x + size, y + size], fill=(226, 232, 244))
        elif kind == "embers":
            x = (x0 + math.sin(t * 1.4 + phase) * 8) % w
            y = (y0 - t * speed) % h
            glow = int(150 + 100 * (0.5 + 0.5 * math.sin(t * 5 + phase)))
            draw.ellipse([x - size, y - size, x + size, y + size], fill=(255, glow, 40))
        elif kind == "sparks":
            twinkle = 0.5 + 0.5 * math.sin(t * 6 + phase)
            if twinkle > 0.45:
                s2 = size * twinkle
                draw.ellipse([x0 - s2, y0 - s2, x0 + s2, y0 + s2], fill=(240, 205, 90))
        elif kind == "drops":
            y = (y0 + t * speed * 3) % h
            draw.line([(x0, y), (x0, y + size * 4)], fill=(150, 205, 240), width=1)
