#!/usr/bin/env python3
"""Structured, same-ID Nowscore prematch evidence.

The module is the only page-facing adapter for the Issue #272 evidence
contract.  It deliberately keeps response bodies in memory only long enough
to parse them, then exposes structured facts, hashes, timestamps, and parser
health.  Identity is still owned by ``prediction_universe`` and is checked by
the existing trusted Nowscore verifier; this module never resolves a match
from aliases or from another provider.
"""

from __future__ import annotations

import argparse
import hashlib
import html as html_lib
import json
import re
import sys
import urllib.error
import urllib.request
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Callable, Mapping
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_ROOT = ROOT / "scripts"
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))

# Keep a stable import name for the adapter module when this file runs as a script.
sys.modules.setdefault("nowscore_prematch_evidence", sys.modules[__name__])

try:  # direct script imports
    from nowscore_markets import (
        ANALYSIS_DATA_URL,
        COACH_URL,
        MARKET_URL,
        PANLU_URL,
        REFEREE_URL,
        USER_AGENT,
        _page_provider_id_details,
        _state_memory_target_identity,
        _trusted_jc_page_verification,
        _decode as _market_decode,
        parse_analysis_data,
        parse_coach_page,
        parse_panlu_page,
        parse_referee_page,
        parse_three_in_one,
    )
except ImportError:  # package imports used by focused tests
    from scripts.nowscore_markets import (
        ANALYSIS_DATA_URL,
        COACH_URL,
        MARKET_URL,
        PANLU_URL,
        REFEREE_URL,
        USER_AGENT,
        _page_provider_id_details,
        _state_memory_target_identity,
        _trusted_jc_page_verification,
        _decode as _market_decode,
        parse_analysis_data,
        parse_coach_page,
        parse_panlu_page,
        parse_referee_page,
        parse_three_in_one,
    )

try:  # direct script imports
    from prediction_universe import trusted_nowscore_jc_fixture
except ImportError:  # package imports used by focused tests
    from scripts.prediction_universe import trusted_nowscore_jc_fixture


SHANGHAI = ZoneInfo("Asia/Shanghai")
CONTRACT_VERSION = "nowscore_prematch_evidence.v1"
PARSER_HEALTH_VERSION = "nowscore_parser_health.v1"
PARSER_VERSION = "nowscore_thin_adapter.v1"

FIELD_NAMES = (
    "competition_standings_stage",
    "standings_context",
    "recent_form",
    "h2h",
    "future_schedule_rest",
    "injuries",
    "suspensions",
    "availability_summary",
    "lineup_state",
    "coach",
    "referee",
    "panlu",
    "technical_stats",
    "market_context",
)
FIELD_SET = frozenset(FIELD_NAMES)
FIELD_SURFACES = {
    "competition_standings_stage": ("market_context", "analysis_page"),
    "standings_context": ("analysis_page",),
    "recent_form": ("analysis_data", "analysis_page"),
    "h2h": ("analysis_page",),
    "future_schedule_rest": ("analysis_page",),
    "injuries": ("analysis_page", "time_page"),
    "suspensions": ("analysis_page", "time_page"),
    "availability_summary": ("analysis_page",),
    "lineup_state": ("analysis_page", "time_page"),
    "coach": ("coach",),
    "referee": ("referee",),
    "panlu": ("panlu",),
    "technical_stats": ("time_page",),
    "market_context": ("market_context",),
}
SURFACES = (
    "market_context",
    "analysis_data",
    "analysis_page",
    "time_page",
    "coach",
    "referee",
    "panlu",
)
STATE_NAMES = (
    "PRESENT",
    "SECTION_PRESENT_EMPTY",
    "ABSENT",
    "ACCESS_GATED",
    "PARSE_UNCERTAIN",
    "CONFLICT",
)
STATE_SET = frozenset(STATE_NAMES)

ANALYSIS_PAGE_URL = "https://m.nowscore.com/Analy/Analysis/{match_id}.htm"
TIME_PAGE_URL = "https://m.nowscore.com/Analy/ShiJian/{match_id}.htm"


def nowscore_source_urls(match_id: int) -> dict[str, str]:
    """Return the bounded public surfaces used by the evidence adapter."""

    numeric_id = int(match_id)
    return {
        "market_context": MARKET_URL.format(match_id=numeric_id),
        "analysis_data": ANALYSIS_DATA_URL.format(match_id=numeric_id),
        "analysis_page": ANALYSIS_PAGE_URL.format(match_id=numeric_id),
        "time_page": TIME_PAGE_URL.format(match_id=numeric_id),
        "coach": COACH_URL.format(match_id=numeric_id),
        "referee": REFEREE_URL.format(match_id=numeric_id),
        "panlu": PANLU_URL.format(match_id=numeric_id),
    }


def _present(value: Any) -> bool:
    return value is not None and not (isinstance(value, str) and not value.strip())


def _safe_text(value: Any, limit: int = 160) -> str:
    text = re.sub(r"\s+", " ", html_lib.unescape(str(value or ""))).strip()
    return text[:limit]


def _parse_timestamp(value: Any, *, local_default: bool = True) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value or "").strip()
        if not text:
            return None
        text = text.replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            parsed = None
            for fmt in (
                "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%d %H:%M",
                "%Y/%m/%d %H:%M:%S",
                "%Y/%m/%d %H:%M",
                "%Y-%m-%dT%H:%M:%S",
                "%Y-%m-%dT%H:%M",
            ):
                try:
                    parsed = datetime.strptime(text, fmt)
                    break
                except ValueError:
                    continue
            if parsed is None:
                return None
    if parsed.tzinfo is None and local_default:
        parsed = parsed.replace(tzinfo=SHANGHAI)
    return parsed


