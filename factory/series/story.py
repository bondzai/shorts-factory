"""Story predicates: a small closed language evaluated on an Outcome.

`must` decides whether a seed is kept; `prefer` ranks the seeds that pass.
There is no eval: a predicate is a known name and a value, and a comparison
is a string like ">=1" or "<=0.8".

Identity predicates name who wins, ranks or falls. docs/08 rule 2.4 keeps
them out of a season by default, because searching seeds until a named
marble loses is choosing the result; `season check` enforces that, and this
module only evaluates what it is given.
"""

from __future__ import annotations

import operator
import re
from typing import Any

from .outcome import Outcome

IDENTITY = frozenset({"winner_in", "winner_not_in", "rank_of", "eliminated_includes"})
MECHANISM = frozenset({"margin_s", "lead_changes", "any_event", "no_event", "finishers", "rounds"})
PREDICATES = IDENTITY | MECHANISM

_OPS = {">=": operator.ge, "<=": operator.le, "==": operator.eq, "!=": operator.ne,
        ">": operator.gt, "<": operator.lt}
_COMPARISON = re.compile(r"^\s*(>=|<=|==|!=|>|<)?\s*(-?\d+(?:\.\d+)?)\s*$")


class StoryError(ValueError):
    """A predicate or comparison this language does not have."""


def comparison(text: Any) -> tuple[str, float]:
    m = _COMPARISON.match(str(text))
    if not m:
        raise StoryError(f"not a comparison: {text!r} (use e.g. \">=1\" or \"<=0.8\")")
    return m.group(1) or "==", float(m.group(2))


def _compare(value: float | None, text: Any) -> bool:
    if value is None:
        return False
    op, target = comparison(text)
    return _OPS[op](float(value), target)


def _names(value: Any) -> list[str]:
    return [value] if isinstance(value, str) else list(value)


def validate(spec: dict[str, Any] | None) -> list[str]:
    """Problems with a must/prefer block, without an outcome to test it on."""
    problems: list[str] = []
    for name, value in (spec or {}).items():
        if name not in PREDICATES:
            problems.append(f"unknown predicate {name!r}; have {sorted(PREDICATES)}")
            continue
        try:
            if name in ("margin_s", "lead_changes", "finishers", "rounds"):
                comparison(value)
            elif name == "rank_of":
                if not isinstance(value, dict) or not value:
                    raise StoryError("rank_of wants {entrant: comparison}")
                for cmp in value.values():
                    comparison(cmp)
            elif not value:
                raise StoryError(f"{name} wants a name or a list")
        except StoryError as exc:
            problems.append(f"{name}: {exc}")
    return problems


def failures(outcome: Outcome, spec: dict[str, Any] | None) -> list[str]:
    """Every predicate in `spec` the outcome does not satisfy; empty means pass."""
    missed: list[str] = []
    kinds = {e.kind for e in outcome.events}
    for name, value in (spec or {}).items():
        if name == "margin_s":
            ok = _compare(outcome.margin_s, value)
        elif name == "lead_changes":
            ok = _compare(outcome.lead_changes, value)
        elif name == "finishers":
            ok = _compare(sum(1 for p in outcome.placements if p.status == "finished"), value)
        elif name == "rounds":
            ok = _compare(len(outcome.facts.get("rounds") or [None]), value)
        elif name == "any_event":
            ok = any(k in kinds for k in _names(value))
        elif name == "no_event":
            ok = not any(k in kinds for k in _names(value))
        elif name == "winner_in":
            ok = outcome.winner in _names(value)
        elif name == "winner_not_in":
            ok = outcome.winner is not None and outcome.winner not in _names(value)
        elif name == "rank_of":
            ok = all(_compare(outcome.rank_of(who), cmp) for who, cmp in value.items())
        elif name == "eliminated_includes":
            out = {e.entrant_id for e in outcome.events if e.kind in ("eliminated", "trap_catch")}
            out |= {p.entrant_id for p in outcome.placements if p.status in ("eliminated", "out")}
            ok = all(who in out for who in _names(value))
        else:
            raise StoryError(f"unknown predicate {name!r}")
        if not ok:
            missed.append(f"{name} {value!r}")
    return missed


def score(outcome: Outcome, prefer: dict[str, Any] | None) -> float:
    """Share of `prefer` predicates satisfied, 0..1; 1 when there are none."""
    if not prefer:
        return 1.0
    return 1.0 - len(failures(outcome, prefer)) / len(prefer)


def identity_predicates(spec: dict[str, Any] | None) -> list[str]:
    return sorted(set(spec or {}) & IDENTITY)
