"""World 2, Trapdoor Roulette (L11-L20): the panels and the mechanics that open them.

Each mechanic is checked for the three things docs/10 asks of one: it is a
function of the seed, it emits what it does as events, and whoever it takes
out is recorded in the Outcome. Seeds are fixed; where a test needs a race in
which something happens it searches a short, fixed range and fails if none of
them does.
"""

import hashlib
import json

import pytest

from factory import settings, stage_qa
from factory.generators import physics, stagekit
from factory.generators.physics import registry
from factory.generators.physics.worlds import trapdoor as w2
from factory.series import planning, story, trace

CAST = [
    {"id": "blaze", "name": "Blaze", "color": "#E84C4A", "traits": {"friction": 0.10, "mass_mult": 0.88}},
    {"id": "tide", "name": "Tide", "color": "#378ADD", "traits": {"friction": 0.28, "mass_mult": 1.2}},
    {"id": "volt", "name": "Volt", "color": "#F2C230", "traits": {"jitter": 3.0, "radius_mult": 0.95}},
    {"id": "moss", "name": "Moss", "color": "#97C459", "traits": {}},
]
TEAMS2 = {"blaze": 2, "tide": 2, "volt": 2, "moss": 2}
LEVELS = {
    "timer-trap": {"stage": "trapfall", "format": "elimination", "teams": TEAMS2},
    "trap-sequence": {"stage": "trapstairs", "format": "elimination", "teams": TEAMS2},
    "finish-trapdoor": {"stage": "trapline"},
    "fake-panels": {"stage": "decoys", "format": "elimination"},
    "leader-sensor-trap": {"stage": "tripwire", "format": "elimination"},
    "spiral-bowl-reverse": {"stage": "sinkhole", "format": "last_standing"},
    "relay-legs": {"stage": "relay", "teams": TEAMS2},
    "trap-timer-overlay": {"stage": "trapfall", "format": "elimination"},
    "five-trapdoors": {"stage": "trapwalk"},
    "trap-gauntlet": {"stage": "pitfall", "format": "elimination",
                      "teams": {"blaze": 3, "tide": 3, "volt": 3, "moss": 3}},
}


def _round(section, seed, **extra):
    params = {"section": section, "cast": CAST, **LEVELS[section], **extra}
    return physics.run_round(seed, "marble_race", params, settings.load().render, 540, 960, 30)


def _first(section, seeds, want, **extra):
    """The first round over `seeds` for which want(round) holds."""
    for seed in seeds:
        r = _round(section, seed, **extra)
        if want(r):
            return r
    pytest.fail(f"{section}: nothing in seeds {seeds.start}..{seeds.stop - 1} did what the test needs")


def _kinds(r):
    return [kind for _, kind, _, _ in r["mech_events"]]


def _opened(r, k):
    """Clip frames at which panel k's lid was open."""
    line = r["style"].mech["clocks"][f"trapdoor{k}_open"]
    return [f for (f, v), nxt in zip(line, line[1:] + [[len(r["states"]), None]]) if v for f in range(f, nxt[0])]


# --- registration -----------------------------------------------------------------------------

def test_every_world_two_mechanic_is_registered_on_a_trial_stage():
    for section, level in LEVELS.items():
        spec = registry.MECHANICS[section]
        assert spec.stage == level["stage"]
        stage = registry.STAGE_BY_ID[spec.stage]
        assert stage.weight == 0 and not stage.live and spec.stage not in registry.LIVE_STAGES
    for name in w2.SECTIONS:
        assert stagekit.SECTIONS[name] is w2.SECTIONS[name] and name in stagekit.SECTION_WORDS


def test_a_mechanic_on_a_stage_without_panels_says_so(sandbox):
    with pytest.raises(ValueError, match="trapdoor panels"):
        physics.run_round(3, "marble_race", {"stage": "zigzag", "section": "timer-trap"},
                          settings.load().render, 540, 960, 30)


# --- the seed decides, and only the seed ------------------------------------------------------

@pytest.mark.parametrize("section", ["timer-trap", "fake-panels", "relay-legs", "spiral-bowl-reverse"])
def test_the_same_seed_is_the_same_trapdoor_race(sandbox, section):
    a, b = _round(section, 11), _round(section, 11)
    assert a["states"] == b["states"] and a["style"].mech == b["style"].mech and a["gone"] == b["gone"]
    assert a["mech_events"] == b["mech_events"]


