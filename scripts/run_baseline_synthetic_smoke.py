#!/usr/bin/env python3
"""Run the complete Phase 1 synthetic benchmark smoke flow."""

from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path
from typing import Any

from automatic_model_core import build_automatic_model
from baseline_production import run_benchmark_for_frozen_prediction, settle_benchmark_for_verified_result
from baseline_settlement import aggregate_settlements
from model_governance import (
    build_deterministic_model_input_snapshot,
    build_prediction_record,
    freeze_prediction,
    load_config,
    load_input_snapshot,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "model_benchmark"
DEFAULT_OUTPUT_ROOT = ROOT / "artifacts" / "model-benchmark-phase1" / "synthetic_smoke"


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"fixture must be an object: {path}")
    return value


def _write_once(document: dict[str, Any], path: Path) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    try:
        with path.open("x", encoding="utf-8") as handle:
            handle.write(json.dumps(document, ensure_ascii=False, indent=2) + "\n")
        return {"status": "created", "path": str(path)}
    except FileExistsError:
        existing = _load(path)
        current = json.dumps(existing, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        if current != serialized:
            raise RuntimeError(f"synthetic smoke output conflict: {path}")
        return {"status": "existing", "path": str(path)}


def _phase0_context() -> dict[str, Any]:
    form = {
        "home_home": {"matches": 10, "goals_for": 20, "goals_against": 8},
        "away_away": {"matches": 10, "goals_for": 15, "goals_against": 10},
        "home_overall": {"matches": 10, "goals_for": 12, "goals_against": 13},
        "away_overall": {"matches": 10, "goals_for": 10, "goals_against": 9},
    }
    deep = {
        "fetched_at": "2026-08-10T19:29:00+08:00",
        "shuju": {"recent_form": deepcopy(form)},
        "ouzhi": {"bookmakers": [
            {"name": "Bet365", "spf_current": {"home": 2.4, "draw": 3.4, "away": 3.0}},
            {"name": "Pinnacle", "spf_current": {"home": 2.7, "draw": 3.4, "away": 2.8}},
        ]},
        "daxiao": {"companies": [{"name": "Totals-A", "current_line": 2.5}]},
        "source_provider": "500_deep",
    }
    return {
        "request": {"match_id": "phase1.1-synthetic-001"},
        "selected_workspace_match": {
            "id": "phase1.1-synthetic-001",
            "home": "Test Home",
            "away": "Test Away",
        },
        "source_snapshots": {"500_deep": {"snapshots": [deep]}},
        "official_market_baseline": {"fair_probabilities": {"home": 0.4, "draw": 0.3, "away": 0.3}},
        "checkpoint_features": {
            "snapshot_count": 1,
            "latest_captured_at": "2026-08-10T19:29:00+08:00",
        },
        "prematch_fundamentals": {"recent_form": deepcopy(form)},
        "model_calibration": {"active": False},
        "prediction_created_at": "2026-08-10T19:31:00+08:00",
    }


def _freeze_phase0_champion(output_root: Path) -> tuple[dict[str, Any], Path, Path, dict[str, Any]]:
    config = load_config()
    checkpoint = {
        "stage": "T-30M",
        "scheduled_at": "2026-08-10T19:30:00+08:00",
        "captured_at": "2026-08-10T19:30:42+08:00",
        "target_minutes_before": 30,
        "actual_minutes_before": 29.3,
        "capture_quality": "on_time",
    }
    input_snapshot = build_deterministic_model_input_snapshot(
        _phase0_context(),
        manifest_ref="data/fetch_runs/test/phase1.1-synthetic-manifest.json",
    )
    model_result = build_automatic_model(input_snapshot["projection"])
    model = model_result["model"]
    payload = {
        "report": {
            "model_version": config["champion"]["release_version"],
            "analysis_timestamp": checkpoint["captured_at"],
            "snapshot_timestamp": checkpoint["captured_at"],
            "market_checkpoint": checkpoint,
        },
        "match": {
            "canonical_match_id": "phase1.1-synthetic-001",
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
    record = build_prediction_record(payload, commit_sha="phase1.1-synthetic-sha", repository_root=ROOT)
    phase0_predictions = output_root / "phase0" / "predictions"
    input_root = output_root / "phase0" / "input_snapshots"
    frozen = freeze_prediction(record, phase0_predictions, input_snapshot_root=input_root)
    frozen_record = frozen["record"]
    load_input_snapshot(frozen_record, input_root)
    return frozen_record, input_root, phase0_predictions, checkpoint


def run_synthetic_smoke(
    *,
    fixture_root: Path = DEFAULT_FIXTURE_ROOT,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
) -> dict[str, Any]:
    fixture_root = Path(fixture_root)
    output_root = Path(output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    frozen_record, input_root, _, checkpoint = _freeze_phase0_champion(output_root)
    actual_fixture = _load(fixture_root / "synthetic_result.json")
    actual = {
        "result_90m": f"{actual_fixture.get('home_goals', 2)}-{actual_fixture.get('away_goals', 1)}",
        "scope": "regulation_90m_plus_stoppage",
        "verified_at": "2026-08-10T22:00:00+08:00",
        "synthetic": True,
    }
    benchmark = run_benchmark_for_frozen_prediction(
        frozen_record,
        benchmark_scope="prospective",
        production_new_freeze=True,
        checkpoint_metadata=frozen_record.get("checkpoint_metadata") or checkpoint,
        snapshot_root=input_root,
        prediction_root=output_root / "predictions",
        repository_root=ROOT,
        synthetic=True,
    )
    comparison = benchmark.get("comparison") or {}
    if comparison.get("comparison_status") != "complete":
        raise RuntimeError(f"synthetic comparison is not complete: {comparison.get('status_reason')}")
    prediction_write = {"status": benchmark["benchmark_status"], "path": Path(benchmark["prediction_path"])}

    report = {"model_governance": {"benchmark_comparison_id": comparison["comparison_id"]}}
    settlement_result = settle_benchmark_for_verified_result(
        report,
        actual,
        prediction_root=output_root / "predictions",
        settlement_root=output_root / "settlements",
    )
    settlement = settlement_result["settlement"]
    settlement_write = {
        "status": settlement_result["status"],
        "path": Path(settlement_result["settlement_path"]),
    }
    metrics_document = {
        "synthetic": True,
        "excluded_from_formal_metrics": True,
        "comparison_id": comparison["comparison_id"],
        "metrics": deepcopy(settlement["metrics"]),
    }
    metrics_write = _write_once(
        metrics_document,
        output_root / "summaries" / f"{comparison['comparison_id']}-synthetic-metrics.json",
    )
    formal_summary = aggregate_settlements([settlement])
    summary_write = _write_once(
        formal_summary,
        output_root / "summaries" / f"{comparison['comparison_id']}-synthetic-summary.json",
    )
    manifest = {
        "synthetic": True,
        "excluded_from_formal_metrics": True,
        "comparison_status": comparison["comparison_status"],
        "comparison_id": comparison["comparison_id"],
        "prediction_path": str(prediction_write["path"]),
        "settlement_path": str(settlement_write["path"]),
        "metrics_path": metrics_write["path"],
        "summary_path": summary_write["path"],
        "formal_summary": formal_summary,
    }
    manifest_write = _write_once(manifest, output_root / "synthetic_manifest.json")
    writes = [
        {"status": write["status"], "path": str(write["path"])}
        for write in (prediction_write, settlement_write, metrics_write, summary_write, manifest_write)
    ]
    return {
        "comparison": comparison,
        "settlement": settlement,
        "metrics": metrics_document,
        "formal_summary": formal_summary,
        "writes": writes,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture-root", type=Path, default=DEFAULT_FIXTURE_ROOT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    args = parser.parse_args()
    result = run_synthetic_smoke(fixture_root=args.fixture_root, output_root=args.output_root)
    print(json.dumps({
        "comparison_id": result["comparison"]["comparison_id"],
        "comparison_status": result["comparison"]["comparison_status"],
        "synthetic": result["settlement"]["synthetic"],
        "excluded_from_formal_metrics": result["settlement"]["excluded_from_formal_metrics"],
        "writes": result["writes"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
