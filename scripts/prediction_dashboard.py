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
    "FROZEN": "已预测",
    "PENDING": "等待预测",
    "INSUFFICIENT_DATA": "数据不足",
    "PREDICTION_FAILED": "预测失败",
    "MISSED_PREMATCH_WINDOW": "错过赛前窗口",
    "REMOVED_FROM_CURRENT_UNIVERSE": "已移出当前赛程",
}
REASON_LABELS = {
    "MISSING_RECENT_FORM": "近期比赛数据不足",
    "MISSING_MARKET_INTELLIGENCE": "缺少最低市场情报",
    "INPUT_TIMESTAMP_UNVERIFIED": "赛前数据时间无法验证",
    "SOURCE_FETCH_FAILED": "赛前数据源获取失败",
    "CACHE_PROVENANCE_INVALID": "近期数据缓存来源无法验证",
    "INPUT_SNAPSHOT_CONSTRUCTION_FAILED": "赛前输入快照构建失败",
    "INPUT_PROVENANCE_UNVERIFIED": "赛前输入来源无法验证",
    "IDENTITY_UNRESOLVED": "比赛身份无法可靠匹配",
    "PREDICTION_FAILED": "模型运行失败",
    "MISSED_PREMATCH_WINDOW": "已错过合法赛前预测窗口",
    "BASE_JOB_MISSING": "基础预测任务尚未生成",
    "PREDICTION_ARTIFACT_MISSING": "预测任务已冻结但正式记录缺失",
}

_CURRENT_FORMAL_STATUSES = {"formal", "frozen", "FROZEN"}
_QUALITY_STATUS_LABELS = {
    "HEALTHY": "正常",
    "ALERT": "异常",
    "INSUFFICIENT_SAMPLE": "样本不足",
    "WATCH": "观察中",
    "UNKNOWN": "暂不可用",
}
_QUALITY_ALERT_COPY = "今日比分预测出现异常集中，当前预测仍保留供观察。"


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


def _job_index(jobs: list[dict[str, Any]], business_date: str) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for job in jobs:
        match_id = str(job.get("match_id") or "").strip()
        if match_id:
            index[f"match_id:{match_id}"] = job
        job_id = str(job.get("job_id") or "").strip()
        if job_id:
            index[f"job_id:{job_id}"] = job
        if match_id:
            index[f"job_id:BASE-{business_date}-{match_id}"] = job
    return index


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
        "match_key": job.get("match_key") or job.get("canonical_match_id"),
        "home": job.get("home") or projected.get("home"),
        "away": job.get("away") or projected.get("away"),
        "kickoff_at": job.get("kickoff") or projected.get("kickoff"),
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
) -> dict[str, Any]:
    card = _fixture_projection(fixture)
    status = str((job or {}).get("status") or "PENDING")
    selection = prematch_selection or {}
    if prematch_selection is not None:
        record = selection.get("selected_record")
        prediction_id = str(selection.get("selected_prediction_id") or "") or None
    else:
        prediction_id = str((job or {}).get("prediction_id") or "") or None
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
        "selected_prediction_id": selection.get("selected_prediction_id") if prematch_selection is not None else prediction_id,
        "current_prediction_id": selection.get("selected_prediction_id") if prematch_selection is not None else prediction_id,
        "final_prematch_prediction_id": selection.get("selected_prediction_id") if prematch_selection is not None else prediction_id,
        "selected_freeze_created_at": selection.get("selected_freeze_created_at") if prematch_selection is not None else (record or {}).get("freeze_created_at"),
        "selected_source_cutoff_at": selection.get("selected_source_cutoff_at") if prematch_selection is not None else (record or {}).get("source_cutoff_at"),
        "superseded_count": int(selection.get("superseded_count") or 0) if prematch_selection is not None else 0,
        "prematch_selection": {
            "status": selection.get("status") if prematch_selection is not None else "LEGACY_POINTER",
            "reason": selection.get("reason") if prematch_selection is not None else "JOB_POINTER",
            "candidate_count": int(selection.get("candidate_count") or 0) if prematch_selection is not None else int(bool(record)),
            "selected_prediction_id": selection.get("selected_prediction_id") if prematch_selection is not None else prediction_id,
            "selected_freeze_created_at": selection.get("selected_freeze_created_at") if prematch_selection is not None else (record or {}).get("freeze_created_at"),
            "selected_source_cutoff_at": selection.get("selected_source_cutoff_at") if prematch_selection is not None else (record or {}).get("source_cutoff_at"),
            "superseded_count": int(selection.get("superseded_count") or 0) if prematch_selection is not None else 0,
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
    })
    return card


def _esc(value: Any) -> str:
    return html.escape(_text(value))


