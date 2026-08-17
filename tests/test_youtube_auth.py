"""Tests for wta_daily.youtube.auth's OAuth credential handling.

These exercise real google-auth ``Credentials`` objects (constructed
directly in-memory, never touching the network) to validate the
load/refresh/error branching logic - but never perform a live OAuth flow
or a real HTTP refresh call. Skipped automatically (not failed) in any
environment where the optional google-auth packages aren't installed
(see requirements-youtube.txt) - the rest of the suite/application never
depends on them.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from wta_daily.config import YouTubeConfig

google_auth = pytest.importorskip("google.oauth2.credentials")
pytest.importorskip("google_auth_oauthlib.flow")

from wta_daily.youtube.auth import YouTubeAuthError, get_credentials  # noqa: E402


def _write_token(path: Path, *, expired: bool = False) -> None:
    from datetime import datetime

    from google.oauth2.credentials import Credentials

    # Deliberately always an explicit timestamp (never None): reloading via
    # from_authorized_user_file defaults a *missing* expiry to "now" (i.e.
    # immediately expired), which would make the "not expired" fixture
    # accidentally trigger a refresh attempt too.
    expiry = datetime(2000, 1, 1) if expired else datetime(2099, 1, 1)
    creds = google_auth.Credentials(
        token="fake-access-token",
        refresh_token="fake-refresh-token",
        client_id="fake-client-id",
        client_secret="fake-client-secret",
        token_uri="https://oauth2.googleapis.com/token",
        expiry=expiry,
    )
    assert isinstance(creds, Credentials)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(creds.to_json(), encoding="utf-8")


def test_get_credentials_reuses_a_still_valid_cached_token(tmp_path: Path) -> None:
    token_path = tmp_path / "secrets" / "youtube_token.json"
    _write_token(token_path, expired=False)
    config = YouTubeConfig(token_path=token_path, client_secret_path=tmp_path / "missing.json")

    creds = get_credentials(config)

    assert creds.valid
    assert creds.token == "fake-access-token"


def test_get_credentials_refreshes_an_expired_token_and_caches_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from google.oauth2.credentials import Credentials

    token_path = tmp_path / "secrets" / "youtube_token.json"
    _write_token(token_path, expired=True)
    config = YouTubeConfig(token_path=token_path, client_secret_path=tmp_path / "missing.json")

    def fake_refresh(self: Credentials, _request: object) -> None:
        self.token = "refreshed-access-token"
        self.expiry = None

    monkeypatch.setattr(Credentials, "refresh", fake_refresh)

    creds = get_credentials(config)

    assert creds.token == "refreshed-access-token"
    # The refreshed token was cached back to disk for the next run.
    saved = token_path.read_text(encoding="utf-8")
    assert "refreshed-access-token" in saved


@pytest.mark.skipif(os.name != "posix", reason="POSIX file permissions only apply on POSIX systems")
def test_get_credentials_leaves_a_refreshed_token_file_owner_only_readable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from google.oauth2.credentials import Credentials

    token_path = tmp_path / "secrets" / "youtube_token.json"
    _write_token(token_path, expired=True)
    config = YouTubeConfig(token_path=token_path, client_secret_path=tmp_path / "missing.json")

    def fake_refresh(self: Credentials, _request: object) -> None:
        self.token = "refreshed-access-token"
        self.expiry = None

    monkeypatch.setattr(Credentials, "refresh", fake_refresh)

    get_credentials(config)

    mode = stat.S_IMODE(token_path.stat().st_mode)
    assert mode == 0o600


def test_get_credentials_raises_a_clear_error_when_refresh_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from google.oauth2.credentials import Credentials

    token_path = tmp_path / "secrets" / "youtube_token.json"
    _write_token(token_path, expired=True)
    config = YouTubeConfig(token_path=token_path, client_secret_path=tmp_path / "missing.json")

    def fake_refresh(self: Credentials, _request: object) -> None:
        raise RuntimeError("simulated revoked token")

    monkeypatch.setattr(Credentials, "refresh", fake_refresh)

    with pytest.raises(YouTubeAuthError):
        get_credentials(config)


def test_get_credentials_raises_a_clear_error_with_no_token_and_no_client_secret(
    tmp_path: Path,
) -> None:
    config = YouTubeConfig(
        token_path=tmp_path / "secrets" / "youtube_token.json",
        client_secret_path=tmp_path / "secrets" / "youtube_client_secret.json",
    )

    with pytest.raises(YouTubeAuthError, match="client secret"):
        get_credentials(config)


def test_get_credentials_never_logs_the_token_value(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    token_path = tmp_path / "secrets" / "youtube_token.json"
    _write_token(token_path, expired=False)
    config = YouTubeConfig(token_path=token_path, client_secret_path=tmp_path / "missing.json")

    with caplog.at_level("DEBUG"):
        get_credentials(config)

    assert "fake-access-token" not in caplog.text
    assert "fake-refresh-token" not in caplog.text
    assert "fake-client-secret" not in caplog.text
