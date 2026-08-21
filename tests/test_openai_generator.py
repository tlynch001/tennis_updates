"""Unit tests for wta_daily.scripts_gen.openai_generator's prompt-building
helpers - the parts that are pure functions and don't require a network
call or API key.
"""

from __future__ import annotations

from datetime import date

from wta_daily.config import ScriptConfig
from wta_daily.models import (
    DailyReport,
    FeaturedPlayerReport,
    MatchResult,
    Movement,
    PlayerReport,
    TournamentRunStatus,
    TournamentState,
)
from wta_daily.scripts_gen.openai_generator import _build_user_prompt, _tournament_status_line


def _loss(*, opponent: str = "Some Rival") -> MatchResult:
    return MatchResult(
        opponent=opponent,
        tournament="Cincinnati",
        round="Round of 16",
        score="6-4,6-3",
        won=False,
        match_date=date(2026, 8, 19),
    )


def _player(**overrides: object) -> PlayerReport:
    defaults: dict[str, object] = {
        "rank": 3,
        "name": "Test Player",
        "player_id": "p3",
        "country_code": "USA",
        "points": 5000,
        "movement": Movement.SAME,
        "previous_rank": 3,
    }
    defaults.update(overrides)
    return PlayerReport(**defaults)  # type: ignore[arg-type]


def test_tournament_status_line_is_none_when_status_is_none() -> None:
    assert _tournament_status_line(None, None) is None


def test_tournament_status_line_for_active_states_no_context_to_add() -> None:
    line = _tournament_status_line(TournamentRunStatus(state=TournamentState.ACTIVE), None)
    assert line is not None
    assert "no elimination/title context" in line


def test_tournament_status_line_for_elimination_includes_facts() -> None:
    status = TournamentRunStatus(
        state=TournamentState.ELIMINATED,
        round_reached="R16",
        round_label="the Round of 16",
        eliminated_by="Some Rival",
        points_earned=120,
        previous_year_round_label="the quarterfinals",
        points_delta=-95,
        is_new_development=True,
    )

    line = _tournament_status_line(status, None)

    assert line is not None
    assert "detailed" in line
    assert "Some Rival" in line
    assert "Round of 16" in line
    assert "120" in line
    assert "-95" in line


def test_tournament_status_line_marks_brief_for_already_reported_result() -> None:
    status = TournamentRunStatus(
        state=TournamentState.ELIMINATED,
        round_reached="R16",
        round_label="the Round of 16",
        is_new_development=False,
    )

    line = _tournament_status_line(status, None)

    assert line is not None
    assert "brief" in line


def test_tournament_status_line_flags_a_result_from_the_match_being_narrated() -> None:
    status = TournamentRunStatus(
        state=TournamentState.ELIMINATED,
        round_reached="R16",
        round_label="the Round of 16",
        eliminated_by="Some Rival",
        is_new_development=True,
    )

    line = _tournament_status_line(status, _loss())

    assert line is not None
    assert "just happened" in line
    assert "detailed" not in line.split(";")[0]  # the first segment names the flag, not "detailed"


def test_user_prompt_includes_tournament_status_line_for_a_player() -> None:
    player = _player(
        tournament_status=TournamentRunStatus(
            state=TournamentState.ELIMINATED,
            round_reached="QF",
            round_label="the quarterfinals",
            eliminated_by="Some Rival",
            is_new_development=True,
        )
    )
    report = DailyReport(report_date=date(2026, 8, 19), tour="wta", players=[player])

    prompt = _build_user_prompt(report, ScriptConfig())

    assert "Tournament status:" in prompt
    assert "Some Rival" in prompt


def test_user_prompt_omits_tournament_status_line_when_absent() -> None:
    player = _player()
    report = DailyReport(report_date=date(2026, 8, 19), tour="wta", players=[player])

    prompt = _build_user_prompt(report, ScriptConfig())

    assert "Tournament status:" not in prompt


def test_user_prompt_includes_featured_player_tournament_status() -> None:
    player = _player()
    featured = FeaturedPlayerReport(
        name="Emma Navarro",
        player_id="325410",
        tagline="america_favorite",
        rank=28,
        points=1669,
        movement=Movement.SAME,
        tournament_status=TournamentRunStatus(
            state=TournamentState.CHAMPION,
            round_reached="W",
            round_label="the title",
            points_earned=1000,
            is_new_development=True,
        ),
    )
    report = DailyReport(
        report_date=date(2026, 8, 19), tour="wta", players=[player], featured_player=featured
    )

    prompt = _build_user_prompt(report, ScriptConfig())

    assert "Tournament status:" in prompt
    assert "champion" in prompt


def test_match_description_omits_round_when_unknown() -> None:
    from wta_daily.scripts_gen.openai_generator import _match_description

    match = MatchResult(
        opponent="Amanda Anisimova",
        tournament="Cincinnati",
        round=None,
        score="6-4,2-6,7-6(4)",
        won=True,
        match_date=date(2026, 8, 19),
    )

    description = _match_description(match)

    assert "None" not in description
    assert "Amanda Anisimova" in description
    assert "Cincinnati" in description


def test_match_description_includes_round_when_known() -> None:
    from wta_daily.scripts_gen.openai_generator import _match_description

    match = MatchResult(
        opponent="Amanda Anisimova",
        tournament="Cincinnati",
        round="Quarterfinal",
        score="6-4,2-6,7-6(4)",
        won=True,
        match_date=date(2026, 8, 19),
    )

    description = _match_description(match)

    assert "Quarterfinal" in description


def test_user_prompt_never_includes_a_raw_none_round() -> None:
    player = _player(
        match=MatchResult(
            opponent="Amanda Anisimova",
            tournament="Cincinnati",
            round=None,
            score="6-4,2-6,7-6(4)",
            won=True,
            match_date=date(2026, 8, 19),
        )
    )
    report = DailyReport(report_date=date(2026, 8, 19), tour="wta", players=[player])

    prompt = _build_user_prompt(report, ScriptConfig())

    assert "(None," not in prompt
    assert "None," not in prompt
