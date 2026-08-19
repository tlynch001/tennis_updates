"""Builds narration sentences describing a player's tournament-elimination
context (see :class:`~wta_daily.models.TournamentRunStatus`) - who
eliminated her, what round she reached, how many ranking points that
finish earned, and (when reliably known) how it compares with her result
at the same event a year ago.

Deliberately its own module rather than living inside
:mod:`wta_daily.scripts_gen.template_generator` or
:mod:`wta_daily.scripts_gen.featured_player`: both of those call the same
:func:`build_tournament_status_sentence` (and check the same
:func:`supersedes_inactivity_narration`) for their respective player(s),
which is what lets the elimination-context narration - and the rule that
it takes precedence over generic "no match to report" filler - behave
identically for a Top N player and the featured player without
duplicating any of this logic (per this feature's brief).

Every fact used here comes straight from ``TournamentRunStatus`` - this
module never computes a point value, a round name, or a comparison
direction itself (that's :mod:`wta_daily.points_table`/
:mod:`wta_daily.rounds`/:mod:`wta_daily.plugins.matches.tournament_status`'s
job); it only ever *phrases* facts it's handed, and degrades a clause to
nothing (not a guess) whenever the underlying fact is ``None``. See the
README's "Tournament elimination context" section for the full
graceful-degradation hierarchy.

By the point any sentence built here is spoken, the player's full name
has already been used earlier in the same paragraph/segment (the Top N
per-player sentence always opens with it; the featured-player segment's
intro always does too) - so every sentence here refers to her only by
first name (:mod:`wta_daily.scripts_gen.name_utils`) or a pronoun, never
the full name again. First name (not a pronoun) is used as the subject of
the ranking-points sentence specifically because the immediately
preceding clause may have just named the eliminator - "she earned 65
points" would be ambiguous about which "she" is meant, "Emma earned 65
points" is not.
"""

from __future__ import annotations

import random

from wta_daily.models import TournamentRunStatus, TournamentState
from wta_daily.rounds import round_rank
from wta_daily.scripts_gen import tournament_status_phrases as tsp
from wta_daily.scripts_gen.name_utils import first_name as _first_name

#: States for which elimination/title context exists at all - see
#: supersedes_inactivity_narration.
_TERMINAL_STATES = frozenset({TournamentState.ELIMINATED, TournamentState.CHAMPION})


def supersedes_inactivity_narration(status: TournamentRunStatus | None) -> bool:
    """Whether ``status`` represents a known, concluded tournament result
    (eliminated or champion) that should take precedence over - and
    therefore suppress - generic "no match to report"/"couldn't confirm
    yesterday's result" filler.

    Once a player's tournament run is known to be over, saying she also
    "had the day off" or "didn't take the court yesterday" reads as an
    odd non-sequitur immediately before or after the real news. This
    check is what lets both :mod:`wta_daily.scripts_gen.template_generator`
    and :mod:`wta_daily.scripts_gen.featured_player` skip that generic
    inactivity sentence specifically (and only) when there's real
    elimination/title context to report instead - an actual win/loss
    match result for the target date is never suppressed by this, only
    the "we have nothing to say either way" filler.
    """

    return status is not None and status.state in _TERMINAL_STATES


def _finish(sentence: str) -> str:
    finished = sentence if sentence.endswith((".", "!", "?")) else f"{sentence}."
    return finished[:1].upper() + finished[1:] if finished else finished


def _history_fragment(status: TournamentRunStatus, rng: random.Random) -> str | None:
    """A clause comparing this result with last year's at the same event -
    ``None`` if there's genuinely nothing reliable to compare against.

    The improved/matched/worse *direction* always comes from comparing
    round order (:func:`wta_daily.rounds.round_rank`), never from
    ``points_delta`` - a round comparison is available (and meaningful)
    even when one side's points aren't (see
    :mod:`wta_daily.points_table`'s graceful-degradation notes), so this
    is the more robust signal to phrase the "improvement/step back"
    framing around.
    """

    if status.previous_year_round_label is None or status.previous_year_round is None:
        return None

    this_rank = round_rank(status.round_reached) if status.round_reached else None
    previous_rank = round_rank(status.previous_year_round)
    if this_rank is None or previous_rank is None:
        return None

    defended_title = status.state is TournamentState.CHAMPION and status.previous_year_round == "W"
    if defended_title:
        return rng.choice(tsp.HISTORY_DEFENDED_TITLE)
    if this_rank > previous_rank:
        pool = tsp.HISTORY_IMPROVED
    elif this_rank == previous_rank:
        pool = tsp.HISTORY_MATCHED
    else:
        pool = tsp.HISTORY_WORSE
    return rng.choice(pool).format(previous_round=status.previous_year_round_label)


