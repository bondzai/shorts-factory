"""World 4, Halloween Cup: Haunted Maze (L31-L38): the maze, the mechanics laid
over it, and the levels they build.

Stage QA is what says the stages race (docs/06, "World 4"). These say each
piece does what its copy claims — a dead end takes a marble out, the lights go
out for about two seconds and come back, a pumpkin stands until it is hit and
then rolls, the web holds the first marble in and tears, the coffin shuts once
it holds one, the time trial shows a par clock — and that all of it is a
function of the seed and redraws to the shipped frames. Where a test needs a
race in which something happens it searches a short, fixed range of seeds.
"""

import math
from pathlib import Path

import pytest
import yaml

from factory import captions, settings
from factory.generators import mechanics, physics, stagekit
from factory.generators.mechanics import clock_at
from factory.generators.physics import registry
from factory.generators.physics.worlds import haunted as w4
from factory.series import trace

CAST = [
    {"id": "blaze", "name": "Blaze", "color": "#E84C4A", "traits": {"friction": 0.10, "mass_mult": 0.88}},
    {"id": "tide", "name": "Tide", "color": "#378ADD", "traits": {"friction": 0.28, "mass_mult": 1.2}},
    {"id": "volt", "name": "Volt", "color": "#F2C230", "traits": {"jitter": 3.0, "radius_mult": 0.95}},
    {"id": "moss", "name": "Moss", "color": "#97C459", "traits": {}},
]
STAGES = ("haunted", "pumpkinpatch", "coffin", "hauntedfinal")
MECHANICS = {"haunted-maze": "haunted", "fog-blackout": "tumble", "rolling-pumpkins": "pumpkinpatch",
             "cobweb-strip": "haunted", "coffin-trapdoor": "coffin", "haunted-maze-final": "hauntedfinal",
             "maze-time-trial": "haunted"}
SEASON = Path(__file__).resolve().parents[1] / "channels/main/season/s0.yaml"
LEVELS = {"L31": "haunted", "L32": "tumble", "L33": "pumpkinpatch", "L34": "haunted", "L36": "coffin",
          "L37": "hauntedfinal", "L38": "haunted"}


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


def _round(seed, cast=CAST, **params):
    return physics.run_round(seed, "marble_race", {"cast": cast, **params}, settings.load().render, 540, 960, 30)


def _kinds(r):
    return [kind for _, kind, _, _ in r["mech_events"]]


def _first(seeds, want, **params):
    for seed in seeds:
        r = _round(seed, **params)
        if want(r):
            return r
    pytest.fail(f"nothing in seeds {seeds.start}..{seeds.stop - 1} did what the test needs")


# --- registered, on trial ------------------------------------------------------------------

def test_every_world4_stage_is_registered_at_weight_zero():
    for stage in STAGES:
        spec = registry.STAGE_BY_ID[stage]
        assert spec.weight == 0 and not spec.live and registry.STAGES[stage] == 0.0
        assert all(name in stagekit.SECTIONS for name, _ in spec.parts)
    for section, stage in MECHANICS.items():
        assert registry.MECHANICS[section].stage == stage
    for name in w4.SECTIONS:
        assert stagekit.SECTIONS[name] is w4.SECTIONS[name] and name in stagekit.SECTION_WORDS


def test_the_world4_levels_name_those_stages_with_hooks_that_pass():
    data = yaml.safe_load(open(SEASON))
    levels = {lv["id"]: lv for lv in (data["levels"] if isinstance(data, dict) else data)}
    for lid, stage in LEVELS.items():
        lv = levels[lid]
        assert lv["status"] in ("ready", "needs_input") and lv["blocked_on"] is None, lid
        assert lv["params"]["stage"] == stage, lid
        assert registry.MECHANICS[lv["params"]["section"]].stage == stage, lid
        assert captions.problem(lv["copy"]["hook"], names=("blaze", "tide", "volt", "moss", "ghost")) is None, lid
    # Who races the semifinal, the final and the solo run is a result: operator
    # input. Season 0 carries stand-in values (notes say so), so they are ready.
    assert all(levels[lid]["status"] in ("ready", "needs_input") for lid in ("L36", "L37", "L38"))


def test_every_world4_level_races_its_rounds_with_its_own_params(sandbox):
    """A second round on a stage without the maze would refuse the mechanic,
    so the heat-and-final levels race both rounds on the same stage and the
    semifinal, the final and the solo run are one race each."""
    from factory.generators.physics.sandbox import race_rounds

    data = yaml.safe_load(open(SEASON))
    levels = {lv["id"]: lv for lv in (data["levels"] if isinstance(data, dict) else data)}
    field = {"L36": CAST[:3], "L37": CAST[1:3], "L38": CAST[3:]}
    for lid in LEVELS:
        lv = levels[lid]
        params = {**lv["params"], "format": lv["format"], "cast": field.get(lid, CAST)}
        rounds = race_rounds(704, "marble_race", params, settings.load().render, 540, 960, 30)
        assert len(rounds) == (1 if lid in field else 2), lid
        assert {r["style"].stage for r in rounds} == {LEVELS[lid]}, lid


