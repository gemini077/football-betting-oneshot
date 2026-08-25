"""Build a frozen, research-only Phase2C1 Challenger record for future pairs.

The adapter deliberately does not call the production governance builder.  It
uses the existing Phase2C1 model calculation, adds the explicit prospective
identity/timing contract required by ``PairLedger``, and never consumes a
target match result.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
import hashlib
from typing import Any

from model_governance import canonical_json, prediction_content_hash
from football_data.phase2c1_model import CandidateSpec, build_team_strength_prediction


CHALLENGER_ID = "research:phase2c1-basic-team-strength:last10-shrink10:v1"
MODEL_FAMILY = "research_phase2c1_basic_team_strength"
MODEL_CORE_VERSION = "basic_team_strength_poisson.v1"
ADAPTER_VERSION = "phase2c1_prospective_candidate_adapter.v1"
PHASE2C1_SPEC = CandidateSpec(window="last_10", shrinkage=10)

_TARGET_RESULT_FIELDS = frozenset(
    {
        "actual",
        "actual_home_goals",
        "actual_away_goals",
        "actual_score",
        "away_goals",
        "home_goals",
        "postmatch_evidence",
        "result",
        "score_90m",
        "settlement",
        "verified_at",
    }
)


def _parse_time(value: Any, field: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            parsed = None
    else:
        parsed = None
    if parsed is None or parsed.tzinfo is None:
        raise ValueError(f"{field}_MUST_BE_TIMEZONE_AWARE_ISO8601")
    return parsed.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _require_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field}_MISSING")
    return value.strip()


def _score_label(cell: Mapping[str, Any]) -> str:
    try:
        home = int(cell["home_goals"])
        away = int(cell["away_goals"])
        probability = float(cell["probability"])
    except (KeyError, TypeError, ValueError):
        raise ValueError("PHASE2C1_SCORE_CELL_INVALID") from None
    if home < 0 or away < 0 or probability < 0.0:
        raise ValueError("PHASE2C1_SCORE_CELL_INVALID")
    return f"{home}-{away}"


def _one_x_two(prediction: Mapping[str, Any]) -> dict[str, float]:
    probabilities = prediction.get("probabilities")
    if not isinstance(probabilities, Mapping):
        raise ValueError("PHASE2C1_PROBABILITIES_MISSING")
    values = probabilities.get("1x2")
    if not isinstance(values, Mapping):
        raise ValueError("PHASE2C1_ONE_X_TWO_MISSING")
    try:
        result = {key: float(values[key]) for key in ("home", "draw", "away")}
    except (KeyError, TypeError, ValueError):
        raise ValueError("PHASE2C1_ONE_X_TWO_MISSING") from None
    if any(value < 0.0 for value in result.values()) or abs(sum(result.values()) - 1.0) > 1e-6:
        raise ValueError("PHASE2C1_ONE_X_TWO_INVALID")
    return result


def _validate_target(target: Mapping[str, Any], match_identity: Mapping[str, Any]) -> tuple[str, datetime]:
    forbidden = sorted(field for field in target if field in _TARGET_RESULT_FIELDS)
    if forbidden:
        raise ValueError("TARGET_RESULT_FIELDS_FORBIDDEN:" + ",".join(forbidden))
    match_key = _require_text(match_identity.get("match_key"), "MATCH_IDENTITY_MATCH_KEY")
    identity_kickoff = _parse_time(match_identity.get("kickoff_at"), "MATCH_IDENTITY_KICKOFF_AT")
    target_kickoff = _parse_time(target.get("kickoff_at") or target.get("kickoff"), "TARGET_KICKOFF_AT")
    if identity_kickoff != target_kickoff:
        raise ValueError("MATCH_IDENTITY_KICKOFF_MISMATCH")
    _require_text(target.get("canonical_match_id") or target.get("target_match_id"), "TARGET_CANONICAL_MATCH_ID")
    _require_text(target.get("competition_id"), "TARGET_COMPETITION_ID")
    _require_text(target.get("season_id"), "TARGET_SEASON_ID")
    _require_text(target.get("home_team_id"), "TARGET_HOME_TEAM_ID")
    _require_text(target.get("away_team_id"), "TARGET_AWAY_TEAM_ID")
    return match_key, target_kickoff


def _prematch_history(
    history: Iterable[Mapping[str, Any]],
    *,
    source_cutoff: datetime,
    kickoff: datetime,
) -> list[dict[str, Any]]:
    rows = [dict(row) for row in history]
    if not rows:
        raise ValueError("PREMATCH_HISTORY_MISSING")
    for row in rows:
        row_kickoff = _parse_time(row.get("kickoff_at"), "HISTORY_KICKOFF_AT")
        if row_kickoff >= kickoff:
            raise ValueError("NON_PREMATCH_HISTORY_FORBIDDEN")
        if row_kickoff >= source_cutoff:
            raise ValueError("HISTORY_AFTER_SOURCE_CUTOFF_FORBIDDEN")
    return sorted(rows, key=lambda row: (str(row.get("kickoff_at")), canonical_json(row)))


def _deterministic_fingerprint(kind: str, *, input_sha256: str | None = None) -> str:
    return _sha256(
        {
            "adapter_version": ADAPTER_VERSION,
            "candidate_id": CHALLENGER_ID,
            "formula_version": MODEL_CORE_VERSION,
            "kind": kind,
            "input_sha256": input_sha256,
        }
    )


def validate_candidate_record(record: Mapping[str, Any]) -> dict[str, Any]:
    """Validate the adapter's immutable content hash and research boundary."""

    value = dict(record)
    if value.get("model_role") != "challenger" or value.get("challenger_id") != CHALLENGER_ID:
        raise ValueError("RESEARCH_CHALLENGER_IDENTITY_INVALID")
    if value.get("prediction_status") != "FROZEN":
        raise ValueError("CANDIDATE_NOT_FROZEN")
    if value.get("production_registration") is not False or value.get("automatic_promotion") is not False:
        raise ValueError("PRODUCTION_BOUNDARY_INVALID")
    if value.get("prediction_sha256") != prediction_content_hash(value):
        raise ValueError("PREDICTION_CONTENT_HASH_MISMATCH")
    return value


