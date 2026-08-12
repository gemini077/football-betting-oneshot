#!/usr/bin/env python3
"""Auditable Champion/Challenger governance without changing model math."""

from __future__ import annotations

import argparse
import ast
from copy import deepcopy
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
MODEL_INPUT_CONTRACT_VERSION = "deterministic_model_input.v1"
SNAPSHOT_CONTRACT_VERSION = "governance_snapshot.v2"
DEFAULT_CALIBRATION_ARTIFACT = "data/model_calibration/latest.json"

REQUIRED_RECORD_FIELDS = (
    "prediction_id", "match_key", "created_at", "kickoff_at", "source_cutoff_at",
    "prediction_created_at", "model_input_as_of_at", "market_snapshot_at", "source_time_range",
    "odds_snapshot_at", "repository_commit_sha", "model_source_fingerprint",
    "calibration_artifact_sha256", "effective_calibration_fingerprint",
    "canonical_model_input_sha256", "model_input_snapshot_ref", "model_role", "model_core_version",
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
    "scripts/checkpoint_features.py",
    "scripts/prematch_fundamentals.py",
    "scripts/match_identity.py",
    "scripts/deepseek_auto_analysis.py",
)
MODEL_SOURCE_COMPONENTS = (
    ("scripts/automatic_model_core.py", None),
    ("scripts/risk_engine.py", None),
    ("scripts/market_contracts.py", None),
    ("scripts/checkpoint_features.py", None),
    ("scripts/prematch_fundamentals.py", None),
    ("scripts/match_identity.py", "canonical_match_id"),
    # Only the context construction symbols are model-input dependencies.
    # The LLM prompt and HTML/report code are deliberately excluded.
    ("scripts/deepseek_auto_analysis.py", "prune"),
    ("scripts/deepseek_auto_analysis.py", "selected_workspace_match"),
    ("scripts/deepseek_auto_analysis.py", "analysis_context"),
    ("scripts/model_governance.py", "_pick"),
    ("scripts/model_governance.py", "_project_market_snapshot"),
    ("scripts/model_governance.py", "_number"),
    ("scripts/model_governance.py", "effective_calibration_projection"),
    ("scripts/model_governance.py", "build_deterministic_model_input_projection"),
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
_AUDIT_ONLY_PREDICTION_FIELDS = {
    "repository_commit_sha",
    "calibration_artifact_sha256",
    "created_at",
    "prediction_created_at",
    "prompt_version",
    "report_schema_version",
    "postmatch_schema_version",
    "checkpoint_stage",
    "checkpoint_target_at",
    "checkpoint_captured_at",
    "minutes_to_kickoff_at_capture",
    "checkpoint_metadata",
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
    for key in (
        "feature_version", "data_pipeline_version", "report_schema_version",
        "postmatch_schema_version", "prompt_version",
        "canonical_model_input_contract_version", "snapshot_contract_version",
    ):
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


def _normalise_source_components(components: Any) -> tuple[tuple[str, str | None], ...]:
    values = components if components is not None else MODEL_SOURCE_COMPONENTS
    normalised: list[tuple[str, str | None]] = []
    for value in values:
        if isinstance(value, (list, tuple)):
            path = str(value[0])
            symbol = str(value[1]) if len(value) > 1 and value[1] else None
        else:
            path, symbol = str(value), None
        normalised.append((path, symbol))
    return tuple(normalised)


def _hash_source_symbol(path: Path, symbol: str) -> str | None:
    try:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
    except (OSError, SyntaxError, UnicodeError):
        return None
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name == symbol:
            segment = ast.get_source_segment(source, node)
            return _sha256_bytes((segment or "").encode("utf-8"))
    return None


def model_source_fingerprint(
    root: Path = ROOT,
    *,
    components: Any = None,
) -> dict[str, Any]:
    """Hash only deterministic model execution dependencies.

    Repository data/report commits are intentionally absent.  Function-level
    hashes keep the DeepSeek prompt and report rendering from changing the
    deterministic Champion identity.
    """
    component_hashes: dict[str, str | None] = {}
    for relative, symbol in _normalise_source_components(components):
        target = Path(relative)
        target = target if target.is_absolute() else root / target
        key = f"{relative}::{symbol}" if symbol else relative
        component_hashes[key] = _hash_source_symbol(target, symbol) if symbol else (
            sha256_file(target) if target.is_file() else None
        )
    fingerprint = _sha256_value({"algorithm": "sha256", "components": component_hashes})
    return {
        "algorithm": "sha256",
        "components": component_hashes,
        "fingerprint": fingerprint,
    }


def governance_source_fingerprint(root: Path = ROOT) -> dict[str, Any]:
    hashed = hash_files(GOVERNANCE_FILES, root=root)
    fingerprint = _sha256_value(hashed)
    return {
        "algorithm": "sha256",
        "components": hashed["files"],
        "fingerprint": fingerprint,
    }


def _number(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def effective_calibration_projection(calibration: Any) -> dict[str, Any]:
    """Return only calibration state consumed by the deterministic Champion.

    The calibration JSON is also a research and audit artifact.  Its sample,
    validation, timestamps, and unapproved candidate values must not become a
    model identity input while the artifact is inactive or a section remains
    unapproved.  The projection mirrors the gates in
    ``automatic_model_core._calibration_state`` and the parameters read by
    ``build_automatic_model`` without changing that mathematical core.
    """
    from automatic_model_core import MODEL_FAMILY

    payload = calibration if isinstance(calibration, dict) else {}
    compatible = bool(payload.get("active")) and payload.get("model_family") == MODEL_FAMILY
    if not compatible:
        return {
            "model_family": MODEL_FAMILY,
            "active": False,
            "effective": False,
        }

    policy = payload.get("policy") if isinstance(payload.get("policy"), dict) else {}
    strength = _number(policy.get("strength")) or 0.0
    strength = max(0.0, min(0.6, strength))
    projection: dict[str, Any] = {
        "model_family": MODEL_FAMILY,
        "active": True,
        "effective": True,
        "policy": {"strength": strength},
    }

    direction = payload.get("direction") if isinstance(payload.get("direction"), dict) else {}
    direction_approved = bool(direction.get("approved"))
    direction_projection: dict[str, Any] = {"approved": direction_approved}
    if direction_approved:
        offsets = direction.get("logit_offsets") if isinstance(direction.get("logit_offsets"), dict) else {}
        direction_projection["logit_offsets"] = {
            key: _number(offsets.get(key)) or 0.0
            for key in ("home", "draw", "away")
        }
    projection["direction"] = direction_projection

    total_goals = payload.get("total_goals") if isinstance(payload.get("total_goals"), dict) else {}
    total_approved = bool(total_goals.get("approved"))
    total_projection: dict[str, Any] = {"approved": total_approved}
    if total_approved:
        total_projection["lambda_shift"] = _number(total_goals.get("lambda_shift")) or 0.0
    projection["total_goals"] = total_projection

    dispersion = payload.get("dispersion") if isinstance(payload.get("dispersion"), dict) else {}
    dispersion_approved = bool(dispersion.get("approved"))
    dispersion_projection: dict[str, Any] = {"approved": dispersion_approved}
    if dispersion_approved:
        dispersion_projection["tail_mixture_weight"] = _number(
            dispersion.get("tail_mixture_weight")
        ) or 0.0
    projection["dispersion"] = dispersion_projection
    return projection


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


def _checkpoint_metadata(payload: dict[str, Any]) -> dict[str, Any]:
    """Copy production checkpoint metadata as audit-only prediction fields.

    ``prematch_market_monitor.checkpoint_meta`` is the authoritative producer of
    these values.  This helper only copies the already-recorded metadata from
    the report payload; it never infers a stage from the current clock.
    """
    report = payload.get("report") or {}
    checkpoint = report.get("market_checkpoint") or {}
    health = report.get("checkpoint_health") or {}
    stage = checkpoint.get("stage") or health.get("stage")
    target_at = (
        checkpoint.get("scheduled_at")
        or checkpoint.get("target_at")
        or health.get("scheduled_at")
        or health.get("target_at")
    )
    captured_at = checkpoint.get("captured_at") or health.get("captured_at")
    minutes = (
        checkpoint.get("actual_minutes_before")
        if checkpoint.get("actual_minutes_before") is not None
        else health.get("actual_minutes_before")
    )
    return {
        "source": (
            "prematch_market_monitor.checkpoint_meta"
            if stage or target_at or captured_at
            else "unclassified"
        ),
        "stage": str(stage) if stage not in (None, "") else "unclassified",
        "target_at": target_at,
        "captured_at": captured_at,
        "minutes_to_kickoff_at_capture": minutes,
        "capture_quality": checkpoint.get("capture_quality") or health.get("status"),
        "scheduled_target_minutes": checkpoint.get("target_minutes_before"),
    }


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
    value = {
        key: value for key, value in record.items()
        if key not in {"prediction_sha256", "_input_snapshot_content", *_AUDIT_ONLY_PREDICTION_FIELDS}
        and not key.startswith("_")
    }
    snapshot = value.get("input_snapshot")
    if isinstance(snapshot, dict):
        value["input_snapshot"] = {
            key: snapshot.get(key)
            for key in (
                "snapshot_id", "contract_version", "snapshot_contract_version",
                "canonical_model_input_sha256", "canonical_input_sha256",
                "source_cutoff_at", "market_snapshot_at", "odds_snapshot_at",
            )
            if key in snapshot
        }
    return value


def prediction_content_hash(record: dict[str, Any]) -> str:
    """Hash immutable model content, excluding audit-only provenance fields."""
    return _sha256_value(_without_prediction_hash(record))


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


def _pick(value: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
    return {key: deepcopy(value[key]) for key in keys if key in value}


def _project_market_snapshot(snapshot: dict[str, Any], *, source_provider: str | None = None) -> dict[str, Any]:
    projected: dict[str, Any] = {}
    for key in ("fetched_at", "captured_at", "source_timestamp", "source_time"):
        if key in snapshot:
            projected[key] = deepcopy(snapshot[key])
    provenance = snapshot.get("source_provenance")
    if isinstance(provenance, dict) and "form_primary" in provenance:
        projected["source_provenance"] = {"form_primary": provenance.get("form_primary")}
    shuju = snapshot.get("shuju")
    if isinstance(shuju, dict) and "recent_form" in shuju:
        projected["shuju"] = {"recent_form": deepcopy(shuju.get("recent_form"))}
    for market, row_key, fields in (
        (
            "ouzhi",
            "bookmakers",
            (
                "name", "bookmaker", "company", "title", "cid", "source_company_id",
                "source", "source_provider", "spf_current",
            ),
        ),
        ("daxiao", "companies", ("name", "current_line", "current_over_water", "current_under_water")),
        ("yazhi", "companies", ("name", "current_handicap", "current_water_home", "current_water_away")),
    ):
        source = snapshot.get(market)
        if not isinstance(source, dict):
            continue
        rows = source.get(row_key)
        if not isinstance(rows, list):
            continue
        projected_rows = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            projected_row = _pick(row, fields)
            if source_provider and "source_provider" not in projected_row and "source" not in projected_row:
                projected_row["source_provider"] = source_provider
            projected_rows.append(projected_row)
        projected[market] = {row_key: projected_rows}
    context = snapshot.get("nowscore_context") or snapshot.get("context")
    if not isinstance(context, dict):
        nested = snapshot.get("nowscore")
        context = nested.get("context") if isinstance(nested, dict) else None
    if isinstance(context, dict):
        projected["nowscore_context"] = _pick(context, ("coach", "referee", "panlu", "source_urls"))
    return projected


def build_deterministic_model_input_projection(context: dict[str, Any]) -> dict[str, Any]:
    """Project exactly the context consumed by the deterministic Champion.

    The projection is deliberately built beside the real model call and then
    passed back into that call.  This prevents the report layer from guessing
    which raw source fields happened to be used.
    """
    sources = context.get("source_snapshots") or {}
    projected_sources: dict[str, Any] = {}
    for name in ("nowscore", "500_deep"):
        source = sources.get(name) or {}
        snapshots = source.get("snapshots") if isinstance(source, dict) else []
        if isinstance(snapshots, list) and snapshots and isinstance(snapshots[0], dict):
            projected_sources[name] = {
                "snapshots": [_project_market_snapshot(snapshots[0], source_provider=name)]
            }
    selected = context.get("selected_workspace_match") or {}
    request = context.get("request") or {}
    projection = {
        "request": _pick(request, ("match_id",)),
        "selected_workspace_match": _pick(selected, ("id", "home", "away")),
        "source_snapshots": projected_sources,
        "official_market_baseline": deepcopy(context.get("official_market_baseline") or {}),
        "checkpoint_features": deepcopy(context.get("checkpoint_features") or {}),
        "prematch_fundamentals": deepcopy(context.get("prematch_fundamentals") or {}),
        # The raw artifact contains research metadata and unapproved
        # candidates.  Only the effective state is a deterministic model
        # input; the complete artifact hash is retained separately for audit.
        "model_calibration": effective_calibration_projection(context.get("model_calibration") or {}),
    }
    return projection


def _timestamp(value: Any) -> str | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return text


def _snapshot_timestamp(snapshot: dict[str, Any]) -> str | None:
    for key in ("fetched_at", "captured_at", "source_timestamp", "source_time"):
        value = _timestamp(snapshot.get(key))
        if value:
            return value
    return None


def _max_timestamp(values: list[str | None]) -> str | None:
    parsed = []
    for value in values:
        if not value:
            continue
        try:
            parsed.append((datetime.fromisoformat(value.replace("Z", "+00:00")), value))
        except ValueError:
            continue
    return max(parsed, key=lambda item: item[0])[1] if parsed else None


def _min_timestamp(values: list[str | None]) -> str | None:
    parsed = []
    for value in values:
        if not value:
            continue
        try:
            parsed.append((datetime.fromisoformat(value.replace("Z", "+00:00")), value))
        except ValueError:
            continue
    return min(parsed, key=lambda item: item[0])[1] if parsed else None


def _collect_source_timestamps(context: dict[str, Any]) -> tuple[dict[str, str | None], list[str]]:
    timestamps: dict[str, str | None] = {}
    required: list[str] = []
    explicit = context.get("source_timestamps") or {}
    explicit_range = context.get("source_time_range") or {}
    if isinstance(explicit_range, dict):
        explicit = {**(explicit_range.get("source_timestamps") or {}), **explicit}
    # Only snapshots copied into the deterministic projection are eligible to
    # define model-input time.  Sporttery/trade/Polymarket report evidence is
    # deliberately excluded unless the projection explicitly consumes it.
    for name in ("nowscore", "500_deep"):
        source = (context.get("source_snapshots") or {}).get(name) or {}
        snapshots = source.get("snapshots") if isinstance(source, dict) else []
        if not isinstance(snapshots, list) or not snapshots or not isinstance(snapshots[0], dict):
            continue
        required.append(str(name))
        timestamps[str(name)] = _timestamp(explicit.get(name)) or _snapshot_timestamp(snapshots[0])

    def first_snapshot(name: str) -> dict[str, Any]:
        source = (context.get("source_snapshots") or {}).get(name) or {}
        snapshots = source.get("snapshots") if isinstance(source, dict) else []
        return snapshots[0] if isinstance(snapshots, list) and snapshots and isinstance(snapshots[0], dict) else {}

    def has_recent_form(snapshot: dict[str, Any]) -> bool:
        return bool((snapshot.get("shuju") or {}).get("recent_form"))

    def has_valid_market_consensus(snapshot: dict[str, Any]) -> bool:
        rows = (snapshot.get("ouzhi") or {}).get("bookmakers") or []
        for row in rows:
            odds = row.get("spf_current") if isinstance(row, dict) else None
            try:
                prices = [float(odds[key]) for key in ("home", "draw", "away")]
            except (KeyError, TypeError, ValueError):
                continue
            if all(price > 1 for price in prices):
                return True
        return False

    primary = first_snapshot("nowscore")
    fallback = first_snapshot("500_deep")
    deep_form_available = has_recent_form(primary) if primary else has_recent_form(fallback)
    if primary and not has_recent_form(primary):
        deep_form_available = has_recent_form(fallback)
    prematch = context.get("prematch_fundamentals") or {}
    if not deep_form_available and isinstance(prematch, dict) and prematch.get("recent_form"):
        required.append("prematch_fundamentals")
        timestamps["prematch_fundamentals"] = _timestamp(
            explicit.get("prematch_fundamentals")
            or prematch.get("captured_at")
            or prematch.get("source_captured_at")
            or prematch.get("fetched_at")
            or prematch.get("source_timestamp")
        )

    # The deterministic core falls back to the official three-way baseline
    # only when the deep snapshot has no usable current SPF consensus.  The
    # workspace odds have no implicit capture time, so absent explicit
    # metadata this deliberately blocks formal eligibility.
    market_available = has_valid_market_consensus(primary) if primary else has_valid_market_consensus(fallback)
    if primary and not (primary.get("ouzhi") or {}).get("bookmakers"):
        market_available = has_valid_market_consensus(fallback)
    official = context.get("official_market_baseline") or {}
    if not market_available and isinstance(official, dict) and official.get("fair_probabilities"):
        required.append("official_market_baseline")
        timestamps["official_market_baseline"] = _timestamp(
            explicit.get("official_market_baseline")
            or official.get("captured_at")
            or official.get("market_snapshot_at")
            or official.get("source_timestamp")
        )
    checkpoint = context.get("checkpoint_features") or {}
    if int(checkpoint.get("snapshot_count") or 0) > 0:
        required.append("checkpoint_features")
        timestamps["checkpoint_features"] = _timestamp(
            explicit.get("checkpoint_features") or checkpoint.get("latest_captured_at")
        )
    return timestamps, required


def build_deterministic_model_input_snapshot(
    context: dict[str, Any],
    *,
    manifest_ref: str | None = None,
    prediction_created_at: str | None = None,
    repository_root: Path = ROOT,
) -> dict[str, Any]:
    projection = build_deterministic_model_input_projection(context)
    canonical_hash = _sha256_value(projection)
    source_timestamps, required = _collect_source_timestamps(context)
    known = [source_timestamps.get(key) for key in required]
    complete = bool(required) and all(known)
    source_cutoff = _max_timestamp(known) if complete else None
    checkpoint_timestamp = source_timestamps.get("checkpoint_features")
    market_values = [
        source_timestamps.get(key)
        for key in ("nowscore", "500_deep")
        if source_timestamps.get(key)
    ]
    if checkpoint_timestamp:
        market_values.append(checkpoint_timestamp)
    # BASE v0 may use the explicitly captured official Sporttery SPF as its
    # only market input.  It is a legitimate market snapshot even though it
    # is not represented as a multi-bookmaker ``source_snapshots`` row.
    official_market_timestamp = source_timestamps.get("official_market_baseline")
    if not market_values and official_market_timestamp:
        market_values.append(official_market_timestamp)
    market_snapshot = _max_timestamp(market_values) if market_values and all(
        source_timestamps.get(key) for key in required if key != "checkpoint_features"
    ) else None
    source_time_range = {
        "earliest_source_at": _min_timestamp(known) if complete else None,
        "latest_source_at": _max_timestamp(known) if complete else None,
        "market_snapshot_at": market_snapshot,
        "source_timestamps": source_timestamps,
    }
    source_refs = _collect_source_refs(context.get("source_snapshots") or {})
    source_refs.extend(str(value) for value in (context.get("model_input_source_refs") or []) if value)
    source_refs = list(dict.fromkeys(source_refs))
    created = _timestamp(prediction_created_at or context.get("prediction_created_at"))
    snapshot = {
        "contract_version": MODEL_INPUT_CONTRACT_VERSION,
        "snapshot_contract_version": SNAPSHOT_CONTRACT_VERSION,
        "snapshot_id": "FBOS-SNAPSHOT-" + canonical_hash[:24],
        "manifest_ref": manifest_ref or context.get("model_input_manifest_ref"),
        "source_refs": source_refs,
        "source_hashes": _source_hashes(source_refs, repository_root),
        "captured_at": source_cutoff,
        "prediction_created_at": created,
        "model_input_as_of_at": source_cutoff,
        "source_cutoff_at": source_cutoff,
        "market_snapshot_at": market_snapshot,
        "odds_snapshot_at": market_snapshot,
        "source_time_range": source_time_range,
        "canonical_model_input_sha256": canonical_hash,
        "canonical_input_sha256": canonical_hash,
        "snapshot_ref": f"data/model_governance/input_snapshots/{canonical_hash}.json",
        "projection": projection,
    }
    return snapshot


def replay_deterministic_model_from_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Replay the Champion using only a frozen deterministic input projection."""
    projection = snapshot.get("projection") if isinstance(snapshot, dict) else None
    if projection is None and isinstance(snapshot, dict):
        projection = snapshot.get("input")
    if not isinstance(projection, dict):
        raise ValueError("deterministic model snapshot is missing its projection")
    from automatic_model_core import build_automatic_model
    return build_automatic_model(projection)


def _deterministic_input(payload: dict[str, Any], input_payload: Any) -> Any:
    if isinstance(input_payload, dict) and isinstance(input_payload.get("projection"), dict):
        return _strip_narrative(input_payload["projection"])
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
            if lowered in {"file", "path", "source_path", "snapshot_ref", "source_ref", "source_url", "url"} and isinstance(child, str):
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
    if isinstance(input_payload, dict) and isinstance(input_payload.get("projection"), dict):
        supplied = {
            key: deepcopy(value)
            for key, value in input_payload.items()
            if key != "projection"
        }
        supplied_hash = supplied.get("canonical_model_input_sha256") or supplied.get("canonical_input_sha256")
        if supplied_hash and supplied_hash != input_hash:
            raise ValueError("model input snapshot hash does not match its projection")
        supplied.update({
            "snapshot_id": supplied.get("snapshot_id") or "FBOS-SNAPSHOT-" + input_hash[:24],
            "canonical_model_input_sha256": input_hash,
            "canonical_input_sha256": input_hash,
            "snapshot_ref": supplied.get("snapshot_ref") or f"data/model_governance/input_snapshots/{input_hash}.json",
            "source_refs": list(supplied.get("source_refs") or []),
            "source_hashes": dict(supplied.get("source_hashes") or {}),
        })
        return supplied, canonical_input
    source_refs = _collect_source_refs(input_payload) if input_payload is not None else []
    snapshot_id = "FBOS-SNAPSHOT-" + input_hash[:24]
    metadata = {
        "snapshot_id": snapshot_id,
        "manifest_ref": _manifest_ref(input_payload),
        "source_refs": source_refs,
        "source_hashes": _source_hashes(source_refs, repository_root),
        "captured_at": source_cutoff_at,
        "contract_version": "legacy_report_fallback",
        "snapshot_contract_version": SNAPSHOT_CONTRACT_VERSION,
        "canonical_input_sha256": input_hash,
        "canonical_model_input_sha256": input_hash,
        "snapshot_ref": f"data/model_governance/input_snapshots/{input_hash}.json",
    }
    return metadata, canonical_input


def _calibration_metadata(config: dict[str, Any], repository_root: Path) -> dict[str, Any]:
    reference = (
        config.get("champion", {}).get("calibration_artifact")
        or config.get("versions", {}).get("calibration_artifact")
        or DEFAULT_CALIBRATION_ARTIFACT
    )
    path = Path(reference)
    if not path.is_absolute():
        path = repository_root / path
    artifact_hash = sha256_file(path) if path.is_file() else None
    version = None
    artifact: dict[str, Any] = {}
    if path.is_file():
        try:
            loaded = _load_json(path)
            if isinstance(loaded, dict):
                artifact = loaded
                version = artifact.get("calibration_version") or artifact.get("schema_version") or artifact.get("generated_at")
        except (OSError, json.JSONDecodeError):
            pass
    effective = effective_calibration_projection(artifact)
    effective_fingerprint = _sha256_value(effective)
    return {
        "reference": str(reference),
        "version": version,
        "calibration_artifact_sha256": artifact_hash,
        "effective_calibration_projection": effective,
        "effective_calibration_fingerprint": effective_fingerprint,
        # Compatibility alias: this is no longer the raw artifact hash.
        "calibration_fingerprint": effective_fingerprint,
    }


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
    automation = payload.get("automation") or {}
    supplied_model_snapshot = automation.get("model_input_snapshot")
    effective_input_payload = input_payload if input_payload is not None else supplied_model_snapshot
    has_model_snapshot = isinstance(effective_input_payload, dict) and isinstance(
        effective_input_payload.get("projection"), dict
    )
    input_snapshot, canonical_input = _build_input_snapshot(
        payload,
        effective_input_payload,
        repository_root=repository_root,
        source_cutoff_at=None,
        created_at=report.get("analysis_timestamp"),
    )
    input_hash = input_snapshot["canonical_input_sha256"]
    prediction_created_at = input_snapshot.get("prediction_created_at") if has_model_snapshot else None
    prediction_created_at = prediction_created_at or report.get("prediction_created_at") or created_at
    if has_model_snapshot:
        source_cutoff = input_snapshot.get("source_cutoff_at")
        odds_snapshot = input_snapshot.get("market_snapshot_at") or input_snapshot.get("odds_snapshot_at")
    else:
        # A report-only fallback cannot prove what the model actually saw.
        source_cutoff = None
        odds_snapshot = None
    created_at = prediction_created_at
    lineup_status = _lineup_status(payload, [str(item) for item in (payload.get("data_quality") or {}).get("missing") or []])
    structural_missing: list[str] = []
    if not isinstance(probabilities, dict) or any(
        _number(probabilities.get(key)) is None for key in ("home", "draw", "away")
    ):
        structural_missing.append("model.probabilities")
    for field, value in (
        ("prediction_created_at", prediction_created_at),
        ("kickoff_at", kickoff),
        ("source_cutoff_at", source_cutoff),
        ("market_snapshot_at", odds_snapshot),
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
    if not has_model_snapshot:
        structural_missing.append("model_input_snapshot")
    if odds_snapshot in (None, ""):
        structural_missing.append("odds_snapshot_at")
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
    source_fingerprint = model_source_fingerprint(repository_root)
    prompt_affects_prediction = False
    if role == "challenger":
        for challenger in config.get("challengers") or []:
            if isinstance(challenger, dict) and str(challenger.get("id") or challenger.get("challenger_id") or "") == str(challenger_id):
                prompt_affects_prediction = bool(challenger.get("prompt_affects_prediction"))
                break
    model_run_identity = {
        "model_role": role,
        "model_family": model_family,
        "model_core_version": model_core_version,
        "release_version": release_version,
        "feature_version": versions.get("feature_version"),
        "data_pipeline_version": versions.get("data_pipeline_version"),
        "effective_calibration_fingerprint": calibration.get("effective_calibration_fingerprint"),
        "calibration_fingerprint": calibration.get("effective_calibration_fingerprint"),
        "model_source_fingerprint": source_fingerprint["fingerprint"],
        "challenger_id": challenger_id,
        "prompt_affects_prediction": prompt_affects_prediction,
    }
    if prompt_affects_prediction:
        model_run_identity["prompt_version"] = prompt_version
    model_run_fingerprint = _sha256_value(model_run_identity)
    checkpoint_metadata = _checkpoint_metadata(payload)
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
        "prediction_created_at": prediction_created_at,
        "kickoff_at": kickoff,
        "source_cutoff_at": source_cutoff,
        "odds_snapshot_at": odds_snapshot,
        "market_snapshot_at": odds_snapshot,
        "model_input_as_of_at": input_snapshot.get("model_input_as_of_at"),
        "source_time_range": input_snapshot.get("source_time_range") or {},
        "repository_commit_sha": commit,
        "calibration_artifact_sha256": calibration.get("calibration_artifact_sha256"),
        "effective_calibration_fingerprint": calibration.get("effective_calibration_fingerprint"),
        # Compatibility alias: consumers must treat this as the effective
        # calibration identity, never as the complete artifact hash.
        "calibration_fingerprint": calibration.get("effective_calibration_fingerprint"),
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
        "canonical_model_input_sha256": input_snapshot.get("canonical_model_input_sha256") or input_hash,
        "model_input_snapshot_ref": input_snapshot.get("snapshot_ref"),
        "input_snapshot": input_snapshot,
        # These fields are benchmark/audit metadata only.  They are excluded
        # from prediction_content_hash and do not participate in Champion math.
        "checkpoint_stage": checkpoint_metadata["stage"],
        "checkpoint_target_at": checkpoint_metadata["target_at"],
        "checkpoint_captured_at": checkpoint_metadata["captured_at"],
        "minutes_to_kickoff_at_capture": checkpoint_metadata["minutes_to_kickoff_at_capture"],
        "checkpoint_metadata": checkpoint_metadata,
        "match_identity": match_identity,
        "snapshot_identity": snapshot_identity,
        "model_run_identity": model_run_identity,
        "model_run_fingerprint": model_run_fingerprint,
        "model_source_fingerprint": source_fingerprint["fingerprint"],
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
            # Preserve already-computed Champion distribution outputs for
            # post-match diagnostics; this does not feed the Champion math.
            "expected_goals": deepcopy(model.get("expected_goals")),
            "btts": deepcopy(model.get("btts")),
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
    record["prediction_sha256"] = prediction_content_hash(record)
    return record


def _validate_record(record: dict[str, Any]) -> None:
    missing = [key for key in REQUIRED_RECORD_FIELDS if key not in record]
    if missing:
        raise ValueError("frozen prediction missing fields: " + ", ".join(missing))
    forbidden = sorted(_nested_postmatch_fields(record))
    if forbidden:
        raise ValueError("postmatch fields are not allowed in a frozen prediction: " + ", ".join(forbidden))
    if record["prediction_sha256"] != prediction_content_hash(record):
        raise ValueError("prediction_sha256 does not match frozen content")
    snapshot = record.get("input_snapshot") or {}
    if snapshot.get("canonical_input_sha256") != record.get("input_sha256"):
        raise ValueError("input snapshot hash does not match input_sha256")
    if snapshot.get("canonical_model_input_sha256") != record.get("canonical_model_input_sha256"):
        raise ValueError("input snapshot hash does not match canonical_model_input_sha256")
    if record.get("model_run_identity", {}).get("model_source_fingerprint") != record.get("model_source_fingerprint"):
        raise ValueError("model source fingerprint does not match model run identity")
    if record.get("model_run_identity", {}).get("effective_calibration_fingerprint") != record.get(
        "effective_calibration_fingerprint"
    ):
        raise ValueError("effective calibration fingerprint does not match model run identity")
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
    if snapshot.get("canonical_model_input_sha256") != record.get("canonical_model_input_sha256"):
        raise ValueError("input snapshot canonical hash does not match prediction record")
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
        if existing.get("snapshot_id") != record["input_snapshot"].get("snapshot_id") or existing.get("input") != content:
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
        if existing.get("prediction_sha256") != record.get("prediction_sha256"):
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
    if review.get("model_source_fingerprint") != record.get("model_source_fingerprint"):
        return {"status": "model_source_fingerprint_mismatch", "formal_eligible": False, "record": record}
    if review.get("canonical_model_input_sha256") != record.get("canonical_model_input_sha256"):
        return {"status": "input_snapshot_hash_mismatch", "formal_eligible": False, "record": record}
    required_match_fields = (
        "source_cutoff_at", "market_snapshot_at", "repository_commit_sha",
    )
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
    source_fingerprint = model_source_fingerprint(ROOT)
    governance_fingerprint = governance_source_fingerprint(ROOT)
    calibration = _calibration_metadata(config, ROOT)
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
        "model_source_fingerprint": source_fingerprint["fingerprint"],
        "governance_source_fingerprint": governance_fingerprint["fingerprint"],
        "calibration_artifact_sha256": calibration.get("calibration_artifact_sha256"),
        "effective_calibration_fingerprint": calibration.get("effective_calibration_fingerprint"),
        "canonical_model_input_contract_version": config["versions"].get("canonical_model_input_contract_version"),
        "snapshot_contract_version": config["versions"].get("snapshot_contract_version"),
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
        "model_source_fingerprint": model_source_fingerprint(ROOT),
        "governance_source_fingerprint": governance_source_fingerprint(ROOT),
        "calibration_artifact_sha256": _calibration_metadata(config, ROOT).get("calibration_artifact_sha256"),
        "effective_calibration_fingerprint": _calibration_metadata(config, ROOT).get("effective_calibration_fingerprint"),
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
