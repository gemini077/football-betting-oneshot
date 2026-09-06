#!/usr/bin/env python3
"""
竞彩官网 (sporttery.cn) 赔率抓取器 v1.1

抓取策略: webapi REST API → 快速失败
- 🥇 主源: webapi.sporttery.cn REST API (SPA页面实际使用的数据接口)
- Official-source failure is reported directly; no third-party fallback is emitted.

修复记录:
  v1.1 (2026-06-26): 原脚本抓取 m.sporttery.cn 的 HTML 空壳页面,
    该页面是 SPA, 数据通过 AJAX 从 webapi REST API 加载。
    删除全部 HTML DOM 解析函数 (extract_matches_from_html 等),
    改为直接调用 REST API 获取 JSON 数据。
  
输出: JSON 到 data/source_cache/sporttery/{date}_jingcai.json
缓存: 1 小时

用法:
  python scripts/fetch_sporttery.py --date 2026-07-15 [--no-cache]
"""

import argparse
import gzip
import hashlib
import json
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timedelta
from pathlib import Path

# ── 配置 ──────────────────────────────────────────
SPORTTERY_POOL_CODE = "had,hhad,crs,ttg,hafu"
SPORTTERY_API = (
    "https://webapi.sporttery.cn/gateway/jc/football/"
    f"getMatchCalculatorV1.qry?channel=c&poolCode={SPORTTERY_POOL_CODE}"
)
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CACHE_DIR = PROJECT_ROOT / "data" / "source_cache" / "sporttery"
CACHE_TTL_HOURS = 1
USER_AGENT = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) "
    "Version/17.0 Mobile/15E148 Safari/604.1"
)
SPORTTERY_REQUEST_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Referer": "https://m.sporttery.cn/mjc/jsq/zqspf/",
    "Origin": "https://m.sporttery.cn",
    "X-Requested-With": "XMLHttpRequest",
    "Accept-Encoding": "gzip",
}
LAST_FETCH_METADATA: dict = {}

# ── 工具函数 ──────────────────────────────────────
def log(msg: str, level: str = "INFO"):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}][{level}] {msg}", file=sys.stderr)


