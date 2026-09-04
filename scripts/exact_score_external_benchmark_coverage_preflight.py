#!/usr/bin/env python3
"""Preflight read-only The Odds API correct-score coverage for future FBOS fixtures."""

from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import re
import sys
from typing import Any, Callable, Iterable, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

try:  # Direct script execution and package-style test imports both work.
    from match_identity import canonical_match_id
    from postmatch_queue import parse_datetime
    from team_identity import team_names
except ImportError:  # pragma: no cover - exercised by package runners.
    from scripts.match_identity import canonical_match_id
    from scripts.postmatch_queue import parse_datetime
    from scripts.team_identity import team_names


MILESTONE = "EXACT-SCORE-EXTERNAL-BENCHMARK-COVERAGE-PREFLIGHT-1"
SCHEMA_VERSION = "exact_score_external_benchmark_coverage_preflight_1.v1"
PROVIDER_NAME = "the-odds-api.com"
PROVIDER_SITE = "https://the-odds-api.com/"
API_HOST = "https://api.the-odds-api.com"
API_KEY_ENV = "THE_ODDS_API_KEY"
SOCCER_GROUP = "soccer"
CORRECT_SCORE_MARKET = "correct_score"
PROBE_REGION = "eu"
MAX_CREDITS = 100
KICKOFF_TOLERANCE_SECONDS = 60.0
SHANGHAI = ZoneInfo("Asia/Shanghai")
HTTP_TIMEOUT_SECONDS = 30
VALID_IDENTITY_STATUSES = {
    "EXACT_MATCH",
    "NO_PROVIDER_SPORT_MAPPING",
    "NO_EVENT_MATCH",
    "IDENTITY_AMBIGUOUS_FAIL_CLOSED",
}
VALID_DECISIONS = {
    "CORRECT_SCORE_BENCHMARK_PILOT_READY",
    "PROVIDER_COVERAGE_INSUFFICIENT",
    "IDENTITY_MAPPING_NOT_READY",
    "FAIL_CLOSED",
}
READ_ONLY_CONTROLS = {
    "read_only_preflight": True,
    "result_network_fetch": False,
    "historical_backfill": False,
    "manual_identity_assignment": False,
    "fuzzy_matching": False,
    "frozen_prediction_modified": False,
    "authoritative_result_modified": False,
    "champion_modified": False,
    "challenger_modified": False,
    "model_modified": False,
    "serving_modified": False,
    "promotion_attempted": False,
    "paid_upgrade_attempted": False,
    "raw_feed_published": False,
}
_SCORE_LABEL = re.compile(r"^\s*(\d+)\s*[-:]\s*(\d+)\s*$")
_USAGE_HEADERS = (
    "x-requests-used",
    "x-requests-remaining",
    "x-requests-last",
)


class PreflightError(RuntimeError):
    """Raised when a safe, trustworthy provider preflight cannot be completed."""


class CredentialRequired(PreflightError):
    """Raised when the required GitHub Actions secret is not present."""


class ProviderRequestError(PreflightError):
    """A provider request failed without retaining URL/query/secret details."""


Transport = Callable[[str, Mapping[str, str]], tuple[Any, Mapping[str, Any]]]


def _parse_instant(value: Any, label: str) -> datetime:
    parsed = parse_datetime(value)
    if parsed is None:
        raise PreflightError(f"{label} is missing or invalid")
    return parsed.astimezone(timezone.utc)


def _snapshot(value: Any | None) -> datetime:
    return _parse_instant(value, "snapshot_at") if value is not None else datetime.now(timezone.utc)


def _fixture_kickoff(fixture: Mapping[str, Any]) -> datetime:
    raw_kickoff = fixture.get("kickoff_at") or fixture.get("kickoff")
    if raw_kickoff:
        return _parse_instant(raw_kickoff, "fixture kickoff")
    date_text = str(fixture.get("matchDate") or fixture.get("match_date") or "").strip()
    time_text = str(fixture.get("matchTime") or fixture.get("match_time") or "").strip()[:5]
    if not date_text or not time_text:
        raise PreflightError("canonical fixture has no kickoff date/time")
    try:
        local = datetime.strptime(f"{date_text} {time_text}", "%Y-%m-%d %H:%M")
    except ValueError as error:
        raise PreflightError("canonical fixture kickoff date/time is invalid") from error
    return local.replace(tzinfo=SHANGHAI).astimezone(timezone.utc)


def _fixture_identity(fixture: Mapping[str, Any]) -> tuple[str, str, str, str, datetime]:
    match_id = str(fixture.get("matchId") or fixture.get("match_id") or "").strip()
    home = str(fixture.get("homeTeam") or fixture.get("home_team") or fixture.get("home") or "").strip()
    away = str(fixture.get("awayTeam") or fixture.get("away_team") or fixture.get("away") or "").strip()
    league = str(fixture.get("league") or fixture.get("competition") or "").strip()
    if not match_id or not home or not away or not league:
        raise PreflightError("canonical fixture is missing match id, teams, or competition")
    kickoff = _fixture_kickoff(fixture)
    return match_id, home, away, league, kickoff


