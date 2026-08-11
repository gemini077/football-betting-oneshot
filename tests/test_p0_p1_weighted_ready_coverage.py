from __future__ import annotations

from scripts.football_data.p0_p1_coverage import weighted_ready_coverage


def test_weighted_rates_keep_bridge_separate_from_strict_ready():
    audits = [
        {"status": "STRICT_READY", "weight": 5},
        {"status": "VERIFIED_BRIDGE", "weight": 3},
        {"status": "STALE", "weight": 2},
        {"status": "SOURCE_MISSING", "weight": 4},
    ]

    result = weighted_ready_coverage(audits)

    assert result["demand_weight"] == 14
    assert result["strict_ready_weight"] == 5
    assert result["verified_bridge_weight"] == 3
    assert result["strict_ready_rate"] == 5 / 14
    assert result["ready_plus_bridge_rate"] == 8 / 14