def test_when_the_trap_opens_does_not_depend_on_who_is_racing(sandbox):
    """Rule 2.4: rename every entrant and the hidden timer is the same."""
    renamed = [{**e, "id": e["id"] + "x", "name": e["name"] + "x"} for e in CAST]
    plain = _round("trap-timer-overlay", 5)
    other = physics.run_round(5, "marble_race", {"section": "trap-timer-overlay", "stage": "trapfall",
                                                 "format": "elimination", "cast": renamed},
                              settings.load().render, 540, 960, 30)
    assert plain["style"].mech["clocks"]["trapdoor0_open"] == other["style"].mech["clocks"]["trapdoor0_open"]
    assert plain["states"] == other["states"]


# --- each mechanic: event emitted, elimination recorded ------------------------------------------

def test_the_timer_trap_opens_once_and_what_it_takes_is_out(sandbox):
    r = _first("timer-trap", range(700, 712), lambda r: r["gone"])
    assert _kinds(r).count("trap_opened") == 1
    line = r["style"].mech["clocks"]["trapdoor0_open"]
    assert [v for _, v in line] in ([False, True, False], [False, True])
    o = physics.race_outcome([r], 30, 540)
    out = [p.entrant_id for p in o.placements if p.status == "eliminated"]
    assert set(out) == set(r["gone"]) and o.facts["eliminations"] == len(out)
    assert {e.entrant_id for e in o.events if e.kind == "trap_catch"} == set(out)
    assert all(e.data["by"] == "trapdoor" for e in o.events if e.kind == "eliminated")
    assert o.facts["teams"]["blaze.2"] == "blaze"
    # caught while it was open (or falling through as it shut behind them)
    opened = set(_opened(r, 0))
    for name, frame in r["gone"].items():
        assert any(frame - k in opened for k in range(0, 45)), name
    assert not story.failures(o, {"any_event": "trap_catch", "eliminations": ">=1"})


def test_the_overlay_draws_the_countdown_to_the_same_hidden_moment(sandbox):
    r = _round("trap-timer-overlay", 9)
    mech = r["style"].mech
    assert [e["kind"] for e in mech["effects"]] == ["countdown"]
    counts = [v for _, v in mech["clocks"]["trap_in"]]
    assert counts[-1] is None and counts[:-1] == sorted(counts[:-1], reverse=True)
    opens_at = next(f for f, v in mech["clocks"]["trapdoor0_open"] if v)
    gone_at = next(f for f, v in mech["clocks"]["trap_in"] if v is None)
    assert opens_at == gone_at


def test_three_doors_in_sequence_each_open_as_the_leader_reaches_it(sandbox):
    r = _first("trap-sequence", range(700, 710), lambda r: len(r["gone"]) >= 2)
    panels = w2.panels_of(r["style"].rig)
    assert len(panels) == 3 and [p.row for p in panels] == [0, 1, 2]
    firsts = [_opened(r, k)[0] for k in range(3)]
    assert firsts == sorted(firsts) and len(set(firsts)) == 3  # staggered, top door first
    names = [b.name for b in r["balls"]]
    for k, p in enumerate(panels):
        # the frame it opened, the lowest marble still racing was within reach of it
        f = firsts[k]
        ys = [y for i, (_, y) in enumerate(r["states"][f]) if r["gone"].get(names[i], f + 1) > f]
        assert min(ys) <= p.top + 540 * stagekit.MARBLE_R * 3.0 + 10


def test_the_finish_trapdoor_opens_only_once_someone_is_through_the_throat(sandbox):
    r = _first("finish-trapdoor", range(700, 712), lambda r: r["gone"])
    rig = r["style"].rig
    p = w2.panels_of(rig)[-1]
    first_open = _opened(r, p.index)[0]
    through = min(f for f, s in enumerate(r["states"]) if min(y for _, y in s) <= rig.finish_throat)
    assert first_open >= through
    assert p.lid - 540 * stagekit.MARBLE_R > 110  # a marble resting on it has not crossed
    o = physics.race_outcome([r], 30, 540)
    assert o.format == "race" and any(p.status == "eliminated" for p in o.placements)


def test_only_the_real_panels_ever_open(sandbox):
    r = _first("fake-panels", range(700, 712), lambda r: r["gone"])
    rig = r["style"].rig
    assert len(w2.panels_of(rig)) == 6 and len(rig.real_panels) == 2
    for p in w2.panels_of(rig):
        assert bool(_opened(r, p.index)) == (p.index in rig.real_panels)
    # every panel looks the same: one lid colour, pits drawn alike
    doors = r["style"].mech["doors"]
    assert len({tuple(d["color"]) for d in doors}) == 1


