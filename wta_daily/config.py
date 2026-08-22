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
from wta_daily.tour import WTA, TourProfile, assert_tour_providers_compatible, profile_for

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
    commit_message_template: str = WTA.git_commit_message_template

    @classmethod
    def from_mapping(
        cls,
        data: dict[str, Any] | None,
        *,
        default_commit_message_template: str | None = None,
    ) -> GitConfig:
        data = data or {}
        defaults = cls()
        template_default = default_commit_message_template or defaults.commit_message_template
        return cls(
            auto_commit=bool(data.get("auto_commit", defaults.auto_commit)),
            auto_push=bool(data.get("auto_push", defaults.auto_push)),
            remote=data.get("remote", defaults.remote),
            branch=data.get("branch"),
            commit_message_template=data.get("commit_message_template", template_default),
        )


@dataclass
class FeaturedPlayerConfig:
    """A recurring, editorially-flavored spotlight on one specific player,
    layered on top of - never mixed into - the official Top N report.

    Disabled by default. Every *fact* reported for this player (rank,
    points, movement, match) comes from exactly the same
    :class:`~wta_daily.plugins.base.RankingsProvider` /
    :class:`~wta_daily.plugins.base.MatchProvider` architecture used for the
    Top N - this config block only names *which* player and *which*
    narration personality (``tagline``) to use; it never bypasses or
    duplicates the data layer. See
    :mod:`wta_daily.scripts_gen.featured_player_phrases` for the currently
    shipped ``"america_favorite"`` personality (tuned for Emma Navarro, but
    not Emma-specific by name - a future featured player could reuse it, or
    a different ``tagline`` could select a different phrase module).
    """

    enabled: bool = False
    player_id: str = ""
    name: str = ""
    tagline: str = "america_favorite"

    @classmethod
    def from_mapping(cls, data: dict[str, Any] | None) -> FeaturedPlayerConfig:
        data = data or {}
        defaults = cls()
        config = cls(
            enabled=bool(data.get("enabled", defaults.enabled)),
            player_id=str(data.get("player_id", defaults.player_id)),
            name=str(data.get("name", defaults.name)),
            tagline=str(data.get("tagline", defaults.tagline)),
        )
        if config.enabled and not (config.player_id and config.name):
            raise ConfigurationError(
                "featured_player.enabled is true but 'player_id' and/or 'name' is not set - "
                "both are required so the pipeline knows exactly who to look up."
            )
        return config


@dataclass
class RankingsConfig:
    """Settings governing how the official WTA ranking is interpreted -
    kept separate from ``rankings_provider`` (which selects *where* rankings
    come from) since this block is about how the app *treats* whatever a
    provider returns.

    ``projected_rankings_enabled`` is a placeholder for a genuinely
    different, future concept: a "live"/"projected" ranking that estimates
    where a player might land on the *next* official list based on points
    being earned in an ongoing tournament. That is deliberately **not**
    implemented yet (it would need real logic to estimate provisional
    points from in-progress tournament results, which the current data
    layer doesn't provide) - this flag exists purely so the config schema
    has an explicit, discoverable place for it, and so enabling it fails
    loudly rather than silently doing nothing. See the README's "Official
    ranking vs. daily match activity" section. Must stay ``False``.
    """

    projected_rankings_enabled: bool = False

    @classmethod
    def from_mapping(cls, data: dict[str, Any] | None) -> RankingsConfig:
        data = data or {}
        defaults = cls()
        config = cls(
            projected_rankings_enabled=bool(
                data.get("projected_rankings_enabled", defaults.projected_rankings_enabled)
            )
        )
        if config.projected_rankings_enabled:
            raise ConfigurationError(
                "rankings.projected_rankings_enabled is true, but projected/live rankings are "
                "not implemented yet - this is a reserved placeholder for a future feature. "
                "Set it back to false. Official rankings (rankings_provider) are unaffected by "
                "this setting."
            )
        return config


