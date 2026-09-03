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
    from exact_score_serving_policy import DEGRADED, exact_score_serving_presentation
except ImportError:  # package import used by tests
    from scripts.exact_score_serving_policy import DEGRADED, exact_score_serving_presentation

try:
    from closed_beta_copy import render_closed_beta_notice
except ImportError:  # package import used by tests
    from scripts.closed_beta_copy import render_closed_beta_notice


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
  --bg: #F7F5F1;
  --surface: #FFFFFF;
  --text: #111111;
  --muted: #6B7280;
  --quiet: #9CA3AF;
  --line: #E5E7EB;
  --accent: #FF6A00;
  --accent-soft: #FFF1E8;
  --warning: #B45309;
  --warning-soft: #FFF7ED;
  --danger: #B91C1C;
  --danger-soft: #FEF2F2;
}
* { box-sizing: border-box; }
html { background: var(--bg); }
body {
  min-width: 0;
  margin: 0;
  background: var(--bg);
  color: var(--text);
  font: 14px/1.45 "Inter", "Segoe UI", "Microsoft YaHei", sans-serif;
  -webkit-font-smoothing: antialiased;
}
a { color: inherit; }
button { font: inherit; }
button, a { -webkit-tap-highlight-color: transparent; }
[hidden] { display: none !important; }

.site {
  width: min(calc(100% - 68px), 1372px);
  margin: 0 auto;
  padding: 32px 0 44px;
}
.site-header {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 24px;
  padding-bottom: 17px;
  border-bottom: 1px solid var(--line);
}
.brand {
  display: flex;
  align-items: baseline;
  gap: 14px;
  min-width: 0;
}
.brand-name {
  flex: 0 0 auto;
  font-size: 25px;
  font-weight: 750;
  letter-spacing: -.055em;
}
.brand-subtitle {
  color: var(--muted);
  font-size: 10px;
  letter-spacing: .18em;
  text-transform: uppercase;
  white-space: nowrap;
}
.header-note {
  color: var(--muted);
  font-size: 11px;
  text-align: right;
  white-space: nowrap;
}
.dashboard-heading {
  display: flex;
  align-items: end;
  justify-content: space-between;
  gap: 24px;
  padding: 18px 0 12px;
}
.dashboard-heading h1 {
  display: flex;
  align-items: baseline;
  gap: 8px;
  flex: 0 1 auto;
  min-width: 0;
  margin: 0;
  font-size: 22px;
  line-height: 1.15;
  letter-spacing: -.04em;
  white-space: nowrap;
}
.dashboard-heading h1 .date-day { font-weight: 750; }
.dashboard-heading h1 .today { color: var(--muted); font-weight: 500; }
.fixture-count {
  margin-left: 8px;
  color: var(--muted);
  font-size: 12px;
  font-weight: 400;
  letter-spacing: 0;
}
.filters {
  display: grid;
  grid-template-columns: repeat(3, minmax(120px, 1fr));
  gap: 7px;
  width: min(100%, 660px);
}
.filter {
  min-height: 26px;
  padding: 3px 12px;
  border: 1px solid var(--line);
  border-radius: 999px;
  background: var(--surface);
  color: var(--text);
  cursor: pointer;
  font-size: 11px;
}
.filter:hover,
.filter[aria-pressed="true"] {
  border-color: #FFB27F;
  color: var(--accent);
}
.filter[aria-pressed="true"] { background: var(--accent-soft); }

.quality-warning,
.runtime-warning {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 5px 10px;
  margin: 0 0 12px;
  padding: 9px 12px;
  border-left: 2px solid var(--accent);
  background: var(--accent-soft);
  color: var(--muted);
  font-size: 12px;
}
.quality-warning strong,
.runtime-warning strong { color: var(--text); font-weight: 700; }
.runtime-warning { border-left-color: var(--danger); background: var(--danger-soft); }
.runtime-warning strong { color: var(--danger); }
.closed-beta-notice {
  margin-top: 9px;
  border-left-color: var(--line);
  background: transparent;
  color: var(--quiet);
  font-size: 11px;
}
.dashboard-trust {
  padding: 11px 0 0;
  border-top: 1px solid var(--line);
}
.dashboard-trust strong,
.dashboard-trust span {
  display: block;
  margin-top: 3px;
}

