#!/usr/bin/env python3
"""Generate a self-contained Football Betting OneShot HTML analysis report."""

from __future__ import annotations

import argparse
import html
import json
import re
from statistics import fmean
from datetime import datetime
from pathlib import Path

from market_intelligence import analyze as analyze_market_intelligence
from market_history import load_history
from live_ev_profile import DEFAULT_OUTPUT_ROOT as DEFAULT_PROFILE_OUTPUT_ROOT
from live_ev_profile import publish_live_ev_profiles
from risk_engine import analyze as analyze_risk_engine
from risk_engine import dixon_coles_score_matrix
from postmatch_schedule import create_schedule
from sync_postmatch_workflow import sync as sync_postmatch_workflow
from postmatch_queue import SHANGHAI


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_ROOT = PROJECT_ROOT / "data" / "analysis_reports"


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def e(value) -> str:
    return html.escape("—" if value is None or value == "" else str(value))


def num(value, digits=2) -> str:
    if value is None:
        return "—"
    return f"{float(value):.{digits}f}"


def pct(value, digits=1) -> str:
    if value is None:
        return "—"
    numeric = float(value)
    if -1 <= numeric <= 1:
        numeric *= 100
    return f"{numeric:.{digits}f}%"


def no_vig(odds: dict | None) -> dict | None:
    if not odds or not all(odds.get(key) for key in ("home", "draw", "away")):
        return None
    raw = {key: 1 / float(odds[key]) for key in ("home", "draw", "away")}
    total = sum(raw.values())
    return {key: raw[key] / total for key in raw}


def mean_spf(bookmakers: list[dict], field: str) -> dict | None:
    valid = [item.get(field) for item in bookmakers if isinstance(item.get(field), dict)]
    if not valid:
        return None
    result = {}
    for outcome in ("home", "draw", "away"):
        values = [float(item[outcome]) for item in valid if item.get(outcome)]
        result[outcome] = fmean(values) if values else None
    return result if all(result.values()) else None


def build_base_engine_audit(
    deep: dict,
    market_intelligence: dict | None = None,
    risk_engine: dict | None = None,
    model_name: str = "Football Betting OneShot",
    model_version: str = "v0.12.0",
) -> dict:
    euro = deep.get("ouzhi", {}).get("bookmakers", [])
    asian = deep.get("yazhi", {}).get("companies", [])
    totals = deep.get("daxiao", {}).get("companies", [])
    exchange = deep.get("touzhu", {})
    exchange_transactions = exchange.get("pl_flow", {}).get("transactions", [])
    structured_fundamentals = deep.get("shuju") or {}

    euro_open_current = sum(
        1 for item in euro if isinstance(item.get("spf_open"), dict) and isinstance(item.get("spf_current"), dict)
    )
    kelly_count = sum(1 for item in euro if isinstance(item.get("kelly_current"), dict))
    asian_timeline = sum(
        1 for item in asian
        if item.get("current_handicap") is not None
        and item.get("open_handicap") is not None
        and item.get("change_time")
    )
    same_line_sources = sum(
        1 for item in asian
        if item.get("current_handicap") is not None
        and item.get("current_handicap") == item.get("open_handicap")
        and item.get("current_water_home") is not None
        and item.get("open_water_home") is not None
    )
    totals_timeline = sum(
        1 for item in totals
        if item.get("current_line") is not None and item.get("open_line") is not None and item.get("change_time")
    )

    def module(label, data_status, detail):
        return {"label": label, "data_status": data_status, "calculation_status": "not_run", "detail": detail}

    modules = {
        "global_consensus": module(
            "30家公司分层共识",
            "ready" if euro_open_current >= 25 else "degraded",
            f"{euro_open_current}家公司具备欧赔开盘与即时；三层权重尚待计算",
        ),
        "scs": module(
            "SCS共识度",
            "degraded" if euro_open_current >= 20 else "missing",
            "开盘与即时数据可用，但缺完整多帧时间序列和历史噪声基线",
        ),
        "dri": module(
            "DRI离散风险",
            "ready" if deep.get("ouzhi", {}).get("summary", {}).get("dispersion") else "degraded",
            "当前缺联赛历史中位DRI校准库" if not deep.get("ouzhi", {}).get("summary", {}).get("dispersion") else "页面离散值可用；仍需联赛校准",
        ),
        "lead_lag": module(
            "Lead-Lag领涨跟随",
            "ready" if asian_timeline >= 3 else "missing",
            f"{asian_timeline}家公司具备亚盘开盘、即时与变动时间",
        ),
        "water_flow": module(
            "水位流向",
            "ready" if same_line_sources >= 3 else "degraded",
            f"{same_line_sources}家公司可做同盘口水位比较；大小球时间轴可用{totals_timeline}家",
        ),
        "exchange": module(
            "交易所背离与量价验证",
            "degraded" if exchange.get("betfair") else "missing",
            f"必发快照可用，近期交易{len(exchange_transactions)}条；尚不足正式4小时基线",
        ),
        "kelly": module(
            "页面凯利指数共识",
            "ready" if kelly_count >= 20 else "degraded",
            f"{kelly_count}家公司具备即时页面凯利指数；尚待三层聚合，不得视为仓位凯利公式",
        ),
        "shin": module("Shin去水", "ready" if euro_open_current else "missing", "赔率输入可用；必须由分析层输出正式Shin结果"),
        "six_d": module(
            "正式6D",
            "degraded" if structured_fundamentals else "missing",
            "结构化基本面可用" if structured_fundamentals else "shuju结构化结果为空，需联网补齐基本面",
        ),
        "traps": module("陷阱扫描", "degraded", "21条欧亚专项与49条全量规则尚待执行"),
    }
    if market_intelligence:
        market_modules = market_intelligence.get("modules", {})
        tier_data = market_intelligence.get("tiers", {})
        mapped = int(tier_data.get("mapped_count", 0))
        unmapped = len(tier_data.get("unmapped", []))
        modules["global_consensus"]["calculation_status"] = "completed" if unmapped == 0 else "degraded"
        modules["global_consensus"]["detail"] = f"30家公司均值已计算；三层已确认映射{mapped}家，未映射{unmapped}家"
        for key in ("scs", "dri", "lead_lag", "water_flow", "exchange", "kelly"):
            result = market_modules.get(key, {})
            if result:
                modules[key]["calculation_status"] = result.get("calculation_status", "not_run")
                if result.get("reason"):
                    modules[key]["detail"] = result["reason"]
        shin = market_intelligence.get("consensus", {}).get("shin")
        if shin and shin.get("probabilities"):
            modules["shin"]["calculation_status"] = "completed"
            modules["shin"]["detail"] = f"KB-1实用Shin近似已计算；z={shin.get('z', 0):.5f}"
    if risk_engine:
        six_d = risk_engine.get("six_d", {})
        traps = risk_engine.get("traps", {})
        if six_d:
            modules["six_d"]["calculation_status"] = six_d.get("calculation_status", "not_run")
            modules["six_d"]["detail"] = (
                f"KB-4连续评分={six_d.get('legacy_0_to_6', 0):.3f}/6；"
                f"限制：{'、'.join(six_d.get('limitations', [])) or '无'}"
            )
        if traps:
            modules["traps"]["calculation_status"] = traps.get("calculation_status", "not_run")
            modules["traps"]["detail"] = (
                f"上游声称{traps.get('upstream_claimed_total', 49)}条，当前明确定义{traps.get('defined_total', 0)}条；"
                f"已评估{traps.get('evaluated_count', 0)}条，触发{traps.get('triggered_count', 0)}条"
            )
    return {
        "policy": "未明确废弃即继续生效",
        "source_version": f"football-odds-analyst v3.10.8 + {model_name} {model_version}",
        "completion_status": "incomplete",
        "modules": modules,
    }


def enforce_complete_report_gate(payload: dict) -> dict:
    mandatory = ("global_consensus", "scs", "dri", "lead_lag", "water_flow", "exchange", "kelly", "shin", "six_d", "traps")
    modules = payload.get("base_engine_audit", {}).get("modules", {})
    incomplete = [key for key in mandatory if modules.get(key, {}).get("calculation_status") != "completed"]
    audit = payload.setdefault("base_engine_audit", {})
    audit["completion_status"] = "complete" if not incomplete else "incomplete"
    audit["incomplete_modules"] = incomplete
    if incomplete and "完整分析" in payload.get("report", {}).get("report_type", ""):
        payload["report"]["report_type"] = "模型分析草稿（基础内核未完成）"
        payload["report"]["final_execution_version"] = False
        quality = payload.setdefault("data_quality", {})
        missing = quality.setdefault("missing", [])
        message = "基础内核未完成：" + "、".join(incomplete)
        if message not in missing:
            missing.append(message)
    return payload


def merge_dict(base: dict, override: dict) -> dict:
    result = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = merge_dict(result[key], value)
        else:
            result[key] = value
    return result


def normalize_page_pl_labels(value):
    """Prevent legacy payload text from presenting page-derived P/L as verified house liability."""
    if isinstance(value, dict):
        return {key: normalize_page_pl_labels(item) for key, item in value.items()}
    if isinstance(value, list):
        return [normalize_page_pl_labels(item) for item in value]
    if isinstance(value, str):
        normalized = value.replace("庄家主胜方向盈亏", "页面模拟主胜盈亏").replace("庄家盈亏", "页面模拟盈亏")
        normalized = normalized.replace("页面模拟主胜盈亏为负，热门端风险集中", "页面模拟主胜盈亏为负（仅展示，不参与方向或EV）")
        return normalized.replace("凯利共识", "页面凯利指数共识").replace("即时凯利", "即时页面凯利指数").replace("正式凯利信号", "正式页面凯利指数信号")
    return value


