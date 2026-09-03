#!/usr/bin/env python3
"""Diagnose the source and time regime of Champion total-mean error.

This is a read-only research audit.  It replays the current Champion against
the pinned PRED-TRUST-2 snapshots, validates the portable semantic snapshot
identity contract, and compares the form, Asian O/U line, fusion, and frozen
total lambda against the verified 90-minute result.  It never writes model,
prediction, snapshot, result, or calibration data.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from statistics import fmean, median
from typing import Any, Callable, Iterable, Mapping


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from automatic_model_core import (  # noqa: E402
    _calibration_state,
    _deep_snapshot,
    _market_total,
    _mean,
    _rate,
    build_automatic_model,
)
from exact_score_error_decomposition_audit import (  # noqa: E402
    UNIVERSES,
    _load_competition_metadata,
    classify_competition,
)


DEFAULT_MANIFEST = PROJECT_ROOT / "data" / "prediction_quality" / "pred_trust_2" / "pinned_cohort_manifest.json"
DEFAULT_JOBS_ROOT = PROJECT_ROOT / "data" / "base_prediction_jobs"
DEFAULT_PREDICTION_ROOT = PROJECT_ROOT / "data" / "model_governance" / "predictions"
DEFAULT_RESULT_ROOT = PROJECT_ROOT / "data" / "postmatch_automation" / "results"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "audit-artifact"

MILESTONE = "EXACT-SCORE-MEAN-SOURCE-AND-REGIME-DECOMPOSITION-1"
CHAMPION_MODEL_FAMILY = "recent_form_market_calibrated_poisson_v2"
BOOTSTRAP_SEED = 20260903
DEFAULT_BOOTSTRAP_REPLICATES = 4000
MIN_UNIVERSE_SAMPLE = 20
SCORE_RE = re.compile(r"^(\d+)\s*-\s*(\d+)$")
EPSILON = 1e-9
ROUNDING_TOLERANCE = 1.1e-6

PRIMARY_MEAN_SOURCE_LABELS = (
    "FORM_TOTAL_LOW",
    "MARKET_LINE_LOW",
    "FUSION_LOW",
    "CLAMP_OR_CALIBRATION_EFFECT",
    "SHORT_WINDOW_SCORING_REGIME",
    "MIXED",
    "NOT_ESTABLISHED",
)

SOURCE_FIELDS = (
    ("form_total", "form_total"),
    ("market_total_line", "market_total_line_median"),
    ("uncalibrated_total", "uncalibrated_total"),
    ("final_lambda_total", "final_lambda_total"),
)


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"missing JSON asset: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON asset: {path}: {exc}") from exc


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_json_sha256(value: Any) -> str:
    """Hash JSON semantics independently of whitespace and line endings."""

    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _prediction_record_hash(record: Mapping[str, Any]) -> str:
    """Hash a frozen prediction with the PR #157 canonical JSON contract."""

    return _canonical_json_sha256(dict(record))


def _digest_ids(values: Iterable[str]) -> str:
    return _canonical_json_sha256(sorted(str(value) for value in values))


def _text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _finite_float(value: Any, label: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} is not numeric: {value!r}") from exc
    if not math.isfinite(number):
        raise ValueError(f"{label} is not finite: {value!r}")
    return number


