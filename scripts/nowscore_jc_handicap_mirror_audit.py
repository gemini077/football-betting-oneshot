#!/usr/bin/env python3
"""Bounded GitHub-hosted preflight for the public Nowscore JC handicap mirror.

This is a research-only comparator.  It reads the immutable PR #203
Sporttery evidence through ``git show`` and only requests Nowscore-owned
public analysis/history pages.  It never writes production data and never
uses a fuzzy or result-assisted match resolver.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Mapping
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
UNIVERSE_ROOT = ROOT / "data" / "prediction_universe"
COMPARATOR_COMMIT = "adc289626a5235510a998d893b6dbc47a3e0fe11"
COMPARATOR_PATH = "tests/fixtures/jc_handicap/official_source_audit.json"
ANALYSIS_URL = "https://m.nowscore.com/Analy/Analysis/{nowscore_id}.htm"
HISTORY_URL = (
    "https://m.nowscore.com/Analy/JcOddsDetail?scheid={nowscore_id}&oddsType=0"
)
NOWSCORE_HOSTS = frozenset({"m.nowscore.com", "live.nowscore.com", "www.nowscore.com"})
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "Chrome/131.0.0.0 Safari/537.36"
)
SHANGHAI = ZoneInfo("Asia/Shanghai")
TIMEOUT_SECONDS = 20
MAX_RESPONSE_BYTES = 5 * 1024 * 1024
AUDIT_CONTRACT_VERSION = "nowscore_jc_handicap_mirror_audit.v1"

DELIVERY_PARITY_PROVEN = "NOWSCORE_JC_MIRROR_PARITY_PROVEN"
DELIVERY_PARITY_PARTIAL = "NOWSCORE_JC_MIRROR_PARITY_PARTIAL"
DELIVERY_NOT_EXECUTABLE = "NOWSCORE_JC_MIRROR_NOT_EXECUTABLE"
DELIVERY_FAIL_CLOSED = "FAIL_CLOSED"

_DECIMAL_RE = re.compile(r"^[0-9]+(?:\.[0-9]+)?$")
_INTEGER_LINE_RE = re.compile(r"^[+-]?[0-9]+$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TIME_RE = re.compile(r"^(\d{1,2}):(\d{2})(?::(\d{2}))?$")


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _text(value: object) -> str:
    return " ".join(str(value or "").split())


def _identity_text(value: object) -> str:
    return _text(value).casefold()


def _normalise_date(value: object) -> str | None:
    text = _text(value)
    if not _DATE_RE.fullmatch(text):
        return None
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError:
        return None


def _normalise_time(value: object) -> str | None:
    match = _TIME_RE.fullmatch(_text(value))
    if not match:
        return None
    hour, minute, second = (int(match.group(1)), int(match.group(2)), int(match.group(3) or 0))
    if hour > 23 or minute > 59 or second > 59:
        return None
    return f"{hour:02d}:{minute:02d}:{second:02d}"


def _integer_line(value: object) -> int | None:
    text = _text(value)
    if not _INTEGER_LINE_RE.fullmatch(text):
        return None
    try:
        return int(text)
    except ValueError:
        return None


def _decimal(value: object) -> Decimal | None:
    text = _text(value)
    if not _DECIMAL_RE.fullmatch(text):
        return None
    try:
        value_decimal = Decimal(text)
    except InvalidOperation:
        return None
    return value_decimal if value_decimal > 0 else None


def _display_decimal(value: Decimal | None) -> float | None:
    return float(value) if value is not None else None


def _parse_js_string(raw: str) -> str | None:
    raw = raw.strip()
    if len(raw) < 2 or raw[0] != raw[-1] or raw[0] not in "\"'":
        return None
    if raw[0] == '"':
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            value = raw[1:-1]
    else:
        value = raw[1:-1].replace("\\'", "'").replace('\\"', '"')
    return unescape(str(value))


def _parse_comparator_timestamp(raw_row: Mapping[str, object]) -> datetime | None:
    raw_date = _normalise_date(raw_row.get("updateDate"))
    raw_time = _normalise_time(raw_row.get("updateTime"))
    if raw_date is None or raw_time is None:
        return None
    try:
        return datetime.fromisoformat(f"{raw_date}T{raw_time}").replace(tzinfo=SHANGHAI)
    except ValueError:
        return None


def _parse_history_timestamp(value: object) -> datetime | None:
    text = _text(value)
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(SHANGHAI)


def _git_show_json(ref: str, path: str, repo_root: Path) -> tuple[dict[str, Any], str]:
    resolved = subprocess.run(
        ["git", "rev-parse", f"{ref}^{{commit}}"],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
    )
    commit = resolved.stdout.strip()
    if resolved.returncode != 0 or commit != COMPARATOR_COMMIT:
        raise ValueError(
            f"fixed comparator ref mismatch: expected {COMPARATOR_COMMIT}, got {commit or 'UNRESOLVED'}"
        )
    shown = subprocess.run(
        ["git", "show", f"{ref}:{path}"],
        cwd=repo_root,
        check=False,
        capture_output=True,
    )
    if shown.returncode != 0:
        raise ValueError(f"fixed comparator path unavailable: {path}")
    try:
        value = json.loads(shown.stdout.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"fixed comparator JSON invalid: {error}") from error
    if not isinstance(value, dict):
        raise ValueError("fixed comparator root is not an object")
    return value, commit


def _require_identity_match(parsed: Mapping[str, object], raw: Mapping[str, object]) -> None:
    raw_values = {
        "businessDate": raw.get("businessDate"),
        "matchNum": raw.get("matchNumStr"),
        "homeTeam": raw.get("homeTeamAbbName"),
        "awayTeam": raw.get("awayTeamAbbName"),
        "matchDate": raw.get("matchDate"),
        "matchTime": raw.get("matchTime"),
    }
    parsed_values = {
        "businessDate": parsed.get("businessDate"),
        "matchNum": parsed.get("matchNum"),
        "homeTeam": parsed.get("homeTeam"),
        "awayTeam": parsed.get("awayTeam"),
        "matchDate": parsed.get("matchDate"),
        "matchTime": parsed.get("matchTime"),
    }
    for key, raw_value in raw_values.items():
        parsed_value = parsed_values[key]
        if key == "matchTime":
            raw_normalised = _normalise_time(raw_value)
            parsed_normalised = _normalise_time(parsed_value)
        elif key in {"businessDate", "matchDate"}:
            raw_normalised = _normalise_date(raw_value)
            parsed_normalised = _normalise_date(parsed_value)
        else:
            raw_normalised = _identity_text(raw_value)
            parsed_normalised = _identity_text(parsed_value)
        if raw_normalised is None or raw_normalised != parsed_normalised:
            raise ValueError(f"fixed comparator parsed/raw identity mismatch: {key}")


def _load_fixed_comparator(
    ref: str = COMPARATOR_COMMIT,
    *,
    repo_root: Path = ROOT,
) -> dict[str, Any]:
    payload, commit = _git_show_json(ref, COMPARATOR_PATH, repo_root)
    audit = payload.get("audit")
    if not isinstance(audit, dict):
        raise ValueError("fixed comparator audit object missing")
    target_date = _normalise_date(audit.get("target_business_date"))
    if target_date is None:
        raise ValueError("fixed comparator business date invalid")
    if audit.get("market_identity") != "JC_HANDICAP_1X2":
        raise ValueError("fixed comparator market identity mismatch")
    evidence_rows = audit.get("evidence_rows")
    if not isinstance(evidence_rows, list) or not evidence_rows:
        raise ValueError("fixed comparator evidence rows missing")

    rows: list[dict[str, Any]] = []
    for index, evidence in enumerate(evidence_rows):
        if not isinstance(evidence, dict):
            raise ValueError(f"fixed comparator row {index} is not an object")
        raw_row = evidence.get("raw_row")
        parsed = evidence.get("parsed")
        if not isinstance(raw_row, dict) or not isinstance(parsed, dict):
            raise ValueError(f"fixed comparator row {index} missing raw/parsed fields")
        expected_hash = _text(evidence.get("raw_row_sha256"))
        actual_hash = hashlib.sha256(_canonical_json(raw_row)).hexdigest()
        if not expected_hash or expected_hash != actual_hash:
            raise ValueError(f"fixed comparator row {index} raw hash mismatch")
        _require_identity_match(parsed, raw_row)
        hhad = raw_row.get("hhad")
        if not isinstance(hhad, dict):
            raise ValueError(f"fixed comparator row {index} hhad missing")
        line = _integer_line(hhad.get("goalLine"))
        odds = {
            "home": _decimal(hhad.get("h")),
            "draw": _decimal(hhad.get("d")),
            "away": _decimal(hhad.get("a")),
        }
        if line is None or any(value is None for value in odds.values()):
            raise ValueError(f"fixed comparator row {index} has invalid integer line or odds")
        match_id = _text(raw_row.get("matchId"))
        if not match_id.isdigit() or int(match_id) <= 0:
            raise ValueError(f"fixed comparator row {index} match id invalid")
        parsed_rqspf = parsed.get("rqspf")
        if not isinstance(parsed_rqspf, dict):
            raise ValueError(f"fixed comparator row {index} parsed rqspf missing")
        if _integer_line(parsed_rqspf.get("handicap")) != line:
            raise ValueError(f"fixed comparator row {index} parsed line mismatch")
        for key, value in odds.items():
            if _decimal(parsed_rqspf.get(key)) != value:
                raise ValueError(f"fixed comparator row {index} parsed {key} mismatch")
        rows.append({
            "business_date": target_date,
            "sporttery_match_id": int(match_id),
            "match_num": _text(raw_row.get("matchNumStr")),
            "home_team": _text(raw_row.get("homeTeamAbbName")),
            "away_team": _text(raw_row.get("awayTeamAbbName")),
            "match_date": _normalise_date(raw_row.get("matchDate")),
            "match_time": _normalise_time(raw_row.get("matchTime")),
            "goal_line": line,
            "odds": {key: _display_decimal(value) for key, value in odds.items()},
            "odds_decimal": odds,
            "raw_row": raw_row,
            "raw_row_sha256": expected_hash,
        })
    return {
        "source_ref": {"commit": commit, "path": COMPARATOR_PATH},
        "business_date": target_date,
        "official_rows_returned": audit.get("official_rows_returned"),
        "delivery_decision": audit.get("delivery_decision"),
        "rows": rows,
    }


def _load_universe(target_date: str, *, repo_root: Path = ROOT) -> tuple[dict[str, Any], str]:
    path = repo_root / "data" / "prediction_universe" / f"{target_date}.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"prediction universe unavailable for fixed comparator date: {error}") from error
    if not isinstance(value, dict):
        raise ValueError("prediction universe root is not an object")
    if _normalise_date(value.get("business_date")) != target_date:
        raise ValueError("prediction universe business date mismatch")
    if str(value.get("status") or "").upper() not in {"READY", "EMPTY_CONFIRMED"}:
        raise ValueError("prediction universe is not authoritative")
    if value.get("source") != "nowscore_public_jc":
        raise ValueError("prediction universe source is not Nowscore public JC")
    try:
        path_ref = path.relative_to(repo_root).as_posix()
    except ValueError:
        path_ref = path.as_posix()
    return value, path_ref


def _fixture_identity_key(fixture: Mapping[str, object]) -> tuple[str, ...] | None:
    business_date = _normalise_date(fixture.get("businessDate") or fixture.get("business_date"))
    match_date = _normalise_date(fixture.get("matchDate") or fixture.get("match_date"))
    match_time = _normalise_time(fixture.get("matchTime") or fixture.get("match_time"))
    values = (
        business_date,
        _identity_text(fixture.get("matchNum") or fixture.get("match_num")),
        _identity_text(fixture.get("homeTeam") or fixture.get("home_team")),
        _identity_text(fixture.get("awayTeam") or fixture.get("away_team")),
        match_date,
        match_time,
    )
    return values if all(value not in (None, "") for value in values) else None


def _comparator_identity_key(row: Mapping[str, object]) -> tuple[str, ...] | None:
    return _fixture_identity_key({
        "businessDate": row.get("business_date"),
        "matchNum": row.get("match_num"),
        "homeTeam": row.get("home_team"),
        "awayTeam": row.get("away_team"),
        "matchDate": row.get("match_date"),
        "matchTime": row.get("match_time"),
    })


def _positive_int(value: object) -> int | None:
    text = _text(value)
    if not text.isdigit():
        return None
    parsed = int(text)
    return parsed if parsed > 0 else None


def _fixture_nowscore_id(fixture: Mapping[str, object]) -> tuple[int | None, list[str]]:
    reasons: list[str] = []
    direct = _positive_int(fixture.get("nowscore_id") or fixture.get("nowscoreId"))
    alternate = _positive_int(fixture.get("nowscoreId"))
    if direct is None or alternate is None:
        reasons.append("NOWSCORE_ID_UNAVAILABLE")
    elif direct != alternate:
        reasons.append("NOWSCORE_ID_FIELD_CONFLICT")
    evidence = fixture.get("jc_membership_evidence")
    evidence_id = _positive_int(evidence.get("nowscore_id") if isinstance(evidence, dict) else None)
    if evidence_id is None:
        reasons.append("JC_MEMBERSHIP_EVIDENCE_ID_UNAVAILABLE")
    elif direct is not None and evidence_id != direct:
        reasons.append("JC_MEMBERSHIP_EVIDENCE_ID_CONFLICT")
    if fixture.get("jc_membership") != "VERIFIED":
        reasons.append("JC_MEMBERSHIP_NOT_VERIFIED")
    if fixture.get("jc_membership_source") != "nowscore_public_jc_sales":
        reasons.append("JC_MEMBERSHIP_SOURCE_CONFLICT")
    if fixture.get("nowscoreMatchStatus") != "EXACT_MATCH":
        reasons.append("NOWSCORE_IDENTITY_NOT_EXACT")
    return direct, list(dict.fromkeys(reasons))


def bind_fixed_comparator(
    comparator: Mapping[str, object],
    universe: Mapping[str, object],
    *,
    universe_path: str = "data/prediction_universe/UNRESOLVED.json",
) -> dict[str, Any]:
    rows = comparator.get("rows") if isinstance(comparator, dict) else None
    fixtures = universe.get("fixtures") if isinstance(universe, dict) else None
    if not isinstance(rows, list) or not isinstance(fixtures, list):
        return {
            "status": "UNAVAILABLE",
            "universe_path": universe_path,
            "comparator_n": len(rows) if isinstance(rows, list) else 0,
            "jc_fixtures": 0,
            "exact_deterministic_identity_n": 0,
            "ambiguous": 0,
            "unmatched": 0,
            "duplicates": 0,
            "conflicts": 1,
            "rows": [],
        }

    fixture_keys: dict[tuple[str, ...], list[dict[str, object]]] = {}
    valid_fixtures: list[dict[str, object]] = []
    for fixture in fixtures:
        if not isinstance(fixture, dict):
            continue
        valid_fixtures.append(fixture)
        key = _fixture_identity_key(fixture)
        if key is not None:
            fixture_keys.setdefault(key, []).append(fixture)
    nowscore_ids = [
        _fixture_nowscore_id(fixture)[0]
        for fixture in valid_fixtures
        if _fixture_nowscore_id(fixture)[0] is not None
    ]
    duplicate_id_count = sum(count - 1 for count in Counter(nowscore_ids).values() if count > 1)
    duplicate_key_count = sum(max(0, len(group) - 1) for group in fixture_keys.values())

    result_rows: list[dict[str, Any]] = []
    exact = ambiguous = unmatched = conflicts = 0
    for comparator_row in rows:
        if not isinstance(comparator_row, dict):
            conflicts += 1
            result_rows.append({"status": "CONFLICT", "reasons": ["INVALID_COMPARATOR_ROW"]})
            continue
        key = _comparator_identity_key(comparator_row)
        candidates = fixture_keys.get(key, []) if key is not None else []
        base = {
            "sporttery_match_id": comparator_row.get("sporttery_match_id"),
            "match_num": comparator_row.get("match_num"),
            "home_team": comparator_row.get("home_team"),
            "away_team": comparator_row.get("away_team"),
            "kickoff": f"{comparator_row.get('match_date')}T{comparator_row.get('match_time')}",
            "goal_line": comparator_row.get("goal_line"),
            "official_odds": comparator_row.get("odds"),
            "raw_row": comparator_row.get("raw_row"),
            "raw_row_sha256": comparator_row.get("raw_row_sha256"),
            "candidate_n": len(candidates),
        }
        if len(candidates) == 0:
            unmatched += 1
            result_rows.append({**base, "status": "UNMATCHED", "reasons": ["NO_EXACT_UNIVERSE_IDENTITY"]})
            continue
        if len(candidates) > 1:
            ambiguous += 1
            result_rows.append({**base, "status": "AMBIGUOUS", "reasons": ["MULTIPLE_EXACT_UNIVERSE_IDENTITIES"]})
            continue
        fixture = candidates[0]
        nowscore_id, provenance_reasons = _fixture_nowscore_id(fixture)
        if provenance_reasons:
            conflicts += 1
            result_rows.append({
                **base,
                "status": "CONFLICT",
                "nowscore_id": nowscore_id,
                "reasons": provenance_reasons,
            })
            continue
        exact += 1
        result_rows.append({
            **base,
            "status": "EXACT_MATCH",
            "nowscore_id": nowscore_id,
            "fixture_source_surface": fixture.get("source_surface"),
            "fixture_fetched_at": fixture.get("fetched_at"),
        })
    return {
        "status": "AVAILABLE",
        "universe_path": universe_path,
        "comparator_n": len(rows),
        "jc_fixtures": len(valid_fixtures),
        "exact_deterministic_identity_n": exact,
        "ambiguous": ambiguous,
        "unmatched": unmatched,
        "duplicates": duplicate_id_count + duplicate_key_count,
        "duplicate_nowscore_id_n": duplicate_id_count,
        "duplicate_identity_key_n": duplicate_key_count,
        "conflicts": conflicts,
        "rows": result_rows,
    }


class _JcAnalysisParser(HTMLParser):
    """Extract the explicit mobile ``竞彩指数`` table only."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.div_depth = 0
        self.header_depth: int | None = None
        self.header_text: list[str] = []
        self.header_open = False
        self.section_active = False
        self.rows: list[dict[str, Any]] = []
        self.current_row: dict[str, Any] | None = None
        self.current_cell: dict[str, Any] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "div":
            classes = set(_text(attributes.get("class")).split())
            if "fenxiBar" in classes:
                self.section_active = False
                self.header_open = True
                self.header_depth = self.div_depth
                self.header_text = []
            self.div_depth += 1
        if tag == "tr" and self.section_active and self.current_row is None:
            onclick = _text(attributes.get("onclick"))
            matched = re.search(r"GoJcUrl\s*\(\s*([01])\s*\)", onclick, re.I)
            if matched:
                self.current_row = {
                    "odds_type": int(matched.group(1)),
                    "cells": [],
                }
        if self.current_row is not None and tag in {"td", "th"} and self.current_cell is None:
            self.current_cell = {
                "text": [],
                "first_quote": "firstOdds" in set(_text(attributes.get("class")).split()),
            }

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
            self.current_row["cells"].append({
                "value": _text("".join(self.current_cell["text"])),
                "first_quote": bool(self.current_cell["first_quote"]),
            })
            self.current_cell = None
        elif tag == "tr" and self.current_row is not None:
            self.rows.append(self.current_row)
            self.current_row = None
        if tag == "div":
            if self.header_open and self.header_depth is not None and self.div_depth == self.header_depth + 1:
                header = _text("".join(self.header_text))
                self.section_active = "竞彩指数" in header
                self.header_open = False
                self.header_depth = None
            self.div_depth = max(0, self.div_depth - 1)


