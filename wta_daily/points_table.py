"""Deterministic lookup of official WTA ranking points by tournament
category, round reached, and (optionally) draw size.

Ranking points are **application data, never generated or guessed** - see
``data/wta_points_table.yaml`` for the actual numbers and their source.
This module only loads and looks values up in that file; nothing here (or
anywhere downstream, including any LLM-backed narration generator) invents
a points figure.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

#: Where the shipped points data lives - overridable via
#: ``TournamentStatusConfig.points_table_path`` for anyone who wants to
#: maintain their own copy (e.g. to add WTA 125 tournaments).
DEFAULT_POINTS_TABLE_PATH = Path("data/wta_points_table.yaml")


class PointsTable:
    """Wraps the parsed points-table data with a single, forgiving lookup method."""

    def __init__(self, data: dict[str, Any]) -> None:
        self._categories: dict[str, dict[str, Any]] = data.get("categories", {})
        self._default_draw_size: dict[str, int] = data.get("default_draw_size", {})

    def lookup(
        self, category: str | None, round_code: str | None, *, draw_size: int | None = None
    ) -> int | None:
        """Return the ranking points for reaching ``round_code`` at a
        tournament of this ``category``, or ``None`` if that combination
        isn't in the table (an unrecognized/unconfigured category, an
        unrecognized round code, or - deliberately - a category this table
        never covers, such as the Olympics, which awards no WTA ranking
        points at all).

        ``draw_size`` picks which of a category's configured draw-size
        variants to use (different-sized draws in the same category can
        award different points for the same early round - see the data
        file's comments); the *closest* configured size is used rather
        than requiring an exact match, since real draw sizes vary slightly
        tournament to tournament and this table only needs to be
        approximately right for those variants to still land on the
        correct schedule. Falls back to the category's documented default
        draw size when ``draw_size`` isn't given at all.
        """

        if not category or not round_code:
            return None
        category_key = category.strip().upper()
        category_data = self._categories.get(category_key)
        if not category_data:
            return None

        draw_sizes: dict[int, dict[str, int]] = category_data.get("draw_sizes", {})
        if not draw_sizes:
            return None

        target_size = draw_size or self._default_draw_size.get(category_key)
        if target_size is None:
            # No hint at all - just pick the largest configured variant,
            # consistent with wta_daily.rounds's own "assume the biggest,
            # most common draw" default.
            target_size = max(draw_sizes)

        closest_size = min(draw_sizes, key=lambda size: abs(size - target_size))
        return draw_sizes[closest_size].get(round_code)


def load_points_table(path: str | Path = DEFAULT_POINTS_TABLE_PATH) -> PointsTable:
    """Load a :class:`PointsTable` from a YAML file shaped like
    ``data/wta_points_table.yaml``. Raises normally (never silently
    swallowed) if the file is missing or malformed - callers that need
    graceful degradation (this feature must never abort the pipeline)
    should catch and log, exactly like every other optional-context
    lookup in this project."""

    with Path(path).open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    return PointsTable(data)