def _timestamp(value: Any) -> str | None:
    parsed = _parse_timestamp(value)
    return parsed.isoformat(timespec="seconds") if parsed else None


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _decode(raw: bytes | str) -> str:
    if isinstance(raw, str):
        return raw
    try:
        return _market_decode(raw)
    except Exception:
        for encoding in ("utf-8", "gb18030"):
            try:
                return raw.decode(encoding)
            except UnicodeDecodeError:
                continue
        return raw.decode("utf-8", errors="replace")


def _content_hash(body: str | bytes | None) -> str | None:
    if body is None:
        return None
    raw = body.encode("utf-8") if isinstance(body, str) else body
    return hashlib.sha256(raw).hexdigest()


def _looks_access_gated(text: str) -> bool:
    lowered = (text or "").casefold()
    return any(
        marker in lowered
        for marker in (
            "access denied",
            "verify you are human",
            "captcha",
            "login required",
            "验证码",
            "请登录",
        )
    )


def _source_update(headers: Mapping[str, Any] | None) -> tuple[str | None, str | None]:
    values = headers or {}
    raw = values.get("Last-Modified") or values.get("last-modified")
    if not raw:
        return None, None
    try:
        parsed = parsedate_to_datetime(str(raw))
    except (TypeError, ValueError, OverflowError):
        return None, None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.isoformat(timespec="seconds"), "http_last_modified"


@dataclass
class SurfacePayload:
    """Transient parse input plus public observation metadata.

    ``body`` is intentionally not serialised anywhere.  A test client may
    construct this object directly; the production client creates it from a
    single unauthenticated public request.
    """

    surface: str
    url: str
    body: str | None
    observation: dict[str, Any]


