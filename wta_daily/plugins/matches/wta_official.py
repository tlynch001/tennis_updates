"""Match provider backed by the official WTA JSON backend.

See :mod:`wta_daily.plugins.wta_api_client` for the rationale behind choosing
this data source, and the module docstring below for how "latest completed
singles match" is actually established.

## Why this needed repairing (production incident, August 2026)

The first production run showed every Top 10 player's ``match_date`` equal
to their most recent tournament's *start* date (e.g. Wimbledon's
``2026-06-29``) regardless of which round the reported match was actually
from. The root cause: ``GET /players/{id}/matches`` returns one
``StartDate``/``tournament.startDate`` value per tournament, repeated
identically for every round played in it - there is no genuine per-match
date anywhere in that response. The previous implementation copied that
tournament-start value straight into ``match_date``, which is exactly the
"tournament start date used as match date" bug.

Separately, that same endpoint can lag real-world results by more than a
week during/just after a tournament (confirmed by comparing its output for
a top player against the tournament's own live results a few days into an
event) - so ``sort=desc`` selects the most recent entry *that endpoint
currently knows about*, which is not guaranteed to be the player's true
most recent match at query time. There is no cheap way to discover "what
tournaments are happening right now" from this API (the tournaments list
endpoint returns its full ~19,000-entry history back to 1960 with no
working date/status filter), so rather than build a speculative live-event
scanner, this provider is honest about the limitation instead: whatever it
reports is real and verified, even if - rarely, during a live event's
opening days - it might lag by a few days until this endpoint catches up.

The fix implemented here:

1. Still use ``/players/{id}/matches`` (``sort=desc``) to find the most
   recent *singles result with a real score* (i.e. not a bye, walkover, or
   still-scheduled entry) - this part of the endpoint's behavior (which
   match is "more recent" than which) checks out fine; only the literal
   date *value* it reports is wrong.
2. For that candidate, look up the authoritative match date via
   ``GET /tournaments/{groupId}/{year}/matches``, which - unlike the
   per-player endpoint - includes a genuine per-match ``MatchTimeStamp``
   and a ``MatchState`` ("F" = finished) for every fixture in that
   tournament. The two player IDs uniquely identify the fixture within one
   tournament's draw, so no round-code translation between the two
   endpoints' different naming schemes is needed.
3. If that lookup can't confirm a date (network hiccup, fixture not found,
   endpoint shape change, etc.), ``match_date`` is left as ``None`` rather
   than falling back to a tournament date - never re-introduce the original
   bug via a "helpful" fallback.

## The deeper staleness problem, and the day-first fix (research, August 2026)

Even with the date fix above, ``get_latest_match`` can still be *wrong in
substance*: it reads ``/players/{id}/matches``, and that per-player history
endpoint has been directly observed to lag the current tournament week by
several days - e.g. three Top 10 players had already won a second-round
match at the following week's tournament while this endpoint still showed
nothing past the previous event for any of them. Confirmed live: the
tournament-level endpoint (``get_tournament_matches``) already had those
exact matches, correctly dated, the same day they were played. The WTA's
own website is built on this same backend (its frontend config literally
declares ``"api": "https://api.wtatennis.com"``), so the freshness clearly
exists somewhere in this API - just not in the per-player endpoint.

:meth:`WtaOfficialMatchProvider.get_matches_for_date` is the fix: instead of
asking "what's this player's latest known match" (a question the per-player
endpoint answers slowly), it asks "which matches finished on this exact
date" by scanning the tournament catalogue for events active on that date
and reading their match lists directly - the same near-real-time source the
website itself benefits from. A player absent from the result is reported
as not having played that day; nothing ever falls back to an older match.
This was proven against a real historical date (see the project's PR
history) with zero discrepancies against three independent third-party
sources.

One tradeoff: a match discovered this way, for a player whose per-player
history hasn't caught up yet, can't be cross-referenced against that
history's nicer round-name text (there's nothing to cross-reference - that's
the whole reason day-first was needed). Round labels for those matches fall
back to a plainer ``"{Main Draw|Qualifying} Round {n}"`` built directly from
the tournament feed's own ``DrawLevelType``/``RoundID`` fields, which are
correct but less polished than the ``R16``/``Quarterfinal``-style names
available once the per-player endpoint does catch up. Opponent name, score,
date, and win/loss are unaffected by this - they come directly from the
tournament feed either way.
"""

