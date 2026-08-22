"""Offline ATP v1 pipeline: mocked BALLDONTLIE rankings, no match claims."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import pytest

from wta_daily.config import AppConfig, GraphicsConfig, ProviderConfig, load_config
from wta_daily.models import Movement
from wta_daily.pipeline import DailyPipeline
from wta_daily.plugins.balldontlie_atp_client import BalldontlieAtpClient
from wta_daily.title import generate_title
from wta_daily.youtube_description import generate_description


def _entry(
    *,
    rank: int,
    player_id: int,
    name: str,
    points: int,
    ranking_date: str | None = "2026-08-18",
    movement: int | None = 2,
) -> dict[str, Any]:
    return {
        "id": rank,
        "player": {
            "id": player_id,
            "full_name": name,
            "first_name": name.split(" ", 1)[0],
            "last_name": name.split(" ", 1)[-1],
            "country_code": "ESP",
        },
        "rank": rank,
        "points": points,
        "movement": movement,
        "ranking_date": ranking_date,
    }


_WEEK_ONE = [
    _entry(rank=1, player_id=10, name="Carlos Alcaraz", points=12000),
    _entry(rank=2, player_id=20, name="Jannik Sinner", points=11500),
    _entry(rank=3, player_id=30, name="Alexander Zverev", points=7000),
]

_WEEK_TWO = [
    _entry(rank=1, player_id=20, name="Jannik Sinner", points=13000, ranking_date="2026-08-25"),
    _entry(rank=2, player_id=10, name="Carlos Alcaraz", points=11800, ranking_date="2026-08-25"),
    _entry(rank=3, player_id=30, name="Alexander Zverev", points=7000, ranking_date="2026-08-25"),
]


def _atp_config(tmp_path: Path) -> AppConfig:
    config = AppConfig()
    config.tour = "atp"
    config.data_dir = tmp_path / "data" / "atp"
    config.output_dir = tmp_path / "output" / "atp"
    config.log_dir = tmp_path / "logs" / "atp"
    config.rankings_provider = ProviderConfig(name="balldontlie_atp")
    config.match_provider = ProviderConfig(name="none")
    config.top_n = 3
    config.rankings_pool_size = 3
    config.graphics = GraphicsConfig(width=480, height=270)
    config.featured_player.enabled = False
    config.voice.enabled = False
    config.video.enabled = False
    config.youtube.enabled = False
    return config


def test_atp_example_config_is_isolated_and_rankings_only() -> None:
    config = load_config(Path("config/config.atp.example.yaml"))

    assert config.tour == "atp"
    assert config.rankings_provider.name == "balldontlie_atp"
    assert config.match_provider.name == "none"
    assert config.data_dir == Path("data/atp")
    assert config.output_dir == Path("output/atp")
    assert config.log_dir == Path("logs/atp")
    assert config.featured_player.enabled is False
    assert config.voice.enabled is False
    assert config.video.enabled is False
    assert config.youtube.enabled is False
    assert config.tour_profile.supports_daily_matches is False


def test_offline_atp_pipeline_produces_rankings_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv("BALLDONTLIE_API_KEY", "test-key-not-a-secret")
    monkeypatch.setattr(BalldontlieAtpClient, "get_rankings", lambda self, n, per_page=None: _WEEK_ONE)
    config = _atp_config(tmp_path)

    with caplog.at_level("INFO"):
        report = DailyPipeline(config).run(date(2026, 8, 22))

    assert len(report.players) == 3
    assert report.tour == "atp"
    assert report.ranking_date == date(2026, 8, 18)
    assert report.match_target_date is None
    assert [p.name for p in report.players] == [
        "Carlos Alcaraz",
        "Jannik Sinner",
        "Alexander Zverev",
    ]
    assert report.players[0].points == 12000
    assert report.players[0].movement is Movement.UNKNOWN
    assert all(player.match is None for player in report.players)
    assert all(player.tournament_status is None for player in report.players)
    assert "did not play" not in caplog.text.lower()

    output_dir = config.output_dir / "2026-08-22"
    script = (output_dir / "script.txt").read_text(encoding="utf-8")
    title = (output_dir / "title.txt").read_text(encoding="utf-8")
    description = (output_dir / "youtube_description.txt").read_text(encoding="utf-8")

    assert generate_title(report) == title.strip()
    assert "ATP Top 3 Rankings Update" in title
    assert "August 18, 2026" in title
    assert "ATP Top 3 Rankings Update" in description
    assert "did not play" not in description.lower()
    assert "daily" not in description.lower()
    assert "12,000 ranking points" in script
    assert "did not play yesterday" not in script.lower()
    assert "WTA" not in script
    assert " she " not in f" {script} "
    assert "defeated" not in script.lower()
    assert "eliminat" not in script.lower()
    assert generate_description(report) == description


def test_offline_atp_pipeline_uses_snapshot_movement_not_vendor_field(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BALLDONTLIE_API_KEY", "test-key-not-a-secret")
    config = _atp_config(tmp_path)

    monkeypatch.setattr(BalldontlieAtpClient, "get_rankings", lambda self, n, per_page=None: _WEEK_ONE)
    DailyPipeline(config).run(date(2026, 8, 18))

    monkeypatch.setattr(BalldontlieAtpClient, "get_rankings", lambda self, n, per_page=None: _WEEK_TWO)
    report = DailyPipeline(config).run(date(2026, 8, 25))

    by_name = {player.name: player for player in report.players}
    # Vendor movement on week two was still +2 for every row; snapshot logic
    # is what the report uses: Sinner 2 -> 1 (up), Alcaraz 1 -> 2 (down).
    assert by_name["Jannik Sinner"].movement is Movement.UP
    assert by_name["Jannik Sinner"].previous_rank == 2
    assert by_name["Carlos Alcaraz"].movement is Movement.DOWN
    assert by_name["Carlos Alcaraz"].previous_rank == 1
    assert by_name["Alexander Zverev"].movement is Movement.SAME
    assert report.ranking_date == date(2026, 8, 25)


def test_same_date_rerun_does_not_fabricate_movement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A second run on the same report_date must compare against the previous
    week's snapshot, not against the snapshot this date just wrote."""

    monkeypatch.setenv("BALLDONTLIE_API_KEY", "test-key-not-a-secret")
    config = _atp_config(tmp_path)

    monkeypatch.setattr(BalldontlieAtpClient, "get_rankings", lambda self, n, per_page=None: _WEEK_ONE)
    first = DailyPipeline(config).run(date(2026, 8, 18))
    assert all(player.movement is Movement.UNKNOWN for player in first.players)

    rerun_first = DailyPipeline(config).run(date(2026, 8, 18))
    assert all(player.movement is Movement.UNKNOWN for player in rerun_first.players)

    monkeypatch.setattr(BalldontlieAtpClient, "get_rankings", lambda self, n, per_page=None: _WEEK_TWO)
    week_two = DailyPipeline(config).run(date(2026, 8, 25))
    week_two_again = DailyPipeline(config).run(date(2026, 8, 25))

    assert [player.movement for player in week_two.players] == [
        player.movement for player in week_two_again.players
    ]
    assert [player.previous_rank for player in week_two.players] == [
        player.previous_rank for player in week_two_again.players
    ]
    by_name = {player.name: player for player in week_two_again.players}
    assert by_name["Jannik Sinner"].movement is Movement.UP
    assert by_name["Carlos Alcaraz"].movement is Movement.DOWN
    assert by_name["Alexander Zverev"].movement is Movement.SAME


