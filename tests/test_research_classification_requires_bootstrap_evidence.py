from __future__ import annotations

from scripts.football_data.phase2c1_model import classification_from_evidence


CORE = {
    "one_x_two_log_loss": -0.02,
    "one_x_two_brier": -0.01,
    "goal_distribution_nll": -0.01,
    "over_2_5_log_loss": -0.01,
    "btts_log_loss": -0.005,
}


def test_point_estimate_improvement_without_bootstrap_is_inconclusive():
    assert classification_from_evidence(CORE, {}) == "INCONCLUSIVE"


def test_promising_requires_a_bootstrap_ci_excluding_zero():
    bootstrap = {
        metric: {"ci_95": [-0.03, -0.001] if metric == "one_x_two_log_loss" else [-0.02, 0.02]}
        for metric in CORE
    }
    assert classification_from_evidence(CORE, bootstrap) == "RESEARCH_PROMISING"

