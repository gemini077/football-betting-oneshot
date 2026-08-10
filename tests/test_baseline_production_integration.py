import copy
import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from automatic_model_core import build_automatic_model  # noqa: E402
from baseline_production import (  # noqa: E402
    BENCHMARK_SNAPSHOT_VERSION,
    build_benchmark_snapshot_from_frozen_prediction,
    run_benchmark_for_frozen_prediction,
    settle_benchmark_for_verified_result,
)
from model_baselines import build_market_reference, build_simple_poisson_baseline  # noqa: E402
import automatic_postmatch_review as postmatch_review  # noqa: E402
import generate_analysis_report as analysis_report  # noqa: E402
from model_governance import (  # noqa: E402
    build_deterministic_model_input_snapshot,
    build_prediction_record,
    freeze_prediction,
    load_config,
    load_input_snapshot,
    prediction_content_hash,
)


CHECKPOINT = {
    "stage": "T-30M",
    "scheduled_at": "2026-08-10T19:30:00+08:00",
    "captured_at": "2026-08-10T19:30:42+08:00",
    "target_minutes_before": 30,
    "actual_minutes_before": 29.3,
    "lateness_minutes": 0.7,
    "capture_quality": "on_time",
}


def phase0_context():
    recent_form = {
        "home_home": {"matches": 10, "goals_for": 20, "goals_against": 8},
        "away_away": {"matches": 10, "goals_for": 15, "goals_against": 10},
        "home_overall": {"matches": 10, "goals_for": 12, "goals_against": 13},
        "away_overall": {"matches": 10, "goals_for": 10, "goals_against": 9},
    }

    def deep(provider, duplicate_odds):
        return {
            "fetched_at": "2026-08-10T19:29:00+08:00",
            "shuju": {"recent_form": copy.deepcopy(recent_form)},
            "ouzhi": {
                "bookmakers": [
                    {"name": "Bet365", "spf_current": duplicate_odds},
                    {
                        "name": "Pinnacle" if provider == "nowscore" else "SBO",
                        "spf_current": {"home": 2.7, "draw": 3.4, "away": 2.8},
                    },
                ],
            },
            "source_provider": provider,
        }

    return {
        "request": {"match_id": "phase0-test-001"},
        "selected_workspace_match": {
            "id": "phase0-test-001",
            "home": "Test Home",
            "away": "Test Away",
        },
        "source_snapshots": {
            "nowscore": {
                "snapshots": [deep("nowscore", {"home": 2.4, "draw": 3.4, "away": 3.0})]
            },
            "500_deep": {
                "snapshots": [deep("500_deep", {"home": 2.1, "draw": 3.7, "away": 3.2})]
            },
        },
        "official_market_baseline": {
            "fair_probabilities": {"home": 0.4, "draw": 0.3, "away": 0.3},
        },
        "checkpoint_features": {"snapshot_count": 0},
        "prematch_fundamentals": {"recent_form": copy.deepcopy(recent_form)},
        "model_calibration": {"active": False},
        "prediction_created_at": "2026-08-10T19:31:00+08:00",
    }


def frozen_phase0_prediction(tmp_path):
    config = load_config()
    context = phase0_context()
    input_snapshot = build_deterministic_model_input_snapshot(
        context,
        manifest_ref="data/fetch_runs/test/manifest.json",
    )
    model_result = build_automatic_model(input_snapshot["projection"])
    model = model_result["model"]
    payload = {
        "report": {
            "model_version": config["champion"]["release_version"],
            "analysis_timestamp": CHECKPOINT["captured_at"],
            "snapshot_timestamp": CHECKPOINT["captured_at"],
            "market_checkpoint": copy.deepcopy(CHECKPOINT),
        },
        "match": {
            "canonical_match_id": "phase0-test-001",
            "home": "Test Home",
            "away": "Test Away",
            "kickoff_local": "2026-08-10T20:00:00+08:00",
        },
        "data_quality": {"missing": []},
        "model": {"method": config["champion"]["model_core_version"], **model},
        "decisions": {
            "data_grade": "A",
            "unique_primary_dimension": "home",
            "unique_score": (model.get("score_probabilities") or [{}])[0].get("score"),
        },
        "betting": {"candidates": []},
        "automation": {
            "prompt_version": config["versions"]["prompt_version"],
            "model_input_snapshot": input_snapshot,
        },
    }
    record = build_prediction_record(payload, commit_sha="phase1.1-test-sha", repository_root=ROOT)
    record_root = tmp_path / "predictions"
    snapshot_root = tmp_path / "input_snapshots"
    freeze_prediction(record, record_root, input_snapshot_root=snapshot_root)
    frozen = json.loads((record_root / f"{record['prediction_id']}.json").read_text(encoding="utf-8"))
    return frozen, snapshot_root, context


