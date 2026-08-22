"""ATP weekly movement narration — presentation only.

Uses synthetic reports. Does not call BALLDONTLIE or rewrite local ATP history.
"""

from __future__ import annotations

from datetime import date

from wta_daily.models import DailyReport, Movement, PlayerReport, RankingsDeparture
from wta_daily.scripts_gen.template_generator import TemplateScriptGenerator
from wta_daily.scripts_gen.weekly_rankings_narration import (
    format_places,
    generate_weekly_rankings_script,
    places_delta,
    summarize_weekly_movement,
)
from wta_daily.tour import ATP, WTA


def _player(
    rank: int,
    name: str,
    *,
    points: int = 5000,
    movement: Movement = Movement.SAME,
    previous_rank: int | None = None,
    player_id: str | None = None,
) -> PlayerReport:
    return PlayerReport(
        rank=rank,
        name=name,
        player_id=player_id or name.lower().replace(" ", "-"),
        country_code="USA",
        points=points,
        movement=movement,
        previous_rank=previous_rank,
    )


def _report(
    players: list[PlayerReport],
    *,
    departed: list[RankingsDeparture] | None = None,
    ranking_date: date | None = date(2026, 8, 25),
) -> DailyReport:
    return DailyReport(
        report_date=date(2026, 8, 25),
        tour="atp",
        players=players,
        ranking_date=ranking_date,
        departed_players=departed or [],
    )


def _script(report: DailyReport) -> str:
    return TemplateScriptGenerator().generate(report)


def test_wta_weekly_flag_is_off() -> None:
    assert WTA.emphasizes_weekly_ranking_movement is False
    assert ATP.emphasizes_weekly_ranking_movement is True


def test_first_run_is_baseline_without_fake_movement() -> None:
    players = [
        _player(1, "Jannik Sinner", points=13450, movement=Movement.UNKNOWN, previous_rank=None),
        _player(2, "Carlos Alcaraz", points=12000, movement=Movement.UNKNOWN, previous_rank=None),
        _player(3, "Alexander Zverev", points=7000, movement=Movement.UNKNOWN, previous_rank=None),
    ]
    report = _report(players)
    summary = summarize_weekly_movement(report)
    script = _script(report)
    lowered = script.lower()

    assert summary.is_baseline is True
    assert summary.biggest_up is None
    assert "baseline" in lowered or "starting" in lowered or "no previous snapshot" in lowered
    assert "new face" not in lowered
    assert "just entered" not in lowered
    assert "climbs" not in lowered
    assert "breaks into" not in lowered
    assert "another week" not in lowered
    assert "13,450 ranking points" in script
    assert "12,000 ranking points" in script
    assert "did not play yesterday" not in lowered
    assert "wta" not in lowered
    assert " she " not in f" {script} "
    assert "defeated" not in lowered
    assert "eliminat" not in lowered
    assert "champion" not in lowered


def test_upward_movement_names_places_gained() -> None:
    report = _report(
        [
            _player(1, "Jannik Sinner", points=13450, previous_rank=1),
            _player(6, "Ben Shelton", points=3670, movement=Movement.UP, previous_rank=10),
        ]
    )
    script = _script(report)
    lowered = script.lower()

    assert places_delta(report.players[1]) == 4
    assert "four places" in lowered
    assert "number 10" in lowered
    assert "number 6" in lowered
    assert "ben shelton" in lowered
    assert "3,670" in script


def test_downward_movement_names_one_place_drop() -> None:
    report = _report(
        [
            _player(1, "Jannik Sinner", points=13450, previous_rank=1),
            _player(7, "Daniil Medvedev", points=3580, movement=Movement.DOWN, previous_rank=6),
        ]
    )
    script = _script(report)
    lowered = script.lower()

    assert places_delta(report.players[1]) == -1
    assert "one place" in lowered
    assert "number 6" in lowered
    assert "number 7" in lowered
    assert "daniil medvedev" in lowered
    assert "3,580" in script


def test_unchanged_number_one_uses_hold_wording() -> None:
    report = _report(
        [
            _player(1, "Jannik Sinner", points=13450, previous_rank=1),
            _player(2, "Carlos Alcaraz", points=10450, previous_rank=2),
        ]
    )
    script = _script(report)
    lowered = script.lower()

    assert "jannik sinner" in lowered
    assert "13,450" in script
    assert any(word in lowered for word in ("holds", "remains", "stays"))
    assert "climbs" not in lowered


