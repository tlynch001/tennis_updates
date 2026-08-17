"""Renders the YouTube thumbnail (``thumbnail.png``), fixed at 1280x720.

Deliberately much simpler and bolder than the leaderboard/player-card
graphics - a thumbnail has to read at a few hundred pixels wide in a
YouTube feed, so this is just 2-3 short, huge lines of text on a plain
background, reusing the project's existing theme colors/fonts
(:mod:`wta_daily.graphics.fonts`, ``GraphicsConfig.theme``) rather than a
separate visual language, but with none of the per-player detail a
leaderboard needs.

The tournament line is optional and never guessed - see
:mod:`wta_daily.tournament_context`, which only returns a name when at
least one tracked player's match confirms it that day.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from wta_daily.config import GraphicsConfig
from wta_daily.exceptions import GraphicsError
from wta_daily.graphics.fonts import load_font
from wta_daily.graphics.utils import hex_to_rgb
from wta_daily.models import DailyReport
from wta_daily.tournament_context import most_relevant_tournament

#: Fixed per YouTube's recommended thumbnail size - independent of
#: `GraphicsConfig.width`/`height`, which control the (much larger)
#: leaderboard/player-card canvas.
THUMBNAIL_WIDTH = 1280
THUMBNAIL_HEIGHT = 720


def render_thumbnail(report: DailyReport, output_path: Path, graphics: GraphicsConfig) -> Path:
    try:
        return _render(report, output_path, graphics)
    except Exception as exc:  # noqa: BLE001
        raise GraphicsError(f"Failed to render thumbnail for {report.report_date}: {exc}") from exc


def _render(report: DailyReport, output_path: Path, graphics: GraphicsConfig) -> Path:
    theme = graphics.theme
    width, height = THUMBNAIL_WIDTH, THUMBNAIL_HEIGHT
    bg = hex_to_rgb(theme.background_color)
    accent = hex_to_rgb(theme.accent_color)
    text_color = hex_to_rgb(theme.text_color)
    subtext_color = hex_to_rgb(theme.subtext_color)

    img = Image.new("RGB", (width, height), bg)
    draw = ImageDraw.Draw(img)

    # A single bold accent stripe along the bottom - enough to feel
    # "branded" without competing with the text for attention.
    stripe_h = int(height * 0.03)
    draw.rectangle([0, height - stripe_h, width, height], fill=accent)

    n = len(report.players)
    headline = f"{report.tour.upper()} TOP {n}"
    date_str = f"{report.report_date:%b} {report.report_date.day}, {report.report_date.year}".upper()
    tournament = most_relevant_tournament(report)
    tournament_text = tournament.upper() if tournament else None

    # Horizontal sizing is untouched: the headline is fit to the same
    # width budget/starting size as before. The tournament line - whose
    # length varies a lot more than the fixed-format headline/date - gets
    # the same width-fitting treatment so a long name (or a wide accented
    # one) never overflows the frame. Only the *vertical* rhythm between
    # lines changes below.
    max_text_width = width * 0.92
    headline_font = _fit_font_to_width(
        draw, headline, theme.font_bold, max_text_width, start_size=int(height * 0.26)
    )
    date_font = load_font(theme.font_bold, size=int(height * 0.11), bold=True)
    tournament_font = (
        _fit_font_to_width(
            draw, tournament_text, theme.font_bold, max_text_width, start_size=int(height * 0.09)
        )
        if tournament_text
        else None
    )

    # Two deliberately *different*, generous gaps rather than one uniform
    # spacing - the headline is the dominant element and the date is
    # secondary, so that break gets the most air; the date-to-tournament
    # break (two secondary/tertiary lines) gets a bit less, but still
    # clearly more than the old single 0.035 value ever gave either gap.
    # This is what turns three tightly-stacked lines into a real visual
    # hierarchy instead of one dense block - see the module docstring.
    gap_after_headline = height * 0.09
    gap_after_date = height * 0.065

    headline_bbox = draw.textbbox((0, 0), headline, font=headline_font)
    headline_h = headline_bbox[3] - headline_bbox[1]
    date_bbox = draw.textbbox((0, 0), date_str, font=date_font)
    date_h = date_bbox[3] - date_bbox[1]

    block_h = headline_h + gap_after_headline + date_h
    if tournament_text and tournament_font is not None:
        tournament_bbox = draw.textbbox((0, 0), tournament_text, font=tournament_font)
        block_h += gap_after_date + (tournament_bbox[3] - tournament_bbox[1])

    top = (height - stripe_h - block_h) / 2
    cx = width / 2

    draw.text((cx, top), headline, font=headline_font, fill=text_color, anchor="ma")
    top += headline_h + gap_after_headline
    draw.text((cx, top), date_str, font=date_font, fill=accent, anchor="ma")
    top += date_h + gap_after_date
    if tournament_text and tournament_font is not None:
        draw.text((cx, top), tournament_text, font=tournament_font, fill=subtext_color, anchor="ma")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(output_path, "PNG")
    return output_path


def _fit_font_to_width(
    draw: ImageDraw.ImageDraw, text: str, font_path: str | None, max_width: float, *, start_size: int
) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Shrink the headline font until it fits within ``max_width`` - a
    longer tour name or a larger top_n (e.g. "TOP 25") must not overflow
    the frame at thumbnail size."""

    size = start_size
    while size > 20:
        font = load_font(font_path, size=size, bold=True)
        if draw.textlength(text, font=font) <= max_width:
            return font
        size -= 4
    return load_font(font_path, size=max(size, 20), bold=True)
