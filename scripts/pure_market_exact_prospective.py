#!/usr/bin/env python3
"""Future-only immutable evidence lane for the pure #189 Market score control."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
from statistics import fmean
from typing import Any, Callable, Iterable, Mapping

from evaluation_kernel import (
    evaluate_prediction_common,
    is_verified_result_artifact,
    normalize_verified_result,
    ranked_probability_score,
)
from market_engine import (
    PURE_MARKET_EXACT_LAMBDA_ITERATIONS,
    PURE_MARKET_EXACT_LAMBDA_LOWER,
    PURE_MARKET_EXACT_LAMBDA_UPPER,
    PURE_MARKET_EXACT_MAX_GOALS_PER_TEAM,
    PURE_MARKET_EXACT_SHARE_ITERATIONS,
    PURE_MARKET_EXACT_SHARE_LOWER,
    PURE_MARKET_EXACT_SHARE_UPPER,
    PURE_MARKET_EXACT_VERSION,
    _canonical_provider,
    build_pure_market_exact_projection,
)
from model_governance import load_frozen_prediction, load_input_snapshot
from prematch_versioning import _identity, _parse_timestamp, select_latest_legal_prematch


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RECORD_ROOT = ROOT / "data" / "model_governance" / "predictions"
DEFAULT_INPUT_SNAPSHOT_ROOT = ROOT / "data" / "model_governance" / "input_snapshots"
DEFAULT_OUTPUT_ROOT = ROOT / "data" / "prediction_quality" / PURE_MARKET_EXACT_VERSION
DEFAULT_RESULT_ROOT = ROOT / "data" / "postmatch_automation" / "results"
PREDICTION_DIRNAME = "predictions"
SETTLEMENT_DIRNAME = "settlements"
INDEX_FILENAME = "latest_index.json"
SETTLEMENT_SUMMARY_FILENAME = "settlement_summary.json"
PREDICTION_SCHEMA_VERSION = "pure_market_exact_prospective.prediction.v1"
INDEX_SCHEMA_VERSION = "pure_market_exact_prospective.index.v1"
SETTLEMENT_SCHEMA_VERSION = "pure_market_exact_prospective.settlement.v1"
RESULT_SCOPE = "regulation_90m_plus_stoppage"
ALLOWED_MARKET_PROVIDERS = frozenset({"nowscore", "500_deep"})
EPSILON = 1e-12
POSTMATCH_FIELDS = frozenset({
    "actual_score", "actual_outcome", "result", "settlement", "verified_at",
    "settlement_status", "postmatch_evidence",
})


class LaneConflictError(RuntimeError):
    """Raised when an immutable evidence file would change content."""


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _parse_required_timestamp(value: Any, field: str) -> datetime:
    parsed = _parse_timestamp(value)
    if parsed is None:
        raise ValueError(f"{field.upper()}_TIMESTAMP_INVALID")
    return parsed


def _identity_key(record: Mapping[str, Any]) -> str:
    identity = _identity(dict(record))
    for key in ("match_key", "match_id"):
        value = str(identity.get(key) or "").strip()
        if value:
            return value
    return "|".join(str(identity.get(key) or "").strip().casefold() for key in ("home", "away", "kickoff_at"))


def _identity_display(record: Mapping[str, Any]) -> dict[str, Any]:
    identity = _identity(dict(record))
    return {
        "match_key": str(identity.get("match_key") or "") or None,
        "match_id": str(identity.get("match_id") or "") or None,
        "home": identity.get("home"),
        "away": identity.get("away"),
        "kickoff_at": identity.get("kickoff_at"),
    }


def _contains_postmatch_field(value: Any) -> bool:
    if isinstance(value, Mapping):
        return any(key in POSTMATCH_FIELDS or _contains_postmatch_field(child) for key, child in value.items())
    if isinstance(value, list):
        return any(_contains_postmatch_field(child) for child in value)
    return False


def _prediction_content(record: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in record.items()
        if key not in {"prediction_digest", "prediction_sha256"}
    }


def prediction_digest(record: Mapping[str, Any]) -> str:
    return _sha256_json(_prediction_content(record))


def settlement_digest(settlement: Mapping[str, Any]) -> str:
    return _sha256_json({key: value for key, value in settlement.items() if key != "settlement_digest"})


def load_frozen_records(record_root: Path = DEFAULT_RECORD_ROOT) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    rejected = 0
    paths = sorted(record_root.glob("*.json"))
    for path in paths:
        record = load_frozen_prediction(path.stem, record_root)
        if record is None:
            rejected += 1
            continue
        rows.append(record)
    return rows, {
        "files_seen": len(paths),
        "reader_accepted_rows": len(rows),
        "reader_rejected_rows": rejected,
    }


def select_unique_legal_records(records: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Select one final legal Champion version per match without result access."""
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    source_rows = [dict(record) for record in records if isinstance(record, Mapping)]
    for record in source_rows:
        groups[_identity_key(record)].append(record)

    selected: list[dict[str, Any]] = []
    decisions: list[dict[str, Any]] = []
    reason_counts: Counter[str] = Counter()
    for key in sorted(groups):
        group = groups[key]
        expected = _identity(group[0])
        selection = select_latest_legal_prematch(group, identity=expected)
        reason = str(selection.get("reason") or selection.get("status") or "UNKNOWN")
        reason_counts[reason] += 1
        chosen = selection.get("selected_record")
        if isinstance(chosen, dict):
            selected.append(dict(chosen))
        decisions.append({
            "match_key": key,
            "raw_record_count": len(group),
            "status": selection.get("status"),
            "reason": reason,
            "selected_prediction_id": selection.get("selected_prediction_id"),
            "superseded_count": int(selection.get("superseded_count") or 0),
        })
    selected.sort(key=_identity_key)
    return {
        "raw_reader_rows": len(source_rows),
        "group_count": len(groups),
        "selected_records": selected,
        "groups": decisions,
        "selection_reason_counts": dict(sorted(reason_counts.items())),
        "postmatch_values_used_for_selection": False,
    }