def fetch_json(url: str, retries: int = 3) -> dict | None:
    """抓取 JSON API，带重试"""
    global LAST_FETCH_METADATA
    LAST_FETCH_METADATA = {
        "http_status": None,
        "response_bytes": 0,
        "raw_response_sha256": None,
        "content_type": None,
        "attempts": 0,
    }
    for attempt in range(retries):
        LAST_FETCH_METADATA["attempts"] = attempt + 1
        try:
            req = urllib.request.Request(
                url,
                headers=SPORTTERY_REQUEST_HEADERS,
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                wire = resp.read()
                raw = gzip.decompress(wire) if "gzip" in str(resp.headers.get("Content-Encoding") or "").casefold() else wire
                LAST_FETCH_METADATA.update({
                    "http_status": int(resp.getcode()),
                    "response_bytes": len(raw),
                    "raw_response_sha256": hashlib.sha256(raw).hexdigest(),
                    "wire_response_bytes": len(wire),
                    "wire_response_sha256": hashlib.sha256(wire).hexdigest(),
                    "content_type": str(resp.headers.get("Content-Type") or ""),
                })
                return json.loads(raw.decode("utf-8"))
        except urllib.error.HTTPError as e:
            raw = b""
            try:
                wire = e.read()
                raw = gzip.decompress(wire) if "gzip" in str(e.headers.get("Content-Encoding") if e.headers else "").casefold() else wire
            except Exception:
                wire = b""
                pass
            LAST_FETCH_METADATA.update({
                "http_status": int(e.code),
                "response_bytes": len(raw),
                "raw_response_sha256": hashlib.sha256(raw).hexdigest() if raw else None,
                "wire_response_bytes": len(wire),
                "wire_response_sha256": hashlib.sha256(wire).hexdigest() if wire else None,
                "content_type": str(e.headers.get("Content-Type") if e.headers else ""),
            })
            log(f"HTTP {e.code} attempt {attempt+1}/{retries}", "WARN")
            # GitHub runners may receive a stable gateway 567 here.  The
            # official lane never substitutes a third-party source.
            if e.code == 567:
                return None
        except Exception as e:
            log(f"Fetch error attempt {attempt+1}/{retries}: {e}", "WARN")
        if attempt < retries - 1:
            time.sleep(2 ** attempt)
    return None


def parse_api_matches(match_info_list: list) -> list[dict]:
    """解析 webapi.sporttery.cn REST API 返回的比赛数据
    
    API 返回结构:
    matchInfoList[].subMatchList[].had = {h:主胜赔率, d:平赔, a:客胜赔率}
    matchInfoList[].subMatchList[].hhad = {goalLine:让球数, h:让球主胜, d:让球平, a:让球客胜}
    """
    parsed = []
    for day_block in match_info_list:
        business_date = day_block.get("businessDate", "")
        for sub in day_block.get("subMatchList", []):
            match = {
                "matchId": str(sub.get("matchId", "")),
                "matchNum": sub.get("matchNumStr", ""),
                "homeTeam": sub.get("homeTeamAbbName", sub.get("homeTeamAllName", "")),
                "awayTeam": sub.get("awayTeamAbbName", sub.get("awayTeamAllName", "")),
                "league": sub.get("leagueAbbName", ""),
                "businessDate": business_date,
                "matchDate": sub.get("matchDate", ""),
                "matchTime": sub.get("matchTime", ""),
                "spf": None,
                "rqspf": None,
            }
            
            # SPF 赔率 (had 池): h=主胜, d=平局, a=客胜
            had = sub.get("had", {})
            if had:
                h, d, a = had.get("h"), had.get("d"), had.get("a")
                if h and d and a and h != "?" and d != "?" and a != "?":
                    match["spf"] = {
                        "home": float(h),
                        "draw": float(d),
                        "away": float(a),
                    }
            
            # 让球胜平负 (hhad 池)
            hhad = sub.get("hhad", {})
            if hhad:
                gl = hhad.get("goalLine")
                handicap = None
                try:
                    candidate_line = float(gl)
                    if candidate_line == int(candidate_line):
                        handicap = int(candidate_line)
                except (ValueError, TypeError, OverflowError):
                    pass
                if handicap is not None:
                    rqspf = {"handicap": handicap}
                    for key, value in (
                        ("home", hhad.get("h")),
                        ("draw", hhad.get("d")),
                        ("away", hhad.get("a")),
                    ):
                        if value not in (None, "", "?"):
                            try:
                                parsed_value = float(value)
                            except (ValueError, TypeError, OverflowError):
                                parsed_value = None
                            if parsed_value is not None:
                                rqspf[key] = parsed_value
                    match["rqspf"] = rqspf
            
            parsed.append(match)
    return parsed


# ── 主流程 ─────────────────────────────────────────
def fetch_jingcai_odds(date: str, no_cache: bool = False, cache_dir=None) -> dict:
    """抓取竞彩赔率，返回标准化 JSON"""

    cache_dir = Path(cache_dir) if cache_dir else DEFAULT_CACHE_DIR

    # 检查缓存
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file = cache_dir / f"{date}_jingcai.json"
    
    if not no_cache and cache_file.exists():
        mtime = datetime.fromtimestamp(cache_file.stat().st_mtime)
        if datetime.now() - mtime < timedelta(hours=CACHE_TTL_HOURS):
            log(f"Cache hit: {cache_file}", "INFO")
            with open(cache_file, "r", encoding="utf-8") as f:
                cached = json.load(f)
            if (
                isinstance(cached, dict)
                and cached.get("source") == "sporttery.cn"
                and cached.get("url") == SPORTTERY_API
                and isinstance(cached.get("request_contract"), dict)
                and cached["request_contract"].get("url") == SPORTTERY_API
                and cached.get("raw_response_sha256")
            ):
                return cached
            log("Ignoring cache without the current official request contract", "WARN")
    
    log(f"Fetching sporttery.cn API for {date}...", "INFO")
    
    result: dict = {
        "source": "sporttery.cn",
        "url": SPORTTERY_API,
        "business_date": date,
        "fetch_time": datetime.now().astimezone().isoformat(),
        "date": date,
        "success": False,
        "matches": [],
        "status": "UNKNOWN",
        "request_contract": {
            "method": "GET",
            "url": SPORTTERY_API,
            "params": {"channel": "c", "poolCode": SPORTTERY_POOL_CODE},
            "required_headers": sorted(SPORTTERY_REQUEST_HEADERS),
            "source_surface": "https://m.sporttery.cn/mjc/jsq/zqspf/",
        },
    }
    
    # 🥇 主源: 调用 webapi REST API (SPA 页面实际使用的数据接口)
    api_data = fetch_json(SPORTTERY_API)
    result.update(LAST_FETCH_METADATA)
    result["payload_success"] = bool(api_data and api_data.get("success") is True)
    
    if api_data and api_data.get("success") and api_data.get("value", {}).get("matchInfoList"):
        all_matches = parse_api_matches(api_data["value"]["matchInfoList"])
        available_dates = sorted({
            m.get("businessDate") or str(m.get("matchDate", ""))[:10]
            for m in all_matches
            if m.get("businessDate") or m.get("matchDate")
        })
        matches = [
            m for m in all_matches
            if m.get("businessDate") == date or str(m.get("matchDate", "")).startswith(date)
        ]
        result["available_dates"] = available_dates
        if matches and any(m.get("spf") or m.get("rqspf") for m in matches):
            result["success"] = True
            result["status"] = "OK_API"
            result["matches"] = matches
            result["url"] = SPORTTERY_API
            log(f"Extracted {len(matches)} matches from sporttery.cn API, {sum(1 for m in matches if m.get('spf'))} with SPF odds", "INFO")
            
            # 写入缓存并返回
            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
            return result
    
    # 🥈 API 未返回有效数据
    log("sporttery.cn API returned no valid data", "WARN")
    result["status"] = "API_FAILED"
    return result


# ── CLI ────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="竞彩官网赔率抓取器")
    parser.add_argument("--date", required=True, help="日期 YYYY-MM-DD")
    parser.add_argument("--no-cache", action="store_true", help="跳过缓存")
    parser.add_argument("--json", action="store_true", help="JSON 输出到 stdout")
    parser.add_argument("--cache-dir", default=str(DEFAULT_CACHE_DIR), help="项目内缓存目录")
    args = parser.parse_args()
    
    result = fetch_jingcai_odds(args.date, args.no_cache, args.cache_dir)
    
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        status = "✅" if result["success"] else "❌"
        print(f"{status} sporttery.cn: {result['status']} ({len(result['matches'])} matches)")
        if result["status"] in ("FETCH_FAILED", "API_FAILED"):
            print("Official source unavailable; formal JC handicap remains NOT_AVAILABLE")
    
    return 0 if result["success"] else 1


if __name__ == "__main__":
    sys.exit(main())
