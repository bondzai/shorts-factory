"""World 9, Color Roulette Gates (L81-L90): the gates, the mechanics that set
them, and the levels they build.

Stage QA says the stages race (docs/06, "World 9"). These say each gate does
what its copy claims — only the lit colour goes through a lit gate, the
reverse gate shuts for whoever leads, the cycling gate lights every colour in
turn, the trapdoor gate drops only the colours it did not light, the breaking
gate breaks under momentum and holds its breaker in the box — that the colour
is the seed's and never a persona's, and that it redraws to the shipped
frames in both renderers.
"""

import pytest
import yaml

from factory import captions, settings
from factory.generators import mechanics, physics, stagekit
from factory.generators.mechanics import clock_at
from factory.generators.physics import registry
from factory.generators.physics.worlds import colour_gates as w9
from factory.series import planning, story, trace

CAST = [
    {"id": "blaze", "name": "Blaze", "color": "#E84C4A", "traits": {"friction": 0.10, "mass_mult": 0.88}},
    {"id": "tide", "name": "Tide", "color": "#378ADD", "traits": {"friction": 0.28, "mass_mult": 1.2}},
    {"id": "volt", "name": "Volt", "color": "#F2C230", "traits": {"jitter": 3.0, "radius_mult": 0.95}},
    {"id": "moss", "name": "Moss", "color": "#97C459", "traits": {}},
    {"id": "nova", "name": "Nova", "color": "#967AE0", "traits": {"radius_mult": 1.05, "friction": 0.2}},
    {"id": "ember", "name": "Ember", "color": "#EF8A27",
     "traits": {"mass_mult": 1.6, "radius_mult": 1.1, "force_immune": True}},
]
GUESTS = [{"id": "acorn", "name": "Acorn", "color": "#8C5A2E", "traits": {}},
          {"id": "juniper", "name": "Juniper", "color": "#1FA89A", "traits": {}}]
LEVELS = {
    "L81": ("colourgate", "random-colour-gate"), "L82": ("threegates", "three-colour-gates"),
    "L83": ("lockout", "leader-lockout-gate"), "L84": ("colourgate", "alliance-gate"),
    "L85": ("rhythm", "cycling-colour-gate"), "L86": ("colourtrap", "colour-trapdoor-gate"),
    "L87": ("snowtrack", "snow-colour-gates"), "L88": ("breakgate", "gate-breaker"),
    "L89": ("seeding", "seeding-cycling-gate"), "L90": ("snowfinal", "all-gates-snow"),
}


def _round(section, seed, cast=CAST, **extra):
    stage = registry.MECHANICS[section].stage
    params = {"stage": stage, "section": section, "cast": cast, **extra}
    return physics.run_round(seed, "marble_race", params, settings.load().render, 540, 960, 30)


def _kinds(r):
    return [kind for _, kind, _, _ in r["mech_events"]]


def _through(r, g):
    """(frame, name) for each marble's first frame below gate g's bar, inside it."""
    out = []
    for i, b in enumerate(r["balls"]):
        for f, p in enumerate(r["states"]):
            if p[i][1] < g.y - b.radius and g.x0 - b.radius <= p[i][0] <= g.x1 + b.radius:
                out.append((f, b.name))
                break
    return out


def _was_let_through(mech, g, name, frame, back=20):
    """In the gate's pass list at this frame or shortly before (it was
    crossing), or the gate was open."""
    for f in range(max(0, frame - back), frame + 1):
        if not clock_at(mech, g.name + "_shut", f) or name in (clock_at(mech, g.name + "_pass", f) or []):
            return True
    return False


# --- registered, on trial ---------------------------------------------------------------------

def test_every_world_nine_level_names_a_trial_stage_and_a_mechanic():
    for stage, section in LEVELS.values():
        spec = registry.STAGE_BY_ID[stage]
        assert spec.weight == 0 and not spec.live and stage not in registry.LIVE_STAGES
        assert registry.MECHANICS[section].stage == stage
    for name in w9.SECTIONS:
        assert stagekit.SECTIONS[name] is w9.SECTIONS[name] and name in stagekit.SECTION_WORDS