def test_adapter_uses_real_phase0_content_addressed_snapshot(tmp_path):
    record, snapshot_root, _ = frozen_phase0_prediction(tmp_path)

    benchmark_snapshot = build_benchmark_snapshot_from_frozen_prediction(
        record,
        checkpoint_metadata=record["checkpoint_metadata"],
        snapshot_root=snapshot_root,
        repository_root=ROOT,
    )

    frozen_document = load_input_snapshot(record, snapshot_root)
    assert benchmark_snapshot["benchmark_snapshot_version"] == BENCHMARK_SNAPSHOT_VERSION
    assert benchmark_snapshot["benchmark_snapshot_status"] == "valid"
    assert benchmark_snapshot["model_input"] == frozen_document["input"]
    assert benchmark_snapshot["canonical_model_input_sha256"] == record["canonical_model_input_sha256"]
    assert benchmark_snapshot["checkpoint_stage"] == "T-30M"
    assert benchmark_snapshot["checkpoint_target_at"] == CHECKPOINT["scheduled_at"]
    assert benchmark_snapshot["checkpoint_captured_at"] == CHECKPOINT["captured_at"]
    assert benchmark_snapshot["checkpoint_metadata"]["source"] == "prematch_market_monitor.checkpoint_meta"
    assert benchmark_snapshot["synthetic"] is False
    assert "market" not in benchmark_snapshot
    assert "recent_form" not in benchmark_snapshot


def test_unclassified_checkpoint_cannot_enter_primary_cohort(tmp_path):
    record, snapshot_root, _ = frozen_phase0_prediction(tmp_path)
    unclassified = copy.deepcopy(record)
    for field in ("checkpoint_stage", "checkpoint_target_at", "checkpoint_captured_at", "checkpoint_metadata"):
        unclassified.pop(field, None)

    benchmark_snapshot = build_benchmark_snapshot_from_frozen_prediction(
        unclassified,
        snapshot_root=snapshot_root,
        repository_root=ROOT,
    )

    assert benchmark_snapshot["checkpoint_stage"] == "unclassified"
    assert benchmark_snapshot["checkpoint_metadata"]["source"] == "unclassified"
    from baseline_shadow_runner import build_comparison

    comparison = build_comparison(benchmark_snapshot, unclassified)
    assert comparison["primary_benchmark_eligible"] is False
    assert comparison["cohort"] == "secondary"


def test_checkpoint_audit_metadata_does_not_change_champion_content_identity(tmp_path):
    record, _, _ = frozen_phase0_prediction(tmp_path)
    changed = copy.deepcopy(record)
    changed["checkpoint_stage"] = "T-2H"
    changed["checkpoint_target_at"] = "2026-08-10T18:00:00+08:00"
    changed["checkpoint_captured_at"] = "2026-08-10T18:00:10+08:00"
    changed["checkpoint_metadata"] = {"stage": "T-2H", "source": "prematch_market_monitor.checkpoint_meta"}

    assert changed["canonical_model_input_sha256"] == record["canonical_model_input_sha256"]
    assert changed["model_run_fingerprint"] == record["model_run_fingerprint"]
    assert prediction_content_hash(changed) == prediction_content_hash(record)


def test_adapter_hash_mismatch_is_invalid_and_cannot_continue(tmp_path):
    record, snapshot_root, _ = frozen_phase0_prediction(tmp_path)
    invalid = copy.deepcopy(record)
    invalid["canonical_model_input_sha256"] = "wrong-hash"

    result = build_benchmark_snapshot_from_frozen_prediction(
        invalid,
        checkpoint_metadata=record["checkpoint_metadata"],
        snapshot_root=snapshot_root,
        repository_root=ROOT,
    )

    assert result["benchmark_snapshot_status"] == "invalid"
    assert result["status_reason"]


def test_real_contract_baselines_read_nested_input_and_deduplicate_bookmakers(tmp_path):
    record, snapshot_root, _ = frozen_phase0_prediction(tmp_path)
    benchmark_snapshot = build_benchmark_snapshot_from_frozen_prediction(
        record,
        checkpoint_metadata=record["checkpoint_metadata"],
        snapshot_root=snapshot_root,
        repository_root=ROOT,
    )

    market = build_market_reference(benchmark_snapshot)
    simple = build_simple_poisson_baseline(benchmark_snapshot)

    assert market["status"] == "evaluable"
    assert market["market_bookmaker_count"] == 3
    bet365 = next(row for row in market["bookmakers"] if row["canonical_bookmaker_id"] == "bet365")
    assert bet365["source_provider"] == "nowscore"
    assert simple["status"] == "evaluable"
    assert simple["input_sources"] == {"home": "home_home", "away": "away_away"}
    assert simple["market_read"] is False
    assert simple["champion_read"] is False


def test_production_freeze_hook_creates_benchmark_without_champion_rerun(tmp_path, monkeypatch):
    record, snapshot_root, _ = frozen_phase0_prediction(tmp_path)
    import automatic_model_core

    monkeypatch.setattr(
        automatic_model_core,
        "build_automatic_model",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("Champion rerun")),
    )

    result = analysis_report.run_shadow_benchmark_after_freeze(
        record,
        {"record": record},
        project_root=ROOT,
        snapshot_root=snapshot_root,
        prediction_root=tmp_path / "benchmark_predictions",
    )

    assert result["benchmark_status"] == "created"
    assert result["benchmark_comparison_id"]
    assert (ROOT / result["benchmark_prediction_path"]).is_file()


