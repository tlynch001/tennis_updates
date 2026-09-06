"""Command-line entry point.

Usage::

    python -m wta_daily.cli --config config/config.yaml
    python -m wta_daily.cli --config config/config.yaml --date 2026-08-09

    # Publish already-generated landscape video:
    python -m wta_daily.cli --config config/config.yaml --date 2026-08-09 --upload-youtube

    # Publish already-generated vertical Short:
    python -m wta_daily.cli --config config/config.yaml --date 2026-08-09 --upload-youtube-vertical
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import date

from wta_daily.config import AppConfig, load_config
from wta_daily.exceptions import ConfigurationError, DataProviderError, WtaDailyError
from wta_daily.logging_setup import configure_logging
from wta_daily.models import DailyReport
from wta_daily.persistence.report_store import DailyOutputStore
from wta_daily.persistence.youtube_upload_store import (
    LANDSCAPE_VARIANT,
    VERTICAL_VARIANT,
    YouTubeUploadStore,
)
from wta_daily.pipeline import DailyPipeline
from wta_daily.plugins.registry import load_builtin_plugins
from wta_daily.youtube.uploader import publish_report

logger = logging.getLogger(__name__)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="wta-daily", description="Generate today's WTA Top N video assets."
    )
    parser.add_argument(
        "--config",
        default="config/config.yaml",
        help="Path to the YAML configuration file (default: config/config.yaml).",
    )
    parser.add_argument(
        "--date",
        default=None,
        help="Run as if today were this date (YYYY-MM-DD). Defaults to the real current date.",
    )
    parser.add_argument(
        "--verbose", action="store_true", help="Enable debug-level logging."
    )
    upload_group = parser.add_mutually_exclusive_group()
    upload_group.add_argument(
        "--upload-youtube",
        action="store_true",
        help=(
            "Skip data collection/narration/video assembly and publish an already-generated "
            "output/<date>/video.mp4 to YouTube."
        ),
    )
    upload_group.add_argument(
        "--upload-youtube-vertical",
        action="store_true",
        help=(
            "Skip data collection/narration/video assembly and publish the already-generated "
            "output/<date>/vertical/video.mp4 to YouTube as the independent vertical upload. "
            "The existing title and youtube_description.txt are reused and no custom landscape "
            "thumbnail is uploaded."
        ),
    )
    parser.add_argument(
        "--force-youtube-upload",
        action="store_true",
        help=(
            "Combined with either YouTube upload option: upload even if that date/tour/format "
            "was already recorded as successfully uploaded. Use deliberately."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)

    try:
        config = load_config(args.config)
    except ConfigurationError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2

    report_date = date.fromisoformat(args.date) if args.date else date.today()
    log_path = configure_logging(config.log_dir, report_date, verbose=args.verbose)
    logger.info("Logging to %s", log_path)

    load_builtin_plugins()

    if args.upload_youtube:
        return _upload_youtube_only(
            config,
            report_date,
            force=args.force_youtube_upload,
            variant=LANDSCAPE_VARIANT,
        )
    if args.upload_youtube_vertical:
        return _upload_youtube_only(
            config,
            report_date,
            force=args.force_youtube_upload,
            variant=VERTICAL_VARIANT,
        )

    try:
        pipeline = DailyPipeline(config)
        pipeline.run(report_date)
    except DataProviderError as exc:
        logger.error("Could not retrieve rankings; aborting this run. %s", exc)
        return 1
    except WtaDailyError as exc:
        logger.exception("Fatal error: %s", exc)
        return 1
    except Exception:  # noqa: BLE001
        logger.exception("Unexpected fatal error.")
        return 1

    return 0


def _upload_youtube_only(
    config: AppConfig,
    report_date: date,
    *,
    force: bool,
    variant: str = LANDSCAPE_VARIANT,
) -> int:
    """Publish one already-generated format without rerunning providers."""

    store = DailyOutputStore(config.output_dir, report_date)
    if not store.report_path.exists():
        logger.error(
            "No existing report found at %s; run the full pipeline for %s first.",
            store.report_path,
            report_date.isoformat(),
        )
        return 1

    with store.report_path.open("r", encoding="utf-8") as fh:
        report = DailyReport.from_dict(json.load(fh))

    upload_store = YouTubeUploadStore(config.data_dir)
    result = publish_report(
        report,
        store,
        config.youtube,
        upload_store,
        force=force,
        variant=variant,
    )

    if result.status == "failed":
        logger.error("YouTube %s upload failed: %s", variant, result.video_error)
        return 1
    if result.status == "disabled":
        logger.info(
            "youtube.enabled is false in config; nothing to upload. Set youtube.enabled: true."
        )
        return 0
    if result.status == "skipped_duplicate":
        logger.info(result.message)
        return 0

    logger.info("YouTube %s upload finished successfully: %s", variant, result.video_url)
    if result.thumbnail_error:
        logger.error("Thumbnail upload failed (video is fine): %s", result.thumbnail_error)
    return 0


if __name__ == "__main__":
    sys.exit(main())
