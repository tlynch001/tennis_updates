"""Command-line entry point.

Usage::

    python -m wta_daily.cli --config config/config.yaml
    python -m wta_daily.cli --config config/config.yaml --date 2026-08-09
    wta-daily --config config/config.yaml --dry-run

The CLI is deliberately thin: it loads configuration, wires up logging, runs
:class:`~wta_daily.pipeline.DailyPipeline`, and translates a fatal error into
a clean, logged message plus a non-zero exit code (rather than a raw
traceback), which matters for unattended scheduler runs (cron, Windows Task
Scheduler, GitHub Actions) where nobody is watching the terminal.
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date

from wta_daily.config import load_config
from wta_daily.exceptions import ConfigurationError, DataProviderError, WtaDailyError
from wta_daily.logging_setup import configure_logging
from wta_daily.pipeline import DailyPipeline
from wta_daily.plugins.registry import load_builtin_plugins

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

    try:
        pipeline = DailyPipeline(config)
        pipeline.run(report_date)
    except DataProviderError as exc:
        logger.error("Could not retrieve rankings; aborting this run. %s", exc)
        return 1
    except WtaDailyError as exc:
        logger.exception("Fatal error: %s", exc)
        return 1
    except Exception:  # noqa: BLE001 - top-level safety net for unattended runs
        logger.exception("Unexpected fatal error.")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
