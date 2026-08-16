"""Orchestrates one full daily run.

:class:`DailyPipeline` is intentionally the only place in the codebase that
knows the *order* of steps (rankings -> movement -> matches -> report ->
script -> graphics -> optional narration/video/git). Every step itself is
implemented behind a plugin interface (see :mod:`wta_daily.plugins.base`),
so the pipeline stays short and easy to read even as more phases are added.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from pathlib import Path

from wta_daily.config import AppConfig
from wta_daily.exceptions import (
    DataProviderError,
    GraphicsError,
    PlayerDataError,
    VideoAssemblyError,
    VoiceSynthesisError,
)
from wta_daily.git_automation import GitAutomationError, commit_and_push
from wta_daily.models import DailyReport, MatchResult, PlayerRanking, PlayerReport
from wta_daily.movement import compute_movement, previous_ranks_by_player
from wta_daily.persistence.report_store import DailyOutputStore
from wta_daily.persistence.snapshot_store import RankingsSnapshotStore
from wta_daily.plugins.registry import (
    graphics_registry,
    load_builtin_plugins,
    matches_registry,
    rankings_registry,
    script_registry,
    video_registry,
    voice_registry,
)

logger = logging.getLogger(__name__)


class DailyPipeline:
    """Runs the full Phase 1 (+ optional Phase 2) daily workflow."""

    def __init__(self, config: AppConfig, repo_root: Path | None = None) -> None:
        load_builtin_plugins()
        self._config = config
        self._repo_root = repo_root or Path.cwd()
        self._snapshot_store = RankingsSnapshotStore(config.data_dir)

        self._rankings_provider = rankings_registry.create(
            config.rankings_provider.name, network=config.network, **config.rankings_provider.options
        )
        self._match_provider = matches_registry.create(
            config.match_provider.name, network=config.network, **config.match_provider.options
        )
        self._script_generator = script_registry.create(
            config.script.generator, script_config=config.script
        )
        self._graphics_renderer = graphics_registry.create(
            config.graphics.renderer, graphics_config=config.graphics
        )

    def run(self, report_date: date | None = None) -> DailyReport:
        report_date = report_date or date.today()
        logger.info("=== WTA Daily pipeline starting for %s ===", report_date.isoformat())

        report = self._build_report(report_date)

        store = DailyOutputStore(self._config.output_dir, report_date)
        store.ensure_dirs()
        store.write_report(report)
        logger.info("Wrote %s", store.report_path)

        logger.info("Generating narration script...")
        script_text = self._script_generator.generate(report)
        store.write_script(script_text)
        logger.info("Wrote %s", store.script_path)

        logger.info("Generating graphics...")
        self._render_graphics(report, store)
        store.write_report(report)  # persist any graphics errors recorded above

        if self._config.voice.enabled:
            self._synthesize_narration(store, report)

        if self._config.video.enabled:
            self._assemble_video(report, store)

        if self._config.git.auto_commit:
            self._commit_to_git(store, report_date)

        if report.errors:
            logger.warning(
                "Finished with %d non-fatal error(s). See report.json 'errors' for details.",
                len(report.errors),
            )
        else:
            logger.info("Finished successfully.")
        return report

    def _build_report(self, report_date: date) -> DailyReport:
        logger.info("Downloading rankings...")
        rankings: list[PlayerRanking] = self._rankings_provider.get_top_n(self._config.top_n)
        logger.info("Retrieved %d rankings.", len(rankings))

        previous = self._snapshot_store.get_previous_snapshot(report_date, self._config.tour)
        has_previous_snapshot = previous is not None
        previous_ranks = previous_ranks_by_player(previous[1] if previous else None)
        if previous is None:
            logger.info(
                "No previous snapshot found; this looks like the first run for this tour. "
                "Movement will be reported as 'unknown' rather than 'new' for every player."
            )
        else:
            logger.info("Comparing against snapshot from %s.", previous[0].isoformat())

        match_target_date = report_date - timedelta(days=self._config.match_target_date_offset_days)
        logger.info("Downloading matches completed on %s...", match_target_date.isoformat())
        matches_by_player, batch_error = self._safe_get_matches_for_date(rankings, match_target_date)
        if batch_error:
            logger.warning(
                "Could not confirm match data for %s - every player below will show "
                "played: false with a match_error rather than a guess.",
                match_target_date.isoformat(),
            )

        players: list[PlayerReport] = []
        errors: list[str] = []
        if batch_error:
            errors.append(batch_error)
        for ranking in rankings:
            previous_rank = previous_ranks.get(ranking.player_id)
            movement = compute_movement(
                ranking.rank, previous_rank, has_previous_snapshot=has_previous_snapshot
            )
            match = matches_by_player.get(ranking.player_id)
            if match is None:
                logger.info("%s did not play on %s.", ranking.name, match_target_date.isoformat())
            players.append(
                PlayerReport(
                    rank=ranking.rank,
                    name=ranking.name,
                    player_id=ranking.player_id,
                    country_code=ranking.country_code,
                    points=ranking.points,
                    movement=movement,
                    previous_rank=previous_rank,
                    match=match,
                    match_error=batch_error,
                )
            )

        self._snapshot_store.save_snapshot(report_date, self._config.tour, rankings)
        return DailyReport(
            report_date=report_date,
            tour=self._config.tour,
            players=players,
            errors=errors,
            match_target_date=match_target_date,
        )

    def _safe_get_matches_for_date(
        self, rankings: list[PlayerRanking], target_date: date
    ) -> tuple[dict[str, MatchResult], str | None]:
        """Batch match lookup for every ranked player, never letting a failure abort the run.

        A failure here means the whole lookup for ``target_date`` could not
        be confirmed (e.g. a network outage) - every player is reported as
        ``played: false`` *with* the returned error message attached, which
        is different from a player who genuinely didn't play (no error).
        See ``PlayerReport.match_error``.
        """

        try:
            return self._match_provider.get_matches_for_date(rankings, target_date), None
        except (PlayerDataError, DataProviderError) as exc:
            logger.error("Match lookup failed for %s: %s", target_date, exc)
            return {}, str(exc)
        except Exception as exc:  # noqa: BLE001 - this step must never abort the run
            logger.exception("Unexpected error fetching matches for %s", target_date)
            return {}, f"Unexpected error fetching matches for {target_date}: {exc}"

    def _render_graphics(self, report: DailyReport, store: DailyOutputStore) -> None:
        try:
            self._graphics_renderer.render_leaderboard(report, store.leaderboard_path)
            logger.info("Rendered %s", store.leaderboard_path)
        except GraphicsError as exc:
            logger.error("Leaderboard rendering failed: %s", exc)
            report.errors.append(str(exc))

        for player in report.players:
            try:
                self._graphics_renderer.render_player_card(
                    player, store.player_cards_dir, top_n=self._config.top_n
                )
            except GraphicsError as exc:
                logger.error("Player card rendering failed for %s: %s", player.name, exc)
                report.errors.append(str(exc))

    def _synthesize_narration(self, store: DailyOutputStore, report: DailyReport) -> None:
        logger.info("Creating narration...")
        try:
            synthesizer = voice_registry.create(self._config.voice.provider, voice_config=self._config.voice)
            synthesizer.synthesize(store.script_path, store.narration_path)
            logger.info("Wrote %s", store.narration_path)
        except VoiceSynthesisError as exc:
            logger.error("Voice synthesis failed: %s", exc)
            report.errors.append(str(exc))

    def _assemble_video(self, report: DailyReport, store: DailyOutputStore) -> None:
        logger.info("Assembling video...")
        try:
            assembler = video_registry.create(self._config.video.assembler, video_config=self._config.video)
            assembler.assemble(report, store.root)
            logger.info("Wrote %s", store.video_path)
        except VideoAssemblyError as exc:
            logger.error("Video assembly failed: %s", exc)
            report.errors.append(str(exc))

    def _commit_to_git(self, store: DailyOutputStore, report_date: date) -> None:
        logger.info("Committing to git...")
        try:
            paths = [
                store.root,
                self._config.data_dir / "rankings-history.json",
                self._config.data_dir / "players.json",
            ]
            commit_and_push(self._repo_root, paths, report_date, self._config.git)
        except GitAutomationError as exc:
            logger.error("Git automation failed: %s", exc)
