from __future__ import annotations

from scripts.football_data.phase2c1_model import classification_from_evidence


def test_all_primary_bootstrap_intervals_cross_zero():
    deltas = {
        "one_x_two_log_loss": -0.02,
        "one_x_two_brier": -0.01,
        "goal_distribution_nll": 0.01,
        "over_2_5_log_loss": 0.01,
        "btts_log_loss": -0.001,
    }
    bootstrap = {
        metric: {"ci_95": [-0.02, 0.02]}
        for metric in deltas
    }
    assert classification_from_evidence(deltas, bootstrap) == "INCONCLUSIVE"

