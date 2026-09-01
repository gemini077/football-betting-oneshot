"""Persistence boundary for the daily Prediction Universe."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    from match_identity import canonical_match_id
except ImportError:  # package imports used by tests
    from scripts.match_identity import canonical_match_id


PROJECT_ROOT = Path(__file__).resolve().parents[1]
UNIVERSE_ROOT = PROJECT_ROOT / "data" / "prediction_universe"
ALLOWED_SOURCES = {"sporttery.cn", "trade.500.com", "nowscore_public_jc"}
VALID_SNAPSHOT_STATUSES = {"READY", "EMPTY_CONFIRMED"}
SCHEMA_VERSION = "1.0"
TRUSTED_NOWSCORE_JC_SOURCE = "nowscore_public_jc_sales"
TRUSTED_NOWSCORE_JC_SALES_WINDOW = "11:00--次日11:00"

_FIELD_ALIASES = {
    "matchId": ("matchId", "match_id", "id"),
    "matchNum": ("matchNum", "match_num"),
    "businessDate": ("businessDate", "business_date"),
    "matchDate": ("matchDate", "match_date"),
    "matchTime": ("matchTime", "match_time"),
    "league": ("league", "competition"),
    "homeTeam": ("homeTeam", "home_team", "home"),
    "awayTeam": ("awayTeam", "away_team", "away"),
    "homeTeamEn": ("homeTeamEn", "home_team_en"),
    "awayTeamEn": ("awayTeamEn", "away_team_en"),
    "nowscoreId": ("nowscoreId", "nowscore_id"),
    "nowscore_id": ("nowscore_id", "nowscoreId"),
    "nowscoreMatchStatus": ("nowscoreMatchStatus", "nowscore_match_status"),
    "nowscoreMatchConfidence": ("nowscoreMatchConfidence", "nowscore_match_confidence"),
    "jc_membership": ("jc_membership", "jcMembership"),
    "jc_membership_source": ("jc_membership_source", "jcMembershipSource"),
    "jc_membership_evidence": ("jc_membership_evidence", "jcMembershipEvidence"),
    "source_surface": ("source_surface", "sourceSurface"),
    "source_url": ("source_url", "sourceUrl"),
    "business_date_source": ("business_date_source", "businessDateSource"),
    "business_date_source_url": (
        "business_date_source_url", "businessDateSourceUrl"
    ),
    "business_date_contract": (
        "business_date_contract", "businessDateContract"
    ),
    "match_number_source": ("match_number_source", "matchNumberSource"),
    "sales_row_id": ("sales_row_id", "salesRowId"),
    "cansale": ("cansale", "canSale"),
    "a32_corroboration": ("a32_corroboration", "a32Corroboration"),
    "a32_corroboration_status": (
        "a32_corroboration_status", "a32CorroborationStatus"
    ),
    "fetched_at": ("fetched_at", "fetchedAt"),
    "date_provenance": ("date_provenance", "dateProvenance"),
    "schedule_source_date": ("schedule_source_date", "scheduleSourceDate"),
    "schedule_source_date_format": (
        "schedule_source_date_format", "scheduleSourceDateFormat"
    ),
    "shujuId": ("shujuId", "shuju_id"),
    "singleMatchAvailable": ("singleMatchAvailable", "single_match_available"),
    "spf": ("spf",),
    "rqspf": ("rqspf",),
}


def universe_path(business_date: str, root: Path = UNIVERSE_ROOT) -> Path:
    return Path(root) / f"{business_date}.json"


def load_prediction_universe(
    business_date: str, root: Path = UNIVERSE_ROOT
) -> dict[str, Any] | None:
    try:
        payload = json.loads(universe_path(business_date, root).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _now() -> str:
    return datetime.now().astimezone().isoformat()


def _present(value: Any) -> bool:
    return value not in (None, "")


def _is_true(value: Any) -> bool:
    return value is True or str(value).strip().casefold() == "true"


def _first_value(row: dict[str, Any], aliases: tuple[str, ...]) -> Any:
    for key in aliases:
        if key in row and _present(row[key]):
            return row[key]
    return None


def _first_mapping_value(row: Mapping[str, Any] | None, *keys: str) -> Any:
    if not isinstance(row, Mapping):
        return None
    for key in keys:
        if _present(row.get(key)):
            return row[key]
    return None


def _numeric_provider_id(value: Any) -> int | None:
    if isinstance(value, bool) or value in (None, ""):
        return None
    text = str(value).strip()
    if not text.isdigit():
        return None
    numeric = int(text)
    return numeric if numeric > 0 else None


def trusted_nowscore_jc_fixture(
    fixture: Mapping[str, Any] | None,
    explicit_id: Any,
) -> dict[str, Any]:
    """Validate the narrow same-provider bypass contract for a JC fixture.

    The result is intentionally diagnostic rather than a boolean so callers
    can preserve the reason when a trusted path is not available.  Kickoff and
    market-page orientation remain separate checks in the Nowscore adapter.
    """

    reasons: list[str] = []
    if not isinstance(fixture, Mapping):
        return {
            "trusted": False,
            "source": TRUSTED_NOWSCORE_JC_SOURCE,
            "nowscore_id": _numeric_provider_id(explicit_id),
            "reasons": ["MISSING_FIXTURE"],
        }

    fixture_id = _numeric_provider_id(
        _first_mapping_value(fixture, "nowscoreId", "nowscore_id")
    )
    requested_id = _numeric_provider_id(explicit_id)
    evidence = fixture.get("jc_membership_evidence")
    provenance = fixture.get("date_provenance")
    evidence_id = _numeric_provider_id(
        evidence.get("nowscore_id") if isinstance(evidence, Mapping) else None
    )
    if requested_id is None or fixture_id != requested_id or evidence_id != fixture_id:
        reasons.append("PROVIDER_ID_MISMATCH")

    if fixture.get("jc_membership") != "VERIFIED":
        reasons.append("JC_MEMBERSHIP_UNVERIFIED")
    if fixture.get("jc_membership_source") != TRUSTED_NOWSCORE_JC_SOURCE:
        reasons.append("JC_MEMBERSHIP_SOURCE_MISMATCH")
    if str(_first_mapping_value(fixture, "nowscoreMatchStatus", "nowscore_match_status") or "") != "EXACT_MATCH":
        reasons.append("NOWSCORE_MATCH_NOT_EXACT")
    try:
        confidence = float(
            _first_mapping_value(
                fixture,
                "nowscoreMatchConfidence",
                "nowscore_match_confidence",
            )
        )
    except (TypeError, ValueError):
        confidence = None
    if confidence != 1.0:
        reasons.append("NOWSCORE_MATCH_NOT_CONFIRMED")

    business_date = str(
        _first_mapping_value(fixture, "businessDate", "business_date") or ""
    ).strip()
    if not business_date:
        reasons.append("BUSINESS_DATE_PROVENANCE_MISSING")
    if fixture.get("business_date_source") != TRUSTED_NOWSCORE_JC_SOURCE:
        reasons.append("BUSINESS_DATE_SOURCE_MISMATCH")

    source_values = [
        fixture.get("source_surface"),
        fixture.get("source_url"),
        fixture.get("business_date_source_url"),
        evidence.get("source_surface") if isinstance(evidence, Mapping) else None,
        provenance.get("business_date_source_url") if isinstance(provenance, Mapping) else None,
    ]
    if any(not _present(value) for value in source_values) or len({str(value).strip() for value in source_values}) != 1:
        reasons.append("SALES_SOURCE_PROVENANCE_INCOMPLETE")
    if not _present(_first_mapping_value(fixture, "fetched_at", "captured_at")):
        reasons.append("SALES_CAPTURE_PROVENANCE_MISSING")

    match_number = _first_mapping_value(fixture, "matchNum", "match_num", "match_number")
    match_number_source = _first_mapping_value(fixture, "match_number_source")
    sales_row_id = _first_mapping_value(fixture, "sales_row_id", "salesRowId")
    if not _present(match_number) or match_number_source != TRUSTED_NOWSCORE_JC_SOURCE:
        reasons.append("SALES_MATCH_NUMBER_PROVENANCE_INCOMPLETE")
    if not _present(sales_row_id):
        reasons.append("SALES_ROW_PROVENANCE_MISSING")

    if not isinstance(evidence, Mapping):
        reasons.append("JC_MEMBERSHIP_EVIDENCE_MISSING")
    else:
        if evidence.get("source") != TRUSTED_NOWSCORE_JC_SOURCE:
            reasons.append("JC_EVIDENCE_SOURCE_MISMATCH")
        if evidence.get("selected_date") != business_date or evidence.get("business_date") != business_date:
            reasons.append("JC_EVIDENCE_DATE_MISMATCH")
        if evidence.get("sales_window") != TRUSTED_NOWSCORE_JC_SALES_WINDOW:
            reasons.append("JC_EVIDENCE_WINDOW_MISMATCH")
        if evidence.get("match_number") != match_number:
            reasons.append("JC_EVIDENCE_MATCH_NUMBER_MISMATCH")
        if evidence.get("sales_row_id") != sales_row_id:
            reasons.append("JC_EVIDENCE_SALES_ROW_MISMATCH")
        if evidence.get("nowscore_id") not in (fixture_id, str(fixture_id)):
            reasons.append("PROVIDER_ID_MISMATCH")

    if not isinstance(provenance, Mapping):
        reasons.append("DATE_PROVENANCE_MISSING")
    else:
        if (
            provenance.get("business_date") != business_date
            or provenance.get("expected_business_date") != business_date
            or provenance.get("business_date_source") != TRUSTED_NOWSCORE_JC_SOURCE
            or provenance.get("sales_window") != TRUSTED_NOWSCORE_JC_SALES_WINDOW
            or provenance.get("sales_row_id") != sales_row_id
            or provenance.get("match_number") != match_number
        ):
            reasons.append("DATE_PROVENANCE_MISMATCH")

    return {
        "trusted": not reasons,
        "source": TRUSTED_NOWSCORE_JC_SOURCE,
        "nowscore_id": requested_id,
        "business_date": business_date or None,
        "source_url": next((str(value).strip() for value in source_values if _present(value)), None),
        "reasons": list(dict.fromkeys(reasons)),
    }


def _is_authorized_full_schedule_payload(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    source = str(payload.get("source") or "")
    if source not in ALLOWED_SOURCES:
        return False
    if _is_true(payload.get("analysis_input_only")):
        return False
    if source == "nowscore_public_jc":
        if str(payload.get("schedule_scope") or "").casefold() != "jc":
            return False
        rows = payload.get("matches")
        if payload.get("success") is not True:
            return isinstance(rows, list) and not rows
        if payload.get("primary_source") != "nowscore_public_jc_sales":
            return False
        if not isinstance(rows, list) or not rows:
            return False
        try:
            for key in (
                "duplicate_nowscore_id_count",
                "duplicate_sales_row_id_count",
                "duplicate_match_number_count",
                "ambiguous_nowscore_id_count",
            ):
                if int(payload.get(key) or 0) != 0:
                    return False
        except (TypeError, ValueError):
            return False
        contract = payload.get("business_date_contract")
        if not isinstance(contract, dict):
            return False
        if (
            contract.get("valid") is not True
            or contract.get("surface") != "nowscore_public_jc_sales"
            or contract.get("date_anchor") != "SelDate + niDate header date"
            or contract.get("sales_window") != "11:00--次日11:00"
            or contract.get("selected_date") != str(
                payload.get("business_date") or payload.get("date") or ""
            )
            or contract.get("requested_date") != str(
                payload.get("business_date") or payload.get("date") or ""
            )
        ):
            return False
        business_date = str(
            payload.get("business_date") or payload.get("date") or ""
        )
        if (
            not business_date
            or payload.get("business_date") != business_date
            or payload.get("date") not in (None, "", business_date)
        ):
            return False
        sales_url = str(
            payload.get("business_date_source_url") or payload.get("url") or ""
        )
        if (
            payload.get("business_date_source") != "nowscore_public_jc_sales"
            or not sales_url
            or payload.get("business_date_source_url") != sales_url
            or payload.get("url") != sales_url
        ):
            return False
        for row in rows:
            if not isinstance(row, dict):
                return False
            if row.get("jc_membership") != "VERIFIED":
                return False
            if row.get("jc_membership_source") != "nowscore_public_jc_sales":
                return False
            if row.get("nowscore_id", row.get("nowscoreId")) in (None, ""):
                return False
            if row.get("source_surface") in (None, ""):
                return False
            if row.get("source_url") in (None, ""):
                return False
            if row.get("source_surface") != sales_url or row.get("source_url") != sales_url:
                return False
            if row.get("business_date_source") != "nowscore_public_jc_sales":
                return False
            if row.get("business_date_source_url") in (None, ""):
                return False
            if row.get("business_date_source_url") != sales_url:
                return False
            if row.get("businessDate", row.get("business_date")) != business_date:
                return False
            if row.get("sales_row_id") in (None, ""):
                return False
            if row.get("match_number", row.get("matchNum")) in (None, ""):
                return False
            provenance = row.get("date_provenance")
            if not isinstance(provenance, dict):
                return False
            if (
                provenance.get("business_date") != business_date
                or provenance.get("business_date_source")
                != "nowscore_public_jc_sales"
                or provenance.get("sales_window") != "11:00--次日11:00"
            ):
                return False
            evidence = row.get("jc_membership_evidence")
            if not isinstance(evidence, dict):
                return False
            if evidence.get("source") != "nowscore_public_jc_sales":
                return False
            if (
                evidence.get("selected_date") != business_date
                or evidence.get("business_date") != business_date
                or evidence.get("sales_window") != "11:00--次日11:00"
                or evidence.get("nowscore_id")
                not in (row.get("nowscore_id"), row.get("nowscoreId"))
                or evidence.get("sales_row_id") != row.get("sales_row_id")
            ):
                return False
        return True
    if payload.get("match_filter") not in (None, ""):
        return False
    for key in ("single_match", "singleMatch", "match_specific", "filtered", "deep"):
        if _is_true(payload.get(key)):
            return False
    if str(payload.get("mode") or "").casefold() in {"deep", "single_match", "filtered"}:
        return False
    matches = payload.get("matches")
    unfiltered_count = payload.get("unfiltered_match_count")
    if isinstance(matches, list) and unfiltered_count not in (None, ""):
        try:
            if int(unfiltered_count) != len(matches):
                return False
        except (TypeError, ValueError):
            return False
    return True


def is_full_daily_schedule(payload: Any) -> bool:
    """Whether a successful payload is allowed to update a daily Universe snapshot."""
    return payload.get("success") is True and _is_authorized_full_schedule_payload(payload)


def _normalise_fixture(row: Any, business_date: str) -> dict[str, Any]:
    if not isinstance(row, dict):
        raise ValueError("fixture row is not an object")

    fixture: dict[str, Any] = {}
    for field, aliases in _FIELD_ALIASES.items():
        value = _first_value(row, aliases)
        if _present(value):
            fixture[field] = value

    fixture.setdefault("businessDate", business_date)
    kickoff = str(row.get("kickoff_local") or row.get("kickoff") or "")
    if not fixture.get("matchDate") and kickoff:
        fixture["matchDate"] = kickoff[:10]
    if not fixture.get("matchTime") and len(kickoff) >= 16:
        fixture["matchTime"] = kickoff[11:16]

    if not (
        _present(fixture.get("matchId"))
        or (_present(fixture.get("homeTeam")) and _present(fixture.get("awayTeam")))
        or _present(fixture.get("matchNum"))
    ):
        raise ValueError("fixture has no stable identity fields")
    return fixture


def _fixture_key(fixture: dict[str, Any]) -> str:
    if _present(fixture.get("matchId")):
        return f"matchId:{fixture['matchId']}"
    kickoff = ""
    if fixture.get("matchDate") and fixture.get("matchTime"):
        kickoff = f"{fixture['matchDate']}T{str(fixture['matchTime'])[:5]}:00+08:00"
    return "canonical:" + canonical_match_id(
        {
            "home": fixture.get("homeTeam"),
            "away": fixture.get("awayTeam"),
            "kickoff_local": kickoff,
        }
    )


def _prepare_fixtures(
    rows: Any, business_date: str
) -> tuple[list[dict[str, Any]], int, int]:
    if not isinstance(rows, list):
        raise ValueError("matches is not a list")

    source_fixture_count = len(rows)
    excluded_cross_date_count = 0
    fixtures: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        explicit_date = _first_value(row, ("businessDate", "business_date")) if isinstance(row, dict) else None
        if _present(explicit_date) and str(explicit_date) != business_date:
            excluded_cross_date_count += 1
            continue
        fixture = _normalise_fixture(row, business_date)
        key = _fixture_key(fixture)
        if key not in seen:
            seen.add(key)
            fixtures.append(fixture)
    return fixtures, source_fixture_count, excluded_cross_date_count


def _attempt_record(
    payload: Any,
    status: str,
    fetched_at: str,
    source_fixture_count: int = 0,
    fixture_count: int = 0,
    excluded_cross_date_count: int = 0,
    error: str | None = None,
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "status": status,
        "source": str(payload.get("source") or "unknown") if isinstance(payload, dict) else "unknown",
        "fetched_at": fetched_at,
        "source_fixture_count": source_fixture_count,
        "fixture_count": fixture_count,
        "excluded_cross_date_count": excluded_cross_date_count,
    }
    if error:
        record["error"] = error
    fallback_provenance = payload.get("fallback_provenance") if isinstance(payload, dict) else None
    if isinstance(fallback_provenance, dict):
        record["fallback_provenance"] = dict(fallback_provenance)
    if isinstance(payload, dict):
        for key in (
            "url", "source_surface", "backing_data_url", "surface",
            "primary_source", "business_date_source", "business_date_source_url",
            "jc_contract", "business_date_contract",
            "jc_membership_source", "date_provenance",
        ):
            if key in payload and payload[key] not in (None, ""):
                record[key] = payload[key]
    return record


def _write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def update_prediction_universe(
    business_date: str,
    payload: Any,
    *,
    root: Path = UNIVERSE_ROOT,
    fetched_at: str | None = None,
) -> dict[str, Any]:
    """Apply one full-schedule attempt without allowing bad data to shrink a valid snapshot."""
    path = universe_path(business_date, root)
    existing = load_prediction_universe(business_date, root)
    attempt_at = str(
        fetched_at
        or (payload.get("fetch_time") if isinstance(payload, dict) else None)
        or _now()
    )

    source_fixture_count = len(payload.get("matches") or []) if isinstance(payload, dict) and isinstance(payload.get("matches"), list) else 0
    fixtures: list[dict[str, Any]] = []
    excluded_cross_date_count = 0
    error: str | None = None
    if not _is_authorized_full_schedule_payload(payload):
        attempt = _attempt_record(
            payload,
            "FETCH_FAILED",
            attempt_at,
            source_fixture_count,
            0,
            0,
            "NOT_FULL_OFFICIAL_DAILY_SCHEDULE",
        )
        if isinstance(existing, dict):
            return existing
        return {
            "schema_version": SCHEMA_VERSION,
            "business_date": business_date,
            "status": "FETCH_FAILED",
            "source": attempt["source"],
            "fetched_at": attempt_at,
            "source_fixture_count": source_fixture_count,
            "fixture_count": 0,
            "excluded_cross_date_count": 0,
            "fixtures": [],
            "last_fetch": attempt,
            "persisted": False,
        }
    if payload.get("success") is not True:
        error = "FULL_SCHEDULE_FETCH_FAILED"
    else:
        try:
            fixtures, source_fixture_count, excluded_cross_date_count = _prepare_fixtures(
                payload.get("matches"), business_date
            )
            if source_fixture_count > 0 and not fixtures:
                error = "NO_FIXTURES_FOR_BUSINESS_DATE"
        except (TypeError, ValueError) as exc:
            error = f"MALFORMED_FULL_SCHEDULE: {exc}"

    if error:
        attempt = _attempt_record(
            payload,
            "FETCH_FAILED",
            attempt_at,
            source_fixture_count,
            0,
            excluded_cross_date_count,
            error,
        )
        if isinstance(existing, dict) and existing.get("status") in VALID_SNAPSHOT_STATUSES:
            preserved = dict(existing)
            preserved["last_fetch"] = attempt
            _write(path, preserved)
            return preserved
        snapshot = {
            "schema_version": SCHEMA_VERSION,
            "business_date": business_date,
            "status": "FETCH_FAILED",
            "source": attempt["source"],
            "fetched_at": attempt_at,
            "source_fixture_count": source_fixture_count,
            "fixture_count": 0,
            "excluded_cross_date_count": excluded_cross_date_count,
            "fixtures": [],
            "last_fetch": attempt,
        }
        _write(path, snapshot)
        return snapshot

    status = "READY" if fixtures else "EMPTY_CONFIRMED"
    snapshot = {
        "schema_version": SCHEMA_VERSION,
        "business_date": business_date,
        "status": status,
        "source": str(payload["source"]),
        "fetched_at": attempt_at,
        "source_fixture_count": source_fixture_count,
        "fixture_count": len(fixtures),
        "excluded_cross_date_count": excluded_cross_date_count,
        "fixtures": fixtures,
        "last_fetch": _attempt_record(
            payload,
            status,
            attempt_at,
            source_fixture_count,
            len(fixtures),
            excluded_cross_date_count,
        ),
    }
    _write(path, snapshot)
    return snapshot
