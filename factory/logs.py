"""Structured event log, one JSON object per line.

The runs table already says a build happened and what it cost. This says what
happened inside it: which clip reached which stage, what each agent call cost,
and the exact reason a clip was thrown out. When an agent is driving the
pipeline rather than a person, this file is the only account of what it did.

Written as JSONL because it has to be both greppable at 2am and parseable by
the thing that reads it back into the UI.
"""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from . import settings

_LOCK = threading.Lock()
LEVELS = ("debug", "info", "warn", "error")


def log_dir() -> Path:
    path = settings.load().db_path.parent / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _today_path() -> Path:
    return log_dir() / f"factory-{datetime.now(timezone.utc):%Y-%m-%d}.jsonl"


def event(
    name: str,
    *,
    level: str = "info",
    channel: str | None = None,
    clip: str | None = None,
    actor: str | None = None,
    **fields: Any,
) -> dict[str, Any]:
    """Record one event. Never raises: a broken log must not stop a build."""
    record = {
        "at": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        "level": level if level in LEVELS else "info",
        "event": name,
        "channel": channel,
        "clip": clip,
        # Who asked for this: "cli", "web", "mcp:<client>". Blank means in-process.
        "actor": actor or os.environ.get("FACTORY_ACTOR"),
        **fields,
    }
    try:
        line = json.dumps(record, default=str, ensure_ascii=False)
        with _LOCK:
            with open(_today_path(), "a", encoding="utf-8") as handle:
                handle.write(line + "\n")
    except Exception:  # pragma: no cover - logging must never be fatal
        pass
    # Some events are worth telling you about wherever you are. notify decides
    # which; a broken webhook must not stop a build, and it never does.
    try:
        from . import notify

        notify.from_log(name, record)
    except Exception:
        pass
    return record


def read(
    *,
    limit: int = 200,
    channel: str | None = None,
    level: str | None = None,
    event_name: str | None = None,
    clip: str | None = None,
    days: int = 3,
) -> list[dict[str, Any]]:
    """Most recent events first, newest file first."""
    files = sorted(log_dir().glob("factory-*.jsonl"), reverse=True)[:days]
    out: list[dict[str, Any]] = []
    for path in files:
        for record in reversed(list(_iter_file(path))):
            if channel and record.get("channel") != channel:
                continue
            if level and record.get("level") != level:
                continue
            if event_name and not str(record.get("event", "")).startswith(event_name):
                continue
            if clip and record.get("clip") != clip:
                continue
            out.append(record)
            if len(out) >= limit:
                return out
    return out


def _iter_file(path: Path) -> Iterator[dict[str, Any]]:
    try:
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    # A half-written final line is normal if a process died
                    # mid-write; skip it rather than lose the whole file.
                    continue
    except FileNotFoundError:
        return
