from scripts.football_data.research_preflight import evaluate_readiness_gate


def _concentration() -> dict:
    return {
        "largest_competition_share": 0.4,
        "largest_season_share": 0.4,
        "largest_team_appearance_share": 0.1,
    }


def test_recommended_dataset_sanity_requires_explicit_pass():
    unknown_gate = evaluate_readiness_gate(
        recommended_fixture_count=240,
        recommended_competitions=["competition:a", "competition:b", "competition:c"],
        recommended_team_count=40,
        timeline={"competition:a": True, "competition:b": True, "competition:c": True},
        concentration=_concentration(),
        dataset_sanity_passed=False,
    )
    passed_gate = evaluate_readiness_gate(
        recommended_fixture_count=240,
        recommended_competitions=["competition:a", "competition:b", "competition:c"],
        recommended_team_count=40,
        timeline={"competition:a": True, "competition:b": True, "competition:c": True},
        concentration=_concentration(),
        dataset_sanity_passed=True,
    )

    assert unknown_gate["criteria"]["recommended_cohort_dataset_sanity_passed"] is False
    assert unknown_gate["phase2c_1_research_ready"] is False
    assert passed_gate["criteria"]["recommended_cohort_dataset_sanity_passed"] is True
    assert passed_gate["phase2c_1_research_ready"] is True
