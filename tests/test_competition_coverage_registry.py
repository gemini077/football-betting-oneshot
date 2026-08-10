from __future__ import annotations

from scripts.football_data.coverage import build_coverage_registry, rank_coverage_gaps


def test_observed_competitions_are_separate_from_canonical_registry_status():
    registry = build_coverage_registry(
        observed=[
            {"raw_name": "瑞典超级联赛", "competition_key": "sweden-allsvenskan", "current_match_count": 2, "historical_record_count": 0},
            {"raw_name": "葡萄牙超级联赛", "competition_key": "portugal-primeira-liga", "current_match_count": 1, "historical_record_count": 0},
        ],
        entries=[
            {"competition_key": "sweden-allsvenskan", "name": "Sweden Allsvenskan", "canonical_competition_id": None, "result_coverage": "UNVERIFIED"},
        ],
    )

    assert len(registry["observed_competitions"]) == 2
    sweden = next(item for item in registry["competitions"] if item["competition_key"] == "sweden-allsvenskan")
    assert sweden["canonical_competition_id"] is None
    assert sweden["result_coverage"] == "UNVERIFIED"


def test_gap_ranking_uses_observed_frequency_before_name_or_league_prestige():
    ranked = rank_coverage_gaps([
        {"competition_key": "rare", "current_match_count": 0, "observed_count": 1, "result_coverage": "MISSING", "team_identity_coverage": 0.0},
        {"competition_key": "current-gap", "current_match_count": 3, "observed_count": 3, "result_coverage": "MISSING", "team_identity_coverage": 0.0},
        {"competition_key": "covered", "current_match_count": 2, "observed_count": 20, "result_coverage": "SUPPORTED", "team_identity_coverage": 1.0},
    ])

    assert ranked[0]["competition_key"] == "current-gap"
    assert ranked[0]["coverage_priority"] == "P0"
