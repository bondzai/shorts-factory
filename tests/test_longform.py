"""Long-form: redrawn from traces, with chapters and a table, never concatenated shorts."""

import numpy as np
import pytest

from factory import channels, db
from factory.series import longform, season as season_mod, standings, trace

FPS, SIM_W, SIM_H, FRAMES = 15, 54, 96, 30

SEASON = """
id: s0
title: Season 0
channel: main
levels:
  - {id: L01, date: 2026-09-25, world: foundations, params: {stage: zigzag}, entrants: [blaze, tide]}
  - {id: L02, date: 2026-09-26, world: foundations, params: {stage: funnels}, entrants: [blaze, tide]}
"""


def redraw(meta, trace_dir):
    arrays, _ = trace.read(trace_dir)
    for _ in range(arrays["round0_positions"].shape[0]):
        yield bytes([int(meta["seed"]) % 255]) * (SIM_W * SIM_H * 3)


@pytest.fixture
def season(sandbox, monkeypatch):
    table = {"L01": [], "L02": [{"entrant_id": "blaze", "name": "Blaze", "points": 3, "wins": 1, "races": 1},
                                {"entrant_id": "tide", "name": "Tide", "points": 2, "wins": 0, "races": 1}]}
    monkeypatch.setattr(standings, "table", lambda conn, ch, s, *, before_level=None: table.get(before_level, table["L02"]))
    (sandbox / "channels" / "main" / "season").mkdir(parents=True)
    (sandbox / "channels" / "main" / "season" / "s0.yaml").write_text(SEASON)
    with db.connect() as conn:
        channels.create(conn, name="Main", channel_id="main")
        for n, level in enumerate(("L01", "L02")):
            d = sandbox / "data" / "work" / "main" / level
            positions = np.zeros((FRAMES, 2, 2))
            trace.write(d, {"round0_positions": positions, "radii": np.array([5.0, 5.0]),
                            "colors": np.array([[232, 76, 74], [55, 138, 221]], dtype=np.uint8)},
                        {"generator": "fakegen", "variant": "race", "seed": 40 + n, "fps": FPS,
                         "sim_w": SIM_W, "sim_h": SIM_H, "entrant_ids": ["blaze", "tide"],
                         "rounds": [{"impacts": [[0.5, 0.8, 0, 0.0]]}]})
            cid = db.insert_clip(conn, channel_id="main", generator="fakegen", variant="race", seed=40 + n,
                                 params={}, hook="", plan_why="t")
            db.update(conn, cid, status="approved", title=f"Race {level}", level_id=level,
                      trace_path=str(d / "trace.json"))
    return season_mod.load("main")


def test_a_tournament_has_a_card_a_race_and_a_table_per_level(season):
    with db.connect() as conn:
        out = longform.render(conn, "main", season, ["L01", "L02"], "tournament", redraw=redraw, preset="ultrafast")
    per_level = longform.CARD_S + FRAMES / FPS + longform.TABLE_S
    assert out["duration_s"] == pytest.approx(2 * per_level, abs=0.3)
    chapters = out["chapters"].read_text().splitlines()
    assert chapters[0].startswith("00:00 L01") and chapters[1].startswith(f"00:{int(per_level):02d} L02")
    text = out["description"].read_text()
    assert "1. Blaze — 3 pts" in text and "00:00 L01" in text
    from factory import render
    info = render.probe(out["video"])
    assert (info["width"], info["height"]) == (1920, 1080)


def test_a_level_without_an_approved_trace_is_refused(season):
    with db.connect() as conn:
        conn.execute("UPDATE clips SET status = 'awaiting_approval' WHERE level_id = 'L02'")
        conn.commit()
        with pytest.raises(ValueError, match="L02 has no approved clip"):
            longform.render(conn, "main", season, ["L01", "L02"], "tournament", redraw=redraw)


def test_sleep_is_not_built(season):
    with db.connect() as conn, pytest.raises(ValueError, match="sleep"):
        longform.render(conn, "main", season, ["L01"], "sleep", redraw=redraw)


def test_stamps_read_like_youtube_chapters():
    assert longform.stamp(0) == "00:00" and longform.stamp(754.9) == "12:34" and longform.stamp(3725) == "1:02:05"
