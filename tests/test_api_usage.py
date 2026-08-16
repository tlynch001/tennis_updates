"""Unit tests for :mod:`wta_daily.api_usage`, the per-run external-request counter."""

from __future__ import annotations

import logging

import pytest

from wta_daily import api_usage


@pytest.fixture(autouse=True)
def _reset_counter() -> None:
    api_usage.reset()
    yield
    api_usage.reset()


def test_starts_empty() -> None:
    assert api_usage.snapshot() == {}
    assert api_usage.total() == 0


def test_record_increments_the_named_category() -> None:
    api_usage.record("WTA rankings")
    api_usage.record("WTA rankings")
    api_usage.record("LiveTennisAPI")

    assert api_usage.snapshot() == {"WTA rankings": 2, "LiveTennisAPI": 1}
    assert api_usage.total() == 3


def test_reset_clears_everything() -> None:
    api_usage.record("WTA rankings")
    api_usage.reset()

    assert api_usage.snapshot() == {}
    assert api_usage.total() == 0


def test_log_summary_reports_every_recorded_category_and_the_total(
    caplog: pytest.LogCaptureFixture,
) -> None:
    api_usage.record("WTA rankings")
    api_usage.record("WTA tournament discovery")
    api_usage.record("WTA match results")
    api_usage.record("WTA match results")
    api_usage.record("WTA match results")

    with caplog.at_level(logging.INFO, logger="wta_daily.api_usage"):
        api_usage.log_summary()

    message = caplog.text
    assert "WTA rankings: 1" in message
    assert "WTA tournament discovery: 1" in message
    assert "WTA match results: 3" in message
    assert "Total: 5" in message


def test_log_summary_never_leaks_secrets(caplog: pytest.LogCaptureFixture) -> None:
    """The counter only ever stores short category labels it was given, and
    those are always hardcoded provider/endpoint names in this codebase -
    never a URL, query string, or header - so nothing resembling an API key
    can end up in this log line regardless of what triggered the call."""

    api_usage.record("LiveTennisAPI")
    with caplog.at_level(logging.INFO, logger="wta_daily.api_usage"):
        api_usage.log_summary()

    assert "key" not in caplog.text.lower()
    assert "bearer" not in caplog.text.lower()
    assert "token" not in caplog.text.lower()


def test_log_summary_handles_no_requests_gracefully(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO, logger="wta_daily.api_usage"):
        api_usage.log_summary()

    assert "none made" in caplog.text.lower()
