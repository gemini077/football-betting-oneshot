#!/usr/bin/env python3
"""Drain a bounded number of automatically selected core-event reports."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

try:
    from core_match_selector import ROOT, select
except ImportError:  # package import used by focused tests
    from scripts.core_match_selector import ROOT, select

SHANGHAI = ZoneInfo("Asia/Shanghai")
STATE_PATH = ROOT / "data" / "analysis_jobs" / "core_auto_state.json"
WORKSPACE = ROOT / "data" / "match_workspace" / "latest.json"


def load(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def save(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def _business_date_now(now: datetime | None = None) -> date:
    current = now or datetime.now(SHANGHAI)
    if current.tzinfo is None:
        current = current.replace(tzinfo=SHANGHAI)
    return current.astimezone(SHANGHAI).date()


def _parse_generated_at(value) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        parsed = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=SHANGHAI)
    return parsed.astimezone(SHANGHAI)


def validate_workspace(workspace: dict | None, *, now: datetime | None = None) -> dict:
    """Validate the workspace snapshot before allowing core selection."""
    if not isinstance(workspace, dict) or not workspace:
        return {"status": "INVALID_WORKSPACE", "reason": "WORKSPACE_MISSING_OR_INVALID"}
    target_date = str(workspace.get("target_date") or "").strip()
    generated_at = _parse_generated_at(workspace.get("generated_at"))
    if not target_date or generated_at is None:
        return {"status": "INVALID_WORKSPACE", "reason": "WORKSPACE_SCHEMA_OR_TIMESTAMP_INVALID"}
    try:
        parsed_target = date.fromisoformat(target_date)
    except ValueError:
        return {"status": "INVALID_WORKSPACE", "reason": "WORKSPACE_TARGET_DATE_INVALID"}
    current_date = _business_date_now(now)
    if parsed_target != current_date or generated_at.date() != parsed_target:
        return {
            "status": "STALE_WORKSPACE",
            "reason": "WORKSPACE_BUSINESS_DATE_STALE",
            "target_date": target_date,
            "current_business_date": current_date.isoformat(),
            "generated_at": generated_at.isoformat(),
        }
    return {
        "status": "CURRENT",
        "target_date": target_date,
        "current_business_date": current_date.isoformat(),
        "generated_at": generated_at.isoformat(),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-jobs", type=int, default=2)
    args = parser.parse_args()
    workspace = load(WORKSPACE, None)
    state = load(STATE_PATH, {"schema_version": "1.0", "jobs": {}})
    if not isinstance(state, dict):
        state = {"schema_version": "1.0", "jobs": {}}
    state.setdefault("schema_version", "1.0")
    state.setdefault("jobs", {})
    validation = validate_workspace(workspace)
    if validation["status"] != "CURRENT":
        state["updated_at"] = datetime.now(SHANGHAI).isoformat()
        state["selected_today"] = []
        state["last_status"] = validation["status"]
        state["last_error"] = validation["reason"]
        save(STATE_PATH, state)
        print(json.dumps({
            "status": validation["status"],
            "reason": validation["reason"],
            "selected": 0,
            "completed": 0,
            "failed": 0,
        }, ensure_ascii=False))
        return 1
    chosen = select(workspace.get("matches") or [])
    completed = failed = 0
    for row in chosen:
        if completed + failed >= max(1, args.max_jobs):
            break
        job_key = f"{row.get('business_date')}:{row.get('id')}"
        previous = state["jobs"].get(job_key) or {}
        if previous.get("status") == "completed" or int(previous.get("attempts") or 0) >= 4:
            continue
        command = [sys.executable, "scripts/deepseek_auto_analysis.py", "--date", str(row.get("business_date")),
                   "--match-id", str(row.get("id")), "--match", f"{row.get('home')} vs {row.get('away')}"]
        record = {
            "match": f"{row.get('home')} vs {row.get('away')}", "tier": row.get("core_tier"),
            "score": row.get("core_score"), "reason": row.get("core_reason"),
            "attempts": int(previous.get("attempts") or 0) + 1,
            "updated_at": datetime.now(SHANGHAI).isoformat(),
        }
        try:
            result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, encoding="utf-8", errors="replace", timeout=600)
        except subprocess.TimeoutExpired as error:
            record.update({"status": "retry_wait", "last_error": f"analysis timeout after {error.timeout}s"})
            state["jobs"][job_key] = record
            save(STATE_PATH, state)
            failed += 1
            continue
        if result.returncode == 0:
            record.update({"status": "completed", "last_error": None})
            completed += 1
        else:
            record.update({"status": "retry_wait", "last_error": (result.stderr or result.stdout)[-3000:]})
            failed += 1
        state["jobs"][job_key] = record
        save(STATE_PATH, state)
    state["updated_at"] = datetime.now(SHANGHAI).isoformat()
    state["last_status"] = "SUCCESS" if chosen else "NO_ELIGIBLE_CORE_MATCH"
    state["last_error"] = None
    state["selected_today"] = [{"id": row.get("id"), "match": f"{row.get('home')} vs {row.get('away')}",
                                 "tier": row.get("core_tier"), "score": row.get("core_score")} for row in chosen]
    save(STATE_PATH, state)
    print(json.dumps({
        "status": "SUCCESS" if chosen else "NO_ELIGIBLE_CORE_MATCH",
        "selected": len(chosen), "completed": completed, "failed": failed,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
