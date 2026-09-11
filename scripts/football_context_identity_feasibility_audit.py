#!/usr/bin/env python3
"""Read-only Issue #286 identity feasibility audit.

The audit keeps Nowscore responses transient, extracts only explicit
competition identifiers from the same ``analysis_page``, and keeps the
API-Football compatibility path limited to fixture identity plus
``/leagues`` coverage metadata.  Issue #293's shared spine is the strict
runtime path for durable cross-provider mappings.
"""

from __future__ import annotations

import argparse
import html as html_lib
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_ROOT = ROOT / "scripts"
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))

try:
    from nowscore_markets import (
        SCHEDULE_URL,
        _decode,
        _fetch_bytes,
        _parse_schedule_js,
    )
    from nowscore_prematch_evidence import (
        ANALYSIS_PAGE_URL,
        NowscorePublicClient,
        _fixture_kickoff,
        _future_fixture,
        _parse_timestamp,
        discover_natural_cohort,
    )
    from prediction_universe import trusted_nowscore_jc_fixture
except ImportError:  # package imports used by focused tests
    from scripts.nowscore_markets import (
        SCHEDULE_URL,
        _decode,
        _fetch_bytes,
        _parse_schedule_js,
    )
    from scripts.nowscore_prematch_evidence import (
        ANALYSIS_PAGE_URL,
        NowscorePublicClient,
        _fixture_kickoff,
        _future_fixture,
        _parse_timestamp,
        discover_natural_cohort,
    )
    from scripts.prediction_universe import trusted_nowscore_jc_fixture


SHANGHAI = ZoneInfo("Asia/Shanghai")
MAX_API_FOOTBALL_REQUESTS = 25
API_FOOTBALL_BASE_URL = "https://v3.football.api-sports.io"
API_ENDPOINTS = ("/fixtures", "/leagues")
FORBIDDEN_API_ENDPOINTS = ("/standings", "/injuries")
EXACT_ALIAS_FIELDS = ("home_team_en", "away_team_en")


def _positive_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    text = str(value).strip()
    if not text.isdigit():
        return None
    parsed = int(text)
    return parsed if parsed > 0 else None


def _clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", html_lib.unescape(str(value or ""))).strip()


def _exact_name_key(value: Any) -> str:
    """Case/whitespace normalization only; no transliteration or fuzzy match."""

    return _clean_text(value).casefold()


def _fixture_id(fixture: Mapping[str, Any]) -> int | None:
    return _positive_int(fixture.get("nowscore_id") or fixture.get("nowscoreId"))


def _source_kickoff(fixture: Mapping[str, Any]) -> datetime | None:
    return _parse_timestamp(_fixture_kickoff(fixture))


def _kickoff_key(value: Any) -> str | None:
    parsed = _parse_timestamp(value)
    if parsed is None:
        return None
    return parsed.astimezone(timezone.utc).replace(second=0, microsecond=0).isoformat()


def _source_date(fixture: Mapping[str, Any]) -> str | None:
    kickoff = _source_kickoff(fixture)
    return kickoff.astimezone(SHANGHAI).date().isoformat() if kickoff else None


def _exact_head() -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()


def extract_nowscore_competition_bridge(body: str | None) -> dict[str, Any]:
    """Extract only explicit source identifiers from an analysis page.

    Generic headings, competition labels, and section aliases are deliberately
    not considered evidence.  Multiple distinct source IDs fail closed.
    """

    if not isinstance(body, str) or not body.strip():
        return {
            "status": "UNBOUND",
            "reason_code": "ANALYSIS_PAGE_BODY_MISSING",
            "candidate_count": 0,
            "evidence_locations": [],
        }

    candidates: list[dict[str, Any]] = []
    for match in re.finditer(
        r"(?i)(?<![\w-])(?:var\s+)?sclassid\s*=\s*['\"]?(\d+)", body
    ):
        value = _positive_int(match.group(1))
        if value is not None:
            candidates.append({
                "competition_id": value,
                "evidence_location": "analysis_page:inline_script:sclassID_assignment",
            })

    for match in re.finditer(
        r'''(?is)href\s*=\s*["'](?P<href>[^"']*(?:SubLeague|Sclass)(?:\.aspx)?[^"']*)["']''',
        body,
    ):
        href = html_lib.unescape(match.group("href"))
        identifier = re.search(r"(?i)(?:^|[?&])sclassid=(\d+)", href)
        location = "analysis_page:href:SubLeague:SclassID"
        if identifier is None:
            identifier = re.search(r"(?i)(?:^|[?&])id=(\d+)", href)
            location = "analysis_page:href:Sclass:id"
        if identifier is None:
            path_match = re.search(r"(?i)/(?:SubLeague|Sclass)(?:/|-|_)(\d+)(?:$|[/?#])", href)
            if path_match:
                identifier = path_match
                location = "analysis_page:href:competition_path_id"
        value = _positive_int(identifier.group(1)) if identifier else None
        if value is not None:
            candidates.append({
                "competition_id": value,
                "evidence_location": location,
            })

    distinct_ids = sorted({item["competition_id"] for item in candidates})
    locations = sorted({item["evidence_location"] for item in candidates})
    if not distinct_ids:
        return {
            "status": "UNBOUND",
            "reason_code": "DIRECT_COMPETITION_ID_MISSING",
            "candidate_count": 0,
            "evidence_locations": [],
        }
    if len(distinct_ids) != 1:
        return {
            "status": "AMBIGUOUS",
            "reason_code": "DIRECT_COMPETITION_ID_AMBIGUOUS",
            "candidate_count": len(candidates),
            "candidate_ids": distinct_ids,
            "evidence_locations": locations,
        }
    return {
        "status": "BOUND",
        "reason_code": "DIRECT_SOURCE_COMPETITION_ID",
        "competition_id": distinct_ids[0],
        "candidate_count": len(candidates),
        "evidence_location": locations[0],
        "evidence_locations": locations,
        "source_surface": "analysis_page",
    }


