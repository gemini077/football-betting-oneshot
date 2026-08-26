#!/usr/bin/env python3
"""Evaluate the unattended MVP runtime and persist exception-only health state."""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

# The production entry point is executed as ``python scripts/...py`` while
# focused tests import it as ``scripts.production_health_watch``.  Keep the
# existing script-local absolute imports usable in both modes.
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from prospective_settlement import is_formally_eligible


BASE_DIR = Path(__file__).resolve().parents[1]
SHANGHAI = ZoneInfo("Asia/Shanghai")
HEALTHY = "HEALTHY"
WATCH = "WATCH"
ALERT = "ALERT"
FINAL_RESULT_SCOPES = {"regulation_90m_plus_stoppage", "90m", "regulation_90m"}
FROZEN_STATUSES = {"formal", "frozen", "FROZEN"}
EXACT_SCORE_MIN_SAMPLE_COUNT = 8
EXACT_SCORE_DOMINANT_COUNT_THRESHOLD = 7
EXACT_SCORE_DOMINANT_SHARE_THRESHOLD = 0.875
EXACT_SCORE_LAMBDA_GAP_THRESHOLD = 0.5
EXACT_SCORE_COMPRESSED_COUNT_THRESHOLD = 7
EXACT_SCORE_COMPRESSED_SHARE_THRESHOLD = 0.75


def _normalise_top1_score(value: Any) -> str | None:
    if isinstance(value, dict):
        if "home_score" in value or "away_score" in value:
            value = (value.get("home_score"), value.get("away_score"))
        else:
            for key in ("score", "unique_score", "score_top1", "formal_unique_score", "value"):
                if key in value:
                    value = value[key]
                    break
    if isinstance(value, (tuple, list)) and len(value) == 2:
        value = f"{value[0]}-{value[1]}"
    match = re.fullmatch(r"\s*(\d+)\s*[-:]\s*(\d+)\s*", str(value or ""))
    return f"{int(match.group(1))}-{int(match.group(2))}" if match else None


def _stored_top1_score(record: dict[str, Any]) -> str | None:
    output = record.get("prediction_output")
    containers = [record, output] if isinstance(output, dict) else [record]
    for container in containers:
        for key in ("unique_score", "score_top1", "formal_unique_score"):
            score = _normalise_top1_score(container.get(key))
            if score:
                return score
        for key in ("top_scores", "score_distribution", "score_probabilities", "score_matrix"):
            rows = container.get(key)
            if isinstance(rows, list) and rows:
                score = _normalise_top1_score(rows[0])
                if score:
                    return score
    return None


def _lambda_gap(record: dict[str, Any]) -> float | None:
    try:
        home = float(record.get("lambda_home"))
        away = float(record.get("lambda_away"))
    except (TypeError, ValueError):
        return None
    if not math.isfinite(home) or not math.isfinite(away):
        return None
    return abs(home - away)


