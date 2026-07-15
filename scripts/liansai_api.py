#!/usr/bin/env python3
"""
500.com Liansai API client — v2.1
Fetch complete tournament match data via liansai internal API.
Usage: python scripts/liansai_api.py --sid 19476 [--round A] [--json]
"""
import json, sys, urllib.request
from pathlib import Path

API_BASE = "https://liansai.500.com/index.php?c=match&a=getmatch&sid={}&round={}"
HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "source_cache" / "liansai"


def _decode_response(raw, content_type=""):
    match = None
    if "charset=" in content_type.lower():
        match = content_type.lower().split("charset=", 1)[1].split(";", 1)[0].strip()
    for encoding in [match, "utf-8", "gbk", "gb18030"]:
        if not encoding:
            continue
        try:
            return raw.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", errors="replace")


def fetch(sid, round_name):
    url = API_BASE.format(sid, round_name)
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(_decode_response(resp.read(), resp.headers.get("Content-Type", "")))

def fetch_all(sid, rounds="ABCDEFGHIJKL"):
    """Fetch all rounds/groups for a tournament"""
    all_matches = []
    for r in rounds:
        matches = fetch(sid, r)
        for m in matches:
            m["_round"] = r
        all_matches.extend(matches)
    return all_matches

def main():
    import argparse
    parser = argparse.ArgumentParser(description="500.com Liansai API client")
    parser.add_argument("--sid", type=int, required=True, help="Season ID (e.g. 19476 for 2026 WC)")
    parser.add_argument("--round", default=None, help="Single round/group (e.g. A). If omitted, fetch all A-Z")
    parser.add_argument("--json", action="store_true", help="JSON output")
    parser.add_argument("--output", help="Optional JSON output path")
    args = parser.parse_args()

    if args.round:
        matches = fetch(args.sid, args.round)
    else:
        matches = fetch_all(args.sid)

    completed = [m for m in matches if m.get("status") == 5]
    upcoming = [m for m in matches if m.get("status") != 5]

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(matches, ensure_ascii=False, indent=2), encoding="utf-8")

    if args.json:
        print(json.dumps(matches, ensure_ascii=False, indent=2))
    else:
        print(f"赛事ID: {args.sid}")
        print(f"总场次: {len(matches)}")
        print(f"已完赛: {len(completed)} | 未赛: {len(upcoming)}")
        for m in completed:
            print(f"  🏁 {m.get('stime','?')[:10]} {m['hname']} {m['hscore']}:{m['gscore']} {m['gname']}  fid={m['fid']}")

if __name__ == "__main__":
    main()
