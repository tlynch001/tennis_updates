"""Unit tests for wta_daily.scripts_gen.tournament_status_narration."""

from __future__ import annotations

import random

import pytest

from wta_daily.models import MatchResult, TournamentRunStatus, TournamentState
from wta_daily.scripts_gen.tournament_status_narration import (
    build_tournament_status_sentence,
    is_result_of_reported_match,
    supersedes_inactivity_narration,
)
from wta_daily.tour import profile_for


def _loss(*, opponent: str = "Some Rival") -> MatchResult:
    return MatchResult(
        opponent=opponent,
        tournament="Cincinnati",
        round="Round of 16",
        score="6-4,6-3",
        won=False,
        match_date=None,
    )


def _win(*, opponent: str = "Some Rival") -> MatchResult:
    return MatchResult(
        opponent=opponent,
        tournament="Cincinnati",
        round="Final",
        score="6-4,6-3",
        won=True,
        match_date=None,
    )


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
        ("QF", "R32", "improving"),
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


# --- Narration-polish follow-up: precedence, naming, grammar ----------------


def test_supersedes_inactivity_narration_true_for_eliminated_and_champion() -> None:
    assert supersedes_inactivity_narration(TournamentRunStatus(state=TournamentState.ELIMINATED)) is True
    assert supersedes_inactivity_narration(TournamentRunStatus(state=TournamentState.CHAMPION)) is True


@pytest.mark.parametrize(
    "state",
    [TournamentState.ACTIVE, TournamentState.DID_NOT_PARTICIPATE, TournamentState.UNKNOWN],
)
def test_supersedes_inactivity_narration_false_for_non_terminal_states(state: TournamentState) -> None:
    assert supersedes_inactivity_narration(TournamentRunStatus(state=state)) is False


def test_supersedes_inactivity_narration_false_for_none() -> None:
    assert supersedes_inactivity_narration(None) is False


def test_uses_first_name_not_full_name_after_introduction() -> None:
    """The full name is assumed already introduced by the caller (see the
    module docstring) - this sentence should never repeat it."""

    status = TournamentRunStatus(
        state=TournamentState.ELIMINATED,
        round_reached="R32",
        round_label="the Round of 32",
        eliminated_by="Jessica Pegula",
        points_earned=65,
        is_new_development=True,
    )

    for seed in range(30):
        sentence = build_tournament_status_sentence(status, "Emma Navarro", random.Random(seed))
        assert sentence is not None
        assert "Navarro" not in sentence
        assert "Emma" in sentence


def test_first_name_used_after_eliminator_avoids_pronoun_ambiguity() -> None:
    """Once the eliminator's name has been mentioned, the points sentence
    must refer to the eliminated player by her first name (not a bare
    'she'/'her'), so it's unambiguous which player earned the points -
    see the module docstring's "Jessica Pegula... Emma earned" example."""

    status = TournamentRunStatus(
        state=TournamentState.ELIMINATED,
        round_reached="R32",
        round_label="the Round of 32",
        eliminated_by="Jessica Pegula",
        points_earned=65,
        is_new_development=True,
    )

    for seed in range(30):
        sentence = build_tournament_status_sentence(status, "Emma Navarro", random.Random(seed))
        assert sentence is not None
        sentences = sentence.split(". ")
        assert len(sentences) >= 2
        points_sentence = next(s for s in sentences if "65" in s)
        # Her first name (not a bare pronoun) must be the one identifying
        # who earned the points - unambiguous regardless of word order.
        assert "Emma" in points_sentence
        assert not points_sentence.strip().startswith(("She ", "Her "))


@pytest.mark.parametrize("seed", range(50))
def test_historical_comparison_never_produces_a_duplicate_article(seed: int) -> None:
    status = TournamentRunStatus(
        state=TournamentState.ELIMINATED,
        round_reached="R32",
        round_label="the Round of 32",
        eliminated_by="Jessica Pegula",
        points_earned=65,
        previous_year_round="R64",
        previous_year_round_label="the Round of 64",
        previous_year_points=35,
        points_delta=30,
        is_new_development=True,
    )

    sentence = build_tournament_status_sentence(status, "Emma Navarro", random.Random(seed))

    assert sentence is not None
    lowered = sentence.lower()
    assert "the the" not in lowered
    assert "her the" not in lowered
    assert "last year's the" not in lowered
    assert "a the" not in lowered


def test_points_sentence_prefers_ranking_points_wording() -> None:
    status = TournamentRunStatus(
        state=TournamentState.ELIMINATED,
        round_reached="R32",
        round_label="the Round of 32",
        eliminated_by="Jessica Pegula",
        points_earned=65,
        is_new_development=True,
    )

    for seed in range(20):
        sentence = build_tournament_status_sentence(status, "Emma Navarro", random.Random(seed))
        assert sentence is not None
        assert "ranking points" in sentence


