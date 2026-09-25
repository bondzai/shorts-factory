"""Long-form videos from a season's approved races (docs/08 §4 Long-form)."""

from __future__ import annotations

import time

from .. import channels, db
from ..series import longform, season as season_mod


def _levels(text: str) -> list[str]:
    if ".." in text:
        a, b = text.split("..", 1)
        lo, hi = int(a.lstrip("Ll")), int(b.lstrip("Ll"))
        return [f"L{n:02d}" for n in range(lo, hi + 1)]
    return [part.strip().upper() for part in text.split(",") if part.strip()]


def cmd_longform(args) -> int:
    with db.connect() as conn:
        ch = channels.resolve(conn, args.channel)
        season = season_mod.load(ch.id, args.season)
        started = time.monotonic()
        out = longform.render(conn, ch.id, season, _levels(args.levels), args.kind, preset=args.preset)
    wall = time.monotonic() - started
    print(f"{out['video']}\n  {out['duration_s'] / 60:.1f} min of video in {wall / 60:.1f} min "
          f"({out['duration_s'] / max(wall, 1e-6):.1f}x realtime)")
    print(f"  chapters     {out['chapters']}\n  description  {out['description']}")
    return 0


def add(sub) -> None:
    p = sub.add_parser("longform", help="a 16:9 tournament or recap redrawn from approved races' traces")
    p.add_argument("--levels", required=True, help="L01..L10 or L01,L03")
    p.add_argument("--kind", choices=list(longform.KINDS), default="tournament")
    p.add_argument("--season", default=None)
    p.add_argument("--preset", default="faster", help="libx264 preset (default faster)")
    p.set_defaults(func=cmd_longform)
