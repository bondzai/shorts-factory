"""WP7 core: the mechanics hooks (generators/mechanics.py) and what uses them.

Three promises are tested here before any mechanic is: a race that asks for
nothing renders exactly what it did before (pinned hashes), a race that asks
for something is still a function of its seed, and a redraw from the trace
is the shipped frame.
"""

import hashlib
import json
import math
import platform
import sys

import pymunk
import pytest

from factory import settings, stage_qa
from factory.generators import mechanics, physics
from factory.generators.mechanics import Rig, clock_at, expand_teams, shade
from factory.generators.physics import build as physics_build
from factory.generators.physics import registry
from factory.series import planning, story, trace
from factory.series.outcome import Outcome, Placement

CAST = [
    {"id": "blaze", "name": "Blaze", "color": "#E84C4A", "traits": {"friction": 0.10, "mass_mult": 0.88}},
    {"id": "tide", "name": "Tide", "color": "#378ADD", "traits": {"friction": 0.28, "mass_mult": 1.2}},
    {"id": "volt", "name": "Volt", "color": "#F2C230", "traits": {"jitter": 3.0, "radius_mult": 0.95}},
    {"id": "moss", "name": "Moss", "color": "#97C459", "traits": {}},
]


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


@pytest.fixture
def mechanic(monkeypatch):
    """Register a level `section` for one test: mechanic(name, apply, stage=None)."""
    def add(name, apply, stage=None):
        monkeypatch.setitem(registry.MECHANICS, name, registry.Mechanic(name, apply, stage=stage))
        return name
    return add


def _hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _race(tmp_path, name, seed, **params):
    return physics.generate(seed=seed, variant="marble_race", params=params, work_dir=tmp_path / name)


# --- 1. nothing existing changes ------------------------------------------------------------

# trace.npz / trace.json of races that ask for no mechanics, recorded on the
# code before WP7 (main at 6bdba9f) and unchanged by it. Frames, audio and
# facts of these and eight more races were compared byte for byte too; the
# trace is what is pinned, because it is what a redraw is made from. A
# float from pymunk may differ in its last bit on another CPU, so the pins
# are per platform: on one with none recorded the test says so and skips.
PINS = {
    ("darwin", "arm64"): {
        "zigzag-2r": ("f7130cd385bbfd47cf8ed7a7dcaab1ac04f8de0401bca42bf7f18a5c0284ac49",
                      "ee864002fc37dab720941621035c488f89e6013e7721c88cd292db8bdc42c16d"),
        "lodestone-cast": ("e005964b4198a87c66064f053cacf4c6e607f11cd1eff253236ce0cd3a22c4a3",
                           "f895fc80b77f7409dbeebe66944b112eb4bebec876e78ee9dc9d7d6f1fea386b"),
        "trapdoor-cast": ("f6e0cc9b358841c73d14c02c779b5898a559eb888a924dd40f75f06e946fb001",
                          "b3f85b40f154549db7959017fe45a2b94dc0ad2bea26bc9c67914ade0f17be96"),
        "rockers-pil": ("0482f3192452aad61fd2bcf613c98f92b0b059400484a92d099645322453efa7",
                        "0c9587fd9cdb512ca511087a4d448a8048fd86cb03ebb1bd4f66eacf69060e7f"),
    },
}
PINNED_RACES = {
    "zigzag-2r": ("pygame", 7, {"stage": "zigzag", "rounds": 2}),
    "lodestone-cast": ("pygame", 11, {"stage": "lodestone", "rounds": 1, "cast": CAST}),
    "trapdoor-cast": ("pygame", 23, {"stage": "trapdoor", "rounds": 1, "cast": CAST}),
    "rockers-pil": ("pil", 3, {"stage": "rockers", "rounds": 1}),
}


@pytest.mark.parametrize("name", sorted(PINNED_RACES))
def test_a_race_without_mechanics_writes_the_trace_it_wrote_before(no_ffmpeg, tmp_path, name):
    pins = PINS.get((sys.platform, platform.machine()))
    if pins is None:
        pytest.skip(f"no trace pins recorded for {sys.platform}/{platform.machine()}")
    engine, seed, params = PINNED_RACES[name]
    settings.load().raw["render"]["engine"] = engine
    # The presentation adds its own time map to the trace; these pins are the
    # race as it was drawn before it (off is byte-identical: test_presentation).
    settings.load().raw["presentation"]["enabled"] = False
    clip = _race(tmp_path, name, seed, **params)
    folder = clip.trace_path.parent
    # The closing ask's words replaced a flag in trace.json (factory/captions);
    # read back as the flag it was, the file is the one pinned.
    meta = json.loads((folder / trace.JSON).read_text())
    meta["ask"] = bool(meta["ask"])
    was = hashlib.sha256((json.dumps(meta, sort_keys=True, indent=1) + "\n").encode()).hexdigest()
    assert (_hash(folder / trace.NPZ), was) == pins[name]


