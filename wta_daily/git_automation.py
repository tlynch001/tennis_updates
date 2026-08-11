"""Optional git automation: commit (and optionally push) each day's output.

Disabled by default (``git.auto_commit: false``). When enabled, stages the
day's output folder plus the updated ``data/rankings-history.json`` and
``data/players.json``, commits with the configured message template, and
(if ``git.auto_push`` is also true) pushes to the configured remote/branch.

This deliberately never force-pushes, rewrites history, or touches branches
other than the current one - it is meant to be the *only* git side-effect an
unattended run performs, and it never uploads anything to YouTube or any
other publishing target.
"""

from __future__ import annotations

import logging
import subprocess
from datetime import date
from pathlib import Path

from wta_daily.config import GitConfig
from wta_daily.exceptions import WtaDailyError

logger = logging.getLogger(__name__)


class GitAutomationError(WtaDailyError):
    """Raised when the git commit/push automation fails."""


def commit_and_push(
    repo_root: Path, paths_to_stage: list[Path], report_date: date, config: GitConfig
) -> None:
    if not config.auto_commit:
        logger.info("git.auto_commit is disabled; skipping git automation.")
        return

    message = config.commit_message_template.format(date=report_date.isoformat())

    _run(["git", "add", *[str(p) for p in paths_to_stage]], cwd=repo_root)

    status = _run(["git", "status", "--porcelain"], cwd=repo_root)
    if not status.stdout.strip():
        logger.info("Nothing to commit for %s.", report_date.isoformat())
        return

    _run(["git", "commit", "-m", message], cwd=repo_root)
    logger.info("Committed daily output: %s", message)

    if config.auto_push:
        branch_args = [config.branch] if config.branch else []
        _run(["git", "push", config.remote, *branch_args], cwd=repo_root)
        logger.info("Pushed to %s%s.", config.remote, f"/{config.branch}" if config.branch else "")


def _run(command: list[str], *, cwd: Path) -> subprocess.CompletedProcess:
    result = subprocess.run(command, cwd=cwd, capture_output=True, text=True)
    if result.returncode != 0:
        raise GitAutomationError(f"Command failed ({' '.join(command)}): {result.stderr.strip()}")
    return result