def _candidate_from_fixture(
    fixture: Mapping[str, Any],
    *,
    source_file: str,
) -> dict[str, Any]:
    match_id, home, away, league, kickoff = _fixture_identity(fixture)
    identity_input = {
        "home": home,
        "away": away,
        "kickoff": kickoff.isoformat(),
    }
    return {
        "match_id": match_id,
        "fbos_match_id": match_id,
        "match_key": canonical_match_id(identity_input),
        "kickoff": kickoff.isoformat(),
        "home": home,
        "away": away,
        "home_team_en": str(fixture.get("homeTeamEn") or fixture.get("home_team_en") or "").strip() or None,
        "away_team_en": str(fixture.get("awayTeamEn") or fixture.get("away_team_en") or "").strip() or None,
        "competition": league,
        "competition_source": "canonical_prediction_universe.league",
        "source_files": [source_file],
    }


def build_candidate_cohort(
    documents: Iterable[Mapping[str, Any]],
    *,
    snapshot_at: Any,
) -> dict[str, Any]:
    """Build one future candidate per canonical fixture identity without mutation."""

    snapshot = _snapshot(snapshot_at)
    by_match_id: dict[str, dict[str, Any]] = {}
    raw_future_rows = 0
    past_or_due_rows = 0
    source_file_count = 0
    for index, document in enumerate(documents):
        if not isinstance(document, Mapping):
            continue
        source_file = str(document.get("_source_file") or f"document-{index}")
        source_file_count += 1
        status = str(document.get("status") or "").strip()
        if status not in {"READY", "EMPTY_CONFIRMED"}:
            continue
        fixtures = document.get("fixtures") or []
        if not isinstance(fixtures, list):
            raise PreflightError("canonical prediction-universe fixtures are not a list")
        for fixture in fixtures:
            if not isinstance(fixture, Mapping):
                raise PreflightError("canonical prediction-universe contains a malformed fixture")
            candidate = _candidate_from_fixture(fixture, source_file=source_file)
            kickoff = _parse_instant(candidate["kickoff"], "candidate kickoff")
            if kickoff <= snapshot:
                past_or_due_rows += 1
                continue
            raw_future_rows += 1
            match_id = candidate["match_id"]
            existing = by_match_id.get(match_id)
            if existing is not None:
                same_identity = all(existing[key] == candidate[key] for key in ("match_key", "kickoff", "home", "away", "competition"))
                if not same_identity:
                    raise PreflightError(f"canonical match id has conflicting future identities: {match_id}")
                existing["source_files"] = sorted(set(existing["source_files"] + candidate["source_files"]))
                continue
            by_match_id[match_id] = candidate

    candidates = sorted(
        by_match_id.values(),
        key=lambda row: (row["kickoff"], row["match_key"], row["match_id"]),
    )
    by_key: dict[str, list[str]] = defaultdict(list)
    for candidate in candidates:
        by_key[candidate["match_key"]].append(candidate["match_id"])
    collisions = {key: ids for key, ids in by_key.items() if len(ids) > 1}
    if collisions:
        raise PreflightError("distinct canonical ids collide on one FBOS match key")
    return {
        "snapshot_at": snapshot.isoformat(),
        "candidate_count": len(candidates),
        "raw_future_candidate_rows": raw_future_rows,
        "deduplicated_match_count": raw_future_rows - len(candidates),
        "past_or_due_fixture_count": past_or_due_rows,
        "universe_document_count": source_file_count,
        "competition_labels": sorted({row["competition"] for row in candidates}),
        "candidates": candidates,
    }


def load_candidate_cohort(universe_root: Path, *, snapshot_at: Any) -> dict[str, Any]:
    documents: list[dict[str, Any]] = []
    root = Path(universe_root)
    files = sorted(root.glob("*.json"))
    for path in files:
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise PreflightError(f"cannot read canonical universe snapshot: {path.name}") from error
        if isinstance(document, Mapping):
            documents.append({**document, "_source_file": path.name})
    cohort = build_candidate_cohort(documents, snapshot_at=snapshot_at)
    cohort["universe_files_scanned"] = len(files)
    return cohort


def parse_regulation_scoreline(label: Any) -> tuple[int, int] | None:
    """Parse only an explicit home-away score token; reject AET/semantic labels."""

    match = _SCORE_LABEL.fullmatch(str(label or ""))
    if not match:
        return None
    return int(match.group(1)), int(match.group(2))


