"""Competition-observation and historical-result coverage diagnostics."""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable, Mapping


STATUSES = frozenset({"SUPPORTED", "PARTIAL", "MISSING", "UNVERIFIED"})
SOURCE_COMPLETENESS_STATUSES = frozenset({"COMPLETE", "PARTIAL", "IN_PROGRESS", "UNKNOWN"})


def _status(value: Any) -> str:
    text = str(value or "UNVERIFIED").upper()
    return text if text in STATUSES else "UNVERIFIED"


def classify_source_completeness(
    *,
    listed_match_count: int | None,
    parsed_result_count: int | None,
    season_status: str | None,
    minimum_completion_ratio: float = 1.0,
) -> dict[str, Any]:
    """Classify a captured source without treating incomplete seasons as supported."""

    listed = int(listed_match_count or 0)
    parsed = int(parsed_result_count or 0)
    ratio = parsed / listed if listed else None
    normalized_season_status = str(season_status or "unknown").casefold()
    if ratio is None:
        completeness = "UNKNOWN"
        coverage = "UNVERIFIED"
    elif normalized_season_status in {"in_progress", "active", "current"}:
        completeness = "IN_PROGRESS"
        coverage = "SUPPORTED" if ratio >= minimum_completion_ratio else "PARTIAL"
    elif normalized_season_status in {"completed", "complete", "ended"}:
        completeness = "COMPLETE" if ratio >= minimum_completion_ratio else "PARTIAL"
        coverage = "SUPPORTED" if completeness == "COMPLETE" else "PARTIAL"
    else:
        completeness = "UNKNOWN"
        coverage = "UNVERIFIED"
    return {
        "result_completion_ratio": ratio,
        "source_completeness_status": completeness,
        "result_coverage": coverage,
    }


