#!/usr/bin/env python3
"""Calculate the one-shot post-match wake-up time for a frozen pre-match report."""

from __future__ import annotations

import argparse
import json
from datetime import timedelta
from pathlib import Path

from postmatch_queue import BASE_DIR, load_json, parse_datetime, report_key, review_delay_minutes


DEFAULT_OUTPUT_ROOT = BASE_DIR / "data" / "postmatch_automation" / "schedules"


def create_schedule(report_path: Path, output_root: Path = DEFAULT_OUTPUT_ROOT) -> tuple[Path, dict]:
    """Register one bounded post-match verification for one frozen report."""
    report_path = report_path if report_path.is_absolute() else BASE_DIR / report_path
    payload = load_json(report_path)
    kickoff = parse_datetime(payload.get("match", {}).get("kickoff_local"))
    if kickoff is None:
        raise ValueError("Frozen report has no valid kickoff_local")
    delay, schedule_type = review_delay_minutes(payload)
    due = kickoff + timedelta(minutes=delay)
    match = payload.get("match", {})
    key = report_key(payload)
    schedule = {
        "schema_version": "1.0",
        "match_key": key,
        "home": match.get("home"),
        "away": match.get("away"),
        "competition": match.get("competition"),
        "business_date": match.get("business_date") or kickoff.date().isoformat(),
        "kickoff_local": kickoff.isoformat(),
        "shuju_id": match.get("shuju_id"),
        "schedule_type": schedule_type,
        "review_delay_minutes": delay,
        "review_due_at": due.isoformat(),
        "status": "scheduled",
        "verification_attempts": 0,
        "retry_policy": {"maximum_retries": 1, "retry_after_minutes": 45, "only_when_result_not_final": True},
        "automation_policy": "one_shot_only_no_periodic_model_polling",
        "source_report": report_path.relative_to(BASE_DIR).as_posix(),
    }
    output_root = output_root if output_root.is_absolute() else BASE_DIR / output_root
    output_root.mkdir(parents=True, exist_ok=True)
    output = output_root / f"{key.replace(':', '_')}.json"
    output.write_text(json.dumps(schedule, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return output, schedule


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    args = parser.parse_args()
    try:
        output, schedule = create_schedule(args.report, args.output_root)
    except ValueError as error:
        raise SystemExit(str(error)) from error
    print(json.dumps({"output": str(output), "review_due_at": schedule["review_due_at"], "schedule_type": schedule["schedule_type"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