def _page_identity(html: str) -> dict[str, Any]:
    def js_value(name: str) -> str | None:
        match = re.search(
            rf"\b(?:var\s+)?{re.escape(name)}\s*=\s*(\"(?:\\.|[^\"])*\"|'(?:\\.|[^'])*')",
            html,
            re.I,
        )
        return _parse_js_string(match.group(1)) if match else None

    def numeric_value(name: str) -> int | None:
        match = re.search(rf"\b(?:var\s+)?{re.escape(name)}\s*=\s*(\d+)", html, re.I)
        return int(match.group(1)) if match else None

    schedule_id = numeric_value("scheduleId")
    timestamp = numeric_value("MatchTimeStamp") or numeric_value("matchTimeStamp")
    kickoff = None
    if timestamp is not None:
        try:
            kickoff = datetime.fromtimestamp(timestamp / 1000, timezone.utc).astimezone(SHANGHAI)
        except (OverflowError, OSError, ValueError):
            kickoff = None
    return {
        "nowscore_id": schedule_id,
        "home_team": js_value("homeTeam"),
        "away_team": js_value("guestTeam") or js_value("awayTeam"),
        "kickoff_local": kickoff.isoformat(timespec="seconds") if kickoff else None,
        "kickoff_date": kickoff.date().isoformat() if kickoff else None,
        "kickoff_time": kickoff.time().replace(microsecond=0).isoformat() if kickoff else None,
        "timestamp_source": "MatchTimeStamp" if timestamp is not None else None,
    }


