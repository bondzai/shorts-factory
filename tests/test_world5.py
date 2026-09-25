"""World 5, Ice vs Sand (L41-L50): its sections, its mechanic, and the levels they build.

Stage QA is what says the stages race (docs/06, "World 5"). These say each
piece does what its copy claims — ice is quicker than sand, the first marble
into the pit sinks, thin ice breaks and takes marbles out, the melt turns ice
to slush, the watcher is a picture and never an entrant — and that all of it
is a function of the seed and redraws to the shipped frames.
"""

import statistics

import pytest
import yaml

from factory import captions, settings
from factory.generators import mechanics, physics, stagekit
from factory.generators.mechanics import clock_at
from factory.generators.physics import registry
from factory.generators.physics.worlds import ice_sand
from factory.series import trace

CAST = [
    {"id": "blaze", "name": "Blaze", "color": "#E84C4A", "traits": {"friction": 0.10, "mass_mult": 0.88}},
    {"id": "tide", "name": "Tide", "color": "#378ADD", "traits": {"friction": 0.28, "mass_mult": 1.2}},
    {"id": "volt", "name": "Volt", "color": "#F2C230", "traits": {"jitter": 3.0, "radius_mult": 0.95}},
    {"id": "moss", "name": "Moss", "color": "#97C459", "traits": {}},
]
STAGES = ("icesand", "stripes", "skijump", "sandpit", "icefall", "thinice", "dunes", "icebowl", "terrain")
LEVELS = ("L41", "L42", "L43", "L44", "L45", "L46", "L47", "L48", "L50")


@pytest.fixture
def no_ffmpeg(sandbox, monkeypatch):
    seen = {"count": 0, "frames": {}}

    def encode_frames(frames, *, out_path, src_size, out_size, fps):
        for i, frame in enumerate(frames):
            seen["frames"][i] = frame if i % 61 == 7 else None
            seen["count"] += 1
        out_path.write_bytes(b"")
        return out_path

    monkeypatch.setattr(physics.sandbox.encoder, "encode_frames", encode_frames)
    monkeypatch.setattr(physics.sandbox.encoder, "mux", lambda video, audio, out: out)
    return seen


def _round(seed, **params):
    return physics.run_round(seed, "marble_race", {"cast": CAST, **params}, settings.load().render, 540, 960, 30)


def _layers(rig):
    return [z for z in rig.zones if not z.out and not z.first_only]


# --- registered, on trial ------------------------------------------------------------------

def test_every_world5_stage_is_registered_at_weight_zero():
    for stage in STAGES:
        spec = registry.STAGE_BY_ID[stage]
        assert spec.weight == 0 and not spec.live and registry.STAGES[stage] == 0.0
        assert all(name in stagekit.SECTIONS for name, _ in spec.parts)
    assert registry.MECHANICS["sideline-watcher"].stage == "terrain"


def test_the_world5_levels_are_ready_on_those_stages_with_hooks_that_pass():
    data = yaml.safe_load(open(settings.ROOT / "channels/main/season/s0.yaml"))
    levels = {lv["id"]: lv for lv in (data["levels"] if isinstance(data, dict) else data)}
    for lid in LEVELS:
        lv = levels[lid]
        assert lv["status"] == "ready" and lv["blocked_on"] is None, lid
        assert lv["params"]["stage"] in STAGES, lid
        assert captions.problem(lv["copy"]["hook"], names=("blaze", "tide", "volt", "moss", "nova")) is None, lid
    # The purple marble is on screen, never in the field.
    assert "nova" not in levels["L50"]["entrants"]
    assert levels["L45"]["params"]["rounds"] == 3


# --- the surfaces ---------------------------------------------------------------------------

def test_ice_and_sand_are_laid_as_surfaces_with_a_layer_that_shows_them(sandbox):
    rig = _round(700, stage="icesand")["style"].rig
    kinds = {s["kind"] for s in rig.surfaces}
    assert {"ice", "sand"} <= kinds
    ice = [z for z in _layers(rig) if z.kind == "ice"]
    sand = [z for z in _layers(rig) if z.kind == "sand"]
    assert ice and sand and all(z.damping == 0 for z in ice) and all(z.damping > 0 for z in sand)
    # Fresh sand: every sand layer has a first-only twin (the trail).
    assert sum(1 for z in rig.zones if z.first_only and z.kind == "sand") == len(sand)
    mech = rig.snapshot()
    assert {z["kind"] for z in mech["zones"]} >= {"ice", "sand"}


