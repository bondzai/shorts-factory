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
# same ritual, not the same sentence. Every shape asks for the pick in its
# first three words and names the stage, and none of them lists the colours:
# in the Shorts feed the title sits on the playing video, where the colours
# are already on screen, and the feed cuts a title at about 45 characters —
# on a five-marble race the list was exactly the part that got cut. The
# pinned comment is where the colours belong, because that is where the
# viewer answers with one.
SHAPES = (
    "Pick one \u2014 {n} go down the {stage}",
    "Call it now: {n} marbles, the {stage}",
    "Which one is yours? {n} down the {stage}",
    "Bet on one \u2014 {n} go down the {stage}",
    "Run it back: {n} marbles, the {stage}",
)
FEED_MAX = 45  # what a phone shows of a title in the Shorts feed before it is cut
HASHTAGS = ["#shorts", "#marblerace", "#marblerun", "#satisfying"]
NUMBERS = {2: "two", 3: "three", 4: "four", 5: "five", 6: "six", 7: "seven", 8: "eight"}


class Unsupported(ValueError):
    """The template only knows how to write a marble race."""


def can_write(facts: dict[str, Any]) -> bool:
    return facts.get("variant") == "marble_race" and bool(facts.get("lineup"))


def names(lineup: list[str]) -> str:
    """'red, blue or green' — the whole field, in screen order. For the pinned
    comment, where the viewer answers with a colour."""
    if len(lineup) == 1:
        return lineup[0]
    return ", ".join(lineup[:-1]) + " or " + lineup[-1]


def title(facts: dict[str, Any], seed: int, taken: set[str] = frozenset()) -> str:
    """The pick, the count, the stage — inside what the feed shows.

    Shapes are tried from the seed's starting point and the first that fits
    45 characters is used, so the rotation survives a long stage name instead
    of collapsing to the shortest shape every time. `taken` is the channel's
    recent titles: two four-marble races on the spillway landed on the same
    seed slot and shipped the same title twice, which reads as a re-upload.
    A shape already on the channel is passed over while another fits.
    """
    n = NUMBERS.get(len(facts["lineup"]), str(len(facts["lineup"])))
    stage = stage_of(facts)
    start = seed % len(SHAPES)
    fits = [c for shape in SHAPES[start:] + SHAPES[:start]
            if len(c := shape.format(n=n, stage=stage)) <= FEED_MAX]
    for candidate in fits:
        if candidate not in taken:
            return candidate
    if fits:
        return fits[0]
    return f"Pick one \u2014 {n} marbles, one line"[:TITLE_MAX]


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
    parts = [first, f"Pick one before the first bend: {names(lineup)}."]
    if len(rounds) > 1:
        parts.append(f"Two rounds: a heat on the {rounds[0].get('stage')}, then a final on the {rounds[-1].get('stage')} with the same marbles.")
    margin = facts.get("margin_s")
    if margin is not None:
        parts.append(f"The margin at the line: {margin} s.")
    parts.append("Next race: same marbles, a different stage.")
    return " ".join(parts)


def write_metadata(*, facts: dict[str, Any], seed: int, taken: set[str] = frozenset()) -> tuple[Metadata, float]:
    """Mirrors `agents.metadata.write_metadata`'s return: (metadata, cost)."""
    if not can_write(facts):
        raise Unsupported(f"the template only writes marble races; this is {facts.get('variant')!r}")
    lineup = list(facts["lineup"])
    return Metadata(
        title=title(facts, seed, taken),
        description=description(facts),
        hashtags=list(HASHTAGS),
        rationale="Template: the shape the channel's rules require, filled from the render's facts.",
        hook_text=None,  # the render's caption bank chose one already
        comment_prompt=f"{names(lineup).capitalize()} — which did you back?",
    ), 0.0