BETTING_LAYER_RULES = {
    "保本层": {
        "label": "保本层",
        "display": "保本层｜低波动",
        "purpose": "承担组合稳定器角色，但不承诺保本；只收价格合格、误差较小的合约。",
        "guardrail": "不得用多场热门串关伪装低风险。",
    },
    "中轴层": {
        "label": "中轴层",
        "display": "中轴层｜主收益",
        "purpose": "承载当日主要正EV暴露，可为单关或经审核的跨场组合。",
        "guardrail": "每一腿必须独立通过价格审核。",
    },
    "博上层": {
        "label": "博上层",
        "display": "博上层｜高方差",
        "purpose": "小额使用高赔率正EV；正确比分只能进入本层。",
        "guardrail": "不得承担回本任务，不得覆盖一串相邻比分。",
    },
}


def _betting_layer(value, market=None) -> str:
    raw = str(value or "").strip()
    aliases = {
        "保本": "保本层", "保本层": "保本层", "capital_preservation": "保本层",
        "中轴": "中轴层", "中轴层": "中轴层", "core": "中轴层",
        "博上": "博上层", "博上层": "博上层", "upside": "博上层",
    }
    if raw in aliases:
        return aliases[raw]
    market_text = str(market or "")
    return "博上层" if "比分" in market_text or "波胆" in market_text else "中轴层"


def normalize_betting_portfolio(betting: dict | None) -> dict:
    """Keep one match dimension while allowing multiple audited tickets and parlays."""
    result = dict(betting or {})
    candidates = []
    for index, raw in enumerate(result.get("candidates") or [], start=1):
        item = dict(raw)
        item["ticket_id"] = str(item.get("ticket_id") or f"C{index:03d}")
        item["tier"] = _betting_layer(item.get("tier") or item.get("layer"), item.get("market"))
        item.setdefault("portfolio_role", BETTING_LAYER_RULES[item["tier"]]["purpose"])
        item.setdefault("form", "单关")
        item.setdefault("status", item.get("reprice_status") or "候选")
        candidates.append(item)
    result["candidates"] = candidates

    locked = []
    for index, raw in enumerate(result.get("open_bets") or [], start=1):
        item = dict(raw)
        item["ticket_id"] = str(item.get("ticket_id") or item.get("id") or f"B{index:03d}")
        item["tier"] = _betting_layer(item.get("tier") or item.get("layer"), item.get("market"))
        locked.append(item)
    result["open_bets"] = locked

    layers = []
    for layer_name, meta in BETTING_LAYER_RULES.items():
        layer_candidates = [item for item in candidates if item.get("tier") == layer_name]
        layer_locked = [item for item in locked if item.get("tier") == layer_name]
        proposed = sum(float(item.get("amount") or 0) for item in layer_candidates)
        committed = sum(float(item.get("amount") or 0) for item in layer_locked)
        layers.append({
            **meta,
            "candidate_count": len(layer_candidates),
            "locked_count": len(layer_locked),
            "proposed_exposure": proposed,
            "committed_exposure": committed,
            "status": "已有候选，仍未锁单" if layer_candidates else ("已有锁单" if layer_locked else "暂无合格候选"),
        })
    result["layers"] = layers

    parlays = []
    for index, raw in enumerate(result.get("parlays") or [], start=1):
        item = dict(raw)
        item["ticket_id"] = str(item.get("ticket_id") or f"P{index:03d}")
        item["tier"] = _betting_layer(item.get("tier") or item.get("layer"), item.get("market"))
        item.setdefault("status", "待逐腿价格审核")
        item.setdefault("correlation_status", "待审计")
        parlays.append(item)
    result["parlays"] = parlays

    by_match = {}
    for item in candidates:
        match_key = str(item.get("match_id") or item.get("match") or "").strip()
        if match_key:
            by_match.setdefault(match_key, []).append(item)
    auto_overlap = []
    for match_key, items in by_match.items():
        if len(items) > 1:
            auto_overlap.append({
                "match": match_key,
                "tickets": [item.get("ticket_id") for item in items],
                "risk": "同场多票",
                "control": "必须用完整赛果情景表证明不是重复放大同一判断",
            })
    result["overlap_audit"] = list(result.get("overlap_audit") or []) + auto_overlap
    result["candidate_exposure"] = sum(float(item.get("amount") or 0) for item in candidates)
    result.setdefault("portfolio_state", "三层均为空仓" if not candidates and not parlays else "组合候选待用户确认")
    result.setdefault("parlay_policy", "串关只在每腿独立正EV、价格同时可得且相关性通过审核时成立")
    return result


def source_file(manifest: dict, source: str, project_root: Path) -> Path | None:
    item = manifest.get("sources", {}).get(source, {})
    relative = item.get("file")
    return project_root / relative if relative else None


def deep_file(manifest: dict, project_root: Path) -> Path | None:
    matches = manifest.get("sources", {}).get("500_deep", {}).get("matches", [])
    if not matches:
        return None
    relative = matches[0].get("file")
    return project_root / relative if relative else None


def safe_name(value: str) -> str:
    value = re.sub(r'[<>:"/\\|?*]+', "_", value).strip(" ._")
    return value or "match"


def table(headers: list[str], rows: list[list], classes: list[str] | None = None) -> str:
    head = "".join(f"<th>{e(item)}</th>" for item in headers)
    body_rows = []
    for row_index, row in enumerate(rows):
        cells = []
        for column_index, item in enumerate(row):
            css_class = ""
            if classes and column_index < len(classes) and classes[column_index]:
                css_class = f' class="{classes[column_index]}"'
            cells.append(f"<td{css_class}>{item if isinstance(item, Html) else e(item)}</td>")
        body_rows.append("<tr>" + "".join(cells) + "</tr>")
    empty = '<tr><td colspan="99" class="empty">暂无可用数据</td></tr>' if not rows else ""
    return f'<div class="table-wrap"><table><thead><tr>{head}</tr></thead><tbody>{"".join(body_rows)}{empty}</tbody></table></div>'


class Html(str):
    pass


def badge(text: str, kind="mid") -> Html:
    return Html(f'<span class="badge b-{kind}">{e(text)}</span>')


def card(title: str, icon: str, content: str, full=False) -> str:
    width = " full" if full else ""
    return (
        f'<section class="card{width}"><div class="card-title"><span class="ico">{e(icon)}</span>'
        f'<h2>{e(title)}</h2></div>{content}</section>'
    )


def probability_bars(probabilities: dict | None) -> str:
    labels = [("home", "主胜", "#ff3657"), ("draw", "平局", "#f3eef7"), ("away", "客胜", "#9b7fd0")]
    if not probabilities:
        return '<div class="empty-panel">等待模型概率</div>'
    bars = []
    for key, label, color in labels:
        value = float(probabilities.get(key, 0))
        if value <= 1:
            value *= 100
        bars.append(
            f'<div class="prob-row"><span>{label}</span><div class="prob-track">'
            f'<i style="width:{max(0, min(value, 100)):.2f}%;background:{color}"></i></div>'
            f'<b>{value:.1f}%</b></div>'
        )
    return '<div class="prob-bars">' + "".join(bars) + "</div>"


def score_matrix_summary(model: dict, max_goals: int = 12) -> dict:
    """Return auditable outcome/total/score summaries from the report lambdas."""
    matrix = dixon_coles_score_matrix(model, max_goals=max_goals)
    if not matrix:
        return {}
    home = sum(value for (h, a), value in matrix.items() if h > a)
    draw = sum(value for (h, a), value in matrix.items() if h == a)
    away = sum(value for (h, a), value in matrix.items() if h < a)
    under_25 = sum(value for (h, a), value in matrix.items() if h + a <= 2)
    top_score, top_probability = max(matrix.items(), key=lambda item: item[1])
    return {
        "matrix": matrix,
        "probabilities": {"home": home, "draw": draw, "away": away},
        "under_25": under_25,
        "top_score": f"{top_score[0]}-{top_score[1]}",
        "top_probability": top_probability,
    }


def sensitivity_scenarios(model: dict) -> list[dict]:
    """Stress the two scoring intensities without presenting them as new forecasts."""
    try:
        home = float(model.get("lambda_home"))
        away = float(model.get("lambda_away"))
    except (TypeError, ValueError):
        return []
    rho = float(model.get("rho") or 0.0)
    scenarios = [
        ("基准", home, away, "当前模型"),
        ("整体少0.20球", max(0.05, home - 0.10), max(0.05, away - 0.10), "比赛更谨慎"),
        ("整体多0.20球", home + 0.10, away + 0.10, "节奏更开放"),
        ("主队多0.15球", home + 0.15, away, "主队进攻超预期"),
        ("客队多0.15球", home, away + 0.15, "客队进攻超预期"),
    ]
    rows = []
    for label, lambda_home, lambda_away, note in scenarios:
        summary = score_matrix_summary({"lambda_home": lambda_home, "lambda_away": lambda_away, "rho": rho})
        if summary:
            rows.append({"label": label, "lambda_home": lambda_home, "lambda_away": lambda_away, "note": note, **summary})
    return rows


