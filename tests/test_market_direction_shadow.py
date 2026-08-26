import copy
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

from baseline_production import (  # noqa: E402
    MARKET_DIRECTION_SHADOW_CANDIDATE_ID,
    _market_direction_candidate,
    run_market_direction_shadow_for_frozen_prediction,
    settle_market_direction_shadow_for_result,
)
from baseline_settlement import aggregate_settlements  # noqa: E402
from benchmark_health import build_health_summary  # noqa: E402
import scripts.base_prediction_runner as prediction_runner  # noqa: E402
from test_baseline_production_integration import frozen_phase0_prediction  # noqa: E402


KICKOFF = "2026-08-10T20:00:00+08:00"
PREMATCH = "2026-08-10T19:40:00+08:00"


def make_fixture(tmp_path):
    record, snapshot_root, _ = frozen_phase0_prediction(tmp_path)
    record["kickoff_at"] = KICKOFF
    return record, snapshot_root


def test_shadow_uses_same_snapshot_total_and_single_changed_variable(tmp_path):
    record, snapshot_root = make_fixture(tmp_path)
    result = run_market_direction_shadow_for_frozen_prediction(
        record,
        shadow_created_at=PREMATCH,
        snapshot_root=snapshot_root,
        prediction_root=tmp_path / "shadow_predictions",
        repository_root=ROOT,
    )

    assert result["status"] == "created"
    comparison = result["comparison"]
    candidate = comparison["predictors"]["market_direction_fusion_full_v1"]
    assert comparison["source_champion_prediction_id"] == record["prediction_id"]
    assert comparison["model_input_snapshot_ref"] == record["model_input_snapshot_ref"]
    assert comparison["canonical_model_input_sha256"] == record["canonical_model_input_sha256"]
    assert candidate["lambda_home"] + candidate["lambda_away"] == pytest.approx(record["lambda_home"] + record["lambda_away"])
    assert comparison["champion_total"] == pytest.approx(record["lambda_home"] + record["lambda_away"])
    assert comparison["changed_variables"] == ["market_direction_fusion"]
    assert comparison["challenger_declaration"]["changed_variables"] == ["market_direction_fusion"]
    assert comparison["challenger_declaration"]["promotion"] == "forbidden_without_separate_governance_review"
    assert candidate["changed_variables"] == ["market_direction_fusion"]
    assert comparison["prospective_shadow"] is True
    assert comparison["user_visible"] is False
    assert comparison["formal_eligible"] is False
    assert comparison["promotion_eligible"] is False
    assert comparison["excluded_from_formal_metrics"] is True
    assert comparison["cohort"] == "shadow"
    assert comparison["shadow_status"] == "complete"
    assert comparison["replay_details"]["parity"] == {"lambda_home": True, "lambda_away": True, "probabilities": True, "raw_score_top1": True}
    assert "actual_result" not in comparison
    assert "settlement" not in comparison
    assert candidate["score_matrix_complete"] is True
    assert len(candidate["score_matrix"]) > 10


def test_shadow_prediction_is_compact_and_keeps_only_candidate_matrix(tmp_path):
    record, snapshot_root = make_fixture(tmp_path)
    root = tmp_path / "shadow_predictions"
    result = run_market_direction_shadow_for_frozen_prediction(
        record,
        shadow_created_at=PREMATCH,
        snapshot_root=snapshot_root,
        prediction_root=root,
        repository_root=ROOT,
    )
    assert result["status"] == "created"
    path = next(root.glob("*.json"))
    payload = json.loads(path.read_text(encoding="utf-8"))

    # The measured pre-compaction fixture was 263,106 bytes.  One genuine
    # 13x13 candidate matrix plus refs/metadata measured 32,999 bytes;
    # 50 KB leaves bounded room for legitimate metadata without allowing
    # immutable snapshot or duplicated predictor payloads to return.
    assert path.stat().st_size <= 50_000
    forbidden_keys = {
        "benchmark_snapshot",
        "input_snapshot",
        "model_input",
        "source_snapshots",
        "score_probabilities",
        "shadow_candidate",
        "shadow_challenger",
        "market_reference",
        "simple_poisson",
    }

    def keys(value):
        if isinstance(value, dict):
            for key, child in value.items():
                yield key
                yield from keys(child)
        elif isinstance(value, list):
            for child in value:
                yield from keys(child)

    assert not forbidden_keys.intersection(keys(payload))
    assert payload["model_input_snapshot_ref"] == record["model_input_snapshot_ref"]
    assert payload["canonical_model_input_sha256"] == record["canonical_model_input_sha256"]
    assert payload["source_champion_prediction_ref"].endswith(".json")
    assert set(payload["predictors"]) == {"champion", "market_direction_fusion_full_v1"}
    candidate = payload["predictors"]["market_direction_fusion_full_v1"]
    assert candidate["score_matrix_complete"] is True
    assert len(candidate["score_matrix"]) == 169
    assert "score_probabilities" not in candidate


