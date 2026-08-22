"""ATP rankings provider backed by api-tennis.com ``get_standings``.

This is a **new ATP-only plugin**. It does not change the existing WTA
``api_tennis`` match provider, which still hard-codes ``event_type="WTA"``
for player-key resolution.

Vendor contract (see ``docs/atp-data-source-spike.md``):

* ``method=get_standings&event_type=ATP``
* REST row fields: ``place``, ``player``, ``player_key``, ``league``,
  ``points``, ``country`` (a name, not an IOC code)
* There is **no** official ranking-list publication date on the standings
  row. ``PlayerRanking.ranking_date`` is left ``None`` - never substituted
  with today or the reporting day.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from wta_daily.config import NetworkConfig
from wta_daily.countries import country_code_from_name
from wta_daily.exceptions import DataProviderError
from wta_daily.models import PlayerRanking
from wta_daily.plugins.api_tennis_client import DEFAULT_BASE_URL, ApiTennisClient
from wta_daily.plugins.base import RankingsProvider
from wta_daily.plugins.registry import rankings_registry

logger = logging.getLogger(__name__)

_ATP_LEAGUE_MARKERS = frozenset({"atp"})
_WTA_LEAGUE_MARKERS = frozenset({"wta"})


def _parse_points(raw: object) -> int:
    if raw is None or raw == "":
        raise ValueError("ranking points are missing")
    text = str(raw).strip().replace(",", "")
    if not text:
        raise ValueError("ranking points are missing")
    return int(text)


def _parse_player_key(row: dict[str, Any]) -> str:
    raw = row.get("player_key")
    if raw is None or raw == "":
        raise ValueError("player_key is missing")
    key = str(raw).strip()
    if not key.isdigit():
        raise ValueError(f"player_key is not a numeric vendor id: {raw!r}")
    return key


def _league_token(row: dict[str, Any]) -> str:
    raw = row.get("league") or row.get("tour") or ""
    return str(raw).strip().lower()


@rankings_registry.register("api_tennis_atp")
class ApiTennisAtpRankingsProvider(RankingsProvider):
    """Fetches current ATP singles standings from api-tennis.com."""

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        api_key_env: str = "APITENNIS_KEY",
        network: NetworkConfig | None = None,
        **_ignored: object,
    ) -> None:
        api_key = os.environ.get(api_key_env)
        self._client = ApiTennisClient(api_key=api_key, base_url=base_url, network=network)
        self._standings_cache: list[PlayerRanking] | None = None

    def get_top_n(self, n: int) -> list[PlayerRanking]:
        if self._standings_cache is None:
            self._standings_cache = self._load_standings()
        return self._standings_cache[:n]

    def _load_standings(self) -> list[PlayerRanking]:
        try:
            raw = self._client.get_standings(event_type="ATP")
        except Exception as exc:  # noqa: BLE001 - surface vendor/network failure
            raise DataProviderError(f"ATP standings request failed: {exc}") from exc

        if not raw:
            raise DataProviderError("ATP standings response contained no rows.")

        rankings: list[PlayerRanking] = []
        for entry in raw:
            try:
                rankings.append(self._parse_row(entry))
            except DataProviderError:
                raise
            except (KeyError, TypeError, ValueError) as exc:
                logger.error("Skipping unusable ATP standings row %r: %s", entry, exc)

        if not rankings:
            raise DataProviderError("ATP standings response contained no usable entries.")
        rankings.sort(key=lambda r: r.rank)
        return rankings

    def _parse_row(self, entry: dict[str, Any]) -> PlayerRanking:
        league = _league_token(entry)
        if league in _WTA_LEAGUE_MARKERS:
            raise DataProviderError(
                f"ATP rankings provider received a WTA standings row ({entry!r}). "
                "Refusing to treat WTA players as ATP."
            )
        if league and league not in _ATP_LEAGUE_MARKERS:
            raise DataProviderError(
                f"ATP rankings provider received a non-ATP standings row "
                f"(league={entry.get('league')!r}): {entry!r}."
            )

        rank_raw = entry.get("place", entry.get("rank"))
        if rank_raw is None or rank_raw == "":
            raise ValueError("rank/place is missing")
        name = str(entry.get("player") or "").strip()
        if not name:
            raise ValueError("player name is missing")

        country_raw = str(entry.get("country") or "").strip()
        country_code = country_code_from_name(country_raw)
        if country_raw and not country_code:
            logger.info(
                "ATP standings country %r for %s could not be mapped to an IOC code; "
                "leaving country_code empty.",
                country_raw,
                name,
            )

        return PlayerRanking(
            rank=int(rank_raw),
            player_id=_parse_player_key(entry),
            name=name,
            country_code=country_code,
            points=_parse_points(entry.get("points")),
            previous_rank=None,
            ranking_date=None,
        )
