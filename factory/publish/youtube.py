"""YouTube driver — turn this on in week 3, not week 1.

Needs the optional extras and an OAuth client:

    pip install -e '.[youtube]'

Create a Desktop-app OAuth client in Google Cloud Console for a project with
both "YouTube Data API v3" and "YouTube Analytics API" enabled, download it as
client_secrets.json into the repo root, then run any command that publishes; a
browser window will ask you to authorise once and the token is cached in
token.json. Both files are gitignored.

A note on the retention number: YouTube has no "swipe-away" metric. What this
reads is audienceWatchRatio in the first 2% of the clip, and swipe_away_pct is
derived as (1 - that ratio) * 100. It tracks the thing the strategy cares about,
but it is not an official figure and it is not comparable to anyone else's.
"""

from __future__ import annotations

from pathlib import Path

from ..settings import ROOT
from .base import Metrics, PublishResult

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
]
CLIENT_SECRETS = ROOT / "client_secrets.json"
TOKEN = ROOT / "token.json"


def _credentials():
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError as exc:  # pragma: no cover - optional extra
        raise RuntimeError("install the youtube extra: pip install -e '.[youtube]'") from exc

    creds = None
    if TOKEN.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN), SCOPES)
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    if not creds or not creds.valid:
        if not CLIENT_SECRETS.exists():
            raise RuntimeError(f"missing {CLIENT_SECRETS}; see this module's docstring")
        flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_SECRETS), SCOPES)
        creds = flow.run_local_server(port=0)
    TOKEN.write_text(creds.to_json())
    return creds


def _service(name: str, version: str):
    from googleapiclient.discovery import build

    return build(name, version, credentials=_credentials(), cache_discovery=False)


class YouTubePublisher:
    name = "youtube"

    def publish(
        self,
        *,
        clip_id: str,
        video_path: Path,
        title: str,
        description: str,
        hashtags: list[str],
    ) -> PublishResult:
        from googleapiclient.http import MediaFileUpload

        body = {
            "snippet": {
                "title": title,
                "description": f"{description}\n\n{' '.join(hashtags)}",
                "tags": [tag.lstrip("#") for tag in hashtags],
                "categoryId": "24",  # Entertainment
            },
            # Uploads land private. Flipping a clip to public stays a human act.
            "status": {"privacyStatus": "private", "selfDeclaredMadeForKids": False},
        }
        media = MediaFileUpload(str(video_path), mimetype="video/mp4", resumable=True)
        request = _service("youtube", "v3").videos().insert(
            part="snippet,status", body=body, media_body=media
        )
        response = None
        while response is None:
            _, response = request.next_chunk()
        return PublishResult(
            platform="youtube",
            remote_id=response["id"],
            note="uploaded as private; set it public in Studio when you are ready",
        )

    def fetch_metrics(self, remote_id: str) -> Metrics:
        stats = (
            _service("youtube", "v3")
            .videos()
            .list(part="statistics", id=remote_id)
            .execute()
        )
        items = stats.get("items") or []
        if not items:
            raise RuntimeError(f"video {remote_id} not found")
        statistics = items[0]["statistics"]

        analytics = _service("youtubeAnalytics", "v2")
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
