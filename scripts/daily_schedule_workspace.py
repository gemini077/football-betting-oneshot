#!/usr/bin/env python3
"""Refresh only the daily Sporttery schedule and rebuild the unified workspace."""

from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timedelta
from pathlib import Path

from fetch_sporttery import DEFAULT_CACHE_DIR, fetch_jingcai_odds
from match_workspace import ROOT, build


def main() -> int:
    parser = argparse.ArgumentParser(description="每日体彩赛程更新（不自动分析）")
    parser.add_argument("--date", default=date.today().isoformat())
    parser.add_argument("--no-cache", action="store_true")
    args = parser.parse_args()
    now = datetime.now().astimezone()
    stamp = now.strftime("%Y%m%d_%H%M%S")
    output_dir = ROOT / "data" / "schedule_updates" / stamp
    output_dir.mkdir(parents=True, exist_ok=False)
    base_date = date.fromisoformat(args.date)
    payloads = []
    schedule_paths = []
    for offset in (0, 1):
        business_date = (base_date + timedelta(days=offset)).isoformat()
        payload = fetch_jingcai_odds(business_date, args.no_cache, DEFAULT_CACHE_DIR)
        schedule_path = output_dir / f"{stamp}_sporttery_{business_date}.json"
        schedule_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        payloads.append(payload)
        schedule_paths.append(schedule_path)
    index, latest = build(args.date)
    match_ids = {
        str(row.get("matchId") or "|".join(str(row.get(key) or "") for key in ("matchNum", "homeTeam", "awayTeam")))
        for payload in payloads
        for row in payload.get("matches") or []
    }
    print(json.dumps({
        "date": args.date, "schedule": str(schedule_paths[0]),
        "schedules": [str(path) for path in schedule_paths], "match_count": len(match_ids),
        "workspace": str(latest), "workspace_snapshot": str(index), "latest": str(latest),
        "user_entry": str(latest), "automatic_analysis": False,
        "automatic_betting": False, "lock_state_changed": False,
    }, ensure_ascii=False, indent=2))
    return 0 if all(payload.get("success") for payload in payloads) else 1


if __name__ == "__main__":
    raise SystemExit(main())
