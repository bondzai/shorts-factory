"""World 7, Harvest Cup: Shrinking Arena (Season 0 L61-L70, and L77): the arena
on the core hooks, the two core options it added (a team arena decided when
one team is left; a last_standing race judged once the field has landed, and
retried when it empties), the camera box it records, and that each ready
level's season params build the arena its copy describes."""

import math
import tomllib
from pathlib import Path

import pytest
import yaml

from factory import settings, stage_qa
from factory.generators import physics
from factory.generators.mechanics import Rig
from factory.generators.physics import present, registry
from factory.generators.physics.worlds import arena

ROOT = Path(__file__).resolve().parent.parent
R5 = ["blaze", "tide", "volt", "moss", "nova"]


def _cast(ids):
    data = tomllib.loads((ROOT / "channels" / "main" / "cast.toml").read_text())
    by = {e["id"]: e for e in data["entrant"]}
    return [{"id": i, "name": by[i]["name"], "color": by[i]["color"], "traits": dict(by[i].get("traits", {}))}
            for i in ids]


def _round(seed, **params):
    params.setdefault("format", "last_standing")
    return physics.run_round(seed, "marble_race", params, settings.load().render, 540, 960, 30)


def _survivor(r):
    return r["winner"] is not None and r["winner"] not in r["gone"]


# --- the arena ---------------------------------------------------------------------------------

@pytest.mark.parametrize("seed", [700, 701, 702])
def test_the_arena_ends_with_one_marble_on_the_floor(sandbox, seed):
    r = _round(seed, section="shrinking-walls", cast=_cast(R5))
    assert _survivor(r) and r["win_by"] == "survival" and r["format"] == "last_standing"
    assert len(r["gone"]) == 4
    mech = r["style"].mech
    assert mech["no_finish"] is True
    # The walls stepped in, and stopped once the race was decided.
    left = mech["clocks"]["arena_left"]
    assert left[-1][1][0] > 0
    assert any(v for _f, v in mech["clocks"]["arena_decided"])


def test_the_floor_behind_a_wall_falls_away_and_the_middle_never_does(sandbox):
    r = _round(700, section="shrinking-walls", cast=_cast(R5))
    mech = r["style"].mech
    tiles = [k for k in mech["clocks"] if k.startswith("arena_tile")]
    assert tiles
    opened = [k for k in tiles if mech["clocks"][k][-1][1] is False]
    assert 0 < len(opened) < len(tiles)


def test_the_walls_wait_is_a_hold_not_a_stall(sandbox):
    rig = Rig(params={"format": "last_standing"})
    style = physics.Style()
    style.rig = rig
    import pymunk
    arena.arena_build("dome")(pymunk.Space(), 540, 960, __import__("random").Random(1), style)
    assert "arena_closing" in rig.holds
    assert rig.unsettled == "arena_unsettled" and rig.survivor_needed


def test_a_team_arena_is_decided_when_one_team_is_left(sandbox):
    teams = {"blaze": 2, "tide": 2, "volt": 2}
    for seed in (700, 701, 702):
        r = _round(seed, section="team-arena", cast=_cast(["blaze", "tide", "volt"]), teams=teams)
        left = [b for b in r["balls"] if b.name not in r["gone"]]
        assert left and len({b.team for b in left}) == 1
        assert r["winner"] in {b.name for b in left}


def test_one_left_is_one_marble_unless_a_team_arena_says_otherwise():
    rig = Rig(params={"format": "last_standing"})
    rig.balls = [type("B", (), {"team": t})() for t in ("a", "a", "b")]
    rig.names = ["a.1", "a.2", "b.1"]
    assert not rig.one_left([0, 1])
    rig.team_survival = True
    assert rig.one_left([0, 1]) and not rig.one_left([0, 2])
    rig.unsettled, rig.values = "air", {"air": True}
    assert not rig.one_left([0])


def test_the_hill_is_held_by_one_marble_when_the_walls_stop(sandbox):
    r = _round(700, section="king-of-the-hill", cast=_cast(R5))
    stops = [(f, d) for f, kind, _i, d in r["mech_events"] if kind == "walls_stopped"]
    assert len(stops) == 1
    f = stops[0][0]
    # Everyone but the holder went out at the stop, by the hill.
    assert sorted(r["gone"].values()) == [f] * 4
    assert _survivor(r)


def test_the_arena_trapdoors_catch_marbles(sandbox):
    caught = 0
    for seed in (700, 701):
        r = _round(seed, section="arena-trapdoors", cast=_cast(R5 + ["acorn", "juniper"]))
        caught += sum(1 for _f, kind, _i, _d in r["mech_events"] if kind == "trap_catch")
        assert _survivor(r)
    assert caught >= 1


def test_pushers_jab_and_launch(sandbox):
    r = _round(700, section="arena-pushers", cast=_cast(R5))
    left = [v[0] for _f, v in r["style"].mech["clocks"]["arena_left"]]
    # A jab goes in and comes back: the wall's offset is not monotonic.
    assert any(b < a for a, b in zip(left, left[1:]))
    assert any(kind == "launched" for _f, kind, _i, _d in r["mech_events"])


def test_the_ice_arena_floor_is_ice_and_the_magnet_sits_under_the_middle(sandbox):
    r = _round(700, section="ice-arena", cast=_cast(R5))
    assert any(z["kind"] == "ice" for z in r["style"].mech["zones"])
    r = _round(700, section="centre-magnet", cast=_cast(R5))
    (mx, my, *_rest), = r["style"].magnets
    assert abs(mx - 270) < 10 and my < 960 * arena.FLOOR_FRAC


