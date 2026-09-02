#!/usr/bin/env python3
"""Render the shared static match-detail page from an analysis contract."""

from __future__ import annotations

import argparse
import html
import json
import math
from pathlib import Path
from typing import Any, Iterable

try:  # Support both ``python scripts/match_detail.py`` and package imports.
    from .match_analysis import MATCH_ANALYSIS_ROOT, build_match_contracts, match_url
except ImportError:  # pragma: no cover - exercised by the direct CLI path.
    from match_analysis import MATCH_ANALYSIS_ROOT, build_match_contracts, match_url

try:  # Keep dashboard and match-detail exact-score semantics identical.
    from .exact_score_serving_policy import DEGRADED, exact_score_serving_presentation
except ImportError:  # pragma: no cover - exercised by the direct CLI path.
    from exact_score_serving_policy import DEGRADED, exact_score_serving_presentation

try:
    from .closed_beta_copy import render_closed_beta_notice
except ImportError:  # pragma: no cover - exercised by the direct CLI path.
    from closed_beta_copy import render_closed_beta_notice


def _esc(value: Any, fallback: str = "") -> str:
    if value is None or value == "":
        return html.escape(fallback)
    return html.escape(str(value))


def _display_score(value: Any) -> str:
    return _esc(str(value).replace("-", "–")) if value else ""


