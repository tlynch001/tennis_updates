"""Match provider backed by the paid `livetennisapi.com <https://livetennisapi.com>`_ API.

See :mod:`wta_daily.plugins.live_tennis_api_client` for why this provider
exists: it's a paid alternative to ``wta_official`` chosen specifically to
address that provider's documented staleness (results can lag real-world
play by more than a week during/right after a tournament on the free WTA
feed). This provider's completed-match records carry a genuine per-match
``scheduled_time`` and an explicit ``event_status`` for
retirements/walkovers/cancellations, so - unlike the original
tournament-start-date bug this project shipped with - there is no date
ambiguity to work around here in the first place.

Player identity is **not** shared with ``api.wtatennis.com``; this service
uses its own numeric player ids. Each :class:`~wta_daily.models.PlayerRanking`
passed in here is resolved to a local id via ``GET /players?search=<name>``,
filtering out doubles teams and unranked namesakes (see
:func:`_pick_best_player_match`). That resolution is the one part of this
provider that can genuinely fail to identify the right person (an unusual
name spelling, a very common name, etc.) - when it does, :class:`PlayerDataError`
is raised so the pipeline's per-player isolation logs it and moves on,
exactly like any other match-lookup failure.

**This provider has its own coverage gaps and should not be trusted alone.**
Verified live against the real August 2026 Top 10 (see PR history): 9 of 10
players resolved to results that exactly matched ``wta_official``'s
independently-verified dates - but one player's record here stopped in
March 2026, silently missing 4+ months (including a Wimbledon final and a
Toronto result that ``wta_official`` had). No error is raised in that case;
it is simply an incomplete data set for that specific person in this
vendor's system. This is *exactly* why :class:`~wta_daily.plugins.matches.best_of.BestOfMatchProvider`
exists - combining this provider with ``wta_official`` and always preferring
whichever source has the more recently-confirmed date is far more reliable
than trusting either alone. See ``config.example.yaml``'s ``best_of``
example.
"""

from __future__ import annotations

import logging
import os
from datetime import date, datetime
from typing import Any

from wta_daily.config import NetworkConfig
from wta_daily.exceptions import PlayerDataError
from wta_daily.models import MatchResult, PlayerRanking
from wta_daily.plugins.base import MatchProvider
from wta_daily.plugins.live_tennis_api_client import DEFAULT_BASE_URL, LiveTennisApiClient
from wta_daily.plugins.registry import matches_registry

logger = logging.getLogger(__name__)

_ROUND_NAMES: dict[str, str] = {
    "R128": "Round of 128",
    "R64": "Round of 64",
    "R32": "Round of 32",
    "R16": "Round of 16",
    "QF": "Quarterfinal",
    "SF": "Semifinal",
    "F": "Final",
    "RR": "Round Robin",
    "BR": "Bronze Medal Match",
    "Q": "Qualifying",
    "Q1": "1st Round Qualifying",
    "Q2": "2nd Round Qualifying",
    "Q3": "3rd Round Qualifying",
    "Q4": "4th Round Qualifying",
    "ER": "Early Round",
}

#: event_status values meaning "no real tennis was actually played" - these
#: are excluded from "latest completed match" the same way byes/walkovers
#: were excluded for wta_official. Confirmed empirically: normal completed
#: matches report "Finished" here (not null, despite what the endpoint's
#: sibling schema for live matches suggests). "Retired" is deliberately NOT
#: excluded: a retirement still has a real, partial score and a real winner.
_NON_MATCH_EVENT_STATUSES = {"Walk Over", "Cancelled", "Postponed"}


def _friendly_round(round_code: str | None, fallback_label: str | None) -> str:
    if round_code and round_code in _ROUND_NAMES:
        return _ROUND_NAMES[round_code]
    return fallback_label or (round_code or "Unknown Round")


def _format_score(games: list[list[int]] | None, our_slot: int) -> str:
    """Build a "our games-opponent games" string per set from the API's
    player-major ``[[p1_set1, p1_set2, ...], [p2_set1, p2_set2, ...]]`` shape.

    This provider's list endpoints don't expose tiebreak sub-scores (only
    the ``/history/matches/{matchId}`` per-match tape does, at the cost of
    one extra request per match), so scores here are plain set tallies
    (e.g. "6-7 6-4 4-6") without a "(3)"-style tiebreak point count.
    """

    if not games or len(games) != 2:
        return ""
    p1_games, p2_games = games
    our_games, opponent_games = (p1_games, p2_games) if our_slot == 1 else (p2_games, p1_games)
    sets = [f"{our}-{opp}" for our, opp in zip(our_games, opponent_games, strict=False)]
    return " ".join(sets)


