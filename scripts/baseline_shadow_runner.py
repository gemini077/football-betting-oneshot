#!/usr/bin/env python3
"""Build and freeze prospective same-snapshot benchmark comparisons."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
from typing import Any

from model_baselines import (
    SNAPSHOT_FIELDS,
    build_market_reference,
    build_simple_poisson_baseline,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PREDICTION_ROOT = ROOT / "data" / "model_benchmarks" / "predictions"
BENCHMARK_CONTRACT_VERSION = "benchmark_comparison.v1"
PRIMARY_CHECKPOINT = "T-30M"
SECONDARY_CHECKPOINTS = {"T-8H", "T-6H", "T-4H", "T-2H", "T-90M", "T-60M", "T-10M"}


class BenchmarkConflictError(RuntimeError):
    """Raised when an immutable benchmark id is reused with other content."""


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def comparison_id_for(match_key: str, snapshot_id: str, benchmark_contract_version: str = BENCHMARK_CONTRACT_VERSION) -> str:
    material = f"{match_key}|{snapshot_id}|{benchmark_contract_version}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _snapshot_identity(snapshot: dict[str, Any]) -> dict[str, Any]:
    return {field: snapshot.get(field) for field in SNAPSHOT_FIELDS}


def _metadata_complete(identity: dict[str, Any]) -> bool:
    return all(identity.get(field) not in (None, "") for field in SNAPSHOT_FIELDS)


def _champion_identity(record: dict[str, Any]) -> dict[str, Any]:
    input_snapshot = record.get("input_snapshot") if isinstance(record.get("input_snapshot"), dict) else {}
    snapshot_identity = record.get("snapshot_identity") if isinstance(record.get("snapshot_identity"), dict) else {}
    match_identity = record.get("match_identity") if isinstance(record.get("match_identity"), dict) else {}
    return {
        "match_key": record.get("match_key") or match_identity.get("match_key"),
        "snapshot_id": (
            record.get("snapshot_id")
            or snapshot_identity.get("snapshot_id")
            or input_snapshot.get("snapshot_id")
        ),
        "canonical_model_input_sha256": (
            record.get("canonical_model_input_sha256")
            or snapshot_identity.get("canonical_model_input_sha256")
            or input_snapshot.get("canonical_model_input_sha256")
        ),
        "source_cutoff_at": (
            record.get("source_cutoff_at")
            or snapshot_identity.get("source_cutoff_at")
            or input_snapshot.get("source_cutoff_at")
        ),
        "market_snapshot_at": (
            record.get("market_snapshot_at")
            or snapshot_identity.get("market_snapshot_at")
            or input_snapshot.get("market_snapshot_at")
            or record.get("odds_snapshot_at")
        ),
        "checkpoint_stage": (
            record.get("checkpoint_stage")
            or snapshot_identity.get("checkpoint_stage")
            or input_snapshot.get("checkpoint_stage")
        ),
    }


def _frozen_champion_output(record: dict[str, Any]) -> tuple[dict[str, Any] | None, dict[str, Any] | None, str | None]:
    if not isinstance(record, dict):
        return None, None, "frozen_champion_missing"
    formal = (
        record.get("model_role") == "champion"
        and record.get("model_formal_eligible") is True
        and record.get("prediction_variant") == "model_only"
        and record.get("prediction_status") == "formal"
    )
    if not formal:
        return None, None, "frozen_champion_not_formal"
    required = ("prediction_id", "prediction_sha256", "model_run_fingerprint")
    if any(record.get(field) in (None, "") for field in required):
        return None, None, "frozen_champion_identity_missing"
    output = record.get("prediction_output") if isinstance(record.get("prediction_output"), dict) else {}
    probabilities = record.get("probabilities") or output.get("probabilities")
    if not isinstance(probabilities, dict):
        return None, None, "frozen_champion_probabilities_missing"
    score_matrix = record.get("score_matrix") or record.get("score_probabilities") or output.get("score_matrix")
    normalized = {
        "model": "champion",
        "version": record.get("model_core_version") or record.get("model_family"),
        "status": "frozen",
        "prediction_id": record["prediction_id"],
        "prediction_sha256": record["prediction_sha256"],
        "model_run_fingerprint": record["model_run_fingerprint"],
        "canonical_model_input_sha256": record.get("canonical_model_input_sha256"),
        "probabilities": deepcopy(probabilities),
        "lambda_home": record.get("lambda_home") or output.get("lambda_home"),
        "lambda_away": record.get("lambda_away") or output.get("lambda_away"),
        "rho": record.get("rho") if record.get("rho") is not None else output.get("rho"),
        "btts": deepcopy(record.get("btts") or output.get("btts")) if isinstance(record.get("btts") or output.get("btts"), dict) else None,
        "expected_goals": deepcopy(record.get("expected_goals") or output.get("expected_goals")) if isinstance(record.get("expected_goals") or output.get("expected_goals"), dict) else None,
        "score_matrix": deepcopy(score_matrix) if isinstance(score_matrix, list) else [],
        "market_read": False,
        "champion_read": True,
        "frozen": True,
    }
    reference = {
        "prediction_id": record["prediction_id"],
        "prediction_sha256": record["prediction_sha256"],
        "canonical_model_input_sha256": record.get("canonical_model_input_sha256"),
        "model_run_fingerprint": record["model_run_fingerprint"],
    }
    return normalized, reference, None


def primary_benchmark_eligibility(snapshot: dict[str, Any]) -> dict[str, Any]:
    stage = snapshot.get("checkpoint_stage")
    has_trusted_timestamps = bool(snapshot.get("source_cutoff_at") and snapshot.get("market_snapshot_at"))
    if stage == PRIMARY_CHECKPOINT and has_trusted_timestamps:
        return {"primary_benchmark_eligible": True, "cohort": "primary", "reason": None}
    if stage in SECONDARY_CHECKPOINTS:
        reason = "missing_trusted_snapshot_timestamps" if not has_trusted_timestamps else "checkpoint_is_secondary"
        return {"primary_benchmark_eligible": False, "cohort": "secondary", "reason": reason}
    return {
        "primary_benchmark_eligible": False,
        "cohort": "secondary",
        "reason": "checkpoint_not_registered",
    }


def build_comparison(
    snapshot: dict[str, Any],
    champion_prediction: dict[str, Any] | None,
    *,
    benchmark_scope: str = "prospective",
) -> dict[str, Any]:
    """Build one comparison without running or reconstructing the Champion."""
    if not isinstance(snapshot, dict):
        raise ValueError("snapshot must be an object")
    if benchmark_scope not in {"prospective", "historical_exploratory"}:
        raise ValueError("benchmark_scope must be prospective or historical_exploratory")
    historical_marker = bool(
        snapshot.get("historical") is True
        or bool(snapshot.get("historical_report"))
        or str(snapshot.get("source_scope") or "").casefold() in {"historical", "legacy"}
        or str(snapshot.get("benchmark_scope") or "").casefold() == "historical_exploratory"
    )
    if benchmark_scope == "prospective" and historical_marker:
        benchmark_scope = "historical_exploratory"

    identity = _snapshot_identity(snapshot)
    eligibility = primary_benchmark_eligibility(snapshot)
    market = build_market_reference(snapshot)
    simple = build_simple_poisson_baseline(snapshot)
    predictors: dict[str, dict[str, Any] | None] = {
        "market_reference": market,
        "simple_poisson": simple,
        "champion": None,
    }
    champion_reference = None
    status = "incomplete"
    status_reason = "frozen_champion_missing"
    same_snapshot: bool | None = None

    if champion_prediction is not None:
        champion_identity = _champion_identity(champion_prediction)
        if _metadata_complete(identity) and _metadata_complete(champion_identity):
            if champion_identity != identity:
                status = "invalid_snapshot_mismatch"
                status_reason = "frozen_champion_snapshot_mismatch"
                same_snapshot = False
            else:
                same_snapshot = True
        else:
            status_reason = "frozen_champion_snapshot_metadata_missing"
        champion, reference, error = _frozen_champion_output(champion_prediction)
        if error is not None:
            status_reason = error
        elif status != "invalid_snapshot_mismatch":
            predictors["champion"] = {**identity, **(champion or {})}
            champion_reference = reference
            if _metadata_complete(identity) and same_snapshot is True:
                status = "complete"
                status_reason = None

    if benchmark_scope == "historical_exploratory" and status != "invalid_snapshot_mismatch":
        status = "historical_exploratory"
        status_reason = "historical_scope_excluded_from_formal_metrics"

    synthetic = bool(snapshot.get("synthetic"))
    return {
        **identity,
        "comparison_id": comparison_id_for(
            str(identity.get("match_key") or ""),
            str(identity.get("snapshot_id") or ""),
            BENCHMARK_CONTRACT_VERSION,
        ),
        "benchmark_contract_version": BENCHMARK_CONTRACT_VERSION,
        "benchmark_scope": benchmark_scope,
        "prospective_only": benchmark_scope == "prospective",
        "comparison_status": status,
        "status_reason": status_reason,
        "same_snapshot": same_snapshot,
        "snapshot_consistent": same_snapshot is True,
        "primary_benchmark_eligible": eligibility["primary_benchmark_eligible"],
        "cohort": eligibility["cohort"],
        "primary_eligibility_reason": eligibility["reason"],
        "synthetic": synthetic,
        "excluded_from_formal_metrics": synthetic or benchmark_scope != "prospective",
        "champion_reference": champion_reference,
        "predictors": predictors,
        "market_reference": market,
        "simple_poisson": simple,
        "champion": predictors["champion"],
    }


def _freeze_json(document: dict[str, Any], root: Path, label: str) -> dict[str, Any]:
    comparison_id = str(document.get("comparison_id") or "")
    if not comparison_id:
        raise ValueError(f"{label} is missing comparison_id")
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    target = root / f"{comparison_id}.json"
    serialized = canonical_json(document)
    try:
        with target.open("x", encoding="utf-8") as handle:
            handle.write(json.dumps(document, ensure_ascii=False, indent=2) + "\n")
        return {"status": "created", "path": target, "document": deepcopy(document)}
    except FileExistsError:
        try:
            existing = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise BenchmarkConflictError(f"existing {label} is unreadable: {target}") from error
        if canonical_json(existing) != serialized:
            raise BenchmarkConflictError(f"{label} content conflict: {comparison_id}")
        return {"status": "existing", "path": target, "document": existing}


def freeze_comparison(comparison: dict[str, Any], prediction_root: Path = DEFAULT_PREDICTION_ROOT) -> dict[str, Any]:
    """Create a content-addressed prediction file; never overwrite it."""
    forbidden = {"actual_result", "settlement", "metrics", "settled_at"}
    polluted = sorted(key for key in forbidden if key in comparison)
    if polluted:
        raise ValueError("postmatch fields are not allowed in benchmark predictions: " + ", ".join(polluted))
    return _freeze_json(comparison, prediction_root, "benchmark prediction")


def load_frozen_comparison(comparison_id: str, prediction_root: Path = DEFAULT_PREDICTION_ROOT) -> dict[str, Any] | None:
    path = Path(prediction_root) / f"{comparison_id}.json"
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


run_shadow_benchmark = build_comparison


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON document must be an object: {path}")
    return value


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, required=True, help="one frozen prospective snapshot JSON")
    parser.add_argument("--champion", type=Path, required=True, help="one formal frozen Champion prediction JSON")
    parser.add_argument("--prediction-root", type=Path, default=DEFAULT_PREDICTION_ROOT)
    parser.add_argument("--scope", choices=("prospective", "historical_exploratory"), default="prospective")
    args = parser.parse_args()
    comparison = build_comparison(
        _load_json(args.snapshot),
        _load_json(args.champion),
        benchmark_scope=args.scope,
    )
    written = freeze_comparison(comparison, args.prediction_root)
    print(json.dumps({
        "comparison_id": comparison["comparison_id"],
        "comparison_status": comparison["comparison_status"],
        "benchmark_scope": comparison["benchmark_scope"],
        "prediction_path": str(written["path"]),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
