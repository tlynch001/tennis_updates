"""Unit tests for :mod:`wta_daily.scripts_gen.featured_player`.

Exercises the narration-building logic in isolation from the rest of the
script generator: rank-tier framing (pursuit / arrived / world No. 1),
movement flavor, match-result integration, and the variation/repetition
requirements from the feature brief.
"""

from __future__ import annotations

import random
import re
from datetime import date

from wta_daily.models import (
    FeaturedPlayerReport,
    MatchResult,
    Movement,
    TournamentRunStatus,
    TournamentState,
)
from wta_daily.scripts_gen import featured_player_phrases as fp
from wta_daily.scripts_gen.featured_player import build_segment

TOP_N = 10


def _match(*, won: bool, opponent: str = "Some Opponent", score: str = "6-4 6-3") -> MatchResult:
    return MatchResult(
        opponent=opponent,
        tournament="Cincinnati",
        round="Round of 32",
        score=score,
        won=won,
        match_date=date(2026, 8, 15),
    )


def _featured(**overrides: object) -> FeaturedPlayerReport:
    defaults: dict[str, object] = {
        "name": "Emma Navarro",
        "player_id": "325410",
        "tagline": "america_favorite",
        "country_code": "USA",
        "rank": 28,
        "points": 1669,
        "movement": Movement.SAME,
        "previous_rank": 28,
        "match": None,
        "match_error": None,
    }
    defaults.update(overrides)
    return FeaturedPlayerReport(**defaults)  # type: ignore[arg-type]


def _rng(seed: str) -> random.Random:
    return random.Random(seed)


def test_returns_none_when_rank_is_unavailable() -> None:
    """Never build a segment around a number we don't have."""

    featured = _featured(rank=None, rank_error="network timeout")

    assert build_segment(featured, top_n=TOP_N, rng=_rng("seed")) is None


def test_outside_top_n_uses_pursuit_framing_not_arrived_language() -> None:
    featured = _featured(rank=28)

    segment = build_segment(featured, top_n=TOP_N, rng=_rng("seed-a"))

    assert segment is not None
    assert "Emma Navarro" in segment
    assert "28" in segment
    lowered = segment.lower()
    for forbidden in ("officially arrived", "has officially arrived", "welcomes a name"):
        assert forbidden not in lowered


def test_never_makes_a_mathematically_specific_pursuit_claim() -> None:
    """Regression test: the brief explicitly forbids claims like 'only two
    wins away' unless the data actually supports them - this codebase never
    computes or asserts such a claim, so no phrase pool should either."""

    seen: set[str] = set()
    for i in range(60):
        featured = _featured(rank=28)
        segment = build_segment(featured, top_n=TOP_N, rng=_rng(f"seed-{i}"))
        assert segment is not None
        seen.add(segment)

    combined = " ".join(seen).lower()
    for forbidden in ("wins away", "one win away", "two wins away", "just one win"):
        assert forbidden not in combined


def test_inside_top_n_uses_arrived_framing_not_pursuit_language() -> None:
    featured = _featured(rank=8, previous_rank=11, movement=Movement.NEW)

    segment = build_segment(featured, top_n=TOP_N, rng=_rng("seed-b"))

    assert segment is not None
    lowered = segment.lower()
    for forbidden in ("climb back toward", "keeping a seat warm", "still lurking"):
        assert forbidden not in lowered


def test_number_one_drops_the_official_vs_unofficial_distinction() -> None:
    featured = _featured(rank=1, previous_rank=2, movement=Movement.UP)

    segment = build_segment(featured, top_n=TOP_N, rng=_rng("seed-c"))

    assert segment is not None
    assert "number one" in segment.lower()
    # The "#1 in our hearts" contrast no longer makes sense once she's
    # genuinely No. 1 - it must never appear for this rank.
    assert "unofficially" not in segment.lower()


