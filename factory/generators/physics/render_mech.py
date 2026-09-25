"""Drawing what the mechanics recorded (`style.mech`), for both renderers.

Everything here reads the recording only — clocks by frame, zones, doors,
who is gone — so a live render and a redraw from a trace draw the same
thing. A style with no `mech` never reaches this module, which is what keeps
every race without mechanics byte-identical.

The look follows the kit's: structure colours lightened for what moves,
the finish chequer's vocabulary for what matters, nothing that competes with
the marbles. Surfaces get a texture a viewer can read at a glance — ice a
cold sheen, sand a grain, a cobweb its threads — because a friction change
nobody can see reads as a glitch, the lesson the magnets' rings taught.
"""

from __future__ import annotations

import math
import random

from ..mechanics import _in_poly, blackout, clock_at, door_state, wall_offset

SURFACE_COLOURS = {
    "ice": (178, 220, 244),
    "thin_ice": (206, 234, 250),
    "sand": (214, 184, 120),
    "mud": (122, 88, 56),
    "cobweb": (214, 214, 224),
    "slush": (150, 176, 190),
}
OUT_RIM = (214, 70, 70)


def mix(a, b, share: float) -> tuple[int, int, int]:
    return tuple(int(round(x + (y - x) * share)) for x, y in zip(a, b))  # type: ignore[return-value]


def zone_points(z, sim_h: float) -> list[tuple[float, float]]:
    """A zone's outline in screen coordinates (y down)."""
    if z.get("rect"):
        x0, y0, x1, y1 = z["rect"]
        return [(x0, sim_h - y0), (x1, sim_h - y0), (x1, sim_h - y1), (x0, sim_h - y1)]
    return [(x, sim_h - y) for x, y in z.get("poly") or []]


def texture(z, t: float, sim_h: float):
    """Marks inside a zone: (kind, list of screen-space items). Deterministic
    from the zone's position, moving with t where the surface is alive."""
    pts = zone_points(z, sim_h)
    if not pts:
        return []
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    rng = random.Random(int(x0 * 31 + y0 * 17 + x1 * 7 + y1))
    kind = z["kind"]
    out = []
    if kind in ("ice", "thin_ice"):
        # A sheen: short diagonal glints sliding slowly along the surface.
        for _ in range(max(2, int((x1 - x0) * (y1 - y0) / 5000))):
            gx, gy = rng.uniform(x0, x1), rng.uniform(y0, y1)
            gx = x0 + ((gx - x0 + t * 18.0) % max(x1 - x0, 1.0))
            length = rng.uniform(8, 18)
            out.append(("line", (gx, gy), (min(x1, gx + length), max(y0, gy - length * 0.6))))
    elif kind in ("sand", "mud", "slush"):
        for _ in range(max(6, int((x1 - x0) * (y1 - y0) / 260))):
            out.append(("dot", (rng.uniform(x0, x1), rng.uniform(y0, y1)), rng.choice((-1, 1))))
    if z.get("poly") and kind != "cobweb":
        # A slanted layer's box is mostly air: keep only the marks inside it
        # (the draws above are made either way, so a rect zone is unchanged).
        out = [item for item in out if _in_poly(item[1][0], item[1][1], pts)]
    if kind == "cobweb":
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        for k in range(8):
            a = k * math.pi / 4 + rng.uniform(-0.2, 0.2)
            r = max(x1 - x0, y1 - y0) / 2
            out.append(("line", (cx, cy), (cx + math.cos(a) * r, cy + math.sin(a) * r)))
        for ring in (0.3, 0.6, 0.9):
            r = min(x1 - x0, y1 - y0) / 2 * ring
            out.append(("ring", (cx, cy), r))
    return out


def surface_colour(kind: str, structure) -> tuple[int, int, int]:
    return mix(structure, SURFACE_COLOURS.get(kind, structure), 0.7)


