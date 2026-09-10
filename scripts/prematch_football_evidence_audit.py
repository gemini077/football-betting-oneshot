#!/usr/bin/env python3
"""Bounded, research-only API-Football prematch evidence probe.

The existing FBOS/Nowscore fixture identity remains the left side.  Provider
responses stay in memory and only a compact, non-reconstructive summary is
written.  This script does not own or feed the existing ``football_state_memory.v1``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

SCRIPT_ROOT = Path(__file__).resolve().parent
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))

try:
    from match_identity import canonical_match_id
    from prediction_universe import trusted_nowscore_jc_fixture
except ImportError:  # package imports used by focused tests
    from scripts.match_identity import canonical_match_id
    from scripts.prediction_universe import trusted_nowscore_jc_fixture


CONTRACT_VERSION = "prematch_football_evidence_shadow_audit.r1"
EXISTING_STATE_MEMORY_CONTRACT = "football_state_memory.v1"
PROVIDER_NAME = "API-Football"
API_BASE_URL = "https://v3.football.api-sports.com"
API_KEY_ENV = "API_FOOTBALL_KEY"
MAX_REQUESTS = 80
MAX_REQUESTS_PER_MINUTE = 10
MAX_COHORT_MATCHES = 12
MIN_COHORT_MATCHES = 8
MAX_KICKOFF_DELTA_MINUTES = 15.0
POSTMATCH_FAMILIES = frozenset({"events", "statistics", "ratings", "player_performance"})

COMPETITION_ALIASES = {
    "欧冠杯": (2, "UEFA Champions League"),
    "葡超": (94, "Primeira Liga"),
    "解放者杯": (13, "CONMEBOL Libertadores"),
    "英超": (39, "Premier League"),
    "西甲": (140, "La Liga"),
    "意甲": (135, "Serie A"),
    "德甲": (78, "Bundesliga"),
    "法甲": (61, "Ligue 1"),
    "日职": (98, "J1 League"),
    "韩职": (292, "K League 1"),
    "中超": (169, "Chinese Super League"),
}
COVERAGE_KEYS = {
    "lineups": ("lineups",),
    "injuries": ("injuries",),
    "odds": ("odds",),
    "earlier_matches": ("fixtures",),
    "earlier_statistics": ("statistics_fixtures", "statistics"),
}
SUMMARY_FIELDS = {
    "lineups": ("team", "coach", "players", "startXI", "substitutes"),
    "injuries": ("player", "team", "type", "reason", "date", "timestamp"),
    "odds": ("bookmakers", "bookmaker", "bets", "values", "update", "market"),
    "earlier_matches": ("fixture", "league", "teams", "goals", "score", "date"),
    "earlier_statistics": ("team", "statistics", "shots on goal", "possession", "passes", "goals"),
}
UTC = timezone.utc
SHANGHAI = timezone(timedelta(hours=8))


class AuditIntegrityError(RuntimeError):
    """A hard audit boundary was reached."""


class RequestBudgetExceeded(AuditIntegrityError):
    pass


class RateLimitBlocked(AuditIntegrityError):
    pass


def _text(value: Any) -> str:
    return str(value or "").strip()


def _first(mapping: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        value = mapping.get(key)
        if value not in (None, ""):
            return value
    return None


def _nested(mapping: Mapping[str, Any], *keys: str) -> Mapping[str, Any]:
    for key in keys:
        value = mapping.get(key)
        if isinstance(value, Mapping):
            return value
    return {}


def _parse_datetime(value: Any, *, naive_tz: timezone = UTC) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    else:
        text = _text(value)
        if not text:
            return None
        normalized = text.replace("Z", "+00:00").replace("/", "-")
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError:
            parsed = None
            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
                try:
                    parsed = datetime.strptime(text, fmt)
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
            parsed = _parse_datetime(value, naive_tz=SHANGHAI)
            if parsed:
                return parsed
    day = _text(_first(row, "matchDate", "match_date"))
    clock = _text(_first(row, "matchTime", "match_time"))
    return _parse_datetime(f"{day}T{clock[:8]}+08:00") if day and clock else None


def _name_key(value: Any) -> str:
    normalized = unicodedata.normalize("NFKC", _text(value)).casefold()
    return "".join(char for char in normalized if char.isalnum())


def _digest(value: Any) -> str:
    text = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _provider_hints(row: Mapping[str, Any], side: str) -> tuple[str | None, str | None]:
    provider = _nested(row, "api_football", "apiFootball", "provider_identity")
    side_row = provider.get(side) if isinstance(provider.get(side), Mapping) else {}
    ids = provider.get("provider_team_ids")
    team_id = (
        _first(side_row, "team_id", "provider_team_id", "api_football_team_id")
        or _first(provider, f"{side}_team_id", f"{side}_provider_team_id", f"{side}_api_football_team_id")
        or (ids.get(side) if isinstance(ids, Mapping) else None)
        or _first(row, f"api_football_{side}_team_id", f"provider_{side}_team_id")
    )
    team_name = (
        _first(side_row, "name", "team_name", "provider_team_name")
        or _first(provider, f"{side}_name", f"{side}_team_name", f"{side}_provider_team_name")
        or _first(row, f"api_football_{side}_team_name", f"provider_{side}_team_name")
    )
    return _text(team_id) or None, _text(team_name) or None


def _provider_fixture_hint(row: Mapping[str, Any]) -> str | None:
    provider = _nested(row, "api_football", "apiFootball", "provider_identity")
    return _text(
        _first(provider, "fixture_id", "provider_fixture_id", "api_football_fixture_id")
        or _first(row, "api_football_fixture_id", "provider_fixture_id")
    ) or None


def _competition(row: Mapping[str, Any]) -> tuple[str, int | None]:
    label = _text(_first(row, "league", "competition", "competition_name", "league_name"))
    provider = _nested(row, "api_football", "apiFootball", "provider_identity")
    raw_id = _first(provider, "league_id", "provider_league_id", "api_football_league_id") or _first(
        row, "api_football_league_id", "provider_league_id"
    )
    try:
        league_id = int(raw_id) if raw_id not in (None, "") else None
    except (TypeError, ValueError):
        league_id = None
    if league_id is None and label in COMPETITION_ALIASES:
        league_id = COMPETITION_ALIASES[label][0]
    return label, league_id


@dataclass(frozen=True)
class CanonicalFixture:
    canonical_match_id: str
    canonical_match_digest: str
    nowscore_id: str
    home_team_name: str
    away_team_name: str
    kickoff_at: datetime
    competition_label: str
    provider_league_id: int | None
    season: int
    provider_fixture_id: str | None
    provider_home_team_id: str | None
    provider_away_team_id: str | None
    provider_home_team_name: str | None
    provider_away_team_name: str | None


@dataclass(frozen=True)
class CohortDeclaration:
    matches: tuple[CanonicalFixture, ...]
    source_rows: int
    future_rows: int
    excluded_past_rows: int
    invalid_rows: int
    duplicate_match_count: int
    source_status: str
    source_path: str
    as_of: datetime

    @property
    def valid(self) -> bool:
        return self.source_status == "READY" and bool(self.matches) and not self.invalid_rows and not self.duplicate_match_count

    def public_summary(self) -> dict[str, Any]:
        count = len(self.matches)
        return {
            "source_path": self.source_path,
            "source_status": self.source_status,
            "as_of": self.as_of.isoformat(),
            "declared_match_count": count,
            "target_range": {"minimum": MIN_COHORT_MATCHES, "maximum": MAX_COHORT_MATCHES, "within_range": MIN_COHORT_MATCHES <= count <= MAX_COHORT_MATCHES},
            "source_rows": self.source_rows,
            "future_rows": self.future_rows,
            "excluded_past_rows": self.excluded_past_rows,
            "invalid_rows": self.invalid_rows,
            "duplicate_match_count": self.duplicate_match_count,
            "one_match_one_observation": self.duplicate_match_count == 0,
            "future_only": bool(self.matches) and all(item.kickoff_at > self.as_of for item in self.matches),
            "competition_count": len({item.competition_label for item in self.matches}),
            "matches": [
                {
                    "canonical_match_digest": item.canonical_match_digest,
                    "kickoff_at": item.kickoff_at.isoformat(),
                    "provider_league_id_present": item.provider_league_id is not None,
                    "provider_identity_hints_present": bool(
                        (item.provider_home_team_id or item.provider_home_team_name)
                        and (item.provider_away_team_id or item.provider_away_team_name)
                    ),
                }
                for item in self.matches
            ],
            "notes": (["available_future_cohort_below_target_range"] if count < MIN_COHORT_MATCHES else []),
        }


def _load_rows(path: Path) -> tuple[list[Mapping[str, Any]], str]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AuditIntegrityError(f"COHORT_READ_FAILED:{type(exc).__name__}") from exc
    if not isinstance(payload, Mapping):
        raise AuditIntegrityError("COHORT_PAYLOAD_NOT_OBJECT")
    rows = payload.get("fixtures") if isinstance(payload.get("fixtures"), list) else payload.get("matches")
    if not isinstance(rows, list):
        raise AuditIntegrityError("COHORT_FIXTURES_NOT_LIST")
    return [row for row in rows if isinstance(row, Mapping)], _text(payload.get("status")) or "UNKNOWN"


def _make_fixture(row: Mapping[str, Any], as_of: datetime) -> CanonicalFixture | None:
    nowscore_id = _text(_first(row, "nowscore_id", "nowscoreId", "matchId", "match_id"))
    home = _text(_first(row, "homeTeam", "home_team", "home"))
    away = _text(_first(row, "awayTeam", "away_team", "away"))
    kickoff = _target_kickoff(row)
    if not nowscore_id or not home or not away or not kickoff or kickoff <= as_of:
        return None
    if not trusted_nowscore_jc_fixture(row, nowscore_id).get("trusted"):
        return None
    competition_label, league_id = _competition(row)
    if not competition_label:
        return None
    match_key = canonical_match_id({"home": home, "away": away, "kickoff": kickoff.isoformat()})
    home_id, home_name = _provider_hints(row, "home")
    away_id, away_name = _provider_hints(row, "away")
    return CanonicalFixture(
        match_key,
        _digest(match_key),
        nowscore_id,
        home,
        away,
        kickoff,
        competition_label,
        league_id,
        kickoff.year,
        _provider_fixture_hint(row),
        home_id,
        away_id,
        home_name,
        away_name,
    )


def declare_cohort(path: str | Path, *, as_of: datetime | None = None, max_matches: int = MAX_COHORT_MATCHES) -> CohortDeclaration:
    if not 1 <= int(max_matches) <= MAX_COHORT_MATCHES:
        raise ValueError(f"max_matches must be between 1 and {MAX_COHORT_MATCHES}")
    source_path = Path(path)
    observed_at = (as_of or datetime.now(UTC)).astimezone(UTC)
    rows, status = _load_rows(source_path)
    future_rows = excluded_past_rows = invalid_rows = duplicate_count = 0
    candidates: list[CanonicalFixture] = []
    for row in rows:
        kickoff = _target_kickoff(row)
        if kickoff and kickoff > observed_at:
            future_rows += 1
        else:
            excluded_past_rows += 1
        candidate = _make_fixture(row, observed_at)
        if candidate:
            candidates.append(candidate)
        elif kickoff and kickoff > observed_at:
            invalid_rows += 1
    unique: dict[str, CanonicalFixture] = {}
    for candidate in sorted(candidates, key=lambda item: (item.kickoff_at, item.canonical_match_id)):
        if candidate.canonical_match_id in unique:
            duplicate_count += 1
        else:
            unique[candidate.canonical_match_id] = candidate
    selected = tuple(list(unique.values())[: int(max_matches)])
    return CohortDeclaration(
        selected,
        len(rows),
        future_rows,
        excluded_past_rows,
        invalid_rows,
        duplicate_count,
        status,
        source_path.as_posix(),
        observed_at,
    )


@dataclass(frozen=True)
class ProviderResponse:
    payload: Mapping[str, Any] | None
    acquired_at: datetime
    response_sha256: str | None
    http_status: int | None = None
    error_code: str | None = None


class RequestBudget:
    def __init__(self, *, max_requests: int = MAX_REQUESTS, max_per_minute: int = MAX_REQUESTS_PER_MINUTE, monotonic: Callable[[], float] = time.monotonic, sleep: Callable[[float], None] = time.sleep) -> None:
        if not 1 <= max_requests <= MAX_REQUESTS or not 1 <= max_per_minute <= MAX_REQUESTS_PER_MINUTE:
            raise ValueError("request limits must be positive and within the Issue #263 caps")
        self.max_requests, self.max_per_minute = int(max_requests), int(max_per_minute)
        self._monotonic, self._sleep, self._times = monotonic, sleep, []
        self.used = self.waited_seconds = 0

    def reserve(self) -> None:
        if self.used >= self.max_requests:
            raise RequestBudgetExceeded("REQUEST_BUDGET_EXCEEDED")
        while True:
            now = self._monotonic()
            self._times = [stamp for stamp in self._times if now - stamp < 60]
            if len(self._times) < self.max_per_minute:
                self._times.append(now)
                self.used += 1
                return
            wait = max(0.0, 60 - (now - self._times[0]))
            before = self._monotonic()
            self._sleep(wait)
            after = self._monotonic()
            self.waited_seconds += wait
            if after <= before:
                raise RateLimitBlocked("RATE_LIMIT_WAIT_DID_NOT_ADVANCE")


class ApiFootballClient:
    def __init__(self, api_key: str, *, base_url: str = API_BASE_URL, opener: Callable[..., Any] = urlopen, now: Callable[[], datetime] = lambda: datetime.now(UTC), budget: RequestBudget | None = None, timeout: float = 30.0) -> None:
        self.api_key, self.base_url, self.opener, self.now = _text(api_key), base_url.rstrip("/"), opener, now
        if not self.api_key:
            raise ValueError("API key is required")
        self.budget, self.timeout = budget or RequestBudget(), timeout

    def get(self, path: str, params: Mapping[str, Any]) -> ProviderResponse:
        self.budget.reserve()
        query = urlencode(sorted((str(key), str(value)) for key, value in params.items()))
        url = f"{self.base_url}{path}" + (f"?{query}" if query else "")
        request = Request(url, headers={"Accept": "application/json", "User-Agent": "FBOS-prematch-evidence-audit/1", "x-apisports-key": self.api_key}, method="GET")
        acquired_at = _parse_datetime(self.now()) or datetime.now(UTC)
        try:
            response = self.opener(request, timeout=self.timeout)
            try:
                raw = response.read()
                status = int(getattr(response, "status", 200))
            finally:
                close = getattr(response, "close", None)
                if callable(close):
                    close()
        except HTTPError as exc:
            return ProviderResponse(None, acquired_at, None, int(exc.code), f"HTTP_{exc.code}")
        except (URLError, OSError, TimeoutError):
            return ProviderResponse(None, acquired_at, None, None, "NETWORK_ERROR")
        if isinstance(raw, str):
            raw = raw.encode("utf-8")
        response_hash = hashlib.sha256(raw).hexdigest()
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return ProviderResponse(None, acquired_at, response_hash, status, "INVALID_JSON")
        return ProviderResponse(payload if isinstance(payload, Mapping) else None, acquired_at, response_hash, status, None if isinstance(payload, Mapping) else "PAYLOAD_NOT_OBJECT")


def _rows(payload: Mapping[str, Any] | None) -> list[Mapping[str, Any]]:
    if not isinstance(payload, Mapping):
        return []
    value = payload.get("response")
    if isinstance(value, Mapping):
        return [value]
    return [row for row in value if isinstance(row, Mapping)] if isinstance(value, list) else []


def _provider_error(payload: Mapping[str, Any] | None) -> bool:
    return not isinstance(payload, Mapping) or bool(payload.get("errors"))


def _coverage(payload: Mapping[str, Any] | None, season: int) -> dict[str, bool]:
    for row in _rows(payload):
        seasons = row.get("seasons")
        if not isinstance(seasons, list):
            continue
        selected = next((item for item in seasons if isinstance(item, Mapping) and str(item.get("season")) == str(season)), None)
        if isinstance(selected, Mapping) and isinstance(selected.get("coverage"), Mapping):
            return {str(key): value is True for key, value in selected["coverage"].items()}
    return {}


def _candidate_id(row: Mapping[str, Any]) -> str | None:
    fixture = row.get("fixture")
    return _text(_first(fixture, "id", "fixture_id")) if isinstance(fixture, Mapping) else None


def _candidate_kickoff(row: Mapping[str, Any]) -> datetime | None:
    fixture = row.get("fixture")
    if not isinstance(fixture, Mapping):
        return None
    parsed = _parse_datetime(fixture.get("date"))
    if parsed:
        return parsed
    try:
        return datetime.fromtimestamp(float(fixture.get("timestamp")), UTC)
    except (TypeError, ValueError, OSError):
        return None


def _candidate_league_id(row: Mapping[str, Any]) -> int | None:
    league = row.get("league")
    try:
        return int(league.get("id")) if isinstance(league, Mapping) else None
    except (TypeError, ValueError):
        return None


def _candidate_team(row: Mapping[str, Any], side: str) -> tuple[str | None, str | None]:
    teams = row.get("teams")
    team = teams.get(side) if isinstance(teams, Mapping) else None
    return (_text(_first(team, "id", "team_id")) or None, _text(_first(team, "name", "team_name")) or None) if isinstance(team, Mapping) else (None, None)


def _same_identity(target: CanonicalFixture, candidate: Mapping[str, Any]) -> tuple[bool, str]:
    candidate_fixture_id = _candidate_id(candidate)
    if target.provider_fixture_id:
        if candidate_fixture_id != target.provider_fixture_id:
            return False, "PROVIDER_FIXTURE_ID_MISMATCH"
        if not ((target.provider_home_team_id or target.provider_home_team_name) and (target.provider_away_team_id or target.provider_away_team_name)):
            return True, "EXACT_PROVIDER_FIXTURE_ID"
    hints = ((target.provider_home_team_id, target.provider_home_team_name), (target.provider_away_team_id, target.provider_away_team_name))
    if not all(item[0] or item[1] for item in hints):
        return False, "NO_REVIEWED_PROVIDER_TEAM_HINTS"
    for side, (expected_id, expected_name) in zip(("home", "away"), hints):
        actual_id, actual_name = _candidate_team(candidate, side)
        if expected_id and actual_id != expected_id:
            return False, f"{side.upper()}_IDENTITY_MISMATCH"
        if not expected_id and (not expected_name or not actual_name or _name_key(expected_name) != _name_key(actual_name)):
            return False, f"{side.upper()}_IDENTITY_MISMATCH"
    return True, "EXACT_PROVIDER_IDS_OR_NAMES"


def resolve_provider_fixture(target: CanonicalFixture, candidates: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    matches: list[tuple[Mapping[str, Any], float]] = []
    reasons = Counter()
    for candidate in candidates:
        if target.provider_league_id is not None and _candidate_league_id(candidate) != target.provider_league_id:
            continue
        provider_time = _candidate_kickoff(candidate)
        if not provider_time:
            continue
        delta = abs((provider_time - target.kickoff_at).total_seconds()) / 60
        if delta > MAX_KICKOFF_DELTA_MINUTES:
            continue
        same, reason = _same_identity(target, candidate)
        if same:
            matches.append((candidate, delta))
        else:
            reasons[reason] += 1
    if len(matches) > 1:
        return {"status": "AMBIGUOUS_MATCH", "candidate_count": len(matches), "identity_reasons": dict(reasons)}
    if not matches:
        return {"status": "IDENTITY_NOT_READY" if reasons.get("NO_REVIEWED_PROVIDER_TEAM_HINTS") else "NO_EXACT_MATCH", "candidate_count": 0, "identity_reasons": dict(reasons)}
    candidate, delta = matches[0]
    return {"status": "EXACT_MATCH", "candidate_count": 1, "kickoff_delta_minutes": round(delta, 3), "candidate": candidate, "provider_fixture_id": _candidate_id(candidate)}


def _walk(value: Any) -> Iterable[Mapping[str, Any]]:
    if isinstance(value, Mapping):
        yield value
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def _update_timestamps(value: Any) -> list[datetime]:
    timestamps: list[datetime] = []
    for mapping in _walk(value):
        for key, raw_value in mapping.items():
            if str(key).casefold() in {"update", "updated_at", "updatedat", "last_update", "timestamp"}:
                parsed = _parse_datetime(raw_value)
                if parsed:
                    timestamps.append(parsed)
    return timestamps


def summarize_prematch_payload(family: str, payload: Mapping[str, Any] | None, *, target_kickoff: datetime, acquired_at: datetime) -> dict[str, Any]:
    raw_rows = _rows(payload)
    rows = raw_rows
    if family == "earlier_matches":
        rows = [row for row in raw_rows if (_candidate_kickoff(row) or target_kickoff) < target_kickoff]
    timestamps = [timestamp for row in raw_rows for timestamp in _update_timestamps(row)]
    if family in POSTMATCH_FAMILIES or acquired_at.astimezone(UTC) >= target_kickoff.astimezone(UTC):
        usable, suppressed = [], len(raw_rows)
    else:
        usable = [row for row in rows if not any(stamp > target_kickoff for stamp in _update_timestamps(row))]
        suppressed = len(raw_rows) - len(usable)
    return {
        "response_present": payload is not None,
        "provider_row_count": len(raw_rows),
        "usable_prematch_row_count": len(usable),
        "post_kickoff_suppressed_row_count": suppressed,
        "provider_update_timestamp_present": bool(timestamps),
        "provider_update_timestamp_count": len(timestamps),
        "field_presence": {field: any(any(str(key).casefold() == field.casefold() for mapping in _walk(row) for key in mapping) for row in usable) for field in SUMMARY_FIELDS.get(family, ())},
    }


def _empty(family: str, supported: bool) -> dict[str, Any]:
    return {"requested": False, "supported_by_coverage": supported, "suppression_reason": "coverage_flag_false_or_missing", "provider_row_count": 0, "usable_prematch_row_count": 0, "post_kickoff_suppressed_row_count": 0, "provider_update_timestamp_present": False, "provider_update_timestamp_count": 0, "field_presence": {field: False for field in SUMMARY_FIELDS.get(family, ())}}


def _merge(destination: dict[str, Any], source: Mapping[str, Any]) -> None:
    for key in ("provider_row_count", "usable_prematch_row_count", "post_kickoff_suppressed_row_count", "provider_update_timestamp_count"):
        destination[key] += int(source.get(key) or 0)
    destination["provider_update_timestamp_present"] |= bool(source.get("provider_update_timestamp_present"))
    for field, present in source.get("field_presence", {}).items():
        destination["field_presence"][field] |= bool(present)


@dataclass
class AuditRunner:
    client: Any
    declaration: CohortDeclaration
    calls: list[dict[str, Any]] = field(default_factory=list)
    errors: Counter[str] = field(default_factory=Counter)
    cache: dict[tuple[str, tuple[tuple[str, str], ...]], ProviderResponse] = field(default_factory=dict)
    fixture_resolution_failed: bool = False

    def request(self, family: str, path: str, params: Mapping[str, Any]) -> ProviderResponse:
        if len(self.calls) >= MAX_REQUESTS:
            raise RequestBudgetExceeded("REQUEST_BUDGET_EXCEEDED")
        key = (path, tuple(sorted((str(k), str(v)) for k, v in params.items())))
        if key in self.cache:
            return self.cache[key]
        response = self.client.get(path, params)
        self.cache[key] = response
        self.calls.append({"family": family, "path": path, "acquired_at": response.acquired_at.isoformat(), "response_sha256_present": bool(response.response_sha256), "error_code": response.error_code})
        if response.error_code:
            self.errors[response.error_code] += 1
        return response

    @staticmethod
    def payload(response: ProviderResponse) -> Mapping[str, Any] | None:
        return None if response.error_code or _provider_error(response.payload) else response.payload

    def resolve(self) -> dict[str, dict[str, Any]]:
        by_date: dict[date, list[CanonicalFixture]] = {}
        for target in self.declaration.matches:
            by_date.setdefault(target.kickoff_at.astimezone(SHANGHAI).date(), []).append(target)
        output = {}
        for calendar_date, targets in sorted(by_date.items()):
            response = self.request("fixture_resolution", "/fixtures", {"date": calendar_date.isoformat()})
            payload = self.payload(response)
            if response.error_code or _provider_error(response.payload):
                self.fixture_resolution_failed = True
            for target in targets:
                output[target.canonical_match_id] = resolve_provider_fixture(target, _rows(payload))
        return output

    def coverage(self, target: CanonicalFixture) -> dict[str, Any]:
        if target.provider_league_id is None:
            return {"season_specific_available": False, "flags": {}}
        response = self.request("coverage", "/leagues", {"id": target.provider_league_id, "season": target.season})
        flags = _coverage(self.payload(response), target.season)
        return {"season_specific_available": bool(flags), "flags": dict(sorted(flags.items()))}

    def call_family(self, target: CanonicalFixture, family: str, path: str, params: Mapping[str, Any]) -> dict[str, Any]:
        response = self.request(family, path, params)
        summary = summarize_prematch_payload(family, self.payload(response), target_kickoff=target.kickoff_at, acquired_at=response.acquired_at)
        summary.update({"requested": True, "supported_by_coverage": True, "response_sha256_present": bool(response.response_sha256)})
        return summary

    def audit_exact(self, target: CanonicalFixture, resolution: Mapping[str, Any], coverage: Mapping[str, Any]) -> dict[str, Any]:
        flags = coverage.get("flags", {})
        candidate = resolution.get("candidate", {})
        provider_fixture_id = _text(resolution.get("provider_fixture_id"))
        evidence = {family: _empty(family, any(flags.get(key) is True for key in keys)) for family, keys in COVERAGE_KEYS.items()}
        if not provider_fixture_id:
            return {"coverage": dict(coverage), "evidence": evidence}
        for family, path in (("lineups", "/fixtures/lineups"), ("injuries", "/injuries"), ("odds", "/odds")):
            if any(flags.get(key) is True for key in COVERAGE_KEYS[family]):
                evidence[family] = self.call_family(target, family, path, {"fixture": provider_fixture_id})
        team_ids = sorted({team_id for team_id in (_candidate_team(candidate, "home")[0], _candidate_team(candidate, "away")[0]) if team_id})
        prior_ids: list[str] = []
        if flags.get("fixtures") is True:
            history = []
            for team_id in team_ids:
                response = self.request("earlier_matches", "/fixtures", {"team": team_id, "last": 5})
                payload = self.payload(response)
                details = summarize_prematch_payload("earlier_matches", payload, target_kickoff=target.kickoff_at, acquired_at=response.acquired_at)
                history.append(details)
                prior_ids.extend(_candidate_id(row) for row in _rows(payload) if _candidate_id(row) and (_candidate_kickoff(row) or target.kickoff_at) < target.kickoff_at)
            evidence["earlier_matches"]["requested"] = bool(team_ids)
            evidence["earlier_matches"]["supported_by_coverage"] = True
            for details in history:
                _merge(evidence["earlier_matches"], details)
            evidence["earlier_matches"]["history_fixture_id_count"] = len(dict.fromkeys(prior_ids))
        for prior_id in list(dict.fromkeys(prior_ids))[:2]:
            if any(flags.get(key) is True for key in COVERAGE_KEYS["earlier_statistics"]):
                evidence["earlier_statistics"]["requested"] = True
                _merge(evidence["earlier_statistics"], self.call_family(target, "earlier_statistics", "/fixtures/statistics", {"fixture": prior_id}))
        return {"coverage": dict(coverage), "evidence": evidence}

    def run(self) -> dict[str, Any]:
        if not self.declaration.valid:
            return {"decision": "FAIL_CLOSED", "reason": "INVALID_OR_NON_UNIQUE_FUTURE_COHORT", "cohort": self.declaration.public_summary(), "matches": []}
        resolutions = self.resolve()
        summaries = []
        exact = []
        for target in self.declaration.matches:
            resolution = resolutions[target.canonical_match_id]
            row = {"canonical_match_digest": target.canonical_match_digest, "identity_status": resolution["status"], "kickoff_delta_minutes": resolution.get("kickoff_delta_minutes"), "provider_candidate_count": int(resolution.get("candidate_count") or 0)}
            summaries.append(row)
            if resolution["status"] == "EXACT_MATCH":
                exact.append((target, resolution, row))
        for target, resolution, row in exact:
            coverage = self.coverage(target)
            details = self.audit_exact(target, resolution, coverage)
            row.update(details)
        if self.fixture_resolution_failed:
            decision, reason = "FAIL_CLOSED", "PROVIDER_FIXTURE_RESOLUTION_FAILED"
        elif not exact:
            decision, reason = "IDENTITY_NOT_READY", "NO_EXACT_PROVIDER_FIXTURE_IDENTITY"
        else:
            useful = sum(any(int((row.get("evidence", {}).get(family, {}).get("usable_prematch_row_count") or 0)) > 0 for family in COVERAGE_KEYS) for _target, _resolution, row in exact)
            enough_exact = len(exact) >= max(1, (len(self.declaration.matches) + 1) // 2)
            decision, reason = (("EVIDENCE_SUBSTRATE_PROBE_READY", "EXACT_FUTURE_MATCHES_EXPOSE_TIME_SAFE_FIELDS") if enough_exact and useful >= max(1, (len(exact) + 1) // 2) else ("COVERAGE_TOO_THIN", "EXACT_MATCHES_OR_TIME_SAFE_FIELDS_TOO_SPARSE"))
        return {"decision": decision, "reason": reason, "cohort": self.declaration.public_summary(), "matches": summaries}


def _request_summary(calls: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    families = Counter(call["family"] for call in calls)
    paths = Counter(call["path"] for call in calls)
    return {"used": len(calls), "max": MAX_REQUESTS, "rate_limit_per_minute": MAX_REQUESTS_PER_MINUTE, "within_budget": len(calls) <= MAX_REQUESTS, "error_count": sum(bool(call.get("error_code")) for call in calls), "families": dict(sorted(families.items())), "paths": dict(sorted(paths.items())), "response_hash_count": sum(bool(call.get("response_sha256_present")) for call in calls), "acquired_at_first": calls[0]["acquired_at"] if calls else None, "acquired_at_last": calls[-1]["acquired_at"] if calls else None}


def _secret_guard(summary: Mapping[str, Any], secret: str) -> None:
    if secret and secret in json.dumps(summary, ensure_ascii=False, sort_keys=True):
        raise AuditIntegrityError("SECRET_OUTPUT_GUARD")


def run_bounded_audit(cohort_path: str | Path, *, api_key: str | None = None, as_of: datetime | None = None, client: Any | None = None, max_matches: int = MAX_COHORT_MATCHES) -> dict[str, Any]:
    declaration = declare_cohort(cohort_path, as_of=as_of, max_matches=max_matches)
    secret = _text(api_key)
    summary = {"contract_version": CONTRACT_VERSION, "provider": PROVIDER_NAME, "existing_fbos_state_memory_contract": EXISTING_STATE_MEMORY_CONTRACT, "decision": "FAIL_CLOSED", "api_key_present": bool(secret), "api_key_persisted": False, "raw_provider_responses_written": False, "public_summary_only": True, "matching_policy": "provider IDs or exact normalized names only; no fuzzy, result-aware, or manual post-hoc matching", "cohort": declaration.public_summary(), "requests": _request_summary(()), "matches": []}
    if not secret:
        summary.update({"decision": "FOUNDER_SECRET_REQUIRED", "reason": "API_FOOTBALL_KEY_NOT_AVAILABLE_IN_EXECUTION_ENVIRONMENT"})
        _secret_guard(summary, secret)
        return summary
    try:
        runner = AuditRunner(client or ApiFootballClient(secret), declaration)
        summary.update(runner.run())
        summary["requests"] = _request_summary(runner.calls)
    except AuditIntegrityError as exc:
        summary.update({"decision": "FAIL_CLOSED", "reason": str(exc)})
        if "runner" in locals():
            summary["requests"] = _request_summary(runner.calls)
    _secret_guard(summary, secret)
    return summary


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cohort-path", default="data/prediction_universe/2026-09-10.json")
    parser.add_argument("--output")
    parser.add_argument("--as-of")
    parser.add_argument("--max-matches", type=int, default=MAX_COHORT_MATCHES)
    args = parser.parse_args(argv)
    as_of = _parse_datetime(args.as_of) if args.as_of else None
    if args.as_of and not as_of:
        raise SystemExit("--as-of must be an ISO timestamp")
    summary = run_bounded_audit(args.cohort_path, api_key=_text(os.environ.get(API_KEY_ENV)), as_of=as_of, max_matches=args.max_matches)
    text = json.dumps(summary, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        destination = Path(args.output)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
