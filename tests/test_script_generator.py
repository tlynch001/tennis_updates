from __future__ import annotations

from datetime import date, timedelta

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
    # The exact wording varies (see phrases.FIFTY_TWO_WEEK_NOTES), so check
    # for the substring every variant shares.
    assert "fifty-two weeks" in script


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

    assert "fifty-two weeks" in script
    last_paragraph = _last_nonblank_paragraph(script)
    possible_closers = {c.format(n=len(report.players)) for c in phrases.CLOSERS}
    assert last_paragraph in possible_closers
    # The filler text must appear strictly before the sign-off in the script.
    assert script.index("fifty-two weeks") < script.index(last_paragraph)


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


# --- Narration polish: selective point-gap commentary -----------------------


def _report_with_points(points_list: list[int], report_date: date) -> DailyReport:
    players = [
        PlayerReport(
            rank=i,
            name=f"Player {i}",
            player_id=f"p{i}",
            country_code="USA",
            points=points,
            movement=Movement.SAME,
            previous_rank=i,
        )
        for i, points in enumerate(points_list, start=1)
    ]
    return DailyReport(report_date=report_date, tour="wta", players=players)


def test_large_point_gaps_are_never_mentioned() -> None:
    """Gaps like 354/275 points (real production examples) are not
    'genuinely noteworthy' - they must never be narrated."""

    points = [10000, 9646, 9371]  # consecutive gaps: 354, 275
    start = date(2026, 8, 1)
    for offset in range(30):
        report = _report_with_points(points, start + timedelta(days=offset))
        script = TemplateScriptGenerator().generate(report)
        assert "354 points" not in script
        assert "275 points" not in script


def test_small_point_gaps_are_mentioned_sometimes_but_not_every_time() -> None:
    """Genuinely tight gaps (32/96 points, also real production examples)
    are an occasional storyline, not a guaranteed mention every single
    time the data qualifies - see _POINTS_GAP_MENTION_PROBABILITY."""

    points = [10000, 9968, 9872]  # consecutive gaps: 32, 96
    start = date(2026, 8, 1)
    mentioned = 0
    total = 50
    for offset in range(total):
        report = _report_with_points(points, start + timedelta(days=offset))
        script = TemplateScriptGenerator().generate(report)
        if "32 points" in script or "96 points" in script:
            mentioned += 1

    assert 0 < mentioned < total


def test_point_gap_mention_never_exceeds_the_noteworthy_threshold() -> None:
    """Whenever a gap sentence does appear, it must always be for a gap at
    or below the noteworthy threshold - never one of the large gaps."""

    points = [10000, 9646, 9614]  # gaps: 354 (skip), 32 (candidate)
    start = date(2026, 8, 1)
    for offset in range(40):
        report = _report_with_points(points, start + timedelta(days=offset))
        script = TemplateScriptGenerator().generate(report)
        assert "354 points" not in script


# --- Narration polish: next-official-ranking acknowledgment -----------------


def test_win_sometimes_acknowledges_the_next_official_ranking_but_never_projects_one() -> None:
    report = _sample_report([Movement.SAME, Movement.SAME])  # player 2 (i=2) wins
    start = date(2026, 8, 1)
    mentioned = 0
    total = 60
    for offset in range(total):
        dated_report = DailyReport(
            report_date=start + timedelta(days=offset), tour="wta", players=report.players
        )
        script = TemplateScriptGenerator().generate(dated_report)
        lowered = script.lower()
        if "next official" in lowered:
            mentioned += 1
        # Never a specific projected rank/points claim.
        assert "projected" not in lowered
        assert "moves her to number" not in lowered
        assert "this moves her" not in lowered

    assert 0 < mentioned < total


def test_next_official_ranking_note_never_implies_the_current_ranking_changed() -> None:
    """The note may only ever be about the *next* publication - never
    phrased as if today's official ranking already reflects the win."""

    for phrase in phrases.NEXT_RANKING_NOTES:
        lowered = phrase.lower()
        assert "next official" in lowered
        assert "moves her" not in lowered
        assert "now ranked" not in lowered


# --- Narration polish: score formatting for narration ------------------------


def test_match_score_gets_a_space_after_the_comma_in_narration() -> None:
    match = MatchResult(
        opponent="Opponent",
        tournament="Test Open",
        round="Final",
        score="6-4,7-6(2)",
        won=True,
        match_date=date(2026, 8, 8),
    )
    player = PlayerReport(
        rank=1,
        name="Player One",
        player_id="p1",
        country_code="USA",
        points=1000,
        movement=Movement.SAME,
        previous_rank=1,
        match=match,
    )
    report = DailyReport(report_date=date(2026, 8, 9), tour="wta", players=[player])

    script = TemplateScriptGenerator().generate(report)

    assert "6-4, 7-6(2)" in script
    assert "6-4,7-6(2)" not in script


# --- Narration polish: variable, PR-#10-consistent 52-week filler -----------


