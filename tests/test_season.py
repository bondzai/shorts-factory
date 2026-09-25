"""The series layer's season half: check, plan, render wiring, standings,
surfaces (CLI, MCP, Telegram) and trace retention. docs/08-series-layer.md."""

import copy
import datetime as dt
import json

import pytest
import yaml

from factory import channels, db, gc, generators, pipeline, seasons, settings, tasks, telegram
from factory.cli import main as cli_main
from factory.generators import GeneratedClip
from factory.models import APPROVED, AWAITING_APPROVAL, PUBLISHED, QC_REJECTED
from factory.series import cast as cast_mod, check, planning, season as season_mod, standings
from factory.series.outcome import Outcome, Placement

CH = "main"

CAST = """
[[entrant]]
id = "blaze"
name = "Blaze"
color = "#E84C4A"
traits = { friction = 0.18 }

[[entrant]]
id = "tide"
name = "Tide"
color = "#2E86DE"

[[entrant]]
id = "volt"
name = "Volt"
color = "#F5C518"

[[entrant]]
id = "moss"
name = "Moss"
color = "#3FA34D"
debut = "L03"

[[entrant]]
id = "ghost"
name = "Ghost"
color = "#EEEEEE"
debut = "L02"
scores = false
"""


def level(n, **over):
    base = {
        "id": f"L{n:02d}", "date": f"2026-10-{n:02d}", "world": "gravity",
        "generator": "physics", "variant": "marble_race",
        "params": {"stage": ["zigzag", "funnels", "bumpers", "pegboard"][n % 4]},
        "entrants": [["tide", "volt"], ["blaze", "tide", "volt"], ["blaze", "tide"]][n % 3],
        "format": "race",
        "story": {"must": {"lead_changes": f">={n % 3}"}, "prefer": {"margin_s": "<=0.8"}},
        "copy": {"title": "Marble Race: {leader_name} leads by {standing:blaze}"},
    }
    base.update(over)
    return base


def season_dict(levels):
    return {"id": "s0", "title": "Season 0", "channel": CH, "levels": levels}


def write_season(root, levels, cast=CAST, scoring=None):
    d = root / "channels" / CH
    (d / "season").mkdir(parents=True, exist_ok=True)
    (d / "season" / "s0.yaml").write_text(yaml.safe_dump(season_dict(levels), sort_keys=False))
    if cast is not None:
        (d / "cast.toml").write_text(cast)
    if scoring is not None:
        (d / "scoring.toml").write_text(scoring)


@pytest.fixture
def chan(sandbox):
    with db.connect() as conn:
        channels.create(conn, name="Main", channel_id=CH)
    write_season(sandbox, [level(n) for n in range(1, 6)])
    return sandbox


def run_check(levels, *, cast_text=CAST, allow_identity=False, variants=None, stages=None):
    s = season_mod.Season(**season_dict(levels))
    c = None
    if cast_text is not None:
        import tomllib
        c = cast_mod.Cast(entrants=[cast_mod.Entrant(**e) for e in tomllib.loads(cast_text)["entrant"]])
    return check.check(s, c, stages=stages if stages is not None else {"zigzag", "funnels", "bumpers", "pegboard"},
                       allow_identity=allow_identity, channel_variants=variants)


def msgs(problems, level_id=None):
    return [p.message for p in problems if level_id is None or p.level_id == level_id]


# --- check -------------------------------------------------------------------

def test_a_clean_season_has_no_problems():
    assert run_check([level(n) for n in range(1, 6)]) == []


def test_entrants_must_exist_and_have_debuted():
    probs = run_check([level(1, entrants=["blaze", "nobody"]), level(2, entrants=["moss", "tide"])])
    assert any("'nobody' is not in the cast" in m for m in msgs(probs, "L01"))
    assert any("before their debut L03" in m for m in msgs(probs, "L02"))


def test_identity_predicates_are_errors_unless_allowed():
    lv = level(1, story={"must": {"winner_not_in": ["blaze"]}, "prefer": {"rank_of": {"tide": "<=2"}}})
    probs = run_check([lv])
    assert sum("chooses who wins" in m for m in msgs(probs)) == 2
    assert not any("chooses who wins" in m for m in msgs(run_check([lv], allow_identity=True)))


