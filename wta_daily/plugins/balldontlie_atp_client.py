"""Thin client for the BALLDONTLIE ATP HTTP API.

Used by the free ATP rankings provider
(:mod:`wta_daily.plugins.rankings.balldontlie_atp`). Matches, ATP Race, and
other ALL-STAR endpoints are intentionally not wrapped here - ATP v1 is
rankings-only.

Current contract (OpenAPI ``https://www.balldontlie.io/openapi/atp.yml``,
verified 22 August 2026):

* ``GET https://api.balldontlie.io/atp/v1/rankings`` — documented Free tier
* Auth: ``Authorization`` header set to the raw API key (not ``Bearer``)
* Pagination: ``cursor`` / ``per_page`` (max 100, default 25) and
  ``meta.next_cursor``
* Ranking object: ``rank``, ``points``, ``movement`` (nullable week change),
  ``ranking_date``, ``player`` (including stable ``id``)
* Free-tier rate limit: 5 requests / minute

The API key is **never** hardcoded. It is resolved from an environment
variable (``api_key_env``, default ``BALLDONTLIE_API_KEY``) — see
``.env.example``. A missing or rejected key raises
:class:`~wta_daily.exceptions.ConfigurationError` immediately; 401 is not
retried (the shared :class:`~wta_daily.http_client.HttpClient` retries every
HTTP error, including auth failures).
"""

from __future__ import annotations

import logging
import time
from typing import Any

import requests

from wta_daily import api_usage
from wta_daily.config import NetworkConfig
from wta_daily.exceptions import ConfigurationError, DataProviderError

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://api.balldontlie.io"
RANKINGS_PATH = "/atp/v1/rankings"
MAX_PER_PAGE = 100
DEFAULT_PER_PAGE = 25

#: api_usage category — see wta_daily.api_usage.
_CATEGORY = "BALLDONTLIE ATP"


class BalldontlieAtpClient:
    """Wraps the free BALLDONTLIE ATP rankings endpoint."""

    def __init__(
        self,
        api_key: str | None,
        *,
        api_key_env: str = "BALLDONTLIE_API_KEY",
        base_url: str = DEFAULT_BASE_URL,
        network: NetworkConfig | None = None,
    ) -> None:
        if not api_key:
            raise ConfigurationError(
                "BALLDONTLIE ATP rankings provider is configured but no API key was found. "
                f"Set the environment variable {api_key_env} in your local .env file "
                "(see .env.example). Never put the key in config YAML, source, or tests."
            )
        self._api_key_env = api_key_env
        self._base_url = base_url.rstrip("/")
        self._network = network or NetworkConfig()
        self._session = requests.Session()
        self._session.headers.update(
            {
                "User-Agent": self._network.user_agent,
                "Authorization": api_key,
            }
        )

    def get_rankings(self, n: int, *, per_page: int | None = None) -> list[dict[str, Any]]:
        """Return at least the first ``n`` ranking rows, paginating if needed.

        One request is enough for a Top 10 (or the default ``rankings_pool_size``
        of 25): ``per_page`` is capped at 100 and defaults to ``max(n, 25)``.
        Extra pages are fetched only when ``meta.next_cursor`` is present and
        fewer than ``n`` usable rows have been collected.
        """

        if n < 1:
            return []
        page_size = min(MAX_PER_PAGE, per_page if per_page is not None else max(n, DEFAULT_PER_PAGE))
        collected: list[dict[str, Any]] = []
        cursor: int | None = None
        while len(collected) < n:
            payload = self._get_rankings_page(per_page=page_size, cursor=cursor)
            rows = payload.get("data") if isinstance(payload, dict) else None
            if not isinstance(rows, list):
                raise DataProviderError(
                    f"Unexpected BALLDONTLIE rankings response shape: {type(payload)!r}"
                )
            collected.extend(row for row in rows if isinstance(row, dict))
            meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
            next_cursor = meta.get("next_cursor")
            if next_cursor is None or not rows:
                break
            cursor = int(next_cursor)
        return collected

    def _get_rankings_page(self, *, per_page: int, cursor: int | None) -> dict[str, Any]:
        url = f"{self._base_url}{RANKINGS_PATH}"
        params: dict[str, Any] = {"per_page": per_page}
        if cursor is not None:
            params["cursor"] = cursor
        api_usage.record(_CATEGORY)
        last_exc: Exception | None = None
        for attempt in range(1, self._network.max_retries + 1):
            try:
                response = self._session.get(
                    url, params=params, timeout=self._network.timeout_seconds
                )
                if response.status_code == 401:
                    raise ConfigurationError(
                        "BALLDONTLIE rejected the ATP rankings request (HTTP 401). "
                        f"Check that {self._api_key_env} in your local .env is a valid "
                        "BALLDONTLIE API key. See .env.example."
                    )
                response.raise_for_status()
                data = response.json()
                if not isinstance(data, dict):
                    raise DataProviderError(
                        f"BALLDONTLIE rankings response was not an object: {type(data)!r}"
                    )
                return data
            except ConfigurationError:
                raise
            except (requests.RequestException, ValueError, DataProviderError) as exc:
                last_exc = exc
                if attempt < self._network.max_retries:
                    delay = self._network.backoff_factor**attempt
                    logger.warning(
                        "BALLDONTLIE rankings request failed (attempt %d/%d): %s. "
                        "Retrying in %.1fs.",
                        attempt,
                        self._network.max_retries,
                        exc,
                        delay,
                    )
                    time.sleep(delay)
        raise DataProviderError(
            f"Failed to GET {url} after {self._network.max_retries} attempts: {last_exc}"
        ) from last_exc
