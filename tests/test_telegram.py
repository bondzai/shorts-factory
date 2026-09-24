"""The Telegram bot: pairing, commands, and deciding from the phone.

Nothing here talks to Telegram. `telegram.call` is replaced with a recorder,
so each test says what the bot would have sent and asserts on that.
"""

import json

import pytest

from factory import channels, db, notify, telegram
from factory.models import APPROVED, AWAITING_APPROVAL, QC_REJECTED


@pytest.fixture
def bot(sandbox, monkeypatch):
    sent = []

    def fake_call(method, payload=None, *, token=None, files=None, timeout=None):
        sent.append({"method": method, **(payload or {}), "files": sorted(files or {})})
        return {"message_id": len(sent)}

    monkeypatch.setattr(telegram, "call", fake_call)
    # A decision also fires the ordinary clip.approved notification; that is
    # notify's business and tested there. Here only the bot's own replies count.
    monkeypatch.setattr(notify, "from_log", lambda name, fields: False)
    monkeypatch.setenv("FACTORY_TELEGRAM_TOKEN", "123:abc")
    monkeypatch.setenv("FACTORY_TELEGRAM_CHAT_ID", "777")
    with db.connect() as conn:
        db.migrate(conn)
        channels.create(conn, name="Main", channel_id="main")
    return sent


def waiting_clip(seed=1, **fields) -> str:
    with db.connect() as conn:
        cid = db.insert_clip(conn, channel_id="main", generator="physics", variant="marble_race", seed=seed, params={}, hook="", plan_why="t")
        db.update(conn, cid, status=AWAITING_APPROVAL, title=f"Pick your marble {seed}",
                  qc_json=json.dumps({"hook_strength": 4, "policy_risk": "low"}), **fields)
        conn.commit()
    return cid


def status_of(cid):
    with db.connect() as conn:
        return db.get(conn, cid)["status"]


def message(text, chat="777"):
    return {"update_id": 1, "message": {"chat": {"id": int(chat)}, "text": text}}


# --- pairing ------------------------------------------------------------------

def test_unpaired_bot_answers_start_with_the_chat_id_and_nothing_else(bot, monkeypatch):
    monkeypatch.setenv("FACTORY_TELEGRAM_CHAT_ID", "")
    assert telegram.configured() is False
    telegram.handle_update(message("/start", chat="4242"))
    assert "4242" in bot[-1]["text"] and "FACTORY_TELEGRAM_CHAT_ID=4242" in bot[-1]["text"]
    n = len(bot)
    telegram.handle_update(message("/status", chat="4242"))
    assert len(bot) == n  # not paired: silent


def test_a_stranger_gets_no_answer_once_paired(bot):
    telegram.handle_update(message("/status", chat="999"))
    telegram.handle_update(message("/start", chat="999"))
    assert bot == []


# --- commands -----------------------------------------------------------------

def test_status_and_queue_read_the_tables(bot):
    cid = waiting_clip()
    telegram.handle_update(message("/status"))
    assert bot[-1]["method"] == "sendMessage" and "[main] 1 to decide" in bot[-1]["text"]
    telegram.handle_update(message("/queue"))
    assert cid[:6] in bot[-1]["text"] and "Pick your marble 1" in bot[-1]["text"]


def test_approve_and_reject_by_prefix(bot):
    a, b = waiting_clip(1), waiting_clip(2)
    telegram.handle_update(message(f"/approve {a[:5]}"))
    assert status_of(a) == APPROVED and "approved" in bot[-1]["text"]
    telegram.handle_update(message(f"/reject {b[:5]} too slow"))
    assert status_of(b) == QC_REJECTED
    with db.connect() as conn:
        assert db.get(conn, b)["reject_reason"] == "human: too slow"
    telegram.handle_update(message(f"/approve {a[:5]}"))
    assert "not waiting" in bot[-1]["text"]  # already decided


def test_an_ambiguous_or_unknown_prefix_is_named_not_guessed(bot):
    telegram.handle_update(message("/approve zzzz"))
    assert "no clip starts with zzzz" in bot[-1]["text"]
    with db.connect() as conn:
        for seed in (1, 2):
            cid = db.insert_clip(conn, channel_id="main", generator="physics", variant="marble_race", seed=seed, params={}, hook="", plan_why="t")
            conn.execute("UPDATE clips SET id = ? WHERE id = ?", (f"aaaa{seed}", cid))
            db.update(conn, f"aaaa{seed}", status=AWAITING_APPROVAL)
        conn.commit()
    telegram.handle_update(message("/approve aaaa"))
    assert "matches 2 clips" in bot[-1]["text"]
    assert status_of("aaaa1") == AWAITING_APPROVAL