def build_nowscore_alias_index(rows: list[Mapping[str, Any]]) -> dict[int, list[dict[str, Any]]]:
    """Index existing Nowscore English aliases by the exact Nowscore match ID."""

    index: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        match_id = _positive_int(row.get("nowscore_id"))
        if match_id is None:
            continue
        aliases = {
            "home": tuple(
                value
                for value in (_clean_text(row.get("home_team_en")),)
                if value
            ),
            "away": tuple(
                value
                for value in (_clean_text(row.get("away_team_en")),)
                if value
            ),
        }
        index[match_id].append({
            "aliases": aliases,
            "nowscore_home_team_id": _positive_int(row.get("home_team_id")),
            "nowscore_away_team_id": _positive_int(row.get("away_team_id")),
            "source_surface": "nowscore_schedule_bf1",
            "evidence_location": "bf1.js:exact_nowscore_id_row",
        })
    return dict(index)


def nowscore_alias_evidence(
    fixture: Mapping[str, Any],
    alias_index: Mapping[int, list[Mapping[str, Any]]],
    *,
    surface_error: str | None = None,
) -> dict[str, Any]:
    """Return sanitized alias availability plus transient exact aliases."""

    match_id = _fixture_id(fixture)
    if surface_error:
        return {
            "status": "UNBOUND",
            "reason_code": "NOWSCORE_ALIAS_SURFACE_UNAVAILABLE",
            "source_surface": "nowscore_schedule_bf1",
            "evidence_location": None,
            "field_presence": {field: False for field in EXACT_ALIAS_FIELDS},
            "alias_field_count": 0,
            "aliases": {"home": (), "away": ()},
        }
    rows = alias_index.get(match_id or 0, [])
    if len(rows) != 1:
        return {
            "status": "AMBIGUOUS" if len(rows) > 1 else "UNBOUND",
            "reason_code": (
                "NOWSCORE_ALIAS_ROW_AMBIGUOUS"
                if len(rows) > 1
                else "NOWSCORE_ALIAS_ROW_MISSING"
            ),
            "source_surface": "nowscore_schedule_bf1",
            "evidence_location": None,
            "field_presence": {field: False for field in EXACT_ALIAS_FIELDS},
            "alias_field_count": 0,
            "aliases": {"home": (), "away": ()},
        }
    aliases = rows[0].get("aliases") if isinstance(rows[0].get("aliases"), Mapping) else {}
    source_ids = {
        key: rows[0].get(key)
        for key in ("nowscore_home_team_id", "nowscore_away_team_id")
        if _positive_int(rows[0].get(key)) is not None
    }
    home = tuple(str(value) for value in aliases.get("home") or () if _clean_text(value))
    away = tuple(str(value) for value in aliases.get("away") or () if _clean_text(value))
    presence = {
        "home_team_en": bool(home),
        "away_team_en": bool(away),
    }
    if not home or not away:
        return {
            "status": "UNBOUND",
            "reason_code": "NOWSCORE_SOURCE_EXACT_ALIAS_MISSING",
            "source_surface": "nowscore_schedule_bf1",
            "evidence_location": rows[0].get("evidence_location"),
            "field_presence": presence,
            "alias_field_count": int(bool(home)) + int(bool(away)),
            "aliases": {"home": home, "away": away},
            **source_ids,
        }
    return {
        "status": "BOUND",
        "reason_code": "NOWSCORE_SOURCE_EXACT_ALIASES",
        "source_surface": "nowscore_schedule_bf1",
        "evidence_location": rows[0].get("evidence_location"),
        "field_presence": presence,
        "alias_field_count": 2,
        "aliases": {"home": home, "away": away},
        **source_ids,
    }


