from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from wta_daily.config import AppConfig, FeaturedPlayerConfig, GraphicsConfig, ProviderConfig
from wta_daily.models import (
    DailyReport,
    MatchLookupResult,
    MatchResult,
    Movement,
    PlayerRanking,
    TournamentRunStatus,
    TournamentState,
)
from wta_daily.persistence.report_store import DailyOutputStore
from wta_daily.pipeline import DailyPipeline
from wta_daily.plugins.base import MatchProvider, RankingsProvider
from wta_daily.plugins.matches.sample import SampleMatchProvider  # noqa: F401 - registers plugin
from wta_daily.plugins.rankings.sample import SampleRankingsProvider
from wta_daily.plugins.registry import matches_registry, rankings_registry
from wta_daily.video.ffmpeg_assembler import FfmpegVideoAssembler
from wta_daily.voice.narration_timing import NarrationSegment
from wta_daily.youtube.uploader import YouTubePublishResult

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

    # New artifacts, on by default, with no featured player configured.
    assert (output_dir / "thumbnail.png").exists()
    assert (output_dir / "youtube_description.txt").exists()
    assert not (output_dir / "featured_player.png").exists()

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


# --- Featured player (Emma Navarro / "america_favorite") --------------------

EMMA_ID = "emma-test-id"
EMMA_NAME = "Emma Navarro"


def _synthetic_rankings(emma_rank: int | None, total: int = 30) -> list[PlayerRanking]:
    """A full 1..total rankings list with Emma at `emma_rank` (or omitted
    entirely if `emma_rank` is None, e.g. to simulate her dropping out of
    the rankings altogether) and everyone else auto-generated."""

    rankings = []
    for rank in range(1, total + 1):
        if rank == emma_rank:
            rankings.append(
                PlayerRanking(
                    rank=rank,
                    player_id=EMMA_ID,
                    name=EMMA_NAME,
                    country_code="USA",
                    points=10_000 - rank * 10,
                )
            )
        else:
            rankings.append(
                PlayerRanking(
                    rank=rank,
                    player_id=f"synthetic-{rank}",
                    name=f"Synthetic Player {rank}",
                    country_code="USA",
                    points=10_000 - rank * 10,
                )
            )
    return rankings


class _SyntheticRankingsProvider(RankingsProvider):
    """Directly controllable rankings source for featured-player scenarios -
    bypasses the plugin registry/config-options plumbing entirely, since
    these tests need precise control over exactly who is ranked where."""

    def __init__(self, rankings: list[PlayerRanking]) -> None:
        self._rankings = rankings
        self.calls: list[int] = []

    def get_top_n(self, n: int) -> list[PlayerRanking]:
        self.calls.append(n)
        return sorted(self._rankings, key=lambda r: r.rank)[:n]


class _SyntheticMatchProvider(MatchProvider):
    """Directly controllable match source: returns exactly the
    matches/unresolved players configured, regardless of who's actually
    asked about - lets tests assert on precisely how a batch call gets
    interpreted without needing real tournament-scan mocking."""

    def __init__(
        self,
        matches: dict[str, MatchResult] | None = None,
        unresolved: set[str] | None = None,
        error: Exception | None = None,
        tournament_status: dict[str, object] | None = None,
        **_ignored: object,
    ) -> None:
        self._matches = matches or {}
        self._unresolved = frozenset(unresolved or ())
        self._error = error
        self._tournament_status = tournament_status or {}
        self.requested_player_ids: list[str] = []

    def get_latest_match(self, player: PlayerRanking) -> MatchResult | None:
        raise AssertionError("not used - get_matches_for_date is overridden")

    def get_matches_for_date(self, players, target_date):  # noqa: ANN001, ANN201
        self.requested_player_ids = [p.player_id for p in players]
        if self._error is not None:
            raise self._error
        requested = {p.player_id for p in players}
        matches = {pid: m for pid, m in self._matches.items() if pid in requested}
        unresolved = self._unresolved & requested
        tournament_status = {pid: s for pid, s in self._tournament_status.items() if pid in requested}
        return MatchLookupResult(
            matches=matches, unresolved_player_ids=unresolved, tournament_status=tournament_status
        )


def _emma_match(*, won: bool) -> MatchResult:
    return MatchResult(
        opponent="Some Opponent",
        tournament="Cincinnati",
        round="Round of 32",
        score="6-4 6-3",
        won=won,
        match_date=date(2026, 8, 8),  # equals report_date (8/9) minus the default 1-day offset
    )


def _make_featured_config(tmp_path: Path, *, top_n: int = 10) -> AppConfig:
    config = _make_config(tmp_path)
    config.top_n = top_n
    config.featured_player = FeaturedPlayerConfig(
        enabled=True, player_id=EMMA_ID, name=EMMA_NAME, tagline="america_favorite"
    )
    return config


def _run_with_featured_player(
    tmp_path: Path,
    *,
    emma_rank: int | None,
    top_n: int = 10,
    matches: dict[str, MatchResult] | None = None,
    unresolved: set[str] | None = None,
    match_error: Exception | None = None,
    rankings_provider: RankingsProvider | None = None,
    report_date: date = date(2026, 8, 9),
):
    config = _make_featured_config(tmp_path, top_n=top_n)
    pipeline = DailyPipeline(config)
    pipeline._rankings_provider = rankings_provider or _SyntheticRankingsProvider(
        _synthetic_rankings(emma_rank)
    )
    pipeline._match_provider = _SyntheticMatchProvider(
        matches=matches, unresolved=unresolved, error=match_error
    )
    return pipeline, pipeline.run(report_date)


