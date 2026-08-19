"""Unit tests for wta_daily.scripts_gen.tournament_status_narration."""

from __future__ import annotations

import random

import pytest

from wta_daily.models import TournamentRunStatus, TournamentState
from wta_daily.scripts_gen.tournament_status_narration import build_tournament_status_sentence


def _rng() -> random.Random:
    return random.Random(0)


def test_returns_none_when_status_is_none() -> None:
    assert build_tournament_status_sentence(None, "Test Player", _rng()) is None


@pytest.mark.parametrize(
    "state",
    [TournamentState.ACTIVE, TournamentState.DID_NOT_PARTICIPATE, TournamentState.UNKNOWN],
)
def test_returns_none_for_non_terminal_states(state: TournamentState) -> None:
    status = TournamentRunStatus(state=state)

    assert build_tournament_status_sentence(status, "Test Player", _rng()) is None


def test_eliminated_detailed_mentions_eliminator_and_round() -> None:
    status = TournamentRunStatus(
        state=TournamentState.ELIMINATED,
        tournament="Cincinnati",
        round_reached="R16",
        round_label="the Round of 16",
        eliminated_by="Iga Swiatek",
        is_new_development=True,
    )

    sentence = build_tournament_status_sentence(status, "Test Player", _rng())

    assert sentence is not None
    assert "Iga Swiatek" in sentence
    assert "Round of 16" in sentence
    assert sentence[0].isupper()
    assert sentence.endswith((".", "!", "?"))


def test_eliminated_detailed_without_eliminator_omits_the_name_gracefully() -> None:
    status = TournamentRunStatus(
        state=TournamentState.ELIMINATED,
        round_reached="QF",
        round_label="the quarterfinals",
        eliminated_by=None,
        is_new_development=True,
    )

    sentence = build_tournament_status_sentence(status, "Test Player", _rng())

    assert sentence is not None
    assert "None" not in sentence
    assert "quarterfinals" in sentence


def test_eliminated_mentions_points_earned_when_available() -> None:
    status = TournamentRunStatus(
        state=TournamentState.ELIMINATED,
        round_reached="R16",
        round_label="the Round of 16",
        eliminated_by="Some Rival",
        points_earned=120,
        is_new_development=True,
    )

    sentence = build_tournament_status_sentence(status, "Test Player", _rng())

    assert sentence is not None
    assert "120" in sentence


def test_eliminated_omits_points_when_unavailable() -> None:
    status = TournamentRunStatus(
        state=TournamentState.ELIMINATED,
        round_reached="R16",
        round_label="the Round of 16",
        eliminated_by="Some Rival",
        points_earned=None,
        is_new_development=True,
    )

    sentence = build_tournament_status_sentence(status, "Test Player", _rng())

    assert sentence is not None
    assert "None" not in sentence


@pytest.mark.parametrize(
    ("round_reached", "previous_year_round", "expect_substring"),
    [
        ("QF", "R32", "improvement"),
        ("R32", "QF", "step back"),
        ("QF", "QF", "matching"),
    ],
)
def test_eliminated_history_comparison_direction(
    round_reached: str, previous_year_round: str, expect_substring: str
) -> None:
    status = TournamentRunStatus(
        state=TournamentState.ELIMINATED,
        round_reached=round_reached,
        round_label="a round",
        eliminated_by="Some Rival",
        previous_year_round=previous_year_round,
        previous_year_round_label="the Round of 32" if previous_year_round == "R32" else "the quarterfinals",
        is_new_development=True,
    )

    # Try many seeds since each direction has multiple phrase variants.
    found = False
    for seed in range(30):
        sentence = build_tournament_status_sentence(status, "Test Player", random.Random(seed))
        assert sentence is not None
        if expect_substring in sentence:
            found = True
            break
    assert found, f"Expected some phrasing containing {expect_substring!r}"


def test_eliminated_omits_history_when_previous_year_data_is_missing() -> None:
    status = TournamentRunStatus(
        state=TournamentState.ELIMINATED,
        round_reached="R16",
        round_label="the Round of 16",
        eliminated_by="Some Rival",
        previous_year_round=None,
        previous_year_round_label=None,
        is_new_development=True,
    )

    sentence = build_tournament_status_sentence(status, "Test Player", _rng())

    assert sentence is not None
    assert "last year" not in sentence
    assert "a year ago" not in sentence


def test_eliminated_net_swing_never_implies_immediate_ranking_change() -> None:
    status = TournamentRunStatus(
        state=TournamentState.ELIMINATED,
        round_reached="QF",
        round_label="the quarterfinals",
        eliminated_by="Some Rival",
        points_earned=215,
        previous_year_round="R32",
        previous_year_round_label="the Round of 32",
        previous_year_points=65,
        points_delta=150,
        is_new_development=True,
    )

    for seed in range(10):
        sentence = build_tournament_status_sentence(status, "Test Player", random.Random(seed))
        assert sentence is not None
        assert "gained" not in sentence.lower()
        assert "moves up" not in sentence.lower()
        assert "climbs" not in sentence.lower()


def test_eliminated_brief_on_subsequent_report_is_shorter_and_omits_points() -> None:
    status = TournamentRunStatus(
        state=TournamentState.ELIMINATED,
        round_reached="R16",
        round_label="the Round of 16",
        eliminated_by="Some Rival",
        points_earned=120,
        previous_year_round="QF",
        previous_year_round_label="the quarterfinals",
        previous_year_points=215,
        points_delta=-95,
        is_new_development=False,
    )

    sentence = build_tournament_status_sentence(status, "Test Player", _rng())

    assert sentence is not None
    assert "120" not in sentence
    assert "Some Rival" not in sentence


def test_champion_detailed_mentions_points() -> None:
    status = TournamentRunStatus(
        state=TournamentState.CHAMPION,
        round_reached="W",
        round_label="the title",
        points_earned=1000,
        is_new_development=True,
    )

    sentence = build_tournament_status_sentence(status, "Test Player", _rng())

    assert sentence is not None
    assert "1000" in sentence


def test_champion_defended_title_uses_defended_phrasing() -> None:
    status = TournamentRunStatus(
        state=TournamentState.CHAMPION,
        round_reached="W",
        round_label="the title",
        previous_year_round="W",
        previous_year_round_label="the title",
        is_new_development=True,
    )

    found = False
    for seed in range(20):
        sentence = build_tournament_status_sentence(status, "Test Player", random.Random(seed))
        assert sentence is not None
        if "defend" in sentence.lower():
            found = True
            break
    assert found


def test_champion_brief_on_subsequent_report() -> None:
    status = TournamentRunStatus(
        state=TournamentState.CHAMPION,
        round_reached="W",
        round_label="the title",
        points_earned=1000,
        is_new_development=False,
    )

    sentence = build_tournament_status_sentence(status, "Test Player", _rng())

    assert sentence is not None
    assert "1000" not in sentence


def test_never_fabricates_history_when_round_reached_is_unrecognized() -> None:
    """A round code that isn't in the stable vocabulary (defensive edge
    case) must not crash the round_rank comparison."""

    status = TournamentRunStatus(
        state=TournamentState.ELIMINATED,
        round_reached="???",
        round_label="a round",
        eliminated_by="Some Rival",
        previous_year_round="QF",
        previous_year_round_label="the quarterfinals",
        is_new_development=True,
    )

    sentence = build_tournament_status_sentence(status, "Test Player", _rng())

    assert sentence is not None
    assert "last year" not in sentence
    assert "a year ago" not in sentence
