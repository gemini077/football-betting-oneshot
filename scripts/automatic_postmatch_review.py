#!/usr/bin/env python3
"""Create strict, comprehensive reviews from frozen reports and verified 90m results."""

from __future__ import annotations

import argparse
import json
import math
import re
from datetime import datetime
from pathlib import Path
from statistics import mean, median
from typing import Any

from market_history import load_history
from postmatch_queue import BASE_DIR, SHANGHAI, load_json
from match_identity import identity_aliases
from postmatch_evidence import fetch_postmatch_evidence
from paper_ledger import pair_key
from risk_engine import dixon_coles_score_matrix


SCHEDULE_ROOT = BASE_DIR / "data" / "postmatch_automation" / "schedules"
REVIEW_ROOT = BASE_DIR / "data" / "postmatch_reviews"
REAL_BET_ROOT = BASE_DIR / "data" / "real_bets"
PAPER_LEDGER_PATH = BASE_DIR / "data" / "paper_ledger" / "latest.json"


def _score(value: Any) -> tuple[int, int] | None:
    match = re.fullmatch(r"\s*(\d+)\s*[-:]\s*(\d+)\s*", str(value or ""))
    return (int(match.group(1)), int(match.group(2))) if match else None


def _actual_outcome(home: int, away: int) -> str:
    return "主胜" if home > away else "平局" if home == away else "客胜"


def _primary_outcome(text: Any) -> str | None:
    value = str(text or "")
    for outcome in ("主胜", "平局", "客胜"):
        if outcome in value:
            return outcome
    return None


def _primary_signature(text: Any) -> str:
    """Compare decision contracts without treating probability text as a reversal."""
    value = str(text or "").strip()
    outcome = _primary_outcome(value)
    if outcome:
        return f"胜平负:{outcome}"
    total = re.search(r"(大|小)\s*(\d+(?:\.\d+)?)", value)
    if total:
        return f"大小球:{total.group(1)}{total.group(2)}"
    if "双方进球" in value or "BTTS" in value.upper():
        return "BTTS:是" if any(token in value for token in ("是", "Yes", "YES")) else "BTTS:否"
    return re.sub(r"[（(][^）)]*%[^）)]*[）)]", "", value)


def _primary_settlement(text: Any, home_goals: int, away_goals: int) -> tuple[str | None, str, bool | None, str]:
    value = str(text or "")
    outcome = _primary_outcome(value)
    actual_outcome = _actual_outcome(home_goals, away_goals)
    if outcome:
        return outcome, actual_outcome, outcome == actual_outcome, "胜平负"
    total = home_goals + away_goals
    total_match = re.search(r"(大|小)\s*(\d+(?:\.\d+)?)", value)
    if total_match:
        side, line = total_match.group(1), float(total_match.group(2))
        if total == line:
            return f"{side}{line:g}", f"总进球{total}（走盘）", None, "大小球"
        hit = total > line if side == "大" else total < line
        return f"{side}{line:g}", f"总进球{total}", hit, "大小球"
    if "双方进球" in value or "BTTS" in value.upper():
        pick_yes = any(token in value for token in ("是", "Yes", "YES"))
        actual_yes = home_goals > 0 and away_goals > 0
        return "双方进球是" if pick_yes else "双方进球否", "双方进球是" if actual_yes else "双方进球否", pick_yes == actual_yes, "BTTS"
    return value or None, actual_outcome, None, "未识别合约"


def _market_timeline(report: dict) -> dict:
    market = report.get("market") or {}
    consensus = market.get("consensus") or {}
    opening = consensus.get("open") or {}
    current = consensus.get("current") or {}
    def vector(row: dict) -> str:
        return f"{row.get('home', '—')}/{row.get('draw', '—')}/{row.get('away', '—')}"
    initial = f"30家公司开盘均值 {vector(opening)}"
    final = f"冻结报告即时均值 {vector(current)}"

    shuju_id = (report.get("match") or {}).get("shuju_id")
    history_path = BASE_DIR / "data" / "market_history" / str(shuju_id) / "market_history.jsonl"
    history = [row for row in load_history(history_path) if row.get("euro") or row.get("asian") or row.get("totals")]

    def snapshot_text(snapshot: dict) -> str:
        euros = [row.get("current") or {} for row in snapshot.get("euro") or []]
        h = [float(row["home"]) for row in euros if row.get("home") is not None]
        d = [float(row["draw"]) for row in euros if row.get("draw") is not None]
        a = [float(row["away"]) for row in euros if row.get("away") is not None]
        asian_lines = [float(row["current_line"]) for row in snapshot.get("asian") or [] if row.get("current_line") is not None]
        total_lines = [float(row["current_line"]) for row in snapshot.get("totals") or [] if row.get("current_line") is not None]
        euro_text = f"{mean(h):.2f}/{mean(d):.2f}/{mean(a):.2f}" if h and d and a else "—"
        asian_text = f"{median(asian_lines):g}" if asian_lines else "—"
        total_text = f"{median(total_lines):g}" if total_lines else "—"
        return f"欧赔均值{euro_text}；亚盘中位{asian_text}；大小中位{total_text}"

    if history:
        first, last = history[0], history[-1]
        first_time = first.get("market_time") or first.get("recorded_at") or "—"
        last_time = last.get("market_time") or last.get("recorded_at") or "—"
        initial += f"；首次有效快照[{first_time}] {snapshot_text(first)}"
        final = f"最后有效赛前快照[{last_time}] {snapshot_text(last)}"
    trace = " → ".join(
        f"{row.get('market_time') or row.get('recorded_at') or '—'} {snapshot_text(row)}"
        for row in history
    ) or "仅有冻结报告开盘/即时对照，没有独立多时点快照"
    return {
        "初盘定位": initial,
        "终盘定位（最后赛前快照）": final,
        # Backward-compatible key consumed by older workspace snapshots.  The
        # displayed value names its real capture time and never claims T-15.
        "终盘定位（临场15min）": final,
        "终盘对比初盘变化": trace,
        "开赛倒计时": f"自动保存{len(history)}个有效独立快照；临盘档为T-30M窗口，不冒充精确T-15",
        "锁单窗口合规性": "模拟观察与真实账户完全分离；未收到“锁单/已下单”不生成真实注单",
        "数据完整度": f"{(report.get('data_quality') or {}).get('status') or '未标注'}；有效历史快照{len(history)}个",
    }