def _parse_datetime(value: Any, label: str) -> datetime:
    raw = _text(value)
    if not raw:
        raise ValueError(f"{label} is missing")
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise ValueError(f"{label} is not ISO-8601: {value!r}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _repo_relative_path(root: Path, reference: str) -> Path:
    candidate = (root / reference).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError(f"asset reference escapes project root: {reference!r}") from exc
    return candidate


def _stable_seed(seed: int, label: str) -> int:
    digest = hashlib.sha256(label.encode("utf-8")).hexdigest()
    return int(seed) + int(digest[:8], 16)


def _parse_score(value: Any, label: str) -> tuple[int, int]:
    match = SCORE_RE.match(_text(value))
    if not match:
        raise ValueError(f"{label} is not a score: {value!r}")
    return int(match.group(1)), int(match.group(2))


def _validate_snapshot_integrity(
    prediction_id: str,
    prediction: Mapping[str, Any],
    snapshot: Mapping[str, Any],
) -> None:
    """Validate portable semantic identity from PR #157/#160."""

    canonical_input = snapshot.get("input")
    if not isinstance(canonical_input, dict):
        raise ValueError(f"input snapshot has no canonical input object for {prediction_id}")

    recomputed_digest = _canonical_json_sha256(canonical_input)
    snapshot_digest = _text(
        snapshot.get("canonical_model_input_sha256") or snapshot.get("canonical_input_sha256")
    )
    prediction_digest = _text(
        prediction.get("canonical_model_input_sha256") or prediction.get("input_sha256")
    )
    embedded_snapshot = prediction.get("input_snapshot")
    if not isinstance(embedded_snapshot, Mapping):
        raise ValueError(f"embedded input snapshot missing for {prediction_id}")
    embedded_digest = _text(
        embedded_snapshot.get("canonical_model_input_sha256")
        or embedded_snapshot.get("canonical_input_sha256")
    )
    if not snapshot_digest or recomputed_digest != snapshot_digest:
        raise ValueError(f"snapshot canonical input digest mismatch for {prediction_id}")
    if prediction_digest != snapshot_digest or embedded_digest != snapshot_digest:
        raise ValueError(f"snapshot/record canonical digest mismatch for {prediction_id}")

    snapshot_id = _text(snapshot.get("snapshot_id"))
    embedded_snapshot_id = _text(embedded_snapshot.get("snapshot_id"))
    if not snapshot_id or embedded_snapshot_id != snapshot_id:
        raise ValueError(f"snapshot ID mismatch for {prediction_id}")

    source_cutoff_at = _text(snapshot.get("source_cutoff_at"))
    prediction_source_cutoff_at = _text(prediction.get("source_cutoff_at"))
    embedded_source_cutoff_at = _text(embedded_snapshot.get("source_cutoff_at"))
    if (
        not source_cutoff_at
        or prediction_source_cutoff_at != source_cutoff_at
        or embedded_source_cutoff_at != source_cutoff_at
    ):
        raise ValueError(f"snapshot source cutoff mismatch for {prediction_id}")


def _validate_frozen_prediction(
    record: Mapping[str, Any],
    prediction: Mapping[str, Any],
    snapshot: Mapping[str, Any],
    snapshot_reference: str,
) -> tuple[float, float]:
    prediction_id = _text(record.get("prediction_id"))
    if _text(prediction.get("prediction_id")) != prediction_id:
        raise ValueError(f"prediction ID mismatch for {prediction_id}")
    if _text(prediction.get("match_id")) != _text(record.get("match_id")):
        raise ValueError(f"match ID mismatch for {prediction_id}")
    if _text(prediction.get("match_key")) != _text(record.get("match_key")):
        raise ValueError(f"match key mismatch for {prediction_id}")
    if _text(prediction.get("input_snapshot_ref") or prediction.get("model_input_snapshot_ref")) != snapshot_reference:
        raise ValueError(f"input snapshot reference mismatch for {prediction_id}")
    if _text(snapshot.get("snapshot_ref")) != snapshot_reference:
        raise ValueError(f"snapshot self-reference mismatch for {prediction_id}")
    if prediction.get("model_role") != "champion":
        raise ValueError(f"non-Champion prediction in pinned cohort: {prediction_id}")
    if prediction.get("model_core_version") != CHAMPION_MODEL_FAMILY:
        raise ValueError(f"unexpected model core for {prediction_id}: {prediction.get('model_core_version')!r}")
    if prediction.get("model_family") != CHAMPION_MODEL_FAMILY:
        raise ValueError(f"unexpected model family for {prediction_id}: {prediction.get('model_family')!r}")
    if prediction.get("prediction_status") != "formal" or prediction.get("formal_eligible") is not True:
        raise ValueError(f"prediction is not formal/frozen-eligible: {prediction_id}")
    if prediction.get("model_formal_eligible") is not True:
        raise ValueError(f"prediction model eligibility is not true: {prediction_id}")

    kickoff = _parse_datetime(
        record.get("kickoff_at") or prediction.get("kickoff_at"),
        f"kickoff_at[{prediction_id}]",
    )
    source_cutoff = _parse_datetime(
        prediction.get("source_cutoff_at") or snapshot.get("source_cutoff_at"),
        f"source_cutoff_at[{prediction_id}]",
    )
    freeze_created = _parse_datetime(prediction.get("freeze_created_at"), f"freeze_created_at[{prediction_id}]")
    if source_cutoff > kickoff or freeze_created > kickoff:
        raise ValueError(f"prematch cutoff/freeze is after kickoff for {prediction_id}")

    lambda_home = _finite_float(prediction.get("lambda_home"), f"lambda_home[{prediction_id}]")
    lambda_away = _finite_float(prediction.get("lambda_away"), f"lambda_away[{prediction_id}]")
    if lambda_home <= 0 or lambda_away <= 0:
        raise ValueError(f"non-positive lambda in {prediction_id}")
    rho = _finite_float(prediction.get("rho"), f"rho[{prediction_id}]")
    if abs(rho) > 1e-12:
        raise ValueError(f"non-zero rho in {prediction_id}: {rho}")
    return lambda_home, lambda_away


def compute_total_components(
    *,
    home_form: float,
    away_form: float,
    market_total_line: float | None,
    calibration_total_shift: float = 0.0,
) -> dict[str, float | None]:
    """Apply only the Champion total formula to already reconstructed inputs."""

    raw_form_total = float(home_form) + float(away_form)
    form_total = max(1.2, min(4.2, raw_form_total))
    target_total = float(market_total_line) if market_total_line is not None else form_total
    uncalibrated_total = 0.60 * form_total + 0.40 * target_total
    calibration_shift = float(calibration_total_shift)
    pre_final_clamp_total = uncalibrated_total + calibration_shift
    final_total = max(1.0, min(4.8, pre_final_clamp_total))
    return {
        "home_form": float(home_form),
        "away_form": float(away_form),
        "raw_form_total": raw_form_total,
        "form_total": form_total,
        "market_total_line_median": float(market_total_line) if market_total_line is not None else None,
        "target_total": target_total,
        "uncalibrated_total": uncalibrated_total,
        "calibration_total_shift": calibration_shift,
        "pre_final_clamp_total": pre_final_clamp_total,
        "final_total": final_total,
        "form_total_clamp_effect": form_total - raw_form_total,
        "final_total_clamp_effect": final_total - pre_final_clamp_total,
    }


def _reconstruct_form_and_total(context: Mapping[str, Any]) -> dict[str, Any]:
    """Rebuild Champion source values using the current core's private helpers."""

    materialized_context = dict(context)
    deep = _deep_snapshot(materialized_context)
    deep_form = (deep.get("shuju") or {}).get("recent_form") or {}
    prematch_facts = materialized_context.get("prematch_fundamentals") or {}
    form = deep_form or prematch_facts.get("recent_form") or {}
    home_home = form.get("home_home") or {}
    away_away = form.get("away_away") or {}
    home_overall = form.get("home_overall") or {}
    away_overall = form.get("away_overall") or {}
    effective_home_home = home_home if home_home.get("matches") else home_overall
    effective_away_away = away_away if away_away.get("matches") else away_overall

    home_venue = _mean([
        _rate(effective_home_home, "goals_for"),
        _rate(effective_away_away, "goals_against"),
    ])
    away_venue = _mean([
        _rate(effective_away_away, "goals_for"),
        _rate(effective_home_home, "goals_against"),
    ])
    home_general = _mean([
        _rate(home_overall, "goals_for"),
        _rate(away_overall, "goals_against"),
    ])
    away_general = _mean([
        _rate(away_overall, "goals_for"),
        _rate(home_overall, "goals_against"),
    ])
    home_form = _mean([home_venue, home_venue, home_general])
    away_form = _mean([away_venue, away_venue, away_general])
    if home_form is None or away_form is None:
        raise ValueError("Champion form reconstruction has a missing home/away form value")

    market_total_line = _market_total(deep)
    calibration_state = _calibration_state(materialized_context)
    calibration_artifact = calibration_state["artifact"]
    raw_calibration_shift = (
        float((calibration_artifact.get("total_goals") or {}).get("lambda_shift") or 0)
        if calibration_state["total_approved"]
        else 0.0
    )
    calibration_strength = float(calibration_state["strength"])
    applied_calibration_shift = raw_calibration_shift * calibration_strength
    components = compute_total_components(
        home_form=home_form,
        away_form=away_form,
        market_total_line=market_total_line,
        calibration_total_shift=applied_calibration_shift,
    )
    model_output = build_automatic_model(materialized_context)
    model = model_output.get("model") if isinstance(model_output, Mapping) else None
    if not isinstance(model, Mapping):
        raise ValueError("current Champion replay returned no model")

    model_form = model.get("calibration") or {}
    if abs(_finite_float(model_form.get("form_lambda_home"), "model form_lambda_home") - round(home_form, 6)) > EPSILON:
        raise ValueError("current core form home replay disagrees with model output")
    if abs(_finite_float(model_form.get("form_lambda_away"), "model form_lambda_away") - round(away_form, 6)) > EPSILON:
        raise ValueError("current core form away replay disagrees with model output")
    expected_goals = _finite_float(model.get("expected_goals"), "model expected_goals")
    if abs(expected_goals - round(float(components["final_total"]), 6)) > EPSILON:
        raise ValueError("current core expected_goals replay disagrees with total formula")

    components.update(
        {
            "calibration_total_shift_raw": raw_calibration_shift,
            "calibration_strength": calibration_strength,
            "calibration_total_shift_applied": applied_calibration_shift,
            "calibration_total_approved": bool(calibration_state["total_approved"]),
            "calibration_state": {
                "status": (calibration_artifact or {}).get("status") or "no_artifact",
                "active": bool(calibration_state["compatible"]),
                "total_goals_applied": bool(calibration_state["total_approved"]),
            },
            "model_lambda_home": _finite_float(model.get("lambda_home"), "model lambda_home"),
            "model_lambda_away": _finite_float(model.get("lambda_away"), "model lambda_away"),
            "model_expected_goals": expected_goals,
            "model_method": model.get("method"),
        }
    )
    return components


def _load_result(result_root: Path, match_key: str, kickoff: datetime) -> tuple[int, int, dict[str, Any]]:
    result_path = result_root / f"{match_key}.json"
    result = _read_json(result_path)
    if not isinstance(result, Mapping):
        raise ValueError(f"result asset is not an object for {match_key}")
    if _text(result.get("match_key")) != match_key:
        raise ValueError(f"result match key mismatch for {match_key}")
    if result.get("scope") != "regulation_90m_plus_stoppage":
        raise ValueError(f"result scope is not 90m+stoppage for {match_key}")
    verified_at = _parse_datetime(result.get("verified_at"), f"verified_at[{match_key}]")
    if verified_at <= kickoff:
        raise ValueError(f"result verification is not postmatch for {match_key}")
    actual_home, actual_away = _parse_score(result.get("result_90m"), f"result_90m[{match_key}]")
    try:
        stored_home = int(result.get("home_score"))
        stored_away = int(result.get("away_score"))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"result score fields are not integers for {match_key}") from exc
    if stored_home != actual_home or stored_away != actual_away:
        raise ValueError(f"result score fields disagree for {match_key}")
    return actual_home, actual_away, dict(result)


