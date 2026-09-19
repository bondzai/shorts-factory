import random
import statistics

import pytest

from factory import settings
from factory.generators import market_replay as mr

BARS = int(15 * mr.BARS_PER_SECOND) + mr.WINDOW


def write_csv(sandbox, name, rows):
    directory = settings.load().db_path.parent / "market"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{name}.csv"
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("time,open,high,low,close,volume\n")
        for i, (o, h, l, c, v) in enumerate(rows):
            handle.write(f"{i},{o},{h},{l},{c},{v}\n")
    return path


def bars(n=mr.WINDOW + 5, start=100.0):
    out, price = [], start
    for i in range(n):
        close = price * 1.01
        out.append((price, close * 1.01, price * 0.99, close, 1000 + i))
        price = close
    return out


# --- the honesty guarantee ----------------------------------------------------

def test_a_simulated_series_says_so_before_anything_else(sandbox):
    """The description is what the title is written from, so the disclaimer has
    to be in it, not only in the facts."""
    series = mr.synthesise(random.Random(1), "crash_replay", BARS)
    assert series.synthetic is True
    assert series.source == "synthetic"


def test_real_bars_are_preferred_when_they_exist(sandbox):
    write_csv(sandbox, "spx-2010-05-06", bars())
    series = mr.MarketReplay()._pick_series(random.Random(1), "crash_replay", BARS, None)
    assert series.synthetic is False
    assert series.source == "spx-2010-05-06.csv"


def test_asking_for_a_series_that_is_not_there_names_what_is(sandbox):
    write_csv(sandbox, "present", bars())
    with pytest.raises(ValueError, match="present"):
        mr.MarketReplay()._pick_series(random.Random(1), "crash_replay", BARS, "absent")


def test_a_csv_too_short_to_fill_the_window_is_refused(sandbox):
    path = write_csv(sandbox, "stub", bars(n=5))
    with pytest.raises(ValueError, match="at least"):
        mr.load_csv(path)


def test_a_malformed_csv_names_the_file(sandbox):
    directory = settings.load().db_path.parent / "market"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "broken.csv"
    path.write_text("time,open,high,low,close,volume\n0,not-a-number,1,1,1,1\n")
    with pytest.raises(ValueError, match="broken.csv"):
        mr.load_csv(path)


# --- the series itself --------------------------------------------------------

def test_the_seed_fixes_the_series(sandbox):
    a = mr.synthesise(random.Random(7), "crash_replay", BARS)
    b = mr.synthesise(random.Random(7), "crash_replay", BARS)
    assert [x.close for x in a.bars] == [x.close for x in b.bars]


def test_different_seeds_give_different_series(sandbox):
    a = mr.synthesise(random.Random(7), "crash_replay", BARS)
    b = mr.synthesise(random.Random(8), "crash_replay", BARS)
    assert [x.close for x in a.bars] != [x.close for x in b.bars]


def test_each_variant_leans_the_way_it_is_named(sandbox):
    """Individually noisy, so this compares the two across many seeds."""
    def mean_move(variant):
        moves = []
        for seed in range(30):
            s = mr.synthesise(random.Random(seed), variant, BARS)
            moves.append((s.bars[-1].close - s.bars[0].close) / s.bars[0].close)
        return statistics.mean(moves)

    assert mean_move("crash_replay") < mean_move("final_hour")


def test_bars_are_internally_consistent(sandbox):
    series = mr.synthesise(random.Random(3), "crash_replay", BARS)
    for bar in series.bars:
        assert bar.high >= max(bar.open, bar.close)
        assert bar.low <= min(bar.open, bar.close)
        assert bar.low > 0
        assert bar.volume >= 0


# --- what gets drawn and heard ------------------------------------------------

def test_one_sound_per_revealed_bar_and_none_past_the_end(sandbox):
    series = mr.synthesise(random.Random(5), "final_hour", BARS)
    fps = 30
    states, impacts = mr.MarketReplay()._script(series, 15 * fps, fps, 540)
    assert len(states) == 15 * fps
    assert states[0] == mr.WINDOW and states[-1] == len(series.bars)
    assert states == sorted(states)
    assert impacts
    assert all(0 <= i.t < 15 for i in impacts)
    assert len(impacts) == len(series.bars) - mr.WINDOW


def test_frames_are_the_right_size_and_count(sandbox):
    series = mr.synthesise(random.Random(5), "crash_replay", BARS)
    fps, w, h = 30, 540, 960
    states, _ = mr.MarketReplay()._script(series, 2 * fps, fps, w)
    frames = list(mr.MarketReplay()._frames(series, states, w, h))
    assert len(frames) == 2 * fps
    assert all(len(f) == w * h * 3 for f in frames)


def test_the_window_scrolls_rather_than_shrinking_the_candles(sandbox):
    """A fixed window is what keeps candles readable on a phone."""
    series = mr.synthesise(random.Random(5), "crash_replay", BARS)
    fps = 30
    states, _ = mr.MarketReplay()._script(series, 5 * fps, fps, 540)
    assert all(s >= mr.WINDOW for s in states)


def test_it_is_registered_and_ready(sandbox):
    from factory import generators

    assert generators.all_generators()["market_replay"].ready is True
    assert "market_replay" in generators.available(None)
