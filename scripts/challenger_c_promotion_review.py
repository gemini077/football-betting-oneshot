#!/usr/bin/env python3
"""Run the read-only Challenger C 100+ unique-match promotion review.

This module deliberately consumes the persisted #176/#217 shadow pair and
the canonical prematch representative selector.  It never regenerates C,
replays Champion, changes a model parameter, fetches a provider, or writes
production/prematch/postmatch state.  ``--write`` writes only the separate
research artifact requested by Issue #221.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import random
import statistics
import sys
from typing import Any, Iterable, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from market_contracts import split_quarter_line  # noqa: E402
from market_side_shadow import (  # noqa: E402
    CANDIDATE_ID,
    OUTCOMES,
    PROMOTION_REVIEW_MINIMUM,
    TAIL_KEYS,
    _actual_for_pair,
    _candidate_metrics,
    _is_promotion_eligible_pair,
    canonical_json,
    evaluate_paired_cohort,
    select_promotion_representatives,
)
from market_side_shadow_refresh import (  # noqa: E402
    build_identity_safe_result_map,
    discover_verified_results,
)


REVIEW_ID = "CHALLENGER-C-100-PROMOTION-REVIEW-1"
REVIEW_SCHEMA_VERSION = "challenger_c_100_promotion_review_1.v1"
DEFAULT_LATEST = ROOT / "data" / "prediction_quality" / "market_side_shadow_1" / "latest.json"
DEFAULT_PAIR_ROOT = ROOT / "data" / "prediction_quality" / "market_side_shadow_1" / "pairs"
DEFAULT_RESULT_ROOT = ROOT / "data" / "postmatch_automation" / "results"
DEFAULT_UNIVERSE_ROOT = ROOT / "data" / "prediction_universe"
DEFAULT_CONFIG = ROOT / "config" / "model_governance.json"
DEFAULT_OUTPUT = ROOT / "artifacts" / "challenger-c-100-promotion-review-1" / "summary.json"
DEFAULT_REPORT = ROOT / "artifacts" / "challenger-c-100-promotion-review-1" / "report.md"

ROUTE_REFERENCE_UNIQUE_MATCHES = 109
MIN_MEANINGFUL_SLICE = 10
BOOTSTRAP_RESAMPLES = 10_000
IID_BOOTSTRAP_SEED = 221_1001
BLOCK_BOOTSTRAP_SEED = 221_1002
MARKET_BRIER_SEED = 221_1891
MARKET_LOGLOSS_SEED = 221_1892
EXACT_MAX_GOALS = 12
EXACT_CELL_COUNT = (EXACT_MAX_GOALS + 1) ** 2
EXACT_SUM_TOLERANCE = 1e-9
EPSILON = 1e-15

AUTHORITY = {
    "repository": "gemini077/Memory-Hub",
    "path": "PROJECTS/Football-Betting-OneShot/RESEARCH/2026-09-06-PUBLIC-LAUNCH-TRUST-MARKET-READINESS-RESULT-R1.md",
    "sha256": "860ba05aa8dbd94b5311f3ec0653ee1d11422cf7",
    "url": "https://github.com/gemini077/Memory-Hub/blob/main/PROJECTS/Football-Betting-OneShot/RESEARCH/2026-09-06-PUBLIC-LAUNCH-TRUST-MARKET-READINESS-RESULT-R1.md",
}

# The accepted #189 contract is used only for a same-time, descriptive Market
# control.  These values are not inputs to C, Champion, or a selector.
MARKET_MAX_GOALS = 20
MARKET_EPSILON = 1e-12
MARKET_OU_SOLVE_LOWER = 0.001
MARKET_OU_SOLVE_UPPER = 20.0
MARKET_OU_SOLVE_ITERATIONS = 90
MARKET_SHARE_SOLVE_LOWER = 0.01
MARKET_SHARE_SOLVE_UPPER = 0.99
MARKET_SHARE_SOLVE_ITERATIONS = 70
MARKET_HORIZON_BANDS = (
    {"id": "T_0_TO_60M", "label": "T-0 to <60m", "lower_minutes": 0.0, "upper_minutes": 60.0},
    {"id": "T_60_TO_180M", "label": "T-60m to <3h", "lower_minutes": 60.0, "upper_minutes": 180.0},
    {"id": "T_3_TO_6H", "label": "T-3h to <6h", "lower_minutes": 180.0, "upper_minutes": 360.0},
    {"id": "T_6_TO_12H", "label": "T-6h to <12h", "lower_minutes": 360.0, "upper_minutes": 720.0},
    {"id": "T_12_TO_24H", "label": "T-12h to <24h", "lower_minutes": 720.0, "upper_minutes": 1440.0},
    {"id": "T_24H_PLUS", "label": "T-24h+", "lower_minutes": 1440.0, "upper_minutes": None},
)

METRIC_PATHS = {
    "exact_top1": ("exact_score", "top1_hit_rate"),
    "exact_top3": ("exact_score", "top3_hit_rate"),
    "exact_nll": ("exact_score", "nll"),
    "one_x_two_accuracy": ("one_x_two", "accuracy"),
    "one_x_two_brier": ("one_x_two", "brier"),
    "one_x_two_log_loss": ("one_x_two", "log_loss"),
    "one_x_two_ece": ("one_x_two", "ece"),
    "btts_accuracy": ("btts", "accuracy"),
    "btts_brier": ("btts", "brier"),
    "btts_log_loss": ("btts", "log_loss"),
    "btts_ece": ("btts", "ece"),
    "ou_2_5_accuracy": ("ou_2_5", "accuracy"),
    "ou_2_5_brier": ("ou_2_5", "brier"),
    "ou_2_5_log_loss": ("ou_2_5", "log_loss"),
    "one_one_top1_share": ("distribution", "one_one_top1_share"),
    "lambda_median_abs_gap": ("lambda", "median_abs_gap"),
    "lambda_gap_lt_0_5_share": ("lambda", "gap_lt_0_5_share"),
}

# Compatibility export for the previous review tests/callers.  It is retained
# as historical version-row evidence only and is not used by #221's gate.
EXPECTED_ACCEPTED_VERSION_ROW_METRICS = {
    "champion": {
        "exact_top1": 0.107142857,
        "exact_top3": 0.285714286,
        "exact_nll": 3.028904590,
        "one_x_two_accuracy": 0.821428571,
        "one_x_two_brier": 0.435564753,
        "one_x_two_log_loss": 0.771894548,
        "one_x_two_ece": 0.161987113,
        "btts_accuracy": 0.428571429,
        "btts_brier": 0.276515756,
        "btts_log_loss": 0.748053264,
        "btts_ece": 0.156400330,
        "ou_2_5_accuracy": 0.660714286,
        "ou_2_5_brier": 0.226804847,
        "ou_2_5_log_loss": 0.645220633,
        "one_one_top1_share": 0.660714286,
        "lambda_median_abs_gap": 0.486788,
        "lambda_gap_lt_0_5_share": 0.526785714,
    },
    "challenger": {
        "exact_top1": 0.125000000,
        "exact_top3": 0.303571429,
        "exact_nll": 2.974156721,
        "one_x_two_accuracy": 0.803571429,
        "one_x_two_brier": 0.378420080,
        "one_x_two_log_loss": 0.687059633,
        "one_x_two_ece": 0.126259979,
        "btts_accuracy": 0.455357143,
        "btts_brier": 0.281726415,
        "btts_log_loss": 0.759251846,
        "btts_ece": 0.163669907,
        "ou_2_5_accuracy": 0.660714286,
        "ou_2_5_brier": 0.226805045,
        "ou_2_5_log_loss": 0.645221067,
        "one_one_top1_share": 0.383928571,
        "lambda_median_abs_gap": 0.773430,
        "lambda_gap_lt_0_5_share": 0.285714286,
    },
}
EXPECTED_ACCEPTED_METRICS = EXPECTED_ACCEPTED_VERSION_ROW_METRICS


class MarketAuditError(ValueError):
    """Raised when the accepted Market-only contract is not identifiable."""


def _load_json(path: Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _write_json(path: Path, value: Any) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _repo_relative(path: Path) -> str:
    try:
        return Path(path).resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return str(path)


def _score_pair(value: Any) -> tuple[int, int] | None:
    if isinstance(value, (tuple, list)) and len(value) == 2:
        left, right = value
    elif isinstance(value, Mapping):
        left = value.get("home_goals", value.get("home_score"))
        right = value.get("away_goals", value.get("away_score"))
    else:
        text = _text(value)
        if "-" not in text:
            return None
        left, right = text.split("-", 1)
    try:
        home, away = int(left), int(right)
    except (TypeError, ValueError):
        return None
    if home < 0 or away < 0:
        return None
    return home, away


def _score_text(score: tuple[int, int]) -> str:
    return f"{score[0]}-{score[1]}"


def _actual_outcome(score: tuple[int, int]) -> str:
    if score[0] > score[1]:
        return "home"
    if score[0] < score[1]:
        return "away"
    return "draw"


def _metric_value(candidate: Mapping[str, Any], name: str) -> float | None:
    current: Any = candidate
    for key in METRIC_PATHS[name]:
        if not isinstance(current, Mapping):
            return None
        current = current.get(key)
    return _number(current)


def compact_candidate_metrics(candidate: Mapping[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {"sample_count": candidate.get("sample_count")}
    for name in METRIC_PATHS:
        result[name] = _metric_value(candidate, name)
    return result


def compact_evaluation(evaluation: Mapping[str, Any]) -> dict[str, Any]:
    return {
        candidate_id: compact_candidate_metrics(candidate)
        for candidate_id, candidate in (evaluation.get("candidates") or {}).items()
        if isinstance(candidate, Mapping)
    }


def _metric_projection_matches(
    observed: Mapping[str, Any],
    expected: Mapping[str, Mapping[str, Any]],
    *,
    tolerance: float = 1e-9,
) -> dict[str, Any]:
    mismatches: list[dict[str, Any]] = []
    for candidate_id, expected_metrics in expected.items():
        actual = observed.get(candidate_id) or {}
        for name, expected_value in expected_metrics.items():
            actual_value = _number(actual.get(name))
            expected_number = _number(expected_value)
            if expected_number is None:
                continue
            if actual_value is None or not math.isclose(
                actual_value, expected_number, rel_tol=0.0, abs_tol=tolerance
            ):
                mismatches.append({
                    "candidate": candidate_id,
                    "metric": name,
                    "expected": expected_number,
                    "observed": actual_value,
                })
    return {"status": "PASS" if not mismatches else "FAIL", "mismatches": mismatches}


def _load_universe_index(universe_root: Path) -> tuple[dict[str, dict[str, Any]], list[str]]:
    result: dict[str, dict[str, Any]] = {}
    fingerprints: dict[str, str] = {}
    conflicts: set[str] = set()
    for path in sorted(Path(universe_root).glob("*.json")):
        try:
            document = _load_json(path)
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(document, Mapping):
            continue
        for row in document.get("fixtures") or []:
            if not isinstance(row, Mapping) or row.get("matchId") is None:
                continue
            key = str(row["matchId"])
            fingerprint = canonical_json({
                "league": row.get("league"),
                "home": row.get("home"),
                "away": row.get("away"),
                "kickoff": row.get("kickoff"),
            })
            if key in fingerprints and fingerprints[key] != fingerprint:
                conflicts.add(key)
                continue
            fingerprints[key] = fingerprint
            result[key] = dict(row)
    return result, sorted(conflicts)


def _load_universe_map(universe_root: Path) -> dict[str, dict[str, Any]]:
    """Compatibility wrapper for the previous review helper."""

    return _load_universe_index(universe_root)[0]


def _horizon_minutes(pair: Mapping[str, Any]) -> float | None:
    kickoff = _parse_time(pair.get("kickoff_at"))
    freeze = _parse_time(pair.get("freeze_created_at"))
    if kickoff is None or freeze is None or freeze >= kickoff:
        return None
    return (kickoff - freeze).total_seconds() / 60.0


def horizon_band(minutes: float | None) -> str | None:
    if minutes is None:
        return None
    for band in MARKET_HORIZON_BANDS:
        upper = band["upper_minutes"]
        if minutes >= band["lower_minutes"] and (upper is None or minutes < upper):
            return str(band["id"])
    return None


def _pair_metadata(pair: Mapping[str, Any], universe_map: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    match_id = str(pair.get("match_id") or "")
    universe = universe_map.get(match_id) or {}
    challenger_inputs = (pair.get("challenger") or {}).get("inputs") or {}
    market_share = _number(challenger_inputs.get("market_share"))
    fair_values: list[float] = []
    snapshot_ref = pair.get("input_snapshot_ref")
    if snapshot_ref:
        try:
            document = _load_json(ROOT / str(snapshot_ref))
            baseline = ((document.get("input") or {}).get("official_market_baseline") or {})
            fair_values = sorted(
                [float(item) for item in (baseline.get("fair_probabilities") or {}).values() if _number(item) is not None],
                reverse=True,
            )
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            fair_values = []
    horizon = _horizon_minutes(pair)
    return {
        "league": universe.get("league") or universe.get("competition") or "<missing>",
        "market_share": market_share,
        "favorite_probability": fair_values[0] if fair_values else None,
        "favorite_gap": fair_values[0] - fair_values[1] if len(fair_values) >= 2 else None,
        "horizon_minutes": horizon,
        "horizon_band": horizon_band(horizon),
        "input_snapshot_ref": pair.get("input_snapshot_ref"),
    }


def _pair_integrity_issues(pair: Mapping[str, Any]) -> list[str]:
    if not _is_promotion_eligible_pair(pair):
        return []
    pair_id = _text(pair.get("pair_id")) or "<missing-pair>"
    issues: list[str] = []
    integrity = pair.get("integrity")
    if not isinstance(integrity, Mapping) or not integrity:
        issues.append(f"{pair_id}:integrity_missing")
    else:
        issues.extend(f"{pair_id}:{key}" for key, value in integrity.items() if value is not True)
    for key in ("same_fixture", "champion_preserved"):
        if pair.get(key) is not True:
            issues.append(f"{pair_id}:{key}")
    if pair.get("post_match_input_used_for_generation") is not False:
        issues.append(f"{pair_id}:post_match_input_used_for_generation")
    kickoff = _parse_time(pair.get("kickoff_at"))
    source_cutoff = _parse_time(pair.get("source_cutoff"))
    freeze = _parse_time(pair.get("freeze_created_at"))
    if kickoff is None or source_cutoff is None or freeze is None:
        issues.append(f"{pair_id}:prematch_chronology_missing")
    else:
        if source_cutoff >= kickoff:
            issues.append(f"{pair_id}:source_cutoff_not_before_kickoff")
        if freeze >= kickoff:
            issues.append(f"{pair_id}:freeze_not_before_kickoff")
    return issues


def _pair_file_audit(
    eligible_pairs: Sequence[Mapping[str, Any]],
    pair_root: Path,
) -> dict[str, Any]:
    failures: list[dict[str, Any]] = []
    checked = 0
    for pair in eligible_pairs:
        pair_id = _text(pair.get("pair_id"))
        if not pair_id:
            failures.append({"pair_id": None, "reason": "PAIR_ID_MISSING"})
            continue
        checked += 1
        path = Path(pair_root) / f"{pair_id}.json"
        if not path.exists():
            failures.append({"pair_id": pair_id, "reason": "PAIR_FILE_MISSING"})
            continue
        try:
            persisted = _load_json(path)
        except (OSError, json.JSONDecodeError):
            failures.append({"pair_id": pair_id, "reason": "PAIR_FILE_INVALID_JSON"})
            continue
        if not isinstance(persisted, Mapping) or dict(persisted) != dict(pair):
            failures.append({"pair_id": pair_id, "reason": "PAIR_FILE_NOT_EQUAL_TO_LATEST"})
            continue
        digest = _text(persisted.get("pair_digest"))
        without_digest = {key: value for key, value in persisted.items() if key != "pair_digest"}
        recomputed = hashlib.sha256(canonical_json(without_digest).encode("utf-8")).hexdigest()
        if not digest or recomputed != digest:
            failures.append({
                "pair_id": pair_id,
                "reason": "PAIR_DIGEST_MISMATCH",
                "expected": digest,
                "recomputed": recomputed,
            })
    return {"status": "PASS" if not failures else "FAIL", "checked": checked, "failures": failures}


def _forbidden_key_paths(value: Any, prefix: str = "") -> list[str]:
    forbidden = {"actual_result", "settlement", "metrics", "settled_at"}
    paths: list[str] = []
    if isinstance(value, Mapping):
        for key, child in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            if str(key) in forbidden:
                paths.append(path)
            paths.extend(_forbidden_key_paths(child, path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            paths.extend(_forbidden_key_paths(child, f"{prefix}[{index}]"))
    return paths


def _validate_probabilities(output: Mapping[str, Any], issues: list[str], label: str) -> dict[str, float]:
    raw = output.get("probabilities")
    if not isinstance(raw, Mapping):
        issues.append(f"{label}:ONE_X_TWO_MISSING")
        return {}
    values = {key: _number(raw.get(key)) for key in OUTCOMES}
    if any(value is None or value < 0.0 for value in values.values()):
        issues.append(f"{label}:ONE_X_TWO_INVALID")
        return {}
    total = sum(float(value) for value in values.values())
    if abs(total - 1.0) > 1e-9:
        issues.append(f"{label}:ONE_X_TWO_NOT_NORMALIZED")
    return {key: float(value) for key, value in values.items()}


def _validate_exact_candidate(
    pair: Mapping[str, Any],
    output: Mapping[str, Any],
    label: str,
) -> tuple[dict[tuple[int, int], float], list[str]]:
    issues: list[str] = []
    pair_id = _text(pair.get("pair_id"))
    expected_id = "champion" if label == "champion" else CANDIDATE_ID
    if _text(output.get("candidate_id")) != expected_id:
        issues.append(f"{pair_id}:{label}:candidate_id_mismatch")
    if _text(output.get("match_id")) != _text(pair.get("match_id")):
        issues.append(f"{pair_id}:{label}:match_id_mismatch")
    if _text(output.get("source_cutoff")) != _text(pair.get("source_cutoff")):
        issues.append(f"{pair_id}:{label}:source_cutoff_mismatch")
    if _text(output.get("frozen_input_digest")) != _text(pair.get("frozen_input_digest")):
        issues.append(f"{pair_id}:{label}:frozen_input_digest_mismatch")
    if pair.get("freeze_eligibility") is not None and output.get("freeze_eligibility") != pair.get("freeze_eligibility"):
        issues.append(f"{pair_id}:{label}:freeze_eligibility_mismatch")
    if label == "challenger" and output.get("post_match_parameter_input") is not False:
        issues.append(f"{pair_id}:{label}:post_match_parameter_input")
    if label == "champion" and output.get("post_match_parameter_input") not in (None, False):
        issues.append(f"{pair_id}:{label}:post_match_parameter_input")
    forbidden = _forbidden_key_paths(output)
    issues.extend(f"{pair_id}:{label}:forbidden_{path}" for path in forbidden)
    _validate_probabilities(output, issues, f"{pair_id}:{label}")

    rows = output.get("exact_score_distribution")
    distribution: dict[tuple[int, int], float] = {}
    ranks: list[int] = []
    if not isinstance(rows, list) or len(rows) != EXACT_CELL_COUNT:
        issues.append(f"{pair_id}:{label}:EXACT_GRID_CELL_COUNT")
        rows = rows if isinstance(rows, list) else []
    for row in rows:
        if not isinstance(row, Mapping):
            issues.append(f"{pair_id}:{label}:EXACT_ROW_INVALID")
            continue
        score = _score_pair(row.get("score"))
        probability = _number(row.get("probability"))
        rank = row.get("rank")
        if score is None or score[0] > EXACT_MAX_GOALS or score[1] > EXACT_MAX_GOALS:
            issues.append(f"{pair_id}:{label}:EXACT_SCORE_OUT_OF_GRID")
            continue
        if probability is None or probability < 0.0 or probability > 1.0:
            issues.append(f"{pair_id}:{label}:EXACT_PROBABILITY_INVALID")
            continue
        if score in distribution:
            issues.append(f"{pair_id}:{label}:EXACT_SCORE_DUPLICATE")
            continue
        distribution[score] = probability
        try:
            ranks.append(int(rank))
        except (TypeError, ValueError):
            issues.append(f"{pair_id}:{label}:EXACT_RANK_INVALID")
    if len(distribution) != EXACT_CELL_COUNT:
        issues.append(f"{pair_id}:{label}:EXACT_GRID_NOT_COMPLETE")
    if sorted(ranks) != list(range(1, EXACT_CELL_COUNT + 1)):
        issues.append(f"{pair_id}:{label}:EXACT_RANKS_NOT_COMPLETE")
    if distribution and abs(sum(distribution.values()) - 1.0) > EXACT_SUM_TOLERANCE:
        issues.append(f"{pair_id}:{label}:EXACT_GRID_NOT_NORMALIZED")
    ordered = sorted(rows, key=lambda row: int(row.get("rank", 10**9)) if isinstance(row, Mapping) and str(row.get("rank", "")).isdigit() else 10**9)
    expected_top = [_text(row.get("score")) for row in ordered[:3] if isinstance(row, Mapping)]
    top1 = _text(output.get("score_top1"))
    top3 = [_text(item) for item in output.get("score_top3") or []]
    if expected_top and top1 != expected_top[0]:
        issues.append(f"{pair_id}:{label}:EXACT_TOP1_MISMATCH")
    if expected_top[:3] != top3[:3]:
        issues.append(f"{pair_id}:{label}:EXACT_TOP3_MISMATCH")
    return distribution, issues


def _validate_candidate_output(
    pair: Mapping[str, Any],
    actual: tuple[int, int],
    label: str,
) -> tuple[dict[str, Any] | None, list[str]]:
    output = pair.get(label)
    if not isinstance(output, Mapping):
        return None, [f"{_text(pair.get('pair_id'))}:{label}:OUTPUT_MISSING"]
    distribution, issues = _validate_exact_candidate(pair, output, label)
    actual_probability = distribution.get(actual)
    if actual_probability is None or actual_probability <= 0.0:
        issues.append(f"{_text(pair.get('pair_id'))}:{label}:ACTUAL_SCORE_OUT_OF_SUPPORT")
    probabilities = _validate_probabilities(output, issues, f"{_text(pair.get('pair_id'))}:{label}")
    if not probabilities:
        return None, issues
    btts_probability = _number(output.get("btts_probability"))
    ou_probability = _number(output.get("ou_2_5_probability"))
    if btts_probability is None or not 0.0 <= btts_probability <= 1.0:
        issues.append(f"{_text(pair.get('pair_id'))}:{label}:BTTS_PROBABILITY_INVALID")
        btts_probability = None
    if ou_probability is None or not 0.0 <= ou_probability <= 1.0:
        issues.append(f"{_text(pair.get('pair_id'))}:{label}:OU_PROBABILITY_INVALID")
        ou_probability = None
    tails_raw = output.get("tail_probabilities") if isinstance(output.get("tail_probabilities"), Mapping) else {}
    tails: dict[str, float] = {}
    for key in TAIL_KEYS:
        value = _number(tails_raw.get(key))
        if value is None or not 0.0 <= value <= 1.0:
            issues.append(f"{_text(pair.get('pair_id'))}:{label}:{key}_INVALID")
        else:
            tails[key] = value
    lambda_home = _number(output.get("lambda_home"))
    lambda_away = _number(output.get("lambda_away"))
    lambda_total = _number(output.get("lambda_total"))
    if lambda_home is None or lambda_away is None or lambda_total is None:
        issues.append(f"{_text(pair.get('pair_id'))}:{label}:LAMBDA_INVALID")
    elif abs(lambda_home + lambda_away - lambda_total) > 1e-6:
        issues.append(f"{_text(pair.get('pair_id'))}:{label}:LAMBDA_TOTAL_MISMATCH")
    if actual_probability is None or btts_probability is None or ou_probability is None or len(tails) != len(TAIL_KEYS) or lambda_home is None or lambda_away is None or lambda_total is None:
        return None, issues
    rank_by_score: dict[tuple[int, int], int] = {}
    rows = output.get("exact_score_distribution") or []
    for row in rows:
        if isinstance(row, Mapping):
            score = _score_pair(row.get("score"))
            try:
                rank = int(row.get("rank"))
            except (TypeError, ValueError):
                continue
            if score is not None:
                rank_by_score[score] = rank
    return {
        "probabilities": probabilities,
        "exact_distribution": distribution,
        "actual_probability": actual_probability,
        "actual_rank": rank_by_score.get(actual),
        "top1_score": _text(output.get("score_top1")),
        "top3_scores": [_text(item) for item in output.get("score_top3") or []],
        "btts_probability": btts_probability,
        "ou_2_5_probability": ou_probability,
        "tail_probabilities": tails,
        "lambda_home": lambda_home,
        "lambda_away": lambda_away,
        "lambda_total": lambda_total,
        "rho": _number(output.get("rho")),
        "formula": output.get("formula"),
    }, issues


def _quantile(values: Iterable[float], probability: float) -> float | None:
    ordered = sorted(float(value) for value in values if _number(value) is not None)
    if not ordered:
        return None
    position = (len(ordered) - 1) * probability
    lower, upper = math.floor(position), math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def _quantiles(values: Iterable[float]) -> dict[str, float | None]:
    return {
        key: _quantile(values, probability)
        for key, probability in (("P10", 0.10), ("P25", 0.25), ("P50", 0.50), ("P75", 0.75), ("P90", 0.90))
    }


def _candidate_observation(
    candidate: Mapping[str, Any],
    actual: tuple[int, int],
) -> dict[str, Any]:
    outcome = _actual_outcome(actual)
    probabilities = dict(candidate["probabilities"])
    btts_actual = actual[0] > 0 and actual[1] > 0
    ou_actual = sum(actual) >= 3
    btts_probability = candidate["btts_probability"]
    ou_probability = candidate["ou_2_5_probability"]
    tails = candidate["tail_probabilities"]
    return {
        "probabilities": probabilities,
        "outcome": outcome,
        "outcome_probability": candidate["actual_probability"],
        "exact_nll": -math.log(max(EPSILON, float(candidate["actual_probability"]))),
        "actual_score_rank": candidate["actual_rank"],
        "exact_top1": candidate["top1_score"] == _score_text(actual),
        "exact_top3": _score_text(actual) in candidate["top3_scores"][:3],
        "btts_probability": btts_probability,
        "btts_actual": btts_actual,
        "btts_accuracy": (btts_probability >= 0.5) == btts_actual,
        "btts_brier": (btts_probability - float(btts_actual)) ** 2,
        "btts_log_loss": -math.log(max(EPSILON, min(1.0 - EPSILON, btts_probability if btts_actual else 1.0 - btts_probability))),
        "ou_2_5_probability": ou_probability,
        "ou_2_5_actual": ou_actual,
        "ou_2_5_accuracy": (ou_probability >= 0.5) == ou_actual,
        "ou_2_5_brier": (ou_probability - float(ou_actual)) ** 2,
        "ou_2_5_log_loss": -math.log(max(EPSILON, min(1.0 - EPSILON, ou_probability if ou_actual else 1.0 - ou_probability))),
        "tail_probabilities": dict(tails),
        "tail_actuals": {key: sum(actual) >= int(key.rsplit("_", 1)[-1]) for key in TAIL_KEYS},
        "lambda_home": candidate["lambda_home"],
        "lambda_away": candidate["lambda_away"],
        "lambda_total": candidate["lambda_total"],
        "lambda_abs_gap": abs(float(candidate["lambda_home"]) - float(candidate["lambda_away"])),
        "top1_score": candidate["top1_score"],
    }


def _candidate_metrics_from_pairs(
    pairs_with_actual: Sequence[tuple[Mapping[str, Any], tuple[int, int]]],
) -> dict[str, Any]:
    """Use the existing shadow evaluator as a reproduction cross-check."""

    return evaluate_paired_cohort(
        [dict(pair) for pair, _ in pairs_with_actual],
        {str(pair.get("pair_id")): {"actual_score": _score_text(actual)} for pair, actual in pairs_with_actual},
    )


def _enrich_shadow_candidate_metrics(
    metrics: dict[str, Any],
    observations: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Add #221-only RPS/mix/rank fields to the existing shadow metrics."""

    rows = list(observations)
    if not rows:
        metrics.setdefault("one_x_two", {})["rps"] = None
        metrics.setdefault("one_x_two", {})["predicted_mix"] = {key: None for key in OUTCOMES}
        metrics.setdefault("one_x_two", {})["actual_mix"] = {key: None for key in OUTCOMES}
        metrics.setdefault("one_x_two", {})["recall"] = {key: None for key in OUTCOMES}
        metrics.setdefault("exact_score", {})["actual_score_rank"] = _quantiles([])
        metrics.setdefault("exact_score", {})["mean_actual_score_rank"] = None
        return metrics
    predicted = [max(row["probabilities"], key=row["probabilities"].get) for row in rows]
    actual = [str(row["outcome"]) for row in rows]
    predicted_counts = Counter(predicted)
    actual_counts = Counter(actual)
    correct_counts = Counter(value for value, guess in zip(actual, predicted) if value == guess)
    metrics["one_x_two"]["rps"] = statistics.fmean(float(row["one_x_two_rps"]) for row in rows)
    metrics["one_x_two"]["predicted_mix"] = {key: predicted_counts[key] / len(rows) for key in OUTCOMES}
    metrics["one_x_two"]["actual_mix"] = {key: actual_counts[key] / len(rows) for key in OUTCOMES}
    metrics["one_x_two"]["recall"] = {key: (correct_counts[key] / actual_counts[key] if actual_counts[key] else None) for key in OUTCOMES}
    ranks = [float(row["actual_score_rank"]) for row in rows if row.get("actual_score_rank") is not None]
    metrics["exact_score"]["actual_score_rank"] = _quantiles(ranks)
    metrics["exact_score"]["mean_actual_score_rank"] = statistics.fmean(ranks) if ranks else None
    return metrics


