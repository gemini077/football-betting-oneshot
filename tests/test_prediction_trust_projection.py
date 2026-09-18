from __future__ import annotations

import json
from pathlib import Path

from scripts.prediction_trust_projection import CALIBRATION_BANDS, _calibration, build_projection
from test_prediction_trust_audit import prediction


def settled(prediction_id: str, *, home: int, away: int, verified_at: str = "2026-08-14T08:00:00+08:00") -> dict:
    return {
        "prediction_id": prediction_id,
        "formal_prospective_eligible": True,
        "actual": {
            "home_score": home,
            "away_score": away,
            "outcome": "HOME" if home > away else "AWAY" if home < away else "DRAW",
        },
        "result_verified_at": verified_at,
    }


def test_projection_uses_one_unique_match_from_the_current_version_only():
    older_current = prediction("P-CURRENT-OLDER", match_id="M-1", created="2026-08-12T14:00:00+08:00")
    older_current["model_run_fingerprint"] = "CURRENT"
    newer_other = prediction("P-OTHER-NEWER", match_id="M-1", created="2026-08-12T15:00:00+08:00", source="2026-08-12T14:59:00+08:00", freeze="2026-08-12T15:01:00+08:00")
    newer_other["model_run_fingerprint"] = "OTHER"

    result = build_projection(
        [older_current, newer_other],
        [settled("P-CURRENT-OLDER", home=1, away=0)],
        current_fingerprint="CURRENT",
        generated_at="2026-08-15T00:00:00+08:00",
    )

    assert result["status"] == "AVAILABLE"
    assert result["cohort"]["locked_unique_match_count"] == 1
    assert result["cohort"]["selected_prediction_ids"] == ["P-CURRENT-OLDER"]
    assert result["cohort"]["superseded_version_count"] == 0
    assert result["version_counts"] == {"CURRENT": 1, "OTHER": 1}


def test_projection_keeps_pending_rows_and_recomputes_canonical_metrics():
    first = prediction("P-1", match_id="M-1", home_probability=0.6, away_probability=0.2)
    first["model_run_fingerprint"] = "CURRENT"
    first["score_top1"] = "1-1"
    second = prediction("P-2", match_id="M-2", home_probability=0.2, away_probability=0.6, score="2-1")
    second["model_run_fingerprint"] = "CURRENT"

    result = build_projection(
        [first, second],
        [settled("P-1", home=1, away=1)],
        current_fingerprint="CURRENT",
        generated_at="2026-08-15T00:00:00+08:00",
    )

    assert result["cohort"]["locked_unique_match_count"] == 2
    assert result["cohort"]["settled_unique_match_count"] == 1
    assert result["cohort"]["pending_unique_match_count"] == 1
    assert result["metrics"]["ft_1x2"]["n"] == 1
    assert result["metrics"]["ft_1x2"]["top1_accuracy"]["hits"] == 0
    assert result["metrics"]["exact_score"]["formal_nll"]["n"] == 0
    assert result["calibration"]["home"][0]["lower_bound"] == 0.0
    assert len(result["calibration"]["home"]) == 5
    assert result["collapse_diagnostics"]["one_one_top1"]["n"] == 1
    assert {row["status"] for row in result["history"]} == {"SETTLED", "PENDING"}
    assert any(row["status"] == "PENDING" for row in result["public"]["history"])


def test_calibration_uses_disjoint_r37_bands_and_observed_minus_predicted_gap():
    rows = [
        {"probabilities": {"home": 0.0, "draw": 0.5, "away": 0.5}, "actual_outcome": "draw"},
        {"probabilities": {"home": 0.2, "draw": 0.4, "away": 0.4}, "actual_outcome": "home"},
        {"probabilities": {"home": 0.4, "draw": 0.3, "away": 0.3}, "actual_outcome": "away"},
        {"probabilities": {"home": 0.6, "draw": 0.2, "away": 0.2}, "actual_outcome": "home"},
        {"probabilities": {"home": 0.8, "draw": 0.1, "away": 0.1}, "actual_outcome": "draw"},
        {"probabilities": {"home": 1.0, "draw": 0.0, "away": 0.0}, "actual_outcome": "home"},
    ]

    calibration = _calibration(rows)

    assert CALIBRATION_BANDS == ((0.0, 0.2), (0.2, 0.4), (0.4, 0.6), (0.6, 0.8), (0.8, 1.0))
    for outcome in ("home", "draw", "away"):
        bands = calibration[outcome]
        assert len(bands) == len(CALIBRATION_BANDS)
        assert sum(band["n"] for band in bands) == len(rows)
    assert [band["n"] for band in calibration["home"]] == [1, 1, 1, 1, 2]
    assert calibration["home"][1]["mean_predicted"] == 0.2
    assert calibration["home"][1]["observed_frequency"] == 1.0
    assert calibration["home"][1]["gap"] == 0.8
    assert calibration["home"][-1]["mean_predicted"] == 0.9