def test_a_mechanic_on_a_stage_without_its_geometry_says_so():
    for fn, what in ((w4.haunted_maze, "maze"), (w4.cobweb_strip, "maze"), (w4.maze_time_trial, "maze"),
                     (w4.coffin_trapdoor, "coffin")):
        with pytest.raises(ValueError, match=what):
            fn(mechanics.Rig(), None, None, [], 540, 960)


# --- the maze -----------------------------------------------------------------------------------

def test_the_maze_is_forks_each_with_a_dead_end_on_either_side(sandbox):
    r = _round(700, stage="haunted", section="haunted-maze", format="elimination")
    rows = r["style"].rig.maze
    assert [row["kind"] for row in rows][:3] == ["join", "split", "join"]
    splits = [row for row in rows if row["kind"] == "split"]
    assert splits and all(len(row["forks"]) == 2 for row in splits)
    dead_ends = [z for z in r["style"].mech["zones"] if z["out"]]
    assert len(dead_ends) == 2 * len(splits)
    room = stagekit.marble_room(540)
    for row in splits:
        for fork in row["forks"]:
            assert w4.FORK[0] * room <= fork["gap"] <= w4.FORK[1] * room  # every marble fits the way on


def test_a_dead_end_takes_a_marble_out(sandbox):
    r = _first(range(700, 712), lambda r: "dead_end" in _kinds(r), stage="haunted", section="haunted-maze",
               format="elimination")
    frames = {f for f, kind, _, _ in r["mech_events"] if kind == "dead_end"}
    outs = [(f, d.get("by")) for f, kind, _, d in r["mech_events"] if kind == "eliminated"]
    assert frames <= {f for f, _ in outs} and all(by == "dead_end" for _, by in outs)
    outcome = physics.race_outcome([r], 30, 540)
    assert sum(1 for p in outcome.placements if p.status == "eliminated") == len(r["gone"]) >= 1
    # The copy brain never sees who went into a dead end.
    assert "dead_end" not in {e["kind"] for e in outcome.without_winner()["events"]}


def test_the_same_seed_is_the_same_maze(sandbox):
    a = _round(703, stage="haunted", section="haunted-maze", format="elimination")
    b = _round(703, stage="haunted", section="haunted-maze", format="elimination")
    assert a["style"].mech == b["style"].mech and a["gone"] == b["gone"]


# --- the fog -----------------------------------------------------------------------------------

def test_the_lights_go_out_for_about_two_seconds_and_come_back(sandbox):
    r = _round(701, stage="tumble", section="fog-blackout")
    mech = r["style"].mech
    line = mech["clocks"]["fog"]
    on = [f for f, v in line if v]
    off = [f for f, v in line if f > on[0] and not v]
    assert len(on) == 1 and off, line
    dark = (off[0] - on[0]) / 30
    assert w4.FOG_MIN - 0.05 <= dark <= w4.FOG_MAX + 0.05
    assert mechanics.blackout(mech, on[0] + 3) and not mechanics.blackout(mech, off[0] + 1)
    assert mechanics.hidden(mech, "blaze", on[0] + 3)  # hidden, not gone
    assert not r["gone"] and {"fog_down", "fog_lifted"} <= set(_kinds(r))
    # Sound carries on in the dark.
    assert any(on[0] <= im.t * 30 < off[0] for im in r["impacts"])


# --- the pumpkins --------------------------------------------------------------------------------

def test_a_pumpkin_stands_until_it_is_hit_then_rolls(sandbox):
    r = _round(702, stage="pumpkinpatch", section="rolling-pumpkins")
    mech = r["style"].mech
    props = [e for e in mech["effects"] if e["kind"] == "prop"]
    assert len(props) == 4 and all(e["track"] and e["look"] == "pumpkin" for e in props)
    rolled = {d["pumpkin"]: f for f, kind, _, d in r["mech_events"] if kind == "pumpkin_rolled"}
    assert rolled
    k, f = next(iter(rolled.items()))
    line = mech["clocks"][f"pumpkin{k}"]
    before = [v for g, v in line if g <= f]
    assert len({tuple(v) for v in before}) == 1  # still until it was hit
    later = clock_at(mech, f"pumpkin{k}", f + 45)
    assert later is None or later != before[-1]  # then it moved (or rolled off the bottom)
    # The bumpers it replaced are gone: a pumpkin is not drawn twice.
    assert all((round(x), round(y)) not in {(round(v[0]), round(v[1])) for v in before}
               for x, y, _ in r["style"].circles)
    names = [b.name for b in r["balls"]]
    assert names == ["blaze", "tide", "volt", "moss"]  # never an entrant


