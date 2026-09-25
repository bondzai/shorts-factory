"""The pygame renderer: the same race with motion on every object.

Squash on impact, trails, sparks, glowing spinners, a burst at the line. The
physics is identical; only the drawing differs.
"""

from __future__ import annotations

import math
import random

from .. import fx
from ..mechanics import hidden, magnets_at
from . import render_mech
from .model import ROCK_AMPLITUDE, Style, trap_angle
from .registry import STAGES
from .render_pil import belt_marks, magnet_marks

def frames_pygame(states, balls, segments, sim_w, sim_h, overlay=None, style=None,
    winner_frame=None, winner=None, ask=None, impacts=(), fps=30,
) -> Iterator[bytes]:
    """The race with the juice: every object moves in its own way.

    Marble      squash along the hit on every impact (the audio's impact
                list drives it, so nothing is re-simulated), a fading
                trail, a rolling highlight, a flash on a hard hit.
    Spinners,   a glow that scales with how fast they turn, so a viewer
    drums       reads the danger before a marble reaches it.
    Gates       pulse once when a marble passes the throat.
    Sparks      on hard impacts, in the marble's colour.
    Finish      the chequer flashes, the winner gets rings and a burst.
    Words       the caption slides up and settles; the ask pops in.
    """
    import pygame

    fx.init()
    style = style or Style()
    mech = getattr(style, "mech", None) or {}  # empty: no mechanics, nothing below reads it
    colours = {b.name: b.color for b in balls}
    gone_at = {i: mech["gone"][b.name] for i, b in enumerate(balls) if b.name in (mech.get("gone") or {})}
    finish_line = style.stage in STAGES and not mech.get("no_finish")
    winner_index = next((i for i, b in enumerate(balls) if b.name == winner), None)
    rng = random.Random(style.seed * 17 + 3)
    by_frame: dict[int, list] = {}
    for im in impacts:
        by_frame.setdefault(int(round(im.t * fps)), []).append(im)
    anim = [fx.Ball(trail_len=7) for _ in balls]
    sparks = fx.Particles(rng, gravity=420.0, decay=2.2)
    confetti = fx.Particles(rng, gravity=260.0, decay=0.7)
    gate_pulse = 0.0
    finish_flash = 0.0
    fy = sim_h - 110.0
    Y = lambda y: sim_h - y  # physics is y-up; the screen is y-down
    cap_surface = fx.text_surface(overlay[0], overlay[1].size, sim_w * 0.9, colour=style.caption) if overlay else None
    ask_surface = fx.text_surface(ask[0], ask[1].size, sim_w * 0.9, colour=style.caption) if ask else None
    structure_hi = fx.lighten(style.structure, 60)
    gate_col = fx.lighten(style.structure, 34)

    surface = pygame.Surface((sim_w, sim_h))
    for frame_index, positions in enumerate(states):
        t = frame_index / fps
        dt = 1.0 / fps
        # --- events → animation state
        for im in by_frame.get(frame_index, []):
            i = im.index
            if i >= len(balls):
                continue
            x, y = positions[i]
            # direction of the squash: away from where it was heading
            prev = states[frame_index - 1][i] if frame_index else (x, y)
            dx, dy = x - prev[0], Y(y) - Y(prev[1])
            norm = math.hypot(dx, dy) or 1.0
            anim[i].hit(im.strength, (dx / norm, dy / norm))
            if im.strength > 0.45:
                sparks.burst(x, Y(y), fx.lighten(balls[i].color, 40), int(2 + im.strength * 6),
                             speed=(60, 200 * im.strength + 60), size=(1.2, 2.6))
        for i, gone in gone_at.items():
            if gone == frame_index:
                # Out of the race: a burst in its colour where it went.
                x, y = positions[i]
                sparks.burst(x, Y(y), fx.lighten(balls[i].color, 30), 16, speed=(60, 220), size=(1.4, 3.0))
        for i, (x, y) in enumerate(positions):
            anim[i].step(x, Y(y), balls[i].radius)
            if style.gates:
                throat = min(b[1] for _, b in style.gates)
                prev_y = states[frame_index - 1][i][1] if frame_index else y
                if prev_y > throat >= y:
                    gate_pulse = 1.0
        if winner_frame is not None and frame_index == winner_frame and winner_index is not None:
            wx, wy = positions[winner_index]
            for colour, count in (((255, 210, 80), 34), ((255, 255, 255), 26), ((120, 200, 255), 22), ((255, 120, 140), 22)):
                confetti.burst(wx, Y(wy), colour, count, speed=(140, 360), size=(2.4, 4.2), arc=(-math.pi, 0), life=1.3)
            finish_flash = 1.0
        sparks.step(dt); confetti.step(dt)
        gate_pulse *= 0.86
        finish_flash *= 0.9

        # --- draw
        surface.fill(style.background)
        if finish_line:
            cell = 14
            lift = int(70 + 120 * finish_flash)
            for k in range(0, sim_w, cell):
                shade = style.structure if (k // cell) % 2 == 0 else fx.lighten(style.structure, lift)
                pygame.draw.rect(surface, shade, (k, fy - 4, cell, 8))
            if finish_flash > 0.05:
                band = pygame.Surface((sim_w, 24), pygame.SRCALPHA); band.fill((255, 255, 255, int(120 * finish_flash)))
                surface.blit(band, (0, fy - 12))
        if style.decoration != "none":
            decorate_pygame(surface, style, frame_index, sim_w, sim_h)
        if mech:
            render_mech.pg_under(surface, style, mech, frame_index, t, sim_h)
        for i, ball in enumerate(balls):
            if mech and hidden(mech, ball.name, frame_index):
                continue
            anim[i].draw_trail(surface, ball.radius, ball.color, alpha=48)
        # moving structure, each with a glow that says how fast it turns
        for sx, sy, half, omega, phase, *bias in style.rockers:
            angle = (bias[0] if bias else 0.0) + ROCK_AMPLITUDE * math.sin(omega * t + phase)
            dx, dy = math.cos(angle) * half, math.sin(angle) * half
            fx.capped_line(surface, (sx - dx, Y(sy - dy)), (sx + dx, Y(sy + dy)), style.thickness, structure_hi)
            fx.disc(surface, sx, Y(sy), style.thickness * 0.9, style.structure)
        for sx, sy, r, omega in style.drums:
            fx.soft(surface, sx, Y(sy), r * 1.18, (*structure_hi, int(min(80, 18 + abs(omega) * 10))), width=3)
            fx.disc(surface, sx, Y(sy), r, fx.lighten(style.structure, 22))
            for k in range(3):
                angle = omega * t + k * 2.094
                fx.capped_line(surface, (sx, Y(sy)), (sx + math.cos(angle) * r * 0.9, Y(sy + math.sin(angle) * r * 0.9)),
                               max(2, style.thickness // 2), structure_hi)
            fx.disc(surface, sx, Y(sy), style.thickness * 0.6, style.structure)
        for hx, hy, bore, depth, period, phase in style.traps:
            angle = trap_angle(t, period, phase)
            ex, ey = hx + math.cos(angle) * bore, hy + math.sin(angle) * bore
            # The door brightens while it is swinging and goes quiet while it
            # holds, so the release reads as a thing that happened rather than
            # a marble that suddenly started falling again. A halo was tried
            # first, as the spinners have: on a bar it traces the sweep, on a
            # door hinged at one end it is a circle round nothing.
            moving = abs(trap_angle(t + 1.0 / fps, period, phase) - angle) * fps
            fx.capped_line(surface, (hx, Y(hy)), (ex, Y(ey)), style.thickness,
                           fx.lighten(style.structure, 60 + int(min(70, moving * 45))))
            fx.disc(surface, hx, Y(hy), style.thickness * 0.8, style.structure)
        for sx, sy, half, omega, phase in style.spinners:
            angle = phase + omega * t
            dx, dy = math.cos(angle) * half, math.sin(angle) * half
            fx.soft(surface, sx, Y(sy), half * 1.04, (*structure_hi, int(min(70, 16 + abs(omega) * 12))), width=3)
            # a ghost of where the bar just was, so the spin has a direction
            ga = angle - omega * dt * 2.5
            gx, gy = math.cos(ga) * half, math.sin(ga) * half
            ghost = pygame.Surface((sim_w, sim_h), pygame.SRCALPHA)
            pygame.draw.line(ghost, (*structure_hi, 70), (sx - gx, Y(sy - gy)), (sx + gx, Y(sy + gy)), style.thickness)
            surface.blit(ghost, (0, 0))
            fx.capped_line(surface, (sx - dx, Y(sy - dy)), (sx + dx, Y(sy + dy)), style.thickness, structure_hi)
            fx.disc(surface, sx, Y(sy), style.thickness * 0.9, style.structure)
        for a, b, speed in style.belts:
            fx.capped_line(surface, (a[0], Y(a[1])), (b[0], Y(b[1])), style.thickness, fx.lighten(style.structure, 26))
            for mx, my, ux, uy in belt_marks(a, b, speed, t):
                # a chevron riding on the belt, pointing the way it runs
                tip = (mx + ux * 6, Y(my + uy * 6))
                nx, ny = -uy, ux
                back_a = (mx - ux * 3 + nx * 4, Y(my - uy * 3 + ny * 4))
                back_b = (mx - ux * 3 - nx * 4, Y(my - uy * 3 - ny * 4))
                pygame.draw.polygon(surface, fx.lighten(style.structure, 110), [tip, back_a, back_b])
        for mx, my, core, _soft, reach, _pull, polarity in magnets_at(style, mech, frame_index):
            # Same magnet as the PIL renderer, with the kit's usual moving-part
            # treatment: the field breathes so a viewer reads it as live before
            # a marble reaches it, the way a spinner's glow says how fast it
            # turns. The ring sits exactly where the force reaches.
            iy = Y(my)
            breath = 0.5 + 0.5 * math.sin(t * 2.2)
            fx.soft(surface, mx, iy, reach, (*structure_hi, int(24 + 20 * breath)), width=1)
            for px, py, ux, uy in magnet_marks(mx, my, reach, t, polarity=polarity):
                nx, ny = -uy, ux
                pygame.draw.polygon(surface, fx.lighten(style.structure, 78 + int(40 * breath)),
                                    [(px + ux * 17, Y(py + uy * 17)),
                                     (px - ux * 2 + nx * 4, Y(py - uy * 2 + ny * 4)),
                                     (px - ux * 2 - nx * 4, Y(py - uy * 2 - ny * 4))])
            pygame.draw.circle(surface, fx.lighten(style.structure, 110), (int(mx), int(iy)), int(core),
                               draw_top_left=True, draw_top_right=True)
            pygame.draw.circle(surface, fx.lighten(style.structure, 14), (int(mx), int(iy)), int(core),
                               draw_bottom_left=True, draw_bottom_right=True)
        for a, b in style.gates:
            col = fx.lighten(gate_col, int(120 * gate_pulse))
            fx.capped_line(surface, (a[0], Y(a[1])), (b[0], Y(b[1])), style.thickness, col)
            if gate_pulse > 0.05:
                fx.soft(surface, b[0], Y(b[1]), style.thickness * (1.5 + 2 * (1 - gate_pulse)), (255, 255, 255, int(120 * gate_pulse)), width=2)
        for a, b in segments:
            fx.capped_line(surface, (a[0], Y(a[1])), (b[0], Y(b[1])), style.thickness, style.structure)
        for cx, cy, r in style.circles:
            fx.disc(surface, cx, Y(cy), r, style.structure)
            fx.disc(surface, cx - r * 0.25, Y(cy) - r * 0.35, r * 0.22, fx.lighten(style.structure, 40))
        if mech:
            render_mech.pg_over(surface, style, mech, frame_index, sim_h, colours)
        for i, (ball, (x, y)) in enumerate(zip(balls, positions)):
            if mech and hidden(mech, ball.name, frame_index):
                continue
            anim[i].draw(surface, x, Y(y), ball.radius, ball.color)
            if winner_index == i and winner_frame is not None and frame_index >= winner_frame:
                fx.winner_rings(surface, x, Y(y), ball.radius, (frame_index - winner_frame) / fps)
        sparks.draw(surface); confetti.draw(surface)
        if mech:
            render_mech.pg_top(surface, style, mech, frame_index, sim_w, sim_h)
        if cap_surface is not None:
            fx.caption_in(surface, cap_surface, sim_w / 2, overlay[3] + cap_surface.get_height() / 2, frame_index, overlay[4], fps, rise=sim_h * 0.04)
        if ask_surface is not None and winner_frame is not None:
            fx.pop_in(surface, ask_surface, sim_w / 2, ask[3], frame_index - winner_frame, ask[4], fps)
        yield fx.to_bytes(surface)


def decorate_pygame(surface, style: Style, frame: int, w: int, h: int) -> None:
    """The seasonal particles, drawn with pygame; same seed, same positions."""

    rng = random.Random(style.seed * 31 + 7)
    kind = style.decoration
    count = {"snow": 70, "embers": 40, "sparks": 55, "drops": 60}.get(kind, 0)
    t = frame / 30.0
    for _ in range(count):
        x0 = rng.uniform(0, w)
        y0 = rng.uniform(0, h)
        speed = rng.uniform(22, 60)
        size = rng.uniform(1.2, 3.2)
        phase = rng.uniform(0, 6.283)
        if kind == "snow":
            fx.soft(surface, (x0 + math.sin(t * 0.8 + phase) * 12) % w, (y0 + t * speed) % h, size, (226, 232, 244, 220))
        elif kind == "embers":
            glow = int(150 + 100 * (0.5 + 0.5 * math.sin(t * 5 + phase)))
            fx.soft(surface, (x0 + math.sin(t * 1.4 + phase) * 8) % w, (y0 - t * speed) % h, size * 1.6, (255, glow, 40, 160))
        elif kind == "sparks":
            twinkle = 0.5 + 0.5 * math.sin(t * 6 + phase)
            if twinkle > 0.45:
                fx.soft(surface, x0, y0, size * twinkle, (240, 205, 90, 230))
        elif kind == "drops":
            y = (y0 + t * speed * 3) % h
            fx.capped_line(surface, (x0, y), (x0, y + size * 4), 1, (150, 205, 240))
