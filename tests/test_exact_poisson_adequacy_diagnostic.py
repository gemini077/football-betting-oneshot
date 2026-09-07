from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from exact_poisson_adequacy_diagnostic import (  # noqa: E402
    BOOTSTRAP_RESAMPLES,
    FIXED_COHORT_COUNT,
    _bootstrap_mean,
    _market_independent_matrix,
    _poisson_pit,
    run_diagnostic,
)


@pytest.fixture(scope="module")
def evidence():
    return run_diagnostic()


def test_fixed_107_authority_and_same_time_lambda_are_verified(evidence):
    assert evidence["decision"] in {
        "POISSON_MISSPECIFICATION_SIGNAL_ESTABLISHED",
        "POISSON_ADEQUACY_NOT_REJECTED",
        "POISSON_ADEQUACY_INCONCLUSIVE",
        "FAIL_CLOSED",
    }
    assert evidence["fixed_cohort"]["status"] == "PASS"
    assert evidence["fixed_cohort"]["unique_match_count"] == FIXED_COHORT_COUNT
    assert len(evidence["paired_rows"]) == FIXED_COHORT_COUNT
    assert evidence["integrity"]["fixed_market_lambda_checked"] is True
    assert evidence["integrity"]["same_time_market_reference_only"] is True


def test_parameter_free_scope_has_no_alternative_family_or_promotion(evidence):
    assert evidence["DC_EXACT_NLL"] is None
    assert evidence["NB_EXACT_NLL"] is None
    assert evidence["DC_DELTA_CI"] is None
    assert evidence["NB_DELTA_CI"] is None
    assert evidence["BEST_SUPPORTED_FAMILY"] is None
    integrity = evidence["integrity"]
    assert integrity["new_model_or_parameter_fit"] is False
    assert integrity["alternative_family_comparison"] is False
    assert integrity["automatic_promotion"] is False
    assert integrity["network_calls"] is False
    assert integrity["replay_or_backfill"] is False


def test_required_diagnostic_dimensions_and_fixed_bootstrap_are_present(evidence):
    diagnostics = evidence["diagnostics"]
    assert set(diagnostics["marginal_calibration"]) == {"home", "away", "total"}
    assert set(diagnostics["dispersion"]) == {"home", "away", "total"}
    assert set(diagnostics["pit"]) == {"home", "away", "total"}
    assert set(diagnostics["right_tail"]) == {"4", "5", "6"}
    assert set(diagnostics["low_score"]) == {"0-0", "1-0", "0-1", "1-1"}
    assert evidence["bootstrap"]["resamples"] == BOOTSTRAP_RESAMPLES == 10_000
    assert evidence["randomized_pit"]["randomization_replicates"] == 100
    assert diagnostics["slices"]["minimum_slice_n"] == 10


def test_parameter_free_math_helpers_are_deterministic_and_normalized():
    matrix, tail_mass = _market_independent_matrix(1.4, 0.9)
    assert sum(matrix.values()) + tail_mass == pytest.approx(1.0, abs=1e-12)
    assert tail_mass >= 0.0
    pit = _poisson_pit(1.4, 2, 0.25)
    assert 0.0 <= pit <= 1.0
    first = _bootstrap_mean([0.0, 1.0, 2.0], seed=2251999, resamples=200)
    second = _bootstrap_mean([0.0, 1.0, 2.0], seed=2251999, resamples=200)
    assert first == second
    assert first["resamples"] == 200
