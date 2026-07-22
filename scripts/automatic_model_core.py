#!/usr/bin/env python3
"""Deterministic pre-match core for unattended Football Betting OneShot runs."""

from __future__ import annotations

import math
from statistics import fmean, median

from risk_engine import dixon_coles_score_matrix


def _deep_snapshot(context: dict) -> dict:
    sources = context.get("source_snapshots") or {}
    nowscore_rows = (sources.get("nowscore") or {}).get("snapshots") or []
    fallback_rows = (sources.get("500_deep") or {}).get("snapshots") or []
    primary = nowscore_rows[0] if nowscore_rows and isinstance(nowscore_rows[0], dict) else {}
    fallback = fallback_rows[0] if fallback_rows and isinstance(fallback_rows[0], dict) else {}
    if not primary:
        return fallback
    # Keep non-market form/context fields from 500 when Nowscore does not
    # provide them, while Nowscore always wins for the three market families.
    merged = {**fallback, **primary}
    for key in ("ouzhi", "yazhi", "daxiao"):
        if not (primary.get(key) or {}).get("bookmakers") and not (primary.get(key) or {}).get("companies"):
            merged[key] = fallback.get(key) or primary.get(key) or {}
    primary_form = (primary.get("shuju") or {}).get("recent_form")
    if not primary_form and fallback.get("shuju"):
        merged["shuju"] = fallback.get("shuju")
    merged.setdefault("source_provenance", {})["market_primary"] = "nowscore"
    merged["source_provenance"]["market_fallback"] = "500.com"
    return merged


def _rate(row: dict, key: str) -> float | None:
    try:
        matches = float(row.get("matches") or 0)
        value = float(row.get(key))
    except (TypeError, ValueError):
        return None
    return value / matches if matches > 0 else None


def _mean(values: list[float | None]) -> float | None:
    clean = [float(value) for value in values if value is not None and math.isfinite(float(value))]
    return fmean(clean) if clean else None


def _consensus_probabilities(deep: dict) -> dict | None:
    rows = []
    for bookmaker in (deep.get("ouzhi") or {}).get("bookmakers") or []:
        odds = bookmaker.get("spf_current") or {}
        try:
            prices = [float(odds[key]) for key in ("home", "draw", "away")]
        except (KeyError, TypeError, ValueError):
            continue
        if any(price <= 1 for price in prices):
            continue
        inverse = [1 / price for price in prices]
        total = sum(inverse)
        rows.append([value / total for value in inverse])
    if not rows:
        return None
    return {key: fmean(row[index] for row in rows) for index, key in enumerate(("home", "draw", "away"))}


def _market_total(deep: dict) -> float | None:
    lines = []
    for company in (deep.get("daxiao") or {}).get("companies") or []:
        try:
            line = float(company.get("current_line"))
        except (TypeError, ValueError):
            continue
        if 1.0 <= line <= 5.0:
            lines.append(line)
    return median(lines) if lines else None


def _market_handicap(deep: dict) -> float | None:
    """Return the median home-team Asian handicap from current quotes."""
    lines = []
    for company in (deep.get("yazhi") or {}).get("companies") or []:
        try:
            line = float(company.get("current_handicap"))
        except (TypeError, ValueError):
            continue
        if -5.0 <= line <= 5.0:
            lines.append(line)
    return median(lines) if lines else None


def _total_line_pricing(expected_goals: float, line: float) -> dict:
    """Price an Asian total at its exact quarter line, including pushes/halves."""
    distribution = []
    covered = 0.0
    for goals in range(16):
        probability = math.exp(-expected_goals) * expected_goals ** goals / math.factorial(goals)
        distribution.append((goals, probability))
        covered += probability
    distribution.append((16, max(0.0, 1.0 - covered)))

    def component(goals: int, component_line: float, side: str) -> tuple[float, float]:
        if side == "over":
            return (1.0, 0.0) if goals > component_line else ((0.0, 1.0) if goals < component_line else (0.0, 0.0))
        return (1.0, 0.0) if goals < component_line else ((0.0, 1.0) if goals > component_line else (0.0, 0.0))

    quarter = round(line * 4) / 4
    if int(round(quarter * 4)) % 2:
        lower = math.floor(quarter * 2) / 2
        components = (lower, lower + 0.5)
    else:
        components = (quarter,)
    priced = {"line": quarter}
    for side in ("over", "under"):
        win_equivalent = loss_equivalent = 0.0
        for goals, probability in distribution:
            outcomes = [component(goals, value, side) for value in components]
            win_equivalent += probability * fmean(item[0] for item in outcomes)
            loss_equivalent += probability * fmean(item[1] for item in outcomes)
        fair_odds = 1.0 + loss_equivalent / win_equivalent if win_equivalent > 0 else None
        priced[side] = {
            "win_equivalent_probability": round(win_equivalent, 6),
            "loss_equivalent_probability": round(loss_equivalent, 6),
            "push_equivalent_probability": round(max(0.0, 1.0 - win_equivalent - loss_equivalent), 6),
            "fair_odds": round(fair_odds, 4) if fair_odds is not None else None,
        }
    return priced


