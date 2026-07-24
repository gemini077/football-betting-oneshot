#!/usr/bin/env python3
"""Capture and recalculate selected pre-match checkpoints without betting."""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from prematch_fundamentals import collect_prematch_fundamentals
from decision_evolution import append_record, attach_evolution
from match_identity import canonical_match_id, identity_aliases
from historical_market_recovery import recover_manifest
from fetch_and_parse import DEFAULT_CACHE_DIR as DEEP_CACHE_DIR, fetch_and_parse
from nowscore_markets import fetch_match_markets as fetch_nowscore_markets
from prematch_task_registry import (
    due_events, load_registry, save_registry, sync_registry, update_checkpoint,
)


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
MAX_ATTEMPTS = 2


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
    """Compatibility helper returning the earliest overdue uncaptured stage."""
    stages = due_stages(match, now, hours_before, completed)
    return stages[0] if stages else None


def due_stages(match, now, hours_before=8.0, completed=None):
    """Return every elapsed checkpoint that is not durably completed."""
    minutes = minutes_before_kickoff(match, now)
    if minutes is None or minutes < -360 or minutes > hours_before * 60:
        return []
    completed = completed or {}
    captured = {
        stage for stage, payload in completed.items()
        if not isinstance(payload, dict) or payload.get("status", "captured")
        in {
            "report_updated", "report_failed", "source_unavailable",
            "captured", "historical_recovery", "late_live", "permanently_missing",
        }
    }
    candidates = []
    for target, stage in CHECKPOINTS:
        if target - minutes >= 0 and stage not in captured:
            candidates.append(stage)
    return candidates


