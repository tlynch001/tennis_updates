from __future__ import annotations

from datetime import date

from wta_daily.models import DailyReport, Movement, PlayerReport
from wta_daily.title import generate_title


def _report(report_date: date, n: int = 10) -> DailyReport:
    players = [
        PlayerReport(
            rank=i,
            name=f"Player {i}",
            player_id=f"p{i}",
            country_code="USA",
            points=1000 - i,
            movement=Movement.SAME,
        )
        for i in range(1, n + 1)
    ]
    return DailyReport(report_date=report_date, tour="wta", players=players)


def test_generate_title_matches_exact_required_format() -> None:
    report = _report(date(2026, 8, 17))

    assert generate_title(report) == "WTA Top 10 Update \u2014 August 17, 2026"


def test_generate_title_does_not_zero_pad_the_day() -> None:
    report = _report(date(2026, 9, 2))

    assert generate_title(report) == "WTA Top 10 Update \u2014 September 2, 2026"


def test_generate_title_uses_full_english_month_name_across_year_boundary() -> None:
    report = _report(date(2027, 1, 1))

    assert generate_title(report) == "WTA Top 10 Update \u2014 January 1, 2027"


def test_generate_title_uses_actual_player_count_not_a_hard_coded_ten() -> None:
    report = _report(date(2026, 8, 17), n=25)

    assert generate_title(report) == "WTA Top 25 Update \u2014 August 17, 2026"


def test_generate_title_is_deterministic() -> None:
    report = _report(date(2026, 8, 17))

    assert generate_title(report) == generate_title(report)


def test_generate_title_uses_report_date_not_system_clock() -> None:
    """A backfilled/older report must title itself for its own report_date,
    never "today" - this is what lets --upload-youtube retroactively
    publish an old report with the correct title."""

    old_report = _report(date(2020, 1, 1))

    assert generate_title(old_report) == "WTA Top 10 Update \u2014 January 1, 2020"


def test_generate_title_contains_no_extra_content() -> None:
    """No tournament, player names, scores, or hashtags - exactly the
    brief's required format, nothing more."""

    report = _report(date(2026, 8, 17))
    title = generate_title(report)

    assert title == "WTA Top 10 Update \u2014 August 17, 2026"
    for player in report.players:
        assert player.name not in title
    assert "#" not in title


def test_generate_title_uses_atp_display_name_for_atp_reports() -> None:
    report = _report(date(2026, 8, 17))
    report.tour = "atp"

    title = generate_title(report)

    assert title == "ATP Top 10 Update \u2014 August 17, 2026"
    assert "WTA" not in title

