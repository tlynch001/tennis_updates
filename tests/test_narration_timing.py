"""Unit tests for :mod:`wta_daily.voice.narration_timing`.

Builds small, realistic narration scripts (mirroring the exact paragraph
structure TemplateScriptGenerator actually produces) and a synthetic,
uniform-rate character alignment, then verifies the derived segments land
on the right players in the right order with contiguous, non-overlapping
durations - the property that actually matters for slide synchronization.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from wta_daily.models import (
    DailyReport,
    FeaturedPlayerReport,
    Movement,
    PlayerReport,
)
from wta_daily.voice.narration_timing import (
    NarrationSegment,
    compute_segment_timings,
    read_timing_file,
    write_timing_file,
)


def _player(rank: int, name: str) -> PlayerReport:
    return PlayerReport(
        rank=rank,
        name=name,
        player_id=f"p{rank}",
        country_code="USA",
        points=10_000 - rank * 100,
        movement=Movement.SAME,
    )


def _uniform_alignment(
    text: str, seconds_per_char: float = 0.05
) -> tuple[list[str], list[float], list[float]]:
    """A synthetic, perfectly uniform character alignment - not realistic
    speech timing, but exactly what's needed to verify offset math without
    depending on any real audio."""

    characters = list(text)
    starts = [i * seconds_per_char for i in range(len(characters))]
    ends = [(i + 1) * seconds_per_char for i in range(len(characters))]
    return characters, starts, ends


def _report(
    players: list[PlayerReport], featured: FeaturedPlayerReport | None = None
) -> DailyReport:
    return DailyReport(
        report_date=date(2026, 8, 16), tour="wta", players=players, featured_player=featured
    )


def test_basic_intro_players_and_closer_are_contiguous_and_in_order() -> None:
    script = (
        "Welcome to today's update.\n\n"
        "Player One is ranked number 1 today, and did not play yesterday.\n\n"
        "Player Two comes in at number 2 after a big win.\n\n"
        "Thanks for watching."
    )
    report = _report([_player(1, "Player One"), _player(2, "Player Two")])
    characters, starts, ends = _uniform_alignment(script)

    segments = compute_segment_timings(report, script, characters, starts, ends)

    kinds = [s.kind for s in segments]
    assert kinds == ["intro", "player", "player", "closer"]
    assert [s.rank for s in segments] == [None, 1, 2, None]

    # Contiguous and monotonically increasing - no gaps or overlaps.
    for earlier, later in zip(segments, segments[1:], strict=False):
        assert earlier.end_seconds <= later.start_seconds + 1e-6

    # The whole timeline is covered: starts at (about) 0, ends at the
    # alignment's final character time.
    assert segments[0].start_seconds < 0.1
    assert segments[-1].end_seconds == ends[-1]


def test_different_length_paragraphs_produce_different_duration_segments() -> None:
    """The core requirement: a short 'did not play' blurb must not get the
    same slide duration as a long match-result paragraph."""

    short_paragraph = "Player One did not play yesterday."
    long_paragraph = (
        "Player Two put in a dominant performance yesterday, coming through in "
        "straight sets against a tough opponent to continue her strong run of form "
        "heading into the next round of the tournament."
    )
    script = f"Welcome to today's update.\n\n{short_paragraph}\n\n{long_paragraph}\n\nThanks for watching."
    report = _report([_player(1, "Player One"), _player(2, "Player Two")])
    characters, starts, ends = _uniform_alignment(script)

    segments = compute_segment_timings(report, script, characters, starts, ends)
    by_rank = {s.rank: s for s in segments if s.kind == "player"}

    assert by_rank[2].duration_seconds > by_rank[1].duration_seconds * 2


def test_featured_player_segment_is_identified_after_top_n_players() -> None:
    script = (
        "Welcome to today's update.\n\n"
        "Player One is ranked number 1 today, and did not play yesterday.\n\n"
        "And now, a word on Emma Navarro. Emma is ranked number 28 today.\n\n"
        "Thanks for watching."
    )
    featured = FeaturedPlayerReport(
        name="Emma Navarro", player_id="emma", tagline="america_favorite", rank=28
    )
    report = _report([_player(1, "Player One")], featured=featured)
    characters, starts, ends = _uniform_alignment(script)

    segments = compute_segment_timings(report, script, characters, starts, ends)

    kinds = [s.kind for s in segments]
    assert kinds == ["intro", "player", "featured", "closer"]
    featured_segment = next(s for s in segments if s.kind == "featured")
    assert featured_segment.label == "Emma Navarro"


def test_featured_player_without_a_rank_produces_no_featured_segment() -> None:
    """If her segment was never narrated (e.g. rank unavailable that run),
    there's nothing to match, and no featured slide should appear."""

    script = (
        "Welcome to today's update.\n\n"
        "Player One is ranked number 1 today, and did not play yesterday.\n\n"
        "Thanks for watching."
    )
    featured = FeaturedPlayerReport(
        name="Emma Navarro", player_id="emma", tagline="america_favorite", rank=None
    )
    report = _report([_player(1, "Player One")], featured=featured)
    characters, starts, ends = _uniform_alignment(script)

    segments = compute_segment_timings(report, script, characters, starts, ends)

    assert "featured" not in [s.kind for s in segments]


