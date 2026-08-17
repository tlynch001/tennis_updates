"""ElevenLabs text-to-speech integration (Phase 2).

Disabled by default (``voice.enabled: false`` in the config). When enabled,
``script.txt`` is sent to the ElevenLabs API and the resulting audio is
written to ``narration.mp3``. The API key is **never** read from the config
file; it is resolved from an environment variable (default
``ELEVENLABS_API_KEY``, configurable via ``voice.api_key_env``) which should
be set in your shell, a local git-ignored ``.env`` file, or your CI/scheduler
secret store.

## Slide-timing metadata

This uses ElevenLabs' ``.../with-timestamps`` endpoint rather than the
plain ``.../{voice_id}`` one - the *same* text-to-speech generation, just
requesting the response include character-level start/end times alongside
the audio, at no extra API call or credit cost (see the README's "Slide
timing synchronization" section for the comparison that led here). When a
``report`` is supplied and the response includes alignment data,
:mod:`wta_daily.voice.narration_timing` derives one timing segment per
visual (intro / each player / featured player / sign-off) and writes it to
``narration_timing.json`` next to the audio, for
:class:`~wta_daily.video.ffmpeg_assembler.FfmpegVideoAssembler` to size
slides against - never required for narration itself to succeed.
"""

from __future__ import annotations

import base64
import logging
from pathlib import Path
from typing import Any

from wta_daily.config import VoiceConfig
from wta_daily.exceptions import VoiceSynthesisError
from wta_daily.models import DailyReport
from wta_daily.plugins.base import VoiceSynthesizer
from wta_daily.plugins.registry import voice_registry
from wta_daily.voice.narration_timing import compute_segment_timings, write_timing_file

logger = logging.getLogger(__name__)

#: The "with-timestamps" variant of the standard text-to-speech endpoint -
#: same generation, same cost, additionally returns character alignment.
_API_URL_TEMPLATE = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/with-timestamps"

_TIMING_FILENAME = "narration_timing.json"


@voice_registry.register("elevenlabs")
class ElevenLabsVoiceSynthesizer(VoiceSynthesizer):
    """Synthesizes narration audio via the ElevenLabs REST API."""

    def __init__(self, voice_config: VoiceConfig | None = None, **_ignored: object) -> None:
        self._config = voice_config or VoiceConfig()

    def synthesize(
        self, script_path: Path, output_path: Path, report: DailyReport | None = None
    ) -> Path:
        api_key = self._config.resolve_api_key()
        if not api_key:
            raise VoiceSynthesisError(
                f"Voice synthesis is enabled but {self._config.api_key_env} is not set. "
                f"Set it in your environment or .env file - never in the config file."
            )

        import requests

        script_text = script_path.read_text(encoding="utf-8")
        url = _API_URL_TEMPLATE.format(voice_id=self._config.voice_id)
        payload = {
            "text": script_text,
            "model_id": self._config.model_id,
            "voice_settings": {
                "stability": self._config.stability,
                "similarity_boost": self._config.similarity_boost,
            },
        }
        headers = {"xi-api-key": api_key, "Content-Type": "application/json"}

        try:
            response = requests.post(url, json=payload, headers=headers, timeout=120)
            response.raise_for_status()
            data = response.json()
            audio_bytes = base64.b64decode(data["audio_base64"])
        except Exception as exc:  # noqa: BLE001
            raise VoiceSynthesisError(f"ElevenLabs request failed: {exc}") from exc

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(audio_bytes)
        logger.info("Wrote narration audio to %s", output_path)

        self._write_timing_file_if_possible(data.get("alignment"), report, script_text, output_path)
        return output_path

    def _write_timing_file_if_possible(
        self,
        alignment: dict[str, Any] | None,
        report: DailyReport | None,
        script_text: str,
        output_path: Path,
    ) -> None:
        """Best-effort: slide timing is a nice-to-have derived from the
        same response, never required for narration.mp3 to be considered a
        success - any problem here is logged and simply means
        FfmpegVideoAssembler falls back to fixed-duration slides."""

        if report is None:
            return
        if not alignment or not alignment.get("characters"):
            logger.info(
                "ElevenLabs did not return character alignment for this request; "
                "video slides will use fixed durations instead of narration timing."
            )
            return

        try:
            segments = compute_segment_timings(
                report,
                script_text,
                list(alignment["characters"]),
                [float(t) for t in alignment["character_start_times_seconds"]],
                [float(t) for t in alignment["character_end_times_seconds"]],
            )
            if not segments:
                logger.info(
                    "Could not derive narration segments from script.txt's structure; "
                    "video slides will use fixed durations instead."
                )
                return
            timing_path = output_path.with_name(_TIMING_FILENAME)
            write_timing_file(timing_path, segments)
            logger.info("Wrote narration timing metadata to %s", timing_path)
        except Exception:  # noqa: BLE001 - timing metadata must never break narration
            logger.exception("Could not compute/write narration timing metadata; continuing.")