MODERN_CSS = r"""
:root {
  --bg: #081117;
  --surface: #101b23;
  --surface-raised: #16252e;
  --surface-soft: #0c151c;
  --line: #273b45;
  --text: #f1f7f5;
  --muted: #9aadb3;
  --quiet: #71858d;
  --accent: #69dfb9;
  --accent-soft: rgba(105, 223, 185, .12);
  --warning: #e9b567;
  --warning-soft: rgba(233, 181, 103, .12);
  --danger: #ef8b91;
  --danger-soft: rgba(239, 139, 145, .13);
  --blue: #8aaeff;
  --max: 1240px;
}
* { box-sizing: border-box; }
html { background: var(--bg); scroll-behavior: smooth; }
body {
  margin: 0;
  color: var(--text);
  background: radial-gradient(circle at 12% -10%, rgba(105, 223, 185, .10), transparent 30rem), var(--bg);
  font: 15px/1.55 "Segoe UI", "Microsoft YaHei", sans-serif;
}
a { color: var(--accent); text-decoration: none; }
a:hover { text-decoration: underline; }
button { font: inherit; }
.shell { width: min(calc(100% - 32px), var(--max)); margin: 0 auto; padding: 24px 0 56px; }
.topbar { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 16px; align-items: end; padding-bottom: 24px; border-bottom: 1px solid var(--line); }
.brand-kicker { color: var(--accent); font-size: 11px; font-weight: 700; letter-spacing: .16em; text-transform: uppercase; }
h1 { margin: 8px 0 4px; font-size: clamp(32px, 5vw, 46px); line-height: 1.05; letter-spacing: -.045em; }
.date-line { color: var(--muted); font-size: 15px; }
.current-date { display: flex; flex-wrap: wrap; gap: 6px 10px; align-items: baseline; margin-top: 16px; color: var(--muted); }
.current-date .date-label { color: var(--quiet); font-size: 12px; }
.current-date strong { color: var(--text); font-size: 16px; }
.current-date .date-context { color: var(--accent); font-size: 13px; }
.refresh-line { color: var(--quiet); font-size: 12px; line-height: 1.45; text-align: right; }
.refresh-line strong { color: var(--muted); font-weight: 600; }
.health-stack { display: flex; flex-wrap: wrap; gap: 8px; margin: 16px 0 0; }
.health-alert { display: inline-flex; flex: 1 1 auto; min-height: 44px; flex-wrap: wrap; gap: 6px 12px; align-items: center; margin: 0; padding: 8px 12px; border: 1px solid rgba(233, 181, 103, .34); border-radius: 12px; background: var(--warning-soft); color: #f4d39d; font-size: 13px; }
.health-alert.alert { border-color: rgba(239, 139, 145, .42); background: var(--danger-soft); color: #ffc3c7; }
.health-alert.normal { border-color: rgba(105, 223, 185, .24); background: var(--accent-soft); color: var(--muted); }
.health-alert strong { color: inherit; }
.health-alert span { color: var(--muted); }
.day-summary { display: flex; flex-wrap: wrap; justify-content: space-between; gap: 12px 20px; align-items: end; margin: 28px 0 18px; }
.day-summary h2 { margin: 0; font-size: 24px; letter-spacing: -.025em; }
.day-summary p { margin: 4px 0 0; color: var(--muted); font-size: 14px; }
.summary-count { display: flex; flex-wrap: wrap; gap: 8px; align-items: baseline; color: var(--muted); }
.summary-count strong { color: var(--accent); font-size: 30px; line-height: 1; letter-spacing: -.05em; }
.summary-count .summary-date { color: var(--quiet); font-size: 12px; }
.summary-stats { display: flex; flex-wrap: wrap; gap: 6px 12px; color: var(--quiet); font-size: 13px; }
.summary-stats span + span { padding-left: 12px; border-left: 1px solid var(--line); }
.toolbar { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; margin: 20px 0 18px; }
.toolbar-label { margin-right: 4px; color: var(--muted); font-size: 13px; }
.filter { min-height: 44px; padding: 8px 14px; border: 1px solid var(--line); border-radius: 999px; color: var(--muted); background: transparent; cursor: pointer; }
.filter:hover, .filter:focus-visible, .filter[aria-pressed="true"] { border-color: var(--accent); color: var(--bg); background: var(--accent); }
.current-day { margin-top: 4px; }
.section-heading { display: flex; flex-wrap: wrap; justify-content: space-between; gap: 8px 16px; align-items: baseline; }
.section-heading h2 { margin: 0; font-size: 22px; letter-spacing: -.025em; }
.section-heading p { margin: 0; color: var(--muted); font-size: 13px; }
.competition-list { display: grid; gap: 24px; margin-top: 16px; }
.competition-group { min-width: 0; }
.competition-heading { display: flex; flex-wrap: wrap; align-items: baseline; gap: 8px 12px; margin-bottom: 9px; }
.competition-heading h3 { margin: 0; font-size: 16px; letter-spacing: -.01em; }
.competition-heading span { color: var(--quiet); font-size: 12px; }
.fixture-list { display: grid; grid-template-columns: 1fr; gap: 12px; }
.fixture-card-link { display: block; min-width: 0; color: inherit; text-decoration: none; border-radius: 16px; }
.fixture-card-link:hover { text-decoration: none; }
.fixture-card-link:focus-visible { outline: 3px solid var(--accent); outline-offset: 3px; }
.fixture-card { min-width: 0; height: 100%; overflow: hidden; border: 1px solid var(--line); border-left: 3px solid var(--quiet); border-radius: 16px; background: var(--surface); transition: border-color .18s ease, background .18s ease, transform .18s ease; }
.fixture-card-link:hover .fixture-card { border-color: rgba(105, 223, 185, .46); background: var(--surface-raised); transform: translateY(-1px); }
.fixture-card.status-frozen { border-left-color: var(--accent); }
.fixture-card.status-insufficient_data { border-left-color: var(--warning); }
.fixture-card.status-prediction_failed, .fixture-card.status-missed_prematch_window { border-left-color: var(--danger); }
.fixture-card.status-pending { border-left-color: var(--blue); }
.fixture-main { padding: 16px; }
.fixture-meta { display: flex; justify-content: space-between; gap: 12px; align-items: center; color: var(--muted); font-size: 13px; }
.fixture-meta .competition { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.match-number { color: var(--quiet); white-space: nowrap; }
.teams { display: grid; grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr); gap: 10px; align-items: center; margin: 16px 0 12px; font-size: clamp(20px, 2.4vw, 27px); font-weight: 700; line-height: 1.18; letter-spacing: -.035em; }
.team { min-width: 0; overflow-wrap: anywhere; }
.team.away { text-align: right; }
.teams .versus { color: var(--quiet); font-size: 12px; font-weight: 600; letter-spacing: .08em; text-transform: uppercase; }
.fixture-subline { display: flex; flex-wrap: wrap; justify-content: space-between; gap: 8px 12px; align-items: center; }
.kickoff { color: var(--muted); font-size: 13px; }
.status-badge { display: inline-flex; min-height: 30px; align-items: center; border-radius: 999px; padding: 4px 9px; color: var(--muted); background: var(--surface-raised); font-size: 12px; font-weight: 700; white-space: nowrap; }
.detail-link { color: var(--muted); font-size: 12px; white-space: nowrap; }
.status-frozen .status-badge { color: var(--accent); background: var(--accent-soft); }
.fixture-card.prediction-pilot { border-left-color: var(--warning); }
.prediction-pilot .status-badge { color: var(--warning); background: var(--warning-soft); }
.prediction-pilot .score-focus strong { color: var(--warning); }
.prediction-pilot .signal.accent { border-color: rgba(233, 181, 103, .35); color: var(--warning); background: var(--warning-soft); }
.status-insufficient_data .status-badge { color: var(--warning); background: var(--warning-soft); }
.status-prediction_failed .status-badge, .status-missed_prematch_window .status-badge { color: var(--danger); background: var(--danger-soft); }
.reason { display: flex; flex-wrap: wrap; gap: 5px 10px; align-items: baseline; margin-top: 14px; padding: 10px 12px; border: 1px solid rgba(233, 181, 103, .25); border-radius: 10px; background: var(--warning-soft); color: #f4d39d; }
.reason strong { font-size: 13px; }
.pilot-note { display: flex; flex-wrap: wrap; gap: 6px 10px; align-items: baseline; margin-top: 12px; color: var(--warning); font-size: 13px; }
.pilot-note span { color: var(--muted); font-size: 12px; }
.prediction-panel { margin-top: 16px; padding-top: 16px; border-top: 1px solid var(--line); }
.prediction-topline { display: flex; justify-content: space-between; gap: 12px; align-items: baseline; }
.prediction-label { color: var(--muted); font-size: 12px; letter-spacing: .04em; }
.score-serving-note { margin-top: 10px; padding: 8px 10px; border-left: 2px solid var(--warning); border-radius: 0 8px 8px 0; color: #f4d39d; background: var(--warning-soft); font-size: 12px; }
.score-serving-note.degraded { border-left-color: var(--danger); color: #ffc3c7; background: var(--danger-soft); }
.probability-distribution { margin-top: 12px; }
.probability-heading { display: flex; justify-content: space-between; gap: 8px; color: var(--muted); font-size: 12px; }
.probability-heading span { color: var(--quiet); }
.probability-track { display: flex; gap: 2px; height: 10px; margin-top: 7px; overflow: hidden; border-radius: 999px; background: var(--surface-soft); }
.probability-segment { min-width: 2px; height: 100%; }
.probability-segment.home { background: #5fcda9; }
.probability-segment.draw { background: #91a6ac; }
.probability-segment.away { background: #7d9fec; }
.probability-cells { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 6px; margin-top: 8px; }
.probability-cell { min-width: 0; padding: 8px; border: 1px solid rgba(154, 173, 179, .18); border-radius: 10px; background: var(--surface-soft); }
.probability-cell.is-leading { border-color: rgba(105, 223, 185, .42); background: var(--accent-soft); }
.probability-cell span { display: block; color: var(--muted); font-size: 12px; }
.probability-cell strong { display: block; margin-top: 2px; color: var(--text); font-size: 16px; font-variant-numeric: tabular-nums; }
.signal-row { display: flex; flex-wrap: wrap; gap: 7px; margin-top: 12px; }
.signal { display: inline-flex; min-height: 30px; align-items: center; padding: 5px 9px; border: 1px solid var(--line); border-radius: 9px; color: var(--muted); background: var(--surface-raised); font-size: 13px; }
.signal.accent { border-color: rgba(105, 223, 185, .35); color: var(--accent); background: var(--accent-soft); }
.score-focus { display: flex; flex-wrap: wrap; align-items: baseline; gap: 8px; margin-top: 14px; }
.score-focus strong { color: var(--accent); font-size: 30px; line-height: 1; letter-spacing: -.06em; }
.score-focus .score-label { color: var(--muted); font-size: 13px; }
.score-focus .score-prob { color: var(--text); font-size: 14px; font-variant-numeric: tabular-nums; }
.score-focus .score-mode { color: var(--quiet); font-size: 12px; }
.score-focus .neighbors { flex-basis: 100%; color: var(--muted); font-size: 12px; }
.score-context { margin: 5px 0 0; color: var(--quiet); font-size: 12px; }
.market-strip { display: flex; flex-wrap: wrap; gap: 7px; margin-top: 12px; }
.market-item { min-width: 0; padding: 7px 9px; border: 1px solid var(--line); border-radius: 9px; color: var(--muted); background: rgba(8, 17, 23, .5); font-size: 13px; }
.market-item strong { color: var(--text); font-weight: 600; }
.market-item small { display: block; margin-top: 2px; color: var(--quiet); }
.market-item .movement { color: var(--warning); }
.data-line { display: flex; flex-wrap: wrap; gap: 6px 12px; margin-top: 12px; color: var(--quiet); font-size: 12px; }
.data-line strong { color: var(--muted); font-weight: 600; }
.prediction-empty, .compact-empty { display: flex; flex-wrap: wrap; gap: 4px 8px; align-items: baseline; margin-top: 14px; padding: 10px 12px; border: 1px dashed rgba(154, 173, 179, .28); border-radius: 10px; color: var(--muted); background: var(--surface-soft); font-size: 13px; }
.prediction-empty strong { color: var(--text); }
.result-line { display: flex; flex-wrap: wrap; gap: 8px 13px; align-items: baseline; margin: 14px -1px -1px; padding: 10px 12px; border: 1px solid rgba(105, 223, 185, .24); border-radius: 10px; background: var(--accent-soft); color: var(--accent); }
.history-surface { margin-top: 32px; border: 1px solid var(--line); border-radius: 16px; background: var(--surface); }
.history-surface summary { display: flex; min-height: 56px; justify-content: space-between; gap: 12px; align-items: center; padding: 14px 16px; cursor: pointer; list-style: none; font-size: 16px; font-weight: 700; }
.history-surface summary::-webkit-details-marker { display: none; }
.history-surface summary::after { content: "+"; color: var(--accent); font-size: 20px; font-weight: 400; }
.history-surface[open] summary::after { content: "–"; }
.history-count { color: var(--quiet); font-size: 12px; font-weight: 500; }
.history-content { padding: 0 16px 16px; }
.historical-result { display: grid; grid-template-columns: 190px minmax(160px, 1fr) 70px minmax(140px, auto); gap: 12px; align-items: center; padding: 12px 0; border-top: 1px solid var(--line); }
.historical-meta { color: var(--muted); font-size: 12px; }
.historical-teams { font-weight: 600; overflow-wrap: anywhere; }
.historical-teams span { color: var(--quiet); font-weight: 400; }
.historical-score { color: var(--accent); font-size: 20px; font-variant-numeric: tabular-nums; }
.historical-links { display: flex; gap: 10px; flex-wrap: wrap; font-size: 12px; }
.historical-links a { min-height: 32px; display: inline-flex; align-items: center; }
.data-warning { margin: 16px 0 0; padding: 10px 12px; border: 1px solid rgba(239, 139, 145, .32); border-radius: 10px; background: var(--danger-soft); color: #ffc3c7; font-size: 13px; }
.page-footer { display: grid; gap: 12px; margin-top: 28px; padding-top: 16px; border-top: 1px solid var(--line); }
.legacy-link { color: var(--quiet); font-size: 12px; }
.page-footer .health-alert.closed-beta-notice { display: grid; flex: none; gap: 3px 12px; min-height: 0; padding: 12px 0 0; border: 0; border-top: 1px solid var(--line); border-radius: 0; background: transparent; color: var(--quiet); font-size: 12px; }
.page-footer .closed-beta-notice strong { color: var(--muted); font-size: 12px; }
.page-footer .closed-beta-notice span { color: var(--quiet); }
@media (min-width: 760px) { .fixture-list { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 700px) { .topbar { display: block; } .refresh-line { margin-top: 12px; text-align: left; } .current-date { margin-top: 12px; } .historical-result { grid-template-columns: 1fr auto; } .historical-meta, .historical-links { grid-column: 1 / -1; } }
@media (max-width: 560px) { .shell { width: min(calc(100% - 24px), var(--max)); padding: 20px 0 40px; } h1 { font-size: 36px; } .day-summary { margin-top: 22px; } .summary-stats span + span { padding-left: 8px; } .fixture-main { padding: 14px; } .teams { font-size: 21px; } .probability-cell { padding: 7px 6px; } .probability-cell strong { font-size: 15px; } .history-content { padding-inline: 12px; } }
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
    return str(value or "").replace("-", "–")


def _signal(label: str, value: Any, css: str = "") -> str:
    if value in (None, "", []):
        return ""
    return f'<span class="signal {css}">{html.escape(label)} · {html.escape(_text(value))}</span>'


def _percent(value: Any, fallback: str = "—") -> str:
    number = _number(value)
    if number is None:
        return fallback
    return f"{number * 100:.1f}%"


def _score_probability(prediction: dict[str, Any], score: Any) -> float | None:
    target = str(score or "").strip()
    if not target:
        return None
    for row in prediction.get("score_distribution") or []:
        if not isinstance(row, dict):
            continue
        if str(row.get("score") or row.get("value") or "").strip() == target:
            return _number(row.get("probability"))
    for row in prediction.get("score_top3") or []:
        if not isinstance(row, dict):
            continue
        if str(row.get("score") or row.get("value") or "").strip() == target:
            return _number(row.get("probability"))
    return None


def _top_total_goal(prediction: dict[str, Any]) -> tuple[str, float] | None:
    candidates = []
    for row in prediction.get("totals") or []:
        if not isinstance(row, dict):
            continue
        probability = _number(row.get("probability"))
        if probability is not None and row.get("goals") not in (None, ""):
            candidates.append((str(row["goals"]), probability))
    return max(candidates, key=lambda item: item[1]) if candidates else None


def _probability_distribution_html(probabilities: dict[str, Any]) -> str:
    keys = ("home", "draw", "away")
    labels = {"home": "主胜", "draw": "平局", "away": "客胜"}
    values = {key: _number(probabilities.get(key)) for key in keys}
    if any(value is None for value in values.values()):
        return '<div class="prediction-empty"><strong>胜平负概率</strong><span>当前字段不足，暂不展示分布。</span></div>'
    numeric = {key: float(values[key]) for key in keys}
    total = sum(max(value, 0.0) for value in numeric.values())
    if total <= 0:
        return '<div class="prediction-empty"><strong>胜平负概率</strong><span>当前字段不足，暂不展示分布。</span></div>'
    leader = max(numeric, key=numeric.get)
    segments = "".join(
        f'<span class="probability-segment {key}" style="width:{max(numeric[key], 0.0) / total * 100:.1f}%"></span>'
        for key in keys
    )
    cells = "".join(
        f'<div class="probability-cell{" is-leading" if key == leader else ""}"><span>{labels[key]}</span><strong>{_percent(numeric[key])}</strong></div>'
        for key in keys
    )
    aria = "、".join(f"{labels[key]} {_percent(numeric[key])}" for key in keys)
    return (
        f'<div class="probability-distribution" role="img" aria-label="胜平负概率分布：{html.escape(aria)}">'
        '<div class="probability-heading"><strong>胜平负概率</strong><span>三项合计按现有数值展示</span></div>'
        f'<div class="probability-track" aria-hidden="true">{segments}</div>'
        f'<div class="probability-cells">{cells}</div>'
        '</div>'
    )


def _data_completeness_label(prediction: dict[str, Any]) -> str:
    grade = str(prediction.get("data_grade") or "").strip().upper()
    return {"A": "较完整", "B": "已记录", "C": "有限"}.get(grade, "待补充")


def _modern_prediction_html(
    prediction: dict[str, Any],
    *,
    pilot_excluded: bool = False,
    exact_score_serving: dict[str, str] | None = None,
) -> str:
    serving = exact_score_serving or exact_score_serving_presentation(None)
    primary = prediction.get("primary_score") or prediction.get("unique_score")
    neighbors = prediction.get("neighbor_scores") or []
    market = prediction.get("market_summary") or {}
    probabilities = prediction.get("probabilities") or {}
    signal_html = _signal("1X2", prediction.get("one_x_two_direction"), "accent")
    score_probability = _score_probability(prediction, primary)
    neighbor_text = " · ".join(_score_label(score) for score in neighbors)
    score_probability_html = (
        f'<span class="score-prob">{html.escape(_percent(score_probability))}</span>'
        if score_probability is not None
        else '<span class="score-prob">概率暂未提供</span>'
    )
    market_items = []
    btts = prediction.get("btts") or {}
    btts_yes = _number(btts.get("yes")) if isinstance(btts, dict) else None
    btts_no = _number(btts.get("no")) if isinstance(btts, dict) else None
    if btts_yes is not None or btts_no is not None:
        btts_parts = []
        if btts_yes is not None:
            btts_parts.append(f"是 {_percent(btts_yes)}")
        if btts_no is not None:
            btts_parts.append(f"否 {_percent(btts_no)}")
        market_items.append(f'<div class="market-item"><strong>双方进球</strong><small>{html.escape(" · ".join(btts_parts))}</small></div>')
    top_total = _top_total_goal(prediction)
    if top_total:
        goals, probability = top_total
        market_items.append(f'<div class="market-item"><strong>总进球 mode</strong><small>{html.escape(goals)}球 · {_percent(probability)}</small></div>')
    asian = market.get("asian_handicap")
    total = market.get("total_line")
    if asian or total:
        if asian:
            movement = f'<small class="movement">{html.escape(str(asian.get("movement")))}</small>' if asian.get("movement") else ""
            market_items.append(f'<div class="market-item"><strong>AH · 主 {html.escape(str(asian.get("line")))}</strong>{movement}</div>')
        if total:
            direction = total.get("direction") or market.get("total_direction")
            direction_text = f" · {html.escape(str(direction))}" if direction else ""
            movement = f'<small class="movement">{html.escape(str(total.get("movement")))}</small>' if total.get("movement") else ""
            market_items.append(f'<div class="market-item"><strong>O/U · {html.escape(str(total.get("line")))}{direction_text}</strong>{movement}</div>')
    market_html = f'<div class="market-strip">{"".join(market_items)}</div>' if market_items else ""
    pilot_note = '<div class="pilot-note"><strong>试运行预测</strong><span>不纳入正式验证</span></div>' if pilot_excluded else ""
    serving_note = (
        f'<div class="score-serving-note {html.escape(serving["state"].lower())}" role="status">'
        f'{html.escape(serving["note"])}</div>'
        if serving.get("note")
        else ""
    )
    return (
        '<section class="prediction-panel">'
        '<div class="prediction-topline">'
        f'<div class="prediction-label">{html.escape(serving["label"])}</div>'
        f'<span class="prediction-state">{html.escape(_data_completeness_label(prediction))} 数据</span>'
        '</div>'
        f'{serving_note}{pilot_note}'
        f'{_probability_distribution_html(probabilities)}'
        f'<div class="signal-row">{signal_html}</div>'
        '<div class="score-focus">'
        f'<span class="score-label">最可能比分 · <span class="score-mode">概率 mode</span></span>'
        f'<strong>{html.escape(_score_label(primary) if primary else "—")}</strong>'
        f'{score_probability_html}'
        f'<span class="neighbors">{("候选 Top2/3 · " + html.escape(neighbor_text)) if neighbor_text else ""}</span>'
        '</div>'
        '<p class="score-context">单格概率最高，不是确定答案。</p>'
        f'{market_html}'
        f'<div class="data-line"><span>数据完整度</span><strong>{html.escape(_data_completeness_label(prediction))}</strong></div>'
        '</section>'
    )


def _modern_result_html(card: dict[str, Any]) -> str:
    result = card.get("result") or {}
    score = result.get("score_90m")
    if not score:
        return ""
    return f'<div class="result-line"><strong>90分钟赛果 · {html.escape(str(score))}</strong></div>'


def _historical_results_html(rows: list[dict[str, Any]]) -> str:
    title = "赛后与历史复盘"
    if not rows:
        return (
            f'<details id="historical-results" class="history-surface">'
            f'<summary><span>{title}</span><span class="history-count">暂无可展示记录</span></summary>'
            '<div class="history-content"><div class="compact-empty">赛后复盘将在结果核验后进入这里。</div></div>'
            '</details>'
        )
    cards = []
    for row in rows:
        status = row.get("historical_status") or ("\u5df2\u5b8c\u8d5b" if row.get("result_90m") else "\u5f85\u590d\u76d8")
        links = []
        if row.get("prematch_report_url"):
            links.append(f'<a href="{html.escape(str(row["prematch_report_url"]), quote=True)}">\u8d5b\u524d\u5feb\u7167</a>')
        if row.get("postmatch_report_url"):
            links.append(f'<a href="{html.escape(str(row["postmatch_report_url"]), quote=True)}">\u8d5b\u540e\u590d\u76d8</a>')
        cards.append(
            '<article class="historical-result" data-result="yes">'
            f'<div class="historical-meta">{_esc(row.get("kickoff"))} · {html.escape(str(status))}</div>'
            f'<div class="historical-teams">{_esc(row.get("home"))}<span> vs </span>{_esc(row.get("away"))}</div>'
            f'<strong class="historical-score">{_esc(row.get("result_90m"))}</strong>'
            f'<div class="historical-links">{" · ".join(links) if links else ""}</div>'
            '</article>'
        )
    return (
        f'<details id="historical-results" class="history-surface">'
        f'<summary><span>{title}</span><span class="history-count">{len(cards)} 条</span></summary>'
        f'<div class="history-content">{"".join(cards)}</div>'
        '</details>'
    )


def _modern_card_html(
    card: dict[str, Any],
    *,
    exact_score_serving: dict[str, str] | None = None,
) -> str:
    status = str(card.get("status") or "PENDING")
    match_id = str(card.get("match_id") or "")
    pilot_excluded = bool(card.get("pilot_excluded") and card.get("prediction"))
    prediction_kind = "pilot" if pilot_excluded else "formal" if card.get("prediction") else "none"
    reason_html = ""
    if card.get("reason_code"):
        reason_html = f'<div class="reason"><strong>{html.escape(str(card.get("reason_text") or "数据暂不可用"))}</strong></div>'
    prediction_html = (
        _modern_prediction_html(
            card["prediction"],
            pilot_excluded=pilot_excluded,
            exact_score_serving=exact_score_serving,
        )
        if card.get("prediction")
        else f'<div class="prediction-empty"><strong>{html.escape(str(card.get("status_label") or status))}</strong><span>当前只展示比赛身份与状态。</span></div>'
    )
    detail_url = f'../matches/{html.escape(match_id, quote=True)}/'
    card_label = f'查看 {_text(card.get("home"), "主队")} 对阵 {_text(card.get("away"), "客队")} 详情'
    return (
        f'<a class="fixture-card-link" href="{detail_url}" aria-label="{html.escape(card_label, quote=True)}">'
        f'<article class="fixture-card status-{html.escape(status.lower())} prediction-{prediction_kind}" data-status="{html.escape(status)}" data-result="{"yes" if card.get("result") else "no"}" data-prediction-kind="{prediction_kind}">'
        '<div class="fixture-main">'
        '<div class="fixture-meta">'
        f'<span class="competition">{_esc(card.get("competition"))}</span>'
        f'<span class="match-number">{_esc(card.get("match_num"))}</span>'
        '</div>'
        f'<div class="teams"><span class="team home">{_esc(card.get("home"))}</span><span class="versus">vs</span><span class="team away">{_esc(card.get("away"))}</span></div>'
        f'<div class="fixture-subline"><span class="kickoff">开球 · {html.escape(_format_kickoff(card.get("kickoff")))}</span>'
        f'<span><span class="status-badge">{html.escape(str(card.get("status_label") or status))}</span> <span class="detail-link">查看详情</span></span></div>'
        f'{reason_html}{prediction_html}{_modern_result_html(card)}'
        '</div>'
        '</article>'
        '</a>'
    )


def _competition_sections_html(
    cards: list[dict[str, Any]],
    *,
    exact_score_serving: dict[str, str],
) -> str:
    groups: dict[str, list[dict[str, Any]]] = {}
    for card in cards:
        competition = str(card.get("competition") or "赛事待补充")
        groups.setdefault(competition, []).append(card)
    sections = []
    for competition, grouped_cards in groups.items():
        cards_html = "".join(
            _modern_card_html(card, exact_score_serving=exact_score_serving)
            for card in grouped_cards
        )
        sections.append(
            '<section class="competition-group" '
            f'data-competition="{html.escape(competition, quote=True)}">'
            f'<div class="competition-heading"><h3>{html.escape(competition)}</h3>'
            f'<span>{len(grouped_cards)} 场</span></div>'
            f'<div class="fixture-list" aria-label="{html.escape(competition)}比赛">{cards_html}</div>'
            '</section>'
        )
    return "".join(sections)


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
    summary = payload["summary"]
    health = payload.get("health") or {}
    system_health = payload.get("system_runtime_health") or health
    quality_health = payload.get("prediction_quality_health") or {}
    health_overall = str(system_health.get("overall_status") or system_health.get("status") or "UNKNOWN")
    health_errors = payload.get("data_errors") or []
    system_display = str(system_health.get("display_status") or health_overall)
    system_css = "alert" if health_overall in {"FAILED", "ALERT"} else "normal" if health_overall == "HEALTHY" else ""
    reason_parts = [
        *(str(value) for value in health_errors),
        *(str(value) for value in system_health.get("failed_steps") or []),
    ]
    reasons = ", ".join(dict.fromkeys(reason_parts))
    system_reason_html = f'<span>{html.escape(reasons)}</span>' if reasons else ""
    system_html = f'<div class="health-alert {system_css}" role="status"><strong>系统运行 · {html.escape(system_display)}</strong>{system_reason_html}</div>'

    quality_status = str(quality_health.get("status") or "UNKNOWN")
    quality_display = str(quality_health.get("display_status") or _QUALITY_STATUS_LABELS.get(quality_status, quality_status))
    exact_score_serving = exact_score_serving_presentation(quality_health)
    if exact_score_serving["state"] == DEGRADED:
        quality_html = f'<div class="health-alert alert" role="status"><strong>预测质量异常</strong><span>{html.escape(_QUALITY_ALERT_COPY)}</span></div>'
    elif exact_score_serving["state"] != "NORMAL":
        quality_html = '<div class="health-alert" role="status"><strong>预测质量状态待确认</strong><span>当前周期质量来源未完成匹配，模型原始比分继续保留。</span></div>'
    else:
        quality_html = f'<div class="health-alert normal" role="status"><strong>预测质量 · {html.escape(quality_display)}</strong></div>'
    health_html = f'<section class="health-stack" aria-label="系统与预测质量状态">{system_html}{quality_html}</section>'
    fixtures = [card for card in payload.get("fixtures") or [] if isinstance(card, dict)]
    grouped_html = _competition_sections_html(fixtures, exact_score_serving=exact_score_serving)
    if not grouped_html:
        grouped_html = '<div class="compact-empty"><strong>今日赛程</strong><span>暂时没有可展示的比赛。</span></div>'
    data_warning = ""
    if summary.get("silent_missing_fixture"):
        data_warning = f'<div class="data-warning">数据完整性提醒：当天 {html.escape(str(summary.get("fixture_count")))} 场，页面仅生成 {html.escape(str(summary.get("card_count")))} 张卡片。</div>'
    historical_html = _historical_results_html(payload.get("completed") or [])
    beta_notice_html = render_closed_beta_notice("health-alert")
    fixture_count = _text(summary.get("fixture_count"), "0")
    competition_count = len({str(card.get("competition") or "赛事待补充") for card in fixtures})
    overview = (
        '<div><h2 id="current-day-title">今日赛程</h2>'
        '<p>按赛事分组 · 今日全部赛事</p></div>'
        f'<div class="summary-count"><strong>{html.escape(fixture_count)}</strong><span>场比赛</span>'
        f'<span class="summary-date">{html.escape(str(payload.get("business_date")))}</span></div>'
        f'<div class="summary-stats"><span>{competition_count} 项赛事</span>'
        f'<span>{int(summary.get("frozen") or 0)} 已预测</span>'
        f'<span>{int(summary.get("insufficient_data") or 0)} 数据不足</span></div>'
    )
    page = f"""<!doctype html>
