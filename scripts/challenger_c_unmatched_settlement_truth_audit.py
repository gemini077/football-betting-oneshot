#!/usr/bin/env python3
"""Audit the settlement truth behind Challenger C's unmatched unique matches.

This is a read-only evidence builder.  It deliberately reuses the existing
pair loading, result discovery, identity-safe matcher, and legal prematch
representative selector.  The only counterfactual operation is counting an
already-valid 90-minute result whose normalized score is not consumed by the
current matcher; no pair, result, review, or production artifact is changed.
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import Any, Iterable, Mapping


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from market_side_shadow import (  # noqa: E402
    _actual_for_pair,
    _is_promotion_eligible_pair,
    load_persisted_pairs,
    select_promotion_representatives,
)
from market_side_shadow_refresh import (  # noqa: E402
    build_identity_safe_result_map,
    discover_verified_results,
)
from postmatch_queue import parse_datetime  # noqa: E402
from prospective_settlement import _is_verified_result_artifact, normalize_result  # noqa: E402


MILESTONE = "CHALLENGER-C-UNMATCHED-SETTLEMENT-TRUTH-1"
SCHEMA_VERSION = "challenger_c_unmatched_settlement_truth_1.v1"
BASELINE_HEAD = "ef7cdb447344341ad250bd6e5eeb223c398c1124"
BASELINE_SOURCE_MAIN_SHA = "151b13782552cbdee48448cb67ae00cdafbfc05d"
BASELINE_WORKFLOW = "33785044810"
BASELINE_ARTIFACT = "9905108293"
RESULT_ROOT_LABEL = "data/postmatch_automation/results"
PAIR_ROOT_LABEL = "data/prediction_quality/market_side_shadow_1/pairs"
RESULT_ID_FIELDS = (
    "prediction_match_id",
    "match_id",
    "provider_match_id",
    "sporttery_match_id",
)
FINAL_SCOPES = {"regulation_90m_plus_stoppage", "90m", "regulation_90m"}

REASONS = (
    "FUTURE_NOT_DUE",
    "PAST_RESULT_MISSING",
    "RESULT_PRESENT_INVALID",
    "RESULT_PRESENT_IDENTITY_CONFLICT",
    "RESULT_PRESENT_RECOVERABLE_LINKAGE",
    "EXPLICIT_POSTPONED_OR_CANCELLED",
    "UNKNOWN_FAIL_CLOSED",
)
FINAL_DECISIONS = (
    "SETTLEMENT_GAP_MATERIAL",
    "PARTIAL_SETTLEMENT_GAP_NOT_CHECKPOINT",
    "SAMPLE_GENUINELY_NOT_REACHED",
    "FAIL_CLOSED",
)

ACCEPTED_BASELINE = {
    "total_pair_version_rows": 400,
    "promotion_eligible_pair_version_rows": 399,
    "promotion_eligible_unique_matches": 70,
    "verified_pair_version_rows": 118,
    "verified_unique_matches": 30,
    "unmatched_eligible_unique_matches": 40,
    "ambiguous_final_chronology_match_groups": 0,
}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _utc(value: Any) -> datetime | None:
    parsed = parse_datetime(value)
    return parsed.astimezone(timezone.utc) if parsed else None


def _json_safe(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _result_path(match_key: str) -> str:
    return f"{RESULT_ROOT_LABEL}/{match_key}.json"


def _pair_summary(pair: Mapping[str, Any] | None, group: Mapping[str, Any]) -> dict[str, Any]:
    if pair is None:
        return {
            "pair_id": None,
            "prediction_id": group.get("selected_prediction_id"),
            "match_id": group.get("match_id"),
            "match_key": group.get("match_key"),
            "kickoff_at": None,
            "source_cutoff": group.get("selected_source_cutoff_at"),
            "freeze_created_at": group.get("selected_freeze_created_at"),
            "frozen_input_digest": None,
            "pair_status": None,
            "promotion_eligible": None,
        }
    return {
        "pair_id": pair.get("pair_id"),
        "prediction_id": group.get("selected_prediction_id"),
        "match_id": pair.get("match_id"),
        "match_key": pair.get("match_key"),
        "kickoff_at": pair.get("kickoff_at"),
        "source_cutoff": pair.get("source_cutoff"),
        "freeze_created_at": pair.get("freeze_created_at"),
        "frozen_input_digest": pair.get("frozen_input_digest"),
        "pair_status": pair.get("pair_status"),
        "promotion_eligible": pair.get("promotion_eligible"),
    }


def _raw_identity(result: Mapping[str, Any]) -> dict[str, Any]:
    fields = (
        "match_key",
        "canonical_match_id",
        "prediction_match_id",
        "match_id",
        "provider_match_id",
        "sporttery_match_id",
        "home",
        "away",
        "kickoff_local",
        "kickoff_at",
    )
    return {field: _json_safe(result.get(field)) for field in fields if result.get(field) not in (None, "")}


def _candidate_ids(result: Mapping[str, Any]) -> set[str]:
    return {
        _text(result.get(field))
        for field in RESULT_ID_FIELDS
        if result.get(field) not in (None, "")
    }


def _exact_identity(pair: Mapping[str, Any], result: Mapping[str, Any]) -> bool:
    expected_key = _text(pair.get("match_key"))
    result_key = _text(result.get("match_key") or result.get("canonical_match_id"))
    if not expected_key or result_key != expected_key:
        return False

    expected_match_id = _text(pair.get("match_id"))
    candidate_ids = _candidate_ids(result)
    if not expected_match_id or expected_match_id not in candidate_ids:
        return False

    expected_kickoff = _utc(pair.get("kickoff_at"))
    result_kickoff = _utc(result.get("kickoff_local") or result.get("kickoff_at"))
    return bool(expected_kickoff and result_kickoff and expected_kickoff == result_kickoff)


def _result_file_evidence(
    pair: Mapping[str, Any],
    result_root: Path,
    result_catalog: Mapping[str, Mapping[str, Any]],
    result_map: Mapping[str, Any],
) -> dict[str, Any]:
    match_key = _text(pair.get("match_key"))
    path = Path(result_root) / f"{match_key}.json"
    evidence: dict[str, Any] = {
        "expected_path": _result_path(match_key),
        "file_exists": path.is_file(),
        "parse_status": "NOT_PRESENT",
        "integrity_status": "ABSENT",
        "scope": None,
        "result_90m": None,
        "verified_at": None,
        "verified_at_post_kickoff": False,
        "identity_exact": False,
        "identity_fields": {},
        "source": None,
        "catalog_key_present": match_key in result_catalog,
        "result_map_linked": False,
        "existing_matcher_actual": None,
        "counterfactual_actual": None,
    }
    if not path.is_file():
        return evidence

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        evidence.update({"parse_status": "INVALID_JSON", "integrity_status": "INVALID_RESULT_ARTIFACT"})
        return evidence
    if not isinstance(raw, dict):
        evidence.update({"parse_status": "INVALID_SHAPE", "integrity_status": "INVALID_RESULT_ARTIFACT"})
        return evidence

    evidence.update(
        {
            "scope": raw.get("scope"),
            "verified_at": raw.get("result_verified_at") or raw.get("verified_at"),
            "identity_fields": _raw_identity(raw),
            "source": raw.get("source"),
        }
    )
    normalized: dict[str, Any] | None = None
    try:
        if _is_verified_result_artifact(raw):
            normalized = normalize_result(raw)
    except (TypeError, ValueError):
        normalized = None
    if normalized is None:
        evidence.update({"parse_status": "INVALID_RESULT", "integrity_status": "INVALID_RESULT_ARTIFACT"})
        return evidence

    home_score = normalized.get("home_score_90m")
    away_score = normalized.get("away_score_90m")
    evidence.update(
        {
            "parse_status": "VALID",
            "result_90m": f"{home_score}-{away_score}",
            "identity_exact": _exact_identity(pair, normalized),
        }
    )
    kickoff = _utc(pair.get("kickoff_at"))
    verified_at = _utc(evidence["verified_at"])
    evidence["verified_at_post_kickoff"] = bool(kickoff and verified_at and verified_at > kickoff)
    if not evidence["identity_exact"]:
        evidence["integrity_status"] = "IDENTITY_CONFLICT"
    elif normalized.get("scope") not in FINAL_SCOPES or not evidence["verified_at_post_kickoff"]:
        evidence["integrity_status"] = "ILLEGAL_RESULT_TRUTH"
    else:
        evidence["integrity_status"] = "VALID_90M_EXACT_IDENTITY"
        evidence["counterfactual_actual"] = [home_score, away_score]

    keys = (
        _text(pair.get("pair_id")),
        _text(pair.get("match_id")),
        _text(pair.get("champion_prediction_id")),
        _text(pair.get("challenger_prediction_id")),
    )
    evidence["result_map_linked"] = any(key and key in result_map for key in keys)
    actual = _actual_for_pair(pair, result_map)
    evidence["existing_matcher_actual"] = list(actual) if actual is not None else None
    return evidence


def _classify_unmatched(
    pair: Mapping[str, Any] | None,
    group: Mapping[str, Any],
    *,
    result_root: Path,
    result_catalog: Mapping[str, Mapping[str, Any]],
    result_map: Mapping[str, Any],
    snapshot_at: datetime,
) -> tuple[str, dict[str, Any]]:
    if pair is None:
        return "UNKNOWN_FAIL_CLOSED", {
            "expected_path": _result_path(_text(group.get("match_key"))),
            "file_exists": False,
            "parse_status": "NOT_EVALUATED",
            "integrity_status": "NO_SELECTED_PREMATCH_REPRESENTATIVE",
        }

    kickoff = _utc(pair.get("kickoff_at"))
    evidence = _result_file_evidence(pair, result_root, result_catalog, result_map)
    evidence["kickoff_relation"] = (
        "FUTURE" if kickoff and kickoff > snapshot_at else "PAST" if kickoff else "UNKNOWN"
    )
    evidence["future_relative_to_snapshot"] = bool(kickoff and kickoff > snapshot_at)

    if not evidence["file_exists"]:
        if evidence["catalog_key_present"]:
            return "RESULT_PRESENT_IDENTITY_CONFLICT", evidence
        if kickoff is None:
            return "UNKNOWN_FAIL_CLOSED", evidence
        return ("FUTURE_NOT_DUE" if kickoff > snapshot_at else "PAST_RESULT_MISSING"), evidence
    if evidence["parse_status"] != "VALID":
        return "RESULT_PRESENT_INVALID", evidence
    if not evidence["identity_exact"]:
        return "RESULT_PRESENT_IDENTITY_CONFLICT", evidence
    if evidence["integrity_status"] != "VALID_90M_EXACT_IDENTITY":
        return "RESULT_PRESENT_INVALID", evidence
    if not evidence["catalog_key_present"] or not evidence["result_map_linked"]:
        return "RESULT_PRESENT_IDENTITY_CONFLICT", evidence
    if evidence["existing_matcher_actual"] is not None:
        return "UNKNOWN_FAIL_CLOSED", evidence
    if evidence["counterfactual_actual"] is None:
        return "RESULT_PRESENT_INVALID", evidence
    return "RESULT_PRESENT_RECOVERABLE_LINKAGE", evidence


def _tracked_json_count(root: Path, pattern: str) -> int:
    return sum(path.is_file() for path in Path(root).glob(pattern))


def _cohort(
    label: str,
    *,
    pair_root: Path,
    result_root: Path,
    snapshot_at: datetime,
) -> dict[str, Any]:
    pairs = load_persisted_pairs(Path(pair_root))
    result_catalog, discovery = discover_verified_results(Path(result_root))
    result_map, matching = build_identity_safe_result_map(pairs, result_catalog)
    selection = select_promotion_representatives(pairs, result_map)
    selected_by_pair_id = {
        _text(pair.get("pair_id")): pair
        for pair in selection.get("selected_representatives") or []
        if _text(pair.get("pair_id"))
    }

    unmatched: list[dict[str, Any]] = []
    for group in selection.get("groups") or []:
        if group.get("status") == "SELECTED" and group.get("verified") is True:
            continue
        selected_pair = selected_by_pair_id.get(_text(group.get("selected_pair_id")))
        reason, result_evidence = _classify_unmatched(
            selected_pair,
            group,
            result_root=Path(result_root),
            result_catalog=result_catalog,
            result_map=result_map,
            snapshot_at=snapshot_at,
        )
        unmatched.append(
            {
                "match_key": group.get("match_key"),
                "match_id": group.get("match_id"),
                "selected_representative": _pair_summary(selected_pair, group),
                "kickoff_at": selected_pair.get("kickoff_at") if selected_pair else None,
                "future_relative_to_snapshot": result_evidence.get("future_relative_to_snapshot"),
                "result_evidence": result_evidence,
                "reason": reason,
            }
        )

    eligible = [pair for pair in pairs if _is_promotion_eligible_pair(pair)]
    identity_matched_eligible_rows = sum(
        _text(pair.get("pair_id")) in result_map for pair in eligible
    )
    selected_counts = selection["counts"]
    counts = {
        "total_pair_version_rows": len(pairs),
        "promotion_eligible_pair_version_rows": selected_counts["promotion_eligible_pair_version_rows"],
        "verified_pair_version_rows": selected_counts["verified_pair_version_rows"],
        "identity_matched_eligible_rows": identity_matched_eligible_rows,
        "promotion_eligible_unique_matches": selected_counts["promotion_eligible_unique_matches"],
        "verified_unique_matches": selected_counts["verified_unique_matches"],
        "unmatched_eligible_unique_matches": len(unmatched),
        "unmatched_eligible_rows": len(eligible) - identity_matched_eligible_rows,
        "ambiguous_final_chronology_match_groups": selected_counts["ambiguous_final_chronology_match_groups"],
        "version_history_match_groups": selected_counts["version_history_match_groups"],
        "extra_version_rows": selected_counts["extra_version_rows"],
    }
    reason_counts = Counter(row["reason"] for row in unmatched)
    return {
        "label": label,
        "counts": counts,
        "reason_counts": {reason: reason_counts.get(reason, 0) for reason in REASONS},
        "pair_files_scanned": _tracked_json_count(Path(pair_root), "MS-SHADOW-PAIR-*.json"),
        "result_files": sorted(path.name for path in Path(result_root).glob("*.json")),
        "discovery": discovery,
        "matching": matching,
        "unmatched_unique": unmatched,
        "groups_by_match_key": {
            _text(group.get("match_key")): {
                "status": group.get("status"),
                "verified": group.get("verified") is True,
                "selected_pair_id": group.get("selected_pair_id"),
                "selected_prediction_id": group.get("selected_prediction_id"),
            }
            for group in selection.get("groups") or []
            if _text(group.get("match_key"))
        },
    }


def _baseline_reproduction(cohort: Mapping[str, Any]) -> dict[str, Any]:
    observed = {
        key: cohort["counts"].get(key)
        for key in ACCEPTED_BASELINE
    }
    mismatches = [
        {
            "metric": key,
            "expected": expected,
            "observed": observed.get(key),
        }
        for key, expected in ACCEPTED_BASELINE.items()
        if observed.get(key) != expected
    ]
    return {
        "status": "PASS" if not mismatches else "FAIL",
        "accepted": dict(ACCEPTED_BASELINE),
        "observed": observed,
        "mismatches": mismatches,
    }


def _row_by_key(cohort: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    return {
        _text(row.get("match_key")): row
        for row in cohort.get("unmatched_unique") or []
        if _text(row.get("match_key"))
    }


def _current_delta(baseline: Mapping[str, Any], current: Mapping[str, Any]) -> dict[str, Any]:
    base_counts = baseline["counts"]
    current_counts = current["counts"]
    count_keys = (
        "total_pair_version_rows",
        "promotion_eligible_pair_version_rows",
        "promotion_eligible_unique_matches",
        "verified_pair_version_rows",
        "verified_unique_matches",
        "unmatched_eligible_unique_matches",
    )
    base_keys = set(baseline.get("groups_by_match_key") or {})
    current_keys = set(current.get("groups_by_match_key") or {})
    baseline_unmatched = _row_by_key(baseline)
    current_unmatched = _row_by_key(current)

    transitions: list[dict[str, Any]] = []
    for match_key in sorted(baseline_unmatched):
        current_group = (current.get("groups_by_match_key") or {}).get(match_key)
        current_row = current_unmatched.get(match_key)
        if current_group is None:
            current_reason = "UNKNOWN_FAIL_CLOSED"
            current_pair_id = None
            current_evidence = {}
        elif current_group.get("verified") is True:
            current_reason = "VERIFIED_BY_CURRENT_MATCHER"
            current_pair_id = current_group.get("selected_pair_id")
            current_evidence = {}
        else:
            current_reason = _text((current_row or {}).get("reason")) or "UNKNOWN_FAIL_CLOSED"
            current_pair_id = (current_row or {}).get("selected_representative", {}).get("pair_id")
            current_evidence = (current_row or {}).get("result_evidence") or {}
        transitions.append(
            {
                "match_key": match_key,
                "baseline_reason": baseline_unmatched[match_key].get("reason"),
                "current_reason": current_reason,
                "baseline_pair_id": baseline_unmatched[match_key]
                .get("selected_representative", {})
                .get("pair_id"),
                "current_pair_id": current_pair_id,
                "current_result_file_exists": current_evidence.get("file_exists"),
                "current_result_90m": current_evidence.get("result_90m"),
                "current_verified_at": current_evidence.get("verified_at"),
            }
        )

    added_keys = sorted(current_keys - base_keys)
    added_rows = []
    for key in added_keys:
        row = current_unmatched.get(key)
        group = (current.get("groups_by_match_key") or {}).get(key) or {}
        added_rows.append(
            {
                "match_key": key,
                "selected_pair_id": (row or {}).get("selected_representative", {}).get("pair_id")
                or group.get("selected_pair_id"),
                "status": "UNMATCHED" if row else "VERIFIED_BY_CURRENT_MATCHER",
                "reason": (row or {}).get("reason"),
                "kickoff_at": (row or {}).get("kickoff_at"),
            }
        )

    changed_representatives = sorted(
        key
        for key in sorted(base_keys & current_keys)
        if (baseline.get("groups_by_match_key") or {}).get(key, {}).get("selected_pair_id")
        != (current.get("groups_by_match_key") or {}).get(key, {}).get("selected_pair_id")
    )
    baseline_result_files = set(baseline.get("result_files") or [])
    current_result_files = set(current.get("result_files") or [])
    return {
        "counts": {
            key: {
                "baseline": base_counts.get(key),
                "current_main": current_counts.get(key),
                "delta": (current_counts.get(key) or 0) - (base_counts.get(key) or 0),
            }
            for key in count_keys
        },
        "baseline_unique_keys": len(base_keys),
        "current_main_unique_keys": len(current_keys),
        "common_unique_keys": len(base_keys & current_keys),
        "added_unique_matches": added_rows,
        "added_result_artifacts": [
            f"{RESULT_ROOT_LABEL}/{name}" for name in sorted(current_result_files - baseline_result_files)
        ],
        "selected_representative_changed_for_common_matches": {
            "count": len(changed_representatives),
            "match_keys": changed_representatives,
        },
        "baseline_unmatched_current_mapping": transitions,
    }


def _decision(
    *,
    baseline_reproduction: Mapping[str, Any],
    current: Mapping[str, Any],
) -> tuple[str, int, int]:
    recoverable_now = current["reason_counts"].get("RESULT_PRESENT_RECOVERABLE_LINKAGE", 0)
    verified = current["counts"]["verified_unique_matches"]
    verified_after = verified + recoverable_now
    residual_reasons = {
        reason
        for reason, count in current["reason_counts"].items()
        if count
    } - {
        "FUTURE_NOT_DUE",
        "PAST_RESULT_MISSING",
        "EXPLICIT_POSTPONED_OR_CANCELLED",
        "RESULT_PRESENT_RECOVERABLE_LINKAGE",
    }
    if baseline_reproduction.get("status") != "PASS" or residual_reasons:
        return "FAIL_CLOSED", recoverable_now, verified_after
    if recoverable_now and verified_after >= 50:
        return "SETTLEMENT_GAP_MATERIAL", recoverable_now, verified_after
    if recoverable_now:
        return "PARTIAL_SETTLEMENT_GAP_NOT_CHECKPOINT", recoverable_now, verified_after
    return "SAMPLE_GENUINELY_NOT_REACHED", recoverable_now, verified_after


def _controls() -> dict[str, bool]:
    return {
        "read_only_audit": True,
        "result_network_fetch": False,
        "result_writeback": False,
        "manual_result_entry": False,
        "fuzzy_matching": False,
        "frozen_prediction_modified": False,
        "authoritative_result_modified": False,
        "champion_modified": False,
        "challenger_c_modified": False,
        "model_modified": False,
        "production_modified": False,
        "promotion_attempted": False,
    }


def run_audit(
    *,
    baseline_pair_root: Path,
    baseline_result_root: Path,
    current_pair_root: Path,
    current_result_root: Path,
    baseline_ref: str = BASELINE_HEAD,
    current_ref: str = "WORKTREE",
    snapshot_at: str | None = None,
) -> dict[str, Any]:
    snapshot = _utc(snapshot_at) if snapshot_at else datetime.now(timezone.utc)
    if snapshot is None:
        raise ValueError(f"invalid snapshot_at: {snapshot_at}")

    baseline = _cohort(
        "PR170_BASELINE",
        pair_root=Path(baseline_pair_root),
        result_root=Path(baseline_result_root),
        snapshot_at=snapshot,
    )
    current = _cohort(
        "CURRENT_MAIN",
        pair_root=Path(current_pair_root),
        result_root=Path(current_result_root),
        snapshot_at=snapshot,
    )
    reproduction = _baseline_reproduction(baseline)
    current_delta = _current_delta(baseline, current)
    final_decision, recoverable_now, verified_after = _decision(
        baseline_reproduction=reproduction,
        current=current,
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "milestone": MILESTONE,
        "audit_snapshot_at": snapshot.isoformat(),
        "source": {
            "baseline": {
                "accepted_pr": 170,
                "accepted_head": BASELINE_HEAD,
                "source_ref_used": baseline_ref,
                "source_main_sha": BASELINE_SOURCE_MAIN_SHA,
                "accepted_workflow": BASELINE_WORKFLOW,
                "accepted_artifact": BASELINE_ARTIFACT,
                "pair_root": PAIR_ROOT_LABEL,
                "result_root": RESULT_ROOT_LABEL,
                "pair_files_scanned": baseline["pair_files_scanned"],
                "result_files_scanned": baseline["discovery"]["result_files_scanned"],
            },
            "current_main": {
                "source_ref_used": current_ref,
                "pair_root": PAIR_ROOT_LABEL,
                "result_root": RESULT_ROOT_LABEL,
                "pair_files_scanned": current["pair_files_scanned"],
                "result_files_scanned": current["discovery"]["result_files_scanned"],
            },
            "universe_job_status": "NOT_CONSUMED_NO_EXPLICIT_STATUS_ARTIFACT_USED",
        },
        "baseline_reproduction": reproduction,
        "baseline": {
            "counts": baseline["counts"],
            "reason_counts": baseline["reason_counts"],
            "discovery": baseline["discovery"],
            "matching": baseline["matching"],
            "unmatched_unique": baseline["unmatched_unique"],
        },
        "current_main": {
            "counts": current["counts"],
            "reason_counts": current["reason_counts"],
            "discovery": current["discovery"],
            "matching": current["matching"],
            "unmatched_unique": current["unmatched_unique"],
        },
        "current_main_delta": current_delta,
        "recoverable_now": recoverable_now,
        "verified_unique_after_legal_recovery": verified_after,
        "final_decision": final_decision,
        "controls": _controls(),
        "method": {
            "pair_selection": "market_side_shadow.select_promotion_representatives",
            "prematch_legality": "prematch_versioning.select_latest_legal_prematch via existing selector",
            "result_discovery": "market_side_shadow_refresh.discover_verified_results",
            "identity_linkage": "market_side_shadow_refresh.build_identity_safe_result_map",
            "counterfactual": "read normalized home_score_90m/away_score_90m only; no writeback",
            "future_or_past": "kickoff compared with audit_snapshot_at in UTC",
            "unmatched_reason_enum": list(REASONS),
            "final_decision_enum": list(FINAL_DECISIONS),
        },
    }


def _short(value: Any) -> str:
    return "" if value in (None, "") else str(value).replace("|", "\\|").replace("\n", " ")


def _row_markdown(row: Mapping[str, Any]) -> str:
    representative = row.get("selected_representative") or {}
    result = row.get("result_evidence") or {}
    return "| " + " | ".join(
        [
            f"`{_short(row.get('match_key'))}`",
            f"`{_short(row.get('match_id'))}`",
            f"`{_short(representative.get('pair_id'))}`",
            f"`{_short(row.get('kickoff_at'))}`",
            f"`{_short(row.get('future_relative_to_snapshot'))}`",
            f"`{_short(result.get('file_exists'))}`",
            f"`{_short(result.get('scope'))}`",
            f"`{_short(result.get('result_90m'))}`",
            f"`{_short(result.get('verified_at'))}`",
            f"`{_short(row.get('reason'))}`",
        ]
    ) + " |"


def _render_rows(title: str, rows: Iterable[Mapping[str, Any]]) -> list[str]:
    lines = [
        f"## {title}",
        "",
        "| match_key | match_id | selected_pair_id | kickoff_at | future_at_snapshot | exact result file | scope | result_90m | verified_at | reason |",
        "|---|---|---|---|---:|---:|---|---|---|---|",
    ]
    lines.extend(_row_markdown(row) for row in rows)
    lines.append("")
    return lines


def _build_report(summary: Mapping[str, Any]) -> str:
    baseline = summary["baseline"]
    current = summary["current_main"]
    delta = summary["current_main_delta"]
    lines = [
        f"# {MILESTONE}",
        "",
        f"Audit snapshot: `{summary['audit_snapshot_at']}`.",
        f"Final decision: **`{summary['final_decision']}`**.",
        "",
        "This is a read-only settlement/sample-truth audit. It does not fetch results, rewrite results or frozen predictions, use fuzzy identity matching, modify production/Champion/Challenger C/model state, or attempt promotion.",
        "",
        "## Accepted PR #170 baseline",
        "",
        f"- Accepted head: `{summary['source']['baseline']['accepted_head']}`; source main: `{summary['source']['baseline']['source_main_sha']}`.",
        f"- Source snapshot files: `{summary['source']['baseline']['pair_files_scanned']}` pair files and `{summary['source']['baseline']['result_files_scanned']}` result files.",
        f"- Reproduction: **`{summary['baseline_reproduction']['status']}`**.",
        f"- Accepted/observed: `{json.dumps(summary['baseline_reproduction']['accepted'], sort_keys=True)}` / `{json.dumps(summary['baseline_reproduction']['observed'], sort_keys=True)}`.",
        "",
        "## Current-main delta",
        "",
        f"- Current source ref: `{summary['source']['current_main']['source_ref_used']}`.",
        f"- Added unique matches: `{len(delta['added_unique_matches'])}`; added result artifacts: `{len(delta['added_result_artifacts'])}`.",
        f"- Selected representative changed for common unique matches: `{delta['selected_representative_changed_for_common_matches']['count']}`.",
        f"- Count delta: `{json.dumps(delta['counts'], sort_keys=True)}`.",
        f"- Added unique match mapping: `{json.dumps(delta['added_unique_matches'], ensure_ascii=False, sort_keys=True)}`.",
        f"- Added result artifacts: `{json.dumps(delta['added_result_artifacts'], ensure_ascii=False)}`.",
        "",
        f"Baseline reason counts: `{json.dumps(baseline['reason_counts'], sort_keys=True)}`.",
        f"Current-main reason counts: `{json.dumps(current['reason_counts'], sort_keys=True)}`.",
        "",
        f"`recoverable_now` = `{summary['recoverable_now']}`; `verified_unique_after_legal_recovery` = `{summary['verified_unique_after_legal_recovery']}`.",
        "",
    ]
    lines.extend(_render_rows("PR #170 baseline unmatched unique classifications", baseline["unmatched_unique"]))
    lines.extend(_render_rows("Current-main unmatched unique classifications", current["unmatched_unique"]))
    lines.extend(
        [
            "## Exact baseline-to-current mapping",
            "",
            "Each of the 40 accepted baseline unmatched unique keys is mapped below; current-main rows use the current selected representative and current result catalog.",
            "",
            "```json",
            json.dumps(delta["baseline_unmatched_current_mapping"], ensure_ascii=False, indent=2, sort_keys=True),
            "```",
            "",
            "## Decision contract",
            "",
            f"- `recoverable_now`: `{summary['recoverable_now']}`.",
            f"- `verified_unique_after_legal_recovery`: `{summary['verified_unique_after_legal_recovery']}`.",
            f"- Final decision: **`{summary['final_decision']}`**.",
            "- The audit stops here. No settlement linkage fix, new model experiment, promotion, merge, or production verification is started.",
            "",
            "## Controls",
            "",
            f"`{json.dumps(summary['controls'], sort_keys=True)}`",
            "",
            "The canonical machine-readable evidence is `summary.json`; this report intentionally contains no raw pair/result dumps beyond the fields needed to independently inspect each unmatched unique match.",
            "",
        ]
    )
    return "\n".join(lines)


def write_artifacts(summary: Mapping[str, Any], output_dir: Path) -> None:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "summary.json").write_text(
        json.dumps(_json_safe(summary), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output_dir / "report.md").write_text(_build_report(summary), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-pair-root", type=Path, required=True)
    parser.add_argument("--baseline-result-root", type=Path, required=True)
    parser.add_argument("--current-pair-root", type=Path, required=True)
    parser.add_argument("--current-result-root", type=Path, required=True)
    parser.add_argument("--baseline-ref", default=BASELINE_HEAD)
    parser.add_argument("--current-ref", default="WORKTREE")
    parser.add_argument("--snapshot-at")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    summary = run_audit(
        baseline_pair_root=args.baseline_pair_root,
        baseline_result_root=args.baseline_result_root,
        current_pair_root=args.current_pair_root,
        current_result_root=args.current_result_root,
        baseline_ref=args.baseline_ref,
        current_ref=args.current_ref,
        snapshot_at=args.snapshot_at,
    )
    write_artifacts(summary, args.output_dir)
    print(
        json.dumps(
            {
                "baseline_reproduction": summary["baseline_reproduction"]["status"],
                "current_main_delta": summary["current_main_delta"]["counts"],
                "recoverable_now": summary["recoverable_now"],
                "verified_unique_after_legal_recovery": summary["verified_unique_after_legal_recovery"],
                "final_decision": summary["final_decision"],
                "output_dir": str(args.output_dir),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0 if summary["final_decision"] != "FAIL_CLOSED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