def test_the_sensor_opens_the_panel_under_the_leader(sandbox):
    r = _first("leader-sensor-trap", range(700, 712), lambda r: r["gone"])
    rig = r["style"].rig
    tripped = [(f, d) for f, kind, _, d in r["mech_events"] if kind == "sensor_tripped"]
    assert len(tripped) == 1
    frame, data = tripped[0]
    opened = [p.index for p in w2.panels_of(rig) if _opened(r, p.index)]
    assert opened == [data["panel"]]
    ys = [y for _, y in r["states"][frame]]
    leader = min(range(len(ys)), key=lambda i: ys[i])
    x = r["states"][frame][leader][0]
    p = w2.panels_of(rig)[data["panel"]]
    others = [q for q in w2.panels_of(rig) if q.row == p.row]
    assert p is min(others, key=lambda q: 0.0 if q.x0 <= x <= q.x1 else min(abs(x - q.x0), abs(x - q.x1)))
    assert 0.4 <= (926 - rig.sensor_y) / (926 - 110) <= 0.6  # the middle of the course


def test_the_bowl_is_won_by_the_last_one_out_of_the_drain(sandbox):
    r = _round("spiral-bowl-reverse", 12)
    assert r["style"].mech["no_finish"] and not r["finishes"]
    assert r["win_by"] == "survival" and r["winner"] not in r["gone"] and len(r["gone"]) == 3
    # decided: the drain does not open again under the winner
    decided = max(r["gone"].values())
    assert not [f for f in _opened(r, 0) if f > decided + 1]
    o = physics.race_outcome([r], 30, 540)
    assert o.winner == r["winner"] and o.format == "last_standing"
    assert not story.failures(o, {"eliminations": ">=3"})
    # mud on the bowl's lower slopes, drawn
    assert any(z["kind"] == "mud" for z in r["style"].mech["zones"])


def test_the_relay_hands_over_at_the_gate_and_a_fallen_runner_takes_its_teammate_out(sandbox):
    r = _first("relay-legs", range(700, 730),
               lambda r: "relay_dropped" in _kinds(r) and "handed_off" in _kinds(r))
    rig = r["style"].rig
    names = [b.name for b in r["balls"]]
    pens = {p.team: p for p in w2.pens_of(rig)}
    assert sorted(pens) == ["blaze", "moss", "tide", "volt"]
    events = r["mech_events"]
    for team, pen in pens.items():
        runner, anchor = names[pen.runner], names[pen.anchor]
        assert runner == f"{team}.1" and anchor == f"{team}.2"
        # the anchor starts in its pen, on its floor
        assert pen.floor < r["states"][0][pen.anchor][1] < pen.floor + 540 * stagekit.MARBLE_R * 1.6
        assert pen.x0 < r["states"][0][pen.anchor][0] < pen.x1
        opened = [f for f, v in r["style"].mech["clocks"][f"pen{pen.index}_shut"] if v is False]
        handed = [f for f, kind, i, _ in events if kind == "handed_off" and i == pen.runner]
        dropped = [f for f, kind, i, _ in events if kind == "relay_dropped" and i == pen.anchor]
        if handed:
            assert opened and opened[0] >= handed[0] and not dropped
        else:
            assert not opened
        if dropped:
            trapped = [f for f, kind, i, _ in events if kind == "trap_catch" and i == pen.runner]
            assert trapped and dropped[0] >= trapped[0]
    # the gate's lights are the teams that handed over
    tagged = r["style"].mech["clocks"]["relay_tagged"][-1][1]
    assert set(tagged) == {names[i] for f, kind, i, _ in events if kind == "handed_off"}
    # the finishers are anchors: a relay is won by the second leg
    assert all(n.endswith(".2") for n in r["finishes"])


def test_a_trapdoor_lid_does_not_shut_on_a_marble_falling_through_it():
    """The hold: an open lid stays open while a marble racing is over the
    pit and within reach of the lid, and shuts once none is."""
    p = w2.Panel(0, 100.0, 200.0, 300.0, 250.0, 0.0, "flat", 0)
    p.opener = lambda f: False

    class F:
        def __init__(self, y, was_open=True):
            self.positions, self.alive, self.names, self.finished = [(150.0, y)], [True], ["m"], set()
            self.values = {p.open_clock: was_open}

    assert w2._is_open(F(330.0), p, 36.0)          # resting on it as it went
    assert not w2._is_open(F(400.0), p, 36.0)      # well clear above
    assert not w2._is_open(F(330.0, was_open=False), p, 36.0)  # a shut lid stays shut
    p.holds = lambda f: False
    assert not w2._is_open(F(330.0), p, 36.0)


def test_five_doors_for_two_marbles(sandbox):
    two = CAST[:2]
    r = physics.run_round(4, "marble_race", {"section": "five-trapdoors", "stage": "trapwalk", "cast": two},
                          settings.load().render, 540, 960, 30)
    assert len(w2.panels_of(r["style"].rig)) == 5 and len(r["balls"]) == 2


