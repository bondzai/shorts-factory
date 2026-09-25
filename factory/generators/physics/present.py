"""The presentation: what a marble race shows when, over a simulation it never touches.

A race is simulated and drawn exactly as before; this decides how the drawn
frames are *shown*. A deterministic director reads a round (positions,
impacts, lead changes, the winner's crossing) and writes a time map — for
every output frame, the source frame it shows (a float: nearest, or two
frames blended in a slowed stretch) and a camera (zoom, centre). The
compositor then plays the renderer's frames through that map, draws the
coloured fire in world space under the camera, and the HUD (caption, name
chips, leaderboard, progress bar, closing ask) over it, never zoomed.

Why it exists: the first three seconds decide the swipe, and a flat,
wide, real-time race opens on marbles the size of a fingernail. So the clip
cold-opens tight (1.9x on the pack), slows the first hit, pulls out to the
whole stage, punches in on every lead change, and ends slowed and tight on
the line, framed like its first frame so a loop reads as one shot.

Nothing here is random: the fire's particles come from a seeded stream,
and the time map is stored in the trace so a redraw is the shipped frame.
`[presentation] enabled = false` never reaches this module.
"""

from __future__ import annotations

import bisect
import dataclasses
import math
import random
from typing import Any, Iterator

import numpy as np
from PIL import Image

from ... import settings
from ..mechanics import FINISH_Y, hidden
from . import outcome as physics_outcome

DEFAULTS: dict[str, Any] = {
    "enabled": True,
    "zoom": 1.9,
    "slowmo": 0.4,
    "reveal_speed": 1.3,
    "punch": 1.25,
    "finish_slowmo": 0.5,
    "fire": True,
    "leaderboard": True,
}

# The opening: where the hit may be found (source seconds), how long a
# window is slowed, and the fallback window when nothing qualifies.
HIT_SEARCH_S = (0.3, 2.2)
HIT_WINDOW_S = 0.5
HIT_LEAD_S = 0.2           # of the window before the event
HIT_FALLBACK_S = (0.6, 1.1)
STRONG_HIT = 0.2           # an impact's strength (dv / 900) that counts as a hit
TOUCH = 1.15               # two marbles within this x their radii are touching
# The reveal: the pull-out to 1.0, and when the speed is back to real time.
PULL_OUT_S = 0.8
RAMP_UP_S = 0.15
REVEAL_END_S = 3.0
# Punch-ins on a lead change: in, out, and the least gap between two.
PUNCH_IN_S, PUNCH_OUT_S, PUNCH_GAP_S = 0.15, 0.15, 1.5
# The finish: seconds of source around the winner's crossing, and the zoom-in.
FINISH_WINDOW_S = 0.8
FINISH_ZOOM_S = 0.5
# HUD clocks, output seconds.
CHIPS_S = (0.3, 2.0)
CHIP_FADE_S = 0.3
TOWER_FROM_S = 1.0
SLAM_S = 0.25
SLAM_FROM = 1.4
CENTROID_SMOOTH = 6        # frames either side
MAX_PARTICLES = 900


def config() -> dict | None:
    """The [presentation] block over the defaults, or None when it is off.

    A config with no block at all is off: a checkout that predates it renders
    as it always did."""
    raw = settings.load().raw.get("presentation")
    if not raw:
        return None
    cfg = {**DEFAULTS, **raw}
    if not cfg["enabled"]:
        return None
    for key in ("zoom", "slowmo", "reveal_speed", "punch", "finish_slowmo"):
        cfg[key] = float(cfg[key])
    cfg["fire"], cfg["leaderboard"] = bool(cfg["fire"]), bool(cfg["leaderboard"])
    if not (1.0 <= cfg["zoom"] <= 3.0 and 1.0 <= cfg["punch"] <= 2.0):
        raise ValueError("presentation: zoom must be 1-3 and punch 1-2")
    if not (0.1 <= cfg["slowmo"] <= 1.0 and 0.1 <= cfg["finish_slowmo"] <= 1.0 and 1.0 <= cfg["reveal_speed"] <= 2.0):
        raise ValueError("presentation: slowmo and finish_slowmo must be 0.1-1, reveal_speed 1-2")
    return cfg


# --- what a round is, to the director and the compositor -------------------------

@dataclasses.dataclass
class View:
    """A round as plain data, the same whether it was just simulated or
    loaded back from a trace."""

    states: np.ndarray                 # (frames, marbles, 2), physics y-up
    names: list[str]
    labels: list[str]                  # what a chip / the tower calls each marble
    colours: list[tuple[int, int, int]]
    radii: list[float]
    impacts: list[tuple[float, float, int]]  # (source t, strength, index)
    winner_frame: int | None
    winner: str | None
    finishes: dict[str, int]
    mech: dict
    seed: int
    finish_y: float | None


def view_of(r: dict, labels: dict[str, str]) -> View:
    """A live round (sandbox's dict) as a View."""
    style = r["style"]
    mech = getattr(style, "mech", None) or {}
    names = [b.name for b in r["balls"]]
    return View(states=np.asarray(r["states"], dtype=np.float64).reshape(len(r["states"]), len(names), 2),
                names=names, labels=[labels.get(n, n) for n in names],
                colours=[tuple(int(c) for c in b.color) for b in r["balls"]],
                radii=[float(b.radius) for b in r["balls"]],
                impacts=[(float(im.t), float(im.strength), int(im.index)) for im in r["impacts"]],
                winner_frame=r["winner_frame"], winner=r["winner"], finishes=dict(r["finishes"]), mech=mech,
                seed=int(style.seed), finish_y=None if mech.get("no_finish") else FINISH_Y)


def labels_for(balls, cast: list[dict] | None) -> dict[str, str]:
    """Display names: the cast's own, `Blaze 2` for a team's second marble,
    the colour's name in capitals when there is no cast."""
    by_id = {e["id"]: str(e.get("name") or e["id"]) for e in (cast or [])}
    out = {}
    for b in balls:
        if b.name in by_id:
            out[b.name] = by_id[b.name]
        elif "." in b.name and b.name.split(".")[0] in by_id:
            base, k = b.name.split(".", 1)
            out[b.name] = f"{by_id[base]} {k}"
        else:
            out[b.name] = b.name.upper()
    return out


