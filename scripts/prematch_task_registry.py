#!/usr/bin/env python3
"""Persistent match-level registry for deterministic pre-match checkpoints."""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from match_identity import canonical_match_id


ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = ROOT / "data" / "market_history" / "prematch_tasks.json"
WORKSPACE_PATH = ROOT / "data" / "match_workspace" / "latest.json"
REPORT_ROOT = ROOT / "data" / "analysis_reports" / "current"
LEGACY_STATE_PATH = ROOT / "data" / "market_history" / "monitor_state.json"
SHANGHAI = ZoneInfo("Asia/Shanghai")
CHECKPOINTS = (
    (480, "T-8H"), (360, "T-6H"), (240, "T-4H"), (120, "T-2H"),
    (90, "T-90M"), (60, "T-60M"), (30, "T-30M"), (10, "T-10M"),
)
TERMINAL_STATUSES = {
    "report_updated",
    "report_failed",
    "source_unavailable",
    "captured",
    "historical_recovery",
    "late_live",
    "permanently_missing",
}


def parse_time(value) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=SHANGHAI) if parsed.tzinfo is None else parsed.astimezone(SHANGHAI)


def load_registry(path: Path = REGISTRY_PATH) -> dict:
    if not path.exists():
        return {"schema_version": "2.0", "updated_at": None, "tasks": {}}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"schema_version": "2.0", "updated_at": None, "tasks": {}}
    payload.setdefault("schema_version", "2.0")
    payload.setdefault("tasks", {})
    return payload


