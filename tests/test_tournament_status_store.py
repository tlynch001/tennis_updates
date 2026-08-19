"""Unit tests for wta_daily.persistence.tournament_status_store."""

from __future__ import annotations

from pathlib import Path

from wta_daily.models import TournamentRunStatus, TournamentState
from wta_daily.persistence.tournament_status_store import TournamentStatusStore


def _eliminated(group_id: str = "1017", round_reached: str = "R16") -> TournamentRunStatus:
    return TournamentRunStatus(
        state=TournamentState.ELIMINATED,
        tournament="Cincinnati",
        tournament_group_id=group_id,
        category="WTA 1000",
        round_reached=round_reached,
        round_label="the Round of 16",
        eliminated_by="Some Rival",
    )


def test_first_report_of_an_elimination_is_new(tmp_path: Path) -> None:
    store = TournamentStatusStore(tmp_path)

    resolved = store.resolve_is_new_development("P1", 2026, _eliminated())

    assert resolved.is_new_development is True


def test_same_elimination_reported_twice_is_not_new_the_second_time(tmp_path: Path) -> None:
    store = TournamentStatusStore(tmp_path)
    store.resolve_is_new_development("P1", 2026, _eliminated())

    resolved = store.resolve_is_new_development("P1", 2026, _eliminated())

    assert resolved.is_new_development is False


def test_advancing_further_and_then_losing_is_a_new_development(tmp_path: Path) -> None:
    """Simulates: eliminated in the QF one day (hypothetically reported),
    but a correction/rescan later shows a different round - a genuinely
    different result must be treated as new again."""

    store = TournamentStatusStore(tmp_path)
    store.resolve_is_new_development("P1", 2026, _eliminated(round_reached="QF"))

    resolved = store.resolve_is_new_development("P1", 2026, _eliminated(round_reached="SF"))

    assert resolved.is_new_development is True


def test_a_new_season_at_the_same_tournament_is_a_new_development(tmp_path: Path) -> None:
    store = TournamentStatusStore(tmp_path)
    store.resolve_is_new_development("P1", 2026, _eliminated())

    resolved = store.resolve_is_new_development("P1", 2027, _eliminated())

    assert resolved.is_new_development is True


def test_active_and_did_not_participate_are_always_reported_as_new_and_never_persisted(
    tmp_path: Path,
) -> None:
    store = TournamentStatusStore(tmp_path)
    active = TournamentRunStatus(state=TournamentState.ACTIVE, tournament="Cincinnati")
    dnp = TournamentRunStatus(state=TournamentState.DID_NOT_PARTICIPATE)

    resolved_active = store.resolve_is_new_development("P1", 2026, active)
    resolved_dnp = store.resolve_is_new_development("P2", 2026, dnp)

    assert resolved_active.is_new_development is True
    assert resolved_dnp.is_new_development is True
    assert store.load() == {}


def test_champion_status_is_tracked_independently_of_elimination(tmp_path: Path) -> None:
    store = TournamentStatusStore(tmp_path)
    champion = TournamentRunStatus(
        state=TournamentState.CHAMPION,
        tournament="Cincinnati",
        tournament_group_id="1017",
        round_reached="W",
        round_label="the title",
    )
    store.resolve_is_new_development("P1", 2026, champion)

    resolved = store.resolve_is_new_development("P1", 2026, champion)

    assert resolved.is_new_development is False


def test_different_players_are_tracked_independently(tmp_path: Path) -> None:
    store = TournamentStatusStore(tmp_path)
    store.resolve_is_new_development("P1", 2026, _eliminated())

    resolved = store.resolve_is_new_development("P2", 2026, _eliminated())

    assert resolved.is_new_development is True


def test_load_returns_empty_dict_when_file_does_not_exist(tmp_path: Path) -> None:
    store = TournamentStatusStore(tmp_path)

    assert store.load() == {}


def test_load_recovers_gracefully_from_a_corrupted_file(tmp_path: Path) -> None:
    store = TournamentStatusStore(tmp_path)
    store.path.parent.mkdir(parents=True, exist_ok=True)
    store.path.write_text("not valid json{{{", encoding="utf-8")

    assert store.load() == {}

    # Still usable afterward - treats it as "no history" and moves on.
    resolved = store.resolve_is_new_development("P1", 2026, _eliminated())
    assert resolved.is_new_development is True
