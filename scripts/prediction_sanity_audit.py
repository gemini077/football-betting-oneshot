#!/usr/bin/env python3
"""Read-only prediction sanity and score-collapse audit.

This module deliberately evaluates already persisted artifacts.  It does not
run a model, fetch data, settle results, or rewrite any production record.
The public helpers are small enough to be used by focused tests and by future
shadow-audit tooling without coupling the audit to the production runner.
"""

from __future__ import annotations

import argparse
import ast
import csv
import hashlib
import json
import math
import os
import shutil
import re
import subprocess
import sys
import tempfile
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from statistics import fmean, median
from typing import Any, Iterable

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - Python 3.8 fallback
    ZoneInfo = None


AUDIT_SCHEMA_VERSION = "1.0"
DEFAULT_CALIBRATION_REVIEW_SAMPLES = 40
SCORE_NLL_TOLERANCE = 1e-6
REPLAY_PROBABILITY_TOLERANCE = 1e-6
REPLAY_SOURCE_COMPONENTS = (
    ("scripts/automatic_model_core.py", None),
    ("scripts/risk_engine.py", None),
    ("scripts/market_contracts.py", None),
    ("scripts/checkpoint_features.py", None),
    ("scripts/prematch_fundamentals.py", None),
    ("scripts/match_identity.py", "canonical_match_id"),
    ("scripts/deepseek_auto_analysis.py", "prune"),
    ("scripts/deepseek_auto_analysis.py", "selected_workspace_match"),
    ("scripts/deepseek_auto_analysis.py", "analysis_context"),
    ("scripts/model_governance.py", "_pick"),
    ("scripts/model_governance.py", "_project_market_snapshot"),
    ("scripts/model_governance.py", "_number"),
    ("scripts/model_governance.py", "effective_calibration_projection"),
    ("scripts/model_governance.py", "build_deterministic_model_input_projection"),
)
SCORE_RE = re.compile(r"^\s*(\d+)\s*[-–—:]\s*(\d+)\s*$")
EXTRA_TIME_TOKENS = ("extra_time", "extratime", "penalty", "shootout", "after_extra")


