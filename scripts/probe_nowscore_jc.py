#!/usr/bin/env python3
"""Probe the public Nowscore schedule page's explicit JC membership contract.

This probe is deliberately separate from the production refresh path.  It
records the page filter contract, its backing JavaScript rows, exact date
provenance, and a comparison with the existing bf1/scN schedule surfaces.
No production or frozen data is written.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

try:
    import nowscore_markets as nowscore
except ImportError:  # package imports used by tests
    from scripts import nowscore_markets as nowscore


REPO_ROOT = Path(__file__).resolve().parents[1]
SHANGHAI = ZoneInfo("Asia/Shanghai")
Nowscore_URL = "https://live.nowscore.com"
SCHEDULE_PAGE_URL = f"{Nowscore_URL}/schedule.aspx?f={{surface}}"
SCHEDULE_DATA_URL = f"{Nowscore_URL}/data/{{filename}}"
TARGET_DATE = "2026-09-01"
MAX_FUTURE_SCHEDULE_OFFSET = 7
ROW_PATTERN = re.compile(r"(?m)^A\[(?P<index>\d+)\]=\[(?P<body>.*?)\];\s*$")


def _now() -> str:
    return datetime.now(SHANGHAI).isoformat(timespec="seconds")


def _target_date(value: object) -> date:
    parsed = date.fromisoformat(str(value)[:10])
    return parsed


def _surface_for_date(target: date, today: date) -> tuple[str | None, str | None]:
    offset = (target - today).days
    if offset == 0:
        return "ft1", "current"
    if 1 <= offset <= MAX_FUTURE_SCHEDULE_OFFSET:
        return f"sc{offset}", "future"
    return None, None


def _strip_tags(value: str) -> str:
    return re.sub(r"<[^>]+>", "", value).strip()


def _page_contract(page_text: str, surface: str) -> dict[str, Any]:
    filename_match = re.search(
        r"\bfilename2\s*=\s*[\"'](?P<filename>[^\"']+)[\"']",
        page_text,
        re.IGNORECASE,
    )
    filename = filename_match.group("filename") if filename_match else ""
    expected_filename = f"{surface}.js"
    function_match = re.search(
        r"function\s+SetLevel\s*\(\s*l\s*\)\s*\{(?P<body>.*?)(?:\n\s*Config\.getCookie|\Z)",
        page_text,
        re.IGNORECASE | re.DOTALL,
    )
    function_body = function_match.group("body") if function_match else ""
    link_match = re.search(
        r"<a\b[^>]*href\s*=\s*[\"']javascript:SetLevel\(\s*3\s*\)[\"'][^>]*>(?P<label>.*?)</a>",
        page_text,
        re.IGNORECASE | re.DOTALL,
    )
    has_index = bool(
        re.search(
            r"if\s*\(\s*l\s*==\s*3\s*\).*?index\s*=\s*32\s*;",
            function_body,
            re.IGNORECASE | re.DOTALL,
        )
    )
    has_predicate = bool(
        re.search(
            r"A\s*\[\s*j\s*\]\s*\[\s*index\s*\]\s*==\s*1",
            function_body,
            re.IGNORECASE,
        )
    )
    valid_filename = filename == expected_filename
    return {
        "surface": surface,
        "expected_filename": expected_filename,
        "filename2": filename or None,
        "jc_filter_link_present": link_match is not None,
        "jc_filter_label": _strip_tags(link_match.group("label")) if link_match else None,
        "function_present": function_match is not None,
        "row_index": 32,
        "filter_function": "SetLevel(3)",
        "predicate": "A[j][32] == 1",
        "row_index_contract_present": has_index,
        "predicate_contract_present": has_predicate,
        "valid": bool(
            valid_filename
            and link_match
            and function_match
            and has_index
            and has_predicate
        ),
    }


def _raw_rows(js_text: str) -> list[dict[str, Any]]:
    rows = []
    for found in ROW_PATTERN.finditer(js_text.lstrip("\ufeff")):
        rows.append({
            "array_index": int(found.group("index")),
            "values": nowscore._split_js_values(found.group("body")),
        })
    return rows


def _signature(row: dict[str, Any]) -> tuple[Any, ...]:
    return (
        row.get("home_team"),
        row.get("home_team_en"),
        row.get("away_team"),
        row.get("away_team_en"),
        row.get("kickoff_local"),
    )


def _empty_result(
    *,
    contract: dict[str, Any],
    expected_date: date,
    source_url: str,
    backing_data_url: str,
    fetched_at: str,
    diagnostics: dict[str, int] | None = None,
) -> dict[str, Any]:
    return {
        "status": "FAIL" if not contract.get("valid") else "PASS",
        "contract": contract,
        "expected_business_date": expected_date.isoformat(),
        "source_url": source_url,
        "backing_data_url": backing_data_url,
        "fetched_at": fetched_at,
        "raw_match_count": 0,
        "target_row_count": 0,
        "jc_flagged_row_count": 0,
        "accepted_fixture_count": 0,
        "duplicate_nowscore_id_count": 0,
        "ambiguous_nowscore_id_count": 0,
        "diagnostics": diagnostics or {},
        "fixtures": [],
    }


def inspect_jc_surface(
    page_text: str,
    js_text: str,
    *,
    expected_date: object,
    source_url: str,
    backing_data_url: str,
    fetched_at: str | None = None,
    surface: str | None = None,
) -> dict[str, Any]:
    """Validate and normalize one Nowscore public schedule surface.

    A row is accepted only when the page's explicit ``SetLevel(3)`` contract
    maps to a numeric ``A[j][32] == 1`` value on that same row.
    """
    target = _target_date(expected_date)
    surface_name = surface or (
        re.search(r"[?&]f=([^&]+)", source_url, re.IGNORECASE).group(1)
        if re.search(r"[?&]f=([^&]+)", source_url, re.IGNORECASE)
        else "unknown"
    )
    contract = _page_contract(page_text, surface_name)
    rows = _raw_rows(js_text)
    normalized, parse_diagnostics = nowscore._parse_schedule_js(
        js_text.lstrip("\ufeff"), expected_date=target
    )
    normalized_by_id: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in normalized:
        normalized_by_id[int(row["nowscore_id"])].append(row)

    target_rows: list[tuple[dict[str, Any], list[Any]]] = []
    for raw in rows:
        values = raw["values"]
        if len(values) < 12:
            continue
        match_id = nowscore._integer(values[0])
        if match_id is None:
            continue
        parsed_rows = normalized_by_id.get(match_id, [])
        if parsed_rows:
            target_rows.append((raw, parsed_rows))

    target_raw_by_id: dict[int, list[dict[str, Any]]] = defaultdict(list)
    raw_jc_rows: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for raw, parsed_rows in target_rows:
        values = raw["values"]
        match_id = nowscore._integer(values[0])
        if match_id is None:
            continue
        target_raw_by_id[match_id].append(raw)
        if len(values) > 32 and values[32] == 1 and len(parsed_rows) == 1:
            raw_jc_rows.append((raw, parsed_rows[0]))

    duplicate_count = sum(
        max(0, len(raw_rows_for_id) - 1)
        for raw_rows_for_id in target_raw_by_id.values()
    )
    by_id = {
        match_id: normalized_by_id.get(match_id, [])
        for match_id in target_raw_by_id
    }
    ambiguous_count = sum(
        1
        for rows_for_id in by_id.values()
        if len({_signature(row) for row in rows_for_id}) > 1
    )
    fixture_by_id: dict[int, dict[str, Any]] = {}
    for raw, parsed in raw_jc_rows:
        match_id = int(parsed["nowscore_id"])
        if match_id in fixture_by_id:
            continue
        fixture_by_id[match_id] = {
            "nowscore_id": match_id,
            "home": parsed.get("home_team"),
            "away": parsed.get("away_team"),
            "home_en": parsed.get("home_team_en"),
            "away_en": parsed.get("away_team_en"),
            "kickoff_local": parsed.get("kickoff_local"),
            "match_number": None,
            "match_number_source": "not_present_in_schedule_row",
            "source_date": parsed.get("schedule_source_date"),
            "source_date_format": parsed.get("schedule_source_date_format"),
            "business_date": target.isoformat(),
            "date_provenance": {
                "source_date_value": raw["values"][11],
                "source_date_format": parsed.get("schedule_source_date_format"),
                "expected_business_date": target.isoformat(),
                "rule": "source date equals supplied business date; year is never inferred",
            },
            "jc_membership": "VERIFIED",
            "jc_membership_source": "nowscore_public_jc",
            "jc_membership_evidence": {
                "filter_function": "SetLevel(3)",
                "row_index": 32,
                "raw_value": raw["values"][32],
                "source_surface": source_url,
                "backing_data_url": backing_data_url,
                "array_index": raw["array_index"],
            },
            "source_surface": source_url,
            "source_url": backing_data_url,
            "fetched_at": fetched_at or _now(),
        }

    result = {
        "status": "PASS" if contract.get("valid") else "FAIL",
        "contract": contract,
        "expected_business_date": target.isoformat(),
        "source_url": source_url,
        "backing_data_url": backing_data_url,
        "fetched_at": fetched_at or _now(),
        "raw_match_count": len(rows),
        "target_row_count": len(target_rows),
        "jc_flagged_row_count": len(raw_jc_rows),
        "accepted_fixture_count": len(fixture_by_id),
        "duplicate_nowscore_id_count": duplicate_count,
        "ambiguous_nowscore_id_count": ambiguous_count,
        "diagnostics": parse_diagnostics,
        "fixtures": list(fixture_by_id.values()),
    }
    if duplicate_count or ambiguous_count:
        result["status"] = "FAIL"
        result["fixtures"] = []
        result["accepted_fixture_count"] = 0
    return result


def _fetch(url: str, *, referer: str) -> tuple[bytes, dict[str, Any]]:
    request = nowscore.urllib.request.Request(
        url,
        headers={
            "User-Agent": nowscore.USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/javascript,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
            "Accept-Encoding": "identity",
            "Referer": referer,
            "Cache-Control": "no-cache",
        },
    )
    with nowscore.urllib.request.urlopen(request, timeout=30) as response:
        raw = response.read()
        return raw, {
            "http_status": response.getcode(),
            "content_type": response.headers.get("Content-Type", ""),
            "bytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
        }


def _surface_result(surface: str, expected: date, fetched_at: str) -> dict[str, Any]:
    page_url = SCHEDULE_PAGE_URL.format(surface=surface)
    page_record: dict[str, Any] = {
        "url": page_url,
        "surface": surface,
        "status": "FETCH_ERROR",
    }
    data_record: dict[str, Any] = {
        "url": SCHEDULE_DATA_URL.format(filename=f"{surface}.js"),
        "surface": surface,
        "status": "FETCH_ERROR",
    }
    try:
        page_raw, page_meta = _fetch(page_url, referer=f"{Nowscore_URL}/")
        page_text = nowscore._decode(page_raw)
        page_record.update(page_meta, status="OK")
        page_contract = _page_contract(page_text, surface)
        filename = page_contract.get("filename2") or f"{surface}.js"
        if filename != f"{surface}.js":
            return {
                "status": "FAIL",
                "surface": surface,
                "page": page_record,
                "data": data_record,
                "error": "PAGE_BACKING_FILENAME_MISMATCH",
                "contract": page_contract,
                "fixtures": [],
                "accepted_fixture_count": 0,
            }
        data_url = SCHEDULE_DATA_URL.format(filename=filename)
        data_url = f"{data_url}?{int(time.time()) * 1000}"
        data_raw, data_meta = _fetch(data_url, referer=page_url)
        data_record.update(data_meta, url=data_url, status="OK")
        result = inspect_jc_surface(
            page_text,
            nowscore._decode(data_raw),
            expected_date=expected,
            source_url=page_url,
            backing_data_url=SCHEDULE_DATA_URL.format(filename=filename),
            fetched_at=fetched_at,
            surface=surface,
        )
        result["page"] = page_record
        result["data"] = data_record
        return result
    except Exception as error:
        return {
            "status": "FETCH_ERROR",
            "surface": surface,
            "page": page_record,
            "data": data_record,
            "error": f"{type(error).__name__}: {error}",
            "fixtures": [],
            "accepted_fixture_count": 0,
        }


def _legacy_comparison(target: date, today: date) -> dict[str, Any]:
    try:
        bundle = nowscore.fetch_schedule_bundle([target], now=today)
    except Exception as error:
        return {
            "status": "FETCH_ERROR",
            "error": f"{type(error).__name__}: {error}",
            "legacy_ids": [],
            "target_row_count": 0,
        }
    rows = [
        row
        for row in bundle.get("matches") or []
        if str(row.get("kickoff_local") or "")[:10] == target.isoformat()
    ]
    ids = sorted({int(row["nowscore_id"]) for row in rows if row.get("nowscore_id") is not None})
    return {
        "status": bundle.get("status"),
        "legacy_ids": ids,
        "target_row_count": len(rows),
        "duplicate_nowscore_id_count": bundle.get("duplicate_nowscore_id_count", 0),
        "errors": bundle.get("errors", []),
        "sources": bundle.get("sources", []),
        "future_surface": bundle.get("future_surface", {}),
    }


def run_probe(target_date: str, *, now: object = None) -> dict[str, Any]:
    target = _target_date(target_date)
    today = nowscore._now_shanghai_date(now)
    surface, surface_kind = _surface_for_date(target, today)
    fetched_at = _now()
    if not surface:
        return {
            "probe": "NOWSCORE-JC-UNIVERSE-1",
            "target_date": target.isoformat(),
            "today": today.isoformat(),
            "status": "FAIL",
            "decision_gate": "NO_CODE",
            "reason": "TARGET_DATE_OUTSIDE_CURRENT_OR_BOUNDED_FUTURE_SURFACE",
            "surfaces": [],
            "fixtures": [],
            "fetched_at": fetched_at,
        }
    surface_result = _surface_result(surface, target, fetched_at)
    accepted_fixtures = list(surface_result.get("fixtures") or [])
    legacy = _legacy_comparison(target, today)
    jc_ids = sorted({int(row["nowscore_id"]) for row in accepted_fixtures})
    legacy_ids = set(legacy.get("legacy_ids") or [])
    fixture_set_ok = bool(
        surface_result.get("status") == "PASS"
        and surface_result.get("accepted_fixture_count", 0) > 0
        and surface_result.get("duplicate_nowscore_id_count", 0) == 0
        and surface_result.get("ambiguous_nowscore_id_count", 0) == 0
        and all(row.get("jc_membership") == "VERIFIED" for row in accepted_fixtures)
        and all(row.get("nowscore_id") is not None for row in accepted_fixtures)
        and all(row.get("business_date") == target.isoformat() for row in accepted_fixtures)
    )
    return {
        "probe": "NOWSCORE-JC-UNIVERSE-1",
        "target_date": target.isoformat(),
        "today": today.isoformat(),
        "surface_kind": surface_kind,
        "fetched_at": fetched_at,
        "public_ui_contract": {
            "surface_url": SCHEDULE_PAGE_URL.format(surface=surface),
            "backing_data_surface": SCHEDULE_DATA_URL.format(filename=f"{surface}.js"),
            "membership_filter": "竞足 / SetLevel(3) / A[j][32] == 1",
            "credential_required": False,
        },
        "surfaces": [surface_result],
        "fixtures": accepted_fixtures,
        "legacy_schedule_comparison": {
            **legacy,
            "jc_ids": jc_ids,
            "intersection_ids": sorted(set(jc_ids) & legacy_ids),
            "jc_only_ids": sorted(set(jc_ids) - legacy_ids),
            "legacy_only_ids": sorted(legacy_ids - set(jc_ids)),
        },
        "decision_gate": "PASS" if fixture_set_ok else "NO_CODE",
        "status": "PASS" if fixture_set_ok else "FAIL",
        "reason": None if fixture_set_ok else "JC_CONTRACT_OR_FIXTURE_GATE_FAILED",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe Nowscore public JC schedule contract")
    parser.add_argument("--date", default=TARGET_DATE)
    parser.add_argument("--output", type=Path, default=REPO_ROOT / "nowscore-jc-probe.json")
    args = parser.parse_args()
    payload = run_probe(args.date)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
