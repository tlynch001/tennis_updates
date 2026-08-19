"""Builds a narration sentence describing a player's tournament-elimination
context (see :class:`~wta_daily.models.TournamentRunStatus`) - who
eliminated her, what round she reached, how many ranking points that
finish earned, and (when reliably known) how it compares with her result
at the same event a year ago.

Deliberately its own module rather than living inside
:mod:`wta_daily.scripts_gen.template_generator` or
:mod:`wta_daily.scripts_gen.featured_player`: both of those call the same
:func:`build_tournament_status_sentence` for their respective player(s),
which is what lets the elimination-context narration behave identically
for a Top N player and the featured player without duplicating any of
this logic (per this feature's brief).

Every fact used here comes straight from ``TournamentRunStatus`` - this
module never computes a point value, a round name, or a comparison
direction itself (that's :mod:`wta_daily.points_table`/
:mod:`wta_daily.rounds`/:mod:`wta_daily.plugins.matches.tournament_status`'s
job); it only ever *phrases* facts it's handed, and degrades a clause to
nothing (not a guess) whenever the underlying fact is ``None``. See the
README's "Tournament elimination context" section for the full
graceful-degradation hierarchy.
"""

from __future__ import annotations

import random

from wta_daily.models import TournamentRunStatus, TournamentState
from wta_daily.rounds import round_rank
from wta_daily.scripts_gen import tournament_status_phrases as tsp


def _finish(sentence: str) -> str:
    finished = sentence if sentence.endswith((".", "!", "?")) else f"{sentence}."
    return finished[:1].upper() + finished[1:] if finished else finished


def _points_clause(points_earned: int | None, rng: random.Random) -> str:
    if points_earned is None:
        return ""
    return rng.choice(tsp.POINTS_CLAUSES).format(points=points_earned)


def _history_clause(status: TournamentRunStatus, rng: random.Random) -> str:
    """A clause comparing this result with last year's at the same event -
    "" if there's genuinely nothing reliable to compare against.

    The improved/matched/worse *direction* always comes from comparing
    round order (:func:`wta_daily.rounds.round_rank`), never from
    ``points_delta`` - a round comparison is available (and meaningful)
    even when one side's points aren't (see
    :mod:`wta_daily.points_table`'s graceful-degradation notes), so this
    is the more robust signal to phrase the "improvement/step back"
    framing around. The points swing itself (when it *is* known) is
    appended as a separate, additional clause - see
    :data:`tsp.NET_SWING_POSITIVE`/:data:`tsp.NET_SWING_NEGATIVE`.
    """

    if status.previous_year_round_label is None or status.previous_year_round is None:
        return ""

    this_rank = round_rank(status.round_reached) if status.round_reached else None
    previous_rank = round_rank(status.previous_year_round)

    if this_rank is None or previous_rank is None:
        return ""

    defended_title = status.state is TournamentState.CHAMPION and status.previous_year_round == "W"
    if defended_title:
        clause = rng.choice(tsp.HISTORY_DEFENDED_TITLE)
    elif this_rank > previous_rank:
        clause = rng.choice(tsp.HISTORY_IMPROVED).format(previous_round=status.previous_year_round_label)
    elif this_rank == previous_rank:
        clause = rng.choice(tsp.HISTORY_MATCHED).format(previous_round=status.previous_year_round_label)
    else:
        clause = rng.choice(tsp.HISTORY_WORSE).format(previous_round=status.previous_year_round_label)

    if status.points_delta is not None and status.points_delta != 0:
        pool = tsp.NET_SWING_POSITIVE if status.points_delta > 0 else tsp.NET_SWING_NEGATIVE
        clause += rng.choice(pool).format(delta=abs(status.points_delta))
    elif status.points_delta == 0:
        clause += rng.choice(tsp.NET_SWING_FLAT)

    return clause


def _eliminated_sentence(status: TournamentRunStatus, name: str, rng: random.Random) -> str:
    round_phrase = status.round_label or "the tournament"

    if not status.is_new_development:
        base = rng.choice(tsp.ELIMINATED_BRIEF).format(name=name, round=round_phrase)
        return base

    pool = (
        tsp.ELIMINATED_DETAILED_WITH_ELIMINATOR
        if status.eliminated_by
        else tsp.ELIMINATED_DETAILED_NO_ELIMINATOR
    )
    base = rng.choice(pool).format(name=name, round=round_phrase, eliminated_by=status.eliminated_by)
    return base + _points_clause(status.points_earned, rng) + _history_clause(status, rng)


def _champion_sentence(status: TournamentRunStatus, name: str, rng: random.Random) -> str:
    if not status.is_new_development:
        return rng.choice(tsp.CHAMPION_BRIEF).format(name=name)

    base = rng.choice(tsp.CHAMPION_DETAILED).format(name=name)
    return base + _points_clause(status.points_earned, rng) + _history_clause(status, rng)


def build_tournament_status_sentence(
    status: TournamentRunStatus | None, name: str, rng: random.Random
) -> str | None:
    """A ready-to-append, fully punctuated sentence for ``status``, or
    ``None`` when there's nothing narration-worthy to add.

    ``None`` for :attr:`TournamentState.ACTIVE`,
    :attr:`TournamentState.DID_NOT_PARTICIPATE`,
    :attr:`TournamentState.UNKNOWN`, or ``status`` itself being ``None``
    (no tournament-draw visibility at all this run) - this feature is
    additive context for a genuinely concluded run (elimination or
    title), never a running commentary on an ongoing one, per the
    feature's brief.
    """

    if status is None:
        return None
    if status.state is TournamentState.ELIMINATED:
        return _finish(_eliminated_sentence(status, name, rng))
    if status.state is TournamentState.CHAMPION:
        return _finish(_champion_sentence(status, name, rng))
    return None
