"""Unit tests for :mod:`wta_daily.plugins.matches.best_of`.

Uses small in-test fake :class:`MatchProvider` implementations rather than
mocking either real provider's HTTP layer, so these tests exercise the
composition logic in isolation.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

import pytest

from wta_daily.exceptions import ConfigurationError, PlayerDataError
from wta_daily.models import MatchLookupResult, MatchResult, PlayerRanking
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


def _register_fake_batch_source(
    name: str,
    *,
    results: dict[str, MatchResult] | None = None,
    unresolved: set[str] | frozenset[str] | None = None,
    error: Exception | None = None,
) -> None:
    """Registers a fake source whose ``get_matches_for_date`` is controlled
    directly (rather than relying on the base class's per-player fallback),
    for tests that exercise ``BestOfMatchProvider.get_matches_for_date``
    specifically.

    By default (``unresolved=None``), this fake behaves like a *confident*
    day-first source (e.g. ``wta_official`` on a normal day): every
    requested player not present in ``results`` is reported as a genuine
    negative, not merely absent. Pass ``unresolved`` to simulate a source
    that couldn't determine specific players' status instead.
    """

    class _FakeBatch(MatchProvider):
        def __init__(self, **_ignored: object) -> None:
            self.calls: list[list[str]] = []

        def get_latest_match(self, player: PlayerRanking) -> MatchResult | None:
            raise AssertionError("get_latest_match should not be called by get_matches_for_date tests")

        def get_matches_for_date(
            self, players: Sequence[PlayerRanking], target_date: date
        ) -> MatchLookupResult:
            self.calls.append([p.player_id for p in players])
            if error is not None:
                raise error
            found = results or {}
            matches = {p.player_id: found[p.player_id] for p in players if p.player_id in found}
            requested_ids = {p.player_id for p in players}
            unresolved_ids = frozenset(unresolved or ()) & requested_ids
            return MatchLookupResult(matches=matches, unresolved_player_ids=unresolved_ids)

    matches_registry.register(name)(_FakeBatch)


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


class _UnconfigurableSource(MatchProvider):
    """Fails to even construct - simulates a paid source with no API key set."""

    def __init__(self, **_ignored: object) -> None:
        raise ConfigurationError("simulated missing API key")

    def get_latest_match(self, player: PlayerRanking) -> MatchResult | None:
        raise AssertionError("never constructed, so never called")


def test_a_source_that_fails_to_construct_is_skipped_not_fatal() -> None:
    """Regression test: one misconfigured source (e.g. a paid provider with
    no API key set yet) must not prevent the whole pipeline from running
    when another configured source is perfectly usable."""

    matches_registry.register("unconfigurable-for-tests")(_UnconfigurableSource)
    _register_fake_source("fake-usable", result=_match("Someone", date(2026, 8, 15)))

    provider = BestOfMatchProvider(
        sources=[{"provider": "unconfigurable-for-tests"}, {"provider": "fake-usable"}]
    )

    assert len(provider._sources) == 1
    result = provider.get_latest_match(PLAYER)
    assert result is not None
    assert result.opponent == "Someone"


def test_raises_configuration_error_when_every_source_fails_to_construct() -> None:
    matches_registry.register("unconfigurable-for-tests-2")(_UnconfigurableSource)

    with pytest.raises(ConfigurationError):
        BestOfMatchProvider(sources=[{"provider": "unconfigurable-for-tests-2"}])


# --- get_matches_for_date (day-first) ----------------------------------------------------

PLAYER_2 = PlayerRanking(rank=8, player_id="329668", name="Linda Noskova", country_code="CZE", points=5016)


def test_get_matches_for_date_first_source_to_find_a_player_wins() -> None:
    match = _match("Someone", date(2026, 8, 15))
    _register_fake_batch_source("batch-first", results={PLAYER.player_id: match})
    _register_fake_batch_source("batch-second", results={})

    provider = BestOfMatchProvider(sources=[{"provider": "batch-first"}, {"provider": "batch-second"}])
    result = provider.get_matches_for_date([PLAYER], date(2026, 8, 15))

    assert result.matches[PLAYER.player_id] is match


def test_get_matches_for_date_second_source_fills_in_players_first_source_missed() -> None:
    """The first source genuinely couldn't determine PLAYER_2's status (a
    realistic stand-in for a source with per-player coverage gaps), so the
    second source is correctly asked about her and fills in the gap."""

    match1 = _match("Opponent 1", date(2026, 8, 15))
    match2 = _match("Opponent 2", date(2026, 8, 15))
    _register_fake_batch_source(
        "batch-partial-1", results={PLAYER.player_id: match1}, unresolved={PLAYER_2.player_id}
    )
    _register_fake_batch_source("batch-partial-2", results={PLAYER_2.player_id: match2})

    provider = BestOfMatchProvider(
        sources=[{"provider": "batch-partial-1"}, {"provider": "batch-partial-2"}]
    )
    result = provider.get_matches_for_date([PLAYER, PLAYER_2], date(2026, 8, 15))

    assert result.matches[PLAYER.player_id] is match1
    assert result.matches[PLAYER_2.player_id] is match2


def test_get_matches_for_date_does_not_call_a_later_source_for_a_confirmed_negative() -> None:
    """The key efficiency property: once a confident source has fully
    accounted for every requested player (whether they played or not), a
    later - possibly paid - source should not be queried about any of them,
    not even the ones who simply didn't play."""

    _register_fake_batch_source(
        "batch-confident", results={PLAYER.player_id: _match("Someone", date(2026, 8, 15))}
    )

    class _TrackedSecond(MatchProvider):
        def __init__(self, **_ignored: object) -> None:
            self.calls: list[list[str]] = []

        def get_latest_match(self, player: PlayerRanking) -> MatchResult | None:
            raise AssertionError("not used")

        def get_matches_for_date(
            self, players: Sequence[PlayerRanking], target_date: date
        ) -> MatchLookupResult:
            self.calls.append([p.player_id for p in players])
            return MatchLookupResult()

    matches_registry.register("batch-tracked-second-confident")(_TrackedSecond)

    provider = BestOfMatchProvider(
        sources=[{"provider": "batch-confident"}, {"provider": "batch-tracked-second-confident"}]
    )
    provider.get_matches_for_date([PLAYER, PLAYER_2], date(2026, 8, 15))

    tracked_second = provider._sources[1]
    # PLAYER_2 wasn't found, but the first source was confident (no
    # unresolved players), so PLAYER_2 is a confirmed "didn't play" and the
    # second source should never be called at all.
    assert tracked_second.calls == []


def test_get_matches_for_date_only_queries_genuinely_unresolved_players_on_later_sources() -> None:
    """A player the first source explicitly couldn't determine is still
    passed on to the next source - but nobody else is."""

    match = _match("Someone", date(2026, 8, 15))
    _register_fake_batch_source(
        "batch-found-early", results={PLAYER.player_id: match}, unresolved={PLAYER_2.player_id}
    )

    class _TrackedSecond(MatchProvider):
        def __init__(self, **_ignored: object) -> None:
            self.calls: list[list[str]] = []

        def get_latest_match(self, player: PlayerRanking) -> MatchResult | None:
            raise AssertionError("not used")

        def get_matches_for_date(
            self, players: Sequence[PlayerRanking], target_date: date
        ) -> MatchLookupResult:
            self.calls.append([p.player_id for p in players])
            return MatchLookupResult()

    matches_registry.register("batch-tracked-second-unresolved")(_TrackedSecond)

    provider = BestOfMatchProvider(
        sources=[{"provider": "batch-found-early"}, {"provider": "batch-tracked-second-unresolved"}]
    )
    provider.get_matches_for_date([PLAYER, PLAYER_2], date(2026, 8, 15))

    tracked_second = provider._sources[1]
    # Only PLAYER_2 was genuinely unresolved after the first source, so
    # that's all the second source should ever be asked about.
    assert tracked_second.calls == [[PLAYER_2.player_id]]


def test_get_matches_for_date_confirms_played_false_when_a_working_source_says_so() -> None:
    """A source that completes successfully but simply doesn't list a player
    is a confident 'she didn't play' - not an error."""

    _register_fake_batch_source("batch-clean-no-match", results={})

    provider = BestOfMatchProvider(sources=[{"provider": "batch-clean-no-match"}])
    result = provider.get_matches_for_date([PLAYER], date(2026, 8, 15))

    assert result.matches == {}
    assert result.unresolved_player_ids == frozenset()


def test_get_matches_for_date_one_source_erroring_does_not_block_another() -> None:
    match = _match("Someone", date(2026, 8, 15))
    _register_fake_batch_source("batch-broken", error=RuntimeError("simulated outage"))
    _register_fake_batch_source("batch-fine", results={PLAYER.player_id: match})

    provider = BestOfMatchProvider(sources=[{"provider": "batch-broken"}, {"provider": "batch-fine"}])
    result = provider.get_matches_for_date([PLAYER], date(2026, 8, 15))

    assert result.matches[PLAYER.player_id] is match


def test_get_matches_for_date_raises_only_when_every_source_fails() -> None:
    _register_fake_batch_source("batch-broken-1", error=RuntimeError("outage 1"))
    _register_fake_batch_source("batch-broken-2", error=RuntimeError("outage 2"))

    provider = BestOfMatchProvider(sources=[{"provider": "batch-broken-1"}, {"provider": "batch-broken-2"}])

    with pytest.raises(PlayerDataError):
        provider.get_matches_for_date([PLAYER], date(2026, 8, 15))


def test_get_matches_for_date_defaults_to_the_per_player_fallback_when_a_source_lacks_native_support() -> (
    None
):
    """A source that only implements get_latest_match still participates
    correctly, via MatchProvider's default fallback."""

    _register_fake_source("legacy-only", result=_match("Someone", date(2026, 8, 15)))

    provider = BestOfMatchProvider(sources=[{"provider": "legacy-only"}])
    result = provider.get_matches_for_date([PLAYER], date(2026, 8, 15))

    assert result.matches[PLAYER.player_id].opponent == "Someone"


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
