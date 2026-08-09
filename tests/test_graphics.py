from __future__ import annotations

from datetime import date
from pathlib import Path

from PIL import Image

from wta_daily.config import GraphicsConfig
from wta_daily.graphics.leaderboard import render_leaderboard
from wta_daily.graphics.player_card import render_player_card
from wta_daily.models import DailyReport, MatchResult, Movement, PlayerReport


def _report() -> DailyReport:
    match = MatchResult(
        opponent="Some Opponent",
        tournament="Some Open",
        round="Final",
        score="6-4 6-4",
        won=True,
        match_date=date(2026, 8, 8),
    )
    players = [
        PlayerReport(
            rank=i,
            name=f"Player {i}",
            player_id=f"p{i}",
            country_code="USA",
            points=10000 - i * 100,
            movement=Movement.NEW,
            match=match,
        )
        for i in range(1, 4)
    ]
    return DailyReport(report_date=date(2026, 8, 9), tour="wta", players=players)


def test_render_leaderboard_creates_correctly_sized_png(tmp_path: Path) -> None:
    config = GraphicsConfig(width=640, height=360)
    output_path = tmp_path / "leaderboard.png"

    result_path = render_leaderboard(_report(), output_path, config)

    assert result_path == output_path
    assert output_path.exists()
    with Image.open(output_path) as img:
        assert img.size == (640, 360)


def test_render_player_card_creates_png(tmp_path: Path) -> None:
    config = GraphicsConfig(width=640, height=360)
    report = _report()
    output_path = tmp_path / "card.png"

    render_player_card(report.players[0], output_path, config, top_n=10)

    assert output_path.exists()
    with Image.open(output_path) as img:
        assert img.size == (640, 360)


def test_render_player_card_handles_no_match(tmp_path: Path) -> None:
    config = GraphicsConfig(width=640, height=360)
    player = PlayerReport(
        rank=1,
        name="No Match",
        player_id="p1",
        country_code="ZZZ",
        points=1000,
        movement=Movement.SAME,
        previous_rank=1,
        match=None,
    )
    output_path = tmp_path / "card.png"

    render_player_card(player, output_path, config, top_n=10)

    assert output_path.exists()
