from __future__ import annotations

from scripts.football_data.populate_p0_p1_coverage import _source_manifest


def test_manifest_keeps_provider_counts_separate_and_reports_partial_openfootball():
    base = {
        "competition_id": "competition:sweden-allsvenskan",
        "season_id": "season:sweden-allsvenskan:2025",
        "competition_key": "sweden-allsvenskan",
        "provider_competition_id": "provider:sweden",
        "provider_season_id": "2025",
        "provider": "openfootball",
        "raw_text": "# Date Sat Mar 29 2025 - Sun Nov 30 2025 (246d)\n# Matches 240\n",
    }
    other = {
        **base,
        "provider": "football-data.co.uk",
        "raw_text": "Date,Home,Away,HG,AG\n",
    }
    manifest = _source_manifest(
        [base, other],
        [
            {**{k: base[k] for k in ("provider", "competition_id", "season_id")}, "parsed_records": 53, "eligible_records": 53, "mapped_team_names": 10},
            {**{k: other[k] for k in ("provider", "competition_id", "season_id")}, "parsed_records": 240, "eligible_records": 240, "mapped_team_names": 10},
        ],
        "2026-08-11T00:00:00Z",
    )

    assert manifest["sources"][0]["parsed_result_count"] == 53
    assert manifest["sources"][0]["listed_match_count"] == 240
    assert manifest["sources"][0]["result_completion_ratio"] == 53 / 240
    assert manifest["sources"][0]["source_completeness_status"] == "PARTIAL"
    assert manifest["sources"][1]["parsed_result_count"] == 240
