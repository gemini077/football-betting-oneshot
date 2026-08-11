from scripts.football_data.phase2c2_opponent_strength import classification_from_exploratory_evidence


def test_cross_zero_validation_evidence_is_exploratory_inconclusive():
    deltas = {name: -0.01 for name in ("one_x_two_log_loss", "one_x_two_brier", "goal_distribution_nll", "over_2_5_log_loss", "btts_log_loss")}
    bootstrap = {name: {"ci_95": [-0.1, 0.1]} for name in deltas}
    assert classification_from_exploratory_evidence(deltas, bootstrap, rolling_fold_improvements=2, rolling_fold_count=3) == "EXPLORATORY_INCONCLUSIVE"


def test_exploratory_promising_requires_ci_and_fold_consistency():
    names = ("one_x_two_log_loss", "one_x_two_brier", "goal_distribution_nll", "over_2_5_log_loss", "btts_log_loss")
    deltas = {name: -0.01 for name in names}
    bootstrap = {name: {"ci_95": [-0.1, -0.001]} for name in names}
    assert classification_from_exploratory_evidence(deltas, bootstrap, rolling_fold_improvements=2, rolling_fold_count=3) == "EXPLORATORY_PROMISING"
