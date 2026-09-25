"""Season copy: a model proposes, code checks, the template catches the rest.

docs/08 §4 "Copy". The validator is the part that has to be right, so most of
this file tries to get something past it: a number the race did not produce,
the winner, one marble out of four, a margin in a title, a title the feed cuts
in the middle of a thought.
"""

import json
import sys
import types
from types import SimpleNamespace

import pytest

from factory import channels, db, llm, logs
from factory.agents import copy as copy_agent
from factory.pipeline import building
from factory.series import copy_check, copywriter
from factory.series.copy_check import CopyContext, check, choose, fill, stands_alone
from factory.series.outcome import Event, Outcome, Placement

ENTRANTS = [("blaze", "Blaze"), ("tide", "Tide"), ("volt", "Volt"), ("moss", "Moss")]
POINTS = {"blaze": 5, "tide": 3, "volt": 1, "moss": 0}


def ctx(**over):
    base = dict(
        entrants=list(ENTRANTS),
        values={"margin_s": 0.42, "lead_changes": 3, "entrant_count": 4, "leader_name": "Blaze"},
        standings=dict(POINTS),
        h2h=lambda a, b: (3, 1),
        known_ids={e for e, _ in ENTRANTS},
        facts={},
        winners={"volt", "Volt"},
        recent_titles=["Marble race on the zigzag: pick one now"],
        recent_pins=["Blaze, Tide, Volt or Moss — who's your pick?"],
        keywords=["Marble Race"],
        emoji_ok=False,
    )
    base.update(over)
    return CopyContext(**base)


# --- every one of these must be refused ---------------------------------------------

REJECTED = [
    ("title", "Four marbles, 3 magnets: who gets launched?", "number"),
    ("title", "Volt is the one to watch on the magnet stage", "winner"),
    ("title", "volt vs the magnet: can anyone stop it tonight", "winner"),
    ("title", "Blaze and Tide go head to head on the magnets", "not the whole field"),
    ("title", "Moss has never been this close to the top spot", "not the whole field"),
    ("title", "Quem vence a corrida de ímãs hoje à noite?", "English"),
    ("title", "Pull, flip, launch — who survives the swap? 🧲", "emoji"),
    ("title", "Marble race on the zigzag: someone new this time", "opens like"),
    ("pin", "Blaze, Tide, Volt or Moss — who's your pick?", "same pin"),
    ("title", "Pick your side: {winner_name} is on the line", "unknown placeholder"),
    ("title", "Settled by {margin_s} seconds: the magnet swap", "result"),
    ("pin", "{lead_changes} lead changes — did you call it?", "result"),
    ("hook", "Watch the magnet flip and pick one now", "words"),
    ("title", "Four marbles go into the magnet swap and only one comes back out", "stand"),
    ("title", "Everything changes when the magnet flips halfway down the course tonight ok", "70"),
    ("title", "WHO SURVIVES THE MAGNET SWAP TONIGHT", "caps"),
    ("title", "Who survives the magnet swap tonight?!", "stacked"),
    ("hook", "Photo finish ahead", "result"),
    ("title", "The magnet flip decided it: pick one now", "result"),
    ("desc_line1", "Four marbles race; Volt leads from the start.", "winner"),
    ("title", "Standings check: {standing:ghost} points so far", "no entrant"),
]


@pytest.mark.parametrize("field,text,why", REJECTED)
def test_the_validator_refuses(field, text, why, sandbox):
    reason = check(field, text, ctx())
    assert reason is not None, f"{text!r} passed"
    assert why.lower() in reason.lower(), reason


def test_a_sixty_character_title_with_no_break_before_45_is_refused():
    title = "Four marbles take on the flipping magnet and one gets launched"
    assert 55 <= len(title) <= 70 and not stands_alone(title)
    assert "stand" in check("title", title, ctx())


def test_a_long_title_passes_when_its_first_clause_stands_alone():
    title = "Marble race, polarity swap: pulled in, then shot out"
    assert len(title) > 45 and stands_alone(title)
    assert check("title", title, ctx()) is None
    assert not stands_alone("Pick one: " + "x" * 50)  # prefix under 20 characters


# --- and these pass, filled --------------------------------------------------------

