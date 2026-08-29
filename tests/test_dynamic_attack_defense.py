from __future__ import annotations

from copy import deepcopy

import pytest

from scripts.football_data.dynamic_attack_defense import (
    DynamicAttackDefenseSpec,
    build_dynamic_prediction,
    evaluate_paired_sample,
)


def _row(
    match_id: str,
    match_date: str,
    home_id: int,
    away_id: int,
    home_goals: int,
    away_goals: int,
) -> dict:
    return {
        "source_date": match_date[2:].replace("-", "-"),
        "match_date": match_date,
        "home_team_id": home_id,
        "home_team_name": f"home-{home_id}",
        "away_team_id": away_id,
        "away_team_name": f"away-{away_id}",
        "home_goals": home_goals,
        "away_goals": away_goals,
    }


def _evidence(*, include_future: bool = False) -> dict:
    home_rows = [
        _row(f"home-{index}", f"2026-08-{index + 1:02d}", 10, 100 + index, 2, 0)
        for index in range(5)
    ]
    away_rows = [
        _row(f"away-{index}", f"2026-08-{index + 1:02d}", 200 + index, 20, 1, 1)
        for index in range(5)
    ]
    if include_future:
        home_rows.append(_row("future", "2026-09-01", 10, 999, 9, 0))
    return {
        "contract_version": "prospective_football_evidence.v1",
        "prediction_id": "FBOS-PRED-test",
        "match_id": "500-test",
        "match_key": "FBOS-test",
        "home": "Test Home",
        "away": "Test Away",
        "kickoff_at": "2026-08-20T12:00:00Z",
        "source_provider": "nowscore",
        "evidence_captured_at": "2026-08-20T09:00:00Z",
        "source_cutoff_at": "2026-08-20T09:00:00Z",
        "recent_matches": {"home_team": home_rows, "away_team": away_rows},
    }


def _target() -> dict:
    return {
        "prediction_id": "FBOS-PRED-test",
        "match_key": "FBOS-test",
        "match_id": "500-test",
        "home_team_id": 10,
        "away_team_id": 20,
        "kickoff_at": "2026-08-20T12:00:00Z",
        # These fields must not be read by the research predictor.
        "home_goals": 0,
        "away_goals": 8,
    }


def test_dynamic_prediction_ignores_future_history_and_target_result():
    evidence = _evidence(include_future=True)
    first = build_dynamic_prediction(_target(), evidence)

    changed_target = deepcopy(_target())
    changed_target["home_goals"] = 8
    changed_target["away_goals"] = 0
    second = build_dynamic_prediction(changed_target, evidence)

    assert first == second
    assert first["features"]["target_result_excluded"] is True
    assert first["features"]["history_count"] == 10
    assert "future" not in first["features"]["used_match_ids"]
    assert all(value < "2026-08-20T12:00:00+00:00" for value in first["features"]["used_kickoffs"])


def test_spec_is_one_predeclared_bounded_configuration_not_a_weight_sweep():
    spec = DynamicAttackDefenseSpec()
    payload = spec.to_dict()

    assert payload["spec_id"] == "dynamic-attack-defense:bounded-v1"
    assert payload["weight_sweep"] is False
    assert payload["parameter_policy"] == "single_predeclared_spec"


def _prediction(*, top1: str = "1-0") -> dict:
    return {
        "probabilities": {"home": 0.5, "draw": 0.25, "away": 0.25},
        "lambda_home": 1.4,
        "lambda_away": 1.0,
        "rho": 0.0,
        "score_top1": top1,
        "score_top3": [top1, "0-0", "1-1"],
        "score_top5": [top1, "0-0", "1-1", "2-0", "0-1"],
    }


def test_paired_evaluation_rejects_nonidentical_samples():
    with pytest.raises(ValueError, match="strict paired sample"):
        evaluate_paired_sample(
            [
                {
                    "match_key": "match-a",
                    "dynamic_prediction": _prediction(),
                    "champion_prediction": _prediction(),
                    "actual": {"home_score": 1, "away_score": 0},
                },
                {
                    "match_key": "match-b",
                    "dynamic_prediction": _prediction(),
                    "champion_prediction": _prediction(),
                    "actual": {"home_score": 0, "away_score": 0},
                },
            ],
            champion_match_keys=["match-a", "match-c"],
        )


def test_paired_evaluation_reports_required_metrics_and_real_score_nll():
    result = evaluate_paired_sample(
        [
            {
                "match_key": "match-a",
                "dynamic_prediction": _prediction(),
                "champion_prediction": _prediction(top1="0-0"),
                "actual": {"home_score": 1, "away_score": 0},
            },
            {
                "match_key": "match-b",
                "dynamic_prediction": _prediction(top1="1-1"),
                "champion_prediction": _prediction(top1="1-1"),
                "actual": {"home_score": 3, "away_score": 2},
            },
        ]
    )

    dynamic = result["model_metrics"]["dynamic_attack_defense"]
    champion = result["model_metrics"]["champion"]
    for key in ("brier_1x2", "logloss_1x2", "goal_mae", "exact_top1", "exact_top3", "exact_top5", "one_to_one_share"):
        assert key in dynamic
        assert key in champion
    assert dynamic["score_nll"]["status"] == "REAL"
    assert champion["score_nll"]["status"] == "UNAVAILABLE"
    assert result["paired_sample_integrity"]["same_match_keys"] is True
