from __future__ import annotations

import json

import pytest

from scripts.football_data.data_home import resolve_football_data_home
from scripts.football_data.phase2c1_experiment import recompute_locked_heldout_metrics
from scripts.football_data.verify_data_home import verify_data_home


def test_metrics_only_recompute_keeps_heldout_count_at_one():
    if verify_data_home().get("status") != "OK":
        pytest.skip("shared Football Data Home unavailable; locked held-out recompute not executed")
    guard_path = resolve_football_data_home() / "research" / "phase2c1" / "heldout_evaluation.json"
    before = guard_path.read_text(encoding="utf-8")
    result = recompute_locked_heldout_metrics(write=False)
    after = guard_path.read_text(encoding="utf-8")
    assert json.loads(before)["heldout_evaluation_count"] == 1
    assert result["heldout_evaluation"]["heldout_evaluation_count"] == 1
    assert after == before

