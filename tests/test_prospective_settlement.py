import json
from copy import deepcopy
import math
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from prediction_exclusions import is_prediction_excluded  # noqa: E402
from exact_distribution import (  # noqa: E402
    build_exact_distribution_contract,
    build_prediction_time_exact_distribution_state,
)
from prospective_settlement import (  # noqa: E402
    BASE_PREDICTION_POLICY,
    _jc_total_goals_summary,
    evaluate_prediction,
    is_formally_eligible,
    normalize_result,
    settle_records,
)


TZ = timezone(timedelta(hours=8))
NOW = datetime(2026, 8, 12, 12, 0, tzinfo=TZ)
KICKOFF = "2026-08-13T03:00:00+08:00"


def record(*, prediction_id="P-1", report_type="base_prediction_minimal", grade="C", kickoff=KICKOFF):
    return {
        "prediction_id": prediction_id,
        "prediction_sha256": f"sha-{prediction_id}",
        "match_key": f"FBOS-{prediction_id}",
        "match_id": "2040001",
        "business_date": "2026-08-12",
        "match_identity": {
            "match_key": f"FBOS-{prediction_id}",
            "home": "Home FC",
            "away": "Away FC",
            "kickoff_at": kickoff,
        },
        "kickoff_at": kickoff,
        "prediction_created_at": "2026-08-12T11:00:00+08:00",
        "source_cutoff_at": "2026-08-12T10:59:00+08:00",
        "freeze_created_at": "2026-08-12T11:00:01+08:00",
        "minutes_to_kickoff_at_freeze": 960.0,
        "prediction_status": "formal",
        "analysis_output": {"report_type": report_type},
        "model_role": "champion",
        "prediction_variant": "model_only",
        "manual_override": False,
        "model_source_fingerprint": "model-fingerprint",
        "model_input_snapshot_ref": "data/model_governance/input_snapshots/input.json",
        "input_sha256": "input-hash",
        "formal_eligibility_policy": BASE_PREDICTION_POLICY,
        "base_input_quality": "VERIFIED_MINIMUM",
        "generic_data_grade": grade,
        "data_grade": grade,
        "formal_eligible": True,
        "model_formal_eligible": True,
        "critical_missing_fields": [],
        "product_role": "FUSION_BASELINE_V0",
        "model_family": "recent_form_market_calibrated_poisson_v2",
        "release_version": "v0.19.0",
        "probabilities": {"home": 0.5, "draw": 0.3, "away": 0.2},
        "lambda_home": 1.5,
        "lambda_away": 0.8,
        "unique_score": "1-0",
        "btts": {"yes": 0.6, "no": 0.4},
        "score_distribution": [
            {"score": "1-0", "probability": 0.25, "rank": 1},
            {"score": "1-1", "probability": 0.20, "rank": 2},
            {"score": "2-0", "probability": 0.15, "rank": 3},
            {"score": "2-1", "probability": 0.10, "rank": 4},
            {"score": "0-0", "probability": 0.08, "rank": 5},
        ],
        "market_only_baseline": {
            "home": 0.4,
            "draw": 0.35,
            "away": 0.25,
            "sources": ["sporttery_spf"],
        },
        "market_intelligence_quality": "LIMITED",
        "market_data_providers": ["sporttery"],
        "market_bookmakers": [],
        "market_families": ["1x2"],
    }


def result(*, home=1, away=0, prediction_id="P-1", match_key="FBOS-P-1"):
    return {
        "status": "result_verified",
        "prediction_id": prediction_id,
        "match_key": match_key,
        "match_id": "2040001",
        "home": "Home FC",
        "away": "Away FC",
        "kickoff_local": KICKOFF,
        "score_90m": f"{home}-{away}",
        "home_score": home,
        "away_score": away,
        "scope": "regulation_90m_plus_stoppage",
        "source": "nowscore_match_detail",
        "verified_at": "2026-08-13T05:30:00+08:00",
    }


