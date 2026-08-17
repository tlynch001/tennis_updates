"""Unit tests for :mod:`wta_daily.tournament_context`."""

from __future__ import annotations

from datetime import date

from wta_daily.models import (
    DailyReport,
    FeaturedPlayerReport,
    MatchResult,
    Movement,
    PlayerReport,
)
from wta_daily.tournament_context import most_relevant_tournament


def _match(tournament: str) -> MatchResult:
    return MatchResult(
        opponent="Opponent",
        tournament=tournament,
        round="Round of 32",
        score="6-4 6-2",
        won=True,
        match_date=date(2026, 8, 15),
    )


def _player(rank: int, match: MatchResult | None) -> PlayerReport:
    return PlayerReport(
        rank=rank,
        name=f"Player {rank}",
        player_id=f"p{rank}",
        country_code="USA",
        points=1000 - rank,
        movement=Movement.SAME,
        match=match,
    )


def _report(players: list[PlayerReport], featured: FeaturedPlayerReport | None = None) -> DailyReport:
    return DailyReport(
        report_date=date(2026, 8, 16), tour="wta", players=players, featured_player=featured
    )


def test_returns_the_tournament_most_players_are_at() -> None:
    report = _report(
        [
            _player(1, _match("Cincinnati")),
            _player(2, _match("Cincinnati")),
            _player(3, _match("Cincinnati")),
            _player(4, _match("Montreal")),
        ]
    )

    assert most_relevant_tournament(report) == "Cincinnati"


def test_returns_none_when_nobody_played() -> None:
    report = _report([_player(1, None), _player(2, None)])

    assert most_relevant_tournament(report) is None


def test_returns_none_for_an_empty_player_list() -> None:
    report = _report([])

    assert most_relevant_tournament(report) is None


def test_includes_the_featured_players_match_in_the_count() -> None:
    featured = FeaturedPlayerReport(
        name="Emma Navarro",
        player_id="emma",
        tagline="america_favorite",
        rank=28,
        match=_match("Cincinnati"),
    )
    report = _report([_player(1, None), _player(2, None)], featured=featured)

    assert most_relevant_tournament(report) == "Cincinnati"


def test_breaks_ties_by_higher_ranked_player() -> None:
    """A tie between two tournaments is broken deterministically in favor
    of whichever appears first (i.e. the higher-ranked player)."""

    report = _report(
        [
            _player(1, _match("Cincinnati")),
            _player(2, _match("Montreal")),
        ]
    )

    assert most_relevant_tournament(report) == "Cincinnati"


def test_single_match_is_still_relevant() -> None:
    report = _report([_player(1, _match("Wimbledon")), _player(2, None)])

    assert most_relevant_tournament(report) == "Wimbledon"