def _team_identity_names(candidate: Mapping[str, Any], side: str) -> set[str]:
    names = set(team_names(candidate.get(side) or ""))
    english = candidate.get(f"{side}_team_en")
    if english:
        names.update(team_names(english))
    names.discard("")
    return names


def _event_time(event: Mapping[str, Any]) -> datetime | None:
    try:
        return _parse_instant(event.get("commence_time") or event.get("kickoff_at"), "provider kickoff")
    except PreflightError:
        return None


def _event_id(event: Mapping[str, Any]) -> str:
    return str(event.get("id") or event.get("event_id") or "").strip()


def _event_sport_key(event: Mapping[str, Any]) -> str:
    return str(event.get("sport_key") or "").strip()


def match_candidate_to_events(
    candidate: Mapping[str, Any],
    events: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    """Resolve exact ordered aliases plus normalized kickoff, never similarity."""

    candidate_kickoff = _parse_instant(candidate.get("kickoff"), "candidate kickoff")
    home_names = _team_identity_names(candidate, "home")
    away_names = _team_identity_names(candidate, "away")
    exact: list[dict[str, Any]] = []
    kickoff_only_ids: set[str] = set()
    partial_ids: set[str] = set()
    for raw_event in events:
        if not isinstance(raw_event, Mapping):
            continue
        provider_id = _event_id(raw_event)
        provider_sport = _event_sport_key(raw_event)
        provider_home = str(raw_event.get("home_team") or raw_event.get("home") or "").strip()
        provider_away = str(raw_event.get("away_team") or raw_event.get("away") or "").strip()
        provider_kickoff = _event_time(raw_event)
        if not provider_id or not provider_home or not provider_away or provider_kickoff is None:
            continue
        delta = (provider_kickoff - candidate_kickoff).total_seconds()
        if abs(delta) > KICKOFF_TOLERANCE_SECONDS:
            continue
        kickoff_only_ids.add(provider_id)
        home_hits = home_names & team_names(provider_home)
        away_hits = away_names & team_names(provider_away)
        if bool(home_hits) ^ bool(away_hits):
            partial_ids.add(provider_id)
        if home_hits and away_hits:
            exact.append({
                "id": provider_id,
                "sport_key": provider_sport,
                "home_team": provider_home,
                "away_team": provider_away,
                "kickoff_delta_seconds": round(delta, 3),
                "home_alias": sorted(home_hits)[0],
                "away_alias": sorted(away_hits)[0],
            })

    distinct_exact: dict[str, dict[str, Any]] = {}
    for event in exact:
        previous = distinct_exact.get(event["id"])
        if previous is not None and previous != event:
            return {
                "identity_status": "IDENTITY_AMBIGUOUS_FAIL_CLOSED",
                "provider_event_id": None,
                "provider_sport_key": None,
                "kickoff_delta_seconds": None,
                "identity_basis": "exact_or_existing_alias_only",
                "ambiguous_provider_event_ids": sorted({event["id"], previous["id"]}),
                "kickoff_only_event_count": len(kickoff_only_ids),
                "partial_team_event_count": len(partial_ids),
            }
        distinct_exact[event["id"]] = event
    if len(distinct_exact) > 1:
        return {
            "identity_status": "IDENTITY_AMBIGUOUS_FAIL_CLOSED",
            "provider_event_id": None,
            "provider_sport_key": None,
            "kickoff_delta_seconds": None,
            "identity_basis": "exact_or_existing_alias_only",
            "ambiguous_provider_event_ids": sorted(distinct_exact),
            "kickoff_only_event_count": len(kickoff_only_ids),
            "partial_team_event_count": len(partial_ids),
        }
    if len(distinct_exact) == 1:
        event = next(iter(distinct_exact.values()))
        return {
            "identity_status": "EXACT_MATCH",
            "provider_event_id": event["id"],
            "provider_sport_key": event["sport_key"],
            "provider_home_team": event["home_team"],
            "provider_away_team": event["away_team"],
            "kickoff_delta_seconds": event["kickoff_delta_seconds"],
            "identity_basis": "exact_or_existing_alias_only",
            "matched_home_alias": event["home_alias"],
            "matched_away_alias": event["away_alias"],
            "kickoff_only_event_count": len(kickoff_only_ids),
            "partial_team_event_count": len(partial_ids),
        }
    return {
        "identity_status": "NO_EVENT_MATCH",
        "provider_event_id": None,
        "provider_sport_key": None,
        "kickoff_delta_seconds": None,
        "identity_basis": "exact_or_existing_alias_only",
        "ambiguous_provider_event_ids": [],
        "kickoff_only_event_count": len(kickoff_only_ids),
        "partial_team_event_count": len(partial_ids),
    }


def _safe_number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _header_value(headers: Mapping[str, Any], name: str) -> str | None:
    lowered = name.casefold()
    for key, value in headers.items():
        if str(key).casefold() == lowered and value not in (None, ""):
            return str(value)
    return None


def _safe_usage_headers(headers: Mapping[str, Any], secret: str | None = None) -> dict[str, str]:
    output: dict[str, str] = {}
    for name in _USAGE_HEADERS:
        value = _header_value(headers, name)
        if value is None:
            continue
        if secret:
            value = value.replace(secret, "[REDACTED]")
        output[name] = value
    return output


def _nonnegative_int(value: Any) -> int | None:
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


class ProviderClient:
    """Minimal single-provider client with a one-credit worst-case probe guard."""

    def __init__(
        self,
        api_key: str,
        *,
        transport: Transport | None = None,
        max_credits: int = MAX_CREDITS,
    ) -> None:
        if not api_key:
            raise CredentialRequired("FOUNDER_SECRET_REQUIRED")
        self._api_key = api_key
        self._transport = transport or self._http_transport
        self.max_credits = int(max_credits)
        self.credits_reserved = 0
        self._observed_costs: list[int | None] = []
        self.usage_headers: list[dict[str, Any]] = []
        self.probe_paths: list[str] = []

    def _http_transport(self, path: str, params: Mapping[str, str]) -> tuple[Any, Mapping[str, Any]]:
        query = urlencode(dict(params))
        url = f"{API_HOST}{path}?{query}"
        request = Request(url, headers={"Accept": "application/json", "User-Agent": "FBOS-coverage-preflight/1"})
        try:
            with urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
                payload = json.loads(response.read().decode("utf-8"))
                headers = dict(response.headers.items())
        except HTTPError as error:
            raise ProviderRequestError(f"provider request failed: {path} (HTTP {error.code})") from None
        except (URLError, TimeoutError, OSError):
            raise ProviderRequestError(f"provider request failed: {path} (network error)") from None
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ProviderRequestError(f"provider returned invalid JSON: {path}") from None
        return payload, headers

    def _get(self, path: str, params: Mapping[str, str] | None = None) -> Any:
        request_params = {str(key): str(value) for key, value in (params or {}).items()}
        request_params["apiKey"] = self._api_key
        try:
            payload, headers = self._transport(path, request_params)
        except ProviderRequestError:
            raise
        except Exception as error:
            raise ProviderRequestError(f"provider transport failed: {path}") from error
        self.usage_headers.append({
            "path": path,
            "headers": _safe_usage_headers(headers, self._api_key),
        })
        return payload, headers

    def discover_sports(self) -> list[dict[str, Any]]:
        payload, _ = self._get("/v4/sports")
        if not isinstance(payload, list):
            raise ProviderRequestError("provider sports response was not a list")
        rows = []
        for row in payload:
            if not isinstance(row, Mapping):
                continue
            key = str(row.get("key") or "").strip()
            group = str(row.get("group") or "").strip().casefold()
            if key.startswith("soccer_") and (group == SOCCER_GROUP or not group):
                rows.append({
                    "key": key,
                    "title": str(row.get("title") or "").strip(),
                    "active": row.get("active") is True,
                })
        return sorted({row["key"]: row for row in rows}.values(), key=lambda row: row["key"])

    def discover_events(self, sport_key: str) -> list[dict[str, Any]]:
        safe_key = quote(sport_key, safe="")
        payload, _ = self._get(f"/v4/sports/{safe_key}/events")
        if not isinstance(payload, list):
            raise ProviderRequestError("provider events response was not a list")
        events = []
        for row in payload:
            if not isinstance(row, Mapping):
                continue
            event = dict(row)
            event.setdefault("sport_key", sport_key)
            events.append(event)
        return events

    def probe_event_odds(self, sport_key: str, event_id: str) -> tuple[Any, Mapping[str, Any]]:
        if self.credits_reserved + 1 > self.max_credits:
            raise PreflightError("provider correct_score probe credit cap reached before request")
        self.credits_reserved += 1
        safe_sport = quote(sport_key, safe="")
        safe_event = quote(event_id, safe="")
        path = f"/v4/sports/{safe_sport}/events/{safe_event}/odds"
        self.probe_paths.append(path)
        payload, headers = self._get(
            path,
            {"regions": PROBE_REGION, "markets": CORRECT_SCORE_MARKET, "oddsFormat": "decimal"},
        )
        last = _nonnegative_int(_header_value(headers, "x-requests-last"))
        self._observed_costs.append(last)
        if last is not None and last > 1:
            raise ProviderRequestError("one-region correct_score probe exceeded one-credit contract")
        return payload, headers

    def credit_usage(self) -> dict[str, Any]:
        complete = len(self._observed_costs) == len(self.probe_paths) and all(
            value is not None for value in self._observed_costs
        )
        credits_used = sum(value for value in self._observed_costs if value is not None) if complete else self.credits_reserved
        return {
            "cap": self.max_credits,
            "credits_used": credits_used,
            "credits_reserved_upper_bound": self.credits_reserved,
            "credits_used_basis": "x-requests-last headers" if complete else "one-credit-per-probe conservative upper bound",
            "probes_attempted": len(self.probe_paths),
            "usage_headers": self.usage_headers,
        }


def _price(value: Any) -> float | None:
    number = _safe_number(value)
    return number if number is not None and number > 0 else None


def probe_correct_score_payload(payload: Any) -> dict[str, Any]:
    """Summarize only correct-score shape; invalid labels never count as coverage."""

    bookmakers = payload.get("bookmakers") if isinstance(payload, Mapping) else []
    if not isinstance(bookmakers, list):
        bookmakers = []
    bookmaker_summaries: list[dict[str, Any]] = []
    market_count = 0
    outcome_count = 0
    parseable_outcome_count = 0
    last_updates: set[str] = set()
    for bookmaker in bookmakers:
        if not isinstance(bookmaker, Mapping):
            continue
        key = str(bookmaker.get("key") or bookmaker.get("title") or "unknown")
        bookmaker_last_update = str(bookmaker.get("last_update") or "").strip() or None
        if bookmaker_last_update:
            last_updates.add(bookmaker_last_update)
        markets = bookmaker.get("markets") or []
        if not isinstance(markets, list):
            markets = []
        correct_markets = [market for market in markets if isinstance(market, Mapping) and market.get("key") == CORRECT_SCORE_MARKET]
        if not correct_markets:
            continue
        for market in correct_markets:
            market_count += 1
            market_last_update = str(market.get("last_update") or "").strip() or None
            if market_last_update:
                last_updates.add(market_last_update)
            outcomes = market.get("outcomes") or []
            if not isinstance(outcomes, list):
                outcomes = []
            market_outcome_count = len([outcome for outcome in outcomes if isinstance(outcome, Mapping)])
            market_parseable_count = 0
            implied_sum = 0.0
            for outcome in outcomes:
                if not isinstance(outcome, Mapping):
                    continue
                score = parse_regulation_scoreline(outcome.get("name"))
                price = _price(outcome.get("price"))
                if score is None or price is None:
                    continue
                market_parseable_count += 1
                implied_sum += 1.0 / price
            outcome_count += market_outcome_count
            parseable_outcome_count += market_parseable_count
            bookmaker_summaries.append({
                "bookmaker_key": key,
                "outcome_count": market_outcome_count,
                "parseable_outcome_count": market_parseable_count,
                "implied_probability_sum": round(implied_sum, 9) if market_parseable_count else None,
                "overround": round(implied_sum - 1.0, 9) if market_parseable_count else None,
                "last_update": market_last_update or bookmaker_last_update,
            })
    return {
        "correct_score_returned": market_count > 0,
        "correct_score_covered": parseable_outcome_count > 0,
        "bookmaker_count": len([bookmaker for bookmaker in bookmakers if isinstance(bookmaker, Mapping)]),
        "correct_score_bookmaker_count": len({row["bookmaker_key"] for row in bookmaker_summaries}),
        "market_count": market_count,
        "outcome_count": outcome_count,
        "parseable_outcome_count": parseable_outcome_count,
        "regulation_time_scoreline_parseable": parseable_outcome_count > 0,
        "last_update_timestamps": sorted(last_updates),
        "bookmakers": bookmaker_summaries,
    }


def decide_preflight(
    *,
    candidate_count: int,
    exact_match_count: int,
    correct_score_covered_count: int,
    credits_used: int,
    kickoff_only_overlap_count: int,
    partial_team_overlap_count: int = 0,
    provider_query_ok: bool = True,
    rights_security_ok: bool = True,
    unresolved_identity_ambiguity_count: int = 0,
) -> str:
    if (
        not provider_query_ok
        or not rights_security_ok
        or credits_used > MAX_CREDITS
        or credits_used < 0
        or unresolved_identity_ambiguity_count < 0
    ):
        return "FAIL_CLOSED"
    if exact_match_count >= 10 and correct_score_covered_count >= 10:
        return "CORRECT_SCORE_BENCHMARK_PILOT_READY"
    if exact_match_count < 10 and (
        kickoff_only_overlap_count >= 10 or partial_team_overlap_count >= 10 or unresolved_identity_ambiguity_count > 0
    ):
        return "IDENTITY_MAPPING_NOT_READY"
    return "PROVIDER_COVERAGE_INSUFFICIENT"


def _public_error(error: Exception) -> str:
    text = str(error)
    if "apiKey" in text or "API_KEY" in text:
        return "provider request failed"
    return text


def _candidate_result(candidate: Mapping[str, Any], identity: Mapping[str, Any], sport_keys: list[str]) -> dict[str, Any]:
    result = {
        **dict(candidate),
        **dict(identity),
        "provider_sport_keys_considered": list(sport_keys),
        "correct_score": None,
        "probe_status": "NOT_PROBED",
    }
    return result


def _base_summary(cohort: Mapping[str, Any], *, current_ref: str, provider_query_ok: bool = True) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "milestone": MILESTONE,
        "audit_snapshot_at": cohort["snapshot_at"],
        "source": {
            "current_ref": current_ref,
            "universe_source": "existing canonical prediction-universe fixtures only",
            "universe_root": "data/prediction_universe",
            "provider": PROVIDER_NAME,
            "provider_site": PROVIDER_SITE,
            "api_host": API_HOST,
            "api_key_env": API_KEY_ENV,
        },
        "candidate_cohort": dict(cohort),
        "provider_discovery": {
            "sports_endpoint": "/v4/sports",
            "events_endpoint": "/v4/sports/{sport_key}/events",
            "soccer_sport_keys": [],
            "events_by_sport": {},
            "provider_event_count": 0,
            "kickoff_only_overlap_candidate_count": 0,
            "partial_team_overlap_candidate_count": 0,
        },
        "probes": {
            "market": CORRECT_SCORE_MARKET,
            "region": PROBE_REGION,
            "region_chosen_before_outcome_inspection": True,
            "exact_match_count": 0,
            "correct_score_covered_count": 0,
            "candidate_results": [],
            "errors": [],
        },
        "credits": {
            "cap": MAX_CREDITS,
            "credits_used": 0,
            "credits_reserved_upper_bound": 0,
            "credits_used_basis": "no paid probe requests",
            "probes_attempted": 0,
            "usage_headers": [],
        },
        "controls": dict(READ_ONLY_CONTROLS),
        "provider_query_ok": provider_query_ok,
        "final_decision": "FAIL_CLOSED",
    }


