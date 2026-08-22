"""ATP match provider backed by api-tennis.com ``get_fixtures``.

This is a **new ATP-only plugin**. It does not change the existing WTA
``api_tennis`` match provider (which still resolves identity by standings
name and hard-codes ``event_type="WTA"``).

ATP v1 is day-first and rankings-plus-completed-matches only:

* one ``get_fixtures`` call for the reporting date (plus a one-run cache)
* filter to completed ATP singles
* reconcile players by numeric ``player_key`` / ``PlayerRanking.player_id``
* never populate ``tournament_status``
* never fall back to WTA fixtures or fuzzy name matching
"""

from __future__ import annotations

import logging
import os
from collections.abc import Sequence
from datetime import date, timedelta
from typing import Any

from wta_daily.config import NetworkConfig
from wta_daily.exceptions import DataProviderError, PlayerDataError
from wta_daily.models import MatchLookupResult, MatchResult, PlayerRanking
from wta_daily.plugins.api_tennis_client import DEFAULT_BASE_URL, ApiTennisClient
from wta_daily.plugins.base import MatchProvider
from wta_daily.plugins.registry import matches_registry

logger = logging.getLogger(__name__)

#: Documented api-tennis ``event_type_key`` for Atp Singles.
ATP_SINGLES_EVENT_TYPE_KEY = 265

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

_COMPLETED_EVENT_STATUSES = {"Finished", "Retired"}
_WINNER_SLOT = {"First Player": "first", "Second Player": "second"}


def _friendly_round(tournament_round: str) -> str | None:
    text = (tournament_round or "").strip()
    if not text:
        return None
    suffix = text.rsplit(" - ", maxsplit=1)[-1].strip()
    if not suffix:
        return None
    return _ROUND_SUFFIX_MAP.get(suffix, suffix)


def _format_score(scores: object, our_slot: str) -> str:
    if not isinstance(scores, list) or not scores:
        raise ValueError("scores list is missing or empty")
    our_key = f"score_{our_slot}"
    opp_key = f"score_{'second' if our_slot == 'first' else 'first'}"
    sets: list[str] = []
    for item in scores:
        if not isinstance(item, dict):
            raise ValueError(f"score set is not an object: {item!r}")
        ours = item.get(our_key)
        opp = item.get(opp_key)
        if ours in (None, "") or opp in (None, ""):
            raise ValueError(f"incomplete set score: {item!r}")
        sets.append(f"{ours}-{opp}")
    if not sets:
        raise ValueError("no usable set scores")
    return " ".join(sets)


def _parse_event_date(event_date: Any) -> date | None:
    if not event_date:
        return None
    try:
        return date.fromisoformat(str(event_date))
    except ValueError:
        logger.info("Unparsable ATP event_date %r", event_date)
        return None


def _event_type_type(fixture: dict[str, Any]) -> str:
    return str(fixture.get("event_type_type") or "")


def _is_wta_fixture(fixture: dict[str, Any]) -> bool:
    token = _event_type_type(fixture).lower()
    return "wta" in token


def _is_atp_singles_fixture(fixture: dict[str, Any]) -> bool:
    if _is_wta_fixture(fixture):
        return False
    raw_key = fixture.get("event_type_key")
    try:
        if raw_key is not None and int(raw_key) == ATP_SINGLES_EVENT_TYPE_KEY:
            return True
    except (TypeError, ValueError):
        pass
    token = _event_type_type(fixture)
    return "Atp Singles" in token or token.lower() == "atp singles"


def _player_key_from_ranking(player: PlayerRanking) -> int | None:
    raw = str(player.player_id or "").strip()
    if not raw.isdigit():
        return None
    return int(raw)


def _int_key(raw: object) -> int | None:
    if raw is None or raw == "":
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