def test_unmatched_filler_paragraph_extends_the_previous_segment() -> None:
    """A length-padding filler paragraph (present in real output when the
    template generator needs to hit its target word count) mentions no
    player by name - it must not become its own slide."""

    script = (
        "Welcome to today's update.\n\n"
        "Player One is ranked number 1 today, and did not play yesterday.\n\n"
        "As always, ranking points reflect performance over the last year.\n\n"
        "Thanks for watching."
    )
    report = _report([_player(1, "Player One")])
    characters, starts, ends = _uniform_alignment(script)

    segments = compute_segment_timings(report, script, characters, starts, ends)

    kinds = [s.kind for s in segments]
    assert kinds == ["intro", "player", "closer"]
    # Player One's segment absorbed the filler paragraph's time.
    player_one = next(s for s in segments if s.rank == 1)
    closer = next(s for s in segments if s.kind == "closer")
    assert player_one.end_seconds == closer.start_seconds


def test_too_few_paragraphs_returns_no_segments() -> None:
    """A malformed/unexpected script shape (e.g. no blank-line paragraphs
    at all) must degrade to 'no timing available', not crash or guess."""

    script = "Just one single paragraph with no structure at all."
    report = _report([_player(1, "Player One")])
    characters, starts, ends = _uniform_alignment(script)

    assert compute_segment_timings(report, script, characters, starts, ends) == []


def test_empty_alignment_still_returns_zero_duration_segments_gracefully() -> None:
    report = _report([_player(1, "Player One")])
    script = "Welcome to today's update.\n\nPlayer One is ranked number 1 today.\n\nThanks for watching."

    segments = compute_segment_timings(report, script, [], [], [])

    # No crash; everything collapses to zero-length segments rather than
    # raising an IndexError.
    assert all(s.duration_seconds == 0.0 for s in segments)


def test_write_and_read_timing_file_round_trip(tmp_path: Path) -> None:
    segments = [
        NarrationSegment(kind="intro", label="intro", start_seconds=0.0, end_seconds=2.0),
        NarrationSegment(kind="player", label="Player One", rank=1, start_seconds=2.0, end_seconds=5.5),
        NarrationSegment(kind="closer", label="closer", start_seconds=5.5, end_seconds=8.0),
    ]
    path = tmp_path / "narration_timing.json"

    write_timing_file(path, segments)
    restored = read_timing_file(path)

    assert restored is not None
    assert len(restored) == 3
    assert restored[1].kind == "player"
    assert restored[1].rank == 1
    assert restored[1].duration_seconds == 3.5


def test_read_timing_file_returns_none_when_missing(tmp_path: Path) -> None:
    assert read_timing_file(tmp_path / "does-not-exist.json") is None


def test_read_timing_file_returns_none_on_corrupt_file(tmp_path: Path) -> None:
    path = tmp_path / "corrupt.json"
    path.write_text("not valid json {{{", encoding="utf-8")

    assert read_timing_file(path) is None


def test_read_timing_file_returns_none_for_empty_segment_list(tmp_path: Path) -> None:
    path = tmp_path / "empty.json"
    path.write_text('{"segments": []}', encoding="utf-8")

    assert read_timing_file(path) is None
