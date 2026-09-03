#!/usr/bin/env python3
"""Audit whether current immutable football evidence can support a structural-lambda experiment.

Research-only. Reads existing prospective football evidence and authoritative
90m result records. It never changes production prediction data.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from statistics import median
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EVIDENCE_ROOT = ROOT / "data" / "prospective" / "football_evidence"
DEFAULT_RESULT_ROOT = ROOT / "data" / "postmatch_automation" / "results"
DEFAULT_LEDGER = ROOT / "data" / "prospective" / "ledger.jsonl"
DEFAULT_PINNED_MANIFEST = (
    ROOT / "data" / "prediction_quality" / "pred_trust_2" / "pinned_cohort_manifest.json"
)
MIN_ROWS_PER_TEAM = 10
MIN_SETTLED_USABLE = 50
RESULT_SCOPE = "regulation_90m_plus_stoppage"
SCORE_90M_RE = re.compile(r"^\s*(\d+)\s*-\s*(\d+)\s*$")


def _display_path(path: Path) -> str:
    """Serialize a path without requiring temporary fixtures under ROOT."""
    resolved = path.resolve()
    try:
        return resolved.relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return resolved.as_posix()


def _parse_time(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def _valid_score_row(row: Any, kickoff: datetime | None) -> bool:
    if not isinstance(row, dict):
        return False
    match_date = str(row.get("match_date") or "").strip()
    try:
        row_date = datetime.fromisoformat(match_date)
    except ValueError:
        return False
    if kickoff is not None and row_date.date() >= kickoff.date():
        return False
    try:
        home_goals = int(row.get("home_goals"))
        away_goals = int(row.get("away_goals"))
    except (TypeError, ValueError):
        return False
    if home_goals < 0 or away_goals < 0:
        return False
    return bool(row.get("home_team_id") and row.get("away_team_id"))


def _infer_subject_team_id(rows: Iterable[dict[str, Any]]) -> tuple[str | None, float]:
    counts: Counter[str] = Counter()
    valid_rows = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        valid_rows += 1
        for key in ("home_team_id", "away_team_id"):
            value = str(row.get(key) or "").strip()
            if value:
                counts[value] += 1
    if not counts or valid_rows <= 0:
        return None, 0.0
    team_id, count = counts.most_common(1)[0]
    return team_id, count / valid_rows


def _evidence_status(payload: dict[str, Any]) -> dict[str, Any]:
    kickoff = _parse_time(payload.get("kickoff_at"))
    captured = _parse_time(payload.get("evidence_captured_at"))
    cutoff = _parse_time(payload.get("source_cutoff_at"))

    reasons: list[str] = []
    if kickoff is None:
        reasons.append("INVALID_KICKOFF")
    if captured is None:
        reasons.append("INVALID_EVIDENCE_CAPTURE_TIME")
    elif kickoff is not None and captured >= kickoff:
        reasons.append("EVIDENCE_NOT_PREMATCH")
    if cutoff is None:
        reasons.append("INVALID_SOURCE_CUTOFF")
    elif kickoff is not None and cutoff >= kickoff:
        reasons.append("SOURCE_CUTOFF_NOT_PREMATCH")
    if not str(payload.get("match_key") or "").strip():
        reasons.append("MISSING_MATCH_KEY")

    recent = payload.get("recent_matches") if isinstance(payload.get("recent_matches"), dict) else {}
    home_rows = recent.get("home_team") if isinstance(recent.get("home_team"), list) else []
    away_rows = recent.get("away_team") if isinstance(recent.get("away_team"), list) else []
    home_valid = [row for row in home_rows if _valid_score_row(row, kickoff)]
    away_valid = [row for row in away_rows if _valid_score_row(row, kickoff)]
    if len(home_valid) < MIN_ROWS_PER_TEAM:
        reasons.append("HOME_HISTORY_TOO_SHORT")
    if len(away_valid) < MIN_ROWS_PER_TEAM:
        reasons.append("AWAY_HISTORY_TOO_SHORT")

    home_id, home_identity_share = _infer_subject_team_id(home_valid)
    away_id, away_identity_share = _infer_subject_team_id(away_valid)
    if home_id is None or home_identity_share < 0.8:
        reasons.append("HOME_TEAM_IDENTITY_UNSTABLE")
    if away_id is None or away_identity_share < 0.8:
        reasons.append("AWAY_TEAM_IDENTITY_UNSTABLE")
    if home_id and away_id and home_id == away_id:
        reasons.append("HOME_AWAY_IDENTITY_COLLISION")

    return {
        "usable": not reasons,
        "reasons": reasons,
        "home_valid_rows": len(home_valid),
        "away_valid_rows": len(away_valid),
        "home_subject_team_id": home_id,
        "away_subject_team_id": away_id,
        "home_identity_share": home_identity_share,
        "away_identity_share": away_identity_share,
    }


def _parse_score_90m(value: Any) -> tuple[int, int] | None:
    if value is None:
        return None
    match = SCORE_90M_RE.fullmatch(str(value).strip())
    if match is None:
        return None
    return int(match.group(1)), int(match.group(2))


def _is_after(later: datetime | None, earlier: datetime | None) -> bool:
    if later is None or earlier is None:
        return False
    try:
        return later > earlier
    except TypeError:
        return False


def _parse_nonnegative_int(value: Any) -> int | None:
    """Parse the integer score representation used by existing result artifacts."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, str) and re.fullmatch(r"\s*\d+\s*", value):
        return int(value.strip())
    return None


