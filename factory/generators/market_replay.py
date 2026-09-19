"""Market replay generator — candles forming, one bar at a time.

The data is a plug, not a hard-coded feed, and the clip says which kind it got.

  Real bars      drop a CSV at data/market/<name>.csv with the columns
                 time,open,high,low,close,volume. Use data you have the right
                 to redistribute as a rendered chart: an exchange's daily bars,
                 or your own recorded feed. The clip's description then names
                 the file and the date range, and a title may reference the real
                 event.

  Simulated      with no CSV, bars are generated from the seed. The clip is
                 marked synthetic in its facts and its description says so in
                 the first sentence, because the description is what the title
                 is written from. A chart of invented data captioned as a real
                 crash is a lie told to a viewer who cannot check, and no amount
                 of "it's just b-roll" makes that not so.

Nothing here is advice, and nothing claims to be current.
"""

from __future__ import annotations

import csv
import math
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from PIL import Image, ImageDraw

from .. import audio, render, settings
from .base import GeneratedClip, register

WINDOW = 46  # bars visible at once; the series scrolls through it
BARS_PER_SECOND = 4.0

UP = (124, 196, 128)
DOWN = (226, 92, 90)
GRID = (42, 44, 56)
INK = (232, 232, 239)
DIM = (120, 122, 140)
BACKGROUND = (14, 15, 21)


@dataclass
class Bar:
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass
class Series:
    bars: list[Bar]
    label: str
    synthetic: bool
    source: str


def data_dir() -> Path:
    return settings.load().db_path.parent / "market"


def available_series() -> list[str]:
    directory = data_dir()
    if not directory.exists():
        return []
    return sorted(p.stem for p in directory.glob("*.csv"))


