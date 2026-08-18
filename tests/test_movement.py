from __future__ import annotations

from datetime import date

from wta_daily.models import Movement, PlayerRanking
from wta_daily.movement import compute_movement, is_same_official_ranking_list, previous_ranks_by_player


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


# --- Official ranking list awareness (same_official_ranking_list) ----------


def test_is_same_official_ranking_list_true_when_dates_match() -> None:
    assert is_same_official_ranking_list(date(2026, 8, 10), date(2026, 8, 10)) is True


def test_is_same_official_ranking_list_false_when_dates_differ() -> None:
    assert is_same_official_ranking_list(date(2026, 8, 17), date(2026, 8, 10)) is False


def test_is_same_official_ranking_list_false_when_current_date_unknown() -> None:
    assert is_same_official_ranking_list(None, date(2026, 8, 10)) is False


def test_is_same_official_ranking_list_false_when_previous_date_unknown() -> None:
    assert is_same_official_ranking_list(date(2026, 8, 10), None) is False


def test_is_same_official_ranking_list_false_when_both_dates_unknown() -> None:
    """Unknown must never be treated as 'assumed same' - see the module
    docstring for why (a provider without ranking dates, like `sample`,
    must fall back to plain rank-number comparison, not skip movement
    entirely)."""

    assert is_same_official_ranking_list(None, None) is False


def test_compute_movement_forces_same_when_same_official_ranking_list_even_if_ranks_differ() -> None:
    """The core guarantee: once the current and previous fetch are
    confirmed to be the identical published ranking list, movement must be
    SAME for a previously-tracked player - even in the hypothetical case
    the raw numbers disagree (a defensive guarantee against transient
    upstream inconsistencies, not something that should happen with a
    well-behaved source)."""

    movement = compute_movement(
        current_rank=2,
        previous_rank=4,
        has_previous_snapshot=True,
        same_official_ranking_list=True,
    )

    assert movement == Movement.SAME


def test_compute_movement_still_computes_up_down_when_ranking_list_differs() -> None:
    """A genuine new official ranking release (same_official_ranking_list is
    False) must still classify movement normally from the rank numbers."""

    assert (
        compute_movement(
            current_rank=2, previous_rank=4, has_previous_snapshot=True, same_official_ranking_list=False
        )
        == Movement.UP
    )
    assert (
        compute_movement(
            current_rank=5, previous_rank=2, has_previous_snapshot=True, same_official_ranking_list=False
        )
        == Movement.DOWN
    )


def test_compute_movement_same_official_ranking_list_defaults_to_false() -> None:
    """Every pre-existing call site (not yet passing this keyword) must
    behave exactly as before - purely numeric comparison."""

    assert compute_movement(current_rank=2, previous_rank=4, has_previous_snapshot=True) == Movement.UP


def test_compute_movement_same_official_ranking_list_does_not_override_new() -> None:
    """A player genuinely absent from the previous snapshot is still NEW,
    even if same_official_ranking_list happens to be True (e.g. top_n was
    widened this run) - the override only ever clamps UP/DOWN to SAME."""

    movement = compute_movement(
        current_rank=9,
        previous_rank=None,
        has_previous_snapshot=True,
        same_official_ranking_list=True,
    )

    assert movement == Movement.NEW


def test_compute_movement_same_official_ranking_list_does_not_override_unknown() -> None:
    movement = compute_movement(
        current_rank=1,
        previous_rank=None,
        has_previous_snapshot=False,
        same_official_ranking_list=True,
    )

    assert movement == Movement.UNKNOWN


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
