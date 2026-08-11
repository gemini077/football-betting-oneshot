from scripts.football_data.final_coverage import weighted_final_coverage


def test_gate_failure_is_only_a_metric_fact():
    result = weighted_final_coverage(
        [
            {"status": "STRICT_READY", "weight": 19},
            {"status": "VERIFIED_BRIDGE", "weight": 1},
            {"status": "IDENTITY_MISSING", "weight": 72},
            {"status": "SOURCE_MISSING", "weight": 60},
        ]
    )

    assert result["ready_plus_bridge_weight"] == 20
    assert result["demand_weight"] == 152
    assert result["eighty_percent_gate_passed"] is False
    assert "phase2b_coverage_limit_reached" not in result
