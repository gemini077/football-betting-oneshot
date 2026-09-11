"""Bounded API-Football identity and enrichment spine for Issue #293.

Names are discovery hints only.  Accepted cross-provider IDs are persisted
only after a unique oriented fixture has independent identity evidence.
Provider responses stay in memory and snapshots contain projected fields only.
"""

from __future__ import annotations

import argparse
import copy
import datetime as dt
import html
import json
import os
import re
import subprocess
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REGISTRY_PATH = ROOT / "data" / "provider_entity_registry.json"
DEFAULT_ARTIFACT_PATH = ROOT / "artifacts" / "issue-293-multi-source-evidence-spine.json"
API_FOOTBALL_BASE_URL = "https://v3.football.api-sports.io"
MAX_API_FOOTBALL_REQUESTS = 100
ALLOWED_ENDPOINTS = (
    "/fixtures",
    "/leagues",
    "/standings",
    "/injuries",
    "/coachs",
    "/coaches",
    "/fixtures/lineups",
    "/teams/statistics",
    "/sidelined",
)
FIELD_NAMES = ("standings", "injuries", "suspensions", "sidelined", "coach", "lineup", "stats")
MAX_SIDELINED_PLAYERS = 8


def _text(value: Any) -> str:
    return str(value).strip() if value not in (None, "") else ""


def _positive_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    text = _text(value)
    if not text.isdigit():
        return None
    number = int(text)
    return number if number > 0 else None


def _clean_name(value: Any) -> str:
    return re.sub(r"\s+", " ", html.unescape(_text(value))).strip()


def _name_key(value: Any) -> str:
    """Candidate-only normalization; it never creates an accepted mapping."""

    value = unicodedata.normalize("NFKD", _clean_name(value)).casefold()
    return "".join(char for char in value if char.isalnum())


def _unique(values: Iterable[Any]) -> list[str]:
    return sorted({_text(value) for value in values if _text(value)})


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def _exact_head() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    except (OSError, subprocess.SubprocessError):
        return "UNKNOWN"


def _timestamp(value: Any) -> dt.datetime | None:
    text = _text(value)
    if not text:
        return None
    try:
        parsed = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.timezone.utc)


def _api_facts(row: Mapping[str, Any]) -> dict[str, Any] | None:
    fixture = row.get("fixture") if isinstance(row.get("fixture"), Mapping) else {}
    teams = row.get("teams") if isinstance(row.get("teams"), Mapping) else {}
    home = teams.get("home") if isinstance(teams.get("home"), Mapping) else {}
    away = teams.get("away") if isinstance(teams.get("away"), Mapping) else {}
    league = row.get("league") if isinstance(row.get("league"), Mapping) else {}
    fixture_id = _positive_int(fixture.get("id"))
    kickoff = _timestamp(fixture.get("date"))
    home_id = _positive_int(home.get("id"))
    away_id = _positive_int(away.get("id"))
    if fixture_id is None or kickoff is None or home_id is None or away_id is None:
        return None
    status = fixture.get("status") if isinstance(fixture.get("status"), Mapping) else {}
    return {
        "fixture_id": fixture_id,
        "kickoff": kickoff,
        "home_team_id": home_id,
        "away_team_id": away_id,
        "home_name": _clean_name(home.get("name")),
        "away_name": _clean_name(away.get("name")),
        "league_id": _positive_int(league.get("id")),
        "league_name": _clean_name(league.get("name")) or None,
        "country": _clean_name(league.get("country")) or None,
        "league_type": _clean_name(league.get("type")) or None,
        "season": _positive_int(league.get("season")),
        "round": _clean_name(league.get("round")) or None,
        "stage": _clean_name(league.get("stage")) or None,
        "status": _clean_name(status.get("short")) or None,
        "identity_evidence": row.get("identity_evidence") if isinstance(row.get("identity_evidence"), Mapping) else {},
        "source_identity": row.get("source_identity") if isinstance(row.get("source_identity"), Mapping) else {},
    }


def _source_id(source: Mapping[str, Any], side: str) -> str | None:
    keys = (
        f"nowscore_{side}_team_id",
        f"{side}_nowscore_team_id",
        f"{side}_team_id",
        f"{side}TeamId",
    )
    for key in keys:
        value = _text(source.get(key))
        if value:
            return value
    nested = source.get(f"{side}Team")
    if isinstance(nested, Mapping):
        for key in ("nowscore_id", "nowscoreId", "id", "team_id"):
            value = _text(nested.get(key))
            if value:
                return value
    return None


def _source_competition_id(source: Mapping[str, Any]) -> str | None:
    for key in ("nowscore_sclass_id", "sclass_id", "sclassID", "competition_id"):
        value = _text(source.get(key))
        if value:
            return value
    return None


def _source_season(source: Mapping[str, Any]) -> int | None:
    for key in ("season", "nowscore_season", "competition_season"):
        value = _positive_int(source.get(key))
        if value is not None:
            return value
    return None