def test_cycling_doors_stay_shut_while_the_caption_is_up(sandbox):
    r = _round("trap-gauntlet", 21)
    skip = int(0.6 * 30)
    for p in w2.panels_of(r["style"].rig):
        assert min(_opened(r, p.index)) >= int(w2.GRACE_S * 30) - skip


def test_a_relay_team_dropping_out_is_hidden_from_the_copy_brain():
    from factory.series.outcome import Event, Outcome, Placement

    o = Outcome(format="race", placements=[Placement(entrant_id="a", rank=1)],
                events=[Event(t_s=1.0, kind="relay_dropped", entrant_id="a"),
                        Event(t_s=1.0, kind="handed_off", entrant_id="b"),
                        Event(t_s=2.0, kind="trap_opened")])
    assert [e["kind"] for e in o.without_winner()["events"]] == ["handed_off", "trap_opened"]


def test_the_gauntlet_races_twelve_from_a_grid_and_takes_most_of_them(sandbox):
    r = _round("trap-gauntlet", 21)
    assert len(r["balls"]) == 12 and len(w2.panels_of(r["style"].rig)) == 7
    assert len({round(y) for _, y in r["states"][0]}) >= 2  # a start grid, not one row
    assert len(r["gone"]) >= 4
    o = physics.race_outcome([r], 30, 540)
    assert o.winner is not None and o.winner not in r["gone"]


# --- stage QA: a mechanism's floor holds, it does not park ---------------------------------------

def test_a_marble_waiting_in_a_shut_pen_is_held_not_parked(sandbox):
    r = _first("relay-legs", range(700, 730),
               lambda r: r["winner_frame"] is not None and any(
                   f > r["winner_frame"] for f, kind, _, _ in r["mech_events"] if kind == "handed_off"))
    race = r["states"][: r["winner_frame"] + 1]
    rig = r["style"].rig
    waiting = [p.anchor for p in w2.pens_of(rig) if p.anchor is not None
               and not any(i == p.runner and f <= r["winner_frame"]
                           for f, kind, i, _ in r["mech_events"] if kind in ("handed_off", "trap_catch"))]
    assert waiting
    for i in waiting:
        assert stage_qa._on_shut_floor(race, i, r["style"]) and not stage_qa.stuck(race, i, r["style"])


# --- the season's levels build ------------------------------------------------------------------

def test_world_two_levels_are_ready_with_params_a_task_carries():
    from factory.series import cast as series_cast
    from factory.series.season import load

    season = load("main", "s0")
    cast = series_cast.load("main")
    for n in range(11, 21):
        lv = season.level(f"L{n}")
        assert lv.status == "ready" and lv.blocked_on is None and lv.note
        params = planning.task_params(lv, season, cast)
        assert params["section"] in registry.MECHANICS
        assert params["round_params"][1] == {"stage": "same"}
        assert not story.validate(lv.story.must) and not story.identity_predicates(lv.story.must)
        from factory import captions
        assert captions.problem(lv.copy_.hook, names=tuple(lv.entrants)) is None, lv.id


def test_a_relay_redraws_to_the_shipped_frames(sandbox, tmp_path, monkeypatch):
    """The pens' team colours and the gate's lights come from the recording."""
    seen = {"count": 0, "frames": {}}

    def encode_frames(frames, *, out_path, src_size, out_size, fps):
        for i, frame in enumerate(frames):
            seen["frames"][i] = frame if i % 53 == 5 else None
            seen["count"] += 1
        out_path.write_bytes(b"")
        return out_path

    monkeypatch.setattr(physics.sandbox.encoder, "encode_frames", encode_frames)
    monkeypatch.setattr(physics.sandbox.encoder, "mux", lambda video, audio, out: out)
    settings.load().raw["render"]["engine"] = "pil"
    clip = physics.generate(seed=3, variant="marble_race", work_dir=tmp_path / "relay",
                            params={"stage": "relay", "section": "relay-legs", "cast": CAST, "teams": TEAMS2,
                                    "rounds": 1})
    _, meta = trace.read(clip.trace_path)
    mech = meta["rounds"][0]["style"]["mech"]
    pens = [d for d in mech["doors"] if (d["closed"] or "").startswith("pen")]
    assert len(pens) == 4 and all(d["color"] for d in pens)  # each pen in its team's colour
    redrawn = list(physics.PhysicsSandbox().redraw(clip.trace_path.parent))
    assert len(redrawn) == seen["count"]
    for i, frame in seen["frames"].items():
        if frame is not None:
            assert hashlib.sha256(redrawn[i]).digest() == hashlib.sha256(frame).digest(), f"frame {i}"
    assert json.dumps(mech, sort_keys=True)
