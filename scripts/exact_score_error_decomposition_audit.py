"""Audit exact-score residuals by intensity, shape, and competition universe.

The audit consumes only the pinned frozen cohort and existing repository
metadata.  It does not refit, calibrate, or mutate any production artifact.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from itertools import combinations
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = PROJECT_ROOT / "data" / "prediction_quality" / "pred_trust_2" / "pinned_cohort_manifest.json"
DEFAULT_AUDIT = PROJECT_ROOT / "data" / "prediction_quality" / "pred_trust_1" / "audit_2026-08-30.json"
DEFAULT_JOBS_ROOT = PROJECT_ROOT / "data" / "base_prediction_jobs"
DEFAULT_PREDICTION_ROOT = PROJECT_ROOT / "data" / "model_governance" / "predictions"
DEFAULT_RESULT_ROOT = PROJECT_ROOT / "data" / "postmatch_automation" / "results"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "audit-artifact"

MILESTONE = "EXACT-SCORE-ERROR-DECOMPOSITION-1-CORRECTION"
CHAMPION_MODEL_FAMILY = "recent_form_market_calibrated_poisson_v2"
BOOTSTRAP_SEED = 20260903
DEFAULT_BOOTSTRAP_REPLICATES = 4000
MIN_UNIVERSE_SAMPLE = 20
SCORE_RE = re.compile(r"^(\d+)\s*-\s*(\d+)$")

UNIVERSES = (
    "CLUB_BIG5_TOP_LEAGUE",
    "CLUB_OTHER_TOP_LEAGUE",
    "CLUB_LOWER_DIVISION",
    "CLUB_DOMESTIC_CUP",
    "CLUB_CONTINENTAL",
    "NATIONAL_TEAM",
    "UNKNOWN_OR_MIXED",
)

SHAPE_METRICS = (
    "total_0",
    "total_1",
    "total_2",
    "total_3",
    "total_4_plus",
    "total_5_plus",
    "total_6_plus",
    "draw",
    "btts",
    "score_0_0",
    "score_1_1",
)

CORE_SHAPE_METRICS = ("draw", "btts", "score_1_1")
TAIL_SHAPE_METRICS = (
    "total_0",
    "total_1",
    "total_2",
    "total_3",
    "total_4_plus",
    "total_5_plus",
    "total_6_plus",
    "score_0_0",
)

LAMBDA_TOTAL_BINS = (
    ("[0,2)", 0.0, 2.0, False),
    ("[2,2.5)", 2.0, 2.5, False),
    ("[2.5,3)", 2.5, 3.0, False),
    ("[3,3.5)", 3.0, 3.5, False),
    ("[3.5,4)", 3.5, 4.0, False),
    ("[4,+)", 4.0, math.inf, True),
)

# These are competition labels already present in the repository's pinned
# cohort metadata.  No team name, country inference, or external lookup is
# used.  Keep the sets explicit so an unfamiliar label remains unknown.
BIG5_TOP_LEAGUE_NAMES = frozenset(
    {
        "\u897f\u73ed\u7259\u7532\u7ea7\u8054\u8d5b",
        "\u82f1\u683c\u5170\u8d85\u7ea7\u8054\u8d5b",
        "\u610f\u5927\u5229\u7532\u7ea7\u8054\u8d5b",
        "\u5fb7\u56fd\u7532\u7ea7\u8054\u8d5b",
        "\u6cd5\u56fd\u7532\u7ea7\u8054\u8d5b",
    }
)

OTHER_TOP_LEAGUE_NAMES = frozenset(
    {
        "\u8377\u5170\u7532\u7ea7\u8054\u8d5b",
        "\u97e9\u56fd\u804c\u4e1a\u8054\u8d5b",
        "\u745e\u5178\u8d85\u7ea7\u8054\u8d5b",
        "\u65e5\u672c\u804c\u4e1a\u8054\u8d5b",
        "\u8461\u8404\u7259\u8d85\u7ea7\u8054\u8d5b",
        "\u632a\u5a01\u8d85\u7ea7\u8054\u8d5b",
        "\u5df4\u897f\u7532\u7ea7\u8054\u8d5b",
        "\u82ac\u5170\u8d85\u7ea7\u8054\u8d5b",
        "\u6c99\u7279\u804c\u4e1a\u8054\u8d5b",
        "\u7f8e\u56fd\u804c\u4e1a\u5927\u8054\u76df",
    }
)

LOWER_DIVISION_NAMES = frozenset(
    {
        "\u82f1\u683c\u5170\u51a0\u519b\u8054\u8d5b",
        "\u5fb7\u56fd\u4e59\u7ea7\u8054\u8d5b",
        "\u65e5\u672c\u4e59\u7ea7\u8054\u8d5b",
        "\u6cd5\u56fd\u4e59\u7ea7\u8054\u8d5b",
        "\u8377\u5170\u4e59\u7ea7\u8054\u8d5b",
    }
)

DOMESTIC_CUP_NAMES = frozenset(
    {
        "\u5df4\u897f\u676f",
        "\u5fb7\u56fd\u8d85\u7ea7\u676f",
        "\u97e9\u56fd\u676f",
        "\u82f1\u683c\u5170\u8054\u8d5b\u676f",
        "\u82f1\u683c\u5170\u793e\u533a\u76fe\u676f",
    }
)

CONTINENTAL_NAMES = frozenset(
    {
        "\u6b27\u7f57\u5df4\u8054\u8d5b",
        "\u6b27\u6d32\u51a0\u519b\u8054\u8d5b",
        "\u5357\u7f8e\u89e3\u653e\u8005\u676f",
    }
)

NATIONAL_TEAM_NAMES = frozenset(
    {
        "\u56fd\u9645\u53cb\u8c0a\u8d5b",
        "\u4e16\u754c\u676f",
        "\u4e16\u754c\u676f\u9884\u9009\u8d5b",
        "\u6b27\u6d32\u676f",
        "\u4e9a\u6d32\u676f",
        "\u7f8e\u6d32\u676f",
        "\u975e\u6d32\u676f",
        "\u6b27\u6d32\u56fd\u5bb6\u8054\u8d5b",
    }
)


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"missing JSON asset: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON asset: {path}: {exc}") from exc


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_json_sha256(value: Any) -> str:
    """Hash JSON semantics independently of file formatting or line endings."""

    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _prediction_record_hash(record: Mapping[str, Any]) -> str:
    """Hash a pinned prediction record using the PR #157 canonical scheme."""

    return _canonical_json_sha256(dict(record))


def _validate_snapshot_integrity(
    prediction_id: str,
    prediction: Mapping[str, Any],
    snapshot: Mapping[str, Any],
) -> None:
    """Validate portable semantic integrity for a frozen model-input snapshot."""

    canonical_input = snapshot.get("input")
    if not isinstance(canonical_input, dict):
        raise ValueError(f"input snapshot has no canonical input object for {prediction_id}")

    recomputed_digest = _canonical_json_sha256(canonical_input)
    snapshot_digest = _text(
        snapshot.get("canonical_model_input_sha256") or snapshot.get("canonical_input_sha256")
    )
    prediction_digest = _text(
        prediction.get("canonical_model_input_sha256") or prediction.get("input_sha256")
    )
    embedded_snapshot = prediction.get("input_snapshot")
    if not isinstance(embedded_snapshot, Mapping):
        raise ValueError(f"embedded input snapshot missing for {prediction_id}")
    embedded_digest = _text(
        embedded_snapshot.get("canonical_model_input_sha256")
        or embedded_snapshot.get("canonical_input_sha256")
    )
    if not snapshot_digest or recomputed_digest != snapshot_digest:
        raise ValueError(f"snapshot canonical input digest mismatch for {prediction_id}")
    if prediction_digest != snapshot_digest or embedded_digest != snapshot_digest:
        raise ValueError(f"snapshot/record canonical digest mismatch for {prediction_id}")

    snapshot_id = _text(snapshot.get("snapshot_id"))
    embedded_snapshot_id = _text(embedded_snapshot.get("snapshot_id"))
    if not snapshot_id or embedded_snapshot_id != snapshot_id:
        raise ValueError(f"snapshot ID mismatch for {prediction_id}")

    source_cutoff_at = _text(snapshot.get("source_cutoff_at"))
    prediction_source_cutoff_at = _text(prediction.get("source_cutoff_at"))
    embedded_source_cutoff_at = _text(embedded_snapshot.get("source_cutoff_at"))
    if (
        not source_cutoff_at
        or prediction_source_cutoff_at != source_cutoff_at
        or embedded_source_cutoff_at != source_cutoff_at
    ):
        raise ValueError(f"snapshot source cutoff mismatch for {prediction_id}")


def _text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _finite_float(value: Any, label: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} is not numeric: {value!r}") from exc
    if not math.isfinite(number):
        raise ValueError(f"{label} is not finite: {value!r}")
    return number