def test_number_one_never_gets_the_hearts_joke_even_across_many_seeds() -> None:
    for i in range(40):
        featured = _featured(rank=1, previous_rank=1, movement=Movement.SAME)
        segment = build_segment(featured, top_n=TOP_N, rng=_rng(f"hearts-check-{i}"))
        assert segment is not None
        assert "unofficially" not in segment.lower()


def test_win_mentions_real_opponent_score_and_tournament() -> None:
    featured = _featured(rank=28, match=_match(won=True, opponent="Iga Swiatek", score="7-6 6-4"))

    segment = build_segment(featured, top_n=TOP_N, rng=_rng("seed-win"))

    assert segment is not None
    assert "Iga Swiatek" in segment
    assert "7-6 6-4" in segment
    assert "Cincinnati" in segment


def test_loss_states_the_real_result_and_does_not_pretend_she_won() -> None:
    featured = _featured(rank=28, match=_match(won=False, opponent="Coco Gauff", score="4-6 3-6"))

    segment = build_segment(featured, top_n=TOP_N, rng=_rng("seed-loss"))

    assert segment is not None
    assert "Coco Gauff" in segment
    assert "4-6 3-6" in segment


def test_loss_never_claims_a_win() -> None:
    for i in range(30):
        featured = _featured(rank=28, match=_match(won=False, opponent="Someone", score="1-6 2-6"))
        segment = build_segment(featured, top_n=TOP_N, rng=_rng(f"loss-{i}"))
        assert segment is not None
        # Every win-phrase template mentions "getting past"/"came through"/
        # "took care of"/"beat" - none of those verbs should appear when
        # she actually lost.
        lowered = segment.lower()
        for win_verb in ("getting past", "came through against", "took care of", " beat "):
            assert win_verb not in lowered


def test_no_match_does_not_invent_a_result() -> None:
    featured = _featured(rank=28, match=None)

    segment = build_segment(featured, top_n=TOP_N, rng=_rng("seed-no-match"))

    assert segment is not None
    lowered = segment.lower()
    assert "day off" in lowered or "no match" in lowered or "quiet day" in lowered or "rest day" in lowered
    assert "cincinnati" not in lowered  # no tournament fabricated without a real match


def test_match_error_does_not_guess_a_result() -> None:
    featured = _featured(rank=28, match=None, match_error="all match sources failed")

    segment = build_segment(featured, top_n=TOP_N, rng=_rng("seed-match-error"))

    assert segment is not None
    lowered = segment.lower()
    assert "confirmed" in lowered
    assert "cincinnati" not in lowered


def test_movement_up_and_down_are_reflected_honestly() -> None:
    up_segment = build_segment(_featured(rank=28, movement=Movement.UP), top_n=TOP_N, rng=_rng("up"))
    down_segment = build_segment(
        _featured(rank=28, movement=Movement.DOWN), top_n=TOP_N, rng=_rng("down")
    )

    assert up_segment is not None and down_segment is not None
    up_words = ("climbing", "on the move", "picking up ground", "trending", "making up ground")
    down_words = ("step back", "for the moment", "down slightly", "easing back")
    assert any(w in up_segment.lower() for w in up_words)
    assert any(w in down_segment.lower() for w in down_words)


def test_unknown_movement_never_uses_new_entrant_language() -> None:
    """Same safety rule as the official Top N: a first-ever run (no prior
    snapshot) must not claim she's 'new' or 'freshly tracked'."""

    featured = _featured(rank=28, movement=Movement.UNKNOWN, previous_rank=None)

    segment = build_segment(featured, top_n=TOP_N, rng=_rng("seed-unknown"))

    assert segment is not None
    lowered = segment.lower()
    for forbidden in ("newly back", "freshly tracked", "back on the board"):
        assert forbidden not in lowered


