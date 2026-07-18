#!/usr/bin/env python3
"""One-time/idempotent migration of automation records to canonical match ids."""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

from match_identity import canonical_match_id, parse_kickoff


ROOT = Path(__file__).resolve().parents[1]
SCHEDULES = ROOT / "data" / "postmatch_automation" / "schedules"
STATE = ROOT / "data" / "market_history" / "monitor_state.json"
FINAL = {"reviewed": 4, "result_verified": 3, "retry_scheduled": 2, "scheduled": 1, "blocked_result_not_final": 0}


def load(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def migrate_schedules(now: datetime | None = None) -> dict:
    now = now or datetime.now().astimezone()
    groups: dict[str, list[tuple[Path, dict]]] = {}
    for path in SCHEDULES.glob("*.json"):
        row = load(path, {})
        if not row:
            continue
        key = canonical_match_id(row)
        groups.setdefault(key, []).append((path, row))
    written, removed = 0, 0
    for key, rows in groups.items():
        _best_path, best = max(rows, key=lambda item: (FINAL.get(str(item[1].get("status")), -1), int(item[1].get("verification_attempts") or 0)))
        merged = dict(best)
        merged["match_key"] = key
        merged["canonical_match_id"] = key
        for _path, row in rows:
            for field in ("shuju_id", "nowscore_id", "provider_match_id", "result_90m", "result_file", "review_file", "result_source"):
                if merged.get(field) in (None, "") and row.get(field) not in (None, ""):
                    merged[field] = row[field]
        kickoff = parse_kickoff(merged.get("kickoff_local"))
        if kickoff:
            merged["verification_expires_at"] = (kickoff + timedelta(hours=24)).isoformat()
        merged["retry_policy"] = {"maximum_retries": 24, "retry_after_minutes": 30, "only_when_result_not_final": True}
        if merged.get("status") == "blocked_result_not_final" and kickoff and now < kickoff + timedelta(hours=24):
            merged["status"] = "retry_scheduled"
            merged["review_due_at"] = now.isoformat()
        target = SCHEDULES / f"{key}.json"
        target.write_text(json.dumps(merged, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        written += 1
        for path, _row in rows:
            if path != target and path.exists():
                path.unlink()
                removed += 1
    return {"canonical_schedules": written, "legacy_removed": removed}


def migrate_monitor_state() -> dict:
    state = load(STATE, {})
    canonical: dict[str, dict] = {}
    # Checkpoint records contain the provider id plus teams/kickoff and are the
    # safest bridge from old keys to the canonical key.
    for path in (ROOT / "data" / "market_history" / "checkpoints").glob("*/*.json"):
        row = load(path, {})
        if not row:
            continue
        key = canonical_match_id(row)
        old = str(row.get("match_id") or path.parent.name)
        source = state.get(old) or {}
        stage = str(row.get("stage") or path.stem)
        canonical.setdefault(key, {})[stage] = {
            **(source.get(stage) or {}),
            "status": "captured",
            "captured_at": row.get("captured_at"),
            "actual_minutes_before": row.get("actual_minutes_before"),
        }
    # Keep unmatched legacy rows for audit, while canonical rows become the
    # only keys used by new automation.
    state.update(canonical)
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"canonical_monitor_matches": len(canonical)}


def main() -> int:
    print(json.dumps({**migrate_schedules(), **migrate_monitor_state()}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
