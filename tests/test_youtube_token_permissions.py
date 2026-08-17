"""Tests for the OAuth token file's on-disk handling in wta_daily.youtube.auth.

Deliberately does NOT need the optional google-auth packages installed -
_save_token/_restrict_token_file_permissions only need an object with a
.to_json() method, so these tests use a tiny fake stand-in rather than a
real google.oauth2.credentials.Credentials instance. This keeps this
security-relevant behavior tested unconditionally, unlike
tests/test_youtube_auth.py's OAuth-flow tests (which do need the real
Credentials class and are skipped when it isn't installed).
"""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest

from wta_daily.youtube.auth import _restrict_token_file_permissions, _save_token


class _FakeCredentials:
    """Stands in for a real google.oauth2.credentials.Credentials object -
    _save_token only ever calls .to_json() on whatever it's given."""

    def __init__(self, payload: dict[str, str]) -> None:
        self._payload = payload

    def to_json(self) -> str:
        return json.dumps(self._payload)


def test_save_token_writes_the_credential_json(tmp_path: Path) -> None:
    token_path = tmp_path / "secrets" / "youtube_token.json"
    creds = _FakeCredentials({"token": "fake-token", "refresh_token": "fake-refresh"})

    _save_token(creds, token_path)

    assert token_path.exists()
    saved = json.loads(token_path.read_text(encoding="utf-8"))
    assert saved == {"token": "fake-token", "refresh_token": "fake-refresh"}


def test_save_token_creates_parent_directories(tmp_path: Path) -> None:
    token_path = tmp_path / "nested" / "secrets" / "youtube_token.json"
    creds = _FakeCredentials({"token": "fake-token"})

    _save_token(creds, token_path)

    assert token_path.exists()


@pytest.mark.skipif(os.name != "posix", reason="POSIX file permissions only apply on POSIX systems")
def test_save_token_restricts_permissions_to_owner_only_on_posix(tmp_path: Path) -> None:
    token_path = tmp_path / "secrets" / "youtube_token.json"
    creds = _FakeCredentials({"token": "fake-token", "refresh_token": "fake-refresh"})

    _save_token(creds, token_path)

    mode = stat.S_IMODE(token_path.stat().st_mode)
    assert mode == 0o600, f"expected mode 0o600 (owner read/write only), got {oct(mode)}"


@pytest.mark.skipif(os.name != "posix", reason="POSIX file permissions only apply on POSIX systems")
def test_save_token_restricts_permissions_when_refreshing_an_existing_token(tmp_path: Path) -> None:
    """A refreshed token overwrites the file, not just a freshly authorized
    one - permissions must be re-applied on every write, not only the
    first."""

    token_path = tmp_path / "secrets" / "youtube_token.json"
    _save_token(_FakeCredentials({"token": "first-token"}), token_path)
    # Simulate the file having been left world-readable by some other means.
    token_path.chmod(0o644)

    _save_token(_FakeCredentials({"token": "refreshed-token"}), token_path)

    mode = stat.S_IMODE(token_path.stat().st_mode)
    assert mode == 0o600
    assert "refreshed-token" in token_path.read_text(encoding="utf-8")


def test_restrict_token_file_permissions_is_a_noop_on_non_posix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Windows has no equivalent of Unix mode bits - this must never raise
    or attempt a chmod call there."""

    token_path = tmp_path / "youtube_token.json"
    token_path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr("wta_daily.youtube.auth.os.name", "nt")

    calls = []
    monkeypatch.setattr(Path, "chmod", lambda self, mode: calls.append(mode))

    _restrict_token_file_permissions(token_path)

    assert calls == []


def test_restrict_token_file_permissions_failure_is_logged_not_raised(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """A chmod failure (unusual filesystem, permissions error, etc.) must
    never fail the run - the token having been written matters more than
    this hardening step succeeding."""

    if os.name != "posix":
        pytest.skip("POSIX file permissions only apply on POSIX systems")

    token_path = tmp_path / "youtube_token.json"
    token_path.write_text("{}", encoding="utf-8")

    def failing_chmod(self: Path, mode: int) -> None:
        raise OSError("simulated permission error")

    monkeypatch.setattr(Path, "chmod", failing_chmod)

    with caplog.at_level("WARNING"):
        _restrict_token_file_permissions(token_path)  # must not raise

    assert any("permission" in record.message.lower() for record in caplog.records)


def test_save_token_never_fails_the_run_if_chmod_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    if os.name != "posix":
        pytest.skip("POSIX file permissions only apply on POSIX systems")

    token_path = tmp_path / "secrets" / "youtube_token.json"
    creds = _FakeCredentials({"token": "fake-token"})

    def failing_chmod(self: Path, mode: int) -> None:
        raise OSError("simulated permission error")

    monkeypatch.setattr(Path, "chmod", failing_chmod)

    _save_token(creds, token_path)  # must not raise despite the chmod failure

    assert token_path.exists()
    assert "fake-token" in token_path.read_text(encoding="utf-8")