def _reliability_metric_delta(rows: Sequence[Mapping[str, Any]], field: str) -> list[float]:
    return [float(row["challenger"][field]) - float(row["champion"][field]) for row in rows]


def _percentile(values: Sequence[float], probability: float) -> float | None:
    return _quantile(values, probability)


def _bootstrap_summary(
    values: Sequence[float],
    *,
    seed: int,
    resamples: int = BOOTSTRAP_RESAMPLES,
    block_length: int | None = None,
) -> dict[str, Any]:
    values = [float(value) for value in values]
    n = len(values)
    if not n:
        return {"n": 0, "resamples": 0, "seed": seed, "ci95": [None, None], "mean_less_than_zero": None}
    rng = random.Random(seed)
    means: list[float] = []
    if block_length is None:
        for _ in range(int(resamples)):
            means.append(sum(values[rng.randrange(n)] for _ in range(n)) / n)
    else:
        length = max(2, int(block_length))
        block_count = math.ceil(n / length)
        for _ in range(int(resamples)):
            sample: list[float] = []
            for _ in range(block_count):
                start = rng.randrange(n)
                sample.extend(values[(start + offset) % n] for offset in range(length))
            means.append(sum(sample[:n]) / n)
    return {
        "n": n,
        "resamples": int(resamples),
        "seed": seed,
        "ci95": [_percentile(means, 0.025), _percentile(means, 0.975)],
        "mean_less_than_zero": sum(value < 0.0 for value in means) / len(means),
        "block_length": block_length,
    }


