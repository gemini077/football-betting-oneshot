#!/usr/bin/env python3
"""Offline falsification for market-calibrated exact-score lambdas.

This module never writes production predictions or frozen history. It reuses
the pinned PRED-TRUST cohort, derives one bounded challenger from immutable
pre-match market snapshots, and evaluates outcomes only after generation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from collections import Counter
from pathlib import Path
from statistics import fmean, median
from typing import Any, Iterable, Mapping

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from automatic_model_core import (  # noqa: E402
    _deep_snapshot,
    _market_share,
    _total_line_pricing,
)
from prediction_trust_2_replay import (  # noqa: E402
    ACCEPTED_WRITEBACK_COMMIT,
    DEFAULT_AUDIT,
    DEFAULT_MANIFEST,
    ROOT,
    _evaluate_candidate,
    _form_and_market_inputs,
    _metric_value,
    _prediction_record_hash,
    _prepare_row,
    build_score_matrix,
)
from prediction_trust_3_replay import derive_market_side_only_lambdas  # noqa: E402
from prediction_trust_audit import _is_formally_eligible, _load_prediction_records  # noqa: E402


MILESTONE = "EXACT-SCORE-MARKET-CALIBRATED-LAMBDA-SHADOW-1"
CANDIDATE_ID = "market_calibrated_lambda_v1"
POWER_ID = "market_calibrated_lambda_v1_power_sensitivity"
SHIN_ID = "market_calibrated_lambda_v1_shin_sensitivity"
MIN_VERIFIED_COVERAGE = 50
OUTCOMES = ("home", "draw", "away")


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _canonical_json_sha256(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _load_portable_pinned_records(
    root: Path,
    manifest_path: Path,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Load the pinned cohort with cross-platform content integrity.

    The legacy manifest also stores a raw snapshot-file SHA256 generated from
    a Windows working tree. Git checkout line-ending normalization makes that
    raw byte digest non-portable even when the Git blob is unchanged. For this
    research replay we keep the record-content hash guard and additionally
    recompute the canonical JSON digest of snapshot["input"], matching it
    against both snapshot and frozen prediction metadata.
    """

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    entries = manifest.get("selected_records") or []
    if manifest.get("accepted_writeback_commit") != ACCEPTED_WRITEBACK_COMMIT:
        raise ValueError("cohort manifest accepted write-back pin mismatch")
    if len(entries) != 217 or manifest.get("selected_match_count") != 217:
        raise ValueError("market-calibrated replay requires the pinned 217-match cohort")

    raw = {
        str(record.get("prediction_id")): record
        for record in _load_prediction_records(root)
    }
    selected: list[dict[str, Any]] = []
    for entry in entries:
        prediction_id = str(entry.get("prediction_id") or "")
        record = raw.get(prediction_id)
        if record is None:
            raise ValueError(f"pinned prediction is missing: {prediction_id}")
        if _prediction_record_hash(record) != entry.get("record_sha256"):
            raise ValueError(f"pinned prediction content changed: {prediction_id}")

        snapshot_ref = str(entry.get("input_snapshot_ref") or "")
        snapshot_path = root / snapshot_ref
        if not snapshot_path.is_file():
            raise ValueError(f"pinned input snapshot is missing: {prediction_id}")
        snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
        canonical_input = snapshot.get("input")
        if not isinstance(canonical_input, dict):
            raise ValueError(f"pinned input snapshot has no canonical input: {prediction_id}")
        recomputed = _canonical_json_sha256(canonical_input)
        snapshot_digest = str(
            snapshot.get("canonical_model_input_sha256")
            or snapshot.get("canonical_input_sha256")
            or ""
        )
        record_digest = str(
            record.get("canonical_model_input_sha256")
            or record.get("input_sha256")
            or ""
        )
        embedded_digest = str(
            (record.get("input_snapshot") or {}).get("canonical_model_input_sha256")
            or (record.get("input_snapshot") or {}).get("canonical_input_sha256")
            or ""
        )
        if not snapshot_digest or recomputed != snapshot_digest:
            raise ValueError(f"snapshot canonical input digest mismatch: {prediction_id}")
        if record_digest != snapshot_digest or embedded_digest != snapshot_digest:
            raise ValueError(f"snapshot/record canonical digest mismatch: {prediction_id}")
        if str((record.get("input_snapshot") or {}).get("snapshot_id") or "") != str(
            snapshot.get("snapshot_id") or ""
        ):
            raise ValueError(f"snapshot identity mismatch: {prediction_id}")
        if str(record.get("source_cutoff_at") or "") != str(snapshot.get("source_cutoff_at") or ""):
            raise ValueError(f"snapshot cutoff mismatch: {prediction_id}")
        if not _is_formally_eligible(record):
            raise ValueError(f"pinned prediction is no longer formally eligible: {prediction_id}")
        selected.append(dict(record))

    match_ids = {
        str(record.get("match_id") or record.get("match_key") or "")
        for record in selected
    }
    if len(match_ids) != len(selected):
        raise ValueError("pinned selected cohort contains duplicate match identities")
    return selected, manifest


