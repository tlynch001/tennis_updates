from __future__ import annotations

from datetime import date
from pathlib import Path

from PIL import Image

from wta_daily.config import GraphicsConfig
from wta_daily.graphics.featured_card import render_featured_card
from wta_daily.graphics.leaderboard import render_leaderboard
from wta_daily.graphics.player_card import render_player_card
from wta_daily.graphics.thumbnail import THUMBNAIL_HEIGHT, THUMBNAIL_WIDTH, render_thumbnail
from wta_daily.graphics.utils import hex_to_rgb
from wta_daily.models import DailyReport, FeaturedPlayerReport, MatchResult, Movement, PlayerReport


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


def test_render_player_card_handles_match_with_unconfirmed_date(tmp_path: Path) -> None:
    """A match can be fully known except for its date - graphics must not crash
    or fabricate a date, per the "null is better than wrong" rule."""

    config = GraphicsConfig(width=640, height=360)
    match = MatchResult(
        opponent="Some Opponent",
        tournament="Some Open",
        round="Final",
        score="6-4 6-4",
        won=True,
        match_date=None,
    )
    player = PlayerReport(
        rank=1,
        name="Unconfirmed Date Player",
        player_id="p1",
        country_code="USA",
        points=1000,
        movement=Movement.SAME,
        previous_rank=1,
        match=match,
    )
    output_path = tmp_path / "card.png"

    render_player_card(player, output_path, config, top_n=10)

    assert output_path.exists()
    with Image.open(output_path) as img:
        assert img.size == (640, 360)


def test_render_player_card_handles_match_with_unknown_round(tmp_path: Path) -> None:
    """A match whose round couldn't be confidently normalized (see
    wta_daily.plugins.matches.wta_official's round-normalization
    docstring) must render without crashing or embedding a literal
    'None' in the card text."""

    config = GraphicsConfig(width=640, height=360)
    match = MatchResult(
        opponent="Amanda Anisimova",
        tournament="Cincinnati",
        round=None,
        score="6-4,2-6,7-6(4)",
        won=True,
        match_date=date(2026, 8, 19),
    )
    player = PlayerReport(
        rank=1,
        name="Unknown Round Player",
        player_id="p1",
        country_code="USA",
        points=1000,
        movement=Movement.SAME,
        previous_rank=1,
        match=match,
    )
    output_path = tmp_path / "card.png"

    render_player_card(player, output_path, config, top_n=10)

    assert output_path.exists()
    with Image.open(output_path) as img:
        assert img.size == (640, 360)


def test_render_player_card_handles_unknown_movement(tmp_path: Path) -> None:
    """No previous snapshot at all - graphics must render neutrally, not as 'NEW'."""

    config = GraphicsConfig(width=640, height=360)
    player = PlayerReport(
        rank=4,
        name="Baseline Player",
        player_id="p4",
        country_code="USA",
        points=1000,
        movement=Movement.UNKNOWN,
        previous_rank=None,
        match=None,
    )
    output_path = tmp_path / "card.png"

    render_player_card(player, output_path, config, top_n=10)

    assert output_path.exists()


# --- Featured-player card -----------------------------------------------------


def test_render_featured_card_creates_correctly_sized_png(tmp_path: Path) -> None:
    config = GraphicsConfig(width=640, height=360)
    match = MatchResult(
        opponent="Some Opponent",
        tournament="Cincinnati",
        round="Round of 32",
        score="6-4 6-2",
        won=True,
        match_date=date(2026, 8, 15),
    )
    featured = FeaturedPlayerReport(
        name="Emma Navarro",
        player_id="325410",
        tagline="america_favorite",
        country_code="USA",
        rank=28,
        points=1669,
        movement=Movement.SAME,
        previous_rank=28,
        match=match,
    )
    output_path = tmp_path / "featured.png"

    result_path = render_featured_card(featured, output_path, config, top_n=10)

    assert result_path == output_path
    assert output_path.exists()
    with Image.open(output_path) as img:
        assert img.size == (640, 360)


