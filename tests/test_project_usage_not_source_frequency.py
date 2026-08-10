from __future__ import annotations

from scripts.football_data.coverage import build_coverage_registry, rank_coverage_gaps


def test_source_record_count_does_not_raise_project_usage_priority():
    rows = [
        {
            "competition_key": "source-heavy",
            "current_match_count": 0,
            "project_analysis_count": 0,
            "analysis_count_30d": 0,
            "analysis_count_90d": 0,
            "source_record_count": 1000,
            "result_coverage": "PARTIAL",
            "team_identity_coverage": 1.0,
        },
        {
            "competition_key": "project-used",
            "current_match_count": 0,
            "project_analysis_count": 3,
            "analysis_count_30d": 3,
            "analysis_count_90d": 3,
            "source_record_count": 1,
            "result_coverage": "MISSING",
            "team_identity_coverage": 0.0,
        },
    ]

    ranked = rank_coverage_gaps(rows)
    by_key = {row["competition_key"]: row for row in ranked}

    assert by_key["project-used"]["coverage_priority"] == "P2"
    assert by_key["source-heavy"]["coverage_priority"] == "P3"
    assert "source_record_count" not in by_key["source-heavy"].get("priority_reason", "")


def test_registry_keeps_project_usage_and_source_records_separate():
    registry = build_coverage_registry(
        observed=[
            {
                "competition_key": "sweden-allsvenskan",
                "raw_name": "Sweden Allsvenskan",
                "project_analysis_count": 2,
                "analysis_count_30d": 2,
                "analysis_count_90d": 2,
                "source_record_count": 119,
                "current_match_count": 2,
            }
        ],
        entries=[{
            "competition_key": "sweden-allsvenskan",
            "name": "Sweden Allsvenskan",
            "canonical_competition_id": "competition:sweden-allsvenskan",
            "result_coverage": "PARTIAL",
        }],
    )

    row = next(item for item in registry["competitions"] if item["competition_key"] == "sweden-allsvenskan")
    assert row["project_analysis_count"] == 2
    assert row["source_record_count"] == 119
    assert row["current_match_count"] == 2


def test_source_only_competition_is_not_project_observed():
    registry = build_coverage_registry(
        observed=[{
            "competition_key": "source-only",
            "raw_name": "Imported League",
            "source_record_count": 500,
            "current_match_count": 0,
        }],
        entries=[],
    )

    assert registry["observed_competitions"] == []
    assert registry["source_observed_competitions"][0]["source_record_count"] == 500