def _probability(report: dict, outcome: str) -> float | None:
    key = {"主胜": "home", "平局": "draw", "客胜": "away"}[outcome]
    value = ((report.get("model") or {}).get("probabilities") or {}).get(key)
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _top_total(report: dict) -> str | None:
    rows = (report.get("model") or {}).get("total_goals_buckets") or []
    valid = [row for row in rows if isinstance(row, dict) and row.get("probability") is not None]
    if not valid:
        return None
    row = max(valid, key=lambda item: float(item.get("probability") or 0))
    return str(row.get("goals") or row.get("bucket") or "").replace("球", "") or None


def _btts_pick(report: dict) -> str | None:
    btts = (report.get("model") or {}).get("btts") or {}
    try:
        yes, no = float(btts.get("yes")), float(btts.get("no"))
    except (TypeError, ValueError):
        return None
    return "是" if yes >= no else "否"


def _model_diagnostics(report: dict, home_goals: int, away_goals: int) -> dict:
    model = report.get("model") or {}
    probabilities = model.get("probabilities") or {}
    actual_key = "home" if home_goals > away_goals else "draw" if home_goals == away_goals else "away"
    actual_vector = {"home": 1.0 if actual_key == "home" else 0.0, "draw": 1.0 if actual_key == "draw" else 0.0, "away": 1.0 if actual_key == "away" else 0.0}
    clean = {key: float(probabilities.get(key) or 0.0) for key in actual_vector}
    brier = sum((clean[key] - actual_vector[key]) ** 2 for key in actual_vector)
    actual_probability = max(clean.get(actual_key, 0.0), 1e-12)
    log_loss = -math.log(actual_probability)
    lambda_home = float(model.get("lambda_home") or 0.0)
    lambda_away = float(model.get("lambda_away") or 0.0)
    matrix = dixon_coles_score_matrix({"lambda_home": lambda_home, "lambda_away": lambda_away, "rho": float(model.get("rho") or 0.0)}) if lambda_home > 0 and lambda_away > 0 else {}
    score_probability = float(matrix.get((home_goals, away_goals)) or 0.0)
    ranked = sorted(matrix.items(), key=lambda item: item[1], reverse=True)
    score_rank = next((index + 1 for index, (score, _) in enumerate(ranked) if score == (home_goals, away_goals)), None)
    market = (model.get("calibration") or {}).get("market_probabilities") or {}
    market_actual = float(market.get(actual_key) or 0.0) if market else None
    return {
        "actual_outcome_key": actual_key,
        "actual_outcome_probability": round(actual_probability, 6),
        "brier_score_1x2": round(brier, 6),
        "log_loss_1x2": round(log_loss, 6),
        "actual_score_probability": round(score_probability, 6),
        "actual_score_rank": score_rank,
        "lambda_home_residual": round(home_goals - lambda_home, 4),
        "lambda_away_residual": round(away_goals - lambda_away, 4),
        "total_goals_residual": round((home_goals + away_goals) - (lambda_home + lambda_away), 4),
        "market_actual_outcome_probability": round(market_actual, 6) if market_actual is not None else None,
        "model_minus_market_actual_outcome": round(actual_probability - market_actual, 6) if market_actual is not None else None,
        "interpretation": "Brier与Log Loss评估方向概率；比分排名和λ残差评估比赛剧本偏差，不能用相邻比分冒充命中。",
    }


def _paper_tickets_for_match(home: str, away: str) -> list[dict]:
    try:
        rows = (load_json(PAPER_LEDGER_PATH) or {}).get("tickets") or []
    except (OSError, json.JSONDecodeError):
        return []
    expected = f"{home} vs {away}"
    expected_key = pair_key(home, away)
    return [
        row for row in rows
        if str(row.get("match") or "") == expected
        or str(row.get("match_key") or "") == expected_key
        or (str(row.get("home") or "") == home and str(row.get("away") or "") == away)
    ]


def _movement(report: dict) -> str:
    consensus = (report.get("market") or {}).get("consensus") or {}
    opening, current = consensus.get("open") or {}, consensus.get("current") or {}
    labels = (("home", "主胜"), ("draw", "平局"), ("away", "客胜"))
    pieces, strongest_cut = [], None
    for key, label in labels:
        try: old, new = float(opening[key]), float(current[key])
        except (KeyError, TypeError, ValueError): continue
        change = new - old
        pieces.append(f"{label}{old:.2f}→{new:.2f}（{'降' if change < 0 else '升' if change > 0 else '平'}{abs(change):.2f}）")
        if change < 0 and (strongest_cut is None or change < strongest_cut[0]): strongest_cut = (change, label)
    if not pieces:
        return "本次冻结快照未形成可量化的价格变化，结论仅按模型概率执行"
    support = strongest_cut[1] if strongest_cut else "不支持单边追价"
    return "；".join(pieces) + f"。最大变化支持：{support}；若临场方向反转并跨回初盘价，则取消该价格信号。"


