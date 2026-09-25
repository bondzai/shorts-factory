"""Telegram: the factory in your pocket.

Two directions, one bot.

  Out    every notification that goes to the webhook also goes here, and a
         clip that passes QC arrives as the video itself with Approve and
         Reject buttons under it. Deciding on the phone is the same call as
         pressing A or R on Team.

  In     a handful of commands — /status, /queue, /clip, /approve, /reject,
         /daily — answered by the server while `factory serve` runs. The bot
         long-polls Telegram; nothing is exposed on this machine.

Setup is three steps and one message: make a bot with @BotFather, put its
token in .env as FACTORY_TELEGRAM_TOKEN, send the bot /start. It replies with
the chat id; put that in .env as FACTORY_TELEGRAM_CHAT_ID and restart. Until
the chat id is set the bot answers /start and nothing else, so a stranger who
finds the bot cannot approve your clips. Once it is set, only that chat can.

Both values are secrets (the token posts as you; the chat id says where) and
live in .env, never in config.toml.
"""

from __future__ import annotations

import json
import mimetypes
import os
import threading
import urllib.error
import urllib.request
import uuid
from typing import Any

from . import settings

API = "https://api.telegram.org"
TIMEOUT_SECONDS = 8
POLL_SECONDS = 20          # Telegram holds getUpdates open this long
MAX_VIDEO_BYTES = 50 * 1024 * 1024  # the Bot API's upload ceiling

HELP = (
    "What I answer:\n"
    "/status — every channel: to decide, to upload, queued, who is working\n"
    "/queue — the clips waiting for your decision\n"
    "/clip <id> — send me that clip to watch, with Approve / Reject under it\n"
    "/approve <id> — same as A on Team\n"
    "/reject <id> [why] — same as R on Team; the reason is what the next planner reads\n"
    "/daily — the upload reminder, now\n"
    "An id is the first few characters of a clip id; the queue shows them."
)


def config() -> dict[str, str]:
    """Token and chat id from the environment (.env is loaded into it)."""
    settings.load_env()
    return {
        "token": os.environ.get("FACTORY_TELEGRAM_TOKEN", "").strip(),
        "chat_id": os.environ.get("FACTORY_TELEGRAM_CHAT_ID", "").strip(),
    }


def configured() -> bool:
    cfg = config()
    return bool(cfg["token"] and cfg["chat_id"])


# --- the wire ------------------------------------------------------------------

def call(method: str, payload: dict[str, Any] | None = None, *, token: str | None = None,
         files: dict[str, tuple[str, bytes]] | None = None, timeout: float = TIMEOUT_SECONDS) -> dict[str, Any]:
    """One Bot API call. Raises on transport or API failure; callers that
    must never raise (notify) catch. Tests replace this function."""
    token = token or config()["token"]
    if not token:
        raise RuntimeError("no Telegram token: set FACTORY_TELEGRAM_TOKEN in .env")
    url = f"{API}/bot{token}/{method}"
    payload = {k: v for k, v in (payload or {}).items() if v is not None}
    if files:
        body, content_type = _multipart(payload, files)
        request = urllib.request.Request(url, data=body, headers={"Content-Type": content_type}, method="POST")
    else:
        request = urllib.request.Request(
            url, data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST",
        )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            out = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:200]
        raise RuntimeError(f"telegram {method}: HTTP {exc.code} {detail}") from None
    if not out.get("ok"):
        raise RuntimeError(f"telegram {method}: {out.get('description', 'not ok')}")
    return out.get("result", {})


def _multipart(fields: dict[str, Any], files: dict[str, tuple[str, bytes]]) -> tuple[bytes, str]:
    boundary = f"----shorts-factory-{uuid.uuid4().hex}"
    parts: list[bytes] = []
    for key, value in fields.items():
        text = value if isinstance(value, str) else json.dumps(value)
        parts.append(
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"{key}\"\r\n\r\n{text}\r\n".encode("utf-8")
        )
    for key, (name, data) in files.items():
        mime = mimetypes.guess_type(name)[0] or "application/octet-stream"
        parts.append(
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"{key}\"; filename=\"{name}\"\r\n"
            f"Content-Type: {mime}\r\n\r\n".encode("utf-8") + data + b"\r\n"
        )
    parts.append(f"--{boundary}--\r\n".encode("utf-8"))
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


# --- outbound -------------------------------------------------------------------

def send_text(text: str, *, chat_id: str | None = None, reply_markup: dict | None = None) -> dict[str, Any]:
    chat_id = chat_id or config()["chat_id"]
    return call("sendMessage", {"chat_id": chat_id, "text": text[:4000], "reply_markup": reply_markup,
                                "disable_web_page_preview": True})


def decision_keyboard(clip_id: str) -> dict[str, Any]:
    return {"inline_keyboard": [[
        {"text": "✅ Approve", "callback_data": f"ok:{clip_id}"},
        {"text": "❌ Reject", "callback_data": f"no:{clip_id}"},
    ]]}


