"""Determines which calendar day a completed match should be attributed
to for **daily-recap** purposes - not necessarily the literal calendar
date the match finished on.

## Why this exists (production incident, August 2026)

Aryna Sabalenka's completed match against Sara Bejlek at Cincinnati
finished shortly after midnight local time. The automated 8 AM run's
report for that morning excluded it: the pipeline asks "did she play on
[report_date - 1 day]" (see :mod:`wta_daily.pipeline`'s
``match_target_date``), but the match's raw completion timestamp,
normalized to UTC, had already rolled over onto the *next* calendar
day (both in UTC and in Eastern local time) - one day later than the
"yesterday" bucket the run was asking about, even though from a
broadcast/recap point of view it was unambiguously part of the previous
evening's schedule.

## The rule

A match completing before an early-morning cutoff hour (in
tournament-local time, when it's known - see
:mod:`wta_daily.tournament_timezones` - otherwise UTC, as a documented
fallback) is attributed to the **previous** calendar day, exactly like a
broadcaster's "late night" programming day is counted as part of the
previous night rather than the next morning. A match completing at or
after the cutoff keeps its own calendar day, unchanged.

This is a pure, deterministic function of the completion instant (and
timezone) alone: the exact same instant always produces the exact same
reporting date. That determinism is what guarantees a match can never be
attributed to two different reporting days by two different runs asking
about two different dates - it either belongs to a given day's report or
it doesn't, with no dependency on when a query happens to be made (see
this module's tests, and
:mod:`wta_daily.plugins.matches.wta_official`'s day-first lookup for how
this is used to prevent a match from ever being reported twice).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, tzinfo

#: Matches completing before this LOCAL hour are still attributed to the
#: previous calendar day - not specific to any one tournament or
#: timezone, applied uniformly using tournament-local time when
#: available and UTC otherwise (see :func:`reporting_date_for_completion`).
DEFAULT_CUTOFF_HOUR = 6


def reporting_date_for_completion(
    completed_at_utc: datetime,
    *,
    tz: tzinfo | None = None,
    cutoff_hour: int = DEFAULT_CUTOFF_HOUR,
) -> date:
    """The calendar day ``completed_at_utc`` (a timezone-aware UTC
    ``datetime``) should be attributed to for daily-recap purposes.

    ``tz`` is the tournament's local timezone when it's known (see
    :mod:`wta_daily.tournament_timezones`) - preferred, since "after
    midnight" only means something in *local* time, and using it also
    correctly accounts for daylight-saving transitions (a fixed UTC
    offset would not). When ``tz`` is ``None``, this falls back to
    treating ``completed_at_utc`` itself as if it were local time, i.e.
    applying the same cutoff directly against the UTC hour - a
    reasonable approximation (see the module docstring) rather than
    refusing to classify the match at all.
    """

    local_dt = completed_at_utc.astimezone(tz) if tz is not None else completed_at_utc
    reporting = local_dt.date()
    if local_dt.hour < cutoff_hour:
        reporting -= timedelta(days=1)
    return reporting
