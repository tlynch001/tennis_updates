"""Thin client for the paid, self-serve `livetennisapi.com <https://livetennisapi.com>`_ API.

Unlike ``api.wtatennis.com`` (see :mod:`wta_daily.plugins.wta_api_client`),
this is a genuinely commercial, independent (not WTA-licensed) aggregator
with a published, self-serve pricing page. It was added specifically to
address a documented limitation of the free WTA endpoint: it can lag
real-world results by more than a week during/right after a tournament.
Empirically, this provider's records update within a day or two of a match
finishing (checked by comparing its ``updated_at`` against a match's actual
date for several current Top 10 results).

Every completed match here carries a genuine per-match ``scheduled_time``
(ISO 8601 UTC) and an explicit ``event_status`` for retirements/walkovers/
cancellations - no "tournament start date" ambiguity like the free feed had.

Player identity is **not** shared with ``api.wtatennis.com`` - this service
has its own numeric player ids, resolved by name search (``GET /players``);
see :mod:`wta_daily.plugins.matches.live_tennis_api` for how that resolution
is done defensively (doubles teams and unranked namesakes filtered out).

The API key is **never** hardcoded here or anywhere else in this project.
It is resolved from an environment variable (``api_key_env`` in config,
default ``LIVETENNISAPI_KEY``) - see the README's "Match-data reliability"
section and ``.env.example``.
"""

from __future__ import annotations

from typing import Any

from wta_daily import api_usage
from wta_daily.config import NetworkConfig
from wta_daily.exceptions import ConfigurationError
from wta_daily.http_client import HttpClient

DEFAULT_BASE_URL = "https://api.livetennisapi.com/api/public/v1"

#: api_usage category - see wta_daily.api_usage and the README's
#: "Understanding API usage" section.
_CATEGORY = "LiveTennisAPI"


class LiveTennisApiClient:
    """Wraps the handful of ``livetennisapi.com`` endpoints this project needs."""

    def __init__(
        self,
        api_key: str | None,
        base_url: str = DEFAULT_BASE_URL,
        network: NetworkConfig | None = None,
    ) -> None:
        if not api_key:
            raise ConfigurationError(
                "livetennisapi.com match provider is configured but no API key was found. "
                "Set the environment variable named by match_provider.api_key_env "
                "(default LIVETENNISAPI_KEY) - never put the key in config.yaml. See "
                ".env.example and the README's 'Match-data reliability' section."
            )
        self._base_url = base_url.rstrip("/")
        self._http = HttpClient(network)
        self._auth_header = {"Authorization": f"Bearer {api_key}"}

    def search_players(self, name: str, *, limit: int = 10) -> list[dict[str, Any]]:
        """``GET /players`` - search players by (partial, case-insensitive) name."""

        url = f"{self._base_url}/players"
        api_usage.record(_CATEGORY)
        data = self._http.get_json(
            url, params={"search": name, "limit": limit}, headers=self._auth_header
        )
        results = data.get("data", []) if isinstance(data, dict) else []
        if not isinstance(results, list):
            raise ValueError(f"Unexpected players response shape from {url}: {type(results)!r}")
        return results

    def get_completed_matches(self, player_id: int | str, *, limit: int = 20) -> list[dict[str, Any]]:
        """``GET /history/matches`` - a player's completed matches, newest first."""

        url = f"{self._base_url}/history/matches"
        api_usage.record(_CATEGORY)
        data = self._http.get_json(
            url, params={"player": player_id, "limit": limit}, headers=self._auth_header
        )
        results = data.get("data", []) if isinstance(data, dict) else []
        if not isinstance(results, list):
            raise ValueError(
                f"Unexpected history/matches response shape from {url}: {type(results)!r}"
            )
        return results
