from __future__ import annotations

import pytest

from scripts.football_data.final_coverage import (
    build_final_identity_gap_summary,
    weighted_final_coverage,
)
from scripts.football_data import populate_phase2b_final


def test_identity_gap_reports_missing_evidence_without_auto_verifying():
    summary = build_final_identity_gap_summary(
        [
            {
                "target_match_id": "target:1",
                "competition": "norway-eliteserien",
                "kickoff": "2026-08-01T12:00:00Z",
                "project_home_name": "汉坎",
                "project_away_name": "特罗姆瑟",
            }
        ],
        {
            "target:1": {
                "home": {
                    "provider": "500",
                    "provider_team_id": None,
                    "provider_team_name": "汉坎",
                    "translated_team_name": None,
                    "translation_status": None,
                    "resolution_status": "unresolved",
                    "reason": ["no verified project provider mapping"],
                    "supporting_fixture_count": 4,
                },
                "away": {
                    "provider": "500",
                    "provider_team_id": None,
                    "provider_team_name": "特罗姆瑟",
                    "translated_team_name": "Tromso",
                    "translation_status": "EXACT_MATCH",
                    "resolution_status": "unresolved",
                    "reason": ["no verified project provider mapping"],
                    "supporting_fixture_count": 4,
                    "candidate_canonical_team_ids_before_context": [],
                },
            }
        },
        generated_at="2026-08-11T00:00:00Z",
    )

    assert summary["starting_identity_missing"] == 1
    assert summary["still_unresolved_fixture_count"] == 1
    assert summary["resolved_fixture_count"] == 0
    assert summary["blocker_counts"]["provider_team_id_missing"] == 2
    assert summary["blocker_counts"]["translated_english_name_missing"] == 1
    assert summary["blocker_counts"]["canonical_source_candidate_missing"] == 2
    assert summary["rows"][0]["fixture_classification"] == "STILL_IDENTITY_MISSING"


def test_identity_gap_preserves_review_and_conflict_states():
    summary = build_final_identity_gap_summary(
        [
            {"target_match_id": "target:review", "competition": "test"},
            {"target_match_id": "target:conflict", "competition": "test"},
            {"target_match_id": "target:auto", "competition": "test"},
        ],
        {
            "target:review": {
                "home": {"canonical_team_id": "team:a", "resolution_status": "resolved"},
                "away": {"canonical_team_id": None, "resolution_status": "review_required", "reason": ["ambiguous"]},
            },
            "target:conflict": {
                "home": {"canonical_team_id": None, "resolution_status": "conflict", "reason": ["provider_namespace_conflict"]},
                "away": {"canonical_team_id": "team:b", "resolution_status": "resolved"},
            },
            "target:auto": {
                "home": {"canonical_team_id": "team:a", "resolution_status": "resolved"},
                "away": {"canonical_team_id": "team:b", "resolution_status": "resolved"},
            },
        },
        generated_at="2026-08-11T00:00:00Z",
    )

    assert summary["review_required_fixture_count"] == 1
    assert summary["conflict_fixture_count"] == 1
    assert summary["auto_resolved_fixture_count"] == 1


def test_final_weighted_gate_keeps_source_missing_in_denominator():
    audits = [
        {"status": "STRICT_READY", "weight": 19},
        {"status": "VERIFIED_BRIDGE", "weight": 1},
        {"status": "IDENTITY_MISSING", "weight": 72},
        {"status": "SOURCE_MISSING", "weight": 60},
    ]

    result = weighted_final_coverage(audits)

    assert result["demand_weight"] == 152
    assert result["strict_ready_weight"] == 19
    assert result["verified_bridge_weight"] == 1
    assert result["ready_plus_bridge_weight"] == 20
    assert result["source_missing_weight"] == 60
    assert result["identity_missing_weight"] == 72
    assert result["ready_plus_bridge_rate"] == 20 / 152
    assert result["gate_threshold_weight"] == 122
    assert result["eighty_percent_gate_passed"] is False
    assert result["phase2b_coverage_limit_reached"] is True


def test_final_population_requires_verified_shared_data_home(monkeypatch):
    monkeypatch.setattr(
        populate_phase2b_final,
        "verify_data_home",
        lambda: {"status": "DATASET_NOT_AVAILABLE"},
    )

    with pytest.raises(RuntimeError, match="shared Football Data Home verification failed"):
        populate_phase2b_final.run()