def _source_snapshot_document(snapshot: Mapping[str, Any]) -> Mapping[str, Any]:
    nested = snapshot.get("input")
    return nested if isinstance(nested, Mapping) else snapshot


def select_legal_market_snapshot(
    record: Mapping[str, Any], snapshot: Mapping[str, Any] | None
) -> dict[str, Any]:
    """Select the latest authorized frozen source snapshot at or before cutoff."""
    if not isinstance(snapshot, Mapping):
        return {"snapshot": None, "source": None, "captured_at": None, "snapshot_sha256": None, "reason": "NO_FROZEN_INPUT_SNAPSHOT"}
    cutoff = _parse_timestamp(record.get("source_cutoff_at"))
    kickoff = _parse_timestamp(_identity(dict(record)).get("kickoff_at"))
    if cutoff is None or kickoff is None or cutoff >= kickoff:
        return {"snapshot": None, "source": None, "captured_at": None, "snapshot_sha256": None, "reason": "UNSAFE_RECORD_CHRONOLOGY"}
    record_market_at = _parse_timestamp(record.get("market_snapshot_at") or record.get("odds_snapshot_at"))
    if record_market_at is not None and record_market_at >= kickoff:
        return {"snapshot": None, "source": None, "captured_at": None, "snapshot_sha256": None, "reason": "UNSAFE_RECORD_CHRONOLOGY"}
    for field in ("captured_at", "source_cutoff_at", "market_snapshot_at", "odds_snapshot_at"):
        captured = _parse_timestamp(snapshot.get(field))
        if captured is not None and captured >= kickoff:
            return {
                "snapshot": None,
                "source": None,
                "captured_at": None,
                "snapshot_sha256": None,
                "reason": "POSTKICKOFF_HISTORICAL_RECOVERY_BLOCKED",
            }
        if captured is not None and captured > cutoff:
            return {
                "snapshot": None,
                "source": None,
                "captured_at": None,
                "snapshot_sha256": None,
                "reason": "POST_CUTOFF_HISTORICAL_RECOVERY_BLOCKED",
            }
    snapshot_cutoff = _parse_timestamp(snapshot.get("source_cutoff_at"))
    if snapshot_cutoff is not None and snapshot_cutoff != cutoff:
        return {
            "snapshot": None,
            "source": None,
            "captured_at": None,
            "snapshot_sha256": None,
            "reason": "FROZEN_SNAPSHOT_CUTOFF_MISMATCH",
        }
    source_data = _source_snapshot_document(snapshot)
    sources = source_data.get("source_snapshots")
    if not isinstance(sources, Mapping) or not sources:
        return {"snapshot": None, "source": None, "captured_at": None, "snapshot_sha256": None, "reason": "NO_FROZEN_SOURCE_SNAPSHOT"}

    candidates: list[tuple[datetime, str, dict[str, Any]]] = []
    later_seen = False
    timestamp_missing = False
    unauthorized_seen = False
    for source_name in sorted(sources, key=str):
        canonical_source = _canonical_provider(source_name)
        if canonical_source not in ALLOWED_MARKET_PROVIDERS:
            unauthorized_seen = True
            continue
        source = sources.get(source_name)
        raw_snapshots = source.get("snapshots") if isinstance(source, Mapping) else None
        for raw in raw_snapshots if isinstance(raw_snapshots, list) else []:
            if not isinstance(raw, Mapping):
                continue
            captured = _parse_timestamp(raw.get("fetched_at") or raw.get("captured_at"))
            if captured is None:
                timestamp_missing = True
                continue
            if captured > cutoff or captured >= kickoff:
                later_seen = True
                continue
            candidates.append((captured, str(source_name), dict(raw)))
    if not candidates:
        if later_seen:
            reason = "LATER_OR_CLOSING_QUOTE_BACKFILL_BLOCKED"
        elif timestamp_missing:
            reason = "FROZEN_MARKET_CAPTURE_TIMESTAMP_MISSING"
        elif unauthorized_seen:
            reason = "NO_AUTHORIZED_FROZEN_SOURCE_SNAPSHOT"
        else:
            reason = "NO_LEGAL_PREMATCH_MARKET_SNAPSHOT"
        return {"snapshot": None, "source": None, "captured_at": None, "snapshot_sha256": None, "reason": reason}
    captured, source_name, chosen = max(candidates, key=lambda item: (item[0], item[1]))
    return {
        "snapshot": chosen,
        "source": _canonical_provider(source_name),
        "captured_at": captured.isoformat(),
        "snapshot_sha256": _sha256_json(chosen),
        "reason": None,
    }


