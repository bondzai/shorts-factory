"""The Copy agent: a season level's title, hook, pinned comment and the first
line of its description, three candidates each.

Text only and trusted with nothing. It is shown the race without its result
(who won, the order, the finish events are removed before it sees a word),
writes measured values as placeholders the code fills, and every candidate
goes through `series.copy_check` after it answers. The first that passes is
used; none passing means the template's words, so a slow or absent model
costs a clip nothing but taste.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field

from .. import llm


class CopyProposal(BaseModel):
    title: list[str] = Field(default_factory=list, max_length=3)
    hook: list[str] = Field(default_factory=list, max_length=3)
    pin: list[str] = Field(default_factory=list, max_length=3)
    desc_line1: list[str] = Field(default_factory=list, max_length=3)


SYSTEM = """You write the words for one episode of a marble-race series on a \
US YouTube Shorts channel: up to three candidates each for the title, the hook \
(the caption on the opening frames), the pinned comment, and the first line of \
the description. Plain American English.

Code checks every candidate and throws away any that breaks a rule:
1. No digits. Write a number only as a {placeholder} from the list you are \
given, and only in the fields that list allows.
2. Never say or hint who wins, loses or falls, or how it ends ("wins", "won", \
"beats", "upset", "photo finish", a margin). You are not told the result; do \
not guess it.
3. Name every marble in the race or none of them. Naming one or two tells the \
viewer something.
4. Title: at most 70 characters, and the first 45 must read as a title on \
their own (the feed cuts there) — end a clause with ": " or " — " before \
character 45, or stay under 45. Hook: at most 6 words.

Do not open a title with the same four words as a recent title, and do not \
repeat a recent pin. No ALL CAPS, no "!!" or "?!". Present tense: what the \
viewer is about to watch."""


def propose(**inputs: Any) -> tuple[CopyProposal, float]:
    """One call. `inputs` is the JSON-able dict `series.copywriter.inputs`
    builds; it is sent as it stands."""
    content = (
        "Everything you may use about this episode (only this is true):\n"
        + json.dumps(inputs, default=str, indent=1)
        + "\n\nReply with up to three candidates for each of title, hook, pin and desc_line1."
    )
    return llm.parse(CopyProposal, system=SYSTEM, content=content, max_tokens=1500, agent="copy")
