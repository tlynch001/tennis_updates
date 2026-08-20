"""Deterministic, template-based narration script generator.

This is the default script generator: it needs no external API key and runs
fully offline, which keeps the Phase 1 prototype runnable end-to-end without
any paid dependency. It still follows the brief closely:

* Sounds conversational, professional-broadcast in tone.
* Mentions ranking movement only when it happened (using "remains"/"holds
  steady" language for unchanged ranks, matching the example in the brief).
* Varies its wording player to player using shuffled phrase pools (see
  :mod:`wta_daily.scripts_gen.phrases`) so consecutive updates don't read as
  a mechanical mail-merge.
* Targets a configurable narration length window (default 5-8 minutes) by
  padding each player's blurb with an optional "how close is the gap above
  her" sentence when there is column inches to spare.

A more sophisticated, LLM-backed generator (:mod:`wta_daily.scripts_gen.openai_generator`)
implements the same :class:`~wta_daily.plugins.base.ScriptGenerator` interface
and can be swapped in purely via configuration once an API key is available.
"""

from __future__ import annotations

import random

from wta_daily.config import ScriptConfig
from wta_daily.models import DailyReport, Movement, PlayerReport
from wta_daily.plugins.base import ScriptGenerator
from wta_daily.plugins.registry import script_registry
from wta_daily.scripts_gen import featured_player, phrases
from wta_daily.scripts_gen.phrase_utils import PhraseCycler as _PhraseCycler
from wta_daily.scripts_gen.phrase_utils import format_score_for_narration
from wta_daily.scripts_gen.tournament_status_narration import (
    build_tournament_status_sentence,
    supersedes_inactivity_narration,
)

#: A points gap is only treated as a storyline worth mentioning when it's
#: genuinely tight - see _points_gap_sentence. Loosened past this, nearly
#: every consecutive pair in a Top 10 has *some* gap, which is exactly
#: what made the narration sound like it was reciting a required field
#: rather than picking out something noteworthy.
_POINTS_GAP_NOTEWORTHY_THRESHOLD = 100

#: Even a genuinely tight gap isn't mentioned every time - an occasional
#: storyline reads better than a guaranteed one.
_POINTS_GAP_MENTION_PROBABILITY = 0.6

#: How often a win is followed by the (deliberately vague, never
#: rank/points-specific) "this could matter for the next official
#: rankings" note - an occasional aside, not a guaranteed addition to
#: every winning player's paragraph.
_NEXT_RANKING_NOTE_PROBABILITY = 0.25