def _outcomes(matrix: dict[tuple[int, int], float]) -> dict:
    result = {"home": 0.0, "draw": 0.0, "away": 0.0}
    for (home, away), probability in matrix.items():
        result["home" if home > away else "draw" if home == away else "away"] += probability
    return result


def _market_share(total: float, target: dict) -> float:
    best = (float("inf"), 0.5)
    for step in range(151, 850):
        share = step / 1000
        matrix = dixon_coles_score_matrix({"lambda_home": total * share, "lambda_away": total * (1 - share), "rho": 0.0})
        outcomes = _outcomes(matrix)
        error = sum((outcomes[key] - target[key]) ** 2 for key in target)
        if error < best[0]:
            best = (error, share)
    return best[1]


def _model_rows(matrix: dict[tuple[int, int], float]) -> tuple[list[dict], list[dict], dict]:
    scores = sorted(matrix.items(), key=lambda item: item[1], reverse=True)
    score_rows = [
        {
            "score": f"{home}-{away}",
            "probability": round(probability, 6),
            "fair_odds": round(1 / probability, 4) if probability > 0 else None,
            "rank": rank,
        }
        for rank, ((home, away), probability) in enumerate(scores[:10], 1)
    ]
    exact_totals: dict[int, float] = {}
    btts_yes = 0.0
    for (home, away), probability in matrix.items():
        exact_totals[home + away] = exact_totals.get(home + away, 0.0) + probability
        if home > 0 and away > 0:
            btts_yes += probability
    total_rows = [
        {"goals": str(goals) if goals < 6 else "6+", "probability": round(
            probability if goals < 6 else sum(value for key, value in exact_totals.items() if key >= 6), 6
        )}
        for goals, probability in sorted(exact_totals.items()) if goals <= 6
    ]
    return score_rows, total_rows, {"yes": round(btts_yes, 6), "no": round(1 - btts_yes, 6)}