def test_a_gate_mechanic_on_a_stage_without_gates_says_so():
    with pytest.raises(ValueError, match="colour gate"):
        w9.random_colour_gate(mechanics.Rig(), None, None, [], 540, 960)
    with pytest.raises(ValueError, match="trapdoor panels"):
        w9.colour_trapdoor(mechanics.Rig(), None, None, [], 540, 960)


def test_the_same_seed_is_the_same_gate_race(sandbox):
    a, b = _round("random-colour-gate", 701), _round("random-colour-gate", 701)
    assert a["style"].mech == b["style"].mech and a["states"] == b["states"]


# --- the gates --------------------------------------------------------------------------------

def test_a_lit_gate_lets_only_its_colour_through_until_it_opens(sandbox):
    r = _round("random-colour-gate", 701)
    mech, g = r["style"].mech, r["style"].rig.colour_gates[0]
    lit = [v for _, v in mech["clocks"]["cgate0_lit"] if v]
    assert len(lit) == 1 and len(lit[0]) == 1 and lit[0][0] in [e["id"] for e in CAST]
    assert "gate_lit" in _kinds(r) and "gate_opened" in _kinds(r)
    passed = _through(r, g)
    assert len(passed) == len(CAST)
    for frame, name in passed:
        assert _was_let_through(mech, g, name, frame), f"{name} went through a shut bar at {frame}"
    # Someone waited: a marble that is not lit sat on the bar while it was shut.
    assert any(v for _, v in mech["clocks"]["cgate0_wait"])


def test_the_colour_is_the_seeds_not_a_personas(sandbox):
    """Rename the field: the gate lights the marble in the same place in it."""
    renamed = [{**e, "id": f"x{k}", "name": f"X{k}"} for k, e in enumerate(CAST)]
    a, b = _round("random-colour-gate", 705), _round("random-colour-gate", 705, cast=renamed)
    pick = lambda r: next(v for _, v in r["style"].mech["clocks"]["cgate0_lit"] if v)[0]  # noqa: E731
    assert [e["id"] for e in CAST].index(pick(a)) == [e["id"] for e in renamed].index(pick(b))


def test_the_alliance_gate_lights_two_colours(sandbox):
    r = _round("alliance-gate", 702)
    lit = next(v for _, v in r["style"].mech["clocks"]["cgate0_lit"] if v)
    assert len(set(lit)) == 2


def test_three_gates_light_three_different_colours(sandbox):
    r = _round("three-colour-gates", 703)
    firsts = [next(v for _, v in r["style"].mech["clocks"][f"cgate{k}_lit"] if v)[0] for k in range(3)]
    assert len(set(firsts)) == 3


def test_the_reverse_gate_shuts_for_whoever_leads_as_the_field_reaches_it(sandbox):
    r = _round("leader-lockout-gate", 701)
    mech, g = r["style"].mech, r["style"].rig.colour_gates[0]
    line = mech["clocks"]["cgate0_lit"]
    frame, locked = next((f, v) for f, v in line if v)
    assert len(locked) == 1 and "gate_locked" in _kinds(r)
    # The locked marble was the lowest marble on the course then.
    lowest = min(range(len(r["balls"])), key=lambda i: r["states"][frame][i][1])
    assert r["balls"][lowest].name == locked[0]
    # It is drawn pale with its lamps crossed out, and it goes through only once the gate opens.
    assert next(d for d in mech["doors"] if d["closed"] == "cgate0_shut")["look"] == "block"
    at = dict((n, f) for f, n in _through(r, g))[locked[0]]
    assert not clock_at(mech, "cgate0_shut", at - 25) or locked[0] in (clock_at(mech, "cgate0_pass", at - 25) or [])


