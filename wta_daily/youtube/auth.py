"""OAuth 2.0 credential handling for the YouTube Data API v3.

Designed for an application running unattended on a Raspberry Pi:

1. You create Google Cloud OAuth "Desktop app" credentials and download the
   client-secret JSON to ``config.client_secret_path`` (see the README's
   "YouTube publishing" section for the exact console steps).
2. You run the interactive authorization *once*, by hand (this needs a
   browser - see ``run_interactive_authorization`` below for the
   headless-Pi workflow).
3. The resulting token (including its refresh token) is cached at
   ``config.token_path``.
4. Every later call - including unattended scheduled runs - loads that
   cached token and silently refreshes the short-lived access token via
   the long-lived refresh token, with no browser and no human involved.

Every ``google.*``/``google_auth_oauthlib.*`` import below is deferred
inside a function body rather than at module import time, so importing
this module - which :mod:`wta_daily.youtube.uploader` (and therefore
:mod:`wta_daily.pipeline`, indirectly, at least at the module level) does
unconditionally - never requires those optional packages to be installed.
They're only actually needed once :func:`get_credentials` is called, which
only ever happens when ``youtube.enabled: true``.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from wta_daily.config import YouTubeConfig
from wta_daily.exceptions import WtaDailyError

logger = logging.getLogger(__name__)

#: Upload-only scope - deliberately the narrowest scope that can perform
#: every operation this project needs (video insert, thumbnail set). Never
#: request a broader scope (e.g. full account management) than the
#: feature actually uses.
SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]


class YouTubeAuthError(WtaDailyError):
    """Raised when OAuth credentials could not be loaded, refreshed, or
    obtained. Never includes the credential contents themselves in its
    message - see the module docstring's secret-handling rules."""


def _install_google_libraries_hint() -> str:
    return (
        "YouTube publishing requires the optional google-api-python-client / "
        "google-auth-oauthlib packages, which are not installed. Run: "
        "pip install -r requirements-youtube.txt (see README.md's 'YouTube publishing' "
        "section)."
    )


def get_credentials(config: YouTubeConfig) -> Any:
    """Return valid OAuth credentials, refreshing or (only if truly
    necessary) interactively obtaining them.

    Only ever called when ``config.enabled`` is ``True`` - see
    :mod:`wta_daily.youtube.uploader`. Never logs the token/client-secret
    contents, only file paths and high-level status.
    """

    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
    except ImportError as exc:  # pragma: no cover - exercised only without the optional deps
        raise YouTubeAuthError(_install_google_libraries_hint()) from exc

    token_path = Path(config.token_path)
    creds = None
    if token_path.exists():
        try:
            creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
        except (ValueError, OSError) as exc:
            logger.warning(
                "Could not read the cached YouTube token at %s (%s); a fresh authorization will be required.",
                token_path,
                exc,
            )
            creds = None

    if creds and creds.valid:
        return creds

    if creds and creds.expired and creds.refresh_token:
        logger.info("Refreshing expired YouTube access token...")
        try:
            creds.refresh(Request())
        except Exception as exc:  # noqa: BLE001 - never leak token contents, just fail clearly
            raise YouTubeAuthError(
                f"Could not refresh the cached YouTube OAuth token at {token_path}. "
                "It may have been revoked - delete the file and re-run the interactive "
                f"authorization. ({type(exc).__name__})"
            ) from exc
        _save_token(creds, token_path)
        logger.info("YouTube access token refreshed successfully.")
        return creds

    return run_interactive_authorization(config)


def run_interactive_authorization(config: YouTubeConfig) -> Any:
    """Perform the one-time interactive OAuth authorization and cache the
    resulting token. Requires a browser (or, over SSH, port-forwarding -
    see the README) - this is meant to be run by a human once, never from
    an unattended scheduled job."""

    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError as exc:  # pragma: no cover - exercised only without the optional deps
        raise YouTubeAuthError(_install_google_libraries_hint()) from exc

    client_secret_path = Path(config.client_secret_path)
    if not client_secret_path.exists():
        raise YouTubeAuthError(
            f"No cached YouTube token at {config.token_path} and no OAuth client secret "
            f"found at {client_secret_path}. Follow the README's 'YouTube publishing' setup "
            "steps to create Google Cloud OAuth credentials, save the client-secret JSON "
            "there, then run the interactive authorization once."
        )

    logger.info(
        "No valid cached YouTube token found; starting one-time interactive authorization using %s...",
        client_secret_path,
    )
    flow = InstalledAppFlow.from_client_secrets_file(str(client_secret_path), SCOPES)
    creds = flow.run_local_server(port=0)
    _save_token(creds, Path(config.token_path))
    logger.info(
        "YouTube OAuth authorization complete; token cached at %s for future unattended runs.",
        config.token_path,
    )
    return creds


def _save_token(creds: Any, token_path: Path) -> None:
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(creds.to_json(), encoding="utf-8")