def test_net_swing_is_phrased_as_a_continuation_of_the_history_clause() -> None:
    """The net-points-swing figure must read as a natural continuation of
    the historical comparison, not a separately crammed-on fragment -
    i.e. it should never appear without a comparison clause before it."""

    status = TournamentRunStatus(
        state=TournamentState.ELIMINATED,
        round_reached="R32",
        round_label="the Round of 32",
        eliminated_by="Jessica Pegula",
        points_earned=65,
        previous_year_round="R64",
        previous_year_round_label="the Round of 64",
        previous_year_points=35,
        points_delta=30,
        is_new_development=True,
    )

    for seed in range(20):
        sentence = build_tournament_status_sentence(status, "Emma Navarro", random.Random(seed))
        assert sentence is not None
        assert "30 points" in sentence
        # The swing figure only ever appears alongside the historical
        # comparison wording, never on its own.
        markers = (
            "improving",
            "better than",
            "step up",
            "matching",
            "same result",
            "step back",
            "short of",
        )
        assert any(marker in sentence for marker in markers)


def test_detailed_report_produces_multiple_sentences_when_history_is_known() -> None:
    """Splitting the elimination fact from the points/history fact into
    separate sentences (rather than one giant dash-joined sentence) is
    the whole point of this polish pass."""

    status = TournamentRunStatus(
        state=TournamentState.ELIMINATED,
        round_reached="R32",
        round_label="the Round of 32",
        eliminated_by="Jessica Pegula",
        points_earned=65,
        previous_year_round="R64",
        previous_year_round_label="the Round of 64",
        previous_year_points=35,
        points_delta=30,
        is_new_development=True,
    )

    sentence = build_tournament_status_sentence(status, "Emma Navarro", random.Random(1))

    assert sentence is not None
    # At least two sentences, each properly capitalized/punctuated.
    parts = [p for p in sentence.split(". ") if p]
    assert len(parts) >= 2
    for part in parts:
        assert part[0].isupper()


def test_narration_still_varies_across_seeds_after_the_polish_pass() -> None:
    """Regression guard: the rewritten phrase pools must still produce
    genuine day-to-day variation, not a single fixed template."""

    status = TournamentRunStatus(
        state=TournamentState.ELIMINATED,
        round_reached="R32",
        round_label="the Round of 32",
        eliminated_by="Jessica Pegula",
        points_earned=65,
        is_new_development=True,
    )

    outputs = {
        build_tournament_status_sentence(status, "Emma Navarro", random.Random(seed)) for seed in range(30)
    }
    assert len(outputs) > 1


# --- New elimination (this match) vs. prior-day elimination ---------------


def test_is_result_of_reported_match_true_for_a_loss_that_eliminated_her() -> None:
    status = TournamentRunStatus(state=TournamentState.ELIMINATED, round_reached="R16")

    assert is_result_of_reported_match(status, _loss()) is True


def test_is_result_of_reported_match_true_for_a_win_that_won_the_title() -> None:
    status = TournamentRunStatus(state=TournamentState.CHAMPION, round_reached="W")

    assert is_result_of_reported_match(status, _win()) is True


def test_is_result_of_reported_match_false_when_no_match_is_given() -> None:
    status = TournamentRunStatus(state=TournamentState.ELIMINATED, round_reached="R16")

    assert is_result_of_reported_match(status, None) is False


def test_is_result_of_reported_match_false_when_status_is_none() -> None:
    assert is_result_of_reported_match(None, _loss()) is False


def test_is_result_of_reported_match_false_for_a_win_while_eliminated() -> None:
    """A won match can't be the one that eliminated her - this only
    happens if the fixture data is stale/inconsistent, and must never be
    treated as 'just happened' causally."""

    status = TournamentRunStatus(state=TournamentState.ELIMINATED, round_reached="R16")

    assert is_result_of_reported_match(status, _win()) is False


def test_is_result_of_reported_match_false_for_active_or_did_not_participate() -> None:
    assert is_result_of_reported_match(TournamentRunStatus(state=TournamentState.ACTIVE), _loss()) is False
    assert (
        is_result_of_reported_match(TournamentRunStatus(state=TournamentState.DID_NOT_PARTICIPATE), _loss())
        is False
    )


def test_a_newly_eliminated_player_gets_causal_immediate_language() -> None:
    """The exact regression: a player eliminated by the match just
    narrated must get 'that ends her run...' style language, never
    'still'/'remains'/'back in' language."""

    status = TournamentRunStatus(
        state=TournamentState.ELIMINATED,
        tournament="Cincinnati",
        round_reached="R16",
        round_label="the Round of 16",
        eliminated_by="Marta Kostyuk",
        points_earned=120,
        is_new_development=True,
    )

    for seed in range(30):
        sentence = build_tournament_status_sentence(
            status, "Mirra Andreeva", random.Random(seed), match=_loss(opponent="Marta Kostyuk")
        )
        assert sentence is not None
        lowered = sentence.lower()
        for forbidden in ("still over", "remains out", "eliminated back in", "was eliminated by"):
            assert forbidden not in lowered
        # The match sentence (built by the caller, not this function)
        # already named the eliminator - this sentence must not repeat it.
        assert "Marta Kostyuk" not in sentence
        assert "Round of 16" in sentence


