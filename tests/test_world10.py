"""World 10, the Christmas Grand Final (L91-L100): the gauntlet that switches
on each earlier world's mechanism, the champion's lap and its standings board,
the Season One teaser's track under construction and its silhouette, and the
season's levels.

Stage QA says the stages race (docs/06, "World 10"). These say the wiring does
what the copy claims — each semifinal track runs its three worlds, the lap
keeps its trapdoors shut and draws only a table it was given, a scaffold ramp
is built ahead of the field and never through a marble, the silhouette is a
picture and never an entrant — and that a World 10 clip redraws to its
shipped frames in both renderers.
"""

import pytest
import yaml
from PIL import Image, ImageDraw

from factory import captions, settings
from factory.generators.mechanics import clock_at
from factory.generators import physics
from factory.generators.physics import registry, render_mech
from factory.generators.physics.worlds import grand_final as w10
from factory.series import planning, story, trace

CAST = [
    {"id": "blaze", "name": "Blaze", "color": "#E84C4A", "traits": {"friction": 0.10, "mass_mult": 0.88}},
    {"id": "tide", "name": "Tide", "color": "#378ADD", "traits": {"friction": 0.28, "mass_mult": 1.2}},
    {"id": "volt", "name": "Volt", "color": "#F2C230", "traits": {"jitter": 3.0, "radius_mult": 0.95}},
    {"id": "moss", "name": "Moss", "color": "#97C459", "traits": {}},
    {"id": "nova", "name": "Nova", "color": "#967AE0", "traits": {"radius_mult": 1.05, "friction": 0.2}},
    {"id": "ember", "name": "Ember", "color": "#EF8A27",
     "traits": {"mass_mult": 1.6, "radius_mult": 1.1, "force_immune": True, "charge": 1.5, "friction": 0.45}},
]
PAIR = CAST[:2]
ROWS = [{"name": "Tide", "points": 41, "color": [55, 138, 221]}, {"name": "Blaze", "points": 38, "color": None}]
NEW_STAGES = ("magnetgates", "trapdice", "construction")


def _round(stage, section, seed, cast=PAIR, **extra):
    params = {"stage": stage, "section": section, "cast": cast, **extra}
    return physics.run_round(seed, "marble_race", params, settings.load().render, 540, 960, 30)


def _kinds(r):
    return {kind for _, kind, _, _ in r["mech_events"]}


# --- registered, on trial ---------------------------------------------------------------------

def test_world_ten_stages_are_trial_and_every_mechanic_names_one():
    for stage in NEW_STAGES:
        spec = registry.STAGE_BY_ID[stage]
        assert spec.weight == 0 and not spec.live and stage not in registry.LIVE_STAGES
    for section, stage in (("gauntlet-magnets-ice-gates", "magnetgates"),
                           ("gauntlet-trapdoors-repulsion-dice", "trapdice"),
                           ("grand-final-composite", "magnetgates"), ("champion-lap", "magnetgates"),
                           ("season-one-teaser", "construction")):
        assert registry.MECHANICS[section].stage == stage
    assert "scaffold" in registry.stagekit.SECTIONS


def test_a_semifinal_mechanic_on_the_wrong_stage_says_so(sandbox):
    with pytest.raises(ValueError, match="magnetgates"):
        _round("trapdice", "gauntlet-magnets-ice-gates", 700)
    with pytest.raises(ValueError, match="trapdice"):
        _round("magnetgates", "gauntlet-trapdoors-repulsion-dice", 700)
    with pytest.raises(ValueError, match="scaffold"):
        _round("zigzag", "season-one-teaser", 700)


# --- the gauntlet -------------------------------------------------------------------------------

def test_each_semifinal_track_runs_its_three_worlds(sandbox):
    a = _round("magnetgates", "gauntlet-magnets-ice-gates", 701)
    assert {"flipped", "gate_lit"} <= _kinds(a)
    mech = a["style"].mech
    assert any(d.get("look") for d in mech["doors"])  # the colour gate
    assert any(z["kind"] == "ice" for z in mech.get("zones") or ()) or mech.get("surfaces")  # its ice arms
    b = _round("trapdice", "gauntlet-trapdoors-repulsion-dice", 701)
    assert {"rolled", "gate_opened", "trap_opened"} <= _kinds(b)
    assert any(e["kind"] == "field" for e in b["style"].mech["effects"])  # the push, drawn