def test_help_lists_every_command(bot):
    telegram.handle_update(message("/help"))
    for cmd in ("/status", "/queue", "/clip", "/approve", "/reject", "/daily"):
        assert cmd in bot[-1]["text"]
    telegram.handle_update(message("/dance"))
    assert "don't know" in bot[-1]["text"]
    n = len(bot)
    telegram.handle_update(message("hello there"))  # not a command
    assert len(bot) == n


# --- the clip with buttons ----------------------------------------------------

def test_clip_goes_as_video_with_approve_and_reject_under_it(bot, sandbox):
    path = sandbox / "data" / "work" / "main" / "x" / "clip.mp4"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"\x00" * 100)
    cid = waiting_clip(video_path="data/work/main/x/clip.mp4", comment_prompt="Red or blue?")
    telegram.handle_update(message(f"/clip {cid[:6]}"))
    msg = bot[-1]
    assert msg["method"] == "sendVideo" and msg["files"] == ["video"]
    assert "Pick your marble 1" in msg["caption"] and "hook 4/5" in msg["caption"] and "Red or blue?" in msg["caption"]
    buttons = msg["reply_markup"]["inline_keyboard"][0]
    assert [b["callback_data"] for b in buttons] == [f"ok:{cid}", f"no:{cid}"]


def test_a_missing_file_falls_back_to_text_with_the_buttons(bot):
    cid = waiting_clip()
    telegram.handle_update(message(f"/clip {cid[:6]}"))
    assert bot[-1]["method"] == "sendMessage" and "video not attached" in bot[-1]["text"]
    assert bot[-1]["reply_markup"]["inline_keyboard"]


def test_a_tap_on_approve_decides_and_removes_the_buttons(bot):
    cid = waiting_clip()
    telegram.handle_update({"update_id": 9, "callback_query": {
        "id": "cb1", "data": f"ok:{cid}", "message": {"message_id": 5, "chat": {"id": 777}}}})
    assert status_of(cid) == APPROVED
    methods = [m["method"] for m in bot]
    assert methods == ["answerCallbackQuery", "editMessageReplyMarkup", "sendMessage"]
    assert bot[1]["reply_markup"] == {"inline_keyboard": []}


def test_a_tap_from_another_chat_does_nothing(bot):
    cid = waiting_clip()
    telegram.handle_update({"update_id": 9, "callback_query": {
        "id": "cb1", "data": f"ok:{cid}", "message": {"message_id": 5, "chat": {"id": 1}}}})
    assert status_of(cid) == AWAITING_APPROVAL and bot == []


# --- as a notification sink ---------------------------------------------------

def test_notify_reaches_telegram_and_a_passed_qc_sends_the_clip(bot, monkeypatch):
    monkeypatch.delenv("FACTORY_WEBHOOK_URL", raising=False)
    monkeypatch.setattr(notify, "_config", lambda: {"telegram": True, "on": ["clip.qc", "task.finished"]})
    cid = waiting_clip()
    assert notify.post("task.finished", "[main] task #1 done", channel="main") is True
    notify.flush()
    assert bot[-1]["method"] == "sendMessage" and bot[-1]["text"] == "[main] task #1 done"
    assert notify.post("clip.qc", f"[main] clip {cid[:6]} passed QC", channel="main", clip=cid) is True
    notify.flush()
    assert bot[-1]["method"] in ("sendVideo", "sendMessage") and bot[-1]["reply_markup"]["inline_keyboard"]


def test_sinks_name_hosts_not_secrets(bot, monkeypatch):
    monkeypatch.setenv("FACTORY_WEBHOOK_URL", "https://discord.com/api/webhooks/1/secret")
    out = notify.sinks()
    assert {s["kind"] for s in out} == {"webhook", "telegram"}
    assert all("secret" not in s["where"] and "123:abc" not in s["where"] for s in out)
    assert next(s for s in out if s["kind"] == "telegram")["where"] == "chat …777"


def test_poll_once_advances_the_offset_and_survives_a_bad_update(bot, monkeypatch):
    updates = [{"update_id": 10, "message": {"chat": {"id": 777}, "text": "/status"}}, {"update_id": 11}]
    monkeypatch.setattr(telegram, "call", lambda method, payload=None, **kw: updates if method == "getUpdates" else {})
    assert telegram.poll_once(None) == 12


def test_polling_does_not_start_without_a_token(sandbox, monkeypatch):
    monkeypatch.delenv("FACTORY_TELEGRAM_TOKEN", raising=False)
    assert telegram.start_polling() is None
