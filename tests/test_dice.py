"""World 6, the dice track (factory/generators/physics/worlds/dice.py).

Every die is drawn, rolls, lands, and only then does the track do what it
shows; these pin that for each level's mechanic, plus the three core hooks
World 6 added (a hold, a die effect, a mechanic cutting the round count).
"""

from __future__ import annotations

import pytest

from factory import settings
from factory.generators import physics, stagekit
from factory.generators.mechanics import Rig, clock_at
from factory.generators.physics import render_mech
from factory.generators.physics.worlds import dice
from factory.series import trace

FIVE = [
    {"id": "blaze", "name": "Blaze", "color": "#E84C4A", "traits": {"friction": 0.10, "mass_mult": 0.88}},
    {"id": "tide", "name": "Tide", "color": "#378ADD", "traits": {"friction": 0.28, "mass_mult": 1.2}},
    {"id": "volt", "name": "Volt", "color": "#F2C230", "traits": {"jitter": 3.0, "radius_mult": 0.95}},
    {"id": "moss", "name": "Moss", "color": "#97C459", "traits": {}},
    {"id": "nova", "name": "Nova", "color": "#967AE0", "traits": {"radius_mult": 1.05, "friction": 0.2}},
]
FPS = 30


def run(section, seed, cast=FIVE, **params):
    cfg = settings.load().render
    return physics.run_round(seed, "marble_race", {"section": section, "cast": cast, **params}, cfg, 540, 960, FPS)


def settled(mech, name):
    """(frame it landed, face) from a die's recorded clock."""
    for frame, value in mech["clocks"][name]:
        if isinstance(value, dict) and value["s"] == "set":
            return frame, value["f"]
    raise AssertionError(f"{name} never landed")


def events(r, kind):
    return [e for e in r["mech_events"] if e[1] == kind]


# --- the die itself -----------------------------------------------------------------------

def test_a_die_is_hidden_then_tumbles_then_lands_on_its_face():
    rig = Rig(fps=10)
    dice.roll(rig, "d", 2, faces=3, at=1.0)
    rig.bind([])
    rig.start(None, 30.0)
    for frame in range(40):
        rig.before_frame(frame)
    line = rig.timeline["d"]
    assert line[0] == [0, None]
    rolling = [v for _, v in line if isinstance(v, dict) and v["s"] == "roll"]
    assert len(rolling) >= 2 and all(1 <= v["f"] <= 3 for v in rolling)
    assert rolling[-1]["f"] != 2  # it lands on a change
    assert line[-1][1] == {"f": 2, "s": "set"}
    assert [e[1] for e in rig.events] == ["rolled"]
    assert clock_at({"clocks": rig.timeline}, "d_open", 39) is True


def test_a_die_effect_draws_in_both_renderers():
    from PIL import Image, ImageDraw

    mech = {"clocks": {"d": [[0, {"f": 5, "s": "roll"}], [20, {"f": 5, "s": "lit"}]]},
            "effects": [{"kind": "die", "clock": "d", "at": [100.0, 800.0], "size": 60, "layer": "top"},
                        {"kind": "die", "value": 3, "at": [300.0, 800.0], "size": 30, "layer": "under"}]}
    (corners, pips, *_), = render_mech.dice(mech, 0, "top", 960)
    assert len(pips) == 5 and len(corners) == 4
    assert render_mech.dice(mech, 25, "top", 960)[0][-1] == render_mech.DIE_LIT
    assert len(render_mech.dice(mech, 25, "under", 960)[0][1]) == 3
    image = Image.new("RGB", (540, 960))
    render_mech.pil_dice(ImageDraw.Draw(image), mech, 25, "top", 960)
    assert image.getpixel((100, 160)) != (0, 0, 0)
    import pygame

    surface = pygame.Surface((540, 960))
    render_mech.pg_dice(surface, mech, 25, "top", 960)
    assert surface.get_at((100, 160))[:3] != (0, 0, 0)


# --- L51 / L56 / L54: dice gates ------------------------------------------------------------

@pytest.mark.parametrize("seed", [701, 702, 703])
def test_the_gate_sends_the_whole_field_down_the_lane_the_die_shows(sandbox, seed):
    r = run("dice-gate-paths", seed)
    g = r["style"].dice["gates"][0]
    frame, face = settled(r["style"].mech, "gate0")
    (opened,) = events(r, "gate_opened")
    assert opened[3]["lane"] == face and opened[0] >= frame
    x0, x1 = g["lanes"][face - 1]
    mid = (g["lane_top"] + g["lane_bottom"]) / 2
    for i in range(len(r["balls"])):
        below = next((s[i] for s in r["states"] if s[i][1] < mid), None)
        if below is not None:
            assert x0 - 2 <= below[0] <= x1 + 2, (seed, r["balls"][i].name, below)


