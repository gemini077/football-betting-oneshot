from scripts.football_data.phase2c2_opponent_strength import OpponentSpec, build_opponent_adjusted_prediction
from tests.phase2c2_test_support import paired_history, target


def test_opponent_prediction_reuses_coherent_poisson_distribution():
    prediction = build_opponent_adjusted_prediction(target(), paired_history(), OpponentSpec(regularization=10))
    probabilities = prediction["probabilities"]
    assert abs(sum(probabilities["1x2"].values()) - 1.0) < 1e-12
    assert abs(probabilities["totals"]["over_2_5"] + probabilities["totals"]["under_2_5"] - 1.0) < 1e-12
    assert abs(probabilities["btts"]["yes"] + probabilities["btts"]["no"] - 1.0) < 1e-12
    assert len(probabilities["top_scores"]) == 10
