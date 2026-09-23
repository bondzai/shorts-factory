"""A clip's life after it is rendered: lists, the file, the text, the decisions."""

from __future__ import annotations

from typing import Any
import json

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from ... import db
from ... import generators
from ... import pipeline
from ... import schedule, settings
from ... import tasks
from ...generators import physics
from ...models import APPROVED, AWAITING_APPROVAL, PLANNED, PUBLISHED
from ..common import IdsBody
from ..common import JOB
from ..common import clip_json
from ..common import download_name
from ..common import resolve

router = APIRouter()

@router.post("/api/clips/bin")
def bin_clips(body: IdsBody) -> dict[str, Any]:
    with db.connect() as conn:
        try:
            return {"binned": pipeline.bin_clips(conn, body.ids)}
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from None


@router.post("/api/clips/unbin")
def unbin_clips(body: IdsBody) -> dict[str, Any]:
    with db.connect() as conn:
        try:
            return {"restored": pipeline.unbin_clips(conn, body.ids)}
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from None


@router.post("/api/clips/destroy")
def destroy_clips(body: IdsBody) -> dict[str, Any]:
    with db.connect() as conn:
        try:
            return {"destroyed": pipeline.destroy_clips(conn, body.ids)}
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from None


@router.get("/api/work")
def work(
    channel: str | None = None, phase: str | None = None, variant: str | None = None, q: str | None = None,
    sort: str | None = None, dir: str | None = None, page: int = 1, page_size: int = 25,
) -> dict[str, Any]:
    """Tasks and clips as one list. Each item says which it is (row_kind) and
    where it is (phase); a task item is tasks.as_dict, a clip item is the
    same shape /api/clips gives, so the page needs no third kind of row."""
    with db.connect() as conn:
        ch = resolve(conn, channel)
        rows, total, counts = db.work(conn, ch.id, phase=phase, variant=variant, query=q,
                                      sort=sort, direction=dir, page=page, page_size=page_size)
        items = []
        for w in rows:
            if w["row_kind"] == "task":
                t = db.get_task(conn, int(w["task_id"]))
                if t is None:
                    continue
                items.append({**tasks.as_dict(t), "row_kind": "task", "phase": w["phase"], "key": w["id"]})
            else:
                row = db.get(conn, w["clip_id"])
                if row is None:
                    continue
                items.append({
                    **clip_json(row), "row_kind": "clip", "phase": w["phase"], "key": w["id"],
                    "created_at": row["created_at"], "views": row["views"],
                    "avg_view_pct": row["avg_view_pct"], "swipe_away_pct": row["swipe_away_pct"],
                })
        binned = conn.execute(
            "SELECT COUNT(*) n FROM clips WHERE channel_id = ? AND deleted_at IS NOT NULL", (ch.id,)
        ).fetchone()["n"]
        modules = generators.available(ch.variants)
    p, size = db.page_args(page, page_size)
    return {
        "items": items, "total": total, "page": p, "page_size": size,
        "phases": [{"id": s, "count": counts.get(s, 0)} for s in db.PHASES if counts.get(s)],
        "modules": modules, "binned": binned,
        # Live stages first; a trial stage renders when named but is never
        # picked at random, and the form says so.
        "stages": [{"id": st.id, "blurb": st.blurb + ("" if st.live else " (trial — not yet through stage QA)"),
                    "live": st.live, "parts": [name for name, _ in st.parts]}
                   for st in sorted(physics.STAGE_SPECS, key=lambda st: not st.live)],
        "kinds": {k: {"meaning": v["meaning"], "params": v["params"], "builtin": v["builtin"]} for k, v in tasks.KINDS.items()},
    }


@router.get("/api/clips")
def clips(
    channel: str | None = None,
    status: str | None = None,
    generator: str | None = None,
    variant: str | None = None,
    q: str | None = None,
    bin: bool = False,
    sort: str | None = None,
    dir: str | None = None,
    page: int = 1,
    page_size: int = 25,
) -> dict[str, Any]:
    with db.connect() as conn:
        ch = resolve(conn, channel)
        rows, total = db.search_clips(
            conn, ch.id, status=status, generator=generator, variant=variant, query=q,
            binned=bin, sort=sort, direction=dir, page=page, page_size=page_size,
        )
        counts = db.status_counts(conn, ch.id)
        binned = conn.execute(
            "SELECT COUNT(*) n FROM clips WHERE channel_id = ? AND deleted_at IS NOT NULL", (ch.id,)
        ).fetchone()["n"]
    items = [
        {
            **clip_json(row),
            "created_at": row["created_at"],
            "published_at": row["published_at"],
            "views": row["views"],
            "avg_view_pct": row["avg_view_pct"],
            "swipe_away_pct": row["swipe_away_pct"],
            "deleted_at": row["deleted_at"],
        }
        for row in rows
    ]
    p, size = db.page_args(page, page_size)
    return {
        "items": items, "total": total, "page": p, "page_size": size,
        "clips": items,  # the previous name; the page reads `items`
        "counts": counts,
        "binned": binned,
        # The filter chips are built from this, so a new generator module
        # appears in the UI without the page knowing its name.
        "modules": generators.available(ch.variants),
        "statuses": sorted(counts),
    }


