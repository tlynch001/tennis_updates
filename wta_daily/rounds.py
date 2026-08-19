"""Normalizes WTA tournament round identifiers into a small, stable set of
codes, and turns those codes into natural spoken-language labels.

Two different vocabularies exist in this codebase and must not be confused:

* The **narrow, stable set** this module defines - ``R128``/``R64``/``R32``/
  ``R16``/``QF``/``SF``/``F``/``W`` - is what :mod:`wta_daily.points_table`
  is keyed on, and what a normal-form ``round_reached`` field means
  anywhere in a report. This set never changes shape.
* The raw ``round_name``/``RoundID`` values individual API responses use
  (e.g. the WTA backend's numeric ``"1"``/``"2"``/``"3"``/``"4"`` for
  pre-quarterfinal rounds, or its single-letter ``"Q"``/``"S"``/``"F"``) -
  see :func:`normalize_wta_round_id` for how those map onto the stable set.

Why this needs a draw size at all: the WTA backend's numeric round IDs are
relative to *that specific tournament's* draw, not an absolute round
number - round ``"1"`` is the Round of 128 in a 96-draw WTA 1000 but the
Round of 64 in a 56-draw one. See the module's :data:`_ROUND_LADDER` and
:func:`normalize_wta_round_id`'s docstring for exactly how a draw size
resolves this.
"""

from __future__ import annotations

import math

#: The narrow, stable set every round reference in this codebase should
#: eventually normalize to, ordered from earliest to latest. ``W`` (won
#: the final) is deliberately distinct from ``F`` (reached the final but
#: lost it) - they earn different ranking points and read very differently
#: in narration.
ROUND_ORDER: list[str] = ["R128", "R64", "R32", "R16", "QF", "SF", "F", "W"]

_ROUND_RANK: dict[str, int] = {code: i for i, code in enumerate(ROUND_ORDER)}

#: Rounds strictly before the quarterfinals, ordered from *latest* to
#: *earliest* - index 0 is always "the round immediately before QF"
#: regardless of how many numbered rounds a particular draw has.
_ROUND_LADDER: list[str] = ["R16", "R32", "R64", "R128"]

_LETTER_ROUNDS: dict[str, str] = {"Q": "QF", "QF": "QF", "S": "SF", "SF": "SF", "F": "F"}


def round_rank(round_code: str) -> int | None:
    """Position of ``round_code`` in :data:`ROUND_ORDER` (higher = later
    in the tournament), or ``None`` for an unrecognized code. Used to
    compare two rounds (e.g. "is this year's result better than last
    year's?") without hard-coding tournament-specific ladder logic at
    every call site.
    """

    return _ROUND_RANK.get(round_code)


def _rounds_before_quarterfinal(draw_size: int | None) -> int:
    """How many numbered rounds (Round of X) precede the quarterfinals in
    a draw of this size.

    Draws are padded with byes to the next power of two for bracket
    purposes (e.g. a real 96-entry draw plays out as a Round-of-128
    bracket), so this rounds ``draw_size`` up to the nearest power of two
    first. Defaults to 4 (a 128-style draw - Grand Slams and the largest
    WTA 1000s) when ``draw_size`` is unknown, since that's the most common
    case among the tournaments a Top N report is likely to cover; this is
    a best-effort default, not a guarantee - see the module docstring.
    """

    if not draw_size or draw_size <= 8:
        return 4
    bracket_size = 2 ** math.ceil(math.log2(draw_size))
    rounds = int(math.log2(bracket_size)) - 3  # bracket_size == 8 means "just the QF onward"
    return max(rounds, 1)


def normalize_wta_round_id(round_id: str, *, draw_size: int | None = None) -> str | None:
    """Normalize the WTA backend's raw ``RoundID`` (as seen on a main-draw,
    singles tournament-matches fixture - see
    :mod:`wta_daily.plugins.matches.wta_official`) into the stable
    :data:`ROUND_ORDER` vocabulary.

    ``"Q"``/``"S"``/``"F"`` map directly to ``QF``/``SF``/``F`` - those are
    unambiguous regardless of draw size. A numeric round (``"1"``, ``"2"``,
    ...) is relative to the draw, so it's resolved against
    :func:`_rounds_before_quarterfinal`: the *last* numbered round before
    the quarterfinals is always ``R16``, the one before that ``R32``, and
    so on - e.g. round ``"4"`` is ``R16`` in a 4-numbered-round (128-style)
    draw but would be out of range (returns ``None``) in a 2-numbered-round
    (32-style) draw. Never guesses ``W`` (winning the final) - the caller
    that already knows who won a given fixture is responsible for that
    distinction (see :mod:`wta_daily.plugins.matches.wta_official`).

    Returns ``None`` for anything unrecognized (qualifying rounds, doubles
    placeholders, junk data) rather than a wrong guess.
    """

    if round_id in _LETTER_ROUNDS:
        return _LETTER_ROUNDS[round_id]
    if not round_id.isdigit():
        return None

    numbered_rounds = _rounds_before_quarterfinal(draw_size)
    n = int(round_id)
    if n < 1 or n > numbered_rounds:
        return None
    # n == numbered_rounds -> R16 (ladder index 0); n == 1 -> the earliest
    # numbered round this draw actually has.
    ladder_index = numbered_rounds - n
    if ladder_index >= len(_ROUND_LADDER):
        return None
    return _ROUND_LADDER[ladder_index]


#: Grand Slams are conventionally narrated by ordinal round number ("the
#: fourth round") in mainstream tennis commentary; other tour levels are
#: conventionally narrated as "Round of N" - see round_label's docstring.
_GRAND_SLAM_ORDINALS: dict[str, str] = {
    "R128": "the first round",
    "R64": "the second round",
    "R32": "the third round",
    "R16": "the fourth round",
}

_ROUND_OF_LABELS: dict[str, str] = {
    "R128": "the Round of 128",
    "R64": "the Round of 64",
    "R32": "the Round of 32",
    "R16": "the Round of 16",
}

_LATE_ROUND_LABELS: dict[str, str] = {
    "QF": "the quarterfinals",
    "SF": "the semifinals",
    "F": "the final",
    "W": "the title",
}


def round_label(round_code: str, *, category: str | None = None) -> str:
    """A natural spoken-language phrase for ``round_code`` (one of
    :data:`ROUND_ORDER`), e.g. ``"the fourth round"`` or
    ``"the quarterfinals"``.

    Grand Slams use the ordinal convention broadcasters use for them
    ("the fourth round"); every other category uses the "Round of N"
    phrasing - deliberately not a blind code-to-text translation, per this
    feature's brief. Falls back to the raw code (still readable, just not
    pretty) for anything unrecognized rather than raising.
    """

    if round_code in _LATE_ROUND_LABELS:
        return _LATE_ROUND_LABELS[round_code]
    is_grand_slam = (category or "").strip().upper() == "GRAND SLAM"
    table = _GRAND_SLAM_ORDINALS if is_grand_slam else _ROUND_OF_LABELS
    return table.get(round_code, round_code)
