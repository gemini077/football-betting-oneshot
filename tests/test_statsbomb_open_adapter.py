from pathlib import Path

from scripts.football_data.entity_resolution import TeamEntityResolver
from scripts.football_data.player_identity import PlayerIdentityResolver
from scripts.football_data.providers.statsbomb_open import StatsBombOpenDataProvider


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "football_data" / "statsbomb_open_data"


def provider():
    return StatsBombOpenDataProvider(
        FIXTURE,
        resolver=TeamEntityResolver(ROOT / "data" / "football_data" / "team_alias_registry.json"),
        player_resolver=PlayerIdentityResolver(ROOT / "data" / "football_data" / "player_identity_registry.json"),
    )


def test_adapter_is_offline_and_preserves_team_and_match_provider_ids():
    value = provider()
    teams = value.get_team_identity()
    assert [row["source_entity_id"] for row in teams] == ["1", "2"]
    assert {row["canonical_entity_id"] for row in teams} == {"team:manchester-united", "team:paris-saint-germain"}
    match = value.get_match_history()[0]
    assert match["provider_match_id"] == "fixture-match-001"
    assert match["canonical_match_id"] is None
    assert "match_identity_unresolved" in match["missing_reason"]


def test_xg_is_provider_specific_and_not_normalized_or_mixed():
    rows = provider().get_xg()
    assert [row["value"] for row in rows] == [0.6, 0.27]
    assert all(row["provider"] == "statsbomb" for row in rows)
    assert all(row["metric_definition"] == "shot.statsbomb_xg" for row in rows)
    assert all(row["normalization_version"] is None for row in rows)
    assert all(row["provenance"]["attribution_required"] is True for row in rows)
    assert all(row["provenance"]["commercial_use_review"] == "required" for row in rows)


def test_event_stats_and_confirmed_lineups_are_fixture_scoped():
    stats = provider().get_team_stats()
    assert len(stats) == 2
    assert {row["metrics"]["shots_for"] for row in stats} == {2, 1}
    lineups = provider().get_lineup()
    assert len(lineups) == 2
    assert all(row["status"] == "confirmed" for row in lineups)
    assert any(player["bench"] for row in lineups for player in row["players"])
    assert {player["canonical_player_id"] for row in lineups for player in row["players"]} == {
        "player:fixture-goalkeeper", "player:fixture-captain", "player:fixture-substitute",
        "player:fixture-away-keeper", "player:fixture-away-forward",
    }
    assert provider().get_availability() == []
