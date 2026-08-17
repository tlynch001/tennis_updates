"""Unit tests for :mod:`wta_daily.voice.elevenlabs_provider`.

Mocks the outbound HTTP call (never hits the network) to verify: the
"with-timestamps" endpoint's JSON response (base64 audio + alignment) is
decoded correctly, script.txt on disk is never modified, and a
narration_timing.json file is written when a report and alignment are
both available (and gracefully skipped otherwise).
"""

from __future__ import annotations

import base64
import json
from datetime import date
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from wta_daily.config import VoiceConfig
from wta_daily.exceptions import VoiceSynthesisError
from wta_daily.models import DailyReport, Movement, PlayerReport
from wta_daily.voice.elevenlabs_provider import ElevenLabsVoiceSynthesizer


def _alignment_for(text: str, seconds_per_char: float = 0.05) -> dict[str, Any]:
    characters = list(text)
    return {
        "characters": characters,
        "character_start_times_seconds": [i * seconds_per_char for i in range(len(characters))],
        "character_end_times_seconds": [(i + 1) * seconds_per_char for i in range(len(characters))],
    }


class _FakeResponse:
    def __init__(
        self,
        audio_bytes: bytes = b"fake-audio-bytes",
        alignment: dict[str, Any] | None = None,
        status_ok: bool = True,
    ) -> None:
        self._payload = {
            "audio_base64": base64.b64encode(audio_bytes).decode("ascii"),
            "alignment": alignment,
        }
        self._status_ok = status_ok

    def raise_for_status(self) -> None:
        if not self._status_ok:
            raise RuntimeError("simulated HTTP error")

    def json(self) -> dict[str, Any]:
        return self._payload


def _write_script(tmp_path: Path, text: str) -> Path:
    script_path = tmp_path / "script.txt"
    script_path.write_text(text, encoding="utf-8")
    return script_path


def _config(**overrides: Any) -> VoiceConfig:
    base = VoiceConfig(enabled=True, api_key_env="TEST_ELEVENLABS_KEY")
    for key, value in overrides.items():
        setattr(base, key, value)
    return base


def _report(text_for_players: list[str]) -> DailyReport:
    players = [
        PlayerReport(
            rank=i + 1,
            name=name,
            player_id=f"p{i + 1}",
            country_code="USA",
            points=1000 - i,
            movement=Movement.SAME,
        )
        for i, name in enumerate(text_for_players)
    ]
    return DailyReport(report_date=date(2026, 8, 16), tour="wta", players=players)


@pytest.fixture(autouse=True)
def _api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEST_ELEVENLABS_KEY", "fake-key")


def test_synthesize_uses_the_with_timestamps_endpoint(tmp_path: Path) -> None:
    script_path = _write_script(tmp_path, "A quiet script.")
    output_path = tmp_path / "narration.mp3"
    synth = ElevenLabsVoiceSynthesizer(voice_config=_config())

    with patch("requests.post") as mock_post:
        mock_post.return_value = _FakeResponse()
        synth.synthesize(script_path, output_path)

    called_url = mock_post.call_args.args[0]
    assert called_url.endswith("/with-timestamps")


def test_synthesize_never_modifies_script_txt_on_disk(tmp_path: Path) -> None:
    original_text = "Some narration text."
    script_path = _write_script(tmp_path, original_text)
    output_path = tmp_path / "narration.mp3"
    synth = ElevenLabsVoiceSynthesizer(voice_config=_config())

    with patch("requests.post") as mock_post:
        mock_post.return_value = _FakeResponse()
        synth.synthesize(script_path, output_path)

    assert script_path.read_text(encoding="utf-8") == original_text


def test_synthesize_decodes_base64_audio_to_the_output_path(tmp_path: Path) -> None:
    script_path = _write_script(tmp_path, "A quiet script.")
    output_path = tmp_path / "narration.mp3"
    synth = ElevenLabsVoiceSynthesizer(voice_config=_config())

    with patch("requests.post") as mock_post:
        mock_post.return_value = _FakeResponse(audio_bytes=b"real-fake-audio")
        synth.synthesize(script_path, output_path)

    assert output_path.read_bytes() == b"real-fake-audio"


