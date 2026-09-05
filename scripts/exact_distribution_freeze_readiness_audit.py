#!/usr/bin/env python3
"""Bounded, offline audit for the prediction-time Exact distribution freeze."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "exact_distribution" / "current_model_input.json"
PREDICTION_ROOT = ROOT / "data" / "model_governance" / "predictions"
AUDIT_CONTRACT_VERSION = "exact_distribution_freeze_readiness.v1"
DECISION_READY = "EXACT_DISTRIBUTION_FREEZE_READY"
DECISION_PARTIAL = "EXACT_DISTRIBUTION_FREEZE_PARTIAL"
DECISION_FAIL_CLOSED = "FAIL_CLOSED"
HISTORICAL_PREFIXES = (
    "data/model_governance/predictions/",
    "data/model_governance/input_snapshots/",
    "data/prospective/",
)


def _load_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _git(root: Path, *args: str) -> list[str]:
    try:
        completed = subprocess.run(
            ["git", *args], cwd=root, text=True, capture_output=True, check=True
        )
    except (OSError, subprocess.CalledProcessError):
        return []
    return [line.strip().replace("\\", "/") for line in completed.stdout.splitlines() if line.strip()]


def _historical_rewrite_count() -> tuple[int, list[str]]:
    changed = set(_git(ROOT, "diff", "--name-only"))
    changed.update(_git(ROOT, "diff", "--cached", "--name-only"))
    base = _git(ROOT, "rev-parse", "origin/main")
    if base:
        changed.update(_git(ROOT, "diff", "--name-only", f"{base[0]}...HEAD"))
    historical = sorted(
        path for path in changed if any(path.startswith(prefix) for prefix in HISTORICAL_PREFIXES)
    )
    return len(historical), historical


def _audit_legacy_records(limit: int) -> dict[str, Any]:
    files = sorted(
        PREDICTION_ROOT.glob("*.json"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    selected = files if limit <= 0 else files[:limit]
    authoritative = 0
    formal_champion = 0
    unreadable = 0
    for path in selected:
        record = _load_json(path)
        if record is None:
            unreadable += 1
            continue
        is_formal_champion = (
            record.get("model_role") == "champion"
            and record.get("model_formal_eligible") is True
            and record.get("formal_eligible") is True
        )
        formal_champion += int(is_formal_champion)
        if isinstance(record.get("exact_score_distribution"), dict):
            authoritative += 1
    return {
        "records_available": len(files),
        "records_scanned": len(selected),
        "formal_champion_records_scanned": formal_champion,
        "authoritative_exact_distribution_records_scanned": authoritative,
        "missing_formal_exact_authority_records_scanned": max(0, formal_champion - authoritative),
        "unreadable_records_scanned": unreadable,
        "formal_historical_full_support_truth": False,
        "historical_exact_metrics_scope": "RESEARCH_RECONSTRUCTED",
        "historical_rewrite_count": 0,
    }


def _probe_current_capture() -> dict[str, Any]:
    from automatic_model_core import build_automatic_model
    from exact_distribution import (
        EXACT_DISTRIBUTION_CELL_COUNT,
        EXACT_DISTRIBUTION_CONTRACT_VERSION,
        build_exact_distribution_contract,
        classify_frozen_exact_score,
        validate_exact_distribution_contract,
    )

    context = _load_json(FIXTURE) or {}
    result = build_automatic_model(context, include_exact_distribution=True)
    model = result.get("model") if isinstance(result, dict) else None
    state = result.get("exact_distribution_state") if isinstance(result, dict) else None
    if not isinstance(model, dict) or not isinstance(state, dict):
        return {
            "capture_contract_valid": False,
            "failure": "current fixture did not produce an exact distribution state",
        }
    identity = {
        "prediction_id": "AUDIT-PROBE",
        "model_role": "champion",
        "model_family": model.get("method"),
        "model_core_version": model.get("method"),
        "release_version": "audit-probe",
        "model_source_fingerprint": "audit-probe",
        "model_run_fingerprint": "audit-probe",
        "input_sha256": "audit-probe",
    }
    try:
        contract = build_exact_distribution_contract(state, model_identity=identity)
        validate_exact_distribution_contract(contract, expected_model_identity=identity)
    except ValueError as error:
        return {"capture_contract_valid": False, "failure": str(error)}
    cells = contract["cells"]
    tail_status = (contract.get("tail_diagnostic") or {}).get("status")
    probe_record = {**identity, "exact_score_distribution": contract}
    in_grid = classify_frozen_exact_score(probe_record, 0, 0)
    out_of_grid = classify_frozen_exact_score(probe_record, 13, 0)
    cell_by_score = {
        (cell["home_goals"], cell["away_goals"]): cell["probability"]
        for cell in cells
    }
    top_rows = model.get("score_probabilities") or []
    top_parity = all(
        isinstance(row, dict)
        and "-" in str(row.get("score") or "")
        and _rounded_probability(
            cell_by_score.get(tuple(int(part) for part in str(row["score"]).split("-", 1)))
        )
        == _rounded_probability(row.get("probability"))
        for row in top_rows[:5]
    )
    return {
        "capture_contract_valid": True,
        "contract_version": EXACT_DISTRIBUTION_CONTRACT_VERSION,
        "model_family": model.get("method"),
        "effective_matrix_cell_count": len(cells),
        "expected_frozen_cell_count": EXACT_DISTRIBUTION_CELL_COUNT,
        "max_home_goals": (contract.get("score_space") or {}).get("max_home_goals"),
        "max_away_goals": (contract.get("score_space") or {}).get("max_away_goals"),
        "finite_normalized_grid": (contract.get("score_space") or {}).get("representation") == "FINITE_NORMALIZED_GRID",
        "full_support": (contract.get("score_space") or {}).get("full_support"),
        "tail_diagnostic_status": tail_status,
        "formal_exact_log_score_on_frozen_cell": in_grid["FORMAL_EXACT_LOG_SCORE_ELIGIBLE"],
        "out_of_support_fail_closed": (
            out_of_grid["OUT_OF_EXPLICIT_SUPPORT"]
            and not out_of_grid["FORMAL_EXACT_LOG_SCORE_ELIGIBLE"]
            and out_of_grid["probability"] is None
        ),
        "top1_to_top5_parity": top_parity,
        "out_of_explicit_support_policy": (contract.get("score_space") or {}).get("out_of_support_policy"),
        "production_path": state.get("production_path"),
        "content_sha256": contract.get("content_sha256"),
    }


def _rounded_probability(value: Any) -> float | None:
    """Match the model's six-decimal display rows without changing the state."""

    try:
        return round(float(value), 6)
    except (TypeError, ValueError):
        return None


