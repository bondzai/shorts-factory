"""Stage 5: the human gate, and the ways back from it.

Approve, reject, and undo: a rejected clip can be restored, a stranded one
resumed, a binned one brought back. Only a clip already in the bin can be
destroyed, so nothing goes from a list to gone in one click.
"""

from __future__ import annotations

import shutil
import sqlite3

from .. import db, logs
from ..agents import qc
from ..channels import Channel
from ..models import (
    APPROVED,
    AWAITING_APPROVAL,
    DESCRIBED,
    FAILED,
    QC_REJECTED,
    RENDERED,
)
from .building import build
from .common import StageOutcome, resolve


def apply_qc(conn: sqlite3.Connection, clip_id: str, verdict) -> tuple[bool, str]:
    """Combine the caller's judgment with this machine's measurements."""
    row = db.get(conn, clip_id)
    if row is None:
        raise ValueError(f"no clip {clip_id}")
    if not row["title"]:
        raise ValueError(f"{clip_id} has no title yet; submit metadata first")
    info = {
        "width": row["width"], "height": row["height"],
        "fps": row["fps"], "duration_s": row["duration_s"],
    }
    failures = qc.hard_failures(
        probe=info, loudness_lufs=row["loudness_lufs"], sameness=row["sameness"] or 0.0
    )
    passed, reason = qc.decide(verdict, failures)
    db.update(
        conn, clip_id,
        status=AWAITING_APPROVAL if passed else QC_REJECTED,
        qc_json=verdict.model_dump_json(),
        reject_reason=None if passed else reason,
    )
    logs.event(
        "clip.qc", level="info" if passed else "warn", channel=row["channel_id"],
        clip=clip_id, passed=passed, hook_strength=verdict.hook_strength,
        policy_risk=verdict.policy_risk, looks_templated=verdict.looks_templated,
        hard_failures=failures, reason=reason or None, by="agent",
    )
    return passed, reason


STUCK = (RENDERED, DESCRIBED)


def stuck(conn: sqlite3.Connection, channel_id: str, *, include_failed: bool = False):
    """Clips that stopped between stages, oldest first."""
    statuses = list(STUCK) + ([FAILED] if include_failed else [])
    marks = ", ".join("?" for _ in statuses)
    return conn.execute(
        f"""SELECT * FROM clips WHERE channel_id = ? AND deleted_at IS NULL AND status IN ({marks})
            ORDER BY created_at""",
        (channel_id, *statuses),
    ).fetchall()


def resume(
    conn: sqlite3.Connection,
    channel: Channel | str | None,
    *,
    include_failed: bool = False,
    limit: int = 20,
) -> list[StageOutcome]:
    """Push stranded clips the rest of the way, reusing what is already on disk."""
    ch = resolve(conn, channel)
    rows = stuck(conn, ch.id, include_failed=include_failed)[:limit]
    out = []
    for row in rows:
        logs.event("clip.resumed", channel=ch.id, clip=row["id"], was=row["status"])
        out.append(build(conn, row["id"]))
    return out


def queue(conn: sqlite3.Connection, channel: Channel | str | None) -> list[sqlite3.Row]:
    ch = resolve(conn, channel)
    return db.by_status(conn, ch.id, AWAITING_APPROVAL)


def approve(conn: sqlite3.Connection, clip_id: str) -> None:
    row = db.get(conn, clip_id)
    if row is None or row["status"] != AWAITING_APPROVAL:
        raise ValueError(f"{clip_id} is not awaiting approval")
    db.update(conn, clip_id, status=APPROVED)
    logs.event("clip.approved", channel=row["channel_id"], clip=clip_id, title=row["title"])


def bin_clips(conn: sqlite3.Connection, clip_ids: list[str]) -> list[str]:
    """Hide clips without losing anything: files stay, rows stay, restorable.

    A binned clip leaves every list and count and stops being planned around.
    The one thing it keeps doing is guarding sameness if it was published —
    YouTube has it whether this page shows it or not.
    """
    done = []
    for clip_id in clip_ids:
        row = db.get(conn, clip_id)
        if row is None:
            raise ValueError(f"no clip {clip_id}")
        if row["deleted_at"]:
            continue
        db.update(conn, clip_id, deleted_at=db.now())
        logs.event("clip.binned", channel=row["channel_id"], clip=clip_id, was=row["status"])
        done.append(clip_id)
    return done


def unbin_clips(conn: sqlite3.Connection, clip_ids: list[str]) -> list[str]:
    done = []
    for clip_id in clip_ids:
        row = db.get(conn, clip_id)
        if row is None:
            raise ValueError(f"no clip {clip_id}")
        if not row["deleted_at"]:
            continue
        db.update(conn, clip_id, deleted_at=None)
        logs.event("clip.unbinned", channel=row["channel_id"], clip=clip_id, status=row["status"])
        done.append(clip_id)
    return done


def destroy_clips(conn: sqlite3.Connection, clip_ids: list[str]) -> list[str]:
    """Delete binned clips for good: the render directory and the row.

    Only from the bin, so nothing goes from a list to gone in one click. The
    publish-queue copy of a published clip is left alone — that is your
    upload record, not the factory's working file — and the event log keeps
    what happened.
    """
    done = []
    for clip_id in clip_ids:
        row = db.get(conn, clip_id)
        if row is None:
            raise ValueError(f"no clip {clip_id}")
        if not row["deleted_at"]:
            raise ValueError(f"{clip_id} is not in the bin; bin it first")
        if row["video_path"]:
            shutil.rmtree(db.video_file(row).parent, ignore_errors=True)
        conn.execute("DELETE FROM clips WHERE id = ?", (clip_id,))
        conn.commit()
        logs.event("clip.destroyed", channel=row["channel_id"], clip=clip_id, was=row["status"],
                   title=row["title"])
        done.append(clip_id)
    return done


def restore(conn: sqlite3.Connection, clip_id: str) -> None:
    """Put a rejected clip back in the review queue.

    Reject is one keystroke on the Review screen and had no undo; the third
    clip of the day went out on an R. The render is still on disk, so nothing
    is redone — the clip just gets looked at again.
    """
    row = db.get(conn, clip_id)
    if row is None or row["status"] != QC_REJECTED:
        raise ValueError(f"{clip_id} is not a rejected clip")
    if not row["video_path"] or not db.video_file(row).exists():
        raise ValueError(f"{clip_id} has no render on disk; rebuild it instead")
    if row["reject_reason"] and row["reject_reason"].startswith("too similar"):
        raise ValueError(f"{clip_id} failed a measured gate ({row['reject_reason'].split(';')[0]}); that does not change by looking again")
    db.update(conn, clip_id, status=AWAITING_APPROVAL, reject_reason=None)
    logs.event("clip.restored", channel=row["channel_id"], clip=clip_id, was=row["reject_reason"])


def reject(conn: sqlite3.Connection, clip_id: str, reason: str) -> None:
    row = db.get(conn, clip_id)
    if row is None:
        raise ValueError(f"no clip {clip_id}")
    db.update(conn, clip_id, status=QC_REJECTED, reject_reason=f"human: {reason}")
    logs.event(
        "clip.rejected", level="warn", channel=row["channel_id"], clip=clip_id,
        reason=reason,
    )
