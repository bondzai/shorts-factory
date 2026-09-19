"""Market replay generator — slot two, not built yet.

The shape is deliberate: this module is the whole difference between one channel
and two. Everything downstream of `generate` already works, so filling this in
is a day of work, not a new pipeline.

To finish it:
  1. Pick a data source with terms that allow redistribution of a rendered
     chart (exchange daily/minute bars, or your own recorded feed). Cache the
     bars in data/market/ keyed by symbol and window so renders stay
     deterministic for a given seed.
  2. Render candles + a depth or volume panel into PIL frames the same way
     physics.py does, animating the window forward one bar per frame.
  3. Derive audio from the bars: a transient per bar whose pitch tracks the
     close and whose strength tracks volume. audio.Impact already fits.
  4. Set ready = True. Nothing else in the pipeline changes.

Do not render a symbol's live price and imply it is current, and do not present
any of this as advice or a signal — put the date range on screen.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .base import GeneratedClip, register


class MarketReplay:
    name = "market_replay"
    variants = ["crash_replay", "final_hour"]
    ready = False
    blurb = (
        "Historical price action animated as candles with a volume panel. "
        "Finance audience, highest ad rates. Not implemented yet."
    )

    def generate(
        self, *, seed: int, variant: str, params: dict[str, Any], work_dir: Path
    ) -> GeneratedClip:
        raise NotImplementedError(
            "market_replay is a stub: see the module docstring for the four steps"
        )


register(MarketReplay())
