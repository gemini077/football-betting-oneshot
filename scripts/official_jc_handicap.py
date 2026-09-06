"""Strict source binding for the official JC handicap market.

The official JC handicap (RQSPF) is a three-way market with an explicit
integer line.  This module only accepts a row from the declared Sporttery
official source and binds it to a match with exact stable identity fields,
teams, and kickoff fields.  It never reads Asian-handicap quotes or
third-party odds as a fallback.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone, timedelta
import math
import re
from typing import Any, Mapping
from urllib.parse import parse_qs, urlparse


OFFICIAL_JC_HANDICAP_SOURCE = "sporttery.cn"
OFFICIAL_JC_HANDICAP_MARKET = "rqspf"
OFFICIAL_JC_HANDICAP_MARKET_ID = "JC_HANDICAP_1X2"
OFFICIAL_JC_HANDICAP_SOURCE_CONTRACT_VERSION = "jc_handicap_source.v1"
OFFICIAL_JC_HANDICAP_DEVIG_METHOD = "PROPORTIONAL_INVERSE_ODDS"
OFFICIAL_JC_HANDICAP_CALCULATOR_PATH = "/gateway/jc/football/getmatchcalculatorv1.qry"
OFFICIAL_JC_HANDICAP_QUERY = {
    "channel": "c",
    "poolCode": "had,hhad,crs,ttg,hafu",
}
OFFICIAL_JC_HANDICAP_REQUIRED_HEADERS = frozenset({
    "Accept",
    "Accept-Encoding",
    "Accept-Language",
    "Origin",
    "Referer",
    "User-Agent",
    "X-Requested-With",
})
OFFICIAL_JC_HANDICAP_SOURCE_SURFACE = "https://m.sporttery.cn/mjc/jsq/zqspf/"
LOCAL_TIMEZONE = timezone(timedelta(hours=8))
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _text(value: Any) -> str:
    return " ".join(str(value or "").strip().casefold().split())


def _first(mapping: Mapping[str, Any] | None, *keys: str) -> Any:
    if not isinstance(mapping, Mapping):
        return None
    for key in keys:
        value = mapping.get(key)
        if value not in (None, ""):
            return value
    return None


def _timestamp(value: Any) -> tuple[str | None, datetime | None]:
    if value in (None, ""):
        return None, None
    text = str(value).strip()
    parsed = None
    candidates = (text, text.replace("Z", "+00:00"))
    for candidate in candidates:
        try:
            parsed = datetime.fromisoformat(candidate)
            break
        except ValueError:
            continue
    if parsed is None:
        for pattern in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M:%S"):
            try:
                parsed = datetime.strptime(text, pattern)
                break
            except ValueError:
                continue
    if parsed is None:
        return None, None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=LOCAL_TIMEZONE)
    return parsed.isoformat(), parsed


def _kickoff_value(row: Mapping[str, Any]) -> Any:
    explicit = _first(row, "kickoff_at", "kickoff_local", "kickoff")
    if explicit not in (None, ""):
        return explicit
    match_date = _first(row, "matchDate", "match_date")
    match_time = _first(row, "matchTime", "match_time")
    if match_date not in (None, "") and match_time not in (None, ""):
        return f"{match_date}T{match_time}"
    return None


def _kickoff(row: Mapping[str, Any] | None) -> tuple[str | None, datetime | None]:
    if not isinstance(row, Mapping):
        return None, None
    return _timestamp(_kickoff_value(row))


def _provider_match_id(row: Mapping[str, Any] | None) -> str | None:
    value = _first(row, "matchId", "match_id", "provider_match_id", "id")
    return str(value).strip() if value not in (None, "") else None


def _match_number(row: Mapping[str, Any] | None) -> str | None:
    value = _first(row, "matchNum", "match_num", "provider_match_num")
    return str(value).strip() if value not in (None, "") else None


def _business_date(row: Mapping[str, Any] | None) -> str | None:
    value = _first(row, "businessDate", "business_date", "date")
    if value in (None, ""):
        return None
    return str(value).strip()[:10]


def _official_source_match_id(row: Mapping[str, Any] | None) -> str | None:
    value = _first(row, "sporttery_match_id", "official_match_id")
    return str(value).strip() if value not in (None, "") else None


def _is_official_source_url(value: Any) -> bool:
    if value in (None, ""):
        return False
    parsed = urlparse(str(value).strip())
    hostname = parsed.hostname.casefold() if parsed.hostname else ""
    return (
        parsed.scheme == "https"
        and (hostname == "sporttery.cn" or hostname.endswith(".sporttery.cn"))
        and parsed.path.casefold() == OFFICIAL_JC_HANDICAP_CALCULATOR_PATH
        and parse_qs(parsed.query, keep_blank_values=True) == {
            key: [value]
            for key, value in OFFICIAL_JC_HANDICAP_QUERY.items()
        }
    )


def _is_current_request_contract(
    request_contract: Mapping[str, Any],
    source_url: str,
) -> bool:
    if (
        request_contract.get("method") != "GET"
        or request_contract.get("url") != source_url
        or request_contract.get("params") != OFFICIAL_JC_HANDICAP_QUERY
        or request_contract.get("source_surface") != OFFICIAL_JC_HANDICAP_SOURCE_SURFACE
    ):
        return False
    headers = request_contract.get("required_headers")
    return isinstance(headers, (list, tuple, set, frozenset)) and {
        str(header) for header in headers
    } == set(OFFICIAL_JC_HANDICAP_REQUIRED_HEADERS)


def _raw_response_sha256(document: Mapping[str, Any]) -> str | None:
    value = _first(document, "raw_response_sha256", "response_sha256", "raw_sha256")
    normalized = str(value).strip().casefold() if value not in (None, "") else ""
    return normalized if _SHA256_PATTERN.fullmatch(normalized) else None


def official_match_binding_candidates(
    source_document: Mapping[str, Any] | None,
    target_match: Mapping[str, Any] | None,
) -> list[Mapping[str, Any]]:
    """Return rows that satisfy the deterministic official-row identity contract."""

    document = source_document if isinstance(source_document, Mapping) else {}
    target = target_match if isinstance(target_match, Mapping) else {}
    return [row for row in _rows(document) if _same_exact_identity(row, target)]


def official_rqspf_line(row: Mapping[str, Any] | None) -> int | None:
    if not isinstance(row, Mapping) or not isinstance(row.get("rqspf"), Mapping):
        return None
    value = _number(_first(row["rqspf"], "handicap", "line", "goalLine"))
    return int(value) if value is not None and int(value) == value else None


def official_rqspf_odds(row: Mapping[str, Any] | None) -> dict[str, float] | None:
    if not isinstance(row, Mapping) or not isinstance(row.get("rqspf"), Mapping):
        return None
    odds = {
        key: _number(row["rqspf"].get(key))
        for key in ("home", "draw", "away")
    }
    if any(value is None or value <= 1.0 for value in odds.values()):
        return None
    return {key: float(value) for key, value in odds.items()}


def _same_exact_identity(source: Mapping[str, Any], target: Mapping[str, Any]) -> bool:
    source_id = _provider_match_id(source)
    target_id = _official_source_match_id(target)
    if target_id and (not source_id or source_id != target_id):
        return False
    source_num = _match_number(source)
    target_num = _first(
        target,
        "sporttery_match_num",
        "official_match_num",
        "matchNum",
        "match_num",
    )
    target_num = str(target_num).strip() if target_num not in (None, "") else None
    if target_num and (not source_num or source_num != target_num):
        return False
    source_date = _business_date(source)
    target_date = _business_date(target)
    if target_date and (not source_date or source_date != target_date):
        return False
    source_home = _first(source, "homeTeam", "home_team", "home")
    source_away = _first(source, "awayTeam", "away_team", "away")
    target_home = _first(target, "homeTeam", "home_team", "home")
    target_away = _first(target, "awayTeam", "away_team", "away")
    if not source_home or not source_away or not target_home or not target_away:
        return False
    if _text(source_home) != _text(target_home) or _text(source_away) != _text(target_away):
        return False
    source_kickoff_text, source_kickoff = _kickoff(source)
    target_kickoff_text, target_kickoff = _kickoff(target)
    if source_kickoff is None or target_kickoff is None:
        return False
    if source_kickoff != target_kickoff:
        return False
    return True


def _rows(source_document: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    for key in ("matches", "fixtures"):
        value = source_document.get(key)
        if isinstance(value, list):
            return [row for row in value if isinstance(row, Mapping)]
    return []


def _unavailable(
    reason: str,
    *,
    source_ref: str | None = None,
    source_url: str | None = None,
    source_timestamp: str | None = None,
    business_date: str | None = None,
    request_contract: Mapping[str, Any] | None = None,
    http_status: int | None = None,
    raw_response_sha256: str | None = None,
    wire_response_sha256: str | None = None,
    response_bytes: int | None = None,
    wire_response_bytes: int | None = None,
    content_type: str | None = None,
) -> dict[str, Any]:
    return {
        "contract_version": OFFICIAL_JC_HANDICAP_SOURCE_CONTRACT_VERSION,
        "status": "NOT_AVAILABLE",
        "authority": "official_sporttery_rqspf_only",
        "provider": None,
        "market": OFFICIAL_JC_HANDICAP_MARKET,
        "market_identity": OFFICIAL_JC_HANDICAP_MARKET_ID,
        "business_date": business_date,
        "source_ref": source_ref,
        "source_url": source_url,
        "request_contract": deepcopy(dict(request_contract)) if isinstance(request_contract, Mapping) else None,
        "http_status": http_status,
        "raw_response_sha256": raw_response_sha256,
        "wire_response_sha256": wire_response_sha256,
        "response_bytes": response_bytes,
        "wire_response_bytes": wire_response_bytes,
        "content_type": content_type,
        "captured_at": source_timestamp,
        "match_binding": {"status": "NOT_AVAILABLE"},
        "handicap_line": None,
        "line": None,
        "official_odds": None,
        "same_time_official_market_baseline": {
            "status": "NOT_AVAILABLE",
            "probabilities": None,
            "source_odds": None,
            "captured_at": None,
            "source": None,
            "reason": reason,
            "derived_from_asian_handicap": False,
            "devig_method": None,
            "overround": None,
        },
        "reason": reason,
    }


def build_official_jc_handicap_state(
    source_document: Mapping[str, Any] | None,
    target_match: Mapping[str, Any] | None,
    *,
    source_ref: str | None = None,
) -> dict[str, Any]:
    """Return verified official RQSPF evidence or an explicit unavailable state."""

    document = source_document if isinstance(source_document, Mapping) else {}
    source_url = _first(document, "url", "source_url")
    source_url = str(source_url).strip() if source_url not in (None, "") else None
    business_date = str(_first(document, "business_date", "businessDate", "date") or "").strip()[:10] or None
    request_contract = document.get("request_contract")
    http_status = document.get("http_status")
    try:
        http_status = int(http_status) if http_status not in (None, "") else None
    except (TypeError, ValueError):
        http_status = None
    raw_response_sha256 = _raw_response_sha256(document)
    wire_response_sha256 = _first(document, "wire_response_sha256", "wire_sha256")
    wire_response_sha256 = (
        str(wire_response_sha256).strip().casefold()
        if wire_response_sha256 not in (None, "")
        else None
    )
    if wire_response_sha256 is not None and not _SHA256_PATTERN.fullmatch(wire_response_sha256):
        wire_response_sha256 = None
    response_bytes = document.get("response_bytes")
    wire_response_bytes = document.get("wire_response_bytes")
    content_type = str(document.get("content_type") or "") or None
    common_unavailable = {
        "source_ref": source_ref,
        "source_url": source_url,
        "business_date": business_date,
        "request_contract": request_contract if isinstance(request_contract, Mapping) else None,
        "http_status": http_status,
        "raw_response_sha256": raw_response_sha256,
        "wire_response_sha256": wire_response_sha256,
        "response_bytes": response_bytes,
        "wire_response_bytes": wire_response_bytes,
        "content_type": content_type,
    }
    source_timestamp, source_datetime = _timestamp(
        _first(document, "fetch_time", "fetched_at", "captured_at", "source_timestamp")
    )
    if str(document.get("source") or "").strip().casefold() != OFFICIAL_JC_HANDICAP_SOURCE:
        return _unavailable(
            "OFFICIAL_SPORTTERY_SOURCE_REQUIRED",
            **common_unavailable,
            source_timestamp=source_timestamp,
        )
    if document.get("success") is not True:
        return _unavailable(
            "OFFICIAL_SPORTTERY_SOURCE_UNAVAILABLE",
            **common_unavailable,
            source_timestamp=source_timestamp,
        )
    if http_status != 200 or document.get("payload_success", True) is not True:
        return _unavailable(
            "OFFICIAL_SOURCE_HTTP_OR_PAYLOAD_NOT_VERIFIED",
            **common_unavailable,
            source_timestamp=source_timestamp,
        )
    if not _is_official_source_url(source_url):
        return _unavailable(
            "OFFICIAL_SPORTTERY_CALCULATOR_URL_REQUIRED",
            **common_unavailable,
            source_timestamp=source_timestamp,
        )
    if not isinstance(request_contract, Mapping):
        return _unavailable(
            "OFFICIAL_SOURCE_REQUEST_CONTRACT_REQUIRED",
            **common_unavailable,
            source_timestamp=source_timestamp,
        )
    if not _is_current_request_contract(request_contract, source_url):
        return _unavailable(
            "OFFICIAL_SOURCE_REQUEST_CONTRACT_INVALID",
            **common_unavailable,
            source_timestamp=source_timestamp,
        )
    if raw_response_sha256 is None:
        return _unavailable(
            "OFFICIAL_SOURCE_RAW_HASH_REQUIRED",
            **common_unavailable,
            source_timestamp=source_timestamp,
        )
    target = target_match if isinstance(target_match, Mapping) else {}
    candidates = official_match_binding_candidates(document, target)
    if len(candidates) != 1:
        return _unavailable(
            "EXACT_OFFICIAL_MATCH_BINDING_REQUIRED" if not candidates else "AMBIGUOUS_OFFICIAL_MATCH_BINDING",
            **common_unavailable,
            source_timestamp=source_timestamp,
        )
    row = candidates[0]
    if not _provider_match_id(row) or not _match_number(row):
        return _unavailable(
            "OFFICIAL_MATCH_ID_AND_NUMBER_REQUIRED",
            **common_unavailable,
            source_timestamp=source_timestamp,
        )
    if source_datetime is None:
        return _unavailable(
            "OFFICIAL_SOURCE_CAPTURE_TIME_REQUIRED",
            **common_unavailable,
        )
    _, kickoff_datetime = _kickoff(row)
    if kickoff_datetime is None or source_datetime >= kickoff_datetime:
        return _unavailable(
            "OFFICIAL_SOURCE_MUST_BE_PREMATCH",
            **common_unavailable,
            source_timestamp=source_timestamp,
        )
    rqspf = row.get("rqspf")
    if not isinstance(rqspf, Mapping):
        return _unavailable(
            "OFFICIAL_RQSPF_NOT_AVAILABLE",
            **common_unavailable,
            source_timestamp=source_timestamp,
        )
    line = _number(_first(rqspf, "handicap", "line", "goalLine"))
    if line is None or int(line) != line:
        return _unavailable(
            "OFFICIAL_RQSPF_INTEGER_LINE_REQUIRED",
            **common_unavailable,
            source_timestamp=source_timestamp,
        )
    line = int(line)
    odds: dict[str, float] | None = None
    try:
        candidate_odds = {key: float(rqspf[key]) for key in ("home", "draw", "away")}
        if all(math.isfinite(value) and value > 1.0 for value in candidate_odds.values()):
            odds = candidate_odds
    except (KeyError, TypeError, ValueError, OverflowError):
        odds = None
    baseline: dict[str, Any]
    if odds is None:
        baseline = {
            "status": "NOT_AVAILABLE",
            "probabilities": None,
            "source_odds": None,
            "captured_at": None,
            "source": None,
            "reason": "OFFICIAL_RQSPF_THREE_WAY_ODDS_UNAVAILABLE",
            "derived_from_asian_handicap": False,
            "devig_method": None,
            "overround": None,
        }
    else:
        inverse = {key: 1.0 / value for key, value in odds.items()}
        total = sum(inverse.values())
        baseline = {
            "status": "AVAILABLE",
            "probabilities": {key: inverse[key] / total for key in ("home", "draw", "away")},
            "source_odds": odds,
            "captured_at": source_timestamp,
            "source": "sporttery.cn.rqspf",
            "reason": None,
            "derived_from_asian_handicap": False,
            "devig_method": OFFICIAL_JC_HANDICAP_DEVIG_METHOD,
            "overround": total,
            "line": line,
        }
    binding = {
        "status": "EXACT",
        "provider_match_id": _provider_match_id(row),
        "provider_match_num": _match_number(row),
        "business_date": _business_date(row) or business_date,
        "home": _first(row, "homeTeam", "home_team", "home"),
        "away": _first(row, "awayTeam", "away_team", "away"),
        "kickoff_at": _kickoff(row)[0],
        "identity_basis": [
            key
            for key, value in (
                ("provider_match_id", _provider_match_id(row)),
                ("provider_match_num", _match_number(row)),
                ("business_date", _business_date(row) or business_date),
                ("home_away_orientation", True),
                ("kickoff_at", _kickoff(row)[0]),
            )
            if value not in (None, "")
        ],
    }
    return {
        "contract_version": OFFICIAL_JC_HANDICAP_SOURCE_CONTRACT_VERSION,
        "status": "AVAILABLE",
        "authority": "official_sporttery_rqspf",
        "provider": OFFICIAL_JC_HANDICAP_SOURCE,
        "market": OFFICIAL_JC_HANDICAP_MARKET,
        "market_identity": OFFICIAL_JC_HANDICAP_MARKET_ID,
        "business_date": _business_date(row) or business_date,
        "source_ref": source_ref,
        "source_url": source_url,
        "request_contract": deepcopy(dict(request_contract)),
        "http_status": http_status,
        "raw_response_sha256": raw_response_sha256,
        "wire_response_sha256": wire_response_sha256,
        "response_bytes": response_bytes,
        "wire_response_bytes": wire_response_bytes,
        "content_type": content_type,
        "captured_at": source_timestamp,
        "match_binding": binding,
        "handicap_line": line,
        "line": line,
        "line_semantics": "home_goals_plus_official_rqspf_line_compared_to_away_goals",
        "official_odds": odds,
        "same_time_official_market_baseline": baseline,
        "reason": None,
    }
