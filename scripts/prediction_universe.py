"""Persistence boundary for the daily Prediction Universe."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    from match_identity import canonical_match_id
except ImportError:  # package imports used by tests
    from scripts.match_identity import canonical_match_id


PROJECT_ROOT = Path(__file__).resolve().parents[1]
UNIVERSE_ROOT = PROJECT_ROOT / "data" / "prediction_universe"
ALLOWED_SOURCES = {"sporttery.cn", "trade.500.com"}
VALID_SNAPSHOT_STATUSES = {"READY", "EMPTY_CONFIRMED"}
SCHEMA_VERSION = "1.0"

_FIELD_ALIASES = {
    "matchId": ("matchId", "match_id", "id"),
    "matchNum": ("matchNum", "match_num"),
    "businessDate": ("businessDate", "business_date"),
    "matchDate": ("matchDate", "match_date"),
    "matchTime": ("matchTime", "match_time"),
    "league": ("league", "competition"),
    "homeTeam": ("homeTeam", "home_team", "home"),
    "awayTeam": ("awayTeam", "away_team", "away"),
    "nowscoreId": ("nowscoreId", "nowscore_id"),
    "nowscoreMatchStatus": ("nowscoreMatchStatus", "nowscore_match_status"),
    "nowscoreMatchConfidence": ("nowscoreMatchConfidence", "nowscore_match_confidence"),
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


def _is_authorized_full_schedule_payload(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    if str(payload.get("source") or "") not in ALLOWED_SOURCES:
        return False
    if _is_true(payload.get("analysis_input_only")):
        return False
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