def parse_nowscore_analysis_page(html: str, *, expected_nowscore_id: int | None = None) -> dict[str, Any]:
    parser = _JcAnalysisParser()
    parser.feed(html)
    identity = _page_identity(html)
    if expected_nowscore_id is not None and identity.get("nowscore_id") != expected_nowscore_id:
        identity_status = "CONFLICT"
    else:
        identity_status = "EXACT_ID" if identity.get("nowscore_id") else "UNAVAILABLE"
    parsed_rows: list[dict[str, Any]] = []
    for raw_row in parser.rows:
        cells = raw_row.get("cells") or []
        values = [cell.get("value") for cell in cells]
        line = _integer_line(values[0]) if raw_row.get("odds_type") == 0 and values else None
        first_cells = [cell for cell in cells[1:4] if cell.get("first_quote")]
        current_cells = [cell for cell in cells[4:7] if not cell.get("first_quote")]
        first_quote = (
            {"home": _decimal(first_cells[0].get("value")), "draw": _decimal(first_cells[1].get("value")), "away": _decimal(first_cells[2].get("value"))}
            if len(first_cells) == 3 else None
        )
        current_quote = (
            {"home": _decimal(current_cells[0].get("value")), "draw": _decimal(current_cells[1].get("value")), "away": _decimal(current_cells[2].get("value"))}
            if len(current_cells) == 3 else None
        )
        history_url = None
        if raw_row.get("odds_type") == 0 and identity.get("nowscore_id"):
            history_url = HISTORY_URL.format(nowscore_id=identity["nowscore_id"])
        parsed_rows.append({
            "odds_type": raw_row.get("odds_type"),
            "line": line,
            "first_quote": {key: _display_decimal(value) for key, value in (first_quote or {}).items()} if first_quote else None,
            "current_quote": {key: _display_decimal(value) for key, value in (current_quote or {}).items()} if current_quote else None,
            "first_quote_complete": bool(first_quote and all(value is not None for value in first_quote.values())),
            "current_quote_complete": bool(current_quote and all(value is not None for value in current_quote.values())),
            "history_url": history_url,
            "cell_values": values,
        })
    handicap_rows = [row for row in parsed_rows if row.get("odds_type") == 0]
    return {
        "section_found": bool(parser.rows),
        "identity": identity,
        "identity_status": identity_status,
        "rows": parsed_rows,
        "handicap_rows": handicap_rows,
        "history_url": next((row.get("history_url") for row in handicap_rows if row.get("history_url")), None),
        "temporal_semantics": {
            "page_first_quote_label": "firstOdds CSS class",
            "page_current_quote_label": "cells without firstOdds class",
            "history_corroboration_required": True,
            "status": "PENDING_HISTORY",
        },
    }


