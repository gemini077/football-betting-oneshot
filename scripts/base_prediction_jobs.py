"""Idempotent BASE prediction job ledger sourced only from the daily Universe."""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

try:
    from match_identity import canonical_match_id
    from prediction_universe import load_prediction_universe
except ImportError:  # package imports used by tests
    from scripts.match_identity import canonical_match_id
    from scripts.prediction_universe import load_prediction_universe


PROJECT_ROOT = Path(__file__).resolve().parents[1]
UNIVERSE_ROOT = PROJECT_ROOT / "data" / "prediction_universe"
BASE_JOBS_ROOT = PROJECT_ROOT / "data" / "base_prediction_jobs"
VALID_UNIVERSE_STATUSES = {"READY", "EMPTY_CONFIRMED"}
REMOVED_STATUS = "REMOVED_FROM_CURRENT_UNIVERSE"
LOCAL_TZ = timezone(timedelta(hours=8))


def _as_now(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now().astimezone()
    if value.tzinfo is None:
        return value.replace(tzinfo=LOCAL_TZ)
    return value


def _present(value: Any) -> bool:
    return value not in (None, "")


def _first_value(row: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if _present(row.get(key)):
            return row[key]
    return None


def _kickoff(row: dict[str, Any]) -> str:
    direct = _first_value(row, "kickoff", "kickoff_local")
    if direct:
        return str(direct)
    match_date = str(_first_value(row, "matchDate", "match_date", "businessDate") or "")[:10]
    match_time = str(_first_value(row, "matchTime", "match_time") or "")[:8]
    if not match_date or not match_time:
        return ""
    if len(match_time) == 5:
        match_time += ":00"
    return f"{match_date}T{match_time}+08:00"


def _parse_kickoff(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=LOCAL_TZ) if parsed.tzinfo is None else parsed


def _safe_identity(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip()).strip("-")
    return safe or "unknown"


def _stable_match_identity(fixture: dict[str, Any]) -> tuple[str, str]:
    match_id = _first_value(fixture, "matchId", "match_id", "id")
    if match_id is not None:
        stable = str(match_id)
        return stable, _safe_identity(stable)
    kickoff = _kickoff(fixture)
    stable = canonical_match_id({
        "home": _first_value(fixture, "homeTeam", "home_team", "home"),
        "away": _first_value(fixture, "awayTeam", "away_team", "away"),
        "kickoff_local": kickoff,
    })
    return stable, _safe_identity(stable)


def _ledger_path(business_date: str, jobs_root: Path) -> Path:
    return Path(jobs_root) / f"{business_date}.json"


def _load_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _blocked_ledger(business_date: str, generated_at: str, source_universe: str) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "business_date": business_date,
        "status": "BLOCKED_UNIVERSE",
        "generated_at": generated_at,
        "fixture_count": 0,
        "job_count": 0,
        "pending_count": 0,
        "frozen_count": 0,
        "predicted_count": 0,
        "insufficient_data_count": 0,
        "prediction_failed_count": 0,
        "missed_prematch_count": 0,
        "source_universe": source_universe,
        "jobs": [],
    }


def _job_status(
    old_job: dict[str, Any] | None,
    kickoff: str,
    now: datetime,
) -> str:
    if old_job:
        old_status = old_job.get("status")
        if old_status and old_status not in {"PENDING", REMOVED_STATUS}:
            return str(old_status)
        if _present(old_job.get("prediction_id")):
            return str(old_status or "PENDING")
    kickoff_at = _parse_kickoff(kickoff)
    if kickoff_at is not None and now >= kickoff_at:
        return "MISSED_PREMATCH_WINDOW"
    return "PENDING"


def _build_job(
    business_date: str,
    fixture: dict[str, Any],
    source_universe: str,
    now: datetime,
    old_job: dict[str, Any] | None,
) -> dict[str, Any]:
    stable_match_id, safe_identity = _stable_match_identity(fixture)
    kickoff = _kickoff(fixture)
    job_id = f"BASE-{business_date}-{safe_identity}"
    now_iso = now.isoformat()
    job = dict(old_job or {})
    job.update({
        "job_id": job_id,
        "business_date": business_date,
        "match_id": stable_match_id,
        "match_num": _first_value(fixture, "matchNum", "match_num"),
        "league": _first_value(fixture, "league", "competition"),
        "home": _first_value(fixture, "homeTeam", "home_team", "home"),
        "away": _first_value(fixture, "awayTeam", "away_team", "away"),
        "kickoff": kickoff,
        "status": _job_status(old_job, kickoff, now),
        "created_at": (old_job or {}).get("created_at") or now_iso,
        "updated_at": now_iso,
        "source_universe": source_universe,
        "prediction_id": (old_job or {}).get("prediction_id"),
        "last_error": (old_job or {}).get("last_error"),
    })
    return job


def sync_base_prediction_jobs(
    business_date: str,
    *,
    universe_root: Path = UNIVERSE_ROOT,
    jobs_root: Path = BASE_JOBS_ROOT,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Ensure exactly one lightweight BASE job for every current Universe fixture."""
    current_time = _as_now(now)
    generated_at = current_time.isoformat()
    source_universe = (Path("data") / "prediction_universe" / f"{business_date}.json").as_posix()
    universe = load_prediction_universe(business_date, Path(universe_root))
    universe_status = universe.get("status") if universe else None
    if (
        not universe
        or universe.get("business_date") != business_date
        or universe_status not in VALID_UNIVERSE_STATUSES
    ):
        ledger = _blocked_ledger(business_date, generated_at, source_universe)
        _write_json(_ledger_path(business_date, Path(jobs_root)), ledger)
        return ledger

    fixtures = universe.get("fixtures")
    if universe_status == "EMPTY_CONFIRMED":
        fixtures = []
    elif not isinstance(fixtures, list):
        ledger = _blocked_ledger(business_date, generated_at, source_universe)
        _write_json(_ledger_path(business_date, Path(jobs_root)), ledger)
        return ledger

    ledger_path = _ledger_path(business_date, Path(jobs_root))
    existing = _load_json(ledger_path) or {}
    old_jobs = [job for job in existing.get("jobs", []) if isinstance(job, dict)]
    old_by_id = {str(job.get("job_id")): job for job in old_jobs if _present(job.get("job_id"))}
    old_removed = [job for job in existing.get("removed_jobs", []) if isinstance(job, dict)]
    old_removed_by_id = {str(job.get("job_id")): job for job in old_removed if _present(job.get("job_id"))}

    jobs: list[dict[str, Any]] = []
    current_ids: set[str] = set()
    duplicate_job_count = 0
    for fixture in fixtures:
        if not isinstance(fixture, dict):
            continue
        stable_match_id, safe_identity = _stable_match_identity(fixture)
        job_id = f"BASE-{business_date}-{safe_identity}"
        if job_id in current_ids:
            duplicate_job_count += 1
            continue
        current_ids.add(job_id)
        old_job = old_by_id.get(job_id) or old_removed_by_id.get(job_id)
        jobs.append(_build_job(business_date, fixture, source_universe, current_time, old_job))

    removed_jobs: list[dict[str, Any]] = []
    for old_job in old_jobs + old_removed:
        job_id = str(old_job.get("job_id") or "")
        if job_id and job_id not in current_ids:
            removed = dict(old_job)
            removed["status"] = REMOVED_STATUS
            removed["updated_at"] = generated_at
            removed_jobs.append(removed)

    pending_count = sum(job.get("status") == "PENDING" for job in jobs)
    frozen_count = sum(job.get("status") == "FROZEN" for job in jobs)
    missed_count = sum(job.get("status") == "MISSED_PREMATCH_WINDOW" for job in jobs)
    ledger = {
        "schema_version": "1.0",
        "business_date": business_date,
        "status": universe_status,
        "generated_at": generated_at,
        "fixture_count": len(fixtures),
        "job_count": len(jobs),
        "pending_count": pending_count,
        "frozen_count": frozen_count,
        "predicted_count": sum(job.get("status") == "PREDICTED" for job in jobs),
        "insufficient_data_count": sum(job.get("status") == "INSUFFICIENT_DATA" for job in jobs),
        "prediction_failed_count": sum(job.get("status") == "PREDICTION_FAILED" for job in jobs),
        "missed_prematch_count": missed_count,
        "duplicate_job_count": duplicate_job_count,
        "source_universe": source_universe,
        "jobs": jobs,
    }
    if removed_jobs:
        ledger["removed_jobs"] = removed_jobs
    _write_json(ledger_path, ledger)
    return ledger
