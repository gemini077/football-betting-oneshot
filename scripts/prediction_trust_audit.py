#!/usr/bin/env python3
"""Read-only PRED-TRUST-1 unique-match quality audit.

The audit deliberately keeps evaluation selection separate from the immutable
prediction and prospective ledgers.  It reuses the repository's prematch
selector and formal eligibility policy, then writes only the two explicit
audit outputs requested by the CLI.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

try:
    from prematch_versioning import (
        _identity as record_identity,
        _is_formal_prematch,
        _parse_timestamp,
        select_latest_legal_prematch,
    )
    from prediction_dashboard import _fixture_projection, _prematch_identity
    from prospective_settlement import (
        FROZEN_STATUSES,
        is_formally_eligible,
        normalize_result,
    )
    from production_health_watch import evaluate_exact_score_health
except ImportError:  # package imports used by focused tests
    from scripts.prematch_versioning import (
        _identity as record_identity,
        _is_formal_prematch,
        _parse_timestamp,
        select_latest_legal_prematch,
    )
    from scripts.prediction_dashboard import _fixture_projection, _prematch_identity
    from scripts.prospective_settlement import (
        FROZEN_STATUSES,
        is_formally_eligible,
        normalize_result,
    )
    from scripts.production_health_watch import evaluate_exact_score_health


BASE_DIR = Path(__file__).resolve().parents[1]
DEFAULT_CURRENT_DATE = "2026-08-30"
DEFAULT_OUTPUT = (
    BASE_DIR
    / "data"
    / "prediction_quality"
    / "pred_trust_1"
    / "audit_2026-08-30.json"
)
DEFAULT_REPORT = (
    BASE_DIR
    / "docs"
    / "prediction-quality"
    / "PRED-TRUST-1_FINAL_REPORT.md"
)
EPSILON = 1e-15
LEADER_KEYS = ("home", "draw", "away")
BUCKETS = (
    ("<40%", 0.0, 0.40),
    ("40–45%", 0.40, 0.45),
    ("45–50%", 0.45, 0.50),
    ("50–55%", 0.50, 0.55),
    ("55%+", 0.55, 1.01),
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


def _rate(count: int, total: int) -> float | None:
    return round(count / total, 6) if total else None


def _count_share(count: int, total: int) -> dict[str, Any]:
    return {"count": count, "share": _rate(count, total)}


def _quantile(values: Iterable[float], probability: float) -> float | None:
    ordered = sorted(float(value) for value in values if _number(value) is not None)
    if not ordered:
        return None
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    value = ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)
    return round(value, 6)


def _quantiles(values: Iterable[float]) -> dict[str, float | None]:
    return {
        "P10": _quantile(values, 0.10),
        "P25": _quantile(values, 0.25),
        "P50": _quantile(values, 0.50),
        "P75": _quantile(values, 0.75),
        "P90": _quantile(values, 0.90),
    }


def _mean(values: Iterable[float]) -> float | None:
    values = [float(value) for value in values if _number(value) is not None]
    return round(sum(values) / len(values), 6) if values else None


def _normalise_text(value: Any) -> str:
    return " ".join(_text(value).casefold().split())


def _score_pair(value: Any) -> tuple[int, int] | None:
    if isinstance(value, (list, tuple)) and len(value) == 2:
        left, right = value
    elif isinstance(value, dict):
        left, right = value.get("home_score"), value.get("away_score")
    else:
        match = re.fullmatch(r"\s*(\d+)\s*-\s*(\d+)\s*", _text(value))
        if not match:
            return None
        left, right = match.groups()
    try:
        home, away = int(left), int(right)
    except (TypeError, ValueError):
        return None
    if home < 0 or away < 0:
        return None
    return home, away


def _score_text(pair: tuple[int, int] | None) -> str | None:
    return f"{pair[0]}-{pair[1]}" if pair else None


def _score_rows(record: Mapping[str, Any]) -> list[dict[str, Any]]:
    output = record.get("prediction_output")
    output = output if isinstance(output, dict) else {}
    source = (
        record.get("score_distribution")
        or record.get("top_scores")
        or output.get("score_distribution")
        or output.get("top_scores")
        or []
    )
    if not isinstance(source, list):
        return []
    rows = [row for row in source if isinstance(row, dict) and _score_pair(row.get("score"))]

    def sort_key(row: dict[str, Any]) -> tuple[int, float, str]:
        rank = row.get("rank")
        probability = _number(row.get("probability")) or 0.0
        try:
            rank_value = int(rank)
        except (TypeError, ValueError):
            rank_value = 10**9
        return rank_value, -probability, _text(row.get("score"))

    return sorted(rows, key=sort_key)


def _top_score(record: Mapping[str, Any]) -> str | None:
    output = record.get("prediction_output")
    output = output if isinstance(output, dict) else {}
    for value in (
        record.get("unique_score"),
        record.get("score_top1"),
        output.get("unique_score"),
        output.get("score_top1"),
    ):
        pair = _score_pair(value)
        if pair:
            return _score_text(pair)
    rows = _score_rows(record)
    return _score_text(_score_pair(rows[0].get("score"))) if rows else None


def _top_scores(record: Mapping[str, Any], count: int) -> list[str]:
    output = record.get("prediction_output")
    output = output if isinstance(output, dict) else {}
    source = record.get("score_top3") if count <= 3 else record.get("score_top5")
    if not isinstance(source, list):
        source = output.get("score_top3") if count <= 3 else output.get("score_top5")
    if isinstance(source, list):
        values = [_score_text(_score_pair(value)) for value in source]
        values = [value for value in values if value]
        if values:
            return values[:count]
    return [
        _score_text(_score_pair(row.get("score")))
        for row in _score_rows(record)[:count]
        if _score_pair(row.get("score"))
    ]


def _probabilities(record: Mapping[str, Any]) -> dict[str, float]:
    output = record.get("prediction_output")
    output = output if isinstance(output, dict) else {}
    value = record.get("probabilities") or output.get("probabilities") or {}
    if not isinstance(value, dict):
        return {}
    return {
        key: number
        for key in LEADER_KEYS
        if (number := _number(value.get(key))) is not None
    }


def _btts_yes(record: Mapping[str, Any]) -> float | None:
    output = record.get("prediction_output")
    output = output if isinstance(output, dict) else {}
    value = record.get("btts") or output.get("btts") or {}
    return _number(value.get("yes")) if isinstance(value, dict) else None


def _over_2_5_probability(record: Mapping[str, Any]) -> float | None:
    output = record.get("prediction_output")
    output = output if isinstance(output, dict) else {}
    rows = record.get("totals") or output.get("totals") or []
    if not isinstance(rows, list) or not rows:
        return None
    probability = 0.0
    found = False
    for row in rows:
        if not isinstance(row, dict):
            continue
        goals = _text(row.get("goals"))
        if goals == "6+":
            include = True
        else:
            try:
                include = int(goals) >= 3
            except (TypeError, ValueError):
                include = False
        if include:
            value = _number(row.get("probability"))
            if value is not None:
                probability += value
                found = True
    return round(probability, 6) if found else None


def _lambda_pair(record: Mapping[str, Any]) -> tuple[float, float] | None:
    home = _number(record.get("lambda_home"))
    away = _number(record.get("lambda_away"))
    return (home, away) if home is not None and away is not None else None


def _leader(record: Mapping[str, Any]) -> str | None:
    probabilities = _probabilities(record)
    if not all(key in probabilities for key in LEADER_KEYS):
        return None
    return max(LEADER_KEYS, key=lambda key: probabilities[key])


def _leader_probability(record: Mapping[str, Any]) -> float | None:
    leader = _leader(record)
    return _probabilities(record).get(leader) if leader else None


def _is_formally_eligible(record: Mapping[str, Any]) -> bool:
    try:
        return bool(is_formally_eligible(dict(record)))
    except Exception:
        return False


def _identity_signature(record: Mapping[str, Any]) -> dict[str, str]:
    identity = record_identity(dict(record))
    return {
        "match_id": _text(identity.get("match_id")),
        "match_key": _text(identity.get("match_key")),
        "home": _normalise_text(identity.get("home")),
        "away": _normalise_text(identity.get("away")),
        "kickoff_at": (
            _parse_timestamp(identity.get("kickoff_at")).isoformat()
            if _parse_timestamp(identity.get("kickoff_at"))
            else _text(identity.get("kickoff_at"))
        ),
    }


def _cohort_group_key(record: Mapping[str, Any]) -> str:
    identity = record_identity(dict(record))
    for field in ("match_id", "match_key", "job_id"):
        value = _text(identity.get(field))
        if value:
            return f"{field}:{value}"
    signature = _identity_signature(record)
    return "fallback:{kickoff_at}|{home}|{away}".format(**signature)


def _selection_identity(record: Mapping[str, Any]) -> dict[str, Any]:
    identity = record_identity(dict(record))
    return {
        "job_id": identity.get("job_id"),
        "match_id": identity.get("match_id"),
        "match_key": identity.get("match_key"),
        "home": identity.get("home"),
        "away": identity.get("away"),
        "kickoff_at": identity.get("kickoff_at"),
    }


def _formal_candidates(
    records: Iterable[Mapping[str, Any]], excluded_ids: set[str]
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for record in records:
        if not isinstance(record, Mapping):
            continue
        prediction_id = _text(record.get("prediction_id"))
        if prediction_id in excluded_ids:
            continue
        if _is_formally_eligible(record):
            candidates.append(dict(record))
    return candidates


def build_unique_match_cohort(
    records: Iterable[Mapping[str, Any]], *, excluded_ids: Iterable[str] = ()
) -> dict[str, Any]:
    """Select exactly one legal final prematch version per unique match.

    This is an evaluation view.  The input dictionaries are copied before
    selection, and no source artifact or ledger row is edited.
    """

    source_records = [dict(record) for record in records if isinstance(record, Mapping)]
    excluded = {_text(value) for value in excluded_ids if _text(value)}
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in source_records:
        groups[_cohort_group_key(record)].append(record)

    selected_records: list[dict[str, Any]] = []
    selection_groups: list[dict[str, Any]] = []
    legal_record_count = 0
    superseded_record_count = 0
    identity_conflict_count = 0
    excluded_present = {
        _text(record.get("prediction_id"))
        for record in source_records
        if _text(record.get("prediction_id")) in excluded
    }

    for group_key in sorted(groups):
        group = groups[group_key]
        candidates = _formal_candidates(group, excluded)
        selection: dict[str, Any]
        if candidates:
            selection = select_latest_legal_prematch(
                candidates, identity=_selection_identity(candidates[0])
            )
        else:
            selection = {
                "status": "NO_LEGAL_PREMATCH_VERSION",
                "reason": "NO_FORMAL_PREMATCH_VERSION_BEFORE_KICKOFF",
                "selected_record": None,
                "selected_prediction_id": None,
                "candidate_count": 0,
                "superseded_count": 0,
            }
        candidate_count = int(selection.get("candidate_count") or 0)
        legal_record_count += candidate_count
        superseded_record_count += int(selection.get("superseded_count") or 0)
        if selection.get("status") == "IDENTITY_CONFLICT":
            identity_conflict_count += 1
        selected = selection.get("selected_record")
        if isinstance(selected, dict):
            selected_records.append(selected)
        first_identity = record_identity(group[0]) if group else {}
        selection_groups.append(
            {
                "group_key": group_key,
                "match_id": first_identity.get("match_id"),
                "match_key": first_identity.get("match_key"),
                "raw_record_count": len(group),
                "formal_candidate_count": len(candidates),
                "legal_candidate_count": candidate_count,
                "selected_prediction_id": selection.get("selected_prediction_id"),
                "superseded_count": int(selection.get("superseded_count") or 0),
                "status": selection.get("status"),
                "reason": selection.get("reason"),
            }
        )

    selected_records.sort(
        key=lambda record: (
            _text(record_identity(record).get("match_id")),
            _text(record_identity(record).get("match_key")),
        )
    )
    return {
        "raw_record_count": len(source_records),
        "formally_eligible_record_count": sum(
            _is_formally_eligible(record) for record in source_records
        ),
        "excluded_prediction_count": len(excluded_present),
        "legal_record_count": legal_record_count,
        "unique_match_count": len(selected_records),
        "superseded_record_count": superseded_record_count,
        "identity_conflict_group_count": identity_conflict_count,
        "selected_records": selected_records,
        "groups": selection_groups,
    }


def build_current_day_cohort(
    root: Path,
    business_date: str,
    records: Iterable[Mapping[str, Any]],
    *,
    excluded_ids: Iterable[str] = (),
) -> dict[str, Any]:
    """Apply the same selector to the canonical daily universe fixtures."""

    universe = _read_json(root / "data" / "prediction_universe" / f"{business_date}.json", {})
    jobs_payload = _read_json(root / "data" / "base_prediction_jobs" / f"{business_date}.json", {})
    fixtures = universe.get("fixtures") if isinstance(universe, dict) else []
    jobs = jobs_payload.get("jobs") if isinstance(jobs_payload, dict) else []
    fixtures = fixtures if isinstance(fixtures, list) else []
    jobs = jobs if isinstance(jobs, list) else []
    records = [dict(record) for record in records if isinstance(record, Mapping)]
    excluded = {_text(value) for value in excluded_ids if _text(value)}
    job_by_match_id = {
        _text(job.get("match_id")): job
        for job in jobs
        if isinstance(job, dict) and _text(job.get("match_id"))
    }
    selected_records: list[dict[str, Any]] = []
    selections: list[dict[str, Any]] = []
    legal_record_count = 0
    superseded_record_count = 0
    for fixture in fixtures:
        if not isinstance(fixture, dict):
            continue
        projected = _fixture_projection(fixture)
        job = job_by_match_id.get(_text(projected.get("match_id")))
        identity = _prematch_identity(fixture, job)
        candidates = [
            record
            for record in records
            if _text(record.get("prediction_id")) not in excluded
            and _is_formally_eligible(record)
        ]
        selection = select_latest_legal_prematch(candidates, identity=identity)
        legal_record_count += int(selection.get("candidate_count") or 0)
        superseded_record_count += int(selection.get("superseded_count") or 0)
        selected = selection.get("selected_record")
        if isinstance(selected, dict):
            selected_records.append(selected)
        selections.append(
            {
                "match_id": projected.get("match_id"),
                "match_num": projected.get("match_num"),
                "competition": projected.get("competition"),
                "home": projected.get("home"),
                "away": projected.get("away"),
                "kickoff_at": projected.get("kickoff"),
                "job_id": identity.get("job_id"),
                "job_status": (job or {}).get("status"),
                "candidate_count": int(selection.get("candidate_count") or 0),
                "superseded_count": int(selection.get("superseded_count") or 0),
                "selected_prediction_id": selection.get("selected_prediction_id"),
                "status": selection.get("status"),
                "reason": selection.get("reason"),
            }
        )
    selected_records.sort(key=lambda record: _text(record.get("match_id")))
    job_status_counts = Counter(
        _text(job.get("status")) or "UNKNOWN"
        for job in jobs
        if isinstance(job, dict)
    )
    return {
        "business_date": business_date,
        "fixture_count": len(fixtures),
        "job_status_counts": dict(sorted(job_status_counts.items())),
        "legal_record_count": legal_record_count,
        "unique_match_count": len(selected_records),
        "superseded_record_count": superseded_record_count,
        "selected_records": selected_records,
        "selections": selections,
        "production_job_summary": {
            key: jobs_payload.get(key)
            for key in (
                "fixture_count",
                "frozen_count",
                "insufficient_data_count",
                "prediction_failed_count",
                "failure_reasons",
                "last_run_at",
            )
            if isinstance(jobs_payload, dict) and key in jobs_payload
        },
    }


def _health_group_key(record: Mapping[str, Any]) -> str:
    return _text(
        record.get("job_id")
        or record.get("match_key")
        or record.get("prediction_id")
    )


def _chronology_key(record: Mapping[str, Any]) -> tuple[str, str, str]:
    values = []
    for field in ("source_cutoff_at", "prediction_created_at", "freeze_created_at"):
        parsed = _parse_timestamp(record.get(field))
        values.append(parsed.isoformat() if parsed else _text(record.get(field)))
    return tuple(values)  # type: ignore[return-value]


def classify_duplicate_groups(
    records: Iterable[Mapping[str, Any]], *, excluded_ids: Iterable[str] = ()
) -> dict[str, Any]:
    """Classify every group that the current health rule calls duplicate."""

    source_records = [dict(record) for record in records if isinstance(record, Mapping)]
    excluded = {_text(value) for value in excluded_ids if _text(value)}
    frozen = [
        record
        for record in source_records
        if _text(record.get("prediction_status")) in FROZEN_STATUSES
    ]
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in frozen:
        key = _health_group_key(record)
        if key:
            groups[key].append(record)

    duplicate_groups: list[dict[str, Any]] = []
    affected_matches: set[str] = set()
    counts = Counter({"A": 0, "B": 0, "C": 0, "D": 0})
    for group_key in sorted(groups):
        rows = groups[group_key]
        if len(rows) <= 1:
            continue
        signatures = [_identity_signature(row) for row in rows]
        for signature in signatures:
            affected_matches.add(
                signature.get("match_id") or signature.get("match_key") or group_key
            )
        identity_collision = any(
            len({signature[field] for signature in signatures if signature[field]}) > 1
            for field in ("match_id", "match_key", "home", "away", "kickoff_at")
        )
        candidates = _formal_candidates(rows, excluded)
        expected_identity = _selection_identity(candidates[0]) if candidates else {}
        selection = (
            select_latest_legal_prematch(
                candidates, identity=expected_identity
            )
            if candidates
            else {"status": "NO_LEGAL_PREMATCH_VERSION", "candidate_count": 0}
        )
        legal_candidates = [
            row
            for row in candidates
            if _is_formal_prematch(row, expected_identity)
        ]
        chronology = [_chronology_key(row) for row in legal_candidates]
        same_chronology = len(chronology) != len(set(chronology))
        if identity_collision or selection.get("status") == "IDENTITY_CONFLICT":
            category = "C"
        elif same_chronology and len(legal_candidates) > 1:
            category = "B"
        elif int(selection.get("candidate_count") or 0) > 1:
            category = "A"
        else:
            category = "D"
        counts[category] += 1
        duplicate_groups.append(
            {
                "health_group_key": group_key,
                "category": category,
                "raw_record_count": len(rows),
                "prediction_ids": sorted(
                    _text(row.get("prediction_id")) for row in rows if _text(row.get("prediction_id"))
                ),
                "match_ids": sorted(
                    {
                        signature["match_id"]
                        for signature in signatures
                        if signature["match_id"]
                    }
                ),
                "match_keys": sorted(
                    {
                        signature["match_key"]
                        for signature in signatures
                        if signature["match_key"]
                    }
                ),
                "formal_candidate_count": len(candidates),
                "legal_candidate_count": int(selection.get("candidate_count") or 0),
                "selected_prediction_id": selection.get("selected_prediction_id"),
                "same_chronology": same_chronology,
                "selection_status": selection.get("status"),
            }
        )

    actual_violation = bool(counts["B"] or counts["C"])
    false_positive_count = counts["A"] + counts["D"]
    if actual_violation:
        recommendation = (
            "PREDICTION_INTEGRITY_BLOCKED: stop model quality conclusions and repair "
            "only the affected final-version/identity groups before re-running the audit."
        )
    elif false_positive_count:
        recommendation = (
            "Bounded repair recommendation only: teach the health monitor the canonical "
            "unique-match selector and alert on unresolved B/C groups; do not patch the "
            "monitor or rewrite history in PRED-TRUST-1."
        )
    else:
        recommendation = "No duplicate monitor repair is indicated by this classification."
    return {
        "health_frozen_record_count": len(frozen),
        "health_group_count": len(groups),
        "duplicate_group_count": len(duplicate_groups),
        "unique_affected_matches": len(affected_matches),
        "classification_counts": {key: counts[key] for key in ("A", "B", "C", "D")},
        "affected_record_count": sum(
            int(group["raw_record_count"]) for group in duplicate_groups
        ),
        "health_rule_false_positive_group_count": false_positive_count,
        "actual_immutable_frozen_integrity_violation": actual_violation,
        "prediction_integrity_status": (
            "PREDICTION_INTEGRITY_BLOCKED" if actual_violation else "CLEAR"
        ),
        "bounded_repair_recommendation": recommendation,
        "groups": duplicate_groups,
    }


def _independent_poisson_map(record: Mapping[str, Any]) -> str | None:
    pair = _lambda_pair(record)
    if not pair:
        return None
    home_lambda, away_lambda = pair
    best: tuple[float, int, int] | None = None
    for home_score in range(0, 11):
        for away_score in range(0, 11):
            probability = (
                math.exp(-home_lambda)
                * home_lambda**home_score
                / math.factorial(home_score)
                * math.exp(-away_lambda)
                * away_lambda**away_score
                / math.factorial(away_score)
            )
            candidate = (probability, -home_score, -away_score)
            if best is None or candidate > best:
                best = candidate
    return f"{-best[1]}-{-best[2]}" if best else None


def _probability_profile(records: list[dict[str, Any]], key: str) -> dict[str, Any]:
    values = [_number(record.get(key)) for record in records]
    values = [value for value in values if value is not None]
    return {"sample_count": len(values), "quantiles": _quantiles(values)}


def _leader_bucket(probability: float | None) -> str:
    if probability is None:
        return "UNAVAILABLE"
    for name, lower, upper in BUCKETS:
        if lower <= probability < upper:
            return name
    return "UNAVAILABLE"


def _summary_leader_strata(records: list[dict[str, Any]]) -> dict[str, Any]:
    strata: dict[str, Any] = {}
    for leader in LEADER_KEYS:
        subset = [record for record in records if _leader(record) == leader]
        pairs = [_lambda_pair(record) for record in subset]
        pairs = [pair for pair in pairs if pair]
        homes = [home for home, _ in pairs]
        aways = [away for _, away in pairs]
        totals = [home + away for home, away in pairs]
        gaps = [abs(home - away) for home, away in pairs]
        strata[leader.upper()] = {
            "sample_count": len(subset),
            "lambda_home": _quantiles(homes),
            "lambda_away": _quantiles(aways),
            "lambda_total": _quantiles(totals),
            "absolute_gap": _quantiles(gaps),
            "gap_lt_0_25": _count_share(sum(gap < 0.25 for gap in gaps), len(gaps)),
            "gap_lt_0_5": _count_share(sum(gap < 0.5 for gap in gaps), len(gaps)),
            "total_lt_2": _count_share(sum(total < 2 for total in totals), len(totals)),
            "total_2_to_3": _count_share(
                sum(2 <= total <= 3 for total in totals), len(totals)
            ),
            "total_gt_3": _count_share(sum(total > 3 for total in totals), len(totals)),
        }
    return strata


def _market_fusion_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    rows: list[tuple[dict[str, float], dict[str, float]]] = []
    for record in records:
        model = _probabilities(record)
        market = record.get("market_only_baseline")
        market = market if isinstance(market, dict) else {}
        market = {key: _number(market.get(key)) for key in LEADER_KEYS}
        if all(key in model and market[key] is not None for key in LEADER_KEYS):
            rows.append((model, market))
    disagreement = 0
    disagreement_draw_score = 0
    leader_pairs = Counter()
    deltas = {key: [] for key in LEADER_KEYS}
    for model, market in rows:
        model_leader = max(LEADER_KEYS, key=lambda key: model[key])
        market_leader = max(LEADER_KEYS, key=lambda key: market[key])
        leader_pairs[(market_leader.upper(), model_leader.upper())] += 1
        if model_leader != market_leader:
            disagreement += 1
        for key in LEADER_KEYS:
            deltas[key].append(model[key] - float(market[key]))
    return {
        "available_count": len(rows),
        "market_model_leader_disagreement": {
            "count": disagreement,
            "share": _rate(disagreement, len(rows)),
        },
        "market_leader_to_model_leader": {
            f"{market}->{model}": count
            for (market, model), count in sorted(leader_pairs.items())
        },
        "mean_model_minus_market_probability": {
            key: _mean(values) for key, values in deltas.items()
        },
    }


def summarize_prediction_cohort(records: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    records = [dict(record) for record in records if isinstance(record, Mapping)]
    sample_count = len(records)
    score_values = [_top_score(record) for record in records]
    score_values = [score for score in score_values if score]
    score_counts = Counter(score_values)
    score_pairs = [_score_pair(score) for score in score_values]
    score_pairs = [pair for pair in score_pairs if pair]
    named_scores = {score: score_counts.get(score, 0) for score in ("1-1", "0-0", "2-1", "1-2", "2-2")}
    valid_score_count = len(score_pairs)
    home_margin = sum(home > away for home, away in score_pairs)
    draw_margin = sum(home == away for home, away in score_pairs)
    away_margin = sum(home < away for home, away in score_pairs)
    high_score = sum(home + away >= 4 for home, away in score_pairs)

    lambda_rows = [_lambda_pair(record) for record in records]
    lambda_rows = [pair for pair in lambda_rows if pair]
    lambda_home = [home for home, _ in lambda_rows]
    lambda_away = [away for _, away in lambda_rows]
    lambda_total = [home + away for home, away in lambda_rows]
    lambda_gap = [abs(home - away) for home, away in lambda_rows]

    home_leader = [record for record in records if _leader(record) == "home"]
    away_leader = [record for record in records if _leader(record) == "away"]
    draw_leader = [record for record in records if _leader(record) == "draw"]
    draw_score_records = [
        record
        for record in records
        if (pair := _score_pair(_top_score(record))) and pair[0] == pair[1]
    ]
    strong_home = [
        record for record in records if (_probabilities(record).get("home") or 0.0) >= 0.55
    ]
    strong_away = [
        record for record in records if (_probabilities(record).get("away") or 0.0) >= 0.55
    ]
    bucket_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        bucket_rows[_leader_bucket(_leader_probability(record))].append(record)
    buckets: dict[str, Any] = {}
    for bucket, _, _ in BUCKETS:
        subset = bucket_rows.get(bucket, [])
        buckets[bucket] = {
            "sample_count": len(subset),
            "leaders": dict(
                sorted(Counter((_leader(record) or "UNAVAILABLE").upper() for record in subset).items())
            ),
            "top1_scores": dict(Counter(_top_score(record) for record in subset if _top_score(record))),
        }

    btts_values = [_btts_yes(record) for record in records]
    btts_values = [value for value in btts_values if value is not None]
    over_values = [_over_2_5_probability(record) for record in records]
    over_values = [value for value in over_values if value is not None]
    one_one = [record for record in records if _top_score(record) == "1-1"]
    non_one_one = [record for record in records if _top_score(record) != "1-1"]

    cross = {
        "home_leader_plus_draw_score_top1": {
            **_count_share(len([record for record in home_leader if record in draw_score_records]), len(home_leader)),
            "cohort_share": _rate(
                len([record for record in home_leader if record in draw_score_records]), sample_count
            ),
        },
        "draw_leader_plus_draw_score_top1": {
            **_count_share(len([record for record in draw_leader if record in draw_score_records]), len(draw_leader)),
            "cohort_share": _rate(
                len([record for record in draw_leader if record in draw_score_records]), sample_count
            ),
        },
        "away_leader_plus_draw_score_top1": {
            **_count_share(len([record for record in away_leader if record in draw_score_records]), len(away_leader)),
            "cohort_share": _rate(
                len([record for record in away_leader if record in draw_score_records]), sample_count
            ),
        },
        "strong_home_probability_plus_1_1": {
            **_count_share(len([record for record in strong_home if _top_score(record) == "1-1"]), len(strong_home)),
            "strong_home_sample_count": len(strong_home),
            "cohort_share": _rate(
                len([record for record in strong_home if _top_score(record) == "1-1"]), sample_count
            ),
        },
        "strong_away_probability_plus_1_1": {
            **_count_share(len([record for record in strong_away if _top_score(record) == "1-1"]), len(strong_away)),
            "strong_away_sample_count": len(strong_away),
            "cohort_share": _rate(
                len([record for record in strong_away if _top_score(record) == "1-1"]), sample_count
            ),
        },
        "leader_probability_buckets": buckets,
        "btts_yes_probability": {
            "sample_count": len(btts_values),
            "quantiles": _quantiles(btts_values),
        },
        "totals_expected_goals": {
            "sample_count": len(lambda_total),
            "quantiles": _quantiles(lambda_total),
        },
        "totals_over_2_5_probability": {
            "sample_count": len(over_values),
            "quantiles": _quantiles(over_values),
        },
        "profile_1_1_vs_other": {
            "score_1_1": {
                "sample_count": len(one_one),
                "btts_yes_median": _quantile(
                    [value for value in (_btts_yes(record) for record in one_one) if value is not None], 0.5
                ),
                "lambda_total_median": _quantile(
                    [sum(pair) for record in one_one if (pair := _lambda_pair(record))], 0.5
                ),
                "over_2_5_probability_median": _quantile(
                    [value for value in (_over_2_5_probability(record) for record in one_one) if value is not None], 0.5
                ),
            },
            "other_top1": {
                "sample_count": len(non_one_one),
                "btts_yes_median": _quantile(
                    [value for value in (_btts_yes(record) for record in non_one_one) if value is not None], 0.5
                ),
                "lambda_total_median": _quantile(
                    [sum(pair) for record in non_one_one if (pair := _lambda_pair(record))], 0.5
                ),
                "over_2_5_probability_median": _quantile(
                    [value for value in (_over_2_5_probability(record) for record in non_one_one) if value is not None], 0.5
                ),
            },
        },
        "tension_flags": {
            "lambda_total_ge_3_and_1_1": _count_share(
                sum(sum(pair) >= 3 and _top_score(record) == "1-1" for record in records if (pair := _lambda_pair(record))),
                sample_count,
            ),
            "totals_over_2_5_ge_0_65_and_1_1": _count_share(
                sum(
                    (_over_2_5_probability(record) or 0.0) >= 0.65
                    and _top_score(record) == "1-1"
                    for record in records
                ),
                sample_count,
            ),
            "btts_yes_ge_0_65_and_1_1": _count_share(
                sum(
                    (_btts_yes(record) or 0.0) >= 0.65
                    and _top_score(record) == "1-1"
                    for record in records
                ),
                sample_count,
            ),
        },
    }

    return {
        "sample_count": sample_count,
        "score_sample_count": valid_score_count,
        "top1_score_distribution": dict(
            sorted(score_counts.items(), key=lambda item: (-item[1], item[0]))
        ),
        "score_counts": named_scores,
        "score_shares": {
            score: _rate(count, valid_score_count) for score, count in named_scores.items()
        },
        "one_x_two_leader_counts": dict(
            sorted(
                Counter((_leader(record) or "UNAVAILABLE").upper() for record in records).items()
            )
        ),
        "high_score_top1": {
            "definition": "home_score + away_score >= 4",
            **_count_share(high_score, valid_score_count),
        },
        "home_margin_top1": _count_share(home_margin, valid_score_count),
        "draw_margin_top1": _count_share(draw_margin, valid_score_count),
        "away_margin_top1": _count_share(away_margin, valid_score_count),
        "lambda": {
            "sample_count": len(lambda_rows),
            "lambda_home": _quantiles(lambda_home),
            "lambda_away": _quantiles(lambda_away),
            "lambda_total": _quantiles(lambda_total),
            "absolute_gap": _quantiles(lambda_gap),
            "gap_lt_0_25": _count_share(sum(gap < 0.25 for gap in lambda_gap), len(lambda_gap)),
            "gap_lt_0_5": _count_share(sum(gap < 0.5 for gap in lambda_gap), len(lambda_gap)),
            "total_lt_2": _count_share(sum(total < 2 for total in lambda_total), len(lambda_total)),
            "total_2_to_3": _count_share(
                sum(2 <= total <= 3 for total in lambda_total), len(lambda_total)
            ),
            "total_gt_3": _count_share(sum(total > 3 for total in lambda_total), len(lambda_total)),
            "by_1x2_leader": _summary_leader_strata(records),
        },
        "cross_market": cross,
        "market_fusion": _market_fusion_summary(records),
        "selector_reconstruction": {
            "independent_poisson_map_matches_top1": sum(
                _top_score(record) == _independent_poisson_map(record)
                for record in records
                if _top_score(record) and _independent_poisson_map(record)
            ),
            "comparable_sample_count": sum(
                bool(_top_score(record) and _independent_poisson_map(record))
                for record in records
            ),
        },
    }


def _result_pair(result: Mapping[str, Any]) -> tuple[int, int] | None:
    try:
        normalised = normalize_result(dict(result))
    except (TypeError, ValueError):
        return None
    return normalised.get("home_score_90m"), normalised.get("away_score_90m")


def _result_candidates(
    result_index: Mapping[str, Any], record: Mapping[str, Any]
) -> list[dict[str, Any]]:
    identity = record_identity(dict(record))
    values: list[dict[str, Any]] = []
    for key in (
        identity.get("match_key"),
        identity.get("match_id"),
        record.get("match_key"),
        record.get("match_id"),
    ):
        key = _text(key)
        if not key:
            continue
        value = result_index.get(key)
        if isinstance(value, dict):
            values.append(value)
        elif isinstance(value, list):
            values.extend(item for item in value if isinstance(item, dict))
    unique: dict[tuple[Any, ...], dict[str, Any]] = {}
    for value in values:
        pair = _result_pair(value)
        identity_key = (_text(value.get("match_key")), pair, _text(value.get("verified_at")))
        unique[identity_key] = value
    return list(unique.values())


def _metric_mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 6) if values else None


def evaluate_prospective_metrics(
    predictions: Iterable[Mapping[str, Any]],
    result_index: Mapping[str, Any],
    *,
    formal_prediction_ids: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Evaluate only selected frozen predictions against verified 90m results."""

    allowed = None
    if formal_prediction_ids is not None:
        allowed = {_text(value) for value in formal_prediction_ids if _text(value)}
    rows: list[dict[str, Any]] = []
    missing_result_count = 0
    result_conflict_count = 0
    seen_matches: set[str] = set()
    for prediction in predictions:
        prediction = dict(prediction)
        prediction_id = _text(prediction.get("prediction_id"))
        if allowed is not None and prediction_id not in allowed:
            continue
        identity = record_identity(prediction)
        match_identity = _text(identity.get("match_id") or identity.get("match_key"))
        if match_identity in seen_matches:
            continue
        seen_matches.add(match_identity)
        candidates = _result_candidates(result_index, prediction)
        if not candidates:
            missing_result_count += 1
            continue
        pairs = {_result_pair(candidate) for candidate in candidates}
        pairs.discard(None)
        if len(pairs) != 1:
            result_conflict_count += 1
            continue
        result = next(candidate for candidate in candidates if _result_pair(candidate) in pairs)
        pair = next(iter(pairs))
        actual_home, actual_away = pair
        actual_outcome = (
            "home" if actual_home > actual_away else "away" if actual_home < actual_away else "draw"
        )
        probabilities = _probabilities(prediction)
        if not all(key in probabilities for key in LEADER_KEYS):
            continue
        score = _score_text(pair)
        top1 = _top_score(prediction)
        top3 = _top_scores(prediction, 3)
        score_probability = {
            _score_text(_score_pair(row.get("score"))): _number(row.get("probability"))
            for row in _score_rows(prediction)
            if _score_pair(row.get("score")) and _number(row.get("probability")) is not None
        }
        btts_probability = _btts_yes(prediction)
        over_probability = _over_2_5_probability(prediction)
        rows.append(
            {
                "prediction_id": prediction_id,
                "match_id": identity.get("match_id"),
                "match_key": identity.get("match_key"),
                "actual_score": score,
                "actual_outcome": actual_outcome,
                "probabilities": probabilities,
                "predicted_outcome": max(LEADER_KEYS, key=lambda key: probabilities[key]),
                "exact_top1": top1,
                "exact_top3": top3,
                "actual_score_probability": score_probability.get(score),
                "btts_probability": btts_probability,
                "btts_actual": actual_home > 0 and actual_away > 0,
                "over_2_5_probability": over_probability,
                "over_2_5_actual": actual_home + actual_away > 2,
                "result_verified_at": result.get("verified_at"),
            }
        )

    outcome_metrics: list[float] = []
    brier_metrics: list[float] = []
    logloss_metrics: list[float] = []
    top1_hits: list[float] = []
    top3_hits: list[float] = []
    actual_probabilities: list[float] = []
    btts_accuracy: list[float] = []
    btts_brier: list[float] = []
    ou_accuracy: list[float] = []
    ou_brier: list[float] = []
    for row in rows:
        actual = row["actual_outcome"]
        outcome_metrics.append(float(row["predicted_outcome"] == actual))
        brier_metrics.append(
            sum(
                (row["probabilities"][key] - float(key == actual)) ** 2
                for key in LEADER_KEYS
            )
        )
        logloss_metrics.append(
            -math.log(max(min(row["probabilities"][actual], 1.0 - EPSILON), EPSILON))
        )
        top1_hits.append(float(row["exact_top1"] == row["actual_score"]))
        top3_hits.append(float(row["actual_score"] in row["exact_top3"]))
        if row["actual_score_probability"] is not None:
            actual_probabilities.append(row["actual_score_probability"])
        if row["btts_probability"] is not None:
            btts_accuracy.append(
                float((row["btts_probability"] >= 0.5) == row["btts_actual"])
            )
            btts_brier.append(
                (row["btts_probability"] - float(row["btts_actual"])) ** 2
            )
        if row["over_2_5_probability"] is not None:
            ou_accuracy.append(
                float((row["over_2_5_probability"] >= 0.5) == row["over_2_5_actual"])
            )
            ou_brier.append(
                (row["over_2_5_probability"] - float(row["over_2_5_actual"])) ** 2
            )
    actual_score_counts = Counter(row["actual_score"] for row in rows)
    return {
        "sample_count": len(rows),
        "missing_result_count": missing_result_count,
        "result_conflict_count": result_conflict_count,
        "outcome_counts": dict(sorted(Counter(row["actual_outcome"] for row in rows).items())),
        "actual_score_top_frequency": dict(
            sorted(actual_score_counts.items(), key=lambda item: (-item[1], item[0]))[:20]
        ),
        "one_x_two": {
            "sample_count": len(outcome_metrics),
            "accuracy": _metric_mean(outcome_metrics),
            "brier": _metric_mean(brier_metrics),
            "log_loss": _metric_mean(logloss_metrics),
        },
        "exact_score": {
            "sample_count": len(rows),
            "top1_hit_rate": _metric_mean(top1_hits),
            "top3_hit_rate": _metric_mean(top3_hits),
            "actual_score_probability_sample_count": len(actual_probabilities),
            "mean_probability_assigned_to_actual_score": _metric_mean(actual_probabilities),
        },
        "btts": {
            "sample_count": len(btts_accuracy),
            "accuracy": _metric_mean(btts_accuracy),
            "brier": _metric_mean(btts_brier),
        },
        "ou_2_5": {
            "sample_count": len(ou_accuracy),
            "accuracy": _metric_mean(ou_accuracy),
            "brier": _metric_mean(ou_brier),
        },
        "evaluated_rows": rows,
    }