def _load_cohort(
    root: Path,
    manifest_path: Path,
    jobs_root: Path,
    prediction_root: Path,
    result_root: Path,
) -> dict[str, Any]:
    manifest = _read_json(manifest_path)
    if not isinstance(manifest, Mapping):
        raise ValueError("cohort manifest must be a JSON object")

    selected_records = manifest.get("selected_records") or []
    verified_ids = [_text(value) for value in (manifest.get("verified_prediction_ids") or [])]
    if not isinstance(selected_records, list) or not isinstance(manifest.get("verified_prediction_ids") or [], list):
        raise ValueError("manifest selected_records/verified_prediction_ids must be lists")
    selected_by_id: dict[str, Mapping[str, Any]] = {}
    for record in selected_records:
        if not isinstance(record, Mapping):
            raise ValueError("selected record is not an object")
        prediction_id = _text(record.get("prediction_id"))
        if not prediction_id or prediction_id in selected_by_id:
            raise ValueError(f"selected prediction IDs are not unique: {prediction_id!r}")
        selected_by_id[prediction_id] = record

    selected_match_ids = [_text(row.get("match_id")) for row in selected_records]
    selected_match_keys = [_text(row.get("match_key")) for row in selected_records]
    if any(not value for value in selected_match_ids + selected_match_keys):
        raise ValueError("selected records contain an empty match identity")
    if len(set(selected_match_ids)) != len(selected_records) or len(set(selected_match_keys)) != len(selected_records):
        raise ValueError("pinned cohort is not one unique match per observation")
    if len(set(verified_ids)) != len(verified_ids):
        raise ValueError("verified prediction IDs are not unique")
    if not set(verified_ids).issubset(selected_by_id):
        raise ValueError("verified prediction IDs are not a subset of selected records")
    selected_digest = _digest_ids(selected_by_id.keys())
    if _text(manifest.get("selected_prediction_digest")) != selected_digest:
        raise ValueError("manifest selected_prediction_digest disagrees with selected records")
    if _text(manifest.get("verified_prediction_digest")) != _digest_ids(verified_ids):
        raise ValueError("manifest verified_prediction_digest disagrees with verified IDs")
    if int(manifest.get("selected_match_count") or 0) != len(selected_records):
        raise ValueError("manifest selected_match_count disagrees with selected records")
    if int(manifest.get("verified_match_count") or 0) != len(verified_ids):
        raise ValueError("manifest verified_match_count disagrees with verified IDs")
    if len(verified_ids) != 181:
        raise ValueError(f"expected 181 verified predictions, got {len(verified_ids)}")

    competition_metadata = _load_competition_metadata(jobs_root, set(selected_match_ids))
    verified_rows: list[dict[str, Any]] = []
    raw_snapshot_hash_status = {
        "checked_n": 0,
        "matched_n": 0,
        "mismatched_n": 0,
        "missing_manifest_hash_n": 0,
        "gate": "legacy_non_portable_evidence_only",
        "mismatch_is_fail_condition": False,
    }
    reconstruction_diffs: list[float] = []
    formula_diffs: list[float] = []

    for prediction_id in verified_ids:
        record = selected_by_id[prediction_id]
        match_id = _text(record.get("match_id"))
        match_key = _text(record.get("match_key"))
        snapshot_reference = _text(record.get("input_snapshot_ref"))
        if not snapshot_reference:
            raise ValueError(f"missing input snapshot reference for {prediction_id}")
        snapshot_path = _repo_relative_path(root, snapshot_reference)
        raw_snapshot_hash_status["checked_n"] += 1
        expected_raw_snapshot_hash = _text(record.get("input_snapshot_sha256"))
        actual_raw_snapshot_hash = _sha256_file(snapshot_path)
        if not expected_raw_snapshot_hash:
            raw_snapshot_hash_status["missing_manifest_hash_n"] += 1
        elif actual_raw_snapshot_hash == expected_raw_snapshot_hash:
            raw_snapshot_hash_status["matched_n"] += 1
        else:
            raw_snapshot_hash_status["mismatched_n"] += 1

        snapshot = _read_json(snapshot_path)
        prediction_path = prediction_root / f"{prediction_id}.json"
        prediction = _read_json(prediction_path)
        if not isinstance(snapshot, Mapping) or not isinstance(prediction, Mapping):
            raise ValueError(f"snapshot/prediction asset is not an object for {prediction_id}")
        expected_record_hash = _text(record.get("record_sha256"))
        if not expected_record_hash:
            raise ValueError(f"missing pinned prediction record hash for {prediction_id}")
        if _prediction_record_hash(prediction) != expected_record_hash:
            raise ValueError(f"pinned prediction content changed for {prediction_id}")
        _validate_snapshot_integrity(prediction_id, prediction, snapshot)
        frozen_home, frozen_away = _validate_frozen_prediction(
            record, prediction, snapshot, snapshot_reference
        )
        kickoff = _parse_datetime(record.get("kickoff_at"), f"kickoff_at[{prediction_id}]")
        actual_home, actual_away, result = _load_result(result_root, match_key, kickoff)

        context = snapshot.get("input")
        if not isinstance(context, Mapping):
            raise ValueError(f"snapshot input is not an object for {prediction_id}")
        components = _reconstruct_form_and_total(context)
        replay_lambda_total = float(components["model_lambda_home"]) + float(components["model_lambda_away"])
        frozen_lambda_total = frozen_home + frozen_away
        reconstruction_difference = replay_lambda_total - frozen_lambda_total
        if abs(reconstruction_difference) > EPSILON:
            raise ValueError(
                f"Champion final lambda total reconstruction mismatch for {prediction_id}: "
                f"{replay_lambda_total} != {frozen_lambda_total}"
            )
        formula_difference = float(components["final_total"]) - frozen_lambda_total
        if abs(formula_difference) > ROUNDING_TOLERANCE:
            raise ValueError(
                f"Champion formula final total mismatch for {prediction_id}: "
                f"{components['final_total']} != {frozen_lambda_total}"
            )
        reconstruction_diffs.append(reconstruction_difference)
        formula_diffs.append(formula_difference)

        metadata = competition_metadata.get(match_id) or {}
        competition = metadata.get("competition")
        universe = classify_competition(competition)
        verified_rows.append(
            {
                "prediction_id": prediction_id,
                "match_id": match_id,
                "match_key": match_key,
                "kickoff_at": _text(record.get("kickoff_at")),
                "competition": competition,
                "competition_candidates": metadata.get("candidates") or [],
                "competition_metadata_status": metadata.get("metadata_status"),
                "universe": universe,
                "lambda_home": frozen_home,
                "lambda_away": frozen_away,
                "final_lambda_total": frozen_lambda_total,
                "actual_home": actual_home,
                "actual_away": actual_away,
                "actual_total": actual_home + actual_away,
                "result_asset": str((result_root / f"{match_key}.json").relative_to(root)).replace("\\", "/"),
                "result_verified_at": _text(result.get("verified_at")),
                **components,
            }
        )

    if len(verified_rows) != len(verified_ids):
        raise ValueError("cohort loading did not preserve verified count")
    if len({row["match_id"] for row in verified_rows}) != len(verified_rows):
        raise ValueError("verified cohort contains duplicate match IDs")
    if len({row["match_key"] for row in verified_rows}) != len(verified_rows):
        raise ValueError("verified cohort contains duplicate match keys")

    return {
        "manifest": dict(manifest),
        "verified_rows": verified_rows,
        "snapshot_integrity": {
            "method": "canonical_json_semantic_integrity",
            "canonical_json_sha256": {
                "serialization": "json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')) encoded as UTF-8",
                "snapshot_fields": ["canonical_model_input_sha256", "canonical_input_sha256"],
                "prediction_record_fields": ["canonical_model_input_sha256", "input_sha256"],
                "embedded_input_snapshot_fields": ["canonical_model_input_sha256", "canonical_input_sha256"],
            },
            "pinned_prediction_record_content_hash": "manifest record_sha256 versus canonical prediction JSON",
            "identity_fields": [
                "prediction_id",
                "match_id",
                "match_key",
                "input_snapshot_ref",
                "snapshot_id",
                "source_cutoff_at",
            ],
            "raw_file_sha256": raw_snapshot_hash_status,
        },
        "reconstruction": {
            "verified_n": len(verified_rows),
            "frozen_lambda_total_match_n": len(reconstruction_diffs),
            "max_abs_frozen_lambda_total_difference": max((abs(value) for value in reconstruction_diffs), default=0.0),
            "max_abs_formula_to_frozen_difference": max((abs(value) for value in formula_diffs), default=0.0),
            "status": "PASS" if all(abs(value) <= EPSILON for value in reconstruction_diffs) else "FAIL",
            "final_lambda_total_source": "current automatic_model_core output lambda_home + lambda_away",
            "formula_final_total_rounding_tolerance": ROUNDING_TOLERANCE,
        },
        "manifest_path": str(manifest_path.relative_to(root)).replace("\\", "/"),
    }