@router.get("/api/clip/{clip_id}")
def clip_detail(clip_id: str) -> dict[str, Any]:
    """Everything the page knows about one clip, for viewing without downloading."""
    with db.connect() as conn:
        row = db.get(conn, clip_id)
    if row is None:
        raise HTTPException(404, f"no clip {clip_id}")
    path = db.video_file(row)
    return {
        **clip_json(row),
        "facts": json.loads(row["facts_json"] or "{}"),
        "params": json.loads(row["params_json"] or "{}"),
        "created_at": row["created_at"],
        "published_at": row["published_at"],
        "deleted_at": row["deleted_at"],
        "purged_at": row["purged_at"],
        "views": row["views"],
        "avg_view_pct": row["avg_view_pct"],
        "swipe_away_pct": row["swipe_away_pct"],
        "likes": row["likes"],
        "metrics_at": row["metrics_at"],
        "file": {
            "path": str(path.relative_to(settings.ROOT)) if path and path.is_relative_to(settings.ROOT) else (str(path) if path else None),
            "exists": bool(path and path.exists()),
            "mb": round(path.stat().st_size / 1e6, 2) if path and path.exists() else None,
        },
    }


@router.get("/api/clip/{clip_id}/video")
def video(clip_id: str, download: bool = False) -> FileResponse:
    with db.connect() as conn:
        row = db.get(conn, clip_id)
    if row is None or not row["video_path"]:
        raise HTTPException(404, "no video for that clip")
    path = db.video_file(row)
    if not path.exists():
        raise HTTPException(410, f"file is gone: {path}")
    if download:
        # Named after the title, so the file you find in the upload dialog
        # is the one you meant. Before a title exists it falls back to the
        # variant and seed — never clip.mp4 twelve times.
        return FileResponse(path, media_type="video/mp4", filename=download_name(row))
    return FileResponse(path, media_type="video/mp4")


@router.post("/api/clip/{clip_id}/publish")
def publish_clip(clip_id: str) -> dict[str, str]:
    """"I uploaded it" on a manual channel; "Upload to YouTube" on a connected
    one — the same button, because both mean "this clip has left the building".
    Either way a person presses it: nothing here uploads on its own."""
    with db.connect() as conn:
        try:
            outcome = pipeline.publish_one(conn, clip_id)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from None
    if outcome.status != PUBLISHED:
        raise HTTPException(500, outcome.detail)
    return {"status": outcome.status, "detail": outcome.detail}


@router.post("/api/clip/{clip_id}/approve")
def approve(clip_id: str) -> dict[str, str]:
    with db.connect() as conn:
        try:
            pipeline.approve(conn, clip_id)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from None
    return {"status": APPROVED}


class RejectBody(BaseModel):
    reason: str = "not good enough"


@router.post("/api/clip/{clip_id}/restore")
def restore(clip_id: str) -> dict[str, str]:
    with db.connect() as conn:
        try:
            pipeline.restore(conn, clip_id)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from None
    return {"status": AWAITING_APPROVAL}


class TextBody(BaseModel):
    title: str | None = None
    description: str | None = None
    comment_prompt: str | None = None
    why: str = ""


@router.get("/api/clip/{clip_id}/upload_text")
def upload_text(clip_id: str) -> dict[str, Any]:
    """What to paste into the upload form, under headings, plus the next slot."""
    with db.connect() as conn:
        try:
            return schedule.upload_text(conn, clip_id)
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from None


@router.patch("/api/clip/{clip_id}/text")
def edit_text(clip_id: str, body: TextBody) -> dict[str, Any]:
    out: dict[str, Any] = {"clip": clip_id}
    with db.connect() as conn:
        try:
            if body.title is not None:
                out = pipeline.retitle(conn, clip_id, body.title, by="human", why=body.why)
            if body.description is not None:
                out["description"] = pipeline.redescribe(conn, clip_id, body.description, by="human")
            if body.comment_prompt is not None:
                if db.get(conn, clip_id) is None:
                    raise ValueError(f"no clip {clip_id}")
                db.update(conn, clip_id, comment_prompt=body.comment_prompt.strip() or None)
                out["comment_prompt"] = body.comment_prompt.strip() or None
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from None
    return out


class HookBody(BaseModel):
    text: str = ""
    background: str | None = None  # "" means back to the theme's palette


@router.post("/api/clip/{clip_id}/hook")
def rehook(clip_id: str, body: HookBody) -> dict[str, Any]:
    """A minute of ffmpeg, so it runs as a job like build does."""
    with db.connect() as conn:
        row = db.get(conn, clip_id)
        if row is None:
            raise HTTPException(404, f"no clip {clip_id}")
        ch = resolve(conn, row["channel_id"])

    text = body.text.strip() or (row["hook_text"] or None)

    def work(emit) -> float:
        with db.connect() as conn:
            emit(f"{clip_id}  re-rendering with caption {text!r}"
                 + (f" and backdrop {body.background or 'from the theme'}" if body.background is not None else ""))
            outcome = pipeline.rehook(conn, clip_id, text, background=body.background)
            emit(f"{clip_id}  {outcome.status}: {outcome.detail}")
        return 0.0

    JOB.start("rehook", ch.id, work)
    return JOB.state()


@router.post("/api/clip/{clip_id}/reject")
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


@router.post("/api/clip/{clip_id}/metrics")
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