def _scenario_score_pick(
    matrix: dict[tuple[int, int], float],
    probabilities: dict,
    total_rows: list[dict],
    btts: dict,
    *,
    expected_goals: float,
    market_probabilities: dict | None = None,
    market_total: float | None = None,
    market_handicap: float | None = None,
    script_context: dict | None = None,
) -> tuple[str, str, dict]:
    """Select one model scenario after reconciling probability, market and script.

    The exact-score matrix supplies the candidate set, not the final answer.  A
    candidate must also fit the model result branch, total-goal centre, BTTS,
    current 1X2 consensus, Asian handicap and verified match-script evidence.
    This deliberately prevents both "mathematical first cell" and "market
    shortest price" from becoming an automatic score recommendation.
    """
    result = max(probabilities, key=probabilities.get)
    market_probabilities = market_probabilities or {}
    market_result = max(market_probabilities, key=market_probabilities.get) if market_probabilities else None
    total_mode_row = max(total_rows, key=lambda row: float(row.get("probability") or 0))
    total_mode = str(total_mode_row.get("goals") or "")
    btts_yes = float(btts.get("yes") or 0) >= 0.5
    maximum = max(matrix.values()) if matrix else 0.0
    script_context = script_context or {}
    script_risks = list(script_context.get("risks") or [])
    high_tail_risk = any(token in " ".join(script_risks) for token in ("红牌", "右尾", "突变"))
    candidates: list[dict] = []
    for (home, away), probability in matrix.items():
        if probability < maximum * 0.42:
            continue
        outcome = "home" if home > away else "draw" if home == away else "away"
        goals = home + away
        total_matches = (total_mode == "6+" and goals >= 6) or total_mode == str(goals)
        btts_matches = (home > 0 and away > 0) == btts_yes
        target_total = market_total if market_total is not None else expected_goals
        total_fit = max(0.0, 1.0 - abs(goals - target_total) / 1.75)
        margin_fit = None
        if market_handicap is not None:
            market_margin = -market_handicap
            margin_fit = max(0.0, 1.0 - abs((home - away) - market_margin) / 1.75)
        components = {
            "比分矩阵": 0.55 * probability / max(maximum, 1e-12),
            "模型方向": 0.18 if outcome == result else -0.12,
            "总进球中枢": 0.14 * total_fit,
            "双方进球": 0.08 if btts_matches else -0.04,
            "市场方向": 0.10 if market_result and outcome == market_result else (-0.05 if market_result else 0.0),
            "亚洲让球": 0.10 * margin_fit if margin_fit is not None else 0.0,
            "比赛剧本": 0.04 if high_tail_risk and goals >= math.ceil(expected_goals) else (-0.03 if high_tail_risk and goals <= 1 else 0.0),
        }
        utility = sum(components.values())
        candidates.append({
            "score": f"{home}-{away}",
            "home": home,
            "away": away,
            "probability": probability,
            "outcome": outcome,
            "goals": goals,
            "total_matches": total_matches,
            "btts_matches": btts_matches,
            "utility": utility,
            "components": components,
        })
    if not candidates:
        (home, away), probability = max(matrix.items(), key=lambda item: item[1])
        trace = {
            "method": "scenario_selector_v2_fallback",
            "selected_score": f"{home}-{away}",
            "selected_probability": round(probability, 6),
            "confidence": "低",
            "main_risk": "可行比分候选不足，只能回退到比分矩阵峰值",
            "candidates": [],
        }
        return f"{home}-{away}", "可行比分区间没有形成稳定情景组合，暂时回退到矩阵峰值。", trace
    candidates.sort(key=lambda row: (row["utility"], row["probability"]), reverse=True)
    challenger = candidates[0]
    mathematical_home, mathematical_away = max(matrix, key=matrix.get)
    selected = next(
        row for row in candidates
        if (int(row["home"]), int(row["away"])) == (mathematical_home, mathematical_away)
    )
    probability = float(selected["probability"])
    home, away, outcome = int(selected["home"]), int(selected["away"]), str(selected["outcome"])
    total_matches, btts_matches = bool(selected["total_matches"]), bool(selected["btts_matches"])
    labels = {"home": "主胜", "draw": "平局", "away": "客胜"}
    reasons = [f"符合{labels[outcome]}主剧本"]
    if total_matches:
        reasons.append(f"落在总进球众数{total_mode}")
    if btts_matches:
        reasons.append("符合双方进球倾向")
    if market_result and outcome == market_result:
        reasons.append("与多公司去水方向一致")
    if market_handicap is not None:
        reasons.append(f"净胜球接近亚洲让球中枢{market_handicap:+g}")
    gap = challenger["utility"] - candidates[1]["utility"] if len(candidates) > 1 else challenger["utility"]
    confidence = "高" if gap >= 0.12 and float(challenger["probability"]) >= 0.09 else "中" if gap >= 0.05 else "低"
    candidate_rows = []
    for rank, row in enumerate(candidates[:8], 1):
        candidate_rows.append({
            "rank": rank,
            "score": row["score"],
            "matrix_probability": round(float(row["probability"]), 6),
            "scenario_score": round(float(row["utility"]), 6),
            "factor_contributions": {key: round(float(value), 4) for key, value in row["components"].items()},
            "decision": "challenger_selected" if row is challenger else "matrix_selected" if row is selected else "rejected",
            "rejection_reason": None if row in (challenger, selected) else "综合情景分低于候选，不按相邻比分算命中",
        })
    trace = {
        "method": "matrix_map_with_scenario_challenger_v1",
        "selected_score": f"{home}-{away}",
        "selected_probability": round(probability, 6),
        "mathematical_first_score": f"{mathematical_home}-{mathematical_away}",
        "scenario_selected_score": challenger["score"],
        "scenario_selected_probability": round(float(challenger["probability"]), 6),
        "model_outcome_leader": result,
        "market_outcome_leader": market_result,
        "total_goal_centre": round(float(market_total if market_total is not None else expected_goals), 3),
        "asian_handicap_median": market_handicap,
        "btts_yes": btts_yes,
        "confidence": confidence,
        "utility_gap_to_second": round(float(gap), 6),
        "main_risk": script_risks[0] if script_risks else f"第二候选{candidates[1]['score']}仍有接近的情景得分" if len(candidates) > 1 else "单一候选稳定性仍需临盘复核",
        "selected_factors": reasons,
        "candidates": candidate_rows,
        "rule": "比分预测与比分投注分离；只有取得可成交赔率且EV通过，才生成模拟注单。",
    }
    return (
        f"{home}-{away}",
        f"正式唯一比分采用比分矩阵峰值（单格概率{probability:.1%}；{'、'.join(reasons)}）。情景选择器建议{challenger['score']}，当前仅作影子候选，待样本外验证后再决定是否覆盖。",
        trace,
    )


