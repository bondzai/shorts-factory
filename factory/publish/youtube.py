"""YouTube driver: upload, schedule, comment, retitle, read the numbers back.

What it does, and what it deliberately does not.

  Uploads          the approved clip, with its title, description, tags and
                   #Shorts, as **private with a publishAt** — the schedule
                   slot the factory already computes (06:00 Bangkok by
                   default, the US-evening window). YouTube flips it public
                   at that minute. Nothing is ever uploaded straight to
                   public unless the operator sets publish.youtube_privacy
                   to "public" on purpose.

  Pins the ask     posts the clip's comment question as a top comment, so
                   the thing the strategy asks for is there when the first
                   viewer arrives. The API cannot pin a comment; the note
                   comes back saying so, and pinning is two taps in Studio.

  Pushes retitles  a retitle of a published clip becomes a videos.update,
                   so the gauge the Results screen keeps (what each title
                   earned) is not a trip to Studio and back.

  Reads back       views and likes from the Data API, average view
                   percentage and a swipe-away figure from Analytics.

  Never            makes a clip public early, deletes anything, touches a
                   video the factory did not upload, or runs without the
                   operator having connected the channel by hand.

Setup, once per channel:

    pip install -e '.[youtube]'
    # a Desktop-app OAuth client from a Google Cloud project with the
    # YouTube Data API v3 and YouTube Analytics API enabled
    cp ~/Downloads/client_secret_*.json client_secrets.json
    factory youtube connect --channel main      # opens a browser, once

The browser step is the operator's: the factory never sees the password,
and the token it stores is that one channel's. Tokens live at
channels/<id>/token.json and are gitignored, as is client_secrets.json.
Authorise each channel while signed in to that channel's account — one
token per channel is the whole point.

Quota: an upload costs 1600 units against a default 10,000 a day, so about
six uploads a day per Google Cloud project. `factory youtube status` says
what has been spent since midnight Pacific, which is when the quota resets.

A note on the retention number: YouTube has no "swipe-away" metric. What
this reads is audienceWatchRatio in the first 2% of the clip, and
swipe_away_pct is derived as (1 - that ratio) * 100. It tracks the thing
the strategy cares about, but it is not an official figure and it is not
comparable to anyone else's.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .. import logs, settings
from ..settings import ROOT
from .base import Metrics, PublishResult

# force-ssl is what lets the factory post the clip's question as a comment
# and push a retitle to a video it uploaded. Without it the driver can only
# upload and read; with it, the loop closes. Ask for it once, at connect.
SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.force-ssl",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
]
CLIENT_SECRETS = ROOT / "client_secrets.json"
UPLOAD_UNITS = 1600  # what one upload costs against the daily quota
CHUNK = 4 * 1024 * 1024


class NotConnected(RuntimeError):
    """No token for this channel yet, and nobody is here to sign in."""


def _config() -> dict[str, Any]:
    return dict(settings.load().raw.get("publish", {}))


def _open_in(browser: str, url: str) -> None:
    """Open the consent page in a named browser, private window.

    The default browser is signed in to whichever Google accounts it is
    signed in to, and the consent screen then offers that account's
    channels. A fresh private window is the only reliable way to be asked
    which account to use.
    """
    import subprocess

    apps = {"chrome": ("Google Chrome", "--incognito"), "safari": ("Safari", None),
            "firefox": ("Firefox", "-private-window"), "edge": ("Microsoft Edge", "--inprivate")}
    app, flag = apps.get(browser, (browser, None))
    cmd = ["open", "-na", app, "--args"] + ([flag] if flag else []) + [url]
    subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _credentials(token_path: Path, *, interactive: bool = False, open_browser: bool = True,
                 browser: str | None = None):
    """The channel's credentials, refreshed if stale.

    `interactive` is the difference between a background upload and the
    operator sitting at the machine: only a person can complete Google's
    consent screen, so everything else refuses rather than opening a browser
    nobody is looking at.
    """
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError as exc:  # pragma: no cover - optional extra
        raise RuntimeError("install the youtube extra: pip install -e '.[youtube]'") from exc

    creds = None
    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    if not creds or not creds.valid:
        if not interactive:
            raise NotConnected(
                f"{token_path.parent.name} is not connected to YouTube. Run "
                f"`factory youtube connect --channel {token_path.parent.name}` "
                f"at the machine — it opens a browser once."
            )
        if not CLIENT_SECRETS.exists():
            raise RuntimeError(
                f"missing {CLIENT_SECRETS.name}: download a Desktop-app OAuth client from "
                f"the Google Cloud project that has YouTube Data API v3 and YouTube "
                f"Analytics API enabled, and save it as {CLIENT_SECRETS}"
            )
        flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_SECRETS), SCOPES)
        # open_browser=False prints the URL instead of opening one. The
        # machine's default browser is signed in to whichever Google accounts
        # it is signed in to, which is not always the one that owns the
        # channel: the consent screen then offers the wrong brand accounts.
        # Pasting the URL into the right browser profile fixes that.
        if browser:
            # run_local_server picks the port, so the URL only exists inside
            # it: hand it a browser opener of our own.
            import webbrowser

            class _Named:
                def open(self, url, *a, **k):
                    _open_in(browser, url)
                    return True

            webbrowser.register(f"factory-{browser}", None, _Named(), preferred=True)
        creds = flow.run_local_server(
            port=0, prompt="consent", open_browser=open_browser or bool(browser),
            authorization_prompt_message=(
                "" if open_browser else
                "Open this in the browser signed in to the account that owns the channel:\n\n{url}\n"
            ),
        )
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(creds.to_json())
    token_path.chmod(0o600)
    return creds


def _service(name: str, version: str, token_path: Path, *, interactive: bool = False):
    from googleapiclient.discovery import build

    return build(
        name, version, credentials=_credentials(token_path, interactive=interactive),
        cache_discovery=False,
    )


def _description(description: str, hashtags: list[str], comment: str | None) -> str:
    """What sits under the video. #Shorts last, and never the pinned ask —
    that is a comment, where a viewer can answer it."""
    tags = " ".join(dict.fromkeys([*hashtags, "#Shorts"]))
    return f"{description}\n\n{tags}".strip()


def _publish_at(when: datetime | None = None) -> str | None:
    """RFC 3339 for the next upload slot, or None to leave it private.

    The slot is the one the whole factory already agrees on (publish.best_time
    in publish.timezone), so a scheduled upload and the "Copy for upload"
    text can never disagree about when a clip goes out.
    """
    from .. import schedule

    mode = str(_config().get("youtube_privacy", "scheduled")).lower()
    if mode != "scheduled":
        return None
    slot = when or schedule.next_slot()
    return slot.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


class YouTubePublisher:
    name = "youtube"

    def __init__(self, channel) -> None:
        # One token per channel. Sharing one would publish to whichever
        # account authorised last, which is the kind of mistake you find out
        # about from a viewer.
        self.channel = channel
        self.token_path = channel.token_path

    # --- connection -----------------------------------------------------------

    def connected(self) -> bool:
        return self.token_path.exists()

    def connect(self, *, open_browser: bool = True, browser: str | None = None) -> dict[str, Any]:
        """Run the consent flow. Only ever called by a person at the machine."""
        _credentials(self.token_path, interactive=True, open_browser=open_browser, browser=browser)
        who = self.whoami()
        logs.event("youtube.connected", channel=self.channel.id, remote_channel=who.get("id"),
                   title=who.get("title"))
        return who

    def disconnect(self) -> bool:
        """Forget this channel's token. The grant itself lives in the Google
        account and is revoked there; this only stops the factory using it."""
        if not self.token_path.exists():
            return False
        self.token_path.unlink()
        logs.event("youtube.disconnected", channel=self.channel.id)
        return True

    def whoami(self) -> dict[str, Any]:
        """Which YouTube channel this token belongs to."""
        items = (
            _service("youtube", "v3", self.token_path)
            .channels()
            .list(part="snippet,statistics", mine=True)
            .execute()
        ).get("items") or []
        if not items:
            raise RuntimeError("this token has no YouTube channel behind it")
        item = items[0]
        stats = item.get("statistics", {})
        return {
            "id": item["id"],
            "title": item["snippet"]["title"],
            "handle": item["snippet"].get("customUrl"),
            "subscribers": int(stats.get("subscriberCount", 0)) if stats.get("subscriberCount") else None,
            "videos": int(stats.get("videoCount", 0)) if stats.get("videoCount") else None,
        }

    # --- publishing -------------------------------------------------------------

    def publish(
        self,
        *,
        clip_id: str,
        video_path: Path,
        title: str,
        description: str,
        hashtags: list[str],
        comment: str | None = None,
        publish_at: datetime | None = None,
    ) -> PublishResult:
        from googleapiclient.http import MediaFileUpload

        cfg = _config()
        when = _publish_at(publish_at)
        status: dict[str, Any] = {
            # Private until its slot. A clip is never uploaded straight to
            # public unless someone changed the setting on purpose.
            "privacyStatus": "public" if str(cfg.get("youtube_privacy")) == "public" else "private",
            "selfDeclaredMadeForKids": bool(cfg.get("youtube_made_for_kids", False)),
        }
        if when and status["privacyStatus"] == "private":
            status["publishAt"] = when
        body = {
            "snippet": {
                "title": title,
                "description": _description(description, hashtags, comment),
                "tags": [tag.lstrip("#") for tag in hashtags][:15],
                "categoryId": str(cfg.get("youtube_category_id", "24")),  # 24 = Entertainment
                "defaultLanguage": str(cfg.get("youtube_language", "en")),
            },
            "status": status,
        }
        media = MediaFileUpload(str(video_path), mimetype="video/mp4", resumable=True, chunksize=CHUNK)
        request = _service("youtube", "v3", self.token_path).videos().insert(
            part="snippet,status", body=body, media_body=media, notifySubscribers=bool(cfg.get("youtube_notify_subscribers", True)),
        )
        logs.event("youtube.upload_started", channel=self.channel.id, clip=clip_id,
                   scheduled_for=when, privacy=status["privacyStatus"])
        response = None
        while response is None:
            try:
                progress, response = request.next_chunk()
            except Exception as exc:  # one place to turn Google's errors into advice
                raise RuntimeError(_explain(exc)) from None
            if progress is not None:
                logs.event("youtube.upload_progress", level="debug", channel=self.channel.id,
                           clip=clip_id, percent=round(progress.progress() * 100))
        video_id = response["id"]
        note = (f"uploaded private, goes public {when}" if when else
                f"uploaded as {status['privacyStatus']}")
        if comment and cfg.get("youtube_post_comment", True):
            note += "; " + self._comment(video_id, comment)
        logs.event("youtube.uploaded", channel=self.channel.id, clip=clip_id,
                   remote_id=video_id, scheduled_for=when)
        return PublishResult(platform="youtube", remote_id=video_id, note=note)

    def _comment(self, video_id: str, text: str) -> str:
        """The clip's question, as a top comment. The API cannot pin it."""
        try:
            _service("youtube", "v3", self.token_path).commentThreads().insert(
                part="snippet",
                body={"snippet": {"videoId": video_id,
                                  "topLevelComment": {"snippet": {"textOriginal": text}}}},
            ).execute()
        except Exception as exc:
            logs.event("youtube.comment_failed", level="warn", channel=self.channel.id,
                       remote_id=video_id, error=str(exc)[:200])
            return f"the comment did not post ({str(exc)[:80]})"
        return "comment posted — pin it in Studio, the API cannot"

    def update_metadata(self, remote_id: str, *, title: str | None = None,
                        description: str | None = None, hashtags: list[str] | None = None) -> bool:
        """Push a retitle to a video this factory uploaded."""
        service = _service("youtube", "v3", self.token_path)
        items = (service.videos().list(part="snippet", id=remote_id).execute()).get("items") or []
        if not items:
            raise RuntimeError(f"video {remote_id} not found")
        snippet = items[0]["snippet"]
        if title:
            snippet["title"] = title
        if description is not None:
            snippet["description"] = _description(description, hashtags or [], None)
        service.videos().update(part="snippet", body={"id": remote_id, "snippet": snippet}).execute()
        logs.event("youtube.retitled", channel=self.channel.id, remote_id=remote_id, title=title)
        return True

    # --- reading back -------------------------------------------------------------

    def fetch_metrics(self, remote_id: str) -> Metrics:
        stats = (
            _service("youtube", "v3", self.token_path)
            .videos()
            .list(part="statistics", id=remote_id)
            .execute()
        )
        items = stats.get("items") or []
        if not items:
            raise RuntimeError(f"video {remote_id} not found")
        statistics = items[0]["statistics"]

        analytics = _service("youtubeAnalytics", "v2", self.token_path)
        summary = analytics.reports().query(
            ids="channel==MINE",
            startDate="2005-01-01",
            endDate="2100-01-01",
            metrics="averageViewPercentage",
            filters=f"video=={remote_id}",
        ).execute()
        rows = summary.get("rows") or [[None]]
        avg_view_pct = rows[0][0]

        retention = analytics.reports().query(
            ids="channel==MINE",
            startDate="2005-01-01",
            endDate="2100-01-01",
            metrics="audienceWatchRatio",
            dimensions="elapsedVideoTimeRatio",
            filters=f"video=={remote_id}",
        ).execute()
        swipe_away = None
        for elapsed, ratio in retention.get("rows") or []:
            if elapsed is not None and elapsed <= 0.02 and ratio is not None:
                swipe_away = round((1.0 - float(ratio)) * 100, 2)
                break

        return Metrics(
            views=int(statistics.get("viewCount", 0)),
            likes=int(statistics.get("likeCount", 0)),
            avg_view_pct=avg_view_pct,
            swipe_away_pct=swipe_away,
        )

    def status(self) -> dict[str, Any]:
        """What the console shows: connected, as whom, and what it costs."""
        out: dict[str, Any] = {
            "channel": self.channel.id,
            "connected": self.connected(),
            "client_secrets": CLIENT_SECRETS.exists(),
            "privacy": str(_config().get("youtube_privacy", "scheduled")),
            "upload_units": UPLOAD_UNITS,
            "uploads_per_day": 10000 // UPLOAD_UNITS,
        }
        if not out["connected"]:
            return out
        try:
            out["account"] = self.whoami()
        except Exception as exc:
            out["error"] = str(exc)[:200]
        return out


def _explain(exc: Exception) -> str:
    """Google's errors, in the words of what to do about them."""
    text = str(exc)
    if "quotaExceeded" in text or "uploadLimitExceeded" in text:
        return ("YouTube's daily quota is spent (an upload costs 1600 of 10,000 units, "
                "about six a day). It resets at midnight Pacific; the rest of the queue "
                "can wait until then.")
    if "youtubeSignupRequired" in text:
        return "that Google account has no YouTube channel yet"
    if "forbidden" in text.lower() and "comment" in text.lower():
        return "the channel does not allow comments from the API"
    if "invalid_grant" in text:
        return "the stored token is no longer valid — run `factory youtube connect` again"
    return text[:400]
