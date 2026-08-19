"""Unit tests for wta_daily.plugins.matches.tournament_status - built
entirely from realistic fixture dicts, no HTTP mocking needed."""

from __future__ import annotations

from typing import Any

from wta_daily.models import TournamentState
from wta_daily.plugins.matches.tournament_status import determine_tournament_run_status

PLAYER = "p1"
OPPONENT = "p2"


def _fixture(
    *,
    round_id: str,
    winner: str | None,
    match_state: str = "F",
    player_a: str = PLAYER,
    player_b: str = OPPONENT,
    draw_level: str = "M",
    match_type: str = "S",
    opponent_first: str = "Some",
    opponent_last: str = "Opponent",
) -> dict[str, Any]:
    return {
        "DrawLevelType": draw_level,
        "DrawMatchType": match_type,
        "RoundID": round_id,
        "MatchState": match_state,
        "PlayerIDA": player_a,
        "PlayerIDB": player_b,
        "PlayerNameFirstA": "Player" if player_a == PLAYER else opponent_first,
        "PlayerNameLastA": "One" if player_a == PLAYER else opponent_last,
        "PlayerNameFirstB": opponent_first if player_b == OPPONENT else "Player",
        "PlayerNameLastB": opponent_last if player_b == OPPONENT else "One",
        "Winner": winner,
    }


def _status(fixtures: list[dict[str, Any]], *, draw_size: int | None = 96, category: str = "WTA 1000"):
    return determine_tournament_run_status(
        fixtures,
        PLAYER,
        tournament_name="Cincinnati",
        tournament_group_id=901,
        category=category,
        draw_size=draw_size,
    )


def test_active_when_a_fixture_is_not_yet_finished() -> None:
    fixtures = [
        _fixture(round_id="1", winner="2", match_state="F"),
        _fixture(round_id="2", winner=None, match_state="O"),  # scheduled, not played
    ]

    status = _status(fixtures)

    assert status.state == TournamentState.ACTIVE
    assert status.tournament == "Cincinnati"
    assert status.tournament_group_id == "901"


def test_did_not_participate_when_player_absent_from_every_fixture() -> None:
    fixtures = [_fixture(round_id="1", winner="2", player_a="other-1", player_b="other-2")]

    status = _status(fixtures)

    assert status.state == TournamentState.DID_NOT_PARTICIPATE
    assert status.tournament is None


def test_eliminated_at_the_latest_finished_round_on_a_loss() -> None:
    fixtures = [
        _fixture(round_id="1", winner="2"),  # won round 1 (R128)
        _fixture(round_id="2", winner="2"),  # won round 2 (R64)
        _fixture(round_id="4", winner="3", opponent_first="Elena", opponent_last="Rybakina"),  # lost R16
    ]

    status = _status(fixtures)

    assert status.state == TournamentState.ELIMINATED
    assert status.round_reached == "R16"
    assert status.round_label == "the Round of 16"
    assert status.eliminated_by == "Elena Rybakina"


def test_champion_on_a_won_final() -> None:
    fixtures = [
        _fixture(round_id="4", winner="2"),
        _fixture(round_id="Q", winner="2"),
        _fixture(round_id="S", winner="2"),
        _fixture(round_id="F", winner="2"),
    ]

    status = _status(fixtures)

    assert status.state == TournamentState.CHAMPION
    assert status.round_reached == "W"
    assert status.round_label == "the title"


def test_active_when_won_latest_match_but_it_is_not_the_final() -> None:
    """Winning her most recent known match (without it being the final)
    never becomes a guessed CHAMPION/ELIMINATED state - just ACTIVE, since
    the next round's fixture may simply not be in the feed yet."""

    fixtures = [_fixture(round_id="4", winner="2")]  # won R16, no further fixture present

    status = _status(fixtures)

    assert status.state == TournamentState.ACTIVE


def test_grand_slam_round_label_uses_ordinal_convention() -> None:
    fixtures = [_fixture(round_id="4", winner="3")]  # lost the fourth round

    status = _status(fixtures, category="GRAND SLAM", draw_size=128)

    assert status.state == TournamentState.ELIMINATED
    assert status.round_reached == "R16"
    assert status.round_label == "the fourth round"


def test_ignores_qualifying_and_doubles_fixtures() -> None:
    fixtures = [
        _fixture(round_id="1", winner="3", draw_level="Q"),  # qualifying loss - irrelevant
        _fixture(round_id="1", winner="3", match_type="D"),  # doubles loss - irrelevant
        _fixture(round_id="2", winner="2"),  # the actual main-draw singles win
    ]

    status = _status(fixtures)

    # Only the main-draw singles win counts; she's still active (no later
    # finished fixture, no unplayed one either in this constructed case).
    assert status.state == TournamentState.ACTIVE


def test_skips_a_finished_fixture_with_no_derivable_winner() -> None:
    fixtures = [_fixture(round_id="1", winner=None, match_state="F")]

    status = _status(fixtures)

    assert status.state == TournamentState.DID_NOT_PARTICIPATE


def test_skips_a_fixture_whose_round_cannot_be_normalized() -> None:
    fixtures = [_fixture(round_id="RR", winner="2")]

    status = _status(fixtures)

    assert status.state == TournamentState.DID_NOT_PARTICIPATE


def test_works_regardless_of_which_slot_the_player_is_in() -> None:
    # player_a is the opponent here, so winner="2" (slot A) means the
    # opponent won and our PLAYER (slot B) lost.
    fixtures = [_fixture(round_id="4", winner="2", player_a=OPPONENT, player_b=PLAYER)]

    status = _status(fixtures)

    assert status.state == TournamentState.ELIMINATED
    assert status.round_reached == "R16"


def test_uses_the_configured_draw_size_for_round_normalization() -> None:
    """A 32-draw's round '2' is R16, not R64 - the same round_id means
    something different depending on draw size."""

    fixtures = [_fixture(round_id="2", winner="3")]

    status = _status(fixtures, draw_size=32, category="WTA 250")

    assert status.round_reached == "R16"