def test_pre_race_placeholders_pass_and_fill(sandbox):
    c = ctx()
    t = "Marble race: can anyone catch {leader_name} tonight?"
    # {leader_name} fills to one entrant's name, which rule 3 then refuses —
    # naming one marble is naming one marble, however it got there.
    assert "whole field" in check("title", t, c)
    t = "{entrant_count} marbles, one magnet: who flips first?"
    assert check("title", t, c) is None
    assert fill(t, c, "title") == "4 marbles, one magnet: who flips first?"
    pin = "Blaze {standing:blaze}, Tide {standing:tide}, Volt {standing:volt}, Moss {standing:moss}: who climbs?"
    assert check("pin", pin, c) is None
    assert fill(pin, c, "pin").startswith("Blaze 5, Tide 3, Volt 1, Moss 0")
    assert fill("Blaze vs Tide so far: {h2h:blaze:tide}", c) == "Blaze vs Tide so far: 3–1"
    assert check("hook", "Pick one before the flip", c) is None
    # Results of this race are for the description body only.
    assert fill("Margin {margin_s}s, {lead_changes} lead changes", c, "description") == "Margin 0.42s, 3 lead changes"


def test_naming_every_entrant_is_fine_even_the_winner(sandbox):
    assert check("title", "Blaze, Tide, Volt, Moss: one magnet flip", ctx()) is None


def test_emoji_passes_when_the_switch_is_on(sandbox):
    assert check("title", "Pull, flip, launch — who survives the swap? 🧲", ctx(emoji_ok=True)) is None


def test_no_leader_at_zero_means_the_placeholder_has_no_value(sandbox):
    assert "no value" in check("hook", "Catch {leader_name}", ctx(values={"leader_name": None}))


# --- choosing -------------------------------------------------------------------------

def test_a_keyword_in_the_first_three_words_ranks_first_then_model_order(sandbox):
    proposal = {"title": ["Pulled in, then shot out: who lands it?",
                          "Marble Race polarity swap: pulled in, shot out",
                          "Marble race of the week: the magnet flips"],
                "hook": ["Pick one", "Call it"], "pin": [], "desc_line1": []}
    got = choose(proposal, ctx(), {"pin": "fallback pin", "desc_line1": "fallback line"})
    assert got.text["title"] == "Marble Race polarity swap: pulled in, shot out"
    assert got.source == {"title": "local", "hook": "local", "pin": "template", "desc_line1": "template"}
    assert got.text["hook"] == "Pick one"
    assert got.text["pin"] == "fallback pin"


def test_rejections_are_all_reported_and_the_first_passing_wins(sandbox):
    proposal = {"title": ["Volt vs the magnet: can anyone stop it", "Who survives the magnet flip tonight?"],
                "hook": ["Watch the magnet flip and pick one now"], "pin": [], "desc_line1": []}
    got = choose(proposal, ctx(keywords=[]), {})
    assert got.text["title"] == "Who survives the magnet flip tonight?"
    assert [r["field"] for r in got.rejected] == ["title", "hook"]
    assert got.source["hook"] == "template" and got.text["hook"] is None


# --- the brain and the pipeline -----------------------------------------------------

CH = "main"
CAST = """
[[entrant]]
id = "blaze"
name = "Blaze"
color = "#E84C4A"
bio = "Fastest off the line, crashes under pressure"

[[entrant]]
id = "tide"
name = "Tide"
color = "#2E86DE"
bio = "Steady"

[[entrant]]
id = "volt"
name = "Volt"
color = "#F5C518"
bio = "Erratic"

[[entrant]]
id = "moss"
name = "Moss"
color = "#3BA55C"
bio = "Average"
"""
SEASON = {
    "id": "s0", "title": "Season 0", "channel": CH,
    "keywords": ["Marble Race"], "footer": "New race every day. Same four marbles.",
    "levels": [
        {"id": "L01", "date": "2026-10-01", "world": "w1", "params": {"stage": "zigzag"},
         "entrants": ["blaze", "tide", "volt", "moss"]},
        {"id": "L02", "date": "2026-10-02", "world": "w1", "params": {"stage": "lodestone"},
         "entrants": ["blaze", "tide", "volt", "moss"],
         "copy": {"title": "Marble Race Polarity Swap: Pulled In, Then Shot Out",
                  "pin": "Getting launched: good or bad?"}},
    ],
}
OUTCOME = Outcome(
    format="race",
    placements=[Placement(entrant_id="volt", rank=1, time_s=10.2), Placement(entrant_id="tide", rank=2, time_s=10.6),
                Placement(entrant_id="blaze", rank=3, time_s=11.0), Placement(entrant_id="moss", rank=4, time_s=12.0)],
    margin_s=0.4, lead_changes=2,
    events=[Event(t_s=3.0, kind="launched", entrant_id="blaze"), Event(t_s=10.2, kind="finish", entrant_id="volt")],
)
FACTS = {
    "variant": "marble_race", "stage": "lodestone", "lineup": ["blaze", "tide", "volt", "moss"],
    "cast": ["blaze", "tide", "volt", "moss"], "winner": "volt", "runner_up": "tide",
    "finishes": {"volt": 306, "tide": 318}, "margin_s": 0.4,
    "rounds": [{"stage": "lodestone", "winner": "volt", "finishes": {"volt": 306}}],
    "outcome": OUTCOME.model_dump(mode="json"), "hook_text": "PICK ONE",
}


