#!/usr/bin/env python3
"""Bounded, research-only audit of same-ID Nowscore prematch surfaces.

The existing FBOS prediction-universe row is the only cohort authority.  This
module reuses the project's Nowscore parsers without calling their cache or
write paths.  Page bodies are held only long enough to parse compact states;
the returned artifact contains no page prose, player names, or raw HTML/JS.
"""

from __future__ import annotations

import argparse
import hashlib
import html as html_lib
import json
import re
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

SCRIPT_ROOT = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_ROOT.parent
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))

try:
    from match_identity import canonical_match_id
    from nowscore_markets import (
        ANALYSIS_DATA_URL,
        COACH_URL,
        MARKET_URL,
        PANLU_URL,
        REFEREE_URL,
        USER_AGENT,
        parse_analysis_data,
        parse_coach_page,
        parse_panlu_page,
        parse_referee_page,
        parse_three_in_one,
    )
    from prediction_universe import trusted_nowscore_jc_fixture
except ImportError:  # package-style imports used by focused tests/tools
    from scripts.match_identity import canonical_match_id
    from scripts.nowscore_markets import (
        ANALYSIS_DATA_URL,
        COACH_URL,
        MARKET_URL,
        PANLU_URL,
        REFEREE_URL,
        USER_AGENT,
        parse_analysis_data,
        parse_coach_page,
        parse_panlu_page,
        parse_referee_page,
        parse_three_in_one,
    )
    from scripts.prediction_universe import trusted_nowscore_jc_fixture


CONTRACT_VERSION = "nowscore_same_id_prematch_evidence_audit.r1"
SOURCE_PROVIDER = "nowscore"
SOURCE_ROLE = "same_source_capability_research_only"
SOURCE_IS_PRODUCTION = False
UTC = timezone.utc
SHANGHAI = timezone(timedelta(hours=8))
MAX_REQUESTS = 80

SURFACE_NAMES = (
    "market_context",
    "analysis_data",
    "analysis_page",
    "time_page",
    "coach",
    "referee",
    "panlu",
)
FIELD_NAMES = (
    "competition_standings_stage",
    "recent_form",
    "h2h",
    "future_schedule_rest",
    "injuries",
    "suspensions",
    "lineup_state",
    "coach",
    "referee",
    "panlu",
    "technical_stats",
    "market_context",
)
ALLOWED_STATES = frozenset(
    {"PRESENT", "SECTION_PRESENT_EMPTY", "ABSENT", "ACCESS_GATED", "PARSE_UNCERTAIN", "CONFLICT"}
)
ALLOWED_DECISIONS = frozenset(
    {
        "SAME_SOURCE_EVIDENCE_CAPABILITY_READY",
        "COVERAGE_TOO_THIN",
        "CHRONOLOGY_NOT_PROVABLE",
        "ACCESS_OR_RIGHTS_BOUNDARY_BLOCKED",
        "FAIL_CLOSED",
    }
)

# This criterion is part of the audit contract and is intentionally declared
# before any live page is inspected.  It is not inferred from observed results.
MIN_CAPABILITY_CRITERION = {
    "name": "predeclared_r1_capability_criterion",
    "minimum_present_fields_per_match": 2,
    "minimum_field_classes_present_on_half_cohort": 3,
    "minimum_match_fraction": 0.5,
    "counts_only_state": "PRESENT",
    "chronology_requirement": "every accepted match has exact same-ID identity and a complete observed-before-kickoff request",
}

SURFACE_URLS = {
    "market_context": MARKET_URL,
    "analysis_data": ANALYSIS_DATA_URL,
    "analysis_page": "https://m.nowscore.com/Analy/Analysis/{match_id}.htm",
    "time_page": "https://m.nowscore.com/Analy/ShiJian/{match_id}.htm",
    "coach": COACH_URL,
    "referee": REFEREE_URL,
    "panlu": PANLU_URL,
}

FIELD_SURFACES = {
    "competition_standings_stage": ("market_context", "analysis_page"),
    "recent_form": ("analysis_data", "analysis_page"),
    "h2h": ("analysis_page",),
    "future_schedule_rest": ("analysis_page",),
    "injuries": ("analysis_page", "time_page"),
    "suspensions": ("analysis_page", "time_page"),
    "lineup_state": ("time_page", "analysis_page"),
    "coach": ("coach",),
    "referee": ("referee",),
    "panlu": ("panlu",),
    "technical_stats": ("time_page",),
    "market_context": ("market_context",),
}

