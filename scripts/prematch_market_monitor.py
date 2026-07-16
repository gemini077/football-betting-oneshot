#!/usr/bin/env python3
"""Capture and recalculate selected pre-match checkpoints without betting."""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from prematch_fundamentals import collect_prematch_fundamentals


ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = ROOT / "data" / "match_workspace" / "latest.json"
INPUT_ROOT = ROOT / "data" / "analysis_inputs" / "automated"
STATE_PATH = ROOT / "data" / "market_history" / "monitor_state.json"
CHECKPOINT_ROOT = ROOT / "data" / "market_history" / "checkpoints"
CHECKPOINTS = (
    (480, "T-8H"),
    (360, "T-6H"),
    (240, "T-4H"),
    (120, "T-2H"),
    (90, "T-90M"),
    (60, "T-60M"),
    (30, "T-30M"),
    (10, "T-10M"),
)
TARGET_MINUTES = {stage: minutes for minutes, stage in CHECKPOINTS}
MAX_LATENESS_MINUTES = 25
SHANGHAI = ZoneInfo("Asia/Shanghai")


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def parse_time(value):
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def minutes_before_kickoff(match, now):
    kickoff = parse_time(match.get("kickoff"))
    if kickoff is None:
        return None
    if kickoff.tzinfo is None:
        kickoff = kickoff.replace(tzinfo=SHANGHAI)
    if now.tzinfo is None:
        now = now.replace(tzinfo=SHANGHAI)
    else:
        now = now.astimezone(SHANGHAI)
    return (kickoff - now).total_seconds() / 60


def due_stage(match, now, hours_before=8.0, completed=None, max_lateness_minutes=MAX_LATENESS_MINUTES):
    """Return only the nearest real checkpoint; never relabel an older miss."""
    minutes = minutes_before_kickoff(match, now)
    if minutes is None or minutes < 0 or minutes > hours_before * 60:
        return None
    candidates = []
    for target, stage in CHECKPOINTS:
        lateness = target - minutes
        if 0 <= lateness <= max_lateness_minutes:
            candidates.append((lateness, stage))
    if not candidates:
        return None
    _lateness, stage = min(candidates)
    return None if stage in (completed or {}) else stage


def checkpoint_meta(match, now, stage):
    actual = minutes_before_kickoff(match, now)
    target = TARGET_MINUTES[stage]
    return {
        "stage": stage,
        "captured_at": now.isoformat(),
        "target_minutes_before": target,
        "actual_minutes_before": round(actual, 2) if actual is not None else None,
        "lateness_minutes": round(target - actual, 2) if actual is not None else None,
        "exact": actual is not None and abs(target - actual) < 0.51,
    }


def due_matches(workspace, now, hours_before=8.0, state=None):
    state = state or {}
    rows = []
    for match in workspace.get("matches") or []:
        if str(match.get("report_state") or "") not in {"已分析", "仅市场基线"}:
            continue
        completed = state.get(str(match.get("id") or "")) or {}
        stage = due_stage(match, now, hours_before, completed=completed)
        if stage:
            rows.append({**match, "_monitor_stage": stage})
    return sorted(rows, key=lambda row: row.get("kickoff") or "")


def matching_analysis(match):
    match_id = str(match.get("id") or "")
    home, away = str(match.get("home") or ""), str(match.get("away") or "")
    for path in sorted(INPUT_ROOT.glob("*.json"), reverse=True):
        try:
            candidate = load_json(path).get("match") or {}
        except (OSError, json.JSONDecodeError):
            continue
        if match_id and str(candidate.get("match_id") or "") == match_id:
            return path
        if candidate.get("home") == home and candidate.get("away") == away:
            return path
    return None


def run_json(command, timeout=240):
    completed = subprocess.run(
        command, cwd=ROOT, text=True, capture_output=True,
        encoding="utf-8", errors="replace", timeout=timeout,
    )
    if completed.returncode:
        raise RuntimeError(completed.stderr or completed.stdout)
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError:
        for match in reversed(list(re.finditer(r"(?m)^\s*\{", completed.stdout))):
            try:
                return json.loads(completed.stdout[match.start():])
            except json.JSONDecodeError:
                continue
        raise RuntimeError(f"Command did not return JSON: {' '.join(command)}")


def refresh_fundamentals(analysis_path, match):
    """Compatibility helper retained for direct tests and manual refreshes."""
    payload = load_json(analysis_path)
    checked = collect_prematch_fundamentals(match, {})
    fundamentals = payload.setdefault("fundamentals", {})
    merged = {
        str(item.get("label") or ""): item
        for item in fundamentals.get("items") or [] if item.get("label")
    }
    for item in checked.get("items") or []:
        label = str(item.get("label") or "")
        if label:
            merged[label] = item
    fundamentals["items"] = list(merged.values())
    fundamentals["status"] = checked.get("status") or fundamentals.get("status")
    fundamentals["sources"] = checked.get("sources") or fundamentals.get("sources") or []
    Path(analysis_path).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return checked.get("status")


