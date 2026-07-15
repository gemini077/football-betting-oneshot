#!/usr/bin/env python3
"""Build deduplicated per-match market history from immutable fetch runs."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
FETCH_ROOT = PROJECT_ROOT / "data" / "fetch_runs"
HISTORY_ROOT = PROJECT_ROOT / "data" / "market_history"


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _market_time(deep: dict) -> str | None:
    candidates = []
    pin = deep.get("yazhi", {}).get("pinnacle") or {}
    if pin.get("snapshot_time"):
        candidates.append(pin["snapshot_time"])
    for item in deep.get("touzhu", {}).get("pl_flow", {}).get("transactions", []):
        if item.get("time"):
            candidates.append(item["time"])
    if candidates:
        parsed = []
        for value in candidates:
            try:
                parsed.append(datetime.fromisoformat(value))
            except ValueError:
                continue
        if parsed:
            return max(parsed).isoformat(sep=" ")
    return deep.get("fetched_at")


def normalize_snapshot(deep: dict, source_file: Path) -> dict:
    try:
        source_label = str(source_file.relative_to(PROJECT_ROOT)).replace("\\", "/")
    except ValueError:
        source_label = str(source_file)
    snapshot = {
        "shuju_id": deep.get("shuju_id"),
        "market_time": _market_time(deep),
        "recorded_at": deep.get("fetched_at"),
        "source_file": source_label,
        "euro": [
            {
                "cid": item.get("cid"),
                "open": item.get("spf_open"),
                "current": item.get("spf_current"),
                "kelly": item.get("kelly_current"),
            }
            for item in deep.get("ouzhi", {}).get("bookmakers", [])
        ],
        "asian": [
            {
                "cid": item.get("cid"),
                "open_line": item.get("open_handicap"),
                "current_line": item.get("current_handicap"),
                "open_home": item.get("open_water_home"),
                "open_away": item.get("open_water_away"),
                "current_home": item.get("current_water_home"),
                "current_away": item.get("current_water_away"),
                "change_time": item.get("change_time"),
            }
            for item in deep.get("yazhi", {}).get("companies", [])
        ],
        "totals": [
            {
                "cid": item.get("cid"),
                "open_line": item.get("open_line"),
                "current_line": item.get("current_line"),
                "open_over": item.get("open_over_water"),
                "open_under": item.get("open_under_water"),
                "current_over": item.get("current_over_water"),
                "current_under": item.get("current_under_water"),
                "change_time": item.get("change_time"),
            }
            for item in deep.get("daxiao", {}).get("companies", [])
        ],
        "exchange": {
            "betfair": deep.get("touzhu", {}).get("betfair"),
            "transactions": deep.get("touzhu", {}).get("pl_flow", {}).get("transactions", []),
        },
    }
    fingerprint_payload = {
        "euro": snapshot["euro"],
        "asian": snapshot["asian"],
        "totals": snapshot["totals"],
        "betfair": snapshot["exchange"]["betfair"],
        "transactions": snapshot["exchange"]["transactions"],
    }
    snapshot["fingerprint"] = hashlib.sha256(
        json.dumps(fingerprint_payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return snapshot


def rebuild_history(shuju_id: int, fetch_root: Path = FETCH_ROOT, history_root: Path = HISTORY_ROOT) -> Path:
    candidates = sorted(fetch_root.glob(f"*/*_500_deep_*_{shuju_id}.json"))
    snapshots = []
    seen = set()
    for path in candidates:
        try:
            deep = load_json(path)
        except (OSError, json.JSONDecodeError):
            continue
        if int(deep.get("shuju_id") or 0) != int(shuju_id):
            continue
        snapshot = normalize_snapshot(deep, path)
        if snapshot["fingerprint"] in seen:
            continue
        seen.add(snapshot["fingerprint"])
        snapshots.append(snapshot)
    snapshots.sort(key=lambda item: item.get("market_time") or item.get("recorded_at") or "")

    output = history_root / str(shuju_id) / "market_history.jsonl"
    output.parent.mkdir(parents=True, exist_ok=True)
    text = "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in snapshots)
    output.write_text(text, encoding="utf-8")
    return output


def load_history(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def main() -> int:
    parser = argparse.ArgumentParser(description="从不可变抓取批次重建单场市场时间序列")
    parser.add_argument("--shuju-id", type=int, required=True)
    parser.add_argument("--fetch-root", default=str(FETCH_ROOT))
    parser.add_argument("--history-root", default=str(HISTORY_ROOT))
    args = parser.parse_args()
    output = rebuild_history(args.shuju_id, Path(args.fetch_root), Path(args.history_root))
    history = load_history(output)
    print(json.dumps({"history_file": str(output), "snapshot_count": len(history)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
