"""Ball battle: an arena, four fighters, health bars, last one standing.

The marble race asks "which one gets out first?"; this asks "which one is
left?". Same physics engine (pymunk) and the same honesty rule — the result
is whatever the seed's collisions produce — but the framing is a game: each
ball has a health bar at the top of the frame, every hit takes health from
both, a ball at zero pops out of the arena, and the clip ends a moment after
one remains.

Drawn with pygame (headless, SDL's dummy driver) rather than PIL, because a
game wants what a game engine draws well: alpha glows, anti-aliased discs,
rounded bars, a burst on elimination.

What makes it watchable and fair at once:

  Arcade speed   No gravity, elastic walls, and every ball is re-set to its
                 target speed each step, so the arena never runs down. The
                 direction is physics; only the magnitude is arcade.

  Rage           Under a third of health a ball moves faster and hits
                 harder. This is the twist that makes the viewer's pick
                 matter to the end: the ball that is losing is the most
                 dangerous ball on the floor, and comebacks happen.

  Two-way hits   Both balls in a collision lose health, scaled by the
                 impulse. The heavier ball loses less, so size is a real
                 stat the viewer can see and bet on.

Nothing here is rigged toward any colour; the tests measure that.
"""

from __future__ import annotations

import math
import os
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

import pymunk
from PIL import Image, ImageDraw

from .. import audio, render, settings
from . import fx
from .base import GeneratedClip, register

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

SUBSTEPS = 3
BALL = 1
WALL = 2
FIGHTERS = 4
MAX_HP = 100.0
SPEED = 0.62          # of frame width per second
RAGE_BELOW = 0.34     # of MAX_HP
RAGE_SPEED = 1.28
RAGE_DAMAGE = 1.5
# Damage per unit of impulse, tuned so four fighters at full speed last
# 14-22 s: fewer fights than a heat, but each one is on the bars.
DAMAGE_PER_IMPULSE = 0.0058
MIN_HIT, MAX_HIT = 2.0, 14.0
HIT_REFRACTORY_S = 0.12  # a pair cannot take damage twice in this window
POST_WIN_S = 1.4
POP_FRAMES = 14
ARENA_SEGMENTS = 56

# Fighters are named by colour, because that is what the viewer can say.
PALETTE = [
    ("red", (232, 70, 70)), ("blue", (72, 140, 240)), ("amber", (240, 176, 44)),
    ("green", (86, 200, 110)), ("violet", (170, 100, 240)), ("teal", (60, 200, 200)),
    ("pink", (240, 100, 170)), ("white", (236, 236, 244)),
]
BACKDROPS = [(14, 12, 22), (10, 14, 20), (18, 12, 16), (12, 16, 14)]


@dataclass
class Fighter:
    name: str
    colour: tuple[int, int, int]
    radius: float
    body: pymunk.Body
    hp: float = MAX_HP
    alive: bool = True
    died_frame: int | None = None
    hits_taken: int = 0
    hits_dealt: int = 0


@dataclass
class Style:
    seed: int
    backdrop: tuple[int, int, int] = BACKDROPS[0]
    arena_centre: tuple[float, float] = (0.0, 0.0)
    arena_radius: float = 0.0
    fighters: list[Fighter] = field(default_factory=list)
    # What happened when, for the animation: ("hit", frame, i, j, strength, x, y),
    # ("wall", frame, i, -1, strength, x, y), ("ko", frame, i, -1, 1, x, y).
    events: list[tuple] = field(default_factory=list)


def _lineup(rng: random.Random, n: int) -> list[tuple[str, tuple[int, int, int]]]:
    return rng.sample(PALETTE, n)


