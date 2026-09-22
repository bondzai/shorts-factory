"""The juice: motion that belongs to objects, drawn with pygame.

Shared by the arena and the race so a marble and a fighter squash, flash,
trail and burst the same way. Nothing here touches physics — every helper
takes a position the simulation already produced and draws around it.

pygame runs headless (SDL's dummy driver); text is drawn by PIL with the
brand font and handed over as a surface, because pygame's font module
cannot pick a face out of a .ttc and the fonts must match the PIL renderer.

One rule learned the hard way: gfxdraw writes RGBA straight into a
per-pixel-alpha surface without compositing, so a translucent glow drawn
that way is a black blob. Everything translucent goes through `soft`, which
draws on its own small surface and blits — the blit is what blends.
"""

from __future__ import annotations

import math
import os
import random
from typing import Any

from PIL import Image, ImageDraw

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

import pygame  # noqa: E402
import pygame.gfxdraw  # noqa: E402

_READY = False


def init() -> None:
    global _READY
    if not _READY:
        pygame.init()
        _READY = True


def lighten(colour, by: int):
    return tuple(min(255, c + by) for c in colour)


def darken(colour, factor: float):
    return tuple(int(c * factor) for c in colour)


# --- drawing primitives ---------------------------------------------------------

def soft(surface, x, y, r, rgba, width: int = 0) -> None:
    """A translucent disc (or ring when width > 0) that actually blends."""
    r = max(1, int(r))
    tmp = pygame.Surface((r * 2 + 4, r * 2 + 4), pygame.SRCALPHA)
    if width:
        pygame.draw.circle(tmp, rgba, (r + 2, r + 2), r, width)
    else:
        pygame.gfxdraw.filled_circle(tmp, r + 2, r + 2, r, rgba)
        pygame.gfxdraw.aacircle(tmp, r + 2, r + 2, r, rgba)
    surface.blit(tmp, (int(x) - r - 2, int(y) - r - 2))


def disc(surface, x, y, r, colour) -> None:
    pygame.gfxdraw.filled_circle(surface, int(x), int(y), max(1, int(r)), colour)
    pygame.gfxdraw.aacircle(surface, int(x), int(y), max(1, int(r)), colour)


def squashed_disc(surface, x, y, r, amount: float, direction, colour) -> None:
    """A disc squashed by `amount` (0..1) along `direction`: shorter along it,
    longer across it, like a ball meeting a wall."""
    if amount < 0.02:
        disc(surface, x, y, r, colour)
        return
    a, b = r * (1 - 0.28 * amount), r * (1 + 0.28 * amount)
    ang = math.degrees(math.atan2(direction[1], direction[0]))
    size = int(r * 2.6)
    tmp = pygame.Surface((size, size), pygame.SRCALPHA)
    pygame.draw.ellipse(tmp, colour, (size / 2 - a, size / 2 - b, a * 2, b * 2))
    rot = pygame.transform.rotate(tmp, -ang)
    surface.blit(rot, (x - rot.get_width() / 2, y - rot.get_height() / 2))


def capped_line(surface, a, b, width: int, colour) -> None:
    """A line with round ends, which is what a pymunk segment with a radius is."""
    pygame.draw.line(surface, colour, a, b, max(1, int(width)))
    if width >= 3:
        disc(surface, a[0], a[1], width / 2, colour)
        disc(surface, b[0], b[1], width / 2, colour)