def test_segment_appears_in_1_to_3_sentences() -> None:
    """Tone requirement: this is a quick inside joke, not a comedy routine."""

    featured = _featured(rank=28, match=_match(won=True))
    segment = build_segment(featured, top_n=TOP_N, rng=_rng("seed-length"))

    assert segment is not None
    sentence_count = segment.count(". ") + 1
    assert 1 <= sentence_count <= 4  # small tolerance for embedded abbreviations/scores


def test_unrecognized_tagline_still_produces_a_segment() -> None:
    """A future featured player with an unrecognized tagline should still
    get a (default) segment rather than silently producing nothing."""

    featured = _featured(rank=28, tagline="totally_unknown_tagline")

    segment = build_segment(featured, top_n=TOP_N, rng=_rng("seed-unknown-tagline"))

    assert segment is not None


def test_produces_substantial_variation_across_many_days() -> None:
    """The core anti-repetition requirement: running the same underlying
    data through many different day-seeds must not produce one canned
    paragraph over and over."""

    featured = _featured(rank=28, movement=Movement.SAME, match=_match(won=True))
    outputs = {
        build_segment(featured, top_n=TOP_N, rng=_rng(f"2026-08-{day:02d}")) for day in range(1, 29)
    }

    # 28 distinct day-seeds should produce well more than a couple of
    # unique paragraphs if the phrase pools are doing their job.
    assert len(outputs) >= 15


# --- Narration polish: no repeated joke phrase within one segment ----------


def test_favorite_label_never_repeats_within_one_loss_segment() -> None:
    """Regression test for a real production script that said 'the
    reigning champion of this show's affections' twice in three
    sentences: a loss segment draws up to three AMERICA_FAVORITE_LABELS
    phrases (intro, the loss clause, the supportive follow-up clause) -
    none of them may repeat verbatim within the same segment."""

    featured = _featured(rank=28, match=_match(won=False, opponent="Someone", score="7-5 6-2"))
    for i in range(80):
        segment = build_segment(featured, top_n=TOP_N, rng=_rng(f"label-repeat-{i}"))
        assert segment is not None
        for label in fp.AMERICA_FAVORITE_LABELS:
            assert segment.count(label) <= 1, f"{label!r} appeared more than once in: {segment!r}"


def test_favorite_label_never_repeats_within_one_win_segment() -> None:
    featured = _featured(rank=28, match=_match(won=True, opponent="Someone", score="6-3 6-2"))
    for i in range(80):
        segment = build_segment(featured, top_n=TOP_N, rng=_rng(f"win-label-repeat-{i}"))
        assert segment is not None
        for label in fp.AMERICA_FAVORITE_LABELS:
            assert segment.count(label) <= 1, f"{label!r} appeared more than once in: {segment!r}"


def test_favorite_label_never_repeats_with_no_match() -> None:
    featured = _featured(rank=28, match=None)
    for i in range(60):
        segment = build_segment(featured, top_n=TOP_N, rng=_rng(f"no-match-label-{i}"))
        assert segment is not None
        for label in fp.AMERICA_FAVORITE_LABELS:
            assert segment.count(label) <= 1, f"{label!r} appeared more than once in: {segment!r}"


# --- Narration polish: sentence-boundary/capitalization ---------------------


def test_loss_segment_never_has_a_lowercase_sentence_start_after_a_period() -> None:
    """Regression test for a real production script that read
    '...7-5,6-2. a temporary setback...' - a lowercase letter immediately
    following a sentence-ending period. Tolerates '.' inside a score/number
    (e.g. abbreviations) only by checking specifically for '. ' followed
    by a lowercase letter, the exact shape of the reported bug."""

    lowercase_after_period = re.compile(r"\.\s+[a-z]")
    featured = _featured(rank=28, match=_match(won=False, opponent="Someone", score="7-5 6-2"))
    for i in range(80):
        segment = build_segment(featured, top_n=TOP_N, rng=_rng(f"sentence-boundary-{i}"))
        assert segment is not None
        match_found = lowercase_after_period.search(segment)
        assert match_found is None, f"Found a lowercase sentence start in: {segment!r}"


