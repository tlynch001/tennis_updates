"""Unit tests for wta_daily.scripts_gen.name_utils."""

from __future__ import annotations

from wta_daily.scripts_gen.name_utils import first_name


def test_first_name_of_a_two_word_name() -> None:
    assert first_name("Emma Navarro") == "Emma"


def test_first_name_of_a_multi_word_name() -> None:
    assert first_name("Maria Jose Martinez Sanchez") == "Maria"


def test_first_name_of_a_single_word_name() -> None:
    assert first_name("Serena") == "Serena"


def test_first_name_strips_surrounding_whitespace() -> None:
    assert first_name("  Emma Navarro  ") == "Emma"


def test_first_name_never_raises_on_empty_input() -> None:
    assert first_name("") == ""


def test_first_name_never_raises_on_whitespace_only_input() -> None:
    assert first_name("   ") == ""