def test_story_blocks_are_validated():
    probs = run_check([level(1, story={"must": {"lead_changes": "lots"}, "prefer": {"vibes": 1}})])
    assert any("story.must" in m and "not a comparison" in m for m in msgs(probs))
    assert any("story.prefer" in m and "unknown predicate" in m for m in msgs(probs))


def test_consecutive_levels_must_differ_in_two_ways():
    a = level(1)
    b = level(2, params=a["params"], entrants=a["entrants"], story=a["story"], format="elimination")
    probs = run_check([a, b])
    assert any("fewer than two" in m for m in msgs(probs, "L02"))
    b["story"] = {"must": {"any_event": "launched"}}
    assert not any("fewer than two" in m for m in msgs(run_check([a, b])))


def test_section_counts_as_part_of_the_stage():
    a = level(1, params={"stage": "zigzag"})
    b = level(2, params={"stage": "zigzag", "section": "magnet-flip"}, entrants=a["entrants"],
              story={"must": {"any_event": "launched"}})
    assert not any("fewer than two" in m for m in msgs(run_check([a, b])))


def test_same_stage_and_entrants_within_ten_levels_needs_rematch_of():
    levels = [level(n) for n in range(1, 10)]
    levels[8] = level(9, params=levels[0]["params"], entrants=levels[0]["entrants"])
    probs = run_check(levels)
    assert any("same stage and entrants as L01" in m for m in msgs(probs, "L09"))
    levels[8]["rematch_of"] = "L01"
    assert not any("same stage" in m for m in msgs(run_check(levels)))


def test_at_most_one_rematch_in_ten_levels_and_it_must_look_back():
    levels = [level(n) for n in range(1, 8)]
    levels[3]["rematch_of"] = "L01"
    levels[5]["rematch_of"] = "L02"
    levels[6]["rematch_of"] = "L09"
    probs = run_check(levels)
    assert any("second rematch" in m for m in msgs(probs))
    assert any("not an earlier level" in m for m in msgs(probs, "L07"))


def test_status_rules():
    probs = run_check([
        level(1, status="blocked"),
        level(2, status="needs_input"),
        level(3, operator_input={"flip_at": None}),
        level(4, status="needs_input", operator_input={"flip_at": None}),
    ])
    assert any("needs blocked_on" in m for m in msgs(probs, "L01"))
    assert any("nothing left to fill" in m for m in msgs(probs, "L02"))
    assert any("should be needs_input" in m for m in msgs(probs, "L03"))
    assert msgs(probs, "L04") == []


def test_dates_do_not_go_backwards_and_anchors_hold():
    levels = [level(n) for n in range(1, 4)]
    levels[2]["date"] = "2026-09-30"
    assert any("before L02" in m for m in msgs(run_check(levels), "L03"))
    l37 = level(37, date="2026-11-01")
    assert any("anchored to 2026-10-31" in m for m in msgs(run_check([l37])))
    assert run_check([level(37, date="2026-10-31")]) == []


def test_unknown_stage_unless_blocked_and_channel_variants():
    probs = run_check([level(1, params={"stage": "moonbase"})])
    assert any("no physics stage 'moonbase'" in m for m in msgs(probs))
    blocked = level(1, params={"stage": "moonbase"}, status="blocked", blocked_on="WP7 moon")
    assert run_check([blocked]) == []
    probs = run_check([level(1)], variants=["battle/arena"])
    assert any("not allowed" in m for m in msgs(probs))


def test_copy_hints_carry_no_draft_numbers_and_only_known_placeholders():
    probs = run_check([level(1, copy={
        "title": "Race 7: {margin_s}s apart",
        "pin": "{h2h:blaze:tide} and {standing:zed} and {winner}",
        "hook": "{entrant_count} marbles, {lead_changes} swaps",
    })])
    m = msgs(probs)
    assert any("copy.title" in x and "digit" in x for x in m)
    assert any("'zed', not in the cast" in x for x in m)
    assert any("unknown placeholder {winner}" in x for x in m)
    assert not any("copy.hook" in x for x in m)


