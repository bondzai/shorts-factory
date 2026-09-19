"""Aggregates for the Analytics screen.

Plain arithmetic over the clips table, deliberately kept out of the Analyst
agent: these are the numbers, not an opinion about them. Every group carries its
n, because with the sample sizes this channel will have for months, n is most of
the argument.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from statistics import median
from typing import Any

from . import db


def _median(values: list[float]) -> float | None:
    clean = [v for v in values if v is not None]
    return round(median(clean), 1) if clean else None


def _group(rows: list[sqlite3.Row], key) -> list[dict[str, Any]]:
    buckets: dict[Any, list[sqlite3.Row]] = {}
    for row in rows:
        value = key(row)
        if value is None:
            continue
        buckets.setdefault(value, []).append(row)
    out = []
    for value, group in buckets.items():
        views = [r["views"] for r in group if r["views"] is not None]
        out.append(
            {
                "key": value,
                "n": len(group),
                "views_median": _median([float(v) for v in views]),
                "views_total": sum(views) if views else 0,
                "retained_median": _median([r["avg_view_pct"] for r in group]),
                "swipe_away_median": _median([r["swipe_away_pct"] for r in group]),
            }
        )
    out.sort(key=lambda item: (item["retained_median"] is None, -(item["retained_median"] or 0)))
    return out


def _hook(row: sqlite3.Row) -> int | None:
    try:
        return json.loads(row["qc_json"] or "{}").get("hook_strength")
    except (json.JSONDecodeError, TypeError):
        return None


def summary(conn: sqlite3.Connection, channel_id: str) -> dict[str, Any]:
    rows = db.published_with_metrics(conn, channel_id)
    counts = db.status_counts(conn, channel_id)

    cutoff = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat(timespec="seconds")
    recent = [r for r in rows if (r["published_at"] or "") >= cutoff]
    views_90d = sum(r["views"] or 0 for r in recent)

    best = max(rows, key=lambda r: r["views"] or 0, default=None)

    return {
        "n_with_metrics": len(rows),
        "n_published": counts.get("published", 0),
        "views_90d": views_90d,
        # The gates that decide whether any of this turns into money. Shown as
        # progress rather than a target so the distance stays honest.
        "gate_tier1_pct": round(min(100.0, views_90d / 3_000_000 * 100), 2),
        "gate_tier2_pct": round(min(100.0, views_90d / 10_000_000 * 100), 2),
        "retained_median": _median([r["avg_view_pct"] for r in rows]),
        "swipe_away_median": _median([r["swipe_away_pct"] for r in rows]),
        "best": (
            {
                "id": best["id"],
                "title": best["title"],
                "views": best["views"],
                "variant": best["variant"],
            }
            if best and best["views"]
            else None
        ),
        "by_variant": _group(rows, lambda r: r["variant"]),
        "by_hook": _group(rows, _hook),
        "series": [
            {
                "id": r["id"],
                "title": r["title"],
                "views": r["views"] or 0,
                "retained": r["avg_view_pct"],
                "published_at": r["published_at"],
            }
            for r in rows
        ],
        # QC rejects weak hooks before they are ever published, so the low
        # buckets of by_hook are empty by construction. The grader never sees
        # its own failures; say so rather than let the column imply otherwise.
        "by_hook_caveat": (
            "Hook scores below the QC floor never reach publication, so those "
            "buckets are empty by construction, not by evidence."
        ),
    }
