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


BASE_DIR = Path(__file__).resolve().parents[1]
UNIVERSE_ROOT = BASE_DIR / "data" / "prediction_universe"
JOBS_ROOT = BASE_DIR / "data" / "base_prediction_jobs"
PREDICTION_ROOT = BASE_DIR / "data" / "model_governance" / "predictions"
EXCLUSION_ROOT = BASE_DIR / "data" / "model_governance" / "prediction_exclusions"
RESULT_ROOT = BASE_DIR / "data" / "postmatch_automation" / "results"
PROSPECTIVE_ROOT = BASE_DIR / "data" / "prospective"
RUNTIME_PATH = BASE_DIR / "data" / "product_runtime" / "latest_cycle.json"
DASHBOARD_ROOT = BASE_DIR / "data" / "prediction_dashboard"
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
    "IDENTITY_UNRESOLVED": "比赛身份无法可靠匹配",
    "PREDICTION_FAILED": "模型运行失败",
    "MISSED_PREMATCH_WINDOW": "已错过合法赛前预测窗口",
    "BASE_JOB_MISSING": "基础预测任务尚未生成",
    "PREDICTION_ARTIFACT_MISSING": "预测任务已冻结但正式记录缺失",
}


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


def _card(
    fixture: dict[str, Any],
    job: dict[str, Any] | None,
    record: dict[str, Any] | None,
    result_index: dict[str, dict[str, Any]],
    exclusions: dict[str, dict[str, Any]],
    formal_samples: dict[str, dict[str, Any]],
    exploratory_samples: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    card = _fixture_projection(fixture)
    status = str((job or {}).get("status") or "PENDING")
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
  --bg: #0b1118;
  --surface: #121b25;
  --surface-2: #172331;
  --line: #263646;
  --text: #f3f7fa;
  --muted: #91a2b3;
  --quiet: #6f8192;
  --accent: #43d3a5;
  --accent-soft: rgba(67, 211, 165, .13);
  --warning: #f0b86a;
  --warning-soft: rgba(240, 184, 106, .14);
  --danger: #f17b85;
  --danger-soft: rgba(241, 123, 133, .14);
  --blue: #79a8ff;
}
* { box-sizing: border-box; }
html { background: var(--bg); }
body {
  margin: 0;
  color: var(--text);
  background:
    radial-gradient(circle at 12% -10%, rgba(67, 211, 165, .11), transparent 32rem),
    var(--bg);
  font: 14px/1.5 "Segoe UI", "Microsoft YaHei", sans-serif;
}
a { color: var(--accent); text-decoration: none; }
a:hover { text-decoration: underline; }
button { font: inherit; }
.shell { max-width: 1440px; margin: 0 auto; padding: 28px 28px 52px; }
.topbar { display: flex; justify-content: space-between; gap: 24px; align-items: flex-start; }
.brand-kicker { color: var(--accent); font-size: 11px; font-weight: 700; letter-spacing: .18em; text-transform: uppercase; }
h1 { margin: 8px 0 4px; font-size: clamp(32px, 5vw, 54px); line-height: 1.02; letter-spacing: -.045em; }
.date-line { color: var(--muted); font-size: 15px; }
.refresh-line { color: var(--quiet); font-size: 12px; text-align: right; }
.health-alert { display: flex; flex-wrap: wrap; gap: 8px 14px; align-items: center; margin: 20px 0 0; padding: 11px 14px; border: 1px solid rgba(240, 184, 106, .35); background: var(--warning-soft); color: #f7d49d; }
.health-alert.alert { border-color: rgba(241, 123, 133, .4); background: var(--danger-soft); color: #ffc1c6; }
.health-alert strong { color: inherit; }
.day-summary { display: flex; flex-wrap: wrap; align-items: baseline; gap: 8px 12px; margin: 28px 0 20px; color: var(--muted); }
.day-summary strong { color: var(--accent); font-size: 26px; line-height: 1; letter-spacing: -.04em; }
.day-summary .summary-date { color: var(--quiet); font-size: 12px; }
.toolbar { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; margin: 24px 0 15px; }
.toolbar-label { margin-right: 4px; color: var(--muted); font-size: 12px; }
.filter { border: 1px solid var(--line); border-radius: 999px; padding: 7px 13px; color: var(--muted); background: transparent; cursor: pointer; }
.filter:hover, .filter[aria-pressed="true"] { border-color: var(--accent); color: var(--bg); background: var(--accent); }
.page-footer { margin-top: 28px; padding-top: 14px; border-top: 1px solid var(--line); }
.legacy-link { color: var(--quiet); font-size: 11px; }
.fixture-list { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; }
.fixture-card { min-width: 0; overflow: hidden; border: 1px solid var(--line); border-left: 3px solid var(--quiet); background: var(--surface); }
.fixture-card.status-frozen { border-left-color: var(--accent); }
.fixture-card.status-insufficient_data { border-left-color: var(--warning); }
.fixture-card.status-prediction_failed, .fixture-card.status-missed_prematch_window { border-left-color: var(--danger); }
.fixture-card.status-pending { border-left-color: var(--blue); }
.fixture-main { padding: 18px 19px 15px; }
.fixture-meta { display: flex; justify-content: space-between; gap: 12px; align-items: center; color: var(--muted); font-size: 12px; }
.fixture-meta .competition { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.match-number { color: var(--quiet); white-space: nowrap; }
.teams { margin: 12px 0 5px; font-size: clamp(20px, 2.3vw, 28px); font-weight: 650; line-height: 1.18; letter-spacing: -.035em; overflow-wrap: anywhere; }
.teams .versus { display: inline-block; margin: 0 6px; color: var(--quiet); font-size: .48em; font-weight: 500; letter-spacing: 0; vertical-align: middle; }
.kickoff { color: var(--muted); font-size: 12px; }
.status-badge { display: inline-flex; align-items: center; border-radius: 999px; padding: 4px 9px; color: var(--muted); background: var(--surface-2); font-size: 11px; font-weight: 700; white-space: nowrap; }
.detail-link { color: var(--muted); font-size: 11px; text-decoration: none; white-space: nowrap; }
.detail-link:hover { color: var(--accent); }
.status-frozen .status-badge { color: var(--accent); background: var(--accent-soft); }
.fixture-card.prediction-pilot { border-left-color: var(--warning); }
.prediction-pilot .status-badge { color: var(--warning); background: var(--warning-soft); }
.prediction-pilot .score-focus strong { color: var(--warning); }
.prediction-pilot .signal.accent { border-color: rgba(240, 184, 106, .35); color: var(--warning); background: var(--warning-soft); }
.status-insufficient_data .status-badge { color: var(--warning); background: var(--warning-soft); }
.status-prediction_failed .status-badge, .status-missed_prematch_window .status-badge { color: var(--danger); background: var(--danger-soft); }
.reason { display: flex; flex-wrap: wrap; gap: 5px 10px; align-items: baseline; margin-top: 14px; padding: 10px 12px; border: 1px solid rgba(240, 184, 106, .25); background: var(--warning-soft); color: #f6d29a; }
.reason strong { font-size: 13px; }
.pilot-note { display: flex; flex-wrap: wrap; gap: 6px 10px; align-items: baseline; margin-top: 12px; color: var(--warning); font-size: 12px; }
.pilot-note span { color: var(--muted); font-size: 11px; }
.prediction-panel { margin-top: 16px; padding: 15px 0 0; border-top: 1px solid var(--line); }
.prediction-topline { display: flex; justify-content: space-between; gap: 15px; align-items: flex-end; }
.prediction-label { color: var(--muted); font-size: 11px; letter-spacing: .08em; text-transform: uppercase; }
.score-focus { display: flex; flex-wrap: wrap; align-items: baseline; justify-content: flex-start; gap: 7px; }
.score-focus strong { color: var(--accent); font-size: 36px; line-height: .95; letter-spacing: -.06em; }
.score-focus .neighbors { color: var(--muted); font-size: 12px; }
.signal-row { display: flex; flex-wrap: wrap; gap: 7px; margin-top: 15px; }
.signal { display: inline-flex; align-items: center; min-height: 27px; padding: 4px 8px; border: 1px solid var(--line); color: var(--muted); background: var(--surface-2); font-size: 12px; }
.signal.accent { border-color: rgba(67, 211, 165, .35); color: var(--accent); background: var(--accent-soft); }
.market-strip { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 12px; }
.market-item { min-width: 0; padding: 8px 10px; border: 1px solid var(--line); color: var(--muted); background: rgba(11, 17, 24, .48); font-size: 12px; }
.market-item strong { color: var(--text); font-weight: 600; }
.market-item small { display: block; margin-top: 2px; color: var(--quiet); }
.market-item .movement { color: var(--warning); }
.result-line { display: flex; flex-wrap: wrap; gap: 8px 13px; align-items: baseline; margin: 16px -1px -1px; padding: 11px 12px; border: 1px solid rgba(67, 211, 165, .24); background: var(--accent-soft); color: var(--accent); }
.empty { grid-column: 1 / -1; padding: 44px 20px; border: 1px dashed var(--line); color: var(--muted); text-align: center; }
.data-warning { margin: 18px 0 0; padding: 10px 13px; border: 1px solid rgba(241, 123, 133, .32); background: var(--danger-soft); color: #ffc1c6; font-size: 12px; }
@media (max-width: 880px) { .fixture-list { grid-template-columns: 1fr; } }
@media (max-width: 560px) { .shell { padding: 20px 12px 38px; } .topbar { display: block; } .refresh-line { margin-top: 10px; text-align: left; } .day-summary { margin-top: 22px; } .fixture-main { padding: 15px 14px 13px; } .fixture-meta { align-items: flex-start; } .teams { font-size: 22px; } .prediction-topline { display: block; } .score-focus { margin-top: 11px; } }
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


def _score_label(value: Any) -> str:
    return str(value or "").replace("-", "–")


def _signal(label: str, value: Any, css: str = "") -> str:
    if value in (None, "", []):
        return ""
    return f'<span class="signal {css}">{html.escape(label)} · {html.escape(_text(value))}</span>'


def _modern_prediction_html(prediction: dict[str, Any], *, pilot_excluded: bool = False) -> str:
    primary = prediction.get("primary_score") or prediction.get("unique_score")
    neighbors = prediction.get("neighbor_scores") or []
    market = prediction.get("market_summary") or {}
    signal_html = "".join([
        _signal("1X2", prediction.get("one_x_two_direction"), "accent"),
        _signal("比分分布", prediction.get("score_concentration")),
    ])
    market_html = ""
    asian = market.get("asian_handicap")
    total = market.get("total_line")
    if asian or total:
        items = []
        if asian:
            movement = f'<small class="movement">{html.escape(str(asian.get("movement")))}</small>' if asian.get("movement") else ""
            items.append(f'<div class="market-item"><strong>AH · 主 {html.escape(str(asian.get("line")))}</strong>{movement}</div>')
        if total:
            direction = total.get("direction") or market.get("total_direction")
            direction_text = f" · {html.escape(str(direction))}" if direction else ""
            movement = f'<small class="movement">{html.escape(str(total.get("movement")))}</small>' if total.get("movement") else ""
            items.append(f'<div class="market-item"><strong>O/U · {html.escape(str(total.get("line")))}{direction_text}</strong>{movement}</div>')
        market_html = f'<div class="market-strip">{"".join(items)}</div>'
    neighbor_text = " · ".join(_score_label(score) for score in neighbors)
    pilot_note = '<div class="pilot-note"><strong>试运行预测</strong><span>不纳入正式验证</span></div>' if pilot_excluded else ""
    return (
        '<section class="prediction-panel">'
        '<div class="prediction-topline">'
        '<div><div class="prediction-label">系统首推比分</div>'
        '<div class="score-focus">'
        f'<strong>{html.escape(_score_label(primary) if primary else "—")}</strong>'
        f'<span class="neighbors">{html.escape(neighbor_text) if neighbor_text else ""}</span></div></div></div>'
        f'{pilot_note}'
        f'<div class="signal-row">{signal_html}</div>'
        f'{market_html}'
        '</section>'
    )


def _modern_result_html(card: dict[str, Any]) -> str:
    result = card.get("result") or {}
    score = result.get("score_90m")
    if not score:
        return ""
    return f'<div class="result-line"><strong>90分钟赛果 · {html.escape(str(score))}</strong></div>'


def _modern_card_html(card: dict[str, Any]) -> str:
    status = str(card.get("status") or "PENDING")
    match_id = str(card.get("match_id") or "")
    pilot_excluded = bool(card.get("pilot_excluded") and card.get("prediction"))
    prediction_kind = "pilot" if pilot_excluded else "formal" if card.get("prediction") else "none"
    reason_html = ""
    if card.get("reason_code"):
        reason_html = f'<div class="reason"><strong>{html.escape(str(card.get("reason_text") or "数据暂不可用"))}</strong></div>'
    prediction_html = _modern_prediction_html(card["prediction"], pilot_excluded=pilot_excluded) if card.get("prediction") else ""
    return (
        f'<article class="fixture-card status-{html.escape(status.lower())} prediction-{prediction_kind}" data-status="{html.escape(status)}" data-result="{"yes" if card.get("result") else "no"}" data-prediction-kind="{prediction_kind}">'
        '<div class="fixture-main">'
        '<div class="fixture-meta">'
        f'<span class="competition">{_esc(card.get("competition"))}</span>'
        f'<span class="match-number">{_esc(card.get("match_num"))}</span>'
        '</div>'
        f'<div class="teams">{_esc(card.get("home"))}<span class="versus">vs</span>{_esc(card.get("away"))}</div>'
        f'<div class="fixture-meta"><span class="kickoff">开球 · {html.escape(_format_kickoff(card.get("kickoff")))}</span>'
        f'<span><span class="status-badge">{html.escape(str(card.get("status_label") or status))}</span>'
        f'<a class="detail-link" href="../matches/{html.escape(match_id)}/">查看详情</a></span></div>'
        f'{reason_html}{prediction_html}{_modern_result_html(card)}'
        '</div>'
        '</article>'
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
    summary = payload["summary"]
    health = payload.get("health") or {}
    health_overall = str(health.get("overall_status") or "UNKNOWN")
    health_errors = payload.get("data_errors") or []
    health_html = ""
    if health_overall != "HEALTHY" or health_errors:
        css = "alert" if health_overall in {"FAILED", "ALERT"} else ""
        reason_parts = [
            *(str(value) for value in health_errors),
            *(str(value) for value in health.get("failed_steps") or []),
        ]
        reasons = ", ".join(dict.fromkeys(reason_parts)) or "待检查"
        health_html = f'<div class="health-alert {css}"><strong>系统状态 · {html.escape(health_overall)}</strong><span>{html.escape(reasons)}</span></div>'
    overview = (
        f'<strong>{html.escape(_text(summary.get("fixture_count"), "0"))}</strong>'
        '<span>场比赛 · 今日全部赛程</span>'
        f'<span class="summary-date">{html.escape(str(payload.get("business_date")))}</span>'
    )
    cards_html = "".join(_modern_card_html(card) for card in payload.get("fixtures") or [])
    if not cards_html:
        cards_html = '<div class="empty">今天没有可展示的比赛。</div>'
    data_warning = ""
    if summary.get("silent_missing_fixture"):
        data_warning = f'<div class="data-warning">数据完整性提醒：当天 {html.escape(str(summary.get("fixture_count")))} 场，页面仅生成 {html.escape(str(summary.get("card_count")))} 张卡片。</div>'
    page = f"""<!doctype html>
<html lang="zh-CN">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>今日比赛 · {html.escape(str(payload.get('business_date')))}</title><style>{MODERN_CSS}</style></head>
<body><main class="shell">
<header class="topbar"><div><div class="brand-kicker">PRE-MATCH FOOTBALL INTELLIGENCE</div><h1>今日比赛</h1><div class="date-line">{html.escape(str(payload.get('business_date')))} · 今日全部赛事</div></div>
<div class="refresh-line">数据更新时间<br><strong>{html.escape(_format_updated_at(health.get('updated_at') or payload.get('generated_at')))}</strong></div></header>
{health_html}<section class="day-summary" aria-label="今日比赛摘要">{overview}</section>
<nav class="toolbar" aria-label="比赛筛选"><span class="toolbar-label">查看</span>
<button class="filter" type="button" data-filter="ALL" aria-pressed="true">全部</button>
<button class="filter" type="button" data-filter="FROZEN" aria-pressed="false">已预测</button>
<button class="filter" type="button" data-filter="INSUFFICIENT_DATA" aria-pressed="false">数据不足</button>
<button class="filter" type="button" data-filter="RESULT" aria-pressed="false">已完赛</button>
 </nav>
{data_warning}<section id="fixture-list" class="fixture-list" aria-label="今日比赛列表">{cards_html}</section>
<footer class="page-footer"><a class="legacy-link" href="../match_workspace/latest.html">Legacy 工作台</a></footer>
</main><script>
const buttons = Array.from(document.querySelectorAll('[data-filter]'));
const cards = Array.from(document.querySelectorAll('.fixture-card'));
buttons.forEach(button => button.addEventListener('click', () => {{
  const filter = button.dataset.filter;
  buttons.forEach(item => item.setAttribute('aria-pressed', String(item === button)));
  cards.forEach(card => {{
    const match = filter === 'ALL' || card.dataset.status === filter || (filter === 'RESULT' && card.dataset.result === 'yes');
    card.hidden = !match;
  }});
}}));
</script></body></html>"""
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
    job_lookup = _job_index(jobs, business_date)
    cards: list[dict[str, Any]] = []
    for fixture in fixtures:
        projected = _fixture_projection(fixture)
        match_id = projected["match_id"]
        job = job_lookup.get(f"match_id:{match_id}") or job_lookup.get(f"job_id:BASE-{business_date}-{match_id}")
        record = records.get(str((job or {}).get("prediction_id") or "")) if job else None
        cards.append(_card(
            fixture,
            job,
            record,
            result_index,
            exclusions,
            formal_samples,
            exploratory_samples,
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
    payload = {
        "schema_version": "1.0",
        "generated_at": (now or datetime.now(SHANGHAI)).isoformat(),
        "business_date": business_date,
        "health": {
            "overall_status": health_overall,
            "display_status": display_status,
            "css_class": css_class,
            "updated_at": runtime.get("finished_at") or runtime.get("started_at"),
            "failed_steps": failed_steps,
        },
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
            "formal_prospective_total": int(formal_total or 0),
            "samples_added_today": int(samples_added or 0),
            "pilot_excluded_count": int(excluded_count or 0),
            "silent_missing_fixture": max(0, int(universe.get("fixture_count") or len(fixtures)) - len(cards)),
        },
        "data_errors": errors,
        "fixtures": cards,
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
