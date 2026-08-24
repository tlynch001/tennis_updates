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
    points_delta,
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
    previous_points: int | None = None,
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
        previous_points=previous_points,
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
    assert "since last week" not in lowered
    assert "from last week" not in lowered
    assert "unchanged from last week" not in lowered
    assert "points earned" not in lowered
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
    assert "daniil medvedev" in lowered
    assert "number 7" in lowered
    assert "3,580" in script
    assert ", moving from" not in lowered
    assert "one place" in lowered or "number 6" in lowered


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
    assert "moving into" in lowered or "moves into" in lowered or "enters" in lowered
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
    assert "out of the Top" in script or "Leaving the Top" in script
    assert "pushes" not in script.lower()
    assert "that move" not in script.lower()


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


def test_headline_mover_is_not_described_twice() -> None:
    report = _report(
        [
            _player(1, "Jannik Sinner", points=13450, previous_rank=1),
            _player(6, "Ben Shelton", points=3670, movement=Movement.UP, previous_rank=10),
        ]
    )
    script = _script(report)
    lowered = script.lower()

    assert lowered.count("four places") == 1
    assert lowered.count("from number 10 to number 6") == 1
    assert lowered.count("ben shelton") == 1
    assert "3,670" in script
    assert "ben is now number 6" in lowered or "ben now sits at number 6" in lowered


def test_unchanged_player_wording_avoids_continues_at() -> None:
    report = _report(
        [
            _player(1, "Jannik Sinner", points=13450, previous_rank=1),
            _player(2, "Carlos Alcaraz", points=10450, previous_rank=2),
            _player(4, "Novak Djokovic", points=7830, previous_rank=4),
        ]
    )
    script = _script(report)
    lowered = script.lower()

    assert "continues at" not in lowered
    assert "carlos alcaraz" in lowered
    assert "novak djokovic" in lowered
    assert any(
        phrase in lowered
        for phrase in (
            "holds at number",
            "remains number",
            "stays at number",
            "holds the number",
            "remains in the number",
        )
    )


def test_downward_movement_does_not_restate_the_same_change() -> None:
    report = _report(
        [
            _player(1, "Jannik Sinner", points=13450, previous_rank=1),
            _player(8, "Alex de Minaur", points=3485, movement=Movement.DOWN, previous_rank=7),
        ]
    )
    script = _script(report)
    lowered = script.lower()

    assert "alex de minaur" in lowered
    assert "3,485" in script
    assert "number 8" in lowered
    assert ", moving from" not in lowered
    assert "falls one place, moving" not in lowered


def test_adjacent_unchanged_lines_vary_leading_verbs() -> None:
    players = [
        _player(i, f"Player {i}", points=10000 - i * 200, previous_rank=i) for i in range(1, 6)
    ]
    script = _script(_report(players))
    lines = [line.split(".")[0] for line in script.split("\n\n") if line.startswith("Player")]
    verbs = [line.split()[2].lower() for line in lines]

    assert len(verbs) >= 4
    for left, right in zip(verbs, verbs[1:]):
        assert left != right


def test_wta_daily_narration_path_and_wording_remain_unchanged() -> None:
    report = DailyReport(
        report_date=date(2026, 8, 17),
        tour="wta",
        players=[
            PlayerReport(
                rank=1,
                name="Aryna Sabalenka",
                player_id="1",
                country_code="BLR",
                points=10000,
                movement=Movement.SAME,
                previous_rank=1,
            ),
            PlayerReport(
                rank=2,
                name="Iga Swiatek",
                player_id="2",
                country_code="POL",
                points=9000,
                movement=Movement.SAME,
                previous_rank=2,
            ),
        ],
    )
    script = TemplateScriptGenerator().generate(report)
    lowered = script.lower()

    assert "wta top" in lowered
    assert "did not play yesterday" in lowered
    assert "women's game" in lowered or "we'll be back tomorrow" in lowered
    assert "this week's atp" not in lowered
    assert "this week's wta top" not in lowered
    assert "biggest mover" not in lowered
    assert "biggest move" not in lowered
    assert "we'll see how the rankings change when the next official list is released" not in lowered


def test_departure_wording_is_factual_not_causal() -> None:
    report = _report(
        [
            _player(1, "Jannik Sinner", points=13450, previous_rank=1),
            _player(10, "Jack Draper", points=2960, movement=Movement.NEW, previous_rank=None),
        ],
        departed=[RankingsDeparture(name="Holger Rune", player_id="rune", previous_rank=8)],
    )
    script = _script(report)
    lowered = script.lower()

    assert "holger rune" in lowered
    assert "pushes" not in lowered
    assert "that move" not in lowered
    assert "those changes push" not in lowered


def test_points_delta_helper() -> None:
    gained = _player(2, "Carlos Alcaraz", points=8160, previous_rank=2, previous_points=7730)
    lost = _player(3, "Alexander Zverev", points=8090, previous_rank=3, previous_points=8410)
    unchanged = _player(1, "Jannik Sinner", points=13450, previous_rank=1, previous_points=13450)
    missing = _player(1, "Jannik Sinner", points=13450, previous_rank=1, previous_points=None)

    assert points_delta(gained) == 430
    assert points_delta(lost) == -320
    assert points_delta(unchanged) == 0
    assert points_delta(missing) is None


