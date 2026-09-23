"""The buttons that start a background job: plan, build, publish, digest."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from ... import db
from ... import pipeline
from ...models import APPROVED, AWAITING_APPROVAL, PLANNED, PUBLISHED
from ..common import ChannelOnly
from ..common import JOB
from ..common import resolve

router = APIRouter()

class PlanBody(BaseModel):
    channel: str | None = None
    count: int = 3


@router.post("/api/plan")
def plan(body: PlanBody) -> dict[str, Any]:
    with db.connect() as conn:
        ch = resolve(conn, body.channel)

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


@router.post("/api/build")
def build(body: ChannelOnly) -> dict[str, Any]:
    with db.connect() as conn:
        ch = resolve(conn, body.channel)

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


@router.post("/api/publish")
def publish(body: ChannelOnly) -> dict[str, Any]:
    with db.connect() as conn:
        ch = resolve(conn, body.channel)

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


@router.post("/api/digest")
def digest(body: ChannelOnly) -> dict[str, Any]:
    with db.connect() as conn:
        ch = resolve(conn, body.channel)

    def work(emit) -> float:
        with db.connect() as conn:
            text, cost, _ = pipeline.digest(conn, ch, apply_rules=False)
        for line in text.splitlines():
            emit(line)
        emit(f"${cost:.4f}")
        return cost

    JOB.start("digest", ch.id, work)
    return JOB.state()
