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
from decision_evolution import append_record, attach_evolution
from match_identity import canonical_match_id, identity_aliases


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


def due_stage(match, now, hours_before=8.0, completed=None, max_lateness_minutes=None):
    """Return the nearest passed checkpoint.

    GitHub schedules are best effort and can be late.  A late run captures one
    real snapshot (never fabricates several historical snapshots) and labels
    it as recovery data instead of silently losing the entire match.
    """
    minutes = minutes_before_kickoff(match, now)
    if minutes is None or minutes < 0 or minutes > hours_before * 60:
        return None
    completed = completed or {}
    captured = {
        stage for stage, payload in completed.items()
        if not isinstance(payload, dict) or payload.get("status", "captured") == "captured"
    }
    candidates = []
    for target, stage in CHECKPOINTS:
        lateness = target - minutes
        if lateness >= 0:
            candidates.append((lateness, stage))
    if not candidates:
        return None
    _lateness, stage = min(candidates)
    return None if stage in captured else stage


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
        "capture_quality": "on_time" if actual is not None and abs(target - actual) <= 5 else "late_recovery",
    }


def due_matches(workspace, now, hours_before=8.0, state=None):
    state = state or {}
    rows = []
    for match in workspace.get("matches") or []:
        report_ready = bool(match.get("report_url") or match.get("analysis_report"))
        if not report_ready and str(match.get("report_state") or "") not in {"已分析", "仅市场基线"}:
            continue
        canonical_id = canonical_match_id(match)
        completed = state.get(canonical_id) or {}
        if not completed:
            for alias in identity_aliases(match):
                if isinstance(state.get(alias), dict):
                    completed.update(state[alias])
        stage = due_stage(match, now, hours_before, completed=completed)
        if stage:
            rows.append({**match, "_monitor_stage": stage, "_canonical_match_id": canonical_id})
    return sorted(rows, key=lambda row: row.get("kickoff") or "")


def matching_analysis(match):
    match_id = str(match.get("id") or "")
    canonical_id = canonical_match_id(match)
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
    # Keep every snapshot, report and post-match task on the same stable key.
    # Previously this variable was only created by the outer loop, so the
    # scheduled GitHub runner crashed before it could publish any checkpoint.
    canonical_id = match.get("_canonical_match_id") or canonical_match_id(match)
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
    analysis.setdefault("match", {})["canonical_match_id"] = canonical_id
    analysis.setdefault("match", {})["provider_match_id"] = match_id
    analysis, evolution_record = attach_evolution(analysis, canonical_id, checkpoint)
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
    append_record(evolution_record)
    checkpoint_record = {
        **checkpoint,
        "match_id": match_id,
        "canonical_match_id": canonical_id,
        "home": match.get("home"),
        "away": match.get("away"),
        "kickoff": match.get("kickoff"),
        "fetch_manifest": str(manifest_path.relative_to(ROOT)).replace("\\", "/"),
        "analysis_input": str(analysis_path.relative_to(ROOT)).replace("\\", "/"),
        "report_html": report_path,
        "model_recalculated": True,
        "real_bet_created": False,
        "decision": evolution_record.get("decision"),
        "change": evolution_record.get("change"),
    }
    checkpoint_path = CHECKPOINT_ROOT / canonical_id / f"{stage}.json"
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    checkpoint_path.write_text(json.dumps(checkpoint_record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "match": label, "status": "refreshed", "stage": stage,
        "checkpoint": checkpoint, "report": report_path,
        "model_recalculated": True, "change": evolution_record.get("change"),
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
        canonical_id = match.get("_canonical_match_id") or canonical_match_id(match)
        try:
            result = refresh_match(match, match["_monitor_stage"], now)
            results.append(result)
            if result.get("status") == "refreshed":
                stage = match["_monitor_stage"]
                state.setdefault(canonical_id, {})[stage] = {
                    **result["checkpoint"], "status": "captured"
                }
        except Exception as error:
            stage = match.get("_monitor_stage")
            state.setdefault(canonical_id, {})[stage] = {
                "status": "failed",
                "last_attempt_at": now.isoformat(),
                "error": str(error)[:1000],
            }
            results.append({
                "match": f"{match.get('home')} vs {match.get('away')}",
                "stage": match.get("_monitor_stage"),
                "status": "error", "error": str(error)[:1000],
            })
    if results:
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if any(row.get("status") == "refreshed" for row in results):
        run_json([
            sys.executable, "scripts/match_workspace.py", "--date",
            str(workspace.get("target_date") or now.date().isoformat()),
        ])
        subprocess.run([sys.executable, "scripts/build_public_site.py"], cwd=ROOT, check=True)
    errors = [row for row in results if row.get("status") == "error"]
    if errors:
        error_dir = ROOT / "data" / "market_history" / "errors"
        error_dir.mkdir(parents=True, exist_ok=True)
        error_stamp = now.strftime("%Y%m%d_%H%M%S")
        (error_dir / f"{error_stamp}_monitor_errors.json").write_text(
            json.dumps({"checked_at": now.isoformat(), "errors": errors}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    print(json.dumps({"checked_at": now.isoformat(), "due": len(results), "results": results}, ensure_ascii=False, indent=2))
    # A single provider/match failure must not discard checkpoints that were
    # refreshed successfully in the same cycle.  Failed rows remain absent
    # from state and are therefore eligible for the next bounded retry.
    has_success = any(row.get("status") == "refreshed" for row in results)
    has_error = any(row.get("status") == "error" for row in results)
    return 1 if has_error and not has_success else 0


if __name__ == "__main__":
    raise SystemExit(main())
