"""Core data models shared across the whole pipeline.

Every model in this module is a plain :mod:`dataclasses` value object with a
``to_dict``/``from_dict`` pair so that reports can be serialized to JSON
(``report.json``) and reloaded without depending on any particular provider
implementation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Any


class Movement(str, Enum):
    """Direction a player moved in the rankings compared to the previous snapshot."""

    UP = "up"
    DOWN = "down"
    SAME = "same"
    NEW = "new"

    @property
    def arrow(self) -> str:
        """A simple text arrow representation, handy for logs and scripts."""

        return {
            Movement.UP: "\u2191",  # ↑
            Movement.DOWN: "\u2193",  # ↓
            Movement.SAME: "\u2014",  # —
            Movement.NEW: "NEW",
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
    """The outcome of a single completed match."""

    opponent: str
    tournament: str
    round: str
    score: str
    won: bool
    match_date: date
    surface: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "opponent": self.opponent,
            "tournament": self.tournament,
            "round": self.round,
            "score": self.score,
            "won": self.won,
            "date": self.match_date.isoformat(),
            "surface": self.surface,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MatchResult:
        return cls(
            opponent=str(data["opponent"]),
            tournament=str(data["tournament"]),
            round=str(data["round"]),
            score=str(data["score"]),
            won=bool(data["won"]),
            match_date=date.fromisoformat(data["date"]),
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
            data["match_date"] = self.match.match_date.isoformat()
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
            match = MatchResult(
                opponent=data["opponent"],
                tournament=data["tournament"],
                round=data.get("round", ""),
                score=data.get("score", ""),
                won=bool(data.get("won")),
                match_date=date.fromisoformat(data["match_date"]),
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
