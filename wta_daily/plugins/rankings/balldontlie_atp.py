"""ATP rankings provider backed by BALLDONTLIE's permanent free tier.

Maps ``GET /atp/v1/rankings`` into the existing
:class:`~wta_daily.models.PlayerRanking` model. Vendor ``movement`` is
**not** copied onto the ranking: the pipeline already computes report
movement from consecutive official snapshots (and ``ranking_date``) via
:func:`wta_daily.movement.compute_movement`. Applying both would produce
two conflicting movement values.

``ranking_date`` is taken from the payload when present and parseable.
It is never replaced with today's date; missing/null/unparseable values
stay ``None`` ("unknown").
"""

from __future__ import annotations

import logging
import os
from datetime import date, datetime

from wta_daily.config import NetworkConfig
from wta_daily.exceptions import DataProviderError
from wta_daily.models import PlayerRanking
from wta_daily.plugins.balldontlie_atp_client import (
    DEFAULT_BASE_URL,
    BalldontlieAtpClient,
)
from wta_daily.plugins.base import RankingsProvider
from wta_daily.plugins.registry import rankings_registry

logger = logging.getLogger(__name__)


def _parse_ranking_date(raw_value: object) -> date | None:
    """Parse BALLDONTLIE ``ranking_date`` (documented as ``YYYY-MM-DD``).

    Never guesses. A missing, null, or unparseable value is ``None`` —
    the pipeline already treats that as "unknown official list date,"
    not as "changed today."
    """

    if raw_value in (None, ""):
        return None
    if isinstance(raw_value, date) and not isinstance(raw_value, datetime):
        return raw_value
    text = str(raw_value).strip()
    if not text:
        return None
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        if "T" in text:
            return datetime.fromisoformat(text).date()
        return date.fromisoformat(text[:10])
    except ValueError:
        logger.warning("Could not parse BALLDONTLIE ranking_date %r; leaving it unset.", raw_value)
        return None


def _player_name(player: dict[str, object]) -> str:
    full = player.get("full_name")
    if isinstance(full, str) and full.strip():
        return full.strip()
    parts = [player.get("first_name"), player.get("last_name")]
    return " ".join(str(part).strip() for part in parts if isinstance(part, str) and part.strip())


def _map_entry(entry: dict[str, object]) -> PlayerRanking | None:
    player = entry.get("player")
    if not isinstance(player, dict):
        raise TypeError("ranking entry is missing a player object")
    player_id = player.get("id")
    if player_id in (None, ""):
        raise ValueError("player object is missing a stable id")
    name = _player_name(player)
    if not name:
        raise ValueError("player object is missing a name")
    country = player.get("country_code") or ""
    return PlayerRanking(
        rank=int(entry["rank"]),
        player_id=str(player_id),
        name=name,
        country_code=str(country),
        points=int(entry.get("points", 0)),
        ranking_date=_parse_ranking_date(entry.get("ranking_date")),
    )


@rankings_registry.register("balldontlie_atp")
class BalldontlieAtpRankingsProvider(RankingsProvider):
    """Fetches current ATP singles rankings from BALLDONTLIE (free tier)."""

    def __init__(
        self,
        api_key_env: str = "BALLDONTLIE_API_KEY",
        base_url: str = DEFAULT_BASE_URL,
        network: NetworkConfig | None = None,
        per_page: int | None = None,
        **_ignored: object,
    ) -> None:
        self._client = BalldontlieAtpClient(
            os.environ.get(api_key_env),
            api_key_env=api_key_env,
            base_url=base_url,
            network=network,
        )
        self._per_page = per_page

    def get_top_n(self, n: int) -> list[PlayerRanking]:
        raw = self._client.get_rankings(n, per_page=self._per_page)
        rankings: list[PlayerRanking] = []
        for entry in raw:
            try:
                mapped = _map_entry(entry)
            except (KeyError, TypeError, ValueError) as exc:
                logger.warning("Skipping malformed BALLDONTLIE ranking entry %r: %s", entry, exc)
                continue
            rankings.append(mapped)
        if not rankings:
            raise DataProviderError("BALLDONTLIE ATP rankings response contained no usable entries.")
        rankings.sort(key=lambda r: r.rank)
        return rankings[:n]