def run_preflight(
    *,
    universe_root: Path,
    current_ref: str,
    snapshot_at: Any,
    api_key: str,
    client: ProviderClient | None = None,
) -> dict[str, Any]:
    cohort = load_candidate_cohort(Path(universe_root), snapshot_at=snapshot_at)
    summary = _base_summary(cohort, current_ref=current_ref)
    if not api_key:
        raise CredentialRequired("FOUNDER_SECRET_REQUIRED")
    client = client or ProviderClient(api_key)
    candidate_results: list[dict[str, Any]] = []
    provider_errors: list[str] = []
    try:
        sports = client.discover_sports()
        sport_keys = [row["key"] for row in sports if row.get("active")]
        summary["provider_discovery"]["soccer_sport_keys"] = sport_keys
        summary["provider_discovery"]["active_soccer_sport_count"] = len(sport_keys)
        all_events: list[dict[str, Any]] = []
        by_sport: dict[str, int] = {}
        for sport_key in sport_keys:
            events = client.discover_events(sport_key)
            by_sport[sport_key] = len(events)
            all_events.extend(events)
        summary["provider_discovery"]["events_by_sport"] = by_sport
        summary["provider_discovery"]["provider_event_count"] = len(all_events)
    except ProviderRequestError as error:
        provider_errors.append(_public_error(error))
        all_events = []
        sport_keys = []

    for candidate in cohort["candidates"]:
        if provider_errors:
            identity = {
                "identity_status": "NO_PROVIDER_SPORT_MAPPING",
                "provider_event_id": None,
                "provider_sport_key": None,
                "kickoff_delta_seconds": None,
                "identity_basis": "provider_discovery_failed",
                "kickoff_only_event_count": 0,
                "partial_team_event_count": 0,
            }
        elif not sport_keys:
            identity = {
                "identity_status": "NO_PROVIDER_SPORT_MAPPING",
                "provider_event_id": None,
                "provider_sport_key": None,
                "kickoff_delta_seconds": None,
                "identity_basis": "no_active_soccer_sport_key_discovered",
                "kickoff_only_event_count": 0,
                "partial_team_event_count": 0,
            }
        else:
            identity = match_candidate_to_events(candidate, all_events)
        if identity["identity_status"] not in VALID_IDENTITY_STATUSES:
            raise PreflightError("provider identity status is outside the contract")
        result = _candidate_result(candidate, identity, sport_keys)
        candidate_results.append(result)

    exact_results = [row for row in candidate_results if row["identity_status"] == "EXACT_MATCH"]
    for result in exact_results:
        try:
            payload, _ = client.probe_event_odds(result["provider_sport_key"], result["provider_event_id"])
            result["correct_score"] = probe_correct_score_payload(payload)
            result["probe_status"] = "PROBED"
        except PreflightError as error:
            result["probe_status"] = "PROBE_ERROR"
            result["probe_error"] = _public_error(error)
            provider_errors.append(_public_error(error))
            if "credit cap" in str(error):
                break
    for result in candidate_results:
        if result["identity_status"] == "EXACT_MATCH" and result["probe_status"] == "NOT_PROBED":
            result["probe_status"] = "NOT_PROBED_CREDIT_CAP"

    kickoff_overlap = sum(row.get("kickoff_only_event_count", 0) > 0 for row in candidate_results)
    partial_overlap = sum(row.get("partial_team_event_count", 0) > 0 for row in candidate_results)
    exact_count = len(exact_results)
    covered_count = sum(
        bool((row.get("correct_score") or {}).get("correct_score_covered"))
        for row in candidate_results
    )
    identity_ambiguity_count = sum(
        row["identity_status"] == "IDENTITY_AMBIGUOUS_FAIL_CLOSED" for row in candidate_results
    )
    summary["provider_discovery"]["kickoff_only_overlap_candidate_count"] = kickoff_overlap
    summary["provider_discovery"]["partial_team_overlap_candidate_count"] = partial_overlap
    summary["probes"]["candidate_results"] = candidate_results
    summary["probes"]["exact_match_count"] = exact_count
    summary["probes"]["correct_score_covered_count"] = covered_count
    summary["probes"]["errors"] = sorted(set(provider_errors))
    summary["credits"] = client.credit_usage()
    summary["provider_query_ok"] = not provider_errors
    summary["decision_conditions"] = {
        "candidate_count": cohort["candidate_count"],
        "exact_match_count": exact_count,
        "correct_score_covered_count": covered_count,
        "credits_used": summary["credits"]["credits_used"],
        "credit_cap_respected": summary["credits"]["credits_used"] <= MAX_CREDITS,
        "kickoff_only_overlap_candidate_count": kickoff_overlap,
        "partial_team_overlap_candidate_count": partial_overlap,
        "unresolved_identity_ambiguity_count": identity_ambiguity_count,
        "provider_errors": sorted(set(provider_errors)),
    }
    summary["final_decision"] = decide_preflight(
        candidate_count=cohort["candidate_count"],
        exact_match_count=exact_count,
        correct_score_covered_count=covered_count,
        credits_used=summary["credits"]["credits_used"],
        kickoff_only_overlap_count=kickoff_overlap,
        partial_team_overlap_count=partial_overlap,
        provider_query_ok=not provider_errors,
        rights_security_ok=True,
        unresolved_identity_ambiguity_count=identity_ambiguity_count,
    )
    if summary["final_decision"] not in VALID_DECISIONS:
        raise PreflightError("provider decision is outside the contract")
    return summary