def save_registry(payload: dict, path: Path = REGISTRY_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload["schema_version"] = "2.0"
    payload["updated_at"] = datetime.now(SHANGHAI).isoformat(timespec="seconds")
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _report_matches(report_root: Path = REPORT_ROOT) -> list[dict]:
    matches = []
    if not report_root.exists():
        return matches
    for path in report_root.glob("*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        match = payload.get("match") or {}
        kickoff = match.get("kickoff") or match.get("kickoff_local")
        if not match.get("home") or not match.get("away") or not kickoff:
            continue
        matches.append({
            "id": match.get("provider_match_id") or match.get("match_id"),
            "canonical_match_id": match.get("canonical_match_id"),
            "home": match.get("home"), "away": match.get("away"),
            "league": match.get("league") or match.get("competition"),
            "business_date": match.get("business_date"),
            "kickoff": kickoff, "match_num": match.get("match_num"),
            "report_url": str(path.with_suffix(".html").relative_to(ROOT)).replace("\\", "/"),
            "report_state": "已分析",
        })
    return matches


def _is_analyzed(match: dict) -> bool:
    return bool(match.get("report_url") or match.get("analysis_report") or match.get("report_state") == "已分析")


def _planned_checkpoints(kickoff: datetime, existing: dict | None = None) -> dict:
    existing = existing or {}
    checkpoints = {}
    for minutes, stage in CHECKPOINTS:
        prior = existing.get(stage) if isinstance(existing.get(stage), dict) else {}
        checkpoints[stage] = {
            "stage": stage,
            "planned_at": (kickoff - timedelta(minutes=minutes)).isoformat(timespec="seconds"),
            "status": prior.get("status", "pending"),
            **{key: value for key, value in prior.items() if key not in {"stage", "planned_at", "status"}},
        }
    return checkpoints


def register_match(registry: dict, match: dict) -> str | None:
    kickoff = parse_time(match.get("kickoff") or match.get("kickoff_local"))
    if kickoff is None or not _is_analyzed(match):
        return None
    canonical_id = str(match.get("canonical_match_id") or canonical_match_id(match))
    existing = (registry.get("tasks") or {}).get(canonical_id) or {}
    registry.setdefault("tasks", {})[canonical_id] = {
        "canonical_match_id": canonical_id,
        "provider_match_id": match.get("id") or match.get("provider_match_id"),
        "home": match.get("home"), "away": match.get("away"),
        "league": match.get("league") or match.get("competition"),
        "business_date": match.get("business_date"), "match_num": match.get("match_num"),
        "kickoff": kickoff.isoformat(timespec="minutes"),
        "report_url": match.get("report_url") or match.get("analysis_report") or existing.get("report_url"),
        "registered_at": existing.get("registered_at") or datetime.now(SHANGHAI).isoformat(timespec="seconds"),
        "checkpoints": _planned_checkpoints(kickoff, existing.get("checkpoints")),
    }
    return canonical_id


def sync_registry(
    registry_path: Path = REGISTRY_PATH,
    workspace_path: Path = WORKSPACE_PATH,
    report_root: Path = REPORT_ROOT,
    legacy_state_path: Path = LEGACY_STATE_PATH,
) -> dict:
    registry = load_registry(registry_path)
    matches = []
    if workspace_path.exists():
        try:
            matches.extend((json.loads(workspace_path.read_text(encoding="utf-8")).get("matches") or []))
        except (OSError, json.JSONDecodeError):
            pass
    matches.extend(_report_matches(report_root))
    registered = 0
    for match in matches:
        if register_match(registry, match):
            registered += 1
    if legacy_state_path.exists():
        try:
            legacy = json.loads(legacy_state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            legacy = {}
        for canonical_id, stages in legacy.items():
            task = (registry.get("tasks") or {}).get(canonical_id)
            if not task or not isinstance(stages, dict):
                continue
            for stage, old in stages.items():
                checkpoint = (task.get("checkpoints") or {}).get(stage)
                if checkpoint is None or not isinstance(old, dict):
                    continue
                status = old.get("status", "captured")
                checkpoint.update({**old, "status": status})
    now = datetime.now(SHANGHAI)
    for task in (registry.get("tasks") or {}).values():
        kickoff = parse_time(task.get("kickoff"))
        if kickoff is None or now <= kickoff + timedelta(hours=6):
            continue
        for checkpoint in (task.get("checkpoints") or {}).values():
            if checkpoint.get("status") in TERMINAL_STATUSES:
                continue
            prior_error = checkpoint.get("last_error") or checkpoint.get("error")
            checkpoint.update({
                "status": "permanently_missing",
                "reason": "任务登记时已超过赛后六小时恢复窗，未伪造历史快照。",
            })
            checkpoint["closed_at"] = now.isoformat(timespec="seconds")
            if prior_error:
                checkpoint["last_error"] = prior_error
    save_registry(registry, registry_path)
    return {"registered_sources": registered, "task_count": len(registry.get("tasks") or {}), "registry": registry}


def due_events(registry: dict, now: datetime, match_id: str | None = None, stage: str | None = None) -> list[dict]:
    now = parse_time(now.isoformat()) or now
    events = []
    for canonical_id, task in (registry.get("tasks") or {}).items():
        if match_id and match_id not in {canonical_id, str(task.get("provider_match_id") or "")}:
            continue
        kickoff = parse_time(task.get("kickoff"))
        if kickoff is None or now > kickoff + timedelta(hours=6):
            continue
        for checkpoint_stage, checkpoint in (task.get("checkpoints") or {}).items():
            if stage and checkpoint_stage != stage:
                continue
            if checkpoint.get("status") in TERMINAL_STATUSES:
                continue
            planned = parse_time(checkpoint.get("planned_at"))
            if planned and planned <= now:
                events.append({
                    **task, "id": task.get("provider_match_id"), "_canonical_match_id": canonical_id,
                    "_monitor_stage": checkpoint_stage, "_planned_at": planned.isoformat(),
                    "_lateness_minutes": round((now - planned).total_seconds() / 60, 2),
                })
    return sorted(events, key=lambda row: (row.get("_planned_at") or "", row.get("kickoff") or ""))


def update_checkpoint(registry: dict, canonical_id: str, stage: str, status: str, **fields) -> None:
    checkpoint = registry["tasks"][canonical_id]["checkpoints"][stage]
    checkpoint.update({"status": status, **fields})


if __name__ == "__main__":
    result = sync_registry()
    print(json.dumps({key: value for key, value in result.items() if key != "registry"}, ensure_ascii=False, indent=2))
