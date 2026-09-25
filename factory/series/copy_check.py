"""Placeholders and the copy validator (docs/08 §4 "Copy").

A model writes the words; this module decides whether they may ship. Every
measured value reaches published text through a placeholder filled here, so
a number in a title is one the race produced, not one a model guessed. The
checks run on the filled text, because that is what a viewer reads.

Pure: no database, no model. The caller gathers a `CopyContext` (see
`series.copywriter`) and asks `check` or `choose`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable

from ..models import HOOK_MAX, TITLE_MIN
from ..pipeline.spoilers import RESULT_WORDS, spoiler
from ..pipeline.words import EMOJI, FEED_MAX

FIELDS = ("title", "hook", "pin", "desc_line1")
TITLE_HARD_MAX = 70
HOOK_WORDS = 6
PIN_MAX = 140
RECENT = 30  # titles and pins looked back over for repetition
FIRST_WORDS = 4
STANDALONE_MIN = 20  # a prefix shorter than this is not a title on its own
BREAKS = (": ", " — ", " - ", ". ", "? ", "! ")

#: What each placeholder means, as told to a brain.
PLACEHOLDERS: dict[str, str] = {
    "margin_s": "seconds between first and second at the line, like 0.42 (a result of this race)",
    "lead_changes": "how many times the lead changed hands in this race (a result of this race)",
    "entrant_count": "how many marbles are in this race",
    "leader_name": "the name at the top of the season standings before this race",
    "standing:<id>": "that entrant's season points before this race, e.g. {standing:blaze}",
    "h2h:<a>:<b>": "head-to-head before this race, a's wins then b's, like 3–1, e.g. {h2h:blaze:tide}",
}
PRE_RACE = frozenset({"entrant_count", "leader_name", "standing", "h2h"})
RESULTS = frozenset({"margin_s", "lead_changes"})
#: Per field, which placeholders may appear. Results of this race tell the
#: viewer how it goes (a margin is the ending with the name filed off), so
#: they stay out of everything the feed shows; the description body, written
#: by code after line 1, may use them.
ALLOWED: dict[str, frozenset[str]] = {
    "title": PRE_RACE,
    "hook": PRE_RACE,
    "pin": PRE_RACE,
    "desc_line1": PRE_RACE,
    "description": PRE_RACE | RESULTS,
}

TOKEN = re.compile(r"\{([^{}]*)\}")
STACKED = re.compile(r"[!?]{2,}")
# Typographic punctuation a US title uses; everything else must be ASCII.
TYPOGRAPHIC = str.maketrans("", "", "—–’‘“”…")

# How the existing spoiler gate names its fields.
SPOILER_FIELD = {"title": "title", "hook": "hook_text", "pin": "comment_prompt",
                 "desc_line1": "description", "description": "description"}


class PlaceholderError(ValueError):
    """A placeholder that is unknown, not allowed here, or has no value."""


@dataclass
class CopyContext:
    """Everything the validator needs about one level clip."""

    entrants: list[tuple[str, str]]  # (id, display name) in screen order
    values: dict[str, Any] = field(default_factory=dict)  # margin_s, lead_changes, entrant_count, leader_name
    standings: dict[str, int] | None = None  # id -> points before this level; None = unknown
    h2h: Callable[[str, str], tuple[int, int]] | None = None
    known_ids: set[str] = field(default_factory=set)  # every cast id a placeholder may name
    facts: dict[str, Any] = field(default_factory=dict)  # the render's facts, for the existing gate
    winners: set[str] = field(default_factory=set)  # ids and display names of this race's winner(s)
    recent_titles: list[str] = field(default_factory=list)
    recent_pins: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    emoji_ok: bool = False


@dataclass
class Chosen:
    text: dict[str, str | None] = field(default_factory=dict)  # filled, per field
    source: dict[str, str] = field(default_factory=dict)  # "local" | "template" per field
    rejected: list[dict[str, str]] = field(default_factory=list)  # {field, text, why}


# --- placeholders ----------------------------------------------------------------

def _value(name: str, args: list[str], ctx: CopyContext) -> str:
    if name in ("margin_s", "lead_changes", "entrant_count", "leader_name"):
        if args:
            raise PlaceholderError(f"{{{name}}} takes no arguments")
        v = ctx.values.get(name)
        if v is None or v == "":
            raise PlaceholderError(f"{{{name}}} has no value for this race")
        if name == "margin_s":
            return f"{float(v):.2f}".rstrip("0").rstrip(".") if float(v) else "0"
        return str(v)
    if name == "standing":
        if len(args) != 1:
            raise PlaceholderError("{standing:<id>} takes one entrant id")
        (who,) = args
        if who not in ctx.known_ids:
            raise PlaceholderError(f"{{standing:{who}}}: no entrant {who!r}")
        if ctx.standings is None:
            raise PlaceholderError("standings are not available")
        return str(int(ctx.standings.get(who, 0)))
    if name == "h2h":
        if len(args) != 2 or args[0] == args[1]:
            raise PlaceholderError("{h2h:<a>:<b>} takes two different entrant ids")
        for who in args:
            if who not in ctx.known_ids:
                raise PlaceholderError(f"{{h2h:{':'.join(args)}}}: no entrant {who!r}")
        if ctx.h2h is None:
            raise PlaceholderError("head-to-head is not available")
        a, b = ctx.h2h(args[0], args[1])
        return f"{int(a)}–{int(b)}"
    raise PlaceholderError(f"unknown placeholder {{{':'.join([name, *args])}}}")


def placeholders(text: str) -> list[tuple[str, list[str]]]:
    return [(p[0], p[1:]) for p in (m.group(1).strip().split(":") for m in TOKEN.finditer(text))]


def fill(text: str, ctx: CopyContext, field_: str | None = None) -> str:
    """Replace every placeholder with its measured value. With a field, a
    placeholder that field may not use is an error too."""
    allowed = ALLOWED.get(field_) if field_ else None
    for name, _ in placeholders(text):
        if allowed is not None and name not in allowed:
            if name in RESULTS:
                raise PlaceholderError(f"{{{name}}} is a result of this race; not allowed in the {field_}")
            if name not in PRE_RACE:
                raise PlaceholderError(f"unknown placeholder {{{name}}}")
            raise PlaceholderError(f"{{{name}}} is not allowed in the {field_}")

    def sub(m: re.Match) -> str:
        name, *args = m.group(1).strip().split(":")
        return _value(name, args, ctx)

    return TOKEN.sub(sub, text)


# --- the checks -------------------------------------------------------------------

def words(text: str) -> list[str]:
    return re.sub(r"[^a-z0-9' ]", " ", text.lower()).replace("'", "").split()


def first_words(text: str, n: int = FIRST_WORDS) -> tuple[str, ...]:
    return tuple(words(text)[:n])


def stands_alone(title: str) -> bool:
    """A title the feed cuts at 45 characters still has to read as a title:
    either it fits, or a clause ends at or before character 45 leaving at
    least 20 characters in front of the break."""
    if len(title) <= FEED_MAX:
        return True
    for sep in BREAKS:
        start = 0
        while (i := title.find(sep, start)) != -1:
            # The break's own punctuation (":" "." "?" "!") belongs to the prefix.
            end = i + (1 if sep[0] in ":.?!" else 0)
            if end > FEED_MAX:
                break
            if len(title[:end].strip()) >= STANDALONE_MIN:
                return True
            start = i + 1
    return False


def _named(text: str, ctx: CopyContext) -> set[str]:
    """Which of the level's entrants the text names, by display name or id."""
    hit = set()
    for eid, name in ctx.entrants:
        for token in {eid, name}:
            if token and re.search(rf"\b{re.escape(token)}\b", text, re.IGNORECASE):
                hit.add(eid)
    return hit


