from __future__ import annotations

from datetime import date

from wta_daily.models import (
    DailyReport,
    FeaturedPlayerReport,
    MatchLookupResult,
    MatchResult,
    Movement,
    PlayerRanking,
    PlayerReport,
)


def test_player_ranking_round_trip() -> None:
    ranking = PlayerRanking(
        rank=1, player_id="p1", name="Test Player", country_code="USA", points=1000
    )
    restored = PlayerRanking.from_dict(ranking.to_dict())
    assert restored == ranking
    assert restored.ranking_date is None


def test_player_ranking_round_trip_with_ranking_date() -> None:
    ranking = PlayerRanking(
        rank=1,
        player_id="p1",
        name="Test Player",
        country_code="USA",
        points=1000,
        ranking_date=date(2026, 8, 10),
    )
    data = ranking.to_dict()
    assert data["ranking_date"] == "2026-08-10"

    restored = PlayerRanking.from_dict(data)
    assert restored == ranking
    assert restored.ranking_date == date(2026, 8, 10)


def test_player_ranking_legacy_data_without_ranking_date_defaults_to_none() -> None:
    """A rankings-history.json entry written before this field existed must
    still load fine."""

    legacy_data = {
        "rank": 1,
        "player_id": "p1",
        "name": "Test Player",
        "country_code": "USA",
        "points": 1000,
    }

    restored = PlayerRanking.from_dict(legacy_data)

    assert restored.ranking_date is None


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
        match_target_date=date(2026, 8, 8),
    )
    data = report.to_dict()
    assert data["match_target_date"] == "2026-08-08"

    restored = DailyReport.from_dict(data)
    assert restored.report_date == report.report_date
    assert restored.tour == "wta"
    assert len(restored.players) == 1
    assert restored.errors == ["something minor"]
    assert restored.match_target_date == date(2026, 8, 8)


def test_daily_report_round_trip_includes_ranking_date() -> None:
    report = DailyReport(
        report_date=date(2026, 8, 17),
        tour="wta",
        players=[],
        ranking_date=date(2026, 8, 10),
    )
    data = report.to_dict()
    assert data["ranking_date"] == "2026-08-10"

    restored = DailyReport.from_dict(data)
    assert restored.ranking_date == date(2026, 8, 10)


def test_daily_report_ranking_date_defaults_to_none_for_old_reports() -> None:
    """report.json files written before this field existed must still load."""

    legacy_data = {
        "date": "2026-08-09",
        "tour": "wta",
        "players": [],
        "errors": [],
    }

    restored = DailyReport.from_dict(legacy_data)

    assert restored.ranking_date is None
    assert restored.to_dict()["ranking_date"] is None


def test_daily_report_match_target_date_defaults_to_none_for_old_reports() -> None:
    """report.json files written before this field existed must still load."""

    legacy_data = {
        "date": "2026-08-09",
        "tour": "wta",
        "players": [],
        "errors": [],
    }

    restored = DailyReport.from_dict(legacy_data)

    assert restored.match_target_date is None
    assert restored.to_dict()["match_target_date"] is None


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


def test_featured_player_report_round_trip_with_match() -> None:
    match = MatchResult(
        opponent="Opponent",
        tournament="Cincinnati",
        round="Round of 32",
        score="6-4 6-2",
        won=True,
        match_date=date(2026, 8, 15),
    )
    featured = FeaturedPlayerReport(
        name="Emma Navarro",
        player_id="325410",
        tagline="america_favorite",
        country_code="USA",
        rank=14,
        points=1800,
        movement=Movement.UP,
        previous_rank=16,
        match=match,
    )
    restored = FeaturedPlayerReport.from_dict(featured.to_dict())

    assert restored.name == "Emma Navarro"
    assert restored.rank == 14
    assert restored.movement == Movement.UP
    assert restored.match == match
    assert restored.played is True
    assert restored.won is True


def test_featured_player_report_without_rank_is_not_fabricated() -> None:
    """When the rank couldn't be determined this run, `played`/`won` must
    stay unknown rather than defaulting to a guessed value."""

    featured = FeaturedPlayerReport(
        name="Emma Navarro",
        player_id="325410",
        tagline="america_favorite",
        rank_error="network timeout",
    )
    data = featured.to_dict()

    assert data["rank"] is None
    assert data["played"] is None
    assert data["won"] is None
    assert data["rank_error"] == "network timeout"

    restored = FeaturedPlayerReport.from_dict(data)
    assert restored.rank is None
    assert restored.played is None


def test_featured_player_report_no_match_is_a_confirmed_false_not_none() -> None:
    """A known rank but no match on the target date means `played: false` -
    distinct from an unknown rank, where `played` is `None`."""

    featured = FeaturedPlayerReport(
        name="Emma Navarro", player_id="325410", tagline="america_favorite", rank=28
    )
    data = featured.to_dict()

    assert data["rank"] == 28
    assert data["played"] is False
    assert data["won"] is None


def test_daily_report_round_trip_includes_featured_player() -> None:
    featured = FeaturedPlayerReport(
        name="Emma Navarro", player_id="325410", tagline="america_favorite", rank=14, points=1800
    )
    report = DailyReport(
        report_date=date(2026, 8, 16),
        tour="wta",
        players=[],
        featured_player=featured,
    )
    data = report.to_dict()
    assert data["featured_player"]["name"] == "Emma Navarro"

    restored = DailyReport.from_dict(data)
    assert restored.featured_player is not None
    assert restored.featured_player.rank == 14


def test_daily_report_featured_player_defaults_to_none() -> None:
    """Old report.json files (or the feature simply disabled) must load fine."""

    legacy_data = {"date": "2026-08-09", "tour": "wta", "players": [], "errors": []}

    restored = DailyReport.from_dict(legacy_data)

    assert restored.featured_player is None
    assert restored.to_dict()["featured_player"] is None


def test_match_lookup_result_defaults_to_empty() -> None:
    result = MatchLookupResult()
    assert result.matches == {}
    assert result.unresolved_player_ids == frozenset()


def test_match_lookup_result_distinguishes_confirmed_negative_from_unresolved() -> None:
    """A player_id absent from both fields is a confirmed 'did not play' -
    distinct from one explicitly listed as unresolved, which a composite
    provider should keep trying other sources for. See the module docstring
    and BestOfMatchProvider for why this distinction matters."""

    match = MatchResult(
        opponent="Opponent",
        tournament="Test Open",
        round="Final",
        score="6-4 6-4",
        won=True,
        match_date=date(2026, 8, 15),
    )
    result = MatchLookupResult(matches={"p1": match}, unresolved_player_ids=frozenset({"p2"}))

    assert "p1" in result.matches
    assert "p2" not in result.matches
    assert "p2" in result.unresolved_player_ids
    # p3 was checked and confirmed not to have played - neither dict mentions her.
    assert "p3" not in result.matches
    assert "p3" not in result.unresolved_player_ids