SECTION_MARKERS = {
    "competition_standings_stage": ("积分榜", "积分排名", "联赛排名", "standings", "stage", "round", "小组赛"),
    "h2h": ("历史交锋", "交锋记录", "对赛往绩", "head to head", "h2h"),
    "future_schedule_rest": ("未来赛程", "未来比赛", "赛程", "next match", "future fixtures", "schedule"),
    "injuries": ("伤停", "伤病", "伤员", "injur"),
    "suspensions": ("停赛", "禁赛", "suspension", "suspended"),
    "lineup_state": ("首发", "阵容", "lineup", "starting xi", "starting lineup"),
    "technical_stats": ("技术统计", "技术对比", "technical statistics", "possession", "shots on goal", "射门", "控球"),
}
SECTION_ITEMS = {
    "competition_standings_stage": ("积分", "points", "position", "rank", "stage", "round", "<table"),
    "h2h": ("胜", "平", "负", "win", "draw", "loss", "对阵"),
    "future_schedule_rest": ("next", "future", "休息", "rest", "schedule", "<tr"),
    "injuries": ("伤缺", "因伤", "injured", "injury list", "out", "doubt"),
    "suspensions": ("停赛", "禁赛", "suspended", "red card"),
    "lineup_state": ("替补", "substitute", "<li"),
    "technical_stats": ("射门", "控球", "传球", "角球", "shots", "possession", "passes"),
}
EMPTY_MARKERS = ("暂无", "无数据", "没有数据", "none", "no data", "not available", "暂无资料")
ACCESS_MARKERS = (
    "请登录",
    "登录后",
    "会员登录",
    "需要登录",
    "验证码",
    "captcha",
    "paywall",
    "login required",
    "sign in to view",
    "please login",
)
CONFIRMED_LINEUP_MARKERS = ("确认首发", "已确认首发", "confirmed lineup", "confirmed starting")
PREDICTED_LINEUP_MARKERS = ("预计首发", "预测首发", "预计阵容", "predicted lineup", "probable lineup")


class AuditIntegrityError(RuntimeError):
    """A hard audit boundary was reached."""


def _text(value: Any) -> str:
    return str(value or "").strip()