# --- the director -----------------------------------------------------------------

def _ease(u: float) -> float:
    u = min(1.0, max(0.0, u))
    return u * u * (3 - 2 * u)


def find_hit(v: View, fps: int) -> dict:
    """The opening's moment: the first strong impact between two marbles, or
    the first lead change, in source 0.3-2.2 s; the fallback window if neither."""
    lo, hi = int(HIT_SEARCH_S[0] * fps), int(HIT_SEARCH_S[1] * fps)
    n = len(v.states)
    gone = {v.names.index(k): f for k, f in (v.mech.get("gone") or {}).items() if k in v.names}
    best: dict | None = None
    for t, strength, i in v.impacts:
        f = int(round(t * fps))
        if not lo <= f <= min(hi, n - 1) or strength < STRONG_HIT or i >= len(v.names):
            continue
        if i in gone and gone[i] <= f:
            continue
        x, y = v.states[f][i]
        for j in range(len(v.names)):
            if j == i or (j in gone and gone[j] <= f):
                continue
            if math.dist((x, y), v.states[f][j]) <= (v.radii[i] + v.radii[j]) * TOUCH:
                best = {"kind": "impact", "frame": f, "who": sorted({v.names[i], v.names[j]})}
                break
        if best:
            break
    end = v.winner_frame if v.winner_frame is not None else n - 1
    leads = physics_outcome.lead_changes(v.states[: end + 1], gone or None)
    lead = next(((f, i) for f, i in leads if lo <= f <= hi), None)
    if lead is not None and (best is None or lead[0] < best["frame"]):
        # Who it took the lead from: the leader one sample earlier.
        ys = v.states[max(0, lead[0] - physics_outcome.LEAD_SAMPLE)][:, 1]
        racing = [i for i in range(len(ys)) if not (i in gone and gone[i] <= lead[0])]
        prev = min(racing, key=lambda i: ys[i]) if racing else lead[1]
        best = {"kind": "lead_change", "frame": lead[0], "who": sorted({v.names[lead[1]], v.names[prev]})}
    if best is None:
        a, b = int(HIT_FALLBACK_S[0] * fps), int(HIT_FALLBACK_S[1] * fps)
        return {"kind": "none", "frame": None, "who": [], "window": [a, min(b, n - 1)]}
    a = max(0, best["frame"] - int(round(HIT_LEAD_S * fps)))
    best["window"] = [a, min(n - 1, a + int(round(HIT_WINDOW_S * fps)))]
    return best


def _speeds(n: int, fps: int, cfg: dict, hit: dict | None, finish: list[int] | None,
            reveal: bool) -> tuple[list[float], dict]:
    """Integrate the speed curve: the source frame of every output frame."""
    out: list[float] = []
    marks: dict[str, int] = {}
    s, k = 0.0, 0
    hit_a, hit_b = hit["window"] if hit else (None, None)
    fin_a, fin_b = finish if finish else (None, None)
    reveal_from: int | None = None
    while True:
        out.append(s)
        if s >= n - 1:
            break
        if hit_a is not None and hit_a <= s < hit_b:
            marks.setdefault("hit_in", k)
            sp = cfg["slowmo"]
        elif fin_a is not None and fin_a <= s < fin_b:
            marks.setdefault("finish_in", k)
            sp = cfg["finish_slowmo"]
        else:
            sp = 1.0
            if hit_b is not None and s >= hit_b:
                if reveal_from is None:
                    reveal_from = k
                    marks["hit_out"] = k
                o = (k - reveal_from) / fps
                end = max(REVEAL_END_S, reveal_from / fps + PULL_OUT_S) * fps
                hold = reveal_from + (RAMP_UP_S + 0.35) * fps
                top = cfg["reveal_speed"] if reveal else 1.0
                if o < RAMP_UP_S:
                    sp = cfg["slowmo"] + (top - cfg["slowmo"]) * _ease(o / RAMP_UP_S)
                elif k < hold:
                    sp = top
                elif k < end:
                    sp = top + (1.0 - top) * _ease((k - hold) / max(1.0, end - hold))
                else:
                    marks.setdefault("reveal_end", k)
            if fin_b is not None and s >= fin_b:
                marks.setdefault("finish_out", k)
        if sp >= 0.999 and abs(sp - 1.0) < 1e-3:
            nxt = math.floor(s + 1e-9) + 1.0  # real time runs on whole frames
        else:
            nxt = s + sp
        s = min(float(n - 1), nxt)
        k += 1
    return out, marks


def _to_out(src: float, S: np.ndarray) -> float:
    """The output frame (float) that shows source frame `src`."""
    return float(np.interp(src, S, np.arange(len(S), dtype=np.float64)))


def _clamp_centre(cx: float, cy: float, z: float, w: int, h: int) -> tuple[float, float]:
    hw, hh = w / (2 * z), h / (2 * z)
    return min(max(cx, hw), w - hw), min(max(cy, hh), h - hh)


