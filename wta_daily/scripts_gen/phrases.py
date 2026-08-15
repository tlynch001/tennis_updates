"""Phrase pools used by :class:`~wta_daily.scripts_gen.template_generator.TemplateScriptGenerator`.

Kept in their own module so the wording can be tuned/extended (or swapped
for a different language) without touching the generator's control flow.
"""

from __future__ import annotations

OPENERS: list[str] = [
    "Welcome to today's WTA Top {n} Update for {date}.",
    "Hello and welcome back to the WTA Top {n} Update, here's what's happening on tour for {date}.",
    "It's time for your WTA Top {n} Update, bringing you up to speed for {date}.",
    "Good day, tennis fans, and welcome to today's WTA Top {n} rundown for {date}.",
]

CLOSERS: list[str] = [
    "That's everything you need to know from the top of the women's game today. We'll be back tomorrow with the latest.",  # noqa: E501
    "That wraps up today's update. Join us again tomorrow for the newest rankings and results from the WTA Tour.",  # noqa: E501
    "And that's a look at the WTA Top {n} today. Thanks for watching, and we'll see you back here tomorrow.",
    "That's today's Top {n} in the books. Stay tuned for more as the tour rolls on.",
]

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

MATCH_LOSS: list[str] = [
    "fell to {opponent} {score} in the {round} at {tournament}",
    "was defeated by {opponent}, {score}, at {tournament}",
    "suffered a loss to {opponent} in the {round} at {tournament}, going down {score}",
    "came up short against {opponent}, dropping a {score} decision at {tournament}",
    "was eliminated by {opponent} {score} in the {round} at {tournament}",
    "couldn't get past {opponent}, losing {score} in the {round} at {tournament}",
]

NO_MATCH: list[str] = [
    "hasn't completed a match since our last update",
    "is yet to take the court since we last checked in",
    "has no new result to report today",
]

POINTS_GAP_TEMPLATES: list[str] = [
    "That keeps her just {gap} points behind the player above her.",
    "She now trails number {rank_above} by a slim {gap} points.",
    "It's a tight gap of only {gap} points to the spot just above her.",
]