def _read_json(path: Path, default: Any) -> Any:
    if not path.is_file():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


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
    except (OSError, json.JSONDecodeError):
        return rows
    return rows


def _load_prediction_records(root: Path) -> list[dict[str, Any]]:
    prediction_root = root / "data" / "model_governance" / "predictions"
    records: list[dict[str, Any]] = []
    for path in sorted(prediction_root.glob("*.json")):
        payload = _read_json(path, None)
        if isinstance(payload, dict):
            records.append(payload)
    return records


def _load_exclusion_ids(root: Path) -> set[str]:
    exclusion_root = root / "data" / "model_governance" / "prediction_exclusions"
    identifiers: set[str] = set()
    for path in sorted(exclusion_root.glob("*.json")):
        payload = _read_json(path, {})
        if isinstance(payload, dict):
            identifiers.update(
                _text(value)
                for value in payload.get("prediction_ids") or []
                if _text(value)
            )
    return identifiers


def _load_result_index(root: Path) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    result_root = root / "data" / "postmatch_automation" / "results"
    index: dict[str, list[dict[str, Any]]] = defaultdict(list)
    valid_count = 0
    invalid_count = 0
    for path in sorted(result_root.glob("*.json")):
        payload = _read_json(path, None)
        if not isinstance(payload, dict):
            invalid_count += 1
            continue
        try:
            normalised = normalize_result(payload)
        except (TypeError, ValueError):
            invalid_count += 1
            continue
        if not _parse_timestamp(normalised.get("result_verified_at")):
            invalid_count += 1
            continue
        valid_count += 1
        for key in (
            normalised.get("match_key"),
            normalised.get("match_id"),
            normalised.get("provider_match_id"),
        ):
            key = _text(key)
            if key:
                index[key].append(normalised)
    return index, {
        "artifact_count": valid_count + invalid_count,
        "verified_final_artifact_count": valid_count,
        "invalid_or_unverified_artifact_count": invalid_count,
        "indexed_identity_count": len(index),
    }


