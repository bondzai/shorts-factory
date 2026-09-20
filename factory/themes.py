"""Seasons, as data the page can edit.

A theme is colours, marble names and a decoration, with an optional window in
the calendar. The active theme is: whatever is forced on the Settings screen;
else the theme whose window contains today; else the default. Nothing else in
the factory knows what month it is.

Marble names matter beyond looks: they end up in descriptions, facts and
titles ("the gold marble reaches the bottom first"), so a theme's names are
words a viewer would use, and a colour that vanishes against the backdrop is
not offered.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from . import settings

DECORATIONS = ("none", "snow", "embers", "sparks", "drops")

DEFAULT_THEMES: list[dict[str, Any]] = [
    {
        "id": "default", "name": "Default", "decoration": "none", "window": None,
        "palettes": [[[18, 18, 26], [58, 58, 74]], [[22, 24, 29], [65, 71, 79]], [[23, 18, 28], [67, 58, 77]],
                     [[16, 26, 22], [52, 71, 63]], [[14, 17, 24], [51, 60, 74]], [[26, 20, 17], [74, 60, 50]]],
        "marbles": [["red", [232, 76, 74]], ["blue", [55, 138, 221]], ["amber", [239, 159, 39]],
                    ["green", [151, 196, 89]], ["violet", [150, 122, 224]]],
        "caption": [255, 255, 255],
    },
    {
        "id": "halloween", "name": "Halloween", "decoration": "embers", "window": ["10-15", "10-31"],
        "palettes": [[[20, 12, 26], [96, 54, 124]], [[14, 10, 18], [122, 72, 32]], [[16, 14, 22], [70, 40, 90]]],
        "marbles": [["orange", [255, 140, 30]], ["purple", [156, 96, 224]], ["green", [124, 222, 92]],
                    ["white", [240, 240, 232]], ["red", [220, 50, 50]]],
        "caption": [255, 160, 60],
    },
    {
        "id": "christmas", "name": "Christmas", "decoration": "snow", "window": ["12-01", "12-26"],
        "palettes": [[[12, 30, 20], [178, 42, 52]], [[10, 20, 32], [200, 170, 80]], [[16, 24, 22], [90, 140, 100]]],
        "marbles": [["red", [225, 50, 60]], ["green", [64, 172, 92]], ["gold", [240, 200, 80]],
                    ["white", [245, 245, 240]], ["blue", [70, 130, 220]]],
        "caption": [245, 245, 240],
    },
    {
        "id": "newyear", "name": "New Year", "decoration": "sparks", "window": ["12-27", "01-03"],
        "palettes": [[[10, 10, 20], [220, 190, 90]], [[12, 12, 18], [160, 160, 180]]],
        "marbles": [["gold", [240, 200, 80]], ["silver", [200, 205, 215]], ["red", [225, 60, 70]],
                    ["blue", [80, 140, 230]], ["violet", [160, 120, 230]]],
        "caption": [240, 200, 80],
    },
    {
        "id": "valentine", "name": "Valentine", "decoration": "none", "window": ["02-07", "02-14"],
        "palettes": [[[28, 12, 20], [190, 70, 110]], [[24, 14, 18], [220, 120, 150]]],
        "marbles": [["pink", [245, 120, 170]], ["red", [225, 50, 70]], ["white", [245, 240, 242]],
                    ["rose", [200, 80, 120]], ["gold", [240, 200, 100]]],
        "caption": [245, 160, 190],
    },
    {
        "id": "songkran", "name": "Songkran", "decoration": "drops", "window": ["04-10", "04-16"],
        "palettes": [[[8, 22, 34], [60, 150, 200]], [[10, 26, 30], [90, 190, 190]]],
        "marbles": [["blue", [60, 150, 240]], ["cyan", [80, 210, 220]], ["white", [240, 248, 250]],
                    ["yellow", [245, 220, 80]], ["green", [90, 200, 120]]],
        "caption": [200, 235, 250],
    },
]


@dataclass(frozen=True)
class Theme:
    id: str
    name: str
    palettes: tuple[tuple[tuple[int, int, int], tuple[int, int, int]], ...]
    marbles: tuple[tuple[str, tuple[int, int, int]], ...]
    caption: tuple[int, int, int]
    decoration: str = "none"
    window: tuple[str, str] | None = None
    enabled: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "name": self.name, "decoration": self.decoration,
            "window": list(self.window) if self.window else None, "enabled": self.enabled,
            "palettes": [[list(a), list(b)] for a, b in self.palettes],
            "marbles": [[n, list(c)] for n, c in self.marbles],
            "caption": list(self.caption),
        }


def _rgb(value: Any, what: str) -> tuple[int, int, int]:
    try:
        r, g, b = (int(v) for v in value)
    except (TypeError, ValueError):
        raise ValueError(f"{what}: a colour is three numbers 0-255") from None
    if not all(0 <= v <= 255 for v in (r, g, b)):
        raise ValueError(f"{what}: a colour is three numbers 0-255")
    return (r, g, b)


def _mmdd(value: str, what: str) -> str:
    try:
        month, day = (int(x) for x in str(value).split("-"))
        date(2024, month, day)
    except (TypeError, ValueError):
        raise ValueError(f"{what}: dates are MM-DD") from None
    return f"{month:02d}-{day:02d}"


def from_dict(raw: dict[str, Any]) -> Theme:
    tid = str(raw.get("id") or "").strip()
    if not tid:
        raise ValueError("a theme needs an id")
    if raw.get("decoration", "none") not in DECORATIONS:
        raise ValueError(f"{tid}: decoration must be one of {DECORATIONS}")
    palettes = raw.get("palettes") or []
    marbles = raw.get("marbles") or []
    if not palettes:
        raise ValueError(f"{tid}: at least one palette (background, structure)")
    if len(marbles) < 3:
        raise ValueError(f"{tid}: at least three named marbles — a race needs runners")
    names = [str(n).strip().lower() for n, _ in marbles]
    if len(set(names)) != len(names) or not all(names):
        raise ValueError(f"{tid}: marble names must be distinct words")
    window = raw.get("window") or None
    if window:
        window = (_mmdd(window[0], tid), _mmdd(window[1], tid))
    return Theme(
        id=tid, name=str(raw.get("name") or tid), decoration=raw.get("decoration", "none"),
        window=window, enabled=bool(raw.get("enabled", True)),
        palettes=tuple((_rgb(a, tid), _rgb(b, tid)) for a, b in palettes),
        marbles=tuple((n, _rgb(c, tid)) for n, (_, c) in zip(names, marbles)),
        caption=_rgb(raw.get("caption") or [255, 255, 255], tid),
    )


def themes() -> list[Theme]:
    raw = settings.load().raw.get("themes", {}).get("list") or DEFAULT_THEMES
    out = [from_dict(t) for t in raw]
    if not any(t.id == "default" for t in out):
        out.insert(0, from_dict(DEFAULT_THEMES[0]))
    return out


def get(theme_id: str) -> Theme:
    for t in themes():
        if t.id == theme_id:
            return t
    raise ValueError(f"no theme {theme_id!r}; have {[t.id for t in themes()]}")


def in_window(window: tuple[str, str] | None, today: date) -> bool:
    if not window:
        return False
    start, end = window
    key = f"{today.month:02d}-{today.day:02d}"
    if start <= end:
        return start <= key <= end
    return key >= start or key <= end  # wraps the year end


def active(today: date | None = None) -> Theme:
    """Forced on the page, else today's season, else default."""
    today = today or date.today()
    force = (settings.load().raw.get("themes", {}).get("force") or "").strip()
    if force:
        return get(force)
    for t in themes():
        if t.enabled and t.id != "default" and in_window(t.window, today):
            return t
    return get("default")