def test_the_cycling_gate_lights_every_colour_one_a_second(sandbox):
    r = _round("cycling-colour-gate", 704)
    line = r["style"].mech["clocks"]["cgate0_lit"]
    seen = [v[0] for _, v in line if v]
    assert set(seen) == {e["id"] for e in CAST}
    gaps = [b[0] - a[0] for a, b in zip(line[1:], line[2:])]
    assert all(g == 30 for g in gaps[:-1])
    mech, g = r["style"].mech, r["style"].rig.colour_gates[0]
    for frame, name in _through(r, g):
        assert _was_let_through(mech, g, name, frame)


def test_the_trapdoor_gate_drops_only_the_colours_it_did_not_light(sandbox):
    cast = CAST + GUESTS
    for seed in range(700, 708):
        r = _round("colour-trapdoor-gate", seed, cast=cast, format="elimination")
        if r["gone"]:
            break
    else:
        pytest.fail("no trapdoor-gate catch in seeds 700-707")
    mech = r["style"].mech
    assert "trap_catch" in _kinds(r)
    for name, frame in r["gone"].items():
        lit = [clock_at(mech, "trapdoor0_lit", f) or [] for f in range(max(0, frame - 45), frame + 1)]
        assert name not in {x for v in lit for x in v}, f"{name} was lit and still fell"
    lid = [d for d in mech["doors"] if d.get("lights") == "trapdoor0_lit"]
    assert lid and all(d["look"] == "pass" for d in lid)


def test_the_gate_breaks_under_momentum_and_the_breaker_serves_its_penalty(sandbox):
    # Strength 1: the first marble to meet the bar shut for it breaks it.
    r = _round("gate-breaker", 703, mechanics={"strength": 1.0})
    events = [(f, i) for f, k, i, _ in r["mech_events"] if k == "gate_broken"]
    assert len(events) == 1
    mech = r["style"].mech
    breaker = r["balls"][events[0][1]].name
    held = [f for f, v in mech["clocks"]["penalty_lit"] if v]
    assert held and all(v in ([breaker], []) for _, v in mech["clocks"]["penalty_lit"])
    assert any(v for _, v in mech["clocks"]["penalty_left"])  # the countdown showed
    assert not clock_at(mech, "cgate0_shut", len(r["states"]) - 1)  # broken for good
    # At the level's strength, the same rule for everyone: on these seeds only the heavy marble has it.
    for seed in (702, 703):
        r = _round("gate-breaker", seed)
        who = [r["balls"][i].name for _, k, i, _ in r["mech_events"] if k == "gate_broken"]
        assert who == ["ember"]


def test_the_snow_tracks_lay_their_gates_on_ice(sandbox):
    r = _round("all-gates-snow", 700)
    rig = r["style"].rig
    assert len(rig.colour_gates) == 3 and rig.trapdoors
    assert {s["kind"] for s in r["style"].mech["surfaces"]} == {"ice"}
    looks = [d.get("look") for d in r["style"].mech["doors"]]
    assert looks.count("block") == 1 and looks.count("pass") >= 3


# --- drawn, and recorded compatibly ------------------------------------------------------------

def test_a_door_without_a_look_records_what_it_always_did():
    rig = mechanics.Rig()
    import pymunk
    space = pymunk.Space()
    rig.door(space, (0, 0), (10, 0))
    rig.door(space, (0, 5), (10, 5), lights=["a"], look="pass", lamps=[(1, 2)])
    plain, gate = rig.snapshot()["doors"]
    assert set(plain) == {"a", "b", "closed", "passes", "color"}
    assert gate["look"] == "pass" and gate["lights"] == ["a"] and gate["lamps"] == [[1.0, 2.0]]
    with pytest.raises(ValueError):
        rig.door(space, (0, 0), (1, 0), look="glow")


