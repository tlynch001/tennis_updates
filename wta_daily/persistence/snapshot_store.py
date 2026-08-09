"""Storage for rankings history and a canonical player cache.

Two files live under the configured ``data_dir``:

``rankings-history.json``
    An append-only (by date) list of daily rankings snapshots. This is what
    lets the pipeline compute ranking movement by comparing "today" against
    the most recent prior snapshot, without depending on any provider's own
    notion of "last week's rank" (which may use a different reference week
    than "yesterday").

``players.json``
    A small cache of ``player_id -> {name, country_code}`` built up over
    time. Handy for future modules (player biographies, head-to-head stats,
    etc.) that want a stable player identity even if a provider's spelling
    of a name changes slightly.

Writes are done via a write-to-temp-then-rename so a crash mid-write (e.g.
the machine loses power during an unattended overnight run) cannot corrupt
either file.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import date
from pathlib import Path
from typing import Any

from wta_daily.models import PlayerRanking

logger = logging.getLogger(__name__)


def _atomic_write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with tmp_path.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False, sort_keys=False)
        fh.write("\n")
    os.replace(tmp_path, path)


class RankingsSnapshotStore:
    """Reads/writes ``rankings-history.json`` and ``players.json``."""

    def __init__(self, data_dir: str | Path) -> None:
        self._data_dir = Path(data_dir)

    @property
    def history_path(self) -> Path:
        return self._data_dir / "rankings-history.json"

    @property
    def players_path(self) -> Path:
        return self._data_dir / "players.json"

    def load_history(self) -> list[dict[str, Any]]:
        if not self.history_path.exists():
            return []
        with self.history_path.open("r", encoding="utf-8") as fh:
            return json.load(fh)

    def get_previous_snapshot(
        self, before: date, tour: str
    ) -> tuple[date, list[PlayerRanking]] | None:
        """Return the most recent snapshot strictly before ``before`` for ``tour``."""

        history = [
            entry
            for entry in self.load_history()
            if entry.get("tour", "wta") == tour and entry.get("date") != before.isoformat()
        ]
        history.sort(key=lambda entry: entry["date"])
        candidates = [entry for entry in history if entry["date"] < before.isoformat()]
        if not candidates:
            return None
        latest = candidates[-1]
        snapshot_date = date.fromisoformat(latest["date"])
        rankings = [PlayerRanking.from_dict(r) for r in latest["rankings"]]
        return snapshot_date, rankings

    def save_snapshot(self, day: date, tour: str, rankings: list[PlayerRanking]) -> None:
        history = self.load_history()
        target_date = day.isoformat()
        history = [
            entry
            for entry in history
            if not (entry.get("date") == target_date and entry.get("tour", "wta") == tour)
        ]
        history.append(
            {
                "date": day.isoformat(),
                "tour": tour,
                "rankings": [r.to_dict() for r in rankings],
            }
        )
        history.sort(key=lambda entry: (entry["date"], entry.get("tour", "wta")))
        _atomic_write_json(self.history_path, history)
        self._update_players_cache(rankings)
        logger.info("Saved rankings snapshot for %s (%s) to %s", day.isoformat(), tour, self.history_path)

    def load_players_cache(self) -> dict[str, dict[str, Any]]:
        if not self.players_path.exists():
            return {}
        with self.players_path.open("r", encoding="utf-8") as fh:
            return json.load(fh)

    def _update_players_cache(self, rankings: list[PlayerRanking]) -> None:
        cache = self.load_players_cache()
        for ranking in rankings:
            cache[ranking.player_id] = {
                "name": ranking.name,
                "country_code": ranking.country_code,
            }
        _atomic_write_json(self.players_path, cache)