def _split_quarter(line: float) -> list[float]:
    quarter = round((abs(line) % 1) * 100)
    sign = -1 if line < 0 else 1
    absolute = abs(line)
    if quarter == 25:
        return [sign * math.floor(absolute), sign * (math.floor(absolute) + 0.5)]
    if quarter == 75:
        return [sign * (math.floor(absolute) + 0.5), sign * math.ceil(absolute)]
    return [line]


def _settlement_probability(matrix: dict[tuple[int, int], float], *, family: str, side: str, line: float) -> dict:
    win = push = loss = 0.0
    for (home, away), probability in matrix.items():
        results = []
        for split in _split_quarter(line):
            if family == "total":
                delta = home + away - split
                if side == "under":
                    delta = -delta
            else:
                delta = home - away + split
                if side == "away":
                    delta = -delta
            results.append(1 if delta > 0 else 0 if delta == 0 else -1)
        factor = sum(results) / len(results)
        if factor > 0:
            win += probability * factor
            if factor < 1:
                push += probability * (1 - factor)
        elif factor < 0:
            loss += probability * -factor
            if factor > -1:
                push += probability * (1 + factor)
        else:
            push += probability
    fair_odds = 1 + loss / win if win > 0 else None
    return {"win": win, "push": push, "loss": loss, "fair_odds": fair_odds}


def _price_audit(deep: dict, matrix: dict[tuple[int, int], float], probabilities: dict) -> list[dict]:
    rows = []
    for outcome, label in (("home", "SPF主胜"), ("draw", "SPF平局"), ("away", "SPF客胜")):
        probability = probabilities[outcome]
        rows.append({
            "market": label,
            "model_probability": round(probability, 6),
            "conservative_probability": round(max(0.01, probability - 0.075), 6),
            "minimum_acceptable_decimal_odds": round(1.08 / max(0.01, probability - 0.075), 3),
            "odds": None,
            "ev": None,
            "audit_role": "模型价格门槛，不是投注指令",
        })
    for company in ((deep.get("daxiao") or {}).get("companies") or [])[:6]:
        try:
            line = float(company.get("current_line"))
        except (TypeError, ValueError):
            continue
        for side, label, water_key in (("over", "大", "current_over_water"), ("under", "小", "current_under_water")):
            probability = _settlement_probability(matrix, family="total", side=side, line=line)
            water = company.get(water_key)
            odds = 1 + float(water) if isinstance(water, (int, float)) else None
            rows.append({
                "market": f"{company.get('name') or '公司'} {label}{line:g}",
                "model_probability": round(probability["win"], 6),
                "push_probability": round(probability["push"], 6),
                "odds": round(odds, 3) if odds else None,
                "ev": round(probability["win"] * (odds - 1) - probability["loss"], 6) if odds else None,
                "minimum_acceptable_decimal_odds": round(probability["fair_odds"] * 1.08, 3) if probability["fair_odds"] else None,
                "audit_role": "市场校准模型的价格复核，非独立套利信号",
            })
    for company in ((deep.get("yazhi") or {}).get("companies") or [])[:6]:
        try:
            line = float(company.get("current_handicap"))
        except (TypeError, ValueError):
            continue
        for side, label, water_key in (("home", "主", "current_water_home"), ("away", "客", "current_water_away")):
            probability = _settlement_probability(matrix, family="handicap", side=side, line=line)
            water = company.get(water_key)
            odds = 1 + float(water) if isinstance(water, (int, float)) else None
            displayed_line = line if side == "home" else -line
            rows.append({
                "market": f"{company.get('name') or '公司'} {label}{displayed_line:+g}",
                "model_probability": round(probability["win"], 6),
                "push_probability": round(probability["push"], 6),
                "odds": round(odds, 3) if odds else None,
                "ev": round(probability["win"] * (odds - 1) - probability["loss"], 6) if odds else None,
                "minimum_acceptable_decimal_odds": round(probability["fair_odds"] * 1.08, 3) if probability["fair_odds"] else None,
                "audit_role": "市场校准模型的价格复核，非独立套利信号",
            })
    return rows


