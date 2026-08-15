"""Pure logic for comparing today's rankings against a previous snapshot."""

from __future__ import annotations

from wta_daily.models import Movement, PlayerRanking


def compute_movement(
    current_rank: int, previous_rank: int | None, *, has_previous_snapshot: bool
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
    """

    if not has_previous_snapshot:
        return Movement.UNKNOWN
    if previous_rank is None:
        return Movement.NEW
    if current_rank < previous_rank:
        return Movement.UP
    if current_rank > previous_rank:
        return Movement.DOWN
    return Movement.SAME


def previous_ranks_by_player(previous: list[PlayerRanking] | None) -> dict[str, int]:
    """Build a ``player_id -> rank`` lookup from a previous snapshot."""

    if not previous:
        return {}
    return {p.player_id: p.rank for p in previous}
