import hashlib
import json
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from automatic_model_core import build_automatic_model
from model_governance import (
    PredictionConflictError,
    build_current_metrics,
    build_prediction_record,
    can_update_parameters,
    evaluate_promotion,
    freeze_prediction,
    hash_files,
    load_config,
)


MODEL_FAMILY = "recent_form_market_calibrated_poisson_v2"
RELEASE_VERSION = "v0.19.0"


def prediction_payload(grade="B", *, model_family=MODEL_FAMILY, odds=None):
    candidate = [] if odds is None else [{"odds": odds, "price_source": "real-executable"}]
    return {
        "report": {
            "model_version": RELEASE_VERSION,
            "analysis_timestamp": "2026-08-05T00:00:00+08:00",
            "snapshot_timestamp": "2026-08-04T23:59:00+08:00",
            "market_checkpoint": {"captured_at": "2026-08-04T23:59:00+08:00"},
        },
        "match": {
            "canonical_match_id": "FBOS-test-001",
            "home": "Home FC",
            "away": "Away FC",
            "kickoff_local": "2026-08-05T02:00:00+08:00",
        },
        "data_quality": {"missing": []},
        "model": {
            "method": model_family,
            "lambda_home": 1.2,
            "lambda_away": 0.9,
            "rho": 0.0,
            "probabilities": {"home": 0.45, "draw": 0.3, "away": 0.25},
            "score_probabilities": [
                {"score": "1-0", "probability": 0.15},
                {"score": "1-1", "probability": 0.13},
                {"score": "0-0", "probability": 0.10},
                {"score": "2-0", "probability": 0.09},
                {"score": "2-1", "probability": 0.08},
            ],
            "dimension_predictions": {
                "1x2": {"selection": "home", "model_probability": 0.45}
            },
        },
        "decisions": {
            "data_grade": grade,
            "prediction_tier": "formal" if grade in {"A", "B"} else "research",
            "unique_primary_dimension": "胜平负：主胜",
            "unique_score": "1-0",
        },
        "betting": {"candidates": candidate},
        "automation": {"provider": "fixed-python-core"},
    }


def test_champion_configuration_loads_and_matches_actual_model():
    config = load_config()
    assert config["champion"]["model_core_version"] == MODEL_FAMILY
    assert config["champion"]["model_family"] == MODEL_FAMILY
    assert config["champion"]["release_version"] == RELEASE_VERSION
    assert config["champion"]["rho"] == 0.0
    assert config["challengers"] == []


def test_governance_version_fields_are_complete():
    config = load_config()
    versions = config["versions"]
    assert all(versions.get(key) for key in (
        "feature_version",
        "data_pipeline_version",
        "report_schema_version",
        "postmatch_schema_version",
        "prompt_version",
    ))
    assert prediction_payload()["automation"]["provider"] == "fixed-python-core"


def test_same_input_freeze_is_idempotent(tmp_path):
    record = build_prediction_record(prediction_payload(), commit_sha="baseline-sha")
    first = freeze_prediction(record, tmp_path)
    second = freeze_prediction(record, tmp_path)
    assert first["status"] == "created"
    assert second["status"] == "existing"
    assert first["path"] == second["path"]


