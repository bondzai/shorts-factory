"""Stage 1: what to make next, from the channel's rules and its recent clips."""

from __future__ import annotations

import sqlite3

from .. import db, logs
from ..agents import idea
from ..channels import Channel
from .common import resolve


def plan(
    conn: sqlite3.Connection, channel: Channel | str | None, count: int
) -> tuple[list[str], float]:
    ch = resolve(conn, channel)
    recent = db.recent(conn, ch.id, limit=12)
    used = {row["seed"] for row in conn.execute("SELECT seed FROM clips").fetchall()}
    plans, cost = idea.propose(
        count=count,
        rules=ch.rules(),
        recent=recent,
        used_seeds=used,
        channel_name=ch.name,
        allowed=ch.variants,
    )
    ids = []
    for item in plans:
        ids.append(
            db.insert_clip(
                conn,
                channel_id=ch.id,
                generator=item.generator,
                variant=item.variant,
                seed=item.seed,
                params=item.params,
                hook=item.hook,
                plan_why=item.why,
            )
        )
    if ids:
        db.add_cost(conn, ids[0], cost)  # one call covered the whole batch
    for clip_id, item in zip(ids, plans):
        logs.event(
            "clip.planned", channel=ch.id, clip=clip_id,
            generator=item.generator, variant=item.variant, seed=item.seed,
            hook=item.hook,
        )
    return ids, cost
