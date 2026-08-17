"""Text preprocessing applied only to what's sent to a text-to-speech
engine - never to ``script.txt``, ``report.json``, or any other
human-readable output.

This exists to fix one specific problem: tennis scores like
``"3-6,6-4,6-2"`` are perfectly clear written down, but ambiguous to a
general-purpose TTS engine - a hyphen between two digits reads naturally
as a numeric *range* ("three to six") rather than two separate game
counts, and stacking several of them with commas/spaces compounds the
confusion. There is no ElevenLabs feature that understands tennis score
*grammar* (its pronunciation-dictionary mechanism only matches literal,
finite strings - see :mod:`wta_daily.voice.pronunciation_dictionary` for
why that mechanism *is* the right fit for player names instead), so this
is solved with a small, general, rule-based normalizer rather than a
lookup table: any run of ``N-M`` or ``N-M(T)`` tokens, comma/space
separated, is spelled out in words with a natural pause between sets - the
same transformation applies to *any* score, current or future, not a
fixed list of "known" scores.

Deliberately narrow in scope: this module only ever touches text that is
about to be spoken, is applied by
:class:`~wta_daily.voice.elevenlabs_provider.ElevenLabsVoiceSynthesizer`
immediately before the API call, and never mutates ``script.txt`` on disk.
"""

from __future__ import annotations

import re

_ONES = [
    "zero",
    "one",
    "two",
    "three",
    "four",
    "five",
    "six",
    "seven",
    "eight",
    "nine",
    "ten",
    "eleven",
    "twelve",
    "thirteen",
    "fourteen",
    "fifteen",
    "sixteen",
    "seventeen",
    "eighteen",
    "nineteen",
]
_TENS = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]


def _number_to_words(value: int) -> str:
    """Spell out a small non-negative integer.

    Tennis game/tiebreak counts never realistically exceed the 20s (even a
    marathon final-set tiebreak), so this only needs to handle 0-99
    confidently; anything larger falls back to the plain digits rather
    than guessing at a word form nobody asked for.
    """

    if value < 0 or value >= 100:
        return str(value)
    if value < 20:
        return _ONES[value]
    tens, ones = divmod(value, 10)
    return _TENS[tens] if ones == 0 else f"{_TENS[tens]}-{_ONES[ones]}"


#: One "set" of a tennis score: two 1-2 digit game counts separated by a
#: hyphen, with an optional tiebreak point count in parentheses immediately
#: after the second number (e.g. "7-6(4)") - the only place that
#: parenthetical convention ever appears in a score string.
_SET_TOKEN = r"\d{1,2}-\d{1,2}(?:\(\d{1,2}\))?"
_SET_RE = re.compile(r"(\d{1,2})-(\d{1,2})(?:\((\d{1,2})\))?")

#: Matches one *or more* comma/space-separated score tokens as a single
#: span, e.g. "6-4 6-2", "6-4,6-2", or "7-6(4) 4-6 6-3". The surrounding
#: lookaround assertions require the span to be bounded by something other
#: than a digit or hyphen, so this can never clip into an unrelated,
#: longer digit-hyphen run (e.g. a "2026-08-15"-style date, should one ever
#: appear in narration text) - see test_narration_text.py's date-safety
#: tests for the regression this guards against.
_SCORE_SPAN_RE = re.compile(
    rf"(?<![\d-])(?:{_SET_TOKEN})(?:[,\s]+(?:{_SET_TOKEN}))*(?![\d-])"
)


def _spell_out_score_span(span: str) -> str:
    tokens = re.split(r"[,\s]+", span.strip())
    spelled: list[str] = []
    for token in tokens:
        match = _SET_RE.fullmatch(token)
        if match is None:  # pragma: no cover - defensive; _SCORE_SPAN_RE guarantees a match
            spelled.append(token)
            continue
        games_a, games_b, _tiebreak_points = match.groups()
        # The tiebreak point count (e.g. the "(4)" in "7-6(4)") is dropped
        # for speech, not mispronounced: reading it aloud as a third
        # number right after the set score ("seven six four") would read
        # as more confusing than informative, and the set score itself -
        # the fact that actually matters for narration - is unaffected.
        # It's still preserved correctly in report.json/script.txt.
        spelled.append(f"{_number_to_words(int(games_a))} {_number_to_words(int(games_b))}")
    return ", ".join(spelled)


def normalize_scores_for_speech(text: str) -> str:
    """Replace every tennis-score-shaped span in ``text`` with a spoken,
    words-only equivalent (e.g. ``"3-6,6-4,6-2"`` -> ``"three six, six
    four, six two"``), leaving everything else - including any other
    hyphenated number that isn't shaped like a score - untouched.
    """

    return _SCORE_SPAN_RE.sub(lambda m: _spell_out_score_span(m.group(0)), text)


def normalize_for_speech(text: str) -> str:
    """Apply every narration-only text transformation, in order.

    Currently just score normalization; kept as its own entry point so a
    future speech-only fixup (if one is ever needed) has one obvious place
    to be added without every caller needing to know the full list.
    """

    return normalize_scores_for_speech(text)
