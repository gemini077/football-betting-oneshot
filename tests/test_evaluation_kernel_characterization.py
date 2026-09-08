from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

from automatic_postmatch_review import _model_diagnostics  # noqa: E402
import automatic_postmatch_review as review_module  # noqa: E402
from baseline_settlement import calculate_metrics  # noqa: E402
from prospective_settlement import evaluate_prediction  # noqa: E402
from test_prospective_settlement import jc_record, record  # noqa: E402


def simple_prediction() -> dict:
    return {
        "model": "simple_poisson",
        "probabilities": {"home": 0.5, "draw": 0.3, "away": 0.2},
        "lambda_home": 1.5,
        "lambda_away": 0.8,
        "rho": 0.0,
        "derive_full_matrix": True,
    }


def test_current_benchmark_characterization_is_frozen():
    metrics = calculate_metrics(simple_prediction(), {"home_goals": 2, "away_goals": 1})

    assert metrics["actual_outcome"] == "home"
    assert metrics["brier_score_1x2"] == pytest.approx(0.38)
    assert metrics["log_loss_1x2"] == pytest.approx(-math.log(0.5))
    assert metrics["outcome_probabilities"] == {"home": 0.5, "draw": 0.3, "away": 0.2}
    assert metrics["actual_score_probability"] == pytest.approx(0.09023296005501762)
    assert metrics["actual_score_rank"] == 5
    assert metrics["score_top1"] is False
    assert metrics["score_top3"] is False
    assert metrics["score_top5"] is True
    assert metrics["score_top10"] is True
    assert metrics["actual_score_nll"] == pytest.approx(2.4053605078503217)
    assert metrics["total_goal_error"] == pytest.approx(0.7)
    assert metrics["total_goal_absolute_error"] == pytest.approx(0.7)
    assert metrics["expected_goal_error_home"] == pytest.approx(0.5)
    assert metrics["expected_goal_error_away"] == pytest.approx(0.2)
    assert metrics["lambda_sum"] == pytest.approx(2.3)
    assert metrics["lambda_gap"] == pytest.approx(0.7)


def test_current_production_review_matches_benchmark_common_metrics(monkeypatch):
    monkeypatch.setattr(review_module, "load_frozen_prediction", lambda *_args: {})
    review = _model_diagnostics(
        {"model": simple_prediction(), "model_governance": {"prediction_id": "missing"}},
        2,
        1,
    )
    benchmark = calculate_metrics(simple_prediction(), {"home_goals": 2, "away_goals": 1})

    assert review["actual_outcome_key"] == benchmark["actual_outcome"]
    assert review["actual_outcome_probability"] == pytest.approx(benchmark["outcome_probabilities"]["home"], abs=1e-6)
    assert review["brier_score_1x2"] == pytest.approx(benchmark["brier_score_1x2"], abs=1e-6)
    assert review["log_loss_1x2"] == pytest.approx(benchmark["log_loss_1x2"], abs=1e-6)
    assert review["actual_score_probability"] == pytest.approx(benchmark["actual_score_probability"], abs=1e-6)
    assert review["actual_score_rank"] == benchmark["actual_score_rank"]
    assert review["exact_score_authority_status"] == "RESEARCH_RECONSTRUCTED"
    assert review["lambda_home_residual"] == pytest.approx(0.5)
    assert review["lambda_away_residual"] == pytest.approx(0.2)
    assert review["total_goals_residual"] == pytest.approx(0.7)


def test_current_prospective_characterization_preserves_frozen_rows_and_result_identity():
    metrics = evaluate_prediction(record(), {"home_score": 2, "away_score": 1})

    assert metrics["actual_outcome"] == "HOME"
    assert metrics["brier_score_1x2"] == pytest.approx(0.38)
    assert metrics["log_loss_1x2"] == pytest.approx(-math.log(0.5))
    assert metrics["home_goal_absolute_error"] == pytest.approx(0.5)
    assert metrics["away_goal_absolute_error"] == pytest.approx(0.2)
    assert metrics["total_goal_absolute_error"] == pytest.approx(0.7)
    assert metrics["exact_score_top1"] is False
    assert metrics["exact_score_top3"] is False
    assert metrics["exact_score_top5"] is True
    assert metrics["exact_score_top10"] is None
    assert metrics["actual_score_probability"] == pytest.approx(0.1)
    assert metrics["actual_score_nll"] == pytest.approx(-math.log(0.1))
    assert metrics["actual_score_nll_status"] == "RESEARCH_RECONSTRUCTED_NO_FROZEN_AUTHORITY"
    assert metrics["exact_score_authority_status"] == "RESEARCH_RECONSTRUCTED"


def test_current_formal_exact_authority_label_is_preserved(monkeypatch):
    frozen = jc_record()
    monkeypatch.setattr(review_module, "load_frozen_prediction", lambda *_args: frozen)

    diagnostics = _model_diagnostics(
        {
            "model": {
                "probabilities": frozen["probabilities"],
                "lambda_home": frozen["lambda_home"],
                "lambda_away": frozen["lambda_away"],
                "rho": 0.0,
            },
            "model_governance": {"prediction_id": "JC-1"},
        },
        3,
        3,
    )

    assert diagnostics["FORMAL_EXACT_DISTRIBUTION_FROZEN"] is True
    assert diagnostics["FORMAL_EXACT_LOG_SCORE_ELIGIBLE"] is True
    assert diagnostics["exact_score_authority_status"] == "FROZEN_PREDICTION_TIME"
    assert diagnostics["actual_score_probability"] == pytest.approx(0.014286, abs=1e-6)
    assert diagnostics["actual_score_rank"] == 25


def test_canonical_owner_exposes_the_characterized_common_evaluation_surface():
    from evaluation_kernel import evaluate_prediction_common

    common = evaluate_prediction_common(
        simple_prediction(),
        {"home_goals": 2, "away_goals": 1},
        allow_research_reconstruction=True,
    )

    assert common["actual_outcome"] == "home"
    assert common["actual_outcome_probability"] == pytest.approx(0.5)
    assert common["brier_score_1x2"] == pytest.approx(0.38)
    assert common["log_loss_1x2"] == pytest.approx(-math.log(0.5))
    assert common["actual_score_probability"] == pytest.approx(0.09023296005501762)
    assert common["actual_score_rank"] == 5
    assert common["exact_score_authority_status"] == "RESEARCH_RECONSTRUCTED"
    assert common["lambda_home_residual"] == pytest.approx(0.5)
    assert common["lambda_away_residual"] == pytest.approx(0.2)
    assert common["total_goals_residual"] == pytest.approx(0.7)


def test_canonical_owner_preserves_formal_exact_authority_label():
    from evaluation_kernel import evaluate_prediction_common

    frozen = jc_record()
    common = evaluate_prediction_common(
        frozen,
        {"home_score": 3, "away_score": 3},
        frozen_record=frozen,
    )

    assert common["FORMAL_EXACT_DISTRIBUTION_FROZEN"] is True
    assert common["FORMAL_EXACT_LOG_SCORE_ELIGIBLE"] is True
    assert common["exact_score_authority_status"] == "FROZEN_PREDICTION_TIME"
    assert common["actual_score_probability"] == pytest.approx(0.014286, abs=1e-6)
    assert common["actual_score_rank"] == 25
