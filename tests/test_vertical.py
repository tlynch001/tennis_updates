from datetime import date
from pathlib import Path

from PIL import Image

from wta_daily.config import GraphicsConfig, ThemeConfig
from wta_daily.models import DailyReport, Movement, PlayerReport
from wta_daily.vertical import (
    PORTRAIT_HEIGHT,
    PORTRAIT_WIDTH,
    _image_for_segment,
    _portrait_config,
    render_vertical_leaderboard,
    render_vertical_player_card,
)
from wta_daily.voice.narration_timing import NarrationSegment


def _player() -> PlayerReport:
    return PlayerReport(
        rank=1,
        name="Aryna Sabalenka",
        player_id="320760",
        country_code="BLR",
        points=8575,
        movement=Movement.SAME,
        previous_rank=1,
    )


def test_portrait_config_preserves_theme_and_changes_only_canvas() -> None:
    theme = ThemeConfig(accent_color="#123456", font_bold="/tmp/custom-bold.ttf")
    source = GraphicsConfig(width=1920, height=1080, theme=theme)

    portrait = _portrait_config(source)

    assert portrait.width == PORTRAIT_WIDTH
    assert portrait.height == PORTRAIT_HEIGHT
    assert portrait.theme is theme
    assert source.width == 1920
    assert source.height == 1080


def test_vertical_graphics_render_at_1080x1920(tmp_path: Path) -> None:
    graphics = _portrait_config(GraphicsConfig())
    player = _player()
    report = DailyReport(report_date=date(2026, 9, 5), tour="wta", players=[player])

    leaderboard = render_vertical_leaderboard(report, tmp_path / "leaderboard.png", graphics)
    card = render_vertical_player_card(
        player,
        tmp_path / "player_cards" / "01.png",
        graphics,
        top_n=10,
        supports_daily_matches=True,
    )

    with Image.open(leaderboard) as image:
        assert image.size == (1080, 1920)
    with Image.open(card) as image:
        assert image.size == (1080, 1920)


def test_segment_image_mapping_uses_portrait_assets(tmp_path: Path) -> None:
    root = tmp_path / "vertical"
    cards = root / "player_cards"
    cards.mkdir(parents=True)
    (root / "leaderboard.png").touch()
    (cards / "01.png").touch()
    (root / "featured_player.png").touch()

    intro = NarrationSegment("intro", "intro", 0.0, 8.0)
    player = NarrationSegment("player", "Aryna Sabalenka", 8.16, 17.12, rank=1)
    featured = NarrationSegment("featured", "Emma Navarro", 140.002, 165.762)
    closer = NarrationSegment("closer", "closer", 165.762, 171.602)

    assert _image_for_segment(intro, root) == root / "leaderboard.png"
    assert _image_for_segment(player, root) == cards / "01.png"
    assert _image_for_segment(featured, root) == root / "featured_player.png"
    assert _image_for_segment(closer, root) == root / "leaderboard.png"


def test_missing_player_card_falls_back_to_leaderboard(tmp_path: Path) -> None:
    root = tmp_path / "vertical"
    root.mkdir()
    leaderboard = root / "leaderboard.png"
    leaderboard.touch()
    segment = NarrationSegment("player", "Missing Player", 1.0, 2.0, rank=7)

    assert _image_for_segment(segment, root) == leaderboard