def test_render_featured_card_handles_match_with_unknown_round(tmp_path: Path) -> None:
    config = GraphicsConfig(width=640, height=360)
    match = MatchResult(
        opponent="Amanda Anisimova",
        tournament="Cincinnati",
        round=None,
        score="6-4,2-6,7-6(4)",
        won=True,
        match_date=date(2026, 8, 19),
    )
    featured = FeaturedPlayerReport(
        name="Emma Navarro",
        player_id="325410",
        tagline="america_favorite",
        country_code="USA",
        rank=28,
        points=1669,
        movement=Movement.SAME,
        previous_rank=28,
        match=match,
    )
    output_path = tmp_path / "featured.png"

    render_featured_card(featured, output_path, config, top_n=10)

    assert output_path.exists()
    with Image.open(output_path) as img:
        assert img.size == (640, 360)


def test_render_featured_card_handles_unavailable_rank_without_crashing(tmp_path: Path) -> None:
    """No rank at all this run - the card must still render, with an honest
    'unavailable' message rather than a fabricated number."""

    config = GraphicsConfig(width=640, height=360)
    featured = FeaturedPlayerReport(
        name="Emma Navarro",
        player_id="325410",
        tagline="america_favorite",
        rank_error="network timeout",
    )
    output_path = tmp_path / "featured.png"

    render_featured_card(featured, output_path, config, top_n=10)

    assert output_path.exists()


def test_render_featured_card_handles_no_match(tmp_path: Path) -> None:
    config = GraphicsConfig(width=640, height=360)
    featured = FeaturedPlayerReport(
        name="Emma Navarro",
        player_id="325410",
        tagline="america_favorite",
        country_code="USA",
        rank=28,
        points=1669,
        movement=Movement.SAME,
        previous_rank=28,
        match=None,
    )
    output_path = tmp_path / "featured.png"

    render_featured_card(featured, output_path, config, top_n=10)

    assert output_path.exists()


def test_render_featured_card_handles_player_inside_top_n(tmp_path: Path) -> None:
    """When she's genuinely inside the tracked group, the card must still
    render without claiming she's outside it."""

    config = GraphicsConfig(width=640, height=360)
    featured = FeaturedPlayerReport(
        name="Emma Navarro",
        player_id="325410",
        tagline="america_favorite",
        country_code="USA",
        rank=8,
        points=4000,
        movement=Movement.NEW,
        previous_rank=None,
        match=None,
    )
    output_path = tmp_path / "featured.png"

    render_featured_card(featured, output_path, config, top_n=10)

    assert output_path.exists()


# --- YouTube thumbnail ---------------------------------------------------------

# Pixel-level helpers used to inspect the *rendered* thumbnail layout
# black-box (rather than the internal pixel math in thumbnail.py), so the
# tests still hold even if the implementation changes.


def _ink_rows(img: Image.Image, bg: tuple[int, int, int], y_start: int, y_end: int) -> list[int]:
    """Row numbers in [y_start, y_end) that contain at least one non-background
    pixel - a crude but implementation-independent way to find text lines."""
    px = img.load()
    rows = []
    for y in range(y_start, y_end):
        for x in range(0, img.width, 2):  # sampling every other column is plenty
            if px[x, y] != bg:
                rows.append(y)
                break
    return rows


def _line_bands(rows: list[int]) -> list[tuple[int, int]]:
    """Group consecutive-ish row numbers into bands (one per text line),
    tolerating the tiny anti-aliasing gaps that can occur within a line
    (e.g. above the closed counter of an "O")."""
    bands: list[list[int]] = []
    for y in rows:
        if bands and y - bands[-1][-1] <= 3:
            bands[-1].append(y)
        else:
            bands.append([y])
    return [(band[0], band[-1]) for band in bands]


def _ink_column_range(
    img: Image.Image, bg: tuple[int, int, int], y_start: int, y_end: int
) -> tuple[int, int]:
    px = img.load()
    left, right = None, None
    for y in range(y_start, y_end + 1):
        for x in range(img.width):
            if px[x, y] != bg:
                left = x if left is None else min(left, x)
                right = x if right is None else max(right, x)
    assert left is not None and right is not None, "expected some ink in this row range"
    return left, right


