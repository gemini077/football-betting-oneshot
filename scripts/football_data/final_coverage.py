"""Final Phase 2B coverage gates and compact identity-gap diagnostics.

This module is deliberately a reporting boundary.  It does not create team
identities, infer missing results, or alter the Champion input surface.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Iterable, Mapping


IDENTITY_BLOCKERS = (
    "provider_team_id_missing",
    "translated_english_name_missing",
    "reviewed_alias_missing",
    "canonical_source_candidate_missing",
    "fixture_graph_insufficient",
    "ambiguous_candidate",
    "provider_namespace_conflict",
    "competition_mismatch",
    "country_mismatch",
)

FINAL_GATE_WEIGHT = 122

PHASE2B_CLOSURE_REASON = (
    "bounded Phase 2B scope completed",
    "remaining identity gaps require new reviewed evidence",
    "remaining source gaps require external credentials, licensing review, or future source availability",
    "continued global coverage expansion is deferred rather than treated as model-data success",
)


def _values(value: Any) -> set[str]:
    if isinstance(value, (list, tuple, set, frozenset)):
        return {str(item) for item in value if str(item).strip()}
    return {str(value)} if value is not None and str(value).strip() else set()


def _reasons(side: Mapping[str, Any]) -> set[str]:
    return {str(value).casefold() for value in side.get("reason") or []}


def classify_identity_side(side: Mapping[str, Any]) -> list[str]:
    """Return evidence blockers for one unresolved project-provider side.

    The function only reports missing or conflicting evidence.  It never turns
    a name similarity, translation, or fixture graph into a verified mapping.
    """

    if side.get("canonical_team_id"):
        return []

    reasons = _reasons(side)
    blockers: set[str] = set()
    before = _values(side.get("candidate_canonical_team_ids_before_context"))
    after = _values(side.get("candidate_canonical_team_ids_after_context"))
    candidates = _values(side.get("candidate_canonical_team_ids"))
    before |= candidates

    if not side.get("provider_team_id"):
        blockers.add("provider_team_id_missing")

    if (
        not side.get("translated_team_name")
        or str(side.get("translation_status") or "").upper() != "EXACT_MATCH"
    ):
        blockers.add("translated_english_name_missing")

    if not side.get("reviewed_alias_group_used") and not _values(side.get("reviewed_alias_group_keys")):
        blockers.add("reviewed_alias_missing")

    if len(before) > 1 or "multiple_unique_canonical_candidates" in reasons or "ambiguous" in reasons:
        blockers.add("ambiguous_candidate")

    if "provider_namespace_conflict" in reasons or "namespace_conflict" in reasons:
        blockers.add("provider_namespace_conflict")
    if "competition_mismatch" in reasons or "context_competition_mismatch" in reasons:
        blockers.add("competition_mismatch")
    if "country_mismatch" in reasons or "context_country_mismatch" in reasons:
        blockers.add("country_mismatch")

    if before and not after and not ("ambiguous_candidate" in blockers):
        if "competition_mismatch" in reasons or "context_competition_mismatch" in reasons:
            blockers.add("competition_mismatch")
        elif "country_mismatch" in reasons or "context_country_mismatch" in reasons:
            blockers.add("country_mismatch")

    if not before and not after:
        blockers.add("canonical_source_candidate_missing")

    fixture_count = side.get("supporting_fixture_count")
    if fixture_count is not None:
        try:
            if int(fixture_count) < 2:
                blockers.add("fixture_graph_insufficient")
        except (TypeError, ValueError):
            blockers.add("fixture_graph_insufficient")

    # Every unresolved side must have an actionable explanation even when a
    # legacy evidence row omitted all optional diagnostics.
    if not blockers:
        blockers.add("canonical_source_candidate_missing")
    return sorted(blockers)


def _side_payload(side: Mapping[str, Any]) -> dict[str, Any]:
    blockers = classify_identity_side(side)
    return {
        "provider": side.get("provider"),
        "provider_team_id": side.get("provider_team_id"),
        "provider_team_name": side.get("provider_team_name"),
        "translated_team_name": side.get("translated_team_name"),
        "translation_status": side.get("translation_status"),
        "canonical_team_id": side.get("canonical_team_id"),
        "canonical_name": side.get("canonical_name"),
        "resolution_status": side.get("resolution_status", "unresolved"),
        "resolution_method": side.get("resolution_method", "unresolved"),
        "reason": list(side.get("reason") or []),
        "blockers": blockers,
        "candidate_canonical_team_ids_before_context": sorted(
            _values(side.get("candidate_canonical_team_ids_before_context"))
            | _values(side.get("candidate_canonical_team_ids"))
        ),
        "candidate_canonical_team_ids_after_context": sorted(
            _values(side.get("candidate_canonical_team_ids_after_context"))
        ),
        "source_ref": side.get("source_ref"),
        "supporting_fixture_count": side.get("supporting_fixture_count"),
    }


def _fixture_classification(home: Mapping[str, Any], away: Mapping[str, Any]) -> str:
    statuses = {str(home.get("resolution_status") or "unresolved"), str(away.get("resolution_status") or "unresolved")}
    if home.get("canonical_team_id") and away.get("canonical_team_id"):
        return "AUTO_RESOLVED"
    if "conflict" in statuses:
        return "CONFLICT"
    if "review_required" in statuses:
        return "REVIEW_REQUIRED"
    if any(
        blocker in {"ambiguous_candidate", "provider_namespace_conflict", "competition_mismatch", "country_mismatch"}
        for side in (home, away)
        for blocker in classify_identity_side(side)
    ):
        return "CONFLICT"
    return "STILL_IDENTITY_MISSING"


def build_final_identity_gap_summary(
    gap_rows: Iterable[Mapping[str, Any]],
    target_evidence: Mapping[str, Mapping[str, Any]],
    *,
    generated_at: str,
) -> dict[str, Any]:
    """Build a compact, side-aware report for the current identity gap."""

    output_rows: list[dict[str, Any]] = []
    fixture_counts = Counter()
    blocker_counts = Counter()
    competition_counts: dict[str, Counter[str]] = {}

    for raw in gap_rows:
        target_id = str(raw.get("target_match_id") or "")
        evidence = target_evidence.get(target_id) or {}
        home_source = dict(evidence.get("home") or {})
        away_source = dict(evidence.get("away") or {})
        home = _side_payload(home_source)
        away = _side_payload(away_source)
        classification = _fixture_classification(home, away)
        fixture_counts[classification] += 1
        for side in (home, away):
            blocker_counts.update(side["blockers"])
        competition = str(raw.get("competition") or "unresolved")
        competition_counts.setdefault(competition, Counter())[classification] += 1
        output_rows.append(
            {
                "target_match_id": target_id,
                "competition": raw.get("competition"),
                "kickoff": raw.get("kickoff"),
                "project_home_name": raw.get("project_home_name") or evidence.get("project_home"),
                "project_away_name": raw.get("project_away_name") or evidence.get("project_away"),
                "provider": evidence.get("provider") or raw.get("provider"),
                "provider_match_id": evidence.get("provider_match_id") or raw.get("provider_match_id"),
                "home": home,
                "away": away,
                "fixture_classification": classification,
                "missing_evidence": sorted(set(home["blockers"] + away["blockers"])),
            }
        )

    return {
        "contract_version": "phase2b_final_identity_gap.v1",
        "generated_at": generated_at,
        "starting_identity_missing": len(output_rows),
        "rows": output_rows,
        "row_count": len(output_rows),
        "resolved_fixture_count": fixture_counts["AUTO_RESOLVED"],
        "auto_resolved_fixture_count": fixture_counts["AUTO_RESOLVED"],
        "review_required_fixture_count": fixture_counts["REVIEW_REQUIRED"],
        "conflict_fixture_count": fixture_counts["CONFLICT"],
        "still_unresolved_fixture_count": fixture_counts["STILL_IDENTITY_MISSING"],
        "blocker_counts": dict(sorted(blocker_counts.items())),
        "competition_classification": {
            key: dict(sorted(value.items())) for key, value in sorted(competition_counts.items())
        },
        "notes": [
            "This report classifies evidence gaps; it never auto-verifies fuzzy names or translation suggestions.",
            "Detailed candidate graphs remain outside Git under ${FOOTBALL_DATA_HOME}/identity/.",
            "SOURCE_MISSING is tracked separately from project-provider identity evidence.",
        ],
    }


def weighted_final_coverage(
    audits: Iterable[Mapping[str, Any]],
    *,
    gate_threshold_weight: int = FINAL_GATE_WEIGHT,
) -> dict[str, Any]:
    """Compute the final fixed-denominator Phase 2B gate."""

    counts: Counter[str] = Counter()
    demand_weight = 0
    for audit in audits:
        weight = int(audit.get("weight") or 1)
        status = str(audit.get("status") or "NOT_READY").upper()
        if status == "STALE_HISTORY":
            status = "STALE"
        counts[status] += weight
        demand_weight += weight

    strict = counts["STRICT_READY"]
    bridge = counts["VERIFIED_BRIDGE"]
    ready_plus_bridge = strict + bridge
    passed = ready_plus_bridge >= gate_threshold_weight
    return {
        "demand_weight": demand_weight,
        "strict_ready_weight": strict,
        "verified_bridge_weight": bridge,
        "ready_plus_bridge_weight": ready_plus_bridge,
        "identity_missing_weight": counts["IDENTITY_MISSING"],
        "source_missing_weight": counts["SOURCE_MISSING"],
        "scope_partial_weight": counts["SCOPE_PARTIAL"],
        "stale_weight": counts["STALE"],
        "conflict_weight": counts["CONFLICT"],
        "insufficient_history_weight": counts["INSUFFICIENT_HISTORY"],
        "strict_ready_rate": strict / demand_weight if demand_weight else 0.0,
        "ready_plus_bridge_rate": ready_plus_bridge / demand_weight if demand_weight else 0.0,
        "status_weights": dict(sorted(counts.items())),
        "gate_threshold_weight": gate_threshold_weight,
        "eighty_percent_gate_passed": passed,
        "validated_for_model": False,
    }


def build_phase2b_closure_decision(
    *,
    weighted: Mapping[str, Any],
    coverage_backlog: Mapping[str, Any],
) -> dict[str, Any]:
    """Record the explicit governance closure separately from coverage math.

    A failed readiness gate is a metric fact.  Closing this bounded phase with
    a backlog is an explicit project decision and must never be inferred from
    ``not weighted["eighty_percent_gate_passed"]``.
    """

    return {
        "phase2b_complete": True,
        "phase2b_closed": True,
        "phase2b_closed_with_backlog": True,
        "closure_reason": list(PHASE2B_CLOSURE_REASON),
        "coverage_backlog": dict(coverage_backlog),
        "global_80_percent_gate_passed": bool(weighted["eighty_percent_gate_passed"]),
        "global_model_data_ready": False,
        "eligible_subset_evaluation_required": True,
    }


__all__ = [
    "FINAL_GATE_WEIGHT",
    "IDENTITY_BLOCKERS",
    "PHASE2B_CLOSURE_REASON",
    "build_phase2b_closure_decision",
    "build_final_identity_gap_summary",
    "classify_identity_side",
    "weighted_final_coverage",
]