from __future__ import annotations

import dataclasses
import logging
from collections.abc import Sequence
from datetime import UTC, date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from wta_daily.config import NetworkConfig
from wta_daily.exceptions import DataProviderError, PlayerDataError
from wta_daily.models import (
    MatchLookupResult,
    MatchResult,
    PlayerRanking,
    TournamentRunStatus,
    TournamentState,
)
from wta_daily.plugins.base import MatchProvider
from wta_daily.plugins.matches.tournament_status import determine_tournament_run_status
from wta_daily.plugins.registry import matches_registry
from wta_daily.plugins.wta_api_client import DEFAULT_BASE_URL, WtaOfficialApiClient
from wta_daily.points_table import DEFAULT_POINTS_TABLE_PATH, PointsTable, load_points_table
from wta_daily.reporting_day import DEFAULT_CUTOFF_HOUR, reporting_date_for_completion
from wta_daily.tournament_timezones import (
    DEFAULT_TOURNAMENT_TIMEZONES_PATH,
    TournamentTimezones,
    load_tournament_timezones,
)

logger = logging.getLogger(__name__)

_ROUND_NAMES: dict[str, str] = {
    "R128": "Round of 128",
    "R64": "Round of 64",
    "R32": "Round of 32",
    "R16": "Round of 16",
    # The WTA backend uses single-letter codes for the final three rounds of a
    # standard draw (as opposed to e.g. "QF"/"SF", which some other feeds use).
    "Q": "Quarterfinal",
    "QF": "Quarterfinal",
    "S": "Semifinal",
    "SF": "Semifinal",
    "F": "Final",
    "Q1": "1st Round Qualifying",
    "Q2": "2nd Round Qualifying",
    "Q3": "3rd Round Qualifying",
    "RR": "Round Robin",
}

#: A completed, "genuinely finished" fixture in the tournament-matches feed.
_FINISHED_MATCH_STATE = "F"

#: ``DrawMatchType``/``s_d_flag`` value meaning singles (as opposed to doubles).
_SINGLES = "S"


def _friendly_round(code: str) -> str:
    return _ROUND_NAMES.get(code, code)


def _parse_score(raw: str) -> str:
    return " ".join(raw.split())


_TOURNAMENT_NAME_OVERRIDES = {"Dc": "DC", "Us": "US", "Uae": "UAE"}


def _titleize_tournament(raw: str) -> str:
    words = raw.title().split()
    return " ".join(_TOURNAMENT_NAME_OVERRIDES.get(word, word) for word in words)


#: DrawLevelType in the tournament-matches feed: "M" (main draw) or "Q" (qualifying).
_DRAW_LEVEL_LABELS = {"M": "Main Draw", "Q": "Qualifying"}

#: WTA tour levels worth scanning for the day-first lookup - deliberately
#: excludes ITF/Challenger/junior events, which never involve Top N players.
_RELEVANT_TOUR_LEVELS = {
    "GRAND SLAM",
    "WTA 1000",
    "WTA 500",
    "WTA 250",
    "WTA FINALS",
    "OLYMPICS",
}


@dataclasses.dataclass(frozen=True)
class _ActiveTournament:
    """One tournament catalogue entry whose date range covers a given
    target date - see :meth:`WtaOfficialMatchProvider._find_active_tournaments`.
    ``level``/``draw_size`` are only used for the tournament-status/
    points-table lookups; ``country`` is only used to resolve the
    tournament's local timezone for the "reporting day" cutoff (see
    :mod:`wta_daily.reporting_day`/:mod:`wta_daily.tournament_timezones`).
    The day-first match lookup itself only ever strictly needed
    ``group_id``/``year``/``name``.
    """

    group_id: Any
    year: Any
    name: str
    level: str
    draw_size: int | None
    country: str | None = None


def _fallback_round_label(fixture: dict[str, Any]) -> str:
    """Best-effort round label built directly from a tournament-level fixture.

    Used only when there's no per-player-endpoint entry to borrow a nicer
    ``round_name`` from - see the module docstring.
    """

    level = _DRAW_LEVEL_LABELS.get(str(fixture.get("DrawLevelType", "")), "")
    round_id = fixture.get("RoundID")
    if round_id is None:
        return level or "Unknown Round"
    return f"{level} Round {round_id}".strip()


