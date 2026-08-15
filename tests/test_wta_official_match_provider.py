"""Unit tests for :mod:`wta_daily.plugins.matches.wta_official`.

These mock the underlying :class:`WtaOfficialApiClient` calls (never hitting
the network) with response shapes captured from the real API, and are the
regression suite for the August 2026 production incident: tournament start
dates being reported as match dates, and stale/incomplete player-match
history not being handled defensively.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from wta_daily.exceptions import PlayerDataError
from wta_daily.models import PlayerRanking
from wta_daily.plugins.matches.wta_official import WtaOfficialMatchProvider

PLAYER = PlayerRanking(rank=1, player_id="P1", name="Test Player", country_code="USA", points=8000)


def _player_match(
    *,
    round_name: str = "R16",
    scores: str = "6-4 6-2",
    winner: int = 1,
    s_d_flag: str = "S",
    opponent_id: str | None = "P2",
    opponent_name: str = "Opponent Name",
    tournament_name: str = "SAMPLE OPEN",
    tournament_group_id: int | None = 900,
    tournament_year: int | None = 2026,
    tournament_start_date: str = "2026-01-01T00:00:00+00:00",
    surface: str = "HARD",
) -> dict[str, Any]:
    """Build one entry shaped like ``GET /players/{id}/matches`` returns."""

    return {
        "s_d_flag": s_d_flag,
        "scores": scores,
        "player_1": "P1",
        "player_2": "P2",
        "winner": winner,
        "opponent": ({"id": opponent_id, "fullName": opponent_name} if opponent_id else None),
        "team_name_2": opponent_name,
        "TournamentName": tournament_name,
        "round_name": round_name,
        "Surface": surface,
        # The buggy old behavior copied this straight into match_date - it
        # must never end up as the reported match_date.
        "StartDate": tournament_start_date,
        "tournament": {
            "tournamentGroup": {"id": tournament_group_id},
            "year": tournament_year,
            "startDate": tournament_start_date[:10],
        },
    }


def _tournament_fixture(
    *,
    player_a: str = "P1",
    player_b: str = "P2",
    match_state: str = "F",
    match_timestamp: str | None = "2026-01-05T18:30:00+00:00",
    draw_match_type: str = "S",
) -> dict[str, Any]:
    """Build one entry shaped like ``GET /tournaments/{id}/{year}/matches`` returns."""

    return {
        "DrawMatchType": draw_match_type,
        "PlayerIDA": player_a,
        "PlayerIDB": player_b,
        "MatchState": match_state,
        "MatchTimeStamp": match_timestamp,
    }


def _provider_with_mocked_client(
    monkeypatch: pytest.MonkeyPatch,
    player_matches: list[dict[str, Any]],
    tournament_matches: list[dict[str, Any]] | None = None,
) -> WtaOfficialMatchProvider:
    provider = WtaOfficialMatchProvider()
    monkeypatch.setattr(
        provider._client, "get_player_matches", lambda player_id, page_size=25: player_matches
    )

    def _fake_get_tournament_matches(group_id: Any, year: Any, *, page_size: int = 500) -> list[dict]:
        if tournament_matches is None:
            raise RuntimeError("simulated tournament-matches endpoint failure")
        return tournament_matches

    monkeypatch.setattr(provider._client, "get_tournament_matches", _fake_get_tournament_matches)
    return provider


def test_match_date_comes_from_tournament_feed_not_tournament_start_date(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The core regression test: StartDate must never leak into match_date."""

    provider = _provider_with_mocked_client(
        monkeypatch,
        player_matches=[_player_match(tournament_start_date="2026-01-01T00:00:00+00:00")],
        tournament_matches=[_tournament_fixture(match_timestamp="2026-01-08T14:00:00+00:00")],
    )

    result = provider.get_latest_match(PLAYER)

    assert result is not None
    assert result.match_date == date(2026, 1, 8)
    assert result.match_date != date(2026, 1, 1)  # the tournament start date


def test_match_date_is_none_when_fixture_not_found_in_tournament_feed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Stale/incomplete tournament-level data must degrade to null, not a guess."""

    provider = _provider_with_mocked_client(
        monkeypatch,
        player_matches=[_player_match()],
        # The tournament feed doesn't (yet) have this fixture at all.
        tournament_matches=[],
    )

    result = provider.get_latest_match(PLAYER)

    assert result is not None
    assert result.match_date is None
    # Everything else the player-matches endpoint gave us is still reported.
    assert result.opponent == "Opponent Name"
    assert result.tournament == "Sample Open"


def test_match_date_is_none_when_tournament_endpoint_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    """A transient failure enriching the date must never fail the whole match lookup."""

    provider = _provider_with_mocked_client(
        monkeypatch,
        player_matches=[_player_match()],
        tournament_matches=None,  # simulates the enrichment call raising
    )

    result = provider.get_latest_match(PLAYER)

    assert result is not None
    assert result.match_date is None
    assert result.opponent == "Opponent Name"


def test_match_date_is_none_when_missing_match_timestamp(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = _provider_with_mocked_client(
        monkeypatch,
        player_matches=[_player_match()],
        tournament_matches=[_tournament_fixture(match_timestamp=None)],
    )

    result = provider.get_latest_match(PLAYER)

    assert result is not None
    assert result.match_date is None


def test_match_date_is_none_when_fixture_not_yet_finished(monkeypatch: pytest.MonkeyPatch) -> None:
    """A fixture the tournament feed hasn't marked finished must not be trusted."""

    provider = _provider_with_mocked_client(
        monkeypatch,
        player_matches=[_player_match()],
        tournament_matches=[_tournament_fixture(match_state="P")],
    )

    result = provider.get_latest_match(PLAYER)

    assert result is not None
    assert result.match_date is None