def zone_shown(mech: dict, z: dict, frame: int) -> bool:
    """A zone that `appear`s is drawn only while its clock is on."""
    return not z.get("appear") or bool(clock_at(mech, z.get("when"), frame))


# --- dice (World 6) ---------------------------------------------------------------------
#
# A die is drawn as a face, never inferred: the clock says which face and
# whether it is still rolling, so a redraw draws the shipped die. While it
# rolls it tumbles (turned, hopping) through faces the mechanic drew from the
# seed; once set it sits square; "lit" rings it (the path it chose), "dim"
# fades it (the ones it did not).
DIE_BODY = (246, 244, 236)
DIE_PIP = (34, 34, 44)
DIE_EDGE = (34, 34, 44)
DIE_LIT = (255, 206, 84)
PIP_AT = {1: [(0, 0)], 2: [(-1, -1), (1, 1)], 3: [(-1, -1), (0, 0), (1, 1)],
          4: [(-1, -1), (1, -1), (-1, 1), (1, 1)], 5: [(-1, -1), (1, -1), (0, 0), (-1, 1), (1, 1)],
          6: [(-1, -1), (1, -1), (-1, 0), (1, 0), (-1, 1), (1, 1)]}


def dice(mech: dict, frame: int, layer: str, sim_h: float):
    """Every die showing now on `layer`, in screen coordinates: a list of
    (corners, pips, pip_r, body, edge, ring) — the body's four corners, the
    pip centres, and the ring colour for a lit die (or None)."""
    out = []
    for e in mech.get("effects") or ():
        if e["kind"] != "die" or (e.get("layer") or "top") != layer:
            continue
        value = clock_at(mech, e.get("clock"), frame) if e.get("clock") else e.get("value")
        if value is None or value is False:
            continue
        face, state = (value.get("f"), value.get("s", "set")) if isinstance(value, dict) else (value, "set")
        face = int(face)
        if face not in PIP_AT:
            continue
        x, y = e.get("at") or (60.0, 880.0)
        size = float(e.get("size") or 56.0)
        sx, sy = x, sim_h - y
        angle = 0.0
        if state == "roll":
            # Tumbling: turned and hopping, deterministic from the frame.
            angle = math.sin(frame * 0.55) * 0.6 + frame * 0.35
            sy -= abs(math.sin(frame * 0.45)) * size * 0.22
        tint = (e.get("tints") or {}).get(str(face))
        body = tuple(tint) if tint else DIE_BODY
        edge = DIE_EDGE
        if state == "dim":
            body, edge = mix(body, (128, 128, 128), 0.55), mix(edge, (128, 128, 128), 0.5)
        c, s = math.cos(angle), math.sin(angle)
        h = size / 2
        corners = [(sx + c * dx - s * dy, sy + s * dx + c * dy) for dx, dy in ((-h, -h), (h, -h), (h, h), (-h, h))]
        step = size * 0.26
        pips = [(sx + c * px * step - s * py * step, sy + s * px * step + c * py * step) for px, py in PIP_AT[face]]
        out.append((corners, pips, max(1.5, size * 0.085), body, edge, DIE_LIT if state == "lit" else None))
    return out


def pil_dice(draw, mech: dict, frame: int, layer: str, sim_h: float) -> None:
    for corners, pips, r, body, edge, ring in dice(mech, frame, layer, sim_h):
        if ring:
            cx = sum(p[0] for p in corners) / 4
            cy = sum(p[1] for p in corners) / 4
            span = max(abs(p[0] - cx) for p in corners) + 5
            draw.rectangle([cx - span, cy - span, cx + span, cy + span], outline=ring, width=4)
        draw.polygon(corners, fill=body, outline=edge)
        for x, y in pips:
            draw.ellipse([x - r, y - r, x + r, y + r], fill=edge)


