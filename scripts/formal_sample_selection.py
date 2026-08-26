"""Shared deterministic formal-sample selection and immutable-identity checks."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any


def strict_aware_at(value: Any) -> datetime | None:
    """Parse an explicitly timezone-aware timestamp; missing/naive values fail closed."""
    if value in (None, ""):
        return None
    try:
        text = str(value).strip().replace("Z", "+00:00")
        parsed = datetime.fromisoformat(text)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def canonical_match_key(record: dict[str, Any]) -> str | None:
    """Return a stable persisted match identity; never fall back to prediction_id."""
    for field in ("match_key", "canonical_match_key", "match_id"):
        value = str(record.get(field) or "").strip()
        if value:
            return value
    identity = record.get("match_identity")
    if isinstance(identity, dict):
        for field in ("match_key", "canonical_match_id", "match_id"):
            value = str(identity.get(field) or "").strip()
            if value:
                return value
    return None


def freeze_timestamp(record: dict[str, Any]) -> tuple[datetime | None, str | None]:
    """Use the strongest persisted freeze timestamp without inventing a checkpoint."""
    for field in ("freeze_created_at", "freeze_at", "prediction_created_at", "created_at"):
        if record.get(field) not in (None, ""):
            return strict_aware_at(record.get(field)), field
    return None, None


def snapshot_identity(record: dict[str, Any]) -> tuple[str, str] | None:
    digest = str(
        record.get("canonical_model_input_sha256")
        or record.get("input_sha256")
        or ""
    ).strip()
    if digest:
        return ("sha256", digest)
    ref = str(record.get("model_input_snapshot_ref") or "").strip()
    if ref:
        return ("ref", ref)
    return None


def checkpoint_identity(record: dict[str, Any]) -> tuple[str, str]:
    # checkpoint_captured_at is a capture timestamp, not a checkpoint identity;
    # missing stage is an internal sentinel, not a fabricated checkpoint label.
    return (
        str(record.get("checkpoint_stage") or "<missing-checkpoint-stage>").strip(),
        str(record.get("checkpoint_target_at") or "").strip(),
    )


def frozen_prediction_identity(formal_records: list[dict[str, Any]]) -> dict[str, Any]:
    """Detect immutable duplicate identities, not legal evolving pre-match versions."""
    duplicate_keys: dict[str, list[str]] = {}
    by_prediction_id: defaultdict[str, list[str]] = defaultdict(list)
    by_snapshot_match_checkpoint: defaultdict[tuple[Any, ...], list[str]] = defaultdict(list)
    missing_identity_count = 0
    for index, record in enumerate(formal_records):
        prediction_id = str(record.get("prediction_id") or f"<row-{index}>").strip()
        if record.get("prediction_id") not in (None, ""):
            by_prediction_id[str(record["prediction_id"]).strip()].append(prediction_id)
        snapshot = snapshot_identity(record)
        if snapshot is None:
            missing_identity_count += 1
        else:
            match_key = canonical_match_key(record)
            if match_key is not None:
                by_snapshot_match_checkpoint[
                    (match_key, snapshot, checkpoint_identity(record))
                ].append(prediction_id)

    for prediction_id, rows in by_prediction_id.items():
        if len(rows) > 1:
            duplicate_keys[f"prediction_id:{prediction_id}"] = rows
    for identity, rows in by_snapshot_match_checkpoint.items():
        if len(rows) > 1:
            match_key, snapshot, checkpoint = identity
            duplicate_keys[
                f"snapshot_checkpoint:{match_key!r}:{snapshot!r}:{checkpoint!r}"
            ] = rows

    historical_groups: defaultdict[str, int] = defaultdict(int)
    missing_match_identity_count = 0
    for record in formal_records:
        match_key = canonical_match_key(record)
        if match_key is None:
            missing_match_identity_count += 1
            continue
        historical_groups[match_key] += 1
    versioned_groups = {
        key: count for key, count in historical_groups.items() if count > 1
    }
    duplicate_record_count = sum(max(0, len(rows) - 1) for rows in duplicate_keys.values())
    return {
        "duplicate_group_count": len(duplicate_keys),
        "duplicate_record_count": duplicate_record_count,
        "same_prediction_id_duplicate_count": sum(
            1 for key in duplicate_keys if key.startswith("prediction_id:")
        ),
        "same_snapshot_checkpoint_duplicate_count": sum(
            1 for key in duplicate_keys if key.startswith("snapshot_checkpoint:")
        ),
        "historical_version_group_count": len(versioned_groups),
        "historical_version_group_keys": sorted(versioned_groups),
        "missing_match_identity_count": missing_match_identity_count,
        "missing_immutable_identity_count": missing_identity_count,
    }


def canonicalize_formal_records(formal_records: list[dict[str, Any]]) -> dict[str, Any]:
    """Select one latest legal pre-kickoff record per match without deleting history."""
    groups: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in formal_records:
        if isinstance(record, dict):
            match_key = canonical_match_key(record)
            if match_key is not None:
                groups[match_key].append(record)

    representatives: list[dict[str, Any]] = []
    invalid_records: list[dict[str, Any]] = []
    superseded_count = 0
    for record in formal_records:
        if canonical_match_key(record) is None:
            invalid_records.append({
                "prediction_id": str(record.get("prediction_id") or ""),
                "match_key": None,
                "reason": "MISSING_MATCH_IDENTITY",
            })
    for match_key in sorted(groups):
        legal: list[tuple[datetime, str, dict[str, Any]]] = []
        for record in groups[match_key]:
            kickoff = strict_aware_at(record.get("kickoff_at"))
            frozen_at, frozen_field = freeze_timestamp(record)
            if kickoff is None:
                invalid_records.append({
                    "prediction_id": str(record.get("prediction_id") or ""),
                    "match_key": match_key,
                    "reason": "MISSING_OR_INVALID_TIMEZONE_AWARE_KICKOFF",
                })
                continue
            if frozen_at is None:
                invalid_records.append({
                    "prediction_id": str(record.get("prediction_id") or ""),
                    "match_key": match_key,
                    "reason": f"MISSING_OR_INVALID_TIMEZONE_AWARE_{(frozen_field or 'FREEZE_TIME').upper()}",
                })
                continue
            if frozen_at >= kickoff:
                invalid_records.append({
                    "prediction_id": str(record.get("prediction_id") or ""),
                    "match_key": match_key,
                    "reason": "FREEZE_NOT_STRICTLY_PRE_KICKOFF",
                })
                continue
            prediction_id = str(record.get("prediction_id") or "")
            legal.append((frozen_at, prediction_id, record))
        if not legal:
            continue
        legal.sort(key=lambda row: (row[0], row[1]))
        representatives.append(legal[-1][2])
        superseded_count += len(legal) - 1

    identity = frozen_prediction_identity(formal_records)
    exclusion_counts = Counter(row["reason"] for row in invalid_records)
    invalid_time_count = sum(
        count
        for reason, count in exclusion_counts.items()
        if "TIME" in reason or "KICKOFF" in reason
    )
    return {
        "records": representatives,
        "selection_policy": (
            "latest_legal_pre_kickoff_frozen_record_by_freeze_created_at/freeze_at; "
            "fallback prediction_created_at/created_at; tie-break prediction_id"
        ),
        "checkpoint_semantics": "checkpoint labels are not assigned by canonical selection",
        "raw_formal_record_count": len(formal_records),
        "raw_match_count": len(groups),
        "canonical_match_count": len(representatives),
        "superseded_historical_version_count": superseded_count,
        "versioned_record_count": superseded_count,
        "canonical_excluded_record_count": len(invalid_records),
        "canonical_exclusion_reason_counts": dict(sorted(exclusion_counts.items())),
        "invalid_time_record_count": invalid_time_count,
        "invalid_time_records": [
            row for row in invalid_records
            if "TIME" in row["reason"] or "KICKOFF" in row["reason"]
        ],
        "frozen_prediction_identity": identity,
    }
