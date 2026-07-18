#!/usr/bin/env python3
"""Run one deterministic maintenance cycle without any LLM call.

The workflow may wake frequently, but every expensive match operation is still
gated by its saved due time.  This keeps schedules and completed results fresh
without spending model tokens or repeatedly analysing every match.
"""
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


def run(command: list[str], *, optional: bool = False) -> dict:
    completed = subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        timeout=360,
    )
    if completed.returncode and not optional:
        raise RuntimeError(completed.stderr or completed.stdout)
    output = completed.stdout.strip()
    try:
        payload = json.loads(output) if output else {}
    except json.JSONDecodeError:
        payload = {"output": output[-2000:]}
    payload["returncode"] = completed.returncode
    if completed.stderr.strip():
        payload["stderr"] = completed.stderr.strip()[-2000:]
    return payload


def cycle(business_date: str) -> dict:
    python = sys.executable
    outcomes = {}
    outcomes["schedule"] = run([
        python, "scripts/daily_schedule_workspace.py", "--date", business_date,
        "--no-cache", "--fetch-only",
    ], optional=True)
    outcomes["workspace_before"] = run([
        python, "scripts/match_workspace.py", "--date", business_date,
    ])
    outcomes["result_schedule_sync"] = run([
        python, "scripts/sync_result_schedules.py", "--date", business_date,
    ], optional=True)
    outcomes["identity_migration"] = run([
        python, "scripts/migrate_automation_identity.py",
    ], optional=True)
    outcomes["prematch_due"] = run([
        python, "scripts/prematch_market_monitor.py",
    ], optional=True)
    outcomes["results_due"] = run([
        python, "scripts/postmatch_result.py",
    ], optional=True)
    outcomes["reviews"] = run([
        python, "scripts/automatic_postmatch_review.py",
    ], optional=True)
    outcomes["dashboard"] = run([
        python, "scripts/postmatch_dashboard.py",
    ], optional=True)
    outcomes["workspace_after"] = run([
        python, "scripts/match_workspace.py", "--date", business_date,
    ])
    outcomes["site"] = run([python, "scripts/build_public_site.py"])
    return {
        "schema_version": "1.0",
        "business_date": business_date,
        "generated_at": datetime.now(SHANGHAI).isoformat(),
        "llm_calls": 0,
        "outcomes": outcomes,
    }


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date")
    args = parser.parse_args()
    business_date = args.date or datetime.now(SHANGHAI).date().isoformat()
    print(json.dumps(cycle(business_date), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