def _objective_market_direction(report: dict) -> dict:
    consensus = (report.get("market") or {}).get("consensus") or {}
    opening, current = consensus.get("open") or {}, consensus.get("current") or {}
    labels = {"home": "主胜", "draw": "平局", "away": "客胜"}
    reductions = []
    for key, label in labels.items():
        try:
            old, new = float(opening[key]), float(current[key])
        except (KeyError, TypeError, ValueError):
            continue
        reductions.append(((old - new) / old, key, label, old, new))
    if not reductions:
        return {"direction": None, "strength": "unknown", "summary": "没有可量化的开盘—最后赛前价格对照。"}
    relative, key, label, old, new = max(reductions)
    strength = "strong" if relative >= 0.08 else "moderate" if relative >= 0.03 else "weak"
    wording = {"strong": "明显加强", "moderate": "温和加强", "weak": "没有拉开明显单边"}[strength]
    return {
        "direction": key,
        "label": label,
        "strength": strength,
        "relative_change": round(relative, 6),
        "summary": f"多公司均值由{old:.2f}降至{new:.2f}（{relative:.1%}），客观价格结构{wording}{label}。该结论是价格压力，不冒充真实成交资金流。",
    }


def _root_cause(
    report: dict,
    actual_outcome: str,
    actual_score: str,
    misses: list[str],
    classification: str,
    primary_market: str = "胜平负",
    primary_pick: str | None = None,
) -> dict:
    probs = (report.get("model") or {}).get("probabilities") or {}
    labels = {"home": "主胜", "draw": "平局", "away": "客胜"}
    numeric = {labels[key]: float(value) for key, value in probs.items() if key in labels and isinstance(value, (int, float))}
    top = max(numeric, key=numeric.get) if numeric else "无有效方向"
    actual_prob = numeric.get(actual_outcome)
    top_prob = numeric.get(top)
    gap = max(0.0, (top_prob or 0) - (actual_prob or 0))
    score_rows = (report.get("model") or {}).get("score_probabilities") or []
    rank = next((index + 1 for index, row in enumerate(score_rows) if str(row.get("score")) == actual_score), None)
    score_note = f"实际比分在赛前矩阵第{rank}位" if rank else "实际比分未进入赛前主要比分区间"
    audit = "；".join(misses) if misses else "主维度及辅助维度均按冻结判断通过"
    if primary_market == "胜平负":
        counter = (f"模型当时首位为{top}，实际{actual_outcome}概率低{gap:.1%}；"
                   f"若赛前将{actual_outcome}上调超过{gap:.1%}，主方向会翻转。{score_note}。")
    else:
        counter = (
            f"赛前主维度是{primary_market}的“{primary_pick or '未命名方向'}”，实际比分为{actual_score}。"
            "要使该方向翻转，赛前进球中枢或双方进球概率必须跨过对应盘口边界；"
            "缺少可复核参数时不编造精确阈值。" + score_note + "。"
        )
    identifiable = "赛前可通过概率差、实际比分尾部排名和价格反向条件识别；不能用赛后比分倒推改写首推"
    change = ("主维度错误进入同类样本校准池；累计同型错误达到3场后再调整胜平负/低比分权重"
              if "错误" in classification else "本场不改主模型参数，只记录比分分布残差")
    return {"决策节点审计": audit, "反事实推演": counter, "赛前可识别性": identifiable,
            "是否修改模型": "观察累计，禁止单场追参", "具体修改建议": change,
            "收敛结论": classification, "生效状态": "观察池", "优先级": "P1" if "错误" in classification else "P2",
            "最大错点触发透视": f"赛前概率首位{top}；实际结果{actual_outcome}；{score_note}"}


def _checkpoint_rows(report: dict) -> list[dict]:
    """Recover every real checkpoint even when legacy provider ids differ."""
    match = report.get("match") or {}
    aliases = identity_aliases(match)
    home, away = str(match.get("home") or ""), str(match.get("away") or "")
    rows = []
    for path in (BASE_DIR / "data" / "market_history" / "checkpoints").glob("*/*.json"):
        try:
            row = load_json(path)
        except (OSError, json.JSONDecodeError):
            continue
        same = (
            str(row.get("canonical_match_id") or "") in aliases
            or str(row.get("match_id") or "") in aliases
            or (str(row.get("home") or "") == home and str(row.get("away") or "") == away)
        )
        if not same:
            continue
        decision = row.get("decision") or {}
        analysis_path = BASE_DIR / str(row.get("analysis_input") or "")
        if not decision and analysis_path.exists():
            try:
                analysis = load_json(analysis_path)
                decision = {
                    "probabilities": (analysis.get("model") or {}).get("probabilities") or {},
                    "primary_dimension": (analysis.get("decisions") or {}).get("unique_primary_dimension"),
                    "unique_score": (analysis.get("decisions") or {}).get("unique_score"),
                    "score_reasoning": (analysis.get("decisions") or {}).get("score_reasoning"),
                    "score_selection_trace": (analysis.get("decisions") or {}).get("score_selection_trace") or {},
                    **((analysis.get("market") or {}).get("interpretation") or {}),
                }
            except (OSError, json.JSONDecodeError):
                pass
        rows.append({**row, "decision": decision})
    return sorted(rows, key=lambda row: str(row.get("captured_at") or ""))