def test_a_file_that_does_not_load_is_one_error(chan):
    (chan / "channels" / CH / "season" / "s0.yaml").write_text("id: s0\nlevels: nope\n")
    with db.connect() as conn:
        out = seasons.check(conn, channels.get(conn, CH))
    assert len(out["problems"]) == 1 and out["problems"][0].severity == "error"


def test_check_registers_the_season(chan):
    with db.connect() as conn:
        out = seasons.check(conn, channels.get(conn, CH))
        row = conn.execute("SELECT * FROM seasons").fetchone()
    assert out["problems"] == []
    assert (row["channel_id"], row["id"], row["title"]) == (CH, "s0", "Season 0")


# --- plan --------------------------------------------------------------------

def test_parse_levels():
    assert planning.parse_levels("L01..L03") == ["L01", "L02", "L03"]
    assert planning.parse_levels("L03, L05,L03") == ["L03", "L05"]
    assert planning.parse_levels("L08..L10,L99") == ["L08", "L09", "L10", "L99"]
    with pytest.raises(ValueError):
        planning.parse_levels("L05..L01")
    with pytest.raises(ValueError):
        planning.parse_levels("level 3")


def test_plan_queues_one_task_per_ready_level_with_the_contract_params(chan):
    levels = [level(n) for n in range(1, 6)]
    levels[1].update(status="blocked", blocked_on="WP7 magnets")
    levels[2].update(status="needs_input", operator_input={"flip_at": None})
    write_season(chan, levels)
    with db.connect() as conn:
        out = seasons.plan(conn, channels.get(conn, CH), "L01..L04")
        by = {r["level"]: r for r in out}
        assert by["L01"]["queued"] and by["L04"]["queued"]
        assert "blocked: WP7 magnets" in by["L02"]["reason"]
        assert "flip_at" in by["L03"]["reason"]
        task = db.get_task(conn, by["L01"]["task_id"])
        params = json.loads(task["params_json"])
        assert params["generator"] == "physics" and params["variant"] == "marble_race"
        assert params["stage"] == levels[0]["params"]["stage"]
        assert [e["id"] for e in params["cast"]] == ["blaze", "tide", "volt"]
        assert params["cast"][0] == {"id": "blaze", "name": "Blaze", "color": "#E84C4A",
                                     "traits": {"friction": 0.18}}
        assert params["story"] == {"must": {"lead_changes": ">=1"}, "prefer": {"margin_s": "<=0.8"}}
        assert (params["level_id"], params["season_id"], params["format"]) == ("L01", "s0", "race")
        row = planning.level_row(conn, CH, "s0", "L01")
        assert (row["status"], row["task_id"]) == ("planned", task["id"])
        assert conn.execute("SELECT COUNT(*) FROM seasons").fetchone()[0] == 1

        again = seasons.plan(conn, channels.get(conn, CH), "L01")
        assert not again[0]["queued"] and "already planned" in again[0]["reason"]
        replanned = seasons.plan(conn, channels.get(conn, CH), "L01", replan=True)
        assert replanned[0]["queued"]
        assert db.get_task(conn, task["id"])["status"] == "cancelled"


def test_plan_refuses_levels_with_check_errors_and_unknown_levels(chan):
    write_season(chan, [level(1, params={"stage": "moonbase"}), level(2)])
    with db.connect() as conn:
        ch = channels.get(conn, CH)
        out = seasons.plan(conn, ch, "L01..L02")
        assert not out[0]["queued"] and "no physics stage" in out[0]["reason"]
        assert out[1]["queued"]
        with pytest.raises(ValueError, match="no level L09"):
            seasons.plan(conn, ch, "L09")


def test_list_and_dict_params_survive_held_params(chan):
    with db.connect() as conn:
        seasons.plan(conn, channels.get(conn, CH), "L01")
        row = db.claim_task(conn, "agent", channel_id=CH)
        want = json.loads(row["params_json"])
        _, use = tasks.held_params(conn, CH, {"variant": "marble_race", "seed": None}, row["id"])
        assert use["cast"] == want["cast"] and use["story"] == want["story"]
        # the same dict given back (key order aside) is not a change
        same = {"story": {"prefer": want["story"]["prefer"], "must": want["story"]["must"]}}
        tasks.held_params(conn, CH, same, row["id"])
        with pytest.raises(ValueError, match="asks for story"):
            tasks.held_params(conn, CH, {"story": {"must": {}}}, row["id"])
        assert tasks.clip_params(use)["level_id"] == "L01"
        assert "seed" not in tasks.clip_params(use)


