"""Formal JC handicap line authority backed by one bounded Nowscore page.

The module deliberately sits beside the deterministic Champion.  It captures
only the explicit mobile ``竞彩指数`` ``GoJcUrl(0)`` row, projects the already
frozen Exact distribution, and keeps the unavailable official-odds baseline
explicit.  No generic Asian market or post-kickoff reconstruction is used.
"""

from __future__ import annotations

import ast
from collections import Counter
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
import re
import time
import urllib.error
import urllib.request
from html import unescape
from html.parser import HTMLParser
from typing import Any, Callable, Mapping
from zoneinfo import ZoneInfo

from exact_distribution import (
    EXACT_DISTRIBUTION_CONTRACT_VERSION,
    EXACT_DISTRIBUTION_NORMALIZATION_TOLERANCE,
    validate_exact_distribution_contract,
)
from prediction_universe import trusted_nowscore_jc_fixture


JC_HANDICAP_SOURCE_CAPTURE_VERSION = "jc_handicap_source_capture.v1"
JC_HANDICAP_CONTRACT_VERSION = "jc_handicap.v1"
JC_HANDICAP_MARKET_CODE = "JC_HANDICAP_1X2"
JC_HANDICAP_MARKET_FAMILY = "official_jc_handicap"
JC_HANDICAP_SELECTION_ORDER = ("home", "draw", "away")
JC_HANDICAP_PARSER_CONTRACT_VERSION = "nowscore_jc_handicap_parser.v1"
NOWSCORE_JC_HANDICAP_PARSER_VERSION = JC_HANDICAP_PARSER_CONTRACT_VERSION
NOWSCORE_JC_HANDICAP_ANALYSIS_URL = "https://m.nowscore.com/Analy/Analysis/{nowscore_id}.htm"
JC_HANDICAP_SOURCE_SURFACE = "nowscore_public_jc_analysis"
JC_HANDICAP_LINE_BINDING = "竞彩指数/GoJcUrl(0)"
JC_HANDICAP_LINE_PERSPECTIVE = "home"
JC_HANDICAP_BASELINE_STATUS = "NOT_AVAILABLE"
JC_HANDICAP_BASELINE_REASON = "QUOTE_TIME_SEMANTICS_NOT_PROVEN"
JC_HANDICAP_BRIER_CONVENTION = "SUM_SQUARED_ERROR"
JC_HANDICAP_RPS_CONVENTION = "CUMULATIVE_SQUARED_ERROR_DIVIDED_BY_K_MINUS_1"
JC_HANDICAP_RPS_DENOMINATOR = len(JC_HANDICAP_SELECTION_ORDER) - 1
JC_HANDICAP_MINIMUM_SUMMARY_SAMPLE_COUNT = 30
SHANGHAI = ZoneInfo("Asia/Shanghai")
FETCH_TIMEOUT_SECONDS = 12
MAX_RESPONSE_BYTES = 5 * 1024 * 1024
DEFAULT_MAX_RETRIES = 1
DEFAULT_BACKOFF_SECONDS = 0.25
RETRYABLE_HTTP_STATUSES = frozenset({408, 425, 429, 500, 502, 503, 504})
_INTEGER_LINE_RE = re.compile(r"^[+-]?[0-9]+$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TIME_RE = re.compile(r"^(\d{1,2}):(\d{2})(?::(\d{2}))?$")
_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "Chrome/131.0.0.0 Safari/537.36"
)


def _text(value: Any) -> str:
    return " ".join(unescape(str(value if value is not None else "")).split())


def _identity_text(value: Any) -> str:
    return _text(value).casefold()


def _normalise_date(value: Any) -> str | None:
    text = _text(value)
    if not _DATE_RE.fullmatch(text):
        return None
    try:
        return datetime.strptime(text, "%Y-%m-%d").date().isoformat()
    except ValueError:
        return None


def _normalise_time(value: Any) -> str | None:
    match = _TIME_RE.fullmatch(_text(value))
    if not match:
        return None
    hour, minute, second = int(match.group(1)), int(match.group(2)), int(match.group(3) or 0)
    if hour > 23 or minute > 59 or second > 59:
        return None
    return f"{hour:02d}:{minute:02d}:{second:02d}"


def _positive_int(value: Any) -> int | None:
    text = _text(value)
    if not text.isdigit():
        return None
    number = int(text)
    return number if number > 0 else None


def _integer_line(value: Any) -> int | None:
    text = _text(value)
    if not _INTEGER_LINE_RE.fullmatch(text):
        return None
    try:
        return int(text)
    except ValueError:
        return None


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    else:
        text = _text(value)
        if not text:
            return None
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=SHANGHAI)
    return parsed.astimezone(SHANGHAI)


def _iso(value: Any) -> str | None:
    parsed = _parse_datetime(value)
    return parsed.isoformat(timespec="seconds") if parsed else None


def _now_shanghai() -> datetime:
    return datetime.now(SHANGHAI)


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


