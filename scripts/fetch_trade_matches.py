#!/usr/bin/env python3
"""Discover 500.com match IDs and visible official prices for one date."""

from __future__ import annotations

import argparse
import gzip
import html as html_lib
import json
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path


TRADE_URL = "https://trade.500.com/jczq/?playid=312&g=2"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CACHE_DIR = PROJECT_ROOT / "data" / "source_cache" / "trade"
CACHE_TTL_SECONDS = 3600


def _decode(raw: bytes, content_type: str = "") -> str:
    declared = None
    match = re.search(r"charset=([^;\s]+)", content_type, re.IGNORECASE)
    if match:
        declared = match.group(1).strip('"\'')
    for encoding in [declared, "gb18030", "gbk", "gb2312", "utf-8"]:
        if not encoding:
            continue
        try:
            return raw.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("gb18030", errors="replace")


def _fetch_trade_page() -> tuple[bytes, str]:
    request = urllib.request.Request(
        TRADE_URL,
        headers={
            "User-Agent": USER_AGENT,
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Accept-Encoding": "gzip",
            "Referer": "https://trade.500.com/",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        raw = response.read()
        if response.headers.get("Content-Encoding") == "gzip":
            raw = gzip.decompress(raw)
        return raw, response.headers.get("Content-Type", "")


def _extract_price_row(row: str, market_type: str) -> dict | None:
    values = re.findall(
        rf'data-type="{re.escape(market_type)}"[^>]*data-value="([310])"[^>]*data-sp="([\d.]+)"',
        row,
    )
    prices = {outcome: float(price) for outcome, price in values}
    if not all(key in prices for key in ("3", "1", "0")):
        return None
    return {"home": prices["3"], "draw": prices["1"], "away": prices["0"]}


def parse_trade_matches(page_text: str, target_date: str) -> list[dict]:
    rows = re.finditer(
        r'<tr\b[^>]*>.*?</tr>',
        page_text,
        re.DOTALL | re.IGNORECASE,
    )
    parsed = []
    current_business_date = None
    for row_match in rows:
        row = row_match.group(0)
        plain_row = html_lib.unescape(re.sub(r"<[^>]+>", " ", row))
        date_header = re.search(r"(\d{4}-\d{2}-\d{2})\s+星期", plain_row)
        if date_header:
            current_business_date = date_header.group(1)

        match_num_match = re.search(r'data-matchnum="([^"]+)"', row)
        if not match_num_match:
            continue
        match_num = match_num_match.group(1)
        shuju = re.search(r"shuju-(\d+)\.shtml", row)
        kickoff = re.search(r'class="td td-endtime"[^>]*title="([0-9]{2}-[0-9]{2}\s+[0-9]{2}:[0-9]{2})', row)
        business_date_match = re.search(r'data-processdate="(\d{4}-\d{2}-\d{2})"', row)
        match_date_match = re.search(r'data-matchdate="(\d{4}-\d{2}-\d{2})"', row)
        match_time_match = re.search(r'data-matchtime="(\d{2}:\d{2})"', row)
        league = re.search(r'class="td td-evt".*?<a[^>]*title="([^"]+)"', row, re.DOTALL)
        home = re.search(r'class="team-l"[^>]*title="([^"]+)"', row)
        away = re.search(r'class="team-r"[^>]*title="([^"]+)"', row)
        if not all((shuju, kickoff, league, home, away)):
            continue

        if match_date_match and match_time_match:
            kickoff_local = f"{match_date_match.group(1)} {match_time_match.group(1)}"
        else:
            kickoff_month = int(kickoff.group(1)[:2])
            target_month = int(target_date[5:7])
            kickoff_year = int(target_date[:4])
            if target_month == 12 and kickoff_month == 1:
                kickoff_year += 1
            elif target_month == 1 and kickoff_month == 12:
                kickoff_year -= 1
            kickoff_local = f"{kickoff_year}-{kickoff.group(1)}"

        business_date = (
            business_date_match.group(1)
            if business_date_match
            else current_business_date or kickoff_local[:10]
        )
        if business_date != target_date:
            continue

        handicap_match = re.search(r'class="green itm-rangA2"[^>]*>\s*([+-]?\d+)', row)
        handicap = int(handicap_match.group(1)) if handicap_match else None
        spf = _extract_price_row(row, "nspf")
        rqspf = _extract_price_row(row, "spf")

        parsed.append({
            "shuju_id": int(shuju.group(1)),
            "match_num": html_lib.unescape(match_num),
            "competition": html_lib.unescape(league.group(1)),
            "business_date": business_date,
            "kickoff_local": kickoff_local,
            "home_team": html_lib.unescape(home.group(1)),
            "away_team": html_lib.unescape(away.group(1)),
            "single_match_available": "ico-dg" in row,
            "official_spf_visible": spf,
            "official_rqspf_visible": ({"handicap": handicap, **rqspf} if rqspf else None),
        })
    return parsed


def fetch_trade_matches(date: str, no_cache: bool = False, cache_dir=None) -> dict:
    cache_dir = Path(cache_dir) if cache_dir else DEFAULT_CACHE_DIR
    cache_dir.mkdir(parents=True, exist_ok=True)
    json_cache = cache_dir / f"{date}_match_list.json"
    raw_cache = cache_dir / f"{date}_trade.html"

    if not no_cache and json_cache.exists() and time.time() - json_cache.stat().st_mtime < CACHE_TTL_SECONDS:
        return json.loads(json_cache.read_text(encoding="utf-8"))

    result = {
        "source": "trade.500.com",
        "url": TRADE_URL,
        "fetch_time": datetime.now().astimezone().isoformat(),
        "date": date,
        "success": False,
        "matches": [],
        "status": "UNKNOWN",
    }
    try:
        raw, content_type = _fetch_trade_page()
        page_text = _decode(raw, content_type)
        matches = parse_trade_matches(page_text, date)
        raw_cache.write_bytes(raw)
        result["matches"] = matches
        result["success"] = bool(matches)
        result["status"] = "OK" if matches else "NO_MATCHES_FOR_DATE"
        json_cache.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        result["status"] = "FETCH_FAILED"
        result["error"] = str(error)
    return result


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="500.com 比赛列表和 shuju_id 抓取器")
    parser.add_argument("--date", required=True, help="日期 YYYY-MM-DD")
    parser.add_argument("--no-cache", action="store_true", help="强制刷新")
    parser.add_argument("--cache-dir", default=str(DEFAULT_CACHE_DIR), help="项目内缓存目录")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    args = parser.parse_args()

    result = fetch_trade_matches(args.date, args.no_cache, args.cache_dir)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"trade.500.com: {result['status']} ({len(result['matches'])} matches)")
        for match in result["matches"]:
            print(
                f"  {match['match_num']} {match['home_team']} vs {match['away_team']} "
                f"shuju_id={match['shuju_id']}"
            )
    return 0 if result["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
