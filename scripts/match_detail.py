#!/usr/bin/env python3
"""Render the shared static match-detail page from an analysis contract."""

from __future__ import annotations

import argparse
import html
import json
from pathlib import Path
from typing import Any, Iterable

try:  # Support both ``python scripts/match_detail.py`` and package imports.
    from .match_analysis import MATCH_ANALYSIS_ROOT, build_match_contracts, match_url
except ImportError:  # pragma: no cover - exercised by the direct CLI path.
    from match_analysis import MATCH_ANALYSIS_ROOT, build_match_contracts, match_url


def _esc(value: Any, fallback: str = "") -> str:
    if value is None or value == "":
        return html.escape(fallback)
    return html.escape(str(value))


def _display_score(value: Any) -> str:
    return _esc(str(value).replace("-", "–")) if value else ""


def _percent(value: Any) -> str:
    if not isinstance(value, (int, float)):
        return _esc(value)
    return f"{value * 100:.1f}%"


def _probability(value: Any) -> str:
    return _percent(value) if value is not None else ""


def _dict_items(payload: Any) -> list[tuple[str, Any]]:
    return list(payload.items()) if isinstance(payload, dict) else []


def _status_class(contract: dict[str, Any]) -> str:
    status = str((contract.get("status") or {}).get("code") or "PENDING").lower()
    if (contract.get("governance") or {}).get("pilot_excluded"):
        return "pilot"
    return status


def _status_explanation(status: dict[str, Any]) -> str:
    code = str(status.get("code") or "")
    fallback = {
        "PENDING": "预测尚未冻结，当前不显示正式比分。",
        "INSUFFICIENT_DATA": "当前数据不足，暂不形成正式预测。",
        "PREDICTION_FAILED": "预测未成功，当前不显示正式比分。",
        "MISSED_PREMATCH_WINDOW": "已错过赛前窗口，当前不补写预测。",
    }.get(code)
    return str(status.get("reason_text") or fallback or "")


def _render_support_list(items: list[dict[str, Any]], *, css: str = "evidence-list") -> str:
    if not items:
        return ""
    rows = []
    for item in items:
        label = _esc(item.get("type"), "证据")
        text = _esc(item.get("text"))
        rows.append(f'<li><span class="evidence-type">[{label}]</span>{text}</li>')
    return f'<ul class="{css}">{"".join(rows)}</ul>'


def _render_form(form: dict[str, Any]) -> str:
    if not form:
        return '<p class="muted">当前没有可追溯的近期比赛数据。</p>'
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
    return "".join(rows) or '<p class="muted">当前没有可追溯的近期比赛数据。</p>'


def _render_market(market: dict[str, Any]) -> str:
    facts = market.get("facts") or {}
    bookmakers = market.get("observed_1x2_bookmakers") or []
    ah_lines = market.get("observed_ah_lines") or []
    totals_lines = market.get("observed_totals_lines") or []
    timeline = market.get("timeline") or []
    rows = [
        f'<div class="fact-row"><span>数据平台</span><strong>{_esc(facts.get("provider"), "未记录")}</strong></div>',
        f'<div class="fact-row"><span>1X2 公司数</span><strong>{_esc(facts.get("bookmaker_count"), "0")}</strong></div>',
        f'<div class="fact-row"><span>AH 观测线</span><strong>{_esc("、".join(map(str, ah_lines)), "未记录")}</strong></div>',
        f'<div class="fact-row"><span>总进球观测线</span><strong>{_esc("、".join(map(str, totals_lines)), "未记录")}</strong></div>',
    ]
    if bookmakers:
        rows.append(f'<div class="fact-row fact-row-stack"><span>实际公司</span><strong>{_esc("、".join(map(str, bookmakers)))}</strong></div>')
    if timeline:
        rows.append('<div class="timeline">' + "".join(
            f'<div class="timeline-row"><time>{_esc(item.get("at"))}</time><span>{_esc(item.get("label"))}</span><strong>{_esc(item.get("value"))}</strong></div>'
            for item in timeline if isinstance(item, dict)
        ) + "</div>")
    return "".join(rows)