def test_shadow_is_strictly_prematch_and_already_started_does_not_capture(tmp_path):
    record, snapshot_root = make_fixture(tmp_path)
    root = tmp_path / "shadow_predictions"
    after = run_market_direction_shadow_for_frozen_prediction(
        record,
        shadow_created_at="2026-08-10T20:00:00+08:00",
        snapshot_root=snapshot_root,
        prediction_root=root,
        repository_root=ROOT,
    )
    naive = run_market_direction_shadow_for_frozen_prediction(
        record,
        shadow_created_at=datetime(2026, 8, 10, 19, 40),
        snapshot_root=snapshot_root,
        prediction_root=root,
        repository_root=ROOT,
    )
    assert after["status"] == "failed"
    assert after["reason"] == "shadow_not_strictly_prematch"
    assert naive["status"] == "failed"
    assert naive["reason"] == "shadow_created_at_not_timezone_aware"
    assert not root.exists()


def test_shadow_capture_is_idempotent_and_deterministic(tmp_path):
    record, snapshot_root = make_fixture(tmp_path)
    root_a = tmp_path / "shadow_a"
    first = run_market_direction_shadow_for_frozen_prediction(
        record,
        shadow_created_at=PREMATCH,
        snapshot_root=snapshot_root,
        prediction_root=root_a,
        repository_root=ROOT,
    )
    second = run_market_direction_shadow_for_frozen_prediction(
        record,
        shadow_created_at="2026-08-10T19:55:00+08:00",
        snapshot_root=snapshot_root,
        prediction_root=root_a,
        repository_root=ROOT,
    )
    root_b = tmp_path / "shadow_b"
    third = run_market_direction_shadow_for_frozen_prediction(
        record,
        shadow_created_at=PREMATCH,
        snapshot_root=snapshot_root,
        prediction_root=root_b,
        repository_root=ROOT,
    )
    assert first["status"] == "created"
    assert second["status"] == "existing"
    assert third["status"] == "created"
    assert len(list(root_a.glob("*.json"))) == 1
    assert first["comparison"] == third["comparison"]


def test_missing_market_fails_closed_without_changing_champion(tmp_path):
    record, snapshot_root = make_fixture(tmp_path)
    original = copy.deepcopy(record)
    snapshot = json.loads(next(snapshot_root.glob("*.json")).read_text(encoding="utf-8"))
    model_input = copy.deepcopy(snapshot["input"])
    model_input.pop("source_snapshots", None)
    model_input.pop("official_market_baseline", None)
    model_input.pop("market", None)
    candidate, reason, _ = _market_direction_candidate(record, {"model_input": model_input})
    assert candidate is None
    assert reason in {"champion_replay_no_model", "market_probabilities_missing_from_frozen_snapshot"}
    assert record == original


