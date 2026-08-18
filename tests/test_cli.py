"""Tests for the --upload-youtube CLI path.

Deliberately never constructs a real DailyPipeline or hits the network -
--upload-youtube's whole purpose is to skip data collection/narration/video
assembly and act only on an already-generated output/<date>/ folder, so
these tests just prepare that folder by hand and mock the one function
that would otherwise talk to YouTube.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from wta_daily import cli
from wta_daily.models import DailyReport, Movement, PlayerReport
from wta_daily.persistence.report_store import DailyOutputStore
from wta_daily.youtube.uploader import YouTubePublishResult


def _write_config(tmp_path: Path, *, youtube_enabled: bool) -> Path:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        f"""
data_dir: {tmp_path / "data"}
output_dir: {tmp_path / "output"}
log_dir: {tmp_path / "logs"}
youtube:
  enabled: {"true" if youtube_enabled else "false"}
""",
        encoding="utf-8",
    )
    return config_path


def _write_existing_report(tmp_path: Path, report_date: date, *, with_video: bool = True) -> None:
    store = DailyOutputStore(tmp_path / "output", report_date)
    store.ensure_dirs()
    report = DailyReport(
        report_date=report_date,
        tour="wta",
        players=[
            PlayerReport(
                rank=1,
                name="Player One",
                player_id="p1",
                country_code="USA",
                points=1000,
                movement=Movement.SAME,
            )
        ],
    )
    store.write_report(report)
    if with_video:
        store.video_path.write_bytes(b"fake mp4 bytes")
    store.thumbnail_path.write_bytes(b"fake png bytes")
    store.write_youtube_description("A great day of tennis.")


def test_upload_youtube_fails_cleanly_when_no_report_exists(tmp_path: Path) -> None:
    config_path = _write_config(tmp_path, youtube_enabled=True)

    exit_code = cli.main(["--config", str(config_path), "--date", "2026-08-17", "--upload-youtube"])

    assert exit_code == 1


def test_upload_youtube_disabled_in_config_returns_success_with_no_upload(
    tmp_path: Path,
) -> None:
    """youtube.enabled: false is handled by the real (unmocked)
    publish_report itself - side-effect-free by construction, so this
    exercises the actual disabled short-circuit rather than a stand-in."""

    config_path = _write_config(tmp_path, youtube_enabled=False)
    _write_existing_report(tmp_path, date(2026, 8, 17))

    exit_code = cli.main(["--config", str(config_path), "--date", "2026-08-17", "--upload-youtube"])

    assert exit_code == 0
    assert not (tmp_path / "data" / "youtube-uploads.json").exists()


def test_upload_youtube_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_path = _write_config(tmp_path, youtube_enabled=True)
    _write_existing_report(tmp_path, date(2026, 8, 17))

    monkeypatch.setattr(
        cli,
        "publish_report",
        lambda *a, **kw: YouTubePublishResult(
            status="success", video_id="abc123", video_url="https://www.youtube.com/watch?v=abc123"
        ),
    )

    exit_code = cli.main(["--config", str(config_path), "--date", "2026-08-17", "--upload-youtube"])

    assert exit_code == 0


def test_upload_youtube_failure_returns_nonzero_exit_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = _write_config(tmp_path, youtube_enabled=True)
    _write_existing_report(tmp_path, date(2026, 8, 17))

    monkeypatch.setattr(
        cli,
        "publish_report",
        lambda *a, **kw: YouTubePublishResult(status="failed", video_error="simulated outage"),
    )

    exit_code = cli.main(["--config", str(config_path), "--date", "2026-08-17", "--upload-youtube"])

    assert exit_code == 1


def test_upload_youtube_skipped_duplicate_returns_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = _write_config(tmp_path, youtube_enabled=True)
    _write_existing_report(tmp_path, date(2026, 8, 17))

    monkeypatch.setattr(
        cli,
        "publish_report",
        lambda *a, **kw: YouTubePublishResult(
            status="skipped_duplicate", video_id="already-there", message="already uploaded"
        ),
    )

    exit_code = cli.main(["--config", str(config_path), "--date", "2026-08-17", "--upload-youtube"])

    assert exit_code == 0


def test_upload_youtube_force_flag_is_passed_through(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_path = _write_config(tmp_path, youtube_enabled=True)
    _write_existing_report(tmp_path, date(2026, 8, 17))

    captured_kwargs: dict[str, object] = {}

    def fake_publish_report(report, store, config, upload_store, **kwargs):  # noqa: ANN001, ANN201
        captured_kwargs.update(kwargs)
        return YouTubePublishResult(status="success", video_id="abc123", video_url="https://x/abc123")

    monkeypatch.setattr(cli, "publish_report", fake_publish_report)

    cli.main(
        [
            "--config",
            str(config_path),
            "--date",
            "2026-08-17",
            "--upload-youtube",
            "--force-youtube-upload",
        ]
    )

    assert captured_kwargs.get("force") is True


def test_upload_youtube_loads_the_report_written_by_a_previous_full_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """--upload-youtube must reuse the exact report already on disk, never
    re-fetch rankings/matches - this is its entire reason to exist."""

    config_path = _write_config(tmp_path, youtube_enabled=True)
    _write_existing_report(tmp_path, date(2026, 8, 17))

    seen_reports = []
    monkeypatch.setattr(
        cli,
        "publish_report",
        lambda report, *a, **kw: (
            seen_reports.append(report)
            or YouTubePublishResult(status="success", video_id="abc123", video_url="https://x/abc123")
        ),
    )

    cli.main(["--config", str(config_path), "--date", "2026-08-17", "--upload-youtube"])

    assert len(seen_reports) == 1
    loaded_report = seen_reports[0]
    assert loaded_report.report_date == date(2026, 8, 17)
    assert loaded_report.players[0].name == "Player One"


def test_upload_youtube_json_report_round_trips_correctly(tmp_path: Path) -> None:
    """Sanity check that a report written by the normal pipeline path can
    actually be reloaded by --upload-youtube (DailyReport.from_dict of
    DailyReport.to_dict)."""

    report_date = date(2026, 8, 17)
    store = DailyOutputStore(tmp_path / "output", report_date)
    store.ensure_dirs()
    original = DailyReport(
        report_date=report_date,
        tour="wta",
        players=[
            PlayerReport(
                rank=1,
                name="Player One",
                player_id="p1",
                country_code="USA",
                points=1000,
                movement=Movement.SAME,
            )
        ],
    )
    store.write_report(original)

    reloaded = DailyReport.from_dict(json.loads(store.report_path.read_text()))

    assert reloaded.report_date == original.report_date
    assert reloaded.players[0].name == original.players[0].name
