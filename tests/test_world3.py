"""World 3, polarity swap (Season 0 L22-L30): the two magnet hooks it added to
the core (per-magnet polarity, moving magnets), its sections, its mechanics,
and that each level's season params build the race its copy describes."""

import math
from pathlib import Path

import pytest
import yaml

from factory import settings
from factory.generators import physics, stagekit
from factory.generators.mechanics import Rig, clock_at, magnets_at
from factory.generators.physics import outcome as physics_outcome
from factory.generators.physics import registry
from factory.generators.physics.model import Style
from factory.generators.physics.worlds import polarity

CAST = [
    {"id": "blaze", "name": "Blaze", "color": "#E84C4A", "traits": {"friction": 0.10, "mass_mult": 0.88}},
    {"id": "tide", "name": "Tide", "color": "#378ADD", "traits": {"friction": 0.28, "mass_mult": 1.2}},
    {"id": "volt", "name": "Volt", "color": "#F2C230", "traits": {"jitter": 3.0, "radius_mult": 0.95}},
    {"id": "moss", "name": "Moss", "color": "#97C459", "traits": {}},
]
SKIP = int(0.6 * 30)


def _round(seed, **params):
    return physics.run_round(seed, "marble_race", params, settings.load().render, 540, 960, 30)


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


@pytest.fixture
def mechanic(monkeypatch):
    def add(name, apply, stage=None):
        monkeypatch.setitem(registry.MECHANICS, name, registry.Mechanic(name, apply, stage=stage))
        return name
    return add


# --- the core hooks ----------------------------------------------------------------------------

def test_a_polarity_list_of_ones_is_the_old_magnet(sandbox, mechanic):
    """The per-magnet path computes the law exactly as the scalar one does."""
    plain = _round(11, stage="lodestone")

    def ones(rig, space, style, balls, w, h):
        rig.clock("polarity", lambda f: [1] * len(style.magnets))
        rig.magnet_polarity("polarity")

    same = _round(11, stage="lodestone", section=mechanic("ones", ones))
    assert same["states"] == plain["states"]


def test_one_magnet_can_push_while_the_rest_pull():
    style = Style()
    style.magnets = [(100.0, 500.0, 20.0, 48.0, 140.0, 1.0), (400.0, 500.0, 20.0, 48.0, 140.0, 1.0)]
    mech = {"clocks": {"p": [[0, [1, -3]]]}, "magnet_clock": "p"}
    (_, _, _, _, _, _, a), (_, _, _, _, _, _, b) = magnets_at(style, mech, 5)
    assert (a, b) == (1, -3)
    # The force: a marble right of the first magnet is pulled left, one right
    # of the second is pushed right, three times as hard at the same distance.
    rig = Rig()
    rig.values["p"] = [1, -3]
    rig.magnet_clock = "p"

    class _Body:
        def __init__(self, x, y):
            self.position = __import__("pymunk").Vec2d(x, y)
            self.mass = 1.0
            self.force = (0.0, 0.0)
            self.velocity = __import__("pymunk").Vec2d(0, 0)

    class _Ball:
        def __init__(self, x, y):
            self.body, self.radius, self.traits = _Body(x, y), 20.0, {}

    rig.balls = [_Ball(160.0, 500.0), _Ball(460.0, 500.0)]
    rig.alive = [True, True]
    rig.substep(style, [False, False], 30.0, 30.0 * 3, 1 / 120)
    (fa, _), (fb, _) = rig.balls[0].body.force, rig.balls[1].body.force
    assert fa < 0 < fb and fb == pytest.approx(-3 * fa)


def test_a_moving_magnet_is_where_its_track_says():
    style = Style()
    style.magnets = [(100.0, 500.0, 20.0, 48.0, 140.0, 1.0), (300.0, 300.0, 20.0, 48.0, 140.0, 1.0)]
    mech = {"clocks": {"at": [[0, [None, [300.0, 300.0]]], [10, [None, [320.0, 310.0]]]]}, "magnet_track": "at"}
    assert magnets_at(style, mech, 12)[1][:2] == (320.0, 310.0)
    assert magnets_at(style, mech, 12)[0][:2] == (100.0, 500.0)
    assert magnets_at(style, {}, 12)[1][:2] == (300.0, 300.0)


