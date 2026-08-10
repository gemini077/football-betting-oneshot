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


def test_aggregate_uses_paired_cohorts_instead_of_independent_availability_means():
    match_a = snapshot("MATCH-A")
    match_b = snapshot("MATCH-B")
    match_b.pop("market")
    match_c = snapshot("MATCH-C")
    match_c["recent_form"] = {}
    rows = [
        settle_comparison(build_comparison(match_a, champion_record(match_a)), {"home_goals": 2, "away_goals": 1}),
        settle_comparison(build_comparison(match_b, champion_record(match_b)), {"home_goals": 1, "away_goals": 1}),
        settle_comparison(build_comparison(match_c, champion_record(match_c)), {"home_goals": 0, "away_goals": 1}),
    ]

    summary = aggregate_settlements(rows, cohort="primary")
    paired = summary["paired_3way_1x2"]
    model_paired = summary["paired_model_distribution"]

    assert summary["total_prospective_matches"] == 3
    assert paired["n"] == 1
    assert paired["match_keys"] == ["MATCH-A"]
    assert model_paired["availability"]["n"] == 2
    assert model_paired["availability"]["match_keys"] == ["MATCH-A", "MATCH-B"]
    assert paired["market_reference"]["brier"] is not None
    assert paired["simple_poisson"]["log_loss"] is not None
    assert paired["champion"]["top1"] is not None
    assert summary["availability"]["market_reference"]["evaluable"] == 2
    assert summary["availability"]["simple_poisson"]["evaluable"] == 2
    assert summary["availability"]["champion"]["evaluable"] == 3


def _distribution_settlement(
    match_key: str,
    result: tuple[int, int],
    *,
    champion_btts: bool = True,
):
    snap = snapshot(match_key)
    champion = champion_record(snap)
    if champion_btts:
        champion["prediction_output"]["btts"] = {"yes": 0.6, "no": 0.4}
    else:
        champion["prediction_output"].pop("btts", None)
    comparison = build_comparison(
        snap,
        champion,
        benchmark_scope="prospective",
        prospective_origin="production_new_freeze",
    )
    return settle_comparison(comparison, {"home_goals": result[0], "away_goals": result[1]})


def test_model_distribution_uses_a_metric_specific_paired_sample():
    rows = [
        _distribution_settlement("METRIC-A", (2, 1)),
        # The frozen Champion has only its stored score rows, so 9-9 is not a
        # supported full-distribution rank/probability observation.
        _distribution_settlement("METRIC-B", (9, 9)),
        # Champion BTTS is unavailable while its score/goal fields remain.
        _distribution_settlement("METRIC-C", (1, 1), champion_btts=False),
    ]

    distribution = aggregate_settlements(rows, cohort="primary")["paired_model_distribution"]
    metrics = distribution["metrics"]

    assert metrics["btts_accuracy"]["n"] == 2
    assert metrics["btts_accuracy"]["match_keys"] == ["METRIC-A", "METRIC-B"]
    assert metrics["score_top5"]["n"] == 3
    assert metrics["score_top5"]["match_keys"] == ["METRIC-A", "METRIC-B", "METRIC-C"]
    assert metrics["score_top10"]["n"] == 3
    assert metrics["total_goal_absolute_error"]["n"] == 3
    assert metrics["expected_goal_error"]["n"] == 3
    assert metrics["actual_score_rank"] == {
        "status": "unsupported_for_champion_full_distribution",
        "reason": "champion_frozen_distribution_is_top10_only",
        "n": 0,
        "match_keys": [],
        "simple_poisson": None,
        "champion": None,
    }
    assert metrics["actual_score_probability"]["status"] == "unsupported_until_full_champion_distribution_is_frozen"


def test_model_distribution_metric_values_use_the_same_match_keys():
    rows = [
        _distribution_settlement("KEY-A", (2, 1)),
        _distribution_settlement("KEY-B", (9, 9)),
    ]
    metrics = aggregate_settlements(rows, cohort="primary")["paired_model_distribution"]["metrics"]

    for metric_name in ("btts_accuracy", "total_goal_absolute_error", "expected_goal_error", "score_top1", "score_top3", "score_top5", "score_top10"):
        metric = metrics[metric_name]
        assert metric["n"] == len(metric["match_keys"])
        assert metric["simple_poisson"] is not None
        assert metric["champion"] is not None