<html lang="zh-CN">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>今日比赛 · {html.escape(str(payload.get('business_date')))}</title><style>{MODERN_CSS}</style></head>
<body><main class="shell">
<header class="topbar"><div><div class="brand-kicker">PRE-MATCH FOOTBALL INTELLIGENCE</div><h1>今日比赛</h1><div class="date-line">赛前决策视图 · 先看今天，再看赛后</div>
<div class="current-date" aria-label="当前日期"><span class="date-label">北京时间</span><time datetime="{html.escape(str(payload.get('business_date')), quote=True)}"><strong>今天 · {html.escape(str(payload.get('business_date')))}</strong></time><span class="date-context">当前日期</span></div></div>
<div class="refresh-line">数据更新时间<br><strong>{html.escape(_format_updated_at(system_health.get('updated_at') or payload.get('generated_at')))}</strong></div></header>
{health_html}<section class="day-summary" aria-label="今日比赛摘要">{overview}</section>
<nav class="toolbar" aria-label="比赛筛选"><span class="toolbar-label">查看</span>
<button class="filter" type="button" data-filter="ALL" aria-pressed="true">全部</button>
<button class="filter" type="button" data-filter="FROZEN" aria-pressed="false">已预测</button>
<button class="filter" type="button" data-filter="INSUFFICIENT_DATA" aria-pressed="false">数据不足</button>
<button class="filter" type="button" data-filter="RESULT" aria-pressed="false">已完赛</button>
 </nav>
{data_warning}<section id="current-day" class="current-day" aria-labelledby="current-day-title"><div class="section-heading"><h2>当前比赛</h2><p>每张卡片可打开完整赛前详情</p></div><div class="competition-list">{grouped_html}</div></section>
{historical_html}
<footer class="page-footer"><a class="legacy-link" href="../match_workspace/latest.html">Legacy 工作台</a>{beta_notice_html}</footer>
</main><script>
const buttons = Array.from(document.querySelectorAll('[data-filter]'));
const cards = Array.from(document.querySelectorAll('.fixture-card'));
const historicalResults = document.querySelector('#historical-results');
buttons.forEach(button => button.addEventListener('click', () => {{
  const filter = button.dataset.filter;
  buttons.forEach(item => item.setAttribute('aria-pressed', String(item === button)));
  cards.forEach(card => {{
    const match = filter === 'ALL' || card.dataset.status === filter || (filter === 'RESULT' && card.dataset.result === 'yes');
    card.hidden = !match;
    const link = card.closest('.fixture-card-link');
    if (link) link.hidden = !match;
  }});
  if (historicalResults) {{
    historicalResults.hidden = filter !== 'ALL' && filter !== 'RESULT';
    if (filter === 'RESULT') historicalResults.open = true;
  }}
}}));
</script></body></html>"""
    result_count = int(summary.get("completed_count") or 0)
    page = page.replace(
        'data-filter="RESULT" aria-pressed="false"',
        f'data-filter="RESULT" data-result-count="{result_count}" aria-pressed="false"',
        1,
    )
    page = page.replace('>已完赛</button>', f'>已完赛 ({result_count})</button>', 1)
    page_version = "|".join(
        str(payload.get(key) or "") for key in ("business_date", "generated_at")
    )
    refresh_script = STATIC_REFRESH_SCRIPT.replace(
        "__PAGE_VERSION__", json.dumps(page_version, ensure_ascii=False)
    )
    return page.replace("</body>", refresh_script + "</body>", 1)


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
    jobs = [row for row in (jobs_payload.get("jobs") or []) if isinstance(row, dict)]
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
    job_lookup = _job_index(jobs, business_date)
    cards: list[dict[str, Any]] = []
    for fixture in fixtures:
        projected = _fixture_projection(fixture)
        match_id = projected["match_id"]
        job = job_lookup.get(f"match_id:{match_id}") or job_lookup.get(f"job_id:BASE-{business_date}-{match_id}")
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