@dataclass
class TournamentStatusConfig:
    """Settings for the tournament-elimination narration context (see the
    README's "Tournament elimination context" section): when a Top N or
    featured player has been eliminated from (or has won) her current
    tournament, narration can mention the round she reached, the official
    ranking points that earned her, and - when reliably available - how
    that compares with her result at the same tournament last year.

    On by default - only a match provider with genuine tournament-draw
    visibility (``wta_official``) ever populates this; every other
    provider leaves it at "unknown" automatically, so leaving this `true`
    has no effect at all unless you're using a provider that supports it.

    ``previous_year_lookback_enabled`` can be turned off on its own to
    keep the elimination/points context while skipping the extra
    previous-year lookup call entirely (made only for players who are
    actually eliminated or champions this run, which is normally a
    handful at most - see the README's "API-call impact" note).
    """

    enabled: bool = True
    previous_year_lookback_enabled: bool = True
    points_table_path: str = "data/wta_points_table.yaml"

    @classmethod
    def from_mapping(cls, data: dict[str, Any] | None) -> TournamentStatusConfig:
        data = data or {}
        defaults = cls()
        return cls(
            enabled=bool(data.get("enabled", defaults.enabled)),
            previous_year_lookback_enabled=bool(
                data.get("previous_year_lookback_enabled", defaults.previous_year_lookback_enabled)
            ),
            points_table_path=str(data.get("points_table_path", defaults.points_table_path)),
        )


@dataclass
class PublishingConfig:
    """YouTube-adjacent artifacts generated alongside the rest of the daily
    output: ``thumbnail.png`` and ``youtube_description.txt`` (see the
    README's "YouTube publishing assets" section).

    Both are on by default - they're built entirely from data already
    fetched for the day's report, so there's no extra cost to producing
    them, unlike the optional Phase 2 features (voice/video) that call
    paid external services. Each can still be disabled independently for
    anyone who doesn't want one of them.
    """

    thumbnail_enabled: bool = True
    description_enabled: bool = True

    @classmethod
    def from_mapping(cls, data: dict[str, Any] | None) -> PublishingConfig:
        data = data or {}
        defaults = cls()
        return cls(
            thumbnail_enabled=bool(data.get("thumbnail_enabled", defaults.thumbnail_enabled)),
            description_enabled=bool(data.get("description_enabled", defaults.description_enabled)),
        )


_VALID_YOUTUBE_PRIVACY_STATUSES = frozenset({"private", "unlisted", "public"})


