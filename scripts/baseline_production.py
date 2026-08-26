#!/usr/bin/env python3
"""Production bridge from the frozen Phase 0 ledger to the Phase 1 benchmark."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from baseline_settlement import (
    DEFAULT_SETTLEMENT_ROOT,
    freeze_settlement,
    settle_comparison,
)
from baseline_shadow_runner import (
    DEFAULT_PREDICTION_ROOT,
    build_comparison,
    comparison_id_for,
    freeze_comparison,
    load_frozen_comparison,
)
from model_governance import DEFAULT_INPUT_SNAPSHOT_ROOT, load_input_snapshot


ROOT = Path(__file__).resolve().parents[1]
BENCHMARK_SNAPSHOT_VERSION = "benchmark_snapshot.v1"
PHASE1_PROSPECTIVE_NOT_BEFORE_SHA = "a14a654e3d80186bb8c93561939e51a4b1ec4ff4"
REGISTERED_CHECKPOINT_STAGES = {
    "T-8H", "T-6H", "T-4H", "T-2H", "T-90M", "T-60M", "T-30M", "T-10M",
}
MARKET_DIRECTION_SHADOW_CANDIDATE_ID = "market-direction-fusion-full-v1"
MARKET_DIRECTION_SHADOW_CONTRACT_VERSION = "market_direction_fusion_shadow.v1"
MARKET_DIRECTION_SHADOW_PREDICTOR_NAME = "market_direction_fusion_full_v1"


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _sha256_value(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _invalid_snapshot(reason: str, *, record: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "benchmark_snapshot_version": BENCHMARK_SNAPSHOT_VERSION,
        "benchmark_snapshot_status": "invalid",
        "status_reason": reason,
        "match_key": (record or {}).get("match_key"),
        "snapshot_id": None,
        "canonical_model_input_sha256": (record or {}).get("canonical_model_input_sha256"),
        "synthetic": False,
        "historical": False,
    }


def _record_snapshot(record: dict[str, Any]) -> dict[str, Any]:
    snapshot = record.get("input_snapshot")
    return snapshot if isinstance(snapshot, dict) else {}


def _checkpoint_metadata(
    record: dict[str, Any],
    checkpoint_metadata: dict[str, Any] | None,
) -> dict[str, Any]:
    stored = record.get("checkpoint_metadata")
    stored = stored if isinstance(stored, dict) else {}
    supplied = checkpoint_metadata if isinstance(checkpoint_metadata, dict) else {}
    for stored_key, supplied_key in (
        ("stage", "stage"),
        ("target_at", "target_at"),
        ("scheduled_at", "scheduled_at"),
        ("captured_at", "captured_at"),
    ):
        if stored.get(stored_key) not in (None, "") and supplied.get(supplied_key) not in (None, ""):
            if stored[stored_key] != supplied[supplied_key]:
                return {
                    "source": "invalid",
                    "checkpoint_stage": "unclassified",
                    "checkpoint_target_at": None,
                    "checkpoint_captured_at": None,
                    "minutes_to_kickoff_at_capture": None,
                    "capture_quality": None,
                    "target_minutes_before": None,
                    "status_reason": "checkpoint_metadata_mismatch",
                }
    merged = {**stored, **supplied}
    stage = (
        merged.get("stage")
        or record.get("checkpoint_stage")
        or "unclassified"
    )
    target_at = (
        merged.get("target_at")
        or merged.get("scheduled_at")
        or record.get("checkpoint_target_at")
    )
    captured_at = (
        merged.get("captured_at")
        or record.get("checkpoint_captured_at")
    )
    minutes = (
        merged.get("minutes_to_kickoff_at_capture")
        if merged.get("minutes_to_kickoff_at_capture") is not None
        else merged.get("actual_minutes_before")
    )
    if stage not in REGISTERED_CHECKPOINT_STAGES:
        stage = "unclassified"
    return {
        "source": merged.get("source") or "unclassified",
        "checkpoint_stage": stage,
        "checkpoint_target_at": target_at,
        "checkpoint_captured_at": captured_at,
        "minutes_to_kickoff_at_capture": minutes,
        "capture_quality": merged.get("capture_quality"),
        "target_minutes_before": merged.get("target_minutes_before")
        or merged.get("scheduled_target_minutes"),
    }


def build_benchmark_snapshot_from_frozen_prediction(
    champion_prediction: dict[str, Any],
    *,
    checkpoint_metadata: dict[str, Any] | None = None,
    snapshot_root: Path = DEFAULT_INPUT_SNAPSHOT_ROOT,
    repository_root: Path = ROOT,
) -> dict[str, Any]:
    """Adapt a formal frozen Champion plus its immutable input into v1.

    The only model input copied into the result is the content loaded through
    ``load_input_snapshot``.  No live provider, workspace, HTML, or Champion
    recalculation is reachable from this function.
    """
    if not isinstance(champion_prediction, dict):
        return _invalid_snapshot("frozen_champion_missing")
    formal = (
        champion_prediction.get("model_role") == "champion"
        and champion_prediction.get("model_formal_eligible") is True
        and champion_prediction.get("prediction_variant") == "model_only"
        and champion_prediction.get("prediction_status") == "formal"
    )
    if not formal:
        return _invalid_snapshot("frozen_champion_not_formal", record=champion_prediction)

    required_record_fields = (
        "prediction_id", "canonical_model_input_sha256", "model_input_snapshot_ref",
        "match_key", "source_cutoff_at", "market_snapshot_at",
    )
    missing = [field for field in required_record_fields if champion_prediction.get(field) in (None, "")]
    if missing:
        return _invalid_snapshot("frozen_champion_identity_missing:" + ",".join(missing), record=champion_prediction)

    record_snapshot = _record_snapshot(champion_prediction)
    expected_hash = str(champion_prediction.get("canonical_model_input_sha256"))
    if record_snapshot.get("canonical_model_input_sha256") != expected_hash:
        return _invalid_snapshot("record_snapshot_hash_mismatch", record=champion_prediction)
    if Path(str(champion_prediction["model_input_snapshot_ref"])).name != f"{expected_hash}.json":
        return _invalid_snapshot("model_input_snapshot_ref_identity_mismatch", record=champion_prediction)
    snapshot_path = Path(snapshot_root) / f"{expected_hash}.json"
    if not snapshot_path.is_file():
        return _invalid_snapshot("immutable_snapshot_ref_missing", record=champion_prediction)
    if Path(snapshot_root).resolve() == Path(DEFAULT_INPUT_SNAPSHOT_ROOT).resolve():
        repository_ref = Path(repository_root) / str(champion_prediction["model_input_snapshot_ref"])
        if not repository_ref.is_file():
            return _invalid_snapshot("model_input_snapshot_ref_not_present_in_repository", record=champion_prediction)

    try:
        frozen_document = load_input_snapshot(champion_prediction, Path(snapshot_root))
    except (OSError, ValueError, json.JSONDecodeError) as error:
        return _invalid_snapshot(f"immutable_snapshot_unavailable:{type(error).__name__}", record=champion_prediction)
    if not isinstance(frozen_document, dict) or not isinstance(frozen_document.get("input"), dict):
        return _invalid_snapshot("immutable_snapshot_input_missing", record=champion_prediction)

    model_input = frozen_document["input"]
    content_hash = _sha256_value(model_input)
    if content_hash != expected_hash:
        return _invalid_snapshot("record_snapshot_content_hash_mismatch", record=champion_prediction)
    if frozen_document.get("canonical_model_input_sha256") != expected_hash:
        return _invalid_snapshot("snapshot_metadata_hash_mismatch", record=champion_prediction)
    if frozen_document.get("snapshot_id") != record_snapshot.get("snapshot_id"):
        return _invalid_snapshot("snapshot_id_mismatch", record=champion_prediction)

    checkpoint = _checkpoint_metadata(champion_prediction, checkpoint_metadata)
    if checkpoint.get("status_reason"):
        return _invalid_snapshot(checkpoint["status_reason"], record=champion_prediction)
    snapshot_id = str(record_snapshot.get("snapshot_id") or frozen_document.get("snapshot_id"))
    result = {
        "benchmark_snapshot_version": BENCHMARK_SNAPSHOT_VERSION,
        "benchmark_snapshot_status": "valid",
        "status_reason": None,
        "match_key": champion_prediction.get("match_key"),
        "snapshot_id": snapshot_id,
        "canonical_model_input_sha256": expected_hash,
        "source_cutoff_at": champion_prediction.get("source_cutoff_at"),
        "market_snapshot_at": champion_prediction.get("market_snapshot_at"),
        "checkpoint_stage": checkpoint["checkpoint_stage"],
        "checkpoint_target_at": checkpoint["checkpoint_target_at"],
        "checkpoint_captured_at": checkpoint["checkpoint_captured_at"],
        "minutes_to_kickoff_at_capture": checkpoint["minutes_to_kickoff_at_capture"],
        "checkpoint_metadata": checkpoint,
        "champion_prediction_id": champion_prediction["prediction_id"],
        "model_input_snapshot_ref": champion_prediction["model_input_snapshot_ref"],
        "model_input": deepcopy(model_input),
        "synthetic": False,
        "historical": False,
        "prospective_not_before_sha": PHASE1_PROSPECTIVE_NOT_BEFORE_SHA,
    }
    return result



def _parse_aware(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value or "").strip()
        if not text:
            return None
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def _valid_probabilities(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    try:
        values = [float(value[key]) for key in ("home", "draw", "away")]
    except (KeyError, TypeError, ValueError):
        return False
    return all(math.isfinite(number) and number >= 0 for number in values) and sum(values) > 0


def _score_rows(matrix: dict[tuple[int, int], float]) -> list[dict[str, Any]]:
    rows = [
        {
            "score": f"{home}-{away}",
            "home_goals": home,
            "away_goals": away,
            "probability": float(probability),
        }
        for (home, away), probability in matrix.items()
    ]
    return sorted(rows, key=lambda row: (-row["probability"], row["home_goals"], row["away_goals"]))


def _close(left: Any, right: Any, tolerance: float = 1e-6) -> bool:
    try:
        return abs(float(left) - float(right)) <= tolerance
    except (TypeError, ValueError):
        return False


def _market_direction_candidate(
    champion_prediction: dict[str, Any],
    snapshot: dict[str, Any],
) -> tuple[dict[str, Any] | None, str | None, dict[str, Any]]:
    """Replay Champion from frozen input, then change only final direction share."""
    model_input = snapshot.get("model_input") or snapshot.get("input")
    if not isinstance(model_input, dict):
        return None, "immutable_snapshot_input_missing", {}
    try:
        from automatic_model_core import (
            _calibration_state,
            _market_share,
            _mix_dispersion,
            _model_rows,
            _outcomes,
            _reweight_outcomes,
            build_automatic_model,
        )
        from risk_engine import dixon_coles_score_matrix

        replay = build_automatic_model(model_input)
    except Exception as error:
        return None, f"champion_replay_error:{type(error).__name__}", {}
    replay_model = replay.get("model") if isinstance(replay, dict) else None
    if not isinstance(replay_model, dict):
        return None, "champion_replay_no_model", {}
    output = champion_prediction.get("prediction_output") or {}
    stored_probabilities = champion_prediction.get("probabilities") or output.get("probabilities")
    stored_home = champion_prediction.get("lambda_home")
    stored_away = champion_prediction.get("lambda_away")
    if stored_home is None:
        stored_home = output.get("lambda_home")
    if stored_away is None:
        stored_away = output.get("lambda_away")
    if not _valid_probabilities(stored_probabilities) or stored_home is None or stored_away is None:
        return None, "champion_output_missing", {}
    replay_probabilities = replay_model.get("probabilities") or {}
    stored_score_rows = champion_prediction.get("score_matrix") or champion_prediction.get("score_probabilities") or output.get("score_matrix") or output.get("score_probabilities") or []
    replay_score_rows = replay_model.get("score_probabilities") or replay_model.get("score_matrix") or []
    stored_raw_top1 = str(champion_prediction.get("score_top1") or (stored_score_rows[0].get("score") if stored_score_rows and isinstance(stored_score_rows[0], dict) else ""))
    replay_raw_top1 = str(replay_score_rows[0].get("score") if replay_score_rows and isinstance(replay_score_rows[0], dict) else "")
    parity = {
        "lambda_home": _close(stored_home, replay_model.get("lambda_home")),
        "lambda_away": _close(stored_away, replay_model.get("lambda_away")),
        "probabilities": _valid_probabilities(replay_probabilities) and all(
            _close(stored_probabilities.get(key), replay_probabilities.get(key))
            for key in ("home", "draw", "away")
        ),
        "raw_score_top1": bool(stored_raw_top1) and bool(replay_raw_top1) and stored_raw_top1 == replay_raw_top1,
    }
    if not all(parity.values()):
        return None, "champion_replay_parity_failure", {"parity": parity}
    calibration = replay_model.get("calibration") or {}
    try:
        form_home = float(calibration["form_lambda_home"])
        form_away = float(calibration["form_lambda_away"])
    except (KeyError, TypeError, ValueError):
        return None, "form_share_missing", {"parity": parity}
    market_probabilities = calibration.get("market_probabilities")
    if not _valid_probabilities(market_probabilities):
        return None, "market_probabilities_missing_from_frozen_snapshot", {"parity": parity}
    form_total = max(1.2, min(4.2, form_home + form_away))
    market_total = calibration.get("market_total_line_median")
    target_total = float(market_total) if market_total is not None else form_total
    market_share = float(_market_share(target_total, market_probabilities))
    form_share = max(0.15, min(0.85, form_home / max(form_home + form_away, 0.01)))
    total = float(stored_home) + float(stored_away)
    rho = float(champion_prediction.get("rho") if champion_prediction.get("rho") is not None else replay_model.get("rho") or 0.0)
    candidate_parameters = {
        "lambda_home": total * market_share,
        "lambda_away": total * (1.0 - market_share),
        "rho": rho,
    }
    matrix = dixon_coles_score_matrix(candidate_parameters)
    calibration_state = _calibration_state(model_input)
    calibration_artifact = calibration_state.get("artifact") or {}
    calibration_strength = calibration_state.get("strength", 0.0)
    if calibration_state.get("dispersion_approved"):
        tail_weight = float((calibration_artifact.get("dispersion") or {}).get("tail_mixture_weight") or 0) * calibration_strength
        matrix = _mix_dispersion(matrix, total, market_share, tail_weight)
    if calibration_state.get("direction_approved"):
        matrix = _reweight_outcomes(
            matrix,
            (calibration_artifact.get("direction") or {}).get("logit_offsets") or {},
            calibration_strength,
        )
    probabilities = _outcomes(matrix)
    score_rows = _score_rows(matrix)
    if not score_rows or not _valid_probabilities(probabilities):
        return None, "candidate_matrix_unavailable", {"parity": parity}
    candidate = {
        "model": MARKET_DIRECTION_SHADOW_PREDICTOR_NAME,
        "version": MARKET_DIRECTION_SHADOW_CANDIDATE_ID,
        "status": "frozen",
        "prediction_variant": "prospective_shadow",
        "probabilities": {key: float(probabilities[key]) for key in ("home", "draw", "away")},
        "lambda_home": candidate_parameters["lambda_home"],
        "lambda_away": candidate_parameters["lambda_away"],
        "rho": rho,
        "expected_goals": total,
        "score_matrix": score_rows,
        "score_matrix_complete": True,
        "score_probabilities": score_rows,
        "score_top1": score_rows[0]["score"],
        "score_top3": [row["score"] for row in score_rows[:3]],
        "raw_score_top1": score_rows[0]["score"],
        "raw_score_top3": [row["score"] for row in score_rows[:3]],
        "form_share": form_share,
        "market_share": market_share,
        "target_total": target_total,
        "market_probabilities": {key: float(market_probabilities[key]) for key in ("home", "draw", "away")},
        "changed_variables": ["market_direction_fusion"],
        "calibration_locked": {
            "direction_applied": bool(calibration_state.get("direction_approved")),
            "dispersion_applied": bool(calibration_state.get("dispersion_approved")),
            "strength": calibration_strength,
        },
    }
    return candidate, None, {
        "parity": parity,
        "stored_raw_score_top1": stored_raw_top1,
        "replay_raw_score_top1": replay_raw_top1,
        "form_share": form_share,
        "market_share": market_share,
    }


def _shadow_metadata(
    comparison: dict[str, Any],
    champion_prediction: dict[str, Any],
    *,
    shadow_created_at: str,
    status: str,
    failure_reason: str | None,
    candidate: dict[str, Any] | None,
    replay_details: dict[str, Any] | None,
) -> dict[str, Any]:
    prediction_id = str(champion_prediction.get("prediction_id") or "")
    comparison["comparison_id"] = comparison_id_for(
        str(comparison.get("match_key") or ""),
        str(comparison.get("snapshot_id") or ""),
        MARKET_DIRECTION_SHADOW_CONTRACT_VERSION,
    )
    comparison["benchmark_contract_version"] = MARKET_DIRECTION_SHADOW_CONTRACT_VERSION
    comparison["prospective_origin"] = "prospective_shadow"
    comparison["shadow_scope"] = "prospective_shadow"
    comparison["candidate_id"] = MARKET_DIRECTION_SHADOW_CANDIDATE_ID
    comparison["candidate_version"] = MARKET_DIRECTION_SHADOW_CANDIDATE_ID
    comparison["shadow_status"] = status
    comparison["shadow_created_at"] = shadow_created_at
    comparison["shadow_failure_reason"] = failure_reason
    comparison["changed_variables"] = ["market_direction_fusion"]
    comparison["challenger_declaration"] = {
        "changed_variables": ["market_direction_fusion"],
        "expected_improvement_metrics": ["brier_score_1x2", "log_loss_1x2", "1x2_top1", "macro_ece"],
        "must_not_regress_metrics": ["total_mae", "total_goals_nll", "exact_score_top1", "exact_score_top3"],
        "known_derived_risks": ["market_overreaction", "directional_calibration_drift", "exact_score_distribution_shift"],
        "freeze_on_failure_condition": "any replay parity failure, snapshot mismatch, missing market direction, or material probability-quality regression",
        "scope": "retrospective_qualified_then_prospective_shadow_only",
        "promotion": "forbidden_without_separate_governance_review",
    }
    comparison["product_role"] = "PROSPECTIVE_SHADOW"
    comparison["prospective_shadow"] = True
    comparison["user_visible"] = False
    comparison["formal_eligible"] = False
    comparison["promotion_eligible"] = False
    comparison["excluded_from_formal_metrics"] = True
    comparison["primary_benchmark_eligible"] = False
    comparison["cohort"] = "shadow"
    comparison["source_champion_prediction_id"] = prediction_id
    comparison["source_champion_prediction_ref"] = f"data/model_governance/predictions/{prediction_id}.json"
    comparison["source_champion_prediction_sha256"] = champion_prediction.get("prediction_sha256")
    comparison["model_input_snapshot_ref"] = champion_prediction.get("model_input_snapshot_ref")
    comparison["canonical_model_input_sha256"] = champion_prediction.get("canonical_model_input_sha256")
    comparison["snapshot_hash"] = champion_prediction.get("canonical_model_input_sha256")
    comparison["kickoff_at"] = champion_prediction.get("kickoff_at")
    comparison["champion_total"] = float(champion_prediction.get("lambda_home") or 0) + float(champion_prediction.get("lambda_away") or 0)
    comparison["replay_details"] = replay_details or {}
    if candidate is not None:
        comparison.setdefault("predictors", {})[MARKET_DIRECTION_SHADOW_PREDICTOR_NAME] = candidate
        comparison["shadow_candidate"] = candidate
        comparison["market_direction_fusion_evaluable"] = True
        comparison["shadow_challenger"] = {
            "candidate_id": MARKET_DIRECTION_SHADOW_CANDIDATE_ID,
            "version": MARKET_DIRECTION_SHADOW_CANDIDATE_ID,
            "lambda_home": candidate["lambda_home"],
            "lambda_away": candidate["lambda_away"],
            "total": candidate["expected_goals"],
            "probabilities": candidate["probabilities"],
            "raw_score_top1": candidate["raw_score_top1"],
            "raw_score_top3": candidate["raw_score_top3"],
        }
    else:
        comparison["market_direction_fusion_evaluable"] = False
        comparison["shadow_candidate"] = None
        comparison["shadow_challenger"] = None
    if status != "complete":
        comparison["comparison_status"] = "shadow_failed"
        comparison["status_reason"] = failure_reason
        comparison["excluded_from_formal_metrics"] = True
        comparison.pop("benchmark_error", None)
    return comparison


def run_market_direction_shadow_for_frozen_prediction(
    champion_prediction: dict[str, Any],
    *,
    shadow_created_at: datetime | str,
    snapshot_root: Path = DEFAULT_INPUT_SNAPSHOT_ROOT,
    prediction_root: Path = DEFAULT_PREDICTION_ROOT,
    repository_root: Path = ROOT,
) -> dict[str, Any]:
    """Capture the fixed Challenger from the already-frozen Champion snapshot."""
    created = _parse_aware(shadow_created_at)
    if created is None:
        return {"status": "failed", "reason": "shadow_created_at_not_timezone_aware"}
    snapshot = build_benchmark_snapshot_from_frozen_prediction(
        champion_prediction,
        snapshot_root=snapshot_root,
        repository_root=repository_root,
    )
    if snapshot.get("benchmark_snapshot_status") != "valid":
        return {"status": "failed", "reason": snapshot.get("status_reason") or "immutable_snapshot_invalid"}
    kickoff = _parse_aware(champion_prediction.get("kickoff_at"))
    if kickoff is None or not created < kickoff:
        return {"status": "failed", "reason": "shadow_not_strictly_prematch", "snapshot": snapshot}
    comparison_id = comparison_id_for(
        str(snapshot.get("match_key") or ""),
        str(snapshot.get("snapshot_id") or ""),
        MARKET_DIRECTION_SHADOW_CONTRACT_VERSION,
    )
    existing = load_frozen_comparison(comparison_id, Path(prediction_root))
    if existing is not None:
        same_source = (
            existing.get("source_champion_prediction_id") == champion_prediction.get("prediction_id")
            and existing.get("canonical_model_input_sha256") == champion_prediction.get("canonical_model_input_sha256")
            and existing.get("candidate_id") == MARKET_DIRECTION_SHADOW_CANDIDATE_ID
        )
        if not same_source:
            return {"status": "failed", "reason": "shadow_existing_content_conflict", "comparison_id": comparison_id}
        return {"status": "existing", "comparison_id": comparison_id, "comparison": existing}
    candidate, failure_reason, replay_details = _market_direction_candidate(champion_prediction, snapshot)
    comparison = build_comparison(
        snapshot,
        champion_prediction,
        benchmark_scope="prospective",
        prospective_origin="production_new_freeze",
    )
    comparison = _shadow_metadata(
        comparison,
        champion_prediction,
        shadow_created_at=created.isoformat(),
        status="complete" if candidate is not None and failure_reason is None else "failed",
        failure_reason=failure_reason,
        candidate=candidate,
        replay_details=replay_details,
    )
    written = freeze_comparison(comparison, Path(prediction_root))
    return {
        "status": "created" if comparison.get("shadow_status") == "complete" else "failed",
        "comparison_id": comparison["comparison_id"],
        "comparison": written["document"],
        "prediction_path": str(written["path"]),
        "reason": failure_reason,
    }


def _actual_score_for_shadow(result: dict[str, Any]) -> tuple[int, int] | None:
    home = result.get("home_score_90m", result.get("home_goals"))
    away = result.get("away_score_90m", result.get("away_goals"))
    try:
        pair = (int(home), int(away))
    except (TypeError, ValueError):
        return None
    return pair if min(pair) >= 0 else None


def settle_market_direction_shadow_for_result(
    champion_prediction: dict[str, Any],
    verified_result: dict[str, Any],
    *,
    prediction_root: Path = DEFAULT_PREDICTION_ROOT,
    settlement_root: Path | None = None,
    settled_at: str | None = None,
) -> dict[str, Any]:
    """Settle the immutable shadow comparison; never writes the formal ledger."""
    snapshot_meta = champion_prediction.get("input_snapshot") or champion_prediction.get("snapshot_identity") or {}
    snapshot_id = snapshot_meta.get("snapshot_id") or champion_prediction.get("snapshot_id")
    comparison_id = comparison_id_for(
        str(champion_prediction.get("match_key") or ""),
        str(snapshot_id or ""),
        MARKET_DIRECTION_SHADOW_CONTRACT_VERSION,
    )
    comparison = load_frozen_comparison(comparison_id, Path(prediction_root))
    if comparison is None:
        return {"status": "no_op", "reason": "shadow_comparison_not_found", "comparison_id": comparison_id}
    if comparison.get("shadow_status") != "complete":
        return {"status": "no_op", "reason": "shadow_not_evaluable", "comparison_id": comparison_id}
    if (
        comparison.get("match_key") != champion_prediction.get("match_key")
        or comparison.get("source_champion_prediction_id") != champion_prediction.get("prediction_id")
        or comparison.get("canonical_model_input_sha256") != champion_prediction.get("canonical_model_input_sha256")
    ):
        return {"status": "no_op", "reason": "shadow_identity_mismatch", "comparison_id": comparison_id}
    score = _actual_score_for_shadow(verified_result)
    if score is None:
        return {"status": "no_op", "reason": "shadow_result_invalid", "comparison_id": comparison_id}
    from baseline_settlement import freeze_settlement, settle_comparison

    actual = {"home_goals": score[0], "away_goals": score[1]}
    settlement = settle_comparison(comparison, actual, settled_at=settled_at)
    target_root = Path(settlement_root) if settlement_root is not None else ROOT / "data" / "model_benchmarks" / "settlements"
    written = freeze_settlement(settlement, target_root)
    return {
        "status": written["status"],
        "comparison_id": comparison_id,
        "settlement_path": str(written["path"]),
        "settlement": written["settlement"],
    }


def run_benchmark_for_frozen_prediction(
    champion_prediction: dict[str, Any],
    *,
    benchmark_scope: str = "historical_exploratory",
    production_new_freeze: bool = False,
    checkpoint_metadata: dict[str, Any] | None = None,
    snapshot_root: Path = DEFAULT_INPUT_SNAPSHOT_ROOT,
    prediction_root: Path = DEFAULT_PREDICTION_ROOT,
    repository_root: Path = ROOT,
    synthetic: bool = False,
) -> dict[str, Any]:
    """Build one benchmark from an explicitly scoped frozen prediction.

    Historical/manual calls default to ``historical_exploratory``.  Only the
    production freeze hook may opt into formal prospective scope by explicitly
    marking a newly created frozen prediction.
    """
    if benchmark_scope not in {"prospective", "historical_exploratory"}:
        raise ValueError("benchmark_scope must be prospective or historical_exploratory")
    if production_new_freeze:
        if benchmark_scope != "prospective":
            raise ValueError("production_new_freeze requires prospective scope")
        prospective_origin = "production_new_freeze"
    else:
        benchmark_scope = "historical_exploratory"
        prospective_origin = "historical_exploratory"
    snapshot = build_benchmark_snapshot_from_frozen_prediction(
        champion_prediction,
        checkpoint_metadata=checkpoint_metadata,
        snapshot_root=snapshot_root,
        repository_root=repository_root,
    )
    if snapshot["benchmark_snapshot_status"] != "valid":
        return {"benchmark_status": "invalid", "benchmark_snapshot": snapshot}
    if synthetic:
        # Test-only boundary: production snapshots are always non-synthetic;
        # this explicit flag prevents smoke data from entering formal metrics.
        snapshot["synthetic"] = True
        snapshot["excluded_from_formal_metrics"] = True
    comparison = build_comparison(
        snapshot,
        champion_prediction,
        benchmark_scope=benchmark_scope,
        prospective_origin=prospective_origin,
    )
    if comparison["comparison_status"] != "complete":
        return {
            "benchmark_status": comparison["comparison_status"],
            "benchmark_snapshot": snapshot,
            "comparison": comparison,
        }
    written = freeze_comparison(comparison, Path(prediction_root))
    return {
        "benchmark_status": written["status"],
        "benchmark_snapshot": snapshot,
        "comparison": comparison,
        "prediction_path": str(written["path"]),
    }


def _parse_result_90m(value: Any) -> tuple[int, int] | None:
    text = str(value or "")
    if "-" not in text:
        return None
    home, away = text.split("-", 1)
    try:
        parsed = (int(home), int(away))
    except ValueError:
        return None
    return parsed if min(parsed) >= 0 else None


def settle_benchmark_for_verified_result(
    report: dict[str, Any],
    verified_result: dict[str, Any],
    *,
    prediction_root: Path = DEFAULT_PREDICTION_ROOT,
    settlement_root: Path = DEFAULT_SETTLEMENT_ROOT,
) -> dict[str, Any]:
    """Settle an existing comparison from a verified regulation-time result."""
    governance = report.get("model_governance") if isinstance(report, dict) else None
    governance = governance if isinstance(governance, dict) else {}
    comparison_id = str(governance.get("benchmark_comparison_id") or "")
    if not comparison_id:
        return {"status": "no_op", "reason": "benchmark_comparison_missing"}
    comparison = load_frozen_comparison(comparison_id, Path(prediction_root))
    if comparison is None:
        return {"status": "no_op", "reason": "benchmark_comparison_not_found", "comparison_id": comparison_id}
    if not isinstance(verified_result, dict) or verified_result.get("scope") != "regulation_90m_plus_stoppage":
        return {"status": "no_op", "reason": "non_regulation_result_scope", "comparison_id": comparison_id}
    score = _parse_result_90m(verified_result.get("result_90m"))
    if score is None:
        return {"status": "no_op", "reason": "invalid_result_90m", "comparison_id": comparison_id}
    actual = {
        "home_goals": score[0],
        "away_goals": score[1],
        "regulation_minutes": 90,
        "synthetic": bool(verified_result.get("synthetic")),
    }
    settlement = settle_comparison(comparison, actual, settled_at=verified_result.get("verified_at"))
    written = freeze_settlement(settlement, Path(settlement_root))
    return {
        "status": written["status"],
        "reason": None,
        "comparison_id": comparison_id,
        "settlement": written["settlement"],
        "settlement_path": str(written["path"]),
    }
