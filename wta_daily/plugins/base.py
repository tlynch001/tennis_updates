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

from abc import ABC, abstractmethod
from pathlib import Path

from wta_daily.models import DailyReport, MatchResult, PlayerRanking, PlayerReport


class RankingsProvider(ABC):
    """Retrieves a tour's current rankings snapshot."""

    #: Unique, stable identifier used in configuration files (e.g. "wta_official").
    name: str = "base"

    @abstractmethod
    def get_top_n(self, n: int) -> list[PlayerRanking]:
        """Return the current top ``n`` players, ordered by rank ascending."""


class MatchProvider(ABC):
    """Retrieves the most recent completed match for a given player."""

    name: str = "base"

    @abstractmethod
    def get_latest_match(self, player: PlayerRanking) -> MatchResult | None:
        """Return the player's most recent completed match, or ``None`` if the
        player has no recorded match (e.g. an unreleased qualifier).
        """


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