class BallBattle:
    name = "battle"
    variants = ["ball_battle"]
    ready = True
    blurb = (
        "Four balls named by colour fight in a round arena with health bars at the top; "
        "every hit costs both of them health, a ball at zero pops out, and the last one "
        "standing wins. A losing ball goes into rage — faster and harder — so comebacks "
        "happen. Drawn with pygame. Facts carry the winner and the elimination order."
    )

    def generate(self, *, seed: int, variant: str, params: dict[str, Any], work_dir: Path) -> GeneratedClip:
        if variant not in self.variants:
            raise ValueError(f"{self.name}: unknown variant {variant!r}; have {self.variants}")
        cfg = settings.load().render
        out_w, out_h = int(cfg["width"]), int(cfg["height"])
        scale = float(cfg["render_scale"])
        sim_w, sim_h = int(out_w * scale), int(out_h * scale)
        fps = int(cfg["fps"])
        max_seconds = float(params.get("seconds", cfg.get("max_seconds", 22)))
        fighters_n = int(params.get("fighters", FIGHTERS))

        style = Style(seed=seed)
        rng = random.Random(seed)
        style.backdrop = BACKDROPS[rng.randrange(len(BACKDROPS))]
        if params.get("background"):
            from .physics import parse_hex
            style.backdrop = parse_hex(params["background"])

        sim = self._simulate(seed, sim_w, sim_h, fps, max_seconds, style, fighters_n)
        states, impacts, winner, winner_frame, eliminated, timed_out = sim
        duration_s = len(states) / fps

        hook_text = params.get("hook_text") or self._default_hook(seed)
        work_dir.mkdir(parents=True, exist_ok=True)
        wav = audio.render_wav(impacts, duration_s, work_dir / "audio.wav")
        silent = render.encode_frames(
            self._frames(states, style, sim_w, sim_h, fps, hook_text, winner, winner_frame),
            out_path=work_dir / "video.mp4", src_size=(sim_w, sim_h), out_size=(out_w, out_h), fps=fps,
        )
        final = render.mux(silent, wav, work_dir / "clip.mp4")

        names = [f.name for f in style.fighters]
        order = [n for n, _ in eliminated]
        finishes = {n: round(fr / fps, 2) for n, fr in eliminated}
        if winner:
            finishes[winner] = round((winner_frame or len(states)) / fps, 2)
        description = (
            f"{len(names)} balls — {', '.join(names)} — bounce around a round arena with a health "
            f"bar each at the top of the frame; every collision costs both balls health, and a ball "
            f"at zero pops out. {len(order)} are knocked out over {duration_s:.1f} seconds"
            + (f" ({', '.join(order)} in that order)" if order else "")
            + (f"; {winner} is the last one standing" if winner and not timed_out else
               f"; time runs out with {winner} holding the most health" if winner else "")
            + f". {len(impacts)} hits are heard. The caption reads '{hook_text}' for the opening seconds."
        )
        return GeneratedClip(
            video_path=final, duration_s=duration_s, description=description,
            facts={
                "variant": variant, "seed": seed, "fighters": names, "winner": winner,
                "winner_frame": winner_frame, "finishes": finishes, "eliminated": order,
                "timed_out": timed_out, "impacts": len(impacts), "hook_text": hook_text,
                "backdrop": "#%02x%02x%02x" % style.backdrop, "stage": "arena",
                "hits": {f.name: {"taken": f.hits_taken, "dealt": f.hits_dealt} for f in style.fighters},
            },
        )

    # --- simulation --------------------------------------------------------------

    def _simulate(self, seed: int, sim_w: int, sim_h: int, fps: int, max_seconds: float, style: Style, n: int):
        rng = random.Random(seed ^ 0xBA77)
        space = pymunk.Space()
        space.gravity = (0.0, 0.0)
        cx, cy, R = sim_w / 2, sim_h * 0.55, sim_w * 0.46
        style.arena_centre, style.arena_radius = (cx, cy), R
        for i in range(ARENA_SEGMENTS):
            a0 = 2 * math.pi * i / ARENA_SEGMENTS
            a1 = 2 * math.pi * (i + 1) / ARENA_SEGMENTS
            seg = pymunk.Segment(space.static_body, (cx + R * math.cos(a0), cy + R * math.sin(a0)),
                                 (cx + R * math.cos(a1), cy + R * math.sin(a1)), 3.0)
            seg.elasticity, seg.friction, seg.collision_type = 1.0, 0.0, WALL
            space.add(seg)

        speed = sim_w * SPEED
        fighters: list[Fighter] = []
        for k, (name, colour) in enumerate(_lineup(rng, n)):
            radius = sim_w * rng.uniform(0.060, 0.084)
            mass = radius * radius / 900.0
            body = pymunk.Body(mass, pymunk.moment_for_circle(mass, 0, radius))
            ang = 2 * math.pi * k / n + rng.uniform(-0.3, 0.3)
            body.position = (cx + (R - radius * 2.2) * 0.62 * math.cos(ang), cy + (R - radius * 2.2) * 0.62 * math.sin(ang))
            direction = rng.uniform(0, 2 * math.pi)
            body.velocity = (speed * math.cos(direction), speed * math.sin(direction))
            shape = pymunk.Circle(body, radius)
            shape.elasticity, shape.friction, shape.collision_type = 1.0, 0.0, BALL
            body.fighter_index = k  # type: ignore[attr-defined]
            space.add(body, shape)
            fighters.append(Fighter(name=name, colour=colour, radius=radius, body=body))
        style.fighters = fighters

        impacts: list[audio.Impact] = []
        last_pair_hit: dict[tuple[int, int], float] = {}
        clock = {"t": 0.0}

        def on_ball(arbiter: pymunk.Arbiter, _space, _data) -> None:
            a, b = arbiter.shapes
            i, j = a.body.fighter_index, b.body.fighter_index  # type: ignore[attr-defined]
            fa, fb = fighters[i], fighters[j]
            if not (fa.alive and fb.alive):
                return
            key = (min(i, j), max(i, j))
            if clock["t"] - last_pair_hit.get(key, -1.0) < HIT_REFRACTORY_S:
                return
            last_pair_hit[key] = clock["t"]
            impulse = arbiter.total_impulse.length
            base = max(MIN_HIT, min(MAX_HIT, impulse * DAMAGE_PER_IMPULSE))
            # The heavier ball shrugs off more; rage hits harder.
            for me, other in ((fa, fb), (fb, fa)):
                dealt = base * (RAGE_DAMAGE if other.hp < MAX_HP * RAGE_BELOW else 1.0) * (other.body.mass / me.body.mass) ** 0.5
                me.hp -= dealt  # may go below zero; the frame loop decides who falls
                me.hits_taken += 1
                other.hits_dealt += 1
            pt = arbiter.contact_point_set.points[0].point_a if arbiter.contact_point_set.points else pymunk.Vec2d(cx, cy)
            strength = min(1.0, 0.35 + base / MAX_HIT * 0.65)
            impacts.append(audio.Impact(t=clock["t"], strength=strength, index=i, pan=(pt.x / sim_w) * 2 - 1))
            style.events.append(("hit", int(clock["t"] * fps), i, j, strength, pt.x, pt.y))

        def on_wall(arbiter: pymunk.Arbiter, _space, _data) -> None:
            a, b = arbiter.shapes
            shape = a if a.collision_type == BALL else b
            i = shape.body.fighter_index  # type: ignore[attr-defined]
            if fighters[i].alive:
                pt = arbiter.contact_point_set.points[0].point_a if arbiter.contact_point_set.points else shape.body.position
                style.events.append(("wall", int(clock["t"] * fps), i, -1, 0.3, pt.x, pt.y))
                if rng.random() < 0.5:
                    impacts.append(audio.Impact(t=clock["t"], strength=0.18, index=i + 4,
                                                pan=(shape.body.position.x / sim_w) * 2 - 1))

        space.on_collision(BALL, BALL, post_solve=on_ball)
        space.on_collision(BALL, WALL, post_solve=on_wall)

        dt = 1.0 / (fps * SUBSTEPS)
        states: list[list[tuple[float, float, float, float, bool, int | None]]] = []
        eliminated: list[tuple[str, int]] = []
        winner: str | None = None
        winner_frame: int | None = None
        timed_out = False
        frames_cap = int(max_seconds * fps)
        for frame in range(frames_cap):
            for _ in range(SUBSTEPS):
                clock["t"] = frame / fps
                space.step(dt)
                for f in fighters:
                    if not f.alive:
                        continue
                    target = speed * (RAGE_SPEED if f.hp < MAX_HP * RAGE_BELOW else 1.0)
                    v = f.body.velocity
                    if v.length < 1e-3:
                        ang = rng.uniform(0, 2 * math.pi)
                        f.body.velocity = (target * math.cos(ang), target * math.sin(ang))
                    else:
                        f.body.velocity = v * (target / v.length)
            falling = sorted((f for f in fighters if f.alive and f.hp <= 0.0), key=lambda f: f.hp)
            standing = [f for f in fighters if f.alive]
            if falling and len(falling) == len(standing):
                # A double knockout on the last exchange: the ball that took
                # less of it stays up with a sliver, so there is always a
                # last one standing and it is the one that earned it.
                survivor = falling.pop()
                survivor.hp = 1.0
            for f in falling:
                f.alive, f.died_frame, f.hp = False, frame, 0.0
                space.remove(f.body, *f.body.shapes)
                eliminated.append((f.name, frame))
                impacts.append(audio.Impact(t=frame / fps, strength=1.0, index=5, pan=(f.body.position.x / sim_w) * 2 - 1))
                style.events.append(("ko", frame, fighters.index(f), -1, 1.0, f.body.position.x, f.body.position.y))
            states.append([(f.body.position.x, f.body.position.y, f.radius, max(0.0, f.hp), f.alive, f.died_frame) for f in fighters])
            alive = [f for f in fighters if f.alive]
            if winner_frame is None and len(alive) <= 1:
                winner = alive[0].name if alive else None
                winner_frame = frame
            if winner_frame is not None and frame >= winner_frame + int(fps * POST_WIN_S):
                break
        else:
            timed_out = winner_frame is None
            if timed_out:
                best = max((f for f in fighters if f.alive), key=lambda f: (f.hp, -f.hits_taken))
                winner, winner_frame = best.name, len(states) - 1
        return states, impacts, winner, winner_frame, eliminated, timed_out

    # --- words ----------------------------------------------------------------------

    def _default_hook(self, seed: int) -> str:
        cfg = settings.load().raw.get("overlay", {})
        bank = [c.strip() for c in str(cfg.get("ball_battle") or "PICK A FIGHTER").split("|") if c.strip()]
        return bank[random.Random(seed).randrange(len(bank))] if bank else ""

    # --- drawing ----------------------------------------------------------------------

    def _frames(self, states, style: Style, sim_w: int, sim_h: int, fps: int, hook_text: str,
                winner: str | None, winner_frame: int | None) -> Iterator[bytes]:
        """Every object has motion of its own, not just position.

        Ball        squash along its heading on a hit, a white flash, a fading
                    trail, a rolling highlight so it reads as spinning, embers
                    when raging.
        Bar         drains smoothly with a pale ghost that lags behind (what a
                    fighting game does), and jolts when its ball is hit.
        Arena       a ripple where a ball meets the wall, a shake on a KO.
        KO          a burst of particles in the ball's colour.
        Words       the caption slides up and settles; the ask pops in.
        Winner      a widening ring and a shower of confetti.
        """
        import pygame
        import pygame.gfxdraw

        fx.init()
        cfg = settings.load().raw.get("overlay", {})
        caption_frames = int(float(cfg.get("seconds", 0)) * fps)
        ask_text = str(cfg.get("cta") or "").strip()
        ask_frames = int(float(cfg.get("cta_seconds", 0) or 0) * fps)
        caption = fx.text_surface(hook_text, int(sim_w * float(cfg.get("size", 0.1))), sim_w * 0.9) if hook_text else None
        ask = fx.text_surface(ask_text, int(sim_w * float(cfg.get("size", 0.1)) * 0.8), sim_w * 0.9) if ask_text and ask_frames else None
        labels = {f.name: fx.text_surface(f.name.upper(), int(sim_w * 0.034), sim_w * 0.3) for f in style.fighters}
        rng = random.Random(style.seed ^ 0xA11)

        n = len(style.fighters)
        cx, cy = style.arena_centre
        R = int(style.arena_radius)
        arena_fill = tuple(min(255, c + 10) for c in style.backdrop)
        winner_index = next((i for i, f in enumerate(style.fighters) if f.name == winner), None) if winner else None
        by_frame: dict[int, list[tuple]] = {}
        for ev in style.events:
            by_frame.setdefault(ev[1], []).append(ev)

        # Per-object animation state.
        disp_hp = [MAX_HP] * n          # what the bar shows; eases toward the real value
        ghost_hp = [MAX_HP] * n         # the pale bar that lags, showing damage just taken
        bar_jolt = [0.0] * n
        squash = [0.0] * n              # 0..1, decays; 1 = just hit
        squash_dir = [(1.0, 0.0)] * n
        flash = [0] * n
        spin = [0.0] * n
        trails: list[list[tuple[float, float]]] = [[] for _ in range(n)]
        particles: list[list[float]] = []   # x, y, vx, vy, life, r, g, b, size
        ripples: list[list[float]] = []     # x, y, age
        shake = 0.0
        confetti: list[list[float]] = []

        soft, ellipse = fx.soft, fx.squashed_disc

        surface = pygame.Surface((sim_w, sim_h))
        for frame_index, state in enumerate(states):
            # --- advance animation state from this frame's events ---------------------
            for ev in by_frame.get(frame_index, []):
                kind, _, i, j, strength, ex, ey = ev
                if kind == "hit":
                    for k in (i, j):
                        squash[k] = 1.0
                        px, py = state[k][0] - ex, state[k][1] - ey
                        norm = math.hypot(px, py) or 1.0
                        squash_dir[k] = (px / norm, py / norm)
                        flash[k] = 3
                        bar_jolt[k] = 1.0
                    for _ in range(int(3 + strength * 6)):
                        a = rng.uniform(0, 2 * math.pi); sp = rng.uniform(40, 160) * strength
                        col = style.fighters[i if rng.random() < 0.5 else j].colour
                        particles.append([ex, ey, math.cos(a) * sp, math.sin(a) * sp, 1.0, *col, rng.uniform(1.5, 3.5)])
                elif kind == "wall":
                    ripples.append([ex, ey, 0.0])
                elif kind == "ko":
                    shake = 1.0
                    col = style.fighters[i].colour
                    for _ in range(28):
                        a = rng.uniform(0, 2 * math.pi); sp = rng.uniform(90, 260)
                        particles.append([ex, ey, math.cos(a) * sp, math.sin(a) * sp, 1.0, *col, rng.uniform(2, 5)])
            if winner_frame is not None and frame_index == winner_frame and winner_index is not None:
                wx, wy = state[winner_index][0], state[winner_index][1]
                for _ in range(70):
                    a = rng.uniform(-math.pi, 0); sp = rng.uniform(120, 320)
                    col = rng.choice(PALETTE)[1]
                    confetti.append([wx, wy, math.cos(a) * sp, math.sin(a) * sp, 1.0, *col, rng.uniform(2, 4)])

            dt = 1.0 / fps
            for i in range(n):
                real = state[i][3]
                disp_hp[i] += (real - disp_hp[i]) * 0.35
                if ghost_hp[i] > disp_hp[i]:
                    ghost_hp[i] = max(disp_hp[i], ghost_hp[i] - MAX_HP * 0.9 * dt)
                else:
                    ghost_hp[i] = disp_hp[i]
                squash[i] *= 0.72
                bar_jolt[i] *= 0.7
                flash[i] = max(0, flash[i] - 1)
                if state[i][4]:
                    x, y, r = state[i][0], state[i][1], state[i][2]
                    trails[i].append((x, y))
                    if len(trails[i]) > 7:
                        trails[i].pop(0)
                    prev = trails[i][-2] if len(trails[i]) > 1 else (x, y)
                    spin[i] += math.hypot(x - prev[0], y - prev[1]) / max(r, 1.0)
                else:
                    trails[i] = trails[i][1:]
            for pset, grav in ((particles, 180.0), (confetti, 260.0)):
                for prt in pset:
                    prt[0] += prt[2] * dt; prt[1] += prt[3] * dt
                    prt[3] += grav * dt
                    prt[2] *= 0.98
                    prt[4] -= dt * (1.6 if pset is particles else 0.7)
                pset[:] = [prt for prt in pset if prt[4] > 0]
            for rp in ripples:
                rp[2] += dt
            ripples[:] = [rp for rp in ripples if rp[2] < 0.35]
            shake *= 0.82
            ox = rng.uniform(-1, 1) * shake * sim_w * 0.012
            oy = rng.uniform(-1, 1) * shake * sim_w * 0.012

            # --- draw ----------------------------------------------------------------------
            surface.fill(style.backdrop)
            world = pygame.Surface((sim_w, sim_h), pygame.SRCALPHA)
            pygame.gfxdraw.filled_circle(world, int(cx), int(cy), R, arena_fill)
            glow_a = 24 + int(10 * math.sin(frame_index / fps * 2.0))
            for k in range(5, 0, -1):
                soft(world, cx, cy, R + k * 2, (120, 140, 255, max(0, glow_a - k * 3)), width=2)
            pygame.gfxdraw.aacircle(world, int(cx), int(cy), R, (150, 160, 220))
            pygame.gfxdraw.aacircle(world, int(cx), int(cy), R - 1, (150, 160, 220))
            for rx, ry, age in ripples:
                t = age / 0.35
                rr = int(6 + t * 34)
                soft(world, rx, ry, rr, (200, 210, 255, int(180 * (1 - t))), width=2)

            for i, f in enumerate(style.fighters):
                x, y, r, hp, alive, died = state[i]
                raging = alive and hp < MAX_HP * RAGE_BELOW
                # trail
                for k, (tx, ty) in enumerate(trails[i][:-1]):
                    t = (k + 1) / len(trails[i])
                    soft(world, tx, ty, r * (0.35 + 0.5 * t), (*f.colour, int(40 * t)))
                if not alive:
                    continue
                # halo (breathes; hotter when raging)
                hc = (255, 110, 70) if raging else f.colour
                pulse = 1.0 + (0.18 * math.sin(frame_index * 0.5) if raging else 0.05 * math.sin(frame_index * 0.15))
                for k in range(4, 0, -1):
                    soft(world, x, y, r * (1 + k * 0.16) * pulse, (*hc, 12 * k + (18 if raging else 0)))
                if raging and frame_index % 2 == 0:
                    a = rng.uniform(0, 2 * math.pi)
                    particles.append([x + math.cos(a) * r, y + math.sin(a) * r, math.cos(a) * 30, -rng.uniform(40, 90), 0.5, 255, 150, 60, 2.0])
                # body, squashed along its heading on a hit
                ellipse(world, x, y, r, squash[i], squash_dir[i], f.colour)
                shade = tuple(int(c * 0.55) for c in f.colour)
                pygame.gfxdraw.filled_circle(world, int(x + r * 0.18), int(y + r * 0.22), int(r * 0.78 * (1 - 0.2 * squash[i])), shade)
                pygame.gfxdraw.filled_circle(world, int(x), int(y), int(r * 0.66 * (1 - 0.2 * squash[i])), f.colour)
                # rolling highlight: a bright spot and a darker band that orbit with the spin
                hx, hy = x + math.cos(spin[i] * 0.9 - 2.3) * r * 0.36, y + math.sin(spin[i] * 0.9 - 2.3) * r * 0.36
                pygame.gfxdraw.filled_circle(world, int(hx), int(hy), int(r * 0.2), (255, 255, 255))
                soft(world, hx + r * 0.12, hy + r * 0.1, r * 0.1, (255, 255, 255, 110))
                if flash[i]:
                    soft(world, x, y, r, (255, 255, 255, min(255, 90 * flash[i])))
                if winner_index == i and winner_frame is not None and frame_index >= winner_frame:
                    age = (frame_index - winner_frame) / fps
                    for k in range(3):
                        t = (age * 1.2 + k * 0.33) % 1.0
                        soft(world, x, y, r * (1.2 + t * 1.6), (255, 240, 180, int(220 * (1 - t))), width=3)

            for prt in particles + confetti:
                px, py, _, _, life, cr, cg, cb, size = prt
                soft(world, px, py, size * min(1.0, life * 1.5), (int(cr), int(cg), int(cb), int(230 * min(1.0, life))))

            surface.blit(world, (int(ox), int(oy)))

            # health bars, drawn on the still frame (the UI does not shake, the ball's row jolts)
            top = sim_h * 0.05
            row_h = sim_h * 0.036
            for i, f in enumerate(style.fighters):
                x, y, r, hp, alive, died = state[i]
                jx = int(bar_jolt[i] * sim_w * 0.012 * math.sin(frame_index * 2.1))
                ry = int(top + i * row_h * 1.25)
                bar_x, bar_w, bar_h = int(sim_w * 0.30) + jx, int(sim_w * 0.62), int(row_h * 0.62)
                pygame.draw.rect(surface, (34, 34, 48), (bar_x, ry, bar_w, bar_h), border_radius=6)
                if alive or (died is not None and frame_index - died < POP_FRAMES):
                    gfrac = max(0.0, ghost_hp[i] / MAX_HP)
                    if gfrac > 0:
                        pygame.draw.rect(surface, (236, 226, 210), (bar_x, ry, max(6, int(bar_w * gfrac)), bar_h), border_radius=6)
                    frac = max(0.0, disp_hp[i] / MAX_HP)
                    raging = hp < MAX_HP * RAGE_BELOW
                    col = (255, 90, 60) if raging else f.colour
                    if frac > 0:
                        pygame.draw.rect(surface, col, (bar_x, ry, max(6, int(bar_w * frac)), bar_h), border_radius=6)
                        # a moving sheen so a full bar still has life in it
                        sx = bar_x + int(((frame_index * 3) % (bar_w + 40)) - 20)
                        sheen = pygame.Surface((14, bar_h), pygame.SRCALPHA); sheen.fill((255, 255, 255, 40))
                        if bar_x <= sx <= bar_x + int(bar_w * frac) - 14:
                            surface.blit(sheen, (sx, ry))
                    if raging and alive and (frame_index // 4) % 2 == 0:
                        pygame.draw.rect(surface, (255, 220, 200), (bar_x, ry, max(6, int(bar_w * frac)), bar_h), width=2, border_radius=6)
                swatch = f.colour if alive else (70, 70, 84)
                sr = int(row_h * 0.30 * (1 + 0.25 * bar_jolt[i]))
                pygame.gfxdraw.filled_circle(surface, int(sim_w * 0.08) + jx, ry + int(row_h * 0.31), sr, swatch)
                pygame.gfxdraw.aacircle(surface, int(sim_w * 0.08) + jx, ry + int(row_h * 0.31), sr, swatch)
                lab = labels[f.name]
                if not alive:
                    lab = lab.copy(); lab.set_alpha(90)
                surface.blit(lab, (int(sim_w * 0.12) + jx, ry + int(row_h * 0.31) - lab.get_height() // 2))

            if caption is not None and frame_index < caption_frames:
                t = min(1.0, frame_index / (0.35 * fps))
                ease = 1 - (1 - t) ** 3
                out = max(0.0, min(1.0, (caption_frames - frame_index) / (0.25 * fps)))
                cap = caption.copy(); cap.set_alpha(int(255 * min(ease, out)))
                surface.blit(cap, ((sim_w - cap.get_width()) // 2, int(sim_h * 0.86 + (1 - ease) * sim_h * 0.05) - cap.get_height() // 2))
            if ask is not None and winner_frame is not None and 0 <= frame_index - winner_frame < ask_frames:
                t = min(1.0, (frame_index - winner_frame) / (0.25 * fps))
                sc = 0.6 + 0.4 * (1 - (1 - t) ** 2) + (0.08 * (1 - t) if t < 1 else 0)
                a2 = pygame.transform.smoothscale(ask, (max(1, int(ask.get_width() * sc)), max(1, int(ask.get_height() * sc))))
                surface.blit(a2, ((sim_w - a2.get_width()) // 2, int(sim_h * 0.30) + (ask.get_height() - a2.get_height()) // 2))
            yield pygame.image.tobytes(surface, "RGB")


register(BallBattle())