def test_non_production_prospective_origin_is_excluded_from_formal_aggregate():
    snap = snapshot("MANUAL-PROSPECTIVE")
    comparison = build_comparison(
        snap,
        champion_record(snap),
        benchmark_scope="prospective",
        prospective_origin="manual_research",
    )
    settlement = settle_comparison(comparison, {"home_goals": 1, "away_goals": 0})

    summary = aggregate_settlements([settlement], cohort="primary")

    assert comparison["excluded_from_formal_metrics"] is True
    assert summary["formal_records"] == 0
    assert summary["paired_model_distribution"]["metrics"]["score_top5"]["n"] == 0


def test_aggregate_excludes_incomplete_mismatch_synthetic_historical_and_secondary_from_formal():
    complete = settle_comparison(
        build_comparison(snapshot("COMPLETE"), champion_record(snapshot("COMPLETE"))),
        {"home_goals": 2, "away_goals": 1},
    )
    incomplete = settle_comparison(
        build_comparison(snapshot("INCOMPLETE"), None),
        {"home_goals": 1, "away_goals": 0},
    )
    mismatch_snapshot = snapshot("MISMATCH")
    mismatch_champion = champion_record(mismatch_snapshot)
    mismatch_champion["snapshot_id"] = "OTHER-SNAPSHOT"
    mismatch = settle_comparison(
        build_comparison(mismatch_snapshot, mismatch_champion),
        {"home_goals": 0, "away_goals": 0},
    )
    historical_snapshot = snapshot("HISTORICAL")
    historical_snapshot["historical"] = True
    historical = settle_comparison(
        build_comparison(historical_snapshot, champion_record(historical_snapshot)),
        {"home_goals": 0, "away_goals": 1},
    )
    secondary_snapshot = snapshot("SECONDARY", stage="T-2H")
    secondary = settle_comparison(
        build_comparison(secondary_snapshot, champion_record(secondary_snapshot)),
        {"home_goals": 1, "away_goals": 1},
    )
    synthetic = copy.deepcopy(complete)
    synthetic["match_key"] = "SYNTHETIC"
    synthetic["synthetic"] = True
    synthetic["excluded_from_formal_metrics"] = True

    summary = aggregate_settlements([secondary, synthetic, mismatch, historical, incomplete, complete], cohort="primary")

    assert summary["formal_records"] == 1
    assert summary["paired_3way_1x2"]["n"] == 1
    assert summary["paired_3way_1x2"]["match_keys"] == ["COMPLETE"]
    assert summary["incomplete_comparison_count"] == 1
    assert summary["snapshot_mismatch_count"] == 1
    assert summary["excluded_records"] == 5


def test_duplicate_primary_is_order_independent_and_excluded_conservatively():
    first_snapshot = snapshot("DUPLICATE")
    second_snapshot = snapshot("DUPLICATE")
    second_snapshot["snapshot_id"] = "SNAPSHOT-DUPLICATE-OTHER"
    first = settle_comparison(
        build_comparison(first_snapshot, champion_record(first_snapshot)),
        {"home_goals": 2, "away_goals": 1},
    )
    second = settle_comparison(
        build_comparison(second_snapshot, champion_record(second_snapshot)),
        {"home_goals": 1, "away_goals": 0},
    )

    forward = aggregate_settlements([first, second], cohort="primary")
    reverse = aggregate_settlements([second, first], cohort="primary")

    assert forward["paired_3way_1x2"]["n"] == 0
    assert forward["duplicate_primary_conflicts"] == ["DUPLICATE"]
    assert reverse["duplicate_primary_conflicts"] == ["DUPLICATE"]
    assert forward["paired_3way_1x2"] == reverse["paired_3way_1x2"]
