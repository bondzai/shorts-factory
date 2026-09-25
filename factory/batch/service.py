"""Bulk work, start to finish: read, expand, check every row, then write —
or write nothing.

The service only knows the four roles (source, expanders, validators, sink);
the CLI, MCP and API each build one and hand it a source.
"""

from __future__ import annotations

import uuid
from typing import Iterable, Protocol

from pydantic import ValidationError

from .. import db, logs
from ..series import planning
from .context import BatchContext
from .sink import JobSink
from .sources import JobSource
from .spec import JobSpec, Receipt, Row, RowResult
from .validators import JobValidator


class JobExpander(Protocol):
    def expand(self, spec: JobSpec, ctx: BatchContext) -> list[JobSpec]: ...


class LevelRange:
    """"L02..L05" becomes one row per level; a ref gets the level appended."""

    def expand(self, spec, ctx):
        if not spec.level or (".." not in spec.level and "," not in spec.level):
            return [spec]
        return [spec.model_copy(update={"level": lv, "ref": f"{spec.ref}:{lv}" if spec.ref else None})
                for lv in planning.parse_levels(spec.level)]


def _reason(exc: ValidationError) -> str:
    return "; ".join(f"{'.'.join(str(p) for p in e['loc']) or 'row'}: {e['msg']}" for e in exc.errors())


class BatchService:
    def __init__(self, validators: Iterable[JobValidator], sink: JobSink,
                 expanders: Iterable[JobExpander] = (LevelRange(),), max_rows: int = 500):
        self.validators, self.sink = tuple(validators), sink
        self.expanders, self.max_rows = tuple(expanders), max_rows

    def _rows(self, source: JobSource, ctx: BatchContext) -> list[Row]:
        raws = list(source.read())
        if len(raws) > self.max_rows:
            raise ValueError(f"{len(raws)} rows; a batch holds at most {self.max_rows}")
        rows: list[Row] = []
        for n, raw in enumerate(raws, 1):
            try:
                specs = [JobSpec(**raw)]
                for expander in self.expanders:
                    specs = [out for s in specs for out in expander.expand(s, ctx)]
            except ValidationError as exc:
                rows.append(Row(n, raw, problems=[_reason(exc)]))
                continue
            except (ValueError, TypeError) as exc:
                rows.append(Row(n, raw, problems=[str(exc)]))
                continue
            rows.extend(Row(n, raw, spec=s) for s in specs)
        for row in rows:
            if row.spec is None:
                continue
            row.problems = [p for v in self.validators for p in v.check(row.spec, ctx)]
            if not row.problems:
                ctx.remember(row.spec)
        return rows

    def submit(self, ctx: BatchContext, source: JobSource, *, by: str, dry_run: bool = False,
               partial: bool = False, ref: str | None = None) -> Receipt:
        """All rows or none by default; `partial` writes the rows that pass.
        `dry_run` writes nothing and says what would happen."""
        rows = self._rows(source, ctx)
        refused = [r for r in rows if r.problems]

        def result(row: Row, ids: list[int] | None = None) -> RowResult:
            spec = row.spec
            return RowResult(row=row.number, ref=spec.ref if spec else row.raw.get("ref"),
                             level=spec.level if spec else row.raw.get("level"), queued=bool(ids),
                             task_ids=ids or [], reason="; ".join(row.problems) or None)

        if dry_run or (refused and not partial):
            note = ("dry run: nothing was queued" if dry_run else
                    f"nothing was queued: {len(refused)} row(s) refused; fix them, or pass partial to queue the rest")
            return Receipt(None, source.name, dry_run, [result(r) for r in rows], note)

        batch_id = uuid.uuid4().hex[:12]
        results = []
        for row in rows:
            ids = [] if row.problems else self.sink.write(row.spec, ctx, batch_id=batch_id, by=by)
            results.append(result(row, ids))
        receipt = Receipt(batch_id, source.name, False, results)
        ctx.conn.execute(
            """INSERT INTO batches (id, channel_id, source, created_by, created_at, rows, accepted, refused, ref)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (batch_id, ctx.channel.id, source.name, by, db.now(), len(results), receipt.accepted,
             receipt.refused, ref))
        ctx.conn.commit()
        logs.event("batch.queued", channel=ctx.channel.id, batch=batch_id, source=source.name, by=by,
                   accepted=receipt.accepted, refused=receipt.refused,
                   tasks=sum(len(r.task_ids) for r in results))
        return receipt