def _json_load(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return default


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _as_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _as_int(value: Any) -> int | None:
    number = _as_float(value)
    return int(number) if number is not None and number.is_integer() else None


def _score_tuple(value: Any) -> tuple[int, int] | None:
    if isinstance(value, (tuple, list)) and len(value) == 2:
        home, away = _as_int(value[0]), _as_int(value[1])
        return (home, away) if home is not None and away is not None and home >= 0 and away >= 0 else None
    if not isinstance(value, str):
        return None
    match = SCORE_RE.match(value)
    if not match:
        return None
    return int(match.group(1)), int(match.group(2))


def _score_string(value: Any) -> str | None:
    parsed = _score_tuple(value)
    return f"{parsed[0]}-{parsed[1]}" if parsed else None


def _nested_dict(value: Any, *keys: str) -> dict:
    current = value
    for key in keys:
        if not isinstance(current, dict):
            return {}
        current = current.get(key)
    return current if isinstance(current, dict) else {}


def _prediction_payload(record: dict) -> dict:
    """Return the stored prediction sub-object when one exists."""
    for key in ("prediction_output", "prediction"):
        value = record.get(key)
        if isinstance(value, dict):
            return value
    return record


def _probabilities(record: dict) -> dict[str, float]:
    candidates = [
        record.get("fusion_1X2"),
        record.get("probabilities"),
        _prediction_payload(record).get("probabilities"),
        _nested_dict(record, "prediction_output", "probabilities"),
        _nested_dict(record, "prediction", "probabilities"),
    ]
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        values = {
            key: _as_float(candidate.get(key))
            for key in ("home", "draw", "away")
        }
        if all(value is not None for value in values.values()):
            return {key: float(value) for key, value in values.items()}
    return {}


def _score_rows_from_candidate(candidate: Any) -> list[dict]:
    if not isinstance(candidate, list):
        return []
    rows: list[dict] = []
    for index, raw in enumerate(candidate, 1):
        if isinstance(raw, str):
            score = _score_string(raw)
            probability = None
            rank = index
        elif isinstance(raw, dict):
            score = _score_string(raw.get("score") or raw.get("exact_score") or raw.get("value"))
            probability = _as_float(raw.get("probability") or raw.get("p"))
            rank = _as_int(raw.get("rank")) or index
        else:
            continue
        if score is None:
            continue
        rows.append({"score": score, "probability": probability, "rank": rank})
    rows.sort(key=lambda row: (row["rank"], -(row["probability"] or 0.0)))
    return rows


def _score_rows(record: dict) -> list[dict]:
    """Read the frozen stored score ranking without recomputing it."""
    payload = _prediction_payload(record)
    candidates = [
        record.get("score_distribution"),
        record.get("top_scores"),
        record.get("score_matrix"),
        payload.get("score_distribution"),
        payload.get("top_scores"),
        payload.get("score_matrix"),
        _nested_dict(record, "prediction_output", "score_matrix"),
        _nested_dict(record, "prediction", "score_distribution"),
    ]
    for candidate in candidates:
        rows = _score_rows_from_candidate(candidate)
        if rows:
            return rows
    return []


def score_nll_for_record(
    record: dict,
    actual_score: str | None,
    ledger_metrics: dict | None = None,
    *,
    tolerance: float = SCORE_NLL_TOLERANCE,
) -> dict[str, Any]:
    """Return a truthful frozen exact-score NLL result.

    A score outside the frozen candidate distribution is *unavailable*, not a
    probability of zero approximated with an epsilon.  When the settlement
    ledger carries an NLL and the frozen row is present, the two values are
    cross-checked before either is used.
    """
    metrics = ledger_metrics if isinstance(ledger_metrics, dict) else {}
    status = str(metrics.get("actual_score_nll_status") or "").strip()
    ledger_value = _as_float(metrics.get("actual_score_nll"))
    base = {
        "status": "UNAVAILABLE",
        "value": None,
        "reason": None,
        "source": None,
        "frozen_probability": None,
        "ledger_value": ledger_value,
        "reconstructed_value": None,
        "reconstruction_match": None,
        "tolerance": tolerance,
    }

    if status == "UNAVAILABLE_IN_FROZEN_RECORD":
        base["reason"] = status
        return base
    if status and ledger_value is None:
        base["reason"] = status
        return base

    score = _score_string(actual_score)
    frozen_probability = None
    if score:
        frozen_probability = next(
            (
                _as_float(row.get("probability"))
                for row in _score_rows(record)
                if row.get("score") == score and _as_float(row.get("probability")) is not None
            ),
            None,
        )
    base["frozen_probability"] = frozen_probability

    if frozen_probability is not None and frozen_probability > 0:
        reconstructed = -math.log(frozen_probability)
        base["reconstructed_value"] = reconstructed
        if ledger_value is not None:
            matches = abs(ledger_value - reconstructed) <= tolerance
            base["reconstruction_match"] = matches
            if not matches:
                base["status"] = "MISMATCH"
                base["reason"] = "NLL_RECONSTRUCTION_MISMATCH"
                return base
            base["status"] = "AVAILABLE"
            base["value"] = reconstructed
            base["source"] = "LEDGER_CROSS_CHECKED_FROZEN_SCORE_DISTRIBUTION"
            return base
        base["status"] = "AVAILABLE"
        base["value"] = reconstructed
        base["source"] = "FROZEN_SCORE_DISTRIBUTION"
        return base

    # A valid ledger metric is an allowed frozen metric source even when the
    # actual score row was not retained in the frozen top-k projection.  It is
    # never replaced with a fabricated near-zero probability.
    if ledger_value is not None:
        base["status"] = "AVAILABLE"
        base["value"] = ledger_value
        base["source"] = "LEDGER_METRICS"
        base["reason"] = "FROZEN_PROBABILITY_NOT_RECONSTRUCTABLE"
        return base

    base["reason"] = "MISSING_FROZEN_ACTUAL_SCORE_PROBABILITY"
    return base


def _outcome(score: Any) -> str | None:
    parsed = _score_tuple(score)
    if not parsed:
        return None
    home, away = parsed
    return "home" if home > away else "draw" if home == away else "away"


def _normalise_outcome(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    token = value.strip().lower()
    aliases = {
        "home": "home", "h": "home", "主": "home", "主胜": "home", "home_win": "home",
        "draw": "draw", "d": "draw", "平": "draw", "平局": "draw",
        "away": "away", "a": "away", "客": "away", "客胜": "away", "away_win": "away",
    }
    return aliases.get(token)


def _leader(probabilities: dict[str, float]) -> str | None:
    clean = {key: _as_float(probabilities.get(key)) for key in ("home", "draw", "away")}
    clean = {key: value for key, value in clean.items() if value is not None}
    return max(clean, key=clean.get) if clean else None


def matrix_map(score_rows: list[dict]) -> str | None:
    """Return the MAP score from the frozen matrix ranking."""
    rows = [row for row in score_rows if _score_string(row.get("score"))]
    if not rows:
        return None
    if any(_as_float(row.get("probability")) is not None for row in rows):
        return max(
            rows,
            key=lambda row: (
                _as_float(row.get("probability")) if _as_float(row.get("probability")) is not None else -1.0,
                -(_as_int(row.get("rank")) or 10**9),
            ),
        )["score"]
    return min(rows, key=lambda row: _as_int(row.get("rank")) or 10**9)["score"]


def outcome_conditioned_map(score_rows: list[dict], probabilities: dict[str, float]) -> str | None:
    """Choose the best stored exact score inside the stored 1X2 leader branch."""
    target = _leader(probabilities)
    if target is None:
        return None
    rows = [row for row in score_rows if _outcome(row.get("score")) == target]
    if not rows:
        return None
    return max(
        rows,
        key=lambda row: (
            _as_float(row.get("probability")) if _as_float(row.get("probability")) is not None else -1.0,
            -(_as_int(row.get("rank")) or 10**9),
        ),
    )["score"]


def _trace_candidates(record: dict) -> Iterable[Any]:
    """Yield only explicitly frozen trace locations; never walk postmatch data."""
    for container in (record, record.get("prediction_output"), record.get("prediction")):
        if not isinstance(container, dict):
            continue
        for key in ("score_selection_trace", "scenario_trace"):
            if key in container:
                yield container[key]
        decisions = container.get("decisions")
        if isinstance(decisions, dict):
            for key in ("score_selection_trace", "scenario_trace"):
                if key in decisions:
                    yield decisions[key]
    analysis = record.get("analysis_output")
    if isinstance(analysis, dict):
        decisions = analysis.get("decisions")
        if isinstance(decisions, dict):
            for key in ("score_selection_trace", "scenario_trace"):
                if key in decisions:
                    yield decisions[key]


def _score_from_trace(value: Any) -> str | None:
    if isinstance(value, dict):
        for key in ("scenario_selected_score", "selected_score", "score"):
            score = _score_string(value.get(key))
            if score:
                return score
        for key in ("trace", "steps", "candidates"):
            nested = value.get(key)
            score = _score_from_trace(nested)
            if score:
                return score
    elif isinstance(value, list):
        for item in value:
            score = _score_from_trace(item)
            if score:
                return score
    return None


def scenario_score_from_record(record: dict) -> str | None:
    """Read an explicitly persisted frozen scenario trace, if present."""
    for candidate in _trace_candidates(record):
        score = _score_from_trace(candidate)
        if score:
            return score
    return None


def classify_sample_tier(record: dict, exclusion_ids: set[str]) -> str:
    prediction_id = str(record.get("prediction_id") or "")
    if prediction_id in exclusion_ids:
        return "PILOT_EXCLUDED"
    status = str(record.get("prediction_status") or "").lower()
    if bool(record.get("formal_eligible")) and status not in {"research", "research_only", "legacy"}:
        return "FORMAL_PROSPECTIVE"
    return "RESEARCH_LEGACY"


def _scope_is_regulation(scope: Any) -> bool:
    if scope is None or scope == "":
        return True
    token = str(scope).strip().lower()
    return not any(part in token for part in EXTRA_TIME_TOKENS)


def verified_result_from_ledger_entry(entry: dict) -> str | None:
    """Return a verified regulation result from a prospective ledger row."""
    if not isinstance(entry, dict) or not entry.get("result_verified_at"):
        return None
    scope = entry.get("scope") or entry.get("result_scope") or entry.get("verified_scope") or entry.get("actual_scope")
    if not _scope_is_regulation(scope):
        return None
    actual = entry.get("actual") if isinstance(entry.get("actual"), dict) else entry
    home = _as_int(actual.get("home_score"))
    away = _as_int(actual.get("away_score"))
    if home is None or away is None or home < 0 or away < 0:
        parsed = _score_string(actual.get("score") or actual.get("actual_score"))
        return parsed
    return f"{home}-{away}"


def score_margin(score_rows: list[dict]) -> dict[str, float | None]:
    rows = sorted(score_rows, key=lambda row: (_as_int(row.get("rank")) or 10**9, -(_as_float(row.get("probability")) or 0.0)))
    probabilities = [
        _as_float(row.get("probability"))
        for row in rows[:3]
    ]
    while len(probabilities) < 3:
        probabilities.append(None)
    top1, top2, top3 = probabilities
    return {
        "top1_probability": top1,
        "top2_probability": top2,
        "top3_probability": top3,
        "top1_top2_gap": round(top1 - top2, 6) if top1 is not None and top2 is not None else None,
        "top1_top3_gap": round(top1 - top3, 6) if top1 is not None and top3 is not None else None,
    }


def outcome_consistency(selected_score: str | None, probabilities: dict[str, float]) -> bool | None:
    if not selected_score:
        return None
    selected = _outcome(selected_score)
    leader = _leader(probabilities)
    return selected == leader if selected and leader else None


def goal_error_metrics(selected_score: str, actual: dict) -> dict[str, float] | None:
    selected = _score_tuple(selected_score)
    actual_tuple = (_as_int(actual.get("home_score")), _as_int(actual.get("away_score"))) if isinstance(actual, dict) else (None, None)
    if not selected or actual_tuple[0] is None or actual_tuple[1] is None:
        return None
    home, away = selected
    actual_home, actual_away = actual_tuple
    return {
        "total_goal_absolute_error": float(abs(home + away - actual_home - actual_away)),
        "goal_difference_absolute_error": float(abs((home - away) - (actual_home - actual_away))),
    }


def select_score_methods(record: dict, dixon_coles_available: bool = True) -> dict[str, str | None]:
    rows = _score_rows(record)
    methods = {
        "matrix_map": matrix_map(rows),
        "outcome_conditioned_map": outcome_conditioned_map(rows, _probabilities(record)),
        "scenario_challenger": scenario_score_from_record(record),
        # No recalibrated Dixon-Coles challenger is created by this audit.
        "dixon_coles_shadow": None,
    }
    if not dixon_coles_available:
        methods["dixon_coles_shadow"] = None
    return methods


def _canonical_sha256(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _commit_model_source_fingerprint(root: Path, commit_sha: str) -> str | None:
    """Hash the committed source bytes, avoiding host checkout line endings."""
    component_hashes: dict[str, str | None] = {}
    for relative, symbol in REPLAY_SOURCE_COMPONENTS:
        try:
            source_bytes = subprocess.check_output(
                ["git", "show", f"{commit_sha}:{relative}"],
                cwd=root,
                stderr=subprocess.DEVNULL,
            )
        except (OSError, subprocess.CalledProcessError):
            component_hashes[f"{relative}::{symbol}" if symbol else relative] = None
            continue
        key = f"{relative}::{symbol}" if symbol else relative
        if symbol:
            try:
                source = source_bytes.decode("utf-8")
                tree = ast.parse(source, filename=relative)
                segment = next(
                    (
                        ast.get_source_segment(source, node)
                        for node in tree.body
                        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                        and node.name == symbol
                    ),
                    None,
                )
                component_hashes[key] = hashlib.sha256((segment or "").encode("utf-8")).hexdigest() if segment is not None else None
            except (UnicodeError, SyntaxError):
                component_hashes[key] = None
        else:
            component_hashes[key] = hashlib.sha256(source_bytes).hexdigest()
    if any(value is None for value in component_hashes.values()):
        return None
    return _canonical_sha256({"algorithm": "sha256", "components": component_hashes})


def _replay_score_rows(replay_result: dict) -> list[dict]:
    model = replay_result.get("model") if isinstance(replay_result, dict) else None
    if not isinstance(model, dict):
        return []
    for key in ("score_probabilities", "score_distribution", "score_matrix", "top_scores"):
        rows = _score_rows_from_candidate(model.get(key))
        if rows:
            return rows
    return []


def _top_score_rows(rows: list[dict], limit: int = 3) -> list[dict]:
    ordered = sorted(rows, key=lambda row: (_as_int(row.get("rank")) or 10**9, -(float(row.get("probability")) if _as_float(row.get("probability")) is not None else -1.0)))
    return ordered[:limit]


def replay_result_against_frozen(
    record: dict,
    replay_result: dict,
    *,
    tolerance: float = REPLAY_PROBABILITY_TOLERANCE,
    actual_score: str | None = None,
) -> dict[str, Any]:
    """Apply the replay sanity gate without using any postmatch data.

    The frozen score rows remain the official candidate set.  A replayed
    scenario score is only exposed when the replay reproduces the frozen
    matrix MAP and frozen Top-3 probabilities within ``tolerance``.
    ``actual_score`` is an explicit post-selection evaluation argument and is
    never read from ``record``.
    """
    model = replay_result.get("model") if isinstance(replay_result, dict) else {}
    model = model if isinstance(model, dict) else {}
    expected_family = str(record.get("model_family") or "").strip()
    replayed_family = str(model.get("method") or "").strip()
    result: dict[str, Any] = {
        "prediction_id": _record_id(record),
        "match_id": _record_match_id(record),
        "repository_commit_sha": record.get("repository_commit_sha"),
        "input_snapshot_ref": record.get("input_snapshot_ref") or record.get("model_input_snapshot_ref") or _nested_dict(record, "input_snapshot").get("snapshot_ref"),
        "model_family": expected_family,
        "replayed_model_family": replayed_family or None,
        "release_version": record.get("release_version"),
        "replay_status": "REPLAY_MISMATCH",
        "replay_reason": None,
        "frozen_matrix_map": None,
        "replayed_matrix_map": None,
        "matrix_match": False,
        "frozen_top3": [],
        "replayed_top3": [],
        "frozen_top3_probabilities": {},
        "replayed_top3_probabilities": {},
        "probability_tolerance": tolerance,
        "scenario_challenger": None,
        "scenario_same_as_matrix": None,
        "scenario_different_from_matrix": None,
        "scenario_in_frozen_top3": None,
        "actual_score": actual_score,
    }
    if expected_family and replayed_family and expected_family != replayed_family:
        result["replay_status"] = "REPLAY_UNAVAILABLE"
        result["replay_reason"] = "MODEL_FAMILY_MISMATCH"
        return result

    frozen_rows = _score_rows(record)
    replayed_rows = _replay_score_rows(replay_result)
    frozen_top3_rows = _top_score_rows(frozen_rows)
    replayed_top3_rows = _top_score_rows(replayed_rows)
    result["frozen_top3"] = [row["score"] for row in frozen_top3_rows]
    result["replayed_top3"] = [row["score"] for row in replayed_top3_rows]
    result["frozen_top3_probabilities"] = {
        row["score"]: _as_float(row.get("probability")) for row in frozen_top3_rows if _as_float(row.get("probability")) is not None
    }
    result["replayed_top3_probabilities"] = {
        row["score"]: _as_float(row.get("probability")) for row in replayed_top3_rows if _as_float(row.get("probability")) is not None
    }
    result["frozen_matrix_map"] = matrix_map(frozen_rows)
    result["replayed_matrix_map"] = matrix_map(replayed_rows)
    if not frozen_top3_rows or not replayed_top3_rows:
        result["replay_reason"] = "REPLAY_SCORE_DISTRIBUTION_MISSING"
        return result

    scores_match = result["frozen_top3"] == result["replayed_top3"]
    probabilities_match = scores_match and all(
        frozen_row.get("probability") is not None
        and replayed_row.get("probability") is not None
        and abs(float(frozen_row["probability"]) - float(replayed_row["probability"])) <= tolerance
        for frozen_row, replayed_row in zip(frozen_top3_rows, replayed_top3_rows)
    )
    matrix_match = bool(
        result["frozen_matrix_map"]
        and result["frozen_matrix_map"] == result["replayed_matrix_map"]
        and scores_match
        and probabilities_match
    )
    result["matrix_match"] = matrix_match
    if not matrix_match:
        result["replay_reason"] = "REPLAY_MATRIX_MAP_OR_TOP3_MISMATCH"
        return result

    scenario = scenario_score_from_record(replay_result)
    result["replay_status"] = "REPLAY_VALID"
    result["scenario_challenger"] = scenario
    if scenario:
        result["scenario_same_as_matrix"] = scenario == result["replayed_matrix_map"]
        result["scenario_different_from_matrix"] = scenario != result["replayed_matrix_map"]
        result["scenario_in_frozen_top3"] = scenario in result["frozen_top3"]
    return result


def _safe_replay_path(root: Path, relative_ref: str) -> Path | None:
    candidate = Path(str(relative_ref))
    if candidate.is_absolute() or ".." in candidate.parts:
        return None
    resolved_root = root.resolve()
    resolved = (root / candidate).resolve()
    try:
        resolved.relative_to(resolved_root)
    except ValueError:
        return None
    return resolved


def _load_replay_snapshot(record: dict, root: Path) -> tuple[dict, dict, str] | tuple[None, None, str]:
    metadata = record.get("input_snapshot") if isinstance(record.get("input_snapshot"), dict) else {}
    reference = record.get("input_snapshot_ref") or record.get("model_input_snapshot_ref") or metadata.get("snapshot_ref")
    expected_hash = str(record.get("canonical_model_input_sha256") or record.get("input_sha256") or metadata.get("canonical_input_sha256") or "")
    snapshot_path = _safe_replay_path(root, str(reference)) if reference else None
    if snapshot_path is None and expected_hash:
        snapshot_path = root / "data" / "model_governance" / "input_snapshots" / f"{expected_hash}.json"
    if snapshot_path is None or not snapshot_path.is_file():
        return None, None, "INPUT_SNAPSHOT_UNAVAILABLE"
    try:
        document = json.loads(snapshot_path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None, None, "INPUT_SNAPSHOT_INVALID"
    if not isinstance(document, dict):
        return None, None, "INPUT_SNAPSHOT_INVALID"
    if metadata.get("snapshot_id") and document.get("snapshot_id") != metadata.get("snapshot_id"):
        return None, None, "INPUT_SNAPSHOT_ID_MISMATCH"
    input_payload = document.get("input")
    if not isinstance(input_payload, dict):
        input_payload = document.get("projection")
    if not isinstance(input_payload, dict):
        return None, None, "INPUT_SNAPSHOT_PROJECTION_MISSING"
    document_hash = document.get("canonical_input_sha256") or document.get("canonical_model_input_sha256")
    calculated_hash = _canonical_sha256(input_payload)
    if document_hash and document_hash != calculated_hash:
        return None, None, "INPUT_SNAPSHOT_HASH_MISMATCH"
    if expected_hash and calculated_hash != expected_hash:
        return None, None, "INPUT_SNAPSHOT_RECORD_HASH_MISMATCH"
    return document, input_payload, str(snapshot_path.relative_to(root))


def _git_commit_exists(root: Path, commit_sha: str) -> bool:
    if not re.fullmatch(r"[0-9a-fA-F]{7,40}", commit_sha):
        return False
    try:
        completed = subprocess.run(
            ["git", "cat-file", "-e", f"{commit_sha}^{{commit}}"],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return False
    return completed.returncode == 0


def _create_replay_worktree(root: Path, commit_sha: str, parent: Path) -> Path | None:
    for attempt in range(3):
        suffix = "" if attempt == 0 else f"-{attempt}"
        path = parent / f"commit-{commit_sha[:12]}{suffix}"
        if path.exists():
            try:
                existing = subprocess.run(
                    ["git", "-C", str(path), "rev-parse", "HEAD"],
                    cwd=root,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if existing.returncode == 0 and existing.stdout.strip().startswith(commit_sha):
                    return path
            except OSError:
                pass
            shutil.rmtree(path, ignore_errors=True)
        try:
            completed = subprocess.run(
                ["git", "worktree", "add", "--detach", str(path), commit_sha],
                cwd=root,
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError:
            continue
        if completed.returncode == 0 and path.is_dir():
            return path
    return None


_REPLAY_CHILD = r'''import json, socket, sys

class _NetworkBlockedSocket:
    def __init__(self, *args, **kwargs):
        raise RuntimeError("network disabled for freeze-time audit replay")

socket.socket = _NetworkBlockedSocket
request = json.load(sys.stdin)
from automatic_model_core import MODEL_FAMILY, build_automatic_model
from deepseek_auto_analysis import MODEL_VERSION
from model_governance import load_config, model_source_fingerprint

config = load_config()
champion = config.get("champion") or {}
identity = {
    "model_family": MODEL_FAMILY,
    "release_version": MODEL_VERSION,
    "configured_model_family": champion.get("model_family"),
    "configured_release_version": champion.get("release_version"),
    "model_source_fingerprint": model_source_fingerprint().get("fingerprint"),
}
if request.get("expected_model_family") and identity["model_family"] != request["expected_model_family"]:
    raise RuntimeError("freeze-time model family identity mismatch")
if request.get("expected_release_version") and identity["release_version"] != request["expected_release_version"]:
    raise RuntimeError("freeze-time release identity mismatch")
result = build_automatic_model(request["projection"])
print(json.dumps({"model": result.get("model"), "decisions": result.get("decisions"), "identity": identity}, ensure_ascii=False, separators=(",", ":")))
'''


def replay_frozen_prediction(
    record: dict,
    root: Path | str,
    worktree_parent: Path,
    worktree_cache: dict[str, Path],
    *,
    tolerance: float = REPLAY_PROBABILITY_TOLERANCE,
) -> dict[str, Any]:
    """Replay one record in an isolated checkout of its freeze-time commit."""
    root = Path(root).resolve()
    commit_sha = str(record.get("repository_commit_sha") or "").strip()
    base = {
        "prediction_id": _record_id(record),
        "match_id": _record_match_id(record),
        "repository_commit_sha": commit_sha or None,
        "input_snapshot_ref": record.get("input_snapshot_ref") or record.get("model_input_snapshot_ref") or _nested_dict(record, "input_snapshot").get("snapshot_ref"),
        "model_family": record.get("model_family"),
        "release_version": record.get("release_version"),
        "replay_status": "REPLAY_UNAVAILABLE",
        "replay_reason": None,
        "matrix_match": None,
        "frozen_matrix_map": None,
        "replayed_matrix_map": None,
        "frozen_top3": [],
        "replayed_top3": [],
        "scenario_challenger": None,
        "scenario_same_as_matrix": None,
        "scenario_different_from_matrix": None,
        "scenario_in_frozen_top3": None,
        "actual_score": None,
        "probability_tolerance": tolerance,
    }
    if not commit_sha or not _git_commit_exists(root, commit_sha):
        base["replay_reason"] = "REPOSITORY_COMMIT_UNAVAILABLE"
        return base
    committed_fingerprint = _commit_model_source_fingerprint(root, commit_sha)
    if not committed_fingerprint:
        base["replay_reason"] = "MODEL_SOURCE_FINGERPRINT_UNAVAILABLE"
        return base
    if committed_fingerprint != str(record.get("model_source_fingerprint") or ""):
        base["replay_reason"] = "MODEL_SOURCE_FINGERPRINT_MISMATCH"
        base["freeze_time_model_source_fingerprint"] = committed_fingerprint
        return base
    if not record.get("model_family") or not record.get("release_version") or not record.get("model_source_fingerprint"):
        base["replay_reason"] = "MODEL_IDENTITY_INCOMPLETE"
        return base
    _, projection, snapshot_reason = _load_replay_snapshot(record, root)
    if projection is None:
        base["replay_reason"] = snapshot_reason
        return base
    worktree = worktree_cache.get(commit_sha)
    if worktree is None or not worktree.is_dir():
        worktree = _create_replay_worktree(root, commit_sha, worktree_parent)
        if worktree is None:
            base["replay_reason"] = "FREEZE_TIME_WORKTREE_UNAVAILABLE"
            return base
        worktree_cache[commit_sha] = worktree
    request = {
        "projection": projection,
        "expected_model_family": record.get("model_family"),
        "expected_release_version": record.get("release_version"),
    }
    try:
        completed = subprocess.run(
            [sys.executable, "-c", _REPLAY_CHILD],
            cwd=worktree,
            input=json.dumps(request, ensure_ascii=False, allow_nan=False),
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
            env={**os.environ, "PYTHONPATH": str(worktree / "scripts")},
        )
    except (OSError, subprocess.SubprocessError) as error:
        base["replay_reason"] = f"REPLAY_PROCESS_ERROR:{type(error).__name__}"
        return base
    if completed.returncode != 0:
        base["replay_reason"] = "REPLAY_PROCESS_FAILED"
        base["replay_error"] = (completed.stderr or "").strip()[-500:]
        return base
    try:
        payload = json.loads((completed.stdout or "").strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError):
        base["replay_reason"] = "REPLAY_OUTPUT_INVALID"
        return base
    comparison = replay_result_against_frozen(record, payload, tolerance=tolerance)
    comparison["freeze_time_identity"] = payload.get("identity") if isinstance(payload, dict) else None
    comparison["freeze_time_model_source_fingerprint"] = committed_fingerprint
    return comparison


def replay_frozen_records(
    records: list[dict],
    root: Path | str,
    *,
    tolerance: float = REPLAY_PROBABILITY_TOLERANCE,
) -> list[dict[str, Any]]:
    """Replay records with one temporary worktree per unique freeze commit."""
    root = Path(root).resolve()
    parent = Path(tempfile.mkdtemp(prefix="football-pa1-r1-replay-"))
    grouped: dict[str, list[tuple[int, dict]]] = {}
    for index, record in enumerate(records):
        grouped.setdefault(str(record.get("repository_commit_sha") or ""), []).append((index, record))
    indexed_results: list[dict[str, Any] | None] = [None] * len(records)
    try:
        # Keep only one full checkout alive at a time.  Besides reducing
        # temporary disk pressure, this avoids Windows Git worktree locks when
        # several historical commits are replayed in one audit.
        for group in grouped.values():
            cache: dict[str, Path] = {}
            try:
                for index, record in group:
                    indexed_results[index] = replay_frozen_prediction(
                        record, root, parent, cache, tolerance=tolerance
                    )
            finally:
                for worktree in list(cache.values()):
                    subprocess.run(
                        ["git", "worktree", "remove", "--force", str(worktree)],
                        cwd=root,
                        capture_output=True,
                        text=True,
                        check=False,
                    )
    finally:
        shutil.rmtree(parent, ignore_errors=True)
    return [result or {
        "prediction_id": _record_id(records[index]),
        "replay_status": "REPLAY_UNAVAILABLE",
        "replay_reason": "REPLAY_RESULT_MISSING",
    } for index, result in enumerate(indexed_results)]


def _iter_json_files(directory: Path) -> Iterable[tuple[Path, dict]]:
    if not directory.exists():
        return
    for path in sorted(directory.glob("*.json")):
        value = _json_load(path)
        if isinstance(value, dict):
            yield path, value


def _extract_list(payload: Any, keys: tuple[str, ...]) -> list[dict]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    for key in keys:
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []


def _load_predictions(root: Path) -> tuple[list[dict], list[str]]:
    records: list[dict] = []
    malformed: list[str] = []
    directory = root / "data" / "model_governance" / "predictions"
    if not directory.exists():
        return records, malformed
    for path in sorted(directory.glob("*.json")):
        try:
            value = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            malformed.append(str(path.relative_to(root)))
            continue
        if isinstance(value, dict):
            value = dict(value)
            value.setdefault("_artifact_path", str(path.relative_to(root)))
            records.append(value)
    return records, malformed


def _load_exclusion_ids(root: Path) -> set[str]:
    result: set[str] = set()
    directory = root / "data" / "model_governance" / "prediction_exclusions"
    for _, payload in _iter_json_files(directory):
        for key in ("prediction_ids", "excluded_prediction_ids"):
            values = payload.get(key)
            if isinstance(values, list):
                result.update(str(value) for value in values if value)
        values = payload.get("exclusions")
        if isinstance(values, list):
            for value in values:
                if isinstance(value, str):
                    result.add(value)
                elif isinstance(value, dict) and value.get("prediction_id"):
                    result.add(str(value["prediction_id"]))
    return result


def _load_ledger(root: Path) -> tuple[list[dict], list[str]]:
    path = root / "data" / "prospective" / "ledger.jsonl"
    rows: list[dict] = []
    malformed: list[str] = []
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except (OSError, UnicodeError):
        return rows, malformed
    for line_number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            malformed.append(f"ledger.jsonl:{line_number}")
            continue
        if isinstance(value, dict):
            rows.append(value)
    return rows, malformed


def _record_id(record: dict) -> str:
    return str(record.get("prediction_id") or "")


def _record_date(record: dict) -> str | None:
    value = record.get("business_date")
    return str(value) if value else None


def _record_score(record: dict) -> str | None:
    for candidate in (
        record.get("unique_score"),
        record.get("primary_score"),
        record.get("score_top1"),
        _nested_dict(record, "prediction_output").get("unique_score"),
        _nested_dict(record, "prediction").get("unique_score"),
    ):
        score = _score_string(candidate)
        if score:
            return score
    return None


def _record_teams(record: dict) -> tuple[str | None, str | None]:
    identity = record.get("match_identity") if isinstance(record.get("match_identity"), dict) else {}
    home = record.get("home") or record.get("home_team") or identity.get("home")
    away = record.get("away") or record.get("away_team") or identity.get("away")
    return (str(home) if home is not None else None, str(away) if away is not None else None)


def _record_match_id(record: dict) -> str | None:
    identity = record.get("match_identity") if isinstance(record.get("match_identity"), dict) else {}
    value = record.get("match_id") or identity.get("match_id")
    return str(value) if value else None


def _record_lambda(record: dict) -> tuple[float | None, float | None]:
    payload = _prediction_payload(record)
    home = _as_float(record.get("lambda_home"))
    away = _as_float(record.get("lambda_away"))
    if home is None:
        home = _as_float(payload.get("lambda_home"))
    if away is None:
        away = _as_float(payload.get("lambda_away"))
    return home, away


def _stored_market_line(record: dict, keys: tuple[str, ...]) -> Any:
    """Read a canonical stored market line when the frozen record exposes one."""
    containers = [record, record.get("market_summary"), _prediction_payload(record)]
    for container in containers:
        if not isinstance(container, dict):
            continue
        for key in keys:
            value = container.get(key)
            if value is not None and not isinstance(value, (dict, list)):
                return value
    return None


def _fixture_key(record: dict) -> str:
    return str(record.get("match_id") or record.get("match_key") or "")


def _load_universe(root: Path, business_date: str) -> dict:
    path = root / "data" / "prediction_universe" / f"{business_date}.json"
    payload = _json_load(path, {})
    if not isinstance(payload, dict):
        return {"exists": False, "fixture_count": 0, "fixtures": [], "status": None}
    fixtures = _extract_list(payload, ("fixtures", "matches", "items", "data"))
    count = _as_int(payload.get("fixture_count"))
    return {
        "exists": True,
        "fixture_count": count if count is not None else len(fixtures),
        "fixtures": fixtures,
        "status": payload.get("status"),
        "fetched_at": payload.get("fetched_at"),
        "path": str(path.relative_to(root)),
    }


def _load_status_projection(root: Path, business_date: str) -> list[dict]:
    for path in (
        root / "data" / "prediction_dashboard" / "latest.json",
        root / "data" / "base_prediction_jobs" / f"{business_date}.json",
    ):
        payload = _json_load(path)
        rows = _extract_list(payload, ("matches", "fixtures", "jobs", "records", "items", "data"))
        if rows:
            payload_date = str(payload.get("business_date") or payload.get("target_date") or "") if isinstance(payload, dict) else ""
            if not payload_date or payload_date == business_date:
                return rows
    return []


def _status_counts(rows: list[dict]) -> Counter:
    counts: Counter = Counter()
    for row in rows:
        status = str(row.get("status") or row.get("prediction_status") or "").upper()
        if status:
            counts[status] += 1
    return counts


def _distribution(scores: Iterable[str]) -> dict:
    values = [score for score in scores if _score_string(score)]
    counts = Counter(values)
    total = len(values)
    probabilities = {score: count / total for score, count in counts.items()} if total else {}
    entropy = -sum(probability * math.log(probability, 2) for probability in probabilities.values() if probability > 0)
    low_score_count = sum(sum(_score_tuple(score)) <= 2 for score in values)
    draw_count = sum(_outcome(score) == "draw" for score in values)
    return {
        "count": total,
        "distinct_scores": len(counts),
        "counts": dict(sorted(counts.items(), key=lambda item: (-item[1], item[0]))),
        "share": {score: round(probability, 6) for score, probability in sorted(probabilities.items())},
        "entropy_bits": round(entropy, 6),
        "mode_score": counts.most_common(1)[0][0] if counts else None,
        "mode_share": round(counts.most_common(1)[0][1] / total, 6) if total else None,
        "one_one_share": round(counts.get("1-1", 0) / total, 6) if total else None,
        "draw_score_share": round(draw_count / total, 6) if total else None,
        "low_score_definition": "total goals <= 2",
        "low_score_share": round(low_score_count / total, 6) if total else None,
    }


def _actual_distribution(results: Iterable[str]) -> dict:
    values = [score for score in results if score]
    outcomes = Counter(_outcome(score) for score in values)
    total_goals = [sum(_score_tuple(score)) for score in values if _score_tuple(score)]
    result = _distribution(values)
    result.update(
        {
            "outcome_counts": dict(outcomes),
            "outcome_share": {key: round(value / len(values), 6) for key, value in outcomes.items()} if values else {},
            "total_goals_mean": round(fmean(total_goals), 6) if total_goals else None,
        }
    )
    return result


def _mean_or_none(values: Iterable[float]) -> float | None:
    clean = [value for value in values if value is not None and math.isfinite(value)]
    return round(fmean(clean), 6) if clean else None


def _median_or_none(values: Iterable[float]) -> float | None:
    clean = [value for value in values if value is not None and math.isfinite(value)]
    return round(median(clean), 6) if clean else None


def _metric_for_method(name: str, evaluated: list[dict]) -> dict:
    available = [row for row in evaluated if row.get("methods", {}).get(name)]
    if not available:
        return {
            "available": 0,
            "exact_score_top1_accuracy": None,
            "stored_top3_coverage": None,
            "stored_top5_coverage": None,
            "stored_top10_coverage": None,
            "outcome_accuracy": None,
            "outcome_consistency_rate": None,
            "goal_mae": None,
            "goal_difference_mae": None,
            "selection_outcome_accuracy": None,
            "selected_goal_mae": None,
            "selected_goal_difference_mae": None,
        }
    hits = [row["methods"][name] == row["actual_score"] for row in available]
    top3 = [row["actual_score"] in row.get("stored_scores", [])[:3] for row in available]
    top5 = [row["actual_score"] in row.get("stored_scores", [])[:5] for row in available]
    top10 = [row["actual_score"] in row.get("stored_scores", [])[:10] for row in available]
    outcome_hits = [
        _outcome(row["methods"][name]) == row["actual_outcome"]
        for row in available
        if _outcome(row["methods"][name])
    ]
    consistency = [
        _outcome(row["methods"][name]) == _leader(row.get("probabilities") or {})
        for row in available
        if _outcome(row["methods"][name]) and _leader(row.get("probabilities") or {})
    ]
    home_leader = [row for row in available if row.get("probabilities") and _leader(row["probabilities"]) == "home"]
    away_leader = [row for row in available if row.get("probabilities") and _leader(row["probabilities"]) == "away"]
    home_draw_scores = [row for row in home_leader if _outcome(row["methods"].get(name)) == "draw"]
    away_draw_scores = [row for row in away_leader if _outcome(row["methods"].get(name)) == "draw"]
    method_goal_errors = [goal_error_metrics(row["methods"][name], row.get("actual") or {}) for row in available]
    goal_errors = [item["total_goal_absolute_error"] for item in method_goal_errors if item]
    difference_errors = [item["goal_difference_absolute_error"] for item in method_goal_errors if item]
    metric = {
        "available": len(available),
        "exact_score_top1_accuracy": round(sum(hits) / len(hits), 6),
        "stored_top3_coverage": round(sum(top3) / len(top3), 6),
        "stored_top5_coverage": round(sum(top5) / len(top5), 6),
        "stored_top10_coverage": round(sum(top10) / len(top10), 6),
        "outcome_accuracy": round(sum(outcome_hits) / len(outcome_hits), 6) if outcome_hits else None,
        "outcome_consistency_rate": round(sum(consistency) / len(consistency), 6) if consistency else None,
        "home_leader_draw_score_rate": round(len(home_draw_scores) / len(home_leader), 6) if home_leader else None,
        "away_leader_draw_score_rate": round(len(away_draw_scores) / len(away_leader), 6) if away_leader else None,
        "home_leader_count": len(home_leader),
        "away_leader_count": len(away_leader),
        "goal_mae": round(fmean(goal_errors), 6) if goal_errors else None,
        "goal_difference_mae": round(fmean(difference_errors), 6) if difference_errors else None,
    }
    metric["selection_outcome_accuracy"] = metric["outcome_accuracy"]
    metric["selected_goal_mae"] = metric["goal_mae"]
    metric["selected_goal_difference_mae"] = metric["goal_difference_mae"]
    return metric


def paired_method_metrics(evaluated: list[dict], first_method: str, second_method: str) -> dict[str, Any]:
    """Compare two methods on exactly the rows where both are available."""
    paired = [
        row for row in evaluated
        if row.get("methods", {}).get(first_method)
        and row.get("methods", {}).get(second_method)
    ]
    return {
        "paired_sample_count": len(paired),
        first_method: _metric_for_method(first_method, paired),
        second_method: _metric_for_method(second_method, paired),
    }


def _verified_formal_rows(records_by_id: dict[str, dict], ledger: list[dict], exclusions: set[str]) -> list[dict]:
    rows: list[dict] = []
    for entry in ledger:
        if not entry.get("formal_prospective_eligible"):
            continue
        prediction_id = str(entry.get("prediction_id") or "")
        if not prediction_id or prediction_id in exclusions:
            continue
        actual_score = verified_result_from_ledger_entry(entry)
        record = records_by_id.get(prediction_id)
        if not actual_score or not record or not _record_score(record):
            continue
        actual = entry.get("actual") if isinstance(entry.get("actual"), dict) else {}
        methods = select_score_methods(record)
        stored_rows = _score_rows(record)
        probabilities = _probabilities(record)
        selected = methods.get("matrix_map")
        errors = goal_error_metrics(selected, actual) if selected else None
        rows.append(
            {
                "prediction_id": prediction_id,
                "record": record,
                "business_date": entry.get("business_date") or _record_date(record),
                "match_id": _record_match_id(record) or _nested_dict(entry, "match_identity").get("match_id"),
                "actual_score": actual_score,
                "actual_outcome": _outcome(actual_score),
                "methods": methods,
                "stored_scores": [row["score"] for row in stored_rows],
                "probabilities": probabilities,
                "selected_outcome": _outcome(selected),
                "outcome_consistent": outcome_consistency(selected, probabilities),
                "goal_errors": errors,
                "actual": actual,
                "ledger_metrics": entry.get("metrics") if isinstance(entry.get("metrics"), dict) else {},
            }
        )
    return rows


def _model_method_comparison(evaluated: list[dict]) -> list[dict]:
    rows: list[dict] = []
    for item in evaluated:
        record = item["record"]
        margin = score_margin(_score_rows(record))
        home, away = _record_teams(record)
        probabilities = item.get("probabilities") or {}
        rows.append(
            {
                "match_id": item.get("match_id"),
                "business_date": item.get("business_date"),
                "home": home,
                "away": away,
                "actual_score": item.get("actual_score"),
                "matrix_map": item["methods"].get("matrix_map"),
                "outcome_conditioned_map": item["methods"].get("outcome_conditioned_map"),
                "scenario_challenger": item["methods"].get("scenario_challenger"),
                "dc_shadow": item["methods"].get("dixon_coles_shadow"),
                "matrix_hit": item["methods"].get("matrix_map") == item.get("actual_score"),
                "outcome_hit": item["methods"].get("outcome_conditioned_map") == item.get("actual_score"),
                "scenario_hit": item["methods"].get("scenario_challenger") == item.get("actual_score") if item["methods"].get("scenario_challenger") else None,
                "dc_hit": item["methods"].get("dixon_coles_shadow") == item.get("actual_score") if item["methods"].get("dixon_coles_shadow") else None,
                "lambda_home": _record_lambda(record)[0],
                "lambda_away": _record_lambda(record)[1],
                "market_total": _stored_market_line(record, ("market_total", "total_line", "ou_line")),
                "market_handicap": _stored_market_line(record, ("market_handicap", "asian_handicap", "ah_line")),
                "fusion_1x2_leader": _leader(probabilities),
                "top1_probability": margin["top1_probability"],
                "top2_probability": margin["top2_probability"],
                "top1_top2_gap": margin["top1_top2_gap"],
            }
        )
    return rows


def _summarise_method_rows(evaluated: list[dict]) -> dict:
    names = ("matrix_map", "outcome_conditioned_map", "scenario_challenger", "dixon_coles_shadow")
    result = {name: _metric_for_method(name, evaluated) for name in names}
    nll_results = [
        score_nll_for_record(row["record"], row["actual_score"], row.get("ledger_metrics"))
        for row in evaluated
    ]
    score_nll_values = [item["value"] for item in nll_results if item.get("status") == "AVAILABLE"]
    unavailable_reason_counts = Counter(
        str(item.get("reason"))
        for item in nll_results
        if item.get("status") == "UNAVAILABLE" and item.get("reason")
    )
    result["underlying_frozen_distribution"] = {
        "available": len(evaluated),
        "top3_coverage": _mean_or_none(float(row["actual_score"] in row.get("stored_scores", [])[:3]) for row in evaluated),
        "top5_coverage": _mean_or_none(float(row["actual_score"] in row.get("stored_scores", [])[:5]) for row in evaluated),
        "top10_coverage": _mean_or_none(float(row["actual_score"] in row.get("stored_scores", [])[:10]) for row in evaluated),
        "score_nll_available_count": len(score_nll_values),
        "score_nll_unavailable_count": sum(item.get("status") == "UNAVAILABLE" for item in nll_results),
        "score_nll_mismatch_count": sum(item.get("status") == "MISMATCH" for item in nll_results),
        "mean_score_nll_available_only": _mean_or_none(score_nll_values),
        "score_nll_unavailable_reason_counts": dict(sorted(unavailable_reason_counts.items())),
        "score_nll_tolerance": SCORE_NLL_TOLERANCE,
    }
    brier = [
        _as_float(row.get("ledger_metrics", {}).get("brier_score_1x2"))
        for row in evaluated
        if row.get("ledger_metrics", {}).get("brier_score_1x2") is not None
    ]
    logloss = [
        _as_float(row.get("ledger_metrics", {}).get("log_loss_1x2"))
        for row in evaluated
        if row.get("ledger_metrics", {}).get("log_loss_1x2") is not None
    ]
    result["underlying_frozen_distribution"].update(
        {
            "mean_ledger_1x2_brier": _mean_or_none(value for value in brier if value is not None),
            "mean_ledger_1x2_logloss": _mean_or_none(value for value in logloss if value is not None),
            "note": "Top-K and score NLL use only stored frozen probabilities or an explicitly valid ledger NLL; unavailable actual-score probabilities are not replaced with epsilon.",
        }
    )
    return result


def _lambda_audit(records: list[dict]) -> dict:
    rows = []
    for record in records:
        home, away = _record_lambda(record)
        if home is None or away is None:
            continue
        rows.append(
            {
                "prediction_id": _record_id(record),
                "match_id": _record_match_id(record),
                "lambda_home": home,
                "lambda_away": away,
                "lambda_gap": abs(home - away),
                "expected_goals": home + away,
                "score": _record_score(record),
                "leader": _leader(_probabilities(record)),
            }
        )
    def stats(key: str) -> dict:
        values = [row[key] for row in rows]
        return {
            "count": len(values),
            "min": round(min(values), 6) if values else None,
            "max": round(max(values), 6) if values else None,
            "mean": _mean_or_none(values),
            "median": _median_or_none(values),
        }
    both_1_to_2 = [row for row in rows if 1.0 <= row["lambda_home"] <= 2.0 and 1.0 <= row["lambda_away"] <= 2.0]
    narrow_gap = [row for row in rows if row["lambda_gap"] < 0.5]
    one_one = [row for row in rows if row["score"] == "1-1"]
    non_one_one = [row for row in rows if row["score"] != "1-1"]
    market_examples = []
    for row in rows:
        record = next((record for record in records if _record_id(record) == row["prediction_id"]), {})
        payload = _prediction_payload(record)
        market = record.get("market_only_baseline") or payload.get("market_only_baseline")
        if not isinstance(market, dict):
            continue
        market_values = [_as_float(market.get(key)) for key in ("home", "draw", "away")]
        if all(value is not None for value in market_values) and max(market_values) >= 0.55 and row["lambda_gap"] < 0.5:
            market_examples.append(
                {
                    "match_id": row["match_id"],
                    "prediction_id": row["prediction_id"],
                    "market_leader": _leader(market),
                    "market_max_probability": round(max(market_values), 6),
                    "lambda_home": row["lambda_home"],
                    "lambda_away": row["lambda_away"],
                    "lambda_gap": row["lambda_gap"],
                }
            )
    return {
        "sample_count": len(rows),
        "lambda_home": stats("lambda_home"),
        "lambda_away": stats("lambda_away"),
        "lambda_gap": stats("lambda_gap"),
        "expected_goals": stats("expected_goals"),
        "both_lambda_in_1_to_2": {"count": len(both_1_to_2), "share": round(len(both_1_to_2) / len(rows), 6) if rows else None},
        "absolute_lambda_gap_lt_0_5": {"count": len(narrow_gap), "share": round(len(narrow_gap) / len(rows), 6) if rows else None},
        "one_one_vs_other": {
            "one_one_count": len(one_one),
            "non_one_one_count": len(non_one_one),
            "one_one_lambda_gap_mean": _mean_or_none(row["lambda_gap"] for row in one_one),
            "non_one_one_lambda_gap_mean": _mean_or_none(row["lambda_gap"] for row in non_one_one),
            "one_one_expected_goals_mean": _mean_or_none(row["expected_goals"] for row in one_one),
            "non_one_one_expected_goals_mean": _mean_or_none(row["expected_goals"] for row in non_one_one),
        },
        "market_strength_vs_lambda_gap": {
            "criterion": "market-only leader probability >= 0.55 and absolute lambda gap < 0.5; descriptive only",
            "examples": market_examples[:10],
            "count": len(market_examples),
        },
    }


def _margin_audit(records: list[dict]) -> dict:
    margins = [score_margin(_score_rows(record)) for record in records if _score_rows(record)]
    gaps = [margin["top1_top2_gap"] for margin in margins if margin["top1_top2_gap"] is not None]
    return {
        "sample_count": len(gaps),
        "top1_top2_gap": {
            "min": min(gaps) if gaps else None,
            "max": max(gaps) if gaps else None,
            "mean": _mean_or_none(gaps),
            "median": _median_or_none(gaps),
        },
        "low_gap_lt_0_01": {
            "criterion": "top1-top2 stored probability gap < 0.01; descriptive only",
            "count": sum(gap < 0.01 for gap in gaps),
            "share": round(sum(gap < 0.01 for gap in gaps) / len(gaps), 6) if gaps else None,
        },
    }


def _selector_audit(root: Path) -> dict:
    path = root / "scripts" / "automatic_model_core.py"
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        source = ""
    return {
        "path": str(path.relative_to(root)) if path.exists() else "scripts/automatic_model_core.py",
        "scenario_score_pick_present": "def _scenario_score_pick" in source,
        "challenger_candidates_present": "challenger = candidates[0]" in source,
        "mathematical_first_score_present": "mathematical_first_score" in source,
        "formal_score_uses_mathematical_candidate": "selected = next" in source and "mathematical_home" in source,
        "declared_shadow_wording_present": "shadow candidate" in source.lower() or "shadow" in source.lower(),
        "interpretation": "The production selector returns the mathematical matrix candidate; the scenario candidate remains shadow-only in the inspected code.",
    }


def _calibration_audit(root: Path, production_versions: set[str]) -> dict:
    path = root / "data" / "model_calibration" / "latest.json"
    payload = _json_load(path, {})
    if not isinstance(payload, dict):
        payload = {}
    policy = payload.get("policy") if isinstance(payload.get("policy"), dict) else {}
    compatible = [str(item) for item in payload.get("compatible_model_versions", []) if item]
    return {
        "path": str(path.relative_to(root)) if path.exists() else "data/model_calibration/latest.json",
        "status": payload.get("status"),
        "active": payload.get("active"),
        "model_family": payload.get("model_family"),
        "compatible_model_versions": compatible,
        "production_release_versions": sorted(production_versions),
        "production_versions_in_compatible": {version: version in compatible for version in sorted(production_versions)},
        "sample": payload.get("sample") if isinstance(payload.get("sample"), dict) else {},
        "policy": policy,
        "approved": {
            key: bool((payload.get(key) or {}).get("approved"))
            for key in ("direction", "total_goals", "dispersion")
            if isinstance(payload.get(key), dict)
        },
    }


def _dixon_coles_audit(records: list[dict], formal_count: int, calibration: dict) -> dict:
    rho_values = []
    for record in records:
        value = record.get("rho")
        if value is None:
            value = _prediction_payload(record).get("rho")
        number = _as_float(value)
        if number is not None:
            rho_values.append(number)
    threshold = _as_int((calibration.get("policy") or {}).get("full_review_samples")) or DEFAULT_CALIBRATION_REVIEW_SAMPLES
    return {
        "production_rho_values": sorted({round(value, 8) for value in rho_values}),
        "production_rho_zero_count": sum(abs(value) < 1e-12 for value in rho_values),
        "production_rho_sample_count": len(rho_values),
        "independent_poisson_equivalent": bool(rho_values) and all(abs(value) < 1e-12 for value in rho_values),
        "calibration_status": "INSUFFICIENT_SAMPLE_FOR_DC_CALIBRATION" if formal_count < threshold else "SHADOW_REVIEW_REQUIRED",
        "required_full_review_samples": threshold,
        "note": "The audit does not fit or apply a new Dixon-Coles parameter.",
    }


def _representative_matches(records: list[dict], evaluated: list[dict]) -> list[dict]:
    formal_by_id = {str(row.get("prediction_id")): row for row in evaluated}
    candidates = []
    for record in records:
        probabilities = _probabilities(record)
        home, away = _record_lambda(record)
        score = _record_score(record)
        match_id = _record_match_id(record)
        record_date = _record_date(record)
        if not score or not probabilities or home is None or away is None or not match_id or not record_date:
            continue
        leader = _leader(probabilities)
        candidates.append(
            {
                "match_id": match_id,
                "prediction_id": _record_id(record),
                "business_date": _record_date(record),
                "home": _record_teams(record)[0],
                "away": _record_teams(record)[1],
                "unique_score": score,
                "leader": leader,
                "leader_probability": round(max(probabilities.values()), 6),
                "expected_goals": round(home + away, 6),
                "matrix_map": matrix_map(_score_rows(record)),
                "outcome_consistent": outcome_consistency(score, probabilities),
                "actual_score": formal_by_id.get(_record_id(record), {}).get("actual_score"),
            }
        )
    selected: list[dict] = []
    predicates = [
        ("strong_favourite", lambda row: row["leader_probability"] >= 0.55),
        ("high_total", lambda row: row["expected_goals"] >= 3.2),
        ("low_total", lambda row: row["expected_goals"] <= 2.2),
        ("non_draw_score", lambda row: _outcome(row["unique_score"]) != "draw"),
        ("formal_result", lambda row: row["actual_score"] is not None),
    ]
    for label, predicate in predicates:
        for row in sorted((item for item in candidates if predicate(item)), key=lambda item: (str(item.get("business_date")), str(item.get("match_id")))):
            if row["match_id"] not in {item.get("match_id") for item in selected}:
                selected.append({"selection_reason": label, **row})
            if len(selected) >= 10:
                break
        if len(selected) >= 10:
            break
    for row in sorted(candidates, key=lambda item: (str(item.get("business_date")), str(item.get("match_id")))):
        if len(selected) >= 10:
            break
        if row["match_id"] not in {item.get("match_id") for item in selected}:
            selected.append({"selection_reason": "deterministic_fill", **row})
    return selected[:10]


def _sanity_cases(records: list[dict], *, business_date: str | None = None, kind: str = "strong_favourite", limit: int = 5) -> list[dict]:
    """Return deterministic sanity examples without changing any selection."""
    rows = []
    for record in records:
        if business_date is not None and _record_date(record) != business_date:
            continue
        match_id = _record_match_id(record)
        record_date = _record_date(record)
        score = _record_score(record)
        probabilities = _probabilities(record)
        home, away = _record_lambda(record)
        if not match_id or not record_date or not score or not probabilities or home is None or away is None:
            continue
        leader_probability = max(probabilities.values())
        expected_goals = home + away
        if kind == "strong_favourite" and leader_probability < 0.55:
            continue
        if kind == "high_total" and expected_goals < 3.2:
            continue
        if kind == "low_total" and expected_goals > 2.2:
            continue
        rows.append(
            {
                "business_date": record_date,
                "match_id": match_id,
                "home": _record_teams(record)[0],
                "away": _record_teams(record)[1],
                "lambda_home": home,
                "lambda_away": away,
                "expected_goals": round(expected_goals, 6),
                "fusion_1x2": probabilities,
                "fusion_1x2_leader": _leader(probabilities),
                "unique_score": score,
                "matrix_map": matrix_map(_score_rows(record)),
                "matrix_outcome": _outcome(matrix_map(_score_rows(record))),
                "matrix_is_draw_score": _outcome(matrix_map(_score_rows(record))) == "draw",
            }
        )
    return sorted(rows, key=lambda row: (row["business_date"], row["match_id"]))[:limit]


def _production_distribution_comparison(current_records: list[dict], evaluated: list[dict]) -> dict:
    predicted = _distribution(_record_score(record) for record in current_records if _record_score(record))
    actual = _actual_distribution(row["actual_score"] for row in evaluated)
    predicted_outcomes = Counter(_outcome(_record_score(record)) for record in current_records if _record_score(record))
    return {
        "predicted_score_distribution": predicted,
        "verified_actual_score_distribution": actual,
        "predicted_current_outcome_counts": dict(predicted_outcomes),
        "sample_scope_note": "Current predictions and verified formal ledger results have different time scopes; comparison is descriptive, not a live performance claim.",
    }


def _hash_path(path: Path) -> str | None:
    if not path.exists():
        return None
    digest = hashlib.sha256()
    if path.is_file():
        try:
            digest.update(path.read_bytes())
        except OSError:
            return None
    else:
        for child in sorted(item for item in path.rglob("*") if item.is_file()):
            try:
                digest.update(str(child.relative_to(path)).encode("utf-8"))
                digest.update(child.read_bytes())
            except OSError:
                return None
    return digest.hexdigest()


def _mutation_hashes(root: Path) -> dict[str, str | None]:
    data = root / "data"
    paths = {
        "predictions": data / "model_governance" / "predictions",
        "input_snapshots": data / "model_governance" / "input_snapshots",
        "prediction_exclusions": data / "model_governance" / "prediction_exclusions",
        "prospective_ledger": data / "prospective" / "ledger.jsonl",
        "prospective_summary": data / "prospective" / "summary.json",
        "calibration": data / "model_calibration" / "latest.json",
    }
    return {key: _hash_path(path) for key, path in paths.items()}


def _current_census(root: Path, business_date: str, current_records: list[dict], exclusions: set[str]) -> dict:
    universe = _load_universe(root, business_date)
    projection_rows = _load_status_projection(root, business_date)
    status_counts = _status_counts(projection_rows)
    tiers = Counter(classify_sample_tier(record, exclusions) for record in current_records if _record_score(record))
    frozen = sum(1 for record in current_records if _record_score(record))
    if status_counts:
        status_counts["FROZEN"] = max(status_counts.get("FROZEN", 0), frozen)
    explained = sum(status_counts.values())
    silent_missing = max(0, int(universe.get("fixture_count") or 0) - explained) if status_counts else max(0, int(universe.get("fixture_count") or 0) - frozen)
    return {
        "business_date": business_date,
        "universe_status": universe.get("status"),
        "universe_fixture_count": universe.get("fixture_count", 0),
        "prediction_record_count": len(current_records),
        "frozen_prediction_count": frozen,
        "formal_predicted_count": tiers.get("FORMAL_PROSPECTIVE", 0),
        "pilot_predicted_count": tiers.get("PILOT_EXCLUDED", 0),
        "status_counts": dict(status_counts),
        "silent_missing_fixtures": silent_missing,
        "status_source": "prediction_dashboard/latest.json or base_prediction_jobs/date.json",
    }


def _replay_summary(current_results: list[dict], formal_results: list[dict], formal_rows: list[dict]) -> dict[str, Any]:
    def status_counts(rows: list[dict]) -> dict[str, int]:
        return dict(Counter(str(row.get("replay_status") or "REPLAY_UNAVAILABLE") for row in rows))

    def scenario_counts(rows: list[dict]) -> dict[str, int]:
        valid = [row for row in rows if row.get("replay_status") == "REPLAY_VALID" and row.get("scenario_challenger")]
        return {
            "scenario_same_as_matrix": sum(bool(row.get("scenario_same_as_matrix")) for row in valid),
            "scenario_different_from_matrix": sum(bool(row.get("scenario_different_from_matrix")) for row in valid),
            "matrix_one_one_scenario_not_one_one": sum(
                row.get("frozen_matrix_map") == "1-1" and row.get("scenario_different_from_matrix") is True
                for row in valid
            ),
        }

    paired = paired_method_metrics(formal_rows, "matrix_map", "scenario_challenger")
    paired["outcome_conditioned_map"] = _metric_for_method(
        "outcome_conditioned_map",
        [
            row for row in formal_rows
            if row.get("methods", {}).get("matrix_map") and row.get("methods", {}).get("scenario_challenger")
        ],
    )
    current_scenario = scenario_counts(current_results)
    formal_scenario = scenario_counts(formal_results)
    return {
        "probability_tolerance": REPLAY_PROBABILITY_TOLERANCE,
        "current": {
            "current_total": len(current_results),
            "status_counts": status_counts(current_results),
            "replay_valid": sum(row.get("replay_status") == "REPLAY_VALID" for row in current_results),
            "replay_unavailable": sum(row.get("replay_status") == "REPLAY_UNAVAILABLE" for row in current_results),
            "replay_mismatch": sum(row.get("replay_status") == "REPLAY_MISMATCH" for row in current_results),
            **current_scenario,
        },
        "formal": {
            "formal_total": len(formal_results),
            "status_counts": status_counts(formal_results),
            "replay_valid": sum(row.get("replay_status") == "REPLAY_VALID" for row in formal_results),
            "replay_unavailable": sum(row.get("replay_status") == "REPLAY_UNAVAILABLE" for row in formal_results),
            "replay_mismatch": sum(row.get("replay_status") == "REPLAY_MISMATCH" for row in formal_results),
            **formal_scenario,
            "paired_metrics_same_sample": paired,
        },
        "selection_rule": "Scenario challenger is evaluated only after freeze-time code, frozen input, model identity, and matrix Top-1/Top-3 replay gates pass.",
        "actual_result_used_after_replay_gate": True,
    }


def run_audit(root: Path | str, business_date: str, output_dir: Path | str | None = None) -> dict:
    """Run the PA-1 audit and write only the two requested output artifacts."""
    root = Path(root).resolve()
    output = Path(output_dir).resolve() if output_dir is not None else None
    before_hashes = _mutation_hashes(root)
    predictions, malformed_prediction_files = _load_predictions(root)
    exclusions = _load_exclusion_ids(root)
    ledger, malformed_ledger_rows = _load_ledger(root)
    records_by_id = {_record_id(record): record for record in predictions if _record_id(record)}
    current_records = [record for record in predictions if _record_date(record) == business_date]
    current_scored = [record for record in current_records if _record_score(record)]
    all_scored = [record for record in predictions if _record_score(record)]
    formal_rows = _verified_formal_rows(records_by_id, ledger, exclusions)
    replay_targets: list[dict] = []
    seen_replay_ids: set[str] = set()
    for record in [*current_scored, *(row["record"] for row in formal_rows)]:
        prediction_id = _record_id(record)
        if prediction_id and prediction_id not in seen_replay_ids:
            replay_targets.append(record)
            seen_replay_ids.add(prediction_id)
    replay_results = replay_frozen_records(replay_targets, root) if replay_targets else []
    replay_by_id = {str(row.get("prediction_id")): row for row in replay_results if row.get("prediction_id")}
    formal_replay_results: list[dict] = []
    for row in formal_rows:
        replay = replay_by_id.get(row["prediction_id"])
        if replay:
            formal_replay = dict(replay)
            formal_replay["actual_score"] = row.get("actual_score")
            formal_replay_results.append(formal_replay)
            if replay.get("replay_status") == "REPLAY_VALID":
                row["methods"]["scenario_challenger"] = replay.get("scenario_challenger")
        else:
            formal_replay_results.append(
                {
                    "prediction_id": row["prediction_id"],
                    "replay_status": "REPLAY_UNAVAILABLE",
                    "replay_reason": "REPLAY_RESULT_MISSING",
                    "actual_score": row.get("actual_score"),
                }
            )
    current_replay_ids = {_record_id(record) for record in current_scored}
    replay_summary = _replay_summary(
        [row for row in replay_results if row.get("prediction_id") in current_replay_ids],
        formal_replay_results,
        formal_rows,
    )
    production_versions = {str(record.get("release_version")) for record in predictions if record.get("release_version")}
    calibration = _calibration_audit(root, production_versions)
    dixon = _dixon_coles_audit(current_scored, len(formal_rows), calibration)
    method_summary = _summarise_method_rows(formal_rows)
    comparison_rows = _model_method_comparison(formal_rows)
    census = _current_census(root, business_date, current_records, exclusions)
    score_distribution = _distribution(_record_score(record) for record in current_scored)
    outcome_inconsistency_rows = [
        record for record in current_scored
        if outcome_consistency(_record_score(record), _probabilities(record)) is False
    ]
    persisted_scenario_available = sum(1 for record in current_scored if scenario_score_from_record(record))
    scenario_replay_current = replay_summary["current"]
    current_margins = _margin_audit(current_scored)
    current_margins["all_prediction_records"] = _margin_audit(all_scored)
    lambda_audit = _lambda_audit(current_scored)
    lambda_audit["all_prediction_records"] = _lambda_audit(all_scored)
    selector = _selector_audit(root)
    distribution_comparison = _production_distribution_comparison(current_scored, formal_rows)
    formal_threshold = _as_int((calibration.get("policy") or {}).get("full_review_samples")) or DEFAULT_CALIBRATION_REVIEW_SAMPLES
    scenario_pairs = [
        (row.get("frozen_matrix_map"), row.get("scenario_challenger"))
        for row in replay_results
        if row.get("replay_status") == "REPLAY_VALID" and row.get("scenario_challenger") and row.get("prediction_id") in current_replay_ids
    ]

    findings: list[dict] = []
    if score_distribution.get("count", 0) >= 10 and (score_distribution.get("mode_share") or 0) >= 0.8 and score_distribution.get("distinct_scores", 0) <= 5:
        findings.append(
            {
                "code": "SCORE_MODE_COLLAPSE",
                "severity": "P0_AUDIT_FLAG",
                "evidence": {
                    "mode_score": score_distribution.get("mode_score"),
                    "mode_count": score_distribution.get("counts", {}).get(score_distribution.get("mode_score"), 0),
                    "sample_count": score_distribution.get("count"),
                    "mode_share": score_distribution.get("mode_share"),
                    "distinct_scores": score_distribution.get("distinct_scores"),
                    "classification": "AUDIT_HEURISTIC_ONLY",
                },
                "interpretation": "Descriptive concentration flag; it is not a newly introduced production acceptance threshold.",
            }
        )
    if outcome_inconsistency_rows:
        findings.append(
            {
                "code": "OUTCOME_INCONSISTENCY",
                "severity": "P0_AUDIT_FLAG",
                "evidence": {
                    "count": len(outcome_inconsistency_rows),
                    "sample_count": len(current_scored),
                    "share": round(len(outcome_inconsistency_rows) / len(current_scored), 6) if current_scored else None,
                },
                "interpretation": "The frozen exact-score outcome is not the same as the frozen 1X2 leader for these records; this audit does not rewrite the official score.",
            }
        )
    if current_scored and persisted_scenario_available == 0:
        findings.append({
            "code": "SCENARIO_TRACE_NOT_PERSISTED",
            "severity": "AUDIT_LIMITATION",
            "evidence": {
                "current_records": len(current_scored),
                "trace_records": 0,
                "freeze_time_replay_valid": scenario_replay_current.get("replay_valid", 0),
                "freeze_time_replay_unavailable": scenario_replay_current.get("replay_unavailable", 0),
                "freeze_time_replay_mismatch": scenario_replay_current.get("replay_mismatch", 0),
            },
        })
    if calibration.get("active") is False and "calibrated" in str(calibration.get("model_family") or "").lower():
        findings.append({"code": "CALIBRATION_INACTIVE_MODEL_NAME_MISLEADING", "severity": "GOVERNANCE_NAMING", "evidence": {"model_family": calibration.get("model_family"), "status": calibration.get("status")}})
    if any(not value for value in (calibration.get("production_versions_in_compatible") or {}).values()):
        findings.append({"code": "PRODUCTION_VERSION_NOT_IN_CALIBRATION_COMPATIBLE_VERSIONS", "severity": "GOVERNANCE_REVIEW", "evidence": calibration.get("production_versions_in_compatible")})
    if dixon.get("independent_poisson_equivalent"):
        findings.append({"code": "DIXON_COLES_RHO_ZERO", "severity": "MODEL_AUDIT_LIMITATION", "evidence": {"rho_values": dixon.get("production_rho_values")}})
    if len(formal_rows) < formal_threshold:
        findings.append({"code": "SMALL_FORMAL_SAMPLE", "severity": "SAMPLE_LIMITATION", "evidence": {"verified_formal_samples": len(formal_rows), "full_review_samples": formal_threshold}})

    recommendations = [
        "KEEP_CURRENT_PRODUCTION_UNCHANGED",
        "KEEP_CA1_PAUSED",
    ]
    if outcome_inconsistency_rows:
        recommendations.append("SHADOW_OUTCOME_CONDITIONED_SELECTOR_FOR_EVALUATION_ONLY")
    if scenario_replay_current.get("replay_valid", 0) == 0:
        recommendations.append("PERSIST_SCENARIO_TRACE_BEFORE_ANY_SCENARIO_PROMOTION")
    else:
        recommendations.append("PERSIST_SCENARIO_TRACE_FOR_FUTURE_AUDIT_REPRODUCTION")
    recommendations.append("MORE_FORMAL_VERIFIED_SAMPLES_REQUIRED_BEFORE_CALIBRATION_OR_DIXON_COLES_PROMOTION")

    result: dict[str, Any] = {
        "audit_schema_version": AUDIT_SCHEMA_VERSION,
        "audit_name": "Prediction Sanity & Score Collapse Audit",
        "audit_mode": "READ_ONLY_SHADOW_EVALUATION",
        "sample_definition": {
            "current_business_date": business_date,
            "current_prediction_scope": "all stored prediction records with matching business_date and stored unique_score",
            "formal_evaluation_scope": "ledger rows with formal_prospective_eligible=true, verified result timestamp, regulation-time score, matching frozen prediction, and no exclusion",
            "verified_result_scope": "regulation_90m_plus_stoppage or an equivalent ledger row without an extra-time/penalty marker",
            "future_information_used_for_selection": False,
            "current_records_included": len(current_scored),
            "formal_verified_comparable_records": len(formal_rows),
        },
        "current_production_census": census,
        "current_score_distribution": score_distribution,
        "lambda_compression": lambda_audit,
        "selection_margin": current_margins,
        "current_selector_observation": {
            "official_score_mode": score_distribution.get("mode_score"),
            "matrix_map_equals_official_count": sum(matrix_map(_score_rows(record)) == _record_score(record) for record in current_scored),
            "matrix_map_equals_official_share": round(sum(matrix_map(_score_rows(record)) == _record_score(record) for record in current_scored) / len(current_scored), 6) if current_scored else None,
            "note": "The audit observes the stored matrix ranking; it does not recompute or replace the official score.",
        },
        "current_outcome_consistency": {
            "consistent_count": len(current_scored) - len(outcome_inconsistency_rows),
            "inconsistent_count": len(outcome_inconsistency_rows),
            "sample_count": len(current_scored),
            "rate": round((len(current_scored) - len(outcome_inconsistency_rows)) / len(current_scored), 6) if current_scored else None,
        },
        "scenario_challenger_audit": {
            "current_trace_available": persisted_scenario_available,
            "current_trace_missing": max(0, len(current_scored) - persisted_scenario_available),
            "trace_same_as_official": sum(official == scenario for official, scenario in scenario_pairs),
            "trace_different_from_official": sum(official != scenario for official, scenario in scenario_pairs),
            "freeze_time_replay": replay_summary["current"],
            "selector_code": selector,
            "official_score_unchanged": True,
            "note": "Scenario challengers are read from the freeze-time model result only after an isolated replay reproduces the frozen matrix Top-1/Top-3; no scenario score is promoted or written to production.",
        },
        "scenario_replay_summary": replay_summary,
        "scenario_replay_evidence": replay_results,
        "formal_scenario_replay_evidence": formal_replay_results,
        "dixon_coles_audit": dixon,
        "calibration_audit": calibration,
        "formal_sample": {
            "verified_regulation_sample_count": len(formal_rows),
            "full_review_threshold": formal_threshold,
            "sample_status": (
                "NO_COMPARABLE_FORMAL_SAMPLE"
                if not formal_rows
                else "DESCRIPTIVE_ONLY_BELOW_FULL_REVIEW_THRESHOLD"
                if len(formal_rows) < formal_threshold
                else "SUFFICIENT_FOR_DESCRIPTIVE_AUDIT"
            ),
            "formal_eligible_ledger_rows_read": sum(bool(row.get("formal_prospective_eligible")) for row in ledger),
            "excluded_ids": len(exclusions),
        },
        "score_methods": method_summary,
        "score_method_comparison_rows": len(comparison_rows),
        "representative_matches": _representative_matches(predictions, formal_rows),
        "strong_favourite_sanity_cases_current": _sanity_cases(current_scored, business_date=business_date, kind="strong_favourite"),
        "high_total_sanity_cases_current": _sanity_cases(current_scored, business_date=business_date, kind="high_total"),
        "low_total_sanity_cases_current": _sanity_cases(current_scored, business_date=business_date, kind="low_total"),
        "predicted_vs_actual_distributions": distribution_comparison,
        "selector_vs_underlying_model": {
            "selector": selector,
            "underlying_distribution_is_shared": True,
            "outcome_conditioned_scope": "OUTCOME_CONDITIONED_STORED_TOPK_MAP",
            "interpretation": "Matrix MAP and outcome-conditioned MAP use the same stored frozen candidate set; the outcome-conditioned result is not a full 8x8 matrix branch MAP and this audit does not change the production selector.",
        },
        "findings": findings,
        "recommendations": recommendations,
        "ca1_decision": "KEEP_PAUSED",
        "data_quality": {
            "malformed_prediction_files": malformed_prediction_files,
            "malformed_ledger_rows": malformed_ledger_rows,
            "exclusion_id_count": len(exclusions),
        },
        "ui_surface_audit": {
            "dashboard_latest_present": (root / "data" / "prediction_dashboard" / "latest.html").exists(),
            "dashboard_contains_primary_score_label": "首推比分" in ((root / "data" / "prediction_dashboard" / "latest.html").read_text(encoding="utf-8", errors="replace") if (root / "data" / "prediction_dashboard" / "latest.html").exists() else ""),
            "note": "UI is observed only; no dashboard or production UI file is changed.",
        },
        "mutation_safety": {},
    }
    after_hashes = _mutation_hashes(root)
    result["mutation_safety"] = {
        "before": before_hashes,
        "after": after_hashes,
        "unchanged": before_hashes == after_hashes,
        "write_scope": [str(output) if output else "caller-selected output directory"],
    }

    if output is not None:
        output.mkdir(parents=True, exist_ok=True)
        _write_json(output / "score_collapse_audit.json", result)
        fieldnames = [
            "match_id", "business_date", "home", "away", "actual_score", "matrix_map",
            "outcome_conditioned_map", "scenario_challenger", "dc_shadow", "matrix_hit",
            "outcome_hit", "scenario_hit", "dc_hit", "lambda_home", "lambda_away",
            "market_total", "market_handicap", "fusion_1x2_leader", "top1_probability", "top2_probability", "top1_top2_gap",
        ]
        with (output / "score_method_comparison.csv").open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows({field: row.get(field) for field in fieldnames} for row in comparison_rows)
    return result


def _default_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _default_business_date() -> str:
    if ZoneInfo is not None:
        try:
            return datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()
        except Exception:
            pass
    return datetime.now().date().isoformat()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the read-only prediction sanity and score-collapse audit.")
    parser.add_argument("--root", type=Path, default=_default_root())
    parser.add_argument("--date", dest="business_date", default=_default_business_date(), help="Business date to audit, YYYY-MM-DD.")
    parser.add_argument("--output-dir", type=Path, help="Output directory; defaults to a system TEMP directory.")
    args = parser.parse_args(argv)
    if args.output_dir is None:
        args.output_dir = Path(tempfile.mkdtemp(prefix="football-pa1-score-audit-"))
    try:
        date.fromisoformat(args.business_date)
    except ValueError:
        parser.error("--date must be YYYY-MM-DD")
    result = run_audit(args.root, args.business_date, args.output_dir)
    print(json.dumps({
        "status": "COMPLETE",
        "audit_schema_version": result["audit_schema_version"],
        "business_date": args.business_date,
        "current_universe": result["current_production_census"].get("universe_fixture_count"),
        "current_predictions": result["current_production_census"].get("frozen_prediction_count"),
        "findings": [finding["code"] for finding in result["findings"]],
        "mutation_unchanged": result["mutation_safety"].get("unchanged"),
        "output_dir": str(args.output_dir.resolve()),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
