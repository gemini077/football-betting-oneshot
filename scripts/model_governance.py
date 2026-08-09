#!/usr/bin/env python3
"""Auditable Champion/Challenger governance without changing model math."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from prediction_quality import classify_prediction


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "model_governance.json"
DEFAULT_RECORD_ROOT = ROOT / "data" / "model_governance" / "predictions"
DEFAULT_INPUT_SNAPSHOT_ROOT = ROOT / "data" / "model_governance" / "input_snapshots"

REQUIRED_RECORD_FIELDS = (
    "prediction_id", "match_key", "created_at", "kickoff_at", "source_cutoff_at",
    "odds_snapshot_at", "repository_commit_sha", "model_role", "model_core_version",
    "model_family", "release_version", "feature_version", "data_pipeline_version",
    "report_schema_version", "postmatch_schema_version", "prompt_version", "data_grade",
    "formal_eligible", "model_formal_eligible", "prediction_variant", "prediction_status",
    "missing_critical_fields", "critical_missing_fields", "noncritical_missing_fields",
    "manual_override", "lineup_status", "input_sha256", "input_snapshot",
    "match_identity", "snapshot_identity", "model_run_identity", "model_run_fingerprint",
    "prediction_sha256", "probabilities", "lambda_home", "lambda_away", "score_top1",
    "score_top3", "score_top5",
)

POSTMATCH_FIELDS = {
    "result", "settlement", "postmatch_evidence", "actual_score", "actual_outcome",
    "verified_at", "reviewed_at", "score_90m",
}

# These lists are intentionally explicit.  The first list is the deterministic
# prediction source chain; the second list is the audit/recording chain.
MODEL_SOURCE_FILES = (
    "scripts/automatic_model_core.py",
    "scripts/risk_engine.py",
    "scripts/market_contracts.py",
    "scripts/fetch_football_data.py",
    "scripts/prematch_fundamentals.py",
    "scripts/checkpoint_features.py",
    "scripts/prediction_quality.py",
    "scripts/deepseek_auto_analysis.py",
    "data/model_calibration/latest.json",
)
GOVERNANCE_FILES = (
    "scripts/model_governance.py",
    "scripts/generate_analysis_report.py",
    "scripts/automatic_postmatch_review.py",
    "config/model_governance.json",
    "schemas/analysis_report.schema.json",
    "schemas/postmatch_review.schema.json",
)
CORE_FILES = MODEL_SOURCE_FILES + GOVERNANCE_FILES

_LINEUP_STATUSES = {
    "unavailable_by_time", "projected", "confirmed", "missing_unexpectedly"
}
_NARRATIVE_KEYS = {
    "analysis", "narrative", "explanation", "llm_response", "deepseek_response",
    "deepseek_narrative",
}


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


def _git_value(root: Path, *args: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", *args], cwd=root, text=True, capture_output=True, check=True
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    value = result.stdout.strip()
    return value or None


def resolve_commit_sha(root: Path = ROOT, environ: dict[str, str] | None = None) -> str | None:
    env = environ or os.environ
    for name in ("GITHUB_SHA", "CI_COMMIT_SHA", "GIT_COMMIT_SHA", "COMMIT_SHA"):
        value = str(env.get(name) or "").strip()
        if value:
            return value
    return _git_value(root, "rev-parse", "HEAD")


def resolve_origin_main_sha(root: Path = ROOT) -> str | None:
    return _git_value(root, "rev-parse", "origin/main")


def working_tree_clean(root: Path = ROOT) -> bool:
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"], cwd=root, text=True, capture_output=True, check=True
        )
    except (OSError, subprocess.CalledProcessError):
        return False
    return result.stdout == ""


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


def _model_role_info(payload: dict[str, Any], config: dict[str, Any]) -> tuple[str, str | None]:
    model = payload.get("model") or {}
    method = str(model.get("method") or "").strip()
    release_version = str((payload.get("report") or {}).get("model_version") or "").strip()
    champion = config["champion"]
    if method == champion.get("model_core_version") and release_version == champion.get("release_version"):
        return "champion", None
    for challenger in config.get("challengers") or []:
        if not isinstance(challenger, dict):
            continue
        if method in {challenger.get("model_core_version"), challenger.get("model_family")}:
            return "challenger", str(challenger.get("id") or challenger.get("challenger_id") or method)
    return "legacy", None


def _model_role(payload: dict[str, Any], config: dict[str, Any]) -> str:
    return _model_role_info(payload, config)[0]


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
    return {
        key: value for key, value in record.items()
        if key not in {"prediction_sha256", "_input_snapshot_content"}
        and not key.startswith("_")
    }


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


def _strip_narrative(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _strip_narrative(child)
            for key, child in value.items()
            if str(key).casefold() not in _NARRATIVE_KEYS
        }
    if isinstance(value, list):
        return [_strip_narrative(child) for child in value]
    return value


def _deterministic_input(payload: dict[str, Any], input_payload: Any) -> Any:
    if input_payload is not None:
        return _strip_narrative(input_payload)
    report = payload.get("report") or {}
    return _strip_narrative({
        "manifest": report.get("data_run_id"),
        "match": payload.get("match") or {},
        "market_checkpoint": report.get("market_checkpoint") or {},
    })


def _collect_source_refs(value: Any, key: str = "") -> list[str]:
    refs: list[str] = []
    if isinstance(value, dict):
        for child_key, child in value.items():
            lowered = str(child_key).casefold()
            if lowered in {"file", "path", "source_path", "snapshot_ref", "source_ref"} and isinstance(child, str):
                refs.append(child)
            refs.extend(_collect_source_refs(child, lowered))
    elif isinstance(value, list):
        for child in value:
            refs.extend(_collect_source_refs(child, key))
    return list(dict.fromkeys(refs))


def _source_hashes(source_refs: list[str], root: Path) -> dict[str, str | None]:
    hashes: dict[str, str | None] = {}
    for ref in source_refs:
        if ref.startswith(("http://", "https://")):
            hashes[ref] = None
            continue
        candidate = Path(ref)
        if not candidate.is_absolute():
            candidate = root / candidate
        hashes[ref] = sha256_file(candidate) if candidate.is_file() else None
    return hashes


def _manifest_ref(input_payload: Any) -> str | None:
    if not isinstance(input_payload, dict):
        return None
    manifest = input_payload.get("manifest")
    if isinstance(manifest, str):
        return manifest
    if isinstance(manifest, dict):
        for key in ("path", "manifest_ref", "data_run_id", "run_id"):
            value = manifest.get(key)
            if value not in (None, ""):
                return str(value)
    return None


def _build_input_snapshot(
    payload: dict[str, Any],
    input_payload: Any,
    *,
    repository_root: Path,
    source_cutoff_at: str | None,
    created_at: str | None,
) -> tuple[dict[str, Any], Any]:
    canonical_input = _deterministic_input(payload, input_payload)
    input_hash = _sha256_value(canonical_input)
    source_refs = _collect_source_refs(input_payload) if input_payload is not None else []
    snapshot_id = "FBOS-SNAPSHOT-" + input_hash[:24]
    metadata = {
        "snapshot_id": snapshot_id,
        "manifest_ref": _manifest_ref(input_payload),
        "source_refs": source_refs,
        "source_hashes": _source_hashes(source_refs, repository_root),
        "captured_at": source_cutoff_at or created_at,
        "canonical_input_sha256": input_hash,
        "snapshot_ref": f"data/model_governance/input_snapshots/{input_hash}.json",
    }
    return metadata, canonical_input


def _calibration_metadata(config: dict[str, Any], repository_root: Path) -> dict[str, Any]:
    reference = (
        config.get("champion", {}).get("calibration_artifact")
        or config.get("versions", {}).get("calibration_artifact")
        or "data/model_calibration/latest.json"
    )
    path = Path(reference)
    if not path.is_absolute():
        path = repository_root / path
    artifact_hash = sha256_file(path) if path.is_file() else None
    version = None
    if path.is_file():
        try:
            artifact = _load_json(path)
            if isinstance(artifact, dict):
                version = artifact.get("calibration_version") or artifact.get("schema_version") or artifact.get("generated_at")
        except (OSError, json.JSONDecodeError):
            pass
    return {"reference": str(reference), "version": version, "sha256": artifact_hash}


def _lineup_status(payload: dict[str, Any], missing: list[str]) -> str | None:
    quality = payload.get("data_quality") or {}
    fundamentals = payload.get("fundamentals") or {}
    value = quality.get("lineup_status") or fundamentals.get("lineup_status") or payload.get("lineup_status")
    if value is not None and str(value) in _LINEUP_STATUSES:
        return str(value)
    if any("lineup" in item.casefold() or "line-up" in item.casefold() or "lineup" in item for item in missing):
        return "missing_unexpectedly"
    return None


def _is_critical_missing(field: str, lineup_status: str | None) -> bool:
    normalized = str(field).strip().casefold()
    if any(token in normalized for token in ("lineup", "line-up", "首发")):
        return lineup_status not in {"unavailable_by_time", "projected", "confirmed"}
    critical_tokens = (
        "match identity", "match_id", "canonical_match", "fixture", "kickoff", "比赛身份",
        "source cutoff", "cutoff", "source_cutoff", "截止", "timestamp", "时间戳", "snapshot",
        "快照", "probability", "probabilities", "概率", "lambda", "λ", "reproduc", "input source",
        "input_snapshot", "输入来源", "manifest", "market baseline", "market input", "odds snapshot",
        "盘口输入", "盘口快照",
    )
    return any(token in normalized for token in critical_tokens)


def _classify_missing_fields(
    quality_missing: list[str],
    structural_missing: list[str],
    lineup_status: str | None,
    *,
    projected_lineup_allowed: bool = True,
) -> tuple[list[str], list[str]]:
    critical: list[str] = list(structural_missing)
    noncritical: list[str] = []
    for field in quality_missing:
        if "lineup" in field.casefold() or "line-up" in field.casefold() or "lineup" in field:
            lineup_allowed = lineup_status in {"unavailable_by_time", "confirmed"} or (
                lineup_status == "projected" and projected_lineup_allowed
            )
            (noncritical if lineup_allowed else critical).append(field)
        else:
            (critical if _is_critical_missing(field, lineup_status) else noncritical).append(field)
    return list(dict.fromkeys(critical)), list(dict.fromkeys(noncritical))


def _challenger_id(config: dict[str, Any], method: str) -> str | None:
    for challenger in config.get("challengers") or []:
        if isinstance(challenger, dict) and method in {challenger.get("model_core_version"), challenger.get("model_family")}:
            return str(challenger.get("id") or challenger.get("challenger_id") or method)
    return None


def build_prediction_record(
    payload: dict[str, Any],
    *,
    config: dict[str, Any] | None = None,
    input_payload: Any = None,
    commit_sha: str | None = None,
    repository_root: Path = ROOT,
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
    role, challenger_id = _model_role_info(payload, config)
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
    input_snapshot, canonical_input = _build_input_snapshot(
        payload,
        input_payload,
        repository_root=repository_root,
        source_cutoff_at=source_cutoff,
        created_at=created_at,
    )
    input_hash = input_snapshot["canonical_input_sha256"]
    lineup_status = _lineup_status(payload, [str(item) for item in (payload.get("data_quality") or {}).get("missing") or []])
    structural_missing: list[str] = []
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
    quality_missing = list(dict.fromkeys(
        str(item) for item in [
            *((payload.get("data_quality") or {}).get("missing") or []),
            *(classification.get("analysis_missing") or []),
        ] if item
    ))
    critical_missing, noncritical_missing = _classify_missing_fields(
        quality_missing,
        structural_missing,
        lineup_status,
        projected_lineup_allowed=bool(config["quality_policy"].get("projected_lineup_formal_allowed", True)),
    )
    primary = decisions.get("unique_primary_dimension")
    manual_override = payload.get("manual_override") if isinstance(payload.get("manual_override"), bool) else False
    model_formal = (
        role == "champion"
        and grade in set(config["quality_policy"].get("formal_grades") or ["A", "B"])
        and bool(primary)
        and not critical_missing
        and not manual_override
    )
    prediction_variant = "human_assisted" if manual_override else "model_only"
    prediction_status = "human_assisted" if manual_override else "formal" if model_formal else "research_only"
    prompt_version = (payload.get("automation") or {}).get("prompt_version") or versions.get("prompt_version")
    calibration = _calibration_metadata(config, repository_root)
    model_run_identity = {
        "model_role": role,
        "model_family": model_family,
        "model_core_version": model_core_version,
        "release_version": release_version,
        "feature_version": versions.get("feature_version"),
        "data_pipeline_version": versions.get("data_pipeline_version"),
        "calibration": calibration,
        "prompt_version": prompt_version,
        "repository_commit_sha": commit,
        "challenger_id": challenger_id,
    }
    model_run_fingerprint = _sha256_value(model_run_identity)
    match_identity = {
        "match_key": _match_key(payload),
        "home": match.get("home"),
        "away": match.get("away"),
        "kickoff_at": kickoff,
    }
    snapshot_identity = {
        "snapshot_id": input_snapshot["snapshot_id"],
        "source_cutoff_at": source_cutoff,
        "odds_snapshot_at": odds_snapshot,
        "input_sha256": input_hash,
    }
    prediction_identity = {
        "match_identity": match_identity,
        "snapshot_identity": snapshot_identity,
        "model_run_identity": model_run_identity,
    }
    scores = _score_values(model, 5)
    record = {
        "schema_version": "1.1",
        "prediction_id": "FBOS-PRED-" + _sha256_value(prediction_identity)[:24],
        "match_key": match_identity["match_key"],
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
        "prompt_version": prompt_version,
        "data_grade": grade,
        "formal_eligible": model_formal,
        "model_formal_eligible": model_formal,
        "prediction_variant": prediction_variant,
        "prediction_status": prediction_status,
        "missing_critical_fields": critical_missing,
        "critical_missing_fields": critical_missing,
        "noncritical_missing_fields": noncritical_missing,
        "missing_fields": list(dict.fromkeys([*critical_missing, *noncritical_missing])),
        "manual_override": manual_override if payload.get("manual_override") is not None else None,
        "lineup_status": lineup_status,
        "input_sha256": input_hash,
        "input_snapshot": input_snapshot,
        "match_identity": match_identity,
        "snapshot_identity": snapshot_identity,
        "model_run_identity": model_run_identity,
        "model_run_fingerprint": model_run_fingerprint,
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
            "status": prediction_status,
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
        # Kept only during the build/freeze call.  freeze_prediction writes it
        # to the content-addressed snapshot file and removes it from the ledger.
        "_input_snapshot_content": canonical_input,
    }
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
    snapshot = record.get("input_snapshot") or {}
    if snapshot.get("canonical_input_sha256") != record.get("input_sha256"):
        raise ValueError("input snapshot hash does not match input_sha256")
    if record.get("prediction_variant") == "human_assisted" and record.get("model_formal_eligible") is not False:
        raise ValueError("human-assisted prediction cannot be model-formal eligible")


def _snapshot_path(snapshot: dict[str, Any], snapshot_root: Path) -> Path:
    input_hash = str(snapshot.get("canonical_input_sha256") or "")
    if not input_hash:
        raise ValueError("input snapshot is missing canonical_input_sha256")
    return snapshot_root / f"{input_hash}.json"


def _validate_snapshot_document(document: dict[str, Any], record: dict[str, Any]) -> dict[str, Any]:
    snapshot = record.get("input_snapshot") or {}
    if document.get("snapshot_id") != snapshot.get("snapshot_id"):
        raise ValueError("input snapshot id does not match prediction record")
    canonical_input = document.get("input")
    if _sha256_value(canonical_input) != snapshot.get("canonical_input_sha256"):
        raise ValueError("input snapshot content hash mismatch")
    if snapshot.get("canonical_input_sha256") != record.get("input_sha256"):
        raise ValueError("input snapshot hash does not match prediction record")
    return document


def load_input_snapshot(record: dict[str, Any], snapshot_root: Path = DEFAULT_INPUT_SNAPSHOT_ROOT) -> dict[str, Any]:
    path = _snapshot_path(record.get("input_snapshot") or {}, snapshot_root)
    try:
        document = _load_json(path)
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"input snapshot is unavailable: {path}") from error
    if not isinstance(document, dict):
        raise ValueError("input snapshot is not an object")
    return _validate_snapshot_document(document, record)


def _write_snapshot(record: dict[str, Any], snapshot_root: Path) -> None:
    snapshot_root.mkdir(parents=True, exist_ok=True)
    path = _snapshot_path(record["input_snapshot"], snapshot_root)
    existing = None
    if path.exists():
        try:
            existing = _load_json(path)
        except (OSError, json.JSONDecodeError) as error:
            raise PredictionConflictError(f"existing input snapshot is unreadable: {path}") from error
        if not isinstance(existing, dict):
            raise PredictionConflictError(f"existing input snapshot is invalid: {path}")
        _validate_snapshot_document(existing, record)
        content = record.get("_input_snapshot_content")
        if content is None:
            return
        if canonical_json(existing) != canonical_json({**record["input_snapshot"], "input": content}):
            raise PredictionConflictError(f"input snapshot content conflict: {record['input_snapshot']['snapshot_id']}")
        return
    content = record.get("_input_snapshot_content")
    if content is None:
        raise ValueError("input snapshot content is unavailable for first freeze")
    document = {**record["input_snapshot"], "input": content}
    _validate_snapshot_document(document, record)
    with path.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(document, ensure_ascii=False, indent=2) + "\n")


def freeze_prediction(
    record: dict[str, Any],
    record_root: Path = DEFAULT_RECORD_ROOT,
    *,
    input_snapshot_root: Path | None = None,
) -> dict[str, Any]:
    _validate_record(record)
    if input_snapshot_root is None:
        input_snapshot_root = (
            DEFAULT_INPUT_SNAPSHOT_ROOT
            if record_root == DEFAULT_RECORD_ROOT
            else record_root.parent / "input_snapshots"
        )
    _write_snapshot(record, input_snapshot_root)
    record_root.mkdir(parents=True, exist_ok=True)
    target = record_root / f"{record['prediction_id']}.json"
    stored_record = {key: value for key, value in record.items() if not key.startswith("_")}
    serialized = canonical_json(stored_record)
    try:
        with target.open("x", encoding="utf-8") as handle:
            handle.write(json.dumps(stored_record, ensure_ascii=False, indent=2) + "\n")
        return {"status": "created", "path": target, "record": stored_record}
    except FileExistsError:
        try:
            existing = _load_json(target)
        except (OSError, json.JSONDecodeError) as error:
            raise PredictionConflictError(f"existing frozen prediction is unreadable: {target}") from error
        if canonical_json(existing) != serialized:
            raise PredictionConflictError(f"prediction id content conflict: {record['prediction_id']}")
        return {"status": "existing", "path": target, "record": existing}


def load_frozen_prediction(prediction_id: str, record_root: Path = DEFAULT_RECORD_ROOT) -> dict[str, Any] | None:
    if not prediction_id:
        return None
    path = record_root / f"{prediction_id}.json"
    if not path.is_file():
        return None
    try:
        record = _load_json(path)
        if not isinstance(record, dict):
            return None
        _validate_record(record)
    except (OSError, json.JSONDecodeError, ValueError):
        return None
    return record


def validate_postmatch_review_link(
    review: dict[str, Any],
    record_root: Path = DEFAULT_RECORD_ROOT,
) -> dict[str, Any]:
    prediction_id = str(review.get("prediction_id") or "").strip()
    if not prediction_id:
        return {"status": "missing_prediction_id", "formal_eligible": False, "record": None}
    record = load_frozen_prediction(prediction_id, record_root)
    if record is None:
        return {"status": "prediction_not_found", "formal_eligible": False, "record": None}
    if review.get("prediction_sha256") != record.get("prediction_sha256"):
        return {"status": "hash_mismatch", "formal_eligible": False, "record": record}
    if review.get("model_run_fingerprint") != record.get("model_run_fingerprint"):
        return {"status": "fingerprint_mismatch", "formal_eligible": False, "record": record}
    required_match_fields = ("source_cutoff_at", "odds_snapshot_at", "repository_commit_sha")
    if any(review.get(field) != record.get(field) for field in required_match_fields):
        return {"status": "snapshot_metadata_mismatch", "formal_eligible": False, "record": record}
    formal = bool(
        record.get("model_formal_eligible") is True
        and record.get("prediction_variant") == "model_only"
        and (review.get("prediction_layer") or {}).get("formal_pick_eligible") is True
    )
    return {"status": "verified", "formal_eligible": formal, "record": record}


def can_update_parameters(
    *,
    sample_count: int,
    match_count: int | None = None,
    unique_match_count: int | None = None,
    config: dict[str, Any] | None = None,
) -> bool:
    config = config or load_config()
    minimum = int(config["correction_policy"].get("minimum_holdout_samples") or 50)
    unique = unique_match_count if unique_match_count is not None else int(match_count or 0)
    return sample_count >= minimum and unique >= minimum and unique > 1


def _metric_value(metrics: Any, key: str) -> float | None:
    return _number((metrics or {}).get(key)) if isinstance(metrics, dict) else None


def evaluate_promotion(comparison: dict[str, Any], config: dict[str, Any] | None = None) -> dict[str, Any]:
    config = config or load_config()
    gates = config["promotion_gates"]
    blocking: list[str] = []
    warnings: list[str] = []
    sample_count = int(comparison.get("sample_count") or comparison.get("snapshot_count") or 0)
    unique_match_count = int(comparison.get("unique_match_count") or comparison.get("match_count") or 0)
    minimum_samples = int(gates.get("minimum_holdout_samples") or 50)
    minimum_unique = int(gates.get("minimum_holdout_unique_matches") or minimum_samples)
    if sample_count < minimum_samples:
        blocking.append("minimum_holdout_samples")
    if unique_match_count < minimum_unique:
        blocking.append("minimum_holdout_unique_matches")
    if gates.get("requires_same_match_same_snapshot") and comparison.get("same_snapshot") is not True:
        blocking.append("same_match_same_snapshot")
    if gates.get("requires_out_of_sample_validation") and comparison.get("out_of_sample") is not True:
        blocking.append("out_of_sample_validation")
    if gates.get("requires_reproducible_inputs") and comparison.get("reproducible_inputs") is not True:
        blocking.append("reproducible_inputs")
    if comparison.get("snapshot_consistent") is False:
        blocking.append("snapshot_consistency")
    for name in ("champion", "challenger"):
        metrics = comparison.get(name)
        if not isinstance(metrics, dict):
            blocking.append(f"{name}_comparison_missing")
            continue
        if _metric_value(metrics, "brier_score") is None:
            blocking.append(f"{name}_brier_missing")
        if _metric_value(metrics, "log_loss") is None:
            blocking.append(f"{name}_log_loss_missing")
    for name, gate_key in (("market_baseline", "requires_market_baseline"), ("simple_baseline", "requires_simple_baseline")):
        metrics = comparison.get(name)
        if gates.get(gate_key) and not isinstance(metrics, dict):
            blocking.append(f"{name}_comparison_missing")
        elif gates.get(gate_key):
            if _metric_value(metrics, "brier_score") is None or _metric_value(metrics, "log_loss") is None:
                blocking.append(f"{name}_metrics_missing")
    champion = comparison.get("champion") or {}
    challenger = comparison.get("challenger") or {}
    champion_brier = _metric_value(champion, "brier_score")
    challenger_brier = _metric_value(challenger, "brier_score")
    if gates.get("brier_must_improve") and champion_brier is not None and challenger_brier is not None:
        if challenger_brier >= champion_brier:
            blocking.append("brier_not_improved")
    champion_log_loss = _metric_value(champion, "log_loss")
    challenger_log_loss = _metric_value(challenger, "log_loss")
    if gates.get("log_loss_must_not_deteriorate") and champion_log_loss is not None and challenger_log_loss is not None:
        if challenger_log_loss > champion_log_loss:
            blocking.append("log_loss_deteriorated")
    if gates.get("automatic_promotion_forbidden"):
        warnings.append("automatic_promotion_forbidden")
    blocking = list(dict.fromkeys(blocking))
    return {
        "eligible_for_human_review": not blocking,
        "automatic_promotion": False,
        "requires_human_approval": True,
        "blocking_reasons": blocking,
        "warnings": list(dict.fromkeys(warnings)),
        # Compatibility aliases are intentionally equal to the human-review
        # result; automatic promotion is never represented by `eligible`.
        "eligible": not blocking,
        "reasons": blocking,
    }


def _is_current_view(path: Path, root: Path) -> bool:
    try:
        return "current" in path.relative_to(root).parts
    except ValueError:
        return False


def _iter_json(root: Path, *, include_current: bool = True) -> list[tuple[Path, dict[str, Any]]]:
    rows = []
    if not root.exists():
        return rows
    for path in sorted(root.rglob("*.json")):
        if not include_current and _is_current_view(path, root):
            continue
        try:
            value = _load_json(path)
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(value, dict):
            rows.append((path, value))
    return rows


def _current_view_file_count(root: Path) -> int:
    if not root.exists():
        return 0
    return sum(1 for path in root.rglob("*.json") if _is_current_view(path, root))


def _frozen_rows(root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not root.exists():
        return rows
    for path in sorted(root.glob("*.json")):
        try:
            value = _load_json(path)
            if isinstance(value, dict):
                _validate_record(value)
                rows.append(value)
        except (OSError, json.JSONDecodeError, ValueError):
            continue
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


def _report_prediction_id(payload: dict[str, Any]) -> str | None:
    value = (payload.get("model_governance") or {}).get("prediction_id")
    return str(value) if value not in (None, "") else None


def _report_snapshot_key(payload: dict[str, Any]) -> tuple[str, str, str] | None:
    governance = payload.get("model_governance") or {}
    prediction_id = _report_prediction_id(payload)
    if not prediction_id:
        return None
    report = payload.get("report") or {}
    checkpoint = report.get("market_checkpoint") or {}
    return (
        prediction_id,
        str(report.get("source_cutoff_at") or report.get("snapshot_timestamp") or checkpoint.get("captured_at") or ""),
        str(report.get("odds_snapshot_at") or checkpoint.get("captured_at") or ""),
    )


def _review_hit(payload: dict[str, Any], key: str) -> bool | None:
    value = ((payload.get("settlement") or {}).get(key) or {}).get("hit")
    return value if isinstance(value, bool) else None


def _review_hit_metric(rows: list[dict[str, Any]], key: str) -> dict[str, Any] | None:
    values = [_review_hit(row, key) for row in rows]
    values = [value for value in values if value is not None]
    if not values:
        return None
    return {"settled": len(values), "hits": sum(values), "hit_rate": round(sum(values) / len(values), 6)}


def _metric_bundle(rows: list[dict[str, Any]]) -> dict[str, Any]:
    diagnostics = [row.get("model_diagnostics") or {} for row in rows]
    brier = [float(row["brier_score_1x2"]) for row in diagnostics if _number(row.get("brier_score_1x2")) is not None]
    log_loss = [float(row["log_loss_1x2"]) for row in diagnostics if _number(row.get("log_loss_1x2")) is not None]
    ranks = [int(row["actual_score_rank"]) for row in diagnostics if row.get("actual_score_rank") is not None]
    return {
        "brier_score": round(sum(brier) / len(brier), 6) if brier else None,
        "log_loss": round(sum(log_loss) / len(log_loss), 6) if log_loss else None,
        "win_draw_loss": _review_hit_metric(rows, "model_1x2"),
        "over_under": _review_hit_metric(rows, "total_goals_mode"),
        "btts": _review_hit_metric(rows, "btts"),
        "score_top1": round(sum(rank <= 1 for rank in ranks) / len(ranks), 6) if ranks else None,
        "score_top3": round(sum(rank <= 3 for rank in ranks) / len(ranks), 6) if ranks else None,
        "score_top5": round(sum(rank <= 5 for rank in ranks) / len(ranks), 6) if ranks else None,
        "actual_score_mean_rank": round(sum(ranks) / len(ranks), 4) if ranks else None,
        "roi": None,
        "clv": None,
        "max_drawdown": None,
    }


def _match_key_from_record(record: dict[str, Any]) -> str:
    return str(record.get("match_key") or (record.get("match_identity") or {}).get("match_key") or "")


def build_current_metrics(
    report_root: Path = ROOT / "data" / "analysis_reports",
    review_root: Path = ROOT / "data" / "postmatch_reviews",
    config: dict[str, Any] | None = None,
    *,
    frozen_root: Path = DEFAULT_RECORD_ROOT,
) -> dict[str, Any]:
    config = config or load_config()
    champion = config["champion"]
    report_rows = [payload for _, payload in _iter_json(report_root, include_current=False)]
    prediction_reports = [payload for payload in report_rows if _report_is_prediction(payload)]
    report_ids = {_report_prediction_id(payload) for payload in prediction_reports}
    report_ids.discard(None)
    snapshot_keys = {_report_snapshot_key(payload) for payload in prediction_reports}
    snapshot_keys.discard(None)
    match_keys = {
        str((payload.get("match") or {}).get("canonical_match_id") or (payload.get("match") or {}).get("match_id") or "")
        for payload in prediction_reports if _report_prediction_id(payload)
    }
    match_keys.discard("")
    historical_inventory = len(report_rows)
    legacy_records = sum(1 for payload in prediction_reports if not _report_prediction_id(payload))
    frozen_rows = _frozen_rows(frozen_root)
    champion_rows = [
        row for row in frozen_rows
        if row.get("model_role") == "champion"
        and row.get("model_core_version") == champion.get("model_core_version")
        and row.get("release_version") == champion.get("release_version")
    ]
    formal_rows = [
        row for row in champion_rows
        if row.get("model_formal_eligible") is True
        and row.get("formal_eligible") is True
        and row.get("prediction_variant") == "model_only"
        and row.get("data_grade") in set(config["quality_policy"].get("formal_grades") or ["A", "B"])
    ]
    human_assisted_rows = [row for row in frozen_rows if row.get("prediction_variant") == "human_assisted"]
    grades = Counter({grade: 0 for grade in ("A", "B", "C", "D")})
    for payload in prediction_reports:
        grade, _ = _grade(payload)
        grades[grade] += 1
    frozen_grades = Counter({grade: 0 for grade in ("A", "B", "C", "D")})
    for row in champion_rows:
        grade = str(row.get("data_grade") or "").upper()
        if grade in frozen_grades:
            frozen_grades[grade] += 1

    exact_reviews: list[dict[str, Any]] = []
    link_status_counts: Counter[str] = Counter()
    duplicate_review_ids: list[str] = []
    seen_review_ids: set[str] = set()
    for _, review in _iter_json(review_root):
        link = validate_postmatch_review_link(review, frozen_root)
        link_status_counts[link["status"]] += 1
        if link["status"] != "verified":
            continue
        prediction_id = str(review.get("prediction_id"))
        if prediction_id in seen_review_ids:
            duplicate_review_ids.append(prediction_id)
            continue
        seen_review_ids.add(prediction_id)
        exact_reviews.append(review)
    settled_rows = [row for row in exact_reviews if row.get("prediction_id")]
    formal_review_rows = [
        review for review in exact_reviews
        if validate_postmatch_review_link(review, frozen_root)["formal_eligible"]
    ]
    all_record_by_id = {str(row.get("prediction_id")): row for row in frozen_rows}
    formal_ids = {str(row.get("prediction_id")) for row in formal_rows}
    formal_review_rows = [row for row in formal_review_rows if str(row.get("prediction_id")) in formal_ids]
    formal_by_match: dict[str, list[dict[str, Any]]] = defaultdict(list)
    record_by_id = {str(row.get("prediction_id")): row for row in formal_rows}
    for review in formal_review_rows:
        record = record_by_id.get(str(review.get("prediction_id")))
        if record:
            formal_by_match[_match_key_from_record(record)].append(review)
    # Match-level evaluation uses one deterministic latest snapshot per match;
    # the snapshot-level values retain every exact, non-duplicate settlement.
    match_representatives = [
        sorted(rows, key=lambda row: str(row.get("source_cutoff_at") or ""))[-1]
        for rows in formal_by_match.values() if rows
    ]
    metrics = _metric_bundle(formal_review_rows)
    match_metrics = _metric_bundle(match_representatives)
    reasons: dict[str, str] = {}
    if not formal_review_rows:
        reasons["formal_metrics"] = "no exact-settled Champion model-only A/B frozen predictions"
    for metric in ("brier_score", "log_loss", "win_draw_loss", "over_under", "btts", "score_top1", "score_top3", "score_top5", "actual_score_mean_rank"):
        if metrics.get(metric) is None:
            reasons[metric] = reasons.get("formal_metrics")
    priced = [row for row in formal_review_rows if row.get("real_executable_price") is True]
    if not priced:
        reasons["roi"] = "no exact-settled formal sample with a verified real executable price"
        reasons["clv"] = "no verified closing-price comparison"
        reasons["max_drawdown"] = "no verified executable-price equity curve"
    scope = {
        "report_record_count": historical_inventory,
        "historical_report_inventory": historical_inventory,
        "historical_report_records": historical_inventory,
        "convenience_view_records_excluded": _current_view_file_count(report_root),
        "unique_prediction_count": len(report_ids),
        "unique_match_snapshot_count": len(snapshot_keys),
        "unique_match_count": len(match_keys),
        "unique_matches": len(match_keys),
        "true_governance_frozen_predictions": len(frozen_rows),
        "champion_frozen_predictions": len(champion_rows),
        "formal_prediction_count": len(formal_rows),
        "formal_unique_match_count": len({_match_key_from_record(row) for row in formal_rows}),
        "formal_unique_matches": len({_match_key_from_record(row) for row in formal_rows}),
        "human_assisted_prediction_count": len(human_assisted_rows),
        "human_assisted_unique_match_count": len({_match_key_from_record(row) for row in human_assisted_rows}),
        "settled_prediction_count": len(settled_rows),
        "settled_unique_match_count": len({_match_key_from_record(all_record_by_id.get(str(row.get("prediction_id")), {})) for row in settled_rows}),
        "formal_settled_prediction_count": len(formal_review_rows),
        "formal_settled_unique_match_count": len(formal_by_match),
        "formal_settled_unique_matches": len(formal_by_match),
        "formal_grades": ["A", "B"],
        "legacy_records": legacy_records,
        "legacy_records_excluded": legacy_records,
        "duplicate_review_ids_excluded": sorted(set(duplicate_review_ids)),
    }
    missing_reasons = {
        metric: reasons.get(metric) for metric in (
            "brier_score", "log_loss", "win_draw_loss", "over_under", "btts", "score_top1",
            "score_top3", "score_top5", "actual_score_mean_rank", "roi", "clv", "max_drawdown",
        )
    }
    return {
        "schema_version": "1.1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "report_record_count": historical_inventory,
        "historical_report_records": historical_inventory,
        "unique_prediction_count": len(report_ids),
        "unique_match_snapshot_count": len(snapshot_keys),
        "unique_match_count": len(match_keys),
        "unique_matches": len(match_keys),
        "true_governance_frozen_predictions": len(frozen_rows),
        "formal_prediction_count": len(formal_rows),
        "formal_unique_match_count": len({_match_key_from_record(row) for row in formal_rows}),
        "formal_unique_matches": len({_match_key_from_record(row) for row in formal_rows}),
        "human_assisted_prediction_count": len(human_assisted_rows),
        "human_assisted_unique_match_count": len({_match_key_from_record(row) for row in human_assisted_rows}),
        "settled_prediction_count": len(settled_rows),
        "settled_unique_match_count": len({_match_key_from_record(all_record_by_id.get(str(row.get("prediction_id")), {})) for row in settled_rows}),
        "formal_settled_unique_match_count": len(formal_by_match),
        "formal_settled_unique_matches": len(formal_by_match),
        "scope": scope,
        "quality_distribution": dict(sorted(grades.items())),
        "frozen_quality_distribution": dict(sorted(frozen_grades.items())),
        "metrics": metrics,
        "human_assisted_metrics": {
            "prediction_count": len(human_assisted_rows),
            "unique_match_count": len({_match_key_from_record(row) for row in human_assisted_rows}),
            "model_metrics_eligible": False,
        },
        "snapshot_metrics": metrics,
        "match_metrics": match_metrics,
        "missing_reasons": missing_reasons,
        "review_link_status": dict(sorted(link_status_counts.items())),
        "policy": {
            "formal_grades": ["A", "B"],
            "formal_metrics_require_exact_prediction_id": True,
            "legacy_separated": True,
            "research_grades": ["C", "D"],
            "current_view_excluded_from_inventory": True,
            "manual_override_excluded_from_model_metrics": True,
            "human_assisted_reported_separately": True,
        },
    }


def _latest_commit_for_file(root: Path, path: str) -> str | None:
    return _git_value(root, "log", "-1", "--format=%H", "HEAD", "--", path)


def build_baseline_manifest(
    *,
    baseline_commit_sha: str | None = None,
    branch: str,
    config: dict[str, Any] | None = None,
    report_root: Path = ROOT / "data" / "analysis_reports",
    review_root: Path = ROOT / "data" / "postmatch_reviews",
    frozen_root: Path = DEFAULT_RECORD_ROOT,
    model_source_commit_sha: str | None = None,
    governance_implementation_commit_sha: str | None = None,
    baseline_export_commit_sha: str | None = None,
    origin_main_observed_sha: str | None = None,
) -> dict[str, Any]:
    config = config or load_config()
    metrics = build_current_metrics(report_root, review_root, config, frozen_root=frozen_root)
    head = resolve_commit_sha(ROOT)
    clean = working_tree_clean(ROOT)
    model_source_commit_sha = model_source_commit_sha or _latest_commit_for_file(ROOT, "scripts/automatic_model_core.py") or head
    governance_implementation_commit_sha = governance_implementation_commit_sha or head or baseline_commit_sha
    baseline_export_commit_sha = baseline_export_commit_sha if baseline_export_commit_sha is not None else head if clean else None
    origin_main_observed_sha = origin_main_observed_sha or resolve_origin_main_sha(ROOT)
    return {
        "schema_version": "1.1",
        "baseline_id": "football-baseline-v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "repository": "gemini077/football-betting-oneshot",
        "branch": branch,
        "model_source_commit_sha": model_source_commit_sha,
        "governance_implementation_commit_sha": governance_implementation_commit_sha,
        "baseline_export_commit_sha": baseline_export_commit_sha,
        "origin_main_observed_sha": origin_main_observed_sha,
        "working_tree_clean": clean,
        "champion": {**config["champion"], "status": "frozen_baseline"},
        "versions": config["versions"],
        "evaluation_scope": metrics["scope"],
        "core_file_hashes": hash_files(MODEL_SOURCE_FILES)["files"],
        "governance_file_hashes": hash_files(GOVERNANCE_FILES)["files"],
        "production_math_changed": False,
    }


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def export_baseline(
    output_root: Path,
    *,
    baseline_commit_sha: str | None = None,
    branch: str,
    origin_main_observed_sha: str | None = None,
) -> dict[str, Any]:
    config = load_config()
    manifest = build_baseline_manifest(
        baseline_commit_sha=baseline_commit_sha,
        branch=branch,
        config=config,
        origin_main_observed_sha=origin_main_observed_sha,
    )
    metrics = build_current_metrics(config=config)
    write_json(output_root / "manifest.json", manifest)
    write_json(output_root / "current-metrics.json", metrics)
    write_json(output_root / "file-hashes.json", {
        "algorithm": "sha256",
        "core_files": hash_files(MODEL_SOURCE_FILES)["files"],
        "governance_files": hash_files(GOVERNANCE_FILES)["files"],
    })
    return {"manifest": manifest, "metrics": metrics}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--export-baseline", type=Path)
    parser.add_argument("--baseline-commit-sha")
    parser.add_argument("--branch", default="")
    parser.add_argument("--origin-main-observed-sha")
    args = parser.parse_args()
    if not args.export_baseline:
        parser.error("--export-baseline is required")
    result = export_baseline(
        args.export_baseline,
        baseline_commit_sha=args.baseline_commit_sha or resolve_commit_sha(),
        branch=args.branch or "unknown",
        origin_main_observed_sha=args.origin_main_observed_sha or resolve_origin_main_sha(),
    )
    print(json.dumps({"manifest": result["manifest"], "metrics": result["metrics"]["scope"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
