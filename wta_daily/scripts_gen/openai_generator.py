"""Optional LLM-backed narration script generator.

This mirrors the brief's suggestion to "use an LLM to create a conversational
narration." It is opt-in (set ``script.generator: openai`` in the config and
export an API key) because Phase 1 must run end-to-end with zero paid
dependencies. If the API key is missing or the request fails for any reason,
this generator logs a clear warning and transparently falls back to the
deterministic :class:`~wta_daily.scripts_gen.template_generator.TemplateScriptGenerator`
so a flaky network call never aborts the whole daily job.
"""

from __future__ import annotations

import logging
import os

from wta_daily.config import ScriptConfig
from wta_daily.models import DailyReport
from wta_daily.plugins.base import ScriptGenerator
from wta_daily.plugins.registry import script_registry
from wta_daily.scripts_gen.template_generator import TemplateScriptGenerator

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "You are a professional tennis broadcaster writing the narration script for a daily "
    "YouTube video covering the WTA Top N rankings. Write natural, conversational, "
    "broadcast-quality prose (not bullet points, not markdown). Mention a ranking change "
    "only when it actually happened; otherwise say the player 'remains' at her rank. "
    "The 'movement' field for each player is one of up/down/same/new/unknown. Treat "
    "'unknown' very differently from 'new': 'unknown' means there is no previous "
    "ranking on record to compare against (e.g. this is the first report ever produced), "
    "so you must NOT say the player is new, just entered, or debuting in the Top N - "
    "simply state her current rank neutrally (e.g. 'sits at number 4 today'). Only use "
    "'new'/'entered'/'debut' language when movement is literally 'new'. "
    "For every player, mention whether they won or lost their most recent match, the "
    "opponent, tournament, round, and score when available; if no match information is "
    "available, say so plainly rather than guessing. Avoid repeating the same sentence "
    "structure twice in a row. Keep the whole script long enough to read aloud in about "
    "the requested number of minutes. End the script with a single, clear sign-off line "
    "(e.g. thanking viewers and mentioning you'll be back tomorrow) - that sign-off must "
    "be the very last line of the script, with no further commentary, statistics, or "
    "caveats added after it."
)


def _build_user_prompt(report: DailyReport, config: ScriptConfig) -> str:
    lines = [
        f"Date: {report.report_date.isoformat()}",
        f"Tour: {report.tour.upper()}",
        (
            f"Target length: {config.target_minutes_low:.0f}-{config.target_minutes_high:.0f} minutes "
            f"at roughly {config.words_per_minute} words per minute."
        ),
        "",
        "Players, ranked 1..N:",
    ]
    for player in report.players:
        match_desc = "no completed match to report"
        if player.match is not None:
            outcome = "won" if player.match.won else "lost"
            match_desc = (
                f"{outcome} vs {player.match.opponent} {player.match.score} "
                f"({player.match.round}, {player.match.tournament})"
            )
        elif player.match_error:
            match_desc = f"match data unavailable ({player.match_error})"
        lines.append(
            f"- Rank {player.rank} (movement: {player.movement.value}, "
            f"previous rank: {player.previous_rank}): {player.name}, {player.points} points. "
            f"Latest match: {match_desc}."
        )
    return "\n".join(lines)


@script_registry.register("openai")
class OpenAIScriptGenerator(ScriptGenerator):
    """Uses the OpenAI Chat Completions API to write the narration script."""

    _API_URL = "https://api.openai.com/v1/chat/completions"

    def __init__(self, script_config: ScriptConfig | None = None, **_ignored: object) -> None:
        self._config = script_config or ScriptConfig()
        self._fallback = TemplateScriptGenerator(script_config=self._config)

    def generate(self, report: DailyReport) -> str:
        api_key = os.environ.get(self._config.openai_api_key_env)
        if not api_key:
            logger.warning(
                "%s is not set; falling back to the template script generator.",
                self._config.openai_api_key_env,
            )
            return self._fallback.generate(report)

        try:
            return self._call_openai(report, api_key)
        except Exception as exc:  # noqa: BLE001 - any failure must not abort the job
            logger.warning("OpenAI script generation failed (%s); using template fallback.", exc)
            return self._fallback.generate(report)

    def _call_openai(self, report: DailyReport, api_key: str) -> str:
        import requests

        payload = {
            "model": self._config.openai_model,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": _build_user_prompt(report, self._config)},
            ],
            "temperature": 0.7,
        }
        response = requests.post(
            self._API_URL,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=payload,
            timeout=60,
        )
        response.raise_for_status()
        data = response.json()
        content = data["choices"][0]["message"]["content"].strip()
        if not content:
            raise ValueError("OpenAI returned an empty script.")
        return content
