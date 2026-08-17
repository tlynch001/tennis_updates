"""Unit tests for :mod:`wta_daily.voice.elevenlabs_provider`.

Mocks the outbound HTTP call (never hits the network) to verify: the
script text is normalized for speech before being sent, script.txt on
disk is never modified, a pronunciation dictionary locator is attached
when available, missing/failed dictionary resolution degrades gracefully,
and the feature can be disabled via config.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from wta_daily.config import VoiceConfig
from wta_daily.exceptions import VoiceSynthesisError
from wta_daily.voice.elevenlabs_provider import ElevenLabsVoiceSynthesizer


class _FakeResponse:
    def __init__(self, content: bytes = b"fake-audio-bytes", status_ok: bool = True) -> None:
        self.content = content
        self._status_ok = status_ok

    def raise_for_status(self) -> None:
        if not self._status_ok:
            raise RuntimeError("simulated HTTP error")


def _write_script(tmp_path: Path, text: str) -> Path:
    script_path = tmp_path / "script.txt"
    script_path.write_text(text, encoding="utf-8")
    return script_path


def _config(**overrides: Any) -> VoiceConfig:
    base = VoiceConfig(enabled=True, api_key_env="TEST_ELEVENLABS_KEY")
    for key, value in overrides.items():
        setattr(base, key, value)
    return base


@pytest.fixture(autouse=True)
def _api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEST_ELEVENLABS_KEY", "fake-key")


def test_synthesize_sends_score_normalized_text(tmp_path: Path) -> None:
    script_path = _write_script(tmp_path, "Sabalenka defeated Rybakina 6-4,6-2 in the Final.")
    output_path = tmp_path / "narration.mp3"
    synth = ElevenLabsVoiceSynthesizer(voice_config=_config(), cache_dir=tmp_path / "cache")

    with (
        patch("requests.post") as mock_post,
        patch(
            "wta_daily.voice.elevenlabs_provider.get_or_create_locator", return_value=None
        ),
    ):
        mock_post.return_value = _FakeResponse()
        synth.synthesize(script_path, output_path)

    sent_text = mock_post.call_args.kwargs["json"]["text"]
    assert "6-4" not in sent_text
    assert "six four, six two" in sent_text


def test_synthesize_never_modifies_script_txt_on_disk(tmp_path: Path) -> None:
    original_text = "Sabalenka defeated Rybakina 6-4,6-2 in the Final."
    script_path = _write_script(tmp_path, original_text)
    output_path = tmp_path / "narration.mp3"
    synth = ElevenLabsVoiceSynthesizer(voice_config=_config(), cache_dir=tmp_path / "cache")

    with (
        patch("requests.post") as mock_post,
        patch(
            "wta_daily.voice.elevenlabs_provider.get_or_create_locator", return_value=None
        ),
    ):
        mock_post.return_value = _FakeResponse()
        synth.synthesize(script_path, output_path)

    assert script_path.read_text(encoding="utf-8") == original_text


def test_synthesize_attaches_pronunciation_dictionary_locator_when_available(
    tmp_path: Path,
) -> None:
    script_path = _write_script(tmp_path, "Iga Swiatek advances.")
    output_path = tmp_path / "narration.mp3"
    synth = ElevenLabsVoiceSynthesizer(voice_config=_config(), cache_dir=tmp_path / "cache")

    fake_locator = {"pronunciation_dictionary_id": "dict-1", "version_id": "v-1"}
    with (
        patch("requests.post") as mock_post,
        patch(
            "wta_daily.voice.elevenlabs_provider.get_or_create_locator",
            return_value=fake_locator,
        ) as mock_get_locator,
    ):
        mock_post.return_value = _FakeResponse()
        synth.synthesize(script_path, output_path)

    assert mock_get_locator.called
    sent_payload = mock_post.call_args.kwargs["json"]
    assert sent_payload["pronunciation_dictionary_locators"] == [fake_locator]


def test_synthesize_omits_locator_field_when_dictionary_unavailable(tmp_path: Path) -> None:
    """A pronunciation-dictionary failure must not block synthesis or crash -
    just proceed without the locator field."""

    script_path = _write_script(tmp_path, "Iga Swiatek advances.")
    output_path = tmp_path / "narration.mp3"
    synth = ElevenLabsVoiceSynthesizer(voice_config=_config(), cache_dir=tmp_path / "cache")

    with (
        patch("requests.post") as mock_post,
        patch(
            "wta_daily.voice.elevenlabs_provider.get_or_create_locator", return_value=None
        ),
    ):
        mock_post.return_value = _FakeResponse()
        synth.synthesize(script_path, output_path)

    sent_payload = mock_post.call_args.kwargs["json"]
    assert "pronunciation_dictionary_locators" not in sent_payload
    assert output_path.exists()


def test_synthesize_skips_dictionary_lookup_when_disabled_in_config(tmp_path: Path) -> None:
    script_path = _write_script(tmp_path, "Iga Swiatek advances.")
    output_path = tmp_path / "narration.mp3"
    synth = ElevenLabsVoiceSynthesizer(
        voice_config=_config(pronunciation_dictionary_enabled=False), cache_dir=tmp_path / "cache"
    )

    with (
        patch("requests.post") as mock_post,
        patch("wta_daily.voice.elevenlabs_provider.get_or_create_locator") as mock_get_locator,
    ):
        mock_post.return_value = _FakeResponse()
        synth.synthesize(script_path, output_path)

    mock_get_locator.assert_not_called()
    sent_payload = mock_post.call_args.kwargs["json"]
    assert "pronunciation_dictionary_locators" not in sent_payload


def test_synthesize_writes_audio_bytes_to_output_path(tmp_path: Path) -> None:
    script_path = _write_script(tmp_path, "A quiet script.")
    output_path = tmp_path / "narration.mp3"
    synth = ElevenLabsVoiceSynthesizer(voice_config=_config(), cache_dir=tmp_path / "cache")

    with (
        patch("requests.post") as mock_post,
        patch(
            "wta_daily.voice.elevenlabs_provider.get_or_create_locator", return_value=None
        ),
    ):
        mock_post.return_value = _FakeResponse(content=b"real-fake-audio")
        synth.synthesize(script_path, output_path)

    assert output_path.read_bytes() == b"real-fake-audio"


def test_synthesize_raises_voice_synthesis_error_when_api_key_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("TEST_ELEVENLABS_KEY", raising=False)
    script_path = _write_script(tmp_path, "Some script.")
    # enabled=False so VoiceConfig.resolve_api_key() doesn't itself raise a
    # ConfigurationError for the missing key (that's a separate, pre-existing
    # guard unrelated to this feature) - this exercises synthesize()'s own
    # "no api key resolved" check specifically.
    synth = ElevenLabsVoiceSynthesizer(
        voice_config=_config(enabled=False), cache_dir=tmp_path / "cache"
    )

    with pytest.raises(VoiceSynthesisError):
        synth.synthesize(script_path, tmp_path / "narration.mp3")


def test_synthesize_raises_voice_synthesis_error_on_http_failure(tmp_path: Path) -> None:
    script_path = _write_script(tmp_path, "Some script.")
    synth = ElevenLabsVoiceSynthesizer(voice_config=_config(), cache_dir=tmp_path / "cache")

    with (
        patch("requests.post", side_effect=RuntimeError("network down")),
        patch(
            "wta_daily.voice.elevenlabs_provider.get_or_create_locator", return_value=None
        ),
    ):
        with pytest.raises(VoiceSynthesisError):
            synth.synthesize(script_path, tmp_path / "narration.mp3")
