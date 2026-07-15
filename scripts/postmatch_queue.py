#!/usr/bin/env python3
"""Build the automatic post-match review queue from frozen pre-match reports."""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


BASE_DIR = Path(__file__).resolve().parents[1]
REPORT_ROOT = BASE_DIR / "data" / "analysis_reports"
RUNTIME_PATH = BASE_DIR / "05_RUNTIME_STATE.json"
OUTPUT_PATH = BASE_DIR / "data" / "postmatch_automation" / "queue.json"
SHANGHAI = timezone(timedelta(hours=8))


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def normalize(text: Any) -> str:
    return re.sub(r"[\s\-—_｜|vsVS\.·]+", "", str(text or "")).casefold()


def parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    try:
        if "T" in text:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        else:
            parsed = datetime.strptime(text, "%Y-%m-%d %H:%M")
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=SHANGHAI)
        return parsed.astimezone(SHANGHAI)
    except ValueError:
        return None


def is_model_report(payload: dict[str, Any]) -> bool:
    probabilities = payload.get("model", {}).get("probabilities") or {}
    return all(isinstance(probabilities.get(key), (int, float)) for key in ("home", "draw", "away"))


def report_key(payload: dict[str, Any]) -> str:
    match = payload.get("match", {})
    shuju_id = match.get("shuju_id")
    if shuju_id not in (None, ""):
        return f"shuju:{shuju_id}"
    return "fixture:" + ":".join(
        normalize(match.get(field)) for field in ("home", "away", "kickoff_local")
    )


def reviewed_pairs(runtime: dict[str, Any]) -> set[tuple[str, str]]:
    pairs: set[tuple[str, str]] = set()
    for item in runtime.get("latest_reviewed_matches", []):
        match = str(item.get("match", ""))
        for separator in (" vs ", " VS ", "-", "—"):
            if separator in match:
                home, away = match.split(separator, 1)
                pairs.add((normalize(home), normalize(away)))
                break
    return pairs


def is_single_leg_knockout(payload: dict[str, Any]) -> bool:
    match = payload.get("match", {})
    haystack = " ".join(str(match.get(key, "")) for key in ("competition", "stage", "round", "format"))
    lowered = haystack.casefold()
    two_leg_markers = ("首回合", "次回合", "两回合", "second leg", "first leg", "2nd leg", "1st leg")
    if any(marker in lowered for marker in two_leg_markers):
        return False
    knockout_markers = (
        "单回合", "淘汰赛", "决赛", "半决赛", "四分之一决赛", "八分之一决赛", "附加赛",
        "knockout", "final", "semi-final", "semifinal", "quarter-final", "quarterfinal", "round of 16", "play-off", "playoff",
    )
    return any(marker in lowered for marker in knockout_markers)


def review_delay_minutes(payload: dict[str, Any], override: int | None = None) -> tuple[int, str]:
    if override is not None:
        return override, "manual_override"
    if is_single_leg_knockout(payload):
        return 195, "single_leg_knockout"
    return 135, "standard_90m"


def status_for(payload: dict[str, Any], now: datetime, delay_minutes: int, reviewed: set[tuple[str, str]]) -> str:
    match = payload.get("match", {})
    pair = (normalize(match.get("home")), normalize(match.get("away")))
    if pair in reviewed:
        return "reviewed"
    kickoff = parse_datetime(match.get("kickoff_local"))
    if kickoff is None:
        return "blocked_missing_kickoff"
    if now < kickoff + timedelta(minutes=delay_minutes):
        return "waiting_for_finish"
    return "pending_result_verification"


def build_queue(now: datetime, grace_override: int | None) -> dict[str, Any]:
    runtime = load_json(RUNTIME_PATH)
    latest: dict[str, tuple[datetime, float, Path, dict[str, Any]]] = {}
    ignored = 0
    invalid = 0
    for path in REPORT_ROOT.rglob("*.json"):
        try:
            payload = load_json(path)
        except (OSError, json.JSONDecodeError):
            invalid += 1
            continue
        if not is_model_report(payload):
            ignored += 1
            continue
        timestamp = parse_datetime(payload.get("report", {}).get("analysis_timestamp"))
        if timestamp is None:
            timestamp = datetime.fromtimestamp(path.stat().st_mtime, tz=SHANGHAI)
        key = report_key(payload)
        modified_at = path.stat().st_mtime
        if key not in latest or (timestamp, modified_at) > (latest[key][0], latest[key][1]):
            latest[key] = (timestamp, modified_at, path, payload)

    reviewed = reviewed_pairs(runtime)
    entries: list[dict[str, Any]] = []
    for key, (analysis_at, _modified_at, path, payload) in latest.items():
        match = payload.get("match", {})
        delay_minutes, schedule_type = review_delay_minutes(payload, grace_override)
        kickoff = parse_datetime(match.get("kickoff_local"))
        due_at = kickoff + timedelta(minutes=delay_minutes) if kickoff else None
        status = status_for(payload, now, delay_minutes, reviewed)
        entries.append(
            {
                "match_key": key,
                "status": status,
                "home": match.get("home"),
                "away": match.get("away"),
                "competition": match.get("competition"),
                "kickoff_local": match.get("kickoff_local"),
                "shuju_id": match.get("shuju_id"),
                "analysis_at": analysis_at.isoformat(),
                "source_report": path.relative_to(BASE_DIR).as_posix(),
                "result_policy": "90分钟含伤停，不含加时和点球",
                "schedule_type": schedule_type,
                "review_delay_minutes": delay_minutes,
                "review_due_at": due_at.isoformat() if due_at else None,
            }
        )
    entries.sort(key=lambda item: (item.get("kickoff_local") or "", item["match_key"]))
    counts: dict[str, int] = {}
    for entry in entries:
        counts[entry["status"]] = counts.get(entry["status"], 0) + 1
    return {
        "schema_version": "1.0",
        "generated_at": now.isoformat(),
        "standard_delay_minutes_after_kickoff": 135,
        "single_leg_knockout_delay_minutes_after_kickoff": 195,
        "grace_override_minutes": grace_override,
        "source_report_count": len(list(REPORT_ROOT.rglob("*.json"))),
        "latest_model_match_count": len(entries),
        "ignored_non_model_reports": ignored,
        "invalid_reports": invalid,
        "counts": counts,
        "pending": [entry for entry in entries if entry["status"] == "pending_result_verification"],
        "entries": entries,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    parser.add_argument("--grace-minutes", type=int, help="Override event-based delay for deterministic tests only")
    parser.add_argument("--now", help="ISO timestamp used for deterministic tests")
    args = parser.parse_args()
    now = parse_datetime(args.now) if args.now else datetime.now(SHANGHAI)
    if now is None:
        raise SystemExit("--now must be an ISO timestamp")
    queue = build_queue(now, args.grace_minutes)
    output = args.output if args.output.is_absolute() else BASE_DIR / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(queue, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output), "counts": queue["counts"], "pending": len(queue["pending"])}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