def _nowscore_context_fundamentals(deep: dict) -> dict:
    context = deep.get("nowscore_context") or deep.get("context") or ((deep.get("nowscore") or {}).get("context") or {})
    coach = context.get("coach") or {}
    referee = context.get("referee") or {}
    panlu = context.get("panlu") or {}
    items = []
    home_coach = (coach.get("home") or {}).get("name")
    away_coach = (coach.get("away") or {}).get("name")
    if home_coach or away_coach:
        items.append(f"教练：主队 {home_coach or '未提供'}；客队 {away_coach or '未提供'}。")
    if referee.get("name"):
        summaries = referee.get("summaries") or []
        overall = summaries[0] if summaries else {}
        items.append(f"裁判：{referee['name']}；公开执法样本 {overall.get('matches', '—')} 场。")
    if panlu.get("count"):
        items.append(f"Nowscore盘路历史已读取 {panlu['count']} 场，仅作风格与盘口复核，不直接改写概率。")
    script_context = _nowscore_script_context(coach, referee)
    items.extend(script_context.get("effects") or [])
    return {
        "coach": coach, "referee": referee, "panlu": panlu,
        "script_context": script_context,
        "items": items, "status": "Nowscore赛前背景已核验" if items else "Nowscore赛前背景未取得",
        "sources": list((context.get("source_urls") or {}).values()),
    }


def _number_or_none(value: object) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _coach_venue_record(profile: dict, venue_flag: str) -> dict:
    rows = list(profile.get("team_records") or []) or list(profile.get("coach_records") or [])
    venue_rows = [row for row in rows if str(row.get("venue_flag") or "") == venue_flag]
    candidates = venue_rows or rows
    return max(candidates, key=lambda row: int(row.get("matches") or 0), default={})


def _percent_number(value: object) -> float | None:
    try:
        return float(str(value).replace("%", "").strip())
    except (TypeError, ValueError):
        return None


def _nowscore_script_context(coach: dict, referee: dict) -> dict:
    """Convert verified context into bounded match-script evidence.

    These features shape tempo, resilience and tail-risk narratives.  They do
    not mechanically alter Poisson lambdas until a holdout calibration exists.
    """
    effects: list[str] = []
    risks: list[str] = []
    home_profile, away_profile = coach.get("home") or {}, coach.get("away") or {}
    home_record = _coach_venue_record(home_profile, "1")
    away_record = _coach_venue_record(away_profile, "0")
    home_ppg = _number_or_none(home_record.get("points_per_match"))
    away_ppg = _number_or_none(away_record.get("points_per_match"))
    if home_ppg is not None and away_ppg is not None:
        home_sample, away_sample = int(home_record.get("matches") or 0), int(away_record.get("matches") or 0)
        if min(home_sample, away_sample) >= 5 and abs(home_ppg - away_ppg) >= 0.35:
            stronger = "主队教练的主场组织与拿分稳定性更强" if home_ppg > away_ppg else "客队教练的客场组织与拿分稳定性更强"
            effects.append(f"教练剧本：{stronger}（主场PPG {home_ppg:.2f}，客场PPG {away_ppg:.2f}；样本 {home_sample}/{away_sample} 场），更支持其在僵持阶段掌控调整节奏。")
        else:
            effects.append(f"教练剧本：主队教练主场PPG {home_ppg:.2f}、客队教练客场PPG {away_ppg:.2f}（样本 {home_sample}/{away_sample} 场），差距不足以单独改写主线。")

    summaries = list(referee.get("summaries") or [])
    referee_row = next((row for row in summaries if int(row.get("matches") or 0) >= 20), summaries[0] if summaries else {})
    home_ref, away_ref = referee_row.get("home") or {}, referee_row.get("away") or {}
    yellow = sum(value for value in (_number_or_none(home_ref.get("avg_yellow")), _number_or_none(away_ref.get("avg_yellow"))) if value is not None)
    red = sum(value for value in (_number_or_none(home_ref.get("avg_red")), _number_or_none(away_ref.get("avg_red"))) if value is not None)
    home_rate, away_rate = _percent_number(home_ref.get("win_rate")), _percent_number(away_ref.get("win_rate"))
    referee_matches = int(referee_row.get("matches") or 0)
    if referee.get("name") and referee_matches:
        if yellow >= 4.5 or red >= 0.15:
            effects.append(f"裁判剧本：{referee.get('name')}在{referee_matches}场公开样本中场均双方合计黄牌约{yellow:.2f}、红牌约{red:.2f}，比赛中断与红牌尾部风险偏高，领先方未必能平稳控场。")
            risks.append("裁判公开样本的牌数与红牌率偏高，比分右尾和比赛状态突变风险高于基础泊松假设")
        elif yellow >= 3.2 or red >= 0.10:
            effects.append(f"裁判剧本：{referee.get('name')}在{referee_matches}场公开样本中场均双方合计黄牌约{yellow:.2f}、红牌约{red:.2f}，对抗和定位球权重中等偏高。")
        else:
            effects.append(f"裁判剧本：{referee.get('name')}的{referee_matches}场公开样本未显示异常高牌风险，裁判因素暂不主导比赛节奏。")
        if home_rate is not None and away_rate is not None and abs(home_rate - away_rate) >= 8:
            leaning = "主队" if home_rate > away_rate else "客队"
            effects.append(f"裁判历史样本下{leaning}胜率更高（主{home_rate:.0f}% / 客{away_rate:.0f}%），仅作为剧本倾向，不视为因果优势。")
    return {
        "coach": {"home_record": home_record, "away_record": away_record},
        "referee": {"name": referee.get("name"), "sample": referee_matches, "combined_yellow": round(yellow, 2), "combined_red": round(red, 2)},
        "effects": effects, "risks": risks,
        "model_usage": "match_script_and_uncertainty_only_not_probability_override",
    }


