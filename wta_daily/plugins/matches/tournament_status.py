"""Pure logic for determining a player's status within one WTA tournament
draw, from that tournament's full fixture list (see
:meth:`~wta_daily.plugins.wta_api_client.WtaOfficialApiClient.get_tournament_matches`).

Deliberately separate from :mod:`wta_daily.plugins.matches.wta_official` so
this can be unit-tested directly against realistic fixture data, with no
HTTP mocking required - and so the exact same logic can answer both "what
is her status in the *current* tournament" and "what was her result at
this *same* tournament last year" (see
:func:`determine_tournament_run_status`'s docstring) without duplicating
the fixture-scanning rules for each question.

Never computes ranking points or a previous-year comparison itself - that
enrichment belongs to the caller (see
:mod:`wta_daily.points_table`/:mod:`wta_daily.plugins.matches.wta_official`),
which is what keeps this module's only job "read fixtures, answer a
factual question about one player."
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from wta_daily.models import TournamentRunStatus, TournamentState
from wta_daily.rounds import normalize_wta_round_id, round_label, round_rank

#: A completed, "genuinely finished" fixture - matches
#: wta_official.py's _FINISHED_MATCH_STATE.
_FINISHED_MATCH_STATE = "F"
_SINGLES = "S"
_MAIN_DRAW = "M"
_WINNER_SLOT = {"2": "A", "3": "B"}


@dataclass(frozen=True)
class _FinishedOutcome:
    round_code: str
    won: bool
    opponent_name: str


def _opponent_name(fixture: dict[str, Any], our_slot: str) -> str:
    first_a = str(fixture.get("PlayerNameFirstA", "")).strip()
    last_a = str(fixture.get("PlayerNameLastA", "")).strip()
    first_b = str(fixture.get("PlayerNameFirstB", "")).strip()
    last_b = str(fixture.get("PlayerNameLastB", "")).strip()
    name = f"{first_b} {last_b}".strip() if our_slot == "A" else f"{first_a} {last_a}".strip()
    return name or "Unknown Opponent"


def determine_tournament_run_status(
    fixtures: list[dict[str, Any]],
    player_id: str,
    *,
    tournament_name: str,
    tournament_group_id: str | int,
    category: str | None,
    draw_size: int | None,
) -> TournamentRunStatus:
    """Determine ``player_id``'s status from one tournament's *complete*
    fixture list (every round, not date-filtered).

    Reusable for two different questions with the exact same logic:
    "what's her status in the tournament this fixture list is for" (pass
    the current edition's fixtures) and "what did she do at this same
    tournament last year" (pass the previous year's edition's fixtures,
    looked up by the same ``tournament_group_id`` under a different
    ``year`` - see :mod:`wta_daily.plugins.matches.wta_official`). Only
    ``DrawLevelType == "M"`` (main draw) ``DrawMatchType == "S"`` (singles)
    fixtures are considered; qualifying and doubles are irrelevant to a
    Top N/featured player's *main-draw* run.

    * Any unfinished fixture involving this player -> :attr:`TournamentState.ACTIVE`
      (she has a match still to come, or in progress).
    * No fixture at all involving this player -> :attr:`TournamentState.DID_NOT_PARTICIPATE`.
    * Otherwise, her *latest* (by round order) finished fixture decides it:
      a loss -> :attr:`TournamentState.ELIMINATED` at that round; a win in
      the final -> :attr:`TournamentState.CHAMPION`; a win that isn't the
      final -> still :attr:`TournamentState.ACTIVE` (she may have simply
      advanced to a round whose fixture isn't in the feed yet - never
      guess a terminal state from an incomplete-looking draw).

    Never raises on malformed fixture data - a fixture missing a
    derivable winner, or whose round can't be normalized, is simply
    skipped rather than treated as a hard failure; the caller's own
    try/except around the whole day's work is what should catch anything
    that means "this tournament's data was fundamentally unreadable."
    """

    outcomes: list[_FinishedOutcome] = []
    has_unplayed = False
    target_id = str(player_id)

    for fixture in fixtures:
        if fixture.get("DrawLevelType") != _MAIN_DRAW or fixture.get("DrawMatchType") != _SINGLES:
            continue
        player_a, player_b = str(fixture.get("PlayerIDA", "")), str(fixture.get("PlayerIDB", ""))
        if target_id not in (player_a, player_b):
            continue
        our_slot = "A" if target_id == player_a else "B"

        if fixture.get("MatchState") != _FINISHED_MATCH_STATE:
            has_unplayed = True
            continue

        winner_slot = _WINNER_SLOT.get(str(fixture.get("Winner")))
        if winner_slot is None:
            continue  # marked finished but no derivable winner - unusable

        round_code = normalize_wta_round_id(str(fixture.get("RoundID", "")), draw_size=draw_size)
        if round_code is None:
            continue

        outcomes.append(
            _FinishedOutcome(
                round_code=round_code,
                won=(winner_slot == our_slot),
                opponent_name=_opponent_name(fixture, our_slot),
            )
        )

    group_id_str = str(tournament_group_id)

    if has_unplayed:
        return TournamentRunStatus(
            state=TournamentState.ACTIVE,
            tournament=tournament_name,
            tournament_group_id=group_id_str,
            category=category,
        )

    if not outcomes:
        return TournamentRunStatus(state=TournamentState.DID_NOT_PARTICIPATE)

    latest = max(outcomes, key=lambda o: round_rank(o.round_code) or -1)

    if latest.won:
        if latest.round_code == "F":
            return TournamentRunStatus(
                state=TournamentState.CHAMPION,
                tournament=tournament_name,
                tournament_group_id=group_id_str,
                category=category,
                round_reached="W",
                round_label=round_label("W", category=category),
            )
        return TournamentRunStatus(
            state=TournamentState.ACTIVE,
            tournament=tournament_name,
            tournament_group_id=group_id_str,
            category=category,
        )

    return TournamentRunStatus(
        state=TournamentState.ELIMINATED,
        tournament=tournament_name,
        tournament_group_id=group_id_str,
        category=category,
        round_reached=latest.round_code,
        round_label=round_label(latest.round_code, category=category),
        eliminated_by=latest.opponent_name,
    )
