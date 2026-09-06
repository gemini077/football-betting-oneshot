"""Bounded GitHub-hosted audit of the current Nowscore JC line surface.

The business date is selected from the newest authoritative
``data/prediction_universe/YYYY-MM-DD.json`` snapshot.  The audit only calls
the existing mobile Nowscore analysis page and never writes production data.
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import date, datetime
import json
import os
from pathlib import Path
import platform
import re
from typing import Any, Mapping

from official_jc_handicap import (
    abstain_nowscore_jc_handicap_capture,
    capture_nowscore_jc_handicap,
)
from prediction_universe import (
    NOT_YET_PUBLISHED,
    load_prediction_universe,
    trusted_nowscore_jc_fixture,
)


ROOT = Path(__file__).resolve().parents[1]
UNIVERSE_ROOT = ROOT / "data" / "prediction_universe"
AUDIT_CONTRACT_VERSION = "jc_handicap_nowscore_live_audit.v1"
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
DEFAULT_LIMIT = 20


def _load(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def resolve_current_business_date(universe_root: Path = UNIVERSE_ROOT) -> str:
    """Resolve the newest authoritative business date without a hardcoded date."""

    candidates: list[tuple[date, str]] = []
    for path in Path(universe_root).glob("*.json"):
        if not DATE_RE.fullmatch(path.stem):
            continue
        payload = _load(path)
        if not payload or payload.get("business_date") != path.stem:
            continue
        if str(payload.get("status") or "") not in {"READY", "EMPTY_CONFIRMED"}:
            continue
        if payload.get("status") == NOT_YET_PUBLISHED:
            continue
        if payload.get("source") != "nowscore_public_jc":
            continue
        candidates.append((date.fromisoformat(path.stem), path.stem))
    if not candidates:
        raise RuntimeError("NO_AUTHORITATIVE_PREDICTION_UNIVERSE")
    return max(candidates)[1]


def _identity_key(fixture: Mapping[str, Any]) -> tuple[str, ...] | None:
    values = (
        str(fixture.get("businessDate") or fixture.get("business_date") or "").strip(),
        str(fixture.get("matchNum") or fixture.get("match_num") or "").strip().casefold(),
        str(fixture.get("homeTeam") or fixture.get("home_team") or "").strip().casefold(),
        str(fixture.get("awayTeam") or fixture.get("away_team") or "").strip().casefold(),
        str(fixture.get("matchDate") or fixture.get("match_date") or "").strip(),
        str(fixture.get("matchTime") or fixture.get("match_time") or "").strip(),
    )
    return values if all(values) else None


def _status_counter(rows: list[Mapping[str, Any]]) -> dict[str, int]:
    return dict(Counter(
        str(row.get("page_http_status")) if row.get("page_http_status") is not None else "NETWORK_ERROR"
        for row in rows
    ))


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=datetime.now().astimezone().tzinfo)


def _name_diagnostics(rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    variant_rows = [row for row in rows if row.get("name_diagnostics")]
    codes = Counter(
        str(code)
        for row in variant_rows
        for code in row.get("name_diagnostics") or []
    )
    return {
        "variant_row_n": len(variant_rows),
        "variant_side_n": sum(len(row.get("name_variant_sides") or []) for row in variant_rows),
        "codes": dict(codes),
        "rows": [
            {
                "match_number": row.get("match_number"),
                "nowscore_id": row.get("nowscore_id"),
                "sides": list(row.get("name_variant_sides") or []),
                "details": list(row.get("name_variant_details") or []),
            }
            for row in variant_rows
        ],
    }


def _timestamp_proof(rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    formal_rows = [row for row in rows if row.get("line_available")]
    response_before_kickoff_n = 0
    captured_equals_fetched_n = 0
    response_equals_observed_n = 0
    request_before_response_n = 0
    invalid_n = 0
    for row in formal_rows:
        kickoff = _parse_timestamp(row.get("kickoff_at"))
        request_started = _parse_timestamp(row.get("request_started_at"))
        response_at = _parse_timestamp(row.get("response_at"))
        observed_at = _parse_timestamp(row.get("observed_at"))
        captured_at = _parse_timestamp(row.get("captured_at"))
        fetched_at = _parse_timestamp(row.get("fetched_at"))
        if kickoff is None or response_at is None or captured_at is None or fetched_at is None:
            invalid_n += 1
            continue
        if response_at < kickoff:
            response_before_kickoff_n += 1
        if captured_at == fetched_at == response_at:
            captured_equals_fetched_n += 1
        if observed_at == response_at:
            response_equals_observed_n += 1
        if request_started is not None and request_started <= response_at:
            request_before_response_n += 1
    return {
        "observation_field": "response_at",
        "formal_capture_n": len(formal_rows),
        "response_before_kickoff_n": response_before_kickoff_n,
        "captured_at_equals_fetched_at_equals_response_at_n": captured_equals_fetched_n,
        "observed_at_equals_response_at_n": response_equals_observed_n,
        "request_started_at_before_or_at_response_at_n": request_before_response_n,
        "invalid_or_missing_n": invalid_n,
    }


def run_audit(
    *,
    universe_root: Path = UNIVERSE_ROOT,
    limit: int = DEFAULT_LIMIT,
) -> dict[str, Any]:
    business_date = resolve_current_business_date(universe_root)
    universe = load_prediction_universe(business_date, Path(universe_root)) or {}
    fixtures = [row for row in universe.get("fixtures") or [] if isinstance(row, dict)]
    bounded_limit = max(0, min(int(limit), DEFAULT_LIMIT))
    identity_groups: dict[tuple[str, ...], list[dict[str, Any]]] = {}
    id_groups: dict[str, list[dict[str, Any]]] = {}
    for fixture in fixtures:
        key = _identity_key(fixture)
        if key is not None:
            identity_groups.setdefault(key, []).append(fixture)
        provider_id = str(fixture.get("nowscoreId") or fixture.get("nowscore_id") or "").strip()
        if provider_id:
            id_groups.setdefault(provider_id, []).append(fixture)
    duplicate_identity_n = sum(max(0, len(rows) - 1) for rows in identity_groups.values())
    duplicate_nowscore_n = sum(max(0, len(rows) - 1) for rows in id_groups.values())

    rows: list[dict[str, Any]] = []
    abstain_reasons: Counter[str] = Counter()
    response_hashes: dict[str, str | None] = {}
    for index, fixture in enumerate(fixtures[:bounded_limit]):
        provider_id = str(fixture.get("nowscoreId") or fixture.get("nowscore_id") or "").strip()
        duplicate = (
            len(identity_groups.get(_identity_key(fixture) or (), [])) > 1
            or len(id_groups.get(provider_id, [])) > 1
        )
        if duplicate:
            capture = abstain_nowscore_jc_handicap_capture(
                fixture,
                "DUPLICATE_IDENTITY",
                reason_codes=["DUPLICATE_IDENTITY_KEY_OR_NOWSCORE_ID"],
            )
        else:
            trusted = trusted_nowscore_jc_fixture(fixture, fixture.get("nowscoreId") or fixture.get("nowscore_id"))
            try:
                capture = (
                    capture_nowscore_jc_handicap(fixture)
                    if trusted.get("trusted")
                    else abstain_nowscore_jc_handicap_capture(
                        fixture,
                        "FIXTURE_BINDING_UNVERIFIED",
                        reason_codes=list(trusted.get("reasons") or []),
                    )
                )
            except Exception as error:  # isolate one match from the live audit
                capture = abstain_nowscore_jc_handicap_capture(
                    fixture,
                    "JC_HANDICAP_AUDIT_EXCEPTION",
                    reason_codes=[type(error).__name__],
                )
        reason = capture.get("reason")
        if reason:
            abstain_reasons[str(reason)] += 1
        if provider_id:
            response_hashes[provider_id] = capture.get("response_sha256")
        identity_status = str(capture.get("identity_status") or "UNRESOLVED")
        row = {
            "fixture_index": index,
            "match_id": fixture.get("matchId") or fixture.get("match_id"),
            "match_number": fixture.get("matchNum") or fixture.get("match_num"),
            "nowscore_id": capture.get("nowscore_id") or provider_id or None,
            "page_http_status": capture.get("page_http_status"),
            "response_sha256": capture.get("response_sha256"),
            "content_sha256": capture.get("content_sha256"),
            "identity_status": identity_status,
            "binding_status": "EXACT" if capture.get("status") == "CAPTURED" else "UNRESOLVED",
            "official_row_n": int(capture.get("official_row_count") or 0),
            "capture_status": capture.get("status"),
            "line_available": capture.get("status") == "CAPTURED",
            "line": capture.get("line"),
            "home_team": capture.get("home_team"),
            "away_team": capture.get("away_team"),
            "kickoff_at": capture.get("kickoff_at"),
            "request_started_at": capture.get("request_started_at"),
            "response_at": capture.get("response_at"),
            "observed_at": capture.get("observed_at"),
            "fetched_at": capture.get("fetched_at"),
            "captured_at": capture.get("captured_at"),
            "page_identity": capture.get("page_identity") or {},
            "retry_count": capture.get("retry_count", 0),
            "fetch_error": capture.get("fetch_error"),
            "abstain_reason": reason,
            "reason_codes": list(capture.get("reason_codes") or []),
            "source_url": capture.get("source_url"),
            "name_diagnostics": list(capture.get("name_diagnostics") or []),
            "name_variant_sides": list(capture.get("name_variant_sides") or []),
            "name_variant_details": list(capture.get("name_variant_details") or []),
        }
        rows.append(row)

    attempted_n = len(rows)
    exact_n = sum(row["binding_status"] == "EXACT" for row in rows)
    conflict_n = sum(
        row["abstain_reason"] == "IDENTITY_CONFLICT"
        or any("CONFLICT" in str(reason) for reason in row["reason_codes"])
        for row in rows
    )
    ambiguous_n = sum(
        row["abstain_reason"] == "DUPLICATE_IDENTITY"
        or any("AMBIGU" in str(reason) for reason in row["reason_codes"])
        for row in rows
    )
    unmatched_n = sum(
        row["binding_status"] != "EXACT"
        and not row["abstain_reason"] in {"DUPLICATE_IDENTITY", "IDENTITY_CONFLICT"}
        and not any("CONFLICT" in str(reason) for reason in row["reason_codes"])
        for row in rows
    )
    duplicate_n = duplicate_identity_n + duplicate_nowscore_n
    line_available_n = sum(bool(row["line_available"]) for row in rows)
    if conflict_n:
        delivery_decision = "FAIL_CLOSED"
        current_source_status = "CONFLICT"
    elif line_available_n == attempted_n and attempted_n == len(fixtures) and attempted_n > 0:
        delivery_decision = "JC_HANDICAP_NOWSCORE_FORMAL_TRUTH_READY"
        current_source_status = "READY"
    elif line_available_n > 0:
        delivery_decision = "JC_HANDICAP_NOWSCORE_FORMAL_TRUTH_PARTIAL"
        current_source_status = "PARTIAL"
    else:
        delivery_decision = "JC_HANDICAP_NOWSCORE_FORMAL_TRUTH_PARTIAL"
        current_source_status = "NOT_EXECUTABLE"
    return {
        "contract_version": AUDIT_CONTRACT_VERSION,
        "audit_scope": "current_authoritative_prediction_universe_nowscore_jc_analysis",
        "runner": {
            "github_actions": os.environ.get("GITHUB_ACTIONS") == "true",
            "runner_os": platform.platform(),
            "github_run_id": os.environ.get("GITHUB_RUN_ID"),
        },
        "current_business_date": business_date,
        "prediction_universe_status": universe.get("status"),
        "prediction_universe_source": universe.get("source"),
        "jc_fixture_n": len(fixtures),
        "attempted_fixture_n": attempted_n,
        "bounded_limit": bounded_limit,
        "page_http_status_counts": _status_counter(rows),
        "current_source_status": current_source_status,
        "binding_funnel": {
            "jc_fixture_n": len(fixtures),
            "attempted_n": attempted_n,
            "exact_n": exact_n,
            "ambiguous_n": ambiguous_n,
            "unmatched_n": unmatched_n,
            "duplicate_n": duplicate_n,
            "conflict_n": conflict_n,
        },
        "official_row_n": sum(int(row["official_row_n"]) for row in rows),
        "line_coverage": {
            "available_n": line_available_n,
            "attempted_n": attempted_n,
            "ratio": round(line_available_n / attempted_n, 6) if attempted_n else None,
            "line_perspective": "home",
            "integer_only": True,
            "source_surface": "https://m.nowscore.com/Analy/Analysis/{nowscore_id}.htm",
        },
        "odds_coverage": {
            "available_n": 0,
            "baseline_status": "NOT_AVAILABLE",
            "reason": "QUOTE_TIME_SEMANTICS_NOT_PROVEN",
            "derived_from_asian_handicap": False,
        },
        "abstain_reasons": dict(abstain_reasons),
        "name_diagnostics": _name_diagnostics(rows),
        "timestamp_proof": _timestamp_proof(rows),
        "response_hashes": response_hashes,
        "rows": rows,
        "delivery_decision": delivery_decision,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    args = parser.parse_args()
    result = run_audit(limit=args.limit)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in result.items() if key not in {"rows", "response_hashes"}}, ensure_ascii=False, sort_keys=True))
    return 1 if result["delivery_decision"] == "FAIL_CLOSED" else 0


if __name__ == "__main__":
    raise SystemExit(main())
