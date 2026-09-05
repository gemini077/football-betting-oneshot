from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

from automatic_model_core import build_automatic_model  # noqa: E402
from automatic_postmatch_review import _model_diagnostics  # noqa: E402
from exact_distribution import (  # noqa: E402
    EXACT_DISTRIBUTION_CELL_COUNT,
    EXACT_DISTRIBUTION_CONTRACT_VERSION,
    build_exact_distribution_contract,
    classify_frozen_exact_score,
    distribution_content_sha256,
    validate_exact_distribution_contract,
)
from model_governance import (  # noqa: E402
    build_prediction_record,
    freeze_prediction,
    load_frozen_prediction,
    prediction_content_hash,
)
from prospective_settlement import evaluate_prediction  # noqa: E402
from risk_engine import dixon_coles_score_matrix  # noqa: E402
from test_model_governance import prediction_payload  # noqa: E402
import automatic_postmatch_review as review_module  # noqa: E402
import exact_distribution_freeze_readiness_audit as readiness_audit  # noqa: E402


FIXTURE = ROOT / "tests" / "fixtures" / "exact_distribution" / "current_model_input.json"


def model_context() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def core_result(*, include_exact_distribution: bool = True) -> dict:
    return build_automatic_model(
        model_context(),
        include_exact_distribution=include_exact_distribution,
    )


def formal_record():
    result = core_result()
    payload = prediction_payload()
    payload["model"] = {
        **payload["model"],
        **deepcopy(result["model"]),
    }
    payload["decisions"] = {
        **payload["decisions"],
        **deepcopy(result["decisions"]),
    }
    return build_prediction_record(
        payload,
        commit_sha="exact-distribution-test-sha",
        exact_distribution_state=result["exact_distribution_state"],
        require_exact_distribution=True,
    )


def test_capture_is_the_effective_matrix_and_does_not_change_model_outputs():
    before = core_result(include_exact_distribution=False)
    after = core_result(include_exact_distribution=True)

    assert before["model"] == after["model"]
    assert before["decisions"] == after["decisions"]
    assert before["price_audit"] == after["price_audit"]
    assert before["live_ev_profiles"] == after["live_ev_profiles"]

    state = after["exact_distribution_state"]
    assert len(state["effective_matrix"]) == EXACT_DISTRIBUTION_CELL_COUNT
    parameters = state["probability_state"]
    effective = {
        (cell["home_goals"], cell["away_goals"]): cell["probability"]
        for cell in state["effective_matrix"]
    }
    direct = dixon_coles_score_matrix(parameters)
    assert effective.keys() == direct.keys()
    for score, probability in direct.items():
        assert effective[score] == pytest.approx(probability, abs=1e-15)


def test_approved_transformations_are_recorded_after_their_application():
    context = model_context()
    context["model_calibration"] = {
        "active": True,
        "model_family": "recent_form_market_calibrated_poisson_v2",
        "policy": {"strength": 0.3},
        "direction": {"approved": True, "logit_offsets": {"home": 0.1, "draw": -0.1, "away": 0.2}},
        "total_goals": {"approved": True, "lambda_shift": 0.2},
        "dispersion": {"approved": True, "tail_mixture_weight": 0.1},
    }
    result = build_automatic_model(context, include_exact_distribution=True)
    state = result["exact_distribution_state"]
    assert state["production_path"]["effective_stage"] == "after_approved_calibration_before_top_score_rows"
    assert state["production_path"]["calibration"] == {
        "compatible": True,
        "strength": 0.3,
        "total_goals_applied": True,
        "dispersion_applied": True,
        "direction_applied": True,
    }
    assert sum(cell["probability"] for cell in state["effective_matrix"]) == pytest.approx(1.0)


def test_contract_is_deterministic_finite_and_hashed():
    result = core_result()
    identity = {
        "prediction_id": "probe",
        "model_role": "champion",
        "model_family": "recent_form_market_calibrated_poisson_v2",
        "model_core_version": "recent_form_market_calibrated_poisson_v2",
        "release_version": "v0.19.0",
        "model_source_fingerprint": "source",
        "model_run_fingerprint": "run",
        "input_sha256": "input",
    }
    first = build_exact_distribution_contract(result["exact_distribution_state"], model_identity=identity)
    second = build_exact_distribution_contract(result["exact_distribution_state"], model_identity=identity)

    assert first == second
    assert first["contract_version"] == EXACT_DISTRIBUTION_CONTRACT_VERSION
    assert first["score_space"]["representation"] == "FINITE_NORMALIZED_GRID"
    assert first["score_space"]["full_support"] is False
    assert first["score_space"]["max_home_goals"] == 12
    assert first["score_space"]["max_away_goals"] == 12
    assert len(first["cells"]) == 169
    assert first["tail_diagnostic"]["status"] == "UNRESOLVED_NOT_REPRESENTED"
    assert first["tail_diagnostic"]["omitted_probability_mass"] is None
    assert first["content_sha256"] == distribution_content_sha256(
        {key: value for key, value in first.items() if key != "content_sha256"}
    )
    validate_exact_distribution_contract(first, expected_model_identity=identity)


