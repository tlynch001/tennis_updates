"""ElevenLabs pronunciation-dictionary management for WTA player names.

## Why this mechanism, and not something else

ElevenLabs supports two ways to correct a mispronounced word via a
"pronunciation dictionary" attached to a text-to-speech request:

* **Phoneme rules** (exact IPA or CMU phonetic transcription) - the most
  precise option, but ElevenLabs' own docs are explicit that phoneme tags
  only take effect on the ``eleven_flash_v2`` and ``eleven_v3`` models;
  every other model (including this project's configured default,
  ``eleven_multilingual_v2`` - see ``VoiceConfig.model_id``) silently
  ignores them and falls back to its normal pronunciation. Relying on
  phonemes today would mean the fix stops working the moment someone
  reads the config and sees no obvious reason not to change the model.
* **Alias rules** - a plain-text respelling substituted at synthesis time
  (e.g. ``"Swiatek"`` -> ``"Shvee-on-tek"``), supported by *every*
  ElevenLabs model. This never changes the text itself - report.json and
  script.txt keep the correctly-spelled name; only the audio uses the
  respelling.

Given the model actually configured for this project, alias rules are the
robust choice, not phonemes - see the README's "Narration pronunciation"
section for the full comparison this module's design followed.

This is also why player names are handled by *this* mechanism and tennis
scores are handled by :mod:`wta_daily.voice.narration_text` instead: a
pronunciation dictionary only ever matches a finite list of literal
strings, so it's a poor fit for an open-ended pattern like "any tennis
score" - but it's exactly the right fit for a curated, maintainable list
of specific names.

## Maintaining the list

:data:`PLAYER_NAME_ALIASES` is the only thing a future contributor needs
to edit to fix a newly-mispronounced name - no pipeline or provider code
changes required. The dictionary is created (or re-created) on ElevenLabs'
side automatically the next time this list's content changes (see
:func:`get_or_create_locator`); a normal day-to-day run with an unchanged
list makes zero calls to the pronunciation-dictionary API, only the
existing per-run text-to-speech call.
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_CREATE_URL = "https://api.elevenlabs.io/v1/pronunciation-dictionaries/add-from-rules"

#: Name of the dictionary as it appears in the ElevenLabs dashboard - for
#: identification only, does not affect matching.
DICTIONARY_NAME = "wta-daily-player-names"

#: Respellings for player surnames whose default English pronunciation is
#: a poor match for how they're actually said, curated by ear against the
#: current WTA Top 30 (see the README for the specific names tested).
#: Matched as whole words by ElevenLabs (its rules default to
#: ``word_boundaries: true``), so an entry fires correctly regardless of
#: which first name precedes it, and never matches inside an unrelated
#: longer word. Add an entry here whenever a new player's name comes back
#: mispronounced - nothing else needs to change.
PLAYER_NAME_ALIASES: dict[str, str] = {
    "Swiatek": "Shvee-on-tek",
    "Sabalenka": "Sah-buh-LENG-kuh",
    "Muchova": "MOO-ho-vah",
    "Krejcikova": "KREY-chee-koh-vah",
    "Bouzkova": "BOOZ-koh-vah",
    "Chwalinska": "Hfah-LEEN-ska",
    "Jovic": "YO-vitch",
    "Cirstea": "SEER-shteh-ah",
}


def _rules_payload() -> list[dict[str, Any]]:
    return [
        {"string_to_replace": name, "type": "alias", "alias": alias}
        for name, alias in PLAYER_NAME_ALIASES.items()
    ]


def _rules_hash() -> str:
    """Stable hash of the current rule set.

    Used to detect when a cached dictionary locator is stale (i.e.
    :data:`PLAYER_NAME_ALIASES` was edited since it was created) without
    needing to compare full payloads, and to avoid ever re-creating the
    dictionary when nothing has changed.
    """

    payload = json.dumps(_rules_payload(), sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class PronunciationDictionaryCache:
    """Persists the created dictionary's id/version/rules-hash to disk.

    Lives under the project's existing ``data/cache`` scratch space (see
    the README's "Folder structure" section) - this is provider-level
    caching, not daily report data, so it belongs there rather than in
    ``rankings-history.json``/``players.json``.
    """

    def __init__(self, cache_path: Path) -> None:
        self._cache_path = cache_path

    def load(self) -> dict[str, Any] | None:
        if not self._cache_path.exists():
            return None
        try:
            with self._cache_path.open("r", encoding="utf-8") as fh:
                return json.load(fh)
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Could not read pronunciation dictionary cache: %s", exc)
            return None

    def save(self, data: dict[str, Any]) -> None:
        self._cache_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self._cache_path.with_suffix(self._cache_path.suffix + ".tmp")
        with tmp_path.open("w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
        tmp_path.replace(self._cache_path)


def get_or_create_locator(
    api_key: str, cache: PronunciationDictionaryCache
) -> dict[str, str] | None:
    """Return a ``pronunciation_dictionary_locators`` entry for the current
    :data:`PLAYER_NAME_ALIASES` rule set.

    Calls the ElevenLabs API to create (or re-create) the dictionary only
    when the cache is missing or stale - never on a normal run where the
    alias list hasn't changed. Returns ``None`` (and logs a warning)
    rather than raising if creation fails for any reason - a pronunciation
    hiccup must never block narration synthesis itself, it should just
    fall back to ElevenLabs' default pronunciation for that run.
    """

    current_hash = _rules_hash()
    cached = cache.load()
    if cached is not None and cached.get("rules_hash") == current_hash:
        return {
            "pronunciation_dictionary_id": cached["pronunciation_dictionary_id"],
            "version_id": cached["version_id"],
        }

    import requests

    try:
        response = requests.post(
            _CREATE_URL,
            headers={"xi-api-key": api_key, "Content-Type": "application/json"},
            json={"name": DICTIONARY_NAME, "rules": _rules_payload()},
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()
        locator = {
            "pronunciation_dictionary_id": str(data["id"]),
            "version_id": str(data["version_id"]),
        }
    except Exception as exc:  # noqa: BLE001 - pronunciation is a nice-to-have, never fatal
        logger.warning(
            "Could not create/update the ElevenLabs pronunciation dictionary; "
            "continuing without it this run (names will use ElevenLabs' default "
            "pronunciation): %s",
            exc,
        )
        return None

    cache.save({**locator, "rules_hash": current_hash})
    logger.info(
        "Created/updated ElevenLabs pronunciation dictionary %s (version %s).",
        locator["pronunciation_dictionary_id"],
        locator["version_id"],
    )
    return locator
