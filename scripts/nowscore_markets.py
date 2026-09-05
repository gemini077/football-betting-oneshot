#!/usr/bin/env python3
"""Read-only Nowscore schedule matching and three-in-one market parser.

The public three-in-one page contains, per company, opening/current Asian
handicap, 1X2 and goal-total quotes.  A snapshot is accepted only after the
home team, away team and kickoff have been checked in the same orientation.
"""

from __future__ import annotations

import argparse
import ast
import html as html_lib
import json
import re
import time
import urllib.error
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections.abc import Iterable, Mapping
from datetime import date, datetime, time as datetime_time, timedelta
from html.parser import HTMLParser
from pathlib import Path
from zoneinfo import ZoneInfo

from provider_match_registry import lookup as lookup_provider_binding
from provider_match_registry import record_binding
from team_identity import clean_display_name, team_similarity

try:
    from prediction_universe import trusted_nowscore_jc_fixture
except ImportError:  # package imports used by tests
    from scripts.prediction_universe import trusted_nowscore_jc_fixture


ROOT = Path(__file__).resolve().parents[1]
CACHE_ROOT = ROOT / "data" / "source_cache" / "nowscore"
SCHEDULE_URL = "https://live.nowscore.com/data/bf1.js"
FUTURE_SCHEDULE_URL = "https://live.nowscore.com/data/sc{offset}.js"
MAX_FUTURE_SCHEDULE_OFFSET = 7
JC_SCHEDULE_PAGE_URL = "https://live.nowscore.com/schedule.aspx?f={surface}"
JC_SCHEDULE_DATA_URL = "https://live.nowscore.com/data/{filename}"
NOT_YET_PUBLISHED = "NOT_YET_PUBLISHED"
JC_BUSINESS_PAGE_URL = (
    "https://cp.nowscore.com/buy/jingcai.aspx"
    "?typeID=101&oddstype=2&date={business_date}"
)
MARKET_URL = "https://live.nowscore.com/odds/match/{match_id}.htm"
ANALYSIS_DATA_URL = "https://live.nowscore.com/analysisJs/data{match_id}.js"
COACH_URL = "https://live.nowscore.com/info/coach/{match_id}.htm?l=1"
REFEREE_URL = "https://live.nowscore.com/info/referee/{match_id}.htm?l=1"
PANLU_URL = "https://live.nowscore.com/panlu/{match_id}.html"
COMPANY_TREND_URL = "https://live.nowscore.com/odds/3in1Odds.aspx?companyid={company_id}&id={match_id}"
TREND_COMPANY_IDS = (1, 3, 4, 8, 12, 14, 17, 22, 24, 31, 9, 7, 19, 35, 42, 47, 48, 49)
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
SHANGHAI = ZoneInfo("Asia/Shanghai")
_IDENTITY_RESOLVER = None

# Stable Nowscore company IDs mapped to this project's confirmed canonical
# bookmaker IDs.  The original provider ID is retained on every row.
COMPANIES = {
    1: (5, "澳门"),
    3: (280, "皇冠"),
    4: (2, "立博"),
    8: (3, "bet365"),
    9: (293, "威廉希尔"),
    12: (9, "易胜博"),
    14: (6, "伟德"),
    19: (4, "Interwetten"),
    24: (16, "12bet"),
    31: (651, "利记"),
    47: (1055, "Pinnacle"),
    49: (11, "Bwin"),
}

# Public Nowscore source-company labels.  Keep this separate from the
# project's canonical bookmaker IDs: it is only used for transparent display
# and must not accidentally merge two providers in the market tables.
SOURCE_COMPANY_NAMES = {
    1: "澳门", 3: "皇冠", 4: "立博", 8: "bet365", 9: "威廉希尔",
    12: "易胜博", 14: "伟德", 17: "Mansion88", 19: "Interwetten",
    22: "10BET", 24: "12BET", 31: "SBOBET", 35: "Wewbet",
    42: "18BET", 47: "Pinnacle", 49: "Bwin",
}