def _rich_market_timeline(report: dict) -> dict:
    rows = _checkpoint_rows(report)
    if not rows:
        return {
            "快照覆盖": "没有找到可复核的独立赛前快照；不把开盘与终盘误写成连续走势。",
            "判断是否反转": "无有效节点，不能声称发生过反转。",
            "判断如何变化": "无有效节点，无法证明判断曾发生变化。",
            "最后有效判断": str((report.get("decisions") or {}).get("unique_primary_dimension") or "未形成"),
            "数据有效性": "仅复盘冻结报告本身，不能声称资金持续流入或机构连续调整。",
        }
    changes, previous = [], None
    leader_changes = 0
    primary_changes = 0
    score_changes = 0
    for row in rows:
        decision = row.get("decision") or {}
        probs = decision.get("probabilities") or {}
        leader = max(probs, key=probs.get) if probs else None
        snapshot = {
            "leader": leader,
            "primary": decision.get("primary_dimension"),
            "primary_signature": _primary_signature(decision.get("primary_dimension")),
            "score": decision.get("unique_score"),
        }
        if previous is None:
            changes.append(f"首次判断：{snapshot['primary'] or '主维度未形成'}；比分 {snapshot['score'] or '未收敛'}。")
        else:
            parts = []
            if snapshot["leader"] != previous["leader"]:
                parts.append(f"胜平负首位由 {previous['leader'] or '未形成'} 变为 {snapshot['leader'] or '未形成'}")
                leader_changes += 1
            if snapshot["primary_signature"] != previous["primary_signature"]:
                parts.append(f"主维度由“{previous['primary']}”变为“{snapshot['primary']}”")
                primary_changes += 1
            if snapshot["score"] != previous["score"]:
                parts.append(f"比分由 {previous['score']} 调整为 {snapshot['score']}")
                score_changes += 1
            if parts:
                changes.append("；".join(parts) + "。")
        previous = snapshot
    last = rows[-1].get("decision") or {}
    late = sum(1 for row in rows if row.get("capture_quality") == "late_recovery" or float(row.get("lateness_minutes") or 0) > 25)
    direction_statement = _movement(report)
    objective_direction = _objective_market_direction(report)
    score_trace = last.get("score_selection_trace") or (report.get("decisions") or {}).get("score_selection_trace") or {}
    score_factor_text = "、".join(str(item) for item in (score_trace.get("selected_factors") or [])[:4])
    stable_statement = (
        "胜平负首位与主维度从未反转，只发生概率微调；不得写成临场翻转。"
        if leader_changes == 0 and primary_changes == 0
        else f"胜平负首位变化{leader_changes}次、主维度变化{primary_changes}次；属于真实判断调整。"
    )
    final_outcome = _primary_outcome(last.get("primary_dimension"))
    objective_label = objective_direction.get("label")
    if objective_direction.get("strength") in {"strong", "moderate"}:
        behaviour = objective_direction["summary"]
        impact = (
            f"盘口与模型原主线同向，增强{objective_label}证据但不构成判断反转。"
            if final_outcome == objective_label
            else f"盘口明显支持{objective_label}而模型主线为{final_outcome or '未形成'}，应提高冲突警报并降低执行置信度。"
        )
    else:
        behaviour = str(last.get("bookmaker_behaviour") or last.get("purpose") or objective_direction.get("summary"))
        impact = str(last.get("model_impact") or "盘口信息未达到推翻基本模型的阈值。")
    return {
        "快照覆盖": f"共保存 {len(rows)} 个独立赛前快照，其中 {late} 个为延迟恢复快照；每个节点只使用当时真实价格。",
        "判断是否反转": stable_statement,
        "判断如何变化": " ".join(changes) if changes else "核心判断始终未越过模型决策边界。",
        "比分判断变化": (f"唯一比分共调整{score_changes}次；最后由{score_factor_text}共同支持。" if score_factor_text else f"唯一比分共调整{score_changes}次。"),
        "盘口客观方向": direction_statement,
        "临盘资金与机构行为": behaviour,
        "对最终判断的影响": impact,
        "最后有效判断": f"{last.get('primary_dimension') or '未形成'}；比分 {last.get('unique_score') or '未收敛'}。",
        "数据有效性": "延迟快照明确标记，不补造错过的节点；缺少交易量时不把赔率变化冒充真实资金流。",
    }