def _safe_prediction_id(match_key: str, source_cutoff: Any, input_sha: Any, source_sha: Any) -> str:
    identity = {
        "match_key": match_key,
        "source_cutoff_at": source_cutoff,
        "input_sha256": input_sha,
        "source_snapshot_sha256": source_sha,
        "version": PURE_MARKET_EXACT_VERSION,
    }
    return "PME-" + _sha256_json(identity)[:24]


def build_prospective_prediction(
    record: Mapping[str, Any],
    snapshot: Mapping[str, Any],
    *,
    activation_at: datetime,
    generated_at: datetime,
    repository_commit_sha: str | None = None,
) -> dict[str, Any]:
    """Build one immutable pure-Market record; never writes post-match values."""
    identity = _identity(dict(record))
    kickoff = _parse_required_timestamp(identity.get("kickoff_at"), "kickoff_at")
    activation = _parse_required_timestamp(activation_at, "implementation_activated_at")
    generated = _parse_required_timestamp(generated_at, "generated_at")
    if activation >= kickoff or generated >= kickoff:
        raise ValueError("KICKOFF_BEFORE_LANE_ACTIVATION")
    if activation > generated:
        raise ValueError("IMPLEMENTATION_ACTIVATION_AFTER_GENERATION")

    selected = select_legal_market_snapshot(record, snapshot)
    if selected["reason"]:
        raise ValueError(f"MARKET_SNAPSHOT_{selected['reason']}")
    captured = _parse_required_timestamp(selected["captured_at"], "source_snapshot_captured_at")
    cutoff = _parse_required_timestamp(record.get("source_cutoff_at"), "source_cutoff_at")
    if captured > cutoff or captured > generated:
        raise ValueError("SOURCE_SNAPSHOT_AFTER_FROZEN_PREDICTION")
    projection = build_pure_market_exact_projection(selected["snapshot"])
    if projection.get("status") != "EVALUABLE":
        raise ValueError(f"MARKET_PROJECTION_{projection.get('reason') or 'NOT_EVALUABLE'}")

    input_meta = record.get("input_snapshot") if isinstance(record.get("input_snapshot"), Mapping) else {}
    input_sha = record.get("input_sha256") or input_meta.get("canonical_input_sha256")
    canonical_model_input_sha = record.get("canonical_model_input_sha256") or input_meta.get("canonical_model_input_sha256")
    snapshot_id = input_meta.get("snapshot_id") or snapshot.get("snapshot_id")
    canonical_match_identity = identity.get("match_key") or identity.get("match_id")
    if not canonical_match_identity:
        raise ValueError("CANONICAL_MATCH_IDENTITY_REQUIRED")
    if not input_sha or not canonical_model_input_sha or not snapshot_id:
        raise ValueError("SOURCE_INPUT_DIGESTS_REQUIRED")
    match_key = str(canonical_match_identity)
    prediction_id = _safe_prediction_id(
        match_key,
        record.get("source_cutoff_at"),
        input_sha,
        selected["snapshot_sha256"],
    )
    champion_reference = {
        "prediction_id": record.get("prediction_id"),
        "prediction_sha256": record.get("prediction_sha256"),
        "match_key": match_key,
        "snapshot_id": snapshot_id,
        "source_cutoff_at": record.get("source_cutoff_at"),
        "freeze_created_at": record.get("freeze_created_at"),
        "same_match": True,
        "same_source_cutoff": True,
        "same_horizon_authority": True,
    }
    result: dict[str, Any] = {
        "schema_version": PREDICTION_SCHEMA_VERSION,
        "prediction_id": prediction_id,
        "status": "FROZEN_PROSPECTIVE",
        "model": "pure_market_exact",
        "model_role": "shadow",
        "model_family": PURE_MARKET_EXACT_VERSION,
        "market_policy": projection["market_policy"],
        "score_engine_version": projection["score_engine_version"],
        "source_record_prediction_id": record.get("prediction_id"),
        "source_record_prediction_sha256": record.get("prediction_sha256"),
        "match_key": match_key,
        "match_id": identity.get("match_id"),
        "home": identity.get("home"),
        "away": identity.get("away"),
        "match_identity": _identity_display(record),
        "kickoff_at": identity.get("kickoff_at"),
        "implementation_activated_at": activation.isoformat(),
        "generated_at": generated.isoformat(),
        "frozen_prediction_at": generated.isoformat(),
        "prediction_created_at": generated.isoformat(),
        "source_cutoff_at": record.get("source_cutoff_at"),
        "source_snapshot_captured_at": selected["captured_at"],
        "market_snapshot_at": record.get("market_snapshot_at") or selected["captured_at"],
        "snapshot_identity": {
            "snapshot_id": snapshot_id,
            "source": selected["source"],
            "source_cutoff_at": record.get("source_cutoff_at"),
            "captured_at": selected["captured_at"],
            "selected_source_snapshot_sha256": selected["snapshot_sha256"],
        },
        "source_input_digests": {
            "input_sha256": input_sha,
            "canonical_model_input_sha256": canonical_model_input_sha,
            "source_record_prediction_sha256": record.get("prediction_sha256"),
            "frozen_snapshot_id": snapshot_id,
            "selected_source_snapshot_sha256": selected["snapshot_sha256"],
        },
        "champion_reference": champion_reference,
        "repository_commit_sha": repository_commit_sha,
        "production_enabled": False,
        "serving_enabled": False,
        "user_visible": False,
        "auto_promote": False,
        "promotion_eligible": False,
        "score_matrix_authority": "one_normalized_independent_poisson_matrix",
        "result_scope": RESULT_SCOPE,
        "solver_identity": {
            "version": "market_189.solver.v1",
            "lambda_total": {
                "method": "asian_settlement_bisection",
                "lower": PURE_MARKET_EXACT_LAMBDA_LOWER,
                "upper": PURE_MARKET_EXACT_LAMBDA_UPPER,
                "iterations": PURE_MARKET_EXACT_LAMBDA_ITERATIONS,
            },
            "home_share": {
                "method": "1x2_golden_section",
                "lower": PURE_MARKET_EXACT_SHARE_LOWER,
                "upper": PURE_MARKET_EXACT_SHARE_UPPER,
                "iterations": PURE_MARKET_EXACT_SHARE_ITERATIONS,
            },
            "score_matrix": {
                "method": "independent_poisson",
                "rho": 0.0,
                "max_goals_per_team": PURE_MARKET_EXACT_MAX_GOALS_PER_TEAM,
            },
        },
        **projection,
    }
    result.pop("model", None)
    result["model"] = "pure_market_exact"
    result["prediction_digest"] = prediction_digest(result)
    result["prediction_sha256"] = result["prediction_digest"]
    validate_prospective_prediction(result)
    return result


