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
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

import pymunk
from PIL import Image, ImageDraw

from .. import audio, render, settings, themes
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
POST_WIN_S = 1.3  # how long the race keeps running after the winner crosses
CLOSE_RACE_S = 1.0  # a runner-up inside this gets the margin on screen


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


# Courses: the shape of the descent. Each is a different picture to the
# perceptual hash, which is what a variant's capacity is made of, and a
# different question to the viewer. Weights are how often a random seed lands
# on each; a task can name one.
# A fourth course, wedges (chevrons staggered like pegs), was built and cut:
# marbles balanced on an apex, wedged between an arm and the next row's wall
# lip, or sat in a wall corner — three traps, and fixing one opened another.
# Measured 7 finishes in 24 at best. The three below each finish 19 of 24
# inside the QC window with no seed stuck.
COURSES = {"zigzag": 0.45, "pegboard": 0.30, "bumpers": 0.25}
# Pace is gravity, not geometry: each course was measured over 24 seeds and
# its gravity set so the median finish lands mid-window (see README).
COURSE_GRAVITY = {"zigzag": -600.0, "pegboard": -110.0, "bumpers": -95.0}
COURSE_NOUN = {"zigzag": "ramps", "pegboard": "pegs", "bumpers": "bumpers"}


@dataclass
class _Style:
    """What the clip looks like, as opposed to how it behaves."""

    background: tuple[int, int, int] = BACKGROUND
    structure: tuple[int, int, int] = STRUCTURE
    thickness: int = 12
    circles: list[tuple[float, float, float]] = field(default_factory=list)  # pegs, bumpers
    course: str = "zigzag"
    theme: str = "default"
    decoration: str = "none"
    caption: tuple[int, int, int] = (255, 255, 255)
    seed: int = 0


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


def _pick(rng: random.Random, weights: dict[str, float]) -> str:
    total = sum(weights.values())
    roll = rng.uniform(0, total)
    for name, weight in weights.items():
        roll -= weight
        if roll <= 0:
            return name
    return next(iter(weights))


def _peg(space: pymunk.Space, x: float, y: float, r: float, elasticity: float = 0.62) -> None:
    shape = pymunk.Circle(space.static_body, r, offset=(x, y))
    shape.elasticity = elasticity
    shape.friction = 0.12
    space.add(shape)


def _course_zigzag(space, w, h, rng, style):
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
        _wall(space, a, b, thickness=style.thickness / 2)
        segments.append((a, b))
    runway = span * 0.62
    lanes = lambda count: [(45.0 + i * (runway / max(count - 1, 1))) if not mirrored else w - (45.0 + i * (runway / max(count - 1, 1))) for i in range(count)]
    return segments, runway, lanes


def _course_pegboard(space, w, h, rng, style):
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
                _peg(space, x, y, r)
                style.circles.append((x, y, r))
    return [], w * 0.6, lambda count: [w * 0.2 + (w * 0.6) * i / max(count - 1, 1) for i in range(count)]


def _course_bumpers(space, w, h, rng, style):
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
                _peg(space, x, y + rng.uniform(-6, 6), r, elasticity=0.9)
                style.circles.append((x, y, r))
    segments = [((26.0, h * 0.22), (w * 0.40, h * 0.10)), ((w - 26.0, h * 0.22), (w * 0.60, h * 0.10))]
    for a, b in segments:
        _wall(space, a, b, thickness=style.thickness / 2)
    return segments, w * 0.6, lambda count: [w * 0.2 + (w * 0.6) * i / max(count - 1, 1) for i in range(count)]


_COURSES = {"zigzag": _course_zigzag, "pegboard": _course_pegboard, "bumpers": _course_bumpers}