@dataclass
class YouTubeConfig:
    """Optional Phase 3: publishing the finished ``video.mp4`` to YouTube via
    the official YouTube Data API v3 (never Selenium/browser automation).

    ``enabled`` is ``False`` by default and MUST stay that way unless a
    caller deliberately opts in - see :mod:`wta_daily.youtube`'s package
    docstring for the guarantee this implies: while disabled, no Google
    library import is required, no OAuth credential file is ever read, no
    network call to Google is made, and no upload is attempted, so the
    rest of the application (and anyone who hasn't set up Google Cloud
    credentials at all) behaves exactly as it did before this feature
    existed.

    ``client_secret_path``/``token_path`` are *locations* of secret files,
    not secrets themselves - unlike ``VoiceConfig.api_key_env`` (a single
    bearer key resolved from the environment), OAuth needs a small JSON
    client-secret file plus a locally-cached, auto-refreshing token file.
    Both default to a git-ignored ``secrets/`` directory (see
    ``.gitignore`` and the README's "YouTube publishing" section for the
    one-time Google Cloud setup that produces the client-secret file).
    """

    enabled: bool = False
    privacy: str = "unlisted"
    category_id: str = "17"  # YouTube category id 17 = Sports
    client_secret_path: Path = Path("secrets/youtube_client_secret.json")
    token_path: Path = Path("secrets/youtube_token.json")

    @classmethod
    def from_mapping(cls, data: dict[str, Any] | None) -> YouTubeConfig:
        data = data or {}
        defaults = cls()
        privacy = str(data.get("privacy", defaults.privacy))
        if privacy not in _VALID_YOUTUBE_PRIVACY_STATUSES:
            raise ConfigurationError(
                f"youtube.privacy must be one of {sorted(_VALID_YOUTUBE_PRIVACY_STATUSES)}, got {privacy!r}."
            )
        return cls(
            enabled=bool(data.get("enabled", defaults.enabled)),
            privacy=privacy,
            category_id=str(data.get("category_id", defaults.category_id)),
            client_secret_path=Path(data.get("client_secret_path", defaults.client_secret_path)),
            token_path=Path(data.get("token_path", defaults.token_path)),
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
    #: How many players to actually request in the single rankings API call
    #: each run (the response is then sliced down to `top_n` for the
    #: report). Deliberately >= top_n so a modest amount of headroom (e.g.
    #: Top 25 for a Top 10 report) is fetched "for free" in that same
    #: request, available for future needs (featured-player lookups,
    #: broader movement comparisons) without ever issuing a second rankings
    #: request. Effective pool size is always at least `top_n`. See the
    #: README's "Understanding API usage" section.
    rankings_pool_size: int = 25
    data_dir: Path = Path("data")
    output_dir: Path = Path("output")
    log_dir: Path = Path("logs")
    #: How many days before `report_date` counts as "the day we're reporting
    #: results for" (1 = yesterday, UTC). Matches are looked up for exactly
    #: this date - a player who didn't play that day is reported as
    #: `played: false`, never substituted with an older result. See the
    #: README's "Match-data reliability" section for why this replaced a
    #: per-player "latest known match regardless of date" approach.
    match_target_date_offset_days: int = 1
    rankings_provider: ProviderConfig = field(
        default_factory=lambda: ProviderConfig(name="wta_official")
    )
    match_provider: ProviderConfig = field(
        default_factory=lambda: ProviderConfig(name="wta_official")
    )
    featured_player: FeaturedPlayerConfig = field(default_factory=FeaturedPlayerConfig)
    rankings: RankingsConfig = field(default_factory=RankingsConfig)
    tournament_status: TournamentStatusConfig = field(default_factory=TournamentStatusConfig)
    network: NetworkConfig = field(default_factory=NetworkConfig)
    script: ScriptConfig = field(default_factory=ScriptConfig)
    graphics: GraphicsConfig = field(default_factory=GraphicsConfig)
    voice: VoiceConfig = field(default_factory=VoiceConfig)
    video: VideoConfig = field(default_factory=VideoConfig)
    git: GitConfig = field(default_factory=GitConfig)
    publishing: PublishingConfig = field(default_factory=PublishingConfig)
    youtube: YouTubeConfig = field(default_factory=YouTubeConfig)
    tournament_preferences: list[str] = field(default_factory=list)

    @property
    def tour_profile(self) -> TourProfile:
        """Presentation profile selected from :attr:`tour`."""

        return profile_for(self.tour)

    @classmethod
    def from_mapping(cls, data: dict[str, Any]) -> AppConfig:
        defaults = cls()
        tour = data.get("tour", defaults.tour)
        profile = profile_for(tour)
        rankings_provider = ProviderConfig.from_mapping(
            data.get("rankings_provider"), default_name="wta_official"
        )
        match_provider = ProviderConfig.from_mapping(
            data.get("match_provider"), default_name="wta_official"
        )
        assert_tour_providers_compatible(
            tour,
            rankings_provider_name=rankings_provider.name,
            match_provider_name=match_provider.name,
            match_provider_options=match_provider.options,
        )
        return cls(
            tour=tour,
            top_n=int(data.get("top_n", defaults.top_n)),
            rankings_pool_size=int(data.get("rankings_pool_size", defaults.rankings_pool_size)),
            data_dir=Path(data.get("data_dir", defaults.data_dir)),
            output_dir=Path(data.get("output_dir", defaults.output_dir)),
            log_dir=Path(data.get("log_dir", defaults.log_dir)),
            match_target_date_offset_days=int(
                data.get("match_target_date_offset_days", defaults.match_target_date_offset_days)
            ),
            rankings_provider=rankings_provider,
            match_provider=match_provider,
            featured_player=FeaturedPlayerConfig.from_mapping(data.get("featured_player")),
            rankings=RankingsConfig.from_mapping(data.get("rankings")),
            tournament_status=TournamentStatusConfig.from_mapping(data.get("tournament_status")),
            network=NetworkConfig.from_mapping(data.get("network")),
            script=ScriptConfig.from_mapping(data.get("script")),
            graphics=GraphicsConfig.from_mapping(data.get("graphics")),
            voice=VoiceConfig.from_mapping(data.get("voice")),
            video=VideoConfig.from_mapping(data.get("video")),
            git=GitConfig.from_mapping(
                data.get("git"),
                default_commit_message_template=profile.git_commit_message_template,
            ),
            publishing=PublishingConfig.from_mapping(data.get("publishing")),
            youtube=YouTubeConfig.from_mapping(data.get("youtube")),
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