def test_top_10_entrant_uses_neutral_wording() -> None:
    report = _report(
        [
            _player(1, "Jannik Sinner", points=13450, previous_rank=1),
            _player(10, "Jack Draper", points=2960, movement=Movement.NEW, previous_rank=None),
        ]
    )
    script = _script(report)
    lowered = script.lower()

    assert "jack draper" in lowered
    assert "top 2" in lowered or "top 10" in lowered
    assert "moves into" in lowered or "enters" in lowered
    assert "returns to" not in lowered
    assert "breaks into" not in lowered
    assert "career" not in lowered
    assert "2,960" in script


def test_top_10_departure_is_mentioned_when_snapshot_lists_them() -> None:
    departed = RankingsDeparture(name="Holger Rune", player_id="rune", previous_rank=8)
    report = _report(
        [
            _player(1, "Jannik Sinner", points=13450, previous_rank=1),
            _player(6, "Ben Shelton", points=3670, movement=Movement.UP, previous_rank=10),
        ],
        departed=[departed],
    )
    summary = summarize_weekly_movement(report)
    script = _script(report)

    assert summary.departed == (departed,)
    assert "Holger Rune" in script
    assert "out of the Top" in script


def test_biggest_mover_is_the_largest_climb() -> None:
    report = _report(
        [
            _player(1, "Jannik Sinner", points=13450, previous_rank=1),
            _player(4, "Taylor Fritz", points=4655, movement=Movement.UP, previous_rank=5),
            _player(6, "Ben Shelton", points=3670, movement=Movement.UP, previous_rank=10),
            _player(7, "Daniil Medvedev", points=3580, movement=Movement.DOWN, previous_rank=6),
        ]
    )
    summary = summarize_weekly_movement(report)
    script = _script(report)

    assert summary.biggest_up is not None
    assert summary.biggest_up.name == "Ben Shelton"
    assert "Ben Shelton" in script
    assert "four places" in script
    assert script.lower().index("ben shelton") < script.lower().index("taylor fritz") or (
        "biggest" in script.lower() and "ben shelton" in script.lower()
    )


def test_no_movement_uses_steady_wording_not_identical_drama() -> None:
    players = [
        _player(i, f"Player {i}", points=10000 - i * 100, previous_rank=i) for i in range(1, 11)
    ]
    report = _report(players)
    summary = summarize_weekly_movement(report)
    script = _script(report)
    lowered = script.lower()

    assert summary.is_baseline is False
    assert summary.biggest_up is None
    assert summary.held_count == 10
    assert "steady" in lowered or "no movement" in lowered or "holding" in lowered
    assert "biggest mover" not in lowered
    assert "climbs" not in lowered
    assert "skyrockets" not in lowered
    assert "collapses" not in lowered
    unique_player_lines = {line for line in script.split("\n\n") if line.startswith("Player")}
    assert len(unique_player_lines) >= 8


def test_close_points_gap_can_be_mentioned_for_an_unchanged_player() -> None:
    report = _report(
        [
            _player(2, "Carlos Alcaraz", points=10450, previous_rank=2),
            _player(3, "Alexander Zverev", points=10380, previous_rank=3),
        ]
    )
    script = _script(report)

    assert "Alexander Zverev" in script
    assert "70" in script
    assert "points" in script.lower()


def test_weekly_script_has_no_match_language() -> None:
    report = _report(
        [
            _player(1, "Jannik Sinner", points=13450, previous_rank=1),
            _player(6, "Ben Shelton", points=3670, movement=Movement.UP, previous_rank=10),
        ]
    )
    script = _script(report).lower()

    for banned in (
        "did not play yesterday",
        "defeated",
        "lost to",
        "eliminat",
        "champion",
        "opponent",
        "yesterday",
        " wta ",
    ):
        assert banned not in f" {script} "


def test_format_places_uses_words() -> None:
    assert format_places(1) == "one place"
    assert format_places(4) == "four places"
    assert format_places(-2) == "two places"


def test_generate_weekly_helper_matches_template_generator() -> None:
    report = _report([_player(1, "Jannik Sinner", points=13450, previous_rank=1)])
    assert generate_weekly_rankings_script(report) == _script(report)
