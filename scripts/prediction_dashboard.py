#!/usr/bin/env python3
"""Build a read-only, accountable Prediction Day product surface."""

from __future__ import annotations

import argparse
import html
import json
import math
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

try:
    from prematch_versioning import select_latest_legal_prematch
except ImportError:  # package import used by tests
    from scripts.prematch_versioning import select_latest_legal_prematch

try:
    from production_health_watch import evaluate_exact_score_health, select_current_serving_predictions
except ImportError:  # package import used by tests
    from scripts.production_health_watch import evaluate_exact_score_health, select_current_serving_predictions

try:
    from current_serving_state import resolve_current_job_for_match
except ImportError:  # package import used by tests
    from scripts.current_serving_state import resolve_current_job_for_match

try:
    from exact_score_serving_policy import exact_score_serving_presentation
except ImportError:  # package import used by tests
    from scripts.exact_score_serving_policy import exact_score_serving_presentation

try:
    from closed_beta_copy import render_closed_beta_notice
except ImportError:  # package import used by tests
    from scripts.closed_beta_copy import render_closed_beta_notice

try:
    from formal_market_projection import (
        project_frozen_formal_markets,
        summarize_formal_markets,
    )
except ImportError:  # package import used by tests
    from scripts.formal_market_projection import (
        project_frozen_formal_markets,
        summarize_formal_markets,
    )


BASE_DIR = Path(__file__).resolve().parents[1]
UNIVERSE_ROOT = BASE_DIR / "data" / "prediction_universe"
JOBS_ROOT = BASE_DIR / "data" / "base_prediction_jobs"
PREDICTION_ROOT = BASE_DIR / "data" / "model_governance" / "predictions"
EXCLUSION_ROOT = BASE_DIR / "data" / "model_governance" / "prediction_exclusions"
RESULT_ROOT = BASE_DIR / "data" / "postmatch_automation" / "results"
PROSPECTIVE_ROOT = BASE_DIR / "data" / "prospective"
RUNTIME_PATH = BASE_DIR / "data" / "product_runtime" / "latest_cycle.json"
HEALTH_WATCH_PATH = BASE_DIR / "data" / "product_runtime" / "health_watch.json"
DASHBOARD_ROOT = BASE_DIR / "data" / "prediction_dashboard"
WORKSPACE_LATEST = BASE_DIR / "data" / "match_workspace" / "latest.json"
SHANGHAI = timezone(timedelta(hours=8))

STATUS_LABELS = {
    "CURRENT_JOB_STATE_CONFLICT": "本场状态待确认",
    "FROZEN": "已形成预测",
    "PENDING": "预测尚未形成",
    "INSUFFICIENT_DATA": "数据不足，暂不预测",
    "PREDICTION_FAILED": "本场未形成有效预测",
    "MISSED_PREMATCH_WINDOW": "未形成合法赛前预测",
    "REMOVED_FROM_CURRENT_UNIVERSE": "暂不在当前赛程",
}
REASON_LABELS = {
    "DUPLICATE_CURRENT_JOB_STATE": "本场状态待确认，暂不形成预测",
    "MULTIPLE_CURRENT_MATCH_GROUPS": "比赛身份待确认，暂不形成预测",
    "MISSING_RECENT_FORM": "近期比赛数据不足",
    "MISSING_MARKET_INTELLIGENCE": "市场信息不足",
    "INPUT_TIMESTAMP_UNVERIFIED": "赛前数据时间无法验证",
    "SOURCE_FETCH_FAILED": "赛前数据源获取失败",
    "CACHE_PROVENANCE_INVALID": "近期数据来源无法验证",
    "INPUT_SNAPSHOT_CONSTRUCTION_FAILED": "赛前输入快照构建失败",
    "INPUT_PROVENANCE_UNVERIFIED": "赛前输入来源无法验证",
    "IDENTITY_UNRESOLVED": "比赛身份无法可靠匹配",
    "PREDICTION_FAILED": "模型运行失败",
    "MISSED_PREMATCH_WINDOW": "未形成合法赛前预测",
    "BASE_JOB_MISSING": "预测任务尚未生成",
    "PREDICTION_ARTIFACT_MISSING": "预测任务已锁定，但正式记录缺失",
}


_CURRENT_FORMAL_STATUSES = {"formal", "frozen", "FROZEN"}
_QUALITY_STATUS_LABELS = {
    "HEALTHY": "正常",
    "ALERT": "异常",
    "INSUFFICIENT_SAMPLE": "样本不足",
    "WATCH": "观察",
    "UNKNOWN": "待确认",
}
_QUALITY_ALERT_COPY = "当前预测质量降级，仅供观察。"



def _read_json(path: Path, errors: list[str], label: str, default: Any) -> Any:
    if not path.is_file():
        errors.append(f"{label}:MISSING")
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        errors.append(f"{label}:INVALID")
        return default


def _read_optional_json(path: Path, errors: list[str], label: str, default: Any) -> Any:
    if not path.is_file():
        return default
    return _read_json(path, errors, label, default)


def _read_jsonl(path: Path, errors: list[str], label: str) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    try:
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            value = json.loads(line)
            if isinstance(value, dict):
                rows.append(value)
            else:
                errors.append(f"{label}:LINE_{line_number}_NOT_OBJECT")
    except (OSError, json.JSONDecodeError):
        errors.append(f"{label}:INVALID")
    return rows


def _text(value: Any, fallback: str = "—") -> str:
    if value in (None, ""):
        return fallback
    if isinstance(value, float):
        if not math.isfinite(value):
            return fallback
        return f"{value:.3f}".rstrip("0").rstrip(".")
    return str(value)


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _iso_sort(value: Any) -> str:
    return str(value or "9999-12-31T23:59:59+08:00")