def test_featured_player_outside_top_n(tmp_path: Path) -> None:
    _, report = _run_with_featured_player(tmp_path, emma_rank=28)

    assert report.featured_player is not None
    assert report.featured_player.name == EMMA_NAME
    assert report.featured_player.rank == 28
    assert report.featured_player.rank_error is None
    # She isn't actually in the Top 10 - the official list must stay factual.
    assert all(p.player_id != EMMA_ID for p in report.players)


def test_featured_player_outside_top_n_renders_a_featured_card(tmp_path: Path) -> None:
    config = _make_featured_config(tmp_path, top_n=10)
    pipeline = DailyPipeline(config)
    pipeline._rankings_provider = _SyntheticRankingsProvider(_synthetic_rankings(28))
    pipeline._match_provider = _SyntheticMatchProvider()

    pipeline.run(date(2026, 8, 9))

    output_dir = config.output_dir / "2026-08-09"
    assert (output_dir / "featured_player.png").exists()
    # She's not officially in the Top 10 - no eleventh numbered card.
    assert not (output_dir / "player_cards" / "11.png").exists()


def test_featured_player_movement_toward_top_n(tmp_path: Path) -> None:
    pipeline, _ = _run_with_featured_player(tmp_path, emma_rank=30, report_date=date(2026, 8, 8))
    # Second run: she's climbed from 30 to 22.
    pipeline._rankings_provider = _SyntheticRankingsProvider(_synthetic_rankings(22))
    pipeline._match_provider = _SyntheticMatchProvider()
    report = pipeline.run(date(2026, 8, 9))

    assert report.featured_player is not None
    assert report.featured_player.rank == 22
    assert report.featured_player.previous_rank == 30
    assert report.featured_player.movement == Movement.UP


def test_featured_player_holding_steady(tmp_path: Path) -> None:
    pipeline, _ = _run_with_featured_player(tmp_path, emma_rank=28, report_date=date(2026, 8, 8))
    pipeline._rankings_provider = _SyntheticRankingsProvider(_synthetic_rankings(28))
    pipeline._match_provider = _SyntheticMatchProvider()
    report = pipeline.run(date(2026, 8, 9))

    assert report.featured_player is not None
    assert report.featured_player.movement == Movement.SAME
    assert report.featured_player.rank == report.featured_player.previous_rank == 28


def test_featured_player_movement_downward(tmp_path: Path) -> None:
    pipeline, _ = _run_with_featured_player(tmp_path, emma_rank=20, report_date=date(2026, 8, 8))
    pipeline._rankings_provider = _SyntheticRankingsProvider(_synthetic_rankings(28))
    pipeline._match_provider = _SyntheticMatchProvider()
    report = pipeline.run(date(2026, 8, 9))

    assert report.featured_player is not None
    assert report.featured_player.rank == 28
    assert report.featured_player.previous_rank == 20
    assert report.featured_player.movement == Movement.DOWN


def test_featured_player_winning_on_match_target_date(tmp_path: Path) -> None:
    win = _emma_match(won=True)
    _, report = _run_with_featured_player(tmp_path, emma_rank=28, matches={EMMA_ID: win})

    assert report.featured_player is not None
    assert report.featured_player.match == win
    assert report.featured_player.won is True
    assert report.featured_player.played is True


def test_featured_player_losing_on_match_target_date(tmp_path: Path) -> None:
    loss = _emma_match(won=False)
    _, report = _run_with_featured_player(tmp_path, emma_rank=28, matches={EMMA_ID: loss})

    assert report.featured_player is not None
    assert report.featured_player.match == loss
    assert report.featured_player.won is False
    assert report.featured_player.played is True


def test_featured_player_did_not_play(tmp_path: Path) -> None:
    _, report = _run_with_featured_player(tmp_path, emma_rank=28, matches={})

    assert report.featured_player is not None
    assert report.featured_player.match is None
    assert report.featured_player.played is False
    assert report.featured_player.won is None
    assert report.featured_player.rank == 28


def test_featured_player_match_data_unavailable_does_not_fabricate(tmp_path: Path) -> None:
    """Her own match-source lookup being unresolved (while her rank is
    perfectly fine) must still leave `match` as None - never a guess."""

    _, report = _run_with_featured_player(tmp_path, emma_rank=28, unresolved={EMMA_ID})

    assert report.featured_player is not None
    assert report.featured_player.rank == 28
    assert report.featured_player.match is None
    assert report.featured_player.won is None


def test_featured_player_total_match_batch_failure_sets_match_error(tmp_path: Path) -> None:
    _, report = _run_with_featured_player(
        tmp_path, emma_rank=28, match_error=RuntimeError("simulated total outage")
    )

    assert report.featured_player is not None
    assert report.featured_player.match is None
    assert report.featured_player.match_error is not None
    # Top N players get the exact same treatment for a total batch failure.
    assert all(p.match_error is not None for p in report.players)


def test_featured_player_entering_top_n(tmp_path: Path) -> None:
    """When she's genuinely inside the tracked group, she must appear as a
    real, factual Top N entry AND still get her featured-player spotlight."""

    win = _emma_match(won=True)
    _, report = _run_with_featured_player(tmp_path, emma_rank=8, matches={EMMA_ID: win})

    official_entry = next(p for p in report.players if p.player_id == EMMA_ID)
    assert official_entry.rank == 8
    assert official_entry.match == win

    assert report.featured_player is not None
    assert report.featured_player.rank == 8
    assert report.featured_player.match == win