def _rich_root_cause(
    report: dict,
    actual_outcome: str,
    actual_score: str,
    misses: list[str],
    classification: str,
    diagnostics: dict,
    evidence: dict,
) -> dict:
    rows = _checkpoint_rows(report)
    decisions = report.get("decisions") or {}
    risks = [str(item) for item in decisions.get("maximum_error_points") or [] if item]
    primary_values = {_primary_signature((row.get("decision") or {}).get("primary_dimension")) for row in rows if row.get("decision")}
    stable = bool(rows) and len(primary_values) <= 1
    if not misses:
        cause = "主维度结算正确；仍独立检查比分和附属市场，不用方向命中掩盖其他错误。"
    elif not rows:
        cause = "没有可复核的独立赛前快照，不能声称发生临场反转；本场仅能确认冻结概率与实际赛果存在校准误差。"
    elif stable:
        cause = "方向在有效快照中保持稳定，但实际赛果落在模型次要分支；主要误差来自概率校准而非临场反转。"
    else:
        cause = "赛前判断发生过反转，最终快照没有充分吸收冲突信号；临盘权重或冲突处理是首要检查项。"
    stats = evidence.get("statistics") or {}
    shots = stats.get("射门") or {}
    shots_on_target = stats.get("射正") or {}
    xg = stats.get("预期进球(xG)") or stats.get("预期进球") or {}
    half_time = evidence.get("score_half_time") or "未取得"
    first_event = next((row for row in evidence.get("key_events") or [] if "进球" in str(row.get("type")) or "入球" in str(row.get("type"))), None)
    script_parts = [f"半场比分{half_time}"]
    if first_event:
        script_parts.append(f"首个进球发生在{first_event.get('minute')}分钟，由{'主队' if first_event.get('side') == 'home' else '客队'}取得")
    if shots:
        script_parts.append(f"射门{shots.get('home')}-{shots.get('away')}、射正{shots_on_target.get('home', '—')}-{shots_on_target.get('away', '—')}")
    if xg:
        script_parts.append(f"赛后xG {xg.get('home')}-{xg.get('away')}")
    trace = decisions.get("score_selection_trace") or {}
    selected_factors = "、".join(str(item) for item in trace.get("selected_factors") or []) or "旧报告未保存比分因子轨迹"
    top_probability = max(((report.get("model") or {}).get("probabilities") or {}).values(), default=0)
    actual_probability = float(diagnostics.get("actual_outcome_probability") or 0)
    probability_gap = max(0.0, float(top_probability) - actual_probability)
    counterfactual = (
        f"赛前只有在独立信息使{actual_outcome}概率至少再提高{probability_gap:.1%}并越过原首位，"
        "或使原首推跌破执行边界时才应改方向；不能用赛后比分倒推。"
    )
    score_counterfactual = (
        f"唯一比分若要改为{actual_score}，必须在赛前候选审计中同时改善结果方向、总进球、BTTS与盘口净胜球适配，"
        f"并超过原首推{trace.get('selected_score') or decisions.get('unique_score')}的综合情景分；相邻比分不构成命中。"
    )
    tags = []
    residual = float(diagnostics.get("total_goals_residual") or 0)
    if residual >= 2:
        tags.append("高比分右尾")
    if half_time not in {"未取得", None}:
        try:
            ht = _score(half_time)
            if ht and sum(ht) >= 3:
                tags.append("上半场早爆")
        except (TypeError, ValueError):
            pass
    if primary_values and stable:
        tags.append("方向稳定但校准失真")
    tags.append("比分情景选择审计")
    return {
        "结算错项": "；".join(misses) if misses else "主维度无错误；附属维度按各自规则独立结算。",
        "最可能根因": cause,
        "数据层根因": f"主队λ残差{diagnostics.get('lambda_home_residual')}、客队λ残差{diagnostics.get('lambda_away_residual')}、总进球残差{diagnostics.get('total_goals_residual')}；{'；'.join(script_parts)}。",
        "概率层根因": f"实际结果赛前概率{actual_probability:.1%}，Brier={diagnostics.get('brier_score_1x2')}，Log Loss={diagnostics.get('log_loss_1x2')}；实际比分概率{float(diagnostics.get('actual_score_probability') or 0):.2%}、全矩阵排名第{diagnostics.get('actual_score_rank') or '未覆盖'}。",
        "市场层根因": _objective_market_direction(report).get("summary", _movement(report)) + (
            " 方向与主维度全程稳定，不能归因为临场反转。" if stable
            else " 没有独立节点，不能判断临场是否反转。" if not rows
            else " 有效节点确实发生主维度变化，需要复核临盘权重。"
        ),
        "比赛剧本层根因": "；".join(script_parts) + "。早段比分状态会改变后续攻守条件，独立泊松对这种状态依赖刻画不足。",
        "决策层根因": f"赛前唯一比分由以下因子选出：{selected_factors}。赛后仍按唯一落点严格结算，不用方向或相邻比分遮盖误差。",
        "自动化层根因": f"保存赛前快照{len(rows)}个；赛后事实抓取状态{evidence.get('status') or 'unavailable'}。缺失节点只降低证据强度，不补造价格轨迹。",
        "赛前已知风险": "；".join(risks) if risks else "冻结报告没有列出可验证的额外风险点。",
        "反事实条件": counterfactual,
        "比分反事实": score_counterfactual,
        "比分误差定位": f"实际比分 {actual_score} 的赛前概率为{float(diagnostics.get('actual_score_probability') or 0):.2%}，在完整比分矩阵排名第 {diagnostics.get('actual_score_rank') or '未覆盖'}。",
        "模型修正": "把本场按标签进入分层样本池；累计至少20场后分别校准方向概率、比分情景权重、早段进球状态依赖和临盘冲突权重，禁止单场追参。",
        "样本标签": "、".join(tags),
        "修正状态": "已归档观察池；达到同类样本门槛后才允许离线重训与版本升级。",
        "复盘结论": classification,
    }