class _JcAnalysisParser(HTMLParser):
    """Collect rows below the explicit mobile ``竞彩指数`` section only."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.div_depth = 0
        self.header_depth: int | None = None
        self.header_text: list[str] = []
        self.header_open = False
        self.section_active = False
        self.section_found = False
        self.rows: list[dict[str, Any]] = []
        self.current_row: dict[str, Any] | None = None
        self.current_cell: dict[str, Any] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "div":
            classes = set(_text(attributes.get("class")).split())
            if "fenxiBar" in classes:
                self.header_open = True
                self.header_depth = self.div_depth
                self.header_text = []
            self.div_depth += 1
        if tag == "tr" and self.section_active and self.current_row is None:
            onclick = _text(attributes.get("onclick"))
            matched = re.search(r"GoJcUrl\s*\(\s*([01])\s*\)", onclick, re.I)
            if matched:
                self.current_row = {"odds_type": int(matched.group(1)), "cells": []}
        if self.current_row is not None and tag in {"td", "th"} and self.current_cell is None:
            self.current_cell = {"text": []}

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self.current_cell is not None and tag == "br":
            self.current_cell["text"].append(" ")

    def handle_data(self, data: str) -> None:
        if self.header_open:
            self.header_text.append(data)
        if self.current_cell is not None:
            self.current_cell["text"].append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"td", "th"} and self.current_cell is not None and self.current_row is not None:
            self.current_row["cells"].append(_text("".join(self.current_cell["text"])))
            self.current_cell = None
        elif tag == "tr" and self.current_row is not None:
            self.rows.append(self.current_row)
            self.current_row = None
        if tag == "div":
            if self.header_open and self.header_depth is not None and self.div_depth == self.header_depth + 1:
                header = _text("".join(self.header_text))
                if "竞彩指数" in header:
                    self.section_active = True
                    self.section_found = True
                else:
                    self.section_active = False
                self.header_open = False
                self.header_depth = None
            self.div_depth = max(0, self.div_depth - 1)


def _parse_js_string(raw: str) -> str | None:
    try:
        value = ast.literal_eval(raw.strip())
    except (SyntaxError, ValueError):
        return None
    return str(value) if isinstance(value, str) else None


def _page_identity(html: str) -> dict[str, Any]:
    def js_string(name: str) -> str | None:
        match = re.search(
            rf"\b(?:var\s+)?{re.escape(name)}\s*=\s*(\"(?:\\.|[^\"])*\"|'(?:\\.|[^'])*')",
            html,
            re.I,
        )
        return _parse_js_string(match.group(1)) if match else None

    def numeric(name: str) -> int | None:
        match = re.search(rf"\b(?:var\s+)?{re.escape(name)}\s*=\s*(\d+)", html, re.I)
        if match:
            return int(match.group(1))
        hidden = re.search(
            rf"id=[\"']hide_{re.escape(name)}[\"'][^>]*value=[\"'](\d+)[\"']",
            html,
            re.I,
        )
        return int(hidden.group(1)) if hidden else None

    timestamp = numeric("MatchTimeStamp") or numeric("matchTimeStamp")
    kickoff = None
    if timestamp is not None:
        try:
            kickoff = datetime.fromtimestamp(timestamp / 1000, timezone.utc).astimezone(SHANGHAI)
        except (OverflowError, OSError, ValueError):
            kickoff = None
    return {
        "nowscore_id": numeric("scheduleId"),
        "home_team": js_string("homeTeam"),
        "away_team": js_string("guestTeam") or js_string("awayTeam"),
        "kickoff_local": kickoff.isoformat(timespec="seconds") if kickoff else None,
        "kickoff_date": kickoff.date().isoformat() if kickoff else None,
        "kickoff_time": kickoff.time().replace(microsecond=0).isoformat() if kickoff else None,
        "timestamp_source": "MatchTimeStamp" if timestamp is not None else None,
    }


def parse_nowscore_analysis_page(
    html: str,
    *,
    expected_nowscore_id: int | None = None,
) -> dict[str, Any]:
    """Parse only the explicit JC handicap row from a mobile analysis page."""

    parser = _JcAnalysisParser()
    try:
        parser.feed(str(html))
        parser.close()
    except Exception as error:
        return {
            "parser_contract_version": JC_HANDICAP_PARSER_CONTRACT_VERSION,
            "section_found": False,
            "identity": {},
            "identity_status": "PARSER_ERROR",
            "rows": [],
            "official_rows": [],
            "official_row_count": 0,
            "parser_error": f"{type(error).__name__}: {error}",
        }
    identity = _page_identity(str(html))
    page_id = identity.get("nowscore_id")
    if expected_nowscore_id is not None and page_id != expected_nowscore_id:
        identity_status = "CONFLICT"
    else:
        identity_status = "EXACT_ID" if page_id else "UNAVAILABLE"
    rows: list[dict[str, Any]] = []
    for raw_row in parser.rows:
        cells = list(raw_row.get("cells") or [])
        line = _integer_line(cells[0]) if raw_row.get("odds_type") == 0 and cells else None
        rows.append({
            "odds_type": raw_row.get("odds_type"),
            "line": line,
            "line_raw": cells[0] if raw_row.get("odds_type") == 0 and cells else None,
            "cell_values": cells,
        })
    official_rows = [row for row in rows if row.get("odds_type") == 0]
    return {
        "parser_contract_version": JC_HANDICAP_PARSER_CONTRACT_VERSION,
        "section_found": parser.section_found,
        "identity": identity,
        "identity_status": identity_status,
        "rows": rows,
        "official_rows": official_rows,
        "official_row_count": len(official_rows),
        "generic_asian_rows_ignored": sum(1 for row in rows if row.get("odds_type") != 0),
        "line_binding": JC_HANDICAP_LINE_BINDING,
    }


def _decode(raw: bytes) -> str:
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _fetch_page(url: str, timeout: float = FETCH_TIMEOUT_SECONDS) -> dict[str, Any]:
    """Fetch one Nowscore-owned page; callers bound all retry attempts."""

    started = time.monotonic()
    request_started_at = _now_shanghai()
    body = b""
    http_status: int | None = None
    error: str | None = None
    try:
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": _USER_AGENT,
                "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
                "Accept-Encoding": "identity",
                "Referer": "https://m.nowscore.com/",
                "Cache-Control": "no-cache",
            },
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            http_status = int(response.getcode())
            body = response.read(MAX_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError as exc:
        http_status = int(exc.code)
        error = f"HTTPError: {exc}"
        try:
            body = exc.read(MAX_RESPONSE_BYTES + 1)
        except OSError:
            body = b""
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        error = f"{type(exc).__name__}: {exc}"
    if len(body) > MAX_RESPONSE_BYTES:
        body = b""
        error = "RESPONSE_TOO_LARGE"
    response_at = _now_shanghai()
    response_timestamp = response_at.isoformat(timespec="seconds")
    return {
        "http_status": http_status,
        "body": body,
        "response_bytes": len(body),
        "response_sha256": _sha256(body) if body else None,
        "error": error,
        "duration_ms": round((time.monotonic() - started) * 1000, 1),
        "request_started_at": request_started_at.isoformat(timespec="seconds"),
        "response_at": response_timestamp,
        "observed_at": response_timestamp,
    }


def _normalise_fetch_result(result: Any) -> dict[str, Any]:
    if isinstance(result, tuple) and len(result) == 2 and isinstance(result[0], Mapping):
        value = dict(result[0])
        value.setdefault("body", result[1])
    elif isinstance(result, Mapping):
        value = dict(result)
    else:
        value = {"body": b"", "error": "INVALID_FETCH_RESULT"}
    body = value.get("body")
    if isinstance(body, str):
        body = body.encode("utf-8")
    if not isinstance(body, bytes):
        body = b""
    if len(body) > MAX_RESPONSE_BYTES:
        body = b""
        value["error"] = "RESPONSE_TOO_LARGE"
    value["body"] = body
    try:
        value["http_status"] = int(value["http_status"]) if value.get("http_status") is not None else None
    except (TypeError, ValueError):
        value["http_status"] = None
    # The immutable digest is derived from the bytes observed by this adapter,
    # never trusted from a caller-provided envelope.
    value["response_sha256"] = _sha256(body) if body else None
    value.setdefault("response_bytes", len(body))
    request_started_at = _iso(value.get("request_started_at"))
    response_at = _iso(value.get("response_at") or value.get("observed_at"))
    if response_at is None:
        # A custom fetcher is a test seam.  Its missing observation timestamp is
        # filled at the adapter boundary with the real local observation clock;
        # the caller's prediction/freeze clock is never used for this field.
        response_at = _now_shanghai().isoformat(timespec="seconds")
    value["request_started_at"] = request_started_at
    value["response_at"] = response_at
    value["observed_at"] = response_at
    return value


def _retryable(fetch_result: Mapping[str, Any]) -> bool:
    status = fetch_result.get("http_status")
    return status is None or status in RETRYABLE_HTTP_STATUSES


def _fixture_value(fixture: Mapping[str, Any], *names: str) -> Any:
    for name in names:
        if fixture.get(name) not in (None, ""):
            return fixture.get(name)
    return None


def _fixture_kickoff(fixture: Mapping[str, Any]) -> datetime | None:
    date_value = _fixture_value(fixture, "matchDate", "match_date")
    time_value = _fixture_value(fixture, "matchTime", "match_time")
    if date_value and time_value:
        parsed_date = _normalise_date(date_value)
        parsed_time = _normalise_time(time_value)
        if parsed_date and parsed_time:
            return _parse_datetime(f"{parsed_date}T{parsed_time}+08:00")
    return _parse_datetime(_fixture_value(fixture, "kickoff_at", "kickoff_local"))


def _name_variant_details(
    fixture: Mapping[str, Any],
    page_identity: Mapping[str, Any],
) -> list[dict[str, str]]:
    expected_home = _identity_text(_fixture_value(fixture, "homeTeam", "home_team", "home"))
    expected_away = _identity_text(_fixture_value(fixture, "awayTeam", "away_team", "away"))
    page_home = _identity_text(page_identity.get("home_team"))
    page_away = _identity_text(page_identity.get("away_team"))
    if not expected_home or not expected_away or not page_home or not page_away:
        return []
    variants: list[dict[str, str]] = []
    for side, expected, observed in (
        ("home", expected_home, page_home),
        ("away", expected_away, page_away),
    ):
        if expected != observed:
            variants.append({
                "code": "NAME_VARIANT_DIAGNOSTIC",
                "side": side,
                "fixture_name": _text(_fixture_value(fixture, "homeTeam", "home_team", "home") if side == "home" else _fixture_value(fixture, "awayTeam", "away_team", "away")),
                "page_name": _text(page_identity.get("home_team") if side == "home" else page_identity.get("away_team")),
            })
    return variants


def _identity_errors(fixture: Mapping[str, Any], page_identity: Mapping[str, Any], expected_id: int) -> list[str]:
    """Return only hard same-provider identity failures.

    Nowscore's stable page id, exact kickoff and the page's native home/away
    orientation are authoritative.  Display-name spelling/translation
    differences are reported separately as diagnostics.
    """

    errors: list[str] = []
    if page_identity.get("nowscore_id") != expected_id:
        errors.append("PAGE_NOWSCORE_ID_CONFLICT" if page_identity.get("nowscore_id") else "PAGE_NOWSCORE_ID_MISSING")

    expected_home = _identity_text(_fixture_value(fixture, "homeTeam", "home_team", "home"))
    expected_away = _identity_text(_fixture_value(fixture, "awayTeam", "away_team", "away"))
    page_home = _identity_text(page_identity.get("home_team"))
    page_away = _identity_text(page_identity.get("away_team"))
    if not expected_home or not expected_away:
        errors.append("FIXTURE_ORIENTATION_MISSING")
    if not page_home:
        errors.append("PAGE_HOME_TEAM_MISSING")
    if not page_away:
        errors.append("PAGE_AWAY_TEAM_MISSING")
    if expected_home and expected_away and page_home and page_away:
        if page_home == expected_away and page_away == expected_home:
            errors.append("PAGE_ORIENTATION_CONFLICT")

    expected_kickoff = _fixture_kickoff(fixture)
    page_date = _normalise_date(page_identity.get("kickoff_date"))
    page_time = _normalise_time(page_identity.get("kickoff_time"))
    if expected_kickoff is None or page_date != expected_kickoff.date().isoformat() or page_time != expected_kickoff.time().replace(microsecond=0).isoformat():
        errors.append("PAGE_KICKOFF_CONFLICT" if page_date or page_time else "PAGE_KICKOFF_MISSING")
    return list(dict.fromkeys(errors))


def _capture_base(
    fixture: Mapping[str, Any],
    *,
    nowscore_id: int | None,
    source_url: str | None,
    captured_at: datetime | None,
    reason: str | None = None,
    reason_codes: list[str] | None = None,
    fetch_result: Mapping[str, Any] | None = None,
    parsed: Mapping[str, Any] | None = None,
    retry_count: int = 0,
) -> dict[str, Any]:
    identity = (parsed or {}).get("identity") if isinstance(parsed, Mapping) else None
    identity = identity if isinstance(identity, Mapping) else {}
    fetch = fetch_result or {}
    response_at = _parse_datetime(fetch.get("response_at") or fetch.get("observed_at"))
    source_observed_at = response_at or captured_at
    name_variant_details = _name_variant_details(fixture, identity)
    value: dict[str, Any] = {
        "contract_version": JC_HANDICAP_SOURCE_CAPTURE_VERSION,
        "status": "CAPTURED" if reason is None else "ABSTAIN",
        "capture_status": "CAPTURED" if reason is None else "ABSTAIN",
        "reason": reason,
        "reason_codes": list(dict.fromkeys(reason_codes or ([reason] if reason else []))),
        "business_date": _fixture_value(fixture, "businessDate", "business_date"),
        "match_number": _fixture_value(fixture, "matchNum", "match_num", "match_number"),
        "home_team": _fixture_value(fixture, "homeTeam", "home_team", "home"),
        "away_team": _fixture_value(fixture, "awayTeam", "away_team", "away"),
        "kickoff_at": _fixture_kickoff(fixture).isoformat(timespec="seconds") if _fixture_kickoff(fixture) else None,
        "nowscore_id": nowscore_id,
        "source": "nowscore_public_jc",
        "source_surface": JC_HANDICAP_SOURCE_SURFACE,
        "source_url": source_url,
        "fetched_at": source_observed_at.isoformat(timespec="seconds") if source_observed_at else None,
        "captured_at": source_observed_at.isoformat(timespec="seconds") if source_observed_at else None,
        "request_started_at": _iso(fetch.get("request_started_at")),
        "response_at": _iso(fetch.get("response_at") or fetch.get("observed_at")),
        "observed_at": _iso(fetch.get("observed_at") or fetch.get("response_at")),
        "http_status": fetch.get("http_status"),
        "page_http_status": fetch.get("http_status"),
        "response_bytes": fetch.get("response_bytes", 0),
        "response_sha256": fetch.get("response_sha256"),
        "content_sha256": fetch.get("response_sha256"),
        "parser_contract_version": JC_HANDICAP_PARSER_CONTRACT_VERSION,
        "parser_version": JC_HANDICAP_PARSER_CONTRACT_VERSION,
        "line_binding": JC_HANDICAP_LINE_BINDING,
        "line_perspective": JC_HANDICAP_LINE_PERSPECTIVE,
        "official_integer_line": None,
        "line": None,
        "line_available": reason is None,
        "odds_available": False,
        "page_identity": deepcopy(dict(identity)),
        "identity_status": (parsed or {}).get("identity_status"),
        "official_row_count": int((parsed or {}).get("official_row_count") or 0),
        "retry_count": retry_count,
        "fetch_error": fetch.get("error"),
        "name_diagnostics": list(dict.fromkeys(item["code"] for item in name_variant_details)),
        "name_variant_sides": [item["side"] for item in name_variant_details],
        "name_variant_details": name_variant_details,
    }
    if reason is None:
        rows = (parsed or {}).get("official_rows") or []
        value["line"] = rows[0].get("line") if rows else None
        value["official_integer_line"] = value["line"]
    return value


def _abstain_capture(
    fixture: Mapping[str, Any],
    reason: str,
    *,
    nowscore_id: int | None = None,
    source_url: str | None = None,
    captured_at: datetime | None = None,
    reason_codes: list[str] | None = None,
    fetch_result: Mapping[str, Any] | None = None,
    parsed: Mapping[str, Any] | None = None,
    retry_count: int = 0,
) -> dict[str, Any]:
    return _capture_base(
        fixture,
        nowscore_id=nowscore_id,
        source_url=source_url,
        captured_at=captured_at,
        reason=reason,
        reason_codes=reason_codes,
        fetch_result=fetch_result,
        parsed=parsed,
        retry_count=retry_count,
    )


def validate_nowscore_jc_handicap_capture(
    capture: Mapping[str, Any],
    *,
    fixture: Mapping[str, Any] | None = None,
    kickoff_at: Any = None,
) -> None:
    if not isinstance(capture, Mapping) or capture.get("contract_version") != JC_HANDICAP_SOURCE_CAPTURE_VERSION:
        raise ValueError("JC handicap source capture contract version is invalid")
    if capture.get("status") not in {"CAPTURED", "ABSTAIN"} or capture.get("capture_status") != capture.get("status"):
        raise ValueError("JC handicap source capture status is invalid")
    if capture.get("source") != "nowscore_public_jc" or capture.get("source_surface") != JC_HANDICAP_SOURCE_SURFACE:
        raise ValueError("JC handicap source surface is invalid")
    expected_id = _positive_int(capture.get("nowscore_id"))
    if expected_id is None:
        raise ValueError("JC handicap source capture nowscore id is missing")
    expected_url = NOWSCORE_JC_HANDICAP_ANALYSIS_URL.format(nowscore_id=expected_id)
    if capture.get("source_url") != expected_url:
        raise ValueError("JC handicap source URL is invalid")
    if capture.get("parser_contract_version") != JC_HANDICAP_PARSER_CONTRACT_VERSION:
        raise ValueError("JC handicap parser contract version is invalid")
    if capture.get("line_binding") != JC_HANDICAP_LINE_BINDING or capture.get("line_perspective") != "home":
        raise ValueError("JC handicap line binding is invalid")
    if capture.get("status") == "CAPTURED":
        line = _integer_line(capture.get("line"))
        if line is None or capture.get("official_integer_line") != line:
            raise ValueError("captured JC handicap line is not an integer")
        if capture.get("page_http_status") != 200 or not capture.get("response_sha256"):
            raise ValueError("captured JC handicap page response is not immutable")
        if capture.get("identity_status") != "EXACT_ID":
            raise ValueError("captured JC handicap page identity is not exact")
        response_at = _parse_datetime(capture.get("response_at"))
        observed_at = _parse_datetime(capture.get("observed_at"))
        fetched_at = _parse_datetime(capture.get("fetched_at"))
        captured_at = _parse_datetime(capture.get("captured_at"))
        if not response_at or not observed_at or not fetched_at or not captured_at:
            raise ValueError("captured JC handicap source observation timestamp is missing")
        if not (response_at == observed_at == fetched_at == captured_at):
            raise ValueError("captured JC handicap source timestamps are inconsistent")
        request_started_at = _parse_datetime(capture.get("request_started_at"))
        if request_started_at is not None and request_started_at > response_at:
            raise ValueError("captured JC handicap request timestamp is after response")
    else:
        if not _text(capture.get("reason")):
            raise ValueError("JC handicap abstain capture has no reason")
        if capture.get("line") is not None or capture.get("official_integer_line") is not None:
            raise ValueError("abstained JC handicap capture contains a line")
    if fixture is not None:
        trusted = trusted_nowscore_jc_fixture(fixture, expected_id)
        if not trusted.get("trusted"):
            raise ValueError("JC handicap capture fixture binding is not trusted")
        if _fixture_value(fixture, "businessDate", "business_date") != capture.get("business_date"):
            raise ValueError("JC handicap capture business date mismatch")
    boundary = _parse_datetime(kickoff_at) if kickoff_at is not None else _parse_datetime(capture.get("kickoff_at"))
    captured = _parse_datetime(capture.get("captured_at"))
    if capture.get("status") == "CAPTURED" and boundary is not None and captured is not None and captured >= boundary:
        raise ValueError("JC handicap capture is not strictly prematch")


def _reusable_capture(
    cached_capture: Mapping[str, Any] | None,
    fixture: Mapping[str, Any],
    *,
    kickoff: datetime,
) -> dict[str, Any] | None:
    if not isinstance(cached_capture, Mapping) or cached_capture.get("status") != "CAPTURED":
        return None
    try:
        validate_nowscore_jc_handicap_capture(cached_capture, fixture=fixture, kickoff_at=kickoff)
    except ValueError:
        return None
    expected_id = _positive_int(_fixture_value(fixture, "nowscoreId", "nowscore_id"))
    if expected_id is None or _positive_int(cached_capture.get("nowscore_id")) != expected_id:
        return None
    page_identity = cached_capture.get("page_identity")
    if not isinstance(page_identity, Mapping) or _identity_errors(fixture, page_identity, expected_id):
        return None
    captured = _parse_datetime(cached_capture.get("captured_at"))
    if captured is None or captured >= kickoff:
        return None
    value = deepcopy(dict(cached_capture))
    value["reuse_status"] = "REUSED_VALID_PREKICKOFF_CAPTURE"
    return value


def capture_nowscore_jc_handicap(
    fixture: Mapping[str, Any],
    *,
    now: datetime | None = None,
    timeout_seconds: float = FETCH_TIMEOUT_SECONDS,
    max_retries: int = DEFAULT_MAX_RETRIES,
    backoff_seconds: float = DEFAULT_BACKOFF_SECONDS,
    fetcher: Callable[..., Any] | None = None,
    cached_capture: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Capture one official Nowscore integer line with a bounded request budget."""

    if not isinstance(fixture, Mapping):
        return _abstain_capture({}, "MISSING_FIXTURE")
    explicit_id = _fixture_value(fixture, "nowscoreId", "nowscore_id")
    direct_id = _positive_int(fixture.get("nowscoreId"))
    alias_id = _positive_int(fixture.get("nowscore_id"))
    if direct_id is not None and alias_id is not None and direct_id != alias_id:
        return _abstain_capture(fixture, "IDENTITY_CONFLICT", reason_codes=["NOWSCORE_ID_FIELD_CONFLICT"])
    trusted = trusted_nowscore_jc_fixture(fixture, explicit_id)
    nowscore_id = _positive_int(trusted.get("nowscore_id") or explicit_id)
    source_url = NOWSCORE_JC_HANDICAP_ANALYSIS_URL.format(nowscore_id=nowscore_id) if nowscore_id else None
    if not trusted.get("trusted"):
        return _abstain_capture(
            fixture,
            "FIXTURE_BINDING_UNVERIFIED",
            nowscore_id=nowscore_id,
            source_url=source_url,
            reason_codes=list(trusted.get("reasons") or []),
        )
    kickoff = _fixture_kickoff(fixture)
    # ``now`` is an injectable eligibility-clock seam for deterministic tests.
    # It is never a source-observation timestamp; the latter comes only from
    # the fetch result after the HTTP response has completed.
    clock = _parse_datetime(now) if now is not None else _now_shanghai()
    if kickoff is None:
        return _abstain_capture(fixture, "KICKOFF_UNRESOLVED", nowscore_id=nowscore_id, source_url=source_url)
    cached = _reusable_capture(cached_capture, fixture, kickoff=kickoff)
    if cached is not None:
        return cached
    if clock >= kickoff:
        return _abstain_capture(
            fixture,
            "POST_KICKOFF_ONLY",
            nowscore_id=nowscore_id,
            source_url=source_url,
        )

    request_fn = fetcher or _fetch_page
    bounded_retries = max(0, min(int(max_retries), 2))
    result: dict[str, Any] = {"http_status": None, "body": b"", "error": "NO_ATTEMPT"}
    attempts = 0
    for attempt in range(bounded_retries + 1):
        attempts = attempt + 1
        try:
            result = _normalise_fetch_result(request_fn(source_url, timeout=timeout_seconds))
        except TypeError:
            result = _normalise_fetch_result(request_fn(source_url))
        if not _retryable(result) or attempt >= bounded_retries:
            break
        time.sleep(max(0.0, min(float(backoff_seconds) * (2**attempt), 2.0)))
    response_at = _parse_datetime(result.get("response_at") or result.get("observed_at"))
    if response_at is None:
        return _abstain_capture(
            fixture,
            "SOURCE_TIMESTAMP_INVALID",
            nowscore_id=nowscore_id,
            source_url=source_url,
            fetch_result=result,
            reason_codes=["SOURCE_RESPONSE_TIME_MISSING"],
            retry_count=max(0, attempts - 1),
        )
    request_started_at = _parse_datetime(result.get("request_started_at"))
    if request_started_at is not None and request_started_at > response_at:
        return _abstain_capture(
            fixture,
            "SOURCE_TIMESTAMP_INVALID",
            nowscore_id=nowscore_id,
            source_url=source_url,
            captured_at=response_at,
            fetch_result=result,
            reason_codes=["SOURCE_REQUEST_AFTER_RESPONSE"],
            retry_count=max(0, attempts - 1),
        )
    if response_at >= kickoff:
        return _abstain_capture(
            fixture,
            "POST_KICKOFF_ONLY",
            nowscore_id=nowscore_id,
            source_url=source_url,
            captured_at=response_at,
            reason_codes=["SOURCE_RESPONSE_AT_OR_AFTER_KICKOFF"],
            fetch_result=result,
            retry_count=max(0, attempts - 1),
        )
    status = result.get("http_status")
    if status != 200 or not result.get("body"):
        reason = "SOURCE_HTTP_NOT_200" if status != 200 else "EMPTY_RESPONSE"
        return _abstain_capture(
            fixture,
            reason,
            nowscore_id=nowscore_id,
            source_url=source_url,
            captured_at=response_at,
            fetch_result=result,
            retry_count=max(0, attempts - 1),
        )
    html = _decode(result["body"])
    parsed = parse_nowscore_analysis_page(html, expected_nowscore_id=nowscore_id)
    identity_errors = _identity_errors(fixture, parsed.get("identity") or {}, nowscore_id)
    if identity_errors:
        return _abstain_capture(
            fixture,
            "IDENTITY_CONFLICT",
            nowscore_id=nowscore_id,
            source_url=source_url,
            captured_at=response_at,
            reason_codes=identity_errors,
            fetch_result=result,
            parsed=parsed,
            retry_count=max(0, attempts - 1),
        )
    if not parsed.get("section_found"):
        reason = "PARSER_DRIFT"
    elif int(parsed.get("official_row_count") or 0) == 0:
        reason = "JC_HANDICAP_ROW_MISSING"
    elif int(parsed.get("official_row_count") or 0) > 1:
        reason = "MULTIPLE_JC_HANDICAP_ROWS"
    elif _integer_line((parsed.get("official_rows") or [{}])[0].get("line")) is None:
        reason = "NON_INTEGER_LINE"
    else:
        capture = _capture_base(
            fixture,
            nowscore_id=nowscore_id,
            source_url=source_url,
            captured_at=response_at,
            fetch_result=result,
            parsed=parsed,
            retry_count=max(0, attempts - 1),
        )
        validate_nowscore_jc_handicap_capture(capture, fixture=fixture, kickoff_at=kickoff)
        return capture
    return _abstain_capture(
            fixture,
            reason,
            nowscore_id=nowscore_id,
            source_url=source_url,
            captured_at=response_at,
            fetch_result=result,
        parsed=parsed,
        retry_count=max(0, attempts - 1),
    )


