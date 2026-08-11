from __future__ import annotations

import json
from pathlib import Path

from scripts.football_data.phase2c1_experiment import _benchmark_health, _handoff_entries


def test_handoff_entries_include_shared_test_support_helper():
    root = Path(__file__).resolve().parents[1]
    summary = json.loads((root / "data/football_data/phase2c1_results_summary.json").read_text(encoding="utf-8"))
    entries = _handoff_entries(root, summary, _benchmark_health(root), 73)
    assert "tests/phase2c1_test_support.py" in entries

