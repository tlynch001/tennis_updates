"""Tiny, name-only helper for natural first-name usage after a player's
full name has already been introduced in narration.

General-purpose - used by both :mod:`wta_daily.scripts_gen.template_generator`
(Top N players) and :mod:`wta_daily.scripts_gen.featured_player` (the
featured player), never hard-coded for any specific player. The rule this
supports: introduce a player by her full name once, then prefer her first
name (or a pronoun, decided by the caller) for the rest of that segment,
rather than mechanically repeating the full name sentence after sentence.
"""

from __future__ import annotations


def first_name(full_name: str) -> str:
    """The first whitespace-separated token of ``full_name``.

    Falls back to the whole (stripped) string for a single-word name or
    empty input - this never raises and never returns an empty string for
    a non-empty input, so callers can always safely substitute the result
    into a sentence.
    """

    parts = full_name.strip().split()
    return parts[0] if parts else full_name.strip()
