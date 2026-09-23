"""The task queue: what is waiting, claimed, done or failed."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ... import db, logs
from ... import tasks
from ..common import ChannelOnly
from ..common import JOB
from ..common import resolve

router = APIRouter()

@router.get("/api/tasks")
def list_tasks(
    channel: str | None = None, status: str | None = None, kind: str | None = None, q: str | None = None,
    sort: str | None = None, dir: str | None = None, page: int = 1, page_size: int = 25,
) -> dict[str, Any]:
    with db.connect() as conn:
        ch = resolve(conn, channel)
        rows, total = db.tasks(conn, ch.id, status, kind=kind, query=q, sort=sort, direction=dir,
                               page=page, page_size=page_size)
        counts = db.task_counts(conn, ch.id)
    items = [tasks.as_dict(r) for r in rows]
    p, size = db.page_args(page, page_size)
    return {
        "items": items, "total": total, "page": p, "page_size": size,
        "tasks": items,
        "counts": counts,
        "kinds": {k: {"meaning": v["meaning"], "params": v["params"], "builtin": v["builtin"]} for k, v in tasks.KINDS.items()},
    }


class TaskBody(BaseModel):
    channel: str | None = None
    kind: str
    params: dict[str, Any] = {}
    count: int = 1
    priority: int = 0


@router.post("/api/tasks")
def add_tasks(body: TaskBody) -> dict[str, Any]:
    with db.connect() as conn:
        ch = resolve(conn, body.channel)
        try:
            ids = tasks.enqueue(conn, ch.id, body.kind, body.params, count=body.count, priority=body.priority)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from None
    return {"ids": ids}


@router.delete("/api/tasks/{task_id}")
def cancel_task(task_id: int) -> dict[str, str]:
    with db.connect() as conn:
        try:
            db.cancel_task(conn, task_id)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from None
    return {"status": "cancelled"}


class TaskIdsBody(BaseModel):
    ids: list[int]


@router.post("/api/tasks/delete")
def delete_tasks(body: TaskIdsBody) -> dict[str, Any]:
    with db.connect() as conn:
        removed = db.delete_tasks(conn, body.ids)
    logs.event("task.deleted", ids=removed, by="human")
    return {"deleted": removed}


@router.post("/api/tasks/cancel")
def cancel_tasks(body: TaskIdsBody) -> dict[str, Any]:
    cancelled = []
    with db.connect() as conn:
        for task_id in body.ids:
            try:
                db.cancel_task(conn, task_id); cancelled.append(task_id)
            except ValueError:
                continue
    return {"cancelled": cancelled}


class TaskClearBody(BaseModel):
    channel: str | None = None


@router.post("/api/tasks/clear")
def clear_tasks(body: TaskClearBody) -> dict[str, Any]:
    with db.connect() as conn:
        ch = resolve(conn, body.channel)
        n = db.clear_finished_tasks(conn, ch.id)
    logs.event("task.cleared", channel=ch.id, count=n, by="human")
    return {"cleared": n}


@router.post("/api/tasks/work")
def work_tasks(body: ChannelOnly) -> dict[str, Any]:
    """Run the queue with the built-in agents, as a job."""
    with db.connect() as conn:
        ch = resolve(conn, body.channel)

    def run(emit) -> float:
        with db.connect() as conn:
            emit(f"{ch.name}: working the queue with the built-in agents")
            try:
                done = tasks.work(conn, channel_id=ch.id)
            except ValueError as exc:
                emit(str(exc)); return 0.0
            for t in done:
                emit(f"task #{t['id']} {t['kind']}: {t['status']} {t.get('error') or (t.get('result') or {}).get('detail', '')}")
            emit(f"{len(done)} task(s) done")
            return sum((t.get("result") or {}).get("cost_usd", 0.0) for t in done)

    JOB.start("work", ch.id, run)
    return JOB.state()
