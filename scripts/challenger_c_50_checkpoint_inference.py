#!/usr/bin/env python3
"""Run the preregistered, read-only inference audit for Challenger C's 50-match checkpoint."""

from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import random
import sys
from statistics import fmean, median
from typing import Any, Iterable, Mapping


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from market_side_shadow import (  # noqa: E402
    EPSILON,
    _actual_for_pair,
    _actual_outcome,
    _distribution_from_output,
    _number,
    evaluate_paired_cohort,
    select_promotion_representatives,
)
from market_side_shadow_refresh import (  # noqa: E402
    build_identity_safe_result_map,
    discover_verified_results,
)
from postmatch_queue import parse_datetime  # noqa: E402


MILESTONE = "CHALLENGER-C-50-CHECKPOINT-INFERENCE-1"
SCHEMA_VERSION = "challenger_c_50_checkpoint_inference_1.v1"
MIN_COMPETITION_SLICE = 10
BOOTSTRAP_RESAMPLES = 10_000
IID_BOOTSTRAP_SEED = 176_5001
BLOCK_BOOTSTRAP_SEED = 176_5002
ACCEPTED_PR175_BASELINE = {
    "eligible_unique_matches": 74,
    "verified_unique_matches": 56,
    "unmatched_unique_matches": 18,
}
ACCEPTED_PR175_REFERENCE = {
    "pr": 175,
    "merge_sha": "3af2656ffcb50386bd37b829876a3dd93acea535",
    "accepted_head": "e90fd09156e3d8d6a832b301c07aff64f0158fa7",
    "actions_run": "33832831273",
    "artifact": "9922289688",
    **ACCEPTED_PR175_BASELINE,
}
OUTCOMES = ("home", "draw", "away")
class AuditError(RuntimeError):
    """Raised when the paired inference reconstruction cannot be trusted."""


def _required_time(value: Any, label: str) -> datetime:
    parsed = parse_datetime(value)
    if parsed is None:
        raise AuditError(f"{label} is missing or invalid: {value!r}")
    return parsed.astimezone(timezone.utc)