def test_benchmark_shadow_failure_is_recorded_without_raising_report_gate(tmp_path, monkeypatch):
    record, _, _ = frozen_phase0_prediction(tmp_path)
    monkeypatch.setattr(
        analysis_report,
        "run_benchmark_for_frozen_prediction",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("adapter-corruption")),
    )

    result = analysis_report.run_shadow_benchmark_after_freeze(record, {"record": record})

    assert result["benchmark_status"] == "error"
    assert "adapter-corruption" in result["benchmark_error"]


def test_verified_regulation_result_triggers_idempotent_settlement(tmp_path):
    record, snapshot_root, _ = frozen_phase0_prediction(tmp_path)
    prediction_root = tmp_path / "benchmark_predictions"
    settlement_root = tmp_path / "benchmark_settlements"
    benchmark = run_benchmark_for_frozen_prediction(
        record,
        checkpoint_metadata=record["checkpoint_metadata"],
        snapshot_root=snapshot_root,
        prediction_root=prediction_root,
        repository_root=ROOT,
    )
    report = {
        "model_governance": {
            "benchmark_comparison_id": benchmark["comparison"]["comparison_id"],
        }
    }
    verified = {
        "result_90m": "2-1",
        "scope": "regulation_90m_plus_stoppage",
        "synthetic": True,
    }

    first = settle_benchmark_for_verified_result(
        report,
        verified,
        prediction_root=prediction_root,
        settlement_root=settlement_root,
    )
    second = settle_benchmark_for_verified_result(
        report,
        verified,
        prediction_root=prediction_root,
        settlement_root=settlement_root,
    )

    assert first["status"] == "created"
    assert second["status"] == "existing"
    assert first["settlement"]["actual_result"]["regulation_minutes"] == 90
    assert list(settlement_root.glob("*.json"))


def test_verified_extra_time_result_is_not_settled(tmp_path):
    record, snapshot_root, _ = frozen_phase0_prediction(tmp_path)
    prediction_root = tmp_path / "benchmark_predictions"
    benchmark = run_benchmark_for_frozen_prediction(
        record,
        checkpoint_metadata=record["checkpoint_metadata"],
        snapshot_root=snapshot_root,
        prediction_root=prediction_root,
        repository_root=ROOT,
    )
    result = settle_benchmark_for_verified_result(
        {"model_governance": {"benchmark_comparison_id": benchmark["comparison"]["comparison_id"]}},
        {"result_90m": "1-1", "scope": "extra_time_or_penalties"},
        prediction_root=prediction_root,
        settlement_root=tmp_path / "settlements",
    )
    assert result["status"] == "no_op"
    assert result["reason"] == "non_regulation_result_scope"


def test_production_postmatch_hook_settles_without_rewriting_report_history(tmp_path, monkeypatch):
    record, snapshot_root, _ = frozen_phase0_prediction(tmp_path)
    prediction_root = tmp_path / "benchmark_predictions"
    settlement_root = tmp_path / "benchmark_settlements"
    benchmark = run_benchmark_for_frozen_prediction(
        record,
        checkpoint_metadata=record["checkpoint_metadata"],
        snapshot_root=snapshot_root,
        prediction_root=prediction_root,
        repository_root=ROOT,
    )
    report_root = tmp_path / "reports"
    result_root = tmp_path / "results"
    schedule_root = tmp_path / "schedules"
    report_root.mkdir()
    result_root.mkdir()
    schedule_root.mkdir()
    report_path = report_root / "report.json"
    report_path.write_text(json.dumps({
        "model_governance": {
            "benchmark_comparison_id": benchmark["comparison"]["comparison_id"],
        }
    }), encoding="utf-8")
    result_path = result_root / "result.json"
    result_path.write_text(json.dumps({
        "result_90m": "2-1",
        "scope": "regulation_90m_plus_stoppage",
        "verified_at": "2026-08-10T22:00:00+08:00",
    }), encoding="utf-8")
    schedule_path = schedule_root / "phase0-test-001.json"
    schedule_path.write_text(json.dumps({
        "match_key": "phase0-test-001",
        "status": "result_verified",
        "result_90m": "2-1",
        "result_file": "results/result.json",
        "source_report": "reports/report.json",
        "home": "Test Home",
        "away": "Test Away",
    }), encoding="utf-8")

    monkeypatch.setattr(postmatch_review, "BASE_DIR", tmp_path)
    monkeypatch.setattr(postmatch_review, "build_review", lambda *_args: {"review": "synthetic"})
    outcomes = postmatch_review.generate_selected(
        [schedule_path],
        tmp_path / "reviews",
        datetime(2026, 8, 10, 23, tzinfo=ZoneInfo("Asia/Shanghai")),
        benchmark_prediction_root=prediction_root,
        benchmark_settlement_root=settlement_root,
    )

    updated_schedule = json.loads(schedule_path.read_text(encoding="utf-8"))
    assert outcomes[0]["status"] == "reviewed"
    assert updated_schedule["benchmark_settlement_status"] == "created"
    assert (settlement_root / f"{benchmark['comparison']['comparison_id']}.json").is_file()
