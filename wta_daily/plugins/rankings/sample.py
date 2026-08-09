"""Offline rankings provider backed by a static JSON fixture.

Used by unit tests and by anyone experimenting with the pipeline without
network access or before deciding on a production data provider. Never used
by default in the shipped configuration.
"""

from __future__ import annotations

import json
from pathlib import Path

from wta_daily.models import PlayerRanking
from wta_daily.plugins.base import RankingsProvider
from wta_daily.plugins.registry import rankings_registry

DEFAULT_FIXTURE_PATH = Path("data/sample/rankings_sample.json")


@rankings_registry.register("sample")
class SampleRankingsProvider(RankingsProvider):
    """Reads a fixed list of players from a local JSON fixture file."""

    def __init__(self, fixture_path: str | Path = DEFAULT_FIXTURE_PATH, **_ignored: object) -> None:
        self._fixture_path = Path(fixture_path)

    def get_top_n(self, n: int) -> list[PlayerRanking]:
        with self._fixture_path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        rankings = [PlayerRanking.from_dict(item) for item in data.get("rankings", [])]
        rankings.sort(key=lambda r: r.rank)
        return rankings[:n]
