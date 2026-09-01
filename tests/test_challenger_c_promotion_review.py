import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from challenger_c_promotion_review import (  # noqa: E402
    EXPECTED_ACCEPTED_VERSION_ROW_METRICS,
    _metric_projection_matches,
    _safety_triggers,
    run_review,
)


def test_review_reproduces_unique_metrics_and_stops_below_unique_match_gate():
    evidence = run_review()

    assert evidence["decision"] == "KEEP CHAMPION / KEEP C SHADOW"
    assert evidence["safety_gate"]["status"] == "FAIL"
    assert evidence["overall_reproduction"]["status"] == "PASS"
    assert evidence["version_row_reproduction"]["status"] == "PASS"
    assert evidence["counts"]["verified_pair_rows"] == 112
    assert evidence["counts"]["verified_unique_matches"] == 29
    assert evidence["counts"]["promotion_eligible_unique_matches"] == 36
    assert evidence["counts"]["version_history_match_groups"] == 26
    assert evidence["counts"]["extra_version_rows"] == 83
    assert evidence["counts"]["duplicate_verified_match_groups"] == 26
    assert evidence["safety_gate"]["checks"]["unique_match_promotion_gate"] is False
    assert evidence["overall"]["metrics"]["champion"]["sample_count"] == 29
    assert evidence["overall"]["version_row_audit_metrics"]["champion"]["sample_count"] == 112
    assert evidence["integrity"]["status"] == "PASS"
    assert evidence["source"]["new_matches_fetched"] is False


def test_expected_metric_projection_is_strict():
    observed = {
        candidate: dict(metrics)
        for candidate, metrics in EXPECTED_ACCEPTED_VERSION_ROW_METRICS.items()
    }
    assert _metric_projection_matches(observed, EXPECTED_ACCEPTED_VERSION_ROW_METRICS)["status"] == "PASS"
    observed["challenger"]["exact_nll"] += 0.000001
    assert _metric_projection_matches(observed, EXPECTED_ACCEPTED_VERSION_ROW_METRICS)["status"] == "FAIL"


def test_safety_floor_only_uses_explicit_proper_metric_floors():
    champion = {
        "one_x_two_brier": 0.30,
        "one_x_two_log_loss": 0.60,
        "btts_brier": 0.25,
        "ou_2_5_brier": 0.20,
    }
    challenger = {
        "one_x_two_brier": 0.41,
        "one_x_two_log_loss": 0.82,
        "btts_brier": 0.331,
        "ou_2_5_brier": 0.20,
        "btts_ece": 0.99,
    }
    triggers = _safety_triggers({"champion": champion, "challenger": challenger})
    assert {item["metric"] for item in triggers} == {
        "one_x_two_brier",
        "one_x_two_log_loss",
        "btts_brier",
    }
    assert all(item["metric"] != "btts_ece" for item in triggers)


@pytest.mark.parametrize("path", [
    ROOT / "data" / "prediction_quality" / "market_side_shadow_1" / "latest.json",
])
def test_review_input_is_current_shadow_artifact(path):
    document = json.loads(path.read_text(encoding="utf-8"))
    assert document["candidate_id"] == "market_side_only_hybrid"
    assert document["checkpoint"]["status"] == "NOT_REACHED"
    assert document["checkpoint"]["verified_unique_matches"] == 29
    assert document["checkpoint"]["verified_pair_version_rows"] == 112
