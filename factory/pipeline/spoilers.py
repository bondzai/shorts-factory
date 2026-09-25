"""The one rule a title has to obey: do not give the race away.

Checked against the render's own facts rather than against taste, so it is a
measurement. Everything that writes words on a clip asks this module first.
"""

from __future__ import annotations

import re


def _persona(name: str) -> str:
    """A team marble ("blaze.2") is its persona's; the viewer reads "Blaze"."""
    return name.split(".", 1)[0]


def winners(facts: dict) -> set[str]:
    """Every marble that won a round, from the render's own facts."""
    names = [r.get("winner") for r in facts.get("rounds") or []] + [facts.get("winner")]
    return {_persona(n) for n in names if n}


def lineup(facts: dict) -> set[str]:
    """Everyone who raced. Not only who crossed: in an elimination or
    last-standing race nobody may cross, and a field read from the finishes
    alone made "Blaze, Tide, Volt or Moss" look like it named just the winner."""
    names: set[str] = set(facts.get("finishes") or {})
    for r in facts.get("rounds") or []:
        names |= set(r.get("finishes") or {})
    names |= set(facts.get("lineup") or []) | set(facts.get("cast") or [])
    names |= {p.get("entrant_id") for p in (facts.get("outcome") or {}).get("placements") or [] if p.get("entrant_id")}
    return {_persona(n) for n in names if n}


RESULT_WORDS = re.compile(
    r"\b(decided|wins?\s+by|won|took|takes\s+it|beat|beats|beaten|edges|edged|"
    r"by\s+(a\s+)?(nose|hair|inch|whisker)|by\s+\d+(\.\d+)?\s*(s|sec|seconds?)|"
    r"photo\s+finish|upset)\b", re.IGNORECASE)


def spoiler(facts: dict, **texts: str | None) -> str | None:
    """Which text names a winner, if any — the title has one job, keeping the
    viewer for the result, and a title that contains the result has already
    paid them out. Checked against facts, so it is a measurement, not taste.

    Naming the whole lineup ("red, blue or amber — which did you back?") gives
    nothing away, so that passes; singling out a winner does not."""
    won, field_ = winners(facts), lineup(facts)
    if not won and not field_:
        # Nothing raced, so there is no result to give away. An ASMR clip of
        # coins falling has no winner, and refusing its title for the word
        # "took" would be a rule enforcing itself rather than the point.
        return None
    for field, text in texts.items():
        if not text:
            continue
        if field in ("title", "hook_text") and (hit := RESULT_WORDS.search(text)):
            return (f"{field} tells the result ({hit.group(0)!r}); write the scene in the "
                    f"present tense — what they are about to watch, not how it ended")
        named = {n for n in won | field_ if re.search(rf"\b{re.escape(n)}\b", text, re.IGNORECASE)}
        if named & won and not (field_ and field_ <= named):
            name = sorted(named & won)[0]
            return f"{field} names the winner ({name}); state the stake, not the result"
    return None