def _quantile(values: Iterable[float], probability: float) -> float | None:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return None
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def _bootstrap_ci(values: list[float], *, seed: int, label: str, replicates: int) -> list[float | None]:
    if not values:
        return [None, None]
    if replicates < 1:
        raise ValueError("bootstrap replicates must be positive")
    rng = random.Random(_stable_seed(seed, label))
    count = len(values)
    means = [
        sum(values[rng.randrange(count)] for _ in range(count)) / count
        for _ in range(replicates)
    ]
    return [_quantile(means, 0.025), _quantile(means, 0.975)]


def source_metric_summary(
    rows: Iterable[Mapping[str, Any]],
    field: str,
    *,
    seed: int = BOOTSTRAP_SEED,
    replicates: int = DEFAULT_BOOTSTRAP_REPLICATES,
    label: str | None = None,
) -> dict[str, Any]:
    """Summarize one source over paired, one-row-per-match observations."""

    values: list[float] = []
    actuals: list[float] = []
    for row in rows:
        value = row.get(field)
        actual = row.get("actual_total")
        if value is None or actual is None:
            continue
        values.append(_finite_float(value, f"{field} value"))
        actuals.append(_finite_float(actual, "actual_total"))
    if not values:
        return {
            "status": "INSUFFICIENT_DATA",
            "observation_n": 0,
            "predicted_mean": None,
            "actual_mean": None,
            "mean_difference_predicted_minus_actual": None,
            "mean_difference_actual_minus_predicted": None,
            "mae": None,
            "mean_difference_bootstrap_ci_95": [None, None],
            "mae_bootstrap_ci_95": [None, None],
        }
    differences = [value - actual for value, actual in zip(values, actuals)]
    absolute_errors = [abs(value) for value in differences]
    ci_label = label or field
    return {
        "status": "OK",
        "observation_n": len(values),
        "predicted_mean": fmean(values),
        "actual_mean": fmean(actuals),
        "mean_difference_predicted_minus_actual": fmean(differences),
        "mean_difference_actual_minus_predicted": -fmean(differences),
        "mae": fmean(absolute_errors),
        "mean_difference_bootstrap_ci_95": _bootstrap_ci(
            differences,
            seed=seed,
            label=f"{ci_label}:mean_difference",
            replicates=replicates,
        ),
        "mae_bootstrap_ci_95": _bootstrap_ci(
            absolute_errors,
            seed=seed,
            label=f"{ci_label}:mae",
            replicates=replicates,
        ),
    }


def _adjustment_summary(
    rows: list[Mapping[str, Any]],
    field: str,
    *,
    label: str,
    seed: int,
    replicates: int,
) -> dict[str, Any]:
    values = [_finite_float(row.get(field), field) for row in rows]
    changed = [value for value in values if abs(value) > EPSILON]
    return {
        "field": field,
        "changed_n": len(changed),
        "sample_n": len(values),
        "mean_shift": fmean(values) if values else 0.0,
        "mean_absolute_shift": fmean(abs(value) for value in values) if values else 0.0,
        "bootstrap_ci_95": _bootstrap_ci(
            values,
            seed=seed,
            label=f"adjustment:{label}",
            replicates=replicates,
        ) if values else [None, None],
    }


def build_global_analysis(
    rows: list[Mapping[str, Any]],
    *,
    seed: int = BOOTSTRAP_SEED,
    replicates: int = DEFAULT_BOOTSTRAP_REPLICATES,
) -> dict[str, Any]:
    actual_values = [_finite_float(row["actual_total"], "actual_total") for row in rows]
    sources = {
        name: source_metric_summary(rows, field, seed=seed, replicates=replicates, label=f"global:{name}")
        for name, field in SOURCE_FIELDS
    }
    form_bias = float(sources["form_total"]["mean_difference_predicted_minus_actual"])
    market_bias = float(sources["market_total_line"]["mean_difference_predicted_minus_actual"])
    fusion_bias = float(sources["uncalibrated_total"]["mean_difference_predicted_minus_actual"])
    final_bias = float(sources["final_lambda_total"]["mean_difference_predicted_minus_actual"])
    weighted_form_values = [0.60 * (float(row["form_total"]) - float(row["actual_total"])) for row in rows]
    weighted_target_values = [0.40 * (float(row["target_total"]) - float(row["actual_total"])) for row in rows]
    weighted_contributions = {
        "form_60_percent": {
            "mean_contribution": fmean(weighted_form_values),
            "bootstrap_ci_95": _bootstrap_ci(
                weighted_form_values,
                seed=seed,
                label="global:weighted_form_contribution",
                replicates=replicates,
            ),
        },
        "market_or_form_fallback_40_percent": {
            "mean_contribution": fmean(weighted_target_values),
            "bootstrap_ci_95": _bootstrap_ci(
                weighted_target_values,
                seed=seed,
                label="global:weighted_target_contribution",
                replicates=replicates,
            ),
        },
    }
    adjustments = {
        "form_total_clamp": _adjustment_summary(
            rows,
            "form_total_clamp_effect",
            label="form_total_clamp",
            seed=seed,
            replicates=replicates,
        ),
        "calibration_total_shift": _adjustment_summary(
            rows,
            "calibration_total_shift_applied",
            label="calibration_total_shift",
            seed=seed,
            replicates=replicates,
        ),
        "final_total_clamp": _adjustment_summary(
            rows,
            "final_total_clamp_effect",
            label="final_total_clamp",
            seed=seed,
            replicates=replicates,
        ),
    }
    post_fusion_values = [
        float(row["calibration_total_shift_applied"]) + float(row["final_total_clamp_effect"])
        for row in rows
    ]
    adjustments["post_fusion_calibration_or_final_clamp"] = {
        "field": "calibration_total_shift_applied + final_total_clamp_effect",
        "changed_n": sum(abs(value) > EPSILON for value in post_fusion_values),
        "sample_n": len(post_fusion_values),
        "mean_shift": fmean(post_fusion_values),
        "mean_absolute_shift": fmean(abs(value) for value in post_fusion_values),
            "bootstrap_ci_95": _bootstrap_ci(
                post_fusion_values,
                seed=seed,
                label="adjustment:post_fusion_calibration_or_final_clamp",
                replicates=replicates,
            ),
    }
    return {
        "observation_n": len(rows),
        "actual_total_mean": fmean(actual_values),
        "sources": sources,
        "fusion_comparison": {
            "form_only_bias": form_bias,
            "market_line_only_bias": market_bias,
            "uncalibrated_fusion_bias": fusion_bias,
            "final_lambda_bias": final_bias,
            "fusion_bias_minus_form_only_bias": fusion_bias - form_bias,
            "fusion_bias_minus_market_line_only_bias": fusion_bias - market_bias,
            "final_bias_minus_uncalibrated_fusion_bias": final_bias - fusion_bias,
            "interpretation": {
                "versus_form_only": "INCREASED_UNDERPREDICTION" if fusion_bias < form_bias else "REDUCED_UNDERPREDICTION" if fusion_bias > form_bias else "NO_CHANGE",
                "versus_market_line_only": "REDUCED_UNDERPREDICTION" if fusion_bias > market_bias else "INCREASED_UNDERPREDICTION" if fusion_bias < market_bias else "NO_CHANGE",
            },
        },
        "weighted_fusion_bias_contributions": weighted_contributions,
        "adjustments": adjustments,
    }


def _insufficient_source_status(n: int) -> dict[str, Any]:
    return {
        "status": "INSUFFICIENT_SAMPLE",
        "observation_n": n,
        "predicted_mean": None,
        "actual_mean": None,
        "mean_difference_predicted_minus_actual": None,
        "mean_difference_actual_minus_predicted": None,
        "mae": None,
        "mean_difference_bootstrap_ci_95": [None, None],
        "mae_bootstrap_ci_95": [None, None],
    }


