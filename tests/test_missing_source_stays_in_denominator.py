from __future__ import annotations

from scripts.football_data.p0_p1_coverage import weighted_ready_coverage


def test_source_missing_is_a_failure_bucket_and_not_removed_from_denominator():
    result = weighted_ready_coverage(
        [
            {"status": "STRICT_READY", "weight": 8},
            {"status": "SOURCE_MISSING", "weight": 27, "competition_key": "south-korea-k-league-1"},
        ]
    )

    assert result["demand_weight"] == 35
    assert result["source_missing_weight"] == 27
    assert result["strict_ready_rate"] == 8 / 35
    assert result["ready_plus_bridge_rate"] == 8 / 35