def pg_dice(surface, mech: dict, frame: int, layer: str, sim_h: float) -> None:
    import pygame

    from .. import fx

    for corners, pips, r, body, edge, ring in dice(mech, frame, layer, sim_h):
        if ring:
            cx = sum(p[0] for p in corners) / 4
            cy = sum(p[1] for p in corners) / 4
            span = max(abs(p[0] - cx) for p in corners) + 5
            fx.soft(surface, cx, cy, span * 1.2, (*ring, 70))
            pygame.draw.rect(surface, ring, (int(cx - span), int(cy - span), int(2 * span), int(2 * span)), 4)
        pygame.draw.polygon(surface, body, corners)
        pygame.draw.polygon(surface, edge, corners, 2)
        for x, y in pips:
            fx.disc(surface, x, y, r, edge)


def countdowns(mech: dict, frame: int):
    """(text, x, y) for each countdown effect showing a value now (physics coords)."""
    out = []
    for e in mech.get("effects") or ():
        if e["kind"] != "countdown":
            continue
        value = clock_at(mech, e.get("clock"), frame)
        if value is None or value is False:
            continue
        x, y = e.get("at") or (270.0, 800.0)
        out.append((str(value), x, y))
    return out


def props(mech: dict, frame: int):
    """(x, y, radius, colour) for each prop showing now (physics coords): a
    marble drawn where no entrant is, with no body behind it."""
    out = []
    for e in mech.get("effects") or ():
        if e["kind"] == "prop" and clock_at(mech, e.get("clock"), frame, e.get("clock") is None):
            x, y = e["at"]
            out.append((x, y, float(e.get("radius", 20.0)), tuple(e.get("color") or (200, 200, 200))))
    return out


# --- PIL -----------------------------------------------------------------------------

def pil_under(draw, style, mech: dict, frame: int, t: float, sim_h: float) -> None:
    """Zones and surfaces: behind the structure and the marbles."""
    bg, st = style.background, style.structure
    for z in mech.get("zones") or ():
        pts = zone_points(z, sim_h)
        if len(pts) < 3 or not zone_shown(mech, z, frame):
            continue
        if z.get("out"):
            active = z.get("when") is None or bool(clock_at(mech, z["when"], frame))
            draw.polygon(pts, fill=mix(bg, (0, 0, 0), 0.45),
                         outline=mix(bg, OUT_RIM, 0.8 if active else 0.3))
            continue
        base = SURFACE_COLOURS.get(z["kind"], st)
        draw.polygon(pts, fill=mix(bg, base, 0.22))
        for item in texture(z, t, sim_h):
            if item[0] == "line":
                draw.line([item[1], item[2]], fill=mix(bg, base, 0.75), width=2)
            elif item[0] == "dot":
                (x, y), tone = item[1], item[2]
                draw.rectangle([x, y, x + 1, y + 1], fill=mix(bg, base, 0.55 if tone > 0 else 0.35))
            elif item[0] == "ring":
                (cx, cy), r = item[1], item[2]
                draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=mix(bg, base, 0.5), width=1)
    for s in mech.get("surfaces") or ():
        a, b = s["a"], s["b"]
        draw.line([(a[0], sim_h - a[1]), (b[0], sim_h - b[1])],
                  fill=surface_colour(s["kind"], st), width=style.thickness)
    pil_dice(draw, mech, frame, "under", sim_h)