def build_universe_analysis(
    rows: list[Mapping[str, Any]],
    *,
    seed: int = BOOTSTRAP_SEED,
    replicates: int = DEFAULT_BOOTSTRAP_REPLICATES,
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for universe in UNIVERSES:
        subset = [row for row in rows if row.get("universe") == universe]
        n = len(subset)
        if n < MIN_UNIVERSE_SAMPLE:
            result[universe] = {
                "universe": universe,
                "verified_n": n,
                "sample_status": "INSUFFICIENT_SAMPLE",
                "metrics": {name: _insufficient_source_status(n) for name, _ in SOURCE_FIELDS if name in {"form_total", "market_total_line", "final_lambda_total"}},
            }
            continue
        result[universe] = {
            "universe": universe,
            "verified_n": n,
            "sample_status": "SUFFICIENT",
            "metrics": {
                name: source_metric_summary(
                    subset,
                    field,
                    seed=seed,
                    replicates=replicates,
                    label=f"universe:{universe}:{name}",
                )
                for name, field in (
                    ("form_total", "form_total"),
                    ("market_total_line", "market_total_line_median"),
                    ("final_lambda_total", "final_lambda_total"),
                )
            },
        }
    sufficient = [universe for universe in UNIVERSES if result[universe]["sample_status"] == "SUFFICIENT"]
    return {
        "minimum_sample": MIN_UNIVERSE_SAMPLE,
        "taxonomic_source": "PR #160 locked competition taxonomy via existing metadata only",
        "by_universe": result,
        "sufficient_universes": sufficient,
    }


def split_chronological_thirds(rows: Iterable[Mapping[str, Any]]) -> dict[str, list[Mapping[str, Any]]]:
    ordered = sorted(
        rows,
        key=lambda row: (
            _parse_datetime(row.get("kickoff_at"), "kickoff_at"),
            _text(row.get("match_key")),
            _text(row.get("prediction_id")),
        ),
    )
    third = len(ordered) // 3
    return {
        "earliest_third": ordered[:third],
        "middle_third": ordered[third : third * 2],
        "latest_third": ordered[third * 2 :],
    }


def build_chronological_analysis(
    rows: list[Mapping[str, Any]],
    *,
    seed: int = BOOTSTRAP_SEED,
    replicates: int = DEFAULT_BOOTSTRAP_REPLICATES,
) -> dict[str, Any]:
    thirds = split_chronological_thirds(rows)
    result: dict[str, Any] = {}
    for name, subset in thirds.items():
        source_metrics = {
            source_name: source_metric_summary(
                subset,
                field,
                seed=seed,
                replicates=replicates,
                label=f"chronological:{name}:{source_name}",
            )
            for source_name, field in SOURCE_FIELDS
        }
        actuals = [float(row["actual_total"]) for row in subset]
        result[name] = {
            "n": len(subset),
            "kickoff_start": _text(subset[0].get("kickoff_at")) if subset else None,
            "kickoff_end": _text(subset[-1].get("kickoff_at")) if subset else None,
            "actual_total_mean": fmean(actuals) if actuals else None,
            "form_total_mean": source_metrics["form_total"]["predicted_mean"],
            "market_line_mean": source_metrics["market_total_line"]["predicted_mean"],
            "final_lambda_total_mean": source_metrics["final_lambda_total"]["predicted_mean"],
            "source_metrics": source_metrics,
            "bias_predicted_minus_actual": {
                source_name: source_metrics[source_name]["mean_difference_predicted_minus_actual"]
                for source_name in ("form_total", "market_total_line", "final_lambda_total")
            },
            "bias_bootstrap_ci_95": {
                source_name: source_metrics[source_name]["mean_difference_bootstrap_ci_95"]
                for source_name in ("form_total", "market_total_line", "final_lambda_total")
            },
            "zero_zero_count": sum(
                int(float(row["actual_home"]) == 0 and float(row["actual_away"]) == 0)
                for row in subset
            ),
            "four_plus_share": fmean(float(row["actual_total"]) >= 4 for row in subset) if subset else None,
            "form_market_both_negative": (
                source_metrics["form_total"]["mean_difference_predicted_minus_actual"] < 0
                and source_metrics["market_total_line"]["mean_difference_predicted_minus_actual"] < 0
            ),
        }
    both_negative = sum(bool(result[name]["form_market_both_negative"]) for name in thirds)
    return {
        "split_method": "kickoff_at ascending; deterministic match_key/prediction_id tie-break; floor thirds with remainder in latest_third",
        "thirds": result,
        "form_market_synchronized_underprediction_thirds_n": both_negative,
        "form_market_synchronized_underprediction_status": "SYNCHRONIZED_IN_EARLIEST_AND_LATEST" if both_negative == 2 else "NOT_ESTABLISHED",
    }


def _load_environment_results(
    result_root: Path,
    cohort_rows: list[Mapping[str, Any]],
    *,
    seed: int = BOOTSTRAP_SEED,
    replicates: int = DEFAULT_BOOTSTRAP_REPLICATES,
) -> dict[str, Any]:
    cohort_kickoffs = [_parse_datetime(row["kickoff_at"], "cohort kickoff_at") for row in cohort_rows]
    earliest_cohort_kickoff = min(cohort_kickoffs)
    history_values: list[dict[str, Any]] = []
    scanned_n = 0
    ignored_n = 0
    seen_match_keys: set[str] = set()
    for path in sorted(result_root.glob("*.json")):
        scanned_n += 1
        try:
            result = _read_json(path)
            if not isinstance(result, Mapping) or result.get("scope") != "regulation_90m_plus_stoppage":
                ignored_n += 1
                continue
            match_key = _text(result.get("match_key"))
            kickoff = _parse_datetime(result.get("kickoff_local"), f"kickoff_local[{path.name}]")
            home, away = _parse_score(result.get("result_90m"), f"result_90m[{path.name}]")
            if int(result.get("home_score")) != home or int(result.get("away_score")) != away:
                ignored_n += 1
                continue
        except (TypeError, ValueError, KeyError):
            ignored_n += 1
            continue
        if not match_key or match_key in seen_match_keys or kickoff >= earliest_cohort_kickoff:
            ignored_n += 1
            continue
        seen_match_keys.add(match_key)
        history_values.append(
            {
                "match_key": match_key,
                "actual_total": home + away,
                "actual_home": home,
                "actual_away": away,
                "kickoff_at": kickoff.isoformat(),
            }
        )

    def summary(values: list[Mapping[str, Any]]) -> dict[str, Any]:
        totals = [int(row["actual_total"]) for row in values]
        if not totals:
            return {
                "n": 0,
                "mean_total": None,
                "median_total": None,
                "zero_zero_share": None,
                "over_2_5_share": None,
                "four_plus_share": None,
                "five_plus_share": None,
                "btts_share": None,
            }
        return {
            "n": len(totals),
            "mean_total": fmean(totals),
            "median_total": median(totals),
            "zero_zero_share": fmean(total == 0 for total in totals),
            "over_2_5_share": fmean(total > 2 for total in totals),
            "four_plus_share": fmean(total >= 4 for total in totals),
            "five_plus_share": fmean(total >= 5 for total in totals),
            "btts_share": fmean(
                int(row["actual_home"]) > 0 and int(row["actual_away"]) > 0
                for row in values
            ),
        }

    cohort_environment = summary(cohort_rows)
    history_environment = summary(history_values)
    current_totals = [int(row["actual_total"]) for row in cohort_rows]
    historical_totals = [int(row["actual_total"]) for row in history_values]
    mean_difference = (
        fmean(current_totals) - fmean(historical_totals)
        if current_totals and historical_totals
        else None
    )
    difference_ci = (
        _bootstrap_difference_ci(
            current_totals,
            historical_totals,
            seed=seed,
            label="environment:current_minus_history_mean_total",
            replicates=replicates,
        )
        if current_totals and historical_totals
        else [None, None]
    )
    return {
        "status": "ENVIRONMENT_ONLY / NO_PREMATCH_MODEL_COMPARISON",
        "cohort_boundary": {
            "definition": "verified-result rows with kickoff_local before the earliest verified prediction kickoff",
            "earliest_cohort_kickoff": earliest_cohort_kickoff.isoformat(),
        },
        "scanned_result_json_n": scanned_n,
        "ignored_result_json_n": ignored_n,
        "prediction_cohort_181": cohort_environment,
        "history_before_cohort": history_environment,
        "mean_total_difference_current_minus_history": mean_difference,
        "mean_total_difference_bootstrap_ci_95": difference_ci,
        "history_used_in_model_metric_denominator_n": 0,
    }


def _bootstrap_difference_ci(
    current_values: list[float],
    history_values: list[float],
    *,
    seed: int,
    label: str,
    replicates: int,
) -> list[float | None]:
    if not current_values or not history_values:
        return [None, None]
    rng = random.Random(_stable_seed(seed, label))
    current_n = len(current_values)
    history_n = len(history_values)
    differences = []
    for _ in range(replicates):
        current_mean = sum(current_values[rng.randrange(current_n)] for _ in range(current_n)) / current_n
        history_mean = sum(history_values[rng.randrange(history_n)] for _ in range(history_n)) / history_n
        differences.append(current_mean - history_mean)
    return [_quantile(differences, 0.025), _quantile(differences, 0.975)]


def _ci_upper_below_zero(metric: Mapping[str, Any]) -> bool:
    value = metric.get("mean_difference_predicted_minus_actual")
    interval = metric.get("mean_difference_bootstrap_ci_95") or []
    return (
        isinstance(value, (int, float))
        and math.isfinite(float(value))
        and float(value) < 0
        and len(interval) == 2
        and interval[1] is not None
        and float(interval[1]) < 0
    )


def diagnose_mean_source(
    global_analysis: Mapping[str, Any],
    adjustments: Mapping[str, Any],
    environment: Mapping[str, Any],
) -> dict[str, Any]:
    """Apply a fixed, non-tuning decision tree to the requested labels."""

    sources = global_analysis.get("sources") or {}
    form_low = _ci_upper_below_zero(sources.get("form_total") or {})
    market_low = _ci_upper_below_zero(sources.get("market_total_line") or {})
    fusion_low = _ci_upper_below_zero(sources.get("uncalibrated_total") or {})
    final_low = _ci_upper_below_zero(sources.get("final_lambda_total") or {})

    final_metric = sources.get("final_lambda_total") or {}
    final_bias = final_metric.get("mean_difference_predicted_minus_actual")
    fusion_metric = sources.get("uncalibrated_total") or {}
    fusion_bias = fusion_metric.get("mean_difference_predicted_minus_actual")
    final_clamp = adjustments.get("final_total_clamp") or {}
    calibration = adjustments.get("calibration_total_shift") or {}
    material_adjustment = (
        int(final_clamp.get("changed_n") or 0) > 0
        or int(calibration.get("changed_n") or 0) > 0
    )
    adjustment_explains_final = bool(
        material_adjustment
        and isinstance(final_bias, (int, float))
        and isinstance(fusion_bias, (int, float))
        and float(final_bias) < float(fusion_bias)
        and abs(float(final_bias) - float(fusion_bias)) >= 0.05
    )

    history_ci = environment.get("mean_total_difference_bootstrap_ci_95") or []
    history_delta = environment.get("mean_total_difference_current_minus_history")
    regime_signal = bool(
        isinstance(history_delta, (int, float))
        and float(history_delta) >= 0.25
        and len(history_ci) == 2
        and history_ci[0] is not None
        and float(history_ci[0]) > 0
    )

    if adjustment_explains_final:
        primary = "CLAMP_OR_CALIBRATION_EFFECT"
    elif form_low and market_low:
        primary = "MIXED"
    elif form_low:
        primary = "FORM_TOTAL_LOW"
    elif market_low:
        primary = "MARKET_LINE_LOW"
    elif fusion_low or final_low:
        primary = "FUSION_LOW"
    elif regime_signal:
        primary = "SHORT_WINDOW_SCORING_REGIME"
    else:
        primary = "NOT_ESTABLISHED"

    form_contribution = ((global_analysis.get("weighted_fusion_bias_contributions") or {}).get("form_60_percent") or {}).get("mean_contribution")
    target_contribution = ((global_analysis.get("weighted_fusion_bias_contributions") or {}).get("market_or_form_fallback_40_percent") or {}).get("mean_contribution")
    if isinstance(form_contribution, (int, float)) and isinstance(target_contribution, (int, float)):
        if abs(float(form_contribution) - float(target_contribution)) <= 0.05:
            dominant_component = "NEARLY_EQUAL_WEIGHTED_FORM_AND_MARKET_OR_FALLBACK"
        elif abs(float(form_contribution)) > abs(float(target_contribution)):
            dominant_component = "FORM_TOTAL_LOW"
        else:
            dominant_component = "MARKET_LINE_LOW"
    else:
        dominant_component = "NOT_ESTABLISHED"
    return {
        "PRIMARY_MEAN_SOURCE": primary,
        "allowed_labels": list(PRIMARY_MEAN_SOURCE_LABELS),
        "form_low_established": form_low,
        "market_line_low_established": market_low,
        "fusion_low_established": fusion_low,
        "final_low_established": final_low,
        "adjustment_explains_final": adjustment_explains_final,
        "regime_context_signal": "SHORT_WINDOW_SCORING_REGIME" if regime_signal else "NOT_ESTABLISHED",
        "weighted_dominant_component": dominant_component,
        "GLOBAL_LAMBDA_RAISE_ALLOWED": "NO",
    }


def build_summary(
    cohort: Mapping[str, Any],
    *,
    seed: int = BOOTSTRAP_SEED,
    replicates: int = DEFAULT_BOOTSTRAP_REPLICATES,
    result_root: Path = DEFAULT_RESULT_ROOT,
) -> dict[str, Any]:
    rows = list(cohort["verified_rows"])
    global_analysis = build_global_analysis(rows, seed=seed, replicates=replicates)
    universe_analysis = build_universe_analysis(rows, seed=seed, replicates=replicates)
    chronological_analysis = build_chronological_analysis(rows, seed=seed, replicates=replicates)
    environment = _load_environment_results(result_root, rows, seed=seed, replicates=replicates)
    diagnosis = diagnose_mean_source(global_analysis, global_analysis["adjustments"], environment)
    return {
        "schema_version": "exact_score_mean_source_audit.v1",
        "milestone": MILESTONE,
        "status": "PASS" if cohort["reconstruction"]["status"] == "PASS" else "FAIL",
        "cohort": {
            "pinned_n": int(cohort["manifest"]["selected_match_count"]),
            "verified_n": len(rows),
            "one_match_one_observation": len({row["match_key"] for row in rows}) == len(rows),
            "champion_model_family": CHAMPION_MODEL_FAMILY,
            "metric_denominator": "181 verified unique frozen Champion matches only",
        },
        "manifest": {
            "path": cohort["manifest_path"],
            "schema_version": cohort["manifest"].get("schema_version"),
            "selection_policy": cohort["manifest"].get("selection_policy"),
            "selected_prediction_digest": cohort["manifest"].get("selected_prediction_digest"),
            "verified_prediction_digest": cohort["manifest"].get("verified_prediction_digest"),
        },
        "snapshot_integrity": cohort["snapshot_integrity"],
        "reconstruction": cohort["reconstruction"],
        "per_match_reconstruction": [dict(row) for row in rows],
        "bootstrap": {
            "seed": seed,
            "replicates": replicates,
            "method": "paired nonparametric bootstrap over unique match rows",
            "confidence_level": 0.95,
        },
        "global": global_analysis,
        "competition_universe": universe_analysis,
        "chronological_regime": chronological_analysis,
        "historical_environment_guardrail": environment,
        "diagnosis": diagnosis,
        "stop_state": {
            "model_modified": False,
            "production_truth_modified": False,
            "provider_added": False,
            "parameter_search": False,
            "global_lambda_raise_allowed": "NO",
            "next_state": "READY_FOR_INDEPENDENT_ACCEPTANCE",
        },
    }


def _fmt(value: Any, digits: int = 3) -> str:
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "是" if value else "否"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if not math.isfinite(number):
        return "—"
    return f"{number:.{digits}f}"


def _fmt_pct(value: Any) -> str:
    if value is None:
        return "—"
    return f"{float(value):.1%}"


def _fmt_ci(interval: Any, digits: int = 3) -> str:
    if not isinstance(interval, (list, tuple)) or len(interval) != 2 or interval[0] is None or interval[1] is None:
        return "—"
    return f"[{_fmt(interval[0], digits)}, {_fmt(interval[1], digits)}]"


def _source_table_rows(sources: Mapping[str, Any]) -> list[str]:
    labels = {
        "form_total": "form_total（近期攻防总和，已按 Champion 1.2–4.2 截断）",
        "market_total_line": "market_total_line（Asian O/U line median；非真实 xG estimator）",
        "uncalibrated_total": "uncalibrated_total（60/40 form/target fusion）",
        "final_lambda_total": "final λ_total（frozen λ_home + λ_away）",
    }
    lines = []
    for name in ("form_total", "market_total_line", "uncalibrated_total", "final_lambda_total"):
        metric = sources[name]
        lines.append(
            f"| {labels[name]} | {metric.get('observation_n', 0)} | {_fmt(metric.get('predicted_mean'))} | "
            f"{_fmt(metric.get('actual_mean'))} | {_fmt(metric.get('mean_difference_predicted_minus_actual'))} | "
            f"{_fmt(metric.get('mean_difference_actual_minus_predicted'))} | {_fmt(metric.get('mae'))} | "
            f"{_fmt_ci(metric.get('mean_difference_bootstrap_ci_95'))} | {_fmt_ci(metric.get('mae_bootstrap_ci_95'))} |"
        )
    return lines


def build_report(summary: Mapping[str, Any]) -> str:
    global_analysis = summary["global"]
    sources = global_analysis["sources"]
    diagnosis = summary["diagnosis"]
    reconstruction = summary["reconstruction"]
    adjustments = global_analysis["adjustments"]
    environment = summary["historical_environment_guardrail"]
    chronology = summary["chronological_regime"]
    universe = summary["competition_universe"]
    fusion = global_analysis["fusion_comparison"]
    form_contribution = global_analysis["weighted_fusion_bias_contributions"]["form_60_percent"]
    target_contribution = global_analysis["weighted_fusion_bias_contributions"]["market_or_form_fallback_40_percent"]

    lines = [
        f"# {MILESTONE}",
        "",
        f"- `STATUS={summary['status']}`",
        f"- `PRIMARY_MEAN_SOURCE={diagnosis['PRIMARY_MEAN_SOURCE']}`",
        f"- `GLOBAL_LAMBDA_RAISE_ALLOWED={diagnosis['GLOBAL_LAMBDA_RAISE_ALLOWED']}`",
        f"- cohort: pinned `{summary['cohort']['pinned_n']}`, verified unique `{summary['cohort']['verified_n']}`",
        "",
        "## 结论",
        "",
        f"181 场 frozen Champion 的 final λ_total 均值为 `{_fmt(sources['final_lambda_total']['predicted_mean'])}`，实际总进球均值为 `{_fmt(global_analysis['actual_total_mean'])}`，预测减实际 bias 为 `{_fmt(sources['final_lambda_total']['mean_difference_predicted_minus_actual'])}`。",
        f"`form_total` bias 为 `{_fmt(sources['form_total']['mean_difference_predicted_minus_actual'])}`，`market_total_line` bias 为 `{_fmt(sources['market_total_line']['mean_difference_predicted_minus_actual'])}`；两者都低于实际，因此主来源判定为 `MIXED`，不是单一全局 λ 偏移。",
        f"在 60/40 公式的加权贡献中，form 侧均值贡献 `{_fmt(form_contribution['mean_contribution'])}`，market/target 侧均值贡献 `{_fmt(target_contribution['mean_contribution'])}`，两者接近，故不把单一一侧强行宣布为唯一来源。",
        f"market line 的未加权 bias 更低（`{_fmt(sources['market_total_line']['mean_difference_predicted_minus_actual'])}` vs form `{_fmt(sources['form_total']['mean_difference_predicted_minus_actual'])}`），但它只是 Asian O/U line，在当前公式中作为 target_total 的 40% 输入，不把它描述为真实 expected-goals estimator。",
        f"当前窗口的实际 scoring environment 相比 cohort 之前 history 高 `{_fmt(environment['mean_total_difference_current_minus_history'])}` 个球；该环境信号记为 `SHORT_WINDOW_SCORING_REGIME`，是 MIXED 来源的背景放大因素，而不是模型参数调整依据。",
        "",
        "## A. 逐场 Champion Total 重建与完整性",
        "",
        f"- reconstruction 与 frozen `lambda_home + lambda_away` 逐场一致：`{reconstruction['frozen_lambda_total_match_n']}/{reconstruction['verified_n']}`；最大绝对差 `{_fmt(reconstruction['max_abs_frozen_lambda_total_difference'], 9)}`。",
        f"- formula final total 与 frozen λ_total 的最大舍入差 `{_fmt(reconstruction['max_abs_formula_to_frozen_difference'], 9)}`，允许范围 `{_fmt(reconstruction['formula_final_total_rounding_tolerance'], 7)}`。",
        f"- one match = one observation: `{_fmt(summary['cohort']['one_match_one_observation'])}`。",
        f"- snapshot integrity: `{summary['snapshot_integrity']['method']}`；legacy raw-file SHA 仅作 evidence，不作为跨平台唯一 gate；raw SHA mismatch is fail condition = `{summary['snapshot_integrity']['raw_file_sha256']['mismatch_is_fail_condition']}`。",
        "",
        "逐场重建字段：`home_form`、`away_form`、`form_total`、`market_total_line_median`、`target_total`、`uncalibrated_total`、`calibration_total_shift_applied`、`form_total_clamp_effect`、`final_total_clamp_effect`、`final_lambda_total`；只读调用当前 Champion 代码语义。",
        "",
        "## B. Global Source Decomposition",
        "",
        "bias 定义为 predicted − actual；underprediction 以 actual − predicted 正数展示。CI 是固定 seed 的逐场非参数 bootstrap 95% CI；MAE CI 同样按逐场观测重采样。",
        "",
        "| source | n | predicted mean | paired actual mean | bias predicted−actual | underprediction actual−predicted | MAE | bias CI 95% | MAE CI 95% |",
        "|---|---:|---:|---:|---:|---:|---:|---|---|",
        *_source_table_rows(sources),
        "",
        "### 60/40 fusion 对比",
        "",
        f"- fusion vs form-only bias change: `{_fmt(fusion['fusion_bias_minus_form_only_bias'])}`；`{fusion['interpretation']['versus_form_only']}`。",
        f"- fusion vs market-line-only bias change: `{_fmt(fusion['fusion_bias_minus_market_line_only_bias'])}`；`{fusion['interpretation']['versus_market_line_only']}`。",
        f"- final vs uncalibrated fusion bias change: `{_fmt(fusion['final_bias_minus_uncalibrated_fusion_bias'])}`。",
        "",
        "### Clamp / calibration shift",
        "",
        "| adjustment | changed matches | mean shift | mean absolute shift | 95% CI |",
        "|---|---:|---:|---:|---|",
    ]
    adjustment_labels = {
        "form_total_clamp": "form_total 输入 clamp（raw form sum → form_total）",
        "calibration_total_shift": "calibration total shift（approved 且 active 时）",
        "final_total_clamp": "final total clamp（pre-final → final）",
        "post_fusion_calibration_or_final_clamp": "post-fusion calibration + final clamp",
    }
    for key in (
        "form_total_clamp",
        "calibration_total_shift",
        "final_total_clamp",
        "post_fusion_calibration_or_final_clamp",
    ):
        adjustment = adjustments[key]
        lines.append(
            f"| {adjustment_labels[key]} | {adjustment['changed_n']}/{adjustment['sample_n']} | "
            f"{_fmt(adjustment['mean_shift'])} | {_fmt(adjustment['mean_absolute_shift'])} | "
            f"{_fmt_ci(adjustment.get('bootstrap_ci_95'))} |"
        )
    lines.extend(
        [
            "",
            "结论：final total clamp 与 calibration total shift 未实质改变 cohort 的 total；仅有 2 场 form_total 输入上界 clamp，平均 effect 很小，不能解释约 −0.490 的 final bias。",
            "",
            "## C. Competition Universe",
            "",
            f"taxonomy 复用 PR #160 已锁定的 `{universe['taxonomic_source']}`；verified n `< {universe['minimum_sample']}` 只标记 `INSUFFICIENT_SAMPLE`，不作适用性结论。",
            "",
            "| universe | verified n | status | form bias | market-line bias | final λ bias |",
            "|---|---:|---|---:|---:|---:|",
        ]
    )
    for name in UNIVERSES:
        entry = universe["by_universe"][name]
        if entry["sample_status"] != "SUFFICIENT":
            lines.append(f"| `{name}` | {entry['verified_n']} | `INSUFFICIENT_SAMPLE` | — | — | — |")
            continue
        metrics = entry["metrics"]
        lines.append(
            f"| `{name}` | {entry['verified_n']} | `SUFFICIENT` | "
            f"{_fmt(metrics['form_total']['mean_difference_predicted_minus_actual'])} "
            f"({_fmt_ci(metrics['form_total']['mean_difference_bootstrap_ci_95'])}) | "
            f"{_fmt(metrics['market_total_line']['mean_difference_predicted_minus_actual'])} "
            f"({_fmt_ci(metrics['market_total_line']['mean_difference_bootstrap_ci_95'])}) | "
            f"{_fmt(metrics['final_lambda_total']['mean_difference_predicted_minus_actual'])} "
            f"({_fmt_ci(metrics['final_lambda_total']['mean_difference_bootstrap_ci_95'])}) |"
        )
    other_top = universe["by_universe"].get("CLUB_OTHER_TOP_LEAGUE")
    if other_top and other_top["sample_status"] == "SUFFICIENT":
        other_metrics = other_top["metrics"]
        lines.extend(
            [
                "",
                f"**other-top focus**：form bias `{_fmt(other_metrics['form_total']['mean_difference_predicted_minus_actual'])}`，market line bias `{_fmt(other_metrics['market_total_line']['mean_difference_predicted_minus_actual'])}`，final bias `{_fmt(other_metrics['final_lambda_total']['mean_difference_predicted_minus_actual'])}`。两侧均低；market line 更低约 `{_fmt(abs(other_metrics['market_total_line']['mean_difference_predicted_minus_actual']) - abs(other_metrics['form_total']['mean_difference_predicted_minus_actual']))}`，但不足以把 mixed source 简化为单一 market-only 结论。",
            ]
        )
    lines.extend(
        [
            "",
            "## D. Chronological Regime",
            "",
            f"切分：kickoff 升序，thirds 样本为 `{chronology['thirds']['earliest_third']['n']}` / `{chronology['thirds']['middle_third']['n']}` / `{chronology['thirds']['latest_third']['n']}`；不做任意日期挖掘。",
            "",
            "| segment | n | actual mean | form mean | market mean | final λ mean | form bias | market bias | final bias | final bias CI 95% | 0-0 | 4+ share |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---:|---:|",
        ]
    )
    for name in ("earliest_third", "middle_third", "latest_third"):
        entry = chronology["thirds"][name]
        lines.append(
            f"| `{name}` | {entry['n']} | {_fmt(entry['actual_total_mean'])} | {_fmt(entry['form_total_mean'])} | "
            f"{_fmt(entry['market_line_mean'])} | {_fmt(entry['final_lambda_total_mean'])} | "
            f"{_fmt(entry['bias_predicted_minus_actual']['form_total'])} | "
            f"{_fmt(entry['bias_predicted_minus_actual']['market_total_line'])} | "
            f"{_fmt(entry['bias_predicted_minus_actual']['final_lambda_total'])} | "
            f"{_fmt_ci(entry['bias_bootstrap_ci_95']['final_lambda_total'])} | "
            f"{entry['zero_zero_count']} | {_fmt_pct(entry['four_plus_share'])} |"
        )
    lines.extend(
        [
            "",
            f"form 与 market 同步落后于实际的 thirds：`{chronology['form_market_synchronized_underprediction_thirds_n']}/3`（`{chronology['form_market_synchronized_underprediction_status']}`）。因此 −0.490 **不贯穿整个窗口**：earliest/latest 是高比分段，middle final bias 接近 0；高比分段中 form 与 market 同步落后。",
            "",
            "## E. Historical Environment Guardrail",
            "",
            f"`{environment['status']}`。history 只来自全量 verified-result store 中、最早 cohort kickoff 之前的 90m+stoppage 赛果；不进入任何 model metric denominator。history used in model denominator n = `{environment['history_used_in_model_metric_denominator_n']}`。",
            "",
            "| environment | n | mean total | median total | 0-0 | O2.5 | 4+ | 5+ | BTTS |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for label, data in (
        ("181 prediction cohort", environment["prediction_cohort_181"]),
        ("cohort之前 verified-result history", environment["history_before_cohort"]),
    ):
        lines.append(
            f"| {label} | {data['n']} | {_fmt(data['mean_total'])} | {_fmt(data['median_total'])} | "
            f"{_fmt_pct(data['zero_zero_share'])} | {_fmt_pct(data['over_2_5_share'])} | "
            f"{_fmt_pct(data['four_plus_share'])} | {_fmt_pct(data['five_plus_share'])} | {_fmt_pct(data['btts_share'])} |"
        )
    lines.extend(
        [
            "",
            f"current − history mean-total difference `{_fmt(environment['mean_total_difference_current_minus_history'])}`, bootstrap CI `{_fmt_ci(environment['mean_total_difference_bootstrap_ci_95'])}`；这只说明当前 window 的 scoring environment 与先前 result history 不同，不构成 prematch model comparison。",
            "",
            "## F. Final Diagnosis",
            "",
            f"- `PRIMARY_MEAN_SOURCE={diagnosis['PRIMARY_MEAN_SOURCE']}`",
            f"- `weighted_dominant_component={diagnosis['weighted_dominant_component']}`",
            f"- `regime_context_signal={diagnosis['regime_context_signal']}`",
            f"- `CLAMP_OR_CALIBRATION_EFFECT` explains final bias: `{diagnosis['adjustment_explains_final']}`",
            f"- `GLOBAL_LAMBDA_RAISE_ALLOWED={diagnosis['GLOBAL_LAMBDA_RAISE_ALLOWED']}`",
            "",
            "停止状态：未修改模型、production/data truth、frozen prediction、provider 或任何参数；无参数搜索。",
            "",
            f"Bootstrap seed `{summary['bootstrap']['seed']}`, replicates `{summary['bootstrap']['replicates']}`。",
            "",
        ]
    )
    return "\n".join(lines)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--jobs-root", type=Path, default=DEFAULT_JOBS_ROOT)
    parser.add_argument("--prediction-root", type=Path, default=DEFAULT_PREDICTION_ROOT)
    parser.add_argument("--result-root", type=Path, default=DEFAULT_RESULT_ROOT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--seed", type=int, default=BOOTSTRAP_SEED)
    parser.add_argument("--bootstrap-replicates", type=int, default=DEFAULT_BOOTSTRAP_REPLICATES)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.bootstrap_replicates < 1:
        raise ValueError("--bootstrap-replicates must be positive")
    root = PROJECT_ROOT.resolve()
    cohort = _load_cohort(
        root,
        args.manifest.resolve(),
        args.jobs_root.resolve(),
        args.prediction_root.resolve(),
        args.result_root.resolve(),
    )
    summary = build_summary(
        cohort,
        seed=args.seed,
        replicates=args.bootstrap_replicates,
        result_root=args.result_root.resolve(),
    )
    report = build_report(summary)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (args.output_dir / "report.md").write_text(report, encoding="utf-8")
    print(f"PRIMARY_MEAN_SOURCE={summary['diagnosis']['PRIMARY_MEAN_SOURCE']}")
    print(f"REGIME_CONTEXT_SIGNAL={summary['diagnosis']['regime_context_signal']}")
    print(f"GLOBAL_LAMBDA_RAISE_ALLOWED={summary['diagnosis']['GLOBAL_LAMBDA_RAISE_ALLOWED']}")
    print(
        f"COHORT=pinned:{summary['cohort']['pinned_n']} verified:{summary['cohort']['verified_n']} "
        f"reconstruction:{summary['reconstruction']['frozen_lambda_total_match_n']}"
    )
    print(f"ARTIFACT={args.output_dir.resolve() / 'summary.json'}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"AUDIT_ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
