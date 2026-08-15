"""Match provider backed by the paid `api-tennis.com <https://api-tennis.com>`_ API.

Evaluated as a third match-data source alongside ``wta_official`` and
`livetennisapi.com` (:mod:`wta_daily.plugins.matches.live_tennis_api`), at
the user's request, using a temporary trial API key. Summary of the live
comparison against the current WTA Top 10 (same players, same day):

* **Rankings** (``get_standings``) matched ``api.wtatennis.com`` exactly -
  same order, same point totals, for every one of the current Top 10.
* **Match coverage was noticeably better than `livetennisapi.com`.** The one
  player whose record there had a real 4+ month gap (missing a Wimbledon
  final) had complete data here, correctly showing that same Wimbledon
  final as her latest result - matching ``wta_official``'s independently
  confirmed date exactly.
* **A minority of dates were off by exactly one calendar day** compared to
  the same matches' dates independently confirmed via ``wta_official`` and
  `livetennisapi.com` (4 of 10 players' latest results, all showing one day
  *later* than the confirmed date - a plausible timezone-rollover artifact
  in how this vendor buckets match dates, not a random error). This is real,
  but minor compared to the tournament-start-date bug this project shipped
  with or `livetennisapi.com`'s multi-month coverage gap.

Net effect for :class:`~wta_daily.plugins.matches.best_of.BestOfMatchProvider`:
because that provider prefers whichever source's date is *most recent*, this
one-day-late quirk means this source's (slightly wrong) date can occasionally
outrank a same-event, more-accurate date from another source. This is called
out explicitly rather than papered over - see the README's "Match-data
reliability" section for the full tradeoff discussion.

Player identity is **not** shared with the other two sources; this service
has its own numeric ``player_key`` space. Unlike `livetennisapi.com`
(fuzzy name search), ``get_standings`` conveniently returns every ranked
player's exact name *and* key in one call, so player resolution here is a
direct dictionary lookup built from one cached call rather than a
per-player fuzzy search - see :meth:`ApiTennisMatchProvider._name_key_map`.
"""

from __future__ import annotations

import logging
import os
from datetime import date, timedelta
from typing import Any

from wta_daily.config import NetworkConfig
from wta_daily.exceptions import PlayerDataError
from wta_daily.models import MatchResult, PlayerRanking
from wta_daily.plugins.api_tennis_client import DEFAULT_BASE_URL, ApiTennisClient
from wta_daily.plugins.base import MatchProvider
from wta_daily.plugins.registry import matches_registry

logger = logging.getLogger(__name__)

#: This vendor's "fraction of the draw" round naming - see module docstring
#: for how these were decoded against the other two providers' round codes.
_ROUND_SUFFIX_MAP = {
    "1/128-finals": "Round of 256",
    "1/64-finals": "Round of 128",
    "1/32-finals": "Round of 64",
    "1/16-finals": "Round of 32",
    "1/8-finals": "Round of 16",
    "Quarter-finals": "Quarterfinal",
    "Semi-finals": "Semifinal",
    "Final": "Final",
}

#: A match this vendor considers to have produced a genuine result. Matches
#: not yet played show "" here (with a "-" event_final_result and a null
#: event_winner); walkovers/retirements still report "Finished" or
#: "Retired" respectively with a real winner.
_COMPLETED_EVENT_STATUSES = {"Finished", "Retired"}


def _friendly_round(tournament_round: str) -> str:
    suffix = tournament_round.rsplit(" - ", maxsplit=1)[-1].strip()
    return _ROUND_SUFFIX_MAP.get(suffix, suffix or "Unknown Round")


def _format_score(scores: list[dict[str, Any]], our_slot: str) -> str:
    """``our_slot`` is "first" or "second" - which side of ``score_first``/
    ``score_second`` is our player. Passed through largely as-is; this
    vendor encodes some tiebreak sub-scores unconventionally (e.g. a 7-6(3)
    set can appear as ``score_first: "6.3"``), which is not reverse-engineered
    here to avoid guessing wrong - see module docstring.
    """

    our_key, opp_key = f"score_{our_slot}", f"score_{'second' if our_slot == 'first' else 'first'}"
    sets = [f"{s.get(our_key, '?')}-{s.get(opp_key, '?')}" for s in scores]
    return " ".join(sets)


