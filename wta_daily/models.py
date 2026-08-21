"""Core data models shared across the whole pipeline.

Every model in this module is a plain :mod:`dataclasses` value object with a
``to_dict``/``from_dict`` pair so that reports can be serialized to JSON
(``report.json``) and reloaded without depending on any particular provider
implementation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum
from typing import Any


class Movement(StrEnum):
    """Direction a player moved in the rankings compared to the previous snapshot.

    ``NEW`` and ``UNKNOWN`` look similar but mean different things, and
    mixing them up is exactly what produced misleading first-run narration
    in production (every established Top 10 player described as "a new
    face"):

    * ``NEW`` means a previous snapshot *exists* and this specific player
      was not ranked in the tracked group in it - a genuine new entrant.
    * ``UNKNOWN`` means there is no previous snapshot at all to compare
      against (typically the application's first-ever run for this tour),
      so nothing can honestly be said about whether the player moved,
      stayed the same, or is new. Narration/graphics should use neutral
      "current rank" language for this case, never "just entered".
    """

    UP = "up"
    DOWN = "down"
    SAME = "same"
    NEW = "new"
    UNKNOWN = "unknown"

    @property
    def arrow(self) -> str:
        """A simple text arrow representation, handy for logs and scripts."""

        return {
            Movement.UP: "\u2191",  # ↑
            Movement.DOWN: "\u2193",  # ↓
            Movement.SAME: "\u2014",  # —
            Movement.NEW: "NEW",
            Movement.UNKNOWN: "?",
        }[self]


@dataclass(frozen=True)
class PlayerRanking:
    """A single player's position in the **officially published** WTA
    ranking list - never a live/in-tournament/projected figure.

    ``rank``/``points`` are exactly the values the ranking source (see
    :class:`~wta_daily.plugins.base.RankingsProvider`) reports for its most
    recently published list; nothing in this application recalculates or
    adjusts them from daily match results - see the README's "Official
    ranking vs. daily match activity" section for the architectural
    guarantee this supports.

    ``ranking_date`` is the publication date of that official list, if the
    provider exposes one (``wta_official`` does, via the upstream API's
    ``rankedAt`` field - the same value for every player in one response,
    since it identifies the *list*, not the player). ``None`` for a
    provider that doesn't supply this (e.g. the offline ``sample``
    fixture) - callers must treat that as "unknown, not necessarily
    different from any other snapshot," never as "changed." This is what
    lets the pipeline tell "a new official ranking was published" apart
    from "the same list was simply fetched again on a different calendar
    day" - see :func:`wta_daily.movement.compute_movement`'s
    ``same_official_ranking_list`` parameter.
    """

    rank: int
    player_id: str
    name: str
    country_code: str
    points: int
    previous_rank: int | None = None
    ranking_date: date | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "rank": self.rank,
            "player_id": self.player_id,
            "name": self.name,
            "country_code": self.country_code,
            "points": self.points,
            "previous_rank": self.previous_rank,
            "ranking_date": self.ranking_date.isoformat() if self.ranking_date else None,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PlayerRanking:
        raw_ranking_date = data.get("ranking_date")
        return cls(
            rank=int(data["rank"]),
            player_id=str(data["player_id"]),
            name=str(data["name"]),
            country_code=str(data.get("country_code", "")),
            points=int(data.get("points", 0)),
            previous_rank=data.get("previous_rank"),
            ranking_date=date.fromisoformat(raw_ranking_date) if raw_ranking_date else None,
        )


@dataclass(frozen=True)
class MatchResult:
    """The outcome of a single completed match.

    ``match_date`` is the date the individual match was actually played, as
    opposed to the date the tournament started. It is ``None`` whenever a
    provider cannot establish that date from an authoritative, match-level
    source - per the project's rule that an unknown date is preferable to a
    confidently incorrect one (e.g. silently substituting the tournament's
    start date). ``opponent``/``tournament``/``score``/``won`` are expected
    to be known whenever a :class:`MatchResult` exists at all.

    ``round`` is ``None`` when a provider's raw round identifier couldn't be
    confidently normalized into a real round name (see
    :mod:`wta_daily.rounds` and
    :mod:`wta_daily.plugins.matches.wta_official`'s ``_fallback_round_label``)
    - the same "an unknown fact is preferable to a confidently wrong one"
    rule as ``match_date``. Every narration/graphics consumer of this field
    must gracefully omit the round rather than expose a raw, unexplained
    provider code (e.g. a bare letter like ``"Q"``) or a literal ``"None"``.
    """

    opponent: str
    tournament: str
    round: str | None
    score: str
    won: bool
    match_date: date | None
    surface: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "opponent": self.opponent,
            "tournament": self.tournament,
            "round": self.round,
            "score": self.score,
            "won": self.won,
            "date": self.match_date.isoformat() if self.match_date else None,
            "surface": self.surface,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MatchResult:
        raw_date = data.get("date")
        raw_round = data.get("round")
        return cls(
            opponent=str(data["opponent"]),
            tournament=str(data["tournament"]),
            round=str(raw_round) if raw_round is not None else None,
            score=str(data["score"]),
            won=bool(data["won"]),
            match_date=date.fromisoformat(raw_date) if raw_date else None,
            surface=data.get("surface"),
        )


class TournamentState(StrEnum):
    """A player's status in the specific tournament her most recent
    activity relates to - deliberately more granular than "played
    yesterday or not," so narration never has to say something as
    unhelpful as "she did not play yesterday" when the real, more useful
    story is that she was already eliminated (see
    :mod:`wta_daily.plugins.matches.wta_official`'s tournament-status
    logic and the README's "Tournament elimination context" section).

    * ``ACTIVE`` - still alive in the draw (has an unplayed fixture, or
      her most recent finished fixture was a win that wasn't the final).
    * ``ELIMINATED`` - her run ended in a loss; ``round_reached`` and
      ``eliminated_by`` on :class:`TournamentRunStatus` describe how.
    * ``CHAMPION`` - won the final.
    * ``DID_NOT_PARTICIPATE`` - not found in any currently-relevant
      tournament's draw at all (the ordinary case on a day with no
      tournament activity for her - not an error).
    * ``UNKNOWN`` - couldn't be determined this run (e.g. a fetch
      failure, or a match provider with no tournament-draw visibility at
      all - see :meth:`~wta_daily.plugins.base.MatchProvider.get_matches_for_date`'s
      default, which never fabricates this).
    """

    ACTIVE = "active"
    ELIMINATED = "eliminated"
    CHAMPION = "champion"
    DID_NOT_PARTICIPATE = "did_not_participate"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class TournamentRunStatus:
    """Everything known about a player's run in her current/most recent
    tournament, including - when reliably determinable - how that
    compares to her result at the *same* tournament last year.

    Every field here is deterministic application data: ``points_earned``/
    ``previous_year_points``/``points_delta`` come from
    :mod:`wta_daily.points_table` (never an LLM guess - see that module's
    docstring), and ``previous_year_round`` comes only from a real,
    matching previous-year tournament fixture found through the same
    provider architecture as everything else (never invented - see
    :mod:`wta_daily.plugins.matches.wta_official`). Any fact that
    couldn't be reliably determined is ``None`` rather than guessed, so
    narration can degrade gracefully field by field (see the README's
    "Tournament elimination context" section for the exact hierarchy).

    ``points_delta`` is deliberately **not** "points gained toward her
    ranking" - it's ``points_earned - previous_year_points`` (when both
    are known), i.e. the *net swing* from this specific tournament once
    last year's result eventually rolls off the rolling 52-week window.
    It is never the player's real-time ranking-points total, which only
    the official ranking list itself (see
    :class:`~wta_daily.models.PlayerRanking`) represents.

    ``is_new_development`` is set by the pipeline (never the match
    provider, which has no notion of "already reported") by comparing
    against the last thing recorded for this player in
    :mod:`wta_daily.persistence.tournament_status_store` - ``True`` the
    first time a given ``(tournament_group_id, year, round_reached)``
    triple is seen, ``False`` on every subsequent day it's still current,
    which is what lets narration go into full detail once and stay brief
    after that (see the README's "detailed once, brief afterward" note).
    """

    state: TournamentState
    tournament: str | None = None
    tournament_group_id: str | None = None
    category: str | None = None
    round_reached: str | None = None
    round_label: str | None = None
    eliminated_by: str | None = None
    points_earned: int | None = None
    previous_year_round: str | None = None
    previous_year_round_label: str | None = None
    previous_year_points: int | None = None
    points_delta: int | None = None
    is_new_development: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self.state.value,
            "tournament": self.tournament,
            "tournament_group_id": self.tournament_group_id,
            "category": self.category,
            "round_reached": self.round_reached,
            "round_label": self.round_label,
            "eliminated_by": self.eliminated_by,
            "points_earned": self.points_earned,
            "previous_year_round": self.previous_year_round,
            "previous_year_round_label": self.previous_year_round_label,
            "previous_year_points": self.previous_year_points,
            "points_delta": self.points_delta,
            "is_new_development": self.is_new_development,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TournamentRunStatus:
        return cls(
            state=TournamentState(data.get("state", "unknown")),
            tournament=data.get("tournament"),
            tournament_group_id=data.get("tournament_group_id"),
            category=data.get("category"),
            round_reached=data.get("round_reached"),
            round_label=data.get("round_label"),
            eliminated_by=data.get("eliminated_by"),
            points_earned=data.get("points_earned"),
            previous_year_round=data.get("previous_year_round"),
            previous_year_round_label=data.get("previous_year_round_label"),
            previous_year_points=data.get("previous_year_points"),
            points_delta=data.get("points_delta"),
            is_new_development=bool(data.get("is_new_development", True)),
        )


@dataclass(frozen=True)
class MatchLookupResult:
    """Outcome of a day-first batch match lookup (:meth:`MatchProvider.get_matches_for_date`)
    for a set of players.

    ``matches`` holds confirmed results, keyed by ``player_id``, for players
    who completed a singles match on the requested date.

    ``unresolved_player_ids`` holds the ``player_id``\\ s this source could
    not determine one way or the other for that date (e.g. a data-fetch
    failure for the specific tournament that would have contained their
    result) - **distinct** from a player_id simply absent from ``matches``,
    which means this source *did* check and positively confirmed that player
    did not play. This distinction is what lets a composite provider (see
    :class:`~wta_daily.plugins.matches.best_of.BestOfMatchProvider`) stop
    asking further sources about a player once her status is genuinely
    confirmed, instead of re-querying every configured (including paid)
    source for every non-playing player on every run.
    """

    matches: dict[str, MatchResult] = field(default_factory=dict)
    unresolved_player_ids: frozenset[str] = field(default_factory=frozenset)
    #: Per-player tournament run status (see :class:`TournamentRunStatus`),
    #: keyed by ``player_id`` - populated only by a provider with genuine
    #: tournament-draw visibility (``wta_official``'s day-first
    #: infrastructure); every other provider simply omits a player here,
    #: which downstream code must treat identically to an explicit
    #: :attr:`TournamentState.UNKNOWN`, never as an error.
    tournament_status: dict[str, TournamentRunStatus] = field(default_factory=dict)


@dataclass
class PlayerReport:
    """Everything the downstream script/graphics/video steps need for one player.

    ``rank``/``points``/``movement`` all describe the player's position on
    the **officially published** WTA ranking list for this report (see
    :class:`PlayerRanking` and :func:`wta_daily.movement.compute_movement`)
    - they are never recalculated from ``match`` below. ``match`` is a
    completely independent fact ("did she play, and what happened, on the
    specific date this report covers") that affects the *narration* for
    this player but must never be allowed to imply a ranking change by
    itself; every consumer (graphics, script generator, YouTube
    description) is expected to keep these two concerns in separate
    sentences/fields rather than deriving one from the other.
    """

    rank: int
    name: str
    player_id: str
    country_code: str
    points: int
    movement: Movement
    previous_rank: int | None = None
    match: MatchResult | None = None
    match_error: str | None = None
    #: See :class:`TournamentRunStatus`. ``None`` whenever the configured
    #: match provider has no tournament-draw visibility (the ordinary
    #: case for e.g. the offline ``sample`` fixture) - callers must treat
    #: that identically to :attr:`TournamentState.UNKNOWN`.
    tournament_status: TournamentRunStatus | None = None

    @property
    def played(self) -> bool:
        return self.match is not None

    @property
    def won(self) -> bool | None:
        return self.match.won if self.match else None

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "rank": self.rank,
            "movement": self.movement.value,
            "previous_rank": self.previous_rank,
            "name": self.name,
            "player_id": self.player_id,
            "country_code": self.country_code,
            "points": self.points,
            "played": self.played,
            "won": self.won,
        }
        if self.match is not None:
            data["opponent"] = self.match.opponent
            data["score"] = self.match.score
            data["tournament"] = self.match.tournament
            data["round"] = self.match.round
            data["match_date"] = self.match.match_date.isoformat() if self.match.match_date else None
            data["surface"] = self.match.surface
        else:
            data["opponent"] = None
            data["score"] = None
            data["tournament"] = None
            data["round"] = None
            data["match_date"] = None
            data["surface"] = None
        if self.match_error:
            data["match_error"] = self.match_error
        if self.tournament_status is not None:
            data["tournament_status"] = self.tournament_status.to_dict()
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PlayerReport:
        match = None
        if data.get("tournament") and data.get("opponent"):
            raw_match_date = data.get("match_date")
            match = MatchResult(
                opponent=data["opponent"],
                tournament=data["tournament"],
                round=data.get("round", ""),
                score=data.get("score", ""),
                won=bool(data.get("won")),
                match_date=date.fromisoformat(raw_match_date) if raw_match_date else None,
                surface=data.get("surface"),
            )
        raw_tournament_status = data.get("tournament_status")
        return cls(
            rank=int(data["rank"]),
            name=str(data["name"]),
            player_id=str(data["player_id"]),
            country_code=str(data.get("country_code", "")),
            points=int(data.get("points", 0)),
            movement=Movement(data.get("movement", "new")),
            previous_rank=data.get("previous_rank"),
            match=match,
            match_error=data.get("match_error"),
            tournament_status=(
                TournamentRunStatus.from_dict(raw_tournament_status) if raw_tournament_status else None
            ),
        )


@dataclass
class FeaturedPlayerReport:
    """A recurring, editorially-flavored spotlight on one specific player,
    tracked independently of (and never mixed into) the official Top N list
    - see :class:`~wta_daily.config.FeaturedPlayerConfig`.

    Every fact here (``rank``, ``points``, ``movement``, ``match``) is
    retrieved through exactly the same provider architecture as the Top N -
    ``rank``/``points``/``movement`` describe her position on the
    **officially published** WTA list (see :class:`PlayerReport`'s
    docstring for the same guarantee), never a total recalculated from
    ``match``. Only the *narration* built from this model is allowed to
    editorialize (see :mod:`wta_daily.scripts_gen.featured_player_phrases`),
    and even then only by describing these two facts in separate sentences,
    never by inventing a ranking change from a match result. A fact that
    could not be determined this run is ``None`` rather than guessed -
    ``rank_error``/``match_error`` explain why when that happens, without
    treating it as a fatal error for the rest of the pipeline.
    """

    name: str
    player_id: str
    tagline: str
    country_code: str = ""
    rank: int | None = None
    points: int | None = None
    movement: Movement | None = None
    previous_rank: int | None = None
    match: MatchResult | None = None
    match_error: str | None = None
    rank_error: str | None = None
    #: See :class:`TournamentRunStatus`; ``None`` under the same
    #: circumstances as :attr:`PlayerReport.tournament_status`.
    tournament_status: TournamentRunStatus | None = None

    @property
    def played(self) -> bool | None:
        """``None`` when we don't even know her rank this run (nothing to
        report at all), as opposed to ``False`` for a confirmed non-match."""

        if self.rank is None:
            return None
        return self.match is not None

    @property
    def won(self) -> bool | None:
        return self.match.won if self.match else None

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "name": self.name,
            "player_id": self.player_id,
            "tagline": self.tagline,
            "country_code": self.country_code,
            "rank": self.rank,
            "points": self.points,
            "movement": self.movement.value if self.movement is not None else None,
            "previous_rank": self.previous_rank,
            "played": self.played,
            "won": self.won,
        }
        if self.match is not None:
            data["opponent"] = self.match.opponent
            data["score"] = self.match.score
            data["tournament"] = self.match.tournament
            data["round"] = self.match.round
            data["match_date"] = self.match.match_date.isoformat() if self.match.match_date else None
            data["surface"] = self.match.surface
        else:
            data["opponent"] = None
            data["score"] = None
            data["tournament"] = None
            data["round"] = None
            data["match_date"] = None
            data["surface"] = None
        if self.match_error:
            data["match_error"] = self.match_error
        if self.rank_error:
            data["rank_error"] = self.rank_error
        if self.tournament_status is not None:
            data["tournament_status"] = self.tournament_status.to_dict()
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FeaturedPlayerReport:
        match = None
        if data.get("tournament") and data.get("opponent"):
            raw_match_date = data.get("match_date")
            match = MatchResult(
                opponent=data["opponent"],
                tournament=data["tournament"],
                round=data.get("round", ""),
                score=data.get("score", ""),
                won=bool(data.get("won")),
                match_date=date.fromisoformat(raw_match_date) if raw_match_date else None,
                surface=data.get("surface"),
            )
        movement_raw = data.get("movement")
        raw_tournament_status = data.get("tournament_status")
        return cls(
            name=str(data["name"]),
            player_id=str(data["player_id"]),
            tagline=str(data.get("tagline", "")),
            country_code=str(data.get("country_code", "")),
            rank=data.get("rank"),
            points=data.get("points"),
            movement=Movement(movement_raw) if movement_raw else None,
            previous_rank=data.get("previous_rank"),
            match=match,
            match_error=data.get("match_error"),
            rank_error=data.get("rank_error"),
            tournament_status=(
                TournamentRunStatus.from_dict(raw_tournament_status) if raw_tournament_status else None
            ),
        )


@dataclass
class DailyReport:
    """The complete, self-contained result of one day's pipeline run.

    ``match_target_date`` is the specific calendar date (UTC) that
    ``players[*].match`` answers "did she play on this day" for - not
    necessarily the same as ``report_date`` (the day the job ran/the video
    covers). A player with ``match is None`` did not have a confirmed
    completed match on ``match_target_date``; nothing is ever substituted
    from an earlier date. ``None`` here only for reports produced before
    this field existed.
    """

    report_date: date
    tour: str
    players: list[PlayerReport] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    match_target_date: date | None = None
    #: The recurring featured-player spotlight (see
    #: :class:`~wta_daily.config.FeaturedPlayerConfig`), kept in its own
    #: field rather than injected into `players` - she is only "official
    #: Top N" when her real rank actually qualifies. `None` whenever the
    #: feature is disabled.
    featured_player: FeaturedPlayerReport | None = None
    #: Publication date of the officially published WTA ranking list that
    #: every player's ``rank``/``points``/``movement`` in this report is
    #: based on (see :class:`PlayerRanking`'s docstring for where this
    #: comes from) - ``None`` when the configured rankings provider doesn't
    #: expose one (e.g. the offline ``sample`` fixture). This is *not*
    #: necessarily the same as ``report_date``: the official list stays
    #: the same for the whole ranking week, so this date only changes when
    #: the WTA actually publishes a new one, which is exactly the point -
    #: see the README's "Official ranking vs. daily match activity" section.
    ranking_date: date | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "date": self.report_date.isoformat(),
            "tour": self.tour,
            "match_target_date": (
                self.match_target_date.isoformat() if self.match_target_date else None
            ),
            "ranking_date": self.ranking_date.isoformat() if self.ranking_date else None,
            "players": [p.to_dict() for p in self.players],
            "featured_player": self.featured_player.to_dict() if self.featured_player else None,
            "errors": self.errors,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DailyReport:
        raw_target_date = data.get("match_target_date")
        raw_ranking_date = data.get("ranking_date")
        raw_featured_player = data.get("featured_player")
        return cls(
            report_date=date.fromisoformat(data["date"]),
            tour=data.get("tour", "wta"),
            players=[PlayerReport.from_dict(p) for p in data.get("players", [])],
            errors=list(data.get("errors", [])),
            match_target_date=date.fromisoformat(raw_target_date) if raw_target_date else None,
            ranking_date=date.fromisoformat(raw_ranking_date) if raw_ranking_date else None,
            featured_player=(
                FeaturedPlayerReport.from_dict(raw_featured_player) if raw_featured_player else None
            ),
        )