def _parse_numeric_score_pair(
    home_value: Any,
    away_value: Any,
) -> tuple[int, int] | None:
    home = _parse_nonnegative_int(home_value)
    away = _parse_nonnegative_int(away_value)
    if home is None or away is None:
        return None
    return home, away


RESULT_SCORE_FALLBACK_CONTRACT = {
    "status": "SUPPORTED",
    "basis": [
        "scripts/postmatch_result.py writes result_90m and home_score/away_score from the same verified score_90m pair",
        "scripts/prospective_settlement.py normalize_result accepts home_score/away_score when no score_90m field is present",
        "the audit still requires exact regulation_90m_plus_stoppage scope and valid verified_at after kickoff",
        "a numeric fallback pair is rejected when it conflicts with result_90m or an existing ledger actual",
    ],
    "fallback_fields": ["home_score", "away_score"],
    "equivalence_claim": "same regulation-90m canonical score pair only; no ledger backfill",
}


def _result_reconciliation_record(
    path: Path,
    payload: Any,
    reasons: Iterable[str],
    *,
    parse_error: str | None = None,
) -> dict[str, Any]:
    source = payload if isinstance(payload, dict) else {}
    raw_result = source.get("result_90m")
    record = {
        "path": _display_path(path),
        "file_match_key": path.stem,
        "match_key": str(source.get("match_key") or "").strip() or None,
        "raw_result_90m": {
            "type": type(raw_result).__name__,
            "value": raw_result,
        },
        "home_score": source.get("home_score"),
        "away_score": source.get("away_score"),
        "scope": source.get("scope"),
        "source": source.get("source"),
        "source_url": source.get("source_url"),
        "verification_quality": source.get("verification_quality"),
        "kickoff": source.get("kickoff_at") or source.get("kickoff_local"),
        "verified_at": source.get("verified_at"),
        "rejection_reasons": sorted(set(str(reason) for reason in reasons)),
    }
    if parse_error:
        record["parse_error"] = parse_error
    return record


def _authoritative_result_status(payload: dict[str, Any]) -> dict[str, Any]:
    match_key = str(payload.get("match_key") or "").strip()
    scope = str(payload.get("scope") or "").strip()
    kickoff = _parse_time(payload.get("kickoff_at") or payload.get("kickoff_local"))
    verified = _parse_time(payload.get("verified_at"))
    raw_result = payload.get("result_90m")
    score = _parse_score_90m(raw_result)
    numeric_fields_present = payload.get("home_score") is not None or payload.get(
        "away_score"
    ) is not None
    numeric_pair = _parse_numeric_score_pair(
        payload.get("home_score"), payload.get("away_score")
    )
    score_source = "result_90m" if score is not None else "unavailable"

    reasons: list[str] = []
    if not match_key:
        reasons.append("RESULT_MISSING_MATCH_KEY")
    if scope != RESULT_SCOPE:
        reasons.append("RESULT_SCOPE_NOT_REGULATION_90M")
    if score is None:
        if raw_result is None or (
            isinstance(raw_result, str) and not raw_result.strip()
        ):
            if numeric_pair is not None:
                score = numeric_pair
                score_source = "home_score_away_score_contract_fallback"
            else:
                reasons.append("RESULT_90M_UNPARSEABLE")
        else:
            reasons.append("RESULT_90M_UNPARSEABLE")
    if score is not None and numeric_fields_present and numeric_pair != score:
        reasons.append("RESULT_SCORE_FIELD_CONFLICT")
    if verified is None:
        reasons.append("INVALID_RESULT_VERIFIED_AT")
    if kickoff is None:
        reasons.append("INVALID_RESULT_KICKOFF")
    elif verified is not None and not _is_after(verified, kickoff):
        reasons.append("VERIFIED_AT_NOT_AFTER_KICKOFF")

    return {
        "valid": not reasons,
        "reasons": reasons,
        "match_key": match_key,
        "kickoff_at": payload.get("kickoff_at") or payload.get("kickoff_local"),
        "verified_at": payload.get("verified_at"),
        "result_90m": raw_result,
        "score_pair": score,
        "score_source": score_source,
        "fallback_used": score_source == "home_score_away_score_contract_fallback",
    }


