"""Unit tests for :mod:`wta_daily.plugins.matches.wta_official`.

These mock the underlying :class:`WtaOfficialApiClient` calls (never hitting
the network) with response shapes captured from the real API, and are the
regression suite for the August 2026 production incident: tournament start
dates being reported as match dates, and stale/incomplete player-match
history not being handled defensively.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from wta_daily.exceptions import PlayerDataError
from wta_daily.models import PlayerRanking
from wta_daily.plugins.matches.wta_official import WtaOfficialMatchProvider

PLAYER = PlayerRanking(rank=1, player_id="P1", name="Test Player", country_code="USA", points=8000)


def _sabalenka_ranking() -> PlayerRanking:
    return PlayerRanking(
        rank=1, player_id="sabalenka-id", name="Aryna Sabalenka", country_code="BLR", points=9000
    )


def _player_match(
    *,
    round_name: str = "R16",
    scores: str = "6-4 6-2",
    winner: int = 1,
    s_d_flag: str = "S",
    opponent_id: str | None = "P2",
    opponent_name: str = "Opponent Name",
    tournament_name: str = "SAMPLE OPEN",
    tournament_group_id: int | None = 900,
    tournament_year: int | None = 2026,
    tournament_start_date: str = "2026-01-01T00:00:00+00:00",
    surface: str = "HARD",
) -> dict[str, Any]:
    """Build one entry shaped like ``GET /players/{id}/matches`` returns."""

    return {
        "s_d_flag": s_d_flag,
        "scores": scores,
        "player_1": "P1",
        "player_2": "P2",
        "winner": winner,
        "opponent": ({"id": opponent_id, "fullName": opponent_name} if opponent_id else None),
        "team_name_2": opponent_name,
        "TournamentName": tournament_name,
        "round_name": round_name,
        "Surface": surface,
        # The buggy old behavior copied this straight into match_date - it
        # must never end up as the reported match_date.
        "StartDate": tournament_start_date,
        "tournament": {
            "tournamentGroup": {"id": tournament_group_id},
            "year": tournament_year,
            "startDate": tournament_start_date[:10],
        },
    }


def _tournament_fixture(
    *,
    player_a: str = "P1",
    player_b: str = "P2",
    match_state: str = "F",
    match_timestamp: str | None = "2026-01-05T18:30:00+00:00",
    draw_match_type: str = "S",
) -> dict[str, Any]:
    """Build one entry shaped like ``GET /tournaments/{id}/{year}/matches`` returns."""

    return {
        "DrawMatchType": draw_match_type,
        "PlayerIDA": player_a,
        "PlayerIDB": player_b,
        "MatchState": match_state,
        "MatchTimeStamp": match_timestamp,
    }


def _provider_with_mocked_client(
    monkeypatch: pytest.MonkeyPatch,
    player_matches: list[dict[str, Any]],
    tournament_matches: list[dict[str, Any]] | None = None,
) -> WtaOfficialMatchProvider:
    provider = WtaOfficialMatchProvider()
    monkeypatch.setattr(
        provider._client, "get_player_matches", lambda player_id, page_size=25: player_matches
    )

    def _fake_get_tournament_matches(group_id: Any, year: Any, *, page_size: int = 500) -> list[dict]:
        if tournament_matches is None:
            raise RuntimeError("simulated tournament-matches endpoint failure")
        return tournament_matches

    monkeypatch.setattr(provider._client, "get_tournament_matches", _fake_get_tournament_matches)
    return provider


def test_match_date_comes_from_tournament_feed_not_tournament_start_date(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The core regression test: StartDate must never leak into match_date."""

    provider = _provider_with_mocked_client(
        monkeypatch,
        player_matches=[_player_match(tournament_start_date="2026-01-01T00:00:00+00:00")],
        tournament_matches=[_tournament_fixture(match_timestamp="2026-01-08T14:00:00+00:00")],
    )

    result = provider.get_latest_match(PLAYER)

    assert result is not None
    assert result.match_date == date(2026, 1, 8)
    assert result.match_date != date(2026, 1, 1)  # the tournament start date


