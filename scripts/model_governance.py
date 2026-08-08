#!/usr/bin/env python3
"""Auditable Champion/Challenger governance without changing model math."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from prediction_quality import classify_prediction


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "model_governance.json"
DEFAULT_RECORD_ROOT = ROOT / "data" / "model_governance" / "predictions"
REQUIRED_RECORD_FIELDS = (
    "prediction_id", "match_key", "created_at", "kickoff_at", "source_cutoff_at",
    "odds_snapshot_at", "repository_commit_sha", "model_role", "model_core_version",
    "model_family", "release_version", "feature_version", "data_pipeline_version",
    "report_schema_version", "prompt_version", "data_grade", "formal_eligible",
    "missing_critical_fields", "manual_override", "input_sha256", "prediction_sha256",
    "probabilities", "lambda_home", "lambda_away", "score_top1", "score_top3",
    "score_top5",
)
POSTMATCH_FIELDS = {
    "result", "settlement", "postmatch_evidence", "actual_score", "actual_outcome",
    "verified_at", "reviewed_at", "score_90m",
}
CORE_FILES = (
    "scripts/automatic_model_core.py",
    "scripts/model_governance.py",
    "scripts/risk_engine.py",
    "scripts/market_contracts.py",
    "scripts/deepseek_auto_analysis.py",
    "scripts/fetch_football_data.py",
    "scripts/prematch_fundamentals.py",
    "scripts/checkpoint_features.py",
    "scripts/prediction_quality.py",
    "scripts/generate_analysis_report.py",
    "data/model_calibration/latest.json",
    "config/model_governance.json",
    "schemas/analysis_report.schema.json",
    "schemas/postmatch_review.schema.json",
)


class PredictionConflictError(RuntimeError):
    """Raised when an immutable prediction id is reused with other content."""


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_value(value: Any) -> str:
    return _sha256_bytes(canonical_json(value).encode("utf-8"))


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def resolve_commit_sha(root: Path = ROOT, environ: dict[str, str] | None = None) -> str | None:
    env = environ or os.environ
    for name in ("GITHUB_SHA", "CI_COMMIT_SHA", "GIT_COMMIT_SHA", "COMMIT_SHA"):
        value = str(env.get(name) or "").strip()
        if value:
            return value
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=root, text=True, capture_output=True, check=True
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    value = result.stdout.strip()
    return value or None


def load_config(path: Path = DEFAULT_CONFIG) -> dict[str, Any]:
    value = _load_json(path)
    if not isinstance(value, dict):
        raise ValueError("model governance config must be an object")
    required = ("champion", "challengers", "versions", "quality_policy", "promotion_gates", "correction_policy")
    missing = [key for key in required if key not in value]
    if missing:
        raise ValueError(f"model governance config missing: {', '.join(missing)}")
    if not isinstance(value["challengers"], list) or value["challengers"]:
        raise ValueError("Phase 0 requires an empty challenger list")
    champion = value["champion"]
    versions = value["versions"]
    if not isinstance(champion, dict) or not isinstance(versions, dict):
        raise ValueError("champion and versions must be objects")
    from automatic_model_core import MODEL_FAMILY
    from deepseek_auto_analysis import MODEL_VERSION
    if champion.get("model_core_version") != MODEL_FAMILY:
        raise ValueError("configured Champion does not match automatic_model_core.MODEL_FAMILY")
    if champion.get("model_family") != MODEL_FAMILY:
        raise ValueError("configured model family does not match automatic_model_core.MODEL_FAMILY")
    if champion.get("release_version") != MODEL_VERSION:
        raise ValueError("configured release version does not match deepseek_auto_analysis.MODEL_VERSION")
    for key in ("feature_version", "data_pipeline_version", "report_schema_version", "postmatch_schema_version", "prompt_version"):
        if not str(versions.get(key) or "").strip():
            raise ValueError(f"configured version is empty: {key}")
    return value


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def hash_files(paths: list[str | Path] | tuple[str | Path, ...], root: Path = ROOT) -> dict[str, Any]:
    files: dict[str, str | None] = {}
    for value in paths:
        path = Path(value)
        target = path if path.is_absolute() else root / path
        try:
            key = target.relative_to(root).as_posix()
        except ValueError:
            key = path.as_posix()
        files[key] = sha256_file(target) if target.is_file() else None
    return {"algorithm": "sha256", "files": files}


def _number(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _match_key(payload: dict[str, Any]) -> str:
    match = payload.get("match") or {}
    for key in ("canonical_match_id", "match_id", "shuju_id"):
        value = match.get(key)
        if value not in (None, ""):
            return str(value)
    return "|".join(str(match.get(key) or "").strip().casefold() for key in ("home", "away", "kickoff_local"))


def _grade(payload: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    decisions = payload.get("decisions") or {}
    quality = payload.get("data_quality") or {}
    value = str(decisions.get("data_grade") or quality.get("data_grade") or "").strip().upper()
    classification = classify_prediction(payload)
    if value not in {"A", "B", "C", "D"}:
        value = str(classification.get("data_grade") or "D").upper()
    return value, classification


def _model_role(payload: dict[str, Any], config: dict[str, Any]) -> str:
    model = payload.get("model") or {}
    method = str(model.get("method") or "").strip()
    release_version = str((payload.get("report") or {}).get("model_version") or "").strip()
    champion = config["champion"]
    if method == champion.get("model_core_version") and release_version == champion.get("release_version"):
        return "champion"
    for challenger in config.get("challengers") or []:
        if isinstance(challenger, dict) and method in {challenger.get("model_core_version"), challenger.get("model_family")}:
            return "challenger"
    return "legacy"


def _first_checkpoint(payload: dict[str, Any]) -> str | None:
    report = payload.get("report") or {}
    checkpoint = report.get("market_checkpoint") or {}
    for key in ("source_cutoff_at", "snapshot_timestamp"):
        value = report.get(key)
        if value:
            return str(value)
    value = checkpoint.get("captured_at")
    return str(value) if value else None


def _score_values(model: dict[str, Any], limit: int) -> list[str]:
    values = []
    for row in model.get("score_probabilities") or []:
        if isinstance(row, dict) and row.get("score") not in (None, ""):
            values.append(str(row["score"]))
        if len(values) >= limit:
            break
    return values


def _real_executable_odds(payload: dict[str, Any]) -> bool:
    for candidate in (payload.get("betting") or {}).get("candidates") or []:
        if (
            isinstance(candidate, dict)
            and candidate.get("price_executable") is True
            and _number(candidate.get("odds")) is not None
        ):
            return True
    return False


def _without_prediction_hash(record: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in record.items() if key != "prediction_sha256"}


def _nested_postmatch_fields(value: Any) -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            if key in POSTMATCH_FIELDS:
                found.append(str(key))
            found.extend(_nested_postmatch_fields(child))
    elif isinstance(value, list):
        for child in value:
            found.extend(_nested_postmatch_fields(child))
    return list(dict.fromkeys(found))


def build_prediction_record(
    payload: dict[str, Any],
    *,
    config: dict[str, Any] | None = None,
    repository_root: Path = ROOT,
    input_payload: Any = None,
    commit_sha: str | None = None,
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("prediction payload must be an object")
    forbidden = sorted(field for field in POSTMATCH_FIELDS if field in payload)
    if forbidden:
        raise ValueError("postmatch fields are not allowed in a frozen prediction: " + ", ".join(forbidden))
    config = config or load_config()
    report = payload.get("report") or {}
    match = payload.get("match") or {}
    model = payload.get("model") or {}
    decisions = payload.get("decisions") or {}
    versions = config["versions"]
    grade, classification = _grade(payload)
    role = _model_role(payload, config)
    commit = commit_sha if commit_sha is not None else resolve_commit_sha(repository_root)
    probabilities = model.get("probabilities")
    probabilities = dict(probabilities) if isinstance(probabilities, dict) else None
    source_cutoff = _first_checkpoint(payload)
    kickoff = match.get("kickoff_local")
    odds_snapshot = report.get("odds_snapshot_at") or (report.get("market_checkpoint") or {}).get("captured_at")
    created_at = report.get("created_at") or report.get("analysis_timestamp")
    model_core_version = config["champion"].get("model_core_version") if role == "champion" else model.get("method")
    model_family = model.get("method")
    release_version = report.get("model_version")
    input_hash = _sha256_value(input_payload if input_payload is not None else {
        "manifest": report.get("data_run_id"),
        "match": match,
        "model": model,
        "market_checkpoint": report.get("market_checkpoint"),
    })
    quality_missing = list(classification.get("analysis_missing") or [])
    structural_missing = []
    if not isinstance(probabilities, dict) or any(
        _number(probabilities.get(key)) is None for key in ("home", "draw", "away")
    ):
        structural_missing.append("model.probabilities")
    for field, value in (
        ("created_at", created_at),
        ("kickoff_at", kickoff),
        ("source_cutoff_at", source_cutoff),
        ("odds_snapshot_at", odds_snapshot),
        ("repository_commit_sha", commit),
        ("model_core_version", model_core_version),
        ("model_family", model_family),
        ("release_version", release_version),
        ("feature_version", versions.get("feature_version")),
        ("data_pipeline_version", versions.get("data_pipeline_version")),
        ("report_schema_version", versions.get("report_schema_version")),
        ("postmatch_schema_version", versions.get("postmatch_schema_version")),
        ("prompt_version", (payload.get("automation") or {}).get("prompt_version") or versions.get("prompt_version")),
        ("lambda_home", model.get("lambda_home")),
        ("lambda_away", model.get("lambda_away")),
    ):
        if value in (None, ""):
            structural_missing.append(field)
    missing = list(dict.fromkeys(str(item) for item in [*quality_missing, *structural_missing]))
    primary = decisions.get("unique_primary_dimension")
    formal = (
        role == "champion"
        and grade in set(config["quality_policy"].get("formal_grades") or ["A", "B"])
        and bool(primary)
        and not structural_missing
    )
    scores = _score_values(model, 5)
    record = {
        "schema_version": "1.0",
        "prediction_id": "",
        "match_key": _match_key(payload),
        "created_at": created_at,
        "kickoff_at": kickoff,
        "source_cutoff_at": source_cutoff,
        "odds_snapshot_at": odds_snapshot,
        "repository_commit_sha": commit,
        "model_role": role,
        "model_core_version": model_core_version,
        "model_family": model_family,
        "release_version": release_version,
        "feature_version": versions.get("feature_version"),
        "data_pipeline_version": versions.get("data_pipeline_version"),
        "report_schema_version": versions.get("report_schema_version"),
        "postmatch_schema_version": versions.get("postmatch_schema_version"),
        "prompt_version": (payload.get("automation") or {}).get("prompt_version") or versions.get("prompt_version"),
        "data_grade": grade,
        "formal_eligible": formal,
        "prediction_status": "formal" if formal else "research_only",
        "missing_critical_fields": missing,
        "manual_override": payload.get("manual_override") if isinstance(payload.get("manual_override"), bool) else None,
        "input_sha256": input_hash,
        "prediction_sha256": None,
        "probabilities": probabilities,
        "lambda_home": model.get("lambda_home"),
        "lambda_away": model.get("lambda_away"),
        "rho": model.get("rho"),
        "score_top1": scores[0] if scores else None,
        "score_top3": scores[:3],
        "score_top5": scores[:5],
        "analysis_output": {"status": "available", "report_type": report.get("report_type")},
        "prediction_output": {
            "status": "formal" if formal else "research_only",
            "probabilities": probabilities,
            "lambda_home": model.get("lambda_home"),
            "lambda_away": model.get("lambda_away"),
            "score_matrix": list(model.get("score_probabilities") or []),
            "unique_score": decisions.get("unique_score"),
            "primary_dimension": primary,
        },
        "betting_reference_output": {
            "status": "evaluable" if _real_executable_odds(payload) else "not_evaluable",
            "reason": None if _real_executable_odds(payload) else "no_real_executable_odds",
            "roi": None,
            "clv": None,
        },
    }
    identity = {
        "match_key": record["match_key"],
        "model_core_version": record["model_core_version"],
        "source_cutoff_at": source_cutoff,
        "odds_snapshot_at": odds_snapshot,
        "input_sha256": input_hash,
    }
    record["prediction_id"] = "FBOS-PRED-" + _sha256_value(identity)[:24]
    record["prediction_sha256"] = _sha256_value(_without_prediction_hash(record))
    return record


def _validate_record(record: dict[str, Any]) -> None:
    missing = [key for key in REQUIRED_RECORD_FIELDS if key not in record]
    if missing:
        raise ValueError("frozen prediction missing fields: " + ", ".join(missing))
    forbidden = sorted(_nested_postmatch_fields(record))
    if forbidden:
        raise ValueError("postmatch fields are not allowed in a frozen prediction: " + ", ".join(forbidden))
    if record["prediction_sha256"] != _sha256_value(_without_prediction_hash(record)):
        raise ValueError("prediction_sha256 does not match frozen content")


def freeze_prediction(record: dict[str, Any], record_root: Path = DEFAULT_RECORD_ROOT) -> dict[str, Any]:
    _validate_record(record)
    record_root.mkdir(parents=True, exist_ok=True)
    target = record_root / f"{record['prediction_id']}.json"
    serialized = canonical_json(record)
    try:
        with target.open("x", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, indent=2) + "\n")
        return {"status": "created", "path": target, "record": record}
    except FileExistsError:
        try:
            existing = _load_json(target)
        except (OSError, json.JSONDecodeError) as error:
            raise PredictionConflictError(f"existing frozen prediction is unreadable: {target}") from error
        if canonical_json(existing) != serialized:
            raise PredictionConflictError(f"prediction id content conflict: {record['prediction_id']}")
        return {"status": "existing", "path": target, "record": existing}


def can_update_parameters(*, sample_count: int, match_count: int, config: dict[str, Any] | None = None) -> bool:
    config = config or load_config()
    minimum = int(config["correction_policy"].get("minimum_holdout_samples") or 50)
    return sample_count >= minimum and match_count > 1


def evaluate_promotion(comparison: dict[str, Any], config: dict[str, Any] | None = None) -> dict[str, Any]:
    config = config or load_config()
    gates = config["promotion_gates"]
    reasons: list[str] = []
    if int(comparison.get("sample_count") or 0) < int(gates.get("minimum_holdout_samples") or 50):
        reasons.append("minimum_holdout_samples")
    if gates.get("requires_same_match_same_snapshot") and comparison.get("same_snapshot") is not True:
        reasons.append("same_match_same_snapshot")
    if gates.get("requires_out_of_sample_validation") and comparison.get("out_of_sample") is not True:
        reasons.append("out_of_sample_validation")
    if gates.get("requires_reproducible_inputs") and comparison.get("reproducible_inputs") is not True:
        reasons.append("reproducible_inputs")
    for name in ("champion", "challenger"):
        if not isinstance(comparison.get(name), dict):
            reasons.append(f"{name}_comparison_missing")
    for name, gate_key in (("market_baseline", "requires_market_baseline"), ("simple_baseline", "requires_simple_baseline")):
        if gates.get(gate_key) and not isinstance(comparison.get(name), dict):
            reasons.append(f"{name}_comparison_missing")
    champion = comparison.get("champion") or {}
    challenger = comparison.get("challenger") or {}
    if gates.get("brier_must_improve") and _number(challenger.get("brier_score")) is not None and _number(champion.get("brier_score")) is not None:
        if challenger["brier_score"] >= champion["brier_score"]:
            reasons.append("brier_not_improved")
    if gates.get("log_loss_must_not_deteriorate") and _number(challenger.get("log_loss")) is not None and _number(champion.get("log_loss")) is not None:
        if challenger["log_loss"] > champion["log_loss"]:
            reasons.append("log_loss_deteriorated")
    if gates.get("automatic_promotion_forbidden"):
        reasons.append("automatic_promotion_forbidden")
    return {"eligible": not reasons, "reasons": list(dict.fromkeys(reasons)), "automatic_promotion": False}


def _iter_json(root: Path) -> list[tuple[Path, dict[str, Any]]]:
    rows = []
    if not root.exists():
        return rows
    for path in sorted(root.rglob("*.json")):
        try:
            value = _load_json(path)
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(value, dict):
            rows.append((path, value))
    return rows


def _report_is_prediction(payload: dict[str, Any]) -> bool:
    model = payload.get("model") or {}
    probabilities = model.get("probabilities")
    return bool(
        isinstance(probabilities, dict)
        and all(_number(probabilities.get(key)) is not None for key in ("home", "draw", "away"))
        and _number(model.get("lambda_home")) is not None
        and _number(model.get("lambda_away")) is not None
    )


def _review_hit(payload: dict[str, Any], key: str) -> bool | None:
    value = ((payload.get("settlement") or {}).get(key) or {}).get("hit")
    return value if isinstance(value, bool) else None


def _review_hit_metric(rows: list[dict[str, Any]], key: str) -> dict[str, Any] | None:
    values = [_review_hit(row, key) for row in rows]
    values = [value for value in values if value is not None]
    if not values:
        return None
    return {
        "settled": len(values),
        "hits": sum(values),
        "hit_rate": round(sum(values) / len(values), 6),
    }


def build_current_metrics(
    report_root: Path = ROOT / "data" / "analysis_reports",
    review_root: Path = ROOT / "data" / "postmatch_reviews",
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    config = config or load_config()
    champion = config["champion"]
    reports = [payload for _, payload in _iter_json(report_root) if _report_is_prediction(payload)]
    champion_rows = [
        payload for payload in reports
        if (payload.get("report") or {}).get("model_version") == champion.get("release_version")
        and (payload.get("model") or {}).get("method") == champion.get("model_family")
    ]
    formal_rows = []
    grades = Counter({grade: 0 for grade in ("A", "B", "C", "D")})
    for payload in champion_rows:
        grade, _ = _grade(payload)
        grades[grade] += 1
        if grade in {"A", "B"} and (payload.get("decisions") or {}).get("prediction_tier") == "formal":
            formal_rows.append(payload)
    review_rows = [
        payload for _, payload in _iter_json(review_root)
        if payload.get("model_version") == champion.get("release_version")
        and payload.get("model_family") == champion.get("model_family")
        and payload.get("data_grade") in {"A", "B"}
        and (payload.get("prediction_layer") or {}).get("formal_pick_eligible") is True
    ]
    reasons = {}
    if not review_rows:
        reasons["formal_metrics"] = "no settled Champion reviews with data grade A/B"
    reviews_with_prices = [row for row in review_rows if row.get("real_executable_price") is True]
    if not reviews_with_prices:
        reasons["roi"] = "no settled formal sample with a verified real executable price"
        reasons["clv"] = "no verified closing-price comparison"
        reasons["max_drawdown"] = "no verified executable-price equity curve"
    diagnostics = [row.get("model_diagnostics") or {} for row in review_rows]
    brier = [float(row["brier_score_1x2"]) for row in diagnostics if _number(row.get("brier_score_1x2")) is not None]
    log_loss = [float(row["log_loss_1x2"]) for row in diagnostics if _number(row.get("log_loss_1x2")) is not None]
    ranks = [int(row["actual_score_rank"]) for row in diagnostics if row.get("actual_score_rank") is not None]
    metrics = {
        "brier_score": round(sum(brier) / len(brier), 6) if brier else None,
        "log_loss": round(sum(log_loss) / len(log_loss), 6) if log_loss else None,
        "win_draw_loss": _review_hit_metric(review_rows, "model_1x2"),
        "over_under": _review_hit_metric(review_rows, "total_goals_mode"),
        "btts": _review_hit_metric(review_rows, "btts"),
        "score_top1": round(sum(rank <= 1 for rank in ranks) / len(ranks), 6) if ranks else None,
        "score_top3": round(sum(rank <= 3 for rank in ranks) / len(ranks), 6) if ranks else None,
        "score_top5": round(sum(rank <= 5 for rank in ranks) / len(ranks), 6) if ranks else None,
        "actual_score_mean_rank": round(sum(ranks) / len(ranks), 4) if ranks else None,
        "roi": None,
        "clv": None,
        "max_drawdown": None,
    }
    scope = {
        "all_records": len(reports),
        "all_frozen_predictions": len(reports),
        "champion_frozen_predictions": len(champion_rows),
        "deduplicated_matches": len({_match_key(payload) for payload in champion_rows}),
        "formal_grades": ["A", "B"],
        "formal_samples": len(formal_rows),
        "formal_settled_samples": len(review_rows),
        "legacy_records_excluded": len(reports) - len(champion_rows),
    }
    missing_reasons = {
        "brier_score": reasons.get("formal_metrics"),
        "log_loss": reasons.get("formal_metrics"),
        "win_draw_loss": reasons.get("formal_metrics"),
        "over_under": reasons.get("formal_metrics"),
        "btts": reasons.get("formal_metrics"),
        "score_top1": reasons.get("formal_metrics"),
        "score_top3": reasons.get("formal_metrics"),
        "score_top5": reasons.get("formal_metrics"),
        "actual_score_mean_rank": reasons.get("formal_metrics"),
        "roi": reasons.get("roi"),
        "clv": reasons.get("clv"),
        "max_drawdown": reasons.get("max_drawdown"),
    }
    return {
        "schema_version": "1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "frozen_prediction_count": len(reports),
        "champion_frozen_prediction_count": len(champion_rows),
        "deduplicated_match_count": len({_match_key(payload) for payload in champion_rows}),
        "formal_sample_count": len(formal_rows),
        "scope": scope,
        "quality_distribution": dict(sorted(grades.items())),
        "metrics": metrics,
        "missing_reasons": missing_reasons,
        "policy": {
            "formal_grades": ["A", "B"],
            "legacy_separated": True,
            "research_grades": ["C", "D"],
        },
    }


def build_baseline_manifest(
    *,
    baseline_commit_sha: str | None,
    branch: str,
    config: dict[str, Any] | None = None,
    report_root: Path = ROOT / "data" / "analysis_reports",
    review_root: Path = ROOT / "data" / "postmatch_reviews",
) -> dict[str, Any]:
    config = config or load_config()
    metrics = build_current_metrics(report_root, review_root, config)
    return {
        "schema_version": "1.0",
        "baseline_id": "football-baseline-v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "repository": "gemini077/football-betting-oneshot",
        "branch": branch,
        "commit_sha": baseline_commit_sha,
        "working_tree_clean": True,
        "champion": {**config["champion"], "status": "frozen_baseline"},
        "versions": config["versions"],
        "evaluation_scope": metrics["scope"],
        "production_math_changed": False,
    }


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def export_baseline(output_root: Path, *, baseline_commit_sha: str | None, branch: str) -> dict[str, Any]:
    config = load_config()
    manifest = build_baseline_manifest(baseline_commit_sha=baseline_commit_sha, branch=branch, config=config)
    metrics = build_current_metrics(config=config)
    write_json(output_root / "manifest.json", manifest)
    write_json(output_root / "current-metrics.json", metrics)
    write_json(output_root / "file-hashes.json", hash_files(CORE_FILES))
    return {"manifest": manifest, "metrics": metrics}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--export-baseline", type=Path)
    parser.add_argument("--baseline-commit-sha")
    parser.add_argument("--branch", default="")
    args = parser.parse_args()
    if not args.export_baseline:
        parser.error("--export-baseline is required")
    result = export_baseline(
        args.export_baseline,
        baseline_commit_sha=args.baseline_commit_sha or resolve_commit_sha(),
        branch=args.branch or "unknown",
    )
    print(json.dumps({"manifest": result["manifest"], "metrics": result["metrics"]["scope"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