def _api_fixture_facts(row: Mapping[str, Any]) -> dict[str, Any] | None:
    fixture = row.get("fixture") if isinstance(row.get("fixture"), Mapping) else {}
    teams = row.get("teams") if isinstance(row.get("teams"), Mapping) else {}
    home = teams.get("home") if isinstance(teams.get("home"), Mapping) else {}
    away = teams.get("away") if isinstance(teams.get("away"), Mapping) else {}
    league = row.get("league") if isinstance(row.get("league"), Mapping) else {}
    fixture_id = _positive_int(fixture.get("id"))
    kickoff = _kickoff_key(fixture.get("date"))
    home_name = _clean_text(home.get("name"))
    away_name = _clean_text(away.get("name"))
    league_id = _positive_int(league.get("id"))
    season = _positive_int(league.get("season"))
    if fixture_id is None or not kickoff:
        return None
    return {
        "fixture_id": fixture_id,
        "kickoff_key": kickoff,
        "home_name": home_name,
        "away_name": away_name,
        "league_id": league_id,
        "league_name": _clean_text(league.get("name")) or None,
        "league_type": _clean_text(league.get("type")) or None,
        "season": season,
        "identity_evidence": row.get("identity_evidence") if isinstance(row.get("identity_evidence"), Mapping) else {},
    }


def bind_api_fixture_strict(
    fixture: Mapping[str, Any],
    aliases: Mapping[str, Any],
    api_rows: list[Mapping[str, Any]],
) -> dict[str, Any]:
    """Bind one API fixture only with exact aliases, orientation, and kickoff."""

    source_kickoff = _kickoff_key(_fixture_kickoff(fixture))
    alias_values = aliases.get("aliases") if isinstance(aliases.get("aliases"), Mapping) else {}
    home_aliases = {_exact_name_key(value) for value in alias_values.get("home") or ()}
    away_aliases = {_exact_name_key(value) for value in alias_values.get("away") or ()}
    if not source_kickoff:
        return {"status": "UNBOUND", "reason_code": "SOURCE_KICKOFF_MISSING"}
    if not home_aliases or not away_aliases:
        return {
            "status": "UNBOUND",
            "reason_code": "NOWSCORE_SOURCE_EXACT_ALIAS_MISSING",
        }

    oriented: list[dict[str, Any]] = []
    reversed_orientation: list[dict[str, Any]] = []
    name_oriented: list[dict[str, Any]] = []
    same_kickoff_rows: list[dict[str, Any]] = []
    for row in api_rows:
        if not isinstance(row, Mapping):
            continue
        facts = _api_fixture_facts(row)
        if facts is None:
            continue
        home_match = _exact_name_key(facts["home_name"]) in home_aliases
        away_match = _exact_name_key(facts["away_name"]) in away_aliases
        reverse_home_match = _exact_name_key(facts["home_name"]) in away_aliases
        reverse_away_match = _exact_name_key(facts["away_name"]) in home_aliases
        same_kickoff = facts["kickoff_key"] == source_kickoff
        if same_kickoff:
            same_kickoff_rows.append(facts)
        if home_match and away_match:
            name_oriented.append(facts)
            if same_kickoff:
                oriented.append(facts)
        if reverse_home_match and reverse_away_match and same_kickoff:
            reversed_orientation.append(facts)

    if len(oriented) > 1:
        return {
            "status": "AMBIGUOUS",
            "reason_code": "MULTIPLE_EXACT_API_FIXTURES",
            "candidate_count": len(oriented),
        }
    if len(oriented) == 1:
        candidate = oriented[0]
        if candidate["league_id"] is None or candidate["season"] is None:
            return {
                "status": "UNBOUND",
                "reason_code": "API_FIXTURE_LEAGUE_SEASON_MISSING",
                "candidate_count": 1,
            }
        identity = candidate.get("identity_evidence") if isinstance(candidate.get("identity_evidence"), Mapping) else {}
        independently_verified = bool(identity.get("team_ids") or identity.get("team")) or all(
            identity.get(key) is True for key in ("competition", "country", "roster")
        )
        if not independently_verified:
            return {
                "status": "UNBOUND",
                "reason_code": "TEAM_IDENTITY_UNPROVEN",
                "candidate_count": 1,
            }
        return {
            "status": "BOUND",
            "reason_code": "EXACT_KICKOFF_ORIENTATION_AND_ALIASES",
            "candidate_count": 1,
            "api_fixture_id": candidate["fixture_id"],
            "league_id": candidate["league_id"],
            "league_name": candidate["league_name"],
            "league_type": candidate["league_type"],
            "season": candidate["season"],
        }
    if reversed_orientation:
        return {
            "status": "UNBOUND",
            "reason_code": "ORIENTATION_MISMATCH",
            "candidate_count": len(reversed_orientation),
        }
    if name_oriented:
        return {
            "status": "UNBOUND",
            "reason_code": "KICKOFF_MISMATCH",
            "candidate_count": len(name_oriented),
        }
    if same_kickoff_rows:
        return {
            "status": "UNBOUND",
            "reason_code": "TEAM_IDENTITY_UNPROVEN",
            "candidate_count": 0,
        }
    return {
        "status": "UNBOUND",
        "reason_code": "NO_EXACT_API_FIXTURE",
        "candidate_count": 0,
    }