def plan_round(v: View, n_round: int, n_rounds: int, fps: int, w: int, h: int, cfg: dict,
               finish_s: float, hit_on: bool = True, reveal: bool = True) -> tuple[np.ndarray, dict]:
    """(time map (frames, 4): source, zoom, cx, cy in screen px; moments)."""
    n = len(v.states)
    first, last = n_round == 0, n_round == n_rounds - 1
    hit = find_hit(v, fps) if first and hit_on else None
    finish = None
    if last and v.winner_frame is not None and finish_s > 0:
        half = finish_s * fps / 2
        a = max(0, int(round(v.winner_frame - half)))
        b = min(n - 1, int(round(v.winner_frame + half)))
        if hit and a < hit["window"][1] + fps:
            a = hit["window"][1] + fps  # never on top of the opening
        if b > a:
            finish = [a, b]
    src, marks = _speeds(n, fps, cfg, hit, finish, reveal)
    S = np.asarray(src, dtype=np.float64)
    m = len(S)

    # The pack's centroid on screen, per source frame, smoothed.
    gone = {v.names.index(k): f for k, f in (v.mech.get("gone") or {}).items() if k in v.names}
    cents = np.zeros((n, 2))
    for f in range(n):
        alive = [i for i in range(len(v.names)) if not (i in gone and gone[i] <= f)] or list(range(len(v.names)))
        cents[f] = v.states[f][alive].mean(axis=0)
    cents[:, 1] = h - cents[:, 1]
    k = CENTROID_SMOOTH
    padded = np.pad(cents, ((k, k), (0, 0)), mode="edge")
    kernel = np.ones(2 * k + 1) / (2 * k + 1)
    smooth = np.stack([np.convolve(padded[:, d], kernel, mode="valid") for d in (0, 1)], axis=1)

    def centroid(s: float) -> tuple[float, float]:
        i0 = int(s)
        i1 = min(n - 1, i0 + 1)
        f = s - i0
        return tuple(smooth[i0] * (1 - f) + smooth[i1] * f)

    def pos(i: int, s: float) -> tuple[float, float]:
        i0 = int(s)
        i1 = min(n - 1, i0 + 1)
        f = s - i0
        x, y = v.states[i0][i] * (1 - f) + v.states[i1][i] * f
        return float(x), float(h - y)

    moments: dict[str, Any] = {"frames": m}
    z_open = cfg["zoom"]
    hit_out = marks.get("hit_out", marks.get("hit_in", 0)) if hit else None
    hit_point = None
    if hit and hit["frame"] is not None and hit["who"]:
        idx = [v.names.index(nm) for nm in hit["who"]]
        pts = [pos(i, float(hit["frame"])) for i in idx]
        hit_point = (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))
    open_end = (hit_out + PULL_OUT_S * fps) if hit else (fps * 1.0)
    fin_in = marks.get("finish_in")

    # Punch-ins: at lead changes after the opening, never crowding the finish.
    punches: list[tuple[float, int]] = []
    if cfg["punch"] > 1.0:
        end = v.winner_frame if v.winner_frame is not None else n - 1
        for f, i in physics_outcome.lead_changes(v.states[: end + 1], gone or None):
            o = _to_out(float(f), S)
            if o < open_end or (fin_in is not None and o + (PUNCH_IN_S + PUNCH_OUT_S + 0.3) * fps > fin_in):
                continue
            if punches and o - punches[-1][0] < PUNCH_GAP_S * fps:
                continue
            punches.append((o, i))
    finish_point = None
    if finish:
        wi = v.names.index(v.winner) if v.winner in v.names else int(np.argmin(v.states[v.winner_frame][:, 1]))
        wx, wy = pos(wi, float(v.winner_frame))
        fy = h - v.finish_y if v.finish_y is not None else wy
        finish_point = (wx, fy)

    tm = np.zeros((m, 4))
    for k_out in range(m):
        s = S[k_out]
        z, cx, cy = 1.0, w / 2, h / 2
        if hit and k_out < open_end:
            c = centroid(s)
            if hit_point is not None:
                # Lean toward the hit so it happens in frame.
                o_hit = _to_out(float(hit["frame"]), S)
                lean = 0.55 * _ease(1 - abs(k_out - o_hit) / (0.6 * fps))
                c = (c[0] + (hit_point[0] - c[0]) * lean, c[1] + (hit_point[1] - c[1]) * lean)
            if k_out < hit_out:
                z = z_open
            else:
                z = z_open + (1.0 - z_open) * _ease((k_out - hit_out) / (PULL_OUT_S * fps))
            cx, cy = c
        for o, i in punches:
            d = k_out - o
            if 0 <= d < (PUNCH_IN_S + PUNCH_OUT_S) * fps:
                u = _ease(d / (PUNCH_IN_S * fps)) if d < PUNCH_IN_S * fps else \
                    _ease(1 - (d - PUNCH_IN_S * fps) / (PUNCH_OUT_S * fps))
                z = 1.0 + (cfg["punch"] - 1.0) * u
                px, py = pos(i, s)
                cx, cy = w / 2 + (px - w / 2) * u, h / 2 + (py - h / 2) * u
        if finish_point is not None and fin_in is not None and k_out >= fin_in:
            u = _ease((k_out - fin_in) / (FINISH_ZOOM_S * fps))
            z = 1.0 + (z_open - 1.0) * u
            cx, cy = w / 2 + (finish_point[0] - w / 2) * u, h / 2 + (finish_point[1] - h / 2) * u
        elif last and finish_point is None and k_out >= m - fps:
            # No winner to frame: close on the pack, as the clip opened.
            u = _ease((k_out - (m - fps)) / (FINISH_ZOOM_S * fps))
            z = 1.0 + (z_open - 1.0) * u
            c = centroid(s)
            cx, cy = w / 2 + (c[0] - w / 2) * u, h / 2 + (c[1] - h / 2) * u
        cx, cy = _clamp_centre(cx, cy, z, w, h)
        tm[k_out] = (s, z, cx, cy)

    sec = lambda k_: round(k_ / fps, 3)  # noqa: E731
    if hit:
        a, b = hit["window"]
        moments["hit"] = {"kind": hit["kind"], "who": hit["who"],
                          "src_s": None if hit["frame"] is None else sec(hit["frame"]),
                          "out_s": None if hit["frame"] is None else sec(_to_out(float(hit["frame"]), S)),
                          "window_src_s": [sec(a), sec(b)],
                          "window_out_s": [sec(_to_out(float(a), S)), sec(_to_out(float(b), S))],
                          "speed": cfg["slowmo"]}
        moments["reveal_out_s"] = [sec(hit_out), sec(marks.get("reveal_end", hit_out + PULL_OUT_S * fps))]
        moments["chips_out_s"] = list(CHIPS_S)
    moments["punch_ins"] = [{"out_s": sec(o), "who": v.names[i]} for o, i in punches]
    if finish:
        moments["finish"] = {"window_src_s": [sec(finish[0]), sec(finish[1])],
                             "window_out_s": [sec(_to_out(float(finish[0]), S)), sec(_to_out(float(finish[1]), S))],
                             "speed": cfg["finish_slowmo"],
                             "winner_out_s": sec(_to_out(float(v.winner_frame), S))}
    return tm, moments


