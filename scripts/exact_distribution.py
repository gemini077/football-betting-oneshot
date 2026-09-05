"""Immutable prediction-time Exact Score distribution contracts.

This module records the effective matrix supplied by the deterministic model;
it never regenerates a distribution from lambdas during post-match evaluation.
The current Champion matrix is a finite, normalized 0--12 by 0--12 grid.  The
omitted infinite-support tail is intentionally not represented as an exact
score cell.
"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math
from typing import Any, Mapping


EXACT_DISTRIBUTION_CONTRACT_VERSION = "exact_score_distribution.v1"
EXACT_DISTRIBUTION_MAX_GOALS = 12
EXACT_DISTRIBUTION_CELL_COUNT = (EXACT_DISTRIBUTION_MAX_GOALS + 1) ** 2
EXACT_DISTRIBUTION_NORMALIZATION_TOLERANCE = 1e-12
JC_TOTAL_GOALS_CONTRACT_VERSION = "jc_total_goals.v1"
JC_TOTAL_GOALS_BUCKET_ORDER = ("0", "1", "2", "3", "4", "5", "6", "7+")
JC_TOTAL_GOALS_SELECTION_ORDER = JC_TOTAL_GOALS_BUCKET_ORDER


def canonical_distribution_json(value: Any) -> str:
    """Return the canonical UTF-8 JSON representation used by the contract."""

    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def distribution_content_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_distribution_json(value).encode("utf-8")).hexdigest()


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _goal(value: Any) -> int | None:
    number = _number(value)
    if number is None or int(number) != number:
        return None
    return int(number)


def _validated_cells(raw_cells: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_cells, list):
        raise ValueError("exact distribution effective_matrix must be a list")
    cells: list[dict[str, Any]] = []
    seen: set[tuple[int, int]] = set()
    for raw in raw_cells:
        if not isinstance(raw, Mapping):
            raise ValueError("exact distribution cell must be an object")
        home = _goal(raw.get("home_goals"))
        away = _goal(raw.get("away_goals"))
        probability = _number(raw.get("probability"))
        if (
            home is None
            or away is None
            or probability is None
            or probability < 0
            or not 0 <= home <= EXACT_DISTRIBUTION_MAX_GOALS
            or not 0 <= away <= EXACT_DISTRIBUTION_MAX_GOALS
        ):
            raise ValueError("exact distribution contains an invalid finite-grid cell")
        score = (home, away)
        if score in seen:
            raise ValueError("exact distribution contains a duplicate cell")
        seen.add(score)
        cells.append({"home_goals": home, "away_goals": away, "probability": probability})
    cells.sort(key=lambda cell: (cell["home_goals"], cell["away_goals"]))
    expected = [
        {"home_goals": home, "away_goals": away}
        for home in range(EXACT_DISTRIBUTION_MAX_GOALS + 1)
        for away in range(EXACT_DISTRIBUTION_MAX_GOALS + 1)
    ]
    if len(cells) != EXACT_DISTRIBUTION_CELL_COUNT:
        raise ValueError(
            f"exact distribution must explicitly contain {EXACT_DISTRIBUTION_CELL_COUNT} cells"
        )
    if [
        {"home_goals": cell["home_goals"], "away_goals": cell["away_goals"]}
        for cell in cells
    ] != expected:
        raise ValueError("exact distribution cells do not cover the declared finite grid")
    return cells


def _jc_total_goals_bucket(total_goals: int) -> str:
    return str(total_goals) if total_goals <= 6 else "7+"


def _jc_bucket_semantics() -> list[dict[str, Any]]:
    return [
        {
            "goals": bucket,
            "minimum_total_goals": 7 if bucket == "7+" else int(bucket),
            "maximum_total_goals": None if bucket == "7+" else int(bucket),
        }
        for bucket in JC_TOTAL_GOALS_BUCKET_ORDER
    ]


def build_jc_total_goals_contract(cells: Any) -> dict[str, Any]:
    """Project the official JC eight-way total-goals market from exact cells."""

    validated_cells = _validated_cells(cells)
    probabilities = {bucket: 0.0 for bucket in JC_TOTAL_GOALS_BUCKET_ORDER}
    for cell in validated_cells:
        total_goals = cell["home_goals"] + cell["away_goals"]
        probabilities[_jc_total_goals_bucket(total_goals)] += float(cell["probability"])
    rows = [
        {"goals": bucket, "probability": probabilities[bucket]}
        for bucket in JC_TOTAL_GOALS_BUCKET_ORDER
    ]
    top_selection = max(
        JC_TOTAL_GOALS_BUCKET_ORDER,
        key=lambda bucket: (probabilities[bucket], -JC_TOTAL_GOALS_BUCKET_ORDER.index(bucket)),
    )
    represented_sum = sum(probabilities.values())
    contract: dict[str, Any] = {
        "contract_version": JC_TOTAL_GOALS_CONTRACT_VERSION,
        "status": "FORMAL_JC_TOTAL_GOALS_FROZEN",
        "authority": "frozen_effective_exact_distribution",
        "market_code": "JC_TOTAL_GOALS",
        "market_family": "official_jc_total_goals",
        "market_name": "official JC total goals",
        "selection_order": list(JC_TOTAL_GOALS_BUCKET_ORDER),
        "bucket_semantics": _jc_bucket_semantics(),
        "buckets": rows,
        "probabilities": probabilities,
        "top_selection": top_selection,
        "top_probability": probabilities[top_selection],
        "normalization": {
            "represented_probability_sum": represented_sum,
            "target_probability_sum": 1.0,
            "absolute_error": abs(represented_sum - 1.0),
            "tolerance": EXACT_DISTRIBUTION_NORMALIZATION_TOLERANCE,
            "status": "NORMALIZED_FROM_FROZEN_EXACT_DISTRIBUTION",
        },
        "same_time_official_market_baseline": {
            "status": "NOT_AVAILABLE",
            "probabilities": None,
            "captured_at": None,
            "source": None,
            "reason": (
                "No same-time official eight-way JC total-goals market baseline "
                "is present in frozen prematch evidence."
            ),
            "derived_from_asian_total": False,
        },
        "content_sha256": None,
    }
    content = {key: value for key, value in contract.items() if key != "content_sha256"}
    contract["content_sha256"] = distribution_content_sha256(content)
    validate_jc_total_goals_contract(contract)
    return contract


def validate_jc_total_goals_contract(contract: Mapping[str, Any]) -> None:
    if not isinstance(contract, Mapping):
        raise ValueError("JC total-goals contract must be an object")
    if (
        contract.get("contract_version") != JC_TOTAL_GOALS_CONTRACT_VERSION
        or contract.get("status") != "FORMAL_JC_TOTAL_GOALS_FROZEN"
        or contract.get("authority") != "frozen_effective_exact_distribution"
        or contract.get("market_code") != "JC_TOTAL_GOALS"
        or contract.get("market_family") != "official_jc_total_goals"
    ):
        raise ValueError("JC total-goals frozen contract identity is invalid")
    if contract.get("selection_order") != list(JC_TOTAL_GOALS_BUCKET_ORDER):
        raise ValueError("JC total-goals selection order is invalid")
    if contract.get("bucket_semantics") != _jc_bucket_semantics():
        raise ValueError("JC total-goals bucket semantics are invalid")
    rows = contract.get("buckets")
    if not isinstance(rows, list) or len(rows) != len(JC_TOTAL_GOALS_BUCKET_ORDER):
        raise ValueError("JC total-goals contract must contain eight buckets")
    row_probabilities: dict[str, float] = {}
    for expected, row in zip(JC_TOTAL_GOALS_BUCKET_ORDER, rows):
        if not isinstance(row, Mapping) or row.get("goals") != expected:
            raise ValueError("JC total-goals buckets are out of order or incomplete")
        probability = _number(row.get("probability"))
        if probability is None or probability < 0:
            raise ValueError("JC total-goals bucket probability is invalid")
        row_probabilities[expected] = probability
    declared_probabilities = contract.get("probabilities")
    if (
        not isinstance(declared_probabilities, Mapping)
        or set(declared_probabilities) != set(JC_TOTAL_GOALS_BUCKET_ORDER)
    ):
        raise ValueError("JC total-goals probability map is incomplete")
    for bucket in JC_TOTAL_GOALS_BUCKET_ORDER:
        declared = _number(declared_probabilities.get(bucket))
        if declared is None or abs(declared - row_probabilities[bucket]) > EXACT_DISTRIBUTION_NORMALIZATION_TOLERANCE:
            raise ValueError("JC total-goals probability map does not match buckets")
    represented_sum = sum(row_probabilities.values())
    normalization = contract.get("normalization")
    declared_sum = (
        _number((normalization or {}).get("represented_probability_sum"))
        if isinstance(normalization, Mapping)
        else None
    )
    tolerance = (
        _number((normalization or {}).get("tolerance"))
        if isinstance(normalization, Mapping)
        else None
    )
    if (
        declared_sum is None
        or tolerance is None
        or tolerance <= 0
        or abs(represented_sum - declared_sum) > tolerance
        or abs(represented_sum - 1.0) > tolerance
    ):
        raise ValueError("JC total-goals normalization diagnostics do not match buckets")
    top_selection = max(
        JC_TOTAL_GOALS_BUCKET_ORDER,
        key=lambda bucket: (row_probabilities[bucket], -JC_TOTAL_GOALS_BUCKET_ORDER.index(bucket)),
    )
    if (
        contract.get("top_selection") != top_selection
        or _number(contract.get("top_probability")) != row_probabilities[top_selection]
    ):
        raise ValueError("JC total-goals top selection does not match probabilities")
    baseline = contract.get("same_time_official_market_baseline")
    if (
        not isinstance(baseline, Mapping)
        or baseline.get("status") != "NOT_AVAILABLE"
        or baseline.get("probabilities") is not None
        or baseline.get("captured_at") is not None
        or baseline.get("source") is not None
        or baseline.get("derived_from_asian_total") is not False
    ):
        raise ValueError("JC total-goals same-time market baseline status is invalid")
    supplied_hash = contract.get("content_sha256")
    content = {key: value for key, value in contract.items() if key != "content_sha256"}
    if not isinstance(supplied_hash, str) or supplied_hash != distribution_content_sha256(content):
        raise ValueError("JC total-goals content hash mismatch")


def build_prediction_time_exact_distribution_state(
    matrix: Mapping[tuple[int, int], float],
    *,
    lambda_home: float,
    lambda_away: float,
    rho: float,
    calibration: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Capture the effective matrix at the model/display boundary.

    ``matrix`` must already include every production transformation.  The
    helper only serializes it; it does not call the risk engine or alter any
    probability.
    """

    cells = _validated_cells(
        [
            {
                "home_goals": score[0],
                "away_goals": score[1],
                "probability": probability,
            }
            for score, probability in matrix.items()
        ]
    )
    represented_sum = sum(float(cell["probability"]) for cell in cells)
    if abs(represented_sum - 1.0) > EXACT_DISTRIBUTION_NORMALIZATION_TOLERANCE:
        raise ValueError("effective exact distribution is not normalized")
    return {
        "effective_matrix": cells,
        "probability_state": {
            "lambda_home": float(lambda_home),
            "lambda_away": float(lambda_away),
            "rho": float(rho),
        },
        "production_path": {
            "base_matrix": "risk_engine.dixon_coles_score_matrix(max_goals=12)",
            "effective_stage": "after_approved_calibration_before_top_score_rows",
            "top_score_projection": "automatic_model_core._model_rows(matrix)",
            "calibration": deepcopy(dict(calibration or {})),
        },
    }