def test_an_idle_rig_is_not_live_and_leaves_no_mech_in_the_trace(no_ffmpeg, tmp_path):
    clip = _race(tmp_path, "plain", 7, stage="zigzag", rounds=1)
    _, meta = trace.read(clip.trace_path)
    assert "mech" not in meta["rounds"][0]["style"] and "rig" not in meta["rounds"][0]["style"]
    assert Rig(params={"format": "race"}).live is False
    assert Rig(params={"format": "elimination"}).live is True


def test_a_polarity_clock_held_at_one_is_the_old_magnet(sandbox, mechanic):
    """The force path the rig takes computes the magnet law exactly as the
    old path did: held at +1 it moves nothing by a single bit."""
    cfg = settings.load().render
    plain = physics.run_round(11, "marble_race", {"stage": "lodestone"}, cfg, 540, 960, 30)

    def steady(rig, space, style, balls, w, h):
        rig.clock("polarity", lambda f: 1)
        rig.magnet_polarity("polarity")

    same = physics.run_round(11, "marble_race", {"stage": "lodestone", "section": mechanic("steady", steady)},
                             cfg, 540, 960, 30)
    assert same["states"] == plain["states"]
    assert same["style"].mech["magnet_clock"] == "polarity"

    def flipped(rig, space, style, balls, w, h):
        rig.at("polarity", t=3.0, before=1, after=-1)
        rig.magnet_polarity("polarity")

    flip = physics.run_round(11, "marble_race", {"stage": "lodestone", "section": mechanic("flip", flipped)},
                             cfg, 540, 960, 30)
    assert flip["states"] != plain["states"]
    skip = int(0.6 * 30)
    assert flip["style"].mech["clocks"]["polarity"] == [[0, 1], [90 - skip, -1]]


# --- 2. elimination ----------------------------------------------------------------------------

def _pits(rig, space, style, balls, w, h):
    """Two always-open pits in the lower third; bypass through the middle."""
    rig.out_zone((10, 200, w * 0.38, 330), label="pit", event="trap_catch")
    rig.out_zone((w * 0.62, 200, w - 10, 330), label="pit")


def _floor(rig, space, style, balls, w, h):
    """No line, and the bottom of the frame is out: the last marble left wins."""
    rig.no_finish_line()
    rig.out_zone((0, 0, w, 160), label="floor")


def test_an_out_zone_eliminates_and_ranks_the_last_out_best(no_ffmpeg, tmp_path, mechanic):
    name = mechanic("pits", _pits, stage="lodestone")
    for seed in (1, 2, 3, 4):
        clip = _race(tmp_path, f"e{seed}", seed, section=name, format="elimination", cast=CAST, rounds=1)
        o = clip.outcome
        out = [p for p in o.placements if p.status == "eliminated"]
        if not out:
            continue
        assert o.format == "elimination" and o.facts["eliminations"] == len(out)
        gone_t = {e.entrant_id: e.t_s for e in o.events if e.kind == "eliminated"}
        assert set(gone_t) == {p.entrant_id for p in out}
        # later out ranks better; everyone who stayed in ranks above all of them
        ordered = sorted(out, key=lambda p: p.rank)
        assert [gone_t[p.entrant_id] for p in ordered] == sorted(gone_t.values(), reverse=True)
        assert max(p.rank for p in o.placements if p.status != "eliminated") < min(p.rank for p in out)
        # the left pit names its extra event kind; both say what took them out
        assert {e.entrant_id for e in o.events if e.kind == "trap_catch"} <= set(gone_t)
        assert all(e.data["by"] == "pit" for e in o.events if e.kind == "eliminated")
        assert not story.failures(o, {"eliminations": f">={len(out)}"})
        assert story.failures(o, {"eliminations": f">={len(out) + 1}"})
        assert clip.facts["rounds"][0]["eliminated"]
        assert "eliminated" in clip.description
        break
    else:
        pytest.fail("no seed in four eliminated anyone")


