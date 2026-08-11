"""Small shared HTTP helper with sane timeouts and retry/backoff.

Centralizing this avoids every provider re-implementing its own retry loop
and makes it trivial to swap in a different HTTP library later.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import requests

from wta_daily.config import NetworkConfig
from wta_daily.exceptions import DataProviderError

logger = logging.getLogger(__name__)


class HttpClient:
    """A ``requests``-backed client with retry/backoff for transient failures."""

    def __init__(self, network: NetworkConfig | None = None) -> None:
        self._network = network or NetworkConfig()
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": self._network.user_agent})

    def get_json(self, url: str, *, params: dict[str, Any] | None = None) -> Any:
        last_exc: Exception | None = None
        for attempt in range(1, self._network.max_retries + 1):
            try:
                response = self._session.get(
                    url, params=params, timeout=self._network.timeout_seconds
                )
                response.raise_for_status()
                return response.json()
            except (requests.RequestException, ValueError) as exc:
                last_exc = exc
                if attempt < self._network.max_retries:
                    delay = self._network.backoff_factor ** attempt
                    logger.warning(
                        "Request to %s failed (attempt %d/%d): %s. Retrying in %.1fs.",
                        url,
                        attempt,
                        self._network.max_retries,
                        exc,
                        delay,
                    )
                    time.sleep(delay)
        raise DataProviderError(
            f"Failed to GET {url} after {self._network.max_retries} attempts: {last_exc}"
        ) from last_exc
