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

    def save_snapshot(
        self,
        day: date,
        tour: str,
        rankings: list[PlayerRanking],
        featured_players: dict[str, PlayerRanking] | None = None,
    ) -> None:
        """Record the tracked (``top_n``) group's ranks for movement comparison.

        Deliberately scoped to exactly the tracked group, not any larger
        rankings pool that happened to be fetched in the same run - "NEW"
        (see :class:`~wta_daily.models.Movement`) specifically means "just
        entered *this* tracked group", and saving a wider pool here would
        silently change that meaning (a player already present in a wider
        pool would show as "same"/"up" instead of "new" upon actually
        entering the tracked group). Use :meth:`update_players_cache`
        separately for wider, non-time-sensitive metadata.

        ``featured_players`` records the ranks of players tracked *outside*
        the official group (e.g. a :class:`~wta_daily.config.FeaturedPlayerConfig`
        subject who isn't currently in the Top N) purely so
        :meth:`get_previous_player_rank` can still compute movement for her
        later - it never affects Top N "NEW" semantics, since it's stored
        under a separate key.
        """

        history = self.load_history()
        target_date = day.isoformat()
        history = [
            entry
            for entry in history
            if not (entry.get("date") == target_date and entry.get("tour", "wta") == tour)
        ]
        entry: dict[str, Any] = {
            "date": day.isoformat(),
            "tour": tour,
            "rankings": [r.to_dict() for r in rankings],
        }
        if featured_players:
            entry["featured_players"] = {
                player_id: r.to_dict() for player_id, r in featured_players.items()
            }
        history.append(entry)
        history.sort(key=lambda entry: (entry["date"], entry.get("tour", "wta")))
        _atomic_write_json(self.history_path, history)
        self.update_players_cache(list(rankings) + list((featured_players or {}).values()))
        logger.info("Saved rankings snapshot for %s (%s) to %s", day.isoformat(), tour, self.history_path)

    def get_previous_player_rank(self, before: date, tour: str, player_id: str) -> int | None:
        """Return ``player_id``'s rank in the most recent snapshot strictly
        before ``before``, whether she was part of the tracked Top N group
        that day or recorded separately via ``featured_players`` (see
        :meth:`save_snapshot`).

        This is the one lookup that makes movement comparisons work
        identically for the Top N and for any player tracked outside it -
        including a future featured player who isn't Emma Navarro. Returns
        ``None`` if there's no prior snapshot at all, or if it exists but
        never recorded this player either way (e.g. the feature was just
        enabled today).
        """

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
        for raw_ranking in latest.get("rankings", []):
            if raw_ranking.get("player_id") == player_id:
                return int(raw_ranking["rank"])
        for pid, raw_ranking in latest.get("featured_players", {}).items():
            if pid == player_id:
                return int(raw_ranking["rank"])
        return None

    def load_players_cache(self) -> dict[str, dict[str, Any]]:
        if not self.players_path.exists():
            return {}
        with self.players_path.open("r", encoding="utf-8") as fh:
            return json.load(fh)

    def update_players_cache(self, rankings: list[PlayerRanking]) -> None:
        """Merge ``{name, country_code}`` for each of ``rankings`` into the
        stable player-metadata cache (``players.json``).

        Safe to call with a wider group than the tracked ``top_n`` (e.g. the
        full rankings pool fetched this run) - unlike :meth:`save_snapshot`,
        this file has no "movement" concept to protect, it's purely a
        stable-identity cache for future modules (see the module docstring),
        so caching more names/countries here is a pure win with no
        behavioral downside.
        """

        cache = self.load_players_cache()
        for ranking in rankings:
            cache[ranking.player_id] = {
                "name": ranking.name,
                "country_code": ranking.country_code,
            }
        _atomic_write_json(self.players_path, cache)
