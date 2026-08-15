from __future__ import annotations

from math import isclose, log

import pytest

from scripts.strength_challenger import (
    ChallengerSpec,
    assert_evaluation_ids_not_in_history,
    blend_one_x_two,
    build_opponent_adjusted_shadow,
    chronological_split,
    dataset_gate,
    market_only_from_record,
    prediction_record_target,
    summarise_prediction_rows,
    uniform_one_x_two,
)
from tests.phase2c2_test_support import paired_history, result, target


def test_dataset_gate_requires_result_identity_and_scores():
    report = dataset_gate(paired_history(count=2))
    assert report["eligible_count"] == 4
    assert report["excluded_count"] == 0

    bad = dict(paired_history(count=1)[0])
    bad["home_goals"] = None
    rejected = dataset_gate([bad])
    assert rejected["eligible_count"] == 0
    assert rejected["excluded_by_reason"]["missing_required_result"] == 1


def test_chronological_split_has_strict_non_overlapping_ranges():
    rows = [result(f"m-{i}", f"2025-01-{i + 1:02d}T12:00:00Z", "h", "a") for i in range(10)]
    split = chronological_split(rows, train_fraction=0.6, validation_fraction=0.2)
    assert [row["canonical_match_id"] for row in split["train"]] == [f"m-{i}" for i in range(6)]
    assert [row["canonical_match_id"] for row in split["validation"]] == ["m-6", "m-7"]
    assert [row["canonical_match_id"] for row in split["holdout"]] == ["m-8", "m-9"]
    assert split["train"][-1]["kickoff_at"] < split["validation"][0]["kickoff_at"]
    assert split["validation"][-1]["kickoff_at"] < split["holdout"][0]["kickoff_at"]


def test_opponent_adjusted_shadow_is_positive_coherent_and_excludes_future_rows():
    history = paired_history(count=8)
    future = result("future", "2026-04-01T12:00:00Z", "team:home", "team:late", 7, 0)
    prediction = build_opponent_adjusted_shadow(
        target(),
        history + [future],
        ChallengerSpec(regularization=10, minimum_history=3),
    )
    assert prediction["status"] == "AVAILABLE"
    assert prediction["lambda_home"] > 0
    assert prediction["lambda_away"] > 0
    assert isclose(sum(prediction["probabilities"]["1x2"].values()), 1.0, abs_tol=1e-12)
    assert "future" not in prediction["features"]["used_match_ids"]
    assert "target" not in prediction["features"]["used_match_ids"]


def test_competition_fallback_is_explicit_not_a_silent_second_schedule():
    history = paired_history(count=6)
    target_in_other_competition = dict(target())
    target_in_other_competition["competition_id"] = "competition:other"
    prediction = build_opponent_adjusted_shadow(
        target_in_other_competition,
        history,
        ChallengerSpec(regularization=10, minimum_history=3, competition_minimum_rows=100),
    )
    assert prediction["status"] == "AVAILABLE"
    assert prediction["features"]["history_scope"] == "global_fallback"


def test_market_only_and_fusion_are_separate_from_football_output():
    record = {"market_only_baseline": {"home": 0.6, "draw": 0.2, "away": 0.2}}
    market = market_only_from_record(record)
    assert market == {"home": 0.6, "draw": 0.2, "away": 0.2}
    football = {"home": 0.3, "draw": 0.3, "away": 0.4}
    fusion = blend_one_x_two(football, market, weight=0.5)
    assert fusion == {"home": 0.45, "draw": 0.25, "away": 0.3}
    assert fusion != football
    assert fusion != market


def test_uniform_baseline_is_exactly_one_third():
    assert uniform_one_x_two() == {"home": 1 / 3, "draw": 1 / 3, "away": 1 / 3}


def test_prediction_record_without_canonical_identity_is_not_fuzzy_resolved():
    target_info = prediction_record_target(
        {
            "match_id": "500-1",
            "match_identity": {"home": "Known-looking name", "away": "Other", "kickoff_at": "2026-08-15T12:00:00Z"},
        }
    )
    assert target_info["status"] == "IDENTITY_UNAVAILABLE"
    assert target_info["target"] is None


def test_formal_evaluation_ids_are_excluded_from_training_history():
    history = [result("h-1", "2025-01-01T12:00:00Z", "h", "a")]
    assert_evaluation_ids_not_in_history(history, {"formal-1"})
    with pytest.raises(ValueError, match="evaluation IDs must not be in training history"):
        assert_evaluation_ids_not_in_history(history + [result("formal-1", "2025-01-02T12:00:00Z", "h", "a")], {"formal-1"})


def test_metric_summary_reports_probability_goal_and_score_metrics():
    rows = [
        {
            "status": "AVAILABLE",
            "actual_score": "1-0",
            "actual_outcome": "home",
            "prediction": {
                "lambda_home": 1.2,
                "lambda_away": 0.8,
                "probabilities": {"1x2": {"home": 0.5, "draw": 0.25, "away": 0.25}},
                "top_scores": [{"score": "1-0", "probability": 0.2}],
            },
        }
    ]
    metrics = summarise_prediction_rows(rows)
    assert metrics["sample"] == 1
    assert metrics["one_x_two_brier"] is not None
    assert metrics["one_x_two_log_loss"] is not None
    assert metrics["home_goals_mae"] == 0.2
    assert metrics["away_goals_mae"] == 0.8
    assert metrics["exact_top1_accuracy"] == 1.0


def test_score_nll_is_unavailable_without_explicit_actual_probability():
    metrics = summarise_prediction_rows([
        {
            "status": "AVAILABLE",
            "actual_score": "2-2",
            "prediction": {
                "probabilities": {"1x2": {"home": 0.4, "draw": 0.3, "away": 0.3}},
                "top_scores": [{"score": "1-0", "probability": 0.2}],
            },
        }
    ])
    assert metrics["score_nll_available_count"] == 0
    assert metrics["score_nll_unavailable_count"] == 1
    assert metrics["mean_score_nll_available_only"] is None


def test_score_nll_uses_explicit_frozen_probability_without_epsilon_fabrication():
    metrics = summarise_prediction_rows([
        {
            "status": "AVAILABLE",
            "actual_score": "2-2",
            "prediction": {
                "probabilities": {"1x2": {"home": 0.4, "draw": 0.3, "away": 0.3}},
                "actual_score_probability": 0.25,
                "top_scores": [],
            },
        }
    ])
    assert metrics["score_nll_available_count"] == 1
    assert isclose(metrics["mean_score_nll_available_only"], -log(0.25), rel_tol=0, abs_tol=1e-12)


def test_valid_stored_nll_is_used_but_unavailable_status_is_not():
    available = summarise_prediction_rows([{"status": "AVAILABLE", "actual_score": "1-0", "prediction": {"probabilities": {"1x2": {"home": 0.6, "draw": 0.2, "away": 0.2}}, "actual_score_nll": 2.5}}])
    unavailable = summarise_prediction_rows([{"status": "AVAILABLE", "actual_score": "1-0", "prediction": {"probabilities": {"1x2": {"home": 0.6, "draw": 0.2, "away": 0.2}}, "actual_score_nll": 2.5, "actual_score_nll_status": "UNAVAILABLE_IN_FROZEN_RECORD"}}])
    assert available["mean_score_nll_available_only"] == 2.5
    assert unavailable["mean_score_nll_available_only"] is None
