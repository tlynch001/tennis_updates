from __future__ import annotations

from wta_daily.rounds import normalize_wta_round_id, round_label, round_rank


def test_normalize_letter_rounds_are_draw_size_independent() -> None:
    for draw_size in (None, 28, 32, 56, 96, 128):
        assert normalize_wta_round_id("Q", draw_size=draw_size) == "QF"
        assert normalize_wta_round_id("S", draw_size=draw_size) == "SF"
        assert normalize_wta_round_id("F", draw_size=draw_size) == "F"


def test_normalize_numeric_rounds_for_a_96_draw() -> None:
    assert normalize_wta_round_id("1", draw_size=96) == "R128"
    assert normalize_wta_round_id("2", draw_size=96) == "R64"
    assert normalize_wta_round_id("3", draw_size=96) == "R32"
    assert normalize_wta_round_id("4", draw_size=96) == "R16"


def test_normalize_numeric_rounds_for_a_56_draw() -> None:
    """A smaller WTA 1000 draw has one fewer numbered round before QF -
    round '1' here is the Round of 64, not the Round of 128."""

    assert normalize_wta_round_id("1", draw_size=56) == "R64"
    assert normalize_wta_round_id("2", draw_size=56) == "R32"
    assert normalize_wta_round_id("3", draw_size=56) == "R16"


def test_normalize_numeric_rounds_for_a_32_draw() -> None:
    assert normalize_wta_round_id("1", draw_size=32) == "R32"
    assert normalize_wta_round_id("2", draw_size=32) == "R16"


def test_normalize_out_of_range_round_returns_none() -> None:
    """A 32-draw only has 2 numbered rounds - round '3' doesn't exist."""

    assert normalize_wta_round_id("3", draw_size=32) is None
    assert normalize_wta_round_id("0", draw_size=32) is None


def test_normalize_unknown_draw_size_defaults_to_the_largest_common_case() -> None:
    assert normalize_wta_round_id("4", draw_size=None) == "R16"
    assert normalize_wta_round_id("1", draw_size=None) == "R128"


def test_normalize_unrecognized_code_returns_none() -> None:
    assert normalize_wta_round_id("RR", draw_size=96) is None
    assert normalize_wta_round_id("garbage", draw_size=96) is None


def test_round_label_grand_slam_uses_ordinal_convention() -> None:
    assert round_label("R128", category="GRAND SLAM") == "the first round"
    assert round_label("R64", category="GRAND SLAM") == "the second round"
    assert round_label("R32", category="GRAND SLAM") == "the third round"
    assert round_label("R16", category="GRAND SLAM") == "the fourth round"


def test_round_label_non_slam_uses_round_of_n_convention() -> None:
    assert round_label("R16", category="WTA 1000") == "the Round of 16"
    assert round_label("R32", category="WTA 500") == "the Round of 32"
    assert round_label("R16", category=None) == "the Round of 16"


def test_round_label_late_rounds_are_identical_across_categories() -> None:
    for category in ("GRAND SLAM", "WTA 1000", "WTA 500", "WTA 250", None):
        assert round_label("QF", category=category) == "the quarterfinals"
        assert round_label("SF", category=category) == "the semifinals"
        assert round_label("F", category=category) == "the final"
        assert round_label("W", category=category) == "the title"


def test_round_label_falls_back_to_the_raw_code_for_unknown_input() -> None:
    assert round_label("RR") == "RR"


def test_round_rank_orders_rounds_correctly() -> None:
    raw_ranks = [round_rank(code) for code in ("R128", "R64", "R32", "R16", "QF", "SF", "F", "W")]
    assert all(rank is not None for rank in raw_ranks)
    ranks: list[int] = [rank for rank in raw_ranks if rank is not None]
    assert ranks == sorted(ranks)
    assert len(set(ranks)) == len(ranks)


def test_round_rank_unknown_code_returns_none() -> None:
    assert round_rank("garbage") is None
