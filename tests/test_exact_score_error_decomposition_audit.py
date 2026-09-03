from __future__ import annotations

import math
import random

from scripts.exact_score_error_decomposition_audit import (
    BOOTSTRAP_SEED,
    SHAPE_METRICS,
    _sample_poisson,
    _classification,
    classify_competition,
    expected_shape_probabilities,
    run_intensity_analysis,
    run_mean_conditioned_shape_bootstrap,
    run_pairwise_total_bias_bootstrap,
    run_parametric_shape_bootstrap,
)


def test_classify_competition_uses_metadata_not_team_names():
    assert classify_competition("\u897f\u73ed\u7259\u7532\u7ea7\u8054\u8d5b") == "CLUB_BIG5_TOP_LEAGUE"
    assert classify_competition("\u82f1\u683c\u5170\u8d85\u7ea7\u8054\u8d5b") == "CLUB_BIG5_TOP_LEAGUE"
    assert classify_competition("\u745e\u5178\u8d85\u7ea7\u8054\u8d5b") == "CLUB_OTHER_TOP_LEAGUE"
    assert classify_competition("\u7f8e\u56fd\u804c\u4e1a\u5927\u8054\u76df") == "CLUB_OTHER_TOP_LEAGUE"
    assert classify_competition("\u65e5\u672c\u804c\u4e1a\u8054\u8d5b") == "CLUB_OTHER_TOP_LEAGUE"
    assert classify_competition("\u97e9\u56fd\u804c\u4e1a\u8054\u8d5b") == "CLUB_OTHER_TOP_LEAGUE"
    assert classify_competition("\u5fb7\u56fd\u4e59\u7ea7\u8054\u8d5b") == "CLUB_LOWER_DIVISION"
    assert classify_competition("\u82f1\u683c\u5170\u51a0\u519b\u8054\u8d5b") == "CLUB_LOWER_DIVISION"
    assert classify_competition("\u5df4\u897f\u676f") == "CLUB_DOMESTIC_CUP"
    assert classify_competition("\u6b27\u6d32\u51a0\u519b\u8054\u8d5b") == "CLUB_CONTINENTAL"
    assert classify_competition("\u82f1\u683c\u5170\u8054\u8d5b\u676f") == "CLUB_DOMESTIC_CUP"
    assert classify_competition("\u56fd\u9645\u53cb\u8c0a\u8d5b") == "NATIONAL_TEAM"
    assert classify_competition("") == "UNKNOWN_OR_MIXED"
    assert classify_competition("\u672a\u77e5\u8054\u8d5b") == "UNKNOWN_OR_MIXED"


def test_independent_poisson_shape_probabilities_use_each_match_lambdas():
    values = expected_shape_probabilities(2.0, 1.0)

    assert math.isclose(values["total_0"], math.exp(-3.0), rel_tol=1e-12)
    assert math.isclose(values["total_1"], 3.0 * math.exp(-3.0), rel_tol=1e-12)
    expected_draw = math.exp(-3.0) * sum(2.0**k / math.factorial(k) ** 2 for k in range(30))
    assert math.isclose(values["draw"], expected_draw, rel_tol=1e-12)
    assert math.isclose(values["btts"], (1.0 - math.exp(-2.0)) * (1.0 - math.exp(-1.0)), rel_tol=1e-12)
    assert math.isclose(values["score_0_0"], math.exp(-3.0), rel_tol=1e-12)
    assert math.isclose(values["score_1_1"], 2.0 * math.exp(-3.0), rel_tol=1e-12)


def test_parametric_shape_bootstrap_is_seeded_and_one_match_is_one_observation():
    rows = [
        {"lambda_home": 1.2, "lambda_away": 0.8, "actual_home": 2, "actual_away": 0},
        {"lambda_home": 1.4, "lambda_away": 1.1, "actual_home": 1, "actual_away": 1},
    ]

    first = run_parametric_shape_bootstrap(rows, seed=BOOTSTRAP_SEED, replicates=80)
    second = run_parametric_shape_bootstrap(rows, seed=BOOTSTRAP_SEED, replicates=80)

    assert first == second
    assert first["sample_count"] == 2
    assert set(first["metrics"]) == {
        "total_0",
        "total_1",
        "total_2",
        "total_3",
        "total_4_plus",
        "total_5_plus",
        "total_6_plus",
        "draw",
        "btts",
        "score_0_0",
        "score_1_1",
    }
    assert first["diagnostic"] == "RAW_SHAPE_DIAGNOSTIC"

    conditioned_first = run_mean_conditioned_shape_bootstrap(rows, seed=BOOTSTRAP_SEED, replicates=80)
    conditioned_second = run_mean_conditioned_shape_bootstrap(rows, seed=BOOTSTRAP_SEED, replicates=80)
    assert conditioned_first == conditioned_second
    assert conditioned_first["diagnostic"] == "MEAN_CONDITIONED_SHAPE"
    assert set(conditioned_first["metrics"]) == set(SHAPE_METRICS)
    assert conditioned_first["multiple_testing"] == {
        "method": "Holm-Bonferroni",
        "family_wise_alpha": 0.05,
        "metric_count": len(SHAPE_METRICS),
    }
    assert all(
        entry["adjusted_p_value"] >= entry["raw_p_value"]
        for entry in conditioned_first["metrics"].values()
    )