def test_the_final_switches_on_whatever_each_rounds_stage_built(sandbox):
    haunted = _round("hauntedfinal", "grand-final-composite", 702, mechanics={"open_share": 0.12})
    assert {"fog_down", "webbed", "pumpkin_rolled"} <= _kinds(haunted)
    dice = _round("trapdice", "grand-final-composite", 702, mechanics={"repel": 1.6})
    assert "rolled" in _kinds(dice) and any(e["kind"] == "field" for e in dice["style"].mech["effects"])
    gates = _round("magnetgates", "grand-final-composite", 702)
    assert {"flipped", "gate_lit"} <= _kinds(gates)


def test_the_same_seed_is_the_same_gauntlet(sandbox):
    a = _round("trapdice", "gauntlet-trapdoors-repulsion-dice", 703)
    b = _round("trapdice", "gauntlet-trapdoors-repulsion-dice", 703)
    assert a["style"].mech == b["style"].mech and a["winner"] == b["winner"]


# --- the champion's lap -------------------------------------------------------------------------

def test_the_lap_keeps_every_trapdoor_shut_and_draws_only_the_table_it_was_given(sandbox):
    for seed in range(700, 706):
        r = _round("trapdice", "champion-lap", seed, cast=CAST[:1], mechanics={"standings": ROWS})
        assert "trap_opened" not in _kinds(r) and not r.get("gone")
        boards = [e for e in r["style"].mech["effects"] if e["kind"] == "board"]
        assert len(boards) == 1 and [x["name"] for x in boards[0]["rows"]] == ["Tide", "Blaze"]
    unfilled = _round("magnetgates", "champion-lap", 700, cast=CAST[:1], mechanics={"standings": "at_plan"})
    assert not any(e["kind"] == "board" for e in unfilled["style"].mech.get("effects") or ())
    assert w10.standings_rows("at_plan") == [] and w10.standings_rows(None) == []


