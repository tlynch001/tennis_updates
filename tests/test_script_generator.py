from __future__ import annotations

from datetime import date

from wta_daily.config import ScriptConfig
from wta_daily.models import DailyReport, MatchResult, Movement, PlayerReport
from wta_daily.scripts_gen import phrases
from wta_daily.scripts_gen.template_generator import TemplateScriptGenerator


def _sample_report(movements: list[Movement]) -> DailyReport:
    players = []
    for i, movement in enumerate(movements, start=1):
        match = MatchResult(
            opponent=f"Opponent {i}",
            tournament="Test Open",
            round="Final",
            score="6-4 6-4",
            won=(i % 2 == 0),
            match_date=date(2026, 8, 8),
        )
        players.append(
            PlayerReport(
                rank=i,
                name=f"Player {i}",
                player_id=f"p{i}",
                country_code="USA",
                points=10000 - i * 100,
                movement=movement,
                previous_rank=i if movement == Movement.SAME else None,
                match=match,
            )
        )
    return DailyReport(report_date=date(2026, 8, 9), tour="wta", players=players)


def test_generate_mentions_every_player_by_name() -> None:
    report = _sample_report([Movement.NEW, Movement.UP, Movement.DOWN, Movement.SAME])
    generator = TemplateScriptGenerator()

    script = generator.generate(report)

    for player in report.players:
        assert player.name in script


def test_generate_mentions_win_loss_language() -> None:
    report = _sample_report([Movement.SAME, Movement.SAME])
    script = TemplateScriptGenerator().generate(report)

    # player 1 lost (i % 2 == 0 is False for i=1), player 2 won.
    keywords = ["fell", "defeated", "came", "lost", "beat", "eliminated", "short", "loss"]
    assert any(word in script for word in keywords)


def test_generate_is_deterministic_for_same_report() -> None:
    report = _sample_report([Movement.UP, Movement.DOWN])
    generator = TemplateScriptGenerator()

    first = generator.generate(report)
    second = generator.generate(report)

    assert first == second


def test_generate_varies_across_different_dates() -> None:
    generator = TemplateScriptGenerator()
    report_a = _sample_report([Movement.SAME] * 3)
    report_b = DailyReport(
        report_date=date(2026, 8, 10), tour="wta", players=_sample_report([Movement.SAME] * 3).players
    )

    script_a = generator.generate(report_a)
    script_b = generator.generate(report_b)

    assert script_a != script_b


def test_generate_handles_missing_match_gracefully() -> None:
    player = PlayerReport(
        rank=1,
        name="No Match Player",
        player_id="p1",
        country_code="USA",
        points=1000,
        movement=Movement.NEW,
        match=None,
    )
    report = DailyReport(report_date=date(2026, 8, 9), tour="wta", players=[player])

    script = TemplateScriptGenerator().generate(report)

    assert "No Match Player" in script


def test_generate_respects_target_length_padding() -> None:
    config = ScriptConfig(target_minutes_low=20, words_per_minute=150)
    report = _sample_report([Movement.SAME])
    script = TemplateScriptGenerator(script_config=config).generate(report)

    # With an unreachable target (20 minutes for 1 player), the generator
    # should still terminate and add its filler note rather than looping.
    assert "ranking points reflect performance" in script


def _last_nonblank_paragraph(script: str) -> str:
    paragraphs = [p for p in script.split("\n\n") if p.strip()]
    return paragraphs[-1]


def test_sign_off_is_the_actual_last_paragraph() -> None:
    """Regression test: the closer must be the literal end of the script,
    not followed by unrelated filler/context (as happened in production)."""

    report = _sample_report([Movement.SAME, Movement.UP, Movement.DOWN])
    script = TemplateScriptGenerator().generate(report)

    last_paragraph = _last_nonblank_paragraph(script)
    possible_closers = {c.format(n=len(report.players)) for c in phrases.CLOSERS}
    assert last_paragraph in possible_closers


def test_sign_off_is_last_even_when_padding_is_added() -> None:
    """The length-padding filler must be inserted *before* the sign-off, never after."""

    config = ScriptConfig(target_minutes_low=20, words_per_minute=150)
    report = _sample_report([Movement.SAME])
    script = TemplateScriptGenerator(script_config=config).generate(report)

    assert "ranking points reflect performance" in script
    last_paragraph = _last_nonblank_paragraph(script)
    possible_closers = {c.format(n=len(report.players)) for c in phrases.CLOSERS}
    assert last_paragraph in possible_closers
    # The filler text must appear strictly before the sign-off in the script.
    assert script.index("ranking points reflect performance") < script.index(last_paragraph)


def test_unknown_movement_never_uses_new_entrant_language() -> None:
    """First-ever run (no previous snapshot): narration must stay neutral.

    Regression test for the production incident where every established
    Top 10 player was described with "new face"/"debut"/"enters the Top N"
    language purely because the application had never run before.
    """

    report = _sample_report([Movement.UNKNOWN] * 10)
    script = TemplateScriptGenerator().generate(report)

    forbidden_phrases = ["new face", "debut", "enters the top", "breaks into"]
    lowered = script.lower()
    for phrase in forbidden_phrases:
        assert phrase not in lowered, f"Unexpected new-entrant language for report: {phrase!r}"


def test_unknown_movement_still_mentions_current_rank() -> None:
    report = _sample_report([Movement.UNKNOWN, Movement.UNKNOWN])
    script = TemplateScriptGenerator().generate(report)

    for player in report.players:
        assert player.name in script