def _kickoff_timestamp(value: Any) -> str | None:
    """Return a timezone-qualified ISO timestamp suitable for browser comparison."""

    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _pick(row: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return value
    return None


def _fixture_projection(fixture: dict[str, Any]) -> dict[str, Any]:
    kickoff = _pick(fixture, "kickoff", "kickoff_local")
    if not kickoff:
        match_date = str(_pick(fixture, "matchDate", "businessDate") or "")[:10]
        match_time = str(_pick(fixture, "matchTime") or "")[:8]
        if match_date and match_time:
            kickoff = f"{match_date}T{match_time}+08:00"
    return {
        "match_id": str(_pick(fixture, "matchId", "match_id", "id") or ""),
        "match_num": _pick(fixture, "matchNum", "match_num"),
        "competition": _pick(fixture, "league", "competition"),
        "home": _pick(fixture, "homeTeam", "home_team", "home"),
        "away": _pick(fixture, "awayTeam", "away_team", "away"),
        "kickoff": kickoff,
        "kickoff_timestamp": _kickoff_timestamp(kickoff),
    }


def _score_focus(record: dict[str, Any]) -> tuple[str | None, list[str], str | None]:
    primary = str(record.get("unique_score") or record.get("score_top1") or "").strip() or None
    source = record.get("score_top3") or record.get("top_scores") or record.get("score_distribution") or []
    names: list[str] = []
    if isinstance(source, list):
        for row in source:
            if isinstance(row, dict):
                score = str(row.get("score") or "").strip()
            else:
                score = str(row).strip()
            if score and score not in names:
                names.append(score)
    if not primary and names:
        primary = names[0]
    neighbors = [score for score in names if score != primary][:2]
    canonical_concentration = record.get("score_concentration")
    concentration = str(canonical_concentration).strip() if canonical_concentration not in (None, "") else None
    return primary, neighbors, concentration


def _one_x_two_direction(probabilities: dict[str, Any]) -> str | None:
    values = {key: _number(probabilities.get(key)) for key in ("home", "draw", "away")}
    if any(value is None for value in values.values()):
        return None
    direction = max(values, key=lambda key: values[key] or 0)
    return {"home": "主胜倾向", "draw": "平局倾向", "away": "客胜倾向"}[direction]


def _prediction_projection(
    record: dict[str, Any],
) -> dict[str, Any]:
    probabilities = record.get("fusion_1X2") or record.get("probabilities") or {}
    probabilities = probabilities if isinstance(probabilities, dict) else {}
    btts = record.get("btts") or {}
    primary, neighbors, concentration = _score_focus(record)
    canonical_market = record.get("market_summary") or record.get("canonical_market_summary") or {}
    if not isinstance(canonical_market, dict):
        canonical_market = {}
    canonical_direction = record.get("one_x_two_direction")
    if canonical_direction in (None, ""):
        prediction_output = record.get("prediction_output")
        if isinstance(prediction_output, dict):
            canonical_direction = prediction_output.get("one_x_two_direction")
    formal_markets = summarize_formal_markets(project_frozen_formal_markets(record))
    return {
        "product_role": record.get("product_role"),
        "model_family": record.get("model_family"),
        "release_version": record.get("release_version"),
        "lambda_home": record.get("lambda_home"),
        "lambda_away": record.get("lambda_away"),
        "probabilities": probabilities,
        "one_x_two_direction": canonical_direction or _one_x_two_direction(probabilities),
        "btts": btts if isinstance(btts, dict) else {},
        "totals": record.get("totals") if isinstance(record.get("totals"), list) else [],
        "unique_score": primary,
        "primary_score": primary,
        "score_top3": record.get("score_top3") or [],
        "neighbor_scores": neighbors,
        "score_concentration": concentration,
        "score_distribution": record.get("score_distribution") if isinstance(record.get("score_distribution"), list) else [],
        "market_summary": canonical_market,
        "market_intelligence_quality": record.get("market_intelligence_quality"),
        "market_data_providers": record.get("market_data_providers") or record.get("market_sources") or [],
        "market_bookmakers": record.get("market_bookmakers") or [],
        "market_families": record.get("market_families") or [],
        "data_grade": record.get("data_grade"),
        "base_input_quality": record.get("base_input_quality"),
        "minutes_to_kickoff_at_freeze": record.get("minutes_to_kickoff_at_freeze"),
        "prediction_created_at": record.get("prediction_created_at") or record.get("created_at"),
        "freeze_created_at": record.get("freeze_created_at") or record.get("freeze_at"),
        "source_cutoff_at": record.get("source_cutoff_at") or record.get("model_input_as_of_at"),
        "input_snapshot_ref": record.get("input_snapshot_ref") or record.get("model_input_snapshot_ref"),
        "source_references": record.get("source_references") or [],
        # Dashboard receives only the compact status/probability summary.  The
        # 169-cell matrix remains a Match Detail concern.
        "formal_markets": formal_markets,
    }


def _result_keys(result: dict[str, Any]) -> set[str]:
    keys: set[str] = set()
    for field in ("match_key", "match_id", "provider_match_id"):
        value = result.get(field)
        if value not in (None, ""):
            keys.add(f"value:{value}")
    home = result.get("home")
    away = result.get("away")
    kickoff = result.get("kickoff_local") or result.get("kickoff_at")
    if home and away and kickoff:
        keys.add(f"teams:{home}|{away}|{kickoff}")
    return keys


def _result_index(result_root: Path, errors: list[str]) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    if not result_root.is_dir():
        return index
    for path in sorted(result_root.glob("*.json")):
        value = _read_optional_json(path, errors, f"result:{path.name}", {})
        if not isinstance(value, dict):
            continue
        value.setdefault("result_file", str(path.relative_to(BASE_DIR)).replace("\\", "/") if path.is_relative_to(BASE_DIR) else path.name)
        for key in _result_keys(value):
            index.setdefault(key, value)
    return index


def _workspace_history(workspace_path: Path, errors: list[str]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Project the published workspace's immutable completed/history rows."""

    if not workspace_path.is_file():
        return [], []
    workspace = _read_json(workspace_path, errors, "workspace", {})
    if not isinstance(workspace, dict):
        return [], []
    history = [row for row in workspace.get("history") or [] if isinstance(row, dict)]
    completed = [row for row in workspace.get("completed") or [] if isinstance(row, dict)]
    if not completed:
        completed = [
            row for row in history
            if row.get("review_available") is True and row.get("result_90m")
        ]
    return completed, history


def _exclusion_index(exclusion_root: Path, errors: list[str]) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    if not exclusion_root.is_dir():
        return index
    for path in sorted(exclusion_root.glob("*.json")):
        value = _read_optional_json(path, errors, f"exclusion:{path.name}", {})
        if not isinstance(value, dict):
            continue
        ids = value.get("prediction_ids") or []
        if value.get("prediction_id"):
            ids = [*ids, value["prediction_id"]]
        for prediction_id in ids:
            index[str(prediction_id)] = {
                "reason_code": value.get("reason_code"),
                "reason": value.get("reason"),
            }
    return index


def _find_result(
    card: dict[str, Any],
    record: dict[str, Any] | None,
    result_index: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    keys: list[str] = []
    if record:
        for field in ("match_key", "match_id"):
            if record.get(field):
                keys.append(f"value:{record[field]}")
        identity = record.get("match_identity") or {}
        home = identity.get("home") or record.get("home")
        away = identity.get("away") or record.get("away")
        kickoff = record.get("kickoff_at") or identity.get("kickoff_at")
        if home and away and kickoff:
            keys.append(f"teams:{home}|{away}|{kickoff}")
    for field in ("match_id",):
        if card.get(field):
            keys.append(f"value:{card[field]}")
    for key in keys:
        if key in result_index:
            return result_index[key]
    return None


def _read_records(prediction_root: Path, errors: list[str]) -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    if not prediction_root.is_dir():
        errors.append("predictions:MISSING")
        return records
    for path in sorted(prediction_root.glob("*.json")):
        value = _read_optional_json(path, errors, f"prediction:{path.name}", {})
        if isinstance(value, dict) and value.get("prediction_id"):
            records[str(value["prediction_id"])] = value
    return records


def _status_reason(status: str, job: dict[str, Any] | None, record: dict[str, Any] | None) -> tuple[str | None, str | None]:
    raw = str((job or {}).get("last_error") or "").strip()
    if raw:
        return raw, REASON_LABELS.get(raw, raw)
    if status == "FROZEN" and record is None:
        return "PREDICTION_ARTIFACT_MISSING", REASON_LABELS["PREDICTION_ARTIFACT_MISSING"]
    if job is None:
        return "BASE_JOB_MISSING", REASON_LABELS["BASE_JOB_MISSING"]
    return None, None


def _prematch_identity(fixture: dict[str, Any], job: dict[str, Any] | None) -> dict[str, Any]:
    projected = _fixture_projection(fixture)
    job = job or {}
    return {
        "job_id": job.get("job_id"),
        "match_id": job.get("match_id") or projected.get("match_id"),
        "match_key": job.get("match_key") or job.get("canonical_match_id") or _pick(fixture, "match_key", "matchKey"),
        "home": job.get("home") or projected.get("home"),
        "away": job.get("away") or projected.get("away"),
        "kickoff_at": job.get("kickoff") or projected.get("kickoff"),
    }


def _public_job_resolution(resolution: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(resolution, dict):
        return None
    return {
        key: resolution.get(key)
        for key in (
            "status",
            "row_count",
            "job_ids",
            "statuses",
            "match_key",
            "conflict_reason",
        )
    }


def _conflict_job(fixture: dict[str, Any], resolution: dict[str, Any]) -> dict[str, Any]:
    projected = _fixture_projection(fixture)
    conflict_reason = str(resolution.get("conflict_reason") or "DUPLICATE_CURRENT_JOB_STATE")
    return {
        "job_id": None,
        "match_id": projected.get("match_id"),
        "match_key": _pick(fixture, "match_key", "matchKey"),
        "home": projected.get("home"),
        "away": projected.get("away"),
        "kickoff": projected.get("kickoff"),
        "status": "CURRENT_JOB_STATE_CONFLICT",
        "prediction_id": None,
        "last_error": conflict_reason,
        "current_job_resolution": _public_job_resolution(resolution),
    }


def _card(
    fixture: dict[str, Any],
    job: dict[str, Any] | None,
    record: dict[str, Any] | None,
    result_index: dict[str, dict[str, Any]],
    exclusions: dict[str, dict[str, Any]],
    formal_samples: dict[str, dict[str, Any]],
    exploratory_samples: dict[str, dict[str, Any]],
    prematch_selection: dict[str, Any] | None = None,
    current_job_resolution: dict[str, Any] | None = None,
) -> dict[str, Any]:
    resolution_status = (current_job_resolution or {}).get("status")
    if resolution_status == "CONFLICT":
        job = _conflict_job(fixture, current_job_resolution or {})
    elif resolution_status == "MISSING":
        job = None
    card = _fixture_projection(fixture)
    status = str((job or {}).get("status") or "PENDING")
    selection = prematch_selection or {}
    current_selection = status == "FROZEN" and prematch_selection is not None
    is_conflict = status == "CURRENT_JOB_STATE_CONFLICT"
    if current_selection:
        record = selection.get("selected_record")
        prediction_id = str(selection.get("selected_prediction_id") or "") or None
    elif is_conflict:
        record = None
        prediction_id = None
    elif status != "FROZEN":
        # A retained prediction pointer is audit identity only until the
        # current base job is FROZEN; never project it as a live recommendation.
        record = None
        prediction_id = str((job or {}).get("prediction_id") or "") or None
    else:
        prediction_id = str((job or {}).get("prediction_id") or "") or None
    if current_selection:
        serving_selection_status = selection.get("status")
        serving_selection_reason = selection.get("reason")
    elif is_conflict:
        serving_selection_status = "CONFLICT"
        serving_selection_reason = (current_job_resolution or {}).get("conflict_reason") or "DUPLICATE_CURRENT_JOB_STATE"
    elif status != "FROZEN":
        serving_selection_status = "NOT_SERVING"
        serving_selection_reason = "CURRENT_JOB_NOT_FROZEN"
    else:
        serving_selection_status = "LEGACY_POINTER"
        serving_selection_reason = "JOB_POINTER"
    reason_code, reason_text = _status_reason(status, job, record)
    result = _find_result(card, record, result_index)
    sample = formal_samples.get(prediction_id or "") or exploratory_samples.get(prediction_id or "")
    pilot_excluded = bool(prediction_id and prediction_id in exclusions)
    formal_prospective = bool(prediction_id and prediction_id in formal_samples)
    card.update({
        "status": status,
        "status_label": "试运行预测" if pilot_excluded and record else STATUS_LABELS.get(status, status),
        "reason_code": reason_code,
        "reason_text": reason_text,
        "job_id": (job or {}).get("job_id"),
        "prediction_id": prediction_id,
        "selected_prediction_id": selection.get("selected_prediction_id") if current_selection else None,
        "current_prediction_id": selection.get("selected_prediction_id") if current_selection else None,
        "final_prematch_prediction_id": selection.get("selected_prediction_id") if current_selection else None,
        "selected_freeze_created_at": selection.get("selected_freeze_created_at") if current_selection else None,
        "selected_source_cutoff_at": selection.get("selected_source_cutoff_at") if current_selection else None,
        "superseded_count": int(selection.get("superseded_count") or 0) if current_selection else 0,
        "prematch_selection": {
            "status": serving_selection_status,
            "reason": serving_selection_reason,
            "candidate_count": int(selection.get("candidate_count") or 0) if current_selection else 0,
            "selected_prediction_id": selection.get("selected_prediction_id") if current_selection else None,
            "selected_freeze_created_at": selection.get("selected_freeze_created_at") if current_selection else None,
            "selected_source_cutoff_at": selection.get("selected_source_cutoff_at") if current_selection else None,
            "superseded_count": int(selection.get("superseded_count") or 0) if current_selection else 0,
        },
        "prediction": _prediction_projection(record) if record else None,
        "result": {
            "score_90m": (result or {}).get("result_90m") or (result or {}).get("score_90m"),
            "verified_at": (result or {}).get("result_verified_at") or (result or {}).get("verified_at"),
            "source": (result or {}).get("source"),
        } if result else None,
        "pilot_excluded": pilot_excluded,
        "formal_prospective": formal_prospective,
        "evaluation": {
            "kind": "formal" if formal_prospective else "pilot_excluded" if prediction_id in exploratory_samples else None,
            "metrics": sample.get("metrics") if isinstance(sample, dict) else {},
        } if sample else None,
        "current_job_resolution": _public_job_resolution(current_job_resolution),
    })
    return card


def _esc(value: Any, fallback: str = "\u2014") -> str:
    return html.escape(_text(value, fallback))


MODERN_CSS = r"""
:root {
  --shell-bg: #07111A;
  --workspace-bg: #F7F7F5;
  --surface: #FFFFFF;
  --surface-subtle: #FAFAF8;
  --text: #121417;
  --muted: #626870;
  --quiet: #8B9198;
  --line: #E6E7E4;
  --accent: #FF6A00;
  --accent-soft: #FFF1E8;
  --home: #1F5EA8;
  --draw: #A9ADB2;
  --away: #E23B3B;
  --warning: #B75C00;
  --warning-soft: #FFF4E8;
  --danger: #B42318;
  --danger-soft: #FFF1F0;
  --verified: #18794E;
}
* { box-sizing: border-box; }
html { background: var(--shell-bg); scroll-behavior: smooth; }
body {
  min-width: 0;
  margin: 0;
  background: var(--workspace-bg);
  color: var(--text);
  font: 14px/1.5 Inter, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
  -webkit-font-smoothing: antialiased;
}
a { color: inherit; }
button { font: inherit; }
button, a { -webkit-tap-highlight-color: transparent; }
button:focus-visible, a:focus-visible, summary:focus-visible { outline: 2px solid var(--accent); outline-offset: 3px; }
[hidden] { display: none !important; }

.app-shell { display: grid; grid-template-columns: 184px minmax(0, 1fr); min-height: 100vh; }
.side-rail {
  display: flex;
  flex-direction: column;
  min-height: 100vh;
  padding: 30px 18px 22px;
  background: var(--shell-bg);
  color: #F5F7F8;
}
.rail-brand { display: block; text-decoration: none; }
.rail-mark { display: block; font-size: 25px; font-weight: 750; letter-spacing: -.06em; }
.rail-caption { display: block; margin-top: 3px; color: #A9B3BB; font-size: 10px; line-height: 1.4; letter-spacing: .12em; text-transform: uppercase; }
.rail-nav { display: grid; gap: 5px; margin-top: 54px; }
.nav-item { display: flex; align-items: baseline; justify-content: space-between; gap: 8px; min-height: 44px; padding: 11px 10px; border-left: 2px solid transparent; color: #A9B3BB; font-size: 13px; text-decoration: none; }
.nav-item small { color: #65727C; font-size: 9px; letter-spacing: .06em; text-transform: uppercase; }
.nav-item:hover, .nav-item.active { border-left-color: var(--accent); background: rgba(255,255,255,.06); color: #FFFFFF; }
.nav-item.active small { color: #F6A26D; }
.rail-footer { margin-top: auto; padding: 14px 10px 0; border-top: 1px solid rgba(255,255,255,.12); color: #7F8B94; font-size: 10px; }
.rail-footer strong { display: block; color: #D7DDE1; font-size: 11px; font-weight: 650; }
.rail-footer span { display: block; margin-top: 4px; }
.workspace { min-width: 0; background: var(--workspace-bg); }
.workspace-inner { width: min(calc(100% - 48px), 1220px); margin: 0 auto; padding: 28px 0 44px; }
.mobile-topbar { display: none; }
.workspace-header { display: flex; align-items: end; justify-content: space-between; gap: 24px; padding-bottom: 20px; border-bottom: 1px solid var(--line); }
.workspace-kicker { color: var(--quiet); font-size: 10px; font-weight: 700; letter-spacing: .16em; text-transform: uppercase; }
.workspace-title { margin: 8px 0 0; font-size: 24px; line-height: 1.15; letter-spacing: -.045em; }
.workspace-title span { margin-left: 9px; color: var(--muted); font-size: 13px; font-weight: 500; letter-spacing: 0; }
.header-note { color: var(--muted); font-size: 11px; text-align: right; white-space: nowrap; }
.dashboard-heading { display: flex; align-items: end; justify-content: space-between; gap: 24px; padding: 22px 0 14px; }
.dashboard-heading h1 { display: none; }
.fixture-count { color: var(--muted); font-size: 12px; font-variant-numeric: tabular-nums; }
.filters { display: flex; flex-wrap: wrap; gap: 7px; }
.filter { min-height: 36px; padding: 6px 14px; border: 1px solid var(--line); border-radius: 9px; background: var(--surface); color: var(--text); cursor: pointer; font-size: 12px; }
.filter:hover, .filter[aria-pressed="true"] { border-color: #FFB27F; color: var(--accent); }
.filter[aria-pressed="true"] { background: var(--accent-soft); }

.quality-warning, .runtime-warning { display: flex; flex-wrap: wrap; align-items: baseline; gap: 5px 10px; margin: 0 0 14px; padding: 11px 14px; border-left: 3px solid var(--accent); background: var(--accent-soft); color: var(--muted); font-size: 12px; }
.quality-warning strong, .runtime-warning strong { color: var(--text); font-weight: 700; }
.runtime-warning { border-left-color: var(--danger); background: var(--danger-soft); }
.runtime-warning strong { color: var(--danger); }
.closed-beta-notice { margin-top: 12px; border-left-color: var(--line); background: transparent; color: var(--quiet); font-size: 11px; }
.dashboard-trust { padding: 15px 0 0; border-top: 1px solid var(--line); }
.dashboard-trust strong, .dashboard-trust span { display: block; margin-top: 3px; }

.fixture-table { overflow: hidden; border: 1px solid var(--line); border-radius: 12px; background: var(--surface); }
.table-header, .fixture-row { display: grid; grid-template-columns: 112px 74px minmax(220px, 1.35fr) minmax(245px, 1.5fr) minmax(160px, 1fr) minmax(150px, .95fr); column-gap: 16px; padding-left: 16px; padding-right: 16px; }
.table-header { min-height: 38px; align-items: center; border-bottom: 1px solid var(--line); background: var(--surface-subtle); color: var(--muted); font-size: 10px; font-weight: 650; }
.fixture-row { position: relative; min-height: 86px; align-items: center; border-bottom: 1px solid var(--line); }
.fixture-row:last-of-type { border-bottom: 0; }
.fixture-row:hover { background: #FFFDFC; }
.fixture-row > * { min-width: 0; }
.fixture-row > *:not(.fixture-row-target) { position: relative; z-index: 1; pointer-events: none; }
.fixture-row-target { position: absolute; inset: 0; z-index: 0; border-radius: inherit; }
.fixture-row-target:focus-visible { outline: 2px solid var(--accent); outline-offset: -3px; }
.identity-cell { min-width: 0; }
.cell-meta, .match-number, .kickoff, .identity-competition, .score-caption, .action-note { color: var(--muted); font-size: 11px; }
.match-number { display: block; color: var(--text); font-weight: 700; font-variant-numeric: tabular-nums; white-space: nowrap; }
.identity-competition { display: block; margin-top: 3px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.kickoff { color: var(--text); font-variant-numeric: tabular-nums; }
.teams-cell { min-width: 0; }
.team-match { display: flex; align-items: baseline; gap: 7px; min-width: 0; font-weight: 700; letter-spacing: -.02em; }
.team-match .team { min-width: 0; overflow-wrap: anywhere; }
.team-match .home { text-align: right; }
.team-match .away { text-align: left; }
.versus { flex: 0 0 auto; color: var(--muted); font-size: 10px; font-weight: 500; }
.result-inline { margin-top: 4px; color: var(--verified); font-size: 11px; font-weight: 650; }
.row-action { display: flex; align-items: baseline; justify-content: flex-start; flex-wrap: wrap; gap: 5px 9px; margin-top: 6px; }
.detail-link { color: var(--accent); font-size: 11px; font-weight: 650; text-decoration: none; white-space: nowrap; }
.detail-link:hover { text-decoration: underline; }
.exception-note { color: var(--warning); font-size: 11px; font-weight: 650; }
.exception-note.failed, .exception-note.missed { color: var(--danger); }
.completed-note { color: var(--verified); font-size: 11px; font-weight: 650; }
.reason-detail { flex-basis: 100%; color: var(--muted); font-size: 10px; }
.prediction-unavailable { padding: 8px 0; color: var(--muted); font-size: 12px; }

.probability-cell-group { min-width: 0; }
.probability-grid { display: grid; gap: 7px; }
.probability-strip { display: flex; width: 100%; height: 7px; overflow: hidden; border-radius: 99px; background: var(--line); }
.probability-segment { display: block; min-width: 2px; height: 100%; }
.probability-segment.home { background: var(--home); }
.probability-segment.draw { background: var(--draw); }
.probability-segment.away { background: var(--away); }
.probability-legend { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 7px; }
.probability-cell { display: grid; gap: 1px; min-width: 0; }
.probability-cell > span:first-child { color: var(--muted); font-size: 10px; }
.probability-cell strong { font-size: 13px; line-height: 1.1; font-variant-numeric: tabular-nums; }
.probability-cell.is-leading strong { font-weight: 800; }
.probability-lead { color: var(--muted); font-size: 10px; }
.score-cell, .queue-context { min-width: 0; }
.score-caption, .context-label { display: block; margin-bottom: 3px; }
.score-primary { display: flex; align-items: baseline; gap: 6px; font-size: 15px; font-weight: 750; font-variant-numeric: tabular-nums; }
.score-primary span { color: var(--muted); font-size: 11px; font-weight: 500; }
.score-serving-note { margin-top: 4px; color: var(--warning); font-size: 10px; font-weight: 650; }
.score-unavailable { color: var(--muted); font-size: 12px; }
.context-value { display: block; font-size: 12px; font-weight: 650; font-variant-numeric: tabular-nums; }
.context-note { display: block; margin-top: 3px; color: var(--muted); font-size: 10px; }
.data-warning { margin: 14px 0; padding: 11px 14px; border-left: 3px solid var(--warning); background: var(--warning-soft); color: var(--warning); font-size: 12px; }
.filter-empty { padding: 54px 20px; color: var(--muted); text-align: center; }

.history { margin-top: 30px; padding-top: 1px; border-top: 1px solid var(--line); }
.history-heading { display: flex; align-items: baseline; justify-content: space-between; gap: 12px; padding: 17px 0 10px; }
.history-heading h2 { margin: 0; font-size: 16px; letter-spacing: -.02em; }
.history-heading span { color: var(--muted); font-size: 11px; }
.history-row { display: grid; grid-template-columns: 100px minmax(220px, 1fr) 116px minmax(170px, auto); gap: 16px; align-items: center; min-height: 60px; border-bottom: 1px solid var(--line); font-size: 12px; }
.history-meta { color: var(--muted); font-size: 11px; }
.history-teams { min-width: 0; font-weight: 650; overflow-wrap: anywhere; }
.history-teams span { color: var(--muted); font-weight: 400; }
.history-result span { display: block; color: var(--muted); font-size: 10px; }
.history-score { display: block; margin-top: 2px; color: var(--verified); font-size: 17px; font-variant-numeric: tabular-nums; }
.history-links { display: flex; flex-wrap: wrap; gap: 8px; color: var(--muted); font-size: 11px; }
.history-links a { text-decoration: none; }
.history-links a:hover { color: var(--accent); text-decoration: underline; }
.page-footer { display: flex; justify-content: space-between; gap: 18px; margin-top: 22px; padding-top: 14px; border-top: 1px solid var(--line); color: var(--quiet); font-size: 10px; }
.page-footer span:last-child { max-width: 52%; text-align: right; }

@media (max-width: 980px) {
  .app-shell { grid-template-columns: 156px minmax(0, 1fr); }
  .side-rail { padding-left: 14px; padding-right: 14px; }
  .table-header, .fixture-row { grid-template-columns: 100px 64px minmax(190px, 1.2fr) minmax(220px, 1.4fr) minmax(145px, 1fr) minmax(125px, .9fr); column-gap: 12px; padding-left: 12px; padding-right: 12px; }
}
@media (max-width: 820px) {
  .app-shell { display: block; }
  .side-rail { display: none; }
  .mobile-topbar { display: flex; align-items: center; justify-content: space-between; min-height: 56px; padding: 0 16px; background: var(--shell-bg); color: #F5F7F8; }
  .mobile-topbar a { font-weight: 750; letter-spacing: -.05em; text-decoration: none; }
  .mobile-topbar span { color: #B7C0C7; font-size: 12px; }
  .workspace-inner { width: calc(100% - 32px); padding: 18px 0 30px; }
  .workspace-header { align-items: baseline; gap: 12px; padding-bottom: 15px; }
  .workspace-title { font-size: 21px; }
  .workspace-title span { display: block; margin: 5px 0 0; font-size: 12px; }
  .header-note { font-size: 10px; white-space: normal; }
  .dashboard-heading { align-items: center; gap: 12px; padding: 16px 0 12px; }
  .dashboard-heading h1 { display: block; margin: 0; font-size: 15px; font-weight: 700; }
  .fixture-count { display: block; margin-top: 3px; font-size: 11px; }
  .filters { gap: 5px; }
  .filter { min-width: 58px; min-height: 44px; padding: 8px 10px; }
  .table-header { display: none; }
  .fixture-table { border-radius: 10px; }
  .fixture-row { display: block; min-height: 0; padding: 16px 14px 15px; }
  .fixture-row > * { margin-top: 11px; }
  .fixture-row > .identity-cell { margin-top: 0; }
  .identity-cell { display: flex; align-items: baseline; justify-content: space-between; gap: 12px; }
  .identity-competition { max-width: 68%; }
  .kickoff { font-size: 12px; }
  .team-match { display: grid; grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr); gap: 8px; font-size: 19px; line-height: 1.2; }
  .team-match .home, .team-match .away { text-align: left; }
  .team-match .away { text-align: right; }
  .versus { align-self: center; font-size: 11px; }
  .row-action { justify-content: flex-start; margin-top: 7px; }
  .probability-cell-group { margin-top: 12px; }
  .probability-grid { gap: 8px; }
  .probability-cell strong { font-size: 16px; }
  .probability-lead { font-size: 10px; }
  .queue-score, .queue-context { display: none; }
  .history { margin-top: 25px; }
  .history-row { grid-template-columns: minmax(0, 1fr) auto; gap: 5px 12px; padding: 11px 0; }
  .history-meta, .history-links { grid-column: 1 / -1; }
  .page-footer { display: block; }
  .page-footer span { display: block; }
  .page-footer span:last-child { max-width: none; margin-top: 6px; text-align: left; }
}
@media (max-width: 360px) {
  .mobile-topbar { padding-left: 12px; padding-right: 12px; }
  .workspace-inner { width: calc(100% - 24px); }
  .workspace-header { align-items: flex-start; }
  .workspace-kicker { max-width: 190px; line-height: 1.35; }
  .header-note { max-width: 94px; }
  .dashboard-heading { align-items: flex-end; gap: 7px; }
  .filters { flex: 1 1 auto; display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); }
  .filter { min-width: 0; padding-left: 5px; padding-right: 5px; font-size: 11px; }
  .fixture-row { padding-left: 10px; padding-right: 10px; }
  .team-match { font-size: 17px; }
  .probability-legend { gap: 5px; }
  .probability-cell strong { font-size: 15px; }
}
"""



def _format_kickoff(value: Any) -> str:
    text = str(value or "").replace("T", " ")
    if "+08:00" in text:
        text = text.replace("+08:00", "")
    return text[:16] if text else "时间待补"


def _format_updated_at(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return "时间待补"
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo:
            parsed = parsed.astimezone(SHANGHAI)
        return parsed.strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return text[:16].replace("T", " ")


def _health_watch_quality_for_cycle(
    health_watch: dict[str, Any],
    runtime: dict[str, Any],
    business_date: str,
) -> tuple[dict[str, Any] | None, str]:
    persisted = health_watch.get("prediction_quality_health")
    if not isinstance(persisted, dict):
        return None, "UNAVAILABLE"
    runtime_business_date = str(runtime.get("business_date") or "").strip()
    runtime_finished_at = str(runtime.get("finished_at") or "").strip()
    persisted_date = str(persisted.get("business_date") or "").strip()
    persisted_cycle = str(persisted.get("runtime_cycle_finished_at") or "").strip()
    top_level_date = str(health_watch.get("business_date") or "").strip()
    top_level_cycle = str(health_watch.get("last_cycle_generated_at") or "").strip()
    if (
        not business_date
        or runtime_business_date != business_date
        or not runtime_finished_at
        or persisted.get("scope") != "current_serving"
        or persisted_date != business_date
        or persisted_cycle != runtime_finished_at
        or (top_level_date and top_level_date != business_date)
        or (top_level_cycle and top_level_cycle != runtime_finished_at)
    ):
        return None, "MISMATCHED"
    return persisted, "MATCHED"


def _current_prediction_quality_health(
    records: dict[str, dict[str, Any]],
    exclusions: dict[str, dict[str, Any]],
    jobs: list[dict[str, Any]],
    runtime: dict[str, Any],
    health_watch: dict[str, Any],
    business_date: str,
) -> dict[str, Any]:
    runtime_finished_at = str(runtime.get("finished_at") or "").strip() or None
    persisted, provenance_status = _health_watch_quality_for_cycle(
        health_watch,
        runtime,
        business_date,
    )
    base: dict[str, Any] = {
        "schema_version": "prediction_quality_health.v1",
        "status": "UNKNOWN",
        "overall_status": "UNKNOWN",
        "scope": "current_serving",
        "business_date": business_date or None,
        "runtime_cycle_finished_at": runtime_finished_at,
        "reasons": [],
        "available": False,
        "provenance_status": provenance_status,
        "source": "unavailable",
        "display_status": _QUALITY_STATUS_LABELS["UNKNOWN"],
    }
    if (
        not business_date
        or str(runtime.get("business_date") or "").strip() != business_date
        or not runtime_finished_at
    ):
        return base

    formal_records = [
        record
        for record in records.values()
        if str(record.get("prediction_status") or "").strip() in _CURRENT_FORMAL_STATUSES
    ]
    try:
        selection = select_current_serving_predictions(
            formal_records,
            business_date=business_date,
            current_jobs=jobs,
            excluded_ids=set(exclusions),
        )
        evaluated = evaluate_exact_score_health(selection["selected_records"])
    except (KeyError, TypeError, ValueError):
        return base

    quality = {
        **evaluated,
        "scope": "current_serving",
        "business_date": business_date,
        "runtime_cycle_finished_at": runtime_finished_at,
        "current_job_count": selection.get("current_job_count", 0),
        "unique_current_match_count": selection.get("unique_current_match_count", 0),
        "current_frozen_job_count": selection.get("current_frozen_job_count", 0),
        "duplicate_current_job_count": selection.get("duplicate_current_job_count", 0),
        "duplicate_current_job_keys": selection.get("duplicate_current_job_keys", []),
        "conflicted_current_match_count": selection.get("conflicted_current_match_count", 0),
        "conflicted_current_match_keys": selection.get("conflicted_current_match_keys", []),
        "selected_record_count": selection.get("selected_record_count", 0),
        "selected_job_ids": selection.get("selected_job_ids", []),
        "selected_prediction_ids": selection.get("selected_prediction_ids", []),
        "available": True,
        "provenance_status": provenance_status,
        "source": "current_serving_projection",
    }
    quality["overall_status"] = quality["status"]
    quality["display_status"] = _QUALITY_STATUS_LABELS.get(
        quality["status"],
        quality["status"],
    )
    if persisted is not None:
        if (
            str(persisted.get("status") or "") != quality["status"]
            or list(persisted.get("reasons") or []) != list(quality.get("reasons") or [])
        ):
            quality["provenance_status"] = "MISMATCHED"
    return quality


def _score_label(value: Any) -> str:
    return str(value or "").strip()


def _format_percent(value: Any) -> str | None:
    number = _number(value)
    if number is None or number < 0 or number > 1:
        return None
    return f"{number * 100:.1f}%"


def _score_rows(prediction: dict[str, Any], limit: int = 5) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    distribution = prediction.get("score_distribution")
    if isinstance(distribution, list):
        for item in distribution:
            if isinstance(item, dict):
                score = _score_label(item.get("score") or item.get("value"))
                probability = _number(item.get("probability"))
            else:
                score = _score_label(item)
                probability = None
            if score and score not in seen:
                rows.append({"score": score, "probability": probability})
                seen.add(score)
    if not rows:
        for item in prediction.get("score_top3") or prediction.get("top_scores") or []:
            if isinstance(item, dict):
                score = _score_label(item.get("score") or item.get("value"))
                probability = _number(item.get("probability"))
            else:
                score = _score_label(item)
                probability = None
            if score and score not in seen:
                rows.append({"score": score, "probability": probability})
                seen.add(score)
    primary = _score_label(prediction.get("primary_score") or prediction.get("unique_score"))
    if primary and primary not in seen:
        rows.insert(0, {"score": primary, "probability": None})
    return rows[:limit]


def _one_x_two_html(prediction: dict[str, Any]) -> str:
    probabilities = prediction.get("probabilities") or {}
    if not isinstance(probabilities, dict):
        return ""
    values = {
        "home": _number(probabilities.get("home")),
        "draw": _number(probabilities.get("draw")),
        "away": _number(probabilities.get("away")),
    }
    if not all(value is not None and 0 <= value <= 1 for value in values.values()):
        return '<div class="prediction-unavailable" role="status">胜平负概率暂不可用</div>'
    total = sum(values.values())
    if total <= 0:
        return '<div class="prediction-unavailable" role="status">胜平负概率暂不可用</div>'
    leader = max(values, key=values.get)
    labels = {"home": "主胜", "draw": "平", "away": "客胜"}
    segments = "".join(
        f'<span class="probability-segment {key}" style="width:{values[key] / total * 100:.3f}%" aria-hidden="true"></span>'
        for key in ("home", "draw", "away")
    )
    cells = []
    for key in ("home", "draw", "away"):
        percent = _format_percent(values[key]) or "—"
        leading = " is-leading" if key == leader else ""
        lead = '<small class="probability-lead">相对占优</small>' if key == leader else '<small class="probability-lead">&nbsp;</small>'
        cells.append(
            f'<div class="probability-cell{leading}">'
            f'<span>{labels[key]}</span><strong>{html.escape(percent)}</strong>{lead}</div>'
        )
    label = "；".join(f"{labels[key]} {_format_percent(values[key])}" for key in ("home", "draw", "away"))
    return (
        f'<div class="probability-grid" aria-label="胜平负概率：{html.escape(label, quote=True)}">'
        f'<div class="probability-strip" role="img" aria-label="胜平负概率分布">{segments}</div>'
        f'<div class="probability-legend">{"".join(cells)}</div></div>'
    )


def _prediction_exact_available(prediction: dict[str, Any]) -> bool:
    formal = prediction.get("formal_markets")
    markets = formal.get("markets") if isinstance(formal, dict) else None
    exact = markets.get("exact_score") if isinstance(markets, dict) else None
    return isinstance(exact, dict) and str(exact.get("status") or "").upper() == "AVAILABLE"


def _total_goal_summary(prediction: dict[str, Any]) -> dict[str, Any] | None:
    totals = prediction.get("totals")
    if not isinstance(totals, list):
        return None
    buckets: dict[str, float] = {}
    for item in totals:
        if not isinstance(item, dict):
            continue
        probability = _number(item.get("probability"))
        if probability is None or not 0 <= probability <= 1:
            continue
        raw_goals = str(item.get("goals") or item.get("total") or "").strip()
        if raw_goals.endswith("+"):
            try:
                bucket = "4+" if int(raw_goals[:-1]) >= 4 else raw_goals
            except ValueError:
                continue
        elif raw_goals.isdigit():
            bucket = raw_goals if int(raw_goals) <= 3 else "4+"
        else:
            continue
        buckets[bucket] = buckets.get(bucket, 0.0) + probability
    if not buckets:
        return None
    top_bucket, top_probability = max(buckets.items(), key=lambda item: item[1])
    return {"bucket": top_bucket, "probability": top_probability, "buckets": buckets}


def _score_summary_html(
    prediction: dict[str, Any],
    *,
    exact_score_serving: dict[str, Any] | None = None,
) -> str:
    serving_state = str((exact_score_serving or {}).get("state") or "NORMAL")
    if not _prediction_exact_available(prediction):
        return (
            '<div class="queue-score score-unavailable" data-score-serving-state="UNAVAILABLE">'
            '<span class="score-caption">比分概率</span><strong>暂不可用</strong></div>'
        )
    rows = [
        row for row in _score_rows(prediction, limit=5)
        if row.get("probability") is not None
    ]
    if not rows:
        return ""
    primary = rows[0]
    primary_probability = _format_percent(primary.get("probability"))
    primary_probability_html = (
        f'<span>{html.escape(primary_probability)}</span>' if primary_probability else ""
    )
    local_context = ""
    if serving_state != "NORMAL":
        local_context = '<div class="score-serving-note">比分概率仅供观察</div>'
    return (
        f'<div class="queue-score score-cell{" score-unverified" if serving_state != "NORMAL" else ""}" '
        f'data-score-serving-state="{html.escape(serving_state, quote=True)}">'
        '<div class="score-caption">最高概率比分</div>'
        f'<div class="score-primary"><strong>{html.escape(primary["score"])}</strong>{primary_probability_html}</div>'
        f'{local_context}</div>'
    )


def _market_divergence_html(prediction: dict[str, Any]) -> str:
    market = prediction.get("market_summary")
    if not isinstance(market, dict):
        return ""
    comparison = market.get("model_comparison")
    if not isinstance(comparison, dict):
        comparison = market
    model_probability = _number(
        comparison.get("model_home_probability") or comparison.get("model_home")
    )
    market_probability = _number(
        comparison.get("market_home_probability") or comparison.get("market_home")
    )
    if (
        model_probability is None
        or market_probability is None
        or not (0 <= model_probability <= 1 and 0 <= market_probability <= 1)
    ):
        return ""
    difference = model_probability - market_probability
    sign = "+" if difference >= 0 else ""
    difference_text = f"{sign}{difference * 100:.1f} \u4e2a\u767e\u5206\u70b9"
    return (
        '<div class="context-item"><span class="context-label">市场对照</span>'
        f'<span class="context-value">主胜 {_format_percent(model_probability)} · 市场 {_format_percent(market_probability)}</span>'
        f'<small class="context-note">差异 {html.escape(difference_text)}</small></div>'
    )


def _queue_context_html(prediction: dict[str, Any]) -> str:
    parts = []
    total = _total_goal_summary(prediction)
    if total:
        parts.append(
            '<div class="context-item"><span class="context-label">总进球分布</span>'
            f'<span class="context-value">最高段 {html.escape(str(total["bucket"]))} · '
            f'{html.escape(_format_percent(total["probability"]) or "—")}</span></div>'
        )
    market = _market_divergence_html(prediction)
    if market:
        parts.append(market)
    return '<div class="queue-context">' + "".join(parts) + '</div>' if parts else '<div class="queue-context"></div>'


def _card_status_copy(card: dict[str, Any]) -> str:
    if card.get("result"):
        return "\u5df2\u7ed3\u675f"
    return {
        "CURRENT_JOB_STATE_CONFLICT": "\u672c\u573a\u72b6\u6001\u5f85\u786e\u8ba4\uff0c\u6682\u4e0d\u9884\u6d4b",
        "PENDING": "\u9884\u6d4b\u5c1a\u672a\u5f62\u6210",
        "INSUFFICIENT_DATA": "\u6570\u636e\u4e0d\u8db3\uff0c\u6682\u4e0d\u9884\u6d4b",
        "PREDICTION_FAILED": "\u672c\u573a\u672a\u5f62\u6210\u6709\u6548\u9884\u6d4b",
        "MISSED_PREMATCH_WINDOW": "\u672a\u5f62\u6210\u5408\u6cd5\u8d5b\u524d\u9884\u6d4b",
    }.get(str(card.get("status") or "PENDING"), "\u5f53\u524d\u6682\u4e0d\u9884\u6d4b")


def _modern_card_html(
    card: dict[str, Any],
    *,
    exact_score_serving: dict[str, str] | None = None,
) -> str:
    status = str(card.get("status") or "PENDING")
    match_id = str(card.get("match_id") or "")
    prediction = card.get("prediction") if status == "FROZEN" else None
    prediction = prediction if isinstance(prediction, dict) else None
    result = card.get("result") if isinstance(card.get("result"), dict) else None
    has_result = bool(result and result.get("score_90m"))
    prediction_kind = "pilot" if card.get("pilot_excluded") and prediction else "formal" if prediction else "none"
    status_class = html.escape(status.lower(), quote=True)
    match_id_html = html.escape(match_id, quote=True)
    detail_link = '<span class="detail-link" aria-hidden="true">\u67e5\u770b\u8be6\u60c5</span>' if match_id else ""
    if has_result:
        action_html = f'<span class="completed-note">{_card_status_copy(card)}</span>{detail_link}'
    elif prediction:
        pilot_html = (
            '<span class="action-note">概率仅供观察</span>'
            if card.get("pilot_excluded")
            else ""
        )
        action_html = f"{pilot_html}{detail_link}"
    else:
        note_class = (
            " failed"
            if status == "PREDICTION_FAILED"
            else " missed"
            if status == "MISSED_PREMATCH_WINDOW"
            else ""
        )
        reason_text = str(card.get("reason_text") or "").strip()
        exact_copy = _card_status_copy(card)
        reason_html = (
            f'<span class="reason-detail">{html.escape(reason_text)}</span>'
            if reason_text and reason_text != exact_copy
            else ""
        )
        action_html = (
            f'<span class="exception-note{note_class}">{html.escape(exact_copy)}</span>'
            f'{reason_html}{detail_link}'
        )
    home_text = _esc(card.get("home"), "\u4e3b\u961f\u5f85\u5b9a")
    away_text = _esc(card.get("away"), "\u5ba2\u961f\u5f85\u5b9a")
    teams_html = (
        '<div class="team-match">'
        f'<span class="team home">{home_text}</span>'
        '<span class="versus">vs</span>'
        f'<span class="team away">{away_text}</span>'
        '</div>'
    )
    if has_result:
        teams_html += f'<div class="result-inline">90\u5206\u949f\u8d5b\u679c {html.escape(str(result.get("score_90m")))}</div>'
    probability_html = _one_x_two_html(prediction) if prediction else '<div class="prediction-unavailable">\u2014</div>'
    score_html = (
        _score_summary_html(prediction, exact_score_serving=exact_score_serving)
        if prediction
        else '<div class="queue-score score-unavailable"><span class="score-caption">比分概率</span><strong>暂不可用</strong></div>'
    )
    goals_html = _queue_context_html(prediction) if prediction else '<div class="queue-context"></div>'
    match_number_text = _esc(card.get("match_num"), "\u2014")
    competition_text = _esc(card.get("competition"), "\u8d5b\u4e8b\u5f85\u5b9a")
    kickoff_timestamp = html.escape(str(card.get("kickoff_timestamp") or _kickoff_timestamp(card.get("kickoff")) or ""), quote=True)
    detail_target = ""
    if match_id:
        detail_home = _text(card.get("home"), "\u4e3b\u961f\u5f85\u5b9a")
        detail_away = _text(card.get("away"), "\u5ba2\u961f\u5f85\u5b9a")
        detail_label = html.escape(
            f'{detail_home} vs {detail_away} \u00b7 \u67e5\u770b\u8be6\u60c5',
            quote=True,
        )
        detail_target = (
            f'<a class="fixture-row-target" href="../matches/{match_id_html}/" '
            f'aria-label="{detail_label}"></a>'
        )
    return (
        f'<article class="fixture-row status-{status_class} prediction-{prediction_kind}" '
        f'data-status="{html.escape(status, quote=True)}" '
        f'data-result="{"yes" if has_result else "no"}" '
        f'data-kickoff="{kickoff_timestamp}" '
        f'data-prediction-kind="{prediction_kind}">'
        f'{detail_target}'
        '<div class="identity-cell">'
        f'<span class="match-number">{match_number_text}</span>'
        f'<span class="identity-competition">{competition_text}</span>'
        '</div>'
        f'<div class="kickoff">{html.escape(_format_kickoff(card.get("kickoff")))}</div>'
         f'<div class="teams-cell">{teams_html}<div class="row-action">{action_html}</div></div>'
         f'<div class="probability-cell-group">{probability_html}</div>'
         f'{score_html}'
         f'{goals_html}'
         '</article>'
     )


def _historical_results_html(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return ""
    cards = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        result = row.get("result_90m")
        if not result:
            continue
        kickoff_text = _esc(row.get("kickoff"), "\u65f6\u95f4\u5f85\u5b9a")
        home_text = _esc(row.get("home"), "\u4e3b\u961f\u5f85\u5b9a")
        away_text = _esc(row.get("away"), "\u5ba2\u961f\u5f85\u5b9a")
        links = []
        if row.get("prematch_report_url"):
            links.append(
                f'<a href="{html.escape(str(row["prematch_report_url"]), quote=True)}">\u8d5b\u524d\u5feb\u7167</a>'
            )
        if row.get("postmatch_report_url"):
            links.append(
                f'<a href="{html.escape(str(row["postmatch_report_url"]), quote=True)}">\u8d5b\u540e\u590d\u76d8</a>'
            )
        link_text = " \u00b7 ".join(links)
        cards.append(
            '<article class="history-row" data-result="yes">'
            f'<div class="history-meta">{kickoff_text}</div>'
            f'<div class="history-teams">{home_text}<span> vs </span>{away_text}</div>'
            f'<div class="history-result"><span>90分钟结果</span><strong class="history-score">{html.escape(str(result))}</strong></div>'
            f'<div class="history-links">{link_text}</div>'
            '</article>'
        )
    if not cards:
        return ""
    return (
        '<section id="historical-results" class="history" aria-labelledby="history-title">'
        '<div class="history-heading"><h2 id="history-title">历史验证</h2>'
        f'<span>{len(cards)} 场独立记录 · 结果优先</span></div>'
        f'{"".join(cards)}</section>'
    )


def _runtime_warning_html(system_health: dict[str, Any], errors: list[Any]) -> str:
    overall = str(system_health.get("overall_status") or system_health.get("status") or "UNKNOWN").upper()
    if overall in {"HEALTHY", "SUCCESS"}:
        return ""
    if overall in {"FAILED", "ALERT"}:
        return (
            '<div class="runtime-warning" role="status">'
            '<strong>\u5f53\u524d\u6570\u636e\u66f4\u65b0\u5f02\u5e38</strong>'
            '<span>\u90e8\u5206\u6bd4\u8d5b\u4fe1\u606f\u53ef\u80fd\u6682\u65f6\u4e0d\u53ef\u7528\uff0c\u8bf7\u4ee5\u9875\u9762\u5b9e\u9645\u5185\u5bb9\u4e3a\u51c6\u3002</span>'
            '</div>'
        )
    if overall in {"UNKNOWN", "RUNNING"} or errors:
        return (
            '<div class="runtime-warning" role="status">'
            '<strong>\u5f53\u524d\u6570\u636e\u72b6\u6001\u5f85\u786e\u8ba4</strong>'
            '<span>\u9875\u9762\u53ea\u5c55\u793a\u5df2\u786e\u8ba4\u7684\u6bd4\u8d5b\u4fe1\u606f\u3002</span>'
            '</div>'
        )
    return ""


def _quality_warning_html(quality_health: dict[str, Any]) -> str:
    exact_score_serving = exact_score_serving_presentation(quality_health)
    state = exact_score_serving["state"]
    if state == "NORMAL":
        return ""
    label = "比分概率仅供观察" if state == "DEGRADED" else "比分概率质量待确认"
    note = (
        "保留原始比分概率，暂不展开解读。"
        if state == "DEGRADED"
        else "先保留已记录的概率，质量确认前暂不展开解读。"
    )
    return (
        '<div class="quality-warning" role="status">'
        f'<strong>{label}</strong><span>{note}</span>'
        '</div>'
    )


STATIC_REFRESH_SCRIPT = """<script>
(() => {
  const latestJson = "./latest.json";
  const pageVersion = __PAGE_VERSION__;
  let currentVersion = pageVersion;
  const versionOf = payload => `${payload?.business_date || payload?.target_date || ""}|${payload?.generated_at || ""}`;
  async function checkForUpdate() {
    if (document.visibilityState !== "visible") return;
    try {
      const response = await fetch(`${latestJson}?t=${Date.now()}`, { cache: "no-store" });
      if (!response.ok) return;
      const version = versionOf(await response.json());
      if (version === "|") return;
      if (version !== currentVersion) {
        const url = new URL(window.location.href);
        url.searchParams.set("v", version);
        window.location.replace(url.toString());
      }
    } catch (_) {}
  }
  window.setInterval(checkForUpdate, 60000);
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") checkForUpdate();
  });
  window.addEventListener("focus", checkForUpdate);
  checkForUpdate();
})();
</script>"""


def render_dashboard(payload: dict[str, Any]) -> str:
    summary = payload.get("summary") or {}
    system_health = payload.get("system_runtime_health") or payload.get("health") or {}
    quality_health = payload.get("prediction_quality_health") or {}
    date_value = str(payload.get("business_date") or "")
    date_parts = date_value.split("-")
    date_label = (
        f"{int(date_parts[1])}\u6708{int(date_parts[2])}\u65e5"
        if len(date_parts) == 3 and date_parts[1].isdigit() and date_parts[2].isdigit()
        else date_value or "\u6bd4\u8d5b\u65e5"
    )
    business_date_label = f"\u7ade\u5f69\u65e5 {date_label}"
    fixture_count = int(summary.get("fixture_count") or len(payload.get("fixtures") or []))
    verified_results = int(summary.get("verified_results") or 0)
    exact_score_serving = exact_score_serving_presentation(quality_health)
    cards_html = "".join(
        _modern_card_html(card, exact_score_serving=exact_score_serving)
        for card in payload.get("fixtures") or []
        if isinstance(card, dict)
    )
    overall_empty_html = (
        '<div class="filter-empty" data-filter-empty="ALL">\u4eca\u5929\u6ca1\u6709\u53ef\u5c55\u793a\u7684\u6bd4\u8d5b\u3002</div>'
        if fixture_count == 0
        else ""
    )
    filter_empty_html = (
        f"{overall_empty_html}"
        '<div class="filter-empty" data-filter-empty="UPCOMING" hidden>\u5f53\u524d\u7ade\u5f69\u65e5\u6682\u65e0\u672a\u5f00\u8d5b\u6bd4\u8d5b</div>'
        '<div class="filter-empty" data-filter-empty="RESULT" hidden>\u5f53\u524d\u7ade\u5f69\u65e5\u6682\u65e0\u5df2\u7ed3\u675f\u5e76\u6838\u9a8c\u7684\u6bd4\u8d5b</div>'
    )
    runtime_warning = _runtime_warning_html(system_health, payload.get("data_errors") or [])
    quality_warning = _quality_warning_html(quality_health)
    historical_html = _historical_results_html(payload.get("completed") or [])
    dashboard_trust = render_closed_beta_notice("dashboard-trust")
    data_warning = ""
    if summary.get("silent_missing_fixture"):
        data_warning = (
            '<div class="data-warning">\u90e8\u5206\u6bd4\u8d5b\u4fe1\u606f\u672a\u80fd\u5b8c\u6574\u5448\u73b0\uff0c\u9875\u9762\u53ea\u5c55\u793a\u5df2\u786e\u8ba4\u5185\u5bb9\u3002</div>'
        )
    page_version = "|".join(
        str(payload.get(key) or "") for key in ("business_date", "generated_at")
    )
    history_nav = '<a class="nav-item" href="#historical-results"><span>\u5386\u53f2\u9a8c\u8bc1</span><small>History</small></a>' if historical_html else ""
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>\u4eca\u65e5\u6bd4\u8d5b \u00b7 FBOS</title>
<style>{MODERN_CSS}</style>
</head>
<body>
<div class="app-shell">
<aside class="side-rail">
  <a class="rail-brand" href="./latest.html"><span class="rail-mark">FBOS</span><span class="rail-caption">Football Prediction<br>Intelligence</span></a>
  <nav class="rail-nav" aria-label="\u4e3b\u5bfc\u822a">
    <a class="nav-item active" href="./latest.html" aria-current="page"><span>\u4eca\u65e5\u6bd4\u8d5b</span><small>Matches</small></a>
    {history_nav}
  </nav>
  <div class="rail-footer"><strong>\u8d5b\u524d\u5206\u6790</strong><span>\u53ea\u5c55\u793a\u80fd\u6539\u53d8\u5f53\u524d\u5224\u65ad\u7684\u5185\u5bb9\u3002</span></div>
</aside>
<main class="workspace">
<div class="mobile-topbar"><a href="./latest.html">FBOS</a><span>\u4eca\u65e5\u6bd4\u8d5b</span></div>
<div class="workspace-inner">
<header class="workspace-header">
  <div><div class="workspace-kicker">Football Prediction Intelligence</div><h1 class="workspace-title">\u4eca\u65e5\u6bd4\u8d5b<span>{html.escape(business_date_label)}</span></h1></div>
  <div class="header-note">\u6d4b\u8bd5\u9636\u6bb5 \u00b7 \u4ec5\u4f9b\u8d5b\u524d\u5206\u6790</div>
</header>
<section class="dashboard-heading">
  <h1>\u4eca\u65e5\u6bd4\u8d5b<span class="fixture-count">{fixture_count} \u573a</span></h1>
  <div class="filters" aria-label="\u6bd4\u8d5b\u7b5b\u9009">
    <button class="filter" type="button" data-filter="ALL" aria-pressed="true">\u5168\u90e8</button>
    <button class="filter" type="button" data-filter="UPCOMING" aria-pressed="false">\u672a\u5f00\u8d5b</button>
    <button class="filter" type="button" data-filter="RESULT" data-result-count="{verified_results}" aria-pressed="false">\u5df2\u7ed3\u675f</button>
  </div>
</section>
{runtime_warning}{quality_warning}{data_warning}
<section class="fixture-table" id="fixture-list" aria-label="\u7ade\u5f69\u65e5\u6bd4\u8d5b\u5217\u8868">
  <div class="table-header" aria-hidden="true">
    <span>\u6bd4\u8d5b / \u8d5b\u4e8b</span><span>\u5f00\u7403</span><span>\u5bf9\u9635 / \u8d5b\u679c</span>
    <span>1X2 \u6982\u7387</span><span>\u6bd4\u5206\u6982\u7387</span><span>\u51b3\u7b56\u8bed\u5883</span>
  </div>
  {cards_html}
  {filter_empty_html}
</section>
{historical_html}
{dashboard_trust}
<footer class="page-footer">
  <span>\u6b63\u5e38\u72b6\u6001\u4fdd\u6301\u5b89\u9759\uff1b\u53ea\u6709\u5f71\u54cd\u5224\u65ad\u7684\u5f02\u5e38\u624d\u4f1a\u663e\u793a\u3002</span>
  <span>Closed Beta \u00b7 \u9884\u6d4b\u53ef\u80fd\u51fa\u9519\uff0c\u4ec5\u4f9b\u6bd4\u8d5b\u5206\u6790\u4e0e\u7814\u7a76\u53c2\u8003\uff1b\u7406\u6027\u53c2\u4e0e\uff0c\u672a\u6210\u5e74\u4eba\u9650\u5236\u3002</span>
</footer>
</div>
</main>
</div>
<script>
const buttons = Array.from(document.querySelectorAll('[data-filter]'));
const cards = Array.from(document.querySelectorAll('.fixture-row'));
const historicalResults = document.querySelector('#historical-results');
const emptyStates = Array.from(document.querySelectorAll('[data-filter-empty]'));
buttons.forEach(button => button.addEventListener('click', () => {{
  const filter = button.dataset.filter;
  buttons.forEach(item => item.setAttribute('aria-pressed', String(item === button)));
  cards.forEach(card => {{
    const kickoffTimestamp = Date.parse(card.dataset.kickoff || '');
    const isUpcoming = Number.isFinite(kickoffTimestamp) && Date.now() < kickoffTimestamp;
    const match = filter === 'ALL'
      || (filter === 'UPCOMING' && isUpcoming)
      || (filter === 'RESULT' && card.dataset.result === 'yes');
    card.hidden = !match;
  }});
  const visibleCount = cards.filter(card => !card.hidden).length;
  emptyStates.forEach(empty => {{
    empty.hidden = empty.dataset.filterEmpty !== filter || visibleCount !== 0;
  }});
  if (historicalResults) historicalResults.hidden = filter !== 'ALL';
}}));
</script>
{STATIC_REFRESH_SCRIPT.replace("__PAGE_VERSION__", json.dumps(page_version, ensure_ascii=False))}
</body>
</html>"""

def build_dashboard(
    business_date: str,
    *,
    universe_root: Path = UNIVERSE_ROOT,
    jobs_root: Path = JOBS_ROOT,
    prediction_root: Path = PREDICTION_ROOT,
    exclusion_root: Path = EXCLUSION_ROOT,
    result_root: Path = RESULT_ROOT,
    prospective_root: Path = PROSPECTIVE_ROOT,
    runtime_path: Path = RUNTIME_PATH,
    health_watch_path: Path = HEALTH_WATCH_PATH,
    workspace_path: Path = WORKSPACE_LATEST,
    output_root: Path = DASHBOARD_ROOT,
    now: datetime | None = None,
) -> dict[str, Any]:
    errors: list[str] = []
    universe_path = Path(universe_root) / f"{business_date}.json"
    jobs_path = Path(jobs_root) / f"{business_date}.json"
    universe = _read_json(universe_path, errors, "universe", {})
    jobs_payload = _read_json(jobs_path, errors, "base_jobs", {})
    if not isinstance(universe, dict):
        universe = {}
    if not isinstance(jobs_payload, dict):
        jobs_payload = {}
    fixtures = [row for row in (universe.get("fixtures") or []) if isinstance(row, dict)]
    jobs = [
        row
        for row in (jobs_payload.get("jobs") or [])
        if isinstance(row, dict)
        and (
            not str(_pick(row, "business_date", "businessDate") or "").strip()
            or str(_pick(row, "business_date", "businessDate") or "").strip() == business_date
        )
    ]
    records = _read_records(Path(prediction_root), errors)
    exclusions = _exclusion_index(Path(exclusion_root), errors)
    result_index = _result_index(Path(result_root), errors)
    formal_rows = _read_jsonl(Path(prospective_root) / "ledger.jsonl", errors, "prospective:ledger")
    exploratory_rows = _read_jsonl(Path(prospective_root) / "exploratory_settlements.jsonl", errors, "prospective:exploratory")
    formal_samples = {str(row.get("prediction_id")): row for row in formal_rows if row.get("prediction_id")}
    exploratory_samples = {str(row.get("prediction_id")): row for row in exploratory_rows if row.get("prediction_id")}
    summary_payload = _read_optional_json(Path(prospective_root) / "summary.json", errors, "prospective:summary", {})
    if not isinstance(summary_payload, dict):
        summary_payload = {}
    runtime = _read_optional_json(Path(runtime_path), errors, "runtime", {})
    if not isinstance(runtime, dict):
        runtime = {}
    health_watch = _read_optional_json(Path(health_watch_path), [], "health_watch", {})
    if not isinstance(health_watch, dict):
        health_watch = {}
    completed, history = _workspace_history(Path(workspace_path), errors)
    cards: list[dict[str, Any]] = []
    for fixture in fixtures:
        current_job_resolution = resolve_current_job_for_match(
            jobs,
            _prematch_identity(fixture, None),
        )
        if current_job_resolution["status"] == "UNIQUE":
            job = current_job_resolution.get("selected_job")
        elif current_job_resolution["status"] == "CONFLICT":
            job = _conflict_job(fixture, current_job_resolution)
        else:
            job = None
        selection = None
        record = None
        if (
            current_job_resolution["status"] == "UNIQUE"
            and str((job or {}).get("status") or "PENDING") == "FROZEN"
        ):
            selection = select_latest_legal_prematch(
                records.values(),
                identity=_prematch_identity(fixture, job),
            )
            record = selection.get("selected_record")
        cards.append(_card(
            fixture,
            job,
            record,
            result_index,
            exclusions,
            formal_samples,
            exploratory_samples,
            selection,
            current_job_resolution,
        ))
    cards.sort(key=lambda item: (_iso_sort(item.get("kickoff")), _text(item.get("match_num"))))
    counts = Counter(card.get("status") for card in cards)
    verified_results = sum(
        1
        for card in cards
        if isinstance(card.get("result"), dict) and card["result"].get("score_90m")
    )
    formal_total = summary_payload.get("formal_sample_count_total")
    if formal_total is None:
        formal_total = len(formal_rows)
    samples_added = summary_payload.get("samples_added_this_run")
    if samples_added is None:
        samples_added = 0
    excluded_count = summary_payload.get("excluded_prediction_count")
    if excluded_count is None:
        excluded_count = len(exclusions)
    health_overall = str(runtime.get("overall_status") or "UNKNOWN")
    display_status = {"HEALTHY": "正常", "DEGRADED": "部分异常", "FAILED": "失败", "RUNNING": "运行中", "UNKNOWN": "尚未运行"}.get(health_overall, health_overall)
    css_class = {"HEALTHY": "normal", "DEGRADED": "degraded", "FAILED": "failed", "RUNNING": "degraded"}.get(health_overall, "unknown")
    failed_steps = [name for name, value in (runtime.get("steps") or {}).items() if isinstance(value, dict) and value.get("status") not in {"SUCCESS", "SKIPPED"}]
    system_runtime_health = {
        "status": health_overall,
        "overall_status": health_overall,
        "display_status": display_status,
        "css_class": css_class,
        "updated_at": runtime.get("finished_at") or runtime.get("started_at"),
        "failed_steps": failed_steps,
    }
    prediction_quality_health = _current_prediction_quality_health(
        records,
        exclusions,
        jobs,
        runtime,
        health_watch,
        business_date,
    )
    payload = {
        "schema_version": "1.0",
        "generated_at": (now or datetime.now(SHANGHAI)).isoformat(),
        "business_date": business_date,
        "system_runtime_health": system_runtime_health,
        "prediction_quality_health": prediction_quality_health,
        "health": system_runtime_health,
        "universe": {
            "status": universe.get("status") or "UNAVAILABLE",
            "source": universe.get("source"),
            "fetched_at": universe.get("fetched_at"),
            "fixture_count": universe.get("fixture_count", len(fixtures)),
        },
        "summary": {
            "fixture_count": int(universe.get("fixture_count") or len(fixtures)),
            "card_count": len(cards),
            "frozen": counts.get("FROZEN", 0),
            "pending": counts.get("PENDING", 0),
            "insufficient_data": counts.get("INSUFFICIENT_DATA", 0),
            "prediction_failed": counts.get("PREDICTION_FAILED", 0),
            "missed": counts.get("MISSED_PREMATCH_WINDOW", 0),
            "verified_results": verified_results,
            # This count powers the current business-day RESULT filter.  The
            # workspace's cross-date rows remain an independent history view.
            "completed_count": verified_results,
            "historical_validation_count": len(completed),
            "history_count": len(history),
            "formal_prospective_total": int(formal_total or 0),
            "samples_added_today": int(samples_added or 0),
            "pilot_excluded_count": int(excluded_count or 0),
            "silent_missing_fixture": max(0, int(universe.get("fixture_count") or len(fixtures)) - len(cards)),
        },
        "data_errors": errors,
        "fixtures": cards,
        "completed": completed,
        "history": history,
    }
    output_root = Path(output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "latest.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output_root / "latest.html").write_text(render_dashboard(payload), encoding="utf-8")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the read-only Prediction Day product surface")
    parser.add_argument("--date", help="Business date YYYY-MM-DD")
    args = parser.parse_args()
    business_date = args.date or datetime.now(SHANGHAI).date().isoformat()
    payload = build_dashboard(business_date)
    print(json.dumps({
        "business_date": business_date,
        "dashboard_json": str(DASHBOARD_ROOT / "latest.json"),
        "dashboard_html": str(DASHBOARD_ROOT / "latest.html"),
        "fixture_count": payload["summary"]["fixture_count"],
        "card_count": payload["summary"]["card_count"],
        "frozen": payload["summary"]["frozen"],
        "pending": payload["summary"]["pending"],
        "insufficient_data": payload["summary"]["insufficient_data"],
        "verified_results": payload["summary"]["verified_results"],
        "formal_prospective_total": payload["summary"]["formal_prospective_total"],
        "silent_missing_fixture": payload["summary"]["silent_missing_fixture"],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