def build_prospective_candidate_record(
    target: Mapping[str, Any],
    prematch_history: Iterable[Mapping[str, Any]],
    *,
    match_identity: Mapping[str, Any],
    source_cutoff_at: str | datetime,
    prediction_created_at: str | datetime,
    freeze_created_at: str | datetime,
    now: str | datetime,
    model_source_fingerprint: str | None = None,
    model_run_fingerprint: str | None = None,
) -> dict[str, Any]:
    """Build one future-only Phase2C1 record without production side effects."""

    match_key, kickoff = _validate_target(target, match_identity)
    cutoff = _parse_time(source_cutoff_at, "SOURCE_CUTOFF_AT")
    created = _parse_time(prediction_created_at, "PREDICTION_CREATED_AT")
    freeze = _parse_time(freeze_created_at, "FREEZE_CREATED_AT")
    current = _parse_time(now, "NOW")
    if not cutoff < created <= freeze < kickoff:
        raise ValueError("PROSPECTIVE_TEMPORAL_ORDER_INVALID")
    if current >= kickoff:
        raise ValueError("KICKOFF_ALREADY_STARTED")
    if freeze > current:
        raise ValueError("FREEZE_AFTER_NOW")

    history = _prematch_history(prematch_history, source_cutoff=cutoff, kickoff=kickoff)
    input_projection = {
        "contract": ADAPTER_VERSION,
        "candidate_id": CHALLENGER_ID,
        "match_identity": dict(match_identity),
        "target": dict(target),
        "source_cutoff_at": _iso(cutoff),
        "history": history,
    }
    input_sha256 = _sha256(input_projection)
    source_fingerprint = model_source_fingerprint or _deterministic_fingerprint("source")
    run_fingerprint = model_run_fingerprint or _deterministic_fingerprint("run", input_sha256=input_sha256)
    _require_text(source_fingerprint, "MODEL_SOURCE_FINGERPRINT")
    _require_text(run_fingerprint, "MODEL_RUN_FINGERPRINT")

    prediction = build_team_strength_prediction(target, history, PHASE2C1_SPEC)
    probabilities = _one_x_two(prediction)
    top_scores = prediction.get("probabilities", {}).get("top_scores")
    if not isinstance(top_scores, list) or not top_scores:
        raise ValueError("PHASE2C1_TOP_SCORES_MISSING")
    score_top3 = [_score_label(cell) for cell in top_scores[:3]]
    score_top1 = score_top3[0]
    lambda_home = float(prediction["lambda_home"])
    lambda_away = float(prediction["lambda_away"])
    lambda_gap = abs(lambda_home - lambda_away)
    prediction_id = f"FBOS-{CHALLENGER_ID.split(':')[1]}-{input_sha256[:24]}"
    snapshot_ref = f"research://phase2c1/{input_sha256}"
    record: dict[str, Any] = {
        "prediction_id": prediction_id,
        "prediction_status": "FROZEN",
        "model_role": "challenger",
        "challenger_id": CHALLENGER_ID,
        "model_family": MODEL_FAMILY,
        "model_core_version": MODEL_CORE_VERSION,
        "release_version": "research-only",
        "model_source_fingerprint": source_fingerprint,
        "model_run_fingerprint": run_fingerprint,
        "match_key": match_key,
        "match_id": match_identity.get("match_id") or target.get("canonical_match_id"),
        "match_identity": dict(match_identity),
        "kickoff_at": _iso(kickoff),
        "source_cutoff_at": _iso(cutoff),
        "prediction_created_at": _iso(created),
        "freeze_created_at": _iso(freeze),
        "model_input_as_of_at": _iso(cutoff),
        "model_input_snapshot_ref": snapshot_ref,
        "input_sha256": input_sha256,
        "canonical_model_input_sha256": input_sha256,
        "input_snapshot": {
            "canonical_input_sha256": input_sha256,
            "canonical_model_input_sha256": input_sha256,
            "source_cutoff_at": _iso(cutoff),
            "snapshot_ref": snapshot_ref,
        },
        "snapshot_identity": {"snapshot_id": input_sha256, "source_cutoff_at": _iso(cutoff)},
        "model_run_identity": {
            "model_source_fingerprint": source_fingerprint,
            "model_run_fingerprint": run_fingerprint,
            "candidate_id": CHALLENGER_ID,
            "input_sha256": input_sha256,
        },
        "probabilities": probabilities,
        "lambda_home": lambda_home,
        "lambda_away": lambda_away,
        "score_top1": score_top1,
        "score_top3": score_top3,
        "structural_evidence": {
            "top1_is_one_to_one": score_top1 == "1-1",
            "lambda_gap": lambda_gap,
            "lambda_gap_below_0_5": lambda_gap < 0.5,
        },
        "features": prediction["features"],
        "candidate_spec": prediction["candidate_spec"],
        "prediction_output": {
            "status": "research_only",
            "probabilities": probabilities,
            "lambda_home": lambda_home,
            "lambda_away": lambda_away,
            "score_top1": score_top1,
            "score_top3": score_top3,
        },
        "research_only": True,
        "formal_eligible": False,
        "model_formal_eligible": False,
        "production_registration": False,
        "automatic_promotion": False,
        "market_used": False,
        "market_snapshot_at": None,
        "prediction_sha256": None,
    }
    record["prediction_sha256"] = prediction_content_hash(record)
    return validate_candidate_record(record)


__all__ = [
    "ADAPTER_VERSION",
    "CHALLENGER_ID",
    "MODEL_CORE_VERSION",
    "MODEL_FAMILY",
    "PHASE2C1_SPEC",
    "build_prospective_candidate_record",
    "validate_candidate_record",
]
