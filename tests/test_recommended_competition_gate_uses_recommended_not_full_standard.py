from scripts.football_data.research_preflight import evaluate_readiness_gate


def test_gate_counts_recommended_competitions_only():
    gate = evaluate_readiness_gate(
        recommended_fixture_count=240,
        recommended_competitions=["competition:a", "competition:b"],
        recommended_team_count=40,
        timeline={"competition:a": True, "competition:b": True},
        concentration={"largest_competition_share": 0.4, "largest_season_share": 0.4, "largest_team_appearance_share": 0.1},
        full_standard_competitions=["competition:a", "competition:b", "competition:c", "competition:d"],
    )

    assert gate["criteria"]["eligible_competitions_at_least_3"] is False
    assert gate["phase2c_1_research_ready"] is False