def _first(mapping: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        value = mapping.get(key)
        if value not in (None, ""):
            return value
    return None


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _parse_datetime(value: Any, *, naive_tz: timezone = SHANGHAI) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    else:
        raw = _text(value)
        if not raw:
            return None
        normalized = raw.replace("Z", "+00:00").replace("/", "-")
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError:
            parsed = None
            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
                try:
                    parsed = datetime.strptime(raw, fmt)
                    break
                except ValueError:
                    continue
            if parsed is None:
                return None
    return (parsed.replace(tzinfo=naive_tz) if parsed.tzinfo is None else parsed).astimezone(UTC)


def _target_kickoff(row: Mapping[str, Any]) -> datetime | None:
    for key in ("kickoff_at", "kickoff", "kickoff_local"):
        value = row.get(key)
        if value not in (None, ""):
            parsed = _parse_datetime(value)
            if parsed:
                return parsed
    match_date = _text(_first(row, "matchDate", "match_date"))
    match_time = _text(_first(row, "matchTime", "match_time"))
    if not match_date or not match_time:
        return None
    return _parse_datetime(f"{match_date}T{match_time[:8]}")


def _numeric_id(value: Any) -> int | None:
    if value in (None, "") or isinstance(value, bool):
        return None
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _name_key(value: Any) -> str:
    return "".join(_text(value).casefold().split())


def _sha256(value: bytes | str) -> str:
    raw = value if isinstance(value, bytes) else value.encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _decode(raw: bytes) -> str:
    for encoding in ("utf-8", "gb18030"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _safe_source_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


@dataclass(frozen=True)
class TargetFixture:
    nowscore_id: int
    canonical_match_id: str
    canonical_match_digest: str
    home_team: str
    away_team: str
    kickoff_at: datetime
    source_row_index: int

    def public(self) -> dict[str, Any]:
        return {
            "nowscore_id": self.nowscore_id,
            "canonical_match_digest": self.canonical_match_digest,
            "kickoff_at": self.kickoff_at.isoformat(),
        }


@dataclass(frozen=True)
class CohortDeclaration:
    matches: tuple[TargetFixture, ...]
    source_path: str
    source_status: str
    as_of: datetime
    source_rows: int
    future_rows: int
    excluded_nonfuture_rows: int
    invalid_rows: int
    duplicate_match_count: int

    @property
    def valid(self) -> bool:
        return bool(self.matches) and self.source_status == "READY" and not self.invalid_rows and not self.duplicate_match_count

    def public_summary(self) -> dict[str, Any]:
        return {
            "source_path": self.source_path,
            "source_status": self.source_status,
            "as_of": self.as_of.isoformat(),
            "natural_cohort": True,
            "source_rows": self.source_rows,
            "declared_match_count": len(self.matches),
            "future_rows": self.future_rows,
            "excluded_nonfuture_rows": self.excluded_nonfuture_rows,
            "invalid_rows": self.invalid_rows,
            "duplicate_match_count": self.duplicate_match_count,
            "future_only": bool(self.matches) and all(item.kickoff_at > self.as_of for item in self.matches),
            "one_match_one_observation": self.duplicate_match_count == 0,
            "matches": [item.public() for item in self.matches],
        }


def _load_cohort_rows(path: Path) -> tuple[list[Any], str]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AuditIntegrityError(f"COHORT_READ_FAILED:{type(exc).__name__}") from exc
    if not isinstance(payload, Mapping):
        raise AuditIntegrityError("COHORT_PAYLOAD_NOT_OBJECT")
    rows = payload.get("fixtures") if isinstance(payload.get("fixtures"), list) else payload.get("matches")
    if not isinstance(rows, list):
        raise AuditIntegrityError("COHORT_FIXTURES_NOT_LIST")
    return rows, _text(payload.get("status")) or "UNKNOWN"


def _build_target(row: Mapping[str, Any], row_index: int, as_of: datetime) -> TargetFixture | None:
    nowscore_id = _numeric_id(_first(row, "nowscore_id", "nowscoreId", "matchId", "match_id"))
    home = _text(_first(row, "homeTeam", "home_team", "home"))
    away = _text(_first(row, "awayTeam", "away_team", "away"))
    kickoff = _target_kickoff(row)
    if nowscore_id is None or not home or not away or kickoff is None or kickoff <= as_of:
        return None
    if not trusted_nowscore_jc_fixture(row, nowscore_id).get("trusted"):
        return None
    match_key = canonical_match_id({"home": home, "away": away, "kickoff": kickoff.isoformat()})
    return TargetFixture(
        nowscore_id=nowscore_id,
        canonical_match_id=match_key,
        canonical_match_digest=_sha256(match_key),
        home_team=home,
        away_team=away,
        kickoff_at=kickoff,
        source_row_index=row_index,
    )


def declare_cohort(path: str | Path, *, as_of: datetime | None = None) -> CohortDeclaration:
    observed_at = _as_utc(as_of or datetime.now(UTC))
    source_path = Path(path)
    rows, source_status = _load_cohort_rows(source_path)
    future_rows = excluded_nonfuture_rows = invalid_rows = duplicate_count = 0
    candidates: list[TargetFixture] = []
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            invalid_rows += 1
            continue
        kickoff = _target_kickoff(row)
        is_future = kickoff is not None and kickoff > observed_at
        if is_future:
            future_rows += 1
        else:
            excluded_nonfuture_rows += 1
        target = _build_target(row, index, observed_at)
        if target:
            candidates.append(target)
        elif is_future:
            invalid_rows += 1
    seen_ids: set[int] = set()
    seen_keys: set[str] = set()
    unique: list[TargetFixture] = []
    for target in sorted(candidates, key=lambda item: (item.kickoff_at, item.nowscore_id)):
        if target.nowscore_id in seen_ids or target.canonical_match_id in seen_keys:
            duplicate_count += 1
            continue
        seen_ids.add(target.nowscore_id)
        seen_keys.add(target.canonical_match_id)
        unique.append(target)
    return CohortDeclaration(
        matches=tuple(unique),
        source_path=_safe_source_path(source_path),
        source_status=source_status,
        as_of=observed_at,
        source_rows=len(rows),
        future_rows=future_rows,
        excluded_nonfuture_rows=excluded_nonfuture_rows,
        invalid_rows=invalid_rows,
        duplicate_match_count=duplicate_count,
    )


def discover_cohort_path(*, root: Path | None = None, as_of: datetime | None = None) -> Path:
    directory = root or REPO_ROOT / "data" / "prediction_universe"
    local_date = _as_utc(as_of or datetime.now(UTC)).astimezone(SHANGHAI).date()
    candidates: list[tuple[date, Path]] = []
    for path in directory.glob("*.json"):
        try:
            file_date = datetime.strptime(path.stem, "%Y-%m-%d").date()
        except ValueError:
            continue
        if file_date <= local_date:
            candidates.append((file_date, path))
    for _file_date, path in sorted(candidates, reverse=True):
        try:
            rows, status = _load_cohort_rows(path)
        except AuditIntegrityError:
            continue
        if status == "READY" and rows:
            return path
    raise AuditIntegrityError("NATURAL_COHORT_NOT_AVAILABLE")


@dataclass(frozen=True)
class ObservationMetadata:
    surface: str
    request_started_at: datetime
    response_at: datetime
    observed_at: datetime
    http_status: int | None
    content_sha256: str | None
    content_length: int
    source_update_at: datetime | None
    source_update_basis: str
    error_code: str | None = None

    def public(self) -> dict[str, Any]:
        return {
            "surface": self.surface,
            "request_started_at": _as_utc(self.request_started_at).isoformat(),
            "response_at": _as_utc(self.response_at).isoformat(),
            "observed_at": _as_utc(self.observed_at).isoformat(),
            "http_status": self.http_status,
            "content_sha256": self.content_sha256,
            "content_length": self.content_length,
            "source_update_at": _as_utc(self.source_update_at).isoformat() if self.source_update_at else None,
            "source_update_basis": self.source_update_basis,
            "error_code": self.error_code,
        }


class NowscorePublicClient:
    """Unauthenticated, no-cache HTTP client for this audit only."""

    def __init__(
        self,
        *,
        opener: Callable[..., Any] = urlopen,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        timeout: float = 30.0,
        max_requests: int = MAX_REQUESTS,
    ) -> None:
        if not 1 <= int(max_requests) <= MAX_REQUESTS:
            raise ValueError(f"max_requests must be between 1 and {MAX_REQUESTS}")
        self.opener = opener
        self.clock = clock
        self.timeout = timeout
        self.max_requests = int(max_requests)
        self.used = 0

    def fetch(self, surface: str, url: str) -> tuple[ObservationMetadata, bytes]:
        if self.used >= self.max_requests:
            raise AuditIntegrityError("REQUEST_BUDGET_EXCEEDED")
        self.used += 1
        started = _as_utc(self.clock())
        request = Request(
            url,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/xhtml+xml,application/javascript,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
                "Accept-Encoding": "identity",
                "Referer": "https://live.nowscore.com/",
                "Cache-Control": "no-cache",
            },
            method="GET",
        )
        body = b""
        status: int | None = None
        headers: Mapping[str, Any] = {}
        error_code: str | None = None
        try:
            response = self.opener(request, timeout=self.timeout)
            try:
                body = response.read()
                status = int(getattr(response, "status", 200))
                raw_headers = getattr(response, "headers", {})
                if hasattr(raw_headers, "items"):
                    headers = {str(key): value for key, value in raw_headers.items()}
            finally:
                close = getattr(response, "close", None)
                if callable(close):
                    close()
        except HTTPError as exc:
            status = int(exc.code)
            raw_headers = getattr(exc, "headers", {})
            if hasattr(raw_headers, "items"):
                headers = {str(key): value for key, value in raw_headers.items()}
            error_code = f"HTTP_{status}"
        except (URLError, OSError, TimeoutError):
            error_code = "NETWORK_ERROR"
        response_at = _as_utc(self.clock())
        observed_at = _as_utc(self.clock())
        source_update_at = _parse_http_date(_header_value(headers, "Last-Modified"))
        metadata = ObservationMetadata(
            surface=surface,
            request_started_at=started,
            response_at=response_at,
            observed_at=observed_at,
            http_status=status,
            content_sha256=_sha256(body) if body else None,
            content_length=len(body),
            source_update_at=source_update_at,
            source_update_basis="HTTP_LAST_MODIFIED" if source_update_at else "NOT_EXPOSED",
            error_code=error_code,
        )
        return metadata, body


def _parse_http_date(value: Any) -> datetime | None:
    raw = _text(value)
    if not raw:
        return None
    try:
        parsed = parsedate_to_datetime(raw)
    except (TypeError, ValueError, OverflowError):
        return None
    return _as_utc(parsed)


def _header_value(headers: Mapping[str, Any], name: str) -> Any:
    wanted = name.casefold()
    for key, value in headers.items():
        if str(key).casefold() == wanted:
            return value
    return None


def _visible_text(text: str) -> str:
    stripped = re.sub(r"<script\b.*?</script>|<style\b.*?</style>", " ", text, flags=re.I | re.S)
    stripped = re.sub(r"<[^>]+>", " ", stripped)
    return re.sub(r"\s+", " ", html_lib.unescape(stripped)).casefold()


def _has_any(text: str, markers: Iterable[str]) -> bool:
    return any(marker.casefold() in text for marker in markers)


def _signal_count(text: str, markers: Iterable[str]) -> int:
    return min(99, sum(text.count(marker.casefold()) for marker in markers))


def _has_nearby(text: str, anchors: Iterable[str], signals: Iterable[str], window: int = 160) -> bool:
    lower = text.casefold()
    signal_values = tuple(signal.casefold() for signal in signals)
    for anchor in anchors:
        needle = anchor.casefold()
        start = 0
        while True:
            position = lower.find(needle, start)
            if position < 0:
                break
            excerpt = lower[max(0, position - window): position + len(needle) + window]
            if any(signal in excerpt for signal in signal_values):
                return True
            start = position + len(needle)
    return False


def _field(state: str, *, signal_count: int = 0, prematch_eligible: bool = True, reason_code: str | None = None, semantic_state: str | None = None, applicable: bool = True) -> dict[str, Any]:
    if state not in ALLOWED_STATES:
        raise ValueError(f"unknown audit state: {state}")
    result: dict[str, Any] = {
        "state": state,
        "signal_count": int(signal_count),
        "prematch_eligible": bool(prematch_eligible),
        "applicable": bool(applicable),
    }
    if reason_code:
        result["reason_code"] = reason_code
    if semantic_state:
        result["semantic_state"] = semantic_state
    return result


def _section_field(text: str, field_name: str) -> dict[str, Any]:
    markers = SECTION_MARKERS[field_name]
    if not _has_any(text, markers):
        return _field("ABSENT", reason_code="SECTION_ABSENT")
    empty_signal = _has_nearby(text, markers, EMPTY_MARKERS)
    item_signal = _has_nearby(text, markers, SECTION_ITEMS[field_name])
    if empty_signal and item_signal:
        return _field("CONFLICT", reason_code="EXPLICIT_EMPTY_AND_ITEM_SIGNALS")
    if empty_signal:
        return _field("SECTION_PRESENT_EMPTY", reason_code="EXPLICIT_EMPTY_MARKER")
    if item_signal:
        return _field("PRESENT", signal_count=_signal_count(text, SECTION_ITEMS[field_name]), reason_code="EXPLICIT_SECTION_AND_ITEM_SIGNAL")
    return _field("PARSE_UNCERTAIN", reason_code="SECTION_PRESENT_WITHOUT_SAFE_ITEM_SIGNAL")


def _lineup_field(text: str) -> dict[str, Any]:
    without_scripts = re.sub(r"<script\b.*?</script>|<style\b.*?</style>", " ", text, flags=re.I | re.S)
    visible = _visible_text(without_scripts)
    result = _section_field(visible, "lineup_state")
    if result["state"] == "PARSE_UNCERTAIN" and re.search(
        r"<(?:ul|ol|table)\b[^>]*>.*?<li\b", without_scripts, flags=re.I | re.S
    ):
        result = _field("PRESENT", signal_count=1, reason_code="EXPLICIT_LINEUP_CONTAINER_SIGNAL")
    if result["state"] == "PRESENT":
        if _has_any(visible, CONFIRMED_LINEUP_MARKERS):
            result["semantic_state"] = "CONFIRMED"
        elif _has_any(visible, PREDICTED_LINEUP_MARKERS):
            result["semantic_state"] = "PREDICTED"
        else:
            result["semantic_state"] = "UNLABELLED"
    elif result["state"] == "SECTION_PRESENT_EMPTY":
        result["semantic_state"] = "UNLABELLED"
    return result


def _parser_field(text: str, field_name: str, parser: Callable[[str], Any], present: Callable[[Any], int], markers: Iterable[str]) -> dict[str, Any]:
    try:
        parsed = parser(text)
        count = max(0, int(present(parsed)))
    except Exception:
        parsed = None
        count = 0
    if count > 0:
        return _field("PRESENT", signal_count=count, reason_code="SAFE_EXISTING_PARSER_RESULT")
    if _has_any(_visible_text(text), markers):
        if _has_any(_visible_text(text), EMPTY_MARKERS):
            return _field("SECTION_PRESENT_EMPTY", reason_code="EXPLICIT_EMPTY_MARKER")
        return _field("PARSE_UNCERTAIN", reason_code="EXPECTED_SECTION_NOT_PARSED")
    return _field("ABSENT", reason_code="NO_SAFE_PARSER_RESULT_OR_SECTION_SIGNAL")


def _analysis_recent_count(parsed: Any) -> int:
    recent = parsed.get("recent_form") if isinstance(parsed, Mapping) else None
    if not isinstance(recent, Mapping):
        return 0
    return sum(int((value or {}).get("matches") or 0) for value in recent.values() if isinstance(value, Mapping))


def _coach_count(parsed: Any) -> int:
    if not isinstance(parsed, Mapping):
        return 0
    count = 0
    for side in ("home", "away"):
        row = parsed.get(side) or {}
        if isinstance(row, Mapping):
            count += int(bool(row.get("name"))) + len(row.get("coach_records") or []) + len(row.get("team_records") or [])
    return count


def _referee_count(parsed: Any) -> int:
    if not isinstance(parsed, Mapping):
        return 0
    return int(bool(parsed.get("name"))) + len(parsed.get("summaries") or [])


def _panlu_count(parsed: Any) -> int:
    return int(parsed.get("count") or 0) if isinstance(parsed, Mapping) else 0


def _market_count(parsed: Any) -> int:
    if not isinstance(parsed, Mapping):
        return 0
    return sum(int((parsed.get(name) or {}).get("total") or 0) for name in ("ouzhi", "yazhi", "daxiao"))


def _market_identity(parsed: Any) -> Mapping[str, Any]:
    identity = parsed.get("identity") if isinstance(parsed, Mapping) else None
    return identity if isinstance(identity, Mapping) else {}


def _base_fields(*, prematch_eligible: bool, reason_code: str | None = None) -> dict[str, dict[str, Any]]:
    return {
        field_name: _field(
            "CONFLICT" if not prematch_eligible else "ABSENT",
            prematch_eligible=prematch_eligible,
            reason_code=reason_code if not prematch_eligible else "SURFACE_NOT_USED",
            applicable=False,
        )
        for field_name in FIELD_NAMES
    }


def _fields_for_surface(surface: str, text: str) -> dict[str, dict[str, Any]]:
    fields = _base_fields(prematch_eligible=True)
    visible = _visible_text(text)
    if surface == "market_context":
        try:
            parsed = parse_three_in_one(text)
            market_count = _market_count(parsed)
        except Exception:
            parsed = None
            market_count = 0
        fields["market_context"] = (
            _field("PRESENT", signal_count=market_count, reason_code="SAFE_EXISTING_PARSER_RESULT")
            if market_count
            else _section_field(visible, "market_context")
            if "market_context" in SECTION_MARKERS
            else _field("PRESENT" if _has_any(visible, ("欧赔", "亚盘", "大小球", "odds", "handicap")) else "ABSENT", reason_code="EXPLICIT_MARKET_SIGNAL")
        )
        fields["competition_standings_stage"] = _section_field(visible, "competition_standings_stage")
    elif surface == "analysis_data":
        fields["recent_form"] = _parser_field(
            text,
            "recent_form",
            parse_analysis_data,
            _analysis_recent_count,
            ("h_data", "a_data", "近期战绩", "recent form"),
        )
    elif surface == "analysis_page":
        for field_name in ("competition_standings_stage", "h2h", "future_schedule_rest", "injuries", "suspensions"):
            fields[field_name] = _section_field(visible, field_name)
        fields["lineup_state"] = _lineup_field(text)
    elif surface == "time_page":
        fields["injuries"] = _section_field(visible, "injuries")
        fields["suspensions"] = _section_field(visible, "suspensions")
        fields["lineup_state"] = _lineup_field(text)
        fields["technical_stats"] = _section_field(visible, "technical_stats")
    elif surface == "coach":
        fields["coach"] = _parser_field(text, "coach", parse_coach_page, _coach_count, ("教练", "coach"))
    elif surface == "referee":
        fields["referee"] = _parser_field(text, "referee", parse_referee_page, _referee_count, ("裁判", "referee"))
    elif surface == "panlu":
        fields["panlu"] = _parser_field(text, "panlu", parse_panlu_page, _panlu_count, ("盘路", "panlu"))
    # Recent form / H2H / future schedule can also be visibly labelled on the
    # Analysis HTML page; analysisData remains the only safe structured form
    # parser and never invents values from a marker alone.
    return fields


def _publication(metadata: ObservationMetadata, text: str) -> dict[str, Any]:
    visible = _visible_text(text)
    if metadata.http_status in (401, 403) or _has_any(visible, ACCESS_MARKERS):
        state, reason = "ACCESS_GATED", "LOGIN_OR_ACCESS_GATE_EXPLICIT"
    elif metadata.error_code or not (200 <= int(metadata.http_status or 0) < 300):
        state, reason = "ABSENT", metadata.error_code or "HTTP_NON_2XX"
    elif not text:
        state, reason = "ABSENT", "EMPTY_RESPONSE_BODY"
    else:
        state, reason = "PRESENT", "HTTP_2XX_BODY"
    return {
        "state": state,
        "reason_code": reason,
        "http_status": metadata.http_status,
        "body_present": bool(text),
        "content_length": metadata.content_length,
        "content_sha256": metadata.content_sha256,
        "source_update_at": metadata.source_update_at.isoformat() if metadata.source_update_at else None,
        "source_update_basis": metadata.source_update_basis,
        "error_code": metadata.error_code,
    }


def validate_same_id_identity(target: TargetFixture, page_identity: Mapping[str, Any]) -> dict[str, Any]:
    reasons: list[str] = []
    page_id = _numeric_id(_first(page_identity, "nowscore_id", "page_provider_id"))
    if page_id is None:
        reasons.append("PAGE_ID_MISSING")
    elif page_id != target.nowscore_id:
        reasons.append("PAGE_ID_MISMATCH")
    page_kickoff = _parse_datetime(page_identity.get("kickoff_local"))
    if page_kickoff is None:
        reasons.append("KICKOFF_MISSING")
    elif page_kickoff != target.kickoff_at:
        reasons.append("KICKOFF_MISMATCH")
    page_home = _text(page_identity.get("home_team"))
    page_away = _text(page_identity.get("away_team"))
    if not page_home or not page_away:
        reasons.append("TEAM_NAME_MISSING")
    else:
        if _name_key(page_home) != _name_key(target.home_team):
            reasons.append("HOME_TEAM_MISMATCH")
        if _name_key(page_away) != _name_key(target.away_team):
            reasons.append("AWAY_TEAM_MISMATCH")
        if _name_key(page_home) == _name_key(target.away_team) and _name_key(page_away) == _name_key(target.home_team):
            reasons.append("ORIENTATION_CONFLICT")
    conflict_reasons = {"PAGE_ID_MISMATCH", "KICKOFF_MISMATCH", "HOME_TEAM_MISMATCH", "AWAY_TEAM_MISMATCH", "ORIENTATION_CONFLICT"}
    state = "CONFLICT" if any(reason in conflict_reasons for reason in reasons) else "PARSE_UNCERTAIN" if reasons else "PRESENT"
    return {
        "state": state,
        "reason_codes": list(dict.fromkeys(reasons)),
        "page_id_present": page_id is not None,
        "kickoff_present": page_kickoff is not None,
        "kickoff_consistent": page_kickoff == target.kickoff_at if page_kickoff else False,
        "team_names_present": bool(page_home and page_away),
    }


def _relation(metadata: ObservationMetadata, kickoff_at: datetime) -> tuple[str, bool]:
    kickoff = _as_utc(kickoff_at)
    timestamps = [
        _as_utc(metadata.request_started_at),
        _as_utc(metadata.response_at),
        _as_utc(metadata.observed_at),
    ]
    if metadata.source_update_at:
        timestamps.append(_as_utc(metadata.source_update_at))
    if all(timestamp < kickoff for timestamp in timestamps):
        return "BEFORE_KICKOFF", True
    if timestamps[0] >= kickoff:
        return "AFTER_KICKOFF", False
    return "CROSSED_KICKOFF", False


def summarize_surface(target: TargetFixture, surface: str, body: bytes, metadata: ObservationMetadata) -> dict[str, Any]:
    if surface not in SURFACE_NAMES:
        raise ValueError(f"unknown Nowscore surface: {surface}")
    text = _decode(body or b"")
    publication = _publication(metadata, text)
    relation, prematch_eligible = _relation(metadata, target.kickoff_at)
    if not prematch_eligible:
        fields = {
            field_name: _field(
                "CONFLICT",
                prematch_eligible=False,
                reason_code="POST_KICKOFF_OBSERVATION",
                applicable=surface in FIELD_SURFACES.get(field_name, ()),
            )
            for field_name in FIELD_NAMES
        }
    elif publication["state"] == "ACCESS_GATED":
        fields = {field_name: _field("ACCESS_GATED", reason_code="LOGIN_OR_ACCESS_GATE_EXPLICIT", applicable=surface in FIELD_SURFACES.get(field_name, ())) for field_name in FIELD_NAMES}
    elif publication["state"] == "ABSENT":
        fields = {field_name: _field("ABSENT", reason_code="SURFACE_UNAVAILABLE", applicable=surface in FIELD_SURFACES.get(field_name, ())) for field_name in FIELD_NAMES}
    else:
        fields = _fields_for_surface(surface, text)
    result = {
        "publication": publication,
        "chronology": {
            "relation": relation,
            "prematch_eligible": prematch_eligible,
            "request_started_at": _as_utc(metadata.request_started_at).isoformat(),
            "response_at": _as_utc(metadata.response_at).isoformat(),
            "observed_at": _as_utc(metadata.observed_at).isoformat(),
            "source_update_at": _as_utc(metadata.source_update_at).isoformat() if metadata.source_update_at else None,
            "source_update_basis": metadata.source_update_basis,
        },
        "fields": fields,
    }
    if surface == "market_context" and prematch_eligible and publication["state"] == "PRESENT":
        try:
            parsed = parse_three_in_one(text)
        except Exception:
            parsed = None
        result["identity"] = validate_same_id_identity(target, _market_identity(parsed))
    elif surface == "market_context":
        result["identity"] = {"state": publication["state"], "reason_codes": [publication["reason_code"]], "page_id_present": False, "kickoff_present": False, "kickoff_consistent": False, "team_names_present": False}
    return result


def _merge_fields(field_rows: Mapping[str, dict[str, Any]], surface: str, fields: Mapping[str, Mapping[str, Any]]) -> None:
    priority = {"ABSENT": 0, "ACCESS_GATED": 1, "PARSE_UNCERTAIN": 2, "SECTION_PRESENT_EMPTY": 3, "PRESENT": 4, "CONFLICT": 5}
    for field_name, detail in fields.items():
        if not detail.get("applicable"):
            continue
        row = field_rows[field_name]
        row["surface_states"][surface] = detail["state"]
        row["applicable_surface_count"] += 1
        row["signal_count"] += int(detail.get("signal_count") or 0)
        row["prematch_eligible"] &= bool(detail.get("prematch_eligible"))
        if detail.get("state") == "PRESENT":
            row["present_surface_count"] += 1
        semantic = detail.get("semantic_state")
        if semantic:
            row.setdefault("semantic_states", {})[surface] = semantic
        current = row["state"]
        if priority[detail["state"]] > priority[current]:
            row["state"] = detail["state"]


def _new_field_rows() -> dict[str, dict[str, Any]]:
    return {
        field_name: {
            "state": "ABSENT",
            "surface_states": {},
            "applicable_surface_count": 0,
            "present_surface_count": 0,
            "signal_count": 0,
            "prematch_eligible": True,
        }
        for field_name in FIELD_NAMES
    }


class AuditRunner:
    def __init__(self, client: Any, declaration: CohortDeclaration) -> None:
        self.client = client
        self.declaration = declaration
        self.observations: list[ObservationMetadata] = []

    def _fetch(self, target: TargetFixture, surface: str) -> dict[str, Any]:
        if len(self.observations) >= MAX_REQUESTS:
            raise AuditIntegrityError("REQUEST_BUDGET_EXCEEDED")
        template = SURFACE_URLS[surface]
        url = template.format(match_id=target.nowscore_id)
        metadata, body = self.client.fetch(surface, url)
        if metadata.surface != surface:
            raise AuditIntegrityError("OBSERVATION_SURFACE_MISMATCH")
        self.observations.append(metadata)
        summary = summarize_surface(target, surface, body, metadata)
        # ``body`` is deliberately not attached to either runner or summary.
        return {"observation": metadata.public(), **summary}

    def _target(self, target: TargetFixture) -> dict[str, Any]:
        surfaces: dict[str, dict[str, Any]] = {}
        market = self._fetch(target, "market_context")
        surfaces["market_context"] = market
        identity = market.get("identity", {})
        if identity.get("state") != "PRESENT":
            fields = _new_field_rows()
            _merge_fields(fields, "market_context", market["fields"])
            return {"target": target.public(), "identity": identity, "surfaces": surfaces, "fields": fields}
        for surface in SURFACE_NAMES:
            if surface == "market_context":
                continue
            surfaces[surface] = self._fetch(target, surface)
        fields = _new_field_rows()
        for surface, summary in surfaces.items():
            _merge_fields(fields, surface, summary["fields"])
        chronology = {
            "all_requested_surfaces_before_kickoff": all(item["chronology"]["prematch_eligible"] for item in surfaces.values()),
            "relation_counts": dict(Counter(item["chronology"]["relation"] for item in surfaces.values())),
            "source_update_timestamp_present_count": sum(bool(item["chronology"]["source_update_at"]) for item in surfaces.values()),
        }
        return {"target": target.public(), "identity": identity, "chronology": chronology, "surfaces": surfaces, "fields": fields}

    def run(self) -> dict[str, Any]:
        if not self.declaration.valid:
            return {"decision": "FAIL_CLOSED", "reason": "INVALID_OR_NON_UNIQUE_FUTURE_COHORT", "matches": []}
        matches = [self._target(target) for target in self.declaration.matches]
        market_states = [row["surfaces"]["market_context"]["publication"]["state"] for row in matches]
        if market_states and all(state == "ACCESS_GATED" for state in market_states):
            decision, reason = "ACCESS_OR_RIGHTS_BOUNDARY_BLOCKED", "ALL_SAME_ID_MARKET_SURFACES_ACCESS_GATED"
        elif any(row["identity"].get("state") == "CONFLICT" for row in matches):
            decision, reason = "FAIL_CLOSED", "SAME_ID_OR_KICKOFF_CONFLICT"
        elif any(row["identity"].get("state") != "PRESENT" for row in matches):
            decision, reason = "FAIL_CLOSED", "SAME_ID_PAGE_IDENTITY_NOT_ESTABLISHED"
        elif any(not row.get("chronology", {}).get("all_requested_surfaces_before_kickoff") for row in matches):
            decision, reason = "CHRONOLOGY_NOT_PROVABLE", "ONE_OR_MORE_OBSERVATIONS_NOT_BEFORE_KICKOFF"
        else:
            field_aggregate = _aggregate_fields(matches)
            cohort_size = len(matches)
            half = max(1, (cohort_size + 1) // 2)
            classes_on_half = sum(item["present_match_count"] >= half for item in field_aggregate.values())
            matches_with_two = sum(sum(item["state"] == "PRESENT" for item in row["fields"].values()) >= MIN_CAPABILITY_CRITERION["minimum_present_fields_per_match"] for row in matches)
            fraction = matches_with_two / cohort_size if cohort_size else 0.0
            if classes_on_half >= MIN_CAPABILITY_CRITERION["minimum_field_classes_present_on_half_cohort"] and fraction >= MIN_CAPABILITY_CRITERION["minimum_match_fraction"]:
                decision, reason = "SAME_SOURCE_EVIDENCE_CAPABILITY_READY", "PREDECLARED_CAPABILITY_CRITERION_MET"
            else:
                decision, reason = "COVERAGE_TOO_THIN", "PREDECLARED_CAPABILITY_CRITERION_NOT_MET"
        return {"decision": decision, "reason": reason, "matches": matches}


def _aggregate_fields(matches: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for field_name in FIELD_NAMES:
        state_counts = Counter(str(row.get("fields", {}).get(field_name, {}).get("state") or "ABSENT") for row in matches)
        present_match_count = state_counts["PRESENT"]
        result[field_name] = {"state_counts": dict(sorted(state_counts.items())), "present_match_count": present_match_count, "match_count": len(matches)}
    return result


def _request_summary(observations: Sequence[ObservationMetadata]) -> dict[str, Any]:
    return {
        "used": len(observations),
        "max": MAX_REQUESTS,
        "within_budget": len(observations) <= MAX_REQUESTS,
        "surface_counts": dict(sorted(Counter(item.surface for item in observations).items())),
        "error_count": sum(bool(item.error_code) for item in observations),
        "source_update_timestamp_count": sum(bool(item.source_update_at) for item in observations),
        "observed_before_kickoff_count": None,
        "content_hash_count": sum(bool(item.content_sha256) for item in observations),
    }


def _base_summary(cohort: CohortDeclaration | None) -> dict[str, Any]:
    return {
        "contract_version": CONTRACT_VERSION,
        "source_provider": SOURCE_PROVIDER,
        "source_role": SOURCE_ROLE,
        "source_is_production": SOURCE_IS_PRODUCTION,
        "production_source_selected": False,
        "model_change_allowed": False,
        "champion_change_allowed": False,
        "serving_change_allowed": False,
        "ui_change_allowed": False,
        "public_raw_content_persisted": False,
        "source_prose_or_names_persisted": False,
        "public_summary_only": True,
        "minimum_capability_criterion": MIN_CAPABILITY_CRITERION,
        "decision": "FAIL_CLOSED",
        "reason": "NOT_RUN",
        "cohort": cohort.public_summary() if cohort else None,
        "matches": [],
        "field_aggregate": {field_name: {"state_counts": {}, "present_match_count": 0, "match_count": 0} for field_name in FIELD_NAMES},
        "requests": _request_summary(()),
    }


def run_bounded_audit(cohort_path: str | Path | None = None, *, as_of: datetime | None = None, client: Any | None = None) -> dict[str, Any]:
    observed_at = _as_utc(as_of or datetime.now(UTC))
    try:
        path = Path(cohort_path) if _text(cohort_path) else discover_cohort_path(as_of=observed_at)
        declaration = declare_cohort(path, as_of=observed_at)
        summary = _base_summary(declaration)
        if len(declaration.matches) * len(SURFACE_NAMES) > MAX_REQUESTS:
            summary.update({"decision": "FAIL_CLOSED", "reason": "REQUEST_BUDGET_WOULD_BE_EXCEEDED_WITHOUT_SAMPLING"})
            return summary
        runner = AuditRunner(client or NowscorePublicClient(), declaration)
        result = runner.run()
        summary.update(result)
        summary["field_aggregate"] = _aggregate_fields(result.get("matches", [])) if result.get("matches") else summary["field_aggregate"]
        summary["requests"] = _request_summary(runner.observations)
        return summary
    except AuditIntegrityError as exc:
        summary = _base_summary(None)
        summary.update({"decision": "FAIL_CLOSED", "reason": str(exc)})
        return summary


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cohort-path", default="")
    parser.add_argument("--as-of")
    parser.add_argument("--output")
    args = parser.parse_args(argv)
    as_of = _parse_datetime(args.as_of, naive_tz=UTC) if args.as_of else None
    if args.as_of and as_of is None:
        raise SystemExit("--as-of must be an ISO timestamp")
    summary = run_bounded_audit(args.cohort_path or None, as_of=as_of)
    text = json.dumps(summary, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        destination = Path(args.output)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
