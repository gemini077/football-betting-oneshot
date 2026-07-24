from prediction_quality import classify_prediction


def test_execution_price_does_not_force_research_grade():
    payload = {
        "data_quality": {"missing": ["确认首发", "即时伤停", "用户渠道即时赔率"]},
        "model": {"calibration": {"checkpoint_features": {"snapshot_count": 2}}},
        "decisions": {"unique_primary_dimension": "胜平负：主胜"},
        "betting": {"candidates": []},
    }

    result = classify_prediction(payload)

    assert result["data_grade"] == "B"
    assert result["formal_pick_eligible"] is True
    assert result["execution_eligible"] is False
    assert "用户渠道即时赔率" not in result["analysis_missing"]
