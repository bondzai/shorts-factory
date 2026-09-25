"""Bulk work: every source gives the same rows, every row is checked before
anything is written, and the same row imported twice is queued once."""

import asyncio
import json

import pytest

from factory import batch, channels, db, tasks
from factory.batch import validators

CAST = """
[[entrant]]
id = "blaze"
name = "Blaze"
color = "#E84C4A"
[[entrant]]
id = "tide"
name = "Tide"
color = "#378ADD"
"""
SEASON = """
id: s0
title: Season 0
channel: main
levels:
  - {id: L01, date: 2026-09-25, world: foundations, params: {stage: zigzag}, entrants: [blaze, tide]}
  - {id: L02, date: 2026-09-26, world: foundations, params: {stage: funnels}, entrants: [blaze, tide], story: {must: {lead_changes: ">=1"}}}
  - {id: L03, date: 2026-09-27, world: foundations, params: {stage: plinko}, entrants: [blaze, tide]}
  - {id: L04, date: 2026-09-28, world: trapdoor, params: {section: trap_modes}, entrants: [blaze, tide], status: blocked, blocked_on: "WP7 trapdoor: modes"}
"""


@pytest.fixture
def ch(sandbox):
    d = sandbox / "channels" / "main"
    (d / "season").mkdir(parents=True)
    (d / "cast.toml").write_text(CAST)
    (d / "season" / "s0.yaml").write_text(SEASON)
    with db.connect() as conn:
        channels.create(conn, name="Gravity Lab", channel_id="main",
                        variants=["physics/marble_race", "battle/ball_battle"])
    return "main"


def submit(rows, **kw):
    with db.connect() as conn:
        ctx = batch.context(conn, channels.resolve(conn, "main"), max_priority=kw.pop("max_priority", 100))
        return batch.service(max_rows=kw.pop("max_rows", 500)).submit(ctx, batch.ListSource(rows), by="test", **kw)


def queued():
    with db.connect() as conn:
        return [tasks.as_dict(r) for r in db.tasks(conn, "main", None)]


def test_a_dry_run_checks_everything_and_writes_nothing(ch):
    r = submit([{"stage": "zigzag", "count": 2}, {"level": "L01..L03"}], dry_run=True)
    assert (r.accepted, r.refused, r.batch_id) == (4, 0, None) and queued() == []


def test_one_bad_row_queues_nothing_unless_partial(ch):
    rows = [{"stage": "zigzag", "ref": "a"}, {"stage": "nope", "ref": "b"}, {"level": "L04"}]
    r = submit(rows)
    assert r.batch_id is None and queued() == []
    assert {x.ref or x.level: x.reason for x in r.rows}["b"] == "no stage 'nope'"
    assert "blocked" in {x.level: x.reason for x in r.rows}["L04"]
    r = submit(rows, partial=True)
    assert r.batch_id and r.accepted == 1 and len(queued()) == 1


def test_a_level_range_plans_each_level_like_season_plan(ch):
    r = submit([{"level": "L01..L03", "ref": "wk", "brief": "open the season gently",
                 "hints": {"title": "Pick one before the zigzag"}}])
    assert [x.ref for x in r.rows] == ["wk:L01", "wk:L02", "wk:L03"] and r.refused == 0
    t = {q["params"]["level_id"]: q for q in queued()}
    assert set(t) == {"L01", "L02", "L03"}
    assert t["L02"]["params"]["story"] == {"must": {"lead_changes": ">=1"}, "prefer": {}}
    assert t["L01"]["params"]["brief"] == "open the season gently"
    assert t["L01"]["params"]["hints"] == {"title": "Pick one before the zigzag"}
    with db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM levels WHERE status = 'planned'").fetchone()[0] == 3
        assert conn.execute("SELECT accepted FROM batches").fetchone()[0] == 3


def test_the_same_row_imported_twice_is_queued_once(ch):
    assert submit([{"stage": "zigzag", "ref": "wk40-a"}]).accepted == 1
    again = submit([{"stage": "zigzag", "ref": "wk40-a"}])
    assert "already queued" in again.rows[0].reason and len(queued()) == 1
    assert "twice in this batch" in submit([{"ref": "x"}, {"ref": "x"}]).rows[1].reason


def test_a_level_is_planned_once_and_keeps_its_own_stage(ch):
    r = submit([{"level": "L01", "stage": "plinko"}], dry_run=True)
    assert "from the season file" in r.rows[0].reason
    submit([{"level": "L01"}])
    assert "already planned" in submit([{"level": "L01"}], dry_run=True).rows[0].reason