def _parse_utc_timestamp(raw: Any) -> datetime | None:
    """Parse a ``MatchTimeStamp``-style value into a timezone-aware UTC
    ``datetime`` - deliberately the full instant, not yet truncated to a
    calendar date (see :func:`wta_daily.reporting_day.reporting_date_for_completion`
    for why the exact instant matters, not just its own UTC calendar date).

    Confirmed empirically: finished matches report this in UTC
    (``+00:00``/``Z``), but not-yet-played matches in the *same* feed can
    report it in tournament LOCAL time with an explicit offset instead
    (e.g. Cincinnati's ``-04:00``). Always normalizing to UTC here avoids
    a day-bucketing bug from that inconsistency - see the module
    docstring's "day-first fix" section. A naive (no offset at all)
    timestamp is assumed to already represent UTC, consistent with this
    API's own convention for finished matches.
    """

    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(str(raw))
    except ValueError:
        logger.info("Unparsable timestamp %r", raw)
        return None
    if parsed.tzinfo is not None:
        return parsed.astimezone(UTC)
    return parsed.replace(tzinfo=UTC)


def _has_real_score(match: dict[str, Any]) -> bool:
    """True if a match actually has games recorded.

    Byes have no opponent and no score. Walkovers/defaults have an
    opponent but no score (the match was never actually played). Both
    look identical to "no genuine completed match happened here" for our
    purposes, so a single "is there a non-blank score" check covers both -
    see the module docstring's linked investigation for confirmation from
    real API responses.
    """

    return bool(str(match.get("scores", "")).strip())