def _redact(value: Any, secret: str | None) -> Any:
    if isinstance(value, Mapping):
        return {key: _redact(item, secret) for key, item in value.items() if key not in {"_api_key", "request_secret"}}
    if isinstance(value, list):
        return [_redact(item, secret) for item in value]
    if isinstance(value, tuple):
        return [_redact(item, secret) for item in value]
    if isinstance(value, str) and secret:
        return value.replace(secret, "[REDACTED]")
    return value


def render_report(summary: Mapping[str, Any]) -> str:
    cohort = summary["candidate_cohort"]
    discovery = summary["provider_discovery"]
    probes = summary["probes"]
    credits = summary["credits"]
    lines = [
        f"# {MILESTONE}",
        "",
        f"Final decision: **{summary['final_decision']}**",
        "",
        "## Candidate cohort",
        "",
        f"- Snapshot: `{summary['audit_snapshot_at']}`; current ref: `{summary['source']['current_ref']}`.",
        f"- Future candidates: **{cohort['candidate_count']}** unique matches; raw future rows `{cohort['raw_future_candidate_rows']}`; deduplicated rows `{cohort['deduplicated_match_count']}`.",
        f"- Competition labels are copied only from existing canonical universe fields: `{json.dumps(cohort['competition_labels'], ensure_ascii=False)}`.",
        "- Past/due fixtures and historical outcomes are excluded; one canonical match id is one candidate.",
        "",
        "## Provider discovery",
        "",
        f"- Provider: `{summary['source']['provider']}`; API host: `{summary['source']['api_host']}`.",
        f"- Quota-free discovery endpoints: `{discovery['sports_endpoint']}` then `{discovery['events_endpoint']}`.",
        f"- Active soccer sport keys considered: `{json.dumps(discovery.get('soccer_sport_keys', []), ensure_ascii=False)}`.",
        f"- Provider events discovered: `{discovery.get('provider_event_count', 0)}`; kickoff-only overlap is diagnostic and never establishes identity: `{discovery.get('kickoff_only_overlap_candidate_count', 0)}` candidates.",
        "- Identity requires ordered exact names or an existing explicit team alias plus normalized kickoff; no fuzzy similarity, LLM guessing, or manual assignment.",
        "",
        "## Correct-score probe",
        "",
        f"- Market: `{probes['market']}`; single region selected before inspecting outcomes: `{probes['region']}`.",
        f"- Exact identity matches: `{probes['exact_match_count']}`; parseable regulation-time correct-score coverage: `{probes['correct_score_covered_count']}`.",
        f"- Credits: `{json.dumps(credits, ensure_ascii=False, sort_keys=True)}`.",
        "- No de-vigging, tuning, ensemble, odds publication, or outcome/result evaluation is performed.",
        "",
        "## Candidate-by-candidate evidence",
        "",
        "The JSON artifact contains the complete candidate rows. `EXACT_MATCH` is the only status eligible for an event-odds probe; ambiguous and non-exact rows are never counted as covered.",
        "",
        "| FBOS match key | kickoff | competition | provider sport | provider event | identity | kickoff delta s | correct_score | parseable outcomes | probe |",
        "| --- | --- | --- | --- | --- | --- | ---: | --- | ---: | --- |",
    ]
    for row in probes["candidate_results"]:
        correct = row.get("correct_score") or {}
        lines.append(
            f"| {row['match_key']} | {row['kickoff']} | {row['competition']} | {row.get('provider_sport_key') or ''} | {row.get('provider_event_id') or ''} | {row['identity_status']} | {row.get('kickoff_delta_seconds') if row.get('kickoff_delta_seconds') is not None else ''} | {correct.get('correct_score_returned') if correct else ''} | {correct.get('parseable_outcome_count') if correct else ''} | {row.get('probe_status')} |"
        )
    lines.extend([
        "",
        "## Decision and safety",
        "",
        f"- Decision conditions: `{json.dumps(summary.get('decision_conditions', {}), ensure_ascii=False, sort_keys=True)}`",
        f"- Controls: `{json.dumps(summary['controls'], ensure_ascii=False, sort_keys=True)}`",
        "- Existing canonical fixture data only; no result fetch/backfill and no historical benchmark data.",
        "- The API key is secret-injected, never serialized, printed, committed, or uploaded.",
        "- No Champion, Challenger C, model, frozen prediction, authoritative result, serving, promotion, or provider-feed publication change.",
        "",
        "STOP: research-only coverage evidence; DO NOT MERGE; independent acceptance required.",
        "",
    ])
    return "\n".join(lines)