def test_last_standing_is_decided_by_who_is_left(sandbox, mechanic):
    cfg = settings.load().render
    name = mechanic("floor", _floor, stage="funnels")
    r = physics.run_round(5, "marble_race", {"section": name, "format": "last_standing", "cast": CAST},
                          cfg, 540, 960, 30)
    assert r["style"].mech["no_finish"] and not r["finishes"]
    assert r["win_by"] == "survival" and r["winner"] not in r["gone"]
    assert len(r["gone"]) == len(CAST) - 1
    o = physics.race_outcome([r], 30, 540)
    assert o.format == "last_standing" and o.winner == r["winner"]
    assert [p.status for p in o.placements] == ["running"] + ["eliminated"] * 3
    last_out = max(r["gone"], key=r["gone"].get)
    assert o.placements[1].entrant_id == last_out


def test_an_elimination_race_redraws_to_the_shipped_frames(no_ffmpeg, tmp_path, mechanic):
    def everything(rig, space, style, balls, w, h):
        _pits(rig, space, style, balls, w, h)
        rig.countdown("left", 5.0)
        rig.effect("countdown", clock="left", at=(w / 2, h * 0.8))
        rig.window("dark", t0=2.0, t1=3.0)
        rig.effect("blackout", clock="dark")
        rig.zone((20, 400, w - 20, 470), kind="sand")
        rig.zone((20, 520, w - 20, 560), kind="ice", friction=0.0)
        rig.surface(space, (30, 600), (150, 580), kind="ice")
        rig.breakable(space, (w - 150, 640), (w - 30, 620))
        rig.clock("gate", lambda f: [f.names[int(f.t) % len(f.names)]])
        rig.cycle("shut", 2.0, on=0.4)
        rig.door(space, (w * 0.35, 720), (w * 0.65, 720), closed="shut", passes="gate", color=(255, 200, 80))
        rig.at("polarity", progress=0.5, before=1, after=-1)
        rig.magnet_polarity("polarity")

    name = mechanic("everything", everything, stage="lodestone")
    for engine in ("pygame", "pil"):
        settings.load().raw["render"]["engine"] = engine
        no_ffmpeg["frames"].clear()
        no_ffmpeg["count"] = 0
        clip = _race(tmp_path, engine, 3, section=name, format="elimination", cast=CAST, rounds=1)
        _, meta = trace.read(clip.trace_path)
        mech = meta["rounds"][0]["style"]["mech"]
        assert {"clocks", "zones", "surfaces", "breakables", "doors", "effects"} <= set(mech)
        redrawn = list(physics.PhysicsSandbox().redraw(clip.trace_path.parent))
        assert len(redrawn) == no_ffmpeg["count"]
        for i, frame in no_ffmpeg["frames"].items():
            if frame is not None:
                assert redrawn[i] == frame, f"{engine} frame {i} differs"


def test_the_same_seed_gives_the_same_mechanics(sandbox, mechanic):
    cfg = settings.load().render

    def seeded(rig, space, style, balls, w, h):
        x = rig.rng.uniform(40, w - 200)
        rig.out_zone((x, 200, x + 160, 320))
        rig.breakable(space, (40, 600), (200, 560))

    name = mechanic("seeded", seeded, stage="lodestone")
    a, b = (physics.run_round(8, "marble_race", {"section": name, "format": "elimination"}, cfg, 540, 960, 30)
            for _ in range(2))
    assert a["states"] == b["states"] and a["style"].mech == b["style"].mech and a["gone"] == b["gone"]


def test_an_unknown_section_is_ignored_as_it_always_was(sandbox):
    cfg = settings.load().render
    plain = physics.run_round(4, "marble_race", {"stage": "zigzag"}, cfg, 540, 960, 30)
    named = physics.run_round(4, "marble_race", {"stage": "zigzag", "section": "no-such-thing"}, cfg, 540, 960, 30)
    assert named["states"] == plain["states"] and not named["style"].mech


# --- 3. clocks ----------------------------------------------------------------------------------