def iid_bootstrap_summary(values: Sequence[float], *, seed: int = IID_BOOTSTRAP_SEED, resamples: int = BOOTSTRAP_RESAMPLES) -> dict[str, Any]:
    """Fixed-seed IID unique-match bootstrap; public for focused tests."""

    return _bootstrap_summary(values, seed=seed, resamples=resamples)


def moving_block_bootstrap_summary(values: Sequence[float], *, seed: int = BLOCK_BOOTSTRAP_SEED, resamples: int = BOOTSTRAP_RESAMPLES) -> dict[str, Any]:
    """Circular moving-block bootstrap with the Issue #221 block rule."""

    block_length = max(2, round(math.sqrt(len(values)))) if values else None
    return _bootstrap_summary(values, seed=seed, resamples=resamples, block_length=block_length)


def _leave_one_out(values: Sequence[float]) -> dict[str, Any]:
    values = [float(value) for value in values]
    n = len(values)
    if n == 0:
        return {"n": 0, "full_mean": None, "max_absolute_shift": None, "max_shift_index": None, "sign_flip": None, "min_mean": None, "max_mean": None}
    full_mean = statistics.fmean(values)
    if n == 1:
        loo_means = [None]
    else:
        total = sum(values)
        loo_means = [(total - value) / (n - 1) for value in values]
    valid = [value for value in loo_means if value is not None]
    shifts = [abs(float(value) - full_mean) if value is not None else None for value in loo_means]
    max_shift = max(value for value in shifts if value is not None) if valid else None
    max_index = shifts.index(max_shift) if max_shift is not None else None
    sign = lambda value: -1 if value < 0 else 1 if value > 0 else 0
    return {
        "n": n,
        "full_mean": full_mean,
        "max_absolute_shift": max_shift,
        "max_shift_index": max_index,
        "sign_flip": any(sign(value) != sign(full_mean) for value in valid),
        "min_mean": min(valid) if valid else None,
        "max_mean": max(valid) if valid else None,
    }