@matches_registry.register("api_tennis_atp")
class ApiTennisAtpMatchProvider(MatchProvider):
    """Completed ATP singles matches from api-tennis.com, matched by player_key."""

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        lookback_days: int = 45,
        api_key_env: str = "APITENNIS_KEY",
        timezone: str = "UTC",
        network: NetworkConfig | None = None,
        **_ignored: object,
    ) -> None:
        api_key = os.environ.get(api_key_env)
        self._client = ApiTennisClient(api_key=api_key, base_url=base_url, network=network)
        self._lookback_days = lookback_days
        self._timezone = timezone
        self._fixtures_by_date: dict[date, list[dict[str, Any]]] = {}

    def get_latest_match(self, player: PlayerRanking) -> MatchResult | None:
        player_key = _player_key_from_ranking(player)
        if player_key is None:
            raise PlayerDataError(
                f"Cannot look up ATP fixtures for {player.name!r}: player_id "
                f"{player.player_id!r} is not a numeric api-tennis player_key. "
                "Refusing to guess by name."
            )

        today = date.today()
        try:
            fixtures = self._client.get_fixtures(
                player_key=player_key,
                date_start=(today - timedelta(days=self._lookback_days)).isoformat(),
                date_stop=today.isoformat(),
            )
        except Exception as exc:  # noqa: BLE001
            raise PlayerDataError(
                f"Could not retrieve ATP fixtures for {player.name} "
                f"(player_key {player_key}): {exc}"
            ) from exc

        completed = self._completed_atp_singles(fixtures, context=player.name)
        completed.sort(key=lambda f: str(f.get("event_date", "")), reverse=True)
        for fixture in completed:
            try:
                return self._build_match_result(fixture, player_key, player.name)
            except ValueError as exc:
                logger.error(
                    "Skipping unusable ATP fixture for %s (player_key %s): %s; fixture=%r",
                    player.name,
                    player_key,
                    exc,
                    fixture,
                )
        return None

    def get_matches_for_date(
        self, players: Sequence[PlayerRanking], target_date: date
    ) -> MatchLookupResult:
        try:
            fixtures = self._fixtures_for_date(target_date)
        except Exception as exc:  # noqa: BLE001 - whole-day lookup failed
            raise DataProviderError(
                f"ATP fixture lookup failed for {target_date.isoformat()}: {exc}"
            ) from exc

        completed = self._completed_atp_singles(
            fixtures, context=f"date {target_date.isoformat()}"
        )
        by_player_key = self._index_fixtures_by_player_key(completed)

        matches: dict[str, MatchResult] = {}
        unresolved: set[str] = set()
        for player in players:
            player_key = _player_key_from_ranking(player)
            if player_key is None:
                logger.error(
                    "Cannot reconcile %s into ATP fixtures: player_id %r is not a "
                    "numeric api-tennis player_key. Leaving unresolved (no name guess).",
                    player.name,
                    player.player_id,
                )
                unresolved.add(player.player_id)
                continue

            player_fixtures = by_player_key.get(player_key, [])
            player_fixtures.sort(key=lambda f: str(f.get("event_date", "")), reverse=True)
            built: MatchResult | None = None
            saw_unusable = False
            for fixture in player_fixtures:
                try:
                    built = self._build_match_result(fixture, player_key, player.name)
                    break
                except ValueError as exc:
                    saw_unusable = True
                    logger.error(
                        "ATP fixture for %s (player_key %s) on %s is unusable: %s; fixture=%r",
                        player.name,
                        player_key,
                        target_date.isoformat(),
                        exc,
                        fixture,
                    )
            if built is not None:
                matches[player.player_id] = built
            elif saw_unusable:
                unresolved.add(player.player_id)
        return MatchLookupResult(matches=matches, unresolved_player_ids=frozenset(unresolved))

    def _fixtures_for_date(self, target_date: date) -> list[dict[str, Any]]:
        cached = self._fixtures_by_date.get(target_date)
        if cached is not None:
            return cached
        day = target_date.isoformat()
        fixtures = self._client.get_fixtures_for_date(
            date_start=day,
            date_stop=day,
            event_type_key=ATP_SINGLES_EVENT_TYPE_KEY,
            timezone=self._timezone,
        )
        self._fixtures_by_date[target_date] = fixtures
        return fixtures

    def _completed_atp_singles(
        self, fixtures: Sequence[dict[str, Any]], *, context: str
    ) -> list[dict[str, Any]]:
        selected: list[dict[str, Any]] = []
        wta_count = 0
        for fixture in fixtures:
            if _is_wta_fixture(fixture):
                wta_count += 1
                continue
            if not _is_atp_singles_fixture(fixture):
                continue
            if fixture.get("event_status") not in _COMPLETED_EVENT_STATUSES:
                continue
            selected.append(fixture)
        if wta_count:
            logger.error(
                "ATP match provider received %d WTA fixture(s) while loading %s; "
                "those rows were discarded and will not be used as ATP results.",
                wta_count,
                context,
            )
        if fixtures and not selected and wta_count == len(fixtures):
            raise DataProviderError(
                f"ATP match provider received only WTA fixtures while loading {context}. "
                "Refusing to treat WTA matches as ATP."
            )
        return selected

    @staticmethod
    def _index_fixtures_by_player_key(
        fixtures: Sequence[dict[str, Any]],
    ) -> dict[int, list[dict[str, Any]]]:
        index: dict[int, list[dict[str, Any]]] = {}
        for fixture in fixtures:
            first = _int_key(fixture.get("first_player_key"))
            second = _int_key(fixture.get("second_player_key"))
            if first is None or second is None:
                logger.error(
                    "ATP fixture is missing a numeric player key; skipping. fixture=%r",
                    fixture,
                )
                continue
            index.setdefault(first, []).append(fixture)
            index.setdefault(second, []).append(fixture)
        return index

    @staticmethod
    def _build_match_result(
        fixture: dict[str, Any], player_key: int, player_name: str
    ) -> MatchResult:
        first_key = _int_key(fixture.get("first_player_key"))
        second_key = _int_key(fixture.get("second_player_key"))
        if first_key == player_key:
            our_slot, opponent_label = "first", str(fixture.get("event_second_player") or "")
        elif second_key == player_key:
            our_slot, opponent_label = "second", str(fixture.get("event_first_player") or "")
        else:
            raise ValueError(
                f"fixture does not reference player_key {player_key} for {player_name}"
            )

        winner_slot = _WINNER_SLOT.get(str(fixture.get("event_winner")))
        if winner_slot is None:
            raise ValueError(f"no derivable winner (event_winner={fixture.get('event_winner')!r})")

        opponent = opponent_label.strip()
        if not opponent:
            raise ValueError("opponent name is missing")
        tournament = str(fixture.get("tournament_name") or "").strip()
        if not tournament:
            raise ValueError("tournament name is missing")

        return MatchResult(
            opponent=opponent,
            tournament=tournament,
            round=_friendly_round(str(fixture.get("tournament_round") or "")),
            score=_format_score(fixture.get("scores"), our_slot),
            won=(winner_slot == our_slot),
            match_date=_parse_event_date(fixture.get("event_date")),
            surface=None,
        )