@matches_registry.register("api_tennis")
class ApiTennisMatchProvider(MatchProvider):
    """Fetches each player's most recent completed singles match from api-tennis.com."""

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        lookback_days: int = 45,
        api_key_env: str = "APITENNIS_KEY",
        network: NetworkConfig | None = None,
        **_ignored: object,
    ) -> None:
        api_key = os.environ.get(api_key_env)
        self._client = ApiTennisClient(api_key=api_key, base_url=base_url, network=network)
        self._lookback_days = lookback_days
        self._name_to_key: dict[str, int] | None = None

    def get_latest_match(self, player: PlayerRanking) -> MatchResult | None:
        try:
            player_key = self._resolve_player_key(player.name)
        except Exception as exc:  # noqa: BLE001 - normalize every failure mode
            raise PlayerDataError(
                f"Could not resolve {player.name!r} to an api-tennis.com player_key: {exc}"
            ) from exc
        if player_key is None:
            raise PlayerDataError(f"No api-tennis.com standings entry found for {player.name!r}.")

        today = date.today()
        try:
            fixtures = self._client.get_fixtures(
                player_key=player_key,
                date_start=(today - timedelta(days=self._lookback_days)).isoformat(),
                date_stop=today.isoformat(),
            )
        except Exception as exc:  # noqa: BLE001
            raise PlayerDataError(
                f"Could not retrieve fixtures for {player.name} (api-tennis.com player_key "
                f"{player_key}): {exc}"
            ) from exc

        singles_completed = [
            f
            for f in fixtures
            if "Singles" in str(f.get("event_type_type", ""))
            and f.get("event_status") in _COMPLETED_EVENT_STATUSES
        ]
        singles_completed.sort(key=lambda f: str(f.get("event_date", "")), reverse=True)

        for fixture in singles_completed:
            result = self._build_match_result(fixture, player_key, player)
            if result is not None:
                return result
        return None

    def _resolve_player_key(self, name: str) -> int | None:
        return self._name_key_map().get(name.strip().lower())

    def _name_key_map(self) -> dict[str, int]:
        if self._name_to_key is None:
            standings = self._client.get_standings(event_type="WTA")
            self._name_to_key = {
                str(row["player"]).strip().lower(): int(row["player_key"])
                for row in standings
                if row.get("player") and row.get("player_key") is not None
            }
        return self._name_to_key

    @staticmethod
    def _build_match_result(
        fixture: dict[str, Any], player_key: int, player: PlayerRanking
    ) -> MatchResult | None:
        first_key = fixture.get("first_player_key")
        second_key = fixture.get("second_player_key")

        if first_key == player_key:
            our_slot, opponent_label = "first", str(fixture.get("event_second_player") or "")
        elif second_key == player_key:
            our_slot, opponent_label = "second", str(fixture.get("event_first_player") or "")
        else:
            logger.warning(
                "Fixture did not reference the resolved player_key %s for %s; skipping.",
                player_key,
                player.name,
            )
            return None

        winner_label = fixture.get("event_winner")
        winner_slot = {"First Player": "first", "Second Player": "second"}.get(str(winner_label))
        if winner_slot is None:
            return None  # no derivable winner despite a "completed" status

        match_date = _parse_event_date(fixture.get("event_date"))

        return MatchResult(
            opponent=opponent_label.strip() or "Unknown Opponent",
            tournament=str(fixture.get("tournament_name") or "Unknown Tournament"),
            round=_friendly_round(str(fixture.get("tournament_round") or "")),
            score=_format_score(fixture.get("scores") or [], our_slot),
            won=(winner_slot == our_slot),
            match_date=match_date,
            surface=None,  # not provided by this endpoint
        )


def _parse_event_date(event_date: Any) -> date | None:
    if not event_date:
        return None
    try:
        return date.fromisoformat(str(event_date))
    except ValueError:
        logger.info("Unparsable event_date %r", event_date)
        return None
