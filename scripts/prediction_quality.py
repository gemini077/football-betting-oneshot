#!/usr/bin/env python3
"""Shared research/formal prediction grading rules."""
from __future__ import annotations

from datetime import datetime, timezone
import math
from typing import Any


EXECUTION_ONLY_MISSING = {"用户渠道即时赔率"}


BASE_PREDICTION_POLICY = "base_prediction_minimum.v1"


def recent_form_is_usable(form: Any) -> bool:
    """Return whether the Champion's minimum four recent-form blocks exist."""
    if not isinstance(form, dict):
        return False
    for key in ("home_overall", "home_home", "away_overall", "away_away"):
        row = form.get(key)
        if not isinstance(row, dict):
            return False
        try:
            matches = float(row.get("matches") or 0)
            goals_for = float(row.get("goals_for"))
            goals_against = float(row.get("goals_against"))
        except (TypeError, ValueError):
            return False
        if matches <= 0 or not math.isfinite(goals_for) or not math.isfinite(goals_against):
            return False
    return True


def _parse_timestamp(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed


def _finite_number(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _recent_form_from_projection(projection: dict[str, Any]) -> Any:
    fundamentals = projection.get("prematch_fundamentals") or {}
    if recent_form_is_usable(fundamentals.get("recent_form")):
        return fundamentals.get("recent_form")
    for source in (projection.get("source_snapshots") or {}).values():
        snapshots = source.get("snapshots") if isinstance(source, dict) else None
        if not isinstance(snapshots, list):
            continue
        for snapshot in snapshots:
            form = ((snapshot or {}).get("shuju") or {}).get("recent_form")
            if recent_form_is_usable(form):
                return form
    return None


def classify_base_prediction(
    payload: dict[str, Any],
    *,
    context: dict[str, Any],
) -> dict[str, Any]:
    """Evaluate the explicit minimum BASE formal contract.

    This policy intentionally does not consult checkpoint count.  Checkpoint
    count remains the generic deep-evidence grade produced by
    :func:`classify_prediction`.
    """
    failures: list[str] = []
    model = payload.get("model") or {}
    match = payload.get("match") or {}
    decisions = payload.get("decisions") or {}
    projection = context.get("input_projection") or {}

    if context.get("model_role") != "champion":
        failures.append("MODEL_ROLE_NOT_CHAMPION")
    if context.get("prediction_variant") != "model_only":
        failures.append("PREDICTION_VARIANT_NOT_MODEL_ONLY")
    if context.get("manual_override"):
        failures.append("MANUAL_OVERRIDE")
    if not context.get("has_model_snapshot"):
        failures.append("MISSING_MODEL_INPUT_SNAPSHOT")
    if not context.get("input_hash_valid"):
        failures.append("INPUT_HASH_INVALID")
    if not str(context.get("model_source_fingerprint") or "").strip():
        failures.append("MISSING_MODEL_SOURCE_FINGERPRINT")

    match_key = str(
        context.get("match_key")
        or match.get("canonical_match_id")
        or match.get("match_id")
        or ""
    ).strip()
    if not match_key or not str(match.get("home") or "").strip() or not str(match.get("away") or "").strip():
        failures.append("INVALID_MATCH_IDENTITY")

    kickoff = _parse_timestamp(context.get("kickoff_at") or match.get("kickoff_local"))
    if kickoff is None:
        failures.append("INVALID_KICKOFF")

    source_cutoff = _parse_timestamp(context.get("source_cutoff_at"))
    prediction_created_at = _parse_timestamp(context.get("prediction_created_at"))
    freeze_created_at = _parse_timestamp(context.get("freeze_created_at"))
    if (
        source_cutoff is None
        or prediction_created_at is None
        or freeze_created_at is None
        or kickoff is None
        or not (source_cutoff < prediction_created_at <= freeze_created_at < kickoff)
    ):
        failures.append("INVALID_PREMATCH_TIMESTAMP_ORDER")

    if not recent_form_is_usable(_recent_form_from_projection(projection)):
        failures.append("MISSING_RECENT_FORM")

    market_quality = str(
        context.get("market_intelligence_quality")
        or (payload.get("data_quality") or {}).get("market_intelligence_quality")
        or ""
    ).upper()
    if market_quality not in {"FULL", "LIMITED"}:
        failures.append("MISSING_MARKET_INTELLIGENCE")

    critical_missing = [str(item) for item in context.get("critical_missing_fields") or [] if item]
    if critical_missing:
        failures.append("BASE_CRITICAL_MISSING_FIELDS")

    probabilities = model.get("probabilities") if isinstance(model, dict) else None
    probability_values = (
        [probabilities.get(key) for key in ("home", "draw", "away")]
        if isinstance(probabilities, dict)
        else []
    )
    btts = model.get("btts") if isinstance(model, dict) else None
    scores = model.get("score_probabilities") if isinstance(model, dict) else None
    totals = model.get("total_goals_buckets") if isinstance(model, dict) else None
    output_complete = (
        _finite_number(model.get("lambda_home"))
        and _finite_number(model.get("lambda_away"))
        and isinstance(probabilities, dict)
        and all(_finite_number(value) for value in probability_values)
        and abs(sum(float(value) for value in probability_values) - 1.0) <= 0.02
        and isinstance(btts, dict)
        and all(_finite_number(btts.get(key)) for key in ("yes", "no"))
        and isinstance(totals, list)
        and bool(totals)
        and isinstance(scores, list)
        and len(scores) >= 5
        and bool(str(decisions.get("unique_primary_dimension") or "").strip())
        and bool(str(decisions.get("unique_score") or "").strip())
    )
    if not output_complete:
        failures.append("INCOMPLETE_MODEL_OUTPUT")

    failures = list(dict.fromkeys(failures))
    timestamp_failure = "INVALID_PREMATCH_TIMESTAMP_ORDER" in failures or "INVALID_KICKOFF" in failures
    return {
        "formal_eligibility_policy": BASE_PREDICTION_POLICY,
        "base_input_quality": (
            "VERIFIED_MINIMUM" if not failures else "INVALID_TIMESTAMP" if timestamp_failure else "INSUFFICIENT"
        ),
        "formal_eligible": not failures,
        "model_formal_eligible": not failures,
        "base_quality_reasons": failures,
        "generic_data_grade": str(context.get("generic_data_grade") or "C").upper(),
    }


def checkpoint_count(payload: dict[str, Any]) -> int:
    checkpoints = payload.get("market_history") or payload.get("checkpoints") or []
    legacy_count = len(checkpoints) if isinstance(checkpoints, list) else 0
    model = payload.get("model") or {}
    features = ((model.get("calibration") or {}).get("checkpoint_features") or {})
    try:
        feature_count = int(features.get("snapshot_count") or 0)
    except (TypeError, ValueError):
        feature_count = 0
    return max(legacy_count, feature_count)


def classify_prediction(payload: dict[str, Any]) -> dict[str, Any]:
    """Grade evidence without treating missing execution price as model evidence."""
    quality = payload.get("data_quality") or (payload.get("analysis") or {}).get("data_quality") or {}
    missing = [
        str(item) for item in quality.get("missing") or []
        if item and str(item) not in EXECUTION_ONLY_MISSING
    ]
    count = checkpoint_count(payload)
    if not missing and count >= 4:
        grade, weight = "A", 1.0
    elif len(missing) <= 2 and count >= 2:
        grade, weight = "B", 0.7
    else:
        grade, weight = "C", 0.4
    decisions = payload.get("decisions") or {}
    formal = grade in {"A", "B"} and bool(decisions.get("unique_primary_dimension"))
    betting = payload.get("betting") or {}
    return {
        "research": True,
        "data_grade": grade,
        "calibration_weight": weight,
        "formal_pick_eligible": formal,
        "execution_eligible": formal and bool(betting.get("candidates")),
        "checkpoint_count": count,
        "analysis_missing": missing,
    }