def _snapshot_time(value: Any | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    return _required_time(value, "snapshot_at")


def _bounded_probability(value: Any, label: str) -> float:
    number = _number(value)
    if number is None or number < 0.0 or number > 1.0:
        raise AuditError(f"{label} is not a probability: {value!r}")
    return float(number)


def _binary_log_loss(probability: float, observed: bool) -> float:
    likelihood = probability if observed else 1.0 - probability
    return -math.log(max(EPSILON, min(1.0 - EPSILON, likelihood)))


def _score_nll(probability: float) -> float:
    return -math.log(max(EPSILON, probability))


def _candidate_observation(output: Mapping[str, Any], actual: tuple[int, int]) -> dict[str, Any]:
    if not isinstance(output, Mapping):
        raise AuditError("paired row is missing a candidate output")
    actual_text = f"{actual[0]}-{actual[1]}"
    actual_outcome = _actual_outcome(actual)
    distribution = _distribution_from_output(output)
    actual_probability = _number(distribution.get(actual))
    if actual_probability is None or actual_probability < 0.0 or actual_probability > 1.0:
        raise AuditError(f"candidate output has no valid actual-score probability: {actual_text}")

    raw_probabilities = output.get("probabilities")
    if not isinstance(raw_probabilities, Mapping):
        raise AuditError("candidate output has no 1X2 probability mapping")
    probabilities = {
        outcome: _bounded_probability(raw_probabilities.get(outcome, 0.0), f"1X2 {outcome}")
        for outcome in OUTCOMES
    }
    one_x_two_brier = sum(
        (probabilities[outcome] - float(outcome == actual_outcome)) ** 2
        for outcome in OUTCOMES
    )
    one_x_two_log_loss = _binary_log_loss(probabilities[actual_outcome], True)

    btts_probability = _bounded_probability(output.get("btts_probability"), "BTTS probability")
    btts_actual = actual[0] > 0 and actual[1] > 0
    ou_probability = _bounded_probability(output.get("ou_2_5_probability"), "O/U 2.5 probability")
    ou_actual = actual[0] + actual[1] >= 3
    top1 = str(output.get("score_top1") or "")
    top3 = [str(value) for value in output.get("score_top3") or []]
    return {
        "actual_score_probability": float(actual_probability),
        "exact_nll": _score_nll(float(actual_probability)),
        "exact_top1_hit": top1 == actual_text,
        "exact_top3_hit": actual_text in top3,
        "one_x_two_probabilities": probabilities,
        "one_x_two_brier": one_x_two_brier,
        "one_x_two_log_loss": one_x_two_log_loss,
        "btts_probability": btts_probability,
        "btts_actual": btts_actual,
        "btts_brier": (btts_probability - float(btts_actual)) ** 2,
        "btts_log_loss": _binary_log_loss(btts_probability, btts_actual),
        "ou_2_5_probability": ou_probability,
        "ou_2_5_actual": ou_actual,
        "ou_2_5_brier": (ou_probability - float(ou_actual)) ** 2,
        "ou_2_5_log_loss": _binary_log_loss(ou_probability, ou_actual),
    }


def _paired_row(pair: Mapping[str, Any], actual: tuple[int, int]) -> dict[str, Any]:
    champion = _candidate_observation(pair.get("champion"), actual)
    challenger = _candidate_observation(pair.get("challenger"), actual)
    deltas = {
        "delta_nll": challenger["exact_nll"] - champion["exact_nll"],
        "delta_actual_score_probability": (
            challenger["actual_score_probability"] - champion["actual_score_probability"]
        ),
        "delta_exact_top1": int(challenger["exact_top1_hit"]) - int(champion["exact_top1_hit"]),
        "delta_exact_top3": int(challenger["exact_top3_hit"]) - int(champion["exact_top3_hit"]),
        "delta_one_x_two_brier": challenger["one_x_two_brier"] - champion["one_x_two_brier"],
        "delta_one_x_two_log_loss": challenger["one_x_two_log_loss"] - champion["one_x_two_log_loss"],
        "delta_btts_brier": challenger["btts_brier"] - champion["btts_brier"],
        "delta_btts_log_loss": challenger["btts_log_loss"] - champion["btts_log_loss"],
        "delta_ou_2_5_brier": challenger["ou_2_5_brier"] - champion["ou_2_5_brier"],
        "delta_ou_2_5_log_loss": challenger["ou_2_5_log_loss"] - champion["ou_2_5_log_loss"],
    }
    return {
        "pair_id": str(pair.get("pair_id") or ""),
        "match_id": str(pair.get("match_id") or ""),
        "match_key": str(pair.get("match_key") or ""),
        "kickoff_at": pair.get("kickoff_at"),
        "actual_score": f"{actual[0]}-{actual[1]}",
        "actual_outcome": _actual_outcome(actual),
        "champion": champion,
        "challenger": challenger,
        "deltas": deltas,
        # Keep the primary input flat as well as nested so the artifact can be
        # recomputed by simple row-oriented tooling.
        "delta_nll": deltas["delta_nll"],
    }


def _cohort_sort_key(row: Mapping[str, Any]) -> tuple[datetime, str, str]:
    return (
        _required_time(row.get("kickoff_at"), "selected representative kickoff"),
        str(row.get("match_id") or ""),
        str(row.get("pair_id") or ""),
    )


def build_audit_cohort(
    pairs: Iterable[Mapping[str, Any]],
    result_map: Mapping[str, Any],
    *,
    snapshot_at: Any | None = None,
) -> dict[str, Any]:
    """Select legal representatives and construct one paired row per verified match."""

    pair_list = [dict(pair) for pair in pairs]
    snapshot = _snapshot_time(snapshot_at)
    selection = select_promotion_representatives(pair_list, result_map)
    if selection["counts"]["ambiguous_final_chronology_match_groups"]:
        raise AuditError("ambiguous final chronology in the legal cohort")

    selected = sorted(selection["selected_representatives"], key=_cohort_sort_key)
    cohort_rows: list[dict[str, Any]] = []
    paired_rows: list[dict[str, Any]] = []
    for pair in selected:
        actual = _actual_for_pair(pair, result_map)
        keys = (
            str(pair.get("pair_id") or ""),
            str(pair.get("match_id") or ""),
        )
        result_map_linked = any(key and key in result_map for key in keys)
        if actual is None and result_map_linked:
            raise AuditError(f"identity-linked result is not consumable: {pair.get('match_key')}")
        if actual is None:
            kickoff = _required_time(pair.get("kickoff_at"), "unmatched kickoff")
            reason = "FUTURE_NOT_DUE" if kickoff > snapshot else "PAST_RESULT_MISSING"
            cohort_rows.append({
                "pair_id": str(pair.get("pair_id") or ""),
                "match_id": str(pair.get("match_id") or ""),
                "match_key": str(pair.get("match_key") or ""),
                "kickoff_at": pair.get("kickoff_at"),
                "status": "UNMATCHED",
                "reason": reason,
                "result_map_linked": result_map_linked,
            })
            continue
        row = _paired_row(pair, actual)
        row["result_map_linked"] = result_map_linked
        row["status"] = "VERIFIED"
        paired_rows.append(row)
        cohort_rows.append({
            "pair_id": row["pair_id"],
            "match_id": row["match_id"],
            "match_key": row["match_key"],
            "kickoff_at": row["kickoff_at"],
            "status": "VERIFIED",
            "reason": "RESULT_PRESENT",
            "result_map_linked": result_map_linked,
        })
    return {
        "snapshot_at": snapshot.isoformat(),
        "selection": selection,
        "cohort_rows": cohort_rows,
        "paired_rows": paired_rows,
    }


def _round(value: float | None) -> float | None:
    return round(float(value), 9) if value is not None else None


def _direction(mean_delta: float | None) -> str | None:
    if mean_delta is None:
        return None
    if mean_delta < 0:
        return "C_FAVORED"
    if mean_delta > 0:
        return "CHAMPION_FAVORED"
    return "TIE"


def _endpoint_summary(rows: Iterable[Mapping[str, Any]], key: str, *, loss: bool) -> dict[str, Any]:
    values = [float(row["deltas"][key]) for row in rows]
    if not values:
        return {
            "n": 0,
            "mean_delta": None,
            "median_delta": None,
            "c_favored_count": 0,
            "c_favored_share": None,
            "direction": None,
        }
    favored = [value < 0 if loss else value > 0 for value in values]
    mean_delta = fmean(values)
    return {
        "n": len(values),
        "mean_delta": _round(mean_delta),
        "median_delta": _round(median(values)),
        "c_favored_count": sum(favored),
        "c_favored_share": _round(sum(favored) / len(values)),
        "direction": _direction(mean_delta if loss else -mean_delta),
    }


def summarize_endpoints(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    row_list = list(rows)
    definitions = {
        "delta_nll": True,
        "delta_actual_score_probability": False,
        "delta_exact_top1": False,
        "delta_exact_top3": False,
        "delta_one_x_two_brier": True,
        "delta_one_x_two_log_loss": True,
        "delta_btts_brier": True,
        "delta_btts_log_loss": True,
        "delta_ou_2_5_brier": True,
        "delta_ou_2_5_log_loss": True,
    }
    return {
        key: _endpoint_summary(row_list, key, loss=loss)
        for key, loss in definitions.items()
    }


def _quantile(values: Iterable[float], probability: float) -> float:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        raise AuditError("cannot compute a bootstrap quantile from no resamples")
    position = (len(ordered) - 1) * probability
    lower, upper = math.floor(position), math.ceil(position)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def _bootstrap_summary(means: list[float], *, seed: int, method: str, **extra: Any) -> dict[str, Any]:
    less_than_zero = sum(value < 0 for value in means)
    return {
        "method": method,
        "seed": seed,
        "resamples": len(means),
        "ci": {
            "lower": _round(_quantile(means, 0.025)),
            "upper": _round(_quantile(means, 0.975)),
        },
        "probability_mean_delta_lt_0": _round(less_than_zero / len(means)),
        **extra,
    }


def paired_bootstrap_summary(
    values: Iterable[float],
    *,
    resamples: int = BOOTSTRAP_RESAMPLES,
    seed: int = IID_BOOTSTRAP_SEED,
) -> dict[str, Any]:
    """Return a fixed-seed IID paired bootstrap for a mean delta."""

    value_list = [float(value) for value in values]
    if not value_list or resamples < 1:
        raise AuditError("IID bootstrap requires values and a positive resample count")
    rng = random.Random(seed)
    sample_size = len(value_list)
    means = [
        sum(value_list[rng.randrange(sample_size)] for _ in range(sample_size)) / sample_size
        for _ in range(resamples)
    ]
    return _bootstrap_summary(means, seed=seed, method="iid_paired_match_bootstrap")


def preregistered_block_length(n: int) -> int:
    if n < 1:
        raise AuditError("block length requires at least one observation")
    return max(2, round(math.sqrt(n)))


def moving_block_indices(n: int, rng: random.Random, *, block_length: int) -> list[int]:
    """Build a circular moving-block sample in the predeclared chronology order."""

    if n < 1 or block_length < 1:
        raise AuditError("moving blocks require positive n and block length")
    starts = math.ceil(n / block_length)
    indices: list[int] = []
    for _ in range(starts):
        start = rng.randrange(n)
        indices.extend((start + offset) % n for offset in range(block_length))
    return indices[:n]


def moving_block_bootstrap_summary(
    values: Iterable[float],
    *,
    resamples: int = BOOTSTRAP_RESAMPLES,
    seed: int = BLOCK_BOOTSTRAP_SEED,
    block_length: int | None = None,
) -> dict[str, Any]:
    value_list = [float(value) for value in values]
    if not value_list or resamples < 1:
        raise AuditError("moving-block bootstrap requires values and a positive resample count")
    block_length = block_length if block_length is not None else preregistered_block_length(len(value_list))
    rng = random.Random(seed)
    means = [
        fmean(value_list[index] for index in moving_block_indices(len(value_list), rng, block_length=block_length))
        for _ in range(resamples)
    ]
    return _bootstrap_summary(
        means,
        seed=seed,
        method="circular_moving_block_bootstrap",
        block_length=block_length,
        block_length_rule="max(2, round(sqrt(n)))",
        chronology_order="kickoff_at_ascending",
    )


def leave_one_out_summary(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    row_list = list(rows)
    if len(row_list) < 2:
        raise AuditError("leave-one-match-out influence requires at least two observations")
    values = [float(row["delta_nll"]) for row in row_list]
    full_mean = fmean(values)
    influence_rows = []
    for index, row in enumerate(row_list):
        remaining = values[:index] + values[index + 1 :]
        mean_without = fmean(remaining)
        shift = mean_without - full_mean
        influence_rows.append({
            "match_key": str(row.get("match_key") or ""),
            "delta_nll": values[index],
            "mean_without_match": mean_without,
            "shift_from_full_mean": shift,
        })
    max_row = max(
        influence_rows,
        key=lambda row: (abs(row["shift_from_full_mean"]), row["match_key"]),
    )
    sign_flip_matches = [
        row["match_key"]
        for row in influence_rows
        if (full_mean < 0 <= row["mean_without_match"])
        or (full_mean > 0 >= row["mean_without_match"])
    ]
    return {
        "full_mean_delta": _round(full_mean),
        "max_abs_shift": _round(abs(max_row["shift_from_full_mean"])),
        "max_shift": _round(max_row["shift_from_full_mean"]),
        "max_shift_match_key": max_row["match_key"],
        "sign_flip": bool(sign_flip_matches),
        "sign_flip_match_keys": sorted(sign_flip_matches),
        "rows": [
            {
                **row,
                "delta_nll": _round(row["delta_nll"]),
                "mean_without_match": _round(row["mean_without_match"]),
                "shift_from_full_mean": _round(row["shift_from_full_mean"]),
            }
            for row in influence_rows
        ],
    }


def _slice_summary(rows: list[Mapping[str, Any]], *, status_if_small: str = "INSUFFICIENT_SAMPLE") -> dict[str, Any]:
    values = [float(row["deltas"]["delta_nll"]) if "deltas" in row else float(row["delta_nll"]) for row in rows]
    if len(values) < MIN_COMPETITION_SLICE:
        return {
            "n": len(values),
            "status": status_if_small,
            "mean_delta_nll": None,
            "median_delta_nll": None,
            "direction": None,
            "c_better_share": None,
            "match_keys": [str(row.get("match_key") or "") for row in rows],
        }
    mean_delta = fmean(values)
    return {
        "n": len(values),
        "status": "DESCRIPTIVE",
        "mean_delta_nll": _round(mean_delta),
        "median_delta_nll": _round(median(values)),
        "direction": _direction(mean_delta),
        "c_better_share": _round(sum(value < 0 for value in values) / len(values)),
        "match_keys": [str(row.get("match_key") or "") for row in rows],
    }


def build_competition_slices(
    rows: Iterable[Mapping[str, Any]],
    labels: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    """Group only by exact current-universe labels; do not infer missing labels."""

    groups: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        label_value = labels.get(str(row.get("match_id") or ""))
        if isinstance(label_value, Mapping):
            label_value = label_value.get("league")
        label = str(label_value or "").strip()
        if label:
            groups[label].append(row)
    return {
        label: _slice_summary(groups[label])
        for label in sorted(groups)
    }


def build_chronological_thirds(rows: Iterable[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    row_list = list(rows)
    n = len(row_list)
    if not n:
        return {}
    base, remainder = divmod(n, 3)
    sizes = [base + (index < remainder) for index in range(3)]
    names = ("earliest", "middle", "latest")
    result: dict[str, dict[str, Any]] = {}
    start = 0
    for name, size in zip(names, sizes):
        subset = row_list[start : start + size]
        result[name] = _slice_summary(subset)
        start += size
    return result


def natural_main_delta(current_counts: Mapping[str, int]) -> dict[str, int]:
    return {
        key: int(current_counts.get(key, 0)) - baseline
        for key, baseline in ACCEPTED_PR175_BASELINE.items()
    }


def decide_primary(
    *,
    mean_delta: float | None,
    iid_upper: float | None,
    block_upper: float | None,
    loo_sign_flip: bool,
    opposite_slice_names: Iterable[str],
) -> str:
    """Apply Issue #176's four-way decision without adding a fifth outcome."""

    opposite = list(opposite_slice_names)
    if mean_delta is None:
        return "FAIL_CLOSED"
    if (
        mean_delta < 0
        and iid_upper is not None
        and block_upper is not None
        and iid_upper < 0
        and block_upper < 0
        and not loo_sign_flip
        and not opposite
    ):
        return "C_SIGNAL_STABLE_KEEP_TO_100"
    if mean_delta < 0:
        return "C_SIGNAL_PROMISING_NOT_ESTABLISHED"
    return "C_SIGNAL_NOT_SUPPORTED"


def _load_json(path: Path) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise AuditError(f"cannot read JSON artifact {path}: {error}") from error


def _load_universe_labels(universe_root: Path) -> tuple[dict[str, str], dict[str, Any]]:
    labels: dict[str, str] = {}
    conflicts: list[dict[str, str]] = []
    files_scanned = 0
    for path in sorted(Path(universe_root).glob("*.json")):
        files_scanned += 1
        document = _load_json(path)
        if not isinstance(document, Mapping):
            continue
        for fixture in document.get("fixtures") or []:
            if not isinstance(fixture, Mapping):
                continue
            match_id = str(fixture.get("matchId") or "").strip()
            league = str(fixture.get("league") or "").strip()
            if not match_id or not league:
                continue
            previous = labels.get(match_id)
            if previous is not None and previous != league:
                conflicts.append({"match_id": match_id, "first": previous, "second": league})
                continue
            labels[match_id] = league
    if conflicts:
        raise AuditError(f"conflicting canonical competition labels: {conflicts[:3]}")
    return labels, {
        "files_scanned": files_scanned,
        "labeled_match_ids": len(labels),
        "conflicts": conflicts,
    }


def _latest_counts(latest: Mapping[str, Any], selection: Mapping[str, Any], evaluation: Mapping[str, Any]) -> dict[str, int]:
    selected_counts = selection["counts"]
    expected = {
        "total_pair_version_rows": int(selected_counts["total_pair_version_rows"]),
        "promotion_eligible_pair_version_rows": int(selected_counts["promotion_eligible_pair_version_rows"]),
        "verified_pair_version_rows": int(selected_counts["verified_pair_version_rows"]),
        "promotion_eligible_unique_matches": int(selected_counts["promotion_eligible_unique_matches"]),
        "verified_unique_matches": int(selected_counts["verified_unique_matches"]),
        "version_history_match_groups": int(selected_counts["version_history_match_groups"]),
        "extra_version_rows": int(selected_counts["extra_version_rows"]),
        "unmatched_unique_matches": int(selected_counts["promotion_eligible_unique_matches"])
        - int(selected_counts["verified_unique_matches"]),
    }
    if expected["unmatched_unique_matches"] < 0:
        raise AuditError("verified unique matches exceed eligible unique matches")
    latest_counts = latest.get("counts") if isinstance(latest.get("counts"), Mapping) else {}
    evaluation_counts = {
        key: evaluation.get(key)
        for key in (
            "total_pair_version_rows",
            "promotion_eligible_pair_version_rows",
            "verified_pair_version_rows",
            "promotion_eligible_unique_matches",
            "verified_unique_matches",
            "version_history_match_groups",
            "extra_version_rows",
        )
    }
    if any(evaluation_counts[key] is None for key in evaluation_counts):
        raise AuditError("fresh evaluation is missing a required count")
    try:
        evaluation_matches = {
            key: int(value)
            for key, value in evaluation_counts.items()
        }
    except (TypeError, ValueError) as error:
        raise AuditError("fresh evaluation contains a non-integer count") from error
    if any(evaluation_matches[key] != expected[key] for key in evaluation_matches):
        raise AuditError("fresh evaluation counts disagree with representative selection")
    for key in expected:
        if key != "unmatched_unique_matches" and latest_counts.get(key) is not None:
            try:
                latest_value = int(latest_counts[key])
            except (TypeError, ValueError) as error:
                raise AuditError(f"refresh artifact contains a non-integer count for {key}") from error
            if latest_value != expected[key]:
                raise AuditError(f"refresh artifact count disagrees for {key}")
    return expected


def run_audit(
    *,
    latest_path: Path,
    result_root: Path,
    universe_root: Path,
    current_ref: str,
    snapshot_at: Any | None = None,
) -> dict[str, Any]:
    latest = _load_json(latest_path)
    if not isinstance(latest, Mapping) or latest.get("candidate_id") != "market_side_only_hybrid":
        raise AuditError("latest artifact is not Challenger C")
    pairs = [dict(pair) for pair in latest.get("pairs") or [] if isinstance(pair, Mapping)]
    if not pairs:
        raise AuditError("latest artifact contains no pair history")

    catalog, discovery = discover_verified_results(Path(result_root))
    result_map, matching = build_identity_safe_result_map(pairs, catalog)
    if discovery["result_identity_conflicts"] or matching["result_identity_mismatches"]:
        raise AuditError("result identity ambiguity requires FAIL_CLOSED")
    selection = select_promotion_representatives(pairs, result_map)
    block_length = preregistered_block_length(int(selection["counts"]["verified_unique_matches"]))
    evaluation = evaluate_paired_cohort(pairs, result_map)
    counts = _latest_counts(latest, selection, evaluation)
    cohort = build_audit_cohort(pairs, result_map, snapshot_at=snapshot_at)
    paired_rows = cohort["paired_rows"]
    if len(paired_rows) != counts["verified_unique_matches"]:
        raise AuditError("paired-row count does not equal verified unique-match count")
    if selection["counts"]["ambiguous_final_chronology_match_groups"]:
        raise AuditError("ambiguous final chronology requires FAIL_CLOSED")

    labels, universe_stats = _load_universe_labels(Path(universe_root))
    competition_slices = build_competition_slices(paired_rows, labels)
    chronology_slices = build_chronological_thirds(paired_rows)
    endpoint_summaries = summarize_endpoints(paired_rows)
    primary_values = [float(row["deltas"]["delta_nll"]) for row in paired_rows]
    iid = paired_bootstrap_summary(primary_values)
    block = moving_block_bootstrap_summary(primary_values, block_length=block_length)
    loo = leave_one_out_summary(
        {"match_key": row["match_key"], "delta_nll": row["deltas"]["delta_nll"]}
        for row in paired_rows
    )
    opposite_slices = [
        f"chronological::{name}"
        for name, value in chronology_slices.items()
        if value.get("status") == "DESCRIPTIVE" and value.get("direction") == "CHAMPION_FAVORED"
    ]
    opposite_slices.extend(
        f"competition::{name}"
        for name, value in competition_slices.items()
        if value.get("status") == "DESCRIPTIVE" and value.get("direction") == "CHAMPION_FAVORED"
    )
    mean_delta = fmean(primary_values) if primary_values else None
    primary = {
        "metric": "exact_score_nll",
        "delta_definition": "challenger_c_nll_minus_champion_nll; negative favors C",
        "mean_delta": _round(mean_delta),
        "median_delta": _round(median(primary_values)) if primary_values else None,
        "iid_bootstrap": iid,
        "moving_block_bootstrap": block,
        "bootstrap_probability_mean_delta_lt_0": iid["probability_mean_delta_lt_0"],
        "leave_one_match_out": loo,
        "c_higher_actual_score_probability_count": sum(
            row["deltas"]["delta_actual_score_probability"] > 0 for row in paired_rows
        ),
        "c_higher_actual_score_probability_share": _round(
            sum(row["deltas"]["delta_actual_score_probability"] > 0 for row in paired_rows)
            / len(paired_rows)
        ) if paired_rows else None,
        "paired_match_count": len(paired_rows),
    }
    natural_counts = {
        "eligible_unique_matches": counts["promotion_eligible_unique_matches"],
        "verified_unique_matches": counts["verified_unique_matches"],
        "unmatched_unique_matches": counts["unmatched_unique_matches"],
    }
    final_decision = decide_primary(
        mean_delta=mean_delta,
        iid_upper=iid["ci"]["upper"],
        block_upper=block["ci"]["upper"],
        loo_sign_flip=loo["sign_flip"],
        opposite_slice_names=opposite_slices,
    )
    refresh = latest.get("refresh") if isinstance(latest.get("refresh"), Mapping) else {}
    early_kill = evaluation.get("early_kill") if isinstance(evaluation.get("early_kill"), Mapping) else {}
    protection = latest.get("production_protection") if isinstance(latest.get("production_protection"), Mapping) else {}
    integrity_failures = list(early_kill.get("integrity_failures") or [])
    controls = {
        "read_only_audit": True,
        "result_network_fetch": False,
        "result_backfill": False,
        "manual_result_entry": False,
        "fuzzy_matching": False,
        "frozen_prediction_modified": False,
        "authoritative_result_modified": False,
        "champion_modified": False,
        "challenger_modified": False,
        "model_modified": False,
        "production_modified": False,
        "promotion_attempted": False,
        "automatic_promotion": protection.get("automatic_promotion") is True,
    }
    if integrity_failures or refresh.get("result_identity_conflicts") or refresh.get("result_identity_mismatches"):
        final_decision = "FAIL_CLOSED"
    if controls["automatic_promotion"]:
        raise AuditError("automatic promotion flag must remain false")
    return {
        "schema_version": SCHEMA_VERSION,
        "milestone": MILESTONE,
        "audit_snapshot_at": cohort["snapshot_at"],
        "source": {
            "current_ref": current_ref,
            "latest_artifact": str(latest_path),
            "result_root": str(result_root),
            "universe_root": str(universe_root),
            "result_source": "existing repository result artifacts only",
            "discovery": discovery,
            "matching": matching,
            "competition_universe": universe_stats,
        },
        "accepted_pr175_reference": ACCEPTED_PR175_REFERENCE,
        "natural_main_delta_vs_pr175": natural_main_delta(natural_counts),
        "scope": {
            "allowed_read_paths": [
                "data/prediction_quality/market_side_shadow_1/pairs",
                "data/postmatch_automation/results",
                "data/prediction_universe",
                "scripts/market_side_shadow.py",
                "scripts/market_side_shadow_refresh.py",
            ],
            "allowed_write_path": "artifact output directory only",
            "forbidden_writes": [
                "frozen predictions",
                "authoritative result truth",
                "Champion/C/model/production paths",
            ],
        },
        "current_main": {
            "counts": counts,
            "checkpoint": latest.get("checkpoint"),
            "refresh": refresh,
            "evaluation_early_kill": early_kill,
            "integrity": {
                "status": "PASS" if not integrity_failures else "FAIL",
                "failures": integrity_failures,
            },
            "cohort_rows": cohort["cohort_rows"],
            "paired_rows": paired_rows,
            "endpoint_summaries": endpoint_summaries,
            "chronological_thirds": chronology_slices,
            "competition_universe_slices": competition_slices,
            "unlabeled_verified_match_count": sum(
                str(row.get("match_id") or "") not in labels for row in paired_rows
            ),
        },
        "primary": primary,
        "decision_conditions": {
            "mean_delta_favors_c": bool(mean_delta is not None and mean_delta < 0),
            "iid_ci_upper_lt_zero": bool(iid["ci"]["upper"] < 0),
            "block_ci_upper_lt_zero": bool(block["ci"]["upper"] < 0),
            "leave_one_out_sign_flip": loo["sign_flip"],
            "opposite_sufficient_slice_names": opposite_slices,
        },
        "method": {
            "observation_unit": "one legal latest-prematch representative per unique football match",
            "paired_endpoints": "all per-match deltas are Challenger C minus Champion; lower is better for losses",
            "iid_bootstrap": {
                "resamples": BOOTSTRAP_RESAMPLES,
                "seed": IID_BOOTSTRAP_SEED,
                "sampling": "n unique-match deltas with replacement",
                "ci": "linear percentile quantiles at 2.5% and 97.5%",
            },
            "moving_block_bootstrap": {
                "resamples": BOOTSTRAP_RESAMPLES,
                "seed": BLOCK_BOOTSTRAP_SEED,
                "block_length": block_length,
                "block_length_rule": "max(2, round(sqrt(n))) determined before reading outcomes",
                "construction": "circular moving blocks in kickoff_at ascending order, truncated to n",
            },
            "leave_one_out": "remove one unique match and recompute the mean Exact NLL delta",
            "chronological_thirds": "earliest/middle/latest after kickoff_at ascending; descriptive only",
            "competition_universe": "exact matchId to current data/prediction_universe/*.json league only; n<10 is INSUFFICIENT_SAMPLE",
            "ece": "not computed per match; aggregate calibration remains descriptive in existing C review output",
        },
        "controls": controls,
        "final_decision": final_decision,
    }


def render_report(summary: Mapping[str, Any]) -> str:
    current = summary["current_main"]
    counts = current["counts"]
    primary = summary["primary"]
    lines = [
        f"# {MILESTONE}",
        "",
        f"Final decision: **{summary['final_decision']}**",
        "",
        "## Cohort and natural main delta",
        "",
        "| snapshot | eligible unique | verified unique | unmatched unique | checkpoint |",
        "| --- | ---: | ---: | ---: | --- |",
        "| merged PR #175 accepted baseline | 74 | 56 | 18 | CHECKPOINT |",
        f"| current origin/main ({summary['source']['current_ref']}) | {counts['promotion_eligible_unique_matches']} | {counts['verified_unique_matches']} | {counts['unmatched_unique_matches']} | {current['checkpoint']['status']} |",
        "",
        f"Natural main delta vs PR #175: `{summary['natural_main_delta_vs_pr175']}`. Version rows are audit history only; the inference sample is `{primary['paired_match_count']}` unique matches.",
        "",
        "## Primary Exact Score NLL",
        "",
        "delta_nll = Challenger C NLL - Champion NLL; negative favors C.",
        "",
        "| mean delta | median delta | IID 95% CI | block 95% CI | P(mean < 0) | C higher actual-score probability |",
        "| ---: | ---: | --- | --- | ---: | ---: |",
        f"| {primary['mean_delta']} | {primary['median_delta']} | [{primary['iid_bootstrap']['ci']['lower']}, {primary['iid_bootstrap']['ci']['upper']}] | [{primary['moving_block_bootstrap']['ci']['lower']}, {primary['moving_block_bootstrap']['ci']['upper']}] | {primary['bootstrap_probability_mean_delta_lt_0']} | {primary['c_higher_actual_score_probability_count']}/{primary['paired_match_count']} ({primary['c_higher_actual_score_probability_share']}) |",
        "",
        f"- IID bootstrap: {primary['iid_bootstrap']['resamples']} resamples, fixed seed {primary['iid_bootstrap']['seed']}.",
        f"- Circular moving-block bootstrap: {primary['moving_block_bootstrap']['resamples']} resamples, fixed seed {primary['moving_block_bootstrap']['seed']}, block length {primary['moving_block_bootstrap']['block_length']}.",
        f"- Leave-one-match-out max absolute shift: {primary['leave_one_match_out']['max_abs_shift']} (match {primary['leave_one_match_out']['max_shift_match_key']}); sign flip: {primary['leave_one_match_out']['sign_flip']}.",
        "",
        "## Paired secondary endpoint deltas",
        "",
        "Negative is favorable for loss metrics; positive is favorable for probability/hit metrics.",
        "",
        "| endpoint delta | mean | median | C favored n/share | direction |",
        "| --- | ---: | ---: | --- | --- |",
    ]
    labels = {
        "delta_actual_score_probability": "actual-score probability",
        "delta_exact_top1": "Exact Top1",
        "delta_exact_top3": "Exact Top3",
        "delta_one_x_two_brier": "1X2 Brier",
        "delta_one_x_two_log_loss": "1X2 log loss",
        "delta_btts_brier": "BTTS Brier",
        "delta_btts_log_loss": "BTTS log loss",
        "delta_ou_2_5_brier": "O/U 2.5 Brier",
        "delta_ou_2_5_log_loss": "O/U 2.5 log loss",
    }
    for key, label in labels.items():
        value = current["endpoint_summaries"][key]
        lines.append(
            f"| {label} | {value['mean_delta']} | {value['median_delta']} | {value['c_favored_count']}/{value['n']} ({value['c_favored_share']}) | {value['direction']} |"
        )
    lines.extend([
        "",
        "## Chronological thirds",
        "",
        "| slice | n | status | mean Exact NLL delta | direction |",
        "| --- | ---: | --- | ---: | --- |",
    ])
    for name, value in current["chronological_thirds"].items():
        lines.append(f"| {name} | {value['n']} | {value['status']} | {value['mean_delta_nll']} | {value['direction']} |")
    lines.extend([
        "",
        "## Competition-universe slices",
        "",
        "Only exact existing matchId labels are used. Groups below n=10 are reported as INSUFFICIENT_SAMPLE and do not enter the decision.",
        "",
        "| league | n | status | mean Exact NLL delta | direction |",
        "| --- | ---: | --- | ---: | --- |",
    ])
    for name, value in current["competition_universe_slices"].items():
        lines.append(f"| {name} | {value['n']} | {value['status']} | {value['mean_delta_nll']} | {value['direction']} |")
    lines.extend([
        "",
        "## Decision conditions",
        "",
        f"`{json.dumps(summary['decision_conditions'], ensure_ascii=False, sort_keys=True)}`",
        "",
        "## Per-match paired rows",
        "",
        "These rows are the complete independent input for the primary mean, IID bootstrap, moving-block bootstrap, and leave-one-match-out calculations.",
        "",
        "| kickoff | match key | actual | Champion p(score) | C p(score) | Champion NLL | C NLL | delta NLL |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |",
    ])
    for row in current["paired_rows"]:
        lines.append(
            f"| {row['kickoff_at']} | {row['match_key']} | {row['actual_score']} | {row['champion']['actual_score_probability']:.12f} | {row['challenger']['actual_score_probability']:.12f} | {row['champion']['exact_nll']:.12f} | {row['challenger']['exact_nll']:.12f} | {row['deltas']['delta_nll']:.12f} |"
        )
    lines.extend([
        "",
        "## Integrity and read-only controls",
        "",
        f"- Integrity: `{current['integrity']['status']}`; result identity conflicts/mismatches: `{current['refresh'].get('result_identity_conflicts')}/{current['refresh'].get('result_identity_mismatches')}`.",
        f"- Input source: existing repository result artifacts only; no result network fetch or backfill; current ref: `{summary['source']['current_ref']}`.",
        f"- Controls: `{json.dumps(summary['controls'], ensure_ascii=False, sort_keys=True)}`",
        f"- Scope: read `{json.dumps(summary['scope']['allowed_read_paths'], ensure_ascii=False)}`; write `{summary['scope']['allowed_write_path']}` only.",
        "- No model, Champion/C mathematics, provider, frozen history, authoritative result truth, serving, or promotion change was made.",
        "",
        "STOP: research-only evidence; DO NOT MERGE; independent acceptance required.",
        "",
    ])
    return "\n".join(lines)


def write_artifacts(summary: Mapping[str, Any], output_dir: Path) -> dict[str, Path]:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    summary_path = output_dir / "summary.json"
    report_path = output_dir / "report.md"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    report_path.write_text(render_report(summary), encoding="utf-8")
    return {"summary": summary_path, "report": report_path}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latest", type=Path, required=True)
    parser.add_argument("--result-root", type=Path, required=True)
    parser.add_argument("--universe-root", type=Path, required=True)
    parser.add_argument("--current-ref", required=True)
    parser.add_argument("--snapshot-at")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        summary = run_audit(
            latest_path=args.latest,
            result_root=args.result_root,
            universe_root=args.universe_root,
            current_ref=args.current_ref,
            snapshot_at=args.snapshot_at,
        )
        paths = write_artifacts(summary, args.output_dir)
    except AuditError as error:
        print(json.dumps({"milestone": MILESTONE, "final_decision": "FAIL_CLOSED", "error": str(error)}, ensure_ascii=False))
        return 1
    print(json.dumps({
        "milestone": MILESTONE,
        "final_decision": summary["final_decision"],
        "verified_unique_matches": summary["current_main"]["counts"]["verified_unique_matches"],
        "mean_delta": summary["primary"]["mean_delta"],
        "iid_ci": summary["primary"]["iid_bootstrap"]["ci"],
        "block_ci": summary["primary"]["moving_block_bootstrap"]["ci"],
        "summary": str(paths["summary"]),
        "report": str(paths["report"]),
    }, ensure_ascii=False, sort_keys=True))
    return 0 if summary["final_decision"] != "FAIL_CLOSED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