def test_win_segment_never_has_a_lowercase_sentence_start_after_a_period() -> None:
    lowercase_after_period = re.compile(r"\.\s+[a-z]")
    featured = _featured(rank=28, match=_match(won=True, opponent="Someone", score="6-3 6-2"))
    for i in range(80):
        segment = build_segment(featured, top_n=TOP_N, rng=_rng(f"win-sentence-boundary-{i}"))
        assert segment is not None
        assert lowercase_after_period.search(segment) is None


# --- Narration polish: score formatting for narration ------------------------


def test_featured_player_match_score_gets_a_space_after_the_comma() -> None:
    featured = _featured(rank=28, match=_match(won=True, opponent="Someone", score="6-4,7-6(2)"))

    segment = build_segment(featured, top_n=TOP_N, rng=_rng("score-format"))

    assert segment is not None
    assert "6-4, 7-6(2)" in segment
    assert "6-4,7-6(2)" not in segment


def test_hearts_joke_appears_sometimes_but_not_every_day() -> None:
    featured = _featured(rank=14, movement=Movement.SAME)
    segments = [
        build_segment(featured, top_n=TOP_N, rng=_rng(f"hearts-{i}")) for i in range(60)
    ]
    hearts_count = sum(1 for s in segments if s and "unofficially" in s.lower())

    assert 0 < hearts_count < len(segments)


# --- Tournament-elimination narration context --------------------------


def test_eliminated_status_adds_elimination_context_to_the_segment() -> None:
    featured = _featured(
        rank=28,
        tournament_status=TournamentRunStatus(
            state=TournamentState.ELIMINATED,
            tournament="Cincinnati",
            round_reached="R32",
            round_label="the Round of 32",
            eliminated_by="Some Rival",
            points_earned=65,
            is_new_development=True,
        ),
    )

    segment = build_segment(featured, top_n=TOP_N, rng=_rng("elimination-context"))

    assert segment is not None
    assert "Some Rival" in segment
    assert "Round of 32" in segment


def test_champion_status_adds_title_context_to_the_segment() -> None:
    featured = _featured(
        rank=5,
        tournament_status=TournamentRunStatus(
            state=TournamentState.CHAMPION,
            tournament="Cincinnati",
            round_reached="W",
            round_label="the title",
            points_earned=1000,
            is_new_development=True,
        ),
    )

    segment = build_segment(featured, top_n=TOP_N, rng=_rng("champion-context"))

    assert segment is not None
    assert "champion" in segment.lower() or "title" in segment.lower()


def test_no_tournament_status_produces_no_elimination_language() -> None:
    featured = _featured(rank=28)

    segment = build_segment(featured, top_n=TOP_N, rng=_rng("no-tournament-status"))

    assert segment is not None
    assert "eliminated" not in segment.lower()
    assert "champion" not in segment.lower()


def test_active_tournament_status_produces_no_elimination_language() -> None:
    featured = _featured(
        rank=28,
        tournament_status=TournamentRunStatus(state=TournamentState.ACTIVE, tournament="Cincinnati"),
    )

    segment = build_segment(featured, top_n=TOP_N, rng=_rng("active-tournament-status"))

    assert segment is not None
    assert "eliminated" not in segment.lower()


# --- Narration-polish follow-up: precedence, naming ---------------------


def test_eliminated_featured_player_never_gets_rest_day_filler() -> None:
    featured = _featured(
        rank=28,
        match=None,
        tournament_status=TournamentRunStatus(
            state=TournamentState.ELIMINATED,
            tournament="Cincinnati",
            round_reached="R32",
            round_label="the Round of 32",
            eliminated_by="Jessica Pegula",
            points_earned=65,
            is_new_development=True,
        ),
    )

    for i in range(20):
        segment = build_segment(featured, top_n=TOP_N, rng=_rng(f"no-rest-day-{i}"))
        assert segment is not None
        for phrase in fp.AMERICA_FAVORITE_NO_MATCH:
            assert phrase.format(name="Emma", favorite="favorite") not in segment
        assert "rest day" not in segment.lower()
        assert "day off" not in segment.lower()
        assert "did not take the court" not in segment.lower()