def test_loaded_dice_always_land_on_the_shelves(sandbox):
    for seed in (700, 701, 702, 703):
        r = run("loaded-dice", seed)
        g = r["style"].dice["gates"][0]
        _, face = settled(r["style"].mech, "gate0")
        assert g["kinds"][face - 1] == "shelves"


def test_three_gates_three_dice_each_landing_before_its_throat_opens(sandbox):
    r = run("dice-gates-duel", 700, cast=FIVE[4:] + FIVE[:1])
    assert len(r["style"].dice["gates"]) == 3
    opened = events(r, "gate_opened")
    assert sorted(e[3]["gate"] for e in opened) == [0, 1, 2]
    for e in opened:
        frame, face = settled(r["style"].mech, f"gate{e[3]['gate']}")
        assert e[3]["lane"] == face and e[0] >= frame


def test_a_gate_with_no_die_holds_then_opens_the_middle_lane(sandbox):
    cfg = settings.load().render
    r = physics.run_round(700, "marble_race", {"stage": "dicetrack", "cast": FIVE}, cfg, 540, 960, FPS)
    assert r["winner"] is not None and not events(r, "rolled")
    g = r["style"].dice["gates"][0]
    x0, x1 = g["lanes"][1]
    mid = (g["lane_top"] + g["lane_bottom"]) / 2
    firsts = [next((s[i] for s in r["states"] if s[i][1] < mid), None) for i in range(5)]
    assert all(p is None or x0 - 2 <= p[0] <= x1 + 2 for p in firsts)


# --- L52 / L59: the rolled grid ------------------------------------------------------------

def test_the_highest_roll_starts_at_the_front_and_the_grid_drops_at_once(sandbox):
    r = run("dice-start-grid", 704)
    mech, states = r["style"].mech, r["states"]
    rolls = [settled(mech, f"grid{k}")[1] for k in range(5)]
    assert rolls == sorted(rolls, reverse=True)
    # slot k is the k-th lowest marble on the ramp at the first frame
    heights = sorted(range(5), key=lambda i: states[0][i][1])
    assert len(set(round(states[0][i][1]) for i in heights)) == 5
    frame, _ = settled(mech, "grid4")
    held = clock_at(mech, "grid_hold", frame)
    assert held is True and clock_at(mech, "grid_hold", len(states) - 1) is False


def test_the_back_marker_starts_last_and_rolls_nothing(sandbox):
    for seed in (700, 701):
        r = run("handicap-back-start", seed, mechanics={"back_marker": "tide"})
        names = [b.name for b in r["balls"]]
        first = r["states"][0]
        back = max(range(5), key=lambda i: first[i][1])
        assert names[back] == "tide"
        dice_drawn = [e for e in r["style"].mech["effects"] if e["kind"] == "die"]
        assert len(dice_drawn) == 4


# --- L53: a blocker removed -------------------------------------------------------------------

def test_the_die_removes_exactly_the_blocker_it_shows(sandbox):
    r = run("dice-remove-obstacle", 705)
    mech = r["style"].mech
    frame, face = settled(mech, "block_die")
    doors = mech["doors"]
    blockers = [d for d in doors if d["passes"] is None and d["closed"] in (None, "block_on")]
    assert len(blockers) == 6
    removed = [k for k, d in enumerate(blockers) if d["closed"] == "block_on"]
    assert removed == [face - 1]
    assert clock_at(mech, "block_on", frame - 1) is True and clock_at(mech, "block_on", frame) is False
    # nobody leaves the start cups before the die has landed
    start = [s[1] for s in r["states"][frame]]
    assert all(y > 850 for y in start)


# --- L55: rounds ---------------------------------------------------------------------------------

def test_the_round_die_sets_how_many_rounds_the_clip_runs(sandbox):
    cfg = settings.load().render
    seen = set()
    for seed in (700, 701, 702, 703, 704):
        params = {"section": "dice-round-count", "cast": FIVE, "rounds": 3,
                  "round_params": [{}, {"stage": "same"}, {"stage": "same"}]}
        rounds = physics.race_rounds(seed, "marble_race", params, cfg, 540, 960, FPS)
        _, face = settled(rounds[0]["style"].mech, "rounds_die")
        assert len(rounds) == face == rounds[0]["clip_rounds"]
        assert all(r["style"].stage == "dicegrid" for r in rounds)
        seen.add(face)
    assert len(seen) >= 2


def test_rounds_asked_for_are_still_the_most(sandbox):
    cfg = settings.load().render
    rounds = physics.race_rounds(702, "marble_race", {"section": "dice-round-count", "cast": FIVE, "rounds": 1},
                                 cfg, 540, 960, FPS)
    assert len(rounds) == 1


