from __future__ import annotations

from wta_daily.points_table import PointsTable, load_points_table


def test_load_default_points_table_and_lookup_a_known_value() -> None:
    table = load_points_table()

    assert table.lookup("WTA 1000", "R16", draw_size=96) == 120
    assert table.lookup("GRAND SLAM", "W") == 2000
    assert table.lookup("GRAND SLAM", "QF") == 430


def test_lookup_uses_the_closest_configured_draw_size() -> None:
    table = load_points_table()

    # R64 differs between the two configured WTA 1000 draw sizes.
    assert table.lookup("WTA 1000", "R64", draw_size=96) == 35
    assert table.lookup("WTA 1000", "R64", draw_size=56) == 10
    # A draw size close to (but not exactly) 56 should still pick the 56 variant.
    assert table.lookup("WTA 1000", "R64", draw_size=60) == 10


def test_lookup_falls_back_to_default_draw_size_when_unspecified() -> None:
    table = load_points_table()

    # WTA 1000's default draw size is 96 - R64 should reflect that variant.
    assert table.lookup("WTA 1000", "R64") == 35


def test_lookup_is_case_insensitive_on_category() -> None:
    table = load_points_table()

    assert table.lookup("wta 1000", "QF", draw_size=96) == table.lookup("WTA 1000", "QF", draw_size=96)


def test_lookup_returns_none_for_unconfigured_category() -> None:
    """The Olympics deliberately awards no WTA ranking points at all -
    this must return None, not a guessed/fabricated number."""

    table = load_points_table()

    assert table.lookup("OLYMPICS", "QF") is None
    assert table.lookup("WTA FINALS", "SF") is None


def test_lookup_returns_none_for_unknown_round_code() -> None:
    table = load_points_table()

    assert table.lookup("WTA 1000", "RR", draw_size=96) is None


def test_lookup_returns_none_for_missing_inputs() -> None:
    table = load_points_table()

    assert table.lookup(None, "QF") is None
    assert table.lookup("WTA 1000", None) is None


def test_points_table_handles_a_minimal_custom_dataset() -> None:
    """A maintainer-supplied points table doesn't need every category -
    missing ones should degrade gracefully, never raise."""

    table = PointsTable(
        {
            "categories": {"WTA 250": {"draw_sizes": {32: {"W": 250, "F": 163}}}},
            "default_draw_size": {"WTA 250": 32},
        }
    )

    assert table.lookup("WTA 250", "W") == 250
    assert table.lookup("WTA 250", "QF") is None  # not configured in this minimal table
    assert table.lookup("WTA 1000", "W") is None  # category not present at all
