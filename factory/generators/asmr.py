"""ASMR: coins stamped with the Bitcoin symbol, falling and settling.

The sound is the product. Everything else — the pile, the tumbling, the way a
coin lands flat and then rocks twice before it stops — exists to make the sound
happen at a rhythm a person wants to keep listening to.

Two things follow from that and shape the whole module:

  Pace     A race wants urgency; this wants the opposite. Coins arrive on a
           loose rhythm with gaps between them, because a gap is what makes the
           next hit land. Dense, continuous clatter measures louder and is
           much less pleasant, which is the trap in optimising a hook score.

  Timbre   A coin is a thin metal disc, not a marble, so it rings on the
           inharmonic modes of a free circular plate and rings far longer.
           That lives in `audio.TIMBRES["coin"]`; here we only say which
           object hit, how hard, and where.

What this is not: it says nothing about price, and nothing about what a coin is
worth. It is an object falling. A clip that implies a market move because it is
orange has told the viewer something it cannot support.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterator

import pymunk
from PIL import Image, ImageDraw

from .. import audio, render, settings
from .base import GeneratedClip, register

SUBSTEPS = 4
GRAVITY = -820.0  # gentler than the race: a coin should fall, not drop
IMPACT_DV = 52.0  # velocity change that counts as a hit, in sim px/s
MAX_IMPACTS_PER_FRAME = 2  # a pile settling at once is a wash, not a sound
SETTLE_SPEED = 9.0  # below this a coin is at rest and stops making sound
# A disc that is already ringing does not produce a fresh strike when it is
# nudged again, and a settling pile nudges constantly: without this the pour
# measured 74 impacts a second, which is gravel, not ASMR.
RING_REFRACTORY_S = 0.14
SUPERSAMPLE = 4  # sprites are drawn this much bigger and scaled down

# Bitcoin's orange is the one colour the subject actually has; the rest are
# metal tints so that a pile reads as many coins rather than one shape.
TINTS = [
    ("orange", (247, 147, 26)),
    ("gold", (226, 178, 62)),
    ("pale", (243, 208, 130)),
    ("bronze", (196, 126, 48)),
]
# Light backdrops as well as dark, and this is not a taste decision. Eight
# seeds of the first version scored 0.92 and 0.98 against a 0.88 sameness
# ceiling — every one would have been rejected — because coin count and tint
# do not move a single pixel of the layout, and a perceptual hash sees layout
# and brightness. What varies the picture is where the subject sits, how big
# it is, what shape holds it, and how light the room is.
BACKDROPS = [
    (18, 16, 22), (14, 15, 20), (24, 18, 14), (16, 18, 24), (22, 20, 18),
    (236, 231, 222), (214, 206, 196), (198, 204, 212), (246, 240, 228),
]
VESSEL_SHAPES = ("bowl", "flat", "vee")
# The gate is an 8x8 average hash per frame: it sees which of 64 cells are
# brighter than that frame's mean, and nothing else. Coin count and tint move
# no cell at all. What moves cells is where the subject sits, how much of the
# frame it covers, and how light the room is — so those are what the seed is
# allowed to swing, and it is allowed to swing them hard.
ZOOM = (0.70, 1.30)


@dataclass
class _Style:
    backdrop: tuple[int, int, int] = BACKDROPS[0]
    vessel: tuple[int, int, int] = (70, 66, 78)
    seed: int = 0
    variant: str = "coin_pour"
    radius: int = 34
    coins: int = 30
    shape: str = "bowl"
    towers: int = 1

    @property
    def light(self) -> bool:
        return sum(self.backdrop) / 3 > 128


def _vessel_for(backdrop: tuple[int, int, int]) -> tuple[int, int, int]:
    """Furniture a step away from the room, whichever way that is."""
    light = sum(backdrop) / 3 > 128
    delta = -74 if light else 52
    return tuple(max(0, min(255, c + delta)) for c in backdrop)


@dataclass
class _Coin:
    body: pymunk.Body
    radius: float
    tint: tuple[int, int, int]
    index: int  # which pitch it rings on
    edge_on: bool = False
    released_at: float = 0.0
    live: bool = False


@dataclass
class _Scene:
    style: _Style
    coins: list[_Coin] = field(default_factory=list)
    # The floor's profile, as a polyline of points, and the uprights beside
    # it. Kept apart because they are drawn as different objects: chaining
    # them into one polyline drew the bowl into the wall and back.
    profile: list[tuple[float, float]] = field(default_factory=list)
    rails: list[tuple[tuple[float, float], tuple[float, float]]] = field(default_factory=list)


# --- drawing ------------------------------------------------------------------

def _shade(colour: tuple[int, int, int], factor: float) -> tuple[int, int, int]:
    return tuple(max(0, min(255, int(c * factor))) for c in colour)


def _bitcoin_glyph(draw: ImageDraw.ImageDraw, cx: float, cy: float, size: float, fill) -> None:
    """The ₿, drawn rather than typed.

    Measured on this machine: every font in the brand module's candidate list
    answers U+20BF with the .notdef box, byte-identical to what it gives a
    Thai character. A symbol drawn from strokes also stays crisp when the
    sprite is scaled down, which a 12px glyph does not.
    """
    stroke = max(1, int(round(size * 0.16)))
    height = size
    width = size * 0.56
    stem_x = cx - width * 0.45
    top, middle, bottom = cy - height / 2, cy, cy + height / 2

    draw.line([(stem_x, top), (stem_x, bottom)], fill=fill, width=stroke)
    # Two bowls, the lower one wider, each an arc whose ends meet the stem:
    # centring the arc's bounding box on the stem is what makes them meet.
    for y_a, y_b, reach in ((top, middle, 0.80), (middle, bottom, 1.0)):
        right = stem_x + width * reach
        draw.arc([2 * stem_x - right, y_a, right, y_b], start=-90, end=90, fill=fill, width=stroke)
    # The two ticks above and below are the whole difference between ₿ and B.
    for dx in (width * 0.12, width * 0.52):
        draw.line([(stem_x + dx, top - height * 0.19), (stem_x + dx, top)], fill=fill, width=stroke)
        draw.line([(stem_x + dx, bottom), (stem_x + dx, bottom + height * 0.19)], fill=fill, width=stroke)


@lru_cache(maxsize=256)
def _coin_sprite(radius: int, tint: tuple[int, int, int], edge_on: bool) -> Image.Image:
    """One coin, drawn once and reused. Supersampled, because an aliased edge
    is the single thing that makes a rendered object look cheap, and this
    format is watched for the look as much as the sound."""
    s = SUPERSAMPLE
    if edge_on:
        w, h = radius * 2, max(4, int(radius * 0.46))
        image = Image.new("RGBA", (w * s + 2 * s, h * s + 2 * s), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        box = [s, s, w * s + s, h * s + s]
        draw.rounded_rectangle(box, radius=h * s / 2, fill=(*tint, 255))
        draw.rounded_rectangle([box[0], box[1], box[2], box[1] + h * s * 0.42],
                               radius=h * s / 3, fill=(*_shade(tint, 1.22), 255))
        draw.rounded_rectangle([box[0], box[3] - h * s * 0.3, box[2], box[3]],
                               radius=h * s / 3, fill=(*_shade(tint, 0.66), 255))
        return image.resize((w + 2, h + 2), Image.LANCZOS)

    size = radius * 2
    image = Image.new("RGBA", (size * s, size * s), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    r = radius * s
    # Rim, face, and a light from the upper left: three tones is enough to
    # read as a disc, and more turns to mud once it is 34px on a phone.
    draw.ellipse([0, 0, r * 2 - 1, r * 2 - 1], fill=(*_shade(tint, 0.62), 255))
    draw.ellipse([r * 0.11, r * 0.11, r * 1.89, r * 1.89], fill=(*tint, 255))
    draw.arc([r * 0.16, r * 0.16, r * 1.84, r * 1.84], start=160, end=330,
             fill=(*_shade(tint, 1.28), 255), width=max(1, int(r * 0.09)))
    _bitcoin_glyph(draw, r, r, r * 0.95, (*_shade(tint, 0.42), 255))
    return image.resize((size, size), Image.LANCZOS)


# --- scenes -------------------------------------------------------------------

def _static(space: pymunk.Space, a, b, thickness=5.0, elasticity=0.34, friction=0.62) -> None:
    seg = pymunk.Segment(space.static_body, a, b, thickness)
    seg.elasticity = elasticity
    seg.friction = friction
    space.add(seg)


def _new_coin(space, x, y, radius, tint, index, *, edge_on: bool, released_at: float) -> _Coin:
    mass = 0.6 + radius / 90.0
    if edge_on:
        half_h = max(2.0, radius * 0.23)
        body = pymunk.Body(mass, pymunk.moment_for_box(mass, (radius * 2, half_h * 2)))
        shape = pymunk.Poly.create_box(body, (radius * 2, half_h * 2), radius=1.5)
    else:
        body = pymunk.Body(mass, pymunk.moment_for_circle(mass, 0, radius))
        shape = pymunk.Circle(body, radius)
    body.position = (x, y)
    # Metal on metal barely bounces, and a bouncy coin sounds like a ping-pong
    # ball. Friction is high so a pile holds its shape instead of flowing.
    shape.elasticity = 0.16
    shape.friction = 0.78
    space.add(body, shape)
    return _Coin(body=body, radius=radius, tint=tint, index=index,
                 edge_on=edge_on, released_at=released_at)


def _build_pour(space: pymunk.Space, w: int, h: int, rng: random.Random, style: _Style, seconds: float) -> _Scene:
    """Coins poured into a vessel. Dense, overlapping, the richer of the two."""
    zoom = rng.uniform(*ZOOM)
    style.radius = int(w * rng.uniform(0.048, 0.064) * zoom)
    style.shape = rng.choice(VESSEL_SHAPES)
    scene = _Scene(style=style)

    centre = w * rng.uniform(0.36, 0.64)
    floor_y = h * rng.uniform(0.10, 0.40)
    half = min(w * 0.44, w * rng.uniform(0.25, 0.36) * zoom)
    # Enough coins to fill what is above the floor and no more: a vessel set
    # high in the frame holds fewer before the pile runs out of room, and
    # coins stacked past the top edge are sound with no picture.
    room = (h * 0.94 - floor_y) * half * 2 * 0.62 / (math.pi * style.radius ** 2)
    style.coins = max(12, min(rng.randint(34, 50), int(room)))
    # Three floors, because a curve, a flat and a V hold a pile in three
    # different silhouettes, which is what the similarity gate is looking at.
    depth = {"bowl": h * 0.085, "flat": 0.0, "vee": h * 0.13}[style.shape]
    points = []
    for i in range(17):
        f = i / 16
        if style.shape == "vee":
            lift = abs(f - 0.5) * 2
        else:
            lift = (abs(f - 0.5) * 2) ** 2
        points.append((centre - half + 2 * half * f, floor_y + lift * depth))
    for a, b in zip(points, points[1:]):
        _static(space, a, b)
    scene.profile = points

    rail_h = h * rng.uniform(0.30, 0.66)
    for side in (-1, 1):
        a = (centre + side * half, floor_y + depth)
        b = (centre + side * half * rng.uniform(1.0, 1.16), floor_y + depth + rail_h)
        _static(space, a, b)
        scene.rails.append((a, b))

    window = seconds * 0.78
    for i in range(style.coins):
        _, tint = TINTS[rng.randrange(len(TINTS))]
        at = 0.25 + window * (i / max(style.coins - 1, 1)) + rng.uniform(-0.07, 0.07)
        radius = style.radius * rng.uniform(0.86, 1.1)
        coin = _new_coin(space, centre + rng.uniform(-half * 0.45, half * 0.45), h + radius * 2,
                         radius, tint, rng.randrange(6), edge_on=False, released_at=max(0.0, at))
        coin.body.angular_velocity = rng.uniform(-3.5, 3.5)
        scene.coins.append(coin)
    return scene


def _build_stack(space: pymunk.Space, w: int, h: int, rng: random.Random, style: _Style, seconds: float) -> _Scene:
    """Coins dropped edge-on onto a plinth, one at a time, into towers.

    Sparser than the pour and more deliberate: one hit, a rock, silence, the
    next. Whether the towers survive is the clip's only question, and it is
    not asked out loud. One tall tower and three short ones are different
    pictures as well as different rhythms.
    """
    style.towers = rng.choice([1, 1, 2, 3])
    zoom = rng.uniform(*ZOOM)
    style.radius = int(w * {1: rng.uniform(0.15, 0.20), 2: rng.uniform(0.10, 0.13),
                            3: rng.uniform(0.072, 0.092)}[style.towers] * zoom)
    scene = _Scene(style=style)

    plinth_y = h * rng.uniform(0.09, 0.34)
    spread = w * rng.uniform(0.26, 0.34) if style.towers > 1 else 0.0
    centre = w * (rng.uniform(0.40, 0.60) if style.towers == 1 else 0.5)
    xs = [centre + (i - (style.towers - 1) / 2) * spread for i in range(style.towers)]
    edge = max(style.radius * 1.9, max(xs) - min(xs) + style.radius * 1.6)
    a, b = (centre - edge, plinth_y), (centre + edge, plinth_y)
    _static(space, a, b, thickness=7.0, friction=0.9)
    scene.profile = [a, b]

    window = seconds * 0.82
    thickness = max(4.0, style.radius * 0.46)
    # However many fit between the plinth and the top of the frame.
    per_tower = max(3, int((h * 0.92 - plinth_y) / thickness) - 2)
    style.coins = min({1: rng.randint(9, 14), 2: rng.randint(12, 18), 3: rng.randint(15, 22)}[style.towers],
                      per_tower * style.towers)
    heights = [0] * style.towers
    for i in range(style.coins):
        _, tint = TINTS[rng.randrange(len(TINTS))]
        at = 0.4 + window * (i / max(style.coins - 1, 1))
        tower = i % style.towers  # grown together, so every tower is in shot
        y = plinth_y + thickness * (heights[tower] + 1.6) + h * 0.24
        heights[tower] += 1
        coin = _new_coin(space, xs[tower] + rng.uniform(-style.radius * 0.1, style.radius * 0.1), y,
                         style.radius, tint, rng.randrange(6), edge_on=True, released_at=at)
        coin.body.angle = rng.uniform(-0.03, 0.03)
        scene.coins.append(coin)
    return scene


_SCENES = {"coin_pour": _build_pour, "coin_stack": _build_stack}


# --- the module ----------------------------------------------------------------

class CoinASMR:
    name = "asmr"
    variants = ["coin_pour", "coin_stack"]
    ready = True
    blurb = (
        "Coins stamped with the Bitcoin symbol, falling and settling, with the "
        "sound as the product: metal rings on inharmonic plate modes, much "
        "longer than a marble. coin_pour fills a bowl and the pile grows; "
        "coin_stack drops them edge-on onto a tower, one at a time, and the "
        "tower may or may not hold. No text on screen, and nothing about price."
    )

    def generate(self, *, seed: int, variant: str, params: dict[str, Any], work_dir: Path) -> GeneratedClip:
        if variant not in self.variants:
            raise ValueError(f"{self.name}: unknown variant {variant!r}; have {self.variants}")
        cfg = settings.load().render
        out_w, out_h = int(cfg["width"]), int(cfg["height"])
        scale = float(cfg["render_scale"])
        sim_w, sim_h = int(out_w * scale), int(out_h * scale)
        fps = int(cfg["fps"])
        seconds = float(params.get("seconds", cfg.get("max_seconds", 20)))
        frames_total = int(seconds * fps)

        rng = random.Random(seed)
        style = _Style(seed=seed, variant=variant)
        style.backdrop = BACKDROPS[rng.randrange(len(BACKDROPS))]
        if params.get("background"):
            from .physics import parse_hex
            style.backdrop = parse_hex(params["background"])
        style.vessel = _vessel_for(style.backdrop)

        states, impacts, scene = self._simulate(seed, variant, sim_w, sim_h, fps, frames_total, style, seconds)
        duration_s = len(states) / fps

        work_dir.mkdir(parents=True, exist_ok=True)
        wav = audio.render_wav(impacts, duration_s, work_dir / "audio.wav")
        silent = render.encode_frames(
            self._frames(states, scene, sim_w, sim_h),
            out_path=work_dir / "video.mp4", src_size=(sim_w, sim_h),
            out_size=(out_w, out_h), fps=fps,
        )
        final = render.mux(silent, wav, work_dir / "clip.mp4")

        settled = sum(1 for c in scene.coins if c.live and abs(c.body.velocity.length) < SETTLE_SPEED)
        if variant == "coin_pour":
            description = (
                f"{len(scene.coins)} coins stamped with the Bitcoin symbol fall one after another "
                f"into a shallow bowl over {duration_s:.1f} seconds, landing on each other and "
                f"settling into a pile; {len(impacts)} separate impacts are heard, and "
                f"{settled} coins have come to rest by the end. No text on screen."
            )
        else:
            description = (
                f"{len(scene.coins)} coins stamped with the Bitcoin symbol are dropped edge-on onto "
                f"a plinth one at a time over {duration_s:.1f} seconds, each landing on the one "
                f"before it; {len(impacts)} separate impacts are heard, and the stack is "
                f"{settled} coins high and still standing at the end. No text on screen."
            )
        return GeneratedClip(
            video_path=final,
            duration_s=duration_s,
            description=description,
            facts={
                "variant": variant, "seed": seed, "coins": len(scene.coins),
                "impacts": len(impacts), "settled": settled,
                "backdrop": "#%02x%02x%02x" % style.backdrop,
                "radius": style.radius, "timbre": "coin",
                "shape": style.shape if variant == "coin_pour" else None,
                "towers": style.towers if variant == "coin_stack" else None,
            },
        )

    def _simulate(self, seed, variant, sim_w, sim_h, fps, frames_total, style, seconds):
        rng = random.Random(seed ^ 0xC01)
        space = pymunk.Space()
        space.gravity = (0.0, GRAVITY)
        # Let a settled pile fall asleep: it stops the micro-jitter at the
        # source, and a sleeping body costs nothing to step.
        space.sleep_time_threshold = 0.4
        space.idle_speed_threshold = SETTLE_SPEED
        scene = _SCENES[variant](space, sim_w, sim_h, rng, style, seconds)
        # Walls, so nothing leaves the frame and goes silent off-screen.
        for a, b in (((3, -sim_h), (3, sim_h * 2)), ((sim_w - 3, -sim_h), (sim_w - 3, sim_h * 2))):
            _static(space, a, b, elasticity=0.2)

        for coin in scene.coins:  # held out of the space until their moment
            space.remove(coin.body, *coin.body.shapes)

        dt = 1.0 / (fps * SUBSTEPS)
        states: list[list[tuple[float, float, float, bool]]] = []
        impacts: list[audio.Impact] = []
        previous: dict[int, tuple[float, float]] = {}
        last_rang: dict[int, float] = {}

        for frame in range(frames_total):
            now = frame / fps
            for coin in scene.coins:
                if not coin.live and now >= coin.released_at:
                    space.add(coin.body, *coin.body.shapes)
                    coin.live = True
                    previous[id(coin)] = (coin.body.velocity.x, coin.body.velocity.y)
            for _ in range(SUBSTEPS):
                space.step(dt)

            frame_impacts = []
            for coin in scene.coins:
                if not coin.live:
                    continue
                vx, vy = coin.body.velocity
                px, py = previous.get(id(coin), (vx, vy))
                dv = math.hypot(vx - px, vy - py)
                previous[id(coin)] = (vx, vy)
                if dv > IMPACT_DV and now - last_rang.get(id(coin), -9.0) >= RING_REFRACTORY_S:
                    last_rang[id(coin)] = now
                    frame_impacts.append(audio.Impact(
                        t=now,
                        # A pile that has already landed keeps jostling; those
                        # nudges are real but they are not what anyone came to
                        # hear, so strength follows the change, not the speed.
                        strength=min(1.0, 0.16 + dv / 620.0),
                        index=coin.index,
                        pan=(coin.body.position.x / sim_w) * 2 - 1,
                        timbre="coin",
                    ))
            frame_impacts.sort(key=lambda im: -im.strength)
            impacts.extend(frame_impacts[:MAX_IMPACTS_PER_FRAME])
            states.append([
                (c.body.position.x, c.body.position.y, c.body.angle, c.live) for c in scene.coins
            ])
        return states, impacts, scene

    def _backdrop(self, scene: _Scene, sim_w: int, sim_h: int) -> Image.Image:
        """The room: vignette and furniture, drawn once and copied per frame.

        Copying a prepared image is much cheaper than redrawing it 660 times,
        and it buys the vignette for nothing — which is what stops a flat fill
        reading as a slide rather than a scene.
        """
        import numpy as np

        style = scene.style
        ys, xs = np.mgrid[0:sim_h, 0:sim_w]
        # Darkest at the corners, unchanged in the middle third.
        r = np.hypot((xs - sim_w / 2) / (sim_w / 2), (ys - sim_h * 0.62) / (sim_h / 2))
        # Darken the corners of a dark room; on a light one, darkening looks
        # like dirt, so lift the middle instead.
        shade = 0.30 if not style.light else 0.13
        fade = np.clip(1.06 - shade * np.clip(r - 0.45, 0, None) ** 1.5 * 2.2, 0.55, 1.10)
        base = np.array(style.backdrop, dtype=float)[None, None, :] * fade[:, :, None]
        image = Image.fromarray(np.clip(base, 0, 255).astype("uint8"), "RGB")
        draw = ImageDraw.Draw(image)

        flip = [(x, sim_h - y) for x, y in scene.profile]
        if style.variant == "coin_pour":
            # The vessel as a solid, not a wire: a band under the floor's own
            # profile gives it a thickness a viewer reads as a bowl.
            lip = 1.3 if not style.light else 0.75
            skirt = flip + [(x, y + sim_h * 0.028) for x, y in reversed(flip)]
            draw.polygon(skirt, fill=_shade(style.vessel, 0.78))
            draw.line(flip, fill=style.vessel, width=7, joint="curve")
            draw.line([(x, y - 2) for x, y in flip], fill=_shade(style.vessel, lip), width=3, joint="curve")
            for (ax, ay), (bx, by) in scene.rails:
                draw.line([(ax, sim_h - ay), (bx, sim_h - by)], fill=_shade(style.vessel, 0.8), width=7)
        else:
            (x1, y1), (x2, _) = flip
            lip = 1.3 if not style.light else 0.75
            draw.rectangle([x1, y1, x2, y1 + sim_h * 0.035], fill=_shade(style.vessel, 0.78))
            draw.rectangle([x1, y1 - 4, x2, y1 + 3], fill=_shade(style.vessel, lip))
        return image

    def _frames(self, states, scene: _Scene, sim_w: int, sim_h: int) -> Iterator[bytes]:
        base = self._backdrop(scene, sim_w, sim_h)
        for positions in states:
            image = base.copy()
            for coin, (x, y, angle, live) in zip(scene.coins, positions):
                if not live:
                    continue
                sprite = _coin_sprite(int(round(coin.radius)), coin.tint, coin.edge_on)
                turned = sprite.rotate(math.degrees(angle), resample=Image.BICUBIC, expand=True)
                image.paste(turned, (int(x - turned.width / 2), int(sim_h - y - turned.height / 2)), turned)
            yield image.tobytes()


register(CoinASMR())