def text_surface(text: str, size: int, max_width: float, colour=(250, 250, 255), outline=True):
    """Text by PIL with the brand font, as a pygame RGBA surface."""
    from ..brand import _font

    probe = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    while True:
        font = _font(size)
        width = probe.textlength(text, font=font)
        if width <= max_width or size <= 12:
            break
        size -= 2
    pad = max(4, size // 6)
    image = Image.new("RGBA", (int(width) + pad * 4, int(size * 1.4) + pad * 2), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    if outline:
        draw.text((pad * 2, pad), text, font=font, fill=(*colour, 255),
                  stroke_width=max(2, size // 12), stroke_fill=(0, 0, 0, 230))
    else:
        draw.text((pad * 2, pad), text, font=font, fill=(*colour, 255))
    return pygame.image.frombytes(image.tobytes(), image.size, "RGBA")


# --- animated state -------------------------------------------------------------

class Ball:
    """Per-object animation state: squash, flash, trail, spin. Feed it one
    position per frame and one `hit` per impact; draw what it says."""

    def __init__(self, trail_len: int = 7):
        self.squash = 0.0
        self.direction = (1.0, 0.0)
        self.flash = 0
        self.spin = 0.0
        self.trail: list[tuple[float, float]] = []
        self.trail_len = trail_len

    def hit(self, strength: float, direction=(1.0, 0.0)) -> None:
        self.squash = max(self.squash, min(1.0, 0.45 + strength * 0.6))
        self.direction = direction
        self.flash = max(self.flash, 2 + int(strength * 2))

    def step(self, x: float, y: float, r: float, alive: bool = True) -> None:
        self.squash *= 0.72
        self.flash = max(0, self.flash - 1)
        if alive:
            self.trail.append((x, y))
            if len(self.trail) > self.trail_len:
                self.trail.pop(0)
            if len(self.trail) > 1:
                px, py = self.trail[-2]
                self.spin += math.hypot(x - px, y - py) / max(r, 1.0)
        else:
            self.trail = self.trail[1:]

    def draw_trail(self, surface, r: float, colour, alpha: int = 40) -> None:
        for k, (tx, ty) in enumerate(self.trail[:-1]):
            t = (k + 1) / len(self.trail)
            soft(surface, tx, ty, r * (0.35 + 0.5 * t), (*colour, int(alpha * t)))

    def draw(self, surface, x: float, y: float, r: float, colour, glow: bool = True) -> None:
        if glow:
            for k in range(3, 0, -1):
                soft(surface, x, y, r * (1 + k * 0.14), (*colour, 10 * k))
        squashed_disc(surface, x, y, r, self.squash, self.direction, colour)
        shade = darken(colour, 0.55)
        disc(surface, x + r * 0.18, y + r * 0.22, r * 0.78 * (1 - 0.2 * self.squash), shade)
        disc(surface, x, y, r * 0.66 * (1 - 0.2 * self.squash), colour)
        # a rolling highlight: it orbits with the distance travelled, so a
        # marble reads as rolling rather than sliding
        hx = x + math.cos(self.spin * 0.9 - 2.3) * r * 0.36
        hy = y + math.sin(self.spin * 0.9 - 2.3) * r * 0.36
        disc(surface, hx, hy, r * 0.2, (255, 255, 255))
        soft(surface, hx + r * 0.12, hy + r * 0.1, r * 0.1, (255, 255, 255, 110))
        if self.flash:
            soft(surface, x, y, r, (255, 255, 255, min(255, 90 * self.flash)))


class Particles:
    """Sparks, embers, confetti: position, velocity, life, colour, size."""

    def __init__(self, rng: random.Random, gravity: float = 180.0, decay: float = 1.6):
        self.rng, self.gravity, self.decay = rng, gravity, decay
        self.items: list[list[float]] = []

    def burst(self, x, y, colour, count: int, speed=(40.0, 160.0), size=(1.5, 3.5), arc=(0.0, 2 * math.pi), life=1.0) -> None:
        for _ in range(count):
            a = self.rng.uniform(*arc)
            sp = self.rng.uniform(*speed)
            self.items.append([x, y, math.cos(a) * sp, math.sin(a) * sp, life, *colour, self.rng.uniform(*size)])

    def step(self, dt: float) -> None:
        for p in self.items:
            p[0] += p[2] * dt
            p[1] += p[3] * dt
            p[3] += self.gravity * dt
            p[2] *= 0.98
            p[4] -= dt * self.decay
        self.items = [p for p in self.items if p[4] > 0]

    def draw(self, surface) -> None:
        for px, py, _, _, life, cr, cg, cb, size in self.items:
            soft(surface, px, py, size * min(1.0, life * 1.5), (int(cr), int(cg), int(cb), int(230 * min(1.0, life))))


class Ripples:
    def __init__(self, span: float = 0.35, radius=(6, 40)):
        self.items: list[list[float]] = []
        self.span, self.radius = span, radius

    def add(self, x, y) -> None:
        self.items.append([x, y, 0.0])

    def step(self, dt: float) -> None:
        for r in self.items:
            r[2] += dt
        self.items = [r for r in self.items if r[2] < self.span]

    def draw(self, surface, colour=(200, 210, 255)) -> None:
        for x, y, age in self.items:
            t = age / self.span
            soft(surface, x, y, self.radius[0] + t * (self.radius[1] - self.radius[0]), (*colour, int(180 * (1 - t))), width=2)


class Shake:
    def __init__(self, rng: random.Random, amount: float):
        self.rng, self.amount, self.level = rng, amount, 0.0

    def kick(self, level: float = 1.0) -> None:
        self.level = max(self.level, level)

    def step(self) -> tuple[int, int]:
        self.level *= 0.82
        return (int(self.rng.uniform(-1, 1) * self.level * self.amount), int(self.rng.uniform(-1, 1) * self.level * self.amount))


def winner_rings(surface, x, y, r, age_s: float, colour=(255, 240, 180)) -> None:
    for k in range(3):
        t = (age_s * 1.2 + k * 0.33) % 1.0
        soft(surface, x, y, r * (1.2 + t * 1.6), (*colour, int(220 * (1 - t))), width=3)


def caption_in(surface, text_surf, cx: float, y: float, frame: int, last: int, fps: int, rise: float = 0.0) -> None:
    """Slide up and settle, then fade out over the last quarter second."""
    if frame >= last:
        return
    t = min(1.0, frame / max(1.0, 0.35 * fps))
    ease = 1 - (1 - t) ** 3
    out = max(0.0, min(1.0, (last - frame) / max(1.0, 0.25 * fps)))
    cap = text_surf.copy()
    cap.set_alpha(int(255 * min(ease, out)))
    surface.blit(cap, (int(cx - cap.get_width() / 2), int(y + (1 - ease) * rise) - cap.get_height() // 2))


def pop_in(surface, text_surf, cx: float, y: float, age: int, span: int, fps: int) -> None:
    """Scale in with a small overshoot, hold for `span` frames."""
    if not 0 <= age < span:
        return
    t = min(1.0, age / max(1.0, 0.25 * fps))
    sc = 0.6 + 0.4 * (1 - (1 - t) ** 2) + (0.08 * (1 - t) if t < 1 else 0)
    scaled = pygame.transform.smoothscale(text_surf, (max(1, int(text_surf.get_width() * sc)), max(1, int(text_surf.get_height() * sc))))
    surface.blit(scaled, (int(cx - scaled.get_width() / 2), int(y) + (text_surf.get_height() - scaled.get_height()) // 2))


def to_bytes(surface) -> bytes:
    return pygame.image.tobytes(surface, "RGB")


def engine() -> str:
    """Which frame renderer a physics clip uses: "pil" (the original) or
    "pygame" (this module's motion). Read from config so a clip made either
    way can be made again the same way."""
    from .. import settings

    return str(settings.load().raw.get("render", {}).get("engine", "pil")).strip().lower() or "pil"
