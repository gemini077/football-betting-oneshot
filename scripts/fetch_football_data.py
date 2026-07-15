#!/usr/bin/env python3
"""Unified read-only football data acquisition entrypoint for this project."""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path

from fetch_and_parse import DEFAULT_CACHE_DIR as DEEP_CACHE_DIR
from fetch_and_parse import fetch_and_parse
from fetch_sporttery import DEFAULT_CACHE_DIR as SPORTTERY_CACHE_DIR
from fetch_sporttery import fetch_jingcai_odds
from fetch_trade_matches import DEFAULT_CACHE_DIR as TRADE_CACHE_DIR
from fetch_trade_matches import fetch_trade_matches
from liansai_api import fetch as fetch_liansai_round
from liansai_api import fetch_all as fetch_liansai_all
from market_history import rebuild_history
from polymarket_public import fetch_snapshot as fetch_polymarket_snapshot


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RUNS_ROOT = PROJECT_ROOT / "data" / "fetch_runs"
STATE_PATH = PROJECT_ROOT / "05_RUNTIME_STATE.json"


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _unique_run_dir(root: Path, stamp: str) -> Path:
    candidate = root / stamp
    suffix = 1
    while candidate.exists():
        candidate = root / f"{stamp}_{suffix:02d}"
        suffix += 1
    candidate.mkdir(parents=True, exist_ok=False)
    return candidate


def _parse_ids(raw_ids: list[str]) -> list[int]:
    result = []
    for raw in raw_ids:
        for value in raw.split(","):
            value = value.strip()
            if value:
                result.append(int(value))
    return list(dict.fromkeys(result))


def _match_filter(matches: list[dict], query: str | None) -> list[dict]:
    if not query:
        return matches

    def folded(value: object) -> str:
        return re.sub(r"[^0-9a-z\u4e00-\u9fff]", "", str(value or "").casefold())

    def same_team(left: str, right: str) -> bool:
        return bool(left and right and (left == right or left in right or right in left))

    query_text = str(query).strip()
    pair = re.split(r"\s*(?:vs?\.?|对阵)\s*|\s+[—–-]\s+", query_text, maxsplit=1, flags=re.IGNORECASE)
    if len(pair) == 2 and all(folded(value) for value in pair):
        query_home, query_away = map(folded, pair)
        paired_matches = []
        for match in matches:
            home = folded(match.get("home_team") or match.get("homeTeam"))
            away = folded(match.get("away_team") or match.get("awayTeam"))
            if (same_team(query_home, home) and same_team(query_away, away)) or (
                same_team(query_home, away) and same_team(query_away, home)
            ):
                paired_matches.append(match)
        return paired_matches

    query_folded = folded(query_text)
    return [
        match for match in matches
        if query_folded in folded(match.get("home_team") or match.get("homeTeam"))
        or query_folded in folded(match.get("away_team") or match.get("awayTeam"))
        or query_folded in folded(match.get("competition") or match.get("league"))
        or query_folded in folded(match.get("match_num") or match.get("matchNum"))
        or query_folded == folded(match.get("match_id") or match.get("matchId"))
    ]


def _deep_summary(result: dict) -> dict:
    pages = ["ouzhi", "yazhi", "rangqiu", "daxiao", "shuju", "touzhu"]
    page_status = {}
    for page in pages:
        data = result.get(page)
        if isinstance(data, dict) and data.get("error"):
            page_status[page] = data["error"]
        elif data is None:
            page_status[page] = "missing"
        else:
            page_status[page] = "ok"
    return {
        "shuju_id": result.get("shuju_id"),
        "page_status": page_status,
        "all_pages_ok": all(value == "ok" for value in page_status.values()),
    }


