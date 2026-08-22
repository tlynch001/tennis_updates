"""Explicitly disabled match provider.

ATP v1 is rankings-only: there is no match feed. Configuration still
needs a registered match-provider name so ``match_provider`` can be set
without falling back to the WTA-only default (``wta_official``).

Both lookup methods return empty results. The pipeline should skip
calling this entirely when
:attr:`~wta_daily.tour.TourProfile.supports_daily_matches` is false —
absence of matches then means "not part of this product," not
"did not play."
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

from wta_daily.models import MatchLookupResult, MatchResult, PlayerRanking
from wta_daily.plugins.base import MatchProvider
from wta_daily.plugins.registry import matches_registry


@matches_registry.register("none")
class NoneMatchProvider(MatchProvider):
    """A no-op match provider used to disable daily match lookup in config."""

    def __init__(self, **_ignored: object) -> None:
        return

    def get_latest_match(self, player: PlayerRanking) -> MatchResult | None:
        return None

    def get_matches_for_date(
        self, players: Sequence[PlayerRanking], target_date: date
    ) -> MatchLookupResult:
        return MatchLookupResult()
