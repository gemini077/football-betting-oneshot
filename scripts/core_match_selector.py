#!/usr/bin/env python3
"""Select a deliberately small core-event pool for automatic reports."""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
SHANGHAI = ZoneInfo("Asia/Shanghai")
MAJOR = ("世界杯", "欧洲杯", "欧锦赛", "美洲杯", "亚洲杯")
TOP_FIVE = ("英超", "英格兰超级", "西甲", "西班牙甲", "德甲", "德国甲", "意甲", "意大利甲", "法甲", "法国甲")
SECONDARY = ("欧冠", "欧洲冠军", "欧联", "欧洲联赛", "欧协联")
EXCLUDE = ("友谊", "热身", "青年", "U17", "U19", "U20", "U21", "U23", "女足", "资格", "预选")


def _odds_complete(row: dict) -> bool:
    spf = row.get("spf") or {}
    return all(isinstance(spf.get(key), (int, float)) and float(spf[key]) > 1 for key in ("home", "draw", "away"))


def classify(row: dict) -> dict:
    league = str(row.get("league") or "")
    excluded = next((term for term in EXCLUDE if term.casefold() in league.casefold()), None)
    if excluded:
        return {"eligible": False, "score": 0, "tier": "excluded", "reason": f"排除低稳定性赛事：{excluded}"}
    if any(term in league for term in MAJOR):
        base, tier, reason = 96, "S", "世界级国家队正赛"
    elif any(term in league for term in SECONDARY):
        base, tier, reason = 88, "S", "欧洲俱乐部核心赛事"
    elif any(term in league for term in TOP_FIVE):
        base, tier, reason = 78, "A", "五大联赛"
    else:
        return {"eligible": False, "score": 0, "tier": "outside", "reason": "不在自动核心赛事池"}
    provider_bound = bool(row.get("nowscore_id") or row.get("nowscoreId"))
    if provider_bound:
        base += 5
        reason += "；Nowscore已唯一绑定"
    if _odds_complete(row):
        base += 4
        reason += "；体彩价格完整"
    if not provider_bound:
        reason += "；等待Nowscore唯一绑定"
    return {"eligible": base >= 82 and provider_bound, "score": min(base, 100), "tier": tier, "reason": reason}


def select(matches: list[dict], now: datetime | None = None) -> list[dict]:
    now = (now or datetime.now(SHANGHAI)).astimezone(SHANGHAI)
    major_day = any(classify(row).get("tier") == "S" and classify(row).get("eligible") for row in matches)
    daily_cap = 8 if major_day else (6 if now.weekday() >= 5 else 4)
    candidates = []
    for row in matches:
        result = classify(row)
        if not result["eligible"] or row.get("report_url") or str(row.get("report_state") or "") == "已分析":
            continue
        candidates.append({**row, "core_tier": result["tier"], "core_score": result["score"], "core_reason": result["reason"]})
    candidates.sort(key=lambda row: (-row["core_score"], str(row.get("kickoff") or ""), str(row.get("match_num") or "")))
    selected, kickoff_counts = [], Counter()
    for row in candidates:
        slot = str(row.get("kickoff") or "")
        if kickoff_counts[slot] >= 2:
            continue
        selected.append(row)
        kickoff_counts[slot] += 1
        if len(selected) >= daily_cap:
            break
    return selected


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, default=ROOT / "data" / "match_workspace" / "latest.json")
    parser.add_argument("--output", type=Path, default=ROOT / "data" / "analysis_jobs" / "core_auto_queue.json")
    args = parser.parse_args()
    payload = json.loads(args.workspace.read_text(encoding="utf-8"))
    rows = select(payload.get("matches") or [])
    output = {"schema_version": "1.0", "generated_at": datetime.now(SHANGHAI).isoformat(), "matches": rows}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"selected": len(rows), "output": str(args.output)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
