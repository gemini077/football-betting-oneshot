#!/usr/bin/env python3
"""Production bridge from the frozen Phase 0 ledger to the Phase 1 benchmark."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
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