def test_a_newly_crowned_champion_gets_causal_immediate_language() -> None:
    status = TournamentRunStatus(
        state=TournamentState.CHAMPION,
        tournament="Cincinnati",
        round_reached="W",
        round_label="the title",
        points_earned=1000,
        is_new_development=True,
    )

    for seed in range(20):
        sentence = build_tournament_status_sentence(
            status, "Test Player", random.Random(seed), match=_win()
        )
        assert sentence is not None
        lowered = sentence.lower()
        assert "title" in lowered or "champion" in lowered
        assert "remains" not in lowered
        assert "still" not in lowered


def test_an_earlier_reporting_day_elimination_can_use_prior_status_language() -> None:
    """No match reported today (the elimination happened on an earlier
    day) - the existing 'was eliminated by.../remains out of the draw'
    language is appropriate here, since it hasn't been said in this
    run's script yet."""

    status = TournamentRunStatus(
        state=TournamentState.ELIMINATED,
        tournament="Cincinnati",
        round_reached="R16",
        round_label="the Round of 16",
        eliminated_by="Marta Kostyuk",
        points_earned=120,
        is_new_development=True,
    )

    sentence = build_tournament_status_sentence(status, "Mirra Andreeva", random.Random(0), match=None)

    assert sentence is not None
    assert "Marta Kostyuk" in sentence


def test_an_already_reported_elimination_still_gets_brief_language_when_no_match_today() -> None:
    """The brief (already-reported) elimination language must remain
    short (no points/eliminator repeated) - but must express this as a
    completed historical fact, never ongoing-state language like
    'remains'/'still' (see the module docstring's production incident)."""

    status = TournamentRunStatus(
        state=TournamentState.ELIMINATED,
        round_reached="R16",
        round_label="the Round of 16",
        is_new_development=False,
    )

    sentence = build_tournament_status_sentence(status, "Linda Noskova", random.Random(0), match=None)

    assert sentence is not None
    lowered = sentence.lower()
    assert "still" not in lowered
    assert "remains" not in lowered
    assert "ended" in lowered or "came to an end" in lowered


def test_backward_compatible_when_match_is_omitted() -> None:
    """Omitting `match` entirely (the pre-existing call signature) must
    still work exactly as before - it simply disables the 'just
    happened' distinction rather than raising."""

    status = TournamentRunStatus(
        state=TournamentState.ELIMINATED,
        round_reached="R16",
        round_label="the Round of 16",
        eliminated_by="Some Rival",
        is_new_development=True,
    )

    sentence = build_tournament_status_sentence(status, "Test Player", random.Random(0))

    assert sentence is not None
    assert "Some Rival" in sentence


def test_new_elimination_language_still_varies_across_seeds() -> None:
    status = TournamentRunStatus(
        state=TournamentState.ELIMINATED,
        tournament="Cincinnati",
        round_reached="R16",
        round_label="the Round of 16",
        eliminated_by="Marta Kostyuk",
        is_new_development=True,
    )

    outputs = {
        build_tournament_status_sentence(status, "Mirra Andreeva", random.Random(seed), match=_loss())
        for seed in range(30)
    }
    assert len(outputs) > 1


def test_wta_elimination_narration_still_uses_her() -> None:
    status = TournamentRunStatus(
        state=TournamentState.ELIMINATED,
        tournament="Cincinnati",
        round_reached="R16",
        round_label="the Round of 16",
        eliminated_by="Marta Kostyuk",
        is_new_development=True,
    )

    sentence = build_tournament_status_sentence(
        status, "Mirra Andreeva", random.Random(0), match=_loss(opponent="Marta Kostyuk")
    )

    assert sentence is not None
    assert " her " in f" {sentence} " or sentence.lower().startswith("her ")
    assert " his " not in f" {sentence} "


def test_atp_elimination_narration_uses_male_pronouns_not_wta_wording() -> None:
    status = TournamentRunStatus(
        state=TournamentState.ELIMINATED,
        tournament="Cincinnati",
        round_reached="R16",
        round_label="the Round of 16",
        eliminated_by="Some Rival",
        is_new_development=True,
    )
    atp = profile_for("atp")

    for seed in range(20):
        sentence = build_tournament_status_sentence(
            status,
            "Jannik Sinner",
            random.Random(seed),
            match=_loss(),
            profile=atp,
        )
        assert sentence is not None
        lowered = f" {sentence.lower()} "
        assert " her " not in lowered
        assert " she " not in lowered
        assert "WTA" not in sentence
        assert " his " in lowered or " him " in lowered or " he " in lowered

