from __future__ import annotations

import pytest

from scripts.football_data.phase2c1_model import evaluate_predictions, probability_payload


def prediction(match_id: str, actual_home: int, actual_away: int) -> dict:
    return {
        "target_match_id": match_id,
        "lambda_home": 1.0,
        "lambda_away": 1.0,
        "probabilities": probability_payload(1.0, 1.0),
        "actual": {"home_goals": actual_home, "away_goals": actual_away},
    }


def test_calibration_reports_home_draw_away_and_macro_ece():
    metrics = evaluate_predictions([
        prediction("home", 1, 0),
        prediction("draw", 1, 1),
        prediction("away", 0, 1),
    ])

    one_x_two = metrics["calibration"]["one_x_two"]
    assert set(one_x_two) == {"home", "draw", "away", "macro_ece"}
    for label in ("home", "draw", "away"):
        assert {"ece", "bins"} <= set(one_x_two[label])
        assert all({"count", "mean_probability", "observed_rate"} <= set(item) for item in one_x_two[label]["bins"])
    assert one_x_two["macro_ece"] == pytest.approx(
        sum(one_x_two[label]["ece"] for label in ("home", "draw", "away")) / 3
    )