def evaluate_exact_score_health(formal_records: list[dict[str, Any]]) -> dict[str, Any]:
    """Evaluate frozen Champion BASE/DEEP score-selector and lambda guardrails."""
    eligible_records: list[dict[str, Any]] = []
    for record in formal_records:
        if not isinstance(record, dict):
            continue
        try:
            eligible = is_formally_eligible(record)
        except Exception:
            eligible = False
        if eligible:
            eligible_records.append(record)

    scored_records = [
        (record, score)
        for record in eligible_records
        if (score := _stored_top1_score(record))
    ]
    scores = [score for _, score in scored_records]
    counts = Counter(scores)
    ordered_counts = counts.most_common(2)
    dominant_score = ordered_counts[0][0] if ordered_counts else None
    dominant_count = ordered_counts[0][1] if ordered_counts else 0
    runner_up_count = ordered_counts[1][1] if len(ordered_counts) > 1 else 0
    sample_count = len(scores)
    dominant_share = round(dominant_count / sample_count, 6) if sample_count else None
    runner_up_share = round(runner_up_count / sample_count, 6) if sample_count else None
    dominant_share_gap = (
        round(dominant_share - runner_up_share, 6)
        if dominant_share is not None and runner_up_share is not None
        else dominant_share
    )
    lambda_gaps = [_lambda_gap(record) for record, _ in scored_records]
    lambda_gap_sample_count = sum(gap is not None for gap in lambda_gaps)
    compressed_count = sum(
        gap is not None and gap < EXACT_SCORE_LAMBDA_GAP_THRESHOLD
        for gap in lambda_gaps
    )
    compressed_share = (
        round(compressed_count / lambda_gap_sample_count, 6)
        if lambda_gap_sample_count
        else None
    )

    reasons: list[str] = []
    if (
        sample_count >= EXACT_SCORE_MIN_SAMPLE_COUNT
        and dominant_count >= EXACT_SCORE_DOMINANT_COUNT_THRESHOLD
        and (dominant_share or 0.0) >= EXACT_SCORE_DOMINANT_SHARE_THRESHOLD
    ):
        reasons.append("SCORE_SELECTOR_COLLAPSE")
    if (
        lambda_gap_sample_count >= EXACT_SCORE_MIN_SAMPLE_COUNT
        and compressed_count >= EXACT_SCORE_COMPRESSED_COUNT_THRESHOLD
        and (compressed_share or 0.0) >= EXACT_SCORE_COMPRESSED_SHARE_THRESHOLD
    ):
        reasons.append("LAMBDA_COMPRESSION")

    if sample_count < EXACT_SCORE_MIN_SAMPLE_COUNT:
        status = "INSUFFICIENT_SAMPLE"
    elif reasons:
        status = ALERT
    else:
        status = HEALTHY

    return {
        "schema_version": "1.0",
        "sample_count": sample_count,
        "eligible_record_count": len(eligible_records),
        "missing_top1_count": len(eligible_records) - sample_count,
        "dominant_score": dominant_score,
        "dominant_count": dominant_count,
        "dominant_share": dominant_share,
        "compressed_count": compressed_count,
        "compressed_share": compressed_share,
        "lambda_gap_sample_count": lambda_gap_sample_count,
        "missing_lambda_gap_count": sample_count - lambda_gap_sample_count,
        "runner_up_count": runner_up_count,
        "runner_up_share": runner_up_share,
        "dominant_share_gap": dominant_share_gap,
        "gap_threshold": EXACT_SCORE_LAMBDA_GAP_THRESHOLD,
        "compression_rule": "abs(lambda_home-lambda_away) < gap_threshold",
        "dominant_share_threshold": EXACT_SCORE_DOMINANT_SHARE_THRESHOLD,
        "compressed_count_threshold": EXACT_SCORE_COMPRESSED_COUNT_THRESHOLD,
        "compressed_share_threshold": EXACT_SCORE_COMPRESSED_SHARE_THRESHOLD,
        "status": status,
        "reasons": reasons,
    }


def _now(value: datetime | None = None) -> datetime:
    current = value or datetime.now(SHANGHAI)
    if current.tzinfo is None:
        return current.replace(tzinfo=SHANGHAI)
    return current.astimezone(SHANGHAI)


def _parse_at(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        text = str(value).strip().replace("Z", "+00:00")
        parsed = datetime.fromisoformat(text)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=SHANGHAI)
    return parsed.astimezone(SHANGHAI)


def _json(path: Path, *, required: tuple[str, ...] = ()) -> tuple[dict[str, Any] | None, str | None]:
    if not path.is_file():
        return None, "MISSING"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None, "MALFORMED_JSON"
    if not isinstance(value, dict):
        return None, "INVALID_SCHEMA"
    missing = [field for field in required if field not in value]
    if missing:
        return None, "MISSING_SCHEMA"
    return value, None


def _json_files(directory: Path) -> tuple[list[tuple[Path, dict[str, Any]]], bool]:
    """Read a durable JSON directory without silently dropping bad files."""
    if not directory.is_dir():
        return [], False
    rows: list[tuple[Path, dict[str, Any]]] = []
    valid = True
    for path in sorted(directory.glob("*.json")):
        payload, error = _json(path)
        if error or payload is None:
            valid = False
            continue
        rows.append((path, payload))
    return rows, valid


