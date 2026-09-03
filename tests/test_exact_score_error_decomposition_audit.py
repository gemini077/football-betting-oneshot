from __future__ import annotations

import math

from scripts.exact_score_error_decomposition_audit import (
    BOOTSTRAP_SEED,
    classify_competition,
    expected_shape_probabilities,
    run_intensity_analysis,
    run_parametric_shape_bootstrap,
)


def test_classify_competition_uses_metadata_not_team_names():
    assert classify_competition("\u897f\u73ed\u7259\u7532\u7ea7\u8054\u8d5b") == "CLUB_TOP_LEAGUE"
    assert classify_competition("\u6b27\u6d32\u51a0\u519b\u8054\u8d5b") == "CLUB_CONTINENTAL"
    assert classify_competition("\u82f1\u683c\u5170\u8054\u8d5b\u676f") == "CLUB_DOMESTIC_CUP"
    assert classify_competition("\u82f1\u683c\u5170\u51a0\u519b\u8054\u8d5b") == "CLUB_LOWER_OR_SMALL_LEAGUE"
    assert classify_competition("\u56fd\u9645\u53cb\u8c0a\u8d5b") == "NATIONAL_TEAM"
    assert classify_competition("") == "UNKNOWN_OR_MIXED"


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