def test_a_marble_that_starts_inside_a_field_is_not_launched_at_frame_eight():
    style = Style()
    style.stage = "lodestone"
    style.magnets = [(270.0, 800.0, 20.0, 48.0, 400.0, 1.0)]
    states = [[(270.0, 900.0 - 3.0 * f)] for f in range(40)]  # steady 90 px/s, inside from frame 0
    assert physics_outcome.launches(states, style, 30) == []


# --- the sections --------------------------------------------------------------------------

def test_the_arm_is_drawn_where_its_magnets_are(sandbox):
    """The bar is drawn from style.spinners (phase + omega * t on the clip's
    clock); the tip fields come from the recorded track. They agree."""
    r = _round(5, stage="carousel", section="rotating-magnet-arm", cast=CAST)
    style = r["style"]
    (cx, cy, half, omega, phase), = style.spinners
    arms = [k for k, role in style.rig.magnet_roles.items() if role == "arm"]
    assert len(arms) == 2
    for f in (0, 40, 200):
        angle = phase + omega * f / 30.0
        tips = sorted((round(cx + s * half * math.cos(angle), 1), round(cy + s * half * math.sin(angle), 1))
                      for s in (-1, 1))
        drawn = sorted((round(m[0], 1), round(m[1], 1)) for k, m in enumerate(magnets_at(style, style.mech, f))
                       if k in arms)
        assert [v for p in drawn for v in p] == pytest.approx([v for p in tips for v in p], abs=0.2)


def test_tug_side_and_detour_geometry():
    import random
    import pymunk

    def build(section, h=(700.0, 400.0)):
        style = Style()
        style.thickness = 12
        segs = stagekit.SECTIONS[section](pymunk.Space(), 540, h[0], h[1], random.Random(3), style)
        return style, segs

    tug, _ = build("tug")
    (lx, ly, *_, lreach, _), (rx, ry, *_, rreach, _) = tug.magnets
    assert ly == ry and lx < 270 < rx and lreach > 270 - lx and rreach > rx - 270  # the fields meet
    side, _ = build("side-magnets")
    assert len(side.magnets) >= 2 and all(m[0] < 270 for m in side.magnets)
    for seed in range(6):
        style = Style()
        style.thickness = 12
        stagekit.detour(pymunk.Space(), 540, 700.0, 380.0, random.Random(seed), style)
        xs = {m[0] < 270 for m in style.magnets}
        assert len(xs) == 1 and len(style.magnets) >= 2
        # the shielded lane is field-free: no field reaches the divider
        assert all(abs(270 - m[0]) - m[4] > 0 for m in style.magnets)


# --- the mechanics ---------------------------------------------------------------------------

def test_magnet_flip_jolts_then_pushes_and_launches_someone(sandbox):
    launched = 0
    for seed in range(700, 706):
        r = _round(seed, stage="lodestone", section="magnet-flip", mechanics={"flip_at": 0.45}, cast=CAST)
        line = r["style"].mech["clocks"]["polarity"]
        values = [v[0] for _, v in line]
        assert values[0] == 1 and values[1:] == [-polarity.KICK, -polarity.FLIP_PUSH]
        assert abs(line[2][0] - line[1][0] - polarity.KICK_S * 30) <= 1
        assert [k for _, k, _, _ in r["mech_events"]].count("flipped") == 1
        launched += bool(physics_outcome.launches(r["states"], r["style"], 30))
    assert launched >= 2


def test_the_reverse_finish_pushes_only_its_own_magnet(sandbox):
    turned = 0
    for seed in range(700, 708):
        r = _round(seed, stage="lodestone", section="reverse-finish-magnet", cast=CAST)
        style = r["style"]
        roles = style.rig.magnet_roles
        (k,) = [k for k, role in roles.items() if role == "finish"]
        assert style.magnets[k][1] < 110 < style.magnets[k][1] + style.magnets[k][4]  # under the line, reaching over it
        pol = clock_at(style.mech, "polarity", 0)
        assert pol[k] == -polarity.FINISH_PUSH and all(p == 1 for i, p in enumerate(pol) if i != k)
        turned += any(kind == "repelled" for _, kind, _, _ in r["mech_events"])
    assert turned >= 2


