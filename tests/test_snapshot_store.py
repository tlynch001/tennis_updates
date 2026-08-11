from __future__ import annotations

from datetime import date
from pathlib import Path

from wta_daily.models import PlayerRanking
from wta_daily.persistence.snapshot_store import RankingsSnapshotStore


def _ranking(rank: int, player_id: str) -> PlayerRanking:
    return PlayerRanking(
        rank=rank,
        player_id=player_id,
        name=f"Player {player_id}",
        country_code="USA",
        points=1000 - rank,
    )


def test_save_and_load_snapshot_round_trip(tmp_path: Path) -> None:
    store = RankingsSnapshotStore(tmp_path)
    rankings = [_ranking(1, "a"), _ranking(2, "b")]

    store.save_snapshot(date(2026, 8, 1), "wta", rankings)

    history = store.load_history()
    assert len(history) == 1
    assert history[0]["date"] == "2026-08-01"
    assert history[0]["tour"] == "wta"


def test_get_previous_snapshot_returns_most_recent_before_date(tmp_path: Path) -> None:
    store = RankingsSnapshotStore(tmp_path)
    store.save_snapshot(date(2026, 8, 1), "wta", [_ranking(1, "a")])
    store.save_snapshot(date(2026, 8, 2), "wta", [_ranking(2, "a")])

    result = store.get_previous_snapshot(date(2026, 8, 3), "wta")
    assert result is not None
    snapshot_date, rankings = result
    assert snapshot_date == date(2026, 8, 2)
    assert rankings[0].rank == 2


def test_get_previous_snapshot_none_when_no_history(tmp_path: Path) -> None:
    store = RankingsSnapshotStore(tmp_path)
    assert store.get_previous_snapshot(date(2026, 8, 1), "wta") is None


def test_get_previous_snapshot_ignores_same_day(tmp_path: Path) -> None:
    store = RankingsSnapshotStore(tmp_path)
    store.save_snapshot(date(2026, 8, 1), "wta", [_ranking(1, "a")])

    assert store.get_previous_snapshot(date(2026, 8, 1), "wta") is None


def test_get_previous_snapshot_scoped_by_tour(tmp_path: Path) -> None:
    store = RankingsSnapshotStore(tmp_path)
    store.save_snapshot(date(2026, 8, 1), "atp", [_ranking(1, "a")])

    assert store.get_previous_snapshot(date(2026, 8, 2), "wta") is None


def test_save_snapshot_updates_players_cache(tmp_path: Path) -> None:
    store = RankingsSnapshotStore(tmp_path)
    store.save_snapshot(date(2026, 8, 1), "wta", [_ranking(1, "a")])

    cache = store.load_players_cache()
    assert cache["a"]["name"] == "Player a"
    assert cache["a"]["country_code"] == "USA"


def test_save_snapshot_overwrites_existing_entry_for_same_day(tmp_path: Path) -> None:
    store = RankingsSnapshotStore(tmp_path)
    store.save_snapshot(date(2026, 8, 1), "wta", [_ranking(1, "a")])
    store.save_snapshot(date(2026, 8, 1), "wta", [_ranking(5, "a")])

    history = store.load_history()
    assert len(history) == 1
    assert history[0]["rankings"][0]["rank"] == 5
