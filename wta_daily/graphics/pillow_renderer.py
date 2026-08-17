"""The default, Pillow-backed :class:`~wta_daily.plugins.base.GraphicsRenderer`."""

from __future__ import annotations

from pathlib import Path

from wta_daily.config import GraphicsConfig
from wta_daily.graphics.featured_card import render_featured_card
from wta_daily.graphics.leaderboard import render_leaderboard
from wta_daily.graphics.player_card import render_player_card
from wta_daily.graphics.thumbnail import render_thumbnail
from wta_daily.models import DailyReport, FeaturedPlayerReport, PlayerReport
from wta_daily.plugins.base import GraphicsRenderer
from wta_daily.plugins.registry import graphics_registry


@graphics_registry.register("pillow")
class PillowGraphicsRenderer(GraphicsRenderer):
    """Renders the leaderboard, player cards, featured card, and thumbnail
    using Pillow."""

    def __init__(self, graphics_config: GraphicsConfig | None = None, **_ignored: object) -> None:
        self._config = graphics_config or GraphicsConfig()

    def render_leaderboard(self, report: DailyReport, output_path: Path) -> Path:
        return render_leaderboard(report, output_path, self._config)

    def render_player_card(self, player: PlayerReport, output_dir: Path, *, top_n: int) -> Path:
        output_path = output_dir / f"{player.rank:02d}.png"
        return render_player_card(player, output_path, self._config, top_n=top_n)

    def render_featured_card(
        self, featured: FeaturedPlayerReport, output_path: Path, *, top_n: int
    ) -> Path:
        return render_featured_card(featured, output_path, self._config, top_n=top_n)

    def render_thumbnail(self, report: DailyReport, output_path: Path) -> Path:
        return render_thumbnail(report, output_path, self._config)
