#!/usr/bin/env python3
"""Validate and persist a user-confirmed real bet submitted through GitHub Issues."""
from __future__ import annotations

import argparse
import json
import os
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "real_bets"
SHANGHAI = ZoneInfo("Asia/Shanghai")


def parse_body(body: str) -> dict:
    values = {}
    for line in body.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        values[key.strip().casefold()] = value.strip()
    required = ("match_id", "match", "market", "selection", "odds", "stake", "confirmed_at")
    missing = [key for key in required if not values.get(key)]
    if missing:
        raise ValueError("缺少字段：" + "、".join(missing))
    odds, stake = float(values["odds"]), float(values["stake"])
    if odds <= 1:
        raise ValueError("实际赔率必须大于1.00")
    if stake < 2:
        raise ValueError("实际投注额不得低于2.00元")
    if abs(stake * 100 - round(stake * 100)) > 1e-7:
        raise ValueError("投注额最小增减单位为0.01元")
    values.update({"odds": round(odds, 4), "stake": round(stake, 2)})
    return values


def persist(values: dict, issue_number: str = "local", out_dir: Path = OUT) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now(SHANGHAI)
    safe_issue = re.sub(r"[^0-9A-Za-z_-]+", "", issue_number) or "local"
    bet_id = f"REAL-{now:%Y%m%d}-{safe_issue}"
    payload = {
        "schema_version": "1.0", "bet_id": bet_id, "ledger": "真实账户",
        "real_execution": True, "status": "locked", "immutable_after_kickoff": True,
        "match_id": values["match_id"], "match": values["match"],
        "market": values["market"], "selection": values["selection"],
        "odds": values["odds"], "stake": values["stake"],
        "channel": values.get("channel") or None, "form": values.get("form") or "单关",
        "confirmed_at": values["confirmed_at"], "recorded_at": now.isoformat(),
    }
    target = out_dir / f"{bet_id}.json"
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    rows = []
    for path in sorted(out_dir.glob("REAL-*.json")):
        try: rows.append(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError): pass
    (out_dir / "latest.json").write_text(json.dumps({"bets": rows}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--body", default=os.environ.get("ISSUE_BODY", ""))
    parser.add_argument("--issue-number", default=os.environ.get("ISSUE_NUMBER", "local"))
    args = parser.parse_args()
    target = persist(parse_body(args.body), args.issue_number)
    print(json.dumps({"status": "recorded", "path": target.relative_to(ROOT).as_posix()}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
