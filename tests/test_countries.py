from __future__ import annotations

from wta_daily.countries import flag_emoji_from_iso2, get_country_info


def test_known_country_resolves_flag_and_name() -> None:
    info = get_country_info("USA")
    assert info.iso2 == "US"
    assert info.display_name == "United States"
    assert info.flag_emoji == "\U0001F1FA\U0001F1F8"


def test_country_lookup_is_case_insensitive() -> None:
    assert get_country_info("usa").iso2 == "US"


def test_unknown_country_code_degrades_gracefully() -> None:
    info = get_country_info("ZZZ")
    assert info.code == "ZZZ"
    assert info.iso2 is None
    assert info.display_name == "ZZZ"
    assert info.flag_emoji  # some placeholder glyph, never raises


def test_empty_country_code_does_not_raise() -> None:
    info = get_country_info("")
    assert info.code == "UNK"


def test_flag_emoji_from_iso2_builds_regional_indicators() -> None:
    assert flag_emoji_from_iso2("fr") == "\U0001F1EB\U0001F1F7"
