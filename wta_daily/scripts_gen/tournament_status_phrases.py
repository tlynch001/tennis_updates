"""Phrase pools for :mod:`wta_daily.scripts_gen.tournament_status_narration`.

Kept in its own module (mirroring :mod:`wta_daily.scripts_gen.phrases` and
:mod:`wta_daily.scripts_gen.featured_player_phrases`) purely so the wording
can be reviewed/extended without touching the composition logic.

Two wording rules baked into every pool here:

1. ``{first_name}`` is used instead of a full name, since by the time this
   module's sentences are spoken, the player's full name has already been
   introduced earlier in the same paragraph/segment (see
   ``tournament_status_narration.py``'s docstring) - mechanically repeating
   the full name sentence after sentence reads unnaturally, and a bare
   pronoun risks ambiguity right after another player's name (the
   eliminator) has just been mentioned.
2. ``{round}``/``{previous_round}`` are substituted with
   ``TournamentRunStatus.round_label``/``previous_year_round_label``,
   which **already include their own leading article** (e.g. "the Round
   of 16", "the quarterfinals") - see ``wta_daily/rounds.py``. No template
   below ever places a determiner (``the``/``her``/``last year's``/``a``)
   directly in front of one of these placeholders, since that would
   double up into ungrammatical text (the "better than the the Round of
   64..." bug this pool was rewritten to fix); every template instead
   uses a preposition/verb (``in``/``on``/``than``/``matching``/etc.)
   immediately before the placeholder, which composes cleanly either way.
"""

from __future__ import annotations

#: The match just narrated in the same paragraph/segment (the win/loss
#: sentence immediately before this one) is *itself* the match that
#: eliminated her - see
#: :func:`wta_daily.scripts_gen.tournament_status_narration.is_result_of_reported_match`.
#: Deliberately does NOT repeat the eliminator's name or the score - the
#: match sentence already said who beat her and how; this only adds the
#: new, causal fact that the loss just narrated is the one that ends her
#: tournament. ``{tournament}`` is the (titleized) tournament name -
#: used when it's reliably known.
ELIMINATED_JUST_NOW_WITH_TOURNAMENT: list[str] = [
    "that ends {possessive} run in {tournament} in {round}",
    "with that loss, {possessive} {tournament} run ends in {round}",
    "{possessive} run in {tournament} ends there, in {round}",
    "that's the end of the road for {object} in {tournament}, in {round}",
]

#: Same as above, for when the tournament name isn't reliably known.
ELIMINATED_JUST_NOW_NO_TOURNAMENT: list[str] = [
    "that brings {possessive} tournament to an end in {round}",
    "that's the end of {possessive} run, in {round}",
    "with that, {possessive} tournament run is over, in {round}",
]

#: First-time-reported elimination that did *not* come from the match
#: just narrated in this same script (e.g. the elimination happened on
#: an earlier day than the one this run's match-result sentence covers -
#: still worth full detail the first time it's noticed, but "just now"
#: causal language would be inaccurate here since no match was just
#: described).
ELIMINATED_OPENING_WITH_ELIMINATOR: list[str] = [
    "{possessive} tournament run is over after {eliminated_by} knocked {object} out in {round}",
    "{first_name}'s run at this event ended in {round}, beaten by {eliminated_by}",
    "it's over for {first_name} at this tournament - {eliminated_by} ended {possessive} run in {round}",
    "{first_name} was knocked out in {round}, falling to {eliminated_by}",
]

#: Same as above, but for when no eliminator name was reliably available.
ELIMINATED_OPENING_NO_ELIMINATOR: list[str] = [
    "{possessive} tournament run is over, ending in {round}",
    "{first_name}'s tournament came to a close in {round}",
    "{first_name} was eliminated in {round}",
]

#: A second/subsequent day's brief mention of an elimination already
#: reported in full - see TournamentRunStatus.is_new_development's
#: docstring for why this stays short rather than repeating every detail.
#:
#: Elimination is a single, completed historical event, not an ongoing
#: state - none of these use "still"/"remains"/"continues to be" (or
#: similar present-progressive framing) to describe it, only simple past
#: tense ("ended", "came to an end"). A production incident (August 2026)
#: produced exactly that wrong framing ("Aryna's tournament run is still
#: over, eliminated back in the Round of 16.", "Linda remains out of the
#: draw here, having fallen in the Round of 16.") - this pool was
#: rewritten to fix it.
ELIMINATED_BRIEF: list[str] = [
    "{first_name}'s tournament run ended in {round}",
    "{possessive} run at this event ended in {round}",
    "{first_name}'s run came to an end in {round}",
]

