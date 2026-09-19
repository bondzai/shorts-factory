"""Idea agent: decides what to make next.

This is the 5-minute step in the daily loop. You read what it proposes and edit
or drop anything you disagree with; it does not render anything by itself.
"""

from __future__ import annotations

import json
import random
import sqlite3

from .. import generators, llm
from ..models import ClipPlan, ClipPlanBatch

SYSTEM = """You plan short vertical video clips for a channel aimed at an \
international audience. Every clip is produced entirely in code by one of the \
generators listed below — there is no camera and no narration, so the clip can \
only contain what its generator can actually draw.

Your job is variety inside a narrow format: the same generator and variant with \
a different seed is a different clip, but three near-identical clips in a row is \
how a channel gets flagged as mass-produced. Vary the variant, and say in `hook` \
what is on screen in the first 1.5 seconds.

Obey the rules file exactly. Pick `generator` and `variant` only from the menu, \
spelled exactly as given. Leave `params` empty unless a rule requires an override."""


def _history(rows: list[sqlite3.Row]) -> str:
    if not rows:
        return "No clips yet. This is the first batch."
    lines = []
    for row in rows:
        metrics = ""
        if row["views"] is not None:
            metrics = (
                f" views={row['views']}"
                f" avg_view={row['avg_view_pct']}%"
                f" swipe_away={row['swipe_away_pct']}%"
            )
        lines.append(
            f"- {row['created_at']} {row['generator']}/{row['variant']} "
            f"seed={row['seed']} status={row['status']} "
            f"title={row['title'] or '-'!r}{metrics}"
        )
    return "\n".join(lines)


def propose(
    *,
    count: int,
    rules: str,
    recent: list[sqlite3.Row],
    used_seeds: set[int],
    channel_name: str,
    allowed: list[str] | None = None,
) -> tuple[list[ClipPlan], float]:
    menu = generators.available(allowed)
    if not menu:
        raise ValueError(
            "this channel has no ready generator enabled; add one with "
            "`factory channels edit <id> --variant physics/marble_race`"
        )
    content = (
        f"Channel: {channel_name}\n\n"
        f"Generators available to this channel:\n{generators.catalogue(allowed)}\n\n"
        f"Its rules:\n---\n{rules}\n---\n\n"
        f"The last {len(recent)} clips on this channel, newest first:\n{_history(recent)}\n\n"
        f"Propose exactly {count} clip plan(s)."
    )
    batch, cost = llm.parse(ClipPlanBatch, system=SYSTEM, content=content, max_tokens=8000)

    plans: list[ClipPlan] = []
    rng = random.Random()
    for plan in batch.plans[:count]:
        if plan.generator not in menu:
            raise ValueError(
                f"idea agent picked generator {plan.generator!r}, which this "
                f"channel cannot use; have {sorted(menu)}"
            )
        if plan.variant not in menu[plan.generator]:
            raise ValueError(
                f"idea agent picked variant {plan.variant!r} for {plan.generator!r}; "
                f"have {menu[plan.generator]}"
            )
        # A reused seed would render a byte-identical clip.
        while plan.seed in used_seeds:
            plan = plan.model_copy(update={"seed": rng.randrange(2**31 - 1)})
        used_seeds.add(plan.seed)
        plans.append(plan)

    if len(plans) < count:
        raise ValueError(f"asked for {count} plans, got {len(plans)}")
    return plans, cost


def plan_summary(plan: ClipPlan) -> str:
    return (
        f"{plan.generator}/{plan.variant} seed={plan.seed}\n"
        f"  hook: {plan.hook}\n"
        f"  why:  {plan.why}"
        + (f"\n  params: {json.dumps(plan.params)}" if plan.params else "")
    )
