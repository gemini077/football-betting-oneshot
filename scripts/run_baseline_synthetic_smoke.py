#!/usr/bin/env python3
"""Run the complete Phase 1 synthetic benchmark smoke flow."""

from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path
from typing import Any

from baseline_settlement import aggregate_settlements, freeze_settlement, settle_comparison
from baseline_shadow_runner import build_comparison, freeze_comparison


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


def run_synthetic_smoke(
    *,
    fixture_root: Path = DEFAULT_FIXTURE_ROOT,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
) -> dict[str, Any]:
    fixture_root = Path(fixture_root)
    output_root = Path(output_root)
    snapshot = _load(fixture_root / "synthetic_snapshot.json")
    champion = _load(fixture_root / "synthetic_champion.json")
    actual = _load(fixture_root / "synthetic_result.json")
    snapshot["synthetic"] = True

    comparison = build_comparison(snapshot, champion, benchmark_scope="prospective")
    if comparison["comparison_status"] != "complete":
        raise RuntimeError(f"synthetic comparison is not complete: {comparison['status_reason']}")
    prediction_write = freeze_comparison(comparison, output_root / "predictions")

    settlement = settle_comparison(comparison, actual)
    settlement_write = freeze_settlement(settlement, output_root / "settlements")
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
