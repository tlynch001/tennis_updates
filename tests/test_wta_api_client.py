"""Unit tests for :mod:`wta_daily.plugins.wta_api_client`'s efficiency behaviors.

Mocks the underlying :class:`~wta_daily.http_client.HttpClient` (never
hitting the network) to verify: (1) every call is recorded against the
right :mod:`wta_daily.api_usage` category, and (2) the tournament-catalogue
page cache genuinely prevents a duplicate HTTP request within one run.
"""

from __future__ import annotations

from typing import Any

import pytest

from wta_daily import api_usage
from wta_daily.plugins.wta_api_client import WtaOfficialApiClient


@pytest.fixture(autouse=True)
def _reset_counter() -> None:
    api_usage.reset()
    yield
    api_usage.reset()


class _CountingHttpClient:
    """Stands in for HttpClient, recording every call it receives."""

    def __init__(self, response: Any) -> None:
        self._response = response
        self.calls: list[tuple[str, dict[str, Any] | None]] = []

    def get_json(self, url: str, *, params: dict[str, Any] | None = None, headers: Any = None) -> Any:
        self.calls.append((url, params))
        return self._response


def _client_with_fake_http(response: Any) -> tuple[WtaOfficialApiClient, _CountingHttpClient]:
    client = WtaOfficialApiClient()
    fake_http = _CountingHttpClient(response)
    client._http = fake_http  # type: ignore[assignment]
    return client, fake_http


def test_get_rankings_records_the_rankings_category() -> None:
    client, _ = _client_with_fake_http([])

    client.get_rankings(page_size=10)

    assert api_usage.snapshot() == {"WTA rankings": 1}


def test_get_player_matches_records_the_match_results_category() -> None:
    client, _ = _client_with_fake_http({"matches": []})

    client.get_player_matches("p1")

    assert api_usage.snapshot() == {"WTA match results": 1}


def test_get_tournament_matches_records_the_match_results_category() -> None:
    client, _ = _client_with_fake_http({"matches": []})

    client.get_tournament_matches(1017, 2026)

    assert api_usage.snapshot() == {"WTA match results": 1}


def test_list_tournaments_page_records_the_tournament_discovery_category() -> None:
    client, _ = _client_with_fake_http({"content": [], "pageInfo": {"numEntries": 0}})

    client.list_tournaments_page(page=0)

    assert api_usage.snapshot() == {"WTA tournament discovery": 1}


def test_list_tournaments_page_caches_repeated_identical_requests() -> None:
    """The core dedup guarantee: asking for the same (page, page_size) twice
    in one run - which legitimately happens when page 0 is fetched up front
    for the total count and also falls inside the scan window - must issue
    only one real HTTP request."""

    client, fake_http = _client_with_fake_http({"content": [], "pageInfo": {"numEntries": 0}})

    first = client.list_tournaments_page(page=0, page_size=100)
    second = client.list_tournaments_page(page=0, page_size=100)

    assert first == second
    assert len(fake_http.calls) == 1
    assert api_usage.snapshot() == {"WTA tournament discovery": 1}


def test_list_tournaments_page_does_not_cache_across_different_pages() -> None:
    client, fake_http = _client_with_fake_http({"content": [], "pageInfo": {"numEntries": 0}})

    client.list_tournaments_page(page=0, page_size=100)
    client.list_tournaments_page(page=1, page_size=100)
    client.list_tournaments_page(page=0, page_size=100)  # repeat of the first - should be cached

    assert len(fake_http.calls) == 2
    assert api_usage.snapshot() == {"WTA tournament discovery": 2}


def test_list_tournaments_page_treats_different_page_sizes_as_distinct() -> None:
    client, fake_http = _client_with_fake_http({"content": [], "pageInfo": {"numEntries": 0}})

    client.list_tournaments_page(page=0, page_size=100)
    client.list_tournaments_page(page=0, page_size=50)

    assert len(fake_http.calls) == 2
