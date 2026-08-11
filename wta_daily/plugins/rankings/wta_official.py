"""Rankings provider backed by the official WTA JSON backend.

See :mod:`wta_daily.plugins.wta_api_client` for the rationale behind choosing
this data source.
"""

from __future__ import annotations

import logging

from wta_daily.config import NetworkConfig
from wta_daily.exceptions import DataProviderError
from wta_daily.models import PlayerRanking
from wta_daily.plugins.base import RankingsProvider
from wta_daily.plugins.registry import rankings_registry
from wta_daily.plugins.wta_api_client import DEFAULT_BASE_URL, WtaOfficialApiClient

logger = logging.getLogger(__name__)


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
                    )
                )
            except (KeyError, TypeError, ValueError) as exc:
                logger.warning("Skipping malformed ranking entry %r: %s", entry, exc)
        if not rankings:
            raise DataProviderError("WTA rankings response contained no usable entries.")
        rankings.sort(key=lambda r: r.rank)
        return rankings[:n]
