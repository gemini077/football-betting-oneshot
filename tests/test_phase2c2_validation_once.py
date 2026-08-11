import pytest

from scripts.football_data.phase2c2_opponent_strength import evaluate_validation_once
from tests.phase2c2_test_support import fold_targets


def test_reused_validation_can_only_be_evaluated_once(tmp_path):
    rows = fold_targets(4)
    first = evaluate_validation_once(rows, rows, tmp_path / "validation_guard.json")
    assert first["validation_evaluation_count"] == 1
    with pytest.raises(RuntimeError, match="once"):
        evaluate_validation_once(rows, rows, tmp_path / "validation_guard.json")