@pytest.mark.parametrize("look", ["pass", "block"])
def test_both_renderers_draw_a_shut_gate_in_its_colour(look):
    from PIL import Image, ImageDraw
    import pygame

    from factory.generators.physics import render_mech
    from factory.generators.physics.model import Style

    style = Style()
    mech = {"clocks": {"s": [[0, True], [10, False]], "l": [[0, ["tide"]]]},
            "doors": [{"a": [100.0, 500.0], "b": [300.0, 500.0], "closed": "s", "passes": None, "color": None,
                       "lights": "l", "look": look, "lamps": [[60.0, 500.0]]}]}
    colours = {"tide": (55, 138, 221)}
    img = Image.new("RGB", (540, 960), style.background)
    render_mech.pil_over(ImageDraw.Draw(img), style, mech, 2, 960, colours)
    surface = pygame.Surface((540, 960))
    surface.fill(style.background)
    render_mech.pg_over(surface, style, mech, 2, 960, colours)
    bar = (200, 460)
    lamp = (60, 460)
    for got in (img.getpixel(bar), tuple(surface.get_at(bar))[:3]):
        assert (got == colours["tide"]) == (look == "pass")
    assert img.getpixel((lamp[0] + 5, lamp[1] - 5)) == colours["tide"] or look == "block"
    # Open: the faint line, no lamps.
    img2 = Image.new("RGB", (540, 960), style.background)
    render_mech.pil_over(ImageDraw.Draw(img2), style, mech, 12, 960, colours)
    assert img2.getpixel(lamp) == style.background and img2.getpixel(bar) != colours["tide"]


def test_a_colour_gate_race_redraws_to_the_shipped_frames(sandbox, tmp_path, monkeypatch):
    seen = {"count": 0, "frames": {}}

    def encode_frames(frames, *, out_path, src_size, out_size, fps):
        for i, frame in enumerate(frames):
            seen["frames"][i] = frame if i % 61 == 7 else None
            seen["count"] += 1
        out_path.write_bytes(b"")
        return out_path

    monkeypatch.setattr(physics.sandbox.encoder, "encode_frames", encode_frames)
    monkeypatch.setattr(physics.sandbox.encoder, "mux", lambda video, audio, out: out)
    for engine in ("pygame", "pil"):
        settings.load().raw["render"]["engine"] = engine
        seen["frames"].clear()
        seen["count"] = 0
        clip = physics.generate(seed=700, variant="marble_race", work_dir=tmp_path / engine,
                                params={"stage": "lockout", "section": "leader-lockout-gate", "cast": CAST,
                                        "rounds": 1})
        _, meta = trace.read(clip.trace_path)
        doors = meta["rounds"][0]["style"]["mech"]["doors"]
        assert doors[0]["look"] == "block" and doors[0]["lamps"]
        redrawn = list(physics.PhysicsSandbox().redraw(clip.trace_path.parent))
        assert len(redrawn) == seen["count"]
        for i, frame in seen["frames"].items():
            if frame is not None:
                assert redrawn[i] == frame, f"{engine} frame {i} differs"


# --- the season's levels ------------------------------------------------------------------------

def test_world_nine_levels_are_ready_with_params_a_task_carries():
    from factory.series import cast as series_cast
    from factory.series.season import load

    data = yaml.safe_load(open(settings.ROOT / "channels/main/season/s0.yaml"))
    raw = {lv["id"]: lv for lv in data["levels"]}
    season = load("main", "s0")
    cast = series_cast.load("main")
    for lid, (stage, section) in LEVELS.items():
        lv = season.level(lid)
        assert lv.status in (("ready", "needs_input") if lid == "L90" else ("ready",)) and lv.blocked_on is None, lid  # L90: stand-in seed list
        assert lv.note and raw[lid]["params"] == {"stage": stage, "section": section}, lid
        params = planning.task_params(lv, season, cast)
        assert params["section"] in registry.MECHANICS
        assert not story.validate(lv.story.must) and not story.identity_predicates(lv.story.must)
        assert captions.problem(lv.copy_.hook, names=tuple(lv.entrants)) is None, lid
    assert season.level("L86").entrants[-2:] == ["acorn", "juniper"] and season.level("L86").format == "elimination"
    assert "STAND-IN" in season.level("L89").note
