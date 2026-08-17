"""Unit tests for :mod:`wta_daily.video.ffmpeg_assembler`.

Mocks ``subprocess.run`` (never actually shells out to ffmpeg) so these
tests focus on the part that changed: which image is chosen for each slide
and for how long, driven by ``narration_timing.json`` when present and by
the original fixed-duration behavior otherwise.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from wta_daily.config import VideoConfig
from wta_daily.exceptions import VideoAssemblyError
from wta_daily.models import DailyReport, FeaturedPlayerReport, Movement, PlayerReport
from wta_daily.persistence.report_store import DailyOutputStore
from wta_daily.video.ffmpeg_assembler import FfmpegVideoAssembler


def _player(rank: int, name: str) -> PlayerReport:
    return PlayerReport(
        rank=rank,
        name=name,
        player_id=f"p{rank}",
        country_code="USA",
        points=1000 - rank,
        movement=Movement.SAME,
    )


def _make_store(tmp_path: Path, report_date: date, *, ranks_with_cards: list[int]) -> DailyOutputStore:
    store = DailyOutputStore(tmp_path / "output", report_date)
    store.ensure_dirs()
    store.leaderboard_path.write_bytes(b"leaderboard")
    for rank in ranks_with_cards:
        store.player_card_path(rank).write_bytes(b"card")
    return store


def _write_timing(store: DailyOutputStore, segments: list[dict]) -> None:
    store.timing_path.write_text(json.dumps({"segments": segments}), encoding="utf-8")


def _segment(kind: str, start: float, end: float, rank: int | None = None, label: str = "x") -> dict:
    return {
        "kind": kind,
        "label": label,
        "rank": rank,
        "start_seconds": start,
        "end_seconds": end,
        "duration_seconds": end - start,
    }


@pytest.fixture(autouse=True)
def _ffmpeg_on_path() -> None:
    with patch("shutil.which", return_value="/usr/bin/ffmpeg"):
        yield


def _mock_subprocess_success(command: list[str], **_kwargs: object) -> MagicMock:
    # ffmpeg's real job is writing the output file (the command's last
    # argument in both _build_silent_video and _mux_audio) - fake that so
    # later steps (shutil.copy of the "silent" video, etc.) have something
    # to work with, without actually invoking ffmpeg.
    Path(command[-1]).write_bytes(b"fake-video-bytes")
    result = MagicMock()
    result.returncode = 0
    result.stderr = ""
    return result


class _CaptureConcatList:
    """Captures the concat list file's contents by wrapping subprocess.run."""

    def __init__(self) -> None:
        self.concat_contents: str | None = None

    def __call__(self, command: list[str], **kwargs: object) -> MagicMock:
        if "-f" in command and "concat" in command:
            list_file = Path(command[command.index("-i") + 1])
            self.concat_contents = list_file.read_text(encoding="utf-8")
        return _mock_subprocess_success(command)


def test_uses_timing_based_slides_when_timing_file_exists(tmp_path: Path) -> None:
    report_date = date(2026, 8, 16)
    report = DailyReport(
        report_date=report_date, tour="wta", players=[_player(1, "Player One"), _player(2, "Player Two")]
    )
    store = _make_store(tmp_path, report_date, ranks_with_cards=[1, 2])
    _write_timing(
        store,
        [
            _segment("intro", 0.0, 2.0),
            _segment("player", 2.0, 5.0, rank=1, label="Player One"),
            _segment("player", 5.0, 12.0, rank=2, label="Player Two"),
            _segment("closer", 12.0, 14.0),
        ],
    )

    capture = _CaptureConcatList()
    with patch("subprocess.run", side_effect=capture):
        FfmpegVideoAssembler(VideoConfig()).assemble(report, store.root)

    assert capture.concat_contents is not None
    assert "duration 2.0" in capture.concat_contents  # intro
    assert "duration 3.0" in capture.concat_contents  # player one: 5.0 - 2.0
    assert "duration 7.0" in capture.concat_contents  # player two: 12.0 - 5.0
    assert str(store.player_card_path(1).resolve()) in capture.concat_contents
    assert str(store.player_card_path(2).resolve()) in capture.concat_contents


def test_falls_back_to_fixed_durations_when_no_timing_file(tmp_path: Path) -> None:
    report_date = date(2026, 8, 16)
    report = DailyReport(
        report_date=report_date, tour="wta", players=[_player(1, "Player One"), _player(2, "Player Two")]
    )
    store = _make_store(tmp_path, report_date, ranks_with_cards=[1, 2])
    config = VideoConfig(seconds_per_player_card=6.0)

    capture = _CaptureConcatList()
    with patch("subprocess.run", side_effect=capture):
        FfmpegVideoAssembler(config).assemble(report, store.root)

    assert capture.concat_contents is not None
    assert "duration 6.0" in capture.concat_contents
    # The fixed-duration intro is 4 + 6 seconds.
    assert "duration 10.0" in capture.concat_contents


def test_missing_player_card_falls_back_to_leaderboard_for_that_segment(tmp_path: Path) -> None:
    """A player card that failed to render must not drop the segment or
    desynchronize later slides - it just shows the leaderboard instead."""

    report_date = date(2026, 8, 16)
    report = DailyReport(
        report_date=report_date, tour="wta", players=[_player(1, "Player One"), _player(2, "Player Two")]
    )
    store = _make_store(tmp_path, report_date, ranks_with_cards=[2])  # rank 1's card is missing
    _write_timing(
        store,
        [
            _segment("intro", 0.0, 2.0),
            _segment("player", 2.0, 5.0, rank=1, label="Player One"),
            _segment("player", 5.0, 8.0, rank=2, label="Player Two"),
            _segment("closer", 8.0, 9.0),
        ],
    )

    capture = _CaptureConcatList()
    with patch("subprocess.run", side_effect=capture):
        FfmpegVideoAssembler(VideoConfig()).assemble(report, store.root)

    assert capture.concat_contents is not None
    # Intro (leaderboard) and rank 1's fallback (also leaderboard) are
    # adjacent and get merged into one longer leaderboard slide.
    assert "duration 5.0" in capture.concat_contents  # 2.0 (intro) + 3.0 (rank 1 fallback)
    assert str(store.player_card_path(2).resolve()) in capture.concat_contents