@matches_registry.register("wta_official")
class WtaOfficialMatchProvider(MatchProvider):
    """Fetches each player's most recent completed singles match."""

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        lookback_matches: int = 25,
        catalogue_scan_pages: int = 25,
        network: NetworkConfig | None = None,
        tournament_status_enabled: bool = True,
        tournament_status_previous_year_lookback_enabled: bool = True,
        tournament_status_points_table_path: str = str(DEFAULT_POINTS_TABLE_PATH),
        reporting_day_cutoff_hour: int = DEFAULT_CUTOFF_HOUR,
        tournament_timezones_path: str = str(DEFAULT_TOURNAMENT_TIMEZONES_PATH),
        **_ignored: object,
    ) -> None:
        self._client = WtaOfficialApiClient(base_url=base_url, network=network)
        self._lookback_matches = lookback_matches
        # How many pages (x100 entries) from the *end* of the ~19,000-entry
        # tournament catalogue to scan for "active on this date" - the
        # catalogue is roughly chronological, so the current season's events
        # are near the end. 25 pages (~2,500 entries) comfortably covers
        # every concurrent tour/level for the current season with margin to
        # spare, while avoiding a ~190-page full scan on every run.
        self._catalogue_scan_pages = catalogue_scan_pages
        # Per-run cache: several Top N players are often in the same recent
        # tournament, so this avoids re-fetching that tournament's full
        # match list once per player.
        self._tournament_matches_cache: dict[tuple[str, str], list[dict[str, Any]]] = {}

        # "Reporting day" cutoff (see wta_daily/reporting_day.py) - a
        # match completing before this LOCAL hour is still attributed to
        # the *previous* calendar day, exactly like a late-night
        # broadcast is counted as part of the previous night's schedule.
        # This is what fixes the August 2026 production incident (a
        # match finishing shortly after midnight Eastern was excluded
        # from the following morning's report because its UTC-normalized
        # completion timestamp had already rolled onto the next calendar
        # day). Loading the timezone data never fails match detection
        # outright - on any load error, every match simply falls back to
        # the UTC-only approximation (tz=None) for the rest of this run,
        # never a hard failure of this core feature.
        self._reporting_cutoff_hour = reporting_day_cutoff_hour
        self._timezones: TournamentTimezones | None = None
        try:
            self._timezones = load_tournament_timezones(tournament_timezones_path)
        except Exception as exc:  # noqa: BLE001 - never let this break match detection
            logger.warning(
                "Could not load tournament timezone data from %s (%s); the reporting-day cutoff "
                "will use each match's UTC completion time as an approximation for this run.",
                tournament_timezones_path,
                exc,
            )

        # See wta_daily.config.TournamentStatusConfig - wired in from there
        # by wta_daily/pipeline.py's provider construction, but exposed as
        # plain constructor kwargs (like every other option here) so a
        # config.yaml `match_provider.options` block can also set them
        # directly if this provider is used standalone rather than
        # through `best_of`.
        self._tournament_status_enabled = tournament_status_enabled
        self._previous_year_lookback_enabled = tournament_status_previous_year_lookback_enabled
        self._points_table: PointsTable | None = None
        if tournament_status_enabled:
            try:
                self._points_table = load_points_table(tournament_status_points_table_path)
            except Exception as exc:  # noqa: BLE001 - points context is optional, never fatal
                logger.warning(
                    "Could not load the ranking-points table from %s (%s); tournament-status "
                    "narration will omit points_earned/previous_year_points for this run.",
                    tournament_status_points_table_path,
                    exc,
                )

    def get_latest_match(self, player: PlayerRanking) -> MatchResult | None:
        try:
            raw_matches = self._client.get_player_matches(
                player.player_id, page_size=self._lookback_matches
            )
        except Exception as exc:  # noqa: BLE001 - normalize every failure mode
            raise PlayerDataError(
                f"Could not retrieve matches for {player.name} ({player.player_id}): {exc}"
            ) from exc

        # Deliberately preserve the API's own sort=desc ordering rather than
        # re-sorting by the per-entry "date" field, which is the tournament's
        # start date repeated for every round and does not reflect real
        # match-to-match chronology within a tournament. See module docstring.
        for match in raw_matches:
            if match.get("s_d_flag") != _SINGLES:
                continue  # doubles
            if not _has_real_score(match):
                continue  # bye, walkover/default, or not actually played
            result = self._build_match_result(match, player)
            if result is not None:
                return result
        return None

    def get_matches_for_date(
        self, players: Sequence[PlayerRanking], target_date: date
    ) -> MatchLookupResult:
        """Day-first lookup: which of ``players`` have a confirmed finished
        singles match on ``target_date``, read directly from the
        tournament-level feed - see the module docstring for why this exists
        and how it differs from (and fixes) the per-player approach.

        A player absent from ``matches`` *and* absent from
        ``unresolved_player_ids`` is a positive, confident "did not play
        that day" - every currently active tournament's full match list was
        read and she wasn't in it. A player only ends up in
        ``unresolved_player_ids`` if fetching at least one active
        tournament's match list failed outright (so we genuinely can't rule
        her out - she might be exactly the player whose match was in the
        tournament we couldn't read), which is the one case where a
        composite provider should still try another source for her. This
        distinction is what lets ``BestOfMatchProvider`` skip its (often
        paid) fallback sources entirely on a normal day, when this method
        alone can already speak confidently for every tracked player.
        """

        try:
            active = self._find_active_tournaments(target_date)
        except Exception as exc:  # noqa: BLE001 - a total failure here must be surfaced, not silently "no one played"
            raise DataProviderError(
                f"Could not determine which tournaments were active on {target_date}: {exc}"
            ) from exc

        player_ids = {p.player_id for p in players}
        results: dict[str, MatchResult] = {}
        tournament_status: dict[str, TournamentRunStatus] = {}
        # (group_id, year, draw_size) per player whose status was resolved
        # this run - needed later for the previous-year lookup, which
        # can't be derived from TournamentRunStatus alone (it deliberately
        # doesn't carry a raw `year`/`draw_size`, since those are lookup
        # plumbing, not narration-facing facts).
        status_context: dict[str, tuple[Any, Any, int | None]] = {}
        any_tournament_fetch_failed = False

        for tournament in active:
            try:
                fixtures = self._get_tournament_matches(tournament.group_id, tournament.year)
            except Exception as exc:  # noqa: BLE001 - one tournament's data failing shouldn't sink the others
                logger.warning(
                    "Could not fetch matches for tournament %s/%s while checking %s: %s",
                    tournament.group_id,
                    tournament.year,
                    target_date,
                    exc,
                )
                any_tournament_fetch_failed = True
                continue

            # Resolved once per tournament (not per fixture) - every
            # fixture in the same tournament shares the same location, so
            # there's nothing to gain from re-resolving it repeatedly.
            # `None` (no recognized country/state) is a safe, documented
            # fallback - see TournamentTimezones.resolve's docstring.
            tz = self._timezones.resolve(tournament.country) if self._timezones else None

            for fixture in fixtures:
                if fixture.get("DrawMatchType") != _SINGLES:
                    continue
                if fixture.get("MatchState") != _FINISHED_MATCH_STATE:
                    continue
                fixture_date = self._reporting_date(fixture.get("MatchTimeStamp"), tz)
                if fixture_date != target_date:
                    continue

                player_a, player_b = str(fixture.get("PlayerIDA", "")), str(fixture.get("PlayerIDB", ""))
                for player_id, slot in ((player_a, "A"), (player_b, "B")):
                    if player_id in player_ids and player_id not in results:
                        result = self._build_match_result_from_fixture(fixture, slot, tournament.name, tz)
                        if result is not None:
                            results[player_id] = result

            if self._tournament_status_enabled:
                for player_id in player_ids:
                    if player_id in tournament_status:
                        continue  # already resolved from another active tournament
                    status = determine_tournament_run_status(
                        fixtures,
                        player_id,
                        tournament_name=tournament.name,
                        tournament_group_id=tournament.group_id,
                        category=tournament.level,
                        draw_size=tournament.draw_size,
                    )
                    if status.state != TournamentState.DID_NOT_PARTICIPATE:
                        tournament_status[player_id] = status
                        status_context[player_id] = (
                            tournament.group_id,
                            tournament.year,
                            tournament.draw_size,
                        )

        if self._tournament_status_enabled:
            for player_id in player_ids:
                tournament_status.setdefault(
                    player_id, TournamentRunStatus(state=TournamentState.DID_NOT_PARTICIPATE)
                )
            for player_id, status in list(tournament_status.items()):
                if status.state in (TournamentState.ELIMINATED, TournamentState.CHAMPION):
                    group_id, year, draw_size = status_context[player_id]
                    tournament_status[player_id] = self._enrich_tournament_status(
                        status, player_id, group_id, year, draw_size
                    )

        # Only players still unaccounted for are genuinely ambiguous, and
        # only if some tournament's data was actually unreadable - if every
        # active tournament was read successfully, an absent player is a
        # confirmed negative, not a gap.
        unresolved: frozenset[str] = (
            frozenset(pid for pid in player_ids if pid not in results)
            if any_tournament_fetch_failed
            else frozenset()
        )
        return MatchLookupResult(
            matches=results, unresolved_player_ids=unresolved, tournament_status=tournament_status
        )

    def _enrich_tournament_status(
        self,
        status: TournamentRunStatus,
        player_id: str,
        group_id: Any,
        year: Any,
        draw_size: int | None,
    ) -> TournamentRunStatus:
        """Add ranking points (and, when possible/enabled, a previous-year
        comparison) to an ELIMINATED/CHAMPION status - never called for
        ACTIVE/DID_NOT_PARTICIPATE, which have no round reached to price.

        Every enrichment step degrades independently and silently: a
        missing points-table entry simply leaves ``points_earned`` (or
        ``previous_year_points``/``points_delta``) unset rather than
        raising, and a previous-year lookup failure (network error,
        tournament didn't exist that year, API shape change) is logged
        and likewise just omitted - see the README's "Tournament
        elimination context" section for the full graceful-degradation
        hierarchy this supports.
        """

        points_earned = (
            self._points_table.lookup(status.category, status.round_reached, draw_size=draw_size)
            if self._points_table
            else None
        )
        enriched = dataclasses.replace(status, points_earned=points_earned)

        if not self._previous_year_lookback_enabled:
            return enriched

        previous_year = int(year) - 1
        try:
            previous_fixtures = self._get_tournament_matches(group_id, previous_year)
        except Exception as exc:  # noqa: BLE001 - the historical callback is optional, never fatal
            logger.info(
                "Could not look up %s's previous-year (%s) result at %s: %s",
                player_id,
                previous_year,
                status.tournament,
                exc,
            )
            return enriched

        # The previous year's edition can (rarely) have had a different
        # draw size than this year's - RoundID normalization is
        # draw-size-relative, so this year's draw_size must never be
        # reused to interpret last year's RoundIDs/points. Falls back to
        # None (the same safe "unknown draw size" default used elsewhere)
        # if that edition's own catalogue entry can't be located, rather
        # than guessing with the wrong year's size.
        previous_edition = self._find_tournament_catalogue_entry(group_id, previous_year)
        previous_draw_size = previous_edition.draw_size if previous_edition else None

        previous_status = determine_tournament_run_status(
            previous_fixtures,
            player_id,
            tournament_name=status.tournament or "",
            tournament_group_id=group_id,
            category=status.category,
            draw_size=previous_draw_size,
        )
        if previous_status.state not in (TournamentState.ELIMINATED, TournamentState.CHAMPION):
            # DID_NOT_PARTICIPATE (never played it last year), or ACTIVE
            # (shouldn't happen for a past year, but never guess if seen) -
            # omit the callback rather than invent one. See the module
            # docstring's "never invent a previous-year result" rule.
            return enriched

        previous_points = (
            self._points_table.lookup(
                previous_status.category, previous_status.round_reached, draw_size=previous_draw_size
            )
            if self._points_table
            else None
        )
        delta = (
            enriched.points_earned - previous_points
            if enriched.points_earned is not None and previous_points is not None
            else None
        )
        return dataclasses.replace(
            enriched,
            previous_year_round=previous_status.round_reached,
            previous_year_round_label=previous_status.round_label,
            previous_year_points=previous_points,
            points_delta=delta,
        )

    def _find_active_tournaments(self, target_date: date) -> list[_ActiveTournament]:
        """Tournaments whose date range covers ``target_date``.

        There's no working date filter on the catalogue endpoint (confirmed
        by testing), so this scans the last ``catalogue_scan_pages`` pages -
        the catalogue is roughly chronological from 1960 onward, so the
        current season sits near the end. See ``__init__`` for the tradeoff.
        The tournament *name* is carried from this catalogue entry because
        (perhaps surprisingly) the tournament-matches endpoint's individual
        fixture records don't include it themselves. ``level`` (category,
        e.g. "WTA 1000"), ``draw_size``, and ``country`` are carried the
        same way, purely for the tournament-status/points-table lookups
        and the reporting-day timezone resolution (see
        :mod:`wta_daily.tournament_timezones`) below - they're already
        present on this same catalogue entry, so capturing them costs
        nothing extra.
        """

        first_page = self._client.list_tournaments_page(page=0, page_size=100)
        total_entries = int(first_page.get("pageInfo", {}).get("numEntries", 0) or 0)
        last_page = max(0, (total_entries - 1) // 100) if total_entries else 0
        start_page = max(0, last_page - self._catalogue_scan_pages + 1)

        active: list[_ActiveTournament] = []
        for page in range(start_page, last_page + 1):
            data = self._client.list_tournaments_page(page=page, page_size=100)
            for entry in data.get("content", []):
                level = str(entry.get("level", "")).upper()
                if level not in _RELEVANT_TOUR_LEVELS:
                    continue
                try:
                    start = date.fromisoformat(entry["startDate"])
                    end = date.fromisoformat(entry["endDate"])
                except (KeyError, ValueError, TypeError):
                    continue
                if start <= target_date <= end:
                    group = entry.get("tournamentGroup") or {}
                    group_id, year = group.get("id"), entry.get("year")
                    if group_id is not None and year is not None:
                        draw_size = entry.get("singlesDrawSize")
                        active.append(
                            _ActiveTournament(
                                group_id=group_id,
                                year=year,
                                name=str(group.get("name", "Unknown Tournament")),
                                level=level,
                                draw_size=int(draw_size) if draw_size else None,
                                country=entry.get("country") or None,
                            )
                        )
        return active

    def _find_tournament_catalogue_entry(
        self, group_id: Any, year: Any
    ) -> _ActiveTournament | None:
        """Locate one specific tournament edition's own catalogue entry -
        used only to get *that edition's own* ``level``/``draw_size`` for
        the previous-year comparison (see ``_enrich_tournament_status``).

        This matters because :func:`wta_daily.rounds.normalize_wta_round_id`
        is draw-size-relative: a tournament's draw size can (rarely) differ
        between editions, so interpreting a previous year's ``RoundID``
        with *this* year's draw size would be wrong. Draw size changing
        year to year is uncommon enough not to warrant a bigger redesign -
        this is a small, targeted lookup, not a general "look up any
        tournament edition" feature.

        Scans backward from the end of the catalogue exactly like
        :meth:`_find_active_tournaments`, matched by ``(group_id, year)``
        instead of a date range, bounded to twice the normal scan window
        (the catalogue is roughly chronological, so one prior year's
        edition of the same tournament is only a small, bounded number of
        pages further back than "this season" - never the whole
        ~19,000-entry catalogue). Pages already fetched this run by
        ``_find_active_tournaments`` are served from
        ``WtaOfficialApiClient``'s own per-page cache, so this typically
        costs few or zero *additional* HTTP requests. Returns ``None``
        (never a guess) if the edition isn't found within that window -
        callers fall back to ``draw_size=None`` (the same safe default
        already used whenever a draw size is simply unknown).
        """

        first_page = self._client.list_tournaments_page(page=0, page_size=100)
        total_entries = int(first_page.get("pageInfo", {}).get("numEntries", 0) or 0)
        last_page = max(0, (total_entries - 1) // 100) if total_entries else 0
        scan_pages = self._catalogue_scan_pages * 2
        start_page = max(0, last_page - scan_pages + 1)

        target_group_id = str(group_id)
        target_year = str(year)
        for page in range(last_page, start_page - 1, -1):
            data = self._client.list_tournaments_page(page=page, page_size=100)
            for entry in data.get("content", []):
                group = entry.get("tournamentGroup") or {}
                if str(group.get("id")) != target_group_id or str(entry.get("year")) != target_year:
                    continue
                level = str(entry.get("level", "")).upper()
                draw_size = entry.get("singlesDrawSize")
                return _ActiveTournament(
                    group_id=group.get("id"),
                    year=entry.get("year"),
                    name=str(group.get("name", "Unknown Tournament")),
                    level=level,
                    draw_size=int(draw_size) if draw_size else None,
                )
        return None

    def _reporting_date(self, raw_timestamp: Any, tz: ZoneInfo | None) -> date | None:
        """The "reporting day" (see :mod:`wta_daily.reporting_day`) a
        fixture's ``MatchTimeStamp`` should be attributed to - ``None``
        if the timestamp itself couldn't be parsed at all.

        This is the single choke point every date used for day-first
        match matching/attribution goes through, which is what
        guarantees :meth:`get_matches_for_date`'s equality comparison
        and :meth:`_build_match_result_from_fixture`'s ``match_date``
        are always computed identically for the same fixture - and,
        since it's a pure function of the timestamp/timezone alone,
        always produces the same result no matter which day's run asks
        (see the module docstring's production-incident section for why
        that determinism is what prevents a match from ever being
        reported on two different days).
        """

        parsed = _parse_utc_timestamp(raw_timestamp)
        if parsed is None:
            return None
        return reporting_date_for_completion(parsed, tz=tz, cutoff_hour=self._reporting_cutoff_hour)

    def _build_match_result_from_fixture(
        self, fixture: dict[str, Any], our_slot: str, tournament_name: str, tz: ZoneInfo | None
    ) -> MatchResult | None:
        winner_slot = {"2": "A", "3": "B"}.get(str(fixture.get("Winner")))
        if winner_slot is None:
            return None  # no derivable winner despite MatchState == "F"

        first_a = str(fixture.get("PlayerNameFirstA", "")).strip()
        last_a = str(fixture.get("PlayerNameLastA", "")).strip()
        first_b = str(fixture.get("PlayerNameFirstB", "")).strip()
        last_b = str(fixture.get("PlayerNameLastB", "")).strip()
        opponent_name = f"{first_b} {last_b}".strip() if our_slot == "A" else f"{first_a} {last_a}".strip()

        return MatchResult(
            opponent=opponent_name or "Unknown Opponent",
            tournament=_titleize_tournament(tournament_name),
            round=_fallback_round_label(fixture),
            score=_parse_score(str(fixture.get("ScoreString", ""))),
            won=(winner_slot == our_slot),
            match_date=self._reporting_date(fixture.get("MatchTimeStamp"), tz),
            surface=None,
        )

    def _build_match_result(
        self, match: dict[str, Any], player: PlayerRanking
    ) -> MatchResult | None:
        player_1 = str(match.get("player_1", ""))
        player_2 = str(match.get("player_2", ""))
        winner_slot = match.get("winner")

        if player.player_id == player_1:
            opponent_info = match.get("opponent") or {}
            won = winner_slot == 1
        elif player.player_id == player_2:
            # The API's "opponent" field is always relative to player_1, so when
            # our player is player_2 we don't get their opponent's name for free.
            opponent_info = {}
            won = winner_slot == 2
        else:
            logger.warning(
                "Match for %s did not reference the expected player id; skipping.", player.name
            )
            return None

        opponent_name = opponent_info.get("fullName") if opponent_info else None
        if not opponent_name:
            team_key = "team_name_2" if player.player_id == player_1 else "team_name_1"
            opponent_name = str(match.get(team_key, "Unknown Opponent")).strip() or "Unknown Opponent"

        tournament = _titleize_tournament(str(match.get("TournamentName", "Unknown Tournament")))
        round_code = str(match.get("round_name", ""))

        match_date = self._resolve_match_date(match, player, opponent_info.get("id"))

        return MatchResult(
            opponent=opponent_name,
            tournament=tournament,
            round=_friendly_round(round_code),
            score=_parse_score(str(match.get("scores", ""))),
            won=bool(won),
            match_date=match_date,
            surface=(str(match.get("Surface")).title() if match.get("Surface") else None),
        )

    def _resolve_match_date(
        self, match: dict[str, Any], player: PlayerRanking, opponent_id: Any
    ) -> date | None:
        """Look up the real, match-level date via the tournament-matches feed.

        Returns ``None`` (never a tournament start date) whenever the real
        date can't be confirmed - see the module docstring for why.
        """

        tournament_info = match.get("tournament") or {}
        group = tournament_info.get("tournamentGroup") or {}
        group_id = group.get("id")
        year = tournament_info.get("year")
        if group_id is None or year is None or opponent_id is None:
            return None

        try:
            fixtures = self._get_tournament_matches(group_id, year)
        except Exception as exc:  # noqa: BLE001 - date enrichment must never fail the run
            logger.info(
                "Could not confirm match date for %s from tournament %s/%s: %s",
                player.name,
                group_id,
                year,
                exc,
            )
            return None

        target_ids = {str(player.player_id), str(opponent_id)}
        for fixture in fixtures:
            if fixture.get("DrawMatchType") != _SINGLES:
                continue
            fixture_ids = {str(fixture.get("PlayerIDA", "")), str(fixture.get("PlayerIDB", ""))}
            if fixture_ids != target_ids:
                continue
            if fixture.get("MatchState") != _FINISHED_MATCH_STATE:
                # We found the fixture, but the tournament feed doesn't
                # consider it finished - don't trust its outcome/date.
                logger.info(
                    "Tournament feed marks %s's match against %s as not finished "
                    "(MatchState=%r); treating date as unconfirmed.",
                    player.name,
                    opponent_id,
                    fixture.get("MatchState"),
                )
                return None
            # No tournament-country context is available here without an
            # extra catalogue lookup (this method only has group_id/year,
            # not the catalogue entry itself) - falls back to the
            # UTC-only reporting-day approximation rather than spending
            # an additional API call just for this legacy per-player
            # fallback path (see the module docstring's "API-call
            # impact" guarantees; the primary day-first path above does
            # have tournament-local timezone resolution, at zero extra
            # cost, since it already scans the catalogue).
            return self._reporting_date(fixture.get("MatchTimeStamp"), tz=None)

        logger.info(
            "Could not find a matching fixture in tournament %s/%s for %s vs opponent %s; "
            "reporting the result without a confirmed date.",
            group_id,
            year,
            player.name,
            opponent_id,
        )
        return None

    def _get_tournament_matches(self, group_id: Any, year: Any) -> list[dict[str, Any]]:
        cache_key = (str(group_id), str(year))
        if cache_key not in self._tournament_matches_cache:
            self._tournament_matches_cache[cache_key] = self._client.get_tournament_matches(
                group_id, year
            )
        return self._tournament_matches_cache[cache_key]
