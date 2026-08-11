from __future__ import annotations

from datetime import date
from pathlib import Path

from wta_daily.config import AppConfig, GraphicsConfig, ProviderConfig
from wta_daily.models import MatchResult, PlayerRanking
from wta_daily.pipeline import DailyPipeline
from wta_daily.plugins.base import MatchProvider
from wta_daily.plugins.matches.sample import SampleMatchProvider  # noqa: F401 - registers plugin
from wta_daily.plugins.rankings.sample import (
    SampleRankingsProvider,  # noqa: F401 - registers plugin
)
from wta_daily.plugins.registry import matches_registry

from .conftest import SAMPLE_MATCHES_FIXTURE, SAMPLE_RANKINGS_FIXTURE


def _make_config(tmp_path: Path) -> AppConfig:
    config = AppConfig()
    config.data_dir = tmp_path / "data"
    config.output_dir = tmp_path / "output"
    config.log_dir = tmp_path / "logs"
    config.rankings_provider = ProviderConfig(
        name="sample", options={"fixture_path": str(SAMPLE_RANKINGS_FIXTURE)}
    )
    config.match_provider = ProviderConfig(
        name="sample", options={"fixture_path": str(SAMPLE_MATCHES_FIXTURE)}
    )
    config.top_n = 5
    config.graphics = GraphicsConfig(width=480, height=270)
    return config


def test_pipeline_run_produces_all_phase1_artifacts(tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    pipeline = DailyPipeline(config)

    report = pipeline.run(date(2026, 8, 9))

    output_dir = config.output_dir / "2026-08-09"
    assert (output_dir / "report.json").exists()
    assert (output_dir / "script.txt").exists()
    assert (output_dir / "leaderboard.png").exists()
    for player in report.players:
        assert (output_dir / "player_cards" / f"{player.rank:02d}.png").exists()

    assert (config.data_dir / "rankings-history.json").exists()
    assert (config.data_dir / "players.json").exists()
    assert len(report.players) == 5
    assert report.errors == []


def test_pipeline_marks_players_new_on_first_run(tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    pipeline = DailyPipeline(config)

    report = pipeline.run(date(2026, 8, 9))

    assert all(p.movement.value == "new" for p in report.players)


def test_pipeline_computes_movement_on_second_run(tmp_path: Path) -> None:
    config = _make_config(tmp_path)

    DailyPipeline(config).run(date(2026, 8, 8))
    report = DailyPipeline(config).run(date(2026, 8, 9))

    # Same fixture data both days => ranks are unchanged => "same".
    assert all(p.movement.value == "same" for p in report.players)


class _FlakyMatchProvider(MatchProvider):
    """Raises for the first player fetched, succeeds for everyone else."""

    def __init__(self, **_ignored: object) -> None:
        self._calls = 0

    def get_latest_match(self, player: PlayerRanking) -> MatchResult | None:
        self._calls += 1
        if self._calls == 1:
            raise RuntimeError("simulated provider outage")
        return MatchResult(
            opponent="Someone",
            tournament="Somewhere Open",
            round="Final",
            score="6-4 6-4",
            won=True,
            match_date=date(2026, 8, 8),
        )


def test_pipeline_continues_when_one_players_match_fails(tmp_path: Path) -> None:
    matches_registry.register("flaky-for-tests")(_FlakyMatchProvider)
    config = _make_config(tmp_path)
    config.match_provider = ProviderConfig(name="flaky-for-tests")

    report = DailyPipeline(config).run(date(2026, 8, 9))

    assert len(report.players) == 5
    failed_players = [p for p in report.players if p.match_error is not None]
    succeeded_players = [p for p in report.players if p.match is not None]
    assert len(failed_players) == 1
    assert len(succeeded_players) == 4
    assert len(report.errors) == 1
    # The whole job still produced a full report and its artifacts.
    assert (config.output_dir / "2026-08-09" / "report.json").exists()
