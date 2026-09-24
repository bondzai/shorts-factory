"""What ran and what happened: runs, the event log, the numbers."""

from __future__ import annotations

from typing import Any
import json

from fastapi import APIRouter

from ... import analytics
from ... import db, logs
from ..common import resolve

router = APIRouter()

@router.get("/api/analytics")
def analytics_summary(channel: str | None = None) -> dict[str, Any]:
    with db.connect() as conn:
        ch = resolve(conn, channel)
        return analytics.summary(conn, ch.id)


@router.get("/api/runs")
def runs(channel: str | None = None, status: str | None = None, kind: str | None = None,
         sort: str | None = None, dir: str | None = None, page: int = 1, page_size: int = 25) -> dict[str, Any]:
    with db.connect() as conn:
        ch = resolve(conn, channel)
        rows, total = db.runs_page(conn, ch.id, status=status, kind=kind, sort=sort, direction=dir,
                                   page=page, page_size=page_size)
    items = [dict(r) for r in rows]
    p, size = db.page_args(page, page_size)
    return {"items": items, "total": total, "page": p, "page_size": size, "runs": items}


@router.get("/api/logs")
def read_logs(
    channel: str | None = None,
    level: str | None = None,
    event: str | None = None,
    q: str | None = None,
    limit: int = 120,
    page: int = 1,
    page_size: int = 25,
) -> dict[str, Any]:
    """The event log is files, not SQL: read a generous window, filter, then page."""
    with db.connect() as conn:
        ch = resolve(conn, channel)
    events = logs.read(limit=max(limit, page * page_size, 2000), channel=ch.id, level=level, event_name=event)
    if q:
        needle = q.lower()
        events = [e for e in events if needle in json.dumps(e, default=str).lower()]
    p, size = db.page_args(page, page_size)
    items = events[(p - 1) * size : p * size]
    return {"items": items, "total": len(events), "page": p, "page_size": size, "events": events[:limit]}
