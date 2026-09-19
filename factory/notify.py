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
    return settings.load().raw.get("notify", {})


def enabled_for(event: str) -> bool:
    cfg = _config()
    if not cfg.get("webhook_url"):
        return False
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
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            logs.event("notify.sent", event_name=event, status=response.status)
    except urllib.error.HTTPError as exc:
        logs.event("notify.failed", level="warn", event_name=event, status=exc.code)
    except Exception as exc:
        logs.event("notify.failed", level="warn", event_name=event, error=str(exc))


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
