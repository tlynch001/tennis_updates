"""Phrase pools for :mod:`wta_daily.scripts_gen.tournament_status_narration`.

Kept in its own module (mirroring :mod:`wta_daily.scripts_gen.phrases` and
:mod:`wta_daily.scripts_gen.featured_player_phrases`) purely so the wording
can be reviewed/extended without touching the composition logic.
"""

from __future__ import annotations

#: First-time-reported elimination, with a named eliminator. ``{name}``,
#: ``{round}`` (a natural label, e.g. "the Round of 16" or "the
#: quarterfinals" - see wta_daily.rounds.round_label), ``{eliminated_by}``.
ELIMINATED_DETAILED_WITH_ELIMINATOR: list[str] = [
    "{name} is out of the tournament, eliminated by {eliminated_by} in {round}",
    "{name}'s run at this event came to an end in {round}, beaten by {eliminated_by}",
    "It's over for {name} at this tournament - {eliminated_by} ended her run in {round}",
    "{name} was knocked out in {round}, falling to {eliminated_by}",
]

#: Same as above, but for when no eliminator name was reliably available.
ELIMINATED_DETAILED_NO_ELIMINATOR: list[str] = [
    "{name} is out of the tournament, her run ending in {round}",
    "{name}'s tournament came to a close in {round}",
    "{name} was eliminated in {round}",
]

#: A second/subsequent day's brief mention of an elimination already
#: reported in full - see TournamentRunStatus.is_new_development's
#: docstring for why this stays short rather than repeating every detail.
ELIMINATED_BRIEF: list[str] = [
    "{name} remains out of the draw here, having fallen in {round}",
    "{name}'s tournament run is still over, eliminated back in {round}",
    "{name} is done at this event, her exit having come in {round}",
]

#: First-time-reported title win.
CHAMPION_DETAILED: list[str] = [
    "{name} has won the title, going the distance through the draw",
    "{name} is the champion here, capping the week off with the trophy",
    "{name} claimed the title, winning the whole tournament",
]

#: Subsequent brief mention of an already-reported title.
CHAMPION_BRIEF: list[str] = [
    "{name} remains this tournament's champion",
    "{name} is still celebrating the title from this event",
]

#: A ranking-points figure earned this run, appended as a trailing clause.
#: ``{points}``.
POINTS_CLAUSES: list[str] = [
    ", a result worth {points} ranking points",
    ", earning {points} points for the run",
    ", good for {points} points toward the rankings",
]

#: This year's result was further/better than last year's at the same
#: event (by round order, not points - see
#: tournament_status_narration.py). ``{previous_round}``.
HISTORY_IMPROVED: list[str] = [
    ", an improvement on her {previous_round} finish here a year ago",
    ", better than the {previous_round} she reached at this event last year",
    ", one step further than last year's {previous_round} showing",
]

#: Same round reached both years.
HISTORY_MATCHED: list[str] = [
    ", matching her {previous_round} result from this event a year ago",
    ", the same result she had here twelve months ago",
]

#: This year's result was earlier/worse than last year's.
HISTORY_WORSE: list[str] = [
    ", a step back from her {previous_round} run here last year",
    ", not quite matching last year's {previous_round} showing",
    ", short of the {previous_round} she reached at this event a year ago",
]

#: A defended title - the one case HISTORY_IMPROVED/MATCHED don't quite
#: cover, since "matching" undersells successfully defending a title.
HISTORY_DEFENDED_TITLE: list[str] = [
    ", successfully defending the title she won here last year",
    ", backing up last year's title run with another one",
]

#: The net ranking-points swing once last year's result eventually rolls
#: off the rolling 52-week list - deliberately never phrased as "gained
#: ranking points" (that would wrongly imply an immediate rank change;
#: see wta_daily.models.TournamentRunStatus.points_delta's docstring).
#: ``{delta}`` is always passed in as a positive number by the caller;
#: the pool itself picks the correctly-signed wording.
NET_SWING_POSITIVE: list[str] = [
    " - a net swing of about {delta} points once last year's result rolls off the list",
    ", netting out to roughly {delta} points better off once the 52-week window turns over",
]

NET_SWING_NEGATIVE: list[str] = [
    " - a net swing of about {delta} points worse off once last year's result rolls off the list",
    ", netting out to roughly {delta} fewer points once the 52-week window turns over",
]

NET_SWING_FLAT: list[str] = [
    " - a wash, points-wise, once last year's result rolls off the list",
]