def _review_decision_evolution(report: dict) -> dict:
    """Rebuild user-facing evolution from normalized contracts, not legacy prose."""
    rows = _checkpoint_rows(report)
    history = []
    previous = None
    labels = {"home": "主胜", "draw": "平局", "away": "客胜"}
    for row in rows:
        decision = row.get("decision") or {}
        probabilities = decision.get("probabilities") or {}
        leader = max(probabilities, key=probabilities.get) if probabilities else None
        current = {
            "leader": leader,
            "primary": decision.get("primary_dimension"),
            "primary_signature": _primary_signature(decision.get("primary_dimension")),
            "score": decision.get("unique_score"),
            "probabilities": probabilities,
            "reasoning": decision.get("score_reasoning"),
        }
        if previous is None:
            headline = f"建立初始判断：{labels.get(leader, '方向未形成')}；唯一比分{current['score'] or '未形成'}"
            summary = f"冻结主维度{current['primary'] or '未形成'}。{current['reasoning'] or ''}".strip()
            changed = True
        else:
            changes = []
            if current["leader"] != previous["leader"]:
                changes.append(f"胜平负首位由{labels.get(previous['leader'], '未形成')}变为{labels.get(current['leader'], '未形成')}")
            if current["primary_signature"] != previous["primary_signature"]:
                changes.append(f"主维度由{previous['primary']}变为{current['primary']}")
            if current["score"] != previous["score"]:
                changes.append(f"唯一比分由{previous['score']}调整为{current['score']}")
            probability_changes = []
            for key in ("home", "draw", "away"):
                try:
                    delta = float(probabilities.get(key)) - float((previous.get("probabilities") or {}).get(key))
                except (TypeError, ValueError):
                    continue
                if abs(delta) >= 0.002:
                    probability_changes.append(f"{labels[key]}{'上调' if delta > 0 else '下调'}{abs(delta):.1%}")
            changes.extend(probability_changes)
            headline = "；".join(changes[:3]) if changes else "核心判断维持不变"
            summary = "；".join(changes) + "。" if changes else "新信息没有越过方向、主维度或唯一比分的决策边界。"
            changed = bool(changes)
        history.append({
            "captured_at": row.get("captured_at"),
            "headline": headline,
            "summary": summary,
            "changed": changed,
            "score": current["score"],
        })
        previous = current
    return {
        "latest": history[-1] if history else None,
        "history": history,
        "normalization_rule": "概率数值微调不等于主维度反转；只有方向或合约发生变化才记为反转。",
    }


