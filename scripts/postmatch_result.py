#!/usr/bin/env python3
"""Verify due results with bounded multi-source retries until final."""

from __future__ import annotations

import argparse
import html as html_lib
import json
import re
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fetch_and_parse import fetch_page
from fetch_trade_matches import fetch_trade_matches
from postmatch_queue import BASE_DIR, SHANGHAI, load_json, normalize, parse_datetime


SCHEDULE_ROOT = BASE_DIR / "data" / "postmatch_automation" / "schedules"
RESULT_ROOT = BASE_DIR / "data" / "postmatch_automation" / "results"
FINAL_STATUSES = {"result_verified", "reviewed"}
RESULT_STRATEGY_VERSION = "nowscore_matchdetail_v3"
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


def resolve_nowscore_id(schedule: dict[str, Any]) -> int | None:
    """Recover the verified Nowscore id already captured during pre-match work."""
    if schedule.get("nowscore_id"):
        return int(schedule["nowscore_id"])
    match_filters: set[str] = set()
    source_report = BASE_DIR / str(schedule.get("source_report") or "")
    if source_report.exists():
        try:
            report = load_json(source_report)
            report_match = report.get("match") or {}
            match_id = str(report_match.get("match_id") or "").strip()
            if match_id:
                match_filters.add(match_id)
            report_home = str(report_match.get("home") or schedule.get("home") or "").strip()
            report_away = str(report_match.get("away") or schedule.get("away") or "").strip()
            if report_home and report_away:
                match_filters.add(f"{report_home} vs {report_away}")
        except (OSError, json.JSONDecodeError, ValueError):
            pass
    if not match_filters:
        return None
    manifests = sorted((BASE_DIR / "data" / "fetch_runs").glob("**/*_fetch_manifest.json"), reverse=True)
    for manifest_path in manifests:
        try:
            manifest = load_json(manifest_path)
        except (OSError, json.JSONDecodeError):
            continue
        if str(manifest.get("match_filter") or "").strip() not in match_filters:
            continue
        for row in (((manifest.get("sources") or {}).get("nowscore") or {}).get("matches") or []):
            if row.get("status") == "OK" and row.get("nowscore_id"):
                schedule["nowscore_id"] = int(row["nowscore_id"])
                return schedule["nowscore_id"]
    return None


def parse_nowscore_detail(page: str) -> tuple[int, int] | None:
    """Read a final 90-minute score from Nowscore's archived event page."""
    state = re.search(r"var\s+state\s*=\s*(-?\d+)", page or "")
    if not state or int(state.group(1)) != -1:
        return None
    home = away = 0
    for event in re.finditer(r'<tr[^>]*data-kind=["\'](1|7|8)["\'][^>]*>(.*?)</tr>', page, re.I | re.S):
        cells = re.findall(r"<td[^>]*>(.*?)</td>", event.group(2), re.I | re.S)
        if len(cells) < 5:
            continue
        left = html_lib.unescape(re.sub(r"<[^>]+>", "", cells[0])).strip()
        right = html_lib.unescape(re.sub(r"<[^>]+>", "", cells[-1])).strip()
        if not left and not right:
            continue
        scoring_home = bool(left)
        if event.group(1) == "8":  # own goal is credited to the other side
            scoring_home = not scoring_home
        if scoring_home:
            home += 1
        else:
            away += 1
    return home, away


def fetch_nowscore_result(match_id: int) -> tuple[tuple[int, int] | None, str, str | None]:
    urls = [
        f"https://live.nowscore.com/MatchDetail/{match_id}.html",
        f"https://live.nowscore.com/detail/{match_id}.html",
    ]
    errors = []
    for url in urls:
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(request, timeout=30) as response:
                raw = response.read()
            for encoding in ("utf-8-sig", "gb18030", "utf-8"):
                try:
                    page = raw.decode(encoding)
                    break
                except UnicodeDecodeError:
                    continue
            else:
                page = raw.decode("utf-8", errors="replace")
            score = parse_nowscore_detail(page) or parse_header_score(page)
            if score is not None:
                return score, url, None
            errors.append(f"{url}: result_not_final")
        except Exception as exc:
            errors.append(f"{url}: {exc}")
    return None, urls[0], "; ".join(errors)


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
    strategy_upgrade = schedule.get("result_strategy_version") != RESULT_STRATEGY_VERSION
    if due is None or (now < due and not strategy_upgrade):
        return {"path": str(path), "status": "skipped_not_due"}

    attempts = int(schedule.get("verification_attempts") or 0) + 1
    schedule["verification_attempts"] = attempts
    schedule["last_checked_at"] = now.isoformat()
    score = None
    source_url = None
    result_source = None
    error = None
    schedule["result_strategy_version"] = RESULT_STRATEGY_VERSION
    try:
        nowscore_id = resolve_nowscore_id(schedule)
    except Exception as exc:
        nowscore_id = None
        error = f"nowscore_id_resolution_failed: {exc}"
    if nowscore_id:
        score, source_url, nowscore_error = fetch_nowscore_result(nowscore_id)
        if score is not None:
            result_source = "nowscore_match_detail"
        elif nowscore_error:
            error = nowscore_error
    try:
        shuju_id = None if score is not None else resolve_shuju_id(schedule)
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
                if score is not None:
                    result_source = "500.com_match_header"
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
            "source": result_source or "verified_match_result",
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
    expires = parse_datetime(schedule.get("verification_expires_at"))
    within_window = expires is None or now < expires
    if score is None and within_window and attempts <= int((schedule.get("retry_policy") or {}).get("maximum_retries", 24)):
        retry_minutes = int((schedule.get("retry_policy") or {}).get("retry_after_minutes", 45))
        schedule["status"] = "retry_scheduled"
        schedule["review_due_at"] = (now + timedelta(minutes=retry_minutes)).isoformat()
        schedule["last_error"] = error or "result_not_final"
        outcome = "retry_scheduled"
    elif score is None:
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
