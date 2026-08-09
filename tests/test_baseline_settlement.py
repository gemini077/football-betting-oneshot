import copy
import math
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from baseline_settlement import (  # noqa: E402
    BenchmarkConflictError,
    aggregate_settlements,
    calculate_metrics,
    freeze_settlement,
    settle_comparison,
)
from baseline_shadow_runner import build_comparison, freeze_comparison  # noqa: E402


def snapshot(match_key="SYNTH-HOME-vs-AWAY", stage="T-30M"):
    return {
        "match_key": match_key,
        "snapshot_id": f"SNAPSHOT-{match_key}",
        "canonical_model_input_sha256": f"input-{match_key}",
        "source_cutoff_at": "2026-08-10T19:30:00+08:00",
        "market_snapshot_at": "2026-08-10T19:31:00+08:00",
        "checkpoint_stage": stage,
        "checkpoint_status": "captured",
        "recent_form": {
            "home_home": {"matches": 10, "goals_for": 20, "goals_against": 8},
            "away_away": {"matches": 10, "goals_for": 15, "goals_against": 10},
            "home_overall": {"matches": 10, "goals_for": 12, "goals_against": 13},
            "away_overall": {"matches": 10, "goals_for": 10, "goals_against": 9},
        },
        "market": {"1x2": [
            {"bookmaker": "A", "home_odds": 2.5, "draw_odds": 3.5, "away_odds": 3.8},
            {"bookmaker": "B", "home_odds": 2.2, "draw_odds": 3.8, "away_odds": 4.2},
        ]},
    }


def champion_record(snap):
    return {
        "prediction_id": f"CHAMPION-{snap['match_key']}",
        "prediction_sha256": "prediction-sha",
        "model_run_fingerprint": "run-fingerprint",
        "canonical_model_input_sha256": snap["canonical_model_input_sha256"],
        "match_key": snap["match_key"],
        "snapshot_id": snap["snapshot_id"],
        "source_cutoff_at": snap["source_cutoff_at"],
        "market_snapshot_at": snap["market_snapshot_at"],
        "checkpoint_stage": snap["checkpoint_stage"],
        "model_role": "champion",
        "model_formal_eligible": True,
        "prediction_variant": "model_only",
        "prediction_status": "formal",
        "probabilities": {"home": 0.50, "draw": 0.25, "away": 0.25},
        "lambda_home": 1.30,
        "lambda_away": 1.00,
        "rho": 0.0,
        "prediction_output": {"score_matrix": [
            {"score": "1-0", "probability": 0.30},
            {"score": "1-1", "probability": 0.20},
            {"score": "2-0", "probability": 0.15},
            {"score": "2-1", "probability": 0.10},
        ]},
    }


def test_settlement_calculates_common_and_model_specific_metrics():
    snap = snapshot()
    comparison = build_comparison(snap, champion_record(snap), benchmark_scope="prospective")
    settlement = settle_comparison(
        comparison,
        {"home_goals": 2, "away_goals": 1, "regulation_minutes": 90, "synthetic": True},
    )

    assert settlement["synthetic"] is True
    assert settlement["excluded_from_formal_metrics"] is True
    assert set(settlement["metrics"]) == {"market_reference", "simple_poisson", "champion"}
    for metrics in settlement["metrics"].values():
        assert metrics["brier_score_1x2"] is not None
        assert metrics["log_loss_1x2"] is not None
        assert metrics["top1_accuracy_1x2"] in {0, 1}
        assert metrics["roi"] is None
        assert metrics["clv"] is None

    simple = settlement["metrics"]["simple_poisson"]
    assert simple["btts_hit"] in {True, False}
    assert simple["total_goal_error"] is not None
    assert simple["expected_goal_error"] is not None
    assert simple["score_top1"] in {True, False}
    assert simple["score_top3"] in {True, False}
    assert simple["score_top5"] in {True, False}
    assert simple["actual_score_rank"] is not None
    assert simple["actual_score_probability"] is not None


def test_market_has_no_fabricated_score_or_model_metrics():
    prediction = {
        "model": "market_reference",
        "probabilities": {"home": 0.5, "draw": 0.25, "away": 0.25},
        "market_bookmaker_count": 2,
    }
    metrics = calculate_metrics(prediction, {"home_goals": 1, "away_goals": 1})

    assert metrics["brier_score_1x2"] is not None
    assert metrics["log_loss_1x2"] is not None
    for key in (
        "btts_hit", "total_goal_error", "expected_goal_error",
        "score_top1", "score_top3", "score_top5",
        "actual_score_rank", "actual_score_probability",
    ):
        assert metrics[key] is None
    assert metrics["roi"] is None
    assert metrics["clv"] is None


def test_metric_formulas_cover_brier_log_loss_and_top1():
    metrics = calculate_metrics(
        {"model": "simple_poisson", "probabilities": {"home": 0.6, "draw": 0.2, "away": 0.2}},
        {"home_goals": 2, "away_goals": 0},
    )

    assert metrics["brier_score_1x2"] == pytest.approx((0.6 - 1) ** 2 + 0.2**2 + 0.2**2)
    assert metrics["log_loss_1x2"] == pytest.approx(-math.log(0.6))
    assert metrics["top1_accuracy_1x2"] == 1


def test_settlement_is_separate_and_immutable(tmp_path):
    snap = snapshot()
    comparison = build_comparison(snap, champion_record(snap), benchmark_scope="prospective")
    freeze_comparison(comparison, tmp_path / "predictions")
    settlement = settle_comparison(comparison, {"home_goals": 2, "away_goals": 1})

    first = freeze_settlement(settlement, tmp_path / "settlements")
    second = freeze_settlement(copy.deepcopy(settlement), tmp_path / "settlements")
    assert first["status"] == "created"
    assert second["status"] == "existing"
    changed = copy.deepcopy(settlement)
    changed["actual_result"]["home_goals"] = 3
    with pytest.raises(BenchmarkConflictError):
        freeze_settlement(changed, tmp_path / "settlements")
    assert (tmp_path / "predictions" / f"{comparison['comparison_id']}.json").is_file()
    assert (tmp_path / "settlements" / f"{comparison['comparison_id']}.json").is_file()


def test_aggregate_excludes_synthetic_and_deduplicates_same_match():
    first = settle_comparison(
        build_comparison(snapshot(), champion_record(snapshot()), benchmark_scope="prospective"),
        {"home_goals": 2, "away_goals": 1},
    )
    duplicate = settle_comparison(
        build_comparison(snapshot(stage="T-2H"), champion_record(snapshot(stage="T-2H")), benchmark_scope="prospective"),
        {"home_goals": 0, "away_goals": 0},
    )
    synthetic = copy.deepcopy(first)
    synthetic["synthetic"] = True
    synthetic["excluded_from_formal_metrics"] = True

    summary = aggregate_settlements([first, duplicate, synthetic])

    assert summary["records_seen"] == 3
    assert summary["formal_records"] == 2
    assert summary["unique_match_count"] == 1
    assert summary["duplicate_checkpoint_records_excluded"] == 1
    assert summary["metrics"]["simple_poisson"]["score_top3"] is not None
