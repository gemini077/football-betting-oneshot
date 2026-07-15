#!/usr/bin/env python3
"""Verify due match results exactly once, with at most one delayed retry."""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fetch_and_parse import fetch_page
from fetch_trade_matches import fetch_trade_matches
from postmatch_queue import BASE_DIR, SHANGHAI, load_json, normalize, parse_datetime


SCHEDULE_ROOT = BASE_DIR / "data" / "postmatch_automation" / "schedules"
RESULT_ROOT = BASE_DIR / "data" / "postmatch_automation" / "results"
FINAL_STATUSES = {"result_verified", "reviewed", "blocked_result_not_final"}
SCORE_PATTERN = re.compile(
    r'<p\s+class=["\']odds_hd_bf["\'][^>]*>\s*<strong>\s*(\d+)\s*[:：]\s*(\d+)\s*</strong>',
    re.IGNORECASE,
)


def safe_key(value: Any) -> str:
    return re.sub(r"[^0-9A-Za-z._-]+", "_", str(value or "unknown")).strip("_") or "unknown"


def parse_header_score(page: str) -> tuple[int, int] | None:
    match = SCORE_PATTERN.search(page or "")
    if not match:
        return None
    return int(match.group(1)), int(match.group(2))


def resolve_shuju_id(schedule: dict[str, Any]) -> int | str | None:
    """Resolve a missing 500.com match id from date and exact team names."""
    shuju_id = schedule.get("shuju_id")
    if shuju_id:
        return shuju_id
    match_key = str(schedule.get("match_key") or "")
    if match_key.startswith("shuju:"):
        return match_key.split(":", 1)[1]

    kickoff = parse_datetime(schedule.get("kickoff_local"))
    dates = [schedule.get("business_date")]
    if kickoff is not None:
        dates.extend([(kickoff - timedelta(days=1)).date().isoformat(), kickoff.date().isoformat()])
    home, away = normalize(schedule.get("home")), normalize(schedule.get("away"))
    for business_date in dict.fromkeys(value for value in dates if value):
        payload = fetch_trade_matches(str(business_date), no_cache=True)
        for match in payload.get("matches") or []:
            if normalize(match.get("home_team")) == home and normalize(match.get("away_team")) == away:
                schedule["shuju_id"] = match.get("shuju_id")
                schedule["resolved_business_date"] = business_date
                schedule["resolved_match_num"] = match.get("match_num")
                return schedule["shuju_id"]
    return None


def verify_schedule(path: Path, now: datetime, result_root: Path = RESULT_ROOT) -> dict[str, Any]:
    schedule = load_json(path)
    status = str(schedule.get("status") or "scheduled")
    if status in FINAL_STATUSES:
        return {"path": str(path), "status": "skipped_final"}

    due = parse_datetime(schedule.get("review_due_at"))
    if due is None or now < due:
        return {"path": str(path), "status": "skipped_not_due"}

    attempts = int(schedule.get("verification_attempts") or 0) + 1
    schedule["verification_attempts"] = attempts
    schedule["last_checked_at"] = now.isoformat()
    score = None
    source_url = None
    error = None
    try:
        shuju_id = resolve_shuju_id(schedule)
    except Exception as exc:
        shuju_id = None
        error = f"match_id_resolution_failed: {exc}"

    if shuju_id:
        source_url = f"https://odds.500.com/fenxi/shuju-{shuju_id}.shtml"
        try:
            page = fetch_page(source_url)
            if page.startswith(("HTTP Error", "URL Error")):
                error = page
            else:
                score = parse_header_score(page)
        except Exception as exc:
            error = str(exc)
    elif error is None:
        error = "missing_shuju_id"

    if score is not None:
        home_score, away_score = score
        result = {
            "schema_version": "1.0",
            "match_key": schedule.get("match_key"),
            "home": schedule.get("home"),
            "away": schedule.get("away"),
            "kickoff_local": schedule.get("kickoff_local"),
            "verified_at": now.isoformat(),
            "result_90m": f"{home_score}-{away_score}",
            "home_score": home_score,
            "away_score": away_score,
            "scope": "regulation_90m_plus_stoppage",
            "source": "500.com_match_header",
            "source_url": source_url,
            "verification_attempt": attempts,
        }
        result_root.mkdir(parents=True, exist_ok=True)
        result_path = result_root / f"{safe_key(schedule.get('match_key'))}.json"
        result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        try:
            result_file = result_path.relative_to(BASE_DIR).as_posix()
        except ValueError:
            result_file = str(result_path)
        schedule.update(
            {
                "status": "result_verified",
                "result_90m": result["result_90m"],
                "result_verified_at": now.isoformat(),
                "result_source": result["source"],
                "result_file": result_file,
            }
        )
        outcome = "result_verified"
    elif attempts <= int((schedule.get("retry_policy") or {}).get("maximum_retries", 1)):
        retry_minutes = int((schedule.get("retry_policy") or {}).get("retry_after_minutes", 45))
        schedule["status"] = "retry_scheduled"
        schedule["review_due_at"] = (now + timedelta(minutes=retry_minutes)).isoformat()
        schedule["last_error"] = error or "result_not_final"
        outcome = "retry_scheduled"
    else:
        schedule["status"] = "blocked_result_not_final"
        schedule["last_error"] = error or "result_not_final_after_bounded_retry"
        outcome = "blocked_result_not_final"

    path.write_text(json.dumps(schedule, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"path": str(path), "status": outcome, "attempts": attempts, "score": schedule.get("result_90m")}


def run_due(now: datetime, schedule_root: Path = SCHEDULE_ROOT) -> list[dict[str, Any]]:
    results = []
    for path in sorted(schedule_root.glob("*.json")):
        outcome = verify_schedule(path, now)
        if not outcome["status"].startswith("skipped_"):
            results.append(outcome)
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--now", help="ISO timestamp for deterministic verification")
    parser.add_argument("--schedule-root", type=Path, default=SCHEDULE_ROOT)
    args = parser.parse_args()
    now = parse_datetime(args.now) if args.now else datetime.now(timezone.utc).astimezone(SHANGHAI)
    if now is None:
        raise SystemExit("--now must be an ISO timestamp")
    root = args.schedule_root if args.schedule_root.is_absolute() else BASE_DIR / args.schedule_root
    outcomes = run_due(now, root)
    print(json.dumps({"checked": len(outcomes), "outcomes": outcomes}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
