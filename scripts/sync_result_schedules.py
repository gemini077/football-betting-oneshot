#!/usr/bin/env python3
"""Ensure every sold Sporttery fixture has one bounded result-verification task."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from match_identity import canonical_match_id
from postmatch_queue import BASE_DIR, SHANGHAI, load_json, parse_datetime


SCHEDULE_ROOT = BASE_DIR / "data" / "postmatch_automation" / "schedules"
UPDATE_ROOT = BASE_DIR / "data" / "schedule_updates"
FETCH_ROOT = BASE_DIR / "data" / "fetch_runs"
POSTMATCH_QUEUE_PATH = BASE_DIR / "data" / "postmatch_automation" / "queue.json"
FINAL = {"result_verified", "reviewed"}


def fixture_kickoff(row: dict[str, Any]) -> datetime | None:
    return parse_datetime(f"{row.get('matchDate')}T{str(row.get('matchTime') or '')[:5]}:00+08:00")


def latest_schedule_payload(business_date: str, update_root: Path = UPDATE_ROOT, fetch_root: Path = FETCH_ROOT) -> dict[str, Any]:
    candidates: list[tuple[int, int, float, dict[str, Any]]] = []
    roots = [update_root]
    if fetch_root != update_root:
        roots.append(fetch_root)
    for root in roots:
        for path in root.glob(f"**/*sporttery*{business_date}*.json"):
            try:
                payload = load_json(path)
            except Exception:
                continue
            matches = payload.get("matches") or []
            if payload.get("success") and matches:
                # A full unfiltered daily snapshot is the source of truth;
                # one-match checkpoint artifacts must not shrink the queue.
                advertised = int(payload.get("unfiltered_match_count") or len(matches))
                candidates.append((len(matches), advertised, path.stat().st_mtime, payload))
    if not candidates:
        return {"matches": []}
    return max(candidates, key=lambda item: item[:3])[3]


def schedule_from_fixture(row: dict[str, Any], now: datetime) -> dict[str, Any] | None:
    kickoff = fixture_kickoff(row)
    if kickoff is None:
        return None
    match = {
        "home": row.get("homeTeam"),
        "away": row.get("awayTeam"),
        "kickoff_local": kickoff.isoformat(),
    }
    key = canonical_match_id(match)
    return {
        "schema_version": "1.1",
        "match_key": key,
        "canonical_match_id": key,
        "provider_match_id": row.get("matchId"),
        "nowscore_id": row.get("nowscoreId"),
        "home": row.get("homeTeam"),
        "away": row.get("awayTeam"),
        "competition": row.get("league"),
        "business_date": row.get("businessDate") or kickoff.date().isoformat(),
        "kickoff_local": kickoff.isoformat(),
        "shuju_id": row.get("shujuId"),
        "match_num": row.get("matchNum"),
        "schedule_type": "result_only",
        "review_delay_minutes": 135,
        "review_due_at": (kickoff + timedelta(minutes=135)).isoformat(),
        "status": "scheduled",
        "verification_attempts": 0,
        "verification_expires_at": (kickoff + timedelta(hours=24)).isoformat(),
        "retry_policy": {"maximum_retries": 1, "retry_after_minutes": 45, "only_when_result_not_final": True},
        "automation_policy": "one_shot_only_no_periodic_model_polling",
        "analysis_available": False,
        "registered_at": now.isoformat(),
    }


def schedule_from_review_queue(entry: dict[str, Any], now: datetime) -> dict[str, Any] | None:
    """Recover a result task when a selected-match fetch was not a full schedule snapshot."""
    kickoff = parse_datetime(entry.get("kickoff_local"))
    home, away = entry.get("home"), entry.get("away")
    if kickoff is None or not home or not away:
        return None
    match = {"home": home, "away": away, "kickoff_local": kickoff.isoformat()}
    key = canonical_match_id(match)
    raw_id = entry.get("shuju_id") or entry.get("nowscore_id")
    try:
        provider_id = int(raw_id) if raw_id not in (None, "") else None
    except (TypeError, ValueError):
        provider_id = None
    return {
        "schema_version": "1.1",
        "match_key": key,
        "canonical_match_id": key,
        "provider_match_id": entry.get("provider_match_id"),
        "nowscore_id": provider_id,
        "home": home,
        "away": away,
        "competition": entry.get("competition"),
        "business_date": entry.get("business_date") or kickoff.date().isoformat(),
        "kickoff_local": kickoff.isoformat(),
        "shuju_id": provider_id,
        "match_num": entry.get("match_num"),
        "schedule_type": entry.get("schedule_type") or "result_only",
        "review_delay_minutes": int(entry.get("review_delay_minutes") or 135),
        "review_due_at": entry.get("review_due_at") or (kickoff + timedelta(minutes=135)).isoformat(),
        "status": "scheduled",
        "verification_attempts": 0,
        "verification_expires_at": (kickoff + timedelta(hours=24)).isoformat(),
        "retry_policy": {"maximum_retries": 1, "retry_after_minutes": 45, "only_when_result_not_final": True},
        "automation_policy": "one_shot_only_no_periodic_model_polling",
        "analysis_available": True,
        "source_report": entry.get("source_report"),
        "registered_at": now.isoformat(),
    }


def merge_schedule(existing: dict[str, Any], fresh: dict[str, Any], now: datetime) -> dict[str, Any]:
    if existing.get("status") in FINAL:
        return existing
    merged = {**fresh, **existing}
    for field in ("provider_match_id", "nowscore_id", "shuju_id", "match_num", "source_report"):
        if fresh.get(field) not in (None, ""):
            merged[field] = fresh[field]
    # A pre-kickoff check was an old scheduler bug, not a real verification
    # attempt.  Reset it while preserving legitimate post-kickoff retries.
    checked = parse_datetime(existing.get("last_checked_at"))
    kickoff = parse_datetime(fresh.get("kickoff_local"))
    pre_kickoff_corruption = bool(
        kickoff and not existing.get("result_90m")
        and (now < kickoff or (checked and checked < kickoff))
    )
    if pre_kickoff_corruption:
        merged["status"] = "scheduled"
        merged["verification_attempts"] = 0
        merged["review_due_at"] = fresh["review_due_at"]
        merged.pop("last_checked_at", None)
        merged.pop("last_error", None)
    merged["analysis_available"] = bool(merged.get("source_report"))
    merged["last_fixture_sync_at"] = now.isoformat()
    return merged


def sync_date(business_date: str, now: datetime, output_root: Path = SCHEDULE_ROOT,
              update_root: Path = UPDATE_ROOT) -> dict[str, int]:
    payload = latest_schedule_payload(business_date, update_root)
    output_root.mkdir(parents=True, exist_ok=True)
    created = updated = 0
    for row in payload.get("matches") or []:
        fresh = schedule_from_fixture(row, now)
        if not fresh:
            continue
        path = output_root / f"{fresh['match_key'].replace(':', '_')}.json"
        if path.exists():
            existing = load_json(path)
            saved = merge_schedule(existing, fresh, now)
            updated += 1
        else:
            saved = fresh
            created += 1
        path.write_text(json.dumps(saved, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    # Selected-match workflows may only leave a filtered fetch artifact.  The
    # postmatch queue still carries the frozen report/provider binding, so use
    # it as a bounded recovery path instead of dropping the result task.
    try:
        queue = load_json(POSTMATCH_QUEUE_PATH) or {}
    except (OSError, json.JSONDecodeError):
        queue = {}
    for entry in queue.get("pending") or []:
        entry_date = str(entry.get("business_date") or "")
        if not entry_date:
            entry_kickoff = parse_datetime(entry.get("kickoff_local"))
            entry_date = entry_kickoff.date().isoformat() if entry_kickoff else ""
        if entry_date != business_date:
            continue
        fresh = schedule_from_review_queue(entry, now)
        if not fresh:
            continue
        path = output_root / f"{fresh['match_key'].replace(':', '_')}.json"
        if path.exists():
            saved = merge_schedule(load_json(path), fresh, now)
            updated += 1
        else:
            saved = fresh
            created += 1
        path.write_text(json.dumps(saved, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"fixtures": len(payload.get("matches") or []), "created": created, "updated": updated}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date")
    args = parser.parse_args()
    now = datetime.now(SHANGHAI)
    business_date = args.date or now.date().isoformat()
    print(json.dumps(sync_date(business_date, now), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