def test_clocks_are_recorded_as_change_points_and_shifted_by_the_skip():
    rig = Rig(fps=10)
    rig.at("switch", t=1.0, before="a", after="b")
    rig.cycle("gate", 1.0, on=0.5)
    rig.countdown("left", 2.0)
    rig.window("dark", p0=0.5)
    rig.bind([])
    rig._start_y = 900.0
    for f in range(30):
        rig.before_frame(f)
    snap = rig.snapshot(skip=3)
    assert snap["clocks"]["switch"] == [[0, "a"], [7, "b"]]
    assert snap["clocks"]["gate"][:3] == [[0, True], [2, False], [7, True]]
    assert snap["clocks"]["left"] == [[0, 2], [7, 1], [17, None]]
    assert snap["clocks"]["dark"] == [[0, False]]  # no marbles: no progress
    assert clock_at(snap, "switch", 6) == "a" and clock_at(snap, "switch", 7) == "b"
    assert clock_at(snap, "missing", 3, default=9) == 9


def _space_with(*balls_at, radius=12.0):
    space = pymunk.Space()
    space.gravity = (0, -300)
    balls = [physics.make_ball(space, pos, radius, (200, 50, 50), f"m{i}") for i, pos in enumerate(balls_at)]
    return space, balls


def _run(rig, space, frames, fps=30, start=0):
    for f in range(start, start + frames):
        rig.before_frame(f)
        for _ in range(4):
            if rig.pushes:
                rig.substep(physics.Style(), [False] * len(rig.balls), 300.0, 300.0, 1 / (fps * 4))
            space.step(1 / (fps * 4))
        rig.after_frame(f)


# --- 4. surfaces ---------------------------------------------------------------------------------

def test_a_sand_zone_drags_and_a_friction_zone_sets_friction_while_inside():
    space, balls = _space_with((100, 500), (400, 500))
    space.gravity = (0, 0)
    for b in balls:
        b.body.velocity = (0, -200)
    rig = Rig(fps=30)
    rig.zone((0, 0, 250, 1000), kind="sand")
    rig.zone((300, 0, 540, 1000), kind="ice", friction=0.01, damping=0.0)
    rig.bind(balls)
    rig.start(space, 300.0)
    _run(rig, space, 10)
    slow, free = balls[0].body.velocity.length, balls[1].body.velocity.length
    assert free == pytest.approx(200.0) and slow < 200.0 * math.exp(-1.4 * 10 / 30) * 1.01
    assert next(iter(balls[1].body.shapes)).friction == 0.01
    assert next(iter(balls[0].body.shapes)).friction == 0.22


def test_a_cobweb_catches_only_the_first_marble_in():
    space, balls = _space_with((100, 520), (100, 600))
    rig = Rig(fps=30)
    rig.zone((0, 0, 540, 500), kind="cobweb", first_only=True, event="webbed")
    rig.bind(balls)
    rig.start(space, 300.0)
    _run(rig, space, 60)
    assert [e[1:3] for e in rig.events] == [("webbed", 0)]


def test_thin_ice_breaks_under_a_seeded_load():
    def once():
        space, balls = _space_with((100, 520))
        rig = Rig(seed=4, fps=30)
        rig.breakable(space, (40, 500), (200, 500), hold=(0.5, 0.9))
        rig.bind(balls)
        rig.start(space, 300.0)
        _run(rig, space, 90)
        return rig, balls
    rig, balls = once()
    br = rig.breakables[0]
    assert br.broke is not None and br.cracked is not None and br.cracked <= br.broke
    assert [e[1] for e in rig.events] == ["broke"]
    assert balls[0].body.position.y < 450  # fell through
    assert once()[0].breakables[0].broke == br.broke
    snap = rig.snapshot()
    assert snap["breakables"][0]["broke"] == br.broke


# --- 5. filters and forces -----------------------------------------------------------------------

def test_a_door_is_solid_for_everyone_but_whom_it_passes():
    space, balls = _space_with((100, 520), (300, 520))
    rig = Rig(fps=30)
    rig.door(space, (20, 480), (500, 480), passes=["m1"])
    rig.bind(balls)
    rig.start(space, 300.0)
    _run(rig, space, 60)
    assert balls[0].body.position.y > 480 > balls[1].body.position.y


def test_a_door_on_a_clock_opens_for_everyone():
    space, balls = _space_with((100, 520))
    rig = Rig(fps=30)
    rig.at("open", t=1.0, before=True, after=False)
    rig.door(space, (20, 480), (500, 480), closed="open")
    rig.bind(balls)
    rig.start(space, 300.0)
    _run(rig, space, 20)
    assert balls[0].body.position.y > 480
    _run(rig, space, 40, start=20)
    assert balls[0].body.position.y < 480


