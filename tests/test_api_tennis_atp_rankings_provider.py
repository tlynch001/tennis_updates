"""Unit tests for :mod:`wta_daily.plugins.rankings.api_tennis_atp`."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from wta_daily.exceptions import ConfigurationError, DataProviderError
from wta_daily.plugins.rankings.api_tennis_atp import ApiTennisAtpRankingsProvider

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "api_tennis_atp" / "standings.json"


def _standings_fixture() -> list[dict[str, Any]]:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _provider(monkeypatch: pytest.MonkeyPatch, rows: list[dict[str, Any]]) -> ApiTennisAtpRankingsProvider:
    monkeypatch.setenv("APITENNIS_KEY", "test_key_not_real")
    provider = ApiTennisAtpRankingsProvider()
    monkeypatch.setattr(provider._client, "get_standings", lambda event_type="WTA": rows)
    return provider


def test_maps_rest_standings_to_player_ranking(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = _provider(monkeypatch, _standings_fixture())

    rankings = provider.get_top_n(10)

    assert [r.rank for r in rankings] == list(range(1, 11))
    assert rankings[0].name == "Jannik Sinner"
    assert rankings[0].player_id == "2072"
    assert rankings[0].points == 13450
    assert rankings[0].country_code == "ITA"
    assert rankings[1].name == "Carlos Alcaraz"
    assert rankings[1].player_id == "3105"
    assert rankings[1].points == 11250
    assert rankings[1].country_code == "ESP"
    assert rankings[5].country_code == "GBR"


def test_ranking_date_is_unknown_and_not_fabricated(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = _provider(monkeypatch, _standings_fixture())

    rankings = provider.get_top_n(3)

    assert all(r.ranking_date is None for r in rankings)
    assert all(r.ranking_date != date.today() for r in rankings)


def test_standings_are_fetched_once_per_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APITENNIS_KEY", "test_key_not_real")
    provider = ApiTennisAtpRankingsProvider()
    calls: list[str] = []

    def _get_standings(event_type: str = "WTA") -> list[dict[str, Any]]:
        calls.append(event_type)
        return _standings_fixture()

    monkeypatch.setattr(provider._client, "get_standings", _get_standings)

    first = provider.get_top_n(10)
    second = provider.get_top_n(3)

    assert calls == ["ATP"]
    assert [r.player_id for r in second] == [r.player_id for r in first[:3]]


def test_missing_points_skips_row_and_keeps_usable_entries(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = _standings_fixture()
    rows[2] = {**rows[2], "points": ""}
    provider = _provider(monkeypatch, rows)

    rankings = provider.get_top_n(10)

    assert "1980" not in {r.player_id for r in rankings}
    assert rankings[0].player_id == "2072"


def test_missing_points_on_every_row_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = [{**row, "points": None} for row in _standings_fixture()]
    provider = _provider(monkeypatch, rows)

    with pytest.raises(DataProviderError, match="no usable"):
        provider.get_top_n(10)


def test_wta_standings_row_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = [
        {
            "place": 1,
            "player": "Aryna Sabalenka",
            "player_key": 1989,
            "league": "WTA",
            "country": "Belarus",
            "points": "8670",
        }
    ]
    provider = _provider(monkeypatch, rows)

    with pytest.raises(DataProviderError, match="WTA"):
        provider.get_top_n(1)


def test_empty_standings_fail(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = _provider(monkeypatch, [])

    with pytest.raises(DataProviderError, match="no rows"):
        provider.get_top_n(10)


def test_missing_player_key_is_not_guessed(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = _standings_fixture()
    rows[0] = {k: v for k, v in rows[0].items() if k != "player_key"}
    provider = _provider(monkeypatch, rows)

    rankings = provider.get_top_n(10)

    assert all(r.name != "Jannik Sinner" for r in rankings)
    assert rankings[0].player_id == "3105"


def test_missing_api_key_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("APITENNIS_KEY", raising=False)

    with pytest.raises(ConfigurationError):
        ApiTennisAtpRankingsProvider()
