"""Small shared helper for shuffled, non-repeating phrase selection.

Used by both :mod:`wta_daily.scripts_gen.template_generator` (the official
Top N narration) and :mod:`wta_daily.scripts_gen.featured_player` (the
editorial featured-player segment) so both get the same "every phrase in
the pool gets used before any phrase repeats, and the repeat order itself
varies day to day" behavior from one implementation.
"""

from __future__ import annotations

import random
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
