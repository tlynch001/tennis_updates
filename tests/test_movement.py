from __future__ import annotations

from wta_daily.models import Movement, PlayerRanking
from wta_daily.movement import compute_movement, previous_ranks_by_player


def test_compute_movement_up() -> None:
    assert compute_movement(current_rank=2, previous_rank=4, has_previous_snapshot=True) == Movement.UP


def test_compute_movement_down() -> None:
    assert compute_movement(current_rank=5, previous_rank=2, has_previous_snapshot=True) == Movement.DOWN


def test_compute_movement_same() -> None:
    assert compute_movement(current_rank=3, previous_rank=3, has_previous_snapshot=True) == Movement.SAME


def test_compute_movement_new() -> None:
    """A previous snapshot exists, but this player wasn't in it - genuinely new."""

    assert compute_movement(current_rank=7, previous_rank=None, has_previous_snapshot=True) == Movement.NEW


def test_compute_movement_unknown_when_no_previous_snapshot_exists() -> None:
    """No previous snapshot at all (e.g. first-ever run) must be 'unknown', not 'new'.

    This is the regression covered for the production incident where every
    established Top 10 player was narrated as "a new face" purely because
    the application had never run before, not because any of them had
    actually just entered the rankings.
    """

    assert (
        compute_movement(current_rank=1, previous_rank=None, has_previous_snapshot=False)
        == Movement.UNKNOWN
    )


def test_compute_movement_unknown_ignores_previous_rank_value() -> None:
    """``has_previous_snapshot=False`` always wins, even if a rank value is (incorrectly) passed."""

    assert (
        compute_movement(current_rank=1, previous_rank=1, has_previous_snapshot=False)
        == Movement.UNKNOWN
    )


def test_previous_ranks_by_player_builds_lookup() -> None:
    previous = [
        PlayerRanking(rank=1, player_id="a", name="A", country_code="USA", points=100),
        PlayerRanking(rank=2, player_id="b", name="B", country_code="FRA", points=90),
    ]
    lookup = previous_ranks_by_player(previous)
    assert lookup == {"a": 1, "b": 2}


def test_previous_ranks_by_player_handles_none() -> None:
    assert previous_ranks_by_player(None) == {}


def test_previous_ranks_by_player_handles_empty_list() -> None:
    assert previous_ranks_by_player([]) == {}