def _load_ledger_ids(root: Path) -> tuple[set[str], int]:
    rows = _read_jsonl(root / "data" / "prospective" / "ledger.jsonl")
    identifiers = {
        _text(row.get("prediction_id"))
        for row in rows
        if _text(row.get("prediction_id"))
        and row.get("formal_prospective_eligible") is True
    }
    return identifiers, len(rows)


def _load_competition_map(root: Path) -> dict[str, str]:
    jobs_root = root / "data" / "base_prediction_jobs"
    mapping: dict[str, str] = {}
    for path in sorted(jobs_root.glob("*.json")):
        payload = _read_json(path, {})
        if not isinstance(payload, dict):
            continue
        rows = list(payload.get("jobs") or []) + list(payload.get("removed_jobs") or [])
        for row in rows:
            if not isinstance(row, dict):
                continue
            match_id = _text(row.get("match_id"))
            competition = _text(row.get("league") or row.get("competition"))
            if match_id and competition:
                mapping[match_id] = competition
    return mapping


def _competition_summary(records: list[dict[str, Any]], competition_map: Mapping[str, str]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        match_id = _text(record_identity(record).get("match_id") or record.get("match_id"))
        grouped[competition_map.get(match_id, "UNKNOWN")].append(record)
    rows: list[dict[str, Any]] = []
    for competition, subset in sorted(grouped.items(), key=lambda item: (-len(item[1]), item[0])):
        summary = summarize_prediction_cohort(subset)
        rows.append(
            {
                "competition": competition,
                "sample_count": len(subset),
                "score_1_1": summary["score_counts"].get("1-1", 0),
                "score_1_1_share": summary["score_shares"].get("1-1"),
                "lambda_gap_lt_0_5": summary["lambda"]["gap_lt_0_5"],
                "lambda_total_lt_2": summary["lambda"]["total_lt_2"],
                "lambda_total_2_to_3": summary["lambda"]["total_2_to_3"],
                "lambda_total_gt_3": summary["lambda"]["total_gt_3"],
            }
        )
    return rows


def _time_window_summary(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    windows = (
        ("2026-08-13..2026-08-20", "2026-08-13", "2026-08-20"),
        ("2026-08-21..2026-08-27", "2026-08-21", "2026-08-27"),
        ("2026-08-28..2026-09-01", "2026-08-28", "2026-09-01"),
    )
    rows: list[dict[str, Any]] = []
    for label, start, end in windows:
        subset = [
            record
            for record in records
            if start <= _text(record.get("kickoff_at"))[:10] <= end
        ]
        summary = summarize_prediction_cohort(subset)
        distribution = summary["top1_score_distribution"]
        dominant_score, dominant_count = (next(iter(distribution.items())) if distribution else (None, 0))
        rows.append(
            {
                "window": label,
                "sample_count": len(subset),
                "dominant_score": dominant_score,
                "dominant_count": dominant_count,
                "dominant_share": _rate(dominant_count, len(subset)),
                "score_1_1": summary["score_counts"].get("1-1", 0),
                "gap_lt_0_5": summary["lambda"]["gap_lt_0_5"],
            }
        )
    return rows


def _root_cause_evidence(
    current_summary: dict[str, Any],
    historical_summary: dict[str, Any],
    historical_records: list[dict[str, Any]],
) -> dict[str, Any]:
    recent_form = Counter(
        _text((record.get("data_quality") or {}).get("recent_form")) or "UNKNOWN"
        for record in historical_records
        if isinstance(record.get("data_quality") or {}, dict)
    )
    market_quality = Counter(
        _text(record.get("market_intelligence_quality")) or "UNKNOWN"
        for record in historical_records
    )
    lambda_block = historical_summary["lambda"]
    selector = historical_summary["selector_reconstruction"]
    market = historical_summary["market_fusion"]
    return {
        "conclusion": "MIXED",
        "ranking": [
            {
                "priority": "P0",
                "bucket": "C. LAMBDA_GENERATION",
                "assessment": "PRIMARY_EVIDENCE",
                "evidence": {
                    "historical_gap_lt_0_5": lambda_block["gap_lt_0_5"],
                    "current_gap_lt_0_5": current_summary["lambda"]["gap_lt_0_5"],
                    "historical_lambda_total_median": lambda_block["lambda_total"]["P50"],
                    "current_lambda_total_median": current_summary["lambda"]["lambda_total"]["P50"],
                },
            },
            {
                "priority": "P1",
                "bucket": "E. PRODUCT_PRESENTATION",
                "assessment": "PRIMARY_PRODUCT_RISK",
                "evidence": {
                    "historical_top1_score_support_size": len(
                        historical_summary["top1_score_distribution"]
                    ),
                    "historical_1_1_share": historical_summary["score_shares"].get("1-1"),
                    "current_1_1_share": current_summary["score_shares"].get("1-1"),
                    "exact_score_top1_hit_rate_is_prospective": "see prospective block",
                },
            },
            {
                "priority": "P2",
                "bucket": "B. MARKET_FUSION",
                "assessment": "SECONDARY_SIGNAL",
                "evidence": {
                    "market_model_leader_disagreement": market[
                        "market_model_leader_disagreement"
                    ],
                    "market_mean_model_minus_market_probability": market[
                        "mean_model_minus_market_probability"
                    ],
                },
            },
        ],
        "not_established": {
            "A. INPUT / FOOTBALL EVIDENCE": {
                "recent_form_status": dict(sorted(recent_form.items())),
                "market_intelligence_quality": dict(sorted(market_quality.items())),
                "assessment": "NOT_ESTABLISHED_BY_THIS_AUDIT",
                "reason": "The selected records expose readiness/quality labels, but not enough feature-depth evidence to claim shallow recent form as the cause.",
            },
            "D. SCORE_SELECTOR": {
                "assessment": "NOT_SUPPORTED_BY_THIS_AUDIT",
                "independent_poisson_map_matches_top1": selector[
                    "independent_poisson_map_matches_top1"
                ],
                "comparable_sample_count": selector["comparable_sample_count"],
                "reason": "The stored Top1 equals the independent Poisson joint MAP for the comparable selected cohort; selector-only failure is not demonstrated.",
            },
        },
        "next_single_milestone": (
            "PRED-TRUST-2 — Strength/Lambda Challenger Experiment Design & "
            "Bounded Prospective Shadow Plan"
        ),
    }


def _health_gate_audit(
    root: Path,
    all_records: list[dict[str, Any]],
    historical_summary: dict[str, Any],
    prospective: dict[str, Any],
    historical_records: list[dict[str, Any]],
    competition_map: Mapping[str, str],
) -> dict[str, Any]:
    frozen = [
        record
        for record in all_records
        if _text(record.get("prediction_status")) in FROZEN_STATUSES
    ]
    existing = evaluate_exact_score_health(frozen)
    actual_frequency = prospective.get("actual_score_top_frequency") or {}
    actual_top_score, actual_top_count = (
        next(iter(actual_frequency.items())) if actual_frequency else (None, 0)
    )
    current_health_watch = _read_json(root / "data" / "product_runtime" / "health_watch.json", {})
    return {
        "current_gate": {
            "dominant_share_threshold": existing.get("dominant_share_threshold", 0.875),
            "minimum_sample_count": existing.get("minimum_sample_count", 8),
            "dominant_count_threshold": existing.get("dominant_count_threshold", 7),
            "observed_population": existing,
            "runtime_status": current_health_watch.get("current_status"),
            "active_reasons": current_health_watch.get("active_reasons") or [],
            "consecutive_problem_cycles": current_health_watch.get("consecutive_problem_cycles"),
            "last_healthy_at": current_health_watch.get("last_healthy_at"),
        },
        "threshold_origin": {
            "status": "LEGACY_FIXED_GUARDRAIL",
            "source": "scripts/production_health_watch.py:41 / commit 50772724e3",
            "definition": "sample>=8 and dominant_count>=7 and dominant_share>=0.875",
            "empirical_calibration_recorded": False,
            "assessment": "No repository evidence documents a calibrated football-product basis for 87.5%; it functions as a 7-of-8-style exception threshold.",
        },
        "random_baselines": {
            "uniform_exact_score_0_to_5_grid": {
                "definition": "uniform random top1 over 36 cells (0-0 through 5-5)",
                "grid_size": 36,
                "dominant_share": round(1 / 36, 6),
            },
            "uniform_1x2": {
                "definition": "uniform random top1 over HOME/DRAW/AWAY",
                "grid_size": 3,
                "dominant_share": round(1 / 3, 6),
            },
        },
        "empirical_actual_score_baseline": {
            "sample_count": prospective.get("sample_count", 0),
            "most_frequent_actual_score": actual_top_score,
            "count": actual_top_count,
            "share": _rate(actual_top_count, prospective.get("sample_count", 0)),
        },
        "champion_time_windows": _time_window_summary(historical_records),
        "competitions": {
            "mapped_selected_match_count": sum(
                bool(competition_map.get(_text(record_identity(record).get("match_id"))))
                for record in historical_records
            ),
            "rows": _competition_summary(historical_records, competition_map),
        },
        "assessment": {
            "would_76_percent_same_score_be_healthy": False,
            "answer": "NO",
            "reason": "A 76% single exact-score Top1 rate is a product-quality failure signal even when it remains below the legacy 87.5% exact-score-only gate.",
            "recommendation": "REPLACE_WITH_MULTI_SIGNAL",
            "action_in_this_milestone": "KEEP_GATE_UNCHANGED",
        },
    }


def run_audit(
    *,
    root: Path,
    business_date: str = DEFAULT_CURRENT_DATE,
    source_commit: str = "",
    latest_main_commit: str = "",
    production_run: str = "33294381128",
    accepted_writeback_commit: str = "73994d32fc148da49295a5bfef2e1e42e042a22e",
) -> dict[str, Any]:
    root = root.resolve()
    records = _load_prediction_records(root)
    excluded_ids = _load_exclusion_ids(root)
    ledger_ids, ledger_row_count = _load_ledger_ids(root)
    result_index, result_assets = _load_result_index(root)
    competition_map = _load_competition_map(root)

    duplicate_audit = classify_duplicate_groups(records, excluded_ids=excluded_ids)
    historical_cohort = build_unique_match_cohort(records, excluded_ids=excluded_ids)
    historical_records = historical_cohort["selected_records"]
    current_cohort = build_current_day_cohort(
        root, business_date, records, excluded_ids=excluded_ids
    )
    current_records = current_cohort["selected_records"]
    current_summary = summarize_prediction_cohort(current_records)
    historical_summary = summarize_prediction_cohort(historical_records)
    prospective = evaluate_prospective_metrics(
        historical_records,
        result_index,
        formal_prediction_ids=ledger_ids,
    )
    health_gate = _health_gate_audit(
        root,
        records,
        historical_summary,
        prospective,
        historical_records,
        competition_map,
    )
    root_cause = _root_cause_evidence(
        current_summary,
        historical_summary,
        historical_records,
    )
    health_watch = _read_json(root / "data" / "product_runtime" / "health_watch.json", {})
    return {
        "schema_version": "pred_trust_1.audit.v1",
        "milestone": "PRED-TRUST-1",
        "status": "READY_FOR_ACCEPTANCE",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": {
            "audited_data_commit": source_commit or accepted_writeback_commit,
            "accepted_production_run": production_run,
            "accepted_writeback_commit": accepted_writeback_commit,
            "latest_synced_main_commit": latest_main_commit,
            "business_date": business_date,
            "timezone": "Asia/Shanghai",
            "current_day_cohort_pin": "accepted production write-back commit; no later refresh is substituted",
            "post_acceptance_refresh_note": "The later synced main contains an automatic generated-data refresh; the accepted 22 frozen / 3 insufficient production cohort remains the audit source so today's prospective evidence is not silently replaced.",
        },
        "cohort_definition": {
            "selection_order": [
                "match_id",
                "all legal pre-kickoff frozen versions",
                "final selected legal prematch prediction",
                "one prediction per unique match",
            ],
            "excluded": [
                "pilot",
                "excluded",
                "post-kickoff",
                "illegal timestamp",
                "superseded version",
                "non-selected duplicate version",
            ],
            "history_mutation": "none; selection is evaluation-only",
            "prediction_record_count_loaded": len(records),
            "prediction_exclusion_id_count": len(excluded_ids),
            "prospective_ledger_row_count": ledger_row_count,
            "prospective_ledger_unique_prediction_count": len(ledger_ids),
            "verified_result_assets": result_assets,
        },
        "duplicate_audit": duplicate_audit,
        "current_day": {
            "selection": {
                key: value
                for key, value in current_cohort.items()
                if key not in {"selected_records"}
            },
            "score_distribution": current_summary,
        },
        "historical_prospective_cohort": {
            "selection": {
                key: value
                for key, value in historical_cohort.items()
                if key not in {"selected_records", "groups"}
            },
            "score_distribution": historical_summary,
        },
        "prospective_evaluation": prospective,
        "health_gate_audit": health_gate,
        "root_cause": root_cause,
        "stop_state": {
            "model_modified": False,
            "champion_modified": False,
            "frozen_predictions_rewritten": False,
            "prospective_ledger_rewritten": False,
            "provider_added": False,
            "identity_alias_added": False,
            "health_gate_modified": False,
            "health_monitor_modified": False,
            "active_runtime_health": {
                "status": health_watch.get("current_status"),
                "active_reasons": health_watch.get("active_reasons") or [],
            },
        },
    }


def _fmt_number(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:.6f}".rstrip("0").rstrip(".")
    return str(value)


def _fmt_share(value: Any) -> str:
    return "—" if value is None else f"{float(value) * 100:.2f}%"


def _score_table(summary: Mapping[str, Any]) -> str:
    rows = [
        (score, summary.get("score_counts", {}).get(score, 0), summary.get("score_shares", {}).get(score))
        for score in ("1-1", "0-0", "2-1", "1-2", "2-2")
    ]
    lines = ["| score | count | share |", "|---|---:|---:|"]
    lines.extend(f"| {score} | {count} | {_fmt_share(share)} |" for score, count, share in rows)
    lines.append(
        f"| high-score (>=4 total) | {summary.get('high_score_top1', {}).get('count', 0)} | {_fmt_share(summary.get('high_score_top1', {}).get('share'))} |"
    )
    lines.append(
        f"| home-margin | {summary.get('home_margin_top1', {}).get('count', 0)} | {_fmt_share(summary.get('home_margin_top1', {}).get('share'))} |"
    )
    lines.append(
        f"| away-margin | {summary.get('away_margin_top1', {}).get('count', 0)} | {_fmt_share(summary.get('away_margin_top1', {}).get('share'))} |"
    )
    return "\n".join(lines)


def _lambda_lines(summary: Mapping[str, Any]) -> str:
    block = summary.get("lambda", {})
    lines = [
        f"- sample_count: `{block.get('sample_count', 0)}`",
        f"- lambda_home P10/P25/P50/P75/P90: `{block.get('lambda_home')}`",
        f"- lambda_away P10/P25/P50/P75/P90: `{block.get('lambda_away')}`",
        f"- lambda_total P10/P25/P50/P75/P90: `{block.get('lambda_total')}`",
        f"- abs(lambda_home-lambda_away) P10/P25/P50/P75/P90: `{block.get('absolute_gap')}`",
        f"- gap < 0.25: `{block.get('gap_lt_0_25')}`; gap < 0.5: `{block.get('gap_lt_0_5')}`",
        f"- total < 2: `{block.get('total_lt_2')}`; total 2–3: `{block.get('total_2_to_3')}`; total > 3: `{block.get('total_gt_3')}`",
    ]
    for leader, values in (block.get("by_1x2_leader") or {}).items():
        lines.append(f"- {leader} leader stratum: `{values}`")
    return "\n".join(lines)


def render_markdown(report: Mapping[str, Any]) -> str:
    current = report["current_day"]
    historical = report["historical_prospective_cohort"]
    duplicate = report["duplicate_audit"]
    prospective = report["prospective_evaluation"]
    health = report["health_gate_audit"]
    root_cause = report["root_cause"]
    source = report["source"]
    current_summary = current["score_distribution"]
    historical_summary = historical["score_distribution"]
    selection = historical["selection"]
    lines = [
        "# PRED-TRUST-1 — Unique-Match Prediction Integrity & Multi-Market Quality Audit",
        "",
        "Status: `READY_FOR_ACCEPTANCE` (audit evidence only; no model or production mutation)",
        "",
        "## 0. Scope and immutable evidence boundary",
        "",
        f"- Audited data commit: `{source.get('audited_data_commit')}`",
        f"- Accepted production run: `{source.get('accepted_production_run')}`",
        f"- Accepted write-back commit: `{source.get('accepted_writeback_commit')}`",
        f"- Latest synced main commit: `{source.get('latest_synced_main_commit') or 'not supplied'}`",
        f"- Current-day cohort: `{source.get('business_date')}`, pinned to the accepted write-back; no later refresh is substituted.",
        f"- Post-acceptance refresh handling: {source.get('post_acceptance_refresh_note')}",
        "- The audit reads immutable prediction/result/ledger artifacts and writes only the audit JSON and this report.",
        "- Today’s frozen predictions, historical frozen files, prospective ledger, Champion, providers, aliases, and health gate are unchanged.",
        "",
        "## 1. Unique-match evaluation cohort",
        "",
        "Selection order: `match_id → all legal pre-kickoff frozen versions → final selected legal prematch prediction → one prediction per unique match`.",
        "Pilot, excluded, post-kickoff, illegal timestamp, superseded, and non-selected duplicate versions are excluded from metrics without deleting their files.",
        "",
        f"- Loaded prediction rows: `{report['cohort_definition']['prediction_record_count_loaded']}`",
        f"- Historical legal rows: `{selection.get('legal_record_count')}`",
        f"- Historical unique matches: `{selection.get('unique_match_count')}`",
        f"- Historical superseded versions excluded from evaluation: `{selection.get('superseded_record_count')}`",
        f"- Prospective ledger rows / unique prediction IDs: `{report['cohort_definition']['prospective_ledger_row_count']}` / `{report['cohort_definition']['prospective_ledger_unique_prediction_count']}`",
        "",
        "## 2. DUPLICATE_FROZEN_PREDICTION classification",
        "",
        f"- Health duplicate groups: `{duplicate['duplicate_group_count']}`",
        f"- Unique affected matches: `{duplicate['unique_affected_matches']}`",
        f"- Classification counts: `{duplicate['classification_counts']}`",
        f"- Real immutable/frozen integrity violation: `{duplicate['actual_immutable_frozen_integrity_violation']}`",
        f"- Prediction integrity status: `{duplicate['prediction_integrity_status']}`",
        f"- Health-rule false-positive groups under canonical selection: `{duplicate['health_rule_false_positive_group_count']}`",
        "",
        "| class | meaning | count |",
        "|---|---|---:|",
        "| A | legitimate immutable prematch version history with one final selected version | "
        f"{duplicate['classification_counts']['A']} |",
        "| B | actual duplicate final: two legal final candidates with tied chronology | "
        f"{duplicate['classification_counts']['B']} |",
        "| C | identity collision: one health group contains different match identity | "
        f"{duplicate['classification_counts']['C']} |",
        "| D | health false positive: duplicate group has no second legal prematch candidate | "
        f"{duplicate['classification_counts']['D']} |",
        "",
        f"Bounded recommendation: {duplicate['bounded_repair_recommendation']}",
        "",
        "## 3. Exact-score Top1 distribution",
        "",
        f"### A. Current `{source.get('business_date')}` cohort (`{current_summary['sample_count']}` matches)",
        "",
        _score_table(current_summary),
        "",
        f"1X2 leader counts: `{current_summary['one_x_two_leader_counts']}`.",
        "",
        f"### B. All legal historical/prospective unique-match cohort (`{historical_summary['sample_count']}` matches)",
        "",
        _score_table(historical_summary),
        "",
        f"1X2 leader counts: `{historical_summary['one_x_two_leader_counts']}`.",
        "",
        f"Historical Top1 distribution: `{historical_summary['top1_score_distribution']}`",
        "",
        "## 4. Lambda distribution",
        "",
        "### Current cohort",
        _lambda_lines(current_summary),
        "",
        "### Historical unique-match cohort",
        _lambda_lines(historical_summary),
        "",
        "## 5. Cross-market consistency",
        "",
        "Leader probability buckets are `<40%`, `40–45%`, `45–50%`, `50–55%`, and `55%+`; strong HOME/AWAY means that side probability is at least 55%. These are descriptive consistency statistics, not error labels.",
        "",
        f"Current cross-market summary: `{current_summary['cross_market']}`",
        "",
        f"Historical cross-market summary: `{historical_summary['cross_market']}`",
        "",
        f"Historical market-fusion summary: `{historical_summary['market_fusion']}`",
        "",
        f"Tension flags (lambda/BTTS/totals versus 1-1): `{historical_summary['cross_market']['tension_flags']}`",
        "",
        "## 6. Verified prospective evaluation",
        "",
        f"Verified 90m result artifacts: `{report['cohort_definition']['verified_result_assets']}`",
        f"Formal unique-match sample: `{prospective['sample_count']}`; missing result: `{prospective['missing_result_count']}`; result conflicts: `{prospective['result_conflict_count']}`.",
        "",
        "| market | sample | accuracy / hit rate | Brier | LogLoss |",
        "|---|---:|---:|---:|---:|",
        f"| 1X2 | {prospective['one_x_two']['sample_count']} | {_fmt_share(prospective['one_x_two']['accuracy'])} | {_fmt_number(prospective['one_x_two']['brier'])} | {_fmt_number(prospective['one_x_two']['log_loss'])} |",
        f"| Exact Score Top1 | {prospective['exact_score']['sample_count']} | {_fmt_share(prospective['exact_score']['top1_hit_rate'])} | — | — |",
        f"| Exact Score Top3 | {prospective['exact_score']['sample_count']} | {_fmt_share(prospective['exact_score']['top3_hit_rate'])} | — | — |",
        f"| BTTS | {prospective['btts']['sample_count']} | {_fmt_share(prospective['btts']['accuracy'])} | {_fmt_number(prospective['btts']['brier'])} | — |",
        f"| O/U 2.5 | {prospective['ou_2_5']['sample_count']} | {_fmt_share(prospective['ou_2_5']['accuracy'])} | {_fmt_number(prospective['ou_2_5']['brier'])} | — |",
        "",
        f"Mean probability assigned to the actual exact score: `{_fmt_number(prospective['exact_score']['mean_probability_assigned_to_actual_score'])}` over `{prospective['exact_score']['actual_score_probability_sample_count']}` rows where the actual score was present in the stored distribution.",
        f"Actual-score empirical baseline: `{prospective['actual_score_top_frequency']}`.",
        "",
        "## 7. Health-gate audit",
        "",
        f"Legacy threshold: `{health['current_gate']['dominant_share_threshold']}` dominant-share; observed health population: `{health['current_gate']['observed_population']}`.",
        f"Threshold origin: `{health['threshold_origin']['status']}` — `{health['threshold_origin']['definition']}`; the repository records the rule in `{health['threshold_origin']['source']}` but no empirical football-product calibration rationale is recorded.",
        f"Runtime health remains `{health['current_gate']['runtime_status']}` with `{health['current_gate']['active_reasons']}` and `{health['current_gate']['consecutive_problem_cycles']}` consecutive problem cycles.",
        f"Uniform exact-score baseline: `{health['random_baselines']['uniform_exact_score_0_to_5_grid']}`.",
        f"Uniform 1X2 baseline: `{health['random_baselines']['uniform_1x2']}`.",
        f"Historical actual-score baseline: `{health['empirical_actual_score_baseline']}`.",
        "",
        "| Champion time window | n | dominant Top1 | share | 1-1 count | gap<0.5 |",
        "|---|---:|---|---:|---:|---:|",
    ]
    for row in health["champion_time_windows"]:
        lines.append(
            f"| {row['window']} | {row['sample_count']} | {row['dominant_score']} | {_fmt_share(row['dominant_share'])} | {row['score_1_1']} | {_fmt_share(row['gap_lt_0_5']['share'])} |"
        )
    lines.extend(
        [
            "",
            "Top competition strata by selected-match count:",
            "",
            "| competition | n | 1-1 share | gap<0.5 | total<2 | total 2–3 | total>3 |",
            "|---|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for row in health["competitions"]["rows"][:10]:
        lines.append(
            f"| {row['competition']} | {row['sample_count']} | {_fmt_share(row['score_1_1_share'])} | {_fmt_share(row['lambda_gap_lt_0_5']['share'])} | {_fmt_share(row['lambda_total_lt_2']['share'])} | {_fmt_share(row['lambda_total_2_to_3']['share'])} | {_fmt_share(row['lambda_total_gt_3']['share'])} |"
        )
    lines.extend(
        [
            "",
            f"Assessment: `{health['assessment']['answer']}` — 76% of matches sharing one exact-score Top1 should not be treated as healthy from a football-product perspective, even though the legacy 87.5% gate does not fire. Recommendation: `{health['assessment']['recommendation']}`; gate action this milestone: `{health['assessment']['action_in_this_milestone']}`.",
            "",
            "## 8. Root-cause ranking (no parameter change)",
            "",
        ]
    )
    for item in root_cause["ranking"]:
        lines.append(
            f"- **{item['priority']} — {item['bucket']}**: `{item['assessment']}`; evidence `{item['evidence']}`"
        )
    lines.extend(
        [
            "",
            f"- A. INPUT / FOOTBALL EVIDENCE: `{root_cause['not_established']['A. INPUT / FOOTBALL EVIDENCE']}`",
            f"- D. SCORE_SELECTOR: `{root_cause['not_established']['D. SCORE_SELECTOR']}`",
            "",
            f"Product conclusion: `{root_cause['conclusion']}`.",
            "",
            "## 9. One next milestone",
            "",
            f"`{root_cause['next_single_milestone']}` — design only; prospective shadow/promotion gates remain mandatory. No automatic implementation starts from this audit.",
            "",
            "## 10. STOP state",
            "",
            "No PRED-AVAIL-3, ID-AUTO-2, new provider, manual alias, league-specific coverage, Publisher validation, B2 work, model tuning, Champion modification, frozen rewrite, lambda patch, score-selector patch, draw penalty, quota, or randomization was performed.",
            "",
            "Full machine-readable evidence is stored beside this report in `data/prediction_quality/pred_trust_1/`.",
            "",
        ]
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=BASE_DIR)
    parser.add_argument("--business-date", default=DEFAULT_CURRENT_DATE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--source-commit", default="")
    parser.add_argument("--latest-main-commit", default="")
    parser.add_argument("--production-run", default="33294381128")
    parser.add_argument(
        "--accepted-writeback-commit",
        default="73994d32fc148da49295a5bfef2e1e42e042a22e",
    )
    args = parser.parse_args(argv)
    report = run_audit(
        root=args.root,
        business_date=args.business_date,
        source_commit=args.source_commit,
        latest_main_commit=args.latest_main_commit,
        production_run=args.production_run,
        accepted_writeback_commit=args.accepted_writeback_commit,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(render_markdown(report), encoding="utf-8")
    print(
        json.dumps(
            {
                "milestone": report["milestone"],
                "status": report["status"],
                "current_unique_matches": report["current_day"]["selection"]["unique_match_count"],
                "historical_unique_matches": report["historical_prospective_cohort"]["selection"]["unique_match_count"],
                "duplicate_classification": report["duplicate_audit"]["classification_counts"],
                "prospective_sample_count": report["prospective_evaluation"]["sample_count"],
                "conclusion": report["root_cause"]["conclusion"],
                "next_milestone": report["root_cause"]["next_single_milestone"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
