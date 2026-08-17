from __future__ import annotations

from datetime import date, timedelta

from wta_daily.config import ScriptConfig
from wta_daily.models import DailyReport, FeaturedPlayerReport, MatchResult, Movement, PlayerReport
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


_CONTINUATION_PHRASES = [
    "elsewhere",
    "meanwhile",
    "next up",
    "turning to",
    "now to",
    "moving to",
    "also,",
    "also today",
]


def _first_player_paragraph(script: str, player_name: str) -> str:
    paragraphs = [p for p in script.split("\n\n") if p.strip()]
    return next(p for p in paragraphs if player_name in p)


def test_first_player_story_never_uses_a_continuation_transition() -> None:
    """Regression test for the production incident where the very first
    Top N story (right after the introduction) began with 'Elsewhere in
    the Top 10' - there is nothing for it to be 'elsewhere' from yet."""

    report = _sample_report([Movement.SAME, Movement.UP, Movement.DOWN, Movement.NEW])
    first_player = report.players[0]

    for day in range(1, 29):  # many simulated dates, to rule out lucky rng draws
        dated_report = DailyReport(report_date=date(2026, 8, day), tour="wta", players=report.players)
        script = TemplateScriptGenerator().generate(dated_report)
        first_paragraph = _first_player_paragraph(script, first_player.name)
        lowered = first_paragraph.lower()

        for phrase in _CONTINUATION_PHRASES:
            assert phrase not in lowered, (
                f"First player story used continuation phrase {phrase!r} on 2026-08-{day:02d}: "
                f"{first_paragraph!r}"
            )


def test_first_player_story_begins_directly_with_her_name() -> None:
    """The first story should read naturally on its own, starting right
    with the player's name - never manufactured filler like 'Starting at
    number one...' either."""

    report = _sample_report([Movement.SAME])

    for day in range(1, 15):
        dated_report = DailyReport(report_date=date(2026, 8, day), tour="wta", players=report.players)
        script = TemplateScriptGenerator().generate(dated_report)
        first_paragraph = _first_player_paragraph(script, report.players[0].name)

        assert first_paragraph.startswith(report.players[0].name)


def test_later_player_stories_can_still_use_continuation_transitions() -> None:
    """The fix must be positional, not a blanket removal of the phrase
    pool - later stories should still be able to say 'Elsewhere in the Top
    N', 'Meanwhile', etc. across enough simulated days."""

    report = _sample_report([Movement.SAME, Movement.UP, Movement.DOWN, Movement.NEW])
    second_player = report.players[1]

    seen_continuation_phrase = False
    start = date(2026, 8, 1)
    for offset in range(60):
        dated_report = DailyReport(
            report_date=start + timedelta(days=offset), tour="wta", players=report.players
        )
        script = TemplateScriptGenerator().generate(dated_report)
        second_paragraph = _first_player_paragraph(script, second_player.name)
        lowered = second_paragraph.lower()
        if any(phrase in lowered for phrase in _CONTINUATION_PHRASES):
            seen_continuation_phrase = True
            break

    assert seen_continuation_phrase, (
        "Expected at least one later-story continuation transition across many simulated days"
    )


def test_first_story_connector_pool_never_presupposes_a_previous_story() -> None:
    """Direct check on the phrase pools themselves: FIRST_STORY_CONNECTORS
    must never contain wording that implies an earlier story, while the
    regular CONNECTORS pool (used from the second story onward) is
    expected to still contain that variety."""

    for connector in phrases.FIRST_STORY_CONNECTORS:
        lowered = connector.lower()
        for phrase in _CONTINUATION_PHRASES:
            assert phrase not in lowered

    # Sanity check the fix didn't accidentally remove variety from the
    # pool used for every subsequent story.
    combined_later_pool = " ".join(phrases.CONNECTORS).lower()
    assert "elsewhere" in combined_later_pool
    assert "meanwhile" in combined_later_pool


def test_no_featured_player_produces_no_extra_content() -> None:
    """The default (feature disabled/unset) must behave exactly as before
    this feature existed - no featured-player wording anywhere."""

    report = _sample_report([Movement.SAME, Movement.UP])
    script = TemplateScriptGenerator().generate(report)

    assert "Emma Navarro" not in script
    assert "America's favorite" not in script


def test_featured_player_segment_appears_after_top_n_and_before_sign_off() -> None:
    report = _sample_report([Movement.SAME, Movement.UP])
    report.featured_player = FeaturedPlayerReport(
        name="Emma Navarro",
        player_id="325410",
        tagline="america_favorite",
        rank=28,
        points=1669,
        movement=Movement.SAME,
        previous_rank=28,
    )

    script = TemplateScriptGenerator().generate(report)

    assert "Emma Navarro" in script
    paragraphs = [p for p in script.split("\n\n") if p.strip()]
    emma_index = next(i for i, p in enumerate(paragraphs) if "Emma Navarro" in p)
    closer_index = len(paragraphs) - 1

    # The featured segment is its own paragraph, strictly after every Top N
    # player paragraph and strictly before the final sign-off.
    assert emma_index > 0
    assert emma_index < closer_index
    for player in report.players:
        player_paragraph_index = next(i for i, p in enumerate(paragraphs) if player.name in p)
        assert player_paragraph_index < emma_index

    possible_closers = {c.format(n=len(report.players)) for c in phrases.CLOSERS}
    assert paragraphs[closer_index] in possible_closers


def test_featured_player_with_unavailable_rank_produces_no_segment() -> None:
    """If her rank couldn't be determined this run, the script must not
    mention her at all rather than saying something with no real numbers."""

    report = _sample_report([Movement.SAME])
    report.featured_player = FeaturedPlayerReport(
        name="Emma Navarro",
        player_id="325410",
        tagline="america_favorite",
        rank_error="network timeout",
    )

    script = TemplateScriptGenerator().generate(report)

    assert "Emma Navarro" not in script
