"""Phrase pools used by :class:`~wta_daily.scripts_gen.template_generator.TemplateScriptGenerator`.

Kept in their own module so the wording can be tuned/extended (or swapped
for a different language) without touching the generator's control flow.
"""

from __future__ import annotations

OPENERS: list[str] = [
    "Welcome to today's {tour} Top {n} Update for {date}.",
    "Hello and welcome back to the {tour} Top {n} Update, here's what's happening on tour for {date}.",
    "It's time for your {tour} Top {n} Update, bringing you up to speed for {date}.",
    "Good day, tennis fans, and welcome to today's {tour} Top {n} rundown for {date}.",
]

CLOSERS: list[str] = [
    "That's everything you need to know from the top of the {game} today. We'll be back tomorrow with the latest.",  # noqa: E501
    "That wraps up today's update. Join us again tomorrow for the newest rankings and results from the {tour_long}.",  # noqa: E501
    "And that's a look at the {tour} Top {n} today. Thanks for watching, and we'll see you back here tomorrow.",  # noqa: E501
    "That's today's Top {n} in the books. Stay tuned for more as the tour rolls on.",
]

#: Used for every player story *except* the first one right after the
#: introduction (see FIRST_STORY_CONNECTORS below for why that one is
#: handled separately). Every phrase here presupposes - explicitly or
#: implicitly - that at least one other player has already been covered
#: this episode ("elsewhere", "meanwhile", "next up", "turning to", "now
#: to" all imply a shift *from* something), which is exactly what makes
#: them wrong for the very first story.
CONNECTORS: list[str] = [
    "Moving to number {rank}, ",
    "At number {rank}, ",
    "Next up, ",
    "Elsewhere in the Top {n}, ",
    "Meanwhile, ",
    "Now to number {rank}. ",
    "Turning to number {rank}, ",
    "",
]

#: Used only for the first Top N player story, immediately after the
#: introduction. Deliberately just the empty string: every phrase in
#: CONNECTORS above implies a preceding story to transition "from" or
#: "elsewhere" relative to, which doesn't exist yet at this point in the
#: script - see the module docstring's production-incident note. This is
#: intentionally not "Starting with the world number one..." or similar
#: manufactured filler either; the player's own sentence already reads
#: naturally as the first thing said, so nothing needs to be added before
#: it. Kept as its own named pool (rather than special-casing an empty
#: string inline) so the *reason* a caller reaches for it is obvious at
#: the call site, and so a future contributor extending this list knows
#: any addition must never presuppose a previous story.
FIRST_STORY_CONNECTORS: list[str] = [""]

MOVEMENT_UP: list[str] = [
    "climbs to world number {rank}",
    "has moved up to number {rank}",
    "jumps up to the number {rank} spot",
    "rises to number {rank} in the latest rankings",
    "is on the way up, now sitting at number {rank}",
    "improves to world number {rank}",
]

MOVEMENT_DOWN: list[str] = [
    "slips to number {rank}",
    "drops to number {rank} in the latest rankings",
    "falls to the number {rank} spot",
    "eases back to world number {rank}",
    "loses a little ground, now down at number {rank}",
]

MOVEMENT_SAME: list[str] = [
    "remains at number {rank}",
    "holds steady at number {rank}",
    "stays at number {rank}",
    "continues to sit at number {rank}",
    "is unchanged at number {rank}",
]

MOVEMENT_NEW: list[str] = [
    "enters the Top {n} this week at number {rank}",
    "breaks into the Top {n} for the first time in a while, debuting at number {rank}",
    "is a new face inside the Top {n}, arriving at number {rank}",
]

# Used only when there is no previous snapshot at all to compare against
# (typically the application's first-ever run for a tour). Deliberately
# neutral - it must never imply the player just arrived in the Top N, since
# on a baseline run every player looks "new" purely for lack of history.
MOVEMENT_UNKNOWN: list[str] = [
    "sits at number {rank} in today's rankings",
    "is ranked number {rank} today",
    "comes in at number {rank}",
    "holds down the number {rank} spot today",
]

MATCH_WIN: list[str] = [
    "defeated {opponent} {score} in the {round} at {tournament}",
    "got past {opponent} {score} to advance through the {round} at {tournament}",
    "came through against {opponent}, winning {score} in the {round} at {tournament}",
    "took care of business against {opponent}, {score}, in the {round} at {tournament}",
    "beat {opponent} {score} in a solid showing at {tournament}",
    "was the stronger player against {opponent}, closing it out {score} at {tournament}",
]