@pytest.fixture
def season_clip(sandbox, monkeypatch):
    import yaml

    root = sandbox / "channels" / CH
    (root / "season").mkdir(parents=True)
    (root / "cast.toml").write_text(CAST)
    (root / "season" / "s0.yaml").write_text(yaml.safe_dump(SEASON))
    with db.connect() as conn:
        channels.create(conn, name="Gravity Lab", channel_id=CH)
        clip_id = db.insert_clip(conn, channel_id=CH, generator="physics", variant="marble_race",
                                 seed=7, params={}, hook="", plan_why="test")
        db.update(conn, clip_id, status="rendered", facts_json=json.dumps(FACTS), hook_text="PICK ONE")
        conn.execute("UPDATE clips SET level_id = 'L02' WHERE id = ?", (clip_id,))
        conn.execute("INSERT INTO levels (channel_id, season_id, id, clip_id) VALUES (?, 's0', 'L02', ?)",
                     (CH, clip_id))
        conn.commit()

    fake = types.ModuleType("factory.series.standings")
    fake.calls = []

    def table(conn, channel_id, season_id, *, before_level=None):
        fake.calls.append((channel_id, season_id, before_level))
        return [{"entrant_id": e, "name": n, "points": POINTS[e], "wins": 0, "races": 1} for e, n in ENTRANTS]

    fake.table = table
    fake.h2h = lambda conn, channel_id, season_id, a, b, *, before_level=None: (2, 1)
    monkeypatch.setitem(sys.modules, "factory.series.standings", fake)
    return clip_id, fake


def brain(monkeypatch, proposal, seen=None):
    monkeypatch.setattr(llm, "readiness", lambda agents=llm.AGENTS: {a: {"ok": True} for a in agents})

    def propose(**inputs):
        if seen is not None:
            seen.update(inputs)
        return copy_agent.CopyProposal(**proposal), 0.0

    monkeypatch.setattr(copy_agent, "propose", propose)


def _write(conn, clip_id):
    row = db.get(conn, clip_id)
    ch = channels.get(conn, CH)
    return building.written_metadata(row, ch, SimpleNamespace(facts=json.loads(row["facts_json"])), [], [], conn=conn)


