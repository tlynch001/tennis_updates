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


def test_rankings_config_projected_disabled_by_default(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text("top_n: 10\n", encoding="utf-8")

    config = load_config(config_path)

    assert config.rankings.projected_rankings_enabled is False


def test_rankings_config_projected_enabled_raises(tmp_path: Path) -> None:
    """Projected/live rankings are a reserved future feature, not yet
    implemented - enabling the flag must fail loudly, never silently do
    nothing."""

    config_path = tmp_path / "config.yaml"
    config_path.write_text("rankings:\n  projected_rankings_enabled: true\n", encoding="utf-8")

    with pytest.raises(ConfigurationError, match="not implemented"):
        load_config(config_path)


def test_tournament_status_enabled_by_default(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text("top_n: 10\n", encoding="utf-8")

    config = load_config(config_path)

    assert config.tournament_status.enabled is True
    assert config.tournament_status.previous_year_lookback_enabled is True
    assert config.tournament_status.points_table_path == "data/wta_points_table.yaml"


def test_tournament_status_can_be_disabled(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "tournament_status:\n  enabled: false\n  previous_year_lookback_enabled: false\n",
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.tournament_status.enabled is False
    assert config.tournament_status.previous_year_lookback_enabled is False


def test_tournament_status_custom_points_table_path(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "tournament_status:\n  points_table_path: data/custom_points.yaml\n", encoding="utf-8"
    )

    config = load_config(config_path)

    assert config.tournament_status.points_table_path == "data/custom_points.yaml"


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


def test_example_config_remains_a_valid_wta_production_config() -> None:
    config = load_config(Path("config/config.example.yaml"))

    assert config.tour == "wta"
    assert config.tour_profile.key == "wta"
    assert config.tour_profile.display_name == "WTA"
    assert config.rankings_provider.name == "wta_official"
    assert config.git.commit_message_template == "Daily WTA Update {date}"


def test_unknown_tour_is_rejected(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text("tour: itf\n", encoding="utf-8")

    with pytest.raises(ConfigurationError, match="Unknown tour"):
        load_config(config_path)


def test_atp_tour_with_default_wta_official_providers_is_rejected(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text("tour: atp\n", encoding="utf-8")

    with pytest.raises(ConfigurationError, match="WTA-only"):
        load_config(config_path)


def test_atp_tour_with_explicit_wta_official_rankings_is_rejected(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "tour: atp\n"
        "rankings_provider:\n  provider: wta_official\n"
        "match_provider:\n  provider: sample\n",
        encoding="utf-8",
    )

    with pytest.raises(ConfigurationError, match="WTA-only"):
        load_config(config_path)


def test_atp_tour_with_best_of_default_sources_is_rejected(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "tour: atp\n"
        "rankings_provider:\n  provider: sample\n"
        "match_provider:\n  provider: best_of\n",
        encoding="utf-8",
    )

    with pytest.raises(ConfigurationError, match="WTA-only"):
        load_config(config_path)


def test_atp_tour_with_api_tennis_match_provider_is_rejected(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "tour: atp\n"
        "rankings_provider:\n  provider: sample\n"
        "match_provider:\n  provider: api_tennis\n",
        encoding="utf-8",
    )

    with pytest.raises(ConfigurationError, match="WTA-only"):
        load_config(config_path)


def test_atp_tour_with_best_of_api_tennis_source_is_rejected(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "tour: atp\n"
        "rankings_provider:\n  provider: sample\n"
        "match_provider:\n  provider: best_of\n"
        "  sources:\n"
        "    - provider: live_tennis_api\n"
        "    - provider: api_tennis\n",
        encoding="utf-8",
    )

    with pytest.raises(ConfigurationError, match="WTA-only"):
        load_config(config_path)


def test_wta_tour_with_api_tennis_match_provider_is_accepted(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "tour: wta\n"
        "rankings_provider:\n  provider: sample\n"
        "match_provider:\n  provider: api_tennis\n",
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.tour == "wta"
    assert config.match_provider.name == "api_tennis"


def test_atp_tour_with_sample_providers_is_allowed_for_presentation(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "tour: atp\n"
        "rankings_provider:\n  provider: sample\n"
        "match_provider:\n  provider: sample\n",
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.tour == "atp"
    assert config.tour_profile.display_name == "ATP"
    assert config.tour_profile.subject == "he"
    assert config.git.commit_message_template == "Daily ATP Update {date}"


def test_wta_explicit_commit_template_is_unchanged(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        'tour: wta\ngit:\n  commit_message_template: "Daily WTA Update {date}"\n',
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.git.commit_message_template == "Daily WTA Update {date}"