def jc_record(vector=None):
    vector = vector or [0.05, 0.10, 0.15, 0.20, 0.15, 0.10, 0.10, 0.15]
    current = record(prediction_id="JC-1")
    bucket_counts = {str(total): total + 1 for total in range(7)}
    bucket_counts["7+"] = 141
    matrix = {}
    for home in range(13):
        for away in range(13):
            total = home + away
            bucket = str(total) if total <= 6 else "7+"
            matrix[(home, away)] = vector[0 if bucket == "0" else int(bucket) if bucket != "7+" else 7] / bucket_counts[bucket]
    state = build_prediction_time_exact_distribution_state(
        matrix,
        lambda_home=1.5,
        lambda_away=0.8,
        rho=0.0,
    )
    contract = build_exact_distribution_contract(
        state,
        model_identity={
            "prediction_id": current["prediction_id"],
            "model_family": current["model_family"],
            "release_version": current["release_version"],
            "model_source_fingerprint": current["model_source_fingerprint"],
            "input_sha256": current["input_sha256"],
        },
    )
    current["exact_score_distribution"] = contract
    current["jc_total_goals"] = deepcopy(contract["jc_total_goals"])
    current["prediction_output"] = {"jc_total_goals": deepcopy(contract["jc_total_goals"])}
    return current


def test_base_c_grade_uses_explicit_policy_not_generic_grade():
    current = record(grade="C")
    assert is_formally_eligible(current) is True


def test_deep_c_grade_does_not_use_base_policy():
    current = record(report_type="deep_analysis", grade="C")
    current["formal_eligibility_policy"] = None
    assert is_formally_eligible(current) is False


def test_exclusion_helper_reads_prediction_ids(tmp_path):
    root = tmp_path / "exclusions"
    root.mkdir()
    (root / "pilot.json").write_text(
        json.dumps({"prediction_ids": ["P-1"], "reason_code": "BASE_QUALITY_GATE_BYPASS"}),
        encoding="utf-8",
    )
    assert is_prediction_excluded("P-1", root) is True
    assert is_prediction_excluded("P-2", root) is False


def test_evaluation_calculates_1x2_brier_and_logloss():
    metrics = evaluate_prediction(record(), {"home_score": 1, "away_score": 0})
    assert metrics["actual_outcome"] == "HOME"
    assert metrics["top1_accuracy_1x2"] == 1
    assert metrics["brier_score_1x2"] == pytest.approx((0.5 - 1) ** 2 + 0.3**2 + 0.2**2)
    assert metrics["log_loss_1x2"] == pytest.approx(-__import__("math").log(0.5))


def test_jc_evaluation_scores_are_independently_recomputed_from_frozen_vector():
    vector = [0.05, 0.10, 0.15, 0.20, 0.15, 0.10, 0.10, 0.15]
    metrics = evaluate_prediction(
        jc_record(vector),
        result(home=3, away=3, prediction_id="JC-1", match_key="FBOS-JC-1"),
    )
    actual_index = 6
    expected_log_loss = -math.log(vector[actual_index])
    expected_brier = sum(
        (probability - float(index == actual_index)) ** 2
        for index, probability in enumerate(vector)
    )
    expected_rps = sum(
        (
            sum(vector[:index + 1])
            - float(actual_index <= index)
        ) ** 2
        for index in range(len(vector) - 1)
    ) / (len(vector) - 1)

    assert metrics["jc_total_goals_evaluation_eligible"] is True
    assert metrics["jc_total_goals_evaluation_status"] == "ELIGIBLE_FROZEN_JC_TOTAL_GOALS"
    assert metrics["jc_total_goals_log_loss"] == pytest.approx(expected_log_loss)
    assert metrics["jc_total_goals_brier"] == pytest.approx(expected_brier)
    assert metrics["jc_total_goals_multiclass_brier"] == pytest.approx(expected_brier)
    assert metrics["jc_total_goals_rps"] == pytest.approx(expected_rps)
    assert metrics["jc_total_goals_brier_convention"] == "SUM_SQUARED_ERROR"
    assert metrics["jc_total_goals_rps_convention"] == "CUMULATIVE_SQUARED_ERROR_DIVIDED_BY_K_MINUS_1"
    assert metrics["jc_total_goals_rps_denominator"] == 7


