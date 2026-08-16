"""Thin client for the WTA's own public JSON backend (``api.wtatennis.com``).

This is the same backend that powers https://www.wtatennis.com. It is
selected as the default data source for this project because it is:

* **Official** - the data originates directly from the WTA, not a scraped or
  reverse-engineered third party mirror.
* **Machine-readable** - plain JSON over HTTPS, no HTML scraping involved.
* **Openly reachable** - no API key, no auth wall, and ``wtatennis.com``'s
  ``robots.txt`` does not disallow automated access to any path
  (``Disallow:`` is empty).
* **Free** - no cost, which matters for a hobby/unattended daily job.

Caveat documented in the README: this endpoint is undocumented/unofficial in
the sense that the WTA has not published a formal developer API contract or
terms of use for it, so it could change or be rate-limited without notice.
Because the whole project is built around the :class:`RankingsProvider` /
:class:`MatchProvider` plugin interfaces, swapping to a licensed commercial
provider (e.g. Sportradar/Stats Perform, or a paid RapidAPI tennis feed) if
that ever becomes necessary is a matter of adding one new module, not
rewriting the pipeline.
"""

from __future__ import annotations

from typing import Any

from wta_daily import api_usage
from wta_daily.config import NetworkConfig
from wta_daily.http_client import HttpClient

DEFAULT_BASE_URL = "https://api.wtatennis.com/tennis"

#: api_usage categories - see wta_daily.api_usage and the README's
#: "Understanding API usage" section.
_CATEGORY_RANKINGS = "WTA rankings"
_CATEGORY_TOURNAMENT_DISCOVERY = "WTA tournament discovery"
_CATEGORY_MATCH_RESULTS = "WTA match results"


class WtaOfficialApiClient:
    """Wraps the handful of endpoints this project needs."""

    def __init__(self, base_url: str = DEFAULT_BASE_URL, network: NetworkConfig | None = None) -> None:
        self._base_url = base_url.rstrip("/")
        self._http = HttpClient(network)
        # Per-instance (i.e. per-run, since one client is built per pipeline
        # run) cache so that asking for the same tournament-catalogue page
        # twice - e.g. page 0 is fetched once up front to learn the total
        # entry count, and could otherwise legitimately fall inside the
        # scan range too - never issues a second identical HTTP request.
        self._tournament_page_cache: dict[tuple[int, int], dict[str, Any]] = {}

    def get_rankings(
        self, *, ranking_type: str = "rankSingles", metric: str = "singles", page_size: int = 10
    ) -> list[dict[str, Any]]:
        url = f"{self._base_url}/players/ranked"
        api_usage.record(_CATEGORY_RANKINGS)
        data = self._http.get_json(
            url, params={"type": ranking_type, "metric": metric, "page": 0, "pageSize": page_size}
        )
        if not isinstance(data, list):
            raise ValueError(f"Unexpected rankings response shape from {url}: {type(data)!r}")
        return data

    def get_player_matches(self, player_id: str, *, page_size: int = 25) -> list[dict[str, Any]]:
        """Return a player's match history, most recent first.

        Ordering (``sort=desc``) reflects genuine chronology reasonably well
        (verified empirically - later rounds of a tournament consistently
        come back before earlier rounds, and more recent tournaments before
        older ones). The per-entry ``StartDate``/``tournament.startDate``
        fields, however, are the *tournament's* start date repeated for
        every round, not the date that specific match was played - see
        :mod:`wta_daily.plugins.matches.wta_official` for how the real,
        match-level date is recovered via :meth:`get_tournament_matches`.
        """

        url = f"{self._base_url}/players/{player_id}/matches"
        api_usage.record(_CATEGORY_MATCH_RESULTS)
        data = self._http.get_json(url, params={"page": 0, "pageSize": page_size, "sort": "desc"})
        matches = data.get("matches", []) if isinstance(data, dict) else []
        if not isinstance(matches, list):
            raise ValueError(f"Unexpected matches response shape from {url}: {type(matches)!r}")
        return matches

    def list_tournaments_page(self, *, page: int, page_size: int = 100) -> dict[str, Any]:
        """One page of the full tournament catalogue (``{pageInfo, content}``).

        There is no working date/status filter on this endpoint (confirmed
        by testing - ``year=``/``status=`` query params are silently
        ignored), so finding "what's happening this week" means paging
        through this catalogue and filtering client-side by
        ``startDate``/``endDate``. Entries are in roughly chronological
        order (it starts at 1960), so the current season's events are near
        the *end* - see :func:`wta_daily.plugins.matches.wta_official._find_active_tournaments`
        for how this is used without scanning the whole ~19,000-entry list
        on every run.

        Cached per ``(page, page_size)`` for the lifetime of this client
        instance (i.e. for one pipeline run), so asking for the same page
        twice - which happens legitimately when page 0 is fetched up front
        to learn the total entry count and also happens to fall inside the
        scan range - only ever issues one real HTTP request.
        """

        cache_key = (page, page_size)
        if cache_key in self._tournament_page_cache:
            return self._tournament_page_cache[cache_key]

        url = f"{self._base_url}/tournaments"
        api_usage.record(_CATEGORY_TOURNAMENT_DISCOVERY)
        data = self._http.get_json(url, params={"page": page, "pageSize": page_size})
        if not isinstance(data, dict) or "content" not in data:
            raise ValueError(f"Unexpected tournaments response shape from {url}: {type(data)!r}")
        self._tournament_page_cache[cache_key] = data
        return data

    def get_tournament_matches(
        self, tournament_group_id: int | str, year: int | str, *, page_size: int = 500
    ) -> list[dict[str, Any]]:
        """Return every match (singles and doubles, all rounds) for one tournament edition.

        Unlike the per-player match history, each entry here carries a real
        per-match ``MatchTimeStamp`` and a ``MatchState`` ("F" once the match
        has actually finished), which is what makes this endpoint useful for
        recovering an authoritative match date instead of a tournament start
        date. In practice this endpoint appears to ignore ``pageSize`` and
        just returns the whole tournament's match list in one response.
        """

        url = f"{self._base_url}/tournaments/{tournament_group_id}/{year}/matches"
        api_usage.record(_CATEGORY_MATCH_RESULTS)
        data = self._http.get_json(url, params={"page": 0, "pageSize": page_size})
        matches = data.get("matches", []) if isinstance(data, dict) else []
        if not isinstance(matches, list):
            raise ValueError(
                f"Unexpected tournament-matches response shape from {url}: {type(matches)!r}"
            )
        return matches