@script_registry.register("template")
class TemplateScriptGenerator(ScriptGenerator):
    """Builds a narration script from shuffled, professional-sounding phrase pools."""

    def __init__(self, script_config: ScriptConfig | None = None, **_ignored: object) -> None:
        self._config = script_config or ScriptConfig()

    def generate(self, report: DailyReport) -> str:
        rng = random.Random(f"{report.report_date.isoformat()}:{report.tour}")
        n = len(report.players)
        date_str = f"{report.report_date:%A, %B} {report.report_date.day}, {report.report_date.year}"

        cyclers = {
            "connector": _PhraseCycler(phrases.CONNECTORS, rng),
            "connector_first": _PhraseCycler(phrases.FIRST_STORY_CONNECTORS, rng),
            "up": _PhraseCycler(phrases.MOVEMENT_UP, rng),
            "down": _PhraseCycler(phrases.MOVEMENT_DOWN, rng),
            "same": _PhraseCycler(phrases.MOVEMENT_SAME, rng),
            "new": _PhraseCycler(phrases.MOVEMENT_NEW, rng),
            "unknown": _PhraseCycler(phrases.MOVEMENT_UNKNOWN, rng),
            "win": _PhraseCycler(phrases.MATCH_WIN, rng),
            "loss": _PhraseCycler(phrases.MATCH_LOSS, rng),
            "no_match": _PhraseCycler(phrases.NO_MATCH, rng),
            "gap": _PhraseCycler(phrases.POINTS_GAP_TEMPLATES, rng),
            "next_ranking_note": _PhraseCycler(phrases.NEXT_RANKING_NOTES, rng),
        }

        # Build everything except the final sign-off first, so any length
        # padding (_pad_to_target_length) is inserted *before* it. The
        # sign-off must always be the last thing spoken - see
        # _pad_to_target_length's docstring for the production bug this
        # ordering fixes.
        body_paragraphs = [rng.choice(phrases.OPENERS).format(n=n, date=date_str)]
        for index, player in enumerate(report.players):
            body_paragraphs.append(self._player_paragraph(player, report, index, n, cyclers, rng))

        body = "\n\n".join(body_paragraphs)
        body = self._pad_to_target_length(body, cyclers, rng)

        # The featured-player segment (if configured) always runs after the
        # legitimate Top N coverage and before the final sign-off - never
        # the other way around. Reuses the same per-run `rng` so its
        # wording still varies day to day, but only ever draws from it when
        # the segment actually exists, so a report with no featured player
        # (the default) produces byte-identical output to before this
        # feature existed.
        segment = (
            featured_player.build_segment(report.featured_player, top_n=n, rng=rng)
            if report.featured_player is not None
            else None
        )

        closer = rng.choice(phrases.CLOSERS).format(n=n)
        parts = [body]
        if segment:
            parts.append(segment)
        parts.append(closer)
        return "\n\n".join(parts)

    def _player_paragraph(
        self,
        player: PlayerReport,
        report: DailyReport,
        index: int,
        n: int,
        cyclers: dict[str, _PhraseCycler],
        rng: random.Random,
    ) -> str:
        # The very first player story runs directly after the introduction,
        # with no earlier story to transition "from" - continuation-style
        # language like "Elsewhere in the Top N" or "Meanwhile" is only
        # sensible starting with the second story onward. See
        # phrases.FIRST_STORY_CONNECTORS's docstring.
        connector_pool = cyclers["connector_first"] if index == 0 else cyclers["connector"]
        connector = connector_pool.next().format(rank=player.rank, n=n)

        movement_clause = {
            Movement.UP: cyclers["up"].next(),
            Movement.DOWN: cyclers["down"].next(),
            Movement.SAME: cyclers["same"].next(),
            Movement.NEW: cyclers["new"].next(),
            Movement.UNKNOWN: cyclers["unknown"].next(),
        }[player.movement].format(rank=player.rank, n=n)

        if connector:
            sentence = f"{connector}{player.name} {movement_clause}"
        else:
            sentence = f"{player.name} {movement_clause}"

        # Once we know a player's tournament run is already over
        # (eliminated or champion), a generic "no match to report"/
        # "couldn't be confirmed" filler about *yesterday specifically*
        # reads as an odd non-sequitur right next to that more important
        # news - the elimination/title context appended below takes
        # precedence instead. A genuine win/loss match result for the
        # target date is never suppressed by this - only the "we have
        # nothing to say either way" filler is.
        superseded = supersedes_inactivity_narration(player.tournament_status)
        if player.match_error:
            sentence += (
                "."
                if superseded
                else ", though yesterday's results couldn't be confirmed for the tour today."
            )
        elif player.match is None:
            sentence += "." if superseded else f", and {cyclers['no_match'].next()}."
        else:
            pool = cyclers["win"] if player.match.won else cyclers["loss"]
            match_clause = pool.next().format(
                opponent=player.match.opponent,
                score=format_score_for_narration(player.match.score),
                round=player.match.round,
                tournament=player.match.tournament,
            )
            sentence += f" after she {match_clause}."

            # Deliberately vague, occasional, and win-only - see
            # phrases.NEXT_RANKING_NOTES's docstring. This never touches
            # the *current* official rank/movement; it's purely a spoken
            # aside about the *next* publication.
            if player.match.won and rng.random() < _NEXT_RANKING_NOTE_PROBABILITY:
                sentence += f" {cyclers['next_ranking_note'].next()}"

        extra = self._points_gap_sentence(player, report, index, cyclers, rng)
        if extra:
            sentence += f" {extra}"

        status_sentence = build_tournament_status_sentence(
            player.tournament_status, player.name, rng, match=player.match
        )
        if status_sentence:
            sentence += f" {status_sentence}"

        return sentence

    @staticmethod
    def _points_gap_sentence(
        player: PlayerReport,
        report: DailyReport,
        index: int,
        cyclers: dict[str, _PhraseCycler],
        rng: random.Random,
    ) -> str | None:
        """An occasional storyline, not a required field - see
        _POINTS_GAP_NOTEWORTHY_THRESHOLD/_POINTS_GAP_MENTION_PROBABILITY's
        docstrings for why this is deliberately selective rather than
        firing for every player with any positive gap to the rank above."""

        if index == 0:
            return None
        above = report.players[index - 1]
        gap = above.points - player.points
        if gap <= 0 or gap > _POINTS_GAP_NOTEWORTHY_THRESHOLD:
            return None
        if rng.random() >= _POINTS_GAP_MENTION_PROBABILITY:
            return None
        return cyclers["gap"].next().format(gap=gap, rank_above=above.rank)

    def _pad_to_target_length(
        self, body: str, cyclers: dict[str, _PhraseCycler], rng: random.Random
    ) -> str:
        """Best-effort nudge toward the configured target word count.

        The template generator's natural output usually already lands inside
        the target window for a Top 10; this only adds a short informational
        note (never fabricated stats) if the script is unusually short, and
        never truncates content to force it shorter.

        Called on the narration *body*, before the final sign-off is
        appended by :meth:`generate` - contextual filler like this must
        never end up after the sign-off, which was a production bug (the
        closer "...we'll see you back here tomorrow" was followed by an
        unrelated ranking-points note, so the actual final spoken line
        wasn't the sign-off at all).

        Picked from :data:`phrases.FIFTY_TWO_WEEK_NOTES` rather than one
        fixed sentence, so a short script doesn't read identically every
        day it needs padding - see that pool's docstring for why every
        variant is careful to say the *next* official publication is where
        this week's results show up, never that rankings update
        automatically once a tournament ends.
        """

        target_words = self._config.words_per_minute * self._config.target_minutes_low
        word_count = len(body.split())
        if word_count >= target_words:
            return body
        return body + "\n\n" + rng.choice(phrases.FIFTY_TWO_WEEK_NOTES)