def test_jc_evaluation_covers_0_6_7_and_high_total_boundaries():
    for home, away, expected_bucket in (
        (0, 0, "0"),
        (3, 3, "6"),
        (4, 3, "7+"),
        (13, 0, "7+"),
    ):
        metrics = evaluate_prediction(
            jc_record(),
            result(home=home, away=away, prediction_id="JC-1", match_key="FBOS-JC-1"),
        )
        assert metrics["actual_jc_total_goals_bucket"] == expected_bucket
        assert metrics["jc_total_goals_evaluation_eligible"] is True
        assert metrics["jc_total_goals_log_loss"] is not None


def test_jc_evaluation_is_frozen_only_and_fail_closed_for_bad_eligibility():
    frozen = jc_record()
    baseline = evaluate_prediction(
        frozen,
        result(home=4, away=3, prediction_id="JC-1", match_key="FBOS-JC-1"),
    )
    changed = deepcopy(frozen)
    changed["probabilities"] = {"home": 0.01, "draw": 0.01, "away": 0.98}
    changed["lambda_home"] = 99.0
    changed["lambda_away"] = 99.0
    changed["market_only_baseline"] = {"home": 0.99, "draw": 0.005, "away": 0.005}
    replay = evaluate_prediction(
        changed,
        result(home=4, away=3, prediction_id="JC-1", match_key="FBOS-JC-1"),
    )
    for key in (
        "jc_total_goals_log_loss",
        "jc_total_goals_brier",
        "jc_total_goals_rps",
        "actual_jc_total_goals_bucket",
    ):
        assert replay[key] == baseline[key]

    missing = evaluate_prediction(
        record(),
        result(home=3, away=3),
    )
    assert missing["jc_total_goals_evaluation_eligible"] is False
    assert missing["jc_total_goals_evaluation_status"] == "MISSING_FROZEN_JC_TOTAL_GOALS"
    assert missing["jc_total_goals_log_loss"] is None
    unverified = evaluate_prediction(jc_record(), {"home_score": 3, "away_score": 3})
    assert unverified["jc_total_goals_evaluation_eligible"] is False
    assert unverified["jc_total_goals_evaluation_status"] == "UNVERIFIED_90M_RESULT"

    zero_actual_probability = jc_record([0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.0, 0.4])
    invalid = evaluate_prediction(
        zero_actual_probability,
        result(home=3, away=3, prediction_id="JC-1", match_key="FBOS-JC-1"),
    )
    assert invalid["FORMAL_JC_TOTAL_GOALS_FROZEN"] is True
    assert invalid["jc_total_goals_evaluation_eligible"] is False
    assert invalid["jc_total_goals_evaluation_status"] == "INVALID_FROZEN_JC_ACTUAL_CLASS_PROBABILITY"
    assert invalid["jc_total_goals_brier"] is None

    excluded = jc_record()
    excluded["formal_eligible"] = False
    not_formal = evaluate_prediction(
        excluded,
        result(home=3, away=3, prediction_id="JC-1", match_key="FBOS-JC-1"),
    )
    assert not_formal["jc_total_goals_evaluation_eligible"] is False
    assert not_formal["jc_total_goals_evaluation_status"] == "NOT_FORMALLY_ELIGIBLE"


