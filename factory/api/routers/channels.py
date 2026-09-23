"""Channels, and the snapshot every screen polls."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ... import channels, db
from ... import llm
from ...models import APPROVED, AWAITING_APPROVAL, PLANNED, PUBLISHED
from ..common import JOB
from ..common import clip_json
from ..common import resolve

router = APIRouter()

@router.get("/api/channels")
def list_channels() -> dict[str, Any]:
    with db.connect() as conn:
        out = []
        for channel in channels.all_channels(conn):
            counts = db.status_counts(conn, channel.id)
            out.append(
                {
                    **channel.as_dict(),
                    "counts": counts,
                    "spend_usd": db.spend(conn, channel.id),
                    "queue": counts.get(AWAITING_APPROVAL, 0),
                }
            )
    return {"channels": out}


class ChannelBody(BaseModel):
    name: str
    id: str | None = None
    handle: str | None = None
    platform: str = "youtube"
    driver: str | None = None
    variants: list[str] = []
    cadence: int = 1


@router.post("/api/channels")
def create_channel(body: ChannelBody) -> dict[str, Any]:
    with db.connect() as conn:
        try:
            channel = channels.create(
                conn,
                name=body.name,
                channel_id=body.id,
                handle=body.handle,
                platform=body.platform,
                driver=body.driver,
                variants=body.variants,
                cadence=body.cadence,
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from None
    return channel.as_dict()


class ChannelEdit(BaseModel):
    name: str | None = None
    handle: str | None = None
    driver: str | None = None
    variants: list[str] | None = None
    cadence: int | None = None
    active: bool | None = None


@router.patch("/api/channels/{channel_id}")
def edit_channel(channel_id: str, body: ChannelEdit) -> dict[str, Any]:
    fields = {k: v for k, v in body.model_dump().items() if v is not None}
    if "active" in fields:
        fields["active"] = int(fields["active"])
    with db.connect() as conn:
        try:
            channel = channels.edit(conn, channel_id, **fields)
        except (KeyError, ValueError) as exc:
            raise HTTPException(400, str(exc)) from None
    return channel.as_dict()


@router.get("/api/state")
def state(channel: str | None = None) -> dict[str, Any]:
    with db.connect() as conn:
        ch = resolve(conn, channel)
        counts = db.status_counts(conn, ch.id)
        return {
            "channel": ch.as_dict(),
            "counts": counts,
            "queue": [clip_json(r) for r in db.by_status(conn, ch.id, AWAITING_APPROVAL)],
            "approved": [clip_json(r) for r in db.by_status(conn, ch.id, APPROVED)],
            "planned": counts.get(PLANNED, 0),
            "recent": [clip_json(r) for r in db.recent(conn, ch.id, 12)],
            "runs": [dict(r) for r in db.recent_runs(conn, ch.id, 8)],
            "spend_usd": db.spend(conn, ch.id),
            "spend_total_usd": db.spend(conn),
            "job": JOB.state(),
            # Two brains can drive this factory: the built-in agents (need a
            # key) or an external one over MCP (needs nothing). The page
            # shows the buttons for whichever can actually do something.
            "agents": {"available": llm.has_credentials()},
            "tasks": db.task_counts(conn, ch.id),
        }
