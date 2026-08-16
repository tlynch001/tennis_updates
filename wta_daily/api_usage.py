"""A tiny per-run counter for outbound external API requests.

Exists purely for operational visibility into how "chatty" one daily run is
against each external service - see the README's "Understanding API usage"
section. It never affects behavior or control flow, and it never records
URLs, query parameters, or headers, so it cannot leak an API key or other
secret; it only counts, keyed by a short human-readable category name
(e.g. ``"WTA rankings"``, ``"LiveTennisAPI"``).

Usage: call :func:`reset` once at the start of a pipeline run, :func:`record`
from each thin API-client wrapper method right before/after issuing its
request, and :func:`log_summary` at the end of the run to see the full
breakdown. This is a simple module-level counter (not thread-safe) because
the pipeline is a single-threaded, once-a-day batch job - no more machinery
than that is warranted here.
"""

from __future__ import annotations

import logging
from collections import Counter

logger = logging.getLogger(__name__)

_counts: Counter[str] = Counter()


def reset() -> None:
    """Clear all counts - call once at the start of a pipeline run."""

    _counts.clear()


def record(category: str) -> None:
    """Record one outbound request against ``category``.

    Also emits a debug-level log line immediately, so a ``--verbose`` run's
    log shows exactly when and in what order requests happened, not just the
    final tally.
    """

    _counts[category] += 1
    logger.debug("External API request recorded: %s (running total: %d)", category, _counts[category])


def snapshot() -> dict[str, int]:
    """Return a plain ``{category: count}`` dict of everything recorded so far."""

    return dict(_counts)


def total() -> int:
    return sum(_counts.values())


def log_summary(*, level: int = logging.INFO) -> None:
    """Log a human-readable breakdown of every category recorded so far.

    Produces output like::

        External API requests:
          WTA rankings: 1
          WTA tournament discovery: 1
          WTA match results: 3
          Total: 5

    Categories that were never recorded (e.g. a disabled fallback provider)
    are intentionally omitted rather than shown as zero, so the summary
    reflects exactly what happened this run.
    """

    if not _counts:
        logger.log(level, "External API requests: none made this run.")
        return
    lines = [f"  {name}: {count}" for name, count in sorted(_counts.items())]
    lines.append(f"  Total: {total()}")
    logger.log(level, "External API requests:\n%s", "\n".join(lines))
