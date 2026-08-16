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


def test_get_previous_player_rank_from_tracked_history(tmp_path: Path) -> None:
    store = RankingsSnapshotStore(tmp_path)
    store.save_snapshot(date(2026, 8, 15), "wta", [_ranking(1, "a"), _ranking(2, "b")])

    assert store.get_previous_player_rank(date(2026, 8, 16), "wta", "b") == 2


def test_get_previous_player_rank_from_featured_players(tmp_path: Path) -> None:
    """A player tracked outside the top_n group (e.g. a featured player who
    isn't currently in the Top N) must still get a previous-rank lookup, so
    her movement can be computed the same way as anyone else's."""

    store = RankingsSnapshotStore(tmp_path)
    store.save_snapshot(
        date(2026, 8, 15),
        "wta",
        [_ranking(1, "a")],
        featured_players={"emma": _ranking(28, "emma")},
    )

    assert store.get_previous_player_rank(date(2026, 8, 16), "wta", "emma") == 28
    assert store.get_previous_player_rank(date(2026, 8, 16), "wta", "a") == 1


def test_get_previous_player_rank_none_when_never_tracked(tmp_path: Path) -> None:
    store = RankingsSnapshotStore(tmp_path)
    store.save_snapshot(date(2026, 8, 15), "wta", [_ranking(1, "a")])

    assert store.get_previous_player_rank(date(2026, 8, 16), "wta", "never-tracked") is None


def test_get_previous_player_rank_none_when_no_history_at_all(tmp_path: Path) -> None:
    store = RankingsSnapshotStore(tmp_path)

    assert store.get_previous_player_rank(date(2026, 8, 16), "wta", "anyone") is None


def test_save_snapshot_without_featured_players_omits_the_key(tmp_path: Path) -> None:
    """Calling save_snapshot the old way (no featured_players) must not add
    an empty key to the history entry - keeps existing history files'
    shape stable when the feature is disabled."""

    store = RankingsSnapshotStore(tmp_path)
    store.save_snapshot(date(2026, 8, 15), "wta", [_ranking(1, "a")])

    history = store.load_history()
    assert "featured_players" not in history[0]


def test_update_players_cache_accepts_a_wider_group_than_the_history(tmp_path: Path) -> None:
    """A wider rankings pool (e.g. Top 25 fetched alongside a Top 10 report,
    in the same single API request) can safely enrich the player-metadata
    cache without affecting movement history at all - see the method's
    docstring for why these two files are deliberately decoupled."""

    store = RankingsSnapshotStore(tmp_path)
    tracked = [_ranking(1, "a"), _ranking(2, "b")]
    pool = tracked + [_ranking(11, "outside-top-n")]

    store.save_snapshot(date(2026, 8, 1), "wta", tracked)
    store.update_players_cache(pool)

    cache = store.load_players_cache()
    assert "outside-top-n" in cache

    history = store.load_history()
    tracked_ids = {r["player_id"] for r in history[0]["rankings"]}
    assert tracked_ids == {"a", "b"}
    assert "outside-top-n" not in tracked_ids
