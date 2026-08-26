import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from prediction_exclusions import is_prediction_excluded  # noqa: E402
from prospective_settlement import (  # noqa: E402
    BASE_PREDICTION_POLICY,
    canonicalize_formal_records,
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


def same_match_record(prediction_id, freeze_created_at):
    current = record(prediction_id=prediction_id)
    current.update({
        "match_key": "FBOS-SAME-MATCH",
        "match_identity": {
            "match_key": "FBOS-SAME-MATCH",
            "home": "Home FC",
            "away": "Away FC",
            "kickoff_at": KICKOFF,
        },
        "model_input_snapshot_ref": f"data/model_governance/input_snapshots/{prediction_id}.json",
        "input_sha256": f"input-{prediction_id}",
        "freeze_created_at": freeze_created_at,
    })
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


def test_settle_records_formally_appends_only_latest_legal_version(tmp_path, monkeypatch):
    earlier = same_match_record("P-EARLY", "2026-08-12T12:00:00+08:00")
    latest = same_match_record("P-LATEST", "2026-08-13T02:30:00+08:00")
    shadow_calls = []

    import baseline_production

    monkeypatch.setattr(
        baseline_production,
        "settle_market_direction_shadow_for_result",
        lambda record, *_args, **_kwargs: shadow_calls.append(record["prediction_id"]) or {"status": "no_op"},
    )
    out = settle_records(
        [earlier, latest],
        now=datetime(2026, 8, 14, 12, 0, tzinfo=TZ),
        result_fetcher=lambda *_: result(match_key="FBOS-SAME-MATCH"),
        prospective_root=tmp_path / "prospective",
        shadow_prediction_root=tmp_path / "shadow-predictions",
        shadow_settlement_root=tmp_path / "shadow-settlements",
    )

    rows = [
        json.loads(line)
        for line in (tmp_path / "prospective" / "ledger.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert out["formal_samples_added"] == 1
    assert out["superseded_formal_prediction_count"] == 1
    assert out["canonical_formal_match_count"] == 1
    assert [row["prediction_id"] for row in rows] == ["P-LATEST"]
    assert shadow_calls == ["P-EARLY", "P-LATEST"]


def test_canonical_tie_break_is_deterministic_and_not_settled_at_based():
    first = same_match_record("P-TIE-A", "2026-08-13T02:00:00+08:00")
    second = same_match_record("P-TIE-B", "2026-08-13T02:00:00+08:00")
    first["settled_at"] = "2099-01-01T00:00:00+00:00"
    second["settled_at"] = "2000-01-01T00:00:00+00:00"

    one = canonicalize_formal_records([first, second])
    two = canonicalize_formal_records([second, first])

    assert [row["prediction_id"] for row in one["records"]] == ["P-TIE-B"]
    assert [row["prediction_id"] for row in two["records"]] == ["P-TIE-B"]


def test_after_kickoff_version_is_not_formally_settled(tmp_path):
    after = same_match_record("P-AFTER", "2026-08-13T03:00:01+08:00")
    out = settle_records(
        [after],
        now=datetime(2026, 8, 14, 12, 0, tzinfo=TZ),
        result_fetcher=lambda *_: pytest.fail("after-kickoff record must not be fetched"),
        prospective_root=tmp_path,
    )

    assert out["formal_samples_added"] == 0
    assert out["canonical_formal_match_count"] == 0
    assert out["canonical_formal_excluded_count"] == 0


def test_historical_ledger_row_is_untouched_while_new_latest_is_added(tmp_path):
    earlier = same_match_record("P-HISTORICAL", "2026-08-12T12:00:00+08:00")
    latest = same_match_record("P-NEW-LATEST", "2026-08-13T02:30:00+08:00")
    kwargs = {
        "now": datetime(2026, 8, 14, 12, 0, tzinfo=TZ),
        "result_fetcher": lambda *_: result(match_key="FBOS-SAME-MATCH"),
        "prospective_root": tmp_path,
    }
    settle_records([earlier], **kwargs)
    before = (tmp_path / "ledger.jsonl").read_bytes().splitlines()[0]

    out = settle_records([earlier, latest], **kwargs)

    rows = (tmp_path / "ledger.jsonl").read_bytes().splitlines()
    assert rows[0] == before
    assert len(rows) == 2
    assert out["formal_samples_added"] == 1
    assert out["formal_prospective_raw_total"] == 2
    assert out["formal_prospective_total"] == 1
    assert out["formal_prospective_superseded_total"] == 1
    summary = json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))
    assert summary["formal_sample_count_total"] == 1
    assert summary["formal_sample_count_total_raw"] == 2
    assert summary["formal_ledger_raw_record_count"] == 2
    assert summary["formal_ledger_canonical_match_count"] == 1
    assert summary["formal_ledger_superseded_historical_version_count"] == 1


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
