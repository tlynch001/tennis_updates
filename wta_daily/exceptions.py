"""Custom exception hierarchy used across the pipeline.

Keeping these distinct (instead of raising bare ``Exception``/``ValueError``)
lets the pipeline decide, per error type, whether a failure should abort the
whole run (e.g. rankings could not be fetched at all) or should simply be
logged and skipped so the rest of the job can continue (e.g. one player's
latest match could not be retrieved).
"""

from __future__ import annotations


class WtaDailyError(Exception):
    """Base class for all errors raised by this package."""


class ConfigurationError(WtaDailyError):
    """Raised when the configuration file/environment is invalid or incomplete."""


class PluginNotFoundError(WtaDailyError):
    """Raised when a configured plugin name has not been registered."""


class DataProviderError(WtaDailyError):
    """Raised when a rankings or match data provider fails in a way that should
    abort the current step (e.g. the rankings endpoint itself is unreachable).
    """


class PlayerDataError(WtaDailyError):
    """Raised when a single player's data (typically their latest match) cannot
    be obtained. The pipeline catches this per player so that one player's
    failure never aborts the whole job.
    """


class GraphicsError(WtaDailyError):
    """Raised when a graphic (leaderboard or player card) cannot be rendered."""


class VoiceSynthesisError(WtaDailyError):
    """Raised when narration audio could not be synthesized."""


class VideoAssemblyError(WtaDailyError):
    """Raised when the final MP4 could not be assembled."""
