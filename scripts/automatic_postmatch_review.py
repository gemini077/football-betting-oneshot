#!/usr/bin/env python3
"""Create strict, comprehensive reviews from frozen reports and verified 90m results."""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path
from statistics import mean, median
from typing import Any

from market_history import load_history
from postmatch_queue import BASE_DIR, SHANGHAI, load_json
from match_identity import identity_aliases


SCHEDULE_ROOT = BASE_DIR / "data" / "postmatch_automation" / "schedules"
REVIEW_ROOT = BASE_DIR / "data" / "postmatch_reviews"
REAL_BET_ROOT = BASE_DIR / "data" / "real_bets"


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
            "判断如何变化": "无有效节点，无法证明判断曾发生变化。",
            "最后有效判断": str((report.get("decisions") or {}).get("unique_primary_dimension") or "未形成"),
            "数据有效性": "仅复盘冻结报告本身，不能声称资金持续流入或机构连续调整。",
        }
    changes, previous = [], None
    for row in rows:
        decision = row.get("decision") or {}
        probs = decision.get("probabilities") or {}
        leader = max(probs, key=probs.get) if probs else None
        snapshot = {"leader": leader, "primary": decision.get("primary_dimension"), "score": decision.get("unique_score")}
        if previous is None:
            changes.append(f"首次判断：{snapshot['primary'] or '主维度未形成'}；比分 {snapshot['score'] or '未收敛'}。")
        else:
            parts = []
            if snapshot["leader"] != previous["leader"]:
                parts.append(f"胜平负首位由 {previous['leader'] or '未形成'} 变为 {snapshot['leader'] or '未形成'}")
            if snapshot["primary"] != previous["primary"]:
                parts.append(f"主维度由“{previous['primary']}”变为“{snapshot['primary']}”")
            if snapshot["score"] != previous["score"]:
                parts.append(f"比分由 {previous['score']} 调整为 {snapshot['score']}")
            if parts:
                changes.append("；".join(parts) + "。")
        previous = snapshot
    last = rows[-1].get("decision") or {}
    late = sum(1 for row in rows if row.get("capture_quality") == "late_recovery" or float(row.get("lateness_minutes") or 0) > 25)
    return {
        "快照覆盖": f"共保存 {len(rows)} 个独立赛前快照，其中 {late} 个为延迟恢复快照；每个节点只使用当时真实价格。",
        "判断如何变化": " ".join(changes) if changes else "核心判断始终未越过模型决策边界。",
        "临盘资金与机构行为": str(last.get("bookmaker_behaviour") or last.get("purpose") or "无真实成交量证据，只依据多公司价格方向判断市场压力。"),
        "对最终判断的影响": str(last.get("model_impact") or "盘口信息未达到推翻基本模型的阈值。"),
        "最后有效判断": f"{last.get('primary_dimension') or '未形成'}；比分 {last.get('unique_score') or '未收敛'}。",
        "数据有效性": "延迟快照明确标记，不补造错过的节点；缺少交易量时不把赔率变化冒充真实资金流。",
    }


def _rich_root_cause(report: dict, actual_outcome: str, actual_score: str, misses: list[str], classification: str) -> dict:
    rows = _checkpoint_rows(report)
    decisions = report.get("decisions") or {}
    score_rows = (report.get("model") or {}).get("score_probabilities") or []
    rank = next((i + 1 for i, row in enumerate(score_rows) if str(row.get("score")) == actual_score), None)
    risks = [str(item) for item in decisions.get("maximum_error_points") or [] if item]
    primary_values = {str((row.get("decision") or {}).get("primary_dimension")) for row in rows if row.get("decision")}
    stable = len(primary_values) <= 1
    if not misses:
        cause = "主维度结算正确；仍独立检查比分和附属市场，不用方向命中掩盖其他错误。"
    elif stable:
        cause = "方向在有效快照中保持稳定，但实际赛果落在模型次要分支；主要误差来自概率校准而非临场反转。"
    else:
        cause = "赛前判断发生过反转，最终快照没有充分吸收冲突信号；临盘权重或冲突处理是首要检查项。"
    return {
        "结算错项": "；".join(misses) if misses else "主维度无错误；附属维度按各自规则独立结算。",
        "最可能根因": cause,
        "赛前已知风险": "；".join(risks) if risks else "冻结报告没有列出可验证的额外风险点。",
        "反事实条件": f"只有独立赛前信息把“{actual_outcome}”推到首位，或使原首推跌破执行边界，才应改变结论；不能用赛后比分倒推。",
        "比分误差定位": f"实际比分 {actual_score} 在赛前矩阵排名第 {rank}。" if rank else f"实际比分 {actual_score} 未进入主要比分区间。",
        "模型修正": "本场进入同类样本池，不改单场参数；累计至少 20 场后分别校准方向概率、低比分相关性和临盘冲突权重。",
        "修正状态": "观察池；禁止因单场结果追改参数。",
        "复盘结论": classification,
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
    score_hit = score_pick == actual if score_pick else None
    total_hit = (total_pick == str(total_actual)) if total_pick and total_pick != "6+" else (total_actual >= 6 if total_pick == "6+" else None)
    btts_hit = btts_pick == btts_actual if btts_pick else None
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
    return {
        "schema_version": "2.0",
        "generated_at": now.isoformat(),
        "match": {"home": schedule.get("home"), "away": schedule.get("away"), "kickoff_local": schedule.get("kickoff_local")},
        "result": {"score_90m": actual_score, "outcome": actual_outcome, "total_goals": total_actual, "btts": btts_actual, "scope": "90分钟含伤停，不含加时与点球"},
        "settlement": {
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
        },
        "errors": misses,
        "maximum_error_points_prematch": maximum_errors,
        "market_movement_review": _movement(report),
        "data_quality_review": report.get("data_quality") or {},
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
        "_root_cause": _rich_root_cause(report, actual_outcome, actual_score, misses, classification),
    }


def generate(schedule_root: Path = SCHEDULE_ROOT, review_root: Path = REVIEW_ROOT, now: datetime | None = None) -> list[dict]:
    now = now or datetime.now(SHANGHAI)
    review_root.mkdir(parents=True, exist_ok=True)
    outcomes = []
    for path in sorted(schedule_root.glob("*.json")):
        schedule = load_json(path)
        if schedule.get("status") not in {"result_verified", "reviewed"} or not schedule.get("result_90m"):
            continue
        source = BASE_DIR / str(schedule.get("source_report") or "")
        if not source.exists():
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
    print(json.dumps({"reviewed": len([row for row in outcomes if row['status'] == 'reviewed']), "outcomes": outcomes}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
