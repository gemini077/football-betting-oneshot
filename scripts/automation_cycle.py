#!/usr/bin/env python3
"""Run one unattended Football Prediction Day maintenance cycle."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
SHANGHAI = ZoneInfo("Asia/Shanghai")
RUNTIME_PATH = ROOT / "data" / "product_runtime" / "latest_cycle.json"
PREDICTION_UNIVERSE_DIR = ROOT / "data" / "prediction_universe"
BASE_JOBS_DIR = ROOT / "data" / "base_prediction_jobs"


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
        "pilot_excluded_settled", "failure_reasons", "shadow_attempted", "shadow_created",
        "shadow_existing", "shadow_failed", "shadow_failure_reasons",
        "shadow_settlements_added", "shadow_settlements_existing", "shadow_settlement_failures",
        "shadow_failure_reasons", "error", "output",
        "target_date", "completed_count", "published_as_latest", "latest_only",
        "market_side_shadow_status", "paired_count", "challenger_abstain_count",
        "promotion_eligible_pairs", "excluded_non_promotion_pair_count",
        "verified_paired_count", "checkpoint_status", "early_stop_status",
        "latest_status", "result_files_scanned", "result_files_accepted",
        "result_files_rejected", "result_identity_conflicts", "result_identity_mismatches",
        "unmatched_pair_count", "auto_promote",
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


def _write_runtime(
    path: Path,
    *,
    business_date: str,
    started_at: str,
    finished_at: str | None,
    steps: dict[str, dict],
    carryover_business_dates: list[str] | None = None,
) -> dict:
    payload = {
        "schema_version": "1.0",
        "started_at": started_at,
        "finished_at": finished_at,
        "business_date": business_date,
        "carryover_business_dates": carryover_business_dates or [],
        "steps": steps,
        "overall_status": _overall_status(steps),
        "failed_steps": [name for name, value in steps.items() if value.get("status") not in {"SUCCESS", "SKIPPED"}],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


def active_business_dates(now: datetime | None = None) -> tuple[str, list[str]]:
    """Return today and the immediately prior Shanghai business date."""
    current = now or datetime.now(SHANGHAI)
    if current.tzinfo is None:
        current = current.replace(tzinfo=SHANGHAI)
    current_date = current.astimezone(SHANGHAI).date()
    return current_date.isoformat(), [(current_date - timedelta(days=1)).isoformat()]


def next_business_date(business_date: str) -> str:
    return (date.fromisoformat(business_date) + timedelta(days=1)).isoformat()


def _carryover_state(business_date: str) -> tuple[str, str]:
    """Check only saved state; never fetch or infer a prior-day Universe."""
    universe_path = PREDICTION_UNIVERSE_DIR / f"{business_date}.json"
    jobs_path = BASE_JOBS_DIR / f"{business_date}.json"
    if not universe_path.exists():
        return "SKIPPED", "UNIVERSE_NOT_FOUND"
    if not jobs_path.exists():
        return "SKIPPED", "BASE_JOBS_NOT_FOUND"
    try:
        universe = json.loads(universe_path.read_text(encoding="utf-8"))
        jobs = json.loads(jobs_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return "DEGRADED", f"CARRYOVER_STATE_INVALID: {error}"
    if universe.get("status") not in {"READY", "EMPTY_CONFIRMED"}:
        return "SKIPPED", "UNIVERSE_NOT_ACTIVE"
    job_count = jobs.get("job_count")
    if job_count is None:
        job_count = len(jobs.get("jobs") or [])
    if not job_count:
        return "SKIPPED", "NO_BASE_JOBS"
    return "READY", ""


def _carryover_marker(status: str, reason: str) -> dict:
    return {
        "status": status,
        "returncode": 0 if status == "SKIPPED" else 1,
        "summary": {"reason": reason},
    }


def _carryover_preparation(business_date: str) -> tuple[dict[str, dict], str]:
    state, reason = _carryover_state(business_date)
    names = (
        "carryover_base_jobs",
        "carryover_base_prediction",
        "carryover_result_schedule",
    )
    if state != "READY":
        status = "SKIPPED" if state == "SKIPPED" else "DEGRADED"
        return {name: _carryover_marker(status, reason) for name in names}, state
    python = sys.executable
    steps = {
        "carryover_base_jobs": _step("carryover_base_jobs", [
            python, "scripts/base_prediction_jobs.py", "--date", business_date,
        ], optional=True),
        "carryover_base_prediction": _step("carryover_base_prediction", [
            python, "scripts/base_prediction_runner.py", "--date", business_date,
        ], optional=True),
        "carryover_result_schedule": _step("carryover_result_schedule", [
            python, "scripts/sync_result_schedules.py", "--date", business_date,
        ], optional=True),
    }
    return steps, state


def cycle(
    business_date: str,
    *,
    runtime_path: Path = RUNTIME_PATH,
    now: datetime | None = None,
    persist_runtime: bool = True,
    defer_projection: bool = False,
) -> dict:
    python = sys.executable
    started = (now or datetime.now(SHANGHAI)).isoformat()
    steps: dict[str, dict] = {}

    steps["universe"] = _step("universe", [
        python, "scripts/daily_schedule_workspace.py", "--date", business_date,
        "--no-cache", "--fetch-only",
    ], optional=True)
    if persist_runtime:
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
    steps["market_side_shadow_evaluation"] = _step("market_side_shadow_evaluation", [
        python, "scripts/market_side_shadow_refresh.py",
    ], optional=True)
    if persist_runtime:
        _write_runtime(Path(runtime_path), business_date=business_date, started_at=started, finished_at=None, steps=steps)

    if defer_projection:
        return {
            "schema_version": "1.0",
            "started_at": started,
            "finished_at": None,
            "business_date": business_date,
            "carryover_business_dates": [],
            "steps": steps,
            "overall_status": _overall_status(steps),
            "failed_steps": [name for name, value in steps.items() if value.get("status") not in {"SUCCESS", "SKIPPED"}],
        }

    steps["dashboard"] = _step("dashboard", [
        python, "scripts/prediction_dashboard.py", "--date", business_date,
    ], optional=False)
    steps["workspace"] = _step("workspace", [
        python, "scripts/match_workspace.py", "--date", business_date,
    ], optional=True)
    steps["site"] = _step("site", [python, "scripts/build_public_site.py"], optional=False)
    finished = (now or datetime.now(SHANGHAI)).isoformat()
    if persist_runtime:
        _write_runtime(Path(runtime_path), business_date=business_date, started_at=started, finished_at=finished, steps=steps)

    # Refresh the projection after the final health state is known, then copy it
    # into the static site.  This keeps the banner from showing a stale RUNNING
    # state after a successful unattended cycle.
    steps["dashboard"] = _step("dashboard_refresh", [
        python, "scripts/prediction_dashboard.py", "--date", business_date,
    ], optional=False)
    steps["site"] = _step("site_refresh", [python, "scripts/build_public_site.py"], optional=False)
    finished = (now or datetime.now(SHANGHAI)).isoformat()
    if persist_runtime:
        return _write_runtime(Path(runtime_path), business_date=business_date, started_at=started, finished_at=finished, steps=steps)
    return {
        "schema_version": "1.0",
        "started_at": started,
        "finished_at": finished,
        "business_date": business_date,
        "carryover_business_dates": [],
        "steps": steps,
        "overall_status": _overall_status(steps),
        "failed_steps": [name for name, value in steps.items() if value.get("status") not in {"SUCCESS", "SKIPPED"}],
    }


def production_cycle(
    *,
    now: datetime | None = None,
    runtime_path: Path = RUNTIME_PATH,
) -> dict:
    """Run today's full cycle, tomorrow's prematch refresh, and yesterday's maintenance."""
    current_date, carryover_dates = active_business_dates(now)
    carryover_date = carryover_dates[0]
    carryover_steps, carryover_state = _carryover_preparation(carryover_date)
    current_payload = cycle(
        current_date,
        runtime_path=runtime_path,
        now=now,
        persist_runtime=False,
        defer_projection=True,
    )
    steps = dict(carryover_steps)
    steps.update(current_payload["steps"])
    next_date = next_business_date(current_date)
    steps["next_universe"] = _step("next_universe", [
        sys.executable, "scripts/daily_schedule_workspace.py", "--date", next_date,
        "--no-cache", "--fetch-only",
    ], optional=True)
    steps["next_base_jobs"] = _step("next_base_jobs", [
        sys.executable, "scripts/base_prediction_jobs.py", "--date", next_date,
    ], optional=True)
    steps["next_base_prediction"] = _step("next_base_prediction", [
        sys.executable, "scripts/base_prediction_runner.py", "--date", next_date,
    ], optional=True)
    if carryover_state == "READY":
        steps["carryover_prospective"] = _step("carryover_prospective", [
            sys.executable, "scripts/prospective_settlement.py", "--date", carryover_date,
        ], optional=True)
    else:
        steps["carryover_prospective"] = _carryover_marker(
            "SKIPPED" if carryover_state == "SKIPPED" else "DEGRADED",
            "CARRYOVER_NOT_READY",
        )
    started = current_payload["started_at"]
    steps["workspace"] = _step("workspace", [
        sys.executable, "scripts/match_workspace.py", "--date", current_date,
        "--latest-only",
    ], optional=True)
    _write_runtime(
        Path(runtime_path),
        business_date=current_date,
        started_at=started,
        finished_at=None,
        steps=steps,
        carryover_business_dates=carryover_dates,
    )
    steps["dashboard"] = _step("dashboard_refresh", [
        sys.executable, "scripts/prediction_dashboard.py", "--date", current_date,
    ], optional=False)
    steps["site"] = _step("site_refresh", [sys.executable, "scripts/build_public_site.py"], optional=False)
    finished = (now or datetime.now(SHANGHAI)).isoformat()
    return _write_runtime(
        Path(runtime_path),
        business_date=current_date,
        started_at=started,
        finished_at=finished,
        steps=steps,
        carryover_business_dates=carryover_dates,
    )


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date")
    parser.add_argument("--runtime-path", type=Path, default=RUNTIME_PATH)
    args = parser.parse_args()
    if args.date:
        payload = cycle(args.date, runtime_path=args.runtime_path)
    else:
        payload = production_cycle(runtime_path=args.runtime_path)
    print(json.dumps(payload, ensure_ascii=False))
    return 1 if payload.get("overall_status") == "FAILED" else 0


if __name__ == "__main__":
    raise SystemExit(main())
