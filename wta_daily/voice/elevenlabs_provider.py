"""ElevenLabs text-to-speech integration (Phase 2).

Disabled by default (``voice.enabled: false`` in the config). When enabled,
``script.txt`` is sent to the ElevenLabs API and the resulting audio is
written to ``narration.mp3``. The API key is **never** read from the config
file; it is resolved from an environment variable (default
``ELEVENLABS_API_KEY``, configurable via ``voice.api_key_env``) which should
be set in your shell, a local git-ignored ``.env`` file, or your CI/scheduler
secret store.
"""

from __future__ import annotations

import logging
from pathlib import Path

from wta_daily.config import VoiceConfig
from wta_daily.exceptions import VoiceSynthesisError
from wta_daily.plugins.base import VoiceSynthesizer
from wta_daily.plugins.registry import voice_registry

logger = logging.getLogger(__name__)

_API_URL_TEMPLATE = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"


@voice_registry.register("elevenlabs")
class ElevenLabsVoiceSynthesizer(VoiceSynthesizer):
    """Synthesizes narration audio via the ElevenLabs REST API."""

    def __init__(self, voice_config: VoiceConfig | None = None, **_ignored: object) -> None:
        self._config = voice_config or VoiceConfig()

    def synthesize(self, script_path: Path, output_path: Path) -> Path:
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
        headers = {"xi-api-key": api_key, "Content-Type": "application/json", "Accept": "audio/mpeg"}

        try:
            response = requests.post(url, json=payload, headers=headers, timeout=120)
            response.raise_for_status()
        except Exception as exc:  # noqa: BLE001
            raise VoiceSynthesisError(f"ElevenLabs request failed: {exc}") from exc

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(response.content)
        logger.info("Wrote narration audio to %s", output_path)
        return output_path