def _spoiler(field_: str, text: str, ctx: CopyContext) -> str | None:
    key = SPOILER_FIELD.get(field_, field_)
    if problem := spoiler(ctx.facts, **{key: text}):
        return problem
    # The same gate over the cast: once with display names, once with ids, so
    # "Blaze" and "blaze" both count and naming the whole field still passes.
    for pick in (lambda e: e[1], lambda e: e[0]):
        everyone = [pick(e) for e in ctx.entrants]
        won = [pick(e) for e in ctx.entrants if e[0] in ctx.winners or e[1] in ctx.winners]
        if not won:
            continue
        facts = {"rounds": [{"winner": w} for w in won], "finishes": {n: 0 for n in everyone}}
        if problem := spoiler(facts, **{key: text}):
            return problem
    return None


def check(field_: str, text: str, ctx: CopyContext) -> str | None:
    """Why this candidate may not ship, or None. `text` is the raw candidate,
    placeholders unfilled."""
    if field_ not in ALLOWED:
        raise ValueError(f"no field {field_!r}; have {list(ALLOWED)}")
    raw = " ".join((text or "").split())
    if not raw:
        return "empty"
    # 1. digits only from placeholders; placeholders only known and allowed ones.
    if re.search(r"\d", TOKEN.sub("", raw)):
        return "a number not produced by a placeholder; write {placeholder}s, never digits"
    try:
        filled = fill(raw, ctx, field_)
    except PlaceholderError as exc:
        return str(exc)
    # 7. English (checked early: the rest assumes words).
    if EMOJI.search(filled) and not ctx.emoji_ok:
        return "emoji, and the channel's titles setting says none"
    if not EMOJI.sub("", filled).translate(TYPOGRAPHIC).isascii():
        return "not plain English"
    # 2. the existing spoiler gate, over the filled text.
    if problem := _spoiler(field_, filled, ctx):
        return problem
    # 3. all entrants or none.
    named = _named(filled, ctx)
    if named and len(named) < len(ctx.entrants):
        return (f"names {', '.join(sorted(named))} but not the whole field; a title naming one "
                f"marble only passes when it lost — name all of them or none")
    if field_ in ("title", "hook", "pin") and STACKED.search(filled):
        return "stacked punctuation"
    if field_ == "title":
        # 4. length, and the first 45 characters must stand alone.
        if len(filled) > TITLE_HARD_MAX:
            return f"{len(filled)} characters; the limit is {TITLE_HARD_MAX}"
        if len(filled) < TITLE_MIN:
            return f"{len(filled)} characters; the floor is {TITLE_MIN}"
        if not stands_alone(filled):
            return (f"the feed cuts at {FEED_MAX} characters and nothing before that stands alone; "
                    f"end a clause (': ', ' — ', '. ') by character {FEED_MAX}")
        letters = [c for c in filled if c.isalpha()]
        if len(letters) > 3 and all(c.isupper() for c in letters):
            return "all caps"
        # 6. the opening words of any recent title.
        mine = first_words(filled)
        for old in ctx.recent_titles[:RECENT]:
            if old and first_words(old) == mine:
                return f"opens like a recent title ({' '.join(mine)!r})"
    if field_ == "hook":
        # 5. short, and never the result.
        if len(filled.split()) > HOOK_WORDS:
            return f"{len(filled.split())} words; a hook is at most {HOOK_WORDS}"
        if len(filled) > HOOK_MAX:
            return f"{len(filled)} characters; the caption fits {HOOK_MAX}"
        if hit := RESULT_WORDS.search(filled):
            return f"hook tells the result ({hit.group(0)!r})"
    if field_ == "pin":
        if len(filled) > PIN_MAX:
            return f"{len(filled)} characters; a pinned comment here is at most {PIN_MAX}"
        norm = " ".join(filled.lower().split())
        if any(norm == " ".join((p or "").lower().split()) for p in ctx.recent_pins[:RECENT]):
            return "the same pin as a recent clip"
    return None


