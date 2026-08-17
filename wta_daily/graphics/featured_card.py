"""Renders the featured-player spotlight graphic (``featured_player.png``).

Deliberately built from the same visual language as
:mod:`wta_daily.graphics.player_card` (same fonts, colors, margins, flag
rendering, movement-badge wording, and "match panel" layout - see the
shared helpers in :mod:`wta_daily.graphics.utils`) so it reads as part of
the same show, not a bolted-on separate design. The one deliberate visual
difference is the headline: a normal card leads with a giant ``#{rank}``;
this card leads with a "FEATURED PLAYER" pill instead, so it's immediately
recognizable as a bonus segment rather than an eleventh Top N entry - see
the module docstring in :mod:`wta_daily.config` (``FeaturedPlayerConfig``)
for why she's tracked separately from the official group in the first
place.

Every fact drawn here comes straight from the
:class:`~wta_daily.models.FeaturedPlayerReport` already built by the
pipeline (rank, points, movement, match) - this module never fetches
anything itself and never fabricates a fact that wasn't available; a
``None``/``rank_error`` field is rendered as an honest "unavailable"
message instead.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

from wta_daily.config import GraphicsConfig
from wta_daily.countries import get_country_info
from wta_daily.exceptions import GraphicsError
from wta_daily.graphics.flags import render_flag
from wta_daily.graphics.fonts import load_font
from wta_daily.graphics.utils import fit_text, hex_to_rgb, movement_headline_text
from wta_daily.models import FeaturedPlayerReport, Movement

#: The badge that replaces a normal card's giant rank number - the main
#: visual cue that this is a bonus segment, not an eleventh Top N entry.
_SPOTLIGHT_LABEL = "FEATURED PLAYER"


def render_featured_card(
    featured: FeaturedPlayerReport, output_path: Path, graphics: GraphicsConfig, *, top_n: int
) -> Path:
    try:
        return _render(featured, output_path, graphics, top_n=top_n)
    except Exception as exc:  # noqa: BLE001
        raise GraphicsError(f"Failed to render featured-player card for {featured.name}: {exc}") from exc


def _render(
    featured: FeaturedPlayerReport, output_path: Path, graphics: GraphicsConfig, *, top_n: int
) -> Path:
    theme = graphics.theme
    width, height = graphics.width, graphics.height
    bg = hex_to_rgb(theme.background_color)
    panel = hex_to_rgb(theme.panel_color)
    accent = hex_to_rgb(theme.accent_color)
    text_color = hex_to_rgb(theme.text_color)
    subtext_color = hex_to_rgb(theme.subtext_color)

    img = Image.new("RGB", (width, height), bg)
    draw = ImageDraw.Draw(img)

    # Same left accent stripe as a normal player card, for visual continuity.
    draw.rectangle([0, 0, int(width * 0.012), height], fill=accent)

    spotlight_font = load_font(theme.font_bold, size=int(height * 0.055), bold=True)
    name_font = load_font(theme.font_bold, size=int(height * 0.08), bold=True)
    country_font = load_font(theme.font_regular, size=int(height * 0.032))
    points_font = load_font(theme.font_bold, size=int(height * 0.14), bold=True)
    points_label_font = load_font(theme.font_regular, size=int(height * 0.035))
    badge_font = load_font(theme.font_bold, size=int(height * 0.04), bold=True)
    section_font = load_font(theme.font_bold, size=int(height * 0.035), bold=True)
    result_font = load_font(theme.font_bold, size=int(height * 0.06), bold=True)
    detail_font = load_font(theme.font_regular, size=int(height * 0.04))

    margin = int(width * 0.06)
    gap = height * 0.02

    # --- Headline: a filled "FEATURED PLAYER" pill instead of a rank number ---
    spotlight_top = height * 0.05
    spotlight_w = draw.textlength(_SPOTLIGHT_LABEL, font=spotlight_font) + width * 0.035
    spotlight_h = height * 0.07
    draw.rounded_rectangle(
        [margin, spotlight_top, margin + spotlight_w, spotlight_top + spotlight_h],
        radius=int(spotlight_h * 0.25),
        fill=accent,
    )
    draw.text(
        (margin + spotlight_w / 2, spotlight_top + spotlight_h / 2),
        _SPOTLIGHT_LABEL,
        font=spotlight_font,
        fill=bg,
        anchor="mm",
    )

    name_top = spotlight_top + spotlight_h + gap
    name_text = fit_text(draw, featured.name, name_font, width - margin * 2 - int(height * 0.12))
    name_bbox = draw.textbbox((margin, name_top), name_text, font=name_font, anchor="la")

    flag_h = int(name_bbox[3] - name_bbox[1])
    flag_img = render_flag(featured.country_code, max(flag_h, 1))
    img.paste(flag_img, (margin, int(name_top)), flag_img)

    name_x = margin + flag_img.width + int(width * 0.02)
    draw.text((name_x, name_top), name_text, font=name_font, fill=text_color, anchor="la")
    name_bbox = draw.textbbox((name_x, name_top), name_text, font=name_font, anchor="la")

    country_name = get_country_info(featured.country_code).display_name if featured.country_code else ""
    country_top = name_bbox[3] + gap * 0.4
    if country_name:
        draw.text(
            (name_x, country_top), country_name, font=country_font, fill=subtext_color, anchor="la"
        )
    country_bbox = draw.textbbox((name_x, country_top), country_name or " ", font=country_font, anchor="la")

    # --- Ranking status badge: honest, never fabricated ---
    if featured.rank is not None:
        status_text = movement_headline_text(
            featured.movement or Movement.UNKNOWN,
            rank=featured.rank,
            top_n=top_n,
            previous_rank=featured.previous_rank,
        )
        if featured.rank > top_n:
            status_text = f"{status_text}  \u2022  OUTSIDE THE TOP {top_n}"
        badge_color = accent
    else:
        status_text = "RANKING UNAVAILABLE TODAY"
        badge_color = subtext_color
    badge_top = country_bbox[3] + gap
    badge_w = draw.textlength(status_text, font=badge_font) + width * 0.03
    badge_h = height * 0.05
    draw.rounded_rectangle(
        [name_x, badge_top, name_x + badge_w, badge_top + badge_h],
        radius=int(badge_h * 0.3),
        outline=badge_color,
        width=3,
    )
    draw.text(
        (name_x + badge_w / 2, badge_top + badge_h / 2),
        status_text,
        font=badge_font,
        fill=badge_color,
        anchor="mm",
    )

    content_bottom = badge_top + badge_h
    if featured.points is not None:
        points_right = width - margin
        points_bbox = draw.textbbox(
            (points_right, height * 0.06), f"{featured.points:,}", font=points_font, anchor="ra"
        )
        draw.text(
            (points_right, height * 0.06),
            f"{featured.points:,}",
            font=points_font,
            fill=text_color,
            anchor="ra",
        )
        draw.text(
            (points_right, points_bbox[3] + gap * 0.3),
            "RANKING POINTS",
            font=points_label_font,
            fill=subtext_color,
            anchor="ra",
        )
        content_bottom = max(content_bottom, points_bbox[3] + height * 0.06)

    panel_top = max(height * 0.56, content_bottom + height * 0.05)
    draw.rounded_rectangle(
        [margin, panel_top, width - margin, height - height * 0.08],
        radius=int(height * 0.02),
        fill=panel,
    )

    # Same section label as a normal card - "yesterday" matches the
    # default match_target_date_offset_days=1 (see player_card.py's
    # identical note).
    draw.text(
        (margin * 1.6, panel_top + height * 0.04),
        "YESTERDAY'S MATCH",
        font=section_font,
        fill=subtext_color,
        anchor="la",
    )

    if featured.rank is None:
        draw.text(
            (margin * 1.6, panel_top + height * 0.10),
            "Ranking and match data unavailable today.",
            font=result_font,
            fill=subtext_color,
            anchor="la",
        )
    elif featured.match is not None:
        outcome = "WON" if featured.match.won else "LOST"
        outcome_color = hex_to_rgb(theme.up_color) if featured.match.won else hex_to_rgb(theme.down_color)
        draw.text(
            (margin * 1.6, panel_top + height * 0.10),
            f"{outcome} vs {featured.match.opponent}",
            font=result_font,
            fill=outcome_color,
            anchor="la",
        )
        detail_line = (
            f"{featured.match.score}    |    {featured.match.tournament} \u2014 {featured.match.round}"
        )
        draw.text(
            (margin * 1.6, panel_top + height * 0.20),
            detail_line,
            font=detail_font,
            fill=text_color,
            anchor="la",
        )
        match_date = featured.match.match_date
        date_label = (
            f"{match_date:%B} {match_date.day}, {match_date.year}" if match_date else "Date unconfirmed"
        )
        draw.text(
            (margin * 1.6, panel_top + height * 0.27),
            date_label,
            font=detail_font,
            fill=subtext_color,
            anchor="la",
        )
    else:
        message = "Did not play yesterday."
        if featured.match_error:
            message = "Match data unavailable today."
        draw.text(
            (margin * 1.6, panel_top + height * 0.10),
            message,
            font=result_font,
            fill=subtext_color,
            anchor="la",
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(output_path, "PNG")
    return output_path