def test_pair_forces_push_apart_pull_together_and_skip_the_immune():
    def gap(strength, immune=False):
        space, balls = _space_with((250, 500), (290, 500))
        space.gravity = (0, 0)
        if immune:
            balls[0].traits = {"force_immune": True}
            balls[1].traits = {"force_immune": True}
        rig = Rig(fps=30)
        rig.pair_force(strength, reach=4.0)
        rig.bind(balls)
        rig.start(space, 300.0)
        for f in range(15):
            rig.before_frame(f)
            for _ in range(4):
                rig.substep(physics.Style(), [bool(b.traits.get("force_immune")) for b in balls], 300.0, 300.0, 1 / 120)
                space.step(1 / 120)
        return balls[1].body.position.x - balls[0].body.position.x
    assert gap(1.0) > 40.5 and gap(-1.0) < 40.0 and gap(1.0, immune=True) == pytest.approx(40.0)


# --- 1b. more entrants and teams --------------------------------------------------------------------

def test_teams_expand_to_shaded_twins_with_a_team():
    field = expand_teams(CAST, {"blaze": 2, "tide": 3})
    assert [e["id"] for e in field] == ["blaze.1", "blaze.2", "tide.1", "tide.2", "tide.3", "volt.1", "moss.1"]
    assert {e["team"] for e in field} == {"blaze", "tide", "volt", "moss"}
    assert field[0]["color"] == "#E84C4A" and len({e["color"] for e in field[:2]}) == 2
    assert shade((100, 100, 100), 2) != shade((100, 100, 100), 3)
    with pytest.raises(ValueError, match="not in the race"):
        expand_teams(CAST, {"ember": 2})
    with pytest.raises(ValueError, match="at most 12"):
        expand_teams(CAST, {"blaze": 4, "tide": 4, "volt": 4})


def test_twelve_marbles_start_from_a_grid_and_a_team_race_keeps_its_teams(sandbox):
    cfg = settings.load().render
    r = physics.run_round(5, "marble_race", {"stage": "plinko", "cast": CAST,
                                             "teams": {"blaze": 3, "tide": 3, "volt": 3, "moss": 3}},
                          cfg, 540, 960, 30)
    assert len(r["balls"]) == 12 and len({b.name for b in r["balls"]}) == 12
    first = r["states"][0]
    assert len({round(y) for _, y in first}) >= 1
    o = physics.race_outcome([r], 30, 540)
    assert o.facts["teams"]["blaze.2"] == "blaze" and len(o.placements) == 12
    with pytest.raises(ValueError, match="at most 12"):
        physics.run_round(5, "marble_race", {"stage": "plinko", "cast": CAST * 4}, cfg, 540, 960, 30)


def test_a_start_grid_that_reaches_the_structure_is_refused():
    space = pymunk.Space()
    physics_build.wall(space, (4, 0), (4, 960))
    physics_build.wall(space, (536, 0), (536, 960))
    physics_build.wall(space, (4, 958), (536, 958))
    xs, ys = physics_build.start_grid(space, 540, 960, 12, 28.0, 62.0, "open")
    assert len(xs) == 12 and len(set(ys)) == 2
    assert min(xs) >= 28 + 6 and max(xs) <= 540 - 28 - 6
    physics_build.peg(space, 270, 880, 30)
    with pytest.raises(ValueError, match="has no room for 12 marbles"):
        physics_build.start_grid(space, 540, 960, 12, 28.0, 62.0, "crowded")


# --- 6. rounds ----------------------------------------------------------------------------------------

def test_three_rounds_and_per_round_transforms(no_ffmpeg, tmp_path):
    clip = _race(tmp_path, "three", 9, stage="plinko", rounds=3, cast=CAST,
                 round_params=[{}, {"stage": "same", "layout": 0, "mirror": True}, {"friction": 0.5}])
    arrays, meta = trace.read(clip.trace_path)
    assert len(meta["rounds"]) == 3 and "round2_positions" in arrays
    starts = [e.data["round"] for e in clip.outcome.events if e.kind == "round_start"]
    assert starts == [0, 1, 2]
    heat, mirror = meta["rounds"][0]["style"], meta["rounds"][1]["style"]
    assert mirror["stage"] == heat["stage"] == "plinko"
    assert sorted((round(540 - x, 6), round(y, 6)) for x, y, _ in heat["circles"]) == \
        sorted((round(x, 6), round(y, 6)) for x, y, _ in mirror["circles"])
    assert "Three rounds" in clip.description
    assert len(list(physics.PhysicsSandbox().redraw(clip.trace_path.parent))) == no_ffmpeg["count"]
    with pytest.raises(ValueError, match="at most 3"):
        physics.race_rounds(9, "marble_race", {"stage": "plinko", "rounds": 4}, settings.load().render, 540, 960, 30)


