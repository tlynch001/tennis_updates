"""Manages the date-stamped, self-contained output folder for one day's run.

Every artifact for a given day (``report.json``, ``script.txt``,
``leaderboard.png``, ``player_cards/*.png``, and eventually ``narration.mp3``
and ``video.mp4``) is written under ``output/<YYYY-MM-DD>/`` so that a whole
day's output can be copied, archived, or committed to git as one unit.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from wta_daily.models import DailyReport


class DailyOutputStore:
    """Owns the on-disk layout for a single day's generated assets."""

    def __init__(self, output_root: str | Path, day: date) -> None:
        self._day = day
        self.root = Path(output_root) / day.isoformat()

    @property
    def report_path(self) -> Path:
        return self.root / "report.json"

    @property
    def script_path(self) -> Path:
        return self.root / "script.txt"

    @property
    def title_path(self) -> Path:
        """The canonical YouTube video title for this day (see
        :mod:`wta_daily.title`) - a single plain-text line, so it can be
        `cat`'d/read directly when publishing by hand, and reused verbatim
        by :mod:`wta_daily.youtube.uploader` when Phase 3 is enabled."""

        return self.root / "title.txt"

    @property
    def leaderboard_path(self) -> Path:
        return self.root / "leaderboard.png"

    @property
    def player_cards_dir(self) -> Path:
        return self.root / "player_cards"

    @property
    def narration_path(self) -> Path:
        return self.root / "narration.mp3"

    @property
    def timing_path(self) -> Path:
        """Optional per-segment narration timing metadata, written by a
        voice synthesizer that can derive it (see
        :mod:`wta_daily.voice.narration_timing`) and consumed by
        :class:`~wta_daily.video.ffmpeg_assembler.FfmpegVideoAssembler` to
        size video slides against actual spoken duration. May not exist -
        every consumer must treat that as "fall back to fixed durations",
        never as an error.
        """

        return self.root / "narration_timing.json"

    @property
    def featured_card_path(self) -> Path:
        """Dedicated visual for the featured-player segment (see
        :class:`~wta_daily.config.FeaturedPlayerConfig` and
        :mod:`wta_daily.graphics.featured_card`) - only written when a
        featured player is configured *and* her ranking was resolved this
        run. Every consumer (notably
        :class:`~wta_daily.video.ffmpeg_assembler.FfmpegVideoAssembler`)
        must still treat a missing file here as "fall back to the
        leaderboard", never as an error - the feature works the same way
        with no featured player configured at all.
        """

        return self.root / "featured_player.png"

    @property
    def thumbnail_path(self) -> Path:
        """The YouTube thumbnail (1280x720 - see
        :mod:`wta_daily.graphics.thumbnail`)."""

        return self.root / "thumbnail.png"

    @property
    def youtube_description_path(self) -> Path:
        """The plain-text YouTube description (see
        :mod:`wta_daily.youtube_description`)."""

        return self.root / "youtube_description.txt"

    @property
    def video_path(self) -> Path:
        return self.root / "video.mp4"

    def ensure_dirs(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self.player_cards_dir.mkdir(parents=True, exist_ok=True)

    def write_report(self, report: DailyReport) -> Path:
        self.ensure_dirs()
        import json

        with self.report_path.open("w", encoding="utf-8") as fh:
            json.dump(report.to_dict(), fh, indent=2, ensure_ascii=False)
            fh.write("\n")
        return self.report_path

    def write_script(self, script_text: str) -> Path:
        self.ensure_dirs()
        with self.script_path.open("w", encoding="utf-8") as fh:
            fh.write(script_text)
            if not script_text.endswith("\n"):
                fh.write("\n")
        return self.script_path

    def write_youtube_description(self, description_text: str) -> Path:
        self.ensure_dirs()
        with self.youtube_description_path.open("w", encoding="utf-8") as fh:
            fh.write(description_text)
            if not description_text.endswith("\n"):
                fh.write("\n")
        return self.youtube_description_path

    def write_title(self, title_text: str) -> Path:
        self.ensure_dirs()
        with self.title_path.open("w", encoding="utf-8") as fh:
            fh.write(title_text)
            if not title_text.endswith("\n"):
                fh.write("\n")
        return self.title_path

    def player_card_path(self, rank: int) -> Path:
        return self.player_cards_dir / f"{rank:02d}.png"
