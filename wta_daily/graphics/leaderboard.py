"""Renders the full-tour leaderboard overview graphic (``leaderboard.png``)."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

from wta_daily.config import GraphicsConfig
from wta_daily.countries import get_country_info
from wta_daily.exceptions import GraphicsError
from wta_daily.graphics.flags import render_flag
from wta_daily.graphics.fonts import load_font
from wta_daily.graphics.utils import draw_movement_glyph, fit_text, hex_to_rgb, movement_color
from wta_daily.models import DailyReport
from wta_daily.tour import profile_for


def render_leaderboard(report: DailyReport, output_path: Path, graphics: GraphicsConfig) -> Path:
    try:
        return _render(report, output_path, graphics)
    except Exception as exc:  # noqa: BLE001
        raise GraphicsError(f"Failed to render leaderboard for {report.report_date}: {exc}") from exc


def _render(report: DailyReport, output_path: Path, graphics: GraphicsConfig) -> Path:
    theme = graphics.theme
    width, height = graphics.width, graphics.height
    bg = hex_to_rgb(theme.background_color)
    panel = hex_to_rgb(theme.panel_color)
    accent = hex_to_rgb(theme.accent_color)
    text_color = hex_to_rgb(theme.text_color)
    subtext_color = hex_to_rgb(theme.subtext_color)

    img = Image.new("RGB", (width, height), bg)
    draw = ImageDraw.Draw(img)

    header_height = int(height * 0.13)
    draw.rectangle([0, 0, width, header_height], fill=panel)
    draw.rectangle([0, header_height - 6, width, header_height], fill=accent)

    title_font = load_font(theme.font_bold, size=int(header_height * 0.42), bold=True)
    subtitle_font = load_font(theme.font_regular, size=int(header_height * 0.22))

    n = len(report.players)
    draw.text(
        (width * 0.03, header_height * 0.18),
        f"{report.tour.upper()} TOP {n}",
        font=title_font,
        fill=text_color,
    )
    date_str = f"{report.report_date:%A, %B} {report.report_date.day}, {report.report_date.year}"
    date_w = draw.textlength(date_str, font=subtitle_font)
    draw.text(
        (width * 0.97 - date_w, header_height * 0.58),
        date_str,
        font=subtitle_font,
        fill=subtext_color,
    )

    footer_height = int(height * 0.045)
    rows_top = header_height + int(height * 0.02)
    rows_bottom = height - footer_height - int(height * 0.02)
    rows_area_height = rows_bottom - rows_top
    row_gap = max(4, int(rows_area_height * 0.01))
    row_height = (rows_area_height - row_gap * (n - 1)) / n if n else rows_area_height

    rank_font = load_font(theme.font_bold, size=int(row_height * 0.42), bold=True)
    name_font = load_font(theme.font_bold, size=int(row_height * 0.34), bold=True)
    country_font = load_font(theme.font_regular, size=int(row_height * 0.2))
    points_font = load_font(theme.font_bold, size=int(row_height * 0.34), bold=True)
    points_label_font = load_font(theme.font_regular, size=int(row_height * 0.16))

    left_margin = int(width * 0.03)
    right_margin = int(width * 0.03)
    rank_col_w = int(width * 0.06)
    flag_col_w = int(width * 0.05)
    points_col_w = int(width * 0.14)
    movement_col_w = int(width * 0.06)

    for i, player in enumerate(report.players):
        row_top = rows_top + i * (row_height + row_gap)
        row_bottom = row_top + row_height
        row_mid = row_top + row_height / 2

        row_bg = panel if i % 2 == 0 else _blend(panel, bg, 0.35)
        draw.rounded_rectangle(
            [left_margin, row_top, width - right_margin, row_bottom],
            radius=int(row_height * 0.18),
            fill=row_bg,
        )

        rank_x = left_margin + rank_col_w / 2
        draw.text(
            (rank_x, row_mid),
            str(player.rank),
            font=rank_font,
            fill=accent,
            anchor="mm",
        )

        flag_x = left_margin + rank_col_w
        flag_h = int(row_height * 0.5)
        flag_img = render_flag(player.country_code, flag_h)
        img.paste(flag_img, (int(flag_x), int(row_mid - flag_h / 2)), flag_img)

        name_x = flag_x + flag_col_w
        max_name_width = width - right_margin - points_col_w - movement_col_w - name_x - 20
        country_name = get_country_info(player.country_code).display_name
        draw.text(
            (name_x, row_top + row_height * 0.22),
            fit_text(draw, player.name, name_font, max_name_width),
            font=name_font,
            fill=text_color,
            anchor="lm",
        )
        draw.text(
            (name_x, row_top + row_height * 0.72),
            country_name,
            font=country_font,
            fill=subtext_color,
            anchor="lm",
        )

        points_x = width - right_margin - movement_col_w - points_col_w
        draw.text(
            (points_x, row_top + row_height * 0.35),
            f"{player.points:,}",
            font=points_font,
            fill=text_color,
            anchor="lm",
        )
        draw.text(
            (points_x, row_top + row_height * 0.75),
            "RANKING POINTS",
            font=points_label_font,
            fill=subtext_color,
            anchor="lm",
        )

        movement_x = width - right_margin - movement_col_w / 2
        color = movement_color(player.movement, theme)
        draw_movement_glyph(draw, (movement_x, row_mid), player.movement, int(row_height * 0.22), color)

    footer_font = load_font(theme.font_regular, size=int(footer_height * 0.55))
    draw.text(
        (left_margin, height - footer_height / 2),
        profile_for(report.tour).attribution,
        font=footer_font,
        fill=subtext_color,
        anchor="lm",
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(output_path, "PNG")
    return output_path


def _blend(
    color_a: tuple[int, int, int], color_b: tuple[int, int, int], t: float
) -> tuple[int, int, int]:
    return tuple(
        int(a + (b - a) * t) for a, b in zip(color_a, color_b, strict=True)
    )  # type: ignore[return-value]
