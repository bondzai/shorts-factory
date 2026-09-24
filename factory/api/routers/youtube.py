"""Connecting a channel to YouTube, and what the console shows about it."""

from __future__ import annotations

from typing import Any
import threading

from fastapi import APIRouter
from pydantic import BaseModel

from ... import db, logs
from ... import schedule
from ...publish.youtube import YouTubePublisher
from ..common import resolve

router = APIRouter()

class YouTubeBody(BaseModel):
    channel: str | None = None


def _youtube_view(ch) -> dict[str, Any]:

    driver = YouTubePublisher(ch)
    out = driver.status()
    out["driver"] = ch.driver
    out["slot"] = schedule.describe(schedule.next_slot())
    return out


@router.get("/api/youtube")
def youtube_status(channel: str | None = None) -> dict[str, Any]:
    with db.connect() as conn:
        ch = resolve(conn, channel)
    return _youtube_view(ch)


@router.post("/api/youtube/connect")
def youtube_connect(body: YouTubeBody) -> dict[str, Any]:
    """Start Google's consent flow. It opens a browser on the machine running
    the server and waits for the person there — so this returns at once and
    the page polls the status."""

    with db.connect() as conn:
        ch = resolve(conn, body.channel)
    driver = YouTubePublisher(ch)
    if driver.connected():
        return {"already": True, **_youtube_view(ch)}

    def work() -> None:
        try:
            driver.connect()
        except Exception as exc:
            logs.event("youtube.connect_failed", level="error", channel=ch.id, error=str(exc)[:300])

    threading.Thread(target=work, name=f"youtube-connect-{ch.id}", daemon=True).start()
    return {"started": True, "note": "a browser is opening on the machine running the server; "
                                     "sign in as this channel's YouTube account"}


@router.post("/api/youtube/disconnect")
def youtube_disconnect(body: YouTubeBody) -> dict[str, Any]:

    with db.connect() as conn:
        ch = resolve(conn, body.channel)
    YouTubePublisher(ch).disconnect()
    return _youtube_view(ch)