def _parse_history_object(html: str) -> dict[str, Any] | None:
    match = re.search(r"\bjcOddsData\s*=\s*(\{.*?\})\s*;", html, re.S)
    if not match:
        return None
    try:
        value = json.loads(match.group(1))
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def parse_nowscore_history_page(html: str, *, expected_nowscore_id: int | None = None) -> dict[str, Any]:
    payload = _parse_history_object(html)
    if payload is None:
        return {
            "payload_status": "UNAVAILABLE",
            "nowscore_id": None,
            "rows": [],
            "identity_status": "UNAVAILABLE",
        }
    raw_id = payload.get("scheduleId")
    nowscore_id = _positive_int(raw_id)
    identity_status = "EXACT_ID" if nowscore_id and nowscore_id == expected_nowscore_id else "CONFLICT"
    rows: list[dict[str, Any]] = []
    details = payload.get("jcOddsDetails")
    for detail in details if isinstance(details, list) else []:
        if not isinstance(detail, dict):
            continue
        rows.append({
            "line": _integer_line(detail.get("rf")),
            "odds": {
                "home": _display_decimal(_decimal(detail.get("win"))),
                "draw": _display_decimal(_decimal(detail.get("draw"))),
                "away": _display_decimal(_decimal(detail.get("lose"))),
            },
            "change_time": detail.get("changeTime"),
            "change_time_local": (
                _parse_history_timestamp(detail.get("changeTime")).isoformat(timespec="seconds")
                if _parse_history_timestamp(detail.get("changeTime")) else None
            ),
        })
    return {
        "payload_status": "AVAILABLE",
        "nowscore_id": nowscore_id,
        "rows": rows,
        "identity_status": identity_status,
        "type": payload.get("type", "JcHandicap"),
    }


