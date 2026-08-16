from __future__ import annotations

from datetime import date
from pathlib import Path

from wta_daily.config import AppConfig, GraphicsConfig, ProviderConfig
from wta_daily.models import MatchResult, PlayerRanking
from wta_daily.pipeline import DailyPipeline
from wta_daily.plugins.base import MatchProvider
from wta_daily.plugins.matches.sample import SampleMatchProvider  # noqa: F401 - registers plugin
from wta_daily.plugins.rankings.sample import SampleRankingsProvider
from wta_daily.plugins.registry import matches_registry, rankings_registry

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


def test_pipeline_marks_players_unknown_on_first_run(tmp_path: Path) -> None:
    """First-ever run (no previous snapshot) must use 'unknown', never 'new'.

    Regression test for the production incident where every established
    Top 10 player was narrated as a brand new entrant purely because the
    application itself had never run before.
    """

    config = _make_config(tmp_path)
    pipeline = DailyPipeline(config)

    report = pipeline.run(date(2026, 8, 9))

    assert all(p.movement.value == "unknown" for p in report.players)
    assert all(p.previous_rank is None for p in report.players)


def test_pipeline_computes_movement_on_second_run(tmp_path: Path) -> None:
    config = _make_config(tmp_path)

    DailyPipeline(config).run(date(2026, 8, 8))
    report = DailyPipeline(config).run(date(2026, 8, 9))

    # Same fixture data both days => ranks are unchanged => "same", now that
    # a real previous snapshot exists (as opposed to "unknown" on day one).
    assert all(p.movement.value == "same" for p in report.players)


class _TrackingRankingsProvider:
    """Wraps SampleRankingsProvider, counting how many times it's called."""

    def __init__(self, fixture_path: str, **_ignored: object) -> None:
        self._inner = SampleRankingsProvider(fixture_path=fixture_path)
        self.calls: list[int] = []

    def get_top_n(self, n: int) -> list[PlayerRanking]:
        self.calls.append(n)
        return self._inner.get_top_n(n)


def test_pipeline_fetches_rankings_exactly_once_per_run(tmp_path: Path) -> None:
    """The core rankings-efficiency property: no matter how many downstream
    steps need ranking data (top_n report, movement comparison, the wider
    pool), only one rankings request should ever be made in one run."""

    provider_name = "tracking-rankings-for-tests"
    rankings_registry.register(provider_name)(_TrackingRankingsProvider)

    config = _make_config(tmp_path)
    config.rankings_provider = ProviderConfig(
        name=provider_name, options={"fixture_path": str(SAMPLE_RANKINGS_FIXTURE)}
    )

    pipeline = DailyPipeline(config)
    pipeline.run(date(2026, 8, 9))

    assert pipeline._rankings_provider.calls == [config.rankings_pool_size]


def test_pipeline_exposes_the_wider_rankings_pool_for_future_reuse(tmp_path: Path) -> None:
    """A larger pool than `top_n` is fetched in that single rankings
    request and kept available on the pipeline instance - e.g. for a future
    featured-player lookup outside the tracked group - without ever
    issuing a second rankings request for it."""

    config = _make_config(tmp_path)
    config.top_n = 5  # sample fixture has 10 players; default pool_size (25) covers all of them

    pipeline = DailyPipeline(config)
    report = pipeline.run(date(2026, 8, 9))

    assert len(report.players) == 5
    assert len(pipeline.last_rankings_pool) == 10
    pool_ranks = {r.rank for r in pipeline.last_rankings_pool}
    assert pool_ranks == set(range(1, 11))


def test_pipeline_caches_wider_pool_metadata_without_affecting_movement_history(
    tmp_path: Path,
) -> None:
    """Ranks 6-10 (outside the tracked top_n=5) should still land in the
    stable player-metadata cache (players.json) as a side benefit of
    fetching the wider pool - but must NOT appear in the movement-comparison
    snapshot history, which stays scoped to exactly the tracked group (see
    RankingsSnapshotStore.save_snapshot's docstring)."""

    config = _make_config(tmp_path)
    config.top_n = 5

    DailyPipeline(config).run(date(2026, 8, 9))

    import json

    players_cache = json.loads((config.data_dir / "players.json").read_text())
    assert "sample-008" in players_cache  # rank 8, outside top_n

    history = json.loads((config.data_dir / "rankings-history.json").read_text())
    tracked_ids = {r["player_id"] for r in history[0]["rankings"]}
    assert "sample-008" not in tracked_ids
    assert len(tracked_ids) == 5