def test_same_prediction_id_with_different_content_is_a_conflict(tmp_path):
    record = build_prediction_record(prediction_payload(), commit_sha="baseline-sha")
    freeze_prediction(record, tmp_path)
    changed = dict(record)
    changed["lambda_home"] = 9.9
    changed["prediction_sha256"] = hashlib.sha256(
        json.dumps(
            {key: value for key, value in changed.items() if key != "prediction_sha256"},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    with pytest.raises(PredictionConflictError):
        freeze_prediction(changed, tmp_path)


def test_frozen_prediction_rejects_postmatch_fields():
    payload = prediction_payload()
    payload["result"] = {"score_90m": "1-0"}
    with pytest.raises(ValueError, match="postmatch"):
        build_prediction_record(payload, commit_sha="baseline-sha")


def test_frozen_prediction_rejects_nested_postmatch_fields(tmp_path):
    record = build_prediction_record(prediction_payload(), commit_sha="baseline-sha")
    record["prediction_output"]["result"] = {"score_90m": "1-0"}
    with pytest.raises(ValueError, match="postmatch"):
        freeze_prediction(record, tmp_path)


@pytest.mark.parametrize("grade, formal", [("A", True), ("B", True), ("C", False), ("D", False)])
def test_quality_grade_controls_formal_eligibility(grade, formal):
    record = build_prediction_record(prediction_payload(grade), commit_sha="baseline-sha")
    assert record["formal_eligible"] is formal
    assert record["prediction_output"]["status"] == ("formal" if formal else "research_only")


def test_b_grade_allowed_quality_gap_does_not_cancel_formal_eligibility():
    payload = prediction_payload("B")
    payload["data_quality"] = {"missing": ["lineup confirmation"]}
    record = build_prediction_record(payload, commit_sha="baseline-sha")
    assert record["formal_eligible"] is True
    assert record["missing_critical_fields"] == ["lineup confirmation"]


def test_legacy_and_champion_records_are_separated():
    champion = build_prediction_record(prediction_payload(), commit_sha="baseline-sha")
    legacy = build_prediction_record(
        prediction_payload(model_family="legacy_poisson_v1"), commit_sha="baseline-sha"
    )
    assert champion["model_role"] == "champion"
    assert legacy["model_role"] == "legacy"
    assert legacy["formal_eligible"] is False


def test_previous_release_is_not_current_champion():
    legacy = build_prediction_record(
        {**prediction_payload(), "report": {**prediction_payload()["report"], "model_version": "v0.18.2"}},
        commit_sha="baseline-sha",
    )
    assert legacy["model_role"] == "legacy"
    assert legacy["formal_eligible"] is False


def test_promotion_requires_at_least_fifty_holdout_samples():
    result = evaluate_promotion({"sample_count": 49, "same_snapshot": True, "out_of_sample": True})
    assert result["eligible"] is False
    assert "minimum_holdout_samples" in result["reasons"]


def test_promotion_rejects_brier_score_without_improvement():
    result = evaluate_promotion({
        "sample_count": 50,
        "same_snapshot": True,
        "out_of_sample": True,
        "reproducible_inputs": True,
        "champion": {"brier_score": 0.20, "log_loss": 0.50},
        "challenger": {"brier_score": 0.20, "log_loss": 0.40},
        "market_baseline": {"brier_score": 0.22, "log_loss": 0.52},
        "simple_baseline": {"brier_score": 0.25, "log_loss": 0.60},
    })
    assert result["eligible"] is False
    assert "brier_not_improved" in result["reasons"]


def test_promotion_rejects_log_loss_deterioration():
    result = evaluate_promotion({
        "sample_count": 50,
        "same_snapshot": True,
        "out_of_sample": True,
        "reproducible_inputs": True,
        "champion": {"brier_score": 0.20, "log_loss": 0.50},
        "challenger": {"brier_score": 0.19, "log_loss": 0.60},
        "market_baseline": {"brier_score": 0.22, "log_loss": 0.52},
        "simple_baseline": {"brier_score": 0.25, "log_loss": 0.60},
    })
    assert result["eligible"] is False
    assert "log_loss_deteriorated" in result["reasons"]


def test_promotion_requires_same_snapshot_and_two_baselines():
    result = evaluate_promotion({
        "sample_count": 50,
        "same_snapshot": False,
        "out_of_sample": True,
        "reproducible_inputs": True,
        "champion": {"brier_score": 0.20, "log_loss": 0.50},
        "challenger": {"brier_score": 0.19, "log_loss": 0.49},
    })
    assert result["eligible"] is False
    assert "same_match_same_snapshot" in result["reasons"]
    assert "market_baseline_comparison_missing" in result["reasons"]
    assert "simple_baseline_comparison_missing" in result["reasons"]


def test_single_match_cannot_update_parameters():
    assert can_update_parameters(sample_count=1, match_count=1) is False
    assert can_update_parameters(sample_count=50, match_count=1) is False
    assert can_update_parameters(sample_count=50, match_count=50) is True


def test_roi_and_clv_are_null_without_real_executable_odds():
    record = build_prediction_record(prediction_payload(odds=None), commit_sha="baseline-sha")
    assert record["betting_reference_output"]["status"] == "not_evaluable"
    assert record["betting_reference_output"]["roi"] is None
    assert record["betting_reference_output"]["clv"] is None


def test_real_executable_odds_are_explicitly_marked():
    payload = prediction_payload(odds=2.1)
    payload["betting"]["candidates"][0]["price_executable"] = True
    record = build_prediction_record(payload, commit_sha="baseline-sha")
    assert record["betting_reference_output"]["status"] == "evaluable"


def test_file_hashes_detect_core_file_changes(tmp_path):
    path = tmp_path / "core.py"
    path.write_text("version = 1\n", encoding="utf-8")
    first = hash_files([path], root=tmp_path)
    path.write_text("version = 2\n", encoding="utf-8")
    second = hash_files([path], root=tmp_path)
    assert first["files"]["core.py"] != second["files"]["core.py"]


def test_fixed_fixture_math_snapshot_matches_pre_change_baseline():
    deep = {
        "shuju": {"recent_form": {
            "home_overall": {"matches": 10, "goals_for": 12, "goals_against": 13},
            "away_overall": {"matches": 10, "goals_for": 22, "goals_against": 9},
            "home_home": {"matches": 10, "goals_for": 19, "goals_against": 11},
            "away_away": {"matches": 10, "goals_for": 16, "goals_against": 13},
        }},
        "ouzhi": {"bookmakers": [
            {"spf_current": {"home": 4.5, "draw": 4.0, "away": 1.7}},
            {"spf_current": {"home": 4.2, "draw": 3.8, "away": 1.72}},
        ]},
        "daxiao": {"companies": [{"current_line": 2.75}, {"current_line": 2.5}]},
    }
    result = build_automatic_model({
        "request": {"match_id": "2040514"},
        "selected_workspace_match": {"id": "2040514", "home": "主队", "away": "客队"},
        "source_snapshots": {"500_deep": {"snapshots": [deep]}},
    })
    snapshot = {
        "probabilities": result["model"]["probabilities"],
        "lambda_home": result["model"]["lambda_home"],
        "lambda_away": result["model"]["lambda_away"],
        "score_probabilities": result["model"]["score_probabilities"],
        "unique_score": result["decisions"]["unique_score"],
        "primary_contract": result["decisions"]["primary_contract"],
        "dimension_predictions": result["model"]["dimension_predictions"],
    }
    digest = hashlib.sha256(json.dumps(
        snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()).hexdigest()
    assert digest == "b104c0f81c2a5c457967d9047b41e389209b99bd3cfc1613d9fb13fb0c2175df"


def test_current_metrics_do_not_mix_legacy_with_champion(tmp_path):
    reports = tmp_path / "reports"
    reviews = tmp_path / "reviews"
    reports.mkdir()
    reviews.mkdir()
    for index, version in enumerate((RELEASE_VERSION, "v0.18.2")):
        payload = prediction_payload()
        payload["report"]["model_version"] = version
        (reports / f"{index}.json").write_text(json.dumps(payload), encoding="utf-8")
    result = build_current_metrics(reports, reviews)
    assert result["scope"]["champion_frozen_predictions"] == 1
    assert result["scope"]["legacy_records_excluded"] == 1


def test_current_metrics_compute_formal_review_dimensions(tmp_path):
    reports = tmp_path / "reports"
    reviews = tmp_path / "reviews"
    reports.mkdir()
    reviews.mkdir()
    report = prediction_payload("A")
    (reports / "report.json").write_text(json.dumps(report), encoding="utf-8")
    review = {
        "model_version": RELEASE_VERSION,
        "model_family": MODEL_FAMILY,
        "data_grade": "A",
        "prediction_layer": {"formal_pick_eligible": True},
        "model_diagnostics": {"brier_score_1x2": 0.2, "log_loss_1x2": 0.4, "actual_score_rank": 1},
        "settlement": {
            "model_1x2": {"hit": True},
            "total_goals_mode": {"hit": False},
            "btts": {"hit": True},
        },
    }
    (reviews / "review.json").write_text(json.dumps(review), encoding="utf-8")
    result = build_current_metrics(reports, reviews)
    assert result["metrics"]["brier_score"] == 0.2
    assert result["metrics"]["log_loss"] == 0.4
    assert result["metrics"]["score_top1"] == 1.0
    assert result["metrics"]["win_draw_loss"]["hit_rate"] == 1.0
    assert result["metrics"]["over_under"]["hit_rate"] == 0.0
    assert result["metrics"]["btts"]["hit_rate"] == 1.0
    assert result["quality_distribution"] == {"A": 1, "B": 0, "C": 0, "D": 0}
