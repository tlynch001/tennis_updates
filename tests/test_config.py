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
    assert config.rankings_pool_size == 25


def test_load_config_reads_rankings_pool_size(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text("top_n: 10\nrankings_pool_size: 50\n", encoding="utf-8")

    config = load_config(config_path)

    assert config.rankings_pool_size == 50


def test_featured_player_disabled_by_default(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text("top_n: 10\n", encoding="utf-8")

    config = load_config(config_path)

    assert config.featured_player.enabled is False
    assert config.featured_player.tagline == "america_favorite"


def test_featured_player_reads_full_block(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "featured_player:\n"
        "  enabled: true\n"
        "  player_id: '325410'\n"
        "  name: Emma Navarro\n"
        "  tagline: america_favorite\n",
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.featured_player.enabled is True
    assert config.featured_player.player_id == "325410"
    assert config.featured_player.name == "Emma Navarro"
    assert config.featured_player.tagline == "america_favorite"


def test_featured_player_enabled_without_player_id_raises(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "featured_player:\n  enabled: true\n  name: Emma Navarro\n", encoding="utf-8"
    )

    with pytest.raises(ConfigurationError):
        load_config(config_path)


def test_featured_player_enabled_without_name_raises(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "featured_player:\n  enabled: true\n  player_id: '325410'\n", encoding="utf-8"
    )

    with pytest.raises(ConfigurationError):
        load_config(config_path)


def test_publishing_config_enabled_by_default(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text("top_n: 10\n", encoding="utf-8")

    config = load_config(config_path)

    assert config.publishing.thumbnail_enabled is True
    assert config.publishing.description_enabled is True


def test_publishing_config_can_be_disabled_independently(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text("publishing:\n  thumbnail_enabled: false\n", encoding="utf-8")

    config = load_config(config_path)

    assert config.publishing.thumbnail_enabled is False
    assert config.publishing.description_enabled is True


def test_youtube_disabled_by_default(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text("top_n: 10\n", encoding="utf-8")

    config = load_config(config_path)

    assert config.youtube.enabled is False
    assert config.youtube.privacy == "unlisted"
    assert config.youtube.category_id == "17"
    assert config.youtube.client_secret_path == Path("secrets/youtube_client_secret.json")
    assert config.youtube.token_path == Path("secrets/youtube_token.json")


def test_youtube_reads_full_block(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "youtube:\n"
        "  enabled: true\n"
        "  privacy: private\n"
        "  category_id: '22'\n"
        "  client_secret_path: secrets/custom_secret.json\n"
        "  token_path: secrets/custom_token.json\n",
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.youtube.enabled is True
    assert config.youtube.privacy == "private"
    assert config.youtube.category_id == "22"
    assert config.youtube.client_secret_path == Path("secrets/custom_secret.json")
    assert config.youtube.token_path == Path("secrets/custom_token.json")


def test_youtube_rejects_invalid_privacy_value(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text("youtube:\n  privacy: everyone\n", encoding="utf-8")

    with pytest.raises(ConfigurationError):
        load_config(config_path)


def test_voice_config_requires_env_var_when_enabled(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text("voice:\n  enabled: true\n  api_key_env: MY_TEST_KEY\n", encoding="utf-8")
    config = load_config(config_path)

    monkeypatch.delenv("MY_TEST_KEY", raising=False)
    with pytest.raises(ConfigurationError):
        config.voice.resolve_api_key()

    monkeypatch.setenv("MY_TEST_KEY", "secret-value")
    assert config.voice.resolve_api_key() == "secret-value"
