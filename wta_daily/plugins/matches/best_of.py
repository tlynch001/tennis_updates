"""A :class:`MatchProvider` that combines several other match providers.

Motivation: neither of this project's two match sources is reliable *alone*.
``wta_official`` (the free WTA endpoint) can lag real-world results by more
than a week during/right after a tournament. ``live_tennis_api`` (the paid
aggregator) is usually fresher, but has its own per-player coverage gaps -
verified live, one Top 10 player's record there simply stopped four months
before the others', with no error or warning from that API to signal it.

Rather than pick one and hope, :class:`BestOfMatchProvider` queries every
configured source for the same player, isolates failures per source (one
source erroring never blocks another from being tried), and returns
whichever successful result has the most recently *confirmed* ``match_date``
- exactly the signal that matters, now that both underlying providers
recover a genuine per-match date instead of ever substituting a tournament
date. A result with an unconfirmed (``None``) date is only used if nothing
better is available, since a dated result is strictly more informative for
comparison purposes.

This composes existing plugins purely through the registry - it does not
know or care what ``wta_official``/``live_tennis_api`` do internally, so
adding a third source later (or removing one) is a one-line config change,
per the project's "never tightly couple the pipeline to a data source" rule.
"""

from __future__ import annotations

import logging
from typing import Any

from wta_daily.config import NetworkConfig
from wta_daily.exceptions import PlayerDataError
from wta_daily.models import MatchResult, PlayerRanking
from wta_daily.plugins.base import MatchProvider
from wta_daily.plugins.registry import matches_registry

logger = logging.getLogger(__name__)

#: Used when config doesn't specify ``sources`` explicitly - the free
#: official source plus the paid aggregator, combined for freshness.
_DEFAULT_SOURCES: list[dict[str, Any]] = [
    {"provider": "wta_official"},
    {"provider": "live_tennis_api"},
]


@matches_registry.register("best_of")
class BestOfMatchProvider(MatchProvider):
    """Tries every configured source; returns the most recently-dated result."""

    def __init__(
        self,
        sources: list[dict[str, Any]] | None = None,
        network: NetworkConfig | None = None,
        **_ignored: object,
    ) -> None:
        source_configs = sources if sources is not None else _DEFAULT_SOURCES
        if not source_configs:
            raise ValueError("BestOfMatchProvider requires at least one entry in 'sources'.")

        self._sources: list[MatchProvider] = []
        for source_config in source_configs:
            source_config = dict(source_config)
            name = source_config.pop("provider", None)
            if not name:
                raise ValueError(f"Each best_of source needs a 'provider' name: {source_config!r}")
            self._sources.append(matches_registry.create(name, network=network, **source_config))

    def get_latest_match(self, player: PlayerRanking) -> MatchResult | None:
        candidates: list[MatchResult] = []
        failures: list[str] = []

        for source in self._sources:
            source_name = getattr(source, "name", type(source).__name__)
            try:
                result = source.get_latest_match(player)
            except Exception as exc:  # noqa: BLE001 - one source's failure must not block others
                logger.info("Match source %s failed for %s: %s", source_name, player.name, exc)
                failures.append(f"{source_name}: {exc}")
                continue
            if result is not None:
                candidates.append(result)

        if not candidates:
            if failures:
                raise PlayerDataError(
                    f"All match sources failed for {player.name}: " + "; ".join(failures)
                )
            return None

        dated = [c for c in candidates if c.match_date is not None]
        if dated:
            return max(dated, key=lambda c: c.match_date)  # type: ignore[return-value, arg-type]
        return candidates[0]