def load_csv(path: Path) -> Series:
    bars: list[Bar] = []
    with open(path, newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            try:
                bars.append(
                    Bar(
                        open=float(row["open"]),
                        high=float(row["high"]),
                        low=float(row["low"]),
                        close=float(row["close"]),
                        volume=float(row.get("volume") or 0.0),
                    )
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError(f"{path.name}: {exc}") from None
    if len(bars) < WINDOW:
        raise ValueError(f"{path.name}: needs at least {WINDOW} bars, found {len(bars)}")
    return Series(bars=bars, label=path.stem, synthetic=False, source=path.name)


def synthesise(rng: random.Random, variant: str, count: int) -> Series:
    """A random walk with the shape the variant is named for.

    Deliberately not modelled on any real instrument. It is a plausible-looking
    line, and the clip says as much.
    """
    price = rng.uniform(80.0, 240.0)
    drift = rng.uniform(-0.0006, 0.0010)
    vol = rng.uniform(0.006, 0.016)
    shock_at = int(count * rng.uniform(0.55, 0.75))

    bars: list[Bar] = []
    for i in range(count):
        step = rng.gauss(drift, vol)
        if variant == "crash_replay" and shock_at <= i < shock_at + max(3, count // 14):
            step -= abs(rng.gauss(0.03, 0.02))
        elif variant == "final_hour" and i >= shock_at:
            step += rng.gauss(0.004, vol * 1.4)
        open_ = price
        close = max(0.5, price * (1.0 + step))
        spread = abs(close - open_) + price * abs(rng.gauss(0.0, vol * 0.6))
        high = max(open_, close) + spread * rng.uniform(0.1, 0.7)
        low = min(open_, close) - spread * rng.uniform(0.1, 0.7)
        volume = abs(rng.gauss(1.0, 0.45)) + abs(step) * 28
        bars.append(Bar(open_, high, max(0.1, low), close, volume))
        price = close
    return Series(bars=bars, label="simulated series", synthetic=True, source="synthetic")


class MarketReplay:
    name = "market_replay"
    variants = ["crash_replay", "final_hour"]
    ready = True
    blurb = (
        "Candles forming one bar at a time with a volume panel underneath. "
        "crash_replay builds to a fall, final_hour to a climb. Reads real bars "
        "from data/market/*.csv when present, otherwise a simulated series. A "
        "simulated one is marked in the clip's facts and description; there is "
        "no text on screen either way."
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
        seconds = float(params.get("seconds", 15.0))
        frames_total = int(seconds * fps)
        bar_count = int(seconds * BARS_PER_SECOND) + WINDOW

        rng = random.Random(seed)
        wanted = params.get("series")
        series = self._pick_series(rng, variant, bar_count, wanted)

        states, impacts = self._script(series, frames_total, fps, sim_w)
        duration_s = len(states) / fps

        work_dir.mkdir(parents=True, exist_ok=True)
        wav = audio.render_wav(impacts, duration_s, work_dir / "audio.wav")
        silent = render.encode_frames(
            self._frames(series, states, sim_w, sim_h),
            out_path=work_dir / "video.mp4",
            src_size=(sim_w, sim_h),
            out_size=(out_w, out_h),
            fps=fps,
        )
        final = render.mux(silent, wav, work_dir / "clip.mp4")

        first, last = series.bars[0].close, series.bars[-1].close
        move = (last - first) / first * 100
        if series.synthetic:
            description = (
                f"A simulated price series, not real market data: {len(series.bars)} "
                f"candles form one at a time with a volume panel underneath, "
                f"{'falling' if move < 0 else 'rising'} {abs(move):.1f}% from the "
                f"first bar to the last over {duration_s:.1f} seconds."
            )
        else:
            description = (
                f"{len(series.bars)} candles from {series.source} form one at a "
                f"time with a volume panel underneath, "
                f"{'falling' if move < 0 else 'rising'} {abs(move):.1f}% from the "
                f"first bar to the last over {duration_s:.1f} seconds."
            )

        return GeneratedClip(
            video_path=final,
            duration_s=duration_s,
            description=description,
            facts={
                "variant": variant,
                "seed": seed,
                "bars": len(series.bars),
                "synthetic": series.synthetic,
                "source": series.source,
                "move_pct": round(move, 2),
                "impacts": len(impacts),
            },
        )

    def _pick_series(
        self, rng: random.Random, variant: str, count: int, wanted: str | None
    ) -> Series:
        names = available_series()
        if wanted:
            path = data_dir() / f"{wanted}.csv"
            if not path.exists():
                raise ValueError(f"no series {wanted!r}; have {names or 'none'}")
            return load_csv(path)
        if names:
            return load_csv(data_dir() / f"{rng.choice(names)}.csv")
        return synthesise(rng, variant, count)

    def _script(self, series: Series, frames_total: int, fps: int, sim_w: int):
        """One state per frame: how many bars are revealed, and the sounds."""
        total = len(series.bars)
        states, impacts = [], []
        revealed_before = WINDOW
        for frame in range(frames_total):
            progress = (frame + 1) / frames_total
            revealed = min(total, WINDOW + int((total - WINDOW) * progress))
            states.append(revealed)
            if revealed > revealed_before:
                bar = series.bars[revealed - 1]
                window = series.bars[max(0, revealed - WINDOW) : revealed]
                high = max(b.high for b in window)
                low = min(b.low for b in window)
                span = max(high - low, 1e-6)
                # Pitch follows where the close sits in the visible range, so a
                # falling market audibly descends.
                position = (bar.close - low) / span
                volumes = [b.volume for b in window] or [1.0]
                loudest = max(volumes) or 1.0
                impacts.append(
                    audio.Impact(
                        t=frame / fps,
                        strength=min(1.0, 0.25 + 0.75 * bar.volume / loudest),
                        index=int(position * 5.99),
                        pan=(revealed % 7) / 6.0 * 2 - 1,
                    )
                )
                revealed_before = revealed
        return states, impacts

    def _frames(self, series: Series, states, sim_w: int, sim_h: int) -> Iterator[bytes]:
        chart_top, chart_bottom = sim_h * 0.20, sim_h * 0.62
        vol_top, vol_bottom = sim_h * 0.66, sim_h * 0.78
        left, right = sim_w * 0.06, sim_w * 0.94

        for revealed in states:
            image = Image.new("RGB", (sim_w, sim_h), BACKGROUND)
            draw = ImageDraw.Draw(image)
            window = series.bars[max(0, revealed - WINDOW) : revealed]
            if not window:
                yield image.tobytes()
                continue

            high = max(b.high for b in window)
            low = min(b.low for b in window)
            span = max(high - low, 1e-6)
            loudest = max((b.volume for b in window), default=1.0) or 1.0

            for i in range(5):
                y = chart_top + (chart_bottom - chart_top) * i / 4
                draw.line([(left, y), (right, y)], fill=GRID, width=1)

            slot = (right - left) / len(window)
            body = max(2.0, slot * 0.62)
            for i, bar in enumerate(window):
                cx = left + slot * (i + 0.5)
                colour = UP if bar.close >= bar.open else DOWN

                def price_y(value: float) -> float:
                    return chart_bottom - (value - low) / span * (chart_bottom - chart_top)

                draw.line(
                    [(cx, price_y(bar.high)), (cx, price_y(bar.low))],
                    fill=colour, width=max(1, int(body * 0.16)),
                )
                top = price_y(max(bar.open, bar.close))
                bottom = price_y(min(bar.open, bar.close))
                if bottom - top < 1.5:
                    bottom = top + 1.5
                draw.rectangle(
                    [cx - body / 2, top, cx + body / 2, bottom], fill=colour
                )

                height = (bar.volume / loudest) * (vol_bottom - vol_top)
                draw.rectangle(
                    [cx - body / 2, vol_bottom - height, cx + body / 2, vol_bottom],
                    fill=tuple(int(c * 0.55) for c in colour),
                )

            last = window[-1]
            y = chart_bottom - (last.close - low) / span * (chart_bottom - chart_top)
            draw.line([(left, y), (right, y)], fill=DIM, width=1)
            marker = UP if last.close >= last.open else DOWN
            draw.rectangle([right - 6, y - 3, right, y + 3], fill=marker)
            yield image.tobytes()


register(MarketReplay())
