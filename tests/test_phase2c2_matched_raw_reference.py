from scripts.football_data.phase2c2_opponent_strength import (
    MatchedRawSpec,
    OpponentSpec,
    build_matched_raw_prediction,
    build_opponent_adjusted_prediction,
)
from tests.phase2c2_test_support import paired_history, target


def test_matched_raw_uses_same_environment_and_regularization_without_opponent_adjustment():
    rows = paired_history()
    opponent = build_opponent_adjusted_prediction(target(), rows, OpponentSpec(regularization=10))
    raw = build_matched_raw_prediction(target(), rows, MatchedRawSpec(regularization=10))
    assert opponent["features"]["league_home_goal_rate"] == raw["features"]["league_home_goal_rate"]
    assert opponent["features"]["regularization"] == raw["features"]["regularization"]
    assert opponent["features"]["opponent_strength_used"] is True
    assert raw["features"]["opponent_strength_used"] is False
