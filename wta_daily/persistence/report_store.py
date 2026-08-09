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
    def leaderboard_path(self) -> Path:
        return self.root / "leaderboard.png"

    @property
    def player_cards_dir(self) -> Path:
        return self.root / "player_cards"

    @property
    def narration_path(self) -> Path:
        return self.root / "narration.mp3"

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

    def player_card_path(self, rank: int) -> Path:
        return self.player_cards_dir / f"{rank:02d}.png"