def test_atp_pipeline_records_top_n_departures_for_weekly_narration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BALLDONTLIE_API_KEY", "test-key-not-a-secret")
    config = _atp_config(tmp_path)

    monkeypatch.setattr(BalldontlieAtpClient, "get_rankings", lambda self, n, per_page=None: _WEEK_ONE)
    DailyPipeline(config).run(date(2026, 8, 18))

    week_two_with_departure = [
        _entry(rank=1, player_id=20, name="Jannik Sinner", points=13000, ranking_date="2026-08-25"),
        _entry(rank=2, player_id=10, name="Carlos Alcaraz", points=11800, ranking_date="2026-08-25"),
        _entry(rank=3, player_id=40, name="Ben Shelton", points=3670, ranking_date="2026-08-25"),
    ]
    monkeypatch.setattr(
        BalldontlieAtpClient, "get_rankings", lambda self, n, per_page=None: week_two_with_departure
    )
    report = DailyPipeline(config).run(date(2026, 8, 25))
    script = (config.output_dir / "2026-08-25" / "script.txt").read_text(encoding="utf-8")

    assert len(report.departed_players) == 1
    assert report.departed_players[0].name == "Alexander Zverev"
    assert report.departed_players[0].previous_rank == 3
    assert "Alexander Zverev" in script
    assert "out of the Top" in script
    assert report.players[2].movement is Movement.NEW
    assert "moves into" in script.lower() or "enters" in script.lower()
