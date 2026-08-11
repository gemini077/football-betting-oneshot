from scripts.football_data.research_sanity import audit_source_observation_duplicates


def row(canonical_id: str) -> dict:
    return {
        "canonical_match_id": canonical_id,
        "competition_id": "competition:portugal-primeira-liga",
        "season_id": "season:portugal-primeira-liga:2025-26",
        "kickoff_at": "2025-08-09T15:30:00Z",
        "home_goals": 0,
        "away_goals": 2,
        "home_team_id": "team:one",
        "away_team_id": "team:two",
        "provider": "openfootball",
        "provider_match_id": "open:match:1",
        "provenance": {"source_record_ref": "open:ref:1"},
    }


def test_source_observation_split_is_flagged_without_merging_records():
    rows = [row("canonical:a"), row("canonical:b")]
    result = audit_source_observation_duplicates(rows)

    assert result["possible_identity_split_duplicate_count"] == 1
    assert result["merge_action"] == "exclude_until_review"
    assert result["groups"][0]["canonical_match_ids"] == ["canonical:a", "canonical:b"]


def test_exact_kickoff_score_split_is_flagged_without_fuzzy_time_window():
    first = row("canonical:a")
    second = row("canonical:b")
    first["raw_home_team"] = second["raw_home_team"] = "Alpha FC"
    first["raw_away_team"] = second["raw_away_team"] = "Beta FC"
    second["provider_match_id"] = "other:match:1"
    second["provenance"] = {"source_record_ref": "other:ref:1"}

    result = audit_source_observation_duplicates([first, second])

    methods = {group["detection_method"] for group in result["groups"]}
    assert "same_competition_season_kickoff_score" in methods
    assert result["merge_action"] == "exclude_until_review"