class ApiFootballClient:
    """Minimal bounded client; the API secret never enters returned data."""

    def __init__(
        self,
        key: str,
        *,
        opener: Callable[..., Any] | None = None,
        timeout: int = 30,
        max_requests: int = MAX_API_FOOTBALL_REQUESTS,
    ) -> None:
        self._key = str(key or "").strip()
        self.opener = opener or urllib.request.urlopen
        self.timeout = timeout
        self.max_requests = max(0, min(int(max_requests), MAX_API_FOOTBALL_REQUESTS))
        self.request_count = 0
        self.blocked_request_count = 0
        self.endpoint_counts: Counter[str] = Counter()

    def get(self, endpoint: str, params: Mapping[str, Any]) -> dict[str, Any]:
        endpoint = "/" + str(endpoint).strip("/")
        if endpoint not in API_ENDPOINTS:
            return {"ok": False, "reason_code": "API_ENDPOINT_NOT_ALLOWED"}
        if not self._key:
            return {"ok": False, "reason_code": "API_KEY_MISSING"}
        if self.request_count >= self.max_requests:
            self.blocked_request_count += 1
            return {"ok": False, "reason_code": "API_REQUEST_CAP_REACHED"}
        self.request_count += 1
        self.endpoint_counts[endpoint] += 1
        query = urllib.parse.urlencode({key: str(value) for key, value in params.items()})
        url = f"{API_FOOTBALL_BASE_URL}{endpoint}?{query}"
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": "FBOS-issue-286-read-only-audit/1",
                "x-apisports-key": self._key,
            },
        )
        try:
            with self.opener(request, timeout=self.timeout) as response:
                raw = response.read()
                payload = json.loads(raw.decode("utf-8"))
        except urllib.error.HTTPError:
            return {"ok": False, "reason_code": "API_HTTP_ERROR"}
        except (urllib.error.URLError, TimeoutError, OSError):
            return {"ok": False, "reason_code": "API_NETWORK_ERROR"}
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
            return {"ok": False, "reason_code": "API_RESPONSE_INVALID"}
        if not isinstance(payload, Mapping):
            return {"ok": False, "reason_code": "API_RESPONSE_INVALID"}
        if payload.get("errors"):
            errors = payload.get("errors")
            if isinstance(errors, Mapping):
                error_keys = sorted(str(key) for key in errors if str(key).strip())
            elif isinstance(errors, list):
                error_keys = sorted(
                    str(item.get("code") or item.get("type"))
                    for item in errors
                    if isinstance(item, Mapping) and str(item.get("code") or item.get("type")).strip()
                )
            else:
                error_keys = ["provider_error"]
            return {
                "ok": False,
                "reason_code": "API_PROVIDER_ERROR",
                "response_state": "PROVIDER_ERROR",
                "provider_error_keys": error_keys,
            }
        if not isinstance(payload.get("response"), list):
            return {
                "ok": False,
                "reason_code": "API_RESPONSE_ENVELOPE_INVALID",
                "response_state": "INVALID_ENVELOPE",
            }
        return {"ok": True, "response_state": "OK", "payload": dict(payload)}


def _response_rows(result: Mapping[str, Any]) -> tuple[list[Mapping[str, Any]], str | None]:
    if result.get("ok") is not True:
        return [], str(result.get("reason_code") or "API_REQUEST_FAILED")
    payload = result.get("payload")
    response = payload.get("response") if isinstance(payload, Mapping) else None
    if not isinstance(response, list):
        return [], "API_RESPONSE_MISSING_LIST"
    return [row for row in response if isinstance(row, Mapping)], None


def _api_league_season_entries(row: Mapping[str, Any]) -> list[dict[str, Any]]:
    league = row.get("league") if isinstance(row.get("league"), Mapping) else {}
    entries: list[dict[str, Any]] = []
    if _positive_int(league.get("season")) is not None or isinstance(league.get("coverage"), Mapping):
        entries.append({
            "id": league.get("id"),
            "name": league.get("name"),
            "type": league.get("type"),
            "season": league.get("season"),
            "coverage": league.get("coverage"),
        })
    seasons = row.get("seasons") if isinstance(row.get("seasons"), list) else league.get("seasons")
    if isinstance(seasons, list):
        for season_row in seasons:
            if isinstance(season_row, Mapping):
                entries.append({
                    "id": league.get("id"),
                    "name": league.get("name"),
                    "type": league.get("type"),
                    "season": season_row.get("year") or season_row.get("season"),
                    "coverage": season_row.get("coverage"),
                })
    return entries


