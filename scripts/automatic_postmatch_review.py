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


SCHEDULE_ROOT = BASE_DIR / "data" / "postmatch_automation" / "schedules"
REVIEW_ROOT = BASE_DIR / "data" / "postmatch_reviews"


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
    value = (report.get("model") or {}).get("probabilities", {}).get(key)
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
    intelligence = report.get("market_intelligence") or {}
    risk = report.get("risk_engine") or {}
    decisions = report.get("decisions") or {}
    pieces = []
    if decisions.get("market_movement"):
        pieces.append(str(decisions["market_movement"]))
    modules = intelligence.get("modules") or {}
    for key, label in (("lead_lag", "升降盘"), ("water_flow", "水位"), ("exchange", "交易所")):
        module = modules.get(key) or {}
        if module.get("summary") or module.get("reason"):
            pieces.append(f"{label}：{module.get('summary') or module.get('reason')}")
    traps = (risk.get("traps") or {}).get("triggered") or []
    if traps:
        pieces.append("陷阱：" + "；".join(str(item.get("name") or item) for item in traps[:3]))
    return "；".join(pieces) or "赛前报告未形成可结算的多帧临盘信号"


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
        misses.append(f"胜平负首推{primary_pick}，实际{actual_outcome}")
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
        "_timeline": {**_market_timeline(report), "盘口变化与赛果方向": _movement(report), "最终赛果验证": actual_score, "来源/备注": "自动复盘读取冻结赛前报告；没有的时间节点明确保留为空，不用赛后价格回填"},
        "_root_cause": {"决策节点审计": "；".join(misses) or "主维度及辅助维度结算通过", "反事实推演": "若赛前最大错点发生，应降低概率置信度而不是改写唯一首推", "赛前可识别性": "以冻结报告中已记录错点为准", "是否修改模型": "进入累计样本，达到阈值后再修正", "具体修改建议": "按玩法分别累计校准，不以单场结果追改参数", "收敛结论": classification, "生效状态": "观察池", "优先级": "P1" if primary_hit is False else "P2"},
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