def test_render_thumbnail_is_exactly_1280x720(tmp_path: Path) -> None:
    output_path = tmp_path / "thumbnail.png"

    result_path = render_thumbnail(_report(), output_path, GraphicsConfig())

    assert result_path == output_path
    with Image.open(output_path) as img:
        assert img.size == (1280, 720)
        assert img.size == (THUMBNAIL_WIDTH, THUMBNAIL_HEIGHT)


def test_render_thumbnail_is_independent_of_graphics_config_dimensions(tmp_path: Path) -> None:
    """The thumbnail is always 1280x720 regardless of the leaderboard/card
    canvas size configured for the rest of the graphics."""

    output_path = tmp_path / "thumbnail.png"

    render_thumbnail(_report(), output_path, GraphicsConfig(width=640, height=360))

    with Image.open(output_path) as img:
        assert img.size == (1280, 720)


def test_render_thumbnail_works_without_reliable_tournament_data(tmp_path: Path) -> None:
    """No player has a confirmed match - the thumbnail must still render,
    simply without a tournament line, rather than guessing one."""

    players = [
        PlayerReport(
            rank=i,
            name=f"Player {i}",
            player_id=f"p{i}",
            country_code="USA",
            points=1000 - i,
            movement=Movement.SAME,
            match=None,
        )
        for i in range(1, 11)
    ]
    report = DailyReport(report_date=date(2026, 8, 16), tour="wta", players=players)
    output_path = tmp_path / "thumbnail.png"

    render_thumbnail(report, output_path, GraphicsConfig())

    assert output_path.exists()
    with Image.open(output_path) as img:
        assert img.size == (1280, 720)


def test_render_thumbnail_has_clearly_distinct_vertical_gaps_between_lines(tmp_path: Path) -> None:
    """Regression test: 'WTA TOP 10' / date / tournament must read as three
    visually distinct lines rather than one tightly packed block - the old
    layout used a single ~25px gap (height * 0.035) between every line."""

    graphics = GraphicsConfig()
    output_path = tmp_path / "thumbnail.png"

    render_thumbnail(_report(), output_path, graphics)

    with Image.open(output_path) as img:
        img = img.convert("RGB")
        bg = hex_to_rgb(graphics.theme.background_color)
        stripe_h = int(img.height * 0.03)
        rows = _ink_rows(img, bg, 0, img.height - stripe_h)

    bands = _line_bands(rows)
    assert len(bands) == 3, f"expected headline/date/tournament as 3 distinct bands, got: {bands}"

    gap_headline_to_date = bands[1][0] - bands[0][1]
    gap_date_to_tournament = bands[2][0] - bands[1][1]

    old_uniform_gap = int(THUMBNAIL_HEIGHT * 0.035)
    assert gap_headline_to_date > old_uniform_gap * 1.5
    assert gap_date_to_tournament > old_uniform_gap * 1.5


def test_render_thumbnail_fits_long_tournament_names_within_frame(tmp_path: Path) -> None:
    """A long tournament name must be shrunk to fit, not clipped or run off
    the edge of the 1280-wide frame - mirrors the headline's own width fit."""

    match = MatchResult(
        opponent="Some Opponent",
        tournament="The Extraordinarily Long Championship Invitational Series",
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
    report = DailyReport(report_date=date(2026, 8, 9), tour="wta", players=players)
    graphics = GraphicsConfig()
    output_path = tmp_path / "thumbnail.png"

    render_thumbnail(report, output_path, graphics)

    with Image.open(output_path) as img:
        img = img.convert("RGB")
        assert img.size == (1280, 720)
        bg = hex_to_rgb(graphics.theme.background_color)
        stripe_h = int(img.height * 0.03)
        rows = _ink_rows(img, bg, 0, img.height - stripe_h)
        bands = _line_bands(rows)
        assert len(bands) == 3
        tournament_top, tournament_bottom = bands[2]
        left, right = _ink_column_range(img, bg, tournament_top, tournament_bottom)

    max_text_width = img.width * 0.92
    assert (right - left) <= max_text_width + 5  # small anti-aliasing tolerance
    assert left > 0
    assert right < img.width - 1