def build_exact_distribution_contract(
    state: Mapping[str, Any],
    *,
    model_identity: Mapping[str, Any],
) -> dict[str, Any]:
    """Build the immutable inline contract used by a new formal freeze."""

    if not isinstance(state, Mapping):
        raise ValueError("prediction-time exact distribution state is missing")
    cells = _validated_cells(state.get("effective_matrix"))
    represented_sum = sum(float(cell["probability"]) for cell in cells)
    if abs(represented_sum - 1.0) > EXACT_DISTRIBUTION_NORMALIZATION_TOLERANCE:
        raise ValueError("prediction-time exact distribution is not normalized")
    probability_state = state.get("probability_state")
    production_path = state.get("production_path")
    if not isinstance(probability_state, Mapping) or not isinstance(production_path, Mapping):
        raise ValueError("prediction-time exact distribution provenance is incomplete")
    contract: dict[str, Any] = {
        "contract_version": EXACT_DISTRIBUTION_CONTRACT_VERSION,
        "status": "FORMAL_EXACT_DISTRIBUTION_FROZEN",
        "authority": "prediction_time_effective_exact_matrix",
        "model_identity": deepcopy(dict(model_identity)),
        "probability_state": deepcopy(dict(probability_state)),
        "production_path": deepcopy(dict(production_path)),
        "score_space": {
            "representation": "FINITE_NORMALIZED_GRID",
            "support_semantics": "EXPLICIT_CELLS_ONLY",
            "min_home_goals": 0,
            "min_away_goals": 0,
            "max_home_goals": EXACT_DISTRIBUTION_MAX_GOALS,
            "max_away_goals": EXACT_DISTRIBUTION_MAX_GOALS,
            "cell_count": EXACT_DISTRIBUTION_CELL_COUNT,
            "full_support": False,
            "tail_bucket": False,
            "out_of_support_policy": "OUT_OF_EXPLICIT_SUPPORT",
        },
        "cells": cells,
        "canonicalization": {
            "cell_order": "home_goals_ascending_then_away_goals_ascending",
            "serialization": "UTF-8 JSON sort_keys=true separators=(',', ':') allow_nan=false",
        },
        "normalization": {
            "represented_probability_sum": represented_sum,
            "target_probability_sum": 1.0,
            "absolute_error": abs(represented_sum - 1.0),
            "tolerance": EXACT_DISTRIBUTION_NORMALIZATION_TOLERANCE,
            "status": "NORMALIZED_FINITE_GRID",
        },
        "tail_diagnostic": {
            "status": "UNRESOLVED_NOT_REPRESENTED",
            "omitted_probability_mass": None,
            "tail_cell_present": False,
            "basis": "risk_engine exposes a normalized finite grid; no frozen pre-normalization tail mass is available",
        },
        "jc_total_goals": build_jc_total_goals_contract(cells),
        "content_sha256": None,
    }
    content = {key: value for key, value in contract.items() if key != "content_sha256"}
    contract["content_sha256"] = distribution_content_sha256(content)
    validate_exact_distribution_contract(contract)
    return contract


