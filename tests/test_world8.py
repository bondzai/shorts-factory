"""World 8, Repel Race (Season 0 L71-L80): the two pair-force options it added
to the core (equal and opposite, immune marbles pushed too), the field it
draws, its geometry built from the marbles' radii, and that each ready level's
season params build the race its copy describes."""

import math
import tomllib
from pathlib import Path

import pymunk
import pytest
import yaml

from factory import settings
from factory.generators import physics
from factory.generators.mechanics import Rig
from factory.generators.physics import registry, render_mech
from factory.generators.physics.worlds import repel

ROOT = Path(__file__).resolve().parent.parent


def _cast(ids):
    data = tomllib.loads((ROOT / "channels" / "main" / "cast.toml").read_text())
    by = {e["id"]: e for e in data["entrant"]}
    return [{"id": i, "name": by[i]["name"], "color": by[i]["color"], "traits": dict(by[i].get("traits", {}))}
            for i in ids]


ALL6 = ["blaze", "tide", "volt", "moss", "nova", "ember"]


def _round(seed, **params):
    return physics.run_round(seed, "marble_race", params, settings.load().render, 540, 960, 30)


# --- the core options ---------------------------------------------------------------------------

def _pair(strength, *, masses=(1.0, 1.0), immune=(False, False), **opts):
    space = pymunk.Space()
    space.gravity = (0, 0)
    balls = [physics.make_ball(space, (250, 500), 12.0, (200, 50, 50), "a", mass_mult=masses[0]),
             physics.make_ball(space, (290, 500), 12.0, (50, 50, 200), "b", mass_mult=masses[1])]
    for b, imm in zip(balls, immune):
        b.traits = {"force_immune": True} if imm else {}
    rig = Rig(fps=30)
    rig.pair_force(strength, reach=4.0, **opts)
    rig.bind(balls)
    rig.start(space, 300.0)
    for f in range(15):
        rig.before_frame(f)
        for _ in range(4):
            rig.substep(physics.Style(), list(immune), 300.0, 300.0, 1 / 120)
            space.step(1 / 120)
    return 250 - balls[0].body.position.x, balls[1].body.position.x - 290


def test_equal_and_opposite_leaves_equal_marbles_as_they_were_and_moves_the_heavy_one_less():
    assert _pair(1.0, newton=True) == pytest.approx(_pair(1.0))
    light, heavy = _pair(1.0, masses=(1.0, 1.6), newton=True)
    assert light > heavy > 0
    # the momentum each gets is the same: m * displacement
    assert light * 1.0 == pytest.approx(heavy * 1.6, rel=0.05)


def test_an_immune_marble_is_pushed_only_when_the_force_says_so():
    _, skipped = _pair(1.0, immune=(False, True))
    _, pushed = _pair(1.0, immune=(False, True), skip_immune=False)
    assert skipped == pytest.approx(0.0, abs=1e-6) and pushed > 0.5


# --- the field on screen --------------------------------------------------------------------------

def test_the_field_is_drawn_between_close_marbles_only_while_it_is_on():
    mech = {"clocks": {"on": [[0, False], [10, True]]},
            "effects": [{"kind": "field", "clock": "on", "reach": 2.3, "sign": 1}]}
    near = [(100.0, 500.0), (140.0, 500.0), (400.0, 100.0)]
    args = (near, [15.0, 15.0, 15.0], [True, True, True], (0, 0, 0), [(255, 0, 0)] * 3, 960.0)
    assert render_mech.field_marks(mech, 5, *args) == []
    marks = render_mech.field_marks(mech, 12, *args)
    assert len(marks) == 2  # one arc per marble of the one close pair; the far marble has none
    hidden = render_mech.field_marks(mech, 12, near, [15.0] * 3, [True, False, True], (0, 0, 0),
                                     [(255, 0, 0)] * 3, 960.0)
    assert hidden == []
    pull = dict(mech, effects=[{"kind": "field", "clock": None, "reach": 2.3, "sign": -1}])
    apart = [(100.0, 500.0), (160.0, 500.0), (400.0, 100.0)]
    dots = render_mech.field_marks(pull, 0, apart, *args[1:])
    assert len(dots) >= 2 and all(len(pts) == 2 for pts, _c, _w in dots)


# --- geometry -------------------------------------------------------------------------------------

@pytest.mark.parametrize("seed", [3, 700, 1234])
def test_the_corridor_is_one_marble_wide_for_the_marbles_racing(sandbox, seed):
    r = _round(seed, section="single-file-corridor", cast=_cast(ALL6))
    rec = r["style"].rig.__dict__["repel"]
    radii = [b.radius for b in r["balls"]]
    inner = rec["corridor_inner"]
    assert inner > 2 * max(radii)          # the biggest fits
    assert inner < 2 * min(radii) * 2      # two of the smallest do not fit side by side
    assert rec["corridor_legs"] >= 1


