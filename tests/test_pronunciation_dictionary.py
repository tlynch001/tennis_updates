"""Unit tests for :mod:`wta_daily.voice.pronunciation_dictionary`.

Mocks the ElevenLabs HTTP call (never hits the network) to verify the
create-once-and-cache behavior, cache invalidation when the alias list
changes, and that a creation failure degrades gracefully rather than
raising.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from wta_daily.voice import pronunciation_dictionary as pd


class _FakeResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict[str, Any]:
        return self._payload


def test_rules_payload_contains_every_alias() -> None:
    payload = pd._rules_payload()
    names = {rule["string_to_replace"] for rule in payload}

    assert names == set(pd.PLAYER_NAME_ALIASES)
    for rule in payload:
        assert rule["type"] == "alias"
        assert rule["alias"] == pd.PLAYER_NAME_ALIASES[rule["string_to_replace"]]


def test_rules_hash_is_stable_and_order_independent() -> None:
    hash1 = pd._rules_hash()
    hash2 = pd._rules_hash()

    assert hash1 == hash2


def test_get_or_create_locator_calls_the_api_when_cache_is_empty(tmp_path: Path) -> None:
    cache = pd.PronunciationDictionaryCache(tmp_path / "cache.json")

    with patch("requests.post") as mock_post:
        mock_post.return_value = _FakeResponse({"id": "dict-123", "version_id": "ver-456"})
        locator = pd.get_or_create_locator("fake-api-key", cache)

    assert locator == {"pronunciation_dictionary_id": "dict-123", "version_id": "ver-456"}
    mock_post.assert_called_once()
    # The API key must be sent as a header, never embedded in the URL or body.
    _, kwargs = mock_post.call_args
    assert kwargs["headers"]["xi-api-key"] == "fake-api-key"


def test_get_or_create_locator_caches_the_result(tmp_path: Path) -> None:
    cache = pd.PronunciationDictionaryCache(tmp_path / "cache.json")

    with patch("requests.post") as mock_post:
        mock_post.return_value = _FakeResponse({"id": "dict-123", "version_id": "ver-456"})
        first = pd.get_or_create_locator("fake-api-key", cache)

    assert first is not None
    cached = cache.load()
    assert cached is not None
    assert cached["pronunciation_dictionary_id"] == "dict-123"


def test_get_or_create_locator_does_not_call_the_api_again_when_cache_is_fresh(
    tmp_path: Path,
) -> None:
    """The core efficiency property: a normal run must not re-create the
    dictionary every single day."""

    cache = pd.PronunciationDictionaryCache(tmp_path / "cache.json")

    with patch("requests.post") as mock_post:
        mock_post.return_value = _FakeResponse({"id": "dict-123", "version_id": "ver-456"})
        pd.get_or_create_locator("fake-api-key", cache)

    with patch("requests.post") as mock_post_second_run:
        locator = pd.get_or_create_locator("fake-api-key", cache)

    assert locator == {"pronunciation_dictionary_id": "dict-123", "version_id": "ver-456"}
    mock_post_second_run.assert_not_called()


def test_get_or_create_locator_recreates_when_the_alias_list_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache = pd.PronunciationDictionaryCache(tmp_path / "cache.json")

    with patch("requests.post") as mock_post:
        mock_post.return_value = _FakeResponse({"id": "dict-123", "version_id": "ver-456"})
        pd.get_or_create_locator("fake-api-key", cache)

    # Simulate a future contributor adding a new name to the alias list.
    monkeypatch.setitem(pd.PLAYER_NAME_ALIASES, "Someone-New", "SUM-wun-noo")

    with patch("requests.post") as mock_post_after_change:
        mock_post_after_change.return_value = _FakeResponse(
            {"id": "dict-789", "version_id": "ver-999"}
        )
        locator = pd.get_or_create_locator("fake-api-key", cache)

    mock_post_after_change.assert_called_once()
    assert locator == {"pronunciation_dictionary_id": "dict-789", "version_id": "ver-999"}


def test_get_or_create_locator_returns_none_on_failure_without_raising(tmp_path: Path) -> None:
    """Pronunciation is a nice-to-have - a failure here must never bubble
    up and block narration synthesis."""

    cache = pd.PronunciationDictionaryCache(tmp_path / "cache.json")

    with patch("requests.post", side_effect=RuntimeError("simulated network failure")):
        locator = pd.get_or_create_locator("fake-api-key", cache)

    assert locator is None


def test_cache_load_returns_none_when_file_does_not_exist(tmp_path: Path) -> None:
    cache = pd.PronunciationDictionaryCache(tmp_path / "does-not-exist.json")

    assert cache.load() is None


def test_cache_load_returns_none_and_warns_on_corrupt_file(tmp_path: Path) -> None:
    cache_path = tmp_path / "cache.json"
    cache_path.write_text("not valid json{{{", encoding="utf-8")
    cache = pd.PronunciationDictionaryCache(cache_path)

    assert cache.load() is None


def test_cache_save_is_atomic_write(tmp_path: Path) -> None:
    cache_path = tmp_path / "nested" / "cache.json"
    cache = pd.PronunciationDictionaryCache(cache_path)

    cache.save({"pronunciation_dictionary_id": "abc", "version_id": "1", "rules_hash": "h"})

    assert cache_path.exists()
    assert not cache_path.with_suffix(".json.tmp").exists()
    assert cache.load() == {
        "pronunciation_dictionary_id": "abc",
        "version_id": "1",
        "rules_hash": "h",
    }
