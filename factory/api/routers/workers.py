"""Workers: the console starting an agent on a channel's queue."""

from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ... import db, workers
from ..common import resolve

router = APIRouter()

class WorkerBody(BaseModel):
    channel: str | None = None
    agent: str = "claude"
    auto: bool = False


def _workers_view(channel_id: str) -> dict[str, Any]:
    return {
        "workers": workers.MANAGER.status(),
        "agents": sorted(workers.COMMANDS),
        "available": workers.available(),
        "in_container": bool(os.environ.get("FACTORY_ROOT")) and not any(workers.available().values()),
        "integration": workers.integration(channel_id),
    }


@router.get("/api/workers")
def get_workers(channel: str | None = None) -> dict[str, Any]:
    with db.connect() as conn:
        ch = resolve(conn, channel)
    return _workers_view(ch.id)


@router.post("/api/workers/start")
def start_worker(body: WorkerBody) -> dict[str, Any]:
    with db.connect() as conn:
        ch = resolve(conn, body.channel)
    try:
        worker = workers.MANAGER.start(ch.id, agent=body.agent, auto=body.auto)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None
    return {"worker": worker.as_dict(), **_workers_view(ch.id)}


@router.post("/api/workers/stop")
def stop_worker(body: WorkerBody) -> dict[str, Any]:
    with db.connect() as conn:
        ch = resolve(conn, body.channel)
    workers.MANAGER.stop(ch.id)
    return _workers_view(ch.id)


@router.get("/api/workers/{channel_id}/log")
def worker_log(channel_id: str, lines: int = 120) -> dict[str, Any]:
    return {"channel": channel_id, "lines": workers.MANAGER.log(channel_id, lines)}
