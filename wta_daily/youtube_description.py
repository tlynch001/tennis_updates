"""Builds the plain-text YouTube description (``youtube_description.txt``)
for one daily run.

A pure function, not a pluggable provider - there's exactly one sensible
way to summarize a day's report for this purpose today, so this avoids the
plugin-registry machinery the project uses for genuinely interchangeable
concerns (rankings source, script tone, etc.). Built entirely from the
same validated :class:`~wta_daily.models.DailyReport` already used for
``report.json``/narration - no new data is fetched, and nothing here is
invented: a fact that isn't available (an unranked featured player, an
unconfirmed tournament) is simply omitted rather than guessed.
"""

from __future__ import annotations

from wta_daily.models import DailyReport, FeaturedPlayerReport, Movement
from wta_daily.tour import profile_for
from wta_daily.tournament_context import most_relevant_tournament


def generate_description(report: DailyReport) -> str:
    top_n = len(report.players)
    date_str = f"{report.report_date:%B} {report.report_date.day}, {report.report_date.year}"
    tournament = most_relevant_tournament(report)
    tour = profile_for(report.tour).display_name

    lines: list[str] = [f"{tour} Top {top_n} Daily Update \u2014 {date_str}", ""]

    if tournament:
        lines.append(
            f"Today's update covers the latest {tour} Top {top_n} rankings and recent "
            f"results from {tournament}."
        )
    else:
        lines.append(f"Today's update covers the latest {tour} Top {top_n} rankings.")
    lines.append("")

    lines.extend(f"{player.rank}. {player.name}" for player in report.players)
    lines.append("")

    if report.featured_player is not None and report.featured_player.rank is not None:
        lines.append(f"Featured Player: {report.featured_player.name}")
        lines.append(_featured_summary(report.featured_player, top_n))
        lines.append("")

    lines.append(f"Follow along for daily {tour} Top {top_n} ranking and results updates.")

    return "\n".join(lines).strip() + "\n"


def _featured_summary(featured: FeaturedPlayerReport, top_n: int) -> str:
    """One short, factual sentence about the featured player - only ever
    built from fields that are actually populated on ``featured``."""

    summary = f"Currently ranked No. {featured.rank}"
    # Gated on the already-computed `movement` (see wta_daily.movement),
    # never on a fresh `rank != previous_rank` comparison here - `movement`
    # is what carries the "this is only true between two official ranking
    # releases, never because of a single match result" guarantee, and
    # duplicating that comparison independently would bypass it.
    if featured.movement in (Movement.UP, Movement.DOWN) and featured.previous_rank:
        direction = "up from" if featured.movement is Movement.UP else "down from"
        summary += f" ({direction} No. {featured.previous_rank})"

    if featured.match is not None:
        outcome = "defeated" if featured.match.won else "fell to"
        summary += (
            f". Most recently {outcome} {featured.match.opponent} {featured.match.score} "
            f"at {featured.match.tournament}."
        )
    elif featured.match_error:
        summary += ". Match results were not confirmed in time for this update."
    else:
        summary += ". Did not play in the most recent results covered by this update."

    return summary