def test_shadow_settlement_is_separate_from_formal_aggregate_and_is_repeatable(tmp_path):
    record, snapshot_root = make_fixture(tmp_path)
    prediction_root = tmp_path / "shadow_predictions"
    settlement_root = tmp_path / "shadow_settlements"
    captured = run_market_direction_shadow_for_frozen_prediction(
        record,
        shadow_created_at=PREMATCH,
        snapshot_root=snapshot_root,
        prediction_root=prediction_root,
        repository_root=ROOT,
    )
    settled = settle_market_direction_shadow_for_result(
        record,
        {"home_score_90m": 4, "away_score_90m": 1},
        prediction_root=prediction_root,
        settlement_root=settlement_root,
        settled_at="2026-08-10T22:00:00+08:00",
    )
    repeated = settle_market_direction_shadow_for_result(
        record,
        {"home_score_90m": 4, "away_score_90m": 1},
        prediction_root=prediction_root,
        settlement_root=settlement_root,
        settled_at="2026-08-10T22:00:00+08:00",
    )
    assert captured["status"] == "created"
    assert settled["status"] == "created"
    assert repeated["status"] == "existing"
    settlement = settled["settlement"]
    assert settlement["excluded_from_formal_metrics"] is True
    assert settlement["prospective_shadow"] is True
    assert set(settlement["metrics"]) == {"champion", "market_direction_fusion_full_v1"}
    candidate_metrics = settlement["metrics"]["market_direction_fusion_full_v1"]
    assert candidate_metrics["actual_score_nll"] is not None
    assert candidate_metrics["total_goals_nll"] is not None
    assert settlement["metrics"]["champion"]["actual_score_nll"] is None
    summary = aggregate_settlements([settlement])
    assert summary["formal_records"] == 0
    shadow = summary["shadow_candidate_vs_champion"]
    assert shadow["n"] == 1
    assert shadow["metrics"]["brier"]["status"] == "supported"
    assert shadow["metrics"]["macro_ece"]["status"] == "supported"
    assert shadow["metrics"]["exact_score_nll"]["status"] == "unsupported"
    assert shadow["metrics"]["total_nll"]["status"] == "unsupported"
    assert shadow["groups"]["high_score_total_ge_4"]["n"] == 1
    assert shadow["groups"]["high_margin_abs_ge_3"]["n"] == 1


def test_shadow_candidate_id_is_fixed():
    assert MARKET_DIRECTION_SHADOW_CANDIDATE_ID == "market-direction-fusion-full-v1"


def test_runner_shadow_failure_isolated_from_formal_record(tmp_path, monkeypatch):
    record, snapshot_root = make_fixture(tmp_path)
    original = copy.deepcopy(record)

    def fail_shadow(*args, **kwargs):
        raise RuntimeError("candidate failure")

    monkeypatch.setattr("baseline_production.run_market_direction_shadow_for_frozen_prediction", fail_shadow)
    result = prediction_runner._capture_market_direction_shadow(
        record,
        input_snapshot_root=snapshot_root,
        shadow_prediction_root=tmp_path / "shadow_predictions",
    )
    assert result["status"] == "failed"
    assert result["reason"].startswith("shadow_exception:RuntimeError:")
    assert record == original
    assert not (tmp_path / "shadow_predictions").exists()


def test_runner_uses_capture_wall_clock_and_fails_after_kickoff(tmp_path, monkeypatch):
    record, snapshot_root = make_fixture(tmp_path)
    actual_capture = datetime(2026, 8, 10, 20, 1, tzinfo=timezone.utc)
    monkeypatch.setattr(prediction_runner, "_utc_now", lambda: actual_capture)

    result = prediction_runner._capture_market_direction_shadow(
        record,
        input_snapshot_root=snapshot_root,
        shadow_prediction_root=tmp_path / "shadow_predictions",
    )

    assert result["status"] == "failed"
    assert result["reason"] == "shadow_not_strictly_prematch"
    assert not (tmp_path / "shadow_predictions").exists()


def test_shadow_timestamp_is_after_champion_times_and_before_kickoff(tmp_path, monkeypatch):
    record, snapshot_root = make_fixture(tmp_path)
    record["prediction_created_at"] = "2026-08-10T19:31:00+08:00"
    record["freeze_created_at"] = "2026-08-10T19:35:00+08:00"
    actual_capture = datetime(2026, 8, 10, 11, 40, tzinfo=timezone.utc)
    monkeypatch.setattr(prediction_runner, "_utc_now", lambda: actual_capture)

    result = prediction_runner._capture_market_direction_shadow(
        record,
        input_snapshot_root=snapshot_root,
        shadow_prediction_root=tmp_path / "shadow_predictions",
    )

    assert result["status"] == "created"
    shadow_created = datetime.fromisoformat(result["comparison"]["shadow_created_at"])
    prediction_created = datetime.fromisoformat(record["prediction_created_at"])
    freeze_created = datetime.fromisoformat(record["freeze_created_at"])
    kickoff = datetime.fromisoformat(record["kickoff_at"])
    assert shadow_created >= prediction_created
    assert shadow_created >= freeze_created
    assert shadow_created < kickoff


