#!/usr/bin/env python3
"""Deterministic pre-match core for unattended Football Betting OneShot runs."""

from __future__ import annotations

import math
from statistics import fmean, median

from risk_engine import dixon_coles_score_matrix


def _deep_snapshot(context: dict) -> dict:
    sources = context.get("source_snapshots") or {}
    for source_name in ("500_deep", "nowscore"):
        source = sources.get(source_name) or {}
        snapshots = source.get("snapshots") if isinstance(source, dict) else []
        if snapshots and isinstance(snapshots[0], dict):
            return snapshots[0]
    return {}


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


def build_automatic_model(context: dict) -> dict:
    deep = _deep_snapshot(context)
    deep_form = (deep.get("shuju") or {}).get("recent_form") or {}
    prematch_facts = context.get("prematch_fundamentals") or {}
    form = deep_form or prematch_facts.get("recent_form") or {}
    form_source = "500.com赛前数据快照" if deep_form else prematch_facts.get("form_source")
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
    top_score = score_rows[0]["score"]
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
    dynamic_errors.append("若早段进球、红牌或比赛节奏偏离基准，总进球与比分尾部会同步变化")
    if abs(model_market_gap) >= 0.05:
        dynamic_errors.append(market_conflict)
    dynamic_errors.extend([
        "首发或关键伤停与当前假设不一致，会直接改变双方λ",
        "临盘若出现跨公司同步升降盘，本次赛前快照的价格结构会失效",
    ])
    decisions = {
        "unique_primary_dimension": f"胜平负：{labels[top_result]}（模型{probabilities[top_result]:.1%}）",
        "unique_score": score_rows[0]["score"],
        "mathematical_first": f"90分钟主胜{probabilities['home']:.1%}、平局{probabilities['draw']:.1%}、客胜{probabilities['away']:.1%}；λ={lambda_home:.2f}-{lambda_away:.2f}。",
        "market_first": f"多公司去水共识主胜{market_probabilities['home']:.1%}、平局{market_probabilities['draw']:.1%}、客胜{market_probabilities['away']:.1%}；大小球中轴{target_total:.2f}。",
        "match_story": f"{control_story}；{tempo_story}。",
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
            "recent_form": form,
            "metric": "recent actual goals, not xG",
            **(context.get("prematch_fundamentals") or {}),
        },
        "live_ev_profiles": live_profile,
    }