def pil_over(draw, style, mech: dict, frame: int, sim_h: float, colours: dict) -> None:
    """Breakables, doors and moving walls: drawn with the structure."""
    st = style.structure
    for br in mech.get("breakables") or ():
        if br.get("broke") is not None and frame >= br["broke"]:
            continue
        a, b = br["a"], br["b"]
        draw.line([(a[0], sim_h - a[1]), (b[0], sim_h - b[1])],
                  fill=surface_colour(br["kind"], st), width=max(3, int(br["thickness"] * 1.4)))
        if br.get("cracked") is not None and frame >= br["cracked"]:
            for k in (0.3, 0.55, 0.8):
                x, y = a[0] + (b[0] - a[0]) * k, a[1] + (b[1] - a[1]) * k
                draw.line([(x - 4, sim_h - y - 5), (x + 2, sim_h - y), (x - 2, sim_h - y + 5)],
                          fill=style.background, width=2)
    for d in mech.get("doors") or ():
        closed, passes = door_state(mech, d, frame)
        a, b = d["a"], d["b"]
        colour = tuple(d["color"]) if d.get("color") else mix(st, (255, 255, 255), 0.15)
        if closed:
            draw.line([(a[0], sim_h - a[1]), (b[0], sim_h - b[1])], fill=colour, width=style.thickness)
        else:
            draw.line([(a[0], sim_h - a[1]), (b[0], sim_h - b[1])], fill=mix(style.background, colour, 0.35), width=2)
        lights = [colours[n] for n in passes if n in colours]
        mx, my = (a[0] + b[0]) / 2, sim_h - (a[1] + b[1]) / 2 - style.thickness - 8
        for k, c in enumerate(lights):
            x = mx + (k - (len(lights) - 1) / 2) * 13
            draw.ellipse([x - 5, my - 5, x + 5, my + 5], fill=c)
    for wl in mech.get("walls") or ():
        dx, dy = wall_offset(mech, wl, frame)
        a, b = wl["a"], wl["b"]
        draw.line([(a[0] + dx, sim_h - a[1] - dy), (b[0] + dx, sim_h - b[1] - dy)],
                  fill=mix(st, (255, 255, 255), 0.2), width=style.thickness)
    for x, y, r, c in props(mech, frame):
        iy = sim_h - y
        draw.ellipse([x - r, iy - r, x + r, iy + r], fill=c)
        draw.ellipse([x - r * 0.42, iy - r * 0.55, x - r * 0.06, iy - r * 0.19],
                     fill=tuple(min(255, v + 60) for v in c))


def pil_top(image, style, mech: dict, frame: int, sim_w: int, sim_h: int):
    """Blackout veil and countdowns, over the race and under the captions.
    Returns the image (a veil replaces it)."""
    from PIL import Image, ImageDraw

    if blackout(mech, frame):
        veil = Image.new("RGB", image.size, mix(style.background, (0, 0, 0), 0.6))
        image = Image.blend(image, veil, 0.82)
    if any(e["kind"] == "die" for e in mech.get("effects") or ()):
        pil_dice(ImageDraw.Draw(image), mech, frame, "top", sim_h)
    shown = countdowns(mech, frame)
    if shown:
        from ...brand import _font  # lazily, as text.py does

        draw = ImageDraw.Draw(image)
        font = _font(int(sim_w * 0.09))
        for text, x, y in shown:
            width = draw.textlength(text, font=font)
            draw.text((x - width / 2, sim_h - y - sim_w * 0.05), text, font=font, fill=style.caption)
    return image


# --- pygame ---------------------------------------------------------------------------

def pg_under(surface, style, mech: dict, frame: int, t: float, sim_h: float) -> None:
    import pygame

    from .. import fx

    bg, st = style.background, style.structure
    for z in mech.get("zones") or ():
        pts = zone_points(z, sim_h)
        if len(pts) < 3 or not zone_shown(mech, z, frame):
            continue
        if z.get("out"):
            active = z.get("when") is None or bool(clock_at(mech, z["when"], frame))
            pygame.draw.polygon(surface, mix(bg, (0, 0, 0), 0.45), pts)
            pygame.draw.polygon(surface, mix(bg, OUT_RIM, 0.8 if active else 0.3), pts, 2)
            continue
        base = SURFACE_COLOURS.get(z["kind"], st)
        pygame.draw.polygon(surface, mix(bg, base, 0.22), pts)
        for item in texture(z, t, sim_h):
            if item[0] == "line":
                fx.capped_line(surface, item[1], item[2], 2, mix(bg, base, 0.75))
            elif item[0] == "dot":
                (x, y), tone = item[1], item[2]
                pygame.draw.rect(surface, mix(bg, base, 0.55 if tone > 0 else 0.35), (int(x), int(y), 2, 2))
            elif item[0] == "ring":
                (cx, cy), r = item[1], item[2]
                pygame.draw.circle(surface, mix(bg, base, 0.5), (int(cx), int(cy)), max(1, int(r)), 1)
    for s in mech.get("surfaces") or ():
        a, b = s["a"], s["b"]
        fx.capped_line(surface, (a[0], sim_h - a[1]), (b[0], sim_h - b[1]), style.thickness,
                       surface_colour(s["kind"], st))
    pg_dice(surface, mech, frame, "under", sim_h)