def _fetch_bytes(url: str, timeout: int = 30) -> bytes:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/javascript,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
            "Accept-Encoding": "identity",
            "Referer": "https://live.nowscore.com/",
            "Cache-Control": "no-cache",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def _decode(raw: bytes) -> str:
    for encoding in ("utf-8", "gb18030"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _split_js_values(raw: str) -> list[object]:
    values: list[str] = []
    current: list[str] = []
    quote = None
    escaped = False
    for char in raw:
        if escaped:
            current.append(char)
            escaped = False
        elif char == "\\" and quote:
            current.append(char)
            escaped = True
        elif quote:
            current.append(char)
            if char == quote:
                quote = None
        elif char in ("'", '"'):
            current.append(char)
            quote = char
        elif char == ",":
            values.append("".join(current).strip())
            current = []
        else:
            current.append(char)
    values.append("".join(current).strip())

    parsed: list[object] = []
    for token in values:
        if not token or token in ("null", "undefined"):
            parsed.append(None)
        elif len(token) >= 2 and token[0] == token[-1] and token[0] in ("'", '"'):
            parsed.append(token[1:-1].replace("\\'", "'").replace('\\"', '"'))
        else:
            try:
                parsed.append(float(token) if "." in token else int(token))
            except ValueError:
                parsed.append(token)
    return parsed


def _normalise_expected_date(value: object) -> date | None:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.date()
        return value.astimezone(SHANGHAI).date()
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        compact = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", text)
        if not compact:
            return None
        try:
            return date(*(int(part) for part in compact.groups()))
        except ValueError:
            return None


def _parse_schedule_clock(value: object) -> datetime_time | None:
    found = re.fullmatch(r"\s*(\d{1,2}):(\d{2})(?::(\d{2}))?\s*", str(value or ""))
    if not found:
        return None
    try:
        return datetime_time(
            int(found.group(1)), int(found.group(2)), int(found.group(3) or 0)
        )
    except ValueError:
        return None


def _integer(value: object) -> int | None:
    try:
        if value is None or str(value).strip() == "":
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _schedule_datetime(
    source_date: object,
    kickoff_value: object,
    expected_date: date | None,
) -> tuple[datetime | None, date | str, str]:
    source_text = str(source_date or "").strip()
    full_parts = source_text.split(",")
    if len(full_parts) == 6 and all(re.fullmatch(r"\d+", part.strip()) for part in full_parts):
        try:
            year, month_zero_based, day, hour, minute, second = (
                int(part.strip()) for part in full_parts
            )
            calendar_date = date(year, month_zero_based + 1, day)
            clock = datetime_time(hour, minute, second)
        except ValueError:
            return None, "invalid_full_date", "full_datetime"
        if expected_date is not None and calendar_date != expected_date:
            return None, "source_date_mismatch", "full_datetime"
        return (
            datetime.combine(calendar_date, clock).replace(tzinfo=SHANGHAI),
            calendar_date,
            "full_datetime",
        )

    month_day = re.fullmatch(r"(\d{2})-(\d{2})", source_text)
    if month_day:
        if expected_date is None:
            return None, "expected_date_required", "month_day"
        month, day = int(month_day.group(1)), int(month_day.group(2))
        if (month, day) != (expected_date.month, expected_date.day):
            return None, "source_date_mismatch", "month_day"
        clock = _parse_schedule_clock(kickoff_value)
        if clock is None:
            return None, "invalid_kickoff_time", "month_day"
        return (
            datetime.combine(expected_date, clock).replace(tzinfo=SHANGHAI),
            expected_date,
            "month_day",
        )

    return None, "invalid_source_date", "unknown"


def _parse_schedule_js(
    text: str, expected_date: object = None
) -> tuple[list[dict], dict[str, int]]:
    expected = _normalise_expected_date(expected_date)
    expected_was_supplied = expected_date is not None and str(expected_date).strip() != ""
    diagnostics: Counter[str] = Counter()
    if expected_was_supplied and expected is None:
        diagnostics["invalid_expected_date"] += 1
        return [], dict(diagnostics)

    matches = []
    for found in re.finditer(r"(?m)^A\[\d+\]=\[(.*?)\];\s*$", text):
        row = _split_js_values(found.group(1))
        if len(row) < 12:
            diagnostics["short_row"] += 1
            continue
        match_id = _integer(row[0])
        if match_id is None:
            diagnostics["invalid_match_id"] += 1
            continue
        kickoff, parsed_date, date_format = _schedule_datetime(
            row[11], row[10], expected
        )
        if kickoff is None:
            diagnostics[str(parsed_date)] += 1
            continue
        matches.append({
            "nowscore_id": match_id,
            "home_team_id": _integer(row[2]),
            "away_team_id": _integer(row[3]),
            "home_team": clean_display_name(row[4]),
            "home_team_en": clean_display_name(row[6]),
            "away_team": clean_display_name(row[7]),
            "away_team_en": clean_display_name(row[9]),
            "kickoff_local": kickoff.isoformat(timespec="minutes"),
            "schedule_source_date": parsed_date.isoformat(),
            "schedule_source_date_format": date_format,
            "schedule_open_handicap": row[25] if len(row) > 25 else None,
            "schedule_total_line": row[29] if len(row) > 29 else None,
        })
    return matches, dict(diagnostics)


def _public_jc_page_contract(page_text: str, surface: str) -> dict:
    """Read the explicit public schedule-page contract for the JC filter."""
    filename_match = re.search(
        r"\bfilename2\s*=\s*[\"'](?P<filename>[^\"']+)[\"']",
        page_text,
        re.IGNORECASE,
    )
    filename = filename_match.group("filename") if filename_match else ""
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
    row_index_contract = bool(
        re.search(
            r"if\s*\(\s*l\s*==\s*3\s*\).*?index\s*=\s*32\s*;",
            function_body,
            re.IGNORECASE | re.DOTALL,
        )
    )
    predicate_contract = bool(
        re.search(
            r"A\s*\[\s*j\s*\]\s*\[\s*index\s*\]\s*==\s*1",
            function_body,
            re.IGNORECASE,
        )
    )
    return {
        "surface": surface,
        "expected_filename": f"{surface}.js",
        "filename2": filename or None,
        "jc_filter_link_present": link_match is not None,
        "jc_filter_label": (
            re.sub(r"<[^>]+>", "", link_match.group("label")).strip()
            if link_match
            else None
        ),
        "function_present": function_match is not None,
        "row_index": 32,
        "filter_function": "SetLevel(3)",
        "predicate": "A[j][32] == 1",
        "row_index_contract_present": row_index_contract,
        "predicate_contract_present": predicate_contract,
        "valid": bool(
            filename == f"{surface}.js"
            and link_match
            and function_match
            and row_index_contract
            and predicate_contract
        ),
    }


class _JcBusinessPageParser(HTMLParser):
    """Collect Nowscore public JC sales-day headers and rows."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tr_depth = 0
        self.current: dict[str, object] | None = None
        self.cell_active = False
        self.cell_text: list[str] = []
        self.rows: list[dict[str, object]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {key.lower(): value or "" for key, value in attrs}
        lower = tag.lower()
        if lower == "tr":
            if self.tr_depth == 0:
                self.current = {
                    "attrs": attributes,
                    "cells": [],
                    "data": [],
                    "ids": [],
                    "titles": [],
                    "onclicks": [],
                }
            self.tr_depth += 1
            return
        if self.current is None or self.tr_depth == 0:
            return
        for key, target in (("id", "ids"), ("title", "titles"), ("onclick", "onclicks")):
            if attributes.get(key):
                self.current[target].append(attributes[key])
        if lower in {"td", "th"} and self.tr_depth == 1:
            self.cell_active = True
            self.cell_text = []

    def handle_data(self, data: str) -> None:
        if self.current is None or self.tr_depth == 0:
            return
        self.current["data"].append(data)
        if self.cell_active and self.tr_depth == 1:
            self.cell_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        lower = tag.lower()
        if lower in {"td", "th"} and self.current is not None and self.tr_depth == 1:
            self.current["cells"].append(" ".join("".join(self.cell_text).split()))
            self.cell_active = False
            self.cell_text = []
        if lower != "tr" or self.tr_depth == 0:
            return
        self.tr_depth -= 1
        if self.tr_depth == 0 and self.current is not None:
            self.rows.append(self.current)
            self.current = None
            self.cell_active = False
            self.cell_text = []


def _date_from_nowscore_text(text: object) -> date | None:
    found = re.search(
        r"(20\d{2})\D{1,8}(\d{1,2})\D{1,8}(\d{1,2})",
        str(text or ""),
    )
    if not found:
        return None
    try:
        return date(*(int(value) for value in found.groups()))
    except ValueError:
        return None


def _nowscore_jc_group_name(row: Mapping[str, object]) -> str | None:
    for value in row.get("ids") or []:
        text = str(value)
        if text.startswith("ah_"):
            return text[3:]
    for onclick in row.get("onclicks") or []:
        found = re.search(r"isShowSclass\(\s*['\"]([^'\"]+)", str(onclick), re.I)
        if found:
            return found.group(1)
    return None


def _classify_nowscore_jc_publication(
    contract: Mapping[str, object], expected: date | None
) -> str | None:
    """Classify a missing sales-day header without weakening the page contract."""
    if expected is None:
        return None
    if contract.get("surface") != "nowscore_public_jc_sales":
        return None
    if contract.get("date_selector_present") is not True:
        return None
    headers = contract.get("headers")
    if not isinstance(headers, list) or not headers:
        return None
    conflicting_groups = contract.get("conflicting_groups")
    if not isinstance(conflicting_groups, Mapping) or conflicting_groups:
        return None

    published_dates: list[date] = []
    groups_by_date: dict[date, set[str]] = {}
    for header in headers:
        if not isinstance(header, Mapping):
            return None
        header_date = _normalise_expected_date(header.get("date"))
        group = str(header.get("group") or "").strip()
        if header_date is None or not group:
            return None
        if header.get("sales_window") != "11:00--次日11:00":
            return None
        published_dates.append(header_date)
        groups_by_date.setdefault(header_date, set()).add(group)

    if any(len(groups) > 1 for groups in groups_by_date.values()):
        return None
    if expected in published_dates:
        return None
    if expected <= max(published_dates):
        return None
    return NOT_YET_PUBLISHED


def parse_nowscore_jc_business_page(
    page_text: str,
    *,
    business_date: object,
) -> dict:
    """Parse one selected Nowscore JC sales-day group.

    The page's selected ``SelDate`` and matching ``niDate`` header are the
    published business-date contract.  A missing requested header is classified
    separately from a malformed contract.  Kickoff is checked against the
    page's explicit sales window, but never used to derive the business date.
    """
    expected = _normalise_expected_date(business_date)
    if expected is None:
        return {
            "status": "FAIL",
            "business_date": str(business_date or ""),
            "fixtures": [],
            "error": "INVALID_BUSINESS_DATE",
        }

    parser = _JcBusinessPageParser()
    parser.feed(page_text)
    headers: list[dict[str, object]] = []
    group_dates: dict[str, list[str]] = {}
    for row in parser.rows:
        attributes = row.get("attrs") or {}
        classes = str(attributes.get("class") or "").split()
        if "niDate" not in classes:
            continue
        text = " ".join(str(value) for value in row.get("data") or [])
        group = _nowscore_jc_group_name(row)
        group_date = _date_from_nowscore_text(text)
        window_match = re.search(r"\(([^()]*--[^()]*)\)", text)
        raw_window = window_match.group(1).strip() if window_match else ""
        window = re.sub(r"\s+", "", raw_window).replace("：", ":") or None
        header = {
            "group": group,
            "date": group_date.isoformat() if group_date else None,
            "sales_window": window,
        }
        headers.append(header)
        if group and group_date:
            group_dates.setdefault(group, []).append(group_date.isoformat())

    selected_match = re.search(
        r"\bSelDate\s*=\s*['\"](\d{4}-\d{1,2}-\d{1,2})['\"]",
        page_text,
        re.I,
    )
    selected = _normalise_expected_date(
        selected_match.group(1) if selected_match else None
    )
    select_match = re.search(
        r"<select\b[^>]*onchange=[\"'][\s\S]*?</select>",
        page_text,
        re.I,
    )
    select_text = select_match.group(0) if select_match else ""
    date_selector_present = bool(
        "this.options[this.selectedIndex].value" in select_text
        and "date=" in select_text
    )
    expected_text = expected.isoformat()
    requested_headers = [
        header for header in headers if header.get("date") == expected_text
    ]
    group_names = {
        str(header.get("group"))
        for header in requested_headers
        if header.get("group")
    }
    conflicting_groups = {
        group: sorted(set(values))
        for group, values in group_dates.items()
        if len(set(values)) > 1
    }
    header_valid = bool(
        len(requested_headers) == 1
        and len(group_names) == 1
        and requested_headers[0].get("sales_window") == "11:00--次日11:00"
    )
    group = next(iter(group_names)) if len(group_names) == 1 else None

    fixtures: list[dict] = []
    for row in parser.rows:
        attributes = row.get("attrs") or {}
        row_id = str(attributes.get("id") or "")
        if not row_id.startswith("row_") or attributes.get("name") != group:
            continue
        nowscore_ids = sorted({
            int(found.group(1))
            for value in row.get("ids") or []
            for found in [
                re.search(r"(?:HomeTeam|GuestTeam)_(\d+)$", str(value), re.I)
            ]
            if found
        })
        kickoff_matches = re.findall(
            r"20\d\d-\d\d-\d\d\s+\d\d:\d\d",
            " ".join(str(value) for value in row.get("titles") or []),
        )
        cells = list(row.get("cells") or [])
        match_number_value = cells[0] if cells else None
        fixtures.append({
            "sales_row_id": attributes.get("matchid") or row_id[4:],
            "match_number": (
                f"{group}{match_number_value}"
                if group and match_number_value
                else None
            ),
            "match_number_group": group,
            "match_number_value": match_number_value,
            "nowscore_ids": nowscore_ids,
            "nowscore_id": nowscore_ids[0] if len(nowscore_ids) == 1 else None,
            "kickoff": kickoff_matches[0] if kickoff_matches else None,
            "home_team": cells[4] if len(cells) > 4 else None,
            "away_team": cells[7] if len(cells) > 7 else None,
            "league": attributes.get("gamename"),
            "cansale": attributes.get("cansale"),
        })

    id_counts: Counter[int] = Counter(
        int(row["nowscore_id"])
        for row in fixtures
        if row.get("nowscore_id") is not None
    )
    duplicate_count = sum(max(0, count - 1) for count in id_counts.values())
    sales_row_counts: Counter[str] = Counter(
        str(row["sales_row_id"])
        for row in fixtures
        if row.get("sales_row_id") not in (None, "")
    )
    duplicate_sales_row_count = sum(
        max(0, count - 1) for count in sales_row_counts.values()
    )
    match_number_counts: Counter[str] = Counter(
        str(row["match_number"])
        for row in fixtures
        if row.get("match_number") not in (None, "")
    )
    duplicate_match_number_count = sum(
        max(0, count - 1) for count in match_number_counts.values()
    )
    ambiguous_count = sum(
        1 for row in fixtures if len(row.get("nowscore_ids") or []) != 1
    )
    window_start = datetime.combine(expected, datetime_time(11, 0)).replace(
        tzinfo=SHANGHAI
    )
    window_end = window_start + timedelta(days=1)
    outside_window = 0
    invalid_match_numbers = 0
    for row in fixtures:
        if not re.fullmatch(
            r"周[一二三四五六日天]\d{3}", str(row.get("match_number") or "")
        ):
            invalid_match_numbers += 1
        try:
            kickoff = datetime.strptime(
                str(row.get("kickoff") or ""), "%Y-%m-%d %H:%M"
            ).replace(tzinfo=SHANGHAI)
        except ValueError:
            outside_window += 1
            continue
        if not window_start <= kickoff < window_end:
            outside_window += 1

    contract = {
        "surface": "nowscore_public_jc_sales",
        "date_anchor": "SelDate + niDate header date",
        "sales_window": "11:00--次日11:00",
        "match_number": "niDate group name + row number cell",
        "selected_date": selected.isoformat() if selected else None,
        "requested_date": expected_text,
        "date_selector_present": date_selector_present,
        "headers": headers,
        "requested_header": requested_headers[0] if header_valid else None,
        "requested_group": group,
        "conflicting_groups": conflicting_groups,
        "valid": bool(
            selected == expected
            and date_selector_present
            and header_valid
            and not conflicting_groups
        ),
    }
    publication_status = _classify_nowscore_jc_publication(contract, expected)
    status = "PASS" if bool(
        contract["valid"]
        and fixtures
        and duplicate_count == 0
        and duplicate_sales_row_count == 0
        and duplicate_match_number_count == 0
        and ambiguous_count == 0
        and invalid_match_numbers == 0
        and outside_window == 0
    ) else "FAIL"
    if publication_status and not (
        fixtures
        or duplicate_count
        or duplicate_sales_row_count
        or duplicate_match_number_count
        or ambiguous_count
        or invalid_match_numbers
        or outside_window
    ):
        status = publication_status
        contract["publication_status"] = publication_status
    return {
        "status": status,
        "contract": contract,
        "business_date": expected_text,
        "row_count": len(fixtures),
        "duplicate_nowscore_id_count": duplicate_count,
        "duplicate_sales_row_id_count": duplicate_sales_row_count,
        "duplicate_match_number_count": duplicate_match_number_count,
        "ambiguous_row_count": ambiguous_count,
        "invalid_match_number_count": invalid_match_numbers,
        "outside_business_window_count": outside_window,
        "next_calendar_day_kickoff_count": sum(
            1
            for row in fixtures
            if str(row.get("kickoff") or "")[:10]
            == (expected + timedelta(days=1)).isoformat()
        ),
        "fixtures": fixtures,
    }


def _raw_schedule_rows(text: str) -> list[tuple[int, list[object]]]:
    rows: list[tuple[int, list[object]]] = []
    for found in re.finditer(r"(?m)^A\[(\d+)\]=\[(.*?)\];\s*$", text.lstrip("\ufeff")):
        rows.append((int(found.group(1)), _split_js_values(found.group(2))))
    return rows


def parse_nowscore_jc_surface(
    page_text: str,
    schedule_text: str,
    *,
    expected_date: object,
    source_url: str,
    backing_data_url: str,
    fetched_at: str | None = None,
    surface: str | None = None,
) -> dict:
    """Normalize one public Nowscore schedule page's explicit JC subset.

    The membership decision is intentionally limited to the page contract's
    numeric ``A[j][32] == 1`` value.  League, team name, odds, and kickoff
    similarity are never used to infer JC membership.
    """
    expected = _normalise_expected_date(expected_date)
    surface_name = surface or (
        re.search(r"[?&]f=([^&]+)", source_url, re.IGNORECASE).group(1)
        if re.search(r"[?&]f=([^&]+)", source_url, re.IGNORECASE)
        else "unknown"
    )
    contract = _public_jc_page_contract(page_text, surface_name)
    captured_at = fetched_at or datetime.now(SHANGHAI).isoformat(timespec="seconds")
    if expected is None:
        return {
            "status": "FAIL",
            "contract": contract,
            "expected_business_date": str(expected_date or ""),
            "source_url": source_url,
            "backing_data_url": backing_data_url,
            "fetched_at": captured_at,
            "raw_match_count": 0,
            "target_row_count": 0,
            "jc_flagged_row_count": 0,
            "accepted_fixture_count": 0,
            "duplicate_nowscore_id_count": 0,
            "ambiguous_nowscore_id_count": 0,
            "diagnostics": {"invalid_expected_date": 1},
            "fixtures": [],
        }

    raw_rows = _raw_schedule_rows(schedule_text)
    normalized, diagnostics = _parse_schedule_js(
        schedule_text.lstrip("\ufeff"), expected_date=expected
    )
    normalized_by_id: dict[int, list[dict]] = {}
    for row in normalized:
        normalized_by_id.setdefault(int(row["nowscore_id"]), []).append(row)

    target_raw_by_id: dict[int, list[tuple[int, list[object]]]] = {}
    target_rows: list[tuple[int, list[object], list[dict]]] = []
    for array_index, values in raw_rows:
        if len(values) < 12:
            continue
        match_id = _integer(values[0])
        if match_id is None:
            continue
        parsed_rows = normalized_by_id.get(match_id, [])
        if not parsed_rows:
            continue
        target_raw_by_id.setdefault(match_id, []).append((array_index, values))
        target_rows.append((array_index, values, parsed_rows))

    duplicate_count = sum(
        max(0, len(rows_for_id) - 1)
        for rows_for_id in target_raw_by_id.values()
    )
    ambiguous_count = sum(
        1
        for match_id in target_raw_by_id
        if len({
            (
                row.get("home_team"), row.get("home_team_en"),
                row.get("away_team"), row.get("away_team_en"),
                row.get("kickoff_local"),
            )
            for row in normalized_by_id.get(match_id, [])
        }) > 1
    )

    fixtures_by_id: dict[int, dict] = {}
    jc_flagged_count = 0
    for array_index, values, parsed_rows in target_rows:
        if len(values) <= 32 or values[32] != 1:
            continue
        jc_flagged_count += 1
        if len(parsed_rows) != 1:
            continue
        parsed = parsed_rows[0]
        match_id = int(parsed["nowscore_id"])
        if match_id in fixtures_by_id:
            continue
        fixtures_by_id[match_id] = {
            "nowscore_id": match_id,
            "home_team_id": parsed.get("home_team_id"),
            "away_team_id": parsed.get("away_team_id"),
            "home_team": parsed.get("home_team"),
            "away_team": parsed.get("away_team"),
            "home_team_en": parsed.get("home_team_en"),
            "away_team_en": parsed.get("away_team_en"),
            "kickoff_local": parsed.get("kickoff_local"),
            "match_number": None,
            "match_number_source": "not_present_in_schedule_row",
            "schedule_source_date": parsed.get("schedule_source_date"),
            "schedule_source_date_format": parsed.get("schedule_source_date_format"),
            "business_date": expected.isoformat(),
            "date_provenance": {
                "source_date_value": values[11],
                "source_date_format": parsed.get("schedule_source_date_format"),
                "expected_business_date": expected.isoformat(),
                "rule": "source date equals supplied business date; year is never inferred",
            },
            "jc_membership": "VERIFIED",
            "jc_membership_source": "nowscore_public_jc",
            "jc_membership_evidence": {
                "filter_function": "SetLevel(3)",
                "row_index": 32,
                "raw_value": values[32],
                "source_surface": source_url,
                "backing_data_url": backing_data_url,
                "array_index": array_index,
            },
            "source_surface": source_url,
            "source_url": backing_data_url,
            "fetched_at": captured_at,
        }

    accepted = list(fixtures_by_id.values())
    status = "PASS" if contract.get("valid") else "FAIL"
    if duplicate_count or ambiguous_count:
        status = "FAIL"
        accepted = []
    return {
        "status": status,
        "contract": contract,
        "expected_business_date": expected.isoformat(),
        "source_url": source_url,
        "backing_data_url": backing_data_url,
        "fetched_at": captured_at,
        "raw_match_count": len(raw_rows),
        "target_row_count": len(target_rows),
        "jc_flagged_row_count": jc_flagged_count,
        "accepted_fixture_count": len(accepted),
        "duplicate_nowscore_id_count": duplicate_count,
        "ambiguous_nowscore_id_count": ambiguous_count,
        "diagnostics": diagnostics,
        "fixtures": accepted,
    }


def parse_schedule_js(text: str, expected_date: object = None) -> list[dict]:
    """Parse bf1/full-date rows or an scN MM-DD surface with a fixed date.

    An MM-DD row is deliberately ignored unless ``expected_date`` supplies its
    year.  A supplied expected date is also used as a strict source-date gate.
    """
    matches, _ = _parse_schedule_js(text, expected_date)
    return matches


def _parse_kickoff(value: object) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(
            str(value).strip().replace("Z", "+00:00").replace("/", "-")
        )
    except ValueError:
        return None
    return parsed.replace(tzinfo=SHANGHAI) if parsed.tzinfo is None else parsed.astimezone(SHANGHAI)


def _resolve_match_strict(
    home: str,
    away: str,
    kickoff: object,
    schedule: list[dict],
    maximum_kickoff_difference_minutes: int,
    bound_id: int | None,
) -> dict:
    target_time = _parse_kickoff(kickoff)
    candidates = []
    for match in schedule:
        home_rows = [team_similarity(home, match.get("home_team", "")), team_similarity(home, match.get("home_team_en", ""))]
        away_rows = [team_similarity(away, match.get("away_team", "")), team_similarity(away, match.get("away_team_en", ""))]
        home_score, home_basis = max(home_rows, key=lambda row: row[0])
        away_score, away_basis = max(away_rows, key=lambda row: row[0])
        provider_time = _parse_kickoff(match.get("kickoff_local"))
        difference = (
            abs((provider_time - target_time).total_seconds()) / 60
            if provider_time and target_time else None
        )
        if bound_id and int(match.get("nowscore_id") or 0) == bound_id:
            home_score = away_score = 1.0
            home_basis = away_basis = "stored_verified_binding"
        if home_score < 0.75 or away_score < 0.75:
            continue
        if difference is not None and difference > maximum_kickoff_difference_minutes:
            continue
        time_score = 1.0 if difference is None else max(0.0, 1.0 - difference / maximum_kickoff_difference_minutes)
        confidence = 0.4 * home_score + 0.4 * away_score + 0.2 * time_score
        candidates.append({
            **match,
            "home_match_score": home_score,
            "away_match_score": away_score,
            "home_match_basis": home_basis,
            "away_match_basis": away_basis,
            "kickoff_difference_minutes": difference,
            "match_confidence": round(confidence, 6),
        })
    candidates.sort(key=lambda row: (row["match_confidence"], -(row["kickoff_difference_minutes"] or 0)), reverse=True)
    if not candidates:
        return {"status": "NO_EXACT_MATCH", "home": home, "away": away, "kickoff": str(kickoff or "")}
    best = candidates[0]
    if best["match_confidence"] < 0.82:
        return {"status": "LOW_CONFIDENCE_MATCH", "candidates": candidates[:5]}
    if len(candidates) > 1 and best["match_confidence"] - candidates[1]["match_confidence"] < 0.05:
        return {"status": "AMBIGUOUS_MATCH", "candidates": candidates[:5]}
    return {"status": "EXACT_MATCH", **best}


def _identity_resolver():
    global _IDENTITY_RESOLVER
    if _IDENTITY_RESOLVER is None:
        from football_data.identity_registry import (
            DEFAULT_IDENTITY_REGISTRY_PATH,
            IdentityRegistryResolver,
        )

        _IDENTITY_RESOLVER = IdentityRegistryResolver(DEFAULT_IDENTITY_REGISTRY_PATH)
    return _IDENTITY_RESOLVER


def _first_fixture_value(fixture: Mapping[str, object] | None, *keys: str) -> str:
    if not fixture:
        return ""
    for key in keys:
        value = fixture.get(key)
        if value not in (None, ""):
            return str(value).strip()
    return ""


def _fallback_competition_id(
    fixture: Mapping[str, object] | None,
    competition_id: str | None,
) -> str | None:
    for value in (
        competition_id,
        _first_fixture_value(fixture, "competition_id", "canonical_competition_id"),
    ):
        text = str(value or "").strip()
        if text.startswith("competition:"):
            return text
    raw_name = _first_fixture_value(fixture, "competition", "league")
    if not raw_name:
        return None
    from football_data.competition_demand import resolve_project_competition

    resolved = resolve_project_competition(raw_name)
    if resolved.get("resolution_status") != "resolved":
        return None
    value = str(resolved.get("canonical_competition_id") or "").strip()
    return value if value.startswith("competition:") else None


def _identity_contains(resolution: Mapping[str, object], canonical_team_id: str) -> bool:
    status = str(resolution.get("resolution_status") or "")
    if status == "AUTO_RESOLVED":
        return resolution.get("canonical_team_id") == canonical_team_id
    if status == "AMBIGUOUS":
        return canonical_team_id in set(resolution.get("candidate_team_ids") or [])
    return False


def _resolve_match_identity_fallback(
    home: str,
    away: str,
    kickoff: object,
    schedule: list[dict],
    *,
    fixture: Mapping[str, object] | None,
    competition_id: str | None,
    identity_resolver=None,
) -> dict:
    target_time = _parse_kickoff(kickoff)
    exact = [
        candidate
        for candidate in schedule
        if target_time is not None
        and _parse_kickoff(candidate.get("kickoff_local")) == target_time
    ]
    resolved_competition_id = _fallback_competition_id(fixture, competition_id)
    details = {
        "competition_id": resolved_competition_id,
        "exact_kickoff_candidate_count": len(exact),
        "confirmed_sides": [],
        "identity_filtered_candidate_ids": [],
        "orientation_conflicts": [],
    }
    if not resolved_competition_id:
        return {"status": "NO_COMPETITION_CONTEXT", "identity_fallback": details}

    resolver = identity_resolver or _identity_resolver()
    target_names = {"home": home, "away": away}
    target_resolutions = {}
    for side in ("home", "away"):
        target_resolutions[side] = resolver.resolve_side(
            competition_id=resolved_competition_id,
            provider="500",
            provider_team_id=_first_fixture_value(
                fixture,
                f"{side}_provider_team_id",
                f"{side}ProviderTeamId",
            ) or None,
            provider_team_name=target_names[side],
            fixture_canonical_team_id=_first_fixture_value(
                fixture,
                f"{side}_canonical_team_id",
                f"{side}CanonicalTeamId",
            ) or None,
        )
        resolution = target_resolutions[side]
        if (
            resolution.get("resolution_status") == "AUTO_RESOLVED"
            and resolution.get("canonical_team_id")
        ):
            details["confirmed_sides"].append({
                "side": side,
                "canonical_team_id": resolution["canonical_team_id"],
                "resolution_method": resolution.get("resolution_method"),
                "evidence": list(resolution.get("evidence") or []),
            })

    if not details["confirmed_sides"]:
        return {"status": "NO_CONFIRMED_SIDE", "identity_fallback": details}

    filtered: dict[int, dict] = {}
    for candidate in exact:
        provider_resolutions = {
            side: resolver.resolve_side(
                competition_id=resolved_competition_id,
                provider="nowscore",
                provider_team_id=str(candidate.get(f"{side}_team_id") or "") or None,
                provider_team_name=(
                    candidate.get(f"{side}_team_en")
                    or candidate.get(f"{side}_team")
                    or ""
                ),
            )
            for side in ("home", "away")
        }
        matched_sides = []
        for confirmed in details["confirmed_sides"]:
            side = str(confirmed["side"])
            canonical_team_id = str(confirmed["canonical_team_id"])
            same_side = provider_resolutions[side]
            opposite_side = provider_resolutions["away" if side == "home" else "home"]
            if (
                same_side.get("resolution_status") == "AUTO_RESOLVED"
                and same_side.get("canonical_team_id") == canonical_team_id
            ):
                matched_sides.append(confirmed)
            if _identity_contains(opposite_side, canonical_team_id):
                details["orientation_conflicts"].append({
                    "nowscore_id": candidate.get("nowscore_id"),
                    "confirmed_side": side,
                    "canonical_team_id": canonical_team_id,
                })
        provider_match_id = candidate.get("nowscore_id")
        if matched_sides and str(provider_match_id or "").isdigit():
            filtered.setdefault(int(provider_match_id), {
                "candidate": candidate,
                "matched_sides": matched_sides,
            })

    details["identity_filtered_candidate_ids"] = sorted(filtered)
    if details["orientation_conflicts"]:
        return {"status": "ORIENTATION_CONFLICT", "identity_fallback": details}
    if len(filtered) > 1:
        return {"status": "AMBIGUOUS_MATCH", "identity_fallback": details}
    if not filtered:
        return {"status": "NO_UNIQUE_PROVIDER_CANDIDATE", "identity_fallback": details}

    provider_match_id, selected = next(iter(filtered.items()))
    candidate = selected["candidate"]
    confirmed_sides = {str(item["side"]) for item in selected["matched_sides"]}
    match_scores = {}
    for side, name in (("home", home), ("away", away)):
        score, basis = max(
            [
                team_similarity(name, candidate.get(f"{side}_team", "")),
                team_similarity(name, candidate.get(f"{side}_team_en", "")),
            ],
            key=lambda row: row[0],
        )
        match_scores[f"{side}_match_score"] = score
        match_scores[f"{side}_match_basis"] = (
            "deterministic_identity_fallback" if side in confirmed_sides else basis
        )
    return {
        "status": "EXACT_MATCH",
        **candidate,
        **match_scores,
        "kickoff_difference_minutes": 0.0,
        "match_confidence": 1.0,
        "resolution_method": "deterministic_identity_fallback",
        "identity_fallback": details,
        "nowscore_id": provider_match_id,
    }


def resolve_match(
    home: str,
    away: str,
    kickoff: object,
    schedule: list[dict],
    maximum_kickoff_difference_minutes: int = 180,
    *,
    fixture: Mapping[str, object] | None = None,
    competition_id: str | None = None,
    identity_resolver=None,
) -> dict:
    target = {"home": home, "away": away, "kickoff": str(kickoff or "")}
    binding = lookup_provider_binding(target, "nowscore")
    bound_id = int(binding["id"]) if binding and str(binding.get("id") or "").isdigit() else None
    strict = _resolve_match_strict(
        home,
        away,
        kickoff,
        schedule,
        maximum_kickoff_difference_minutes,
        bound_id,
    )
    if strict.get("status") == "EXACT_MATCH" or bound_id is not None:
        return strict
    fallback = _resolve_match_identity_fallback(
        home,
        away,
        kickoff,
        schedule,
        fixture=fixture,
        competition_id=competition_id,
        identity_resolver=identity_resolver,
    )
    if fallback.get("status") == "EXACT_MATCH":
        return fallback
    return {
        **strict,
        "fallback_status": fallback.get("status"),
        "identity_fallback": fallback.get("identity_fallback", {}),
    }


def _normalise_required_dates(required_dates: Iterable[object] | object | None) -> tuple[list[date], list[str]]:
    if required_dates is None:
        values: list[object] = []
    elif isinstance(required_dates, (str, date, datetime)):
        values = [required_dates]
    else:
        values = list(required_dates)  # type: ignore[arg-type]

    dates: set[date] = set()
    invalid: list[str] = []
    for value in values:
        parsed = _normalise_expected_date(value)
        if parsed is None:
            invalid.append(str(value))
        else:
            dates.add(parsed)
    return sorted(dates), invalid


def _now_shanghai_date(now: object = None) -> date:
    if now is None:
        return datetime.now(SHANGHAI).date()
    parsed = _normalise_expected_date(now)
    if parsed is None:
        raise ValueError(f"invalid now: {now}")
    if isinstance(now, datetime) and now.tzinfo is not None:
        return now.astimezone(SHANGHAI).date()
    return parsed


def _dedupe_schedule_rows(rows: Iterable[dict]) -> tuple[list[dict], int]:
    merged: list[dict] = []
    seen: set[int] = set()
    duplicate_count = 0
    for row in rows:
        match_id = _integer(row.get("nowscore_id"))
        if match_id is None:
            continue
        if match_id in seen:
            duplicate_count += 1
            continue
        seen.add(match_id)
        merged.append(row)
    return merged, duplicate_count


def fetch_schedule_bundle(
    required_dates: Iterable[object] | object | None = None,
    *,
    now: object = None,
) -> dict:
    """Fetch bf1 plus only the required, bounded scN future surfaces.

    ``bf1`` remains the live fallback.  An scN error is retained in the
    returned provenance and never causes a guessed fixture to enter the union.
    """
    today = _now_shanghai_date(now)
    required, invalid_required = _normalise_required_dates(required_dates)
    source_rows: list[dict] = []
    sources: list[dict] = []
    errors: list[dict] = []

    bf1_url = f"{SCHEDULE_URL}?_={int(time.time())}"
    try:
        raw = _fetch_bytes(bf1_url)
        parsed, diagnostics = _parse_schedule_js(_decode(raw))
        source_rows.extend(parsed)
        sources.append({
            "surface": "bf1",
            "url": SCHEDULE_URL,
            "status": "OK",
            "raw_match_count": len(parsed) + sum(diagnostics.values()),
            "parsed_match_count": len(parsed),
            "diagnostics": diagnostics,
        })
        bf1_ok = True
    except Exception as error:
        detail = f"{type(error).__name__}: {error}"
        source = {"surface": "bf1", "url": SCHEDULE_URL, "status": "FETCH_ERROR", "error": detail}
        sources.append(source)
        errors.append(source)
        bf1_ok = False

    future_sources: list[dict] = []
    future_errors: list[dict] = []
    for invalid in invalid_required:
        source = {
            "surface": "future_schedule",
            "status": "REJECTED",
            "error": "INVALID_REQUIRED_DATE",
            "requested_date": invalid,
        }
        future_sources.append(source)
        future_errors.append(source)

    for expected in required:
        offset = (expected - today).days
        if offset < 1:
            future_sources.append({
                "surface": "future_schedule",
                "status": "NOT_NEEDED",
                "expected_date": expected.isoformat(),
                "offset": offset,
            })
            continue
        if offset > MAX_FUTURE_SCHEDULE_OFFSET:
            source = {
                "surface": "future_schedule",
                "status": "SKIPPED",
                "expected_date": expected.isoformat(),
                "offset": offset,
                "error": "FUTURE_OFFSET_OUT_OF_RANGE",
            }
            future_sources.append(source)
            future_errors.append(source)
            continue

        surface = f"sc{offset}"
        # The browser surface uses a numeric millisecond cache buster.  Keep
        # it second-aligned to avoid provider/proxy rejection of rapid random
        # query variants while still preventing a stale cached response.
        url = f"{FUTURE_SCHEDULE_URL.format(offset=offset)}?{int(time.time()) * 1000}"
        try:
            raw = _fetch_bytes(url)
            parsed, diagnostics = _parse_schedule_js(
                _decode(raw), expected_date=expected
            )
            source = {
                "surface": surface,
                "url": FUTURE_SCHEDULE_URL.format(offset=offset),
                "status": "OK" if parsed else "REJECTED",
                "expected_date": expected.isoformat(),
                "offset": offset,
                "raw_match_count": len(parsed) + sum(diagnostics.values()),
                "parsed_match_count": len(parsed),
                "diagnostics": diagnostics,
            }
            if not parsed:
                source["error"] = "NO_MATCHING_ROWS_FOR_EXPECTED_DATE"
                future_errors.append(source)
            future_sources.append(source)
            source_rows.extend(parsed)
        except Exception as error:
            source = {
                "surface": surface,
                "url": FUTURE_SCHEDULE_URL.format(offset=offset),
                "status": "FETCH_ERROR",
                "expected_date": expected.isoformat(),
                "offset": offset,
                "error": f"{type(error).__name__}: {error}",
            }
            future_sources.append(source)
            future_errors.append(source)

    matches, duplicate_count = _dedupe_schedule_rows(source_rows)
    if not bf1_ok:
        status = "FETCH_ERROR"
    elif future_errors:
        status = "DEGRADED"
    else:
        status = "OK"
    future_surface = {
        "today": today.isoformat(),
        "required_dates": [value.isoformat() for value in required],
        "sources": future_sources,
        "errors": future_errors,
    }
    return {
        "status": status,
        "matches": matches,
        "schedule_count": len(matches),
        "raw_schedule_count": len(source_rows),
        "duplicate_nowscore_id_count": duplicate_count,
        "sources": sources,
        "errors": errors + future_errors,
        "bf1": sources[0] if sources else {},
        "future_surface": future_surface,
        "provenance": {"bf1": sources[0] if sources else {}, "future_surface": future_surface},
    }


def fetch_schedule(
    required_dates: Iterable[object] | object | None = None,
    *,
    now: object = None,
) -> list[dict]:
    """Backward-compatible schedule list API backed by the bounded bundle."""
    return fetch_schedule_bundle(required_dates, now=now)["matches"]


def fetch_nowscore_jc_schedule(
    business_date: object,
    *,
    now: object = None,
) -> dict:
    """Fetch one Nowscore public JC sales-day group.

    The direct JC sales page is the authoritative current-universe source for
    membership, business date, match number, identity, and kickoff.  The
    live ``ft1/scN`` page/data surfaces are best-effort corroboration only:
    their absence never removes a direct sales-page fixture.
    """
    expected = _normalise_expected_date(business_date)
    fetched_at = datetime.now(SHANGHAI).isoformat(timespec="seconds")
    business_page_url = ""
    if expected is None:
        return {
            "source": "nowscore_public_jc",
            "success": False,
            "status": "INVALID_BUSINESS_DATE",
            "date": str(business_date or ""),
            "fetch_time": fetched_at,
            "fetched_at": fetched_at,
            "matches": [],
        }

    today = _now_shanghai_date(now)
    business_page_url = JC_BUSINESS_PAGE_URL.format(
        business_date=expected.isoformat()
    )
    base_result = {
        "source": "nowscore_public_jc",
        "primary_source": "nowscore_public_jc_sales",
        "schedule_scope": "jc",
        "date": expected.isoformat(),
        "business_date": expected.isoformat(),
        "fetch_time": fetched_at,
        "fetched_at": fetched_at,
        "url": business_page_url,
        "source_surface": business_page_url,
        "business_date_source": "nowscore_public_jc_sales",
        "business_date_source_url": business_page_url,
        "surface": "nowscore_public_jc_sales",
    }
    try:
        business_page_text = _decode(_fetch_bytes(business_page_url))
        business_page = parse_nowscore_jc_business_page(
            business_page_text,
            business_date=expected,
        )
        if business_page.get("status") != "PASS":
            page_status = str(business_page.get("status") or "")
            status = (
                NOT_YET_PUBLISHED
                if page_status == NOT_YET_PUBLISHED
                else "BUSINESS_DATE_CONTRACT_REJECTED"
            )
            return {
                **base_result,
                "success": False,
                "status": status,
                "publication_status": (
                    NOT_YET_PUBLISHED if status == NOT_YET_PUBLISHED else None
                ),
                "matches": [],
                "business_date_contract": business_page.get("contract"),
                "jc_contract": business_page.get("contract"),
                "business_date_candidate_row_count": business_page.get(
                    "row_count", 0
                ),
                "duplicate_nowscore_id_count": business_page.get(
                    "duplicate_nowscore_id_count", 0
                ),
                "duplicate_sales_row_id_count": business_page.get(
                    "duplicate_sales_row_id_count", 0
                ),
                "duplicate_match_number_count": business_page.get(
                    "duplicate_match_number_count", 0
                ),
                "ambiguous_nowscore_id_count": business_page.get(
                    "ambiguous_row_count", 0
                ),
                "diagnostics": {
                    "business_date_page_status": business_page.get("status"),
                },
            }

        candidate_rows = list(business_page.get("fixtures") or [])
        candidate_ids = {
            int(candidate["nowscore_id"])
            for candidate in candidate_rows
            if candidate.get("nowscore_id") is not None
        }
        calendar_dates_by_surface: dict[str, set[date]] = {}
        optional_surface_skips: list[dict] = []
        for candidate in candidate_rows:
            calendar_date = _normalise_expected_date(
                str(candidate.get("kickoff") or "")[:10]
            )
            if calendar_date is None:
                optional_surface_skips.append({
                    "nowscore_id": candidate.get("nowscore_id"),
                    "status": "SKIPPED",
                    "error": "INVALID_DIRECT_KICKOFF",
                })
                continue
            offset = (calendar_date - today).days
            if offset == 0:
                surface = "ft1"
            elif 1 <= offset <= MAX_FUTURE_SCHEDULE_OFFSET:
                surface = f"sc{offset}"
            else:
                optional_surface_skips.append({
                    "nowscore_id": candidate.get("nowscore_id"),
                    "calendar_date": calendar_date.isoformat(),
                    "offset": offset,
                    "status": "SKIPPED",
                    "error": "OPTIONAL_CORROBORATION_OUTSIDE_BOUNDED_SURFACE",
                })
                continue
            calendar_dates_by_surface.setdefault(surface, set()).add(calendar_date)

        a32_by_id: dict[int, list[dict]] = {}
        optional_surfaces: dict[str, dict] = {}
        optional_flagged_count = 0
        optional_duplicate_count = 0
        optional_ambiguous_count = 0
        for surface, calendar_dates in sorted(calendar_dates_by_surface.items()):
            source_url = JC_SCHEDULE_PAGE_URL.format(surface=surface)
            data_base_url = JC_SCHEDULE_DATA_URL.format(
                filename=f"{surface}.js"
            )
            surface_record: dict[str, object] = {
                "surface": surface,
                "source_url": source_url,
                "backing_data_url": data_base_url,
                "calendar_dates": sorted(
                    value.isoformat() for value in calendar_dates
                ),
                "status": "FETCH_ERROR",
                "parsed": [],
            }
            try:
                page_text = _decode(_fetch_bytes(source_url))
                contract = _public_jc_page_contract(page_text, surface)
                if contract.get("filename2") != f"{surface}.js":
                    raise ValueError("PAGE_BACKING_FILENAME_MISMATCH")
                data_url = f"{data_base_url}?{int(time.time()) * 1000}"
                schedule_text = _decode(_fetch_bytes(data_url))
                surface_record["contract"] = contract
                surface_record["data_url"] = data_url
                surface_record["status"] = "OK" if contract.get("valid") else "REJECTED"
                for calendar_date in sorted(calendar_dates):
                    parsed = parse_nowscore_jc_surface(
                        page_text,
                        schedule_text,
                        expected_date=calendar_date,
                        source_url=source_url,
                        backing_data_url=data_base_url,
                        fetched_at=fetched_at,
                        surface=surface,
                    )
                    surface_record["parsed"].append({
                        "calendar_date": calendar_date.isoformat(),
                        "status": parsed.get("status"),
                        "target_row_count": parsed.get("target_row_count", 0),
                        "jc_flagged_row_count": parsed.get(
                            "jc_flagged_row_count", 0
                        ),
                        "duplicate_nowscore_id_count": parsed.get(
                            "duplicate_nowscore_id_count", 0
                        ),
                        "ambiguous_nowscore_id_count": parsed.get(
                            "ambiguous_nowscore_id_count", 0
                        ),
                    })
                    optional_flagged_count += int(
                        parsed.get("jc_flagged_row_count", 0)
                    )
                    optional_duplicate_count += int(
                        parsed.get("duplicate_nowscore_id_count", 0)
                    )
                    optional_ambiguous_count += int(
                        parsed.get("ambiguous_nowscore_id_count", 0)
                    )
                    if parsed.get("status") != "PASS":
                        continue
                    for corroboration in parsed.get("fixtures") or []:
                        match_id = corroboration.get("nowscore_id")
                        if match_id in candidate_ids:
                            a32_by_id.setdefault(int(match_id), []).append({
                                "filter_function": "SetLevel(3)",
                                "predicate": "A[j][32] == 1",
                                "row_index": 32,
                                "raw_value": corroboration.get(
                                    "jc_membership_evidence", {}
                                ).get("raw_value"),
                                "array_index": corroboration.get(
                                    "jc_membership_evidence", {}
                                ).get("array_index"),
                                "source_surface": source_url,
                                "backing_data_url": data_base_url,
                                "calendar_date": calendar_date.isoformat(),
                            })
            except Exception as error:
                surface_record["error"] = f"{type(error).__name__}: {error}"
            optional_surfaces[surface] = surface_record

        matches: list[dict] = []
        for candidate in candidate_rows:
            match_id = candidate.get("nowscore_id")
            kickoff_text = str(candidate.get("kickoff") or "")
            try:
                kickoff = datetime.strptime(
                    kickoff_text, "%Y-%m-%d %H:%M"
                ).replace(tzinfo=SHANGHAI)
            except ValueError:
                continue
            fixture = {
                "nowscore_id": int(match_id),
                "home_team": candidate.get("home_team"),
                "away_team": candidate.get("away_team"),
                "kickoff_local": kickoff.isoformat(timespec="seconds"),
                "business_date": expected.isoformat(),
                "business_date_source": "nowscore_public_jc_sales",
                "business_date_source_url": business_page_url,
                "match_number": candidate.get("match_number"),
                "match_number_source": "nowscore_public_jc_sales",
                "sales_row_id": candidate.get("sales_row_id"),
                "league": candidate.get("league"),
                "cansale": candidate.get("cansale"),
                "date_provenance": {
                    "source_date_value": kickoff_text,
                    "source_date_format": "full_datetime",
                    "schedule_calendar_date": kickoff_text[:10],
                    "business_date": expected.isoformat(),
                    "expected_business_date": expected.isoformat(),
                    "business_date_source": "nowscore_public_jc_sales",
                    "business_date_source_url": business_page_url,
                    "business_date_anchor": (
                        business_page.get("contract") or {}
                    ).get("date_anchor"),
                    "sales_window": (
                        business_page.get("contract") or {}
                    ).get("sales_window"),
                    "match_number": candidate.get("match_number"),
                    "sales_row_id": candidate.get("sales_row_id"),
                    "rule": (
                        "business date is copied from the selected Nowscore JC "
                        "sales-day group; kickoff calendar date is retained separately"
                    ),
                },
                "jc_membership": "VERIFIED",
                "jc_membership_source": "nowscore_public_jc_sales",
                "jc_membership_evidence": {
                    "source": "nowscore_public_jc_sales",
                    "source_surface": business_page_url,
                    "selected_date": (
                        business_page.get("contract") or {}
                    ).get("selected_date"),
                    "business_date": expected.isoformat(),
                    "group": candidate.get("match_number_group"),
                    "match_number": candidate.get("match_number"),
                    "sales_row_id": candidate.get("sales_row_id"),
                    "nowscore_id": int(match_id),
                    "sales_window": (
                        business_page.get("contract") or {}
                    ).get("sales_window"),
                },
                "source_surface": business_page_url,
                "source_url": business_page_url,
                "fetched_at": fetched_at,
            }
            corroborations = a32_by_id.get(int(match_id), [])
            if len(corroborations) == 1:
                fixture["a32_corroboration"] = corroborations[0]
            elif len(corroborations) > 1:
                fixture["a32_corroboration_status"] = "AMBIGUOUS_OPTIONAL"
            matches.append(fixture)

        direct_contract = business_page.get("contract")
        success = bool(
            business_page.get("status") == "PASS"
            and len(matches) == len(candidate_rows)
            and int(business_page.get("duplicate_nowscore_id_count", 0)) == 0
            and int(business_page.get("duplicate_sales_row_id_count", 0)) == 0
            and int(business_page.get("duplicate_match_number_count", 0)) == 0
            and int(business_page.get("ambiguous_row_count", 0)) == 0
        )
        return {
            **base_result,
            "success": success,
            "status": "OK" if success else "BUSINESS_DATE_CONTRACT_REJECTED",
            "matches": matches,
            "business_date_contract": direct_contract,
            "jc_contract": direct_contract,
            "business_date_candidate_row_count": len(candidate_rows),
            "target_row_count": len(candidate_rows),
            "jc_flagged_row_count": optional_flagged_count,
            "a32_corroborated_count": sum(
                1 for values in a32_by_id.values() if len(values) == 1
            ),
            "duplicate_nowscore_id_count": business_page.get(
                "duplicate_nowscore_id_count", 0
            ),
            "duplicate_sales_row_id_count": business_page.get(
                "duplicate_sales_row_id_count", 0
            ),
            "duplicate_match_number_count": business_page.get(
                "duplicate_match_number_count", 0
            ),
            "ambiguous_nowscore_id_count": business_page.get(
                "ambiguous_row_count", 0
            ),
            "diagnostics": {
                "business_date_page_status": business_page.get("status"),
                "optional_a32_corroboration": {
                    "filter_function": "SetLevel(3)",
                    "predicate": "A[j][32] == 1",
                    "surfaces": optional_surfaces,
                    "skipped": optional_surface_skips,
                    "flagged_row_count": optional_flagged_count,
                    "duplicate_nowscore_id_count": optional_duplicate_count,
                    "ambiguous_nowscore_id_count": optional_ambiguous_count,
                },
            },
        }
    except Exception as error:
        return {
            **base_result,
            "success": False,
            "status": "FETCH_ERROR",
            "matches": [],
            "error": f"{type(error).__name__}: {error}",
        }


def prebind_match(
    home: str,
    away: str,
    kickoff: object,
    schedule: list[dict],
    *,
    fixture: Mapping[str, object] | None = None,
    competition_id: str | None = None,
    identity_resolver=None,
) -> dict:
    resolved = resolve_match(
        home,
        away,
        kickoff,
        schedule,
        fixture=fixture,
        competition_id=competition_id,
        identity_resolver=identity_resolver,
    )
    if resolved.get("status") != "EXACT_MATCH":
        return resolved
    match = {"home": home, "away": away, "kickoff": str(kickoff or "")}
    record_binding(
        match, "nowscore", resolved["nowscore_id"], confidence=resolved["match_confidence"],
        verification=(
            "schedule_pair_time_identity_fallback"
            if resolved.get("resolution_method") == "deterministic_identity_fallback"
            else "schedule_pair_time"
        ), provider_home=resolved.get("home_team", ""),
        provider_away=resolved.get("away_team", ""), provider_kickoff=resolved.get("kickoff_local", ""),
    )
    return resolved


class _OddsTableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[dict] = []
        self.in_row = False
        self.in_cell = False
        self.cells: list[str] = []
        self.cell_text: list[str] = []
        self.company_id: int | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "tr" and "datatr" in str(attributes.get("class") or "").split():
            self.in_row, self.cells, self.company_id = True, [], None
        elif self.in_row and tag == "td":
            self.in_cell, self.cell_text = True, []
        elif self.in_row and tag == "a":
            found = re.search(r"companyid=(\d+)", str(attributes.get("href") or ""), re.I)
            if found and self.company_id is None:
                self.company_id = int(found.group(1))

    def handle_data(self, data: str) -> None:
        if self.in_cell:
            self.cell_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "td" and self.in_row and self.in_cell:
            self.cells.append(" ".join("".join(self.cell_text).split()))
            self.in_cell = False
        elif tag == "tr" and self.in_row:
            self.rows.append({"company_id": self.company_id, "cells": self.cells})
            self.in_row = False


class _TextTableParser(HTMLParser):
    """Collect visible table rows without depending on page-specific classes."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[str]] = []
        self.in_row = False
        self.in_cell = False
        self.cells: list[str] = []
        self.cell_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "tr":
            self.in_row, self.cells = True, []
        elif self.in_row and tag in ("td", "th"):
            self.in_cell, self.cell_text = True, []
        elif self.in_cell and tag == "br":
            self.cell_text.append(" ")

    def handle_data(self, data: str) -> None:
        if self.in_cell:
            self.cell_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in ("td", "th") and self.in_row and self.in_cell:
            self.cells.append(" ".join("".join(self.cell_text).split()))
            self.in_cell = False
        elif tag == "tr" and self.in_row:
            if any(self.cells):
                self.rows.append(self.cells)
            self.in_row = False


def _table_rows(text: str) -> list[list[str]]:
    parser = _TextTableParser()
    parser.feed(text)
    return parser.rows


def _number(value: object, minimum: float | None = None) -> float | None:
    try:
        number = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    if minimum is not None and number < minimum:
        return None
    return number


def handicap_number(value: object) -> float | None:
    text = str(value or "").strip().replace("球", "")
    if not text:
        return None
    numeric = _number(text)
    if numeric is not None:
        return numeric
    numeric_parts = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*/\s*(\d+(?:\.\d+)?)\s*", text)
    if numeric_parts:
        return (float(numeric_parts.group(1)) + float(numeric_parts.group(2))) / 2
    receiving = text.startswith("受")
    text = text.removeprefix("受")
    values = {
        "平手": 0.0, "平/半": 0.25, "半": 0.5, "半/一": 0.75,
        "一": 1.0, "一/球半": 1.25, "球半": 1.5, "球半/两": 1.75,
        "两": 2.0, "两/两球半": 2.25, "两球半": 2.5,
        "两球半/三": 2.75, "三": 3.0, "三/三球半": 3.25,
        "三球半": 3.5, "三球半/四": 3.75, "四": 4.0,
    }
    depth = values.get(text)
    if depth is None:
        return None
    return depth if receiving else -depth


def _page_provider_id_details(page_identity: Mapping[str, object] | None) -> dict[str, object]:
    """Classify the page's provider ID without turning parser gaps into mismatches."""

    identity = page_identity if isinstance(page_identity, Mapping) else {}
    missing = object()
    raw = identity.get("page_provider_id_raw", missing)
    if raw is missing:
        raw = identity.get("nowscore_id", missing)
    if raw is missing:
        raw = identity.get("page_provider_id")

    base = {
        "page_provider_id": None,
        "page_provider_id_availability_state": "UNAVAILABLE",
        "page_provider_id_reason": "PAGE_PROVIDER_ID_UNAVAILABLE",
        "page_provider_id_parse_state": "MISSING",
        "page_provider_id_raw": None if raw is missing else raw,
    }
    if raw is missing or raw is None or str(raw).strip() == "":
        return base
    try:
        parsed = int(str(raw).strip())
    except (TypeError, ValueError):
        return {**base, "page_provider_id_parse_state": "UNPARSEABLE"}
    if parsed <= 0:
        return {**base, "page_provider_id_parse_state": "ZERO"}
    return {
        "page_provider_id": parsed,
        "page_provider_id_availability_state": "AVAILABLE",
        "page_provider_id_reason": None,
        "page_provider_id_parse_state": "POSITIVE",
        "page_provider_id_raw": raw,
    }


def _identity(html: str) -> dict:
    def find(pattern: str) -> str | None:
        found = re.search(pattern, html, re.I | re.S)
        return html_lib.unescape(re.sub(r"<[^>]+>", "", found.group(1))).strip() if found else None

    def find_team_id(container_id: str) -> int | None:
        found = re.search(
            rf'<div[^>]+id=["\']{container_id}["\'][^>]*>.*?teamid=(\d+)',
            html,
            re.I | re.S,
        )
        return int(found.group(1)) if found else None

    provider_id_raw = find(r'id=["\']hide_scheduleId["\'][^>]*value=["\']([^"\']*)')
    provider_id = _page_provider_id_details({"page_provider_id_raw": provider_id_raw})
    return {
        "nowscore_id": int(provider_id["page_provider_id"] or 0),
        "nowscore_id_raw": provider_id_raw,
        **provider_id,
        "kickoff_local": find(r'id=["\']hide_matchTime["\'][^>]*value=["\']([^"\']+)'),
        "home_team": find(r'<div[^>]+id=["\']home["\'][^>]*>.*?<a[^>]+class=["\']name["\'][^>]*>(.*?)</a>'),
        "away_team": find(r'<div[^>]+id=["\']guest["\'][^>]*>.*?<a[^>]+class=["\']name["\'][^>]*>(.*?)</a>'),
        "home_team_id": find_team_id("home"),
        "away_team_id": find_team_id("guest"),
    }


def parse_three_in_one(html: str) -> dict:
    parser = _OddsTableParser()
    parser.feed(html)
    bookmakers, asian, totals = [], [], []
    for row in parser.rows:
        cells = row["cells"]
        if len(cells) < 19:
            continue
        provider_id = row.get("company_id")
        canonical_id, canonical_name = COMPANIES.get(provider_id, (provider_id, cells[0].replace("*", "").strip() or f"Nowscore-{provider_id}"))
        common = {"name": canonical_name, "cid": canonical_id, "source_company_id": provider_id, "source": "nowscore_3in1"}
        spf_open = {"home": _number(cells[7], 1.0), "draw": _number(cells[8], 1.0), "away": _number(cells[9], 1.0)}
        spf_current = {"home": _number(cells[10], 1.0), "draw": _number(cells[11], 1.0), "away": _number(cells[12], 1.0)}
        if any(value is not None for value in (*spf_open.values(), *spf_current.values())):
            bookmakers.append({**common, "spf_open": spf_open, "spf_current": spf_current})
        open_handicap, current_handicap = handicap_number(cells[2]), handicap_number(cells[5])
        if open_handicap is not None or current_handicap is not None:
            asian.append({
                **common,
                "open_handicap": open_handicap, "current_handicap": current_handicap,
                "open_water_home": _number(cells[1]), "open_water_away": _number(cells[3]),
                "current_water_home": _number(cells[4]), "current_water_away": _number(cells[6]),
            })
        open_total, current_total = _number(cells[14]), _number(cells[17])
        if open_total is not None or current_total is not None:
            totals.append({
                **common,
                "open_line": open_total, "current_line": current_total,
                "open_over_water": _number(cells[13]), "open_under_water": _number(cells[15]),
                "current_over_water": _number(cells[16]), "current_under_water": _number(cells[18]),
            })

    valid_current = [row["spf_current"] for row in bookmakers if all((row.get("spf_current") or {}).get(key) for key in ("home", "draw", "away"))]
    summary = {}
    if valid_current:
        summary["avg_spf_current"] = {
            key: round(sum(row[key] for row in valid_current) / len(valid_current), 4)
            for key in ("home", "draw", "away")
        }
    pinnacle_book = next((row for row in bookmakers if row.get("cid") == 1055), None)
    pinnacle_asian = next((row for row in asian if row.get("cid") == 1055), None)
    return {
        "identity": _identity(html),
        "ouzhi": {"bookmakers": bookmakers, "pinnacle": pinnacle_book, "summary": summary, "total": len(bookmakers), "source": "nowscore_3in1"},
        "yazhi": {"companies": asian, "pinnacle": pinnacle_asian, "total": len(asian), "source": "nowscore_3in1"},
        "daxiao": {"companies": totals, "total": len(totals), "source": "nowscore_3in1"},
    }


def _literal_array(text: str, name: str) -> list:
    """Read a JavaScript array that is also valid as a Python literal."""
    found = re.search(rf"(?:var\s+)?{re.escape(name)}\s*=\s*(\[.*?\]);", text, re.S)
    if not found:
        return []
    try:
        value = ast.literal_eval(found.group(1))
    except (SyntaxError, ValueError):
        return []
    return value if isinstance(value, list) else []


def _analysis_array(text: str, name: str) -> list[list[object]]:
    """Read one literal match-history array from Nowscore analysis JS."""
    return [row for row in _literal_array(text, name) if isinstance(row, list) and len(row) >= 10]


def _target_team_id(rows: list[list[object]]) -> int | None:
    ids: Counter[int] = Counter()
    for row in rows:
        for index in (4, 6):
            try:
                ids[int(row[index])] += 1
            except (TypeError, ValueError, IndexError):
                continue
    return ids.most_common(1)[0][0] if ids else None


def _form_summary(rows: list[list[object]], team_id: int, venue: str | None = None, limit: int = 10) -> dict:
    selected = []
    for row in rows:
        try:
            home_id, away_id = int(row[4]), int(row[6])
            home_goals, away_goals = int(row[8]), int(row[9])
        except (TypeError, ValueError, IndexError):
            continue
        is_home, is_away = home_id == team_id, away_id == team_id
        if not (is_home or is_away):
            continue
        if venue == "home" and not is_home:
            continue
        if venue == "away" and not is_away:
            continue
        selected.append((home_goals, away_goals) if is_home else (away_goals, home_goals))
        if len(selected) >= limit:
            break
    wins = sum(gf > ga for gf, ga in selected)
    draws = sum(gf == ga for gf, ga in selected)
    return {
        "matches": len(selected), "wins": wins, "draws": draws,
        "losses": len(selected) - wins - draws,
        "goals_for": sum(gf for gf, _ in selected),
        "goals_against": sum(ga for _, ga in selected),
    }


def _normalise_recent_match_date(source_date: str) -> str | None:
    if not re.fullmatch(r"\d{2}-\d{2}-\d{2}", source_date):
        return None
    try:
        datetime.strptime("20" + source_date, "%Y-%m-%d")
    except ValueError:
        return None
    return "20" + source_date


def _recent_match_row(row: list[object]) -> dict[str, object] | None:
    if len(row) < 10:
        return None
    try:
        home_team_id = int(row[4])
        away_team_id = int(row[6])
        home_goals = int(row[8])
        away_goals = int(row[9])
    except (TypeError, ValueError, IndexError):
        return None
    source_date = str(row[0])
    return {
        "source_date": source_date,
        "match_date": _normalise_recent_match_date(source_date),
        "home_team_id": home_team_id,
        "home_team_name": str(row[5]),
        "away_team_id": away_team_id,
        "away_team_name": str(row[7]),
        "home_goals": home_goals,
        "away_goals": away_goals,
    }


def _recent_matches(rows: list[list[object]]) -> list[dict[str, object]]:
    return [parsed for row in rows if (parsed := _recent_match_row(row)) is not None]


def _state_memory_match_row(row: list[object]) -> dict[str, object] | None:
    """Retain source-only identifiers beside the legacy recent-form row."""
    parsed = _recent_match_row(row)
    if parsed is None:
        return None
    value = dict(parsed)
    # Index 20 is retained only as a candidate.  The state-memory builder
    # promotes it after exact corroboration against the current panlu source
    # fixture record; a positional value is never trusted on its own.
    if len(row) > 20:
        source_fixture_id_candidate = _integer(row[20])
        if source_fixture_id_candidate is not None and source_fixture_id_candidate > 0:
            value["source_fixture_id_candidate"] = source_fixture_id_candidate
    # row[1] has no independently established field-level semantic in the
    # current source contract.  Do not persist it as a competition identifier.
    return value


def _state_memory_matches(rows: list[list[object]]) -> list[dict[str, object]]:
    return [
        parsed
        for row in rows
        if (parsed := _state_memory_match_row(row)) is not None
    ]


def parse_analysis_data(text: str) -> dict:
    """Build the recent-form contract consumed by the deterministic model."""
    home_rows, away_rows = _analysis_array(text, "h_data"), _analysis_array(text, "a_data")
    home_id, away_id = _target_team_id(home_rows), _target_team_id(away_rows)
    if home_id is None or away_id is None:
        return {}
    recent_form = {
        "home_overall": _form_summary(home_rows, home_id),
        "home_home": _form_summary(home_rows, home_id, "home"),
        "away_overall": _form_summary(away_rows, away_id),
        "away_away": _form_summary(away_rows, away_id, "away"),
    }
    if not all(item.get("matches") for item in recent_form.values()):
        return {}
    return {
        "recent_form": recent_form,
        "recent_matches": {
            "home_team": _recent_matches(home_rows),
            "away_team": _recent_matches(away_rows),
        },
        "state_memory_matches": {
            "home_team": _state_memory_matches(home_rows),
            "away_team": _state_memory_matches(away_rows),
        },
        "source_note": "Nowscore analysis recent results; actual goals, not xG",
        "team_ids": {"home": home_id, "away": away_id},
    }


def _profile_pairs(rows: list[list[str]]) -> list[dict]:
    profiles: list[dict] = []
    current: dict[str, str] = {}
    keys = {"姓名：": "name", "生日：": "birth_date", "国籍：": "nationality"}
    for row in rows:
        if len(row) < 2 or row[0] not in keys:
            continue
        key = keys[row[0]]
        if key == "name" and current:
            profiles.append(current)
            current = {}
        current[key] = row[1]
    if current:
        profiles.append(current)
    return profiles


def _coach_record(row: list[object]) -> dict | None:
    if len(row) < 12:
        return None
    try:
        return {
            "competition_or_team": str(row[4] or ""),
            "matches": int(row[5]), "wins": int(row[6]), "draws": int(row[7]),
            "losses": int(row[8]), "goals_for": int(row[9]), "goals_against": int(row[10]),
            "points_per_match": float(row[11]), "venue_flag": str(row[14] or "") if len(row) > 14 else "",
        }
    except (TypeError, ValueError):
        return None


def parse_coach_page(text: str) -> dict:
    profiles = _profile_pairs(_table_rows(text))
    result: dict[str, object] = {
        "home": profiles[0] if profiles else {},
        "away": profiles[1] if len(profiles) > 1 else {},
    }
    for side, prefix in (("home", "hc"), ("away", "gc")):
        coach_rows = [_coach_record(row) for row in _literal_array(text, f"{prefix}_data")]
        team_rows = [_coach_record(row) for row in _literal_array(text, f"{prefix}Team_data")]
        result[side]["coach_records"] = [row for row in coach_rows if row]
        result[side]["team_records"] = [row for row in team_rows if row]
    return result


def _result_triplet(value: str) -> dict:
    numbers = re.findall(r"(\d+)\s*[胜勝平负負]", value or "")
    return {
        "wins": int(numbers[0]) if len(numbers) > 0 else 0,
        "draws": int(numbers[1]) if len(numbers) > 1 else 0,
        "losses": int(numbers[2]) if len(numbers) > 2 else 0,
    }


def parse_referee_page(text: str) -> dict:
    rows = _table_rows(text)
    profiles = _profile_pairs(rows)
    summaries: list[dict] = []
    for index, row in enumerate(rows):
        if len(row) < 8 or row[0] not in ("所有赛事", "所有賽事", "瑞典超"):
            continue
        home = {
            "side": "home", **_result_triplet(row[3]),
            "avg_fouls": _number(row[4]), "avg_yellow": _number(row[5]),
            "avg_red": _number(row[6]), "win_rate": row[7],
        }
        away_row = rows[index + 1] if index + 1 < len(rows) else []
        away = {}
        if len(away_row) >= 6 and "客场" in away_row[0]:
            away = {
                "side": "away", **_result_triplet(away_row[1]),
                "avg_fouls": _number(away_row[2]), "avg_yellow": _number(away_row[3]),
                "avg_red": _number(away_row[4]), "win_rate": away_row[5] if len(away_row) > 5 else "",
            }
        summaries.append({"competition": row[0], "matches": int(row[1]), "home": home, "away": away})
    profile = profiles[0] if profiles else {}
    profile["summaries"] = summaries
    profile["home_team_history_count"] = len(_literal_array(text, "h_data"))
    profile["away_team_history_count"] = len(_literal_array(text, "a_data"))
    return profile


def parse_panlu_page(text: str, limit: int = 60) -> dict:
    matches: list[dict] = []
    for found in re.finditer(r"a\[\d+\]\s*=\s*(\[.*?\]);", text, re.S):
        try:
            row = ast.literal_eval(found.group(1))
        except (SyntaxError, ValueError):
            continue
        if not isinstance(row, list) or len(row) < 16:
            continue
        matches.append({
            "match_id": row[0], "competition": row[1], "kickoff": row[3],
            "home_team": row[4], "away_team": row[5], "home_team_id": row[6], "away_team_id": row[7],
            "full_time": {"home": row[8], "away": row[9]},
            "half_time": {"home": row[10], "away": row[11]},
            "asian_line": row[12], "total_line": row[15],
            "provider_flags": [row[13], row[14]],
        })
        if len(matches) >= limit:
            break
    return {"matches": matches, "count": len(matches)}


def _trend_timestamp(value: str, kickoff: object) -> str | None:
    match = re.search(r"(\d{2})-(\d{2})\s+(\d{2}):(\d{2})", value or "")
    base = _parse_kickoff(kickoff)
    if not match or not base:
        return None
    month, day, hour, minute = map(int, match.groups())
    try:
        parsed = datetime(base.year, month, day, hour, minute, tzinfo=SHANGHAI)
        if parsed > base.replace(hour=23, minute=59) and (parsed - base).days > 30:
            parsed = parsed.replace(year=base.year - 1)
        return parsed.isoformat(timespec="minutes")
    except ValueError:
        return None


def parse_company_trend(text: str, company_id: int, kickoff: object = None, company_name: str | None = None) -> dict:
    sections = {"asian": [], "total": [], "one_x_two": []}
    section: str | None = None
    for row in _table_rows(text):
        joined = "|".join(row)
        if len(row) >= 7 and "变化" in joined:
            if "和局" in joined:
                section = "one_x_two"
            elif "大" in row and "小" in row:
                section = "total"
            else:
                section = "asian"
            continue
        if not section or len(row) < 7 or not re.search(r"\d{2}-\d{2}\s+\d{2}:\d{2}", row[5]):
            continue
        common = {
            "timestamp_raw": row[5], "captured_at": _trend_timestamp(row[5], kickoff),
            "score": row[1], "status": row[6],
        }
        if section == "one_x_two":
            quote = {**common, "home": _number(row[2], 1.0), "draw": _number(row[3], 1.0), "away": _number(row[4], 1.0)}
        elif section == "total":
            quote = {**common, "over": _number(row[2]), "line": row[3], "line_number": handicap_number(row[3]), "under": _number(row[4])}
        else:
            quote = {**common, "home_water": _number(row[2]), "line": row[3], "line_number": handicap_number(row[3]), "away_water": _number(row[4])}
        sections[section].append(quote)
    count = sum(len(items) for items in sections.values())
    safe_name = str(company_name or "").strip()
    if len(safe_name) < 2 or safe_name.isdigit() or safe_name.startswith("Nowscore-"):
        safe_name = SOURCE_COMPANY_NAMES.get(company_id, "")
    if len(safe_name) < 2:
        safe_name = f"Nowscore-{company_id}"
    return {
        "source_company_id": company_id, "name": safe_name,
        "markets": sections, "snapshot_count": count,
    }


def _verified(
    target: dict,
    page_identity: dict,
    maximum_minutes: int = 180,
) -> tuple[bool, list[str]]:
    reasons = []
    home_score, _ = team_similarity(target.get("home", ""), page_identity.get("home_team", ""))
    away_score, _ = team_similarity(target.get("away", ""), page_identity.get("away_team", ""))
    if home_score < 0.75:
        reasons.append("HOME_TEAM_MISMATCH")
    if away_score < 0.75:
        reasons.append("AWAY_TEAM_MISMATCH")
    target_time, page_time = _parse_kickoff(target.get("kickoff")), _parse_kickoff(page_identity.get("kickoff_local"))
    if target_time and page_time and abs((target_time - page_time).total_seconds()) / 60 > maximum_minutes:
        reasons.append("KICKOFF_MISMATCH")
    return not reasons, reasons


def _fixture_team_name(fixture: Mapping[str, object], side: str) -> str:
    if side == "home":
        keys = ("homeTeam", "home_team", "home")
    else:
        keys = ("awayTeam", "away_team", "away")
    for key in keys:
        value = fixture.get(key)
        if value not in (None, ""):
            return str(value).strip()
    return ""


def _fixture_kickoff(fixture: Mapping[str, object]) -> str:
    for key in ("kickoff", "kickoff_local"):
        if fixture.get(key) not in (None, ""):
            return str(fixture[key])
    match_date = str(fixture.get("matchDate") or fixture.get("match_date") or "")[:10]
    match_time = str(fixture.get("matchTime") or fixture.get("match_time") or "")[:8]
    if len(match_time) == 5:
        match_time += ":00"
    return f"{match_date}T{match_time}+08:00" if match_date and match_time else ""


def _fixture_team_id(fixture: Mapping[str, object], side: str) -> int | None:
    keys = (
        ("home_team_id", "homeTeamId", "nowscore_home_team_id", "nowscoreHomeTeamId")
        if side == "home"
        else ("away_team_id", "awayTeamId", "nowscore_away_team_id", "nowscoreAwayTeamId")
    )
    for key in keys:
        value = fixture.get(key)
        if value in (None, "") or isinstance(value, bool):
            continue
        try:
            parsed = int(str(value).strip())
        except (TypeError, ValueError):
            continue
        if parsed > 0:
            return parsed
    return None


def _page_team_id(page_identity: Mapping[str, object], side: str) -> int | None:
    value = page_identity.get(f"{side}_team_id")
    if value in (None, "") or isinstance(value, bool):
        return None
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _trusted_jc_page_verification(
    target: Mapping[str, object],
    page_identity: Mapping[str, object],
    fixture: Mapping[str, object],
    explicit_id: int,
    maximum_minutes: int = 180,
) -> dict[str, object]:
    """Verify non-name identity facts before accepting a trusted JC ID."""

    reasons: list[str] = []
    page_provider_id = _page_provider_id_details(page_identity)
    non_blocking_reasons = []
    if page_provider_id["page_provider_id_availability_state"] == "UNAVAILABLE":
        non_blocking_reasons.append("PAGE_PROVIDER_ID_UNAVAILABLE")
    elif page_provider_id["page_provider_id"] != explicit_id:
        reasons.append("PROVIDER_ID_MISMATCH")
    page_id_corroborated = (
        page_provider_id["page_provider_id_availability_state"] == "AVAILABLE"
        and page_provider_id["page_provider_id"] == explicit_id
    )

    target_time = _parse_kickoff(target.get("kickoff"))
    fixture_time = _parse_kickoff(_fixture_kickoff(fixture))
    page_time = _parse_kickoff(page_identity.get("kickoff_local"))
    if (
        target_time is None
        or fixture_time is None
        or fixture_time != target_time
        or page_time is None
        or abs((target_time - page_time).total_seconds()) / 60 > maximum_minutes
    ):
        reasons.append("KICKOFF_MISMATCH")

    page_names = {
        side: str(page_identity.get(f"{side}_team") or "").strip()
        for side in ("home", "away")
    }
    if not page_names["home"] or not page_names["away"]:
        reasons.append("PROVIDER_TEAM_IDENTITY_MISSING")

    fixture_names = {
        side: _fixture_team_name(fixture, side)
        for side in ("home", "away")
    }
    if not fixture_names["home"] or not fixture_names["away"]:
        reasons.append("FIXTURE_TEAM_IDENTITY_MISSING")
    elif team_similarity(fixture_names["home"], fixture_names["away"])[0] >= 0.75:
        reasons.append("AMBIGUOUS_IDENTITY")
    target_names = {
        side: str(target.get(side) or "").strip()
        for side in ("home", "away")
    }
    target_scores = {
        side: team_similarity(target_names[side], fixture_names[side])[0]
        for side in ("home", "away")
    }
    target_reverse_scores = {
        "home": team_similarity(target_names["home"], fixture_names["away"])[0],
        "away": team_similarity(target_names["away"], fixture_names["home"])[0],
    }
    if not target_names["home"] or not target_names["away"]:
        reasons.append("TARGET_TEAM_IDENTITY_MISSING")
    elif all(score >= 0.75 for score in target_reverse_scores.values()) and all(
        score < 0.75 for score in target_scores.values()
    ):
        reasons.append("ORIENTATION_CONFLICT")
    elif any(score < 0.75 for score in target_scores.values()):
        reasons.append("TARGET_FIXTURE_IDENTITY_CONFLICT")
    fixture_ids = {
        side: _fixture_team_id(fixture, side)
        for side in ("home", "away")
    }
    page_ids = {
        side: _page_team_id(page_identity, side)
        for side in ("home", "away")
    }
    for side in ("home", "away"):
        if fixture_ids[side] is not None and page_ids[side] != fixture_ids[side]:
            reasons.append(f"{side.upper()}_TEAM_ID_MISMATCH")
    if (
        fixture_ids["home"] is not None
        and fixture_ids["away"] is not None
        and page_ids["home"] == fixture_ids["away"]
        and page_ids["away"] == fixture_ids["home"]
    ):
        reasons.append("ORIENTATION_CONFLICT")
    if (
        page_ids["home"] is not None
        and page_ids["away"] is not None
        and page_ids["home"] == page_ids["away"]
    ):
        reasons.append("AMBIGUOUS_IDENTITY")
    if clean_display_name(page_names["home"]).casefold() == clean_display_name(page_names["away"]).casefold():
        reasons.append("AMBIGUOUS_IDENTITY")

    same_scores = {
        side: team_similarity(fixture_names[side], page_names[side])[0]
        for side in ("home", "away")
    }
    reverse_scores = {
        "home": team_similarity(fixture_names["away"], page_names["home"])[0],
        "away": team_similarity(fixture_names["home"], page_names["away"])[0],
    }
    for side in ("home", "away"):
        if reverse_scores[side] >= 0.75 and same_scores[side] < 0.75:
            reasons.append("ORIENTATION_CONFLICT")
    return {
        "trusted": not reasons,
        "status": "TRUSTED_JC_SAME_PROVIDER" if not reasons else "TRUSTED_JC_REJECTED",
        "source": "nowscore_public_jc_sales",
        "nowscore_id": explicit_id,
        **page_provider_id,
        "page_provider_id_corroborated": page_id_corroborated,
        "display_name_mismatch": bool(
            same_scores["home"] < 0.75 or same_scores["away"] < 0.75
        ),
        "same_side_scores": same_scores,
        "reverse_side_scores": reverse_scores,
        "reasons": list(dict.fromkeys(reasons)),
        "non_blocking_reasons": list(dict.fromkeys(non_blocking_reasons)),
    }


def _fetch_cached_page(url: str, cache_path: Path, no_cache: bool, maximum_age: int = 3600) -> bytes:
    if not no_cache and cache_path.exists() and time.time() - cache_path.stat().st_mtime < maximum_age:
        return cache_path.read_bytes()
    raw = _fetch_bytes(url)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_bytes(raw)
    return raw


def fetch_context_bundle(match_id: int, kickoff: object, parsed_markets: dict, no_cache: bool = False) -> dict:
    """Fetch optional same-match context; individual failures never discard core odds."""
    raw_root = CACHE_ROOT / "raw"
    source_urls = {
        "coach": COACH_URL.format(match_id=match_id),
        "referee": REFEREE_URL.format(match_id=match_id),
        "panlu": PANLU_URL.format(match_id=match_id),
    }
    parsers = {"coach": parse_coach_page, "referee": parse_referee_page, "panlu": parse_panlu_page}
    context: dict[str, object] = {"source_urls": source_urls, "errors": {}}
    for key, url in source_urls.items():
        try:
            raw = _fetch_cached_page(url, raw_root / f"{match_id}_{key}.html", no_cache)
            context[key] = parsers[key](_decode(raw))
        except Exception as error:
            context[key] = {}
            context["errors"][key] = f"{type(error).__name__}: {error}"

    company_names: dict[int, str] = {}
    for market in ("ouzhi", "yazhi", "daxiao"):
        rows = (parsed_markets.get(market) or {}).get("bookmakers" if market == "ouzhi" else "companies") or []
        for row in rows:
            if row.get("source_company_id") is not None:
                company_names[int(row["source_company_id"])] = str(row.get("name") or "")

    def fetch_company(company_id: int) -> tuple[int, dict | None, str | None]:
        url = COMPANY_TREND_URL.format(company_id=company_id, match_id=match_id)
        try:
            raw = _fetch_cached_page(url, raw_root / f"{match_id}_company_{company_id}.html", no_cache, maximum_age=900)
            trend = parse_company_trend(_decode(raw), company_id, kickoff, company_names.get(company_id))
            trend["source_url"] = url
            return company_id, trend, None
        except Exception as error:
            return company_id, None, f"{type(error).__name__}: {error}"

    trends: list[dict] = []
    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = [executor.submit(fetch_company, company_id) for company_id in TREND_COMPANY_IDS]
        for future in as_completed(futures):
            company_id, trend, error = future.result()
            if trend and trend.get("snapshot_count"):
                trends.append(trend)
            if error:
                context["errors"][f"company_{company_id}"] = error
    trends.sort(key=lambda row: TREND_COMPANY_IDS.index(int(row["source_company_id"])))
    context["company_trends"] = trends
    context["quality"] = {
        "coach_available": bool((context.get("coach") or {}).get("home")),
        "referee_available": bool((context.get("referee") or {}).get("name")),
        "panlu_match_count": int((context.get("panlu") or {}).get("count") or 0),
        "trend_company_count": len(trends),
        "trend_snapshot_count": sum(int(row.get("snapshot_count") or 0) for row in trends),
    }
    return context


def _state_memory_target_identity(
    identity: Mapping[str, object],
    match_id: int,
    fixture: Mapping[str, object] | None,
) -> dict[str, object]:
    """Expose direct target identity for the research-only capture layer."""
    fixture = fixture or {}
    raw_competition = (
        fixture.get("raw_competition_label")
        or fixture.get("competition")
        or fixture.get("league")
    )
    return {
        "source_fixture_id": match_id,
        "provider_match_id": match_id,
        "home_team_id": identity.get("home_team_id"),
        "away_team_id": identity.get("away_team_id"),
        "home_team_name": identity.get("home_team"),
        "away_team_name": identity.get("away_team"),
        "kickoff_at": identity.get("kickoff_local"),
        "raw_competition_label": raw_competition,
        "source_record_ref": MARKET_URL.format(match_id=match_id),
    }


def fetch_match_markets(
    home: str,
    away: str,
    kickoff: object,
    explicit_id: int | None = None,
    no_cache: bool = False,
    *,
    fixture: Mapping[str, object] | None = None,
) -> dict:
    fetched_at = datetime.now(SHANGHAI).isoformat(timespec="seconds")
    try:
        schedule_raw = _fetch_bytes(f"{SCHEDULE_URL}?_={int(time.time())}")
        schedule_text = _decode(schedule_raw)
        schedule = parse_schedule_js(schedule_text)
    except Exception as error:
        schedule, schedule_text = [], ""
        schedule_error = f"{type(error).__name__}: {error}"
    else:
        schedule_error = None

    if explicit_id:
        resolved = {"status": "EXPLICIT_ID", "nowscore_id": int(explicit_id)}
    elif schedule_error:
        binding = lookup_provider_binding(
            {"home": home, "away": away, "kickoff": str(kickoff or "")},
            "nowscore",
        )
        bound_id = str((binding or {}).get("id") or "")
        resolved = (
            {"status": "STORED_VERIFIED_BINDING", "nowscore_id": int(bound_id)}
            if bound_id.isdigit()
            else {"status": "SCHEDULE_UNAVAILABLE", "schedule_error": schedule_error}
        )
    else:
        resolved = resolve_match(home, away, kickoff, schedule)
    if not resolved.get("nowscore_id"):
        return {
            "source": "nowscore_public_3in1", "status": resolved.get("status"),
            "fetched_at": fetched_at, "target": {"home": home, "away": away, "kickoff": str(kickoff or "")},
            "schedule_count": len(schedule), "schedule_error": schedule_error, "resolution": resolved,
        }

    match_id = int(resolved["nowscore_id"])
    cache_path = CACHE_ROOT / "raw" / f"{match_id}_3in1.html"
    raw = None
    if not no_cache and cache_path.exists() and time.time() - cache_path.stat().st_mtime < 3600:
        raw = cache_path.read_bytes()
    if raw is None:
        try:
            raw = _fetch_bytes(MARKET_URL.format(match_id=match_id))
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            return {
                "source": "nowscore_public_3in1", "status": "FETCH_ERROR", "fetched_at": fetched_at,
                "nowscore_id": match_id, "resolution": resolved, "error": f"{type(error).__name__}: {error}",
            }
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_bytes(raw)
    parsed = parse_three_in_one(_decode(raw))
    target = {"home": home, "away": away, "kickoff": kickoff}
    page_provider_id = _page_provider_id_details(parsed["identity"])
    verified, reasons = _verified(target, parsed["identity"])
    trusted_provenance = trusted_nowscore_jc_fixture(
        fixture,
        match_id,
    )
    if trusted_provenance.get("trusted"):
        binding = lookup_provider_binding(target, "nowscore")
        bound_id = str((binding or {}).get("id") or "")
        if bound_id and (not bound_id.isdigit() or int(bound_id) != match_id):
            trusted_provenance = {
                **trusted_provenance,
                "trusted": False,
                "reasons": [
                    *list(trusted_provenance.get("reasons") or []),
                    "PROVIDER_ID_MISMATCH",
                ],
            }
    identity_verification = None
    if trusted_provenance.get("trusted"):
        identity_verification = _trusted_jc_page_verification(
            target,
            parsed["identity"],
            fixture or {},
            match_id,
        )
        if identity_verification.get("trusted"):
            verified = True
            reasons = []
        else:
            reasons = list(dict.fromkeys([
                *reasons,
                *list(identity_verification.get("reasons") or []),
            ]))
    else:
        provenance_reasons = list(trusted_provenance.get("reasons") or []) if fixture is not None else []
        identity_verification = {
            "trusted": False,
            "status": "TRUSTED_JC_REJECTED" if fixture is not None else "ORDINARY_EXPLICIT_ID",
            "source": "nowscore_public_jc_sales",
            "nowscore_id": match_id,
            **page_provider_id,
            "page_provider_id_corroborated": None,
            "reasons": list(dict.fromkeys([*reasons, *provenance_reasons])),
            "non_blocking_reasons": (
                ["PAGE_PROVIDER_ID_UNAVAILABLE"]
                if page_provider_id["page_provider_id_availability_state"] == "UNAVAILABLE"
                else []
            ),
        }
        reasons = list(dict.fromkeys([*reasons, *provenance_reasons]))
    resolved = {
        **resolved,
        "identity_verification": identity_verification,
        "trusted_jc_provenance": trusted_provenance,
    }
    if not verified:
        return {
            "source": "nowscore_public_3in1", "status": "IDENTITY_MISMATCH", "fetched_at": fetched_at,
            "nowscore_id": match_id, "target": target, "page_identity": parsed["identity"],
            "identity_errors": reasons, "resolution": resolved,
            "identity_verification": identity_verification,
            "trusted_jc_provenance": trusted_provenance,
            **page_provider_id,
        }
    confidence = float((resolved or {}).get("match_confidence") or 1.0)
    record_binding(
        target, "nowscore", match_id, confidence=confidence,
        verification=(
            "market_page_identity_verified_trusted_jc"
            if identity_verification and identity_verification.get("trusted")
            else "market_page_identity_verified"
        ),
        provider_home=parsed["identity"].get("home_team", ""),
        provider_away=parsed["identity"].get("away_team", ""),
        provider_kickoff=parsed["identity"].get("kickoff_local", ""),
    )
    analysis_error = None
    shuju = {}
    analysis_cache = CACHE_ROOT / "raw" / f"{match_id}_analysis.js"
    analysis_raw = None
    if not no_cache and analysis_cache.exists() and time.time() - analysis_cache.stat().st_mtime < 3600:
        analysis_raw = analysis_cache.read_bytes()
    if analysis_raw is None:
        try:
            analysis_raw = _fetch_bytes(ANALYSIS_DATA_URL.format(match_id=match_id))
            analysis_cache.parent.mkdir(parents=True, exist_ok=True)
            analysis_cache.write_bytes(analysis_raw)
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            analysis_error = f"{type(error).__name__}: {error}"
    if analysis_raw is not None:
        shuju = parse_analysis_data(_decode(analysis_raw))
        if not shuju:
            analysis_error = "RECENT_FORM_PARSE_EMPTY"
    context = fetch_context_bundle(match_id, kickoff, parsed, no_cache=no_cache)
    return {
        "source": "nowscore_public_3in1", "status": "OK", "fetched_at": fetched_at,
        "nowscore_id": match_id, "target": target, "resolution": resolved,
        "identity": parsed["identity"], "source_url": MARKET_URL.format(match_id=match_id),
        "state_memory_identity": _state_memory_target_identity(
            parsed["identity"], match_id, fixture,
        ),
        "identity_verification": identity_verification,
        "trusted_jc_provenance": trusted_provenance,
        **page_provider_id,
        "ouzhi": parsed["ouzhi"], "yazhi": parsed["yazhi"], "daxiao": parsed["daxiao"],
        "shuju": shuju,
        "context": context,
        "analysis_source_url": ANALYSIS_DATA_URL.format(match_id=match_id),
        "analysis_error": analysis_error,
        "quality": {
            "home_away_kickoff_verified": True,
            "bookmaker_count": parsed["ouzhi"]["total"],
            "asian_count": parsed["yazhi"]["total"],
            "total_count": parsed["daxiao"]["total"],
            "recent_form_complete": bool((shuju.get("recent_form") or {})),
            **(context.get("quality") or {}),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", required=True)
    parser.add_argument("--away", required=True)
    parser.add_argument("--kickoff", required=True)
    parser.add_argument("--nowscore-id", type=int)
    parser.add_argument("--no-cache", action="store_true")
    parser.add_argument("--output")
    args = parser.parse_args()
    result = fetch_match_markets(args.home, args.away, args.kickoff, args.nowscore_id, args.no_cache)
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        path = Path(args.output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    print(text)
    return 0 if result.get("status") == "OK" else 1


if __name__ == "__main__":
    raise SystemExit(main())