def _same_quote(left: Mapping[str, object] | None, right: Mapping[str, object] | None) -> bool:
    if not isinstance(left, Mapping) or not isinstance(right, Mapping):
        return False
    return all(_decimal(left.get(key)) == _decimal(right.get(key)) for key in ("home", "draw", "away"))


def _history_quote_matches(
    comparator_row: Mapping[str, Any],
    history: Mapping[str, Any] | None,
) -> tuple[bool, bool, str]:
    if not isinstance(history, Mapping) or history.get("payload_status") != "AVAILABLE":
        return False, False, "HISTORY_UNAVAILABLE"
    matching = [
        row for row in history.get("rows", [])
        if isinstance(row, Mapping)
        and row.get("line") == comparator_row.get("goal_line")
        and _same_quote(
            row.get("odds"),
            comparator_row.get("official_odds") or comparator_row.get("odds"),
        )
    ]
    if not matching:
        return False, False, "QUOTE_VALUE_NOT_FOUND_IN_HISTORY"
    comparator_time = _parse_comparator_timestamp(comparator_row.get("raw_row", {}).get("hhad", {}))
    if comparator_time is None:
        return True, False, "COMPARATOR_UPDATE_TIME_UNAVAILABLE"
    for row in matching:
        history_time = _parse_history_timestamp(row.get("change_time"))
        if history_time is not None and history_time == comparator_time:
            return True, True, "EXACT_HISTORY_TIMESTAMP"
    return True, False, "HISTORY_VALUE_MATCH_TIMESTAMP_UNRESOLVED"