def test_featured_player_entering_top_n_still_renders_featured_card(tmp_path: Path) -> None:
    """Even when she's genuinely inside the Top N (and therefore already
    has a numbered player card), the dedicated featured-player visual is
    still produced - the two are complementary, not exclusive."""

    win = _emma_match(won=True)
    config = _make_featured_config(tmp_path, top_n=10)
    pipeline = DailyPipeline(config)
    pipeline._rankings_provider = _SyntheticRankingsProvider(_synthetic_rankings(8))
    pipeline._match_provider = _SyntheticMatchProvider(matches={EMMA_ID: win})

    pipeline.run(date(2026, 8, 9))

    output_dir = config.output_dir / "2026-08-09"
    assert (output_dir / "featured_player.png").exists()
    assert (output_dir / "player_cards" / "08.png").exists()


def test_featured_player_reaching_number_one(tmp_path: Path) -> None:
    _, report = _run_with_featured_player(tmp_path, emma_rank=1)

    official_entry = next(p for p in report.players if p.player_id == EMMA_ID)
    assert official_entry.rank == 1

    assert report.featured_player is not None
    assert report.featured_player.rank == 1


def test_featured_player_not_found_anywhere_does_not_break_top_n(tmp_path: Path) -> None:
    """She's dropped out of the rankings entirely (unranked/retired/etc.) -
    the Top N pipeline must still succeed, and her section just reports
    that her rank is unavailable rather than guessing."""

    _, report = _run_with_featured_player(tmp_path, emma_rank=None)

    assert len(report.players) == 10
    assert report.featured_player is not None
    assert report.featured_player.rank is None
    assert report.featured_player.rank_error is not None
    assert report.errors  # surfaced for operator visibility, but non-fatal


def test_featured_player_not_found_anywhere_does_not_render_featured_card(tmp_path: Path) -> None:
    """No rank means nothing honest to draw - the card must simply be
    skipped, not rendered with a fabricated/blank rank."""

    config = _make_featured_config(tmp_path, top_n=10)
    pipeline = DailyPipeline(config)
    pipeline._rankings_provider = _SyntheticRankingsProvider(_synthetic_rankings(None))
    pipeline._match_provider = _SyntheticMatchProvider()

    pipeline.run(date(2026, 8, 9))

    output_dir = config.output_dir / "2026-08-09"
    assert not (output_dir / "featured_player.png").exists()
    # The rest of the run still succeeded normally.
    assert (output_dir / "thumbnail.png").exists()
    assert (output_dir / "youtube_description.txt").exists()


def test_featured_player_fallback_fetch_failure_is_isolated_from_a_healthy_top_n(
    tmp_path: Path,
) -> None:
    """The realistic isolation case: the *initial* rankings pool (used for
    the real Top N) succeeds fine; only the *second*, featured-player-only
    fallback fetch (needed because she wasn't in the initial pool) fails.
    The Top N report must be completely unaffected."""

    class _PoolThenFailProvider(RankingsProvider):
        def __init__(self, pool: list[PlayerRanking]) -> None:
            self._pool = pool
            self.calls: list[int] = []

        def get_top_n(self, n: int) -> list[PlayerRanking]:
            self.calls.append(n)
            if len(self.calls) == 1:
                return sorted(self._pool, key=lambda r: r.rank)[:n]
            raise RuntimeError("simulated outage on the featured-player fallback fetch")

    config = _make_featured_config(tmp_path, top_n=10)
    pipeline = DailyPipeline(config)
    # Emma is rank 50 - well outside the default rankings_pool_size (25),
    # so the fallback fetch is guaranteed to trigger and then fail.
    pipeline._rankings_provider = _PoolThenFailProvider(_synthetic_rankings(50, total=60))
    pipeline._match_provider = _SyntheticMatchProvider()

    report = pipeline.run(date(2026, 8, 9))

    assert len(report.players) == 10
    assert all(p.player_id != EMMA_ID for p in report.players)
    assert report.errors  # non-fatal, but visible
    assert report.featured_player is not None
    assert report.featured_player.rank is None
    assert report.featured_player.rank_error is not None
    # The output was still written successfully.
    assert (config.output_dir / "2026-08-09" / "report.json").exists()


def test_featured_player_disabled_produces_no_featured_player_field(tmp_path: Path) -> None:
    """The default (disabled) behavior must be completely unaffected -
    report.featured_player stays None and nothing about the Top N changes."""

    config = _make_config(tmp_path)
    assert config.featured_player.enabled is False

    report = DailyPipeline(config).run(date(2026, 8, 9))

    assert report.featured_player is None
    output_dir = config.output_dir / "2026-08-09"
    assert not (output_dir / "featured_player.png").exists()
    # The rest of the run is unaffected by the feature being off.
    assert (output_dir / "thumbnail.png").exists()
    assert (output_dir / "youtube_description.txt").exists()


def test_featured_player_segment_appears_after_top_n_and_before_sign_off_end_to_end(
    tmp_path: Path,
) -> None:
    """Full pipeline run (through the real template script generator):
    Emma's segment must land after every Top N player and before the
    closing sign-off in the actual written script.txt."""

    win = _emma_match(won=True)
    config = _make_featured_config(tmp_path)
    pipeline = DailyPipeline(config)
    pipeline._rankings_provider = _SyntheticRankingsProvider(_synthetic_rankings(28))
    pipeline._match_provider = _SyntheticMatchProvider(matches={EMMA_ID: win})

    pipeline.run(date(2026, 8, 9))

    script = (config.output_dir / "2026-08-09" / "script.txt").read_text()
    paragraphs = [p for p in script.split("\n\n") if p.strip()]
    emma_index = next(i for i, p in enumerate(paragraphs) if EMMA_NAME in p)

    assert emma_index == len(paragraphs) - 2  # last paragraph is the sign-off
    for i, paragraph in enumerate(paragraphs[:-1]):
        if EMMA_NAME in paragraph:
            continue
        assert i < emma_index


