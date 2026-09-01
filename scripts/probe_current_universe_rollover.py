#!/usr/bin/env python3
"""Run one bounded current-business-date source probe.

The probe is intentionally independent of the production refresh path.  It
records the response contract and date evidence for the two official Sporttery
route families plus the current 500.com trade page, without writing production
state or retrying requests.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import html
import json
import platform
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from fetch_trade_matches import parse_trade_matches
except ImportError:  # package imports used by tests
    from scripts.fetch_trade_matches import parse_trade_matches


REPO_ROOT = Path(__file__).resolve().parents[1]
TARGET_DATE = "2026-09-01"
REQUEST_TIMEOUT_SECONDS = 30
MAX_RESPONSE_BYTES = 10 * 1024 * 1024
POOL_CODE = "had,hhad,crs,ttg,hafu"

REPO_CALCULATOR_URL = (
    "https://webapi.sporttery.cn/gateway/uniform/football/"
    "getMatchCalculatorV1.qry?channel=tycp"
)
JC_MATCH_LIST_URL = (
    "https://webapi.sporttery.cn/gateway/jc/football/"
    "getMatchListV1.qry?clientCode=3001"
)
UNIFORM_MATCH_LIST_URL = (
    "https://webapi.sporttery.cn/gateway/uniform/football/"
    "getMatchListV1.qry?clientCode=3001"
)
JC_CALCULATOR_URL = (
    "https://webapi.sporttery.cn/gateway/jc/football/"
    f"getMatchCalculatorV1.qry?channel=c&poolCode={POOL_CODE}"
)
UNIFORM_CALCULATOR_URL = (
    "https://webapi.sporttery.cn/gateway/uniform/football/"
    f"getMatchCalculatorV1.qry?channel=c&poolCode={POOL_CODE}"
)
TRADE_URL = "https://trade.500.com/jczq/?playid=312&g=2"

REPO_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) "
        "Version/17.0 Mobile/15E148 Safari/604.1"
    ),
    "Accept": "application/json",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Referer": "https://m.sporttery.cn/",
    "Accept-Encoding": "gzip",
}

OFFICIAL_PAGE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) "
        "Version/17.5 Mobile/15E148 Safari/604.1"
    ),
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Referer": "https://m.sporttery.cn/mjc/jsq/zqspf/",
    "Origin": "https://m.sporttery.cn",
    "X-Requested-With": "XMLHttpRequest",
    "Accept-Encoding": "gzip",
}

TRADE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Accept-Encoding": "gzip",
    "Referer": "https://trade.500.com/",
}

PROBES = (
    {
        "id": "A_repo_current",
        "family": "official_calculator",
        "url": REPO_CALCULATOR_URL,
        "headers": REPO_HEADERS,
    },
    {
        "id": "A_repo_official_headers",
        "family": "official_calculator",
        "url": REPO_CALCULATOR_URL,
        "headers": OFFICIAL_PAGE_HEADERS,
    },
    {
        "id": "B_jc_match_list",
        "family": "official_match_list",
        "url": JC_MATCH_LIST_URL,
        "headers": OFFICIAL_PAGE_HEADERS,
    },
    {
        "id": "B_uniform_match_list",
        "family": "official_match_list",
        "url": UNIFORM_MATCH_LIST_URL,
        "headers": OFFICIAL_PAGE_HEADERS,
    },
    {
        "id": "C_jc_calculator",
        "family": "official_calculator_contract",
        "url": JC_CALCULATOR_URL,
        "headers": OFFICIAL_PAGE_HEADERS,
    },
    {
        "id": "C_uniform_calculator",
        "family": "official_calculator_contract",
        "url": UNIFORM_CALCULATOR_URL,
        "headers": OFFICIAL_PAGE_HEADERS,
    },
    {
        "id": "D_trade_page",
        "family": "trade_page",
        "url": TRADE_URL,
        "headers": TRADE_HEADERS,
    },
)


def _date_value(value: Any) -> str | None:
    text = str(value or "").strip()
    match = re.search(r"(?<!\d)(20\d{2})[-/]?(\d{2})[-/]?(\d{2})(?!\d)", text)
    if not match:
        return None
    return f"{match.group(1)}-{match.group(2)}-{match.group(3)}"


def _first_date(record: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = _date_value(record.get(key))
        if value:
            return value
    return None


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _is_success(value: Any) -> bool:
    return value is True or _text(value).casefold() == "true"


def _response_type(raw: bytes, content_type: str) -> str:
    lowered = content_type.casefold()
    stripped = raw.lstrip()
    if "json" in lowered or stripped.startswith((b"{", b"[")):
        return "JSON"
    if "html" in lowered or stripped.startswith((b"<", b"<!")):
        return "HTML"
    if "text/" in lowered or not raw:
        return "TEXT"
    return "BINARY"


def _decode_body(raw: bytes, content_type: str) -> str:
    charset_match = re.search(r"charset=([^;\s]+)", content_type, re.IGNORECASE)
    candidates = [charset_match.group(1).strip('"\'') if charset_match else None]
    candidates.extend(["utf-8", "gb18030", "gbk"])
    for encoding in candidates:
        if not encoding:
            continue
        try:
            return raw.decode(encoding)
        except (LookupError, UnicodeDecodeError):
            continue
    return raw.decode("utf-8", errors="replace")


def _waf_evidence(status: int | None, body_text: str) -> list[str]:
    evidence: list[str] = []
    if status in {403, 429, 503, 567}:
        evidence.append(f"HTTP_{status}")
    patterns = (
        ("WAF_MARKER", r"\bwaf\b|腾讯云|安全防护|访问被拒绝|请求被拦截"),
        ("ACCESS_DENIED_MARKER", r"access denied|request blocked|forbidden|captcha|challenge"),
    )
    compact = re.sub(r"\s+", " ", html.unescape(body_text)).strip()
    for name, pattern in patterns:
        match = re.search(pattern, compact, re.IGNORECASE)
        if match:
            start = max(0, match.start() - 80)
            end = min(len(compact), match.end() + 160)
            evidence.append(f"{name}: {compact[start:end]}")
    return evidence


def _read_response(response: Any) -> tuple[bytes, str]:
    raw = response.read(MAX_RESPONSE_BYTES + 1)
    content_encoding = str(response.headers.get("Content-Encoding") or "").casefold()
    if "gzip" in content_encoding:
        raw = gzip.decompress(raw)
    return raw, str(response.headers.get("Content-Type") or "")


def extract_official_summary(payload: Any, target_date: str) -> dict[str, Any]:
    """Summarize nested Sporttery match groups without using kickoff date as business date."""
    if not isinstance(payload, dict):
        return {
            "available_business_dates": [],
            "business_date_row_count": 0,
            "target_business_date_row_count": 0,
            "sample_match_ids": [],
            "sample_match_numbers": [],
            "target_business_date_rows": [],
        }

    value = payload.get("value") if isinstance(payload.get("value"), dict) else payload
    groups = value.get("matchInfoList") if isinstance(value, dict) else None
    if not isinstance(groups, list):
        groups = []

    available_dates: set[str] = set()
    total_rows = 0
    target_rows: list[dict[str, Any]] = []
    sample_ids: list[str] = []
    sample_numbers: list[str] = []
    for group in groups:
        if not isinstance(group, dict):
            continue
        group_date = _first_date(
            group, ("businessDate", "business_date", "matchNumDate", "processDate", "processdate")
        )
        if group_date:
            available_dates.add(group_date)
        rows = group.get("subMatchList")
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            total_rows += 1
            row_date = _first_date(
                row, ("businessDate", "business_date", "matchNumDate", "processDate", "processdate")
            )
            effective_date = row_date or group_date
            if effective_date:
                available_dates.add(effective_date)
            match_id = _text(row.get("matchId") or row.get("match_id") or row.get("id"))
            match_num = _text(row.get("matchNumStr") or row.get("matchNum") or row.get("match_num"))
            if effective_date == target_date:
                target_row = {
                    "match_id": match_id or None,
                    "match_num": match_num or None,
                    "business_date": effective_date,
                    "match_date": _first_date(row, ("matchDate", "match_date")),
                    "match_time": _text(row.get("matchTime") or row.get("match_time")) or None,
                    "home_team": _text(
                        row.get("homeTeamAbbName") or row.get("homeTeamAllName") or row.get("homeTeam")
                    )
                    or None,
                    "away_team": _text(
                        row.get("awayTeamAbbName") or row.get("awayTeamAllName") or row.get("awayTeam")
                    )
                    or None,
                }
                target_rows.append(target_row)
                if match_id and len(sample_ids) < 5:
                    sample_ids.append(match_id)
                if match_num and len(sample_numbers) < 5:
                    sample_numbers.append(match_num)

    return {
        "available_business_dates": sorted(available_dates),
        "business_date_row_count": total_rows,
        "target_business_date_row_count": len(target_rows),
        "sample_match_ids": sample_ids,
        "sample_match_numbers": sample_numbers,
        "target_business_date_rows": target_rows[:20],
    }


def _attribute(row_html: str, name: str) -> str | None:
    match = re.search(rf"\b{re.escape(name)}\s*=\s*([\"'])(.*?)\1", row_html, re.IGNORECASE | re.DOTALL)
    return html.unescape(match.group(2)) if match else None


def _iter_trade_rows(page_text: str):
    """Yield complete tr blocks for rows carrying data-matchnum, including nested tr tags."""
    tag_pattern = re.compile(r"<tr\b[^>]*>|</tr\s*>", re.IGNORECASE)
    start: int | None = None
    depth = 0
    for match in tag_pattern.finditer(page_text):
        tag = match.group(0)
        if tag.casefold().startswith("<tr"):
            if start is None:
                if re.search(r"\bdata-matchnum\s*=\s*[\"']", tag, re.IGNORECASE):
                    start = match.start()
                    depth = 1
            else:
                depth += 1
        elif start is not None:
            depth -= 1
            if depth == 0:
                yield page_text[start : match.end()]
                start = None


def summarize_trade_page(
    page_text: str,
    target_date: str,
    *,
    parser_target_row_count: int | None = None,
) -> dict[str, Any]:
    raw_rows: list[dict[str, Any]] = []
    for row_html in _iter_trade_rows(page_text):
        match_num = _attribute(row_html, "data-matchnum")
        process_date = _attribute(row_html, "data-processdate")
        match_date = _attribute(row_html, "data-matchdate")
        match_time = _attribute(row_html, "data-matchtime")
        shuju_match = re.search(r"shuju-(\d+)\.shtml", row_html, re.IGNORECASE)
        raw_rows.append(
            {
                "match_num": match_num,
                "shuju_id": shuju_match.group(1) if shuju_match else None,
                "data_processdate": _date_value(process_date),
                "data_matchdate": _date_value(match_date),
                "data_matchtime": match_time,
                "raw_row_sha256": hashlib.sha256(row_html.encode("utf-8")).hexdigest(),
                "raw_row_html": row_html,
            }
        )

    process_dates = sorted({row["data_processdate"] for row in raw_rows if row["data_processdate"]})
    match_dates = sorted({row["data_matchdate"] for row in raw_rows if row["data_matchdate"]})
    page_headers = sorted(
        {
            value
            for value in re.findall(r"(?<!\d)(20\d{2}-\d{2}-\d{2})\s*(?:星期|周)", page_text)
            if value
        }
    )
    target_process_rows = [row for row in raw_rows if row["data_processdate"] == target_date]
    target_match_rows = [row for row in raw_rows if row["data_matchdate"] == target_date]
    sample_ids = [row["shuju_id"] for row in raw_rows if row["shuju_id"]][:5]
    sample_numbers = [row["match_num"] for row in raw_rows if row["match_num"]][:5]
    summary: dict[str, Any] = {
        "available_business_dates": sorted(set(process_dates) | set(page_headers)),
        "available_match_dates": match_dates,
        "page_date_headers": page_headers,
        "raw_match_row_count": len(raw_rows),
        "target_business_date_row_count": len(target_process_rows),
        "target_match_date_row_count": len(target_match_rows),
        "target_business_date_rows": target_process_rows,
        "target_match_date_rows": target_match_rows,
        "raw_match_rows": raw_rows,
        "sample_match_ids": sample_ids,
        "sample_match_numbers": sample_numbers,
    }
    if parser_target_row_count is not None:
        summary["current_parser_target_row_count"] = parser_target_row_count
    return summary


def _base_record(spec: dict[str, Any]) -> dict[str, Any]:
    return {
        "probe_family": spec["family"],
        "url": spec["url"],
        "request_headers": sorted(spec["headers"]),
        "http_status": None,
        "response_type": None,
        "success": False,
        "http_success": False,
        "payload_success": None,
        "response_bytes": 0,
        "response_sha256": None,
        "waf_blocked": False,
        "waf_block_evidence": [],
        "available_business_dates": [],
        "available_match_dates": [],
        "business_date_row_count": 0,
        "target_business_date_row_count": 0,
        "target_match_date_row_count": 0,
        "sample_match_ids": [],
        "sample_match_numbers": [],
    }


def _fetch_probe(spec: dict[str, Any], target_date: str) -> dict[str, Any]:
    result = _base_record(spec)
    started = time.monotonic()
    raw = b""
    content_type = ""
    body_text = ""
    try:
        request = urllib.request.Request(spec["url"], headers=spec["headers"])
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            result["http_status"] = int(response.getcode())
            raw, content_type = _read_response(response)
    except urllib.error.HTTPError as error:
        result["http_status"] = int(error.code)
        try:
            raw, content_type = _read_response(error)
        except Exception:
            raw = b""
            content_type = str(error.headers.get("Content-Type") if error.headers else "")
        result["error"] = f"HTTPError: {error}"
    except (OSError, TimeoutError, urllib.error.URLError) as error:
        result["error"] = f"{type(error).__name__}: {error}"
    finally:
        result["http_success"] = result["http_status"] == 200
        result["duration_ms"] = round((time.monotonic() - started) * 1000, 1)

    result["response_bytes"] = len(raw)
    result["response_sha256"] = hashlib.sha256(raw).hexdigest() if raw else None
    result["response_type"] = _response_type(raw, content_type)
    result["content_type"] = content_type
    body_text = _decode_body(raw, content_type) if raw else ""
    waf_evidence = _waf_evidence(result["http_status"], body_text)
    result["waf_block_evidence"] = waf_evidence
    result["waf_blocked"] = bool(waf_evidence)
    if not raw:
        return result

    if spec["family"] == "trade_page":
        try:
            parser_rows = parse_trade_matches(body_text, target_date)
            parser_count = len(parser_rows)
        except Exception as error:  # preserve probe evidence even if parser rejects the page
            parser_count = 0
            result["parser_error"] = f"{type(error).__name__}: {error}"
        summary = summarize_trade_page(
            body_text, target_date, parser_target_row_count=parser_count
        )
        result.update(summary)
        result["page_fetch_success"] = result["http_status"] == 200
        result["parser_success"] = bool(parser_count)
        result["success"] = bool(result["page_fetch_success"] and parser_count)
        return result

    try:
        payload = json.loads(body_text)
    except json.JSONDecodeError as error:
        result["json_error"] = str(error)
        return result
    result["payload_success"] = _is_success(payload.get("success")) if isinstance(payload, dict) else False
    summary = extract_official_summary(payload, target_date)
    result.update(summary)
    result["success"] = bool(
        result["http_status"] == 200
        and result["payload_success"]
        and result["target_business_date_row_count"]
    )
    return result


def _row_count(record: dict[str, Any], key: str = "target_business_date_row_count") -> int:
    try:
        return int(record.get(key) or 0)
    except (TypeError, ValueError):
        return 0


def _has_waf(record: dict[str, Any]) -> bool:
    return bool(record.get("waf_blocked") or record.get("waf_block_evidence"))


def classify_probe(probes: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Apply the rollover decision gate to bounded probe facts."""
    a_current = _row_count(probes.get("A_repo_current", {}))
    a_official_headers = _row_count(probes.get("A_repo_official_headers", {}))
    list_target = max(
        _row_count(probes.get("B_jc_match_list", {})),
        _row_count(probes.get("B_uniform_match_list", {})),
    )
    calculator_target = max(
        _row_count(probes.get("C_jc_calculator", {})),
        _row_count(probes.get("C_uniform_calculator", {})),
    )
    trade = probes.get("D_trade_page", {})
    trade_process_target = _row_count(trade)
    trade_match_target = _row_count(trade, "target_match_date_row_count")
    parser_target = _row_count(trade, "current_parser_target_row_count")
    official_target = max(list_target, calculator_target)

    causes: list[str] = []
    reasons: list[str] = []
    if a_official_headers > 0 and a_current == 0:
        causes.append("WAF_BLOCK")
        reasons.append("current repo headers miss target rows while official mobile-page headers return rows")
    if list_target > 0 and a_current == 0 and a_official_headers == 0:
        causes.append("STALE_ENDPOINT_CONTRACT")
        reasons.append("official getMatchListV1 returns target rows while repo calculator contract does not")
    if calculator_target > 0 and list_target == 0 and a_current == 0 and a_official_headers == 0:
        causes.append("WRONG_CHANNEL_OR_POOL_CONTRACT")
        reasons.append("only channel=c with poolCode calculator contract returns target rows")
    if trade_process_target > 0 and parser_target == 0:
        causes.append("BUSINESS_DATE_FILTER_BUG")
        reasons.append("raw target process-date rows are dropped by the current parser")
    elif trade_process_target == 0 and trade_match_target > 0 and parser_target == 0:
        causes.append("SOURCE_ROLLOVER_LAG")
        reasons.append("500 rows have target match dates but remain assigned to an earlier process date")

    all_official = [probes.get(name, {}) for name in (
        "A_repo_current",
        "A_repo_official_headers",
        "B_jc_match_list",
        "B_uniform_match_list",
        "C_jc_calculator",
        "C_uniform_calculator",
    )]
    if not official_target and any(_has_waf(record) for record in all_official):
        causes.append("WAF_BLOCK")
        reasons.append("official probe response contains HTTP or body-level block evidence")

    unique_causes = list(dict.fromkeys(causes))
    if len(unique_causes) > 1:
        classification = "MULTI_CAUSE"
    elif unique_causes:
        classification = unique_causes[0]
    else:
        classification = "SOURCE_ROLLOVER_LAG" if not official_target and not trade_process_target else "MULTI_CAUSE"

    if a_official_headers > 0 and a_current == 0:
        decision_gate = "FIX_HEADERS_ONLY"
    elif official_target > 0:
        decision_gate = "FIX_OFFICIAL_ROUTE"
    elif trade_process_target > 0 and parser_target == 0:
        decision_gate = "FIX_PARSER_ONLY"
    else:
        decision_gate = "NO_CODE"

    return {
        "classification": classification,
        "classification_causes": unique_causes,
        "classification_reasons": reasons,
        "decision_gate": decision_gate,
        "official_target_row_count": official_target,
        "repo_current_target_row_count": a_current,
        "repo_official_headers_target_row_count": a_official_headers,
        "trade_process_target_row_count": trade_process_target,
        "trade_match_date_target_row_count": trade_match_target,
        "trade_parser_target_row_count": parser_target,
    }


def run_probe(target_date: str) -> dict[str, Any]:
    started_at = datetime.now(timezone.utc).isoformat()
    probes: dict[str, dict[str, Any]] = {}
    for spec in PROBES:
        probes[spec["id"]] = _fetch_probe(spec, target_date)
    finished_at = datetime.now(timezone.utc).isoformat()
    return {
        "schema_version": "1.0",
        "milestone": "CURRENT-UNIVERSE-ROLLOVER-1",
        "target_business_date": target_date,
        "probe_policy": "one request per route, no retry, no production-state writes",
        "runner": {
            "platform": platform.platform(),
            "python": sys.version.split()[0],
        },
        "started_at": started_at,
        "finished_at": finished_at,
        "probes": probes,
        "decision": classify_probe(probes),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Bounded Sporttery/500.com current-universe rollover probe")
    parser.add_argument("--date", default=TARGET_DATE, help="target business date YYYY-MM-DD")
    parser.add_argument("--output", type=Path, default=REPO_ROOT / "current-universe-rollover-probe.json")
    args = parser.parse_args()
    payload = run_probe(args.date)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
