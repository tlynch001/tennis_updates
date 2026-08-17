"""Pure logic for inferring which tournament is most relevant to a day's
report, without ever calling an external API or hard-coding a tournament
calendar.

Both the YouTube thumbnail (:mod:`wta_daily.graphics.thumbnail`) and the
YouTube description (:mod:`wta_daily.youtube_description`) need to answer
"what tournament is this update about", and both need the same answer for
the same report - so the logic lives here once, reused by both, rather
than duplicated or (worse) drifting out of sync.
"""

from __future__ import annotations

from collections import Counter

from wta_daily.models import DailyReport


def most_relevant_tournament(report: DailyReport) -> str | None:
    """Return the tournament name most of today's *confirmed* matches were
    played at, or ``None`` if there's no reliable signal to go on.

    Draws only from data already fetched for the day's report -
    ``report.players[*].match.tournament`` (and the featured player's
    match, if any) - the exact same match data already used for the
    narration and player cards, so this never triggers an additional
    lookup. A tournament name only appears here if at least one player in
    the tracked group (or the featured player) has a *confirmed* completed
    match there on the target date; a day where nobody played yields
    ``None`` rather than a guess (e.g. reusing yesterday's tournament or a
    hard-coded "current" event).

    Ties are broken by first-encountered order (i.e. the higher-ranked
    player's tournament wins) - deterministic, and a reasonable default
    without inventing a tournament-importance calendar.
    """

    tournaments = [p.match.tournament for p in report.players if p.match is not None]
    if report.featured_player is not None and report.featured_player.match is not None:
        tournaments.append(report.featured_player.match.tournament)

    if not tournaments:
        return None

    counts = Counter(tournaments)
    max_count = max(counts.values())
    for tournament in tournaments:
        if counts[tournament] == max_count:
            return tournament
    return None  # pragma: no cover - unreachable, tournaments is non-empty