def test_fifty_two_week_filler_never_implies_automatic_ranking_updates() -> None:
    config = ScriptConfig(target_minutes_low=20, words_per_minute=150)
    report = _sample_report([Movement.SAME])

    script = TemplateScriptGenerator(script_config=config).generate(report)

    assert "fifty-two weeks" in script
    # The old wording implied a result itself reshuffles the rankings.
    assert "can shuffle several places" not in script.lower()
    assert "once a big tournament wraps up" not in script.lower()


def test_fifty_two_week_filler_wording_varies_across_days() -> None:
    config = ScriptConfig(target_minutes_low=20, words_per_minute=150)
    report = _sample_report([Movement.SAME])
    start = date(2026, 8, 1)

    variants_seen = set()
    for offset in range(20):
        dated_report = DailyReport(
            report_date=start + timedelta(days=offset), tour="wta", players=report.players
        )
        script = TemplateScriptGenerator(script_config=config).generate(dated_report)
        for note in phrases.FIFTY_TWO_WEEK_NOTES:
            if note in script:
                variants_seen.add(note)

    assert len(variants_seen) >= 2


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


# --- Tournament-elimination narration context --------------------------


def test_eliminated_player_gets_elimination_context_in_her_paragraph() -> None:
    """No match reported for the target date (a 'previous reporting day'
    elimination, first noticed today) - the declarative, detailed pool
    is expected, including the eliminator's name."""

    report = _sample_report([Movement.SAME])
    report.players[0].match = None
    report.players[0].tournament_status = TournamentRunStatus(
        state=TournamentState.ELIMINATED,
        tournament="Cincinnati",
        round_reached="R16",
        round_label="the Round of 16",
        eliminated_by="Iga Swiatek",
        points_earned=120,
        is_new_development=True,
    )

    script = TemplateScriptGenerator().generate(report)

    assert "Iga Swiatek" in script
    assert "Round of 16" in script


def test_champion_player_gets_title_context_in_her_paragraph() -> None:
    report = _sample_report([Movement.SAME])
    report.players[0].tournament_status = TournamentRunStatus(
        state=TournamentState.CHAMPION,
        tournament="Cincinnati",
        round_reached="W",
        round_label="the title",
        points_earned=1000,
        is_new_development=True,
    )

    script = TemplateScriptGenerator().generate(report)

    assert "champion" in script.lower() or "title" in script.lower()


def test_active_tournament_status_adds_nothing_to_the_script() -> None:
    with_status = _sample_report([Movement.SAME])
    with_status.players[0].tournament_status = TournamentRunStatus(
        state=TournamentState.ACTIVE, tournament="Cincinnati"
    )
    without_status = _sample_report([Movement.SAME])

    script_with = TemplateScriptGenerator().generate(with_status)
    script_without = TemplateScriptGenerator().generate(without_status)

    assert script_with == script_without


def test_no_tournament_status_produces_the_same_script_as_before_this_feature() -> None:
    """Regression guard: a report where the match provider has no
    tournament-draw visibility at all (tournament_status left as the
    dataclass default, None) must never mention elimination/championship
    language it has no facts for."""

    report = _sample_report([Movement.UP, Movement.DOWN, Movement.SAME])
    for player in report.players:
        assert player.tournament_status is None  # the default

    script = TemplateScriptGenerator().generate(report)

    assert "eliminated by" not in script
    assert "champion" not in script.lower()


def test_eliminated_player_never_gets_generic_no_match_filler() -> None:
    """Once we know a player's tournament is over, saying she also 'had
    no match to report' reads as an odd non-sequitur - the elimination
    context should stand alone."""

    report = _sample_report([Movement.SAME])
    report.players[0].match = None
    report.players[0].tournament_status = TournamentRunStatus(
        state=TournamentState.ELIMINATED,
        tournament="Cincinnati",
        round_reached="R16",
        round_label="the Round of 16",
        eliminated_by="Iga Swiatek",
        points_earned=120,
        is_new_development=True,
    )

    for seed_offset in range(10):
        report.report_date = date(2026, 8, 9 + seed_offset)
        script = TemplateScriptGenerator().generate(report)
        assert "no match to report" not in script.lower()
        for phrase in phrases.NO_MATCH:
            assert phrase not in script


def test_eliminated_player_never_gets_match_error_filler() -> None:
    report = _sample_report([Movement.SAME])
    report.players[0].match = None
    report.players[0].match_error = "simulated outage"
    report.players[0].tournament_status = TournamentRunStatus(
        state=TournamentState.ELIMINATED,
        round_reached="R16",
        round_label="the Round of 16",
        eliminated_by="Iga Swiatek",
        is_new_development=True,
    )

    script = TemplateScriptGenerator().generate(report)

    assert "couldn't be confirmed" not in script


def test_champion_player_never_gets_generic_no_match_filler() -> None:
    report = _sample_report([Movement.SAME])
    report.players[0].match = None
    report.players[0].tournament_status = TournamentRunStatus(
        state=TournamentState.CHAMPION,
        round_reached="W",
        round_label="the title",
        points_earned=1000,
        is_new_development=True,
    )

    script = TemplateScriptGenerator().generate(report)

    assert "no match to report" not in script.lower()