def settle_real_bets(home: str, away: str, home_goals: int, away_goals: int) -> list[dict]:
    """Settle only user-confirmed records with their actual entered price/stake."""
    if not REAL_BET_ROOT.exists(): return []
    expected = f"{home} vs {away}"
    settled = []
    for path in sorted(REAL_BET_ROOT.glob("REAL-*.json")):
        payload = load_json(path)
        if str(payload.get("match") or "") != expected or payload.get("status") not in {"locked", "settled"}:
            continue
        selection = str(payload.get("selection") or "")
        score_pick = _score(selection)
        if score_pick is not None:
            hit = score_pick == (home_goals, away_goals)
        else:
            _, _, hit, _ = _primary_settlement(selection, home_goals, away_goals)
        stake, odds = float(payload.get("stake") or 0), float(payload.get("odds") or 0)
        profit = round(stake * (odds - 1), 2) if hit is True else -stake if hit is False else 0.0
        payload.update({"status": "settled", "settlement": "赢" if hit is True else "输" if hit is False else "走/不可结算", "profit": profit,
                        "result_90m": f"{home_goals}-{away_goals}", "settled_at": datetime.now(SHANGHAI).isoformat()})
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        settled.append(payload)
    if settled:
        rows = []
        for path in sorted(REAL_BET_ROOT.glob("REAL-*.json")):
            try: rows.append(load_json(path))
            except (OSError, json.JSONDecodeError): pass
        (REAL_BET_ROOT / "latest.json").write_text(json.dumps({"bets": rows}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return settled


def build_review(schedule: dict, report: dict, now: datetime) -> dict:
    actual = _score(schedule.get("result_90m"))
    if actual is None:
        raise ValueError("verified result_90m is required")
    home_goals, away_goals = actual
    actual_score = f"{home_goals}-{away_goals}"
    actual_outcome = _actual_outcome(home_goals, away_goals)
    decisions = report.get("decisions") or {}
    primary_pick, primary_actual, primary_hit, primary_market = _primary_settlement(
        decisions.get("unique_primary_dimension"), home_goals, away_goals
    )
    score_pick = _score(decisions.get("unique_score"))
    btts_pick = _btts_pick(report)
    btts_actual = "是" if home_goals > 0 and away_goals > 0 else "否"
    total_pick = _top_total(report)
    total_actual = home_goals + away_goals
    evidence = fetch_postmatch_evidence(report, schedule)
    if evidence.get("score_90m") and evidence.get("score_90m") != actual_score:
        evidence["status"] = "score_conflict"
        evidence["conflict"] = f"赛程核验{actual_score}，Nowscore详情{evidence.get('score_90m')}；停止自动归因，等待人工核验。"
    diagnostics = _model_diagnostics(report, home_goals, away_goals)
    score_hit = score_pick == actual if score_pick else None
    total_hit = (total_pick == str(total_actual)) if total_pick and total_pick != "6+" else (total_actual >= 6 if total_pick == "6+" else None)
    btts_hit = btts_pick == btts_actual if btts_pick else None
    score_trace = decisions.get("score_selection_trace") or {}
    misses = []
    if primary_hit is False:
        misses.append(f"{primary_market}首推{primary_pick}，实际{primary_actual}")
    if score_hit is False:
        misses.append(f"唯一比分{score_pick[0]}-{score_pick[1]}，实际{actual_score}；相邻比分不计命中")
    if total_hit is False:
        misses.append(f"总进球众数{total_pick}，实际{total_actual}")
    if btts_hit is False:
        misses.append(f"BTTS首选{btts_pick}，实际{btts_actual}")
    classification = "主维度命中" if primary_hit is True else "主维度错误" if primary_hit is False else "主维度走盘/不可结算"
    report_match = report.get("match") or {}
    maximum_errors = decisions.get("maximum_error_points") or []
    probability = _probability(report, actual_outcome)
    summary = (
        f"90分钟{actual_score}（{actual_outcome}）。{classification}；"
        f"唯一比分{'精确命中' if score_hit else '未命中' if score_hit is False else '无有效首推'}；"
        f"总进球{'命中' if total_hit else '未命中' if total_hit is False else '不可结算'}；"
        f"BTTS{'命中' if btts_hit else '未命中' if btts_hit is False else '不可结算'}。"
    )
    score_trace = score_trace or {
        "method": "legacy_report_without_trace",
        "selected_score": f"{score_pick[0]}-{score_pick[1]}" if score_pick else None,
        "confidence": "旧报告未保存",
        "main_risk": "只能复核冻结比分，无法还原候选综合评分",
        "candidates": [],
    }
    outcome_pick = max(((report.get("model") or {}).get("probabilities") or {}), key=((report.get("model") or {}).get("probabilities") or {}).get, default=None)
    outcome_label = {"home": "主胜", "draw": "平局", "away": "客胜"}.get(outcome_pick)
    outcome_hit = outcome_label == actual_outcome if outcome_label else None
    process = {
        "半场比分": evidence.get("score_half_time") or "未取得",
        "关键事件": evidence.get("key_events") or [],
        "技术统计": evidence.get("statistics") or {},
        "阵型": evidence.get("formations") or {},
        "场地天气": evidence.get("environment") or "未取得",
        "事实来源": evidence.get("source_url") or "未取得Nowscore赛后详情",
    }
    data_quality = report.get("data_quality") or {}
    missing = [str(item) for item in data_quality.get("missing") or [] if item]
    checkpoint_count = len(_checkpoint_rows(report))
    if evidence.get("status") == "score_conflict":
        data_grade, calibration_weight = "D", 0.0
    elif not missing and checkpoint_count >= 4:
        data_grade, calibration_weight = "A", 1.0
    elif len(missing) <= 1 and checkpoint_count >= 2:
        data_grade, calibration_weight = "B", 0.7
    else:
        data_grade, calibration_weight = "C", 0.4
    error_tags = []
    if primary_hit is False:
        error_tags.append("direction_error")
        if primary_actual == "平局":
            error_tags.append("draw_underestimated")
        elif primary_actual == "客胜":
            error_tags.append("away_tail_missed")
    if score_hit is False:
        actual_rank = diagnostics.get("actual_score_rank")
        if actual_rank is not None and int(actual_rank) <= 5:
            if score_trace.get("selected_score") != score_trace.get("mathematical_first_score"):
                error_tags.append("selector_override_error")
            else:
                error_tags.append("score_matrix_top5_miss")
        elif actual_rank is not None and int(actual_rank) <= 10:
            error_tags.append("score_matrix_rank_error")
        elif actual_rank is not None:
            error_tags.append("score_matrix_tail_error")
        else:
            error_tags.append("score_selector_error")
    if total_hit is False:
        error_tags.append("goal_total_error")
    if btts_hit is False:
        error_tags.append("btts_error")
    if not checkpoint_count:
        error_tags.append("insufficient_snapshots")
    for item in missing:
        if "首发" in item:
            error_tags.append("missing_lineup")
        elif "伤停" in item:
            error_tags.append("missing_injury")
        elif "赔率" in item or "价格" in item:
            error_tags.append("missing_market_price")
    error_tags = list(dict.fromkeys(error_tags))
    formal_pick_eligible = data_grade in {"A", "B"} and primary_pick is not None
    execution_eligible = formal_pick_eligible and bool((report.get("betting") or {}).get("candidates"))
    quality_payload = {**data_quality, "data_grade": data_grade, "calibration_weight": calibration_weight,
                       "missing_count": len(missing), "checkpoint_count": checkpoint_count}
    return {
        "schema_version": "3.0",
        "generated_at": now.isoformat(),
        "match": {"home": schedule.get("home"), "away": schedule.get("away"), "kickoff_local": schedule.get("kickoff_local")},
        "result": {"score_90m": actual_score, "outcome": actual_outcome, "total_goals": total_actual, "btts": btts_actual, "scope": "90分钟含伤停，不含加时与点球"},
        "settlement": {
            "model_1x2": {"pick": outcome_label, "actual": actual_outcome, "hit": outcome_hit, "rule": "模型胜平负概率首位严格结算"},
            "primary": {
                "market": primary_market,
                "pick": primary_pick,
                "actual": primary_actual,
                "hit": primary_hit,
                "actual_probability": probability if primary_market == "胜平负" else None,
            },
            "exact_score": {"pick": f"{score_pick[0]}-{score_pick[1]}" if score_pick else None, "actual": actual_score, "hit": score_hit, "rule": "仅精确比分命中"},
            "total_goals_mode": {"pick": total_pick, "actual": total_actual, "hit": total_hit},
            "btts": {"pick": btts_pick, "actual": btts_actual, "hit": btts_hit},
            "expected_goals": {
                "pick": round(float((report.get("model") or {}).get("expected_goals") or 0), 3),
                "actual": total_actual,
                "hit": None,
                "rule": "连续预测不做红黑结算，使用总进球残差评估",
            },
        },
        "postmatch_evidence": evidence,
        "match_process": process,
        "model_diagnostics": diagnostics,
        "score_selection_audit": score_trace,
        "decision_evolution": _review_decision_evolution(report),
        "paper_ticket_settlements": _paper_tickets_for_match(str(schedule.get("home") or ""), str(schedule.get("away") or "")),
        "errors": misses,
        "maximum_error_points_prematch": maximum_errors,
        "market_movement_review": _movement(report),
        "data_quality_review": quality_payload,
        "data_grade": data_grade,
        "calibration_weight": calibration_weight,
        "prediction_layer": {
            "research": True,
            "formal_pick_eligible": formal_pick_eligible,
            "execution_eligible": execution_eligible,
        },
        "error_tags": error_tags,
        "source_report": schedule.get("source_report"),
        "bet_locked": False,
        "赛事与对阵": f"{schedule.get('home')} vs {schedule.get('away')}",
        "MatchID": str(schedule.get("match_key") or ""),
        "实际90分钟比分": actual_score,
        "主维度是否命中": "命中" if primary_hit else "未命中" if primary_hit is False else "不可结算",
        "比分是否命中": "精确命中" if score_hit else "未命中" if score_hit is False else "不可结算",
        "相邻比分污染": "不适用；相邻比分一律按未命中处理",
        "冷门/右尾污染": f"实际赛果在模型中的概率为{probability:.1%}" if probability is not None else "无有效概率",
        "红黑与模型逻辑分类": classification,
        "赛前三维交叉验证结论": decisions.get("mathematical_first"),
        "盘路性质判定": _movement(report),
        "赛前唯一首推比分": f"{score_pick[0]}-{score_pick[1]}" if score_pick else "无有效首推",
        "赛前首推主维度": decisions.get("unique_primary_dimension"),
        "赛前亚盘方向": decisions.get("asian_pick") or "未形成可严格结算合约",
        "赛前大小球方向": f"总进球众数 {total_pick}" if total_pick else "未形成可严格结算合约",
        "赛前BTTS判断": btts_pick or "未形成可严格结算合约",
        "赛前最大错点": "；".join(str(item) for item in maximum_errors),
        "错点归因（单选）": misses[0] if misses else "核心结算维度未发现错误",
        "最大错点类型": "模型方向错误" if primary_hit is False else "比分分布误差" if score_hit is False else "无核心错点",
        "复盘摘要": summary,
        "_timeline": {**_rich_market_timeline(report), "最终赛果验证": actual_score, "来源说明": "只使用真实保存的赛前快照，不用赛后价格回填。"},
        "_root_cause": _rich_root_cause(report, actual_outcome, actual_score, misses, classification, diagnostics, evidence),
    }


def generate(schedule_root: Path = SCHEDULE_ROOT, review_root: Path = REVIEW_ROOT, now: datetime | None = None) -> list[dict]:
    now = now or datetime.now(SHANGHAI)
    review_root.mkdir(parents=True, exist_ok=True)
    outcomes = []
    for path in sorted(schedule_root.glob("*.json")):
        schedule = load_json(path)
        if schedule.get("status") not in {"result_verified", "reviewed"} or not schedule.get("result_90m"):
            continue
        source_report = str(schedule.get("source_report") or "").strip()
        source = BASE_DIR / source_report if source_report else None
        # Result-only tasks intentionally have no model report.  Their verified
        # score still updates the workspace, but they must not enter the model
        # review builder or be interpreted as BASE_DIR itself.
        if source is None or not source.is_file():
            outcomes.append({"match_key": schedule.get("match_key"), "status": "missing_source_report"})
            continue
        review = build_review(schedule, load_json(source), now)
        actual = _score(schedule.get("result_90m"))
        if actual:
            review["real_bet_settlements"] = settle_real_bets(str(schedule.get("home") or ""), str(schedule.get("away") or ""), *actual)
        target = review_root / (re.sub(r"[^0-9A-Za-z._-]+", "_", str(schedule.get("match_key") or "match")).strip("_") + ".json")
        target.write_text(json.dumps(review, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        try:
            review_file = target.relative_to(BASE_DIR).as_posix()
        except ValueError:
            review_file = str(target)
        schedule.update({"status": "reviewed", "reviewed_at": now.isoformat(), "review_file": review_file})
        path.write_text(json.dumps(schedule, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        outcomes.append({"match_key": schedule.get("match_key"), "status": "reviewed", "review_file": schedule["review_file"]})
    return outcomes


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--schedule-root", type=Path, default=SCHEDULE_ROOT)
    parser.add_argument("--review-root", type=Path, default=REVIEW_ROOT)
    args = parser.parse_args()
    schedule_root = args.schedule_root if args.schedule_root.is_absolute() else BASE_DIR / args.schedule_root
    review_root = args.review_root if args.review_root.is_absolute() else BASE_DIR / args.review_root
    outcomes = generate(schedule_root, review_root)
    try:
        from review_metrics import build_metrics
        build_metrics(review_root)
    except Exception as exc:
        outcomes.append({"status": "metrics_failed", "error": str(exc)})
    print(json.dumps({"reviewed": len([row for row in outcomes if row['status'] == 'reviewed']), "outcomes": outcomes}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