#: The win just narrated in the same paragraph/segment is itself the
#: match that won her the title - deliberately doesn't repeat the score
#: (already said in the match sentence).
CHAMPION_JUST_NOW_WITH_TOURNAMENT: list[str] = [
    "that's the title at {tournament}",
    "with that win, {subject} claims the title at {tournament}",
    "that completes the run - {first_name} is the {tournament} champion",
]

CHAMPION_JUST_NOW_NO_TOURNAMENT: list[str] = [
    "that's the title",
    "with that win, {subject} claims the title",
    "that completes the run - a champion crowned",
]

#: First-time-reported title win that did *not* come from the match just
#: narrated in this same script (see ELIMINATED_OPENING_* above for the
#: same reasoning).
CHAMPION_OPENING: list[str] = [
    "{first_name} has won the title, going the distance through the draw",
    "{first_name} is the champion here, capping the week off with the trophy",
    "{first_name} claimed the title, winning the whole tournament",
]

#: Subsequent brief mention of an already-reported title.
CHAMPION_BRIEF: list[str] = [
    "{first_name} remains this tournament's champion",
    "{first_name} is still celebrating the title from this event",
]

#: A ranking-points figure earned this run, standing alone as its own
#: sentence (no previous-year data to add) - always says "ranking
#: points" explicitly (not just "points") so it's unmistakable what the
#: number represents.
POINTS_ONLY_SENTENCES: list[str] = [
    "that finish earns {first_name} {points} ranking points",
    "{first_name} picks up {points} ranking points for that result",
    "that's {points} ranking points banked for {first_name}",
]

#: Same as above, but with a trailing ``{history}`` clause (see
#: HISTORY_* below) folded into the same sentence via a natural
#: connector, rather than crammed on with a dash.
POINTS_WITH_HISTORY_SENTENCES: list[str] = [
    "that finish earns {first_name} {points} ranking points, {history}",
    "{first_name} picks up {points} ranking points for that result, {history}",
    "that's {points} ranking points for {first_name}, {history}",
]

#: The rarer case: a reliable previous-year comparison exists, but the
#: points table has no entry for this round/category (e.g. WTA Finals'
#: round-robin scoring) - phrased without a points figure at all.
HISTORY_ONLY_SENTENCES: list[str] = [
    "that's still {history}",
]

#: This year's result was further/better than last year's at the same
#: event (compared by round order, not points - see
#: tournament_status_narration.py). No determiner immediately precedes
#: {previous_round} in any of these - see the module docstring.
HISTORY_IMPROVED: list[str] = [
    "improving on {previous_round} {subject} reached here last year",
    "better than {previous_round} {subject} reached at this event last year",
    "a step up from {previous_round} {subject} managed here a year ago",
]

#: Same round reached both years.
HISTORY_MATCHED: list[str] = [
    "matching {previous_round} {subject} reached here a year ago",
    "the same result as {previous_round} last year",
]

#: This year's result was earlier/worse than last year's.
HISTORY_WORSE: list[str] = [
    "a step back from {previous_round} {subject} reached here last year",
    "short of {previous_round} {subject} managed at this event a year ago",
]

#: A defended title - the one case HISTORY_IMPROVED/MATCHED don't quite
#: cover, since "matching" undersells successfully defending a title.
HISTORY_DEFENDED_TITLE: list[str] = [
    "successfully defending the title {subject} won here last year",
    "backing up last year's title run with another one",
]

#: The net ranking-points swing once last year's result eventually rolls
#: off the rolling 52-week list - deliberately never phrased as "gained
#: ranking points" (that would wrongly imply an immediate rank change;
#: see wta_daily.models.TournamentRunStatus.points_delta's docstring).
#: Always appended (via "and"/a comma) directly after a HISTORY_* clause,
#: never as a standalone opener. ``{delta}`` is always passed in as a
#: positive number by the caller; the pool itself picks the
#: correctly-signed wording.
SWING_POSITIVE: list[str] = [
    " and a net gain of about {delta} points once last year's result rolls off the list",
    ", netting out to roughly {delta} points better off once the 52-week window turns over",
]

SWING_NEGATIVE: list[str] = [
    " and a net loss of about {delta} points once last year's result rolls off the list",
    ", netting out to roughly {delta} fewer points once the 52-week window turns over",
]

SWING_FLAT: list[str] = [
    " - a wash, points-wise, once last year's result rolls off the list",
]