def write_artifacts(summary: Mapping[str, Any], output_dir: Path, *, secret: str | None = None) -> dict[str, Path]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    public_summary = _redact(summary, secret)
    summary_path = output / "summary.json"
    report_path = output / "report.md"
    summary_path.write_text(json.dumps(public_summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    report_path.write_text(render_report(public_summary), encoding="utf-8")
    return {"summary": summary_path, "report": report_path}


def _failure_summary(*, universe_root: Path, current_ref: str, snapshot_at: Any, error: Exception) -> dict[str, Any]:
    cohort = load_candidate_cohort(Path(universe_root), snapshot_at=snapshot_at)
    summary = _base_summary(cohort, current_ref=current_ref, provider_query_ok=False)
    summary["provider_discovery"]["errors"] = [_public_error(error)]
    summary["final_decision"] = "FAIL_CLOSED"
    summary["decision_conditions"] = {"provider_errors": [_public_error(error)]}
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--universe-root", type=Path, required=True)
    parser.add_argument("--current-ref", required=True)
    parser.add_argument("--snapshot-at")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--api-key-env", default=API_KEY_ENV)
    args = parser.parse_args(argv)
    api_key = os.environ.get(args.api_key_env, "")
    if not api_key:
        print("FOUNDER_SECRET_REQUIRED")
        return 2
    snapshot_at = args.snapshot_at or datetime.now(timezone.utc).isoformat()
    try:
        summary = run_preflight(
            universe_root=args.universe_root,
            current_ref=args.current_ref,
            snapshot_at=snapshot_at,
            api_key=api_key,
        )
    except CredentialRequired:
        print("FOUNDER_SECRET_REQUIRED")
        return 2
    except PreflightError as error:
        summary = _failure_summary(
            universe_root=args.universe_root,
            current_ref=args.current_ref,
            snapshot_at=snapshot_at,
            error=error,
        )
    paths = write_artifacts(summary, args.output_dir, secret=api_key)
    print(json.dumps({
        "milestone": MILESTONE,
        "candidate_count": summary["candidate_cohort"]["candidate_count"],
        "exact_match_count": summary["probes"]["exact_match_count"],
        "correct_score_covered_count": summary["probes"]["correct_score_covered_count"],
        "credits_used": summary["credits"]["credits_used"],
        "final_decision": summary["final_decision"],
        "summary": str(paths["summary"]),
        "report": str(paths["report"]),
    }, ensure_ascii=False, sort_keys=True))
    return 0 if summary["final_decision"] != "FAIL_CLOSED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