def test_jc_prospective_summary_reports_mix_recall_and_small_cohort_status():
    first = evaluate_prediction(
        jc_record(),
        result(home=3, away=3, prediction_id="JC-1", match_key="FBOS-JC-1"),
    )
    second = evaluate_prediction(
        jc_record([0.02, 0.03, 0.05, 0.08, 0.10, 0.12, 0.15, 0.45]),
        result(home=4, away=3, prediction_id="JC-1", match_key="FBOS-JC-1"),
    )
    summary = _jc_total_goals_summary([
        {"metrics": first},
        {"metrics": second},
        {"metrics": {"jc_total_goals_evaluation_eligible": False}},
    ])

    assert summary["status"] == "INSUFFICIENT_SAMPLE"
    assert summary["formal_cohort_n"] == 3
    assert summary["eligible_n"] == 2
    assert summary["coverage"] == pytest.approx(2 / 3, abs=1e-6)
    assert summary["eligibility_status_counts"] == {
        "ELIGIBLE_FROZEN_JC_TOTAL_GOALS": 2,
        "MISSING_PERSISTED_JC_EVALUATION": 1,
    }
    assert summary["mean_log_loss"] == pytest.approx(
        (first["jc_total_goals_log_loss"] + second["jc_total_goals_log_loss"]) / 2,
        abs=1e-9,
    )
    assert summary["predicted_class_counts"]["3"] == 1
    assert summary["predicted_class_counts"]["7+"] == 1
    assert summary["actual_class_counts"]["6"] == 1
    assert summary["actual_class_counts"]["7+"] == 1
    assert summary["per_class_recall"]["6"] == {"actual_n": 1, "hits": 0, "recall": 0.0}
    assert summary["per_class_recall"]["7+"] == {"actual_n": 1, "hits": 1, "recall": 1.0}

    empty = _jc_total_goals_summary([])
    assert empty["status"] == "INSUFFICIENT_SAMPLE"
    assert empty["eligible_n"] == 0
    assert empty["mean_rps"] is None
    assert empty["eligibility_status_counts"] == {}
    assert all(value is None for value in empty["actual_class_mix"].values())


def test_jc_metrics_and_summary_are_persisted_for_formal_settlement(tmp_path):
    out = settle_records(
        [jc_record()],
        now=datetime(2026, 8, 14, 12, 0, tzinfo=TZ),
        result_fetcher=lambda *_: result(
            home=4,
            away=3,
            prediction_id="JC-1",
            match_key="FBOS-JC-1",
        ),
        prospective_root=tmp_path,
        shadow_prediction_root=tmp_path / "shadow_predictions",
        shadow_settlement_root=tmp_path / "shadow_settlements",
    )
    sample = json.loads((tmp_path / "ledger.jsonl").read_text(encoding="utf-8"))
    summary = json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))

    assert out["formal_jc_total_goals_evaluation_eligible"] == 1
    assert sample["metrics"]["jc_total_goals_evaluation_eligible"] is True
    assert sample["metrics"]["jc_total_goals_log_loss"] is not None
    assert summary["jc_total_goals"]["eligible_n"] == 1
    assert summary["jc_total_goals"]["formal_cohort_n"] == 1
    assert summary["jc_total_goals"]["status"] == "INSUFFICIENT_SAMPLE"
    assert summary["jc_total_goals"]["actual_class_counts"]["7+"] == 1


def test_evaluation_calculates_goal_absolute_errors():
    metrics = evaluate_prediction(record(), {"home_score": 2, "away_score": 1})
    assert metrics["home_goal_absolute_error"] == pytest.approx(0.5)
    assert metrics["away_goal_absolute_error"] == pytest.approx(0.2)
    assert metrics["total_goal_absolute_error"] == pytest.approx(0.7)


def test_btts_brier_uses_frozen_probability():
    metrics = evaluate_prediction(record(), {"home_score": 1, "away_score": 1})
    assert metrics["btts_brier"] == pytest.approx((0.6 - 1) ** 2)


def test_btts_is_unavailable_when_not_frozen():
    current = record()
    current.pop("btts")
    metrics = evaluate_prediction(current, {"home_score": 1, "away_score": 1})
    assert metrics["btts_brier"] is None
    assert metrics["btts_metric_status"] == "UNAVAILABLE_IN_FROZEN_RECORD"


