"""Render Unicode flag emoji as cropped RGBA images for compositing.

See :mod:`wta_daily.countries` for why Unicode emoji (rather than downloaded
flag images) are used. Color emoji fonts (e.g. Noto Color Emoji) are usually
bitmap "strike" fonts with a single fixed pixel size, so we render at that
native size, crop to the glyph's tight bounding box, and let the caller
resize as needed.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from wta_daily.countries import get_country_info

logger = logging.getLogger(__name__)

_EMOJI_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf",
    "/usr/share/fonts/google-noto-color-emoji-fonts/NotoColorEmoji.ttf",
]
_STRIKE_SIZE = 109


@lru_cache(maxsize=1)
def _emoji_font() -> ImageFont.FreeTypeFont | None:
    for candidate in _EMOJI_FONT_CANDIDATES:
        if Path(candidate).exists():
            try:
                return ImageFont.truetype(candidate, _STRIKE_SIZE)
            except OSError as exc:  # pragma: no cover - defensive
                logger.warning("Could not load emoji font %s: %s", candidate, exc)
    logger.warning(
        "No color emoji font found; country flags will fall back to text badges. "
        "Install 'fonts-noto-color-emoji' for real flag glyphs."
    )
    return None


@lru_cache(maxsize=256)
def render_flag(country_code: str, target_height: int) -> Image.Image:
    """Return an RGBA image of the flag for ``country_code``, ``target_height`` px tall."""

    info = get_country_info(country_code)
    font = _emoji_font()
    if font is not None:
        canvas = Image.new("RGBA", (_STRIKE_SIZE * 2, _STRIKE_SIZE * 2), (0, 0, 0, 0))
        draw = ImageDraw.Draw(canvas)
        try:
            draw.text((0, 0), info.flag_emoji, font=font, embedded_color=True)
            bbox = canvas.getbbox()
            if bbox is not None:
                cropped = canvas.crop(bbox)
                ratio = target_height / cropped.height
                target_width = max(1, int(round(cropped.width * ratio)))
                return cropped.resize((target_width, target_height), Image.Resampling.LANCZOS)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Failed to render flag emoji for %s: %s", country_code, exc)

    return _text_badge_fallback(info.code, target_height)


def _text_badge_fallback(code: str, target_height: int) -> Image.Image:
    """A plain badge with the 3-letter country code, used if no emoji font exists."""

    from wta_daily.graphics.fonts import load_font

    width = int(target_height * 1.8)
    img = Image.new("RGBA", (width, target_height), (60, 66, 82, 255))
    draw = ImageDraw.Draw(img)
    font = load_font(None, size=int(target_height * 0.55), bold=True)
    text = code[:3]
    bbox = draw.textbbox((0, 0), text, font=font)
    text_w, text_h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text(
        ((width - text_w) / 2 - bbox[0], (target_height - text_h) / 2 - bbox[1]),
        text,
        font=font,
        fill=(245, 247, 250, 255),
    )
    return img
