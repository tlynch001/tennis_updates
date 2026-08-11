from __future__ import annotations

import pytest

from wta_daily.exceptions import PluginNotFoundError
from wta_daily.plugins.registry import PluginRegistry


class _Base:
    name = "base"

    def __init__(self, value: int = 0) -> None:
        self.value = value


def test_register_and_create_plugin() -> None:
    registry: PluginRegistry = PluginRegistry("widget")

    @registry.register("thing")
    class Thing(_Base):
        pass

    instance = registry.create("thing", value=42)
    assert isinstance(instance, Thing)
    assert instance.value == 42
    assert Thing.name == "thing"


def test_get_unknown_plugin_raises_with_available_list() -> None:
    registry: PluginRegistry = PluginRegistry("widget")

    @registry.register("known")
    class Known(_Base):
        pass

    with pytest.raises(PluginNotFoundError, match="known"):
        registry.get("unknown")


def test_available_lists_registered_names_sorted() -> None:
    registry: PluginRegistry = PluginRegistry("widget")

    @registry.register("zeta")
    class Zeta(_Base):
        pass

    @registry.register("alpha")
    class Alpha(_Base):
        pass

    assert registry.available() == ["alpha", "zeta"]


def test_builtin_plugins_are_all_registered() -> None:
    from wta_daily.plugins.registry import (
        graphics_registry,
        load_builtin_plugins,
        matches_registry,
        rankings_registry,
        script_registry,
        video_registry,
        voice_registry,
    )

    load_builtin_plugins()

    assert "wta_official" in rankings_registry.available()
    assert "sample" in rankings_registry.available()
    assert "wta_official" in matches_registry.available()
    assert "sample" in matches_registry.available()
    assert "template" in script_registry.available()
    assert "openai" in script_registry.available()
    assert "pillow" in graphics_registry.available()
    assert "elevenlabs" in voice_registry.available()
    assert "ffmpeg" in video_registry.available()
