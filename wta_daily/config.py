"""Configuration loading.

All tunable behavior lives in a single YAML file (see
``config/config.example.yaml``) so the pipeline never needs source changes to
change the top-N cutoff, output paths, video resolution, voice, data
provider, tournament preferences, or theme colors.

Secrets (API keys) are **never** stored in the YAML file. Instead, the YAML
references an environment variable name (e.g. ``api_key_env: ELEVENLABS_API_KEY``)
and this module resolves the actual value from the process environment (which
in turn may have been populated from a local, git-ignored ``.env`` file via
python-dotenv, or from real environment variables/secrets in CI).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import yaml

from wta_daily.exceptions import ConfigurationError

try:  # pragma: no cover - optional convenience dependency
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None  # type: ignore[assignment]


def _get_secret(env_var: str | None, *, required: bool = False) -> str | None:
    if not env_var:
        return None
    value = os.environ.get(env_var)
    if required and not value:
        raise ConfigurationError(
            f"Environment variable '{env_var}' is not set. Add it to your shell "
            f"environment or to a local .env file (see .env.example); never hardcode "
            f"secrets in the config file."
        )
    return value


@dataclass
class ProviderConfig:
    """Generic ``{name, options}`` block used for every pluggable component."""

    name: str
    options: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, data: dict[str, Any] | None, *, default_name: str) -> ProviderConfig:
        data = data or {}
        name = data.get("provider", default_name)
        options = {k: v for k, v in data.items() if k != "provider"}
        return cls(name=name, options=options)


@dataclass
class NetworkConfig:
    timeout_seconds: float = 15.0
    max_retries: int = 3
    backoff_factor: float = 1.5
    user_agent: str = "wta-daily/0.1 (+https://github.com/)"

    @classmethod
    def from_mapping(cls, data: dict[str, Any] | None) -> NetworkConfig:
        data = data or {}
        return cls(
            timeout_seconds=float(data.get("timeout_seconds", 15.0)),
            max_retries=int(data.get("max_retries", 3)),
            backoff_factor=float(data.get("backoff_factor", 1.5)),
            user_agent=str(data.get("user_agent", cls.user_agent)),
        )


@dataclass
class ThemeConfig:
    background_color: str = "#0B0F19"
    panel_color: str = "#141B2D"
    accent_color: str = "#00E0C6"
    text_color: str = "#F5F7FA"
    subtext_color: str = "#9AA5B1"
    up_color: str = "#2ECC71"
    down_color: str = "#E74C3C"
    same_color: str = "#9AA5B1"
    font_bold: str | None = None
    font_regular: str | None = None

    @classmethod
    def from_mapping(cls, data: dict[str, Any] | None) -> ThemeConfig:
        data = data or {}
        defaults = cls()
        return cls(
            background_color=data.get("background_color", defaults.background_color),
            panel_color=data.get("panel_color", defaults.panel_color),
            accent_color=data.get("accent_color", defaults.accent_color),
            text_color=data.get("text_color", defaults.text_color),
            subtext_color=data.get("subtext_color", defaults.subtext_color),
            up_color=data.get("up_color", defaults.up_color),
            down_color=data.get("down_color", defaults.down_color),
            same_color=data.get("same_color", defaults.same_color),
            font_bold=data.get("font_bold"),
            font_regular=data.get("font_regular"),
        )


@dataclass
class GraphicsConfig:
    renderer: str = "pillow"
    width: int = 1920
    height: int = 1080
    theme: ThemeConfig = field(default_factory=ThemeConfig)

    @classmethod
    def from_mapping(cls, data: dict[str, Any] | None) -> GraphicsConfig:
        data = data or {}
        return cls(
            renderer=data.get("renderer", "pillow"),
            width=int(data.get("width", 1920)),
            height=int(data.get("height", 1080)),
            theme=ThemeConfig.from_mapping(data.get("theme")),
        )


@dataclass
class VoiceConfig:
    enabled: bool = False
    provider: str = "elevenlabs"
    voice_id: str = "21m00Tcm4TlvDq8ikWAM"
    model_id: str = "eleven_multilingual_v2"
    stability: float = 0.5
    similarity_boost: float = 0.75
    api_key_env: str = "ELEVENLABS_API_KEY"

    @classmethod
    def from_mapping(cls, data: dict[str, Any] | None) -> VoiceConfig:
        data = data or {}
        defaults = cls()
        return cls(
            enabled=bool(data.get("enabled", defaults.enabled)),
            provider=data.get("provider", defaults.provider),
            voice_id=data.get("voice_id", defaults.voice_id),
            model_id=data.get("model_id", defaults.model_id),
            stability=float(data.get("stability", defaults.stability)),
            similarity_boost=float(data.get("similarity_boost", defaults.similarity_boost)),
            api_key_env=data.get("api_key_env", defaults.api_key_env),
        )

    def resolve_api_key(self) -> str | None:
        return _get_secret(self.api_key_env, required=self.enabled)


@dataclass
class VideoConfig:
    enabled: bool = False
    assembler: str = "ffmpeg"
    width: int = 1920
    height: int = 1080
    fps: int = 30
    background_music_path: str | None = None
    seconds_per_player_card: float = 6.0

    @classmethod
    def from_mapping(cls, data: dict[str, Any] | None) -> VideoConfig:
        data = data or {}
        defaults = cls()
        return cls(
            enabled=bool(data.get("enabled", defaults.enabled)),
            assembler=data.get("assembler", defaults.assembler),
            width=int(data.get("width", defaults.width)),
            height=int(data.get("height", defaults.height)),
            fps=int(data.get("fps", defaults.fps)),
            background_music_path=data.get("background_music_path"),
            seconds_per_player_card=float(
                data.get("seconds_per_player_card", defaults.seconds_per_player_card)
            ),
        )


@dataclass
class GitConfig:
    auto_commit: bool = False
    auto_push: bool = False
    remote: str = "origin"
    branch: str | None = None
    commit_message_template: str = "Daily WTA Update {date}"

    @classmethod
    def from_mapping(cls, data: dict[str, Any] | None) -> GitConfig:
        data = data or {}
        defaults = cls()
        return cls(
            auto_commit=bool(data.get("auto_commit", defaults.auto_commit)),
            auto_push=bool(data.get("auto_push", defaults.auto_push)),
            remote=data.get("remote", defaults.remote),
            branch=data.get("branch"),
            commit_message_template=data.get(
                "commit_message_template", defaults.commit_message_template
            ),
        )


@dataclass
class ScriptConfig:
    generator: str = "template"
    target_minutes_low: float = 5.0
    target_minutes_high: float = 8.0
    words_per_minute: int = 150
    openai_model: str = "gpt-4o-mini"
    openai_api_key_env: str = "OPENAI_API_KEY"

    @classmethod
    def from_mapping(cls, data: dict[str, Any] | None) -> ScriptConfig:
        data = data or {}
        defaults = cls()
        return cls(
            generator=data.get("generator", defaults.generator),
            target_minutes_low=float(data.get("target_minutes_low", defaults.target_minutes_low)),
            target_minutes_high=float(
                data.get("target_minutes_high", defaults.target_minutes_high)
            ),
            words_per_minute=int(data.get("words_per_minute", defaults.words_per_minute)),
            openai_model=data.get("openai_model", defaults.openai_model),
            openai_api_key_env=data.get("openai_api_key_env", defaults.openai_api_key_env),
        )


@dataclass
class AppConfig:
    """The fully-resolved application configuration."""

    tour: str = "wta"
    top_n: int = 10
    data_dir: Path = Path("data")
    output_dir: Path = Path("output")
    log_dir: Path = Path("logs")
    rankings_provider: ProviderConfig = field(
        default_factory=lambda: ProviderConfig(name="wta_official")
    )
    match_provider: ProviderConfig = field(
        default_factory=lambda: ProviderConfig(name="wta_official")
    )
    network: NetworkConfig = field(default_factory=NetworkConfig)
    script: ScriptConfig = field(default_factory=ScriptConfig)
    graphics: GraphicsConfig = field(default_factory=GraphicsConfig)
    voice: VoiceConfig = field(default_factory=VoiceConfig)
    video: VideoConfig = field(default_factory=VideoConfig)
    git: GitConfig = field(default_factory=GitConfig)
    tournament_preferences: list[str] = field(default_factory=list)

    @classmethod
    def from_mapping(cls, data: dict[str, Any]) -> AppConfig:
        defaults = cls()
        return cls(
            tour=data.get("tour", defaults.tour),
            top_n=int(data.get("top_n", defaults.top_n)),
            data_dir=Path(data.get("data_dir", defaults.data_dir)),
            output_dir=Path(data.get("output_dir", defaults.output_dir)),
            log_dir=Path(data.get("log_dir", defaults.log_dir)),
            rankings_provider=ProviderConfig.from_mapping(
                data.get("rankings_provider"), default_name="wta_official"
            ),
            match_provider=ProviderConfig.from_mapping(
                data.get("match_provider"), default_name="wta_official"
            ),
            network=NetworkConfig.from_mapping(data.get("network")),
            script=ScriptConfig.from_mapping(data.get("script")),
            graphics=GraphicsConfig.from_mapping(data.get("graphics")),
            voice=VoiceConfig.from_mapping(data.get("voice")),
            video=VideoConfig.from_mapping(data.get("video")),
            git=GitConfig.from_mapping(data.get("git")),
            tournament_preferences=list(data.get("tournament_preferences", [])),
        )

    def output_dir_for(self, day: date) -> Path:
        return self.output_dir / day.isoformat()


def load_config(path: str | Path, *, dotenv_path: str | Path | None = None) -> AppConfig:
    """Load and validate an :class:`AppConfig` from a YAML file.

    Also loads a ``.env`` file (if python-dotenv is installed and the file
    exists) so that ``api_key_env`` references resolve during local
    development without exporting variables manually.
    """

    if load_dotenv is not None:
        env_file = Path(dotenv_path) if dotenv_path else Path(".env")
        if env_file.exists():
            load_dotenv(env_file)

    config_path = Path(path)
    if not config_path.exists():
        raise ConfigurationError(f"Config file not found: {config_path}")

    with config_path.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}

    if not isinstance(raw, dict):
        raise ConfigurationError(f"Config file {config_path} must contain a YAML mapping.")

    try:
        return AppConfig.from_mapping(raw)
    except (TypeError, ValueError) as exc:
        raise ConfigurationError(f"Invalid configuration in {config_path}: {exc}") from exc