def _jsonl(path: Path) -> tuple[list[dict[str, Any]], bool]:
    if not path.is_file():
        return [], False
    rows: list[dict[str, Any]] = []
    valid = True
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError):
        return [], False
    for line in lines:
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            valid = False
            continue
        if not isinstance(value, dict):
            valid = False
            continue
        rows.append(value)
    return rows, valid


def _reason_once(reasons: list[str], reason: str) -> None:
    if reason not in reasons:
        reasons.append(reason)


def _identity(value: dict[str, Any], *, fixture: bool = False) -> str:
    fields = ("matchId", "match_id") if fixture else ("match_id", "matchId")
    for field in fields:
        if value.get(field) not in (None, ""):
            return f"match_id:{value[field]}"
    if value.get("match_key") not in (None, ""):
        return f"match_key:{value['match_key']}"
    if value.get("match_num") not in (None, "") or value.get("matchNum") not in (None, ""):
        return f"match_num:{value.get('match_num') or value.get('matchNum')}"
    home = value.get("home") or value.get("homeTeam") or ""
    away = value.get("away") or value.get("awayTeam") or ""
    kickoff = value.get("kickoff") or value.get("kickoff_at") or value.get("matchDate") or ""
    return f"teams:{home}|{away}|{kickoff}"


def _is_final_result(payload: dict[str, Any]) -> bool:
    status = str(payload.get("status") or "").strip().lower()
    if status in {"live", "in_progress", "scheduled", "pending", "result_pending"}:
        return False
    if status and status not in {"result_verified", "verified", "reviewed", "manual_review_required"}:
        return False
    if str(payload.get("scope") or "").strip() not in FINAL_RESULT_SCOPES:
        return False
    if not (payload.get("verified_at") or payload.get("result_verified_at")):
        return False
    return any(
        payload.get(field) not in (None, "")
        for field in ("score_90m", "result_90m", "home_score_90m", "home_score")
    )


def _result_keys(path: Path, payload: dict[str, Any]) -> set[str]:
    keys = {path.stem}
    for field in ("match_key", "canonical_match_id", "prediction_match_id", "match_id", "sporttery_match_id"):
        if payload.get(field) not in (None, ""):
            keys.add(str(payload[field]))
    return keys


