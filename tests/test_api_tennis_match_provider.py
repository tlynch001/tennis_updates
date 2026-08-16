"""Unit tests for :mod:`wta_daily.plugins.matches.api_tennis`.

These mock :class:`ApiTennisClient` directly (never hitting the network and
never needing a real API key), with response shapes captured from the real
API during development - including the confirmed one-day date-drift quirk
that's why this provider isn't in ``best_of``'s default source list.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from wta_daily.exceptions import ConfigurationError, PlayerDataError
from wta_daily.models import PlayerRanking
from wta_daily.plugins.matches.api_tennis import ApiTennisMatchProvider

PLAYER = PlayerRanking(rank=1, player_id="320760", name="Aryna Sabalenka", country_code="BLR", points=8670)


def _standings_row(*, player: str = "Aryna Sabalenka", player_key: int = 1989) -> dict[str, Any]:
    return {"place": 1, "player": player, "player_key": player_key, "league": "WTA", "points": "8670"}


def _fixture(
    *,
    first_player_key: int = 1989,
    second_player_key: int = 45,
    event_first_player: str = "A. Sabalenka",
    event_second_player: str = "E. Alexandrova",
    event_date: str | None = "2026-08-08",
    tournament_name: str = "Toronto",
    tournament_round: str = "WTA Toronto - 1/8-finals",
    event_type_type: str = "Wta Singles",
    event_status: str = "Finished",
    event_winner: str | None = "Second Player",
    scores: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    return {
        "event_key": 1,
        "event_date": event_date,
        "event_first_player": event_first_player,
        "first_player_key": first_player_key,
        "event_second_player": event_second_player,
        "second_player_key": second_player_key,
        "event_final_result": "1 - 2",
        "event_winner": event_winner,
        "event_status": event_status,
        "event_type_type": event_type_type,
        "tournament_name": tournament_name,
        "tournament_round": tournament_round,
        "event_qualification": "False",
        "scores": (
            scores
            if scores is not None
            else [{"score_first": "6", "score_second": "7", "score_set": "1"}]
        ),
    }


def _provider_with_mocked_client(
    monkeypatch: pytest.MonkeyPatch,
    *,
    standings: list[dict[str, Any]],
    fixtures: list[dict[str, Any]],
) -> ApiTennisMatchProvider:
    monkeypatch.setenv("APITENNIS_KEY", "test_key_not_real")
    provider = ApiTennisMatchProvider()
    monkeypatch.setattr(provider._client, "get_standings", lambda event_type="WTA": standings)
    monkeypatch.setattr(
        provider._client,
        "get_fixtures",
        lambda player_key, date_start, date_stop: fixtures,
    )
    return provider


def test_missing_api_key_raises_configuration_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("APITENNIS_KEY", raising=False)

    with pytest.raises(ConfigurationError):
        ApiTennisMatchProvider()


def test_resolves_name_via_standings_and_returns_match(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = _provider_with_mocked_client(
        monkeypatch, standings=[_standings_row()], fixtures=[_fixture()]
    )

    result = provider.get_latest_match(PLAYER)

    assert result is not None
    assert result.opponent == "E. Alexandrova"
    assert result.tournament == "Toronto"
    assert result.round == "Round of 16"
    assert result.match_date == date(2026, 8, 8)
    assert result.won is False  # winner="Second Player", our player is "first"


def test_name_lookup_is_case_insensitive(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = _provider_with_mocked_client(
        monkeypatch,
        standings=[_standings_row(player="aryna sabalenka")],
        fixtures=[_fixture()],
    )

    assert provider.get_latest_match(PLAYER) is not None


def test_score_formatted_from_our_players_perspective_when_we_are_second(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture(
        first_player_key=45,
        second_player_key=1989,
        event_first_player="E. Alexandrova",
        event_second_player="A. Sabalenka",
        event_winner="First Player",
        scores=[
            {"score_first": "7", "score_second": "6", "score_set": "1"},
            {"score_first": "4", "score_second": "6", "score_set": "2"},
        ],
    )
    provider = _provider_with_mocked_client(monkeypatch, standings=[_standings_row()], fixtures=[fixture])

    result = provider.get_latest_match(PLAYER)

    assert result is not None
    assert result.opponent == "E. Alexandrova"
    assert result.won is False
    # our player is "second": [6-7, 6-4] from her perspective.
    assert result.score == "6-7 6-4"


def test_round_suffix_translation() -> None:
    from wta_daily.plugins.matches.api_tennis import _friendly_round

    assert _friendly_round("WTA Toronto - 1/32-finals") == "Round of 64"
    assert _friendly_round("WTA Toronto - 1/16-finals") == "Round of 32"
    assert _friendly_round("WTA Toronto - 1/8-finals") == "Round of 16"
    assert _friendly_round("WTA Toronto - Quarter-finals") == "Quarterfinal"
    assert _friendly_round("WTA Toronto - Semi-finals") == "Semifinal"
    assert _friendly_round("WTA Toronto - Final") == "Final"
    assert _friendly_round("Some Unrecognised Suffix") == "Some Unrecognised Suffix"


def test_player_not_in_standings_raises_player_data_error(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = _provider_with_mocked_client(monkeypatch, standings=[], fixtures=[])

    with pytest.raises(PlayerDataError):
        provider.get_latest_match(PLAYER)


def test_doubles_fixtures_are_filtered_out(monkeypatch: pytest.MonkeyPatch) -> None:
    doubles = _fixture(event_type_type="Wta Doubles", event_second_player="Doubles Opponent")
    singles = _fixture(tournament_round="WTA Toronto - 1/16-finals", event_second_player="Singles Opponent")
    provider = _provider_with_mocked_client(
        monkeypatch, standings=[_standings_row()], fixtures=[doubles, singles]
    )

    result = provider.get_latest_match(PLAYER)

    assert result is not None
    assert result.opponent == "Singles Opponent"


def test_unplayed_fixtures_are_filtered_out(monkeypatch: pytest.MonkeyPatch) -> None:
    """A not-yet-played fixture reports event_status "" with no winner."""

    unplayed = _fixture(event_status="", event_winner=None, event_second_player="Future Opponent")
    played = _fixture(tournament_round="WTA Toronto - 1/16-finals", event_second_player="Past Opponent")
    provider = _provider_with_mocked_client(
        monkeypatch, standings=[_standings_row()], fixtures=[unplayed, played]
    )

    result = provider.get_latest_match(PLAYER)

    assert result is not None
    assert result.opponent == "Past Opponent"


def test_retired_matches_are_still_selected(monkeypatch: pytest.MonkeyPatch) -> None:
    retired = _fixture(event_status="Retired", event_second_player="Retirement Opponent")
    provider = _provider_with_mocked_client(monkeypatch, standings=[_standings_row()], fixtures=[retired])

    result = provider.get_latest_match(PLAYER)

    assert result is not None
    assert result.opponent == "Retirement Opponent"


def test_most_recent_event_date_is_selected(monkeypatch: pytest.MonkeyPatch) -> None:
    older = _fixture(event_date="2026-08-01", event_second_player="Older Opponent")
    newer = _fixture(event_date="2026-08-08", event_second_player="Newer Opponent")
    provider = _provider_with_mocked_client(
        monkeypatch, standings=[_standings_row()], fixtures=[older, newer]
    )

    result = provider.get_latest_match(PLAYER)

    assert result is not None
    assert result.opponent == "Newer Opponent"


def test_missing_event_date_yields_null_match_date(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = _provider_with_mocked_client(
        monkeypatch, standings=[_standings_row()], fixtures=[_fixture(event_date=None)]
    )

    result = provider.get_latest_match(PLAYER)

    assert result is not None
    assert result.match_date is None


def test_fixtures_lookup_failure_raises_player_data_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APITENNIS_KEY", "test_key_not_real")
    provider = ApiTennisMatchProvider()
    monkeypatch.setattr(provider._client, "get_standings", lambda event_type="WTA": [_standings_row()])

    def _boom(player_key: int, date_start: str, date_stop: str) -> list[dict]:
        raise RuntimeError("simulated network failure")

    monkeypatch.setattr(provider._client, "get_fixtures", _boom)

    with pytest.raises(PlayerDataError):
        provider.get_latest_match(PLAYER)


def test_standings_are_fetched_only_once_across_players(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APITENNIS_KEY", "test_key_not_real")
    provider = ApiTennisMatchProvider()
    call_count = 0

    def _get_standings(event_type: str = "WTA") -> list[dict]:
        nonlocal call_count
        call_count += 1
        return [
            _standings_row(),
            _standings_row(player="Elena Rybakina", player_key=2172),
        ]

    monkeypatch.setattr(provider._client, "get_standings", _get_standings)
    monkeypatch.setattr(
        provider._client, "get_fixtures", lambda player_key, date_start, date_stop: [_fixture()]
    )

    provider.get_latest_match(PLAYER)
    provider.get_latest_match(
        PlayerRanking(rank=2, player_id="324166", name="Elena Rybakina", country_code="KAZ", points=8316)
    )

    assert call_count == 1
