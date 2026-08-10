from __future__ import annotations

from scripts.football_data.competition_demand import recover_competition_usage


def test_unresolved_metadata_is_reported_without_guessing_a_competition():
    result = recover_competition_usage(
        schedule_rows=[
            {
                "canonical_match_id": "schedule:unknown",
                "provider_match_id": "500-unknown",
                "home": "Alpha FC",
                "away": "Beta FC",
                "competition": None,
                "kickoff_local": "2026-08-03T20:00:00+08:00",
            }
        ],
        prematch_tasks={},
        analysis_jobs={"2026-08-03:500-unknown": {"match": "Alpha FC vs Beta FC"}},
        selected_matches=[],
        current_matches=[],
        generated_at="2026-08-10T00:00:00Z",
    )

    assert result["resolved_match_count"] == 0
    assert result["unresolved_match_count"] == 1
    assert result["unresolved_usage"][0]["resolution_status"] == "unresolved"
    assert result["job_recovery"]["still_unresolved_count"] == 1
    assert "unresolved" not in result["all_indexed_recent_production_period"]["competitions"]
