"""Physics sandbox generator — the first module in the slot.

Two variants, both fully determined by the seed:

  marble_race  four marbles race a zigzag course, first to the bottom wins
  funnel_drop  a stream of small balls pours through a funnel

Impacts are detected from per-frame velocity changes rather than pymunk's
collision callbacks, because the callback API moved between pymunk 6 and 7 and
this only needs to know that something hit something hard.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

import pymunk
from PIL import Image, ImageDraw

from .. import audio, render, settings
from .base import GeneratedClip, register

SUBSTEPS = 4
# Gravity is a dial, not a physical constant. The race runs slowly on purpose:
# at earth-like gravity the marbles finish a 960px course in under three
# seconds, which is too short to publish and too fast to be pleasant.
RACE_GRAVITY = -600.0
FUNNEL_GRAVITY = -260.0
IMPACT_DV = 22.0  # velocity change that counts as a hit, in sim px/s
MAX_IMPACTS_PER_FRAME = 2  # 54 balls landing at once is a wash, not a sound
STALL_SPEED = 12.0  # below this, in sim px/s, nothing is moving any more
MAX_ATTEMPTS = 4  # a stalled race is retried on a derived seed, not abandoned


class _Stalled(RuntimeError):
    """The simulation came to rest before anything interesting happened."""


RACE_COLORS = [
    ("red", (232, 76, 74)),
    ("blue", (55, 138, 221)),
    ("amber", (239, 159, 39)),
    ("green", (151, 196, 89)),
    ("violet", (150, 122, 224)),
]
BACKGROUND = (18, 18, 26)
STRUCTURE = (58, 58, 74)

# Backdrops, each (background, structure). Two independent judges — the
# perceptual hash and an agent looking at four frames — both called the old
# single-palette race template-like, and both were right: every seed differed
# only in ramp slope and finishing order, neither of which shows in a still.
# These change what a viewer sees before anything moves.
PALETTES = [
    ((18, 18, 26), (58, 58, 74)),
    ((22, 24, 29), (65, 71, 79)),
    ((23, 18, 28), (67, 58, 77)),
    ((16, 26, 22), (52, 71, 63)),
    ((14, 17, 24), (51, 60, 74)),
    ((26, 20, 17), (74, 60, 50)),
]


@dataclass
class _Style:
    """What the clip looks like, as opposed to how it behaves."""

    background: tuple[int, int, int] = BACKGROUND
    structure: tuple[int, int, int] = STRUCTURE
    thickness: int = 12


@dataclass
class _Ball:
    body: pymunk.Body
    radius: float
    color: tuple[int, int, int]
    name: str


def _wall(space: pymunk.Space, a, b, thickness=6.0, friction=0.30) -> None:
    seg = pymunk.Segment(space.static_body, a, b, thickness)
    seg.elasticity = 0.46
    seg.friction = friction
    space.add(seg)


def _ball(space: pymunk.Space, pos, radius, color, name, friction=0.22) -> _Ball:
    # Friction is deliberately low. Chipmunk multiplies the two coefficients, and
    # anything near realistic lets a marble come to rest perched on the rounded
    # end cap of a ramp — four of them then stack behind it and the clip is dead
    # in the water at four seconds. Low friction means they slide off instead.
    mass = 1.0 + radius / 40.0
    body = pymunk.Body(mass, pymunk.moment_for_circle(mass, 0, radius))
    body.position = pos
    shape = pymunk.Circle(body, radius)
    shape.elasticity = 0.52
    shape.friction = friction
    space.add(body, shape)
    return _Ball(body=body, radius=radius, color=color, name=name)


def _build_race(space: pymunk.Space, w: int, h: int, rng: random.Random):
    """Zigzag ramps steep enough that the marbles never come to rest.

    A shallow ramp looks fine in a screenshot and stalls in the solver — at a
    slope of 0.15 the marbles stop dead after four seconds, so the slope is held
    near 0.4 whatever else changes. Everything a viewer can see in a single
    frame is varied around that fixed point: the backdrop, how many ramps, which
    side they start from, how thick they are, how many marbles there are and how
    big.

    Ramp count and span move together on purpose. Span is derived from the slope
    rather than chosen, so more ramps means shorter ones and the total path
    length — and therefore the clip's duration — stays where QC wants it.
    """
    style = _Style()
    style.background, style.structure = rng.choice(PALETTES)
    style.thickness = rng.randint(8, 15)

    _wall(space, (4, 0), (4, h))
    _wall(space, (w - 4, 0), (w - 4, h))
    _wall(space, (4, 6), (w - 4, 6))

    # Five was in this list until a forced test stalled 12 times out of 12: at
    # that count the ramps are long enough that a marble comes to rest on one.
    # Leaving it in only spent retries on a course that never finishes.
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
        if starts_left:
            a, b = (26.0, y), (26.0 + span, y - step)
        else:
            a, b = (w - 26.0, y), (w - 26.0 - span, y - step)
        _wall(space, a, b, thickness=style.thickness / 2)
        segments.append((a, b))

    # Identical marbles keep their starting order for the whole run, which kills
    # the only question the clip asks. Varying the radius makes them overtake,
    # and the lane order is shuffled so the seed decides who starts in front.
    base_radius = w * rng.uniform(0.036, 0.050)
    # How many fit depends on how long the first ramp is: a nine-ramp course has
    # short ramps, and five marbles would start on top of each other.
    runway = span * 0.62
    room = int(runway // (base_radius * 2.5)) + 1
    count = max(3, min(rng.choice([3, 4, 5]), room, len(RACE_COLORS)))
    spacing = runway / max(count - 1, 1)

    colours = list(RACE_COLORS)
    rng.shuffle(colours)
    lanes = [45.0 + i * spacing for i in range(count)]
    if not mirrored:
        pass
    else:
        lanes = [w - x for x in lanes]
    rng.shuffle(lanes)

    balls = []
    for (name, color), x in zip(colours[:count], lanes):
        radius = base_radius * rng.uniform(0.88, 1.12)
        ball = _ball(space, (x, h - 30.0), radius, color, name)
        ball.body.velocity = (0.0, -130.0)  # already moving on frame one
        balls.append(ball)
    return balls, segments, style


def _build_funnel(space: pymunk.Space, w: int, h: int, rng: random.Random):
    """Two funnels in series, throats measured in ball radii.

    Throat width is the one number that decides whether this variant works, and
    it is not a matter of taste. Below about five radii the balls arch across the
    opening and nothing comes through at all — measured over five seeds, a 3.4r
    throat left 54 of 54 balls sitting above it. Six radii drains every seed. The
    pour is stretched to a watchable length with gravity instead, which is a dial
    that cannot jam.
    """
    style = _Style()
    style.background, style.structure = rng.choice(PALETTES)

    _wall(space, (4, 0), (4, h))
    _wall(space, (w - 4, 0), (w - 4, h))
    _wall(space, (4, 6), (w - 4, 6))

    radius = w * 0.022
    upper_gap = radius * rng.uniform(5.6, 6.4)
    lower_gap = radius * rng.uniform(5.1, 5.9)
    segments = [
        ((16.0, h * 0.78), (w / 2 - upper_gap / 2, h * 0.46)),
        ((w - 16.0, h * 0.78), (w / 2 + upper_gap / 2, h * 0.46)),
        ((16.0, h * 0.34), (w / 2 - lower_gap / 2, h * 0.13)),
        ((w - 16.0, h * 0.34), (w / 2 + lower_gap / 2, h * 0.13)),
    ]
    for a, b in segments:
        _wall(space, a, b)

    columns = 6
    pitch = radius * 2.35
    left = w / 2 - (columns - 1) * pitch / 2
    balls = []
    for i in range(54):
        x = left + (i % columns) * pitch + rng.uniform(-2.5, 2.5)
        y = h - 60.0 - (i // columns) * radius * 2.6
        ball = _ball(space, (x, y), radius, _hsv((i * 37 % 360) / 360.0), f"ball{i}")
        ball.body.velocity = (0.0, -90.0)  # falling on frame one, not hanging
        balls.append(ball)
    return balls, segments, style


def _hsv(hue: float) -> tuple[int, int, int]:
    r, g, b = _hsv_to_rgb(hue, 0.55, 0.92)
    return (int(r * 255), int(g * 255), int(b * 255))


def _hsv_to_rgb(h: float, s: float, v: float):
    i = int(h * 6.0)
    f = h * 6.0 - i
    p, q, t = v * (1 - s), v * (1 - s * f), v * (1 - s * (1 - f))
    return [(v, t, p), (q, v, p), (p, v, t), (p, q, v), (t, p, v), (v, p, q)][i % 6]


class PhysicsSandbox:
    name = "physics"
    variants = ["marble_race", "funnel_drop"]
    ready = True
    blurb = (
        "Deterministic 2D physics. marble_race: four coloured marbles race a "
        "zigzag ramp course, one wins. funnel_drop: dozens of small balls pour "
        "through a funnel. No prior knowledge needed, holds attention to the end."
    )

    def generate(
        self, *, seed: int, variant: str, params: dict[str, Any], work_dir: Path
    ) -> GeneratedClip:
        if variant not in self.variants:
            raise ValueError(f"{self.name}: unknown variant {variant!r}")
        cfg = settings.load().render
        out_w, out_h = int(cfg["width"]), int(cfg["height"])
        scale = float(cfg["render_scale"])
        sim_w, sim_h = int(out_w * scale), int(out_h * scale)
        fps = int(cfg["fps"])
        max_frames = int(float(params.get("max_seconds", cfg["max_seconds"])) * fps)

        # About one race seed in six wedges a marble and never finishes. Rather
        # than burn the seed, derive the next course from it: still fully
        # determined by `seed`, just not by its first attempt.
        for attempt in range(MAX_ATTEMPTS):
            try:
                sim = self._simulate(
                    seed=seed + attempt * 7919,
                    variant=variant,
                    sim_w=sim_w,
                    sim_h=sim_h,
                    fps=fps,
                    max_frames=max_frames,
                )
                break
            except _Stalled as exc:
                if attempt == MAX_ATTEMPTS - 1:
                    raise RuntimeError(
                        f"{variant} seed {seed} stalled on every one of "
                        f"{MAX_ATTEMPTS} attempts ({exc})"
                    ) from None
        states, impacts, balls, segments, winner, winner_frame, style = sim
        attempts_used = attempt + 1
        duration_s = len(states) / fps
        impacts = [im for im in impacts if im.t < duration_s]

        clip_dir = work_dir
        clip_dir.mkdir(parents=True, exist_ok=True)
        wav = audio.render_wav(impacts, duration_s, clip_dir / "audio.wav")
        silent = render.encode_frames(
            self._frames(
                states, balls, segments, sim_w, sim_h,
                overlay=self._overlay(variant, sim_w, sim_h, fps),
                style=style,
            ),
            out_path=clip_dir / "video.mp4",
            src_size=(sim_w, sim_h),
            out_size=(out_w, out_h),
            fps=fps,
        )
        final = render.mux(silent, wav, clip_dir / "clip.mp4")

        if variant == "marble_race":
            names = ", ".join(b.name for b in balls)
            ramp_count = len(segments)
            if winner:
                description = (
                    f"{len(balls)} marbles ({names}) race down a {ramp_count}-ramp "
                    f"zigzag course. The {winner} marble reaches the bottom first, at "
                    f"{winner_frame / fps:.1f} seconds."
                )
            else:
                description = (
                    f"{len(balls)} marbles race down a {ramp_count}-ramp zigzag course; "
                    f"none reaches the bottom within {duration_s:.1f} seconds."
                )
        else:
            description = (
                f"{len(balls)} small coloured balls pour through a narrow funnel throat "
                f"over {duration_s:.1f} seconds, clicking as they jam and release."
            )

        return GeneratedClip(
            video_path=final,
            duration_s=duration_s,
            description=description,
            facts={
                "variant": variant,
                "seed": seed,
                "winner": winner,
                "impacts": len(impacts),
                "objects": len(balls),
                "ramps": len(segments),
                "palette": style.background,
                "sim_attempts": attempts_used,
            },
        )

    def _simulate(
        self, *, seed: int, variant: str, sim_w: int, sim_h: int, fps: int, max_frames: int
    ):
        """Run the physics only. Raises _Stalled when a race goes nowhere."""
        rng = random.Random(seed)
        space = pymunk.Space()
        if variant == "marble_race":
            space.gravity = (0.0, RACE_GRAVITY)
            balls, segments, style = _build_race(space, sim_w, sim_h, rng)
            finish_y: float | None = 110.0
        else:
            space.gravity = (0.0, FUNNEL_GRAVITY)
            balls, segments, style = _build_funnel(space, sim_w, sim_h, rng)
            finish_y = None

        dt = 1.0 / (fps * SUBSTEPS)
        states: list[list[tuple[float, float]]] = []
        impacts: list[audio.Impact] = []
        previous = [(b.body.velocity.x, b.body.velocity.y) for b in balls]
        winner: str | None = None
        winner_frame: int | None = None
        stalled = 0

        for frame in range(max_frames):
            for _ in range(SUBSTEPS):
                space.step(dt)

            frame_impacts = []
            for i, ball in enumerate(balls):
                vx, vy = ball.body.velocity
                dv = math.hypot(vx - previous[i][0], vy - previous[i][1])
                previous[i] = (vx, vy)
                if dv > IMPACT_DV:
                    frame_impacts.append(
                        audio.Impact(
                            t=frame / fps,
                            strength=min(1.0, dv / 900.0),
                            index=i,
                            pan=(ball.body.position.x / sim_w) * 2 - 1,
                        )
                    )
            frame_impacts.sort(key=lambda im: -im.strength)
            impacts.extend(frame_impacts[:MAX_IMPACTS_PER_FRAME])
            states.append([(b.body.position.x, b.body.position.y) for b in balls])

            # Everything coming to rest ends the pour, but in a race it means a
            # marble is wedged and the clip is dead.
            if max(b.body.velocity.length for b in balls) < STALL_SPEED:
                stalled += 1
            else:
                stalled = 0
            if stalled > fps * 1.5:
                if finish_y is None:
                    break
                raise _Stalled(f"no winner by {frame / fps:.1f}s")

            if finish_y is not None and winner is None:
                for ball in balls:
                    if ball.body.position.y - ball.radius <= finish_y:
                        winner, winner_frame = ball.name, frame
                        break
            if winner_frame is not None and frame >= winner_frame + int(fps * 1.3):
                break

        # Varying the course changed the duration spread as well as the look,
        # and a short course can now finish under the QC floor. The generator
        # knows that floor, so it burns the seed here rather than handing QC a
        # clip it is certain to reject.
        # Only judge a race that actually finished: a run cut off by max_frames
        # has no meaningful duration yet, and short runs are exactly what the
        # tests use.
        if finish_y is not None and winner_frame is not None:
            floor = float(settings.load().qc["min_seconds"])
            if len(states) / fps < floor:
                raise _Stalled(
                    f"finished in {len(states) / fps:.1f}s, under the {floor}s floor"
                )

        return states, impacts, balls, segments, winner, winner_frame, style

    def _overlay(self, variant: str, sim_w: int, sim_h: int, fps: int):
        """Opening caption, or None. Returns (text, font, x, y, last_frame)."""
        cfg = settings.load().raw.get("overlay", {})
        text = (cfg.get(variant) or "").strip()
        if not text:
            return None
        from ..brand import _font

        font = _font(int(sim_w * 0.072))
        probe = ImageDraw.Draw(Image.new("RGB", (1, 1)))
        text_width = probe.textlength(text, font=font)
        # Two constraints squeeze this: the objects all start at the top of
        # frame and spend the caption's whole life up there, and Shorts covers
        # the bottom ~15% and right ~12% with its own UI. That leaves the lower
        # third but above the UI.
        return (
            text,
            font,
            (sim_w - text_width) / 2,
            sim_h * 0.70,
            int(float(cfg.get("seconds", 0)) * fps),
        )

    def _frames(
        self, states, balls, segments, sim_w, sim_h, overlay=None, style=None
    ) -> Iterator[bytes]:
        style = style or _Style()
        for frame_index, positions in enumerate(states):
            image = Image.new("RGB", (sim_w, sim_h), style.background)
            draw = ImageDraw.Draw(image)
            for a, b in segments:
                draw.line(
                    [(a[0], sim_h - a[1]), (b[0], sim_h - b[1])],
                    fill=style.structure,
                    width=style.thickness,
                )
            for ball, (x, y) in zip(balls, positions):
                iy = sim_h - y
                r = ball.radius
                draw.ellipse([x - r, iy - r, x + r, iy + r], fill=ball.color)
                draw.ellipse(
                    [x - r * 0.42, iy - r * 0.55, x - r * 0.06, iy - r * 0.19],
                    fill=tuple(min(255, c + 60) for c in ball.color),
                )
            if overlay is not None:
                text, font, tx, ty, last = overlay
                if frame_index < last:
                    # Fade over the final third rather than cutting, which reads
                    # as a dropped frame.
                    fade = min(1.0, (last - frame_index) / max(1, last / 3))
                    level = int(60 + 195 * fade)
                    draw.text((tx, ty), text, font=font, fill=(level, level, level))
            yield image.tobytes()


register(PhysicsSandbox())