def clip_caption(row) -> str:
    qc = json.loads(row["qc_json"]) if row["qc_json"] else {}
    facts = json.loads(row["facts_json"]) if row["facts_json"] else {}
    bits = [f"[{row['channel_id']}] {row['title'] or row['id']}", f"clip {row['id'][:8]} · {row['generator']}/{row['variant']}"]
    if facts.get("stage"):
        bits[-1] += f" · stage {facts['stage']}"
    if row["duration_s"]:
        bits[-1] += f" · {float(row['duration_s']):.1f}s"
    level = _level_line(row)
    if level:
        bits.append(level)
    if qc:
        bits.append(f"QC hook {qc.get('hook_strength', '—')}/5 · policy {qc.get('policy_risk', '—')}")
    if row["comment_prompt"]:
        bits.append(f"pinned: {row['comment_prompt']}")
    return "\n".join(bits)[:1000]


def _level_line(row) -> str | None:
    """"level L22 · before it: Blaze 9 · Tide 7 · …" for a season level clip.

    The table is the one before this level, so approving does not read as
    already counted. Never breaks the caption: a missing season file or cast
    just drops the standings half.
    """
    from . import db
    from .series import standings

    if "level_id" not in row.keys() or not row["level_id"]:
        return None
    ids = standings.level_of_clip(row)
    line = f"level {row['level_id']}"
    if ids is None:
        return line
    try:
        with db.connect() as conn:
            table = standings.summary_line(conn, row["channel_id"], ids[0], before_level=ids[1])
    except Exception:
        return line
    return f"{line} · before it: {table}"


def send_clip(clip_id: str, *, chat_id: str | None = None) -> dict[str, Any]:
    """The clip itself, with the two buttons. Falls back to a text line when
    the file is missing or over Telegram's limit — the decision can still be
    made with /approve and /reject."""
    from . import db
    from .models import AWAITING_APPROVAL

    chat_id = chat_id or config()["chat_id"]
    with db.connect() as conn:
        row = db.get(conn, clip_id)
        if row is None:
            raise ValueError(f"no clip {clip_id}")
        path = db.video_file(row)
    caption = clip_caption(row)
    markup = decision_keyboard(row["id"]) if row["status"] == AWAITING_APPROVAL else None
    if path is not None and path.exists() and path.stat().st_size <= MAX_VIDEO_BYTES:
        return call(
            "sendVideo",
            {"chat_id": chat_id, "caption": caption, "supports_streaming": "true", "reply_markup": markup},
            files={"video": (f"{row['id'][:8]}.mp4", path.read_bytes())},
            timeout=60,
        )
    why = "file not kept" if path is None or not path.exists() else "file over Telegram's 50 MB limit"
    return send_text(f"{caption}\n(video not attached: {why}; open Team to watch)", chat_id=chat_id, reply_markup=markup)


# --- inbound --------------------------------------------------------------------

def _find_clip(conn, prefix: str):
    """A clip by any unambiguous prefix of its id."""
    prefix = prefix.strip().lower()
    if not prefix:
        return None, "which clip? give the first few characters of its id"
    rows = conn.execute(
        "SELECT * FROM clips WHERE id LIKE ? AND deleted_at IS NULL ORDER BY created_at DESC LIMIT 3", (prefix + "%",)
    ).fetchall()
    if not rows:
        return None, f"no clip starts with {prefix}"
    if len(rows) > 1:
        return None, f"{prefix} matches {len(rows)} clips; give more characters: " + ", ".join(r["id"][:8] for r in rows)
    return rows[0], None


def status_text(conn) -> str:
    from . import channels, db
    from .models import APPROVED, AWAITING_APPROVAL

    lines = []
    for ch in channels.all_channels(conn):
        counts = db.status_counts(conn, ch.id)
        tasks = db.task_counts(conn, ch.id)
        workers = [r["claimed_by"] for r in conn.execute(
            "SELECT DISTINCT claimed_by FROM tasks WHERE channel_id = ? AND status = 'claimed'", (ch.id,)).fetchall()]
        lines.append(
            f"[{ch.id}] {counts.get(AWAITING_APPROVAL, 0)} to decide · {counts.get(APPROVED, 0)} to upload · "
            f"{tasks.get('queued', 0)} queued · {tasks.get('claimed', 0)} rendering"
            + (f" ({', '.join(w for w in workers if w)})" if workers else "")
        )
    return "\n".join(lines) or "no channels yet"


def queue_text(conn) -> str:
    from . import channels, db
    from .models import AWAITING_APPROVAL

    lines = []
    for ch in channels.all_channels(conn):
        for row in db.by_status(conn, ch.id, AWAITING_APPROVAL):
            qc = json.loads(row["qc_json"]) if row["qc_json"] else {}
            lines.append(f"{row['id'][:6]}  [{ch.id}] {row['title'] or '(untitled)'}  · hook {qc.get('hook_strength', '—')}/5")
    if not lines:
        return "nothing is waiting for a decision"
    return "Waiting for you — /clip <id> to watch one:\n" + "\n".join(lines[:20])