def test_projection_calibration_counts_are_auditable_against_settled_denominator():
    records = []
    settlements = []
    for index, (home_probability, away_probability) in enumerate(((0.1, 0.7), (0.5, 0.2), (0.9, 0.05)), start=1):
        record = prediction(
            f"P-CAL-{index}",
            match_id=f"M-CAL-{index}",
            home_probability=home_probability,
            away_probability=away_probability,
        )
        record["model_run_fingerprint"] = "CURRENT"
        records.append(record)
        settlements.append(settled(f"P-CAL-{index}", home=index, away=0))

    result = build_projection(records, settlements, current_fingerprint="CURRENT", generated_at="2026-08-15T00:00:00+08:00")
    denominator = result["cohort"]["settled_unique_match_count"]

    assert denominator == 3
    for bands in result["calibration"].values():
        assert sum(band["n"] for band in bands) == denominator


def test_current_artifact_calibration_fields_are_directly_recomputable():
    artifact = json.loads(
        (Path(__file__).resolve().parents[1] / "data" / "prediction_quality" / "current_champion_trust.json").read_text(
            encoding="utf-8"
        )
    )

    for bands in artifact["calibration"].values():
        for band in bands:
            if band["n"]:
                assert band["gap"] == round(band["observed_frequency"] - band["mean_predicted"], 6)


def test_projection_surfaces_pair_counts_without_authorizing_promotion():
    record = prediction("P-1")
    record["model_run_fingerprint"] = "CURRENT"
    market_review = {
        "counts": {
            "unique_market_matches": 3,
            "paired_unique_match_count": 1,
            "rejected_unique_market_match_count": 2,
            "reject_reason_counts": {"CHAMPION_PREDICTION_MISSING": 2},
        },
        "decision": {
            "sample_band": "n<50",
            "verdict": "INSUFFICIENT_SAMPLE_CONTINUE_ACCUMULATING",
            "promotion_authorized": False,
        },
        "metrics": {"deltas": {"exact_nll": {"n": 1, "mean": 0.1, "ci95_low": 0.1, "ci95_high": 0.1}}},
        "pairs": [],
        "rejections": [],
    }

    result = build_projection(
        [record],
        [settled("P-1", home=1, away=0)],
        current_fingerprint="CURRENT",
        market_review=market_review,
        generated_at="2026-08-15T00:00:00+08:00",
    )

    comparator = result["comparator"]
    assert comparator["paired_unique_match_count"] == 1
    assert comparator["unpaired_unique_match_count"] == 2
    assert comparator["decision"]["promotion_authorized"] is False
    assert result["public"]["comparator"]["unpaired_unique_match_count"] == 2


def test_projection_does_not_choose_a_conflicting_settlement():
    record = prediction("P-CONFLICT")
    record["model_run_fingerprint"] = "CURRENT"

    result = build_projection(
        [record],
        [settled("P-CONFLICT", home=1, away=0), settled("P-CONFLICT", home=0, away=1)],
        current_fingerprint="CURRENT",
        generated_at="2026-08-15T00:00:00+08:00",
    )

    assert result["status"] == "DEGRADED"
    assert result["cohort"]["settled_unique_match_count"] == 0
    assert result["cohort"]["unresolved_unique_match_count"] == 1
    assert result["cohort"]["evaluation_reason_counts"] == {"SETTLEMENT_CONFLICT": 1}