def test_a_marble_is_quicker_on_ice_than_in_sand(sandbox):
    """What the world is about: over a few races of the striped stage, the same
    marbles move faster in the ice layers than in the sand ones."""
    speed = {"ice": [], "sand": []}
    for seed in (700, 701, 702):
        r = _round(seed, stage="stripes")
        layers = _layers(r["style"].rig)
        st = r["states"]
        for f in range(1, r["winner_frame"] or len(st) - 1):
            for i, (x, y) in enumerate(st[f]):
                kind = next((z.kind for z in layers if z.contains(x, y)), None)
                if kind in speed:
                    x0, y0 = st[f - 1][i]
                    speed[kind].append(((x - x0) ** 2 + (y - y0) ** 2) ** 0.5 * 30)
    assert statistics.mean(speed["ice"]) > 1.4 * statistics.mean(speed["sand"])


def test_the_melt_turns_ice_to_slush_and_the_ice_left_grips_more(sandbox):
    dry = _round(700, stage="icefall", mechanics={"melt": 0.0})["style"].rig
    wet = _round(700, stage="icefall", mechanics={"melt": 0.9})["style"].rig
    assert not any(s["kind"] == "slush" for s in dry.surfaces)
    share = sum(s["kind"] == "slush" for s in wet.surfaces) / len(wet.surfaces)
    assert share > 0.6
    frictions = {round(z.friction, 3) for z in _layers(wet) if z.kind == "slush"}
    assert frictions == {ice_sand.SLUSH_GRIP}


def test_three_melting_rounds_run_the_same_track(sandbox):
    params = {"stage": "icefall", "rounds": 3, "mechanics": {"melt": 0.2},
              "round_params": [{}, {"layout": 0, "mechanics": {"melt": 0.55}},
                               {"layout": 0, "mechanics": {"melt": 0.9}}]}
    rounds = physics.race_rounds(700, "marble_race", {"cast": CAST, **params}, settings.load().render,
                                 540, 960, 30)
    shapes = [sorted((tuple(s["a"]), tuple(s["b"])) for s in r["style"].rig.surfaces) for r in rounds]
    assert shapes[0] == shapes[1] == shapes[2]
    slush = [sum(s["kind"] == "slush" for s in r["style"].rig.surfaces) for r in rounds]
    assert slush[0] < slush[2]


# --- the mechanisms ---------------------------------------------------------------------------

def test_the_first_marble_into_the_pit_sinks(sandbox):
    r = _round(700, stage="sandpit")
    sank = [(f, i) for f, kind, i, _ in r["style"].rig.events if kind == "sank"]
    assert len(sank) == 1
    pit = next(z for z in r["style"].rig.zones if z.first_only and z.event == "sank")
    assert pit.victim == sank[0][1] and pit.damping == ice_sand.PIT_FIRST


def test_the_ski_jump_launches_the_field(sandbox):
    r = _round(700, stage="skijump")
    launched = {i for _, kind, i, _ in r["style"].rig.events if kind == "launched"}
    assert len(launched) >= 3
    assert any(e.kind == "launched" for e in physics.race_outcome([r], 30, 540).events)


def test_thin_ice_breaks_and_takes_marbles_out(sandbox):
    out = 0
    for seed in (700, 701, 702, 703):
        r = _round(seed, stage="thinice", format="elimination")
        rig = r["style"].rig
        assert rig.breakables and any(z.out for z in rig.zones)
        out += len(r["gone"])
        kinds = [k for _, k, _, _ in rig.events]
        assert kinds.count("eliminated") == kinds.count("fell_through") == len(r["gone"])
    assert out >= 2


def test_the_same_seed_breaks_the_same_ice(sandbox):
    a, b = (_round(705, stage="thinice", format="elimination") for _ in range(2))
    assert a["states"] == b["states"] and a["style"].mech == b["style"].mech and a["gone"] == b["gone"]