def audit(limit: int = 200) -> dict[str, Any]:
    legacy = _audit_legacy_records(limit)
    probe = _probe_current_capture()
    historical_rewrite_count, changed_historical_files = _historical_rewrite_count()
    legacy["historical_rewrite_count"] = historical_rewrite_count
    if (
        historical_rewrite_count
        or not probe.get("capture_contract_valid")
        or not probe.get("formal_exact_log_score_on_frozen_cell")
        or not probe.get("out_of_support_fail_closed")
        or not probe.get("top1_to_top5_parity")
    ):
        decision = DECISION_FAIL_CLOSED
    elif probe.get("tail_diagnostic_status") != "EXACT_TAIL_RESOLVED":
        decision = DECISION_PARTIAL
    else:
        decision = DECISION_READY
    return {
        "audit_contract_version": AUDIT_CONTRACT_VERSION,
        "network_used": False,
        "read_scope": [
            "data/model_governance/predictions/*.json (bounded latest sample)",
            "tests/fixtures/exact_distribution/current_model_input.json",
            "scripts/automatic_model_core.py effective matrix capture",
        ],
        "LEGACY_RECONSTRUCTION_COVERAGE": legacy,
        "PROSPECTIVE_CAPTURE_CAPABILITY": probe,
        "historical_rewrite_count": historical_rewrite_count,
        "changed_historical_files": changed_historical_files,
        "readiness_decision": decision,
        "decision_rule": "FAIL_CLOSED on capture/rewrite failure; PARTIAL when immutable finite grid is valid but exact infinite-support tail remains unresolved; READY only when both are resolved.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=200, help="latest frozen records to inspect; 0 means all")
    parser.add_argument("--output", type=Path, help="optional JSON output outside data stores")
    args = parser.parse_args()
    result = audit(args.limit)
    text = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
