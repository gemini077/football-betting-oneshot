from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from review_metrics import _window_metrics


def test_review_metrics_keeps_each_market_family_separate():
    rows = [
        {"settlement": {"by_dimension": {
            "double_chance": {"hit": True, "units": 1.0, "profit": 0.8},
            "total": {"hit": None, "units": 0.0, "profit": 0.0},
        }}},
        {"settlement": {"by_dimension": {
            "double_chance": {"hit": False, "units": -1.0, "profit": -1.0},
            "total": {"hit": True, "units": 1.0, "profit": 0.9},
        }}},
    ]
    dimensions = _window_metrics(rows)["by_dimension"]
    assert dimensions["double_chance"]["samples"] == 2
    assert dimensions["double_chance"]["hit_rate"] == 0.5
    assert dimensions["total"]["effective_hit_rate"] == 0.5