def test_enqueue_keeps_series_params():
    allowed = set(tasks.KINDS["make-clip"]["params"])
    assert {"cast", "story", "level_id", "season_id", "format", "section", "rounds",
            "max_story_attempts", "prefer_pool"} <= allowed


# --- render wiring -----------------------------------------------------------

def outcome(order, fmt="race", statuses=None):
    statuses = statuses or {}
    return Outcome(format=fmt, placements=[
        Placement(entrant_id=e, rank=i + 1, status=statuses.get(e, "finished")) for i, e in enumerate(order)
    ])


@pytest.fixture
def fake_render(monkeypatch):
    """A generator that writes a trace and an outcome, and a render module
    that measures nothing: only the pipeline's bookkeeping is under test."""
    from factory import phash, render

    state = {"fail": None, "order": ["blaze", "tide", "volt"]}

    class Gen:
        def generate(self, *, seed, variant, params, work_dir):
            if state["fail"]:
                raise RuntimeError(state["fail"])
            work_dir.mkdir(parents=True, exist_ok=True)
            (work_dir / "clip.mp4").write_bytes(b"v")
            (work_dir / "trace.npz").write_bytes(b"n")
            (work_dir / "trace.json").write_text("{}")
            out = outcome(state["order"], fmt=state.get("fmt", "race"), statuses=state.get("statuses"))
            if state.get("teams"):
                out.facts["teams"] = state["teams"]
            return GeneratedClip(video_path=work_dir / "clip.mp4", duration_s=20.0, description="a race",
                                 facts={"outcome": out.model_dump(mode="json"), "story_attempts": 3},
                                 outcome=out, trace_path=work_dir / "trace.json")

    monkeypatch.setattr(generators, "get", lambda name: Gen())
    monkeypatch.setattr(render, "probe", lambda p: {"duration_s": 20.0, "width": 1080, "height": 1920, "fps": 60})
    monkeypatch.setattr(render, "loudness_lufs", lambda p: -14.0)
    monkeypatch.setattr(render, "sample_frames", lambda p, t: [b"frame"])
    monkeypatch.setattr(phash, "clip_hash", lambda frames: "0" * 16)
    monkeypatch.setattr(phash, "max_similarity", lambda h, known: 0.0)
    return state


def render_level(conn, level_id, state=None, order=None):
    """Plan a level if needed, then render a clip for it the way the worker does."""
    if state is not None and order is not None:
        state["order"] = order
    if planning.level_row(conn, CH, "s0", level_id) is None:
        seasons.plan(conn, channels.get(conn, CH), level_id)
    row = planning.level_row(conn, CH, "s0", level_id)
    params = json.loads(db.get_task(conn, row["task_id"])["params_json"])
    clip_id = db.insert_clip(conn, channel_id=CH, generator="physics", variant="marble_race",
                             seed=abs(hash((level_id, str(order)))) % 10**6,
                             params=tasks.clip_params(params), hook="", plan_why="t")
    pipeline.render_stage(conn, channels.get(conn, CH), clip_id, tasks.clip_params(params))
    db.update(conn, clip_id, status=AWAITING_APPROVAL, title="t")
    return clip_id


def test_render_records_trace_and_level(chan, fake_render):
    with db.connect() as conn:
        clip_id = render_level(conn, "L01")
        row = db.get(conn, clip_id)
        assert row["level_id"] == "L01"
        assert row["trace_path"] == f"data/work/{CH}/{clip_id}/trace.json"
        lv = planning.level_row(conn, CH, "s0", "L01")
        assert (lv["clip_id"], lv["status"]) == (clip_id, "rendered")