def validate_prospective_prediction(record: Mapping[str, Any]) -> None:
    required = (
        "prediction_id", "match_key", "kickoff_at", "implementation_activated_at",
        "generated_at", "source_cutoff_at", "prediction_digest", "score_matrix",
        "probabilities", "lambda_home", "lambda_away", "rho",
    )
    missing = [key for key in required if key not in record]
    if missing:
        raise ValueError("PROSPECTIVE_PREDICTION_MISSING_FIELDS:" + ",".join(missing))
    if record.get("schema_version") != PREDICTION_SCHEMA_VERSION:
        raise ValueError("PROSPECTIVE_PREDICTION_SCHEMA_INVALID")
    if record.get("production_enabled") is not False or record.get("serving_enabled") is not False:
        raise ValueError("PROSPECTIVE_PREDICTION_SERVING_MUST_BE_DISABLED")
    if record.get("user_visible") is not False or record.get("auto_promote") is not False:
        raise ValueError("PROSPECTIVE_PREDICTION_POLICY_FLAGS_INVALID")
    if record.get("model_role") != "shadow" or record.get("rho") != 0.0:
        raise ValueError("PROSPECTIVE_PREDICTION_MODEL_POLICY_INVALID")
    if record.get("result_scope") != RESULT_SCOPE:
        raise ValueError("PROSPECTIVE_PREDICTION_RESULT_SCOPE_INVALID")
    if _contains_postmatch_field(record):
        raise ValueError("PROSPECTIVE_PREDICTION_CONTAINS_POSTMATCH_FIELD")
    kickoff = _parse_required_timestamp(record.get("kickoff_at"), "kickoff_at")
    activation = _parse_required_timestamp(record.get("implementation_activated_at"), "implementation_activated_at")
    generated = _parse_required_timestamp(record.get("generated_at"), "generated_at")
    cutoff = _parse_required_timestamp(record.get("source_cutoff_at"), "source_cutoff_at")
    if activation >= kickoff or generated >= kickoff:
        raise ValueError("PROSPECTIVE_PREDICTION_NOT_FUTURE_ONLY")
    if activation > generated or cutoff > generated:
        raise ValueError("PROSPECTIVE_PREDICTION_CHRONOLOGY_INVALID")
    matrix = record.get("score_matrix")
    if not isinstance(matrix, list) or not matrix:
        raise ValueError("PROSPECTIVE_PREDICTION_SCORE_MATRIX_MISSING")
    probabilities = [float(row.get("probability")) for row in matrix if isinstance(row, Mapping) and row.get("probability") is not None]
    if len(probabilities) != len(matrix) or any(not math.isfinite(value) or value < 0 for value in probabilities):
        raise ValueError("PROSPECTIVE_PREDICTION_SCORE_MATRIX_INVALID")
    if abs(sum(probabilities) - 1.0) > 1e-9:
        raise ValueError("PROSPECTIVE_PREDICTION_SCORE_MATRIX_NOT_NORMALIZED")
    digest = record.get("prediction_digest")
    if digest != prediction_digest(record) or record.get("prediction_sha256") != digest:
        raise ValueError("PROSPECTIVE_PREDICTION_DIGEST_MISMATCH")