.fixture-table {
  overflow: hidden;
  border-top: 1px solid var(--line);
  background: var(--surface);
}
.table-header,
.fixture-row {
  display: grid;
  grid-template-columns: 150px 70px minmax(260px, 1.55fr) minmax(230px, 1.25fr) minmax(235px, 1.3fr) minmax(180px, 1fr);
  column-gap: 16px;
  padding-left: 9px;
  padding-right: 9px;
}
.table-header {
  min-height: 28px;
  align-items: center;
  color: var(--muted);
  background: #FCFBF9;
  font-size: 10px;
}
.fixture-row {
  min-height: 56px;
  align-items: center;
  border-bottom: 1px solid var(--line);
}
.fixture-row:hover { background: #FFFCF9; }
.fixture-row > * { min-width: 0; }
.identity-cell { min-width: 0; }
.cell-meta,
.match-number,
.kickoff,
.identity-competition,
.goal-signal,
.score-caption,
.score-top3,
.action-note {
  color: var(--muted);
  font-size: 11px;
}
.match-number { white-space: nowrap; }
.competition {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.identity-competition {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.kickoff { color: var(--text); font-variant-numeric: tabular-nums; }
.teams-cell { min-width: 0; }
.team-match {
  display: flex;
  align-items: baseline;
  gap: 7px;
  min-width: 0;
  font-weight: 650;
  letter-spacing: -.015em;
}
.team-match .team {
  min-width: 0;
  overflow-wrap: anywhere;
}
.team-match .home { text-align: right; }
.team-match .away { text-align: left; }
.versus {
  flex: 0 0 auto;
  color: var(--muted);
  font-size: 10px;
  font-weight: 400;
}
.result-inline {
  margin-top: 3px;
  color: var(--accent);
  font-size: 11px;
  font-weight: 650;
}
.probability-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
}
.probability-cell {
  display: grid;
  gap: 2px;
  min-width: 0;
}
.probability-cell span {
  color: var(--muted);
  font-size: 10px;
}
.probability-cell strong {
  font-variant-numeric: tabular-nums;
  font-size: 13px;
  line-height: 1;
}
.probability-cell.is-leading strong { color: var(--accent); }
.score-cell { min-width: 0; }
.score-caption { margin-bottom: 2px; }
.score-primary {
  display: flex;
  align-items: baseline;
  gap: 6px;
  font-size: 13px;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
}
.score-primary span {
  color: var(--muted);
  font-size: 10px;
  font-weight: 400;
}
.score-top3 {
  display: flex;
  flex-wrap: wrap;
  gap: 3px 10px;
  margin-top: 3px;
  font-variant-numeric: tabular-nums;
}
.score-top3 span { white-space: nowrap; }
.goal-signals {
  display: flex;
  flex-wrap: wrap;
  gap: 3px 10px;
  min-width: 0;
}
.goal-signal {
  white-space: nowrap;
  font-variant-numeric: tabular-nums;
}
.row-action {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  flex-wrap: wrap;
  gap: 5px 9px;
  text-align: right;
}
.prediction-unavailable { display: none; }
.empty-score-cell { visibility: hidden; }
.detail-link {
  color: var(--muted);
  font-size: 11px;
  text-decoration: none;
  white-space: nowrap;
}
.detail-link:hover { color: var(--accent); text-decoration: underline; }
.exception-note {
  color: var(--warning);
  font-size: 11px;
  font-weight: 650;
}
.exception-note.failed,
.exception-note.missed { color: var(--danger); }
.completed-note { color: var(--accent); font-size: 11px; font-weight: 650; }
.reason-detail {
  flex-basis: 100%;
  color: var(--muted);
  font-size: 10px;
}
.data-warning {
  margin: 12px 0;
  padding: 9px 12px;
  border-left: 2px solid var(--warning);
  background: var(--warning-soft);
  color: var(--warning);
  font-size: 11px;
}
.empty {
  padding: 46px 20px;
  color: var(--muted);
  text-align: center;
}
.history {
  margin-top: 22px;
  border-top: 1px solid var(--line);
}
.history-heading {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
  padding: 14px 0 9px;
}
.history-heading h2 { margin: 0; font-size: 15px; letter-spacing: -.02em; }
.history-heading span { color: var(--muted); font-size: 11px; }
.history-row {
  display: grid;
  grid-template-columns: 92px minmax(230px, 1fr) 65px minmax(180px, auto);
  gap: 14px;
  align-items: center;
  min-height: 47px;
  border-bottom: 1px solid var(--line);
  font-size: 12px;
}
.history-meta { color: var(--muted); font-size: 11px; }
.history-teams { font-weight: 650; }
.history-teams span { color: var(--muted); font-weight: 400; }
.history-score { color: var(--accent); font-size: 16px; font-variant-numeric: tabular-nums; }
.history-links { display: flex; flex-wrap: wrap; gap: 8px; color: var(--muted); font-size: 11px; }
.page-footer {
  display: flex;
  justify-content: space-between;
  gap: 18px;
  margin-top: 19px;
  padding-top: 12px;
  border-top: 1px solid var(--line);
  color: var(--quiet);
  font-size: 10px;
}
.page-footer span:last-child { text-align: right; }
.page-footer a { text-decoration: none; }
.page-footer a:hover { color: var(--accent); }

@media (max-width: 820px) {
  .site { width: calc(100% - 32px); padding: 16px 0 28px; }
  .site-header { align-items: center; padding-bottom: 13px; }
  .brand-subtitle { display: none; }
  .header-note { font-size: 10px; }
  .dashboard-heading { display: flex; align-items: end; padding: 15px 0 10px; }
  .dashboard-heading h1 { font-size: 19px; }
  .filters { width: auto; flex: 0 0 auto; margin-top: 0; grid-template-columns: repeat(3, auto); gap: 5px; }
  .filter { min-height: 27px; }
  .table-header { display: none; }
  .fixture-row {
    display: block;
    padding: 12px 10px 11px;
  }
  .fixture-row > * { margin-top: 9px; }
  .fixture-row > .identity-cell { margin-top: 0; }
  .identity-cell {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: 10px;
  }
  .fixture-row .competition { max-width: 70%; }
  .teams-cell { margin-top: 7px; }
  .team-match {
    display: grid;
    grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr);
    gap: 8px;
    font-size: 18px;
    line-height: 1.18;
  }
  .team-match .home,
  .team-match .away { text-align: left; }
  .team-match .away { text-align: right; }
  .versus { align-self: center; font-size: 11px; }
  .probability-grid { gap: 9px; margin-top: 11px; }
  .probability-cell span { font-size: 10px; }
  .probability-cell strong { font-size: 15px; }
  .score-cell {
    display: grid;
    grid-template-columns: auto minmax(0, 1fr);
    column-gap: 9px;
    align-items: baseline;
    padding-top: 9px;
    border-top: 1px solid var(--line);
  }
  .score-caption { margin: 0; }
  .score-primary { justify-self: end; }
  .score-top3 {
    grid-column: 1 / -1;
    margin-top: 4px;
    font-size: 10px;
  }
  .goal-signals {
    gap: 3px 12px;
    padding-top: 1px;
  }
  .row-action {
    justify-content: flex-start;
    text-align: left;
  }
  .empty-score-cell { display: none; }
  .goals-cell:empty { display: none; }
  .reason-detail { flex-basis: auto; }
  .history-row { grid-template-columns: 1fr auto; gap: 5px 12px; padding: 9px 0; }
  .history-meta, .history-links { grid-column: 1 / -1; }
  .page-footer { display: block; }
  .page-footer span { display: block; }
  .page-footer span:last-child { margin-top: 5px; text-align: left; }
}
@media (max-width: 360px) {
  .site { width: calc(100% - 24px); }
  .brand-name { font-size: 23px; }
  .header-note { max-width: 126px; white-space: normal; text-align: right; }
  .dashboard-heading { gap: 7px; }
  .dashboard-heading h1 { font-size: 16px; gap: 5px; }
  .fixture-count { margin-left: 3px; font-size: 11px; }
  .filter { padding-left: 6px; padding-right: 6px; font-size: 10px; }
  .fixture-row { padding-left: 7px; padding-right: 7px; }
  .team-match { font-size: 16px; }
  .probability-grid { gap: 6px; }
  .probability-cell strong { font-size: 14px; }
  .goal-signals { gap: 3px 8px; }
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
    valid = {key: value for key, value in values.items() if value is not None and 0 <= value <= 1}
    if not valid:
        return ""
    leader = max(valid, key=lambda key: valid[key])
    labels = {"home": "\u4e3b\u80dc", "draw": "\u5e73", "away": "\u5ba2\u80dc"}
    cells = []
    for key in ("home", "draw", "away"):
        percent = _format_percent(values.get(key))
        if percent is None:
            continue
        leading = " is-leading" if key == leader else ""
        cells.append(
            f'<div class="probability-cell{leading}">'
            f'<span>{labels[key]}</span><strong>{html.escape(percent)}</strong></div>'
        )
    return f'<div class="probability-grid">{"".join(cells)}</div>' if cells else ""


def _goal_signal_values(prediction: dict[str, Any]) -> list[tuple[str, str]]:
    signals: list[tuple[str, str]] = []
    btts = prediction.get("btts")
    if isinstance(btts, dict):
        yes = _number(btts.get("yes"))
        no = _number(btts.get("no"))
        candidates = [(yes, "BTTS \u662f"), (no, "BTTS \u5426")]
        valid = [(value, label) for value, label in candidates if value is not None and 0 <= value <= 1]
        if valid:
            value, label = max(valid, key=lambda item: item[0])
            percent = _format_percent(value)
            if percent:
                signals.append((label, percent))
    totals = prediction.get("totals")
    if isinstance(totals, list):
        under = 0.0
        over = 0.0
        has_under = False
        has_over = False
        for item in totals:
            if not isinstance(item, dict):
                continue
            probability = _number(item.get("probability"))
            goals = str(item.get("goals") or "").strip()
            if probability is None or probability < 0:
                continue
            if goals in {"0", "1", "2"}:
                under += probability
                has_under = True
            elif goals in {"3", "4", "5", "6+"}:
                over += probability
                has_over = True
        if has_under and has_over:
            value, label = (under, "\u5c0f2.5") if under >= over else (over, "\u59272.5")
            percent = _format_percent(value)
            if percent:
                signals.append((label, percent))
    return signals


def _goal_signals_html(prediction: dict[str, Any]) -> str:
    signals = _goal_signal_values(prediction)
    if not signals:
        return ""
    return '<div class="goal-signals">' + "".join(
        f'<span class="goal-signal">{html.escape(label)} {html.escape(percent)}</span>'
        for label, percent in signals
    ) + "</div>"


def _score_summary_html(prediction: dict[str, Any]) -> str:
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
    top3 = "".join(
        f'<span>{html.escape(row["score"])}'
        f'{(" " + html.escape(percent)) if (percent := _format_percent(row.get("probability"))) else ""}</span>'
        for row in rows[:3]
    )
    return (
        '<div class="score-cell"><div class="score-caption">\u6700\u9ad8\u6982\u7387\u6bd4\u5206</div>'
        f'<div class="score-primary"><strong>{html.escape(primary["score"])}</strong>{primary_probability_html}</div>'
        f'<div class="score-top3">{top3}</div></div>'
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
        '<div class="market-divergence"><span>\u6a21\u578b\u4e0e\u5e02\u573a</span>'
        f'<strong>\u4e3b\u80dc {html.escape(_format_percent(model_probability) or "")}'
        f' / \u5e02\u573a {html.escape(_format_percent(market_probability) or "")}</strong>'
        f'<small>\u5dee\u5f02 {html.escape(difference_text)}</small></div>'
    )


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
    del exact_score_serving
    status = str(card.get("status") or "PENDING")
    match_id = str(card.get("match_id") or "")
    prediction = card.get("prediction") if status == "FROZEN" else None
    prediction = prediction if isinstance(prediction, dict) else None
    result = card.get("result") if isinstance(card.get("result"), dict) else None
    has_result = bool(result and result.get("score_90m"))
    prediction_kind = "pilot" if card.get("pilot_excluded") and prediction else "formal" if prediction else "none"
    status_class = html.escape(status.lower(), quote=True)
    match_id_html = html.escape(match_id, quote=True)
    detail_link = (
        f'<a class="detail-link" href="../matches/{match_id_html}/">\u67e5\u770b\u8be6\u60c5</a>'
        if match_id
        else ""
    )
    if has_result:
        action_html = f'<span class="completed-note">{_card_status_copy(card)}</span>{detail_link}'
    elif prediction:
        pilot_html = (
            '<span class="action-note">\u8bd5\u8fd0\u884c\u9884\u6d4b \u00b7 \u4ec5\u4f9b\u89c2\u5bdf</span>'
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
        _score_summary_html(prediction)
        if prediction
        else '<div class="score-cell empty-score-cell" aria-hidden="true"></div>'
    )
    goals_html = (
        f'{_goal_signals_html(prediction)}{_market_divergence_html(prediction)}'
        if prediction
        else ""
    )
    match_number_text = _esc(card.get("match_num"), "\u2014")
    competition_text = _esc(card.get("competition"), "\u8d5b\u4e8b\u5f85\u5b9a")
    return (
        f'<article class="fixture-row status-{status_class} prediction-{prediction_kind}" '
        f'data-status="{html.escape(status, quote=True)}" '
        f'data-result="{"yes" if has_result else "no"}" '
        f'data-prediction-kind="{prediction_kind}">'
        '<div class="identity-cell">'
        f'<span class="match-number">{match_number_text}</span>'
        f'<span class="identity-competition">{competition_text}</span>'
        '</div>'
        f'<div class="kickoff">{html.escape(_format_kickoff(card.get("kickoff")))}</div>'
        f'<div class="teams-cell">{teams_html}<div class="row-action">{action_html}</div></div>'
        f'<div class="probability-cell-group">{probability_html}</div>'
        f'{score_html}'
        f'<div class="goals-cell">{goals_html}</div>'
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
            f'<strong class="history-score">{html.escape(str(result))}</strong>'
            f'<div class="history-links">{link_text}</div>'
            '</article>'
        )
    if not cards:
        return ""
    return (
        '<section id="historical-results" class="history">'
        '<div class="history-heading"><h2>\u5df2\u7ed3\u675f \u00b7 \u8d5b\u540e\u9a8c\u8bc1</h2>'
        f'<span>{len(cards)} \u573a\u5df2\u8bb0\u5f55</span></div>'
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
    if exact_score_serving["state"] == DEGRADED:
        return (
            '<div class="quality-warning" role="status">'
            '<strong>\u9884\u6d4b\u8d28\u91cf\u964d\u7ea7\uff0c\u4ec5\u4f9b\u89c2\u5bdf</strong>'
            '<span>\u6bd4\u5206\u6982\u7387\u4fdd\u7559\u539f\u59cb\u6a21\u578b\u8f93\u51fa\uff0c\u4e0d\u4f5c\u4e3a\u786e\u5b9a\u7b54\u6848\u3002</span>'
            '</div>'
        )
    if exact_score_serving["state"] != "NORMAL":
        return (
            '<div class="quality-warning" role="status">'
            '<strong>\u8d28\u91cf\u5f85\u786e\u8ba4\uff0c\u4e0d\u4f5c\u4e3a\u6b63\u5e38\u63a8\u8350</strong>'
            '<span>\u5f53\u524d\u53ea\u5c55\u793a\u5df2\u6709\u6982\u7387\uff0c\u4e0d\u6269\u5c55\u63a8\u8350\u5224\u65ad\u3002</span>'
            '</div>'
        )
    return ""


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
    fixture_count = int(summary.get("fixture_count") or len(payload.get("fixtures") or []))
    completed_count = int(summary.get("completed_count") or 0)
    exact_score_serving = exact_score_serving_presentation(quality_health)
    cards_html = "".join(
        _modern_card_html(card, exact_score_serving=exact_score_serving)
        for card in payload.get("fixtures") or []
        if isinstance(card, dict)
    )
    if not cards_html:
        cards_html = '<div class="empty">\u4eca\u5929\u6ca1\u6709\u53ef\u5c55\u793a\u7684\u6bd4\u8d5b\u3002</div>'
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
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(date_label)} \u00b7 FBOS</title>
<style>{MODERN_CSS}</style>
</head>
<body>
<main class="site">
<header class="site-header">
  <div class="brand"><span class="brand-name">FBOS</span><span class="brand-subtitle">Football betting \u00b7 one shot</span></div>
  <div class="header-note">Closed Beta \u00b7 \u6982\u7387\u5206\u6790\uff0c\u4e0d\u63d0\u4f9b\u8d2d\u5f69/\u4e0b\u6ce8\u670d\u52a1</div>
</header>
<section class="dashboard-heading">
  <h1><span class="date-day">{html.escape(date_label)}</span><span>\u00b7</span><span class="today">\u4eca\u5929</span><span class="fixture-count">{fixture_count} \u573a</span></h1>
  <div class="filters" aria-label="\u6bd4\u8d5b\u7b5b\u9009">
    <button class="filter" type="button" data-filter="ALL" aria-pressed="true">\u5168\u90e8</button>
    <button class="filter" type="button" data-filter="UPCOMING" aria-pressed="false">\u672a\u5f00\u8d5b</button>
  <button class="filter" type="button" data-filter="RESULT" data-result-count="{completed_count}" aria-pressed="false">\u5df2\u7ed3\u675f</button>
  </div>
</section>
{runtime_warning}{quality_warning}{data_warning}
<section class="fixture-table" id="fixture-list" aria-label="\u4eca\u65e5\u6bd4\u8d5b\u5217\u8868">
  <div class="table-header" aria-hidden="true">
    <span>\u7ade\u5f69\u7f16\u53f7 / \u8d5b\u4e8b</span><span>\u5f00\u7403</span><span>\u5bf9\u9635 / \u8d5b\u679c</span>
    <span>1X2 \u6982\u7387</span><span>\u6bd4\u5206\u6982\u7387 Top3</span><span>\u8fdb\u7403\u4fe1\u53f7</span>
  </div>
  {cards_html}
</section>
{historical_html}
{dashboard_trust}
<footer class="page-footer">
  <span>\u6b63\u5e38\u72b6\u6001\u4fdd\u6301\u5b89\u9759\uff1b\u53ea\u6709\u5f71\u54cd\u5224\u65ad\u7684\u5f02\u5e38\u624d\u4f1a\u663e\u793a\u3002</span>
  <span>Closed Beta \u00b7 \u9884\u6d4b\u53ef\u80fd\u51fa\u9519\uff0c\u4ec5\u4f9b\u6bd4\u8d5b\u5206\u6790\u4e0e\u7814\u7a76\u53c2\u8003\uff1b\u7406\u6027\u53c2\u4e0e\uff0c\u672a\u6210\u5e74\u4eba\u9650\u5236\u3002</span>
</footer>
</main>
<script>
const buttons = Array.from(document.querySelectorAll('[data-filter]'));
const cards = Array.from(document.querySelectorAll('.fixture-row'));
const historicalResults = document.querySelector('#historical-results');
buttons.forEach(button => button.addEventListener('click', () => {{
  const filter = button.dataset.filter;
  buttons.forEach(item => item.setAttribute('aria-pressed', String(item === button)));
  cards.forEach(card => {{
    const match = filter === 'ALL'
      || (filter === 'UPCOMING' && card.dataset.result !== 'yes')
      || (filter === 'RESULT' && card.dataset.result === 'yes');
    card.hidden = !match;
  }});
  if (historicalResults) historicalResults.hidden = filter !== 'ALL' && filter !== 'RESULT';
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
    verified_results = sum(1 for card in cards if card.get("result"))
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
            "completed_count": len(completed),
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
