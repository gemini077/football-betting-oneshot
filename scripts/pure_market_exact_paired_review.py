#!/usr/bin/env python3
"""Read-only exact-pair prospective review for Pure Market Exact.

The report starts from settled Pure Market versions, applies the existing
unique-match aggregation order, and resolves Champion only through the exact
stored control-pair prediction id.  It never changes prediction, settlement,
Champion, serving, or promotion state.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import sys
from typing import Any, Callable, Iterable, Mapping

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from evaluation_kernel import (  # noqa: E402
    evaluate_prediction_common,
    normalize_verified_result,
    parse_score_pair,
    ranked_probability_score,
)
from model_governance import load_frozen_prediction  # noqa: E402
from pure_market_exact_prospective import (  # noqa: E402
    DEFAULT_OUTPUT_ROOT as DEFAULT_MARKET_ROOT,
    RESULT_SCOPE,
    aggregate_settlements,
    load_persisted_predictions,
    load_persisted_settlements,
    select_unique_settlements,
)

REVIEW_ID = "PURE-MARKET-EXACT-PAIRED-PROSPECTIVE-REVIEW-R1"
REVIEW_SCHEMA_VERSION = "pure_market_exact_paired_review_1.v1"
MARKET_NAMESPACE = "pure_market_exact_prospective_1"
DEFAULT_RECORD_ROOT = ROOT / "data" / "model_governance" / "predictions"
DEFAULT_OUTPUT = (
    ROOT
    / "data"
    / "prediction_quality"
    / "pure_market_exact_paired_review_1"
    / "review.json"
)
DEFAULT_SUMMARY = (
    ROOT
    / "data"
    / "prediction_quality"
    / "pure_market_exact_paired_review_1"
    / "summary.md"
)

METRICS = (
    "exact_nll",
    "exact_top1",
    "exact_top3",
    "exact_top5",
    "actual_score_rank",
    "ft_1x2_log_loss",
    "ft_1x2_brier",
    "ft_1x2_rps",
    "ou_2_5_brier",
    "btts_brier",
    "lambda_home_residual",
    "lambda_away_residual",
    "lambda_total_residual",
    "lambda_home_absolute_error",
    "lambda_away_absolute_error",
    "lambda_total_absolute_error",
    "score_1_1_top1",
)

LOWER_IS_BETTER = frozenset({
    "exact_nll",
    "actual_score_rank",
    "ft_1x2_log_loss",
    "ft_1x2_brier",
    "ft_1x2_rps",
    "ou_2_5_brier",
    "btts_brier",
    "lambda_home_absolute_error",
    "lambda_away_absolute_error",
    "lambda_total_absolute_error",
})
HIGHER_IS_BETTER = frozenset({
    "exact_top1",
    "exact_top3",
    "exact_top5",
})

PAIR_SELECTION_ORDER = (
    "source_cutoff_at",
    "prediction_generated_at",
    "evaluated_at",
    "prediction_id",
)

SOURCE_PATHS = {
    "market_root": "data/prediction_quality/pure_market_exact_prospective_1",
    "market_predictions": "data/prediction_quality/pure_market_exact_prospective_1/predictions",
    "market_settlements": "data/prediction_quality/pure_market_exact_prospective_1/settlements",
    "champion_predictions": "data/model_governance/predictions",
    "aggregation_kernel": "scripts/pure_market_exact_prospective.py::aggregate_settlements",
    "evaluation_kernel": "scripts/evaluation_kernel.py::evaluate_prediction_common",
}

def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None

def _timestamp(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)

def _same_timestamp(left: Any, right: Any) -> bool:
    parsed_left = _timestamp(left)
    parsed_right = _timestamp(right)
    return parsed_left is not None and parsed_right is not None and parsed_left == parsed_right

def _record_field(record: Mapping[str, Any], field: str) -> Any:
    nested = record.get("match_identity")
    nested = nested if isinstance(nested, Mapping) else {}
    return record.get(field) or nested.get(field)

def _record_match_key(record: Mapping[str, Any]) -> str:
    return str(_record_field(record, "match_key") or "").strip()

def _record_match_id(record: Mapping[str, Any]) -> str:
    return str(_record_field(record, "match_id") or "").strip()

def _record_kickoff(record: Mapping[str, Any]) -> Any:
    return _record_field(record, "kickoff_at")

def _relative_path(path: Path) -> str:
    path = Path(path)
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return str(path)

def _write_text_if_changed(path: Path, value: str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file() and path.read_text(encoding="utf-8") == value:
        return
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(value, encoding="utf-8")
    os.replace(temporary, path)

def _market_version_reason(settlement: Any) -> str | None:
    if not isinstance(settlement, Mapping):
        return "MARKET_SETTLEMENT_NOT_OBJECT"
    if not str(settlement.get("match_key") or "").strip():
        return "MARKET_MATCH_KEY_MISSING"
    kickoff = _timestamp(settlement.get("kickoff_at"))
    source_cutoff = _timestamp(settlement.get("source_cutoff_at"))
    generated = _timestamp(settlement.get("prediction_generated_at"))
    if kickoff is None:
        return "MARKET_KICKOFF_TIMESTAMP_INVALID"
    if source_cutoff is None or generated is None:
        return "MARKET_PREMATCH_TIMESTAMP_MISSING"
    if source_cutoff >= kickoff or generated >= kickoff:
        return "MARKET_VERSION_POST_KICKOFF"
    return None

def _market_selection(
    settlements: Iterable[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    raw_rows = [dict(row) for row in settlements if isinstance(row, Mapping)]
    raw_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    legal_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    legal_rows: list[dict[str, Any]] = []
    exclusions: Counter[str] = Counter()
    exclusion_rows: list[dict[str, Any]] = []
    for row in raw_rows:
        key = str(row.get("match_key") or "")
        raw_groups[key].append(row)
        reason = _market_version_reason(row)
        if reason:
            exclusions[reason] += 1
            exclusion_rows.append({
                "match_key": str(row.get("match_key") or "") or None,
                "market_prediction_id": str(row.get("prediction_id") or "") or None,
                "reason": reason,
            })
            continue
        legal_groups[key].append(row)
        legal_rows.append(row)

    # This call is the canonical aggregate kernel used by the existing lane.
    aggregate = aggregate_settlements(legal_rows)
    selection = select_unique_settlements(legal_rows)
    selected = [dict(row) for row in selection["unique_settlements"]]
    selected.sort(key=lambda row: str(row.get("match_key") or ""))

    selection_rows: list[dict[str, Any]] = []
    conflict_keys = set(str(key) for key in aggregate["duplicate_match_conflicts"])
    for key in sorted(raw_groups):
        rows = legal_groups.get(key, [])
        selected_row = next(
            (row for row in selected if str(row.get("match_key") or "") == key),
            None,
        )
        selection_rows.append({
            "match_key": key,
            "raw_market_settlement_count": len(raw_groups[key]),
            "legal_market_version_count": len(rows),
            "superseded_market_version_count": (
                max(0, len(rows) - 1) if key not in conflict_keys else 0
            ),
            "status": (
                "REJECTED_RESULT_CONFLICT"
                if key in conflict_keys
                else "SELECTED" if selected_row else "REJECTED_NO_LEGAL_VERSION"
            ),
            "selected_market_prediction_id": (
                str(selected_row.get("prediction_id") or "") if selected_row else None
            ),
        })
    return selected, {
        "aggregate": aggregate,
        "raw_market_settlement_count": len(raw_rows),
        "raw_market_match_group_count": len(raw_groups),
        "legal_market_settlement_count": len(legal_rows),
        "selection_rows": selection_rows,
        "selection_excluded_reason_counts": dict(sorted(exclusions.items())),
        "selection_exclusions": sorted(
            exclusion_rows,
            key=lambda row: (
                str(row.get("match_key") or ""),
                str(row.get("market_prediction_id") or ""),
                str(row.get("reason") or ""),
            ),
        ),
    }

def _control_pair_reference(
    settlement: Mapping[str, Any],
    market_prediction: Mapping[str, Any] | None,
) -> tuple[str | None, list[dict[str, Any]], str | None]:
    references: list[dict[str, Any]] = []
    stored = settlement.get("control_pair")
    if stored is not None:
        if not isinstance(stored, Mapping):
            return None, [], "CONTROL_PAIR_MISSING"
        references.append(dict(stored))
        if not str(stored.get("prediction_id") or stored.get("source_record_prediction_id") or "").strip():
            return None, [], "CONTROL_PAIR_MISSING"

    if isinstance(market_prediction, Mapping):
        champion_reference = market_prediction.get("champion_reference")
        if champion_reference is not None:
            if not isinstance(champion_reference, Mapping):
                return None, [], "CONTROL_PAIR_MISSING"
            references.append(dict(champion_reference))
        source_id = str(market_prediction.get("source_record_prediction_id") or "").strip()
        if source_id:
            references.append({"prediction_id": source_id})

    ids = {
        str(reference.get("prediction_id") or reference.get("source_record_prediction_id") or "").strip()
        for reference in references
    }
    ids.discard("")
    if not ids:
        return None, [], "CONTROL_PAIR_MISSING"
    if len(ids) != 1:
        return None, references, "CONTROL_PAIR_ID_CONFLICT"
    return next(iter(ids)), references, None

def _contains_postmatch_field(value: Any) -> bool:
    fields = {
        "actual_score",
        "actual_outcome",
        "result",
        "settlement",
        "postmatch_evidence",
        "verified_at",
        "reviewed_at",
    }
    if isinstance(value, Mapping):
        return any(key in fields or _contains_postmatch_field(child) for key, child in value.items())
    if isinstance(value, list):
        return any(_contains_postmatch_field(child) for child in value)
    return False

def _snapshot_id(record: Mapping[str, Any]) -> str:
    input_snapshot = record.get("input_snapshot")
    if isinstance(input_snapshot, Mapping) and input_snapshot.get("snapshot_id"):
        return str(input_snapshot["snapshot_id"])
    snapshot_identity = record.get("snapshot_identity")
    if isinstance(snapshot_identity, Mapping) and snapshot_identity.get("snapshot_id"):
        return str(snapshot_identity["snapshot_id"])
    return ""

def _validate_control_pair_metadata(
    settlement: Mapping[str, Any],
    references: list[Mapping[str, Any]],
    champion: Mapping[str, Any],
) -> str | None:
    if not references:
        return "CONTROL_PAIR_MISSING"
    match_key = str(settlement.get("match_key") or "")
    for reference in references:
        if any(key in reference for key in ("same_match", "same_source_cutoff", "same_horizon_authority")):
            if reference.get("same_match") is not True:
                return "CONTROL_PAIR_SAME_MATCH_INVALID"
            if reference.get("same_source_cutoff") is not True:
                return "CONTROL_PAIR_SOURCE_CUTOFF_INVALID"
            if reference.get("same_horizon_authority") is not True:
                return "CONTROL_PAIR_HORIZON_INVALID"
        if reference.get("match_key") not in (None, "") and str(reference.get("match_key")) != match_key:
            return "MATCH_IDENTITY_MISMATCH"
        if reference.get("source_cutoff_at") not in (None, "") and not _same_timestamp(
            reference.get("source_cutoff_at"), settlement.get("source_cutoff_at")
        ):
            return "SOURCE_CUTOFF_MISMATCH"
        if reference.get("prediction_sha256") not in (None, "") and reference.get("prediction_sha256") != champion.get("prediction_sha256"):
            return "CHAMPION_DIGEST_MISMATCH"
        if reference.get("freeze_created_at") not in (None, "") and reference.get("freeze_created_at") != champion.get("freeze_created_at"):
            return "CHAMPION_FREEZE_MISMATCH"
        snapshot_id = reference.get("snapshot_id")
        if snapshot_id not in (None, "") and str(snapshot_id) != _snapshot_id(champion):
            return "HORIZON_AUTHORITY_MISMATCH"
    return None

def _validate_linked_records(
    settlement: Mapping[str, Any],
    market_prediction: Mapping[str, Any] | None,
    champion: Mapping[str, Any],
) -> str | None:
    match_key = str(settlement.get("match_key") or "")
    if _record_match_key(champion) != match_key:
        return "MATCH_IDENTITY_MISMATCH"
    if not _same_timestamp(_record_kickoff(champion), settlement.get("kickoff_at")):
        return "MATCH_IDENTITY_MISMATCH"
    if market_prediction is not None:
        if _record_match_key(market_prediction) != match_key:
            return "MARKET_MATCH_IDENTITY_MISMATCH"
        if not _same_timestamp(_record_kickoff(market_prediction), settlement.get("kickoff_at")):
            return "MARKET_MATCH_IDENTITY_MISMATCH"
        market_id = str(market_prediction.get("prediction_id") or "")
        if market_id != str(settlement.get("prediction_id") or ""):
            return "MARKET_PREDICTION_ID_MISMATCH"
        if not _same_timestamp(
            market_prediction.get("source_cutoff_at"), settlement.get("source_cutoff_at")
        ):
            return "MARKET_SOURCE_CUTOFF_MISMATCH"
        settlement_digest = str(settlement.get("prediction_digest") or "")
        market_digest = str(
            market_prediction.get("prediction_digest")
            or market_prediction.get("prediction_sha256")
            or ""
        )
        if settlement_digest and market_digest and settlement_digest != market_digest:
            return "MARKET_PREDICTION_DIGEST_MISMATCH"
        settlement_match_id = str(settlement.get("match_id") or "")
        market_match_id = _record_match_id(market_prediction)
        if settlement_match_id and market_match_id and settlement_match_id != market_match_id:
            return "MARKET_MATCH_IDENTITY_MISMATCH"

    champion_match_id = _record_match_id(champion)
    market_match_id = _record_match_id(market_prediction) if market_prediction is not None else ""
    settlement_match_id = str(settlement.get("match_id") or "")
    if settlement_match_id and champion_match_id and settlement_match_id != champion_match_id:
        return "MATCH_IDENTITY_MISMATCH"
    if champion_match_id and market_match_id and champion_match_id != market_match_id:
        return "MATCH_IDENTITY_MISMATCH"
    if not _same_timestamp(champion.get("source_cutoff_at"), settlement.get("source_cutoff_at")):
        return "SOURCE_CUTOFF_MISMATCH"
    model_input_as_of = champion.get("model_input_as_of_at")
    if model_input_as_of not in (None, "") and not _same_timestamp(model_input_as_of, settlement.get("source_cutoff_at")):
        return "HORIZON_AUTHORITY_MISMATCH"
    kickoff = _timestamp(settlement.get("kickoff_at"))
    source_cutoff = _timestamp(champion.get("source_cutoff_at"))
    prediction_created = _timestamp(champion.get("prediction_created_at") or champion.get("created_at"))
    freeze_created = _timestamp(champion.get("freeze_created_at"))
    if (
        kickoff is None
        or source_cutoff is None
        or prediction_created is None
        or freeze_created is None
        or source_cutoff >= kickoff
        or prediction_created >= kickoff
        or freeze_created >= kickoff
    ):
        return "CHAMPION_NOT_IMMUTABLE_PREMATCH"
    if champion.get("model_role") not in (None, "champion"):
        return "CHAMPION_NOT_IMMUTABLE_PREMATCH"
    if champion.get("formal_eligible") is False or champion.get("model_formal_eligible") is False:
        return "CHAMPION_NOT_IMMUTABLE_PREMATCH"
    if _contains_postmatch_field(champion):
        return "CHAMPION_NOT_IMMUTABLE_PREMATCH"
    return None

def _settlement_result(settlement: Mapping[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    if settlement.get("settlement_status") != "SETTLED":
        return None, "MARKET_SETTLEMENT_NOT_SETTLED"
    result = settlement.get("result")
    if not isinstance(result, Mapping):
        return None, "RESULT_MISSING"
    if result.get("scope") != RESULT_SCOPE:
        return None, "RESULT_SCOPE_MISMATCH"
    verified_at = result.get("verified_at") or result.get("result_verified_at")
    kickoff = _timestamp(settlement.get("kickoff_at"))
    verified = _timestamp(verified_at)
    if kickoff is None or verified is None or verified <= kickoff:
        return None, "RESULT_TIME_UNVERIFIED"
    score = parse_score_pair(result.get("actual_score"))
    if score is None:
        return None, "RESULT_MISSING"
    try:
        normalized = normalize_verified_result({
            "status": "result_verified",
            "scope": RESULT_SCOPE,
            "verified_at": verified_at,
            "score_90m": result.get("actual_score"),
        })
    except ValueError:
        return None, "RESULT_MISSING"
    return normalized, None

def _full_score_rows(prediction: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    exact = prediction.get("exact_score_distribution")
    if isinstance(exact, Mapping) and isinstance(exact.get("cells"), list):
        return [row for row in exact["cells"] if isinstance(row, Mapping)]
    matrix = prediction.get("score_matrix")
    if isinstance(matrix, list) and prediction.get("score_matrix_complete") is True:
        return [row for row in matrix if isinstance(row, Mapping)]
    output = prediction.get("prediction_output")
    if (
        isinstance(output, Mapping)
        and output.get("score_matrix_complete") is True
        and isinstance(output.get("score_matrix"), list)
    ):
        return [row for row in output["score_matrix"] if isinstance(row, Mapping)]
    return []

def _total_goals_over_probability(rows: Any) -> float | None:
    if not isinstance(rows, list):
        return None
    probabilities: list[float] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        goals = str(row.get("goals") or "").strip()
        probability = _number(row.get("probability"))
        if probability is None:
            continue
        if goals.endswith("+"):
            is_over = True
        else:
            try:
                is_over = float(goals) >= 3
            except ValueError:
                continue
        if is_over:
            probabilities.append(probability)
    return sum(probabilities) if probabilities else None

def _over_2_5_probability(prediction: Mapping[str, Any]) -> float | None:
    derived = prediction.get("derived_markets")
    if isinstance(derived, Mapping):
        totals = derived.get("totals")
        row = totals.get("2.5") if isinstance(totals, Mapping) else None
        over = row.get("over") if isinstance(row, Mapping) else None
        direct = _number(over.get("win_probability")) if isinstance(over, Mapping) else None
        if direct is not None:
            return direct
    for key in ("totals", "total_goal_distribution"):
        direct = _total_goals_over_probability(prediction.get(key))
        if direct is not None:
            return direct
    output = prediction.get("prediction_output")
    if isinstance(output, Mapping):
        direct = _total_goals_over_probability(output.get("totals"))
        if direct is not None:
            return direct
    rows = _full_score_rows(prediction)
    probabilities = []
    for row in rows:
        score = parse_score_pair(row)
        probability = _number(row.get("probability"))
        if score is not None and probability is not None:
            probabilities.append((score, probability))
    if not probabilities:
        return None
    return sum(probability for (home, away), probability in probabilities if home + away >= 3)

def _evaluated_metrics(
    prediction: Mapping[str, Any],
    result: Mapping[str, Any],
    *,
    frozen_record: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    common = evaluate_prediction_common(
        prediction,
        result,
        frozen_record=frozen_record,
        include_distribution=True,
        preserve_declared_rank=True,
        include_output_probabilities=False,
    )
    over_probability = _over_2_5_probability(prediction)
    actual_over = common.get("actual_score")
    actual_score = parse_score_pair(actual_over)
    btts_actual = common.get("btts_actual")
    return {
        "exact_nll": common.get("actual_score_nll"),
        "exact_top1": common.get("exact_score_top1"),
        "exact_top3": common.get("exact_score_top3"),
        "exact_top5": common.get("exact_score_top5"),
        "actual_score_rank": common.get("actual_score_rank"),
        "ft_1x2_log_loss": common.get("log_loss_1x2"),
        "ft_1x2_brier": common.get("brier_score_1x2"),
        "ft_1x2_rps": ranked_probability_score(
            common.get("outcome_probabilities"),
            common.get("actual_outcome"),
        ),
        "ou_2_5_brier": (
            (over_probability - float(actual_score[0] + actual_score[1] >= 3)) ** 2
            if over_probability is not None and actual_score is not None
            else None
        ),
        "btts_brier": (
            (float(common["btts_probability"]) - float(btts_actual)) ** 2
            if common.get("btts_probability") is not None and isinstance(btts_actual, bool)
            else None
        ),
        "lambda_home_residual": common.get("lambda_home_residual"),
        "lambda_away_residual": common.get("lambda_away_residual"),
        "lambda_total_residual": common.get("total_goals_residual"),
        "lambda_home_absolute_error": common.get("home_goal_absolute_error"),
        "lambda_away_absolute_error": common.get("away_goal_absolute_error"),
        "lambda_total_absolute_error": common.get("total_goal_absolute_error"),
        "score_1_1_top1": common.get("top1_1_1"),
    }

def _stored_metrics(settlement: Mapping[str, Any]) -> dict[str, Any]:
    stored = settlement.get("metrics")
    stored = stored if isinstance(stored, Mapping) else {}
    return {metric: stored.get(metric) for metric in METRICS}

def _metric_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    return _number(value)

def _metric_summary(values: Iterable[Any]) -> dict[str, Any]:
    numbers = [number for value in values if (number := _metric_number(value)) is not None]
    return {
        "n": len(numbers),
        "mean": sum(numbers) / len(numbers) if numbers else None,
    }

def _paired_delta_stats(values: Iterable[float]) -> dict[str, Any]:
    numbers = [float(value) for value in values if _number(value) is not None]
    count = len(numbers)
    if not count:
        return {
            "n": 0,
            "mean": None,
            "sample_stddev": None,
            "standard_error": None,
            "ci95_low": None,
            "ci95_high": None,
        }
    mean = sum(numbers) / count
    if count < 2:
        stddev = None
        standard_error = None
        ci95_low = None
        ci95_high = None
    else:
        variance = sum((value - mean) ** 2 for value in numbers) / (count - 1)
        stddev = math.sqrt(variance)
        standard_error = stddev / math.sqrt(count)
        ci95_low = mean - 1.96 * standard_error
        ci95_high = mean + 1.96 * standard_error
    return {
        "n": count,
        "mean": mean,
        "sample_stddev": stddev,
        "standard_error": standard_error,
        "ci95_low": ci95_low,
        "ci95_high": ci95_high,
    }

def _maturity(count: int) -> dict[str, Any]:
    if count < 50:
        verdict = "INSUFFICIENT_SAMPLE_CONTINUE_ACCUMULATING"
        band = "n<50"
    elif count < 100:
        verdict = "DIRECTION_AND_UNCERTAINTY_ONLY_NO_AUTOMATIC_PROMOTION"
        band = "50<=n<100"
    else:
        verdict = "MATURE_FOR_SEPARATE_INDEPENDENT_PROMOTION_REGATE"
        band = "n>=100"
    return {
        "sample_band": band,
        "verdict": verdict,
        "winner": None,
        "promotion_authorized": False,
    }

def _pair_rejection(
    settlement: Mapping[str, Any],
    reason: str,
    *,
    champion_prediction_id: str | None = None,
    market_prediction_ids: Iterable[str] | None = None,
) -> dict[str, Any]:
    result = {
        "match_key": str(settlement.get("match_key") or "") or None,
        "market_prediction_id": str(settlement.get("prediction_id") or "") or None,
        "champion_prediction_id": champion_prediction_id,
        "reason": reason,
    }
    if market_prediction_ids is not None:
        result["market_prediction_ids"] = sorted(str(value) for value in market_prediction_ids)
    return result

def build_review(
    settlements: Iterable[Mapping[str, Any]],
    *,
    market_predictions: Mapping[str, Mapping[str, Any]] | None = None,
    champion_predictions: Mapping[str, Mapping[str, Any]] | None = None,
    champion_loader: Callable[[str], Mapping[str, Any] | None] | None = None,
    source: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a deterministic paired review from already persisted artifacts."""

    settlement_rows = [dict(row) for row in settlements if isinstance(row, Mapping)]
    selected, selection_info = _market_selection(settlement_rows)
    market_by_id = (
        {str(key): dict(value) for key, value in market_predictions.items() if isinstance(value, Mapping)}
        if market_predictions is not None
        else None
    )
    champion_by_id = (
        {str(key): dict(value) for key, value in champion_predictions.items() if isinstance(value, Mapping)}
        if champion_predictions is not None
        else None
    )

    rejects: list[dict[str, Any]] = []
    reject_counts: Counter[str] = Counter()
    pairs: list[dict[str, Any]] = []
    exact_control_pair_id_count = 0
    exact_champion_pair_resolved_count = 0

    for conflict_key in selection_info["aggregate"]["duplicate_match_conflicts"]:
        conflict_rows = [
            row for row in settlement_rows
            if str(row.get("match_key") or "") == str(conflict_key)
            and _market_version_reason(row) is None
        ]
        rejection = _pair_rejection(
            {"match_key": conflict_key},
            "DUPLICATE_RESULT_CONFLICT",
            market_prediction_ids=(row.get("prediction_id") for row in conflict_rows),
        )
        rejects.append(rejection)
        reject_counts[rejection["reason"]] += 1

    for settlement in selected:
        market_id = str(settlement.get("prediction_id") or "")
        market_prediction = market_by_id.get(market_id) if market_by_id is not None else None
        if market_by_id is not None and market_prediction is None:
            reason = "MARKET_PREDICTION_MISSING"
            rejects.append(_pair_rejection(settlement, reason))
            reject_counts[reason] += 1
            continue

        champion_id, references, reason = _control_pair_reference(settlement, market_prediction)
        if champion_id:
            exact_control_pair_id_count += 1
        if reason:
            rejects.append(_pair_rejection(settlement, reason, champion_prediction_id=champion_id))
            reject_counts[reason] += 1
            continue

        if champion_by_id is not None:
            champion = champion_by_id.get(champion_id or "")
        elif champion_loader is not None:
            try:
                champion = champion_loader(champion_id or "")
            except (OSError, TypeError, ValueError, json.JSONDecodeError):
                champion = None
        else:
            champion = None
        if not isinstance(champion, Mapping):
            reason = "CHAMPION_PREDICTION_MISSING"
            rejects.append(_pair_rejection(settlement, reason, champion_prediction_id=champion_id))
            reject_counts[reason] += 1
            continue
        exact_champion_pair_resolved_count += 1

        if str(champion.get("prediction_id") or "") != champion_id:
            reason = "CHAMPION_PREDICTION_ID_MISMATCH"
        else:
            reason = _validate_linked_records(settlement, market_prediction, champion)
        if reason is None:
            reason = _validate_control_pair_metadata(settlement, references, champion)
        result, result_reason = _settlement_result(settlement)
        if reason is None:
            reason = result_reason
        if reason:
            rejects.append(_pair_rejection(settlement, reason, champion_prediction_id=champion_id))
            reject_counts[reason] += 1
            continue

        assert result is not None
        if market_prediction is None:
            market_metrics = _stored_metrics(settlement)
        else:
            market_metrics = _evaluated_metrics(market_prediction, result)
        champion_metrics = _evaluated_metrics(champion, result, frozen_record=champion)
        pair_deltas = {
            metric: (
                _metric_number(market_metrics.get(metric)) - _metric_number(champion_metrics.get(metric))
                if _metric_number(market_metrics.get(metric)) is not None
                and _metric_number(champion_metrics.get(metric)) is not None
                else None
            )
            for metric in METRICS
        }
        pairs.append({
            "match_key": str(settlement.get("match_key") or ""),
            "market_prediction_id": market_id,
            "champion_prediction_id": champion_id,
            "kickoff_at": settlement.get("kickoff_at"),
            "source_cutoff_at": settlement.get("source_cutoff_at"),
            "verified_at": (settlement.get("result") or {}).get("verified_at"),
            "actual_score": result.get("actual_score"),
            "result_scope": result.get("scope"),
            "market": market_metrics,
            "champion": {metric: champion_metrics.get(metric) for metric in METRICS},
            "deltas": pair_deltas,
        })

    pairs.sort(key=lambda row: str(row.get("match_key") or ""))
    rejects.sort(key=lambda row: (
        str(row.get("match_key") or ""),
        str(row.get("market_prediction_id") or ""),
        str(row.get("reason") or ""),
    ))

    market_metrics = {
        metric: _metric_summary(pair["market"].get(metric) for pair in pairs)
        for metric in METRICS
    }
    champion_metrics = {
        metric: _metric_summary(pair["champion"].get(metric) for pair in pairs)
        for metric in METRICS
    }
    delta_values = {
        metric: [
            delta
            for pair in pairs
            if (delta := _metric_number(pair["deltas"].get(metric))) is not None
        ]
        for metric in METRICS
    }
    deltas = {metric: _paired_delta_stats(values) for metric, values in delta_values.items()}
    comparisons: dict[str, Any] = {}
    for metric in sorted(LOWER_IS_BETTER | HIGHER_IS_BETTER):
        direction = "lower_is_better" if metric in LOWER_IS_BETTER else "higher_is_better"
        wins = ties = losses = 0
        for value in delta_values[metric]:
            if math.isclose(value, 0.0, rel_tol=0.0, abs_tol=1e-12):
                ties += 1
            elif (direction == "lower_is_better" and value < 0) or (
                direction == "higher_is_better" and value > 0
            ):
                wins += 1
            else:
                losses += 1
        comparisons[metric] = {
            "direction": direction,
            "comparable_n": len(delta_values[metric]),
            "market_wins": wins,
            "ties": ties,
            "market_losses": losses,
        }

    aggregate = selection_info["aggregate"]
    unique_market_matches = int(aggregate["unique_match_count"])
    paired_count = len(pairs)
    output_source = dict(SOURCE_PATHS)
    if source:
        output_source.update(dict(source))
    return {
        "schema_version": REVIEW_SCHEMA_VERSION,
        "review_id": REVIEW_ID,
        "market_namespace": MARKET_NAMESPACE,
        "observation_unit": "one unique Market match = one exact control-pair observation",
        "source": output_source,
        "selection_policy": {
            "selector": "pure_market_exact_prospective.select_unique_settlements",
            "aggregate_kernel": "pure_market_exact_prospective.aggregate_settlements",
            "selection_order": list(PAIR_SELECTION_ORDER),
            "post_match_values_used_for_market_version_selection": False,
            "champion_resolution": "exact stored control_pair.prediction_id/source_record_prediction_id only",
            "fuzzy_pairing": False,
            "result_based_version_selection": False,
        },
        "counts": {
            "raw_market_settlement_count": selection_info["raw_market_settlement_count"],
            "raw_market_match_group_count": selection_info["raw_market_match_group_count"],
            "legal_market_settlement_count": selection_info["legal_market_settlement_count"],
            "unique_market_matches": unique_market_matches,
            "superseded_market_version_count": sum(
                int(row["superseded_market_version_count"])
                for row in selection_info["selection_rows"]
            ),
            "exact_control_pair_id_count": exact_control_pair_id_count,
            "exact_champion_pair_resolved_count": exact_champion_pair_resolved_count,
            "paired_unique_match_count": paired_count,
            "rejected_unique_market_match_count": len(rejects),
            "selection_excluded_reason_counts": selection_info["selection_excluded_reason_counts"],
            "reject_reason_counts": dict(sorted(reject_counts.items())),
        },
        "decision": _maturity(paired_count),
        "metrics": {
            "market": market_metrics,
            "champion": champion_metrics,
            "deltas": deltas,
            "paired_comparisons": comparisons,
            "direction_definitions": {
                "lower_is_better": sorted(LOWER_IS_BETTER),
                "higher_is_better": sorted(HIGHER_IS_BETTER),
                "diagnostic_only": sorted(set(METRICS) - LOWER_IS_BETTER - HIGHER_IS_BETTER),
            },
        },
        "market_selection": selection_info["selection_rows"],
        "selection_exclusions": selection_info["selection_exclusions"],
        "pairs": pairs,
        "rejections": rejects,
        "production_action": "STOPPED_BEFORE_PROMOTION",
        "champion_serving_ui_unchanged": True,
        "nowscore_and_model_authority_unchanged": True,
    }

