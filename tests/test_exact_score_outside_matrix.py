from __future__ import annotations

from scripts.football_data.phase2c1_model import evaluate_predictions, probability_payload


def test_actual_score_outside_matrix_has_no_rank_or_top_k_membership():
    metrics = evaluate_predictions([{
        "target_match_id": "outside",
        "lambda_home": 1.0,
        "lambda_away": 1.0,
        "probabilities": probability_payload(1.0, 1.0),
        "actual": {"home_goals": 9, "away_goals": 0},
    }])

    exact = metrics["exact_score"]
    assert exact["actual_score_in_matrix"] is False
    assert exact["actual_score_rank"] is None
    assert exact["top1"] == 0.0
    assert exact["top3"] == 0.0
    assert exact["top5"] == 0.0
    assert exact["top10"] == 0.0
    assert exact["actual_score_log_probability"] > 0

