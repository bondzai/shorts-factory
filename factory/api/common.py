"""What every router shares: the one background job, and how a row is read.

Kept small on purpose. A helper that only one screen needs belongs in that
screen's router; this is for the things two of them would otherwise copy.
"""

from __future__ import annotations

import json
import threading
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from fastapi import HTTPException
from pydantic import BaseModel

from .. import channels, db, settings
import re
import unicodedata

STATIC = Path(__file__).resolve().parent.parent / "static"



class Job:
    """One background task at a time, with a log the page can poll.

    Deliberately not a queue: two builds at once would fight over the same clip
    rows. The channel is part of the job so the page can tell you that the thing
    blocking you is a build on another channel.
    """

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.name: str | None = None
        self.channel_id: str | None = None
        self.log: list[str] = []
        self.finished_at: str | None = None

    @property
    def running(self) -> bool:
        return self.name is not None

    def start(
        self, name: str, channel_id: str, work: Callable[[Callable[[str], None]], float]
    ) -> None:
        with self.lock:
            if self.running:
                raise HTTPException(
                    409, f"{self.name} is already running on {self.channel_id}"
                )
            self.name = name
            self.channel_id = channel_id
            self.log = []
            self.finished_at = None

        def emit(line: str) -> None:
            stamp = datetime.now(timezone.utc).strftime("%H:%M:%S")
            self.log.append(f"{stamp}  {line}")

        def run() -> None:
            with db.connect() as conn:
                run_id = db.start_run(conn, channel_id, name)
            status, cost = "ok", 0.0
            try:
                cost = work(emit) or 0.0
            except Exception as exc:
                status = "failed"
                emit(f"failed: {exc}")
                emit(traceback.format_exc().strip().splitlines()[-1])
            finally:
                with db.connect() as conn:
                    db.finish_run(
                        conn, run_id, status=status,
                        detail=self.log[-1] if self.log else "",
                        log="\n".join(self.log[-60:]), cost_usd=cost,
                    )
                with self.lock:
                    self.name = None
                    self.channel_id = None
                    self.finished_at = db.now()

        threading.Thread(target=run, daemon=True).start()

    def state(self) -> dict[str, Any]:
        return {
            "running": self.running,
            "name": self.name,
            "channel_id": self.channel_id,
            "log": self.log[-60:],
            "finished_at": self.finished_at,
        }


JOB = Job()


def resolve(conn, channel_id: str | None):
    try:
        return channels.resolve(conn, channel_id)
    except (KeyError, ValueError) as exc:
        raise HTTPException(404, str(exc)) from None


def facts_for_page(facts: dict[str, Any]) -> dict[str, Any]:
    if "stage" not in facts and "course" in facts:  # clips rendered before the rename
        facts = {**facts, "stage": facts["course"]}
    return {k: v for k, v in facts.items() if k in ("stage", "theme", "backdrop", "margin_s", "winner")}


def clip_json(row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "channel_id": row["channel_id"],
        "generator": row["generator"],
        "variant": row["variant"],
        "seed": row["seed"],
        "status": row["status"],
        "hook": row["hook"],
        "why": row["plan_why"],
        "title": row["title"],
        "description": row["description"],
        "hashtags": json.loads(row["hashtags_json"] or "[]"),
        "render_desc": row["render_desc"],
        "duration_s": row["duration_s"],
        "loudness_lufs": row["loudness_lufs"],
        "sameness": row["sameness"],
        "cost_usd": row["cost_usd"],
        "qc": json.loads(row["qc_json"] or "null"),
        "reject_reason": row["reject_reason"],
        "has_video": bool(row["video_path"]),
        "hook_text": row["hook_text"],
        "comment_prompt": row["comment_prompt"],
        "title_history": json.loads(row["title_history_json"] or "[]"),
        "published_at": row["published_at"],
        "facts": facts_for_page(json.loads(row["facts_json"] or "{}")),
    }


class IdsBody(BaseModel):
    ids: list[str]


def download_name(row) -> str:
    """The title as a filename: letters and digits kept (any script), runs
    of anything else become one hyphen, trimmed to a length a file dialog
    shows in full. Combining marks are kept with their letters — \\w alone
    drops Thai vowels and tone marks, and "เลือก" came out "เล-อก"."""

    title = (row["title"] or "").strip()
    if title:
        keep = lambda ch: ch.isalnum() or ch == "_" or unicodedata.category(ch).startswith("M")
        slug = "".join(ch if keep(ch) else "-" for ch in title).strip("-")
        slug = re.sub(r"-{2,}", "-", slug)[:80].rstrip("-")
        if slug:
            return f"{slug}.mp4"
    return f"{row['variant']}-{row['seed']}-{row['id'][:6]}.mp4"


class ChannelOnly(BaseModel):
    channel: str | None = None
