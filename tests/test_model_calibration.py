import json
from pathlib import Path

from build_model_calibration import build_calibration


def _write_sample(root: Path, index: int, actual: str, family: str = "recent_form_market_calibrated_poisson_v2"):
    report = root / f"report-{index}.json"
    report.write_text(json.dumps({
        "report": {"model_version": "v-test"},
        "model": {
            "method": family,
            "probabilities": {"home": 0.70, "draw": 0.20, "away": 0.10},
        },
    }), encoding="utf-8")
    labels = {"home": "主胜", "draw": "平局", "away": "客胜"}
    review = {
        "source_report": str(report),
        "match": {"kickoff_local": f"2026-07-{index + 1:02d}T03:00:00+08:00"},
        "result": {"outcome": labels[actual], "total_goals": 3},
        "settlement": {"expected_goals": {"pick": 2.0}},
        "calibration_weight": 1.0,
    }
    (root / f"review-{index}.json").write_text(json.dumps(review, ensure_ascii=False), encoding="utf-8")


def test_walk_forward_calibration_only_activates_validated_adjustments(tmp_path):
    actuals = ["away", "draw", "away", "home"] * 6
    for index, actual in enumerate(actuals):
        _write_sample(tmp_path, index, actual)

    result = build_calibration(tmp_path)

    assert result["sample"]["compatible"] == 24
    assert result["direction"]["approved"] is True
    assert result["total_goals"]["approved"] is True
    assert result["active"] is True
    assert result["direction"]["validation"]["brier_after"] < result["direction"]["validation"]["brier_before"]
    assert result["total_goals"]["validation"]["mae_after"] < result["total_goals"]["validation"]["mae_before"]


def test_calibration_observes_without_minimum_sample(tmp_path):
    for index in range(10):
        _write_sample(tmp_path, index, "home")

    result = build_calibration(tmp_path)

    assert result["status"] == "observing"
    assert result["active"] is False
    assert result["sample"]["compatible"] == 10
