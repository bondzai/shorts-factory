"""`season check`: a season file held against its cast and docs/08 §4.

Pure: it reads a loaded `Season` and `Cast` and returns problems. The caller
supplies what only the generator layer knows (the physics stage ids) so this
package never imports a generator.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import asdict, dataclass
from typing import Any, Iterable, Literal

from . import story
from .cast import Cast, level_number
from .season import Level, Season

Severity = Literal["error", "warning"]

#: Levels that do not slide (docs/08 §6 Calendar).
ANCHORED = {
    "L37": dt.date(2026, 10, 31),
    "L63": dt.date(2026, 11, 26),
    "L92": dt.date(2026, 12, 25),
    "L98": dt.date(2026, 12, 31),
}
#: Levels within which the same stage and entrants need `rematch_of`, and
#: which may hold at most one rematch.
REMATCH_WINDOW = 10
PLACEHOLDER = re.compile(r"\{([^{}]*)\}")
SIMPLE_PLACEHOLDERS = frozenset({"margin_s", "lead_changes", "entrant_count", "leader_name"})
HINT_FIELDS = ("angle", "title", "hook", "pin", "desc")


@dataclass
class Problem:
    level_id: str | None  # None: the season as a whole
    severity: Severity
    message: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    def __str__(self) -> str:
        return f"{self.severity:7} {self.level_id or '-':5} {self.message}"


def stage_key(level: Level) -> tuple[Any, Any] | None:
    """What "the same stage" means: (params.stage, params.section); None if neither."""
    key = (level.params.get("stage"), level.params.get("section"))
    return None if key == (None, None) else key


def placeholder_problems(text: str, cast_ids: set[str] | None) -> list[str]:
    """Unknown placeholders, and digits that did not come from one."""
    out = []
    for name in PLACEHOLDER.findall(text):
        parts = name.split(":")
        if name in SIMPLE_PLACEHOLDERS:
            continue
        if parts[0] == "standing" and len(parts) == 2 and parts[1]:
            ids = parts[1:]
        elif parts[0] == "h2h" and len(parts) == 3 and all(parts[1:]):
            ids = parts[1:]
        else:
            out.append(f"unknown placeholder {{{name}}}")
            continue
        if cast_ids is not None:
            out += [f"placeholder {{{name}}} names {i!r}, not in the cast" for i in ids if i not in cast_ids]
    if re.search(r"\d", PLACEHOLDER.sub("", text)):
        out.append(f"a digit outside a placeholder in {text!r} (draft numbers must not survive)")
    return out


def check(
    season: Season,
    cast: Cast | None,
    *,
    stages: set[str] | None,
    allow_identity: bool,
    channel_variants: Iterable[str] | None,
) -> list[Problem]:
    """Every problem in the season; an empty list means it may be planned.

    `stages`: known physics stage ids (None skips that check).
    `channel_variants`: "generator/variant" strings the channel allows; empty
    or None means any.
    """
    problems: list[Problem] = []

    def err(level: str | None, message: str) -> None:
        problems.append(Problem(level, "error", message))

    def warn(level: str | None, message: str) -> None:
        problems.append(Problem(level, "warning", message))

    allowed = set(channel_variants or [])
    cast_ids = set(cast.ids()) if cast else None

    levels: list[Level] = []
    seen: set[str] = set()
    for lv in season.levels:
        try:
            level_number(lv.id)
        except ValueError as exc:
            err(lv.id, str(exc))
            continue
        if lv.id in seen:
            err(lv.id, "level id appears twice")
            continue
        seen.add(lv.id)
        levels.append(lv)
    if [lv.id for lv in levels] != sorted((lv.id for lv in levels), key=level_number):
        err(None, "levels are not in order of their number")
    levels.sort(key=lambda lv: level_number(lv.id))
    by_id = {lv.id: lv for lv in levels}

    for lv in levels:
        # cast
        if lv.entrants and cast is None:
            err(lv.id, "names entrants but the channel has no cast.toml")
        elif cast is not None:
            if len(set(lv.entrants)) != len(lv.entrants):
                err(lv.id, "an entrant appears twice")
            for who in lv.entrants:
                if who not in cast_ids:
                    err(lv.id, f"entrant {who!r} is not in the cast")
                elif not cast.get(who).debuted_by(lv.id):
                    err(lv.id, f"entrant {who!r} appears before their debut {cast.get(who).debut}")
        # story
        for part in ("must", "prefer"):
            spec = getattr(lv.story, part)
            for msg in story.validate(spec):
                err(lv.id, f"story.{part}: {msg}")
            for name in story.identity_predicates(spec):
                if not allow_identity:
                    err(lv.id, f"story.{part}: {name} chooses who wins, ranks or falls "
                               "(docs/08 rule 2.4; [series] allow_identity_constraints is off)")
        # status
        if lv.status == "blocked" and not lv.blocked_on:
            err(lv.id, "status blocked needs blocked_on")
        missing = lv.missing_input()
        if lv.status == "needs_input" and not missing:
            err(lv.id, "status needs_input but operator_input has nothing left to fill")
        if lv.status == "ready" and missing:
            err(lv.id, f"operator_input still to fill: {', '.join(missing)}; status should be needs_input")
        # module and stage
        if allowed and f"{lv.generator}/{lv.variant}" not in allowed:
            err(lv.id, f"{lv.generator}/{lv.variant} is not allowed on this channel ({sorted(allowed)})")
        stage = lv.params.get("stage")
        if stages is not None and lv.generator == "physics" and lv.status != "blocked" and stage:
            if stage not in stages:
                err(lv.id, f"no physics stage {stage!r}")
        # copy hints
        for field in HINT_FIELDS:
            text = getattr(lv.copy_, field)
            if text:
                for msg in placeholder_problems(text, cast_ids):
                    err(lv.id, f"copy.{field}: {msg}")
        # rematch
        if lv.rematch_of:
            ref = by_id.get(lv.rematch_of)
            try:
                earlier = level_number(lv.rematch_of) < level_number(lv.id)
            except ValueError:
                earlier = False
            if ref is None or not earlier:
                err(lv.id, f"rematch_of {lv.rematch_of!r} is not an earlier level of this season")
        # dates
        anchored = ANCHORED.get(lv.id)
        if anchored and lv.date != anchored:
            err(lv.id, f"date {lv.date} but {lv.id} is anchored to {anchored}")
        if lv.note and lv.status == "ready" and "TODO" in lv.note:
            warn(lv.id, f"note still says TODO: {lv.note}")

    for prev, lv in zip(levels, levels[1:]):
        if lv.date < prev.date:
            err(lv.id, f"date {lv.date} is before {prev.id}'s {prev.date}")
        differs = [
            stage_key(prev) != stage_key(lv),
            set(prev.entrants) != set(lv.entrants),
            prev.format != lv.format,
            prev.story.must != lv.story.must,
        ]
        if sum(differs) < 2:
            err(lv.id, f"differs from {prev.id} in fewer than two of stage, entrants, format, "
                       "story must (anti-repetition)")

    for i, lv in enumerate(levels):
        key = stage_key(lv)
        if key is None or lv.rematch_of:
            continue
        n = level_number(lv.id)
        for prev in levels[:i]:
            if n - level_number(prev.id) < REMATCH_WINDOW and stage_key(prev) == key \
                    and set(prev.entrants) == set(lv.entrants):
                err(lv.id, f"same stage and entrants as {prev.id} within {REMATCH_WINDOW} levels "
                           "without rematch_of")
                break
    rematches = [level_number(lv.id) for lv in levels if lv.rematch_of]
    for i, n in enumerate(rematches):
        crowd = [m for m in rematches[i + 1:] if m - n < REMATCH_WINDOW]
        if crowd:
            err(f"L{crowd[0]:02d}", f"a second rematch within {REMATCH_WINDOW} levels of L{n:02d}")
    return problems


def errors(problems: Iterable[Problem]) -> list[Problem]:
    return [p for p in problems if p.severity == "error"]