def test_synthesize_raises_voice_synthesis_error_when_api_key_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("TEST_ELEVENLABS_KEY", raising=False)
    script_path = _write_script(tmp_path, "Some script.")
    # enabled=False so VoiceConfig.resolve_api_key() doesn't itself raise a
    # ConfigurationError for the missing key - this exercises synthesize()'s
    # own "no api key resolved" check specifically.
    synth = ElevenLabsVoiceSynthesizer(voice_config=_config(enabled=False))

    with pytest.raises(VoiceSynthesisError):
        synth.synthesize(script_path, tmp_path / "narration.mp3")


def test_synthesize_raises_voice_synthesis_error_on_http_failure(tmp_path: Path) -> None:
    script_path = _write_script(tmp_path, "Some script.")
    synth = ElevenLabsVoiceSynthesizer(voice_config=_config())

    with patch("requests.post", side_effect=RuntimeError("network down")):
        with pytest.raises(VoiceSynthesisError):
            synth.synthesize(script_path, tmp_path / "narration.mp3")


# --- Narration timing metadata -----------------------------------------------


def test_synthesize_writes_timing_file_when_report_and_alignment_are_available(
    tmp_path: Path,
) -> None:
    script_text = (
        "Welcome to today's update.\n\n"
        "Player One is ranked number 1 today, and did not play yesterday.\n\n"
        "Thanks for watching."
    )
    script_path = _write_script(tmp_path, script_text)
    output_path = tmp_path / "narration.mp3"
    synth = ElevenLabsVoiceSynthesizer(voice_config=_config())
    report = _report(["Player One"])

    with patch("requests.post") as mock_post:
        mock_post.return_value = _FakeResponse(alignment=_alignment_for(script_text))
        synth.synthesize(script_path, output_path, report=report)

    timing_path = output_path.with_name("narration_timing.json")
    assert timing_path.exists()
    payload = json.loads(timing_path.read_text())
    kinds = [s["kind"] for s in payload["segments"]]
    assert kinds == ["intro", "player", "closer"]


def test_synthesize_skips_timing_file_when_report_is_not_provided(tmp_path: Path) -> None:
    script_text = "Welcome to today's update.\n\nPlayer One is ranked number 1.\n\nThanks for watching."
    script_path = _write_script(tmp_path, script_text)
    output_path = tmp_path / "narration.mp3"
    synth = ElevenLabsVoiceSynthesizer(voice_config=_config())

    with patch("requests.post") as mock_post:
        mock_post.return_value = _FakeResponse(alignment=_alignment_for(script_text))
        synth.synthesize(script_path, output_path)  # no report=

    assert not output_path.with_name("narration_timing.json").exists()
    assert output_path.exists()  # narration itself still succeeds


def test_synthesize_skips_timing_file_when_alignment_is_missing(tmp_path: Path) -> None:
    script_text = "Welcome to today's update.\n\nPlayer One is ranked number 1.\n\nThanks for watching."
    script_path = _write_script(tmp_path, script_text)
    output_path = tmp_path / "narration.mp3"
    synth = ElevenLabsVoiceSynthesizer(voice_config=_config())
    report = _report(["Player One"])

    with patch("requests.post") as mock_post:
        mock_post.return_value = _FakeResponse(alignment=None)
        synth.synthesize(script_path, output_path, report=report)

    assert not output_path.with_name("narration_timing.json").exists()
    assert output_path.exists()


def test_synthesize_timing_failure_does_not_break_narration(tmp_path: Path) -> None:
    """A bug/edge case while computing timing must never take down the
    narration synthesis that already succeeded."""

    script_text = "Welcome to today's update.\n\nPlayer One is ranked number 1.\n\nThanks for watching."
    script_path = _write_script(tmp_path, script_text)
    output_path = tmp_path / "narration.mp3"
    synth = ElevenLabsVoiceSynthesizer(voice_config=_config())
    report = _report(["Player One"])

    with (
        patch("requests.post") as mock_post,
        patch(
            "wta_daily.voice.elevenlabs_provider.compute_segment_timings",
            side_effect=RuntimeError("simulated bug"),
        ),
    ):
        mock_post.return_value = _FakeResponse(alignment=_alignment_for(script_text))
        result_path = synth.synthesize(script_path, output_path, report=report)

    assert result_path == output_path
    assert output_path.exists()
