#!/usr/bin/env python3
"""Read-only health summary for the prospective benchmark ledgers."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from baseline_settlement import aggregate_settlements


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BENCHMARK_ROOT = ROOT / "data" / "model_benchmarks"
HEALTH_VERSION = "benchmark_health.v1"
PRODUCTION_ORIGIN = "production_new_freeze"


def _load_json_records(directory: Path) -> tuple[list[tuple[Path, dict[str, Any]]], int]:
    """Load only top-level JSON ledger entries and count unreadable entries."""
    if not directory.is_dir():
        return [], 0
    records: list[tuple[Path, dict[str, Any]]] = []
    errors = 0
    for path in sorted(directory.glob("*.json")):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            errors += 1
            continue
        if not isinstance(value, dict):
            errors += 1
            continue
        records.append((path, value))
    return records, errors


def _read_production_state(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    start = value.get("phase1_production_start") if isinstance(value, dict) else None
    return start if isinstance(start, dict) else {}


def _production_scope(row: dict[str, Any]) -> bool:
    return (
        row.get("benchmark_scope") == "prospective"
        and row.get("prospective_origin") == PRODUCTION_ORIGIN
        and row.get("synthetic") is not True
    )


def _formal_candidate(row: dict[str, Any]) -> bool:
    return (
        _production_scope(row)
        and row.get("comparison_status") == "complete"
        and row.get("same_snapshot") is True
        and row.get("excluded_from_formal_metrics") is False
    )


def _has_benchmark_error(row: dict[str, Any]) -> bool:
    if row.get("benchmark_error") is True:
        return True
    status = str(row.get("benchmark_status") or "").casefold()
    if status in {"error", "failed", "failure"}:
        return True
    return _production_scope(row) and row.get("comparison_status") not in {
        "complete",
        "incomplete",
        "invalid_snapshot_mismatch",
    }


def _timestamp_value(row: dict[str, Any], path: Path, field: str) -> str:
    value = row.get(field)
    if isinstance(value, str) and value.strip():
        return value
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat().replace("+00:00", "Z")
    except OSError:
        return ""


def _timestamp_sort_key(value: str) -> tuple[int, str]:
    if not value:
        return (0, "")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return (1, parsed.astimezone(timezone.utc).isoformat())
    except ValueError:
        return (1, value)


def _latest_timestamp(records: list[tuple[Path, dict[str, Any]]], field: str) -> str | None:
    values = [_timestamp_value(row, path, field) for path, row in records]
    values = [value for value in values if value]
    return max(values, key=_timestamp_sort_key) if values else None


def build_health_summary(
    *,
    benchmark_root: Path = DEFAULT_BENCHMARK_ROOT,
    production_state_path: Path | None = None,
) -> dict[str, Any]:
    """Aggregate the existing benchmark ledger without creating predictions."""
    benchmark_root = Path(benchmark_root)
    production_state_path = Path(production_state_path or benchmark_root / "production_state.json")
    prediction_records, prediction_errors = _load_json_records(benchmark_root / "predictions")
    settlement_records, settlement_errors = _load_json_records(benchmark_root / "settlements")

    production_rows = [(path, row) for path, row in prediction_records if _production_scope(row)]
    formal_records = [(path, row) for path, row in production_rows if _formal_candidate(row)]
    formal_ids = {
        str(row.get("comparison_id"))
        for _, row in formal_records
        if row.get("comparison_id") not in (None, "")
    }
    formal_settlements = [
        (path, row)
        for path, row in settlement_records
        if str(row.get("comparison_id") or "") in formal_ids and _formal_candidate(row)
    ]

    primary_records = [
        row for _, row in formal_records
        if row.get("cohort") == "primary" and row.get("primary_benchmark_eligible") is True
    ]
    secondary_records = [row for _, row in formal_records if row.get("cohort") == "secondary"]
    settled_rows = [row for _, row in formal_settlements]
    primary_aggregate = aggregate_settlements(settled_rows, cohort="primary")
    paired_model = primary_aggregate.get("paired_model_distribution") or {}

    errors = prediction_errors + settlement_errors
    errors += sum(_has_benchmark_error(row) for _, row in prediction_records)
    errors += sum(_has_benchmark_error(row) for _, row in settlement_records)
    state = _read_production_state(production_state_path)

    return {
        "benchmark_health_version": HEALTH_VERSION,
        "production_start_sha": str(state.get("merge_sha") or ""),
        "production_start_at": str(state.get("merged_at") or ""),
        "prospective_comparisons": len(formal_ids),
        "settled_comparisons": len({str(row.get("comparison_id")) for row in settled_rows}),
        "primary_t30m": len(primary_records),
        "secondary": len(secondary_records),
        "paired_3way_1x2": int((primary_aggregate.get("paired_3way_1x2") or {}).get("n") or 0),
        "paired_simple_vs_champion": int((paired_model.get("availability") or {}).get("n") or 0),
        "market_unavailable": sum(
            row.get("market_evaluable") is not True for _, row in formal_records
        ),
        "simple_unavailable": sum(
            row.get("simple_evaluable") is not True for _, row in formal_records
        ),
        "benchmark_errors": errors,
        "snapshot_mismatches": sum(
            row.get("comparison_status") == "invalid_snapshot_mismatch" or row.get("same_snapshot") is False
            for _, row in production_rows
        ),
        "incomplete_comparisons": sum(
            row.get("comparison_status") == "incomplete" for _, row in production_rows
        ),
        "last_benchmark_created_at": _latest_timestamp(formal_records, "created_at"),
        "last_benchmark_settled_at": _latest_timestamp(formal_settlements, "settled_at"),
    }


def write_health_summary(summary: dict[str, Any], output_path: Path) -> Path:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=False) + "\n"
    if not output_path.is_file() or output_path.read_text(encoding="utf-8") != serialized:
        output_path.write_text(serialized, encoding="utf-8")
    return output_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--benchmark-root", type=Path, default=DEFAULT_BENCHMARK_ROOT)
    parser.add_argument("--production-state", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--no-write", action="store_true", help="print the derived summary without writing health.json")
    args = parser.parse_args(argv)

    benchmark_root = Path(args.benchmark_root)
    state_path = args.production_state or benchmark_root / "production_state.json"
    summary = build_health_summary(
        benchmark_root=benchmark_root,
        production_state_path=state_path,
    )
    output_path = args.output or benchmark_root / "health.json"
    if not args.no_write:
        write_health_summary(summary, output_path)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
