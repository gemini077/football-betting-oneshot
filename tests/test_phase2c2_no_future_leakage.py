from scripts.football_data.phase2c2_opponent_strength import (
    OpponentSpec,
    build_opponent_adjusted_prediction,
)
from tests.phase2c2_test_support import paired_history, result, target


def test_opponent_prediction_uses_only_prior_kickoffs():
    history = paired_history(count=10)
    future = result("future", "2026-04-01T12:00:00Z", "team:home", "team:late", 7, 0)
    prediction = build_opponent_adjusted_prediction(
        target(),
        history + [future],
        OpponentSpec(regularization=10),
    )
    used_ids = set(prediction["features"]["used_match_ids"])
    assert "future" not in used_ids
    assert "target" not in used_ids
    assert all(kickoff < "2026-03-01T12:00:00Z" for kickoff in prediction["features"]["used_kickoffs"])
