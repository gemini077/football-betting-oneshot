import hashlib
import json
import math
import subprocess
from pathlib import Path

import pytest

from scripts.prediction_sanity_audit import (
    classify_sample_tier,
    _REPLAY_CHILD,
    _commit_model_source_fingerprint,
    goal_error_metrics,
    matrix_map,
    outcome_conditioned_map,
    outcome_consistency,
    paired_method_metrics,
    replay_result_against_frozen,
    run_audit,
    scenario_score_from_record,
    score_margin,
    score_nll_for_record,
    select_score_methods,
    verified_result_from_ledger_entry,
)


def score_rows():
    return [
        {"score": "1-1", "probability": 0.11, "rank": 1},
        {"score": "1-0", "probability": 0.10, "rank": 2},
        {"score": "2-1", "probability": 0.08, "rank": 3},
        {"score": "0-1", "probability": 0.05, "rank": 4},
    ]


def test_matrix_map_reproduces_frozen_top_matrix_score():
    assert matrix_map(score_rows()) == "1-1"


def test_outcome_conditioned_home_does_not_select_draw_score():
    selected = outcome_conditioned_map(score_rows(), {"home": 0.55, "draw": 0.23, "away": 0.22})
    assert selected in {"1-0", "2-1"}
    assert selected != "1-1"


def test_outcome_conditioned_draw_only_selects_equal_score():
    selected = outcome_conditioned_map(score_rows(), {"home": 0.20, "draw": 0.50, "away": 0.30})
    assert selected == "1-1"


def test_outcome_conditioned_away_does_not_select_home_or_draw_score():
    selected = outcome_conditioned_map(score_rows(), {"home": 0.20, "draw": 0.30, "away": 0.50})
    assert selected == "0-1"


def test_scenario_reader_uses_frozen_trace_but_not_postmatch_fields():
    record = {
        "decisions": {"score_selection_trace": {"scenario_selected_score": "2-1"}},
        "postmatch": {"score_selection_trace": {"scenario_selected_score": "3-0"}},
    }
    assert scenario_score_from_record(record) == "2-1"
    assert scenario_score_from_record({"postmatch": {"scenario_selected_score": "3-0"}}) is None


def test_missing_trace_is_safely_unavailable():
    assert scenario_score_from_record({"unique_score": "1-1"}) is None


def test_pilot_and_legacy_are_not_formal_samples():
    assert classify_sample_tier({"prediction_id": "pilot", "formal_eligible": True}, {"pilot"}) == "PILOT_EXCLUDED"
    assert classify_sample_tier({"prediction_id": "legacy", "formal_eligible": False}, set()) == "RESEARCH_LEGACY"
    assert classify_sample_tier({"prediction_id": "formal", "formal_eligible": True}, set()) == "FORMAL_PROSPECTIVE"


def test_verified_result_requires_regulation_90m_scope():
    valid = {
        "actual": {"home_score": 2, "away_score": 1},
        "result_verified_at": "2026-08-15T10:00:00+08:00",
        "scope": "regulation_90m_plus_stoppage",
    }
    extra_time = {**valid, "scope": "after_extra_time"}
    assert verified_result_from_ledger_entry(valid) == "2-1"
    assert verified_result_from_ledger_entry(extra_time) is None


def test_score_margin_reports_top1_top2_and_top3_gaps():
    margin = score_margin(score_rows())
    assert margin["top1_probability"] == 0.11
    assert margin["top2_probability"] == 0.10
    assert margin["top1_top2_gap"] == 0.01
    assert margin["top1_top3_gap"] == 0.03


def test_outcome_consistency_is_not_score_accuracy():
    assert outcome_consistency("1-0", {"home": 0.55, "draw": 0.23, "away": 0.22}) is True
    assert outcome_consistency("1-1", {"home": 0.55, "draw": 0.23, "away": 0.22}) is False


def test_goal_error_metrics_are_derived_from_selected_score_and_actual():
    metrics = goal_error_metrics("2-0", {"home_score": 1, "away_score": 2})
    assert metrics == {"total_goal_absolute_error": 1.0, "goal_difference_absolute_error": 3.0}