def _devig_multiplicative(odds: Iterable[float]) -> list[float]:
    prices = [float(value) for value in odds]
    if len(prices) < 2 or any(not math.isfinite(value) or value <= 1.0 for value in prices):
        raise ValueError("decimal odds must contain at least two finite prices > 1")
    inverse = [1.0 / value for value in prices]
    total = sum(inverse)
    return [value / total for value in inverse]


def _devig_power(odds: Iterable[float]) -> list[float]:
    prices = [float(value) for value in odds]
    if len(prices) < 2 or any(not math.isfinite(value) or value <= 1.0 for value in prices):
        raise ValueError("decimal odds must contain at least two finite prices > 1")
    implied = [1.0 / value for value in prices]
    low, high = 0.01, 20.0
    for _ in range(100):
        exponent = (low + high) / 2.0
        total = sum(value**exponent for value in implied)
        if total > 1.0:
            low = exponent
        else:
            high = exponent
    exponent = (low + high) / 2.0
    probabilities = [value**exponent for value in implied]
    normalizer = sum(probabilities)
    return [value / normalizer for value in probabilities]


def _devig_shin(odds: Iterable[float]) -> list[float]:
    prices = [float(value) for value in odds]
    if len(prices) < 2 or any(not math.isfinite(value) or value <= 1.0 for value in prices):
        raise ValueError("decimal odds must contain at least two finite prices > 1")
    implied = [1.0 / value for value in prices]
    booksum = sum(implied)
    if len(prices) == 2:
        # For two outcomes Shin is analytically equivalent to additive devig.
        margin = booksum - 1.0
        probabilities = [value - margin / 2.0 for value in implied]
        if any(value <= 0 for value in probabilities):
            return _devig_multiplicative(prices)
        normalizer = sum(probabilities)
        return [value / normalizer for value in probabilities]

    def probabilities(z: float) -> list[float]:
        denominator = 2.0 * (1.0 - z)
        return [
            (
                math.sqrt(
                    z * z
                    + 4.0 * (1.0 - z) * value * value / booksum
                )
                - z
            )
            / denominator
            for value in implied
        ]

    low, high = 0.0, 1.0 - 1e-12
    if sum(probabilities(low)) < 1.0:
        return _devig_multiplicative(prices)
    for _ in range(100):
        z = (low + high) / 2.0
        if sum(probabilities(z)) > 1.0:
            low = z
        else:
            high = z
    output = probabilities((low + high) / 2.0)
    normalizer = sum(output)
    return [value / normalizer for value in output]


def devig(odds: Iterable[float], method: str = "multiplicative") -> list[float]:
    if method == "multiplicative":
        return _devig_multiplicative(odds)
    if method == "power":
        return _devig_power(odds)
    if method == "shin":
        return _devig_shin(odds)
    raise ValueError(f"unknown devig method: {method}")


def _valid_1x2_rows(deep: Mapping[str, Any]) -> list[dict[str, Any]]:
    valid = []
    for row in (deep.get("ouzhi") or {}).get("bookmakers") or []:
        if not isinstance(row, dict):
            continue
        current = row.get("spf_current") or {}
        prices = [_number(current.get(key)) for key in OUTCOMES]
        if all(value is not None and value > 1.0 for value in prices):
            valid.append(row)
    return valid


def consensus_1x2(
    deep: Mapping[str, Any],
    *,
    method: str = "multiplicative",
) -> dict[str, float]:
    rows = _valid_1x2_rows(deep)
    if not rows:
        raise ValueError("missing usable 1X2 current odds")
    probabilities = []
    for row in rows:
        current = row["spf_current"]
        probabilities.append(devig([current[key] for key in OUTCOMES], method))
    return {
        key: fmean(row[index] for row in probabilities)
        for index, key in enumerate(OUTCOMES)
    }


