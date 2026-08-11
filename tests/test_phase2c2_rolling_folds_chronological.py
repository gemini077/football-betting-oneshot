from scripts.football_data.phase2c2_opponent_strength import build_rolling_folds
from tests.phase2c2_test_support import fold_targets


def test_rolling_folds_are_expanding_and_chronological():
    folds = build_rolling_folds(fold_targets(12))
    assert len(folds) == 3
    for fold in folds:
        assert fold["train_max_kickoff"] < fold["evaluation_min_kickoff"]
        assert not set(fold["train_match_ids"]) & set(fold["evaluation_match_ids"])