def test_match_date_is_none_when_fixture_not_found_in_tournament_feed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Stale/incomplete tournament-level data must degrade to null, not a guess."""

    provider = _provider_with_mocked_client(
        monkeypatch,
        player_matches=[_player_match()],
        # The tournament feed doesn't (yet) have this fixture at all.
        tournament_matches=[],
    )

    result = provider.get_latest_match(PLAYER)

    assert result is not None
    assert result.match_date is None
    # Everything else the player-matches endpoint gave us is still reported.
    assert result.opponent == "Opponent Name"
    assert result.tournament == "Sample Open"


def test_match_date_is_none_when_tournament_endpoint_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    """A transient failure enriching the date must never fail the whole match lookup."""

    provider = _provider_with_mocked_client(
        monkeypatch,
        player_matches=[_player_match()],
        tournament_matches=None,  # simulates the enrichment call raising
    )

    result = provider.get_latest_match(PLAYER)

    assert result is not None
    assert result.match_date is None
    assert result.opponent == "Opponent Name"


def test_match_date_is_none_when_missing_match_timestamp(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = _provider_with_mocked_client(
        monkeypatch,
        player_matches=[_player_match()],
        tournament_matches=[_tournament_fixture(match_timestamp=None)],
    )

    result = provider.get_latest_match(PLAYER)

    assert result is not None
    assert result.match_date is None


def test_match_date_is_none_when_fixture_not_yet_finished(monkeypatch: pytest.MonkeyPatch) -> None:
    """A fixture the tournament feed hasn't marked finished must not be trusted."""

    provider = _provider_with_mocked_client(
        monkeypatch,
        player_matches=[_player_match()],
        tournament_matches=[_tournament_fixture(match_state="P")],
    )

    result = provider.get_latest_match(PLAYER)

    assert result is not None
    assert result.match_date is None


def test_byes_are_never_selected_as_the_latest_match(monkeypatch: pytest.MonkeyPatch) -> None:
    bye = _player_match(scores="", opponent_id=None, opponent_name="")
    bye["opponent"] = None
    real_match = _player_match(round_name="R32", scores="6-1 6-2", opponent_name="Real Opponent")

    provider = _provider_with_mocked_client(
        monkeypatch,
        player_matches=[bye, real_match],
        tournament_matches=[_tournament_fixture()],
    )

    result = provider.get_latest_match(PLAYER)

    assert result is not None
    assert result.opponent == "Real Opponent"


def test_walkovers_are_never_selected_as_the_latest_match(monkeypatch: pytest.MonkeyPatch) -> None:
    """A walkover/default has an opponent listed but no real score - not a played match."""

    walkover = _player_match(scores="", opponent_name="Withdrew Opponent")
    real_match = _player_match(round_name="R32", scores="7-5 6-3", opponent_name="Real Opponent")

    provider = _provider_with_mocked_client(
        monkeypatch,
        player_matches=[walkover, real_match],
        tournament_matches=[_tournament_fixture()],
    )

    result = provider.get_latest_match(PLAYER)

    assert result is not None
    assert result.opponent == "Real Opponent"


def test_doubles_matches_are_filtered_out(monkeypatch: pytest.MonkeyPatch) -> None:
    doubles_match = _player_match(s_d_flag="D", opponent_name="Doubles Opponent")
    singles_match = _player_match(round_name="R32", opponent_name="Singles Opponent")

    provider = _provider_with_mocked_client(
        monkeypatch,
        player_matches=[doubles_match, singles_match],
        tournament_matches=[_tournament_fixture()],
    )

    result = provider.get_latest_match(PLAYER)

    assert result is not None
    assert result.opponent == "Singles Opponent"


def test_no_singles_matches_at_all_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = _provider_with_mocked_client(
        monkeypatch,
        player_matches=[_player_match(s_d_flag="D")],
        tournament_matches=[],
    )

    assert provider.get_latest_match(PLAYER) is None


def test_get_latest_match_raises_player_data_error_on_provider_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The outer player-matches call failing is real data loss and must be surfaced
    (the pipeline catches PlayerDataError per player - see test_pipeline_integration.py)."""

    provider = WtaOfficialMatchProvider()

    def _boom(player_id: str, page_size: int = 25) -> list[dict]:
        raise RuntimeError("network exploded")

    monkeypatch.setattr(provider._client, "get_player_matches", _boom)

    with pytest.raises(PlayerDataError):
        provider.get_latest_match(PLAYER)


def test_tournament_matches_are_cached_across_players_in_one_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Several Top N players often share a recent tournament; don't refetch it per player."""

    provider = WtaOfficialMatchProvider()
    call_count = 0

    def _get_player_matches(player_id: str, page_size: int = 25) -> list[dict]:
        return [_player_match()]

    def _get_tournament_matches(group_id: Any, year: Any, *, page_size: int = 500) -> list[dict]:
        nonlocal call_count
        call_count += 1
        return [_tournament_fixture()]

    monkeypatch.setattr(provider._client, "get_player_matches", _get_player_matches)
    monkeypatch.setattr(provider._client, "get_tournament_matches", _get_tournament_matches)

    provider.get_latest_match(PLAYER)
    provider.get_latest_match(
        PlayerRanking(rank=2, player_id="P3", name="Other", country_code="FRA", points=7000)
    )

    assert call_count == 1


