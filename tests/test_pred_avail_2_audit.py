from __future__ import annotations

from scripts.football_data.providers.football_data_org import FootballDataOrgRecentFormRoute
from scripts.football_data.run_pred_avail_2 import (
    EXPECTED_COHORT_SHA256,
    build_pred_avail_2_audit,
    build_pred_avail_2_baseline,
    build_source_preflight,
)


def test_pred_avail_2_baseline_is_the_p1_after_state():
    baseline = build_pred_avail_2_baseline()

    assert baseline["cohort_sha256"] == EXPECTED_COHORT_SHA256
    assert len(baseline["fixtures"]) == 25
    assert baseline["baseline_summary"]["full_prediction_count"] == 2
    assert baseline["baseline_summary"]["missing_recent_form_count"] == 23
    released = next(row for row in baseline["fixtures"] if row["match_id"] == "500-1364199")
    assert released["prediction_status"] == "FROZEN"
    assert released["p1_after_source"] == "authoritative_historical_results"


def test_offline_audit_fails_closed_without_provider_credential(tmp_path, monkeypatch):
    monkeypatch.delenv("FOOTBALL_DATA_ORG_TOKEN", raising=False)
    route = FootballDataOrgRecentFormRoute(token="", cache_root=tmp_path)

    audit = build_pred_avail_2_audit(route=route)

    assert audit["cohort_sha256"] == EXPECTED_COHORT_SHA256
    assert audit["before"]["full_prediction_count"] == 2
    assert audit["before"]["missing_recent_form_count"] == 23
    assert audit["after"]["full_prediction_count"] == 2
    assert audit["after"]["missing_recent_form_count"] == 23
    assert audit["CALL_COUNT"] == 0
    assert audit["CACHE_HIT_COUNT"] == 0
    assert audit["after"]["route_status_counts"]["SOURCE_UNAVAILABLE"] == 18
    assert audit["after"]["route_status_counts"]["OUTSIDE_PROVIDER_FREE_COVERAGE"] == 5
    assert audit["after"]["route_status_counts"]["PRESERVED_EXISTING_FROZEN"] == 2
    assert audit["required_status_counts"] == {
        "FULL": 2,
        "DEGRADED": 0,
        "INSUFFICIENT_DATA": 23,
        "MISSING_RECENT_FORM": 23,
        "SOURCE_UNAVAILABLE": 18,
        "FIXTURE_MAPPING_UNAVAILABLE": 0,
        "OUTSIDE_PROVIDER_FREE_COVERAGE": 5,
        "AMBIGUOUS_FIXTURE": 0,
    }
    assert audit["quality_boundary"] == {
        "champion_math_changed": False,
        "frozen_prediction_rewritten": False,
        "prospective_mutated": False,
        "market_only_production_fallback": False,
        "synthetic_evidence": False,
        "fuzzy_identity": False,
        "llm_identity": False,
        "league_specific_adapter": False,
        "provider_hopping": False,
    }


def test_source_preflight_reports_credential_block_without_secret_value(monkeypatch):
    monkeypatch.delenv("FOOTBALL_DATA_ORG_TOKEN", raising=False)

    preflight = build_source_preflight(now="2026-08-29T17:49:07Z", live_requested=False)

    assert preflight["result"] == "LIVE_VALIDATION_BLOCKED_BY_CREDENTIAL"
    assert preflight["credential"]["present"] is False
    assert preflight["credential"]["value_persisted"] is False
    assert preflight["credential"]["value_logged"] is False
