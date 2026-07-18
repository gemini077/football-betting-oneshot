#!/usr/bin/env python3
"""Drain a bounded number of automatically selected core-event reports."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from core_match_selector import ROOT, select

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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-jobs", type=int, default=2)
    args = parser.parse_args()
    workspace = load(WORKSPACE, {})
    state = load(STATE_PATH, {"schema_version": "1.0", "jobs": {}})
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
    state["selected_today"] = [{"id": row.get("id"), "match": f"{row.get('home')} vs {row.get('away')}",
                                 "tier": row.get("core_tier"), "score": row.get("core_score")} for row in chosen]
    save(STATE_PATH, state)
    print(json.dumps({"selected": len(chosen), "completed": completed, "failed": failed}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
