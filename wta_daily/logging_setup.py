"""Logging configuration.

Every run writes a dated log file (``logs/wta-daily-<date>.log``) in addition
to console output, so a failure discovered the next morning can always be
traced back to a specific log file, per the project's logging requirements.
"""

from __future__ import annotations

import logging
import sys
from datetime import date
from pathlib import Path


def configure_logging(log_dir: str | Path, report_date: date, *, verbose: bool = False) -> Path:
    log_dir_path = Path(log_dir)
    log_dir_path.mkdir(parents=True, exist_ok=True)
    log_path = log_dir_path / f"wta-daily-{report_date.isoformat()}.log"

    level = logging.DEBUG if verbose else logging.INFO
    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    )

    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()

    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    root.addHandler(console_handler)

    return log_path
