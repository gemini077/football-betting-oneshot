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
from datetime import date, datetime
from pathlib import Path
from typing import Any
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
    """Use the production parser for the exact JC contract probe."""
    return nowscore.parse_nowscore_jc_surface(
        page_text,
        js_text,
        expected_date=expected_date,
        source_url=source_url,
        backing_data_url=backing_data_url,
        fetched_at=fetched_at,
        surface=surface,
    )


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
