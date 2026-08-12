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
    "FROZEN": "预测已冻结",
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


def _prediction_projection(record: dict[str, Any]) -> dict[str, Any]:
    probabilities = record.get("fusion_1X2") or record.get("probabilities") or {}
    btts = record.get("btts") or {}
    top_scores = record.get("score_distribution") or record.get("top_scores") or []
    score_top3 = record.get("score_top3")
    if not score_top3 and isinstance(top_scores, list):
        score_top3 = [row.get("score") for row in top_scores[:3] if isinstance(row, dict)]
    return {
        "product_role": record.get("product_role"),
        "model_family": record.get("model_family"),
        "release_version": record.get("release_version"),
        "lambda_home": record.get("lambda_home"),
        "lambda_away": record.get("lambda_away"),
        "probabilities": probabilities if isinstance(probabilities, dict) else {},
        "btts": btts if isinstance(btts, dict) else {},
        "totals": record.get("totals") if isinstance(record.get("totals"), list) else [],
        "unique_score": record.get("unique_score") or record.get("score_top1"),
        "score_top3": score_top3 or [],
        "market_intelligence_quality": record.get("market_intelligence_quality"),
        "market_data_providers": record.get("market_data_providers") or [],
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
    card.update({
        "status": status,
        "status_label": STATUS_LABELS.get(status, status),
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
        "pilot_excluded": bool(prediction_id and prediction_id in exclusions),
        "formal_prospective": bool(prediction_id and prediction_id in formal_samples),
        "evaluation": {
            "kind": "formal" if prediction_id in formal_samples else "pilot_excluded" if prediction_id in exploratory_samples else None,
            "metrics": sample.get("metrics") if isinstance(sample, dict) else {},
        } if sample else None,
    })
    return card


def _metric_value(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:.4f}"
    return _text(value)


def _esc(value: Any) -> str:
    return html.escape(_text(value))


def _probability(value: Any) -> str:
    number = _number(value)
    return f"{number:.1%}" if number is not None else "—"


def _field(label: str, value: Any, *, css: str = "") -> str:
    return f'<div class="metric {css}"><span>{html.escape(label)}</span><strong>{html.escape(_text(value))}</strong></div>'


def _prediction_html(prediction: dict[str, Any]) -> str:
    probabilities = prediction.get("probabilities") or {}
    btts = prediction.get("btts") or {}
    score_top3 = prediction.get("score_top3") or []
    totals = prediction.get("totals") or []
    total_text = "、".join(
        f"{row.get('goals')}（{_probability(row.get('probability'))}）"
        for row in totals[:3] if isinstance(row, dict)
    ) or "—"
    market_quality = prediction.get("market_intelligence_quality")
    market_note = "市场情报有限" if market_quality == "LIMITED" else None
    market_fields = [
        _field("市场情报质量", market_quality),
        _field("数据等级", prediction.get("data_grade")),
        _field("BASE输入质量", prediction.get("base_input_quality")),
        _field("冻结时距开赛（分钟）", prediction.get("minutes_to_kickoff_at_freeze")),
    ]
    if prediction.get("market_bookmakers"):
        market_fields.append(_field("实际公司", "、".join(map(str, prediction["market_bookmakers"]))))
    if prediction.get("market_data_providers"):
        market_fields.append(_field("数据提供方", "、".join(map(str, prediction["market_data_providers"]))))
    if prediction.get("market_families"):
        market_fields.append(_field("市场类别", "、".join(map(str, prediction["market_families"]))))
    return (
        '<section class="prediction-block"><div class="block-title">BASE 概率预测</div>'
        '<div class="model-line">FUSION_BASELINE_V0 · 当前 Champion 融合基线</div>'
        '<div class="data-grid">'
        + _field("λ 主队", prediction.get("lambda_home"))
        + _field("λ 客队", prediction.get("lambda_away"))
        + _field("主胜概率", _probability(probabilities.get("home")))
        + _field("平局概率", _probability(probabilities.get("draw")))
        + _field("客胜概率", _probability(probabilities.get("away")))
        + _field("BTTS Yes", _probability(btts.get("yes")))
        + _field("BTTS No", _probability(btts.get("no")))
        + _field("唯一比分", prediction.get("unique_score"))
        + _field("Top3 比分", "、".join(map(str, score_top3)) or "—", css="wide")
        + _field("总进球概率", total_text, css="wide")
        + "</div><div class=\"data-grid quality-grid\">"
        + "".join(market_fields)
        + "</div>"
        + (f'<p class="limited-note">{html.escape(market_note)}</p>' if market_note else "")
        + "</section>"
    )


def _result_html(card: dict[str, Any]) -> str:
    result = card.get("result") or {}
    score = result.get("score_90m")
    if not score:
        return '<div class="result-line pending-result">等待赛果</div>'
    sample = card.get("evaluation")
    if sample and sample.get("kind") == "formal":
        label = "已进入正式评估样本"
    elif card.get("pilot_excluded"):
        label = "试运行样本 · 不计入正式评估"
    else:
        label = "已取得验证赛果"
    return f'<div class="result-line"><strong>90分钟赛果：{html.escape(str(score))}</strong><span>{html.escape(label)}</span></div>'


def _evaluation_html(evaluation: dict[str, Any] | None) -> str:
    if not evaluation:
        return ""
    metrics = evaluation.get("metrics") or {}
    labels = {
        "top1_accuracy": "1X2 命中",
        "exact_score_top1_hit": "Exact Score Top1",
        "exact_score_top3_hit": "Exact Score Top3",
        "brier_1x2": "1X2 Brier",
        "log_loss_1x2": "1X2 LogLoss",
        "1x2_brier": "1X2 Brier",
        "1x2_log_loss": "1X2 LogLoss",
    }
    fields = []
    for key, label in labels.items():
        if key in metrics:
            fields.append(_field(label, _metric_value(metrics[key])))
    if not fields:
        return ""
    prefix = "正式评估" if evaluation.get("kind") == "formal" else "试运行评价（不计入正式样本）"
    return f'<section class="evaluation-block"><div class="block-title">{html.escape(prefix)}</div><div class="data-grid">{"".join(fields)}</div></section>'


def _card_html(card: dict[str, Any]) -> str:
    status = str(card.get("status") or "PENDING")
    reason = ""
    if card.get("reason_code"):
        reason = (
            f'<div class="reason"><strong>{html.escape(str(card.get("reason_text") or card["reason_code"]))}</strong>'
            f'<code>{html.escape(str(card["reason_code"]))}</code></div>'
        )
    prediction = _prediction_html(card["prediction"]) if card.get("prediction") else ""
    return (
        f'<article class="fixture-card status-{html.escape(status.lower())}" data-status="{html.escape(status)}" '
        f'data-result="{"yes" if card.get("result") else "no"}">'
        '<div class="fixture-head">'
        f'<div><div class="fixture-kicker">{_esc(card.get("competition"))} · {_esc(card.get("match_num"))}</div>'
        f'<h2>{_esc(card.get("home"))} <span>vs</span> {_esc(card.get("away"))}</h2>'
        f'<div class="kickoff">开球：{_esc(card.get("kickoff"))}</div></div>'
        f'<span class="status-badge">{html.escape(str(card.get("status_label") or status))}</span></div>'
        + reason + prediction + _result_html(card) + _evaluation_html(card.get("evaluation"))
        + "</article>"
    )


CSS = r"""
:root { --ink:#1f2933; --muted:#64717d; --line:#d9e0e5; --paper:#f6f8f9; --panel:#ffffff; --navy:#17324d; --teal:#1d8175; --amber:#c77a18; --red:#b84c4c; --blue:#3475a8; }
* { box-sizing:border-box; }
body { margin:0; background:var(--paper); color:var(--ink); font:14px/1.6 "Segoe UI","Microsoft YaHei",sans-serif; }
a { color:var(--teal); }
.page { max-width:1240px; margin:0 auto; padding:28px 20px 54px; }
.hero { background:var(--navy); color:#fff; padding:30px 32px; border-radius:14px; box-shadow:0 10px 28px rgba(23,50,77,.14); }
.eyebrow { color:#9bd6cd; letter-spacing:.15em; font-size:11px; font-weight:700; }
h1 { margin:7px 0 3px; font-size:clamp(28px,4vw,42px); letter-spacing:-.03em; }
.hero p { margin:0; color:#d2e0eb; }
.health { margin-top:22px; display:flex; flex-wrap:wrap; gap:10px; align-items:center; }
.health-badge, .status-badge { display:inline-flex; padding:4px 10px; border-radius:999px; font-weight:700; font-size:12px; }
.health-normal { background:#d9f2e8; color:#17614f; }
.health-degraded { background:#fff0cf; color:#825114; }
.health-failed { background:#f9dddd; color:#8e3333; }
.health-unknown { background:#e7edf1; color:#4e5b65; }
.summary-grid { display:grid; grid-template-columns:repeat(8,minmax(0,1fr)); gap:10px; margin:18px 0; }
.summary-card { background:var(--panel); border:1px solid var(--line); padding:15px 14px; min-height:84px; }
.summary-card strong { display:block; font-size:25px; color:var(--navy); line-height:1.1; }
.summary-card span { color:var(--muted); font-size:12px; }
.summary-card.accent { border-top:3px solid var(--teal); }
.filters { display:flex; gap:8px; flex-wrap:wrap; align-items:center; margin:22px 0 13px; }
.filter { cursor:pointer; border:1px solid var(--line); background:#fff; color:var(--ink); padding:7px 13px; border-radius:7px; }
.filter[aria-pressed="true"] { background:var(--navy); color:#fff; border-color:var(--navy); }
.fixture-list { display:grid; gap:13px; }
.fixture-card { background:var(--panel); border:1px solid var(--line); border-left:5px solid var(--blue); padding:20px; }
.status-frozen { border-left-color:var(--teal); }
.status-insufficient_data { border-left-color:var(--amber); }
.status-prediction_failed, .status-missed_prematch_window { border-left-color:var(--red); }
.status-pending { border-left-color:#9aa7b0; }
.fixture-head { display:flex; justify-content:space-between; gap:18px; align-items:flex-start; }
.fixture-kicker, .block-title { color:var(--muted); text-transform:uppercase; letter-spacing:.08em; font-size:11px; font-weight:700; }
h2 { margin:4px 0 2px; color:var(--navy); font-size:23px; letter-spacing:-.02em; }
h2 span { color:#9aa7b0; font-size:14px; font-weight:400; }
.kickoff { color:var(--muted); }
.status-badge { background:#e7edf1; color:#43515c; white-space:nowrap; }
.status-frozen .status-badge { background:#d9f2e8; color:#17614f; }
.status-insufficient_data .status-badge { background:#fff0cf; color:#825114; }
.status-prediction_failed .status-badge, .status-missed_prematch_window .status-badge { background:#f9dddd; color:#8e3333; }
.reason { display:flex; gap:9px; flex-wrap:wrap; align-items:center; margin:14px 0 0; padding:10px 12px; background:#fff8e9; border:1px solid #f0dba8; color:#76501c; }
.reason code { color:#926527; font-size:12px; }
.prediction-block, .evaluation-block { border-top:1px solid var(--line); margin-top:18px; padding-top:16px; }
.model-line { color:var(--teal); font-weight:700; margin:3px 0 12px; }
.data-grid { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:8px; margin-top:10px; }
.quality-grid { margin-top:12px; }
.metric { border:1px solid #e5eaee; padding:9px 10px; background:#fbfcfc; min-width:0; }
.metric span { display:block; color:var(--muted); font-size:11px; }
.metric strong { display:block; margin-top:2px; color:var(--ink); overflow-wrap:anywhere; }
.metric.wide { grid-column:span 2; }
.limited-note { color:#8a5a16; background:#fff8e9; padding:7px 9px; margin:10px 0 0; }
.result-line { display:flex; align-items:center; gap:15px; flex-wrap:wrap; margin-top:15px; padding:11px 13px; background:#eef8f5; color:#17614f; }
.pending-result { background:#f2f5f7; color:var(--muted); }
.result-line span { font-size:12px; }
.page-error { border:1px solid #efc7c7; background:#fff1f1; color:#8e3333; padding:12px 14px; margin:16px 0; }
.empty { padding:32px; text-align:center; color:var(--muted); border:1px dashed var(--line); }
@media (max-width:900px) { .summary-grid { grid-template-columns:repeat(4,minmax(0,1fr)); } .data-grid { grid-template-columns:repeat(2,minmax(0,1fr)); } }
@media (max-width:520px) { .page { padding:14px 10px 36px; } .hero { padding:22px 18px; } .summary-grid { grid-template-columns:repeat(2,minmax(0,1fr)); } .fixture-head { display:block; } .status-badge { margin-top:12px; } .data-grid { grid-template-columns:1fr; } .metric.wide { grid-column:span 1; } h2 { font-size:20px; } }
"""


def render_dashboard(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    health = payload.get("health") or {}
    health_status = str(health.get("display_status") or "待更新")
    health_class = str(health.get("css_class") or "unknown")
    health_errors = payload.get("data_errors") or []
    summary_cards = [
        ("今日比赛", summary.get("fixture_count"), ""),
        ("预测已冻结", summary.get("frozen"), "accent"),
        ("等待预测", summary.get("pending"), ""),
        ("数据不足", summary.get("insufficient_data"), ""),
        ("预测失败", summary.get("prediction_failed"), ""),
        ("错过窗口", summary.get("missed"), ""),
        ("已验证赛果", summary.get("verified_results"), ""),
        ("正式 Prospective Samples", summary.get("formal_prospective_total"), "accent"),
        ("本日新增正式样本", summary.get("samples_added_today"), ""),
        ("Pilot excluded", summary.get("pilot_excluded_count"), ""),
    ]
    summary_html = "".join(
        f'<div class="summary-card {css}"><strong>{html.escape(_text(value, "0"))}</strong><span>{html.escape(label)}</span></div>'
        for label, value, css in summary_cards
    )
    cards_html = "".join(_card_html(card) for card in payload.get("fixtures") or [])
    cards_html = cards_html or '<div class="empty">该业务日没有可展示的 Prediction Universe 赛事。</div>'
    error_html = (
        '<div class="page-error"><strong>数据完整性提示：</strong>'
        + html.escape("、".join(map(str, health_errors)))
        + "</div>"
        if health_errors else ""
    )
    return f"""<!doctype html>
<html lang="zh-CN">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Prediction Day · {html.escape(str(payload.get('business_date')))}</title><style>{CSS}</style></head>
<body><main class="page">
<header class="hero"><div class="eyebrow">PRE-MATCH FOOTBALL INTELLIGENCE</div>
<h1>Prediction Day · {html.escape(str(payload.get('business_date')))}</h1>
<p>完整 Prediction Universe · 所有比赛保留 · 概率预测与赛果状态</p>
<div class="health"><span class="health-badge health-{html.escape(health_class)}">系统状态：{html.escape(health_status)}</span>
<span>系统更新时间：{html.escape(_text(health.get('updated_at') or payload.get('generated_at')))}</span>
<span>页面生成：{html.escape(_text(payload.get('generated_at')))}</span></div></header>
{error_html}<section class="summary-grid">{summary_html}</section>
<section class="filters" aria-label="比赛筛选"><span>显示：</span>
<button class="filter" type="button" data-filter="ALL" aria-pressed="true">全部</button>
<button class="filter" type="button" data-filter="FROZEN" aria-pressed="false">已预测</button>
<button class="filter" type="button" data-filter="INSUFFICIENT_DATA" aria-pressed="false">数据不足</button>
<button class="filter" type="button" data-filter="RESULT" aria-pressed="false">已完赛</button>
<a href="../match_workspace/latest.html">打开旧比赛工作台</a></section>
<section id="fixture-list" class="fixture-list" aria-label="Prediction Universe 比赛列表">{cards_html}</section>
<footer style="margin-top:26px;color:#64717d;font-size:12px">Universe {html.escape(str(summary.get('fixture_count', 0)))} 场 · 页面卡片 {html.escape(str(summary.get('card_count', 0)))} 张 · silent_missing_fixture = {html.escape(str(summary.get('silent_missing_fixture', 0)))} · 今日新增正式样本 {html.escape(str(summary.get('samples_added_today', 0)))} · pilot excluded {html.escape(str(summary.get('pilot_excluded_count', 0)))}</footer>
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
        cards.append(_card(fixture, job, record, result_index, exclusions, formal_samples, exploratory_samples))
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
