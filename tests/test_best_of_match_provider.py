"""Unit tests for :mod:`wta_daily.plugins.matches.best_of`.

Uses small in-test fake :class:`MatchProvider` implementations rather than
mocking either real provider's HTTP layer, so these tests exercise the
composition logic in isolation.
"""

from __future__ import annotations

from datetime import date

import pytest

from wta_daily.exceptions import PlayerDataError
from wta_daily.models import MatchResult, PlayerRanking
from wta_daily.plugins.base import MatchProvider
from wta_daily.plugins.matches.best_of import BestOfMatchProvider
from wta_daily.plugins.registry import matches_registry

PLAYER = PlayerRanking(rank=7, player_id="322191", name="Karolina Muchova", country_code="CZE", points=5048)


def _match(opponent: str, match_date: date | None) -> MatchResult:
    return MatchResult(
        opponent=opponent,
        tournament="Test Open",
        round="Final",
        score="6-4 6-4",
        won=True,
        match_date=match_date,
    )


def _register_fake_source(
    name: str, *, result: MatchResult | None = None, error: Exception | None = None
) -> None:
    class _Fake(MatchProvider):
        def __init__(self, **_ignored: object) -> None:
            pass

        def get_latest_match(self, player: PlayerRanking) -> MatchResult | None:
            if error is not None:
                raise error
            return result

    matches_registry.register(name)(_Fake)


def test_prefers_the_source_with_the_more_recent_confirmed_date() -> None:
    """Regression test for the real 'stale paid-source coverage' incident:
    a fresher wta_official result must win over a stale live_tennis_api one."""

    _register_fake_source("fake-stale", result=_match("Old Opponent", date(2026, 3, 21)))
    _register_fake_source("fake-fresh", result=_match("New Opponent", date(2026, 8, 8)))

    provider = BestOfMatchProvider(sources=[{"provider": "fake-stale"}, {"provider": "fake-fresh"}])
    result = provider.get_latest_match(PLAYER)

    assert result is not None
    assert result.opponent == "New Opponent"
    assert result.match_date == date(2026, 8, 8)


def test_source_order_does_not_matter_only_recency_does() -> None:
    _register_fake_source("fake-fresh-2", result=_match("New Opponent", date(2026, 8, 8)))
    _register_fake_source("fake-stale-2", result=_match("Old Opponent", date(2026, 3, 21)))

    provider = BestOfMatchProvider(sources=[{"provider": "fake-fresh-2"}, {"provider": "fake-stale-2"}])
    result = provider.get_latest_match(PLAYER)

    assert result is not None
    assert result.opponent == "New Opponent"


def test_one_source_failing_falls_back_to_the_other() -> None:
    _register_fake_source("fake-broken", error=RuntimeError("simulated outage"))
    _register_fake_source("fake-working", result=_match("Working Opponent", date(2026, 8, 8)))

    provider = BestOfMatchProvider(sources=[{"provider": "fake-broken"}, {"provider": "fake-working"}])
    result = provider.get_latest_match(PLAYER)

    assert result is not None
    assert result.opponent == "Working Opponent"


def test_all_sources_failing_raises_player_data_error() -> None:
    _register_fake_source("fake-broken-1", error=RuntimeError("outage 1"))
    _register_fake_source("fake-broken-2", error=RuntimeError("outage 2"))

    provider = BestOfMatchProvider(sources=[{"provider": "fake-broken-1"}, {"provider": "fake-broken-2"}])

    with pytest.raises(PlayerDataError):
        provider.get_latest_match(PLAYER)


def test_all_sources_returning_none_returns_none_without_error() -> None:
    _register_fake_source("fake-none-1", result=None)
    _register_fake_source("fake-none-2", result=None)

    provider = BestOfMatchProvider(sources=[{"provider": "fake-none-1"}, {"provider": "fake-none-2"}])

    assert provider.get_latest_match(PLAYER) is None


def test_a_dated_result_is_preferred_over_an_undated_one() -> None:
    _register_fake_source("fake-undated", result=_match("Undated Opponent", None))
    _register_fake_source("fake-dated", result=_match("Dated Opponent", date(2026, 1, 1)))

    provider = BestOfMatchProvider(sources=[{"provider": "fake-undated"}, {"provider": "fake-dated"}])
    result = provider.get_latest_match(PLAYER)

    assert result is not None
    assert result.opponent == "Dated Opponent"


def test_undated_result_is_used_if_it_is_the_only_one_available() -> None:
    _register_fake_source("fake-only-undated", result=_match("Only Opponent", None))

    provider = BestOfMatchProvider(sources=[{"provider": "fake-only-undated"}])
    result = provider.get_latest_match(PLAYER)

    assert result is not None
    assert result.opponent == "Only Opponent"


def test_requires_at_least_one_source() -> None:
    with pytest.raises(ValueError):
        BestOfMatchProvider(sources=[])


def test_source_entry_without_provider_key_raises() -> None:
    with pytest.raises(ValueError):
        BestOfMatchProvider(sources=[{"lookback_matches": 10}])


def test_defaults_to_wta_official_and_live_tennis_api_when_unconfigured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Loading the real built-in plugins (no fakes) with default sources
    should construct wta_official + live_tennis_api - verifying the default
    wiring without making a real network call (the key just needs to exist;
    LiveTennisApiMatchProvider only validates it eagerly at construction)."""

    from wta_daily.plugins.registry import load_builtin_plugins

    load_builtin_plugins()
    monkeypatch.setenv("LIVETENNISAPI_KEY", "twjp_test_key_not_real")

    provider = BestOfMatchProvider()

    assert len(provider._sources) == 2
    source_names = {type(s).__name__ for s in provider._sources}
    assert source_names == {"WtaOfficialMatchProvider", "LiveTennisApiMatchProvider"}
