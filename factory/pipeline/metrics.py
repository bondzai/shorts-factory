"""Stage 7: what the clips earned, and what to do differently.

The numbers come back either from the platform or from a human reading
Studio, and the digest is the only place they turn back into rules.
"""

from __future__ import annotations

import sqlite3

from .. import db
from .. import publish as drivers
from ..agents import analyst
from ..channels import Channel
from ..models import PUBLISHED
from .common import StageOutcome, resolve


def pull_metrics(
    conn: sqlite3.Connection, channel: Channel | str | None
) -> list[StageOutcome]:
    ch = resolve(conn, channel)
    driver = drivers.get(ch.driver, ch)
    results = []
    for row in db.by_status(conn, ch.id, PUBLISHED, limit=500):
        if not row["remote_id"]:
            continue
        try:
            metrics = driver.fetch_metrics(row["remote_id"])
            db.update(
                conn,
                row["id"],
                views=metrics.views,
                likes=metrics.likes,
                avg_view_pct=metrics.avg_view_pct,
                swipe_away_pct=metrics.swipe_away_pct,
                metrics_at=db.now(),
            )
            results.append(StageOutcome(row["id"], PUBLISHED, f"views={metrics.views}"))
        except Exception as exc:
            results.append(StageOutcome(row["id"], PUBLISHED, f"metrics failed: {exc}"))
    return results


def set_metrics(
    conn: sqlite3.Connection,
    clip_id: str,
    *,
    views: int,
    avg_view_pct: float,
    swipe_away_pct: float,
    likes: int = 0,
) -> None:
    """For the manual driver: type in what YouTube Studio shows you."""
    if db.get(conn, clip_id) is None:
        raise ValueError(f"no clip {clip_id}")
    db.update(
        conn,
        clip_id,
        views=views,
        likes=likes,
        avg_view_pct=avg_view_pct,
        swipe_away_pct=swipe_away_pct,
        metrics_at=db.now(),
    )


def digest(
    conn: sqlite3.Connection, channel: Channel | str | None, *, apply_rules: bool
) -> tuple[str, float, int]:
    ch = resolve(conn, channel)
    rows = db.published_with_metrics(conn, ch.id)
    if not rows:
        return (f"No published clip on {ch.name} has metrics yet.", 0.0, 0)
    result, cost, allowed = analyst.digest(rows)
    body = analyst.render_digest(result, len(rows), allowed)
    applied = 0
    if apply_rules and result.proposed_rules:
        ch.rules()  # make sure the file exists before appending to it
        applied = analyst.apply_rules(result.proposed_rules, ch.rules_path)
    db.record_digest(
        conn,
        channel_id=ch.id,
        n_published=len(rows),
        body=body,
        rules_applied=bool(applied),
        # Kept whether or not they were applied, so the Rules screen can offer
        # them one at a time instead of forcing all-or-nothing.
        proposals=result.proposed_rules,
    )
    return body, cost, applied