def test_seeds_modules_params_and_priority_are_checked(ch):
    r = submit([{"seed": 7, "count": 2}, {"seed": 9}, {"seed": 9}, {"generator": "asmr"},
                {"params": {"cast": []}}, {"priority": 9}, {"background": "red"}],
               dry_run=True, max_priority=5)
    reasons = [x.reason for x in r.rows]
    assert "fixed seed makes one clip" in reasons[0] and reasons[1] is None and "twice" in reasons[2]
    assert "no module 'asmr'" in reasons[3] and "not settable" in reasons[4]
    assert "above 5" in reasons[5] and "#RRGGBB" in reasons[6]


def test_malformed_rows_are_refused_one_by_one(ch):
    r = submit([{"seed": "x"}, {"nonsense": 1}, {"count": 101}], dry_run=True)
    assert all(x.reason for x in r.rows) and "seed" in r.rows[0].reason and "nonsense" in r.rows[1].reason


def test_a_batch_has_a_size_limit(ch):
    with pytest.raises(ValueError, match="at most 2"):
        submit([{}, {}, {}], max_rows=2)


def test_every_file_format_reads_to_the_same_rows(ch, tmp_path):
    (tmp_path / "a.csv").write_text("ref,stage,count,hint_title,params\nr1,zigzag,2,Pick one now,\"{\"\"rounds\"\": 2}\"\n")
    (tmp_path / "a.json").write_text(json.dumps({"jobs": [{"ref": "r1", "stage": "zigzag", "count": 2}]}))
    (tmp_path / "a.jsonl").write_text('{"ref": "r1", "stage": "zigzag"}\n\n{"level": "L01"}\n')
    (tmp_path / "a.yaml").write_text("- {ref: r1, stage: zigzag}\n- {level: L01}\n")
    rows = list(batch.source_for(tmp_path / "a.csv").read())
    assert rows == [{"ref": "r1", "stage": "zigzag", "count": "2", "params": {"rounds": 2},
                     "hints": {"title": "Pick one now"}}]
    assert list(batch.source_for(tmp_path / "a.json").read())[0]["count"] == 2
    assert len(list(batch.source_for(tmp_path / "a.jsonl").read())) == 2
    assert list(batch.source_for(tmp_path / "a.yaml").read())[1] == {"level": "L01"}
    with pytest.raises(ValueError, match="no reader for .txt"):
        batch.source_for(tmp_path / "a.txt")
    with db.connect() as conn:
        r = batch.service().submit(batch.context(conn, channels.resolve(conn, "main")),
                                   batch.source_for(tmp_path / "a.csv"), by="test")
    assert r.accepted == 1 and queued()[0]["params"]["rounds"] == 2


def test_a_new_rule_is_a_new_class(ch):
    class NoBattles:
        def check(self, spec, ctx):
            return ["no battles this week"] if spec.generator == "battle" else []

    svc = batch.BatchService((*validators.DEFAULT, NoBattles()), batch.TaskSink())
    with db.connect() as conn:
        r = svc.submit(batch.context(conn, channels.resolve(conn, "main")),
                       batch.ListSource([{"generator": "battle", "variant": "ball_battle"}]), by="t", dry_run=True)
    assert r.rows[0].reason == "no battles this week"


def call(server, name, args):
    result = asyncio.run(server.call_tool(name, args))
    return json.loads(result[0][0].text) if isinstance(result, tuple) else json.loads(result.content[0].text)


def test_an_agent_orders_over_mcp_dry_run_first_and_capped(ch):
    from factory import mcp

    server = mcp.build_server()
    opts = call(server, "batch_options", {})
    assert [lv["level"] for lv in opts["season"]["ready"]] == ["L01", "L02", "L03"]
    assert opts["season"]["blocked"][0]["waits_for"] == "WP7 trapdoor: modes"
    assert "zigzag" in {s["id"] for s in opts["stages"]} and opts["limits"]["rows"] == mcp.MCP_BATCH_ROWS
    dry = call(server, "enqueue_batch", {"jobs": [{"level": "L02", "brief": "a close one"}], "agent": "claude code"})
    assert dry["dry_run"] and dry["accepted"] == 1 and queued() == []
    real = call(server, "enqueue_batch", {"jobs": [{"level": "L02", "ref": "L02"}], "dry_run": False, "agent": "claude"})
    assert real["batch_id"] and queued()[0]["created_by"] == "claude"
    capped = call(server, "enqueue_batch", {"jobs": [{"priority": 50}]})
    assert "above 5" in capped["rows"][0]["reason"]