def _load_authoritative_results(
    root: Path,
) -> tuple[
    dict[str, dict[str, Any]],
    int,
    Counter[str],
    list[dict[str, Any]],
]:
    results: dict[str, dict[str, Any]] = {}
    failure_reasons: Counter[str] = Counter()
    rejected_records: list[dict[str, Any]] = []
    result_files = sorted(root.glob("*.json"))
    for path in result_files:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            failure_reasons["INVALID_RESULT_JSON"] += 1
            rejected_records.append(
                _result_reconciliation_record(
                    path,
                    {},
                    ["INVALID_RESULT_JSON"],
                    parse_error="INVALID_RESULT_JSON",
                )
            )
            continue
        if not isinstance(payload, dict):
            failure_reasons["INVALID_RESULT_OBJECT"] += 1
            rejected_records.append(
                _result_reconciliation_record(
                    path,
                    payload,
                    ["INVALID_RESULT_OBJECT"],
                    parse_error="INVALID_RESULT_OBJECT",
                )
            )
            continue
        status = _authoritative_result_status(payload)
        for reason in status["reasons"]:
            failure_reasons[reason] += 1
        if not status["valid"]:
            rejected_records.append(
                _result_reconciliation_record(path, payload, status["reasons"])
            )
            continue
        match_key = status["match_key"]
        if match_key in results:
            failure_reasons["DUPLICATE_RESULT_MATCH_KEY"] += 1
            rejected_records.append(
                _result_reconciliation_record(
                    path, payload, ["DUPLICATE_RESULT_MATCH_KEY"]
                )
            )
            continue
        results[match_key] = {
            "path": _display_path(path),
            "_source_path": path,
            "_payload": payload,
            **status,
        }
    return results, len(result_files), failure_reasons, rejected_records


def _ledger_match_key(payload: dict[str, Any]) -> str:
    identity = (
        payload.get("match_identity")
        if isinstance(payload.get("match_identity"), dict)
        else {}
    )
    return str(identity.get("match_key") or "").strip()


def _ledger_row_is_settled(payload: dict[str, Any]) -> bool:
    actual = payload.get("actual") if isinstance(payload.get("actual"), dict) else {}
    pair = _parse_numeric_score_pair(actual.get("home_score"), actual.get("away_score"))
    return pair is not None and bool(_ledger_match_key(payload))


