"""Unit tests for wta_daily.reporting_day."""

from __future__ import annotations

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from wta_daily.reporting_day import reporting_date_for_completion

EASTERN = ZoneInfo("America/New_York")


def test_daytime_match_keeps_its_own_calendar_day_in_utc_fallback() -> None:
    completed = datetime(2026, 8, 19, 18, 30, tzinfo=UTC)  # mid-afternoon UTC

    assert reporting_date_for_completion(completed) == date(2026, 8, 19)


def test_daytime_match_keeps_its_own_calendar_day_with_local_timezone() -> None:
    # 2:30 PM Eastern (EDT, UTC-4) on Aug 19 = 18:30 UTC.
    completed = datetime(2026, 8, 19, 18, 30, tzinfo=UTC)

    assert reporting_date_for_completion(completed, tz=EASTERN) == date(2026, 8, 19)


def test_the_real_regression_case_sabalenka_vs_bejlek() -> None:
    """Sara Bejlek def. Aryna Sabalenka 7-6(9-7), 6-4 at Cincinnati - the
    match completed at 12:15 AM EDT Thursday, August 20, 2026 (04:15 UTC
    the same calendar day). It must be attributed to Wednesday, August
    19 - the evening session it was actually part of."""

    completed_utc = datetime(2026, 8, 20, 4, 15, tzinfo=UTC)

    assert reporting_date_for_completion(completed_utc, tz=EASTERN) == date(2026, 8, 19)


def test_the_real_regression_case_without_a_known_timezone_still_resolves_correctly() -> None:
    """Even the UTC-only fallback (no tournament timezone resolved) gets
    this specific, real case right, since 4:15 AM is still before the
    cutoff hour in UTC terms too."""

    completed_utc = datetime(2026, 8, 20, 4, 15, tzinfo=UTC)

    assert reporting_date_for_completion(completed_utc) == date(2026, 8, 19)


def test_a_match_completing_exactly_at_the_cutoff_hour_keeps_its_own_day() -> None:
    completed = datetime(2026, 8, 20, 6, 0, tzinfo=UTC)

    assert reporting_date_for_completion(completed, tz=EASTERN) == date(2026, 8, 19)  # 2 AM Eastern


def test_a_match_completing_just_before_local_midnight_is_not_shifted() -> None:
    # 11:45 PM Eastern (EDT) on Aug 19 = 03:45 UTC Aug 20 - still "last
    # night" in local terms, and *not* shifted a second time since it's
    # already the same calendar day locally (no midnight crossing at all
    # from the local date's perspective - it's simply evening).
    completed_utc = datetime(2026, 8, 20, 3, 45, tzinfo=UTC)

    assert reporting_date_for_completion(completed_utc, tz=EASTERN) == date(2026, 8, 19)


def test_a_match_completing_well_after_the_cutoff_the_next_morning_is_not_shifted() -> None:
    # 9:00 AM Eastern local time - a genuine next-day daytime match, not
    # a late-night carryover.
    completed_utc = datetime(2026, 8, 20, 13, 0, tzinfo=UTC)

    assert reporting_date_for_completion(completed_utc, tz=EASTERN) == date(2026, 8, 20)


def test_custom_cutoff_hour_is_respected() -> None:
    completed = datetime(2026, 8, 20, 7, 0, tzinfo=UTC)  # 3 AM Eastern

    assert reporting_date_for_completion(completed, tz=EASTERN, cutoff_hour=4) == date(2026, 8, 19)
    assert reporting_date_for_completion(completed, tz=EASTERN, cutoff_hour=2) == date(2026, 8, 20)


def test_reporting_date_is_a_pure_deterministic_function_of_the_instant() -> None:
    """The same instant must always map to the same reporting date,
    regardless of how many times (or when) it's evaluated - this is what
    guarantees a match can never end up eligible for two different
    daily reports."""

    completed = datetime(2026, 8, 20, 4, 15, tzinfo=UTC)

    results = {reporting_date_for_completion(completed, tz=EASTERN) for _ in range(5)}

    assert results == {date(2026, 8, 19)}