def test_exact_score_top1_top3_top5_are_from_frozen_rows():
    metrics = evaluate_prediction(record(), {"home_score": 2, "away_score": 0})
    assert metrics["exact_score_top1"] is False
    assert metrics["exact_score_top3"] is True
    assert metrics["exact_score_top5"] is True


def test_actual_score_nll_uses_frozen_score_probability_only():
    metrics = evaluate_prediction(record(), {"home_score": 1, "away_score": 1})
    assert metrics["actual_score_nll"] == pytest.approx(-__import__("math").log(0.2))

    current = record()
    current["score_distribution"] = current["score_distribution"][:2]
    unavailable = evaluate_prediction(current, {"home_score": 2, "away_score": 2})
    assert unavailable["actual_score_nll"] is None
    assert unavailable["actual_score_nll_status"] == "UNAVAILABLE_IN_FROZEN_RECORD"
    assert unavailable["exact_score_top10"] is None


def test_market_only_metrics_are_preserved():
    metrics = evaluate_prediction(record(), {"home_score": 0, "away_score": 1})
    assert metrics["market_only_1x2_brier"] == pytest.approx((0.4**2) + (0.35**2) + (0.25 - 1) ** 2)
    assert metrics["market_only_1x2_logloss"] == pytest.approx(-__import__("math").log(0.25))


def test_normalize_result_keeps_regulation_score_and_scope():
    normalized = normalize_result(result(home=2, away=2))
    assert normalized["home_score_90m"] == 2
    assert normalized["away_score_90m"] == 2
    assert normalized["actual_outcome"] == "DRAW"
    assert normalized["total_goals"] == 4
    assert normalized["btts_actual"] is True


def test_identity_mismatch_is_not_settled(tmp_path):
    current = record()
    out = settle_records(
        [current],
        now=datetime(2026, 8, 14, 12, 0, tzinfo=TZ),
        result_fetcher=lambda *_: result(match_key="OTHER-MATCH"),
        prospective_root=tmp_path,
    )
    assert out["result_conflicts"] == 0
    assert out["result_failures"] == 1
    assert out["failure_reasons"]["RESULT_IDENTITY_UNRESOLVED"] == 1


def test_pre_kickoff_result_is_pending(tmp_path):
    out = settle_records(
        [record()],
        now=NOW,
        result_fetcher=lambda *_: pytest.fail("must not fetch before kickoff"),
        prospective_root=tmp_path,
    )
    assert out["pending_results"] == 1
    assert out["formal_samples_added"] == 0