def test_the_bowls_gap_takes_in_its_lowest_point(sandbox):
    rig = _round(700, stage="icebowl")["style"].rig
    bowl = next(z for z in rig.zones if z.kind == "ice" and z.damping == ice_sand.BOWL_DRAG)
    lowest = min(p[1] for p in bowl.poly)
    floor = [s for s in rig.surfaces if s["kind"] == "ice" and min(s["a"][1], s["b"][1]) < lowest + 1.0]
    assert not floor  # no ice at the very bottom: that is the gap


def test_dunes_only_ever_go_downhill(sandbox):
    rig = _round(700, stage="dunes")["style"].rig
    for s in rig.surfaces:
        (ax, ay), (bx, by) = s["a"], s["b"]
        if s["kind"] == "sand" and ax != bx:
            assert ay >= by - 1e-6  # every piece is laid from its high end


# --- the watcher --------------------------------------------------------------------------------

def test_the_watcher_is_a_picture_not_an_entrant(sandbox):
    r = _round(700, stage="terrain", section="sideline-watcher")
    names = [b.name for b in r["balls"]]
    assert names == ["blaze", "tide", "volt", "moss"]
    mech = r["style"].mech
    prop = next(e for e in mech["effects"] if e["kind"] == "prop")
    assert prop["color"] == list(ice_sand.WATCHER_COLOUR) and prop["clock"] == "watcher"
    line = mech["clocks"]["watcher"]
    assert line[0][1] is False and line[-1][1] is True  # it arrives late, and stays
    outcome = physics.race_outcome([r], 30, 540)
    assert [p.entrant_id for p in outcome.placements if p.entrant_id not in names] == []


def test_the_watcher_needs_a_pit():
    with pytest.raises(ValueError, match="sand pit"):
        ice_sand.sideline_watcher(mechanics.Rig(), None, None, [], 540, 960)


def test_a_prop_is_drawn_by_both_renderers_only_while_its_clock_is_on():
    from PIL import Image, ImageDraw

    from factory.generators.physics import render_mech
    from factory.generators.physics.model import Style

    style = Style()
    mech = {"clocks": {"w": [[0, False], [5, True]]},
            "effects": [{"kind": "prop", "clock": "w", "at": [100.0, 500.0], "radius": 20.0,
                         "color": [150, 122, 224]}]}
    assert render_mech.props(mech, 2) == [] and len(render_mech.props(mech, 6)) == 1
    img = Image.new("RGB", (540, 960), style.background)
    render_mech.pil_over(ImageDraw.Draw(img), style, mech, 6, 960, {})
    assert img.getpixel((110, 465)) == (150, 122, 224)
    import pygame

    surface = pygame.Surface((540, 960))
    surface.fill(style.background)
    render_mech.pg_over(surface, style, mech, 6, 960, {})
    assert tuple(surface.get_at((110, 465)))[:3] != tuple(style.background)
    assert clock_at(mech, "w", 2) is False


def test_a_world5_race_redraws_to_the_shipped_frames(no_ffmpeg, tmp_path):
    for engine in ("pygame", "pil"):
        settings.load().raw["render"]["engine"] = engine
        no_ffmpeg["frames"].clear()
        no_ffmpeg["count"] = 0
        clip = physics.generate(seed=700, variant="marble_race", work_dir=tmp_path / engine,
                                params={"stage": "terrain", "section": "sideline-watcher", "cast": CAST,
                                        "rounds": 2, "round_params": [{"section": None}, {"stage": "same"}]})
        _, meta = trace.read(clip.trace_path)
        heat, final = (r["style"]["mech"] for r in meta["rounds"])
        assert "effects" not in heat and {"zones", "surfaces", "effects", "clocks"} <= set(final)
        assert meta["rounds"][1]["style"]["stage"] == "terrain"
        redrawn = list(physics.PhysicsSandbox().redraw(clip.trace_path.parent))
        assert len(redrawn) == no_ffmpeg["count"]
        for i, frame in no_ffmpeg["frames"].items():
            if frame is not None:
                assert redrawn[i] == frame, f"{engine} frame {i} differs"
