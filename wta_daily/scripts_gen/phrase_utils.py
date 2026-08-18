"""Small shared helper for shuffled, non-repeating phrase selection.

Used by both :mod:`wta_daily.scripts_gen.template_generator` (the official
Top N narration) and :mod:`wta_daily.scripts_gen.featured_player` (the
editorial featured-player segment) so both get the same "every phrase in
the pool gets used before any phrase repeats, and the repeat order itself
varies day to day" behavior from one implementation.
"""

from __future__ import annotations

import random
import re
from collections.abc import Iterable


class PhraseCycler:
    """Yields phrases from a shuffled pool, reshuffling once exhausted."""

    def __init__(self, phrase_pool: Iterable[str], rng: random.Random) -> None:
        self._phrases = list(phrase_pool)
        self._rng = rng
        self._remaining: list[str] = []

    def next(self) -> str:
        if not self._remaining:
            self._remaining = list(self._phrases)
            self._rng.shuffle(self._remaining)
        return self._remaining.pop()


#: Matches a comma not already followed by whitespace - i.e. exactly the
#: set-separator style used by MatchResult.score (e.g. "6-4,7-6(2)"), never
#: a comma that's already spaced or embedded in something else.
_SCORE_COMMA_RE = re.compile(r",(?!\s)")


def format_score_for_narration(score: str) -> str:
    """Add a space after each set-separating comma for narration/script
    readability (e.g. ``"6-4,7-6(2)"`` -> ``"6-4, 7-6(2)"``).

    Display/narration formatting only - the underlying
    ``MatchResult.score`` value (as used in ``report.json``, graphics, and
    the YouTube description) is never modified; this is applied only where
    a score is substituted into a spoken narration sentence. Idempotent
    and a no-op for scores that don't use a comma separator at all.
    """

    return _SCORE_COMMA_RE.sub(", ", score)