def test_eliminated_featured_player_never_gets_match_unknown_filler() -> None:
    featured = _featured(
        rank=28,
        match=None,
        match_error="simulated outage",
        tournament_status=TournamentRunStatus(
            state=TournamentState.ELIMINATED,
            round_reached="R32",
            round_label="the Round of 32",
            eliminated_by="Jessica Pegula",
            is_new_development=True,
        ),
    )

    segment = build_segment(featured, top_n=TOP_N, rng=_rng("no-match-unknown"))

    assert segment is not None
    for phrase in fp.AMERICA_FAVORITE_MATCH_UNKNOWN:
        assert phrase not in segment


def test_champion_featured_player_never_gets_rest_day_filler() -> None:
    featured = _featured(
        rank=5,
        match=None,
        tournament_status=TournamentRunStatus(
            state=TournamentState.CHAMPION,
            round_reached="W",
            round_label="the title",
            points_earned=1000,
            is_new_development=True,
        ),
    )

    segment = build_segment(featured, top_n=TOP_N, rng=_rng("champion-no-rest-day"))

    assert segment is not None
    assert "rest day" not in segment.lower()


def test_a_real_match_result_is_never_suppressed_even_when_eliminated() -> None:
    """The suppression only targets generic 'nothing to say either way'
    filler - a genuine win/loss result for the target date is real news
    and must still appear."""

    featured = _featured(
        rank=28,
        match=_match(won=False, opponent="Jessica Pegula", score="7-5,6-3"),
        tournament_status=TournamentRunStatus(
            state=TournamentState.ELIMINATED,
            round_reached="R32",
            round_label="the Round of 32",
            eliminated_by="Jessica Pegula",
            is_new_development=True,
        ),
    )

    segment = build_segment(featured, top_n=TOP_N, rng=_rng("real-match-kept"))

    assert segment is not None
    assert "7-5, 6-3" in segment


def test_active_status_does_not_suppress_the_generic_no_match_filler() -> None:
    """Suppression is specific to a *concluded* run (eliminated/champion) -
    an ACTIVE player with no match that day still gets the normal filler
    sentence, e.g. 'day off'/'rest day'/'no match to report'."""

    featured = _featured(
        rank=28,
        match=None,
        tournament_status=TournamentRunStatus(state=TournamentState.ACTIVE, tournament="Cincinnati"),
    )

    found = False
    for i in range(30):
        segment = build_segment(featured, top_n=TOP_N, rng=_rng(f"active-still-normal-{i}"))
        assert segment is not None
        lowered = segment.lower()
        if any(marker in lowered for marker in ("day off", "rest day", "no match to report")):
            found = True
            break
    assert found


def test_full_name_is_used_only_once_in_the_segment() -> None:
    """The full name should appear only in the intro sentence - every
    later reference (status, match, elimination context) should use her
    first name instead of mechanically repeating the full name."""

    featured = _featured(
        rank=28,
        match=_match(won=False, opponent="Jessica Pegula", score="7-5 6-3"),
        tournament_status=TournamentRunStatus(
            state=TournamentState.ELIMINATED,
            round_reached="R32",
            round_label="the Round of 32",
            eliminated_by="Jessica Pegula",
            points_earned=65,
            previous_year_round="R64",
            previous_year_round_label="the Round of 64",
            points_delta=30,
            is_new_development=True,
        ),
    )

    for i in range(20):
        segment = build_segment(featured, top_n=TOP_N, rng=_rng(f"single-full-name-{i}"))
        assert segment is not None
        assert segment.count("Navarro") == 1
        assert "Emma" in segment


