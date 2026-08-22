"""TourProfile selection, values, and provider-compatibility guards."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from wta_daily.exceptions import ConfigurationError
from wta_daily.tour import (
    ATP,
    WTA,
    WTA_ONLY_PROVIDER_NAMES,
    TourProfile,
    assert_tour_providers_compatible,
    profile_for,
)


def test_profile_for_selects_wta_and_atp_case_insensitively() -> None:
    assert profile_for("wta") is WTA
    assert profile_for("WTA") is WTA
    assert profile_for("atp") is ATP
    assert profile_for("ATP") is ATP


def test_unknown_tour_raises_configuration_error() -> None:
    with pytest.raises(ConfigurationError, match="Unknown tour"):
        profile_for("itf")


def test_wta_profile_reproduces_current_production_presentation() -> None:
    assert WTA.key == "wta"
    assert WTA.display_name == "WTA"
    assert WTA.tour_long_name == "WTA Tour"
    assert WTA.game_label == "women's game"
    assert WTA.subject == "she"
    assert WTA.object == "her"
    assert WTA.possessive == "her"
    assert WTA.subject_cap == "She"
    assert WTA.ranking_body == "the WTA"
    assert (
        WTA.attribution
        == "Data: WTA (api.wtatennis.com)  |  Generated automatically  |  wta-daily"
    )
    assert WTA.git_commit_message_template == "Daily WTA Update {date}"


def test_atp_profile_is_presentation_only() -> None:
    assert ATP.key == "atp"
    assert ATP.display_name == "ATP"
    assert ATP.tour_long_name == "ATP Tour"
    assert ATP.game_label == "men's game"
    assert ATP.subject == "he"
    assert ATP.object == "him"
    assert ATP.possessive == "his"
    assert ATP.subject_cap == "He"
    assert ATP.ranking_body == "the ATP"
    # Do not invent an ATP rankings URL that this repo does not call.
    assert "api.wtatennis.com" not in ATP.attribution
    assert "WTA" not in ATP.attribution
    assert ATP.git_commit_message_template == "Daily ATP Update {date}"


def test_wta_phrase_formatting_keeps_production_wording() -> None:
    assert (
        WTA.format("Welcome to today's {tour} Top {n} Update for {date}.", n=10, date="Monday")
        == "Welcome to today's WTA Top 10 Update for Monday."
    )
    assert (
        WTA.format(
            "That's everything you need to know from the top of the {game} today. "
            "We'll be back tomorrow with the latest."
        )
        == "That's everything you need to know from the top of the women's game today. "
        "We'll be back tomorrow with the latest."
    )
    assert (
        WTA.format(
            "That wraps up today's update. Join us again tomorrow for the newest "
            "rankings and results from the {tour_long}."
        )
        == "That wraps up today's update. Join us again tomorrow for the newest "
        "rankings and results from the WTA Tour."
    )
    assert (
        WTA.format("That keeps {object} just {gap} points behind the player above {object}.", gap=40)
        == "That keeps her just 40 points behind the player above her."
    )
    assert (
        WTA.format(
            "number {rank} according to {ranking_body}, number one according to "
            "an extremely biased editorial board",
            rank=28,
        )
        == "number 28 according to the WTA, number one according to an extremely biased editorial board"
    )


def test_atp_phrase_formatting_uses_atp_identity_and_male_pronouns() -> None:
    assert (
        ATP.format("Welcome to today's {tour} Top {n} Update for {date}.", n=10, date="Monday")
        == "Welcome to today's ATP Top 10 Update for Monday."
    )
    assert "women's game" not in ATP.format("from the top of the {game} today")
    assert "men's game" in ATP.format("from the top of the {game} today")
    assert ATP.format("{subject_cap} now trails number {rank_above}.", rank_above=3) == (
        "He now trails number 3."
    )
    assert "she" not in ATP.format("after {subject} defeated {opponent}", opponent="Rival")
    assert ATP.format("after {subject} defeated {opponent}", opponent="Rival") == (
        "after he defeated Rival"
    )


def test_wta_tour_is_compatible_with_wta_official_providers() -> None:
    assert_tour_providers_compatible(
        "wta",
        rankings_provider_name="wta_official",
        match_provider_name="best_of",
        match_provider_options=None,
    )


def test_atp_tour_with_sample_providers_is_allowed() -> None:
    assert_tour_providers_compatible(
        "atp",
        rankings_provider_name="sample",
        match_provider_name="sample",
    )


def test_atp_tour_rejects_wta_official_rankings() -> None:
    with pytest.raises(ConfigurationError, match="WTA-only"):
        assert_tour_providers_compatible(
            "atp",
            rankings_provider_name="wta_official",
            match_provider_name="sample",
        )


def test_atp_tour_rejects_wta_official_match_provider() -> None:
    with pytest.raises(ConfigurationError, match="WTA-only"):
        assert_tour_providers_compatible(
            "atp",
            rankings_provider_name="sample",
            match_provider_name="wta_official",
        )


def test_atp_tour_rejects_best_of_default_sources_that_include_wta_official() -> None:
    with pytest.raises(ConfigurationError, match="WTA-only"):
        assert_tour_providers_compatible(
            "atp",
            rankings_provider_name="sample",
            match_provider_name="best_of",
            match_provider_options=None,
        )


def test_atp_tour_rejects_best_of_explicit_wta_official_source() -> None:
    with pytest.raises(ConfigurationError, match="WTA-only"):
        assert_tour_providers_compatible(
            "atp",
            rankings_provider_name="sample",
            match_provider_name="best_of",
            match_provider_options={
                "sources": [{"provider": "wta_official"}, {"provider": "live_tennis_api"}]
            },
        )


def test_atp_tour_allows_best_of_without_wta_official_sources() -> None:
    assert_tour_providers_compatible(
        "atp",
        rankings_provider_name="sample",
        match_provider_name="best_of",
        match_provider_options={"sources": [{"provider": "sample"}]},
    )


def test_wta_only_provider_names_are_the_official_wta_plugins() -> None:
    assert WTA_ONLY_PROVIDER_NAMES == frozenset({"wta_official"})


def test_tour_profile_is_frozen() -> None:
    with pytest.raises(FrozenInstanceError):
        WTA.display_name = "ATP"  # type: ignore[misc]
    assert isinstance(WTA, TourProfile)
