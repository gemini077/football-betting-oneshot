from pathlib import Path

from scripts.football_data.competition_resolution import CompetitionEntityResolver
from scripts.football_data.entity_resolution import TeamEntityResolver
from scripts.football_data.providers.statsbomb_open import StatsBombOpenDataProvider


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_REGISTRY = ROOT / "tests" / "fixtures" / "football_data" / "statsbomb_open_data" / "competition_identity_registry.json"


def test_raw_provider_name_is_not_a_canonical_competition_id_without_reviewed_mapping():
    resolver = CompetitionEntityResolver(FIXTURE_REGISTRY)
    result = resolver.resolve(
        provider="statsbomb",
        provider_competition_id="unreviewed:competition",
        provider_competition_name="Premier League",
        provider_season_id="unreviewed:season",
        provider_season_name="2025/2026",
    )
    assert result.canonical_competition_id is None
    assert result.canonical_season_id is None
    assert result.resolution_status == "unresolved"
    assert result.resolution_method == "unresolved"


def test_reviewed_provider_ids_resolve_to_separate_canonical_competition_and_season():
    resolver = CompetitionEntityResolver(FIXTURE_REGISTRY)
    result = resolver.resolve(
        provider="statsbomb_fixture",
        provider_competition_id="fixture:competition",
        provider_competition_name="Premier League",
        provider_season_id="fixture:season",
        provider_season_name="2025/2026",
    )
    assert result.canonical_competition_id == "competition:england-premier-league"
    assert result.canonical_season_id == "season:england-premier-league-2025-26"
    assert result.resolution_status == "resolved"
    assert result.resolution_method == "manual_verified"
    assert result.confidence == 1.0


def test_competition_name_matching_is_not_fuzzy_or_silent():
    resolver = CompetitionEntityResolver(FIXTURE_REGISTRY)
    result = resolver.resolve(
        provider="statsbomb_fixture",
        provider_competition_id=None,
        provider_competition_name="Premier League 2",
        provider_season_id=None,
        provider_season_name="2025/2026",
    )
    assert result.canonical_competition_id is None
    assert result.resolution_status == "unresolved"


def test_adapter_keeps_raw_provider_name_out_of_canonical_competition_context():
    fixture = ROOT / "tests" / "fixtures" / "football_data" / "statsbomb_open_data"
    provider = StatsBombOpenDataProvider(
        fixture,
        match_id="fixture-match-001",
        resolver=TeamEntityResolver(fixture / "team_alias_registry.json"),
    )
    record = provider.get_team_identity()[0]
    assert record["provider_competition_name"] == "Premier League"
    assert record["canonical_competition_id"] is None
    assert record["competition"] is None
