from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))

from football_data.first_challenger_pre_screen import (
    NOT_QUALIFIED,
    QUALIFIED_FOR_PROSPECTIVE_SHADOW,
    evaluate_challenger_prescreen,
    prescreen_phase2c1_summary,
)


def _record(
    match_key: str,
    *,
    score: tuple[int, int],
    probabilities: dict[str, float],
    lambdas: tuple[float, float],
    top1: str,
) -> dict[str, object]:
    return {
        "match_key": match_key,
        "actual_home_goals": score[0],
        "actual_away_goals": score[1],
        "probabilities": probabilities,
        "lambda_home": lambdas[0],
        "lambda_away": lambdas[1],
        "score_top3": [top1, "1-1", "0-0"],
    }


def _same_sample() -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    outcomes = [(2, 0), (1, 1), (0, 1), (1, 0)]
    baseline_probabilities = [
        {"home": 0.50, "draw": 0.30, "away": 0.20},
        {"home": 0.25, "draw": 0.50, "away": 0.25},
        {"home": 0.20, "draw": 0.30, "away": 0.50},
        {"home": 0.45, "draw": 0.30, "away": 0.25},
    ]
    challenger_probabilities = [
        {"home": 0.60, "draw": 0.25, "away": 0.15},
        {"home": 0.20, "draw": 0.60, "away": 0.20},
        {"home": 0.15, "draw": 0.25, "away": 0.60},
        {"home": 0.55, "draw": 0.25, "away": 0.20},
    ]
    baseline_top1 = ["1-1", "1-1", "0-1", "1-0"]
    challenger_top1 = ["2-0", "1-0", "0-1", "2-0"]
    baseline_lambdas = [(1.1, 0.9), (1.0, 0.9), (0.7, 1.5), (1.4, 0.8)]
    challenger_lambdas = [(1.4, 0.5), (1.3, 0.5), (0.6, 1.5), (1.5, 0.7)]
    baseline = [
        _record(f"M-{index}", score=score, probabilities=baseline_probabilities[index], lambdas=baseline_lambdas[index], top1=baseline_top1[index])
        for index, score in enumerate(outcomes)
    ]
    challenger = [
        _record(f"M-{index}", score=score, probabilities=challenger_probabilities[index], lambdas=challenger_lambdas[index], top1=challenger_top1[index])
        for index, score in enumerate(outcomes)
    ]
    return baseline, challenger


def test_valid_same_sample_can_qualify_only_with_probability_guardrails_and_structure_gain():
    baseline, challenger = _same_sample()

    result = evaluate_challenger_prescreen(baseline, challenger)

    assert result["status"] == QUALIFIED_FOR_PROSPECTIVE_SHADOW
    assert result["paired_sample_count"] == 4
    assert result["metric_deltas"]["brier"] < 0
    assert result["metric_deltas"]["log_loss"] < 0
    assert result["structure"]["one_to_one_top1_share"]["baseline"] == pytest.approx(0.5)
    assert result["structure"]["one_to_one_top1_share"]["challenger"] == pytest.approx(0.0)
    assert result["structure"]["lambda_gap_below_0_5_share"]["baseline"] == pytest.approx(0.5)
    assert result["structure"]["lambda_gap_below_0_5_share"]["challenger"] == pytest.approx(0.0)
    assert result["metrics"]["challenger"]["exact_score_top1"]["available"] is True


def test_fewer_one_to_one_predictions_but_worse_brier_or_log_loss_must_fail():
    baseline, challenger = _same_sample()
    challenger[0]["probabilities"] = {"home": 0.05, "draw": 0.10, "away": 0.85}

    result = evaluate_challenger_prescreen(baseline, challenger)

    assert result["status"] == NOT_QUALIFIED
    assert result["structure"]["one_to_one_top1_share"]["improved"] is True
    assert result["metric_deltas"]["brier"] > 0
    assert "ONE_X_TWO_BRIER_REGRESSION" in result["blocking_reasons"]
    assert "ONE_X_TWO_LOG_LOSS_REGRESSION" in result["blocking_reasons"]


def test_lambda_separation_gain_does_not_offset_log_loss_regression():
    baseline, challenger = _same_sample()
    challenger[1]["probabilities"] = {"home": 0.80, "draw": 0.10, "away": 0.10}

    result = evaluate_challenger_prescreen(baseline, challenger)

    assert result["structure"]["lambda_gap_below_0_5_share"]["improved"] is True
    assert result["status"] == NOT_QUALIFIED
    assert "ONE_X_TWO_LOG_LOSS_REGRESSION" in result["blocking_reasons"]


def test_unpaired_and_zero_evidence_fail_closed():
    baseline, challenger = _same_sample()
    unpaired = evaluate_challenger_prescreen(baseline, challenger[:-1])
    empty = evaluate_challenger_prescreen([], [])

    assert unpaired["status"] == NOT_QUALIFIED
    assert "UNPAIRED_OR_MISMATCHED_SAMPLE" in unpaired["blocking_reasons"]
    assert empty["status"] == NOT_QUALIFIED
    assert "HISTORICAL_STRUCTURE_EVIDENCE_MISSING" in empty["blocking_reasons"]
    assert empty["paired_sample_count"] == 0


def test_phase2c1_summary_is_real_evidence_but_not_qualified_without_per_match_structure():
    summary_path = Path(__file__).parents[1] / "data" / "football_data" / "phase2c1_results_summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))

    result = prescreen_phase2c1_summary(summary)

    assert result["status"] == NOT_QUALIFIED
    assert result["paired_sample_count"] == 144
    assert result["metric_deltas"]["brier"] == pytest.approx(-0.014022318503427611)
    assert result["metric_deltas"]["log_loss"] == pytest.approx(-0.018700001041710657)
    assert result["metrics"]["challenger"]["exact_score_top1"]["share"] == pytest.approx(0.125)
    assert result["structure"]["one_to_one_top1_share"]["available"] is False
    assert "HISTORICAL_STRUCTURE_EVIDENCE_MISSING" in result["blocking_reasons"]
