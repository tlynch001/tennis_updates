from __future__ import annotations

from wta_daily.models import PlayerRanking
from wta_daily.plugins.matches.sample import SampleMatchProvider
from wta_daily.plugins.rankings.sample import SampleRankingsProvider

from .conftest import SAMPLE_MATCHES_FIXTURE, SAMPLE_RANKINGS_FIXTURE


def test_sample_rankings_provider_returns_sorted_top_n() -> None:
    provider = SampleRankingsProvider(fixture_path=SAMPLE_RANKINGS_FIXTURE)

    top5 = provider.get_top_n(5)

    assert len(top5) == 5
    assert [p.rank for p in top5] == [1, 2, 3, 4, 5]
    assert all(isinstance(p, PlayerRanking) for p in top5)


def test_sample_rankings_provider_caps_at_available_players() -> None:
    provider = SampleRankingsProvider(fixture_path=SAMPLE_RANKINGS_FIXTURE)

    everyone = provider.get_top_n(1000)

    assert len(everyone) == 10


def test_sample_match_provider_returns_known_match() -> None:
    provider = SampleMatchProvider(fixture_path=SAMPLE_MATCHES_FIXTURE)
    player = PlayerRanking(rank=1, player_id="sample-001", name="X", country_code="BLR", points=1)

    match = provider.get_latest_match(player)

    assert match is not None
    assert match.won is True
    assert match.tournament == "Sample Open"


def test_sample_match_provider_returns_none_for_unknown_player() -> None:
    provider = SampleMatchProvider(fixture_path=SAMPLE_MATCHES_FIXTURE)
    player = PlayerRanking(rank=99, player_id="does-not-exist", name="Y", country_code="USA", points=1)

    assert provider.get_latest_match(player) is None