def validate_exact_distribution_contract(
    contract: Mapping[str, Any],
    *,
    expected_model_identity: Mapping[str, Any] | None = None,
) -> None:
    if not isinstance(contract, Mapping):
        raise ValueError("exact distribution contract must be an object")
    if contract.get("contract_version") != EXACT_DISTRIBUTION_CONTRACT_VERSION:
        raise ValueError("unsupported exact distribution contract version")
    if contract.get("status") != "FORMAL_EXACT_DISTRIBUTION_FROZEN":
        raise ValueError("exact distribution contract is not frozen")
    score_space = contract.get("score_space")
    if not isinstance(score_space, Mapping):
        raise ValueError("exact distribution score space is missing")
    if (
        score_space.get("representation") != "FINITE_NORMALIZED_GRID"
        or score_space.get("support_semantics") != "EXPLICIT_CELLS_ONLY"
        or score_space.get("max_home_goals") != EXACT_DISTRIBUTION_MAX_GOALS
        or score_space.get("max_away_goals") != EXACT_DISTRIBUTION_MAX_GOALS
        or score_space.get("cell_count") != EXACT_DISTRIBUTION_CELL_COUNT
        or score_space.get("full_support") is not False
        or score_space.get("tail_bucket") is not False
    ):
        raise ValueError("exact distribution finite-support semantics are invalid")
    cells = _validated_cells(contract.get("cells"))
    normalization = contract.get("normalization")
    if not isinstance(normalization, Mapping):
        raise ValueError("exact distribution normalization diagnostics are missing")
    represented_sum = sum(float(cell["probability"]) for cell in cells)
    declared_sum = _number(normalization.get("represented_probability_sum"))
    tolerance = _number(normalization.get("tolerance"))
    if (
        declared_sum is None
        or tolerance is None
        or tolerance <= 0
        or abs(represented_sum - declared_sum) > tolerance
        or abs(represented_sum - 1.0) > tolerance
    ):
        raise ValueError("exact distribution normalization diagnostics do not match cells")
    if contract.get("jc_total_goals") is not None:
        validate_jc_total_goals_contract(contract["jc_total_goals"])
    identity = contract.get("model_identity")
    if not isinstance(identity, Mapping):
        raise ValueError("exact distribution model identity is missing")
    for key, expected in (expected_model_identity or {}).items():
        if expected is not None and identity.get(key) != expected:
            raise ValueError(f"exact distribution model identity mismatch: {key}")
    supplied_hash = contract.get("content_sha256")
    content = {key: value for key, value in contract.items() if key != "content_sha256"}
    if not isinstance(supplied_hash, str) or supplied_hash != distribution_content_sha256(content):
        raise ValueError("exact distribution content hash mismatch")


