#!/usr/bin/env python3
"""Compute an auditable, conservative market-intelligence panel.

The calculator never promotes degraded approximations to formal MBI results.
Missing tier mappings, league DRI baselines, multi-frame price history or a
four-hour exchange baseline remain explicit blockers.
"""

from __future__ import annotations

import argparse
import json
import math
from datetime import datetime
from pathlib import Path
from statistics import fmean, pstdev

from market_history import load_history


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TIER_CONFIG = PROJECT_ROOT / "config" / "bookmaker_tiers.json"
OUTCOMES = ("home", "draw", "away")
OUTCOME_LABELS = {"home": "主胜", "draw": "平局", "away": "客胜"}


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _number(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def no_vig(odds: dict | None) -> dict | None:
    if not odds or not all(odds.get(key) for key in OUTCOMES):
        return None
    raw = {key: 1 / float(odds[key]) for key in OUTCOMES}
    total = sum(raw.values())
    return {key: raw[key] / total for key in OUTCOMES}


def shin_no_vig(odds: dict | None) -> dict | None:
    """Apply the upstream KB-1 practical Shin approximation and normalize."""
    if not odds or not all(odds.get(key) for key in OUTCOMES):
        return None
    overround = sum(1 / float(odds[key]) for key in OUTCOMES)
    z = max(0.0, (overround - 1.0) / 2.0)
    raw = {
        key: (1.0 - z) / ((1.0 - z) * float(odds[key]) + z)
        for key in OUTCOMES
    }
    total = sum(raw.values())
    return {
        "method": "shin_practical_approximation",
        "z": z,
        "overround": overround,
        "payout_rate": 1.0 / overround if overround > 0 else None,
        "probabilities": {key: raw[key] / total for key in OUTCOMES},
    }


def fixed_odds_scenario_profit(stakes: dict | None, odds: dict | None) -> dict | None:
    """Calculate single-market operator P/L only from actual outcome stakes and decimal odds."""
    if not stakes or not odds or not all(key in stakes and key in odds for key in OUTCOMES):
        return None
    stake_values = {key: float(stakes[key]) for key in OUTCOMES}
    odds_values = {key: float(odds[key]) for key in OUTCOMES}
    if any(value < 0 for value in stake_values.values()) or any(value <= 1 for value in odds_values.values()):
        raise ValueError("stakes must be non-negative and decimal odds must be greater than 1")
    total_stakes = sum(stake_values.values())
    if total_stakes <= 0:
        raise ValueError("total stakes must be positive")
    gross_return = {
        key: stake_values[key] * odds_values[key]
        for key in OUTCOMES
    }
    profit = {
        key: total_stakes - gross_return[key]
        for key in OUTCOMES
    }
    return {
        "scope": "single_fixed_odds_market_before_hedges_costs_and_cross_market_exposure",
        "stake_source_requirement": "actual_stakes_not_implied_probability_or_audience_poll",
        "total_stakes": total_stakes,
        "gross_return_by_outcome": gross_return,
        "operator_profit_by_outcome": profit,
        "operator_margin_on_stakes_by_outcome": {
            key: profit[key] / total_stakes for key in OUTCOMES
        },
    }


def mean_outcomes(rows: list[dict], field: str) -> dict | None:
    valid = [row.get(field) for row in rows if isinstance(row.get(field), dict)]
    if not valid:
        return None
    result = {}
    for outcome in OUTCOMES:
        values = [float(item[outcome]) for item in valid if item.get(outcome)]
        result[outcome] = fmean(values) if values else None
    return result if all(value is not None for value in result.values()) else None


def tier_index(config: dict) -> tuple[dict[int, str], dict[str, float]]:
    index = {}
    weights = {}
    for tier, definition in config["tiers"].items():
        weights[tier] = float(definition["weight"])
        for cid in definition.get("members", {}):
            index[int(cid)] = tier
    return index, weights


def tier_panel(bookmakers: list[dict], config: dict) -> dict:
    index, weights = tier_index(config)
    grouped = {tier: [] for tier in config["tiers"]}
    unmapped = []
    for bookmaker in bookmakers:
        tier = index.get(int(bookmaker.get("cid") or 0))
        if tier:
            grouped[tier].append(bookmaker)
        else:
            unmapped.append({"cid": bookmaker.get("cid"), "name": bookmaker.get("name")})
    tiers = {}
    for tier, rows in grouped.items():
        tiers[tier] = {
            "weight": weights[tier],
            "company_count": len(rows),
            "cids": [row.get("cid") for row in rows],
            "open_mean": mean_outcomes(rows, "spf_open"),
            "current_mean": mean_outcomes(rows, "spf_current"),
        }
    return {"tiers": tiers, "mapped_count": sum(len(rows) for rows in grouped.values()), "unmapped": unmapped}


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _history_series(history: list[dict], cid: int, outcome: str) -> list[tuple[datetime, float]]:
    series = []
    for snapshot in history:
        timestamp = _parse_time(snapshot.get("market_time") or snapshot.get("recorded_at"))
        bookmaker = next((item for item in snapshot.get("euro", []) if int(item.get("cid") or 0) == cid), None)
        current = bookmaker.get("current") if bookmaker else None
        if timestamp and isinstance(current, dict) and current.get(outcome):
            series.append((timestamp, float(current[outcome])))
    return sorted(series, key=lambda item: item[0])


def scs_panel(bookmakers: list[dict], config: dict, history: list[dict] | None = None) -> dict:
    history = history or []
    index, weights = tier_index(config)
    tier_scores = {tier: {outcome: [] for outcome in OUTCOMES} for tier in weights}
    used = 0
    for bookmaker in bookmakers:
        tier = index.get(int(bookmaker.get("cid") or 0))
        opening = bookmaker.get("spf_open")
        current = bookmaker.get("spf_current")
        if not tier or not isinstance(opening, dict) or not isinstance(current, dict):
            continue
        used += 1
        for outcome in OUTCOMES:
            open_price = float(opening[outcome])
            current_price = float(current[outcome])
            delta = current_price - open_price
            series = _history_series(history, int(bookmaker.get("cid") or 0), outcome)
            sigma = pstdev([value for _, value in series]) if len(series) >= 3 else 0.0
            noise = max(0.02 * open_price, 1.5 * sigma)
            last_change_time = None
            for (previous_time, previous), (current_time, observed) in zip(series, series[1:]):
                if observed != previous:
                    last_change_time = current_time
            latest_time = series[-1][0] if series else None
            age_hours = max(0.0, (latest_time - last_change_time).total_seconds() / 3600) if latest_time and last_change_time else 0.0
            time_decay = math.exp(-age_hours / 24)
            if abs(delta) < noise:
                signal = 0.0
            else:
                direction = 1.0 if delta < 0 else -1.0
                magnitude = min(abs(delta / open_price) / 0.10, 1.0)
                signal = direction * magnitude * time_decay
            tier_scores[tier][outcome].append(signal)

    per_outcome = {}
    for outcome in OUTCOMES:
        weighted = 0.0
        present_weight = 0.0
        layer_values = {}
        for tier, weight in weights.items():
            values = tier_scores[tier][outcome]
            layer_value = fmean(values) if values else None
            layer_values[tier] = layer_value
            if layer_value is not None:
                weighted += weight * layer_value
                present_weight += weight
        per_outcome[outcome] = {
            "signed_score": weighted / present_weight if present_weight else None,
            "tier_scores": layer_values,
        }
    return {
        "calculation_status": "degraded",
        "reason": "已使用可用历史快照估算σ和时间衰减；历史不足24小时且公司分层未全映射",
        "mapped_company_count": used,
        "history_snapshot_count": len(history),
        "per_outcome": per_outcome,
    }


def dri_panel(ouzhi: dict, league_median: float | None = None) -> dict:
    dispersion = ouzhi.get("summary", {}).get("dispersion_current") or ouzhi.get("summary", {}).get("dispersion")
    if not dispersion:
        return {"calculation_status": "not_run", "reason": "页面离散值缺失"}
    raw = float(dispersion["home"]) * 0.5 + float(dispersion["draw"]) * 0.3 + float(dispersion["away"]) * 0.2
    calibrated = raw / league_median * 30 if league_median else None
    value_for_band = calibrated if calibrated is not None else raw
    if value_for_band < 12:
        risk = "tight"
    elif value_for_band <= 35:
        risk = "normal"
    elif value_for_band <= 60:
        risk = "high"
    else:
        risk = "extreme"
    return {
        "calculation_status": "completed" if calibrated is not None else "degraded",
        "dispersion": dispersion,
        "raw": raw,
        "league_median": league_median,
        "calibrated": calibrated,
        "risk_band": risk,
        "reason": None if calibrated is not None else "缺联赛500场以上历史中位DRI，风险档仅为未校准观察",
    }


def water_flow_panel(companies: list[dict]) -> dict:
    same_line = []
    home_in = 0
    home_out = 0
    neutral = 0
    for company in companies:
        if company.get("current_handicap") != company.get("open_handicap"):
            continue
        required = ("current_water_home", "current_water_away", "open_water_home", "open_water_away")
        if any(company.get(key) is None for key in required):
            continue
        home_change = float(company["current_water_home"]) - float(company["open_water_home"])
        away_change = float(company["current_water_away"]) - float(company["open_water_away"])
        if home_change < 0 or away_change > 0:
            direction = "home_in"
            home_in += 1
        elif home_change > 0 or away_change < 0:
            direction = "home_out"
            home_out += 1
        else:
            direction = "neutral"
            neutral += 1
        same_line.append({"cid": company.get("cid"), "direction": direction, "home_change": home_change, "away_change": away_change})
    count = len(same_line)
    return {
        "calculation_status": "degraded" if count else "not_run",
        "same_line_sources": count,
        "home_in": home_in,
        "home_out": home_out,
        "neutral": neutral,
        "flow_ratio": abs(home_in - home_out) / count if count else None,
        "direction": "home" if home_in > home_out else "away" if home_out > home_in else "neutral",
        "sources": same_line,
        "reason": "缺多帧相关系数，尚未执行同源白标聚类去重",
    }


def nowscore_trend_panel(company_trends: list[dict]) -> dict:
    """Summarize bookmaker price histories; these are not transaction volumes."""
    markets = {"asian": [], "total": [], "one_x_two": []}
    first_moves: list[dict] = []
    direction_counts = {
        "one_x_two_home": {"shortened": 0, "lengthened": 0, "flat": 0},
        "asian_home": {"strengthened": 0, "weakened": 0, "flat": 0},
        "total": {"up": 0, "down": 0, "flat": 0},
    }
    for company in company_trends or []:
        for market, target in markets.items():
            rows = [row for row in ((company.get("markets") or {}).get(market) or []) if row.get("captured_at")]
            rows.sort(key=lambda row: row["captured_at"])
            if not rows:
                continue
            target.append({
                "source_company_id": company.get("source_company_id"), "name": company.get("name"),
                "snapshot_count": len(rows), "first_at": rows[0]["captured_at"], "last_at": rows[-1]["captured_at"],
            })
            if market == "one_x_two" and rows[0].get("home") is not None and rows[-1].get("home") is not None:
                delta = float(rows[-1]["home"]) - float(rows[0]["home"])
                direction_counts["one_x_two_home"]["shortened" if delta < -0.005 else "lengthened" if delta > 0.005 else "flat"] += 1
            elif market == "asian" and rows[0].get("line_number") is not None and rows[-1].get("line_number") is not None:
                delta = float(rows[-1]["line_number"]) - float(rows[0]["line_number"])
                direction_counts["asian_home"]["strengthened" if delta < -0.01 else "weakened" if delta > 0.01 else "flat"] += 1
            elif market == "total" and rows[0].get("line_number") is not None and rows[-1].get("line_number") is not None:
                delta = float(rows[-1]["line_number"]) - float(rows[0]["line_number"])
                direction_counts["total"]["up" if delta > 0.01 else "down" if delta < -0.01 else "flat"] += 1
            comparable = ("home_water", "line_number", "away_water") if market == "asian" else (
                ("over", "line_number", "under") if market == "total" else ("home", "draw", "away")
            )
            previous = rows[0]
            for row in rows[1:]:
                if any(row.get(key) != previous.get(key) for key in comparable):
                    first_moves.append({
                        "market": market, "source_company_id": company.get("source_company_id"),
                        "name": company.get("name"), "captured_at": row["captured_at"],
                    })
                    break
                previous = row
    # A provider can move several market families at the same minute.  The
    # user-facing report needs one provider event, not duplicate company rows.
    deduplicated_moves: dict[object, dict] = {}
    for move in sorted(first_moves, key=lambda row: row["captured_at"]):
        key = move.get("source_company_id") or move.get("name")
        existing = deduplicated_moves.get(key)
        if existing is None:
            deduplicated_moves[key] = {**move, "markets": [move.get("market")]}
        elif move.get("market") not in existing["markets"]:
            existing["markets"].append(move.get("market"))
    first_moves = sorted(deduplicated_moves.values(), key=lambda row: row["captured_at"])
    snapshot_count = sum(item["snapshot_count"] for rows in markets.values() for item in rows)
    company_count = len({item["source_company_id"] for rows in markets.values() for item in rows})
    return {
        "calculation_status": "completed" if company_count >= 3 and snapshot_count >= 12 else "degraded" if snapshot_count else "not_run",
        "company_count": company_count, "snapshot_count": snapshot_count,
        "markets": markets, "first_moves": first_moves[:12],
        "direction_counts": direction_counts,
        "semantic_scope": "bookmaker_price_and_line_history_not_transaction_flow",
        "reason": None if company_count >= 3 and snapshot_count >= 12 else "独立公司历史轨迹不足",
    }


def lead_lag_panel(companies: list[dict], company_trends: list[dict] | None = None) -> dict:
    trend_panel = nowscore_trend_panel(company_trends or [])
    if trend_panel.get("calculation_status") == "completed":
        return {
            "calculation_status": "completed",
            "priority": [1055, 3, 5],
            "observed": trend_panel.get("first_moves") or [],
            "chain": trend_panel.get("first_moves") or [],
            "company_count": trend_panel.get("company_count"),
            "snapshot_count": trend_panel.get("snapshot_count"),
            "reason": None,
        }
    priority = [1055, 3, 5]
    observed = []
    for cid in priority:
        item = next((company for company in companies if int(company.get("cid") or 0) == cid), None)
        if item and item.get("change_time"):
            observed.append({
                "cid": cid,
                "name": item.get("name"),
                "change_time": item.get("change_time"),
                "open_handicap": item.get("open_handicap"),
                "current_handicap": item.get("current_handicap"),
            })
    return {
        "calculation_status": "degraded" if observed else "not_run",
        "priority": priority,
        "observed": observed,
        "chain": None,
        "reason": "页面只提供各公司最近一次变动时间，无法证明完整的首次领涨—2小时/4小时跟随链",
    }


def exchange_panel(touzhu: dict, consensus_probability: dict | None, history: list[dict] | None = None) -> dict:
    history = history or []
    betfair = touzhu.get("betfair") or {}
    metadata = touzhu.get("betfair_metadata") or {}
    transactions = touzhu.get("pl_flow", {}).get("transactions", [])
    if not betfair or not consensus_probability:
        return {"calculation_status": "not_run", "reason": "必发或市场概率缺失"}
    gaps = {}
    for outcome in OUTCOMES:
        item = betfair.get(outcome) or {}
        volume_pct = item.get("volume_ratio_pct")
        gaps[outcome] = None if volume_pct is None else float(volume_pct) - consensus_probability[outcome] * 100
    current_total = sum(float((betfair.get(outcome) or {}).get("betfair_volume") or 0) for outcome in OUTCOMES)
    historical_exchange = []
    for snapshot in history:
        timestamp = _parse_time(snapshot.get("market_time") or snapshot.get("recorded_at"))
        panel = snapshot.get("exchange", {}).get("betfair")
        if timestamp and panel:
            historical_exchange.append((timestamp, panel))
    historical_exchange.sort(key=lambda item: item[0])
    current_time = historical_exchange[-1][0] if historical_exchange else None
    prior_four_hours = [item for item in historical_exchange[:-1] if current_time and 0 < (current_time - item[0]).total_seconds() <= 4 * 3600]
    prior_reference = prior_four_hours[0][1] if prior_four_hours else (historical_exchange[-2][1] if len(historical_exchange) >= 2 else None)
    growth = {}
    if prior_reference:
        for outcome in OUTCOMES:
            previous = float((prior_reference.get(outcome) or {}).get("betfair_volume") or 0)
            current = float((betfair.get(outcome) or {}).get("betfair_volume") or 0)
            growth[outcome] = current / previous if previous > 0 else None
    enough_baseline = len(prior_four_hours) >= 3
    return {
        "calculation_status": "completed" if current_total > 50000 and enough_baseline else "degraded",
        "volume_minus_market_probability_pp": gaps,
        "transaction_count": len(transactions),
        "total_volume": current_total,
        "history_snapshot_count": len(historical_exchange),
        "prior_four_hour_snapshot_count": len(prior_four_hours),
        "volume_growth_ratio": growth,
        "volume_scope": metadata.get("volume_scope", "unverified_visible_page_scope"),
        "page_simulated_pl_signal_usage": "display_only_not_direction_or_ev",
        "reason": None if enough_baseline else "历史已接入，但前4小时内不足3个独立快照，量价四象限仍降级",
    }


def _direction_ratio(positive: int, negative: int) -> float | None:
    total = positive + negative
    return (positive - negative) / total if total else None


def _model_leader(probabilities: dict | None) -> str | None:
    valid = {key: float(value) for key, value in (probabilities or {}).items() if key in OUTCOMES and value is not None}
    return max(valid, key=valid.get) if valid else None


def interpret_market_intent(
    deep: dict,
    intelligence: dict,
    model_probabilities: dict | None = None,
    checkpoint_stage: str | None = None,
) -> dict:
    """Explain price pressure, likely operator purpose and model impact.

    Bookmaker quotes are price-pressure evidence, never transaction flow.
    Purpose labels are deterministic inferences with explicit confidence and
    are not claims about a bookmaker's private intention.
    """
    modules = intelligence.get("modules") or {}
    trends = modules.get("nowscore_trends") or {}
    counts = trends.get("direction_counts") or {}
    euro = counts.get("one_x_two_home") or {}
    asian = counts.get("asian_home") or {}
    totals = counts.get("total") or {}
    euro_ratio = _direction_ratio(int(euro.get("shortened") or 0), int(euro.get("lengthened") or 0))
    asian_ratio = _direction_ratio(int(asian.get("strengthened") or 0), int(asian.get("weakened") or 0))

    water = modules.get("water_flow") or {}
    water_ratio = float(water.get("flow_ratio") or 0)
    water_signed = water_ratio if water.get("direction") == "home" else -water_ratio if water.get("direction") == "away" else 0.0
    scs_home = (((modules.get("scs") or {}).get("per_outcome") or {}).get("home") or {})
    sharp_signal = _number(((scs_home.get("tier_scores") or {}).get("sharp")))

    components: list[tuple[str, float]] = []
    if euro_ratio is not None:
        components.append(("多公司欧赔", euro_ratio))
    if asian_ratio is not None:
        components.append(("亚洲让球", asian_ratio))
    if water.get("same_line_sources"):
        components.append(("同盘水位", water_signed))
    if sharp_signal is not None:
        components.append(("Sharp层", sharp_signal))
    weighted_score = (
        (0.35 * (euro_ratio or 0.0))
        + (0.30 * (asian_ratio or 0.0))
        + (0.15 * water_signed)
        + (0.20 * (sharp_signal or 0.0))
    )
    direction = "home" if weighted_score >= 0.18 else "away" if weighted_score <= -0.18 else "neutral"
    direction_label = {"home": "主队", "away": "客队", "neutral": "两侧未拉开"}[direction]
    directional_components = [value for _, value in components if abs(value) >= 0.18]
    aligned_components = sum(1 for value in directional_components if (value > 0) == (weighted_score > 0))
    disagreement = any(value > 0.18 for _, value in components) and any(value < -0.18 for _, value in components)

    exchange = modules.get("exchange") or {}
    exchange_gaps = {
        key: _number(value)
        for key, value in (exchange.get("volume_minus_market_probability_pp") or {}).items()
        if key in OUTCOMES and _number(value) is not None
    }
    exchange_direction = max(exchange_gaps, key=exchange_gaps.get) if exchange_gaps else None
    exchange_gap = exchange_gaps.get(exchange_direction) if exchange_direction else None
    exchange_confirmed = (
        exchange_direction in ("home", "away")
        and direction == exchange_direction
        and exchange_gap is not None and exchange_gap >= 3.0
    )
    exchange_conflict = (
        exchange_direction in ("home", "away")
        and direction in ("home", "away")
        and direction != exchange_direction
        and exchange_gap is not None and exchange_gap >= 3.0
    )

    if direction == "neutral":
        purpose = "当前更像分散调价和平衡风险，尚没有足够证据说明机构在主动表达单边方向。"
    elif exchange_confirmed and aligned_components >= 2:
        purpose = f"多层价格与交易所成交共同指向{direction_label}，更像主动价格发现并降低该方向潜在赔付风险。"
    elif disagreement or exchange_conflict:
        purpose = "Sharp层、广泛市场或交易所没有同向，较可能是机构在不同客群间平衡受注，也存在用价格吸引对手盘的可能。"
    elif aligned_components >= 2:
        purpose = f"欧赔、让球或水位有至少两层同向，较像机构持续修正{direction_label}价格并控制同侧风险。"
    else:
        purpose = "目前只有单层报价偏移，更像常规风险平衡，不能据此认定专业资金已经完成方向选择。"

    late_stages = {"T-90M", "T-60M", "T-30M", "T-10M"}
    is_late = checkpoint_stage in late_stages
    confidence = "高" if exchange_confirmed and aligned_components >= 2 else "中" if aligned_components >= 2 and not disagreement else "低"
    leader = _model_leader(model_probabilities)
    if direction == "neutral" or leader is None:
        impact_code = "observe"
        model_impact = "市场方向尚未拉开，不改变模型主线，只保留观察。"
    elif direction == leader:
        impact_code = "confirm"
        model_impact = f"市场压力与模型{OUTCOME_LABELS[leader]}同向，{'临盘确认价值较高' if is_late else '可提高方向置信度，但距离临盘仍需复核'}；避免把同一市场信息重复计入概率。"
    elif leader == "draw":
        impact_code = "weaken"
        model_impact = f"市场正在偏向{direction_label}，削弱模型平局主线；{'临盘需暂停直接沿用原判断' if is_late and confidence == '高' else '暂记为反证，不自动改方向'}。"
    else:
        impact_code = "weaken"
        model_impact = f"市场压力与模型{OUTCOME_LABELS[leader]}相反，削弱原首推；{'临盘多源确认时应暂停沿用并重算' if is_late and confidence in ('高', '中') else '当前只降置信度，不凭一次调价反转'}。"

    if exchange.get("total_volume"):
        strongest = OUTCOME_LABELS.get(exchange_direction, "未知方向")
        money_flow = (
            f"交易所可见成交量约{float(exchange.get('total_volume')):,.0f}，成交占比相对市场概率最偏向{strongest}"
            f"（{exchange_gap:+.1f}个百分点）；{'与盘口压力互相确认' if exchange_confirmed else '与盘口压力存在分歧' if exchange_conflict else '尚未达到同向确认门槛'}。"
        )
    else:
        money_flow = f"没有可核验的交易所成交量；当前只能确认报价形成的{direction_label}价格压力，不能称为真实资金流。"

    market_pressure = (
        f"{trends.get('company_count', 0)}家公司、{trends.get('snapshot_count', 0)}条轨迹："
        f"主胜降赔{euro.get('shortened', 0)}家/升赔{euro.get('lengthened', 0)}家，"
        f"亚洲盘主队加强{asian.get('strengthened', 0)}家/减弱{asian.get('weakened', 0)}家，"
        f"大小球升盘{totals.get('up', 0)}家/降盘{totals.get('down', 0)}家。综合价格压力偏向{direction_label}。"
    )
    sharp_text = "Sharp层方向不足"
    if sharp_signal is not None:
        if sharp_signal >= 0.12:
            sharp_text = f"Pinnacle/bet365代表的Sharp层正在支持主队（强度{abs(sharp_signal):.2f}）"
        elif sharp_signal <= -0.12:
            sharp_text = f"Pinnacle/bet365代表的Sharp层正在削弱主队（强度{abs(sharp_signal):.2f}）"
        else:
            sharp_text = f"Pinnacle/bet365代表的Sharp层基本中性（强度{abs(sharp_signal):.2f}）"
    bookmaker_behaviour = f"{sharp_text}；目的推断：{purpose}可信度：{confidence}。"
    return {
        "market_pressure": market_pressure,
        "money_flow": money_flow,
        "bookmaker_behaviour": bookmaker_behaviour,
        "model_impact": model_impact,
        "direction": direction,
        "purpose": purpose,
        "confidence": confidence,
        "impact_code": impact_code,
        "late_market_weight": "high" if is_late else "normal",
        "actual_volume_available": bool(exchange.get("total_volume")),
        "semantic_scope": "purpose_is_model_inference_not_bookmaker_disclosure",
        "evidence": [{"name": name, "signed_home_support": round(value, 4)} for name, value in components],
    }


def kelly_panel(bookmakers: list[dict], config: dict) -> dict:
    """Aggregate bookmaker-page Kelly indices; this is not a bankroll Kelly fraction."""
    index, _ = tier_index(config)
    grouped = {tier: [] for tier in config["tiers"]}
    for bookmaker in bookmakers:
        tier = index.get(int(bookmaker.get("cid") or 0))
        if tier and isinstance(bookmaker.get("kelly_current"), dict):
            grouped[tier].append(bookmaker)
    tiers = {}
    for tier, rows in grouped.items():
        tiers[tier] = {"company_count": len(rows), "current_mean": mean_outcomes(rows, "kelly_current")}
    return {
        "calculation_status": "degraded",
        "tiers": tiers,
        "semantic_scope": "bookmaker_page_kelly_index_not_bankroll_kelly_fraction",
        "staking_usage": "forbidden",
        "reason": "三层页面凯利指数均值已算，但必须与Lead-Lag、水位流和必发共同验证；不得用于计算仓位",
    }


def analyze(deep: dict, tier_config: dict, league_median_dri: float | None = None, history: list[dict] | None = None) -> dict:
    history = history or []
    ouzhi = deep.get("ouzhi", {})
    bookmakers = ouzhi.get("bookmakers", [])
    summary = ouzhi.get("summary", {})
    # The executable model currently parses 30 bookmaker rows. The page footer
    # may aggregate a larger display set (currently 52), so do not mix that
    # footer average into the explicitly named 30-company consensus.
    consensus_open = mean_outcomes(bookmakers, "spf_open") or summary.get("avg_spf_open")
    consensus_current = mean_outcomes(bookmakers, "spf_current") or summary.get("avg_spf_current")
    consensus_probability = no_vig(consensus_current)
    shin = shin_no_vig(consensus_current)
    tiers = tier_panel(bookmakers, tier_config)
    scs = scs_panel(bookmakers, tier_config, history)
    dri = dri_panel(ouzhi, league_median_dri)
    nowscore_context = deep.get("nowscore_context") or deep.get("context") or ((deep.get("nowscore") or {}).get("context") or {})
    company_trends = nowscore_context.get("company_trends") or []
    trend_panel = nowscore_trend_panel(company_trends)
    lead_lag = lead_lag_panel(deep.get("yazhi", {}).get("companies", []), company_trends)
    water_flow = water_flow_panel(deep.get("yazhi", {}).get("companies", []))
    exchange = exchange_panel(deep.get("touzhu", {}), consensus_probability, history)
    kelly = kelly_panel(bookmakers, tier_config)
    tier_complete = not tiers["unmapped"] and not any(
        definition.get("expected_but_unconfirmed") for definition in tier_config["tiers"].values()
    )

    return {
        "generated_at": datetime.now().astimezone().isoformat(),
        "source_match_id": deep.get("shuju_id"),
        "source_fetched_at": deep.get("fetched_at"),
        "history_snapshot_count": len(history),
        "tier_config_version": tier_config.get("version"),
        "consensus": {
            "open": consensus_open,
            "current": consensus_current,
            "proportional_no_vig": consensus_probability,
            "shin": shin,
            "lowest_odds_direction": min(OUTCOMES, key=lambda key: consensus_current[key]) if consensus_current else None,
            "parsed_company_count": len(bookmakers),
            "page_footer_average": summary.get("avg_spf_current"),
        },
        "tiers": tiers,
        "modules": {
            "scs": scs,
            "dri": dri,
            "lead_lag": lead_lag,
            "nowscore_trends": trend_panel,
            "water_flow": water_flow,
            "exchange": exchange,
            "kelly": kelly,
        },
        "formal_mbi_status": "complete" if tier_complete and all(
            module.get("calculation_status") == "completed" for module in (scs, dri, lead_lag, water_flow, exchange, kelly)
        ) else "degraded",
        "formal_mbi_verdict": None,
        "blockers": [
            "部分博彩公司cid尚未完成三层归类",
            "SCS缺历史噪声和欧赔多帧时间衰减",
            "DRI缺联赛历史中位数校准",
            "Lead-Lag缺完整首次变动链",
            "水位流缺白标同源聚类",
            "必发缺4小时成交基线",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="计算多公司市场情报审计面板")
    parser.add_argument("--deep-json", required=True)
    parser.add_argument("--tier-config", default=str(DEFAULT_TIER_CONFIG))
    parser.add_argument("--league-median-dri", type=float)
    parser.add_argument("--history-jsonl")
    parser.add_argument("--output")
    args = parser.parse_args()

    history = load_history(Path(args.history_jsonl)) if args.history_jsonl else []
    result = analyze(load_json(Path(args.deep_json)), load_json(Path(args.tier_config)), args.league_median_dri, history)
    output = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(output, encoding="utf-8")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