def _valid_total_quotes(deep: Mapping[str, Any]) -> list[dict[str, float]]:
    quotes = []
    for row in (deep.get("daxiao") or {}).get("companies") or []:
        if not isinstance(row, dict):
            continue
        line = _number(row.get("current_line"))
        over_water = _number(row.get("current_over_water"))
        under_water = _number(row.get("current_under_water"))
        if (
            line is None
            or not 1.0 <= line <= 5.0
            or over_water is None
            or under_water is None
        ):
            continue
        over_odds = 1.0 + over_water
        under_odds = 1.0 + under_water
        if over_odds <= 1.0 or under_odds <= 1.0:
            continue
        quotes.append(
            {
                "line": round(line * 4.0) / 4.0,
                "over_odds": over_odds,
                "under_odds": under_odds,
            }
        )
    return quotes


def _effective_over_probability(expected_goals: float, line: float) -> float:
    priced = _total_line_pricing(float(expected_goals), float(line))
    over = priced["over"]
    win = float(over["win_equivalent_probability"])
    loss = float(over["loss_equivalent_probability"])
    denominator = win + loss
    if denominator <= 0:
        raise ValueError("Asian total line has no win/loss mass")
    return win / denominator


def solve_total_lambda(
    *,
    line: float,
    over_odds: float,
    under_odds: float,
    devig_method: str = "multiplicative",
    low: float = 0.5,
    high: float = 6.5,
) -> float:
    target_over = devig([over_odds, under_odds], devig_method)[0]
    low_probability = _effective_over_probability(low, line)
    high_probability = _effective_over_probability(high, line)
    if not low_probability <= target_over <= high_probability:
        raise ValueError("market total target is outside solver bounds")
    left, right = low, high
    for _ in range(70):
        middle = (left + right) / 2.0
        if _effective_over_probability(middle, line) < target_over:
            left = middle
        else:
            right = middle
    return (left + right) / 2.0


def market_implied_total(
    deep: Mapping[str, Any],
    *,
    devig_method: str = "multiplicative",
) -> dict[str, Any]:
    quotes = _valid_total_quotes(deep)
    if not quotes:
        raise ValueError("missing usable O/U line plus two-sided current prices")
    per_line: dict[float, list[float]] = {}
    failures = 0
    for quote in quotes:
        try:
            implied = solve_total_lambda(
                line=quote["line"],
                over_odds=quote["over_odds"],
                under_odds=quote["under_odds"],
                devig_method=devig_method,
            )
        except ValueError:
            failures += 1
            continue
        per_line.setdefault(quote["line"], []).append(implied)
    if not per_line:
        raise ValueError("all usable O/U quotes failed total-lambda solving")
    line_consensus = {
        line: median(values)
        for line, values in sorted(per_line.items())
    }
    return {
        "total": median(line_consensus.values()),
        "quote_count": len(quotes),
        "solved_quote_count": sum(len(values) for values in per_line.values()),
        "failed_quote_count": failures,
        "line_count": len(line_consensus),
        "line_consensus": line_consensus,
    }


def derive_market_calibrated_lambdas(
    context: Mapping[str, Any],
    *,
    one_x_two_devig: str = "multiplicative",
) -> dict[str, Any]:
    deep = _deep_snapshot(dict(context))
    probabilities = consensus_1x2(deep, method=one_x_two_devig)
    total = market_implied_total(deep, devig_method="multiplicative")
    share = _market_share(float(total["total"]), probabilities)
    return {
        "candidate_id": CANDIDATE_ID,
        "one_x_two_devig": one_x_two_devig,
        "total_devig": "multiplicative",
        "rho": 0.0,
        "total": float(total["total"]),
        "share": float(share),
        "lambda_home": float(total["total"]) * float(share),
        "lambda_away": float(total["total"]) * (1.0 - float(share)),
        "market_probabilities": probabilities,
        "total_diagnostics": total,
    }


def _strip_rows(metrics: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in metrics.items()
        if key != "evaluated_rows"
    }


