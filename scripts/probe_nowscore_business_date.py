#!/usr/bin/env python3
"""Replay Nowscore's public JC sales-day grouping contract.

This probe is intentionally independent of the production refresh path.  The
Nowscore direct JC sales page supplies the business-day anchor, membership,
match-number group, and fixture identity.  The live schedule page is only an
optional corroboration surface for the existing ``SetLevel(3)`` /
``A[j][32] == 1`` contract.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
from datetime import date, datetime, time as datetime_time, timedelta
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import quote
from zoneinfo import ZoneInfo

try:
    import nowscore_markets as nowscore
except ImportError:  # package imports used by tests
    from scripts import nowscore_markets as nowscore


REPO_ROOT = Path(__file__).resolve().parents[1]
SHANGHAI = ZoneInfo("Asia/Shanghai")
CP_BASE_URL = (
    "https://cp.nowscore.com/buy/jingcai.aspx"
    "?typeID=101&oddstype=2&date={business_date}"
)
LIVE_BASE_URL = "https://live.nowscore.com"
SCHEDULE_PAGE_URL = f"{LIVE_BASE_URL}/schedule.aspx?f={{surface}}"
SCHEDULE_DATA_URL = f"{LIVE_BASE_URL}/data/{{surface}}.js"
DEFAULT_DATES = ("2026-08-31", "2026-09-01")


def _now() -> str:
    return datetime.now(SHANGHAI).isoformat(timespec="seconds")


def _date(value: object) -> date | None:
    match = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", str(value or "").strip())
    if not match:
        return None
    try:
        return date(*(int(part) for part in match.groups()))
    except ValueError:
        return None


def _date_in_text(text: str) -> date | None:
    match = re.search(r"(20\d{2})\D{1,6}(\d{1,2})\D{1,6}(\d{1,2})", text)
    if not match:
        return None
    try:
        return date(*(int(part) for part in match.groups()))
    except ValueError:
        return None


def _normalise_date_value(value: object) -> str | None:
    parsed = _date(value)
    return parsed.isoformat() if parsed else None


class _JcPageParser(HTMLParser):
    """Collect the outer table rows used by the public Nowscore JC page."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tr_depth = 0
        self.current: dict[str, Any] | None = None
        self.cell_active = False
        self.cell_text: list[str] = []
        self.rows: list[dict[str, Any]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {key.lower(): value or "" for key, value in attrs}
        if tag.lower() == "tr":
            if self.tr_depth == 0:
                self.current = {
                    "attrs": attributes,
                    "cells": [],
                    "data": [],
                    "ids": [],
                    "titles": [],
                    "hrefs": [],
                    "onclicks": [],
                }
            self.tr_depth += 1
            return
        if self.current is None or self.tr_depth == 0:
            return
        self.current["data"].append("")
        if attributes.get("id"):
            self.current["ids"].append(attributes["id"])
        if attributes.get("title"):
            self.current["titles"].append(attributes["title"])
        if attributes.get("href"):
            self.current["hrefs"].append(attributes["href"])
        if attributes.get("onclick"):
            self.current["onclicks"].append(attributes["onclick"])
        if tag.lower() in {"td", "th"} and self.tr_depth == 1:
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


def _row_text(row: dict[str, Any]) -> str:
    return " ".join(str(value) for value in row.get("data") or [])


def _group_name(row: dict[str, Any]) -> str | None:
    attributes = row.get("attrs") or {}
    if attributes.get("id", "").startswith("ah_"):
        return attributes["id"][3:]
    for onclick in row.get("onclicks") or []:
        match = re.search(r"isShowSclass\(\s*['\"]([^'\"]+)", onclick, re.I)
        if match:
            return match.group(1)
    for value in row.get("ids") or []:
        if value.startswith("ah_"):
            return value[3:]
    return None


def _header_contract(page_text: str, requested: date) -> dict[str, Any]:
    parser = _JcPageParser()
    parser.feed(page_text)
    headers: list[dict[str, Any]] = []
    group_dates: dict[str, list[str]] = {}
    for row in parser.rows:
        attributes = row.get("attrs") or {}
        classes = str(attributes.get("class") or "").split()
        if "niDate" not in classes:
            continue
        text = _row_text(row)
        group = _group_name(row)
        group_date = _date_in_text(text)
        window_match = re.search(r"\(([^()]*--[^()]*)\)", text)
        raw_window = window_match.group(1).strip() if window_match else None
        window = re.sub(r"\s+", "", raw_window or "").replace("：", ":")
        header = {
            "group": group,
            "date": group_date.isoformat() if group_date else None,
            "window": window or None,
            "raw_text": text,
        }
        headers.append(header)
        if group and group_date:
            group_dates.setdefault(group, []).append(group_date.isoformat())

    selected_match = re.search(
        r"\bSelDate\s*=\s*['\"](\d{4}-\d{1,2}-\d{1,2})['\"]", page_text, re.I
    )
    selected_date = _normalise_date_value(selected_match.group(1) if selected_match else None)
    select_match = re.search(
        r"<select\b[^>]*onchange=[\"'][\s\S]*?</select>", page_text, re.I
    )
    select_text = select_match.group(0) if select_match else ""
    date_selector_present = bool(
        "this.options[this.selectedIndex].value" in select_text
        and "date=" in select_text
    )
    requested_text = requested.isoformat()
    requested_headers = [
        header
        for header in headers
        if header.get("date") == requested_text
    ]
    group_names = {
        header.get("group")
        for header in requested_headers
        if header.get("group")
    }
    valid_group = len(requested_headers) == 1 and len(group_names) == 1
    valid_window = bool(
        valid_group
        and requested_headers[0].get("window") == "11:00--次日11:00"
    )
    conflicting_groups = {
        group: sorted(set(dates))
        for group, dates in group_dates.items()
        if len(set(dates)) > 1
    }
    return {
        "selected_date": selected_date,
        "requested_date": requested_text,
        "date_selector_present": date_selector_present,
        "headers": headers,
        "requested_header": requested_headers[0] if valid_group else None,
        "requested_group": next(iter(group_names)) if valid_group else None,
        "conflicting_groups": conflicting_groups,
        "valid": bool(
            selected_date == requested_text
            and date_selector_present
            and valid_group
            and valid_window
            and not conflicting_groups
        ),
    }


def _jc_rows(page_text: str, contract: dict[str, Any]) -> list[dict[str, Any]]:
    parser = _JcPageParser()
    parser.feed(page_text)
    group = contract.get("requested_group")
    rows: list[dict[str, Any]] = []
    for row in parser.rows:
        attributes = row.get("attrs") or {}
        row_id = str(attributes.get("id") or "")
        if not row_id.startswith("row_") or attributes.get("name") != group:
            continue
        ids = sorted({
            int(match.group(1))
            for value in row.get("ids") or []
            for match in [re.search(r"(?:HomeTeam|GuestTeam)_(\d+)$", value, re.I)]
            if match
        })
        kickoff_matches = re.findall(
            r"20\d\d-\d\d-\d\d\s+\d\d:\d\d", " ".join(row.get("titles") or [])
        )
        cells = row.get("cells") or []
        match_number = cells[0] if cells else None
        kickoff = kickoff_matches[0] if kickoff_matches else None
        rows.append({
            "sales_row_id": row_id[4:],
            "match_number": f"{group}{match_number}" if group and match_number else None,
            "match_number_group": group,
            "match_number_value": match_number,
            "nowscore_ids": ids,
            "nowscore_id": ids[0] if len(ids) == 1 else None,
            "kickoff": kickoff,
            "home_team": cells[4] if len(cells) > 4 else None,
            "away_team": cells[7] if len(cells) > 7 else None,
            "cansale": attributes.get("cansale"),
            "league": attributes.get("gamename"),
        })
    return rows


def parse_jc_page(page_text: str, *, business_date: object) -> dict[str, Any]:
    requested = _date(business_date)
    if requested is None:
        return {"status": "FAIL", "error": "INVALID_BUSINESS_DATE", "fixtures": []}
    contract = _header_contract(page_text, requested)
    rows = _jc_rows(page_text, contract)
    counts: dict[int, int] = {}
    for row in rows:
        nowscore_id = row.get("nowscore_id")
        if nowscore_id is not None:
            counts[nowscore_id] = counts.get(nowscore_id, 0) + 1
    duplicate_ids = sum(max(0, count - 1) for count in counts.values())
    ambiguous_rows = sum(1 for row in rows if len(row.get("nowscore_ids") or []) != 1)
    window_start = datetime.combine(requested, datetime_time(11, 0)).replace(tzinfo=SHANGHAI)
    window_end = window_start + timedelta(days=1)
    outside_window = 0
    invalid_match_numbers = 0
    for row in rows:
        if not re.fullmatch(r"周[一二三四五六日天]\d{3}", str(row.get("match_number") or "")):
            invalid_match_numbers += 1
        try:
            kickoff = datetime.strptime(str(row.get("kickoff") or ""), "%Y-%m-%d %H:%M")
            kickoff = kickoff.replace(tzinfo=SHANGHAI)
        except ValueError:
            outside_window += 1
            continue
        if not window_start <= kickoff < window_end:
            outside_window += 1
    status = "PASS" if bool(
        contract.get("valid")
        and rows
        and duplicate_ids == 0
        and ambiguous_rows == 0
        and invalid_match_numbers == 0
        and outside_window == 0
    ) else "FAIL"
    return {
        "status": status,
        "contract": contract,
        "business_date": requested.isoformat(),
        "row_count": len(rows),
        "duplicate_nowscore_id_count": duplicate_ids,
        "ambiguous_row_count": ambiguous_rows,
        "invalid_match_number_count": invalid_match_numbers,
        "outside_business_window_count": outside_window,
        "next_calendar_day_kickoff_count": sum(
            1
            for row in rows
            if str(row.get("kickoff") or "")[0:10]
            == (requested + timedelta(days=1)).isoformat()
        ),
        "fixtures": rows,
    }


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


def _cp_surface_result(business_date: date, fetched_at: str) -> dict[str, Any]:
    url = CP_BASE_URL.format(business_date=quote(business_date.isoformat()))
    record: dict[str, Any] = {"url": url, "status": "FETCH_ERROR"}
    try:
        raw, meta = _fetch(url, referer="https://cp.nowscore.com/")
        record.update(meta, status="OK")
        parsed = parse_jc_page(nowscore._decode(raw), business_date=business_date)
        return {
            **parsed,
            "page": record,
            "source_surface": url,
            "fetched_at": fetched_at,
        }
    except Exception as error:
        return {
            "status": "FETCH_ERROR",
            "page": record,
            "source_surface": url,
            "fetched_at": fetched_at,
            "error": f"{type(error).__name__}: {error}",
            "fixtures": [],
        }


def _surface_for_calendar(calendar_date: date, today: date) -> str | None:
    offset = (calendar_date - today).days
    if offset == 0:
        return "ft1"
    if 1 <= offset <= 7:
        return f"sc{offset}"
    return None


def _schedule_surface(surface: str, *, today: date, fetched_at: str) -> dict[str, Any]:
    page_url = SCHEDULE_PAGE_URL.format(surface=surface)
    data_url = SCHEDULE_DATA_URL.format(surface=surface)
    page_record: dict[str, Any] = {"url": page_url, "status": "FETCH_ERROR"}
    data_record: dict[str, Any] = {"url": data_url, "status": "FETCH_ERROR"}
    try:
        page_raw, page_meta = _fetch(page_url, referer=f"{LIVE_BASE_URL}/")
        page_text = nowscore._decode(page_raw)
        page_record.update(page_meta, status="OK")
        contract = nowscore._public_jc_page_contract(page_text, surface)
        filename = contract.get("filename2")
        if filename != f"{surface}.js":
            return {
                "status": "FAIL",
                "surface": surface,
                "page": page_record,
                "data": data_record,
                "contract": contract,
                "rows": [],
                "error": "PAGE_BACKING_FILENAME_MISMATCH",
            }
        actual_data_url = f"{data_url}?{int(time.time()) * 1000}"
        data_raw, data_meta = _fetch(actual_data_url, referer=page_url)
        data_record.update(data_meta, status="OK", url=actual_data_url)
        return {
            "status": "PASS" if contract.get("valid") else "FAIL",
            "surface": surface,
            "page": page_record,
            "data": data_record,
            "contract": contract,
            "rows": nowscore._raw_schedule_rows(nowscore._decode(data_raw)),
            "fetched_at": fetched_at,
            "today": today.isoformat(),
        }
    except Exception as error:
        return {
            "status": "FETCH_ERROR",
            "surface": surface,
            "page": page_record,
            "data": data_record,
            "error": f"{type(error).__name__}: {error}",
            "rows": [],
        }


def _join_membership(
    page_result: dict[str, Any],
    schedule_surfaces: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    accepted: list[dict[str, Any]] = []
    missing_surface = 0
    missing_schedule_row = 0
    schedule_duplicate = 0
    source_date_mismatch = 0
    not_flagged = 0
    a32_corroborated = 0
    for candidate in page_result.get("fixtures") or []:
        kickoff = str(candidate.get("kickoff") or "")
        calendar = _date(kickoff[:10])
        surface = _surface_for_calendar(calendar, _date(page_result.get("today")) or calendar) if calendar else None
        # The direct sales page is authoritative.  Live ft1/scN is inspected
        # only when a bounded surface is available; no optional result can
        # remove a direct-page fixture from the replay.
        if surface is None or surface not in schedule_surfaces:
            missing_surface += 1
        else:
            schedule = schedule_surfaces[surface]
            matched = [
                (index, values)
                for index, values in schedule.get("rows") or []
                if len(values) > 0 and values[0] == candidate.get("nowscore_id")
            ]
            if len(matched) > 1:
                schedule_duplicate += len(matched) - 1
            elif not matched:
                missing_schedule_row += 1
            else:
                index, values = matched[0]
                if len(values) <= 32 or values[32] != 1:
                    not_flagged += 1
                else:
                    a32_corroborated += 1
                    candidate = {
                        **candidate,
                        "a32_corroboration": {
                            "filter_function": "SetLevel(3)",
                            "predicate": "A[j][32] == 1",
                            "row_index": 32,
                            "raw_value": values[32],
                            "array_index": index,
                            "source_surface": schedule.get("page", {}).get("url"),
                            "backing_data_url": schedule.get("data", {}).get("url"),
                            "schedule_source_date": values[11] if len(values) > 11 else None,
                            "calendar_date": calendar.isoformat() if calendar else None,
                        },
                    }
                if len(values) > 11 and str(values[11]) != kickoff[5:10]:
                    source_date_mismatch += 1
        evidence = {
            "source": "nowscore_public_jc_sales",
            "source_surface": page_result.get("source_surface"),
            "selected_date": (page_result.get("contract") or {}).get("selected_date"),
            "business_date": page_result.get("business_date"),
            "group": candidate.get("match_number_group"),
            "match_number": candidate.get("match_number"),
            "sales_row_id": candidate.get("sales_row_id"),
            "nowscore_id": candidate.get("nowscore_id"),
            "sales_window": (page_result.get("contract") or {}).get("requested_header", {}).get("window"),
            "fetched_at": page_result.get("fetched_at"),
        }
        accepted.append({
            **candidate,
            "business_date": page_result.get("business_date"),
            "business_date_source": "nowscore_public_jc_sales",
            "business_date_source_url": page_result.get("source_surface"),
            "date_provenance": {
                "source_date_value": kickoff,
                "source_date_format": "full_datetime",
                "schedule_calendar_date": kickoff[:10],
                "business_date": page_result.get("business_date"),
                "business_date_source": "nowscore_public_jc_sales",
                "business_date_source_url": page_result.get("source_surface"),
                "business_date_anchor": "SelDate + niDate header date",
                "sales_window": evidence["sales_window"],
                "match_number": candidate.get("match_number"),
                "sales_row_id": candidate.get("sales_row_id"),
            },
            "source_surface": page_result.get("source_surface"),
            "source_url": page_result.get("source_surface"),
            "fetched_at": page_result.get("fetched_at"),
            "jc_membership": "VERIFIED",
            "jc_membership_source": "nowscore_public_jc_sales",
            "jc_membership_evidence": evidence,
        })
    return {
        "accepted_fixture_count": len(accepted),
        "accepted_fixtures": accepted,
        "missing_schedule_surface_count": missing_surface,
        "missing_schedule_row_count": missing_schedule_row,
        "schedule_duplicate_count": schedule_duplicate,
        "source_date_mismatch_count": source_date_mismatch,
        "not_flagged_count": not_flagged,
        "a32_corroborated_count": a32_corroborated,
        "membership_source": "nowscore_public_jc_sales",
    }


def _direct_page_rows_available(pages: list[dict[str, Any]]) -> bool:
    """The direct sales page itself establishes nonempty current JC rows."""
    return bool(pages) and all(
        page.get("status") == "PASS" and int(page.get("row_count") or 0) > 0
        for page in pages
    )


def run_probe(dates: tuple[str, ...] = DEFAULT_DATES, *, today: object = "2026-09-01") -> dict[str, Any]:
    replay_today = _date(today)
    if replay_today is None:
        raise ValueError(f"invalid today: {today}")
    fetched_at = _now()
    pages: list[dict[str, Any]] = []
    all_calendar_dates: set[date] = set()
    for value in dates:
        business_date = _date(value)
        if business_date is None:
            pages.append({"status": "FAIL", "business_date": str(value), "error": "INVALID_DATE"})
            continue
        result = _cp_surface_result(business_date, fetched_at)
        result["today"] = replay_today.isoformat()
        pages.append(result)
        for fixture in result.get("fixtures") or []:
            calendar = _date(str(fixture.get("kickoff") or "")[:10])
            if calendar:
                all_calendar_dates.add(calendar)
    surfaces: dict[str, dict[str, Any]] = {}
    for calendar in sorted(all_calendar_dates):
        surface = _surface_for_calendar(calendar, replay_today)
        if surface and surface not in surfaces:
            surfaces[surface] = _schedule_surface(surface, today=replay_today, fetched_at=fetched_at)
    for page in pages:
        page["membership_replay"] = _join_membership(page, surfaces)
    page_id_sets = {
        str(page.get("business_date")): {
            int(fixture["nowscore_id"])
            for fixture in page.get("fixtures") or []
            if fixture.get("nowscore_id") is not None
        }
        for page in pages
    }
    dates_overlap: dict[str, list[int]] = {}
    keys = sorted(page_id_sets)
    for index, left in enumerate(keys):
        for right in keys[index + 1:]:
            dates_overlap[f"{left}|{right}"] = sorted(page_id_sets[left] & page_id_sets[right])
    accepted_id_sets = {
        str(page.get("business_date")): {
            int(fixture["nowscore_id"])
            for fixture in page.get("membership_replay", {}).get("accepted_fixtures") or []
        }
        for page in pages
    }
    accepted_overlap: dict[str, list[int]] = {}
    keys = sorted(accepted_id_sets)
    for index, left in enumerate(keys):
        for right in keys[index + 1:]:
            accepted_overlap[f"{left}|{right}"] = sorted(accepted_id_sets[left] & accepted_id_sets[right])
    pages_pass = all(page.get("status") == "PASS" for page in pages) and bool(pages)
    direct_membership_only = all(
        fixture.get("jc_membership_source") == "nowscore_public_jc_sales"
        and fixture.get("jc_membership_evidence", {}).get("source")
        == "nowscore_public_jc_sales"
        for page in pages
        for fixture in page.get("membership_replay", {}).get("accepted_fixtures") or []
    )
    direct_page_rows_available = _direct_page_rows_available(pages)
    direct_id_overlap_free = all(not values for values in dates_overlap.values())
    accepted_id_overlap_free = all(not values for values in accepted_overlap.values())
    optional_schedule_pass = bool(surfaces) and all(
        surface.get("status") == "PASS"
        and surface.get("page", {}).get("http_status") == 200
        and surface.get("data", {}).get("http_status") == 200
        for surface in surfaces.values()
    )
    gate_pass = bool(
        pages_pass
        and direct_page_rows_available
        and direct_membership_only
        and direct_id_overlap_free
        and accepted_id_overlap_free
    )
    return {
        "probe": "NOWSCORE-JC-SALES-PAGE-1",
        "status": "PASS" if gate_pass else "FAIL",
        "decision_gate": "PASS" if gate_pass else "NO_CODE",
        "today": replay_today.isoformat(),
        "fetched_at": fetched_at,
        "business_date_contract": {
            "surface": "Nowscore direct JC sales page",
            "url_template": CP_BASE_URL,
            "date_anchor": "SelDate + niDate header date",
            "sales_window": "11:00--次日11:00",
            "match_number": "niDate group name + row number cell",
            "credential_required": False,
        },
        "pages": pages,
        "schedule_surfaces": {
            key: {k: v for k, v in value.items() if k != "rows"}
            | {"raw_row_count": len(value.get("rows") or [])}
            for key, value in surfaces.items()
        },
        "business_date_id_overlap": dates_overlap,
        "accepted_id_overlap": accepted_overlap,
        "same_fixture_in_two_business_dates": sorted({
            fixture_id
            for values in dates_overlap.values()
            for fixture_id in values
        }),
        "same_accepted_fixture_in_two_business_dates": sorted({
            fixture_id
            for values in accepted_overlap.values()
            for fixture_id in values
        }),
        "membership_contract_preserved": direct_membership_only,
        "direct_membership_source": "nowscore_public_jc_sales",
        "direct_page_rows_available": direct_page_rows_available,
        "optional_schedule_pass": optional_schedule_pass,
        "current_target_rows_available": direct_page_rows_available,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Replay Nowscore JC business-date contract")
    parser.add_argument("--date", action="append", dest="dates", default=None)
    parser.add_argument("--today", default="2026-09-01")
    parser.add_argument("--output", type=Path, default=REPO_ROOT / "nowscore-business-date-probe.json")
    args = parser.parse_args()
    dates = tuple(args.dates or DEFAULT_DATES)
    payload = run_probe(dates, today=args.today)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    # The Windows runner may expose a legacy GBK stdout; keep the file's
    # UTF-8 evidence lossless while making the CLI path encoding-independent.
    print(json.dumps(payload, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
