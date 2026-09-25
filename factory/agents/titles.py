"""The Title agent: five ways to ask for the pick, one per angle.

The template writes the title the rules fix. This is for when the operator
wants a different way in — and the point is variety of *angle*, not a break
from the ritual. Every idea still asks the viewer to choose a side and never
tells the result; the server checks that after the model has answered, so
nothing here is trusted.

Text only: the facts, the lineup and the stage in words are enough to write
a title, and a call with no frames is a few hundred tokens — cheap on an
API, seconds on a CPU.
"""

from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, Field

from .. import llm

Angle = Literal["pick", "curiosity", "stakes", "challenge", "series"]

ANGLES: dict[str, str] = {
    "pick": "ask them to choose a marble; say how many and where, not which colours",
    "curiosity": "say there is an outcome without saying what it is — a gap they stay to close",
    "stakes": "a number from the facts that describes the scene (marbles, obstacles, throats), never the ending",
    "challenge": "dare them to call it before the stage's mechanism decides",
    "series": "make it one of a run — same marbles, another stage; a reason to come back",
}


class TitleIdea(BaseModel):
    angle: Angle
    title: str = Field(max_length=120)
    caption: str | None = Field(default=None, max_length=40,
                                description="Two or three words for the opening frame, second person, a verb. Optional.")
    why: str = Field(max_length=200, description="One sentence: what this angle is doing to the thumb.")


class TitleIdeas(BaseModel):
    # One per angle is asked for; fewer is the server's problem to report, not
    # a reason to throw the whole answer away.
    ideas: list[TitleIdea] = Field(min_length=1, max_length=7)


SYSTEM = """You write titles for silent, vertical marble-race videos on a US \
Shorts feed. A viewer gives a title one second, and in that second it has one \
job: make them pick a marble. A viewer who has picked has a stake, and a \
viewer with a stake stays to the finish.

Rules the server enforces after you answer, so obey them or the idea is thrown \
away: never name the winner; never tell the result in any form (no "decided", \
"wins", "won", "upset", "photo finish", no margin like "by 0.4s"); no result \
language at all. Do not list the colours in the title: the title sits on the \
playing video where the colours are already on screen, and the feed cuts a \
title at about 45 characters — the pinned comment names them instead. \
Sentence case, under 45 characters, American English, no \
emoji unless told you may, no ALL CAPS, no exclamation marks, no Thai. \
Present tense, second person. Every colour, number and stage you mention must \
be in the facts — a promise the clip does not keep costs more than a dull title.

Write one idea per angle asked for, each a genuinely different way in, and \
none of them shaped like the titles already used on this channel."""


def suggest(*, facts: dict[str, Any], recent_titles: list[str], directions: str,
            emoji_allowed: bool, want_captions: bool, lessons: str = "") -> tuple[TitleIdeas, float]:
    lineup = facts.get("lineup") or []
    text = (
        f"Facts about the clip (only these are true):\n{json.dumps(facts, default=str)}\n\n"
        f"The lineup, in the order they appear on screen: {', '.join(lineup) or 'unknown'}\n"
        f"The stage, in the render's words: {facts.get('stage_words') or facts.get('stage') or 'unknown'}\n\n"
        "Angles — write exactly one title for each:\n"
        + "\n".join(f"- {k}: {v}" for k, v in ANGLES.items())
        + "\n\nTitles already used on this channel — do not repeat their shape or their first three words:\n"
        + ("\n".join(f"- {t}" for t in recent_titles) if recent_titles else "- none yet")
        + (f"\n\nOperator's directions:\n{directions}" if directions else "")
        + (f"\n\nLessons this channel's numbers taught (adopted by the operator):\n{lessons}" if lessons else "")
        + ("\n\nOne emoji at the end of a title is allowed." if emoji_allowed else "\n\nNo emoji.")
        + ("\n\nAlso give each idea a caption: two or three words for the opening frame, "
           "second person, a verb, no colours, no numbers." if want_captions else "")
    )
    return llm.parse(TitleIdeas, system=SYSTEM, content=text, max_tokens=1500, agent="metadata")
