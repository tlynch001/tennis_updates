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
from wta_daily.models import DailyReport, MatchResult, TournamentRunStatus, TournamentState
from wta_daily.plugins.base import ScriptGenerator
from wta_daily.plugins.registry import script_registry
from wta_daily.scripts_gen.template_generator import TemplateScriptGenerator
from wta_daily.scripts_gen.tournament_status_narration import is_result_of_reported_match

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
    "The 'Latest match' field for each player describes a match confirmed to have been "
    "completed on the specific target date given below (not just 'whenever her last known "
    "match was') - if it says 'no completed match to report', that means she did NOT play "
    "on that date; do not invent or imply a match happened, and do not describe an older "
    "result instead. Mention whether they won or lost, the opponent, tournament, round, and "
    "score when a match is given; if no match information is available, say so plainly "
    "rather than guessing. Format scores with a space after each comma (e.g. '6-4, 7-6(2)', "
    "not '6-4,7-6(2)') for readability. A match result never changes the CURRENT official "
    "ranking shown for that player - never say a match 'moves her to number X' or imply the "
    "official ranking updated because of it; you may occasionally (not for every winning "
    "player) add a brief, vague aside that a strong result could matter for the NEXT official "
    "WTA ranking release, but never state a specific projected rank or points total - that is "
    "a separate, not-yet-built feature. Only mention the points gap to the player ranked just "
    "above someone when it is genuinely tight (roughly 100 points or fewer) and treat it as an "
    "occasional storyline, not something to report for every player. Avoid repeating the same "
    "sentence structure twice in a row. "
    "The very first player's story (immediately after your introduction) has no earlier "
    "story to transition from, so it should begin directly with her name rather than a "
    "continuation phrase like 'Elsewhere in the Top N', 'Meanwhile', 'Also', or 'Turning "
    "to' - don't replace it with manufactured filler like 'Starting at number one' either, "
    "just start the sentence with her name. Those continuation phrases are fine, and "
    "encouraged for variety, starting from the second player's story onward. Keep "
    "the whole script long enough to read aloud in about the requested number of minutes. "
    "End the script with a single, clear sign-off line "
    "(e.g. thanking viewers and mentioning you'll be back tomorrow) - that sign-off must "
    "be the very last line of the script, with no further commentary, statistics, or "
    "caveats added after it. "
    "If a 'Featured player' section is given below, add one short (1-3 sentence) segment "
    "about that player AFTER all the Top N coverage and AFTER any length-related notes, but "
    "BEFORE the final sign-off line. This segment is the one place a light, affectionate, "
    "tongue-in-cheek editorial voice is allowed - the running joke is that this player is "
    "unofficially 'America's favorite' regardless of her real ranking, and if she's outside "
    "the Top N, that the Top N return is inevitable (vary the wording; do not repeat the same "
    "sentence structure across consecutive days). Never reuse the exact same nickname/joke "
    "phrase for her (e.g. 'America's favorite', 'the reigning champion of this show's "
    "affections') more than once within this segment - pick a different one for each "
    "sentence that needs one. Never make a mathematically specific claim "
    "like 'just two wins away'. Never make a proximity claim that isn't actually true of her "
    "rank, either - phrases like 'just outside the Top N', 'on the doorstep', 'knocking on the "
    "door', or 'lurking just outside' imply she's genuinely close (e.g. rank 11-15 for a "
    "Top 10 show), which is misleading for a player ranked, say, 28th or 100th. For a player "
    "well outside the Top N, prefer playful language that doesn't claim closeness - e.g. 'the "
    "climb back toward the Top N continues', 'this program remains considerably more optimistic "
    "than the rankings', 'naturally, this program has higher expectations', 'still some "
    "climbing to do before she's back in the Top N' - the joke is that the show is unusually "
    "fond of her regardless of the numbers, never that she's about to break in when she isn't. "
    "If her rank has her already inside the Top N, retire the "
    "'trying to break in' framing and instead celebrate that she's arrived; if she's reached "
    "world No. 1, drop the official-vs-unofficial-ranking bit entirely and just recognize the "
    "real result. Only occasionally (not every script) use a '#1 in our hearts' style joke "
    "contrasting her official rank with an imaginary one - and never once she's genuinely "
    "world No. 1. Every fact you state about this player (rank, movement, match result) must "
    "come only from the 'Featured player' data given below - if her rank is not given, omit "
    "the segment entirely rather than guessing; if her match result is not given, do not "
    "mention a match at all for her. "
    "Some players (Top N or the featured player) may have a 'Tournament status' line. Use it "
    "for elimination/title context ONLY - who eliminated her, what round she reached, ranking "
    "points that finish earned, and (if given) how it compares with her result at the same "
    "event last year. Every number and fact in that line (round, eliminator, points, previous "
    "year's round/points/net swing) is precomputed application data - copy it into natural "
    "prose, but NEVER calculate, estimate, or restate it differently, and NEVER invent a "
    "previous-year comparison, round name, eliminator, or points figure that isn't explicitly "
    "given. If a 'Tournament status' line says 'active' or 'did not participate' or 'unknown', "
    "say nothing about tournament elimination/title context for that player at all - do not "
    "say she 'did not play' just because there's no ranking-list news for her either way. If "
    "the line's detail level is 'brief' (a result already reported on an earlier day), keep it "
    "to one short clause (e.g. 'remains out of the draw, having fallen in the quarterfinals') "
    "rather than repeating every detail again. If it's 'detailed' (first time this exact result "
    "is being reported), you may use the full detail given, split naturally across two or three "
    "broadcast-style sentences rather than crammed into one sentence with dashes - e.g. one "
    "sentence for the elimination/title fact, a separate sentence for the ranking points and "
    "any historical comparison. Prefer saying 'ranking points' explicitly (e.g. 'earning 65 "
    "ranking points') rather than just 'points', so it's unmistakable what the number "
    "represents. When phrasing a historical comparison, never place 'the'/'her'/'a'/'last "
    "year's' directly in front of a given round name (e.g. 'the Round of 64') - that round name "
    "already includes its own article, so stacking another one in front of it produces broken "
    "text like 'better than the the Round of 64'; use a preposition or verb right before it "
    "instead (e.g. 'improving on the Round of 64 she reached last year', 'matching the Round of "
    "64 she reached last year'). A 'net points swing' figure (if given) describes what happens "
    "once last year's result eventually rolls off the rolling 52-week ranking window - NEVER "
    "phrase it as an immediate ranking change, gain, or points total; phrase it as a "
    "future/eventual effect, exactly like the general 'next official ranking' rule above, and "
    "only mention it alongside the historical comparison it belongs to, never on its own. "
    "Once a player's 'Tournament status' is 'eliminated' or 'champion' (in either detail level), "
    "that is more important news than a generic 'no completed match to report'/'result "
    "unavailable' filler for that same player - do NOT also say she 'did not play "
    "yesterday'/'had the day off'/'result couldn't be confirmed' once you know her tournament "
    "run is already over; the elimination/title context replaces that filler entirely. A "
    "genuine win/loss match result for the target date is never dropped by this rule, only the "
    "generic 'nothing to report either way' filler is. "
    "If a 'Tournament status' line is marked '(just happened, from the match you're already "
    "narrating for her)', that means the win/loss you just described for this player IS the "
    "match that eliminated her or won her the title - in that case use immediate, causal "
    "language (e.g. 'that ends her run in the Round of 16', 'with that loss, her tournament "
    "run is over', 'that's the title') and do NOT repeat the opponent's name, the score, or the "
    "round the way you just did in her match sentence - only add the NEW facts (that this loss "
    "ends her run, the ranking points, any historical comparison). Never say 'remains "
    "eliminated', 'is still out', 'was eliminated' (past tense implying an earlier day), or "
    "similar language for a result that just happened in the match you're narrating right now - "
    "that phrasing is reserved for the 'detailed'/'brief' cases below, where the elimination/"
    "title did NOT come from a match you're narrating today (e.g. it happened on an earlier "
    "reporting day, or no match is being reported for her at all this run). "
    "General naming rule for every player (Top N and featured alike): introduce her by her full "
    "name once (the first time she's mentioned in her own story/segment), then prefer her first "
    "name or a clear pronoun for the rest of that story/segment - do not mechanically repeat the "
    "full name sentence after sentence. Be especially careful right after another player's name "
    "has just been mentioned (e.g. the player who eliminated her): use her first name there "
    "rather than a bare 'she'/'her', since a pronoun immediately after another player's name is "
    "ambiguous about who it refers to (e.g. prefer 'Jessica Pegula eliminated Emma Navarro in "
    "the Round of 32. Emma earned 65 ranking points...' over '...She earned 65 ranking "
    "points...')."
)