def test_score_methods_do_not_use_postmatch_actual_to_choose_a_score():
    record = {"score_distribution": score_rows(), "probabilities": {"home": 0.55, "draw": 0.23, "away": 0.22}}
    before = select_score_methods(record)
    after = select_score_methods({**record, "postmatch": {"actual_score": "1-0"}})
    assert before == after


def test_run_audit_is_read_only_and_writes_only_requested_output(tmp_path):
    root = tmp_path / "project"
    prediction_dir = root / "data" / "model_governance" / "predictions"
    exclusion_dir = root / "data" / "model_governance" / "prediction_exclusions"
    prediction_dir.mkdir(parents=True)
    exclusion_dir.mkdir(parents=True)
    (root / "data" / "prospective").mkdir(parents=True)
    (root / "data" / "model_calibration").mkdir(parents=True)
    record = {
        "prediction_id": "p1",
        "business_date": "2026-08-15",
        "match_id": "m1",
        "home": "Home",
        "away": "Away",
        "unique_score": "1-1",
        "formal_eligible": True,
        "prediction_status": "formal",
        "score_distribution": score_rows(),
        "fusion_1X2": {"home": 0.55, "draw": 0.23, "away": 0.22},
        "lambda_home": 1.4,
        "lambda_away": 1.2,
        "rho": 0.0,
        "model_family": "test-model",
        "release_version": "test",
    }
    (prediction_dir / "p1.json").write_text(json.dumps(record), encoding="utf-8")
    (root / "data" / "prospective" / "ledger.jsonl").write_text("", encoding="utf-8")
    (root / "data" / "model_calibration" / "latest.json").write_text("{}", encoding="utf-8")
    before = hashlib.sha256((prediction_dir / "p1.json").read_bytes()).hexdigest()
    output = tmp_path / "output"
    result = run_audit(root, "2026-08-15", output)
    after = hashlib.sha256((prediction_dir / "p1.json").read_bytes()).hexdigest()
    assert before == after
    assert result["sample_definition"]["current_business_date"] == "2026-08-15"
    assert (output / "score_collapse_audit.json").exists()
    assert (output / "score_method_comparison.csv").exists()


def test_goal_and_outcome_methods_report_insufficient_dixon_coles_sample():
    record = {"score_distribution": score_rows(), "probabilities": {"home": 0.55, "draw": 0.23, "away": 0.22}}
    methods = select_score_methods(record, dixon_coles_available=False)
    assert methods["matrix_map"] == "1-1"
    assert methods["outcome_conditioned_map"] == "1-0"
    assert methods["dixon_coles_shadow"] is None


def test_score_nll_missing_frozen_actual_probability_is_unavailable_without_epsilon():
    record = {"score_distribution": [{"score": "1-1", "probability": 0.25, "rank": 1}]}
    result = score_nll_for_record(record, "2-0", {})
    assert result["status"] == "UNAVAILABLE"
    assert result["value"] is None
    assert result["reason"] == "MISSING_FROZEN_ACTUAL_SCORE_PROBABILITY"


def test_score_nll_reconstructs_from_explicit_frozen_probability():
    record = {"score_distribution": [{"score": "2-0", "probability": 0.25, "rank": 1}]}
    result = score_nll_for_record(record, "2-0", {})
    assert result["status"] == "AVAILABLE"
    assert result["source"] == "FROZEN_SCORE_DISTRIBUTION"
    assert result["value"] == pytest.approx(-math.log(0.25))


def test_score_nll_ledger_value_is_cross_checked_and_mismatch_is_reported():
    record = {"score_distribution": [{"score": "2-0", "probability": 0.25, "rank": 1}]}
    matching = score_nll_for_record(record, "2-0", {"actual_score_nll": -math.log(0.25), "actual_score_nll_status": None})
    mismatching = score_nll_for_record(record, "2-0", {"actual_score_nll": 9.0, "actual_score_nll_status": None})
    assert matching["status"] == "AVAILABLE"
    assert matching["reconstruction_match"] is True
    assert mismatching["status"] == "MISMATCH"
    assert mismatching["reason"] == "NLL_RECONSTRUCTION_MISMATCH"
    assert mismatching["value"] is None


