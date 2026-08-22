"""Unit tests for the BALLDONTLIE ATP rankings provider.

Never hits the live API. Fixtures follow the documented OpenAPI contract
(``GET /atp/v1/rankings``): ``rank``, ``points``, ``movement``,
``ranking_date``, and ``player.id`` / ``full_name``.
"""

from __future__ import annotations

from datetime import date
from typing import Any
from unittest.mock import patch

import pytest

from wta_daily.exceptions import ConfigurationError, DataProviderError
from wta_daily.plugins.balldontlie_atp_client import BalldontlieAtpClient
from wta_daily.plugins.rankings.balldontlie_atp import (
    BalldontlieAtpRankingsProvider,
    _parse_ranking_date,
)


def _player(
    *,
    player_id: int = 1,
    full_name: str = "Carlos Alcaraz",
    country_code: str = "ESP",
) -> dict[str, Any]:
    return {
        "id": player_id,
        "first_name": full_name.split(" ", 1)[0],
        "last_name": full_name.split(" ", 1)[-1],
        "full_name": full_name,
        "country_code": country_code,
    }


def _entry(
    *,
    rank: int = 1,
    player_id: int = 1,
    full_name: str = "Carlos Alcaraz",
    points: int = 12000,
    ranking_date: str | None = "2026-08-18",
    movement: int | None = 0,
    country_code: str = "ESP",
) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "id": rank,
        "player": _player(player_id=player_id, full_name=full_name, country_code=country_code),
        "rank": rank,
        "points": points,
        "movement": movement,
    }
    if ranking_date is not None:
        entry["ranking_date"] = ranking_date
    return entry


def _page(rows: list[dict[str, Any]], *, next_cursor: int | None = None) -> dict[str, Any]:
    return {"data": rows, "meta": {"next_cursor": next_cursor, "per_page": len(rows)}}


@pytest.fixture
def dummy_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BALLDONTLIE_API_KEY", "test-key-not-a-secret")


def test_missing_api_key_raises_clear_configuration_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BALLDONTLIE_API_KEY", raising=False)

    with pytest.raises(ConfigurationError, match="BALLDONTLIE_API_KEY"):
        BalldontlieAtpRankingsProvider()


def test_maps_rank_points_name_id_and_ranking_date(dummy_key: None) -> None:
    provider = BalldontlieAtpRankingsProvider()
    payload = _page(
        [
            _entry(rank=1, player_id=42, full_name="Carlos Alcaraz", points=12000),
            _entry(
                rank=2,
                player_id=7,
                full_name="Jannik Sinner",
                points=11050,
                country_code="ITA",
                movement=1,
            ),
        ]
    )
    with patch.object(provider._client, "_get_rankings_page", return_value=payload) as fetch:
        rankings = provider.get_top_n(2)

    fetch.assert_called_once()
    assert [r.rank for r in rankings] == [1, 2]
    assert rankings[0].name == "Carlos Alcaraz"
    assert rankings[0].player_id == "42"
    assert rankings[0].points == 12000
    assert rankings[0].country_code == "ESP"
    assert rankings[0].ranking_date == date(2026, 8, 18)
    assert rankings[1].name == "Jannik Sinner"
    assert rankings[1].player_id == "7"
    assert rankings[0].previous_rank is None


def test_vendor_movement_is_not_applied_to_player_ranking(dummy_key: None) -> None:
    """BALLDONTLIE's week-change field is ignored so the pipeline's snapshot
    movement remains the single source of truth."""

    provider = BalldontlieAtpRankingsProvider()
    payload = _page([_entry(movement=3)])
    with patch.object(provider._client, "_get_rankings_page", return_value=payload):
        rankings = provider.get_top_n(1)

    assert rankings[0].previous_rank is None
    assert not hasattr(rankings[0], "movement")


def test_missing_ranking_date_stays_unknown_not_today(dummy_key: None) -> None:
    provider = BalldontlieAtpRankingsProvider()
    payload = _page([_entry(ranking_date=None)])
    payload["data"][0].pop("ranking_date", None)

    with patch.object(provider._client, "_get_rankings_page", return_value=payload):
        rankings = provider.get_top_n(1)

    assert rankings[0].ranking_date is None
    assert rankings[0].ranking_date != date.today()


def test_null_ranking_date_stays_unknown(dummy_key: None) -> None:
    provider = BalldontlieAtpRankingsProvider()
    payload = _page([_entry(ranking_date=None)])
    payload["data"][0]["ranking_date"] = None

    with patch.object(provider._client, "_get_rankings_page", return_value=payload):
        rankings = provider.get_top_n(1)

    assert rankings[0].ranking_date is None


def test_unparseable_ranking_date_stays_unknown(dummy_key: None) -> None:
    assert _parse_ranking_date("not-a-date") is None
    assert _parse_ranking_date("") is None
    assert _parse_ranking_date(None) is None


def test_parse_ranking_date_never_uses_today_as_fallback() -> None:
    assert _parse_ranking_date(None) is None
    parsed = _parse_ranking_date("2026-01-05")
    assert parsed == date(2026, 1, 5)
    assert parsed != date.today()


def test_one_page_is_enough_for_top_10(dummy_key: None) -> None:
    provider = BalldontlieAtpRankingsProvider()
    rows = [_entry(rank=i, player_id=i, full_name=f"Player {i}", points=10000 - i) for i in range(1, 26)]
    payload = _page(rows, next_cursor=None)

    with patch.object(provider._client, "_get_rankings_page", return_value=payload) as fetch:
        rankings = provider.get_top_n(10)

    fetch.assert_called_once()
    assert [r.rank for r in rankings] == list(range(1, 11))
    assert fetch.call_args.kwargs["per_page"] >= 10


def test_paginates_only_when_first_page_is_short(dummy_key: None) -> None:
    provider = BalldontlieAtpRankingsProvider(per_page=5)
    first = _page(
        [_entry(rank=i, player_id=i, full_name=f"Player {i}") for i in range(1, 6)],
        next_cursor=5,
    )
    second = _page(
        [_entry(rank=i, player_id=i, full_name=f"Player {i}") for i in range(6, 11)],
        next_cursor=None,
    )

    with patch.object(
        provider._client, "_get_rankings_page", side_effect=[first, second]
    ) as fetch:
        rankings = provider.get_top_n(10)

    assert fetch.call_count == 2
    assert fetch.call_args_list[1].kwargs["cursor"] == 5
    assert [r.rank for r in rankings] == list(range(1, 11))


def test_skips_malformed_entries(dummy_key: None) -> None:
    provider = BalldontlieAtpRankingsProvider()
    payload = _page(
        [
            _entry(rank=1, player_id=1),
            {"rank": 2, "points": 100},  # missing player
            _entry(rank=3, player_id=3, full_name="Player Three"),
        ]
    )
    with patch.object(provider._client, "_get_rankings_page", return_value=payload):
        rankings = provider.get_top_n(3)

    assert [r.rank for r in rankings] == [1, 3]


def test_raises_when_every_entry_is_unusable(dummy_key: None) -> None:
    provider = BalldontlieAtpRankingsProvider()
    with patch.object(provider._client, "_get_rankings_page", return_value=_page([{"rank": 1}])):
        with pytest.raises(DataProviderError, match="no usable entries"):
            provider.get_top_n(1)


def test_client_rejects_missing_key() -> None:
    with pytest.raises(ConfigurationError, match="no API key"):
        BalldontlieAtpClient(api_key=None)
