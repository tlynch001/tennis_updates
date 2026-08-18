"""Rankings provider backed by the official WTA JSON backend.

See :mod:`wta_daily.plugins.wta_api_client` for the rationale behind choosing
this data source.
"""

from __future__ import annotations

import logging
from datetime import date, datetime

from wta_daily.config import NetworkConfig
from wta_daily.exceptions import DataProviderError
from wta_daily.models import PlayerRanking
from wta_daily.plugins.base import RankingsProvider
from wta_daily.plugins.registry import rankings_registry
from wta_daily.plugins.wta_api_client import DEFAULT_BASE_URL, WtaOfficialApiClient

logger = logging.getLogger(__name__)


def _parse_ranked_at(raw_value: object) -> date | None:
    """Parse the upstream API's ``rankedAt`` field (e.g.
    ``"2026-08-10T00:00:00Z"``) into the official ranking list's
    publication date.

    Identical for every player in one response (verified live) - it
    identifies the *list*, not the individual player - so a parse failure
    here is not fatal to the ranking itself: this just logs a warning and
    returns ``None`` (the pipeline's existing, pre-``ranking_date``
    fallback behavior), never raising and never guessing a date.
    """

    if not raw_value:
        return None
    try:
        return datetime.fromisoformat(str(raw_value).replace("Z", "+00:00")).date()
    except ValueError:
        logger.warning("Could not parse ranking publication date %r; leaving it unset.", raw_value)
        return None


@rankings_registry.register("wta_official")
class WtaOfficialRankingsProvider(RankingsProvider):
    """Fetches current WTA singles rankings from ``api.wtatennis.com``."""

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        ranking_type: str = "rankSingles",
        metric: str = "singles",
        network: NetworkConfig | None = None,
        **_ignored: object,
    ) -> None:
        self._client = WtaOfficialApiClient(base_url=base_url, network=network)
        self._ranking_type = ranking_type
        self._metric = metric

    def get_top_n(self, n: int) -> list[PlayerRanking]:
        raw = self._client.get_rankings(
            ranking_type=self._ranking_type, metric=self._metric, page_size=n
        )
        rankings: list[PlayerRanking] = []
        for entry in raw:
            try:
                player = entry["player"]
                rankings.append(
                    PlayerRanking(
                        rank=int(entry["ranking"]),
                        player_id=str(player["id"]),
                        name=str(player["fullName"]),
                        country_code=str(player.get("countryCode", "")),
                        points=int(entry.get("points", 0)),
                        ranking_date=_parse_ranked_at(entry.get("rankedAt")),
                    )
                )
            except (KeyError, TypeError, ValueError) as exc:
                logger.warning("Skipping malformed ranking entry %r: %s", entry, exc)
        if not rankings:
            raise DataProviderError("WTA rankings response contained no usable entries.")
        rankings.sort(key=lambda r: r.rank)
        return rankings[:n]
