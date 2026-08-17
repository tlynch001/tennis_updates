"""Unit tests for :mod:`wta_daily.voice.narration_text`'s score normalizer.

Covers the exact problem reported: TTS reading a score's hyphen as a
numeric range, common score/tiebreak notations from our real providers,
and a regression guard against clipping into unrelated hyphenated numbers
(e.g. a date) that happen to appear near a real score in a sentence.
"""

from __future__ import annotations

from wta_daily.voice.narration_text import normalize_for_speech, normalize_scores_for_speech


def test_basic_two_set_score_matches_the_reported_example() -> None:
    """The exact example from the pronunciation bug report."""

    assert normalize_scores_for_speech("3-6,6-4,6-2") == "three six, six four, six two"


def test_space_separated_score() -> None:
    assert normalize_scores_for_speech("6-4 6-2") == "six four, six two"


def test_single_set_score() -> None:
    assert normalize_scores_for_speech("6-4") == "six four"


def test_score_embedded_in_a_full_sentence() -> None:
    text = "Aryna Sabalenka defeated Elena Rybakina 6-4,6-2 in the Final at Cincinnati."
    result = normalize_scores_for_speech(text)

    assert "6-4" not in result
    assert "six four, six two" in result
    # Everything else in the sentence is untouched.
    assert "Aryna Sabalenka defeated Elena Rybakina" in result
    assert "in the Final at Cincinnati." in result


def test_tiebreak_notation_does_not_confuse_the_output() -> None:
    """A tiebreak sub-score like "(4)" must not leak into the spoken form
    as a spurious extra number - the set score itself is still spoken
    correctly, just without an ambiguous trailing digit."""

    result = normalize_scores_for_speech("7-6(4) 4-6 6-3")

    assert result == "seven six, four six, six three"


def test_multiple_tiebreaks_in_one_score() -> None:
    result = normalize_scores_for_speech("7-6(3) 6-7(9) 7-6(2)")

    assert result == "seven six, six seven, seven six"


def test_double_digit_super_tiebreak_games() -> None:
    """Deciding-set super tiebreaks can run into double digits."""

    assert normalize_scores_for_speech("6-7(8) 7-6(11) 10-8") == "six seven, seven six, ten eight"


def test_zero_is_spelled_out() -> None:
    assert normalize_scores_for_speech("6-0 6-0") == "six zero, six zero"


def test_teens_are_spelled_out_correctly() -> None:
    # Not a realistic tennis score, but exercises the 13-19 "teen" branch
    # of the number-to-words table distinctly from the tens branch.
    assert normalize_scores_for_speech("13-15") == "thirteen fifteen"


def test_does_not_touch_a_four_digit_year_looking_like_a_date() -> None:
    """Regression guard: a hyphenated date must never be misread as (or
    clipped into) a tennis score."""

    text = "The tournament ran through 2026-08-15 without incident."

    assert normalize_scores_for_speech(text) == text


def test_score_immediately_followed_by_a_date_like_string_is_still_isolated() -> None:
    """Even when a real score and something date-shaped are close together,
    only the genuine score span should be transformed."""

    text = "She won 6-4,6-2 on 2026-08-15."
    result = normalize_scores_for_speech(text)

    assert "six four, six two" in result
    assert "2026-08-15" in result  # untouched


def test_non_score_hyphenated_text_is_left_alone() -> None:
    text = "The player is a well-known, hard-hitting veteran."

    assert normalize_scores_for_speech(text) == text


def test_score_at_the_end_of_a_sentence_keeps_its_period() -> None:
    text = "She won 6-4, 6-2."
    result = normalize_scores_for_speech(text)

    assert result == "She won six four, six two."


def test_score_followed_by_a_comma_in_prose() -> None:
    text = "After winning 6-4, 6-2, she celebrated."
    result = normalize_scores_for_speech(text)

    assert "six four, six two" in result
    assert result.endswith("she celebrated.")


def test_empty_and_score_free_text_are_unaffected() -> None:
    assert normalize_scores_for_speech("") == ""
    assert normalize_scores_for_speech("No scores here at all.") == "No scores here at all."


def test_normalize_for_speech_is_the_public_entry_point() -> None:
    """normalize_for_speech is what the ElevenLabs provider actually calls -
    verify it delegates to the score normalizer (and leaves room for future
    additions without callers needing to know the full list)."""

    text = "Final score: 6-4,6-2."
    assert normalize_for_speech(text) == normalize_scores_for_speech(text)
