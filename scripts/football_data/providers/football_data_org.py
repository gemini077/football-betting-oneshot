"""Provider-scoped recent-form route for football-data.org v4.

The adapter is deliberately independent from the canonical team registry.  A
fixture is first bridged by exact competition and UTC kickoff, then the
provider's stable team IDs are used for finished-match history.  The returned
form is the existing Champion four-block contract, while every identity field
stays explicitly provider-scoped.

Network access is opt-in through ``FOOTBALL_DATA_ORG_TOKEN``.  The client can
read a fresh local response cache without a token, but it never makes a live
request without one.  The default cache is runtime state and is not a source
of committed evidence.
"""

from __future__ import annotations

import hashlib
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_API_BASE_URL = "https://api.football-data.org/v4"
DEFAULT_COVERAGE_MANIFEST_PATH = PROJECT_ROOT / "data" / "football_data" / "pred_avail_2" / "football_data_org_coverage.json"
DEFAULT_CACHE_ROOT = PROJECT_ROOT / "data" / "product_runtime" / "football_data_org_recent_form"
TOKEN_ENV = "FOOTBALL_DATA_ORG_TOKEN"
PROVIDER_NAME = "football-data.org"
PROVIDER_SCHEMA = "football-data.org-api-v4"
RESPONSE_CACHE_CONTRACT = "football_data_org_response_cache.v1"
FREE_CALLS_PER_MINUTE = 10
DEFAULT_FIXTURE_CACHE_TTL_SECONDS = 6 * 60 * 60
DEFAULT_TEAM_MATCH_CACHE_TTL_SECONDS = 6 * 60 * 60
DEFAULT_MAX_HISTORY_AGE_DAYS = 60
DEFAULT_FORM_WINDOW = 5
UPCOMING_STATUSES = frozenset({"SCHEDULED", "TIMED"})


class FootballDataOrgError(RuntimeError):
    """Base class for provider adapter failures."""


class CredentialMissingError(FootballDataOrgError):
    """Raised before network access when the provider token is absent."""


class ProviderResponseError(FootballDataOrgError):
    """Raised for non-JSON or non-success provider responses."""


class ProviderDataConflictError(FootballDataOrgError):
    """Raised when one provider match ID has conflicting observations."""


