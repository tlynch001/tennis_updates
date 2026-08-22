"""Pure logic for comparing today's rankings against a previous snapshot.

See the README's "Official ranking vs. daily match activity" section for
the architectural principle this module exists to enforce: a player
winning (or losing) a match must never, by itself, cause the application
to report a ranking change. Only an actual new official WTA ranking
publication can do that.
"""

from __future__ import annotations

import dataclasses
from datetime import date

from wta_daily.models import Movement, PlayerRanking


def is_same_official_ranking_list(
    current_ranking_date: date | None, previous_ranking_date: date | None
) -> bool:
    """Whether two ranking dates identify the *same* published WTA list.

    ``True`` only when both dates are known and equal. Deliberately
    ``False`` (never "assumed same") whenever either date is unknown - a
    rankings provider that doesn't expose a ranking date at all (e.g. the
    offline ``sample`` fixture used in tests) simply can't participate in
    this guarantee, so callers fall back to comparing rank numbers alone,
    exactly as before this concept existed.
    """

    return (
        current_ranking_date is not None
        and previous_ranking_date is not None
        and current_ranking_date == previous_ranking_date
    )


def compute_movement(
    current_rank: int,
    previous_rank: int | None,
    *,
    has_previous_snapshot: bool,
    same_official_ranking_list: bool = False,
) -> Movement:
    """Classify a single player's rank change.

    A lower rank number is better (rank 1 is world number one), so moving
    from rank 3 to rank 2 is "up" even though the number decreased.

    ``has_previous_snapshot`` must be ``False`` only when there is no prior
    snapshot to compare against at all (e.g. the application's first-ever
    run for this tour) - that case returns :attr:`Movement.UNKNOWN`, not
    :attr:`Movement.NEW`, so downstream narration/graphics don't claim an
    established Top N player "just entered" it. ``previous_rank`` being
    ``None`` while a snapshot *does* exist means the player genuinely
    wasn't in the tracked group last time, which is :attr:`Movement.NEW`.

    ``same_official_ranking_list`` (see :func:`is_same_official_ranking_list`)
    is the key guarantee this project needs: when the current fetch and the
    previous snapshot are confirmed to be the *identical* published ranking
    list (not just fetched on different calendar days), movement is always
    :attr:`Movement.SAME` for a previously-tracked player - regardless of
    what the raw rank numbers say. This is deliberately defensive: today's
    numbers *should* already match the previous snapshot's whenever the
    official list hasn't changed (that's what "official" means), but a
    match result must never be able to produce "moved up"/"moved down"
    narration, even in the face of a hypothetical transient upstream
    inconsistency. Defaults to ``False`` (the pre-existing, purely
    numeric-comparison behavior) so every caller not yet passing this
    keyword continues to work unchanged.
    """

    if not has_previous_snapshot:
        return Movement.UNKNOWN
    if previous_rank is None:
        return Movement.NEW
    if same_official_ranking_list:
        return Movement.SAME
    if current_rank < previous_rank:
        return Movement.UP
    if current_rank > previous_rank:
        return Movement.DOWN
    return Movement.SAME


def resolve_official_ranking(
    current: PlayerRanking,
    previous: PlayerRanking | None,
    *,
    same_official_ranking_list: bool,
    tour_display_name: str = "WTA",
) -> tuple[PlayerRanking, str | None]:
    """Guard against a contradictory official-ranking fetch.

    When ``same_official_ranking_list`` is ``True``, the current fetch and
    the previously saved snapshot both claim to be the *same* published
    WTA ranking list - the WTA does not amend an already-published list,
    so a previously-tracked player's ``rank``/``points`` **must** agree
    between the two. If they don't, this is never silently accepted as if
    it were a genuine (but somehow unannounced) change: it's treated as an
    unreliable fetch, and the previously saved, trusted values are kept
    instead - which is also what guarantees the *displayed ordering* for
    the Top N can never shift while the official list is unchanged, not
    just the ``Movement`` label (see :func:`compute_movement`).

    Returns ``(resolved, warning)``:

    * ``resolved`` is ``current`` unchanged in every case except a
      detected contradiction, in which case it's a copy of ``current``
      with ``rank``/``points`` overridden to ``previous``'s values (every
      other field - name, country, ranking_date - is left as fetched,
      since only the numbers themselves are in question).
    * ``warning`` is ``None`` unless a contradiction was detected, in
      which case it's a human-readable message identifying the player and
      both conflicting values - callers should log it and surface it
      (e.g. in ``report.errors``) rather than discard it, per this
      project's "never silently accept contradictory ranking data" rule.

    A no-op (returns ``current, None``) whenever ``same_official_ranking_list``
    is ``False`` or there's no ``previous`` entry to compare against - this
    check only applies when both sides confidently claim to be the same
    official list.
    """

    if not same_official_ranking_list or previous is None:
        return current, None
    if current.rank == previous.rank and current.points == previous.points:
        return current, None

    warning = (
        f"{current.name}: official ranking dated {current.ranking_date} is unchanged since "
        f"the previous run, but the fetched rank/points changed from #{previous.rank} "
        f"({previous.points} pts) to #{current.rank} ({current.points} pts). "
        f"The {tour_display_name} does not "
        "amend an already-published ranking, so this is treated as an unreliable fetch - "
        "keeping the previously saved official values instead."
    )
    resolved = dataclasses.replace(current, rank=previous.rank, points=previous.points)
    return resolved, warning


def previous_ranks_by_player(previous: list[PlayerRanking] | None) -> dict[str, int]:
    """Build a ``player_id -> rank`` lookup from a previous snapshot."""

    if not previous:
        return {}
    return {p.player_id: p.rank for p in previous}
