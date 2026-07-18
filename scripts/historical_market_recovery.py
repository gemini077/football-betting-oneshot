#!/usr/bin/env python3
"""Recover a checkpoint from timestamped Nowscore company histories."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
SHANGHAI = ZoneInfo("Asia/Shanghai")


def _time(value) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=SHANGHAI) if parsed.tzinfo is None else parsed.astimezone(SHANGHAI)


def _latest_before(rows: list[dict], cutoff: datetime) -> dict | None:
    eligible = [(parsed, row) for row in rows if (parsed := _time(row.get("captured_at"))) and parsed <= cutoff]
    return max(eligible, key=lambda item: item[0])[1] if eligible else None


def recover_payload(payload: dict, cutoff_value) -> dict:
    cutoff = _time(cutoff_value)
    if cutoff is None:
        return {"status": "invalid_cutoff", "recovered_companies": 0}
    context = (
        payload.get("nowscore_context")
        or payload.get("context")
        or ((payload.get("nowscore") or {}).get("context") or {})
    )
    trends = context.get("company_trends") or []
    market_rows = {
        "one_x_two": ((payload.get("ouzhi") or {}).get("bookmakers") or []),
        "asian": ((payload.get("yazhi") or {}).get("companies") or []),
        "total": ((payload.get("daxiao") or {}).get("companies") or []),
    }
    recovered = {"one_x_two": 0, "asian": 0, "total": 0}
    recovered_ids = {"one_x_two": set(), "asian": set(), "total": set()}
    used_times = []
    trimmed_trends = []
    for company in trends:
        provider_id = company.get("source_company_id")
        company_markets = company.get("markets") or {}
        for market, target_rows in market_rows.items():
            eligible = [
                row for row in (company_markets.get(market) or [])
                if (parsed := _time(row.get("captured_at"))) and parsed <= cutoff
            ]
            company_markets[market] = eligible
            quote = _latest_before(eligible, cutoff)
            target = next((row for row in target_rows if row.get("source_company_id") == provider_id), None)
            if not quote or target is None:
                continue
            if market == "one_x_two":
                target["spf_current"] = {key: quote.get(key) for key in ("home", "draw", "away")}
            elif market == "asian":
                target.update({
                    "current_handicap": quote.get("line_number"),
                    "current_water_home": quote.get("home_water"),
                    "current_water_away": quote.get("away_water"),
                })
            else:
                target.update({
                    "current_line": quote.get("line_number"),
                    "current_over_water": quote.get("over"),
                    "current_under_water": quote.get("under"),
                })
            recovered[market] += 1
            recovered_ids[market].add(provider_id)
            used_times.append(quote.get("captured_at"))
        company["markets"] = company_markets
        company["snapshot_count"] = sum(len(rows) for rows in company_markets.values())
        if company["snapshot_count"]:
            trimmed_trends.append(company)
    context["company_trends"] = trimmed_trends
    for market, target_rows in market_rows.items():
        target_rows[:] = [row for row in target_rows if row.get("source_company_id") in recovered_ids[market]]
    company_count = len(set().union(*recovered_ids.values()))
    total_quotes = sum(recovered.values())
    recovery_complete = all(recovered[market] > 0 for market in recovered)
    payload["historical_checkpoint_recovery"] = {
        "status": "recovered" if recovery_complete else "insufficient_history",
        "cutoff": cutoff.isoformat(), "source": "nowscore_timestamped_company_history",
        "trend_company_count": company_count, "recovered_quotes": recovered,
        "latest_quote_used": max((value for value in used_times if value), default=None),
        "current_price_used_as_history": False,
    }
    # Public exchange snapshots are point-in-time only.  A later snapshot must
    # never be presented as historical transaction flow.
    if payload.get("touzhu"):
        payload["touzhu"]["betfair"] = {}
        payload["touzhu"]["pl_flow"] = {"transactions": []}
        payload["touzhu"]["betfair_metadata"] = {
            "completeness": "historical_unavailable",
            "reason": "public_exchange_snapshot_has_no_verified_historical_cutoff",
        }
    return {"status": payload["historical_checkpoint_recovery"]["status"], "recovered_companies": company_count, "recovered_quotes": total_quotes}


def recover_manifest(manifest_path: Path, cutoff_value) -> dict:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    candidates = []
    for item in (((manifest.get("sources") or {}).get("500_deep") or {}).get("matches") or []):
        if item.get("file"):
            candidates.append(ROOT / item["file"])
    for item in (((manifest.get("sources") or {}).get("nowscore") or {}).get("matches") or []):
        if item.get("file"):
            candidates.append(ROOT / item["file"])
    summaries = []
    for path in candidates:
        if not path.exists():
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        summary = recover_payload(payload, cutoff_value)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        summaries.append({"file": str(path.relative_to(ROOT)).replace("\\", "/"), **summary})
    recovered = sum(item.get("recovered_quotes", 0) for item in summaries)
    return {"status": "recovered" if recovered >= 3 else "insufficient_history", "files": summaries, "recovered_quotes": recovered}
