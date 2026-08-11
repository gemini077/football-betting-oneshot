from scripts.football_data.research_preflight import cohort_manifest


def row(index: int) -> dict:
    return {
        "canonical_match_id": f"match:{index}",
        "competition_id": "competition:test",
        "season_id": "season:test:2026",
        "kickoff_at": f"2026-01-{index + 1:02d}T12:00:00Z",
        "home_team_id": f"team:home:{index}",
        "away_team_id": f"team:away:{index}",
    }


def test_cohort_id_changes_when_sanity_excludes_a_fixture():
    full = cohort_manifest("standard_recommended", [row(0), row(1)], dataset_digest="dataset")
    reduced = cohort_manifest("standard_recommended", [row(0)], dataset_digest="dataset")

    assert full["research_cohort_id"] != reduced["research_cohort_id"]
    assert full["cohort_match_id_digest"] != reduced["cohort_match_id_digest"]