def test_backdated_shadow_is_not_settled_or_added_to_metrics(tmp_path):
    record, snapshot_root = make_fixture(tmp_path)
    prediction_root = tmp_path / "shadow_predictions"
    settlement_root = tmp_path / "shadow_settlements"
    captured = run_market_direction_shadow_for_frozen_prediction(
        record,
        shadow_created_at=PREMATCH,
        snapshot_root=snapshot_root,
        prediction_root=prediction_root,
        repository_root=ROOT,
    )
    assert captured["status"] == "created"

    record["prediction_created_at"] = "2026-08-10T19:45:00+08:00"
    record["freeze_created_at"] = "2026-08-10T19:50:00+08:00"
    settled = settle_market_direction_shadow_for_result(
        record,
        {"home_score_90m": 2, "away_score_90m": 1},
        prediction_root=prediction_root,
        settlement_root=settlement_root,
        settled_at="2026-08-10T22:00:00+08:00",
        repository_root=ROOT,
    )

    assert settled["status"] == "failed"
    assert settled["reason"] == "shadow_audit_invalid_prematch_time"
    assert not settlement_root.exists()


def test_deploy_pages_persists_only_shadow_benchmark_directories():
    workflow = (ROOT / ".github" / "workflows" / "deploy-pages.yml").read_text(encoding="utf-8")
    path_lines = [line for line in workflow.splitlines() if "paths=(" in line]
    assert len(path_lines) == 1
    persisted_paths = path_lines[0]
    assert "data/model_benchmarks/predictions" in persisted_paths
    assert "data/model_benchmarks/settlements" in persisted_paths
    assert 'git add -A -- "${existing[@]}"' in workflow
    assert "data/model_benchmarks " not in persisted_paths
    assert "site/" not in persisted_paths
    assert "public/" not in persisted_paths


def test_shadow_origin_and_failure_do_not_enter_benchmark_health(tmp_path):
    record, snapshot_root = make_fixture(tmp_path)
    benchmark_root = tmp_path / "benchmarks"
    before = build_health_summary(benchmark_root=benchmark_root)
    captured = run_market_direction_shadow_for_frozen_prediction(
        record,
        shadow_created_at=PREMATCH,
        snapshot_root=snapshot_root,
        prediction_root=benchmark_root / "predictions",
        repository_root=ROOT,
    )
    settled = settle_market_direction_shadow_for_result(
        record,
        {"home_score_90m": 2, "away_score_90m": 1},
        prediction_root=benchmark_root / "predictions",
        settlement_root=benchmark_root / "settlements",
        settled_at="2026-08-10T22:00:00+08:00",
    )
    comparison = captured["comparison"]
    assert comparison["benchmark_scope"] == "prospective"
    assert comparison["prospective_origin"] == "prospective_shadow"
    assert comparison["shadow_scope"] == "prospective_shadow"
    assert comparison["excluded_from_formal_metrics"] is True
    assert "benchmark_error" not in comparison
    assert settled["settlement"]["benchmark_scope"] == "prospective"
    assert settled["settlement"]["prospective_origin"] == "prospective_shadow"

    failed = copy.deepcopy(comparison)
    failed["comparison_id"] = "failed-shadow"
    failed["shadow_status"] = "failed"
    failed["comparison_status"] = "shadow_failed"
    failed["shadow_failure_reason"] = "market_missing"
    failed.pop("benchmark_error", None)
    failed_settlement = copy.deepcopy(settled["settlement"])
    failed_settlement["comparison_id"] = "failed-shadow"
    failed_settlement["shadow_status"] = "failed"
    failed_settlement["comparison_status"] = "shadow_failed"
    failed_settlement.pop("benchmark_error", None)
    (benchmark_root / "predictions" / "failed-shadow.json").write_text(json.dumps(failed), encoding="utf-8")
    (benchmark_root / "settlements" / "failed-shadow.json").write_text(json.dumps(failed_settlement), encoding="utf-8")

    after = build_health_summary(benchmark_root=benchmark_root)
    assert after["prospective_comparisons"] == before["prospective_comparisons"] == 0
    assert after["settled_comparisons"] == before["settled_comparisons"] == 0
    assert after["benchmark_errors"] == before["benchmark_errors"] == 0
    assert after["snapshot_mismatches"] == before["snapshot_mismatches"] == 0
