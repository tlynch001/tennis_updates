"""Phrase pools for the recurring, tongue-in-cheek featured-player segment.

This is the *only* place in the project where editorial commentary is
allowed to depart from strictly neutral broadcast language - see
:mod:`wta_daily.scripts_gen.phrases` for the factual Top N phrasing this is
deliberately kept separate from. Every fact substituted into these
templates (``{rank}``, ``{opponent}``, ``{score}``, ``{tournament}``,
``{round}``, ``{name}``) still comes straight from
:class:`~wta_daily.models.FeaturedPlayerReport`, built from the same
provider architecture as the Top N (see :mod:`wta_daily.pipeline`) - only
the *wording* around those facts has a sense of humor. ``{name}`` is
filled in with her *first* name by :mod:`wta_daily.scripts_gen.featured_player`
(her full name is only ever used once, in the segment's intro sentence -
see :mod:`wta_daily.scripts_gen.name_utils`), so every template here reads
naturally as a follow-up reference, not a re-introduction. See
:mod:`wta_daily.scripts_gen.featured_player` for how these are composed,
and the README's "Featured player" section for the tone guidelines.

Named ``AMERICA_FAVORITE_*`` because it's the one personality tuned for
Emma Navarro's ``tagline: america_favorite`` (see
:class:`~wta_daily.config.FeaturedPlayerConfig`), not because anything here
hardcodes her name - a future featured player could reuse this exact module
by pointing a different config entry at the same tagline, or a sibling
module could ship a different personality selected by a different tagline.
"""

from __future__ import annotations

#: Lead-ins introducing the segment. Always follows the legitimate Top N
#: coverage and always precedes the final sign-off - see
#: wta_daily.scripts_gen.template_generator.
AMERICA_FAVORITE_INTROS: list[str] = [
    "And before we go, a quick check on",
    "Of course, no update would be complete without a word on",
    "And now, the ranking that really matters to us:",
    "Before we wrap things up, let's check in with",
    "And finally, our obligatory visit with",
    "One more thing before we sign off -",
    "As always, we can't close things out without a mention of",
    "And now, a brief and entirely unbiased update on",
    "Before we go, a moment for",
]

#: The running "America's favorite" premise - keep this playful, never
#: phrased as if it were an actual poll result or verified fact.
AMERICA_FAVORITE_LABELS: list[str] = [
    "America's favorite player",
    "America's choice",
    "the people's champion",
    "our unofficial national favorite",
    "America's sweetheart of the rankings",
    "the player this program remains completely unbiased about",
    "the tour's most enthusiastically supported American",
    "the one player we're contractually incapable of covering neutrally",
    "the reigning champion of this show's affections",
]

#: Used when she's outside the Top N - hints at an "inevitable" return
#: without ever making a mathematically specific claim (no "just two wins
#: away" style promises - see wta_daily.scripts_gen.featured_player).
AMERICA_FAVORITE_PURSUIT: list[str] = [
    "the climb back toward the Top {n} continues",
    "we're treating that ranking as strictly temporary",
    "the Top {n} might want to keep an eye over its shoulder",
    "surely just a matter of time before the Top {n} comes calling",
    "the comeback campaign rolls on",
    "still lurking just outside the neighborhood she belongs in",
    "we're keeping a seat warm in the Top {n} regardless",
    "another step on the way back to where she belongs",
    "the Top {n} remains, in our completely biased view, only a matter of time",
    "the case for a return to the Top {n} keeps building",
    "we remain confident the Top {n} is next on the itinerary",
]

#: Used the (rarer) day she's actually inside the Top N. Never continues
#: framing the Top N as something still being chased.
AMERICA_FAVORITE_ARRIVED: list[str] = [
    "America's favorite has officially arrived in the Top {n}",
    "the rankings have finally caught up with us",
    "the Top {n} has recognized what we've known all along",
    "official confirmation of what this program has been saying for a while now",
    "the rest of the Top {n} has some company it should get used to",
    "no longer a prediction - she's actually there",
    "the Top {n} welcomes a name that's been overdue for a while",
]

#: The one-time special case: reaching world No. 1 for real. The joke
#: shifts from "official vs. unofficial ranking" to simply celebrating a
#: now entirely real result - see wta_daily.scripts_gen.featured_player.
AMERICA_FAVORITE_NUMBER_ONE: list[str] = [
    "for once, our biased ranking and the official one are in perfect agreement",
    "the unofficial and the official rankings have finally become the same thing",
    "there's no punchline left to make here - she's simply the best in the world",
    "we'd normally make a joke about this, but the actual result speaks for itself",
    "the only ranking that ever mattered around here is now also the real one",
]

