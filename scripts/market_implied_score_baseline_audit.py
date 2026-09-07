#!/usr/bin/env python3
"""Research-only market-implied full-time score baseline audit.

The audit consumes only immutable Champion records, their content-addressed
input snapshots, the existing prospective ledger and already persisted
regulation-only result artifacts.  It never fetches a provider, rewrites a
frozen record, or changes any production model path.
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
import subprocess
import sys
from typing import Any, Iterable, Mapping


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

try:  # Direct execution from the repository root.
    from market_contracts import split_quarter_line
    from model_governance import load_frozen_prediction, load_input_snapshot
    from prematch_versioning import (
        _identity as record_identity,
        _is_formal_prematch,
        _parse_timestamp,
        select_latest_legal_prematch,
    )
    from prospective_settlement import is_formally_eligible, normalize_result
except ImportError:  # Package imports used by focused tests.
    from scripts.market_contracts import split_quarter_line
    from scripts.model_governance import load_frozen_prediction, load_input_snapshot
    from scripts.prematch_versioning import (
        _identity as record_identity,
        _is_formal_prematch,
        _parse_timestamp,
        select_latest_legal_prematch,
    )
    from scripts.prospective_settlement import is_formally_eligible, normalize_result


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = ROOT / "artifacts" / "market-implied-score-baseline-1"
AUDIT_SCHEMA_VERSION = "market_implied_score_baseline_audit.v1"
ISSUE_NUMBER = 189
OBSERVATION_UNIT = "one football match = one unique match_key"
RESULT_SCOPE = "regulation_90m_plus_stoppage"
OUTCOMES = ("home", "draw", "away")
EPSILON = 1e-12
PARITY_TOLERANCE = 1e-5
MAX_GOALS = 20
OU_SOLVE_LOWER = 0.001
OU_SOLVE_UPPER = 20.0
OU_SOLVE_ITERATIONS = 90
SHARE_SOLVE_LOWER = 0.01
SHARE_SOLVE_UPPER = 0.99
SHARE_SOLVE_ITERATIONS = 70
BOOTSTRAP_ITERATIONS = 2000
BOOTSTRAP_SEED = 189
ARTIFACT_FLOAT_DECIMALS = 6
MIN_PAIRED_SAMPLE_FOR_MEANINGFUL_DECISION = 50

HORIZON_BANDS = (
    {"id": "T_0_TO_60M", "label": "T-0 to <60m", "lower_minutes": 0.0, "upper_minutes": 60.0},
    {"id": "T_60_TO_180M", "label": "T-60m to <3h", "lower_minutes": 60.0, "upper_minutes": 180.0},
    {"id": "T_3_TO_6H", "label": "T-3h to <6h", "lower_minutes": 180.0, "upper_minutes": 360.0},
    {"id": "T_6_TO_12H", "label": "T-6h to <12h", "lower_minutes": 360.0, "upper_minutes": 720.0},
    {"id": "T_12_TO_24H", "label": "T-12h to <24h", "lower_minutes": 720.0, "upper_minutes": 1440.0},
    {"id": "T_24H_PLUS", "label": "T-24h+", "lower_minutes": 1440.0, "upper_minutes": None},
)

SOURCE_PATHS = (
    "data/model_governance/predictions/*.json",
    "data/model_governance/input_snapshots/*.json",
    "data/prediction_universe/*.json",
    "data/prospective/ledger.jsonl",
    "data/postmatch_automation/results/*.json",
)
READER_PATHS = (
    "scripts/model_governance.py:load_frozen_prediction/load_input_snapshot",
    "scripts/prematch_versioning.py:select_latest_legal_prematch",
    "scripts/prospective_settlement.py:is_formally_eligible/normalize_result",
    "scripts/market_contracts.py:split_quarter_line",
)


class AuditError(ValueError):
    """Raised for an invalid research input or non-identifiable solve."""


def _json_default(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError(f"not JSON serializable: {type(value)!r}")


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False, default=_json_default)


def _stable_artifact_value(value: Any) -> Any:
    """Quantize serialized floats so local and CI audit artifacts are byte-stable."""
    if isinstance(value, float):
        if not math.isfinite(value):
            raise AuditError("NON_FINITE_ARTIFACT_FLOAT")
        rounded = float(f"{value:.{ARTIFACT_FLOAT_DECIMALS}f}")
        return 0.0 if rounded == 0.0 else rounded
    if isinstance(value, dict):
        return {key: _stable_artifact_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_stable_artifact_value(item) for item in value]
    return value


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _timestamp(value: Any) -> datetime | None:
    try:
        return _parse_timestamp(value)
    except (TypeError, ValueError):
        return None


def _text(value: Any) -> str:
    return str(value or "").strip()


def _repo_relative(path: Path, root: Path = ROOT) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path)


def _mean(values: Iterable[float]) -> float | None:
    values = [float(value) for value in values if _number(value) is not None]
    return statistics.fmean(values) if values else None


def _median(values: Iterable[float]) -> float | None:
    values = [float(value) for value in values if _number(value) is not None]
    return statistics.median(values) if values else None


def _quantile(values: Iterable[float], q: float) -> float | None:
    ordered = sorted(float(value) for value in values if _number(value) is not None)
    if not ordered:
        return None
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * q
    left = math.floor(position)
    right = math.ceil(position)
    if left == right:
        return ordered[left]
    weight = position - left
    return ordered[left] * (1.0 - weight) + ordered[right] * weight


def _summary_numbers(values: Iterable[float]) -> dict[str, Any]:
    values = [float(value) for value in values if _number(value) is not None]
    return {
        "n": len(values),
        "min": min(values) if values else None,
        "p10": _quantile(values, 0.10),
        "median": _quantile(values, 0.50),
        "p90": _quantile(values, 0.90),
        "max": max(values) if values else None,
        "mean": _mean(values),
    }


def _rate(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def _rounded(value: Any, digits: int = 8) -> Any:
    number = _number(value)
    return round(number, digits) if number is not None else None


def _score_pair(value: Any) -> tuple[int, int] | None:
    if isinstance(value, (tuple, list)) and len(value) == 2:
        left, right = value
    elif isinstance(value, dict):
        left, right = value.get("home_goals", value.get("home_score")), value.get("away_goals", value.get("away_score"))
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


def score_text(score: tuple[int, int]) -> str:
    return f"{score[0]}-{score[1]}"


def actual_outcome(score: tuple[int, int]) -> str:
    if score[0] > score[1]:
        return "home"
    if score[0] < score[1]:
        return "away"
    return "draw"


def water_to_decimal(water: Any) -> float:
    """Convert positive HK net water to decimal odds; fail closed otherwise."""
    value = _number(water)
    if value is None or value <= 0.0:
        raise AuditError("INVALID_HK_WATER_DOMAIN")
    result = 1.0 + value
    if not math.isfinite(result) or result <= 1.0:
        raise AuditError("INVALID_DECIMAL_ODDS_DOMAIN")
    return result


def proportional_devig(odds: Mapping[str, Any] | Iterable[Any]) -> dict[str, float] | list[float]:
    """Fixed proportional inverse-odds de-vig, shared by every surface."""
    if isinstance(odds, Mapping):
        keys = list(odds)
        values = [odds[key] for key in keys]
    else:
        keys = []
        values = list(odds)
    decimals: list[float] = []
    for value in values:
        number = _number(value)
        if number is None or number <= 1.0:
            raise AuditError("INVALID_DECIMAL_ODDS_DOMAIN")
        decimals.append(number)
    inverse = [1.0 / value for value in decimals]
    total = sum(inverse)
    if not math.isfinite(total) or total <= 0.0:
        raise AuditError("INVALID_INVERSE_ODDS_SUM")
    probabilities = [value / total for value in inverse]
    if keys:
        return {key: probability for key, probability in zip(keys, probabilities)}
    return probabilities


def _quote_key(row: Mapping[str, Any]) -> str:
    for key in ("cid", "source_company_id", "company_id", "name"):
        value = _text(row.get(key))
        if value:
            return value.casefold()
    return ""


def _valid_quarter_line(value: Any, *, allow_negative: bool = False) -> float | None:
    number = _number(value)
    if number is None or (not allow_negative and number < 0.0):
        return None
    rounded = round(number * 4.0) / 4.0
    return rounded if abs(number - rounded) <= 1e-8 else None


def poisson_pmf(lam: float, max_goals: int = MAX_GOALS) -> list[float]:
    if _number(lam) is None or lam < 0.0 or max_goals < 0:
        raise AuditError("INVALID_POISSON_INTENSITY")
    values = [math.exp(-lam)]
    for goal in range(1, max_goals + 1):
        values.append(values[-1] * lam / goal)
    return values


def independent_score_matrix(lambda_home: float, lambda_away: float, *, max_goals: int = MAX_GOALS) -> tuple[dict[tuple[int, int], float], float]:
    """Return a normalized rho=0 score matrix and the omitted tail mass."""
    home = poisson_pmf(lambda_home, max_goals)
    away = poisson_pmf(lambda_away, max_goals)
    raw = {(h, a): home[h] * away[a] for h in range(max_goals + 1) for a in range(max_goals + 1)}
    mass = sum(raw.values())
    if not math.isfinite(mass) or mass <= 0.0:
        raise AuditError("SCORE_MATRIX_MASS_INVALID")
    tail = max(0.0, 1.0 - mass)
    return {score: probability / mass for score, probability in raw.items()}, tail


def _outcome_probabilities(lambda_home: float, lambda_away: float) -> dict[str, float]:
    home = poisson_pmf(lambda_home)
    away = poisson_pmf(lambda_away)
    cumulative_away = []
    running = 0.0
    for probability in away:
        cumulative_away.append(running)
        running += probability
    draw = sum(home[goal] * away[goal] for goal in range(min(len(home), len(away))))
    home_win = sum(home[h] * cumulative_away[h] for h in range(len(home)))
    away_win = max(0.0, 1.0 - home_win - draw)
    total = home_win + draw + away_win
    if total <= 0.0 or not math.isfinite(total):
        raise AuditError("OUTCOME_PROBABILITIES_INVALID")
    return {"home": home_win / total, "draw": draw / total, "away": away_win / total}


def _settlement_weights(matrix: Mapping[tuple[int, int], float], line: float, family: str, selection: str) -> tuple[float, float]:
    components = split_quarter_line(line)
    win_weight = 0.0
    loss_weight = 0.0
    for score, probability in matrix.items():
        score_win = 0.0
        score_loss = 0.0
        for component in components:
            if family == "total":
                delta = score[0] + score[1] - component
                if selection == "under":
                    delta = -delta
            elif family == "asian_handicap":
                delta = score[0] - score[1] + component
                if selection == "away":
                    delta = -delta
            else:
                raise AuditError("UNSUPPORTED_SETTLEMENT_FAMILY")
            if delta > 1e-9:
                score_win += 1.0
            elif delta < -1e-9:
                score_loss += 1.0
        win_weight += probability * score_win / len(components)
        loss_weight += probability * score_loss / len(components)
    return win_weight, loss_weight


def fair_probability_from_matrix(matrix: Mapping[tuple[int, int], float], line: float, family: str, selection: str) -> float:
    win_weight, loss_weight = _settlement_weights(matrix, line, family, selection)
    denominator = win_weight + loss_weight
    if win_weight <= EPSILON or loss_weight <= EPSILON or denominator <= EPSILON:
        raise AuditError("SETTLEMENT_PRICE_NOT_IDENTIFIABLE")
    return win_weight / denominator


def fair_decimal_from_matrix(matrix: Mapping[tuple[int, int], float], line: float, family: str, selection: str) -> float:
    win_weight, loss_weight = _settlement_weights(matrix, line, family, selection)
    if win_weight <= EPSILON or loss_weight <= EPSILON:
        raise AuditError("SETTLEMENT_PRICE_NOT_IDENTIFIABLE")
    return 1.0 + loss_weight / win_weight


def solve_total_lambda(line: float, target_over_probability: float) -> dict[str, float]:
    """Solve total Poisson intensity against the exact Asian settlement price."""
    line = _valid_quarter_line(line)
    target = _number(target_over_probability)
    if line is None or target is None or not (EPSILON < target < 1.0 - EPSILON):
        raise AuditError("OU_SOLVE_DOMAIN_INVALID")

    def model_probability(lam: float) -> float:
        matrix, _ = independent_score_matrix(lam, 0.0, max_goals=MAX_GOALS)
        # Matrix with away intensity zero has total-goal distribution exactly.
        return fair_probability_from_matrix(matrix, line, "total", "over")

    lower, upper = OU_SOLVE_LOWER, OU_SOLVE_UPPER
    try:
        low_probability = model_probability(lower)
        high_probability = model_probability(upper)
    except AuditError as error:
        raise AuditError("OU_SOLVE_DOMAIN_INVALID") from error
    if target < low_probability - 1e-10 or target > high_probability + 1e-10:
        raise AuditError("OU_SOLVE_NOT_IDENTIFIABLE")
    for _ in range(OU_SOLVE_ITERATIONS):
        middle = (lower + upper) / 2.0
        probability = model_probability(middle)
        if probability < target:
            lower = middle
        else:
            upper = middle
    lam = (lower + upper) / 2.0
    residual = model_probability(lam) - target
    if not math.isfinite(residual) or abs(residual) > 1e-7:
        raise AuditError("OU_SOLVE_NO_CONVERGENCE")
    return {"lambda_total": lam, "target_probability": target, "model_probability": target + residual, "residual": residual}


def solve_home_share(lambda_total: float, target_probabilities: Mapping[str, float]) -> dict[str, float]:
    """Deterministic bounded golden-section fit; AH is intentionally absent."""
    target = {key: _number(target_probabilities.get(key)) for key in OUTCOMES}
    if any(value is None or value < 0.0 for value in target.values()):
        raise AuditError("HOME_SHARE_TARGET_INVALID")
    target_sum = sum(float(value) for value in target.values())
    if target_sum <= 0.0:
        raise AuditError("HOME_SHARE_TARGET_INVALID")
    target = {key: float(value) / target_sum for key, value in target.items()}

    def evaluate(share: float) -> float:
        probabilities = _outcome_probabilities(lambda_total * share, lambda_total * (1.0 - share))
        return sum((probabilities[key] - target[key]) ** 2 for key in OUTCOMES)

    left, right = SHARE_SOLVE_LOWER, SHARE_SOLVE_UPPER
    golden = (math.sqrt(5.0) - 1.0) / 2.0
    x1 = right - golden * (right - left)
    x2 = left + golden * (right - left)
    f1, f2 = evaluate(x1), evaluate(x2)
    for _ in range(SHARE_SOLVE_ITERATIONS):
        if f1 > f2:
            left, x1, f1 = x1, x2, f2
            x2 = left + golden * (right - left)
            f2 = evaluate(x2)
        else:
            right, x2, f2 = x2, x1, f1
            x1 = right - golden * (right - left)
            f1 = evaluate(x1)
    share = (left + right) / 2.0
    probabilities = _outcome_probabilities(lambda_total * share, lambda_total * (1.0 - share))
    return {
        "share": share,
        "lambda_home": lambda_total * share,
        "lambda_away": lambda_total * (1.0 - share),
        "loss": sum((probabilities[key] - target[key]) ** 2 for key in OUTCOMES),
        "iterations": SHARE_SOLVE_ITERATIONS,
    }


def _top_scores(matrix: Mapping[tuple[int, int], float], limit: int) -> list[dict[str, Any]]:
    rows = sorted(matrix.items(), key=lambda item: (-item[1], item[0][0], item[0][1]))[:limit]
    return [
        {"score": score_text(score), "home_goals": score[0], "away_goals": score[1], "probability": probability, "rank": index}
        for index, (score, probability) in enumerate(rows, start=1)
    ]


def _market_projection(lambda_home: float, lambda_away: float) -> dict[str, Any]:
    matrix, tail = independent_score_matrix(lambda_home, lambda_away)
    probabilities = _outcome_probabilities(lambda_home, lambda_away)
    total_distribution: dict[str, float] = defaultdict(float)
    for (home, away), probability in matrix.items():
        total_distribution[str(home + away)] += probability
    btts_yes = sum(probability for (home, away), probability in matrix.items() if home > 0 and away > 0)
    total_over_2_5 = sum(probability for (home, away), probability in matrix.items() if home + away > 2)
    return {
        "probabilities": probabilities,
        "lambda_home": lambda_home,
        "lambda_away": lambda_away,
        "lambda_total": lambda_home + lambda_away,
        "matrix": matrix,
        "score_matrix_tail_probability": tail,
        "top_scores": _top_scores(matrix, 5),
        "btts_yes": btts_yes,
        "btts_no": 1.0 - btts_yes,
        "total_over_2_5": total_over_2_5,
        "total_under_2_5": 1.0 - total_over_2_5,
        "total_distribution": dict(sorted(total_distribution.items(), key=lambda item: int(item[0]))),
    }


def _identity_key(record: Mapping[str, Any]) -> str:
    identity = record_identity(dict(record))
    for key in ("match_key", "match_id"):
        value = _text(identity.get(key))
        if value:
            return value
    return "|".join(_text(identity.get(key)).casefold() for key in ("home", "away", "kickoff_at"))


def _identity_display(record: Mapping[str, Any]) -> dict[str, Any]:
    identity = record_identity(dict(record))
    return {
        "match_key": _text(identity.get("match_key")) or None,
        "match_id": _text(identity.get("match_id")) or None,
        "home": identity.get("home"),
        "away": identity.get("away"),
        "kickoff_at": identity.get("kickoff_at"),
    }


def load_prediction_rows(root: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    record_root = root / "data" / "model_governance" / "predictions"
    rows: list[dict[str, Any]] = []
    load_errors: Counter[str] = Counter()
    for path in sorted(record_root.glob("*.json")):
        record = load_frozen_prediction(path.stem, record_root)
        if record is None:
            load_errors["FROZEN_RECORD_READER_REJECTED"] += 1
            continue
        rows.append(record)
    return rows, {
        "path": _repo_relative(record_root),
        "files_seen": len(list(record_root.glob("*.json"))),
        "reader_accepted_rows": len(rows),
        "reader_errors": dict(sorted(load_errors.items())),
    }


def select_unique_legal_versions(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Select one final legal Champion version per match without result access."""
    source_rows = [dict(row) for row in rows if isinstance(row, Mapping)]
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in source_rows:
        groups[_identity_key(record)].append(record)

    formal_flags = [row for row in source_rows if row.get("formal_eligible") is True]
    accepted = [row for row in source_rows if is_formally_eligible(row)]
    rejected_formal = [
        {
            "prediction_id": row.get("prediction_id"),
            "match_key": _identity_key(row),
            "reason": "EXISTING_FORMAL_ELIGIBILITY_READER_REJECTED",
        }
        for row in formal_flags
        if not is_formally_eligible(row)
    ]

    selected: list[dict[str, Any]] = []
    group_rows: list[dict[str, Any]] = []
    selection_reasons: Counter[str] = Counter()
    for key in sorted(groups):
        group = groups[key]
        candidates = [row for row in group if is_formally_eligible(row)]
        expected = record_identity(candidates[0] if candidates else group[0])
        selection = select_latest_legal_prematch(candidates, identity=expected)
        status = _text(selection.get("status")) or "UNKNOWN"
        selection_reasons[_text(selection.get("reason")) or status] += 1
        chosen = selection.get("selected_record")
        if isinstance(chosen, dict):
            selected.append(dict(chosen))
        group_rows.append({
            "match_key": key,
            "raw_record_count": len(group),
            "formal_flag_count": sum(row.get("formal_eligible") is True for row in group),
            "eligible_candidate_count": len(candidates),
            "status": status,
            "reason": _text(selection.get("reason")) or status,
            "selected_prediction_id": selection.get("selected_prediction_id"),
            "superseded_count": int(selection.get("superseded_count") or 0),
        })
    selected.sort(key=lambda row: _identity_key(row))
    return {
        "raw_reader_rows": len(source_rows),
        "raw_formal_flag_rows": len(formal_flags),
        "existing_eligibility_reader_rows": len(accepted),
        "raw_formal_flag_unique_matches": len({_identity_key(row) for row in formal_flags}),
        "eligible_unique_match_count": len(selected),
        "group_count": len(groups),
        "groups": group_rows,
        "selected_records": selected,
        "reader_rejected_formal_flags": rejected_formal,
        "selection_reason_counts": dict(sorted(selection_reasons.items())),
        "selection_rule": "existing is_formally_eligible gate, then select_latest_legal_prematch by source_cutoff_at, freeze_created_at, prediction_created_at, prediction_id; identity/chronology guarded",
        "postmatch_values_used_for_selection": False,
    }


