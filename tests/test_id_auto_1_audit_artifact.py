from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data" / "football_data" / "id_auto_1"


def load(name: str) -> dict:
    return json.loads((OUTPUT / name).read_text(encoding="utf-8"))


def test_exact_66_fixture_before_after_audit_is_complete_and_non_blocking():
    audit = load("daily_fixture_audit.json")

    assert audit["cohort"]["fixture_count"] == 66
    assert len(audit["fixtures"]) == 66
    assert audit["before"]["coverage"]["status_counts"] == {
        "SUPPORTED": 1,
        "DEGRADED": 0,
        "UNSUPPORTED": 65,
    }
    assert audit["before"]["coverage"]["reason_counts"]["IDENTITY_UNAVAILABLE"] == 65
    assert audit["after"]["identity"]["auto_resolved_fixture_count"] == 2
    assert audit["after"]["identity"]["partial_identity_fixture_count"] == 7
    assert audit["after"]["identity"]["ambiguous_fixture_count"] == 0
    assert audit["after"]["identity"]["unresolved_fixture_count"] == 57
    assert audit["after"]["coverage"]["status_counts"] == {
        "SUPPORTED": 2,
        "DEGRADED": 0,
        "UNSUPPORTED": 64,
    }
    assert audit["after"]["coverage"]["reason_counts"]["IDENTITY_UNAVAILABLE"] == 64
    assert audit["after"]["coverage"]["champion_prediction_allowed_count"] == 66
    assert audit["after"]["coverage"]["blocked_count"] == 0
    assert audit["after"]["coverage"]["non_blocking"] is True
    assert sum(row["fixture_count"] for row in audit["by_competition"]) == 66
    assert sum(row["after"]["fixture_count"] for row in audit["high_value_history_group"]) == 15


def test_registry_and_reuse_artifacts_keep_exact_only_policy():
    registry = load("identity_registry.json")
    reuse = load("provider_id_reuse_evidence.json")
    backlog = load("identity_resolution_backlog.json")

    assert registry["contract_version"] == "identity_registry.v1"
    assert registry["normalization"]["fuzzy_matching"] is False
    assert registry["normalization"]["transliteration"] is False
    assert registry["resolution_ladder"] == [
        "stable_provider_id_crosswalk",
        "reviewed_canonical_provider_crosswalk",
        "fixture_canonical_id",
        "competition_exact_normalized_name",
        "competition_reviewed_alias",
    ]
    assert registry["summary"]["linked_reviewed_alias_group_count"] == 9
    assert reuse["replay_check_count"] == 37
    assert reuse["replay_resolved_count"] == 37
    assert reuse["replay_ambiguous_count"] == 0
    assert reuse["replay_unresolved_count"] == 0
    assert backlog["summary"] == {
        "entry_count": 64,
        "ambiguous_fixture_count": 0,
        "reviewable_candidate_fixture_count": 7,
        "unresolved_fixture_count": 57,
    }


def test_id_auto_1_protects_authoritative_store_and_champion_route():
    audit = load("daily_fixture_audit.json")

    assert audit["history_protection"]["authoritative_count"] == 1778
    assert audit["history_protection"]["authoritative_dataset_digest"] == (
        "48088556830cfb5a6ecd523fc4dc29889406b4853001c51849f5533ecc44a3f2"
    )
    assert audit["history_protection"]["read_mode"] == "read_only"
    assert audit["history_protection"]["mutation_performed"] is False
    assert audit["champion_protection"]["blocked_count"] == 0
    assert audit["champion_protection"]["existing_champion_math_changed"] is False
    assert audit["champion_protection"]["frozen_predictions_changed"] is False
    assert audit["champion_protection"]["prospective_records_changed"] is False
    assert audit["construction_policy"]["manual_fixture_aliases_added"] == 0
    assert audit["construction_policy"]["manual_team_aliases_added"] == 0
    assert audit["construction_policy"]["league_specific_resolution_code_added"] is False
