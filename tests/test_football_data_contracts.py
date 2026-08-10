import json
from pathlib import Path

import pytest

from scripts.football_data.contracts import ContractError, validate_record
from scripts.football_data.providers.nowscore_500 import Nowscore500SnapshotProvider


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_DIR = ROOT / "schemas" / "football_data"


def common(contract_version="team_identity.v1", *, canonical_entity_id="team:test"):
    return {
        "contract_version": contract_version,
        "source": "fixture",
        "source_entity_id": "fixture:test",
        "canonical_entity_id": canonical_entity_id,
        "captured_at": "2026-08-01T12:00:00Z",
        "source_as_of_at": "2026-08-01T12:00:00Z",
        "competition": "competition:test",
        "season": "season:test",
        "home_away_context": "overall",
        "sample_size": {"matches": 1, "minutes": 90},
        "value": None,
        "unit": None,
        "quality": "A",
        "freshness": {"state": "fresh", "age_seconds": 0, "ttl_seconds": 21600},
        "missing_reason": [],
        "provenance": {
            "provider": "fixture",
            "source": "fixture",
            "source_record_ref": "fixture:test",
            "captured_at": "2026-08-01T12:00:00Z",
            "source_as_of_at": "2026-08-01T12:00:00Z",
            "attribution_required": False,
        },
    }


def test_all_versioned_schema_files_are_json_and_versioned():
    expected = {
        "team_identity.schema.json": "team_identity.v1",
        "competition_identity.schema.json": "competition_identity.v1",
        "match_identity.schema.json": "match_identity.v1",
        "team_strength_snapshot.schema.json": "team_strength_snapshot.v1",
        "team_form_snapshot.schema.json": "team_form_snapshot.v1",
        "xg_snapshot.schema.json": "xg_snapshot.v1",
        "lineup_snapshot.schema.json": "lineup_snapshot.v1",
        "availability_snapshot.schema.json": "availability_snapshot.v1",
        "data_provenance.schema.json": "data_provenance.v1",
        "player_identity.schema.json": "player_identity.v1",
    }
    for name, version in expected.items():
        value = json.loads((SCHEMA_DIR / name).read_text(encoding="utf-8"))
        assert value["$schema"].endswith("2020-12/schema")
        assert version in value["$id"]


def test_team_identity_contract_requires_explicit_unresolved_reason():
    record = common(canonical_entity_id=None)
    record.update(
        {
            "canonical_name": "Unknown FC",
            "country": None,
            "gender": "unknown",
            "team_level": "unknown",
            "resolution_status": "unresolved",
            "resolution_method": "unresolved",
            "confidence": None,
            "missing_reason": ["identity_unresolved"],
        }
    )
    assert validate_record("team_identity", record)
    record["missing_reason"] = []
    with pytest.raises(ContractError, match="identity_unresolved"):
        validate_record("team_identity", record)


def test_xg_contract_preserves_provider_definition_and_rejects_implicit_normalization():
    record = common("xg_snapshot.v1", canonical_entity_id="team:test")
    record.update(
        {
            "team_id": "team:test",
            "competition_id": "competition:test",
            "season_id": "season:test",
            "as_of_at": "2026-08-01T12:00:00Z",
            "provider": "statsbomb",
            "metric_definition": "shot.statsbomb_xg",
            "includes_penalties": None,
            "post_shot_or_pre_shot": "pre_shot",
            "model_version_if_known": None,
            "normalization_version": None,
            "value": 1.4,
            "unit": "goals",
        }
    )
    record["source"] = "statsbomb"
    record["provenance"]["provider"] = "statsbomb"
    assert validate_record("xg_snapshot", record)
    record["normalization_version"] = "xg-normalized-v1"
    with pytest.raises(ContractError, match="normalized xG"):
        validate_record("xg_snapshot", record)


def test_opponent_adjustment_contract_is_structure_only():
    record = common("team_strength_snapshot.v1")
    record.update(
        {
            "team_id": "team:test",
            "competition_id": "competition:test",
            "season_id": "season:test",
            "as_of_at": "2026-08-01T12:00:00Z",
            "matches": 1,
            "window_type": "season_to_date",
            "window_start": "2026-08-01",
            "window_end": "2026-08-01",
            "minutes": 90,
            "metrics": {"goals_for_per90": 1.0, "xg_for_per90": None},
            "opponent_adjustment": {
                "opponent_team_id": "team:opponent",
                "opponent_strength_snapshot_ref": "snapshot:opponent:1",
                "raw_metric": 1.0,
                "opponent_adjusted_metric": None,
                "adjustment_method": "not_calculated",
                "adjustment_version": "future",
            },
        }
    )
    assert validate_record("team_strength_snapshot", record)