def test_story_unsatisfiable_fails_the_level_with_the_reason(chan, fake_render):
    fake_render["fail"] = "story_unsatisfiable: 200 seeds, none had lead_changes >=1"
    with db.connect() as conn:
        seasons.plan(conn, channels.get(conn, CH), "L01")
        params = json.loads(db.get_task(conn, planning.level_row(conn, CH, "s0", "L01")["task_id"])["params_json"])
        clip_id = db.insert_clip(conn, channel_id=CH, generator="physics", variant="marble_race",
                                 seed=5, params=tasks.clip_params(params), hook="", plan_why="t")
        result = pipeline.build(conn, clip_id)
        assert result.status == "failed"
        lv = planning.level_row(conn, CH, "s0", "L01")
        assert lv["status"] == "failed" and lv["reason"].startswith("story_unsatisfiable:")
        assert lv["clip_id"] == clip_id
        # a failed level may be planned again without --replan
        assert seasons.plan(conn, channels.get(conn, CH), "L01")[0]["queued"]


def test_a_clip_that_is_not_a_level_touches_no_level(chan, fake_render):
    with db.connect() as conn:
        clip_id = db.insert_clip(conn, channel_id=CH, generator="physics", variant="marble_race",
                                 seed=9, params={}, hook="", plan_why="t")
        pipeline.render_stage(conn, channels.get(conn, CH), clip_id, {})
        assert db.get(conn, clip_id)["level_id"] is None
        assert conn.execute("SELECT COUNT(*) FROM levels").fetchone()[0] == 0


# --- standings ---------------------------------------------------------------

def table_now(conn, **kw):
    return standings.table(conn, CH, "s0", **kw)


def recomputed(conn):
    before = table_now(conn)
    standings.recompute(conn, CH, "s0")
    after = table_now(conn)
    return before, after


def test_incremental_table_equals_recompute_through_every_transition(chan, fake_render):
    with db.connect() as conn:
        a = render_level(conn, "L01", fake_render, ["blaze", "tide", "volt"])
        b = render_level(conn, "L02", fake_render, ["tide", "blaze"])
        c = render_level(conn, "L03", fake_render, ["volt", "tide", "blaze"])
        steps = [
            lambda: pipeline.approve(conn, a),
            lambda: pipeline.approve(conn, b),
            lambda: pipeline.reject(conn, b, "no"),
            lambda: pipeline.restore(conn, b),
            lambda: pipeline.approve(conn, b),
            lambda: pipeline.approve(conn, c),
            lambda: pipeline.bin_clips(conn, [c]),
            lambda: pipeline.unbin_clips(conn, [c]),
            lambda: pipeline.bin_clips(conn, [a]),
            lambda: pipeline.destroy_clips(conn, [a]),
        ]
        for step in steps:
            step()
            before, after = recomputed(conn)
            assert before == after
        pts = {r["entrant_id"]: r["points"] for r in table_now(conn)}
        # a destroyed; b: tide 3 blaze 2; c: volt 3 tide 2 blaze 1
        assert pts == {"tide": 5, "blaze": 3, "volt": 3, "moss": 0}  # moss debuted by L03
        assert [r["entrant_id"] for r in table_now(conn)][:1] == ["tide"]


def test_table_rows_before_level_and_debuts(chan, fake_render):
    with db.connect() as conn:
        a = render_level(conn, "L01", fake_render, ["blaze", "tide", "volt"])
        b = render_level(conn, "L03", fake_render, ["volt", "tide", "blaze"])
        pipeline.approve(conn, a)
        pipeline.approve(conn, b)
        full = table_now(conn)
        # all on 4: blaze and volt won once (then by id), tide never
        assert full[0] == {"entrant_id": "blaze", "name": "Blaze", "points": 4, "wins": 1, "races": 2}
        assert [r["entrant_id"] for r in full[:3]] == ["blaze", "volt", "tide"]
        assert {r["entrant_id"] for r in full} == {"blaze", "tide", "volt", "moss"}  # moss debuted L03
        early = table_now(conn, before_level="L03")
        assert [r["entrant_id"] for r in early] == ["blaze", "tide", "volt", "moss"]
        assert early[0]["points"] == 3 and early[0]["wins"] == 1
        assert table_now(conn, before_level="L02")[-1]["entrant_id"] == "volt"  # no moss yet
        assert "moss" not in {r["entrant_id"] for r in table_now(conn, before_level="L02")}
        assert all(r["entrant_id"] != "ghost" for r in full)