def _tournament_status_line(status: TournamentRunStatus | None, match: MatchResult | None) -> str | None:
    """A single precomputed-facts line for the LLM to phrase (never
    recompute) - ``None`` when there's nothing worth mentioning.

    Only ELIMINATED/CHAMPION get a substantive line; ACTIVE/
    DID_NOT_PARTICIPATE/UNKNOWN get an explicit "nothing to report" line
    so the model doesn't need to guess why it's absent, but the system
    prompt tells it to say nothing narration-wise for those states either
    way.

    ``match`` should be this same player's "Latest match" result (if
    any) - used only to add an explicit "just happened" flag (see
    :func:`wta_daily.scripts_gen.tournament_status_narration.is_result_of_reported_match`)
    telling the model whether this status came from the match it's
    already narrating for this player, which changes how it should be
    phrased (see the system prompt).
    """

    if status is None:
        return None
    if status.state not in (TournamentState.ELIMINATED, TournamentState.CHAMPION):
        return f"{status.state.value}, no elimination/title context to add"

    if is_result_of_reported_match(status, match):
        detail = "just happened, from the match you're already narrating for her"
    elif status.is_new_development:
        detail = "detailed"
    else:
        detail = "brief"
    parts = [f"{status.state.value} ({detail})"]
    if status.round_label:
        parts.append(f"round reached: {status.round_label}")
    if status.eliminated_by:
        parts.append(f"eliminated by: {status.eliminated_by}")
    if status.points_earned is not None:
        parts.append(f"points earned this run: {status.points_earned}")
    if status.previous_year_round_label:
        parts.append(f"previous year's round at this event: {status.previous_year_round_label}")
    if status.points_delta is not None:
        parts.append(f"net points swing vs. previous year once it rolls off: {status.points_delta}")
    return "; ".join(parts)