def test_red_card_fields_are_preserved_and_availability_conflicts_are_not_overwritten():
    strength = common("team_strength_snapshot.v1")
    strength.update({
        "team_id": "team:test", "competition_id": "competition:test", "season_id": "season:test", "as_of_at": "2026-08-01T12:00:00Z",
        "matches": 1, "window_type": "single_match", "window_start": "2026-08-01", "window_end": "2026-08-01", "minutes": 90,
        "metrics": {"goals_for": 1}, "red_card_events": 1, "minutes_10v11": 35, "minutes_11v10": 0,
    })
    assert validate_record("team_strength_snapshot", strength)

    availability = common("availability_snapshot.v1", canonical_entity_id="team:test")
    availability.update({
        "team_id": "team:test", "canonical_player_id": "player:test", "provider_player_id": "provider:player:test",
        "player_name": "Fixture Player", "status": "questionable", "evidence": ["source-a says questionable", "source-b says returned"],
        "source_timestamp": "2026-08-01T11:00:00Z", "confidence": 0.5, "conflict_group_id": "conflict:player:test:2026-08-01", "conflict_state": "conflicting",
    })
    assert validate_record("availability_snapshot", availability)


def test_lineup_contract_allows_unknown_source_semantics_and_tracks_identity_coverage():
    lineup = common("lineup_snapshot.v1", canonical_entity_id="team:test")
    lineup.update({
        "match_id": "match:test",
        "team_id": "team:test",
        "status": "confirmed",
        "players": [{
            "canonical_player_id": None,
            "provider_player_id": "provider:player:test",
            "name": "Unresolved Player",
            "team_id": "team:test",
            "position": None,
            "starter": None,
            "bench": None,
            "captain": None,
            "goalkeeper": None,
            "source": "fixture",
            "captured_at": "2026-08-01T12:00:00Z",
            "status": "confirmed",
        }],
        "player_identity_coverage": {"resolved_players": 0, "total_players": 1, "coverage_ratio": 0.0},
    })
    assert validate_record("lineup_snapshot", lineup)


def test_availability_contract_allows_missing_source_fact_timestamp():
    availability = common("availability_snapshot.v1", canonical_entity_id="team:test")
    availability.update({
        "team_id": "team:test",
        "canonical_player_id": None,
        "provider_player_id": "provider:player:test",
        "player_name": "Unresolved Player",
        "status": "unknown",
        "evidence": [],
        "source_timestamp": None,
        "confidence": None,
    })
    assert validate_record("availability_snapshot", availability)


def test_nowscore_500_adapter_does_not_infer_xg_or_injury_absence():
    provider = Nowscore500SnapshotProvider(
        {
            "source": "500.com",
            "captured_at": "2026-08-01T12:00:00Z",
            "competition": "competition:test",
            "season": "season:test",
            "home_team": {"name": "Manchester United"},
            "away_team": {"name": "Paris Saint-Germain"},
            "shuju": {
                "recent_form": {
                    "home": [{"team_name": "Manchester United", "gf": 2, "ga": 1}],
                    "away": [{"team_name": "PSG", "gf": 1, "ga": 1}],
                }
            },
        }
    )
    assert provider.get_xg() == []
    assert provider.get_availability() == []
    form = provider.get_match_history()
    assert len(form) == 2
    assert all(row["contract_version"] == "team_form_snapshot.v1" for row in form)


def test_nowscore_500_adapter_reads_current_aggregate_form_shape_without_merging_windows():
    provider = Nowscore500SnapshotProvider(
        {
            "source": "500.com",
            "captured_at": "2026-08-01T12:00:00Z",
            "shuju": {"recent_form": {
                "home_overall": {"matches": 10, "goals_for": 12, "goals_against": 13},
                "away_overall": {"matches": 10, "goals_for": 22, "goals_against": 9},
                "home_home": {"matches": 10, "goals_for": 19, "goals_against": 11},
                "away_away": {"matches": 10, "goals_for": 16, "goals_against": 13},
            }},
            "home_team": {"name": "Manchester United"},
            "away_team": {"name": "Paris Saint-Germain"},
        }
    )
    rows = provider.get_match_history()
    assert len(rows) == 4
    assert {row["matches"] for row in rows} == {10}
    assert {row["metrics"]["goals_for"] for row in rows} == {12, 22, 19, 16}


def test_feature_registry_has_no_model_validated_feature():
    registry = json.loads((ROOT / "config" / "football_feature_registry.json").read_text(encoding="utf-8"))
    assert registry["validated_for_model"] is False
    assert registry["features"]
    assert sum(1 for feature in registry["features"] if feature["validated_for_model"] is True) == 0
