from __future__ import annotations

import json

from scripts.football_data import recover_competition_demand as recovery
from scripts.football_data.competition_demand import recover_competition_usage


def test_recovery_links_job_metadata_and_deduplicates_sources():
    result = recover_competition_usage(
        schedule_rows=[
            {
                "canonical_match_id": "schedule:1",
                "provider_match_id": "500-1",
                "home": "Home FC",
                "away": "Away FC",
                "competition": "巴西甲级联赛",
                "kickoff_local": "2026-08-01T20:00:00+08:00",
            }
        ],
        prematch_tasks={
            "task-1": {
                "provider_match_id": "500-1",
                "home": "Home FC",
                "away": "Away FC",
                "league": "巴西甲级联赛",
                "kickoff": "2026-08-01T20:00:00+08:00",
            },
            "task-2": {
                "provider_match_id": "France|England",
                "home": "France",
                "away": "England",
                "league": "世界杯",
                "kickoff": "2026-08-02T20:00:00+08:00",
            },
        },
        analysis_jobs={
            "2026-08-01:500-1": {"match": "Home FC vs Away FC"},
            "2026-08-02:500-2": {"match": "France vs England"},
        },
        selected_matches=[],
        current_matches=[],
        generated_at="2026-08-10T00:00:00Z",
    )

    assert result["job_recovery"]["analysis_job_count"] == 2
    assert result["job_recovery"]["recovered_count"] == 2
    assert result["job_recovery"]["still_unresolved_count"] == 0
    assert result["resolved_match_count"] == 2
    assert result["unresolved_match_count"] == 0
    assert result["all_indexed_recent_production_period"]["competitions"]["brazil-serie-a"]["project_analysis_count"] == 1
    assert result["all_indexed_recent_production_period"]["competitions"]["fifa-world-cup"]["project_analysis_count"] == 1


def test_recovery_keeps_source_evidence_on_a_single_project_match():
    result = recover_competition_usage(
        schedule_rows=[
            {
                "canonical_match_id": "schedule:1",
                "provider_match_id": "500-1",
                "home": "Home FC",
                "away": "Away FC",
                "competition": "巴西甲级联赛",
                "kickoff_local": "2026-08-01T20:00:00+08:00",
            }
        ],
        prematch_tasks={
            "task-1": {
                "provider_match_id": "500-1",
                "home": "Home FC",
                "away": "Away FC",
                "league": "巴西甲级联赛",
                "kickoff": "2026-08-01T20:00:00+08:00",
            }
        },
        analysis_jobs={},
        selected_matches=[],
        current_matches=[],
        generated_at="2026-08-10T00:00:00Z",
    )

    competition = result["all_indexed_recent_production_period"]["competitions"]["brazil-serie-a"]
    assert competition["project_analysis_count"] == 1
    assert competition["evidence_source_count"] == 2


def test_exact_selected_match_metadata_can_enrich_a_schedule_without_competition():
    result = recover_competition_usage(
        schedule_rows=[
            {
                "canonical_match_id": "schedule:world-cup",
                "home": "France",
                "away": "Spain",
                "competition": None,
                "kickoff_local": "2026-07-15T03:00:00+08:00",
            }
        ],
        prematch_tasks={},
        analysis_jobs={},
        selected_matches=[
            {
                "id": "2040507",
                "home": "France",
                "away": "Spain",
                "league": "世界杯",
                "kickoff": "2026-07-15 03:00",
            }
        ],
        current_matches=[],
        generated_at="2026-08-10T00:00:00Z",
    )

    assert result["resolved_match_count"] == 1
    assert result["unresolved_match_count"] == 0
    assert result["all_indexed_recent_production_period"]["competitions"]["fifa-world-cup"]["project_analysis_count"] == 1


def test_current_identity_evidence_is_used_when_latest_workspace_is_empty(tmp_path):
    latest_path = tmp_path / "latest.json"
    evidence_path = tmp_path / "current_match_identity_evidence.json"
    latest_path.write_text(json.dumps({"matches": []}), encoding="utf-8")
    evidence_path.write_text(
        json.dumps({
            "matches": [{
                "id": "500-current",
                "provider_match_id": "500-current",
                "home": "Home FC",
                "away": "Away FC",
                "league": "宸磋タ鐢茬骇鑱旇禌",
                "kickoff_at": "2026-08-11T01:00:00+08:00",
            }]
        }),
        encoding="utf-8",
    )

    current = recovery.load_current_matches(latest_path, evidence_path)

    assert len(current) == 1
    assert current[0]["provider_match_id"] == "500-current"