#: The "#1 in our hearts" bit - meant to surface occasionally (see
#: wta_daily.scripts_gen.featured_player's probability gate), never as a
#: daily refrain, and never once she's genuinely reached No. 1.
AMERICA_FAVORITE_HEARTS: list[str] = [
    "officially number {rank}, unofficially number one around here",
    "the computer may say {rank}; our rankings remain unchanged",
    "number {rank} according to the WTA, number one according to an extremely biased editorial board",  # noqa: E501
    "still holding the only ranking that actually matters around here",
    "number {rank} on paper, number one in spirit",
    "the WTA has her at {rank}; we have her exactly where we've always had her",
]

#: Movement-flavored fragments - the same up/down/same/new/unknown
#: vocabulary as the official Top N (see wta_daily.models.Movement), just
#: with a lighter touch. Never claims a change that didn't happen.
AMERICA_FAVORITE_MOVEMENT_UP: list[str] = [
    "climbing to number {rank}",
    "on the move, up to number {rank}",
    "picking up ground, now at number {rank}",
    "trending in the right direction at number {rank}",
    "making up ground, now sitting at number {rank}",
]

AMERICA_FAVORITE_MOVEMENT_DOWN: list[str] = [
    "at number {rank} after a small step back",
    "sitting at number {rank} for the moment",
    "down slightly to number {rank}",
    "easing back a touch to number {rank}",
]

AMERICA_FAVORITE_MOVEMENT_SAME: list[str] = [
    "holding steady at number {rank}",
    "parked at number {rank} for another day",
    "still at number {rank}",
    "unchanged at number {rank}",
]

AMERICA_FAVORITE_MOVEMENT_NEW: list[str] = [
    "newly back on our radar at number {rank}",
    "freshly tracked at number {rank}",
    "back on the board at number {rank}",
]

AMERICA_FAVORITE_MOVEMENT_UNKNOWN: list[str] = [
    "sitting at number {rank} today",
    "currently at number {rank}",
    "coming in at number {rank}",
]

#: Match-result phrasing. `{favorite}` and `{name}` are both available, so
#: consecutive sentences don't have to lean on the same noun phrase twice.
AMERICA_FAVORITE_WIN: list[str] = [
    "{favorite} had a good day at {tournament}, with {name} getting past {opponent} {score}",
    "{name} came through against {opponent} {score} at {tournament}",
    "{favorite} kept it rolling with a {score} win over {opponent} at {tournament}",
    "{name} took care of {opponent} {score} in the {round} at {tournament}",
    "a solid day for {favorite}, who beat {opponent} {score} at {tournament}",
]

AMERICA_FAVORITE_LOSS: list[str] = [
    "{name} fell to {opponent} {score}",
    "{favorite} came up short against {opponent}, {score}",
    "a tougher day for {favorite}, who lost to {opponent} {score} in the {round} at {tournament}",
    "{name} couldn't get past {opponent}, dropping a {score} decision at {tournament}",
    "{favorite} was edged out by {opponent} {score} at {tournament}",
]

#: Soft, supportive follow-ups appended after a loss - never minimizes the
#: result, just keeps the tone kind.
AMERICA_FAVORITE_LOSS_SUPPORT: list[str] = [
    "a temporary setback for {favorite}, whose completely unbiased supporters remain confident",
    "these things happen - the charge back toward the Top {n} resumes soon enough",
    "one result changes nothing about where this is all heading, as far as we're concerned",
    "the comeback timeline gets pushed back a day, not cancelled",
]

AMERICA_FAVORITE_NO_MATCH: list[str] = [
    "{name} had the day off yesterday",
    "no match to report for {name} yesterday",
    "{favorite} didn't take the court yesterday",
    "a quiet day off the court for {name}",
    "yesterday was a rest day for {name}",
]

#: Used only when the underlying match lookup for the target date genuinely
#: failed - never a substitute for a real result, and never a guess.
AMERICA_FAVORITE_MATCH_UNKNOWN: list[str] = [
    "yesterday's result couldn't be confirmed in time for today's update",
    "we don't have a confirmed result for yesterday just yet",
    "today's sources hadn't confirmed yesterday's result by air time",
]