def test_player_2_slot_without_opponent_id_still_reports_match_with_null_date(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When our player is in the player_2 slot, the API gives us no opponent id, so
    date enrichment can't run - the rest of the match must still be reported."""

    match = _player_match()
    match["player_1"] = "SOMEONE_ELSE"
    match["player_2"] = "P1"
    match["opponent"] = None  # API only ever populates "opponent" relative to player_1
    match["team_name_1"] = "Someone Else"
    match["winner"] = 2  # player_2 (our player) won

    provider = _provider_with_mocked_client(
        monkeypatch, player_matches=[match], tournament_matches=[_tournament_fixture()]
    )

    result = provider.get_latest_match(PLAYER)

    assert result is not None
    assert result.won is True
    assert result.match_date is None
    assert result.opponent == "Someone Else"


# --- get_matches_for_date (day-first) ----------------------------------------------------


def _catalogue_page(
    *,
    page: int = 0,
    total_entries: int = 1,
    entries: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "pageInfo": {"page": page, "numPages": 0, "pageSize": 100, "numEntries": total_entries},
        "content": entries if entries is not None else [],
    }


def _tournament_catalogue_entry(
    *,
    group_id: int = 1017,
    year: int = 2026,
    name: str = "CINCINNATI",
    level: str = "WTA 1000",
    start_date: str = "2026-08-13",
    end_date: str = "2026-08-23",
    draw_size: int | None = None,
    country: str | None = None,
) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "tournamentGroup": {"id": group_id, "name": name, "level": level},
        "year": year,
        "startDate": start_date,
        "endDate": end_date,
        "level": level,
    }
    if draw_size is not None:
        entry["singlesDrawSize"] = draw_size
    if country is not None:
        entry["country"] = country
    return entry


def _tournament_level_fixture(
    *,
    player_id_a: str = "P1",
    player_id_b: str = "P2",
    first_a: str = "Test",
    last_a: str = "Player",
    first_b: str = "Opponent",
    last_b: str = "Name",
    match_state: str = "F",
    draw_match_type: str = "S",
    match_timestamp: str = "2026-08-15T20:23:32.46+00:00",
    winner: str = "3",
    round_id: str = "2",
    draw_level_type: str = "M",
    score_string: str = "6-3,6-2",
) -> dict[str, Any]:
    return {
        "PlayerIDA": player_id_a,
        "PlayerIDB": player_id_b,
        "PlayerNameFirstA": first_a,
        "PlayerNameLastA": last_a,
        "PlayerNameFirstB": first_b,
        "PlayerNameLastB": last_b,
        "MatchState": match_state,
        "DrawMatchType": draw_match_type,
        "MatchTimeStamp": match_timestamp,
        "Winner": winner,
        "RoundID": round_id,
        "DrawLevelType": draw_level_type,
        "ScoreString": score_string,
    }


def _provider_for_day_first(
    monkeypatch: pytest.MonkeyPatch,
    *,
    catalogue_entries: list[dict[str, Any]],
    fixtures_by_tournament: dict[tuple[Any, Any], list[dict[str, Any]]],
) -> WtaOfficialMatchProvider:
    provider = WtaOfficialMatchProvider()
    monkeypatch.setattr(
        provider._client,
        "list_tournaments_page",
        lambda page, page_size=100: (
            _catalogue_page(page=page, total_entries=len(catalogue_entries), entries=catalogue_entries)
            if page == 0
            else _catalogue_page(page=page, entries=[])
        ),
    )
    monkeypatch.setattr(
        provider._client,
        "get_tournament_matches",
        lambda group_id, year, page_size=500: fixtures_by_tournament.get((group_id, year), []),
    )
    return provider