def classify_frozen_exact_score(
    record: Mapping[str, Any],
    home_goals: Any,
    away_goals: Any,
) -> dict[str, Any]:
    """Classify one realized score using only the frozen inline contract."""

    base = {
        "FORMAL_EXACT_DISTRIBUTION_FROZEN": False,
        "FINITE_GRID_EXACTLY_REPRESENTED": False,
        "OUT_OF_EXPLICIT_SUPPORT": False,
        "FORMAL_EXACT_LOG_SCORE_ELIGIBLE": False,
        "formal_exact_distribution_status": "MISSING_FROZEN_EXACT_DISTRIBUTION",
        "authority_status": "RESEARCH_RECONSTRUCTED",
        "probability": None,
        "log_score": None,
        "rank": None,
    }
    contract = record.get("exact_score_distribution") if isinstance(record, Mapping) else None
    if not isinstance(contract, Mapping):
        return base
    expected_identity = {
        "prediction_id": record.get("prediction_id"),
        "model_family": record.get("model_family"),
        "model_core_version": record.get("model_core_version"),
        "release_version": record.get("release_version"),
        "model_source_fingerprint": record.get("model_source_fingerprint"),
        "model_run_fingerprint": record.get("model_run_fingerprint"),
        "calibration_artifact_sha256": record.get("calibration_artifact_sha256"),
        "effective_calibration_fingerprint": record.get("effective_calibration_fingerprint"),
        "input_sha256": record.get("input_sha256"),
    }
    try:
        validate_exact_distribution_contract(
            contract,
            expected_model_identity={key: value for key, value in expected_identity.items() if value is not None},
        )
    except ValueError:
        base["formal_exact_distribution_status"] = "INVALID_FROZEN_EXACT_DISTRIBUTION"
        base["authority_status"] = "FAIL_CLOSED"
        return base
    base.update({
        "FORMAL_EXACT_DISTRIBUTION_FROZEN": True,
        "formal_exact_distribution_status": "FORMAL_EXACT_DISTRIBUTION_FROZEN",
        "authority_status": "FROZEN_PREDICTION_TIME",
    })
    home = _goal(home_goals)
    away = _goal(away_goals)
    maximum = EXACT_DISTRIBUTION_MAX_GOALS
    if home is None or away is None:
        base["formal_exact_distribution_status"] = "INVALID_REALIZED_SCORE"
        return base
    if home < 0 or away < 0 or home > maximum or away > maximum:
        base.update({
            "OUT_OF_EXPLICIT_SUPPORT": True,
            "formal_exact_distribution_status": "OUT_OF_EXPLICIT_SUPPORT",
        })
        return base
    cells = contract["cells"]
    cell = next(
        item
        for item in cells
        if item["home_goals"] == home and item["away_goals"] == away
    )
    probability = float(cell["probability"])
    base["FINITE_GRID_EXACTLY_REPRESENTED"] = True
    base["probability"] = probability
    ranked = sorted(
        cells,
        key=lambda item: (-float(item["probability"]), item["home_goals"], item["away_goals"]),
    )
    base["rank"] = next(
        index + 1
        for index, item in enumerate(ranked)
        if item["home_goals"] == home and item["away_goals"] == away
    )
    if probability <= 0:
        base["formal_exact_distribution_status"] = "NON_POSITIVE_FROZEN_PROBABILITY"
        return base
    base.update({
        "FORMAL_EXACT_LOG_SCORE_ELIGIBLE": True,
        "formal_exact_distribution_status": "FORMAL_EXACT_LOG_SCORE_ELIGIBLE",
        "log_score": -math.log(probability),
    })
    return base