def test_the_arena_records_the_box_the_camera_holds(sandbox):
    r = _round(700, section="shrinking-walls", cast=_cast(R5))
    boxes = [v for _f, v in r["style"].mech["clocks"]["view"]]
    widths = [b[2] - b[0] for b in boxes]
    assert widths[-1] < widths[0]
    v = present.view_of(r, {})
    assert v.finish_y is None
    # No line: the tower keeps the ones left in their places.
    assert present.standings(v, 0.0, 0) == list(range(5))


def test_no_lead_changes_are_counted_in_an_arena(sandbox):
    rounds = physics.race_rounds(700, "marble_race", {"section": "shrinking-walls", "format": "last_standing",
                                                       "rounds": 1, "cast": _cast(R5)},
                                 settings.load().render, 540, 960, 30)
    o = physics.race_outcome(rounds, 30, 540)
    assert o.lead_changes == 0 and o.placements[0].entrant_id == rounds[0]["winner"]


def test_the_same_seed_gives_the_same_arena(sandbox):
    a = _round(9, section="arena-pushers", cast=_cast(R5))
    b = _round(9, section="arena-pushers", cast=_cast(R5))
    assert a["states"] == b["states"] and a["style"].mech == b["style"].mech


@pytest.fixture
def no_ffmpeg(sandbox, monkeypatch):
    seen = {"count": 0, "frames": {}}

    def encode_frames(frames, *, out_path, src_size, out_size, fps):
        for i, frame in enumerate(frames):
            seen["frames"][i] = frame if i % 53 == 11 else None
            seen["count"] += 1
        out_path.write_bytes(b"")
        return out_path

    monkeypatch.setattr(physics.sandbox.encoder, "encode_frames", encode_frames)
    monkeypatch.setattr(physics.sandbox.encoder, "mux", lambda video, audio, out: out)
    return seen


def test_an_arena_clip_redraws_to_the_shipped_frames(no_ffmpeg, tmp_path):
    """Walls, tiles, panels and the camera box read off the recording, in both engines."""
    for engine in ("pygame", "pil"):
        settings.load().raw["render"]["engine"] = engine
        no_ffmpeg["frames"].clear()
        no_ffmpeg["count"] = 0
        clip = physics.generate(seed=4, variant="marble_race", work_dir=tmp_path / engine,
                                params={"section": "mega-arena", "format": "last_standing", "rounds": 1,
                                        "teams": {"blaze": 2, "tide": 2}, "cast": _cast(["blaze", "tide", "volt"])})
        redrawn = list(physics.PhysicsSandbox().redraw(clip.trace_path.parent))
        assert len(redrawn) == no_ffmpeg["count"]
        for i, frame in no_ffmpeg["frames"].items():
            if frame is not None:
                assert redrawn[i] == frame, f"{engine} frame {i} differs"


# --- stage QA ---------------------------------------------------------------------------------------

def test_last_standing_gates_ask_for_one_left_every_race(sandbox):
    r = stage_qa.Report(stage="arena", gravity=-300.0, seeds=2, finished=2, first_try=2)
    r.elim_counts, r.last_two, r.decided = [4, 4], [0.1, 0.2], 2
    r.durations = [12.0, 14.0]
    r.wins = {"blaze": 1}
    assert any("one left" in p for p in stage_qa.last_standing_problems(r))
    r.wins = {"blaze": 1, "tide": 1}
    assert stage_qa.last_standing_problems(r) == []


# --- the season -----------------------------------------------------------------------------------

WORLD7 = ("L61", "L62", "L63", "L64", "L65", "L66", "L67", "L68", "L69", "L70")


def _levels():
    path = ROOT / "channels" / "main" / "season" / "s0.yaml"
    return {lv["id"]: lv for lv in yaml.safe_load(path.read_text())["levels"]}


def test_world_seven_levels_and_l77_are_ready_physics_arenas():
    levels = _levels()
    for lid in WORLD7 + ("L77",):
        lv = levels[lid]
        assert lv["status"] == "ready" and lv["blocked_on"] is None
        assert lv["generator"] == "physics" and lv["variant"] == "marble_race"
        assert lv["format"] == "last_standing"
        section = lv["params"]["section"]
        assert section in registry.MECHANICS
        assert lv["params"]["stage"] == registry.MECHANICS[section].stage
        assert lv["params"]["stage"] in registry.STAGE_BY_ID


def test_world_seven_stages_are_trial():
    for sid in ("arena", "arenahill", "arenatrap", "arenaw"):
        assert registry.STAGE_BY_ID[sid].weight == 0


@pytest.mark.parametrize("lid", WORLD7 + ("L77",))
def test_each_world_seven_level_races_from_its_params(sandbox, lid):
    lv = _levels()[lid]
    params = {**lv["params"], "cast": _cast(lv["entrants"]), "format": lv["format"]}
    rounds = physics.race_rounds(700, "marble_race", params, settings.load().render, 540, 960, 30)
    assert len(rounds) == 1 and _survivor(rounds[0])
    n = len(rounds[0]["balls"])
    assert len(rounds[0]["gone"]) >= 1
    assert n == sum((lv["params"].get("teams") or {}).get(e, 1) for e in lv["entrants"])
    assert all(not math.isnan(x) for st in rounds[0]["states"][-1:] for x, _y in st)