def test_h2h(chan, fake_render):
    with db.connect() as conn:
        for lv, order in (("L01", ["blaze", "tide", "volt"]), ("L02", ["tide", "blaze"]),
                          ("L03", ["blaze", "volt", "tide"])):
            pipeline.approve(conn, render_level(conn, lv, fake_render, order))
        assert standings.h2h(conn, CH, "s0", "blaze", "tide") == (2, 1)
        assert standings.h2h(conn, CH, "s0", "tide", "volt") == (1, 1)
        assert standings.h2h(conn, CH, "s0", "blaze", "tide", before_level="L02") == (1, 0)
        assert standings.h2h(conn, CH, "s0", "moss", "tide") == (0, 0)


def test_guests_never_score_and_final_doubles(chan, fake_render):
    levels = [level(n) for n in range(1, 4)]
    levels[1].update(entrants=["ghost", "blaze", "tide"], final=True)
    write_season(chan, levels)
    with db.connect() as conn:
        pipeline.approve(conn, render_level(conn, "L02", fake_render, ["ghost", "blaze", "tide"]))
        rows = {r["entrant_id"]: r for r in table_now(conn)}
        assert "ghost" not in rows
        assert rows["blaze"]["points"] == 4 and rows["tide"]["points"] == 2  # 2 and 1, doubled
        assert rows["blaze"]["wins"] == 0


def test_elimination_scores_entrants_outlasted_and_scoring_toml_overrides(chan):
    rules = standings.scoring(CH)
    elim = outcome(["tide", "blaze", "volt"], fmt="elimination")
    assert rules.points(elim, final=False, guests=set()) == {"tide": 2, "blaze": 1, "volt": 0}
    dnf = outcome(["tide", "blaze", "volt"], statuses={"volt": "stopped"})
    assert rules.points(dnf, final=False, guests=set())["volt"] == 0
    (chan / "channels" / CH / "scoring.toml").write_text(
        "final_multiplier = 3\n[race]\npoints = [5, 3]\n[scheme.cup.race]\npoints = [10]\n")
    rules = standings.scoring(CH)
    race = outcome(["tide", "blaze", "volt"])
    assert rules.points(race, final=True, guests=set()) == {"tide": 15, "blaze": 9, "volt": 0}
    assert standings.scoring(CH, "cup").points(race, final=False, guests=set())["tide"] == 10
    with pytest.raises(ValueError):
        standings.scoring(CH, "league")


TEAMS = {"blaze.1": "blaze", "blaze.2": "blaze", "tide.1": "tide", "tide.2": "tide"}


def test_a_team_race_scores_the_persona_by_sum_or_best(chan):
    race = outcome(["blaze.1", "tide.1", "blaze.2", "tide.2"])
    race.facts["teams"] = TEAMS
    assert standings.scoring(CH).points(race, final=False, guests=set()) == {"blaze": 4, "tide": 2}
    elim = outcome(["tide.1", "blaze.1", "tide.2", "blaze.2"], fmt="elimination",
                   statuses={"blaze.1": "eliminated", "tide.2": "eliminated", "blaze.2": "eliminated"})
    elim.facts["teams"] = TEAMS
    # outlasted, never counting a teammate: tide.1 2, blaze.1 1, tide.2 1, blaze.2 0
    assert standings.scoring(CH).points(elim, final=False, guests=set()) == {"tide": 3, "blaze": 1}
    (chan / "channels" / CH / "scoring.toml").write_text('[teams]\nmode = "best"\n')
    best = standings.scoring(CH)
    assert best.points(race, final=True, guests=set()) == {"blaze": 6, "tide": 4}
    assert best.points(elim, final=False, guests=set()) == {"tide": 2, "blaze": 1}
    (chan / "channels" / CH / "scoring.toml").write_text('[teams]\nmode = "most"\n')
    with pytest.raises(ValueError, match="sum or best"):
        standings.scoring(CH)