def test_two_rounds_without_round_params_are_the_final_they_always_were(sandbox):
    cfg = settings.load().render
    two = physics.race_rounds(7, "marble_race", {"stage": "zigzag", "rounds": 2}, cfg, 540, 960, 30)
    three = physics.race_rounds(7, "marble_race", {"stage": "zigzag", "rounds": 3}, cfg, 540, 960, 30)
    assert [r["states"] for r in two] == [r["states"] for r in three[:2]]
    assert three[2]["style"].stage not in {two[0]["style"].stage, two[1]["style"].stage}


def test_a_trapdoor_stage_refuses_a_mirror(sandbox):
    with pytest.raises(ValueError, match="cannot be mirrored"):
        physics.run_round(3, "marble_race", {"stage": "trapdoor", "mirror": True}, settings.load().render,
                          540, 960, 30)


# --- 7-9. story, planning, stage QA -------------------------------------------------------------------

def test_eliminations_is_a_mechanism_predicate():
    assert "eliminations" in story.MECHANISM and "eliminations" not in story.IDENTITY
    assert story.validate({"eliminations": ">=2"}) == []
    assert story.validate({"eliminations": "lots"})
    o = Outcome(format="elimination", placements=[
        Placement(entrant_id="a", rank=1), Placement(entrant_id="b", rank=2, status="eliminated"),
        Placement(entrant_id="c", rank=3, status="eliminated")])
    assert story.failures(o, {"eliminations": ">=2"}) == []
    assert story.failures(o, {"eliminations": ">=3"})


def test_a_level_can_carry_the_mechanics_params():
    assert {"teams", "win", "mechanics", "round_params"} <= planning.PARAM_KEYS


def test_stage_qa_measures_an_elimination_race(sandbox, mechanic):
    name = mechanic("pits", _pits)
    rep = stage_qa.run("lodestone", [1, 2, 3], params={"section": name, "format": "elimination"})
    assert rep.elimination and len(rep.elim_counts) == rep.finished == len(rep.finisher_counts)
    assert sum(rep.elim_counts) > 0 and rep.decided == rep.finished
    row = stage_qa.elimination_row(rep)
    assert row.startswith("| `lodestone` | 3/3 |")
    plain = stage_qa.run("lodestone", [1])
    assert not plain.elimination and plain.elim_counts == []


def timer_trap(rig, space, style, balls, w, h):
    """docs/10-mechanics.md's worked example, verbatim."""
    if not style.traps:
        raise ValueError("timer-trap needs a stage with a trapdoor")
    at = float(rig.knob("open_at") or rig.rng.uniform(5.0, 9.0))  # seeded, never steered
    rig.window("sprung", t0=at, t1=at + 1.0)
    for hx, hy, bore, depth, _period, _phase in style.traps:
        rig.out_zone((hx, hy, hx + bore, hy + depth), when="sprung",
                     event="trap_catch", label="trapdoor")
    if rig.knob("show_timer", False):          # L18: the countdown on screen
        rig.countdown("trap_in", at)
        rig.effect("countdown", clock="trap_in", at=(w / 2, h * 0.82))


def test_the_worked_example_springs_the_trapdoor(sandbox, mechanic):
    name = mechanic("timer-trap", timer_trap, stage="trapdoor")
    rep = stage_qa.run("trapdoor", range(700, 712),
                       params={"section": name, "format": "elimination", "mechanics": {"show_timer": True}})
    assert rep.finished >= 10 and sum(rep.elim_counts) >= 1
    with pytest.raises(ValueError, match="needs a stage with a trapdoor"):
        physics.run_round(1, "marble_race", {"stage": "zigzag", "section": name}, settings.load().render,
                          540, 960, 30)


def test_hidden_marbles_and_blackouts_read_off_the_recording():
    mech = {"gone": {"a": 10}, "clocks": {"dark": [[0, False], [20, True], [30, False]]},
            "effects": [{"kind": "blackout", "clock": "dark"}]}
    assert not mechanics.hidden(mech, "a", 9) and mechanics.hidden(mech, "a", 10)
    assert not mechanics.hidden(mech, "b", 19) and mechanics.hidden(mech, "b", 25)
    assert not mechanics.hidden(mech, "b", 30)
