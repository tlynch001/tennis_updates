"""Unit tests for :mod:`wta_daily.plugins.matches.api_tennis_atp`."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from wta_daily.exceptions import ConfigurationError, DataProviderError, PlayerDataError
from wta_daily.models import PlayerRanking
from wta_daily.plugins.matches.api_tennis_atp import ApiTennisAtpMatchProvider

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "api_tennis_atp" / "fixtures.json"
STANDINGS_PATH = Path(__file__).parent / "fixtures" / "api_tennis_atp" / "standings.json"

ALCARAZ = PlayerRanking(
    rank=2, player_id="3105", name="Carlos Alcaraz", country_code="ESP", points=11250
)
SINNER = PlayerRanking(
    rank=1, player_id="2072", name="Jannik Sinner", country_code="ITA", points=13450
)
FRITZ = PlayerRanking(
    rank=5, player_id="2508", name="Taylor Fritz", country_code="USA", points=4675
)
ZVEREV = PlayerRanking(
    rank=3, player_id="1980", name="Alexander Zverev", country_code="GER", points=7465
)


def _fixtures() -> list[dict[str, Any]]:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _standings() -> list[dict[str, Any]]:
    return json.loads(STANDINGS_PATH.read_text(encoding="utf-8"))


def _provider(
    monkeypatch: pytest.MonkeyPatch, fixtures: list[dict[str, Any]]
) -> ApiTennisAtpMatchProvider:
    monkeypatch.setenv("APITENNIS_KEY", "test_key_not_real")
    provider = ApiTennisAtpMatchProvider()
    monkeypatch.setattr(
        provider._client,
        "get_fixtures_for_date",
        lambda **_kwargs: fixtures,
    )
    monkeypatch.setattr(
        provider._client,
        "get_fixtures",
        lambda **_kwargs: fixtures,
    )
    return provider


def test_maps_completed_atp_singles_fixture(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = _provider(monkeypatch, _fixtures())

    result = provider.get_matches_for_date([ALCARAZ], date(2026, 8, 8))

    match = result.matches["3105"]
    assert match.opponent == "A. Rublev"
    assert match.won is True
    assert match.score == "6-4 6-3"
    assert match.tournament == "Cincinnati"
    assert match.round == "Quarterfinal"
    assert match.match_date == date(2026, 8, 8)
    assert result.unresolved_player_ids == frozenset()
    assert result.tournament_status == {}


def test_score_is_from_tracked_player_perspective(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = _provider(monkeypatch, _fixtures())

    result = provider.get_matches_for_date([ZVEREV, FRITZ], date(2026, 8, 8))

    assert result.matches["1980"].opponent == "T. Fritz"
    assert result.matches["1980"].won is False
    assert result.matches["1980"].score == "3-6 4-6"
    assert result.matches["2508"].opponent == "A. Zverev"
    assert result.matches["2508"].won is True
    assert result.matches["2508"].score == "6-3 6-4"


def test_identity_uses_player_key_from_standings(monkeypatch: pytest.MonkeyPatch) -> None:
    standings = _standings()
    alcaraz_key = next(str(row["player_key"]) for row in standings if row["player"] == "Carlos Alcaraz")
    player = PlayerRanking(
        rank=2, player_id=alcaraz_key, name="Carlos Alcaraz", country_code="ESP", points=11250
    )
    provider = _provider(monkeypatch, _fixtures())

    result = provider.get_matches_for_date([player], date(2026, 8, 8))

    assert alcaraz_key == "3105"
    assert result.matches[alcaraz_key].opponent == "A. Rublev"


def test_player_without_a_fixture_is_a_confirmed_non_match(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = _provider(monkeypatch, _fixtures())

    result = provider.get_matches_for_date([SINNER], date(2026, 8, 8))

    assert SINNER.player_id not in result.matches
    assert result.unresolved_player_ids == frozenset()


def test_missing_numeric_player_id_is_unresolved_not_name_matched(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    player = PlayerRanking(
        rank=2, player_id="carlos-alcaraz", name="Carlos Alcaraz", country_code="ESP", points=11250
    )
    provider = _provider(monkeypatch, _fixtures())

    result = provider.get_matches_for_date([player], date(2026, 8, 8))

    assert result.matches == {}
    assert result.unresolved_player_ids == frozenset({"carlos-alcaraz"})


def test_wta_only_payload_fails_visibly(monkeypatch: pytest.MonkeyPatch) -> None:
    wta_only = [row for row in _fixtures() if "Wta" in str(row.get("event_type_type"))]
    provider = _provider(monkeypatch, wta_only)

    with pytest.raises(DataProviderError, match="only WTA"):
        provider.get_matches_for_date([ALCARAZ], date(2026, 8, 8))


def test_wta_rows_are_discarded_from_mixed_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = _provider(monkeypatch, _fixtures())

    result = provider.get_matches_for_date([ALCARAZ], date(2026, 8, 8))

    assert "1989" not in result.matches
    assert result.matches["3105"].tournament == "Cincinnati"


def test_malformed_score_is_unresolved(monkeypatch: pytest.MonkeyPatch) -> None:
    fixtures = _fixtures()
    fixtures[0]["scores"] = [{"score_first": "6"}]
    provider = _provider(monkeypatch, fixtures)

    result = provider.get_matches_for_date([ALCARAZ], date(2026, 8, 8))

    assert ALCARAZ.player_id not in result.matches
    assert ALCARAZ.player_id in result.unresolved_player_ids


def test_date_fixtures_are_fetched_once(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APITENNIS_KEY", "test_key_not_real")
    provider = ApiTennisAtpMatchProvider()
    calls: list[dict[str, Any]] = []

    def _get_fixtures_for_date(**kwargs: Any) -> list[dict[str, Any]]:
        calls.append(kwargs)
        return _fixtures()

    monkeypatch.setattr(provider._client, "get_fixtures_for_date", _get_fixtures_for_date)

    target = date(2026, 8, 8)
    provider.get_matches_for_date([ALCARAZ, SINNER, FRITZ], target)
    provider.get_matches_for_date([ZVEREV], target)

    assert len(calls) == 1
    assert calls[0]["date_start"] == "2026-08-08"
    assert calls[0]["date_stop"] == "2026-08-08"
    assert calls[0]["event_type_key"] == 265


def test_get_latest_match_requires_numeric_player_key(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = _provider(monkeypatch, _fixtures())
    player = PlayerRanking(
        rank=2, player_id="not-a-key", name="Carlos Alcaraz", country_code="ESP", points=11250
    )

    with pytest.raises(PlayerDataError, match="numeric api-tennis player_key"):
        provider.get_latest_match(player)


def test_missing_api_key_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("APITENNIS_KEY", raising=False)

    with pytest.raises(ConfigurationError):
        ApiTennisAtpMatchProvider()