# --- L57: surfaces --------------------------------------------------------------------------------

def test_a_band_takes_the_surface_its_die_lands_on_and_only_then(sandbox):
    kinds = set()
    for seed in (700, 701, 702):
        r = run("dice-surface", seed)
        mech = r["style"].mech
        zones = {z["when"]: z for z in mech.get("zones") or ()}
        for k in range(3):
            frame, face = settled(mech, f"surface{k}")
            kind = dice.SURFACE_FACES[face]
            kinds.add(kind)
            z = zones.get(f"surface{k}_set")
            if kind == "plain":
                assert z is None
                continue
            assert z["kind"] == kind and z["appear"]
            assert not render_mech.zone_shown(mech, z, frame - 1) and render_mech.zone_shown(mech, z, frame)
    assert len(kinds) >= 2


# --- L58: the head start --------------------------------------------------------------------------

def test_the_head_start_goes_to_the_cup_the_die_shows(sandbox):
    for seed in (700, 701, 702):
        r = run("handicap-start", seed)
        mech, states = r["style"].mech, r["states"]
        frame, face = settled(mech, "head_die")
        screen = sorted(range(5), key=lambda i: states[0][i][0])
        chosen = screen[face - 1]
        (ev,) = events(r, "head_start")
        assert ev[2] == chosen
        # a beat after the die, the chosen marble has dropped and nobody else has
        later = states[min(len(states) - 1, frame + int(1.45 * FPS))]
        start = states[0]
        assert start[chosen][1] - later[chosen][1] > 8
        assert all(abs(start[i][1] - later[i][1]) < 6 for i in range(5) if i != chosen)


# --- L60: all of it ----------------------------------------------------------------------------------

def test_the_final_rolls_grid_rounds_path_and_surface(sandbox):
    r = run("dice-final", 700, rounds=3)
    mech = r["style"].mech
    names = set(mech["clocks"])
    assert {"grid0", "grid4", "rounds_die", "gate0", "lanes_surface"} <= names
    assert r["clip_rounds"] == settled(mech, "rounds_die")[1]
    assert events(r, "gate_opened")


# --- determinism and the redraw --------------------------------------------------------------------

def test_the_same_seed_rolls_the_same_dice(sandbox):
    a, b = run("dice-final", 703), run("dice-final", 703)
    assert a["states"] == b["states"] and a["style"].mech == b["style"].mech


def test_a_dice_clip_redraws_to_the_shipped_frames(sandbox, monkeypatch, tmp_path):
    seen = {"count": 0, "frames": {}}

    def encode_frames(frames, *, out_path, src_size, out_size, fps):
        for i, frame in enumerate(frames):
            seen["frames"][i] = frame if i % 37 == 5 else None
            seen["count"] += 1
        out_path.write_bytes(b"")
        return out_path

    monkeypatch.setattr(physics.sandbox.encoder, "encode_frames", encode_frames)
    monkeypatch.setattr(physics.sandbox.encoder, "mux", lambda video, audio, out: out)
    for engine in ("pygame", "pil"):
        settings.load().raw["render"]["engine"] = engine
        seen["frames"].clear()
        seen["count"] = 0
        clip = physics.generate(seed=702, variant="marble_race", work_dir=tmp_path / engine,
                                params={"section": "dice-surface", "cast": FIVE, "rounds": 1})
        _, meta = trace.read(clip.trace_path)
        mech = meta["rounds"][0]["style"]["mech"]
        assert any(e["kind"] == "die" for e in mech["effects"])
        redrawn = list(physics.PhysicsSandbox().redraw(clip.trace_path.parent))
        assert len(redrawn) == seen["count"]
        for i, frame in seen["frames"].items():
            if frame is not None:
                assert redrawn[i] == frame, f"{engine} frame {i} differs"


# --- the stages -------------------------------------------------------------------------------------

def test_the_dice_stages_are_trial_and_their_levels_name_them():
    for stage in ("dicetrack", "dicegrid", "diceblock", "dicetriple", "dicesurface", "dicefinal"):
        assert physics.STAGE_BY_ID[stage].weight == 0
    for name in ("dice-gate-paths", "dice-start-grid", "dice-remove-obstacle", "dice-gates-duel",
                 "dice-round-count", "loaded-dice", "dice-surface", "handicap-start", "handicap-back-start",
                 "dice-final"):
        spec = physics.registry.MECHANICS[name]
        assert spec.stage in physics.STAGE_BY_ID
    assert {"dicegate", "dicetriple", "runway", "diceblock", "surfaceramps"} <= set(stagekit.SECTIONS)
