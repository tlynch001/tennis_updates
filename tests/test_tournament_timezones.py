"""Unit tests for wta_daily.tournament_timezones."""

from __future__ import annotations

from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from wta_daily.tournament_timezones import (
    DEFAULT_TOURNAMENT_TIMEZONES_PATH,
    TournamentTimezones,
    load_tournament_timezones,
)


def test_default_data_file_loads_successfully() -> None:
    timezones = load_tournament_timezones()

    assert timezones.resolve("USA, OH") == ZoneInfo("America/New_York")


def test_resolves_a_us_state_to_its_own_timezone() -> None:
    timezones = TournamentTimezones(
        countries={"USA": "America/New_York"},
        us_states={"OH": "America/New_York", "CA": "America/Los_Angeles"},
    )

    assert timezones.resolve("USA, CA") == ZoneInfo("America/Los_Angeles")
    assert timezones.resolve("USA, OH") == ZoneInfo("America/New_York")


def test_resolves_a_bare_country_code() -> None:
    timezones = TournamentTimezones(countries={"GBR": "Europe/London"}, us_states={})

    assert timezones.resolve("GBR") == ZoneInfo("Europe/London")


def test_unrecognized_country_returns_none() -> None:
    timezones = TournamentTimezones(countries={"GBR": "Europe/London"}, us_states={})

    assert timezones.resolve("ATLANTIS") is None


def test_usa_with_unrecognized_state_falls_back_to_country_default() -> None:
    timezones = TournamentTimezones(
        countries={"USA": "America/New_York"}, us_states={"CA": "America/Los_Angeles"}
    )

    assert timezones.resolve("USA, ZZ") == ZoneInfo("America/New_York")


def test_none_or_empty_country_returns_none() -> None:
    timezones = TournamentTimezones(countries={"USA": "America/New_York"}, us_states={})

    assert timezones.resolve(None) is None
    assert timezones.resolve("") is None
    assert timezones.resolve("   ") is None


def test_resolution_is_case_insensitive() -> None:
    timezones = TournamentTimezones(countries={"GBR": "Europe/London"}, us_states={"OH": "America/New_York"})

    assert timezones.resolve("gbr") == ZoneInfo("Europe/London")
    assert timezones.resolve("usa, oh") == ZoneInfo("America/New_York")


def test_invalid_iana_name_in_data_logs_and_returns_none(tmp_path: Path) -> None:
    timezones = TournamentTimezones(countries={"XYZ": "Not/A_Real_Zone"}, us_states={})

    assert timezones.resolve("XYZ") is None


def test_load_tournament_timezones_from_a_custom_minimal_file(tmp_path: Path) -> None:
    custom_path = tmp_path / "custom.yaml"
    custom_path.write_text(
        "countries:\n  FRA: Europe/Paris\nus_states:\n  NY: America/New_York\n",
        encoding="utf-8",
    )

    timezones = load_tournament_timezones(custom_path)

    assert timezones.resolve("FRA") == ZoneInfo("Europe/Paris")
    assert timezones.resolve("USA, NY") == ZoneInfo("America/New_York")
    assert timezones.resolve("USA, ZZ") is None  # unrecognized state, and no "USA" country default configured


def test_load_tournament_timezones_handles_an_empty_file(tmp_path: Path) -> None:
    empty_path = tmp_path / "empty.yaml"
    empty_path.write_text("", encoding="utf-8")

    timezones = load_tournament_timezones(empty_path)

    assert timezones.resolve("USA, OH") is None


def test_default_path_points_at_a_real_file() -> None:
    assert DEFAULT_TOURNAMENT_TIMEZONES_PATH.exists()


@pytest.mark.parametrize(
    ("country", "expected_zone"),
    [
        ("GBR", "Europe/London"),
        ("FRA", "Europe/Paris"),
        ("AUS", "Australia/Melbourne"),
        ("USA, CA", "America/Los_Angeles"),
        ("USA, TX", "America/Chicago"),
    ],
)
def test_default_data_file_covers_common_wta_tour_locations(country: str, expected_zone: str) -> None:
    timezones = load_tournament_timezones()

    assert timezones.resolve(country) == ZoneInfo(expected_zone)
