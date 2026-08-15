"""Small drawing helpers shared by the leaderboard and player card renderers."""

from __future__ import annotations

from PIL import ImageDraw, ImageFont

from wta_daily.models import Movement


def hex_to_rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    if len(value) == 3:
        value = "".join(ch * 2 for ch in value)
    return tuple(int(value[i : i + 2], 16) for i in range(0, 6, 2))  # type: ignore[return-value]


def movement_color(movement: Movement, theme) -> tuple[int, int, int]:  # noqa: ANN001
    return {
        Movement.UP: hex_to_rgb(theme.up_color),
        Movement.DOWN: hex_to_rgb(theme.down_color),
        Movement.SAME: hex_to_rgb(theme.same_color),
        Movement.NEW: hex_to_rgb(theme.accent_color),
        Movement.UNKNOWN: hex_to_rgb(theme.same_color),
    }[movement]


def draw_movement_glyph(
    draw: ImageDraw.ImageDraw,
    center: tuple[float, float],
    movement: Movement,
    size: int,
    color: tuple[int, int, int],
) -> None:
    """Draw an up/down triangle, a dash for SAME, a ring for NEW, or a filled
    dot for UNKNOWN (no previous snapshot to compare against at all)."""

    x, y = center
    half = size / 2
    if movement == Movement.UP:
        draw.polygon([(x, y - half), (x - half, y + half), (x + half, y + half)], fill=color)
    elif movement == Movement.DOWN:
        draw.polygon([(x, y + half), (x - half, y - half), (x + half, y - half)], fill=color)
    elif movement == Movement.SAME:
        thickness = max(2, size // 6)
        draw.rectangle([x - half, y - thickness / 2, x + half, y + thickness / 2], fill=color)
    elif movement == Movement.UNKNOWN:
        radius = half * 0.6
        draw.ellipse([x - radius, y - radius, x + radius, y + radius], fill=color)
    else:  # NEW
        draw.ellipse([x - half, y - half, x + half, y + half], outline=color, width=max(2, size // 8))


def movement_label(movement: Movement) -> str:
    return {
        Movement.UP: "UP",
        Movement.DOWN: "DOWN",
        Movement.SAME: "—",
        Movement.NEW: "NEW",
        Movement.UNKNOWN: "N/A",
    }[movement]


def fit_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    max_width: int,
) -> str:
    """Truncate ``text`` with an ellipsis if it would overflow ``max_width``."""

    if draw.textlength(text, font=font) <= max_width:
        return text
    truncated = text
    while truncated and draw.textlength(truncated + "…", font=font) > max_width:
        truncated = truncated[:-1]
    return truncated + "…" if truncated else "…"
