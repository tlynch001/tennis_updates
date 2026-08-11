"""Match provider backed by the official WTA JSON backend.

See :mod:`wta_daily.plugins.wta_api_client` for the rationale behind choosing
this data source.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any

from wta_daily.config import NetworkConfig
from wta_daily.exceptions import PlayerDataError
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


def _friendly_round(code: str) -> str:
    return _ROUND_NAMES.get(code, code)


def _parse_score(raw: str) -> str:
    return " ".join(raw.split())


_TOURNAMENT_NAME_OVERRIDES = {"Dc": "DC", "Us": "US", "Uae": "UAE"}


def _titleize_tournament(raw: str) -> str:
    words = raw.title().split()
    return " ".join(_TOURNAMENT_NAME_OVERRIDES.get(word, word) for word in words)


@matches_registry.register("wta_official")
class WtaOfficialMatchProvider(MatchProvider):
    """Fetches each player's most recent completed singles match."""

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        lookback_matches: int = 25,
        network: NetworkConfig | None = None,
        **_ignored: object,
    ) -> None:
        self._client = WtaOfficialApiClient(base_url=base_url, network=network)
        self._lookback_matches = lookback_matches

    def get_latest_match(self, player: PlayerRanking) -> MatchResult | None:
        try:
            raw_matches = self._client.get_player_matches(
                player.player_id, page_size=self._lookback_matches
            )
        except Exception as exc:  # noqa: BLE001 - normalize every failure mode
            raise PlayerDataError(
                f"Could not retrieve matches for {player.name} ({player.player_id}): {exc}"
            ) from exc

        singles = [m for m in raw_matches if m.get("s_d_flag") == "S"]
        singles.sort(key=lambda m: m.get("StartDate", ""), reverse=True)

        today = date.today()
        for match in singles:
            result = self._to_match_result(match, player, today)
            if result is not None:
                return result
        return None

    @staticmethod
    def _to_match_result(
        match: dict[str, Any], player: PlayerRanking, today: date
    ) -> MatchResult | None:
        try:
            match_date = datetime.fromisoformat(match["StartDate"]).date()
        except (KeyError, ValueError) as exc:
            logger.warning("Skipping match with unparsable date for %s: %s", player.name, exc)
            return None
        if match_date > today:
            return None  # not yet played

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

        return MatchResult(
            opponent=opponent_name,
            tournament=tournament,
            round=_friendly_round(round_code),
            score=_parse_score(str(match.get("scores", ""))),
            won=bool(won),
            match_date=match_date,
            surface=(str(match.get("Surface")).title() if match.get("Surface") else None),
        )
