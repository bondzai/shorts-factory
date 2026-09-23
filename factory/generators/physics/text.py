"""The words the render itself puts on screen, and what it says it showed.

The opening caption, the closing ask, and the plain-language account of the
stage that the Metadata agent writes a title from.
"""

from __future__ import annotations

import random

from PIL import Image, ImageDraw

from ... import settings
from .registry import STAGE_BY_ID

def stage_text(r) -> str:
    style, segments = r["style"], r["segments"]
    obstacles = len(style.circles) or len(segments)
    base = STAGE_BY_ID[style.stage].describe(style, segments)
    if style.spinners:
        base += f" with {len(style.spinners)} spinning bar{'s' if len(style.spinners) > 1 else ''}"
    if style.gates:
        base += " and a throat in the run-in to the line"
    return base


def default_hook(variant: str, round_: dict | None) -> str:
    """The opening caption: two or three words that make the viewer pick a
    marble. Not the result, and not the stage's spec sheet either —
    "PICK ONE · 4 SPINNERS" made a viewer read arithmetic in the one
    second they give us. The pick is the whole job: a viewer who has
    chosen a side stays to see it lose or win.

    The bank lives in config (overlay.marble_race, captions separated by
    "|"), so the operator edits it on the Settings page; one is chosen
    per seed so consecutive clips do not open on the same words.
    """
    cfg = settings.load().raw.get("overlay", {})
    bank = [c.strip() for c in str(cfg.get(variant) or "").split("|") if c.strip()]
    if not bank:
        return ""
    if variant == "marble_race" and round_ and len(bank) > 1:
        seed = getattr(round_["style"], "seed", 0) or 0
        return bank[random.Random(seed).randrange(len(bank))]
    return bank[0]

def closing_ask(sim_w: int, sim_h: int, fps: int):
    """What the clip asks for once the result is in.

    The opening caption asks the viewer to pick; this asks them to say
    what they picked, and it runs in the second the race keeps going
    after the winner crosses, where there is nothing left to give away
    and nothing left to compete with.
    """
    cfg = settings.load().raw.get("overlay", {})
    text = str(cfg.get("cta") or "").strip()
    seconds = float(cfg.get("cta_seconds", 0) or 0)
    if not text or seconds <= 0:
        return None
    from ...brand import _font  # lazily: brand reads this package's palette

    probe = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    size = int(sim_w * float(cfg.get("size", 0.072)) * 0.8)
    while True:
        font = _font(size)
        width = probe.textlength(text, font=font)
        if width <= sim_w * 0.90 or size <= 12:
            break
        size -= 2
    return text, font, (sim_w - width) / 2, sim_h * 0.30, int(seconds * fps)

def overlay(variant: str, sim_w: int, sim_h: int, fps: int, text: str | None = None):
    """Opening caption, or None. Returns (text, font, x, y, last_frame)."""
    cfg = settings.load().raw.get("overlay", {})
    if text is None:
        text = (cfg.get(variant) or "").strip()
    if not text:
        return None
    from ...brand import _font  # lazily: brand reads this package's palette

    probe = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    # Shrink until it fits: "FINAL · GREEN TOOK THE HEAT" at the race's
    # caption size ran off both edges of the frame.
    size = int(sim_w * float(cfg.get("size", 0.072)))
    while True:
        font = _font(size)
        text_width = probe.textlength(text, font=font)
        if text_width <= sim_w * 0.90 or size <= 14:
            break
        size -= 2
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