def test_a_tracked_prop_is_drawn_where_its_clock_says_by_both_renderers():
    from PIL import Image, ImageDraw

    from factory.generators.physics import render_mech
    from factory.generators.physics.model import Style

    style = Style()
    mech = {"clocks": {"p": [[0, [100.0, 500.0]], [5, [300.0, 400.0]], [9, None]]},
            "effects": [{"kind": "prop", "clock": "p", "track": True, "look": "pumpkin", "radius": 18.0,
                         "color": list(w4.PUMPKIN_COLOUR)}]}
    assert render_mech.props(mech, 2) == [] and render_mech.props(mech, 2, "pumpkin")[0][:2] == (100.0, 500.0)
    assert render_mech.props(mech, 6, "pumpkin")[0][:2] == (300.0, 400.0) and render_mech.props(mech, 9, "pumpkin") == []
    img = Image.new("RGB", (540, 960), style.background)
    render_mech.pil_over(ImageDraw.Draw(img), style, mech, 6, 960, {})
    assert img.getpixel((306, 560)) == w4.PUMPKIN_COLOUR
    import pygame

    surface = pygame.Surface((540, 960))
    surface.fill(style.background)
    render_mech.pg_over(surface, style, mech, 6, 960, {})
    assert tuple(surface.get_at((306, 560)))[:3] != tuple(style.background)


# --- the web ------------------------------------------------------------------------------------

def test_the_web_holds_the_first_marble_in_then_tears(sandbox):
    r = _round(700, stage="haunted", section="cobweb-strip", format="elimination")
    webbed = [(f, i) for f, kind, i, _ in r["mech_events"] if kind == "webbed"]
    assert len(webbed) == 1  # only the first
    line = r["style"].mech["clocks"]["web"]
    assert line[0][1] is True and line[-1][1] is False  # there, then torn
    torn = line[-1][0]
    assert abs((torn - webbed[0][0]) / 30 - w4.WEB_HOLD) < 0.1
    web = next(z for z in r["style"].mech["zones"] if z["kind"] == "cobweb")
    assert web["appear"] and web["when"] == "web"  # drawn only while it holds


# --- the coffin ---------------------------------------------------------------------------------

def test_the_coffin_takes_one_and_shuts_for_good(sandbox):
    three = CAST[:3]
    r = _first(range(700, 710), lambda r: "trap_catch" in _kinds(r), cast=three, stage="coffin",
               section="coffin-trapdoor", format="elimination")
    mech = r["style"].mech
    p = r["style"].rig.coffin
    caught = min(f for f, kind, _, _ in r["mech_events"] if kind == "trap_catch")
    line = mech["clocks"][p.open_clock]
    assert clock_at(mech, p.open_clock, caught + 2) is False
    assert all(not v for f, v in line if f > caught)  # never opens again
    assert all(tuple(d["color"]) == w4.WOOD for d in mech["doors"])


def test_the_final_has_everything(sandbox):
    two = CAST[1:3]
    r = _round(702, cast=two, stage="hauntedfinal", section="haunted-maze-final",
               mechanics={"open_share": 0.12, "fork": [1.3, 1.45]})
    kinds = set(_kinds(r))
    assert {"pumpkin_rolled", "fog_down", "fog_lifted", "webbed", "trap_opened"} <= kinds
    mech = r["style"].mech
    assert any(z["kind"] == "cobweb" for z in mech["zones"]) and any(z["out"] for z in mech["zones"])
    assert any(e["kind"] == "blackout" for e in mech["effects"])


def test_the_time_trial_shows_a_fixed_par_clock(sandbox):
    r = _round(701, cast=CAST[3:], stage="haunted", section="maze-time-trial")
    mech = r["style"].mech
    effect = next(e for e in mech["effects"] if e["kind"] == "countdown")
    assert effect["clock"] == "par"
    values = [v for _, v in mech["clocks"]["par"]]
    assert values[-1] is None and max(v for v in values if v is not None) <= math.ceil(w4.PAR_S)
    skip = round(float(settings.load().render.get("skip_start_s", 0)) * 30)  # the clip's opening skip
    off = next(f for f, v in mech["clocks"]["par"] if v is None)
    assert abs((off + skip) / 30 - w4.PAR_S) < 0.05  # the same par for every run


# --- redrawn -----------------------------------------------------------------------------------

def test_a_world4_final_redraws_to_the_shipped_frames(no_ffmpeg, tmp_path):
    for engine in ("pygame", "pil"):
        settings.load().raw["render"]["engine"] = engine
        no_ffmpeg["frames"].clear()
        no_ffmpeg["count"] = 0
        clip = physics.generate(seed=702, variant="marble_race", work_dir=tmp_path / engine,
                                params={"stage": "hauntedfinal", "section": "haunted-maze-final", "cast": CAST[1:3],
                                        "rounds": 1,
                                        "mechanics": {"open_share": 0.12, "fork": [1.3, 1.45]}})
        _, meta = trace.read(clip.trace_path)
        mech = meta["rounds"][0]["style"]["mech"]
        assert {"zones", "doors", "effects", "clocks"} <= set(mech)
        redrawn = list(physics.PhysicsSandbox().redraw(clip.trace_path.parent))
        assert len(redrawn) == no_ffmpeg["count"]
        for i, frame in no_ffmpeg["frames"].items():
            if frame is not None:
                assert redrawn[i] == frame, f"{engine} frame {i} differs"
