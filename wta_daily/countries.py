"""Mapping from the 3-letter IOC/tour country codes used by tennis data feeds
to ISO 3166-1 alpha-2 codes, display names, and Unicode regional-indicator
flag emoji.

Flags are rendered from the *Unicode emoji standard* (glyphs supplied by the
system's own emoji font, e.g. Noto Color Emoji) rather than from any
downloaded image, so there is no copyright/licensing concern: national flags
themselves are not copyrightable, and Unicode code points are a text
standard, not artwork we would need to license.

The table intentionally covers the countries that most frequently appear in
WTA/ATP Top 100 rankings. Unknown codes fall back gracefully to a neutral
placeholder instead of raising, per the project's "never abort on missing
data" philosophy.
"""

from __future__ import annotations

from dataclasses import dataclass

# IOC (or tour) code -> (ISO 3166-1 alpha-2 code, display name)
_IOC_TO_ISO2: dict[str, tuple[str, str]] = {
    "AHO": ("CW", "Netherlands Antilles"),
    "ALG": ("DZ", "Algeria"),
    "ARG": ("AR", "Argentina"),
    "ARM": ("AM", "Armenia"),
    "AUS": ("AU", "Australia"),
    "AUT": ("AT", "Austria"),
    "AZE": ("AZ", "Azerbaijan"),
    "BAR": ("BB", "Barbados"),
    "BEL": ("BE", "Belgium"),
    "BIH": ("BA", "Bosnia and Herzegovina"),
    "BLR": ("BY", "Belarus"),
    "BRA": ("BR", "Brazil"),
    "BUL": ("BG", "Bulgaria"),
    "CAN": ("CA", "Canada"),
    "CHI": ("CL", "Chile"),
    "CHN": ("CN", "China"),
    "COL": ("CO", "Colombia"),
    "CRO": ("HR", "Croatia"),
    "CYP": ("CY", "Cyprus"),
    "CZE": ("CZ", "Czech Republic"),
    "DEN": ("DK", "Denmark"),
    "ECU": ("EC", "Ecuador"),
    "EGY": ("EG", "Egypt"),
    "ESP": ("ES", "Spain"),
    "EST": ("EE", "Estonia"),
    "FIN": ("FI", "Finland"),
    "FRA": ("FR", "France"),
    "GBR": ("GB", "Great Britain"),
    "GEO": ("GE", "Georgia"),
    "GER": ("DE", "Germany"),
    "GRE": ("GR", "Greece"),
    "HKG": ("HK", "Hong Kong"),
    "HUN": ("HU", "Hungary"),
    "INA": ("ID", "Indonesia"),
    "IND": ("IN", "India"),
    "IRL": ("IE", "Ireland"),
    "ISR": ("IL", "Israel"),
    "ITA": ("IT", "Italy"),
    "JPN": ("JP", "Japan"),
    "KAZ": ("KZ", "Kazakhstan"),
    "KOR": ("KR", "South Korea"),
    "KSA": ("SA", "Saudi Arabia"),
    "LAT": ("LV", "Latvia"),
    "LTU": ("LT", "Lithuania"),
    "LUX": ("LU", "Luxembourg"),
    "MAR": ("MA", "Morocco"),
    "MDA": ("MD", "Moldova"),
    "MEX": ("MX", "Mexico"),
    "MNE": ("ME", "Montenegro"),
    "NED": ("NL", "Netherlands"),
    "NOR": ("NO", "Norway"),
    "NZL": ("NZ", "New Zealand"),
    "PAR": ("PY", "Paraguay"),
    "PER": ("PE", "Peru"),
    "PHI": ("PH", "Philippines"),
    "POL": ("PL", "Poland"),
    "POR": ("PT", "Portugal"),
    "PUR": ("PR", "Puerto Rico"),
    "ROU": ("RO", "Romania"),
    "RSA": ("ZA", "South Africa"),
    "RUS": ("RU", "Russia"),
    "SLO": ("SI", "Slovenia"),
    "SRB": ("RS", "Serbia"),
    "SUI": ("CH", "Switzerland"),
    "SVK": ("SK", "Slovakia"),
    "SWE": ("SE", "Sweden"),
    "THA": ("TH", "Thailand"),
    "TPE": ("TW", "Chinese Taipei"),
    "TUN": ("TN", "Tunisia"),
    "TUR": ("TR", "Turkey"),
    "UKR": ("UA", "Ukraine"),
    "URU": ("UY", "Uruguay"),
    "USA": ("US", "United States"),
    "UZB": ("UZ", "Uzbekistan"),
    "VEN": ("VE", "Venezuela"),
    "VIE": ("VN", "Vietnam"),
}

_REGIONAL_INDICATOR_BASE = ord("\U0001F1E6") - ord("A")


@dataclass(frozen=True)
class CountryInfo:
    """Resolved display information for a country code."""

    code: str
    iso2: str | None
    display_name: str
    flag_emoji: str


def flag_emoji_from_iso2(iso2: str) -> str:
    """Build a Unicode regional-indicator flag emoji from an ISO alpha-2 code."""

    iso2 = iso2.upper()
    if len(iso2) != 2 or not iso2.isalpha():
        return "\U0001F3F3"  # white flag placeholder
    return "".join(chr(ord(ch) + _REGIONAL_INDICATOR_BASE) for ch in iso2)


def get_country_info(code: str) -> CountryInfo:
    """Resolve a 3-letter tour country code into display-ready information.

    Unrecognized codes never raise; they degrade to the raw code as the
    display name and a neutral placeholder flag, in keeping with the
    "never abort the job over one missing piece of data" requirement.
    """

    code = (code or "").upper().strip()
    entry = _IOC_TO_ISO2.get(code)
    if entry is None:
        return CountryInfo(
            code=code or "UNK", iso2=None, display_name=code or "Unknown", flag_emoji="\U0001F3F3"
        )
    iso2, display_name = entry
    return CountryInfo(
        code=code, iso2=iso2, display_name=display_name, flag_emoji=flag_emoji_from_iso2(iso2)
    )
