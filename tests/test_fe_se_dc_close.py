from __future__ import annotations

import pytest

from scripts.football_data.fe_dc1_model import PreRegisteredConfig
from scripts.football_data.fe_se_dc_close import (
    ReplayIntegrityError,
    _evaluate_extended,
    _target_reconciliation,
)


def _old_target(match_id: str = "old-id", *, home_goals: int = 2, away_goals: int = 1) -> dict:
    return {
        "match_id": match_id,
        "competition_id": "competition:sweden-allsvenskan",
        "season_id": "season:sweden-allsvenskan:2026",
        "kickoff_at": "2026-04-17T18:00:00Z",
        "home_team_id": "team:home",
        "away_team_id": "team:away",
        "actual_home_goals": home_goals,
        "actual_away_goals": away_goals,
    }


def _new_record(match_id: str = "new-id", *, home_goals: int = 2, away_goals: int = 1) -> dict:
    return {
        "canonical_match_id": match_id,
        "competition_id": "competition:sweden-allsvenskan",
        "season_id": "season:sweden-allsvenskan:2026",
        "home_team_id": "team:home",
        "away_team_id": "team:away",
        "kickoff_at": "2026-04-17T17:00:00Z",
        "home_goals": home_goals,
        "away_goals": away_goals,
    }


def test_target_reconciliation_uses_exact_id_before_deterministic_fixture_key() -> None:
    exact = _target_reconciliation([_old_target(match_id="same-id")], [_new_record(match_id="same-id")])
    assert exact["exact_id_count"] == 1
    assert exact["deterministic_reconciled_count"] == 0

    reconciled = _target_reconciliation([_old_target(match_id="old-id")], [_new_record(match_id="new-id")])
    assert reconciled["exact_id_count"] == 0
    assert reconciled["deterministic_reconciled_count"] == 1
    assert reconciled["mappings"][0]["method"].endswith("deterministic_reconciliation")


def test_target_reconciliation_rejects_outcome_change() -> None:
    with pytest.raises(ReplayIntegrityError, match="fixture/outcome changed"):
        _target_reconciliation([_old_target()], [_new_record(home_goals=0)])


def test_config_is_the_preregistered_fe_dc1_configuration() -> None:
    config = PreRegisteredConfig()
    assert config.competition_id == "competition:sweden-allsvenskan"
    assert config.half_life_days == 365
    assert config.warmup_matches == 32
    assert config.max_goals == 12
    assert config.rho_bounds == (-0.1, 0.1)
    assert config.optimizer_max_iter == 500
    assert config.optimizer_tolerance == 1e-6
    assert config.parameter_bound == 1.5
    assert config.home_advantage_bounds == (-0.8, 0.8)


def test_target_reconciliation_rejects_missing_or_ambiguous_fixture() -> None:
    with pytest.raises(ReplayIntegrityError, match="target reconciliation incomplete"):
        _target_reconciliation([_old_target()], [])
    with pytest.raises(ReplayIntegrityError, match="target reconciliation incomplete"):
        _target_reconciliation([_old_target()], [_new_record("a"), _new_record("b")])


def test_evaluate_extended_reports_top1_and_rho_boundary() -> None:
    model = {
        "model_id": "test",
        "rho_mode": "fit",
        "lambda_home": 1.0,
        "lambda_away": 1.0,
        "rho": -0.1,
        "max_goals": 12,
        "matrix": [[1.0]],
        "grid_mass": 1.0,
        "independent_poisson_grid_mass": 1.0,
        "tail_mass": 0.0,
        "normalization_factor": 1.0,
        "probabilities": {"home": 0.6, "draw": 0.2, "away": 0.2},
        "score_probabilities": {"1-0": 0.7, "0-0": 0.2, "0-1": 0.1},
        "top_scores": [{"score": "1-0", "probability": 0.7}],
        "total_goals_distribution": {"1": 1.0},
        "fit_diagnostics": {"optimizer_converged": True},
    }
    row = {
        "match_id": "m",
        "actual_home_goals": 1,
        "actual_away_goals": 0,
        "history_match_count": 1,
        "home_history_match_count": 1,
        "away_history_match_count": 1,
        "models": {"dixon_coles": model},
    }
    metrics = _evaluate_extended([row], "dixon_coles", PreRegisteredConfig())
    assert metrics["top1_outcome_hit_rate"] == 1.0
    assert metrics["rho_boundary_hit_frequency"]["lower"] == 1