def pg_over(surface, style, mech: dict, frame: int, sim_h: float, colours: dict) -> None:
    import pygame

    from .. import fx

    st = style.structure
    for br in mech.get("breakables") or ():
        if br.get("broke") is not None and frame >= br["broke"]:
            continue
        a, b = br["a"], br["b"]
        fx.capped_line(surface, (a[0], sim_h - a[1]), (b[0], sim_h - b[1]), max(3, int(br["thickness"] * 1.4)),
                       surface_colour(br["kind"], st))
        if br.get("cracked") is not None and frame >= br["cracked"]:
            for k in (0.3, 0.55, 0.8):
                x, y = a[0] + (b[0] - a[0]) * k, a[1] + (b[1] - a[1]) * k
                pygame.draw.lines(surface, style.background, False,
                                  [(x - 4, sim_h - y - 5), (x + 2, sim_h - y), (x - 2, sim_h - y + 5)], 2)
    for d in mech.get("doors") or ():
        closed, passes = door_state(mech, d, frame)
        a, b = d["a"], d["b"]
        colour = tuple(d["color"]) if d.get("color") else mix(st, (255, 255, 255), 0.15)
        if closed:
            fx.capped_line(surface, (a[0], sim_h - a[1]), (b[0], sim_h - b[1]), style.thickness, colour)
        else:
            fx.capped_line(surface, (a[0], sim_h - a[1]), (b[0], sim_h - b[1]), 2, mix(style.background, colour, 0.35))
        lights = [colours[n] for n in passes if n in colours]
        mx, my = (a[0] + b[0]) / 2, sim_h - (a[1] + b[1]) / 2 - style.thickness - 8
        for k, c in enumerate(lights):
            x = mx + (k - (len(lights) - 1) / 2) * 13
            fx.soft(surface, x, my, 8, (*c, 70))
            fx.disc(surface, x, my, 5, c)
    for wl in mech.get("walls") or ():
        dx, dy = wall_offset(mech, wl, frame)
        a, b = wl["a"], wl["b"]
        fx.capped_line(surface, (a[0] + dx, sim_h - a[1] - dy), (b[0] + dx, sim_h - b[1] - dy),
                       style.thickness, mix(st, (255, 255, 255), 0.2))
    for x, y, r, c in props(mech, frame):
        fx.disc(surface, x, sim_h - y, r, c)
        fx.disc(surface, x - r * 0.25, sim_h - y - r * 0.37, r * 0.2, tuple(min(255, v + 60) for v in c))


_TEXT_CACHE: dict = {}


def pg_top(surface, style, mech: dict, frame: int, sim_w: int, sim_h: int) -> None:
    import pygame

    from .. import fx

    if blackout(mech, frame):
        veil = pygame.Surface((sim_w, sim_h), pygame.SRCALPHA)
        veil.fill((*mix(style.background, (0, 0, 0), 0.6), int(255 * 0.82)))
        surface.blit(veil, (0, 0))
    pg_dice(surface, mech, frame, "top", sim_h)
    for text, x, y in countdowns(mech, frame):
        key = (text, int(sim_w * 0.09), tuple(style.caption))
        if key not in _TEXT_CACHE:
            _TEXT_CACHE[key] = fx.text_surface(text, int(sim_w * 0.09), sim_w * 0.5, colour=style.caption)
        img = _TEXT_CACHE[key]
        surface.blit(img, (x - img.get_width() / 2, sim_h - y - img.get_height() / 2))