def test_team_standings_count_a_persona_once_and_equal_recompute(chan, fake_render):
    with db.connect() as conn:
        fake_render["teams"] = TEAMS
        a = render_level(conn, "L01", fake_render, ["tide.1", "blaze.1", "blaze.2", "tide.2"])
        fake_render["teams"] = None
        b = render_level(conn, "L02", fake_render, ["blaze", "tide", "volt"])
        for step in (lambda: pipeline.approve(conn, a), lambda: pipeline.approve(conn, b),
                     lambda: pipeline.reject(conn, a, "no"), lambda: pipeline.restore(conn, a),
                     lambda: pipeline.approve(conn, a)):
            step()
            before, after = recomputed(conn)
            assert before == after
        rows = {r["entrant_id"]: r for r in table_now(conn)}
        assert "blaze.1" not in rows and "tide.2" not in rows
        # L01 teams, summed: tide 3 + 0, blaze 2 + 1; L02: blaze 3, tide 2, volt 1
        assert rows["tide"]["points"] == 5 and rows["blaze"]["points"] == 6
        assert rows["tide"]["races"] == 2 and rows["tide"]["wins"] == 1 and rows["blaze"]["wins"] == 1
        assert standings.h2h(conn, CH, "s0", "blaze", "tide") == (1, 1)


def test_a_second_clip_for_a_counted_level_cannot_be_approved(chan, fake_render):
    with db.connect() as conn:
        a = render_level(conn, "L01", fake_render, ["blaze", "tide", "volt"])
        pipeline.approve(conn, a)
        seasons.plan(conn, channels.get(conn, CH), "L01", replan=True)
        b = render_level(conn, "L01", fake_render, ["tide", "blaze", "volt"])
        with pytest.raises(ValueError, match="already counts"):
            pipeline.approve(conn, b)
        assert db.get(conn, b)["status"] == AWAITING_APPROVAL
        pipeline.reject(conn, a, "redo")
        pipeline.approve(conn, b)
        assert table_now(conn)[0]["entrant_id"] == "tide"


def test_published_clips_count_and_recompute_prefers_them(chan, fake_render):
    with db.connect() as conn:
        a = render_level(conn, "L01", fake_render, ["blaze", "tide", "volt"])
        pipeline.approve(conn, a)
        db.update(conn, a, status=PUBLISHED)
        standings.recompute(conn, CH, "s0")
        assert table_now(conn)[0]["entrant_id"] == "blaze"


# --- surfaces ----------------------------------------------------------------

def test_cli_check_plan_standings_status(chan, fake_render, capsys, monkeypatch):
    assert cli_main(["season", "check"]) == 0
    assert "0 errors" in capsys.readouterr().out
    assert cli_main(["season", "plan", "--levels", "L01..L02"]) == 0
    out = capsys.readouterr().out
    assert "L01   queued as task #" in out and "2 queued" in out
    with db.connect() as conn:
        clip_id = render_level(conn, "L01", fake_render, ["volt", "tide", "blaze"])
        facts = json.loads(db.get(conn, clip_id)["facts_json"])
        db.update(conn, clip_id, facts_json=json.dumps({**facts, "copy_source": "template"}))
        pipeline.approve(conn, clip_id)
    assert cli_main(["season", "standings"]) == 0
    out = capsys.readouterr().out
    assert "Volt" in out.splitlines()[2]
    assert cli_main(["season", "standings", "--recompute", "--after", "L01"]) == 0
    assert "after L01 (recomputed)" in capsys.readouterr().out
    assert cli_main(["season", "status"]) == 0
    out = capsys.readouterr().out
    assert clip_id in out and "approved" in out and "template" in out and "copy: template 1 (100%)" in out


def test_cli_check_fails_on_errors(chan, capsys):
    write_season(chan, [level(1, status="blocked")])
    assert cli_main(["season", "check"]) == 1
    assert "needs blocked_on" in capsys.readouterr().out


@pytest.mark.anyio
async def test_mcp_season_tools(chan, fake_render):
    from factory import mcp

    server = mcp.build_server()
    names = {t.name for t in await server.list_tools()}
    assert {"season_check", "season_plan", "get_standings", "get_level"} <= names

    def body(result):
        return " ".join(getattr(b, "text", "") for b in getattr(result, "content", []) or [])

    assert '"errors": []' in body(await server.call_tool("season_check", {}))
    planned = body(await server.call_tool("season_plan", {"levels": "L01,L02"}))
    assert '"queued": true' in planned
    again = body(await server.call_tool("season_plan", {"levels": "L01"}))
    assert "already planned" in again
    with db.connect() as conn:
        pipeline.approve(conn, render_level(conn, "L01", fake_render, ["tide", "blaze", "volt"]))
    assert '"Tide"' in body(await server.call_tool("get_standings", {}))
    level_info = body(await server.call_tool("get_level", {"level": "L02"}))
    assert '"standings_before"' in level_info and '"planned"' in level_info


