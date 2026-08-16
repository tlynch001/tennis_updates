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

Isolation starts even before any lookup happens: if a configured source
can't be *constructed* at all (e.g. a paid source's API key hasn't been set
yet), that source is skipped with a logged warning rather than crashing the
whole pipeline - as long as at least one other configured source is usable.
Only if every source fails to construct does this raise, since at that
point there is genuinely nothing left to try.

This composes existing plugins purely through the registry - it does not
know or care what ``wta_official``/``live_tennis_api`` do internally, so
adding a third source later (or removing one) is a one-line config change,
per the project's "never tightly couple the pipeline to a data source" rule.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import date
from typing import Any

from wta_daily.config import NetworkConfig
from wta_daily.exceptions import ConfigurationError, PlayerDataError
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
        construction_failures: list[str] = []
        for source_config in source_configs:
            source_config = dict(source_config)
            name = source_config.pop("provider", None)
            if not name:
                raise ValueError(f"Each best_of source needs a 'provider' name: {source_config!r}")
            # A source that can't even be *constructed* (e.g. a missing API
            # key for a paid provider) must not take the whole job down with
            # it if another configured source is perfectly usable - this is
            # the same "isolate failures per source" principle as the
            # runtime methods below, just applied one step earlier. Only if
            # every source fails to construct do we escalate (see below).
            try:
                self._sources.append(matches_registry.create(name, network=network, **source_config))
            except Exception as exc:  # noqa: BLE001 - never let one bad source block the others
                logger.warning(
                    "best_of source %r could not be set up and will be skipped for this run: %s",
                    name,
                    exc,
                )
                construction_failures.append(f"{name}: {exc}")

        if not self._sources:
            raise ConfigurationError(
                "None of the configured best_of match sources could be set up: "
                + "; ".join(construction_failures)
            )

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

    def get_matches_for_date(
        self, players: Sequence[PlayerRanking], target_date: date
    ) -> dict[str, MatchResult]:
        """Ask every source in turn; a player found by any one of them is
        confidently reported as having played (sources agree on real-world
        facts, so the first hit is as good as any). A player still
        unresolved after a source that itself completed without error is
        confidently reported as ``played: false`` by that source - only if
        *every* source fails outright do we raise, rather than guess.
        """

        remaining: dict[str, PlayerRanking] = {p.player_id: p for p in players}
        results: dict[str, MatchResult] = {}
        any_source_succeeded = False
        failures: list[str] = []

        for source in self._sources:
            if not remaining:
                break
            source_name = getattr(source, "name", type(source).__name__)
            try:
                source_results = source.get_matches_for_date(list(remaining.values()), target_date)
            except Exception as exc:  # noqa: BLE001 - one source's failure must not block others
                logger.info(
                    "Match source %s failed while checking %s: %s", source_name, target_date, exc
                )
                failures.append(f"{source_name}: {exc}")
                continue

            any_source_succeeded = True
            for player_id, match in source_results.items():
                if player_id in remaining:
                    results[player_id] = match
                    del remaining[player_id]

        if remaining and not any_source_succeeded:
            raise PlayerDataError(
                f"All match sources failed while checking {target_date} for "
                f"{len(remaining)} player(s): " + "; ".join(failures)
            )
        return results
