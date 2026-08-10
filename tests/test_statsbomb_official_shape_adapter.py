from pathlib import Path

import pytest

from scripts.football_data.competition_resolution import CompetitionEntityResolver
from scripts.football_data.entity_resolution import TeamEntityResolver
from scripts.football_data.player_identity import PlayerIdentityResolver
from scripts.football_data.providers.statsbomb_open import StatsBombOpenDataProvider


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "football_data" / "statsbomb_open_data"
TEAM_REGISTRY = FIXTURE / "team_alias_registry.json"
COMPETITION_REGISTRY = FIXTURE / "competition_identity_registry.json"
PLAYER_REGISTRY = FIXTURE / "player_identity_registry.json"


def provider(match_id="fixture-match-001"):
    return StatsBombOpenDataProvider(
        FIXTURE,
        match_id=match_id,
        resolver=TeamEntityResolver(TEAM_REGISTRY),
        competition_resolver=CompetitionEntityResolver(COMPETITION_REGISTRY),
        player_resolver=PlayerIdentityResolver(PLAYER_REGISTRY),
    )


def test_official_match_list_selects_exact_match_and_reads_nested_identity():
    value = provider()
    assert value.match_id == "fixture-match-001"
    assert value.match["home_team"]["home_team_id"] == 1
    assert value.match["away_team"]["away_team_id"] == 2

    teams = value.get_team_identity()
    assert [row["source_entity_id"] for row in teams] == ["1", "2"]
    assert {row["canonical_entity_id"] for row in teams} == {
        "team:manchester-united",
        "team:paris-saint-germain",
    }
    assert all(row["provider_competition_id"] == "fixture:competition" for row in teams)
    assert all(row["provider_competition_name"] == "Premier League" for row in teams)
    assert all(row["canonical_competition_id"] == "competition:england-premier-league" for row in teams)
    assert all(row["provider_season_id"] == "fixture:season" for row in teams)
    assert all(row["canonical_season_id"] == "season:england-premier-league-2025-26" for row in teams)

    # The selected match is the second element, so relying on list[0] would fail.
    assert provider("fixture-match-000").get_match_history()[0]["provider_match_id"] == "fixture-match-000"


def test_match_selection_rejects_missing_and_duplicate_ids():
    with pytest.raises(ValueError, match="match_not_found"):
        provider("does-not-exist")

    matches = [
        {
            "match_id": "duplicate",
            "competition": {},
            "season": {},
            "home_team": {"home_team_id": 1, "home_team_name": "A"},
            "away_team": {"away_team_id": 2, "away_team_name": "B"},
        },
        {
            "match_id": "duplicate",
            "competition": {},
            "season": {},
            "home_team": {"home_team_id": 3, "home_team_name": "C"},
            "away_team": {"away_team_id": 4, "away_team_name": "D"},
        },
    ]
    with pytest.raises(ValueError, match="ambiguous_match_id"):
        StatsBombOpenDataProvider(
            match_source=matches,
            events_source=[],
            lineups_source=[],
            metadata={"captured_at": "2026-08-01T12:00:00Z"},
            match_id="duplicate",
        )


def test_official_lineup_shape_preserves_unknown_semantics_and_coverage():
    rows = provider().get_lineup()
    assert len(rows) == 2
    assert all(row["status"] == "confirmed" for row in rows)

    players = {player["provider_player_id"]: player for row in rows for player in row["players"]}
    assert players["101"]["starter"] is True
    assert players["101"]["bench"] is False
    assert players["101"]["goalkeeper"] is True
    assert players["101"]["captain"] is None
    assert players["103"]["starter"] is False
    assert players["103"]["bench"] is True
    assert players["104"]["starter"] is None
    assert players["104"]["bench"] is None
    assert players["102"]["goalkeeper"] is None
    assert players["102"]["captain"] is None
    assert rows[0]["player_identity_coverage"] == {
        "resolved_players": 3,
        "total_players": 4,
        "coverage_ratio": 0.75,
    }


def test_synthetic_provenance_does_not_claim_real_open_data_observation():
    record = provider().get_xg()[0]
    assert record["source"] == "synthetic_statsbomb_schema_fixture"
    assert record["provider"] == "statsbomb_fixture"
    assert record["provenance"]["synthetic"] is True
    assert record["provenance"]["observation_origin"] == "synthetic_schema_fixture"
    assert record["provenance"]["provider_schema"] == "statsbomb"
    assert record["provenance"]["provider_schema_reference"] == "https://github.com/hudl/open-data"
    assert record["provenance"]["source_url"] is None
