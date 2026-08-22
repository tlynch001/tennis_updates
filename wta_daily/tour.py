"""Tour identity and presentation.

Selected once from ``config.tour``. Downstream presentation (titles,
descriptions, narration, graphics attribution) asks a :class:`TourProfile`
for wording instead of hard-coding WTA strings or branching on the raw
tour key.

This is **presentation only**. Rankings and match providers stay independently
configured; an ATP profile does not imply ATP data support exists. Combining
``tour: atp`` with a WTA-only provider is rejected so an ATP-branded video
cannot silently show WTA players.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from wta_daily.exceptions import ConfigurationError

#: Provider plugin names that fetch WTA data (official WTA JSON backend).
#: Used only to refuse ATP-branded runs that would still load WTA players.
WTA_ONLY_PROVIDER_NAMES = frozenset({"wta_official"})

#: ``best_of`` with no ``sources`` list uses this mix (see
#: :mod:`wta_daily.plugins.matches.best_of`); it includes ``wta_official``.
_BEST_OF_DEFAULT_SOURCE_NAMES = ("wta_official", "live_tennis_api")


@dataclass(frozen=True)
class TourProfile:
    """Presentation values for one tour.

    Downstream code should read these fields (or :meth:`format`) rather than
    interpreting ``config.tour`` / ``report.tour`` with its own conditionals.
    """

    key: str
    display_name: str
    tour_long_name: str
    game_label: str
    subject: str
    object: str
    possessive: str
    ranking_body: str
    attribution: str
    git_commit_message_template: str

    @property
    def subject_cap(self) -> str:
        return self.subject[:1].upper() + self.subject[1:] if self.subject else self.subject

    def presentation_fields(self) -> dict[str, str]:
        """Keyword arguments for phrase-pool ``str.format`` calls."""

        return {
            "tour": self.display_name,
            "tour_long": self.tour_long_name,
            "game": self.game_label,
            "subject": self.subject,
            "subject_cap": self.subject_cap,
            "object": self.object,
            "possessive": self.possessive,
            "ranking_body": self.ranking_body,
        }

    def format(self, template: str, **kwargs: object) -> str:
        """Format ``template`` with this profile's fields plus any extra kwargs."""

        return template.format(**self.presentation_fields(), **kwargs)


WTA = TourProfile(
    key="wta",
    display_name="WTA",
    tour_long_name="WTA Tour",
    game_label="women's game",
    subject="she",
    object="her",
    possessive="her",
    ranking_body="the WTA",
    attribution="Data: WTA (api.wtatennis.com)  |  Generated automatically  |  wta-daily",
    git_commit_message_template="Daily WTA Update {date}",
)

ATP = TourProfile(
    key="atp",
    display_name="ATP",
    tour_long_name="ATP Tour",
    game_label="men's game",
    subject="he",
    object="him",
    possessive="his",
    ranking_body="the ATP",
    # No ATP data provider ships yet - do not invent a rankings URL.
    attribution="Generated automatically",
    git_commit_message_template="Daily ATP Update {date}",
)

_PROFILES: dict[str, TourProfile] = {WTA.key: WTA, ATP.key: ATP}


def profile_for(tour: str) -> TourProfile:
    """Return the profile for ``tour`` (case-insensitive).

    The stored tour key on reports/config is left unchanged; only lookup is
    normalized. Unknown tours fail loudly rather than falling back to WTA
    wording (which would mislabel the output).
    """

    key = (tour or "").strip().lower()
    try:
        return _PROFILES[key]
    except KeyError as exc:
        supported = ", ".join(sorted(_PROFILES))
        raise ConfigurationError(
            f"Unknown tour {tour!r}. Supported tours: {supported}."
        ) from exc


def match_provider_plugin_names(name: str, options: dict[str, Any] | None) -> frozenset[str]:
    """Plugin names a match_provider config will actually construct."""

    names = {name}
    if name == "best_of":
        sources = (options or {}).get("sources")
        if sources is None:
            names.update(_BEST_OF_DEFAULT_SOURCE_NAMES)
        else:
            for source in sources:
                if isinstance(source, dict) and source.get("provider"):
                    names.add(str(source["provider"]))
    return frozenset(names)


def assert_tour_providers_compatible(
    tour: str,
    *,
    rankings_provider_name: str,
    match_provider_name: str,
    match_provider_options: dict[str, Any] | None = None,
) -> None:
    """Reject ATP (or any non-WTA tour) combined with WTA-only data plugins.

    ``tour: wta`` is unrestricted. ``tour: atp`` with ``sample`` providers is
    allowed for presentation tests; ``tour: atp`` with ``wta_official``
    (directly or as a ``best_of`` source, including the default source list)
    is not, because that run would brand WTA players as ATP.
    """

    profile = profile_for(tour)
    if profile.key == WTA.key:
        return

    used: list[str] = []
    if rankings_provider_name in WTA_ONLY_PROVIDER_NAMES:
        used.append(f"rankings_provider={rankings_provider_name}")
    for plugin in sorted(
        match_provider_plugin_names(match_provider_name, match_provider_options)
        & WTA_ONLY_PROVIDER_NAMES
    ):
        used.append(f"match_provider includes {plugin}")
    if not used:
        return
    raise ConfigurationError(
        f"tour: {profile.key} cannot use WTA-only data providers ({', '.join(used)}). "
        "That combination would brand WTA players as ATP. ATP data support is not "
        "implemented; use tour: wta for production, or sample providers for "
        "presentation tests."
    )
