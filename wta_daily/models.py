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
    """A single player's position in a rankings snapshot."""

    rank: int
    player_id: str
    name: str
    country_code: str
    points: int
    previous_rank: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "rank": self.rank,
            "player_id": self.player_id,
            "name": self.name,
            "country_code": self.country_code,
            "points": self.points,
            "previous_rank": self.previous_rank,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PlayerRanking:
        return cls(
            rank=int(data["rank"]),
            player_id=str(data["player_id"]),
            name=str(data["name"]),
            country_code=str(data.get("country_code", "")),
            points=int(data.get("points", 0)),
            previous_rank=data.get("previous_rank"),
        )


@dataclass(frozen=True)
class MatchResult:
    """The outcome of a single completed match.

    ``match_date`` is the date the individual match was actually played, as
    opposed to the date the tournament started. It is ``None`` whenever a
    provider cannot establish that date from an authoritative, match-level
    source - per the project's rule that an unknown date is preferable to a
    confidently incorrect one (e.g. silently substituting the tournament's
    start date). Every field below other than ``match_date`` is expected to
    be known whenever a :class:`MatchResult` exists at all.
    """

    opponent: str
    tournament: str
    round: str
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
        return cls(
            opponent=str(data["opponent"]),
            tournament=str(data["tournament"]),
            round=str(data["round"]),
            score=str(data["score"]),
            won=bool(data["won"]),
            match_date=date.fromisoformat(raw_date) if raw_date else None,
            surface=data.get("surface"),
        )


@dataclass
class PlayerReport:
    """Everything the downstream script/graphics/video steps need for one player."""

    rank: int
    name: str
    player_id: str
    country_code: str
    points: int
    movement: Movement
    previous_rank: int | None = None
    match: MatchResult | None = None
    match_error: str | None = None

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
        )


@dataclass
class DailyReport:
    """The complete, self-contained result of one day's pipeline run."""

    report_date: date
    tour: str
    players: list[PlayerReport] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "date": self.report_date.isoformat(),
            "tour": self.tour,
            "players": [p.to_dict() for p in self.players],
            "errors": self.errors,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DailyReport:
        return cls(
            report_date=date.fromisoformat(data["date"]),
            tour=data.get("tour", "wta"),
            players=[PlayerReport.from_dict(p) for p in data.get("players", [])],
            errors=list(data.get("errors", [])),
        )
