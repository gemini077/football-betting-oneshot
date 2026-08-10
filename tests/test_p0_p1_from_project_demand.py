from __future__ import annotations

from scripts.football_data.coverage import rank_coverage_gaps


def test_p0_p1_are_driven_by_project_demand_and_readiness_gap():
    ranked = rank_coverage_gaps(
        [
            {
                "competition_key": "source-heavy-only",
                "current_match_count": 0,
                "project_analysis_count": 0,
                "source_record_count": 10000,
                "result_coverage": "SUPPORTED",
                "team_identity_coverage": 1.0,
            },
            {
                "competition_key": "current-stale",
                "current_match_count": 1,
                "project_analysis_count": 1,
                "result_coverage": "SUPPORTED",
                "team_identity_coverage": 1.0,
                "current_strength_coverage": 0.0,
            },
            {
                "competition_key": "high-demand-gap",
                "current_match_count": 0,
                "project_analysis_count": 12,
                "result_coverage": "MISSING",
                "team_identity_coverage": 0.0,
            },
            {
                "competition_key": "high-demand-ready",
                "current_match_count": 1,
                "project_analysis_count": 12,
                "result_coverage": "SUPPORTED",
                "team_identity_coverage": 1.0,
                "current_strength_coverage": 1.0,
            },
        ]
    )
    by_key = {row["competition_key"]: row for row in ranked}

    assert by_key["source-heavy-only"]["coverage_priority"] == "P3"
    assert by_key["current-stale"]["coverage_priority"] == "P0"
    assert by_key["high-demand-gap"]["coverage_priority"] == "P1"
    assert by_key["high-demand-ready"]["coverage_priority"] != "P1"
