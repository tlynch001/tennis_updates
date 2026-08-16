"""Thin client for the paid `api-tennis.com <https://api-tennis.com>`_ API.

A second paid, self-serve, independent (not WTA-licensed) aggregator,
evaluated alongside `livetennisapi.com <https://livetennisapi.com>`_ (see
:mod:`wta_daily.plugins.live_tennis_api_client`) as another candidate
``best_of`` source. Unlike that service, ``api-tennis.com`` uses a single
endpoint with a ``method=`` query parameter (not REST-style paths) and
passes the API key as a query parameter (``APIkey=``) rather than an
``Authorization`` header.

Empirically (see :mod:`wta_daily.plugins.matches.api_tennis` for the full
comparison writeup): this source's rankings (``get_standings``) matched
``api.wtatennis.com`` exactly, and its match coverage was noticeably more
complete than `livetennisapi.com` for at least one player who had a real
multi-month gap there. It does have its own quirk - a small number of
matches were observed one calendar day later than the same match's
independently-confirmed date from the other two sources, so it is combined
via ``best_of`` rather than trusted in isolation, same as the other paid
source.

The API key is **never** hardcoded here or anywhere else in this project.
It is resolved from an environment variable (``api_key_env`` in config,
default ``APITENNIS_KEY``) - see the README's "Match-data reliability"
section and ``.env.example``.
"""

from __future__ import annotations

from typing import Any

from wta_daily import api_usage
from wta_daily.config import NetworkConfig
from wta_daily.exceptions import ConfigurationError
from wta_daily.http_client import HttpClient

DEFAULT_BASE_URL = "https://api.api-tennis.com/tennis/"

#: api_usage category - see wta_daily.api_usage and the README's
#: "Understanding API usage" section.
_CATEGORY = "API-Tennis"


class ApiTennisClient:
    """Wraps the handful of ``api-tennis.com`` methods this project needs."""

    def __init__(
        self,
        api_key: str | None,
        base_url: str = DEFAULT_BASE_URL,
        network: NetworkConfig | None = None,
    ) -> None:
        if not api_key:
            raise ConfigurationError(
                "api-tennis.com match provider is configured but no API key was found. "
                "Set the environment variable named by match_provider.api_key_env "
                "(default APITENNIS_KEY) - never put the key in config.yaml. See "
                ".env.example and the README's 'Match-data reliability' section."
            )
        self._base_url = base_url
        self._http = HttpClient(network)
        self._api_key = api_key

    def _call(self, method: str, **params: Any) -> list[dict[str, Any]]:
        query = {"method": method, "APIkey": self._api_key, **params}
        api_usage.record(_CATEGORY)
        data = self._http.get_json(self._base_url, params=query)
        if not isinstance(data, dict) or data.get("success") != 1:
            raise ValueError(f"api-tennis.com method={method} did not report success: {data!r}")
        result = data.get("result", [])
        if not isinstance(result, list):
            raise ValueError(f"Unexpected result shape from method={method}: {type(result)!r}")
        return result

    def get_standings(self, *, event_type: str = "WTA") -> list[dict[str, Any]]:
        """``method=get_standings`` - rank-ordered list with each player's ``player_key``."""

        return self._call("get_standings", event_type=event_type)

    def get_fixtures(
        self, *, player_key: int | str, date_start: str, date_stop: str
    ) -> list[dict[str, Any]]:
        """``method=get_fixtures`` - one player's matches (any status) in a date range."""

        return self._call(
            "get_fixtures", player_key=player_key, date_start=date_start, date_stop=date_stop
        )