def abstain_nowscore_jc_handicap_capture(
    fixture: Mapping[str, Any] | None,
    reason: str,
    *,
    reason_codes: list[str] | None = None,
) -> dict[str, Any]:
    """Create a serializable fail-closed capture when the adapter itself errors."""

    row = fixture if isinstance(fixture, Mapping) else {}
    explicit_id = _fixture_value(row, "nowscoreId", "nowscore_id")
    nowscore_id = _positive_int(explicit_id)
    source_url = NOWSCORE_JC_HANDICAP_ANALYSIS_URL.format(nowscore_id=nowscore_id) if nowscore_id else None
    return _abstain_capture(
        row,
        reason,
        nowscore_id=nowscore_id,
        source_url=source_url,
        reason_codes=reason_codes,
    )


def _validate_line(line: Any) -> int:
    value = _integer_line(line)
    if value is None:
        raise ValueError("JC handicap line must be an integer")
    return value


def _goal(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    number = _number(value)
    if number is None or number < 0 or int(number) != number:
        return None
    return int(number)


def handicap_class(home_goals: Any, away_goals: Any, line: Any) -> str:
    home = _goal(home_goals)
    away = _goal(away_goals)
    if home is None or away is None:
        raise ValueError("realized 90m score must be non-negative integers")
    handicap = _validate_line(line)
    adjusted_home = home + handicap
    return "home" if adjusted_home > away else "draw" if adjusted_home == away else "away"


def _cells_from_exact(value: Any) -> list[Mapping[str, Any]]:
    if isinstance(value, Mapping):
        if value.get("contract_version") == EXACT_DISTRIBUTION_CONTRACT_VERSION:
            validate_exact_distribution_contract(value)
        cells = value.get("cells")
    else:
        cells = value
    if not isinstance(cells, list) or len(cells) != 169:
        raise ValueError("JC handicap projection requires the frozen 13x13 Exact grid")
    seen: set[tuple[int, int]] = set()
    validated: list[Mapping[str, Any]] = []
    total = 0.0
    for cell in cells:
        if not isinstance(cell, Mapping):
            raise ValueError("Exact cell is not an object")
        home = _number(cell.get("home_goals"))
        away = _number(cell.get("away_goals"))
        probability = _number(cell.get("probability"))
        if home is None or away is None or probability is None or probability < 0 or int(home) != home or int(away) != away:
            raise ValueError("Exact cell is invalid")
        score = (int(home), int(away))
        if score in seen or not 0 <= score[0] <= 12 or not 0 <= score[1] <= 12:
            raise ValueError("Exact grid has duplicate or out-of-range cell")
        seen.add(score)
        total += probability
        validated.append(cell)
    if len(seen) != 169 or abs(total - 1.0) > EXACT_DISTRIBUTION_NORMALIZATION_TOLERANCE:
        raise ValueError("Exact grid is not a normalized complete grid")
    return validated


def project_jc_handicap_probabilities(exact_distribution: Any, line: Any) -> dict[str, float]:
    """Deterministically sum the frozen Exact cells into H/D/A."""

    handicap = _validate_line(line)
    values = {selection: 0.0 for selection in JC_HANDICAP_SELECTION_ORDER}
    for cell in _cells_from_exact(exact_distribution):
        selection = handicap_class(cell.get("home_goals"), cell.get("away_goals"), handicap)
        values[selection] += float(cell.get("probability"))
    return values


def _baseline() -> dict[str, Any]:
    return {
        "status": JC_HANDICAP_BASELINE_STATUS,
        "probabilities": None,
        "captured_at": None,
        "source": None,
        "reason": JC_HANDICAP_BASELINE_REASON,
        "derived_from_asian_handicap": False,
        "odds_available": False,
    }


def _source_authority(capture: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "provider": "nowscore_public_jc",
        "surface": capture.get("source_surface") or JC_HANDICAP_SOURCE_SURFACE,
        "source_url": capture.get("source_url"),
        "nowscore_id": capture.get("nowscore_id"),
        "business_date": capture.get("business_date"),
        "match_number": capture.get("match_number"),
        "fetched_at": capture.get("fetched_at"),
        "captured_at": capture.get("captured_at"),
        "request_started_at": capture.get("request_started_at"),
        "response_at": capture.get("response_at"),
        "observed_at": capture.get("observed_at"),
        "http_status": capture.get("page_http_status", capture.get("http_status")),
        "response_sha256": capture.get("response_sha256"),
        "content_sha256": capture.get("content_sha256") or capture.get("response_sha256"),
        "parser_contract_version": capture.get("parser_contract_version"),
        "line_binding": capture.get("line_binding"),
        "line_perspective": capture.get("line_perspective"),
        "identity_status": capture.get("identity_status"),
        "page_identity": deepcopy(capture.get("page_identity") or {}),
        "capture_status": capture.get("status"),
        "capture_reason": capture.get("reason"),
        "capture_reason_codes": list(capture.get("reason_codes") or []),
        "name_diagnostics": list(capture.get("name_diagnostics") or []),
        "name_variant_sides": list(capture.get("name_variant_sides") or []),
        "name_variant_details": deepcopy(capture.get("name_variant_details") or []),
    }


def _capture_identity_conflicts(
    capture: Mapping[str, Any],
    expected: Mapping[str, Any] | None,
) -> list[str]:
    if not isinstance(expected, Mapping) or capture.get("status") != "CAPTURED":
        return []
    conflicts: list[str] = []
    expected_id = _positive_int(expected.get("nowscore_id") or expected.get("nowscoreId"))
    captured_id = _positive_int(capture.get("nowscore_id"))
    if expected_id is not None and captured_id != expected_id:
        conflicts.append("CAPTURE_NOWSCORE_ID_CONFLICT")
    page_identity = capture.get("page_identity")
    if isinstance(page_identity, Mapping):
        expected_home = _identity_text(expected.get("home"))
        expected_away = _identity_text(expected.get("away"))
        page_home = _identity_text(page_identity.get("home_team"))
        page_away = _identity_text(page_identity.get("away_team"))
        if expected_home and expected_away and page_home == expected_away and page_away == expected_home:
            conflicts.append("CAPTURE_ORIENTATION_CONFLICT")
    captured_kickoff = _parse_datetime(capture.get("kickoff_at"))
    expected_kickoff = _parse_datetime(expected.get("kickoff_at"))
    if captured_kickoff is None or expected_kickoff is None or captured_kickoff != expected_kickoff:
        conflicts.append("CAPTURE_KICKOFF_CONFLICT")
    expected_date = expected.get("business_date")
    if expected_date not in (None, "") and str(capture.get("business_date") or "") != str(expected_date):
        conflicts.append("CAPTURE_BUSINESS_DATE_CONFLICT")
    return conflicts


def _horizon(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    result = deepcopy(dict(value))
    created = _parse_datetime(result.get("prediction_created_at"))
    kickoff = _parse_datetime(result.get("kickoff_at"))
    if created and kickoff:
        result.setdefault("minutes", round((kickoff - created).total_seconds() / 60.0, 3))
    result.setdefault("definition", "prediction_created_at_to_kickoff_at")
    return result


def _contract_hash(contract: Mapping[str, Any]) -> str:
    return _sha256(_canonical_json({key: value for key, value in contract.items() if key != "content_sha256"}))


def build_jc_handicap_contract(
    exact_distribution: Mapping[str, Any] | None,
    source_capture: Mapping[str, Any],
    *,
    model_identity: Mapping[str, Any] | None = None,
    forecast_horizon: Mapping[str, Any] | None = None,
    expected_match_identity: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Freeze formal H/D/A projection or an explicit per-match ABSTAIN."""

    exact_valid = False
    exact_reason = None
    exact_fingerprint = None
    if isinstance(exact_distribution, Mapping):
        try:
            validate_exact_distribution_contract(exact_distribution)
            exact_valid = True
            exact_fingerprint = exact_distribution.get("content_sha256")
        except ValueError as error:
            exact_reason = f"EXACT_DISTRIBUTION_INVALID:{type(error).__name__}"
    else:
        exact_reason = "EXACT_DISTRIBUTION_MISSING"

    capture = source_capture if isinstance(source_capture, Mapping) else {}
    source_status = str(capture.get("status") or "ABSTAIN")
    reasons = list(capture.get("reason_codes") or [])
    if capture.get("reason") and capture.get("reason") not in reasons:
        reasons.insert(0, str(capture["reason"]))
    formal = exact_valid and source_status == "CAPTURED"
    line = _integer_line(capture.get("line")) if formal else None
    if formal and line is None:
        formal = False
        reasons.insert(0, "NON_INTEGER_LINE")
    identity_conflicts = _capture_identity_conflicts(capture, expected_match_identity)
    if formal and identity_conflicts:
        formal = False
        reasons = [*identity_conflicts, *reasons]
    if not exact_valid and exact_reason:
        reasons.insert(0, exact_reason)
    if not formal and not reasons:
        reasons = ["JC_HANDICAP_SOURCE_CAPTURE_MISSING"] if not capture else ["JC_HANDICAP_ABSTAIN"]
    probabilities = None
    vector = None
    top_selection = None
    top_probability = None
    normalization: dict[str, Any] = {
        "represented_probability_sum": None,
        "target_probability_sum": 1.0,
        "absolute_error": None,
        "tolerance": EXACT_DISTRIBUTION_NORMALIZATION_TOLERANCE,
        "status": "NOT_COMPUTED_DUE_TO_ABSTAIN" if not formal else None,
    }
    if formal:
        try:
            probabilities = project_jc_handicap_probabilities(exact_distribution, line)
        except ValueError as error:
            formal = False
            reasons.insert(0, f"PROJECTION_INVALID:{type(error).__name__}")
        else:
            vector = [probabilities[key] for key in JC_HANDICAP_SELECTION_ORDER]
            represented_sum = sum(vector)
            normalization = {
                "represented_probability_sum": represented_sum,
                "target_probability_sum": 1.0,
                "absolute_error": abs(represented_sum - 1.0),
                "tolerance": EXACT_DISTRIBUTION_NORMALIZATION_TOLERANCE,
                "status": "NORMALIZED_FROM_FROZEN_EFFECTIVE_EXACT_DISTRIBUTION",
            }
            top_selection = max(
                JC_HANDICAP_SELECTION_ORDER,
                key=lambda key: (probabilities[key], -JC_HANDICAP_SELECTION_ORDER.index(key)),
            )
            top_probability = probabilities[top_selection]
    if not formal:
        # An abstain contract must never retain a line or projected values from
        # a source/exact authority that failed one of the formal gates.
        line = None
        probabilities = None
        vector = None
        top_selection = None
        top_probability = None
        normalization = {
            "represented_probability_sum": None,
            "target_probability_sum": 1.0,
            "absolute_error": None,
            "tolerance": EXACT_DISTRIBUTION_NORMALIZATION_TOLERANCE,
            "status": "NOT_COMPUTED_DUE_TO_ABSTAIN",
        }
    status = "FORMAL_JC_HANDICAP_FROZEN" if formal else "JC_HANDICAP_ABSTAIN"
    contract: dict[str, Any] = {
        "contract_version": JC_HANDICAP_CONTRACT_VERSION,
        "status": status,
        "served_state": "FORMAL" if formal else "ABSTAIN",
        "authority": "frozen_effective_exact_distribution_and_prematch_nowscore_line",
        "market_code": JC_HANDICAP_MARKET_CODE,
        "market_family": JC_HANDICAP_MARKET_FAMILY,
        "market_name": "official JC handicap 1X2",
        "selection_order": list(JC_HANDICAP_SELECTION_ORDER),
        "line": line,
        "official_integer_line": line,
        "line_perspective": JC_HANDICAP_LINE_PERSPECTIVE,
        "source_authority": _source_authority(capture),
        "probabilities": probabilities,
        "probability_vector": vector,
        "top_selection": top_selection,
        "top_probability": top_probability,
        "normalization": normalization,
        "underlying_exact_distribution": {
            "contract_version": EXACT_DISTRIBUTION_CONTRACT_VERSION,
            "status": "FROZEN_EXACT_AUTHORITY" if exact_valid else "MISSING_OR_INVALID",
            "reference": "inline:exact_score_distribution",
            "content_sha256": exact_fingerprint,
        },
        "forecast_horizon": _horizon(forecast_horizon),
        "abstain_reason": None if formal else reasons[0],
        "abstain_reasons": [] if formal else list(dict.fromkeys(reasons)),
        "same_time_official_market_baseline": _baseline(),
        "generic_asian_handicap_used": False,
        "model_identity": deepcopy(dict(model_identity or {})),
        "content_sha256": None,
    }
    contract["content_sha256"] = _contract_hash(contract)
    validate_jc_handicap_contract(contract)
    return contract


def validate_jc_handicap_contract(
    contract: Mapping[str, Any],
    *,
    expected_exact_content_sha256: str | None = None,
) -> None:
    if not isinstance(contract, Mapping):
        raise ValueError("JC handicap contract must be an object")
    if (
        contract.get("contract_version") != JC_HANDICAP_CONTRACT_VERSION
        or contract.get("market_code") != JC_HANDICAP_MARKET_CODE
        or contract.get("market_family") != JC_HANDICAP_MARKET_FAMILY
        or contract.get("authority") != "frozen_effective_exact_distribution_and_prematch_nowscore_line"
    ):
        raise ValueError("JC handicap contract identity is invalid")
    if contract.get("selection_order") != list(JC_HANDICAP_SELECTION_ORDER):
        raise ValueError("JC handicap selection order is invalid")
    if contract.get("line_perspective") != "home" or contract.get("generic_asian_handicap_used") is not False:
        raise ValueError("JC handicap line semantics are invalid")
    baseline = contract.get("same_time_official_market_baseline")
    if (
        not isinstance(baseline, Mapping)
        or baseline.get("status") != JC_HANDICAP_BASELINE_STATUS
        or baseline.get("probabilities") is not None
        or baseline.get("captured_at") is not None
        or baseline.get("source") is not None
        or baseline.get("reason") != JC_HANDICAP_BASELINE_REASON
        or baseline.get("derived_from_asian_handicap") is not False
        or baseline.get("odds_available") is not False
    ):
        raise ValueError("JC handicap same-time baseline is invalid")
    source = contract.get("source_authority")
    if not isinstance(source, Mapping):
        raise ValueError("JC handicap source authority is missing")
    if (
        source.get("provider") != "nowscore_public_jc"
        or source.get("surface") != JC_HANDICAP_SOURCE_SURFACE
        or source.get("line_binding") != JC_HANDICAP_LINE_BINDING
        or source.get("line_perspective") != "home"
    ):
        raise ValueError("JC handicap source authority is invalid")
    underlying = contract.get("underlying_exact_distribution")
    if not isinstance(underlying, Mapping) or underlying.get("reference") != "inline:exact_score_distribution":
        raise ValueError("JC handicap Exact authority reference is invalid")
    if expected_exact_content_sha256 is not None and underlying.get("content_sha256") != expected_exact_content_sha256:
        raise ValueError("JC handicap Exact authority fingerprint mismatch")
    status = contract.get("status")
    formal = status == "FORMAL_JC_HANDICAP_FROZEN" and contract.get("served_state") == "FORMAL"
    abstain = status == "JC_HANDICAP_ABSTAIN" and contract.get("served_state") == "ABSTAIN"
    if not (formal or abstain):
        raise ValueError("JC handicap served state is invalid")
    if formal:
        line = _integer_line(contract.get("line"))
        if line is None or contract.get("official_integer_line") != line:
            raise ValueError("formal JC handicap line is invalid")
        if source.get("capture_status") != "CAPTURED" or source.get("http_status") != 200 or not source.get("response_sha256"):
            raise ValueError("formal JC handicap source capture is invalid")
        if underlying.get("status") != "FROZEN_EXACT_AUTHORITY" or not underlying.get("content_sha256"):
            raise ValueError("formal JC handicap Exact authority is invalid")
        probabilities = contract.get("probabilities")
        vector = contract.get("probability_vector")
        if not isinstance(probabilities, Mapping) or list(probabilities) != list(JC_HANDICAP_SELECTION_ORDER):
            raise ValueError("formal JC handicap probability map is invalid")
        if not isinstance(vector, list) or len(vector) != len(JC_HANDICAP_SELECTION_ORDER):
            raise ValueError("formal JC handicap probability vector is invalid")
        for key, value in zip(JC_HANDICAP_SELECTION_ORDER, vector):
            number = _number(value)
            if number is None or number < 0 or abs(number - float(probabilities.get(key))) > EXACT_DISTRIBUTION_NORMALIZATION_TOLERANCE:
                raise ValueError("formal JC handicap probability vector does not match map")
        total = sum(float(value) for value in vector)
        normalization = contract.get("normalization")
        if not isinstance(normalization, Mapping) or abs(total - 1.0) > EXACT_DISTRIBUTION_NORMALIZATION_TOLERANCE:
            raise ValueError("formal JC handicap probability vector is not normalized")
        if abs(float(normalization.get("represented_probability_sum")) - total) > float(normalization.get("tolerance")):
            raise ValueError("JC handicap normalization diagnostics do not match vector")
        expected_top = max(
            JC_HANDICAP_SELECTION_ORDER,
            key=lambda key: (float(probabilities[key]), -JC_HANDICAP_SELECTION_ORDER.index(key)),
        )
        if contract.get("top_selection") != expected_top or _number(contract.get("top_probability")) != float(probabilities[expected_top]):
            raise ValueError("JC handicap top selection does not match vector")
        if contract.get("abstain_reason") is not None or contract.get("abstain_reasons") != []:
            raise ValueError("formal JC handicap contains an abstain reason")
    else:
        if not _text(contract.get("abstain_reason")) or not isinstance(contract.get("abstain_reasons"), list):
            raise ValueError("JC handicap abstain reason is missing")
        if contract.get("line") is not None or contract.get("official_integer_line") is not None:
            raise ValueError("JC handicap abstain contains a line")
        if contract.get("probabilities") is not None or contract.get("probability_vector") is not None:
            raise ValueError("JC handicap abstain contains probabilities")
    supplied_hash = contract.get("content_sha256")
    if not isinstance(supplied_hash, str) or supplied_hash != _contract_hash(contract):
        raise ValueError("JC handicap content hash mismatch")


def _expected_exact_identity(record: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: record.get(key)
        for key in (
            "prediction_id",
            "model_family",
            "model_core_version",
            "release_version",
            "model_source_fingerprint",
            "model_run_fingerprint",
            "calibration_artifact_sha256",
            "effective_calibration_fingerprint",
            "input_sha256",
        )
        if record.get(key) is not None
    }


def _record_jc_handicap(record: Mapping[str, Any]) -> Mapping[str, Any] | None:
    value = record.get("jc_handicap")
    if isinstance(value, Mapping):
        return value
    output = record.get("prediction_output") or {}
    for key in ("jc_handicap", "official_jc_handicap"):
        value = output.get(key) if isinstance(output, Mapping) else None
        if isinstance(value, Mapping):
            return value
    return None


def classify_frozen_jc_handicap(
    record: Mapping[str, Any],
    home_goals: Any,
    away_goals: Any,
) -> dict[str, Any]:
    base: dict[str, Any] = {
        "FORMAL_JC_HANDICAP_FROZEN": False,
        "JC_HANDICAP_1X2_ELIGIBLE": False,
        "jc_handicap_status": "MISSING_FROZEN_JC_HANDICAP",
        "authority_status": "RESEARCH_RECONSTRUCTED",
        "official_jc_handicap_line": None,
        "actual_jc_handicap_class": None,
        "jc_handicap_probability": None,
        "jc_handicap_top_selection": None,
        "jc_handicap_top_selection_hit": None,
        "same_time_official_market_baseline_status": None,
    }
    if not isinstance(record, Mapping):
        return base
    exact = record.get("exact_score_distribution")
    if not isinstance(exact, Mapping):
        base["jc_handicap_status"] = "MISSING_FROZEN_EXACT_DISTRIBUTION"
        return base
    try:
        validate_exact_distribution_contract(exact, expected_model_identity=_expected_exact_identity(record))
    except ValueError:
        base["jc_handicap_status"] = "INVALID_FROZEN_EXACT_DISTRIBUTION"
        base["authority_status"] = "FAIL_CLOSED"
        return base
    contract = _record_jc_handicap(record)
    if not isinstance(contract, Mapping):
        return base
    try:
        validate_jc_handicap_contract(contract, expected_exact_content_sha256=exact.get("content_sha256"))
    except ValueError:
        base["jc_handicap_status"] = "INVALID_FROZEN_JC_HANDICAP"
        base["authority_status"] = "FAIL_CLOSED"
        return base
    if contract.get("served_state") != "FORMAL":
        base.update({
            "jc_handicap_status": "JC_HANDICAP_ABSTAIN",
            "authority_status": "FROZEN_PREDICTION_TIME",
            "same_time_official_market_baseline_status": JC_HANDICAP_BASELINE_STATUS,
        })
        return base
    try:
        actual = handicap_class(home_goals, away_goals, contract.get("line"))
    except (TypeError, ValueError):
        base["jc_handicap_status"] = "INVALID_REALIZED_SCORE"
        return base
    probabilities = contract.get("probabilities") or {}
    top = contract.get("top_selection")
    base.update({
        "FORMAL_JC_HANDICAP_FROZEN": True,
        "JC_HANDICAP_1X2_ELIGIBLE": True,
        "jc_handicap_status": "FORMAL_JC_HANDICAP_FROZEN",
        "authority_status": "FROZEN_PREDICTION_TIME",
        "official_jc_handicap_line": int(contract["line"]),
        "actual_jc_handicap_class": actual,
        "jc_handicap_probability": float(probabilities[actual]),
        "jc_handicap_top_selection": top,
        "jc_handicap_top_selection_hit": top == actual,
        "same_time_official_market_baseline_status": JC_HANDICAP_BASELINE_STATUS,
    })
    return base


def settle_frozen_jc_handicap(
    record_or_contract: Mapping[str, Any],
    score: tuple[int, int] | list[int] | Mapping[str, Any],
) -> dict[str, Any]:
    contract = _record_jc_handicap(record_or_contract) if isinstance(record_or_contract, Mapping) else None
    if contract is None and isinstance(record_or_contract, Mapping) and record_or_contract.get("contract_version") == JC_HANDICAP_CONTRACT_VERSION:
        contract = record_or_contract
    result: dict[str, Any] = {
        "market_code": JC_HANDICAP_MARKET_CODE,
        "selection_order": list(JC_HANDICAP_SELECTION_ORDER),
        "line": None,
        "actual_selection": None,
        "units": None,
        "hit": None,
        "scope": "regulation_90m_plus_stoppage",
    }
    if not isinstance(contract, Mapping):
        result["status"] = "ABSTAIN"
        result["reason"] = "MISSING_FROZEN_JC_HANDICAP"
        return result
    try:
        validate_jc_handicap_contract(contract)
    except ValueError:
        result["status"] = "FAIL_CLOSED"
        result["reason"] = "INVALID_FROZEN_JC_HANDICAP"
        return result
    if isinstance(record_or_contract, Mapping) and record_or_contract.get("exact_score_distribution") is not None:
        exact = record_or_contract.get("exact_score_distribution")
        if not isinstance(exact, Mapping):
            result["status"] = "FAIL_CLOSED"
            result["reason"] = "INVALID_FROZEN_EXACT_DISTRIBUTION"
            return result
        try:
            validate_exact_distribution_contract(exact)
        except ValueError:
            result["status"] = "FAIL_CLOSED"
            result["reason"] = "INVALID_FROZEN_EXACT_DISTRIBUTION"
            return result
        if (contract.get("underlying_exact_distribution") or {}).get("content_sha256") != exact.get("content_sha256"):
            result["status"] = "FAIL_CLOSED"
            result["reason"] = "FROZEN_EXACT_AUTHORITY_MISMATCH"
            return result
    if contract.get("served_state") != "FORMAL":
        result["status"] = "ABSTAIN"
        result["reason"] = contract.get("abstain_reason")
        return result
    if isinstance(score, Mapping):
        home, away = score.get("home_score_90m", score.get("home_score")), score.get("away_score_90m", score.get("away_score"))
    elif isinstance(score, (tuple, list)) and len(score) == 2:
        home, away = score
    else:
        result["status"] = "FAIL_CLOSED"
        result["reason"] = "INVALID_90M_SCORE"
        return result
    home, away = _goal(home), _goal(away)
    if home is None or away is None:
        result["status"] = "FAIL_CLOSED"
        result["reason"] = "INVALID_90M_SCORE"
        return result
    try:
        actual = handicap_class(home, away, contract.get("line"))
    except (TypeError, ValueError):
        result["status"] = "FAIL_CLOSED"
        result["reason"] = "INVALID_90M_SCORE"
        return result
    result.update({
        "status": "SETTLED",
        "line": int(contract["line"]),
        "actual_selection": actual,
        "units": 1.0 if actual in JC_HANDICAP_SELECTION_ORDER else None,
        "hit": True,
    })
    return result


def _empty_jc_handicap_evaluation(status: str) -> dict[str, Any]:
    return {
        "jc_handicap_evaluation_eligible": False,
        "jc_handicap_evaluation_status": status,
        "jc_handicap_line": None,
        "actual_jc_handicap_class": None,
        "jc_handicap_probability": None,
        "jc_handicap_top_selection": None,
        "jc_handicap_top_selection_hit": None,
        "jc_handicap_log_loss": None,
        "jc_handicap_brier": None,
        "jc_handicap_multiclass_brier": None,
        "jc_handicap_rps": None,
        "jc_handicap_brier_convention": JC_HANDICAP_BRIER_CONVENTION,
        "jc_handicap_rps_convention": JC_HANDICAP_RPS_CONVENTION,
        "jc_handicap_rps_denominator": JC_HANDICAP_RPS_DENOMINATOR,
        "jc_handicap_vector_order": list(JC_HANDICAP_SELECTION_ORDER),
        "jc_handicap_probability_vector": None,
        "jc_handicap_forecast_horizon": None,
        "same_time_official_market_baseline_status": JC_HANDICAP_BASELINE_STATUS,
    }


def evaluate_frozen_jc_handicap(
    record: Mapping[str, Any],
    score: tuple[int, int] | list[int] | Mapping[str, Any],
    *,
    verified_result: bool,
    formally_eligible: bool = True,
) -> dict[str, Any]:
    if not verified_result:
        return _empty_jc_handicap_evaluation("UNVERIFIED_90M_RESULT")
    if not formally_eligible:
        return _empty_jc_handicap_evaluation("NOT_FORMALLY_ELIGIBLE")
    if isinstance(score, Mapping):
        home, away = score.get("home_score_90m", score.get("home_score")), score.get("away_score_90m", score.get("away_score"))
    elif isinstance(score, (tuple, list)) and len(score) == 2:
        home, away = score
    else:
        return _empty_jc_handicap_evaluation("INVALID_90M_SCORE")
    home, away = _goal(home), _goal(away)
    if home is None or away is None:
        return _empty_jc_handicap_evaluation("INVALID_90M_SCORE")
    classified = classify_frozen_jc_handicap(record, home, away)
    if not classified["FORMAL_JC_HANDICAP_FROZEN"]:
        empty = _empty_jc_handicap_evaluation(classified["jc_handicap_status"])
        empty["same_time_official_market_baseline_status"] = classified.get("same_time_official_market_baseline_status") or JC_HANDICAP_BASELINE_STATUS
        return empty
    contract = _record_jc_handicap(record) or {}
    probabilities = contract.get("probabilities") or {}
    vector = [_number(probabilities.get(key)) for key in JC_HANDICAP_SELECTION_ORDER]
    actual = classified["actual_jc_handicap_class"]
    actual_index = JC_HANDICAP_SELECTION_ORDER.index(actual)
    if any(value is None or value < 0 for value in vector) or abs(sum(vector) - 1.0) > EXACT_DISTRIBUTION_NORMALIZATION_TOLERANCE:
        return _empty_jc_handicap_evaluation("INVALID_FROZEN_JC_HANDICAP_VECTOR")
    actual_probability = vector[actual_index]
    if actual_probability is None or actual_probability <= 0:
        return _empty_jc_handicap_evaluation("INVALID_FROZEN_JC_ACTUAL_CLASS_PROBABILITY")
    brier = sum((float(value) - float(index == actual_index)) ** 2 for index, value in enumerate(vector))
    rps = sum(
        (sum(vector[:index + 1]) - float(actual_index <= index)) ** 2
        for index in range(JC_HANDICAP_RPS_DENOMINATOR)
    ) / JC_HANDICAP_RPS_DENOMINATOR
    return {
        "jc_handicap_evaluation_eligible": True,
        "jc_handicap_evaluation_status": "ELIGIBLE_FROZEN_JC_HANDICAP",
        "jc_handicap_line": classified["official_jc_handicap_line"],
        "actual_jc_handicap_class": actual,
        "jc_handicap_probability": float(actual_probability),
        "jc_handicap_top_selection": classified["jc_handicap_top_selection"],
        "jc_handicap_top_selection_hit": classified["jc_handicap_top_selection_hit"],
        "jc_handicap_log_loss": -math.log(actual_probability),
        "jc_handicap_brier": brier,
        "jc_handicap_multiclass_brier": brier,
        "jc_handicap_rps": rps,
        "jc_handicap_brier_convention": JC_HANDICAP_BRIER_CONVENTION,
        "jc_handicap_rps_convention": JC_HANDICAP_RPS_CONVENTION,
        "jc_handicap_rps_denominator": JC_HANDICAP_RPS_DENOMINATOR,
        "jc_handicap_vector_order": list(JC_HANDICAP_SELECTION_ORDER),
        "jc_handicap_probability_vector": [float(value) for value in vector],
        "jc_handicap_forecast_horizon": deepcopy(contract.get("forecast_horizon") or {}),
        "same_time_official_market_baseline_status": JC_HANDICAP_BASELINE_STATUS,
    }


def _timestamp_range(rows: list[Mapping[str, Any]], field: str) -> dict[str, str | None]:
    values = [_parse_datetime(row.get(field)) for row in rows]
    parsed = [value for value in values if value]
    return {
        "earliest": min(parsed).isoformat(timespec="seconds") if parsed else None,
        "latest": max(parsed).isoformat(timespec="seconds") if parsed else None,
    }


def summarize_jc_handicap_evaluations(
    formal_rows: list[Mapping[str, Any]],
    *,
    minimum_sample_count: int = JC_HANDICAP_MINIMUM_SUMMARY_SAMPLE_COUNT,
) -> dict[str, Any]:
    eligible: list[Mapping[str, Any]] = []
    status_counts: Counter[str] = Counter()
    for row in formal_rows:
        metrics = row.get("metrics") if isinstance(row, Mapping) else None
        if not isinstance(metrics, Mapping):
            status_counts["MISSING_PERSISTED_JC_HANDICAP_EVALUATION"] += 1
            continue
        status_counts[str(metrics.get("jc_handicap_evaluation_status") or "MISSING_PERSISTED_JC_HANDICAP_EVALUATION")] += 1
        if (
            metrics.get("jc_handicap_evaluation_eligible") is True
            and metrics.get("actual_jc_handicap_class") in JC_HANDICAP_SELECTION_ORDER
            and metrics.get("jc_handicap_top_selection") in JC_HANDICAP_SELECTION_ORDER
            and isinstance(metrics.get("jc_handicap_top_selection_hit"), bool)
            and all(_number(metrics.get(key)) is not None for key in ("jc_handicap_log_loss", "jc_handicap_brier", "jc_handicap_rps"))
        ):
            eligible.append(row)
    eligible_count = len(eligible)
    served_count = sum(
        1
        for row in formal_rows
        if isinstance(row, Mapping)
        and isinstance(row.get("metrics"), Mapping)
        and row["metrics"].get("FORMAL_JC_HANDICAP_FROZEN") is True
    )
    predicted_counts = {key: 0 for key in JC_HANDICAP_SELECTION_ORDER}
    actual_counts = {key: 0 for key in JC_HANDICAP_SELECTION_ORDER}
    recall_hits = {key: 0 for key in JC_HANDICAP_SELECTION_ORDER}
    for row in eligible:
        metrics = row["metrics"]
        actual, predicted = metrics["actual_jc_handicap_class"], metrics["jc_handicap_top_selection"]
        actual_counts[actual] += 1
        predicted_counts[predicted] += 1
        recall_hits[actual] += int(actual == predicted)

    def mix(counts: Mapping[str, int]) -> dict[str, float | None]:
        return {key: round(value / eligible_count, 6) if eligible_count else None for key, value in counts.items()}

    metric_names = ("jc_handicap_log_loss", "jc_handicap_brier", "jc_handicap_rps")
    means = {
        name: round(sum(float(row["metrics"][name]) for row in eligible) / eligible_count, 9) if eligible_count else None
        for name in metric_names
    }
    if not formal_rows:
        coverage_status = "NO_FORMAL_SETTLED_SAMPLES"
    elif not eligible:
        coverage_status = "NO_ELIGIBLE_FROZEN_JC_SAMPLES"
    elif eligible_count < len(formal_rows):
        coverage_status = "PARTIAL_COVERAGE"
    else:
        coverage_status = "FULL_COVERAGE"
    horizons: list[float] = []
    for row in eligible:
        horizon = (row.get("metrics") or {}).get("jc_handicap_forecast_horizon") or {}
        minutes = _number(horizon.get("minutes")) if isinstance(horizon, Mapping) else None
        if minutes is not None:
            horizons.append(minutes)
    return {
        "contract_version": JC_HANDICAP_CONTRACT_VERSION,
        "status": "SUFFICIENT_SAMPLE" if eligible_count >= minimum_sample_count else "INSUFFICIENT_SAMPLE",
        "minimum_sample_count": minimum_sample_count,
        "prospective": True,
        "observation_unit": "unique football match",
        "formal_cohort_n": len(formal_rows),
        "served_n": served_count,
        "abstain_n": max(0, len(formal_rows) - served_count),
        "served_coverage": round(served_count / len(formal_rows), 6) if formal_rows else None,
        "served_full_coverage": bool(formal_rows) and served_count == len(formal_rows),
        "eligible_n": eligible_count,
        "sample_count": eligible_count,
        "evaluation_coverage": round(eligible_count / len(formal_rows), 6) if formal_rows else None,
        "coverage": round(eligible_count / len(formal_rows), 6) if formal_rows else None,
        "coverage_status": coverage_status,
        "eligibility_status_counts": dict(status_counts),
        "top1_hit_rate": round(sum(int((row["metrics"].get("jc_handicap_top_selection_hit")) is True) for row in eligible) / eligible_count, 9) if eligible_count else None,
        "mean_log_loss": means["jc_handicap_log_loss"],
        "mean_brier": means["jc_handicap_brier"],
        "mean_multiclass_brier": means["jc_handicap_brier"],
        "mean_rps": means["jc_handicap_rps"],
        "predicted_class_counts": predicted_counts,
        "actual_class_counts": actual_counts,
        "predicted_class_mix": mix(predicted_counts),
        "actual_class_mix": mix(actual_counts),
        "per_class_recall": {
            key: {
                "actual_n": actual_counts[key],
                "hits": recall_hits[key],
                "recall": round(recall_hits[key] / actual_counts[key], 9) if actual_counts[key] else None,
            }
            for key in JC_HANDICAP_SELECTION_ORDER
        },
        "chronology": {
            "prediction_created_at": _timestamp_range(eligible, "prediction_created_at"),
            "kickoff_at": _timestamp_range(eligible, "kickoff_at"),
        },
        "forecast_horizon": {
            "minimum_minutes": min(horizons) if horizons else None,
            "maximum_minutes": max(horizons) if horizons else None,
            "mean_minutes": round(sum(horizons) / len(horizons), 3) if horizons else None,
        },
        "metric_conventions": {
            "order": list(JC_HANDICAP_SELECTION_ORDER),
            "brier": JC_HANDICAP_BRIER_CONVENTION,
            "rps": JC_HANDICAP_RPS_CONVENTION,
            "rps_denominator": JC_HANDICAP_RPS_DENOMINATOR,
        },
        "same_time_official_market_baseline_status": JC_HANDICAP_BASELINE_STATUS,
    }


# Short aliases make the lane easy to discover without creating a second
# implementation surface.
parse_nowscore_jc_handicap_page = parse_nowscore_analysis_page
settle_jc_handicap_contract = settle_frozen_jc_handicap
evaluate_jc_handicap = evaluate_frozen_jc_handicap
empty_jc_handicap_evaluation = _empty_jc_handicap_evaluation
