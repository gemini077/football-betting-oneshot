from __future__ import annotations

from scripts.football_data.coverage import analysis_weighted_coverage


def test_analysis_weighted_coverage_reports_strict_and_verified_bridge_separately():
    metrics = analysis_weighted_coverage(
        [
            {
                "competition_key": "ready",
                "coverage_priority": "P1",
                "project_analysis_count": 80,
                "business_status": "READY",
                "current_strength_coverage": 1.0,
            },
            {
                "competition_key": "bridge",
                "coverage_priority": "P1",
                "project_analysis_count": 10,
                "business_status": "BRIDGE_ONLY",
                "history_recency_status": "BRIDGE_ONLY",
                "current_strength_coverage": 0.0,
            },
            {
                "competition_key": "stale",
                "coverage_priority": "P1",
                "project_analysis_count": 10,
                "business_status": "STALE",
                "history_recency_status": "STALE",
                "current_strength_coverage": 0.0,
            },
        ]
    )

    assert metrics["analysis_weight"] == 100
    assert metrics["strict_ready_weight"] == 80
    assert metrics["ready_plus_bridge_weight"] == 90
    assert metrics["analysis_weighted_strict_ready"] == 0.8
    assert metrics["analysis_weighted_ready_plus_bridge"] == 0.9