def direct(views: list[View], fps: int, w: int, h: int, cfg: dict, max_s: float,
           min_s: float = 0.0) -> dict:
    """Every round's time map and moments, inside the QC length.

    When the slowed stretches would push the clip past `max_s`, the finish
    slow-mo gives way first (shorter, then none), then the opening's."""
    finish_s = FINISH_WINDOW_S
    hit_on = True
    reveal = True
    while True:
        plans = [plan_round(v, n, len(views), fps, w, h, cfg, finish_s, hit_on, reveal) for n, v in enumerate(views)]
        total = sum(len(tm) for tm, _ in plans) / fps
        if total > max_s:
            if finish_s > 0:
                finish_s = round(max(0.0, finish_s - 0.2), 3)
                continue
            if hit_on:
                hit_on = False
                continue
        if total < min_s and reveal:
            reveal = False  # the 1.3x stretch is the only thing that shortens a clip
            continue
        break
    return {"maps": [tm for tm, _ in plans], "moments": [mo for _, mo in plans],
            "output_s": total, "source_s": sum(len(v.states) for v in views) / fps,
            "finish_window_s": finish_s, "hit": hit_on, "reveal": reveal}


def out_time(src_t: float, S: np.ndarray, fps: int) -> float:
    """Output seconds (within a round) of a source time."""
    return _to_out(src_t * fps, S) / fps


def trace_meta(cfg: dict, labels: dict[str, str], rounds: list[dict], plan: dict) -> dict:
    """What trace.json keeps so a redraw is the shipped frame: the settings,
    the labels, each round's finishes (a trace kept only the winner's) and
    moments. The per-frame time map itself goes to trace.npz. Round-tripped
    through JSON here so the live render reads exactly what a redraw will."""
    import json

    meta = {"config": cfg, "labels": labels, "output_s": round(plan["output_s"], 3),
            "rounds": [{"finishes": dict(r["finishes"]), "moments": mo}
                       for r, mo in zip(rounds, plan["moments"])]}
    return json.loads(json.dumps(meta, sort_keys=True))


def facts(plan: dict) -> dict:
    """facts["presentation"]: the output length and the moments, for QC and copy."""
    return {"output_s": round(plan["output_s"], 2), "source_s": round(plan["source_s"], 2),
            "rounds": [{k: v for k, v in r["moments"].items() if k != "frames"} for r in plan["meta"]["rounds"]]}


def soundtrack(rounds: list[dict], plan: dict, fps: int):
    """(impacts on the output clock, the presentation's own sounds).

    An impact keeps its pitch; a slowed stretch only spreads them out."""
    from ... import audio

    shown: list = []
    offset = 0.0
    for r, tm in zip(rounds, plan["maps"]):
        S = tm[:, 0]
        shown += [audio.Impact(offset + out_time(im.t, S, fps), im.strength, im.index, im.pan)
                  for im in r["impacts"]]
        offset += len(tm) / fps
    sounds = [(0.0, "whoosh", 0.55)]
    hit = plan["meta"]["rounds"][0]["moments"].get("hit") or {}
    if hit.get("out_s") is not None:
        sounds.append((float(hit["out_s"]), "thump", 0.9))
    return shown, sounds


def hud(cfg: dict, overlay, ask, style, n_round: int) -> "Hud":
    return Hud(caption=overlay, ask=ask, caption_colour=tuple(style.caption), chips=n_round == 0,
               leaderboard=cfg["leaderboard"])


def view_from_trace(arrays: dict, meta: dict, n: int) -> View:
    """Round n of a trace as a View: the same numbers view_of read live."""
    pres = meta["presentation"]
    r = meta["rounds"][n]
    names = list(meta["entrant_ids"])
    mech = r["style"].get("mech") or {}
    return View(states=np.asarray(arrays[f"round{n}_positions"], dtype=np.float64), names=names,
                labels=[pres["labels"].get(nm, nm) for nm in names],
                colours=[tuple(int(c) for c in rgb) for rgb in arrays["colors"]],
                radii=[float(x) for x in arrays["radii"][n]],
                impacts=[(float(t), float(st), int(i)) for t, st, i, _ in r["impacts"]],
                winner_frame=r["winner_frame"], winner=r["winner"],
                finishes={k: int(f) for k, f in pres["rounds"][n]["finishes"].items()}, mech=mech,
                seed=int(r["style"].get("seed", 0)), finish_y=None if mech.get("no_finish") else FINISH_Y)


# --- the compositor -----------------------------------------------------------------

