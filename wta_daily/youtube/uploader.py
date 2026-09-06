"""Optional YouTube publishing via the official YouTube Data API v3.

This module consumes already-generated artifacts. It never regenerates data,
narration, titles, descriptions, graphics, or video. Standard landscape and
vertical Short uploads are tracked independently.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from wta_daily.config import YouTubeConfig
from wta_daily.exceptions import WtaDailyError
from wta_daily.models import DailyReport
from wta_daily.persistence.report_store import DailyOutputStore
from wta_daily.persistence.youtube_upload_store import (
    LANDSCAPE_VARIANT,
    VERTICAL_VARIANT,
    YouTubeUploadStore,
)
from wta_daily.title import generate_title
from wta_daily.youtube.auth import get_credentials

logger = logging.getLogger(__name__)


class YouTubeUploadError(WtaDailyError):
    """Raised internally when the video or thumbnail upload call fails."""


@dataclass
class YouTubePublishResult:
    """Outcome of one publish attempt."""

    status: str
    video_id: str | None = None
    video_url: str | None = None
    video_error: str | None = None
    thumbnail_uploaded: bool = False
    thumbnail_error: str | None = None
    message: str | None = None

    @property
    def ok(self) -> bool:
        return self.status in {"disabled", "skipped_duplicate", "success"}


def build_client(config: YouTubeConfig) -> Any:
    try:
        from googleapiclient.discovery import build
    except ImportError as exc:  # pragma: no cover
        raise YouTubeUploadError(
            "YouTube publishing requires the optional google-api-python-client package, "
            "which is not installed. Run: pip install -r requirements-youtube.txt "
            "(see README.md's 'YouTube publishing' section)."
        ) from exc

    credentials = get_credentials(config)
    return build("youtube", "v3", credentials=credentials, cache_discovery=False)


def _upload_video(
    client: Any,
    video_path: Path,
    *,
    title: str,
    description: str,
    category_id: str,
    privacy_status: str,
) -> str:
    from googleapiclient.http import MediaFileUpload

    body = {
        "snippet": {"title": title, "description": description, "categoryId": category_id},
        "status": {"privacyStatus": privacy_status},
    }
    media = MediaFileUpload(str(video_path), mimetype="video/mp4", chunksize=-1, resumable=True)
    request = client.videos().insert(part="snippet,status", body=body, media_body=media)

    response = None
    while response is None:
        _status, response = request.next_chunk()
    return str(response["id"])


def _set_thumbnail(client: Any, video_id: str, thumbnail_path: Path) -> None:
    from googleapiclient.http import MediaFileUpload

    media = MediaFileUpload(str(thumbnail_path), mimetype="image/png")
    client.thumbnails().set(videoId=video_id, media_body=media).execute()


def _read_text_or_none(path: Path) -> str | None:
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8")


def _video_path_for_variant(store: DailyOutputStore, variant: str) -> Path:
    if variant == LANDSCAPE_VARIANT:
        return store.video_path
    if variant == VERTICAL_VARIANT:
        return store.root / "vertical" / "video.mp4"
    raise ValueError(f"Unsupported YouTube upload variant: {variant!r}")


def publish_report(
    report: DailyReport,
    store: DailyOutputStore,
    config: YouTubeConfig,
    upload_store: YouTubeUploadStore,
    *,
    force: bool = False,
    variant: str = LANDSCAPE_VARIANT,
    client_factory: Callable[[YouTubeConfig], Any] = build_client,
) -> YouTubePublishResult:
    """Upload one already-generated video package to YouTube.

    ``variant='landscape'`` preserves the existing behavior, including the
    custom thumbnail. ``variant='vertical'`` uploads
    ``output/<date>/vertical/video.mp4`` with the same title and description
    and deliberately skips the landscape thumbnail. Each variant has its own
    duplicate-protection record.
    """

    if not config.enabled:
        logger.debug("YouTube publishing is disabled (youtube.enabled: false); skipping.")
        return YouTubePublishResult(status="disabled", message="youtube.enabled is false")

    video_path = _video_path_for_variant(store, variant)
    existing = upload_store.get_upload(report.report_date, report.tour, variant)
    if existing is not None and not force:
        message = (
            f"YouTube {variant} upload skipped: report for {report.report_date.isoformat()} "
            f"already uploaded as {existing.video_id}"
        )
        logger.info(message)
        return YouTubePublishResult(
            status="skipped_duplicate",
            video_id=existing.video_id,
            video_url=existing.video_url,
            message=message,
        )

    if not video_path.exists():
        message = f"No {variant} video found at {video_path}; cannot publish to YouTube."
        logger.error(message)
        return YouTubePublishResult(status="failed", video_error=message)

    # The vertical upload deliberately reuses the completed run's existing
    # title/description. Landscape keeps its historical title fallback.
    saved_title = _read_text_or_none(store.title_path)
    title = (saved_title.strip() if saved_title else None) or generate_title(report)
    description = _read_text_or_none(store.youtube_description_path) or ""

    logger.info("YouTube publishing enabled (%s)", variant)
    logger.info("Uploading %s video...", variant)
    try:
        client = client_factory(config)
        video_id = _upload_video(
            client,
            video_path,
            title=title,
            description=description,
            category_id=config.category_id,
            privacy_status=config.privacy,
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("YouTube %s video upload failed: %s", variant, exc)
        return YouTubePublishResult(status="failed", video_error=str(exc))

    video_url = f"https://www.youtube.com/watch?v={video_id}"
    logger.info("%s video uploaded successfully", variant.capitalize())
    logger.info("YouTube video ID: %s", video_id)
    logger.info("YouTube URL: %s", video_url)

    result = YouTubePublishResult(status="success", video_id=video_id, video_url=video_url)

    if variant == LANDSCAPE_VARIANT:
        if store.thumbnail_path.exists():
            logger.info("Uploading custom thumbnail...")
            try:
                _set_thumbnail(client, video_id, store.thumbnail_path)
                result.thumbnail_uploaded = True
                logger.info("Thumbnail uploaded successfully")
            except Exception as exc:  # noqa: BLE001
                result.thumbnail_error = str(exc)
                logger.error("Thumbnail upload failed (video %s uploaded fine): %s", video_id, exc)
        else:
            logger.info("No thumbnail found at %s; skipping thumbnail upload.", store.thumbnail_path)
    else:
        logger.info("Vertical upload: skipping landscape custom thumbnail.")

    upload_store.record_upload(
        report.report_date,
        report.tour,
        video_id=video_id,
        video_url=video_url,
        title=title,
        variant=variant,
    )
    return result
