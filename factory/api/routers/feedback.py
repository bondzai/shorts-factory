"""Lessons from the numbers: list, read, write, and the evidence preview.

Every write goes through factory/feedback.py, the same service the CLI and
the MCP tools use; a ValueError there is a 400 here with its own words.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ... import db, logs
from ... import feedback as service
from ..common import resolve

router = APIRouter()


class LessonBody(BaseModel):
    channel: str | None = None
    observation: str | None = None
    area: str | None = None
    evidence: str | None = None
    clip_ids: list[str] | None = None
    action: str | None = None
    status: str | None = None
    result: str | None = None
    source: str | None = None


def _bad(exc: ValueError) -> HTTPException:
    return HTTPException(400, str(exc))


@router.get("/api/feedback")
def list_feedback(
    channel: str | None = None, status: str | None = None, area: str | None = None,
    clip: str | None = None, q: str | None = None, page: int = 1, page_size: int = 25,
) -> dict[str, Any]:
    with db.connect() as conn:
        ch = resolve(conn, channel)
        try:
            items, total = service.list_(conn, ch.id, status=status, area=area, clip=clip, query=q,
                                         page=page, page_size=page_size)
        except ValueError as exc:
            raise _bad(exc) from None
        p, size = db.page_args(page, page_size)
        return {"items": items, "total": total, "page": p, "page_size": size,
                "counts": service.counts(conn, ch.id),
                "areas": list(service.AREAS), "statuses": list(service.STATUSES)}


# Declared before /{feedback_id} so "evidence" is not read as an id.
@router.get("/api/feedback/evidence")
def evidence(clips: str = "") -> dict[str, Any]:
    ids = [c for c in clips.replace(" ", ",").split(",") if c]
    with db.connect() as conn:
        missing = [c for c in ids if db.get(conn, c) is None]
        if missing:
            raise HTTPException(400, f"no clip {', '.join(missing)}")
        return {"clips": service.snapshot(conn, ids)}


@router.get("/api/feedback/{feedback_id}")
def get_feedback(feedback_id: int) -> dict[str, Any]:
    with db.connect() as conn:
        found = service.get(conn, feedback_id)
    if found is None:
        raise HTTPException(404, f"no lesson {feedback_id}")
    return found


@router.post("/api/feedback")
def create_feedback(body: LessonBody) -> dict[str, Any]:
    fields = body.model_dump(exclude_none=True, exclude={"channel"})
    with db.connect() as conn:
        ch = resolve(conn, body.channel)
        try:
            out = service.create(conn, ch.id, created_by="operator",
                                 **{"source": "manual", "observation": "", **fields})
        except ValueError as exc:
            raise _bad(exc) from None
    logs.event("feedback.created", channel=ch.id, id=out["id"], area=out["area"], status=out["status"])
    return out


@router.patch("/api/feedback/{feedback_id}")
def update_feedback(feedback_id: int, body: LessonBody) -> dict[str, Any]:
    fields = body.model_dump(exclude_none=True, exclude={"channel"})
    with db.connect() as conn:
        if service.get(conn, feedback_id) is None:
            raise HTTPException(404, f"no lesson {feedback_id}")
        try:
            out = service.update(conn, feedback_id, **fields)
        except ValueError as exc:
            raise _bad(exc) from None
    logs.event("feedback.updated", channel=out["channel_id"], id=feedback_id, fields=sorted(fields),
               status=out["status"])
    return out


@router.delete("/api/feedback/{feedback_id}")
def delete_feedback(feedback_id: int) -> dict[str, Any]:
    with db.connect() as conn:
        if not service.delete(conn, feedback_id):
            raise HTTPException(404, f"no lesson {feedback_id}")
    logs.event("feedback.deleted", id=feedback_id)
    return {"deleted": feedback_id}
