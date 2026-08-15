"""Unit tests for :mod:`wta_daily.plugins.matches.live_tennis_api`.

These mock :class:`LiveTennisApiClient` directly (never hitting the network
and never needing a real API key), with response shapes captured from the
real API during development - including the confirmed per-player coverage
gap that motivated :mod:`wta_daily.plugins.matches.best_of`.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from wta_daily.exceptions import ConfigurationError, PlayerDataError
from wta_daily.models import PlayerRanking
from wta_daily.plugins.matches.live_tennis_api import LiveTennisApiMatchProvider

PLAYER = PlayerRanking(rank=1, player_id="320760", name="Aryna Sabalenka", country_code="BLR", points=8670)


def _player_record(
    *, id: int = 55, name: str = "Aryna Sabalenka", is_doubles_team: bool = False, ranking: int | None = 1
) -> dict[str, Any]:
    return {
        "id": id,
        "name": name,
        "is_doubles_team": is_doubles_team,
        "ranking": ranking,
        "ranking_points": 8000 if ranking else None,
        "tour": "wta",
        "country": None,
    }


def _match_record(
    *,
    match_id: int = 172280,
    our_player_id: int = 55,
    our_slot: int = 2,
    opponent_id: int = 45,
    opponent_name: str = "Ekaterina Alexandrova",
    scheduled_time: str | None = "2026-08-08T23:10:00Z",
    tournament: str = "Toronto",
    round_code: str | None = "R16",
    round_label: str = "WTA Toronto - 1/8-finals",
    games: list[list[int]] | None = None,
    winner: int | None = 1,
    is_doubles: bool = False,
    status: str = "completed",
    event_status: str | None = "Finished",
    surface: str = "hard",
) -> dict[str, Any]:
    our_record = {"id": our_player_id, "name": PLAYER.name}
    opponent_record = {"id": opponent_id, "name": opponent_name}
    players = (
        {"p1": opponent_record, "p2": our_record}
        if our_slot == 2
        else {"p1": our_record, "p2": opponent_record}
    )
    return {
        "id": match_id,
        "players": players,
        "tournament": tournament,
        "round_code": round_code,
        "round": round_label,
        "scheduled_time": scheduled_time,
        "score": {"games": games if games is not None else [[7, 4, 6], [6, 6, 4]]},
        "winner": winner,
        "is_doubles": is_doubles,
        "status": status,
        "event_status": event_status,
        "surface": surface,
    }


def _provider_with_mocked_client(
    monkeypatch: pytest.MonkeyPatch,
    *,
    search_results: list[dict[str, Any]],
    match_history: list[dict[str, Any]],
) -> LiveTennisApiMatchProvider:
    monkeypatch.setenv("LIVETENNISAPI_KEY", "twjp_test_key_not_real")
    provider = LiveTennisApiMatchProvider()
    monkeypatch.setattr(provider._client, "search_players", lambda name, limit=10: search_results)
    monkeypatch.setattr(
        provider._client, "get_completed_matches", lambda player_id, limit=20: match_history
    )
    return provider


def test_missing_api_key_raises_configuration_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LIVETENNISAPI_KEY", raising=False)

    with pytest.raises(ConfigurationError):
        LiveTennisApiMatchProvider()


def test_resolves_name_to_id_and_returns_match(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = _provider_with_mocked_client(
        monkeypatch,
        search_results=[_player_record()],
        match_history=[_match_record()],
    )

    result = provider.get_latest_match(PLAYER)

    assert result is not None
    assert result.opponent == "Ekaterina Alexandrova"
    assert result.tournament == "Toronto"
    assert result.round == "Round of 16"
    assert result.match_date == date(2026, 8, 8)
    assert result.won is False  # winner=1 (p1=opponent), our player is p2
    assert result.surface == "Hard"


def test_score_is_formatted_from_our_players_perspective(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = _provider_with_mocked_client(
        monkeypatch,
        search_results=[_player_record()],
        match_history=[_match_record(games=[[7, 4, 6], [6, 6, 4]])],
    )

    result = provider.get_latest_match(PLAYER)

    assert result is not None
    # our player is p2 with per-set games [6, 6, 4] vs opponent's [7, 4, 6].
    assert result.score == "6-7 6-4 4-6"


def test_doubles_team_search_results_are_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    doubles_noise = _player_record(id=13386, name="Marozava / Sabalenka", is_doubles_team=True, ranking=None)
    real_player = _player_record(id=55, name="Aryna Sabalenka", ranking=1)
    provider = _provider_with_mocked_client(
        monkeypatch,
        search_results=[doubles_noise, real_player],
        match_history=[_match_record(our_player_id=55)],
    )

    result = provider.get_latest_match(PLAYER)

    assert result is not None  # resolved to the real (non-doubles) player, not the noise entry


def test_unranked_namesake_is_not_preferred_over_ranked_player(monkeypatch: pytest.MonkeyPatch) -> None:
    """Regression test for the real 'Karolina Muchova' duplicate-record case."""

    unranked_duplicate = _player_record(id=8784, name="Karolina Muchova", ranking=None)
    real_player = _player_record(id=61, name="Karolina Muchova", ranking=9)
    provider = _provider_with_mocked_client(
        monkeypatch,
        search_results=[unranked_duplicate, real_player],
        match_history=[_match_record(our_player_id=61, opponent_id=99)],
    )

    player = PlayerRanking(
        rank=7, player_id="322191", name="Karolina Muchova", country_code="CZE", points=5048
    )
    result = provider.get_latest_match(player)

    assert result is not None  # only resolves to a match if it picked id=61, not the unranked id=8784


def test_no_player_match_found_raises_player_data_error(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = _provider_with_mocked_client(monkeypatch, search_results=[], match_history=[])

    with pytest.raises(PlayerDataError):
        provider.get_latest_match(PLAYER)


def test_only_doubles_team_search_results_raises_player_data_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _provider_with_mocked_client(
        monkeypatch,
        search_results=[_player_record(is_doubles_team=True, ranking=None)],
        match_history=[],
    )

    with pytest.raises(PlayerDataError):
        provider.get_latest_match(PLAYER)


def test_doubles_matches_are_filtered_out(monkeypatch: pytest.MonkeyPatch) -> None:
    doubles_match = _match_record(is_doubles=True, opponent_name="Doubles Opponent")
    singles_match = _match_record(round_code="R32", opponent_name="Singles Opponent")
    provider = _provider_with_mocked_client(
        monkeypatch, search_results=[_player_record()], match_history=[doubles_match, singles_match]
    )

    result = provider.get_latest_match(PLAYER)

    assert result is not None
    assert result.opponent == "Singles Opponent"


def test_walkovers_and_cancellations_are_filtered_out(monkeypatch: pytest.MonkeyPatch) -> None:
    walkover = _match_record(event_status="Walk Over", opponent_name="Walkover Opponent")
    cancelled = _match_record(event_status="Cancelled", opponent_name="Cancelled Opponent")
    real_match = _match_record(round_code="R32", opponent_name="Real Opponent", event_status="Finished")
    provider = _provider_with_mocked_client(
        monkeypatch,
        search_results=[_player_record()],
        match_history=[walkover, cancelled, real_match],
    )

    result = provider.get_latest_match(PLAYER)

    assert result is not None
    assert result.opponent == "Real Opponent"


def test_retirements_are_still_selected_as_the_latest_match(monkeypatch: pytest.MonkeyPatch) -> None:
    retired_match = _match_record(event_status="Retired", opponent_name="Retirement Opponent")
    provider = _provider_with_mocked_client(
        monkeypatch, search_results=[_player_record()], match_history=[retired_match]
    )

    result = provider.get_latest_match(PLAYER)

    assert result is not None
    assert result.opponent == "Retirement Opponent"


def test_non_completed_matches_are_skipped(monkeypatch: pytest.MonkeyPatch) -> None:
    upcoming = _match_record(status="upcoming", opponent_name="Future Opponent")
    completed = _match_record(round_code="R32", opponent_name="Past Opponent")
    provider = _provider_with_mocked_client(
        monkeypatch, search_results=[_player_record()], match_history=[upcoming, completed]
    )

    result = provider.get_latest_match(PLAYER)

    assert result is not None
    assert result.opponent == "Past Opponent"


def test_missing_scheduled_time_yields_null_match_date(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = _provider_with_mocked_client(
        monkeypatch, search_results=[_player_record()], match_history=[_match_record(scheduled_time=None)]
    )

    result = provider.get_latest_match(PLAYER)

    assert result is not None
    assert result.match_date is None


def test_stale_coverage_still_returns_the_best_available_match(monkeypatch: pytest.MonkeyPatch) -> None:
    """This provider has no way to know its own data is stale for a given
    player - it just reports whatever it has. That's exactly why BestOfMatchProvider
    exists (see tests/test_best_of_match_provider.py); this test documents
    the behavior in isolation."""

    old_match = _match_record(scheduled_time="2026-03-21T20:05:00Z", tournament="Miami")
    provider = _provider_with_mocked_client(
        monkeypatch, search_results=[_player_record()], match_history=[old_match]
    )

    result = provider.get_latest_match(PLAYER)

    assert result is not None
    assert result.match_date == date(2026, 3, 21)


def test_history_lookup_failure_raises_player_data_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LIVETENNISAPI_KEY", "twjp_test_key_not_real")
    provider = LiveTennisApiMatchProvider()
    monkeypatch.setattr(provider._client, "search_players", lambda name, limit=10: [_player_record()])

    def _boom(player_id: int, limit: int = 20) -> list[dict]:
        raise RuntimeError("simulated network failure")

    monkeypatch.setattr(provider._client, "get_completed_matches", _boom)

    with pytest.raises(PlayerDataError):
        provider.get_latest_match(PLAYER)


def test_player_id_resolution_is_cached_across_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LIVETENNISAPI_KEY", "twjp_test_key_not_real")
    provider = LiveTennisApiMatchProvider()
    search_calls = 0

    def _search(name: str, limit: int = 10) -> list[dict]:
        nonlocal search_calls
        search_calls += 1
        return [_player_record()]

    monkeypatch.setattr(provider._client, "search_players", _search)
    monkeypatch.setattr(
        provider._client, "get_completed_matches", lambda player_id, limit=20: [_match_record()]
    )

    provider.get_latest_match(PLAYER)
    provider.get_latest_match(PLAYER)

    assert search_calls == 1
