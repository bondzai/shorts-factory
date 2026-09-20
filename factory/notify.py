"""Outbound notification when a run finishes.

Pointed away from this machine, not at it. The MCP server, the CLI and the web
UI all write the same SQLite file, so none of them needs telling what the others
did — they can already see it. The thing that cannot see it is you, asleep,
while an agent builds clips at three in the morning.

So this posts to a URL you choose: Slack, Discord, ntfy, a webhook of your own.
The payload carries a plain `text` line, which is what those three read, plus
the structured fields underneath for anything that wants them.

Hooked into `db.finish_run`, which every surface already calls, so a run started
from Codex, from cron and from the web all notify the same way.

Never raises. A webhook that is down must not fail the build that called it.
"""

from __future__ import annotations

import atexit
import json
import os
from datetime import datetime
import threading
import urllib.error
import urllib.request
from typing import Any

from . import settings

TIMEOUT_SECONDS = 6

# Delivery runs off the calling thread so a slow endpoint cannot stall a build.
# But `factory build` finishes its last run and exits immediately, and a daemon
# thread dies with the process — the first version of this lost every
# notification a CLI command sent. These are tracked and joined at exit.
_IN_FLIGHT: list[threading.Thread] = []
_FLUSH_BUDGET = TIMEOUT_SECONDS + 2


def flush(timeout: float = _FLUSH_BUDGET) -> None:
    """Wait for outstanding deliveries. Registered at exit; safe to call anytime."""
    for thread in list(_IN_FLIGHT):
        thread.join(timeout=timeout)
        if not thread.is_alive():
            _IN_FLIGHT.remove(thread)


atexit.register(flush)


def _config() -> dict[str, Any]:
    cfg = dict(settings.load().raw.get("notify", {}))
    # The URL is a secret (anyone holding it can post as you), so it lives in
    # .env, not in config.toml where it would be committed.
    settings.load_env()
    env_url = os.environ.get("FACTORY_WEBHOOK_URL")
    if env_url:
        cfg["webhook_url"] = env_url
    return cfg


# What is worth waking you for, and how to say it in one line. Anything not
# here is visible on the Activity screen and nowhere else — a webhook that
# fires on every render is a webhook you mute.
def for_event(name: str, fields: dict[str, Any]) -> str | None:
    f = fields
    ch = f.get("channel") or "main"
    clip = (f.get("clip") or "")[:6]
    if name == "task.finished":
        mark = "done" if f.get("status") == "done" else "FAILED"
        tail = f.get("error") or ""
        return f"[{ch}] task #{f.get('task')} {f.get('kind')} {mark} by {f.get('by')}" + (f" — {tail}" if tail else "")
    if name == "clip.qc":
        if f.get("passed"):
            return f"[{ch}] clip {clip} passed QC — waiting for your approval"
        reasons = f.get("hard_failures") or []
        return f"[{ch}] clip {clip} rejected in QC" + (f" — {'; '.join(reasons)}" if reasons else "")
    if name == "clip.published":
        return f"[{ch}] published: {f.get('title') or clip}"
    if name == "clip.failed":
        return f"[{ch}] clip {clip} FAILED at {f.get('stage')}: {f.get('error')}"
    if name == "clip.publish_failed":
        return f"[{ch}] publish FAILED for clip {clip}: {f.get('error')}"
    if name == "clip.retitled":
        return f"[{ch}] retitled: “{f.get('was')}” → “{f.get('title')}” ({f.get('by')})"
    if name == "clip.approved":
        return f"[{ch}] approved: {f.get('title') or clip}"
    return None


def from_log(name: str, fields: dict[str, Any]) -> bool:
    """Called for every logged event; posts the ones worth a notification."""
    if name.startswith("notify."):
        return False
    text = for_event(name, fields)
    if text is None:
        return False
    return post(name, text, **{k: v for k, v in fields.items() if k in ("channel", "clip", "task", "kind", "status", "title", "by")})


def enabled_for(event: str) -> bool:
    cfg = _config()
    if not cfg.get("webhook_url"):
        return False
    if event in ("notify.test", "notify.daily"):
        return True
    wanted = cfg.get("on")
    return True if wanted is None else event in wanted