def test_the_board_is_drawn_under_the_line_in_both_renderers():
    mech = {"effects": [{"kind": "board", "rows": ROWS, "at": [270, 50], "title": "SEASON STANDINGS"}]}
    img = render_mech.board_image(mech["effects"][0], 540, (255, 255, 255))
    (left, top), = [at for _, at in render_mech.boards(mech, 540, 960, (255, 255, 255))]
    assert top > 960 - 110 - 6 and top + img.height <= 960  # the strip under the finish line
    assert img.getpixel((img.width // 2, img.height // 2))[3] > 0


# --- the Season One teaser ----------------------------------------------------------------------

def test_the_scaffold_is_built_ahead_of_the_field_and_never_through_a_marble(sandbox):
    r = _round("construction", "season-one-teaser", 704, cast=CAST)
    mech, states = r["style"].mech, r["states"]
    doors = [d for d in mech["doors"] if str(d.get("closed", "")).startswith("scaffold")]
    assert len(doors) >= 2
    built = [f for f, kind, _, _ in r["mech_events"] if kind == "built"]
    assert len(built) == len(doors)
    for d in doors:
        first = next(f for f in range(len(states)) if clock_at(mech, d["closed"], f))
        assert clock_at(mech, d["closed"], len(states) - 1)  # built for good
        (ax, ay), (bx, by) = d["a"], d["b"]
        for i, (x, y) in enumerate(states[first]):
            # nobody inside the ramp's line the frame it is built
            t = max(0.0, min(1.0, ((x - ax) * (bx - ax) + (y - ay) * (by - ay)) / ((bx - ax) ** 2 + (by - ay) ** 2)))
            gap = ((x - ax - t * (bx - ax)) ** 2 + (y - ay - t * (by - ay)) ** 2) ** 0.5
            assert gap > r["balls"][i].radius, (d["closed"], i)
    sketches = [e for e in mech["effects"] if e["kind"] == "sketch"]
    assert len(sketches) == len(doors)
    assert render_mech.sketches(mech, 0, 960) and not render_mech.sketches(mech, len(states) - 1, 960)


def test_the_silhouette_is_a_picture_never_an_entrant(sandbox):
    r = _round("construction", "season-one-teaser", 705, cast=CAST)
    mech = r["style"].mech
    (prop,) = [e for e in mech["effects"] if e["kind"] == "prop"]
    assert prop["look"] == "silhouette" and prop["track"]
    assert clock_at(mech, "newcomer", 0) is None and clock_at(mech, "newcomer", len(r["states"]) - 1)
    assert len(r["balls"]) == len(CAST) and all(b.name in {c["id"] for c in CAST} for b in r["balls"])
    frame = len(r["states"]) - 1
    (x, y, radius, colour), = render_mech.props(mech, frame, "silhouette")
    img = Image.new("RGB", (540, 960), (200, 0, 0))
    render_mech.pil_over(ImageDraw.Draw(img), r["style"], mech, frame, 960, {})
    assert img.getpixel((int(x), int(960 - y))) == tuple(colour)


def test_a_world_ten_clip_redraws_to_the_shipped_frames(sandbox, tmp_path, monkeypatch):
    seen = {"count": 0, "frames": {}}

    def encode_frames(frames, *, out_path, src_size, out_size, fps):
        for i, frame in enumerate(frames):
            seen["frames"][i] = frame if i % 53 == 5 else None
            seen["count"] += 1
        out_path.write_bytes(b"")
        return out_path

    monkeypatch.setattr(physics.sandbox.encoder, "encode_frames", encode_frames)
    monkeypatch.setattr(physics.sandbox.encoder, "mux", lambda video, audio, out: out)
    cases = [("construction", "season-one-teaser", CAST, {}),
             ("trapdice", "champion-lap", CAST[:1], {"standings": ROWS})]
    for engine in ("pygame", "pil"):
        settings.load().raw["render"]["engine"] = engine
        for stage, section, cast, knobs in cases:
            seen["frames"].clear()
            seen["count"] = 0
            clip = physics.generate(seed=700, variant="marble_race", work_dir=tmp_path / engine / stage,
                                    params={"stage": stage, "section": section, "cast": cast, "rounds": 1,
                                            "mechanics": knobs})
            _, meta = trace.read(clip.trace_path)
            kinds = {e["kind"] for e in meta["rounds"][0]["style"]["mech"]["effects"]}
            assert kinds & {"sketch", "board"}
            redrawn = list(physics.PhysicsSandbox().redraw(clip.trace_path.parent))
            assert len(redrawn) == seen["count"]
            for i, frame in seen["frames"].items():
                if frame is not None:
                    assert redrawn[i] == frame, f"{engine} {stage} frame {i} differs"


# --- the season's levels ------------------------------------------------------------------------

def test_world_ten_levels_are_ready_or_honestly_blocked():
    from factory.series import cast as series_cast
    from factory.series.season import load

    raw = {lv["id"]: lv for lv in yaml.safe_load(open(settings.ROOT / "channels/main/season/s0.yaml"))["levels"]}
    season = load("main", "s0")
    cast = series_cast.load("main")
    for n in range(91, 101):
        lid = f"L{n}"
        lv = season.level(lid)
        assert captions.problem(lv.copy_.hook, names=tuple(lv.entrants)) is None, lid
        if lid == "L94":
            assert lv.status == "blocked" and "arena" in lv.blocked_on
            continue
        assert lv.status == "ready" and lv.blocked_on is None and lv.note, lid
        assert set(raw[lid]["params"]) <= planning.PARAM_KEYS, lid
        params = planning.task_params(lv, season, cast)
        assert params["stage"] in registry.STAGE_BY_ID, lid
        assert params.get("section") is None or params["section"] in registry.MECHANICS, lid
        assert int(params.get("rounds", 0)) in (1, 3), lid  # never the config's default second round
        assert not story.validate(lv.story.must) and not story.identity_predicates(lv.story.must), lid
        assert not story.identity_predicates(lv.story.prefer), lid
    for lid in ("L91", "L92", "L93", "L95", "L96", "L97", "L98", "L99"):
        assert "STAND-IN" in season.level(lid).note, lid
    assert season.level("L92").date.isoformat() == "2026-12-25" and season.level("L92").rematch_of == "L37"
    assert season.level("L98").date.isoformat() == "2026-12-31" and season.level("L98").final
    assert [r.get("stage") for r in season.level("L98").params["round_params"]] == [None, "trapdice", "magnetgates"]
    assert not season.level("L99").scored and not season.level("L100").scored
    assert season.level("L99").params["mechanics"]["standings"] == planning.STANDINGS_AT_PLAN