def checkpoint_meta(match, now, stage):
    actual = minutes_before_kickoff(match, now)
    target = TARGET_MINUTES[stage]
    kickoff = parse_time(match.get("kickoff"))
    if kickoff and kickoff.tzinfo is None:
        kickoff = kickoff.replace(tzinfo=SHANGHAI)
    planned = kickoff - timedelta(minutes=target) if kickoff else None
    return {
        "stage": stage,
        "scheduled_at": planned.isoformat() if planned else None,
        "captured_at": now.astimezone(SHANGHAI).isoformat(),
        "target_minutes_before": target,
        "actual_minutes_before": round(actual, 2) if actual is not None else None,
        "lateness_minutes": round(target - actual, 2) if actual is not None else None,
        "exact": actual is not None and abs(target - actual) < 0.51,
        "capture_quality": "on_time" if actual is not None and abs(target - actual) <= 5 else "pending_recovery",
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
        for stage in due_stages(match, now, hours_before, completed=completed):
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


def _relative(path: Path) -> str:
    return str(path.relative_to(ROOT)).replace("\\", "/")


def _usable_500_snapshot(payload: dict) -> bool:
    return bool(
        ((payload.get("ouzhi") or {}).get("bookmakers") or [])
        or ((payload.get("yazhi") or {}).get("companies") or [])
        or ((payload.get("daxiao") or {}).get("companies") or [])
    )


def capture_market_snapshot(match: dict, stage: str, now: datetime) -> Path:
    """Persist Nowscore-first evidence without depending on a live schedule list."""
    stamp = now.astimezone(SHANGHAI).strftime("%Y%m%d_%H%M%S")
    safe_stage = stage.replace("-", "_")
    run_dir = ROOT / "data" / "fetch_runs" / f"{stamp}_checkpoint_{safe_stage}"
    suffix = 1
    while run_dir.exists():
        run_dir = ROOT / "data" / "fetch_runs" / f"{stamp}_checkpoint_{safe_stage}_{suffix:02d}"
        suffix += 1
    run_dir.mkdir(parents=True)
    home, away = str(match.get("home") or ""), str(match.get("away") or "")
    kickoff = match.get("kickoff")
    manifest = {
        "run_id": run_dir.name,
        "fetch_time": now.astimezone(SHANGHAI).isoformat(timespec="seconds"),
        "target_date": match.get("business_date"),
        "match_filter": f"{home} vs {away}",
        "checkpoint": stage,
        "analysis_input_only": True,
        "lock_state_changed": False,
        "sources": {},
        "warnings": [],
    }
    source_errors = []
    try:
        nowscore = fetch_nowscore_markets(home, away, kickoff, None, True)
    except Exception as error:
        nowscore = {
            "source": "nowscore_public_3in1",
            "status": "FETCH_ERROR",
            "error": f"{type(error).__name__}: {error}",
        }
    nowscore_path = run_dir / f"{stamp}_nowscore.json"
    nowscore_path.write_text(json.dumps(nowscore, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    nowscore_ok = nowscore.get("status") == "OK"
    manifest["sources"]["nowscore"] = {
        "status": nowscore.get("status") or "UNKNOWN",
        "success": nowscore_ok,
        "match_count": 1 if nowscore_ok else 0,
        "matches": [{"file": _relative(nowscore_path), "status": nowscore.get("status")}],
        "analysis_input_only": True,
    }
    if not nowscore_ok:
        source_errors.append(f"nowscore: {nowscore.get('error') or nowscore.get('status')}")

    provider_id = str(match.get("provider_match_id") or match.get("id") or "")
    shuju_match = re.fullmatch(r"500-(\d+)", provider_id, flags=re.IGNORECASE)
    if not nowscore_ok and shuju_match:
        shuju_id = int(shuju_match.group(1))
        try:
            fallback = fetch_and_parse(
                shuju_id,
                str(match.get("business_date") or str(kickoff or "")[:10]),
                DEEP_CACHE_DIR,
                True,
            )
        except Exception as error:
            fallback = {"shuju_id": shuju_id, "error": f"{type(error).__name__}: {error}"}
        fallback_path = run_dir / f"{stamp}_500_deep_{shuju_id}.json"
        fallback_path.write_text(json.dumps(fallback, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        fallback_ok = _usable_500_snapshot(fallback)
        manifest["sources"]["500_deep"] = {
            "status": "OK" if fallback_ok else "FAILED",
            "success": fallback_ok,
            "match_count": 1 if fallback_ok else 0,
            "matches": [{
                "file": _relative(fallback_path),
                "shuju_id": shuju_id,
                "all_pages_ok": fallback_ok,
            }],
        }
        if not fallback_ok:
            source_errors.append(f"500.com: {fallback.get('error') or 'no usable market rows'}")

    manifest["source_errors"] = source_errors
    manifest_path = run_dir / f"{stamp}_fetch_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if not any(source.get("success") for source in manifest["sources"].values()):
        raise RuntimeError("; ".join(source_errors) or "no usable checkpoint market source")
    return manifest_path


def refresh_match(match, stage=None, now=None):
    """Fetch a new snapshot and recalculate the complete deterministic model."""
    from deepseek_auto_analysis import analysis_context, deterministic_analysis, report_manifest

    now = now or datetime.now(SHANGHAI)
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
        "match_snapshot": {
            "id": match_id,
            "canonical_match_id": canonical_id,
            "home": match.get("home"),
            "away": match.get("away"),
            "league": match.get("league"),
            "business_date": match.get("business_date"),
            "kickoff": match.get("kickoff"),
            "match_num": match.get("match_num"),
        },
    }
    checkpoint = checkpoint_meta(match, now, stage)
    checkpoint_path = CHECKPOINT_ROOT / canonical_id / f"{stage}.json"
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    existing = {}
    if checkpoint_path.exists():
        try:
            existing = load_json(checkpoint_path)
        except (OSError, json.JSONDecodeError):
            existing = {}
    existing_manifest = existing.get("fetch_manifest")
    manifest_path = ROOT / existing_manifest if existing_manifest else None
    if manifest_path is None or not manifest_path.exists():
        manifest_path = capture_market_snapshot(match, stage, now)
        capture_record = {
            **checkpoint,
            "status": "snapshot_captured",
            "report_status": "pending",
            "match_id": match_id,
            "canonical_match_id": canonical_id,
            "home": match.get("home"),
            "away": match.get("away"),
            "kickoff": match.get("kickoff"),
            "fetch_manifest": _relative(manifest_path),
            "model_recalculated": False,
            "real_bet_created": False,
        }
        checkpoint_path.write_text(
            json.dumps(capture_record, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        existing = capture_record
    else:
        checkpoint.update({
            key: existing.get(key)
            for key in ("scheduled_at", "captured_at", "target_minutes_before",
                        "actual_minutes_before", "lateness_minutes", "exact", "capture_quality")
            if existing.get(key) is not None
        })
    recovery = None
    if float(checkpoint.get("lateness_minutes") or 0) > 5:
        recovery = recover_manifest(manifest_path, checkpoint.get("scheduled_at"))
        checkpoint["capture_quality"] = (
            "historical_recovery" if recovery.get("status") == "recovered" else "late_live"
        )
        checkpoint["historical_recovery"] = recovery
        kickoff = parse_time(match.get("kickoff"))
        if kickoff and kickoff.tzinfo is None:
            kickoff = kickoff.replace(tzinfo=SHANGHAI)
        if recovery.get("status") != "recovered" and kickoff and now >= kickoff:
            checkpoint["capture_quality"] = "permanently_missing"
            return {
                "match": label,
                "status": "missed_checkpoint",
                "stage": stage,
                "checkpoint": checkpoint,
                "model_recalculated": False,
                "reason": "赛前历史轨迹没有该节点，且比赛已经开赛；保留原报告，不用当前价冒充历史价。",
            }
    try:
        context = analysis_context(manifest_path, request)
        analysis = deterministic_analysis(context, request)
    except Exception as error:
        failed = {
            **existing,
            **checkpoint,
            "status": "snapshot_captured",
            "report_status": "failed",
            "fetch_manifest": _relative(manifest_path),
            "report_error": f"{type(error).__name__}: {error}"[:1000],
        }
        checkpoint_path.write_text(json.dumps(failed, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return {
            "match": label,
            "status": "snapshot_captured",
            "stage": stage,
            "checkpoint": checkpoint,
            "report_error": failed["report_error"],
            "model_recalculated": False,
        }
    analysis.setdefault("match", {})["canonical_match_id"] = canonical_id
    analysis.setdefault("match", {})["provider_match_id"] = match_id
    analysis, evolution_record = attach_evolution(analysis, canonical_id, checkpoint)
    analysis.setdefault("report", {})["market_checkpoint"] = checkpoint
    analysis.setdefault("report", {})["checkpoint_health"] = {
        "stage": stage, "scheduled_at": checkpoint.get("scheduled_at"),
        "captured_at": checkpoint.get("captured_at"),
        "status": checkpoint.get("capture_quality"),
        "recovered_quotes": ((recovery or {}).get("recovered_quotes") or 0),
    }
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
    try:
        report = run_json([
            sys.executable, "scripts/generate_analysis_report.py",
            "--fetch-manifest", str(render_manifest), "--analysis-json", str(analysis_path),
        ])
    except Exception as error:
        failed = {
            **checkpoint,
            "status": "snapshot_captured",
            "report_status": "failed",
            "match_id": match_id,
            "canonical_match_id": canonical_id,
            "home": match.get("home"),
            "away": match.get("away"),
            "kickoff": match.get("kickoff"),
            "fetch_manifest": _relative(manifest_path),
            "analysis_input": _relative(analysis_path),
            "report_error": f"{type(error).__name__}: {error}"[:1000],
            "model_recalculated": True,
            "real_bet_created": False,
        }
        checkpoint_path.write_text(json.dumps(failed, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return {
            "match": label,
            "status": "snapshot_captured",
            "stage": stage,
            "checkpoint": checkpoint,
            "report_error": failed["report_error"],
            "model_recalculated": True,
        }
    report_path = report.get("report") or report.get("html")
    append_record(evolution_record)
    checkpoint_record = {
        **checkpoint,
        "status": "report_updated",
        "report_status": "updated",
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
    checkpoint_path.write_text(json.dumps(checkpoint_record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "match": label, "status": "report_updated", "stage": stage,
        "checkpoint": checkpoint, "report": report_path,
        "model_recalculated": True, "change": evolution_record.get("change"),
    }


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--now")
    parser.add_argument("--hours-before", type=float, default=8.0)
    parser.add_argument("--count-due", action="store_true")
    parser.add_argument("--match-id", help="只处理一个canonical/provider比赛ID")
    parser.add_argument("--checkpoint", choices=[stage for _, stage in CHECKPOINTS])
    parser.add_argument("--sync-tasks", action="store_true")
    parser.add_argument("--max-events", type=int, default=1)
    args = parser.parse_args()
    now = parse_time(args.now) if args.now else datetime.now(SHANGHAI)
    if now is None:
        raise SystemExit("--now must be an ISO timestamp")
    workspace = load_json(WORKSPACE) if WORKSPACE.exists() else {"matches": []}
    state = load_json(STATE_PATH) if STATE_PATH.exists() else {}
    if args.sync_tasks:
        synced = sync_registry()
        registry = synced["registry"]
    else:
        registry = load_registry()
        synced = {"task_count": len(registry.get("tasks") or {})}
    due = due_events(registry, now, args.match_id, args.checkpoint)
    if args.sync_tasks and not args.count_due:
        print(json.dumps({"checked_at": now.isoformat(), "task_count": synced["task_count"]}, ensure_ascii=False, indent=2))
        return 0
    if args.count_due:
        print(len(due))
        return 0
    due = due[:max(1, args.max_events)]

    results = []
    for match in due:
        canonical_id = match.get("_canonical_match_id") or canonical_match_id(match)
        try:
            result = refresh_match(match, match["_monitor_stage"], now)
            results.append(result)
            if result.get("status") in {"report_updated", "snapshot_captured", "missed_checkpoint"}:
                stage = match["_monitor_stage"]
                quality = (result.get("checkpoint") or {}).get("capture_quality") or "captured"
                current = registry["tasks"][canonical_id]["checkpoints"][stage]
                attempts = list(current.get("attempts") or [])
                attempts.append({
                    "at": now.isoformat(),
                    "result": result.get("status"),
                    "error": result.get("report_error"),
                })
                if result.get("status") == "report_updated":
                    durable_status = "report_updated"
                elif result.get("status") == "missed_checkpoint":
                    durable_status = "permanently_missing"
                else:
                    durable_status = "report_failed" if len(attempts) >= MAX_ATTEMPTS else "snapshot_captured"
                state.setdefault(canonical_id, {})[stage] = {
                    **result["checkpoint"],
                    "status": durable_status,
                    "capture_quality": quality,
                    "report_error": result.get("report_error"),
                }
                update_checkpoint(
                    registry, canonical_id, stage, durable_status,
                    captured_at=result["checkpoint"].get("captured_at"),
                    actual_minutes_before=result["checkpoint"].get("actual_minutes_before"),
                    lateness_minutes=result["checkpoint"].get("lateness_minutes"),
                    capture_quality=quality,
                    report_status="updated" if durable_status == "report_updated" else "failed",
                    report=result.get("report"),
                    reason=result.get("reason"),
                    last_error=result.get("report_error"),
                    attempts=attempts,
                )
        except Exception as error:
            stage = match.get("_monitor_stage")
            current = registry["tasks"][canonical_id]["checkpoints"][stage]
            attempts = list(current.get("attempts") or [])
            attempts.append({"at": now.isoformat(), "result": "source_error", "error": str(error)[:1000]})
            durable_status = "source_unavailable" if len(attempts) >= MAX_ATTEMPTS else "retry_wait"
            state.setdefault(canonical_id, {})[stage] = {
                "status": durable_status,
                "last_attempt_at": now.isoformat(),
                "error": str(error)[:1000],
                "attempts": attempts,
            }
            if canonical_id in registry.get("tasks", {}) and stage:
                update_checkpoint(
                    registry, canonical_id, stage, durable_status,
                    last_attempt_at=now.isoformat(),
                    error=str(error)[:1000],
                    last_error=str(error)[:1000],
                    attempts=attempts,
                )
            results.append({
                "match": f"{match.get('home')} vs {match.get('away')}",
                "stage": match.get("_monitor_stage"),
                "status": "error", "error": str(error)[:1000],
            })
    if results:
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        save_registry(registry)
    if any(row.get("status") == "report_updated" for row in results):
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
    has_success = any(row.get("status") in {"report_updated", "snapshot_captured"} for row in results)
    has_error = any(row.get("status") == "error" for row in results)
    return 1 if has_error and not has_success else 0


if __name__ == "__main__":
    raise SystemExit(main())
