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
from collections.abc import Iterable

from wta_daily.config import ScriptConfig
from wta_daily.models import DailyReport, Movement, PlayerReport
from wta_daily.plugins.base import ScriptGenerator
from wta_daily.plugins.registry import script_registry
from wta_daily.scripts_gen import phrases


class _PhraseCycler:
    """Yields phrases from a shuffled pool, reshuffling once exhausted.

    Reshuffling (rather than reusing simple round-robin order) means the
    *order* of repeats also varies day to day, while still guaranteeing every
    phrase in the pool gets used before any phrase repeats.
    """

    def __init__(self, phrase_pool: Iterable[str], rng: random.Random) -> None:
        self._phrases = list(phrase_pool)
        self._rng = rng
        self._remaining: list[str] = []

    def next(self) -> str:
        if not self._remaining:
            self._remaining = list(self._phrases)
            self._rng.shuffle(self._remaining)
        return self._remaining.pop()


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
            "up": _PhraseCycler(phrases.MOVEMENT_UP, rng),
            "down": _PhraseCycler(phrases.MOVEMENT_DOWN, rng),
            "same": _PhraseCycler(phrases.MOVEMENT_SAME, rng),
            "new": _PhraseCycler(phrases.MOVEMENT_NEW, rng),
            "unknown": _PhraseCycler(phrases.MOVEMENT_UNKNOWN, rng),
            "win": _PhraseCycler(phrases.MATCH_WIN, rng),
            "loss": _PhraseCycler(phrases.MATCH_LOSS, rng),
            "no_match": _PhraseCycler(phrases.NO_MATCH, rng),
            "gap": _PhraseCycler(phrases.POINTS_GAP_TEMPLATES, rng),
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

        closer = rng.choice(phrases.CLOSERS).format(n=n)
        return f"{body}\n\n{closer}"

    def _player_paragraph(
        self,
        player: PlayerReport,
        report: DailyReport,
        index: int,
        n: int,
        cyclers: dict[str, _PhraseCycler],
        rng: random.Random,
    ) -> str:
        connector = cyclers["connector"].next().format(rank=player.rank, n=n)

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

        if player.match_error:
            sentence += f", though her latest result couldn't be confirmed today ({player.match_error})."
        elif player.match is None:
            sentence += f", and {cyclers['no_match'].next()}."
        else:
            pool = cyclers["win"] if player.match.won else cyclers["loss"]
            match_clause = pool.next().format(
                opponent=player.match.opponent,
                score=player.match.score,
                round=player.match.round,
                tournament=player.match.tournament,
            )
            sentence += f" after she {match_clause}."

        extra = self._points_gap_sentence(player, report, index, cyclers)
        if extra:
            sentence += f" {extra}"

        return sentence

    @staticmethod
    def _points_gap_sentence(
        player: PlayerReport, report: DailyReport, index: int, cyclers: dict[str, _PhraseCycler]
    ) -> str | None:
        if index == 0:
            return None
        above = report.players[index - 1]
        gap = above.points - player.points
        if gap <= 0 or gap > 400:
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
        """

        target_words = self._config.words_per_minute * self._config.target_minutes_low
        word_count = len(body.split())
        if word_count >= target_words:
            return body
        filler = (
            "\n\nAs always, ranking points reflect performance over the last fifty-two weeks, "
            "so a single result can shuffle several places once a big tournament wraps up."
        )
        return body + filler