def test_the_merge_gap_is_one_marble_wide_and_off_the_middle(sandbox):
    r = _round(700, section="merge-point", cast=_cast(["blaze", "nova"]))
    x0, x1, _y = r["style"].rig.__dict__["repel"]["merge_throats"][0]
    radii = [b.radius for b in r["balls"]]
    assert 2 * max(radii) < (x1 - x0) - 2 * repel.THICK < 4 * min(radii)
    assert abs((x0 + x1) / 2 - 270) >= 14


def test_the_blocker_is_the_heaviest_marble_by_mass(sandbox):
    r = _round(700, section="heavy-blocker", cast=_cast(["ember", "blaze", "volt", "moss"]))
    names = [b.name for b in r["balls"]]
    assert names[repel.heaviest(r["balls"])] == "ember"
    assert r["winner"]


# --- the mechanics --------------------------------------------------------------------------------

def test_the_switch_pulls_first_then_pushes(sandbox):
    r = _round(701, section="repulsion-switch", cast=_cast(ALL6))
    clocks = r["style"].mech["clocks"]
    assert clocks["packing"][0][1] is True and clocks["packing"][-1][1] is False
    values = [v for _f, v in clocks["repulsion"]]
    assert values[0] == 0 and repel.KICK in values and values[-1] == 1
    kinds = {e["kind"] for e in r["style"].mech["effects"]}
    assert kinds == {"field"}


def test_the_gauntlet_takes_marbles_out_in_its_pits(sandbox):
    gone = 0
    for seed in (700, 701, 702):
        r = _round(seed, section="repulsion-gauntlet", format="elimination", cast=_cast(ALL6))
        gone += len(r.get("gone") or {})
    assert gone >= 2


def test_the_same_seed_gives_the_same_world_eight_race(sandbox):
    a = _round(9, section="marble-repulsion", cast=_cast(ALL6))
    b = _round(9, section="marble-repulsion", cast=_cast(ALL6))
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


def test_a_world_eight_clip_redraws_to_the_shipped_frames(no_ffmpeg, tmp_path):
    """The field and the corridor's walls read off the recording, in both engines."""
    for engine in ("pygame", "pil"):
        settings.load().raw["render"]["engine"] = engine
        no_ffmpeg["frames"].clear()
        no_ffmpeg["count"] = 0
        clip = physics.generate(seed=4, variant="marble_race", work_dir=tmp_path / engine,
                                params={"section": "single-file-corridor", "rounds": 1, "cast": _cast(ALL6)})
        redrawn = list(physics.PhysicsSandbox().redraw(clip.trace_path.parent))
        assert len(redrawn) == no_ffmpeg["count"]
        for i, frame in no_ffmpeg["frames"].items():
            if frame is not None:
                assert redrawn[i] == frame, f"{engine} frame {i} differs"


# --- the season -----------------------------------------------------------------------------------

WORLD8 = ("L71", "L72", "L73", "L74", "L75", "L76", "L78", "L79", "L80")


def _levels():
    path = ROOT / "channels" / "main" / "season" / "s0.yaml"
    return {lv["id"]: lv for lv in yaml.safe_load(path.read_text())["levels"]}


def test_world_eight_levels_are_ready_on_registered_mechanics_and_the_arena_one_waits():
    levels = _levels()
    for lid in WORLD8:
        lv = levels[lid]
        assert lv["status"] == "ready" and lv["blocked_on"] is None
        section = lv["params"]["section"]
        assert section in registry.MECHANICS
        stage = lv["params"].get("stage") or registry.MECHANICS[section].stage
        assert stage in registry.STAGE_BY_ID
    assert levels["L77"]["status"] == "blocked"
    assert levels["L77"]["blocked_on"] == "WP7 arena: shrinking arena (then repulsion)"


def test_world_eight_stages_are_trial():
    for sid in ("singlefile", "blockade", "mergelane", "pitfunnels", "threeramps"):
        assert registry.STAGE_BY_ID[sid].weight == 0


def test_ember_feels_the_push_and_pushes_hardest():
    ember = next(e for e in _cast(["ember"]))
    assert ember["traits"]["force_immune"] is True
    assert ember["traits"]["charge"] > 1


@pytest.mark.parametrize("lid", WORLD8)
def test_each_world_eight_level_races_from_its_params(sandbox, lid):
    lv = _levels()[lid]
    params = {**lv["params"], "cast": _cast(lv["entrants"]), "format": lv["format"]}
    rounds = physics.race_rounds(700, "marble_race", params, settings.load().render, 540, 960, 30)
    assert len(rounds) == 1 and rounds[0]["winner"]
    mech = rounds[0]["style"].mech
    assert any(e["kind"] == "field" for e in mech["effects"])
    assert all(not math.isnan(x) for st in rounds[0]["states"][-1:] for x, _y in st)
