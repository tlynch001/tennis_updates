"""FFmpeg-based video assembly (Phase 2).

Disabled by default (``video.enabled: false``). When enabled, builds
``video.mp4`` from:

1. the leaderboard overview,
2. one slide per player card,
3. the narration track (``narration.mp3``) if it exists, and
4. optional background music, mixed underneath the narration.

This shells out to the ``ffmpeg`` CLI (via :mod:`subprocess`) rather than
pulling in a Python wrapper library, so the only new "dependency" is having
ffmpeg installed on the machine that runs the job - true for essentially
every CI runner and easy to install locally (``apt install ffmpeg`` /
``brew install ffmpeg`` / the official Windows builds).
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
from pathlib import Path

from wta_daily.config import VideoConfig
from wta_daily.exceptions import VideoAssemblyError
from wta_daily.models import DailyReport
from wta_daily.persistence.report_store import DailyOutputStore
from wta_daily.plugins.base import VideoAssembler
from wta_daily.plugins.registry import video_registry

logger = logging.getLogger(__name__)

_INTRO_SECONDS = 4.0
_LEADERBOARD_SECONDS = 6.0


@video_registry.register("ffmpeg")
class FfmpegVideoAssembler(VideoAssembler):
    """Assembles the leaderboard, player cards, and narration into an MP4."""

    def __init__(self, video_config: VideoConfig | None = None, **_ignored: object) -> None:
        self._config = video_config or VideoConfig()

    def assemble(self, report: DailyReport, output_dir: Path) -> Path:
        if shutil.which("ffmpeg") is None:
            raise VideoAssemblyError(
                "ffmpeg was not found on PATH. Install it (e.g. 'apt install ffmpeg') to "
                "enable video assembly, or set video.enabled: false."
            )

        store = DailyOutputStore(output_dir.parent, report.report_date)
        leaderboard = store.leaderboard_path
        if not leaderboard.exists():
            raise VideoAssemblyError(f"Missing leaderboard image: {leaderboard}")

        slides: list[tuple[Path, float]] = [(leaderboard, _INTRO_SECONDS + _LEADERBOARD_SECONDS)]
        for player in report.players:
            card_path = store.player_card_path(player.rank)
            if card_path.exists():
                slides.append((card_path, self._config.seconds_per_player_card))
            else:
                logger.warning("No card image for rank %d; skipping in video.", player.rank)

        with tempfile.TemporaryDirectory(prefix="wta-daily-video-") as tmp:
            tmp_path = Path(tmp)
            silent_video = tmp_path / "silent.mp4"
            self._build_silent_video(slides, silent_video)

            output_path = store.video_path
            narration = store.narration_path
            if narration.exists():
                self._mux_audio(silent_video, narration, output_path)
            else:
                logger.warning("No narration.mp3 found; video.mp4 will have no audio track.")
                shutil.copy(silent_video, output_path)

        return output_path

    def _build_silent_video(self, slides: list[tuple[Path, float]], output_path: Path) -> None:
        list_file = output_path.parent / "concat_list.txt"
        with list_file.open("w", encoding="utf-8") as fh:
            for image_path, duration in slides:
                fh.write(f"file '{image_path.resolve()}'\n")
                fh.write(f"duration {duration}\n")
            # ffmpeg's concat demuxer requires the last file repeated without a duration.
            fh.write(f"file '{slides[-1][0].resolve()}'\n")

        command = [
            "ffmpeg",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(list_file),
            "-vf",
            f"scale={self._config.width}:{self._config.height},fps={self._config.fps}",
            "-pix_fmt",
            "yuv420p",
            "-c:v",
            "libx264",
            str(output_path),
        ]
        self._run(command)

    def _mux_audio(self, silent_video: Path, narration: Path, output_path: Path) -> None:
        command = [
            "ffmpeg",
            "-y",
            "-i",
            str(silent_video),
            "-i",
            str(narration),
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-shortest",
            str(output_path),
        ]
        self._run(command)

    @staticmethod
    def _run(command: list[str]) -> None:
        logger.debug("Running: %s", " ".join(command))
        result = subprocess.run(command, capture_output=True, text=True)
        if result.returncode != 0:
            raise VideoAssemblyError(f"ffmpeg failed: {result.stderr[-2000:]}")