def run_review(
    *,
    market_root: Path = DEFAULT_MARKET_ROOT,
    record_root: Path = DEFAULT_RECORD_ROOT,
) -> dict[str, Any]:
    """Load the persisted lanes and build the deterministic review."""

    market_root = Path(market_root)
    record_root = Path(record_root)
    settlements = load_persisted_settlements(market_root)
    market_predictions = load_persisted_predictions(market_root)
    market_by_id = {str(row.get("prediction_id") or ""): row for row in market_predictions}
    report = build_review(
        settlements,
        market_predictions=market_by_id,
        champion_loader=lambda prediction_id: load_frozen_prediction(prediction_id, record_root),
        source={
            "market_root": _relative_path(market_root),
            "market_predictions": _relative_path(market_root / "predictions"),
            "market_settlements": _relative_path(market_root / "settlements"),
            "champion_predictions": _relative_path(record_root),
        },
    )
    return report

def render_summary(report: Mapping[str, Any]) -> str:
    counts = report.get("counts") if isinstance(report.get("counts"), Mapping) else {}
    decision = report.get("decision") if isinstance(report.get("decision"), Mapping) else {}
    metrics = report.get("metrics") if isinstance(report.get("metrics"), Mapping) else {}
    market = metrics.get("market") if isinstance(metrics.get("market"), Mapping) else {}
    champion = metrics.get("champion") if isinstance(metrics.get("champion"), Mapping) else {}
    deltas = metrics.get("deltas") if isinstance(metrics.get("deltas"), Mapping) else {}
    comparisons = metrics.get("paired_comparisons") if isinstance(metrics.get("paired_comparisons"), Mapping) else {}

    def fmt(value: Any) -> str:
        number = _number(value)
        return "-" if number is None else f"{number:.6f}"

    def summary_value(side: Mapping[str, Any], metric: str) -> str:
        row = side.get(metric) if isinstance(side.get(metric), Mapping) else {}
        return f"{fmt(row.get('mean'))} (n={row.get('n', 0)})"

    lines = [
        "# Pure Market Exact vs Champion paired prospective review",
        "",
        f"- Verdict: `{decision.get('verdict')}`; paired unique matches: `{counts.get('paired_unique_match_count', 0)}`.",
        f"- Counts: raw Market settlements `{counts.get('raw_market_settlement_count', 0)}`, unique Market matches `{counts.get('unique_market_matches', 0)}`, exact Champion pairs resolved `{counts.get('exact_champion_pair_resolved_count', 0)}`, rejected `{counts.get('rejected_unique_market_match_count', 0)}`.",
        f"- Reject counts: `{json.dumps(counts.get('reject_reason_counts') or {}, ensure_ascii=False, sort_keys=True)}`.",
        f"- Selection exclusions: `{json.dumps(counts.get('selection_excluded_reason_counts') or {}, ensure_ascii=False, sort_keys=True)}`.",
        "- No winner or promotion conclusion is emitted; Champion and all serving/model authority remain unchanged.",
        "",
        "## Paired metrics",
        "",
        "| Metric | Market | Champion | Market-Champion delta | 95% CI for delta | W/T/L |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for metric in METRICS:
        delta = deltas.get(metric) if isinstance(deltas.get(metric), Mapping) else {}
        comparison = comparisons.get(metric) if isinstance(comparisons.get(metric), Mapping) else None
        ci = "-"
        if delta.get("ci95_low") is not None:
            ci = f"[{fmt(delta.get('ci95_low'))}, {fmt(delta.get('ci95_high'))}]"
        wtl = "-"
        if comparison is not None:
            wtl = f"{comparison.get('market_wins', 0)}/{comparison.get('ties', 0)}/{comparison.get('market_losses', 0)}"
        lines.append(
            f"| `{metric}` | {summary_value(market, metric)} | {summary_value(champion, metric)} | {fmt(delta.get('mean'))} | {ci} | {wtl} |"
        )

    lines.extend([
        "",
        "## Exact paired IDs",
        "",
        "| match_key | Market prediction | Champion prediction | result |",
        "|---|---|---|---|",
    ])
    for pair in report.get("pairs") or []:
        lines.append(
            f"| `{pair.get('match_key')}` | `{pair.get('market_prediction_id')}` | `{pair.get('champion_prediction_id')}` | `{pair.get('actual_score')}` |"
        )
    if report.get("rejections"):
        lines.extend(["", "## Reject reasons", ""])
        for rejection in report["rejections"]:
            lines.append(
                f"- `{rejection.get('match_key')}` / `{rejection.get('market_prediction_id')}`: `{rejection.get('reason')}`"
            )
    return "\n".join(lines) + "\n"

def write_artifacts(
    report: Mapping[str, Any],
    *,
    output: Path = DEFAULT_OUTPUT,
    summary: Path = DEFAULT_SUMMARY,
) -> dict[str, str]:
    serialized = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    _write_text_if_changed(Path(output), serialized)
    _write_text_if_changed(Path(summary), render_summary(report))
    return {
        "json": _relative_path(Path(output)),
        "summary": _relative_path(Path(summary)),
    }

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--market-root", type=Path, default=DEFAULT_MARKET_ROOT)
    parser.add_argument("--record-root", type=Path, default=DEFAULT_RECORD_ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY)
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args(argv)

    report = run_review(market_root=args.market_root, record_root=args.record_root)
    if not args.no_write:
        write_artifacts(report, output=args.output, summary=args.summary)
    print(render_summary(report), end="")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
