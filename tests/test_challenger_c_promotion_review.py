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
from market_side_shadow_refresh import CURRENT_VIEW_SCHEMA_VERSION, refresh_shadow  # noqa: E402


@pytest.fixture
def current_review(tmp_path):
    pair_root = ROOT / "data" / "prediction_quality" / "market_side_shadow_1" / "pairs"
    result_root = ROOT / "data" / "postmatch_automation" / "results"
    latest_path = tmp_path / "latest.json"
    refresh_shadow(
        pair_root=pair_root,
        result_root=result_root,
        output=latest_path,
        refreshed_at="2026-09-08T00:00:00+00:00",
    )
    return run_review(
        latest_path=latest_path,
        pair_root=pair_root,
        result_root=result_root,
    )


def test_review_loads_compact_pair_index_and_reproduces_stored_evaluation(current_review):
    evidence = current_review

    assert evidence["overall_reproduction"]["status"] == "PASS"
    assert evidence["integrity"]["status"] == "PASS"
    assert evidence["counts"]["pair_rows"] == evidence["counts"]["total_pair_version_rows"]
    assert evidence["source"]["pair_root"].endswith("market_side_shadow_1/pairs")


def test_review_reproduces_unique_metrics_and_stops_before_promotion_action(current_review):
    evidence = current_review

    assert evidence["overall_reproduction"]["status"] == "PASS"
    assert evidence["integrity"]["status"] == "PASS"
    assert evidence["counts"]["verified_pair_rows"] == evidence["counts"]["verified_pair_version_rows"]
    assert evidence["counts"]["verified_unique_matches"] <= evidence["counts"]["promotion_eligible_unique_matches"]
    assert evidence["overall"]["metrics"]["champion"]["sample_count"] == evidence["counts"]["verified_unique_matches"]
    assert evidence["overall"]["version_row_audit_metrics"]["champion"]["sample_count"] == evidence["counts"]["verified_pair_version_rows"]
    assert evidence["source"]["new_matches_fetched"] is False
    assert evidence["production_action"] == "STOPPED_BEFORE_PROMOTION"
    assert evidence["no_new_challenger"] is True


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
    assert document["schema_version"] == CURRENT_VIEW_SCHEMA_VERSION
    assert "pairs" not in document
    assert len(document["pair_index"]["pair_set_digest"]) == 64
    assert "entries" not in document["pair_index"]
    assert "representative_selector" not in document["evaluation"]
    assert document["pair_index"]["pair_count"] > 0
    assert document["checkpoint"]["auto_promote"] is False
