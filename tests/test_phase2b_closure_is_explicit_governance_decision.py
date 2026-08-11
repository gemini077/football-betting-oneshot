from scripts.football_data.final_coverage import (
    build_phase2b_closure_decision,
    weighted_final_coverage,
)


def test_closure_does_not_claim_failed_gate_proves_permanent_limit():
    weighted = weighted_final_coverage([{"status": "SOURCE_MISSING", "weight": 1}])
    closure = build_phase2b_closure_decision(
        weighted=weighted,
        coverage_backlog={"identity_missing": 0, "source_missing": 1, "total_not_ready": 1},
    )

    assert closure["phase2b_closed"] is True
    assert closure["phase2b_closed_with_backlog"] is True
    assert closure["global_80_percent_gate_passed"] is False
    assert "continued global coverage expansion is deferred rather than treated as model-data success" in closure["closure_reason"]
