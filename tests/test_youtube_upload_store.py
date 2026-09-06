from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from wta_daily.persistence.youtube_upload_store import (
    LANDSCAPE_VARIANT,
    VERTICAL_VARIANT,
    YouTubeUploadStore,
)


def test_get_upload_returns_none_when_nothing_recorded(tmp_path: Path) -> None:
    store = YouTubeUploadStore(tmp_path)

    assert store.get_upload(date(2026, 8, 17), "wta") is None
    assert not store.path.exists()


def test_record_and_retrieve_an_upload(tmp_path: Path) -> None:
    store = YouTubeUploadStore(tmp_path)

    record = store.record_upload(
        date(2026, 8, 17),
        "wta",
        video_id="abc123",
        video_url="https://www.youtube.com/watch?v=abc123",
        title="WTA Top 10 Update — August 17, 2026",
    )

    assert record.video_id == "abc123"
    assert record.variant == LANDSCAPE_VARIANT
    fetched = store.get_upload(date(2026, 8, 17), "wta")
    assert fetched is not None
    assert fetched.video_id == "abc123"
    assert fetched.video_url == "https://www.youtube.com/watch?v=abc123"
    assert fetched.title == "WTA Top 10 Update — August 17, 2026"
    assert fetched.uploaded_at


def test_upload_is_scoped_by_date_tour_and_variant(tmp_path: Path) -> None:
    store = YouTubeUploadStore(tmp_path)
    store.record_upload(
        date(2026, 8, 17),
        "wta",
        video_id="landscape-video",
        video_url="https://x/landscape",
        title="t",
    )

    assert store.get_upload(date(2026, 8, 18), "wta") is None
    assert store.get_upload(date(2026, 8, 17), "atp") is None
    assert store.get_upload(date(2026, 8, 17), "wta", LANDSCAPE_VARIANT) is not None
    assert store.get_upload(date(2026, 8, 17), "wta", VERTICAL_VARIANT) is None


def test_landscape_and_vertical_can_both_be_recorded(tmp_path: Path) -> None:
    store = YouTubeUploadStore(tmp_path)
    day = date(2026, 8, 17)
    store.record_upload(
        day,
        "wta",
        video_id="wide",
        video_url="https://x/wide",
        title="same title",
        variant=LANDSCAPE_VARIANT,
    )
    store.record_upload(
        day,
        "wta",
        video_id="short",
        video_url="https://x/short",
        title="same title",
        variant=VERTICAL_VARIANT,
    )

    assert store.get_upload(day, "wta", LANDSCAPE_VARIANT).video_id == "wide"  # type: ignore[union-attr]
    assert store.get_upload(day, "wta", VERTICAL_VARIANT).video_id == "short"  # type: ignore[union-attr]


def test_legacy_record_is_still_treated_as_landscape(tmp_path: Path) -> None:
    day = date(2026, 8, 17)
    path = tmp_path / "youtube-uploads.json"
    path.write_text(
        json.dumps(
            {
                "wta:2026-08-17": {
                    "date": "2026-08-17",
                    "tour": "wta",
                    "video_id": "legacy",
                    "video_url": "https://x/legacy",
                    "title": "old",
                    "uploaded_at": "2026-08-17T12:00:00+00:00",
                }
            }
        ),
        encoding="utf-8",
    )
    store = YouTubeUploadStore(tmp_path)

    landscape = store.get_upload(day, "wta", LANDSCAPE_VARIANT)
    assert landscape is not None
    assert landscape.video_id == "legacy"
    assert landscape.variant == LANDSCAPE_VARIANT
    assert store.get_upload(day, "wta", VERTICAL_VARIANT) is None


def test_recording_a_new_date_does_not_clobber_an_earlier_one(tmp_path: Path) -> None:
    store = YouTubeUploadStore(tmp_path)
    store.record_upload(date(2026, 8, 16), "wta", video_id="video-16", video_url="https://x/16", title="t16")
    store.record_upload(date(2026, 8, 17), "wta", video_id="video-17", video_url="https://x/17", title="t17")

    assert store.get_upload(date(2026, 8, 16), "wta").video_id == "video-16"  # type: ignore[union-attr]
    assert store.get_upload(date(2026, 8, 17), "wta").video_id == "video-17"  # type: ignore[union-attr]


def test_write_is_atomic_and_human_readable(tmp_path: Path) -> None:
    store = YouTubeUploadStore(tmp_path)
    store.record_upload(date(2026, 8, 17), "wta", video_id="abc123", video_url="https://x/abc123", title="t")

    assert not store.path.with_suffix(".json.tmp").exists()
    raw = json.loads(store.path.read_text(encoding="utf-8"))
    assert raw["wta:2026-08-17:landscape"]["video_id"] == "abc123"
    assert raw["wta:2026-08-17:landscape"]["variant"] == LANDSCAPE_VARIANT