def _build_race(space: pymunk.Space, w: int, h: int, rng: random.Random, course: str | None = None):
    """A course from the registry, dressed by the active theme.

    Everything a viewer can see in a single frame is varied: which course, the
    backdrop, how thick the structure is, how many marbles and how big. What
    stays fixed is what keeps the solver honest — slopes, throat widths, pace.
    """
    theme = themes.active()
    style = _Style()
    style.background, style.structure = rng.choice(theme.palettes)
    style.thickness = rng.randint(8, 15)
    style.theme, style.decoration, style.caption = theme.id, theme.decoration, theme.caption
    style.course = course or _pick(rng, COURSES)
    if style.course not in _COURSES:
        raise ValueError(f"no course {style.course!r}; have {sorted(_COURSES)}")
    space.gravity = (0.0, COURSE_GRAVITY[style.course])

    _wall(space, (4, 0), (4, h))
    _wall(space, (w - 4, 0), (w - 4, h))
    _wall(space, (4, 6), (w - 4, 6))

    segments, runway, lanes_for = _COURSES[style.course](space, w, h, rng, style)

    # Identical marbles keep their starting order for the whole run, which kills
    # the only question the clip asks. Varying the radius makes them overtake,
    # and the lane order is shuffled so the seed decides who starts in front.
    base_radius = w * rng.uniform(0.036, 0.050)
    room = int(runway // (base_radius * 2.5)) + 1
    count = max(3, min(rng.choice([3, 4, 5]), room, len(theme.marbles)))

    colours = list(theme.marbles)
    rng.shuffle(colours)
    lanes = lanes_for(count)
    rng.shuffle(lanes)

    balls = []
    for (name, color), x in zip(colours[:count], lanes):
        radius = base_radius * rng.uniform(0.88, 1.12)
        ball = _ball(space, (x, h - 30.0), radius, tuple(color), name)
        ball.body.velocity = (rng.uniform(-20, 20), -130.0)  # already moving on frame one
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
                    course=params.get("course"),
                )
                break
            except _Stalled as exc:
                if attempt == MAX_ATTEMPTS - 1:
                    raise RuntimeError(
                        f"{variant} seed {seed} stalled on every one of "
                        f"{MAX_ATTEMPTS} attempts ({exc})"
                    ) from None
        states, impacts, balls, segments, winner, winner_frame, style, finishes = sim
        attempts_used = attempt + 1
        duration_s = len(states) / fps
        impacts = [im for im in impacts if im.t < duration_s]

        finish_s = {
            name: round(f / fps, 2)
            for name, f in sorted(finishes.items(), key=lambda kv: kv[1])
        }
        order = list(finish_s)
        runner_up = order[1] if len(order) > 1 else None
        margin_s = round(finish_s[order[1]] - finish_s[order[0]], 2) if runner_up else None
        hook_text = (params.get("hook_text") or "").strip() or self._default_hook(variant, margin_s)

        clip_dir = work_dir
        clip_dir.mkdir(parents=True, exist_ok=True)
        wav = audio.render_wav(impacts, duration_s, clip_dir / "audio.wav")
        silent = render.encode_frames(
            self._frames(
                states, balls, segments, sim_w, sim_h,
                overlay=self._overlay(variant, sim_w, sim_h, fps, text=hook_text),
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
            obstacles = len(style.circles) or len(segments)
            course_text = {
                "zigzag": f"a {obstacles}-ramp zigzag course",
                "pegboard": f"a pegboard of {obstacles} pegs",
                "bumpers": f"a field of {obstacles} bumpers",
            }[style.course]
            themed = "" if style.theme == "default" else f" Styled for {style.theme}."
            if winner:
                gap = (
                    f", {margin_s:.1f} seconds ahead of {runner_up}"
                    if runner_up else
                    f"; no other marble crosses in the next {POST_WIN_S} seconds"
                )
                description = (
                    f"{len(balls)} marbles ({names}) race down {course_text}. The "
                    f"{winner} marble reaches the bottom first, at "
                    f"{winner_frame / fps:.1f} seconds{gap}.{themed}"
                )
            else:
                description = (
                    f"{len(balls)} marbles race down {course_text}; "
                    f"none reaches the bottom within {duration_s:.1f} seconds.{themed}"
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
                "course": style.course,
                "obstacles": len(style.circles) or len(segments),
                "theme": style.theme,
                "palette": style.background,
                "sim_attempts": attempts_used,
                "finishes": finish_s,
                "runner_up": runner_up,
                "margin_s": margin_s,
                "hook_text": hook_text,
            },
        )

    def _simulate(
        self, *, seed: int, variant: str, sim_w: int, sim_h: int, fps: int, max_frames: int,
        course: str | None = None,
    ):
        """Run the physics only. Raises _Stalled when a race goes nowhere."""
        rng = random.Random(seed)
        space = pymunk.Space()
        if variant == "marble_race":
            space.gravity = (0.0, RACE_GRAVITY)
            balls, segments, style = _build_race(space, sim_w, sim_h, rng, course)
            style.seed = seed
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
        finishes: dict[str, int] = {}
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

            if finish_y is not None:
                # Every crossing is recorded, not only the first: the gap to
                # the runner-up is what the opening caption is built from.
                for ball in balls:
                    if ball.name in finishes:
                        continue
                    if ball.body.position.y - ball.radius <= finish_y:
                        finishes[ball.name] = frame
                        if winner is None:
                            winner, winner_frame = ball.name, frame
            if winner_frame is not None and frame >= winner_frame + int(fps * POST_WIN_S):
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

        return states, impacts, balls, segments, winner, winner_frame, style, finishes

    def _default_hook(self, variant: str, margin_s: float | None) -> str:
        """The opening caption, from the race itself whenever the race gives one.

        "DECIDED BY 0.4s" is a fact the simulation produced; "WHO TAKES IT?" is
        a slogan. Three of four viewers swipe before the race resolves, and a
        number states the stake in the one second they give us. Falls back to
        the config line when the runner-up never crossed.
        """
        if variant == "marble_race" and margin_s is not None and margin_s < CLOSE_RACE_S:
            shown = f"{margin_s:.2f}" if margin_s < 0.1 else f"{margin_s:.1f}"
            return f"DECIDED BY {shown}s"
        cfg = settings.load().raw.get("overlay", {})
        return (cfg.get(variant) or "").strip()

    def _overlay(self, variant: str, sim_w: int, sim_h: int, fps: int, text: str | None = None):
        """Opening caption, or None. Returns (text, font, x, y, last_frame)."""
        cfg = settings.load().raw.get("overlay", {})
        if text is None:
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
            for cx, cy, r in style.circles:
                iy = sim_h - cy
                draw.ellipse([cx - r, iy - r, cx + r, iy + r], fill=style.structure)
                draw.ellipse([cx - r * 0.45, iy - r * 0.55, cx - r * 0.05, iy - r * 0.15],
                             fill=tuple(min(255, c + 40) for c in style.structure))
            if style.decoration != "none":
                _decorate(draw, style, frame_index, sim_w, sim_h)
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
                    mix = 0.25 + 0.75 * fade
                    draw.text((tx, ty), text, font=font,
                              fill=tuple(int(c * mix) for c in style.caption))
            yield image.tobytes()


def _decorate(draw, style: _Style, frame: int, w: int, h: int) -> None:
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


register(PhysicsSandbox())
