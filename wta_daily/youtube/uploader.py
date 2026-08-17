"""Optional Phase 3: publishes the finished daily video to YouTube via the
official YouTube Data API v3 - never Selenium, browser automation, or
YouTube Studio scripting.

Mirrors :mod:`wta_daily.git_automation`'s shape: a single, optional,
isolated final pipeline stage, entirely gated by config, with its own
narrow exception types, that can never take down the rest of a run if it
fails (see :func:`publish_report`'s docstring for the full failure-mode
contract).

This module consumes artifacts already produced by earlier phases
(``video.mp4``, ``thumbnail.png``, ``youtube_description.txt``, the
canonical title from :mod:`wta_daily.title`) - it never regenerates any of
them itself.
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
from wta_daily.persistence.youtube_upload_store import YouTubeUploadStore
from wta_daily.title import generate_title
from wta_daily.youtube.auth import get_credentials

logger = logging.getLogger(__name__)


class YouTubeUploadError(WtaDailyError):
    """Raised (internally - callers should prefer :class:`YouTubePublishResult`)
    when the video or thumbnail upload call itself fails."""


@dataclass
class YouTubePublishResult:
    """The outcome of one :func:`publish_report` call - deliberately a
    plain return value rather than a raised exception for every non-success
    case, since "YouTube publishing failed" must never look like "the whole
    pipeline run failed" to a caller (see the module docstring)."""

    #: "disabled" | "skipped_duplicate" | "success" | "failed"
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
    """Construct an authenticated ``googleapiclient`` YouTube resource.

    Only ever called when ``config.enabled`` is ``True``. The
    ``google-api-python-client`` import is deferred here (rather than at
    module level) so merely importing :mod:`wta_daily.youtube.uploader`
    never requires it to be installed - see the package docstring.
    """

    try:
        from googleapiclient.discovery import build
    except ImportError as exc:  # pragma: no cover - exercised only without the optional deps
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


def publish_report(
    report: DailyReport,
    store: DailyOutputStore,
    config: YouTubeConfig,
    upload_store: YouTubeUploadStore,
    *,
    force: bool = False,
    client_factory: Callable[[YouTubeConfig], Any] = build_client,
) -> YouTubePublishResult:
    """Upload one day's finished video package to YouTube.

    Failure contract (see the "Phase 3" brief this implements):

    * If ``config.enabled`` is ``False``, returns immediately with
      ``status="disabled"`` - no credential loading, no import of any
      Google library, no network call. This is the default and must stay
      side-effect-free.
    * If this exact ``(report.report_date, report.tour)`` was already
      uploaded successfully (see :class:`~wta_daily.persistence.youtube_upload_store.YouTubeUploadStore`),
      returns ``status="skipped_duplicate"`` without uploading again,
      unless ``force=True``.
    * A video-upload failure never deletes/regenerates any local artifact
      (``video.mp4``, ``thumbnail.png``, etc.) - it simply returns
      ``status="failed"`` with ``video_error`` set, and nothing is
      recorded in ``upload_store`` (so a later retry is treated as a fresh
      attempt, not a duplicate).
    * A *thumbnail* failure after a *successful* video upload is reported
      separately (``thumbnail_error`` set, ``status`` stays ``"success"``)
      - the video is never re-uploaded just because the thumbnail step
      failed, and the successful video upload is still recorded.
    """

    if not config.enabled:
        logger.debug("YouTube publishing is disabled (youtube.enabled: false); skipping.")
        return YouTubePublishResult(status="disabled", message="youtube.enabled is false")

    existing = upload_store.get_upload(report.report_date, report.tour)
    if existing is not None and not force:
        message = (
            f"YouTube upload skipped: report for {report.report_date.isoformat()} "
            f"already uploaded as {existing.video_id}"
        )
        logger.info(message)
        return YouTubePublishResult(
            status="skipped_duplicate",
            video_id=existing.video_id,
            video_url=existing.video_url,
            message=message,
        )

    if not store.video_path.exists():
        message = f"No video found at {store.video_path}; cannot publish to YouTube."
        logger.error(message)
        return YouTubePublishResult(status="failed", video_error=message)

    title = generate_title(report)
    description = _read_text_or_none(store.youtube_description_path) or ""

    logger.info("YouTube publishing enabled")
    logger.info("Uploading video...")
    try:
        client = client_factory(config)
        video_id = _upload_video(
            client,
            store.video_path,
            title=title,
            description=description,
            category_id=config.category_id,
            privacy_status=config.privacy,
        )
    except Exception as exc:  # noqa: BLE001 - a publishing failure must never crash the run
        logger.error("YouTube video upload failed: %s", exc)
        return YouTubePublishResult(status="failed", video_error=str(exc))

    video_url = f"https://www.youtube.com/watch?v={video_id}"
    logger.info("Video uploaded successfully")
    logger.info("YouTube video ID: %s", video_id)
    logger.info("YouTube URL: %s", video_url)

    result = YouTubePublishResult(status="success", video_id=video_id, video_url=video_url)

    if store.thumbnail_path.exists():
        logger.info("Uploading custom thumbnail...")
        try:
            _set_thumbnail(client, video_id, store.thumbnail_path)
            result.thumbnail_uploaded = True
            logger.info("Thumbnail uploaded successfully")
        except Exception as exc:  # noqa: BLE001 - the video upload above already succeeded
            result.thumbnail_error = str(exc)
            logger.error("Thumbnail upload failed (video %s uploaded fine): %s", video_id, exc)
    else:
        logger.info("No thumbnail found at %s; skipping thumbnail upload.", store.thumbnail_path)

    upload_store.record_upload(
        report.report_date, report.tour, video_id=video_id, video_url=video_url, title=title
    )
    return result
