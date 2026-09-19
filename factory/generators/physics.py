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
]
BACKGROUND = (18, 18, 26)
STRUCTURE = (58, 58, 74)


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
    slope of 0.15 the marbles stop dead after four seconds. Each ramp here drops
    its full share of the height, so the slope stays around 0.4, and each ramp
    ends short of the wall so the marble falls onto the next one and makes a
    sound doing it.
    """
    _wall(space, (4, 0), (4, h))
    _wall(space, (w - 4, 0), (w - 4, h))
    _wall(space, (4, 6), (w - 4, 6))

    ramps = 7
    top, bottom = h - 80.0, 40.0
    step = (top - bottom) / ramps
    base_span = w * rng.uniform(0.52, 0.60)
    segments = []
    for i in range(ramps):
        y = top - i * step
        span = base_span * rng.uniform(0.92, 1.06)
        if i % 2 == 0:
            a, b = (26.0, y), (26.0 + span, y - step)
        else:
            a, b = (w - 26.0, y), (w - 26.0 - span, y - step)
        _wall(space, a, b)
        segments.append((a, b))

    # Identical marbles keep their starting order for the whole run, which kills
    # the only question the clip asks. Varying the radius a little makes them
    # overtake each other, and the lane order is shuffled so the seed decides
    # who starts in front.
    base_radius = w * 0.042
    lanes = [50.0 + i * 62.0 for i in range(len(RACE_COLORS))]
    rng.shuffle(lanes)
    balls = []
    for (name, color), x in zip(RACE_COLORS, lanes):
        radius = base_radius * rng.uniform(0.88, 1.12)
        ball = _ball(space, (x, h - 30.0), radius, color, name)
        ball.body.velocity = (0.0, -130.0)  # already moving on frame one
        balls.append(ball)
    return balls, segments


def _build_funnel(space: pymunk.Space, w: int, h: int, rng: random.Random):
    """Two funnels in series, throats measured in ball radii.

    Throat width is the one number that decides whether this variant works, and
    it is not a matter of taste. Below about five radii the balls arch across the
    opening and nothing comes through at all — measured over five seeds, a 3.4r
    throat left 54 of 54 balls sitting above it. Six radii drains every seed. The
    pour is stretched to a watchable length with gravity instead, which is a dial
    that cannot jam.
    """
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
    return balls, segments


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
        states, impacts, balls, segments, winner, winner_frame = sim
        attempts_used = attempt + 1
        duration_s = len(states) / fps
        impacts = [im for im in impacts if im.t < duration_s]

        clip_dir = work_dir
        clip_dir.mkdir(parents=True, exist_ok=True)
        wav = audio.render_wav(impacts, duration_s, clip_dir / "audio.wav")
        silent = render.encode_frames(
            self._frames(states, balls, segments, sim_w, sim_h),
            out_path=clip_dir / "video.mp4",
            src_size=(sim_w, sim_h),
            out_size=(out_w, out_h),
            fps=fps,
        )
        final = render.mux(silent, wav, clip_dir / "clip.mp4")

        if variant == "marble_race":
            if winner:
                description = (
                    f"Four marbles ({', '.join(n for n, _ in RACE_COLORS)}) race down a "
                    f"seven-ramp zigzag course. The {winner} marble reaches the bottom "
                    f"first, at {winner_frame / fps:.1f} seconds."
                )
            else:
                description = (
                    "Four marbles race down a seven-ramp zigzag course; none of them "
                    f"reaches the bottom within {duration_s:.1f} seconds."
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
            balls, segments = _build_race(space, sim_w, sim_h, rng)
            finish_y: float | None = 110.0
        else:
            space.gravity = (0.0, FUNNEL_GRAVITY)
            balls, segments = _build_funnel(space, sim_w, sim_h, rng)
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

        return states, impacts, balls, segments, winner, winner_frame

    def _frames(self, states, balls, segments, sim_w, sim_h) -> Iterator[bytes]:
        for positions in states:
            image = Image.new("RGB", (sim_w, sim_h), BACKGROUND)
            draw = ImageDraw.Draw(image)
            for a, b in segments:
                draw.line(
                    [(a[0], sim_h - a[1]), (b[0], sim_h - b[1])],
                    fill=STRUCTURE,
                    width=12,
                )
            for ball, (x, y) in zip(balls, positions):
                iy = sim_h - y
                r = ball.radius
                draw.ellipse([x - r, iy - r, x + r, iy + r], fill=ball.color)
                draw.ellipse(
                    [x - r * 0.42, iy - r * 0.55, x - r * 0.06, iy - r * 0.19],
                    fill=tuple(min(255, c + 60) for c in ball.color),
                )
            yield image.tobytes()


register(PhysicsSandbox())