def test_valid_base_c_prediction_adds_one_formal_sample(tmp_path):
    out = settle_records(
        [record()],
        now=datetime(2026, 8, 14, 12, 0, tzinfo=TZ),
        result_fetcher=lambda *_: result(),
        prospective_root=tmp_path,
    )
    assert out["formal_samples_added"] == 1
    rows = (tmp_path / "ledger.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(rows) == 1
    assert json.loads(rows[0])["prediction_id"] == "P-1"


def test_repeated_settlement_is_idempotent_and_does_not_fetch_twice(tmp_path):
    calls = []
    kwargs = {
        "now": datetime(2026, 8, 14, 12, 0, tzinfo=TZ),
        "result_fetcher": lambda *_: calls.append(1) or result(),
        "prospective_root": tmp_path,
    }
    assert settle_records([record()], **kwargs)["formal_samples_added"] == 1
    assert settle_records([record()], **kwargs)["formal_samples_added"] == 0
    assert len(calls) == 2
    assert len((tmp_path / "ledger.jsonl").read_text(encoding="utf-8").splitlines()) == 1


def test_result_conflict_does_not_overwrite_existing_sample(tmp_path):
    settle_records(
        [record()],
        now=datetime(2026, 8, 14, 12, 0, tzinfo=TZ),
        result_fetcher=lambda *_: result(home=1, away=0),
        prospective_root=tmp_path,
    )
    out = settle_records(
        [record()],
        now=datetime(2026, 8, 14, 13, 0, tzinfo=TZ),
        result_fetcher=lambda *_: result(home=0, away=2),
        prospective_root=tmp_path,
    )
    assert out["result_conflicts"] == 1
    row = json.loads((tmp_path / "ledger.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert row["actual"]["home_score"] == 1


def test_excluded_pilot_is_exploratory_only(tmp_path):
    exclusions = tmp_path / "exclusions"
    exclusions.mkdir()
    (exclusions / "pilot.json").write_text(json.dumps({"prediction_ids": ["P-1"]}), encoding="utf-8")
    out = settle_records(
        [record()],
        now=datetime(2026, 8, 14, 12, 0, tzinfo=TZ),
        result_fetcher=lambda *_: result(),
        prospective_root=tmp_path / "prospective",
        exclusion_root=exclusions,
    )
    assert out["formal_samples_added"] == 0
    assert out["pilot_excluded_settled"] == 1
    assert (tmp_path / "prospective" / "ledger.jsonl").exists()
    assert not (tmp_path / "prospective" / "ledger.jsonl").read_text(encoding="utf-8")
    assert (tmp_path / "prospective" / "exploratory_settlements.jsonl").exists()


def test_after_kickoff_freeze_is_not_formally_eligible():
    current = record(kickoff="2026-08-13T10:00:00+08:00")
    current["freeze_created_at"] = "2026-08-13T10:00:01+08:00"
    assert is_formally_eligible(current) is False


def test_non_base_policy_cannot_enter_formal_ledger(tmp_path):
    current = record(report_type="deep_analysis", grade="C")
    current["formal_eligibility_policy"] = None
    out = settle_records(
        [current],
        now=datetime(2026, 8, 14, 12, 0, tzinfo=TZ),
        result_fetcher=lambda *_: result(),
        prospective_root=tmp_path,
    )
    assert out["formal_samples_added"] == 0
    assert out["frozen_predictions"] == 1


def test_result_after_extra_time_still_uses_saved_90m_score():
    current = result(home=1, away=0)
    current["after_extra_time"] = "2-0"
    normalized = normalize_result(current)
    assert normalized["home_score_90m"] == 1
    assert normalized["away_score_90m"] == 0


def test_live_result_payload_cannot_create_prospective_sample(tmp_path):
    live = {
        "status": "live",
        "match_key": "FBOS-P-1",
        "home_score": 1,
        "away_score": 0,
        "scope": "regulation_90m_plus_stoppage",
    }
    result_root = tmp_path / "results"
    out = settle_records(
        [record()],
        now=datetime(2026, 8, 14, 12, 0, tzinfo=TZ),
        result_fetcher=lambda *_: live,
        prospective_root=tmp_path / "prospective",
        result_root=result_root,
    )
    assert out["formal_samples_added"] == 0
    assert out["result_failures"] == 1
    assert not result_root.exists()


def test_verified_regulation_result_can_continue_to_evaluation(tmp_path):
    verified = result(home=1, away=0)
    out = settle_records(
        [record()],
        now=datetime(2026, 8, 14, 12, 0, tzinfo=TZ),
        result_fetcher=lambda *_: verified,
        prospective_root=tmp_path,
    )
    assert out["results_found"] == 1
    assert out["formal_samples_added"] == 1


def test_result_verified_before_kickoff_is_rejected(tmp_path):
    current = result()
    current["verified_at"] = "2026-08-13T02:59:00+08:00"
    out = settle_records(
        [record()],
        now=datetime(2026, 8, 14, 12, 0, tzinfo=TZ),
        result_fetcher=lambda *_: current,
        prospective_root=tmp_path,
    )
    assert out["formal_samples_added"] == 0
    assert out["failure_reasons"]["RESULT_TIME_UNVERIFIED"] == 1
