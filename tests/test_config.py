from __future__ import annotations

from pathlib import Path

import pytest

from wta_daily.config import load_config
from wta_daily.exceptions import ConfigurationError

MINIMAL_CONFIG = """
tour: wta
top_n: 5
data_dir: data
output_dir: output
rankings_provider:
  provider: sample
match_provider:
  provider: sample
voice:
  enabled: false
"""


def test_load_config_parses_minimal_yaml(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(MINIMAL_CONFIG, encoding="utf-8")

    config = load_config(config_path)

    assert config.tour == "wta"
    assert config.top_n == 5
    assert config.rankings_provider.name == "sample"
    assert config.match_provider.name == "sample"
    assert config.voice.enabled is False


def test_load_config_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(ConfigurationError):
        load_config(tmp_path / "does-not-exist.yaml")


def test_load_config_applies_defaults_for_missing_sections(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text("top_n: 10\n", encoding="utf-8")

    config = load_config(config_path)

    assert config.tour == "wta"
    assert config.graphics.width == 1920
    assert config.graphics.height == 1080
    assert config.video.enabled is False


def test_voice_config_requires_env_var_when_enabled(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "voice:\n  enabled: true\n  api_key_env: MY_TEST_KEY\n", encoding="utf-8"
    )
    config = load_config(config_path)

    monkeypatch.delenv("MY_TEST_KEY", raising=False)
    with pytest.raises(ConfigurationError):
        config.voice.resolve_api_key()

    monkeypatch.setenv("MY_TEST_KEY", "secret-value")
    assert config.voice.resolve_api_key() == "secret-value"