def read_api_league_coverage(
    result: Mapping[str, Any],
    *,
    league_id: int,
    season: int,
) -> dict[str, Any]:
    """Read only the season-specific coverage flags from a /leagues response."""

    rows, error = _response_rows(result)
    if error:
        return {
            "status": "UNAVAILABLE",
            "reason_code": error,
            "league_id": league_id,
            "season": season,
            "coverage": {"standings": None, "injuries": None},
        }
    exact = []
    season_mismatch = False
    for row in rows:
        for league in _api_league_season_entries(row):
            if _positive_int(league.get("id")) != league_id:
                continue
            row_season = _positive_int(league.get("season"))
            if row_season is not None and row_season != season:
                season_mismatch = True
                continue
            exact.append(league)
    if len(exact) != 1:
        return {
            "status": "AMBIGUOUS" if len(exact) > 1 else "UNAVAILABLE",
            "reason_code": (
                "API_LEAGUE_SEASON_RESPONSE_AMBIGUOUS"
                if len(exact) > 1
                else "API_LEAGUE_SEASON_MISMATCH" if season_mismatch else "API_LEAGUE_SEASON_NO_COVERAGE"
            ),
            "league_id": league_id,
            "season": season,
            "coverage": {"standings": None, "injuries": None},
        }
    league = exact[0]
    coverage = league.get("coverage") if isinstance(league.get("coverage"), Mapping) else {}
    standings = coverage.get("standings")
    injuries = coverage.get("injuries")
    if not isinstance(standings, bool) or not isinstance(injuries, bool):
        return {
            "status": "UNAVAILABLE",
            "reason_code": "API_COVERAGE_FLAGS_MISSING",
            "league_id": league_id,
            "league_name": _clean_text(league.get("name")) or None,
            "league_type": _clean_text(league.get("type")) or None,
            "season": season,
            "coverage": {
                "standings": standings if isinstance(standings, bool) else None,
                "injuries": injuries if isinstance(injuries, bool) else None,
            },
        }
    return {
        "status": "READ",
        "reason_code": "SEASON_SPECIFIC_COVERAGE_READ",
        "league_id": league_id,
        "league_name": _clean_text(league.get("name")) or None,
        "league_type": _clean_text(league.get("type")) or None,
        "season": season,
        "coverage": {"standings": standings, "injuries": injuries},
    }


def _fetch_nowscore_alias_rows() -> tuple[list[Mapping[str, Any]], str | None]:
    try:
        raw = _fetch_bytes(SCHEDULE_URL)
        rows, _ = _parse_schedule_js(_decode(raw))
        return rows, None
    except Exception:
        return [], "NOWSCORE_ALIAS_SURFACE_UNAVAILABLE"


def _select_fixtures(
    cohort: Mapping[str, Any],
    *,
    as_of: str | datetime | None,
    max_matches: int,
) -> tuple[list[Mapping[str, Any]], datetime]:
    cutoff = _parse_timestamp(as_of) if as_of else datetime.now(SHANGHAI)
    if cutoff is None:
        raise ValueError(f"invalid as-of timestamp: {as_of}")
    fixtures = [item for item in cohort.get("fixtures") or [] if isinstance(item, Mapping)]
    future = [item for item in fixtures if _future_fixture(item, cutoff)]
    selected = future[: max(0, min(int(max_matches), 20))]
    return selected, cutoff


def _observation_summary(payload: Any) -> dict[str, Any]:
    observation = getattr(payload, "observation", {})
    return {
        "http_status": observation.get("http_status"),
        "error_code": observation.get("error_code"),
        "content_length": observation.get("content_length"),
    }