def post(event: str, text: str, **fields: Any) -> bool:
    """Send one notification. Returns whether it was attempted, not whether it landed."""
    if not enabled_for(event):
        return False
    url = _config()["webhook_url"]
    payload = {
        # Slack, Discord and ntfy all read a top-level text/content field; send
        # both names so one config works for the common three.
        "text": text,
        "content": text,
        "event": event,
        **fields,
    }
    thread = threading.Thread(target=_deliver, args=(url, payload, event), daemon=True)
    _IN_FLIGHT.append(thread)
    thread.start()
    return True


def _deliver(url: str, payload: dict[str, Any], event: str) -> None:
    from . import logs

    request = urllib.request.Request(
        url,
        data=json.dumps(payload, default=str).encode("utf-8"),
        # Discord sits behind Cloudflare, which answers urllib's default
        # User-Agent with a 403. Say who is calling.
        headers={"Content-Type": "application/json", "User-Agent": "shorts-factory/1.0 (+notify)"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            logs.event("notify.sent", event_name=event, status=response.status)
    except urllib.error.HTTPError as exc:
        logs.event("notify.failed", level="warn", event_name=event, status=exc.code)
    except Exception as exc:
        logs.event("notify.failed", level="warn", event_name=event, error=str(exc))


def daily_text(conn) -> str | None:
    """How many approved clips wait for upload, per channel, and when to do it.
    None when nothing waits — a reminder about nothing is noise."""
    from . import channels, db, schedule
    from .models import APPROVED

    lines = []
    for ch in channels.all_channels(conn):
        rows = db.search_clips(conn, ch.id, status=APPROVED, limit=10)
        if not rows:
            continue
        titles = "; ".join((r["title"] or r["id"])[:60] for r in rows[:3])
        more = f" (+{len(rows) - 3} more)" if len(rows) > 3 else ""
        lines.append(f"[{ch.id}] {len(rows)} approved, ready to upload: {titles}{more}")
    if not lines:
        return None
    return "\n".join(lines) + f"\nNext slot: {schedule.describe(schedule.next_slot())} — open Today, Copy for upload."


def daily(force: bool = False) -> bool:
    """Post the reminder once per local day. Returns whether it was posted."""
    from . import db, schedule

    with db.connect() as conn:
        key = datetime.now(schedule.timezone()).date().isoformat()
        if not force and db.overrides(conn).get(("notify", "daily_sent")) == key:
            return False
        text = daily_text(conn)
        db.set_override(conn, "notify", "daily_sent", key)
        conn.commit()
    if text is None:
        return False
    return post("notify.daily", text, kind="daily")


def due(now: datetime | None = None) -> bool:
    """Is it the reminder minute (or just past it, unsent today)?"""
    from . import schedule

    at = _config().get("daily_at")
    if not at:
        return False
    h, m = schedule.parse_hhmm(at, (5, 45))
    now = now or datetime.now(schedule.timezone())
    return (now.hour, now.minute) >= (h, m)


def start_scheduler(interval_s: float = 30.0) -> threading.Thread:
    """A daemon that posts the daily reminder while the server runs. It checks
    the clock every half minute and sends at most once per local day; a
    restart after the minute has passed still sends, a second run does not."""
    def loop() -> None:
        import time
        while True:
            try:
                if due():
                    daily()
            except Exception:  # never let the reminder take the server down
                pass
            time.sleep(interval_s)
    thread = threading.Thread(target=loop, name="daily-reminder", daemon=True)
    thread.start()
    return thread


def run_finished(
    *, channel_id: str, kind: str, status: str, detail: str, cost_usd: float, waiting: int
) -> bool:
    """Called for every finished run, whoever started it."""
    event = "run.failed" if status == "failed" else "run.finished"
    mark = "failed" if status == "failed" else "done"
    text = (
        f"[{channel_id}] {kind} {mark}"
        + (f": {detail}" if detail else "")
        + (f" · ${cost_usd:.4f}" if cost_usd else "")
        + (f" · {waiting} waiting for review" if waiting else "")
    )
    return post(
        event,
        text,
        channel=channel_id,
        kind=kind,
        status=status,
        detail=detail,
        cost_usd=round(cost_usd, 6),
        waiting=waiting,
    )