def _parse_timestamp(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _iso(value: Any) -> str | None:
    parsed = _parse_timestamp(value)
    return parsed.replace(microsecond=0).isoformat().replace("+00:00", "Z") if parsed else None


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _strict_provider_id(value: Any) -> str | None:
    if isinstance(value, bool) or value in (None, ""):
        return None
    text = str(value).strip()
    if not text.isdigit() or int(text) <= 0:
        return None
    return str(int(text))


def _text(value: Any) -> str:
    return str(value or "").strip()


def _normalise_alias(value: Any) -> str:
    return " ".join(_text(value).casefold().split())


def _provider_team_key(provider_team_id: str) -> str:
    return f"{PROVIDER_NAME}:team:{provider_team_id}"


def _unique(values: Iterable[Any]) -> list[str]:
    result: list[str] = []
    for value in values:
        text = _text(value)
        if text and text not in result:
            result.append(text)
    return result


@dataclass
class RequestAccounting:
    """Observable request/cache counters for one bounded route run."""

    requests: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    credential_blocks: int = 0
    endpoint_counts: dict[str, int] = field(default_factory=dict)

    def record_request(self, endpoint: str) -> None:
        self.requests += 1
        self.endpoint_counts[endpoint] = self.endpoint_counts.get(endpoint, 0) + 1

    def snapshot(self) -> dict[str, Any]:
        return {
            "request_count": self.requests,
            "cache_hit_count": self.cache_hits,
            "cache_miss_count": self.cache_misses,
            "credential_block_count": self.credential_blocks,
            "endpoint_counts": dict(sorted(self.endpoint_counts.items())),
            "free_tier_calls_per_minute": FREE_CALLS_PER_MINUTE,
        }


@dataclass(frozen=True)
class CachedResponse:
    payload: dict[str, Any]
    fetched_at: str


class JsonResponseCache:
    """Small content-addressed JSON response cache with explicit TTL."""

    def __init__(self, root: str | Path | None = DEFAULT_CACHE_ROOT) -> None:
        self.root = Path(root) if root is not None else None

    def _path(self, request_key: str) -> Path | None:
        if self.root is None:
            return None
        digest = hashlib.sha256(request_key.encode("utf-8")).hexdigest()
        return self.root / f"{digest}.json"

    def read(self, request_key: str, *, now: datetime, ttl_seconds: int) -> CachedResponse | None:
        path = self._path(request_key)
        if path is None or ttl_seconds < 0:
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(payload, Mapping) or payload.get("contract_version") != RESPONSE_CACHE_CONTRACT:
            return None
        fetched_at = _parse_timestamp(payload.get("fetched_at"))
        response = payload.get("payload")
        if fetched_at is None or not isinstance(response, Mapping):
            return None
        age = (now - fetched_at).total_seconds()
        if age < 0 or age > ttl_seconds:
            return None
        return CachedResponse(dict(response), _iso(fetched_at) or "")

    def write(self, request_key: str, payload: Mapping[str, Any], *, fetched_at: str) -> None:
        path = self._path(request_key)
        if path is None:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        envelope = {
            "contract_version": RESPONSE_CACHE_CONTRACT,
            "request_key": request_key,
            "fetched_at": fetched_at,
            "payload": dict(payload),
        }
        path.write_text(json.dumps(envelope, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


@dataclass(frozen=True)
class ProviderResponse:
    payload: dict[str, Any]
    fetched_at: str
    source_url: str
    cache_hit: bool


def _default_transport(url: str, headers: Mapping[str, str]) -> Mapping[str, Any]:
    request = urllib.request.Request(url, headers=dict(headers), method="GET")
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            raw = response.read()
    except urllib.error.HTTPError as error:
        raise ProviderResponseError(f"HTTP_{error.code}") from error
    except urllib.error.URLError as error:
        raise ProviderResponseError("NETWORK_ERROR") from error
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ProviderResponseError("INVALID_JSON") from error
    if not isinstance(value, Mapping):
        raise ProviderResponseError("INVALID_RESPONSE_SHAPE")
    return dict(value)


class FootballDataOrgClient:
    """Minimal authenticated v4 client with response-level cache reuse."""

    provider_name = PROVIDER_NAME
    provider_version = PROVIDER_SCHEMA

    def __init__(
        self,
        *,
        token: str | None = None,
        base_url: str = DEFAULT_API_BASE_URL,
        transport: Callable[[str, Mapping[str, str]], Mapping[str, Any] | bytes] | None = None,
        cache: JsonResponseCache | None = None,
        cache_root: str | Path | None = DEFAULT_CACHE_ROOT,
        accounting: RequestAccounting | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.token = (token if token is not None else os.environ.get(TOKEN_ENV, "")).strip() or None
        self.base_url = base_url.rstrip("/")
        self.transport = transport or _default_transport
        self.cache = cache or JsonResponseCache(cache_root)
        self.accounting = accounting or RequestAccounting()
        self.clock = clock or _now

    @staticmethod
    def _endpoint(path: str) -> str:
        return path.strip("/").removeprefix("v4/")

    def _url(self, path: str, params: Mapping[str, Any]) -> str:
        clean_path = "/" + path.strip("/")
        query = urllib.parse.urlencode({key: value for key, value in params.items() if value not in (None, "")})
        return f"{self.base_url}{clean_path}" + (f"?{query}" if query else "")

    def get_json(
        self,
        path: str,
        params: Mapping[str, Any] | None = None,
        *,
        ttl_seconds: int = DEFAULT_TEAM_MATCH_CACHE_TTL_SECONDS,
        now: datetime | str | None = None,
    ) -> ProviderResponse:
        query = dict(params or {})
        url = self._url(path, query)
        request_key = f"GET {url}"
        current = _parse_timestamp(now) if now is not None else _parse_timestamp(self.clock())
        if current is None:
            raise ProviderResponseError("INVALID_CLOCK")
        cached = self.cache.read(request_key, now=current, ttl_seconds=ttl_seconds)
        if cached is not None:
            self.accounting.cache_hits += 1
            return ProviderResponse(cached.payload, cached.fetched_at, url, True)
        self.accounting.cache_misses += 1
        if not self.token:
            self.accounting.credential_blocks += 1
            raise CredentialMissingError(TOKEN_ENV)
        headers = {
            "Accept": "application/json",
            "User-Agent": "football-betting-oneshot/football-data-org",
            "X-Auth-Token": self.token,
        }
        self.accounting.record_request(self._endpoint(path))
        value = self.transport(url, headers)
        if isinstance(value, bytes):
            try:
                value = json.loads(value.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise ProviderResponseError("INVALID_JSON") from error
        if not isinstance(value, Mapping):
            raise ProviderResponseError("INVALID_RESPONSE_SHAPE")
        fetched_at = _iso(current) or ""
        payload = dict(value)
        self.cache.write(request_key, payload, fetched_at=fetched_at)
        return ProviderResponse(payload, fetched_at, url, False)

    def get_competition_matches(
        self,
        competition_code: str,
        target_date: date,
        *,
        now: datetime | str | None = None,
    ) -> ProviderResponse:
        date_value = target_date.isoformat()
        return self.get_json(
            f"/competitions/{competition_code}/matches",
            {"dateFrom": date_value, "dateTo": date_value},
            ttl_seconds=DEFAULT_FIXTURE_CACHE_TTL_SECONDS,
            now=now,
        )

    def get_team_matches(
        self,
        provider_team_id: str,
        competition_code: str,
        cutoff_at: str,
        *,
        max_history_age_days: int = DEFAULT_MAX_HISTORY_AGE_DAYS,
        now: datetime | str | None = None,
    ) -> ProviderResponse:
        cutoff = _parse_timestamp(cutoff_at)
        if cutoff is None or max_history_age_days < 0:
            raise ProviderResponseError("INVALID_TEAM_HISTORY_WINDOW")
        date_from = (cutoff - timedelta(days=max_history_age_days)).date().isoformat()
        date_to = cutoff.date().isoformat()
        return self.get_json(
            f"/teams/{_strict_provider_id(provider_team_id) or provider_team_id}/matches",
            {
                "dateFrom": date_from,
                "dateTo": date_to,
                "competitions": competition_code,
                "status": "FINISHED",
                "limit": 100,
            },
            ttl_seconds=DEFAULT_TEAM_MATCH_CACHE_TTL_SECONDS,
            now=now,
        )


def _coverage_rows(manifest: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = manifest.get("competitions")
    if not isinstance(rows, list):
        return []
    result: list[dict[str, Any]] = []
    for raw in rows:
        if not isinstance(raw, Mapping):
            continue
        canonical_id = _text(raw.get("canonical_competition_id"))
        if not canonical_id:
            continue
        aliases = raw.get("aliases") if isinstance(raw.get("aliases"), list) else []
        result.append({
            **dict(raw),
            "canonical_competition_id": canonical_id,
            "aliases": _unique([raw.get("canonical_name"), *aliases]),
            "free_tier": bool(raw.get("free_tier")),
        })
    return result


def load_coverage_manifest(path: str | Path = DEFAULT_COVERAGE_MANIFEST_PATH) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise FootballDataOrgError("COVERAGE_MANIFEST_UNAVAILABLE") from error
    if not isinstance(value, Mapping) or not _coverage_rows(value):
        raise FootballDataOrgError("COVERAGE_MANIFEST_INVALID")
    return dict(value)


def _target_value(target: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if target.get(key) not in (None, ""):
            return target[key]
    return None


def _target_projection(job: Mapping[str, Any], fixture: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "match_id": _target_value(fixture, "match_id", "matchId", "id") or _target_value(job, "match_id", "matchId", "id"),
        "competition_id": _target_value(fixture, "canonical_competition_id", "competition_id") or _target_value(job, "canonical_competition_id", "competition_id"),
        "competition": _target_value(fixture, "competition", "league") or _target_value(job, "competition", "league"),
        "home": _target_value(fixture, "home", "homeTeam") or _target_value(job, "home", "homeTeam"),
        "away": _target_value(fixture, "away", "awayTeam") or _target_value(job, "away", "awayTeam"),
        "kickoff": _target_value(fixture, "kickoff", "kickoff_at") or _target_value(job, "kickoff", "kickoff_at"),
        "provider_home_team_id": _target_value(fixture, "provider_home_team_id", "home_team_id") or _target_value(job, "provider_home_team_id", "home_team_id"),
        "provider_away_team_id": _target_value(fixture, "provider_away_team_id", "away_team_id") or _target_value(job, "provider_away_team_id", "away_team_id"),
    }


def resolve_provider_competition(
    target: Mapping[str, Any],
    manifest: Mapping[str, Any],
) -> dict[str, Any]:
    rows = _coverage_rows(manifest)
    requested_id = _text(_target_value(target, "canonical_competition_id", "competition_id"))
    requested_name = _normalise_alias(_target_value(target, "competition", "league"))
    row = next((item for item in rows if requested_id and item["canonical_competition_id"] == requested_id), None)
    if row is None and requested_name:
        row = next(
            (
                item
                for item in rows
                if any(_normalise_alias(alias) == requested_name for alias in item.get("aliases", []))
            ),
            None,
        )
    if row is None:
        return {
            "status": "BLOCKED",
            "reason_code": "COMPETITION_UNSUPPORTED",
            "canonical_competition_id": requested_id or None,
            "provider_competition_code": None,
        }
    if not row.get("free_tier") or not _text(row.get("provider_competition_code")):
        return {
            "status": "BLOCKED",
            "reason_code": "OUTSIDE_PROVIDER_FREE_COVERAGE",
            "canonical_competition_id": row["canonical_competition_id"],
            "provider_competition_code": None,
            "provider_competition_name": _text(row.get("provider_competition_name")) or None,
        }
    return {
        "status": "SUPPORTED",
        "reason_code": None,
        "canonical_competition_id": row["canonical_competition_id"],
        "provider_competition_code": _text(row["provider_competition_code"]),
        "provider_competition_name": _text(row.get("provider_competition_name")) or None,
        "coverage_source": row.get("coverage_source"),
    }


def _competition_matches_code(raw: Mapping[str, Any], code: str) -> bool:
    competition = raw.get("competition")
    if not isinstance(competition, Mapping):
        return False
    return _text(competition.get("code")) == code


def bridge_fixture(
    target: Mapping[str, Any],
    provider_matches: Iterable[Mapping[str, Any]],
    *,
    provider_competition_code: str,
    now: datetime | str,
    provider_competition_id: str | None = None,
) -> dict[str, Any]:
    """Bridge one fixture using exact competition, UTC kickoff and source state."""

    target_kickoff = _parse_timestamp(_target_value(target, "kickoff", "kickoff_at"))
    current = _parse_timestamp(now)
    if target_kickoff is None or current is None or target_kickoff <= current:
        return {
            "status": "BLOCKED",
            "reason_code": "FIXTURE_MAPPING_UNAVAILABLE",
            "provider_fixture_id": None,
            "candidate_provider_fixture_ids": [],
        }
    candidates: list[Mapping[str, Any]] = []
    for raw in provider_matches:
        if not isinstance(raw, Mapping) or not _competition_matches_code(raw, provider_competition_code):
            continue
        provider_kickoff = _parse_timestamp(raw.get("utcDate"))
        if provider_kickoff != target_kickoff:
            continue
        if _text(raw.get("status")) not in UPCOMING_STATUSES:
            continue
        last_updated = _parse_timestamp(raw.get("lastUpdated"))
        if last_updated is None or last_updated > current or last_updated >= target_kickoff:
            continue
        candidates.append(raw)
    candidate_ids = [_strict_provider_id(raw.get("id")) or _text(raw.get("id")) for raw in candidates]
    candidate_ids = [value for value in candidate_ids if value]
    if len(candidates) != 1:
        return {
            "status": "BLOCKED",
            "reason_code": "AMBIGUOUS_FIXTURE" if len(candidates) > 1 else "FIXTURE_MAPPING_UNAVAILABLE",
            "provider_fixture_id": None,
            "candidate_provider_fixture_ids": candidate_ids,
        }
    raw = candidates[0]
    provider_fixture_id = _strict_provider_id(raw.get("id"))
    competition = raw.get("competition") if isinstance(raw.get("competition"), Mapping) else {}
    home_team = raw.get("homeTeam") if isinstance(raw.get("homeTeam"), Mapping) else {}
    away_team = raw.get("awayTeam") if isinstance(raw.get("awayTeam"), Mapping) else {}
    home_id = _strict_provider_id(home_team.get("id"))
    away_id = _strict_provider_id(away_team.get("id"))
    expected_home = _strict_provider_id(_target_value(target, "provider_home_team_id", "home_team_id"))
    expected_away = _strict_provider_id(_target_value(target, "provider_away_team_id", "away_team_id"))
    if not provider_fixture_id or not home_id or not away_id or home_id == away_id:
        return {
            "status": "BLOCKED",
            "reason_code": "FIXTURE_MAPPING_UNAVAILABLE",
            "provider_fixture_id": None,
            "candidate_provider_fixture_ids": candidate_ids,
        }
    if (expected_home and expected_home != home_id) or (expected_away and expected_away != away_id):
        return {
            "status": "BLOCKED",
            "reason_code": "FIXTURE_ORIENTATION_MISMATCH",
            "provider_fixture_id": None,
            "candidate_provider_fixture_ids": candidate_ids,
        }
    source_url = f"{DEFAULT_API_BASE_URL}/matches/{provider_fixture_id}"
    return {
        "status": "BRIDGED",
        "reason_code": None,
        "provider_fixture_id": provider_fixture_id,
        "provider_home_team_id": home_id,
        "provider_away_team_id": away_id,
        "provider_home_team_name": _text(home_team.get("name")) or None,
        "provider_away_team_name": _text(away_team.get("name")) or None,
        "provider_competition_id": _strict_provider_id(competition.get("id")) or _text(competition.get("id")) or provider_competition_id,
        "provider_competition_code": provider_competition_code,
        "provider_competition_name": _text(competition.get("name")) or None,
        "provider_season_id": _strict_provider_id((raw.get("season") or {}).get("id")) if isinstance(raw.get("season"), Mapping) else None,
        "provider_kickoff_at": _iso(raw.get("utcDate")),
        "identity_scope": "provider_scoped",
        "canonical_home_team_id": None,
        "canonical_away_team_id": None,
        "orientation": "provider_home_away",
        "source_fixture_state": {
            "status": _text(raw.get("status")),
            "last_updated_at": _iso(raw.get("lastUpdated")),
        },
        "source_refs": [source_url],
    }


def _full_time_goals(raw: Mapping[str, Any]) -> tuple[int, int] | None:
    score = raw.get("score")
    full_time = score.get("fullTime") if isinstance(score, Mapping) else None
    if not isinstance(full_time, Mapping):
        return None
    values: list[int] = []
    for key in ("home", "away"):
        value = full_time.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            return None
        values.append(value)
    return values[0], values[1]


def normalize_team_matches(
    payload: Mapping[str, Any],
    *,
    provider_team_id: str,
    cutoff_at: str,
    fetched_at: str,
    provider_competition_code: str,
    source_url: str,
) -> list[dict[str, Any]]:
    """Normalize complete FINISHED observations for one provider team."""

    team_id = _strict_provider_id(provider_team_id)
    cutoff = _parse_timestamp(cutoff_at)
    fetched = _parse_timestamp(fetched_at)
    if not team_id or cutoff is None or fetched is None or fetched >= cutoff:
        return []
    rows = payload.get("matches") if isinstance(payload, Mapping) else None
    if not isinstance(rows, list):
        return []
    by_match: dict[str, dict[str, Any]] = {}
    for raw in rows:
        if not isinstance(raw, Mapping) or _text(raw.get("status")) != "FINISHED":
            continue
        kickoff = _parse_timestamp(raw.get("utcDate"))
        last_updated = _parse_timestamp(raw.get("lastUpdated"))
        if kickoff is None or last_updated is None or kickoff >= cutoff or last_updated > fetched:
            continue
        competition = raw.get("competition") if isinstance(raw.get("competition"), Mapping) else {}
        if _text(competition.get("code")) != provider_competition_code:
            continue
        home_team = raw.get("homeTeam") if isinstance(raw.get("homeTeam"), Mapping) else {}
        away_team = raw.get("awayTeam") if isinstance(raw.get("awayTeam"), Mapping) else {}
        home_id = _strict_provider_id(home_team.get("id"))
        away_id = _strict_provider_id(away_team.get("id"))
        match_id = _strict_provider_id(raw.get("id"))
        goals = _full_time_goals(raw)
        if not home_id or not away_id or not match_id or goals is None or team_id not in {home_id, away_id}:
            continue
        venue = "home" if home_id == team_id else "away"
        goals_for, goals_against = goals if venue == "home" else (goals[1], goals[0])
        source_record_ref = f"{source_url}#match:{match_id}"
        normalized = {
            "team_id": _provider_team_key(team_id),
            "provider_namespace": PROVIDER_NAME,
            "provider_team_id": team_id,
            "canonical_team_id": None,
            "provider_match_id": match_id,
            "kickoff_at": _iso(kickoff),
            "venue": venue,
            "goals_for": goals_for,
            "goals_against": goals_against,
            "opponent_provider_team_id": away_id if venue == "home" else home_id,
            "opponent_provider_team_name": _text(away_team.get("name")) if venue == "home" else _text(home_team.get("name")),
            "provider_competition_id": _strict_provider_id(competition.get("id")) or _text(competition.get("id")) or None,
            "provider_competition_code": provider_competition_code,
            "provider_competition_name": _text(competition.get("name")) or None,
            "source_fetched_at": _iso(fetched),
            "source_last_updated_at": _iso(last_updated),
            "source_url": source_url,
            "source_record_ref": source_record_ref,
            "synthetic": False,
        }
        previous = by_match.get(match_id)
        if previous is not None and previous != normalized:
            raise ProviderDataConflictError(f"conflicting provider match {match_id}")
        by_match[match_id] = normalized
    return sorted(by_match.values(), key=lambda row: (str(row.get("kickoff_at") or ""), str(row.get("provider_match_id") or "")))


def _fresh_enough(latest_by_team: Mapping[str, Any], cutoff: datetime, max_history_age_days: int) -> bool:
    if max_history_age_days < 0:
        return False
    for value in latest_by_team.values():
        latest = _parse_timestamp(value)
        if latest is None or latest >= cutoff or (cutoff - latest).total_seconds() > max_history_age_days * 86400:
            return False
    return True


def build_provider_recent_form(
    home_records: Iterable[Mapping[str, Any]],
    away_records: Iterable[Mapping[str, Any]],
    *,
    home_provider_team_id: str,
    away_provider_team_id: str,
    cutoff_at: str,
    captured_at: str,
    fixture_bridge: Mapping[str, Any],
    max_history_age_days: int = DEFAULT_MAX_HISTORY_AGE_DAYS,
    window_size: int = DEFAULT_FORM_WINDOW,
) -> dict[str, Any]:
    """Convert provider records to the existing Champion four-block form."""

    home_id = _strict_provider_id(home_provider_team_id)
    away_id = _strict_provider_id(away_provider_team_id)
    cutoff = _parse_timestamp(cutoff_at)
    captured = _parse_timestamp(captured_at)
    if not home_id or not away_id or home_id == away_id or cutoff is None or captured is None or captured >= cutoff:
        return {"status": "INSUFFICIENT_DATA", "reason_codes": ["HISTORY_INSUFFICIENT"], "final_prediction_eligible": False}
    records: list[dict[str, Any]] = []
    for expected_id, values in ((home_id, home_records), (away_id, away_records)):
        for raw in values:
            if not isinstance(raw, Mapping):
                continue
            row = dict(raw)
            kickoff = _parse_timestamp(row.get("kickoff_at"))
            if kickoff is None or kickoff >= cutoff:
                continue
            row.update({
                "team_id": _provider_team_key(expected_id),
                "provider_team_id": expected_id,
                "canonical_team_id": None,
                "provider_namespace": PROVIDER_NAME,
            })
            records.append(row)
    # Import lazily to keep the provider module independent from the cache
    # module during package import and to reuse the exact Champion contract.
    try:
        from recent_form_cache import build_recent_form
    except ModuleNotFoundError:
        from scripts.recent_form_cache import build_recent_form
    built = build_recent_form(
        records,
        home_team_id=_provider_team_key(home_id),
        away_team_id=_provider_team_key(away_id),
        cutoff_at=_iso(cutoff) or cutoff_at,
        window_size=window_size,
    )
    if not built or not _fresh_enough(built["latest_by_team"], cutoff, max_history_age_days):
        return {
            "status": "INSUFFICIENT_DATA",
            "reason_codes": ["HISTORY_INSUFFICIENT"],
            "final_prediction_eligible": False,
            "identity_scope": "provider_scoped",
        }
    bridge_refs = [str(value) for value in fixture_bridge.get("source_refs") or [] if _text(value)]
    record_refs = [str(row.get("source_record_ref")) for row in built["records"] if _text(row.get("source_record_ref"))]
    source_refs = _unique([*bridge_refs, *record_refs])
    references = [{"url": ref, "captured_at": _iso(captured)} for ref in source_refs]
    provenance = {
        "provider": PROVIDER_NAME,
        "provider_schema": PROVIDER_SCHEMA,
        "provider_namespace": PROVIDER_NAME,
        "identity_scope": "provider_scoped",
        "canonical_historical_identity": None,
        "provider_fixture_id": _text(fixture_bridge.get("provider_fixture_id")) or None,
        "provider_home_team_id": home_id,
        "provider_away_team_id": away_id,
        "provider_competition_id": _text(fixture_bridge.get("provider_competition_id")) or None,
        "provider_competition_code": _text(fixture_bridge.get("provider_competition_code")) or None,
        "fetched_at": _iso(captured),
        "cutoff_at": _iso(cutoff),
        "source_refs": source_refs,
        "synthetic": False,
        "no_future_leakage": all((_parse_timestamp(row.get("kickoff_at")) or cutoff) < cutoff for row in built["records"]),
    }
    return {
        "status": "FULL",
        "reason_codes": [],
        "final_prediction_eligible": True,
        "recent_form": built["recent_form"],
        "records": built["records"],
        "latest_by_team": built["latest_by_team"],
        "source": "football_data_org_recent_form",
        "captured_at": _iso(captured),
        "cutoff_at": _iso(cutoff),
        "references": references,
        "source_refs": source_refs,
        "provenance": provenance,
        "provider_fixture_id": _text(fixture_bridge.get("provider_fixture_id")) or None,
        "provider_home_team_id": home_id,
        "provider_away_team_id": away_id,
        "provider_identity": {
            "provider": PROVIDER_NAME,
            "provider_fixture_id": _text(fixture_bridge.get("provider_fixture_id")) or None,
            "home_team_id": home_id,
            "away_team_id": away_id,
            "canonical_home_team_id": None,
            "canonical_away_team_id": None,
        },
    }


class FootballDataOrgRecentFormRoute:
    """Demand-driven fixture bridge and recent-form route."""

    def __init__(
        self,
        *,
        coverage_manifest: Mapping[str, Any] | str | Path | None = None,
        token: str | None = None,
        transport: Callable[[str, Mapping[str, str]], Mapping[str, Any] | bytes] | None = None,
        cache: JsonResponseCache | None = None,
        cache_root: str | Path | None = DEFAULT_CACHE_ROOT,
        accounting: RequestAccounting | None = None,
        max_history_age_days: int = DEFAULT_MAX_HISTORY_AGE_DAYS,
    ) -> None:
        if coverage_manifest is None:
            manifest = load_coverage_manifest()
        elif isinstance(coverage_manifest, Mapping):
            manifest = dict(coverage_manifest)
        else:
            manifest = load_coverage_manifest(coverage_manifest)
        if not _coverage_rows(manifest):
            raise FootballDataOrgError("COVERAGE_MANIFEST_INVALID")
        self.coverage_manifest = manifest
        self.max_history_age_days = max_history_age_days
        self.accounting = accounting or RequestAccounting()
        self.client = FootballDataOrgClient(
            token=token,
            transport=transport,
            cache=cache,
            cache_root=cache_root,
            accounting=self.accounting,
        )

    def _blocked(
        self,
        *,
        status: str,
        reason_codes: Iterable[str],
        target: Mapping[str, Any],
        competition: Mapping[str, Any],
        bridge: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        result: dict[str, Any] = {
            "status": status,
            "reason_codes": _unique(reason_codes),
            "final_prediction_eligible": False,
            "fixture_id": _text(target.get("match_id")) or None,
            "canonical_competition_id": competition.get("canonical_competition_id"),
            "provider_competition_code": competition.get("provider_competition_code"),
            "identity_scope": "provider_scoped",
            "provider_fixture_id": None,
            "provider_home_team_id": None,
            "provider_away_team_id": None,
            "canonical_home_team_id": None,
            "canonical_away_team_id": None,
            "source_refs": [],
        }
        if bridge:
            result.update({
                "fixture_bridge": dict(bridge),
                "provider_fixture_id": bridge.get("provider_fixture_id"),
                "provider_home_team_id": bridge.get("provider_home_team_id"),
                "provider_away_team_id": bridge.get("provider_away_team_id"),
                "source_refs": list(bridge.get("source_refs") or []),
            })
        return result

    def get_recent_form(
        self,
        job: Mapping[str, Any],
        fixture: Mapping[str, Any],
        *,
        now: datetime | str,
    ) -> dict[str, Any]:
        target = _target_projection(job, fixture)
        current = _parse_timestamp(now)
        kickoff = _parse_timestamp(target.get("kickoff"))
        competition = resolve_provider_competition(target, self.coverage_manifest)
        if current is None or kickoff is None or kickoff <= current:
            return self._blocked(
                status="INSUFFICIENT_DATA",
                reason_codes=["FIXTURE_MAPPING_UNAVAILABLE"],
                target=target,
                competition=competition,
            )
        if competition.get("status") != "SUPPORTED":
            return self._blocked(
                status=str(competition.get("reason_code") or "OUTSIDE_PROVIDER_FREE_COVERAGE"),
                reason_codes=[str(competition.get("reason_code") or "COMPETITION_UNSUPPORTED")],
                target=target,
                competition=competition,
            )
        code = str(competition["provider_competition_code"])
        try:
            fixture_response = self.client.get_competition_matches(code, kickoff.date(), now=current)
        except CredentialMissingError:
            return self._blocked(
                status="SOURCE_UNAVAILABLE",
                reason_codes=["SOURCE_UNAVAILABLE", "LIVE_VALIDATION_BLOCKED_BY_CREDENTIAL"],
                target=target,
                competition=competition,
            )
        except FootballDataOrgError as error:
            return self._blocked(
                status="SOURCE_UNAVAILABLE",
                reason_codes=["SOURCE_UNAVAILABLE", str(error)],
                target=target,
                competition=competition,
            )
        bridge = bridge_fixture(
            target,
            fixture_response.payload.get("matches") or [],
            provider_competition_code=code,
            provider_competition_id=str(competition.get("provider_competition_id") or "") or None,
            now=current,
        )
        if bridge.get("status") != "BRIDGED":
            return self._blocked(
                status=str(bridge.get("reason_code") or "FIXTURE_MAPPING_UNAVAILABLE"),
                reason_codes=[str(bridge.get("reason_code") or "FIXTURE_MAPPING_UNAVAILABLE")],
                target=target,
                competition=competition,
                bridge=bridge,
            )
        try:
            home_response = self.client.get_team_matches(
                str(bridge["provider_home_team_id"]),
                code,
                _iso(kickoff) or "",
                max_history_age_days=self.max_history_age_days,
                now=current,
            )
            away_response = self.client.get_team_matches(
                str(bridge["provider_away_team_id"]),
                code,
                _iso(kickoff) or "",
                max_history_age_days=self.max_history_age_days,
                now=current,
            )
            fixture_ref = fixture_response.source_url.split("?", 1)[0]
            bridge = {**bridge, "source_refs": [fixture_ref]}
            home_records = normalize_team_matches(
                home_response.payload,
                provider_team_id=str(bridge["provider_home_team_id"]),
                cutoff_at=_iso(kickoff) or "",
                fetched_at=home_response.fetched_at,
                provider_competition_code=code,
                source_url=home_response.source_url.split("?", 1)[0],
            )
            away_records = normalize_team_matches(
                away_response.payload,
                provider_team_id=str(bridge["provider_away_team_id"]),
                cutoff_at=_iso(kickoff) or "",
                fetched_at=away_response.fetched_at,
                provider_competition_code=code,
                source_url=away_response.source_url.split("?", 1)[0],
            )
            form = build_provider_recent_form(
                home_records,
                away_records,
                home_provider_team_id=str(bridge["provider_home_team_id"]),
                away_provider_team_id=str(bridge["provider_away_team_id"]),
                cutoff_at=_iso(kickoff) or "",
                captured_at=max(home_response.fetched_at, away_response.fetched_at, fixture_response.fetched_at),
                fixture_bridge=bridge,
                max_history_age_days=self.max_history_age_days,
            )
        except CredentialMissingError:
            return self._blocked(
                status="SOURCE_UNAVAILABLE",
                reason_codes=["SOURCE_UNAVAILABLE", "LIVE_VALIDATION_BLOCKED_BY_CREDENTIAL"],
                target=target,
                competition=competition,
                bridge=bridge,
            )
        except ProviderDataConflictError:
            return self._blocked(
                status="INSUFFICIENT_DATA",
                reason_codes=["PROVIDER_MATCH_CONFLICT"],
                target=target,
                competition=competition,
                bridge=bridge,
            )
        except FootballDataOrgError as error:
            return self._blocked(
                status="SOURCE_UNAVAILABLE",
                reason_codes=["SOURCE_UNAVAILABLE", str(error)],
                target=target,
                competition=competition,
                bridge=bridge,
            )
        if form.get("status") != "FULL":
            return {
                **self._blocked(
                    status="INSUFFICIENT_DATA",
                    reason_codes=form.get("reason_codes") or ["HISTORY_INSUFFICIENT"],
                    target=target,
                    competition=competition,
                    bridge=bridge,
                ),
                "form": form,
            }
        return {
            **form,
            "fixture_id": _text(target.get("match_id")) or None,
            "canonical_competition_id": competition.get("canonical_competition_id"),
            "provider_competition_code": code,
            "fixture_bridge": bridge,
            "source_fetched_at": {
                "fixture": fixture_response.fetched_at,
                "home_team_matches": home_response.fetched_at,
                "away_team_matches": away_response.fetched_at,
            },
        }


__all__ = [
    "CredentialMissingError",
    "DEFAULT_API_BASE_URL",
    "DEFAULT_CACHE_ROOT",
    "FootballDataOrgClient",
    "FootballDataOrgError",
    "FootballDataOrgRecentFormRoute",
    "JsonResponseCache",
    "ProviderDataConflictError",
    "ProviderResponse",
    "ProviderResponseError",
    "RequestAccounting",
    "bridge_fixture",
    "build_provider_recent_form",
    "load_coverage_manifest",
    "normalize_team_matches",
    "resolve_provider_competition",
]
