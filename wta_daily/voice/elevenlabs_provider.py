"""ElevenLabs text-to-speech integration (Phase 2).

Disabled by default (``voice.enabled: false`` in the config). When enabled,
``script.txt`` is sent to the ElevenLabs API and the resulting audio is
written to ``narration.mp3``. The API key is **never** read from the config
file; it is resolved from an environment variable (default
``ELEVENLABS_API_KEY``, configurable via ``voice.api_key_env``) which should
be set in your shell, a local git-ignored ``.env`` file, or your CI/scheduler
secret store.

## Pronunciation

Two known problems - some WTA player names come back mispronounced, and
tennis scores like ``"3-6,6-4,6-2"`` get read as if the hyphen were a
numeric range - are fixed here, each with the mechanism actually suited to
it (see the README's "Narration pronunciation" section for the full
investigation):

* Scores: :func:`wta_daily.voice.narration_text.normalize_for_speech`
  spells every score out in words (e.g. ``"six four, six two"``) before
  the text is sent - a general, rule-based transformation, since a score
  is an open-ended pattern, not a finite list of "known" values.
* Names: :func:`wta_daily.voice.pronunciation_dictionary.get_or_create_locator`
  attaches an ElevenLabs pronunciation dictionary (alias rules - the
  mechanism that actually applies to this project's configured model) so
  a curated, maintainable list of respellings is substituted by ElevenLabs
  itself at synthesis time.

Both only ever affect the audio: ``script.txt`` (read from disk here) and
``report.json`` are never touched by this module.
"""

from __future__ import annotations

import logging
from pathlib import Path

from wta_daily.config import VoiceConfig
from wta_daily.exceptions import VoiceSynthesisError
from wta_daily.plugins.base import VoiceSynthesizer
from wta_daily.plugins.registry import voice_registry
from wta_daily.voice.narration_text import normalize_for_speech
from wta_daily.voice.pronunciation_dictionary import (
    PronunciationDictionaryCache,
    get_or_create_locator,
)

logger = logging.getLogger(__name__)

_API_URL_TEMPLATE = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"

DEFAULT_CACHE_DIR = Path("data/cache")
_PRONUNCIATION_CACHE_FILENAME = "elevenlabs_pronunciation_dictionary.json"


@voice_registry.register("elevenlabs")
class ElevenLabsVoiceSynthesizer(VoiceSynthesizer):
    """Synthesizes narration audio via the ElevenLabs REST API."""

    def __init__(
        self,
        voice_config: VoiceConfig | None = None,
        cache_dir: str | Path | None = None,
        **_ignored: object,
    ) -> None:
        self._config = voice_config or VoiceConfig()
        self._dictionary_cache = PronunciationDictionaryCache(
            Path(cache_dir or DEFAULT_CACHE_DIR) / _PRONUNCIATION_CACHE_FILENAME
        )

    def synthesize(self, script_path: Path, output_path: Path) -> Path:
        api_key = self._config.resolve_api_key()
        if not api_key:
            raise VoiceSynthesisError(
                f"Voice synthesis is enabled but {self._config.api_key_env} is not set. "
                f"Set it in your environment or .env file - never in the config file."
            )

        import requests

        script_text = script_path.read_text(encoding="utf-8")
        speech_text = normalize_for_speech(script_text)

        url = _API_URL_TEMPLATE.format(voice_id=self._config.voice_id)
        payload: dict[str, object] = {
            "text": speech_text,
            "model_id": self._config.model_id,
            "voice_settings": {
                "stability": self._config.stability,
                "similarity_boost": self._config.similarity_boost,
            },
        }

        if self._config.pronunciation_dictionary_enabled:
            locator = get_or_create_locator(api_key, self._dictionary_cache)
            if locator is not None:
                payload["pronunciation_dictionary_locators"] = [locator]

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