def main() -> int:
    state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    model_name = state.get("model_name", "Football Betting OneShot")
    model_version = state.get("model_version", "v0.12.0")
    parser = argparse.ArgumentParser(description=f"{model_name} {model_version} 统一数据抓取入口")
    parser.add_argument("--date", required=True, help="竞彩业务日期 YYYY-MM-DD；比赛可能在次日凌晨开球")
    parser.add_argument("--match", help="按球队、赛事或竞彩编号筛选")
    parser.add_argument("--deep", action="store_true", help="对筛选后的比赛抓取500.com六个深层页面")
    parser.add_argument("--shuju-id", action="append", default=[], help="指定一个或逗号分隔的shuju_id")
    parser.add_argument("--sid", type=int, help="可选：500联赛season ID")
    parser.add_argument("--round", help="可选：联赛轮次或小组，例如A")
    parser.add_argument("--skip-sporttery", action="store_true", help="不抓中国竞彩主源")
    parser.add_argument("--skip-trade", action="store_true", help="不抓500竞彩比赛列表")
    parser.add_argument("--skip-polymarket", action="store_true", help="不抓Polymarket公开只读市场证据")
    parser.add_argument("--polymarket-home", help="Polymarket赛事匹配用英文主队名；中文队名无法可靠匹配时使用")
    parser.add_argument("--polymarket-away", help="Polymarket赛事匹配用英文客队名；须与--polymarket-home同时使用")
    parser.add_argument("--polymarket-kickoff", help="可选：ISO开球时间；用于防止同队名错配")
    parser.add_argument("--no-cache", action="store_true", help="强制刷新全部已选择来源")
    parser.add_argument("--output-root", default=str(RUNS_ROOT), help="不可变抓取批次输出根目录")
    args = parser.parse_args()

    now = datetime.now().astimezone()
    stamp = now.strftime("%Y%m%d_%H%M%S")
    run_dir = _unique_run_dir(Path(args.output_root), stamp)
    manifest = {
        "model_name": model_name,
        "model_version": model_version,
        "run_id": run_dir.name,
        "fetch_time": now.isoformat(),
        "target_date": args.date,
        "match_filter": args.match,
        "analysis_input_only": True,
        "lock_state_changed": False,
        "sources": {},
        "warnings": [],
    }

    trade_result = {"success": False, "matches": [], "status": "SKIPPED"}
    official_matches = []

    if not args.skip_sporttery:
        official = fetch_jingcai_odds(args.date, args.no_cache, SPORTTERY_CACHE_DIR)
        official_unfiltered_count = len(official.get("matches", []))
        official["matches"] = _match_filter(official.get("matches", []), args.match)
        official_matches = official["matches"]
        official["unfiltered_match_count"] = official_unfiltered_count
        official_selected_success = official.get("success", False) and bool(official["matches"])
        official_selected_status = official.get("status") if official_selected_success else "NO_MATCHES_AFTER_FILTER"
        official_path = run_dir / f"{stamp}_sporttery_{args.date}.json"
        _write_json(official_path, official)
        manifest["sources"]["sporttery"] = {
            "status": official_selected_status,
            "success": official_selected_success,
            "match_count": len(official.get("matches", [])),
            "file": str(official_path.relative_to(PROJECT_ROOT)).replace("\\", "/"),
        }
        if not official_selected_success:
            manifest["warnings"].append("中国竞彩主源未返回目标日期的有效赔率，需要使用500.com可见官方行降级。")

    if not args.skip_trade:
        trade_result = fetch_trade_matches(args.date, args.no_cache, TRADE_CACHE_DIR)
        selected_matches = _match_filter(trade_result.get("matches", []), args.match)
        trade_output = {**trade_result, "matches": selected_matches, "unfiltered_match_count": len(trade_result.get("matches", []))}
        trade_path = run_dir / f"{stamp}_500_trade_{args.date}.json"
        _write_json(trade_path, trade_output)
        manifest["sources"]["500_trade"] = {
            "status": trade_result.get("status"),
            "success": trade_result.get("success", False),
            "match_count": len(selected_matches),
            "file": str(trade_path.relative_to(PROJECT_ROOT)).replace("\\", "/"),
        }
        if args.match and not selected_matches:
            manifest["warnings"].append("500竞彩列表中未找到匹配筛选条件的比赛。")
    else:
        selected_matches = []

    if not args.skip_polymarket:
        if bool(args.polymarket_home) != bool(args.polymarket_away):
            parser.error("--polymarket-home 与 --polymarket-away 必须同时提供")
        identity_match = (selected_matches or official_matches or [{}])[0]
        poly_home = args.polymarket_home or identity_match.get("home_team") or identity_match.get("homeTeam")
        poly_away = args.polymarket_away or identity_match.get("away_team") or identity_match.get("awayTeam")
        poly_kickoff = (
            args.polymarket_kickoff
            or identity_match.get("kickoff_local")
            or " ".join(filter(None, [identity_match.get("matchDate"), identity_match.get("matchTime")]))
            or None
        )
        if not poly_home or not poly_away:
            polymarket = {
                "schema_version": "1.0",
                "source": "polymarket_public_gamma",
                "analysis_input_only": True,
                "authentication_used": False,
                "account_connected": False,
                "trading_enabled": False,
                "match": {"status": "NO_MATCH_IDENTITY"},
                "quality_flags": ["NO_MATCH_IDENTITY"],
            }
        elif not args.polymarket_home and not all(str(value).isascii() for value in (poly_home, poly_away)):
            polymarket = {
                "schema_version": "1.0",
                "source": "polymarket_public_gamma",
                "analysis_input_only": True,
                "authentication_used": False,
                "account_connected": False,
                "trading_enabled": False,
                "target": {"home": poly_home, "away": poly_away, "kickoff": poly_kickoff},
                "match": {"status": "NEEDS_ENGLISH_TEAM_ALIASES"},
                "quality_flags": ["NEEDS_ENGLISH_TEAM_ALIASES"],
            }
        else:
            try:
                polymarket = fetch_polymarket_snapshot(poly_home, poly_away, poly_kickoff)
            except Exception as exc:  # public market evidence must never break the primary fetch
                polymarket = {
                    "schema_version": "1.0",
                    "source": "polymarket_public_gamma",
                    "analysis_input_only": True,
                    "authentication_used": False,
                    "account_connected": False,
                    "trading_enabled": False,
                    "target": {"home": poly_home, "away": poly_away, "kickoff": poly_kickoff},
                    "match": {"status": "FETCH_ERROR"},
                    "quality_flags": ["FETCH_ERROR"],
                    "error": f"{type(exc).__name__}: {exc}",
                }
        polymarket_path = run_dir / f"{stamp}_polymarket_{args.date}.json"
        _write_json(polymarket_path, polymarket)
        poly_success = polymarket.get("match", {}).get("status") == "EXACT_EVENT_MATCH"
        manifest["sources"]["polymarket"] = {
            "status": polymarket.get("match", {}).get("status", "UNKNOWN"),
            "success": poly_success,
            "match_count": 1 if poly_success else 0,
            "file": str(polymarket_path.relative_to(PROJECT_ROOT)).replace("\\", "/"),
            "analysis_input_only": True,
            "execution_source": False,
        }
        if not poly_success:
            manifest["warnings"].append("Polymarket未可靠匹配目标赛事；该来源已降级，不影响其他赛前数据。")

    if args.sid:
        liansai_matches = (
            fetch_liansai_round(args.sid, args.round)
            if args.round
            else fetch_liansai_all(args.sid)
        )
        liansai_matches = [
            match for match in liansai_matches
            if str(match.get("stime", "")).startswith(args.date)
        ]
        liansai_path = run_dir / f"{stamp}_500_liansai_{args.sid}_{args.round or 'all'}_{args.date}.json"
        _write_json(liansai_path, liansai_matches)
        manifest["sources"]["500_liansai"] = {
            "status": "OK" if liansai_matches else "NO_MATCHES_FOR_DATE",
            "success": bool(liansai_matches),
            "match_count": len(liansai_matches),
            "file": str(liansai_path.relative_to(PROJECT_ROOT)).replace("\\", "/"),
        }

    deep_ids = _parse_ids(args.shuju_id)
    discovered_by_id = {int(match["shuju_id"]): match for match in selected_matches if match.get("shuju_id")}
    if args.deep:
        deep_ids.extend(discovered_by_id)
        deep_ids = list(dict.fromkeys(deep_ids))

    deep_summaries = []
    for shuju_id in deep_ids:
        result = fetch_and_parse(shuju_id, args.date, DEEP_CACHE_DIR, args.no_cache)
        deep_path = run_dir / f"{stamp}_500_deep_{args.date}_{shuju_id}.json"
        _write_json(deep_path, result)
        summary = _deep_summary(result)
        summary["file"] = str(deep_path.relative_to(PROJECT_ROOT)).replace("\\", "/")
        history_path = rebuild_history(shuju_id)
        summary["history_file"] = str(history_path.relative_to(PROJECT_ROOT)).replace("\\", "/")
        if shuju_id in discovered_by_id:
            summary["match"] = discovered_by_id[shuju_id]
        deep_summaries.append(summary)
    if deep_ids:
        manifest["sources"]["500_deep"] = {
            "status": "OK" if deep_summaries and all(item["all_pages_ok"] for item in deep_summaries) else "PARTIAL",
            "success": bool(deep_summaries),
            "match_count": len(deep_summaries),
            "matches": deep_summaries,
        }
    elif args.deep:
        manifest["warnings"].append("已请求深层抓取，但没有可用的shuju_id。")

    manifest_path = run_dir / f"{stamp}_fetch_manifest.json"
    _write_json(manifest_path, manifest)
    print(json.dumps({
        "run_id": manifest["run_id"],
        "run_dir": str(run_dir),
        "manifest": str(manifest_path),
        "sources": manifest["sources"],
        "warnings": manifest["warnings"],
        "lock_state_changed": False,
    }, ensure_ascii=False, indent=2))

    any_success = any(source.get("success") for source in manifest["sources"].values())
    return 0 if any_success else 1


if __name__ == "__main__":
    raise SystemExit(main())