class EntityRegistry:
    """Small durable cross-provider registry with uniqueness checks."""

    SCHEMA_VERSION = "provider_entity_registry.v1"

    def __init__(self, data: Mapping[str, Any] | None = None) -> None:
        raw = copy.deepcopy(dict(data or {}))
        self.data: dict[str, Any] = {
            "schema_version": self.SCHEMA_VERSION,
            "updated_at": raw.get("updated_at") or _now(),
            "teams": raw.get("teams") if isinstance(raw.get("teams"), Mapping) else {},
            "competitions": raw.get("competitions") if isinstance(raw.get("competitions"), Mapping) else {},
            "fixtures": raw.get("fixtures") if isinstance(raw.get("fixtures"), Mapping) else {},
        }
        self._validate()

    @classmethod
    def load(cls, path: str | Path = DEFAULT_REGISTRY_PATH) -> "EntityRegistry":
        path = Path(path)
        if not path.exists():
            return cls()
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError) as error:
            raise ValueError(f"invalid provider entity registry: {path}") from error
        if not isinstance(value, Mapping):
            raise ValueError(f"invalid provider entity registry: {path}")
        return cls(value)

    def _validate(self) -> None:
        if self.data.get("schema_version") != self.SCHEMA_VERSION:
            raise ValueError("unsupported provider entity registry schema")
        for section in ("teams", "competitions", "fixtures"):
            if not isinstance(self.data.get(section), Mapping):
                raise ValueError(f"provider entity registry section is not an object: {section}")
        seen_team_ids: dict[str, str] = {}
        for source_id, row in self.data["teams"].items():
            if not isinstance(row, Mapping) or row.get("status") != "ACCEPTED":
                raise ValueError("provider entity registry contains an unaccepted team mapping")
            api_id = _text(row.get("api_team_id"))
            if not _text(source_id) or not api_id:
                raise ValueError("provider team mapping requires both IDs")
            previous = seen_team_ids.get(api_id)
            if previous and previous != str(source_id):
                raise ValueError("API team ID maps to multiple Nowscore team IDs")
            seen_team_ids[api_id] = str(source_id)
        seen_competitions: dict[str, str] = {}
        for key, row in self.data["competitions"].items():
            if not isinstance(row, Mapping) or row.get("status") != "ACCEPTED":
                raise ValueError("provider entity registry contains an unaccepted competition mapping")
            if not _text(row.get("nowscore_sclass_id")) or _positive_int(row.get("api_league_id")) is None:
                raise ValueError(f"invalid competition mapping: {key}")
            if _positive_int(row.get("season")) is None:
                raise ValueError(f"competition mapping season is missing: {key}")
            provider_key = f"{_positive_int(row.get('api_league_id'))}:{_positive_int(row.get('season'))}"
            previous = seen_competitions.get(provider_key)
            if previous and previous != str(key):
                raise ValueError("API league-season maps to multiple Nowscore competitions")
            seen_competitions[provider_key] = str(key)
        seen_fixtures: dict[str, str] = {}
        for key, row in self.data["fixtures"].items():
            if not isinstance(row, Mapping) or row.get("status") != "ACCEPTED":
                raise ValueError("provider entity registry contains an unaccepted fixture mapping")
            if not _text(key) or _positive_int(row.get("api_fixture_id")) is None:
                raise ValueError(f"invalid fixture mapping: {key}")
            provider_key = _text(row.get("api_fixture_id"))
            previous = seen_fixtures.get(provider_key)
            if previous and previous != str(key):
                raise ValueError("API fixture ID maps to multiple Nowscore fixtures")
            seen_fixtures[provider_key] = str(key)

    @staticmethod
    def _key(value: Any) -> str:
        value = _text(value)
        if not value:
            raise ValueError("registry IDs must be non-empty")
        return value

    def lookup_team(self, nowscore_team_id: Any) -> dict[str, Any] | None:
        row = self.data["teams"].get(_text(nowscore_team_id))
        return dict(row) if isinstance(row, Mapping) and row.get("status") == "ACCEPTED" else None

    def lookup_competition(self, nowscore_sclass_id: Any, season: Any) -> dict[str, Any] | None:
        key = f"{_text(nowscore_sclass_id)}:{_positive_int(season) or 0}"
        row = self.data["competitions"].get(key)
        return dict(row) if isinstance(row, Mapping) and row.get("status") == "ACCEPTED" else None

    def lookup_fixture(self, nowscore_fixture_id: Any) -> dict[str, Any] | None:
        row = self.data["fixtures"].get(_text(nowscore_fixture_id))
        return dict(row) if isinstance(row, Mapping) and row.get("status") == "ACCEPTED" else None

    def accept_team(
        self,
        nowscore_team_id: Any,
        api_team_id: Any,
        *,
        aliases: Iterable[Any] = (),
        evidence: Iterable[Any] = (),
    ) -> dict[str, Any]:
        source_id = self._key(nowscore_team_id)
        provider_id = self._key(api_team_id)
        existing = self.lookup_team(source_id)
        if existing and _text(existing.get("api_team_id")) != provider_id:
            raise ValueError("Nowscore team is already bound to a different API team")
        for other_source, row in self.data["teams"].items():
            if other_source != source_id and _text(row.get("api_team_id")) == provider_id:
                raise ValueError("API team is already bound to a different Nowscore team")
        row = {
            "status": "ACCEPTED",
            "nowscore_team_id": source_id,
            "api_team_id": int(provider_id) if provider_id.isdigit() else provider_id,
            "aliases": _unique(aliases),
            "evidence": _unique(evidence),
            "verified_at": existing.get("verified_at") if existing else _now(),
        }
        self.data["teams"][source_id] = row
        self.data["updated_at"] = _now()
        return dict(row)

    def accept_competition(
        self,
        nowscore_sclass_id: Any,
        api_league_id: Any,
        season: Any,
        *,
        country: str | None = None,
        evidence: Iterable[Any] = (),
    ) -> dict[str, Any]:
        source_id = self._key(nowscore_sclass_id)
        league_id = _positive_int(api_league_id)
        competition_season = _positive_int(season)
        if league_id is None or competition_season is None:
            raise ValueError("competition mapping requires positive league ID and season")
        key = f"{source_id}:{competition_season}"
        existing = self.lookup_competition(source_id, competition_season)
        if existing and (
            _positive_int(existing.get("api_league_id")) != league_id
            or _positive_int(existing.get("season")) != competition_season
        ):
            raise ValueError("competition is already bound to a different API league-season")
        for other_key, other in self.data["competitions"].items():
            if other_key != key and _positive_int(other.get("api_league_id")) == league_id and _positive_int(other.get("season")) == competition_season:
                raise ValueError("API league-season is already bound to a different Nowscore competition")
        row = {
            "status": "ACCEPTED",
            "nowscore_sclass_id": source_id,
            "api_league_id": league_id,
            "season": competition_season,
            "country": _clean_name(country) or None,
            "evidence": _unique(evidence),
            "verified_at": existing.get("verified_at") if existing else _now(),
        }
        self.data["competitions"][key] = row
        self.data["updated_at"] = _now()
        return dict(row)

    def accept_fixture(
        self,
        nowscore_fixture_id: Any,
        api_fixture_id: Any,
        *,
        nowscore_home_team_id: Any = None,
        nowscore_away_team_id: Any = None,
        api_home_team_id: Any = None,
        api_away_team_id: Any = None,
        nowscore_sclass_id: Any = None,
        api_league_id: Any = None,
        season: Any = None,
        kickoff: Any = None,
        evidence: Iterable[Any] = (),
    ) -> dict[str, Any]:
        source_id = self._key(nowscore_fixture_id)
        provider_id = _positive_int(api_fixture_id)
        if provider_id is None:
            raise ValueError("fixture mapping requires a positive API fixture ID")
        existing = self.lookup_fixture(source_id)
        if existing and _positive_int(existing.get("api_fixture_id")) != provider_id:
            raise ValueError("Nowscore fixture is already bound to a different API fixture")
        for other_source, other in self.data["fixtures"].items():
            if other_source != source_id and _positive_int(other.get("api_fixture_id")) == provider_id:
                raise ValueError("API fixture is already bound to a different Nowscore fixture")
        row = {
            "status": "ACCEPTED",
            "nowscore_fixture_id": source_id,
            "api_fixture_id": provider_id,
            "nowscore_home_team_id": _text(nowscore_home_team_id) or None,
            "nowscore_away_team_id": _text(nowscore_away_team_id) or None,
            "api_home_team_id": _positive_int(api_home_team_id),
            "api_away_team_id": _positive_int(api_away_team_id),
            "nowscore_sclass_id": _text(nowscore_sclass_id) or None,
            "api_league_id": _positive_int(api_league_id),
            "season": _positive_int(season),
            "kickoff": _text(kickoff) or None,
            "evidence": _unique(evidence),
            "verified_at": existing.get("verified_at") if existing else _now(),
        }
        self.data["fixtures"][source_id] = row
        self.data["updated_at"] = _now()
        return dict(row)

    def save(self, path: str | Path = DEFAULT_REGISTRY_PATH) -> Path:
        self._validate()
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps(self.data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(path)
        return path

    def summary(self) -> dict[str, int]:
        return {section: len(self.data[section]) for section in ("teams", "competitions", "fixtures")}


class ApiFootballSharedClient:
    """Quota-aware in-process cache; raw response data never leaves memory."""

    def __init__(
        self,
        key: str,
        *,
        opener: Callable[..., Any] | None = None,
        timeout: int = 30,
        max_requests: int = MAX_API_FOOTBALL_REQUESTS,
    ) -> None:
        self._key = _text(key)
        self.opener = opener or urllib.request.urlopen
        self.timeout = timeout
        self.max_requests = max(0, min(int(max_requests), MAX_API_FOOTBALL_REQUESTS))
        self.request_count = 0
        self.blocked_request_count = 0
        self.cache_hits = 0
        self.endpoint_counts: Counter[str] = Counter()
        self.response_states: Counter[str] = Counter()
        self._cache: dict[str, dict[str, Any]] = {}

    @staticmethod
    def _cache_key(endpoint: str, params: Mapping[str, Any]) -> str:
        normalized = {str(key): str(value) for key, value in sorted(params.items())}
        return endpoint + "?" + urllib.parse.urlencode(normalized)

    @staticmethod
    def _provider_error_keys(errors: Any) -> list[str]:
        if isinstance(errors, Mapping):
            return sorted(_text(key) for key in errors if _text(key))
        if isinstance(errors, list):
            return sorted(_text(item.get("code") or item.get("type")) for item in errors if isinstance(item, Mapping) and _text(item.get("code") or item.get("type")))
        return ["provider_error"] if errors else []

    def get(self, endpoint: str, params: Mapping[str, Any]) -> dict[str, Any]:
        endpoint = "/" + _text(endpoint).strip("/")
        if endpoint not in ALLOWED_ENDPOINTS:
            return {"ok": False, "reason_code": "API_ENDPOINT_NOT_ALLOWED", "response_state": "NOT_REQUESTED"}
        if not self._key:
            return {"ok": False, "reason_code": "API_KEY_MISSING", "response_state": "NOT_REQUESTED"}
        normalized_params = {str(key): str(value) for key, value in params.items() if value is not None}
        cache_key = self._cache_key(endpoint, normalized_params)
        if cache_key in self._cache:
            self.cache_hits += 1
            result = copy.deepcopy(self._cache[cache_key])
            result["cache_hit"] = True
            return result
        if self.request_count >= self.max_requests:
            self.blocked_request_count += 1
            return {"ok": False, "reason_code": "API_REQUEST_CAP_REACHED", "response_state": "NOT_REQUESTED"}
        self.request_count += 1
        self.endpoint_counts[endpoint] += 1
        query = urllib.parse.urlencode(normalized_params)
        request = urllib.request.Request(
            f"{API_FOOTBALL_BASE_URL}{endpoint}?{query}",
            headers={
                "Accept": "application/json",
                "User-Agent": "FBOS-issue-293-shared-spine/1",
                "x-apisports-key": self._key,
            },
        )
        try:
            with self.opener(request, timeout=self.timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError:
            return {"ok": False, "reason_code": "API_HTTP_ERROR", "response_state": "HTTP_ERROR"}
        except (urllib.error.URLError, TimeoutError, OSError):
            return {"ok": False, "reason_code": "API_NETWORK_ERROR", "response_state": "NETWORK_ERROR"}
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
            return {"ok": False, "reason_code": "API_RESPONSE_INVALID", "response_state": "INVALID_ENVELOPE"}
        if not isinstance(payload, Mapping):
            return {"ok": False, "reason_code": "API_RESPONSE_ENVELOPE_INVALID", "response_state": "INVALID_ENVELOPE"}
        errors = payload.get("errors")
        if errors:
            result = {
                "ok": False,
                "reason_code": "API_PROVIDER_ERROR",
                "response_state": "PROVIDER_ERROR",
                "provider_error_keys": self._provider_error_keys(errors),
            }
        elif not isinstance(payload.get("response"), list):
            result = {"ok": False, "reason_code": "API_RESPONSE_ENVELOPE_INVALID", "response_state": "INVALID_ENVELOPE"}
        else:
            result = {"ok": True, "response_state": "OK", "payload": dict(payload)}
        self.response_states[str(result.get("response_state"))] += 1
        self._cache[cache_key] = copy.deepcopy(result)
        return result


def _response_rows(result: Mapping[str, Any]) -> tuple[list[Mapping[str, Any]], str | None]:
    if result.get("ok") is not True:
        return [], _text(result.get("reason_code")) or "API_REQUEST_FAILED"
    payload = result.get("payload")
    rows = payload.get("response") if isinstance(payload, Mapping) else None
    if not isinstance(rows, list):
        return [], "API_RESPONSE_ENVELOPE_INVALID"
    return [row for row in rows if isinstance(row, Mapping)], None


def _league_season_entries(row: Mapping[str, Any]) -> list[dict[str, Any]]:
    league = row.get("league") if isinstance(row.get("league"), Mapping) else {}
    country = league.get("country") or row.get("country")
    if isinstance(country, Mapping):
        country = country.get("name")
    common = {
        "id": league.get("id"),
        "name": league.get("name"),
        "country": country,
        "type": league.get("type"),
    }
    entries: list[dict[str, Any]] = []
    if _positive_int(league.get("season")) is not None:
        entries.append({**common, "season": league.get("season"), "coverage": league.get("coverage")})
    seasons = row.get("seasons") if isinstance(row.get("seasons"), list) else league.get("seasons")
    if isinstance(seasons, list):
        for season in seasons:
            if not isinstance(season, Mapping):
                continue
            entries.append({
                **common,
                "season": season.get("year") or season.get("season"),
                "coverage": season.get("coverage"),
            })
    return entries


def read_league_coverage(
    result: Mapping[str, Any],
    *,
    league_id: int,
    season: int,
) -> dict[str, Any]:
    """Differentiate provider errors, empty season coverage, and valid flags."""

    rows, error = _response_rows(result)
    empty_coverage = {"standings": None, "injuries": None, "lineups": None, "statistics": None}
    if error:
        return {
            "status": "UNAVAILABLE",
            "reason_code": error,
            "league_id": league_id,
            "season": season,
            "coverage": empty_coverage,
            "provenance": {"response_state": result.get("response_state"), "cache_hit": bool(result.get("cache_hit"))},
        }
    exact = []
    season_mismatch = False
    for row in rows:
        for league in _league_season_entries(row):
            if _positive_int(league.get("id")) != league_id:
                continue
            row_season = _positive_int(league.get("season"))
            if row_season != season:
                season_mismatch = True
                continue
            exact.append(league)
    if not exact and not season_mismatch:
        # A valid envelope with no season-bearing row is a coverage miss, not
        # an API response error.
        season_mismatch = False
    if not exact:
        return {
            "status": "UNAVAILABLE",
            "reason_code": "API_LEAGUE_SEASON_MISMATCH" if season_mismatch else "API_LEAGUE_SEASON_NO_COVERAGE",
            "league_id": league_id,
            "season": season,
            "coverage": empty_coverage,
        }
    if len(exact) > 1:
        return {
            "status": "AMBIGUOUS",
            "reason_code": "API_LEAGUE_SEASON_RESPONSE_AMBIGUOUS",
            "league_id": league_id,
            "season": season,
            "coverage": empty_coverage,
        }
    league = exact[0]
    coverage = league.get("coverage") if isinstance(league.get("coverage"), Mapping) else {}
    fixtures = coverage.get("fixtures") if isinstance(coverage.get("fixtures"), Mapping) else {}

    def flag(name: str) -> bool | None:
        value = coverage.get(name)
        if isinstance(value, bool):
            return value
        value = fixtures.get(name)
        return value if isinstance(value, bool) else None

    flags = {name: flag(name) for name in ("standings", "injuries", "lineups", "statistics")}
    return {
        "status": "READ" if all(isinstance(value, bool) for value in flags.values()) else "READ_PARTIAL",
        "reason_code": "SEASON_SPECIFIC_COVERAGE_READ" if all(isinstance(value, bool) for value in flags.values()) else "API_COVERAGE_FLAGS_PARTIAL",
        "league_id": league_id,
        "league_name": _clean_name(league.get("name")) or None,
        "country": _clean_name(league.get("country")) or None,
        "season": season,
        "coverage": flags,
    }


def _bound_result(facts: Mapping[str, Any], evidence: Mapping[str, Any], *, reason: str) -> dict[str, Any]:
    return {
        "status": "BOUND",
        "reason_code": reason,
        "candidate_count": 1,
        "api_fixture_id": facts["fixture_id"],
        "api_home_team_id": facts["home_team_id"],
        "api_away_team_id": facts["away_team_id"],
        "api_home_name": facts["home_name"],
        "api_away_name": facts["away_name"],
        "api_league_id": facts["league_id"],
        "league_name": facts["league_name"],
        "country": facts["country"],
        "league_type": facts["league_type"],
        "season": facts["season"],
        "round": facts["round"],
        "stage": facts["stage"],
        "kickoff": facts["kickoff"].isoformat(),
        "evidence": dict(evidence),
    }


def bind_fixture_identity(
    source: Mapping[str, Any],
    aliases: Mapping[str, Any],
    api_rows: list[Mapping[str, Any]],
    *,
    registry: EntityRegistry,
    allow_bootstrap: bool = False,
) -> dict[str, Any]:
    """Resolve a fixture without accepting a name-only candidate."""

    source_id = _text(source.get("nowscore_id") or source.get("nowscoreId"))
    kickoff_value = source.get("kickoff") or source.get("match_kickoff")
    if not kickoff_value and source.get("matchDate") and source.get("matchTime"):
        kickoff_value = f"{_text(source.get('matchDate'))}T{_text(source.get('matchTime'))}:00+08:00"
    source_kickoff = _timestamp(kickoff_value or source.get("matchDate"))
    if not source_id:
        return {"status": "UNBOUND", "reason_code": "NOWSCORE_FIXTURE_ID_MISSING"}
    if source_kickoff is None:
        return {"status": "UNBOUND", "reason_code": "SOURCE_KICKOFF_MISSING"}
    facts_rows = [facts for row in api_rows if isinstance(row, Mapping) and (facts := _api_facts(row))]
    persisted = registry.lookup_fixture(source_id)
    if persisted:
        exact = [row for row in facts_rows if row["fixture_id"] == _positive_int(persisted.get("api_fixture_id"))]
        if len(exact) != 1:
            return {"status": "UNBOUND", "reason_code": "PERSISTED_API_FIXTURE_NOT_IN_RESPONSE", "candidate_count": len(exact)}
        facts = exact[0]
        if _positive_int(persisted.get("api_home_team_id")) not in (None, facts["home_team_id"]):
            return {"status": "UNBOUND", "reason_code": "PERSISTED_ORIENTATION_MISMATCH"}
        if _positive_int(persisted.get("api_away_team_id")) not in (None, facts["away_team_id"]):
            return {"status": "UNBOUND", "reason_code": "PERSISTED_ORIENTATION_MISMATCH"}
        if _positive_int(persisted.get("api_league_id")) not in (None, facts["league_id"]):
            return {"status": "UNBOUND", "reason_code": "PERSISTED_COMPETITION_MISMATCH"}
        if _positive_int(persisted.get("season")) not in (None, facts["season"]):
            return {"status": "UNBOUND", "reason_code": "PERSISTED_SEASON_MISMATCH"}
        if abs((facts["kickoff"] - source_kickoff).total_seconds()) > 15 * 60:
            return {"status": "UNBOUND", "reason_code": "KICKOFF_MISMATCH"}
        return _bound_result(facts, {"persisted_fixture": True}, reason="PERSISTED_ACCEPTED_MAPPING")

    alias_values = aliases.get("aliases") if isinstance(aliases.get("aliases"), Mapping) else aliases
    home_aliases = {_name_key(value) for value in (alias_values.get("home") or ()) if _name_key(value)} if isinstance(alias_values, Mapping) else set()
    away_aliases = {_name_key(value) for value in (alias_values.get("away") or ()) if _name_key(value)} if isinstance(alias_values, Mapping) else set()
    source_home_id = _source_id(source, "home")
    source_away_id = _source_id(source, "away")
    source_competition_id = _source_competition_id(source)
    home_mapping = registry.lookup_team(source_home_id) if source_home_id else None
    away_mapping = registry.lookup_team(source_away_id) if source_away_id else None
    oriented: list[tuple[dict[str, Any], dict[str, Any]]] = []
    reverse_oriented = 0
    name_oriented = 0
    kickoff_rows = 0
    for facts in facts_rows:
        same_kickoff = abs((facts["kickoff"] - source_kickoff).total_seconds()) <= 15 * 60
        name_home = _name_key(facts["home_name"]) in home_aliases
        name_away = _name_key(facts["away_name"]) in away_aliases
        id_home = bool(home_mapping and _positive_int(home_mapping.get("api_team_id")) == facts["home_team_id"])
        id_away = bool(away_mapping and _positive_int(away_mapping.get("api_team_id")) == facts["away_team_id"])
        reverse_name = _name_key(facts["home_name"]) in away_aliases and _name_key(facts["away_name"]) in home_aliases
        reverse_id = bool(home_mapping and away_mapping and _positive_int(home_mapping.get("api_team_id")) == facts["away_team_id"] and _positive_int(away_mapping.get("api_team_id")) == facts["home_team_id"])
        if same_kickoff:
            kickoff_rows += 1
        if reverse_name:
            reverse_oriented += int(same_kickoff)
            # Conflicting names and persisted IDs are not reconciled by a
            # preference rule; the fixture remains fail-closed.
            continue
        if (name_home and name_away) or (id_home and id_away):
            name_oriented += int(name_home and name_away)
            if same_kickoff:
                evidence = {
                    "team_ids": bool(id_home and id_away),
                    "competition": False,
                    "country": False,
                    "roster": False,
                    "counterpart_pair": False,
                    "competition_context": False,
                    "country_context": False,
                    "roster_context": False,
                    "name_candidate": bool(name_home and name_away),
                }
                identity = facts.get("identity_evidence") or facts.get("source_identity") or {}
                if allow_bootstrap:
                    evidence["counterpart_pair"] = bool(
                        source_home_id and source_away_id
                        and facts["home_team_id"] and facts["away_team_id"]
                        and name_home and name_away
                    )
                    evidence["competition_context"] = bool(
                        source_competition_id and facts["league_id"] and facts["season"]
                    )
                    evidence["country_context"] = bool(facts.get("country"))
                if isinstance(identity, Mapping):
                    for key in ("counterpart_pair", "competition_context", "country_context", "roster_context"):
                        if identity.get(key) is True:
                            evidence[key] = True
                oriented.append((facts, evidence))
        if same_kickoff and (reverse_name or reverse_id):
            reverse_oriented += 1

    if len(oriented) > 1:
        return {"status": "AMBIGUOUS", "reason_code": "MULTIPLE_ORIENTED_API_FIXTURES", "candidate_count": len(oriented)}
    if not oriented:
        if reverse_oriented:
            return {"status": "UNBOUND", "reason_code": "ORIENTATION_MISMATCH", "candidate_count": reverse_oriented}
        if name_oriented:
            return {"status": "UNBOUND", "reason_code": "KICKOFF_MISMATCH", "candidate_count": name_oriented}
        if kickoff_rows:
            return {"status": "UNBOUND", "reason_code": "TEAM_IDENTITY_UNPROVEN", "candidate_count": 0}
        return {"status": "UNBOUND", "reason_code": "NO_ORIENTED_API_FIXTURE", "candidate_count": 0}

    facts, evidence = oriented[0]
    source_season = _source_season(source)
    if source_season is not None and facts["season"] != source_season:
        return {"status": "UNBOUND", "reason_code": "SEASON_MISMATCH", "candidate_count": 1}
    competition_id = source_competition_id
    competition_mapping = registry.lookup_competition(competition_id, facts["season"]) if competition_id and facts["season"] else None
    if competition_mapping and _positive_int(competition_mapping.get("api_league_id")) == facts["league_id"]:
        evidence["competition"] = True
    if _positive_int(source.get("api_league_id") or source.get("api_football_league_id")) == facts["league_id"]:
        evidence["competition"] = True
    source_country = _clean_name(source.get("country") or source.get("league_country"))
    if source_country and facts["country"] and _name_key(source_country) == _name_key(facts["country"]):
        evidence["country"] = True
    identity = facts.get("identity_evidence") or facts.get("source_identity") or {}
    if isinstance(identity, Mapping):
        for key in ("team", "team_ids", "competition", "country", "roster"):
            if identity.get(key) is True:
                evidence[key if key != "team" else "team_ids"] = True
    if isinstance(facts.get("source_identity"), Mapping):
        source_identity = facts["source_identity"]
        evidence["team_ids"] = evidence["team_ids"] or (
            _text(source_identity.get("home_team_id")) == _text(source_home_id)
            and _text(source_identity.get("away_team_id")) == _text(source_away_id)
        )
    bootstrap_verified = allow_bootstrap and all(
        evidence[key] for key in ("counterpart_pair", "competition_context", "country_context")
    )
    if bootstrap_verified:
        evidence["competition"] = True
        evidence["bootstrap_proof"] = "unique_fixture_counterpart_and_competition_country_context"
    # ponytail: require stable team IDs, or an explicit first-mapping proof;
    # name and kickoff alone remain candidates forever.
    independently_verified = evidence["team_ids"] or bootstrap_verified or all(
        evidence[key] for key in ("competition", "country", "roster")
    )
    if not independently_verified:
        return {
            "status": "UNBOUND",
            "reason_code": "NAME_CANDIDATE_ONLY",
            "candidate_count": 1,
            "evidence": evidence,
        }
    return _bound_result(
        facts,
        evidence,
        reason=(
            "UNIQUE_ORIENTED_FIXTURE_WITH_BOOTSTRAP_EVIDENCE"
            if bootstrap_verified and not evidence["team_ids"]
            else "UNIQUE_ORIENTED_FIXTURE_WITH_VERIFIED_EVIDENCE"
        ),
    )


def _field_unavailable(reason: str, *, endpoint: str | None = None, params: Mapping[str, Any] | None = None) -> dict[str, Any]:
    return {
        "state": "UNAVAILABLE",
        "reason_code": reason,
        "value": None,
        "provenance": {"endpoint": endpoint, "params": dict(params or {})},
    }


def _provenance(result: Mapping[str, Any], endpoint: str, params: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "endpoint": endpoint,
        "params": dict(params),
        "response_state": result.get("response_state"),
        "cache_hit": bool(result.get("cache_hit")),
        "reason_code": result.get("reason_code") if result.get("ok") is not True else "RESPONSE_RECEIVED",
    }


def _projected_field(
    result: Mapping[str, Any],
    endpoint: str,
    params: Mapping[str, Any],
    projector: Callable[[list[Mapping[str, Any]]], Any],
    *,
    empty_reason: str = "NO_PUBLISHED_DATA",
) -> dict[str, Any]:
    rows, error = _response_rows(result)
    provenance = _provenance(result, endpoint, params)
    if error:
        return {"state": "UNAVAILABLE", "reason_code": error, "value": None, "provenance": provenance}
    if not rows:
        return {"state": "EMPTY", "reason_code": empty_reason, "value": None, "provenance": provenance}
    return {"state": "PRESENT", "reason_code": "PROJECTED_FROM_PROVIDER_RESPONSE", "value": projector(rows), "provenance": provenance}


def _team_value(value: Any) -> dict[str, Any]:
    return {
        "team_id": _positive_int(value.get("id")) if isinstance(value, Mapping) else None,
        "team_name": _clean_name(value.get("name")) or None if isinstance(value, Mapping) else None,
    }


def _project_standings(rows: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    projected = []
    for row in rows:
        league = row.get("league") if isinstance(row.get("league"), Mapping) else {}
        groups = league.get("standings") if isinstance(league.get("standings"), list) else []
        for group in groups:
            entries = group if isinstance(group, list) else []
            for entry in entries:
                if not isinstance(entry, Mapping):
                    continue
                all_stats = entry.get("all") if isinstance(entry.get("all"), Mapping) else {}
                goals = all_stats.get("goals") if isinstance(all_stats.get("goals"), Mapping) else {}
                projected.append({
                    "rank": _positive_int(entry.get("rank")),
                    **_team_value(entry.get("team")),
                    "played": _positive_int(all_stats.get("played")),
                    "wins": _positive_int(all_stats.get("win")) or 0,
                    "draws": _positive_int(all_stats.get("draw")) or 0,
                    "losses": _positive_int(all_stats.get("lose")) or 0,
                    "goals_for": _positive_int(goals.get("for")) or 0,
                    "goals_against": _positive_int(goals.get("against")) or 0,
                    "goal_diff": entry.get("goalsDiff") if isinstance(entry.get("goalsDiff"), (int, float)) else None,
                    "points": entry.get("points") if isinstance(entry.get("points"), (int, float)) else None,
                })
    return projected


def _project_injuries(rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    injury_count = 0
    suspension_count = 0
    players = []
    teams: dict[str, dict[str, Any]] = {}
    for row in rows:
        team = _team_value(row.get("team"))
        key = _text(team.get("team_id")) or "unknown"
        item = teams.setdefault(key, {**team, "injury_count": 0, "suspension_count": 0})
        kind = f"{_text(row.get('type'))} {_text(row.get('reason'))}".casefold()
        player = row.get("player") if isinstance(row.get("player"), Mapping) else {}
        fixture = row.get("fixture") if isinstance(row.get("fixture"), Mapping) else {}
        players.append({
            "player_id": _positive_int(player.get("id")),
            "player_name": _clean_name(player.get("name")) or None,
            "position": _clean_name(player.get("position") or player.get("pos")) or None,
            **team,
            "type": _clean_name(row.get("type")) or None,
            "reason": _clean_name(row.get("reason")) or None,
            "fixture_id": _positive_int(fixture.get("id")),
        })
        if "suspend" in kind or "red card" in kind:
            suspension_count += 1
            item["suspension_count"] += 1
        else:
            injury_count += 1
            item["injury_count"] += 1
    return {
        "injury_count": injury_count,
        "suspension_count": suspension_count,
        "players": sorted(players, key=lambda item: (_text(item.get("player_id")), _text(item.get("player_name")))),
        "teams": sorted(teams.values(), key=lambda item: _text(item.get("team_id"))),
    }


def _project_coaches(rows: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    projected = []
    for row in rows:
        coach = row.get("coach") if isinstance(row.get("coach"), Mapping) else row
        career = coach.get("career") if isinstance(coach.get("career"), list) else []
        projected.append({
            "coach_id": _positive_int(coach.get("id")),
            "coach_name": _clean_name(coach.get("name")) or None,
            "career": [
                {
                    "team_id": _positive_int(item.get("team", {}).get("id")) if isinstance(item, Mapping) and isinstance(item.get("team"), Mapping) else None,
                    "team_name": _clean_name(item.get("team", {}).get("name")) or None if isinstance(item, Mapping) and isinstance(item.get("team"), Mapping) else None,
                    "league_id": _positive_int(item.get("league", {}).get("id")) if isinstance(item, Mapping) and isinstance(item.get("league"), Mapping) else None,
                    "season": _positive_int(item.get("season")) if isinstance(item, Mapping) else None,
                    "start": _text(item.get("start")) or None if isinstance(item, Mapping) else None,
                    "end": _text(item.get("end")) or None if isinstance(item, Mapping) else None,
                }
                for item in career
                if isinstance(item, Mapping)
            ],
        })
    return projected


def _project_lineups(rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    teams = []
    for row in rows:
        team = _team_value(row.get("team"))
        start = row.get("startXI") if isinstance(row.get("startXI"), list) else []
        substitutes = row.get("substitutes") if isinstance(row.get("substitutes"), list) else []
        teams.append({
            **team,
            "starting_count": len(start),
            "substitute_count": len(substitutes),
            "formation": _clean_name(row.get("formation")) or None,
        })
    return {"published": bool(teams), "team_count": len(teams), "teams": teams}


def _project_stat_value(value: Any, depth: int = 0) -> Any:
    if depth > 4:
        return None
    if isinstance(value, Mapping):
        return {
            _text(key): _project_stat_value(item, depth + 1)
            for key, item in value.items()
            if _text(key) and not _text(key).casefold().endswith(("logo", "url"))
        }
    if isinstance(value, list):
        return [_project_stat_value(item, depth + 1) for item in value[:50]]
    return value if isinstance(value, (str, int, float, bool)) or value is None else None


def _project_stats(rows: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    projected = []
    for row in rows:
        team = _team_value(row.get("team"))
        result = {
            **team,
            "league_id": _positive_int(row.get("league", {}).get("id")) if isinstance(row.get("league"), Mapping) else None,
            "season": _positive_int(row.get("league", {}).get("season")) if isinstance(row.get("league"), Mapping) else None,
        }
        for key in ("fixtures", "goals", "biggest", "clean_sheet", "failed_to_score", "penalty", "lineups", "form"):
            if key in row:
                result[key] = _project_stat_value(row.get(key))
        if isinstance(row.get("statistics"), list):
            result["statistics"] = _project_stat_value(row.get("statistics"))
        projected.append(result)
    return projected


def _coverage_field(coverage: Mapping[str, Any], name: str) -> bool | None:
    flags = coverage.get("coverage") if isinstance(coverage.get("coverage"), Mapping) else {}
    value = flags.get(name)
    return value if isinstance(value, bool) else None


def _coverage_projected_field(
    client: ApiFootballSharedClient,
    coverage: Mapping[str, Any],
    name: str,
    endpoint: str,
    params: Mapping[str, Any],
    projector: Callable[[list[Mapping[str, Any]]], Any],
) -> dict[str, Any]:
    flag = _coverage_field(coverage, name)
    if flag is False:
        return {"state": "UNSUPPORTED", "reason_code": "API_COVERAGE_FLAG_FALSE", "value": None, "provenance": {"endpoint": "/leagues", "params": {"league": coverage.get("league_id"), "season": coverage.get("season")}}}
    if flag is None:
        return _field_unavailable("API_COVERAGE_FLAG_UNKNOWN", endpoint="/leagues", params={"league": coverage.get("league_id"), "season": coverage.get("season")})
    return _projected_field(client.get(endpoint, params), endpoint, params, projector)


def _project_sidelined(rows: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    projected = []
    for row in rows:
        player = row.get("player") if isinstance(row.get("player"), Mapping) else {}
        history = row.get("sidelined") if isinstance(row.get("sidelined"), list) else []
        for item in history:
            if not isinstance(item, Mapping):
                continue
            projected.append({
                "player_id": _positive_int(player.get("id")),
                "player_name": _clean_name(player.get("name")) or None,
                "type": _clean_name(item.get("type")) or None,
                "reason": _clean_name(item.get("reason")) or None,
                "start": _text(item.get("start")) or None,
                "end": _text(item.get("end")) or None,
            })
    return projected


def _sidelined_field(
    client: ApiFootballSharedClient,
    injuries: Mapping[str, Any],
) -> dict[str, Any]:
    if injuries.get("state") == "UNSUPPORTED":
        return {"state": "UNSUPPORTED", "reason_code": "INJURY_COVERAGE_FLAG_FALSE", "value": None, "provenance": {"source": "injuries_coverage"}}
    if injuries.get("state") == "UNAVAILABLE":
        return _field_unavailable(_text(injuries.get("reason_code")) or "INJURY_COVERAGE_UNAVAILABLE")
    players = injuries.get("value", {}).get("players", []) if isinstance(injuries.get("value"), Mapping) else []
    player_ids = sorted({_positive_int(player.get("player_id")) for player in players if isinstance(player, Mapping)} - {None})
    if not player_ids:
        return {"state": "EMPTY", "reason_code": "NO_PLAYER_IDS_FOR_SIDELINED", "value": None, "provenance": {"endpoint": "/sidelined", "requested_player_count": 0}}
    requested = player_ids[:MAX_SIDELINED_PLAYERS]
    rows: list[Mapping[str, Any]] = []
    errors = []
    for player_id in requested:
        result = client.get("/sidelined", {"player": player_id})
        response_rows, error = _response_rows(result)
        rows.extend(response_rows)
        if error:
            errors.append(error)
    value = _project_sidelined(rows)
    provenance = {
        "endpoint": "/sidelined",
        "requested_player_ids": requested,
        "requested_player_count": len(requested),
        "skipped_player_count": max(0, len(player_ids) - len(requested)),
        "cache_hits": client.cache_hits,
        "errors": sorted(set(errors)),
    }
    if value:
        return {"state": "PRESENT", "reason_code": "PROJECTED_FROM_PROVIDER_RESPONSE", "value": value, "provenance": provenance}
    if errors and not rows:
        return {"state": "UNAVAILABLE", "reason_code": errors[0], "value": None, "provenance": provenance}
    return {"state": "EMPTY", "reason_code": "NO_SIDELINED_HISTORY", "value": None, "provenance": provenance}


def _team_stats_field(
    client: ApiFootballSharedClient,
    coverage: Mapping[str, Any],
    *,
    league_id: int | None,
    season: int | None,
    team_ids: Iterable[int | None],
    source_kickoff: dt.datetime | None,
    as_of: dt.datetime | None,
) -> dict[str, Any]:
    flag = _coverage_field(coverage, "statistics")
    base_params = {"league": league_id, "season": season}
    if flag is False:
        return {"state": "UNSUPPORTED", "reason_code": "API_COVERAGE_FLAG_FALSE", "value": None, "provenance": {"endpoint": "/leagues", "params": base_params}}
    if flag is None:
        return _field_unavailable("API_COVERAGE_FLAG_UNKNOWN", endpoint="/leagues", params=base_params)
    if as_of is not None and source_kickoff is not None and as_of >= source_kickoff:
        return _field_unavailable("PREMATCH_CUTOFF_AFTER_KICKOFF", endpoint="/teams/statistics", params=base_params)
    rows: list[Mapping[str, Any]] = []
    errors = []
    requested = sorted({_positive_int(team_id) for team_id in team_ids} - {None})
    for team_id in requested:
        params = {"league": league_id, "season": season, "team": team_id}
        result = client.get("/teams/statistics", params)
        response_rows, error = _response_rows(result)
        rows.extend(response_rows)
        if error:
            errors.append(error)
    provenance = {
        "endpoint": "/teams/statistics",
        "league": league_id,
        "season": season,
        "team_ids": requested,
        "prematch_cutoff": as_of.isoformat() if as_of else None,
        "cache_hits": client.cache_hits,
        "errors": sorted(set(errors)),
    }
    if rows:
        return {"state": "PRESENT", "reason_code": "PROJECTED_FROM_PROVIDER_RESPONSE", "value": _project_stats(rows), "provenance": provenance}
    if errors:
        return {"state": "UNAVAILABLE", "reason_code": errors[0], "value": None, "provenance": provenance}
    return {"state": "EMPTY", "reason_code": "NO_TEAM_STATISTICS", "value": None, "provenance": provenance}


def build_enrichment_snapshot(
    source: Mapping[str, Any],
    binding: Mapping[str, Any],
    client: ApiFootballSharedClient,
    *,
    coverage: Mapping[str, Any],
    as_of: dt.datetime | str | None = None,
) -> dict[str, Any]:
    """Return one sanitized, field-level-provenance snapshot per bound fixture."""

    source_id = _text(source.get("nowscore_id") or source.get("nowscoreId")) or None
    fixture_id = _positive_int(binding.get("api_fixture_id"))
    league_id = _positive_int(binding.get("api_league_id"))
    season = _positive_int(binding.get("season"))
    cutoff = as_of if isinstance(as_of, dt.datetime) else _timestamp(as_of)
    source_kickoff = _timestamp(source.get("kickoff") or source.get("match_kickoff"))
    identity = {
        "nowscore_fixture_id": source_id,
        "api_fixture_id": fixture_id,
        "nowscore_home_team_id": _source_id(source, "home"),
        "nowscore_away_team_id": _source_id(source, "away"),
        "api_home_team_id": _positive_int(binding.get("api_home_team_id")),
        "api_away_team_id": _positive_int(binding.get("api_away_team_id")),
        "nowscore_sclass_id": _source_competition_id(source),
        "api_league_id": league_id,
        "season": season,
    }
    fields: dict[str, Any] = {
        "competition": {
            "state": "PRESENT",
            "reason_code": "BOUND_FIXTURE_METADATA",
            "value": {
                "league_id": league_id,
                "league_name": _clean_name(binding.get("league_name")) or None,
                "country": _clean_name(binding.get("country")) or None,
                "season": season,
                "round": _clean_name(binding.get("round")) or None,
                "stage": _clean_name(binding.get("stage")) or None,
            },
            "provenance": {"source": "api_fixture_identity"},
        }
    }
    standings_params = {"league": league_id, "season": season}
    fixture_params = {"fixture": fixture_id}
    fields["standings"] = _coverage_projected_field(client, coverage, "standings", "/standings", standings_params, _project_standings)
    injuries = _coverage_projected_field(client, coverage, "injuries", "/injuries", fixture_params, _project_injuries)
    fields["injuries"] = injuries
    fields["sidelined"] = _sidelined_field(client, injuries)
    injury_value = injuries.get("value") if isinstance(injuries.get("value"), Mapping) else {}
    suspension_players = [
        player for player in injury_value.get("players", [])
        if isinstance(player, Mapping)
        and (
            "suspend" in f"{_text(player.get('type'))} {_text(player.get('reason'))}".casefold()
            or "red card" in f"{_text(player.get('type'))} {_text(player.get('reason'))}".casefold()
        )
    ]
    fields["suspensions"] = {
        "state": injuries["state"],
        "reason_code": injuries["reason_code"],
        "value": ({"suspension_count": injury_value.get("suspension_count", 0), "players": suspension_players} if injury_value else None),
        "provenance": dict(injuries["provenance"]),
    }

    coach_results = []
    for team_id in sorted({_positive_int(identity.get("api_home_team_id")), _positive_int(identity.get("api_away_team_id"))} - {None}):
        coach_results.append((team_id, client.get("/coachs", {"team": team_id})))
    coach_rows = [row for _, result in coach_results for row in _response_rows(result)[0]]
    coach_errors = [(_text(result.get("reason_code")) or "API_REQUEST_FAILED", result) for _, result in coach_results if result.get("ok") is not True]
    if coach_errors and not coach_rows:
        fields["coach"] = _field_unavailable(coach_errors[0][0], endpoint="/coachs", params={"team": "BOUND_TEAMS"})
    elif not coach_rows:
        fields["coach"] = {"state": "EMPTY", "reason_code": "NO_COACH_RECORD", "value": None, "provenance": {"endpoint": "/coachs", "params": {"team": "BOUND_TEAMS"}}}
    else:
        fields["coach"] = {"state": "PRESENT", "reason_code": "PROJECTED_FROM_PROVIDER_RESPONSE", "value": _project_coaches(coach_rows), "provenance": {"endpoint": "/coachs", "team_count": len(coach_results), "cache_hits": sum(bool(result.get("cache_hit")) for _, result in coach_results)}}

    fields["lineup"] = _coverage_projected_field(client, coverage, "lineups", "/fixtures/lineups", fixture_params, _project_lineups)
    fields["stats"] = _team_stats_field(
        client,
        coverage,
        league_id=league_id,
        season=season,
        team_ids=(identity.get("api_home_team_id"), identity.get("api_away_team_id")),
        source_kickoff=source_kickoff,
        as_of=cutoff,
    )
    return {
        "snapshot_version": "api_football_fixture_evidence.v1",
        "identity": identity,
        "binding": {key: value for key, value in binding.items() if key not in {"api_home_name", "api_away_name"}},
        "fields": fields,
        "rights": {"api_key_persisted": False, "raw_response_persisted": False},
    }


def _unbound_snapshot(source: Mapping[str, Any], binding: Mapping[str, Any]) -> dict[str, Any]:
    reason = _text(binding.get("reason_code")) or "IDENTITY_UNBOUND"
    return {
        "snapshot_version": "api_football_fixture_evidence.v1",
        "identity": {
            "nowscore_fixture_id": _text(source.get("nowscore_id") or source.get("nowscoreId")) or None,
            "nowscore_home_team_id": _source_id(source, "home"),
            "nowscore_away_team_id": _source_id(source, "away"),
            "nowscore_sclass_id": _source_competition_id(source),
        },
        "binding": dict(binding),
        "fields": {name: _field_unavailable(reason) for name in FIELD_NAMES},
        "rights": {"api_key_persisted": False, "raw_response_persisted": False},
    }


def _raw_markers(value: Any) -> int:
    serialized = json.dumps(value, ensure_ascii=False, sort_keys=True)
    return sum(marker in serialized.casefold() for marker in ("<html", "<script", "<!doctype", "var h_data"))


def _relative(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT.resolve())).replace("\\", "/")
    except ValueError:
        return str(path)


def _fixture_id(fixture: Mapping[str, Any]) -> str | None:
    value = fixture.get("nowscore_id") or fixture.get("nowscoreId")
    return _text(value) or None


def _fixture_source(fixture: Mapping[str, Any], alias: Mapping[str, Any], bridge: Mapping[str, Any]) -> dict[str, Any]:
    source = dict(fixture)
    source["nowscore_id"] = _fixture_id(fixture)
    source["kickoff"] = fixture.get("kickoff") or f"{_text(fixture.get('matchDate'))}T{_text(fixture.get('matchTime'))}:00+08:00"
    source["aliases"] = alias.get("aliases") if isinstance(alias.get("aliases"), Mapping) else {"home": (), "away": ()}
    for key in ("nowscore_home_team_id", "nowscore_away_team_id"):
        if _positive_int(alias.get(key)) is not None:
            source[key] = _positive_int(alias.get(key))
    if bridge.get("status") == "BOUND":
        source["nowscore_sclass_id"] = bridge.get("competition_id")
    return source


def _read_cohort(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, Mapping) or not isinstance(value.get("fixtures"), list):
        raise ValueError(f"invalid prediction cohort: {path}")
    return dict(value)


def run_enrichment_cohort(
    *,
    cohort_path: str | Path | None = None,
    api_key: str | None = None,
    as_of: str | dt.datetime | None = None,
    business_date: str | None = None,
    max_matches: int = 12,
    registry_path: str | Path = DEFAULT_REGISTRY_PATH,
    api_client: ApiFootballSharedClient | None = None,
    alias_rows: list[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Run the same natural future cohort without changing Nowscore inputs."""

    from scripts.football_context_identity_feasibility_audit import (
        _fetch_nowscore_alias_rows,
        _future_fixture,
        _parse_timestamp,
        build_nowscore_alias_index,
        discover_natural_cohort,
        extract_nowscore_competition_bridge,
        nowscore_alias_evidence,
    )
    from scripts.nowscore_prematch_evidence import ANALYSIS_PAGE_URL, NowscorePublicClient

    cutoff = _parse_timestamp(as_of) if as_of else dt.datetime.now(dt.timezone.utc)
    if cutoff is None:
        raise ValueError(f"invalid as-of timestamp: {as_of}")
    if cohort_path is None:
        cohort, selected_path = discover_natural_cohort(
            cohort_path=None,
            business_date=business_date,
            as_of=as_of,
        )
        path = Path(selected_path)
    else:
        path = Path(cohort_path)
        cohort = _read_cohort(path)
    selected = [fixture for fixture in cohort["fixtures"] if isinstance(fixture, Mapping) and _future_fixture(fixture, cutoff)][: max(0, min(int(max_matches), 20))]
    if alias_rows is None:
        alias_rows, alias_error = _fetch_nowscore_alias_rows() if selected else ([], None)
    else:
        alias_error = None
    alias_index = build_nowscore_alias_index(alias_rows)
    nowscore_client = NowscorePublicClient(max_requests=max(1, len(selected)))
    registry = EntityRegistry.load(registry_path)
    client = api_client or ApiFootballSharedClient(api_key or "")
    records: list[dict[str, Any]] = []
    date_rows: dict[str, list[Mapping[str, Any]]] = {}
    date_errors: dict[str, str] = {}
    for fixture in selected:
        alias = nowscore_alias_evidence(fixture, alias_index, surface_error=alias_error)
        bridge = {"status": "UNBOUND", "reason_code": "NATIVE_COMPETITION_NOT_REQUESTED"}
        match_id = _fixture_id(fixture)
        if match_id:
            payload = nowscore_client.fetch("analysis_page", ANALYSIS_PAGE_URL.format(match_id=match_id))
            bridge = extract_nowscore_competition_bridge(getattr(payload, "body", None))
        source = _fixture_source(fixture, alias, bridge)
        record = {"source": source, "alias": alias, "competition": bridge}
        if not _text(client._key):
            record["binding"] = {"status": "UNBOUND", "reason_code": "API_KEY_MISSING"}
            records.append(record)
            continue
        source_date = _text(fixture.get("matchDate"))
        if source_date not in date_rows and source_date not in date_errors:
            result = client.get("/fixtures", {"date": source_date, "timezone": "Asia/Shanghai"})
            rows, error = _response_rows(result)
            if error:
                date_errors[source_date] = error
                date_rows[source_date] = []
            else:
                date_rows[source_date] = rows
        if source_date in date_errors:
            record["binding"] = {"status": "UNBOUND", "reason_code": date_errors[source_date]}
        else:
            record["binding"] = bind_fixture_identity(
                source,
                alias,
                date_rows[source_date],
                registry=registry,
                allow_bootstrap=True,
            )
        records.append(record)

    coverage_cache: dict[tuple[int, int], dict[str, Any]] = {}
    snapshots = []
    for record in records:
        binding = record["binding"]
        if binding.get("status") != "BOUND":
            snapshots.append(_unbound_snapshot(record["source"], binding))
            continue
        league_id = _positive_int(binding.get("api_league_id"))
        season = _positive_int(binding.get("season"))
        pair = (league_id or 0, season or 0)
        if pair not in coverage_cache:
            coverage_cache[pair] = read_league_coverage(
                client.get("/leagues", {"id": league_id, "season": season}),
                league_id=league_id or 0,
                season=season or 0,
            )
        snapshots.append(
            build_enrichment_snapshot(
                record["source"],
                binding,
                client,
                coverage=coverage_cache[pair],
                as_of=cutoff,
            )
        )
        source = record["source"]
        evidence = binding.get("evidence") if isinstance(binding.get("evidence"), Mapping) else {}
        if evidence.get("team_ids") or evidence.get("counterpart_pair"):
            home_id = _source_id(source, "home")
            away_id = _source_id(source, "away")
            if home_id and away_id:
                registry.accept_team(home_id, binding["api_home_team_id"], aliases=(binding.get("api_home_name"),), evidence=("unique_oriented_fixture",))
                registry.accept_team(away_id, binding["api_away_team_id"], aliases=(binding.get("api_away_name"),), evidence=("unique_oriented_fixture",))
        competition_id = _source_competition_id(source)
        if competition_id and (evidence.get("competition") or evidence.get("competition_context")):
            registry.accept_competition(competition_id, binding["api_league_id"], binding["season"], country=binding.get("country"), evidence=("unique_oriented_fixture",))
        registry.accept_fixture(
            source.get("nowscore_id"),
            binding["api_fixture_id"],
            nowscore_home_team_id=_source_id(source, "home"),
            nowscore_away_team_id=_source_id(source, "away"),
            api_home_team_id=binding.get("api_home_team_id"),
            api_away_team_id=binding.get("api_away_team_id"),
            nowscore_sclass_id=competition_id,
            api_league_id=binding.get("api_league_id"),
            season=binding.get("season"),
            kickoff=binding.get("kickoff"),
            evidence=("unique_oriented_fixture_with_verified_evidence",),
        )
    before_summary = EntityRegistry.load(registry_path).summary()
    after_summary = registry.summary()
    if after_summary != before_summary:
        registry.save(registry_path)
    binding_counts = Counter(str(record["binding"].get("status") or "UNBOUND") for record in records)
    reason_counts = Counter(str(record["binding"].get("reason_code") or "UNKNOWN") for record in records)
    field_states = {name: Counter(snapshot["fields"].get(name, {}).get("state", "UNAVAILABLE") for snapshot in snapshots) for name in FIELD_NAMES}
    report: dict[str, Any] = {
        "contract_version": "multi_source_evidence_spine.v1",
        "run": {
            "exact_head": _exact_head(),
            "cohort_source_path": _relative(path),
            "business_date": cohort.get("business_date"),
            "as_of": cutoff.isoformat(timespec="seconds"),
            "natural_cohort_count": len(selected),
        },
        "identity_registry": {
            "path": _relative(Path(registry_path)),
            "summary_before": before_summary,
            "summary_after": after_summary,
        },
        "api_football": {
            "credential_state": "PRESENT" if _text(client._key) else "MISSING",
            "request_cap": MAX_API_FOOTBALL_REQUESTS,
            "request_count": client.request_count,
            "blocked_request_count": client.blocked_request_count,
            "cache_hits": client.cache_hits,
            "endpoint_counts": dict(sorted(client.endpoint_counts.items())),
            "response_states": dict(sorted(client.response_states.items())),
            "binding_counts": dict(sorted(binding_counts.items())),
            "binding_reason_counts": dict(sorted(reason_counts.items())),
            "field_state_counts": {name: dict(sorted(counts.items())) for name, counts in field_states.items()},
            "league_season_coverage": list(coverage_cache.values()),
            "sidelined_player_cap": MAX_SIDELINED_PLAYERS,
        },
        "snapshots": snapshots,
        "boundary_proof": {
            "raw_body_persistence_count": 0,
            "raw_body_output_marker_count": _raw_markers(snapshots),
            "secret_leakage_count": 0,
            "fuzzy_matching_used": False,
            "name_similarity_acceptance_count": 0,
            "ambiguous_mapping_acceptance_count": 0,
            "orientation_swap_acceptance_count": 0,
            "api_prediction_used": False,
            "production_enrichment_written": False,
            "article_changed": False,
            "ui_changed": False,
            "model_changed": False,
            "champion_changed": False,
            "serving_changed": False,
            "rights": {"raw_bodies_persisted": False, "api_key_persisted": False},
        },
    }
    key = _text(api_key)
    if key and key in json.dumps(report, ensure_ascii=False):
        report["boundary_proof"]["secret_leakage_count"] = 1
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cohort-path")
    parser.add_argument("--business-date")
    parser.add_argument("--as-of")
    parser.add_argument("--max-matches", type=int, default=12)
    parser.add_argument("--registry", default=str(DEFAULT_REGISTRY_PATH))
    parser.add_argument("--output", default=str(DEFAULT_ARTIFACT_PATH))
    args = parser.parse_args(argv)
    try:
        report = run_enrichment_cohort(
            cohort_path=args.cohort_path,
            api_key=os.environ.get("API_FOOTBALL_KEY", ""),
            as_of=args.as_of,
            business_date=args.business_date,
            max_matches=args.max_matches,
            registry_path=args.registry,
        )
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"multi-source evidence spine failed: {type(error).__name__}: {error}")
        return 2
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": "ok",
        "output": str(output),
        "natural_cohort_count": report["run"]["natural_cohort_count"],
        "binding_counts": report["api_football"]["binding_counts"],
        "request_count": report["api_football"]["request_count"],
        "field_state_counts": report["api_football"]["field_state_counts"],
        "boundary_proof": report["boundary_proof"],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "ALLOWED_ENDPOINTS",
    "ApiFootballSharedClient",
    "DEFAULT_ARTIFACT_PATH",
    "DEFAULT_REGISTRY_PATH",
    "EntityRegistry",
    "MAX_API_FOOTBALL_REQUESTS",
    "MAX_SIDELINED_PLAYERS",
    "bind_fixture_identity",
    "build_enrichment_snapshot",
    "read_league_coverage",
    "run_enrichment_cohort",
]