def test_featured_segment_falls_back_to_leaderboard_when_no_dedicated_visual(tmp_path: Path) -> None:
    report_date = date(2026, 8, 16)
    featured = FeaturedPlayerReport(
        name="Emma Navarro", player_id="emma", tagline="america_favorite", rank=28
    )
    report = DailyReport(
        report_date=report_date,
        tour="wta",
        players=[_player(1, "Player One")],
        featured_player=featured,
    )
    store = _make_store(tmp_path, report_date, ranks_with_cards=[1])
    _write_timing(
        store,
        [
            _segment("intro", 0.0, 2.0),
            _segment("player", 2.0, 5.0, rank=1, label="Player One"),
            _segment("featured", 5.0, 8.0, label="Emma Navarro"),
            _segment("closer", 8.0, 9.0),
        ],
    )
    assert not store.featured_card_path.exists()

    capture = _CaptureConcatList()
    with patch("subprocess.run", side_effect=capture):
        FfmpegVideoAssembler(VideoConfig()).assemble(report, store.root)

    assert capture.concat_contents is not None
    # closer (1.0s) merges with the featured leaderboard-fallback (3.0s).
    assert "duration 4.0" in capture.concat_contents


def test_featured_segment_uses_dedicated_visual_when_present(tmp_path: Path) -> None:
    report_date = date(2026, 8, 16)
    featured = FeaturedPlayerReport(
        name="Emma Navarro", player_id="emma", tagline="america_favorite", rank=28
    )
    report = DailyReport(
        report_date=report_date, tour="wta", players=[], featured_player=featured
    )
    store = _make_store(tmp_path, report_date, ranks_with_cards=[])
    store.featured_card_path.write_bytes(b"emma card")
    _write_timing(
        store,
        [
            _segment("intro", 0.0, 2.0),
            _segment("featured", 2.0, 6.0, label="Emma Navarro"),
            _segment("closer", 6.0, 7.0),
        ],
    )

    capture = _CaptureConcatList()
    with patch("subprocess.run", side_effect=capture):
        FfmpegVideoAssembler(VideoConfig()).assemble(report, store.root)

    assert capture.concat_contents is not None
    assert str(store.featured_card_path.resolve()) in capture.concat_contents


def test_corrupt_timing_file_falls_back_gracefully(tmp_path: Path) -> None:
    report_date = date(2026, 8, 16)
    report = DailyReport(report_date=report_date, tour="wta", players=[_player(1, "Player One")])
    store = _make_store(tmp_path, report_date, ranks_with_cards=[1])
    store.timing_path.write_text("not valid json {{{", encoding="utf-8")

    capture = _CaptureConcatList()
    with patch("subprocess.run", side_effect=capture):
        FfmpegVideoAssembler(VideoConfig()).assemble(report, store.root)

    assert capture.concat_contents is not None  # did not crash; fell back successfully


def test_missing_leaderboard_raises(tmp_path: Path) -> None:
    report_date = date(2026, 8, 16)
    report = DailyReport(report_date=report_date, tour="wta", players=[])
    store = DailyOutputStore(tmp_path / "output", report_date)
    store.ensure_dirs()  # no leaderboard.png written

    with pytest.raises(VideoAssemblyError):
        FfmpegVideoAssembler(VideoConfig()).assemble(report, store.root)


def test_ffmpeg_not_installed_raises(tmp_path: Path) -> None:
    report_date = date(2026, 8, 16)
    report = DailyReport(report_date=report_date, tour="wta", players=[])
    store = _make_store(tmp_path, report_date, ranks_with_cards=[])

    with patch("shutil.which", return_value=None), pytest.raises(VideoAssemblyError):
        FfmpegVideoAssembler(VideoConfig()).assemble(report, store.root)


def test_assembles_successfully_without_narration_audio(tmp_path: Path) -> None:
    """Video generation must still work if narration is unavailable -
    falls back to fixed timing and a silent video."""

    report_date = date(2026, 8, 16)
    report = DailyReport(report_date=report_date, tour="wta", players=[_player(1, "Player One")])
    store = _make_store(tmp_path, report_date, ranks_with_cards=[1])
    assert not store.narration_path.exists()

    with patch("subprocess.run", side_effect=_mock_subprocess_success):
        with patch("shutil.copy") as mock_copy:
            output = FfmpegVideoAssembler(VideoConfig()).assemble(report, store.root)

    mock_copy.assert_called_once()
    assert output == store.video_path


def test_assembles_with_narration_audio_present(tmp_path: Path) -> None:
    report_date = date(2026, 8, 16)
    report = DailyReport(report_date=report_date, tour="wta", players=[_player(1, "Player One")])
    store = _make_store(tmp_path, report_date, ranks_with_cards=[1])
    store.narration_path.write_bytes(b"fake mp3")

    call_count = {"n": 0}

    def _fake_run(command: list[str], **kwargs: object) -> MagicMock:
        call_count["n"] += 1
        return _mock_subprocess_success(command)

    with patch("subprocess.run", side_effect=_fake_run):
        output = FfmpegVideoAssembler(VideoConfig()).assemble(report, store.root)

    assert call_count["n"] == 2  # one to build the silent video, one to mux audio
    assert output == store.video_path
