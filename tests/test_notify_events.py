"""Only what is worth waking you for, said in one line."""

from factory import notify


def test_important_events_become_one_line_each():
    assert "task #6 make-clip done by Codex" in notify.for_event("task.finished", {"task": 6, "kind": "make-clip", "status": "done", "by": "Codex"})
    assert "FAILED" in notify.for_event("task.finished", {"task": 1, "kind": "make-clip", "status": "failed", "by": "Codex", "error": "too similar"})
    assert "passed QC" in notify.for_event("clip.qc", {"clip": "abcdef123456", "passed": True})
    assert "0.906" in notify.for_event("clip.qc", {"clip": "abc", "passed": False, "hard_failures": ["too similar: 0.906 > 0.88"]})
    assert notify.for_event("clip.rendered", {"clip": "abc"}) is None  # every render would be a mute


def test_nothing_is_posted_when_no_webhook_is_set(sandbox, monkeypatch):
    monkeypatch.delenv("FACTORY_WEBHOOK_URL", raising=False)
    from factory import settings
    monkeypatch.setitem(settings.load().raw["notify"], "webhook_url", "")
    assert notify.from_log("task.finished", {"task": 1, "kind": "x", "status": "done", "by": "y"}) is False


def test_the_env_url_wins_and_the_bridge_posts(sandbox, monkeypatch):
    monkeypatch.setenv("FACTORY_WEBHOOK_URL", "https://example.invalid/hook")
    sent = []
    monkeypatch.setattr(notify, "_deliver", lambda url, payload, event: sent.append((url, payload["content"])))
    assert notify.from_log("clip.published", {"channel": "main", "clip": "abc", "title": "Red by 0.4s"}) is True
    notify.flush()
    assert sent and sent[0][0].endswith("/hook") and "published: Red by 0.4s" in sent[0][1]
