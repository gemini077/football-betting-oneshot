from __future__ import annotations

from scripts.football_data.phase2c1_model import evaluate_predictions, probability_payload


def test_tied_score_probabilities_have_one_deterministic_top1():
    metrics = evaluate_predictions([{
        "target_match_id": "tie",
        "lambda_home": 1.0,
        "lambda_away": 1.0,
        "probabilities": probability_payload(1.0, 1.0),
        "actual": {"home_goals": 1, "away_goals": 0},
    }])

    exact = metrics["exact_score"]
    assert exact["actual_score_rank"] == 3
    assert exact["top1"] == 0.0
    assert exact["top3"] == 1.0