def _parse_datetime(value: Any, label: str) -> datetime:
    raw = _text(value)
    if not raw:
        raise ValueError(f"{label} is missing")
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise ValueError(f"{label} is not ISO-8601: {value!r}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _repo_relative_path(root: Path, reference: str) -> Path:
    candidate = (root / reference).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError(f"asset reference escapes project root: {reference!r}") from exc
    return candidate


def _stable_seed(seed: int, label: str) -> int:
    digest = hashlib.sha256(label.encode("utf-8")).hexdigest()
    return int(seed) + int(digest[:8], 16)


def classify_competition(competition: str | None) -> str:
    """Classify an existing competition label without using team names."""

    name = _text(competition)
    if not name:
        return "UNKNOWN_OR_MIXED"
    if name in NATIONAL_TEAM_NAMES:
        return "NATIONAL_TEAM"
    if name in CONTINENTAL_NAMES:
        return "CLUB_CONTINENTAL"
    if name in BIG5_TOP_LEAGUE_NAMES:
        return "CLUB_BIG5_TOP_LEAGUE"
    if name in OTHER_TOP_LEAGUE_NAMES:
        return "CLUB_OTHER_TOP_LEAGUE"
    if name in LOWER_DIVISION_NAMES:
        return "CLUB_LOWER_DIVISION"
    if name in DOMESTIC_CUP_NAMES:
        return "CLUB_DOMESTIC_CUP"
    return "UNKNOWN_OR_MIXED"


def _load_competition_metadata(jobs_root: Path, selected_match_ids: set[str]) -> dict[str, dict[str, Any]]:
    """Read deterministic league metadata only for pinned match IDs."""

    candidates: dict[str, set[str]] = defaultdict(set)
    for path in sorted(jobs_root.glob("*.json")):
        payload = _read_json(path)
        if not isinstance(payload, Mapping):
            continue
        for section in ("jobs", "removed_jobs"):
            rows = payload.get(section) or []
            if not isinstance(rows, list):
                continue
            for row in rows:
                if not isinstance(row, Mapping):
                    continue
                match_id = _text(row.get("match_id"))
                if match_id not in selected_match_ids:
                    continue
                competition = _text(row.get("league") or row.get("competition"))
                if competition:
                    candidates[match_id].add(competition)

    metadata: dict[str, dict[str, Any]] = {}
    for match_id in selected_match_ids:
        values = sorted(candidates.get(match_id, set()))
        metadata[match_id] = {
            "competition": values[0] if len(values) == 1 else None,
            "candidates": values,
            "metadata_status": "MATCHED" if len(values) == 1 else "AMBIGUOUS" if values else "MISSING",
        }
    return metadata


def _parse_score(value: Any, label: str) -> tuple[int, int]:
    match = SCORE_RE.match(_text(value))
    if not match:
        raise ValueError(f"{label} is not a score: {value!r}")
    return int(match.group(1)), int(match.group(2))


def _validate_frozen_prediction(
    record: Mapping[str, Any],
    prediction: Mapping[str, Any],
    snapshot: Mapping[str, Any],
    snapshot_reference: str,
) -> tuple[float, float]:
    prediction_id = _text(record.get("prediction_id"))
    if _text(prediction.get("prediction_id")) != prediction_id:
        raise ValueError(f"prediction ID mismatch for {prediction_id}")
    if _text(prediction.get("match_id")) != _text(record.get("match_id")):
        raise ValueError(f"match ID mismatch for {prediction_id}")
    if _text(prediction.get("match_key")) != _text(record.get("match_key")):
        raise ValueError(f"match key mismatch for {prediction_id}")
    if _text(prediction.get("input_snapshot_ref") or prediction.get("model_input_snapshot_ref")) != snapshot_reference:
        raise ValueError(f"input snapshot reference mismatch for {prediction_id}")
    if _text(snapshot.get("snapshot_ref")) != snapshot_reference:
        raise ValueError(f"snapshot self-reference mismatch for {prediction_id}")
    if prediction.get("model_role") != "champion":
        raise ValueError(f"non-Champion prediction in pinned cohort: {prediction_id}")
    if prediction.get("model_core_version") != CHAMPION_MODEL_FAMILY:
        raise ValueError(f"unexpected model core for {prediction_id}: {prediction.get('model_core_version')!r}")
    if prediction.get("model_family") != CHAMPION_MODEL_FAMILY:
        raise ValueError(f"unexpected model family for {prediction_id}: {prediction.get('model_family')!r}")
    if prediction.get("prediction_status") != "formal" or prediction.get("formal_eligible") is not True:
        raise ValueError(f"prediction is not formal/frozen-eligible: {prediction_id}")
    if prediction.get("model_formal_eligible") is not True:
        raise ValueError(f"prediction model eligibility is not true: {prediction_id}")

    kickoff = _parse_datetime(record.get("kickoff_at") or prediction.get("kickoff_at"), f"kickoff_at[{prediction_id}]")
    source_cutoff = _parse_datetime(
        prediction.get("source_cutoff_at") or snapshot.get("source_cutoff_at"),
        f"source_cutoff_at[{prediction_id}]",
    )
    freeze_created = _parse_datetime(prediction.get("freeze_created_at"), f"freeze_created_at[{prediction_id}]")
    if source_cutoff > kickoff or freeze_created > kickoff:
        raise ValueError(f"prematch cutoff/freeze is after kickoff for {prediction_id}")

    lambda_home = _finite_float(prediction.get("lambda_home"), f"lambda_home[{prediction_id}]")
    lambda_away = _finite_float(prediction.get("lambda_away"), f"lambda_away[{prediction_id}]")
    if lambda_home <= 0 or lambda_away <= 0:
        raise ValueError(f"non-positive lambda in {prediction_id}")
    rho = _finite_float(prediction.get("rho"), f"rho[{prediction_id}]")
    if abs(rho) > 1e-12:
        raise ValueError(f"non-zero rho in {prediction_id}: {rho}")
    return lambda_home, lambda_away


def _load_cohort(
    root: Path,
    manifest_path: Path,
    audit_path: Path,
    jobs_root: Path,
    prediction_root: Path,
    result_root: Path,
) -> dict[str, Any]:
    manifest = _read_json(manifest_path)
    audit = _read_json(audit_path)
    if not isinstance(manifest, Mapping) or not isinstance(audit, Mapping):
        raise ValueError("manifest and audit must be JSON objects")

    selected_records = manifest.get("selected_records") or []
    verified_ids = list(manifest.get("verified_prediction_ids") or [])
    if not isinstance(selected_records, list) or not isinstance(verified_ids, list):
        raise ValueError("manifest selected_records/verified_prediction_ids must be lists")
    selected_by_id: dict[str, Mapping[str, Any]] = {}
    for record in selected_records:
        if not isinstance(record, Mapping):
            raise ValueError("selected record is not an object")
        prediction_id = _text(record.get("prediction_id"))
        if not prediction_id or prediction_id in selected_by_id:
            raise ValueError(f"selected prediction IDs are not unique: {prediction_id!r}")
        selected_by_id[prediction_id] = record
    selected_match_ids = {_text(row.get("match_id")) for row in selected_records}
    selected_match_keys = {_text(row.get("match_key")) for row in selected_records}
    if len(selected_match_ids) != len(selected_records) or len(selected_match_keys) != len(selected_records):
        raise ValueError("pinned cohort is not one unique match per observation")
    verified_set = {_text(value) for value in verified_ids}
    if len(verified_set) != len(verified_ids):
        raise ValueError("verified prediction IDs are not unique")
    if not verified_set.issubset(selected_by_id):
        raise ValueError("verified prediction IDs are not a subset of selected records")

    audit_rows = audit.get("prospective_evaluation", {}).get("evaluated_rows") or []
    audit_by_id: dict[str, Mapping[str, Any]] = {}
    for row in audit_rows:
        if not isinstance(row, Mapping):
            continue
        prediction_id = _text(row.get("prediction_id"))
        if prediction_id:
            if prediction_id in audit_by_id:
                raise ValueError(f"duplicate audit row for {prediction_id}")
            audit_by_id[prediction_id] = row
    if set(audit_by_id).intersection(verified_set) != verified_set:
        missing = sorted(verified_set - set(audit_by_id))
        raise ValueError(f"verified IDs missing from pred_trust_1 evaluated rows: {missing[:5]}")

    competition_metadata = _load_competition_metadata(jobs_root, selected_match_ids)
    selected_rows: list[dict[str, Any]] = []
    verified_rows: list[dict[str, Any]] = []
    raw_snapshot_hash_status = {
        "matched_n": 0,
        "mismatched_n": 0,
        "missing_manifest_hash_n": 0,
    }

    for record in selected_records:
        prediction_id = _text(record.get("prediction_id"))
        match_id = _text(record.get("match_id"))
        match_key = _text(record.get("match_key"))
        snapshot_reference = _text(record.get("input_snapshot_ref"))
        if not snapshot_reference:
            raise ValueError(f"missing input snapshot reference for {prediction_id}")
        snapshot_path = _repo_relative_path(root, snapshot_reference)
        expected_raw_snapshot_hash = _text(record.get("input_snapshot_sha256"))
        actual_raw_snapshot_hash = _sha256_file(snapshot_path)
        if not expected_raw_snapshot_hash:
            raw_snapshot_hash_status["missing_manifest_hash_n"] += 1
        elif actual_raw_snapshot_hash == expected_raw_snapshot_hash:
            raw_snapshot_hash_status["matched_n"] += 1
        else:
            raw_snapshot_hash_status["mismatched_n"] += 1
        snapshot = _read_json(snapshot_path)
        prediction_path = prediction_root / f"{prediction_id}.json"
        prediction = _read_json(prediction_path)
        expected_record_hash = _text(record.get("record_sha256"))
        if not expected_record_hash:
            raise ValueError(f"missing pinned prediction record hash for {prediction_id}")
        if _prediction_record_hash(prediction) != expected_record_hash:
            raise ValueError(f"pinned prediction content changed for {prediction_id}")
        _validate_snapshot_integrity(prediction_id, prediction, snapshot)
        lambda_home, lambda_away = _validate_frozen_prediction(record, prediction, snapshot, snapshot_reference)

        metadata = competition_metadata[match_id]
        competition = metadata.get("competition")
        universe = classify_competition(competition)
        selected_row = {
            "prediction_id": prediction_id,
            "match_id": match_id,
            "match_key": match_key,
            "competition": competition,
            "competition_candidates": metadata.get("candidates") or [],
            "competition_metadata_status": metadata.get("metadata_status"),
            "universe": universe,
            "kickoff_at": _text(record.get("kickoff_at") or prediction.get("kickoff_at")),
            "lambda_home": lambda_home,
            "lambda_away": lambda_away,
            "lambda_total": lambda_home + lambda_away,
        }
        selected_rows.append(selected_row)
        if prediction_id not in verified_set:
            continue

        audit_row = audit_by_id[prediction_id]
        if _text(audit_row.get("match_key")) != match_key or _text(audit_row.get("match_id")) != match_id:
            raise ValueError(f"audit identity mismatch for {prediction_id}")
        result_path = result_root / f"{match_key}.json"
        result = _read_json(result_path)
        if not isinstance(result, Mapping):
            raise ValueError(f"result asset is not an object for {prediction_id}")
        if _text(result.get("match_key")) != match_key:
            raise ValueError(f"result match key mismatch for {prediction_id}")
        if result.get("scope") != "regulation_90m_plus_stoppage":
            raise ValueError(f"result scope is not 90m+stoppage for {prediction_id}")
        kickoff = _parse_datetime(selected_row["kickoff_at"], f"kickoff_at[{prediction_id}]")
        verified_at = _parse_datetime(result.get("verified_at"), f"verified_at[{prediction_id}]")
        if verified_at <= kickoff:
            raise ValueError(f"result verification is not postmatch for {prediction_id}")
        actual_home, actual_away = _parse_score(result.get("result_90m"), f"result_90m[{prediction_id}]")
        audit_score = _text(audit_row.get("actual_score"))
        if audit_score and audit_score != _text(result.get("result_90m")):
            raise ValueError(f"audit/result score mismatch for {prediction_id}")
        if int(result.get("home_score")) != actual_home or int(result.get("away_score")) != actual_away:
            raise ValueError(f"result score fields disagree for {prediction_id}")
        verified_rows.append(
            {
                **selected_row,
                "actual_home": actual_home,
                "actual_away": actual_away,
                "actual_total": actual_home + actual_away,
                "result_asset": str(result_path.relative_to(root)).replace("\\", "/"),
                "result_verified_at": _text(result.get("verified_at")),
            }
        )

    if len(selected_rows) != len(selected_records) or len(verified_rows) != len(verified_set):
        raise ValueError("cohort loading did not preserve pinned/verified counts")
    if int(manifest.get("selected_match_count") or 0) != len(selected_rows):
        raise ValueError("manifest selected_match_count disagrees with selected records")
    if int(manifest.get("verified_match_count") or 0) != len(verified_rows):
        raise ValueError("manifest verified_match_count disagrees with verified records")

    return {
        "manifest": manifest,
        "audit": audit,
        "selected_rows": selected_rows,
        "verified_rows": verified_rows,
        "competition_metadata": competition_metadata,
        "snapshot_integrity": {
            "method": "canonical_json_semantic_integrity",
            "canonical_json_sha256": {
                "serialization": "json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')) encoded as UTF-8",
                "snapshot_fields": ["canonical_model_input_sha256", "canonical_input_sha256"],
                "prediction_record_fields": ["canonical_model_input_sha256", "input_sha256"],
                "embedded_input_snapshot_fields": ["canonical_model_input_sha256", "canonical_input_sha256"],
            },
            "pinned_prediction_record_content_hash": "manifest record_sha256 versus canonical prediction JSON",
            "identity_fields": [
                "prediction_id",
                "match_id",
                "match_key",
                "input_snapshot_ref",
                "snapshot_id",
                "source_cutoff_at",
            ],
            "raw_file_sha256": {
                "manifest_field": "input_snapshot_sha256",
                "status": "legacy_non_portable_evidence_only",
                "mismatch_is_fail_condition": False,
                **raw_snapshot_hash_status,
            },
        },
        "manifest_path": str(manifest_path.relative_to(root)).replace("\\", "/"),
        "audit_path": str(audit_path.relative_to(root)).replace("\\", "/"),
    }


def _poisson_pmf(mean: float, goals: int) -> float:
    return math.exp(-mean) * mean**goals / math.factorial(goals)


def _draw_probability(lambda_home: float, lambda_away: float) -> float:
    home_probability = math.exp(-lambda_home)
    away_probability = math.exp(-lambda_away)
    total = 0.0
    for goals in range(100):
        total += home_probability * away_probability
        next_goals = goals + 1
        home_probability *= lambda_home / next_goals
        away_probability *= lambda_away / next_goals
        if home_probability == 0.0 and away_probability == 0.0:
            break
    return max(0.0, min(1.0, total))


def expected_shape_probabilities(lambda_home: float, lambda_away: float) -> dict[str, float]:
    """Return independent-Poisson event probabilities for one fixture."""

    lambda_home = _finite_float(lambda_home, "lambda_home")
    lambda_away = _finite_float(lambda_away, "lambda_away")
    if lambda_home < 0 or lambda_away < 0:
        raise ValueError("lambda values must be non-negative")
    lambda_total = lambda_home + lambda_away
    total_probabilities = [_poisson_pmf(lambda_total, goals) for goals in range(7)]
    return {
        "total_0": total_probabilities[0],
        "total_1": total_probabilities[1],
        "total_2": total_probabilities[2],
        "total_3": total_probabilities[3],
        "total_4_plus": max(0.0, 1.0 - sum(total_probabilities[:4])),
        "total_5_plus": max(0.0, 1.0 - sum(total_probabilities[:5])),
        "total_6_plus": max(0.0, 1.0 - sum(total_probabilities[:6])),
        "draw": _draw_probability(lambda_home, lambda_away),
        "btts": (1.0 - math.exp(-lambda_home)) * (1.0 - math.exp(-lambda_away)),
        "score_0_0": math.exp(-lambda_total),
        "score_1_1": lambda_home * lambda_away * math.exp(-lambda_total),
    }


def _actual_shape_flags(actual_home: int, actual_away: int) -> dict[str, bool]:
    total = actual_home + actual_away
    return {
        "total_0": total == 0,
        "total_1": total == 1,
        "total_2": total == 2,
        "total_3": total == 3,
        "total_4_plus": total >= 4,
        "total_5_plus": total >= 5,
        "total_6_plus": total >= 6,
        "draw": actual_home == actual_away,
        "btts": actual_home > 0 and actual_away > 0,
        "score_0_0": actual_home == 0 and actual_away == 0,
        "score_1_1": actual_home == 1 and actual_away == 1,
    }


def _sample_poisson(mean: float, rng: random.Random) -> int:
    """Sample a Poisson variate without adding a numerical dependency."""

    probability = math.exp(-mean)
    cumulative = probability
    goals = 0
    threshold = rng.random()
    while threshold > cumulative:
        goals += 1
        probability *= mean / goals
        cumulative += probability
        if goals >= 1000:
            return goals
    return goals


def _quantile(values: list[float], probability: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = int(math.floor(position))
    upper = min(len(ordered) - 1, lower + 1)
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def run_parametric_shape_bootstrap(
    rows: Iterable[Mapping[str, Any]],
    *,
    seed: int = BOOTSTRAP_SEED,
    replicates: int = DEFAULT_BOOTSTRAP_REPLICATES,
) -> dict[str, Any]:
    """Run the raw frozen-lambda shape diagnostic under a fixed seed.

    This intentionally keeps the original lambdas unchanged.  Its residuals
    describe the complete frozen distribution, but are not used on their own
    to classify ``DISTRIBUTION_SHAPE``.
    """

    if replicates < 1:
        raise ValueError("bootstrap replicates must be positive")
    materialized = list(rows)
    if not materialized:
        return {
            "diagnostic": "RAW_SHAPE_DIAGNOSTIC",
            "sample_count": 0,
            "seed": seed,
            "replicates": replicates,
            "metrics": {},
        }

    expected_counts = Counter()
    observed_counts = Counter()
    for row in materialized:
        probabilities = expected_shape_probabilities(row["lambda_home"], row["lambda_away"])
        actuals = _actual_shape_flags(int(row["actual_home"]), int(row["actual_away"]))
        for metric in SHAPE_METRICS:
            expected_counts[metric] += probabilities[metric]
            observed_counts[metric] += int(actuals[metric])

    rng = random.Random(seed)
    bootstrap_differences = {metric: [] for metric in SHAPE_METRICS}
    for _ in range(replicates):
        simulated_counts = Counter()
        for row in materialized:
            simulated_home = _sample_poisson(float(row["lambda_home"]), rng)
            simulated_away = _sample_poisson(float(row["lambda_away"]), rng)
            flags = _actual_shape_flags(simulated_home, simulated_away)
            for metric in SHAPE_METRICS:
                simulated_counts[metric] += int(flags[metric])
        for metric in SHAPE_METRICS:
            bootstrap_differences[metric].append(simulated_counts[metric] - expected_counts[metric])

    sample_count = len(materialized)
    metrics: dict[str, dict[str, Any]] = {}
    for metric in SHAPE_METRICS:
        observed_count = int(observed_counts[metric])
        expected_count = float(expected_counts[metric])
        residual_count = observed_count - expected_count
        null_values = bootstrap_differences[metric]
        p_value = (
            1.0
            + sum(abs(value) >= abs(residual_count) for value in null_values)
        ) / (len(null_values) + 1.0)
        null_ci = [_quantile(null_values, 0.025), _quantile(null_values, 0.975)]
        metrics[metric] = {
            "observed_count": observed_count,
            "expected_count": expected_count,
            "residual_count_observed_minus_expected": residual_count,
            "observed_rate": observed_count / sample_count,
            "expected_rate": expected_count / sample_count,
            "residual_rate_observed_minus_expected": residual_count / sample_count,
            "parametric_bootstrap_null_ci_95_count": null_ci,
            "parametric_bootstrap_null_ci_95_rate": [
                value / sample_count if value is not None else None for value in null_ci
            ],
            "raw_p_value": p_value,
            "two_sided_p_value": p_value,
        }
    return {
        "diagnostic": "RAW_SHAPE_DIAGNOSTIC",
        "sample_count": sample_count,
        "seed": seed,
        "replicates": replicates,
        "distribution": "independent_poisson_lambda_home_lambda_away_rho_0",
        "metrics": metrics,
    }


def _holm_bonferroni(p_values: Mapping[str, float]) -> dict[str, float]:
    """Return Holm-Bonferroni adjusted p-values in the original metric order."""

    ordered = sorted(p_values.items(), key=lambda item: (item[1], item[0]))
    adjusted: dict[str, float] = {}
    running_max = 0.0
    metric_count = len(ordered)
    for rank, (metric, p_value) in enumerate(ordered):
        candidate = min(1.0, float(p_value) * (metric_count - rank))
        running_max = max(running_max, candidate)
        adjusted[metric] = running_max
    return adjusted


def estimate_mean_conditioning_scales(rows: Iterable[Mapping[str, Any]]) -> dict[str, float]:
    """Estimate the postmatch-only home/away nuisance scales from a cohort."""

    materialized = list(rows)
    if not materialized:
        return {"scale_home": 1.0, "scale_away": 1.0}
    original_home_sum = sum(_finite_float(row["lambda_home"], "lambda_home") for row in materialized)
    original_away_sum = sum(_finite_float(row["lambda_away"], "lambda_away") for row in materialized)
    if original_home_sum <= 0 or original_away_sum <= 0:
        raise ValueError("original lambda sums must be positive")
    actual_home_sum = sum(int(row["actual_home"]) for row in materialized)
    actual_away_sum = sum(int(row["actual_away"]) for row in materialized)
    return {
        "scale_home": actual_home_sum / original_home_sum,
        "scale_away": actual_away_sum / original_away_sum,
    }


def run_mean_conditioned_shape_bootstrap(
    rows: Iterable[Mapping[str, Any]],
    *,
    seed: int = BOOTSTRAP_SEED,
    replicates: int = DEFAULT_BOOTSTRAP_REPLICATES,
) -> dict[str, Any]:
    """Audit shape after removing the observed mean/intensity bias.

    The observed nuisance scales are estimated only for this postmatch
    diagnostic.  Every parametric bootstrap replicate simulates from the
    observed conditioned lambdas, re-estimates both scales against the
    original frozen lambdas, and recomputes its own conditioned expectations.
    """

    if replicates < 1:
        raise ValueError("bootstrap replicates must be positive")
    materialized = list(rows)
    if not materialized:
        return {
            "diagnostic": "MEAN_CONDITIONED_SHAPE",
            "sample_count": 0,
            "seed": seed,
            "replicates": replicates,
            "metrics": {},
        }

    scales = estimate_mean_conditioning_scales(materialized)
    scale_home = scales["scale_home"]
    scale_away = scales["scale_away"]
    original_home = [
        _finite_float(row["lambda_home"], "lambda_home") for row in materialized
    ]
    original_away = [
        _finite_float(row["lambda_away"], "lambda_away") for row in materialized
    ]
    original_home_sum = sum(original_home)
    original_away_sum = sum(original_away)
    conditioned_pairs = [
        (lambda_home * scale_home, lambda_away * scale_away)
        for lambda_home, lambda_away in zip(original_home, original_away)
    ]

    expected_counts = Counter()
    observed_counts = Counter()
    for row, (conditioned_home, conditioned_away) in zip(materialized, conditioned_pairs):
        probabilities = expected_shape_probabilities(conditioned_home, conditioned_away)
        actuals = _actual_shape_flags(int(row["actual_home"]), int(row["actual_away"]))
        for metric in SHAPE_METRICS:
            expected_counts[metric] += probabilities[metric]
            observed_counts[metric] += int(actuals[metric])

    rng = random.Random(seed)
    bootstrap_differences = {metric: [] for metric in SHAPE_METRICS}
    for _ in range(replicates):
        simulated_scores: list[tuple[int, int]] = []
        simulated_home_sum = 0
        simulated_away_sum = 0
        for conditioned_home, conditioned_away in conditioned_pairs:
            simulated_home = _sample_poisson(conditioned_home, rng)
            simulated_away = _sample_poisson(conditioned_away, rng)
            simulated_scores.append((simulated_home, simulated_away))
            simulated_home_sum += simulated_home
            simulated_away_sum += simulated_away

        replicate_scale_home = simulated_home_sum / original_home_sum
        replicate_scale_away = simulated_away_sum / original_away_sum
        replicate_expected_counts = Counter()
        simulated_counts = Counter()
        for index, (simulated_home, simulated_away) in enumerate(simulated_scores):
            replicate_probabilities = expected_shape_probabilities(
                original_home[index] * replicate_scale_home,
                original_away[index] * replicate_scale_away,
            )
            flags = _actual_shape_flags(simulated_home, simulated_away)
            for metric in SHAPE_METRICS:
                replicate_expected_counts[metric] += replicate_probabilities[metric]
                simulated_counts[metric] += int(flags[metric])
        for metric in SHAPE_METRICS:
            bootstrap_differences[metric].append(
                simulated_counts[metric] - replicate_expected_counts[metric]
            )

    sample_count = len(materialized)
    raw_p_values: dict[str, float] = {}
    null_intervals: dict[str, list[float | None]] = {}
    for metric in SHAPE_METRICS:
        observed_count = int(observed_counts[metric])
        residual_count = observed_count - float(expected_counts[metric])
        null_values = bootstrap_differences[metric]
        raw_p_values[metric] = (
            1.0 + sum(abs(value) >= abs(residual_count) for value in null_values)
        ) / (len(null_values) + 1.0)
        null_intervals[metric] = [_quantile(null_values, 0.025), _quantile(null_values, 0.975)]
    adjusted_p_values = _holm_bonferroni(raw_p_values)

    metrics: dict[str, dict[str, Any]] = {}
    for metric in SHAPE_METRICS:
        observed_count = int(observed_counts[metric])
        conditioned_expected_count = float(expected_counts[metric])
        residual_count = observed_count - conditioned_expected_count
        null_ci = null_intervals[metric]
        raw_p_value = raw_p_values[metric]
        adjusted_p_value = adjusted_p_values[metric]
        metrics[metric] = {
            "observed_count": observed_count,
            "observed_rate": observed_count / sample_count,
            "conditioned_expected_count": conditioned_expected_count,
            "conditioned_expected_rate": conditioned_expected_count / sample_count,
            "residual_count_observed_minus_conditioned_expected": residual_count,
            "residual_rate_observed_minus_conditioned_expected": residual_count / sample_count,
            # These aliases keep the metric shape easy to consume while the
            # conditioned names make the nuisance adjustment explicit.
            "expected_count": conditioned_expected_count,
            "expected_rate": conditioned_expected_count / sample_count,
            "residual_count_observed_minus_expected": residual_count,
            "residual_rate_observed_minus_expected": residual_count / sample_count,
            "parametric_bootstrap_null_ci_95_count": null_ci,
            "parametric_bootstrap_null_ci_95_rate": [
                value / sample_count if value is not None else None for value in null_ci
            ],
            "raw_p_value": raw_p_value,
            "adjusted_p_value": adjusted_p_value,
            "holm_bonferroni_adjusted_p_value": adjusted_p_value,
            "two_sided_p_value": raw_p_value,
        }
    return {
        "diagnostic": "MEAN_CONDITIONED_SHAPE",
        "sample_count": sample_count,
        "seed": seed,
        "replicates": replicates,
        "distribution": "independent_poisson_conditioned_lambda_home_lambda_away_rho_0",
        "conditioning": "postmatch_diagnostic_nuisance_adjustment_only_not_written_to_predictions",
        "scale_home": scale_home,
        "scale_away": scale_away,
        "original_lambda_home_sum": original_home_sum,
        "original_lambda_away_sum": original_away_sum,
        "conditioned_lambda_home_mean": sum(pair[0] for pair in conditioned_pairs) / sample_count,
        "conditioned_lambda_away_mean": sum(pair[1] for pair in conditioned_pairs) / sample_count,
        "multiple_testing": {
            "method": "Holm-Bonferroni",
            "family_wise_alpha": 0.05,
            "metric_count": len(SHAPE_METRICS),
        },
        "metrics": metrics,
    }


# Explicit alias for callers that describe the same output as an audit rather
# than a bootstrap implementation.
run_mean_conditioned_shape_audit = run_mean_conditioned_shape_bootstrap


def _intensity_point(rows: list[Mapping[str, Any]]) -> dict[str, float]:
    sample_count = len(rows)
    if not sample_count:
        return {}
    predicted_home = sum(float(row["lambda_home"]) for row in rows) / sample_count
    predicted_away = sum(float(row["lambda_away"]) for row in rows) / sample_count
    predicted_total = sum(float(row["lambda_total"]) for row in rows) / sample_count
    actual_home = sum(int(row["actual_home"]) for row in rows) / sample_count
    actual_away = sum(int(row["actual_away"]) for row in rows) / sample_count
    actual_total = sum(int(row["actual_total"]) for row in rows) / sample_count
    return {
        "mean_predicted_home_goals": predicted_home,
        "mean_actual_home_goals": actual_home,
        "lambda_home_bias_predicted_minus_actual": predicted_home - actual_home,
        "mean_predicted_away_goals": predicted_away,
        "mean_actual_away_goals": actual_away,
        "lambda_away_bias_predicted_minus_actual": predicted_away - actual_away,
        "mean_predicted_total_goals": predicted_total,
        "mean_actual_total_goals": actual_total,
        "lambda_total_mean_bias_predicted_minus_actual": predicted_total - actual_total,
        "lambda_total_mae": sum(abs(float(row["lambda_total"]) - int(row["actual_total"])) for row in rows)
        / sample_count,
    }


def _bootstrap_mean_ci(
    rows: list[Mapping[str, Any]],
    statistic: Callable[[Mapping[str, Any]], float],
    *,
    seed: int,
    replicates: int,
) -> list[float | None]:
    if not rows:
        return [None, None]
    rng = random.Random(seed)
    values: list[float] = []
    count = len(rows)
    for _ in range(replicates):
        values.append(sum(statistic(rows[rng.randrange(count)]) for _ in range(count)) / count)
    return [_quantile(values, 0.025), _quantile(values, 0.975)]


def run_intensity_bootstrap(
    rows: list[Mapping[str, Any]],
    *,
    seed: int,
    replicates: int,
) -> dict[str, Any]:
    point = _intensity_point(rows)
    if not point:
        return {"sample_count": 0, "seed": seed, "replicates": replicates, "metrics": {}}

    statistics: dict[str, Callable[[Mapping[str, Any]], float]] = {
        "mean_predicted_home_goals": lambda row: float(row["lambda_home"]),
        "mean_actual_home_goals": lambda row: float(row["actual_home"]),
        "lambda_home_bias_predicted_minus_actual": lambda row: float(row["lambda_home"]) - int(row["actual_home"]),
        "mean_predicted_away_goals": lambda row: float(row["lambda_away"]),
        "mean_actual_away_goals": lambda row: float(row["actual_away"]),
        "lambda_away_bias_predicted_minus_actual": lambda row: float(row["lambda_away"]) - int(row["actual_away"]),
        "mean_predicted_total_goals": lambda row: float(row["lambda_total"]),
        "mean_actual_total_goals": lambda row: float(row["actual_total"]),
        "lambda_total_mean_bias_predicted_minus_actual": lambda row: float(row["lambda_total"])
        - int(row["actual_total"]),
        "lambda_total_mae": lambda row: abs(float(row["lambda_total"]) - int(row["actual_total"])),
    }
    metrics = {
        name: {"value": point[name], "nonparametric_bootstrap_ci_95": _bootstrap_mean_ci(rows, fn, seed=_stable_seed(seed, name), replicates=replicates)}
        for name, fn in statistics.items()
    }
    return {
        "sample_count": len(rows),
        "seed": seed,
        "replicates": replicates,
        "bias_convention": "predicted_minus_actual",
        "metrics": metrics,
    }


def _run_lambda_total_bins(rows: list[Mapping[str, Any]], *, seed: int, replicates: int) -> list[dict[str, Any]]:
    buckets: list[dict[str, Any]] = []
    for label, lower, upper, upper_inclusive in LAMBDA_TOTAL_BINS:
        if upper_inclusive:
            subset = [row for row in rows if lower <= float(row["lambda_total"])]
        else:
            subset = [row for row in rows if lower <= float(row["lambda_total"]) < upper]
        if subset:
            expected_mean = sum(float(row["lambda_total"]) for row in subset) / len(subset)
            observed_mean = sum(int(row["actual_total"]) for row in subset) / len(subset)
            observed_minus_expected = observed_mean - expected_mean
            ci = _bootstrap_mean_ci(
                subset,
                lambda row: int(row["actual_total"]) - float(row["lambda_total"]),
                seed=_stable_seed(seed, label),
                replicates=replicates,
            )
        else:
            expected_mean = observed_mean = observed_minus_expected = None
            ci = [None, None]
        buckets.append(
            {
                "bin": label,
                "sample_count": len(subset),
                "sample_status": "SUFFICIENT" if len(subset) >= MIN_UNIVERSE_SAMPLE else "INSUFFICIENT_SAMPLE",
                "expected_lambda_total_mean": expected_mean,
                "observed_total_goals_mean": observed_mean,
                "observed_minus_expected_mean": observed_minus_expected,
                "observed_minus_expected_nonparametric_bootstrap_ci_95": ci,
            }
        )
    return buckets


def run_intensity_analysis(
    rows: list[Mapping[str, Any]],
    *,
    seed: int,
    replicates: int,
) -> dict[str, Any]:
    intensity = run_intensity_bootstrap(rows, seed=_stable_seed(seed, "intensity"), replicates=replicates)
    intensity["lambda_total_bins"] = _run_lambda_total_bins(
        rows,
        seed=_stable_seed(seed, "lambda_total_bins"),
        replicates=replicates,
    )
    return intensity


def run_pairwise_total_bias_bootstrap(
    rows_a: Iterable[Mapping[str, Any]],
    rows_b: Iterable[Mapping[str, Any]],
    *,
    universe_a: str,
    universe_b: str,
    seed: int,
    replicates: int,
) -> dict[str, Any]:
    """Bootstrap the difference in total intensity bias for two universes."""

    if replicates < 1:
        raise ValueError("bootstrap replicates must be positive")
    materialized_a = list(rows_a)
    materialized_b = list(rows_b)
    if not materialized_a or not materialized_b:
        return {
            "universe_a": universe_a,
            "universe_b": universe_b,
            "sample_count_a": len(materialized_a),
            "sample_count_b": len(materialized_b),
            "seed": seed,
            "replicates": replicates,
            "point_estimate": None,
            "point_estimate_bias_a_minus_bias_b": None,
            "bootstrap_ci_95": [None, None],
            "bootstrap_ci_95_bias_difference": [None, None],
            "ci_excludes_zero": False,
        }

    def total_bias(row: Mapping[str, Any]) -> float:
        lambda_total = row.get("lambda_total")
        if lambda_total is None:
            lambda_total = float(row["lambda_home"]) + float(row["lambda_away"])
        actual_total = row.get("actual_total")
        if actual_total is None:
            actual_total = int(row["actual_home"]) + int(row["actual_away"])
        return float(lambda_total) - int(actual_total)

    bias_values_a = [total_bias(row) for row in materialized_a]
    bias_values_b = [total_bias(row) for row in materialized_b]
    point_estimate = sum(bias_values_a) / len(bias_values_a) - sum(bias_values_b) / len(bias_values_b)
    rng = random.Random(seed)
    bootstrap_differences: list[float] = []
    for _ in range(replicates):
        bootstrap_a = sum(bias_values_a[rng.randrange(len(bias_values_a))] for _ in bias_values_a) / len(bias_values_a)
        bootstrap_b = sum(bias_values_b[rng.randrange(len(bias_values_b))] for _ in bias_values_b) / len(bias_values_b)
        bootstrap_differences.append(bootstrap_a - bootstrap_b)
    interval = [_quantile(bootstrap_differences, 0.025), _quantile(bootstrap_differences, 0.975)]
    return {
        "universe_a": universe_a,
        "universe_b": universe_b,
        "sample_count_a": len(materialized_a),
        "sample_count_b": len(materialized_b),
        "seed": seed,
        "replicates": replicates,
        "method": "independent_nonparametric_bootstrap_of_total_bias_difference",
        "bias_convention": "predicted_minus_actual",
        "point_estimate": point_estimate,
        "point_estimate_bias_a_minus_bias_b": point_estimate,
        "bootstrap_ci_95": interval,
        "bootstrap_ci_95_bias_difference": interval,
        "ci_excludes_zero": _ci_excludes_zero(interval),
    }


def _scope_payload(
    name: str,
    rows: list[Mapping[str, Any]],
    *,
    seed: int,
    replicates: int,
) -> dict[str, Any]:
    sample_count = len(rows)
    payload: dict[str, Any] = {
        "scope": name,
        "sample_count": sample_count,
        "sample_status": "SUFFICIENT" if sample_count >= MIN_UNIVERSE_SAMPLE else "INSUFFICIENT_SAMPLE",
        "strong_conclusion_allowed": sample_count >= MIN_UNIVERSE_SAMPLE,
        "bootstrap_seed": seed,
        "bootstrap_replicates": replicates,
        "intensity": run_intensity_analysis(rows, seed=_stable_seed(seed, f"{name}:intensity"), replicates=replicates)
        if rows
        else None,
        "raw_shape_diagnostic": run_parametric_shape_bootstrap(
            rows,
            seed=_stable_seed(seed, f"{name}:raw_shape_diagnostic"),
            replicates=replicates,
        )
        if rows
        else None,
        "mean_conditioned_shape": run_mean_conditioned_shape_bootstrap(
            rows,
            seed=_stable_seed(seed, f"{name}:mean_conditioned_shape"),
            replicates=replicates,
        )
        if rows
        else None,
    }
    return payload


def _metric_value(scope: Mapping[str, Any], metric: str) -> float | None:
    intensity = scope.get("intensity") or {}
    entry = (intensity.get("metrics") or {}).get(metric) or {}
    value = entry.get("value")
    return float(value) if value is not None else None


def _metric_ci(scope: Mapping[str, Any], metric: str) -> list[float | None]:
    intensity = scope.get("intensity") or {}
    entry = (intensity.get("metrics") or {}).get(metric) or {}
    return list(entry.get("nonparametric_bootstrap_ci_95") or [None, None])


def _ci_excludes_zero(interval: list[float | None]) -> bool:
    return len(interval) == 2 and interval[0] is not None and interval[1] is not None and (interval[0] > 0 or interval[1] < 0)


def _shape_p_value(
    scope: Mapping[str, Any],
    metric: str,
    *,
    diagnostic: str,
    value_key: str,
) -> float | None:
    shape = scope.get(diagnostic) or {}
    entry = (shape.get("metrics") or {}).get(metric) or {}
    value = entry.get(value_key)
    return float(value) if value is not None else None


def _classification(
    global_scope: Mapping[str, Any],
    universe_scopes: Mapping[str, Mapping[str, Any]],
    coverage: list[Mapping[str, Any]],
    universe_rows: Mapping[str, list[Mapping[str, Any]]] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    global_count = int(global_scope.get("sample_count") or 0)
    total_bias_ci = _metric_ci(global_scope, "lambda_total_mean_bias_predicted_minus_actual")
    home_bias_ci = _metric_ci(global_scope, "lambda_home_bias_predicted_minus_actual")
    away_bias_ci = _metric_ci(global_scope, "lambda_away_bias_predicted_minus_actual")
    intensity_supported = global_count >= MIN_UNIVERSE_SAMPLE and (
        _ci_excludes_zero(total_bias_ci) or _ci_excludes_zero(home_bias_ci) or _ci_excludes_zero(away_bias_ci)
    )
    intensity_status = "SUPPORTED" if intensity_supported else "NOT_ESTABLISHED" if global_count < MIN_UNIVERSE_SAMPLE else "NOT_SUPPORTED"

    mean_conditioned_shape = global_scope.get("mean_conditioned_shape") or {}
    conditioned_signals = [
        metric
        for metric in SHAPE_METRICS
        if (
            _shape_p_value(
                global_scope,
                metric,
                diagnostic="mean_conditioned_shape",
                value_key="adjusted_p_value",
            )
            is not None
            and _shape_p_value(
                global_scope,
                metric,
                diagnostic="mean_conditioned_shape",
                value_key="adjusted_p_value",
            )
            <= 0.05
        )
    ]
    raw_tail_signals = [
        metric
        for metric in TAIL_SHAPE_METRICS
        if (
            _shape_p_value(
                global_scope,
                metric,
                diagnostic="raw_shape_diagnostic",
                value_key="raw_p_value",
            )
            is not None
            and _shape_p_value(
                global_scope,
                metric,
                diagnostic="raw_shape_diagnostic",
                value_key="raw_p_value",
            )
            <= 0.05
        )
    ]
    conditioned_tail_signals = [metric for metric in conditioned_signals if metric in TAIL_SHAPE_METRICS]
    tail_error_explained_by_mean_bias = bool(raw_tail_signals) and not conditioned_tail_signals
    if global_count < MIN_UNIVERSE_SAMPLE:
        shape_status = "NOT_ESTABLISHED"
    elif not mean_conditioned_shape.get("metrics"):
        shape_status = "NOT_ESTABLISHED"
    elif conditioned_signals:
        shape_status = "SUPPORTED"
    else:
        shape_status = "NOT_SUPPORTED"

    sufficient_universes = [
        row["universe"]
        for row in coverage
        if int(row.get("verified_n") or 0) >= MIN_UNIVERSE_SAMPLE and row["universe"] in universe_scopes
    ]
    total_directions = {
        universe: _metric_value(universe_scopes[universe], "lambda_total_mean_bias_predicted_minus_actual")
        for universe in sufficient_universes
    }
    component_directions: dict[str, dict[str, float | None]] = {}
    component_reversals: dict[str, bool] = {}
    bias_evidence_by_universe: dict[str, dict[str, Any]] = {}
    for metric in (
        "lambda_total_mean_bias_predicted_minus_actual",
        "lambda_home_bias_predicted_minus_actual",
        "lambda_away_bias_predicted_minus_actual",
    ):
        values = {universe: _metric_value(universe_scopes[universe], metric) for universe in sufficient_universes}
        component_directions[metric] = values
        signs = {1 if value > 0 else -1 if value < 0 else 0 for value in values.values() if value is not None}
        component_reversals[metric] = len(signs - {0}) > 1
    for universe in sufficient_universes:
        bias_evidence_by_universe[universe] = {
            metric: {
                "value": _metric_value(universe_scopes[universe], metric),
                "bootstrap_ci_95": _metric_ci(universe_scopes[universe], metric),
            }
            for metric in (
                "lambda_home_bias_predicted_minus_actual",
                "lambda_away_bias_predicted_minus_actual",
                "lambda_total_mean_bias_predicted_minus_actual",
            )
        }

    shape_reversals: dict[str, bool] = {}
    for metric in CORE_SHAPE_METRICS:
        values = {
            universe: float(
                (
                    (universe_scopes[universe].get("mean_conditioned_shape") or {}).get("metrics") or {}
                ).get(metric, {}).get(
                    "residual_rate_observed_minus_conditioned_expected", 0.0
                )
            )
            for universe in sufficient_universes
        }
        signs = {1 if value > 0 else -1 if value < 0 else 0 for value in values.values()}
        shape_reversals[metric] = len(signs - {0}) > 1

    pairwise_total_bias_differences: list[dict[str, Any]] = []
    if universe_rows is not None:
        pairwise_seed = int(global_scope.get("bootstrap_seed") or BOOTSTRAP_SEED)
        pairwise_replicates = int(global_scope.get("bootstrap_replicates") or DEFAULT_BOOTSTRAP_REPLICATES)
        for universe_a, universe_b in combinations(sufficient_universes, 2):
            pairwise_total_bias_differences.append(
                run_pairwise_total_bias_bootstrap(
                    universe_rows.get(universe_a, []),
                    universe_rows.get(universe_b, []),
                    universe_a=universe_a,
                    universe_b=universe_b,
                    seed=_stable_seed(pairwise_seed, f"{universe_a}:{universe_b}:total_bias"),
                    replicates=pairwise_replicates,
                )
            )
    material_heterogeneity_pairs = [
        pair for pair in pairwise_total_bias_differences if pair.get("ci_excludes_zero") is True
    ]
    if len(sufficient_universes) < 2:
        heterogeneity_status = "NOT_ESTABLISHED"
    elif not pairwise_total_bias_differences:
        heterogeneity_status = "NOT_ESTABLISHED"
    elif material_heterogeneity_pairs:
        heterogeneity_status = "SUPPORTED"
    else:
        heterogeneity_status = "NOT_SUPPORTED"

    global_total_direction = _metric_value(global_scope, "lambda_total_mean_bias_predicted_minus_actual")
    global_total_sign = 1 if (global_total_direction or 0) > 0 else -1 if (global_total_direction or 0) < 0 else 0
    global_total_cancellation = any(
        value is not None and global_total_sign and (1 if value > 0 else -1 if value < 0 else 0) != global_total_sign
        for value in total_directions.values()
    )
    classifications = {
        "MEAN_INTENSITY": {
            "status": intensity_status,
            "evidence": {
                "global_lambda_total_bias_ci_95": total_bias_ci,
                "global_lambda_home_bias_ci_95": home_bias_ci,
                "global_lambda_away_bias_ci_95": away_bias_ci,
            },
            "reason": (
                "Global predicted intensity is below actual scoring, with the total bias CI excluding zero."
                if intensity_status == "SUPPORTED"
                else "The global intensity interval does not establish a systematic mean bias."
            ),
        },
        "DISTRIBUTION_SHAPE": {
            "status": shape_status,
            "evidence": {
                "mean_conditioned_shape_signals_adjusted_p_le_0_05": conditioned_signals,
                "mean_conditioned_tail_signals_adjusted_p_le_0_05": conditioned_tail_signals,
                "raw_shape_tail_signals_p_le_0_05": raw_tail_signals,
                "tail_error_explained_by_mean_bias": tail_error_explained_by_mean_bias,
                "mean_conditioned_shape_metrics": list(SHAPE_METRICS),
                "multiple_testing": (mean_conditioned_shape.get("multiple_testing") or {}),
            },
            "reason": (
                "At least one mean-conditioned shape metric remains significant after Holm-Bonferroni correction."
                if conditioned_signals
                else "Mean-conditioned diagnostics do not provide independent shape evidence after Holm-Bonferroni correction; raw tail residuals are not used for this decision."
            ),
        },
        "COMPETITION_UNIVERSE_HETEROGENEITY": {
            "status": heterogeneity_status,
            "evidence": {
                "sufficient_universes": sufficient_universes,
                "lambda_bias_by_universe": component_directions,
                "lambda_bias_evidence_by_universe": bias_evidence_by_universe,
                "pairwise_total_bias_differences": pairwise_total_bias_differences,
                "material_pairwise_total_bias_differences": material_heterogeneity_pairs,
                "component_direction_reversals": component_reversals,
                "core_shape_direction_reversals": shape_reversals,
                "global_total_bias_cancellation_detected": global_total_cancellation,
            },
            "reason": (
                "A predefined sufficient-universe pair has a total-bias difference bootstrap CI excluding zero."
                if heterogeneity_status == "SUPPORTED"
                else "At least two predefined sufficient universes were compared and no total-bias difference bootstrap CI excludes zero."
                if heterogeneity_status == "NOT_SUPPORTED"
                else "Fewer than two predefined sufficient universes or pairwise total-bias evidence is available."
            ),
        },
    }
    if heterogeneity_status == "SUPPORTED":
        primary = "COMPETITION_UNIVERSE_HETEROGENEITY"
    elif intensity_status == "SUPPORTED" and shape_status == "SUPPORTED":
        primary = "MIXED"
    elif intensity_status == "SUPPORTED":
        primary = "MEAN_INTENSITY"
    elif shape_status == "SUPPORTED":
        primary = "DISTRIBUTION_SHAPE"
    else:
        primary = "NOT_ESTABLISHED"
    return classifications, {
        "status": heterogeneity_status,
        "sufficient_universes": sufficient_universes,
        "total_intensity_bias_by_universe": total_directions,
        "lambda_bias_evidence_by_universe": bias_evidence_by_universe,
        "pairwise_total_bias_differences": pairwise_total_bias_differences,
        "material_pairwise_total_bias_differences": material_heterogeneity_pairs,
        "component_direction_reversals": component_reversals,
        "core_shape_direction_reversals": shape_reversals,
        "global_total_bias_cancellation_detected": global_total_cancellation,
        "primary_defect": primary,
    }


def _coverage(selected_rows: list[Mapping[str, Any]], verified_rows: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    selected_by_universe: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    verified_by_universe: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in selected_rows:
        selected_by_universe[str(row["universe"])].append(row)
    for row in verified_rows:
        verified_by_universe[str(row["universe"])].append(row)
    rows = []
    for universe in UNIVERSES:
        selected = selected_by_universe.get(universe, [])
        verified = verified_by_universe.get(universe, [])
        raw_competitions = {
            value
            for row in selected
            for value in ([row.get("competition")] if row.get("competition") else row.get("competition_candidates") or [])
            if _text(value)
        }
        examples = sorted(
            {_text(value) for value in raw_competitions}
        )[:5]
        rows.append(
            {
                "universe": universe,
                "pinned_n": len(selected),
                "verified_n": len(verified),
                "sample_status": "SUFFICIENT" if len(verified) >= MIN_UNIVERSE_SAMPLE else "INSUFFICIENT_SAMPLE",
                "competition_examples": examples,
                "raw_competition_count": len(raw_competitions),
            }
        )
    return rows


def build_summary(
    cohort: Mapping[str, Any],
    *,
    seed: int = BOOTSTRAP_SEED,
    replicates: int = DEFAULT_BOOTSTRAP_REPLICATES,
) -> dict[str, Any]:
    selected_rows = list(cohort["selected_rows"])
    verified_rows = list(cohort["verified_rows"])
    coverage = _coverage(selected_rows, verified_rows)
    global_scope = _scope_payload("GLOBAL", verified_rows, seed=seed, replicates=replicates)
    universe_scope_payloads = {
        universe: _scope_payload(
            universe,
            [row for row in verified_rows if row["universe"] == universe],
            seed=seed,
            replicates=replicates,
        )
        for universe in UNIVERSES
    }
    universe_rows = {
        universe: [row for row in verified_rows if row["universe"] == universe]
        for universe in UNIVERSES
    }
    classifications, heterogeneity = _classification(
        global_scope,
        universe_scope_payloads,
        coverage,
        universe_rows,
    )
    manifest = cohort["manifest"]
    audit = cohort["audit"]
    national_team_verified_n = sum(1 for row in verified_rows if row["universe"] == "NATIONAL_TEAM")
    if national_team_verified_n == 0:
        national_team_applicability = "NOT_ESTABLISHED"
    elif national_team_verified_n < MIN_UNIVERSE_SAMPLE:
        national_team_applicability = "INSUFFICIENT_SAMPLE"
    else:
        national_team_applicability = "ESTABLISHED"
    raw_shape_summary = {
        "global": global_scope["raw_shape_diagnostic"],
        "by_universe": {
            universe: payload["raw_shape_diagnostic"] for universe, payload in universe_scope_payloads.items()
        },
    }
    mean_conditioned_shape_summary = {
        "global": global_scope["mean_conditioned_shape"],
        "by_universe": {
            universe: payload["mean_conditioned_shape"]
            for universe, payload in universe_scope_payloads.items()
        },
    }
    return {
        "schema_version": "exact_score_error_decomposition_audit.v2",
        "milestone": MILESTONE,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": {
            "manifest": cohort["manifest_path"],
            "audit": cohort["audit_path"],
            "champion_model_family": CHAMPION_MODEL_FAMILY,
            "champion_model_role": "champion",
            "rho_required": 0.0,
            "competition_metadata": "data/base_prediction_jobs/*.json: league or competition field",
            "result_metadata": "data/postmatch_automation/results/{match_key}.json",
            "audit_generated_at": audit.get("generated_at"),
            "accepted_production_run": manifest.get("accepted_production_run"),
            "accepted_writeback_commit": manifest.get("accepted_writeback_commit"),
        },
        "snapshot_integrity": cohort["snapshot_integrity"],
        "cohort": {
            "pinned_n": len(selected_rows),
            "verified_n": len(verified_rows),
            "unique_match_observation_n": len({row["match_id"] for row in verified_rows}),
            "selection_rule": "one pinned Champion frozen prediction per unique match; verified IDs from pred_trust_2 manifest",
            "result_scope": "regulation_90m_plus_stoppage",
            "prematch_prediction_fields_used": ["lambda_home", "lambda_away", "rho"],
            "postmatch_fields_used": ["result_90m", "home_score", "away_score"],
        },
        "bootstrap": {
            "seed": seed,
            "replicates": replicates,
            "intensity_method": "paired nonparametric bootstrap over unique matches",
            "raw_shape_method": "parametric independent-Poisson bootstrap with each original frozen lambda pair",
            "mean_conditioned_shape_method": "conditioned independent-Poisson bootstrap; each replicate re-estimates home/away scales against original frozen lambdas",
            "shape_multiple_testing": "Holm-Bonferroni over 11 mean-conditioned metrics; family-wise alpha 0.05",
            "universe_heterogeneity_method": "independent nonparametric bootstrap of predefined sufficient-universe total-bias differences",
        },
        "competition_universe_coverage": coverage,
        "NATIONAL_TEAM_APPLICABILITY": national_team_applicability,
        "mean_intensity": {
            "global": global_scope["intensity"],
            "by_universe": {universe: payload["intensity"] for universe, payload in universe_scope_payloads.items()},
        },
        "distribution_shape": {
            "raw_shape_diagnostic": raw_shape_summary,
            "mean_conditioned_shape": mean_conditioned_shape_summary,
            "mean_conditioned": mean_conditioned_shape_summary,
        },
        "universe_heterogeneity": heterogeneity,
        "defect_classification": classifications,
        "primary_defect": heterogeneity["primary_defect"],
        "stop_invariants": {
            "production_changed": False,
            "champion_changed": False,
            "challenger_c_changed": False,
            "model_parameters_searched": False,
            "provider_added": False,
            "frozen_history_rewritten": False,
            "result_used_only_for_postmatch_evaluation": True,
        },
    }


def _fmt_number(value: Any, digits: int = 3) -> str:
    if value is None:
        return "—"
    if isinstance(value, bool):
        return str(value)
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return str(value)


def _fmt_ci(interval: Any, digits: int = 3) -> str:
    if not interval or len(interval) != 2 or interval[0] is None or interval[1] is None:
        return "—"
    return f"[{_fmt_number(interval[0], digits)}, {_fmt_number(interval[1], digits)}]"


def _intensity_table(scope: Mapping[str, Any]) -> list[str]:
    metrics = scope.get("metrics") or {}
    selected = (
        "mean_predicted_home_goals",
        "mean_actual_home_goals",
        "lambda_home_bias_predicted_minus_actual",
        "mean_predicted_away_goals",
        "mean_actual_away_goals",
        "lambda_away_bias_predicted_minus_actual",
        "mean_predicted_total_goals",
        "mean_actual_total_goals",
        "lambda_total_mean_bias_predicted_minus_actual",
        "lambda_total_mae",
    )
    lines = ["| metric | value | 95% bootstrap CI |", "|---|---:|---:|"]
    for metric in selected:
        entry = metrics.get(metric) or {}
        lines.append(
            f"| `{metric}` | {_fmt_number(entry.get('value'))} | {_fmt_ci(entry.get('nonparametric_bootstrap_ci_95'))} |"
        )
    return lines


def _shape_table(scope: Mapping[str, Any], *, conditioned: bool) -> list[str]:
    metrics = scope.get("metrics") or {}
    if conditioned:
        lines = [
            "| metric | observed | conditioned expected | observed - conditioned expected | observed rate | conditioned expected rate | raw p-value | adjusted p-value |",
            "|---|---:|---:|---:|---:|---:|---:|---:|",
        ]
    else:
        lines = [
            "| metric | observed | expected | observed - expected | observed rate | expected rate | raw p-value |",
            "|---|---:|---:|---:|---:|---:|---:|",
        ]
    for metric in SHAPE_METRICS:
        entry = metrics.get(metric) or {}
        if conditioned:
            lines.append(
                "| `{metric}` | {observed} | {expected} | {residual} | {observed_rate} | {expected_rate} | {raw_p_value} | {adjusted_p_value} |".format(
                    metric=metric,
                    observed=_fmt_number(entry.get("observed_count")),
                    expected=_fmt_number(entry.get("conditioned_expected_count")),
                    residual=_fmt_number(entry.get("residual_count_observed_minus_conditioned_expected")),
                    observed_rate=_fmt_number(entry.get("observed_rate"), 4),
                    expected_rate=_fmt_number(entry.get("conditioned_expected_rate"), 4),
                    raw_p_value=_fmt_number(entry.get("raw_p_value"), 4),
                    adjusted_p_value=_fmt_number(entry.get("adjusted_p_value"), 4),
                )
            )
        else:
            lines.append(
                "| `{metric}` | {observed} | {expected} | {residual} | {observed_rate} | {expected_rate} | {raw_p_value} |".format(
                    metric=metric,
                    observed=_fmt_number(entry.get("observed_count")),
                    expected=_fmt_number(entry.get("expected_count")),
                    residual=_fmt_number(entry.get("residual_count_observed_minus_expected")),
                    observed_rate=_fmt_number(entry.get("observed_rate"), 4),
                    expected_rate=_fmt_number(entry.get("expected_rate"), 4),
                    raw_p_value=_fmt_number(entry.get("raw_p_value", entry.get("two_sided_p_value")), 4),
                )
            )
    return lines



def build_report(summary: Mapping[str, Any]) -> str:
    coverage = summary["competition_universe_coverage"]
    mean_intensity = summary["mean_intensity"]
    distribution_shape = summary["distribution_shape"]
    classifications = summary["defect_classification"]
    raw_shape = distribution_shape["raw_shape_diagnostic"]
    mean_conditioned_shape = distribution_shape["mean_conditioned_shape"]
    global_sample_status = (
        "SUFFICIENT"
        if summary["cohort"]["verified_n"] >= MIN_UNIVERSE_SAMPLE
        else "INSUFFICIENT_SAMPLE"
    )
    national_team_applicability = summary.get("NATIONAL_TEAM_APPLICABILITY", "NOT_ESTABLISHED")
    lines = [
        f"# {summary['milestone']}",
        "",
        "## Scope and guardrails",
        "",
        f"- Champion: `{summary['source']['champion_model_family']}`; `rho=0`.",
        f"- Cohort: pinned `{summary['cohort']['pinned_n']}`; verified `{summary['cohort']['verified_n']}`; unique-match observations `{summary['cohort']['unique_match_observation_n']}`.",
        f"- Results: `{summary['cohort']['result_scope']}` only; frozen prematch lambdas are never rebuilt from results.",
        f"- Bootstrap: seed `{summary['bootstrap']['seed']}`, replicates `{summary['bootstrap']['replicates']}`.",
        f"- `NATIONAL_TEAM_APPLICABILITY={national_team_applicability}`.",
        "- Snapshot integrity uses canonical JSON semantic SHA256 for the snapshot input, pinned prediction record, and embedded input snapshot; snapshot ID and source cutoff are cross-checked.",
        f"- Raw snapshot-file SHA256 is legacy/non-portable evidence only: `{summary['snapshot_integrity']['raw_file_sha256']['matched_n']}` matched, `{summary['snapshot_integrity']['raw_file_sha256']['mismatched_n']}` mismatched, `{summary['snapshot_integrity']['raw_file_sha256']['missing_manifest_hash_n']}` missing; mismatch is not a fail condition.",
        "- Sign convention for intensity bias: predicted minus actual; negative means underprediction.",
        "",
        "## Competition universe coverage",
        "",
        "| universe | pinned n | verified n | status | competition examples |",
        "|---|---:|---:|---|---|",
    ]
    for row in coverage:
        examples = ", ".join(row["competition_examples"]) or "-"
        lines.append(
            f"| `{row['universe']}` | {row['pinned_n']} | {row['verified_n']} | `{row['sample_status']}` | {examples} |"
        )

    def add_intensity_scope(title: str, scope: Mapping[str, Any]) -> None:
        lines.extend(["", f"### {title} (n={scope.get('sample_count', 0)}; {scope.get('sample_status')})", ""])
        if not scope.get("intensity"):
            lines.append("No observations.")
            return
        lines.extend(_intensity_table(scope["intensity"]))
        lines.extend(
            [
                "",
                "lambda_total bins:",
                "",
                "| bin | n | status | expected lambda_total | observed total | observed - expected | 95% CI |",
                "|---|---:|---|---:|---:|---:|---:|",
            ]
        )
        for bucket in scope["intensity"].get("lambda_total_bins") or []:
            lines.append(
                f"| `{bucket['bin']}` | {bucket['sample_count']} | `{bucket['sample_status']}` | {_fmt_number(bucket.get('expected_lambda_total_mean'))} | {_fmt_number(bucket.get('observed_total_goals_mean'))} | {_fmt_number(bucket.get('observed_minus_expected_mean'))} | {_fmt_ci(bucket.get('observed_minus_expected_nonparametric_bootstrap_ci_95'))} |"
            )

    lines.extend(["", "## MEAN_INTENSITY", ""])
    add_intensity_scope(
        "GLOBAL",
        {
            "sample_count": summary["cohort"]["verified_n"],
            "sample_status": global_sample_status,
            "intensity": mean_intensity["global"],
        },
    )
    for row in coverage:
        universe = row["universe"]
        if row["verified_n"]:
            add_intensity_scope(
                universe,
                {
                    "sample_count": row["verified_n"],
                    "sample_status": row["sample_status"],
                    "intensity": mean_intensity["by_universe"].get(universe),
                },
            )

    def add_shape_scope(title: str, shape: Mapping[str, Any] | None, *, conditioned: bool, sample_count: int, sample_status: str) -> None:
        lines.extend(["", f"### {title} (n={sample_count}; {sample_status})", ""])
        if not shape:
            lines.append("No observations.")
            return
        if conditioned:
            lines.extend(
                [
                    f"- `scale_home={_fmt_number(shape.get('scale_home'))}`; `scale_away={_fmt_number(shape.get('scale_away'))}`.",
                    "- Scales are postmatch diagnostic nuisance adjustments only; they are not written to predictions, serving, or production data.",
                ]
            )
        lines.extend(_shape_table(shape, conditioned=conditioned))
        if conditioned:
            lines.extend(
                [
                    "",
                    "`raw p-value` is the deterministic two-sided parametric-bootstrap probability; `adjusted p-value` is Holm-Bonferroni over all 11 mean-conditioned metrics with family-wise alpha 0.05.",
                ]
            )
        else:
            lines.extend(
                [
                    "",
                    "The raw p-value is the deterministic two-sided parametric-bootstrap probability for the observed-minus-expected count.",
                ]
            )

    lines.extend(
        [
            "",
            "## RAW_SHAPE_DIAGNOSTIC",
            "",
            "Raw frozen-lambda residuals are descriptive and do not determine `DISTRIBUTION_SHAPE`.",
        ]
    )
    add_shape_scope(
        "GLOBAL",
        raw_shape["global"],
        conditioned=False,
        sample_count=summary["cohort"]["verified_n"],
        sample_status=global_sample_status,
    )
    for row in coverage:
        if row["verified_n"]:
            add_shape_scope(
                row["universe"],
                raw_shape["by_universe"].get(row["universe"]),
                conditioned=False,
                sample_count=row["verified_n"],
                sample_status=row["sample_status"],
            )

    lines.extend(
        [
            "",
            "## MEAN_CONDITIONED_SHAPE",
            "",
            "The observed home/away scales remove the established mean/intensity bias for this diagnostic only. Each bootstrap replicate simulates under the conditioned null, re-estimates both scales against the original frozen lambdas, and recomputes its own conditioned expectations.",
        ]
    )
    add_shape_scope(
        "GLOBAL",
        mean_conditioned_shape["global"],
        conditioned=True,
        sample_count=summary["cohort"]["verified_n"],
        sample_status=global_sample_status,
    )
    for row in coverage:
        if row["verified_n"]:
            add_shape_scope(
                row["universe"],
                mean_conditioned_shape["by_universe"].get(row["universe"]),
                conditioned=True,
                sample_count=row["verified_n"],
                sample_status=row["sample_status"],
            )

    heterogeneity = summary["universe_heterogeneity"]
    coverage_by_universe = {row["universe"]: row for row in coverage}
    lines.extend(
        [
            "",
            "## UNIVERSE_HETEROGENEITY",
            "",
            f"- Classification: `{heterogeneity['status']}`.",
            f"- Predefined sufficient universes: `{', '.join(heterogeneity['sufficient_universes']) or 'none'}`.",
            f"- `NATIONAL_TEAM_APPLICABILITY={national_team_applicability}`.",
            f"- Global total-bias cancellation detected (descriptive only): `{heterogeneity['global_total_bias_cancellation_detected']}`.",
            "",
            "### Bias by sufficient universe",
            "",
            "| universe | verified n | home bias | 95% CI | away bias | 95% CI | total bias | 95% CI |",
            "|---|---:|---:|---|---:|---|---:|---|",
        ]
    )
    bias_evidence = heterogeneity.get("lambda_bias_evidence_by_universe") or {}
    for universe in heterogeneity["sufficient_universes"]:
        evidence = bias_evidence.get(universe) or {}
        home = evidence.get("lambda_home_bias_predicted_minus_actual") or {}
        away = evidence.get("lambda_away_bias_predicted_minus_actual") or {}
        total = evidence.get("lambda_total_mean_bias_predicted_minus_actual") or {}
        lines.append(
            f"| `{universe}` | {coverage_by_universe[universe]['verified_n']} | {_fmt_number(home.get('value'))} | {_fmt_ci(home.get('bootstrap_ci_95'))} | {_fmt_number(away.get('value'))} | {_fmt_ci(away.get('bootstrap_ci_95'))} | {_fmt_number(total.get('value'))} | {_fmt_ci(total.get('bootstrap_ci_95'))} |"
        )
    lines.extend(
        [
            "",
            "### Pairwise total-bias difference bootstrap",
            "",
            "| universe A | universe B | A bias - B bias | 95% CI | CI excludes 0 |",
            "|---|---|---:|---|---|",
        ]
    )
    for pair in heterogeneity.get("pairwise_total_bias_differences") or []:
        lines.append(
            f"| `{pair['universe_a']}` | `{pair['universe_b']}` | {_fmt_number(pair.get('point_estimate_bias_a_minus_bias_b'))} | {_fmt_ci(pair.get('bootstrap_ci_95_bias_difference'))} | `{pair.get('ci_excludes_zero')}` |"
        )
    lines.extend(
        [
            "",
            "## Final classification",
            "",
            "| defect | status | reason |",
            "|---|---|---|",
        ]
    )
    for defect in ("MEAN_INTENSITY", "DISTRIBUTION_SHAPE", "COMPETITION_UNIVERSE_HETEROGENEITY"):
        classification = classifications[defect]
        lines.append(f"| `{defect}` | `{classification['status']}` | {classification['reason']} |")
    lines.extend(
        [
            "",
            f"`PRIMARY_DEFECT={summary['primary_defect']}`",
            "",
            "## Stop state",
            "",
            "- No production/model/calibration/provider/data truth was modified.",
            "- No parameter search, rho adjustment, bivariate model, xG model, or next Challenger was implemented.",
            "",
        ]
    )
    return "\n".join(lines)

def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--audit", type=Path, default=DEFAULT_AUDIT)
    parser.add_argument("--jobs-root", type=Path, default=DEFAULT_JOBS_ROOT)
    parser.add_argument("--prediction-root", type=Path, default=DEFAULT_PREDICTION_ROOT)
    parser.add_argument("--result-root", type=Path, default=DEFAULT_RESULT_ROOT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--seed", type=int, default=BOOTSTRAP_SEED)
    parser.add_argument("--bootstrap-replicates", type=int, default=DEFAULT_BOOTSTRAP_REPLICATES)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.bootstrap_replicates < 1:
        raise ValueError("--bootstrap-replicates must be positive")
    root = PROJECT_ROOT.resolve()
    cohort = _load_cohort(
        root,
        args.manifest.resolve(),
        args.audit.resolve(),
        args.jobs_root.resolve(),
        args.prediction_root.resolve(),
        args.result_root.resolve(),
    )
    summary = build_summary(cohort, seed=args.seed, replicates=args.bootstrap_replicates)
    report = build_report(summary)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (args.output_dir / "report.md").write_text(report, encoding="utf-8")
    print(f"PRIMARY_DEFECT={summary['primary_defect']}")
    print(f"NATIONAL_TEAM_APPLICABILITY={summary['NATIONAL_TEAM_APPLICABILITY']}")
    print(f"COHORT=pinned:{summary['cohort']['pinned_n']} verified:{summary['cohort']['verified_n']}")
    print(f"ARTIFACT={args.output_dir / 'summary.json'}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"AUDIT_ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
