#!/usr/bin/env python3
"""Persist one exact Polymarket football event as read-only analysis evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from polymarket_public import fetch_snapshot


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--home", required=True)
    parser.add_argument("--away", required=True)
    parser.add_argument("--kickoff")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    snapshot = fetch_snapshot(args.home, args.away, args.kickoff)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "output": str(output),
        "status": snapshot.get("match", {}).get("status"),
        "market_count": len(snapshot.get("markets", [])),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
