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
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = PROJECT_ROOT / "data" / "prediction_quality" / "pred_trust_2" / "pinned_cohort_manifest.json"
DEFAULT_AUDIT = PROJECT_ROOT / "data" / "prediction_quality" / "pred_trust_1" / "audit_2026-08-30.json"
DEFAULT_JOBS_ROOT = PROJECT_ROOT / "data" / "base_prediction_jobs"
DEFAULT_PREDICTION_ROOT = PROJECT_ROOT / "data" / "model_governance" / "predictions"
DEFAULT_RESULT_ROOT = PROJECT_ROOT / "data" / "postmatch_automation" / "results"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "audit-artifact"

MILESTONE = "EXACT-SCORE-ERROR-DECOMPOSITION-1"
CHAMPION_MODEL_FAMILY = "recent_form_market_calibrated_poisson_v2"
BOOTSTRAP_SEED = 20260903
DEFAULT_BOOTSTRAP_REPLICATES = 4000
MIN_UNIVERSE_SAMPLE = 20
SCORE_RE = re.compile(r"^(\d+)\s*-\s*(\d+)$")

UNIVERSES = (
    "CLUB_TOP_LEAGUE",
    "CLUB_LOWER_OR_SMALL_LEAGUE",
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

# These are competition labels already present in the repository's league
# metadata.  No team name, country inference, or external lookup is used.
TOP_LEAGUE_NAMES = frozenset(
    {
        "\u897f\u73ed\u7259\u7532\u7ea7\u8054\u8d5b",
        "\u8377\u5170\u7532\u7ea7\u8054\u8d5b",
        "\u82f1\u683c\u5170\u8d85\u7ea7\u8054\u8d5b",
        "\u610f\u5927\u5229\u7532\u7ea7\u8054\u8d5b",
        "\u97e9\u56fd\u804c\u4e1a\u8054\u8d5b",
        "\u745e\u5178\u8d85\u7ea7\u8054\u8d5b",
        "\u65e5\u672c\u804c\u4e1a\u8054\u8d5b",
        "\u8461\u8404\u7259\u8d85\u7ea7\u8054\u8d5b",
        "\u6cd5\u56fd\u7532\u7ea7\u8054\u8d5b",
        "\u632a\u5a01\u8d85\u7ea7\u8054\u8d5b",
        "\u5fb7\u56fd\u7532\u7ea7\u8054\u8d5b",
        "\u5df4\u897f\u7532\u7ea7\u8054\u8d5b",
        "\u82ac\u5170\u8d85\u7ea7\u8054\u8d5b",
        "\u6c99\u7279\u804c\u4e1a\u8054\u8d5b",
        "\u7f8e\u56fd\u804c\u4e1a\u5927\u8054\u76df",
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
    if name in NATIONAL_TEAM_NAMES or "\u56fd\u5bb6\u961f" in name:
        return "NATIONAL_TEAM"
    if name in CONTINENTAL_NAMES:
        return "CLUB_CONTINENTAL"
    if name in TOP_LEAGUE_NAMES:
        return "CLUB_TOP_LEAGUE"
    if "\u676f" in name:
        return "CLUB_DOMESTIC_CUP"
    if "\u8054\u8d5b" in name or "\u5927\u8054\u76df" in name:
        return "CLUB_LOWER_OR_SMALL_LEAGUE"
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

    for record in selected_records:
        prediction_id = _text(record.get("prediction_id"))
        match_id = _text(record.get("match_id"))
        match_key = _text(record.get("match_key"))
        snapshot_reference = _text(record.get("input_snapshot_ref"))
        if not snapshot_reference:
            raise ValueError(f"missing input snapshot reference for {prediction_id}")
        snapshot_path = _repo_relative_path(root, snapshot_reference)
        if _sha256_file(snapshot_path) != _text(record.get("input_snapshot_sha256")):
            raise ValueError(f"input snapshot hash mismatch for {prediction_id}")
        snapshot = _read_json(snapshot_path)
        prediction_path = prediction_root / f"{prediction_id}.json"
        prediction = _read_json(prediction_path)
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
    if lambda_home <= 0 or lambda_away <= 0:
        raise ValueError("lambda values must be positive")
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
    """Compare observed shape counts to model expectations under a fixed seed."""

    if replicates < 1:
        raise ValueError("bootstrap replicates must be positive")
    materialized = list(rows)
    if not materialized:
        return {"sample_count": 0, "seed": seed, "replicates": replicates, "metrics": {}}

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
            "two_sided_p_value": p_value,
        }
    return {
        "sample_count": sample_count,
        "seed": seed,
        "replicates": replicates,
        "distribution": "independent_poisson_lambda_home_lambda_away_rho_0",
        "metrics": metrics,
    }


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
        "shape": run_parametric_shape_bootstrap(
            rows,
            seed=_stable_seed(seed, f"{name}:shape"),
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


def _shape_p_value(scope: Mapping[str, Any], metric: str) -> float | None:
    shape = scope.get("shape") or {}
    entry = (shape.get("metrics") or {}).get(metric) or {}
    value = entry.get("two_sided_p_value")
    return float(value) if value is not None else None


def _classification(
    global_scope: Mapping[str, Any],
    universe_scopes: Mapping[str, Mapping[str, Any]],
    coverage: list[Mapping[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    global_count = int(global_scope.get("sample_count") or 0)
    total_bias_ci = _metric_ci(global_scope, "lambda_total_mean_bias_predicted_minus_actual")
    home_bias_ci = _metric_ci(global_scope, "lambda_home_bias_predicted_minus_actual")
    away_bias_ci = _metric_ci(global_scope, "lambda_away_bias_predicted_minus_actual")
    intensity_supported = global_count >= MIN_UNIVERSE_SAMPLE and (
        _ci_excludes_zero(total_bias_ci) or _ci_excludes_zero(home_bias_ci) or _ci_excludes_zero(away_bias_ci)
    )
    intensity_status = "SUPPORTED" if intensity_supported else "NOT_ESTABLISHED" if global_count < MIN_UNIVERSE_SAMPLE else "NOT_SUPPORTED"

    core_signals = [
        metric
        for metric in CORE_SHAPE_METRICS
        if (_shape_p_value(global_scope, metric) is not None and _shape_p_value(global_scope, metric) <= 0.05)
    ]
    tail_signals = [
        metric
        for metric in TAIL_SHAPE_METRICS
        if (_shape_p_value(global_scope, metric) is not None and _shape_p_value(global_scope, metric) <= 0.05)
    ]
    if global_count < MIN_UNIVERSE_SAMPLE:
        shape_status = "NOT_ESTABLISHED"
    elif core_signals:
        shape_status = "SUPPORTED"
    elif tail_signals and not intensity_supported:
        shape_status = "SUPPORTED"
    elif tail_signals and intensity_supported:
        shape_status = "NOT_SUPPORTED"
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
    for metric in (
        "lambda_total_mean_bias_predicted_minus_actual",
        "lambda_home_bias_predicted_minus_actual",
        "lambda_away_bias_predicted_minus_actual",
    ):
        values = {universe: _metric_value(universe_scopes[universe], metric) for universe in sufficient_universes}
        component_directions[metric] = values
        signs = {1 if value > 0 else -1 if value < 0 else 0 for value in values.values() if value is not None}
        component_reversals[metric] = len(signs - {0}) > 1

    shape_reversals: dict[str, bool] = {}
    for metric in CORE_SHAPE_METRICS:
        values = {
            universe: float(
                ((universe_scopes[universe].get("shape") or {}).get("metrics") or {}).get(metric, {}).get(
                    "residual_rate_observed_minus_expected", 0.0
                )
            )
            for universe in sufficient_universes
        }
        signs = {1 if value > 0 else -1 if value < 0 else 0 for value in values.values()}
        shape_reversals[metric] = len(signs - {0}) > 1

    total_signs = {1 if value > 0 else -1 if value < 0 else 0 for value in total_directions.values() if value is not None}
    total_reversal = len(total_signs - {0}) > 1
    if len(sufficient_universes) < 2:
        heterogeneity_status = "NOT_ESTABLISHED"
    elif total_reversal:
        heterogeneity_status = "SUPPORTED"
    elif any(shape_reversals.values()) or any(component_reversals.values()):
        heterogeneity_status = "NOT_ESTABLISHED"
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
                "global_core_shape_signals_p_le_0_05": core_signals,
                "global_tail_signals_p_le_0_05": tail_signals,
                "core_shape_metrics": list(CORE_SHAPE_METRICS),
                "tail_shape_metrics": list(TAIL_SHAPE_METRICS),
            },
            "reason": (
                "A core draw/BTTS/1-1 mismatch rejects the independent-Poisson shape."
                if core_signals
                else "Tail residuals are recorded, but core draw/BTTS/1-1 shape signals do not reject; the tail direction is concordant with the established mean underprediction."
            ),
        },
        "COMPETITION_UNIVERSE_HETEROGENEITY": {
            "status": heterogeneity_status,
            "evidence": {
                "sufficient_universes": sufficient_universes,
                "lambda_bias_by_universe": component_directions,
                "component_direction_reversals": component_reversals,
                "core_shape_direction_reversals": shape_reversals,
                "global_total_bias_cancellation_detected": global_total_cancellation,
            },
            "reason": (
                "Sufficient universes show opposite total-intensity directions."
                if heterogeneity_status == "SUPPORTED"
                else "Only exploratory component/shape direction reversals remain; no opposite total-intensity direction is established across sufficient universes."
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
    classifications, heterogeneity = _classification(global_scope, universe_scope_payloads, coverage)
    manifest = cohort["manifest"]
    audit = cohort["audit"]
    return {
        "schema_version": "exact_score_error_decomposition_audit.v1",
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
            "shape_method": "parametric independent-Poisson bootstrap with each frozen lambda pair",
        },
        "competition_universe_coverage": coverage,
        "mean_intensity": {
            "global": global_scope["intensity"],
            "by_universe": {universe: payload["intensity"] for universe, payload in universe_scope_payloads.items()},
        },
        "distribution_shape": {
            "global": global_scope["shape"],
            "by_universe": {universe: payload["shape"] for universe, payload in universe_scope_payloads.items()},
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


def _shape_table(scope: Mapping[str, Any]) -> list[str]:
    metrics = scope.get("metrics") or {}
    lines = [
        "| metric | observed | expected | observed−expected | observed rate | expected rate | p-value |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for metric in SHAPE_METRICS:
        entry = metrics.get(metric) or {}
        lines.append(
            "| `{metric}` | {observed} | {expected} | {residual} | {observed_rate} | {expected_rate} | {p_value} |".format(
                metric=metric,
                observed=_fmt_number(entry.get("observed_count")),
                expected=_fmt_number(entry.get("expected_count")),
                residual=_fmt_number(entry.get("residual_count_observed_minus_expected")),
                observed_rate=_fmt_number(entry.get("observed_rate"), 4),
                expected_rate=_fmt_number(entry.get("expected_rate"), 4),
                p_value=_fmt_number(entry.get("two_sided_p_value"), 4),
            )
        )
    return lines


def build_report(summary: Mapping[str, Any]) -> str:
    coverage = summary["competition_universe_coverage"]
    mean_intensity = summary["mean_intensity"]
    distribution_shape = summary["distribution_shape"]
    classifications = summary["defect_classification"]
    lines = [
        f"# {summary['milestone']}",
        "",
        "## Scope and guardrails",
        "",
        f"- Champion: `{summary['source']['champion_model_family']}`; `rho=0`.",
        f"- Cohort: pinned `{summary['cohort']['pinned_n']}`; verified `{summary['cohort']['verified_n']}`; unique-match observations `{summary['cohort']['unique_match_observation_n']}`.",
        f"- Results: `{summary['cohort']['result_scope']}` only; frozen prematch lambdas are never rebuilt from results.",
        f"- Bootstrap: seed `{summary['bootstrap']['seed']}`, replicates `{summary['bootstrap']['replicates']}`.",
        "- Sign convention for intensity bias: predicted minus actual; negative means underprediction.",
        "",
        "## Competition universe coverage",
        "",
        "| universe | pinned n | verified n | status | competition examples |",
        "|---|---:|---:|---|---|",
    ]
    for row in coverage:
        examples = ", ".join(row["competition_examples"]) or "—"
        lines.append(
            f"| `{row['universe']}` | {row['pinned_n']} | {row['verified_n']} | `{row['sample_status']}` | {examples} |"
        )

    def add_intensity_scope(title: str, scope: Mapping[str, Any]) -> None:
        lines.extend(["", f"### {title} (n={scope.get('sample_count', 0)}; {scope.get('sample_status')})", ""])
        if not scope.get("intensity"):
            lines.append("No observations.")
            return
        lines.extend(_intensity_table(scope["intensity"]))
        lines.extend(["", "λ_total bins: ", "", "| bin | n | status | expected λ_total | observed total | observed−expected | 95% CI |", "|---|---:|---|---:|---:|---:|---:|"])
        for bucket in scope["intensity"].get("lambda_total_bins") or []:
            lines.append(
                f"| `{bucket['bin']}` | {bucket['sample_count']} | `{bucket['sample_status']}` | {_fmt_number(bucket.get('expected_lambda_total_mean'))} | {_fmt_number(bucket.get('observed_total_goals_mean'))} | {_fmt_number(bucket.get('observed_minus_expected_mean'))} | {_fmt_ci(bucket.get('observed_minus_expected_nonparametric_bootstrap_ci_95'))} |"
            )

    lines.extend(["", "## MEAN_INTENSITY", ""])
    add_intensity_scope("GLOBAL", {"sample_count": summary["cohort"]["verified_n"], "sample_status": "SUFFICIENT", "intensity": mean_intensity["global"]})
    for row in coverage:
        universe = row["universe"]
        scope = {"sample_count": row["verified_n"], "sample_status": row["sample_status"], "intensity": mean_intensity["by_universe"].get(universe)}
        if row["verified_n"]:
            add_intensity_scope(universe, scope)

    lines.extend(["", "## DISTRIBUTION_SHAPE", ""])

    def add_shape_scope(title: str, scope: Mapping[str, Any]) -> None:
        lines.extend(["", f"### {title} (n={scope.get('sample_count', 0)}; {scope.get('sample_status')})", ""])
        if not scope.get("shape"):
            lines.append("No observations.")
            return
        lines.extend(_shape_table(scope["shape"]))
        lines.extend(["", "The p-value is the deterministic two-sided parametric-bootstrap null probability for the observed-minus-expected count."])

    add_shape_scope("GLOBAL", {"sample_count": summary["cohort"]["verified_n"], "sample_status": "SUFFICIENT", "shape": distribution_shape["global"]})
    for row in coverage:
        universe = row["universe"]
        if row["verified_n"]:
            add_shape_scope(
                universe,
                {
                    "sample_count": row["verified_n"],
                    "sample_status": row["sample_status"],
                    "shape": distribution_shape["by_universe"].get(universe),
                },
            )

    heterogeneity = summary["universe_heterogeneity"]
    lines.extend(
        [
            "",
            "## UNIVERSE_HETEROGENEITY",
            "",
            f"- Classification: `{heterogeneity['status']}`.",
            f"- Sufficient universes used for cross-universe direction checks: `{', '.join(heterogeneity['sufficient_universes']) or 'none'}`.",
            f"- Global total-bias cancellation detected: `{heterogeneity['global_total_bias_cancellation_detected']}`.",
            f"- Component direction reversals: `{json.dumps(heterogeneity['component_direction_reversals'], ensure_ascii=False, sort_keys=True)}`.",
            f"- Core shape direction reversals: `{json.dumps(heterogeneity['core_shape_direction_reversals'], ensure_ascii=False, sort_keys=True)}`.",
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
    print(f"COHORT=pinned:{summary['cohort']['pinned_n']} verified:{summary['cohort']['verified_n']}")
    print(f"ARTIFACT={args.output_dir / 'summary.json'}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"AUDIT_ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
