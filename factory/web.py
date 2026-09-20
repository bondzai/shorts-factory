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
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import analytics, channels, db, generators, llm, logs, pipeline, playbooks, settings
from .agents import analyst
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
        "hook_text": row["hook_text"],
        "comment_prompt": row["comment_prompt"],
        "title_history": json.loads(row["title_history_json"] or "[]"),
        "published_at": row["published_at"],
    }


app.mount("/static", StaticFiles(directory=STATIC), name="static")


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
            # Two brains can drive this factory: the built-in agents (need a
            # key) or an external one over MCP (needs nothing). The page
            # shows the buttons for whichever can actually do something.
            "agents": {"available": llm.has_credentials()},
        }


@app.get("/api/playbooks")
def list_playbooks() -> dict[str, Any]:
    return {"playbooks": playbooks.available()}


@app.get("/api/playbook/{name}")
def get_playbook(name: str, channel: str | None = None) -> dict[str, Any]:
    with db.connect() as conn:
        ch = _resolve(conn, channel)
    try:
        return {"name": name, "channel": ch.id, "text": playbooks.render(name, ch.id)}
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from None


@app.get("/api/clips")
def clips(
    channel: str | None = None,
    status: str | None = None,
    generator: str | None = None,
    variant: str | None = None,
    q: str | None = None,
) -> dict[str, Any]:
    with db.connect() as conn:
        ch = _resolve(conn, channel)
        rows = db.search_clips(
            conn, ch.id, status=status, generator=generator, variant=variant, query=q
        )
        counts = db.status_counts(conn, ch.id)
    return {
        "clips": [
            {
                **_clip_json(row),
                "created_at": row["created_at"],
                "published_at": row["published_at"],
                "views": row["views"],
                "avg_view_pct": row["avg_view_pct"],
                "swipe_away_pct": row["swipe_away_pct"],
            }
            for row in rows
        ],
        "counts": counts,
        # The filter chips are built from this, so a new generator module
        # appears in the UI without the page knowing its name.
        "modules": generators.available(ch.variants),
        "statuses": sorted(counts),
    }


@app.get("/api/analytics")
def analytics_summary(channel: str | None = None) -> dict[str, Any]:
    with db.connect() as conn:
        ch = _resolve(conn, channel)
        return analytics.summary(conn, ch.id)


@app.get("/api/runs")
def runs(channel: str | None = None, limit: int = 30) -> dict[str, Any]:
    with db.connect() as conn:
        ch = _resolve(conn, channel)
        return {"runs": [dict(r) for r in db.recent_runs(conn, ch.id, limit)]}


@app.get("/api/logs")
def read_logs(
    channel: str | None = None,
    level: str | None = None,
    event: str | None = None,
    limit: int = 120,
) -> dict[str, Any]:
    with db.connect() as conn:
        ch = _resolve(conn, channel)
    return {
        "events": logs.read(limit=limit, channel=ch.id, level=level, event_name=event)
    }


@app.get("/api/rules")
def get_rules(channel: str | None = None) -> dict[str, Any]:
    with db.connect() as conn:
        ch = _resolve(conn, channel)
        latest = db.latest_digest(conn, ch.id)
        text = ch.rules()
    proposals = json.loads(latest["proposals_json"]) if latest else []
    return {
        "channel_id": ch.id,
        # Relative to the repo: the absolute path is long, machine-specific and
        # tells the reader nothing they need.
        "path": str(ch.rules_path.relative_to(settings.ROOT)),
        "text": text,
        "proposals": [p for p in proposals if p not in text],
        "digest": (
            {
                "created_at": latest["created_at"],
                "n_published": latest["n_published"],
                "body": latest["body"],
            }
            if latest
            else None
        ),
    }


class RulesBody(BaseModel):
    channel: str | None = None
    text: str


@app.put("/api/rules")
def put_rules(body: RulesBody) -> dict[str, Any]:
    with db.connect() as conn:
        ch = _resolve(conn, body.channel)
        ch.rules()  # make sure the file exists before overwriting it
        ch.rules_path.write_text(body.text)
    return {"path": str(ch.rules_path), "bytes": len(body.text)}


class AcceptBody(BaseModel):
    channel: str | None = None
    rules: list[str]


@app.post("/api/rules/accept")
def accept_rules(body: AcceptBody) -> dict[str, Any]:
    """Append chosen proposals to this channel's rules, one at a time."""
    with db.connect() as conn:
        ch = _resolve(conn, body.channel)
        ch.rules()
        try:
            applied = analyst.apply_rules(body.rules, ch.rules_path)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from None
    return {"applied": applied, "text": ch.rules_path.read_text()}


@app.get("/api/clip/{clip_id}/video")
def video(clip_id: str, download: bool = False) -> FileResponse:
    with db.connect() as conn:
        row = db.get(conn, clip_id)
    if row is None or not row["video_path"]:
        raise HTTPException(404, "no video for that clip")
    path = Path(row["video_path"])
    if not path.exists():
        raise HTTPException(410, f"file is gone: {path}")
    if download:
        # A name you can find in the upload dialog, not clip.mp4 twelve times.
        return FileResponse(
            path, media_type="video/mp4",
            filename=f"{row['variant']}-{row['seed']}-{clip_id[:6]}.mp4",
        )
    return FileResponse(path, media_type="video/mp4")


@app.post("/api/clip/{clip_id}/publish")
def publish_clip(clip_id: str) -> dict[str, str]:
    """The "I uploaded it" button on a manual channel."""
    with db.connect() as conn:
        try:
            outcome = pipeline.publish_one(conn, clip_id)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from None
    if outcome.status != PUBLISHED:
        raise HTTPException(500, outcome.detail)
    return {"status": outcome.status, "detail": outcome.detail}


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


@app.post("/api/clip/{clip_id}/restore")
def restore(clip_id: str) -> dict[str, str]:
    with db.connect() as conn:
        try:
            pipeline.restore(conn, clip_id)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from None
    return {"status": AWAITING_APPROVAL}


class TextBody(BaseModel):
    title: str | None = None
    comment_prompt: str | None = None
    why: str = ""


@app.patch("/api/clip/{clip_id}/text")
def edit_text(clip_id: str, body: TextBody) -> dict[str, Any]:
    out: dict[str, Any] = {"clip": clip_id}
    with db.connect() as conn:
        try:
            if body.title is not None:
                out = pipeline.retitle(conn, clip_id, body.title, by="human", why=body.why)
            if body.comment_prompt is not None:
                if db.get(conn, clip_id) is None:
                    raise ValueError(f"no clip {clip_id}")
                db.update(conn, clip_id, comment_prompt=body.comment_prompt.strip() or None)
                out["comment_prompt"] = body.comment_prompt.strip() or None
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from None
    return out


class HookBody(BaseModel):
    text: str


@app.post("/api/clip/{clip_id}/hook")
def rehook(clip_id: str, body: HookBody) -> dict[str, Any]:
    """A minute of ffmpeg, so it runs as a job like build does."""
    with db.connect() as conn:
        row = db.get(conn, clip_id)
        if row is None:
            raise HTTPException(404, f"no clip {clip_id}")
        ch = _resolve(conn, row["channel_id"])

    def work(emit) -> float:
        with db.connect() as conn:
            emit(f"{clip_id}  re-rendering with caption {body.text.strip()!r}")
            outcome = pipeline.rehook(conn, clip_id, body.text)
            emit(f"{clip_id}  {outcome.status}: {outcome.detail}")
        return 0.0

    JOB.start("rehook", ch.id, work)
    return JOB.state()


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
