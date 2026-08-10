"""Data-layer quality grades and class-specific freshness evaluation."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


DEFAULT_RULES_PATH = Path(__file__).resolve().parents[2] / "config" / "football_data_quality.json"


def load_quality_rules(path: str | Path = DEFAULT_RULES_PATH) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as handle:
        return json.load(handle)


def assess_quality(
    flags: Mapping[str, bool],
    *,
    rules: Mapping[str, Any] | None = None,
) -> str:
    """Return an A/B/C/D data-quality grade from explicit evidence flags."""

    config = rules or load_quality_rules()
    grades = config["grades"]
    for disqualifier in grades["D"].get("disqualifiers", []):
        if flags.get(disqualifier, False):
            return "D"
    for disqualifier in grades["C"].get("disqualifiers", []):
        if flags.get(disqualifier, False):
            return "C"
    if all(flags.get(requirement, False) for requirement in grades["A"].get("requires", [])):
        return "A"
    if all(flags.get(requirement, False) for requirement in grades["B"].get("requires", [])):
        return "B"
    return "C"


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def freshness_status(
    *,
    captured_at: str | None,
    source_as_of_at: str | None,
    data_class: str,
    now: datetime | None = None,
    invalidated: bool = False,
    rules: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Calculate freshness without imposing one TTL on every data class."""

    config = rules or load_quality_rules()
    ttl = config.get("freshness_ttl_seconds", {}).get(data_class)
    reference = _parse_timestamp(source_as_of_at) or _parse_timestamp(captured_at)
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    current = current.astimezone(timezone.utc)

    if reference is None:
        return {"state": "unknown", "age_seconds": None, "ttl_seconds": ttl}
    age_seconds = max(0, int((current - reference).total_seconds()))
    if data_class == "historical_immutable":
        state = "stale" if invalidated else "fresh"
    elif ttl is None or not isinstance(ttl, int):
        state = "unknown"
    else:
        state = "fresh" if age_seconds <= ttl else "stale"
    return {"state": state, "age_seconds": age_seconds, "ttl_seconds": ttl}


def evaluate_record(
    record: Mapping[str, Any],
    *,
    data_class: str,
    now: datetime | None = None,
    source_reliable: bool = True,
    sample_complete: bool | None = None,
    conflicts: Mapping[str, bool] | None = None,
) -> dict[str, Any]:
    """Evaluate an existing normalized record without mutating it."""

    provenance = record.get("provenance") if isinstance(record.get("provenance"), Mapping) else {}
    sample_size = record.get("sample_size") if isinstance(record.get("sample_size"), Mapping) else {}
    if sample_complete is None:
        sample_complete = sample_size.get("matches") is not None
    conflict_flags = dict(conflicts or {})
    flags = {
        "identity_confirmed": bool(record.get("canonical_entity_id")),
        "timestamp_known": bool(_parse_timestamp(record.get("captured_at")) or _parse_timestamp(provenance.get("captured_at"))),
        "reliable_source": source_reliable,
        "sample_complete": bool(sample_complete),
        "material_metric_missing": bool(record.get("material_metric_missing", False)),
        **conflict_flags,
    }
    grade = assess_quality(flags)
    freshness = freshness_status(
        captured_at=record.get("captured_at"),
        source_as_of_at=record.get("source_as_of_at") or provenance.get("source_as_of_at"),
        data_class=data_class,
        now=now,
    )
    return {"data_quality_grade": grade, "freshness": freshness, "flags": flags}
