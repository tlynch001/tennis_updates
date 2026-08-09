"""A tiny, dependency-free plugin registry.

Each plugin *category* (rankings, matches, script generation, graphics,
voice, video) gets its own :class:`PluginRegistry` instance. Concrete plugin
modules register themselves with a decorator::

    @rankings_registry.register("wta_official")
    class WtaOfficialRankingsProvider(RankingsProvider):
        ...

The pipeline then asks the registry to build a provider by name, with that
name coming straight out of the YAML configuration file - no source code
changes required to switch providers, and no source code changes required to
*add* a new one; only a new module (imported once from
``wta_daily/plugins/__init__.py`` or a sibling ``__init__.py``) and a
decorator are needed. This is the mechanism that makes it easy to later add
an ATP feed, a "Top 25" variant, or additional languages.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Generic, TypeVar

from wta_daily.exceptions import PluginNotFoundError

T = TypeVar("T")


class PluginRegistry(Generic[T]):
    """Maps short string names to plugin classes for one plugin category."""

    def __init__(self, category: str) -> None:
        self._category = category
        self._plugins: dict[str, type[T]] = {}

    def register(self, name: str) -> Callable[[type[T]], type[T]]:
        """Class decorator that registers ``cls`` under ``name``."""

        def decorator(cls: type[T]) -> type[T]:
            if name in self._plugins and self._plugins[name] is not cls:
                raise ValueError(
                    f"A {self._category} plugin named '{name}' is already registered "
                    f"({self._plugins[name].__qualname__})."
                )
            cls.name = name  # type: ignore[attr-defined]
            self._plugins[name] = cls
            return cls

        return decorator

    def get(self, name: str) -> type[T]:
        try:
            return self._plugins[name]
        except KeyError as exc:
            available = ", ".join(sorted(self._plugins)) or "<none registered>"
            raise PluginNotFoundError(
                f"No {self._category} plugin named '{name}'. Available: {available}"
            ) from exc

    def create(self, name: str, /, **kwargs: object) -> T:
        """Instantiate the plugin registered under ``name`` with ``kwargs``."""

        return self.get(name)(**kwargs)

    def available(self) -> list[str]:
        return sorted(self._plugins)


rankings_registry: PluginRegistry = PluginRegistry("rankings")
matches_registry: PluginRegistry = PluginRegistry("match")
script_registry: PluginRegistry = PluginRegistry("script generator")
graphics_registry: PluginRegistry = PluginRegistry("graphics renderer")
voice_registry: PluginRegistry = PluginRegistry("voice synthesizer")
video_registry: PluginRegistry = PluginRegistry("video assembler")


def load_builtin_plugins() -> None:
    """Import every built-in plugin module so its registration decorator runs.

    This is the single place that needs a new ``import`` line when a new
    built-in plugin module is added; importing a module is what triggers its
    ``@registry.register(...)`` decorator to execute. Third-party plugins can
    be loaded the same way from application start-up code without editing
    this function.
    """

    from wta_daily.graphics import pillow_renderer  # noqa: F401
    from wta_daily.plugins.matches import sample as _matches_sample  # noqa: F401
    from wta_daily.plugins.matches import wta_official as _matches_wta  # noqa: F401
    from wta_daily.plugins.rankings import sample as _rankings_sample  # noqa: F401
    from wta_daily.plugins.rankings import wta_official as _rankings_wta  # noqa: F401
    from wta_daily.scripts_gen import (
        openai_generator,  # noqa: F401
        template_generator,  # noqa: F401
    )
    from wta_daily.video import ffmpeg_assembler  # noqa: F401
    from wta_daily.voice import elevenlabs_provider  # noqa: F401
