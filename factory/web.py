"""Local web UI for the daily loop, across every channel.

The command line is fine for plan, build and publish, but not for the fifteen
minutes that matter: deciding. You cannot judge a hook by reading a row in a
table — you have to watch the first second. So the queue here is a stack of
clips that play, with approve and reject one keystroke away.

Every request names a channel. One page switches between them; nothing is
shared but the code.

Binds to 127.0.0.1 only. There is no authentication and none is wanted; this
reads your database and spends your API credit.
"""

from __future__ import annotations

import json
import threading
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel

from . import channels, db, pipeline, settings
from .models import APPROVED, AWAITING_APPROVAL, PLANNED, PUBLISHED

STATIC = Path(__file__).resolve().parent / "static"


class _Job:
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


JOB = _Job()
app = FastAPI(title="shorts-factory", docs_url=None, redoc_url=None)


def _resolve(conn, channel_id: str | None):
    try:
        return channels.resolve(conn, channel_id)
    except (KeyError, ValueError) as exc:
        raise HTTPException(404, str(exc)) from None


def _clip_json(row) -> dict[str, Any]:
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
    }


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return (STATIC / "index.html").read_text()


@app.get("/api/channels")
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


@app.post("/api/channels")
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


@app.patch("/api/channels/{channel_id}")
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


@app.get("/api/state")
def state(channel: str | None = None) -> dict[str, Any]:
    with db.connect() as conn:
        ch = _resolve(conn, channel)
        counts = db.status_counts(conn, ch.id)
        return {
            "channel": ch.as_dict(),
            "counts": counts,
            "queue": [_clip_json(r) for r in db.by_status(conn, ch.id, AWAITING_APPROVAL)],
            "approved": [_clip_json(r) for r in db.by_status(conn, ch.id, APPROVED)],
            "planned": counts.get(PLANNED, 0),
            "recent": [_clip_json(r) for r in db.recent(conn, ch.id, 12)],
            "runs": [dict(r) for r in db.recent_runs(conn, ch.id, 8)],
            "spend_usd": db.spend(conn, ch.id),
            "spend_total_usd": db.spend(conn),
            "job": JOB.state(),
        }


@app.get("/api/clip/{clip_id}/video")
def video(clip_id: str) -> FileResponse:
    with db.connect() as conn:
        row = db.get(conn, clip_id)
    if row is None or not row["video_path"]:
        raise HTTPException(404, "no video for that clip")
    path = Path(row["video_path"])
    if not path.exists():
        raise HTTPException(410, f"file is gone: {path}")
    return FileResponse(path, media_type="video/mp4")


class PlanBody(BaseModel):
    channel: str | None = None
    count: int = 3


@app.post("/api/plan")
def plan(body: PlanBody) -> dict[str, Any]:
    with db.connect() as conn:
        ch = _resolve(conn, body.channel)

    def work(emit) -> float:
        emit(f"{ch.name}: asking the Idea agent for {body.count} clip(s)")
        with db.connect() as conn:
            ids, cost = pipeline.plan(conn, ch, body.count)
            for clip_id in ids:
                row = db.get(conn, clip_id)
                emit(f"{clip_id}  {row['generator']}/{row['variant']}  {row['hook']}")
        emit(f"planned {len(ids)}, ${cost:.4f}")
        return cost

    JOB.start("plan", ch.id, work)
    return JOB.state()


class ChannelOnly(BaseModel):
    channel: str | None = None


@app.post("/api/build")
def build(body: ChannelOnly) -> dict[str, Any]:
    with db.connect() as conn:
        ch = _resolve(conn, body.channel)

    def work(emit) -> float:
        with db.connect() as conn:
            planned = db.by_status(conn, ch.id, PLANNED)
            if not planned:
                emit("nothing planned")
                return 0.0
            emit(f"{ch.name}: building {len(planned)} clip(s)")
            spend = 0.0
            for row in planned:
                emit(f"{row['id']}  rendering {row['generator']}/{row['variant']}...")
                outcome = pipeline.build(conn, row["id"])
                spend += outcome.cost_usd
                emit(f"{row['id']}  {outcome.status}: {outcome.detail}")
            emit(f"done, ${spend:.4f}")
            return spend

    JOB.start("build", ch.id, work)
    return JOB.state()


@app.post("/api/publish")
def publish(body: ChannelOnly) -> dict[str, Any]:
    with db.connect() as conn:
        ch = _resolve(conn, body.channel)

    def work(emit) -> float:
        with db.connect() as conn:
            outcomes = pipeline.publish_approved(conn, ch)
        if not outcomes:
            emit("nothing approved")
        for outcome in outcomes:
            emit(f"{outcome.clip_id}  {outcome.status}: {outcome.detail}")
        return 0.0

    JOB.start("publish", ch.id, work)
    return JOB.state()


@app.post("/api/digest")
def digest(body: ChannelOnly) -> dict[str, Any]:
    with db.connect() as conn:
        ch = _resolve(conn, body.channel)

    def work(emit) -> float:
        with db.connect() as conn:
            text, cost, _ = pipeline.digest(conn, ch, apply_rules=False)
        for line in text.splitlines():
            emit(line)
        emit(f"${cost:.4f}")
        return cost

    JOB.start("digest", ch.id, work)
    return JOB.state()


@app.post("/api/clip/{clip_id}/approve")
def approve(clip_id: str) -> dict[str, str]:
    with db.connect() as conn:
        try:
            pipeline.approve(conn, clip_id)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from None
    return {"status": APPROVED}


class RejectBody(BaseModel):
    reason: str = "not good enough"


@app.post("/api/clip/{clip_id}/reject")
def reject(clip_id: str, body: RejectBody) -> dict[str, str]:
    with db.connect() as conn:
        try:
            pipeline.reject(conn, clip_id, body.reason)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from None
    return {"status": "qc_rejected"}


class MetricsBody(BaseModel):
    views: int
    avg_view_pct: float
    swipe_away_pct: float
    likes: int = 0


@app.post("/api/clip/{clip_id}/metrics")
def metrics(clip_id: str, body: MetricsBody) -> dict[str, str]:
    with db.connect() as conn:
        try:
            pipeline.set_metrics(
                conn,
                clip_id,
                views=body.views,
                avg_view_pct=body.avg_view_pct,
                swipe_away_pct=body.swipe_away_pct,
                likes=body.likes,
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from None
    return {"status": PUBLISHED}


def serve(host: str = "127.0.0.1", port: int = 8765) -> None:
    import uvicorn

    settings.load().ensure_dirs()
    uvicorn.run(app, host=host, port=port, log_level="warning")
