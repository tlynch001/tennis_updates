from __future__ import annotations

from datetime import date

from wta_daily.models import DailyReport, MatchResult, Movement, PlayerRanking, PlayerReport


def test_player_ranking_round_trip() -> None:
    ranking = PlayerRanking(
        rank=1, player_id="p1", name="Test Player", country_code="USA", points=1000
    )
    restored = PlayerRanking.from_dict(ranking.to_dict())
    assert restored == ranking


def test_match_result_round_trip() -> None:
    match = MatchResult(
        opponent="Opponent",
        tournament="Test Open",
        round="Final",
        score="6-4 6-4",
        won=True,
        match_date=date(2026, 8, 1),
        surface="Hard",
    )
    restored = MatchResult.from_dict(match.to_dict())
    assert restored == match


def test_match_result_allows_null_match_date() -> None:
    """A match can be fully known (opponent/score/round/tournament) while its
    exact date is unconfirmed - this must serialize as JSON ``null``, never a
    guessed/substituted date such as the tournament's start date."""

    match = MatchResult(
        opponent="Opponent",
        tournament="Test Open",
        round="Final",
        score="6-4 6-4",
        won=True,
        match_date=None,
    )
    data = match.to_dict()
    assert data["date"] is None

    restored = MatchResult.from_dict(data)
    assert restored.match_date is None
    assert restored == match


def test_player_report_round_trip_with_match() -> None:
    match = MatchResult(
        opponent="Opponent",
        tournament="Test Open",
        round="Final",
        score="6-4 6-4",
        won=True,
        match_date=date(2026, 8, 1),
        surface="Hard",
    )
    report = PlayerReport(
        rank=2,
        name="Test Player",
        player_id="p2",
        country_code="ESP",
        points=5000,
        movement=Movement.UP,
        previous_rank=4,
        match=match,
    )
    restored = PlayerReport.from_dict(report.to_dict())
    assert restored.rank == report.rank
    assert restored.movement == Movement.UP
    assert restored.match == match
    assert restored.played is True
    assert restored.won is True


def test_player_report_round_trip_with_match_but_unconfirmed_date() -> None:
    match = MatchResult(
        opponent="Opponent",
        tournament="Test Open",
        round="Final",
        score="6-4 6-4",
        won=True,
        match_date=None,
    )
    report = PlayerReport(
        rank=3,
        name="Unconfirmed Date Player",
        player_id="p3",
        country_code="ITA",
        points=4500,
        movement=Movement.SAME,
        previous_rank=3,
        match=match,
    )
    data = report.to_dict()
    assert data["match_date"] is None
    assert data["opponent"] == "Opponent"  # the rest of the match is still reported

    restored = PlayerReport.from_dict(data)
    assert restored.played is True
    assert restored.match is not None
    assert restored.match.match_date is None


def test_player_report_round_trip_without_match() -> None:
    report = PlayerReport(
        rank=5,
        name="No Match Player",
        player_id="p5",
        country_code="FRA",
        points=3000,
        movement=Movement.SAME,
        previous_rank=5,
        match=None,
        match_error="network timeout",
    )
    restored = PlayerReport.from_dict(report.to_dict())
    assert restored.played is False
    assert restored.won is None
    assert restored.match_error == "network timeout"


def test_daily_report_round_trip() -> None:
    report = DailyReport(
        report_date=date(2026, 8, 9),
        tour="wta",
        players=[
            PlayerReport(
                rank=1,
                name="Player A",
                player_id="a",
                country_code="USA",
                points=8000,
                movement=Movement.NEW,
            )
        ],
        errors=["something minor"],
    )
    restored = DailyReport.from_dict(report.to_dict())
    assert restored.report_date == report.report_date
    assert restored.tour == "wta"
    assert len(restored.players) == 1
    assert restored.errors == ["something minor"]


def test_movement_arrow_labels() -> None:
    assert Movement.UP.arrow == "\u2191"
    assert Movement.DOWN.arrow == "\u2193"
    assert Movement.SAME.arrow == "\u2014"
    assert Movement.NEW.arrow == "NEW"
    assert Movement.UNKNOWN.arrow == "?"


def test_movement_new_and_unknown_are_distinct_values() -> None:
    """These must never be conflated - see Movement's docstring."""

    assert Movement.NEW != Movement.UNKNOWN
    assert Movement.NEW.value == "new"
    assert Movement.UNKNOWN.value == "unknown"