class Fire:
    """Flames in each marble's own colour: a bright core, a darker tip.

    Particles are born just behind a marble and left where they were born
    (a little drift, a little rise), so the trail they make is as long as
    the marble is fast. All in world screen px; drawn through the camera."""

    STAGES = 6

    def __init__(self, seed: int, colours, radii):
        import pygame

        self.pg = pygame
        self.rng = random.Random(seed * 7919 + 0xF1E)
        self.colours = colours
        self.radii = radii
        self.items: list[list[float]] = []  # x, y, vx, vy, age, life, marble, size
        self.carry = [0.0] * len(colours)
        self.cache: dict[tuple, Any] = {}
        self.ramps = [self._ramp(c) for c in colours]

    @staticmethod
    def _ramp(colour):
        """Colour by age: white-hot core, the marble's colour, a dark tip."""
        hot = tuple(int(c + (255 - c) * 0.6) for c in colour)
        tip = tuple(int(c * 0.35) for c in colour)
        out = []
        for k in range(Fire.STAGES):
            u = k / (Fire.STAGES - 1)
            if u < 0.4:
                a, b, t = hot, colour, u / 0.4
            else:
                a, b, t = colour, tip, (u - 0.4) / 0.6
            out.append(tuple(int(x + (y - x) * t) for x, y in zip(a, b)))
        return out

    def sprite(self, colour, r: int):
        key = (colour, r)
        spr = self.cache.get(key)
        if spr is None:
            pg = self.pg
            size = r * 2 + 2
            spr = pg.Surface((size, size))
            spr.fill((0, 0, 0))
            # A soft disc: concentric circles, dimmer outward. RGB only; it is
            # added, so black is transparent and the falloff is the alpha.
            for q in range(r, 0, -1):
                f = (1 - q / (r + 1)) ** 1.4
                pg.draw.circle(spr, tuple(int(c * f) for c in colour), (r + 1, r + 1), q)
            self.cache[key] = spr
        return spr

    def emit(self, i: int, x: float, y: float, vx: float, vy: float, dt: float) -> None:
        speed = math.hypot(vx, vy)
        r = self.radii[i]
        rate = 14.0 + speed * 0.10             # per source second
        self.carry[i] += rate * dt
        count = int(self.carry[i])
        self.carry[i] -= count
        # Flames stream away from the way it moves and upward: behind a fast
        # marble, straight up off a slow one. Born on the rim, not over the
        # marble, so it stays a marble with fire on it rather than a blur.
        dx, dy = -vx, -vy - 160.0
        norm = math.hypot(dx, dy) or 1.0
        ux, uy = dx / norm, dy / norm
        for _ in range(count):
            out = r * self.rng.uniform(0.75, 1.0)
            side = r * self.rng.uniform(-0.55, 0.55)
            px, py = x + ux * out - uy * side, y + uy * out + ux * side
            push = 20.0 + speed * 0.05
            self.items.append([px, py, ux * push + self.rng.uniform(-14, 14), uy * push + self.rng.uniform(-14, 14),
                               0.0, self.rng.uniform(0.18, 0.32), i, r * self.rng.uniform(0.42, 0.66)])

    def preroll(self, points, vels, fps: int, frames: int = 10) -> None:
        """The cold open is already burning: run the flames over the moments
        before frame one, the marbles taken back along their first velocity."""
        for j in range(frames, 0, -1):
            for i, ((x, y), (vx, vy)) in enumerate(zip(points, vels)):
                if (x, y) != (None, None):
                    self.emit(i, x - vx * j / fps, y - vy * j / fps, vx, vy, 1.0 / fps)
            self.step(1.0 / fps)

    def burst(self, i: int, x: float, y: float, strength: float, count: int) -> None:
        r = self.radii[i]
        for _ in range(count):
            a = self.rng.uniform(0, 2 * math.pi)
            sp = self.rng.uniform(40, 90 + 260 * strength)
            life = self.rng.uniform(0.18, 0.34 + 0.2 * strength)
            # Born a stage past white-hot: a burst of near-white read as a
            # flash, not as that marble's fire.
            self.items.append([x + math.cos(a) * r * 0.6, y + math.sin(a) * r * 0.6,
                               math.cos(a) * sp, math.sin(a) * sp - 30,
                               life * 0.25, life, i,
                               r * self.rng.uniform(0.25, 0.45 + 0.25 * strength)])

    def step(self, dt: float) -> None:
        if dt <= 0:
            return
        for p in self.items:
            p[0] += p[2] * dt
            p[1] += p[3] * dt
            p[3] -= 70.0 * dt      # flames rise (screen y is down)
            p[2] *= 0.92
            p[4] += dt
        self.items = [p for p in self.items if p[4] < p[5]]
        if len(self.items) > MAX_PARTICLES:
            self.items = self.items[-MAX_PARTICLES:]

    def draw(self, surface, cam) -> None:
        z, x0, y0 = cam
        add = self.pg.BLEND_ADD
        for x, y, _vx, _vy, age, life, i, size in self.items:
            u = age / life
            stage = min(Fire.STAGES - 1, int(u * Fire.STAGES))
            r = max(1, int(size * z * (1.0 - 0.55 * u)))
            spr = self.sprite(self.ramps[int(i)][stage], r)
            surface.blit(spr, (int((x - x0) * z) - r - 1, int((y - y0) * z) - r - 1), special_flags=add)


def layout(w: int, h: int, count: int) -> dict[str, Any]:
    """Where the HUD sits: a thin bar near the top, a tower on the LEFT (the
    right is under Shorts' buttons), each as (x, y, w, h).

    The tower sits in the middle band, between the closing ask (0.30 h) and
    the caption (0.70 h). At the top it was under the marbles for the whole
    opening: every race starts at the top, and the zoomed camera is clamped
    there, so the pack filled exactly the corner the tower was in."""
    bar = (round(w * 0.06), round(h * 0.052), round(w * 0.74), max(4, round(h * 0.0065)))
    row = min(h * 0.036, max(h * 0.022, h * 0.19 / max(1, count)))
    top = h * 0.37
    tw = w * 0.30
    rows = [(round(w * 0.03), round(top + k * row), round(tw), round(row)) for k in range(count)]
    tower = (round(w * 0.03) - 4, round(top) - 4, round(tw) + 8, round(row * count) + 8)
    return {"bar": bar, "tower": tower, "rows": rows, "row_h": row}


@dataclasses.dataclass
class Hud:
    """The words and their clocks for one round (output frames)."""

    caption: tuple | None      # overlay(): (text, font, x, y, last)
    ask: tuple | None          # closing_ask(): (text, font, x, y, span)
    caption_colour: tuple[int, int, int]
    chips: bool                # the name chips (the clip's first round)
    leaderboard: bool