def test_mean_conditioned_shape_diagnostic_does_not_call_mean_error_shape_error():
    rng = random.Random(17)
    rows = [
        {
            "lambda_home": 1.0,
            "lambda_away": 1.0,
            "actual_home": _sample_poisson(2.0, rng),
            "actual_away": _sample_poisson(2.0, rng),
        }
        for _ in range(240)
    ]

    raw = run_parametric_shape_bootstrap(rows, seed=BOOTSTRAP_SEED, replicates=300)
    conditioned = run_mean_conditioned_shape_bootstrap(rows, seed=BOOTSTRAP_SEED, replicates=300)

    assert raw["metrics"]["total_4_plus"]["raw_p_value"] <= 0.05
    assert all(entry["adjusted_p_value"] > 0.05 for entry in conditioned["metrics"].values())


def test_mean_conditioned_shape_diagnostic_retains_true_overdispersion_signal():
    rng = random.Random(18)
    rows = []
    for _ in range(180):
        latent_mean = 0.2 if rng.random() < 0.5 else 2.0
        rows.append(
            {
                "lambda_home": 1.1,
                "lambda_away": 1.1,
                "actual_home": _sample_poisson(latent_mean, rng),
                "actual_away": _sample_poisson(latent_mean, rng),
            }
        )

    conditioned = run_mean_conditioned_shape_bootstrap(rows, seed=BOOTSTRAP_SEED, replicates=300)

    assert any(entry["adjusted_p_value"] <= 0.05 for entry in conditioned["metrics"].values())


def test_distribution_shape_classification_ignores_raw_shape_p_values():
    intensity_metrics = {
        metric: {"nonparametric_bootstrap_ci_95": [1.0, 2.0]}
        for metric in (
            "lambda_home_bias_predicted_minus_actual",
            "lambda_away_bias_predicted_minus_actual",
            "lambda_total_mean_bias_predicted_minus_actual",
        )
    }
    raw_metrics = {metric: {"raw_p_value": 0.001} for metric in SHAPE_METRICS}
    conditioned_metrics = {metric: {"adjusted_p_value": 0.25} for metric in SHAPE_METRICS}
    global_scope = {
        "sample_count": 181,
        "bootstrap_seed": BOOTSTRAP_SEED,
        "bootstrap_replicates": 80,
        "intensity": {"metrics": intensity_metrics},
        "raw_shape_diagnostic": {"metrics": raw_metrics},
        "mean_conditioned_shape": {"metrics": conditioned_metrics},
    }

    classifications, _ = _classification(global_scope, {}, [], {})

    assert classifications["DISTRIBUTION_SHAPE"]["status"] == "NOT_SUPPORTED"


def test_pairwise_total_bias_bootstrap_reports_predefined_universe_difference():
    rows_a = [{"lambda_total": 1.0, "actual_total": 0} for _ in range(25)]
    rows_b = [{"lambda_total": 1.0, "actual_total": 3} for _ in range(25)]

    result = run_pairwise_total_bias_bootstrap(
        rows_a,
        rows_b,
        universe_a="CLUB_BIG5_TOP_LEAGUE",
        universe_b="CLUB_OTHER_TOP_LEAGUE",
        seed=BOOTSTRAP_SEED,
        replicates=80,
    )

    assert result["point_estimate_bias_a_minus_bias_b"] == 3.0
    assert result["bootstrap_ci_95_bias_difference"] == [3.0, 3.0]
    assert result["ci_excludes_zero"] is True


def test_intensity_reports_home_away_total_bias_and_lambda_bins():
    rows = [
        {
            "lambda_home": 1.0,
            "lambda_away": 1.0,
            "lambda_total": 2.0,
            "actual_home": 2,
            "actual_away": 1,
            "actual_total": 3,
        },
        {
            "lambda_home": 2.0,
            "lambda_away": 1.0,
            "lambda_total": 3.0,
            "actual_home": 1,
            "actual_away": 0,
            "actual_total": 1,
        },
    ]

    result = run_intensity_analysis(rows, seed=BOOTSTRAP_SEED, replicates=40)

    assert result["sample_count"] == 2
    assert result["metrics"]["lambda_total_mean_bias_predicted_minus_actual"]["value"] == 0.5
    assert result["metrics"]["lambda_total_mae"]["value"] == 1.5
    assert len(result["lambda_total_bins"]) == 6