def build_coverage_registry(
    *,
    observed: Iterable[Mapping[str, Any]],
    entries: Iterable[Mapping[str, Any]],
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Merge bounded project observations with reviewed coverage declarations.

    ``source_record_count`` describes imported source volume only.  It is never
    used as a proxy for project demand; that comes from project analysis and
    current-match metadata.
    """

    grouped: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "raw_names": set(),
            "project_analysis_count": 0,
            "analysis_count_30d": 0,
            "analysis_count_90d": 0,
            "analysis_count_all_recoverable": 0,
            "source_record_count": 0,
            "current_match_count": 0,
            "resolved_match_count": 0,
            "unresolved_match_count": 0,
            "provider_competition_ids": set(),
        }
    )
    for row in observed:
        key = str(row.get("competition_key") or row.get("raw_name") or "unresolved")
        bucket = grouped[key]
        if row.get("raw_name"):
            bucket["raw_names"].add(str(row["raw_name"]))
        explicit_project_usage = any(key in row for key in ("project_analysis_count", "analysis_count_30d", "analysis_count_90d"))
        bucket["project_analysis_count"] += int(row.get("project_analysis_count") or 0)
        bucket["analysis_count_30d"] += int(row.get("analysis_count_30d") or 0)
        bucket["analysis_count_90d"] += int(row.get("analysis_count_90d") or 0)
        bucket["analysis_count_all_recoverable"] += int(row.get("analysis_count_all_recoverable") or 0)
        bucket["source_record_count"] += int(row.get("source_record_count") or (row.get("observed_count") or 0))
        if not explicit_project_usage and row.get("current_match_count"):
            bucket["project_analysis_count"] += int(row.get("current_match_count") or 0)
        bucket["current_match_count"] += int(row.get("current_match_count") or 0)
        bucket["resolved_match_count"] += int(row.get("resolved_match_count") or 0)
        bucket["unresolved_match_count"] += int(row.get("unresolved_match_count") or 0)
        if row.get("provider_competition_id"):
            bucket["provider_competition_ids"].add(str(row["provider_competition_id"]))

    by_key: dict[str, dict[str, Any]] = {}
    for raw in entries:
        row = dict(raw)
        key = str(row.get("competition_key") or row.get("canonical_competition_id") or row.get("name") or "unresolved")
        row["competition_key"] = key
        row["result_coverage"] = _status(row.get("result_coverage"))
        row["current_season_coverage"] = _status(row.get("current_season_coverage"))
        row.setdefault("project_analysis_count", 0)
        row.setdefault("analysis_count_30d", 0)
        row.setdefault("analysis_count_90d", 0)
        row.setdefault("analysis_count_all_recoverable", 0)
        row.setdefault("source_record_count", 0)
        row.setdefault("current_match_count", 0)
        row.setdefault("resolved_match_count", 0)
        row.setdefault("unresolved_match_count", 0)
        by_key[key] = row

    for key, bucket in grouped.items():
        row = by_key.setdefault(
            key,
            {
                "competition_key": key,
                "canonical_competition_id": None,
                "name": next(iter(bucket["raw_names"]), key),
                "country": None,
                "entity_type": "club",
                "competition_type": "unknown",
                "historical_result_sources": [],
                "current_match_sources": [],
                "result_coverage": "UNVERIFIED",
                "current_season_coverage": "UNVERIFIED",
                "team_identity_coverage": None,
                "last_verified_at": None,
                "notes": [],
                "project_analysis_count": 0,
                "analysis_count_30d": 0,
                "analysis_count_90d": 0,
                "analysis_count_all_recoverable": 0,
                "source_record_count": 0,
                "current_match_count": 0,
                "resolved_match_count": 0,
                "unresolved_match_count": 0,
            },
        )
        row["project_analysis_count"] = int(row.get("project_analysis_count") or 0) + bucket["project_analysis_count"]
        row["analysis_count_30d"] = int(row.get("analysis_count_30d") or 0) + bucket["analysis_count_30d"]
        row["analysis_count_90d"] = int(row.get("analysis_count_90d") or 0) + bucket["analysis_count_90d"]
        row["analysis_count_all_recoverable"] = int(row.get("analysis_count_all_recoverable") or 0) + bucket["analysis_count_all_recoverable"]
        row["source_record_count"] = int(row.get("source_record_count") or 0) + bucket["source_record_count"]
        row["current_match_count"] = int(row.get("current_match_count") or 0) + bucket["current_match_count"]
        row["resolved_match_count"] = int(row.get("resolved_match_count") or 0) + bucket["resolved_match_count"]
        row["unresolved_match_count"] = int(row.get("unresolved_match_count") or 0) + bucket["unresolved_match_count"]
        # Legacy readers may expect observed_count; it is a source-only alias.
        row["observed_count"] = row["source_record_count"]
        row["observed_raw_names"] = sorted(set(row.get("observed_raw_names") or []) | bucket["raw_names"])
        row["observed_provider_competition_ids"] = sorted(set(row.get("observed_provider_competition_ids") or []) | bucket["provider_competition_ids"])
        row["result_coverage"] = _status(row.get("result_coverage"))
        row["current_season_coverage"] = _status(row.get("current_season_coverage"))

    def _observation_payload(key: str, bucket: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "competition_key": key,
            "raw_names": sorted(bucket["raw_names"]),
            "project_analysis_count": bucket["project_analysis_count"],
            "analysis_count_30d": bucket["analysis_count_30d"],
            "analysis_count_90d": bucket["analysis_count_90d"],
            "analysis_count_all_recoverable": bucket["analysis_count_all_recoverable"],
            "source_record_count": bucket["source_record_count"],
            "observed_count": bucket["source_record_count"],
            "current_match_count": bucket["current_match_count"],
            "resolved_match_count": bucket["resolved_match_count"],
            "unresolved_match_count": bucket["unresolved_match_count"],
            "provider_competition_ids": sorted(bucket["provider_competition_ids"]),
        }

    project_observed = [
        _observation_payload(key, bucket)
        for key, bucket in sorted(grouped.items())
        if bucket["project_analysis_count"] or bucket["analysis_count_30d"] or bucket["analysis_count_90d"] or bucket["current_match_count"]
    ]
    source_observed = [_observation_payload(key, bucket) for key, bucket in sorted(grouped.items()) if bucket["source_record_count"]]
    return {
        "contract_version": "competition_coverage_registry.v1",
        "generated_at": generated_at,
        "observed_competitions": project_observed,
        "source_observed_competitions": source_observed,
        "competitions": [by_key[key] for key in sorted(by_key)],
    }


def rank_coverage_gaps(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Rank gaps by project usage and current demand, never source volume."""

    output: list[dict[str, Any]] = []
    for raw in rows:
        row = dict(raw)
        current = int(row.get("current_match_count") or 0)
        has_usage_fields = any(key in row for key in ("project_analysis_count", "analysis_count_30d", "analysis_count_90d"))
        project_analysis_count = int(row.get("project_analysis_count") or 0)
        analysis_30d = int(row.get("analysis_count_30d") or 0)
        analysis_90d = int(row.get("analysis_count_90d") or 0)
        legacy_usage = int(row.get("observed_count") or 0) if not has_usage_fields else 0
        project_usage = max(project_analysis_count, analysis_30d, analysis_90d, legacy_usage)
        current_strength_coverage = row.get("current_strength_coverage")
        current_strength_ok = (current_strength_coverage is not None and float(current_strength_coverage) >= 1.0) if current else True
        supported = _status(row.get("result_coverage")) == "SUPPORTED" and float(row.get("team_identity_coverage") or 0) >= 1.0 and current_strength_ok
        if current and not supported:
            priority = "P0"
        elif project_usage >= 10 and not supported:
            priority = "P1"
        elif project_usage:
            priority = "P2"
        else:
            priority = "P3"
        row["coverage_priority"] = priority
        row["project_usage_count"] = project_usage
        row["priority_reason"] = "current project analysis gap" if priority == "P0" else "project analysis usage" if project_usage else "no project usage evidence"
        output.append(row)
    order = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
    return sorted(
        output,
        key=lambda row: (
            order.get(str(row.get("coverage_priority")), 9),
            -int(row.get("current_match_count") or 0),
            -int(row.get("project_usage_count") or 0),
            str(row.get("competition_key") or ""),
        ),
    )


def analysis_weighted_coverage(
    rows: Iterable[Mapping[str, Any]],
    *,
    priorities: frozenset[str] = frozenset({"P0", "P1"}),
) -> dict[str, Any]:
    """Weight readiness by project demand, with bridge reported separately."""

    selected = [row for row in rows if str(row.get("coverage_priority")) in priorities]
    weight = lambda row: int(row.get("project_analysis_count") or row.get("analysis_count_all_recoverable") or 0)
    total = sum(weight(row) for row in selected)
    strict = sum(
        weight(row)
        for row in selected
        if str(row.get("business_status")) == "READY" and float(row.get("current_strength_coverage") or 0) >= 1.0
    )
    bridge = sum(
        weight(row)
        for row in selected
        if str(row.get("business_status")) in {"READY", "BRIDGE_ONLY"}
        or str(row.get("history_recency_status")) == "BRIDGE_ONLY"
    )
    return {
        "priority_scope": sorted(priorities),
        "analysis_weight": total,
        "strict_ready_weight": strict,
        "ready_plus_bridge_weight": bridge,
        "analysis_weighted_strict_ready": round(strict / total, 6) if total else 0,
        "analysis_weighted_ready_plus_bridge": round(bridge / total, 6) if total else 0,
    }


__all__ = [
    "STATUSES",
    "SOURCE_COMPLETENESS_STATUSES",
    "build_coverage_registry",
    "classify_source_completeness",
    "analysis_weighted_coverage",
    "rank_coverage_gaps",
]