def compose(raw: Iterator[bytes], v: View, tm: np.ndarray, hud: Hud, w: int, h: int, fps: int,
            fire_on: bool, moments: dict) -> Iterator[bytes]:
    """The shipped frames of one round: `raw` (the renderer's frames, in
    source order) played through the time map, with fire and the HUD."""
    import pygame

    from .. import fx

    fx.init()
    n = len(v.states)
    S = tm[:, 0]
    frames: dict[int, np.ndarray] = {}
    it = iter(raw)
    got = -1

    def source(i: int) -> np.ndarray:
        nonlocal got
        while got < i:
            got += 1
            frames[got] = np.frombuffer(next(it), dtype=np.uint8).reshape(h, w, 3)
            for old in [k for k in frames if k < got - 2]:
                del frames[old]
        return frames[i]

    fire = Fire(v.seed, v.colours, v.radii) if fire_on else None
    impacts = sorted(v.impacts)
    ts = [t * fps for t, _, _ in impacts]
    hit = moments.get("hit") or {}
    hit_f = None if hit.get("src_s") is None else round(hit["src_s"] * fps)
    lay = layout(w, h, len(v.names))
    order_y = None  # the tower's rows, easing to their slots
    tower_dim = 1.0  # eases down while a marble is under the tower
    labels = [fx.text_surface(t, max(10, int(lay["row_h"] * 0.62)), lay["rows"][0][2] * 0.66, outline=False)
              for t in v.labels]
    ranks = [fx.text_surface(str(r + 1), max(9, int(lay["row_h"] * 0.5)), lay["row_h"], colour=(200, 200, 210),
                             outline=False) for r in range(len(v.names))]
    chip_font = max(11, int(w * 0.034))
    chips = [_chip(pygame, fx, t, c, chip_font) for t, c in zip(v.labels, v.colours)] if hud.chips else []
    cap = (fx.text_surface(hud.caption[0], hud.caption[1].size, w * 0.9, colour=hud.caption_colour)
           if hud.caption else None)
    ask = fx.text_surface(hud.ask[0], hud.ask[1].size, w * 0.9, colour=hud.caption_colour) if hud.ask else None
    win_out = None
    if v.winner_frame is not None:
        win_out = int(math.ceil(_to_out(float(v.winner_frame), S) - 1e-9))
    y0s = v.states[0][:, 1].max() if n else 0.0
    prev_s = 0.0

    def at(i: int, s: float) -> tuple[float, float]:
        i0 = min(n - 1, int(s))
        i1 = min(n - 1, i0 + 1)
        f = s - int(s)
        x, y = v.states[i0][i] * (1 - f) + v.states[i1][i] * f
        return float(x), float(h - y)

    for k in range(len(tm)):
        s, z, cx, cy = (float(q) for q in tm[k])
        slow = (k and s - S[k - 1] < 0.999) or (k + 1 < len(S) and S[k + 1] - s < 0.999)
        i0 = int(math.floor(s + 1e-9))
        frac = s - i0
        if frac < 1e-6:
            img = source(i0)
        elif slow and i0 + 1 < n:
            # A sharpened cross-fade: near a whole frame it is that frame, and
            # only mid-way are two mixed. A straight mix left every marble with
            # a double edge through the whole slow-mo.
            mix = min(1.0, max(0.0, (frac - 0.25) / 0.5))
            a, b = source(i0), source(i0 + 1)
            img = a if mix <= 0.0 else b if mix >= 1.0 else \
                (a.astype(np.float32) * (1 - mix) + b.astype(np.float32) * mix + 0.5).astype(np.uint8)
        else:
            img = source(min(n - 1, int(round(s))))
        hw, hh = w / (2 * z), h / (2 * z)
        x0, y0 = cx - hw, cy - hh
        if abs(z - 1.0) > 1e-6:
            pic = Image.fromarray(img).resize((w, h), Image.BILINEAR, box=(x0, y0, x0 + 2 * hw, y0 + 2 * hh))
            surface = pygame.image.frombytes(pic.tobytes(), (w, h), "RGB")
        else:
            surface = pygame.image.frombytes(img.tobytes(), (w, h), "RGB")
        frame_no = int(round(s))

        # --- fire, in world space through the camera
        if fire is not None:
            dt = max(0.0, (s - prev_s) / fps)
            lo = bisect.bisect_right(ts, prev_s) if k else 0
            hi = bisect.bisect_right(ts, s)
            for t, strength, i in impacts[lo:hi]:
                if i < len(v.names) and not hidden(v.mech, v.names[i], frame_no) and strength >= 0.12:
                    x, y = at(i, t * fps)
                    fire.burst(i, x, y, strength, int(2 + 9 * strength))
            if hit_f is not None and (prev_s < hit_f <= s or (k == 0 and hit_f == 0)):
                for name in hit.get("who") or []:
                    i = v.names.index(name)
                    x, y = at(i, float(hit_f))
                    fire.burst(i, x, y, 1.0, 26)
            if k == 0 and n > 1:
                pts, vels = [], []
                for i, name in enumerate(v.names):
                    x, y = at(i, 0.0)
                    nx, ny = at(i, 1.0)
                    hide = hidden(v.mech, name, 0)
                    pts.append((None, None) if hide else (x, y))
                    vels.append((0.0, 0.0) if hide else ((nx - x) * fps, (ny - y) * fps))
                fire.preroll(pts, vels, fps)
            fire.step(dt)
            if dt > 0:
                for i, name in enumerate(v.names):
                    if hidden(v.mech, name, frame_no):
                        continue
                    x, y = at(i, s)
                    px, py = at(i, max(0.0, s - 1))
                    fire.emit(i, x, y, (x - px) * fps, (y - py) * fps, dt)
            fire.draw(surface, (z, x0, y0))
        prev_s = s
        o = k / fps

        # --- HUD: after the camera, never zoomed
        if hud.leaderboard and o >= TOWER_FROM_S - 0.3:
            fade = _ease((o - (TOWER_FROM_S - 0.3)) / 0.3)
            # Zoomed in, the marbles are big and near it: let them show through.
            fade *= 1.0 - 0.45 * min(1.0, max(0.0, (z - 1.0) / 0.6))
            if hud.ask and win_out is not None and 0 <= k - win_out < hud.ask[4]:
                fade *= 0.45  # out of the ask's way while it is up
            # A marble passing under it sees through it: every stage runs a
            # marble down the left at some point, and a solid panel there hid it.
            tx, ty, tw, th = lay["tower"]
            under = False
            for i, name in enumerate(v.names):
                if hidden(v.mech, name, frame_no):
                    continue
                px, py = at(i, s)
                sx, sy, sr = (px - x0) * z, (py - y0) * z, v.radii[i] * z
                if tx - sr < sx < tx + tw + sr and ty - sr < sy < ty + th + sr:
                    under = True
                    break
            tower_dim += ((0.3 if under else 1.0) - tower_dim) * 0.25
            fade *= tower_dim
            order = standings(v, s, frame_no)
            if order_y is None:
                order_y = {i: float(r) for r, i in enumerate(order)}
            for r, i in enumerate(order):
                order_y[i] += (r - order_y[i]) * 0.28
            _tower(pygame, surface, lay, v, order, order_y, labels, ranks, fade)
            _bar(pygame, fx, surface, lay, v, order, s, y0s, fade)
        if chips and CHIPS_S[0] - 0.15 <= o <= CHIPS_S[1] + CHIP_FADE_S:
            alpha = min(_ease((o - (CHIPS_S[0] - 0.15)) / 0.15), 1 - _ease((o - CHIPS_S[1]) / CHIP_FADE_S))
            _chips(pygame, surface, v, chips, [at(i, s) for i in range(len(v.names))], (z, x0, y0), w, h, alpha, frame_no)
        if cap is not None:
            _slam(pygame, surface, cap, w / 2, hud.caption[3] + cap.get_height() / 2, k, hud.caption[4], fps, w)
        if ask is not None and win_out is not None:
            fx.pop_in(surface, ask, w / 2, hud.ask[3], k - win_out, hud.ask[4], fps)
        yield fx.to_bytes(surface)