class NowscorePublicClient:
    """Small no-cache, no-auth public HTTP client with a request budget."""

    def __init__(
        self,
        *,
        opener: Callable[..., Any] | None = None,
        timeout: int = 30,
        max_requests: int = 16,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.opener = opener or urllib.request.urlopen
        self.timeout = timeout
        self.max_requests = max(1, int(max_requests))
        self.clock = clock or _now_utc
        self.request_count = 0

    def fetch(self, surface: str, url: str) -> SurfacePayload:
        if self.request_count >= self.max_requests:
            return SurfacePayload(
                surface,
                url,
                None,
                _observation(
                    surface,
                    url,
                    observed_at=self.clock(),
                    error_code="REQUEST_BUDGET_EXCEEDED",
                ),
            )
        self.request_count += 1
        started = self.clock()
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
        try:
            with self.opener(request, timeout=self.timeout) as response:
                raw = response.read()
                status = int(response.getcode() or 200)
                headers = getattr(response, "headers", {})
                finished = self.clock()
                body = _decode(raw)
                source_update_at, source_update_basis = _source_update(headers)
                if _looks_access_gated(body):
                    return SurfacePayload(
                        surface,
                        url,
                        None,
                        _observation(
                            surface,
                            url,
                            observed_at=finished,
                            started_at=started,
                            http_status=status,
                            content_sha256=_content_hash(raw),
                            content_length=len(raw),
                            source_update_at=source_update_at,
                            source_update_basis=source_update_basis,
                            error_code="ACCESS_GATED",
                        ),
                    )
                return SurfacePayload(
                    surface,
                    url,
                    body,
                    _observation(
                        surface,
                        url,
                        observed_at=finished,
                        started_at=started,
                        http_status=status,
                        content_sha256=_content_hash(raw),
                        content_length=len(raw),
                        source_update_at=source_update_at,
                        source_update_basis=source_update_basis,
                    ),
                )
        except urllib.error.HTTPError as error:
            # The error body is deliberately not read or persisted.  Status
            # alone is sufficient to represent an access-gated surface.
            code = "ACCESS_GATED" if int(error.code) in (401, 403, 429) else "HTTP_ERROR"
            return SurfacePayload(
                surface,
                url,
                None,
                _observation(
                    surface,
                    url,
                    observed_at=self.clock(),
                    started_at=started,
                    http_status=int(error.code),
                    error_code=code,
                    error_detail=type(error).__name__,
                ),
            )
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            return SurfacePayload(
                surface,
                url,
                None,
                _observation(
                    surface,
                    url,
                    observed_at=self.clock(),
                    started_at=started,
                    error_code="NETWORK_ERROR",
                    error_detail=type(error).__name__,
                ),
            )


def _observation(
    surface: str,
    url: str,
    *,
    observed_at: datetime | str | None,
    started_at: datetime | str | None = None,
    http_status: int | None = None,
    content_sha256: str | None = None,
    content_length: int | None = None,
    source_update_at: str | None = None,
    source_update_basis: str | None = None,
    error_code: str | None = None,
    error_detail: str | None = None,
) -> dict[str, Any]:
    return {
        "surface": surface,
        "url": url,
        "observed_at": _timestamp(observed_at),
        "request_started_at": _timestamp(started_at),
        "source_update_at": source_update_at,
        "source_update_basis": source_update_basis,
        "http_status": http_status,
        "content_sha256": content_sha256,
        "content_length": content_length,
        "error_code": error_code,
        "error_detail": _safe_text(error_detail, 80) if error_detail else None,
    }


def _normalise_client_payload(value: Any, surface: str, url: str) -> SurfacePayload:
    if isinstance(value, SurfacePayload):
        return value
    if isinstance(value, Mapping):
        body = value.get("body")
        observation = value.get("observation")
        if not isinstance(observation, dict):
            observation = _observation(
                surface,
                url,
                observed_at=_now_utc(),
                http_status=200 if body is not None else None,
                content_sha256=_content_hash(body),
                content_length=len(body.encode("utf-8")) if isinstance(body, str) else None,
            )
        return SurfacePayload(surface, url, _decode(body) if body is not None else None, observation)
    if isinstance(value, tuple) and len(value) == 2:
        first, second = value
        if isinstance(first, (bytes, str)) or first is None:
            body, observation = first, second
        else:
            observation, body = first, second
        if not isinstance(observation, dict):
            observation = _observation(
                surface,
                url,
                observed_at=_now_utc(),
                http_status=200 if body is not None else None,
                content_sha256=_content_hash(body),
                content_length=len(body.encode("utf-8")) if isinstance(body, str) else None,
            )
        return SurfacePayload(surface, url, _decode(body) if body is not None else None, observation)
    if isinstance(value, (bytes, str)):
        body = _decode(value)
        return SurfacePayload(
            surface,
            url,
            body,
            _observation(
                surface,
                url,
                observed_at=_now_utc(),
                http_status=200,
                content_sha256=_content_hash(body),
                content_length=len(body.encode("utf-8")),
            ),
        )
    return SurfacePayload(
        surface,
        url,
        None,
        _observation(
            surface,
            url,
            observed_at=_now_utc(),
            error_code="INVALID_CLIENT_PAYLOAD",
        ),
    )


from nowscore_prematch_adapters import _adapter, _markup_adapter


def _fixture_name(fixture: Mapping[str, Any] | None, side: str) -> str:
    if not isinstance(fixture, Mapping):
        return ""
    keys = ("homeTeam", "home_team", "home") if side == "home" else ("awayTeam", "away_team", "away")
    for key in keys:
        if _present(fixture.get(key)):
            return _safe_text(fixture[key], 160)
    return ""


def _fixture_kickoff(fixture: Mapping[str, Any] | None) -> str:
    if not isinstance(fixture, Mapping):
        return ""
    for key in ("kickoff", "kickoff_local"):
        if _present(fixture.get(key)):
            return str(fixture[key]).strip()
    match_date = str(fixture.get("matchDate") or fixture.get("match_date") or "")[:10]
    match_time = str(fixture.get("matchTime") or fixture.get("match_time") or "")[:8]
    if len(match_time) == 5:
        match_time += ":00"
    return f"{match_date}T{match_time}+08:00" if match_date and match_time else ""


def _fixture_team_id(fixture: Mapping[str, Any] | None, side: str) -> int | None:
    if not isinstance(fixture, Mapping):
        return None
    keys = (
        ("home_team_id", "homeTeamId", "nowscore_home_team_id", "nowscoreHomeTeamId")
        if side == "home"
        else ("away_team_id", "awayTeamId", "nowscore_away_team_id", "nowscoreAwayTeamId")
    )
    for key in keys:
        value = fixture.get(key)
        try:
            parsed = int(str(value).strip())
        except (TypeError, ValueError):
            continue
        if parsed > 0:
            return parsed
    return None


def _analysis_page_target(
    target: Mapping[str, Any],
    identity: Mapping[str, Any],
    fixture: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Pass only verified identity/context into field-specific page parsers."""

    enriched = dict(target)
    enriched["identity_home"] = _safe_text(identity.get("home_team") or target.get("home"), 160)
    enriched["identity_away"] = _safe_text(identity.get("away_team") or target.get("away"), 160)
    enriched["identity_home_id"] = identity.get("home_team_id") or _fixture_team_id(fixture, "home")
    enriched["identity_away_id"] = identity.get("away_team_id") or _fixture_team_id(fixture, "away")
    for key in ("competition", "league", "competition_name", "league_name"):
        if _present((fixture or {}).get(key)):
            enriched["competition"] = _safe_text((fixture or {}).get(key), 120)
            break
    for key in ("season", "season_name"):
        if _present((fixture or {}).get(key)):
            enriched["season"] = _safe_text((fixture or {}).get(key), 80)
            break
    enriched["identity_source"] = "verified_market_context"
    return enriched


def _numeric_id(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _max_timestamp(values: list[Any]) -> str | None:
    parsed: list[tuple[datetime, str]] = []
    for value in values:
        timestamp = _timestamp(value)
        dt = _parse_timestamp(timestamp)
        if timestamp and dt:
            parsed.append((dt, timestamp))
    return max(parsed, key=lambda item: item[0])[1] if parsed else None


def _field_temporal_state(item: dict[str, Any], kickoff: Any) -> dict[str, Any]:
    value = dict(item)
    observed = _parse_timestamp(item.get("observed_at"))
    source_update = _parse_timestamp(item.get("source_update_at"))
    cutoff = _parse_timestamp(kickoff)
    eligible: bool | None = None
    if cutoff and (observed or source_update):
        eligible = bool(observed and observed < cutoff and (source_update is None or source_update < cutoff))
    value["prematch_eligible"] = eligible
    if eligible is False and value.get("state") not in {"ABSENT", "ACCESS_GATED"}:
        value["state"] = "CONFLICT"
        value["value"] = None
        value["reason_code"] = "POST_KICKOFF_OR_SOURCE_UPDATE"
    return value


def _json_equal(left: Any, right: Any) -> bool:
    try:
        return json.dumps(left, ensure_ascii=False, sort_keys=True, separators=(",", ":")) == json.dumps(right, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError):
        return left == right


def _merge_field_entries(field: str, entries: list[dict[str, Any]]) -> dict[str, Any]:
    if not entries:
        return {
            "state": "ABSENT",
            "value": None,
            "reason_code": "NO_SOURCE_SURFACE_OBSERVED",
            "record_count": 0,
            "semantic_state": None,
            "surface": None,
            "source_surfaces": [],
            "surface_states": {},
            "observed_at": None,
            "source_update_at": None,
            "prematch_eligible": None,
        }
    states = [str(item.get("state") or "PARSE_UNCERTAIN") for item in entries]
    surface_states = {
        str(item.get("surface") or "unknown"): state
        for item, state in zip(entries, states)
    }
    present_values = [item.get("value") for item in entries if item.get("state") == "PRESENT"]
    conflict = "CONFLICT" in states
    if len(present_values) > 1 and any(not _json_equal(present_values[0], value) for value in present_values[1:]):
        conflict = True
    if "PRESENT" in states and any(state == "SECTION_PRESENT_EMPTY" for state in states):
        conflict = True
    if conflict:
        state = "CONFLICT"
        value = None
        reason = "MULTI_SURFACE_CONFLICT"
        selected = next((item for item in entries if item.get("state") == "CONFLICT"), entries[0])
    else:
        priority = {"PRESENT": 5, "SECTION_PRESENT_EMPTY": 4, "PARSE_UNCERTAIN": 3, "ACCESS_GATED": 2, "ABSENT": 1}
        selected = max(entries, key=lambda item: priority.get(str(item.get("state")), 0))
        state = str(selected.get("state") or "PARSE_UNCERTAIN")
        value = selected.get("value") if state == "PRESENT" else None
        reason = selected.get("reason_code") or "SOURCE_STATE"
    observed_at = _max_timestamp([item.get("observed_at") for item in entries])
    source_update_at = _max_timestamp([item.get("source_update_at") for item in entries])
    eligibilities = [item.get("prematch_eligible") for item in entries if item.get("prematch_eligible") is not None]
    eligible: bool | None
    if eligibilities and all(value is True for value in eligibilities):
        eligible = True
    elif any(value is False for value in eligibilities):
        eligible = False
    else:
        eligible = None
    return {
        "state": state,
        "value": value,
        "reason_code": reason,
        "record_count": max(int(item.get("record_count") or 0) for item in entries),
        "semantic_state": selected.get("semantic_state"),
        "surface": selected.get("surface"),
        "source_surfaces": list(dict.fromkeys(str(item.get("surface")) for item in entries if item.get("surface"))),
        "surface_states": surface_states,
        "observed_at": observed_at,
        "source_update_at": source_update_at,
        "prematch_eligible": eligible,
    }


def _force_identity_conflict(fields: dict[str, dict[str, Any]], reasons: list[str]) -> None:
    reason = "IDENTITY_NOT_VERIFIED" if not reasons else "IDENTITY_NOT_VERIFIED:" + ",".join(dict.fromkeys(reasons))
    for item in fields.values():
        if item.get("state") in {"PRESENT", "SECTION_PRESENT_EMPTY", "PARSE_UNCERTAIN"}:
            item["state"] = "CONFLICT"
            item["value"] = None
            item["reason_code"] = reason
            item["prematch_eligible"] = False


def _coverage(fields: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    state_counts = Counter(str(item.get("state") or "PARSE_UNCERTAIN") for item in fields.values())
    result: dict[str, Any] = {
        "field_count": len(FIELD_NAMES),
        "present_count": sum(fields.get(field, {}).get("state") == "PRESENT" for field in FIELD_NAMES),
        "field_state_counts": {state: int(state_counts.get(state, 0)) for state in STATE_NAMES},
        "fields": {},
    }
    result["present_fraction"] = round(result["present_count"] / len(FIELD_NAMES), 4) if FIELD_NAMES else 0.0
    for field in FIELD_NAMES:
        item = fields.get(field) or {}
        result["fields"][field] = {
            "state": item.get("state"),
            "record_count": int(item.get("record_count") or 0),
            "source_surfaces": list(item.get("source_surfaces") or []),
            "prematch_eligible": item.get("prematch_eligible"),
        }
    return result


def _parser_health(health: list[dict[str, Any]], *, identity_trusted: bool) -> dict[str, Any]:
    statuses = [str(item.get("status") or "UNAVAILABLE") for item in health]
    if not identity_trusted:
        overall = "BLOCKED"
    elif "DRIFT_SUSPECTED" in statuses:
        overall = "DRIFT_SUSPECTED"
    elif any(status in {"ACCESS_GATED", "UNAVAILABLE"} for status in statuses):
        overall = "DEGRADED"
    else:
        overall = "HEALTHY"
    drift_signals = []
    for item in health:
        for reason in item.get("drift_reasons") or []:
            drift_signals.append({"surface": item.get("surface"), "reason": reason})
    return {
        "contract_version": PARSER_HEALTH_VERSION,
        "overall_status": overall,
        "surface_health": health,
        "drift_signal_count": len(drift_signals),
        "drift_signals": drift_signals,
    }


def _target_fixture(
    match_id: int,
    home: str,
    away: str,
    kickoff: Any,
    identity: Mapping[str, Any],
    fixture: Mapping[str, Any] | None,
) -> dict[str, Any]:
    return {
        "provider_match_id": match_id,
        "source_fixture_id": match_id,
        "home_team": _safe_text(identity.get("home_team") or home),
        "away_team": _safe_text(identity.get("away_team") or away),
        "home_team_id": identity.get("home_team_id") or _fixture_team_id(fixture, "home"),
        "away_team_id": identity.get("away_team_id") or _fixture_team_id(fixture, "away"),
        "kickoff_at": _timestamp(identity.get("kickoff_local") or kickoff),
        "raw_competition_label": _safe_text((fixture or {}).get("competition") or (fixture or {}).get("league"), 120),
        "source_record_ref": MARKET_URL.format(match_id=match_id),
    }


def _build_evidence(
    *,
    match_id: int,
    home: str,
    away: str,
    kickoff: Any,
    fixture: Mapping[str, Any] | None,
    identity: Mapping[str, Any],
    provenance: Mapping[str, Any],
    fields: Mapping[str, Mapping[str, Any]],
    observations: list[dict[str, Any]],
    health: list[dict[str, Any]],
) -> dict[str, Any]:
    observed_at = _max_timestamp([item.get("observed_at") for item in observations])
    source_updates = [item.get("source_update_at") for item in observations if item.get("source_update_at")]
    source_update_at = _max_timestamp(source_updates)
    source_update_bases = list(dict.fromkeys(
        str(item.get("source_update_basis"))
        for item in observations
        if item.get("source_update_at") and item.get("source_update_basis")
    ))
    market_observation = next((item for item in observations if item.get("surface") == "market_context"), None)
    cutoff = _parse_timestamp(kickoff)
    market_time = _parse_timestamp((market_observation or {}).get("observed_at"))
    market_field = fields.get("market_context") or {}
    prematch_verified = bool(
        provenance.get("trusted")
        and market_time
        and cutoff
        and market_time < cutoff
        and market_field.get("prematch_eligible") is not False
    )
    normalized_fields = {
        field: dict(fields.get(field) or _merge_field_entries(field, []))
        for field in FIELD_NAMES
    }
    return {
        "contract_version": CONTRACT_VERSION,
        "source": {
            "provider": "nowscore",
            "role": "same_id_prematch_evidence",
            "provider_match_id": match_id,
            "observed_at": observed_at,
            "source_update_at": source_update_at,
            "source_update_basis": source_update_bases[0] if len(source_update_bases) == 1 else ("multiple" if source_update_bases else None),
            "prematch_verified": prematch_verified,
            "prematch_status": "VERIFIED" if prematch_verified else ("UNVERIFIED" if cutoff else "UNKNOWN"),
            "source_references": [item.get("url") for item in observations if item.get("url")],
            "trusted_identity_source": provenance.get("source"),
        },
        "target_fixture": _target_fixture(match_id, home, away, kickoff, identity, fixture),
        "fields": normalized_fields,
        "observations": observations,
        "coverage": _coverage(normalized_fields),
        "parser_health": _parser_health(health, identity_trusted=bool(provenance.get("trusted"))),
        "rights": {
            "raw_bodies_persisted": False,
            "raw_html_js_persisted": False,
            "player_name_lists_persisted": False,
            "auth_or_bypass_used": False,
        },
    }


def _error_observation(surface: str, url: str, error_code: str, detail: str | None = None) -> SurfacePayload:
    return SurfacePayload(
        surface,
        url,
        None,
        _observation(surface, url, observed_at=_now_utc(), error_code=error_code, error_detail=detail),
    )


def _fetch_payload(client: Any, surface: str, url: str) -> SurfacePayload:
    try:
        return _normalise_client_payload(client.fetch(surface, url), surface, url)
    except Exception as error:
        return _error_observation(surface, url, "CLIENT_EXCEPTION", type(error).__name__)


def _invalid_identity_result(
    *,
    match_id: int,
    home: str,
    away: str,
    kickoff: Any,
    fixture: Mapping[str, Any] | None,
    provenance: Mapping[str, Any],
    identity_verification: Mapping[str, Any] | None = None,
    status: str = "IDENTITY_MISMATCH",
    error: str | None = None,
) -> dict[str, Any]:
    fields = {field: _merge_field_entries(field, []) for field in FIELD_NAMES}
    evidence = _build_evidence(
        match_id=match_id,
        home=home,
        away=away,
        kickoff=kickoff,
        fixture=fixture,
        identity={},
        provenance=provenance,
        fields=fields,
        observations=[],
        health=[],
    )
    return {
        "source": "nowscore_prematch_evidence",
        "status": status,
        "fetched_at": _now_utc().isoformat(timespec="seconds"),
        "nowscore_id": match_id,
        "target": {"home": home, "away": away, "kickoff": str(kickoff or "")},
        "resolution": {"status": "EXPLICIT_ID", "nowscore_id": match_id},
        "identity_verification": dict(identity_verification or {"trusted": False, "reasons": list(provenance.get("reasons") or [])}),
        "trusted_jc_provenance": dict(provenance),
        "prematch_evidence": evidence,
        "error": error,
        "quality": {"home_away_kickoff_verified": False, "recent_form_complete": False},
        "source_urls": nowscore_source_urls(match_id),
    }


def fetch_nowscore_prematch_evidence(
    home: str,
    away: str,
    kickoff: object,
    explicit_id: int | None = None,
    no_cache: bool = False,
    *,
    fixture: Mapping[str, object] | None = None,
    client: Any | None = None,
) -> dict[str, Any]:
    """Fetch one verified same-ID Nowscore evidence bundle.

    ``no_cache`` remains in the compatibility signature for the existing
    runner.  This adapter never reads or writes a cache, regardless of its
    value.  The trusted JC fixture is mandatory so an explicit number cannot
    become a new identity path.
    """

    del no_cache
    match_id = _numeric_id(explicit_id)
    if match_id is None:
        return _invalid_identity_result(
            match_id=0,
            home=home,
            away=away,
            kickoff=kickoff,
            fixture=fixture,
            provenance={"trusted": False, "source": "nowscore_public_jc_sales", "reasons": ["INVALID_PROVIDER_ID"]},
            status="INVALID_PROVIDER_ID",
            error="explicit_id must be a positive integer",
        )
    provenance = trusted_nowscore_jc_fixture(fixture, match_id)
    if not provenance.get("trusted"):
        return _invalid_identity_result(
            match_id=match_id,
            home=home,
            away=away,
            kickoff=kickoff,
            fixture=fixture,
            provenance=provenance,
        )

    target = {"home": str(home or ""), "away": str(away or ""), "kickoff": kickoff}
    urls = nowscore_source_urls(match_id)
    http_client = client or NowscorePublicClient()
    market_payload = _fetch_payload(http_client, "market_context", urls["market_context"])
    market_result = _adapter("market_context", market_payload, target)
    identity = market_result.get("identity") if isinstance(market_result.get("identity"), dict) else {}
    identity_verification = _trusted_jc_page_verification(target, identity, fixture or {}, match_id)
    observations = [dict(market_payload.observation)]
    health = [market_result.get("health") or {}]
    all_entries: dict[str, list[dict[str, Any]]] = {field: [] for field in FIELD_NAMES}
    analysis_result: dict[str, Any] = {}
    coach_result: dict[str, Any] = {}
    referee_result: dict[str, Any] = {}
    panlu_result: dict[str, Any] = {}
    for field, item in (market_result.get("fields") or {}).items():
        if field in FIELD_SET:
            all_entries[field].append(_field_temporal_state(item, kickoff))
    if not identity_verification.get("trusted"):
        _force_identity_conflict(market_result.get("fields") or {}, list(identity_verification.get("reasons") or []))
        all_entries = {field: [] for field in FIELD_NAMES}
        for field, item in (market_result.get("fields") or {}).items():
            if field in FIELD_SET:
                all_entries[field].append(_field_temporal_state(item, kickoff))
        merged = {field: _merge_field_entries(field, entries) for field, entries in all_entries.items()}
        evidence = _build_evidence(
            match_id=match_id,
            home=home,
            away=away,
            kickoff=kickoff,
            fixture=fixture,
            identity=identity,
            provenance=provenance,
            fields=merged,
            observations=observations,
            health=health,
        )
        return {
            "source": "nowscore_prematch_evidence",
            "status": "IDENTITY_MISMATCH",
            "fetched_at": evidence["source"].get("observed_at") or _now_utc().isoformat(timespec="seconds"),
            "nowscore_id": match_id,
            "target": target,
            "page_identity": identity,
            "identity_errors": list(identity_verification.get("reasons") or []),
            "resolution": {"status": "EXPLICIT_ID", "nowscore_id": match_id},
            "identity_verification": identity_verification,
            "trusted_jc_provenance": provenance,
            "prematch_evidence": evidence,
            "source_url": urls["market_context"],
            "source_urls": urls,
            "error": "same-ID page identity verification failed",
            **_page_provider_id_details(identity),
        }

    parser_target = _analysis_page_target(target, identity, fixture)
    for surface in SURFACES[1:]:
        payload = _fetch_payload(http_client, surface, urls[surface])
        parsed = _adapter(surface, payload, parser_target)
        observations.append(dict(payload.observation))
        health.append(parsed.get("health") or {})
        for field, item in (parsed.get("fields") or {}).items():
            if field in FIELD_SET:
                all_entries[field].append(_field_temporal_state(item, kickoff))
        if surface == "analysis_data":
            analysis_result = parsed
        elif surface == "coach":
            coach_result = parsed
        elif surface == "referee":
            referee_result = parsed
        elif surface == "panlu":
            panlu_result = parsed

    merged = {field: _merge_field_entries(field, all_entries[field]) for field in FIELD_NAMES}
    evidence = _build_evidence(
        match_id=match_id,
        home=home,
        away=away,
        kickoff=kickoff,
        fixture=fixture,
        identity=identity,
        provenance=provenance,
        fields=merged,
        observations=observations,
        health=health,
    )
    parsed_markets = market_result.get("legacy") if isinstance(market_result.get("legacy"), dict) else {}
    shuju = (analysis_result.get("legacy") or {}) if isinstance(analysis_result, dict) else {}
    coach = (coach_result.get("legacy") or {}) if isinstance(coach_result, dict) else {}
    referee = (referee_result.get("legacy") or {}) if isinstance(referee_result, dict) else {}
    panlu = (panlu_result.get("legacy") or {}) if isinstance(panlu_result, dict) else {}
    context = {
        "coach": coach,
        "referee": referee,
        "panlu": panlu,
        "source_urls": {key: urls[key] for key in ("coach", "referee", "panlu")},
        "errors": {
            item["surface"]: item.get("error_code")
            for item in observations
            if item.get("error_code")
        },
        "quality": {
            "coach_available": merged["coach"]["state"] == "PRESENT",
            "referee_available": merged["referee"]["state"] == "PRESENT",
            "panlu_match_count": int((panlu or {}).get("count") or 0),
        },
    }
    status = "OK" if merged["market_context"]["state"] in {"PRESENT", "SECTION_PRESENT_EMPTY"} else "PARTIAL"
    analysis_error = None
    if merged["recent_form"]["state"] != "PRESENT":
        analysis_error = merged["recent_form"].get("reason_code")
    return {
        "source": "nowscore_prematch_evidence",
        "status": status,
        "fetched_at": evidence["source"].get("observed_at") or _now_utc().isoformat(timespec="seconds"),
        "nowscore_id": match_id,
        "target": target,
        "resolution": {"status": "EXPLICIT_ID", "nowscore_id": match_id},
        "identity": identity,
        "state_memory_identity": _state_memory_target_identity(identity, match_id, fixture),
        "identity_verification": identity_verification,
        "trusted_jc_provenance": provenance,
        "source_url": urls["market_context"],
        "analysis_source_url": urls["analysis_data"],
        "source_urls": urls,
        "ouzhi": parsed_markets.get("ouzhi") or {},
        "yazhi": parsed_markets.get("yazhi") or {},
        "daxiao": parsed_markets.get("daxiao") or {},
        "shuju": shuju,
        "context": context,
        "analysis_error": analysis_error,
        "prematch_evidence": evidence,
        "quality": {
            "home_away_kickoff_verified": True,
            "bookmaker_count": int((parsed_markets.get("ouzhi") or {}).get("total") or 0),
            "asian_count": int((parsed_markets.get("yazhi") or {}).get("total") or 0),
            "total_count": int((parsed_markets.get("daxiao") or {}).get("total") or 0),
            "recent_form_complete": bool((shuju or {}).get("recent_form")),
            "prematch_field_coverage": evidence["coverage"],
            "parser_health": evidence["parser_health"],
            **context["quality"],
        },
    }


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"cohort is not an object: {path}")
    return value


def _cohort_date(value: Any) -> datetime | None:
    text = str(value or "").strip()
    try:
        return datetime.fromisoformat(text[:10]).replace(tzinfo=SHANGHAI)
    except ValueError:
        return None


def discover_natural_cohort(
    *,
    cohort_path: str | Path | None = None,
    business_date: str | None = None,
    as_of: str | datetime | None = None,
) -> tuple[dict[str, Any], Path]:
    """Select the latest READY prediction-universe cohort without crawling it."""

    if cohort_path is not None:
        path = Path(cohort_path)
        payload = _load_json(path)
        if str(payload.get("status") or "") != "READY":
            raise ValueError(f"cohort is not READY: {path}")
        if str(payload.get("source") or "") not in {"nowscore_public_jc", "nowscore_public_jc_sales"}:
            raise ValueError(f"cohort source is not Nowscore JC: {path}")
        return payload, path
    root = ROOT / "data" / "prediction_universe"
    requested = _cohort_date(business_date) if business_date else None
    if business_date and requested is None:
        raise ValueError(f"invalid business date: {business_date}")
    cutoff = _parse_timestamp(as_of) if as_of else datetime.now(SHANGHAI)
    if cutoff is None:
        raise ValueError(f"invalid as-of timestamp: {as_of}")
    candidates: list[tuple[datetime, Path, dict[str, Any]]] = []
    for path in sorted(root.glob("*.json")):
        date_value = _cohort_date(path.stem)
        if date_value is None or date_value > cutoff:
            continue
        if requested is not None and date_value.date() != requested.date():
            continue
        try:
            payload = _load_json(path)
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
            continue
        if str(payload.get("status") or "") != "READY":
            continue
        if str(payload.get("source") or "") not in {"nowscore_public_jc", "nowscore_public_jc_sales"}:
            continue
        candidates.append((date_value, path, payload))
    if not candidates:
        raise FileNotFoundError("no READY prediction-universe cohort at or before the requested cutoff")
    _, path, payload = max(candidates, key=lambda item: item[0])
    return payload, path


def _future_fixture(fixture: Mapping[str, Any], as_of: datetime) -> bool:
    kickoff = _parse_timestamp(
        fixture.get("kickoff")
        or fixture.get("kickoff_local")
        or f"{fixture.get('matchDate') or fixture.get('match_date') or ''}T{fixture.get('matchTime') or fixture.get('match_time') or ''}+08:00"
    )
    return bool(kickoff and kickoff > as_of)


def _relative_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT.resolve()))
    except ValueError:
        return str(path)


def _cohort_match_summary(result: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "nowscore_id": result.get("nowscore_id"),
        "status": result.get("status"),
        "identity_verification": result.get("identity_verification"),
        "trusted_jc_provenance": result.get("trusted_jc_provenance"),
        "prematch_evidence": result.get("prematch_evidence"),
        "quality": result.get("quality"),
        "error": result.get("error"),
    }


def run_natural_cohort(
    *,
    cohort_path: str | Path | None = None,
    business_date: str | None = None,
    as_of: str | datetime | None = None,
    max_matches: int = 12,
    client_factory: Callable[[], Any] | None = None,
) -> dict[str, Any]:
    """Run the current natural future cohort; intended for GitHub Actions."""

    started = _now_utc()
    cohort, selected_path = discover_natural_cohort(
        cohort_path=cohort_path,
        business_date=business_date,
        as_of=as_of,
    )
    cutoff = _parse_timestamp(as_of) if as_of else datetime.now(SHANGHAI)
    if cutoff is None:
        raise ValueError(f"invalid as-of timestamp: {as_of}")
    fixtures = [item for item in cohort.get("fixtures") or [] if isinstance(item, dict)]
    future = [item for item in fixtures if _future_fixture(item, cutoff)]
    selected = future[: max(0, min(int(max_matches), 20))]
    matches: list[dict[str, Any]] = []
    for fixture in selected:
        match_id = _numeric_id(fixture.get("nowscoreId") or fixture.get("nowscore_id"))
        if match_id is None:
            matches.append({
                "nowscore_id": None,
                "status": "INVALID_PROVIDER_ID",
                "trusted_jc_provenance": {"trusted": False, "reasons": ["INVALID_PROVIDER_ID"]},
            })
            continue
        client = client_factory() if client_factory else None
        result = fetch_nowscore_prematch_evidence(
            _fixture_name(fixture, "home"),
            _fixture_name(fixture, "away"),
            _fixture_kickoff(fixture),
            explicit_id=match_id,
            fixture=fixture,
            client=client,
        )
        matches.append(_cohort_match_summary(result))

    field_state_counts: dict[str, dict[str, int]] = {
        field: {state: 0 for state in STATE_NAMES} for field in FIELD_NAMES
    }
    surface_status_counts: Counter[str] = Counter()
    drift_signals: list[dict[str, Any]] = []
    present_count = 0
    total_field_count = len(matches) * len(FIELD_NAMES)
    for match in matches:
        evidence = match.get("prematch_evidence") if isinstance(match, dict) else None
        if not isinstance(evidence, dict):
            continue
        for field in FIELD_NAMES:
            state = str((evidence.get("fields") or {}).get(field, {}).get("state") or "ABSENT")
            if state not in STATE_SET:
                state = "PARSE_UNCERTAIN"
            field_state_counts[field][state] += 1
            present_count += state == "PRESENT"
        health = evidence.get("parser_health") or {}
        for item in health.get("surface_health") or []:
            surface_status_counts[str(item.get("status") or "UNAVAILABLE")] += 1
        drift_signals.extend(health.get("drift_signals") or [])
    coverage = {
        "match_count": len(matches),
        "declared_fixture_count": len(fixtures),
        "future_fixture_count": len(future),
        "selected_fixture_count": len(selected),
        "present_field_count": present_count,
        "field_count": total_field_count,
        "present_fraction": round(present_count / total_field_count, 4) if total_field_count else 0.0,
        "field_state_counts": field_state_counts,
    }
    completed = _now_utc()
    return {
        "contract_version": CONTRACT_VERSION,
        "run": {
            "execution": "github_actions_live",
            "started_at": started.isoformat(timespec="seconds"),
            "completed_at": completed.isoformat(timespec="seconds"),
            "as_of": _timestamp(cutoff),
            "max_matches": int(max_matches),
        },
        "cohort": {
            "source": str(cohort.get("source") or "nowscore_public_jc"),
            "source_path": _relative_path(selected_path),
            "business_date": cohort.get("business_date"),
            "status": cohort.get("status"),
            "declared_fixture_count": len(fixtures),
            "future_fixture_count": len(future),
            "selected_fixture_count": len(selected),
        },
        "matches": matches,
        "coverage": coverage,
        "parser_health": {
            "contract_version": PARSER_HEALTH_VERSION,
            "surface_status_counts": dict(surface_status_counts),
            "drift_signal_count": len(drift_signals),
            "drift_signals": drift_signals,
        },
        "rights": {
            "raw_bodies_persisted": False,
            "raw_html_js_persisted": False,
            "player_name_lists_persisted": False,
            "auth_or_bypass_used": False,
        },
        "change_boundary": {
            "model_math_changed": False,
            "champion_changed": False,
            "serving_changed": False,
            "ui_changed": False,
            "provider_selection_changed": False,
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cohort-path", help="READY prediction-universe JSON path")
    parser.add_argument("--business-date", help="select this READY cohort date")
    parser.add_argument("--as-of", help="prematch cutoff timestamp")
    parser.add_argument("--max-matches", type=int, default=12)
    parser.add_argument("--output", default="nowscore-prematch-evidence.json")
    args = parser.parse_args(argv)
    try:
        report = run_natural_cohort(
            cohort_path=args.cohort_path,
            business_date=args.business_date,
            as_of=args.as_of,
            max_matches=args.max_matches,
        )
    except (FileNotFoundError, OSError, ValueError, json.JSONDecodeError) as error:
        print(f"nowscore prematch evidence failed: {type(error).__name__}: {error}", file=sys.stderr)
        return 2
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "ok", "output": str(output), "match_count": len(report.get("matches") or [])}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