def _summary_table(metrics: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    specs = (
        ("Exact Score Top1", "exact_score.top1_hit_rate"),
        ("Exact Score Top3", "exact_score.top3_hit_rate"),
        ("Exact Score NLL", "exact_score.nll"),
        ("Actual score mean probability", "exact_score.mean_probability_assigned_to_actual_score"),
        ("1X2 accuracy", "one_x_two.accuracy"),
        ("1X2 Brier", "one_x_two.brier"),
        ("1X2 LogLoss", "one_x_two.log_loss"),
        ("1X2 ECE", "one_x_two.ece"),
        ("O/U 2.5 accuracy", "ou_2_5.accuracy"),
        ("O/U 2.5 Brier", "ou_2_5.brier"),
        ("O/U 2.5 ECE", "ou_2_5.ece"),
        ("BTTS accuracy", "btts.accuracy"),
        ("BTTS Brier", "btts.brier"),
        ("1-1 Top1 share", "distribution.one_one_top1_share"),
        ("Top1 support size", "distribution.top1_support_size"),
        ("Gap <0.5 share", "distribution.gap_lt_0_5_share"),
        ("Median absolute lambda gap", "distribution.absolute_gap.P50"),
        ("Median lambda total", "distribution.lambda_total.P50"),
    )
    candidate_order = (
        "champion",
        "challenger_c",
        CANDIDATE_ID,
        POWER_ID,
        SHIN_ID,
    )
    return [
        {
            "metric": label,
            **{
                candidate: _metric_value(metrics[candidate], path)
                for candidate in candidate_order
            },
        }
        for label, path in specs
    ]


def _decision(metrics: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    champion = metrics["champion"]
    challenger_c = metrics["challenger_c"]
    primary = metrics[CANDIDATE_ID]
    power = metrics[POWER_ID]
    shin = metrics[SHIN_ID]

    best_existing_nll = min(
        _metric_value(champion, "exact_score.nll"),
        _metric_value(challenger_c, "exact_score.nll"),
    )
    checks = {
        "exact_score_nll_beats_champion_and_c": (
            _metric_value(primary, "exact_score.nll") < best_existing_nll
        ),
        "ou_brier_improves_vs_champion": (
            _metric_value(primary, "ou_2_5.brier")
            < _metric_value(champion, "ou_2_5.brier")
        ),
        "top3_not_materially_worse": (
            _metric_value(primary, "exact_score.top3_hit_rate")
            >= _metric_value(champion, "exact_score.top3_hit_rate") - 0.01
        ),
        "1x2_brier_not_materially_worse": (
            _metric_value(primary, "one_x_two.brier")
            <= _metric_value(champion, "one_x_two.brier") + 0.01
        ),
        "1x2_logloss_not_materially_worse": (
            _metric_value(primary, "one_x_two.log_loss")
            <= _metric_value(champion, "one_x_two.log_loss") + 0.02
        ),
        "power_sensitivity_keeps_nll_direction": (
            _metric_value(power, "exact_score.nll")
            < _metric_value(champion, "exact_score.nll")
        ),
        "shin_sensitivity_keeps_nll_direction": (
            _metric_value(shin, "exact_score.nll")
            < _metric_value(champion, "exact_score.nll")
        ),
    }
    survives = all(checks.values())
    return {
        "status": "EXPERIMENT_SURVIVES" if survives else "REJECTED",
        "checks": checks,
        "promotion": "NO",
        "production_changes": "NO",
        "next_step": (
            "prospective shadow only"
            if survives
            else "stop D; diagnose which probability dimension failed before another challenger"
        ),
    }


def run(
    *,
    root: Path = ROOT,
    manifest_path: Path = DEFAULT_MANIFEST,
    audit_path: Path = DEFAULT_AUDIT,
) -> dict[str, Any]:
    records, manifest = _load_portable_pinned_records(root, manifest_path)
    generation_rows: dict[str, list[dict[str, Any]]] = {
        "champion": [],
        "challenger_c": [],
        CANDIDATE_ID: [],
        POWER_ID: [],
        SHIN_ID: [],
    }
    eligible_ids: set[str] = set()
    coverage_failures: Counter[str] = Counter()
    total_quote_counts: list[int] = []
    total_line_counts: list[int] = []

    # Generation phase: no actual-result object is loaded or consulted here.
    for record in records:
        prediction_id = str(record["prediction_id"])
        snapshot_ref = str(
            record.get("input_snapshot_ref")
            or record.get("model_input_snapshot_ref")
            or ""
        )
        try:
            snapshot = json.loads((root / snapshot_ref).read_text(encoding="utf-8"))
            context = snapshot.get("input") or {}
            deep = _deep_snapshot(dict(context))
            if not _valid_1x2_rows(deep):
                coverage_failures["MISSING_1X2_CURRENT_ODDS"] += 1
                continue
            if not _valid_total_quotes(deep):
                coverage_failures["MISSING_TOTAL_TWO_SIDED_PRICE"] += 1
                continue
            inputs = _form_and_market_inputs(context)
            primary = derive_market_calibrated_lambdas(
                context,
                one_x_two_devig="multiplicative",
            )
            power = derive_market_calibrated_lambdas(
                context,
                one_x_two_devig="power",
            )
            shin = derive_market_calibrated_lambdas(
                context,
                one_x_two_devig="shin",
            )
            challenger_c = derive_market_side_only_lambdas(
                form_home=inputs["form_home"],
                form_away=inputs["form_away"],
                market_total=inputs["market_total"],
                market_share=inputs["market_share"],
                form_total=inputs["form_total"],
            )
            champion = {
                "lambda_home": float(record["lambda_home"]),
                "lambda_away": float(record["lambda_away"]),
            }
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
            coverage_failures["GENERATION_OR_SOLVER_FAILED"] += 1
            continue

        candidates = {
            "champion": champion,
            "challenger_c": challenger_c,
            CANDIDATE_ID: primary,
            POWER_ID: {**power, "candidate_id": POWER_ID},
            SHIN_ID: {**shin, "candidate_id": SHIN_ID},
        }
        for candidate_id, candidate in candidates.items():
            matrix = build_score_matrix(
                float(candidate["lambda_home"]),
                float(candidate["lambda_away"]),
            )
            generation_rows[candidate_id].append(
                _prepare_row(record, record, candidate, matrix)
            )
        eligible_ids.add(prediction_id)
        total_quote_counts.append(int(primary["total_diagnostics"]["solved_quote_count"]))
        total_line_counts.append(int(primary["total_diagnostics"]["line_count"]))

    # Evaluation phase starts only after all candidate generation is complete.
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    verified_rows = (
        audit.get("prospective_evaluation", {}).get("evaluated_rows") or []
    )
    verified_by_id = {
        str(row["prediction_id"]): row
        for row in verified_rows
        if row.get("prediction_id")
    }
    verified_eligible_ids = eligible_ids & set(verified_by_id)
    if len(verified_eligible_ids) < MIN_VERIFIED_COVERAGE:
        return {
            "schema_version": "market_calibrated_lambda_shadow.v1",
            "milestone": MILESTONE,
            "status": "DATA_COVERAGE_INSUFFICIENT",
            "coverage": {
                "pinned_unique": len(records),
                "pinned_verified": len(verified_by_id),
                "eligible_unique": len(eligible_ids),
                "verified_eligible_unique": len(verified_eligible_ids),
                "minimum_verified_required": MIN_VERIFIED_COVERAGE,
                "failure_reasons": dict(sorted(coverage_failures.items())),
            },
            "production_changes": "NO",
            "promotion": "NO",
        }

    filtered_rows = {
        candidate_id: [
            row for row in rows
            if row["prediction_id"] in verified_eligible_ids
        ]
        for candidate_id, rows in generation_rows.items()
    }
    filtered_verified = {
        prediction_id: verified_by_id[prediction_id]
        for prediction_id in verified_eligible_ids
    }
    metrics = {
        candidate_id: _strip_rows(
            _evaluate_candidate(rows, filtered_verified)
        )
        for candidate_id, rows in filtered_rows.items()
    }
    return {
        "schema_version": "market_calibrated_lambda_shadow.v1",
        "milestone": MILESTONE,
        "status": "READY_FOR_ACCEPTANCE",
        "source": {
            "pinned_manifest": str(manifest_path.relative_to(root)),
            "pinned_selection_digest": manifest["selected_prediction_digest"],
            "results_loaded_after_generation": True,
            "postmatch_input_used_for_generation": False,
            "snapshot_integrity": "record canonical hash + recomputed canonical snapshot-input SHA256",
            "legacy_raw_snapshot_sha256": "not used because Windows/Git line-ending normalization makes it non-portable",
        },
        "coverage": {
            "pinned_unique": len(records),
            "pinned_verified": len(verified_by_id),
            "eligible_unique": len(eligible_ids),
            "verified_eligible_unique": len(verified_eligible_ids),
            "minimum_verified_required": MIN_VERIFIED_COVERAGE,
            "failure_reasons": dict(sorted(coverage_failures.items())),
            "median_solved_total_quotes": median(total_quote_counts) if total_quote_counts else None,
            "median_total_line_count": median(total_line_counts) if total_line_counts else None,
        },
        "candidate_contract": {
            "primary": CANDIDATE_ID,
            "rho": 0.0,
            "total": "O/U line + two-sided current price -> de-vig -> Asian-total implied lambda; robust median across lines/books",
            "side": "de-vigged 1X2 consensus -> existing outcome-marginal market_share fit at solved total",
            "asian_handicap": "diagnostic only; not an optimization input",
            "sensitivity": ["power", "shin"],
            "production_enabled": False,
            "auto_promote": False,
        },
        "metrics": metrics,
        "comparison_table": _summary_table(metrics),
        "decision": _decision(metrics),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = run()
    payload = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
