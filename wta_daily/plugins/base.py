"""Abstract base classes that define every pluggable concern in the pipeline.

Each interface here is intentionally small. Concrete implementations live in
their own module under :mod:`wta_daily.plugins` (or under :mod:`wta_daily.graphics`,
:mod:`wta_daily.scripts_gen`, :mod:`wta_daily.voice`, :mod:`wta_daily.video`) and
register themselves with the matching registry in
:mod:`wta_daily.plugins.registry`. The pipeline only ever depends on these
abstract types, never on a concrete provider, which is what makes it possible
to add an ATP feed, a "Top 25" variant, or a Spanish narrator by writing a new
module instead of touching existing code.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from collections.abc import Sequence
from datetime import date
from pathlib import Path

from wta_daily.models import DailyReport, MatchResult, PlayerRanking, PlayerReport

logger = logging.getLogger(__name__)


class RankingsProvider(ABC):
    """Retrieves a tour's current rankings snapshot."""

    #: Unique, stable identifier used in configuration files (e.g. "wta_official").
    name: str = "base"

    @abstractmethod
    def get_top_n(self, n: int) -> list[PlayerRanking]:
        """Return the current top ``n`` players, ordered by rank ascending."""


class MatchProvider(ABC):
    """Retrieves completed match results for players.

    There are two different questions a caller can ask, and they are **not**
    interchangeable:

    * :meth:`get_latest_match` - "what's the most recent completed match
      this provider knows about for this player, whenever it was?" This is
      useful context, but answering "did she play yesterday" by calling
      this and hoping the answer happens to be recent is exactly the bug
      that shipped in production: a source whose per-player history lags
      the current tournament week will confidently return an old match
      with no signal that it might not be current.
    * :meth:`get_matches_for_date` - "which of these players have a
      *confirmed* completed match on *this exact date*, and what happened?"
      A player absent from the result played that day, per this provider's
      information - never a stale substitute. The default implementation
      below falls back to :meth:`get_latest_match` filtered by date, which
      is honest (it will never claim a false date) but can under-report a
      real match if a provider's per-player history hasn't ingested it yet
      - a provider whose data source supports a genuine day-indexed lookup
      (see ``wta_official``, which scans the tournament-level feed instead
      of the slower per-player one) should override this for completeness.
    """

    name: str = "base"

    @abstractmethod
    def get_latest_match(self, player: PlayerRanking) -> MatchResult | None:
        """Return the player's most recent completed match, or ``None`` if the
        player has no recorded match (e.g. an unreleased qualifier).
        """

    def get_matches_for_date(
        self, players: Sequence[PlayerRanking], target_date: date
    ) -> dict[str, MatchResult]:
        """Return ``{player_id: MatchResult}`` for players confirmed to have
        completed a match on ``target_date``. Players not present in the
        result should be treated as ``played: false`` for that date - never
        substitute an older match.

        Default implementation: call :meth:`get_latest_match` per player and
        keep the result only if its ``match_date`` exactly equals
        ``target_date``. Failures are isolated per player (one player's
        lookup failing does not affect the others) since this default is
        built directly on the existing per-player contract.
        """

        results: dict[str, MatchResult] = {}
        for player in players:
            try:
                match = self.get_latest_match(player)
            except Exception as exc:  # noqa: BLE001 - isolate every player, no matter the failure
                logger.info(
                    "get_latest_match failed for %s while checking %s: %s", player.name, target_date, exc
                )
                continue
            if match is not None and match.match_date == target_date:
                results[player.player_id] = match
        return results


class ScriptGenerator(ABC):
    """Turns a :class:`~wta_daily.models.DailyReport` into a narration script."""

    name: str = "base"

    @abstractmethod
    def generate(self, report: DailyReport) -> str:
        """Return the full narration script as plain text."""


class GraphicsRenderer(ABC):
    """Renders the leaderboard and per-player card PNGs for a daily report."""

    name: str = "base"

    @abstractmethod
    def render_leaderboard(self, report: DailyReport, output_path: Path) -> Path:
        """Render the 1920x1080 leaderboard overview PNG."""

    @abstractmethod
    def render_player_card(self, player: PlayerReport, output_dir: Path, *, top_n: int) -> Path:
        """Render one player's card PNG into ``output_dir``.

        ``top_n`` is the size of the tracked list (e.g. 10) and is only used
        for display text such as "NEW in the Top 10".
        """


class VoiceSynthesizer(ABC):
    """Converts a narration script into an MP3 (or other audio) file."""

    name: str = "base"

    @abstractmethod
    def synthesize(self, script_path: Path, output_path: Path) -> Path:
        """Read ``script_path`` and write synthesized audio to ``output_path``."""


class VideoAssembler(ABC):
    """Assembles the final MP4 from graphics, narration, and optional music."""

    name: str = "base"

    @abstractmethod
    def assemble(self, report: DailyReport, output_dir: Path) -> Path:
        """Build ``video.mp4`` inside ``output_dir`` and return its path."""