def test_a_real_match_result_is_never_suppressed_even_when_eliminated() -> None:
    """The suppression only ever targets generic 'nothing to say either
    way' filler - a genuine win/loss result for the target date is a
    real fact and must still appear."""

    report = _sample_report([Movement.SAME])
    report.players[0].tournament_status = TournamentRunStatus(
        state=TournamentState.ELIMINATED,
        round_reached="R16",
        round_label="the Round of 16",
        eliminated_by="Iga Swiatek",
        is_new_development=True,
    )
    assert report.players[0].match is not None  # sanity check on the fixture helper

    script = TemplateScriptGenerator().generate(report)

    assert report.players[0].match.opponent in script


def test_active_status_does_not_suppress_generic_no_match_filler() -> None:
    """Suppression is specific to a *concluded* run (eliminated/champion) -
    an ACTIVE player with no match that day still gets the normal filler."""

    report = _sample_report([Movement.SAME])
    report.players[0].match = None
    report.players[0].tournament_status = TournamentRunStatus(
        state=TournamentState.ACTIVE, tournament="Cincinnati"
    )

    found = False
    for seed_offset in range(10):
        report.report_date = date(2026, 8, 9 + seed_offset)
        script = TemplateScriptGenerator().generate(report)
        if any(phrase in script for phrase in phrases.NO_MATCH):
            found = True
            break
    assert found


# --- New elimination (this match) vs. prior-day elimination ---------------


def test_a_player_eliminated_by_todays_match_gets_causal_immediate_language() -> None:
    """Regression: a Top N player eliminated by the match just narrated
    must never get 'still over'/'remains out'/'eliminated back in'
    language - see wta_daily.scripts_gen.tournament_status_narration."""

    report = _sample_report([Movement.SAME])
    player = report.players[0]
    player.match = MatchResult(
        opponent="Marta Kostyuk",
        tournament="Cincinnati",
        round="Round of 16",
        score="6-4,6-3",
        won=False,
        match_date=date(2026, 8, 19),
    )
    player.tournament_status = TournamentRunStatus(
        state=TournamentState.ELIMINATED,
        tournament="Cincinnati",
        round_reached="R16",
        round_label="the Round of 16",
        eliminated_by="Marta Kostyuk",
        points_earned=120,
        is_new_development=True,
    )

    script = TemplateScriptGenerator().generate(report)
    lowered = script.lower()

    for forbidden in ("still over", "remains out", "eliminated back in"):
        assert forbidden not in lowered
    assert "Round of 16" in script


def test_a_player_eliminated_on_an_earlier_day_can_use_prior_status_language() -> None:
    """No match reported for the target date (the elimination happened
    on an earlier reporting day) - the declarative 'was eliminated
    by...' framing is appropriate here."""

    report = _sample_report([Movement.SAME])
    player = report.players[0]
    player.match = None
    player.tournament_status = TournamentRunStatus(
        state=TournamentState.ELIMINATED,
        tournament="Cincinnati",
        round_reached="R16",
        round_label="the Round of 16",
        eliminated_by="Marta Kostyuk",
        points_earned=120,
        is_new_development=True,
    )

    script = TemplateScriptGenerator().generate(report)

    assert "Marta Kostyuk" in script


def test_a_previously_reported_elimination_uses_completed_historical_wording() -> None:
    """Regression: 'still over'/'remains out of the draw' must never
    appear once an elimination has already been reported before -
    elimination is a completed event, never described with
    ongoing-state language."""

    report = _sample_report([Movement.SAME])
    player = report.players[0]
    player.match = None
    player.tournament_status = TournamentRunStatus(
        state=TournamentState.ELIMINATED,
        tournament="Cincinnati",
        round_reached="R16",
        round_label="the Round of 16",
        is_new_development=False,
    )

    script = TemplateScriptGenerator().generate(report)
    lowered = script.lower()

    for forbidden in ("still over", "remains out of the draw", "eliminated back in", "continues to be"):
        assert forbidden not in lowered
    assert "ended" in lowered or "came to an end" in lowered


def test_round_omitted_gracefully_when_it_cannot_be_normalized() -> None:
    """A match whose round couldn't be confidently normalized (see
    wta_daily.plugins.matches.wta_official's round-normalization
    docstring) must never surface a raw/invalid round code or a literal
    'None' - the sentence stays grammatically correct with the round
    simply omitted."""

    report = _sample_report([Movement.SAME])
    player = report.players[0]
    player.match = MatchResult(
        opponent="Amanda Anisimova",
        tournament="Cincinnati",
        round=None,
        score="6-4,2-6,7-6(4)",
        won=True,
        match_date=date(2026, 8, 19),
    )

    script = TemplateScriptGenerator().generate(report)

    assert "None" not in script
    assert "Round Q" not in script
    assert "Main Draw Round" not in script
    assert "Amanda Anisimova" in script
    assert "Cincinnati" in script
