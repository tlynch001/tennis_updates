from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from wta_daily import cli
from wta_daily.models import DailyReport, Movement, PlayerReport
from wta_daily.persistence.report_store import DailyOutputStore
from wta_daily.persistence.youtube_upload_store import VERTICAL_VARIANT
from wta_daily.youtube.uploader import YouTubePublishResult


def _write_config(tmp_path: Path) -> Path:
    path = tmp_path / "config.yaml"
    path.write_text(
        f"""
data_dir: {tmp_path / 'data'}
output_dir: {tmp_path / 'output'}
log_dir: {tmp_path / 'logs'}
youtube:
  enabled: true
""",
        encoding="utf-8",
    )
    return path


def _write_report(tmp_path: Path) -> None:
    day = date(2026, 8, 17)
    store = DailyOutputStore(tmp_path / "output", day)
    store.ensure_dirs()
    store.write_report(
        DailyReport(
            report_date=day,
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
    )


def test_vertical_upload_flag_routes_to_vertical_variant(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = _write_config(tmp_path)
    _write_report(tmp_path)
    seen: dict[str, object] = {}

    def fake_publish_report(report, store, config, upload_store, **kwargs):  # noqa: ANN001, ANN201
        seen.update(kwargs)
        return YouTubePublishResult(
            status="success",
            video_id="short123",
            video_url="https://www.youtube.com/watch?v=short123",
        )

    monkeypatch.setattr(cli, "publish_report", fake_publish_report)

    exit_code = cli.main(
        [
            "--config",
            str(config_path),
            "--date",
            "2026-08-17",
            "--upload-youtube-vertical",
        ]
    )

    assert exit_code == 0
    assert seen["variant"] == VERTICAL_VARIANT
    assert seen["force"] is False


def test_landscape_and_vertical_upload_flags_are_mutually_exclusive(tmp_path: Path) -> None:
    parser = cli.build_arg_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["--upload-youtube", "--upload-youtube-vertical"])
