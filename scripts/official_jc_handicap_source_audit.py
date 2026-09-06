#!/usr/bin/env python3
"""Bounded current Sporttery-only source audit for the official JC handicap lane."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import platform
import sys
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from fetch_sporttery import (
    SPORTTERY_API,
    SPORTTERY_POOL_CODE,
    SPORTTERY_REQUEST_HEADERS,
    parse_api_matches,
)
from official_jc_handicap import (
    official_match_binding_candidates,
    official_rqspf_line,
    official_rqspf_odds,
)


ROOT = Path(__file__).resolve().parents[1]
OFFICIAL_PAGE_URL = "https://m.sporttery.cn/mjc/jsq/zqspf/"
TIMEOUT_SECONDS = 30
MAX_RESPONSE_BYTES = 10 * 1024 * 1024
AUDIT_CONTRACT_VERSION = "jc_handicap_source_audit.v1"
UNIVERSE_ROOT = ROOT / "data" / "prediction_universe"
DELIVERY_FORMAL_READY = "JC_HANDICAP_FORMAL_TRUTH_READY"
DELIVERY_SOURCE_PARTIAL = "JC_HANDICAP_SOURCE_AUTHORITY_PARTIAL"
DELIVERY_SOURCE_NOT_EXECUTABLE = "OFFICIAL_SOURCE_NOT_EXECUTABLE"
DELIVERY_FAIL_CLOSED = "FAIL_CLOSED"


def _read_response(response: Any) -> tuple[bytes, bytes, str]:
    wire = response.read(MAX_RESPONSE_BYTES + 1)
    content_encoding = str(response.headers.get("Content-Encoding") or "").casefold()
    body = gzip.decompress(wire) if "gzip" in content_encoding else wire
    return wire, body, str(response.headers.get("Content-Type") or "")


def _probe(url: str, *, headers: dict[str, str], parse_json: bool = False) -> dict[str, Any]:
    started = time.monotonic()
    result: dict[str, Any] = {
        "url": url,
        "request_headers": sorted(headers),
        "http_status": None,
        "response_bytes": 0,
        "response_sha256": None,
        "content_type": None,
        "response_type": "UNKNOWN",
        "success": False,
        "payload_success": None,
        "error": None,
    }
    wire = b""
    body = b""
    try:
        request = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            result["http_status"] = int(response.getcode())
            wire, body, result["content_type"] = _read_response(response)
    except urllib.error.HTTPError as error:
        result["http_status"] = int(error.code)
        result["error"] = f"HTTPError: {error}"
        try:
            wire, body, result["content_type"] = _read_response(error)
        except Exception:
            wire = b""
            body = b""
    except (OSError, TimeoutError, urllib.error.URLError) as error:
        result["error"] = f"{type(error).__name__}: {error}"
    result["response_bytes"] = len(body)
    result["wire_response_bytes"] = len(wire)
    result["response_sha256"] = hashlib.sha256(body).hexdigest() if body else None
    result["wire_response_sha256"] = hashlib.sha256(wire).hexdigest() if wire else None
    result["duration_ms"] = round((time.monotonic() - started) * 1000, 1)
    if body.lstrip().startswith((b"{", b"[")):
        result["response_type"] = "JSON"
    elif body.lstrip().startswith(b"<"):
        result["response_type"] = "HTML"
    elif body:
        result["response_type"] = "TEXT"
    if parse_json and body:
        try:
            payload = json.loads(body.decode("utf-8"))
            result["payload_success"] = payload.get("success") is True if isinstance(payload, dict) else False
            result["payload"] = payload
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            result["error"] = f"{type(error).__name__}: {error}"
    result["success"] = result["http_status"] == 200 and (
        not parse_json or result["payload_success"] is True
    )
    return result


def _raw_hhad_rows(payload: Any, target_date: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    groups = (payload.get("value") or {}).get("matchInfoList") if isinstance(payload, dict) else None
    for group in groups if isinstance(groups, list) else []:
        if not isinstance(group, dict):
            continue
        for row in group.get("subMatchList") or []:
            if not isinstance(row, dict) or str(row.get("businessDate") or "") != target_date:
                continue
            hhad = row.get("hhad")
            if not isinstance(hhad, dict) or not str(hhad.get("goalLine") or "").strip():
                continue
            raw_projection = {
                "businessDate": row.get("businessDate"),
                "matchId": row.get("matchId"),
                "matchNumStr": row.get("matchNumStr"),
                "matchDate": row.get("matchDate"),
                "matchTime": row.get("matchTime"),
                "homeTeamAbbName": row.get("homeTeamAbbName"),
                "awayTeamAbbName": row.get("awayTeamAbbName"),
                "hhad": hhad,
            }
            raw_bytes = json.dumps(
                raw_projection,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            parsed_row = parse_api_matches([{
                "businessDate": target_date,
                "subMatchList": [row],
            }])
            rows.append({
                "raw_row_sha256": hashlib.sha256(raw_bytes).hexdigest(),
                "raw_row": raw_projection,
                "parsed": parsed_row[0] if parsed_row else None,
            })
    return rows


def _row_identity_key(row: dict[str, Any]) -> tuple[str, ...]:
    return tuple(
        str(row.get(key) or "").strip().casefold()
        for key in ("businessDate", "matchNum", "homeTeam", "awayTeam", "matchDate", "matchTime")
    )


def _duplicate_diagnostics(rows: list[dict[str, Any]]) -> dict[str, int]:
    duplicate_counts: dict[str, int] = {}
    for label, field in (
        ("provider_match_id", "matchId"),
        ("provider_match_num", "matchNum"),
        ("identity", None),
    ):
        groups: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            value = _row_identity_key(row) if field is None else str(row.get(field) or "").strip()
            if value:
                groups.setdefault(str(value), []).append(row)
        duplicate_counts[f"duplicate_{label}_count"] = sum(
            max(0, len(group) - 1) for group in groups.values() if len(group) > 1
        )
        if label == "identity":
            duplicate_counts["conflict_identity_group_count"] = sum(
                1
                for group in groups.values()
                if len(group) > 1
                and len({
                    json.dumps(
                        {
                            "line": official_rqspf_line(row),
                            "odds": official_rqspf_odds(row),
                        },
                        sort_keys=True,
                    )
                    for row in group
                }) > 1
            )
    return duplicate_counts


def _binding_funnel(
    official_rows: list[dict[str, Any]],
    universe: dict[str, Any] | None,
    *,
    universe_path: str,
) -> dict[str, Any]:
    fixtures = universe.get("fixtures") if isinstance(universe, dict) else None
    if not isinstance(fixtures, list):
        duplicate_diagnostics = _duplicate_diagnostics(official_rows)
        return {
            "status": "JC_UNIVERSE_NOT_AVAILABLE",
            "universe_path": universe_path,
            "jc_fixtures": 0,
            "official_rows": len(official_rows),
            "exact_bound": 0,
            "ambiguous": 0,
            "unmatched": 0,
            "duplicates": duplicate_diagnostics["duplicate_identity_count"],
            "conflicts": duplicate_diagnostics["conflict_identity_group_count"],
            "duplicate_diagnostics": duplicate_diagnostics,
            "line_available": 0,
            "odds_available": 0,
        }
    exact_bound = 0
    ambiguous = 0
    unmatched = 0
    line_available = 0
    odds_available = 0
    for fixture in fixtures:
        if not isinstance(fixture, dict):
            unmatched += 1
            continue
        candidates = official_match_binding_candidates(
            {"matches": official_rows},
            fixture,
        )
        if len(candidates) == 1:
            exact_bound += 1
            line_available += int(official_rqspf_line(candidates[0]) is not None)
            odds_available += int(official_rqspf_odds(candidates[0]) is not None)
        elif len(candidates) > 1:
            ambiguous += 1
        else:
            unmatched += 1
    duplicate_diagnostics = _duplicate_diagnostics(official_rows)
    return {
        "status": "AVAILABLE",
        "universe_path": universe_path,
        "jc_fixtures": len(fixtures),
        "official_rows": len(official_rows),
        "exact_bound": exact_bound,
        "ambiguous": ambiguous,
        "unmatched": unmatched,
        "duplicates": duplicate_diagnostics["duplicate_identity_count"],
        "conflicts": duplicate_diagnostics["conflict_identity_group_count"],
        "duplicate_diagnostics": duplicate_diagnostics,
        "line_available": line_available,
        "odds_available": odds_available,
    }


def _load_identity_universe(target_date: str) -> tuple[dict[str, Any] | None, str]:
    path = UNIVERSE_ROOT / f"{target_date}.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None, path.as_posix()
    return value if isinstance(value, dict) else None, path.as_posix()


def _delivery_decision(
    *,
    source_available: bool,
    page_probe: dict[str, Any],
    calculator_probe: dict[str, Any],
    binding_funnel: dict[str, Any],
) -> str:
    if (
        page_probe.get("http_status") != 200
        or calculator_probe.get("http_status") != 200
        or calculator_probe.get("payload_success") is not True
    ):
        return DELIVERY_SOURCE_NOT_EXECUTABLE
    if not source_available:
        return DELIVERY_FAIL_CLOSED
    if (
        binding_funnel.get("status") != "AVAILABLE"
        or not binding_funnel.get("jc_fixtures")
        or binding_funnel.get("exact_bound") != binding_funnel.get("jc_fixtures")
        or binding_funnel.get("ambiguous")
        or binding_funnel.get("unmatched")
        or binding_funnel.get("duplicates")
        or binding_funnel.get("conflicts")
        or binding_funnel.get("line_available") != binding_funnel.get("exact_bound")
    ):
        return DELIVERY_SOURCE_PARTIAL
    return DELIVERY_FORMAL_READY


def build_audit(
    target_date: str,
    *,
    page_probe: dict[str, Any],
    calculator_probe: dict[str, Any],
    universe: dict[str, Any] | None = None,
    universe_path: str | None = None,
) -> dict[str, Any]:
    payload = calculator_probe.get("payload")
    raw_rows = _raw_hhad_rows(payload, target_date)
    parsed_rows = parse_api_matches(
        ((payload or {}).get("value") or {}).get("matchInfoList") or []
    ) if isinstance(payload, dict) else []
    target_rows = [row for row in parsed_rows if row.get("businessDate") == target_date]
    line_rows = [row for row in raw_rows if isinstance((row.get("parsed") or {}).get("rqspf"), dict)]
    price_rows = [
        row for row in line_rows
        if all((row.get("parsed") or {}).get("rqspf", {}).get(key) not in (None, "") for key in ("home", "draw", "away"))
    ]
    request_contract = {
        "method": "GET",
        "url": SPORTTERY_API,
        "params": {"channel": "c", "poolCode": SPORTTERY_POOL_CODE},
        "required_headers": sorted(SPORTTERY_REQUEST_HEADERS),
        "source_surface": OFFICIAL_PAGE_URL,
    }
    source_available = bool(
        page_probe.get("success")
        and page_probe.get("http_status") == 200
        and calculator_probe.get("success")
        and target_rows
        and line_rows
        and calculator_probe.get("response_sha256")
    )
    binding_funnel = _binding_funnel(
        target_rows,
        universe,
        universe_path=universe_path or str((UNIVERSE_ROOT / f"{target_date}.json").as_posix()),
    )
    delivery_decision = _delivery_decision(
        source_available=source_available,
        page_probe=page_probe,
        calculator_probe=calculator_probe,
        binding_funnel=binding_funnel,
    )
    calculator_probe = {key: value for key, value in calculator_probe.items() if key != "payload"}
    return {
        "schema_version": AUDIT_CONTRACT_VERSION,
        "target_business_date": target_date,
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "source": "sporttery.cn",
        "market": "rqspf",
        "market_identity": "JC_HANDICAP_1X2",
        "request_contract": request_contract,
        "official_page_probe": page_probe,
        "official_calculator_probe": calculator_probe,
        "current_source_status": "AVAILABLE" if source_available else "NOT_AVAILABLE",
        "official_rows_returned": len(target_rows),
        "hhad_line_available": len(line_rows),
        "hhad_three_prices_available": len(price_rows),
        "binding_funnel": binding_funnel,
        "delivery_decision": delivery_decision,
        "evidence_rows": raw_rows[:5],
        "parser_contract": {
            "source_field": "hhad.goalLine",
            "prices": {"home": "hhad.h", "draw": "hhad.d", "away": "hhad.a"},
            "line_type": "integer",
            "home_perspective_formula": "home_goals + handicap_line compared to away_goals",
        },
        "source_authority_decision": (
            "JC_HANDICAP_SOURCE_AUTHORITY_PROVEN"
            if source_available
            else "JC_HANDICAP_SOURCE_AUTHORITY_NOT_PROVEN"
        ),
        "decision": (
            "JC_HANDICAP_SOURCE_AUTHORITY_PROVEN"
            if source_available
            else "JC_HANDICAP_SOURCE_AUTHORITY_NOT_PROVEN"
        ),
    }


def run_audit(target_date: str) -> dict[str, Any]:
    page_probe = _probe(OFFICIAL_PAGE_URL, headers=SPORTTERY_REQUEST_HEADERS)
    calculator_probe = _probe(SPORTTERY_API, headers=SPORTTERY_REQUEST_HEADERS, parse_json=True)
    universe, universe_path = _load_identity_universe(target_date)
    return {
        "audit_contract_version": AUDIT_CONTRACT_VERSION,
        "probe_policy": "Sporttery-owned page/calculator only; one request per surface; no retry; no production writes",
        "runner": {"platform": platform.platform(), "python": sys.version.split()[0]},
        "audit": build_audit(
            target_date,
            page_probe=page_probe,
            calculator_probe=calculator_probe,
            universe=universe,
            universe_path=universe_path,
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", default=date.today().isoformat())
    parser.add_argument("--output", type=Path, default=ROOT / "official-jc-handicap-source-audit.json")
    args = parser.parse_args()
    result = run_audit(args.date)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["audit"]["current_source_status"] == "AVAILABLE" else 1


if __name__ == "__main__":
    raise SystemExit(main())
