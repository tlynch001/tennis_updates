"""Unit tests for :mod:`wta_daily.plugins.rankings.wta_official`.

Mocks the underlying :class:`WtaOfficialApiClient` (never hitting the
network) with response shapes captured from the real API - notably the
``rankedAt`` field, which identifies the officially published ranking
list's publication date and is identical for every entry in one response
(verified live against api.wtatennis.com).
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from wta_daily.exceptions import DataProviderError
from wta_daily.plugins.rankings.wta_official import WtaOfficialRankingsProvider


def _entry(
    *,
    rank: int = 1,
    player_id: int = 100,
    full_name: str = "Test Player",
    country_code: str = "USA",
    points: int = 8000,
    ranked_at: str | None = "2026-08-10T00:00:00Z",
) -> dict[str, Any]:
    """Build one entry shaped like ``GET /players/ranked`` returns."""

    entry: dict[str, Any] = {
        "player": {"id": player_id, "fullName": full_name, "countryCode": country_code},
        "ranking": rank,
        "points": points,
        "tournamentsPlayed": 18,
        "movement": 0,
    }
    if ranked_at is not None:
        entry["rankedAt"] = ranked_at
    return entry


def _provider_with_mocked_response(
    monkeypatch: pytest.MonkeyPatch, raw_response: list[dict[str, Any]]
) -> WtaOfficialRankingsProvider:
    provider = WtaOfficialRankingsProvider()
    monkeypatch.setattr(
        provider._client,
        "get_rankings",
        lambda ranking_type="rankSingles", metric="singles", page_size=10: raw_response,
    )
    return provider


def test_get_top_n_parses_rank_points_and_ranking_date(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = _provider_with_mocked_response(
        monkeypatch,
        [
            _entry(rank=1, player_id=1, full_name="Player One", points=8670),
            _entry(rank=2, player_id=2, full_name="Player Two", points=8316),
        ],
    )

    rankings = provider.get_top_n(2)

    assert [r.rank for r in rankings] == [1, 2]
    assert rankings[0].name == "Player One"
    assert rankings[0].points == 8670
    assert rankings[0].ranking_date == date(2026, 8, 10)
    assert rankings[1].ranking_date == date(2026, 8, 10)


def test_ranking_date_is_the_same_official_list_for_every_player(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """rankedAt identifies the *list*, not the individual player - every
    entry in one response must produce the identical ranking_date."""

    provider = _provider_with_mocked_response(
        monkeypatch, [_entry(rank=i, player_id=i, ranked_at="2026-08-10T00:00:00Z") for i in range(1, 11)]
    )

    rankings = provider.get_top_n(10)

    assert {r.ranking_date for r in rankings} == {date(2026, 8, 10)}


def test_missing_ranked_at_leaves_ranking_date_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    """A provider response without rankedAt (e.g. an older API version)
    must not crash - it just means ranking_date is unknown."""

    provider = _provider_with_mocked_response(monkeypatch, [_entry(ranked_at=None)])

    rankings = provider.get_top_n(1)

    assert rankings[0].ranking_date is None


def test_malformed_ranked_at_leaves_ranking_date_unset_without_failing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _provider_with_mocked_response(monkeypatch, [_entry(ranked_at="not-a-date")])

    rankings = provider.get_top_n(1)

    assert rankings[0].ranking_date is None
    assert rankings[0].rank == 1  # the rest of the entry is still usable


def test_get_top_n_skips_malformed_entries_without_failing(monkeypatch: pytest.MonkeyPatch) -> None:
    good = _entry(rank=1, player_id=1)
    malformed = {"player": {"id": 2}}  # missing "ranking"
    provider = _provider_with_mocked_response(monkeypatch, [good, malformed])

    rankings = provider.get_top_n(2)

    assert len(rankings) == 1
    assert rankings[0].player_id == "1"


def test_get_top_n_raises_when_every_entry_is_malformed(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = _provider_with_mocked_response(monkeypatch, [{"player": {"id": 1}}])

    with pytest.raises(DataProviderError):
        provider.get_top_n(1)


def test_get_top_n_sorts_and_truncates_to_n(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = _provider_with_mocked_response(
        monkeypatch, [_entry(rank=3, player_id=3), _entry(rank=1, player_id=1), _entry(rank=2, player_id=2)]
    )

    rankings = provider.get_top_n(2)

    assert [r.rank for r in rankings] == [1, 2]
