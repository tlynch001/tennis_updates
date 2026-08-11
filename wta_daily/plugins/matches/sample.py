"""Offline match provider backed by a static JSON fixture."""

from __future__ import annotations

import json
from pathlib import Path

from wta_daily.models import MatchResult, PlayerRanking
from wta_daily.plugins.base import MatchProvider
from wta_daily.plugins.registry import matches_registry

DEFAULT_FIXTURE_PATH = Path("data/sample/matches_sample.json")


@matches_registry.register("sample")
class SampleMatchProvider(MatchProvider):
    """Reads each player's latest match from a local JSON fixture file."""

    def __init__(self, fixture_path: str | Path = DEFAULT_FIXTURE_PATH, **_ignored: object) -> None:
        self._fixture_path = Path(fixture_path)
        with self._fixture_path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        self._matches: dict[str, dict] = data.get("matches", {})

    def get_latest_match(self, player: PlayerRanking) -> MatchResult | None:
        entry = self._matches.get(player.player_id)
        if entry is None:
            return None
        return MatchResult.from_dict(entry)