def _build_user_prompt(report: DailyReport, config: ScriptConfig) -> str:
    target_date = report.match_target_date
    lines = [
        f"Date: {report.report_date.isoformat()}",
        f"Tour: {report.tour.upper()}",
        (
            f"Target length: {config.target_minutes_low:.0f}-{config.target_minutes_high:.0f} minutes "
            f"at roughly {config.words_per_minute} words per minute."
        ),
    ]
    if target_date is not None:
        lines.append(
            f"Match target date: {target_date.isoformat()} - every 'Latest match' below is "
            f"confirmed to have been completed on this date, or is explicitly absent if the "
            f"player did not play on it."
        )
    lines.extend(["", "Players, ranked 1..N:"])
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
        line = (
            f"- Rank {player.rank} (movement: {player.movement.value}, "
            f"previous rank: {player.previous_rank}): {player.name}, {player.points} points. "
            f"Latest match: {match_desc}."
        )
        status_line = _tournament_status_line(player.tournament_status, player.match)
        if status_line:
            line += f" Tournament status: {status_line}."
        lines.append(line)

    featured = report.featured_player
    if featured is not None:
        lines.extend(["", "Featured player (see system prompt for how to use this):"])
        if featured.rank is None:
            lines.append(
                f"- {featured.name}: current rank unavailable this run "
                f"({featured.rank_error or 'no reason given'}) - omit the segment entirely."
            )
        else:
            match_desc = "no completed match to report"
            if featured.match is not None:
                outcome = "won" if featured.match.won else "lost"
                match_desc = (
                    f"{outcome} vs {featured.match.opponent} {featured.match.score} "
                    f"({featured.match.round}, {featured.match.tournament})"
                )
            elif featured.match_error:
                match_desc = f"match data unavailable ({featured.match_error})"
            featured_line = (
                f"- {featured.name}: rank {featured.rank} (movement: "
                f"{featured.movement.value if featured.movement else 'unknown'}, previous rank: "
                f"{featured.previous_rank}), in Top {len(report.players)}: "
                f"{featured.rank <= len(report.players)}. Latest match: {match_desc}."
            )
            status_line = _tournament_status_line(featured.tournament_status, featured.match)
            if status_line:
                featured_line += f" Tournament status: {status_line}."
            lines.append(featured_line)

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
