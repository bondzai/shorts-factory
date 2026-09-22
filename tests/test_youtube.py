"""The YouTube driver, against a fake API. Nothing here reaches Google.

What matters about this driver is what it *sends*: a clip must go up private
with the slot the rest of the factory agreed on, never public by accident,
with the question as a comment and the retitle pushed. So the tests record
the request bodies and read them.
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from factory import channels, db, pipeline, settings
from factory.models import APPROVED, PUBLISHED
from factory.publish import youtube as yt

BKK = ZoneInfo("Asia/Bangkok")


class FakeRequest:
    def __init__(self, calls, name, kwargs, result):
        self.calls, self.name, self.kwargs, self.result = calls, name, kwargs, result

    def execute(self):
        self.calls.append((self.name, self.kwargs))
        return self.result

    def next_chunk(self):
        self.calls.append((self.name, self.kwargs))
        return None, self.result


class FakeCollection:
    def __init__(self, calls, prefix, results):
        self.calls, self.prefix, self.results = calls, prefix, results

    def __getattr__(self, method):
        def call(**kwargs):
            name = f"{self.prefix}.{method}"
            return FakeRequest(self.calls, name, kwargs, self.results.get(name, {}))
        return call


class FakeService:
    def __init__(self, calls, results):
        self.calls, self.results = calls, results

    def __getattr__(self, collection):
        def get():
            return FakeCollection(self.calls, collection, self.results)
        return get


@pytest.fixture
def fake(sandbox, monkeypatch):
    calls: list = []
    results = {
        "videos.insert": {"id": "vid123"},
        "videos.list": {"items": [{"snippet": {"title": "old", "description": "d", "categoryId": "24"},
                                   "statistics": {"viewCount": "1500", "likeCount": "42"}}]},
        "videos.update": {"id": "vid123"},
        "commentThreads.insert": {"id": "c1"},
        "channels.list": {"items": [{"id": "UC123", "snippet": {"title": "Gravity Lab", "customUrl": "@gravitylab"},
                                     "statistics": {"subscriberCount": "310", "videoCount": "12"}}]},
        "reports.query": {"rows": [[71.5]]},
    }
    monkeypatch.setattr(yt, "_service", lambda name, version, token_path, interactive=False: FakeService(calls, results))
    monkeypatch.setattr("googleapiclient.http.MediaFileUpload", lambda *a, **k: object())
    with db.connect() as conn:
        db.migrate(conn)
        channels.create(conn, name="Gravity Lab", channel_id="main", driver="youtube")
        ch = channels.get(conn, "main")
    ch.token_path.parent.mkdir(parents=True, exist_ok=True)
    ch.token_path.write_text("{}")  # connected, as far as the driver is concerned
    return ch, calls, results


def body_of(calls, name):
    return next(kwargs for called, kwargs in calls if called == name)


def a_clip(channel="main", **fields) -> str:
    with db.connect() as conn:
        clip_id = db.insert_clip(conn, channel_id=channel, generator="physics", variant="marble_race",
                                 seed=7, params={}, hook="", plan_why="t")
        path = settings.load().db_path.parent / "work" / clip_id / "clip.mp4"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"\x00" * 64)
        db.update(conn, clip_id, status=APPROVED, title="Pick your marble: red, blue or green",
                  description="Three marbles run the drums.", hashtags_json='["#shorts", "#marblerace"]',
                  comment_prompt="Red, blue or green — which did you back?",
                  video_path=str(path.relative_to(settings.ROOT)), **fields)
        conn.commit()
    return clip_id


# --- what goes up ---------------------------------------------------------------

def test_a_clip_uploads_private_with_the_slot_the_factory_agreed_on(fake):
    ch, calls, _ = fake
    clip_id = a_clip()
    with db.connect() as conn:
        outcome = pipeline.publish_one(conn, clip_id)
        row = db.get(conn, clip_id)
    sent = body_of(calls, "videos.insert")["body"]
    assert sent["status"]["privacyStatus"] == "private"
    from factory import schedule
    slot = schedule.next_slot().astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    assert sent["status"]["publishAt"] == slot
    assert sent["status"]["selfDeclaredMadeForKids"] is False
    assert sent["snippet"]["title"] == "Pick your marble: red, blue or green"
    assert sent["snippet"]["tags"] == ["shorts", "marblerace"]
    assert sent["snippet"]["categoryId"] == "24"
    assert outcome.status == PUBLISHED and row["remote_id"] == "vid123" and row["platform"] == "youtube"


def test_the_description_carries_the_hashtags_and_shorts_but_not_the_question(fake):
    ch, calls, _ = fake
    pipeline.publish_one(db.connect(), a_clip())
    sent = body_of(calls, "videos.insert")["body"]
    text = sent["snippet"]["description"]
    assert text.startswith("Three marbles run the drums.")
    assert "#shorts" in text and "#Shorts" in text and "#marblerace" in text
    assert "which did you back" not in text  # that is a comment, where it can be answered


def test_the_question_is_posted_as_a_comment_and_the_note_says_pinning_is_manual(fake):
    ch, calls, _ = fake
    with db.connect() as conn:
        outcome = pipeline.publish_one(conn, a_clip())
    posted = body_of(calls, "commentThreads.insert")["body"]
    assert posted["snippet"]["videoId"] == "vid123"
    assert posted["snippet"]["topLevelComment"]["snippet"]["textOriginal"].startswith("Red, blue or green")
    assert "pin it in Studio" in outcome.detail


def test_a_comment_that_will_not_post_does_not_lose_the_upload(fake, monkeypatch):
    ch, calls, results = fake
    driver = yt.YouTubePublisher(ch)
    monkeypatch.setattr(driver, "_comment", lambda *a, **k: "the comment did not post (forbidden)")
    out = driver.publish(clip_id="x", video_path=Path("/dev/null"), title="t", description="d",
                         hashtags=["#shorts"], comment="q?")
    assert out.remote_id == "vid123" and "did not post" in out.note


def test_public_is_only_ever_on_purpose(fake, monkeypatch):
    ch, calls, _ = fake
    raw = settings.load().raw
    monkeypatch.setitem(raw, "publish", {**raw["publish"], "youtube_privacy": "public"})
    yt.YouTubePublisher(ch).publish(clip_id="x", video_path=Path("/dev/null"), title="t",
                                    description="d", hashtags=[], comment=None)
    sent = body_of(calls, "videos.insert")["body"]
    assert sent["status"]["privacyStatus"] == "public" and "publishAt" not in sent["status"]


def test_private_without_a_slot_when_asked(fake, monkeypatch):
    ch, calls, _ = fake
    raw = settings.load().raw
    monkeypatch.setitem(raw, "publish", {**raw["publish"], "youtube_privacy": "private"})
    yt.YouTubePublisher(ch).publish(clip_id="x", video_path=Path("/dev/null"), title="t",
                                    description="d", hashtags=[], comment=None)
    sent = body_of(calls, "videos.insert")["body"]
    assert sent["status"]["privacyStatus"] == "private" and "publishAt" not in sent["status"]


# --- retitling a published clip reaches the video ----------------------------------

def test_a_retitle_is_pushed_to_youtube(fake):
    ch, calls, _ = fake
    clip_id = a_clip()
    with db.connect() as conn:
        pipeline.publish_one(conn, clip_id)
        out = pipeline.retitle(conn, clip_id, "Call it now: red, blue or green on the drums")
    assert out["pushed"] is True and out["needs_manual_update"] is False
    sent = body_of(calls, "videos.update")["body"]
    assert sent["id"] == "vid123" and sent["snippet"]["title"].startswith("Call it now")


def test_a_failed_push_says_so_rather_than_pretending(fake, monkeypatch):
    ch, calls, _ = fake
    clip_id = a_clip()
    with db.connect() as conn:
        pipeline.publish_one(conn, clip_id)
        monkeypatch.setattr(yt.YouTubePublisher, "update_metadata",
                            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("quotaExceeded")))
        out = pipeline.retitle(conn, clip_id, "Call it now: red, blue or green on the drums")
    assert out["pushed"] is False and out["needs_manual_update"] is True and "quota" in out["push_error"]


def test_a_manual_channel_still_asks_for_a_trip_to_studio(fake):
    with db.connect() as conn:
        channels.create(conn, name="Manual", channel_id="hand", driver="manual")
    clip_id = a_clip(channel="hand")
    with db.connect() as conn:
        db.update(conn, clip_id, status=PUBLISHED, remote_id="abc")
        out = pipeline.retitle(conn, clip_id, "Call it now: red, blue or green on the drums")
    assert out["pushed"] is False and out["needs_manual_update"] is True


# --- reading the numbers back --------------------------------------------------------

def test_metrics_come_back_with_the_derived_swipe_away(fake, monkeypatch):
    ch, calls, results = fake
    driver = yt.YouTubePublisher(ch)
    results_by_call = []

    def query(**kwargs):
        results_by_call.append(kwargs["metrics"])
        rows = {"averageViewPercentage": {"rows": [[71.5]]},
                "audienceWatchRatio": {"rows": [[0.0, 0.62], [0.05, 0.4]]}}[kwargs["metrics"]]
        return FakeRequest(calls, "reports.query", kwargs, rows)

    service = FakeService(calls, results)
    monkey = type("S", (), {"reports": lambda self: type("R", (), {"query": staticmethod(query)})(),
                            "videos": lambda self: FakeCollection(calls, "videos", results)})()
    monkeypatch.setattr(yt, "_service", lambda name, version, token_path, interactive=False: monkey)
    metrics = driver.fetch_metrics("vid123")
    assert metrics.views == 1500 and metrics.likes == 42
    assert metrics.avg_view_pct == 71.5
    assert metrics.swipe_away_pct == 38.0  # (1 - 0.62) * 100
    assert results_by_call == ["averageViewPercentage", "audienceWatchRatio"]


# --- connecting is a person's job -----------------------------------------------------

def test_without_a_token_nothing_uploads_and_the_error_says_what_to_run(sandbox):
    with db.connect() as conn:
        db.migrate(conn)
        channels.create(conn, name="Gravity Lab", channel_id="main", driver="youtube")
        ch = channels.get(conn, "main")
    driver = yt.YouTubePublisher(ch)
    assert driver.connected() is False
    with pytest.raises(yt.NotConnected, match="factory youtube connect"):
        yt._credentials(ch.token_path, interactive=False)
    status = driver.status()
    assert status["connected"] is False and status["uploads_per_day"] == 6


def test_status_names_the_account_once_connected(fake):
    ch, calls, _ = fake
    status = yt.YouTubePublisher(ch).status()
    assert status["connected"] is True and status["account"]["title"] == "Gravity Lab"
    assert status["account"]["subscribers"] == 310


def test_disconnect_forgets_the_token(fake):
    ch, _, _ = fake
    driver = yt.YouTubePublisher(ch)
    assert driver.disconnect() is True and not ch.token_path.exists()
    assert driver.disconnect() is False


def test_quota_errors_are_explained_in_what_to_do(sandbox):
    assert "resets at midnight Pacific" in yt._explain(RuntimeError("quotaExceeded: ..."))
    assert "connect" in yt._explain(RuntimeError("invalid_grant"))


def test_the_api_serves_the_status_and_refuses_nothing_else(fake):
    from fastapi.testclient import TestClient
    from factory import web

    with TestClient(web.app) as client:
        body = client.get("/api/youtube?channel=main").json()
        assert body["connected"] is True and body["driver"] == "youtube" and body["slot"]
        out = client.post("/api/youtube/disconnect", json={"channel": "main"}).json()
        assert out["connected"] is False
