"""Tests for wta_daily.youtube.uploader's orchestration logic.

None of these tests make a real network call or require real Google
credentials.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from wta_daily.config import YouTubeConfig
from wta_daily.models import DailyReport, Movement, PlayerReport
from wta_daily.persistence.report_store import DailyOutputStore
from wta_daily.persistence.youtube_upload_store import (
    LANDSCAPE_VARIANT,
    VERTICAL_VARIANT,
    YouTubeUploadStore,
)
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
    pass


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

    assert len(upload_calls) == 1
    video_path, kwargs = upload_calls[0]
    assert video_path == store.video_path
    assert kwargs["title"] == "WTA Top 2 Update — August 17, 2026"
    assert kwargs["description"] == "A great day of tennis.\n"
    assert kwargs["category_id"] == "17"
    assert kwargs["privacy_status"] == "unlisted"
    assert thumbnail_calls == [("abc123", store.thumbnail_path)]

    record = upload_store.get_upload(date(2026, 8, 17), "wta")
    assert record is not None
    assert record.video_id == "abc123"
    assert record.variant == LANDSCAPE_VARIANT


def test_vertical_upload_uses_vertical_video_same_saved_title_and_description_and_no_thumbnail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = YouTubeConfig(enabled=True, privacy="public", category_id="17")
    store = _store_with_video(tmp_path)
    vertical_path = store.root / "vertical" / "video.mp4"
    vertical_path.parent.mkdir(parents=True, exist_ok=True)
    vertical_path.write_bytes(b"vertical mp4")
    store.title_path.write_text("Exact Existing Daily Title\n", encoding="utf-8")
    fake_client = _FakeClient()
    upload_store = YouTubeUploadStore(tmp_path / "data")
    upload_calls = []

    def fake_upload_video(client: object, video_path: Path, **kwargs: object) -> str:
        assert client is fake_client
        upload_calls.append((video_path, kwargs))
        return "short123"

    def _no_thumbnail(*_a: object, **_kw: object) -> None:
        raise AssertionError("vertical upload must not set the landscape thumbnail")

    monkeypatch.setattr(uploader, "_upload_video", fake_upload_video)
    monkeypatch.setattr(uploader, "_set_thumbnail", _no_thumbnail)

    result = uploader.publish_report(
        _report(),
        store,
        config,
        upload_store,
        variant=VERTICAL_VARIANT,
        client_factory=lambda _config: fake_client,
    )

    assert result.status == "success"
    assert result.video_id == "short123"
    assert result.thumbnail_uploaded is False
    assert len(upload_calls) == 1
    video_path, kwargs = upload_calls[0]
    assert video_path == vertical_path
    assert kwargs["title"] == "Exact Existing Daily Title"
    assert kwargs["description"] == "A great day of tennis.\n"
    assert upload_store.get_upload(date(2026, 8, 17), "wta", VERTICAL_VARIANT).video_id == "short123"  # type: ignore[union-attr]
    assert upload_store.get_upload(date(2026, 8, 17), "wta", LANDSCAPE_VARIANT) is None


def test_landscape_record_does_not_block_vertical_upload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = YouTubeConfig(enabled=True)
    store = _store_with_video(tmp_path)
    vertical_path = store.root / "vertical" / "video.mp4"
    vertical_path.parent.mkdir(parents=True, exist_ok=True)
    vertical_path.write_bytes(b"vertical")
    upload_store = YouTubeUploadStore(tmp_path / "data")
    upload_store.record_upload(
        date(2026, 8, 17),
        "wta",
        video_id="wide123",
        video_url="https://x/wide",
        title="t",
        variant=LANDSCAPE_VARIANT,
    )
    monkeypatch.setattr(uploader, "_upload_video", lambda *a, **kw: "short123")
    monkeypatch.setattr(uploader, "_set_thumbnail", lambda *a, **kw: None)

    result = uploader.publish_report(
        _report(),
        store,
        config,
        upload_store,
        variant=VERTICAL_VARIANT,
        client_factory=lambda _c: _FakeClient(),
    )

    assert result.status == "success"
    assert result.video_id == "short123"


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
    store.ensure_dirs()
    upload_store = YouTubeUploadStore(tmp_path / "data")

    def _boom(*_a: object, **_kw: object) -> None:
        raise AssertionError("must not attempt an upload with no video file")

    monkeypatch.setattr(uploader, "build_client", _boom)

    result = uploader.publish_report(_report(), store, config, upload_store)

    assert result.status == "failed"
    assert "No landscape video found" in (result.video_error or "")
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

    assert result.status == "success"
    assert result.video_id == "abc123"
    assert result.thumbnail_uploaded is False
    assert "simulated thumbnail failure" in (result.thumbnail_error or "")
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