def build_automatic_model(context: dict) -> dict:
    deep = _deep_snapshot(context)
    nowscore_fundamentals = _nowscore_context_fundamentals(deep)
    deep_form = (deep.get("shuju") or {}).get("recent_form") or {}
    prematch_facts = context.get("prematch_fundamentals") or {}
    form = deep_form or prematch_facts.get("recent_form") or {}
    provenance = deep.get("source_provenance") or {}
    if deep_form and provenance.get("form_primary") == "nowscore_analysis":
        form_source = "Nowscore近期赛事数据"
    elif deep_form:
        form_source = "500.com赛前数据快照"
    else:
        form_source = prematch_facts.get("form_source")
    home_home = form.get("home_home") or {}
    away_away = form.get("away_away") or {}
    home_overall = form.get("home_overall") or {}
    away_overall = form.get("away_overall") or {}
    effective_home_home = home_home if home_home.get("matches") else home_overall
    effective_away_away = away_away if away_away.get("matches") else away_overall
    home_venue = _mean([_rate(effective_home_home, "goals_for"), _rate(effective_away_away, "goals_against")])
    away_venue = _mean([_rate(effective_away_away, "goals_for"), _rate(effective_home_home, "goals_against")])
    home_general = _mean([_rate(home_overall, "goals_for"), _rate(away_overall, "goals_against")])
    away_general = _mean([_rate(away_overall, "goals_for"), _rate(home_overall, "goals_against")])
    home_form = _mean([home_venue, home_venue, home_general])
    away_form = _mean([away_venue, away_venue, away_general])
    market_probabilities = _consensus_probabilities(deep) or context.get("official_market_baseline", {}).get("fair_probabilities")
    market_total = _market_total(deep)
    market_handicap = _market_handicap(deep)
    if home_form is None or away_form is None or not market_probabilities:
        return {"model": None, "data_quality": {"status": "仅市场基线", "missing": ["可解析的主客场近期攻防样本"]}}

    form_total = max(1.2, min(4.2, home_form + away_form))
    target_total = market_total if market_total is not None else form_total
    total = 0.60 * form_total + 0.40 * target_total
    form_share = max(0.15, min(0.85, home_form / max(home_form + away_form, 0.01)))
    market_share = _market_share(target_total, market_probabilities)
    share = 0.65 * form_share + 0.35 * market_share
    lambda_home = total * share
    lambda_away = total * (1 - share)
    matrix = dixon_coles_score_matrix({"lambda_home": lambda_home, "lambda_away": lambda_away, "rho": 0.0})
    probabilities = _outcomes(matrix)
    score_rows, total_rows, btts = _model_rows(matrix)
    btts["judgement"] = "双方进球偏是" if btts["yes"] >= 0.55 else "双方进球偏否"
    top_result = max(probabilities, key=probabilities.get)
    labels = {"home": "主胜", "draw": "平局", "away": "客胜"}
    model = {
        "status": "确定性融合模型（可核验近期攻防 + 市场校准）",
        "method": "recent_form_market_calibrated_poisson_v2",
        "lambda_home": round(lambda_home, 6), "lambda_away": round(lambda_away, 6), "rho": 0.0,
        "expected_goals": round(total, 6),
        "probabilities": {key: round(value, 6) for key, value in probabilities.items()},
        "total_goals_buckets": total_rows, "btts": btts, "score_probabilities": score_rows,
        "total_line_analysis": [
            _total_line_pricing(total, line)
            for line in (2.5, 2.75, 3.0, 3.25, 3.5)
        ],
        "calibration": {
            "form_lambda_home": round(home_form, 6), "form_lambda_away": round(away_form, 6),
            "market_total_line_median": market_total, "market_probabilities": market_probabilities,
            "form_weight": 0.60, "market_weight": 0.40,
            "form_source": form_source,
            "venue_proxy_used": not (home_home.get("matches") and away_away.get("matches")),
        },
        "limitations": [
            "近期样本含不同赛事与对手强度，尚未完成逐队Elo/xG对手校正",
            "确认首发、即时伤停、天气与临场战术需在开赛前另行修正",
            "市场信息用于校准，因此该概率不是完全独立于赔率的纯基本面概率",
        ],
    }
    if not deep_form:
        model["limitations"].insert(0, "500深层页缺失，本次改用ESPN可核验近5场样本；样本范围较窄，已按不确定性处理，不能等同完整联赛近况")
    if not (home_home.get("matches") and away_away.get("matches")):
        model["limitations"].insert(1, "主客场拆分样本不足，主客场攻防项使用整体样本代理")
    workspace_match = context.get("selected_workspace_match") or {}
    home_name = workspace_match.get("home") or "主队"
    away_name = workspace_match.get("away") or "客队"
    gap = lambda_home - lambda_away
    if gap >= 0.25:
        control_story = f"{home_name}更可能掌握主动，但{away_name}仍有足够进球期望制造反击或定位球威胁"
    elif gap <= -0.25:
        control_story = f"{away_name}的进攻期望更高，{home_name}需要依靠主场开局和转换效率保持平衡"
    else:
        control_story = "双方预期进球接近，比赛更可能由先入球、定位球或临场换人打破均衡"
    if total >= 3.0:
        tempo_story = "总进球中枢偏高；早段进球会显著放大开放对攻和右尾比分风险"
    elif total <= 2.25:
        tempo_story = "总进球中枢偏低；上半场试探和低比分停留时间可能较长"
    else:
        tempo_story = "总进球中枢处于常规区间，2至3球是主要密集带"
    script_context = nowscore_fundamentals.get("script_context") or {}
    top_score, score_reasoning, score_selection_trace = _scenario_score_pick(
        matrix,
        probabilities,
        total_rows,
        btts,
        expected_goals=total,
        market_probabilities=market_probabilities,
        market_total=market_total,
        market_handicap=market_handicap,
        script_context=script_context,
    )
    model_market_gap = probabilities[top_result] - market_probabilities[top_result]
    market_conflict = (
        f"模型对{labels[top_result]}的判断比多公司市场高{abs(model_market_gap):.1%}，需要用阵容与临盘验证这部分分歧"
        if model_market_gap >= 0
        else f"多公司市场对{labels[top_result]}的定价比模型更强{abs(model_market_gap):.1%}，不能把市场热度直接当成模型优势"
    )
    score_explanation = f"唯一比分{top_score}只是单个比分格的最高点；胜平负主线{labels[top_result]}是多个比分格合计，二者不要求同方向。"
    dynamic_errors = []
    away_away_games = float(away_away.get("matches") or 0)
    home_home_games = float(home_home.get("matches") or 0)
    if top_result == "home" and away_away_games:
        away_loss_rate = float(away_away.get("losses") or 0) / away_away_games
        if away_loss_rate <= 0.2:
            dynamic_errors.append(f"{away_name}近{int(away_away_games)}个客场输球率仅{away_loss_rate:.0%}，主胜主线可能高估主场压制")
    if top_result == "away" and home_home_games:
        home_win_rate = float(home_home.get("wins") or 0) / home_home_games
        if home_win_rate >= 0.6:
            dynamic_errors.append(f"{home_name}近{int(home_home_games)}个主场胜率{home_win_rate:.0%}，客胜主线可能低估主场韧性")
    script_effects = script_context.get("effects") or []
    dynamic_errors.extend(script_context.get("risks") or [])
    dynamic_errors.append("若早段进球、红牌或比赛节奏偏离基准，总进球与比分尾部会同步变化")
    if abs(model_market_gap) >= 0.05:
        dynamic_errors.append(market_conflict)
    dynamic_errors.extend([
        "首发或关键伤停与当前假设不一致，会直接改变双方λ",
        "临盘若出现跨公司同步升降盘，本次赛前快照的价格结构会失效",
    ])
    decisions = {
        "unique_primary_dimension": f"胜平负：{labels[top_result]}（模型{probabilities[top_result]:.1%}）",
        "unique_score": top_score,
        "score_reasoning": score_reasoning,
        "score_selection_trace": score_selection_trace,
        "mathematical_first": f"90分钟主胜{probabilities['home']:.1%}、平局{probabilities['draw']:.1%}、客胜{probabilities['away']:.1%}；λ={lambda_home:.2f}-{lambda_away:.2f}。",
        "market_first": f"多公司去水共识主胜{market_probabilities['home']:.1%}、平局{market_probabilities['draw']:.1%}、客胜{market_probabilities['away']:.1%}；大小球中轴{target_total:.2f}。",
        "match_story": "；".join(part.rstrip("。；") for part in [control_story, tempo_story, *script_effects]) + "。",
        "market_conflict": market_conflict,
        "score_vs_outcome_explanation": score_explanation,
        "maximum_error_points": dynamic_errors[:4],
        "value_judgement": "仅完成模型概率与市场基线；须取得用户渠道即时赔率后才计算EV。",
        "final_state": "空仓｜未锁单",
    }
    request = context.get("request") or {}
    match_id = str(workspace_match.get("id") or request.get("match_id") or "")
    selection_code = {"home": "1", "draw": "X", "away": "2"}[top_result]
    selection_name = {"home": workspace_match.get("home") or "主队", "draw": "平局", "away": workspace_match.get("away") or "客队"}[top_result]
    live_profile = None
    if match_id.isdigit():
        live_profile = {
            "active": True, "overlay_primary": True,
            "contract": {"match_id": match_id, "market_code": "1", "market_name": "全场独赢", "handicap_line": "", "selection_code": selection_code, "selection_name": selection_name, "contract_type": "three_way_selection"},
            "probability": {"point": round(probabilities[top_result], 6), "conservative": round(max(0.01, probabilities[top_result] - (0.10 if not deep_form else 0.075)), 6), "confirmed_model_output": True, "source": "recent_form_market_calibrated_poisson_v2", "calibration_status": "market_calibrated_with_uncertainty_haircut_not_holdout_calibrated"},
            "price": {"max_quote_age_ms": 15000}, "execution": {"minimum_conservative_ev": 0.08},
        }
    return {
        "model": model, "decisions": decisions,
        "price_audit": _price_audit(deep, matrix, probabilities),
        "data_quality": {"status": "模型已计算，临场信息待补", "overall": "FORM_AND_MARKET_MODEL", "missing": ["确认首发", "即时伤停", "用户渠道即时赔率"], "notes": [f"近期攻防来源：{form_source or '未标明'}。", "模型数值由固定公式生成，DeepSeek不参与概率计算。"]},
        "fundamentals": {
            **(context.get("prematch_fundamentals") or {}),
            "recent_form": form,
            "metric": "recent actual goals, not xG",
            "nowscore_context": nowscore_fundamentals,
            "items": list((context.get("prematch_fundamentals") or {}).get("items") or []) + list(nowscore_fundamentals.get("items") or []),
            "status": nowscore_fundamentals.get("status") or (context.get("prematch_fundamentals") or {}).get("status"),
            "sources": list((context.get("prematch_fundamentals") or {}).get("sources") or []) + list(nowscore_fundamentals.get("sources") or []),
        },
        "live_ev_profiles": live_profile,
    }
