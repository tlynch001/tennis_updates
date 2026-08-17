"""Tests for wta_daily.youtube.uploader's orchestration logic.

None of these tests make a real network call or require real Google
credentials: the two functions that actually talk to the YouTube API
(``_upload_video``/``_set_thumbnail``) are monkeypatched out, and
``client_factory`` is injected as a stand-in for the real, credential-
requiring ``build_client`` - exactly the seam the module exposes for this
purpose (see ``publish_report``'s ``client_factory`` parameter).
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from wta_daily.config import YouTubeConfig
from wta_daily.models import DailyReport, Movement, PlayerReport
from wta_daily.persistence.report_store import DailyOutputStore
from wta_daily.persistence.youtube_upload_store import YouTubeUploadStore
from wta_daily.youtube import uploader


def _report(report_date: date = date(2026, 8, 17)) -> DailyReport:
    players = [
        PlayerReport(
            rank=i,
            name=f"Player {i}",
            player_id=f"p{i}",
            country_code="USA",
            points=1000 - i,
            movement=Movement.SAME,
        )
        for i in range(1, 3)
    ]
    return DailyReport(report_date=report_date, tour="wta", players=players)


def _store_with_video(tmp_path: Path, report_date: date = date(2026, 8, 17)) -> DailyOutputStore:
    store = DailyOutputStore(tmp_path / "output", report_date)
    store.ensure_dirs()
    store.video_path.write_bytes(b"fake mp4 bytes")
    store.write_youtube_description("A great day of tennis.")
    store.thumbnail_path.write_bytes(b"fake png bytes")
    return store


class _FakeClient:
    """Sentinel object standing in for a real googleapiclient YouTube
    resource - tests only need to confirm the exact instance returned by
    client_factory flows through to _upload_video/_set_thumbnail, never
    that it behaves like a real API client."""


def test_publish_report_disabled_never_touches_disk_or_calls_anything(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = YouTubeConfig(enabled=False)
    store = _store_with_video(tmp_path)
    upload_store = YouTubeUploadStore(tmp_path / "data")

    def _boom(*_a: object, **_kw: object) -> None:
        raise AssertionError("must not be called when disabled")

    monkeypatch.setattr(uploader, "build_client", _boom)
    monkeypatch.setattr(uploader, "_upload_video", _boom)
    monkeypatch.setattr(uploader, "_set_thumbnail", _boom)

    result = uploader.publish_report(_report(), store, config, upload_store)

    assert result.status == "disabled"
    assert not upload_store.path.exists()


def test_publish_report_uploads_video_captures_id_and_applies_thumbnail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = YouTubeConfig(enabled=True, privacy="unlisted", category_id="17")
    store = _store_with_video(tmp_path)
    upload_store = YouTubeUploadStore(tmp_path / "data")
    fake_client = _FakeClient()

    upload_calls = []
    thumbnail_calls = []

    def fake_upload_video(client: object, video_path: Path, **kwargs: object) -> str:
        assert client is fake_client
        upload_calls.append((video_path, kwargs))
        return "abc123"

    def fake_set_thumbnail(client: object, video_id: str, thumbnail_path: Path) -> None:
        assert client is fake_client
        thumbnail_calls.append((video_id, thumbnail_path))

    monkeypatch.setattr(uploader, "_upload_video", fake_upload_video)
    monkeypatch.setattr(uploader, "_set_thumbnail", fake_set_thumbnail)

    result = uploader.publish_report(
        _report(), store, config, upload_store, client_factory=lambda _config: fake_client
    )

    assert result.status == "success"
    assert result.video_id == "abc123"
    assert result.video_url == "https://www.youtube.com/watch?v=abc123"
    assert result.thumbnail_uploaded is True
    assert result.thumbnail_error is None

    # 1. video uploaded, with the canonical title/description/category/privacy
    assert len(upload_calls) == 1
    _video_path, kwargs = upload_calls[0]
    assert kwargs["title"] == "WTA Top 2 Update \u2014 August 17, 2026"
    assert kwargs["description"] == "A great day of tennis.\n"
    assert kwargs["category_id"] == "17"
    assert kwargs["privacy_status"] == "unlisted"

    # 2. + 3. returned video ID captured and used for the thumbnail call
    assert thumbnail_calls == [("abc123", store.thumbnail_path)]

    # 4. successful upload metadata recorded
    record = upload_store.get_upload(date(2026, 8, 17), "wta")
    assert record is not None
    assert record.video_id == "abc123"
    assert record.video_url == "https://www.youtube.com/watch?v=abc123"


def test_publish_report_skips_duplicate_upload_by_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = YouTubeConfig(enabled=True)
    store = _store_with_video(tmp_path)
    upload_store = YouTubeUploadStore(tmp_path / "data")
    upload_store.record_upload(
        date(2026, 8, 17), "wta", video_id="already-uploaded", video_url="https://x/already", title="t"
    )

    def _boom(*_a: object, **_kw: object) -> None:
        raise AssertionError("must not upload again")

    monkeypatch.setattr(uploader, "_upload_video", _boom)

    result = uploader.publish_report(_report(), store, config, upload_store)

    assert result.status == "skipped_duplicate"
    assert result.video_id == "already-uploaded"
    assert "already uploaded as already-uploaded" in (result.message or "")


def test_publish_report_force_reuploads_a_duplicate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = YouTubeConfig(enabled=True)
    store = _store_with_video(tmp_path)
    upload_store = YouTubeUploadStore(tmp_path / "data")
    upload_store.record_upload(
        date(2026, 8, 17), "wta", video_id="old-video", video_url="https://x/old", title="t"
    )

    fake_client = _FakeClient()
    monkeypatch.setattr(uploader, "_upload_video", lambda *a, **kw: "new-video")
    monkeypatch.setattr(uploader, "_set_thumbnail", lambda *a, **kw: None)

    result = uploader.publish_report(
        _report(), store, config, upload_store, force=True, client_factory=lambda _c: fake_client
    )

    assert result.status == "success"
    assert result.video_id == "new-video"
    assert upload_store.get_upload(date(2026, 8, 17), "wta").video_id == "new-video"  # type: ignore[union-attr]


def test_publish_report_missing_video_fails_without_calling_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = YouTubeConfig(enabled=True)
    store = DailyOutputStore(tmp_path / "output", date(2026, 8, 17))
    store.ensure_dirs()  # no video.mp4 written
    upload_store = YouTubeUploadStore(tmp_path / "data")

    def _boom(*_a: object, **_kw: object) -> None:
        raise AssertionError("must not attempt an upload with no video file")

    monkeypatch.setattr(uploader, "build_client", _boom)

    result = uploader.publish_report(_report(), store, config, upload_store)

    assert result.status == "failed"
    assert "No video found" in (result.video_error or "")
    assert upload_store.get_upload(date(2026, 8, 17), "wta") is None


def test_publish_report_video_upload_failure_does_not_delete_local_artifacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = YouTubeConfig(enabled=True)
    store = _store_with_video(tmp_path)
    upload_store = YouTubeUploadStore(tmp_path / "data")

    def failing_upload(*_a: object, **_kw: object) -> str:
        raise RuntimeError("simulated network failure")

    monkeypatch.setattr(uploader, "_upload_video", failing_upload)

    result = uploader.publish_report(
        _report(), store, config, upload_store, client_factory=lambda _c: _FakeClient()
    )

    assert result.status == "failed"
    assert "simulated network failure" in (result.video_error or "")
    # Every locally generated artifact is completely untouched.
    assert store.video_path.exists()
    assert store.thumbnail_path.exists()
    assert store.youtube_description_path.exists()
    assert upload_store.get_upload(date(2026, 8, 17), "wta") is None


def test_publish_report_thumbnail_failure_reported_separately_from_video_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = YouTubeConfig(enabled=True)
    store = _store_with_video(tmp_path)
    upload_store = YouTubeUploadStore(tmp_path / "data")

    def failing_thumbnail(*_a: object, **_kw: object) -> None:
        raise RuntimeError("simulated thumbnail failure")

    monkeypatch.setattr(uploader, "_upload_video", lambda *a, **kw: "abc123")
    monkeypatch.setattr(uploader, "_set_thumbnail", failing_thumbnail)

    result = uploader.publish_report(
        _report(), store, config, upload_store, client_factory=lambda _c: _FakeClient()
    )

    # Video upload itself is unambiguously a success...
    assert result.status == "success"
    assert result.video_id == "abc123"
    # ...while the thumbnail failure is reported distinctly, not merged in.
    assert result.thumbnail_uploaded is False
    assert "simulated thumbnail failure" in (result.thumbnail_error or "")
    # The video is still recorded as uploaded - no second upload attempt
    # should ever be triggered just because the thumbnail step failed.
    record = upload_store.get_upload(date(2026, 8, 17), "wta")
    assert record is not None
    assert record.video_id == "abc123"


def test_publish_report_skips_thumbnail_upload_when_no_thumbnail_was_generated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = YouTubeConfig(enabled=True)
    store = DailyOutputStore(tmp_path / "output", date(2026, 8, 17))
    store.ensure_dirs()
    store.video_path.write_bytes(b"fake mp4 bytes")
    # No thumbnail.png this time.
    upload_store = YouTubeUploadStore(tmp_path / "data")

    def _boom_thumbnail(*_a: object, **_kw: object) -> None:
        raise AssertionError("must not attempt a thumbnail upload with no thumbnail file")

    monkeypatch.setattr(uploader, "_upload_video", lambda *a, **kw: "abc123")
    monkeypatch.setattr(uploader, "_set_thumbnail", _boom_thumbnail)

    result = uploader.publish_report(
        _report(), store, config, upload_store, client_factory=lambda _c: _FakeClient()
    )

    assert result.status == "success"
    assert result.thumbnail_uploaded is False
    assert result.thumbnail_error is None