def test_formal_record_freezes_contract_and_evaluator_uses_it_only(tmp_path, monkeypatch):
    record = formal_record()
    original_contract = deepcopy(record["exact_score_distribution"])
    frozen = freeze_prediction(
        record,
        tmp_path / "predictions",
        input_snapshot_root=tmp_path / "input_snapshots",
    )
    loaded = load_frozen_prediction(record["prediction_id"], tmp_path / "predictions")
    assert frozen["status"] == "created"
    assert loaded["exact_score_distribution"] == original_contract

    # The formal review path reads the frozen matrix and never replays the
    # current risk-engine configuration for a record with frozen authority.
    report = {
        "model": {
            "probabilities": record["probabilities"],
            "lambda_home": record["lambda_home"],
            "lambda_away": record["lambda_away"],
            "rho": record["rho"],
            "calibration": {},
        },
        "model_governance": {"prediction_id": record["prediction_id"]},
    }
    monkeypatch.setattr(review_module, "DEFAULT_RECORD_ROOT", tmp_path / "predictions")
    monkeypatch.setattr(
        review_module,
        "dixon_coles_score_matrix",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("formal review replayed current code")),
    )
    diagnostics = _model_diagnostics(report, 1, 0)
    expected = classify_frozen_exact_score(record, 1, 0)
    assert diagnostics["FORMAL_EXACT_DISTRIBUTION_FROZEN"] is True
    assert diagnostics["FORMAL_EXACT_LOG_SCORE_ELIGIBLE"] is True
    assert diagnostics["actual_score_probability"] == pytest.approx(expected["probability"], abs=1e-6)
    assert diagnostics["actual_score_rank"] == expected["rank"]

    metrics = evaluate_prediction(record, {"home_score": 1, "away_score": 0})
    assert metrics["FORMAL_EXACT_DISTRIBUTION_FROZEN"] is True
    assert metrics["FINITE_GRID_EXACTLY_REPRESENTED"] is True
    assert metrics["FORMAL_EXACT_LOG_SCORE_ELIGIBLE"] is True
    assert metrics["actual_score_probability"] == pytest.approx(expected["probability"])
    assert metrics["actual_score_nll"] == pytest.approx(expected["log_score"])
    assert record["prediction_sha256"] == prediction_content_hash(record)

    # Changing a later/current object cannot change the inline frozen record.
    record["exact_score_distribution"]["probability_state"]["lambda_home"] = 99.0
    assert loaded["exact_score_distribution"] == original_contract


def test_out_of_grid_is_fail_closed_and_not_an_invented_tail_probability():
    record = formal_record()
    classification = classify_frozen_exact_score(record, 13, 0)
    assert classification["FORMAL_EXACT_DISTRIBUTION_FROZEN"] is True
    assert classification["FINITE_GRID_EXACTLY_REPRESENTED"] is False
    assert classification["OUT_OF_EXPLICIT_SUPPORT"] is True
    assert classification["FORMAL_EXACT_LOG_SCORE_ELIGIBLE"] is False
    assert classification["probability"] is None

    metrics = evaluate_prediction(record, {"home_score": 13, "away_score": 0})
    assert metrics["OUT_OF_EXPLICIT_SUPPORT"] is True
    assert metrics["FORMAL_EXACT_LOG_SCORE_ELIGIBLE"] is False
    assert metrics["actual_score_probability"] is None
    assert metrics["actual_score_nll"] is None
    assert metrics["actual_score_nll_status"] == "OUT_OF_EXPLICIT_SUPPORT"


def test_old_record_is_readable_but_has_no_formal_exact_authority():
    old = prediction_payload()
    record = build_prediction_record(old, commit_sha="legacy-test-sha")
    assert "exact_score_distribution" not in record
    classification = classify_frozen_exact_score(record, 1, 0)
    assert classification["FORMAL_EXACT_DISTRIBUTION_FROZEN"] is False
    assert classification["FORMAL_EXACT_LOG_SCORE_ELIGIBLE"] is False
    assert classification["authority_status"] == "RESEARCH_RECONSTRUCTED"


def test_required_new_formal_freeze_fails_closed_without_captured_state():
    with pytest.raises(ValueError, match="prediction-time exact distribution state"):
        build_prediction_record(
            prediction_payload(),
            commit_sha="missing-state-sha",
            require_exact_distribution=True,
        )


def test_readiness_audit_separates_legacy_and_prospective_sections():
    result = readiness_audit.audit(limit=5)
    assert result["network_used"] is False
    assert set(result) >= {
        "LEGACY_RECONSTRUCTION_COVERAGE",
        "PROSPECTIVE_CAPTURE_CAPABILITY",
        "readiness_decision",
        "historical_rewrite_count",
    }
    assert result["PROSPECTIVE_CAPTURE_CAPABILITY"]["effective_matrix_cell_count"] == 169
    assert result["PROSPECTIVE_CAPTURE_CAPABILITY"]["full_support"] is False
    assert result["LEGACY_RECONSTRUCTION_COVERAGE"]["formal_historical_full_support_truth"] is False
    assert result["historical_rewrite_count"] == 0
    assert result["readiness_decision"] in {
        readiness_audit.DECISION_READY,
        readiness_audit.DECISION_PARTIAL,
    }
