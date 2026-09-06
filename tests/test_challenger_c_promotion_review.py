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


def test_review_reproduces_109_unique_metrics_and_separates_natural_growth():
    evidence = run_review()

    assert evidence["milestone"] == "CHALLENGER-C-100-PROMOTION-REVIEW-1"
    assert evidence["decision"] == "C_PROMOTION_REVIEW_INCONCLUSIVE"
    assert evidence["integrity"]["status"] == "PASS"
    assert evidence["cohort"]["verified_unique_matches"] == 109
    assert evidence["cohort"]["natural_growth_unique_matches"] == 2
    assert evidence["cohort"]["natural_growth_included_in_decision"] is False
    assert evidence["primary_exact_nll"]["n"] == 109
    assert evidence["primary_exact_nll"]["iid_bootstrap_95_ci"]["resamples"] >= 10_000
    assert evidence["primary_exact_nll"]["moving_block_bootstrap_95_ci"]["block_length"] == 10
    assert evidence["overall"]["overall_reproduction_against_109_authority"]["status"] == "PASS"
    assert evidence["overall"]["shadow_reference_reproduction"]["status"] == "PASS"
    assert evidence["immutable_exact_authority"]["status"] == "PASS"
    assert evidence["market_control"]["status"] == "COMPARABLE"
    assert evidence["market_control"]["cohort_match_count"] == 107
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
    assert document["checkpoint"]["status"] == "PROMOTION_REVIEW_READY"
    assert document["checkpoint"]["verified_unique_matches"] == 109
    assert document["checkpoint"]["promotion_review_minimum"] == 100
    assert document["checkpoint"]["auto_promote"] is False
