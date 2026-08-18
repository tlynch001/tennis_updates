"""Unit tests for :mod:`wta_daily.youtube_description`."""

from __future__ import annotations

from datetime import date

from wta_daily.models import (
    DailyReport,
    FeaturedPlayerReport,
    MatchResult,
    Movement,
    PlayerReport,
)
from wta_daily.youtube_description import generate_description


def _match(*, won: bool = True, opponent: str = "Opponent", tournament: str = "Cincinnati") -> MatchResult:
    return MatchResult(
        opponent=opponent,
        tournament=tournament,
        round="Round of 32",
        score="6-4 6-2",
        won=won,
        match_date=date(2026, 8, 15),
    )


def _player(rank: int, name: str, match: MatchResult | None = None) -> PlayerReport:
    return PlayerReport(
        rank=rank,
        name=name,
        player_id=f"p{rank}",
        country_code="USA",
        points=10_000 - rank * 100,
        movement=Movement.SAME,
        match=match,
    )


def _report(
    players: list[PlayerReport], featured: FeaturedPlayerReport | None = None
) -> DailyReport:
    return DailyReport(
        report_date=date(2026, 8, 16), tour="wta", players=players, featured_player=featured
    )


def test_contains_the_report_date() -> None:
    report = _report([_player(1, "Player One")])

    description = generate_description(report)

    assert "August 16, 2026" in description


def test_contains_the_full_top_n_list_in_order() -> None:
    players = [_player(i, f"Player {i}") for i in range(1, 11)]
    report = _report(players)

    description = generate_description(report)

    for player in players:
        assert f"{player.rank}. {player.name}" in description
    # In order: rank 1's line appears before rank 10's.
    assert description.index("1. Player 1") < description.index("10. Player 10")


def test_includes_the_relevant_tournament_when_available() -> None:
    report = _report([_player(1, "Player One", _match(tournament="Cincinnati"))])

    description = generate_description(report)

    assert "Cincinnati" in description


def test_omits_tournament_sentence_gracefully_when_unavailable() -> None:
    report = _report([_player(1, "Player One", None)])

    description = generate_description(report)

    assert "Cincinnati" not in description
    assert "Today's update covers the latest WTA Top 1 rankings." in description


def test_includes_featured_player_when_configured_and_resolved() -> None:
    featured = FeaturedPlayerReport(
        name="Emma Navarro",
        player_id="emma",
        tagline="america_favorite",
        rank=28,
        previous_rank=30,
        movement=Movement.UP,
        match=_match(won=True, opponent="Anhelina Kalinina", tournament="Cincinnati"),
    )
    report = _report([_player(1, "Player One")], featured=featured)

    description = generate_description(report)

    assert "Featured Player: Emma Navarro" in description
    assert "No. 28" in description
    assert "up from No. 30" in description
    assert "Anhelina Kalinina" in description


def test_featured_player_direction_annotation_requires_up_or_down_movement() -> None:
    """The '(up from/down from No. Y)' annotation must come from the
    already-computed Movement, never from independently comparing raw rank
    numbers - a rank/previous_rank mismatch with movement=SAME (e.g. an
    official ranking list that hasn't changed) must never be annotated as
    if it were a genuine change."""

    featured = FeaturedPlayerReport(
        name="Emma Navarro",
        player_id="emma",
        tagline="america_favorite",
        rank=28,
        previous_rank=30,
        movement=Movement.SAME,
    )
    report = _report([_player(1, "Player One")], featured=featured)

    description = generate_description(report)

    assert "up from" not in description
    assert "down from" not in description


def test_omits_featured_player_section_when_not_configured() -> None:
    report = _report([_player(1, "Player One")])

    description = generate_description(report)

    assert "Featured Player" not in description


def test_omits_featured_player_section_when_rank_unavailable() -> None:
    """Never fabricate a featured-player blurb when we couldn't even
    confirm her rank this run."""

    featured = FeaturedPlayerReport(
        name="Emma Navarro", player_id="emma", tagline="america_favorite", rank_error="timeout"
    )
    report = _report([_player(1, "Player One")], featured=featured)

    description = generate_description(report)

    assert "Featured Player" not in description


def test_featured_player_no_match_does_not_fabricate_a_result() -> None:
    featured = FeaturedPlayerReport(
        name="Emma Navarro", player_id="emma", tagline="america_favorite", rank=28, match=None
    )
    report = _report([_player(1, "Player One")], featured=featured)

    description = generate_description(report)

    assert "Featured Player: Emma Navarro" in description
    assert "did not play" in description.lower()
    assert "defeated" not in description.lower()
    assert "fell to" not in description.lower()


def test_featured_player_match_error_is_reported_honestly() -> None:
    featured = FeaturedPlayerReport(
        name="Emma Navarro",
        player_id="emma",
        tagline="america_favorite",
        rank=28,
        match=None,
        match_error="all sources failed",
    )
    report = _report([_player(1, "Player One")], featured=featured)

    description = generate_description(report)

    assert "not confirmed" in description.lower()


def test_does_not_include_urls_handles_or_calls_to_action() -> None:
    report = _report([_player(1, "Player One")])

    description = generate_description(report)

    assert "http" not in description.lower()
    assert "@" not in description
    assert "subscribe" not in description.lower()


def test_ends_with_a_generic_closing_line() -> None:
    report = _report([_player(1, "Player One")])

    description = generate_description(report)

    assert description.strip().endswith("updates.")


def test_changes_with_different_daily_data() -> None:
    report_a = _report([_player(1, "Player One", _match(tournament="Cincinnati"))])
    report_b = _report([_player(1, "Player Two", _match(tournament="Montreal"))])

    assert generate_description(report_a) != generate_description(report_b)
