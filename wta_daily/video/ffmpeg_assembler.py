"""FFmpeg-based video assembly (Phase 2).

Disabled by default (``video.enabled: false``). When enabled, builds
``video.mp4`` from:

1. the leaderboard overview,
2. one slide per player card (plus, if configured, the featured player),
3. the narration track (``narration.mp3``) if it exists, and
4. optional background music, mixed underneath the narration.

This shells out to the ``ffmpeg`` CLI (via :mod:`subprocess`) rather than
pulling in a Python wrapper library, so the only new "dependency" is having
ffmpeg installed on the machine that runs the job - true for essentially
every CI runner and easy to install locally (``apt install ffmpeg`` /
``brew install ffmpeg`` / the official Windows builds).

## Slide timing

Slides are sized to match the actual spoken narration whenever
``narration_timing.json`` exists (written by
:class:`~wta_daily.voice.elevenlabs_provider.ElevenLabsVoiceSynthesizer`
from ElevenLabs' character-alignment response - see
:mod:`wta_daily.voice.narration_timing` and the README's "Slide timing
synchronization" section for the full investigation): the leaderboard
shows during the intro and sign-off, and each player's card shows for
exactly the stretch of narration that mentions her, in order.

If that file doesn't exist (narration disabled, or ElevenLabs didn't
return alignment for some reason) or turns out to be unusable, this falls
back to the previous fixed-duration behavior
(``video.seconds_per_player_card`` for every player, a fixed intro) rather
than failing - synchronized timing is a quality improvement, never a
requirement for video assembly to succeed.
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
from wta_daily.voice.narration_timing import NarrationSegment, read_timing_file

logger = logging.getLogger(__name__)

_INTRO_SECONDS = 4.0
_LEADERBOARD_SECONDS = 6.0

#: Guards against a literal zero/negative-duration concat entry (ffmpeg's
#: concat demuxer doesn't handle those gracefully) - not a general quality
#: floor, since artificially inflating a real, timing-derived duration
#: would push every later slide out of sync with the narration.
_MIN_SLIDE_SECONDS = 0.1


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

        segments = read_timing_file(store.timing_path)
        if segments:
            logger.info(
                "Using narration-synchronized slide timing from %s (%d segments).",
                store.timing_path,
                len(segments),
            )
            slides = self._slides_from_segments(segments, report, store)
        else:
            logger.info(
                "No usable narration timing found; using fixed-duration slides "
                "(%.1fs/player).",
                self._config.seconds_per_player_card,
            )
            slides = self._slides_from_fixed_durations(report, store)

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

    def _slides_from_segments(
        self, segments: list[NarrationSegment], report: DailyReport, store: DailyOutputStore
    ) -> list[tuple[Path, float]]:
        """Build the slide list from real narration timing.

        Every segment becomes exactly one slide - a missing image (e.g. a
        player card that failed to render) falls back to the leaderboard
        for that segment's duration rather than being dropped, so the cut
        points stay aligned with the narration even when a graphic is
        unavailable.
        """

        slides: list[tuple[Path, float]] = []
        for segment in segments:
            duration = max(segment.duration_seconds, _MIN_SLIDE_SECONDS)
            image_path = self._image_for_segment(segment, report, store)
            slides.append((image_path, duration))
        return self._merge_consecutive_identical_images(slides)

    def _image_for_segment(
        self, segment: NarrationSegment, report: DailyReport, store: DailyOutputStore
    ) -> Path:
        if segment.kind in ("intro", "closer"):
            return store.leaderboard_path

        if segment.kind == "player" and segment.rank is not None:
            card_path = store.player_card_path(segment.rank)
            if card_path.exists():
                return card_path
            logger.warning(
                "No card image for rank %d; showing the leaderboard during her narration "
                "instead of skipping the segment.",
                segment.rank,
            )
            return store.leaderboard_path

        if segment.kind == "featured":
            if store.featured_card_path.exists():
                return store.featured_card_path
            logger.info(
                "No dedicated featured-player visual found; showing the leaderboard "
                "during %s's segment instead.",
                segment.label,
            )
            return store.leaderboard_path

        # Defensive fallback for any future/unrecognized segment kind.
        return store.leaderboard_path

    @staticmethod
    def _merge_consecutive_identical_images(
        slides: list[tuple[Path, float]],
    ) -> list[tuple[Path, float]]:
        """Collapse back-to-back slides that ended up showing the same
        image (e.g. intro -> a missing card's leaderboard fallback) into
        one longer slide, rather than an unnecessary hard cut to the exact
        same picture."""

        if not slides:
            return slides
        merged: list[tuple[Path, float]] = [slides[0]]
        for image_path, duration in slides[1:]:
            last_image, last_duration = merged[-1]
            if image_path == last_image:
                merged[-1] = (last_image, last_duration + duration)
            else:
                merged.append((image_path, duration))
        return merged

    def _slides_from_fixed_durations(
        self, report: DailyReport, store: DailyOutputStore
    ) -> list[tuple[Path, float]]:
        """The original, pre-synchronization behavior: fixed durations for
        everyone, used whenever real narration timing isn't available."""

        slides: list[tuple[Path, float]] = [
            (store.leaderboard_path, _INTRO_SECONDS + _LEADERBOARD_SECONDS)
        ]
        for player in report.players:
            card_path = store.player_card_path(player.rank)
            if card_path.exists():
                slides.append((card_path, self._config.seconds_per_player_card))
            else:
                logger.warning("No card image for rank %d; skipping in video.", player.rank)

        if report.featured_player is not None and report.featured_player.rank is not None:
            featured_image = (
                store.featured_card_path
                if store.featured_card_path.exists()
                else store.leaderboard_path
            )
            slides.append((featured_image, self._config.seconds_per_player_card))

        return self._merge_consecutive_identical_images(slides)

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
