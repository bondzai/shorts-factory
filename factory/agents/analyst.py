"""Analyst agent: reads the metrics table, writes the digest, proposes rules.

The gate matters more than the prompt. Below `[analyst] min_published_for_rules`
published clips with metrics, proposed rules are discarded in code, however
confident the model sounds — with n that small, any pattern it finds is noise,
and following it means retuning the pipeline against randomness.
"""

from __future__ import annotations

import json
import sqlite3

from .. import llm, settings
from ..models import Digest

SYSTEM = """You analyse performance data for a channel of short vertical videos.

You are given one row per published clip: generator, variant, seed, title, views, \
average view percentage, swipe-away percentage, likes.

Report only what the numbers support. State n for every claim. If two variants \
differ by less than the spread within either one, say they are indistinguishable \
— that is a useful finding. Do not invent audience psychology to explain a \
difference; name the number and stop.

Propose a rule only when the evidence would still hold if the three best-performing \
clips were removed from the sample. Each proposed rule is one markdown bullet, \
written as an instruction a writer could follow, not as an observation."""


def _rows_for_model(rows: list[sqlite3.Row]) -> str:
    keep = (
        "created_at", "generator", "variant", "seed", "title",
        "views", "avg_view_pct", "swipe_away_pct", "likes",
    )
    return json.dumps([{k: row[k] for k in keep} for row in rows], indent=1)


def digest(rows: list[sqlite3.Row]) -> tuple[Digest, float, bool]:
    """Returns (digest, cost, rules_allowed)."""
    cfg = settings.load().raw["analyst"]
    n = len(rows)
    rules_allowed = n >= cfg["min_published_for_rules"]

    content = (
        f"{n} published clips have metrics. The threshold for proposing rules is "
        f"{cfg['min_published_for_rules']}.\n"
        + (
            ""
            if rules_allowed
            else "You are below the threshold: report the numbers and leave "
            "proposed_rules empty.\n"
        )
        + f"\nData:\n{_rows_for_model(rows)}"
    )
    result, cost = llm.parse(Digest, system=SYSTEM, content=content, max_tokens=16000)

    if not rules_allowed and result.proposed_rules:
        # The gate is enforced here, not in the prompt.
        result = result.model_copy(update={"proposed_rules": []})
    return result, cost, rules_allowed


MARKER_BEGIN = "<!-- analyst:begin -->"
MARKER_END = "<!-- analyst:end -->"


def apply_rules(bullets: list[str]) -> int:
    """Append accepted rules between the markers in rules.md. Returns how many."""
    if not bullets:
        return 0
    path = settings.load().rules_path
    text = path.read_text()
    if MARKER_BEGIN not in text or MARKER_END not in text:
        raise ValueError(f"{path} is missing the analyst markers")
    head, rest = text.split(MARKER_BEGIN, 1)
    body, tail = rest.split(MARKER_END, 1)
    addition = "\n".join(f"- {b.lstrip('- ').strip()}" for b in bullets)
    new_body = f"{body.rstrip()}\n{addition}\n"
    path.write_text(f"{head}{MARKER_BEGIN}{new_body}{MARKER_END}{tail}")
    return len(bullets)


def render_digest(result: Digest, n: int, rules_allowed: bool) -> str:
    lines = [f"# Digest — {n} published clips with metrics", "", result.summary, ""]
    if result.findings:
        lines.append("## Findings")
        for finding in result.findings:
            lines.append(f"- **{finding.claim}** (n={finding.n}, {finding.confidence})")
            lines.append(f"  - {finding.evidence}")
        lines.append("")
    if result.proposed_rules:
        lines.append("## Proposed rules")
        lines.extend(f"- {rule}" for rule in result.proposed_rules)
    elif not rules_allowed:
        lines.append("_Below the sample threshold; no rules proposed._")
    return "\n".join(lines)
