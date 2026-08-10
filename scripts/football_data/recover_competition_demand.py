"""Recover project competition demand from bounded local metadata indexes."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .competition_demand import recover_competition_usage


ROOT = Path(__file__).resolve().parents[2]
SCHEDULE_ROOT = ROOT / "data" / "postmatch_automation" / "schedules"
TASKS_PATH = ROOT / "data" / "market_history" / "prematch_tasks.json"
JOBS_PATH = ROOT / "data" / "analysis_jobs" / "core_auto_state.json"
SELECTED_PATH = ROOT / "data" / "match_workspace" / "selected_matches.json"
CURRENT_PATH = ROOT / "data" / "match_workspace" / "latest.json"
CURRENT_EVIDENCE_PATH = ROOT / "data" / "football_data" / "current_match_identity_evidence.json"
USAGE_PATH = ROOT / "data" / "football_data" / "competition_usage_history.json"


def _load(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def load_schedule_metadata(root: Path = SCHEDULE_ROOT) -> list[dict[str, Any]]:
    """Read only the schedule JSON metadata needed for demand recovery."""

    rows: list[dict[str, Any]] = []
    for path in sorted(root.glob("*.json")):
        data = _load(path, {})
        if not isinstance(data, dict):
            continue
        rows.append({
            "metadata_file": str(path.relative_to(ROOT)).replace("\\", "/"),
            "canonical_match_id": data.get("canonical_match_id"),
            "provider_match_id": data.get("provider_match_id") or data.get("nowscore_id"),
            "home": data.get("home"),
            "away": data.get("away"),
            "competition": data.get("competition"),
            "kickoff_local": data.get("kickoff_local"),
            "business_date": data.get("business_date"),
            "status": data.get("status"),
        })
    return rows


def load_current_matches(
    latest_path: Path = CURRENT_PATH,
    evidence_path: Path = CURRENT_EVIDENCE_PATH,
) -> list[dict[str, Any]]:
    """Load current-match metadata from both workspace and reviewed evidence.

    The automated workspace can be refreshed to an empty ``matches`` list
    after result settlement while the bounded, reviewed identity evidence
    still describes the active target fixtures.  Both inputs are passed to
    the demand collector, which deduplicates overlapping match IDs.
    """

    rows: list[dict[str, Any]] = []
    latest = _load(latest_path, {})
    if isinstance(latest, dict) and isinstance(latest.get("matches"), list):
        rows.extend(item for item in latest["matches"] if isinstance(item, dict))
    evidence = _load(evidence_path, {})
    if isinstance(evidence, dict) and isinstance(evidence.get("matches"), list):
        rows.extend(item for item in evidence["matches"] if isinstance(item, dict))
    return rows


def recover_from_repo(*, generated_at: str | None = None) -> dict[str, Any]:
    old_usage = _load(USAGE_PATH, {})
    tasks_doc = _load(TASKS_PATH, {})
    jobs_doc = _load(JOBS_PATH, {})
    selected = _load(SELECTED_PATH, [])
    timestamp = generated_at or datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    result = recover_competition_usage(
        schedule_rows=load_schedule_metadata(),
        prematch_tasks=tasks_doc.get("tasks", {}) if isinstance(tasks_doc, dict) else {},
        analysis_jobs=jobs_doc.get("jobs", {}) if isinstance(jobs_doc, dict) else {},
        selected_matches=selected if isinstance(selected, list) else [],
        current_matches=load_current_matches(),
        generated_at=timestamp,
        previous_usage=old_usage if isinstance(old_usage, dict) else {},
    )
    USAGE_PATH.parent.mkdir(parents=True, exist_ok=True)
    USAGE_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


if __name__ == "__main__":
    result = recover_from_repo()
    print(json.dumps({
        "analysis_jobs": result["job_recovery"]["analysis_job_count"],
        "jobs_recovered": result["job_recovery"]["recovered_count"],
        "jobs_unresolved": result["job_recovery"]["still_unresolved_count"],
        "resolved_matches": result["resolved_match_count"],
        "unresolved_matches": result["unresolved_match_count"],
        "competitions": len(result["windows"]["all_indexed_recent_production_period"]["competitions"]),
    }, ensure_ascii=False))
