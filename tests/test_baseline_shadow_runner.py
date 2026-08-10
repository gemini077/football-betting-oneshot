import copy
import hashlib
import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from baseline_shadow_runner import (  # noqa: E402
    BENCHMARK_CONTRACT_VERSION,
    BenchmarkConflictError,
    build_comparison,
    comparison_id_for,
    freeze_comparison,
    primary_benchmark_eligibility,
)


def snapshot(stage="T-30M"):
    return {
        "match_key": "SYNTH-HOME-vs-AWAY",
        "snapshot_id": "SNAPSHOT-SYNTH-001",
        "canonical_model_input_sha256": "input-sha-synth-001",
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


def champion_record(snap=None):
    snap = snap or snapshot()
    return {
        "prediction_id": "CHAMPION-SYNTH-001",
        "prediction_sha256": "prediction-sha-synth-001",
        "model_run_fingerprint": "run-fingerprint-synth-001",
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
        "prediction_output": {
            "score_matrix": [
                {"score": "1-0", "probability": 0.30},
                {"score": "1-1", "probability": 0.20},
                {"score": "2-0", "probability": 0.15},
                {"score": "2-1", "probability": 0.10},
            ],
        },
    }


def test_comparison_records_one_same_snapshot_and_stable_id_for_all_predictors():
    snap = snapshot()
    comparison = build_comparison(snap, champion_record(snap), benchmark_scope="prospective")

    assert comparison["comparison_status"] == "complete"
    assert comparison["benchmark_contract_version"] == BENCHMARK_CONTRACT_VERSION
    assert comparison["comparison_id"] == comparison_id_for(
        snap["match_key"], snap["snapshot_id"], BENCHMARK_CONTRACT_VERSION
    )
    for predictor in comparison["predictors"].values():
        assert {key: predictor[key] for key in (
            "match_key", "snapshot_id", "canonical_model_input_sha256",
            "source_cutoff_at", "market_snapshot_at", "checkpoint_stage",
        )} == {key: snap[key] for key in (
            "match_key", "snapshot_id", "canonical_model_input_sha256",
            "source_cutoff_at", "market_snapshot_at", "checkpoint_stage",
        )}


def test_snapshot_mismatch_is_rejected_and_not_compared():
    snap = snapshot()
    champion = champion_record(snap)
    champion["snapshot_id"] = "SNAPSHOT-OTHER"

    result = build_comparison(snap, champion, benchmark_scope="prospective")

    assert result["comparison_status"] == "invalid_snapshot_mismatch"
    assert result["same_snapshot"] is False


def test_missing_formal_frozen_champion_is_incomplete_without_backfill():
    result = build_comparison(snapshot(), None, benchmark_scope="prospective")

    assert result["comparison_status"] == "incomplete"
    assert result["predictors"]["champion"] is None
    assert result["champion_reference"] is None


def test_runner_uses_frozen_champion_record_without_rerunning_champion(monkeypatch):
    import automatic_model_core

    monkeypatch.setattr(
        automatic_model_core,
        "build_automatic_model",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("Champion rerun")),
    )

    result = build_comparison(snapshot(), champion_record(), benchmark_scope="prospective")

    assert result["comparison_status"] == "complete"
    assert result["champion_reference"]["prediction_id"] == "CHAMPION-SYNTH-001"


def test_t30m_is_primary_only_with_real_snapshot_timestamps():
    assert primary_benchmark_eligibility(snapshot()) == {
        "primary_benchmark_eligible": True,
        "cohort": "primary",
        "reason": None,
    }
    missing_time = snapshot()
    missing_time["market_snapshot_at"] = None
    assert primary_benchmark_eligibility(missing_time)["primary_benchmark_eligible"] is False
    assert primary_benchmark_eligibility(snapshot("T-2H"))["cohort"] == "secondary"


def test_historical_scope_is_explicitly_excluded_from_formal_benchmark():
    result = build_comparison(snapshot(), champion_record(), benchmark_scope="historical_exploratory")

    assert result["comparison_status"] == "historical_exploratory"
    assert result["excluded_from_formal_metrics"] is True


def test_historical_snapshot_marker_cannot_be_registered_as_prospective():
    snap = snapshot()
    snap["historical"] = True

    result = build_comparison(snap, champion_record(snap), benchmark_scope="prospective")

    assert result["comparison_status"] == "historical_exploratory"
    assert result["benchmark_scope"] == "historical_exploratory"


def test_snapshot_mismatch_remains_invalid_even_for_historical_scope():
    snap = snapshot()
    champion = champion_record(snap)
    champion["snapshot_id"] = "SNAPSHOT-OTHER"

    result = build_comparison(snap, champion, benchmark_scope="historical_exploratory")

    assert result["comparison_status"] == "invalid_snapshot_mismatch"


def test_prediction_freeze_is_idempotent_and_conflicts_are_rejected(tmp_path):
    comparison = build_comparison(snapshot(), champion_record(), benchmark_scope="prospective")
    first = freeze_comparison(comparison, tmp_path)
    second = freeze_comparison(copy.deepcopy(comparison), tmp_path)

    assert first["status"] == "created"
    assert second["status"] == "existing"
    changed = copy.deepcopy(comparison)
    changed["predictors"]["simple_poisson"]["lambda_home"] += 0.01
    with pytest.raises(BenchmarkConflictError):
        freeze_comparison(changed, tmp_path)
    polluted = copy.deepcopy(comparison)
    polluted["actual_result"] = {"home_goals": 2, "away_goals": 1}
    with pytest.raises(ValueError, match="postmatch fields"):
        freeze_comparison(polluted, tmp_path)
    assert (tmp_path / f"{comparison['comparison_id']}.json").is_file()
