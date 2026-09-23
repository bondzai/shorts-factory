"""The team overview, and where notifications go."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from ... import db
from ... import notify
from ... import settings
from ... import team

router = APIRouter()

@router.get("/api/team")
def team_overview() -> dict[str, Any]:
    """Every agent, what it holds, what it did today, across all channels."""
    with db.connect() as conn:
        return team.overview(conn)


@router.get("/api/notify")
def notify_view() -> dict[str, Any]:
    cfg = settings.load().raw.get("notify", {})
    return {"sinks": notify.sinks(), "daily_at": cfg.get("daily_at") or "", "on": cfg.get("on") or []}


@router.post("/api/notify/test")
def notify_test() -> dict[str, Any]:
    if not notify.sinks():
        raise HTTPException(400, "nothing is configured: FACTORY_WEBHOOK_URL or FACTORY_TELEGRAM_TOKEN in .env")
    sent = notify.post("notify.test", "[test] shorts-factory can reach this endpoint", channel="test", kind="test", status="ok")
    return {"sent": sent, "sinks": notify.sinks()}