def test_score_nll_unavailable_ledger_status_is_not_replaced_by_epsilon():
    record = {"score_distribution": [{"score": "1-1", "probability": 0.25, "rank": 1}]}
    result = score_nll_for_record(
        record,
        "2-0",
        {"actual_score_nll": None, "actual_score_nll_status": "UNAVAILABLE_IN_FROZEN_RECORD"},
    )
    assert result["status"] == "UNAVAILABLE"
    assert result["reason"] == "UNAVAILABLE_IN_FROZEN_RECORD"
    assert result["value"] is None


def _replay_record():
    return {
        "prediction_id": "p-replay",
        "match_id": "m-replay",
        "repository_commit_sha": "abc123",
        "model_source_fingerprint": "source-fp",
        "model_family": "test-model",
        "release_version": "v-test",
        "input_snapshot_ref": "data/model_governance/input_snapshots/frozen.json",
        "unique_score": "1-1",
        "score_distribution": [
            {"score": "1-1", "probability": 0.40, "rank": 1},
            {"score": "2-0", "probability": 0.30, "rank": 2},
            {"score": "0-1", "probability": 0.20, "rank": 3},
        ],
        "postmatch": {"actual_score": "9-9"},
    }


def _replay_result(*, scenario="2-0", top1="1-1"):
    rows = [
        {"score": top1, "probability": 0.40, "rank": 1},
        {"score": "2-0", "probability": 0.30, "rank": 2},
        {"score": "0-1", "probability": 0.20, "rank": 3},
    ]
    return {
        "model": {"method": "test-model", "score_probabilities": rows},
        "decisions": {"score_selection_trace": {"scenario_selected_score": scenario}},
    }


def test_replay_matrix_match_allows_freeze_time_scenario_challenger_without_using_actual_result():
    comparison = replay_result_against_frozen(_replay_record(), _replay_result())
    assert comparison["replay_status"] == "REPLAY_VALID"
    assert comparison["matrix_match"] is True
    assert comparison["frozen_matrix_map"] == "1-1"
    assert comparison["replayed_matrix_map"] == "1-1"
    assert comparison["scenario_challenger"] == "2-0"
    assert comparison["actual_score"] is None


def test_replay_matrix_mismatch_excludes_scenario_challenger():
    comparison = replay_result_against_frozen(_replay_record(), _replay_result(top1="3-0"))
    assert comparison["replay_status"] == "REPLAY_MISMATCH"
    assert comparison["matrix_match"] is False
    assert comparison["scenario_challenger"] is None


def test_replay_does_not_extend_official_frozen_candidate_pool():
    comparison = replay_result_against_frozen(_replay_record(), _replay_result(scenario="3-1"))
    assert comparison["replay_status"] == "REPLAY_VALID"
    assert comparison["scenario_challenger"] == "3-1"
    assert comparison["frozen_top3"] == ["1-1", "2-0", "0-1"]
    assert "3-1" not in comparison["frozen_top3"]


def test_paired_method_metrics_use_identical_replay_valid_sample():
    evaluated = [
        {"methods": {"matrix_map": "1-0", "scenario_challenger": "1-1"}, "actual_score": "1-0", "actual_outcome": "home", "stored_scores": ["1-0"]},
        {"methods": {"matrix_map": "1-1", "scenario_challenger": None}, "actual_score": "0-0", "actual_outcome": "draw", "stored_scores": ["1-1"]},
    ]
    result = paired_method_metrics(evaluated, "matrix_map", "scenario_challenger")
    assert result["paired_sample_count"] == 1
    assert result["matrix_map"]["available"] == 1
    assert result["scenario_challenger"]["available"] == 1


def test_replay_child_is_network_blocked_and_receives_only_frozen_projection():
    assert "network disabled for freeze-time audit replay" in _REPLAY_CHILD
    assert "request[\"projection\"]" in _REPLAY_CHILD
    assert "postmatch" not in _REPLAY_CHILD
    assert "actual_score" not in _REPLAY_CHILD


def test_replay_source_identity_is_derived_from_committed_git_blobs():
    root = Path(__file__).resolve().parents[1]
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    assert _commit_model_source_fingerprint(root, commit)
