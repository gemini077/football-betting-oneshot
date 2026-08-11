from __future__ import annotations

import pytest

from scripts.football_data.phase2c1_experiment import HeldoutAlreadyEvaluatedError, evaluate_heldout_once


def test_heldout_guard_allows_one_evaluation_only():
    result = evaluate_heldout_once([], heldout_evaluation_count=0)
    assert result["heldout_evaluation_count"] == 1

    with pytest.raises(HeldoutAlreadyEvaluatedError):
        evaluate_heldout_once([], heldout_evaluation_count=result["heldout_evaluation_count"])