def test_byes_are_never_selected_as_the_latest_match(monkeypatch: pytest.MonkeyPatch) -> None:
    bye = _player_match(scores="", opponent_id=None, opponent_name="")
    bye["opponent"] = None
    real_match = _player_match(round_name="R32", scores="6-1 6-2", opponent_name="Real Opponent")

    provider = _provider_with_mocked_client(
        monkeypatch,
        player_matches=[bye, real_match],
        tournament_matches=[_tournament_fixture()],
    )

    result = provider.get_latest_match(PLAYER)

    assert result is not None
    assert result.opponent == "Real Opponent"


def test_walkovers_are_never_selected_as_the_latest_match(monkeypatch: pytest.MonkeyPatch) -> None:
    """A walkover/default has an opponent listed but no real score - not a played match."""

    walkover = _player_match(scores="", opponent_name="Withdrew Opponent")
    real_match = _player_match(round_name="R32", scores="7-5 6-3", opponent_name="Real Opponent")

    provider = _provider_with_mocked_client(
        monkeypatch,
        player_matches=[walkover, real_match],
        tournament_matches=[_tournament_fixture()],
    )

    result = provider.get_latest_match(PLAYER)

    assert result is not None
    assert result.opponent == "Real Opponent"


def test_doubles_matches_are_filtered_out(monkeypatch: pytest.MonkeyPatch) -> None:
    doubles_match = _player_match(s_d_flag="D", opponent_name="Doubles Opponent")
    singles_match = _player_match(round_name="R32", opponent_name="Singles Opponent")

    provider = _provider_with_mocked_client(
        monkeypatch,
        player_matches=[doubles_match, singles_match],
        tournament_matches=[_tournament_fixture()],
    )

    result = provider.get_latest_match(PLAYER)

    assert result is not None
    assert result.opponent == "Singles Opponent"


def test_no_singles_matches_at_all_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = _provider_with_mocked_client(
        monkeypatch,
        player_matches=[_player_match(s_d_flag="D")],
        tournament_matches=[],
    )

    assert provider.get_latest_match(PLAYER) is None


def test_get_latest_match_raises_player_data_error_on_provider_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The outer player-matches call failing is real data loss and must be surfaced
    (the pipeline catches PlayerDataError per player - see test_pipeline_integration.py)."""

    provider = WtaOfficialMatchProvider()

    def _boom(player_id: str, page_size: int = 25) -> list[dict]:
        raise RuntimeError("network exploded")

    monkeypatch.setattr(provider._client, "get_player_matches", _boom)

    with pytest.raises(PlayerDataError):
        provider.get_latest_match(PLAYER)


def test_tournament_matches_are_cached_across_players_in_one_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Several Top N players often share a recent tournament; don't refetch it per player."""

    provider = WtaOfficialMatchProvider()
    call_count = 0

    def _get_player_matches(player_id: str, page_size: int = 25) -> list[dict]:
        return [_player_match()]

    def _get_tournament_matches(group_id: Any, year: Any, *, page_size: int = 500) -> list[dict]:
        nonlocal call_count
        call_count += 1
        return [_tournament_fixture()]

    monkeypatch.setattr(provider._client, "get_player_matches", _get_player_matches)
    monkeypatch.setattr(provider._client, "get_tournament_matches", _get_tournament_matches)

    provider.get_latest_match(PLAYER)
    provider.get_latest_match(
        PlayerRanking(rank=2, player_id="P3", name="Other", country_code="FRA", points=7000)
    )

    assert call_count == 1


def test_player_2_slot_without_opponent_id_still_reports_match_with_null_date(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When our player is in the player_2 slot, the API gives us no opponent id, so
    date enrichment can't run - the rest of the match must still be reported."""

    match = _player_match()
    match["player_1"] = "SOMEONE_ELSE"
    match["player_2"] = "P1"
    match["opponent"] = None  # API only ever populates "opponent" relative to player_1
    match["team_name_1"] = "Someone Else"
    match["winner"] = 2  # player_2 (our player) won

    provider = _provider_with_mocked_client(
        monkeypatch, player_matches=[match], tournament_matches=[_tournament_fixture()]
    )

    result = provider.get_latest_match(PLAYER)

    assert result is not None
    assert result.won is True
    assert result.match_date is None
    assert result.opponent == "Someone Else"
