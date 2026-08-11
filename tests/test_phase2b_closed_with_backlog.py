from scripts.football_data.final_coverage import build_phase2b_closure_decision


def test_final_closure_preserves_backlog_and_subset_governance_gate():
    closure = build_phase2b_closure_decision(
        weighted={"eighty_percent_gate_passed": False},
        coverage_backlog={
            "identity_missing": 72,
            "source_missing": 60,
            "total_not_ready": 132,
            "by_competition": {
                "identity_missing": {"norway-eliteserien": 23},
                "source_missing": {"uefa-champions-league": 16},
            },
        },
    )

    assert closure["phase2b_complete"] is True
    assert closure["phase2b_closed"] is True
    assert closure["phase2b_closed_with_backlog"] is True
    assert closure["coverage_backlog"]["identity_missing"] == 72
    assert closure["coverage_backlog"]["source_missing"] == 60
    assert closure["coverage_backlog"]["total_not_ready"] == 132
    assert closure["global_model_data_ready"] is False
    assert closure["eligible_subset_evaluation_required"] is True