def test_get_matches_for_date_finds_a_finished_match_on_the_target_date(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The core day-first regression test: a match the per-player endpoint
    hasn't ingested yet is still found via the tournament-level scan."""

    provider = _provider_for_day_first(
        monkeypatch,
        catalogue_entries=[_tournament_catalogue_entry()],
        fixtures_by_tournament={
            (1017, 2026): [_tournament_level_fixture(player_id_a="P1", player_id_b="P2")]
        },
    )

    result = provider.get_matches_for_date([PLAYER], date(2026, 8, 15))

    assert "P1" in result.matches
    match = result.matches["P1"]
    assert match.opponent == "Opponent Name"
    assert match.tournament == "Cincinnati"
    assert match.match_date == date(2026, 8, 15)
    assert match.won is False  # Winner="3" means the B slot (opponent) won
    # No tournament fetch failed, so absence would be a confident negative.
    assert result.unresolved_player_ids == frozenset()


def test_get_matches_for_date_reports_no_match_for_a_day_nobody_played(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _provider_for_day_first(
        monkeypatch,
        catalogue_entries=[_tournament_catalogue_entry()],
        fixtures_by_tournament={(1017, 2026): [_tournament_level_fixture()]},
    )

    # The fixture is dated 2026-08-15; asking about a different day must not
    # return it - and must not fall back to it either.
    result = provider.get_matches_for_date([PLAYER], date(2026, 8, 14))

    assert result.matches == {}
    # Confirmed negative, since every active tournament was read successfully.
    assert result.unresolved_player_ids == frozenset()


def test_get_matches_for_date_never_falls_back_to_an_older_match(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression test for the exact production complaint: a stale Toronto/
    Wimbledon-style older match must never stand in for "did she play on
    this specific day"."""

    older_fixture = _tournament_level_fixture(match_timestamp="2026-06-29T00:00:00+00:00")
    provider = _provider_for_day_first(
        monkeypatch,
        catalogue_entries=[_tournament_catalogue_entry()],
        fixtures_by_tournament={(1017, 2026): [older_fixture]},
    )

    result = provider.get_matches_for_date([PLAYER], date(2026, 8, 15))

    assert "P1" not in result.matches


def test_get_matches_for_date_ignores_doubles_and_unfinished_fixtures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    doubles = _tournament_level_fixture(draw_match_type="D")
    unfinished = _tournament_level_fixture(match_state="U", winner="")
    provider = _provider_for_day_first(
        monkeypatch,
        catalogue_entries=[_tournament_catalogue_entry()],
        fixtures_by_tournament={(1017, 2026): [doubles, unfinished]},
    )

    result = provider.get_matches_for_date([PLAYER], date(2026, 8, 15))

    assert result.matches == {}


def test_get_matches_for_date_uses_fallback_round_label(monkeypatch: pytest.MonkeyPatch) -> None:
    """No per-player entry exists to borrow a nicer round name from, so the
    plainer DrawLevelType+RoundID label is used - see module docstring."""

    provider = _provider_for_day_first(
        monkeypatch,
        catalogue_entries=[_tournament_catalogue_entry()],
        fixtures_by_tournament={
            (1017, 2026): [_tournament_level_fixture(round_id="2", draw_level_type="M")]
        },
    )

    result = provider.get_matches_for_date([PLAYER], date(2026, 8, 15))

    assert result.matches["P1"].round == "Main Draw Round 2"


def test_get_matches_for_date_normalizes_local_offset_timestamps_to_utc(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A finished match reported in a local offset (not observed in practice,
    but the not-yet-played entries in the same feed do this - see module
    docstring) must still normalize to UTC correctly - checked here with a
    daytime timestamp so the separate reporting-day cutoff (see
    test_get_matches_for_date_applies_the_reporting_day_cutoff_for_a_late_night_finish)
    doesn't also shift the bucketing and confound this specific check."""

    # 14:30 in UTC-04:00 is 18:30 the same day in UTC - well after the
    # reporting-day cutoff, so this isolates offset normalization alone.
    fixture = _tournament_level_fixture(match_timestamp="2026-08-15T14:30:00-04:00")
    provider = _provider_for_day_first(
        monkeypatch,
        catalogue_entries=[_tournament_catalogue_entry()],
        fixtures_by_tournament={(1017, 2026): [fixture]},
    )

    result = provider.get_matches_for_date([PLAYER], date(2026, 8, 15))

    assert "P1" in result.matches
    assert result.matches["P1"].match_date == date(2026, 8, 15)


# ---------------------------------------------------------------------------
# Reporting-day cutoff (production regression, August 2026): Sara Bejlek
# def. Aryna Sabalenka 7-6(9-7), 6-4 at Cincinnati, completed 12:15 AM EDT
# Thursday, August 20, 2026 (04:15 UTC the same calendar day). The 8 AM
# Thursday run incorrectly reported Sabalenka as "did not play yesterday"
# because the match's UTC-normalized completion date (Aug 20) didn't
# equal the query's target date (Aug 19, i.e. "yesterday" as of the
# Thursday run) - even though this was unambiguously part of Wednesday
# night's schedule.
# ---------------------------------------------------------------------------


def _bejlek_def_sabalenka_fixture(*, match_timestamp: str) -> dict[str, Any]:
    return _tournament_level_fixture(
        player_id_a="sabalenka-id",
        player_id_b="bejlek-id",
        first_a="Aryna",
        last_a="Sabalenka",
        first_b="Sara",
        last_b="Bejlek",
        match_state="F",
        match_timestamp=match_timestamp,
        winner="3",  # slot B (Bejlek) won
        round_id="4",
        score_string="7-6(9-7),6-4",
    )


def test_a_late_night_finish_is_included_in_the_following_mornings_report(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The exact regression case: a match completing at 12:15 AM Eastern
    Thursday (04:15 UTC) must be included when the Thursday-morning run
    asks 'what happened Wednesday' (target_date = Wednesday, August 19)."""

    fixture = _bejlek_def_sabalenka_fixture(match_timestamp="2026-08-20T04:15:00+00:00")
    provider = _provider_for_day_first(
        monkeypatch,
        catalogue_entries=[_tournament_catalogue_entry(country="USA, OH")],
        fixtures_by_tournament={(1017, 2026): [fixture]},
    )

    result = provider.get_matches_for_date([PLAYER, _sabalenka_ranking()], date(2026, 8, 19))

    assert "sabalenka-id" in result.matches
    match = result.matches["sabalenka-id"]
    assert match.opponent == "Sara Bejlek"
    assert match.won is False
    assert match.score == "7-6(9-7),6-4"
    assert match.match_date == date(2026, 8, 19)


def test_the_same_late_night_match_is_not_reported_again_the_following_day(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The Friday-morning run (target_date = Thursday, August 20) must
    NOT also report this same Wednesday-night match - it belongs to
    exactly one reporting day, never two."""

    fixture = _bejlek_def_sabalenka_fixture(match_timestamp="2026-08-20T04:15:00+00:00")
    provider = _provider_for_day_first(
        monkeypatch,
        catalogue_entries=[_tournament_catalogue_entry(country="USA, OH")],
        fixtures_by_tournament={(1017, 2026): [fixture]},
    )

    result = provider.get_matches_for_date([PLAYER, _sabalenka_ranking()], date(2026, 8, 20))

    assert "sabalenka-id" not in result.matches


def test_a_match_completed_normally_during_the_daytime_is_included_as_before(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An ordinary daytime match must retain its expected reporting
    date - the cutoff must not shift matches that were never near a
    midnight boundary in the first place."""

    fixture = _bejlek_def_sabalenka_fixture(match_timestamp="2026-08-19T20:23:32+00:00")  # 4:23 PM Eastern
    provider = _provider_for_day_first(
        monkeypatch,
        catalogue_entries=[_tournament_catalogue_entry(country="USA, OH")],
        fixtures_by_tournament={(1017, 2026): [fixture]},
    )

    result = provider.get_matches_for_date([PLAYER, _sabalenka_ranking()], date(2026, 8, 19))

    assert "sabalenka-id" in result.matches
    assert result.matches["sabalenka-id"].match_date == date(2026, 8, 19)


def test_a_true_next_day_daytime_match_is_reported_on_its_own_day(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A genuine Thursday daytime match (not a late-night carryover from
    Wednesday) must be reported in Friday's 'what happened Thursday'
    recap, not folded into Wednesday's."""

    fixture = _bejlek_def_sabalenka_fixture(match_timestamp="2026-08-20T15:00:00+00:00")  # 11 AM Eastern
    provider = _provider_for_day_first(
        monkeypatch,
        catalogue_entries=[_tournament_catalogue_entry(country="USA, OH")],
        fixtures_by_tournament={(1017, 2026): [fixture]},
    )

    result = provider.get_matches_for_date([PLAYER, _sabalenka_ranking()], date(2026, 8, 20))

    assert "sabalenka-id" in result.matches
    assert result.matches["sabalenka-id"].match_date == date(2026, 8, 20)


def test_reporting_day_cutoff_falls_back_gracefully_for_an_unrecognized_country(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No recognized tournament country/timezone must never exclude a
    match outright - it falls back to treating the UTC completion time
    as if it were local (still correctly resolving this specific case,
    since 04:15 UTC is before the UTC-based fallback cutoff too)."""

    fixture = _bejlek_def_sabalenka_fixture(match_timestamp="2026-08-20T04:15:00+00:00")
    provider = _provider_for_day_first(
        monkeypatch,
        catalogue_entries=[_tournament_catalogue_entry(country="ATLANTIS")],
        fixtures_by_tournament={(1017, 2026): [fixture]},
    )

    result = provider.get_matches_for_date([PLAYER, _sabalenka_ranking()], date(2026, 8, 19))

    assert "sabalenka-id" in result.matches


def test_reporting_day_cutoff_falls_back_gracefully_when_no_country_is_given(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _bejlek_def_sabalenka_fixture(match_timestamp="2026-08-20T04:15:00+00:00")
    provider = _provider_for_day_first(
        monkeypatch,
        catalogue_entries=[_tournament_catalogue_entry()],  # no country at all
        fixtures_by_tournament={(1017, 2026): [fixture]},
    )

    result = provider.get_matches_for_date([PLAYER, _sabalenka_ranking()], date(2026, 8, 19))

    assert "sabalenka-id" in result.matches


def test_reporting_day_cutoff_is_configurable(monkeypatch: pytest.MonkeyPatch) -> None:
    """A custom cutoff hour is respected - a 2 AM Eastern finish is
    reclassified to the previous day under the default 6 AM cutoff, but
    not under a stricter 1 AM cutoff."""

    provider = _provider_for_day_first(
        monkeypatch,
        catalogue_entries=[_tournament_catalogue_entry(country="USA, OH")],
        fixtures_by_tournament={
            (1017, 2026): [
                # 2:00 AM Eastern Thursday = 06:00 UTC Thursday.
                _bejlek_def_sabalenka_fixture(match_timestamp="2026-08-20T06:00:00+00:00")
            ]
        },
    )
    provider._reporting_cutoff_hour = 1

    result = provider.get_matches_for_date([PLAYER, _sabalenka_ranking()], date(2026, 8, 20))

    # With a 1 AM cutoff, 2 AM is no longer "late night" - it keeps its
    # own day (Thursday), rather than being folded into Wednesday.
    assert "sabalenka-id" in result.matches


def test_get_matches_for_date_skips_irrelevant_tour_levels(monkeypatch: pytest.MonkeyPatch) -> None:
    """ITF/Challenger events never involve Top N players and are skipped
    without even fetching their match list."""

    fetch_calls: list[tuple[Any, Any]] = []
    provider = _provider_for_day_first(
        monkeypatch,
        catalogue_entries=[_tournament_catalogue_entry(group_id=42, level="ITF")],
        fixtures_by_tournament={},
    )

    def _tracking_get_tournament_matches(group_id: Any, year: Any, page_size: int = 500) -> list[dict]:
        fetch_calls.append((group_id, year))
        return []

    monkeypatch.setattr(provider._client, "get_tournament_matches", _tracking_get_tournament_matches)

    result = provider.get_matches_for_date([PLAYER], date(2026, 8, 15))

    assert result.matches == {}
    assert fetch_calls == []


def test_get_matches_for_date_one_tournament_failing_does_not_block_others(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = WtaOfficialMatchProvider()
    monkeypatch.setattr(
        provider._client,
        "list_tournaments_page",
        lambda page, page_size=100: (
            _catalogue_page(
                page=page,
                total_entries=2,
                entries=[
                    _tournament_catalogue_entry(group_id=1, name="BROKEN"),
                    _tournament_catalogue_entry(group_id=2, name="WORKING"),
                ],
            )
            if page == 0
            else _catalogue_page(page=page, entries=[])
        ),
    )

    def _get_tournament_matches(group_id: Any, year: Any, page_size: int = 500) -> list[dict]:
        if group_id == 1:
            raise RuntimeError("simulated outage for this one tournament")
        return [_tournament_level_fixture(player_id_a="P1", player_id_b="P2")]

    monkeypatch.setattr(provider._client, "get_tournament_matches", _get_tournament_matches)

    result = provider.get_matches_for_date([PLAYER], date(2026, 8, 15))

    assert "P1" in result.matches  # found via the working tournament despite the broken one
    # P1 was actually found, so she isn't ambiguous even though a
    # (different) tournament failed to fetch.
    assert result.unresolved_player_ids == frozenset()


def test_get_matches_for_date_marks_players_unresolved_when_a_tournament_fetch_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A player who isn't found anywhere, while some active tournament's
    match list genuinely couldn't be read, must be reported as unresolved -
    not a confident 'played: false' - since her match might be exactly the
    one hidden inside the tournament that failed to fetch. This is what lets
    a composite provider (best_of) correctly still try another source for
    her, while not bothering to re-check every other, genuinely-resolved
    player."""

    provider = WtaOfficialMatchProvider()
    other_player = PlayerRanking(
        rank=2, player_id="P9", name="Someone Else", country_code="FRA", points=1000
    )
    monkeypatch.setattr(
        provider._client,
        "list_tournaments_page",
        lambda page, page_size=100: (
            _catalogue_page(
                page=page,
                total_entries=1,
                entries=[_tournament_catalogue_entry(group_id=1, name="BROKEN")],
            )
            if page == 0
            else _catalogue_page(page=page, entries=[])
        ),
    )
    monkeypatch.setattr(
        provider._client,
        "get_tournament_matches",
        lambda group_id, year, page_size=500: (_ for _ in ()).throw(
            RuntimeError("simulated outage")
        ),
    )

    result = provider.get_matches_for_date([PLAYER, other_player], date(2026, 8, 15))

    assert result.matches == {}
    assert result.unresolved_player_ids == frozenset({"P1", "P9"})


def test_get_matches_for_date_raises_when_catalogue_scan_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    from wta_daily.exceptions import DataProviderError

    provider = WtaOfficialMatchProvider()

    def _boom(page: int, page_size: int = 100) -> dict:
        raise RuntimeError("simulated catalogue outage")

    monkeypatch.setattr(provider._client, "list_tournaments_page", _boom)

    with pytest.raises(DataProviderError):
        provider.get_matches_for_date([PLAYER], date(2026, 8, 15))


def test_get_matches_for_date_finds_second_player_slot(monkeypatch: pytest.MonkeyPatch) -> None:
    """Our player can be in either PlayerIDA or PlayerIDB - both must resolve."""

    provider = _provider_for_day_first(
        monkeypatch,
        catalogue_entries=[_tournament_catalogue_entry()],
        fixtures_by_tournament={
            (1017, 2026): [
                # Our player is in slot B; Winner="3" means slot B won.
                _tournament_level_fixture(player_id_a="OTHER", player_id_b="P1", winner="3")
            ]
        },
    )

    result = provider.get_matches_for_date([PLAYER], date(2026, 8, 15))

    assert "P1" in result.matches
    assert result.matches["P1"].won is True
    assert result.matches["P1"].opponent == "Test Player"  # slot A's name, per the fixture helper's defaults


# ---------------------------------------------------------------------------
# Tournament-status detection (elimination, points, previous-year callback)
# ---------------------------------------------------------------------------


def test_get_matches_for_date_reports_elimination_with_round_and_points(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _provider_for_day_first(
        monkeypatch,
        catalogue_entries=[_tournament_catalogue_entry()],  # WTA 1000, default
        fixtures_by_tournament={
            (1017, 2026): [
                # Won an earlier round...
                _tournament_level_fixture(player_id_a="P1", player_id_b="P4", round_id="2", winner="2"),
                # ...then lost in the Round of 16.
                _tournament_level_fixture(
                    player_id_a="P1",
                    player_id_b="P3",
                    round_id="4",
                    winner="3",
                    first_b="Rival",
                    last_b="Player",
                ),
            ]
        },
    )

    result = provider.get_matches_for_date([PLAYER], date(2026, 8, 15))

    status = result.tournament_status["P1"]
    assert status.state.value == "eliminated"
    assert status.round_reached == "R16"
    assert status.round_label == "the Round of 16"
    assert status.eliminated_by == "Rival Player"
    assert status.points_earned == 120  # WTA 1000, R16, default (96) draw size
    # No 2025 fixtures were configured for this tournament, so there's
    # genuinely nothing to compare against - never invented.
    assert status.previous_year_round is None
    assert status.previous_year_points is None
    assert status.points_delta is None


def test_get_matches_for_date_reports_champion(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = _provider_for_day_first(
        monkeypatch,
        catalogue_entries=[_tournament_catalogue_entry()],
        fixtures_by_tournament={
            (1017, 2026): [
                _tournament_level_fixture(player_id_a="P1", player_id_b="P4", round_id="F", winner="2")
            ]
        },
    )

    result = provider.get_matches_for_date([PLAYER], date(2026, 8, 15))

    status = result.tournament_status["P1"]
    assert status.state.value == "champion"
    assert status.round_reached == "W"
    assert status.round_label == "the title"
    assert status.points_earned == 1000  # WTA 1000 champion points


def test_get_matches_for_date_reports_active_when_a_fixture_is_still_unplayed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _provider_for_day_first(
        monkeypatch,
        catalogue_entries=[_tournament_catalogue_entry()],
        fixtures_by_tournament={
            (1017, 2026): [
                _tournament_level_fixture(player_id_a="P1", player_id_b="P4", round_id="2", winner="2"),
                _tournament_level_fixture(
                    player_id_a="P1", player_id_b="P3", round_id="4", winner="", match_state="O"
                ),
            ]
        },
    )

    result = provider.get_matches_for_date([PLAYER], date(2026, 8, 15))

    status = result.tournament_status["P1"]
    assert status.state.value == "active"
    assert status.round_reached is None
    assert status.points_earned is None


def test_get_matches_for_date_reports_did_not_participate_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _provider_for_day_first(
        monkeypatch,
        catalogue_entries=[_tournament_catalogue_entry()],
        fixtures_by_tournament={
            (1017, 2026): [_tournament_level_fixture(player_id_a="OTHER1", player_id_b="OTHER2")]
        },
    )

    result = provider.get_matches_for_date([PLAYER], date(2026, 8, 15))

    status = result.tournament_status["P1"]
    assert status.state.value == "did_not_participate"
    assert status.tournament is None


def test_tournament_status_is_empty_when_the_feature_is_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = WtaOfficialMatchProvider(tournament_status_enabled=False)
    monkeypatch.setattr(
        provider._client,
        "list_tournaments_page",
        lambda page, page_size=100: (
            _catalogue_page(page=page, total_entries=1, entries=[_tournament_catalogue_entry()])
            if page == 0
            else _catalogue_page(page=page, entries=[])
        ),
    )
    monkeypatch.setattr(
        provider._client,
        "get_tournament_matches",
        lambda group_id, year, page_size=500: [
            _tournament_level_fixture(player_id_a="P1", player_id_b="P3", round_id="4", winner="3")
        ],
    )

    result = provider.get_matches_for_date([PLAYER], date(2026, 8, 15))

    assert result.tournament_status == {}


def test_previous_year_callback_computes_points_delta(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = _provider_for_day_first(
        monkeypatch,
        catalogue_entries=[_tournament_catalogue_entry()],
        fixtures_by_tournament={
            (1017, 2026): [
                # Eliminated in the quarterfinals this year.
                _tournament_level_fixture(player_id_a="P1", player_id_b="P3", round_id="Q", winner="3")
            ],
            (1017, 2025): [
                # Only reached the Round of 32 last year.
                _tournament_level_fixture(player_id_a="P1", player_id_b="P5", round_id="3", winner="3")
            ],
        },
    )

    result = provider.get_matches_for_date([PLAYER], date(2026, 8, 15))

    status = result.tournament_status["P1"]
    assert status.round_reached == "QF"
    assert status.points_earned == 215  # WTA 1000 QF
    assert status.previous_year_round == "R32"
    assert status.previous_year_points == 65  # WTA 1000 R32
    assert status.points_delta == 215 - 65


def test_previous_year_lookback_can_be_disabled_independently(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _provider_for_day_first(
        monkeypatch,
        catalogue_entries=[_tournament_catalogue_entry()],
        fixtures_by_tournament={
            (1017, 2026): [
                _tournament_level_fixture(player_id_a="P1", player_id_b="P3", round_id="Q", winner="3")
            ],
            (1017, 2025): [
                _tournament_level_fixture(player_id_a="P1", player_id_b="P5", round_id="3", winner="3")
            ],
        },
    )
    provider._previous_year_lookback_enabled = False

    result = provider.get_matches_for_date([PLAYER], date(2026, 8, 15))

    status = result.tournament_status["P1"]
    assert status.points_earned == 215  # still computed - this is independent of the lookback flag
    assert status.previous_year_round is None
    assert status.previous_year_points is None
    assert status.points_delta is None


def test_previous_year_lookup_failure_degrades_gracefully(monkeypatch: pytest.MonkeyPatch) -> None:
    """A network error while fetching *last year's* fixtures must never
    take down this year's (successfully fetched) elimination context."""

    provider = WtaOfficialMatchProvider()
    monkeypatch.setattr(
        provider._client,
        "list_tournaments_page",
        lambda page, page_size=100: (
            _catalogue_page(page=page, total_entries=1, entries=[_tournament_catalogue_entry()])
            if page == 0
            else _catalogue_page(page=page, entries=[])
        ),
    )

    def _get_tournament_matches(group_id: Any, year: Any, page_size: int = 500) -> list[dict]:
        if year == 2026:
            return [_tournament_level_fixture(player_id_a="P1", player_id_b="P3", round_id="4", winner="3")]
        raise RuntimeError("simulated outage fetching last year's draw")

    monkeypatch.setattr(provider._client, "get_tournament_matches", _get_tournament_matches)

    result = provider.get_matches_for_date([PLAYER], date(2026, 8, 15))

    status = result.tournament_status["P1"]
    assert status.state.value == "eliminated"
    assert status.round_reached == "R16"
    assert status.points_earned == 120
    assert status.previous_year_round is None  # gracefully omitted, not fabricated


def test_previous_year_edition_with_a_different_draw_size_uses_its_own_draw_size(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression test: the previous year's RoundID must be interpreted
    using *that edition's own* draw size, never this year's - draw size
    changing between editions is rare, but RoundID normalization is
    draw-size-relative, so reusing the wrong year's size would silently
    misidentify the round (and therefore the points) reached last year.

    This year's draw is 56 (3 numbered rounds before QF), last year's was
    32 (2 numbered rounds) - the same raw RoundID "2" means R32 this year
    but R16 last year, with different points (32 vs. 60) for WTA 500.
    """

    provider = _provider_for_day_first(
        monkeypatch,
        catalogue_entries=[
            _tournament_catalogue_entry(year=2026, level="WTA 500", draw_size=56),
            _tournament_catalogue_entry(year=2025, level="WTA 500", draw_size=32),
        ],
        fixtures_by_tournament={
            (1017, 2026): [
                _tournament_level_fixture(player_id_a="P1", player_id_b="P3", round_id="2", winner="3")
            ],
            (1017, 2025): [
                _tournament_level_fixture(player_id_a="P1", player_id_b="P5", round_id="2", winner="3")
            ],
        },
    )

    result = provider.get_matches_for_date([PLAYER], date(2026, 8, 15))

    status = result.tournament_status["P1"]
    assert status.state.value == "eliminated"
    # This year (draw size 56): RoundID "2" -> R32.
    assert status.round_reached == "R32"
    assert status.points_earned == 32
    # Last year (draw size 32): the *same* RoundID "2" -> R16, not R32.
    assert status.previous_year_round == "R16"
    assert status.previous_year_points == 60


def test_points_earned_is_none_when_category_has_no_points_table_entry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """WTA Finals' round-robin scoring isn't in the points table by design
    (see data/wta_points_table.yaml) - a lookup for it must degrade to
    ``None``, never raise or guess."""

    provider = _provider_for_day_first(
        monkeypatch,
        catalogue_entries=[_tournament_catalogue_entry(level="WTA FINALS")],
        fixtures_by_tournament={
            (1017, 2026): [
                _tournament_level_fixture(player_id_a="P1", player_id_b="P3", round_id="S", winner="3")
            ]
        },
    )

    result = provider.get_matches_for_date([PLAYER], date(2026, 8, 15))

    status = result.tournament_status["P1"]
    assert status.state.value == "eliminated"
    assert status.round_reached == "SF"
    assert status.points_earned is None
