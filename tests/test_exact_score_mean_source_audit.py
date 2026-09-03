from __future__ import annotations

import json

from scripts.exact_score_mean_source_audit import (
    BOOTSTRAP_SEED,
    _canonical_json_sha256,
    compute_total_components,
    diagnose_mean_source,
    split_chronological_thirds,
    source_metric_summary,
)


def test_total_components_follow_current_champion_formula_and_expose_adjustments():
    components = compute_total_components(
        home_form=2.2166666667,
        away_form=2.3666666667,
        market_total_line=3.5,
        calibration_total_shift=0.0,
    )

    assert components["raw_form_total"] > 4.2
    assert components["form_total"] == 4.2
    assert components["target_total"] == 3.5
    assert components["uncalibrated_total"] == 3.92
    assert components["calibration_total_shift"] == 0.0
    assert components["final_total"] == 3.92
    assert components["form_total_clamp_effect"] < 0
    assert components["final_total_clamp_effect"] == 0.0


def test_source_metric_summary_is_seeded_and_treats_each_match_as_one_observation():
    rows = [
        {"actual_total": 2, "form_total": 1.0},
        {"actual_total": 4, "form_total": 3.0},
        {"actual_total": 3, "form_total": 4.0},
    ]

    first = source_metric_summary(rows, "form_total", seed=BOOTSTRAP_SEED, replicates=120)
    second = source_metric_summary(rows, "form_total", seed=BOOTSTRAP_SEED, replicates=120)

    assert first == second
    assert first["observation_n"] == 3
    assert first["predicted_mean"] == 8 / 3
    assert first["actual_mean"] == 3.0
    assert first["mean_difference_predicted_minus_actual"] == -1 / 3
    assert first["mae"] == 1.0
    assert len(first["mean_difference_bootstrap_ci_95"]) == 2
    assert len(first["mae_bootstrap_ci_95"]) == 2


def test_chronological_thirds_are_deterministic_and_nearly_equal():
    rows = [
        {"kickoff_at": f"2026-08-{day:02d}T00:00:00+08:00", "match_key": str(day)}
        for day in range(1, 8)
    ]

    thirds = split_chronological_thirds(rows)

    assert [len(thirds[name]) for name in ("earliest_third", "middle_third", "latest_third")] == [2, 2, 3]
    assert thirds["earliest_third"][0]["match_key"] == "1"
    assert thirds["latest_third"][-1]["match_key"] == "7"


def test_mean_source_diagnosis_is_mixed_when_both_inputs_are_low_and_regime_is_high():
    low_ci = [-0.8, -0.2]
    global_scope = {
        "sources": {
            "form_total": {
                "mean_difference_predicted_minus_actual": -0.4,
                "mean_difference_bootstrap_ci_95": low_ci,
            },
            "market_total_line": {
                "mean_difference_predicted_minus_actual": -0.6,
                "mean_difference_bootstrap_ci_95": low_ci,
            },
            "uncalibrated_total": {
                "mean_difference_predicted_minus_actual": -0.48,
                "mean_difference_bootstrap_ci_95": low_ci,
            },
            "final_lambda_total": {
                "mean_difference_predicted_minus_actual": -0.49,
                "mean_difference_bootstrap_ci_95": low_ci,
            },
        }
    }
    adjustments = {
        "calibration_total_shift": {"changed_n": 0, "mean_shift": 0.0},
        "final_total_clamp": {"changed_n": 0, "mean_shift": 0.0},
    }
    environment = {
        "mean_total_difference_current_minus_history": 0.58,
        "mean_total_difference_bootstrap_ci_95": [0.25, 0.9],
    }

    diagnosis = diagnose_mean_source(global_scope, adjustments, environment)

    assert diagnosis["PRIMARY_MEAN_SOURCE"] == "MIXED"
    assert diagnosis["regime_context_signal"] == "SHORT_WINDOW_SCORING_REGIME"
    assert diagnosis["GLOBAL_LAMBDA_RAISE_ALLOWED"] == "NO"


def test_canonical_hash_is_independent_of_json_formatting():
    value = {"nested": {"b": 2, "a": 1}, "unicode": "进球"}
    reformatted = json.loads(json.dumps(value, ensure_ascii=False, indent=2))

    assert _canonical_json_sha256(value) == _canonical_json_sha256(reformatted)
