import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from factory import db, notify, settings


class _Sink:
    def __init__(self, status=200):
        self.received = []
        self.status = status
        handler = self._handler()
        self.server = HTTPServer(("127.0.0.1", 0), handler)
        self.url = f"http://127.0.0.1:{self.server.server_port}/hook"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def _handler(sink):
        class H(BaseHTTPRequestHandler):
            def do_POST(self):
                body = self.rfile.read(int(self.headers["Content-Length"]))
                sink.received.append(json.loads(body))
                self.send_response(sink.status)
                self.end_headers()
            def log_message(self, *a):
                pass
        return H

    def close(self):
        self.server.shutdown()


@pytest.fixture
def sink(sandbox, monkeypatch):
    s = _Sink()
    raw = settings.load().raw
    monkeypatch.setitem(raw, "notify", {"webhook_url": s.url, "on": ["run.finished", "run.failed"]})
    yield s
    s.close()


def test_nothing_is_sent_without_a_url(sandbox, monkeypatch):
    monkeypatch.setitem(settings.load().raw, "notify", {"webhook_url": ""})
    assert notify.post("run.finished", "hi") is False


def test_events_not_in_the_list_are_skipped(sink, monkeypatch):
    monkeypatch.setitem(
        settings.load().raw, "notify", {"webhook_url": sink.url, "on": ["run.failed"]}
    )
    assert notify.post("run.finished", "hi") is False
    assert notify.post("run.failed", "oh") is True
    notify.flush()
    assert len(sink.received) == 1


def test_the_payload_carries_text_and_structure(sink):
    notify.run_finished(
        channel_id="main", kind="build", status="ok",
        detail="2 reached the queue", cost_usd=0.04, waiting=3,
    )
    notify.flush()
    body = sink.received[0]
    # Slack, Discord and ntfy each read one of these two.
    assert body["text"] == body["content"]
    assert "build done" in body["text"]
    assert "3 waiting" in body["text"]
    assert body["channel"] == "main"
    assert body["cost_usd"] == 0.04


def test_a_failed_run_sends_the_failure_event(sink):
    notify.run_finished(
        channel_id="main", kind="plan", status="failed",
        detail="seed stalled", cost_usd=0.0, waiting=0,
    )
    notify.flush()
    assert sink.received[0]["event"] == "run.failed"


def test_finishing_a_run_notifies(sink):
    """The hook lives in finish_run, so every surface gets it for free."""
    from factory import channels

    with db.connect() as conn:
        channels.create(conn, name="Gravity Lab", channel_id="gl")
        run = db.start_run(conn, "gl", "build")
        db.finish_run(conn, run, status="ok", detail="done", cost_usd=0.01)
    notify.flush()
    assert sink.received and sink.received[0]["kind"] == "build"


def test_delivery_survives_the_process_ending(sink):
    """A daemon thread dies with the process; flush is what makes it arrive."""
    notify.post("run.finished", "late")
    notify.flush()
    assert len(sink.received) == 1


def test_an_endpoint_that_errors_does_not_raise(sandbox, monkeypatch):
    s = _Sink(status=500)
    monkeypatch.setitem(settings.load().raw, "notify", {"webhook_url": s.url, "on": None})
    try:
        assert notify.post("anything", "hi") is True
        notify.flush()
    finally:
        s.close()


def test_an_unreachable_endpoint_does_not_raise(sandbox, monkeypatch):
    monkeypatch.setitem(
        settings.load().raw, "notify",
        {"webhook_url": "http://127.0.0.1:1/nope", "on": None},
    )
    assert notify.post("run.finished", "hi") is True
    notify.flush()