def standings(v: View, s: float, frame: int) -> list[int]:
    """Current order: finished by finish frame, then the rest by who is
    lowest (the lead the events count), the eliminated last."""
    gone = v.mech.get("gone") or {}
    i0 = min(len(v.states) - 1, int(s))
    keyed = []
    for i, name in enumerate(v.names):
        f = v.finishes.get(name)
        if f is not None and f <= frame:
            keyed.append(((0, f, 0.0), i))
        elif name in gone and gone[name] <= frame:
            keyed.append(((2, -gone[name], 0.0), i))
        else:
            keyed.append(((1, 0, float(v.states[i0][i][1])), i))
    keyed.sort(key=lambda t: (t[0], t[1]))
    return [i for _, i in keyed]


def _chip(pygame, fx, text: str, colour, size: int):
    """A name chip's body: a pill in the marble's colour. Its pointer is drawn
    per frame, since it points down at the marble or, when the camera has the
    marble out of view, sideways toward it."""
    light = sum(colour) / 3 > 150
    label = fx.text_surface(text, size, 10_000, colour=(20, 20, 26) if light else (255, 255, 255), outline=False)
    pad = max(3, size // 4)
    w, h = label.get_width() + pad, label.get_height() + 2
    surf = pygame.Surface((w, h), pygame.SRCALPHA)
    pygame.draw.rect(surf, (*colour, 235), (0, 0, w, h), border_radius=h // 2)
    surf.blit(label, ((w - label.get_width()) // 2, 1))
    return surf


def chip_tip(h: int) -> int:
    return max(4, h // 3)


def chip_rects(points, sizes, radii, cam, w: int, h: int) -> list[tuple[int, int, int, int, str]]:
    """Where each name chip goes, as (x, y, w, h, pointer): above its marble
    pointing down; for a marble the camera has out of view, at that edge
    pointing toward it. Always inside the frame and clear of the right-hand
    strip Shorts covers; nudged past any chip it would overlap."""
    z, x0, y0 = cam
    placed: list[tuple[float, float, float, float]] = []
    screen = [((px - x0) * z, (py - y0) * z) for px, py in points]
    inside = [0 <= sx <= w for sx, _ in screen]
    # Chips over a marble in view first, lowest marble first; then the edge
    # chips, which slide along their edge — and off any marble in view,
    # since a chip parked on one reads as that marble's name.
    order = sorted(range(len(points)), key=lambda i: (not inside[i], -screen[i][1]))
    discs = [(sx, sy, radii[i] * z) for i, (sx, sy) in enumerate(screen) if inside[i]]
    rects: dict[int, tuple[int, int, int, int, str]] = {}
    left, right, top, bottom = w * 0.02, w * 0.86, h * 0.09, h * 0.80

    def clash(x, y, cw, ch, tip, edge):
        for r in placed:
            if x < r[0] + r[2] and r[0] < x + cw and y < r[1] + r[3] + tip and r[1] < y + ch + tip:
                return r
        if edge:
            for dx, dy, dr in discs:
                if x - dr < dx < x + cw + dr and y - dr < dy < y + ch + dr:
                    return (dx - dr, dy - dr, 2 * dr, 2 * dr)
        return None

    for i in order:
        cw, ch = sizes[i]
        tip = chip_tip(ch)
        sx, sy = screen[i]
        if sx < 0:
            pointer, x, y = "left", left + tip, sy - ch / 2
        elif sx > w:
            pointer, x, y = "right", right - cw - tip, sy - ch / 2
        else:
            pointer = "down"
            x = min(max(sx - cw / 2, left + tip), right - cw - tip)
            y = sy - radii[i] * z - ch - tip - 1
        y = min(max(y, top), bottom - ch - tip)
        edge = pointer != "down"
        for _ in range(3 * len(points)):
            hit = clash(x, y, cw, ch, tip, edge)
            if hit is None:
                break
            if edge:
                y = hit[1] + hit[3] + tip + 2      # along the edge, downward
                if y > bottom - ch - tip:
                    y = min(max(sy - ch / 2, top), bottom - ch - tip)
                    break
            else:
                y = hit[1] - ch - tip - 2
                if y < top:
                    y = hit[1] + hit[3] + tip + 2
        placed.append((x, y, cw, ch))
        rects[i] = (int(x), int(y), int(cw), int(ch), pointer)
    return [rects[i] for i in range(len(points))]


def _chips(pygame, surface, v: View, chips, points, cam, w, h, alpha: float, frame: int) -> None:
    if alpha <= 0.01:
        return
    shown = [i for i in range(len(v.names)) if not hidden(v.mech, v.names[i], frame)]
    rects = chip_rects([points[i] for i in shown], [chips[i].get_size() for i in shown],
                       [v.radii[i] for i in shown], cam, w, h)
    for i, (x, y, cw, ch, pointer) in zip(shown, rects):
        tip = chip_tip(ch)
        layer = pygame.Surface((cw + 2 * tip, ch + 2 * tip), pygame.SRCALPHA)
        layer.blit(chips[i], (tip, tip))
        col = (*v.colours[i], 235)
        if pointer == "down":
            m = tip + cw / 2
            pygame.draw.polygon(layer, col, [(m - tip, tip + ch - 1), (m + tip, tip + ch - 1), (m, tip + ch + tip - 1)])
        elif pointer == "left":
            m = tip + ch / 2
            pygame.draw.polygon(layer, col, [(tip + 1, m - tip), (tip + 1, m + tip), (1, m)])
        else:
            m = tip + ch / 2
            pygame.draw.polygon(layer, col, [(tip + cw - 1, m - tip), (tip + cw - 1, m + tip), (tip + cw + tip - 1, m)])
        layer.set_alpha(int(255 * alpha))
        surface.blit(layer, (x - tip, y - tip))


def _tower(pygame, surface, lay, v: View, order, order_y, labels, ranks, fade: float) -> None:
    if fade <= 0.01:
        return
    tx, ty, tw, th = lay["tower"]
    panel = pygame.Surface((tw, th), pygame.SRCALPHA)
    pygame.draw.rect(panel, (8, 8, 14, int(120 * fade)), (0, 0, tw, th), border_radius=8)
    surface.blit(panel, (tx, ty))
    row_h = lay["row_h"]
    gone = v.mech.get("gone") or {}
    for r, i in enumerate(order):
        x, y0, _, _ = lay["rows"][0]
        y = y0 + order_y[i] * row_h
        dot = row_h * 0.30
        dim = 0.4 if v.names[i] in gone else 1.0
        col = tuple(int(c * dim) for c in v.colours[i])
        rank = ranks[r].copy()
        rank.set_alpha(int(255 * fade * dim))
        surface.blit(rank, (x + 2, int(y + (row_h - rank.get_height()) / 2)))
        cxd = x + row_h * 0.62 + dot
        layer = pygame.Surface((int(dot * 2 + 4), int(dot * 2 + 4)), pygame.SRCALPHA)
        pygame.draw.circle(layer, (*col, int(255 * fade)), (int(dot + 2), int(dot + 2)), int(dot))
        surface.blit(layer, (int(cxd - dot - 2), int(y + row_h / 2 - dot - 2)))
        lab = labels[i].copy()
        lab.set_alpha(int(255 * fade * dim))
        surface.blit(lab, (int(cxd + dot + 5), int(y + (row_h - lab.get_height()) / 2)))


def progress(v: View, s: float, i: int, y_start: float) -> float:
    if v.finish_y is None:
        return 0.0
    i0 = min(len(v.states) - 1, int(s))
    line = v.finish_y + v.radii[i]
    if v.finishes.get(v.names[i]) is not None and v.finishes[v.names[i]] <= s:
        return 1.0
    y = float(v.states[i0][i][1])
    return min(1.0, max(0.0, (y_start - y) / max(1.0, y_start - line)))


def _bar(pygame, fx, surface, lay, v: View, order, s: float, y_start: float, fade: float) -> None:
    if v.finish_y is None or fade <= 0.01:
        return
    bx, by, bw, bh = lay["bar"]
    lead = order[0]
    p = progress(v, s, lead, y_start)
    layer = pygame.Surface((bw + bh * 2, bh * 3), pygame.SRCALPHA)
    pygame.draw.rect(layer, (255, 255, 255, int(60 * fade)), (bh, bh, bw, bh), border_radius=bh // 2)
    fill = max(bh, int(bw * p))
    pygame.draw.rect(layer, (*v.colours[lead], int(255 * fade)), (bh, bh, fill, bh), border_radius=bh // 2)
    pygame.draw.circle(layer, (*v.colours[lead], int(255 * fade)), (bh + fill, int(bh * 1.5)), int(bh * 1.4))
    surface.blit(layer, (bx - bh, by - bh))


def slam_scale(t: float, width: float, w: int) -> float:
    """1.4 -> 1.0 with a small overshoot over SLAM_S; never wider than the frame."""
    top = min(SLAM_FROM, (w * 0.98) / max(1.0, width))
    if t >= SLAM_S:
        return 1.0
    u = t / SLAM_S
    c1 = 1.70158
    back = 1 + (c1 + 1) * (u - 1) ** 3 + c1 * (u - 1) ** 2  # ease-out-back: 0 -> ~1.1 -> 1
    return top + (1.0 - top) * back


def _slam(pygame, surface, cap, cx: float, cy: float, frame: int, last: int, fps: int, w: int) -> None:
    if frame >= last:
        return
    sc = slam_scale(frame / fps, cap.get_width(), w)
    out = max(0.0, min(1.0, (last - frame) / max(1.0, 0.25 * fps)))
    img = cap if abs(sc - 1.0) < 1e-3 else pygame.transform.smoothscale(
        cap, (max(1, int(cap.get_width() * sc)), max(1, int(cap.get_height() * sc))))
    if out < 1.0:
        img = img.copy()
        img.set_alpha(int(255 * out))
    surface.blit(img, (int(cx - img.get_width() / 2), int(cy - img.get_height() / 2)))