def _primary_summary(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    deltas = [float(row["challenger"]["exact_nll"]) - float(row["champion"]["exact_nll"]) for row in rows]
    iid = iid_bootstrap_summary(deltas)
    block = moving_block_bootstrap_summary(deltas)
    loo = _leave_one_out(deltas)
    c_higher_p = sum(
        float(row["challenger"]["outcome_probability"]) > float(row["champion"]["outcome_probability"])
        for row in rows
    )
    return {
        "metric": "exact_nll",
        "direction": "C - Champion; lower is better",
        "n": len(deltas),
        "mean_delta": statistics.fmean(deltas) if deltas else None,
        "median_delta": statistics.median(deltas) if deltas else None,
        "iid_bootstrap_95_ci": iid,
        "moving_block_bootstrap_95_ci": block,
        "probability_mean_delta_lt_0": iid.get("mean_less_than_zero"),
        "leave_one_match_out": loo,
        "c_higher_actual_probability_count": c_higher_p,
        "c_higher_actual_probability_share": c_higher_p / len(deltas) if deltas else None,
        "actual_score_out_of_support_count": sum(row.get("exact_support_issue") is not None for row in rows),
    }


def _delta_summary(values: Sequence[float], *, seed: int) -> dict[str, Any]:
    values = [float(value) for value in values]
    boot = iid_bootstrap_summary(values, seed=seed)
    return {
        "n": len(values),
        "mean": statistics.fmean(values) if values else None,
        "median": statistics.median(values) if values else None,
        "iid_bootstrap_95_ci": boot,
    }


def _market_water_to_decimal(value: Any) -> float:
    water = _number(value)
    if water is None or water <= 0.0:
        raise MarketAuditError("INVALID_HK_WATER_DOMAIN")
    decimal = 1.0 + water
    if not math.isfinite(decimal) or decimal <= 1.0:
        raise MarketAuditError("INVALID_DECIMAL_ODDS_DOMAIN")
    return decimal


def _market_proportional_devig(values: Iterable[Any]) -> list[float]:
    decimals: list[float] = []
    for value in values:
        decimal = _number(value)
        if decimal is None or decimal <= 1.0:
            raise MarketAuditError("INVALID_DECIMAL_ODDS_DOMAIN")
        decimals.append(decimal)
    inverse = [1.0 / value for value in decimals]
    total = sum(inverse)
    if not math.isfinite(total) or total <= 0.0:
        raise MarketAuditError("INVALID_INVERSE_ODDS_SUM")
    return [value / total for value in inverse]


def _market_quote_key(row: Mapping[str, Any]) -> str:
    for key in ("cid", "source_company_id", "company_id", "name"):
        value = _text(row.get(key))
        if value:
            return value.casefold()
    return ""


def _market_valid_quarter_line(value: Any) -> float | None:
    number = _number(value)
    if number is None or number < 0.0:
        return None
    rounded = round(number * 4.0) / 4.0
    return rounded if abs(number - rounded) <= 1e-8 else None


def _market_rows(snapshot: Mapping[str, Any] | None, family: str) -> list[dict[str, Any]]:
    if not isinstance(snapshot, Mapping) or not isinstance(snapshot.get(family), Mapping):
        return []
    market = snapshot[family]
    key = "bookmakers" if family == "ouzhi" else "companies"
    rows = market.get(key)
    return [dict(row) for row in rows if isinstance(row, Mapping)] if isinstance(rows, list) else []


def _market_extract_1x2(snapshot: Mapping[str, Any] | None) -> dict[str, Any]:
    rows = _market_rows(snapshot, "ouzhi")
    valid: list[dict[str, Any]] = []
    rejected: Counter[str] = Counter()
    seen: set[str] = set()
    for row in rows:
        key = _market_quote_key(row)
        if not key:
            rejected["MISSING_BOOKMAKER_IDENTITY"] += 1
            continue
        if key in seen:
            rejected["DUPLICATE_BOOKMAKER_ROW"] += 1
            continue
        seen.add(key)
        odds_raw = row.get("spf_current")
        if not isinstance(odds_raw, Mapping):
            rejected["MISSING_CURRENT_1X2_QUOTES"] += 1
            continue
        odds = [_number(odds_raw.get(outcome)) for outcome in OUTCOMES]
        if any(value is None or value <= 1.0 for value in odds):
            rejected["INVALID_1X2_DECIMAL_ODDS_DOMAIN"] += 1
            continue
        try:
            fair = _market_proportional_devig(odds)
        except MarketAuditError as error:
            rejected[str(error)] += 1
            continue
        valid.append({"bookmaker": key, "fair": dict(zip(OUTCOMES, fair)), "odds": dict(zip(OUTCOMES, odds))})
    consensus = None
    if valid:
        consensus = {
            outcome: statistics.fmean(row["fair"][outcome] for row in valid)
            for outcome in OUTCOMES
        }
        total = sum(consensus.values())
        consensus = {outcome: consensus[outcome] / total for outcome in OUTCOMES}
    return {
        "valid": valid,
        "consensus": consensus,
        "raw_row_count": len(rows),
        "valid_bookmaker_count": len(valid),
        "rejected_reasons": dict(sorted(rejected.items())),
        "reason": None if valid else ("NO_FROZEN_1X2_QUOTE_ROWS" if not rows else "NO_VALID_1X2_QUOTE_ROWS"),
    }


def _market_extract_ou(snapshot: Mapping[str, Any] | None) -> dict[str, Any]:
    rows = _market_rows(snapshot, "daxiao")
    valid: list[dict[str, Any]] = []
    rejected: Counter[str] = Counter()
    seen: set[str] = set()
    for row in rows:
        key = _market_quote_key(row)
        if not key:
            rejected["MISSING_BOOKMAKER_IDENTITY"] += 1
            continue
        if key in seen:
            rejected["DUPLICATE_BOOKMAKER_ROW"] += 1
            continue
        seen.add(key)
        line = _market_valid_quarter_line(row.get("current_line"))
        if line is None:
            rejected["INVALID_QUARTER_LINE"] += 1
            continue
        try:
            over_decimal = _market_water_to_decimal(row.get("current_over_water"))
            under_decimal = _market_water_to_decimal(row.get("current_under_water"))
            fair = _market_proportional_devig((over_decimal, under_decimal))
        except MarketAuditError as error:
            rejected[str(error)] += 1
            continue
        valid.append({
            "bookmaker": key,
            "line": line,
            "fair_over_probability": fair[0],
            "fair_under_probability": fair[1],
        })
    return {
        "valid": valid,
        "raw_row_count": len(rows),
        "valid_bookmaker_count": len(valid),
        "rejected_reasons": dict(sorted(rejected.items())),
        "reason": None if valid else ("NO_FROZEN_DAXIAO_QUOTE_ROWS" if not rows else "NO_VALID_DAXIAO_QUOTE_ROWS"),
    }


def _market_poisson_pmf(lam: float, max_goals: int = MARKET_MAX_GOALS) -> list[float]:
    if _number(lam) is None or lam < 0.0:
        raise MarketAuditError("INVALID_POISSON_INTENSITY")
    values = [math.exp(-lam)]
    for goal in range(1, max_goals + 1):
        values.append(values[-1] * lam / goal)
    return values


def _market_independent_matrix(lambda_home: float, lambda_away: float, *, max_goals: int = MARKET_MAX_GOALS) -> tuple[dict[tuple[int, int], float], float]:
    home = _market_poisson_pmf(lambda_home, max_goals)
    away = _market_poisson_pmf(lambda_away, max_goals)
    raw = {(h, a): home[h] * away[a] for h in range(max_goals + 1) for a in range(max_goals + 1)}
    mass = sum(raw.values())
    if not math.isfinite(mass) or mass <= 0.0:
        raise MarketAuditError("SCORE_MATRIX_MASS_INVALID")
    return {score: value / mass for score, value in raw.items()}, max(0.0, 1.0 - mass)


def _market_outcome_probabilities(lambda_home: float, lambda_away: float) -> dict[str, float]:
    home = _market_poisson_pmf(lambda_home)
    away = _market_poisson_pmf(lambda_away)
    cumulative_away: list[float] = []
    running = 0.0
    for value in away:
        cumulative_away.append(running)
        running += value
    draw = sum(home[goal] * away[goal] for goal in range(min(len(home), len(away))))
    home_win = sum(home[h] * cumulative_away[h] for h in range(len(home)))
    away_win = max(0.0, 1.0 - home_win - draw)
    total = home_win + draw + away_win
    if total <= 0.0 or not math.isfinite(total):
        raise MarketAuditError("OUTCOME_PROBABILITIES_INVALID")
    return {"home": home_win / total, "draw": draw / total, "away": away_win / total}


def _market_settlement_weights(
    matrix: Mapping[tuple[int, int], float],
    line: float,
    selection: str,
) -> tuple[float, float]:
    win_weight = 0.0
    loss_weight = 0.0
    components = split_quarter_line(line)
    for score, probability in matrix.items():
        score_win = 0.0
        score_loss = 0.0
        for component in components:
            delta = score[0] + score[1] - component
            if selection == "under":
                delta = -delta
            if delta > 1e-9:
                score_win += 1.0
            elif delta < -1e-9:
                score_loss += 1.0
        win_weight += probability * score_win / len(components)
        loss_weight += probability * score_loss / len(components)
    return win_weight, loss_weight


def _market_fair_probability(matrix: Mapping[tuple[int, int], float], line: float, selection: str) -> float:
    win, loss = _market_settlement_weights(matrix, line, selection)
    denominator = win + loss
    if win <= MARKET_EPSILON or loss <= MARKET_EPSILON or denominator <= MARKET_EPSILON:
        raise MarketAuditError("SETTLEMENT_PRICE_NOT_IDENTIFIABLE")
    return win / denominator


def _market_solve_total_lambda(line: float, target_over_probability: float) -> dict[str, float]:
    target = _number(target_over_probability)
    normalized_line = _market_valid_quarter_line(line)
    if normalized_line is None or target is None or not MARKET_EPSILON < target < 1.0 - MARKET_EPSILON:
        raise MarketAuditError("OU_SOLVE_DOMAIN_INVALID")

    def model_probability(lam: float) -> float:
        matrix, _ = _market_independent_matrix(lam, 0.0)
        return _market_fair_probability(matrix, normalized_line, "over")

    lower, upper = MARKET_OU_SOLVE_LOWER, MARKET_OU_SOLVE_UPPER
    low_probability, high_probability = model_probability(lower), model_probability(upper)
    if target < low_probability - 1e-10 or target > high_probability + 1e-10:
        raise MarketAuditError("OU_SOLVE_NOT_IDENTIFIABLE")
    for _ in range(MARKET_OU_SOLVE_ITERATIONS):
        middle = (lower + upper) / 2.0
        if model_probability(middle) < target:
            lower = middle
        else:
            upper = middle
    lam = (lower + upper) / 2.0
    residual = model_probability(lam) - target
    if not math.isfinite(residual) or abs(residual) > 1e-7:
        raise MarketAuditError("OU_SOLVE_NO_CONVERGENCE")
    return {"lambda_total": lam, "target_probability": target, "model_probability": target + residual, "residual": residual}


def _market_solve_home_share(lambda_total: float, target_probabilities: Mapping[str, float]) -> dict[str, float]:
    target = {key: _number(target_probabilities.get(key)) for key in OUTCOMES}
    if any(value is None or value < 0.0 for value in target.values()):
        raise MarketAuditError("HOME_SHARE_TARGET_INVALID")
    total = sum(float(value) for value in target.values())
    if total <= 0.0:
        raise MarketAuditError("HOME_SHARE_TARGET_INVALID")
    target = {key: float(value) / total for key, value in target.items()}

    def loss(share: float) -> float:
        probabilities = _market_outcome_probabilities(lambda_total * share, lambda_total * (1.0 - share))
        return sum((probabilities[key] - target[key]) ** 2 for key in OUTCOMES)

    left, right = MARKET_SHARE_SOLVE_LOWER, MARKET_SHARE_SOLVE_UPPER
    golden = (math.sqrt(5.0) - 1.0) / 2.0
    x1 = right - golden * (right - left)
    x2 = left + golden * (right - left)
    f1, f2 = loss(x1), loss(x2)
    for _ in range(MARKET_SHARE_SOLVE_ITERATIONS):
        if f1 > f2:
            left, x1, f1 = x1, x2, f2
            x2 = left + golden * (right - left)
            f2 = loss(x2)
        else:
            right, x2, f2 = x2, x1, f1
            x1 = right - golden * (right - left)
            f1 = loss(x1)
    share = (left + right) / 2.0
    probabilities = _market_outcome_probabilities(lambda_total * share, lambda_total * (1.0 - share))
    return {
        "share": share,
        "lambda_home": lambda_total * share,
        "lambda_away": lambda_total * (1.0 - share),
        "loss": sum((probabilities[key] - target[key]) ** 2 for key in OUTCOMES),
        "iterations": MARKET_SHARE_SOLVE_ITERATIONS,
    }


def _market_projection(lambda_home: float, lambda_away: float) -> dict[str, Any]:
    matrix, tail = _market_independent_matrix(lambda_home, lambda_away)
    probabilities = _market_outcome_probabilities(lambda_home, lambda_away)
    ranked = sorted(matrix.items(), key=lambda item: (-item[1], item[0][0], item[0][1]))
    total_distribution: dict[str, float] = defaultdict(float)
    for (home, away), probability in matrix.items():
        total_distribution[str(home + away)] += probability
    btts_yes = sum(probability for (home, away), probability in matrix.items() if home > 0 and away > 0)
    over = sum(probability for (home, away), probability in matrix.items() if home + away > 2)
    return {
        "probabilities": probabilities,
        "lambda_home": lambda_home,
        "lambda_away": lambda_away,
        "lambda_total": lambda_home + lambda_away,
        "matrix": matrix,
        "score_matrix_tail_probability": tail,
        "top_scores": [
            {"score": _score_text(score), "home_goals": score[0], "away_goals": score[1], "probability": probability, "rank": rank}
            for rank, (score, probability) in enumerate(ranked[:5], start=1)
        ],
        "btts_yes": btts_yes,
        "btts_no": 1.0 - btts_yes,
        "total_over_2_5": over,
        "total_under_2_5": 1.0 - over,
        "total_distribution": dict(sorted(total_distribution.items(), key=lambda item: int(item[0]))),
    }


def _load_legal_market_snapshot(pair: Mapping[str, Any]) -> dict[str, Any]:
    ref = _text(pair.get("input_snapshot_ref"))
    if not ref:
        return {"snapshot": None, "source": None, "reason": "NO_FROZEN_INPUT_SNAPSHOT"}
    path = Path(ref)
    if not path.is_absolute():
        path = ROOT / path
    if not path.exists():
        return {"snapshot": None, "source": None, "reason": "NO_FROZEN_INPUT_SNAPSHOT"}
    try:
        document = _load_json(path)
    except (OSError, json.JSONDecodeError):
        return {"snapshot": None, "source": None, "reason": "FROZEN_INPUT_SNAPSHOT_INVALID"}
    cutoff = _parse_time(pair.get("source_cutoff"))
    kickoff = _parse_time(pair.get("kickoff_at"))
    sources = ((document.get("input") or {}).get("source_snapshots") or {}) if isinstance(document, Mapping) else {}
    if cutoff is None or kickoff is None or cutoff >= kickoff:
        return {"snapshot": None, "source": None, "reason": "UNSAFE_RECORD_CHRONOLOGY"}
    if not isinstance(sources, Mapping) or not sources:
        return {"snapshot": None, "source": None, "reason": "NO_FROZEN_SOURCE_SNAPSHOT"}
    candidates: list[tuple[datetime, str, dict[str, Any]]] = []
    later_count = 0
    timestamp_missing = 0
    for source_name in sorted(sources):
        source = sources.get(source_name)
        snapshots = source.get("snapshots") if isinstance(source, Mapping) else []
        for raw in snapshots or []:
            if not isinstance(raw, Mapping):
                continue
            captured = _parse_time(raw.get("fetched_at") or raw.get("captured_at"))
            if captured is None:
                timestamp_missing += 1
                continue
            if captured > cutoff or captured >= kickoff:
                later_count += 1
                continue
            candidates.append((captured, str(source_name), dict(raw)))
    if not candidates:
        if later_count:
            reason = "LATER_OR_CLOSING_QUOTE_BACKFILL_BLOCKED"
        elif timestamp_missing:
            reason = "FROZEN_MARKET_CAPTURE_TIMESTAMP_MISSING"
        else:
            reason = "NO_LEGAL_PREMATCH_MARKET_SNAPSHOT"
        return {"snapshot": None, "source": None, "reason": reason, "later_snapshot_count": later_count}
    captured, source_name, snapshot = max(candidates, key=lambda item: (item[0], item[1]))
    return {
        "snapshot": snapshot,
        "source": source_name,
        "captured_at": captured.isoformat(),
        "reason": None,
        "later_snapshot_count": later_count,
        "timestamp_missing_count": timestamp_missing,
        "snapshot_ref": _repo_relative(path),
    }


def _build_market_baseline(one_x2: Mapping[str, Any], ou: Mapping[str, Any]) -> dict[str, Any]:
    if one_x2.get("reason"):
        return {"status": "NOT_EVALUABLE", "reason": one_x2["reason"]}
    if ou.get("reason"):
        return {"status": "NOT_EVALUABLE", "reason": ou["reason"]}
    solved: list[dict[str, Any]] = []
    solve_reasons: Counter[str] = Counter()
    for quote in ou["valid"]:
        try:
            result = _market_solve_total_lambda(quote["line"], quote["fair_over_probability"])
        except MarketAuditError as error:
            solve_reasons[str(error)] += 1
            continue
        solved.append({**quote, **result})
    if not solved:
        return {
            "status": "NOT_EVALUABLE",
            "reason": "OU_SOLVE_FAILED_FOR_ALL_VALID_BOOKMAKERS",
            "solve_reasons": dict(sorted(solve_reasons.items())),
        }
    lambda_total = float(statistics.median(row["lambda_total"] for row in solved))
    try:
        share = _market_solve_home_share(lambda_total, one_x2["consensus"])
    except MarketAuditError as error:
        return {"status": "NOT_EVALUABLE", "reason": str(error), "solve_reasons": dict(sorted(solve_reasons.items()))}
    return {
        "status": "EVALUABLE",
        "reason": None,
        "lambda_total": lambda_total,
        "lambda_total_bookmaker_count": len(solved),
        "lambda_total_residuals": [row["residual"] for row in solved],
        "ou_solve_reasons": dict(sorted(solve_reasons.items())),
        "one_x2_bookmaker_count": one_x2["valid_bookmaker_count"],
        "one_x2_consensus": one_x2["consensus"],
        "share_solver": share,
        "projection": _market_projection(share["lambda_home"], share["lambda_away"]),
    }


def _market_observation(probabilities: Mapping[str, float], actual: tuple[int, int]) -> dict[str, Any]:
    outcome = _actual_outcome(actual)
    one_hot = {key: float(key == outcome) for key in OUTCOMES}
    return {
        "probabilities": dict(probabilities),
        "outcome": outcome,
        "accuracy": max(probabilities, key=probabilities.get) == outcome,
        "brier": sum((float(probabilities[key]) - one_hot[key]) ** 2 for key in OUTCOMES),
        "log_loss": -math.log(max(EPSILON, min(1.0 - EPSILON, float(probabilities[outcome])))),
    }


def _market_aggregate(observations: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    rows = list(observations)
    if not rows:
        return {"sample_count": 0, "accuracy": None, "brier": None, "log_loss": None, "rps": None}
    rps_values = []
    for row in rows:
        cumulative = 0.0
        observed = 0.0
        value = 0.0
        for key in OUTCOMES[:-1]:
            cumulative += float(row["probabilities"][key])
            observed += float(key == row["outcome"])
            value += (cumulative - observed) ** 2
        rps_values.append(value / 2.0)
    return {
        "sample_count": len(rows),
        "accuracy": statistics.fmean(float(row["accuracy"]) for row in rows),
        "brier": statistics.fmean(float(row["brier"]) for row in rows),
        "log_loss": statistics.fmean(float(row["log_loss"]) for row in rows),
        "rps": statistics.fmean(rps_values),
    }


def _as_market_metric_observation(observation: Mapping[str, Any]) -> dict[str, Any]:
    """Project a persisted C/Champion observation onto the Market 1X2 shape."""

    if "accuracy" in observation:
        return dict(observation)
    return {
        "probabilities": observation["probabilities"],
        "outcome": observation["outcome"],
        "accuracy": observation["one_x_two_accuracy"],
        "brier": observation["one_x_two_brier"],
        "log_loss": observation["one_x_two_log_loss"],
    }


def _build_market_control(
    rows: Sequence[Mapping[str, Any]],
    result_map: Mapping[str, Any],
) -> dict[str, Any]:
    evaluated: list[dict[str, Any]] = []
    failures: Counter[str] = Counter()
    for pair in rows:
        actual = _actual_for_pair(pair, result_map)
        if actual is None:
            failures["NO_VERIFIED_RESULT"] += 1
            continue
        selected = _load_legal_market_snapshot(pair)
        if selected.get("reason"):
            failures[str(selected["reason"])] += 1
            continue
        one_x2 = _market_extract_1x2(selected["snapshot"])
        ou = _market_extract_ou(selected["snapshot"])
        baseline = _build_market_baseline(one_x2, ou)
        if baseline.get("status") != "EVALUABLE":
            failures[str(baseline.get("reason") or "MARKET_BASELINE_NOT_EVALUABLE")] += 1
            continue
        market = _market_observation(baseline["projection"]["probabilities"], actual)
        evaluated.append({
            "pair_id": pair.get("pair_id"),
            "match_id": pair.get("match_id"),
            "snapshot_source": selected.get("source"),
            "snapshot_captured_at": selected.get("captured_at"),
            "later_snapshot_count": selected.get("later_snapshot_count", 0),
            "one_x2_raw_row_count": one_x2.get("raw_row_count"),
            "one_x2_valid_bookmaker_count": one_x2.get("valid_bookmaker_count"),
            "ou_raw_row_count": ou.get("raw_row_count"),
            "ou_valid_bookmaker_count": ou.get("valid_bookmaker_count"),
            "market": market,
            "market_projection": {
                key: baseline["projection"][key]
                for key in ("lambda_home", "lambda_away", "lambda_total", "btts_yes", "total_over_2_5", "score_matrix_tail_probability")
            },
        })
    if not evaluated:
        return {
            "status": "MARKET_CONTROL_NOT_COMPARABLE",
            "reason": ";".join(f"{key}={value}" for key, value in sorted(failures.items())) or "NO_EVALUABLE_MARKET_ROWS",
            "cohort_match_count": 0,
            "failure_counts": dict(sorted(failures.items())),
            "paired_rows": [],
        }
    evaluated_ids = {item["pair_id"] for item in evaluated}
    c_rows = [_as_market_metric_observation(row["c_observation"]) for row in rows if row.get("pair_id") in evaluated_ids]
    champion_rows = [_as_market_metric_observation(row["champion_observation"]) for row in rows if row.get("pair_id") in evaluated_ids]
    market_rows = [item["market"] for item in evaluated]
    c_brier = [float(c["brier"]) - float(m["brier"]) for c, m in zip(c_rows, market_rows)]
    c_log_loss = [float(c["log_loss"]) - float(m["log_loss"]) for c, m in zip(c_rows, market_rows)]
    brier_delta = _delta_summary(c_brier, seed=MARKET_BRIER_SEED)
    log_loss_delta = _delta_summary(c_log_loss, seed=MARKET_LOGLOSS_SEED)
    dominates = (
        brier_delta["iid_bootstrap_95_ci"]["ci95"][0] is not None
        and log_loss_delta["iid_bootstrap_95_ci"]["ci95"][0] is not None
        and brier_delta["iid_bootstrap_95_ci"]["ci95"][0] > 0.0
        and log_loss_delta["iid_bootstrap_95_ci"]["ci95"][0] > 0.0
    )
    return {
        "status": "COMPARABLE",
        "observation_unit": "unique_match_intersection",
        "cohort_match_count": len(evaluated),
        "requested_cohort_match_count": len(rows),
        "excluded_from_market_intersection": len(rows) - len(evaluated),
        "failure_counts": dict(sorted(failures.items())),
        "market_dominates_c_on_both_1x2_scores": dominates,
        "champion": _market_aggregate(champion_rows),
        "C": _market_aggregate(c_rows),
        "market": _market_aggregate(market_rows),
        "C_minus_market": {"brier": brier_delta, "log_loss": log_loss_delta},
        "contract": {
            "source": "Issue #189 accepted Market-only contract / PR #190",
            "one_x2": "same-time frozen 1X2 proportional inverse-odds de-vig; equal-weight valid-bookmaker consensus",
            "over_under": "positive HK net water to decimal 1+water; exact Asian quarter settlement; solve lambda_total per book; median",
            "split": "solve home share against frozen 1X2 consensus; rho=0; AH held out",
            "quote_cutoff": "frozen source timestamp <= pair source_cutoff and < kickoff",
            "network_calls": False,
            "outcome_conditioned_reconstruction": False,
        },
        "paired_rows": evaluated,
    }


def _slice_result(
    name: str,
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    result: dict[str, Any] = {"slice": name, "sample_count": len(rows)}
    if len(rows) < MIN_MEANINGFUL_SLICE:
        result["status"] = "INSUFFICIENT_SAMPLE"
        result["metrics"] = None
        return result
    pairs_with_actual = [
        (row["pair"], row["actual"])
        for row in rows
    ]
    evaluation = _candidate_metrics_from_pairs(pairs_with_actual)
    champion_metrics = _enrich_shadow_candidate_metrics(
        evaluation["candidates"]["champion"],
        [row["champion_observation"] for row in rows],
    )
    challenger_metrics = _enrich_shadow_candidate_metrics(
        evaluation["candidates"]["challenger"],
        [row["challenger_observation"] for row in rows],
    )
    result["status"] = "DESCRIPTIVE"
    result["metrics"] = {
        "champion": champion_metrics,
        "challenger": challenger_metrics,
    }
    result["exact_nll_C_minus_Champion"] = statistics.fmean(
        float(row["challenger_observation"]["exact_nll"]) - float(row["champion_observation"]["exact_nll"])
        for row in rows
    )
    return result


def _build_slices(rows: Sequence[Mapping[str, Any]], metadata: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    ordered = list(rows)
    slices: dict[str, list[Mapping[str, Any]]] = {}
    n = len(ordered)
    if n:
        first_end = n // 3
        second_end = 2 * n // 3
        slices["chronological_third_1"] = ordered[:first_end]
        slices["chronological_third_2"] = ordered[first_end:second_end]
        slices["chronological_third_3"] = ordered[second_end:]
    horizon_groups: dict[str, list[Mapping[str, Any]]] = {str(band["id"]): [] for band in MARKET_HORIZON_BANDS}
    horizon_groups["HORIZON_UNSAFE"] = []
    league_groups: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in ordered:
        pair_id = str(row.get("pair_id") or (row.get("pair") or {}).get("pair_id") or "")
        info = metadata.get(pair_id, {})
        horizon_groups[str(info.get("horizon_band") or "HORIZON_UNSAFE")].append(row)
        league_groups[str(info.get("league") or "<missing>")].append(row)
    for name, grouped in horizon_groups.items():
        slices[f"horizon::{name}"] = grouped
    for league, grouped in sorted(league_groups.items()):
        slices[f"competition::{league}"] = grouped
    return {name: _slice_result(name, grouped) for name, grouped in slices.items()}


def _safety_triggers(metrics: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Compatibility helper retaining the previous non-decision watch floors."""

    champion = metrics.get("champion") or {}
    challenger = metrics.get("challenger") or {}
    checks = (
        ("one_x_two_brier", "1X2 Brier", 0.10),
        ("one_x_two_log_loss", "1X2 LogLoss", 0.20),
        ("btts_brier", "BTTS Brier", 0.08),
        ("ou_2_5_brier", "O/U 2.5 Brier", 0.08),
    )
    triggers: list[dict[str, Any]] = []
    for metric, label, floor in checks:
        champion_value = _number(champion.get(metric))
        challenger_value = _number(challenger.get(metric))
        if champion_value is None or challenger_value is None:
            triggers.append({"metric": metric, "label": label, "status": "MISSING"})
        elif challenger_value - champion_value > floor:
            triggers.append({"metric": metric, "label": label, "status": "TRIGGERED", "worsening": challenger_value - champion_value, "floor": floor})
    return triggers


def _gate_statuses(
    *,
    integrity: Mapping[str, Any],
    reproduction: Mapping[str, Any],
    unique_count: int,
    minimum_unique_matches: int,
    subgroup_gate: Mapping[str, Any],
    overall_metrics: Mapping[str, Mapping[str, Any]],
    slices: Mapping[str, Any],
) -> dict[str, Any]:
    """Compatibility view for the pre-#221 unique-cohort tests."""

    overall_triggers = _safety_triggers(overall_metrics)
    exact_support: list[str] = []
    one_one_support: list[str] = []
    for name, value in slices.items():
        metrics = value.get("metrics") or {}
        champion = metrics.get("champion") or {}
        challenger = metrics.get("challenger") or {}
        if _number(challenger.get("exact_nll")) is not None and _number(champion.get("exact_nll")) is not None and challenger["exact_nll"] <= champion["exact_nll"]:
            exact_support.append(name)
        if _number(challenger.get("one_one_top1_share")) is not None and _number(champion.get("one_one_top1_share")) is not None and challenger["one_one_top1_share"] < champion["one_one_top1_share"]:
            one_one_support.append(name)
    statuses = {
        "pair_freeze_integrity": integrity["status"] == "PASS",
        "accepted_overall_unique_reproduce": reproduction["status"] == "PASS",
        "unique_match_promotion_gate": unique_count >= minimum_unique_matches,
        "meaningful_subgroup_safety": subgroup_gate["status"] == "PASS" and not overall_triggers,
        "exact_score_improvement_not_confined": len(exact_support) >= 2,
        "one_one_reduction_broad": len(one_one_support) >= 2,
        "btts_regression_bounded": not any(trigger.get("metric") == "btts_brier" for trigger in overall_triggers),
        "no_post_match_information_in_generation": integrity["status"] == "PASS",
    }
    return {
        "status": "PASS" if all(statuses.values()) else "FAIL",
        "checks": statuses,
        "overall_safety_triggers": overall_triggers,
        "exact_supporting_slices": exact_support,
        "one_one_supporting_slices": one_one_support,
        "minimum_unique_matches": minimum_unique_matches,
    }


def _decision(
    *,
    integrity_status: str,
    primary: Mapping[str, Any],
    champion: Mapping[str, Any],
    challenger: Mapping[str, Any],
    one_x_two_deltas: Mapping[str, Any],
    market_control: Mapping[str, Any],
) -> tuple[str, dict[str, Any]]:
    if integrity_status != "PASS":
        return "FAIL_CLOSED", {"reason": "integrity_or_immutable_exact_authority_failed"}
    mean_delta = _number(primary.get("mean_delta"))
    iid_ci = (primary.get("iid_bootstrap_95_ci") or {}).get("ci95") or [None, None]
    block_ci = (primary.get("moving_block_bootstrap_95_ci") or {}).get("ci95") or [None, None]
    exact_mean_negative = mean_delta is not None and mean_delta < 0.0
    exact_both_ci_upper_negative = (
        _number(iid_ci[1]) is not None and _number(block_ci[1]) is not None and iid_ci[1] < 0.0 and block_ci[1] < 0.0
    )
    loo_stable = (primary.get("leave_one_match_out") or {}).get("sign_flip") is False
    c_brier = _number((challenger.get("one_x_two") or {}).get("brier"))
    champion_brier = _number((champion.get("one_x_two") or {}).get("brier"))
    c_log = _number((challenger.get("one_x_two") or {}).get("log_loss"))
    champion_log = _number((champion.get("one_x_two") or {}).get("log_loss"))
    point_not_worse = c_brier is not None and champion_brier is not None and c_log is not None and champion_log is not None and c_brier <= champion_brier and c_log <= champion_log
    brier_ci = ((one_x_two_deltas.get("brier") or {}).get("iid_bootstrap_95_ci") or {}).get("ci95") or [None, None]
    log_ci = ((one_x_two_deltas.get("log_loss") or {}).get("iid_bootstrap_95_ci") or {}).get("ci95") or [None, None]
    no_credible_1x2_regression = not (
        (_number(brier_ci[0]) is not None and brier_ci[0] > 0.0)
        or (_number(log_ci[0]) is not None and log_ci[0] > 0.0)
    )
    exact_stable = exact_mean_negative and exact_both_ci_upper_negative and loo_stable
    one_x_two_safe = point_not_worse and no_credible_1x2_regression
    market_preferred = market_control.get("status") == "COMPARABLE" and market_control.get("market_dominates_c_on_both_1x2_scores") is True
    checks = {
        "exact_mean_delta_negative": exact_mean_negative,
        "exact_iid_ci_upper_negative": _number(iid_ci[1]) is not None and iid_ci[1] < 0.0,
        "exact_block_ci_upper_negative": _number(block_ci[1]) is not None and block_ci[1] < 0.0,
        "loo_no_sign_flip": loo_stable,
        "1x2_point_estimates_not_worse": point_not_worse,
        "1x2_no_ci_entirely_worse": no_credible_1x2_regression,
        "market_control_not_credible_both_score_dominance": not market_preferred,
    }
    if market_preferred and exact_stable and one_x_two_safe:
        return "C_SIGNAL_STABLE_BUT_MARKET_CONTROL_PREFERRED", checks
    if exact_stable and one_x_two_safe:
        return "C_PROMOTION_REVIEW_PASS", checks
    if mean_delta is not None and mean_delta >= 0.0:
        return "C_PROMOTION_REVIEW_REJECT", checks
    if point_not_worse is False or no_credible_1x2_regression is False:
        return "C_PROMOTION_REVIEW_REJECT", checks
    return "C_PROMOTION_REVIEW_INCONCLUSIVE", checks


def _build_pair_artifact_row(
    pair: Mapping[str, Any],
    actual: tuple[int, int],
    champion: Mapping[str, Any],
    challenger: Mapping[str, Any],
    *,
    metadata: Mapping[str, Any],
) -> dict[str, Any]:
    row = {
        "pair_id": pair.get("pair_id"),
        "match_id": pair.get("match_id"),
        "match_key": pair.get("match_key"),
        "kickoff_at": pair.get("kickoff_at"),
        "freeze_created_at": pair.get("freeze_created_at"),
        "source_cutoff": pair.get("source_cutoff"),
        "actual_score": _score_text(actual),
        "actual_outcome": _actual_outcome(actual),
        "result_scope": "regulation_90m_plus_stoppage",
        "horizon_band": metadata.get("horizon_band"),
        "league": metadata.get("league"),
        "champion": champion,
        "challenger": challenger,
        "deltas": {
            "exact_nll_C_minus_Champion": challenger["exact_nll"] - champion["exact_nll"],
            "actual_probability_C_minus_Champion": challenger["outcome_probability"] - champion["outcome_probability"],
            "one_x_two_brier_C_minus_Champion": challenger["one_x_two_brier"] - champion["one_x_two_brier"],
            "one_x_two_log_loss_C_minus_Champion": challenger["one_x_two_log_loss"] - champion["one_x_two_log_loss"],
        },
    }
    return row


def _json_observation(candidate: Mapping[str, Any]) -> dict[str, Any]:
    """Keep paired rows sufficient for recomputation without copying 169 cells."""

    return {
        "probabilities": candidate["probabilities"],
        "one_x_two_accuracy": candidate["one_x_two_accuracy"],
        "one_x_two_brier": candidate["one_x_two_brier"],
        "one_x_two_log_loss": candidate["one_x_two_log_loss"],
        "one_x_two_rps": candidate["one_x_two_rps"],
        "outcome_probability": candidate["outcome_probability"],
        "exact_nll": candidate["exact_nll"],
        "actual_score_rank": candidate.get("actual_score_rank"),
        "exact_top1": candidate["exact_top1"],
        "exact_top3": candidate["exact_top3"],
        "btts_probability": candidate["btts_probability"],
        "btts_actual": candidate["btts_actual"],
        "btts_brier": candidate["btts_brier"],
        "btts_log_loss": candidate["btts_log_loss"],
        "ou_2_5_probability": candidate["ou_2_5_probability"],
        "ou_2_5_actual": candidate["ou_2_5_actual"],
        "ou_2_5_brier": candidate["ou_2_5_brier"],
        "ou_2_5_log_loss": candidate["ou_2_5_log_loss"],
        "tail_probabilities": candidate["tail_probabilities"],
        "tail_actuals": candidate["tail_actuals"],
        "lambda_home": candidate["lambda_home"],
        "lambda_away": candidate["lambda_away"],
        "lambda_total": candidate["lambda_total"],
        "lambda_abs_gap": candidate["lambda_abs_gap"],
        "top1_score": candidate["top1_score"],
    }


def run_review(
    *,
    latest_path: Path = DEFAULT_LATEST,
    pair_root: Path = DEFAULT_PAIR_ROOT,
    result_root: Path = DEFAULT_RESULT_ROOT,
    universe_root: Path = DEFAULT_UNIVERSE_ROOT,
    config_path: Path | None = None,
    current_ref: str | None = None,
) -> dict[str, Any]:
    latest = _load_json(latest_path)
    if not isinstance(latest, Mapping):
        raise ValueError("latest shadow artifact must be an object")
    pairs = [dict(pair) for pair in latest.get("pairs") or [] if isinstance(pair, Mapping)]
    if _text(latest.get("candidate_id")) != CANDIDATE_ID:
        raise ValueError("latest artifact is not Challenger C")

    catalog, discovery = discover_verified_results(Path(result_root))
    result_map, matching = build_identity_safe_result_map(pairs, catalog)
    eligible = [pair for pair in pairs if _is_promotion_eligible_pair(pair)]
    selection = select_promotion_representatives(pairs, verified_results=result_map)
    result_independent_selection = select_promotion_representatives(pairs, verified_results={})
    current_verified = list(selection["verified_representatives"])
    current_verified_ids = {_text(pair.get("pair_id")) for pair in current_verified}
    stored_ids = {
        _text(item)
        for item in (((latest.get("evaluation") or {}).get("representative_selector") or {}).get("verified_representative_pair_ids") or [])
        if _text(item)
    }
    reference_ids = stored_ids
    reference_rows = [pair for pair in current_verified if _text(pair.get("pair_id")) in reference_ids]
    growth_rows = [pair for pair in current_verified if _text(pair.get("pair_id")) not in reference_ids]
    reference_rows.sort(key=lambda pair: (_parse_time(pair.get("kickoff_at")) or datetime.min.replace(tzinfo=timezone.utc), _text(pair.get("match_id"))))
    growth_rows.sort(key=lambda pair: (_parse_time(pair.get("kickoff_at")) or datetime.min.replace(tzinfo=timezone.utc), _text(pair.get("match_id"))))

    universe_map, universe_conflicts = _load_universe_index(Path(universe_root))
    metadata = {
        _text(pair.get("pair_id")): _pair_metadata(pair, universe_map)
        for pair in current_verified
    }
    pair_file_audit = _pair_file_audit(eligible, Path(pair_root))
    integrity_failures: list[str] = []
    for pair in eligible:
        integrity_failures.extend(_pair_integrity_issues(pair))
    if discovery.get("result_identity_conflicts", 0):
        integrity_failures.append("result_identity_conflicts")
    if matching.get("result_identity_mismatches", 0):
        integrity_failures.append("result_identity_mismatches")
    if universe_conflicts:
        integrity_failures.extend(f"universe_identity_conflict:{key}" for key in universe_conflicts)
    if pair_file_audit["status"] != "PASS":
        integrity_failures.extend(f"pair_file:{item.get('pair_id')}:{item.get('reason')}" for item in pair_file_audit["failures"])
    if len(stored_ids) != ROUTE_REFERENCE_UNIQUE_MATCHES:
        integrity_failures.append("stored_route_reference_count_not_109")
    if len(reference_rows) != ROUTE_REFERENCE_UNIQUE_MATCHES:
        integrity_failures.append("current_reference_intersection_not_109")
    if stored_ids - current_verified_ids:
        integrity_failures.append("stored_route_reference_not_present_in_current_selection")
    if len({str(pair.get("match_id")) for pair in reference_rows}) != len(reference_rows):
        integrity_failures.append("duplicate_reference_match_identity")
    if selection["counts"].get("ambiguous_final_chronology_match_groups", 0):
        integrity_failures.append("ambiguous_final_chronology")
    selected_ids = [_text(pair.get("pair_id")) for pair in selection["selected_representatives"]]
    independent_ids = [_text(pair.get("pair_id")) for pair in result_independent_selection["selected_representatives"]]
    if selected_ids != independent_ids:
        integrity_failures.append("result_affected_version_selection")

    pair_rows: list[dict[str, Any]] = []
    authority_failures: list[str] = []
    for pair in reference_rows:
        actual = _actual_for_pair(pair, result_map)
        if actual is None:
            authority_failures.append(f"{_text(pair.get('pair_id'))}:RESULT_MISSING")
            continue
        champion, champion_issues = _validate_candidate_output(pair, actual, "champion")
        challenger, challenger_issues = _validate_candidate_output(pair, actual, "challenger")
        authority_failures.extend(champion_issues + challenger_issues)
        if champion is None or challenger is None:
            continue
        champion_observation = _candidate_observation(champion, actual)
        challenger_observation = _candidate_observation(challenger, actual)
        champion_observation["one_x_two_accuracy"] = champion_observation["probabilities"] and max(champion_observation["probabilities"], key=champion_observation["probabilities"].get) == champion_observation["outcome"]
        challenger_observation["one_x_two_accuracy"] = max(challenger_observation["probabilities"], key=challenger_observation["probabilities"].get) == challenger_observation["outcome"]
        for observation in (champion_observation, challenger_observation):
            one_hot = {key: float(key == observation["outcome"]) for key in OUTCOMES}
            observation["one_x_two_brier"] = sum((observation["probabilities"][key] - one_hot[key]) ** 2 for key in OUTCOMES)
            observation["one_x_two_log_loss"] = -math.log(max(EPSILON, min(1.0 - EPSILON, observation["probabilities"][observation["outcome"]])))
            predicted, observed, rps = 0.0, 0.0, 0.0
            for key in OUTCOMES[:-1]:
                predicted += observation["probabilities"][key]
                observed += one_hot[key]
                rps += (predicted - observed) ** 2
            observation["one_x_two_rps"] = rps / 2.0
        pair_rows.append({
            "pair": pair,
            "actual": actual,
            "metadata": metadata.get(_text(pair.get("pair_id")), {}),
            "champion_observation": champion_observation,
            "challenger_observation": challenger_observation,
        })
    if authority_failures:
        integrity_failures.extend(f"immutable_exact:{failure}" for failure in authority_failures)

    if len(pair_rows) != ROUTE_REFERENCE_UNIQUE_MATCHES:
        integrity_failures.append("immutable_exact_reference_rows_not_109")
    champion_observations = [item["champion_observation"] for item in pair_rows]
    challenger_observations = [item["challenger_observation"] for item in pair_rows]
    representative_pairs_with_actual = [
        (item["pair"], item["actual"])
        for item in pair_rows
    ]
    shadow_reference_evaluation = _candidate_metrics_from_pairs(representative_pairs_with_actual)
    champion_metrics = _enrich_shadow_candidate_metrics(
        shadow_reference_evaluation["candidates"]["champion"],
        champion_observations,
    )
    challenger_metrics = _enrich_shadow_candidate_metrics(
        shadow_reference_evaluation["candidates"]["challenger"],
        challenger_observations,
    )
    artifact_rows: list[dict[str, Any]] = []
    for item in pair_rows:
        artifact_rows.append(_build_pair_artifact_row(
            item["pair"],
            item["actual"],
            _json_observation(item["champion_observation"]),
            _json_observation(item["challenger_observation"]),
            metadata=item["metadata"],
        ))
    # The primary helper consumes the exact same paired values from the
    # in-memory authority-checked observations, not the serialized artifact.
    primary_rows_for_stats = [
        {"champion": item["champion_observation"], "challenger": item["challenger_observation"], "pair_id": item["pair"].get("pair_id")}
        for item in pair_rows
    ]
    primary = _primary_summary(primary_rows_for_stats)
    one_x_two_deltas = {
        "brier": _delta_summary(_reliability_metric_delta(primary_rows_for_stats, "one_x_two_brier"), seed=IID_BOOTSTRAP_SEED + 10),
        "log_loss": _delta_summary(_reliability_metric_delta(primary_rows_for_stats, "one_x_two_log_loss"), seed=IID_BOOTSTRAP_SEED + 11),
    }
    one_x_two_comparison = {
        "champion": {"accuracy": champion_metrics["one_x_two"]["accuracy"], "brier": champion_metrics["one_x_two"]["brier"], "log_loss": champion_metrics["one_x_two"]["log_loss"], "rps": champion_metrics["one_x_two"]["rps"], "ece": champion_metrics["one_x_two"]["ece"]},
        "C": {"accuracy": challenger_metrics["one_x_two"]["accuracy"], "brier": challenger_metrics["one_x_two"]["brier"], "log_loss": challenger_metrics["one_x_two"]["log_loss"], "rps": challenger_metrics["one_x_two"]["rps"], "ece": challenger_metrics["one_x_two"]["ece"]},
        "C_minus_Champion": {
            "accuracy": challenger_metrics["one_x_two"]["accuracy"] - champion_metrics["one_x_two"]["accuracy"],
            "brier": challenger_metrics["one_x_two"]["brier"] - champion_metrics["one_x_two"]["brier"],
            "log_loss": challenger_metrics["one_x_two"]["log_loss"] - champion_metrics["one_x_two"]["log_loss"],
            "rps": challenger_metrics["one_x_two"]["rps"] - champion_metrics["one_x_two"]["rps"],
            "ece": challenger_metrics["one_x_two"]["ece"] - champion_metrics["one_x_two"]["ece"],
        },
        "paired_bootstrap": one_x_two_deltas,
    }
    overall_reproduction = _metric_projection_matches(
        compact_evaluation({"candidates": {"champion": champion_metrics, "challenger": challenger_metrics}}),
        compact_evaluation(latest.get("evaluation") or {}),
    )
    shadow_reproduction = _metric_projection_matches(
        compact_evaluation(shadow_reference_evaluation),
        compact_evaluation({"candidates": {"champion": champion_metrics, "challenger": challenger_metrics}}),
    )
    route_reference_evaluation = latest.get("evaluation") or {}
    route_reference_metrics = compact_evaluation(route_reference_evaluation)
    current_shadow_evaluation = evaluate_paired_cohort(pairs, result_map)
    current_shadow_metrics = compact_evaluation(current_shadow_evaluation)

    natural_growth_artifact: list[dict[str, Any]] = []
    for pair in growth_rows:
        actual = _actual_for_pair(pair, result_map)
        if actual is None:
            continue
        c, c_issues = _validate_candidate_output(pair, actual, "champion")
        challenger, challenger_issues = _validate_candidate_output(pair, actual, "challenger")
        if c_issues or challenger_issues or c is None or challenger is None:
            integrity_failures.extend(f"natural_growth:{failure}" for failure in c_issues + challenger_issues)
            continue
        natural_growth_artifact.append({
            "pair_id": pair.get("pair_id"),
            "match_id": pair.get("match_id"),
            "actual_score": _score_text(actual),
            "kickoff_at": pair.get("kickoff_at"),
            "included_in_formal_review": False,
            "reason": "natural_growth_after_109_route_selection_snapshot",
            "C_exact_nll": -math.log(max(EPSILON, c["actual_probability"])),
            "Champion_exact_nll": -math.log(max(EPSILON, challenger["actual_probability"])),
        })

    market_input_rows = [
        {
            "pair_id": item["pair"].get("pair_id"),
            "match_id": item["pair"].get("match_id"),
            "match_key": item["pair"].get("match_key"),
            "kickoff_at": item["pair"].get("kickoff_at"),
            "source_cutoff": item["pair"].get("source_cutoff"),
            "freeze_created_at": item["pair"].get("freeze_created_at"),
            "input_snapshot_ref": item["pair"].get("input_snapshot_ref"),
            "champion_observation": item["champion_observation"],
            "c_observation": item["challenger_observation"],
        }
        for item in pair_rows
    ]
    market_control = _build_market_control(market_input_rows, result_map)
    slices = _build_slices(pair_rows, metadata)
    integrity_status = "PASS" if not integrity_failures else "FAIL_CLOSED"
    decision, decision_checks = _decision(
        integrity_status=integrity_status,
        primary=primary,
        champion=champion_metrics,
        challenger=challenger_metrics,
        one_x_two_deltas=one_x_two_deltas,
        market_control=market_control,
    )
    evidence = {
        "schema_version": REVIEW_SCHEMA_VERSION,
        "milestone": REVIEW_ID,
        "review_id": REVIEW_ID,
        "reviewed_at": datetime.now(timezone.utc).isoformat(),
        "current_ref": current_ref,
        "decision": decision,
        "decision_checks": decision_checks,
        "automatic_promotion": False,
        "promotion_attempted": False,
        "production_action": "STOPPED_BEFORE_PROMOTION",
        "authority": AUTHORITY,
        "source": {
            "latest": _repo_relative(Path(latest_path)),
            "pair_root": _repo_relative(Path(pair_root)),
            "result_root": _repo_relative(Path(result_root)),
            "universe_root": _repo_relative(Path(universe_root)),
            "new_matches_fetched": False,
            "network_calls": False,
            "replay_or_backfill": False,
        },
        "cohort": {
            "observation_unit": "unique football match",
            "formal_route_reference_unique_matches": ROUTE_REFERENCE_UNIQUE_MATCHES,
            "verified_unique_matches": len(reference_rows),
            "formal_review_pair_ids": [_text(pair.get("pair_id")) for pair in reference_rows],
            "natural_growth_unique_matches": len(growth_rows),
            "natural_growth_pair_ids": [_text(pair.get("pair_id")) for pair in growth_rows],
            "natural_growth_included_in_decision": False,
            "selection": "prematch_versioning.select_latest_legal_prematch",
            "selection_version": selection.get("selector_version"),
            "selection_result_independence": {
                "status": "PASS" if selected_ids == independent_ids else "FAIL",
                "with_result_selected_pair_ids_sha256": hashlib.sha256("\n".join(selected_ids).encode()).hexdigest(),
                "without_result_selected_pair_ids_sha256": hashlib.sha256("\n".join(independent_ids).encode()).hexdigest(),
            },
        },
        "counts": {
            "pair_version_rows": len(pairs),
            "promotion_eligible_pair_version_rows": len(eligible),
            "verified_pair_version_rows_current": selection["counts"].get("verified_pair_version_rows"),
            "promotion_eligible_unique_matches": selection["counts"].get("promotion_eligible_unique_matches"),
            "verified_unique_matches_current": len(current_verified),
            "verified_unique_matches_formal_review": len(reference_rows),
            "version_history_match_groups_current": selection["counts"].get("version_history_match_groups"),
            "extra_verified_version_rows_current": selection["counts"].get("extra_version_rows"),
            "unmatched_eligible_pair_rows": len(eligible) - selection["counts"].get("verified_pair_version_rows", 0),
        },
        "discovery": discovery,
        "matching": matching,
        "pair_file_audit": pair_file_audit,
        "immutable_exact_authority": {
            "status": "PASS" if not authority_failures else "FAIL_CLOSED",
            "representation": "persisted candidate-time explicit 0..12 x 0..12 finite normalized 169-cell grid",
            "score_space": "home_goals, away_goals; no tail bucket in C/Champion persisted representation",
            "candidate_time_pair_digest_verified": pair_file_audit["status"] == "PASS",
            "model_replay_called": False,
            "result_used_for_version_selection_or_generation": False,
            "formal_review_rows": len(pair_rows),
            "actual_score_legitimate_probability_count": len(pair_rows) - sum("ACTUAL_SCORE_OUT_OF_SUPPORT" in failure for failure in authority_failures),
            "actual_score_out_of_support_or_missing_count": sum("ACTUAL_SCORE_OUT_OF_SUPPORT" in failure or "RESULT_MISSING" in failure for failure in authority_failures),
            "failures": authority_failures,
        },
        "integrity": {
            "status": integrity_status,
            "failures": integrity_failures,
            "eligible_pair_integrity_checked": len(eligible),
            "result_identity_conflicts": discovery.get("result_identity_conflicts", 0),
            "result_identity_mismatches": matching.get("result_identity_mismatches", 0),
            "universe_identity_conflicts": universe_conflicts,
            "post_match_generation_flags": sum(pair.get("post_match_input_used_for_generation") is not False for pair in eligible),
            "result_leakage_checked": True,
        },
        "overall": {
            "metric_unit": "unique_match",
            "champion": champion_metrics,
            "C": challenger_metrics,
            "challenger": challenger_metrics,
            "route_reference_stored_point_estimates": route_reference_metrics,
            "current_shadow_point_estimates_including_natural_growth": current_shadow_metrics,
            "shadow_reference_reproduction": shadow_reproduction,
            "overall_reproduction_against_109_authority": overall_reproduction,
        },
        "primary_exact_nll": primary,
        "one_x_two_C_vs_champion": one_x_two_comparison,
        "market_control": market_control,
        "slices": slices,
        "paired_rows": artifact_rows,
        "natural_growth": {
            "verified_unique_matches_after_route_reference": len(growth_rows),
            "included_in_formal_review": False,
            "rows": natural_growth_artifact,
        },
        "forbidden_actions_not_taken": [
            "Champion/C/Market parameter changes",
            "weight/rho/calibration/selector tuning",
            "anti-1-1 or diversity patch",
            "replay/backfill",
            "new data source",
            "serving/UI change",
            "automatic promotion",
        ],
    }
    return evidence


def _format_number(value: Any, digits: int = 9) -> str:
    number = _number(value)
    return "NA" if number is None else f"{number:.{digits}f}"


def render_report(evidence: Mapping[str, Any]) -> str:
    primary = evidence["primary_exact_nll"]
    one_x_two = evidence["one_x_two_C_vs_champion"]
    market = evidence["market_control"]
    lines = [
        f"# {REVIEW_ID}",
        "",
        f"Decision: **`{evidence['decision']}`**",
        f"Integrity: **`{evidence['integrity']['status']}`**",
        "",
        "## Scope and stop state",
        "",
        f"- Formal observation unit: `{evidence['cohort']['observation_unit']}`.",
        f"- Formal route-reference sample: `{evidence['cohort']['verified_unique_matches']}` unique matches.",
        f"- Natural growth after the 109-match route snapshot: `{evidence['cohort']['natural_growth_unique_matches']}`; included in decision: `False`.",
        "- Read-only statistics only. Champion, C, Market parameters, selector, serving, UI, and frozen history were not changed.",
        "- Automatic promotion, replay, backfill, provider/network access, and new data-source access were not attempted.",
        "",
        "## Authority and immutable Exact proof",
        "",
        f"- Memory-Hub authority: [{evidence['authority']['path']}]({evidence['authority']['url']}) (blob SHA `{evidence['authority']['sha256']}`).",
        f"- Persisted pair-file/digest audit: `{evidence['pair_file_audit']['status']}`; checked `{evidence['pair_file_audit']['checked']}` promotion-eligible version rows.",
        f"- C/Champion representation: `{evidence['immutable_exact_authority']['representation']}`.",
        f"- Formal actual-score support: `{evidence['immutable_exact_authority']['actual_score_legitimate_probability_count']}/{evidence['immutable_exact_authority']['formal_review_rows']}`; out-of-support/missing: `{evidence['immutable_exact_authority']['actual_score_out_of_support_or_missing_count']}`.",
        f"- Result affected selection/generation: `{evidence['cohort']['selection_result_independence']['status']}` / `False`.",
        "",
        "## Primary Exact endpoint",
        "",
        "C - Champion; lower NLL is better. IID bootstrap is 10,000 resamples with the fixed seed; moving-block bootstrap is circular, chronological, fixed block length max(2, round(sqrt(n))).",
        "",
        f"- Champion Exact NLL: `{_format_number(evidence['overall']['champion']['exact_score']['nll'])}`.",
        f"- C Exact NLL: `{_format_number(evidence['overall']['C']['exact_score']['nll'])}`.",
        f"- Mean delta: `{_format_number(primary['mean_delta'])}`; median delta: `{_format_number(primary['median_delta'])}`.",
        f"- IID 95% CI: `{json.dumps(primary['iid_bootstrap_95_ci']['ci95'])}`; block 95% CI: `{json.dumps(primary['moving_block_bootstrap_95_ci']['ci95'])}`.",
        f"- P(mean delta < 0): `{_format_number(primary['probability_mean_delta_lt_0'])}`.",
        f"- LOO max absolute shift: `{_format_number(primary['leave_one_match_out']['max_absolute_shift'])}`; sign flip: `{primary['leave_one_match_out']['sign_flip']}`.",
        f"- C assigned higher actual-score probability in `{primary['c_higher_actual_probability_count']}/{primary['n']}` matches (`{_format_number(primary['c_higher_actual_probability_share'])}`).",
        "",
        "| Candidate | n | Exact Top1 | Exact Top3 | Exact NLL | Mean p(actual) | 1X2 Acc | 1X2 Brier | 1X2 LogLoss | 1X2 RPS | BTTS Brier | O/U 2.5 Brier | 1-1 Top1 | Median |λH-λA| |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for label, candidate in (("Champion", evidence["overall"]["champion"]), ("C", evidence["overall"]["C"])):
        lines.append(
            f"| {label} | {candidate['sample_count']} | {_format_number(candidate['exact_score']['top1_hit_rate'])} | {_format_number(candidate['exact_score']['top3_hit_rate'])} | {_format_number(candidate['exact_score']['nll'])} | {_format_number(candidate['exact_score']['mean_probability_assigned_to_actual_score'])} | {_format_number(candidate['one_x_two']['accuracy'])} | {_format_number(candidate['one_x_two']['brier'])} | {_format_number(candidate['one_x_two']['log_loss'])} | {_format_number(candidate['one_x_two']['rps'])} | {_format_number(candidate['btts']['brier'])} | {_format_number(candidate['ou_2_5']['brier'])} | {_format_number(candidate['distribution']['one_one_top1_share'])} | {_format_number(candidate['lambda']['median_abs_gap'])} |"
        )
    lines.extend([
        "",
        "## 1X2 and Market control",
        "",
        f"- C vs Champion accuracy delta: `{_format_number(one_x_two['C_minus_Champion']['accuracy'])}`; Brier delta: `{_format_number(one_x_two['C_minus_Champion']['brier'])}`; LogLoss delta: `{_format_number(one_x_two['C_minus_Champion']['log_loss'])}`; RPS delta: `{_format_number(one_x_two['C_minus_Champion']['rps'])}`.",
        f"- Market control: `{market['status']}` on `{market.get('cohort_match_count', 0)}` identical frozen-input unique matches.",
        f"- Market control C-minus-Market Brier mean/CI: `{_format_number(((market.get('C_minus_market') or {}).get('brier') or {}).get('mean'))}` / `{json.dumps((((market.get('C_minus_market') or {}).get('brier') or {}).get('iid_bootstrap_95_ci') or {}).get('ci95'))}`.",
        f"- Market control C-minus-Market LogLoss mean/CI: `{_format_number(((market.get('C_minus_market') or {}).get('log_loss') or {}).get('mean'))}` / `{json.dumps((((market.get('C_minus_market') or {}).get('log_loss') or {}).get('iid_bootstrap_95_ci') or {}).get('ci95'))}`.",
        f"- Credible Market dominance on both 1X2 scores: `{market.get('market_dominates_c_on_both_1x2_scores')}`.",
        "- Contract: same-time frozen 1X2 proportional inverse-odds de-vig/equal-bookmaker consensus; positive HK water to decimal; exact quarter-line settlement; per-book total-intensity solve with median; home-share solve; rho=0; AH held out; no closing quote or outcome-conditioned reconstruction.",
        "",
        "## Slices",
        "",
        "Slices are descriptive only. Every slice below with n < 10 is explicitly `INSUFFICIENT_SAMPLE`; no slice tunes or changes a formula.",
        "",
        "| Slice | n | Status | C - Champion Exact NLL |",
        "|---|---:|---|---:|",
    ])
    for name, value in evidence["slices"].items():
        lines.append(f"| {name} | {value['sample_count']} | {value['status']} | {_format_number(value.get('exact_nll_C_minus_Champion'))} |")
    lines.extend([
        "",
        "## Required paired artifact and final decision",
        "",
        f"- `summary.json` contains `{len(evidence['paired_rows'])}` formal paired rows sufficient to recompute the primary delta, both bootstrap inputs, LOO, 1X2 deltas, and secondary metrics.",
        f"- Decision checks: `{json.dumps(evidence['decision_checks'], ensure_ascii=False, sort_keys=True)}`.",
        f"- Final decision: **`{evidence['decision']}`**.",
        "- STOP: research-only evidence; no merge and no automatic promotion.",
        "",
    ])
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latest", type=Path, default=DEFAULT_LATEST)
    parser.add_argument("--pair-root", type=Path, default=DEFAULT_PAIR_ROOT)
    parser.add_argument("--result-root", type=Path, default=DEFAULT_RESULT_ROOT)
    parser.add_argument("--universe-root", type=Path, default=DEFAULT_UNIVERSE_ROOT)
    parser.add_argument("--current-ref", default=None)
    parser.add_argument("--write", action="store_true", help="write research-only summary.json and report.md")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args(argv)
    evidence = run_review(
        latest_path=args.latest,
        pair_root=args.pair_root,
        result_root=args.result_root,
        universe_root=args.universe_root,
        current_ref=args.current_ref,
    )
    if args.write:
        _write_json(args.output, evidence)
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(render_report(evidence), encoding="utf-8")
    print(json.dumps({
        "milestone": evidence["milestone"],
        "decision": evidence["decision"],
        "integrity": evidence["integrity"]["status"],
        "verified_unique_matches": evidence["cohort"]["verified_unique_matches"],
        "natural_growth_unique_matches": evidence["cohort"]["natural_growth_unique_matches"],
        "written": bool(args.write),
    }, ensure_ascii=False, sort_keys=True))
    return 0 if evidence["integrity"]["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
