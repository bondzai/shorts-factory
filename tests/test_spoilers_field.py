"""The field is everyone who raced, not only who crossed."""

from factory.pipeline.spoilers import spoiler


def test_naming_the_whole_field_of_a_last_standing_race_is_no_spoiler():
    facts = {"winner": "blaze", "finishes": {}, "lineup": ["blaze", "tide", "volt", "moss"],
             "outcome": {"placements": [{"entrant_id": e} for e in ("blaze", "tide", "volt", "moss")]}}
    assert spoiler(facts, comment_prompt="Blaze, Tide, Volt or Moss — who's your pick?") is None
    assert spoiler(facts, comment_prompt="Can Blaze hold on?") is not None


def test_team_marbles_count_as_their_persona():
    facts = {"winner": "tide.2", "finishes": {"tide.2": 11.0},
             "lineup": ["blaze.1", "blaze.2", "tide.1", "tide.2", "volt.1", "volt.2", "moss.1", "moss.2"]}
    assert spoiler(facts, title="Blaze, Tide, Volt or Moss: pick a team") is None
    assert spoiler(facts, title="Tide takes both") is not None