def _swing_fragment(points_delta: int | None, rng: random.Random) -> str:
    """A trailing clause describing the net points swing - "" if unknown.

    Only ever appended directly after a history fragment (never as a
    standalone opener), since it reads as a continuation of "compared to
    last year," not a fact on its own.
    """

    if points_delta is None:
        return ""
    if points_delta > 0:
        return rng.choice(tsp.SWING_POSITIVE).format(delta=points_delta)
    if points_delta < 0:
        return rng.choice(tsp.SWING_NEGATIVE).format(delta=abs(points_delta))
    return rng.choice(tsp.SWING_FLAT)


def _points_and_history_sentence(status: TournamentRunStatus, name: str, rng: random.Random) -> str | None:
    """The second (optional) sentence: ranking points earned, with a
    natural historical comparison folded in when one's reliably known -
    ``None`` if there's nothing at all to say (no points, no history).
    """

    history = _history_fragment(status, rng)

    if status.points_earned is None:
        if history is None:
            return None
        return _finish(rng.choice(tsp.HISTORY_ONLY_SENTENCES).format(history=history))

    if history is None:
        base = rng.choice(tsp.POINTS_ONLY_SENTENCES).format(first_name=name, points=status.points_earned)
        return _finish(base)

    swing = _swing_fragment(status.points_delta, rng)
    base = rng.choice(tsp.POINTS_WITH_HISTORY_SENTENCES).format(
        first_name=name, points=status.points_earned, history=history
    )
    return _finish(base + swing)


def _eliminated_sentences(status: TournamentRunStatus, name: str, rng: random.Random) -> list[str]:
    round_phrase = status.round_label or "the tournament"

    if not status.is_new_development:
        base = rng.choice(tsp.ELIMINATED_BRIEF).format(first_name=name, round=round_phrase)
        return [_finish(base)]

    pool = (
        tsp.ELIMINATED_OPENING_WITH_ELIMINATOR
        if status.eliminated_by
        else tsp.ELIMINATED_OPENING_NO_ELIMINATOR
    )
    opening = rng.choice(pool).format(first_name=name, round=round_phrase, eliminated_by=status.eliminated_by)
    sentences = [_finish(opening)]

    points_history = _points_and_history_sentence(status, name, rng)
    if points_history:
        sentences.append(points_history)
    return sentences


def _champion_sentences(status: TournamentRunStatus, name: str, rng: random.Random) -> list[str]:
    if not status.is_new_development:
        return [_finish(rng.choice(tsp.CHAMPION_BRIEF).format(first_name=name))]

    sentences = [_finish(rng.choice(tsp.CHAMPION_OPENING).format(first_name=name))]
    points_history = _points_and_history_sentence(status, name, rng)
    if points_history:
        sentences.append(points_history)
    return sentences


def build_tournament_status_sentence(
    status: TournamentRunStatus | None, full_name: str, rng: random.Random
) -> str | None:
    """One or more ready-to-append, fully punctuated sentences for
    ``status`` (joined with spaces into a single string), or ``None``
    when there's nothing narration-worthy to add.

    ``None`` for :attr:`TournamentState.ACTIVE`,
    :attr:`TournamentState.DID_NOT_PARTICIPATE`,
    :attr:`TournamentState.UNKNOWN`, or ``status`` itself being ``None``
    (no tournament-draw visibility at all this run) - this feature is
    additive context for a genuinely concluded run (elimination or
    title), never a running commentary on an ongoing one, per the
    feature's brief.

    ``full_name`` is used only to derive her first name
    (:mod:`wta_daily.scripts_gen.name_utils`) - callers are expected to
    have already introduced the full name earlier in the same
    paragraph/segment, per this module's docstring.
    """

    if status is None:
        return None
    name = _first_name(full_name)
    if status.state is TournamentState.ELIMINATED:
        return " ".join(_eliminated_sentences(status, name, rng))
    if status.state is TournamentState.CHAMPION:
        return " ".join(_champion_sentences(status, name, rng))
    return None
