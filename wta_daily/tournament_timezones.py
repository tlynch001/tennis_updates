"""Resolves a WTA tournament catalogue entry's ``country`` field (e.g.
``"USA, OH"``, ``"GBR"``, ``"FRA"``) to an IANA timezone, for the
"reporting day" cutoff used to correctly attribute a late-night
completed match to the previous calendar day (see
:mod:`wta_daily.reporting_day`).

Deliberately data-driven (``data/tournament_timezones.yaml``) rather
than a hard-coded mapping in code, and deliberately keyed by
*country/state*, not by any one tournament by name - this is what keeps
the "prefer tournament-local time" fix general (it works identically for
any WTA tour stop this data file recognizes) rather than a special case
for Cincinnati specifically. An unrecognized country/state resolves to
``None`` rather than guessing - callers (see
:mod:`wta_daily.plugins.matches.wta_official`) already have a documented,
safe UTC-based fallback for exactly this case.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml

logger = logging.getLogger(__name__)

#: Where the shipped timezone data lives, resolved relative to the
#: current working directory - same convention as
#: ``wta_daily.points_table.DEFAULT_POINTS_TABLE_PATH`` (the app is run
#: from the repo root). Overridable via a constructor kwarg for anyone
#: who wants to maintain their own copy.
DEFAULT_TOURNAMENT_TIMEZONES_PATH = Path("data/tournament_timezones.yaml")


class TournamentTimezones:
    """Wraps the parsed country/state -> timezone data with a single,
    forgiving lookup method."""

    def __init__(self, countries: dict[str, str], us_states: dict[str, str]) -> None:
        self._countries = {str(k).upper(): str(v) for k, v in countries.items()}
        self._us_states = {str(k).upper(): str(v) for k, v in us_states.items()}

    def resolve(self, country: str | None) -> ZoneInfo | None:
        """``country`` is expected in the WTA catalogue's own format,
        e.g. ``"USA, OH"``, ``"GBR"``, ``"FRA"`` - a bare country code,
        optionally followed by a comma and a US state abbreviation.

        Returns ``None`` (never a guess) when the country isn't
        recognized, the state isn't one of the mapped US states (falls
        back to the country-level ``USA`` entry instead of guessing a
        specific state), or the resulting IANA name isn't valid on this
        system.
        """

        if not country:
            return None

        parts = [p.strip().upper() for p in country.split(",") if p.strip()]
        if not parts:
            return None

        primary = parts[0]
        state = parts[1] if len(parts) > 1 else None

        tz_name: str | None = None
        if primary == "USA" and state and state in self._us_states:
            tz_name = self._us_states[state]
        else:
            tz_name = self._countries.get(primary)

        if tz_name is None:
            return None
        try:
            return ZoneInfo(tz_name)
        except ZoneInfoNotFoundError:
            logger.warning("Unknown IANA timezone %r configured for country %r; ignoring.", tz_name, country)
            return None


def load_tournament_timezones(
    path: str | Path = DEFAULT_TOURNAMENT_TIMEZONES_PATH,
) -> TournamentTimezones:
    """Load ``data/tournament_timezones.yaml`` (or an override path)."""

    with Path(path).open("r", encoding="utf-8") as fh:
        data: dict[str, Any] = yaml.safe_load(fh) or {}
    return TournamentTimezones(
        countries=data.get("countries") or {},
        us_states=data.get("us_states") or {},
    )