# --- Featured card in the synchronized video sequence ------------------------


def test_featured_card_is_used_in_the_synchronized_video_sequence(tmp_path: Path) -> None:
    """End-to-end plumbing check: the featured card the pipeline renders is
    exactly the file FfmpegVideoAssembler picks up for the 'featured'
    narration segment - not a coincidence of matching filenames, but the
    actual DailyOutputStore.featured_card_path convention both sides share.
    """

    win = _emma_match(won=True)
    config = _make_featured_config(tmp_path, top_n=10)
    pipeline = DailyPipeline(config)
    pipeline._rankings_provider = _SyntheticRankingsProvider(_synthetic_rankings(28))
    pipeline._match_provider = _SyntheticMatchProvider(matches={EMMA_ID: win})

    pipeline.run(date(2026, 8, 9))

    store = DailyOutputStore(config.output_dir, date(2026, 8, 9))
    assert store.featured_card_path.exists()

    assembler = FfmpegVideoAssembler(config.video)
    segment = NarrationSegment(
        kind="featured", label=EMMA_NAME, start_seconds=10.0, end_seconds=20.0
    )
    report = DailyReport.from_dict(json.loads(store.report_path.read_text()))
    chosen_image = assembler._image_for_segment(segment, report, store)

    assert chosen_image == store.featured_card_path