def refresh_match(match, stage=None, now=None):
    """Fetch a new snapshot and recalculate the complete deterministic model."""
    from deepseek_auto_analysis import analysis_context, deterministic_analysis, report_manifest

    now = now or datetime.now().astimezone()
    stage = stage or due_stage(match, now)
    label = f"{match.get('home')} vs {match.get('away')}"
    match_id = str(match.get("id") or "")
    if not stage:
        return {"match": label, "status": "skipped_not_at_checkpoint"}
    request = {
        "business_date": str(match.get("business_date") or ""),
        "match_id": match_id,
        "match": label,
    }
    fetched = run_json([
        sys.executable, "scripts/fetch_football_data.py",
        "--date", request["business_date"], "--match", match_id or label,
        "--deep", "--no-cache",
    ])
    manifest_path = Path(fetched["manifest"])
    if not manifest_path.is_absolute():
        manifest_path = ROOT / manifest_path
    context = analysis_context(manifest_path, request)
    analysis = deterministic_analysis(context, request)
    checkpoint = checkpoint_meta(match, now, stage)
    analysis.setdefault("report", {})["market_checkpoint"] = checkpoint
    analysis.setdefault("automation", {})["market_refresh"] = {
        **checkpoint,
        "model_recalculated": True,
        "execution_authorized": False,
        "lock_state_changed": False,
        "bankroll_state_changed": False,
    }

    INPUT_ROOT.mkdir(parents=True, exist_ok=True)
    stamp = now.strftime("%Y%m%d_%H%M%S")
    safe_id = re.sub(r"[^A-Za-z0-9_-]", "_", match_id or "match")
    analysis_path = INPUT_ROOT / f"{stamp}_{safe_id}_{stage}.json"
    analysis_path.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    render_manifest = report_manifest(manifest_path, context)
    report = run_json([
        sys.executable, "scripts/generate_analysis_report.py",
        "--fetch-manifest", str(render_manifest), "--analysis-json", str(analysis_path),
    ])
    report_path = report.get("report") or report.get("html")
    checkpoint_record = {
        **checkpoint,
        "match_id": match_id,
        "home": match.get("home"),
        "away": match.get("away"),
        "kickoff": match.get("kickoff"),
        "fetch_manifest": str(manifest_path.relative_to(ROOT)).replace("\\", "/"),
        "analysis_input": str(analysis_path.relative_to(ROOT)).replace("\\", "/"),
        "report_html": report_path,
        "model_recalculated": True,
        "real_bet_created": False,
    }
    checkpoint_path = CHECKPOINT_ROOT / safe_id / f"{stage}.json"
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    checkpoint_path.write_text(json.dumps(checkpoint_record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "match": label, "status": "refreshed", "stage": stage,
        "checkpoint": checkpoint, "report": report_path,
        "model_recalculated": True,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--now")
    parser.add_argument("--hours-before", type=float, default=8.0)
    parser.add_argument("--count-due", action="store_true")
    args = parser.parse_args()
    now = parse_time(args.now) if args.now else datetime.now().astimezone()
    if now is None:
        raise SystemExit("--now must be an ISO timestamp")
    workspace = load_json(WORKSPACE) if WORKSPACE.exists() else {"matches": []}
    state = load_json(STATE_PATH) if STATE_PATH.exists() else {}
    due = due_matches(workspace, now, args.hours_before, state)
    if args.count_due:
        print(len(due))
        return 0

    results = []
    for match in due:
        try:
            result = refresh_match(match, match["_monitor_stage"], now)
            results.append(result)
            if result.get("status") == "refreshed":
                stage = match["_monitor_stage"]
                state.setdefault(str(match.get("id") or ""), {})[stage] = result["checkpoint"]
        except Exception as error:
            results.append({
                "match": f"{match.get('home')} vs {match.get('away')}",
                "stage": match.get("_monitor_stage"),
                "status": "error", "error": str(error)[:1000],
            })
    if any(row.get("status") == "refreshed" for row in results):
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        run_json([
            sys.executable, "scripts/match_workspace.py", "--date",
            str(workspace.get("target_date") or now.date().isoformat()),
        ])
        subprocess.run([sys.executable, "scripts/build_public_site.py"], cwd=ROOT, check=True)
    print(json.dumps({"checked_at": now.isoformat(), "due": len(results), "results": results}, ensure_ascii=False, indent=2))
    return 1 if any(row.get("status") == "error" for row in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