def _json_file(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def persist_prediction(prediction: Mapping[str, Any], output_root: Path = DEFAULT_OUTPUT_ROOT) -> dict[str, Any]:
    value = dict(prediction)
    validate_prospective_prediction(value)
    output_root = Path(output_root)
    target = output_root / PREDICTION_DIRNAME / f"{value['prediction_id']}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        existing = _json_file(target)
        validate_prospective_prediction(existing)
        stable_fields = {
            "generated_at", "implementation_activated_at", "frozen_prediction_at",
            "prediction_created_at", "repository_commit_sha",
            "prediction_digest", "prediction_sha256",
        }
        existing_stable = {key: item for key, item in existing.items() if key not in stable_fields}
        value_stable = {key: item for key, item in value.items() if key not in stable_fields}
        if canonical_json(existing_stable) != canonical_json(value_stable):
            raise LaneConflictError(f"prediction content conflict: {target}")
        return {"status": "existing", "path": target, "record": existing}
    try:
        with target.open("x", encoding="utf-8") as handle:
            handle.write(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    except FileExistsError:
        return persist_prediction(value, output_root)
    return {"status": "created", "path": target, "record": value}


def load_persisted_predictions(output_root: Path = DEFAULT_OUTPUT_ROOT) -> list[dict[str, Any]]:
    root = Path(output_root) / PREDICTION_DIRNAME
    rows: list[dict[str, Any]] = []
    for path in sorted(root.glob("*.json")) if root.is_dir() else []:
        row = _json_file(path)
        validate_prospective_prediction(row)
        rows.append(row)
    return rows


def _prediction_index_entry(record: Mapping[str, Any], settlement_ids: set[str]) -> dict[str, Any]:
    prediction_id = str(record["prediction_id"])
    return {
        "prediction_id": prediction_id,
        "match_key": record.get("match_key"),
        "kickoff_at": record.get("kickoff_at"),
        "implementation_activated_at": record.get("implementation_activated_at"),
        "generated_at": record.get("generated_at"),
        "source_cutoff_at": record.get("source_cutoff_at"),
        "status": record.get("status"),
        "prediction_path": f"{PREDICTION_DIRNAME}/{prediction_id}.json",
        "settlement_path": (
            f"{SETTLEMENT_DIRNAME}/{prediction_id}.json"
            if prediction_id in settlement_ids else None
        ),
    }


def build_compact_index(
    predictions: Iterable[Mapping[str, Any]],
    *,
    settlement_ids: set[str] | None = None,
    refreshed_at: str | None = None,
) -> dict[str, Any]:
    settlement_ids = settlement_ids or set()
    rows = sorted(
        [_prediction_index_entry(row, settlement_ids) for row in predictions],
        key=lambda row: (str(row.get("match_key") or ""), str(row.get("generated_at") or ""), str(row["prediction_id"])),
    )
    latest_by_match: dict[str, str] = {}
    for row in rows:
        latest_by_match[str(row.get("match_key") or "")] = str(row["prediction_id"])
    index: dict[str, Any] = {
        "schema_version": INDEX_SCHEMA_VERSION,
        "prediction_namespace": PURE_MARKET_EXACT_VERSION,
        "observation_unit": "one football match = one unique match_key",
        "prediction_count": len(rows),
        "settled_prediction_count": len(settlement_ids.intersection({str(row["prediction_id"]) for row in rows})),
        "latest_by_match": latest_by_match,
        "predictions": rows,
    }
    if refreshed_at is not None:
        index["refreshed_at"] = refreshed_at
    return index


def _write_derived_if_changed(
    path: Path, value: Mapping[str, Any], *, ignored_keys: frozenset[str] = frozenset()
) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        existing = _json_file(path)
        existing_stable = {key: item for key, item in existing.items() if key not in ignored_keys}
        value_stable = {key: item for key, item in value.items() if key not in ignored_keys}
        if canonical_json(existing_stable) == canonical_json(value_stable):
            return False
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)
    return True


def _result_identity_key(result: Mapping[str, Any]) -> str:
    for key in ("match_key", "canonical_match_id", "match_id"):
        value = str(result.get(key) or "").strip()
        if value:
            return value
    return "|".join(str(result.get(key) or "").strip().casefold() for key in ("home", "away", "kickoff_local"))


def discover_verified_results(result_root: Path = DEFAULT_RESULT_ROOT) -> dict[str, list[dict[str, Any]]]:
    results: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for path in sorted(Path(result_root).glob("*.json")) if Path(result_root).is_dir() else []:
        try:
            payload = _json_file(path)
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        if not is_verified_result_artifact(payload):
            continue
        results[_result_identity_key(payload)].append({"path": path, "payload": payload})
    return results


def _same_identity(record: Mapping[str, Any], result: Mapping[str, Any]) -> bool:
    if _identity_key(record) == _result_identity_key(result):
        return True
    identity = _identity(dict(record))
    return (
        str(identity.get("home") or "").strip().casefold() == str(result.get("home") or "").strip().casefold()
        and str(identity.get("away") or "").strip().casefold() == str(result.get("away") or "").strip().casefold()
        and _parse_timestamp(identity.get("kickoff_at")) == _parse_timestamp(result.get("kickoff_local"))
    )


def _result_verified_at(result: Mapping[str, Any]) -> datetime | None:
    return _parse_timestamp(result.get("result_verified_at") or result.get("verified_at"))


def _result_signature(normalized: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        normalized.get("actual_score"),
        normalized.get("scope"),
        normalized.get("home_score_90m"),
        normalized.get("away_score_90m"),
    )


def _find_verified_result(
    prediction: Mapping[str, Any], result_map: Mapping[str, list[dict[str, Any]]]
) -> tuple[dict[str, Any] | None, str | None]:
    candidates = list(result_map.get(_identity_key(prediction), []))
    if not candidates:
        candidates = [
            item
            for items in result_map.values()
            for item in items
            if _same_identity(prediction, item["payload"])
        ]
    if not candidates:
        return None, "RESULT_NOT_AVAILABLE"
    kickoff = _parse_timestamp(prediction.get("kickoff_at"))
    normalized: list[tuple[tuple[Any, ...], dict[str, Any], dict[str, Any]]] = []
    pre_kickoff = False
    for item in candidates:
        verified_at = _result_verified_at(item["payload"])
        if kickoff is not None and (verified_at is None or verified_at <= kickoff):
            pre_kickoff = True
            continue
        try:
            value = normalize_verified_result(item["payload"])
        except ValueError:
            continue
        normalized.append((_result_signature(value), value, item))
    if not normalized:
        return None, "RESULT_TIME_UNVERIFIED" if pre_kickoff else "RESULT_NOT_AVAILABLE"
    signatures = {signature for signature, _, _ in normalized}
    if len(signatures) > 1:
        return None, "DUPLICATE_RESULT_CONFLICT"
    normalized.sort(key=lambda item: _result_verified_at(item[2]["payload"]) or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    return normalized[0][2], None


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def _total_over_probability(prediction: Mapping[str, Any], line: str = "2.5") -> float | None:
    totals = ((prediction.get("derived_markets") or {}).get("totals") or {})
    row = totals.get(line)
    if not isinstance(row, Mapping):
        return None
    over = row.get("over")
    if not isinstance(over, Mapping):
        return None
    return _number(over.get("win_probability"))


def settle_prediction(
    prediction: Mapping[str, Any],
    result: Mapping[str, Any],
    *,
    result_path: Path | None = None,
    settled_at: datetime | None = None,
) -> dict[str, Any]:
    """Evaluate one immutable prediction against one verified regulation result."""
    value = dict(prediction)
    validate_prospective_prediction(value)
    normalized = normalize_verified_result(result)
    kickoff = _parse_required_timestamp(value.get("kickoff_at"), "kickoff_at")
    verified_at = _result_verified_at(normalized)
    if verified_at is None or verified_at <= kickoff:
        raise ValueError("RESULT_TIME_UNVERIFIED")
    common = evaluate_prediction_common(
        value,
        normalized,
        include_distribution=True,
        include_output_probabilities=False,
    )
    actual_over = normalized["home_score_90m"] + normalized["away_score_90m"] > 2
    actual_btts = normalized["home_score_90m"] > 0 and normalized["away_score_90m"] > 0
    over_probability = _total_over_probability(value)
    btts_probability = _number((value.get("btts") or {}).get("yes")) if isinstance(value.get("btts"), Mapping) else None
    metrics = {
        "exact_nll": common.get("actual_score_nll"),
        "exact_nll_status": "PURE_MARKET_EXACT_PROSPECTIVE_FROZEN" if common.get("actual_score_nll") is not None else common.get("actual_score_nll_status"),
        "exact_top1": common.get("exact_score_top1"),
        "exact_top3": common.get("exact_score_top3"),
        "exact_top5": common.get("exact_score_top5"),
        "actual_score_rank": common.get("actual_score_rank"),
        "actual_score_probability": common.get("actual_score_probability"),
        "ft_1x2_log_loss": common.get("log_loss_1x2"),
        "ft_1x2_brier": common.get("brier_score_1x2"),
        "ft_1x2_rps": ranked_probability_score(common.get("outcome_probabilities"), common.get("actual_outcome")),
        "ft_1x2_outcome_probabilities": common.get("outcome_probabilities"),
        "ou_2_5_probability": over_probability,
        "ou_2_5_brier": (over_probability - float(actual_over)) ** 2 if over_probability is not None else None,
        "btts_probability": btts_probability,
        "btts_brier": (btts_probability - float(actual_btts)) ** 2 if btts_probability is not None else None,
        "lambda_home_residual": common.get("lambda_home_residual"),
        "lambda_away_residual": common.get("lambda_away_residual"),
        "lambda_total_residual": common.get("total_goals_residual"),
        "lambda_home_absolute_error": common.get("home_goal_absolute_error"),
        "lambda_away_absolute_error": common.get("away_goal_absolute_error"),
        "lambda_total_absolute_error": common.get("total_goal_absolute_error"),
        "score_1_1_top1": common.get("top1_1_1"),
    }
    evaluated_at = settled_at or datetime.now(timezone.utc)
    if evaluated_at.tzinfo is None:
        raise ValueError("SETTLED_AT_TIMESTAMP_INVALID")
    return {
        "schema_version": SETTLEMENT_SCHEMA_VERSION,
        "settlement_status": "SETTLED",
        "prediction_id": value["prediction_id"],
        "match_key": value["match_key"],
        "kickoff_at": value["kickoff_at"],
        "prediction_generated_at": value.get("generated_at"),
        "source_cutoff_at": value.get("source_cutoff_at"),
        "prediction_digest": value["prediction_digest"],
        "result": {
            "path": str(result_path) if result_path is not None else None,
            "result_digest": _sha256_json(normalized),
            "verified_at": verified_at.isoformat(),
            "scope": normalized.get("scope"),
            "actual_score": normalized.get("actual_score"),
        },
        "metrics": metrics,
        "control_pair": value.get("champion_reference"),
        "evaluated_at": evaluated_at.isoformat(),
        "settlement_digest": None,
    }


def persist_settlement(settlement: Mapping[str, Any], output_root: Path = DEFAULT_OUTPUT_ROOT) -> dict[str, Any]:
    value = dict(settlement)
    value["settlement_digest"] = settlement_digest(value)
    target = Path(output_root) / SETTLEMENT_DIRNAME / f"{value['prediction_id']}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        existing = _json_file(target)
        existing_stable = {
            key: item for key, item in existing.items()
            if key not in {"evaluated_at", "settlement_digest"}
        }
        value_stable = {
            key: item for key, item in value.items()
            if key not in {"evaluated_at", "settlement_digest"}
        }
        if canonical_json(existing_stable) != canonical_json(value_stable):
            raise LaneConflictError(f"settlement content conflict: {target}")
        return {"status": "existing", "path": target, "settlement": existing}
    try:
        with target.open("x", encoding="utf-8") as handle:
            handle.write(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    except FileExistsError:
        return persist_settlement(value, output_root)
    return {"status": "created", "path": target, "settlement": value}


def load_persisted_settlements(output_root: Path = DEFAULT_OUTPUT_ROOT) -> list[dict[str, Any]]:
    root = Path(output_root) / SETTLEMENT_DIRNAME
    rows: list[dict[str, Any]] = []
    for path in sorted(root.glob("*.json")) if root.is_dir() else []:
        row = _json_file(path)
        if row.get("settlement_digest") != settlement_digest(row):
            raise ValueError(f"SETTLEMENT_DIGEST_MISMATCH:{path}")
        rows.append(row)
    return rows


SUMMARY_METRICS = (
    "exact_nll", "exact_top1", "exact_top3", "exact_top5", "actual_score_rank",
    "ft_1x2_log_loss", "ft_1x2_brier", "ft_1x2_rps", "ou_2_5_brier", "btts_brier",
    "lambda_home_residual", "lambda_away_residual", "lambda_total_residual",
    "lambda_home_absolute_error", "lambda_away_absolute_error", "lambda_total_absolute_error",
    "score_1_1_top1",
)


def _metric_summary(values: Iterable[Any]) -> dict[str, Any]:
    numbers = [
        float(value)
        for value in values
        if isinstance(value, bool) or _number(value) is not None
    ]
    return {"n": len(numbers), "mean": fmean(numbers) if numbers else None}


def aggregate_settlements(
    settlements: Iterable[Mapping[str, Any]], *, generated_at: datetime | None = None
) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for settlement in settlements:
        if isinstance(settlement, Mapping):
            groups[str(settlement.get("match_key") or "")].append(dict(settlement))
    unique: list[dict[str, Any]] = []
    conflicts: list[str] = []
    for key in sorted(groups):
        rows = groups[key]
        result_signatures = {
            (
                str((row.get("result") or {}).get("actual_score") or ""),
                str((row.get("result") or {}).get("scope") or ""),
            )
            for row in rows
        }
        if len(result_signatures) > 1:
            conflicts.append(key)
            continue
        unique.append(sorted(
            rows,
            key=lambda row: (
                str(row.get("source_cutoff_at") or ""),
                str(row.get("prediction_generated_at") or ""),
                str(row.get("evaluated_at") or ""),
                str(row.get("prediction_id") or ""),
            ),
            reverse=True,
        )[0])
    metrics = {
        name: _metric_summary((row.get("metrics") or {}).get(name) for row in unique)
        for name in SUMMARY_METRICS
    }
    metrics["score_1_1_top1_share"] = metrics.pop("score_1_1_top1")
    return {
        "schema_version": "pure_market_exact_prospective.settlement_summary.v1",
        "prediction_namespace": PURE_MARKET_EXACT_VERSION,
        "result_scope": RESULT_SCOPE,
        "observation_unit": "one football match = one unique match_key",
        "records_seen": sum(len(rows) for rows in groups.values()),
        "unique_match_count": len(unique),
        "duplicate_match_conflicts": conflicts,
        "metrics": metrics,
        "generated_at": (generated_at or datetime.now(timezone.utc)).isoformat(),
    }


def _repository_sha() -> str | None:
    for value in (os.environ.get("GITHUB_SHA"),):
        if value:
            return value
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip() or None
    except (OSError, subprocess.CalledProcessError):
        return None


def run_lane(
    *,
    records: Iterable[Mapping[str, Any]] | None = None,
    snapshot_loader: Callable[[Mapping[str, Any]], Mapping[str, Any]] | None = None,
    record_root: Path = DEFAULT_RECORD_ROOT,
    input_snapshot_root: Path = DEFAULT_INPUT_SNAPSHOT_ROOT,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    result_root: Path = DEFAULT_RESULT_ROOT,
    now: datetime | None = None,
    activation_at: datetime | None = None,
    repository_commit_sha: str | None = None,
    match_key: str | None = None,
) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    activation_at = activation_at or now
    if now.tzinfo is None or activation_at.tzinfo is None:
        raise ValueError("LANE_TIMEZONE_REQUIRED")
    if records is None:
        source_rows, inventory = load_frozen_records(record_root)
    else:
        source_rows = [dict(row) for row in records if isinstance(row, Mapping)]
        inventory = {
            "files_seen": None,
            "reader_accepted_rows": len(source_rows),
            "reader_rejected_rows": 0,
        }
    selection = select_unique_legal_records(source_rows)
    selected = selection["selected_records"]
    if match_key:
        selected = [row for row in selected if _identity_key(row) == match_key]
    loader = snapshot_loader or (lambda row: load_input_snapshot(dict(row), input_snapshot_root))
    created = 0
    existing = 0
    skipped: Counter[str] = Counter()
    conflicts: list[str] = []
    for record in selected:
        identity = _identity(record)
        kickoff = _parse_timestamp(identity.get("kickoff_at"))
        if kickoff is None or kickoff <= activation_at.astimezone(timezone.utc):
            skipped["KICKOFF_BEFORE_LANE_ACTIVATION"] += 1
            continue
        try:
            snapshot = loader(record)
            prediction = build_prospective_prediction(
                record,
                snapshot,
                activation_at=activation_at,
                generated_at=now,
                repository_commit_sha=repository_commit_sha or _repository_sha(),
            )
            persisted = persist_prediction(prediction, output_root)
            if persisted["status"] == "created":
                created += 1
            else:
                existing += 1
        except LaneConflictError as error:
            conflicts.append(str(error))
        except (OSError, ValueError, json.JSONDecodeError) as error:
            reason = str(error).split(":", 1)[0] or type(error).__name__
            skipped[reason] += 1

    predictions = load_persisted_predictions(output_root)
    result_map = discover_verified_results(result_root)
    settlement_created = 0
    settlement_existing = 0
    settlement_skipped: Counter[str] = Counter()
    for prediction in predictions:
        result_item, reason = _find_verified_result(prediction, result_map)
        if result_item is None:
            settlement_skipped[reason or "RESULT_NOT_AVAILABLE"] += 1
            continue
        try:
            settlement = settle_prediction(
                prediction,
                result_item["payload"],
                result_path=result_item["path"],
                settled_at=now,
            )
            persisted = persist_settlement(settlement, output_root)
            if persisted["status"] == "created":
                settlement_created += 1
            else:
                settlement_existing += 1
        except (LaneConflictError, OSError, ValueError, json.JSONDecodeError) as error:
            conflicts.append(str(error))

    settlements = load_persisted_settlements(output_root)
    summary = aggregate_settlements(settlements, generated_at=now)
    settlement_ids = {str(row.get("prediction_id") or "") for row in settlements}
    index = build_compact_index(predictions, settlement_ids=settlement_ids, refreshed_at=now.isoformat())
    index_path = Path(output_root) / INDEX_FILENAME
    summary_path = Path(output_root) / SETTLEMENT_SUMMARY_FILENAME
    # Derived views are allowed to refresh; they never embed prediction distributions.
    _write_derived_if_changed(index_path, index, ignored_keys=frozenset({"refreshed_at"}))
    _write_derived_if_changed(summary_path, summary, ignored_keys=frozenset({"generated_at"}))
    completion_state = "FAIL_CLOSED" if conflicts else (
        "PURE_MARKET_PROSPECTIVE_WIRED" if predictions else "PURE_MARKET_PROSPECTIVE_WIRED_NO_CURRENT_ROWS"
    )
    return {
        "completion_state": completion_state,
        "prediction_namespace": PURE_MARKET_EXACT_VERSION,
        "implementation_activated_at": activation_at.isoformat(),
        "generated_at": now.isoformat(),
        "inventory": inventory,
        "selected_match_count": len(selected),
        "created_prediction_count": created,
        "existing_prediction_count": existing,
        "persisted_prediction_count": len(predictions),
        "skip_reasons": dict(sorted(skipped.items())),
        "settlement_created_count": settlement_created,
        "settlement_existing_count": settlement_existing,
        "settlement_skipped_reasons": dict(sorted(settlement_skipped.items())),
        "persisted_settlement_count": len(settlements),
        "index_path": str(index_path),
        "summary_path": str(summary_path),
        "conflicts": conflicts,
    }


def _parser() -> Any:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--record-root", type=Path, default=DEFAULT_RECORD_ROOT)
    parser.add_argument("--input-snapshot-root", type=Path, default=DEFAULT_INPUT_SNAPSHOT_ROOT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--result-root", type=Path, default=DEFAULT_RESULT_ROOT)
    parser.add_argument("--match-key")
    parser.add_argument("--now")
    parser.add_argument("--activation-at")
    parser.add_argument("--repository-commit-sha")
    parser.add_argument("--smoke", action="store_true", help="run the real future/current lane and emit JSON state")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    now = _parse_required_timestamp(args.now, "now") if args.now else datetime.now(timezone.utc)
    activation = _parse_required_timestamp(args.activation_at, "activation_at") if args.activation_at else now
    outcome = run_lane(
        record_root=args.record_root,
        input_snapshot_root=args.input_snapshot_root,
        output_root=args.output_root,
        result_root=args.result_root,
        now=now,
        activation_at=activation,
        repository_commit_sha=args.repository_commit_sha or _repository_sha(),
        match_key=args.match_key,
    )
    print(json.dumps(outcome, ensure_ascii=False, sort_keys=True, indent=2))
    return 0 if outcome["completion_state"] != "FAIL_CLOSED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