def test_thumbnail_can_be_disabled_via_config(tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    config.publishing.thumbnail_enabled = False

    DailyPipeline(config).run(date(2026, 8, 9))

    output_dir = config.output_dir / "2026-08-09"
    assert not (output_dir / "thumbnail.png").exists()
    assert (output_dir / "youtube_description.txt").exists()


def test_description_can_be_disabled_via_config(tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    config.publishing.description_enabled = False

    DailyPipeline(config).run(date(2026, 8, 9))

    output_dir = config.output_dir / "2026-08-09"
    assert (output_dir / "thumbnail.png").exists()
    assert not (output_dir / "youtube_description.txt").exists()


# --- YouTube publishing (Phase 3) --------------------------------------------


def test_title_txt_is_written_with_the_canonical_format(tmp_path: Path) -> None:
    config = _make_config(tmp_path)

    DailyPipeline(config).run(date(2026, 8, 17))

    title = (config.output_dir / "2026-08-17" / "title.txt").read_text(encoding="utf-8").strip()
    assert title == "WTA Top 5 Update \u2014 August 17, 2026"


def test_youtube_disabled_by_default_never_calls_publish_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _make_config(tmp_path)
    assert config.youtube.enabled is False

    def _boom(*_a: object, **_kw: object) -> None:
        raise AssertionError("publish_report must not be called when youtube.enabled is false")

    monkeypatch.setattr("wta_daily.pipeline.publish_report", _boom)

    report = DailyPipeline(config).run(date(2026, 8, 9))

    assert report.errors == []
    assert not (config.data_dir / "youtube-uploads.json").exists()


def test_youtube_publish_success_adds_no_errors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = _make_config(tmp_path)
    config.youtube.enabled = True

    monkeypatch.setattr(
        "wta_daily.pipeline.publish_report",
        lambda *a, **kw: YouTubePublishResult(
            status="success", video_id="abc123", video_url="https://www.youtube.com/watch?v=abc123"
        ),
    )

    report = DailyPipeline(config).run(date(2026, 8, 9))

    assert report.errors == []
    saved = json.loads((config.output_dir / "2026-08-09" / "report.json").read_text())
    assert saved["errors"] == []


def test_youtube_publish_failure_is_recorded_without_aborting_the_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _make_config(tmp_path)
    config.youtube.enabled = True

    monkeypatch.setattr(
        "wta_daily.pipeline.publish_report",
        lambda *a, **kw: YouTubePublishResult(status="failed", video_error="simulated outage"),
    )

    report = DailyPipeline(config).run(date(2026, 8, 9))

    assert any("YouTube upload failed" in e and "simulated outage" in e for e in report.errors)
    # Every other artifact from earlier phases is completely unaffected.
    output_dir = config.output_dir / "2026-08-09"
    assert (output_dir / "report.json").exists()
    assert (output_dir / "script.txt").exists()
    assert (output_dir / "leaderboard.png").exists()
    assert (output_dir / "thumbnail.png").exists()
    # The failure is visible in the persisted report too, not just in-memory.
    saved = json.loads((output_dir / "report.json").read_text())
    assert any("YouTube upload failed" in e for e in saved["errors"])


def test_youtube_thumbnail_failure_reported_separately_from_video_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _make_config(tmp_path)
    config.youtube.enabled = True

    monkeypatch.setattr(
        "wta_daily.pipeline.publish_report",
        lambda *a, **kw: YouTubePublishResult(
            status="success",
            video_id="abc123",
            video_url="https://www.youtube.com/watch?v=abc123",
            thumbnail_error="simulated thumbnail failure",
        ),
    )

    report = DailyPipeline(config).run(date(2026, 8, 9))

    assert any(
        "YouTube thumbnail upload failed" in e and "simulated thumbnail failure" in e for e in report.errors
    )


def test_youtube_publishing_end_to_end_with_a_real_upload_store(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Exercises the real DailyPipeline._publish_to_youtube -> publish_report
    -> YouTubeUploadStore wiring end to end, all the way through the real
    (offline - google-api-python-client's discovery document is bundled,
    no network call) build_client()/googleapiclient.discovery.build() call.
    Only get_credentials (which would otherwise need a real OAuth token)
    and the two functions that would otherwise perform a real upload call
    are mocked. Skipped, not failed, if the optional google packages
    (requirements-youtube.txt) aren't installed."""

    pytest.importorskip("google.oauth2.credentials")
    pytest.importorskip("googleapiclient.discovery")
    from google.oauth2.credentials import Credentials

    config = _make_config(tmp_path)
    config.youtube.enabled = True
    # publish_report requires a real video.mp4 on disk (Phase 3 only ever
    # consumes it, never regenerates it) - video assembly itself (ffmpeg)
    # is out of scope for this test, so just place a stand-in file where
    # the pipeline's own DailyOutputStore convention expects one.
    video_dir = config.output_dir / "2026-08-09"
    video_dir.mkdir(parents=True, exist_ok=True)
    (video_dir / "video.mp4").write_bytes(b"fake mp4 bytes")

    from wta_daily.youtube import uploader as uploader_module

    monkeypatch.setattr(uploader_module, "_upload_video", lambda *a, **kw: "real-flow-video-id")
    monkeypatch.setattr(uploader_module, "_set_thumbnail", lambda *a, **kw: None)
    # publish_report's default client_factory is the real build_client, which
    # itself calls get_credentials - patch that (a normal name lookup at call
    # time, unlike a bound default-argument value) to avoid any real OAuth,
    # while still exercising the real (offline) googleapiclient.discovery.build().
    monkeypatch.setattr(uploader_module, "get_credentials", lambda _config: Credentials(token="fake-token"))

    report = DailyPipeline(config).run(date(2026, 8, 9))

    assert report.errors == []
    from wta_daily.persistence.youtube_upload_store import YouTubeUploadStore

    record = YouTubeUploadStore(config.data_dir).get_upload(date(2026, 8, 9), config.tour)
    assert record is not None
    assert record.video_id == "real-flow-video-id"


def test_missing_tournament_data_does_not_crash_the_run(tmp_path: Path) -> None:
    """A day where nobody in the tracked group (or the featured player)
    played must still produce a complete, successful run - the thumbnail
    and description simply omit the tournament reference."""

    config = _make_featured_config(tmp_path, top_n=10)
    pipeline = DailyPipeline(config)
    pipeline._rankings_provider = _SyntheticRankingsProvider(_synthetic_rankings(28))
    pipeline._match_provider = _SyntheticMatchProvider(matches={})  # nobody played

    report = pipeline.run(date(2026, 8, 9))

    assert report.errors == []
    output_dir = config.output_dir / "2026-08-09"
    assert (output_dir / "thumbnail.png").exists()
    description = (output_dir / "youtube_description.txt").read_text()
    assert "None" not in description


# --- Official ranking vs. daily match activity -------------------------------
#
# These are the regression tests for the core architectural guarantee: a
# match result must never, by itself, cause the app to report an official
# ranking change - only an actual new official WTA ranking publication can.
# See wta_daily/movement.py and README.md's "Official ranking vs. daily
# match activity" section.


def _official_ranking(rank: int, player_id: str, name: str, points: int, ranking_date: date) -> PlayerRanking:
    return PlayerRanking(
        rank=rank,
        player_id=player_id,
        name=name,
        country_code="USA",
        points=points,
        ranking_date=ranking_date,
    )


def test_daily_win_does_not_change_official_ranking(tmp_path: Path) -> None:
    """Test 1: Player A official rank=4, Player B official rank=5. Player B
    wins a match and earns tournament points. Expected: ranks are
    unchanged, and movement is SAME, until a new official ranking list
    says otherwise."""

    config = _make_config(tmp_path)
    config.top_n = 2
    ranking_date = date(2026, 8, 10)
    rankings = [
        _official_ranking(4, "player-a", "Player A", 5000, ranking_date),
        _official_ranking(5, "player-b", "Player B", 4800, ranking_date),
    ]
    pipeline = DailyPipeline(config)
    pipeline._rankings_provider = _SyntheticRankingsProvider(rankings)
    pipeline._match_provider = _SyntheticMatchProvider()
    pipeline.run(date(2026, 8, 11))  # establishes the baseline snapshot

    win = MatchResult(
        opponent="Someone",
        tournament="Cincinnati",
        round="Quarterfinal",
        score="6-4 6-3",
        won=True,
        match_date=date(2026, 8, 11),
    )
    pipeline._match_provider = _SyntheticMatchProvider(matches={"player-b": win})
    report = pipeline.run(date(2026, 8, 12))

    by_id = {p.player_id: p for p in report.players}
    assert by_id["player-a"].rank == 4
    assert by_id["player-b"].rank == 5
    assert by_id["player-a"].movement == Movement.SAME
    assert by_id["player-b"].movement == Movement.SAME
    # The match is still reported as daily activity - just not as a ranking change.
    assert by_id["player-b"].match == win


def test_official_ranking_movement_forced_same_even_if_raw_numbers_wobble(
    tmp_path: Path,
) -> None:
    """Defensive/robustness case beyond Test 1: even if the *raw* rank
    numbers a provider returns were to differ slightly (a hypothetical
    transient upstream inconsistency), the app must still report SAME as
    long as the official ranking_date hasn't actually changed - this is
    the guarantee that makes "official movement" trustworthy rather than
    an accident of a stable-but-unverified upstream source."""

    config = _make_config(tmp_path)
    config.top_n = 2
    ranking_date = date(2026, 8, 10)
    pipeline = DailyPipeline(config)
    pipeline._rankings_provider = _SyntheticRankingsProvider(
        [
            _official_ranking(4, "player-a", "Player A", 5000, ranking_date),
            _official_ranking(5, "player-b", "Player B", 4800, ranking_date),
        ]
    )
    pipeline._match_provider = _SyntheticMatchProvider()
    pipeline.run(date(2026, 8, 11))

    # Same ranking_date, but (hypothetically) the numbers themselves wobbled.
    pipeline._rankings_provider = _SyntheticRankingsProvider(
        [
            _official_ranking(3, "player-a", "Player A", 5010, ranking_date),
            _official_ranking(6, "player-b", "Player B", 4790, ranking_date),
        ]
    )
    report = pipeline.run(date(2026, 8, 12))

    by_id = {p.player_id: p for p in report.players}
    assert by_id["player-a"].movement == Movement.SAME
    assert by_id["player-b"].movement == Movement.SAME


def test_new_official_ranking_publication_updates_positions_and_movement(
    tmp_path: Path,
) -> None:
    """Test 2: previous official list has A=4/B=5; a genuinely new official
    list has B=4/A=5. Expected: the app accepts the new ranking and
    identifies the movement correctly."""

    config = _make_config(tmp_path)
    config.top_n = 2
    pipeline = DailyPipeline(config)
    old_date = date(2026, 8, 10)
    pipeline._rankings_provider = _SyntheticRankingsProvider(
        [
            _official_ranking(4, "player-a", "Player A", 5000, old_date),
            _official_ranking(5, "player-b", "Player B", 4800, old_date),
        ]
    )
    pipeline._match_provider = _SyntheticMatchProvider()
    pipeline.run(date(2026, 8, 11))

    new_date = date(2026, 8, 17)
    pipeline._rankings_provider = _SyntheticRankingsProvider(
        [
            _official_ranking(4, "player-b", "Player B", 5100, new_date),
            _official_ranking(5, "player-a", "Player A", 4900, new_date),
        ]
    )
    report = pipeline.run(date(2026, 8, 18))

    by_id = {p.player_id: p for p in report.players}
    assert by_id["player-b"].rank == 4
    assert by_id["player-b"].previous_rank == 5
    assert by_id["player-b"].movement == Movement.UP
    assert by_id["player-a"].rank == 5
    assert by_id["player-a"].previous_rank == 4
    assert by_id["player-a"].movement == Movement.DOWN
    assert report.ranking_date == new_date


def test_narration_cannot_claim_ranking_changed_from_daily_match_alone(
    tmp_path: Path,
) -> None:
    """Test 3: a normal daily match result (no new official ranking) must
    never produce narration claiming the player's official ranking
    changed - no "moves up"/"climbs"/"takes over the No. X spot" wording."""

    config = _make_config(tmp_path)
    config.top_n = 2
    ranking_date = date(2026, 8, 10)
    pipeline = DailyPipeline(config)
    pipeline._rankings_provider = _SyntheticRankingsProvider(
        [
            _official_ranking(4, "player-a", "Player A", 5000, ranking_date),
            _official_ranking(5, "player-b", "Player B", 4800, ranking_date),
        ]
    )
    pipeline._match_provider = _SyntheticMatchProvider()
    pipeline.run(date(2026, 8, 11))

    win = MatchResult(
        opponent="Someone",
        tournament="Cincinnati",
        round="Final",
        score="6-4 6-3",
        won=True,
        match_date=date(2026, 8, 11),
    )
    pipeline._match_provider = _SyntheticMatchProvider(matches={"player-b": win})
    pipeline.run(date(2026, 8, 12))

    script = (config.output_dir / "2026-08-12" / "script.txt").read_text().lower()
    forbidden_phrases = [
        "moves up",
        "moved up",
        "move up",
        "climbs",
        "climbing",
        "moves down",
        "moved down",
        "falls to",
        "takes over the no",
        "rises to",
        "jumps up",
        "drops to",
        "slips to",
    ]
    for phrase in forbidden_phrases:
        assert phrase not in script, f"Unexpected ranking-movement wording {phrase!r} in: {script!r}"
    # The match itself is still described - only the ranking-movement
    # claim is forbidden, not the match result.
    assert "player b" in script or "Player B".lower() in script


def test_same_ranking_list_on_consecutive_days_keeps_same_ordering(
    tmp_path: Path,
) -> None:
    """Test 4: running the app on two consecutive days with the same
    official ranking source must produce the same Top N ordering, while
    still incorporating new match results into the later day's report."""

    config = _make_config(tmp_path)
    config.top_n = 2
    ranking_date = date(2026, 8, 10)
    rankings = [
        _official_ranking(4, "player-a", "Player A", 5000, ranking_date),
        _official_ranking(5, "player-b", "Player B", 4800, ranking_date),
    ]
    pipeline = DailyPipeline(config)
    pipeline._rankings_provider = _SyntheticRankingsProvider(rankings)
    pipeline._match_provider = _SyntheticMatchProvider()
    pipeline.run(date(2026, 8, 10))  # baseline snapshot

    # "Tuesday"
    pipeline._rankings_provider = _SyntheticRankingsProvider(rankings)
    pipeline._match_provider = _SyntheticMatchProvider()
    tuesday_report = pipeline.run(date(2026, 8, 11))

    # "Wednesday" - same official rankings, but Player B has a fresh match result.
    win = MatchResult(
        opponent="Someone",
        tournament="Cincinnati",
        round="Semifinal",
        score="7-5 6-2",
        won=True,
        match_date=date(2026, 8, 12),
    )
    pipeline._rankings_provider = _SyntheticRankingsProvider(rankings)
    pipeline._match_provider = _SyntheticMatchProvider(matches={"player-b": win})
    wednesday_report = pipeline.run(date(2026, 8, 13))

    tuesday_order = [p.player_id for p in tuesday_report.players]
    wednesday_order = [p.player_id for p in wednesday_report.players]
    assert tuesday_order == wednesday_order == ["player-a", "player-b"]

    tuesday_by_id = {p.player_id: p for p in tuesday_report.players}
    wednesday_by_id = {p.player_id: p for p in wednesday_report.players}
    assert tuesday_by_id["player-a"].rank == wednesday_by_id["player-a"].rank == 4
    assert tuesday_by_id["player-b"].rank == wednesday_by_id["player-b"].rank == 5
    assert tuesday_by_id["player-a"].movement == Movement.SAME
    assert tuesday_by_id["player-b"].movement == Movement.SAME
    assert wednesday_by_id["player-a"].movement == Movement.SAME
    assert wednesday_by_id["player-b"].movement == Movement.SAME

    # Wednesday's report incorporates the fresh match; Tuesday's does not.
    assert tuesday_by_id["player-b"].match is None
    assert wednesday_by_id["player-b"].match == win


def test_report_records_the_official_ranking_date(tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    config.top_n = 2
    ranking_date = date(2026, 8, 10)
    pipeline = DailyPipeline(config)
    pipeline._rankings_provider = _SyntheticRankingsProvider(
        [
            _official_ranking(1, "player-a", "Player A", 5000, ranking_date),
            _official_ranking(2, "player-b", "Player B", 4800, ranking_date),
        ]
    )
    pipeline._match_provider = _SyntheticMatchProvider()

    report = pipeline.run(date(2026, 8, 11))

    assert report.ranking_date == ranking_date
    saved = json.loads((config.output_dir / "2026-08-11" / "report.json").read_text())
    assert saved["ranking_date"] == "2026-08-10"


def test_unchanged_ranking_date_cannot_change_displayed_top_n_ordering_or_points(
    tmp_path: Path,
) -> None:
    """Regression test: even if a rankings fetch returns numbers that
    disagree with the previously saved snapshot (a hypothetical transient
    upstream inconsistency), an unchanged official ranking_date must never
    let that contradiction change the *displayed* Top N ordering or point
    totals - not just the Movement label. The app must not silently accept
    contradictory ranking data; it falls back to the previously saved,
    trusted values and records a clear warning."""

    config = _make_config(tmp_path)
    config.top_n = 2
    ranking_date = date(2026, 8, 10)
    pipeline = DailyPipeline(config)
    pipeline._rankings_provider = _SyntheticRankingsProvider(
        [
            _official_ranking(4, "player-a", "Player A", 5000, ranking_date),
            _official_ranking(5, "player-b", "Player B", 4800, ranking_date),
        ]
    )
    pipeline._match_provider = _SyntheticMatchProvider()
    pipeline.run(date(2026, 8, 11))  # establishes the trusted baseline snapshot

    # Same ranking_date, but the fetch now (hypothetically) disagrees with
    # the previously saved snapshot on both rank *and* points, and even
    # reverses the two players' relative order.
    pipeline._rankings_provider = _SyntheticRankingsProvider(
        [
            _official_ranking(6, "player-a", "Player A", 4790, ranking_date),
            _official_ranking(3, "player-b", "Player B", 5010, ranking_date),
        ]
    )
    report = pipeline.run(date(2026, 8, 12))

    # Displayed ordering and points must still match the trusted snapshot -
    # never the contradictory fetch.
    assert [p.player_id for p in report.players] == ["player-a", "player-b"]
    by_id = {p.player_id: p for p in report.players}
    assert by_id["player-a"].rank == 4
    assert by_id["player-a"].points == 5000
    assert by_id["player-b"].rank == 5
    assert by_id["player-b"].points == 4800
    assert by_id["player-a"].movement == Movement.SAME
    assert by_id["player-b"].movement == Movement.SAME

    # The contradiction was not silently accepted - it's recorded.
    assert any("Player A" in e and "official ranking" in e for e in report.errors)
    assert any("Player B" in e and "official ranking" in e for e in report.errors)

    # The trusted (not contradictory) values are what get persisted for
    # future comparisons too - the wobble is never allowed to propagate
    # forward into rankings-history.json.
    history = json.loads((config.data_dir / "rankings-history.json").read_text())
    saved_entry = next(e for e in history if e["date"] == "2026-08-12")
    saved_by_id = {r["player_id"]: r for r in saved_entry["rankings"]}
    assert saved_by_id["player-a"]["rank"] == 4
    assert saved_by_id["player-a"]["points"] == 5000
    assert saved_by_id["player-b"]["rank"] == 5
    assert saved_by_id["player-b"]["points"] == 4800


def test_ranking_date_is_none_for_providers_that_do_not_supply_one(tmp_path: Path) -> None:
    """The sample/offline provider (and any other provider that doesn't
    expose a ranking date) must not break anything - report.ranking_date
    stays None, and movement still falls back to plain rank comparison."""

    config = _make_config(tmp_path)  # uses the sample provider, no ranking_date

    report = DailyPipeline(config).run(date(2026, 8, 9))

    assert report.ranking_date is None


# --- Tournament-elimination narration context (end-to-end) ------------------


def test_tournament_status_flows_from_provider_into_report_and_narration(tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    config.top_n = 5
    pipeline = DailyPipeline(config)
    pipeline._rankings_provider = SampleRankingsProvider(fixture_path=SAMPLE_RANKINGS_FIXTURE)
    target_id = "sample-001"
    status = TournamentRunStatus(
        state=TournamentState.ELIMINATED,
        tournament="Cincinnati",
        tournament_group_id="1017",
        category="WTA 1000",
        round_reached="R16",
        round_label="the Round of 16",
        eliminated_by="Some Rival",
        points_earned=120,
        is_new_development=True,
    )
    pipeline._match_provider = _SyntheticMatchProvider(tournament_status={target_id: status})

    report = pipeline.run(date(2026, 8, 9))

    player = next(p for p in report.players if p.player_id == target_id)
    assert player.tournament_status is not None
    assert player.tournament_status.state == TournamentState.ELIMINATED
    assert player.tournament_status.round_reached == "R16"

    saved = json.loads((config.output_dir / "2026-08-09" / "report.json").read_text())
    saved_player = next(p for p in saved["players"] if p["player_id"] == target_id)
    assert saved_player["tournament_status"]["state"] == "eliminated"
    assert saved_player["tournament_status"]["eliminated_by"] == "Some Rival"

    script = (config.output_dir / "2026-08-09" / "script.txt").read_text()
    assert "Some Rival" in script
    assert "Round of 16" in script


def test_tournament_status_is_detailed_on_first_report_and_brief_afterward(tmp_path: Path) -> None:
    """End-to-end persistence check: the same elimination result reported
    on two separate pipeline runs (sharing the same data_dir) must be
    'detailed' the first time and 'brief' the second - see
    TournamentStatusStore."""

    config = _make_config(tmp_path)
    config.top_n = 5
    target_id = "sample-001"
    status = TournamentRunStatus(
        state=TournamentState.ELIMINATED,
        tournament="Cincinnati",
        tournament_group_id="1017",
        category="WTA 1000",
        round_reached="QF",
        round_label="the quarterfinals",
        eliminated_by="Some Rival",
        points_earned=215,
        is_new_development=True,  # provider always reports True; the store decides otherwise
    )

    pipeline = DailyPipeline(config)
    pipeline._match_provider = _SyntheticMatchProvider(tournament_status={target_id: status})
    first_report = pipeline.run(date(2026, 8, 9))
    first_player = next(p for p in first_report.players if p.player_id == target_id)
    assert first_player.tournament_status is not None
    assert first_player.tournament_status.is_new_development is True

    pipeline2 = DailyPipeline(config)  # fresh pipeline, same config.data_dir
    pipeline2._match_provider = _SyntheticMatchProvider(tournament_status={target_id: status})
    second_report = pipeline2.run(date(2026, 8, 10))
    second_player = next(p for p in second_report.players if p.player_id == target_id)
    assert second_player.tournament_status is not None
    assert second_player.tournament_status.is_new_development is False

    second_script = (config.output_dir / "2026-08-10" / "script.txt").read_text()
    # Brief mention only - the full detail (eliminator name, points figure)
    # shouldn't be repeated a second time.
    assert "215" not in second_script


def test_tournament_status_never_breaks_the_pipeline_when_absent(tmp_path: Path) -> None:
    """A match provider with no tournament-draw visibility (the ordinary
    sample/offline fixture) must produce identical Phase 1 behavior to
    before this feature existed - no tournament_status anywhere, no
    elimination language in the script."""

    config = _make_config(tmp_path)
    report = DailyPipeline(config).run(date(2026, 8, 9))

    assert all(p.tournament_status is None for p in report.players)
    script = (config.output_dir / "2026-08-09" / "script.txt").read_text()
    assert "eliminated by" not in script


def test_tournament_status_config_is_wired_into_match_provider_construction(tmp_path: Path) -> None:
    captured_kwargs: dict[str, object] = {}

    class _KwargCapturingMatchProvider(MatchProvider):
        def __init__(self, **kwargs: object) -> None:
            captured_kwargs.update(kwargs)

        def get_latest_match(self, player: PlayerRanking) -> MatchResult | None:
            return None

    matches_registry.register("kwarg-capturing-for-tests")(_KwargCapturingMatchProvider)
    config = _make_config(tmp_path)
    config.match_provider = ProviderConfig(name="kwarg-capturing-for-tests")
    config.tournament_status.enabled = False
    config.tournament_status.previous_year_lookback_enabled = False

    DailyPipeline(config)

    # The pipeline wires config.tournament_status straight into the match
    # provider's constructor kwargs, regardless of which provider is
    # configured - see DailyPipeline.__init__'s match_provider_kwargs.
    assert captured_kwargs["tournament_status_enabled"] is False
    assert captured_kwargs["tournament_status_previous_year_lookback_enabled"] is False


def test_featured_player_gets_tournament_status_context(tmp_path: Path) -> None:
    config = _make_featured_config(tmp_path)
    pipeline = DailyPipeline(config)
    pipeline._rankings_provider = _SyntheticRankingsProvider(_synthetic_rankings(28))
    status = TournamentRunStatus(
        state=TournamentState.CHAMPION,
        tournament="Cincinnati",
        round_reached="W",
        round_label="the title",
        points_earned=1000,
        is_new_development=True,
    )
    pipeline._match_provider = _SyntheticMatchProvider(tournament_status={EMMA_ID: status})

    report = pipeline.run(date(2026, 8, 9))

    assert report.featured_player is not None
    assert report.featured_player.tournament_status is not None
    assert report.featured_player.tournament_status.state == TournamentState.CHAMPION

    script = (config.output_dir / "2026-08-09" / "script.txt").read_text()
    assert "champion" in script.lower() or "title" in script.lower()
