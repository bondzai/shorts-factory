"""Where accepted rows go: the task queue. Level rows go through the season's
own planning so the levels table stays true."""

from __future__ import annotations

from typing import Protocol

from .. import tasks
from ..series import planning
from .context import BatchContext
from .spec import JobSpec


class JobSink(Protocol):
    def write(self, spec: JobSpec, ctx: BatchContext, *, batch_id: str, by: str) -> list[int]: ...


def _words(spec: JobSpec) -> dict:
    out = {}
    if spec.brief:
        out["brief"] = spec.brief
    if spec.hints and spec.hints.compact():
        out["hints"] = spec.hints.compact()
    return out


class TaskSink:
    def write(self, spec, ctx, *, batch_id, by):
        if spec.level:
            level = ctx.season.level(spec.level)
            params = {**planning.task_params(level, ctx.season, ctx.cast), **_words(spec)}
            return [planning.queue_level(ctx.conn, ctx.channel, ctx.season, level, params, by=by,
                                         priority=spec.priority, batch_id=batch_id, ref=spec.ref)]
        params = {"generator": spec.generator, "variant": spec.variant, "stage": spec.stage,
                  "seed": spec.seed, "background": spec.background, **spec.params, **_words(spec)}
        return tasks.enqueue(ctx.conn, ctx.channel.id, spec.kind, params, count=spec.count, by=by,
                             priority=spec.priority, batch_id=batch_id, ref=spec.ref)