def primary_live_profile(payload: dict) -> dict:
    profiles = payload.get("live_ev_profiles") or []
    if isinstance(profiles, dict):
        profiles = [profiles]
    return next(
        (item for item in profiles if item.get("active", True) and item.get("overlay_primary", False)),
        next((item for item in profiles if item.get("active", True)), {}),
    )


def genuine_market_timeline(match: dict) -> list[dict]:
    """Use only immutable snapshots; two-point opening/current pairs are not a timeline."""
    shuju_id = match.get("shuju_id")
    if not shuju_id:
        return []
    history = load_history(PROJECT_ROOT / "data" / "market_history" / str(shuju_id) / "market_history.jsonl")
    points = []
    for snapshot in history:
        current_rows = [row.get("current") for row in snapshot.get("euro", []) if isinstance(row.get("current"), dict)]
        if not current_rows:
            continue
        odds = {}
        for outcome in ("home", "draw", "away"):
            values = [float(row[outcome]) for row in current_rows if row.get(outcome)]
            odds[outcome] = fmean(values) if values else None
        if all(odds.values()):
            points.append({"time": snapshot.get("market_time") or snapshot.get("recorded_at"), **odds})
    return points if len(points) >= 3 else []


def timeline_svg(points: list[dict]) -> str:
    if len(points) < 3:
        return '<div class="timeline empty-panel">尚未形成至少3个独立时间点的赔率轨迹；当前开盘/即时值只作快照对照，不伪装成时间序列。</div>'
    width, height, pad = 760, 250, 34
    values = [float(point[key]) for point in points for key in ("home", "draw", "away")]
    low, high = min(values), max(values)
    spread = max(high - low, 0.01)

    def x(index: int) -> float:
        return pad + index * (width - pad * 2) / max(1, len(points) - 1)

    def y(value: float) -> float:
        return pad + (high - value) * (height - pad * 2) / spread

    lines = []
    for key, label, color in (("home", "主胜", "#ff3657"), ("draw", "平局", "#f3eef7"), ("away", "客胜", "#9b7fd0")):
        coordinates = " ".join(f"{x(index):.1f},{y(float(point[key])):.1f}" for index, point in enumerate(points))
        lines.append(f'<polyline points="{coordinates}" fill="none" stroke="{color}" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>')
        lines.append(f'<text x="{width - pad + 5}" y="{y(float(points[-1][key])) + 4:.1f}" fill="{color}" font-size="11">{label}</text>')
    labels = []
    for index in sorted({0, len(points) // 2, len(points) - 1}):
        label = str(points[index].get("time") or "")[-11:-3]
        labels.append(f'<text x="{x(index):.1f}" y="{height - 8}" fill="#8c839f" font-size="10" text-anchor="middle">{e(label)}</text>')
    return (
        '<div class="timeline"><div class="timeline-head"><b>真实多快照赔率轨迹</b>'
        f'<span>{len(points)}个独立快照 · 数值为公司即时均值</span></div>'
        f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="胜平负赔率轨迹">'
        f'<line x1="{pad}" y1="{height-pad}" x2="{width-pad}" y2="{height-pad}" stroke="rgba(255,255,255,.12)"/>'
        + "".join(lines + labels) + '</svg></div>'
    )


def build_payload(
    manifest: dict,
    official: dict,
    trade: dict,
    deep: dict,
    state: dict,
    analysis: dict | None,
    polymarket: dict | None = None,
) -> dict:
    official_match = (official.get("matches") or [{}])[0]
    trade_match = (trade.get("matches") or [{}])[0]
    polymarket = polymarket or {}
    polymarket_target = polymarket.get("target") or {}
    polymarket_match = polymarket.get("match") or {}
    match = {
        "competition": trade_match.get("competition") or official_match.get("league") or "未核到",
        "stage": "未核到",
        "home": trade_match.get("home_team") or official_match.get("homeTeam") or polymarket_target.get("home") or "主队",
        "away": trade_match.get("away_team") or official_match.get("awayTeam") or polymarket_target.get("away") or "客队",
        "business_date": trade_match.get("business_date") or official_match.get("businessDate"),
        "kickoff_local": (
            trade_match.get("kickoff_local")
            or " ".join(filter(None, [official_match.get("matchDate"), official_match.get("matchTime")]))
            or polymarket_target.get("kickoff")
            or polymarket_match.get("kickoff_utc")
        ),
        "match_num": trade_match.get("match_num") or official_match.get("matchNum"),
        "shuju_id": trade_match.get("shuju_id") or deep.get("shuju_id"),
        "single_match_available": trade_match.get("single_match_available"),
    }
    official_spf = official_match.get("spf") or trade_match.get("official_spf_visible")
    official_rqspf = official_match.get("rqspf") or trade_match.get("official_rqspf_visible")
    pinnacle = deep.get("ouzhi", {}).get("pinnacle") or {}
    tier_config = load_json(PROJECT_ROOT / "config" / "bookmaker_tiers.json")
    history_path = PROJECT_ROOT / "data" / "market_history" / str(deep.get("shuju_id")) / "market_history.jsonl"
    market_history = load_history(history_path)
    market_intelligence = analyze_market_intelligence(deep, tier_config, history=market_history) if deep else {}
    trap_registry = load_json(PROJECT_ROOT / "config" / "trap_rules.json")
    analysis_model = (analysis or {}).get("model")
    risk_engine = analyze_risk_engine(deep, market_intelligence, trap_registry, model=analysis_model) if deep else {}
    consensus_open = mean_spf(deep.get("ouzhi", {}).get("bookmakers", []), "spf_open")
    consensus_current = mean_spf(deep.get("ouzhi", {}).get("bookmakers", []), "spf_current")
    betfair = deep.get("touzhu", {}).get("betfair") or {}
    model_default = {
        "status": "等待完整模型",
        "lambda_home": None,
        "lambda_away": None,
        "rho": None,
        "expected_goals": None,
        "probabilities": None,
        "total_goals_buckets": [],
        "btts": {"yes": None, "no": None, "judgement": "待定"},
        "score_probabilities": [],
    }
    decisions_default = {
        "unique_primary_dimension": "待完整模型",
        "unique_score": "待完整模型",
        "mathematical_first": "待完整模型",
        "market_first": "待完整模型",
        "maximum_error_points": ["基本面、大小球和确认首发尚未完成核验"],
        "value_judgement": "尚未进入价格审核",
        "final_state": "空仓（未形成候选）",
    }
    missing_default = [
        "确认首发与即时伤停",
        "可靠的大小球盘口线及时间轴",
        "xG、射门、射正、Big Chances与PSxG",
        "天气、场地与临场信息",
        "用户实际可成交价格",
    ]
    betting_default = {
        "balance": state.get("bankroll", {}).get("current_balance"),
        "open_bets": state.get("exposure", {}).get("open_bets", []),
        "candidates": [],
        "current_exposure": state.get("exposure", {}).get("current_open_exposure", 0),
        "remaining_cash": state.get("bankroll", {}).get("current_balance"),
        "state": "空仓（未形成候选）",
    }
    base = {
        "report": {
            "model_name": state.get("model_name", "Football Betting OneShot"),
            "model_version": state.get("model_version", "v0.12.0"),
            "report_type": "数据审计版",
            "analysis_timestamp": manifest.get("fetch_time"),
            "snapshot_timestamp": manifest.get("fetch_time"),
            "final_execution_version": False,
            "data_run_id": manifest.get("run_id"),
        },
        "match": match,
        "market": {
            "official_spf": official_spf,
            "official_rqspf": official_rqspf,
            "pinnacle": pinnacle,
            "consensus": {"open": consensus_open, "current": consensus_current},
            "betfair": betfair,
            "polymarket": polymarket or {},
            "euro_bookmaker_count": deep.get("ouzhi", {}).get("total", 0),
            "asian_company_count": deep.get("yazhi", {}).get("total", 0),
            "rq_company_count": deep.get("rangqiu", {}).get("total", 0),
            "totals_company_count": deep.get("daxiao", {}).get("total", 0),
        },
        "data_quality": {
            "status": "部分完整",
            "missing": missing_default,
            "notes": [
                "六个500深层页面已保存原始快照",
                "欧赔和交易数据结构化可用",
                "Polymarket仅为公开只读、未校准市场证据，不进入模型概率、EV或执行",
                "大小球与基本面解析尚不完整",
            ],
        },
        "fundamentals": {"status": "待联网补齐", "items": []},
        "model": model_default,
        "decisions": decisions_default,
        "betting": betting_default,
        "evidence_chain": [],
        "market_intelligence": market_intelligence,
        "risk_engine": risk_engine,
        "base_engine_audit": build_base_engine_audit(
            deep,
            market_intelligence,
            risk_engine,
            state.get("model_name", "Football Betting OneShot"),
            state.get("model_version", "v0.12.0"),
        ),
    }
    payload = normalize_page_pl_labels(enforce_complete_report_gate(merge_dict(base, analysis or {})))
    payload["betting"] = normalize_betting_portfolio(payload.get("betting"))
    payload["report"]["model_name"] = state.get("model_name", "Football Betting OneShot")
    payload["report"]["model_version"] = state.get("model_version", "v0.12.0")
    payload["base_engine_audit"]["source_version"] = (
        "football-odds-analyst v3.10.8 + "
        f"{payload['report']['model_name']} {payload['report']['model_version']}"
    )
    return payload


def render(payload: dict) -> str:
    report = payload["report"]
    match = payload["match"]
    market = payload["market"]
    quality = payload["data_quality"]
    model = payload["model"]
    decisions = payload["decisions"]
    betting = payload["betting"]
    pinnacle = market.get("pinnacle") or {}
    pin_open = pinnacle.get("spf_open") or {}
    pin_current = pinnacle.get("spf_current") or {}
    pin_prob = no_vig(pin_current)
    consensus = market.get("consensus") or {}
    consensus_open = consensus.get("open") or {}
    consensus_current = consensus.get("current") or {}
    consensus_prob = (
        payload.get("market_intelligence", {}).get("consensus", {}).get("shin", {}).get("probabilities")
        or no_vig(consensus_current)
    )
    official_spf = market.get("official_spf") or {}
    rq = market.get("official_rqspf") or {}
    betfair = market.get("betfair") or {}
    polymarket = market.get("polymarket") or {}
    poly_match = polymarket.get("match") or {}

    quality_rows = [
        ["竞彩主源", "完整" if official_spf else "缺失", "SPF / RQSPF / 销售比赛"],
        ["欧赔", f"{market.get('euro_bookmaker_count', 0)}家公司", "开盘、即时、概率、返还率、凯利"],
        ["亚盘", f"{market.get('asian_company_count', 0)}家公司", market.get("asian_line_summary") or "当前仅部分结构化"],
        ["大小球", f"{market.get('totals_company_count', 0)}家公司原始页", market.get("totals_line_summary") or "盘口线尚未通过质量校验"],
        ["基本面", quality.get("status", "待定"), "确认首发、伤停、高级数据待补"],
        [
            "Polymarket",
            poly_match.get("status", "未抓取"),
            "公开只读市场证据；不连接账户，不作为EV成交价",
        ],
    ]
    audit = table(["数据模块", "状态", "说明"], quality_rows)
    missing_items = "".join(f"<li>{e(item)}</li>" for item in quality.get("missing", []))
    audit += f'<div class="callout warn"><b>当前缺口</b><ul>{missing_items}</ul></div>'

    market_rows = [
        ["竞彩官方", num(official_spf.get("home")), num(official_spf.get("draw")), num(official_spf.get("away")), "执行价格参考"],
        ["30家公司开盘均值", num(consensus_open.get("home")), num(consensus_open.get("draw")), num(consensus_open.get("away")), "全球分析基线"],
        ["30家公司即时均值", num(consensus_current.get("home")), num(consensus_current.get("draw")), num(consensus_current.get("away")), "全球分析基线"],
        ["Pinnacle开盘", num(pin_open.get("home")), num(pin_open.get("draw")), num(pin_open.get("away")), "Sharp层参考"],
        ["Pinnacle即时", num(pin_current.get("home")), num(pin_current.get("draw")), num(pin_current.get("away")), f"Sharp层参考；返还率 {num(pinnacle.get('return_current_pct'))}%"],
    ]
    market_content = table(["来源", "主胜", "平局", "客胜", "用途"], market_rows)
    market_content += probability_bars(consensus_prob)

    base_audit = payload.get("base_engine_audit") or {}
    audit_rows = []
    status_label = {"ready": "数据就绪", "degraded": "降级", "missing": "数据缺失", "completed": "已计算", "not_run": "未计算"}
    for item in (base_audit.get("modules") or {}).values():
        audit_rows.append([
            item.get("label"),
            status_label.get(item.get("data_status"), item.get("data_status")),
            status_label.get(item.get("calculation_status"), item.get("calculation_status")),
            item.get("detail"),
        ])
    base_audit_content = table(["基础模块", "数据状态", "计算状态", "说明"], audit_rows)
    base_audit_content += f'<div class="callout warn"><b>内核状态</b><span>{e(base_audit.get("completion_status"))}；未完成时报告不得称为完整分析版。</span></div>'

    mbi = payload.get("market_intelligence") or {}
    mbi_modules = mbi.get("modules") or {}
    scs = mbi_modules.get("scs") or {}
    scs_outcomes = scs.get("per_outcome") or {}
    dri = mbi_modules.get("dri") or {}
    lead_lag = mbi_modules.get("lead_lag") or {}
    flow = mbi_modules.get("water_flow") or {}
    exchange_module = mbi_modules.get("exchange") or {}
    kelly_module = mbi_modules.get("kelly") or {}
    lead_observed = " → ".join(
        f"{item.get('name')} {item.get('change_time')}"
        for item in lead_lag.get("observed", [])
    ) or "—"
    exchange_gaps = exchange_module.get("volume_minus_market_probability_pp") or {}
    kelly_tiers = kelly_module.get("tiers") or {}
    kelly_text = "；".join(
        f"{tier}:{num((values.get('current_mean') or {}).get('home'))}/{num((values.get('current_mean') or {}).get('draw'))}/{num((values.get('current_mean') or {}).get('away'))}"
        for tier, values in kelly_tiers.items()
    ) or "—"
    mbi_rows = [
        ["SCS", scs.get("calculation_status"), f"主{num((scs_outcomes.get('home') or {}).get('signed_score'), 3)} / 平{num((scs_outcomes.get('draw') or {}).get('signed_score'), 3)} / 客{num((scs_outcomes.get('away') or {}).get('signed_score'), 3)}", scs.get("reason")],
        ["DRI", dri.get("calculation_status"), f"原始{num(dri.get('raw'), 2)} / 校准{num(dri.get('calibrated'), 2)} / {dri.get('risk_band', '—')}", dri.get("reason")],
        ["Lead-Lag", lead_lag.get("calculation_status"), lead_observed, lead_lag.get("reason")],
        ["水位流向", flow.get("calculation_status"), f"同盘口{flow.get('same_line_sources', 0)}家 / 比率{num(flow.get('flow_ratio'), 2)} / {flow.get('direction', '—')}", flow.get("reason")],
        ["交易所背离", exchange_module.get("calculation_status"), f"主{num(exchange_gaps.get('home'), 1)}pp / 平{num(exchange_gaps.get('draw'), 1)}pp / 客{num(exchange_gaps.get('away'), 1)}pp", exchange_module.get("reason")],
        ["页面凯利指数共识", kelly_module.get("calculation_status"), kelly_text, kelly_module.get("reason")],
    ]
    mbi_content = table(["MBI模块", "状态", "当前计算", "限制"], mbi_rows)
    mbi_content += f'<div class="callout warn"><b>正式MBI</b><span>{e(mbi.get("formal_mbi_status", "未计算"))}；降级模块不允许生成正式综合判定。</span></div>'

    risk_engine = payload.get("risk_engine") or {}
    six_d = risk_engine.get("six_d") or {}
    traps = risk_engine.get("traps") or {}
    dimension_rows = []
    for key, item in (six_d.get("dimensions") or {}).items():
        dimension_rows.append([
            key,
            num(item.get("score"), 3),
            pct(item.get("weight"), 0),
            num((item.get("score") or 0) * (item.get("weight") or 0), 3),
            item.get("reason"),
        ])
    risk_content = table(["维度", "原始分", "权重", "加权贡献", "计算依据"], dimension_rows)
    action_label = {
        "confidence_plus_3pp": "置信度可上调3个百分点",
        "neutral": "不修正置信度",
        "confidence_minus_3pp": "置信度下调3个百分点",
        "skip": "跳过",
    }
    risk_content += (
        f'<div class="callout warn"><b>6D结果</b><span>{num(six_d.get("legacy_0_to_6"), 3)}/6 · '
        f'{e(six_d.get("calculation_status", "未计算"))} · {e(action_label.get(six_d.get("action"), six_d.get("action")))}；'
        f'限制：{e("、".join(six_d.get("limitations", [])) or "无")}</span></div>'
    )
    triggered_rows = [
        [item.get("id"), item.get("category"), item.get("name"), item.get("trigger"), item.get("reason")]
        for item in traps.get("triggered", [])
    ]
    risk_content += table(["触发编号", "类别", "规则", "阈值", "当前证据"], triggered_rows)
    unresolved = "；".join(traps.get("unresolved_upstream_rules", [])) or "无"
    risk_content += (
        f'<div class="callout warn"><b>陷阱覆盖</b><span>上游声称{e(traps.get("upstream_claimed_total"))}条，'
        f'当前明确定义{e(traps.get("defined_total"))}条；已评估{e(traps.get("evaluated_count"))}条，'
        f'触发{e(traps.get("triggered_count"))}条，未能评估{e(traps.get("not_evaluable_count"))}条。'
        f'上游缺口：{e(unresolved)}</span></div>'
    )

    b_rows = []
    for key, label in (("home", "主胜"), ("draw", "平局"), ("away", "客胜")):
        item = betfair.get(key, {})
        page_pl = item.get("page_simulated_pl", item.get("bookmaker_pl", 0))
        b_rows.append([label, num(item.get("betfair_price")), f"{int(item.get('betfair_volume', 0)):,}", pct(item.get("volume_ratio_pct")), f"{int(page_pl):,}", item.get("hot_cold_index")])
    trade_content = table(["方向", "成交价", "成交量", "占比", "页面模拟盈亏*", "冷热"], b_rows)

    poly_three_way = polymarket.get("three_way_consensus") or {}
    poly_outcomes = poly_three_way.get("outcomes") or {}
    poly_norm = poly_three_way.get("normalized_mid_probabilities") or {}
    poly_rows = []
    for key, label in (("home", "主胜"), ("draw", "平局"), ("away", "客胜")):
        item = poly_outcomes.get(key) or {}
        poly_rows.append([
            label,
            num(item.get("best_bid"), 4),
            num(item.get("best_ask"), 4),
            num(item.get("mid"), 4),
            pct(poly_norm.get(key), 2),
            num(item.get("liquidity"), 0),
            "是" if item.get("fees_enabled") else "否",
        ])
    poly_content = table(["方向", "买一", "卖一", "中间价", "三向归一化", "流动性", "费用"], poly_rows)
    score_contracts = (polymarket.get("correct_score") or {}).get("contracts") or []
    poly_score_rows = [
        [row.get("selection_label"), num(row.get("best_bid"), 4), num(row.get("best_ask"), 4), num(row.get("mid"), 4), num(row.get("liquidity"), 0)]
        for row in sorted(score_contracts, key=lambda row: row.get("mid") or 0, reverse=True)[:12]
    ]
    poly_content += table(["波胆合约", "买一", "卖一", "中间价", "流动性"], poly_score_rows)

    kpis = [
        ("λ 主队", model.get("lambda_home")),
        ("λ 客队", model.get("lambda_away")),
        ("总进球期望", model.get("expected_goals")),
        ("低比分ρ", model.get("rho")),
    ]
    kpi_html = "".join(
        f'<div class="kpi"><span>{num(value, 3) if value is not None else "—"}</span><small>{e(label)}</small></div>'
        for label, value in kpis
    )
    model_content = f'<div class="status-line">{badge(model.get("status", "待定"), "warn" if not model.get("probabilities") else "good")}</div><div class="kpis">{kpi_html}</div>'
    model_content += probability_bars(model.get("probabilities"))

    live_profile = primary_live_profile(payload)
    live_probability = live_profile.get("probability") or {}
    live_execution = live_profile.get("execution") or {}
    point_probability = live_probability.get("point")
    conservative_probability = live_probability.get("conservative")
    minimum_conservative_ev = float(live_execution.get("minimum_conservative_ev") or 0.0)
    if point_probability and conservative_probability:
        point_probability = float(point_probability)
        conservative_probability = float(conservative_probability)
        point_fair_odds = 1.0 / point_probability
        conservative_fair_odds = 1.0 / conservative_probability
        execution_odds = (1.0 + minimum_conservative_ev) / conservative_probability
        interval_html = (
            '<div class="interval-panel">'
            f'<div><small>主维度点概率</small><b>{pct(point_probability)}</b><em>公平赔率 {num(point_fair_odds)}</em></div>'
            f'<div><small>保守概率边界</small><b>{pct(conservative_probability)}</b><em>保守公平价 {num(conservative_fair_odds)}</em></div>'
            f'<div class="accent"><small>允许执行的最低赔率</small><b>{num(execution_odds)}</b><em>已含 {pct(minimum_conservative_ev)} EV安全边际</em></div>'
            '</div><p class="method-note">这里是“保守边界—点估计”的执行区间，不冒充统计置信区间。</p>'
        )
        model_content += interval_html

    model_probabilities = model.get("probabilities") or {}
    divergence_rows = []
    divergence_summary = []
    for key, label in (("home", "主胜"), ("draw", "平局"), ("away", "客胜")):
        model_value = model_probabilities.get(key)
        market_value = (consensus_prob or {}).get(key)
        if model_value is None or market_value is None:
            continue
        model_value = float(model_value)
        market_value = float(market_value)
        if model_value > 1:
            model_value /= 100
        if market_value > 1:
            market_value /= 100
        gap_pp = (model_value - market_value) * 100
        if gap_pp >= 3:
            reading = "模型高于市场"
            css = "gap-pos"
        elif gap_pp <= -3:
            reading = "市场高于模型"
            css = "gap-neg"
        else:
            reading = "基本一致"
            css = "gap-flat"
        divergence_rows.append([label, pct(model_value), pct(market_value), Html(f'<span class="{css}">{gap_pp:+.1f}pp</span>'), reading])
        divergence_summary.append((abs(gap_pp), label, gap_pp))
    divergence_content = table(["结果", "模型概率", "市场去水概率", "差值", "解读"], divergence_rows)
    if divergence_summary:
        _, largest_label, largest_gap = max(divergence_summary)
        divergence_content += (
            '<div class="plain-conclusion"><b>最大分歧</b>'
            f'<span>{e(largest_label)}：模型相对市场 {largest_gap:+.1f} 个百分点。分歧用于定位需要解释的方向，不自动等于投注价值。</span></div>'
        )

    fundamentals = payload.get("fundamentals", {})
    fundamental_items = fundamentals.get("items", [])
    if fundamental_items:
        fundamental_html = "".join(
            '<div class="fact">'
            f'<b>{e(item.get("label"))}</b><span>{e(item.get("value"))}'
            + (f'<a href="{e(item.get("source_url"))}" target="_blank" rel="noopener">查看来源</a>' if item.get("source_url") else "")
            + '</span></div>'
            for item in fundamental_items
        )
    else:
        fundamental_html = '<div class="empty-panel">本次未取得可唯一匹配的赛前信息；不据此猜测首发、伤停或天气。</div>'

    primary_error = (decisions.get("maximum_error_points") or ["临场信息可能使首推失效"])[0]
    rq_rows = [[
        f"主队 {rq.get('handicap', '—')}", num(rq.get("home")), num(rq.get("draw")), num(rq.get("away")),
        "单关" if match.get("single_match_available") else "未核到",
    ]]
    rq_market_content = table(["让球", "主胜", "平局", "客胜", "销售"], rq_rows)
    asian = market.get("asian_handicap") or {}
    if asian:
        rq_market_content += table(
            ["节点", "盘口", "主队价格", "客队价格", "说明"],
            [
                ["开盘", asian.get("open_line"), asian.get("open_home_odds"), asian.get("open_away_odds"), asian.get("open_note")],
                ["即时", asian.get("current_line"), asian.get("current_home_odds"), asian.get("current_away_odds"), asian.get("current_note")],
            ],
        )
    rq_content = rq_market_content + (
        '<div class="primary-with-risk">'
        f'<div class="callout"><b>唯一主维度</b><span>{e(decisions.get("unique_primary_dimension"))}</span></div>'
        f'<div class="callout warn"><b>首要错点</b><span>{e(primary_error)}</span></div>'
        '</div>'
    )

    totals_rows = model.get("total_goals_buckets") or []
    totals_market = market.get("totals") or {}
    totals_content = ""
    if totals_market:
        totals_content += table(
            ["节点", "盘口", "大球价格", "小球价格", "说明"],
            [
                ["开盘", totals_market.get("open_line"), totals_market.get("open_over_odds"), totals_market.get("open_under_odds"), totals_market.get("open_note")],
                ["即时", totals_market.get("current_line"), totals_market.get("current_over_odds"), totals_market.get("current_under_odds"), totals_market.get("current_note")],
            ],
        )
    totals_content += table(
        ["总进球数", "模型概率"],
        [[f'{item.get("bucket", item.get("goals", "—"))}球', pct(item.get("probability"))] for item in totals_rows],
    )
    totals_content += f'<div class="callout"><b>BTTS</b><span>{e(model.get("btts", {}).get("judgement"))}</span></div>'
    sensitivity_rows = []
    for item in sensitivity_scenarios(model):
        probabilities = item["probabilities"]
        sensitivity_rows.append([
            item["label"],
            f'{num(item["lambda_home"], 2)} / {num(item["lambda_away"], 2)}',
            f'{pct(probabilities["home"])} / {pct(probabilities["draw"])} / {pct(probabilities["away"])}',
            pct(item["under_25"]),
            f'{item["top_score"]}（{pct(item["top_probability"])}）',
            item["note"],
        ])
    if sensitivity_rows:
        totals_content += '<h3 class="subhead">参数敏感性：如果比赛不像基准剧本</h3>'
        totals_content += table(["情景", "主/客 λ", "主/平/客", "小2.5", "最高比分", "含义"], sensitivity_rows)

    score_rows = model.get("score_probabilities") or []
    matrix_summary = score_matrix_summary(model)
    matrix = matrix_summary.get("matrix") or {}
    heat_rows = []
    if matrix:
        visible_max = max(matrix.get((home_goals, away_goals), 0.0) for home_goals in range(6) for away_goals in range(6)) or 1.0
        for home_goals in range(6):
            row = [Html(f'<b class="heat-axis">主{home_goals}</b>')]
            for away_goals in range(6):
                probability = matrix.get((home_goals, away_goals), 0.0)
                alpha = 0.08 + 0.72 * probability / visible_max
                row.append(Html(
                    f'<span class="heat-cell" style="background:rgba(255,54,87,{alpha:.3f})">'
                    f'<b>{home_goals}-{away_goals}</b><small>{pct(probability)}</small></span>'
                ))
            heat_rows.append(row)
    score_content = ""
    if heat_rows:
        score_content += '<div class="heatmap"><div class="heat-title">行是主队进球，列是客队进球；颜色越深，模型概率越高。</div>'
        score_content += table(["比分"] + [f"客{goals}" for goals in range(6)], heat_rows)
        score_content += '</div>'
    score_content += '<h3 class="subhead">最高概率比分排序</h3>' + table(["排名", "比分", "概率", "公平赔率"], [
        [index + 1, item.get("score"), pct(item.get("probability")), num(item.get("fair_odds"), 2)]
        for index, item in enumerate(score_rows[:10])
    ])
    primary_dimension = decisions.get("unique_primary_dimension")
    unique_score = decisions.get("unique_score")
    score_content += (
        '<div class="decision-strip">'
        f'<div><small>胜平负主线</small><b>{e(primary_dimension)}</b><em>{e(decisions.get("mathematical_first"))}</em></div>'
        f'<div><small>盘口对照</small><b>{e(decisions.get("market_first"))}</b><em>市场只用于校准和发现分歧，不替代模型主线。</em></div>'
        f'<div class="accent"><small>单一比分落点</small><b>{e(unique_score)}</b><em>这是概率最高的一个比分格，不代表要买比分列表，也不等于胜平负总概率的第一方向。首要错点：{e(primary_error)}</em></div>'
        '</div>'
    )

    error_items = "".join(f"<li>{e(item)}</li>" for item in decisions.get("maximum_error_points", []))
    conclusion = (
        '<div class="verdict-grid">'
        f'<div><small>唯一主维度</small><b>{e(decisions.get("unique_primary_dimension"))}</b></div>'
        f'<div><small>唯一首推比分</small><b>{e(decisions.get("unique_score"))}</b></div>'
        f'<div><small>价值判断</small><b>{e(decisions.get("value_judgement"))}</b></div>'
        f'<div><small>最终状态</small><b>{e(decisions.get("final_state"))}</b></div>'
        '</div>'
        f'<div class="callout warn"><b>最大错点</b><ul>{error_items}</ul></div>'
    )

    candidate_rows = []
    for item in betting.get("candidates", []):
        candidate_rows.append([
            item.get("match"), item.get("market"),
            item.get("user_channel_odds", item.get("observed_odds")),
            item.get("repriced_ev", item.get("initial_ev")),
            item.get("minimum_acceptable_decimal_odds", item.get("odds_threshold")),
            item.get("reprice_source", item.get("odds_source")), item.get("amount"), item.get("form"),
            item.get("status", item.get("reprice_status", "候选")),
        ])
    locked_rows = []
    for item in betting.get("open_bets", []):
        locked_rows.append([
            item.get("match"), item.get("market"), item.get("odds"), "冻结", "—",
            item.get("source"), item.get("amount"), item.get("form"), "已锁",
        ])
    betting_rows = locked_rows + candidate_rows
    betting_content = (
        '<div class="money-grid">'
        f'<div><small>当前余额</small><b>¥{num(betting.get("balance"))}</b></div>'
        f'<div><small>已锁暴露</small><b>¥{num(betting.get("current_exposure"))}</b></div>'
        f'<div><small>候选暴露</small><b>¥{num(betting.get("candidate_exposure"))}</b></div>'
        f'<div><small>投注状态</small><b>{e(betting.get("state"))}</b></div>'
        '</div>'
    )
    betting_content += table(["比赛", "玩法", "抓取/渠道赔率", "初算/复算EV", "最低可接受赔率", "来源/时间", "金额", "形式", "状态"], betting_rows)

    def format_market_vector(value: Any, *, probability: bool = False) -> str:
        if isinstance(value, dict):
            labels = (("home", "主"), ("draw", "平"), ("away", "客"))
            parts = []
            for key, label in labels:
                cell = value.get(key)
                parts.append(f"{label}{pct(cell, 1) if probability else num(cell, 2)}")
            return " / ".join(parts)
        return pct(value, 1) if probability else num(value, 2)

    price_audit_rows = []
    for item in betting.get("price_audit") or []:
        odds = item.get("odds")
        probabilities = item.get("model_probabilities", item.get("model_probability"))
        ev_value = item.get("ev")
        minimum = item.get("minimum_acceptable_decimal_odds", item.get("conservative_fair_odds"))
        if isinstance(odds, (int, float)) and isinstance(minimum, (int, float)):
            result = "达到执行线" if float(odds) >= float(minimum) else "不过执行线"
        elif isinstance(ev_value, dict):
            ev_cells = [value for value in ev_value.values() if isinstance(value, (int, float))]
            result = "不过线" if ev_cells and max(ev_cells) <= 0 else "存在正EV方向"
        elif isinstance(ev_value, (int, float)):
            result = "正EV" if ev_value > 0 else "不过线"
        else:
            result = "等待渠道价"
        price_audit_rows.append([
            item.get("market"),
            format_market_vector(odds),
            format_market_vector(probabilities, probability=True),
            format_market_vector(ev_value, probability=True),
            minimum,
            result,
        ])
    price_audit_content = table(
        ["审核玩法", "当前赔率", "模型概率", "EV", "最低价格", "结论"],
        price_audit_rows,
    )
    betting_content += '<h3 class="subhead">赔率价值审核</h3>' + price_audit_content

    live_contract = live_profile.get("contract") or {}
    live_match_id = live_contract.get("match_id") or match.get("live_match_id")
    if live_profile and live_match_id:
        live_market_label = " ".join(filter(None, [live_contract.get("market_name"), str(live_contract.get("handicap_line") or ""), live_contract.get("selection_name") or live_contract.get("selection_code")]))
        live_reprice_content = (
            '<div class="live-reprice" id="liveRepricePanel">'
            '<div class="live-head"><div><small>实时EV联动</small>'
            f'<b>{e(live_market_label)}</b></div><span class="live-dot connected">赔率页悬浮窗</span></div>'
            '<div class="live-values">'
            '<div><small>模型概率</small><b>' + (pct(point_probability) if point_probability else '—') + '</b></div>'
            '<div><small>保守概率</small><b>' + (pct(conservative_probability) if conservative_probability else '—') + '</b></div>'
            f'<div><small>执行线</small><b>{num(execution_odds) if point_probability and conservative_probability else "—"}</b></div>'
            '<div><small>实时结论</small><b>在渠道赔率页查看</b></div>'
            '</div><p class="method-note">实时赔率、盘口变动和EV由浏览器扩展悬浮窗读取。本报告页不再显示“桥接未连接”的假状态；比赛开赛后不沿用赛前概率。</p>'
            '<a class="live-action" href="https://user-pc-new.hl99yjjpf.com/#/home" target="_blank" rel="noopener">打开渠道赔率页</a></div>'
        )
        betting_content = live_reprice_content + betting_content
    else:
        live_reprice_content = ""

    evidence_items = payload.get("evidence_chain") or [
        {"title": "市场锚点", "items": [f"Pinnacle即时：{num(pin_current.get('home'))} / {num(pin_current.get('draw'))} / {num(pin_current.get('away'))}", f"竞彩官方：{num(official_spf.get('home'))} / {num(official_spf.get('draw'))} / {num(official_spf.get('away'))}"]},
        {"title": "交易层", "items": ["已获取三向成交价、成交量、成交占比、页面模拟盈亏和冷热指数；模拟盈亏不作为方向信号"]},
        {"title": "Polymarket只读证据", "items": [f"赛事匹配：{poly_match.get('status', '未抓取')}", "公开买卖价、流动性和市场分歧仅作诊断；不连接账户，不进入EV或执行"]},
        {"title": "待补齐", "items": quality.get("missing", [])},
    ]
    evidence_cols = []
    for block in evidence_items:
        items = "".join(f"<li>{e(item)}</li>" for item in block.get("items", []))
        evidence_cols.append(f'<div><h3>{e(block.get("title"))}</h3><ul>{items}</ul></div>')
    evidence = '<div class="evidence-grid">' + "".join(evidence_cols) + "</div>"

    headline = (
        '<div class="answer-banner">'
        '<div><small>唯一主维度</small>'
        f'<strong>{e(decisions.get("unique_primary_dimension"))}</strong></div>'
        '<div><small>90分钟首推比分</small>'
        f'<strong>{e(decisions.get("unique_score"))}</strong></div>'
        '<div><small>现在是否值得投</small>'
        f'<strong>{e(decisions.get("final_state"))}</strong></div>'
        '</div>'
        f'<div class="plain-conclusion"><b>价格结论</b><span>{e(decisions.get("value_judgement"))}</span></div>'
        f'<div class="plain-conclusion risk"><b>首要错点</b><span>{e(primary_error)}</span></div>'
    )
    error_content = (
        '<div class="callout warn"><b>失效条件</b>'
        f'<ul>{error_items}</ul></div>'
        '<div class="plain-conclusion"><b>怎么处理</b>'
        '<span>确认首发、盘口换线或渠道赔率变化触发上述条件时，重新计算概率与EV；不沿用旧结论。</span></div>'
    )

    football_evidence = []
    for block in payload.get("evidence_chain") or []:
        if "足球" in str(block.get("title") or ""):
            football_evidence.extend(block.get("items") or [])
    script_items = "".join(f"<li>{e(item)}</li>" for item in football_evidence)
    script_content = fundamental_html
    if script_items:
        script_content += f'<div class="plain-conclusion"><b>比赛剧本</b><ul>{script_items}</ul></div>'

    market_content += timeline_svg(genuine_market_timeline(match))

    cards = [
        card("先看答案", "01", headline, True),
        card("模型给出的胜平负", "02", model_content),
        card("模型和市场哪里不一样", "03", divergence_content),
        card("盘口和赔率说明了什么", "04", market_content + rq_market_content),
        card("球队信息与比赛剧本", "05", script_content),
        card("进球数判断与敏感性", "06", totals_content, True),
        card("比分概率矩阵与首推比分", "07", score_content, True),
        card("EV与实时渠道复算", "08", betting_content, True),
        card("为什么这样判断", "09", evidence, True),
        card("可能判断错在哪里", "10", error_content, True),
    ]
    internal_audit = (
        '<details class="internal-audit">'
        '<summary>模型内部计算记录（默认收起）</summary>'
        '<p>这里保存数据完整性、基础内核、MBI、6D、规则扫描及原始市场明细，仅供复盘核查。</p>'
        '<div class="grid internal-grid">'
        + card("数据完整性", "A1", audit, True)
        + card("基础内核", "A2", base_audit_content, True)
        + card("MBI计算", "A3", mbi_content, True)
        + card("6D与规则扫描", "A4", risk_content, True)
        + card("交易所原始数据", "A5", trade_content)
        + card("公开市场原始数据", "A6", poly_content)
        + '</div></details>'
    )

    live_script = ""

    execution_label = "最终执行窗口" if report.get("final_execution_version") else "赛前分析报告"
    return f'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{e(match.get('home'))} vs {e(match.get('away'))} · {e(report.get('model_name'))} {e(report.get('model_version'))}</title>
<style>
:root{{--bg:#0a0811;--panel:#13101f;--panel2:#181326;--ink:#f7f2fa;--body:#c9c1d6;--mut:#8c839f;--line:rgba(255,255,255,.1);--accent:#ff3657;--accent2:#ff7189;--purple:#9b7fd0;--green:#39d6a0;--amber:#ffbd5c;--shadow:0 16px 50px rgba(0,0,0,.32)}}
*{{box-sizing:border-box}}html{{scroll-behavior:smooth}}body{{margin:0;background:radial-gradient(70% 42% at 50% -8%,rgba(255,54,87,.26),transparent 68%),linear-gradient(180deg,#171027 0,#0a0811 52%);color:var(--body);font-family:"Segoe UI","Microsoft YaHei",sans-serif;line-height:1.58;padding:32px}}.page{{max-width:1440px;margin:auto}}.hero{{position:relative;min-height:320px;border:1px solid rgba(255,255,255,.1);border-radius:22px;overflow:hidden;padding:42px;display:flex;flex-direction:column;justify-content:flex-end;background:linear-gradient(145deg,rgba(255,54,87,.18),transparent 38%),linear-gradient(25deg,#100b1b,#211232);box-shadow:var(--shadow)}}.hero:before{{content:"";position:absolute;inset:0;background:linear-gradient(135deg,transparent 42%,rgba(155,127,208,.12)),repeating-linear-gradient(118deg,transparent 0 72px,rgba(255,255,255,.025) 73px 74px);pointer-events:none}}.hero>*{{position:relative}}.eyebrow{{color:var(--accent2);font-size:12px;letter-spacing:.28em;font-weight:800;overflow-wrap:anywhere}}h1{{margin:14px 0 6px;color:var(--ink);font-size:clamp(34px,5vw,68px);line-height:1.04;letter-spacing:.03em;overflow-wrap:anywhere}}h1 span{{color:var(--accent);font-weight:300;margin:0 .22em}}.hero-sub{{color:var(--mut);font-size:14px}}.chips{{display:flex;gap:10px;flex-wrap:wrap;margin-top:22px}}.chip{{max-width:100%;padding:7px 11px;border:1px solid var(--line);border-radius:8px;background:rgba(255,255,255,.055);font-size:12px;overflow-wrap:anywhere}}.chip b{{color:var(--ink)}}.grid{{display:grid;grid-template-columns:repeat(12,minmax(0,1fr));gap:20px;margin-top:24px}}.card{{grid-column:span 6;background:linear-gradient(180deg,rgba(255,255,255,.035),rgba(255,255,255,.018));border:1px solid var(--line);border-radius:16px;padding:22px;box-shadow:0 8px 28px rgba(0,0,0,.16);overflow:hidden}}.card.full{{grid-column:span 12}}.card-title{{display:flex;align-items:center;gap:11px;margin-bottom:16px}}.card-title .ico{{width:32px;height:32px;border:1px solid rgba(255,54,87,.45);border-radius:8px;display:grid;place-items:center;background:rgba(255,54,87,.1);color:var(--accent2);font-size:11px;font-weight:800}}h2{{margin:0;color:var(--ink);font-size:16px}}h3{{color:var(--accent2);font-size:14px;margin:0 0 8px}}.table-wrap{{overflow:auto;border-radius:10px;border:1px solid rgba(255,255,255,.06)}}table{{width:100%;border-collapse:collapse;font-size:13px;min-width:520px}}th,td{{padding:10px 11px;border-bottom:1px solid rgba(255,255,255,.07);text-align:center}}th{{color:var(--mut);background:rgba(255,255,255,.035);font-size:11px;letter-spacing:.04em}}td:first-child{{text-align:left;color:#ded7e8}}tr:last-child td{{border-bottom:0}}tr:hover td{{background:rgba(255,54,87,.045)}}.empty{{color:var(--mut)!important;text-align:center!important}}.badge{{display:inline-flex;padding:4px 9px;border-radius:999px;border:1px solid var(--line);font-size:11px;font-weight:700}}.b-good{{color:var(--green);border-color:rgba(57,214,160,.4)}}.b-mid{{color:var(--mut)}}.b-warn{{color:var(--amber);border-color:rgba(255,189,92,.42)}}.callout{{display:flex;gap:12px;align-items:flex-start;margin-top:14px;border:1px solid rgba(255,54,87,.32);border-radius:11px;padding:14px;background:rgba(255,54,87,.055)}}.callout b{{color:var(--accent2);white-space:nowrap}}.callout span{{color:var(--ink)}}.callout ul{{margin:0}}.callout.warn{{border-color:rgba(255,189,92,.32);background:rgba(255,189,92,.045)}}.callout.warn b{{color:var(--amber)}}ul{{margin:0;padding-left:18px}}li{{margin:4px 0}}.prob-bars{{display:grid;gap:10px;margin-top:16px}}.prob-row{{display:grid;grid-template-columns:42px 1fr 58px;gap:10px;align-items:center;font-size:12px}}.prob-row b{{color:var(--ink);text-align:right}}.prob-track{{height:8px;background:rgba(255,255,255,.07);border-radius:999px;overflow:hidden}}.prob-track i{{display:block;height:100%;border-radius:999px}}.kpis{{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-top:14px}}.kpi,.money-grid>div,.verdict-grid>div,.decision-strip>div{{border:1px solid var(--line);border-radius:11px;padding:15px;background:rgba(255,255,255,.025)}}.kpi span,.money-grid b,.verdict-grid b,.decision-strip b{{display:block;color:var(--ink);font-size:21px}}.kpi small,.money-grid small,.verdict-grid small,.decision-strip small{{color:var(--mut);font-size:11px}}.status-line{{display:flex;justify-content:flex-end}}.empty-panel{{border:1px dashed rgba(255,255,255,.14);border-radius:11px;padding:30px;text-align:center;color:var(--mut)}}.fact{{display:flex;justify-content:space-between;gap:20px;border-bottom:1px solid var(--line);padding:10px}}.fact b{{color:var(--mut)}}.fact span{{color:var(--ink);text-align:right}}.decision-strip{{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-top:14px}}.decision-strip .accent{{border-color:rgba(255,54,87,.46);background:rgba(255,54,87,.07)}}.decision-strip .accent b{{color:var(--accent2)}}.verdict-grid,.money-grid{{display:grid;grid-template-columns:repeat(4,1fr);gap:10px}}.verdict-grid b{{font-size:16px;margin-top:6px}}.money-grid{{margin-bottom:14px}}.money-grid b{{font-size:18px;margin-top:5px}}.lock-rule{{margin-top:14px;padding:12px 14px;border-radius:10px;background:rgba(255,54,87,.07);border:1px solid rgba(255,54,87,.35);color:var(--accent2);font-weight:700}}.evidence-grid{{display:grid;grid-template-columns:repeat(3,1fr);gap:20px}}.footer{{margin:28px 0 8px;padding:18px 4px 0;border-top:1px solid var(--line);color:var(--mut);font-size:12px}}.footer b{{color:var(--body)}}
.decision-strip em{{display:block;color:var(--amber);font-size:11px;font-style:normal;margin-top:8px;line-height:1.45}}.primary-with-risk{{display:grid;grid-template-columns:1fr 1fr;gap:12px}}.answer-banner{{display:grid;grid-template-columns:1.15fr 1fr 1.25fr;gap:12px}}.answer-banner>div{{border:1px solid rgba(255,54,87,.34);border-radius:13px;padding:18px;background:linear-gradient(145deg,rgba(255,54,87,.09),rgba(155,127,208,.04))}}.answer-banner small{{display:block;color:var(--mut);font-size:11px;margin-bottom:8px}}.answer-banner strong{{display:block;color:var(--ink);font-size:18px;line-height:1.42}}.plain-conclusion{{display:flex;gap:14px;align-items:flex-start;margin-top:14px;padding:15px 16px;border:1px solid var(--line);border-radius:12px;background:rgba(255,255,255,.025)}}.plain-conclusion>b{{flex:0 0 auto;color:var(--accent2)}}.plain-conclusion span{{color:var(--ink)}}.plain-conclusion.risk{{border-color:rgba(255,189,92,.35);background:rgba(255,189,92,.045)}}.plain-conclusion.risk>b{{color:var(--amber)}}.subhead{{margin-top:20px}}.internal-audit{{margin-top:24px;border:1px solid rgba(255,255,255,.08);border-radius:14px;background:rgba(255,255,255,.018);color:var(--mut)}}.internal-audit>summary{{cursor:pointer;padding:15px 18px;color:var(--mut);font-size:12px;user-select:none}}.internal-audit>p{{margin:0;padding:0 18px;font-size:12px}}.internal-audit .internal-grid{{padding:0 18px 18px;margin-top:14px}}.internal-audit .card{{box-shadow:none}} 
.interval-panel{{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-top:16px}}.interval-panel>div{{border:1px solid var(--line);border-radius:11px;padding:15px;background:rgba(255,255,255,.025)}}.interval-panel>div.accent{{border-color:rgba(57,214,160,.4);background:rgba(57,214,160,.055)}}.interval-panel small,.live-values small,.live-head small{{display:block;color:var(--mut);font-size:11px}}.interval-panel b{{display:block;color:var(--ink);font-size:22px;margin:3px 0}}.interval-panel em{{color:var(--mut);font-size:11px;font-style:normal}}.method-note{{color:var(--mut);font-size:11px;margin:10px 0 0}}.gap-pos{{color:var(--green);font-weight:800}}.gap-neg{{color:var(--amber);font-weight:800}}.gap-flat{{color:var(--mut);font-weight:800}}
.heatmap .table-wrap{{border:0;overflow:auto}}.heatmap table{{min-width:680px;border-collapse:separate;border-spacing:6px}}.heatmap th,.heatmap td{{border:0;padding:0;background:transparent!important}}.heatmap td:first-child{{text-align:center}}.heat-axis{{display:grid;place-items:center;min-height:58px;color:var(--mut)}}.heat-cell{{display:grid;place-items:center;min-height:58px;border:1px solid rgba(255,255,255,.08);border-radius:8px;color:var(--ink)}}.heat-cell b{{font-size:13px}}.heat-cell small{{color:#f8eaf0;font-size:10px}}.heat-title{{color:var(--mut);font-size:11px;margin-bottom:8px}}
.timeline{{margin-top:18px;border:1px solid var(--line);border-radius:12px;padding:14px;background:rgba(255,255,255,.02)}}.timeline-head{{display:flex;justify-content:space-between;gap:12px;align-items:center}}.timeline-head b{{color:var(--ink)}}.timeline-head span{{color:var(--mut);font-size:11px}}.timeline svg{{display:block;width:100%;margin-top:8px}}
.live-reprice{{margin-bottom:18px;border:1px solid rgba(57,214,160,.34);border-radius:13px;padding:18px;background:linear-gradient(145deg,rgba(57,214,160,.055),rgba(155,127,208,.035))}}.live-head{{display:flex;align-items:center;justify-content:space-between;gap:15px}}.live-head b{{display:block;color:var(--ink);font-size:17px;margin-top:3px}}.live-dot{{display:inline-flex;padding:5px 10px;border-radius:999px;font-size:11px;font-weight:800;border:1px solid var(--line)}}.live-dot.waiting{{color:var(--amber);border-color:rgba(255,189,92,.38)}}.live-dot.connected{{color:var(--purple);border-color:rgba(155,127,208,.45)}}.live-dot.pass{{color:var(--green);border-color:rgba(57,214,160,.45)}}.live-values{{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-top:14px}}.live-values>div{{border:1px solid var(--line);border-radius:10px;padding:13px;background:rgba(0,0,0,.12)}}.live-values b{{display:block;color:var(--ink);font-size:17px;margin-top:4px}}.live-time{{color:var(--mut);font-size:10px;margin-top:8px}}
.live-action,.back-link{{display:inline-flex;align-items:center;width:max-content;margin:12px 0;padding:8px 12px;border:1px solid rgba(155,127,208,.45);border-radius:9px;color:#d8caef;text-decoration:none;background:rgba(155,127,208,.08)}}.live-action:hover,.back-link:hover{{border-color:var(--accent2);color:var(--accent2)}}.fact span a{{display:block;margin-top:4px;color:var(--purple);font-size:11px;text-decoration:none}}
@media(max-width:900px){{body{{padding:16px}}.hero{{min-height:280px;padding:28px 22px}}.card,.card.full{{grid-column:span 12}}.kpis,.verdict-grid,.money-grid{{grid-template-columns:repeat(2,1fr)}}.decision-strip,.evidence-grid,.primary-with-risk,.answer-banner{{grid-template-columns:1fr}}}}
@media(max-width:900px){{.interval-panel,.live-values{{grid-template-columns:repeat(2,1fr)}}}}
@media(max-width:520px){{body{{padding:10px}}.hero{{border-radius:15px}}h1{{font-size:34px;display:flex;flex-direction:column;gap:4px}}h1 span{{font-size:18px;margin:4px 0;letter-spacing:.2em}}.card{{padding:16px;border-radius:13px}}.kpis,.verdict-grid,.money-grid,.interval-panel,.live-values{{grid-template-columns:1fr}}.chips{{gap:6px}}.chip{{flex:1 1 140px;font-size:11px}}.plain-conclusion{{display:block}}.plain-conclusion>b{{display:block;margin-bottom:6px}}.timeline-head,.live-head{{align-items:flex-start;flex-direction:column}}}}
@media print{{body{{background:#fff;color:#222;padding:0}}.hero,.card{{box-shadow:none;break-inside:avoid}}}}
</style></head><body><main class="page"><a class="back-link" href="../../match_workspace/latest.html">← 返回赛事总览</a>
<header class="hero"><div class="eyebrow">{e(str(report.get('model_name', 'Football Betting OneShot')).upper())} · {e(report.get('model_version'))} · MARKET INTELLIGENCE</div>
<h1>{e(match.get('home'))}<span>VS</span>{e(match.get('away'))}</h1>
<div class="hero-sub">{e(report.get('report_type'))} · {e(execution_label)} · 90分钟含伤停，不含加时与点球</div>
<div class="chips"><span class="chip">赛事 <b>{e(match.get('competition'))}</b></span><span class="chip">竞彩日 <b>{e(match.get('business_date'))}</b></span><span class="chip">开球 <b>{e(match.get('kickoff_local'))}</b></span><span class="chip">编号 <b>{e(match.get('match_num'))}</b></span><span class="chip">快照 <b>{e(report.get('snapshot_timestamp'))}</b></span></div></header>
<div class="grid">{"".join(cards)}</div>
{internal_audit}
<footer class="footer"><b>{e(report.get('model_name'))} {e(report.get('model_version'))}</b> · 数据批次 {e(report.get('data_run_id'))}</footer>
</main>{live_script}</body></html>'''


def main() -> int:
    parser = argparse.ArgumentParser(description="生成Football Betting OneShot可视化HTML报告")
    parser.add_argument("--fetch-manifest", required=True, help="抓取批次manifest路径")
    parser.add_argument("--analysis-json", help="可选：完整模型分析结果JSON")
    parser.add_argument("--state", default=str(PROJECT_ROOT / "05_RUNTIME_STATE.json"), help="运行状态JSON")
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT), help="报告输出根目录")
    parser.add_argument(
        "--profile-output-root",
        default=str(DEFAULT_PROFILE_OUTPUT_ROOT),
        help="分析结果到悬浮窗配置的输出根目录",
    )
    args = parser.parse_args()

    manifest_path = Path(args.fetch_manifest).resolve()
    manifest = load_json(manifest_path)
    official_path = source_file(manifest, "sporttery", PROJECT_ROOT)
    trade_path = source_file(manifest, "500_trade", PROJECT_ROOT)
    deep_path = deep_file(manifest, PROJECT_ROOT)
    polymarket_path = source_file(manifest, "polymarket", PROJECT_ROOT)
    official = load_json(official_path) if official_path and official_path.exists() else {"matches": []}
    trade = load_json(trade_path) if trade_path and trade_path.exists() else {"matches": []}
    deep = load_json(deep_path) if deep_path and deep_path.exists() else {}
    polymarket = load_json(polymarket_path) if polymarket_path and polymarket_path.exists() else {}
    state = load_json(Path(args.state))
    analysis = load_json(Path(args.analysis_json)) if args.analysis_json else None
    payload = build_payload(manifest, official, trade, deep, state, analysis, polymarket)

    stamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S")
    output_dir = Path(args.output_root) / stamp
    output_dir.mkdir(parents=True, exist_ok=False)
    match = payload["match"]
    base_name = f"{stamp}_{safe_name(match['home'])}_vs_{safe_name(match['away'])}_盘口解析"
    payload_path = output_dir / f"{base_name}.json"
    report_path = output_dir / f"{base_name}.html"
    payload["report"]["live_ev_profile_publication"] = publish_live_ev_profiles(
        payload,
        output_root=Path(args.profile_output_root),
        report_payload_path=payload_path,
    )
    payload_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    report_path.write_text(render(payload), encoding="utf-8")
    schedule_path = None
    schedule_error = None
    workflow_path = None
    try:
        schedule_path, _schedule = create_schedule(payload_path)
        workflow_path, _due_times = sync_postmatch_workflow(
            datetime.now().astimezone(SHANGHAI),
            PROJECT_ROOT / "data" / "postmatch_automation" / "schedules",
        )
    except (OSError, ValueError, json.JSONDecodeError) as error:
        schedule_error = str(error)
    print(json.dumps({
        "report": str(report_path),
        "payload": str(payload_path),
        "report_type": payload["report"]["report_type"],
        "final_execution_version": payload["report"]["final_execution_version"],
        "postmatch_schedule": str(schedule_path) if schedule_path else None,
        "postmatch_workflow": str(workflow_path) if workflow_path else None,
        "postmatch_schedule_error": schedule_error,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