def _pick_best_player_match(candidates: list[dict[str, Any]], target_name: str) -> dict[str, Any] | None:
    """Resolve a search-by-name result list to the one real singles player.

    ``GET /players`` can return doubles teams (e.g. "Marozava / Sabalenka")
    and unranked namesake noise entries alongside the actual player, so an
    exact-name, non-doubles, ranked match is strongly preferred - see the
    module docstring.
    """

    singles_candidates = [c for c in candidates if not c.get("is_doubles_team")]
    if not singles_candidates:
        return None

    target_lower = target_name.strip().lower()
    exact_matches = [c for c in singles_candidates if str(c.get("name", "")).strip().lower() == target_lower]
    pool = exact_matches or singles_candidates

    ranked = [c for c in pool if c.get("ranking") is not None]
    if ranked:
        return ranked[0]
    return pool[0]


@matches_registry.register("live_tennis_api")
class LiveTennisApiMatchProvider(MatchProvider):
    """Fetches each player's most recent completed singles match from livetennisapi.com."""

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        lookback_matches: int = 20,
        api_key_env: str = "LIVETENNISAPI_KEY",
        network: NetworkConfig | None = None,
        **_ignored: object,
    ) -> None:
        api_key = os.environ.get(api_key_env)
        self._client = LiveTennisApiClient(api_key=api_key, base_url=base_url, network=network)
        self._lookback_matches = lookback_matches
        # Per-run cache: a name only ever needs to be resolved to an id once.
        self._player_id_cache: dict[str, int | None] = {}

    def get_latest_match(self, player: PlayerRanking) -> MatchResult | None:
        try:
            player_id = self._resolve_player_id(player.name)
        except Exception as exc:  # noqa: BLE001 - normalize every failure mode
            raise PlayerDataError(
                f"Could not resolve {player.name!r} to a livetennisapi.com player id: {exc}"
            ) from exc
        if player_id is None:
            raise PlayerDataError(
                f"No unambiguous livetennisapi.com player match found for {player.name!r}."
            )

        try:
            raw_matches = self._client.get_completed_matches(
                player_id, limit=self._lookback_matches
            )
        except Exception as exc:  # noqa: BLE001
            raise PlayerDataError(
                f"Could not retrieve match history for {player.name} (livetennisapi id "
                f"{player_id}): {exc}"
            ) from exc

        for match in raw_matches:
            if match.get("is_doubles"):
                continue
            if match.get("status") != "completed":
                continue
            if match.get("event_status") in _NON_MATCH_EVENT_STATUSES:
                continue
            result = self._build_match_result(match, player_id, player)
            if result is not None:
                return result
        return None

    def _resolve_player_id(self, name: str) -> int | None:
        if name not in self._player_id_cache:
            candidates = self._client.search_players(name)
            best = _pick_best_player_match(candidates, name)
            self._player_id_cache[name] = best.get("id") if best else None
        return self._player_id_cache[name]

    @staticmethod
    def _build_match_result(
        match: dict[str, Any], player_id: int, player: PlayerRanking
    ) -> MatchResult | None:
        players = match.get("players") or {}
        p1 = players.get("p1") or {}
        p2 = players.get("p2") or {}

        if p1.get("id") == player_id:
            our_slot, opponent = 1, p2
        elif p2.get("id") == player_id:
            our_slot, opponent = 2, p1
        else:
            logger.warning(
                "Match did not reference the resolved player id %s for %s; skipping.",
                player_id,
                player.name,
            )
            return None

        winner_slot = match.get("winner")
        if winner_slot not in (1, 2):
            # No derivable winner (e.g. a cancelled/void match that still
            # slipped through the status/event_status filters upstream).
            return None

        score = match.get("score") or {}
        match_date = _parse_match_date(match.get("scheduled_time"))

        return MatchResult(
            opponent=str(opponent.get("name") or "Unknown Opponent"),
            tournament=str(match.get("tournament") or "Unknown Tournament"),
            round=_friendly_round(match.get("round_code"), match.get("round")),
            score=_format_score(score.get("games"), our_slot),
            won=(winner_slot == our_slot),
            match_date=match_date,
            surface=(str(match.get("surface")).title() if match.get("surface") else None),
        )


def _parse_match_date(scheduled_time: Any) -> date | None:
    """``scheduled_time`` is the field this API's own docs use for its
    completed-match date-range filters ("Earliest/latest play date"), so its
    date component is treated as the authoritative match date here - unlike
    ``wta_official``'s bug, there is no separate "tournament start date"
    masquerading as a match date in this API to begin with.
    """

    if not scheduled_time:
        return None
    try:
        return datetime.fromisoformat(str(scheduled_time).replace("Z", "+00:00")).date()
    except ValueError:
        logger.info("Unparsable scheduled_time %r", scheduled_time)
        return None
