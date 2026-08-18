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

from wta_daily import api_usage
from wta_daily.config import AppConfig
from wta_daily.exceptions import (
    DataProviderError,
    GraphicsError,
    PlayerDataError,
    VideoAssemblyError,
    VoiceSynthesisError,
)
from wta_daily.git_automation import GitAutomationError, commit_and_push
from wta_daily.models import (
    DailyReport,
    FeaturedPlayerReport,
    MatchResult,
    PlayerRanking,
    PlayerReport,
)
from wta_daily.movement import (
    compute_movement,
    is_same_official_ranking_list,
    previous_ranks_by_player,
    resolve_official_ranking,
)
from wta_daily.persistence.report_store import DailyOutputStore
from wta_daily.persistence.snapshot_store import RankingsSnapshotStore
from wta_daily.persistence.youtube_upload_store import YouTubeUploadStore
from wta_daily.plugins.registry import (
    graphics_registry,
    load_builtin_plugins,
    matches_registry,
    rankings_registry,
    script_registry,
    video_registry,
    voice_registry,
)
from wta_daily.title import generate_title
from wta_daily.youtube.uploader import publish_report
from wta_daily.youtube_description import generate_description

logger = logging.getLogger(__name__)


class DailyPipeline:
    """Runs the full Phase 1 (+ optional Phase 2) daily workflow."""

    def __init__(self, config: AppConfig, repo_root: Path | None = None) -> None:
        load_builtin_plugins()
        self._config = config
        self._repo_root = repo_root or Path.cwd()
        self._snapshot_store = RankingsSnapshotStore(config.data_dir)
        #: The full rankings response from the most recent run, before it was
        #: sliced down to `top_n` for the report - e.g. Top 25 when `top_n`
        #: is 10 and `rankings_pool_size` is 25 (see AppConfig). Exposed so a
        #: future featured-player lookup for someone just outside the
        #: tracked Top N can reuse this instead of firing a brand new
        #: rankings request for one player.
        self.last_rankings_pool: list[PlayerRanking] = []

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
        api_usage.reset()

        report = self._build_report(report_date)

        store = DailyOutputStore(self._config.output_dir, report_date)
        store.ensure_dirs()
        store.write_report(report)
        logger.info("Wrote %s", store.report_path)

        logger.info("Generating narration script...")
        script_text = self._script_generator.generate(report)
        store.write_script(script_text)
        logger.info("Wrote %s", store.script_path)

        title = generate_title(report)
        store.write_title(title)
        logger.info("Wrote %s", store.title_path)

        logger.info("Generating graphics...")
        self._render_graphics(report, store)
        self._render_featured_card(report, store)
        if self._config.publishing.thumbnail_enabled:
            self._generate_thumbnail(report, store)
        if self._config.publishing.description_enabled:
            self._generate_youtube_description(report, store)
        store.write_report(report)  # persist any errors recorded above

        if self._config.voice.enabled:
            self._synthesize_narration(store, report)

        if self._config.video.enabled:
            self._assemble_video(report, store)

        self._publish_to_youtube(report, store)

        if self._config.git.auto_commit:
            self._commit_to_git(store, report_date)

        if report.errors:
            logger.warning(
                "Finished with %d non-fatal error(s). See report.json 'errors' for details.",
                len(report.errors),
            )
        else:
            logger.info("Finished successfully.")
        api_usage.log_summary()
        return report

    def _build_report(self, report_date: date) -> DailyReport:
        # Fetch a somewhat larger pool than just `top_n` (e.g. Top 25 for a
        # Top 10 report) in the *same* single rankings request, rather than
        # a separate one - this is what lets a future featured-player
        # lookup for someone just outside the tracked group reuse
        # `self.last_rankings_pool` instead of firing its own request. The
        # report itself is still built from exactly `top_n` players; nothing
        # about what gets reported changes.
        pool_size = max(self._config.top_n, self._config.rankings_pool_size)
        logger.info("Downloading rankings (top %d)...", pool_size)
        pool: list[PlayerRanking] = self._rankings_provider.get_top_n(pool_size)
        self.last_rankings_pool = pool
        rankings: list[PlayerRanking] = pool[: self._config.top_n]
        logger.info(
            "Retrieved %d official ranked players (%d tracked for this report).", len(pool), len(rankings)
        )

        # The publication date of the official WTA ranking list this whole
        # run is based on (see PlayerRanking.ranking_date's docstring) -
        # identical across every entry in `pool`, so any tracked player's
        # value represents the whole list. `None` for a provider that
        # doesn't expose one (e.g. the offline `sample` fixture).
        current_ranking_date = rankings[0].ranking_date if rankings else None
        if current_ranking_date is not None:
            logger.info("Using official WTA ranking dated %s", current_ranking_date.isoformat())

        previous = self._snapshot_store.get_previous_snapshot(report_date, self._config.tour)
        has_previous_snapshot = previous is not None
        previous_rankings = previous[1] if previous else None
        previous_ranks = previous_ranks_by_player(previous_rankings)
        previous_ranking_date = previous_rankings[0].ranking_date if previous_rankings else None
        # The single guarantee this whole feature exists for: a match
        # result must never be able to make the app report a ranking
        # change - only an actual new official ranking publication can.
        # See wta_daily.movement.is_same_official_ranking_list's docstring
        # for why this is False (not "assumed same") whenever either date
        # is unknown.
        same_official_ranking_list = is_same_official_ranking_list(
            current_ranking_date, previous_ranking_date
        )

        if previous is None:
            logger.info(
                "No previous snapshot found; this looks like the first run for this tour. "
                "Movement will be reported as 'unknown' rather than 'new' for every player."
            )
        elif same_official_ranking_list:
            logger.info(
                "Official ranking list unchanged since previous run (still dated %s).",
                current_ranking_date.isoformat() if current_ranking_date else "unknown",
            )
        elif current_ranking_date is not None and previous_ranking_date is not None:
            logger.info(
                "New official WTA ranking published (previous: %s, now: %s).",
                previous_ranking_date.isoformat(),
                current_ranking_date.isoformat(),
            )
        else:
            logger.info("Comparing against snapshot from %s.", previous[0].isoformat())

        errors: list[str] = []

        # Defense against a contradictory official-ranking fetch: if
        # ranking_date is unchanged, a previously-tracked player's
        # rank/points MUST agree with the previously saved snapshot - the
        # WTA does not amend an already-published list. A disagreement
        # here is never silently accepted as if it were a genuine (but
        # unannounced) change; the previously saved, trusted values are
        # kept instead, and a clear warning is logged and recorded. This
        # also guarantees the *ordering* displayed for the Top N can never
        # shift while the official list is unchanged, not just the
        # movement label - see resolve_official_ranking's docstring.
        if same_official_ranking_list and previous_rankings:
            previous_by_id = {p.player_id: p for p in previous_rankings}
            resolved_rankings = []
            for ranking in rankings:
                resolved, warning = resolve_official_ranking(
                    ranking, previous_by_id.get(ranking.player_id), same_official_ranking_list=True
                )
                if warning:
                    logger.warning(warning)
                    errors.append(warning)
                resolved_rankings.append(resolved)
            rankings = sorted(resolved_rankings, key=lambda r: r.rank)

        # Resolve the featured player's current ranking (if configured)
        # before the match batch call, so she can ride along in that same
        # request instead of triggering one of her own - see
        # _safe_resolve_featured_player_ranking's docstring.
        featured_ranking: PlayerRanking | None = None
        featured_rank_error: str | None = None
        if self._config.featured_player.enabled:
            featured_ranking, featured_rank_error = self._safe_resolve_featured_player_ranking(pool)

        match_target_date = report_date - timedelta(days=self._config.match_target_date_offset_days)
        logger.info("Downloading matches completed on %s...", match_target_date.isoformat())
        logger.debug(
            "Processing daily match activity separately from official rankings - "
            "match results affect narration only, never rank/points/movement."
        )
        match_batch = list(rankings)
        tracked_ids = {r.player_id for r in rankings}
        if featured_ranking is not None and featured_ranking.player_id not in tracked_ids:
            match_batch.append(featured_ranking)
        matches_by_player, batch_error = self._safe_get_matches_for_date(match_batch, match_target_date)
        if batch_error:
            logger.warning(
                "Could not confirm match data for %s - every player below will show "
                "played: false with a match_error rather than a guess.",
                match_target_date.isoformat(),
            )

        players: list[PlayerReport] = []
        if batch_error:
            errors.append(batch_error)
        for ranking in rankings:
            previous_rank = previous_ranks.get(ranking.player_id)
            movement = compute_movement(
                ranking.rank,
                previous_rank,
                has_previous_snapshot=has_previous_snapshot,
                same_official_ranking_list=same_official_ranking_list,
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

        featured_player_report: FeaturedPlayerReport | None = None
        if self._config.featured_player.enabled:
            featured_player_report, featured_build_error = self._safe_build_featured_player_report(
                featured_ranking,
                featured_rank_error,
                matches_by_player,
                batch_error,
                report_date,
                has_previous_snapshot,
                same_official_ranking_list,
            )
            if featured_build_error:
                errors.append(featured_build_error)

        # Movement history stays scoped to exactly the tracked group (see
        # RankingsSnapshotStore.save_snapshot's docstring for why widening
        # this would silently break "NEW" semantics); the featured player's
        # rank (if she isn't already in that group) is recorded separately
        # so her own movement can still be computed on future runs. The
        # wider pool's names/countries are cached either way, at no extra
        # API cost since it's the same response already fetched above.
        featured_players_to_save = (
            {featured_ranking.player_id: featured_ranking} if featured_ranking is not None else None
        )
        self._snapshot_store.save_snapshot(
            report_date, self._config.tour, rankings, featured_players=featured_players_to_save
        )
        cache_pool = list(pool)
        if featured_ranking is not None and featured_ranking.player_id not in {r.player_id for r in pool}:
            cache_pool.append(featured_ranking)
        self._snapshot_store.update_players_cache(cache_pool)
        return DailyReport(
            report_date=report_date,
            tour=self._config.tour,
            players=players,
            errors=errors,
            match_target_date=match_target_date,
            featured_player=featured_player_report,
            ranking_date=current_ranking_date,
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

        A player left ``unresolved`` by every configured source (rather
        than confidently confirmed either way) is also reported as
        ``played: false`` for this report - same downstream behavior as
        before this method existed - but is called out in the log, since
        that is worth an operator's attention even though it isn't a hard
        failure.
        """

        try:
            result = self._match_provider.get_matches_for_date(rankings, target_date)
        except (PlayerDataError, DataProviderError) as exc:
            logger.error("Match lookup failed for %s: %s", target_date, exc)
            return {}, str(exc)
        except Exception as exc:  # noqa: BLE001 - this step must never abort the run
            logger.exception("Unexpected error fetching matches for %s", target_date)
            return {}, f"Unexpected error fetching matches for {target_date}: {exc}"

        if result.unresolved_player_ids:
            unresolved_names = [
                r.name for r in rankings if r.player_id in result.unresolved_player_ids
            ]
            logger.warning(
                "Could not confirm match status for %s on %s (every configured source was "
                "inconclusive); reporting played: false for %s without a match_error.",
                ", ".join(unresolved_names) or f"{len(result.unresolved_player_ids)} player(s)",
                target_date.isoformat(),
                "them" if len(unresolved_names) != 1 else "her",
            )
        return result.matches, None

    def _safe_resolve_featured_player_ranking(
        self, pool: list[PlayerRanking]
    ) -> tuple[PlayerRanking | None, str | None]:
        """Find the configured featured player's current ranking, never
        letting a failure here affect the Top N report.

        Looks in the rankings pool already fetched for this run first (the
        common case - free, since it's the exact same response). Only if
        she isn't in it does this fall back to one additional
        :meth:`RankingsProvider.get_top_n` call for a larger page -
        reusing the same provider interface rather than adding a
        dedicated "look up one player" endpoint - since her real rank
        could be well outside the configured pool size.
        """

        fp_config = self._config.featured_player
        for ranking in pool:
            if ranking.player_id == fp_config.player_id:
                return ranking, None

        fallback_n = max(len(pool) * 4, 100)
        logger.info(
            "Featured player %s (id=%s) was not in the top %d; requesting a "
            "larger rankings page (top %d) to locate her.",
            fp_config.name,
            fp_config.player_id,
            len(pool),
            fallback_n,
        )
        try:
            larger_pool = self._rankings_provider.get_top_n(fallback_n)
        except Exception as exc:  # noqa: BLE001 - must never affect the Top N report
            logger.warning(
                "Could not resolve featured player %s's ranking this run: %s", fp_config.name, exc
            )
            return None, f"Could not resolve {fp_config.name}'s ranking: {exc}"

        for ranking in larger_pool:
            if ranking.player_id == fp_config.player_id:
                return ranking, None

        logger.info(
            "Featured player %s (id=%s) was not found in the top %d WTA rankings this run.",
            fp_config.name,
            fp_config.player_id,
            fallback_n,
        )
        return None, (
            f"{fp_config.name} was not found in the top {fallback_n} WTA rankings this run."
        )

    def _safe_build_featured_player_report(
        self,
        ranking: PlayerRanking | None,
        rank_error: str | None,
        matches_by_player: dict[str, MatchResult],
        batch_error: str | None,
        report_date: date,
        has_previous_snapshot: bool,
        same_official_ranking_list: bool,
    ) -> tuple[FeaturedPlayerReport, str | None]:
        """Build the featured-player section of the report, isolating any
        unexpected failure so it can never break the rest of the pipeline -
        see the module docstring's "never cause the normal Top N pipeline
        to fail" requirement.
        """

        fp_config = self._config.featured_player
        try:
            if ranking is None:
                return (
                    FeaturedPlayerReport(
                        name=fp_config.name,
                        player_id=fp_config.player_id,
                        tagline=fp_config.tagline,
                        rank_error=rank_error,
                    ),
                    rank_error,
                )

            previous_rank = self._snapshot_store.get_previous_player_rank(
                report_date, self._config.tour, ranking.player_id
            )
            movement = compute_movement(
                ranking.rank,
                previous_rank,
                has_previous_snapshot=has_previous_snapshot,
                same_official_ranking_list=same_official_ranking_list,
            )
            return (
                FeaturedPlayerReport(
                    name=ranking.name,
                    player_id=ranking.player_id,
                    tagline=fp_config.tagline,
                    country_code=ranking.country_code,
                    rank=ranking.rank,
                    points=ranking.points,
                    movement=movement,
                    previous_rank=previous_rank,
                    match=matches_by_player.get(ranking.player_id),
                    match_error=batch_error,
                ),
                None,
            )
        except Exception as exc:  # noqa: BLE001 - the featured segment must never break the run
            logger.exception("Unexpected error building the featured-player report for %s", fp_config.name)
            return (
                FeaturedPlayerReport(
                    name=fp_config.name,
                    player_id=fp_config.player_id,
                    tagline=fp_config.tagline,
                    rank_error=f"Unexpected error building featured-player report: {exc}",
                ),
                f"Unexpected error building featured-player report for {fp_config.name}: {exc}",
            )

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

    def _render_featured_card(self, report: DailyReport, store: DailyOutputStore) -> None:
        """Render the featured-player spotlight visual, if there's a real
        one to render this run.

        Deliberately keyed off ``report.featured_player`` (built earlier
        from config, not a hard-coded name) rather than any
        player-specific check - a differently-configured featured player
        works identically. Nothing is rendered (not an error) when the
        feature is disabled, or when her ranking couldn't be resolved this
        run - there's no honest visual to draw without at least a rank.
        """

        featured = report.featured_player
        if featured is None or featured.rank is None:
            return
        try:
            self._graphics_renderer.render_featured_card(
                featured, store.featured_card_path, top_n=self._config.top_n
            )
            logger.info("Rendered %s", store.featured_card_path)
        except GraphicsError as exc:
            logger.error("Featured-player card rendering failed for %s: %s", featured.name, exc)
            report.errors.append(str(exc))

    def _generate_thumbnail(self, report: DailyReport, store: DailyOutputStore) -> None:
        try:
            self._graphics_renderer.render_thumbnail(report, store.thumbnail_path)
            logger.info("Rendered %s", store.thumbnail_path)
        except GraphicsError as exc:
            logger.error("Thumbnail rendering failed: %s", exc)
            report.errors.append(str(exc))

    def _generate_youtube_description(self, report: DailyReport, store: DailyOutputStore) -> None:
        try:
            description = generate_description(report)
            store.write_youtube_description(description)
            logger.info("Wrote %s", store.youtube_description_path)
        except Exception as exc:  # noqa: BLE001 - a text-formatting step must never abort the run
            logger.exception("Could not generate the YouTube description.")
            report.errors.append(f"Could not generate the YouTube description: {exc}")

    def _synthesize_narration(self, store: DailyOutputStore, report: DailyReport) -> None:
        logger.info("Creating narration...")
        try:
            synthesizer = voice_registry.create(self._config.voice.provider, voice_config=self._config.voice)
            synthesizer.synthesize(store.script_path, store.narration_path, report=report)
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

    def _publish_to_youtube(self, report: DailyReport, store: DailyOutputStore) -> None:
        """Optional Phase 3, run only after every earlier phase has already
        produced its artifacts (see :mod:`wta_daily.youtube.uploader`'s
        module docstring). Disabled by default; when disabled this is a
        single cheap boolean check and nothing else - no import of any
        Google library, no credential loading, no network call.

        A failure here is recorded in ``report.errors`` (surfaced via
        `report.json`, exactly like every other optional phase's
        failures) but never raises - the finished video/thumbnail/
        description/report already on disk are completely unaffected.
        """

        if not self._config.youtube.enabled:
            logger.debug("YouTube publishing is disabled (youtube.enabled: false); skipping.")
            return

        upload_store = YouTubeUploadStore(self._config.data_dir)
        result = publish_report(report, store, self._config.youtube, upload_store)

        if result.status == "failed":
            report.errors.append(f"YouTube upload failed: {result.video_error}")
        elif result.status == "success" and result.thumbnail_error:
            report.errors.append(f"YouTube thumbnail upload failed: {result.thumbnail_error}")

        store.write_report(report)  # persist the outcome above, if any

    def _commit_to_git(self, store: DailyOutputStore, report_date: date) -> None:
        logger.info("Committing to git...")
        try:
            paths = [
                store.root,
                self._config.data_dir / "rankings-history.json",
                self._config.data_dir / "players.json",
            ]
            youtube_uploads_path = self._config.data_dir / "youtube-uploads.json"
            if youtube_uploads_path.exists():
                paths.append(youtube_uploads_path)
            commit_and_push(self._repo_root, paths, report_date, self._config.git)
        except GitAutomationError as exc:
            logger.error("Git automation failed: %s", exc)