#: Used instead of MATCH_WIN whenever MatchResult.round is None - see
#: wta_daily.plugins.matches.wta_official's round-normalization docstring
#: for why a round can be legitimately unknown. Never substitutes a raw
#: provider code or a placeholder; simply omits the round clause.
MATCH_WIN_NO_ROUND: list[str] = [
    "defeated {opponent} {score} at {tournament}",
    "got past {opponent} {score} at {tournament}",
    "came through against {opponent}, winning {score} at {tournament}",
    "took care of business against {opponent}, {score}, at {tournament}",
    "beat {opponent} {score} in a solid showing at {tournament}",
    "was the stronger player against {opponent}, closing it out {score} at {tournament}",
]

MATCH_LOSS: list[str] = [
    "fell to {opponent} {score} in the {round} at {tournament}",
    "was defeated by {opponent}, {score}, at {tournament}",
    "suffered a loss to {opponent} in the {round} at {tournament}, going down {score}",
    "came up short against {opponent}, dropping a {score} decision at {tournament}",
    "was eliminated by {opponent} {score} in the {round} at {tournament}",
    "couldn't get past {opponent}, losing {score} in the {round} at {tournament}",
]

#: Used instead of MATCH_LOSS whenever MatchResult.round is None - see
#: MATCH_WIN_NO_ROUND's docstring.
MATCH_LOSS_NO_ROUND: list[str] = [
    "fell to {opponent} {score} at {tournament}",
    "was defeated by {opponent}, {score}, at {tournament}",
    "suffered a loss to {opponent}, going down {score} at {tournament}",
    "came up short against {opponent}, dropping a {score} decision at {tournament}",
    "was eliminated by {opponent} {score} at {tournament}",
    "couldn't get past {opponent}, losing {score} at {tournament}",
]

NO_MATCH: list[str] = [
    "did not play yesterday",
    "was off yesterday, with no completed match to report",
    "has no result from yesterday's play to bring you",
    "did not take the court yesterday",
]

#: Only ever mentioned for genuinely tight gaps (see
#: TemplateScriptGenerator._points_gap_sentence's threshold) and even then
#: only some of the time - a points gap is an occasional storyline, not a
#: field every player's paragraph is required to report. Never implies the
#: gap changed today; it's always the gap on the *current* official list.
POINTS_GAP_TEMPLATES: list[str] = [
    "That keeps {object} just {gap} points behind the player above {object}.",
    "{subject_cap} now trails number {rank_above} by a slim {gap} points.",
    "It's a tight gap of only {gap} points to the spot just above {object}.",
]

#: An occasional, deliberately vague acknowledgment that a win *could*
#: factor into the *next* official ranking publication - never a
#: specific projected rank/points claim (that's a separate, not-yet-built
#: "projected ranking" feature - see the README's "Official ranking vs.
#: daily match activity" section). Used selectively after a win (see
#: TemplateScriptGenerator's probability gate), never automatically for
#: every winning player every day, and never implies the *current*
#: official ranking already reflects this result.
NEXT_RANKING_NOTES: list[str] = [
    "That result could help {possessive} case when the next official rankings are released.",
    "It's exactly the sort of result that could matter once the next official list comes out.",
    "Results like that tend to add up by the time the next official rankings drop.",
    "That's the kind of win that could show up on the next official ranking update.",
]

#: The "why doesn't the ranking always match this week's results" filler
#: (see TemplateScriptGenerator._pad_to_target_length) - kept as a pool,
#: not one fixed sentence, so it doesn't become identical daily
#: boilerplate. Every variant is careful to say the *next* official
#: publication is where this week's results show up, never that rankings
#: update automatically once a tournament ends.
FIFTY_TWO_WEEK_NOTES: list[str] = [
    "As always, ranking points reflect results over the last fifty-two weeks. This week's "
    "matches can affect the picture when the next official {tour} rankings are released.",
    "A quick reminder: these rankings reflect a rolling fifty-two-week window. Nothing "
    "changes officially until the next scheduled {tour} ranking update.",
    "As always, today's points reflect fifty-two weeks of results - the next official "
    "rankings, whenever they're released, are where this week's matches will actually count.",
]
