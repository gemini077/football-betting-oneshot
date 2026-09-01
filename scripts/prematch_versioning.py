"""Read-only selection helpers for immutable pre-match prediction versions."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable


POSTMATCH_FIELDS = frozenset({
    "actual_score",
    "postmatch_evidence",
    "result",
    "settlement",
    "settlement_status",
    "verified_at",
})


def _parse_timestamp(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _text(value: Any) -> str:
    return str(value or "").strip()


def _normalise_text(value: Any) -> str:
    return " ".join(_text(value).casefold().split())


def _first(source: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = source.get(key)
        if value not in (None, ""):
            return value
    return None


def _identity(record: dict[str, Any]) -> dict[str, Any]:
    nested = record.get("match_identity")
    nested = nested if isinstance(nested, dict) else {}
    return {
        "job_id": _first(record, "job_id") or _first(nested, "job_id"),
        "match_id": _first(record, "match_id", "live_match_id") or _first(nested, "match_id", "live_match_id"),
        "match_key": _first(record, "match_key", "canonical_match_id") or _first(nested, "match_key", "canonical_match_id"),
        "home": _first(record, "home", "home_team") or _first(nested, "home", "home_team"),
        "away": _first(record, "away", "away_team") or _first(nested, "away", "away_team"),
        "kickoff_at": _first(record, "kickoff_at", "kickoff_local") or _first(nested, "kickoff_at", "kickoff_local"),
    }


def _expected_identity(identity: dict[str, Any]) -> dict[str, Any]:
    return {
        "job_id": _first(identity, "job_id"),
        "match_id": _first(identity, "match_id", "live_match_id"),
        "match_key": _first(identity, "match_key", "canonical_match_id"),
        "home": _first(identity, "home", "home_team"),
        "away": _first(identity, "away", "away_team"),
        "kickoff_at": _first(identity, "kickoff_at", "kickoff_local", "kickoff"),
    }


def _associated(record_identity: dict[str, Any], expected: dict[str, Any]) -> bool:
    for field in ("job_id", "match_id", "match_key"):
        actual = _text(record_identity.get(field))
        wanted = _text(expected.get(field))
        if actual and wanted and actual == wanted:
            return True
    actual_kickoff = _parse_timestamp(record_identity.get("kickoff_at"))
    expected_kickoff = _parse_timestamp(expected.get("kickoff_at"))
    return bool(
        actual_kickoff
        and expected_kickoff
        and actual_kickoff == expected_kickoff
        and _normalise_text(record_identity.get("home")) == _normalise_text(expected.get("home"))
        and _normalise_text(record_identity.get("away")) == _normalise_text(expected.get("away"))
    )


def _identity_conflicts(record_identity: dict[str, Any], expected: dict[str, Any]) -> bool:
    for field in ("job_id", "match_id", "match_key"):
        actual = _text(record_identity.get(field))
        wanted = _text(expected.get(field))
        if actual and wanted and actual != wanted:
            return True
    for field in ("home", "away"):
        actual = _normalise_text(record_identity.get(field))
        wanted = _normalise_text(expected.get(field))
        if actual and wanted and actual != wanted:
            return True
    actual_kickoff = _parse_timestamp(record_identity.get("kickoff_at"))
    expected_kickoff = _parse_timestamp(expected.get("kickoff_at"))
    return bool(actual_kickoff and expected_kickoff and actual_kickoff != expected_kickoff)


def _contains_postmatch_field(value: Any) -> bool:
    if isinstance(value, dict):
        if any(key in POSTMATCH_FIELDS for key in value):
            return True
        return any(_contains_postmatch_field(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_postmatch_field(item) for item in value)
    return False


def _is_formal_prematch(record: dict[str, Any], expected: dict[str, Any]) -> bool:
    if not record.get("prediction_id"):
        return False
    if record.get("prediction_status") != "formal":
        return False
    if record.get("model_role") != "champion":
        return False
    if record.get("formal_eligible") is not True or record.get("model_formal_eligible") is not True:
        return False
    if record.get("prediction_variant") != "model_only" or record.get("manual_override") is True:
        return False
    if _contains_postmatch_field(record):
        return False

    identity = _identity(record)
    if not all(identity.get(field) not in (None, "") for field in ("home", "away", "kickoff_at")):
        return False
    kickoff = _parse_timestamp(identity.get("kickoff_at"))
    expected_kickoff = _parse_timestamp(expected.get("kickoff_at"))
    if kickoff is None or expected_kickoff is None or kickoff != expected_kickoff:
        return False

    source_cutoff = _parse_timestamp(record.get("source_cutoff_at"))
    prediction_created = _parse_timestamp(record.get("prediction_created_at"))
    freeze_created = _parse_timestamp(record.get("freeze_created_at"))
    if not source_cutoff or not prediction_created or not freeze_created:
        return False
    # The source cutoff and both creation points must be strictly prematch.
    # The source must also precede the prediction that consumed it.
    return (
        source_cutoff < kickoff
        and prediction_created < kickoff
        and freeze_created < kickoff
        and source_cutoff < prediction_created <= freeze_created
    )


def select_latest_legal_prematch(
    records: Iterable[dict[str, Any]],
    *,
    identity: dict[str, Any],
) -> dict[str, Any]:
    """Select the latest legal immutable version for one match identity.

    The selector never mutates records and never treats a post-kickoff record
    as a replacement for a prematch version.  Identity conflicts and equal
    final chronology fail closed rather than being resolved by an ID tie-break.
    """
    expected = _expected_identity(identity)
    associated: list[dict[str, Any]] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        record_identity = _identity(record)
        if _associated(record_identity, expected):
            associated.append(record)

    if any(_identity_conflicts(_identity(record), expected) for record in associated):
        return {
            "status": "IDENTITY_CONFLICT",
            "reason": "MATCH_IDENTITY_CONFLICT",
            "selected_record": None,
            "selected_prediction_id": None,
            "selected_freeze_created_at": None,
            "selected_source_cutoff_at": None,
            "candidate_count": 0,
            "superseded_count": 0,
        }

    legal = [record for record in associated if _is_formal_prematch(record, expected)]

    def sort_key(record: dict[str, Any]) -> tuple[datetime, datetime, datetime, str]:
        return (
            _parse_timestamp(record.get("source_cutoff_at")) or datetime.min.replace(tzinfo=timezone.utc),
            _parse_timestamp(record.get("freeze_created_at")) or datetime.min.replace(tzinfo=timezone.utc),
            _parse_timestamp(record.get("prediction_created_at")) or datetime.min.replace(tzinfo=timezone.utc),
            _text(record.get("prediction_id")),
        )

    legal.sort(key=sort_key, reverse=True)
    if len(legal) >= 2 and sort_key(legal[0])[:3] == sort_key(legal[1])[:3]:
        return {
            "status": "AMBIGUOUS_FINAL_CHRONOLOGY",
            "reason": "EQUAL_FINAL_PREMATCH_CHRONOLOGY",
            "selected_record": None,
            "selected_prediction_id": None,
            "selected_freeze_created_at": None,
            "selected_source_cutoff_at": None,
            "candidate_count": len(legal),
            "superseded_count": 0,
        }
    selected = legal[0] if legal else None
    if selected is None:
        return {
            "status": "NO_LEGAL_PREMATCH_VERSION",
            "reason": "NO_FORMAL_PREMATCH_VERSION_BEFORE_KICKOFF",
            "selected_record": None,
            "selected_prediction_id": None,
            "selected_freeze_created_at": None,
            "selected_source_cutoff_at": None,
            "candidate_count": 0,
            "superseded_count": 0,
        }

    return {
        "status": "SELECTED",
        "reason": "LATEST_LEGAL_PREMATCH_VERSION",
        "selected_record": selected,
        "selected_prediction_id": selected.get("prediction_id"),
        "selected_freeze_created_at": selected.get("freeze_created_at"),
        "selected_source_cutoff_at": selected.get("source_cutoff_at"),
        "candidate_count": len(legal),
        "superseded_count": max(0, len(legal) - 1),
    }