# --- choosing ----------------------------------------------------------------------

def keyword_first(title: str, keywords: list[str]) -> bool:
    """A channel keyword inside the title's first three words."""
    head = " " + " ".join(words(title)[:3]) + " "
    return any(k.strip() and f" {' '.join(words(k))} " in head for k in keywords)


def candidates(proposal: Any, field_: str) -> list[str]:
    got = proposal.get(field_) if isinstance(proposal, dict) else getattr(proposal, field_, None)
    if isinstance(got, str):
        got = [got]
    return [c for c in (got or []) if isinstance(c, str) and c.strip()]


def choose(proposal: Any, ctx: CopyContext, fallback: dict[str, str | None] | None = None) -> Chosen:
    """Per field, the first candidate that passes, in the model's order —
    titles with a channel keyword in their first three words go first. A
    field with none passing takes `fallback` (source "template")."""
    out = Chosen()
    fallback = fallback or {}
    for f in FIELDS:
        cands = candidates(proposal, f) if proposal is not None else []
        if f == "title" and ctx.keywords:
            cands = sorted(cands, key=lambda c: not keyword_first(_try_fill(c, ctx), ctx.keywords))
        for c in cands:
            why = check(f, c, ctx)
            if why is None:
                out.text[f], out.source[f] = fill(" ".join(c.split()), ctx, f), "local"
                break
            out.rejected.append({"field": f, "text": c, "why": why})
        else:
            out.text[f], out.source[f] = fallback.get(f), "template"
    return out


def _try_fill(text: str, ctx: CopyContext) -> str:
    try:
        return fill(text, ctx)
    except PlaceholderError:
        return text