def _recursive_conflict_reasons(value: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = re.sub(r"[^A-Z0-9]+", "_", str(key).upper()).strip("_")
            if normalized in {"RESULT_CONFLICT", "RESULT_CONFLICTS"} and child:
                found.add("RESULT_CONFLICT")
            if normalized in {
                "IMMUTABLE_PREDICTION_CONFLICT",
                "PREDICTION_CONFLICT",
                "PREDICTION_CONFLICTS",
            } and child:
                found.add("IMMUTABLE_PREDICTION_CONFLICT")
            if normalized == "FAILURE_REASONS" and isinstance(child, dict) and child.get("RESULT_CONFLICT"):
                found.add("RESULT_CONFLICT")
            found.update(_recursive_conflict_reasons(child))
    elif isinstance(value, list):
        for child in value:
            found.update(_recursive_conflict_reasons(child))
    elif isinstance(value, str):
        normalized = re.sub(r"[^A-Z0-9]+", "_", value.upper())
        if "PREDICTIONCONFLICTERROR" in normalized or "IMMUTABLE_PREDICTION_CONFLICT" in normalized:
            found.add("IMMUTABLE_PREDICTION_CONFLICT")
    return found


def _recursive_integrity_reasons(value: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = re.sub(r"[^A-Z0-9]+", "_", str(key).upper()).strip("_")
            if normalized in {
                "SILENT_MISSING_FIXTURES",
                "PREDICTION_AFTER_KICKOFF",
                "DUPLICATE_FROZEN_PREDICTION",
                "DUPLICATE_FORMAL_PROSPECTIVE",
                "PILOT_EXCLUSION_VIOLATION",
                "PROSPECTIVE_ORPHAN",
            } and child:
                found.add(normalized)
            found.update(_recursive_integrity_reasons(child))
    elif isinstance(value, list):
        for child in value:
            found.update(_recursive_integrity_reasons(child))
    return found


def _load_active_dates(runtime: dict[str, Any]) -> list[str]:
    dates = [str(runtime.get("business_date") or "").strip()]
    dates.extend(str(value).strip() for value in runtime.get("carryover_business_dates") or [])
    return list(dict.fromkeys(value for value in dates if value))


def _carryover_missing_is_expected(runtime: dict[str, Any], business_date: str) -> bool:
    """A first-ever carryover date may legitimately have no saved state."""
    if business_date not in {str(value) for value in runtime.get("carryover_business_dates") or []}:
        return False
    steps = runtime.get("steps") or {}
    for name in ("carryover_base_jobs", "carryover_base_prediction", "carryover_result_schedule"):
        step = steps.get(name) or {}
        summary = step.get("summary") or {}
        if step.get("status") == "SKIPPED" and summary.get("reason") in {
            "UNIVERSE_NOT_FOUND",
            "BASE_JOBS_NOT_FOUND",
            "NO_BASE_JOBS",
            "CARRYOVER_NOT_READY",
        }:
            return True
    return False


def _check_universe_and_jobs(root: Path, runtime: dict[str, Any], reasons: list[str], details: dict[str, Any]) -> None:
    universe_root = root / "data" / "prediction_universe"
    jobs_root = root / "data" / "base_prediction_jobs"
    active_dates = _load_active_dates(runtime)
    for business_date in active_dates:
        universe, universe_error = _json(
            universe_root / f"{business_date}.json",
            required=("schema_version", "business_date", "status", "fixture_count", "fixtures"),
        )
        if universe_error or universe is None:
            if _carryover_missing_is_expected(runtime, business_date):
                continue
            details.setdefault("artifact_errors", []).append(f"prediction_universe/{business_date}.json:{universe_error}")
            _reason_once(reasons, "DURABLE_ARTIFACT_INVALID")
            continue
        if str(universe.get("business_date") or "") != business_date:
            _reason_once(reasons, "DURABLE_ARTIFACT_INVALID")
            continue
        status = str(universe.get("status") or "")
        if status == "FETCH_FAILED":
            _reason_once(reasons, "UNIVERSE_FETCH_FAILED")
            continue
        if status not in {"READY", "EMPTY_CONFIRMED"}:
            _reason_once(reasons, "DURABLE_ARTIFACT_INVALID")
            continue
        fixtures = universe.get("fixtures")
        if not isinstance(fixtures, list):
            _reason_once(reasons, "DURABLE_ARTIFACT_INVALID")
            continue
        try:
            fixture_count = int(universe.get("fixture_count"))
        except (TypeError, ValueError):
            fixture_count = -1
        if fixture_count < 0:
            _reason_once(reasons, "DURABLE_ARTIFACT_INVALID")
            continue
        if status == "READY" and fixture_count != len(fixtures):
            _reason_once(reasons, "SILENT_MISSING_FIXTURES")

        jobs, jobs_error = _json(
            jobs_root / f"{business_date}.json",
            required=("schema_version", "business_date", "status", "fixture_count", "job_count", "jobs"),
        )
        if jobs_error or jobs is None:
            details.setdefault("artifact_errors", []).append(f"base_prediction_jobs/{business_date}.json:{jobs_error}")
            _reason_once(reasons, "DURABLE_ARTIFACT_INVALID")
            continue
        if str(jobs.get("business_date") or "") != business_date:
            _reason_once(reasons, "DURABLE_ARTIFACT_INVALID")
            continue
        for integrity_reason in _recursive_integrity_reasons(jobs):
            _reason_once(reasons, integrity_reason)
        job_rows = jobs.get("jobs")
        if not isinstance(job_rows, list):
            _reason_once(reasons, "DURABLE_ARTIFACT_INVALID")
            continue
        if status == "READY":
            expected = {_identity(row, fixture=True) for row in fixtures if isinstance(row, dict)}
            actual = {_identity(row) for row in job_rows if isinstance(row, dict)}
            missing = expected - actual
            if missing or len(job_rows) < fixture_count or int(jobs.get("job_count") or 0) < fixture_count:
                _reason_once(reasons, "SILENT_MISSING_FIXTURES")
                details.setdefault("silent_missing_fixtures", 0)
                details["silent_missing_fixtures"] += max(len(missing), fixture_count - len(job_rows), 0)


def _check_workspace_freshness(
    root: Path,
    runtime: dict[str, Any],
    reasons: list[str],
    details: dict[str, Any],
) -> None:
    """Ensure the legacy workspace projection follows the current cycle date."""
    workspace_path = root / "data" / "match_workspace" / "latest.json"
    workspace, workspace_error = _json(
        workspace_path,
        required=("target_date", "generated_at"),
    )
    if workspace_error or workspace is None:
        details.setdefault("artifact_errors", []).append(f"match_workspace/latest.json:{workspace_error}")
        _reason_once(reasons, "MATCH_WORKSPACE_INVALID")
        return
    target_date = str(workspace.get("target_date") or "").strip()
    generated_at = _parse_at(workspace.get("generated_at"))
    runtime_date = str(runtime.get("business_date") or "").strip()
    try:
        target = datetime.fromisoformat(f"{target_date}T00:00:00").date()
    except ValueError:
        target = None
    details["workspace"] = {
        "target_date": target_date,
        "generated_at": generated_at.isoformat() if generated_at else None,
        "match_count": len(workspace.get("matches") or []) + len(workspace.get("completed") or []),
    }
    if target is None or generated_at is None:
        _reason_once(reasons, "MATCH_WORKSPACE_INVALID")
        return
    if runtime_date != target_date or generated_at.date() != target:
        _reason_once(reasons, "MATCH_WORKSPACE_STALE")


def _load_durable_assets(root: Path, reasons: list[str], details: dict[str, Any]):
    data = root / "data"
    prediction_rows, prediction_valid = _json_files(data / "model_governance" / "predictions")
    snapshot_rows, snapshot_valid = _json_files(data / "model_governance" / "input_snapshots")
    exclusion_rows, exclusion_valid = _json_files(data / "model_governance" / "prediction_exclusions")
    result_rows, result_valid = _json_files(data / "postmatch_automation" / "results")
    for label, valid in (
        ("predictions", prediction_valid),
        ("input_snapshots", snapshot_valid),
        ("prediction_exclusions", exclusion_valid),
        ("results", result_valid),
    ):
        directory = {
            "predictions": data / "model_governance" / "predictions",
            "input_snapshots": data / "model_governance" / "input_snapshots",
            "prediction_exclusions": data / "model_governance" / "prediction_exclusions",
            "results": data / "postmatch_automation" / "results",
        }[label]
        if not directory.is_dir() or not valid:
            details.setdefault("artifact_errors", []).append(label)
            _reason_once(reasons, "DURABLE_ARTIFACT_INVALID")

    ledger, ledger_valid = _jsonl(data / "prospective" / "ledger.jsonl")
    summary, summary_error = _json(
        data / "prospective" / "summary.json",
        required=("schema_version", "formal_sample_count_total", "samples_added_this_run"),
    )
    if not ledger_valid or summary_error or summary is None:
        details.setdefault("artifact_errors", []).append("prospective")
        _reason_once(reasons, "DURABLE_ARTIFACT_INVALID")

    return prediction_rows, exclusion_rows, result_rows, ledger, summary or {}


def _check_prediction_integrity(
    predictions: list[tuple[Path, dict[str, Any]]],
    exclusion_rows: list[tuple[Path, dict[str, Any]]],
    result_rows: list[tuple[Path, dict[str, Any]]],
    ledger: list[dict[str, Any]],
    runtime: dict[str, Any],
    reasons: list[str],
    details: dict[str, Any],
) -> None:
    formal_records = [
        payload for _, payload in predictions
        if str(payload.get("prediction_status") or "").strip() in FROZEN_STATUSES
    ]
    exact_score_health = evaluate_exact_score_health(formal_records)
    details["production_exact_score_health"] = exact_score_health
    for exact_score_reason in exact_score_health["reasons"]:
        _reason_once(reasons, exact_score_reason)
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in formal_records:
        key = str(record.get("job_id") or record.get("match_key") or record.get("prediction_id") or "")
        if key:
            groups[key].append(record)
        kickoff = _parse_at(record.get("kickoff_at"))
        created = _parse_at(record.get("prediction_created_at"))
        freeze = _parse_at(record.get("freeze_created_at"))
        if record.get("prediction_after_kickoff") is True or (
            kickoff is not None and ((created is not None and created >= kickoff) or (freeze is not None and freeze >= kickoff))
        ):
            _reason_once(reasons, "PREDICTION_AFTER_KICKOFF")
        for conflict_reason in _recursive_conflict_reasons(record):
            _reason_once(reasons, conflict_reason)
    if any(len(rows) > 1 for rows in groups.values()):
        _reason_once(reasons, "DUPLICATE_FROZEN_PREDICTION")

    exclusion_ids: set[str] = set()
    for _, payload in exclusion_rows:
        exclusion_ids.update(str(value).strip() for value in payload.get("prediction_ids") or [] if str(value).strip())
    ledger_ids = [str(row.get("prediction_id") or "").strip() for row in ledger]
    counts = Counter(value for value in ledger_ids if value)
    if any(count > 1 for count in counts.values()):
        _reason_once(reasons, "DUPLICATE_FORMAL_PROSPECTIVE")
    if set(ledger_ids) & exclusion_ids:
        _reason_once(reasons, "PILOT_EXCLUSION_VIOLATION")

    by_prediction_id = defaultdict(list)
    for record in formal_records:
        if record.get("prediction_id"):
            by_prediction_id[str(record["prediction_id"])].append(record)
    for prediction_id in set(ledger_ids):
        if len(by_prediction_id.get(prediction_id, [])) != 1:
            _reason_once(reasons, "PROSPECTIVE_ORPHAN")
            break

    for conflict_reason in _recursive_conflict_reasons(runtime):
        _reason_once(reasons, conflict_reason)
    for integrity_reason in _recursive_integrity_reasons(runtime):
        _reason_once(reasons, integrity_reason)
    for _, payload in result_rows:
        for conflict_reason in _recursive_conflict_reasons(payload):
            _reason_once(reasons, conflict_reason)
        for integrity_reason in _recursive_integrity_reasons(payload):
            _reason_once(reasons, integrity_reason)

    result_index: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for path, payload in result_rows:
        for key in _result_keys(path, payload):
            result_index[key].append(payload)
    active_dates = set(_load_active_dates(runtime))
    formal_ledger_ids = set(ledger_ids)
    stuck_ids: list[str] = []
    for record in formal_records:
        prediction_id = str(record.get("prediction_id") or "")
        if not prediction_id or prediction_id in exclusion_ids or prediction_id in formal_ledger_ids:
            continue
        if active_dates and str(record.get("business_date") or "") not in active_dates:
            continue
        try:
            eligible = is_formally_eligible(record)
        except Exception:
            eligible = False
        if not eligible:
            continue
        keys = {
            str(record.get(field))
            for field in ("match_key", "match_id")
            if record.get(field) not in (None, "")
        }
        if any(_is_final_result(candidate) for key in keys for candidate in result_index.get(key, [])):
            stuck_ids.append(prediction_id)
    if stuck_ids:
        _reason_once(reasons, "PROSPECTIVE_SETTLEMENT_STUCK")
        details["settlement_stuck_prediction_ids"] = sorted(stuck_ids)


def evaluate_health(
    *,
    root: Path = BASE_DIR,
    state_path: Path | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Return a machine-readable health result and persist the small counter state."""
    root = Path(root).resolve()
    state_path = Path(state_path) if state_path is not None else root / "data" / "product_runtime" / "health_watch.json"
    if not state_path.is_absolute():
        state_path = root / state_path
    current_time = _now(now)
    reasons: list[str] = []
    details: dict[str, Any] = {}
    previous_state: dict[str, Any] = {}
    state_error = False
    if state_path.exists():
        try:
            loaded = json.loads(state_path.read_text(encoding="utf-8"))
            if not isinstance(loaded, dict):
                raise ValueError("health state must be an object")
            if any(field not in loaded for field in (
                "schema_version", "current_status", "consecutive_problem_cycles",
            )):
                raise ValueError("health state schema is incomplete")
            previous_state = loaded
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
            state_error = True
            _reason_once(reasons, "HEALTH_STATE_CORRUPTED")

    runtime, runtime_error = _json(
        root / "data" / "product_runtime" / "latest_cycle.json",
        required=("schema_version", "business_date", "overall_status", "steps"),
    )
    if runtime_error or runtime is None:
        details.setdefault("artifact_errors", []).append(f"latest_cycle.json:{runtime_error}")
        _reason_once(reasons, "DURABLE_ARTIFACT_INVALID")
        runtime = {}
    else:
        overall = str(runtime.get("overall_status") or "")
        if overall == "FAILED":
            _reason_once(reasons, "CYCLE_FAILED")
        elif overall == "DEGRADED":
            _reason_once(reasons, "CYCLE_DEGRADED")
        elif overall != HEALTHY:
            _reason_once(reasons, "DURABLE_ARTIFACT_INVALID")

    _check_workspace_freshness(root, runtime, reasons, details)
    _check_universe_and_jobs(root, runtime, reasons, details)
    predictions, exclusions, results, ledger, summary = _load_durable_assets(root, reasons, details)
    for integrity_reason in _recursive_integrity_reasons(summary):
        _reason_once(reasons, integrity_reason)
    _check_prediction_integrity(predictions, exclusions, results, ledger, runtime, reasons, details)

    immediate_reasons = [
        reason for reason in reasons if reason in {
            "SILENT_MISSING_FIXTURES",
            "PREDICTION_AFTER_KICKOFF",
            "DUPLICATE_FROZEN_PREDICTION",
            "DUPLICATE_FORMAL_PROSPECTIVE",
            "RESULT_CONFLICT",
            "IMMUTABLE_PREDICTION_CONFLICT",
            "PILOT_EXCLUSION_VIOLATION",
            "PROSPECTIVE_ORPHAN",
            "HEALTH_STATE_CORRUPTED",
            "MATCH_WORKSPACE_STALE",
            "MATCH_WORKSPACE_INVALID",
            "SCORE_SELECTOR_COLLAPSE",
            "LAMBDA_COMPRESSION",
        }
    ]
    engineering_reasons = [reason for reason in reasons if reason not in immediate_reasons]
    previous_count = int(previous_state.get("consecutive_problem_cycles") or 0) if not state_error else 0
    if immediate_reasons:
        status = ALERT
        consecutive = max(previous_count + 1, 1)
    elif engineering_reasons:
        consecutive = previous_count + 1 if previous_count else 1
        status = ALERT if consecutive >= 2 else WATCH
    else:
        consecutive = 0
        status = HEALTHY

    previous_reasons = list(previous_state.get("active_reasons") or [])
    timestamp = current_time.isoformat()
    state = {
        "schema_version": "1.0",
        "updated_at": timestamp,
        "current_status": status,
        "consecutive_problem_cycles": consecutive,
        "last_healthy_at": timestamp if status == HEALTHY else previous_state.get("last_healthy_at"),
        "last_alert_at": timestamp if status == ALERT else previous_state.get("last_alert_at"),
        "active_reasons": reasons,
        "previous_reasons": previous_reasons,
        "last_cycle_generated_at": runtime.get("finished_at") or runtime.get("started_at"),
    }
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    result = {
        "schema_version": "1.0",
        "status": status,
        "notify": status == ALERT,
        "reasons": reasons,
        "immediate_reasons": immediate_reasons,
        "engineering_reasons": engineering_reasons,
        "consecutive_problem_cycles": consecutive,
        "business_date": runtime.get("business_date"),
        "last_cycle_generated_at": state["last_cycle_generated_at"],
        "details": details,
    }
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=BASE_DIR)
    parser.add_argument("--state-path", type=Path)
    parser.add_argument("--now")
    args = parser.parse_args()
    current = _parse_at(args.now) if args.now else None
    if args.now and current is None:
        raise SystemExit("--now must be an ISO timestamp")
    result = evaluate_health(root=args.root, state_path=args.state_path, now=current)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
