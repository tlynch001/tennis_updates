from __future__ import annotations

from wta_daily.models import Movement, PlayerRanking
from wta_daily.movement import compute_movement, previous_ranks_by_player


def test_compute_movement_up() -> None:
    assert compute_movement(current_rank=2, previous_rank=4) == Movement.UP


def test_compute_movement_down() -> None:
    assert compute_movement(current_rank=5, previous_rank=2) == Movement.DOWN


def test_compute_movement_same() -> None:
    assert compute_movement(current_rank=3, previous_rank=3) == Movement.SAME


def test_compute_movement_new() -> None:
    assert compute_movement(current_rank=7, previous_rank=None) == Movement.NEW


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
