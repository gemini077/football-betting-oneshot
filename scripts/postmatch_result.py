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
from match_identity import canonical_match_id


SCHEDULE_ROOT = BASE_DIR / "data" / "postmatch_automation" / "schedules"
RESULT_ROOT = BASE_DIR / "data" / "postmatch_automation" / "results"
FINAL_STATUSES = {
    "result_verified",
    "reviewed",
    "manual_review_required",
    "expired_unresolved",
}
RESULT_STRATEGY_VERSION = "nowscore_matchdetail_v4_dual_source_phase_aware"
WORKSPACE_PATH = BASE_DIR / "data" / "match_workspace" / "latest.json"
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
    # The public workspace is refreshed more often than a frozen report.  Use
    # its later verified provider binding before scanning old fetch manifests.
    try:
        workspace = load_json(WORKSPACE_PATH)
    except (OSError, json.JSONDecodeError):
        workspace = {}
    provider_id = str(schedule.get("provider_match_id") or "").strip()
    schedule_key = str(schedule.get("canonical_match_id") or schedule.get("match_key") or "")
    schedule_kickoff = parse_datetime(schedule.get("kickoff_local"))
    for row in list(workspace.get("matches") or []) + list(workspace.get("completed") or []):
        row_id = str(row.get("provider_match_id") or row.get("id") or row.get("match_id") or "").strip()
        same_provider = bool(provider_id and row_id == provider_id)
        same_canonical = bool(schedule_key and canonical_match_id(row) == schedule_key)
        same_teams = (
            normalize(row.get("home")) == normalize(schedule.get("home"))
            and normalize(row.get("away")) == normalize(schedule.get("away"))
        )
        row_kickoff = parse_datetime(row.get("kickoff") or row.get("kickoff_local"))
        same_kickoff = bool(
            schedule_kickoff and row_kickoff
            and abs((schedule_kickoff - row_kickoff).total_seconds()) <= 15 * 60
        )
        if (same_provider or same_canonical or (same_teams and same_kickoff)) and row.get("nowscore_id"):
            schedule["nowscore_id"] = int(row["nowscore_id"])
            schedule["nowscore_identity_source"] = "match_workspace"
            return schedule["nowscore_id"]
    # A finished match may already have moved out of the workspace before the
    # verifier runs.  The successful Sporttery schedule snapshots retain the
    # verified Nowscore binding, so use them as the next authoritative source.
    schedule_files = sorted(
        (BASE_DIR / "data" / "schedule_updates").glob("**/*_sporttery_*.json"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    for schedule_path in schedule_files:
        try:
            schedule_payload = load_json(schedule_path)
        except (OSError, json.JSONDecodeError):
            continue
        for row in schedule_payload.get("matches") or []:
            same_teams = (
                normalize(row.get("homeTeam")) == normalize(schedule.get("home"))
                and normalize(row.get("awayTeam")) == normalize(schedule.get("away"))
            )
            row_kickoff = parse_datetime(
                f"{row.get('matchDate')}T{str(row.get('matchTime') or '')[:5]}:00+08:00"
            )
            same_kickoff = bool(
                schedule_kickoff and row_kickoff
                and abs((schedule_kickoff - row_kickoff).total_seconds()) <= 15 * 60
            )
            if same_teams and same_kickoff and row.get("nowscoreId"):
                schedule["nowscore_id"] = int(row["nowscoreId"])
                schedule["nowscore_identity_source"] = "sporttery_schedule_snapshot"
                return schedule["nowscore_id"]
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


def _event_minute(event_html: str) -> int | None:
    """Extract the displayed minute, including 90+ stoppage time."""
    cells = re.findall(r"<td[^>]*>(.*?)</td>", event_html, re.I | re.S)
    if len(cells) < 5:
        return None
    minute_text = html_lib.unescape(re.sub(r"<[^>]+>", "", cells[2])).strip()
    match = re.search(r"(\d{1,3})(?:\s*\+\s*\d{1,2})?", minute_text)
    return int(match.group(1)) if match else None


def _score_result(home: int, away: int, *, after_extra_time: str | None = None) -> dict[str, Any]:
    return {
        "score_90m": f"{home}-{away}",
        "after_extra_time": after_extra_time,
        "penalties": None,
        "scope": "regulation_90m_plus_stoppage",
    }


def _result_from_tuple(score: tuple[int, int]) -> dict[str, Any]:
    return _score_result(score[0], score[1])


def parse_nowscore_detail(page: str) -> dict[str, Any] | None:
    """Read 90-minute and extra-time scores from Nowscore's event page.

    Nowscore places an own-goal event on the side receiving the goal.  The
    column position is therefore the authoritative scoring side; data-kind 8
    must not be inverted a second time.
    """
    state = re.search(r"var\s+state\s*=\s*(-?\d+)", page or "")
    if not state or int(state.group(1)) != -1:
        return None
    home = away = extra_home = extra_away = 0
    for event in re.finditer(r'<tr[^>]*data-kind=["\'](1|7|8)["\'][^>]*>(.*?)</tr>', page, re.I | re.S):
        cells = re.findall(r"<td[^>]*>(.*?)</td>", event.group(2), re.I | re.S)
        if len(cells) < 5:
            continue
        minute = _event_minute(event.group(2))
        if minute is None:
            continue
        left = html_lib.unescape(re.sub(r"<[^>]+>", "", cells[0])).strip()
        right = html_lib.unescape(re.sub(r"<[^>]+>", "", cells[-1])).strip()
        if not left and not right:
            continue
        scoring_home = bool(left)
        if minute <= 90:
            if scoring_home:
                home += 1
            else:
                away += 1
        else:
            if scoring_home:
                extra_home += 1
            else:
                extra_away += 1
    after_extra_time = None
    if extra_home or extra_away:
        after_extra_time = f"{home + extra_home}-{away + extra_away}"
    return _score_result(home, away, after_extra_time=after_extra_time)


def fetch_nowscore_result(match_id: int) -> tuple[dict[str, Any] | None, str, str | None]:
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
            result = parse_nowscore_detail(page)
            if result is None:
                header_score = parse_header_score(page)
                result = _result_from_tuple(header_score) if header_score is not None else None
            if result is not None:
                return result, url, None
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
    # A parser upgrade must never make a future fixture eligible early.  It is
    # applied on the first check after the saved due time instead.
    if due is None or now < due:
        return {"path": str(path), "status": "skipped_not_due"}

    attempts = int(schedule.get("verification_attempts") or 0) + 1
    schedule["verification_attempts"] = attempts
    schedule["last_checked_at"] = now.isoformat()
    nowscore_result = None
    secondary_score = None
    nowscore_source_url = None
    secondary_source_url = None
    result_source = None
    primary_error = None
    secondary_error = None
    schedule["result_strategy_version"] = RESULT_STRATEGY_VERSION
    had_explicit_nowscore_id = bool(schedule.get("nowscore_id"))
    try:
        nowscore_id = resolve_nowscore_id(schedule)
    except Exception as exc:
        nowscore_id = None
        primary_error = f"nowscore_id_resolution_failed: {exc}"
    if nowscore_id:
        nowscore_result, nowscore_source_url, nowscore_error = fetch_nowscore_result(nowscore_id)
        # 保留旧调用方返回 (home, away) 元组时的兼容性。
        if isinstance(nowscore_result, tuple) and len(nowscore_result) == 2:
            nowscore_result = _result_from_tuple(nowscore_result)
        if nowscore_result is not None:
            result_source = "nowscore_match_detail"
        elif nowscore_error:
            primary_error = nowscore_error
    explicit_dual_source = had_explicit_nowscore_id and str(schedule.get("shuju_id") or "").isdigit()
    try:
        shuju_id = resolve_shuju_id(schedule)
    except Exception as exc:
        shuju_id = None
        secondary_error = f"match_id_resolution_failed: {exc}"

    if shuju_id:
        secondary_source_url = f"https://odds.500.com/fenxi/shuju-{shuju_id}.shtml"
        try:
            page = fetch_page(secondary_source_url)
            if page.startswith(("HTTP Error", "URL Error")):
                secondary_error = page
            else:
                secondary_score = parse_header_score(page)
                if secondary_score is None:
                    secondary_error = "result_not_final"
        except Exception as exc:
            secondary_error = str(exc)
    elif secondary_error is None:
        secondary_error = "missing_shuju_id"

    verification_issue = None
    if explicit_dual_source and nowscore_result is not None and secondary_score is not None:
        if nowscore_result["score_90m"] != f"{secondary_score[0]}-{secondary_score[1]}":
            verification_issue = "result_source_conflict"
            secondary_error = (
                "result_source_conflict: "
                f"nowscore={nowscore_result['score_90m']} "
                f"500={secondary_score[0]}-{secondary_score[1]}"
            )
    if explicit_dual_source and nowscore_result is not None and secondary_score is None and shuju_id:
        verification_issue = "secondary_source_unavailable"
        secondary_error = secondary_error or "result_secondary_source_unavailable"
    if nowscore_result is None and secondary_score is None:
        verification_issue = "result_not_final"

    schedule["result_sources"] = {
        "primary": {
            "name": "nowscore_match_detail",
            "status": "verified" if nowscore_result is not None else "unavailable",
            "score_90m": nowscore_result.get("score_90m") if nowscore_result else None,
            "source_url": nowscore_source_url,
            "error": primary_error,
        },
        "secondary": {
            "name": "500_com_match_header",
            "status": "verified" if secondary_score is not None else "unavailable",
            "score_90m": f"{secondary_score[0]}-{secondary_score[1]}" if secondary_score else None,
            "source_url": secondary_source_url,
            "error": secondary_error,
        },
    }
    schedule["verification_issue"] = verification_issue

    result = None
    if verification_issue is None and (nowscore_result is not None or secondary_score is not None):
        result = nowscore_result or _result_from_tuple(secondary_score)
        home_score, away_score = (int(part) for part in result["score_90m"].split("-"))
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
            "after_extra_time": result.get("after_extra_time"),
            "penalties": result.get("penalties"),
            "scope": result.get("scope") or "regulation_90m_plus_stoppage",
            "source": "nowscore_match_detail+500_com_match_header" if explicit_dual_source and secondary_score is not None and nowscore_result is not None else result_source or "verified_match_result",
            "source_url": nowscore_source_url if nowscore_result is not None else secondary_source_url,
            "secondary_source_url": secondary_source_url if secondary_score is not None else None,
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
                "after_extra_time": result.get("after_extra_time"),
                "penalties": result.get("penalties"),
                "result_verified_at": now.isoformat(),
                "result_source": result["source"],
                "result_file": result_file,
            }
        )
        schedule.pop("last_error", None)
        schedule.pop("terminal_reason", None)
        outcome = "result_verified"
    expires = parse_datetime(schedule.get("verification_expires_at"))
    within_window = expires is None or now < expires
    retry_limit = int((schedule.get("retry_policy") or {}).get("maximum_retries", 1))
    issue_error = secondary_error or primary_error or verification_issue or "result_not_final"
    if result is None and within_window and attempts <= retry_limit:
        retry_minutes = int((schedule.get("retry_policy") or {}).get("retry_after_minutes", 45))
        schedule["status"] = "retry_scheduled"
        schedule["review_due_at"] = (now + timedelta(minutes=retry_minutes)).isoformat()
        schedule["last_error"] = issue_error
        outcome = "retry_scheduled"
    elif result is None:
        terminal_status = (
            "manual_review_required"
            if verification_issue in {"result_source_conflict", "secondary_source_unavailable"}
            else "expired_unresolved"
        )
        schedule["status"] = terminal_status
        schedule["terminal_reason"] = verification_issue or "result_not_final_after_bounded_retry"
        schedule["last_error"] = issue_error
        outcome = terminal_status

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