def test_a_level_clip_takes_checked_copy_from_the_brain(season_clip, monkeypatch):
    clip_id, fake = season_clip
    seen = {}
    brain(monkeypatch, {
        "title": ["Who survives the flip tonight, then?", "Marble Race: Volt vs the magnet, who stops it?",
                  "Marble Race polarity swap: pulled in, shot out"],
        "hook": ["Pick one before the flip"],
        "pin": ["Launched early: good or bad? Blaze, Tide, Volt or Moss"],
        "desc_line1": ["{entrant_count} marbles, one magnet that flips halfway down."],
    }, seen)
    with db.connect() as conn:
        meta, cost, by = _write(conn, clip_id)
        row = db.get(conn, clip_id)
    assert by == "copy/local" and cost == 0.0
    assert meta.title == "Marble Race polarity swap: pulled in, shot out"
    assert meta.hook_text is None  # recorded, never burned here
    assert meta.description.splitlines() == [
        "4 marbles, one magnet that flips halfway down.",
        "Standings: Blaze 5, Tide 3, Volt 1, Moss 0.",
        "New race every day. Same four marbles.",
    ]
    assert meta.hashtags[0] == "#shorts"
    facts = json.loads(row["facts_json"])
    assert facts["copy_source"] == "local"
    assert facts["copy"]["source"] == {f: "local" for f in copy_check.FIELDS}
    assert facts["copy"]["hook"] == "Pick one before the flip"
    assert facts["copy"]["rejected"][0]["field"] == "title"
    assert row["comment_prompt"] == "Launched early: good or bad? Blaze, Tide, Volt or Moss"
    assert row["hook_text"] == "PICK ONE"
    assert fake.calls == [(CH, "s0", "L02")]
    # The brain never saw who won.
    blob = json.dumps(seen)
    assert "runner_up" not in blob and '"winner"' not in blob and "finishes" not in blob
    assert "placements" not in blob and '"finish"' not in blob
    assert seen["plan_hints"]["title"].startswith("Marble Race")
    assert seen["entrants_in_screen_order"][0] == {"id": "blaze", "name": "Blaze",
                                                   "bio": "Fastest off the line, crashes under pressure"}
    assert "margin_s" not in seen["allowed_placeholders"]["title"]
    events = [e for e in logs.read(limit=20) if e.get("event") == "copy.chosen"]
    assert events and events[0]["source"] == "local"


def test_the_brain_down_means_the_template_for_every_field(season_clip, monkeypatch):
    clip_id, _ = season_clip
    monkeypatch.setattr(llm, "readiness", lambda agents=llm.AGENTS: {a: {"ok": False, "why": "ollama is not answering"}
                                                                     for a in agents})
    monkeypatch.setattr(copy_agent, "propose", lambda **k: pytest.fail("the brain was asked"))
    with db.connect() as conn:
        meta, _, by = _write(conn, clip_id)
        row = db.get(conn, clip_id)
    assert by == "copy/template"
    assert meta.title.startswith(("Pick one", "Call it", "Which one", "Bet on one", "Run it back"))
    assert "lodestone" in meta.title and len(meta.title) <= 45
    assert row["comment_prompt"] == "Blaze, Tide, Volt or Moss — who's your pick?"
    assert meta.description.splitlines()[0] == "4 marbles race down the lodestone."
    facts = json.loads(row["facts_json"])
    assert facts["copy_source"] == "template"
    assert facts["copy"]["hook"] is None
    assert "not ready" in facts["copy"]["rejected"][0]["why"]


def test_a_brain_that_throws_falls_back_too(season_clip, monkeypatch):
    clip_id, _ = season_clip
    monkeypatch.setattr(llm, "readiness", lambda agents=llm.AGENTS: {a: {"ok": True} for a in agents})

    def boom(**_):
        raise ValueError("ollama/qwen2.5:7b did not return valid CopyProposal")

    monkeypatch.setattr(copy_agent, "propose", boom)
    with db.connect() as conn:
        _, _, by = _write(conn, clip_id)
    assert by == "copy/template"


def test_a_repeated_template_pin_rotates_to_another_ending(season_clip, monkeypatch):
    clip_id, _ = season_clip
    with db.connect() as conn:
        other = db.insert_clip(conn, channel_id=CH, generator="physics", variant="marble_race",
                               seed=8, params={}, hook="", plan_why="test")
        db.update(conn, other, comment_prompt="Blaze, Tide, Volt or Moss — who's your pick?")
        result = copywriter.write(conn, clip_id, brain="template")
    assert result.metadata.comment_prompt == "Blaze, Tide, Volt or Moss — which one are you backing?"


def test_season_opener_line_when_the_table_is_all_zeros(season_clip, monkeypatch):
    clip_id, fake = season_clip
    fake.table = lambda conn, c, s, *, before_level=None: [
        {"entrant_id": e, "name": n, "points": 0, "wins": 0, "races": 0} for e, n in ENTRANTS]
    with db.connect() as conn:
        result = copywriter.write(conn, clip_id, brain="template")
    assert result.metadata.description.splitlines()[1] == copywriter.OPENER


