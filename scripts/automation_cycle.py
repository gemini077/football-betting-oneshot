#!/usr/bin/env python3
"""Run one unattended Football Prediction Day maintenance cycle."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
SHANGHAI = ZoneInfo("Asia/Shanghai")
RUNTIME_PATH = ROOT / "data" / "product_runtime" / "latest_cycle.json"


def run(command: list[str], *, optional: bool = False) -> dict:
    """Run a local CLI and return a bounded JSON summary."""
    try:
        completed = subprocess.run(
            command,
            cwd=ROOT,
            text=True,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=360,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        if not optional:
            raise RuntimeError(str(error)) from error
        return {"returncode": 1, "error": f"{type(error).__name__}: {error}"}
    output = completed.stdout.strip()
    try:
        payload = json.loads(output) if output else {}
    except json.JSONDecodeError:
        payload = {"output": output[-2000:]}
    if not isinstance(payload, dict):
        payload = {"output": payload}
    payload["returncode"] = completed.returncode
    if completed.stderr.strip():
        payload["stderr"] = completed.stderr.strip()[-2000:]
    if completed.returncode and not optional:
        raise RuntimeError(completed.stderr or completed.stdout or f"command failed: {command}")
    return payload


def _summary(payload: dict) -> dict:
    """Keep runtime health useful without copying paths or large ledgers."""
    allowed = {
        "status", "refresh_status", "fixture_count", "match_count", "job_count",
        "frozen", "pending", "insufficient_data", "prediction_failed", "missed_prematch",
        "formal_samples_added", "formal_prospective_total", "results_found", "pending_results",
        "pilot_excluded_settled", "failure_reasons", "error", "output",
    }
    return {key: value for key, value in payload.items() if key in allowed}


def _step(name: str, command: list[str], *, optional: bool, executor=None) -> dict:
    executor = executor or run
    try:
        payload = executor(command, optional=optional)
    except Exception as error:  # the cycle records the failure and keeps projection alive
        return {
            "status": "FAILED" if not optional else "DEGRADED",
            "returncode": 1,
            "summary": {"error": f"{type(error).__name__}: {error}"},
            "command": command,
        }
    code = int(payload.get("returncode") or 0)
    return {
        "status": "SUCCESS" if code == 0 else "FAILED" if not optional else "DEGRADED",
        "returncode": code,
        "summary": _summary(payload),
        "command": command,
    }


def _group(name: str, commands: list[list[str]], *, optional: bool, executor=None) -> dict:
    executor = executor or run
    results = [_step(f"{name}_{index}", command, optional=optional, executor=executor) for index, command in enumerate(commands, 1)]
    failed = [row for row in results if row["returncode"] != 0]
    return {
        "status": "SUCCESS" if not failed else "DEGRADED" if optional else "FAILED",
        "returncode": 0 if not failed else 1,
        "summary": [{"step": index, "status": row["status"], **row["summary"]} for index, row in enumerate(results, 1)],
        "command": [part for command in commands for part in command],
    }


def _overall_status(steps: dict[str, dict]) -> str:
    if any(steps.get(name, {}).get("status") == "FAILED" for name in ("dashboard", "site")):
        return "FAILED"
    if any(value.get("status") not in {"SUCCESS", "SKIPPED"} for value in steps.values()):
        return "DEGRADED"
    return "HEALTHY"


def _write_runtime(path: Path, *, business_date: str, started_at: str, finished_at: str | None, steps: dict[str, dict]) -> dict:
    payload = {
        "schema_version": "1.0",
        "started_at": started_at,
        "finished_at": finished_at,
        "business_date": business_date,
        "steps": steps,
        "overall_status": _overall_status(steps),
        "failed_steps": [name for name, value in steps.items() if value.get("status") not in {"SUCCESS", "SKIPPED"}],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


def cycle(
    business_date: str,
    *,
    runtime_path: Path = RUNTIME_PATH,
    now: datetime | None = None,
) -> dict:
    python = sys.executable
    started = (now or datetime.now(SHANGHAI)).isoformat()
    steps: dict[str, dict] = {}

    steps["universe"] = _step("universe", [
        python, "scripts/daily_schedule_workspace.py", "--date", business_date,
        "--no-cache", "--fetch-only",
    ], optional=True)
    _write_runtime(Path(runtime_path), business_date=business_date, started_at=started, finished_at=None, steps=steps)

    steps["base_jobs"] = _step("base_jobs", [
        python, "scripts/base_prediction_jobs.py", "--date", business_date,
    ], optional=True)
    steps["base_prediction"] = _step("base_prediction", [
        python, "scripts/base_prediction_runner.py", "--date", business_date,
    ], optional=True)
    steps["postmatch"] = _group("postmatch", [
        [python, "scripts/sync_result_schedules.py", "--date", business_date],
        [python, "scripts/postmatch_result.py"],
        [python, "scripts/automatic_postmatch_review.py"],
        [python, "scripts/postmatch_dashboard.py"],
    ], optional=True)
    steps["prospective"] = _step("prospective", [
        python, "scripts/prospective_settlement.py", "--date", business_date,
    ], optional=True)
    _write_runtime(Path(runtime_path), business_date=business_date, started_at=started, finished_at=None, steps=steps)

    steps["dashboard"] = _step("dashboard", [
        python, "scripts/prediction_dashboard.py", "--date", business_date,
    ], optional=False)
    steps["workspace"] = _step("workspace", [
        python, "scripts/match_workspace.py", "--date", business_date,
    ], optional=True)
    steps["site"] = _step("site", [python, "scripts/build_public_site.py"], optional=False)
    finished = (now or datetime.now(SHANGHAI)).isoformat()
    _write_runtime(Path(runtime_path), business_date=business_date, started_at=started, finished_at=finished, steps=steps)

    # Refresh the projection after the final health state is known, then copy it
    # into the static site.  This keeps the banner from showing a stale RUNNING
    # state after a successful unattended cycle.
    steps["dashboard"] = _step("dashboard_refresh", [
        python, "scripts/prediction_dashboard.py", "--date", business_date,
    ], optional=False)
    steps["site"] = _step("site_refresh", [python, "scripts/build_public_site.py"], optional=False)
    finished = (now or datetime.now(SHANGHAI)).isoformat()
    return _write_runtime(Path(runtime_path), business_date=business_date, started_at=started, finished_at=finished, steps=steps)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date")
    parser.add_argument("--runtime-path", type=Path, default=RUNTIME_PATH)
    args = parser.parse_args()
    business_date = args.date or datetime.now(SHANGHAI).date().isoformat()
    payload = cycle(business_date, runtime_path=args.runtime_path)
    print(json.dumps(payload, ensure_ascii=False))
    return 1 if payload.get("overall_status") == "FAILED" else 0


if __name__ == "__main__":
    raise SystemExit(main())