def classify_frozen_jc_total_goals(
    record: Mapping[str, Any],
    home_goals: Any,
    away_goals: Any,
) -> dict[str, Any]:
    """Classify a realized 90-minute score using only frozen JC truth."""

    base = {
        "FORMAL_JC_TOTAL_GOALS_FROZEN": False,
        "JC_TOTAL_GOALS_BUCKET_EXACTLY_REPRESENTED": False,
        "jc_total_goals_status": "MISSING_FROZEN_JC_TOTAL_GOALS",
        "authority_status": "RESEARCH_RECONSTRUCTED",
        "actual_jc_total_goals_bucket": None,
        "jc_total_goals_probability": None,
        "jc_total_goals_top_selection": None,
        "jc_total_goals_top_selection_hit": None,
        "same_time_official_market_baseline_status": None,
    }
    exact_contract = record.get("exact_score_distribution") if isinstance(record, Mapping) else None
    if not isinstance(exact_contract, Mapping):
        return base
    expected_identity = {
        "prediction_id": record.get("prediction_id"),
        "model_family": record.get("model_family"),
        "model_core_version": record.get("model_core_version"),
        "release_version": record.get("release_version"),
        "model_source_fingerprint": record.get("model_source_fingerprint"),
        "model_run_fingerprint": record.get("model_run_fingerprint"),
        "calibration_artifact_sha256": record.get("calibration_artifact_sha256"),
        "effective_calibration_fingerprint": record.get("effective_calibration_fingerprint"),
        "input_sha256": record.get("input_sha256"),
    }
    try:
        validate_exact_distribution_contract(
            exact_contract,
            expected_model_identity={key: value for key, value in expected_identity.items() if value is not None},
        )
    except ValueError:
        base["jc_total_goals_status"] = "INVALID_FROZEN_JC_TOTAL_GOALS"
        base["authority_status"] = "FAIL_CLOSED"
        return base
    jc_contract = exact_contract.get("jc_total_goals")
    if not isinstance(jc_contract, Mapping):
        return base
    home = _goal(home_goals)
    away = _goal(away_goals)
    if home is None or away is None or home < 0 or away < 0:
        base["jc_total_goals_status"] = "INVALID_REALIZED_SCORE"
        return base
    bucket = _jc_total_goals_bucket(home + away)
    probabilities = jc_contract["probabilities"]
    base.update({
        "FORMAL_JC_TOTAL_GOALS_FROZEN": True,
        "JC_TOTAL_GOALS_BUCKET_EXACTLY_REPRESENTED": True,
        "jc_total_goals_status": "FORMAL_JC_TOTAL_GOALS_FROZEN",
        "authority_status": "FROZEN_PREDICTION_TIME",
        "actual_jc_total_goals_bucket": bucket,
        "jc_total_goals_probability": float(probabilities[bucket]),
        "jc_total_goals_top_selection": jc_contract["top_selection"],
        "jc_total_goals_top_selection_hit": jc_contract["top_selection"] == bucket,
        "same_time_official_market_baseline_status": (
            jc_contract["same_time_official_market_baseline"]["status"]
        ),
    })
    return base