def test_the_clump_grips_the_whole_field_then_lets_go(sandbox):
    for seed in (700, 701, 702):
        r = _round(seed, stage="honeypot", section="magnet-clump", cast=CAST)
        kinds = [k for _, k, _, _ in r["mech_events"]]
        assert kinds.count("released") == 1
        values = [v[0] for _, v in r["style"].mech["clocks"]["polarity"]]
        assert values == [polarity.GRIP, -polarity.EJECT, 0]
        assert "clumped" in kinds and kinds.index("clumped") < kinds.index("released")


def test_the_final_flips_the_band_but_not_the_arm_or_the_finish(sandbox):
    r = _round(702, stage="maelstrom", section="all-magnets", mechanics={"kick": 25}, cast=CAST)
    style = r["style"]
    roles = style.rig.magnet_roles
    last = clock_at(style.mech, "polarity", len(r["states"]) - 1)
    for k in range(len(style.magnets)):
        role = roles.get(k, "band")
        assert last[k] == {"band": -polarity.FLIP_PUSH, "arm": polarity.ARM_PULL,
                           "finish": -polarity.FINISH_PUSH}[role]
    assert {"band", "arm", "finish"} == {roles.get(k, "band") for k in range(len(style.magnets))}


def test_a_mirrored_round_puts_the_side_magnets_on_the_other_side(sandbox):
    rounds = physics.race_rounds(9, "marble_race", {"stage": "sidewinder", "rounds": 2, "cast": CAST,
                                                    "round_params": [{}, {"layout": 0, "mirror": True}]},
                                 settings.load().render, 540, 960, 30)
    heat, final = (r["style"].magnets for r in rounds)
    assert all(m[0] < 270 for m in heat) and all(m[0] > 270 for m in final)
    assert sorted(round(540 - m[0], 6) for m in heat) == sorted(round(m[0], 6) for m in final)


def test_the_same_seed_gives_the_same_world_three_race(sandbox):
    a, b = (_round(8, stage="maelstrom", section="all-magnets", cast=CAST) for _ in range(2))
    assert a["states"] == b["states"] and a["style"].mech == b["style"].mech


def test_a_world_three_clip_redraws_to_the_shipped_frames(no_ffmpeg, tmp_path):
    """Moving magnets and per-magnet polarity read off the recording."""
    for engine in ("pygame", "pil"):
        settings.load().raw["render"]["engine"] = engine
        no_ffmpeg["frames"].clear()
        no_ffmpeg["count"] = 0
        clip = physics.generate(seed=4, variant="marble_race", work_dir=tmp_path / engine,
                                params={"stage": "maelstrom", "section": "all-magnets", "rounds": 1, "cast": CAST})
        redrawn = list(physics.PhysicsSandbox().redraw(clip.trace_path.parent))
        assert len(redrawn) == no_ffmpeg["count"]
        for i, frame in no_ffmpeg["frames"].items():
            if frame is not None:
                assert redrawn[i] == frame, f"{engine} frame {i} differs"


# --- the season -----------------------------------------------------------------------------

WORLD3 = ("L22", "L23", "L24", "L25", "L26", "L27", "L28", "L30")


def _levels():
    path = Path(__file__).resolve().parent.parent / "channels" / "main" / "season" / "s0.yaml"
    return {lv["id"]: lv for lv in yaml.safe_load(path.read_text())["levels"]}


def test_world_three_levels_are_ready_on_trial_stages_and_registered_mechanics():
    levels = _levels()
    for lid in WORLD3:
        lv = levels[lid]
        assert lv["status"] == "ready" and lv["blocked_on"] is None
        stage, section = lv["params"]["stage"], lv["params"].get("section")
        assert stage in registry.STAGE_BY_ID and registry.STAGE_BY_ID[stage].weight == 0 or stage == "lodestone"
        assert section is None or section in registry.MECHANICS


@pytest.mark.parametrize("lid", WORLD3)
def test_each_world_three_level_races_from_its_params(sandbox, lid):
    lv = _levels()[lid]
    params = {**lv["params"], "cast": CAST, "format": lv["format"]}
    rounds = physics.race_rounds(700, "marble_race", params, settings.load().render, 540, 960, 30)
    assert len(rounds) == 2 and all(r["winner"] for r in rounds)
    assert all(r["style"].stage == lv["params"]["stage"] for r in rounds)