def load_universe_index(root: Path) -> tuple[dict[str, dict[str, Any]], list[str]]:
    index: dict[str, dict[str, Any]] = {}
    errors: list[str] = []
    for path in sorted((root / "data" / "prediction_universe").glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            errors.append(f"{_repo_relative(path)}:UNREADABLE_JSON")
            continue
        for fixture in payload.get("fixtures") or []:
            if not isinstance(fixture, dict):
                continue
            key = _text(fixture.get("matchId") or fixture.get("match_id"))
            if not key:
                continue
            projected = {
                "competition": _text(fixture.get("league") or fixture.get("competition")) or "UNKNOWN",
                "home": fixture.get("homeTeam"),
                "away": fixture.get("awayTeam"),
                "business_date": fixture.get("businessDate"),
                "source_path": _repo_relative(path),
            }
            if key in index and index[key] != projected:
                errors.append(f"{key}:DUPLICATE_UNIVERSE_IDENTITY")
                continue
            index[key] = projected
    return index, errors


def _ledger_keys(root: Path) -> tuple[set[str], dict[str, Any]]:
    path = root / "data" / "prospective" / "ledger.jsonl"
    keys: set[str] = set()
    rows = 0
    errors: Counter[str] = Counter()
    if not path.is_file():
        return keys, {"path": _repo_relative(path), "rows": 0, "unique_match_keys": 0, "errors": {"MISSING_LEDGER": 1}}
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        rows += 1
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            errors["INVALID_LEDGER_JSON"] += 1
            continue
        identity = value.get("match_identity") if isinstance(value, dict) else None
        key = _text(identity.get("match_key")) if isinstance(identity, dict) else ""
        if not key:
            errors["LEDGER_ROW_MISSING_MATCH_KEY"] += 1
            continue
        keys.add(key)
    return keys, {"path": _repo_relative(path), "rows": rows, "unique_match_keys": len(keys), "errors": dict(sorted(errors.items()))}


def load_verified_results(root: Path) -> tuple[dict[str, dict[str, Any]], set[str], dict[str, Any]]:
    result_root = root / "data" / "postmatch_automation" / "results"
    all_results: dict[str, dict[str, Any]] = {}
    duplicate_keys: set[str] = set()
    errors: Counter[str] = Counter()
    files = sorted(result_root.glob("*.json"))
    for path in files:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            errors["INVALID_RESULT_JSON"] += 1
            continue
        key = _text(value.get("match_key")) if isinstance(value, dict) else ""
        if not key:
            errors["RESULT_MISSING_MATCH_KEY"] += 1
            continue
        if key in all_results:
            duplicate_keys.add(key)
            errors["DUPLICATE_RESULT_KEY"] += 1
            continue
        all_results[key] = value

    verified: dict[str, dict[str, Any]] = {}
    invalid_reasons: Counter[str] = Counter()
    for key, value in all_results.items():
        if key in duplicate_keys:
            invalid_reasons["DUPLICATE_RESULT_KEY"] += 1
            continue
        verified_at = value.get("result_verified_at") or value.get("verified_at")
        if _timestamp(verified_at) is None:
            invalid_reasons["RESULT_VERIFICATION_TIMESTAMP_MISSING_OR_UNSAFE"] += 1
            continue
        try:
            normalized = normalize_result(value)
        except (TypeError, ValueError):
            invalid_reasons["RESULT_NOT_VERIFIED_REGULATION_90M"] += 1
            continue
        if normalized.get("scope") not in {RESULT_SCOPE, "90m", "regulation_90m"}:
            invalid_reasons["RESULT_NOT_VERIFIED_REGULATION_90M"] += 1
            continue
        verified[key] = {
            "result_file": _repo_relative(result_root / f"{key}.json"),
            "home_score_90m": normalized["home_score_90m"],
            "away_score_90m": normalized["away_score_90m"],
            "score": score_text((normalized["home_score_90m"], normalized["away_score_90m"])),
            "actual_outcome": actual_outcome((normalized["home_score_90m"], normalized["away_score_90m"])),
            "verified_at": verified_at,
            "scope": normalized.get("scope"),
        }
    return verified, duplicate_keys, {
        "path": _repo_relative(result_root),
        "files_seen": len(files),
        "files_with_keys": len(all_results),
        "verified_result_files": len(verified),
        "invalid_reasons": dict(sorted(invalid_reasons.items())),
        "reader_errors": dict(sorted(errors.items())),
    }


def load_legal_market_snapshot(record: Mapping[str, Any], snapshot: Mapping[str, Any] | None) -> dict[str, Any]:
    """Return the one frozen source snapshot that is legal for this record."""
    if not isinstance(snapshot, Mapping):
        return {"snapshot": None, "source": None, "reason": "NO_FROZEN_INPUT_SNAPSHOT"}
    cutoff = _timestamp(record.get("source_cutoff_at"))
    kickoff = _timestamp(record.get("kickoff_at"))
    if cutoff is None or kickoff is None or cutoff >= kickoff:
        return {"snapshot": None, "source": None, "reason": "UNSAFE_RECORD_CHRONOLOGY"}
    input_data = snapshot.get("input") if isinstance(snapshot.get("input"), dict) else {}
    sources = input_data.get("source_snapshots") if isinstance(input_data, dict) else {}
    if not isinstance(sources, dict) or not sources:
        return {"snapshot": None, "source": None, "reason": "NO_FROZEN_SOURCE_SNAPSHOT"}

    candidates: list[tuple[datetime, str, dict[str, Any]]] = []
    later_seen = False
    timestamp_missing = False
    for source_name in sorted(sources):
        source = sources.get(source_name)
        for raw in (source.get("snapshots") or []) if isinstance(source, dict) else []:
            if not isinstance(raw, dict):
                continue
            captured = _timestamp(raw.get("fetched_at") or raw.get("captured_at"))
            if captured is None:
                timestamp_missing = True
                continue
            if captured > cutoff or captured >= kickoff:
                later_seen = True
                continue
            candidates.append((captured, str(source_name), raw))
    if not candidates:
        if later_seen:
            return {"snapshot": None, "source": None, "reason": "LATER_OR_CLOSING_QUOTE_BACKFILL_BLOCKED"}
        if timestamp_missing:
            return {"snapshot": None, "source": None, "reason": "FROZEN_MARKET_CAPTURE_TIMESTAMP_MISSING"}
        return {"snapshot": None, "source": None, "reason": "NO_LEGAL_PREMATCH_MARKET_SNAPSHOT"}
    captured, source_name, chosen = max(candidates, key=lambda item: (item[0], item[1]))
    return {
        "snapshot": chosen,
        "source": source_name,
        "captured_at": captured.isoformat(),
        "reason": None,
    }


def _market_rows(snapshot: Mapping[str, Any] | None, family: str) -> list[dict[str, Any]]:
    if not isinstance(snapshot, Mapping):
        return []
    market = snapshot.get(family)
    if not isinstance(market, dict):
        return []
    key = "bookmakers" if family == "ouzhi" else "companies"
    rows = market.get(key)
    return [dict(row) for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []


def extract_1x2_quotes(snapshot: Mapping[str, Any] | None) -> dict[str, Any]:
    rows = _market_rows(snapshot, "ouzhi")
    valid: list[dict[str, Any]] = []
    rejected: Counter[str] = Counter()
    seen: set[str] = set()
    for row in rows:
        key = _quote_key(row)
        if not key:
            rejected["MISSING_BOOKMAKER_IDENTITY"] += 1
            continue
        if key in seen:
            rejected["DUPLICATE_BOOKMAKER_ROW"] += 1
            continue
        seen.add(key)
        values = row.get("spf_current")
        if not isinstance(values, dict):
            rejected["MISSING_CURRENT_1X2_QUOTES"] += 1
            continue
        odds = {outcome: _number(values.get(outcome)) for outcome in OUTCOMES}
        if any(value is None or value <= 1.0 for value in odds.values()):
            rejected["INVALID_1X2_DECIMAL_ODDS_DOMAIN"] += 1
            continue
        try:
            fair = proportional_devig(odds)
        except AuditError as error:
            rejected[str(error)] += 1
            continue
        valid.append({"bookmaker": key, "odds": odds, "fair": fair})
    if not valid:
        reason = "NO_FROZEN_1X2_QUOTE_ROWS" if not rows else "NO_VALID_1X2_QUOTE_ROWS"
    else:
        reason = None
    if valid:
        consensus = {outcome: statistics.fmean(row["fair"][outcome] for row in valid) for outcome in OUTCOMES}
        total = sum(consensus.values())
        consensus = {outcome: consensus[outcome] / total for outcome in OUTCOMES}
    else:
        consensus = None
    return {
        "valid": valid,
        "consensus": consensus,
        "raw_row_count": len(rows),
        "valid_bookmaker_count": len(valid),
        "rejected_reasons": dict(sorted(rejected.items())),
        "reason": reason,
    }


def _extract_two_sided_rows(snapshot: Mapping[str, Any] | None, family: str, line_key: str, first_water: str, second_water: str) -> dict[str, Any]:
    rows = _market_rows(snapshot, family)
    valid: list[dict[str, Any]] = []
    rejected: Counter[str] = Counter()
    seen: set[str] = set()
    for row in rows:
        key = _quote_key(row)
        if not key:
            rejected["MISSING_BOOKMAKER_IDENTITY"] += 1
            continue
        if key in seen:
            rejected["DUPLICATE_BOOKMAKER_ROW"] += 1
            continue
        seen.add(key)
        line = _valid_quarter_line(row.get(line_key), allow_negative=family == "yazhi")
        if line is None:
            rejected["INVALID_QUARTER_LINE"] += 1
            continue
        try:
            first_decimal = water_to_decimal(row.get(first_water))
            second_decimal = water_to_decimal(row.get(second_water))
            fair = proportional_devig([first_decimal, second_decimal])
        except AuditError as error:
            rejected[str(error)] += 1
            continue
        valid.append({
            "bookmaker": key,
            "line": line,
            "first_decimal": first_decimal,
            "second_decimal": second_decimal,
            "fair_first_probability": fair[0],
            "fair_second_probability": fair[1],
        })
    reason = None if valid else (f"NO_FROZEN_{family.upper()}_QUOTE_ROWS" if not rows else f"NO_VALID_{family.upper()}_QUOTE_ROWS")
    return {
        "valid": valid,
        "raw_row_count": len(rows),
        "valid_bookmaker_count": len(valid),
        "rejected_reasons": dict(sorted(rejected.items())),
        "reason": reason,
    }


def extract_ou_quotes(snapshot: Mapping[str, Any] | None) -> dict[str, Any]:
    return _extract_two_sided_rows(snapshot, "daxiao", "current_line", "current_over_water", "current_under_water")


def extract_ah_quotes(snapshot: Mapping[str, Any] | None) -> dict[str, Any]:
    return _extract_two_sided_rows(snapshot, "yazhi", "current_handicap", "current_water_home", "current_water_away")


def build_market_baseline(one_x2: dict[str, Any], ou: dict[str, Any]) -> dict[str, Any]:
    if one_x2.get("reason"):
        return {"status": "NOT_EVALUABLE", "reason": one_x2["reason"]}
    if ou.get("reason"):
        return {"status": "NOT_EVALUABLE", "reason": ou["reason"]}
    per_book: list[dict[str, Any]] = []
    solve_reasons: Counter[str] = Counter()
    for quote in ou["valid"]:
        try:
            solved = solve_total_lambda(quote["line"], quote["fair_first_probability"])
        except AuditError as error:
            solve_reasons[str(error)] += 1
            continue
        per_book.append({**quote, **solved})
    if not per_book:
        return {
            "status": "NOT_EVALUABLE",
            "reason": "OU_SOLVE_FAILED_FOR_ALL_VALID_BOOKMAKERS",
            "solve_reasons": dict(sorted(solve_reasons.items())),
        }
    lambda_total = float(statistics.median(item["lambda_total"] for item in per_book))
    try:
        share = solve_home_share(lambda_total, one_x2["consensus"])
    except AuditError as error:
        return {"status": "NOT_EVALUABLE", "reason": str(error), "solve_reasons": dict(sorted(solve_reasons.items()))}
    projection = _market_projection(share["lambda_home"], share["lambda_away"])
    return {
        "status": "EVALUABLE",
        "reason": None,
        "lambda_total": lambda_total,
        "lambda_total_bookmaker_count": len(per_book),
        "lambda_total_bookmaker_estimates": [
            {"bookmaker": item["bookmaker"], "line": item["line"], "lambda_total": item["lambda_total"], "residual": item["residual"]}
            for item in per_book
        ],
        "lambda_total_residuals": [item["residual"] for item in per_book],
        "ou_solve_reasons": dict(sorted(solve_reasons.items())),
        "one_x2_bookmaker_count": one_x2["valid_bookmaker_count"],
        "one_x2_consensus": one_x2["consensus"],
        "share_solver": share,
        "projection": projection,
    }


def _champion_probabilities(record: Mapping[str, Any]) -> dict[str, float] | None:
    values = record.get("probabilities") or (record.get("prediction_output") or {}).get("probabilities")
    if not isinstance(values, dict):
        return None
    result = {key: _number(values.get(key)) for key in OUTCOMES}
    if any(value is None or value < 0.0 for value in result.values()):
        return None
    total = sum(float(value) for value in result.values())
    if total <= 0.0 or abs(total - 1.0) > 1e-3:
        return None
    return {key: float(value) for key, value in result.items()}


def _champion_score_list(record: Mapping[str, Any], key: str) -> list[str]:
    value = record.get(key)
    if value is None:
        value = (record.get("prediction_output") or {}).get(key)
    if isinstance(value, str):
        return [value] if _score_pair(value) else []
    return [_text(item) for item in value or [] if _score_pair(item)] if isinstance(value, list) else []


def _score_rank(scores: Iterable[str], target: str) -> int | None:
    for rank, score in enumerate(scores, start=1):
        if score == target:
            return rank
    return None


def champion_total_probability(record: Mapping[str, Any]) -> float | None:
    rows = record.get("totals") or (record.get("prediction_output") or {}).get("totals")
    if not isinstance(rows, list):
        return None
    probabilities: list[tuple[str, float]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        value = _number(row.get("probability"))
        goals = _text(row.get("goals"))
        if value is None or value < 0.0 or not goals:
            return None
        probabilities.append((goals, value))
    if not probabilities or abs(sum(value for _, value in probabilities) - 1.0) > 1e-3:
        return None
    return sum(value for goals, value in probabilities if goals in {"3", "4", "5", "6+"})


def champion_btts_probability(record: Mapping[str, Any]) -> float | None:
    value = record.get("btts") or (record.get("prediction_output") or {}).get("btts")
    if not isinstance(value, dict):
        return None
    yes, no = _number(value.get("yes")), _number(value.get("no"))
    if yes is None or no is None or yes < 0.0 or no < 0.0 or abs(yes + no - 1.0) > 1e-3:
        return None
    return yes


def has_explicit_full_distribution(record: Mapping[str, Any]) -> bool:
    for container in (record, record.get("prediction_output") if isinstance(record.get("prediction_output"), dict) else {}):
        if not isinstance(container, dict):
            continue
        rows = container.get("score_distribution") or container.get("score_matrix")
        if container.get("score_matrix_complete") is True and isinstance(rows, list) and len(rows) >= 100:
            return True
    return False


def replay_champion_parity(records: Iterable[Mapping[str, Any]], *, return_reconstructed: bool = False) -> dict[str, Any]:
    rows = [dict(row) for row in records]
    failures: Counter[str] = Counter()
    checked = 0
    passed = 0
    explicit_full = 0
    reconstructed: dict[str, dict[tuple[int, int], float]] = {}
    for record in rows:
        checked += 1
        if has_explicit_full_distribution(record):
            explicit_full += 1
        probabilities = _champion_probabilities(record)
        lambda_home = _number(record.get("lambda_home"))
        lambda_away = _number(record.get("lambda_away"))
        if probabilities is None or lambda_home is None or lambda_away is None:
            failures["MISSING_IMMUTABLE_REPLAY_INPUT"] += 1
            continue
        try:
            replay = _outcome_probabilities(lambda_home, lambda_away)
        except AuditError:
            failures["REPLAY_FAILED"] += 1
            continue
        if any(abs(replay[key] - probabilities[key]) > PARITY_TOLERANCE for key in OUTCOMES):
            failures["PERSISTED_1X2_PARITY_MISMATCH"] += 1
            continue
        replay_matrix, _ = independent_score_matrix(lambda_home, lambda_away)
        replay_top = [row["score"] for row in _top_scores(replay_matrix, 5)]
        persisted_top1 = _champion_score_list(record, "score_top1")
        persisted_top3 = _champion_score_list(record, "score_top3")
        persisted_top5 = _champion_score_list(record, "score_top5")
        if not persisted_top1 or replay_top[:1] != persisted_top1[:1]:
            failures["PERSISTED_TOP1_PARITY_MISMATCH"] += 1
            continue
        if replay_top[:3] != persisted_top3[:3] or replay_top[:5] != persisted_top5[:5]:
            failures["PERSISTED_TOPK_PARITY_MISMATCH"] += 1
            continue
        passed += 1
        reconstructed[_identity_key(record)] = replay_matrix
    replay_parity_proven = checked > 0 and passed == checked and not failures
    formal_full_support_proven = replay_parity_proven and explicit_full == checked
    result = {
        "status": "CHAMPION_FULL_DISTRIBUTION_REPLAY_PARITY_PROVEN" if formal_full_support_proven else "CHAMPION_FULL_DISTRIBUTION_NOT_FORMALLY_RECONSTRUCTIBLE",
        "checked_unique_matches": checked,
        "replay_parity_pass": passed,
        "replay_parity_fail": checked - passed,
        "explicit_full_distribution_persisted": explicit_full,
        "explicit_full_distribution_denominator": checked,
        "tolerance": PARITY_TOLERANCE,
        "failure_reasons": dict(sorted(failures.items())),
        "formal_champion_exact_nll": None,
        "formal_champion_topk_probability_calibration": None,
        "FORMAL_HISTORICAL_FULL_SUPPORT_TRUTH": "NO",
        "research_reconstruction_allowed": replay_parity_proven,
        "research_reconstruction_status": "RESEARCH_RECONSTRUCTED" if replay_parity_proven else "RESEARCH_RECONSTRUCTION_BLOCKED_BY_REPLAY_PARITY",
        "reason": "frozen lambda replay parity gates a research-only reconstructed matrix; explicit persisted full-support truth remains absent and Top1/3/5 alone are not formal full distribution",
    }
    if return_reconstructed:
        result["_reconstructed_matrices"] = reconstructed if replay_parity_proven else {}
    return result


def _verified_result_for_record(record: Mapping[str, Any], ledger_keys: set[str], results: Mapping[str, Mapping[str, Any]], duplicate_result_keys: set[str]) -> tuple[dict[str, Any] | None, str]:
    key = _identity_key(record)
    if key not in ledger_keys:
        return None, "NO_VERIFIED_RESULT_LINKAGE_IN_PROSPECTIVE_LEDGER"
    if key in duplicate_result_keys:
        return None, "DUPLICATE_RESULT_KEY"
    result = results.get(key)
    if result is None:
        return None, "RESULT_LINKED_BUT_ARTIFACT_MISSING"
    return dict(result), "VERIFIED_REGULATION_90M_RESULT"


def _horizon(record: Mapping[str, Any]) -> tuple[float | None, str | None]:
    kickoff = _timestamp(record.get("kickoff_at"))
    freeze = _timestamp(record.get("freeze_created_at"))
    if kickoff is None or freeze is None or freeze >= kickoff:
        return None, "MISSING_OR_UNSAFE_KICKOFF_OR_FREEZE_TIMESTAMP"
    return (kickoff - freeze).total_seconds() / 60.0, None


def horizon_band(minutes: float | None) -> str | None:
    if minutes is None:
        return None
    for band in HORIZON_BANDS:
        upper = band["upper_minutes"]
        if minutes >= band["lower_minutes"] and (upper is None or minutes < upper):
            return band["id"]
    return None


def _metric_row(
    record: Mapping[str, Any],
    result: Mapping[str, Any],
    baseline: Mapping[str, Any],
    *,
    reconstructed_champion_matrix: Mapping[tuple[int, int], float] | None = None,
) -> dict[str, Any] | None:
    actual = (int(result["home_score_90m"]), int(result["away_score_90m"]))
    champion_probabilities = _champion_probabilities(record)
    market_probabilities = baseline["projection"]["probabilities"]
    if champion_probabilities is None:
        return None
    outcome = actual_outcome(actual)
    champion_top1 = max(OUTCOMES, key=lambda key: champion_probabilities[key])
    market_top1 = max(OUTCOMES, key=lambda key: market_probabilities[key])
    one_hot = {key: float(key == outcome) for key in OUTCOMES}
    def brier(probabilities: Mapping[str, float]) -> float:
        return sum((probabilities[key] - one_hot[key]) ** 2 for key in OUTCOMES)
    def logloss(probabilities: Mapping[str, float]) -> float:
        return -math.log(max(float(probabilities[outcome]), EPSILON))
    def rps(probabilities: Mapping[str, float]) -> float:
        # Fixed descriptive class order; this is not used to tune the baseline.
        predicted = 0.0
        observed = 0.0
        total = 0.0
        value = 0.0
        for key in OUTCOMES[:-1]:
            predicted += probabilities[key]
            observed += one_hot[key]
            value += (predicted - observed) ** 2
        return value / 2.0

    actual_score = score_text(actual)
    champion_top1_scores = _champion_score_list(record, "score_top1")
    champion_top3_scores = _champion_score_list(record, "score_top3")
    champion_top5_scores = _champion_score_list(record, "score_top5")
    market_top = [row["score"] for row in baseline["projection"]["top_scores"]]
    champion_btts = champion_btts_probability(record)
    champion_over = champion_total_probability(record)
    actual_btts = actual[0] > 0 and actual[1] > 0
    actual_over = sum(actual) > 2
    research_reconstructed: dict[str, Any] | None = None
    if reconstructed_champion_matrix is not None:
        market_matrix = baseline["projection"]["matrix"]
        champion_ranked_scores = [row["score"] for row in _top_scores(reconstructed_champion_matrix, len(reconstructed_champion_matrix))]
        market_ranked_scores = [row["score"] for row in _top_scores(market_matrix, len(market_matrix))]
        champion_actual_rank = _score_rank(champion_ranked_scores, actual_score)
        market_actual_rank = _score_rank(market_ranked_scores, actual_score)
        if champion_actual_rank is None or market_actual_rank is None:
            raise AuditError("ACTUAL_SCORE_OUTSIDE_RESEARCH_MATRIX_SUPPORT")
        research_reconstructed = {
            "label": "RESEARCH_RECONSTRUCTED",
            "FORMAL_HISTORICAL_FULL_SUPPORT_TRUTH": "NO",
            "champion_exact_nll": -math.log(max(float(reconstructed_champion_matrix.get(actual, 0.0)), EPSILON)),
            "market_exact_nll": -math.log(max(float(market_matrix.get(actual, 0.0)), EPSILON)),
            "champion_actual_score_rank": champion_actual_rank,
            "market_actual_score_rank": market_actual_rank,
            "actual_score_rank_comparable": True,
        }
    return {
        "match_key": _identity_key(record),
        "actual_score": actual_score,
        "actual_outcome": outcome,
        "champion": {
            "top1_accuracy": int(champion_top1 == outcome),
            "log_loss": logloss(champion_probabilities),
            "brier": brier(champion_probabilities),
            "rps": rps(champion_probabilities),
            "predicted_outcome": champion_top1,
            "exact_top1": int(actual_score in champion_top1_scores[:1]),
            "exact_top3": int(actual_score in champion_top3_scores[:3]),
            "exact_top5": int(actual_score in champion_top5_scores[:5]),
            "btts_brier": (champion_btts - float(actual_btts)) ** 2 if champion_btts is not None else None,
            "over_2_5_brier": (champion_over - float(actual_over)) ** 2 if champion_over is not None else None,
        },
        "market": {
            "top1_accuracy": int(market_top1 == outcome),
            "log_loss": logloss(market_probabilities),
            "brier": brier(market_probabilities),
            "rps": rps(market_probabilities),
            "predicted_outcome": market_top1,
            "exact_top1": int(actual_score == market_top[:1][0]) if market_top else None,
            "exact_top3": int(actual_score in market_top[:3]),
            "exact_top5": int(actual_score in market_top[:5]),
            "btts_brier": (baseline["projection"]["btts_yes"] - float(actual_btts)) ** 2,
            "over_2_5_brier": (baseline["projection"]["total_over_2_5"] - float(actual_over)) ** 2,
            "actual_score_nll": -math.log(max(float(baseline["projection"]["matrix"].get(actual, 0.0)), EPSILON)),
        },
        "research_reconstructed": research_reconstructed,
    }


def _bootstrap_interval(values: list[float], *, seed: int = BOOTSTRAP_SEED) -> dict[str, Any]:
    if not values:
        return {"n": 0, "point": None, "ci95": [None, None], "iterations": 0}
    rng = random.Random(seed)
    point = statistics.fmean(values)
    samples: list[float] = []
    for _ in range(BOOTSTRAP_ITERATIONS):
        samples.append(statistics.fmean(values[rng.randrange(len(values))] for _ in values))
    return {
        "n": len(values),
        "point": point,
        "ci95": [_quantile(samples, 0.025), _quantile(samples, 0.975)],
        "iterations": BOOTSTRAP_ITERATIONS,
        "seed": seed,
    }


def _paired_bootstrap(rows: list[dict[str, Any]], key: str, *, lower_is_better: bool) -> dict[str, Any]:
    champion = [row["champion"][key] for row in rows if _number(row["champion"].get(key)) is not None and _number(row["market"].get(key)) is not None]
    market = [row["market"][key] for row in rows if _number(row["champion"].get(key)) is not None and _number(row["market"].get(key)) is not None]
    deltas = [c - m for c, m in zip(champion, market)]
    result = {
        "champion": _bootstrap_interval(champion, seed=BOOTSTRAP_SEED + len(key)),
        "market": _bootstrap_interval(market, seed=BOOTSTRAP_SEED + len(key) + 1),
        "paired_delta_champion_minus_market": _bootstrap_interval(deltas, seed=BOOTSTRAP_SEED + len(key) + 2),
        "lower_is_better": lower_is_better,
    }
    delta = result["paired_delta_champion_minus_market"]
    point = delta["point"]
    ci = delta["ci95"]
    if point is None or ci[0] is None or ci[1] is None or ci[0] <= 0.0 <= ci[1]:
        decision = "INDISTINGUISHABLE_WITH_95CI"
    elif lower_is_better:
        decision = "CHAMPION_BETTER" if point < 0.0 else "MARKET_BETTER"
    else:
        decision = "CHAMPION_BETTER" if point > 0.0 else "MARKET_BETTER"
    result["decision"] = decision
    return result


def _class_mix(rows: list[dict[str, Any]], model: str) -> dict[str, Any]:
    predicted = Counter(row[model]["predicted_outcome"] for row in rows)
    actual = Counter(row["actual_outcome"] for row in rows)
    recall = {}
    for outcome in OUTCOMES:
        denominator = actual[outcome]
        hits = sum(row[model]["predicted_outcome"] == outcome and row["actual_outcome"] == outcome for row in rows)
        recall[outcome] = {"n": denominator, "hits": hits, "recall": _rate(hits, denominator)}
    return {
        "predicted_class_mix": {key: {"n": predicted[key], "share": _rate(predicted[key], len(rows))} for key in OUTCOMES},
        "actual_class_mix": {key: {"n": actual[key], "share": _rate(actual[key], len(rows))} for key in OUTCOMES},
        "per_class_recall": recall,
    }


def _paired_series_scorecard(
    champion: list[float],
    market: list[float],
    *,
    lower_is_better: bool,
    seed: int,
    include_bootstrap: bool,
) -> dict[str, Any]:
    if len(champion) != len(market):
        raise AuditError("RESEARCH_RECONSTRUCTED_PAIRED_SERIES_LENGTH_MISMATCH")
    if include_bootstrap:
        champion_stat = _bootstrap_interval(champion, seed=seed)
        market_stat = _bootstrap_interval(market, seed=seed + 1)
        delta_stat = _bootstrap_interval([c - m for c, m in zip(champion, market)], seed=seed + 2)
    else:
        champion_stat = {"n": len(champion), "point": _mean(champion), "ci95": [None, None]}
        market_stat = {"n": len(market), "point": _mean(market), "ci95": [None, None]}
        delta_stat = {"n": len(champion), "point": _mean(c - m for c, m in zip(champion, market)), "ci95": [None, None]}
    point = delta_stat["point"]
    ci = delta_stat["ci95"]
    if not include_bootstrap:
        decision = "NOT_BOOTSTRAPPED"
    elif point is None or ci[0] is None or ci[1] is None or ci[0] <= 0.0 <= ci[1]:
        decision = "INDISTINGUISHABLE_WITH_95CI"
    elif lower_is_better:
        decision = "CHAMPION_BETTER" if point < 0.0 else "MARKET_BETTER"
    else:
        decision = "CHAMPION_BETTER" if point > 0.0 else "MARKET_BETTER"
    return {
        "champion": champion_stat,
        "market": market_stat,
        "paired_delta_champion_minus_market": delta_stat,
        "lower_is_better": lower_is_better,
        "decision": decision,
    }


def _research_reconstructed_scorecard(rows: list[dict[str, Any]], *, include_bootstrap: bool) -> dict[str, Any]:
    if not rows:
        return {
            "status": "RESEARCH_RECONSTRUCTION_BLOCKED_BY_REPLAY_PARITY",
            "label": "RESEARCH_RECONSTRUCTED",
            "FORMAL_HISTORICAL_FULL_SUPPORT_TRUTH": "NO",
            "paired_unique_match_n": 0,
            "reason": "NO_PAIRED_UNIQUE_MATCHES",
            "exact_nll": None,
            "full_actual_score_rank": None,
        }
    research_rows = [row.get("research_reconstructed") for row in rows]
    if any(item is None for item in research_rows):
        return {
            "status": "RESEARCH_RECONSTRUCTION_BLOCKED_BY_REPLAY_PARITY",
            "label": "RESEARCH_RECONSTRUCTED",
            "FORMAL_HISTORICAL_FULL_SUPPORT_TRUTH": "NO",
            "paired_unique_match_n": 0,
            "reason": "REPLAY_PARITY_NOT_PROVEN",
            "exact_nll": None,
            "full_actual_score_rank": None,
        }
    exact_champion = [float(item["champion_exact_nll"]) for item in research_rows]
    exact_market = [float(item["market_exact_nll"]) for item in research_rows]
    rank_champion = [float(item["champion_actual_score_rank"]) for item in research_rows]
    rank_market = [float(item["market_actual_score_rank"]) for item in research_rows]
    return {
        "status": "RESEARCH_RECONSTRUCTED",
        "label": "RESEARCH_RECONSTRUCTED",
        "FORMAL_HISTORICAL_FULL_SUPPORT_TRUTH": "NO",
        "paired_unique_match_n": len(rows),
        "cohort_rule": "all paired unique verified matches; no actual-score-in-Champion-Top5 filter",
        "distribution_source": "frozen lambda_home/lambda_away after 1X2 + Top1/3/5 replay parity",
        "exact_nll": _paired_series_scorecard(
            exact_champion,
            exact_market,
            lower_is_better=True,
            seed=BOOTSTRAP_SEED + 401,
            include_bootstrap=include_bootstrap,
        ),
        "full_actual_score_rank": _paired_series_scorecard(
            rank_champion,
            rank_market,
            lower_is_better=True,
            seed=BOOTSTRAP_SEED + 404,
            include_bootstrap=include_bootstrap,
        ),
    }


def paired_scorecard(rows: list[dict[str, Any]], *, include_bootstrap: bool = True) -> dict[str, Any]:
    seen: set[str] = set()
    for row in rows:
        key = _text(row.get("match_key"))
        if not key:
            raise AuditError("PAIRED_METRIC_ROW_MISSING_MATCH_KEY")
        if key in seen:
            raise AuditError("DUPLICATE_PAIRED_MATCH_KEY")
        seen.add(key)
    metrics: dict[str, Any] = {}
    for key, lower in (("top1_accuracy", False), ("log_loss", True), ("brier", True), ("rps", True)):
        metrics[key] = _paired_bootstrap(rows, key, lower_is_better=lower) if include_bootstrap else {
            "champion": {"n": len(rows), "point": _mean(row["champion"][key] for row in rows), "ci95": [None, None]},
            "market": {"n": len(rows), "point": _mean(row["market"][key] for row in rows), "ci95": [None, None]},
            "paired_delta_champion_minus_market": {"n": len(rows), "point": _mean(row["champion"][key] - row["market"][key] for row in rows), "ci95": [None, None]},
            "lower_is_better": lower,
            "decision": "NOT_BOOTSTRAPPED",
        }
    exact = {}
    for key in ("exact_top1", "exact_top3", "exact_top5"):
        exact[key] = _paired_bootstrap(rows, key, lower_is_better=False) if include_bootstrap else {
            "champion": {"n": len(rows), "point": _mean(row["champion"][key] for row in rows), "ci95": [None, None]},
            "market": {"n": len(rows), "point": _mean(row["market"][key] for row in rows), "ci95": [None, None]},
            "paired_delta_champion_minus_market": {"n": len(rows), "point": _mean(row["champion"][key] - row["market"][key] for row in rows), "ci95": [None, None]},
            "lower_is_better": False,
            "decision": "NOT_BOOTSTRAPPED",
        }
    derived = {}
    for key in ("btts_brier", "over_2_5_brier"):
        derived[key] = _paired_bootstrap(rows, key, lower_is_better=True) if include_bootstrap else {
            "champion": {"n": len(rows), "point": _mean(row["champion"].get(key) for row in rows), "ci95": [None, None]},
            "market": {"n": len(rows), "point": _mean(row["market"].get(key) for row in rows), "ci95": [None, None]},
            "paired_delta_champion_minus_market": {"n": len(rows), "point": _mean(row["champion"].get(key) - row["market"].get(key) for row in rows if row["champion"].get(key) is not None), "ci95": [None, None]},
            "lower_is_better": True,
            "decision": "NOT_BOOTSTRAPPED",
        }
    market_nll = _bootstrap_interval([row["market"]["actual_score_nll"] for row in rows], seed=BOOTSTRAP_SEED + 99)
    return {
        "paired_unique_match_n": len(rows),
        "ft_1x2": {**metrics, "champion_class_mix": _class_mix(rows, "champion"), "market_class_mix": _class_mix(rows, "market")},
        "exact_score_topk": exact,
        "research_reconstructed_scorecard": _research_reconstructed_scorecard(rows, include_bootstrap=include_bootstrap),
        "derived_scoring_state": derived,
        "market_only_exact_score_nll_descriptive": market_nll,
    }


def _slice_scorecard(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {"paired_unique_match_n": 0}
    result = paired_scorecard(rows, include_bootstrap=False)
    result.pop("market_only_exact_score_nll_descriptive", None)
    return result


def _slice_table(observations: list[dict[str, Any]], metric_rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_key: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in metric_rows:
        by_key[row["match_key"]].append(row)
    table: dict[str, Any] = {}
    for observation in observations:
        key = observation["slice_key"]
        table.setdefault(key, {"unique_frozen_matches": 0, "verified_matches": 0, "baseline_evaluable": 0, "paired_metric_rows": []})
        entry = table[key]
        entry["unique_frozen_matches"] += 1
        if observation.get("verified"):
            entry["verified_matches"] += 1
        if observation.get("baseline_status") == "EVALUABLE":
            entry["baseline_evaluable"] += 1
        entry["paired_metric_rows"].extend(by_key.get(observation["match_key"], []))
    for entry in table.values():
        entry["paired_scorecard"] = _slice_scorecard(entry.pop("paired_metric_rows"))
    return dict(sorted(table.items()))


def _build_ah_diagnostic(baseline: Mapping[str, Any], ah_quotes: Mapping[str, Any]) -> dict[str, Any]:
    if baseline.get("status") != "EVALUABLE":
        return {"status": "NOT_EVALUABLE", "reason": "BASELINE_NOT_EVALUABLE", "n": 0}
    projection = baseline["projection"]
    residuals: list[float] = []
    rows: list[dict[str, Any]] = []
    rejected: Counter[str] = Counter(ah_quotes.get("rejected_reasons") or {})
    for quote in ah_quotes.get("valid") or []:
        try:
            model_home = fair_probability_from_matrix(projection["matrix"], quote["line"], "asian_handicap", "home")
        except AuditError as error:
            rejected[str(error)] += 1
            continue
        residual = model_home - quote["fair_first_probability"]
        residuals.append(abs(residual))
        rows.append({
            "bookmaker": quote["bookmaker"],
            "line": quote["line"],
            "model_home_probability": model_home,
            "market_home_probability": quote["fair_first_probability"],
            "residual": residual,
            "absolute_error": abs(residual),
        })
    if not rows:
        return {"status": "NOT_EVALUABLE", "reason": ah_quotes.get("reason") or "AH_SETTLEMENT_PRICE_NOT_IDENTIFIABLE", "n": 0, "rejected_reasons": dict(sorted(rejected.items()))}
    return {
        "status": "EVALUABLE",
        "reason": None,
        "n": len(rows),
        "match_mean_absolute_error": statistics.fmean(residuals),
        "match_median_absolute_error": statistics.median(residuals),
        "residual_summary": _summary_numbers([row["residual"] for row in rows]),
        "quote_rows": rows,
        "rejected_reasons": dict(sorted(rejected.items())),
    }


def _load_snapshot_for_record(record: Mapping[str, Any], snapshot_root: Path) -> tuple[dict[str, Any] | None, str | None]:
    try:
        return load_input_snapshot(dict(record), snapshot_root), None
    except (OSError, ValueError, json.JSONDecodeError) as error:
        return None, f"INPUT_SNAPSHOT_READER_ERROR:{type(error).__name__}"


def _git_commit_time(root: Path, sha: str | None) -> str | None:
    if not sha:
        return None
    try:
        result = subprocess.run(["git", "show", "-s", "--format=%cI", sha], cwd=root, text=True, capture_output=True, check=True)
    except (OSError, subprocess.CalledProcessError):
        return None
    return result.stdout.strip() or None


def _source_main_sha(root: Path, explicit: str | None) -> str | None:
    if explicit:
        return explicit
    try:
        result = subprocess.run(["git", "rev-parse", "origin/main"], cwd=root, text=True, capture_output=True, check=True)
    except (OSError, subprocess.CalledProcessError):
        return None
    return result.stdout.strip() or None


def _decision_from_n(n: int, baseline_n: int, integrity_failures: list[str], solver_failures: int) -> str:
    if integrity_failures:
        return "FAIL_CLOSED"
    if baseline_n < MIN_PAIRED_SAMPLE_FOR_MEANINGFUL_DECISION:
        return "MARKET_BASELINE_COVERAGE_INSUFFICIENT"
    if solver_failures > 0 and baseline_n == 0:
        return "MARKET_BASELINE_CONSTRUCTION_NOT_VALIDATED"
    if n == 0:
        return "MARKET_BASELINE_COVERAGE_INSUFFICIENT"
    return "MARKET_BASELINE_EVALUABLE"


def build_summary(root: Path = ROOT, *, source_main_sha: str | None = None) -> dict[str, Any]:
    source_main_sha = _source_main_sha(root, source_main_sha)
    records, inventory = load_prediction_rows(root)
    selection = select_unique_legal_versions(records)
    universe, universe_errors = load_universe_index(root)
    ledger_keys, ledger_info = _ledger_keys(root)
    result_index, duplicate_result_keys, result_info = load_verified_results(root)
    snapshot_root = root / "data" / "model_governance" / "input_snapshots"
    snapshot_cache: dict[str, tuple[dict[str, Any] | None, str | None]] = {}
    replay = replay_champion_parity(selection["selected_records"], return_reconstructed=True)
    reconstructed_matrices = replay.pop("_reconstructed_matrices", {})

    observations: list[dict[str, Any]] = []
    quote_reason_counts = {"1x2": Counter(), "ou": Counter(), "ah": Counter(), "baseline": Counter(), "result": Counter()}
    ou_estimates: list[float] = []
    ou_residuals: list[float] = []
    solve_failures = 0
    all_selected_raw_1x2 = 0
    all_selected_raw_ou = 0
    all_selected_ah = 0
    for record in selection["selected_records"]:
        key = _identity_key(record)
        if key not in snapshot_cache:
            snapshot_cache[key] = _load_snapshot_for_record(record, snapshot_root)
        snapshot, snapshot_error = snapshot_cache[key]
        legal_snapshot = load_legal_market_snapshot(record, snapshot) if snapshot_error is None else {"snapshot": None, "source": None, "reason": snapshot_error}
        raw_snapshot = legal_snapshot.get("snapshot")
        one_x2 = extract_1x2_quotes(raw_snapshot)
        ou_quotes = extract_ou_quotes(raw_snapshot)
        ah_quotes = extract_ah_quotes(raw_snapshot)
        if one_x2.get("reason"):
            quote_reason_counts["1x2"][one_x2["reason"]] += 1
        else:
            all_selected_raw_1x2 += 1
        if ou_quotes.get("reason"):
            quote_reason_counts["ou"][ou_quotes["reason"]] += 1
        else:
            all_selected_raw_ou += 1
        if ah_quotes.get("reason"):
            quote_reason_counts["ah"][ah_quotes["reason"]] += 1
        else:
            all_selected_ah += 1
        result, result_reason = _verified_result_for_record(record, ledger_keys, result_index, duplicate_result_keys)
        if result_reason != "VERIFIED_REGULATION_90M_RESULT":
            quote_reason_counts["result"][result_reason] += 1
        baseline = build_market_baseline(one_x2, ou_quotes)
        if baseline.get("status") == "NOT_EVALUABLE":
            quote_reason_counts["baseline"][baseline.get("reason") or "BASELINE_NOT_EVALUABLE"] += 1
            solve_failures += 1 if "SOLVE" in str(baseline.get("reason")) or "SHARE" in str(baseline.get("reason")) else 0
        else:
            ou_estimates.extend(item["lambda_total"] for item in baseline["lambda_total_bookmaker_estimates"])
            ou_residuals.extend(baseline["lambda_total_residuals"])
        horizon_minutes, horizon_reason = _horizon(record)
        if horizon_reason:
            quote_reason_counts["result"][horizon_reason] += 1
        competition = universe.get(_text(record.get("match_id")), {}).get("competition", "UNKNOWN")
        data_grade = _text(record.get("data_grade") or record.get("generic_data_grade")) or "UNKNOWN"
        verified = result is not None
        metric = (
            _metric_row(
                record,
                result,
                baseline,
                reconstructed_champion_matrix=reconstructed_matrices.get(key),
            )
            if verified and baseline.get("status") == "EVALUABLE"
            else None
        )
        ah = _build_ah_diagnostic(baseline, ah_quotes)
        observations.append({
            "match_key": key,
            "record": record,
            "result": result,
            "verified": verified,
            "result_reason": result_reason,
            "snapshot": snapshot,
            "snapshot_reason": legal_snapshot.get("reason"),
            "source": legal_snapshot.get("source"),
            "captured_at": legal_snapshot.get("captured_at"),
            "one_x2": one_x2,
            "ou": ou_quotes,
            "ah_quotes": ah_quotes,
            "baseline": baseline,
            "ah": ah,
            "horizon_minutes": horizon_minutes,
            "horizon_reason": horizon_reason,
            "horizon_band": horizon_band(horizon_minutes),
            "competition": competition or "UNKNOWN",
            "data_grade": data_grade,
            "metric": metric,
            "slice_key": "UNKNOWN",
        })

    metric_rows = [observation["metric"] for observation in observations if observation.get("metric") is not None]
    verified_observations = [observation for observation in observations if observation["verified"]]
    baseline_observations = [observation for observation in observations if observation["baseline"].get("status") == "EVALUABLE"]
    paired_observations = [observation for observation in observations if observation.get("metric") is not None]

    funnel = {
        "unique_frozen": len(observations),
        "verified_unique_matches": len(verified_observations),
        "raw_frozen_1x2_valid_all_selected": all_selected_raw_1x2,
        "raw_frozen_ou_valid_all_selected": all_selected_raw_ou,
        "ah_heldout_valid_all_selected": all_selected_ah,
        "verified_raw_1x2_valid": sum(not observation["one_x2"].get("reason") for observation in verified_observations),
        "verified_raw_ou_valid": sum(not observation["ou"].get("reason") for observation in verified_observations),
        "baseline_evaluable": len(baseline_observations),
        "paired_champion_market_1x2_n": len(paired_observations),
        "ah_heldout_evaluable": sum(observation["ah"].get("status") == "EVALUABLE" for observation in baseline_observations),
        "observation_unit": OBSERVATION_UNIT,
        "version_rows_not_counted_as_observations": True,
    }

    paired_score = paired_scorecard(metric_rows)
    # Slices are fixed from observed fields, but no result is used to choose a row.
    slice_groups: dict[str, dict[str, list[dict[str, Any]]]] = {"competition": defaultdict(list), "horizon": defaultdict(list), "data_grade": defaultdict(list)}
    for observation in observations:
        for kind, value in (
            ("competition", observation["competition"]),
            ("horizon", observation["horizon_band"] or "HORIZON_UNSAFE"),
            ("data_grade", observation["data_grade"]),
        ):
            observation_copy = dict(observation)
            observation_copy["slice_key"] = value
            slice_groups[kind][value].append(observation_copy)
    slices = {}
    for kind, groups in slice_groups.items():
        slices[kind] = {}
        for value, group in sorted(groups.items()):
            group_metrics = [row["metric"] for row in group if row.get("metric") is not None]
            slices[kind][value] = {
                "unique_frozen_matches": len(group),
                "verified_unique_matches": sum(row["verified"] for row in group),
                "baseline_evaluable": sum(row["baseline"].get("status") == "EVALUABLE" for row in group),
                "paired_scorecard": _slice_scorecard(group_metrics),
            }

    horizon_values = [observation["horizon_minutes"] for observation in observations if observation["horizon_minutes"] is not None]
    raw_horizon = {
        "eligible_unique_matches": len(observations),
        "safe_unique_matches": len(horizon_values),
        "unsafe_unique_matches": len(observations) - len(horizon_values),
        "missing_reasons": dict(sorted(Counter(observation["horizon_reason"] for observation in observations if observation["horizon_reason"]).items())),
        "statistics_minutes": _summary_numbers(horizon_values),
        "minutes_sorted": [round(value, 6) for value in sorted(horizon_values)],
    }
    horizon_map = {
        "timestamp_rule": "kickoff_at - freeze_created_at; both timezone-aware; freeze strictly before kickoff",
        "raw_lead_time_distribution": raw_horizon,
        "bands": [
            {
                **band,
                "unique_frozen_matches": sum(observation["horizon_band"] == band["id"] for observation in observations),
                "verified_unique_matches": sum(observation["horizon_band"] == band["id"] and observation["verified"] for observation in observations),
                "baseline_evaluable": sum(observation["horizon_band"] == band["id"] and observation["baseline"].get("status") == "EVALUABLE" for observation in observations),
            }
            for band in HORIZON_BANDS
        ],
        "band_policy": list(HORIZON_BANDS),
    }

    quote_diagnostics = {
        "water_domain": {
            "raw_domain": "positive HK net odds water",
            "conversion": "decimal = 1 + water",
            "invalid_water_fails_closed": True,
            "direct_water_as_probability": False,
        },
        "devig": {
            "method": "proportional inverse odds",
            "bookmaker_aggregation_1x2": "equal-weight valid bookmaker fair vectors, normalize consensus once",
            "ou_aggregation": "median per-book lambda_total",
            "bookmaker_weights_fitted_on_outcomes": False,
        },
        "selected_unique_matches": len(observations),
        "one_x2_bookmaker_counts": _summary_numbers(observation["one_x2"].get("valid_bookmaker_count", 0) for observation in observations),
        "ou_bookmaker_counts": _summary_numbers(observation["ou"].get("valid_bookmaker_count", 0) for observation in observations),
        "ah_bookmaker_counts": _summary_numbers(observation["ah_quotes"].get("valid_bookmaker_count", 0) for observation in observations),
        "missing_reasons": {key: dict(sorted(value.items())) for key, value in quote_reason_counts.items()},
    }
    ou_diagnostics = {
        "settlement": "exact Asian full_win/half_win/push/half_loss semantics via market_contracts.split_quarter_line",
        "line_used_as_expected_goals": False,
        "solve_bounds": [OU_SOLVE_LOWER, OU_SOLVE_UPPER],
        "solve_iterations": OU_SOLVE_ITERATIONS,
        "per_book_estimates": _summary_numbers(ou_estimates),
        "per_book_residuals": _summary_numbers(ou_residuals),
        "evaluable_match_count": len(baseline_observations),
        "failed_match_count": sum(observation["baseline"].get("status") != "EVALUABLE" for observation in observations),
        "failure_reasons": dict(sorted(quote_reason_counts["baseline"].items())),
    }
    ah_summary_rows = [observation["ah"] for observation in baseline_observations if observation["ah"].get("status") == "EVALUABLE"]
    ah_residuals = [row["match_mean_absolute_error"] for row in ah_summary_rows]
    ah_heldout = {
        "used_in_primary_fit": False,
        "evaluable_unique_match_n": len(ah_summary_rows),
        "match_mean_absolute_error": _summary_numbers(ah_residuals),
        "quote_row_count": sum(row["n"] for row in ah_summary_rows),
        "settlement_correct_quarter_lines": True,
        "diagnostic_failure_reasons": dict(sorted(Counter(
            reason
            for observation in observations
            for reason in (observation["ah"].get("rejected_reasons") or {})
        ).items())),
    }

    integrity_failures: list[str] = []
    if universe_errors:
        integrity_failures.extend(universe_errors)
    if duplicate_result_keys:
        # Duplicate result identity is an integrity failure only for a selected match.
        selected_keys = {_identity_key(observation["record"]) for observation in observations}
        integrity_failures.extend(f"{key}:DUPLICATE_RESULT_KEY" for key in sorted(duplicate_result_keys & selected_keys))
    integrity = {
        "read_only": True,
        "network_calls": 0,
        "external_provider_calls": 0,
        "frozen_history_mutated": False,
        "champion_challenger_calibration_serving_ui_mutated": False,
        "postmatch_values_used_to_select_prematch_version": False,
        "ah_used_in_primary_fit": False,
        "later_or_closing_quotes_used": False,
        "identity_or_chronology_failures": sorted(integrity_failures),
        "integrity_status": "PASS" if not integrity_failures else "FAIL",
    }

    match_rows: list[dict[str, Any]] = []
    for observation in observations:
        record = observation["record"]
        baseline = observation["baseline"]
        match_rows.append({
            "match_key": observation["match_key"],
            "prediction_id": record.get("prediction_id"),
            "prediction_record_ref": f"data/model_governance/predictions/{record.get('prediction_id')}.json",
            "competition": observation["competition"],
            "data_grade": observation["data_grade"],
            "kickoff_at": record.get("kickoff_at"),
            "freeze_created_at": record.get("freeze_created_at"),
            "source_cutoff_at": record.get("source_cutoff_at"),
            "horizon_minutes": _rounded(observation["horizon_minutes"], 6),
            "horizon_band": observation["horizon_band"],
            "source_provider": observation["source"],
            "verified": observation["verified"],
            "result_reason": observation["result_reason"],
            "actual_score": observation["result"].get("score") if observation["result"] else None,
            "raw_1x2_status": "VALID" if not observation["one_x2"].get("reason") else observation["one_x2"].get("reason"),
            "raw_ou_status": "VALID" if not observation["ou"].get("reason") else observation["ou"].get("reason"),
            "baseline_status": baseline.get("status"),
            "baseline_reason": baseline.get("reason"),
            "one_x2_bookmaker_count": observation["one_x2"].get("valid_bookmaker_count", 0),
            "ou_bookmaker_count": observation["ou"].get("valid_bookmaker_count", 0),
            "lambda_total": _rounded(baseline.get("lambda_total"), 8),
            "lambda_total_residual_summary": _summary_numbers(baseline.get("lambda_total_residuals") or []),
            "lambda_home_market": _rounded((baseline.get("projection") or {}).get("lambda_home"), 8),
            "lambda_away_market": _rounded((baseline.get("projection") or {}).get("lambda_away"), 8),
            "ah_status": observation["ah"].get("status"),
            "ah_reason": observation["ah"].get("reason"),
            "ah_mean_absolute_error": _rounded(observation["ah"].get("match_mean_absolute_error"), 8),
            "research_reconstructed": (observation["metric"] or {}).get("research_reconstructed"),
        })

    top_decision = _decision_from_n(len(observations), len(paired_observations), integrity_failures, solve_failures)
    if top_decision == "MARKET_BASELINE_EVALUABLE" and len(baseline_observations) < MIN_PAIRED_SAMPLE_FOR_MEANINGFUL_DECISION:
        top_decision = "MARKET_BASELINE_COVERAGE_INSUFFICIENT"
    generated_at = _git_commit_time(root, source_main_sha) or source_main_sha
    return {
        "audit_schema_version": AUDIT_SCHEMA_VERSION,
        "issue": ISSUE_NUMBER,
        "milestone": "MARKET-IMPLIED-SCORE-BASELINE-1",
        "generated_at": generated_at,
        "source_main_sha": source_main_sha,
        "source_paths": list(SOURCE_PATHS),
        "reader_paths": list(READER_PATHS),
        "scope": {
            "read_only": True,
            "research_only": True,
            "observation_unit": OBSERVATION_UNIT,
            "external_api_used": False,
            "external_provider_used": False,
            "later_closing_odds_fetched": False,
            "reep_used": False,
            "odds_api_used": False,
            "correct_score_provider_used": False,
            "champion_challenger_calibration_serving_ui_changed": False,
            "frozen_history_rewritten": False,
            "FORMAL_HISTORICAL_FULL_SUPPORT_TRUTH": "NO",
        },
        "policy": {
            "version_selection": selection["selection_rule"],
            "prediction_horizon": "kickoff_at minus selected legal freeze_created_at",
            "market_cutoff": "source snapshot fetched_at must be <= selected source_cutoff_at and strictly before kickoff",
            "one_x2": "current spf_current decimal odds, proportional inverse-odds de-vig per bookmaker, equal-weight fair vectors",
            "hk_water": "positive HK net water only; decimal = 1 + water; invalid/non-finite/non-positive fail closed",
            "ou": "current line + both current waters; exact quarter-line Asian settlement; solve lambda_total per bookmaker; aggregate by fixed median",
            "home_away_split": "rho=0; bounded deterministic golden-section loss against frozen 1X2 consensus; no AH input",
            "ah": "held-out settlement-correct consistency surface only",
            "score_matrix_max_goals": MAX_GOALS,
            "artifact_float_decimals": ARTIFACT_FLOAT_DECIMALS,
            "bootstrap": {"iterations": BOOTSTRAP_ITERATIONS, "seed": BOOTSTRAP_SEED, "unit": OBSERVATION_UNIT},
        },
        "inventory": {
            "frozen_prediction_store": inventory,
            "selection": {key: value for key, value in selection.items() if key not in {"selected_records", "groups"}},
            "prediction_universe": {"unique_match_ids": len(universe), "reader_errors": universe_errors},
            "prospective_ledger": ledger_info,
            "result_artifacts": result_info,
        },
        "funnel": funnel,
        "selection": {
            "selected_unique_match_count": len(observations),
            "formal_eligibility_reader_rejected_formal_flags": selection["reader_rejected_formal_flags"],
            "selection_reason_counts": selection["selection_reason_counts"],
            "groups_without_selected_legal_version": [row for row in selection["groups"] if not row.get("selected_prediction_id")],
        },
        "quote_diagnostics": quote_diagnostics,
        "ou_solve_diagnostics": ou_diagnostics,
        "ah_heldout_consistency": ah_heldout,
        "paired_scorecard": paired_score,
        "slices": slices,
        "horizon_map": horizon_map,
        "replay_parity": replay,
        "exclusion_reasons": quote_diagnostics["missing_reasons"],
        "integrity": integrity,
        "top_level_decision": top_decision,
        "decision_rule": "MARKET_BASELINE_EVALUABLE requires no integrity failure, at least 50 paired verified unique matches, and a deterministic settlement-correct baseline; this does not authorize a model change",
        "match_rows": match_rows,
        "stop": "READY_FOR_INDEPENDENT_ACCEPTANCE; DO NOT MERGE",
    }


def _metric_point(scorecard: Mapping[str, Any], path: tuple[str, ...]) -> Any:
    value: Any = scorecard
    for key in path:
        if not isinstance(value, Mapping):
            return None
        value = value.get(key)
    return value


def render_report(summary: Mapping[str, Any]) -> str:
    funnel = summary["funnel"]
    paired = summary["paired_scorecard"]
    lines = [
        "# MARKET-IMPLIED-SCORE-BASELINE-1",
        "",
        "Research-only, read-only audit. **DO NOT MERGE.**",
        "",
        f"- Source `origin/main`: `{summary.get('source_main_sha')}`",
        f"- Observation unit: `{OBSERVATION_UNIT}`",
        f"- Top-level decision: **`{summary.get('top_level_decision')}`**",
        f"- Stop state: `{summary.get('stop')}`",
        "",
        "## Scope and immutable cohort",
        "",
        "The audit reads only repository-resident frozen Champion records, their content-addressed input snapshots, the existing prospective ledger, and already persisted regulation-90m result artifacts. It does not fetch odds, use later/closing quotes, call a provider, or mutate Champion, Challenger, calibration, serving, UI, or frozen history.",
        "",
        f"Version selection is deterministic: `{summary['policy']['version_selection']}`. The result is selected before any result artifact is consulted.",
        "",
        "## Unique-match funnel",
        "",
        "| Stage | Unique matches |",
        "|---|---:|",
        f"| Unique frozen selected | {funnel['unique_frozen']} |",
        f"| Verified regulation-90m result linkage | {funnel['verified_unique_matches']} |",
        f"| Raw frozen 1X2 valid (all selected) | {funnel['raw_frozen_1x2_valid_all_selected']} |",
        f"| Raw frozen O/U valid (all selected) | {funnel['raw_frozen_ou_valid_all_selected']} |",
        f"| Verified + raw 1X2 valid | {funnel['verified_raw_1x2_valid']} |",
        f"| Verified + raw O/U valid | {funnel['verified_raw_ou_valid']} |",
        f"| Market baseline evaluable | {funnel['baseline_evaluable']} |",
        f"| Paired Champion vs market 1X2 | {funnel['paired_champion_market_1x2_n']} |",
        f"| AH held-out evaluable | {funnel['ah_heldout_evaluable']} |",
        "",
        "The all-selected quote counts are reported separately because verified-result linkage is a post-match denominator; they are not silently substituted for paired evaluation n.",
        "",
        "## Construction contract",
        "",
        f"- 1X2: `{summary['policy']['one_x2']}`",
        f"- O/U: `{summary['policy']['ou']}`",
        f"- Home/away split: `{summary['policy']['home_away_split']}`",
        f"- AH: `{summary['policy']['ah']}`",
        f"- O/U line directly used as expected goals: `{summary['ou_solve_diagnostics']['line_used_as_expected_goals']}`",
        "",
        "## O/U and AH diagnostics",
        "",
        f"- O/U evaluable matches: `{summary['ou_solve_diagnostics']['evaluable_match_count']}`; failed: `{summary['ou_solve_diagnostics']['failed_match_count']}`.",
        f"- Per-book O/U lambda residual summary: `{json.dumps(summary['ou_solve_diagnostics']['per_book_residuals'], ensure_ascii=False, sort_keys=True)}`",
        f"- AH was used in the primary fit: `{summary['ah_heldout_consistency']['used_in_primary_fit']}`.",
        f"- AH held-out mean absolute error summary: `{json.dumps(summary['ah_heldout_consistency']['match_mean_absolute_error'], ensure_ascii=False, sort_keys=True)}`",
        "",
        "## Champion vs market paired scorecard",
        "",
        "Values are paired point estimates with deterministic unique-match bootstrap 95% intervals. A delta is Champion minus market; lower is better for loss/error metrics and higher is better for hit metrics.",
        "",
        "### FT 1X2",
        "",
        "| Metric | Champion | Market | Paired delta | Decision |",
        "|---|---:|---:|---:|---|",
    ]
    for key, label in (("top1_accuracy", "Top1 accuracy"), ("log_loss", "Log loss"), ("brier", "Brier"), ("rps", "RPS")):
        item = paired["ft_1x2"][key]
        lines.append(f"| {label} | {item['champion']['point']:.6f} | {item['market']['point']:.6f} | {item['paired_delta_champion_minus_market']['point']:.6f} [{item['paired_delta_champion_minus_market']['ci95'][0]:.6f}, {item['paired_delta_champion_minus_market']['ci95'][1]:.6f}] | {item['decision']} |")
    lines += [
        "",
        f"Champion predicted class mix / recall: `{json.dumps(paired['ft_1x2']['champion_class_mix'], ensure_ascii=False, sort_keys=True)}`",
        f"Market predicted class mix / recall: `{json.dumps(paired['ft_1x2']['market_class_mix'], ensure_ascii=False, sort_keys=True)}`",
        "",
        "### Exact Score Top-k",
        "",
        "| Metric | Champion | Market | Paired delta | Decision |",
        "|---|---:|---:|---:|---|",
    ]
    for key, label in (("exact_top1", "Top1 hit"), ("exact_top3", "Top3 hit"), ("exact_top5", "Top5 hit")):
        item = paired["exact_score_topk"][key]
        lines.append(f"| {label} | {item['champion']['point']:.6f} | {item['market']['point']:.6f} | {item['paired_delta_champion_minus_market']['point']:.6f} [{item['paired_delta_champion_minus_market']['ci95'][0]:.6f}, {item['paired_delta_champion_minus_market']['ci95'][1]:.6f}] | {item['decision']} |")
    reconstructed = paired["research_reconstructed_scorecard"]
    lines += [
        "",
        "### RESEARCH_RECONSTRUCTED full score surface",
        "",
        "The reconstructed Champion matrix is created only after frozen lambda replay reproduces persisted Champion 1X2 + Top1/3/5 parity. It is a research surface, never historical frozen full-support truth; the realized score never decides cohort membership.",
        f"- Status: `{reconstructed['status']}`; paired unique matches: `{reconstructed['paired_unique_match_n']}`.",
        f"- `FORMAL_HISTORICAL_FULL_SUPPORT_TRUTH={reconstructed['FORMAL_HISTORICAL_FULL_SUPPORT_TRUTH']}`.",
        f"- Cohort rule: `{reconstructed.get('cohort_rule', reconstructed.get('reason'))}`.",
        "",
        f"Market-only descriptive Exact Score NLL: `{json.dumps(paired['market_only_exact_score_nll_descriptive'], ensure_ascii=False, sort_keys=True)}`. This is not a paired Champion-vs-market NLL verdict.",
        "",
        "### Derived scoring state",
        "",
        "BTTS and Over 2.5 Brier are included only because the frozen Champion stores those probability vectors. Missing Champion probabilities are not manufactured.",
        "",
    ]
    if reconstructed["status"] == "RESEARCH_RECONSTRUCTED":
        insert_at = lines.index("### Derived scoring state")
        lines[insert_at:insert_at] = [
            "| Metric | Reconstructed Champion | Market | Paired delta | Decision |",
            "|---|---:|---:|---:|---|",
            f"| Exact NLL | {reconstructed['exact_nll']['champion']['point']:.6f} | {reconstructed['exact_nll']['market']['point']:.6f} | {reconstructed['exact_nll']['paired_delta_champion_minus_market']['point']:.6f} [{reconstructed['exact_nll']['paired_delta_champion_minus_market']['ci95'][0]:.6f}, {reconstructed['exact_nll']['paired_delta_champion_minus_market']['ci95'][1]:.6f}] | {reconstructed['exact_nll']['decision']} |",
            f"| Full actual-score rank | {reconstructed['full_actual_score_rank']['champion']['point']:.6f} | {reconstructed['full_actual_score_rank']['market']['point']:.6f} | {reconstructed['full_actual_score_rank']['paired_delta_champion_minus_market']['point']:.6f} [{reconstructed['full_actual_score_rank']['paired_delta_champion_minus_market']['ci95'][0]:.6f}, {reconstructed['full_actual_score_rank']['paired_delta_champion_minus_market']['ci95'][1]:.6f}] | {reconstructed['full_actual_score_rank']['decision']} |",
            "",
        ]
    else:
        insert_at = lines.index("### Derived scoring state")
        lines[insert_at:insert_at] = ["Reconstructed Exact NLL and full actual-score rank are omitted because replay parity did not pass.", ""]
    for key, label in (("btts_brier", "BTTS Brier"), ("over_2_5_brier", "Over 2.5 Brier")):
        item = paired["derived_scoring_state"][key]
        lines.append(f"- {label}: Champion `{item['champion']['point']}`, market `{item['market']['point']}`, paired delta `{item['paired_delta_champion_minus_market']['point']}` ({item['decision']}).")
    lines += [
        "",
        "## Full-distribution replay parity",
        "",
        f"- Status: **`{summary['replay_parity']['status']}`**",
        f"- Replay parity pass: `{summary['replay_parity']['replay_parity_pass']}/{summary['replay_parity']['checked_unique_matches']}`",
        f"- Research reconstruction gate: **`{summary['replay_parity']['research_reconstruction_status']}`**",
        f"- `FORMAL_HISTORICAL_FULL_SUPPORT_TRUTH={summary['replay_parity']['FORMAL_HISTORICAL_FULL_SUPPORT_TRUTH']}`",
        f"- Explicit full-distribution persistence: `{summary['replay_parity']['explicit_full_distribution_persisted']}/{summary['replay_parity']['explicit_full_distribution_denominator']}`",
        "- Formal historical Champion Exact NLL and Top-k probability calibration remain omitted. The reconstructed research distribution must not be relabeled as frozen formal full-support truth.",
        "",
        "## Horizon and slices",
        "",
        f"Raw horizon statistics: `{json.dumps(summary['horizon_map']['raw_lead_time_distribution']['statistics_minutes'], ensure_ascii=False, sort_keys=True)}`",
        "",
        "| Horizon band | Unique | Verified | Baseline evaluable |",
        "|---|---:|---:|---:|",
    ]
    for band in summary["horizon_map"]["bands"]:
        lines.append(f"| {band['label']} | {band['unique_frozen_matches']} | {band['verified_unique_matches']} | {band['baseline_evaluable']} |")
    lines += [
        "",
        "Competition, horizon and data-grade scorecards are persisted in `summary.json` under `slices`; tiny slices are descriptive only and are not treated as superiority evidence.",
        "",
        "## Missing/exclusion reasons and integrity",
        "",
        f"- Exact stage reasons: `{json.dumps(summary['exclusion_reasons'], ensure_ascii=False, sort_keys=True)}`",
        f"- Integrity status: **`{summary['integrity']['integrity_status']}`**",
        f"- Integrity details: `{json.dumps(summary['integrity'], ensure_ascii=False, sort_keys=True)}`",
        "",
        "## Top-level decision",
        "",
        f"**`{summary['top_level_decision']}`** — the market baseline is a deterministic research control on the paired cohort; this decision does not authorize Champion/Challenger/model or product changes.",
        "",
        "STOP: `READY_FOR_INDEPENDENT_ACCEPTANCE; DO NOT MERGE`.",
        "",
    ]
    return "\n".join(lines)


def _safe_output_dir(root: Path, output_dir: Path) -> Path:
    resolved_root = root.resolve()
    resolved = output_dir.resolve()
    protected = (
        resolved_root / "data" / "model_governance",
        resolved_root / "data" / "prospective",
        resolved_root / "data" / "postmatch_automation",
        resolved_root / "scripts",
    )
    if any(resolved == item or item in resolved.parents for item in protected):
        raise ValueError("audit output must stay outside protected truth/code directories")
    return resolved


def write_outputs(summary: dict[str, Any], output_dir: Path, *, root: Path = ROOT) -> tuple[Path, Path]:
    output_dir = _safe_output_dir(root, output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    stable_summary = _stable_artifact_value(summary)
    summary_path = output_dir / "summary.json"
    report_path = output_dir / "report.md"
    summary_path.write_text(json.dumps(stable_summary, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8", newline="\n")
    report_path.write_text(render_report(stable_summary), encoding="utf-8", newline="\n")
    return summary_path, report_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the read-only market-implied score baseline audit.")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--source-main-sha", default=None)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args(argv)
    summary = build_summary(args.root.resolve(), source_main_sha=args.source_main_sha)
    summary_path, report_path = write_outputs(summary, args.output_dir, root=args.root.resolve())
    print(json.dumps({
        "summary": _repo_relative(summary_path, args.root.resolve()),
        "report": _repo_relative(report_path, args.root.resolve()),
        "top_level_decision": summary["top_level_decision"],
        "unique_frozen": summary["funnel"]["unique_frozen"],
        "verified_unique_matches": summary["funnel"]["verified_unique_matches"],
        "baseline_evaluable": summary["funnel"]["baseline_evaluable"],
        "ah_heldout_evaluable": summary["funnel"]["ah_heldout_evaluable"],
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
