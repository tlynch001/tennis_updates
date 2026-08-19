"""Storage that lets the pipeline tell "she was just eliminated/crowned
champion" apart from "she's still eliminated/still champion, same as
yesterday" for the tournament-elimination narration context (see
:mod:`wta_daily.models`'s :class:`~wta_daily.models.TournamentRunStatus`
and the README's "Tournament elimination context" section).

Deliberately its own small file (``tournament-status-history.json`` under
the configured ``data_dir``) rather than reusing
:class:`~wta_daily.persistence.snapshot_store.RankingsSnapshotStore` -
this tracks a completely different thing (a player's *tournament* result,
not her *ranking*) on a different key shape, and the two stores' failure
modes shouldn't be able to affect each other.

Keyed by ``player_id`` only (one entry per player, always overwritten with
the latest known result) plus a ``(tournament_group_id, year,
round_reached)`` triple to detect whether *this specific* result has
already been reported once before. ``year`` here is deliberately the
calendar year of the run's ``target_date`` (supplied by
:mod:`wta_daily.pipeline`), not any tournament-provider-internal year
field - this store has no dependency on ``wta_official`` or any other
match provider's internals, consistent with every other module in this
package.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import replace
from pathlib import Path
from typing import Any

from wta_daily.models import TournamentRunStatus, TournamentState

logger = logging.getLogger(__name__)

#: States for which "have I told this story before" is even a meaningful
#: question - ACTIVE/DID_NOT_PARTICIPATE/UNKNOWN never engage the
#: detailed-once/brief-thereafter narration distinction, so nothing about
#: them is worth persisting here.
_TRACKED_STATES = frozenset({TournamentState.ELIMINATED, TournamentState.CHAMPION})


def _atomic_write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with tmp_path.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False, sort_keys=True)
        fh.write("\n")
    os.replace(tmp_path, path)


class TournamentStatusStore:
    """Reads/writes ``tournament-status-history.json``."""

    def __init__(self, data_dir: str | Path) -> None:
        self._data_dir = Path(data_dir)

    @property
    def path(self) -> Path:
        return self._data_dir / "tournament-status-history.json"

    def load(self) -> dict[str, dict[str, Any]]:
        if not self.path.exists():
            return {}
        try:
            with self.path.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning(
                "Could not read %s (%s) - treating every tournament result as newly reported this run.",
                self.path,
                exc,
            )
            return {}
        return data if isinstance(data, dict) else {}

    def resolve_is_new_development(
        self, player_id: str, year: int, status: TournamentRunStatus
    ) -> TournamentRunStatus:
        """Return ``status`` with ``is_new_development`` set correctly, and
        record it for next time.

        A no-op (returns ``status`` unchanged, records nothing) for any
        state outside :data:`_TRACKED_STATES` - there's nothing to
        remember about "active" or "did not participate" from one day to
        the next.
        """

        if status.state not in _TRACKED_STATES:
            return status

        history = self.load()
        previous = history.get(player_id)
        is_new = previous is None or (
            previous.get("tournament_group_id") != status.tournament_group_id
            or previous.get("year") != year
            or previous.get("round_reached") != status.round_reached
        )

        history[player_id] = {
            "tournament_group_id": status.tournament_group_id,
            "year": year,
            "round_reached": status.round_reached,
            "state": status.state.value,
        }
        try:
            _atomic_write_json(self.path, history)
        except OSError as exc:  # noqa: BLE001 - persistence failing must not break narration
            logger.warning(
                "Could not persist tournament-status history to %s (%s) - the "
                "'detailed once, brief afterward' distinction may repeat next run.",
                self.path,
                exc,
            )

        return replace(status, is_new_development=is_new)