def _render_model(model: dict[str, Any]) -> str:
    probabilities = model.get("probabilities") or {}
    btts = model.get("btts") or {}
    return "".join([
        f'<div class="fact-row"><span>模型版本</span><strong>{_esc(model.get("model_family"), "未记录")} · {_esc(model.get("release_version"), "未记录")}</strong></div>',
        f'<div class="fact-row"><span>λ</span><strong>{_esc(model.get("lambda_home"), "—")} / {_esc(model.get("lambda_away"), "—")}</strong></div>',
        f'<div class="fact-row"><span>1X2</span><strong>主 {_probability(probabilities.get("home"))} · 平 {_probability(probabilities.get("draw"))} · 客 {_probability(probabilities.get("away"))}</strong></div>',
        f'<div class="fact-row"><span>BTTS</span><strong>Yes {_probability(btts.get("yes"))} · No {_probability(btts.get("no"))}</strong></div>',
    ])


def _render_sources(source_quality: dict[str, Any]) -> str:
    refs = source_quality.get("source_references") or []
    rendered = []
    for ref in refs:
        if isinstance(ref, dict):
            value = ref.get("url") or ref.get("path") or json.dumps(ref, ensure_ascii=False)
        else:
            value = ref
        rendered.append(f"<li>{_esc(value)}</li>")
    list_html = f'<ul class="source-list">{"".join(rendered)}</ul>' if rendered else '<p class="muted">当前没有可展示的来源引用。</p>'
    missing = source_quality.get("missing") or []
    return "".join([
        f'<div class="fact-row"><span>数据等级</span><strong>{_esc(source_quality.get("data_grade"), "未记录")}</strong></div>',
        f'<div class="fact-row"><span>市场情报质量</span><strong>{_esc(source_quality.get("market_intelligence_quality"), "未记录")}</strong></div>',
        f'<div class="fact-row"><span>输入快照</span><strong>{_esc(source_quality.get("input_snapshot_ref"), "未记录")}</strong></div>',
        f'<div class="fact-row"><span>缺失项</span><strong>{_esc("、".join(map(str, missing)), "无")}</strong></div>',
        '<div class="source-label">来源引用</div>',
        list_html,
    ])


