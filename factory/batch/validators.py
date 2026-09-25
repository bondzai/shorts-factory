"""The checks a row must pass, one rule per class. Each returns the reasons it
refuses a row (empty: fine). A new rule is a new class in DEFAULT."""

from __future__ import annotations

import re
from typing import Protocol

from ..series import planning
from .context import BatchContext
from .spec import JobSpec

# Generator knobs a row may set in `params`; the series keys are the season's.
PARAM_KEYS = frozenset({"section", "rounds", "max_story_attempts", "prefer_pool",
                        "teams", "win", "mechanics", "round_params"})


class JobValidator(Protocol):
    def check(self, spec: JobSpec, ctx: BatchContext) -> list[str]: ...


class KnownModule:
    def check(self, spec, ctx):
        if spec.level:
            return []
        variants = ctx.modules.get(spec.generator)
        if variants is None:
            return [f"no module {spec.generator!r} on {ctx.channel.id}; have {sorted(ctx.modules)}"]
        if spec.variant not in variants:
            return [f"{spec.generator} has no variant {spec.variant!r} here; have {variants}"]
        return []


class KnownStage:
    def check(self, spec, ctx):
        if spec.stage and spec.stage not in ctx.stages:
            return [f"no stage {spec.stage!r}"]
        return []


class KnownParams:
    def check(self, spec, ctx):
        unknown = sorted(set(spec.params) - PARAM_KEYS)
        return [f"params {unknown} are not settable here; allowed: {sorted(PARAM_KEYS)}"] if unknown else []


class Background:
    def check(self, spec, ctx):
        if spec.background and not re.fullmatch(r"#?[0-9A-Fa-f]{6}", spec.background):
            return [f"background {spec.background!r} is not a #RRGGBB colour"]
        return []


class FreeSeed:
    def check(self, spec, ctx):
        if spec.seed is None:
            return []
        if spec.count > 1:
            return ["a fixed seed makes one clip; drop the seed or set count to 1"]
        if spec.seed in ctx.used_seeds:
            return [f"seed {spec.seed} was already rendered on this channel"]
        if spec.seed in ctx.seen_seeds:
            return [f"seed {spec.seed} appears twice in this batch"]
        return []


class UniqueRef:
    def check(self, spec, ctx):
        if not spec.ref:
            return []
        if spec.ref in ctx.known_refs:
            return [f"ref {spec.ref!r} was already queued (importing the same row twice)"]
        if spec.ref in ctx.seen_refs:
            return [f"ref {spec.ref!r} appears twice in this batch"]
        return []


class PriorityCap:
    def check(self, spec, ctx):
        if spec.priority > ctx.max_priority:
            return [f"priority {spec.priority} is above {ctx.max_priority}, the most this caller may set"]
        return []


class PlannableLevel:
    """A season level takes its stage, cast and story from the season file, and
    is refused for the same reasons `season plan` refuses it."""

    OWN = ("stage", "seed", "background")

    def check(self, spec, ctx):
        if not spec.level:
            return []
        if ctx.season is None:
            return [f"{ctx.channel.id} has no season file, so there is no level {spec.level}"]
        clash = [k for k in self.OWN if getattr(spec, k) is not None] + sorted(spec.params)
        if clash:
            return [f"a level row takes {', '.join(clash)} from the season file; leave them out"]
        if spec.count != 1:
            return ["a level is one clip; count must be 1"]
        if spec.level in ctx.seen_levels:
            return [f"{spec.level} appears twice in this batch"]
        try:
            level = ctx.season.level(spec.level)
        except KeyError as exc:
            return [str(exc).strip("'\"")]
        reason = planning.refusal(ctx.conn, ctx.season, level, replan=False, problems=ctx.season_problems)
        if reason is None and not ctx.channel.allows(level.generator, level.variant):
            reason = f"{ctx.channel.id} does not allow {level.generator}/{level.variant}"
        if reason is None:
            try:
                planning.task_params(level, ctx.season, ctx.cast)
            except (KeyError, ValueError) as exc:
                reason = str(exc)
        return [reason] if reason else []


DEFAULT: tuple[JobValidator, ...] = (KnownModule(), KnownStage(), KnownParams(), Background(),
                                     FreeSeed(), UniqueRef(), PriorityCap(), PlannableLevel())
