"""Unit tests for :class:`wta_daily.plugins.base.MatchProvider`'s default
``get_matches_for_date`` fallback (built on top of ``get_latest_match``).

Concrete providers with a genuine day-indexed data source (``wta_official``)
override this; providers without one (``sample``, ``live_tennis_api``,
``api_tennis``) rely on this default, so it's tested here in isolation.
"""

from __future__ import annotations

from datetime import date

from wta_daily.models import MatchResult, PlayerRanking
from wta_daily.plugins.base import MatchProvider

PLAYER = PlayerRanking(rank=1, player_id="P1", name="Test Player", country_code="USA", points=8000)


def _match(match_date: date | None) -> MatchResult:
    return MatchResult(
        opponent="Opponent",
        tournament="Test Open",
        round="Final",
        score="6-4 6-4",
        won=True,
        match_date=match_date,
    )


class _FixedLatestMatchProvider(MatchProvider):
    """A minimal provider that only implements get_latest_match, exercising
    the base class's default get_matches_for_date fallback unmodified."""

    def __init__(self, match: MatchResult | None = None, error: Exception | None = None) -> None:
        self._match = match
        self._error = error

    def get_latest_match(self, player: PlayerRanking) -> MatchResult | None:
        if self._error is not None:
            raise self._error
        return self._match


def test_default_fallback_accepts_a_match_on_the_exact_target_date() -> None:
    provider = _FixedLatestMatchProvider(match=_match(date(2026, 8, 15)))

    result = provider.get_matches_for_date([PLAYER], date(2026, 8, 15))

    assert PLAYER.player_id in result.matches
    assert result.unresolved_player_ids == frozenset()


def test_default_fallback_rejects_a_match_on_a_different_date() -> None:
    """This is the key safety property: an older "latest known match" must
    never be accepted as if it happened on the target date. Since the
    lookup itself succeeded, this is a confirmed negative, not unresolved."""

    provider = _FixedLatestMatchProvider(match=_match(date(2026, 6, 29)))

    result = provider.get_matches_for_date([PLAYER], date(2026, 8, 15))

    assert result.matches == {}
    assert result.unresolved_player_ids == frozenset()


def test_default_fallback_rejects_a_match_with_an_unconfirmed_date() -> None:
    provider = _FixedLatestMatchProvider(match=_match(None))

    result = provider.get_matches_for_date([PLAYER], date(2026, 8, 15))

    assert result.matches == {}
    assert result.unresolved_player_ids == frozenset()


def test_default_fallback_handles_no_match_at_all() -> None:
    provider = _FixedLatestMatchProvider(match=None)

    result = provider.get_matches_for_date([PLAYER], date(2026, 8, 15))

    assert result.matches == {}
    assert result.unresolved_player_ids == frozenset()


def test_default_fallback_reports_a_failed_lookup_as_unresolved_not_a_confirmed_negative() -> None:
    """A player whose lookup genuinely raised is different from one whose
    lookup succeeded but simply returned an older/no match - the former
    must be flagged unresolved so a composite provider can still try
    another source for her specifically."""

    provider = _FixedLatestMatchProvider(error=RuntimeError("simulated failure"))

    result = provider.get_matches_for_date([PLAYER], date(2026, 8, 15))

    assert result.matches == {}
    assert result.unresolved_player_ids == frozenset({PLAYER.player_id})


def test_default_fallback_isolates_one_players_failure_from_others() -> None:
    class _MixedProvider(MatchProvider):
        def __init__(self) -> None:
            self._calls = 0

        def get_latest_match(self, player: PlayerRanking) -> MatchResult | None:
            self._calls += 1
            if player.player_id == "BROKEN":
                raise RuntimeError("simulated failure")
            return _match(date(2026, 8, 15))

    provider = _MixedProvider()
    players = [
        PLAYER,
        PlayerRanking(rank=2, player_id="BROKEN", name="Broken Player", country_code="FRA", points=1000),
    ]

    result = provider.get_matches_for_date(players, date(2026, 8, 15))

    assert PLAYER.player_id in result.matches
    assert "BROKEN" not in result.matches
    assert result.unresolved_player_ids == frozenset({"BROKEN"})
