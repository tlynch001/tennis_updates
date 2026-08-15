"""Renders one full-screen player card graphic (``player_cards/<rank>.png``)."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

from wta_daily.config import GraphicsConfig
from wta_daily.countries import get_country_info
from wta_daily.exceptions import GraphicsError
from wta_daily.graphics.flags import render_flag
from wta_daily.graphics.fonts import load_font
from wta_daily.graphics.utils import fit_text, hex_to_rgb, movement_color
from wta_daily.models import Movement, PlayerReport

_MOVEMENT_HEADLINE = {
    Movement.UP: "MOVED UP",
    Movement.DOWN: "MOVED DOWN",
    Movement.SAME: "STAYED AT #{rank}",
    Movement.NEW: "NEW IN THE TOP {n}",
    # No previous snapshot exists to compare against - state the fact
    # neutrally rather than implying the player just arrived.
    Movement.UNKNOWN: "CURRENTLY #{rank}",
}


def render_player_card(
    player: PlayerReport, output_path: Path, graphics: GraphicsConfig, *, top_n: int
) -> Path:
    try:
        return _render(player, output_path, graphics, top_n=top_n)
    except Exception as exc:  # noqa: BLE001
        raise GraphicsError(f"Failed to render player card for {player.name}: {exc}") from exc


def _render(
    player: PlayerReport, output_path: Path, graphics: GraphicsConfig, *, top_n: int
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

    draw.rectangle([0, 0, int(width * 0.012), height], fill=accent)

    rank_font = load_font(theme.font_bold, size=int(height * 0.2), bold=True)
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

    rank_text = f"#{player.rank}"
    rank_y = height * 0.05
    rank_bbox = draw.textbbox((margin, rank_y), rank_text, font=rank_font, anchor="la")
    draw.text((margin, rank_y), rank_text, font=rank_font, fill=accent, anchor="la")

    name_top = rank_bbox[3] + gap
    name_text = fit_text(draw, player.name, name_font, width - margin * 2 - int(height * 0.12))
    name_bbox = draw.textbbox((margin, name_top), name_text, font=name_font, anchor="la")

    flag_h = int(name_bbox[3] - name_bbox[1])
    flag_img = render_flag(player.country_code, max(flag_h, 1))
    img.paste(flag_img, (margin, int(name_top)), flag_img)

    name_x = margin + flag_img.width + int(width * 0.02)
    draw.text((name_x, name_top), name_text, font=name_font, fill=text_color, anchor="la")
    name_bbox = draw.textbbox((name_x, name_top), name_text, font=name_font, anchor="la")

    country_name = get_country_info(player.country_code).display_name
    country_top = name_bbox[3] + gap * 0.4
    draw.text(
        (name_x, country_top), country_name, font=country_font, fill=subtext_color, anchor="la"
    )
    country_bbox = draw.textbbox((name_x, country_top), country_name, font=country_font, anchor="la")

    movement_headline = _MOVEMENT_HEADLINE[player.movement].format(rank=player.rank, n=top_n)
    if player.movement == Movement.UP and player.previous_rank:
        movement_headline = f"UP FROM #{player.previous_rank}"
    elif player.movement == Movement.DOWN and player.previous_rank:
        movement_headline = f"DOWN FROM #{player.previous_rank}"
    badge_color = movement_color(player.movement, theme)
    badge_top = country_bbox[3] + gap
    badge_w = draw.textlength(movement_headline, font=badge_font) + width * 0.03
    badge_h = height * 0.05
    draw.rounded_rectangle(
        [name_x, badge_top, name_x + badge_w, badge_top + badge_h],
        radius=int(badge_h * 0.3),
        outline=badge_color,
        width=3,
    )
    draw.text(
        (name_x + badge_w / 2, badge_top + badge_h / 2),
        movement_headline,
        font=badge_font,
        fill=badge_color,
        anchor="mm",
    )

    points_right = width - margin
    points_bbox = draw.textbbox(
        (points_right, height * 0.06), f"{player.points:,}", font=points_font, anchor="ra"
    )
    draw.text(
        (points_right, height * 0.06),
        f"{player.points:,}",
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

    content_bottom = max(badge_top + badge_h, points_bbox[3] + height * 0.06)
    panel_top = max(height * 0.56, content_bottom + height * 0.05)
    draw.rounded_rectangle(
        [margin, panel_top, width - margin, height - height * 0.08],
        radius=int(height * 0.02),
        fill=panel,
    )

    section_label = "MOST RECENT MATCH"
    draw.text(
        (margin * 1.6, panel_top + height * 0.04),
        section_label,
        font=section_font,
        fill=subtext_color,
        anchor="la",
    )

    if player.match is not None:
        outcome = "WON" if player.match.won else "LOST"
        outcome_color = hex_to_rgb(theme.up_color) if player.match.won else hex_to_rgb(theme.down_color)
        draw.text(
            (margin * 1.6, panel_top + height * 0.10),
            f"{outcome} vs {player.match.opponent}",
            font=result_font,
            fill=outcome_color,
            anchor="la",
        )
        detail_line = f"{player.match.score}    |    {player.match.tournament} \u2014 {player.match.round}"
        draw.text(
            (margin * 1.6, panel_top + height * 0.20),
            detail_line,
            font=detail_font,
            fill=text_color,
            anchor="la",
        )
        match_date = player.match.match_date
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
        message = "No completed match to report today."
        if player.match_error:
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