def _percent(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return _esc(value)
    if not math.isfinite(number):
        return ""
    return f"{number * 100:.1f}%"


def _probability(value: Any) -> str:
    return _percent(value) if value is not None else ""


def _decimal(value: Any, fallback: str = "—") -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return fallback
    return f"{number:.2f}" if math.isfinite(number) else fallback


def _format_kickoff(value: Any) -> str:
    text = str(value or "").strip().replace("T", " ")
    if "+08:00" in text:
        text = text.replace("+08:00", "")
    return text[:16] if text else "时间待补充"


def _dict_items(payload: Any) -> list[tuple[str, Any]]:
    return list(payload.items()) if isinstance(payload, dict) else []


def _status_class(contract: dict[str, Any]) -> str:
    status = str((contract.get("status") or {}).get("code") or "PENDING").lower()
    if (contract.get("governance") or {}).get("pilot_excluded"):
        return "pilot"
    return {
        "frozen": "recorded",
        "insufficient_data": "insufficient",
        "prediction_failed": "failed",
        "missed_prematch_window": "missed",
    }.get(status, status)


_USER_STATUS_LABELS = {
    "FROZEN": "已预测",
    "PENDING": "预测尚未记录",
    "INSUFFICIENT_DATA": "数据不足",
    "PREDICTION_FAILED": "预测失败",
    "MISSED_PREMATCH_WINDOW": "错过赛前窗口",
}

_MISSING_LABELS = {
    "MISSING_RECENT_FORM": "近期比赛数据",
    "MISSING_MARKET_INTELLIGENCE": "市场信息",
    "INPUT_TIMESTAMP_UNVERIFIED": "赛前时间",
    "IDENTITY_UNRESOLVED": "比赛身份",
}

_QUALITY_ALERT_COPY = "今日比分预测出现异常集中，当前预测仍保留供观察。"


def _user_status_label(status: dict[str, Any]) -> str:
    code = str(status.get("code") or "")
    return _USER_STATUS_LABELS.get(code, "状态待确认")


def _quality_label(value: Any, *, fallback: str = "待补充") -> str:
    labels = {
        "FULL": "较完整",
        "LIMITED": "有限",
        "VERIFIED": "已核验",
        "VERIFIED_MINIMUM": "已核验最低要求",
    }
    text = str(value or "").strip()
    return labels.get(text, fallback if not text else "已记录")


def _data_completeness_label(source_quality: dict[str, Any]) -> str:
    grade = str(source_quality.get("data_grade") or "").strip().upper()
    if grade == "A":
        return "较完整"
    if grade == "B":
        return "已记录"
    if grade == "C":
        return "有限"
    return "有限" if source_quality.get("missing") else "已记录"


def _friendly_missing(value: Any) -> str:
    text = str(value or "").strip()
    return _MISSING_LABELS.get(text, "部分比赛信息")


def _source_display(value: Any) -> str:
    if isinstance(value, dict):
        value = value.get("url") or value.get("path") or value.get("source")
    text = str(value or "").strip()
    if not text:
        return "来源待补充"
    return Path(text).name or "已记录来源"


def _legacy_key_label(value: Any) -> str:
    key = str(value or "")
    if "match_story" in key:
        return "比赛剧本"
    if "score_reasoning" in key:
        return "比分依据"
    if "score_selection_trace" in key:
        return "候选比分比较"
    if "maximum_error_points" in key:
        return "最大不确定性"
    if "market.interpretation" in key:
        return "市场解读"
    if "risk_engine" in key:
        return "风险记录"
    if "structured_form" in key:
        return "比赛数据"
    if "decision_evolution" in key:
        return "判断变化记录"
    return "分析记录"


def _result_scope_label(value: Any) -> str:
    return "90分钟（含伤停补时）" if value else "90分钟赛果"


def _status_explanation(status: dict[str, Any]) -> str:
    code = str(status.get("code") or "")
    fallback = {
        "PENDING": "预测尚未记录，当前不显示正式比分。",
        "INSUFFICIENT_DATA": "当前数据不足，暂不形成正式预测。",
        "PREDICTION_FAILED": "预测未成功，当前不显示正式比分。",
        "MISSED_PREMATCH_WINDOW": "已错过赛前窗口，当前不补写预测。",
    }.get(code)
    reason = str(status.get("reason_text") or "")
    if code in {"PENDING", "PREDICTION_FAILED"}:
        return fallback or ""
    if reason and not reason.isupper() and "_" not in reason:
        return reason
    return fallback or ""


def _evidence_type_label(value: Any) -> str:
    return {
        "模型": "预测依据",
        "model": "预测依据",
        "分析": "分析依据",
        "analysis": "分析依据",
        "基本面": "比赛数据",
        "fundamentals": "比赛数据",
    }.get(str(value or ""), str(value or "证据"))


def _user_copy(value: Any) -> str:
    text = str(value or "")
    return text.replace(
        "原始基本面、市场和模型字段保留在证据审计层",
        "原始比赛数据、市场和预测字段保留在分析依据区",
    ).replace("冻结前", "赛前").replace("冻结预测", "原预测记录").replace("冻结分布", "赛前比分分布").replace("冻结记录", "赛前记录").replace("rank 之外", "候选比分之外")


def _render_support_list(items: list[dict[str, Any]], *, css: str = "evidence-list") -> str:
    if not items:
        return ""
    rows = []
    for item in items:
        label = _esc(_evidence_type_label(item.get("type")), "证据")
        text = _esc(item.get("text"))
        rows.append(f'<li><span class="evidence-type">[{label}]</span>{text}</li>')
    return f'<ul class="{css}">{"".join(rows)}</ul>'


def _render_form(form: dict[str, Any]) -> str:
    if not form:
        return '<div class="compact-empty">近期比赛数据暂未形成可展示条目。</div>'
    labels = {
        "home_overall": "主队整体",
        "home_home": "主队主场",
        "away_overall": "客队整体",
        "away_away": "客队客场",
    }
    rows = []
    for key, label in labels.items():
        value = form.get(key)
        if not isinstance(value, dict):
            continue
        bits = []
        for field, field_label in (
            ("matches", "场"),
            ("wins", "胜"),
            ("draws", "平"),
            ("losses", "负"),
            ("goals_for", "进球"),
            ("goals_against", "失球"),
        ):
            if value.get(field) is not None:
                bits.append(f'{field_label}{_esc(value[field])}')
        rows.append(f'<div class="fact-row"><span>{_esc(label)}</span><strong>{" · ".join(bits)}</strong></div>')
    return "".join(rows) or '<div class="compact-empty">近期比赛数据暂未形成可展示条目。</div>'


def _render_market(market: dict[str, Any]) -> str:
    facts = market.get("facts") or {}
    bookmakers = market.get("observed_1x2_bookmakers") or []
    ah_lines = market.get("observed_ah_lines") or []
    totals_lines = market.get("observed_totals_lines") or []
    timeline = market.get("timeline") or []
    rows = []
    if facts.get("provider"):
        rows.append(f'<div class="fact-row"><span>市场来源</span><strong>{_esc(facts.get("provider"))}</strong></div>')
    if facts.get("bookmaker_count"):
        rows.append(f'<div class="fact-row"><span>市场覆盖</span><strong>{_esc(facts.get("bookmaker_count"))} 家</strong></div>')
    if ah_lines:
        rows.append(f'<div class="fact-row"><span>亚洲让球</span><strong>{_esc("、".join(map(str, ah_lines)))}</strong></div>')
    if totals_lines:
        rows.append(f'<div class="fact-row"><span>大小球</span><strong>{_esc("、".join(map(str, totals_lines)))}</strong></div>')
    if bookmakers:
        rows.append(f'<div class="fact-row fact-row-stack"><span>主要公司</span><strong>{_esc("、".join(map(str, bookmakers)))}</strong></div>')
    if timeline:
        rows.append('<div class="timeline">' + "".join(
            f'<div class="timeline-row"><time>{_esc(item.get("at"))}</time><span>{_esc(item.get("label"))}</span><strong>{_esc(item.get("value"))}</strong></div>'
            for item in timeline if isinstance(item, dict)
        ) + "</div>")
    return "".join(rows) or '<div class="compact-empty">市场信息暂未形成可展示条目。</div>'


def _render_model(model: dict[str, Any]) -> str:
    probabilities = model.get("probabilities") or {}
    btts = model.get("btts") or {}
    return "".join([
        f'<div class="fact-row"><span>进球预期</span><strong>主队 {_esc(_decimal(model.get("lambda_home")))} · 客队 {_esc(_decimal(model.get("lambda_away")))}</strong></div>',
        f'<div class="fact-row"><span>预测概率</span><strong>主胜 {_probability(probabilities.get("home"))} · 平 {_probability(probabilities.get("draw"))} · 客胜 {_probability(probabilities.get("away"))}</strong></div>',
        f'<div class="fact-row"><span>双方进球概率</span><strong>是 {_probability(btts.get("yes"))} · 否 {_probability(btts.get("no"))}</strong></div>',
    ])


def _render_legacy_lineage(material: dict[str, Any]) -> str:
    if not isinstance(material, dict) or material.get("status") in {None, "NOT_FOUND"}:
        return '<div class="compact-empty">历史分析素材暂不可用。</div>'
    origin = material.get("analysis_origin") or {}
    refs = material.get("lineage") or []
    status_labels = {
        "USABLE": "已核对",
        "PARTIALLY_USABLE": "部分可用",
        "PREDICTION_MISMATCH": "与本次预测不一致",
        "TIME_UNVERIFIED": "时间未核实",
        "CONFLICTED": "存在矛盾",
    }
    rows = [
        f'<div class="fact-row"><span>来源状态</span><strong>{_esc(status_labels.get(material.get("status")), "已记录")}</strong></div>',
        f'<div class="fact-row"><span>分析记录时间</span><strong>{_esc(origin.get("source_timestamp"), "待补充")}</strong></div>',
    ]
    if material.get("source_keys"):
        rows.append(f'<div class="fact-row fact-row-stack"><span>分析依据</span><strong>{_esc("、".join(_legacy_key_label(value) for value in material.get("source_keys")))}</strong></div>')
    if refs:
        rows.append('<div class="source-label">来源记录</div><ul class="source-list">' + "".join(
            f'<li>{_esc(_source_display(item.get("source_artifact")), "待补充")}</li>'
            for item in refs if isinstance(item, dict)
        ) + '</ul>')
    return '<details class="technical-details"><summary>技术详情</summary>' + "".join(rows) + '</details>'


def _render_sources(source_quality: dict[str, Any], legacy_material: dict[str, Any] | None = None) -> str:
    refs = source_quality.get("source_references") or []
    rendered = []
    for ref in refs:
        rendered.append(f"<li>{_esc(_source_display(ref))}</li>")
    list_html = f'<ul class="source-list">{"".join(rendered)}</ul>' if rendered else '<div class="compact-empty">来源引用暂未形成可展示条目。</div>'
    missing = source_quality.get("missing") or []
    legacy_html = _render_legacy_lineage(legacy_material or {})
    return "".join([
        f'<div class="fact-row"><span>数据完整度</span><strong>{_esc(_data_completeness_label(source_quality))}</strong></div>',
        f'<div class="fact-row"><span>市场信息质量</span><strong>{_esc(_quality_label(source_quality.get("market_intelligence_quality")))}</strong></div>',
        (f'<div class="fact-row"><span>缺少信息</span><strong>{_esc("、".join(_friendly_missing(value) for value in missing))}</strong></div>' if missing else ""),
        '<div class="source-label">数据来源</div>',
        list_html,
        '<div class="source-label">分析来源</div>',
        legacy_html,
    ])


def _render_probability_distribution(probabilities: dict[str, Any]) -> str:
    keys = ("home", "draw", "away")
    labels = {"home": "主胜", "draw": "平局", "away": "客胜"}
    values = {}
    for key in keys:
        try:
            value = float(probabilities.get(key))
        except (TypeError, ValueError):
            value = None
        values[key] = value if value is not None and math.isfinite(value) else None
    if any(value is None for value in values.values()):
        return '<div class="probability-distribution"><div class="compact-empty"><strong>胜平负概率</strong><span>当前字段不足，暂不展示分布。</span></div></div>'
    total = sum(max(value, 0.0) for value in values.values())
    if total <= 0:
        return '<div class="probability-distribution"><div class="compact-empty"><strong>胜平负概率</strong><span>当前字段不足，暂不展示分布。</span></div></div>'
    leader = max(values, key=values.get)
    segments = "".join(
        f'<span class="probability-segment {key}" style="width:{max(values[key], 0.0) / total * 100:.1f}%"></span>'
        for key in keys
    )
    cells = "".join(
        f'<div class="probability-cell{" is-leading" if key == leader else ""}"><span>{labels[key]}</span><strong>{_probability(values[key])}</strong></div>'
        for key in keys
    )
    aria = "、".join(f"{labels[key]} {_probability(values[key])}" for key in keys)
    return (
        f'<div class="probability-distribution" role="img" aria-label="胜平负概率分布：{html.escape(aria)}">'
        '<div class="probability-heading"><strong>胜平负概率分布</strong><span>三项合计按现有数值展示</span></div>'
        f'<div class="probability-track" aria-hidden="true">{segments}</div>'
        f'<div class="probability-cells">{cells}</div>'
        '</div>'
    )


def _render_score_top3(contract: dict[str, Any], serving: dict[str, str]) -> str:
    candidates = [item for item in (contract.get("candidate_scores") or [])[:3] if isinstance(item, dict)]
    rows = []
    for index, item in enumerate(candidates, 1):
        probability = item.get("probability")
        try:
            numeric_probability = float(probability) if probability is not None else None
        except (TypeError, ValueError):
            numeric_probability = None
        if numeric_probability is not None and not math.isfinite(numeric_probability):
            numeric_probability = None
        probability_html = (
            f'<strong>{_display_score(item.get("score"))} · {_probability(numeric_probability)}</strong>'
            if numeric_probability is not None
            else f'<strong>{_display_score(item.get("score"))}</strong><span class="score-row-prob">概率字段未提供</span>'
        )
        track_html = (
            f'<div class="score-row-track" aria-hidden="true"><span style="width:{max(0.0, min(1.0, numeric_probability)) * 100:.1f}%"></span></div>'
            if numeric_probability is not None
            else ""
        )
        rows.append(
            f'<div class="score-row"><div class="score-row-meta"><span class="score-row-rank">Top {index}</span>'
            f'{probability_html}</div>{track_html}</div>'
        )
    rows_html = "".join(rows) or '<div class="compact-empty">比分候选概率待补充。</div>'
    probability_note = (
        "显示现有比分格概率；单格概率最高，不是确定答案。"
        if any(item.get("probability") is not None for item in candidates)
        else "本次记录仅提供候选顺序，未提供对应比分格概率。"
    )
    return (
        '<section class="score-top3" aria-labelledby="score-top3-title">'
        '<div class="score-top3-heading"><div><div class="section-kicker">Exact Score</div>'
        '<h2 id="score-top3-title">最可能比分 <span>概率 mode</span></h2></div>'
        f'<span class="serving-label">{_esc(serving.get("label"))}</span></div>'
        '<p class="score-top3-note">概率 mode · 单格最高，不是确定答案。</p>'
        f'<div class="score-rows">{rows_html}</div>'
        f'<p class="score-top3-footnote">{_esc(probability_note)}</p>'
        '</section>'
    )


def _render_candidates(contract: dict[str, Any]) -> str:
    candidates = contract.get("candidate_scores") or []
    if not candidates:
        return '<div class="compact-empty">比分候选概率待补充。</div>'
    cards = []
    for index, item in enumerate(candidates[:3], 1):
        probability = item.get("probability")
        probability_html = f' · {_probability(probability)}' if probability is not None else ""
        rank = item.get("rank") or index
        script_label = item.get("script_label")
        script_html = f'<span class="candidate-label">{_esc(script_label)}</span>' if script_label else ""
        cards.append(
            f'<div class="candidate"><span class="candidate-rank">{_esc(rank)}</span><strong>{_display_score(item.get("score"))}{probability_html}</strong>{script_html}</div>'
        )
    return f'<div class="candidate-grid">{"".join(cards)}</div>'


def _render_section(section: dict[str, Any]) -> str:
    supports = _render_support_list(section.get("supports") or [])
    conflicts = _render_support_list(section.get("conflicts") or [], css="evidence-list conflict-list")
    impact = f'<p class="score-impact"><span>比分影响</span>{_esc(section.get("score_impact"))}</p>' if section.get("score_impact") else ""
    return (
        '<article class="analysis-section">'
        f'<h3>{_esc(section.get("title"))}</h3>'
        f'<p class="section-conclusion">{_esc(_user_copy(section.get("conclusion")))}</p>'
        f'{supports}'
        f'{conflicts}'
        f'<p class="section-explanation">{_esc(_user_copy(section.get("explanation")))}</p>'
        f'{impact}</article>'
    )


def render_match_detail(contract: dict[str, Any]) -> str:
    identity = contract.get("identity") or {}
    status = contract.get("status") or {}
    hero = contract.get("hero") or {}
    governance = contract.get("governance") or {}
    timestamps = contract.get("timestamps") or {}
    model = contract.get("model") or {}
    result = contract.get("result") or {}
    evidence = contract.get("evidence") or {}
    source_quality = contract.get("source_quality") or evidence.get("source_quality") or {}
    prediction_quality = contract.get("prediction_quality_health") or {}
    exact_score_serving = exact_score_serving_presentation(prediction_quality)
    pilot = bool(governance.get("pilot_excluded"))
    status_class = _status_class(contract)
    status_note = '<span class="pilot-note">试运行预测 · 不纳入正式验证</span>' if pilot else f'<span class="status-badge">{_esc(_user_status_label(status), "状态待确认")}</span>'
    quality_warning_html = ""
    if exact_score_serving["state"] == DEGRADED:
        quality_warning_html = (
            '<div class="quality-alert serving-degraded" role="status">'
            '<strong>预测质量异常</strong>'
            f'<span>{_esc(_QUALITY_ALERT_COPY)}</span>'
            f'<span>{_esc(exact_score_serving["note"])}</span>'
            '</div>'
        )
    elif exact_score_serving["state"] != "NORMAL":
        quality_warning_html = (
            '<div class="quality-alert serving-unverified" role="status">'
            '<strong>预测质量状态待确认</strong>'
            '<span>当前周期质量来源未完成匹配，模型原始比分继续保留。</span>'
            '</div>'
        )
    status_explanation = _status_explanation(status)
    status_explanation_html = f'<div class="status-explanation"><strong>{_esc(status_explanation)}</strong><span>当前证据不足，暂不扩展判断。</span></div>' if status_explanation else ""
    status_quality = _data_completeness_label(source_quality)
    probabilities = hero.get("probabilities") or model.get("probabilities") or {}
    probability_html = _render_probability_distribution(probabilities)
    score_top3_html = _render_score_top3(contract, exact_score_serving)
    summary = _user_copy(hero.get("summary")) or "当前证据不足，暂不扩展判断。"
    script = hero.get("script")
    script_html = f'<p class="script">{_esc(script)}</p>' if script else '<p class="script muted">比赛剧本暂不可用，暂不扩展判断。</p>'
    supports_html = _render_support_list(hero.get("supports") or []) or '<div class="compact-empty">支持依据暂未形成单独条目。</div>'
    conflicts_html = _render_support_list(hero.get("conflicts") or [], css="evidence-list conflict-list") or '<div class="compact-empty">冲突证据暂未形成单独条目。</div>'
    risk_html = f'<div class="fact-row"><span>最大不确定性</span><strong>{_esc(hero.get("biggest_failure_point"))}</strong></div>' if hero.get("biggest_failure_point") else '<div class="compact-empty">风险提示暂未形成单独条目。</div>'
    post_updates = contract.get("post_freeze_updates") or {}
    update_items = post_updates.get("items") or []
    update_html = ""
    if update_items:
        update_html = '<div class="post-freeze" id="post-freeze"><h3>赛前后新增信息</h3>' + "".join(
            f'<div class="update-item"><time>{_esc(item.get("at"))}</time><strong>{_esc(item.get("label"))}</strong><span>{_esc(item.get("text"))}</span></div>'
            for item in update_items if isinstance(item, dict)
        ) + '<p class="muted">以上信息不参与原预测记录。</p></div>'
    freeze_html = "".join([
        f'<span>预测记录时间 {_esc(timestamps.get("prediction_frozen_at"), "时间待补充")}</span>',
        f'<span>依据更新时间 {_esc(timestamps.get("evidence_updated_at"), "时间待补充")}</span>',
    ])
    route = match_url(identity.get("match_id"))
    page_title = f'{_esc(identity.get("home"), "比赛")} vs {_esc(identity.get("away"), "")} · 详情'
    sections_html = "".join(_render_section(section) for section in contract.get("analysis_sections") or [])
    legacy_material = evidence.get("legacy_report_material") or {}
    model_html = _render_model(model) if model.get("probabilities") or model.get("lambda_home") is not None or model.get("lambda_away") is not None else '<div class="compact-empty">预测数据待补充。</div>'
    result_html = f'<div class="postmatch-result"><span>90分钟赛果</span><strong>{_esc(result.get("score_90m"))}</strong><small>{_esc(_result_scope_label(result.get("scope")))} · {_esc(result.get("verified_at"))}</small></div>' if result.get("score_90m") else '<div class="compact-empty">90分钟赛果将在结果核验后显示。</div>'
    beta_notice_html = render_closed_beta_notice("status-explanation")
    return f'''<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{page_title}</title>
  <style>
    :root {{ color-scheme: dark; --bg:#071116; --panel:#101d26; --panel-2:#162933; --soft:#0c171e; --line:#28404a; --ink:#eef6f4; --muted:#9aadb3; --quiet:#71858d; --accent:#70d6b0; --accent-soft:rgba(112,214,176,.12); --amber:#e2b56e; --amber-soft:rgba(226,181,110,.12); --danger:#f18f8f; --danger-soft:rgba(241,143,143,.12); --max:1200px; }}
    * {{ box-sizing:border-box; }}
    html {{ scroll-behavior:smooth; background:var(--bg); }}
    body {{ margin:0; background:radial-gradient(circle at 14% 0%,#132e38 0,#071116 34rem); color:var(--ink); font:15px/1.6 Inter,ui-sans-serif,system-ui,-apple-system,"Segoe UI","Microsoft YaHei",sans-serif; }}
    a {{ color:inherit; }}
    .page {{ width:min(calc(100% - 32px),var(--max)); margin:0 auto; padding:20px 0 64px; }}
    .topbar {{ display:flex; align-items:center; justify-content:space-between; gap:16px; margin-bottom:12px; }}
    .eyebrow,.section-kicker,.source-label {{ color:var(--muted); font-size:11px; letter-spacing:.13em; text-transform:uppercase; }}
    .back {{ min-height:44px; display:inline-flex; align-items:center; color:var(--muted); text-decoration:none; font-size:13px; }}
    .back:hover {{ color:var(--ink); }}
    .detail-nav {{ position:sticky; top:8px; z-index:2; display:flex; gap:4px; overflow-x:auto; padding:4px; margin:0 0 16px; background:rgba(7,17,22,.88); border:1px solid rgba(112,214,176,.14); border-radius:12px; backdrop-filter:blur(12px); }}
    .detail-nav a {{ min-height:44px; display:inline-flex; align-items:center; white-space:nowrap; color:var(--muted); text-decoration:none; font-size:13px; padding:8px 13px; border-radius:9px; }}
    .detail-nav a:hover,.detail-nav a:focus-visible {{ background:var(--panel-2); color:var(--ink); }}
    .hero,.layer {{ background:linear-gradient(145deg,rgba(20,38,51,.97),rgba(10,24,33,.97)); border:1px solid var(--line); border-radius:16px; box-shadow:0 12px 36px rgba(0,0,0,.16); }}
    .hero {{ padding:24px; }}
    .anchor-target {{ position:relative; top:-88px; display:block; visibility:hidden; }}
    .hero-head {{ display:grid; grid-template-columns:minmax(0,1fr) auto; gap:16px; align-items:start; }}
    .match-meta {{ display:flex; flex-wrap:wrap; gap:7px 13px; color:var(--muted); font-size:13px; }}
    .match-meta span + span {{ padding-left:13px; border-left:1px solid rgba(154,173,179,.2); }}
    .hero h1 {{ margin:8px 0 0; font-size:clamp(28px,4vw,44px); line-height:1.12; letter-spacing:-.035em; overflow-wrap:anywhere; }}
    .hero h1 span {{ color:var(--muted); font-weight:500; }}
    .hero-teams {{ min-width:0; }}
    .hero-state {{ display:flex; flex-wrap:wrap; gap:8px; align-items:center; min-height:44px; margin-top:18px; padding:8px 10px; border:1px solid rgba(154,173,179,.18); border-radius:12px; background:rgba(0,0,0,.12); }}
    .state-detail {{ color:var(--muted); font-size:13px; }}
    .status-badge,.pilot-note {{ display:inline-flex; min-height:32px; align-items:center; border-radius:999px; padding:5px 10px; font-size:12px; white-space:nowrap; }}
    .status-badge {{ background:var(--accent-soft); color:var(--accent); }}
    .pilot-note {{ background:var(--amber-soft); color:var(--amber); }}
    .status-explanation {{ display:flex; flex:1 1 100%; flex-wrap:wrap; gap:5px 10px; padding:9px 11px; border-left:3px solid var(--amber); background:var(--amber-soft); color:#e7c996; font-size:13px; }}
    .status-explanation span {{ color:var(--muted); }}
    .quality-alert {{ display:flex; flex:1 1 100%; flex-wrap:wrap; gap:5px 10px; padding:9px 11px; border-left:3px solid var(--danger); background:var(--danger-soft); color:#f4c6c6; font-size:13px; }}
    .quality-alert strong {{ color:inherit; }}
    .probability-distribution {{ margin-top:20px; padding:16px; border:1px solid rgba(112,214,176,.18); border-radius:14px; background:rgba(0,0,0,.12); }}
    .probability-heading {{ display:flex; justify-content:space-between; gap:12px; align-items:baseline; color:var(--ink); font-size:14px; }}
    .probability-heading span {{ color:var(--quiet); font-size:12px; }}
    .probability-track {{ display:flex; gap:2px; height:12px; margin-top:10px; overflow:hidden; border-radius:999px; background:var(--soft); }}
    .probability-segment {{ min-width:2px; height:100%; }}
    .probability-segment.home {{ background:#5fcda9; }}
    .probability-segment.draw {{ background:#91a6ac; }}
    .probability-segment.away {{ background:#7d9fec; }}
    .probability-cells {{ display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:8px; margin-top:10px; }}
    .probability-cell {{ min-width:0; padding:9px 10px; border:1px solid rgba(154,173,179,.18); border-radius:10px; background:var(--soft); }}
    .probability-cell.is-leading {{ border-color:rgba(112,214,176,.42); background:var(--accent-soft); }}
    .probability-cell span {{ display:block; color:var(--muted); font-size:13px; }}
    .probability-cell strong {{ display:block; margin-top:2px; color:var(--ink); font-size:20px; font-variant-numeric:tabular-nums; }}
    .thirty-second-summary {{ margin-top:20px; padding:16px; border-left:3px solid var(--accent); border-radius:0 14px 14px 0; background:var(--accent-soft); }}
    .thirty-second-summary p {{ margin:6px 0 0; color:#d9e8e5; font-size:17px; }}
    .thirty-second-summary .script {{ color:#c7d8d5; font-size:14px; }}
    .score-top3 {{ margin-top:20px; padding:16px; border:1px solid rgba(154,173,179,.18); border-radius:14px; background:rgba(0,0,0,.12); }}
    .score-top3-heading {{ display:flex; justify-content:space-between; gap:12px; align-items:start; }}
    .score-top3 h2 {{ margin:2px 0 0; font-size:23px; letter-spacing:-.025em; }}
    .score-top3 h2 span {{ color:var(--muted); font-size:12px; font-weight:500; letter-spacing:0; }}
    .serving-label {{ color:var(--muted); font-size:12px; text-align:right; }}
    .score-top3-note,.score-top3-footnote {{ margin:6px 0 0; color:var(--muted); font-size:13px; }}
    .score-rows {{ display:grid; gap:9px; margin-top:14px; }}
    .score-row {{ padding:10px 11px; border:1px solid rgba(154,173,179,.14); border-radius:10px; background:var(--soft); }}
    .score-row:first-child {{ border-color:rgba(112,214,176,.38); }}
    .score-row-meta {{ display:flex; flex-wrap:wrap; gap:8px; align-items:baseline; }}
    .score-row-rank,.score-row-prob {{ color:var(--muted); font-size:12px; }}
    .score-row-meta strong {{ color:var(--ink); font-size:23px; letter-spacing:-.04em; }}
    .score-row-prob {{ margin-left:auto; font-variant-numeric:tabular-nums; }}
    .score-row-track {{ height:6px; margin-top:8px; overflow:hidden; border-radius:999px; background:rgba(154,173,179,.12); }}
    .score-row-track span {{ display:block; height:100%; border-radius:inherit; background:var(--accent); }}
    .layer {{ margin-top:20px; padding:22px; }}
    .layer-heading {{ display:flex; align-items:end; justify-content:space-between; gap:16px; margin-bottom:16px; }}
    .layer h2 {{ margin:0; font-size:23px; letter-spacing:-.02em; }}
    .layer-heading p {{ margin:0; color:var(--muted); font-size:13px; }}
    .model-summary {{ margin-bottom:16px; }}
    .model-notes {{ display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:12px; margin-bottom:16px; }}
    .model-notes > div {{ min-width:0; padding:14px; border:1px solid rgba(145,165,173,.16); border-radius:13px; background:rgba(0,0,0,.10); }}
    .model-notes h3 {{ margin:0 0 8px; font-size:16px; }}
    .analysis-list {{ display:grid; gap:10px; }}
    .analysis-section {{ padding:16px; border:1px solid rgba(145,165,173,.16); border-radius:13px; background:rgba(0,0,0,.10); }}
    .analysis-section h3 {{ margin:2px 0 7px; font-size:18px; }}
    .section-conclusion {{ margin:0 0 10px; color:#e4f0ed; font-size:15px; }}
    .section-explanation {{ margin:11px 0 0; color:var(--muted); font-size:13px; }}
    .score-impact {{ margin:11px 0 0; color:var(--accent); font-size:13px; }}
    .score-impact span {{ color:var(--muted); margin-right:7px; }}
    .candidate-grid {{ display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:8px; margin:0 0 16px; }}
    .candidate {{ min-width:0; padding:11px 12px; border:1px solid rgba(145,165,173,.16); border-radius:11px; background:var(--soft); }}
    .candidate:first-child {{ border-color:rgba(112,214,176,.38); background:var(--accent-soft); }}
    .candidate strong {{ display:block; font-size:20px; letter-spacing:-.04em; }}
    .candidate-rank {{ color:var(--muted); font-size:12px; }}
    .candidate-label {{ display:block; margin-top:5px; color:var(--muted); font-size:12px; overflow-wrap:anywhere; }}
    .evidence-list {{ list-style:none; margin:0; padding:0; display:grid; gap:7px; }}
    .evidence-list li {{ color:#c7d8d5; font-size:13px; }}
    .evidence-type {{ color:var(--muted); margin-right:6px; font-size:12px; }}
    .conflict-list li {{ color:#e4c79f; }}
    .record-line {{ display:flex; flex-wrap:wrap; gap:6px 14px; margin-top:18px; color:var(--muted); font-size:12px; }}
    .detail-grid {{ display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:12px; }}
    .detail-grid .layer {{ margin-top:0; }}
    .fact-row {{ display:flex; justify-content:space-between; gap:14px; padding:9px 0; border-top:1px solid rgba(145,165,173,.1); font-size:14px; }}
    .fact-row span {{ color:var(--muted); }}
    .fact-row strong {{ text-align:right; font-weight:500; overflow-wrap:anywhere; }}
    .fact-row-stack {{ display:block; }}
    .fact-row-stack strong {{ display:block; margin-top:4px; text-align:left; }}
    .source-label {{ margin-top:14px; }}
    .source-list {{ margin:6px 0 0; padding-left:17px; color:var(--muted); font-size:13px; overflow-wrap:anywhere; }}
    .timeline {{ margin-top:12px; }}
    .timeline-row {{ display:grid; grid-template-columns:110px 1fr auto; gap:10px; padding:8px 0; border-top:1px solid rgba(145,165,173,.1); font-size:13px; }}
    .timeline-row time {{ color:var(--muted); }}
    .compact-empty {{ margin-top:10px; padding:10px 12px; border:1px dashed rgba(145,165,173,.25); border-radius:10px; color:var(--muted); background:var(--soft); font-size:13px; }}
    .muted {{ color:var(--muted); }}
    .post-freeze {{ margin-top:12px; padding:14px; border:1px solid rgba(226,181,110,.25); border-radius:13px; background:var(--amber-soft); }}
    .post-freeze h3 {{ margin:0 0 8px; font-size:18px; }}
    .update-item {{ display:flex; flex-wrap:wrap; gap:8px 12px; padding:8px 0; border-top:1px solid rgba(226,181,110,.17); }}
    .postmatch-result {{ display:flex; flex-wrap:wrap; gap:9px; align-items:baseline; padding:12px; border-left:3px solid var(--accent); border-radius:0 10px 10px 0; background:var(--accent-soft); }}
    .postmatch-result span,.postmatch-result small {{ color:var(--muted); font-size:13px; }}
    .postmatch-result strong {{ color:var(--accent); font-size:22px; }}
    footer {{ display:grid; gap:12px; padding:22px 2px 0; color:var(--muted); font-size:12px; }}
    .footer-beta .status-explanation.closed-beta-notice {{ display:grid; gap:3px 12px; margin:0; padding:12px 0 0; border:0; border-top:1px solid var(--line); background:transparent; color:var(--quiet); font-size:12px; }}
    .footer-beta .closed-beta-notice strong {{ color:var(--muted); font-size:12px; }}
    .footer-beta .closed-beta-notice span {{ color:var(--quiet); }}
    @media (max-width:760px) {{
      .page {{ width:min(calc(100% - 24px),var(--max)); padding-top:12px; }}
      .topbar {{ margin-bottom:8px; }}
      .hero,.layer {{ padding:16px; border-radius:14px; }}
      .hero-head {{ display:block; }}
      .hero-head > :last-child {{ margin-top:12px; }}
      .hero h1 {{ font-size:29px; }}
      .hero-state {{ align-items:flex-start; }}
      .model-notes {{ grid-template-columns:1fr; }}
      .detail-grid {{ grid-template-columns:1fr; }}
      .layer-heading {{ display:block; }}
      .layer-heading p {{ margin-top:5px; }}
      .score-top3-heading {{ display:block; }}
      .serving-label {{ display:block; margin-top:8px; text-align:left; }}
      .timeline-row {{ grid-template-columns:1fr; gap:2px; }}
      .fact-row {{ display:block; }}
      .fact-row strong {{ display:block; margin-top:3px; text-align:left; }}
      .candidate-grid {{ grid-template-columns:1fr; }}
    }}
    @media (max-width:380px) {{
      .detail-nav {{ margin-inline:-4px; }}
      .hero h1 {{ font-size:26px; }}
      .probability-distribution,.thirty-second-summary,.score-top3 {{ padding:12px; }}
      .probability-cell {{ padding:8px 6px; }}
      .probability-cell strong {{ font-size:17px; }}
      .score-row-meta strong {{ font-size:21px; }}
    }}
  </style>
</head>
<body class="detail-page status-{html.escape(status_class)}">
  <main class="page">
    <header class="topbar"><a class="back" href="../../prediction_dashboard/latest.html">← 今日比赛</a><span class="eyebrow">赛前决策详情</span></header>
    <nav class="detail-nav" aria-label="页面导航"><a href="#overview">概览</a><a href="#model">模型</a><a href="#market">市场</a><a href="#fundamentals">基本面</a><a href="#sources">来源</a><a href="#postmatch">赛后</a></nav>
    <section class="hero" id="overview">
      <span id="conclusion" class="anchor-target" aria-hidden="true"></span>
      <div class="hero-head"><div><div class="match-meta"><span>{_esc(identity.get("competition"), "赛事待补充")}</span><span>{_esc(identity.get("match_num"), "场次待补充")}</span><span>开球 · {_esc(_format_kickoff(identity.get("kickoff_at")))}</span></div><div class="hero-teams"><div class="eyebrow">概览</div><h1>{_esc(identity.get("home"), "主队待补充")} <span>vs</span> {_esc(identity.get("away"), "客队待补充")}</h1></div></div></div>
      <div class="hero-state"><span>{status_note}</span><span class="state-detail">数据完整度 · {html.escape(status_quality)}</span>{quality_warning_html}{status_explanation_html}</div>
      {probability_html}
      <div class="thirty-second-summary"><div class="section-kicker">30秒结论</div><p>{_esc(summary)}</p>{script_html}</div>
      {score_top3_html}
      <div class="record-line">{freeze_html}<span>业务日 {_esc(identity.get("business_date"), "日期待补充")}</span></div>
    </section>
    <section class="layer" id="model"><span id="analysis" class="anchor-target" aria-hidden="true"></span><div class="layer-heading"><div><div class="eyebrow">模型</div><h2>模型与预测依据</h2></div><p>候选比分来自赛前记录，概率 mode 不是确定答案。</p></div><div class="model-summary">{model_html}</div>{_render_candidates(contract)}<div class="model-notes"><div><h3>支持</h3>{supports_html}</div><div><h3>冲突与风险</h3>{conflicts_html}{risk_html}</div></div><div class="analysis-list">{sections_html or '<div class="compact-empty">模型分析分段待补充。</div>'}</div></section>
    <section class="layer" id="market"><span id="evidence" class="anchor-target" aria-hidden="true"></span><div class="layer-heading"><div><div class="eyebrow">市场</div><h2>市场信息</h2></div><p>只展示当前合约中的市场字段。</p></div>{_render_market(contract.get("market") or {})}</section>
    <section class="layer" id="fundamentals"><div class="layer-heading"><div><div class="eyebrow">基本面</div><h2>近期比赛数据</h2></div><p>来自赛前输入快照。</p></div>{_render_form((evidence.get("fundamentals") or {}).get("recent_form") or {})}</section>
    <section class="layer" id="sources"><div class="layer-heading"><div><div class="eyebrow">来源</div><h2>数据来源</h2></div><p>用于回看本次赛前证据。</p></div>{_render_sources(source_quality, legacy_material)}</section>
    <section class="layer" id="postmatch"><div class="layer-heading"><div><div class="eyebrow">赛后</div><h2>赛后验证</h2></div><p>正式结果口径为 90 分钟含伤停补时。</p></div>{result_html}{update_html}</section>
    <footer><span>稳定地址：{_esc(route)}</span><span>赛前预测记录与当时依据保持不变；新增事实若存在，将单独列为赛前后更新。</span><div class="footer-beta">{beta_notice_html}</div></footer>
  </main>
</body>
</html>
'''


def write_match_detail_page(contract: dict[str, Any], output_root: Path) -> Path:
    match_id = str((contract.get("identity") or {}).get("match_id") or "")
    if not match_id:
        raise ValueError("contract has no match_id")
    target = Path(output_root) / match_id / "index.html"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render_match_detail(contract), encoding="utf-8")
    return target


def build_static_match_pages(
    *,
    business_dates: Iterable[str] | None = None,
    site_matches_root: Path,
    contract_root: Path = MATCH_ANALYSIS_ROOT,
    **roots: Any,
) -> list[Path]:
    contracts = build_match_contracts(business_dates=business_dates, output_root=contract_root, **roots)
    pages = [write_match_detail_page(contract, site_matches_root) for contract in contracts]
    return pages


def _main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", help="business date to build")
    parser.add_argument("--output", type=Path, default=Path("site") / "matches")
    parser.add_argument("--contract-root", type=Path, default=MATCH_ANALYSIS_ROOT)
    args = parser.parse_args()
    output = args.output if args.output.is_absolute() else Path(__file__).resolve().parents[1] / args.output
    contract_root = args.contract_root if args.contract_root.is_absolute() else Path(__file__).resolve().parents[1] / args.contract_root
    pages = build_static_match_pages(
        business_dates=[args.date] if args.date else None,
        site_matches_root=output,
        contract_root=contract_root,
    )
    print(json.dumps({"pages_written": len(pages), "output": str(output)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