def decide(conn, prefix: str, what: str, reason: str = "") -> tuple[str, str | None]:
    """Approve or reject by prefix. Returns (reply text, clip id or None)."""
    from . import pipeline
    from .models import AWAITING_APPROVAL

    row, problem = _find_clip(conn, prefix)
    if problem:
        return problem, None
    if row["status"] != AWAITING_APPROVAL:
        return f"{row['id'][:8]} is {row['status'].replace('_', ' ')}, not waiting for a decision", row["id"]
    if what == "approve":
        pipeline.approve(conn, row["id"])
        return f"✅ approved {row['id'][:8]} — {row['title'] or ''}\nIt is on Team under 'Ready to upload'.", row["id"]
    pipeline.reject(conn, row["id"], reason or "rejected from Telegram")
    return f"❌ rejected {row['id'][:8]}" + (f" — {reason}" if reason else ""), row["id"]


def handle_command(text: str, chat_id: str) -> str | None:
    """One text message → one reply (None to stay silent)."""
    from . import db, notify

    cfg = config()
    parts = text.strip().split(maxsplit=2)
    if not parts or not parts[0].startswith("/"):
        return None
    command = parts[0].lower().split("@")[0]
    arg = parts[1] if len(parts) > 1 else ""
    rest = parts[2] if len(parts) > 2 else ""

    if not cfg["chat_id"]:
        if command == "/start":
            return (f"Hello. This chat's id is {chat_id}.\nPut FACTORY_TELEGRAM_CHAT_ID={chat_id} in .env next to the "
                    f"token and restart the server; after that I answer commands here and nowhere else.")
        return None  # not paired: say nothing to anyone else
    if str(chat_id) != cfg["chat_id"]:
        return None  # someone else found the bot

    if command in ("/start", "/help"):
        return "shorts-factory here.\n" + HELP
    with db.connect() as conn:
        if command == "/status":
            return status_text(conn)
        if command == "/queue":
            return queue_text(conn)
        if command == "/clip":
            row, problem = _find_clip(conn, arg)
            if problem:
                return problem
            send_clip(row["id"], chat_id=chat_id)
            return None
        if command == "/approve":
            return decide(conn, arg, "approve")[0]
        if command == "/reject":
            return decide(conn, arg, "reject", rest.strip())[0]
        if command == "/daily":
            return notify.daily_text(conn) or "nothing approved is waiting for upload"
    return "I don't know that one.\n" + HELP


def handle_callback(query: dict[str, Any]) -> None:
    """A tap on Approve or Reject under a clip."""
    from . import db

    cfg = config()
    data = str(query.get("data") or "")
    message = query.get("message") or {}
    chat_id = str((message.get("chat") or {}).get("id") or "")
    if not cfg["chat_id"] or chat_id != cfg["chat_id"]:
        return
    what, _, clip_id = data.partition(":")
    verb = {"ok": "approve", "no": "reject"}.get(what)
    if not verb or not clip_id:
        return
    with db.connect() as conn:
        reply, _ = decide(conn, clip_id, verb)
    call("answerCallbackQuery", {"callback_query_id": query.get("id"), "text": reply[:180]})
    if message.get("message_id"):
        # Take the buttons away so the same clip is not decided twice from a
        # stale message, and say on the message what happened.
        try:
            call("editMessageReplyMarkup", {"chat_id": chat_id, "message_id": message["message_id"],
                                            "reply_markup": {"inline_keyboard": []}})
        except Exception:
            pass
    send_text(reply, chat_id=chat_id)


def handle_update(update: dict[str, Any]) -> None:
    if "callback_query" in update:
        handle_callback(update["callback_query"])
        return
    message = update.get("message") or update.get("edited_message")
    if not message:
        return
    chat_id = str((message.get("chat") or {}).get("id") or "")
    text = message.get("text") or ""
    reply = handle_command(text, chat_id)
    if reply:
        send_text(reply, chat_id=chat_id)


def poll_once(offset: int | None) -> int | None:
    """One long poll. Returns the offset to use next."""
    updates = call("getUpdates", {"offset": offset, "timeout": POLL_SECONDS, "allowed_updates": ["message", "callback_query"]},
                   timeout=POLL_SECONDS + 10)
    for update in updates or []:
        try:
            handle_update(update)
        except Exception as exc:  # one bad update must not stop the loop
            from . import logs
            logs.event("telegram.failed", level="warn", error=str(exc), update_id=update.get("update_id"))
        offset = int(update["update_id"]) + 1
    return offset


def start_polling() -> threading.Thread | None:
    """Answer commands while the server runs. Needs a token; without a chat id
    it still runs so /start can hand the id over."""
    if not config()["token"]:
        return None
    from . import logs

    def loop() -> None:
        import time
        offset: int | None = None
        while True:
            try:
                offset = poll_once(offset)
            except Exception as exc:
                logs.event("telegram.failed", level="warn", error=str(exc))
                time.sleep(15)

    thread = threading.Thread(target=loop, name="telegram-bot", daemon=True)
    thread.start()
    logs.event("telegram.started", paired=bool(config()["chat_id"]))
    return thread