def _render_candidates(contract: dict[str, Any]) -> str:
    candidates = contract.get("candidate_scores") or []
    if not candidates:
        return '<p class="muted">当前没有合法冻结候选比分。</p>'
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
        f'<article class="analysis-section"><div class="section-kicker">{_esc(section.get("id"))}</div>'
        f'<h3>{_esc(section.get("title"))}</h3>'
        f'<p class="section-conclusion">{_esc(section.get("conclusion"))}</p>'
        f'{supports}'
        f'{conflicts}'
        f'<p class="section-explanation">{_esc(section.get("explanation"))}</p>'
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
    pilot = bool(governance.get("pilot_excluded"))
    primary = hero.get("primary_score")
    status_class = _status_class(contract)
    status_note = '<span class="pilot-note">试运行预测 · 不纳入正式验证</span>' if pilot else f'<span class="status-badge">{_esc(status.get("label"), "状态未知")}</span>'
    status_explanation = _status_explanation(status)
    status_explanation_html = f'<div class="status-explanation"><strong>{_esc(status_explanation)}</strong><span>当前证据不足，暂不扩展判断。</span></div>' if status_explanation and not primary else ""
    hero_score = f'<div class="hero-score">{_display_score(primary)}</div>' if primary else '<div class="hero-score empty-score">—</div>'
    neighbors = hero.get("neighbor_scores") or []
    neighbor_html = f'<div class="hero-neighbors">邻近候选 · {" · ".join(_display_score(value) for value in neighbors)}</div>' if neighbors else ""
    probabilities = hero.get("probabilities") or {}
    one_x_two = ""
    if primary and probabilities:
        one_x_two = (
            '<div class="hero-probabilities"><span>主胜 <strong>' + _probability(probabilities.get("home")) +
            '</strong></span><span>平 <strong>' + _probability(probabilities.get("draw")) +
            '</strong></span><span>客胜 <strong>' + _probability(probabilities.get("away")) + '</strong></span></div>'
        )
    script = hero.get("script")
    script_html = f'<p class="script">{_esc(script)}</p>' if script else '<p class="muted">当前没有可追溯的正式比赛剧本字段，暂不扩展判断。</p>'
    supports_html = _render_support_list(hero.get("supports") or [])
    conflicts_html = _render_support_list(hero.get("conflicts") or [], css="evidence-list conflict-list")
    risk_html = f'<div class="risk"><span>最大不确定性</span><strong>{_esc(hero.get("biggest_failure_point"))}</strong></div>' if hero.get("biggest_failure_point") else ""
    result_html = f'<div class="result-banner"><span>90分钟赛果</span><strong>{_esc(result.get("score_90m"))}</strong><small>{_esc(result.get("scope"))} · {_esc(result.get("verified_at"))}</small></div>' if result.get("score_90m") else ""
    post_updates = contract.get("post_freeze_updates") or {}
    update_items = post_updates.get("items") or []
    post_html = ""
    if update_items:
        post_html = '<section class="post-freeze" id="post-freeze"><h2>冻结后更新</h2>' + "".join(
            f'<div class="update-item"><time>{_esc(item.get("at"))}</time><strong>{_esc(item.get("label"))}</strong><span>{_esc(item.get("text"))}</span></div>'
            for item in update_items if isinstance(item, dict)
        ) + '<p class="muted">以上信息不参与原冻结预测。</p></section>'
    freeze_html = "".join([
        f'<span>冻结时间 {_esc(timestamps.get("prediction_frozen_at"), "未记录")}</span>',
        f'<span>证据更新时间 {_esc(timestamps.get("evidence_updated_at"), "未记录")}</span>',
    ])
    route = match_url(identity.get("match_id"))
    page_title = f'{_esc(identity.get("home"), "比赛")} vs {_esc(identity.get("away"), "")} · 详情'
    sections_html = "".join(_render_section(section) for section in contract.get("analysis_sections") or [])
    return f'''<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{page_title}</title>
  <style>
    :root {{ color-scheme: dark; --bg:#071018; --panel:#101d27; --panel-2:#142633; --line:#263b49; --ink:#eef6f4; --muted:#91a5ad; --accent:#70d6b0; --amber:#e2b56e; --danger:#f18f8f; --max:1120px; }}
    * {{ box-sizing:border-box; }}
    html {{ scroll-behavior:smooth; }}
    body {{ margin:0; background:radial-gradient(circle at 14% 0%,#132e38 0,#071018 34rem); color:var(--ink); font:15px/1.65 Inter,ui-sans-serif,system-ui,-apple-system,"Segoe UI","Microsoft YaHei",sans-serif; }}
    a {{ color:inherit; }}
    .page {{ width:min(calc(100% - 32px),var(--max)); margin:0 auto; padding:24px 0 72px; }}
    .topbar {{ display:flex; align-items:center; justify-content:space-between; gap:16px; margin-bottom:20px; }}
    .eyebrow,.section-kicker,.source-label {{ color:var(--muted); font-size:11px; letter-spacing:.14em; text-transform:uppercase; }}
    .back {{ color:var(--muted); text-decoration:none; font-size:13px; }}
    .back:hover {{ color:var(--ink); }}
    .detail-nav {{ position:sticky; top:10px; z-index:2; display:flex; gap:8px; overflow-x:auto; padding:6px; margin:0 0 18px; background:rgba(7,16,24,.86); border:1px solid rgba(112,214,176,.12); border-radius:999px; backdrop-filter:blur(12px); }}
    .detail-nav a {{ white-space:nowrap; color:var(--muted); text-decoration:none; font-size:12px; padding:5px 10px; border-radius:999px; }}
    .detail-nav a:hover {{ background:var(--panel-2); color:var(--ink); }}
    .hero,.layer {{ background:linear-gradient(145deg,rgba(20,38,51,.97),rgba(10,24,33,.97)); border:1px solid var(--line); border-radius:22px; box-shadow:0 20px 60px rgba(0,0,0,.18); }}
    .hero {{ padding:28px; }}
    .hero-head {{ display:flex; justify-content:space-between; align-items:flex-start; gap:16px; }}
    .hero h1 {{ margin:4px 0 0; font-size:clamp(25px,4vw,44px); line-height:1.15; letter-spacing:-.03em; }}
    .hero h1 span {{ color:var(--muted); font-weight:500; }}
    .match-meta {{ display:flex; flex-wrap:wrap; gap:7px 13px; color:var(--muted); font-size:13px; }}
    .status-badge,.pilot-note {{ display:inline-flex; align-items:center; border-radius:999px; padding:5px 10px; font-size:12px; white-space:nowrap; }}
    .status-badge {{ background:rgba(112,214,176,.12); color:var(--accent); }}
    .pilot-note {{ background:rgba(226,181,110,.15); color:var(--amber); }}
    .status-explanation {{ display:flex; flex-wrap:wrap; gap:5px 10px; margin-top:16px; padding:10px 12px; border-left:3px solid var(--amber); background:rgba(226,181,110,.08); color:#e7c996; font-size:13px; }}
    .status-explanation span {{ color:var(--muted); }}
    .hero-score-wrap {{ display:flex; align-items:baseline; gap:18px; margin:28px 0 18px; }}
    .hero-score {{ font-variant-numeric:tabular-nums; font-size:clamp(72px,13vw,148px); line-height:.9; letter-spacing:-.08em; color:var(--accent); font-weight:800; }}
    .empty-score {{ color:var(--muted); }}
    .hero-score-label {{ color:var(--muted); font-size:13px; }}
    .hero-neighbors {{ color:var(--muted); font-size:16px; }}
    .hero-probabilities {{ display:flex; flex-wrap:wrap; gap:8px; color:var(--muted); font-size:13px; margin-top:14px; }}
    .hero-probabilities span {{ padding:5px 9px; background:rgba(255,255,255,.045); border-radius:8px; }}
    .hero-probabilities strong {{ color:var(--ink); }}
    .result-banner {{ display:flex; align-items:baseline; flex-wrap:wrap; gap:9px; margin-top:16px; padding:10px 13px; border-left:3px solid var(--accent); background:rgba(112,214,176,.08); }}
    .result-banner span,.result-banner small {{ color:var(--muted); font-size:12px; }}
    .result-banner strong {{ color:var(--accent); font-size:20px; }}
    .summary {{ max-width:760px; margin:20px 0 0; font-size:17px; color:#d9e8e5; }}
    .script {{ max-width:760px; margin:10px 0 0; color:#c7d8d5; }}
    .hero-grid {{ display:grid; grid-template-columns:1.2fr .8fr; gap:16px; margin-top:22px; }}
    .hero-evidence,.risk {{ padding:15px 16px; border:1px solid rgba(145,165,173,.18); border-radius:15px; background:rgba(0,0,0,.12); }}
    .hero-evidence h3,.risk span {{ margin:0 0 8px; color:var(--muted); font-size:12px; font-weight:600; }}
    .risk {{ display:flex; flex-direction:column; gap:5px; border-color:rgba(241,143,143,.24); }}
    .risk strong {{ color:#f4c6c6; font-weight:500; }}
    .evidence-list {{ list-style:none; margin:0; padding:0; display:grid; gap:7px; }}
    .evidence-list li {{ color:#c7d8d5; }}
    .evidence-type {{ color:var(--muted); margin-right:6px; font-size:12px; }}
    .conflict-list li {{ color:#e4c79f; }}
    .governance-line {{ display:flex; flex-wrap:wrap; gap:6px 14px; margin-top:20px; color:var(--muted); font-size:12px; }}
    .layer {{ margin-top:20px; padding:24px; }}
    .layer-heading {{ display:flex; align-items:end; justify-content:space-between; gap:16px; margin-bottom:18px; }}
    .layer h2 {{ margin:0; font-size:24px; letter-spacing:-.02em; }}
    .layer-heading p {{ margin:0; color:var(--muted); font-size:13px; }}
    .candidate-grid {{ display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:10px; margin-bottom:24px; }}
    .candidate {{ display:flex; align-items:baseline; gap:10px; min-width:0; padding:14px 15px; background:rgba(255,255,255,.045); border-radius:14px; }}
    .candidate:first-child {{ background:rgba(112,214,176,.12); }}
    .candidate strong {{ font-size:26px; letter-spacing:-.04em; }}
     .candidate-rank,.candidate-prob {{ color:var(--muted); font-size:12px; }}
     .candidate-prob {{ margin-left:auto; }}
     .candidate-label {{ grid-column:2/-1; color:var(--muted); font-size:12px; overflow-wrap:anywhere; }}
    .analysis-list {{ display:grid; gap:12px; }}
    .analysis-section {{ padding:19px 20px; border:1px solid rgba(145,165,173,.16); border-radius:16px; background:rgba(0,0,0,.10); }}
    .analysis-section h3 {{ margin:2px 0 7px; font-size:19px; }}
    .section-conclusion {{ margin:0 0 11px; color:#e4f0ed; font-size:15px; }}
    .section-explanation {{ margin:12px 0 0; color:var(--muted); font-size:13px; }}
    .score-impact {{ margin:12px 0 0; color:var(--accent); font-size:13px; }}
    .score-impact span {{ color:var(--muted); margin-right:7px; }}
    .evidence-columns {{ display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:12px; }}
    details {{ border:1px solid rgba(145,165,173,.16); border-radius:15px; background:rgba(0,0,0,.1); padding:0 15px; }}
    details[open] {{ padding-bottom:14px; }}
    summary {{ cursor:pointer; list-style:none; padding:14px 0; font-weight:700; }}
    summary::-webkit-details-marker {{ display:none; }}
    .fact-row {{ display:flex; justify-content:space-between; gap:14px; padding:8px 0; border-top:1px solid rgba(145,165,173,.1); font-size:13px; }}
    .fact-row span {{ color:var(--muted); }}
    .fact-row strong {{ text-align:right; font-weight:500; overflow-wrap:anywhere; }}
    .fact-row-stack {{ display:block; }}
    .fact-row-stack strong {{ display:block; margin-top:4px; text-align:left; }}
    .source-label {{ margin-top:14px; }}
    .source-list {{ margin:6px 0 0; padding-left:17px; color:var(--muted); font-size:12px; overflow-wrap:anywhere; }}
    .timeline {{ margin-top:12px; }}
    .timeline-row {{ display:grid; grid-template-columns:110px 1fr auto; gap:10px; padding:7px 0; border-top:1px solid rgba(145,165,173,.1); font-size:12px; }}
    .timeline-row time {{ color:var(--muted); }}
    .muted {{ color:var(--muted); }}
    .post-freeze {{ margin-top:20px; padding:18px; border:1px solid rgba(226,181,110,.25); border-radius:16px; background:rgba(226,181,110,.06); }}
    .post-freeze h2 {{ margin:0 0 10px; font-size:18px; }}
    .update-item {{ display:flex; flex-wrap:wrap; gap:8px 12px; padding:9px 0; border-top:1px solid rgba(226,181,110,.17); }}
    .update-item time {{ color:var(--muted); }}
    footer {{ padding:24px 2px 0; color:var(--muted); font-size:12px; display:flex; justify-content:space-between; gap:12px; flex-wrap:wrap; }}
    @media (max-width:760px) {{
      .page {{ width:min(calc(100% - 20px),var(--max)); padding-top:14px; }}
      .topbar {{ margin-bottom:12px; }}
      .hero,.layer {{ padding:18px; border-radius:17px; }}
      .hero-head {{ display:block; }}
      .hero-head > :last-child {{ margin-top:12px; }}
      .hero-score-wrap {{ margin-top:23px; gap:12px; }}
      .hero-score-wrap {{ display:block; }}
      .hero-score {{ width:max-content; max-width:100%; font-size:78px; white-space:nowrap; }}
      .hero-score-label {{ margin-top:12px; }}
      .hero-grid,.evidence-columns {{ grid-template-columns:1fr; }}
      .candidate-grid {{ gap:7px; }}
      .candidate {{ padding:11px 10px; gap:6px; }}
      .candidate strong {{ font-size:21px; }}
      .layer-heading {{ display:block; }}
      .layer-heading p {{ margin-top:5px; }}
      .timeline-row {{ grid-template-columns:1fr; gap:2px; }}
      footer {{ display:block; }}
      footer span {{ display:block; margin-top:6px; }}
    }}
  </style>
</head>
<body class="detail-page status-{html.escape(status_class)}">
  <main class="page">
    <header class="topbar"><a class="back" href="../../prediction_dashboard/latest.html">← 今日比赛</a><span class="eyebrow">Match detail · {_esc(contract.get("analysis_contract_version"))}</span></header>
    <nav class="detail-nav" aria-label="页面导航"><a href="#conclusion">结论</a><a href="#analysis">比赛分析</a><a href="#evidence">市场证据</a><a href="#model">模型证据</a><a href="#sources">数据来源</a></nav>
    <section class="hero" id="conclusion">
      <div class="hero-head"><div><div class="match-meta"><span>{_esc(identity.get("competition"), "赛事未记录")}</span><span>{_esc(identity.get("match_num"), "")}</span><span>开球 · {_esc(identity.get("kickoff_at"), "时间未记录")}</span></div><h1>{_esc(identity.get("home"), "主队未记录")} <span>vs</span> {_esc(identity.get("away"), "客队未记录")}</h1></div><div>{status_note}</div></div>
      {status_explanation_html}
      <div class="hero-score-wrap"><div><div class="eyebrow">Layer 1 · 30秒结论</div><div class="eyebrow">唯一首推比分</div>{hero_score}{neighbor_html}</div><div class="hero-score-label">{_esc(hero.get("summary"))}</div></div>
      {one_x_two}
      {result_html}
      {script_html}
      <div class="hero-grid"><div class="hero-evidence"><h3>支持</h3>{supports_html or '<p class="muted">当前没有可单独列出的支持证据。</p>'}<h3 style="margin-top:16px">冲突</h3>{conflicts_html or '<p class="muted">当前没有可单独列出的冲突证据。</p>'}</div>{risk_html}</div>
      <div class="governance-line">{freeze_html}<span>业务日 {_esc(identity.get("business_date"), "未记录")}</span></div>
    </section>
    {post_html}
    <section class="layer" id="analysis"><div class="layer-heading"><div><div class="eyebrow">Layer 2</div><h2>核心候选比分与比赛分析</h2></div><p>候选池只来自已保存的冻结分布。</p></div>{_render_candidates(contract)}<div class="analysis-list">{sections_html}</div></section>
    <section class="layer" id="evidence"><div class="layer-heading"><div><div class="eyebrow">Layer 3</div><h2>完整证据审计</h2></div><p>事实、模型与来源分开呈现。</p></div><div class="evidence-columns"><details open><summary id="fundamentals">基本面</summary>{_render_form((evidence.get("fundamentals") or {}).get("recent_form") or {})}</details><details><summary id="market">市场事实</summary>{_render_market(contract.get("market") or {})}</details><details><summary id="model">模型证据</summary>{_render_model(model)}</details><details><summary id="sources">来源 / 数据质量</summary>{_render_sources(source_quality)}</details></div></section>
    <footer><span>稳定地址：{_esc(route)}</span><span>冻结预测与冻结前证据保持不变；新增事实若存在，将单独列为冻结后更新。</span></footer>
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
