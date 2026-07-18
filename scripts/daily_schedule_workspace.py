#!/usr/bin/env python3
"""Refresh only the daily Sporttery schedule and rebuild the unified workspace."""

from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timedelta
from pathlib import Path

from fetch_sporttery import DEFAULT_CACHE_DIR, fetch_jingcai_odds
from fetch_trade_matches import fetch_trade_matches
from match_workspace import ROOT, build
from nowscore_markets import fetch_schedule as fetch_nowscore_schedule, prebind_match


def _kickoff(row: dict) -> str:
    match_date = str(row.get("matchDate") or row.get("businessDate") or "")[:10]
    match_time = str(row.get("matchTime") or "")[:5]
    return f"{match_date}T{match_time}:00+08:00" if match_date and match_time else ""


def attach_nowscore_bindings(payloads: list[dict]) -> dict:
    """Resolve every fixture once during schedule intake, before analysis is requested."""
    try:
        provider_schedule = fetch_nowscore_schedule()
    except Exception as error:
        return {"status": "FETCH_ERROR", "error": f"{type(error).__name__}: {error}", "bound": 0}
    bound = ambiguous = missing = 0
    for payload in payloads:
        for row in payload.get("matches") or []:
            resolved = prebind_match(row.get("homeTeam") or "", row.get("awayTeam") or "", _kickoff(row), provider_schedule)
            status = str(resolved.get("status") or "")
            row["nowscoreMatchStatus"] = status
            row["nowscoreMatchConfidence"] = resolved.get("match_confidence")
            if resolved.get("nowscore_id"):
                row["nowscoreId"] = int(resolved["nowscore_id"])
                row["nowscoreProviderHome"] = resolved.get("home_team")
                row["nowscoreProviderAway"] = resolved.get("away_team")
                bound += 1
            elif status in {"AMBIGUOUS_MATCH", "LOW_CONFIDENCE_MATCH"}:
                ambiguous += 1
            else:
                missing += 1
    return {"status": "OK", "schedule_count": len(provider_schedule), "bound": bound, "ambiguous": ambiguous, "missing": missing}


def fallback_trade_schedule(business_date: str, no_cache: bool) -> dict:
    """Map the visible 500.com sales list to the canonical schedule contract."""
    trade = fetch_trade_matches(business_date, no_cache=no_cache)
    matches = []
    for row in trade.get("matches") or []:
        kickoff = str(row.get("kickoff_local") or "")
        matches.append({
            "matchId": f"500-{row.get('shuju_id')}",
            "matchNum": row.get("match_num"),
            "homeTeam": row.get("home_team"),
            "awayTeam": row.get("away_team"),
            "league": row.get("competition"),
            "businessDate": business_date,
            "matchDate": kickoff[:10],
            "matchTime": kickoff[11:16],
            "spf": row.get("official_spf_visible"),
            "rqspf": row.get("official_rqspf_visible"),
            "shujuId": row.get("shuju_id"),
            "singleMatchAvailable": bool(row.get("single_match_available")),
        })
    return {
        "source": "trade.500.com",
        "primary_source": "sporttery.cn",
        "fallback_reason": "official_schedule_unavailable",
        "url": trade.get("url"),
        "fetch_time": trade.get("fetch_time") or datetime.now().astimezone().isoformat(),
        "date": business_date,
        "success": bool(matches),
        "matches": matches,
        "status": "OK_FALLBACK_500" if matches else str(trade.get("status") or "FALLBACK_FAILED"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="每日体彩赛程更新（不自动分析）")
    parser.add_argument("--date", default=date.today().isoformat())
    parser.add_argument("--no-cache", action="store_true")
    parser.add_argument("--fetch-only", action="store_true", help="只刷新赛程数据，由后续步骤统一重建页面")
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
        if not payload.get("success"):
            fallback = fallback_trade_schedule(business_date, args.no_cache)
            if fallback.get("success"):
                payload = fallback
        payloads.append(payload)
    nowscore_binding = attach_nowscore_bindings(payloads)
    for offset, payload in enumerate(payloads):
        business_date = str(payload.get("date") or (base_date + timedelta(days=offset)).isoformat())
        payload["nowscore_binding"] = nowscore_binding
        schedule_path = output_dir / f"{stamp}_sporttery_{business_date}.json"
        schedule_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        schedule_paths.append(schedule_path)
    match_ids = {
        str(row.get("matchId") or "|".join(str(row.get(key) or "") for key in ("matchNum", "homeTeam", "awayTeam")))
        for payload in payloads
        for row in payload.get("matches") or []
    }
    successful_payloads = [payload for payload in payloads if payload.get("success")]
    # 抓取全部失败时保留旧工作台。失败诊断文件可以落盘，但绝不能用新的页面
    # 生成时间伪装成赛程已更新。
    if not successful_payloads:
        print(json.dumps({
            "date": args.date,
            "schedules": [str(path) for path in schedule_paths],
            "match_count": 0,
            "refresh_status": "failed_kept_previous_workspace",
            "workspace_rebuilt": False,
            "automatic_analysis": False,
            "automatic_betting": False,
            "lock_state_changed": False,
        }, ensure_ascii=False, indent=2))
        return 1

    index = latest = ROOT / "data" / "match_workspace" / "latest.html"
    if not args.fetch_only:
        index, latest = build(args.date)
    print(json.dumps({
        "date": args.date, "schedule": str(schedule_paths[0]),
        "schedules": [str(path) for path in schedule_paths], "match_count": len(match_ids),
        "workspace": str(latest), "workspace_snapshot": str(index), "latest": str(latest),
        "user_entry": str(latest), "automatic_analysis": False,
        "automatic_betting": False, "lock_state_changed": False,
        "refresh_status": "success" if len(successful_payloads) == len(payloads) else "partial_success",
        "nowscore_binding": nowscore_binding,
        "workspace_rebuilt": not args.fetch_only,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