def _safe_nowscore_url(url: str) -> bool:
    parsed = urllib.parse.urlsplit(url)
    return parsed.scheme == "https" and parsed.hostname in NOWSCORE_HOSTS


def _fetch(url: str) -> tuple[dict[str, Any], bytes]:
    if not _safe_nowscore_url(url):
        return {
            "url": url,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "http_status": None,
            "response_bytes": 0,
            "response_sha256": None,
            "success": False,
            "error": "URL_NOT_Nowscore_OWNED",
        }, b""
    started = time.monotonic()
    result: dict[str, Any] = {
        "url": url,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "http_status": None,
        "response_bytes": 0,
        "response_sha256": None,
        "success": False,
        "error": None,
    }
    body = b""
    try:
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
                "Accept-Encoding": "identity",
                "Referer": "https://m.nowscore.com/",
                "Cache-Control": "no-cache",
            },
        )
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            result["http_status"] = int(response.getcode())
            body = response.read(MAX_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError as error:
        result["http_status"] = int(error.code)
        result["error"] = f"HTTPError: {error}"
        try:
            body = error.read(MAX_RESPONSE_BYTES + 1)
        except OSError:
            body = b""
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        result["error"] = f"{type(error).__name__}: {error}"
    if len(body) > MAX_RESPONSE_BYTES:
        result["error"] = "RESPONSE_TOO_LARGE"
        body = b""
    result["response_bytes"] = len(body)
    result["response_sha256"] = hashlib.sha256(body).hexdigest() if body else None
    result["duration_ms"] = round((time.monotonic() - started) * 1000, 1)
    result["success"] = result["http_status"] == 200 and bool(body)
    return result, body


def _decode(raw: bytes) -> str:
    for encoding in ("utf-8", "gb18030"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _identity_conflict(
    bound: Mapping[str, Any],
    page: Mapping[str, Any],
    fixture: Mapping[str, object] | None,
) -> list[str]:
    reasons: list[str] = []
    identity = page.get("identity") if isinstance(page.get("identity"), Mapping) else {}
    expected_id = _positive_int(bound.get("nowscore_id"))
    if expected_id is None or identity.get("nowscore_id") != expected_id:
        reasons.append("PAGE_NOWSCORE_ID_CONFLICT")
    if not isinstance(fixture, Mapping):
        return reasons
    expected_home = _identity_text(fixture.get("homeTeam"))
    expected_away = _identity_text(fixture.get("awayTeam"))
    if expected_home and _identity_text(identity.get("home_team")) != expected_home:
        reasons.append("PAGE_HOME_TEAM_CONFLICT")
    if expected_away and _identity_text(identity.get("away_team")) != expected_away:
        reasons.append("PAGE_AWAY_TEAM_CONFLICT")
    expected_date = _normalise_date(fixture.get("matchDate"))
    expected_time = _normalise_time(fixture.get("matchTime"))
    if identity.get("kickoff_date") != expected_date or identity.get("kickoff_time") != expected_time:
        reasons.append("PAGE_KICKOFF_CONFLICT")
    return reasons


def _decide_delivery(
    *,
    binding: Mapping[str, Any],
    rows: list[Mapping[str, Any]],
    page_success_n: int,
    blocked_n: int,
    semantic_conflict: bool,
) -> str:
    if semantic_conflict or binding.get("conflicts"):
        return DELIVERY_FAIL_CLOSED
    if blocked_n or (binding.get("exact_deterministic_identity_n", 0) and page_success_n == 0):
        return DELIVERY_NOT_EXECUTABLE
    exact_n = int(binding.get("exact_deterministic_identity_n") or 0)
    line_available_n = sum(1 for row in rows if row.get("line_status") == "AVAILABLE")
    line_parity_n = sum(1 for row in rows if row.get("line_parity") == "MATCH")
    comparator_n = int(binding.get("comparator_n") or 0)
    if (
        exact_n == comparator_n
        and comparator_n > 0
        and page_success_n == comparator_n
        and line_available_n == comparator_n
        and line_parity_n == comparator_n
    ):
        return DELIVERY_PARITY_PROVEN
    return DELIVERY_PARITY_PARTIAL


def _status_counts(probes: list[Mapping[str, Any]]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for probe in probes:
        status = probe.get("http_status")
        counts[str(status) if status is not None else "NETWORK_ERROR"] += 1
    return dict(sorted(counts.items()))


def _representative_row(row: Mapping[str, Any]) -> dict[str, Any]:
    keys = (
        "sporttery_match_id", "match_num", "home_team", "away_team", "nowscore_id",
        "page_http_status", "history_http_status", "page_response_sha256",
        "history_response_sha256", "page_identity_status", "line_status",
        "line_parity", "quote_value_parity", "quote_time_status", "reasons",
    )
    return {key: row.get(key) for key in keys if key in row}


def run_audit(
    *,
    comparator_ref: str = COMPARATOR_COMMIT,
    repo_root: Path = ROOT,
) -> dict[str, Any]:
    captured_at = datetime.now(timezone.utc).isoformat()
    try:
        comparator = _load_fixed_comparator(comparator_ref, repo_root=repo_root)
        universe, universe_path = _load_universe(comparator["business_date"], repo_root=repo_root)
        binding = bind_fixed_comparator(comparator, universe, universe_path=universe_path)
    except Exception as error:
        return {
            "audit_contract_version": AUDIT_CONTRACT_VERSION,
            "probe_policy": "Nowscore-owned public analysis/history only; fixed PR #203 comparator; no Sporttery request; no fallback; no production writes",
            "runner": {"platform": platform.platform(), "python": sys.version.split()[0]},
            "comparator": {"commit": COMPARATOR_COMMIT, "path": COMPARATOR_PATH},
            "business_date": None,
            "binding": {"status": "UNAVAILABLE", "conflicts": 1},
            "delivery_decision": DELIVERY_FAIL_CLOSED,
            "error": f"{type(error).__name__}: {error}",
            "captured_at": captured_at,
        }

    # The binding row carries the exact identity; use an explicit key lookup
    # rather than relying on list order when validating the page identity.
    fixture_by_identity = {
        _fixture_identity_key(fixture): fixture
        for fixture in universe.get("fixtures", [])
        if isinstance(fixture, dict) and _fixture_identity_key(fixture) is not None
    }

    page_probes: list[dict[str, Any]] = []
    history_probes: list[dict[str, Any]] = []
    evidence_rows: list[dict[str, Any]] = []
    blocked_n = 0
    semantic_conflict = False
    for bound in binding.get("rows", []):
        if not isinstance(bound, dict):
            continue
        if bound.get("status") != "EXACT_MATCH":
            evidence_rows.append({**bound, "line_status": "NOT_ATTEMPTED"})
            continue
        nowscore_id = _positive_int(bound.get("nowscore_id"))
        page_url = ANALYSIS_URL.format(nowscore_id=nowscore_id)
        page_probe, page_body = _fetch(page_url)
        page_probes.append(page_probe)
        if page_probe.get("http_status") != 200:
            if page_probe.get("http_status") in {403, 429, 500, 502, 503, 504, 567} or page_probe.get("error"):
                blocked_n += 1
            evidence_rows.append({
                **bound,
                "page_url": page_url,
                "page_http_status": page_probe.get("http_status"),
                "page_fetched_at": page_probe.get("fetched_at"),
                "page_response_sha256": page_probe.get("response_sha256"),
                "line_status": "NOT_AVAILABLE",
                "line_parity": "UNRESOLVED",
                "quote_time_status": "UNRESOLVED_PAGE_UNAVAILABLE",
                "reasons": [page_probe.get("error") or "PAGE_HTTP_NOT_200"],
            })
            continue
        page = parse_nowscore_analysis_page(_decode(page_body), expected_nowscore_id=nowscore_id)
        identity_key = _comparator_identity_key(bound)
        fixture = fixture_by_identity.get(identity_key)
        identity_reasons = _identity_conflict(bound, page, fixture)
        if identity_reasons:
            semantic_conflict = True
        handicap_rows = page.get("handicap_rows") or []
        if len(handicap_rows) != 1:
            semantic_conflict = semantic_conflict or len(handicap_rows) > 1
        handicap = handicap_rows[0] if len(handicap_rows) == 1 else {}
        if handicap.get("line") is None:
            line_status = "NOT_AVAILABLE"
            line_parity = "UNRESOLVED"
        else:
            line_status = "AVAILABLE"
            line_parity = "MATCH" if handicap.get("line") == bound.get("goal_line") else "MISMATCH"
            if line_parity == "MISMATCH":
                semantic_conflict = True
        history_probe: dict[str, Any] = {
            "url": page.get("history_url"),
            "http_status": None,
            "fetched_at": None,
            "response_sha256": None,
            "success": False,
            "error": "HISTORY_LINK_UNAVAILABLE",
        }
        history: dict[str, Any] | None = None
        if page.get("history_url"):
            history_probe, history_body = _fetch(str(page["history_url"]))
            history_probes.append(history_probe)
            if history_probe.get("http_status") == 200:
                history = parse_nowscore_history_page(_decode(history_body), expected_nowscore_id=nowscore_id)
                if history.get("identity_status") == "CONFLICT":
                    semantic_conflict = True
        comparator_odds = bound.get("official_odds")
        page_quote = handicap.get("first_quote")
        quote_value_parity = _same_quote(page_quote, comparator_odds)
        history_value_match, history_time_resolved, history_time_reason = _history_quote_matches(bound, history)
        if history_time_resolved:
            quote_time_status = "RESOLVED_EXACT_TIMESTAMP"
        elif history_value_match:
            quote_time_status = "UNRESOLVED_TIMESTAMP"
        elif history_probe.get("http_status") == 200:
            quote_time_status = "UNRESOLVED_HISTORY_SEMANTICS"
        else:
            quote_time_status = "UNRESOLVED_HISTORY_UNAVAILABLE"
        evidence_rows.append({
            **bound,
            "page_url": page_url,
            "page_http_status": page_probe.get("http_status"),
            "page_fetched_at": page_probe.get("fetched_at"),
            "page_response_sha256": page_probe.get("response_sha256"),
            "page_identity": page.get("identity"),
            "page_identity_status": "CONFLICT" if identity_reasons else page.get("identity_status"),
            "history_url": page.get("history_url"),
            "history_http_status": history_probe.get("http_status"),
            "history_fetched_at": history_probe.get("fetched_at"),
            "history_response_sha256": history_probe.get("response_sha256"),
            "line_status": line_status,
            "nowscore_line": handicap.get("line"),
            "line_parity": line_parity,
            "nowscore_first_quote": page_quote,
            "nowscore_current_quote": handicap.get("current_quote"),
            "quote_value_parity": "MATCH" if quote_value_parity or history_value_match else "UNRESOLVED",
            "quote_time_status": quote_time_status,
            "history_quote_time_reason": history_time_reason,
            "reasons": identity_reasons,
        })

    page_success_n = sum(1 for probe in page_probes if probe.get("success"))
    line_available_n = sum(1 for row in evidence_rows if row.get("line_status") == "AVAILABLE")
    line_parity_n = sum(1 for row in evidence_rows if row.get("line_parity") == "MATCH")
    line_mismatch_n = sum(1 for row in evidence_rows if row.get("line_parity") == "MISMATCH")
    quote_resolved_n = sum(1 for row in evidence_rows if row.get("quote_time_status") == "RESOLVED_EXACT_TIMESTAMP")
    quote_unresolved_n = sum(1 for row in evidence_rows if str(row.get("quote_time_status") or "").startswith("UNRESOLVED"))
    delivery = _decide_delivery(
        binding=binding,
        rows=evidence_rows,
        page_success_n=page_success_n,
        blocked_n=blocked_n,
        semantic_conflict=semantic_conflict,
    )
    return {
        "audit_contract_version": AUDIT_CONTRACT_VERSION,
        "probe_policy": "Nowscore-owned public analysis/history only; fixed PR #203 comparator; no Sporttery request; no fallback; no production writes",
        "runner": {"platform": platform.platform(), "python": sys.version.split()[0]},
        "comparator": {
            **comparator.get("source_ref", {}),
            "business_date": comparator.get("business_date"),
            "comparator_n": binding.get("comparator_n"),
            "official_rows_returned_in_fixture": comparator.get("official_rows_returned"),
            "fixture_delivery_decision": comparator.get("delivery_decision"),
        },
        "business_date": {
            "requested": comparator.get("business_date"),
            "source": "fixed PR #203 comparator audit.target_business_date",
            "prediction_universe_path": binding.get("universe_path"),
        },
        "nowscore_surface": {
            "analysis_surface": "m.nowscore.com/Analy/Analysis/{nowscore_id}.htm",
            "jc_section": "竞彩指数",
            "handicap_row_binding": "GoJcUrl(0) integer line only",
            "history_surface": "m.nowscore.com/Analy/JcOddsDetail?scheid={nowscore_id}&oddsType=0",
            "generic_asian_handicap_used": False,
        },
        "http_coverage": {
            "analysis_pages_attempted": len(page_probes),
            "analysis_pages_success": page_success_n,
            "analysis_pages_failed": len(page_probes) - page_success_n,
            "analysis_status_counts": _status_counts(page_probes),
            "history_pages_attempted": len(history_probes),
            "history_pages_success": sum(1 for probe in history_probes if probe.get("success")),
            "history_pages_failed": sum(1 for probe in history_probes if not probe.get("success")),
            "history_status_counts": _status_counts(history_probes),
            "blocked_or_network_failure_n": blocked_n,
        },
        "binding_funnel": binding,
        "line_parity": {
            "comparator_n": binding.get("comparator_n"),
            "line_available_n": line_available_n,
            "parity_n": line_parity_n,
            "mismatch_n": line_mismatch_n,
            "status": "COMPLETE" if line_parity_n == binding.get("comparator_n") and binding.get("comparator_n") else "PARTIAL",
        },
        "quote_time_semantics": {
            "quote_value_parity_n": sum(1 for row in evidence_rows if row.get("quote_value_parity") == "MATCH"),
            "time_resolved_n": quote_resolved_n,
            "time_unresolved_n": quote_unresolved_n,
            "status": "RESOLVED" if quote_unresolved_n == 0 and quote_resolved_n else "UNRESOLVED",
            "rule": "Only an exact Nowscore JC history changeTime equal to the frozen comparator update timestamp resolves quote time; displayed first/current position alone does not",
        },
        "ambiguity_conflict": {
            "ambiguous_n": binding.get("ambiguous"),
            "unmatched_n": binding.get("unmatched"),
            "duplicate_n": binding.get("duplicates"),
            "binding_conflict_n": binding.get("conflicts"),
            "page_or_semantic_conflict": semantic_conflict,
        },
        "response_hashes": {
            "analysis": [probe.get("response_sha256") for probe in page_probes],
            "history": [probe.get("response_sha256") for probe in history_probes],
        },
        "rights": {
            "public_page_access": True,
            "commercial_reuse_authority": "NOT_PROVEN",
            "boundary": "PUBLIC_PAGE_ACCESS != COMMERCIAL_REUSE_AUTHORITY",
            "nowscore_contract_surface": "调用 page advertises data-interface cooperation and free-trial/quotation routing",
            "feijing_product_surface": "足球即时竞彩 claims Sports Lottery fixtures and JC football play types",
            "public_pricing_or_contract_for_required_field": "NOT_PROVEN",
        },
        "representative_rows": [_representative_row(row) for row in evidence_rows[:5]],
        "evidence_rows": evidence_rows,
        "delivery_decision": delivery,
        "captured_at": captured_at,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--comparator-ref", default=COMPARATOR_COMMIT)
    parser.add_argument("--output", type=Path, default=ROOT / "nowscore-jc-handicap-mirror-audit.json")
    args = parser.parse_args()
    result = run_audit(comparator_ref=args.comparator_ref)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("delivery_decision") == DELIVERY_PARITY_PROVEN else 1


if __name__ == "__main__":
    raise SystemExit(main())
