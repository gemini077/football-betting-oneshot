"""Central data-layer quality grades and class-specific freshness evaluation."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


DEFAULT_RULES_PATH = Path(__file__).resolve().parents[2] / "config" / "football_data_quality.json"


def load_quality_rules(path: str | Path = DEFAULT_RULES_PATH) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as handle:
        return json.load(handle)


def assess_quality(flags: Mapping[str, Any], rules: Mapping[str, Any] | None = None) -> str:
    """Return an A/B/C/D data-quality grade from explicit evidence flags."""

    config = rules or load_quality_rules()
    grades = config.get("grades", {})
    d_rules = grades.get("D", {})
    c_rules = grades.get("C", {})
    if any(bool(flags.get(name)) for name in d_rules.get("disqualifiers", [])):
        return "D"
    if any(bool(flags.get(name)) for name in c_rules.get("disqualifiers", [])):
        return "C"
    if all(bool(flags.get(name)) for name in grades.get("A", {}).get("requires", [])):
        return "A"
    if all(bool(flags.get(name)) for name in grades.get("B", {}).get("requires", [])):
        return "B"
    return "C"


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _freshness_policy(config: Mapping[str, Any], data_class: str) -> dict[str, Any]:
    policy = config.get("freshness_policies", {}).get(data_class)
    if isinstance(policy, Mapping):
        return dict(policy)
    ttl = config.get("freshness_ttl_seconds", {}).get(data_class)
    return {
        "requires_source_fact_time": data_class != "slow_changing",
        "allow_capture_time_fallback": data_class == "slow_changing",
        "ttl_seconds": ttl,
    }


def freshness_status(
    *,
    captured_at: str | None,
    source_as_of_at: str | None,
    data_class: str,
    now: datetime | None = None,
    invalidated: bool = False,
    rules: Mapping[str, Any] | None = None,
    source_timestamp: str | None = None,
    allow_capture_time_fallback: bool | None = None,
) -> dict[str, Any]:
    """Calculate freshness using fact time, never silently using capture time.

    ``source_timestamp`` is used first for availability records.  For lineup
    and other source observations, ``source_as_of_at`` is the fact time.  A
    capture-time fallback is permitted only by an explicit data-class policy.
    """

    config = rules or load_quality_rules()
    policy = _freshness_policy(config, data_class)
    ttl = policy.get("ttl_seconds")
    fallback = policy.get("allow_capture_time_fallback", False) if allow_capture_time_fallback is None else allow_capture_time_fallback
    reference_value = source_timestamp if source_timestamp is not None else source_as_of_at
    reference = _parse_timestamp(reference_value)
    reference_kind = "source_timestamp" if source_timestamp is not None else "source_as_of_at" if source_as_of_at is not None else None

    result: dict[str, Any] = {
        "state": "unknown",
        "age_seconds": None,
        "ttl_seconds": ttl,
        "reference": reference_kind,
    }
    if reference_value is not None and reference is None:
        result.update({"reason": "invalid_source_fact_time", "timestamp_conflict": True})
        return result
    if reference is None and fallback:
        reference = _parse_timestamp(captured_at)
        if reference is not None:
            reference_kind = "captured_at"
            result["reference"] = reference_kind
    if reference is None:
        result["reason"] = "source_fact_time_missing" if policy.get("requires_source_fact_time", True) else "reference_time_missing"
        return result

    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    delta = (current - reference).total_seconds()
    tolerance = int(config.get("clock_skew_tolerance_seconds", 300))
    if delta < -tolerance:
        result.update({"reference": reference_kind, "reason": "future_source_fact_time", "timestamp_conflict": True})
        return result
    clock_skew_adjusted = delta < 0
    age_seconds = max(0, int(delta))
    result["age_seconds"] = age_seconds
    if clock_skew_adjusted:
        result["clock_skew_adjusted"] = True
    if invalidated and data_class == "historical_immutable":
        result["state"] = "stale"
        result["reason"] = "explicitly_invalidated"
    elif ttl is None:
        result["state"] = "fresh"
    else:
        result["state"] = "fresh" if age_seconds <= int(ttl) else "stale"
    return result


def _infer_record_type(record: Mapping[str, Any], record_type: str | None) -> str:
    if record_type:
        return record_type
    if "players" in record:
        return "lineup_snapshot"
    if "source_timestamp" in record and "status" in record:
        return "availability_snapshot"
    if "metric_definition" in record:
        return "xg_snapshot"
    if record.get("contract_version") == "historical_match_result.v1":
        return "historical_match_result"
    if "window_type" in record and "metrics" in record:
        return "team_form_snapshot"
    if "canonical_name" in record:
        return "team_identity"
    return "observation"


def _material_flags(record: Mapping[str, Any], record_type: str) -> dict[str, bool]:
    flags = {"material_metric_missing": False, "sample_complete": True}
    if record_type == "team_form_snapshot":
        metrics = record.get("metrics")
        matches = record.get("matches", (record.get("sample_size") or {}).get("matches"))
        flags["material_metric_missing"] = not (
            isinstance(metrics, Mapping)
            and metrics.get("goals_for") is not None
            and metrics.get("goals_against") is not None
            and record.get("window_type")
            and matches is not None
        )
        flags["sample_complete"] = not flags["material_metric_missing"]
    elif record_type == "xg_snapshot":
        flags["material_metric_missing"] = not bool(record.get("metric_definition")) or record.get("value") is None
        flags["sample_complete"] = not flags["material_metric_missing"]
    elif record_type == "lineup_snapshot":
        coverage = record.get("player_identity_coverage")
        ratio = coverage.get("coverage_ratio") if isinstance(coverage, Mapping) else None
        flags["material_metric_missing"] = not isinstance(coverage, Mapping) or ratio is None or ratio < 1
        flags["sample_complete"] = not flags["material_metric_missing"]
    elif record_type == "availability_snapshot":
        flags["material_metric_missing"] = not bool(record.get("canonical_player_id")) or not record.get("source_timestamp") or not bool(record.get("evidence"))
        flags["sample_complete"] = not flags["material_metric_missing"]
    elif record_type == "historical_match_result":
        flags["material_metric_missing"] = not all(
            record.get(field) not in (None, "")
            for field in ("kickoff_at", "home_team_id", "away_team_id", "home_goals", "away_goals")
        )
        flags["sample_complete"] = not flags["material_metric_missing"]
    elif record_type == "team_strength_snapshot":
        metrics = record.get("metrics")
        flags["material_metric_missing"] = not (
            isinstance(metrics, Mapping)
            and record.get("matches", 0) > 0
            and metrics.get("goals_for_per_match") is not None
            and metrics.get("goals_against_per_match") is not None
            and record.get("window_type")
        )
        flags["sample_complete"] = not flags["material_metric_missing"]
    return flags


def evaluate_record(
    record: Mapping[str, Any],
    *,
    data_class: str,
    now: datetime | None = None,
    rules: Mapping[str, Any] | None = None,
    record_type: str | None = None,
) -> dict[str, Any]:
    """Evaluate one normalized record; adapters and tests share this path."""

    kind = _infer_record_type(record, record_type)
    provenance = record.get("provenance") if isinstance(record.get("provenance"), Mapping) else {}
    source_as_of = record.get("source_as_of_at") or provenance.get("source_as_of_at")
    source_timestamp = record.get("source_timestamp") if kind == "availability_snapshot" else None
    if kind == "availability_snapshot":
        source_as_of = None
    freshness = freshness_status(
        captured_at=record.get("captured_at") or provenance.get("captured_at"),
        source_as_of_at=source_as_of,
        source_timestamp=source_timestamp,
        data_class=data_class,
        now=now,
        rules=rules,
    )
    material = _material_flags(record, kind)
    sample_size = record.get("sample_size") if isinstance(record.get("sample_size"), Mapping) else {}
    flags: dict[str, Any] = {
        "identity_confirmed": bool(record.get("canonical_entity_id")),
        "timestamp_known": freshness.get("reference") is not None and not freshness.get("timestamp_conflict"),
        "source_fact_timestamp_known": freshness.get("reference") in {"source_as_of_at", "source_timestamp"} and not freshness.get("timestamp_conflict"),
        "reliable_source": (
            provenance.get("source_reliable") is True
            and bool(provenance.get("provider"))
            and bool(provenance.get("source"))
        ),
        "sample_complete": material["sample_complete"] and sample_size.get("matches") is not None if kind not in {"lineup_snapshot", "availability_snapshot"} else material["sample_complete"],
        "material_metric_missing": material["material_metric_missing"],
        "source_fact_timestamp_missing": freshness.get("reason") == "source_fact_time_missing",
        "timestamp_conflict": bool(freshness.get("timestamp_conflict")),
        "synthetic_observation": bool(provenance.get("synthetic", False)),
        "identity_conflict": bool(record.get("identity_conflict")),
        "source_conflict": bool(record.get("source_conflict")),
        "fallback_provider": bool(record.get("fallback_provider")),
    }
    grade = assess_quality(flags, rules)
    return {"data_quality_grade": grade, "freshness": freshness, "flags": flags, "record_type": kind}


def finalize_record_quality(
    record: dict[str, Any],
    *,
    data_class: str,
    now: datetime | None = None,
    rules: Mapping[str, Any] | None = None,
    record_type: str | None = None,
) -> dict[str, Any]:
    """Mutate a normalized record through the same evaluator used for audits."""

    result = evaluate_record(record, data_class=data_class, now=now, rules=rules, record_type=record_type)
    record["quality"] = result["data_quality_grade"]
    record["freshness"] = result["freshness"]
    return record
