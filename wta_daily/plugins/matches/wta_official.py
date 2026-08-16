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

import logging
from collections.abc import Sequence
from datetime import UTC, date, datetime
from typing import Any

from wta_daily.config import NetworkConfig
from wta_daily.exceptions import DataProviderError, PlayerDataError
from wta_daily.models import MatchResult, PlayerRanking
from wta_daily.plugins.base import MatchProvider
from wta_daily.plugins.registry import matches_registry
from wta_daily.plugins.wta_api_client import DEFAULT_BASE_URL, WtaOfficialApiClient

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


def _parse_timestamp(raw: Any) -> date | None:
    """Parse a ``MatchTimeStamp``-style value into a UTC calendar date.

    Confirmed empirically: finished matches report this in UTC
    (``+00:00``/``Z``), but not-yet-played matches in the *same* feed can
    report it in tournament LOCAL time with an explicit offset instead
    (e.g. Cincinnati's ``-04:00``). Always normalizing to UTC before taking
    the date avoids a day-bucketing bug from that inconsistency - see the
    module docstring's "day-first fix" section.
    """

    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(str(raw))
    except ValueError:
        logger.info("Unparsable timestamp %r", raw)
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(UTC)
    return parsed.date()


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
    ) -> dict[str, MatchResult]:
        """Day-first lookup: which of ``players`` have a confirmed finished
        singles match on ``target_date``, read directly from the
        tournament-level feed - see the module docstring for why this exists
        and how it differs from (and fixes) the per-player approach.
        """

        try:
            active = self._find_active_tournaments(target_date)
        except Exception as exc:  # noqa: BLE001 - a total failure here must be surfaced, not silently "no one played"
            raise DataProviderError(
                f"Could not determine which tournaments were active on {target_date}: {exc}"
            ) from exc

        player_ids = {p.player_id for p in players}
        results: dict[str, MatchResult] = {}
        for group_id, year, tournament_name in active:
            try:
                fixtures = self._get_tournament_matches(group_id, year)
            except Exception as exc:  # noqa: BLE001 - one tournament's data failing shouldn't sink the others
                logger.warning(
                    "Could not fetch matches for tournament %s/%s while checking %s: %s",
                    group_id,
                    year,
                    target_date,
                    exc,
                )
                continue

            for fixture in fixtures:
                if fixture.get("DrawMatchType") != _SINGLES:
                    continue
                if fixture.get("MatchState") != _FINISHED_MATCH_STATE:
                    continue
                fixture_date = _parse_timestamp(fixture.get("MatchTimeStamp"))
                if fixture_date != target_date:
                    continue

                player_a, player_b = str(fixture.get("PlayerIDA", "")), str(fixture.get("PlayerIDB", ""))
                for player_id, slot in ((player_a, "A"), (player_b, "B")):
                    if player_id in player_ids and player_id not in results:
                        result = self._build_match_result_from_fixture(fixture, slot, tournament_name)
                        if result is not None:
                            results[player_id] = result
        return results

    def _find_active_tournaments(self, target_date: date) -> list[tuple[Any, Any, str]]:
        """(groupId, year, tournamentName) triples whose date range covers ``target_date``.

        There's no working date filter on the catalogue endpoint (confirmed
        by testing), so this scans the last ``catalogue_scan_pages`` pages -
        the catalogue is roughly chronological from 1960 onward, so the
        current season sits near the end. See ``__init__`` for the tradeoff.
        The tournament *name* is carried from this catalogue entry because
        (perhaps surprisingly) the tournament-matches endpoint's individual
        fixture records don't include it themselves.
        """

        first_page = self._client.list_tournaments_page(page=0, page_size=100)
        total_entries = int(first_page.get("pageInfo", {}).get("numEntries", 0) or 0)
        last_page = max(0, (total_entries - 1) // 100) if total_entries else 0
        start_page = max(0, last_page - self._catalogue_scan_pages + 1)

        active: list[tuple[Any, Any, str]] = []
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
                        active.append((group_id, year, str(group.get("name", "Unknown Tournament"))))
        return active

    @staticmethod
    def _build_match_result_from_fixture(
        fixture: dict[str, Any], our_slot: str, tournament_name: str
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
            match_date=_parse_timestamp(fixture.get("MatchTimeStamp")),
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
            return _parse_timestamp(fixture.get("MatchTimeStamp"))

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
