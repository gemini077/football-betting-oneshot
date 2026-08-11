from __future__ import annotations

from scripts.football_data.phase2c1_model import evaluate_predictions


def row(match_id: str, actual_home: int, actual_away: int) -> dict:
    return {
        "target_match_id": match_id,
        "actual": {"home_goals": actual_home, "away_goals": actual_away},
        "lambda_home": 1.4,
        "lambda_away": 0.8,
        "probabilities": {
            "1x2": {"home": 0.5, "draw": 0.25, "away": 0.25},
            "totals": {"over_2_5": 0.45, "under_2_5": 0.55},
            "btts": {"yes": 0.4, "no": 0.6},
        },
        "score_matrix": {"0": {"0": 0.2}},
        "score_matrix_tail_probability": 0.8,
    }


def test_metrics_report_primary_and_secondary_outputs():
    metrics = evaluate_predictions([row("one", 1, 0), row("two", 0, 1)])
    assert metrics["sample"] == 2
    assert "one_x_two_log_loss" in metrics
    assert "goal_distribution_nll" in metrics
    assert "calibration" in metrics
    assert "exact_score" in metrics
