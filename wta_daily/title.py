"""Canonical YouTube video title generator (``title.txt``).

One deterministic, pure function - not an LLM call, since the format is
fixed and fully derivable from the report's own canonical
``report_date``/player count. Kept as its own small module (mirroring
:mod:`wta_daily.youtube_description` and :mod:`wta_daily.tournament_context`)
so there is exactly one place this format is defined; both
``DailyPipeline`` (which writes ``title.txt`` alongside the rest of a
day's output) and :mod:`wta_daily.youtube.uploader` (which sends the same
string to the YouTube Data API as the video's title) import this function
rather than each formatting their own copy.
"""

from __future__ import annotations

from wta_daily.models import DailyReport

#: Non-breaking em dash, matches the brief's exact required separator.
_EM_DASH = "\u2014"


def generate_title(report: DailyReport) -> str:
    """Return e.g. ``"WTA Top 10 Update \u2014 August 17, 2026"``.

    * ``top_n`` comes from ``len(report.players)`` - the actual number of
      players covered this run, not a hard-coded "10" - so a differently
      configured ``top_n`` (e.g. 25) still produces an accurate title.
    * The date comes from ``report.report_date`` - the pipeline's one
      canonical "what day is this report for" field - never the system
      clock, so re-publishing/backfilling an older report always titles
      it correctly.
    * Full English month name, no zero-padded day (``%-d``/``%e`` aren't
      portable across platforms, so this uses the day integer directly).
    * No tournament names, player names, rankings, scores, or hashtags -
      exactly the brief's required format, nothing more.
    """

    top_n = len(report.players)
    date_str = f"{report.report_date:%B} {report.report_date.day}, {report.report_date.year}"
    return f"WTA Top {top_n} Update {_EM_DASH} {date_str}"