def _load_ledger_sanity_reference(
    ledger_path: Path | None,
    evidence_records: dict[str, dict[str, Any]],
    result_root: Path,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    reference: dict[str, Any] = {
        "available": False,
        "scope": "SANITY_REFERENCE_ONLY_NOT_READINESS_SETTLEMENT_TRUTH",
        "basis": "ledger settled rows joined to authoritative result filenames only",
        "source": _display_path(ledger_path) if ledger_path is not None else None,
    }
    if ledger_path is None:
        reference["reason"] = "LEDGER_REFERENCE_NOT_REQUESTED_FOR_EXTERNAL_FIXTURE"
        return reference, {}
    if not ledger_path.is_file():
        reference["reason"] = "LEDGER_REFERENCE_NOT_FOUND"
        return reference, {}

    ledger_rows: dict[str, dict[str, Any]] = {}
    invalid_rows = 0
    duplicate_rows = 0
    try:
        lines = ledger_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        reference["reason"] = "LEDGER_REFERENCE_UNREADABLE"
        return reference, {}
    for line in lines:
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            invalid_rows += 1
            continue
        if not isinstance(payload, dict):
            invalid_rows += 1
            continue
        prediction_id = str(payload.get("prediction_id") or "").strip()
        if not prediction_id:
            invalid_rows += 1
            continue
        if prediction_id in ledger_rows:
            duplicate_rows += 1
            continue
        ledger_rows[prediction_id] = payload

    result_file_keys = {path.stem for path in result_root.glob("*.json")}
    represented_ids = set(evidence_records) & set(ledger_rows)
    settled_ids = {
        prediction_id
        for prediction_id in represented_ids
        if _ledger_row_is_settled(ledger_rows[prediction_id])
        and _ledger_match_key(ledger_rows[prediction_id])
        == evidence_records[prediction_id]["match_key"]
    }
    settled_with_result_files = {
        prediction_id
        for prediction_id in settled_ids
        if evidence_records[prediction_id]["match_key"] in result_file_keys
    }
    unique_matches = {
        evidence_records[prediction_id]["match_key"]
        for prediction_id in settled_with_result_files
        if evidence_records[prediction_id]["match_key"]
    }
    reference.update(
        {
            "available": True,
            "ledger_rows": len(ledger_rows),
            "invalid_ledger_rows": invalid_rows,
            "duplicate_ledger_rows": duplicate_rows,
            "evidence_prediction_ids_in_ledger": len(represented_ids),
            "settled_prediction_snapshots_in_ledger_with_result_files": len(
                settled_with_result_files
            ),
            "settled_unique_matches_in_ledger_with_result_files": len(unique_matches),
        }
    )
    return reference, ledger_rows


def _ledger_actuals_by_match_key(
    ledger_rows: dict[str, dict[str, Any]],
) -> dict[str, set[tuple[int, int]]]:
    actuals: dict[str, set[tuple[int, int]]] = {}
    for payload in ledger_rows.values():
        if not _ledger_row_is_settled(payload):
            continue
        match_key = _ledger_match_key(payload)
        actual = payload.get("actual") if isinstance(payload.get("actual"), dict) else {}
        pair = _parse_numeric_score_pair(actual.get("home_score"), actual.get("away_score"))
        if match_key and pair is not None:
            actuals.setdefault(match_key, set()).add(pair)
    return actuals


def _apply_ledger_result_conflicts(
    authoritative_results: dict[str, dict[str, Any]],
    rejected_records: list[dict[str, Any]],
    failure_reasons: Counter[str],
    ledger_rows: dict[str, dict[str, Any]],
) -> set[str]:
    """Reject a canonical result only when an existing ledger actual disagrees."""
    actuals_by_match_key = _ledger_actuals_by_match_key(ledger_rows)
    conflict_keys: set[str] = set()
    for match_key, result in list(authoritative_results.items()):
        score_pair = result.get("score_pair")
        ledger_pairs = actuals_by_match_key.get(match_key, set())
        if score_pair is None or not ledger_pairs or all(
            score_pair == ledger_pair for ledger_pair in ledger_pairs
        ):
            continue
        conflict_keys.add(match_key)
        failure_reasons["RESULT_SCORE_CONFLICTS_WITH_LEDGER_ACTUAL"] += 1
        rejected_records.append(
            _result_reconciliation_record(
                result["_source_path"],
                result["_payload"],
                ["RESULT_SCORE_CONFLICTS_WITH_LEDGER_ACTUAL"],
            )
        )
        del authoritative_results[match_key]
    return conflict_keys


def _annotate_rejected_results(
    rejected_records: list[dict[str, Any]],
    evidence_records: dict[str, dict[str, Any]],
    ledger_rows: dict[str, dict[str, Any]],
) -> None:
    evidence_counts: Counter[str] = Counter()
    evidence_ids_by_match_key: dict[str, set[str]] = {}
    for prediction_id, evidence in evidence_records.items():
        match_key = str(evidence.get("match_key") or "").strip()
        if not match_key:
            continue
        evidence_counts[match_key] += 1
        evidence_ids_by_match_key.setdefault(match_key, set()).add(prediction_id)

    ledger_ids_by_match_key: dict[str, set[str]] = {}
    for prediction_id, payload in ledger_rows.items():
        match_key = _ledger_match_key(payload)
        if match_key:
            ledger_ids_by_match_key.setdefault(match_key, set()).add(prediction_id)

    actuals_by_match_key = _ledger_actuals_by_match_key(ledger_rows)
    for record in rejected_records:
        match_key = str(record.get("match_key") or "").strip()
        evidence_ids = evidence_ids_by_match_key.get(match_key, set())
        ledger_ids = ledger_ids_by_match_key.get(match_key, set())
        intersection_ids = evidence_ids & ledger_ids
        record["evidence_snapshot_count"] = evidence_counts.get(match_key, 0)
        record["ledger_snapshot_count"] = len(ledger_ids)
        record["evidence_ledger_intersection_snapshot_count"] = len(intersection_ids)
        record["ledger_actual"] = [
            {"home_score": home, "away_score": away}
            for home, away in sorted(actuals_by_match_key.get(match_key, set()))
        ]
        record["in_evidence_ledger_intersection"] = bool(intersection_ids)


def _reconciliation_explanation(
    *,
    sanity_reference: dict[str, Any],
    authoritative_results: dict[str, dict[str, Any]],
    rejected_records: list[dict[str, Any]],
) -> dict[str, Any]:
    relevant_by_match_key: dict[str, dict[str, Any]] = {}
    for record in rejected_records:
        match_key = str(record.get("match_key") or "").strip()
        if (
            match_key
            and record.get("in_evidence_ledger_intersection")
            and match_key not in authoritative_results
        ):
            relevant_by_match_key.setdefault(match_key, record)

    rejected_match_keys = sorted(relevant_by_match_key)
    explained_snapshot_delta = sum(
        int(record.get("evidence_ledger_intersection_snapshot_count") or 0)
        for record in relevant_by_match_key.values()
    )
    reference_available = bool(sanity_reference.get("available"))
    if reference_available:
        strict_snapshots = int(
            sanity_reference.get("strict_settled_usable_prediction_snapshots", 0)
        )
        strict_unique = int(
            sanity_reference.get("strict_settled_usable_unique_matches", 0)
        )
        reference_snapshots = int(
            sanity_reference.get(
                "settled_prediction_snapshots_in_ledger_with_result_files", 0
            )
        )
        reference_unique = int(
            sanity_reference.get("settled_unique_matches_in_ledger_with_result_files", 0)
        )
        sanity_snapshots_minus_strict = reference_snapshots - strict_snapshots
        sanity_unique_minus_strict = reference_unique - strict_unique
        residual_snapshot = sanity_snapshots_minus_strict - explained_snapshot_delta
        residual_unique = sanity_unique_minus_strict - len(rejected_match_keys)
    else:
        strict_snapshots = None
        strict_unique = None
        reference_snapshots = None
        reference_unique = None
        sanity_snapshots_minus_strict = None
        sanity_unique_minus_strict = None
        residual_snapshot = None
        residual_unique = None

    return {
        "sanity_reference_available": reference_available,
        "sanity_settled_prediction_snapshots": reference_snapshots,
        "sanity_settled_unique_matches": reference_unique,
        "strict_settled_usable_prediction_snapshots": strict_snapshots,
        "strict_settled_usable_unique_matches": strict_unique,
        "sanity_snapshots_minus_strict_snapshots": sanity_snapshots_minus_strict,
        "sanity_unique_minus_strict_unique": sanity_unique_minus_strict,
        "rejected_strict_result_match_keys_in_evidence_ledger_intersection": rejected_match_keys,
        "explained_unique_delta": len(rejected_match_keys),
        "explained_snapshot_delta": explained_snapshot_delta,
        "residual_unique_mismatch": residual_unique,
        "residual_snapshot_mismatch": residual_snapshot,
        "reconciliation_complete": bool(
            reference_available and residual_unique == 0 and residual_snapshot == 0
        ),
        "strict_rejected_authoritative_results": rejected_records,
    }


def run(
    *,
    evidence_root: Path = DEFAULT_EVIDENCE_ROOT,
    result_root: Path = DEFAULT_RESULT_ROOT,
    pinned_manifest: Path = DEFAULT_PINNED_MANIFEST,
    ledger_path: Path | None = None,
) -> dict[str, Any]:
    (
        authoritative_results,
        result_file_count,
        result_failure_reasons,
        rejected_result_records,
    ) = _load_authoritative_results(result_root)
    reason_counts: Counter[str] = Counter()
    settlement_failure_reasons: Counter[str] = Counter()
    evidence_records: dict[str, dict[str, Any]] = {}
    valid_row_counts: list[int] = []
    provider_counts: Counter[str] = Counter()
    evidence_paths = sorted(evidence_root.glob("*.json"))

    for path in evidence_paths:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            reason_counts["INVALID_EVIDENCE_JSON"] += 1
            continue
        if not isinstance(payload, dict):
            reason_counts["INVALID_EVIDENCE_OBJECT"] += 1
            continue
        prediction_id = str(payload.get("prediction_id") or "").strip()
        if not prediction_id:
            reason_counts["MISSING_PREDICTION_ID"] += 1
            continue
        if prediction_id in evidence_records:
            reason_counts["DUPLICATE_PREDICTION_ID"] += 1
            continue
        status = _evidence_status(payload)
        for reason in status["reasons"]:
            reason_counts[reason] += 1
        if status["usable"]:
            valid_row_counts.extend(
                [status["home_valid_rows"], status["away_valid_rows"]]
            )
            provider_counts[str(payload.get("source_provider") or "UNKNOWN")] += 1
        evidence_records[prediction_id] = {
            "path": _display_path(path),
            "match_id": str(payload.get("match_id") or ""),
            "match_key": str(payload.get("match_key") or "").strip(),
            "kickoff_at": payload.get("kickoff_at"),
            "usable": status["usable"],
            **status,
        }

    usable_ids = {pid for pid, row in evidence_records.items() if row["usable"]}
    if ledger_path is None:
        same_default_roots = (
            evidence_root.resolve() == DEFAULT_EVIDENCE_ROOT.resolve()
            and result_root.resolve() == DEFAULT_RESULT_ROOT.resolve()
        )
        ledger_path = DEFAULT_LEDGER if same_default_roots else None
    sanity_reference, ledger_rows = _load_ledger_sanity_reference(
        ledger_path, evidence_records, result_root
    )
    conflict_keys = _apply_ledger_result_conflicts(
        authoritative_results,
        rejected_result_records,
        result_failure_reasons,
        ledger_rows,
    )
    _annotate_rejected_results(
        rejected_result_records,
        evidence_records,
        ledger_rows,
    )

    settled_ids: set[str] = set()
    for prediction_id, row in evidence_records.items():
        result = authoritative_results.get(row["match_key"])
        if result is None:
            continue
        if not _is_after(
            _parse_time(result["verified_at"]),
            _parse_time(row["kickoff_at"]),
        ):
            settlement_failure_reasons["RESULT_NOT_AFTER_EVIDENCE_KICKOFF"] += 1
            continue
        settled_ids.add(prediction_id)
    settled_usable = settled_ids & usable_ids
    settled_usable_match_keys = {
        evidence_records[prediction_id]["match_key"]
        for prediction_id in settled_usable
        if evidence_records[prediction_id]["match_key"]
    }

    try:
        pinned = json.loads(pinned_manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        pinned = {}
    if not isinstance(pinned, dict):
        pinned = {}
    pinned_ids = {
        str(row.get("prediction_id") or "")
        for row in (pinned.get("selected_records") or [])
        if isinstance(row, dict) and str(row.get("prediction_id") or "")
    }
    pinned_verified_ids = {
        str(value)
        for value in (pinned.get("verified_prediction_ids") or [])
        if str(value)
    }

    all_prospective = {
        "total_evidence_files": len(evidence_paths),
        "football_evidence_files": len(evidence_paths),
        "evidence_records": len(evidence_records),
        "usable_structural_evidence": len(usable_ids),
        "authoritative_result_files": result_file_count,
        "valid_authoritative_results": len(authoritative_results),
        "settled_prediction_snapshots": len(settled_ids),
        "settled_usable_prediction_snapshots": len(settled_usable),
        "settled_usable_unique_matches": len(settled_usable_match_keys),
        "settled_with_any_evidence": len(settled_ids),
        "settled_with_usable_structural_evidence": len(settled_usable),
        "canonical_score_fallbacks": sum(
            1
            for result in authoritative_results.values()
            if result.get("fallback_used")
        ),
    }

    threshold_decision = (
        "STRUCTURAL_OFFLINE_EXPERIMENT_READY"
        if len(settled_usable_match_keys) >= MIN_SETTLED_USABLE
        else "STRUCTURAL_EVIDENCE_SAMPLE_INSUFFICIENT"
    )

    sanity_mismatches: list[dict[str, int | str]] = []
    if sanity_reference["available"]:
        comparisons = (
            (
                "settled_usable_prediction_snapshots",
                "settled_prediction_snapshots_in_ledger_with_result_files",
            ),
            (
                "settled_usable_unique_matches",
                "settled_unique_matches_in_ledger_with_result_files",
            ),
        )
        for formal_key, reference_key in comparisons:
            formal_value = int(all_prospective[formal_key])
            reference_value = int(sanity_reference[reference_key])
            if formal_value != reference_value:
                sanity_mismatches.append(
                    {
                        "metric": formal_key,
                        "formal_value": formal_value,
                        "reference_value": reference_value,
                        "difference": reference_value - formal_value,
                    }
                )
    sanity_reference["material_mismatch"] = bool(sanity_mismatches)
    sanity_reference["mismatches"] = sanity_mismatches
    sanity_reference["strict_settled_usable_prediction_snapshots"] = len(settled_usable)
    sanity_reference["strict_settled_usable_unique_matches"] = len(
        settled_usable_match_keys
    )
    reconciliation = _reconciliation_explanation(
        sanity_reference=sanity_reference,
        authoritative_results=authoritative_results,
        rejected_records=rejected_result_records,
    )

    fail_closed_reasons: list[str] = []
    if reconciliation["sanity_reference_available"] and (
        reconciliation["residual_unique_mismatch"] != 0
        or reconciliation["residual_snapshot_mismatch"] != 0
    ):
        fail_closed_reasons.append("UNEXPLAINED_SANITY_RESIDUAL_MISMATCH")
    if conflict_keys or any(
        reason in result_failure_reasons
        for reason in (
            "RESULT_SCORE_FIELD_CONFLICT",
            "RESULT_SCORE_CONFLICTS_WITH_LEDGER_ACTUAL",
        )
    ):
        fail_closed_reasons.append("RESULT_FIELD_CONFLICT")
    if RESULT_SCORE_FALLBACK_CONTRACT.get("status") != "SUPPORTED":
        fail_closed_reasons.append("RESULT_SCORE_FALLBACK_CONTRACT_AMBIGUOUS")
    fail_closed = bool(fail_closed_reasons)
    decision = (
        "STRUCTURAL_EVIDENCE_SAMPLE_INSUFFICIENT"
        if fail_closed
        else threshold_decision
    )

    pinned_verified_usable_ids = pinned_verified_ids & usable_ids
    pinned_verified_settled_usable_ids = pinned_verified_ids & settled_usable
    pinned_verified_settled_usable_match_keys = {
        evidence_records[prediction_id]["match_key"]
        for prediction_id in pinned_verified_settled_usable_ids
        if evidence_records[prediction_id]["match_key"]
    }
    coverage = {
        **all_prospective,
        "all_prospective": dict(all_prospective),
        "gate_scope": "ALL_PROSPECTIVE_EVIDENCE_NOT_PINNED_COHORT_LIMITED",
        "settlement_truth_source": "data/postmatch_automation/results/*.json",
        "postmatch_reviews_used_for_readiness": False,
        "pinned_unique": len(pinned_ids),
        "pinned_with_any_evidence": len(pinned_ids & set(evidence_records)),
        "pinned_verified": len(pinned_verified_ids),
        "pinned_verified_with_usable_evidence": len(pinned_verified_usable_ids),
        "pinned_verified_with_settled_usable_snapshots": len(
            pinned_verified_settled_usable_ids
        ),
        "pinned_verified_with_settled_usable_unique_matches": len(
            pinned_verified_settled_usable_match_keys
        ),
        "median_valid_rows_per_team_side": (
            median(valid_row_counts) if valid_row_counts else None
        ),
        "provider_counts_for_usable": dict(sorted(provider_counts.items())),
    }
    return {
        "schema_version": "structural_football_evidence_coverage.v3",
        "status": "FAIL_CLOSED" if fail_closed else "READY_FOR_ACCEPTANCE",
        "decision": decision,
        "threshold_decision": threshold_decision,
        "minimum_settled_usable_required": MIN_SETTLED_USABLE,
        "coverage": coverage,
        "failure_reasons": dict(sorted(reason_counts.items())),
        "authoritative_result_failure_reasons": dict(
            sorted(result_failure_reasons.items())
        ),
        "settlement_failure_reasons": dict(sorted(settlement_failure_reasons.items())),
        "independent_sanity_reference": sanity_reference,
        "reconciliation": reconciliation,
        "result_score_fallback_contract": RESULT_SCORE_FALLBACK_CONTRACT,
        "gate": {
            "settled_usable_unique_matches": len(settled_usable_match_keys),
            "threshold_passed": threshold_decision
            == "STRUCTURAL_OFFLINE_EXPERIMENT_READY",
            "fail_closed": fail_closed,
            "fail_closed_reason": ";".join(fail_closed_reasons) if fail_closed else None,
            "final_decision": decision,
        },
        "integrity_contract": {
            "evidence_capture_must_be_prematch": True,
            "source_cutoff_must_be_prematch": True,
            "minimum_valid_rows_per_team": MIN_ROWS_PER_TEAM,
            "subject_team_id_share_minimum": 0.8,
            "authoritative_result_scope": RESULT_SCOPE,
            "authoritative_result_90m_parse_required": True,
            "numeric_score_fallback_allowed_only_under_contract": True,
            "result_score_fallback_contract_status": RESULT_SCORE_FALLBACK_CONTRACT["status"],
            "authoritative_verified_at_must_be_after_kickoff": True,
            "postmatch_review_used_for_readiness": False,
            "postmatch_result_used_for_generation": False,
        },
        "next_step": (
            "FAIL CLOSED: resolve unexplained settlement reconciliation or result-field conflicts before any offline experiment; no model change"
            if fail_closed
            else (
                "settled usable unique-match threshold evaluated from authoritative results; no model change in this PR"
                if decision == "STRUCTURAL_OFFLINE_EXPERIMENT_READY"
                else "do not backfill or fabricate history; keep prospective structural evidence capture and wait for >=50 settled usable unique matches"
            )
        ),
        "production_changes": "NO",
        "promotion": "NO",
    }


def build_report(result: dict[str, Any]) -> str:
    """Build a concise, recoverable report from one audit result."""
    coverage = (
        result.get("coverage")
        if isinstance(result.get("coverage"), dict)
        else {}
    )
    all_prospective = (
        coverage.get("all_prospective")
        if isinstance(coverage.get("all_prospective"), dict)
        else coverage
    )
    gate = result.get("gate") if isinstance(result.get("gate"), dict) else {}
    sanity = (
        result.get("independent_sanity_reference")
        if isinstance(result.get("independent_sanity_reference"), dict)
        else {}
    )
    reconciliation = (
        result.get("reconciliation")
        if isinstance(result.get("reconciliation"), dict)
        else {}
    )
    integrity = (
        result.get("integrity_contract")
        if isinstance(result.get("integrity_contract"), dict)
        else {}
    )
    lines = [
        "# Structural football evidence coverage audit",
        "",
        f"- status: `{result.get('status')}`",
        f"- threshold decision: `{result.get('threshold_decision')}`",
        f"- final Gate decision: `{result.get('decision')}`",
        f"- minimum settled usable unique matches required: `{result.get('minimum_settled_usable_required')}`",
        "",
        "## ALL_PROSPECTIVE",
        "",
        "The readiness gate uses all current prospective evidence and authoritative results; it is not limited to the pinned cohort.",
    ]
    for key in (
        "total_evidence_files",
        "football_evidence_files",
        "evidence_records",
        "usable_structural_evidence",
        "authoritative_result_files",
        "valid_authoritative_results",
        "settled_prediction_snapshots",
        "settled_usable_prediction_snapshots",
        "settled_usable_unique_matches",
        "settled_with_any_evidence",
        "settled_with_usable_structural_evidence",
        "canonical_score_fallbacks",
    ):
        lines.append(f"- {key}: `{all_prospective.get(key)}`")

    lines.extend(
        [
            "",
            "## Authoritative settlement",
            "",
            f"- source: `{coverage.get('settlement_truth_source')}`",
            f"- postmatch_reviews_used_for_readiness: `{coverage.get('postmatch_reviews_used_for_readiness')}`",
            "- join: `evidence.match_key == authoritative_result.match_key`",
            "- readiness unit: `one match = one unique match_key`; snapshots are reported separately",
            f"- authoritative_result_failure_reasons: `{json.dumps(result.get('authoritative_result_failure_reasons', {}), ensure_ascii=False, sort_keys=True)}`",
            f"- settlement_failure_reasons: `{json.dumps(result.get('settlement_failure_reasons', {}), ensure_ascii=False, sort_keys=True)}`",
            f"- result_score_fallback_contract: `{json.dumps(result.get('result_score_fallback_contract', {}), ensure_ascii=False, sort_keys=True)}`",
            "",
            "## PINNED_COHORT_ONLY",
            "",
            f"- pinned_unique: `{coverage.get('pinned_unique')}`",
            f"- pinned_with_any_evidence: `{coverage.get('pinned_with_any_evidence')}`",
            f"- pinned_verified: `{coverage.get('pinned_verified')}`",
            f"- pinned_verified_with_usable_evidence: `{coverage.get('pinned_verified_with_usable_evidence')}`",
            f"- pinned_verified_with_settled_usable_snapshots: `{coverage.get('pinned_verified_with_settled_usable_snapshots')}`",
            f"- pinned_verified_with_settled_usable_unique_matches: `{coverage.get('pinned_verified_with_settled_usable_unique_matches')}`",
            "",
            "## Settlement reconciliation",
            "",
            "The historical result store is used only as `ENVIRONMENT_ONLY / NO_PREMATCH_MODEL_COMPARISON`-style sanity evidence. It is not readiness settlement truth and is never used to backfill a result.",
            f"- sanity_unique_minus_strict_unique: `{reconciliation.get('sanity_unique_minus_strict_unique')}`",
            f"- sanity_snapshots_minus_strict_snapshots: `{reconciliation.get('sanity_snapshots_minus_strict_snapshots')}`",
            f"- explained_unique_delta: `{reconciliation.get('explained_unique_delta')}`",
            f"- explained_snapshot_delta: `{reconciliation.get('explained_snapshot_delta')}`",
            f"- residual_unique_mismatch: `{reconciliation.get('residual_unique_mismatch')}`",
            f"- residual_snapshot_mismatch: `{reconciliation.get('residual_snapshot_mismatch')}`",
            f"- reconciliation_complete: `{reconciliation.get('reconciliation_complete')}`",
            f"- rejected_strict_result_match_keys_in_evidence_ledger_intersection: `{json.dumps(reconciliation.get('rejected_strict_result_match_keys_in_evidence_ledger_intersection', []), ensure_ascii=False)}`",
            "",
            "### strict_rejected_authoritative_results",
            "",
            "Every strict-rejected result file is listed below with its raw score field and the corresponding evidence/ledger intersection counts.",
            "",
            "```json",
            json.dumps(
                reconciliation.get("strict_rejected_authoritative_results", []),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            ),
            "```",
            "",
            "## Gate and independent sanity reference",
            "",
            f"- threshold_passed: `{gate.get('threshold_passed')}`",
            f"- fail_closed: `{gate.get('fail_closed')}`",
            f"- fail_closed_reason: `{gate.get('fail_closed_reason')}`",
            f"- sanity_reference: `{json.dumps(sanity, ensure_ascii=False, sort_keys=True)}`",
            "",
            "## Prematch evidence integrity",
            "",
            f"- contract: `{json.dumps(integrity, ensure_ascii=False, sort_keys=True)}`",
            f"- failure_reasons: `{json.dumps(result.get('failure_reasons', {}), ensure_ascii=False, sort_keys=True)}`",
            "",
            "## Controls",
            "",
            f"- production_changes: `{result.get('production_changes')}`",
            f"- promotion: `{result.get('promotion')}`",
            f"- next_step: {result.get('next_step')}",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    result = run()
    text = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(build_report(result), encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
