"""Font loading with graceful fallbacks.

Custom fonts can be dropped into ``assets/fonts/`` and referenced from
``config.yaml`` (``graphics.theme.font_regular`` / ``font_bold``). If those
paths are not configured or not found, we fall back to the DejaVu Sans
family that ships with most Linux distributions (``fonts-dejavu-core``), and
finally to Pillow's built-in bitmap font so rendering never hard-fails just
because a font file is missing.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path

from PIL import ImageFont

logger = logging.getLogger(__name__)

_SYSTEM_FALLBACKS = {
    False: [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    ],
    True: [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    ],
}


@lru_cache(maxsize=64)
def load_font(
    path: str | None, size: int, bold: bool = False
) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates: list[str] = []
    if path:
        candidates.append(path)
    candidates.extend(_SYSTEM_FALLBACKS[bold])

    for candidate in candidates:
        if Path(candidate).exists():
            try:
                return ImageFont.truetype(candidate, size)
            except OSError as exc:  # pragma: no cover - defensive
                logger.warning("Could not load font %s: %s", candidate, exc)

    logger.warning("No TrueType font found (tried %s); using Pillow's default bitmap font.", candidates)
    return ImageFont.load_default(size=size)