def test_telegram_caption_carries_level_and_standings_before_it(chan, fake_render):
    with db.connect() as conn:
        pipeline.approve(conn, render_level(conn, "L01", fake_render, ["blaze", "tide", "volt"]))
        second = render_level(conn, "L02", fake_render, ["tide", "blaze"])
        caption = telegram.clip_caption(db.get(conn, second))
        plain = telegram.clip_caption(db.get(conn, db.insert_clip(
            conn, channel_id=CH, generator="physics", variant="marble_race", seed=1,
            params={}, hook="", plan_why="t")))
    assert "level L02 · before it: Blaze 3 · Tide 2 · Volt 1" in caption
    assert "level" not in plain


# --- retention ---------------------------------------------------------------

def trace_dir(root, clip_id):
    d = settings.load().work_dir / CH / clip_id
    d.mkdir(parents=True, exist_ok=True)
    for name in ("clip.mp4", "trace.npz", "trace.json"):
        (d / name).write_bytes(b"x" * 100)
    return d


def old_clip(conn, status, root):
    cid = db.insert_clip(conn, channel_id=CH, generator="physics", variant="marble_race",
                         seed=len(status), params={}, hook="", plan_why="t")
    d = trace_dir(root, cid)
    db.update(conn, cid, status=status, video_path=f"data/work/{CH}/{cid}/clip.mp4",
              trace_path=f"data/work/{CH}/{cid}/trace.json")
    conn.execute("UPDATE clips SET created_at = datetime('now', '-400 days') WHERE id = ?", (cid,))
    conn.commit()
    return cid, d


def test_gc_keeps_traces_of_approved_and_published_forever(chan, monkeypatch):
    raw = settings.load().raw
    monkeypatch.setitem(raw, "retention", {**raw.get("retention", {}), "trace_days": -1,
                                           "published_days": 30, "rejected_days": 3})
    with db.connect() as conn:
        _, pub = old_clip(conn, PUBLISHED, chan)
        _, ok = old_clip(conn, APPROVED, chan)
        rej_id, rej = old_clip(conn, QC_REJECTED, chan)
        gc.sweep_clips(conn)
    assert not (pub / "clip.mp4").exists()
    assert (pub / "trace.npz").exists() and (pub / "trace.json").exists()
    assert (ok / "trace.npz").exists() and (ok / "clip.mp4").exists()
    assert not rej.exists()  # rejected: the whole directory, traces included


def test_gc_drops_traces_when_trace_days_says_so(chan, monkeypatch):
    raw = settings.load().raw
    monkeypatch.setitem(raw, "retention", {**raw.get("retention", {}), "trace_days": 30,
                                           "published_days": -1, "rejected_days": 3})
    with db.connect() as conn:
        pub_id, pub = old_clip(conn, PUBLISHED, chan)
        dry = gc.sweep_clips(conn, dry_run=True)
        assert pub_id in dry.clips and (pub / "trace.npz").exists()
        gc.sweep_clips(conn)
    assert not (pub / "trace.npz").exists() and (pub / "clip.mp4").exists()


def test_a_fresh_rejected_clip_keeps_its_trace(chan):
    with db.connect() as conn:
        cid = db.insert_clip(conn, channel_id=CH, generator="physics", variant="marble_race",
                             seed=1, params={}, hook="", plan_why="t")
        d = trace_dir(chan, cid)
        db.update(conn, cid, status=QC_REJECTED, video_path=f"data/work/{CH}/{cid}/clip.mp4")
        gc.sweep_clips(conn)
    assert (d / "trace.json").exists()


def test_the_series_package_never_imports_a_generator():
    import pathlib

    root = pathlib.Path(standings.__file__).parent
    for path in root.glob("*.py"):
        text = path.read_text()
        assert "generators" not in "\n".join(
            line for line in text.splitlines() if line.lstrip().startswith(("import", "from"))
        ), path.name