def test_gains_points_while_rank_unchanged() -> None:
    report = _report(
        [
            _player(1, "Jannik Sinner", points=13450, previous_rank=1, previous_points=13450),
            _player(2, "Carlos Alcaraz", points=8160, previous_rank=2, previous_points=7730),
        ]
    )
    script = _script(report)
    lowered = script.lower()

    assert points_delta(report.players[1]) == 430
    assert "carlos alcaraz" in lowered
    assert "8,160" in script
    assert "430" in script
    assert "points earned" not in lowered
    assert "earned this week" not in lowered


def test_loses_points_while_rank_unchanged() -> None:
    report = _report(
        [
            _player(1, "Jannik Sinner", points=13450, previous_rank=1, previous_points=13450),
            _player(3, "Alexander Zverev", points=8090, previous_rank=3, previous_points=8410),
        ]
    )
    script = _script(report)
    lowered = script.lower()

    assert points_delta(report.players[1]) == -320
    assert "alexander zverev" in lowered
    assert "320" in script
    assert "points earned" not in lowered


def test_rank_and_points_both_increase() -> None:
    report = _report(
        [
            _player(1, "Jannik Sinner", points=13450, previous_rank=1, previous_points=13450),
            _player(
                6,
                "Ben Shelton",
                points=4655,
                movement=Movement.UP,
                previous_rank=8,
                previous_points=4155,
            ),
        ]
    )
    script = _script(report)
    lowered = script.lower()

    assert places_delta(report.players[1]) == 2
    assert points_delta(report.players[1]) == 500
    assert "ben shelton" in lowered
    assert "500" in script
    assert "number 6" in lowered
    assert "points earned" not in lowered


def test_rank_improves_while_point_total_decreases() -> None:
    report = _report(
        [
            _player(1, "Jannik Sinner", points=13450, previous_rank=1, previous_points=13450),
            _player(
                4,
                "Taylor Fritz",
                points=4500,
                movement=Movement.UP,
                previous_rank=5,
                previous_points=4800,
            ),
        ]
    )
    script = _script(report)
    lowered = script.lower()

    assert places_delta(report.players[1]) == 1
    assert points_delta(report.players[1]) == -300
    assert "taylor fritz" in lowered
    assert "300" in script
    assert any(word in lowered for word in ("down", "losing", "drop"))
    assert "points earned" not in lowered


def test_rank_falls_while_point_total_increases() -> None:
    report = _report(
        [
            _player(1, "Jannik Sinner", points=13450, previous_rank=1, previous_points=13450),
            _player(
                8,
                "Alex de Minaur",
                points=3485,
                movement=Movement.DOWN,
                previous_rank=7,
                previous_points=3300,
            ),
        ]
    )
    script = _script(report)
    lowered = script.lower()

    assert places_delta(report.players[1]) == -1
    assert points_delta(report.players[1]) == 185
    assert "alex de minaur" in lowered
    assert "185" in script
    assert any(word in lowered for word in ("up ", "gaining", "increase"))
    assert "points earned" not in lowered


def test_points_unchanged_from_last_week() -> None:
    report = _report(
        [
            _player(1, "Jannik Sinner", points=13450, previous_rank=1, previous_points=13450),
            _player(2, "Carlos Alcaraz", points=10450, previous_rank=2, previous_points=10450),
        ]
    )
    script = _script(report)
    lowered = script.lower()

    assert points_delta(report.players[0]) == 0
    assert "unchanged from last week" in lowered
    assert "jannik sinner" in lowered
    assert "points earned" not in lowered


def test_previous_points_unavailable_omits_week_to_week_change() -> None:
    report = _report(
        [
            _player(1, "Jannik Sinner", points=13450, previous_rank=1, previous_points=None),
            _player(2, "Carlos Alcaraz", points=8160, previous_rank=2, previous_points=None),
        ]
    )
    script = _script(report)
    lowered = script.lower()

    assert points_delta(report.players[1]) is None
    assert "since last week" not in lowered
    assert "from last week" not in lowered
    assert "from the previous rankings" not in lowered
    assert "8,160" in script


def test_opening_notes_point_shifts_when_rankings_are_unchanged() -> None:
    players = [
        _player(1, "Jannik Sinner", points=13450, previous_rank=1, previous_points=13450),
        _player(2, "Carlos Alcaraz", points=8160, previous_rank=2, previous_points=7730),
        _player(3, "Alexander Zverev", points=8090, previous_rank=3, previous_points=8410),
    ]
    report = _report(players)
    summary = summarize_weekly_movement(report)
    script = _script(report)
    lowered = script.lower()

    assert summary.is_baseline is False
    assert summary.biggest_up is None
    assert len(summary.meaningful_point_changes) == 2
    assert "positions are unchanged" in lowered or "same ranking" in lowered or "no change in the top" in lowered
    assert "quiet week" not in lowered
    assert "remain exactly where they were" not in lowered
    assert "430" in script
    assert "320" in script
    assert "points earned" not in lowered


def test_weekly_narration_never_calls_delta_points_earned() -> None:
    report = _report(
        [
            _player(1, "Jannik Sinner", points=13450, previous_rank=1, previous_points=13000),
            _player(
                6,
                "Ben Shelton",
                points=3670,
                movement=Movement.UP,
                previous_rank=10,
                previous_points=3170,
            ),
            _player(
                8,
                "Alex de Minaur",
                points=3485,
                movement=Movement.DOWN,
                previous_rank=7,
                previous_points=3300,
            ),
        ]
    )
    script = _script(report).lower()

    assert "points earned" not in script
    assert "earned this week" not in script
    assert "earned at" not in script
    assert "because he won" not in script
    assert "because of a tournament" not in script