def test_first_name_appears_after_the_eliminator_is_named() -> None:
    featured = _featured(
        rank=28,
        match=None,
        tournament_status=TournamentRunStatus(
            state=TournamentState.ELIMINATED,
            round_reached="R32",
            round_label="the Round of 32",
            eliminated_by="Jessica Pegula",
            points_earned=65,
            is_new_development=True,
        ),
    )

    for i in range(20):
        segment = build_segment(featured, top_n=TOP_N, rng=_rng(f"disambiguate-{i}"))
        assert segment is not None
        pegula_index = segment.index("Pegula")
        assert "Emma" in segment[pegula_index:]


# --- Proximity language must match the actual ranking distance ---------


def test_far_from_top_n_never_claims_close_proximity() -> None:
    """A player around #28 (well outside a Top 10 show) must never be
    described as 'just outside,' 'on the doorstep,' 'knocking on the
    door,' or 'lurking' near the Top N - those phrases falsely imply
    she's close."""

    featured = _featured(rank=28)

    forbidden_phrases = [
        "just outside",
        "on the doorstep",
        "knocking on the door",
        "lurking",
        "next on the itinerary",
        "comes calling",
        "keep an eye over its shoulder",
    ]
    for i in range(60):
        segment = build_segment(featured, top_n=TOP_N, rng=_rng(f"proximity-{i}"))
        assert segment is not None
        lowered = segment.lower()
        for phrase in forbidden_phrases:
            assert phrase not in lowered


def test_far_from_top_n_still_produces_a_playful_but_plausible_segment() -> None:
    featured = _featured(rank=28)

    segment = build_segment(featured, top_n=TOP_N, rng=_rng("plausible-28"))

    assert segment is not None
    assert "28" in segment


def test_a_player_much_further_away_also_never_claims_close_proximity() -> None:
    """The same pool is used for any rank outside the Top N, so it must
    remain safe even for a player nowhere near breaking in (e.g. #150)."""

    featured = _featured(rank=150)

    forbidden_phrases = ["just outside", "on the doorstep", "knocking on the door", "lurking"]
    for i in range(60):
        segment = build_segment(featured, top_n=TOP_N, rng=_rng(f"far-away-{i}"))
        assert segment is not None
        lowered = segment.lower()
        for phrase in forbidden_phrases:
            assert phrase not in lowered


def test_pursuit_language_still_varies_across_many_days() -> None:
    featured = _featured(rank=28)

    segments = {build_segment(featured, top_n=TOP_N, rng=_rng(f"variety-{i}")) for i in range(40)}

    assert len(segments) > 1


# --- Historical elimination wording + round-omission (featured player) --


def test_previously_reported_elimination_uses_completed_historical_wording() -> None:
    featured = _featured(
        rank=28,
        match=None,
        tournament_status=TournamentRunStatus(
            state=TournamentState.ELIMINATED,
            tournament="Cincinnati",
            round_reached="R16",
            round_label="the Round of 16",
            is_new_development=False,
        ),
    )

    for i in range(20):
        segment = build_segment(featured, top_n=TOP_N, rng=_rng(f"historical-{i}"))
        assert segment is not None
        lowered = segment.lower()
        for forbidden in ("still over", "remains out of the draw", "eliminated back in"):
            assert forbidden not in lowered


def test_round_omitted_gracefully_in_featured_match_sentence() -> None:
    """A featured-player match whose round is unknown must never surface
    a raw round code or literal 'None' in her segment."""

    featured = _featured(
        rank=28,
        match=MatchResult(
            opponent="Amanda Anisimova",
            tournament="Cincinnati",
            round=None,
            score="6-4,2-6,7-6(4)",
            won=True,
            match_date=date(2026, 8, 19),
        ),
    )

    for i in range(20):
        segment = build_segment(featured, top_n=TOP_N, rng=_rng(f"round-omit-{i}"))
        assert segment is not None
        assert "None" not in segment
        assert "Round Q" not in segment
        assert "Amanda Anisimova" in segment
