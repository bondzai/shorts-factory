"""Deleting what the pipeline no longer needs.

Each clip leaves three files behind: `video.mp4` (silent, pre-mux), `audio.wav`,
and `clip.mp4`. Measured on this project, that is about 4.5 MB a clip of which
roughly 3 MB is throwaway the moment the mux finishes. At two clips a day the
waste is invisible; at five a day for three months it is over a gigabyte of
files nothing will ever open again.

Two separate jobs, deliberately not one:

  sweep_intermediates  runs after every build, deletes the pre-mux pair. Safe
                       by construction — clip.mp4 already contains both.
  sweep_clips          runs on demand, deletes clip.mp4 for clips whose outcome
                       is settled and old enough. This one can lose something
                       you wanted, so it is age-gated, status-gated, and can be
                       asked what it would do before it does it.

Nothing here touches data/out: a published clip's copy in the publish queue is
the artefact you actually shipped.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import db, logs, settings

INTERMEDIATES = ("video.mp4", "audio.wav")


@dataclass
class Swept:
    files: int = 0
    bytes_freed: int = 0
    clips: list[str] = field(default_factory=list)

    @property
    def mb(self) -> float:
        return round(self.bytes_freed / 1_000_000, 1)

    def as_dict(self) -> dict[str, Any]:
        return {
            "files": self.files,
            "mb_freed": self.mb,
            "clips": self.clips,
        }


def _unlink(path: Path, swept: Swept, dry_run: bool) -> None:
    try:
        size = path.stat().st_size
    except OSError:
        return
    if not dry_run:
        try:
            path.unlink()
        except OSError:
            return
    swept.files += 1
    swept.bytes_freed += size


def sweep_intermediates(clip_dir: Path, *, dry_run: bool = False) -> Swept:
    """Drop the pre-mux pair for one clip. Only ever runs once clip.mp4 exists."""
    swept = Swept()
    if not (clip_dir / "clip.mp4").exists():
        return swept
    for name in INTERMEDIATES:
        _unlink(clip_dir / name, swept, dry_run)
    return swept


def sweep_clips(
    conn: sqlite3.Connection,
    *,
    dry_run: bool = False,
    channel_id: str | None = None,
) -> Swept:
    """Delete rendered files for clips whose outcome is settled and old enough."""
    cfg = settings.load().raw.get("retention", {})
    rules = {
        "qc_rejected": int(cfg.get("rejected_days", 3)),
        "failed": int(cfg.get("rejected_days", 3)),
        "published": int(cfg.get("published_days", 30)),
    }
    swept = Swept()
    for status, days in rules.items():
        if days < 0:  # negative means keep forever
            continue
        sql = (
            "SELECT id, channel_id, video_path FROM clips "
            "WHERE status = ? AND video_path IS NOT NULL AND purged_at IS NULL "
            "AND created_at < datetime('now', ?)"
        )
        args: list[Any] = [status, f"-{days} days"]
        if channel_id:
            sql += " AND channel_id = ?"
            args.append(channel_id)
        for row in conn.execute(sql, args).fetchall():
            path = db.video_file(row)
            before = swept.files
            _unlink(path, swept, dry_run)
            for name in INTERMEDIATES:
                _unlink(path.parent / name, swept, dry_run)
            if swept.files > before:
                swept.clips.append(row["id"])
                if not dry_run:
                    conn.execute(
                        "UPDATE clips SET purged_at = ? WHERE id = ?", (db.now(), row["id"])
                    )
                    # An empty directory left behind is just noise in a listing.
                    try:
                        path.parent.rmdir()
                    except OSError:
                        pass
    if not dry_run and swept.clips:
        conn.commit()
        logs.event(
            "gc.swept", channel=channel_id, files=swept.files, mb_freed=swept.mb,
            clips=len(swept.clips),
        )
    return swept


def sweep_all_intermediates(*, dry_run: bool = False) -> Swept:
    """Sweep every clip directory under data/work, not only the one just built.

    Catches directories left by earlier runs and by `render-check`, which does
    not go through the pipeline at all.
    """
    total = Swept()
    root = settings.load().work_dir
    if not root.exists():
        return total
    for final in root.rglob("clip.mp4"):
        swept = sweep_intermediates(final.parent, dry_run=dry_run)
        total.files += swept.files
        total.bytes_freed += swept.bytes_freed
        if swept.files:
            total.clips.append(final.parent.name)
    return total


def disk_usage() -> dict[str, Any]:
    cfg = settings.load()
    def total(path: Path) -> int:
        if not path.exists():
            return 0
        return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())

    work = total(cfg.work_dir)
    out = total(cfg.out_dir)
    return {
        "work_mb": round(work / 1_000_000, 1),
        "out_mb": round(out / 1_000_000, 1),
        "total_mb": round((work + out) / 1_000_000, 1),
    }