def test_mixed_when_some_fields_fall_back(season_clip, monkeypatch):
    clip_id, _ = season_clip
    brain(monkeypatch, {"title": ["Who survives the magnet flip tonight?"], "hook": [], "pin": [], "desc_line1": []})
    with db.connect() as conn:
        result = copywriter.write(conn, clip_id)
    assert result.source == "mixed"
    assert result.chosen.source["title"] == "local" and result.chosen.source["pin"] == "template"


def test_copy_source_template_never_asks_the_brain(season_clip, monkeypatch):
    from factory import settings

    clip_id, _ = season_clip
    settings.load().raw.setdefault("series", {})["copy_source"] = "template"
    monkeypatch.setattr(llm, "readiness", lambda agents=llm.AGENTS: pytest.fail("readiness asked"))
    with db.connect() as conn:
        _, _, by = _write(conn, clip_id)
    assert by == "copy/template"


def test_a_clip_without_a_level_is_written_exactly_as_before(season_clip, monkeypatch):
    from factory import settings
    from factory.agents import template

    settings.load().raw["llm"]["metadata_source"] = "template"
    monkeypatch.setattr(copy_agent, "propose", lambda **k: pytest.fail("the brain was asked"))
    with db.connect() as conn:
        clip_id = db.insert_clip(conn, channel_id=CH, generator="physics", variant="marble_race",
                                 seed=7, params={}, hook="", plan_why="test")
        facts = {k: v for k, v in FACTS.items() if k not in ("outcome", "cast")}
        db.update(conn, clip_id, facts_json=json.dumps(facts))
        row = db.get(conn, clip_id)
        meta, cost, by = building.written_metadata(row, channels.get(conn, CH), SimpleNamespace(facts=facts),
                                                   [], [], conn=conn)
        after = db.get(conn, clip_id)
    expected, _ = template.write_metadata(facts=facts, seed=7)
    assert by == "template" and meta == expected
    assert "copy" not in json.loads(after["facts_json"]) and after["comment_prompt"] is None


def test_submit_copy_applies_through_retitle_or_returns_reasons(season_clip):
    clip_id, _ = season_clip
    with db.connect() as conn:
        db.update(conn, clip_id, title="Pick one — four go down the lodestone", description="Old words here.")
        bad = copywriter.submit(conn, clip_id, {"title": "Volt takes on the magnet: who stops it?",
                                                "hook": "Pick one", "pin": "Who is yours?",
                                                "desc_line1": "Four marbles, one magnet."})
        assert bad["applied"] is False and bad["rejected"][0]["field"] == "title"
        good = copywriter.submit(conn, clip_id, {"title": "Who survives the magnet flip tonight?",
                                                 "hook": "", "pin": "Blaze, Tide, Volt or Moss: who flies?",
                                                 "desc_line1": "{entrant_count} marbles, one magnet."})
        row = db.get(conn, clip_id)
    assert good["applied"] and set(good["changed"]) >= {"title", "description", "pin"}
    assert row["title"] == "Who survives the magnet flip tonight?"
    assert json.loads(row["title_history_json"])[0]["title"] == "Pick one — four go down the lodestone"
    assert row["description"].startswith("4 marbles, one magnet.\nStandings: Blaze 5")
    assert row["comment_prompt"] == "Blaze, Tide, Volt or Moss: who flies?"


def test_the_cli_reruns_copy_and_keeps_the_title_history(season_clip, monkeypatch, capsys):
    from factory.cli import main

    clip_id, _ = season_clip
    with db.connect() as conn:
        db.update(conn, clip_id, title="An older title for this level clip", description="Old words here.")
    assert main(["copy", "--clip", clip_id, "--brain", "template"]) == 0
    out = capsys.readouterr().out
    assert "plan hint" in out and "Marble Race Polarity Swap" in out and "[template]" in out
    with db.connect() as conn:
        row = db.get(conn, clip_id)
    assert json.loads(row["title_history_json"])[0]["title"] == "An older title for this level clip"
    assert json.loads(row["facts_json"])["copy_source"] == "template"


@pytest.mark.anyio
async def test_the_mcp_tools_are_registered(season_clip):
    from factory import mcp

    names = {t.name for t in await mcp.build_server().list_tools()}
    assert {"propose_copy", "submit_copy"} <= names
