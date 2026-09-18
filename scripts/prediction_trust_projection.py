#!/usr/bin/env python3
"""Build the current Champion trust projection without changing source truth."""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import sys
from typing import Any, Iterable, Mapping


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = Path(__file__).resolve().parent
for path in (ROOT, SCRIPT_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from evaluation_kernel import (  # noqa: E402
    evaluate_prediction_common,
    expected_goals,
    parse_score_pair,
    ranked_probability_score,
)
from model_governance import load_frozen_prediction  # noqa: E402
from prediction_exclusions import excluded_prediction_ids  # noqa: E402
from prediction_trust_audit import build_unique_match_cohort  # noqa: E402
from production_health_watch import select_current_serving_predictions  # noqa: E402
from prematch_versioning import _identity as record_identity  # noqa: E402
from prospective_settlement import is_formally_eligible  # noqa: E402
from pure_market_exact_paired_review import build_review  # noqa: E402
from pure_market_exact_prospective import (  # noqa: E402
    load_persisted_predictions,
    load_persisted_settlements,
)


TRUST_ID = "CURRENT-CHAMPION-TRUST-PROJECTION-R37"
SCHEMA_VERSION = "current_champion_trust.v1"
PUBLIC_SCHEMA_VERSION = "current_champion_trust.public.v1"
RESULT_SCOPE = "regulation_90m_plus_stoppage"
DEFAULT_OUTPUT = ROOT / "data" / "prediction_quality" / "current_champion_trust.json"
DEFAULT_SUMMARY = ROOT / "data" / "prediction_quality" / "current_champion_trust.md"
DEFAULT_RUNTIME = ROOT / "data" / "product_runtime" / "latest_cycle.json"
DEFAULT_PREDICTION_ROOT = ROOT / "data" / "model_governance" / "predictions"
DEFAULT_EXCLUSION_ROOT = ROOT / "data" / "model_governance" / "prediction_exclusions"
DEFAULT_LEDGER = ROOT / "data" / "prospective" / "ledger.jsonl"
DEFAULT_MARKET_ROOT = ROOT / "data" / "prediction_quality" / "pure_market_exact_prospective_1"
OUTCOMES = ("home", "draw", "away")
CALIBRATION_BANDS = (
    (0.0, 0.2),
    (0.2, 0.4),
    (0.4, 0.6),
    (0.6, 0.8),
    (0.8, 1.0),
)


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _text(value: Any) -> str:
    return str(value or "").strip()


def _timestamp(value: Any) -> datetime | None:
    text = _text(value)
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _iso(value: Any) -> str | None:
    parsed = _timestamp(value)
    return parsed.isoformat().replace("+00:00", "Z") if parsed else None


def _rounded(value: Any) -> float | None:
    number = _number(value)
    return round(number, 6) if number is not None else None


def _rate(count: int, total: int) -> float | None:
    return round(count / total, 6) if total else None


def _metric_summary(values: Iterable[Any]) -> dict[str, Any]:
    numbers = [float(value) for value in values if _number(value) is not None]
    return {"n": len(numbers), "mean": _rounded(sum(numbers) / len(numbers)) if numbers else None}


def _hit_summary(values: Iterable[Any]) -> dict[str, Any]:
    hits = [bool(value) for value in values if isinstance(value, (bool, int, float))]
    hit_count = sum(hits)
    return {"n": len(hits), "hits": hit_count, "rate": _rate(hit_count, len(hits))}


def _identity(record: Mapping[str, Any]) -> dict[str, Any]:
    return record_identity(dict(record))


def _source_digest(records: Iterable[Mapping[str, Any]]) -> str:
    digest = hashlib.sha256()
    for record in sorted(records, key=lambda row: _text(row.get("prediction_id"))):
        digest.update(_text(record.get("prediction_id")).encode("utf-8"))
        digest.update(b"\0")
        digest.update(_text(record.get("prediction_sha256")).encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def _file_digest(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError:
        return None
    return digest.hexdigest()


def _tree_digest(path: Path) -> str | None:
    if not path.is_dir():
        return None
    digest = hashlib.sha256()
    try:
        files = sorted(item for item in path.rglob("*") if item.is_file())
        for item in files:
            digest.update(item.relative_to(path).as_posix().encode("utf-8"))
            digest.update(b"\0")
            file_digest = _file_digest(item)
            if file_digest:
                digest.update(file_digest.encode("ascii"))
            digest.update(b"\n")
    except OSError:
        return None
    return digest.hexdigest()


def _read_json(path: Path, default: Any) -> Any:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return default
    return value


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            value = json.loads(line)
            if isinstance(value, dict):
                rows.append(value)
    except (OSError, UnicodeError, json.JSONDecodeError):
        return rows
    return rows


def _load_records(prediction_root: Path) -> tuple[list[dict[str, Any]], dict[str, int]]:
    records: list[dict[str, Any]] = []
    invalid = 0
    if prediction_root.is_dir():
        for path in sorted(prediction_root.glob("*.json")):
            try:
                record = load_frozen_prediction(path.stem, prediction_root)
            except (OSError, TypeError, ValueError, json.JSONDecodeError):
                record = None
            if isinstance(record, dict):
                records.append(record)
            else:
                invalid += 1
    return records, {"loaded": len(records), "invalid": invalid}


def _eligible(record: Mapping[str, Any]) -> bool:
    try:
        return bool(is_formally_eligible(dict(record)))
    except (KeyError, TypeError, ValueError):
        return False


def _result_for_row(row: Mapping[str, Any], record: Mapping[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    actual = row.get("actual")
    pair = parse_score_pair(actual)
    if pair is None:
        return None, "RESULT_SCORE_MISSING_OR_INVALID"
    verified_at = _timestamp(row.get("result_verified_at"))
    identity = _identity(record)
    kickoff = _timestamp(identity.get("kickoff_at"))
    if verified_at is None:
        return None, "RESULT_VERIFICATION_TIMESTAMP_MISSING"
    if kickoff is None or verified_at <= kickoff:
        return None, "RESULT_VERIFIED_BEFORE_KICKOFF"
    home, away = pair
    result = {
        "status": "result_verified",
        "scope": RESULT_SCOPE,
        "score_90m": f"{home}-{away}",
        "verified_at": verified_at.isoformat(),
        "source": row.get("result_source"),
    }
    return result, None


def _settlement_index(
    rows: Iterable[Mapping[str, Any]],
) -> tuple[dict[str, dict[str, Any]], int, int, set[str]]:
    by_id: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        if not isinstance(row, Mapping) or row.get("formal_prospective_eligible") is not True:
            continue
        prediction_id = _text(row.get("prediction_id"))
        if prediction_id:
            by_id.setdefault(prediction_id, []).append(dict(row))
    duplicate_count = sum(max(0, len(values) - 1) for values in by_id.values())
    conflict_count = 0
    conflict_ids: set[str] = set()
    selected: dict[str, dict[str, Any]] = {}
    for prediction_id, values in by_id.items():
        signatures = {
            json.dumps(value.get("actual"), ensure_ascii=False, sort_keys=True)
            for value in values
        }
        if len(signatures) > 1:
            conflict_count += 1
            conflict_ids.add(prediction_id)
        selected[prediction_id] = values[0]
    return selected, duplicate_count, conflict_count, conflict_ids


def _calibration(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    output: dict[str, list[dict[str, Any]]] = {}
    for outcome in OUTCOMES:
        bands: list[dict[str, Any]] = []
        for index, (lower, upper) in enumerate(CALIBRATION_BANDS):
            values = []
            for row in rows:
                probability = _number((row.get("probabilities") or {}).get(outcome))
                if probability is None or not 0.0 <= probability <= 1.0:
                    continue
                in_band = (
                    lower <= probability <= upper
                    if index == len(CALIBRATION_BANDS) - 1
                    else lower <= probability < upper
                )
                if in_band:
                    values.append((probability, row.get("actual_outcome") == outcome))
            n = len(values)
            mean_predicted = sum(value for value, _ in values) / n if n else None
            observed = sum(bool(hit) for _, hit in values) / n if n else None
            mean_predicted = _rounded(mean_predicted)
            observed = _rounded(observed)
            bands.append({
                "lower_bound": lower,
                "upper_bound": upper,
                "n": n,
                "mean_predicted": mean_predicted,
                "observed_frequency": observed,
                "gap": _rounded(observed - mean_predicted) if mean_predicted is not None and observed is not None else None,
            })
        output[outcome] = bands
    return output


def _freshness(records: list[Mapping[str, Any]], rows: list[dict[str, Any]]) -> dict[str, Any]:
    def first_last(values: Iterable[Any]) -> tuple[str | None, str | None]:
        parsed = sorted(value for value in (_timestamp(item) for item in values) if value)
        if not parsed:
            return None, None
        return parsed[0].isoformat().replace("+00:00", "Z"), parsed[-1].isoformat().replace("+00:00", "Z")

    first_prediction, last_prediction = first_last(record.get("prediction_created_at") for record in records)
    first_kickoff, last_kickoff = first_last(_identity(record).get("kickoff_at") for record in records)
    verified = [_timestamp(row.get("verified_at")) for row in rows]
    settled_through = max((value for value in verified if value), default=None)
    return {
        "first_prediction_at": first_prediction,
        "last_prediction_at": last_prediction,
        "first_kickoff_at": first_kickoff,
        "last_kickoff_at": last_kickoff,
        "settled_through": settled_through.isoformat().replace("+00:00", "Z") if settled_through else None,
    }


def _observation(record: Mapping[str, Any], *, status: str, reason: str | None = None) -> dict[str, Any]:
    identity = _identity(record)
    return {
        "prediction_id": _text(record.get("prediction_id")),
        "match_key": _text(identity.get("match_key")) or None,
        "match_id": _text(identity.get("match_id")) or None,
        "home": _text(identity.get("home")) or None,
        "away": _text(identity.get("away")) or None,
        "kickoff_at": _iso(identity.get("kickoff_at")),
        "prediction_created_at": _iso(record.get("prediction_created_at")),
        "model_run_fingerprint": _text(record.get("model_run_fingerprint")) or None,
        "status": status,
        "reason": reason,
        "actual_score": None,
        "actual_outcome": None,
        "probabilities": None,
        "ft_1x2_top1": None,
        "ft_1x2_log_loss": None,
        "ft_1x2_brier": None,
        "ft_1x2_rps": None,
        "exact_top1": None,
        "exact_top3": None,
        "exact_top5": None,
        "exact_nll": None,
        "exact_nll_status": None,
        "exact_frozen": None,
        "formal_exact_eligible": None,
        "actual_score_rank": None,
        "actual_score_probability": None,
        "top1_score": None,
        "top1_1_1": None,
        "lambda_home": None,
        "lambda_away": None,
        "lambda_sum": None,
        "lambda_gap": None,
        "out_of_support": None,
        "verified_at": None,
        "market_pair_status": "UNPAIRED",
    }


def _evaluate_records(
    selected_records: list[dict[str, Any]],
    settlements: Mapping[str, Mapping[str, Any]],
    settlement_conflict_ids: set[str] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], Counter[str]]:
    observations: list[dict[str, Any]] = []
    evaluated: list[dict[str, Any]] = []
    reasons: Counter[str] = Counter()
    conflict_ids = settlement_conflict_ids or set()
    for record in selected_records:
        prediction_id = _text(record.get("prediction_id"))
        if prediction_id in conflict_ids:
            observation = _observation(record, status="UNRESOLVED", reason="SETTLEMENT_CONFLICT")
            reasons[observation["reason"]] += 1
            observations.append(observation)
            continue
        settlement = settlements.get(prediction_id)
        if settlement is None:
            observation = _observation(record, status="PENDING", reason="NO_FORMAL_SETTLEMENT")
            reasons[observation["reason"]] += 1
            observations.append(observation)
            continue
        result, reason = _result_for_row(settlement, record)
        if result is None:
            observation = _observation(record, status="UNRESOLVED", reason=reason)
            reasons[reason or "RESULT_UNRESOLVED"] += 1
            observations.append(observation)
            continue
        try:
            common = evaluate_prediction_common(
                record,
                result,
                frozen_record=record,
                include_distribution=True,
                preserve_declared_rank=True,
                top10_requires_ten=True,
                include_output_probabilities=False,
            )
        except (KeyError, TypeError, ValueError) as error:
            reason = f"EVALUATION_FAILED_{type(error).__name__}"
            observation = _observation(record, status="UNRESOLVED", reason=reason)
            reasons[reason] += 1
            observations.append(observation)
            continue
        probabilities = common.get("outcome_probabilities")
        rps = ranked_probability_score(probabilities, common.get("actual_outcome"))
        score_rows = common.get("_score_rows") or []
        top1_pair = parse_score_pair(score_rows[0]) if score_rows else parse_score_pair(record.get("score_top1"))
        top1_score = f"{top1_pair[0]}-{top1_pair[1]}" if top1_pair else None
        expected = expected_goals(record)
        observation = _observation(record, status="SETTLED")
        observation.update({
            "actual_score": common.get("actual_score"),
            "actual_outcome": common.get("actual_outcome"),
            "probabilities": probabilities,
            "ft_1x2_top1": common.get("top1_accuracy_1x2"),
            "ft_1x2_log_loss": common.get("log_loss_1x2"),
            "ft_1x2_brier": common.get("brier_score_1x2"),
            "ft_1x2_rps": rps,
            "exact_top1": common.get("exact_score_top1"),
            "exact_top3": common.get("exact_score_top3"),
            "exact_top5": common.get("exact_score_top5"),
            "exact_nll": (
                common.get("actual_score_nll")
                if common.get("FORMAL_EXACT_LOG_SCORE_ELIGIBLE") is True
                else None
            ),
            "exact_nll_status": common.get("actual_score_nll_status"),
            "exact_frozen": common.get("FORMAL_EXACT_DISTRIBUTION_FROZEN") is True,
            "formal_exact_eligible": common.get("FORMAL_EXACT_LOG_SCORE_ELIGIBLE") is True,
            "actual_score_rank": common.get("actual_score_rank"),
            "actual_score_probability": common.get("actual_score_probability"),
            "top1_score": top1_score,
            "top1_1_1": common.get("top1_1_1"),
            "lambda_home": _rounded(expected[0]) if expected else None,
            "lambda_away": _rounded(expected[1]) if expected else None,
            "lambda_sum": _rounded(sum(expected)) if expected else None,
            "lambda_gap": _rounded(abs(expected[0] - expected[1])) if expected else None,
            "out_of_support": common.get("OUT_OF_EXPLICIT_SUPPORT"),
            "verified_at": _iso(result.get("verified_at")),
        })
        observation["probabilities"] = {
            key: _rounded(value) for key, value in (probabilities or {}).items()
        }
        observations.append(observation)
        evaluated.append(observation)
    observations.sort(key=lambda row: (_text(row.get("kickoff_at")), _text(row.get("prediction_id"))))
    evaluated = [row for row in observations if row.get("status") == "SETTLED"]
    return observations, evaluated, reasons


def _metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "ft_1x2": {
            "n": len(rows),
            "top1_accuracy": _hit_summary(row.get("ft_1x2_top1") for row in rows),
            "log_loss": _metric_summary(row.get("ft_1x2_log_loss") for row in rows),
            "brier": _metric_summary(row.get("ft_1x2_brier") for row in rows),
            "rps": _metric_summary(row.get("ft_1x2_rps") for row in rows),
        },
        "exact_score": {
            "settled_n": len(rows),
            "frozen_n": sum(row.get("exact_frozen") is True for row in rows),
            "formal_nll_eligible_n": sum(row.get("formal_exact_eligible") is True for row in rows),
            "top1": _hit_summary(row.get("exact_top1") for row in rows),
            "top3": _hit_summary(row.get("exact_top3") for row in rows),
            "top5": _hit_summary(row.get("exact_top5") for row in rows),
            "formal_nll": _metric_summary(row.get("exact_nll") for row in rows),
            "formal_nll_coverage": _rate(
                sum(_number(row.get("exact_nll")) is not None for row in rows), len(rows)
            ),
            "out_of_support_n": sum(row.get("out_of_support") is True for row in rows),
            "actual_score_rank": _metric_summary(row.get("actual_score_rank") for row in rows),
            "actual_score_probability": _metric_summary(row.get("actual_score_probability") for row in rows),
            "nll_status_counts": dict(sorted(Counter(
                _text(row.get("exact_nll_status")) or "UNAVAILABLE"
                for row in rows
            ).items())),
        },
    }


def _collapse_diagnostics(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    top1_scores = []
    lambda_rows = []
    for row in rows:
        score = parse_score_pair(row.get("top1_score"))
        if score is not None:
            top1_scores.append(f"{score[0]}-{score[1]}")
        if all(_number(row.get(key)) is not None for key in ("lambda_sum", "lambda_gap")):
            lambda_rows.append(row)
    frequencies = Counter(top1_scores)
    leading_score, leading_count = (None, 0)
    if frequencies:
        leading_score, leading_count = sorted(
            frequencies.items(), key=lambda item: (-item[1], item[0])
        )[0]
    one_one_count = frequencies.get("1-1", 0)
    return {
        "top1_score_n": len(top1_scores),
        "top1_score_frequency": dict(sorted(frequencies.items())),
        "leading_top1_score": leading_score,
        "leading_top1_share": _rate(leading_count, len(top1_scores)),
        "one_one_top1": {
            "count": one_one_count,
            "n": len(top1_scores),
            "share": _rate(one_one_count, len(top1_scores)),
        },
        "lambda": {
            "n": len(lambda_rows),
            "sum": _metric_summary(row.get("lambda_sum") for row in lambda_rows),
            "gap": _metric_summary(row.get("lambda_gap") for row in lambda_rows),
        },
    }


def _comparator(review: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(review, Mapping):
        return {
            "status": "UNAVAILABLE",
            "unique_market_matches": 0,
            "paired_unique_match_count": 0,
            "unpaired_unique_match_count": 0,
            "champion_unique_match_count": None,
            "champion_paired_unique_match_count": None,
            "champion_unpaired_unique_match_count": None,
            "rejected_unique_market_match_count": 0,
            "reject_reason_counts": {},
            "decision": {"promotion_authorized": False},
            "metrics": {},
            "pairs": [],
        }
    counts = review.get("counts") if isinstance(review.get("counts"), Mapping) else {}
    unique = int(counts.get("unique_market_matches") or 0)
    paired = int(counts.get("paired_unique_match_count") or 0)
    metrics = review.get("metrics") if isinstance(review.get("metrics"), Mapping) else {}
    return {
        "status": "AVAILABLE",
        "unique_market_matches": unique,
        "paired_unique_match_count": paired,
        "unpaired_unique_match_count": max(0, unique - paired),
        "rejected_unique_market_match_count": int(counts.get("rejected_unique_market_match_count") or 0),
        "reject_reason_counts": dict(counts.get("reject_reason_counts") or {}),
        "selection_excluded_reason_counts": dict(counts.get("selection_excluded_reason_counts") or {}),
        "decision": dict(review.get("decision") or {}),
        "metrics": {
            "deltas": dict(metrics.get("deltas") or {}),
            "paired_comparisons": dict(metrics.get("paired_comparisons") or {}),
        },
        "pairs": [dict(pair) for pair in review.get("pairs") or [] if isinstance(pair, Mapping)],
    }


def _public_history(rows: Iterable[Mapping[str, Any]], paired_ids: set[str]) -> list[dict[str, Any]]:
    output = []
    for row in rows:
        output.append({
            "home": row.get("home"),
            "away": row.get("away"),
            "kickoff_at": row.get("kickoff_at"),
            "status": row.get("status"),
            "actual_score": row.get("actual_score"),
            "actual_outcome": row.get("actual_outcome"),
            "ft_1x2_hit": row.get("ft_1x2_top1"),
            "exact_top1_hit": row.get("exact_top1"),
            "exact_top3_hit": row.get("exact_top3"),
            "exact_top5_hit": row.get("exact_top5"),
            "paired": row.get("prediction_id") in paired_ids if row.get("prediction_id") else None,
        })
    return output


def _public_payload(
    *,
    status: str,
    model: Mapping[str, Any],
    cohort: Mapping[str, Any],
    metrics: Mapping[str, Any],
    calibration: Mapping[str, Any],
    comparator: Mapping[str, Any],
    diagnostics: Mapping[str, Any],
    freshness: Mapping[str, Any],
    history: list[Mapping[str, Any]],
) -> dict[str, Any]:
    status_copy = {
        "AVAILABLE": "持续更新中",
        "DEGRADED": "证据正在补齐",
        "UNAVAILABLE": "暂时无法形成可信记录",
    }.get(status, "暂待确认")
    return {
        "schema_version": PUBLIC_SCHEMA_VERSION,
        "status": status,
        "status_label": status_copy,
        "message": "只统计当前正式模型；命中与失误均保留，结果按90分钟及伤停补时核验。",
        "model": {
            "label": "当前正式模型",
            "model_family": model.get("model_family"),
            "release_version": model.get("release_version"),
        },
        "cohort": {
            key: cohort.get(key)
            for key in (
                "locked_unique_match_count",
                "settled_unique_match_count",
                "pending_unique_match_count",
                "unresolved_unique_match_count",
                "raw_formal_prediction_count",
                "current_version_formal_prediction_count",
                "ineligible_prediction_count",
                "invalid_persisted_record_count",
                "excluded_prediction_count",
                "superseded_version_count",
            )
        },
        "metrics": dict(metrics),
        "calibration": dict(calibration),
        "collapse_diagnostics": dict(diagnostics),
        "comparator": {
            "status": comparator.get("status"),
            "unique_market_matches": comparator.get("unique_market_matches", 0),
            "paired_unique_match_count": comparator.get("paired_unique_match_count", 0),
            "unpaired_unique_match_count": comparator.get("unpaired_unique_match_count", 0),
            "champion_unique_match_count": comparator.get("champion_unique_match_count"),
            "champion_paired_unique_match_count": comparator.get("champion_paired_unique_match_count"),
            "champion_unpaired_unique_match_count": comparator.get("champion_unpaired_unique_match_count"),
            "rejected_unique_market_match_count": comparator.get("rejected_unique_market_match_count", 0),
            "decision": dict(comparator.get("decision") or {}),
            "metrics": dict(comparator.get("metrics") or {}),
        },
        "freshness": dict(freshness),
        "history": [dict(row) for row in history],
    }


def build_projection(
    records: Iterable[Mapping[str, Any]],
    ledger_rows: Iterable[Mapping[str, Any]],
    *,
    current_fingerprint: str | None,
    excluded_ids: Iterable[str] = (),
    market_review: Mapping[str, Any] | None = None,
    serving_resolution: Mapping[str, Any] | None = None,
    source: Mapping[str, Any] | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    source_records = [dict(record) for record in records if isinstance(record, Mapping)]
    source_meta = source.get("record_load") if isinstance(source, Mapping) else {}
    invalid_record_count = int(source_meta.get("invalid") or 0) if isinstance(source_meta, Mapping) else 0
    excluded = {_text(value) for value in excluded_ids if _text(value)}
    formal = [record for record in source_records if _eligible(record)]
    version_counts = Counter(
        _text(record.get("model_run_fingerprint")) or "UNRESOLVED"
        for record in formal
        if _text(record.get("prediction_id")) not in excluded
    )
    settlements, duplicate_settlements, settlement_conflicts, settlement_conflict_ids = _settlement_index(ledger_rows)
    resolution = dict(serving_resolution or {})
    if current_fingerprint:
        resolution.setdefault("status", "RESOLVED")
        resolution.setdefault("fingerprint", current_fingerprint)
        resolution.setdefault("source", "current_serving_selection")
    else:
        resolution.setdefault("status", "UNRESOLVED")
        resolution.setdefault("fingerprint", None)
        resolution.setdefault("source", "current_serving_selection")

    selected_records: list[dict[str, Any]] = []
    current_formal_count = 0
    selection = {
        "raw_record_count": 0,
        "formally_eligible_record_count": len(formal),
        "excluded_prediction_count": sum(
            _text(record.get("prediction_id")) in excluded for record in formal
        ),
        "legal_record_count": 0,
        "unique_match_count": 0,
        "superseded_record_count": 0,
        "identity_conflict_group_count": 0,
    }
    if current_fingerprint:
        current_formal = [
            record for record in formal
            if _text(record.get("model_run_fingerprint")) == current_fingerprint
        ]
        current_formal_count = len(current_formal)
        cohort = build_unique_match_cohort(current_formal, excluded_ids=excluded)
        selected_records = [dict(record) for record in cohort.get("selected_records") or []]
        selection.update({
            key: cohort.get(key, selection[key])
            for key in selection
            if key in cohort
        })
        selection["raw_record_count"] = len(current_formal)
    observations, settled_rows, evaluation_reasons = _evaluate_records(
        selected_records,
        settlements,
        settlement_conflict_ids,
    )
    paired_review = _comparator(market_review)
    paired_ids = {
        _text(pair.get("champion_prediction_id"))
        for pair in paired_review.get("pairs") or []
        if _text(pair.get("champion_prediction_id"))
    }
    for observation in observations:
        observation["market_pair_status"] = "PAIRED" if observation.get("prediction_id") in paired_ids else "UNPAIRED"
    if paired_review.get("status") == "AVAILABLE":
        paired_review.update({
            "champion_unique_match_count": len(selected_records),
            "champion_paired_unique_match_count": len(paired_ids),
            "champion_unpaired_unique_match_count": max(0, len(selected_records) - len(paired_ids)),
        })
    paired = {key: value for key, value in paired_review.items() if key != "pairs"}
    cohort_payload = {
        **selection,
        "locked_unique_match_count": len(selected_records),
        "superseded_version_count": int(selection.get("superseded_record_count") or 0),
        "raw_formal_prediction_count": len(formal),
        "current_version_formal_prediction_count": current_formal_count,
        "ineligible_prediction_count": max(0, len(source_records) - len(formal)) + invalid_record_count,
        "eligibility_reason_counts": {
            "formal": len(formal),
            "excluded": sum(
                _text(record.get("prediction_id")) in excluded for record in formal
            ),
            "not_formally_eligible": max(0, len(source_records) - len(formal)),
            "invalid_persisted_record": invalid_record_count,
        },
        "invalid_persisted_record_count": invalid_record_count,
        "selected_prediction_ids": sorted(_text(record.get("prediction_id")) for record in selected_records),
        "settled_unique_match_count": len(settled_rows),
        "pending_unique_match_count": sum(row.get("status") == "PENDING" for row in observations),
        "unresolved_unique_match_count": sum(row.get("status") == "UNRESOLVED" for row in observations),
        "settlement_duplicate_row_count": duplicate_settlements,
        "settlement_conflict_prediction_count": settlement_conflicts,
        "evaluation_reason_counts": dict(sorted(evaluation_reasons.items())),
        "history_match_count": len(observations),
    }
    metrics = _metrics(settled_rows)
    diagnostics = _collapse_diagnostics(settled_rows)
    status = "AVAILABLE" if current_fingerprint and settled_rows else "DEGRADED" if current_fingerprint else "UNAVAILABLE"
    if settlement_conflicts or cohort_payload["unresolved_unique_match_count"]:
        status = "DEGRADED" if current_fingerprint else "UNAVAILABLE"
    model = next((record for record in selected_records if isinstance(record, dict)), None) or next(
        (record for record in formal if _text(record.get("model_run_fingerprint")) == current_fingerprint), {}
    )
    freshness = _freshness(selected_records, settled_rows)
    paired_verified = [pair.get("verified_at") for pair in paired_review.get("pairs") or []]
    pair_freshness = _freshness(
        [{"prediction_created_at": pair.get("source_cutoff_at"), "match_identity": {"kickoff_at": pair.get("kickoff_at")}}
         for pair in paired_review.get("pairs") or []],
        [{"verified_at": value} for value in paired_verified],
    )
    freshness.update({
        "paired_first_kickoff_at": pair_freshness.get("first_kickoff_at"),
        "paired_last_kickoff_at": pair_freshness.get("last_kickoff_at"),
        "paired_settled_through": pair_freshness.get("settled_through"),
    })
    generated = generated_at or datetime.now(timezone.utc).isoformat()
    result = {
        "schema_version": SCHEMA_VERSION,
        "trust_id": TRUST_ID,
        "generated_at": generated,
        "status": status,
        "evidence_state": "PARTIAL_COVERAGE" if cohort_payload["pending_unique_match_count"] or cohort_payload["unresolved_unique_match_count"] else status,
        "policy": {
            "observation_unit": "one unique football match",
            "formal_denominator": "all formal production Champion predictions after current model-run isolation",
            "selection": "existing prediction_trust_audit.build_unique_match_cohort -> prematch_versioning.select_latest_legal_prematch",
            "result_scope": RESULT_SCOPE,
            "result_selection_dependency": False,
            "history_mutation": "none",
            "model_tuning": False,
            "promotion_authorized": False,
        },
        "current_version": resolution,
        "model": {
            "model_family": _text(model.get("model_family")) or None,
            "release_version": _text(model.get("release_version")) or None,
            "feature_version": _text(model.get("feature_version")) or None,
            "data_pipeline_version": _text(model.get("data_pipeline_version")) or None,
            "effective_calibration_fingerprint": _text(model.get("effective_calibration_fingerprint")) or None,
            "calibration_fingerprint": _text(model.get("calibration_fingerprint")) or None,
            "model_source_fingerprint": _text(model.get("model_source_fingerprint")) or None,
            "model_run_fingerprint": current_fingerprint,
        },
        "version_counts": dict(sorted(version_counts.items())),
        "cohort": cohort_payload,
        "metrics": metrics,
        "collapse_diagnostics": diagnostics,
        "calibration": _calibration(settled_rows),
        "comparator": paired,
        "freshness": freshness,
        "history": observations,
        "source": dict(source or {}),
        "public": _public_payload(
            status=status,
            model=model,
            cohort=cohort_payload,
            metrics=metrics,
            calibration=_calibration(settled_rows),
            comparator=paired,
            diagnostics=diagnostics,
            freshness={"generated_at": generated, **freshness},
            history=_public_history(observations, paired_ids),
        ),
    }
    result["public"]["freshness"]["generated_at"] = result["generated_at"]
    return result


def _market_review(market_root: Path, records: Iterable[Mapping[str, Any]], current_fingerprint: str | None) -> dict[str, Any] | None:
    if not current_fingerprint or not market_root.is_dir():
        return None
    market_predictions = load_persisted_predictions(market_root)
    settlements = load_persisted_settlements(market_root)
    champion_predictions = {
        _text(record.get("prediction_id")): dict(record)
        for record in records
        if _text(record.get("model_run_fingerprint")) == current_fingerprint
        and _text(record.get("prediction_id"))
    }
    return build_review(
        settlements,
        market_predictions={
            _text(record.get("prediction_id")): record
            for record in market_predictions
            if _text(record.get("prediction_id"))
        },
        champion_predictions=champion_predictions,
        source={"projection": TRUST_ID},
    )


def _relative(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path)


def run_projection(
    *,
    root: Path = ROOT,
    business_date: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    root = Path(root).resolve()
    prediction_root = root / "data" / "model_governance" / "predictions"
    exclusion_root = root / "data" / "model_governance" / "prediction_exclusions"
    ledger_path = root / "data" / "prospective" / "ledger.jsonl"
    runtime_path = root / "data" / "product_runtime" / "latest_cycle.json"
    market_root = root / "data" / "prediction_quality" / "pure_market_exact_prospective_1"
    runtime = _read_json(runtime_path, {})
    if not isinstance(runtime, dict):
        runtime = {}
    current_date = _text(business_date) or _text(runtime.get("business_date"))
    jobs_path = root / "data" / "base_prediction_jobs" / f"{current_date}.json"
    jobs_payload = _read_json(jobs_path, {})
    jobs = jobs_payload.get("jobs") if isinstance(jobs_payload, dict) else []
    jobs = jobs if isinstance(jobs, list) else []
    records, record_counts = _load_records(prediction_root)
    excluded = excluded_prediction_ids(exclusion_root)
    ledger_rows = _read_jsonl(ledger_path)
    try:
        serving = select_current_serving_predictions(
            records,
            business_date=current_date,
            current_jobs=jobs,
            excluded_ids=excluded,
        )
    except (KeyError, TypeError, ValueError):
        serving = {}
    fingerprints = sorted({
        _text(record.get("model_run_fingerprint"))
        for record in serving.get("selected_records") or []
        if _text(record.get("model_run_fingerprint"))
    })
    current_fingerprint = fingerprints[0] if len(fingerprints) == 1 else None
    resolution = {
        "status": "RESOLVED" if current_fingerprint else "UNRESOLVED",
        "fingerprint": current_fingerprint,
        "source": "current_serving_selection",
        "selected_record_count": int(serving.get("selected_record_count") or 0),
        "serving_fingerprint_count": len(fingerprints),
        "reason": None if current_fingerprint else "CURRENT_VERSION_UNRESOLVED",
    }
    market_review = None
    market_error = None
    try:
        market_review = _market_review(market_root, records, current_fingerprint)
    except (OSError, TypeError, ValueError, KeyError, json.JSONDecodeError) as error:
        market_error = f"{type(error).__name__}: {error}"
    source = {
        "prediction_root": {
            "path": _relative(root, prediction_root),
            "sha256": _source_digest(records),
            "record_count": record_counts["loaded"],
        },
        "prospective_ledger": {
            "path": _relative(root, ledger_path),
            "sha256": _file_digest(ledger_path),
            "row_count": len(ledger_rows),
        },
        "current_jobs": {
            "path": _relative(root, jobs_path),
            "sha256": _file_digest(jobs_path),
            "job_count": len(jobs),
        },
        "prediction_exclusions": {
            "path": _relative(root, exclusion_root),
            "sha256": _tree_digest(exclusion_root),
            "excluded_prediction_count": len(excluded),
        },
        "market_root": {
            "path": _relative(root, market_root),
            "sha256": _tree_digest(market_root),
        },
        "business_date": current_date or None,
    }
    if market_error:
        source["market_root"]["error"] = market_error
    projection = build_projection(
        records,
        ledger_rows,
        current_fingerprint=current_fingerprint,
        excluded_ids=excluded,
        market_review=market_review,
        serving_resolution=resolution,
        source={"root": source, "record_load": record_counts},
        generated_at=(now or datetime.now(timezone.utc)).isoformat(),
    )
    projection["business_date"] = current_date or None
    projection["public"]["business_date"] = current_date or None
    return projection


def render_summary(projection: Mapping[str, Any]) -> str:
    cohort = projection.get("cohort") if isinstance(projection.get("cohort"), Mapping) else {}
    metrics = projection.get("metrics") if isinstance(projection.get("metrics"), Mapping) else {}
    ft = metrics.get("ft_1x2") if isinstance(metrics.get("ft_1x2"), Mapping) else {}
    exact = metrics.get("exact_score") if isinstance(metrics.get("exact_score"), Mapping) else {}
    comparator = projection.get("comparator") if isinstance(projection.get("comparator"), Mapping) else {}
    return "\n".join([
        "# Current Champion trust projection",
        "",
        f"- Status: `{projection.get('status')}`; generated at `{projection.get('generated_at')}`.",
        f"- Current model run: `{(projection.get('current_version') or {}).get('status')}`.",
        f"- Denominator: `{cohort.get('locked_unique_match_count', 0)}` unique matches; settled `{cohort.get('settled_unique_match_count', 0)}`; pending `{cohort.get('pending_unique_match_count', 0)}`; unresolved `{cohort.get('unresolved_unique_match_count', 0)}`.",
        f"- FT1X2: Top1 `{(ft.get('top1_accuracy') or {}).get('rate')}`; log loss `{(ft.get('log_loss') or {}).get('mean')}`; Brier `{(ft.get('brier') or {}).get('mean')}`; RPS `{(ft.get('rps') or {}).get('mean')}`.",
        f"- Exact: Top1 `{(exact.get('top1') or {}).get('rate')}`; Top3 `{(exact.get('top3') or {}).get('rate')}`; Top5 `{(exact.get('top5') or {}).get('rate')}`; formal NLL n=`{(exact.get('formal_nll') or {}).get('n', 0)}`.",
        f"- Market comparison: paired `{comparator.get('paired_unique_match_count', 0)}`; unpaired `{comparator.get('unpaired_unique_match_count', 0)}`; promotion authorized `{(comparator.get('decision') or {}).get('promotion_authorized', False)}`.",
        "- Selection is read-only; frozen predictions, settlement truth, Champion, Serving, and providers are unchanged.",
        "",
    ])


def write_artifacts(
    projection: Mapping[str, Any],
    *,
    output: Path = DEFAULT_OUTPUT,
    summary: Path = DEFAULT_SUMMARY,
) -> dict[str, str]:
    output = Path(output)
    summary = Path(summary)
    output.parent.mkdir(parents=True, exist_ok=True)
    summary.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(projection, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    summary.write_text(render_summary(projection), encoding="utf-8")
    return {"json": str(output), "summary": str(summary)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--business-date")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY)
    args = parser.parse_args(argv)
    projection = run_projection(root=args.root, business_date=args.business_date)
    write_artifacts(projection, output=args.output, summary=args.summary)
    print(json.dumps({
        "status": projection["status"],
        "business_date": projection.get("business_date"),
        "locked_unique_matches": projection["cohort"]["locked_unique_match_count"],
        "settled_unique_matches": projection["cohort"]["settled_unique_match_count"],
        "pending_unique_matches": projection["cohort"]["pending_unique_match_count"],
        "paired_unique_matches": projection["comparator"]["paired_unique_match_count"],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
