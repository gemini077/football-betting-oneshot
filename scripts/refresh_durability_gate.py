#!/usr/bin/env python3
"""Classify whether a refresh produced a safe durable-data checkpoint."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


GENERATION_STEPS = ("universe", "base_jobs", "base_prediction", "dashboard")
NEXT_PREMATCH_STEPS = ("next_universe", "next_base_jobs", "next_base_prediction")
PUBLICATION_STEPS = ("site", "site_refresh")
ACTIVE_ARTIFACT_STATUSES = {"READY", "EMPTY_CONFIRMED"}


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _step_status(steps: dict[str, Any], name: str) -> str | None:
    value = steps.get(name)
    return value.get("status") if isinstance(value, dict) else None


def _artifacts_are_current(data_root: Path, business_date: str) -> bool:
    json_paths = (
        data_root / "prediction_universe" / f"{business_date}.json",
        data_root / "base_prediction_jobs" / f"{business_date}.json",
        data_root / "prediction_dashboard" / "latest.json",
    )
    payloads = [_read_json(path) for path in json_paths]
    dashboard_html = data_root / "prediction_dashboard" / "latest.html"
    if any(payload is None for payload in payloads) or not dashboard_html.is_file() or dashboard_html.stat().st_size <= 0:
        return False
    universe, jobs, dashboard = payloads
    if universe.get("business_date") != business_date or universe.get("status") not in ACTIVE_ARTIFACT_STATUSES:
        return False
    if jobs.get("business_date") != business_date or jobs.get("status") not in ACTIVE_ARTIFACT_STATUSES:
        return False
    return dashboard.get("business_date") == business_date


def classify(
    cycle_result: dict[str, Any],
    *,
    data_root: Path,
    cycle_outcome: str,
) -> dict[str, Any]:
    """Return a fail-closed durable-data decision for the current cycle only."""

    if cycle_outcome not in {"success", "failure"}:
        return {"ready": False, "reason": "CYCLE_OUTCOME_UNKNOWN"}
    business_date = cycle_result.get("business_date")
    steps = cycle_result.get("steps")
    if not isinstance(business_date, str) or not business_date or not isinstance(steps, dict):
        return {"ready": False, "reason": "CYCLE_RESULT_INVALID"}
    if any(_step_status(steps, name) != "SUCCESS" for name in GENERATION_STEPS):
        return {"ready": False, "reason": "UPSTREAM_GENERATION_NOT_COMPLETE"}
    if any(name in steps for name in NEXT_PREMATCH_STEPS):
        if any(_step_status(steps, name) != "SUCCESS" for name in NEXT_PREMATCH_STEPS):
            return {"ready": False, "reason": "NEXT_PREMATCH_GENERATION_NOT_COMPLETE"}

    publication_name = next((name for name in PUBLICATION_STEPS if name in steps), None)
    publication_status = _step_status(steps, publication_name) if publication_name else None
    if publication_status not in {"SUCCESS", "FAILED"}:
        return {"ready": False, "reason": "PUBLICATION_STEP_NOT_CLASSIFIED"}
    if cycle_outcome == "failure" and publication_status != "FAILED":
        return {"ready": False, "reason": "CYCLE_FAILURE_NOT_SITE_FAILURE"}
    if cycle_outcome == "success" and publication_status != "SUCCESS":
        return {"ready": False, "reason": "SUCCESS_CYCLE_PUBLICATION_MISMATCH"}
    if not _artifacts_are_current(Path(data_root), business_date):
        return {"ready": False, "reason": "GENERATED_ARTIFACT_MISSING_OR_STALE"}
    reason = "SITE_FAILURE_AFTER_COMPLETE_GENERATION" if publication_status == "FAILED" else "COMPLETE_GENERATION"
    return {"ready": True, "reason": reason, "business_date": business_date}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cycle-result", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    parser.add_argument("--cycle-outcome", required=True)
    parser.add_argument("--github-output", type=Path)
    args = parser.parse_args()
    cycle_result = _read_json(args.cycle_result) or {}
    result = classify(
        cycle_result,
        data_root=args.data_root,
        cycle_outcome=args.cycle_outcome,
    )
    if args.github_output:
        with args.github_output.open("a", encoding="utf-8", newline="\n") as output:
            output.write(f"ready={str(result['ready']).lower()}\n")
            output.write(f"reason={result['reason']}\n")
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