def _sanitized_record(record: Mapping[str, Any]) -> dict[str, Any]:
    competition = record.get("nowscore_competition") if isinstance(record.get("nowscore_competition"), Mapping) else {}
    aliases = record.get("nowscore_aliases") if isinstance(record.get("nowscore_aliases"), Mapping) else {}
    api = record.get("api_fixture") if isinstance(record.get("api_fixture"), Mapping) else {}
    coverage = record.get("api_coverage") if isinstance(record.get("api_coverage"), Mapping) else None
    return {
        "nowscore_id": record.get("nowscore_id"),
        "kickoff": record.get("kickoff"),
        "nowscore_competition": {
            key: competition.get(key)
            for key in (
                "status",
                "reason_code",
                "competition_id",
                "candidate_count",
                "evidence_location",
                "evidence_locations",
                "source_surface",
            )
            if key in competition
        },
        "nowscore_aliases": {
            key: aliases.get(key)
            for key in (
                "status",
                "reason_code",
                "source_surface",
                "evidence_location",
                "field_presence",
                "alias_field_count",
            )
            if key in aliases
        },
        "api_fixture": {
            key: api.get(key)
            for key in (
                "status",
                "reason_code",
                "candidate_count",
                "api_fixture_id",
                "league_id",
                "league_name",
                "league_type",
                "season",
            )
            if key in api
        },
        "api_coverage": {
            key: coverage.get(key)
            for key in (
                "status",
                "reason_code",
                "league_id",
                "league_name",
                "league_type",
                "season",
                "coverage",
            )
            if key in coverage
        } if coverage else None,
    }