def test_pipeline_marks_genuine_new_entrant_when_snapshot_exists(tmp_path: Path) -> None:
    """A player absent from a *real* previous snapshot is 'new', not 'unknown'."""

    config = _make_config(tmp_path)
    config.top_n = 4
    DailyPipeline(config).run(date(2026, 8, 8))  # snapshot only covers ranks 1-4

    config.top_n = 5  # rank 5 was not part of yesterday's tracked snapshot
    report = DailyPipeline(config).run(date(2026, 8, 9))

    by_rank = {p.rank: p for p in report.players}
    assert by_rank[5].movement.value == "new"
    assert by_rank[5].previous_rank is None
    assert by_rank[1].movement.value == "same"


class _FlakyMatchProvider(MatchProvider):
    """Raises for the first player fetched, succeeds for everyone else.

    Only overrides ``get_latest_match``, so ``get_matches_for_date`` uses
    ``MatchProvider``'s default per-player fallback - this exercises that
    default's per-player failure isolation specifically.
    """

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
            match_date=date(2026, 8, 8),  # equals report_date (8/9) minus the default 1-day offset
        )


def test_pipeline_continues_when_one_players_match_fails(tmp_path: Path) -> None:
    """A single player's lookup failing (within the default get_matches_for_date
    fallback) must not abort the run or affect any other player - the
    affected player simply shows played: false, indistinguishable from
    genuinely not having played (this is a designed tradeoff: a per-item
    failure buried inside one batch call has no clean way to be flagged as
    "unknown" separately from "false" without the source explicitly
    supporting that - see the total-batch-failure test below for the case
    that *is* flagged, via match_error)."""

    matches_registry.register("flaky-for-tests")(_FlakyMatchProvider)
    config = _make_config(tmp_path)
    config.match_provider = ProviderConfig(name="flaky-for-tests")

    report = DailyPipeline(config).run(date(2026, 8, 9))

    assert len(report.players) == 5
    no_match_players = [p for p in report.players if p.match is None]
    matched_players = [p for p in report.players if p.match is not None]
    assert len(no_match_players) == 1
    assert len(matched_players) == 4
    assert report.errors == []
    # The whole job still produced a full report and its artifacts.
    assert (config.output_dir / "2026-08-09" / "report.json").exists()


class _TotallyBrokenMatchProvider(MatchProvider):
    """Every lookup fails outright - simulates the whole data source being down."""

    def __init__(self, **_ignored: object) -> None:
        pass

    def get_latest_match(self, player: PlayerRanking) -> MatchResult | None:
        raise RuntimeError("should not be called - get_matches_for_date is overridden")

    def get_matches_for_date(self, players, target_date):  # noqa: ANN001, ANN201
        raise RuntimeError("simulated total outage")


def test_pipeline_marks_every_player_with_match_error_on_total_batch_failure(
    tmp_path: Path,
) -> None:
    """If the match source fails entirely (not just for one player), every
    player is reported as played: false *with* a match_error attached -
    distinguishing "we couldn't check" from a confirmed "she didn't play"."""

    matches_registry.register("totally-broken-for-tests")(_TotallyBrokenMatchProvider)
    config = _make_config(tmp_path)
    config.match_provider = ProviderConfig(name="totally-broken-for-tests")

    report = DailyPipeline(config).run(date(2026, 8, 9))

    assert len(report.players) == 5
    assert all(p.match is None for p in report.players)
    assert all(p.match_error is not None for p in report.players)
    assert len(report.errors) == 1
    assert (config.output_dir / "2026-08-09" / "report.json").exists()
