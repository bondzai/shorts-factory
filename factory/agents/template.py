"""Metadata the rules already decide: written from the facts, no model.

The channel's rules fix the shape of a title down to the word order — a
verb, the stage by name, the lineup in screen order, never the winner —
and the last thirteen titles an agent wrote were that shape with the
colours swapped. A model at three tokens a second on a mini PC, or at five
dollars a million on an API, was being paid to produce a string a template
produces. So the template produces it, and a brain becomes something the
operator turns on for taste, not something a clip cannot ship without.

Everything here is held to the same gates as an agent's words: the length
bounds on `Metadata`, and the spoiler check in the pipeline.
"""

from __future__ import annotations

from typing import Any

from ..models import TITLE_MAX, Metadata

# Rotated by seed so consecutive clips do not open on the same words; the
# same ritual, not the same sentence. Every one is a verb in the second
# person, which is what the hooks skill asks of a title's first three words.
VERBS = ("Pick your marble", "Call it now", "Which one is yours", "Bet on one", "Pick one")
FEED_MAX = 60  # what a phone shows of a title in the feed before it is cut
HASHTAGS = ["#shorts", "#marblerace", "#marblerun", "#satisfying"]


class Unsupported(ValueError):
    """The template only knows how to write a marble race."""


def can_write(facts: dict[str, Any]) -> bool:
    return facts.get("variant") == "marble_race" and bool(facts.get("lineup"))


def names(lineup: list[str]) -> str:
    """'red, blue or green' — the whole field, in screen order."""
    if len(lineup) == 1:
        return lineup[0]
    return ", ".join(lineup[:-1]) + " or " + lineup[-1]


def title(facts: dict[str, Any], seed: int) -> str:
    """The pick, the stage, the lineup — and the whole lineup or none of it.

    Five colours and a stage leave eleven characters for the verb, so the
    verbs are tried from the seed's starting point and the first that fits
    is used: the rotation survives a long lineup instead of collapsing to
    the shortest verb every time. The stage goes before the colours do, and
    the colours go whole: a title that dropped some would name a subset, and
    a subset that happens to hold the winner is a spoiler by the pipeline's
    own rule.
    """
    lineup, stage = list(facts["lineup"]), stage_of(facts)
    field = names(lineup)
    start = seed % len(VERBS)
    order = VERBS[start:] + VERBS[:start]
    for shape in ("{verb} at the {stage}: {field}", "{verb}: {field}"):
        for verb in order:
            candidate = shape.format(verb=verb, stage=stage, field=field)
            if len(candidate) <= FEED_MAX:
                return candidate
    return f"{order[0]} at the {stage} — {len(lineup)} marbles, one line"[:TITLE_MAX]


def stage_of(facts: dict[str, Any]) -> str:
    """The stage the viewer sees first: the heat's, when there are two."""
    rounds = facts.get("rounds") or []
    return (rounds[0].get("stage") if rounds else None) or facts.get("stage") or "stage"


def description(facts: dict[str, Any]) -> str:
    """First sentence: the scene, present tense, no result — it is checked
    like a title. After it, what a viewer who has watched wants to know."""
    lineup = list(facts["lineup"])
    words = facts.get("stage_words") or f"the {stage_of(facts)}"
    rounds = facts.get("rounds") or []
    first = f"{len(lineup)} marbles race down {words}."
    parts = [first, "Pick one before the first bend."]
    if len(rounds) > 1:
        parts.append(f"Two rounds: a heat on the {rounds[0].get('stage')}, then a final on the {rounds[-1].get('stage')} with the same marbles.")
    margin = facts.get("margin_s")
    if margin is not None:
        parts.append(f"The margin at the line: {margin} s.")
    parts.append("Next race: same marbles, a different stage.")
    return " ".join(parts)


def write_metadata(*, facts: dict[str, Any], seed: int) -> tuple[Metadata, float]:
    """Mirrors `agents.metadata.write_metadata`'s return: (metadata, cost)."""
    if not can_write(facts):
        raise Unsupported(f"the template only writes marble races; this is {facts.get('variant')!r}")
    lineup = list(facts["lineup"])
    return Metadata(
        title=title(facts, seed),
        description=description(facts),
        hashtags=list(HASHTAGS),
        rationale="Template: the shape the channel's rules require, filled from the render's facts.",
        hook_text=None,  # the render's caption bank chose one already
        comment_prompt=f"{names(lineup).capitalize()} — which did you back?",
    ), 0.0