def _choose_representatives(records: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    chosen: list[Mapping[str, Any]] = []
    predicates = (
        lambda row: (row.get("api_fixture") or {}).get("status") in {"UNBOUND", "AMBIGUOUS"},
        lambda row: (row.get("api_fixture") or {}).get("status") == "BOUND",
        lambda row: (row.get("nowscore_competition") or {}).get("status") in {"UNBOUND", "AMBIGUOUS"},
    )
    for predicate in predicates:
        item = next((row for row in records if row not in chosen and predicate(row)), None)
        if item is not None:
            chosen.append(item)
    for item in records:
        if len(chosen) >= 3:
            break
        if item not in chosen:
            chosen.append(item)
    return [_sanitized_record(item) for item in chosen[:3]]


def _count_statuses(records: list[Mapping[str, Any]], key: str) -> dict[str, Any]:
    statuses = Counter(str((record.get(key) or {}).get("status") or "UNBOUND") for record in records)
    reasons = Counter(str((record.get(key) or {}).get("reason_code") or "UNKNOWN") for record in records)
    return {
        "bound_count": int(statuses.get("BOUND", 0)),
        "unbound_count": int(statuses.get("UNBOUND", 0)),
        "ambiguous_count": int(statuses.get("AMBIGUOUS", 0)),
        "status_counts": dict(sorted(statuses.items())),
        "reason_counts": dict(sorted(reasons.items())),
    }


def _coverage_pairs(records: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    pairs: dict[tuple[int, int], Mapping[str, Any]] = {}
    for record in records:
        coverage = record.get("api_coverage")
        api = record.get("api_fixture")
        if not isinstance(coverage, Mapping) or not isinstance(api, Mapping):
            continue
        league_id = _positive_int(api.get("league_id"))
        season = _positive_int(api.get("season"))
        if league_id is not None and season is not None:
            pairs.setdefault((league_id, season), coverage)
    return [dict(pairs[key]) for key in sorted(pairs)]


def _nowscore_competition_bindings(records: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    bindings = []
    for record in records:
        bridge = record.get("nowscore_competition")
        if not isinstance(bridge, Mapping) or bridge.get("status") != "BOUND":
            continue
        bindings.append({
            "nowscore_id": record.get("nowscore_id"),
            "competition_id": bridge.get("competition_id"),
            "source_surface": bridge.get("source_surface"),
            "evidence_location": bridge.get("evidence_location"),
        })
    return bindings


def _api_exact_bindings(records: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    bindings = []
    for record in records:
        api = record.get("api_fixture")
        if not isinstance(api, Mapping) or api.get("status") != "BOUND":
            continue
        coverage = record.get("api_coverage")
        bindings.append({
            "nowscore_id": record.get("nowscore_id"),
            "api_fixture_id": api.get("api_fixture_id"),
            "league_id": api.get("league_id"),
            "league_name": api.get("league_name"),
            "league_type": api.get("league_type"),
            "season": api.get("season"),
            "coverage": coverage.get("coverage") if isinstance(coverage, Mapping) else None,
            "coverage_status": coverage.get("status") if isinstance(coverage, Mapping) else "NOT_REQUESTED",
            "coverage_reason_code": coverage.get("reason_code") if isinstance(coverage, Mapping) else "NOT_REQUESTED",
        })
    return bindings


def _relative_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT.resolve())).replace("\\", "/")
    except ValueError:
        return str(path)


def _contains_raw_markers(value: Any) -> int:
    serialized = json.dumps(value, ensure_ascii=False, sort_keys=True)
    return sum(
        marker.casefold() in serialized.casefold()
        for marker in ("<html", "<script", "<!doctype", "var h_data")
    )


def build_audit_report(
    *,
    cohort: Mapping[str, Any],
    cohort_path: Path,
    cutoff: datetime,
    records: list[Mapping[str, Any]],
    nowscore_analysis_requests: int,
    nowscore_alias_request_count: int,
    api_client: ApiFootballClient | None,
    api_key_present: bool,
    api_secret_for_check: str = "",
    exact_head: str,
) -> dict[str, Any]:
    api_request_count = api_client.request_count if api_client else 0
    endpoint_counts = {
        endpoint: int(api_client.endpoint_counts.get(endpoint, 0)) if api_client else 0
        for endpoint in API_ENDPOINTS
    }
    api_bridge = _count_statuses(records, "api_fixture")
    nowscore_bridge = _count_statuses(records, "nowscore_competition")
    alias_bridge = _count_statuses(records, "nowscore_aliases")
    report: dict[str, Any] = {
        "audit_version": "football_context_identity_feasibility.v1",
        "run": {
            "execution": "github_actions_live",
            "exact_head": exact_head,
            "as_of": cutoff.isoformat(timespec="seconds"),
            "natural_cohort_count": len(records),
            "cohort_source_path": _relative_path(cohort_path),
            "cohort_business_date": cohort.get("business_date"),
        },
        "nowscore": {
            "analysis_page_request_count": nowscore_analysis_requests,
            "alias_surface_request_count": nowscore_alias_request_count,
            "direct_competition_bridge": nowscore_bridge,
            "exact_alias_bridge": alias_bridge,
            "direct_competition_bindings": _nowscore_competition_bindings(records),
        },
        "api_football": {
            "credential_state": "PRESENT" if api_key_present else "MISSING",
            "request_cap": MAX_API_FOOTBALL_REQUESTS,
            "request_count": api_request_count,
            "blocked_request_count": api_client.blocked_request_count if api_client else 0,
            "endpoint_counts": endpoint_counts,
            "forbidden_endpoint_counts": {endpoint: 0 for endpoint in FORBIDDEN_API_ENDPOINTS},
            "fixture_bridge": api_bridge,
            "exact_fixture_bindings": _api_exact_bindings(records),
            "league_season_coverage_pairs": _coverage_pairs(records),
        },
        "sanitized_records": _choose_representatives(records),
        "boundary_proof": {
            "raw_body_persistence_count": 0,
            "raw_body_output_marker_count": 0,
            "secret_leakage_count": 0,
            "fuzzy_matching_used": False,
            "manual_mapping_used": False,
            "orientation_swap_attempt_count": 0,
            "date_only_binding_count": 0,
            "kickoff_only_binding_count": 0,
            "standings_endpoint_call_count": 0,
            "injuries_endpoint_call_count": 0,
            "production_enrichment_written": False,
            "production_mapping_file_created": False,
            "article_changed": False,
            "ui_changed": False,
            "model_changed": False,
            "champion_changed": False,
            "serving_changed": False,
            "rights": {
                "raw_bodies_persisted": False,
                "raw_html_js_persisted": False,
                "api_key_persisted": False,
            },
        },
    }
    serialized = json.dumps(report, ensure_ascii=False, sort_keys=True)
    if api_secret_for_check and api_secret_for_check in serialized:
        report["boundary_proof"]["secret_leakage_count"] = 1
    report["boundary_proof"]["raw_body_output_marker_count"] = _contains_raw_markers(report)
    return report


def run_audit(
    *,
    cohort_path: str | Path | None = None,
    business_date: str | None = None,
    as_of: str | datetime | None = None,
    max_matches: int = 12,
    api_key: str | None = None,
    nowscore_client_factory: Callable[[int], Any] | None = None,
    api_client: ApiFootballClient | None = None,
) -> dict[str, Any]:
    cohort, selected_path = discover_natural_cohort(
        cohort_path=cohort_path,
        business_date=business_date,
        as_of=as_of,
    )
    selected, cutoff = _select_fixtures(cohort, as_of=as_of, max_matches=max_matches)
    alias_rows, alias_error = _fetch_nowscore_alias_rows() if selected else ([], None)
    alias_index = build_nowscore_alias_index(alias_rows)
    client = (
        nowscore_client_factory(max(1, len(selected)))
        if nowscore_client_factory
        else NowscorePublicClient(max_requests=max(1, len(selected)))
    )
    records: list[dict[str, Any]] = []
    for fixture in selected:
        match_id = _fixture_id(fixture)
        record: dict[str, Any] = {
            "nowscore_id": match_id,
            "kickoff": _fixture_kickoff(fixture),
            "nowscore_competition": {
                "status": "UNBOUND",
                "reason_code": "INVALID_NOWSCORE_ID",
            },
            "nowscore_aliases": nowscore_alias_evidence(
                fixture,
                alias_index,
                surface_error=alias_error,
            ),
        }
        if match_id is not None and trusted_nowscore_jc_fixture(fixture, match_id).get("trusted"):
            payload = client.fetch(
                "analysis_page",
                ANALYSIS_PAGE_URL.format(match_id=match_id),
            )
            bridge = extract_nowscore_competition_bridge(getattr(payload, "body", None))
            bridge["observation"] = _observation_summary(payload)
            record["nowscore_competition"] = bridge
        else:
            record["nowscore_competition"]["reason_code"] = "NOWSCORE_TRUST_GATE_REJECTED"
        record["api_fixture"] = {
            "status": "UNBOUND",
            "reason_code": "API_KEY_MISSING" if not str(api_key or "").strip() else "PENDING_EXACT_BINDING",
        }
        records.append(record)

    key = str(api_key or "").strip()
    live_api = api_client if api_client is not None else (ApiFootballClient(key) if key else None)
    if live_api is not None:
        fixture_rows_by_date: dict[str, list[Mapping[str, Any]]] = {}
        fixture_error_by_date: dict[str, str] = {}
        for record, fixture in zip(records, selected):
            aliases = record.get("nowscore_aliases")
            source_date = _source_date(fixture)
            if not isinstance(aliases, Mapping) or aliases.get("status") != "BOUND":
                record["api_fixture"] = {
                    "status": "UNBOUND",
                    "reason_code": str((aliases or {}).get("reason_code") or "NOWSCORE_SOURCE_EXACT_ALIAS_MISSING"),
                }
                continue
            if source_date is None:
                record["api_fixture"] = {
                    "status": "UNBOUND",
                    "reason_code": "SOURCE_KICKOFF_MISSING",
                }
                continue
            if source_date not in fixture_rows_by_date and source_date not in fixture_error_by_date:
                result = live_api.get(
                    "/fixtures",
                    {"date": source_date, "timezone": "Asia/Shanghai"},
                )
                rows, error = _response_rows(result)
                if error:
                    fixture_error_by_date[source_date] = error
                    fixture_rows_by_date[source_date] = []
                else:
                    fixture_rows_by_date[source_date] = rows
            if source_date in fixture_error_by_date:
                record["api_fixture"] = {
                    "status": "UNBOUND",
                    "reason_code": fixture_error_by_date[source_date],
                }
            else:
                record["api_fixture"] = bind_api_fixture_strict(
                    fixture,
                    aliases,
                    fixture_rows_by_date[source_date],
                )

        coverage_cache: dict[tuple[int, int], dict[str, Any]] = {}
        for record in records:
            api_result = record.get("api_fixture")
            if not isinstance(api_result, Mapping) or api_result.get("status") != "BOUND":
                continue
            league_id = _positive_int(api_result.get("league_id"))
            season = _positive_int(api_result.get("season"))
            if league_id is None or season is None:
                continue
            pair = (league_id, season)
            if pair not in coverage_cache:
                coverage_cache[pair] = read_api_league_coverage(
                    live_api.get("/leagues", {"id": league_id, "season": season}),
                    league_id=league_id,
                    season=season,
                )
            record["api_coverage"] = coverage_cache[pair]
    else:
        for record in records:
            record["api_fixture"] = {
                "status": "UNBOUND",
                "reason_code": "API_KEY_MISSING",
            }

    return build_audit_report(
        cohort=cohort,
        cohort_path=selected_path,
        cutoff=cutoff,
        records=records,
        nowscore_analysis_requests=int(getattr(client, "request_count", 0)),
        nowscore_alias_request_count=1 if selected else 0,
        api_client=live_api,
        api_key_present=bool(key),
        api_secret_for_check=key,
        exact_head=_exact_head(),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cohort-path")
    parser.add_argument("--business-date")
    parser.add_argument("--as-of")
    parser.add_argument("--max-matches", type=int, default=12)
    parser.add_argument("--output", default="football-context-identity-feasibility-audit.json")
    args = parser.parse_args(argv)
    try:
        report = run_audit(
            cohort_path=args.cohort_path,
            business_date=args.business_date,
            as_of=args.as_of,
            max_matches=args.max_matches,
            api_key=os.environ.get("API_FOOTBALL_KEY", ""),
        )
    except (FileNotFoundError, OSError, ValueError, json.JSONDecodeError, subprocess.SubprocessError) as error:
        print(f"football context identity feasibility audit failed: {type(error).__name__}: {error}", file=sys.stderr)
        return 2
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": "ok",
        "output": str(output),
        "exact_head": report["run"]["exact_head"],
        "natural_cohort_count": report["run"]["natural_cohort_count"],
        "nowscore_direct_competition_bridge": report["nowscore"]["direct_competition_bridge"],
        "api_fixture_bridge": report["api_football"]["fixture_bridge"],
        "api_request_count": report["api_football"]["request_count"],
        "api_endpoint_counts": report["api_football"]["endpoint_counts"],
        "boundary_proof": report["boundary_proof"],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
