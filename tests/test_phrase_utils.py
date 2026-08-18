from __future__ import annotations

import random

from wta_daily.scripts_gen.phrase_utils import PhraseCycler, format_score_for_narration


def test_format_score_adds_space_after_comma() -> None:
    assert format_score_for_narration("6-4,7-6(2)") == "6-4, 7-6(2)"


def test_format_score_handles_multiple_sets() -> None:
    assert format_score_for_narration("6-4,1-6,6-3") == "6-4, 1-6, 6-3"


def test_format_score_is_idempotent_when_already_spaced() -> None:
    assert format_score_for_narration("6-4, 7-6(2)") == "6-4, 7-6(2)"


def test_format_score_leaves_space_separated_scores_unchanged() -> None:
    """Some providers already separate sets with spaces, not commas -
    nothing to fix there."""

    assert format_score_for_narration("6-4 7-6(2)") == "6-4 7-6(2)"


def test_format_score_never_touches_the_original_string_object_semantics() -> None:
    """Display-only helper - never mutates, just returns a new formatted
    string; the underlying MatchResult.score itself is never touched by
    this function (callers pass a fresh copy for the sentence being built)."""

    original = "6-2,7-6(2)"
    formatted = format_score_for_narration(original)

    assert original == "6-2,7-6(2)"  # untouched
    assert formatted == "6-2, 7-6(2)"


def test_phrase_cycler_still_cycles_through_every_phrase_before_repeating() -> None:
    """Sanity check that the module's existing PhraseCycler behavior is
    untouched by this file's new addition."""

    rng = random.Random("seed")
    cycler = PhraseCycler(["a", "b", "c"], rng)
    drawn = {cycler.next() for _ in range(3)}

    assert drawn == {"a", "b", "c"}
