#!/usr/bin/env python3
"""Run the fixed-cohort, parameter-free Issue #225 Poisson adequacy check."""

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
from typing import Any, Callable, Iterable, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from market_contracts import split_quarter_line  # noqa: E402
from market_side_shadow import _actual_for_pair, load_persisted_pairs  # noqa: E402
from market_side_shadow_refresh import (  # noqa: E402
    build_identity_safe_result_map,
    discover_verified_results,
)


MILESTONE = "EXACT-POISSON-ADEQUACY-DIAGNOSTIC-1"
SCHEMA_VERSION = "exact_poisson_adequacy_diagnostic_1.v1"
FIXED_COHORT_COUNT = 107
MIN_MEANINGFUL_SLICE = 10
MARKET_MAX_GOALS = 20
MARKET_EPSILON = 1e-12
MARKET_OU_SOLVE_LOWER = 0.001
MARKET_OU_SOLVE_UPPER = 20.0
MARKET_OU_SOLVE_ITERATIONS = 90
MARKET_SHARE_SOLVE_LOWER = 0.01
MARKET_SHARE_SOLVE_UPPER = 0.99
MARKET_SHARE_SOLVE_ITERATIONS = 70
BOOTSTRAP_RESAMPLES = 10_000
PIT_BINS = 10
PIT_RANDOMIZATION_REPLICATES = 100
PIT_SEED = 2_251_501
MATERIAL_GAP = 0.05
MATERIAL_DISPERSION_DELTA = 0.20
MATERIAL_DEPENDENCE_CORRELATION = 0.15
MATERIAL_PIT_BIN_GAP = 0.10
BOOTSTRAP_SEEDS = {
    "mean_home_goals": 2_251_101,
    "mean_away_goals": 2_251_102,
    "mean_total_goals": 2_251_103,
    "dispersion_home": 2_251_111,
    "dispersion_away": 2_251_112,
    "dispersion_total": 2_251_113,
    "dependence_covariance": 2_251_121,
    "dependence_correlation": 2_251_122,
    "tail_ge_4": 2_251_131,
    "tail_ge_5": 2_251_132,
    "tail_ge_6": 2_251_133,
    "low_0_0": 2_251_141,
    "low_1_0": 2_251_142,
    "low_0_1": 2_251_143,
    "low_1_1": 2_251_144,
    "exact_context": 2_251_151,
}
DEFAULT_MANIFEST = ROOT / "artifacts" / "exact-poisson-adequacy-diagnostic-1" / "fixed_107_manifest.json"
DEFAULT_LAMBDA_REFERENCE = ROOT / "artifacts" / "exact-poisson-adequacy-diagnostic-1" / "fixed_107_market_lambda_reference.json"
DEFAULT_OUTPUT = ROOT / "artifacts" / "exact-poisson-adequacy-diagnostic-1" / "summary.json"
DEFAULT_REPORT = ROOT / "artifacts" / "exact-poisson-adequacy-diagnostic-1" / "report.md"
DEFAULT_UNIVERSE_ROOT = ROOT / "data" / "prediction_universe"
DEFAULT_PAIR_ROOT = ROOT / "data" / "prediction_quality" / "market_side_shadow_1" / "pairs"
DEFAULT_RESULT_ROOT = ROOT / "data" / "postmatch_automation" / "results"
OUTCOMES = ("home", "draw", "away")
FINAL_RESULT_SCOPES = {"regulation_90m_plus_stoppage", "regulation_90m", "90m"}
HORIZON_BANDS = (
    ("T_0_TO_60M", 0.0, 60.0),
    ("T_60_TO_180M", 60.0, 180.0),
    ("T_3_TO_6H", 180.0, 360.0),
    ("T_6_TO_12H", 360.0, 720.0),
    ("T_12_TO_24H", 720.0, 1440.0),
    ("T_24H_PLUS", 1440.0, None),
)
AUTHORITY = {
    "repository": "gemini077/Memory-Hub",
    "path": "PROJECTS/Football-Betting-OneShot/RESEARCH/2026-09-06-POST-223-POISSON-ADEQUACY-ROUTE-R1.md",
    "sha": "d0af7bdd1993f0f7a581ea3cb925065593215f99",
    "url": "https://github.com/gemini077/Memory-Hub/blob/main/PROJECTS/Football-Betting-OneShot/RESEARCH/2026-09-06-POST-223-POISSON-ADEQUACY-ROUTE-R1.md",
}


class MarketAuditError(ValueError):
    """Raised when the accepted local Market contract is not identifiable."""


def _load_json(path: Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _write_json(path: Path, value: Any) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _text(value: Any) -> str:
    return str(value).strip() if value not in (None, "") else ""


def _parse_time(value: Any) -> datetime | None:
    text = _text(value)
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _repo_relative(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT.resolve())).replace("\\", "/")
    except ValueError:
        return str(path)


def _score_text(score: tuple[int, int]) -> str:
    return f"{score[0]}-{score[1]}"


def _actual_outcome(score: tuple[int, int]) -> str:
    if score[0] > score[1]:
        return "home"
    if score[0] < score[1]:
        return "away"
    return "draw"


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
        consensus = {outcome: statistics.fmean(row["fair"][outcome] for row in valid) for outcome in OUTCOMES}
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
        valid.append({"bookmaker": key, "line": line, "fair_over_probability": fair[0], "fair_under_probability": fair[1]})
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


def _market_settlement_weights(matrix: Mapping[tuple[int, int], float], line: float, selection: str) -> tuple[float, float]:
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
        return {"status": "NOT_EVALUABLE", "reason": "OU_SOLVE_FAILED_FOR_ALL_VALID_BOOKMAKERS", "solve_reasons": dict(sorted(solve_reasons.items()))}
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


def _manifest_row(pair: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: pair.get(key)
        for key in (
            "pair_id",
            "match_id",
            "match_key",
            "kickoff_at",
            "source_cutoff",
            "freeze_created_at",
            "frozen_input_digest",
            "input_snapshot_ref",
        )
    }


def _canonical_rows(rows: Sequence[Mapping[str, Any]]) -> bytes:
    return json.dumps(list(rows), ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")


def _load_universe_map(universe_root: Path) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for path in sorted(Path(universe_root).glob("*.json")):
        try:
            document = _load_json(path)
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(document, Mapping):
            continue
        for fixture in document.get("fixtures") or []:
            if isinstance(fixture, Mapping) and fixture.get("matchId") is not None:
                result[str(fixture["matchId"])] = dict(fixture)
    return result


def _horizon_band(pair: Mapping[str, Any]) -> str:
    kickoff = _parse_time(pair.get("kickoff_at"))
    cutoff = _parse_time(pair.get("source_cutoff"))
    if kickoff is None or cutoff is None or cutoff >= kickoff:
        return "HORIZON_UNSAFE"
    minutes = (kickoff - cutoff).total_seconds() / 60.0
    for name, lower, upper in HORIZON_BANDS:
        if minutes >= lower and (upper is None or minutes < upper):
            return name
    return "HORIZON_UNSAFE"


def _load_lambda_reference(path: Path) -> tuple[dict[str, dict[str, float]], list[str]]:
    document = _load_json(path)
    rows = document.get("rows") if isinstance(document, Mapping) else None
    failures: list[str] = []
    if not isinstance(rows, list) or len(rows) != FIXED_COHORT_COUNT:
        failures.append("lambda_reference_count_not_107")
        rows = rows if isinstance(rows, list) else []
    reference: dict[str, dict[str, float]] = {}
    for row in rows:
        if not isinstance(row, Mapping) or not row.get("pair_id"):
            failures.append("lambda_reference_row_invalid")
            continue
        pair_id = str(row["pair_id"])
        if pair_id in reference:
            failures.append(f"lambda_reference_duplicate:{pair_id}")
        values = {key: _number(row.get(key)) for key in ("lambda_home", "lambda_away", "lambda_total", "score_matrix_tail_probability")}
        if any(value is None for value in values.values()):
            failures.append(f"lambda_reference_value_missing:{pair_id}")
            continue
        reference[pair_id] = {key: float(value) for key, value in values.items()}
    actual_digest = hashlib.sha256(_canonical_rows(rows)).hexdigest()
    if actual_digest != document.get("digest_sha256"):
        failures.append("lambda_reference_digest_mismatch")
    return reference, failures


def _fixed_evaluation_rows(
    *,
    manifest_path: Path,
    lambda_reference_path: Path,
    pairs: Sequence[Mapping[str, Any]],
    result_catalog: Mapping[str, Mapping[str, Any]],
    result_map: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    manifest = _load_json(manifest_path)
    manifest_rows = manifest.get("rows") if isinstance(manifest, Mapping) else None
    failures: list[str] = []
    if not isinstance(manifest_rows, list) or len(manifest_rows) != FIXED_COHORT_COUNT:
        failures.append("fixed_manifest_count_not_107")
        manifest_rows = manifest_rows if isinstance(manifest_rows, list) else []
    lambda_reference, lambda_failures = _load_lambda_reference(lambda_reference_path)
    failures.extend(lambda_failures)
    pair_by_id = {str(pair.get("pair_id")): pair for pair in pairs if pair.get("pair_id")}
    rows: list[dict[str, Any]] = []
    match_ids: set[str] = set()
    actual_manifest_rows: list[dict[str, Any]] = []
    for expected in manifest_rows:
        if not isinstance(expected, Mapping):
            failures.append("fixed_manifest_row_invalid")
            continue
        pair_id = str(expected.get("pair_id") or "")
        pair = pair_by_id.get(pair_id)
        if pair is None:
            failures.append(f"fixed_pair_missing:{pair_id}")
            continue
        actual_manifest_rows.append(_manifest_row(pair))
        for key, value in _manifest_row(pair).items():
            if value != expected.get(key):
                failures.append(f"fixed_pair_manifest_mismatch:{pair_id}:{key}")
        if pair.get("pair_status") != "PAIRED":
            failures.append(f"fixed_pair_not_paired:{pair_id}")
        if pair.get("post_match_input_used_for_generation") is not False:
            failures.append(f"fixed_pair_post_match_input:{pair_id}")
        match_id = str(pair.get("match_id") or pair.get("match_key") or "")
        if not match_id or match_id in match_ids:
            failures.append(f"fixed_match_identity_not_unique:{pair_id}")
        match_ids.add(match_id)
        result = result_catalog.get(str(pair.get("match_key") or ""))
        if result is None or result.get("scope") not in FINAL_RESULT_SCOPES:
            failures.append(f"fixed_result_scope_or_identity_missing:{pair_id}")
        actual = _actual_for_pair(pair, result_map)
        if actual is None:
            failures.append(f"fixed_result_missing:{pair_id}")
        selected = _load_legal_market_snapshot(pair)
        if selected.get("reason"):
            failures.append(f"fixed_market_snapshot:{pair_id}:{selected['reason']}")
            continue
        one_x2 = _market_extract_1x2(selected["snapshot"])
        ou = _market_extract_ou(selected["snapshot"])
        baseline = _build_market_baseline(one_x2, ou)
        if baseline.get("status") != "EVALUABLE":
            failures.append(f"fixed_market_lambda_not_evaluable:{pair_id}:{baseline.get('reason')}")
            continue
        projection = baseline["projection"]
        expected_lambda = lambda_reference.get(pair_id)
        if expected_lambda is None:
            failures.append(f"lambda_reference_pair_missing:{pair_id}")
        else:
            for key in ("lambda_home", "lambda_away", "lambda_total", "score_matrix_tail_probability"):
                if abs(float(projection[key]) - expected_lambda[key]) > 1e-12:
                    failures.append(f"fixed_market_lambda_mismatch:{pair_id}:{key}")
        if actual is None or actual not in projection["matrix"] or projection["matrix"].get(actual, 0.0) <= 0.0:
            failures.append(f"fixed_exact_actual_out_of_support:{pair_id}")
            continue
        rows.append({
            "pair": pair,
            "pair_id": pair_id,
            "match_id": match_id,
            "match_key": pair.get("match_key"),
            "kickoff_at": pair.get("kickoff_at"),
            "source_cutoff": pair.get("source_cutoff"),
            "actual": actual,
            "projection": projection,
            "market_snapshot_source": selected.get("source"),
            "market_snapshot_captured_at": selected.get("captured_at"),
            "horizon_band": _horizon_band(pair),
        })
    current_digest = hashlib.sha256(_canonical_rows(actual_manifest_rows)).hexdigest()
    if current_digest != manifest.get("cohort_digest_sha256"):
        failures.append("fixed_cohort_digest_mismatch")
    rows.sort(key=lambda row: (_parse_time(row.get("kickoff_at")) or datetime.min.replace(tzinfo=timezone.utc), str(row.get("match_id") or "")))
    chronology = {
        "match_count": len(rows),
        "earliest_kickoff": rows[0]["kickoff_at"] if rows else None,
        "latest_kickoff": rows[-1]["kickoff_at"] if rows else None,
        "manifest_digest_sha256": manifest.get("cohort_digest_sha256"),
        "current_digest_sha256": current_digest,
        "lambda_reference_digest_sha256": _load_json(lambda_reference_path).get("digest_sha256"),
    }
    if len(rows) != FIXED_COHORT_COUNT:
        failures.append("fixed_evaluation_row_count_not_107")
    if len({row["match_id"] for row in rows}) != len(rows):
        failures.append("fixed_evaluation_duplicate_match_identity")
    return rows, {
        "status": "PASS" if not failures else "FAIL",
        "requested_match_count": FIXED_COHORT_COUNT,
        "verified_match_count": len(rows),
        "unique_match_count": len({row["match_id"] for row in rows}),
        "chronology": chronology,
        "manifest": _repo_relative(manifest_path),
        "lambda_reference": _repo_relative(lambda_reference_path),
        "failures": sorted(set(failures)),
    }


def _quantile(values: Iterable[float], probability: float) -> float | None:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return None
    position = (len(ordered) - 1) * probability
    lower, upper = math.floor(position), math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def _bootstrap_mean(values: Sequence[float], *, seed: int, resamples: int = BOOTSTRAP_RESAMPLES) -> dict[str, Any]:
    clean = [float(value) for value in values]
    if not clean:
        return {"n": 0, "resamples": 0, "seed": seed, "mean": None, "ci95": [None, None]}
    rng = random.Random(seed)
    n = len(clean)
    means = [sum(clean[rng.randrange(n)] for _ in range(n)) / n for _ in range(int(resamples))]
    return {
        "n": n,
        "resamples": int(resamples),
        "seed": seed,
        "mean": statistics.fmean(clean),
        "ci95": [_quantile(means, 0.025), _quantile(means, 0.975)],
    }


def _bootstrap_statistic(
    rows: Sequence[Mapping[str, Any]],
    statistic: Callable[[Sequence[Mapping[str, Any]]], float],
    *,
    seed: int,
    resamples: int = BOOTSTRAP_RESAMPLES,
) -> dict[str, Any]:
    if not rows:
        return {"n": 0, "resamples": 0, "seed": seed, "value": None, "ci95": [None, None]}
    rng = random.Random(seed)
    n = len(rows)
    values = [float(statistic([rows[rng.randrange(n)] for _ in range(n)])) for _ in range(int(resamples))]
    return {
        "n": n,
        "resamples": int(resamples),
        "seed": seed,
        "value": float(statistic(rows)),
        "ci95": [_quantile(values, 0.025), _quantile(values, 0.975)],
    }


def _poisson_pmf(lam: float, goals: int) -> float:
    if goals < 0:
        return 0.0
    if lam < 0.0 or not math.isfinite(lam):
        raise ValueError("invalid Poisson intensity")
    if lam == 0.0:
        return 1.0 if goals == 0 else 0.0
    return math.exp(-lam + goals * math.log(lam) - math.lgamma(goals + 1.0))


def _poisson_cdf(lam: float, goals: int) -> float:
    if goals < 0:
        return 0.0
    term = math.exp(-lam)
    total = term
    for goal in range(1, goals + 1):
        term *= lam / goal
        total += term
    return min(1.0, max(0.0, total))


def _poisson_tail(lam: float, threshold: int) -> float:
    return min(1.0, max(0.0, 1.0 - _poisson_cdf(lam, threshold - 1)))


def _poisson_pit(lam: float, actual: int, uniform_value: float) -> float:
    return _poisson_cdf(lam, actual - 1) + uniform_value * _poisson_pmf(lam, actual)


def _dispersion_observation(row: Mapping[str, Any], observed_key: str, lambda_key: str) -> dict[str, float]:
    observed = float(row[observed_key])
    lam = float(row[lambda_key])
    standardized = (observed - lam) / math.sqrt(max(lam, MARKET_EPSILON))
    return {"standardized_residual": standardized, "pearson_component": standardized * standardized}


def _correlation(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right) or len(left) < 2:
        return 0.0
    left_mean, right_mean = statistics.fmean(left), statistics.fmean(right)
    numerator = sum((a - left_mean) * (b - right_mean) for a, b in zip(left, right))
    denominator = math.sqrt(sum((a - left_mean) ** 2 for a in left) * sum((b - right_mean) ** 2 for b in right))
    return numerator / denominator if denominator > 0.0 else 0.0


def _standardized_residuals(rows: Sequence[Mapping[str, Any]]) -> tuple[list[float], list[float]]:
    home = []
    away = []
    for row in rows:
        home.append(_dispersion_observation(row, "home_goals", "lambda_home")["standardized_residual"])
        away.append(_dispersion_observation(row, "away_goals", "lambda_away")["standardized_residual"])
    return home, away


def _dispersion_summary(rows: Sequence[Mapping[str, Any]], observed_key: str, lambda_key: str, seed_name: str) -> dict[str, Any]:
    observations = [_dispersion_observation(row, observed_key, lambda_key) for row in rows]
    components = [item["pearson_component"] for item in observations]
    residuals = [item["standardized_residual"] for item in observations]
    bootstrap = _bootstrap_mean(components, seed=BOOTSTRAP_SEEDS[seed_name])
    ci = bootstrap["ci95"]
    value = bootstrap["mean"]
    if value is not None and value > 1.0 + MATERIAL_DISPERSION_DELTA and ci[0] is not None and ci[0] > 1.0 + MATERIAL_DISPERSION_DELTA:
        classification = "OVERDISPERSED"
    elif value is not None and value < 1.0 - MATERIAL_DISPERSION_DELTA and ci[1] is not None and ci[1] < 1.0 - MATERIAL_DISPERSION_DELTA:
        classification = "UNDERDISPERSED"
    else:
        classification = "NOT_MATERIAL"
    return {
        "n": len(rows),
        "expected_poisson_dispersion": 1.0,
        "pearson_dispersion": value,
        "dispersion_delta_from_1": value - 1.0 if value is not None else None,
        "standardized_residual_mean": statistics.fmean(residuals) if residuals else None,
        "standardized_residual_variance": statistics.fmean((value - statistics.fmean(residuals)) ** 2 for value in residuals) if residuals else None,
        "bootstrap_95_ci": bootstrap,
        "material_threshold_absolute": MATERIAL_DISPERSION_DELTA,
        "classification": classification,
        "material_signal": classification != "NOT_MATERIAL",
    }


def _marginal_summary(rows: Sequence[Mapping[str, Any]], observed_key: str, lambda_key: str, seed_name: str) -> dict[str, Any]:
    observed = [int(row[observed_key]) for row in rows]
    predicted = [float(row[lambda_key]) for row in rows]
    gap_values = [float(value) - lam for value, lam in zip(observed, predicted)]
    bins = list(range(6)) + ["6+"]
    frequencies: dict[str, dict[str, Any]] = {}
    for bucket in bins:
        if bucket == "6+":
            observed_values = [value >= 6 for value in observed]
            predicted_values = [_poisson_tail(lam, 6) for lam in predicted]
        else:
            observed_values = [value == bucket for value in observed]
            predicted_values = [_poisson_pmf(lam, bucket) for lam in predicted]
        per_match_gap = [float(observed_value) - predicted_value for observed_value, predicted_value in zip(observed_values, predicted_values)]
        frequencies[str(bucket)] = {
            "observed_frequency": statistics.fmean(float(value) for value in observed_values) if observed_values else None,
            "predicted_frequency": statistics.fmean(predicted_values) if predicted_values else None,
            "calibration_gap_observed_minus_predicted": statistics.fmean(per_match_gap) if per_match_gap else None,
            "bootstrap_95_ci": _bootstrap_mean(per_match_gap, seed=BOOTSTRAP_SEEDS[seed_name] + (bucket if isinstance(bucket, int) else 6)),
        }
    return {
        "n": len(rows),
        "observed_mean": statistics.fmean(observed) if observed else None,
        "predicted_mean_lambda": statistics.fmean(predicted) if predicted else None,
        "mean_calibration_gap_observed_minus_predicted": statistics.fmean(gap_values) if gap_values else None,
        "mean_gap_bootstrap_95_ci": _bootstrap_mean(gap_values, seed=BOOTSTRAP_SEEDS[seed_name]),
        "frequency_bins": frequencies,
        "tail_bin": "6+",
    }


def _tail_summary(rows: Sequence[Mapping[str, Any]], threshold: int, seed_name: str) -> dict[str, Any]:
    indicators = [float(row["total_goals"] >= threshold) for row in rows]
    predicted = [_poisson_tail(float(row["lambda_total"]), threshold) for row in rows]
    gaps = [indicator - probability for indicator, probability in zip(indicators, predicted)]
    brier = [(indicator - probability) ** 2 for indicator, probability in zip(indicators, predicted)]
    bootstrap = _bootstrap_mean(gaps, seed=BOOTSTRAP_SEEDS[seed_name])
    ci = bootstrap["ci95"]
    signal = bool(
        bootstrap["mean"] is not None
        and abs(bootstrap["mean"]) >= MATERIAL_GAP
        and ci[0] is not None
        and ci[1] is not None
        and (ci[0] > 0.0 or ci[1] < 0.0)
    )
    return {
        "threshold": threshold,
        "n": len(rows),
        "observed_frequency": statistics.fmean(indicators) if indicators else None,
        "mean_predicted_probability": statistics.fmean(predicted) if predicted else None,
        "calibration_gap_observed_minus_predicted": bootstrap["mean"],
        "gap_bootstrap_95_ci": bootstrap,
        "exceedance_brier": statistics.fmean(brier) if brier else None,
        "material_threshold_absolute": MATERIAL_GAP,
        "material_signal": signal,
    }


def _low_score_summary(rows: Sequence[Mapping[str, Any]], home_goals: int, away_goals: int, seed_name: str) -> dict[str, Any]:
    score = f"{home_goals}-{away_goals}"
    indicators = [float(row["actual"] == (home_goals, away_goals)) for row in rows]
    predicted = [_poisson_pmf(float(row["lambda_home"]), home_goals) * _poisson_pmf(float(row["lambda_away"]), away_goals) for row in rows]
    gaps = [indicator - probability for indicator, probability in zip(indicators, predicted)]
    bootstrap = _bootstrap_mean(gaps, seed=BOOTSTRAP_SEEDS[seed_name])
    ci = bootstrap["ci95"]
    signal = bool(
        bootstrap["mean"] is not None
        and abs(bootstrap["mean"]) >= MATERIAL_GAP
        and ci[0] is not None
        and ci[1] is not None
        and (ci[0] > 0.0 or ci[1] < 0.0)
    )
    return {
        "score": score,
        "n": len(rows),
        "observed_frequency": statistics.fmean(indicators) if indicators else None,
        "mean_predicted_probability": statistics.fmean(predicted) if predicted else None,
        "calibration_gap_observed_minus_predicted": bootstrap["mean"],
        "gap_bootstrap_95_ci": bootstrap,
        "material_threshold_absolute": MATERIAL_GAP,
        "material_signal": signal,
    }


def _pit_statistics(values: Sequence[float]) -> dict[str, Any]:
    counts = [0] * PIT_BINS
    for value in values:
        index = min(PIT_BINS - 1, max(0, int(float(value) * PIT_BINS)))
        counts[index] += 1
    n = len(values)
    frequencies = [count / n for count in counts] if n else []
    deviations = [frequency - 1.0 / PIT_BINS for frequency in frequencies]
    ordered = sorted(values)
    cvm = (
        1.0 / (12.0 * n)
        + sum((value - (2.0 * index - 1.0) / (2.0 * n)) ** 2 for index, value in enumerate(ordered, start=1)) / n
        if n
        else None
    )
    return {
        "n": n,
        "histogram_counts": counts,
        "histogram_frequencies": frequencies,
        "expected_bin_frequency": 1.0 / PIT_BINS,
        "bin_deviations": deviations,
        "max_absolute_bin_deviation": max((abs(value) for value in deviations), default=None),
        "mean": statistics.fmean(values) if values else None,
        "variance": statistics.fmean((value - 0.5) ** 2 for value in values) if values else None,
        "cramer_von_mises": cvm,
    }


def _pit_summary(rows: Sequence[Mapping[str, Any]], observed_key: str, lambda_key: str, seed_offset: int) -> dict[str, Any]:
    def draw(seed: int) -> list[float]:
        rng = random.Random(seed)
        return [
            _poisson_pit(float(row[lambda_key]), int(row[observed_key]), rng.random())
            for row in rows
        ]

    primary = draw(PIT_SEED + seed_offset)
    repeated = [_pit_statistics(draw(PIT_SEED + seed_offset + replicate + 1)) for replicate in range(PIT_RANDOMIZATION_REPLICATES)]
    primary_stats = _pit_statistics(primary)
    mean_gap_bootstrap = _bootstrap_mean(
        [value - 0.5 for value in primary],
        seed=PIT_SEED + 1000 + seed_offset,
    )
    repeated_max = [value["max_absolute_bin_deviation"] for value in repeated if value["max_absolute_bin_deviation"] is not None]
    repeated_mean_gap = [abs(float(value["mean"]) - 0.5) for value in repeated if value.get("mean") is not None]
    robust_max_mean = statistics.fmean(repeated_max) if repeated_max else None
    primary_max = primary_stats["max_absolute_bin_deviation"]
    material_signal = bool(
        primary_max is not None
        and primary_max >= MATERIAL_PIT_BIN_GAP
        and robust_max_mean is not None
        and robust_max_mean >= MATERIAL_PIT_BIN_GAP
    )
    return {
        "n": len(rows),
        "seed": PIT_SEED + seed_offset,
        "randomization_replicates": PIT_RANDOMIZATION_REPLICATES,
        "primary": primary_stats,
        "primary_mean_minus_uniform": (primary_stats["mean"] - 0.5) if primary_stats["mean"] is not None else None,
        "primary_mean_bootstrap_95_ci": mean_gap_bootstrap,
        "repeated_randomization": {
            "max_abs_bin_deviation_mean": robust_max_mean,
            "max_abs_bin_deviation_min": min(repeated_max) if repeated_max else None,
            "max_abs_bin_deviation_max": max(repeated_max) if repeated_max else None,
            "absolute_mean_minus_uniform_mean": statistics.fmean(repeated_mean_gap) if repeated_mean_gap else None,
        },
        "material_threshold_max_abs_bin_deviation": MATERIAL_PIT_BIN_GAP,
        "material_signal": material_signal,
    }


def _dependence_summary(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    home = [float(row["standardized_home_residual"]) for row in rows]
    away = [float(row["standardized_away_residual"]) for row in rows]
    covariance_values = [left * right for left, right in zip(home, away)]
    covariance_bootstrap = _bootstrap_mean(covariance_values, seed=BOOTSTRAP_SEEDS["dependence_covariance"])

    def correlation_stat(sample: Sequence[Mapping[str, Any]]) -> float:
        return _correlation(
            [float(row["standardized_home_residual"]) for row in sample],
            [float(row["standardized_away_residual"]) for row in sample],
        )

    correlation_bootstrap = _bootstrap_statistic(rows, correlation_stat, seed=BOOTSTRAP_SEEDS["dependence_correlation"])
    correlation = correlation_stat(rows)
    covariance = covariance_bootstrap["mean"]
    covariance_ci = covariance_bootstrap["ci95"]
    correlation_ci = correlation_bootstrap["ci95"]
    material_signal = bool(
        (covariance is not None and abs(covariance) >= MATERIAL_DEPENDENCE_CORRELATION and covariance_ci[0] is not None and covariance_ci[1] is not None and (covariance_ci[0] > 0.0 or covariance_ci[1] < 0.0))
        or (abs(correlation) >= MATERIAL_DEPENDENCE_CORRELATION and correlation_ci[0] is not None and correlation_ci[1] is not None and (correlation_ci[0] > 0.0 or correlation_ci[1] < 0.0))
    )
    return {
        "n": len(rows),
        "independence_reference": 0.0,
        "standardized_residual_covariance": covariance,
        "covariance_bootstrap_95_ci": covariance_bootstrap,
        "standardized_residual_correlation": correlation,
        "correlation_bootstrap_95_ci": correlation_bootstrap,
        "material_threshold_absolute": MATERIAL_DEPENDENCE_CORRELATION,
        "material_signal": material_signal,
    }


def _exact_context(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    observations: list[dict[str, Any]] = []
    for row in rows:
        actual = row["actual"]
        matrix = row["projection"]["matrix"]
        ranked = sorted(matrix.items(), key=lambda item: (-item[1], item[0][0], item[0][1]))
        actual_probability = float(matrix[actual])
        observations.append({
            "actual_score_probability": actual_probability,
            "exact_nll": -math.log(max(MARKET_EPSILON, actual_probability)),
            "actual_score_rank": next(index for index, (score, _) in enumerate(ranked, start=1) if score == actual),
            "exact_top1": actual == ranked[0][0],
            "exact_top3": actual in {score for score, _ in ranked[:3]},
            "top1_score": _score_text(ranked[0][0]),
            "one_one_top1": ranked[0][0] == (1, 1),
        })
    nll = [value["exact_nll"] for value in observations]
    ranks = [float(value["actual_score_rank"]) for value in observations]
    return {
        "n": len(observations),
        "nll": statistics.fmean(nll) if nll else None,
        "nll_bootstrap_95_ci": _bootstrap_mean(nll, seed=BOOTSTRAP_SEEDS["exact_context"]),
        "top1_hit_rate": statistics.fmean(float(value["exact_top1"]) for value in observations) if observations else None,
        "top3_hit_rate": statistics.fmean(float(value["exact_top3"]) for value in observations) if observations else None,
        "mean_probability_assigned_to_actual_score": statistics.fmean(value["actual_score_probability"] for value in observations) if observations else None,
        "actual_score_rank": {
            "P10": _quantile(ranks, 0.10),
            "P25": _quantile(ranks, 0.25),
            "P50": _quantile(ranks, 0.50),
            "P75": _quantile(ranks, 0.75),
            "P90": _quantile(ranks, 0.90),
        },
        "one_one_top1_share": statistics.fmean(float(value["one_one_top1"]) for value in observations) if observations else None,
        "top_score_counts": dict(sorted(Counter(value["top1_score"] for value in observations).items())),
    }


def _diagnostic_rows(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for row in rows:
        actual = row["actual"]
        projection = row["projection"]
        matrix = projection["matrix"]
        ranked = sorted(matrix.items(), key=lambda item: (-item[1], item[0][0], item[0][1]))
        lambda_home = float(projection["lambda_home"])
        lambda_away = float(projection["lambda_away"])
        lambda_total = float(projection["lambda_total"])
        home_residual = (actual[0] - lambda_home) / math.sqrt(max(lambda_home, MARKET_EPSILON))
        away_residual = (actual[1] - lambda_away) / math.sqrt(max(lambda_away, MARKET_EPSILON))
        actual_probability = float(matrix[actual])
        output.append({
            "pair_id": row["pair_id"],
            "match_id": row["match_id"],
            "kickoff_at": row["kickoff_at"],
            "source_cutoff": row["source_cutoff"],
            "horizon_band": row["horizon_band"],
            "actual_score": _score_text(actual),
            "home_goals": actual[0],
            "away_goals": actual[1],
            "total_goals": actual[0] + actual[1],
            "lambda_home": lambda_home,
            "lambda_away": lambda_away,
            "lambda_total": lambda_total,
            "score_matrix_tail_probability": projection["score_matrix_tail_probability"],
            "standardized_home_residual": home_residual,
            "standardized_away_residual": away_residual,
            "actual_score_probability": actual_probability,
            "exact_nll": -math.log(max(MARKET_EPSILON, actual_probability)),
            "actual_score_rank": next(index for index, (score, _) in enumerate(ranked, start=1) if score == actual),
            "exact_top1": actual == ranked[0][0],
            "exact_top3": actual in {score for score, _ in ranked[:3]},
            "top1_score": _score_text(ranked[0][0]),
        })
    return output


def _row_exact_nll(row: Mapping[str, Any]) -> float:
    return -math.log(max(MARKET_EPSILON, float(row["projection"]["matrix"][row["actual"]])))


def _slice_summary(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Return descriptive-only slice values; no slice drives the decision gate."""
    if not rows:
        return {"n": 0}
    actual_home = [int(row["actual"][0]) for row in rows]
    actual_away = [int(row["actual"][1]) for row in rows]
    actual_total = [home + away for home, away in zip(actual_home, actual_away)]
    lambda_home = [float(row["projection"]["lambda_home"]) for row in rows]
    lambda_away = [float(row["projection"]["lambda_away"]) for row in rows]
    lambda_total = [float(row["projection"]["lambda_total"]) for row in rows]
    actual_matrix_probabilities = [
        float(row["projection"]["matrix"][row["actual"]]) for row in rows
    ]
    top1 = []
    top3 = []
    one_one = []
    for row in rows:
        matrix = row["projection"]["matrix"]
        ranked = sorted(matrix.items(), key=lambda item: (-item[1], item[0][0], item[0][1]))
        top1.append(float(row["actual"] == ranked[0][0]))
        top3.append(float(row["actual"] in {score for score, _ in ranked[:3]}))
        one_one.append(float(ranked[0][0] == (1, 1)))
    total_tail_observed = [float(value >= 4) for value in actual_total]
    total_tail_predicted = [_poisson_tail(lam, 4) for lam in lambda_total]
    low_score_observed = [float(row["actual"] == (1, 1)) for row in rows]
    low_score_predicted = [
        _poisson_pmf(float(row["projection"]["lambda_home"]), 1)
        * _poisson_pmf(float(row["projection"]["lambda_away"]), 1)
        for row in rows
    ]
    home_residual = [float(row["standardized_home_residual"]) for row in rows]
    away_residual = [float(row["standardized_away_residual"]) for row in rows]
    return {
        "n": len(rows),
        "observed_mean_home_goals": statistics.fmean(actual_home),
        "predicted_mean_home_lambda": statistics.fmean(lambda_home),
        "observed_mean_away_goals": statistics.fmean(actual_away),
        "predicted_mean_away_lambda": statistics.fmean(lambda_away),
        "observed_mean_total_goals": statistics.fmean(actual_total),
        "predicted_mean_total_lambda": statistics.fmean(lambda_total),
        "exact_nll_context_mean": statistics.fmean(_row_exact_nll(row) for row in rows),
        "actual_score_probability_mean": statistics.fmean(actual_matrix_probabilities),
        "top1_hit_rate_context": statistics.fmean(top1),
        "top3_hit_rate_context": statistics.fmean(top3),
        "top_score_1_1_share_context": statistics.fmean(one_one),
        "total_ge_4_observed_frequency": statistics.fmean(total_tail_observed),
        "total_ge_4_predicted_probability": statistics.fmean(total_tail_predicted),
        "total_ge_4_gap_observed_minus_predicted": statistics.fmean(
            observed - predicted
            for observed, predicted in zip(total_tail_observed, total_tail_predicted)
        ),
        "score_1_1_observed_frequency": statistics.fmean(low_score_observed),
        "score_1_1_predicted_probability": statistics.fmean(low_score_predicted),
        "score_1_1_gap_observed_minus_predicted": statistics.fmean(
            observed - predicted
            for observed, predicted in zip(low_score_observed, low_score_predicted)
        ),
        "standardized_residual_correlation": _correlation(home_residual, away_residual),
    }


def _descriptive_slices(
    rows: Sequence[Mapping[str, Any]],
    universe_map: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    chronological = sorted(
        rows,
        key=lambda row: (
            _parse_time(row.get("kickoff_at")) or datetime.min.replace(tzinfo=timezone.utc),
            str(row.get("match_id") or ""),
        ),
    )
    n = len(chronological)
    third_cut_1 = n // 3
    third_cut_2 = (2 * n) // 3
    groups: dict[str, list[Mapping[str, Any]]] = {
        "chronological_third_1": chronological[:third_cut_1],
        "chronological_third_2": chronological[third_cut_1:third_cut_2],
        "chronological_third_3": chronological[third_cut_2:],
    }
    horizon_groups: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    competition_groups: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in chronological:
        horizon_groups[str(row.get("horizon_band") or "UNKNOWN")].append(row)
        fixture = universe_map.get(str(row.get("match_id") or ""), {})
        competition = str(fixture.get("league") or "UNKNOWN").strip() or "UNKNOWN"
        competition_groups[competition].append(row)
    groups["horizon_band"] = horizon_groups
    groups["competition"] = competition_groups

    descriptive: dict[str, Any] = {}
    excluded_small: dict[str, dict[str, int]] = {}
    for category, category_groups in groups.items():
        if not isinstance(category_groups, Mapping):
            category_groups = {"all": category_groups}
        category_output: dict[str, Any] = {}
        category_excluded: dict[str, int] = {}
        for label, subset in sorted(category_groups.items(), key=lambda item: str(item[0])):
            subset_rows = list(subset)
            if len(subset_rows) < MIN_MEANINGFUL_SLICE:
                category_excluded[str(label)] = len(subset_rows)
                continue
            category_output[str(label)] = _slice_summary(subset_rows)
        if category_output:
            descriptive[category] = category_output
        if category_excluded:
            excluded_small[category] = category_excluded
    return {
        "minimum_slice_n": MIN_MEANINGFUL_SLICE,
        "descriptive_slices": descriptive,
        "excluded_small_slices": excluded_small,
    }


def _ci_excludes_zero(bootstrap: Mapping[str, Any]) -> bool:
    ci = bootstrap.get("ci95")
    return bool(
        isinstance(ci, Sequence)
        and len(ci) == 2
        and ci[0] is not None
        and ci[1] is not None
        and (float(ci[0]) > 0.0 or float(ci[1]) < 0.0)
    )


def _material_gap_signal(value: Any, bootstrap: Mapping[str, Any], threshold: float = MATERIAL_GAP) -> bool:
    return bool(
        value is not None
        and abs(float(value)) >= threshold
        and _ci_excludes_zero(bootstrap)
    )


def _marginal_structural_signals(marginal: Mapping[str, Any]) -> tuple[bool, bool, list[str]]:
    tail_signal = False
    low_signal = False
    reasons: list[str] = []
    for side in ("home", "away", "total"):
        summary = marginal.get(side, {})
        for bucket, entry in (summary.get("frequency_bins") or {}).items():
            if not isinstance(entry, Mapping):
                continue
            gap = entry.get("calibration_gap_observed_minus_predicted")
            bootstrap = entry.get("bootstrap_95_ci") or {}
            if not _material_gap_signal(gap, bootstrap):
                continue
            if str(bucket) in {"0", "1"}:
                low_signal = True
                reasons.append(f"marginal_{side}_{bucket}")
            elif str(bucket) in {"4", "5", "6+"}:
                tail_signal = True
                reasons.append(f"marginal_{side}_{bucket}")
    return tail_signal, low_signal, reasons


def _decision(
    diagnostics: Mapping[str, Any],
    *,
    authority_status: str,
) -> dict[str, Any]:
    if authority_status != "PASS":
        return {
            "decision": "FAIL_CLOSED",
            "misspecification_dimension": None,
            "structural_signal": False,
            "directional_signal": False,
            "checks": {"fixed_cohort_authority": "FAIL"},
            "reasons": ["fixed_107_or_market_lambda_authority_failed"],
        }

    right_tail = diagnostics.get("right_tail", {})
    dispersion = diagnostics.get("dispersion", {})
    marginal = diagnostics.get("marginal_calibration", {})
    low_score = diagnostics.get("low_score", {})
    dependence = diagnostics.get("dependence", {})
    pit = diagnostics.get("pit", {})

    tail_signal, marginal_low_signal, marginal_reasons = _marginal_structural_signals(marginal)
    tail_reasons = [
        f"total_ge_{threshold}"
        for threshold, entry in sorted(right_tail.items())
        if isinstance(entry, Mapping) and entry.get("material_signal")
    ]
    if dispersion.get("total", {}).get("material_signal"):
        tail_signal = True
        tail_reasons.append("total_dispersion")
    low_reasons = [
        str(score)
        for score, entry in sorted(low_score.items())
        if isinstance(entry, Mapping) and entry.get("material_signal")
    ]
    low_signal = bool(low_reasons or marginal_low_signal)
    dependence_signal = bool(dependence.get("material_signal"))
    dimensions: list[str] = []
    if tail_signal:
        dimensions.append("TAIL")
    if dependence_signal:
        dimensions.append("DEPENDENCE")
    if low_signal:
        dimensions.append("LOW_SCORE")
    dimensions = sorted(set(dimensions))

    directional_reasons: list[str] = []
    for side, summary in marginal.items():
        if not isinstance(summary, Mapping):
            continue
        if _ci_excludes_zero(summary.get("mean_gap_bootstrap_95_ci") or {}) and abs(float(summary.get("mean_calibration_gap_observed_minus_predicted") or 0.0)) >= 0.02:
            directional_reasons.append(f"marginal_mean_{side}")
    for threshold, entry in sorted(right_tail.items()):
        if isinstance(entry, Mapping) and _ci_excludes_zero(entry.get("gap_bootstrap_95_ci") or {}):
            directional_reasons.append(f"tail_{threshold}")
    for score, entry in sorted(low_score.items()):
        if isinstance(entry, Mapping) and _ci_excludes_zero(entry.get("gap_bootstrap_95_ci") or {}):
            directional_reasons.append(f"low_score_{score}")
    if dependence_signal or _ci_excludes_zero(dependence.get("correlation_bootstrap_95_ci") or {}):
        directional_reasons.append("dependence")
    if any(isinstance(entry, Mapping) and entry.get("material_signal") for entry in pit.values()):
        directional_reasons.append("randomized_pit")
    else:
        for side, entry in pit.items():
            if isinstance(entry, Mapping) and _ci_excludes_zero(entry.get("primary_mean_bootstrap_95_ci") or {}):
                directional_reasons.append(f"pit_mean_{side}")

    if dimensions:
        decision = "POISSON_MISSPECIFICATION_SIGNAL_ESTABLISHED"
        dimension = dimensions[0] if len(dimensions) == 1 else "MIXED"
    elif directional_reasons:
        decision = "POISSON_ADEQUACY_INCONCLUSIVE"
        dimension = None
    else:
        decision = "POISSON_ADEQUACY_NOT_REJECTED"
        dimension = None
    return {
        "decision": decision,
        "misspecification_dimension": dimension,
        "structural_signal": bool(dimensions),
        "directional_signal": bool(directional_reasons),
        "checks": {
            "fixed_cohort_authority": "PASS",
            "tail_signal": bool(tail_signal),
            "tail_reasons": sorted(set(tail_reasons + marginal_reasons if tail_signal else tail_reasons)),
            "dependence_signal": dependence_signal,
            "low_score_signal": low_signal,
            "low_score_reasons": sorted(set(low_reasons + [reason for reason in marginal_reasons if reason.startswith("marginal_") and reason.rsplit("_", 1)[-1] in {"0", "1"}])),
            "directional_reasons": sorted(set(directional_reasons)),
            "material_gap_threshold": MATERIAL_GAP,
            "material_dispersion_delta": MATERIAL_DISPERSION_DELTA,
            "material_dependence_absolute_correlation_or_covariance": MATERIAL_DEPENDENCE_CORRELATION,
            "material_pit_max_bin_gap": MATERIAL_PIT_BIN_GAP,
        },
        "reasons": sorted(set(tail_reasons + low_reasons + marginal_reasons + directional_reasons)),
    }


def _decorate_rows(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for row in rows:
        actual = row["actual"]
        projection = row["projection"]
        output.append({
            **row,
            "home_goals": int(actual[0]),
            "away_goals": int(actual[1]),
            "total_goals": int(actual[0] + actual[1]),
            "lambda_home": float(projection["lambda_home"]),
            "lambda_away": float(projection["lambda_away"]),
            "lambda_total": float(projection["lambda_total"]),
            "standardized_home_residual": (actual[0] - float(projection["lambda_home"])) / math.sqrt(max(float(projection["lambda_home"]), MARKET_EPSILON)),
            "standardized_away_residual": (actual[1] - float(projection["lambda_away"])) / math.sqrt(max(float(projection["lambda_away"]), MARKET_EPSILON)),
        })
    return output


def _empty_metrics() -> dict[str, Any]:
    return {
        "marginal_calibration": None,
        "dispersion": None,
        "dependence": None,
        "pit": None,
        "right_tail": None,
        "low_score": None,
        "exact_context": None,
        "slices": None,
    }


def run_diagnostic(
    *,
    manifest_path: Path = DEFAULT_MANIFEST,
    lambda_reference_path: Path = DEFAULT_LAMBDA_REFERENCE,
    pair_root: Path = DEFAULT_PAIR_ROOT,
    result_root: Path = DEFAULT_RESULT_ROOT,
    universe_root: Path = DEFAULT_UNIVERSE_ROOT,
) -> dict[str, Any]:
    pairs = load_persisted_pairs(pair_root)
    result_catalog, result_catalog_stats = discover_verified_results(result_root)
    result_map, result_map_stats = build_identity_safe_result_map(pairs, result_catalog)
    rows, authority = _fixed_evaluation_rows(
        manifest_path=Path(manifest_path),
        lambda_reference_path=Path(lambda_reference_path),
        pairs=pairs,
        result_catalog=result_catalog,
        result_map=result_map,
    )
    universe_map = _load_universe_map(Path(universe_root))
    metrics = _empty_metrics()
    compact_rows: list[dict[str, Any]] = []
    if authority["status"] == "PASS":
        decorated_rows = _decorate_rows(rows)
        for row in decorated_rows:
            row["universe_league"] = str(universe_map.get(str(row["match_id"]), {}).get("league") or "UNKNOWN")
        metrics["marginal_calibration"] = {
            "home": _marginal_summary(decorated_rows, "home_goals", "lambda_home", "mean_home_goals"),
            "away": _marginal_summary(decorated_rows, "away_goals", "lambda_away", "mean_away_goals"),
            "total": _marginal_summary(decorated_rows, "total_goals", "lambda_total", "mean_total_goals"),
        }
        metrics["dispersion"] = {
            "home": _dispersion_summary(decorated_rows, "home_goals", "lambda_home", "dispersion_home"),
            "away": _dispersion_summary(decorated_rows, "away_goals", "lambda_away", "dispersion_away"),
            "total": _dispersion_summary(decorated_rows, "total_goals", "lambda_total", "dispersion_total"),
        }
        metrics["dependence"] = _dependence_summary(decorated_rows)
        metrics["pit"] = {
            "home": _pit_summary(decorated_rows, "home_goals", "lambda_home", 1),
            "away": _pit_summary(decorated_rows, "away_goals", "lambda_away", 2),
            "total": _pit_summary(decorated_rows, "total_goals", "lambda_total", 3),
        }
        metrics["right_tail"] = {
            str(threshold): _tail_summary(decorated_rows, threshold, f"tail_ge_{threshold}")
            for threshold in (4, 5, 6)
        }
        metrics["low_score"] = {
            score: _low_score_summary(decorated_rows, home, away, f"low_{score.replace('-', '_')}")
            for score, home, away in (("0-0", 0, 0), ("1-0", 1, 0), ("0-1", 0, 1), ("1-1", 1, 1))
        }
        metrics["exact_context"] = _exact_context(decorated_rows)
        metrics["slices"] = _descriptive_slices(decorated_rows, universe_map)
        compact_rows = _diagnostic_rows(rows)
        for compact, row in zip(compact_rows, decorated_rows):
            compact["universe_league"] = row["universe_league"]
    decision = _decision(metrics, authority_status=authority["status"])
    exact = metrics.get("exact_context") or {}
    integrity_failures = list(authority.get("failures") or [])
    evidence = {
        "schema_version": SCHEMA_VERSION,
        "milestone": MILESTONE,
        "reviewed_at": datetime.now(timezone.utc).isoformat(),
        "decision": decision["decision"],
        "misspecification_dimension": decision["misspecification_dimension"],
        "decision_detail": decision,
        "authority": AUTHORITY,
        "fixed_cohort": authority,
        "exact_context": exact,
        "diagnostics": metrics,
        "POISSON_EXACT_NLL": exact.get("nll"),
        "POISSON_EXACT_NLL_BOOTSTRAP_95_CI": exact.get("nll_bootstrap_95_ci"),
        "POISSON_TOP1": exact.get("top1_hit_rate"),
        "POISSON_TOP3": exact.get("top3_hit_rate"),
        "DC_EXACT_NLL": None,
        "NB_EXACT_NLL": None,
        "DC_DELTA_CI": None,
        "NB_DELTA_CI": None,
        "BEST_SUPPORTED_FAMILY": None,
        "1X2_SAFETY": "NOT_APPLICABLE_PARAMETER_FREE_DIAGNOSTIC",
        "bootstrap": {
            "resamples": BOOTSTRAP_RESAMPLES,
            "seeds": BOOTSTRAP_SEEDS,
        },
        "randomized_pit": {
            "base_seed": PIT_SEED,
            "bins": PIT_BINS,
            "randomization_replicates": PIT_RANDOMIZATION_REPLICATES,
        },
        "paired_rows": compact_rows,
        "integrity": {
            "status": "PASS" if not integrity_failures else "FAIL_CLOSED",
            "failures": sorted(set(integrity_failures)),
            "fixed_market_lambda_checked": True,
            "same_time_market_reference_only": True,
            "network_calls": False,
            "new_data_source": False,
            "new_model_or_parameter_fit": False,
            "alternative_family_comparison": False,
            "serving_modified": False,
            "ui_modified": False,
            "history_modified": False,
            "replay_or_backfill": False,
            "automatic_promotion": False,
        },
        "source": {
            "manifest": _repo_relative(Path(manifest_path)),
            "lambda_reference": _repo_relative(Path(lambda_reference_path)),
            "pair_root": _repo_relative(Path(pair_root)),
            "result_root": _repo_relative(Path(result_root)),
            "universe_root": _repo_relative(Path(universe_root)),
            "result_catalog_stats": result_catalog_stats,
            "result_map_stats": result_map_stats,
        },
        "forbidden_actions": [
            "fit_rho_or_kappa",
            "fit_new_parameters",
            "compare_dixon_coles_negative_binomial_or_cmp",
            "adjust_champion_or_c_weights",
            "anti_1_1_or_diversity_patch",
            "replay_or_backfill",
            "new_data_source",
            "serving_ui_or_history_change",
            "automatic_promotion",
        ],
    }
    return evidence


def _format_number(value: Any, digits: int = 6) -> str:
    if value is None:
        return "NA"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return f"{float(value):.{digits}f}"
    return str(value)


def _format_ci(bootstrap: Mapping[str, Any] | None) -> str:
    if not isinstance(bootstrap, Mapping):
        return "NA"
    ci = bootstrap.get("ci95")
    if not isinstance(ci, Sequence) or len(ci) != 2:
        return "NA"
    return f"[{_format_number(ci[0])}, {_format_number(ci[1])}]"


def render_report(evidence: Mapping[str, Any]) -> str:
    decision = str(evidence.get("decision") or "FAIL_CLOSED")
    dimension = evidence.get("misspecification_dimension")
    authority = evidence.get("fixed_cohort") or {}
    diagnostics = evidence.get("diagnostics") or {}
    marginal = diagnostics.get("marginal_calibration") or {}
    dispersion = diagnostics.get("dispersion") or {}
    dependence = diagnostics.get("dependence") or {}
    pit = diagnostics.get("pit") or {}
    tails = diagnostics.get("right_tail") or {}
    low_score = diagnostics.get("low_score") or {}
    exact = diagnostics.get("exact_context") or {}
    lines = [
        f"# {MILESTONE}",
        "",
        f"- Decision: `{decision}`",
        f"- Misspecification dimension: `{dimension or 'NONE'}`",
        f"- Fixed cohort: `{authority.get('unique_match_count', 0)}/{FIXED_COHORT_COUNT}` unique matches; authority `{authority.get('status')}`",
        f"- Chronology: `{(authority.get('chronology') or {}).get('earliest_kickoff')}` to `{(authority.get('chronology') or {}).get('latest_kickoff')}`",
        f"- Lambda reference digest: `{(authority.get('chronology') or {}).get('lambda_reference_digest_sha256')}`",
        "",
        "## Fixed parameter-free diagnostics",
        "",
        "| Quantity | Observed | Predicted / reference | Bootstrap 95% CI |",
        "|---|---:|---:|---:|",
    ]
    for side, label in (("home", "Home goals"), ("away", "Away goals"), ("total", "Total goals")):
        summary = marginal.get(side) or {}
        lines.append(
            f"| {label} mean | {_format_number(summary.get('observed_mean'))} | {_format_number(summary.get('predicted_mean_lambda'))} | {_format_ci(summary.get('mean_gap_bootstrap_95_ci'))} gap |"
        )
        disp = dispersion.get(side) or {}
        lines.append(
            f"| {label} dispersion | {_format_number(disp.get('pearson_dispersion'))} | 1.000000 | {_format_ci(disp.get('bootstrap_95_ci'))} |"
        )
    lines.extend([
        "",
        "### Home/away dependence",
        f"- Standardized residual covariance: `{_format_number(dependence.get('standardized_residual_covariance'))}`; CI `{_format_ci(dependence.get('covariance_bootstrap_95_ci'))}`",
        f"- Standardized residual correlation: `{_format_number(dependence.get('standardized_residual_correlation'))}`; CI `{_format_ci(dependence.get('correlation_bootstrap_95_ci'))}`",
        "",
        "### Randomized PIT",
    ])
    for side in ("home", "away", "total"):
        summary = pit.get(side) or {}
        primary = summary.get("primary") or {}
        repeated = summary.get("repeated_randomization") or {}
        lines.append(
            f"- {side}: seed `{summary.get('seed')}`, bins `{PIT_BINS}`, max bin gap `{_format_number(primary.get('max_absolute_bin_deviation'))}`, mean-minus-0.5 CI `{_format_ci(summary.get('primary_mean_bootstrap_95_ci'))}`, repeated max-gap mean `{_format_number(repeated.get('max_abs_bin_deviation_mean'))}`"
        )
    lines.extend(["", "### Right tails", "", "| Tail | Observed | Predicted | Gap | CI | Signal |", "|---|---:|---:|---:|---:|---|"])
    for threshold in ("4", "5", "6"):
        entry = tails.get(threshold) or {}
        lines.append(
            f"| total >= {threshold} | {_format_number(entry.get('observed_frequency'))} | {_format_number(entry.get('mean_predicted_probability'))} | {_format_number(entry.get('calibration_gap_observed_minus_predicted'))} | {_format_ci(entry.get('gap_bootstrap_95_ci'))} | {entry.get('material_signal')} |"
        )
    lines.extend(["", "### Low-score cells", "", "| Score | Observed | Predicted | Gap | CI | Signal |", "|---|---:|---:|---:|---:|---|"])
    for score in ("0-0", "1-0", "0-1", "1-1"):
        entry = low_score.get(score) or {}
        lines.append(
            f"| {score} | {_format_number(entry.get('observed_frequency'))} | {_format_number(entry.get('mean_predicted_probability'))} | {_format_number(entry.get('calibration_gap_observed_minus_predicted'))} | {_format_ci(entry.get('gap_bootstrap_95_ci'))} | {entry.get('material_signal')} |"
        )
    lines.extend([
        "",
        "### Exact-score context only",
        f"- Exact NLL: `{_format_number(exact.get('nll'))}`; IID bootstrap 95% CI `{_format_ci(exact.get('nll_bootstrap_95_ci'))}`",
        f"- Top1: `{_format_number(exact.get('top1_hit_rate'))}`; Top3: `{_format_number(exact.get('top3_hit_rate'))}`; mean actual-score probability `{_format_number(exact.get('mean_probability_assigned_to_actual_score'))}`",
        f"- Actual-score rank quantiles: `{json.dumps(exact.get('actual_score_rank') or {}, sort_keys=True)}`",
        f"- 1-1 top-score share: `{_format_number(exact.get('one_one_top1_share'))}`",
        "",
        "### Score space / tails / support",
        f"- Fixed Market lambda was reconstructed with the accepted #189 same-time contract and the fixed 20x20 score matrix; matrix tail mass is carried per match.",
        "- Poisson tail diagnostics use analytic independent-Poisson total-goal tails; no tail renormalization or new score family was introduced.",
        "- Actual scores outside the supported matrix would fail closed; all 107 actual scores were in support.",
        "",
        "### Scope / integrity",
        "- No training, parameter fitting, alternative-family comparison, serving/UI/history change, replay/backfill, new source, or automatic promotion.",
        f"- Bootstrap resamples: `{BOOTSTRAP_RESAMPLES}`; fixed PIT seed: `{PIT_SEED}`; PIT randomization replicates: `{PIT_RANDOMIZATION_REPLICATES}`.",
        f"- Integrity: `{(evidence.get('integrity') or {}).get('status')}`",
    ])
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--lambda-reference", type=Path, default=DEFAULT_LAMBDA_REFERENCE)
    parser.add_argument("--pair-root", type=Path, default=DEFAULT_PAIR_ROOT)
    parser.add_argument("--result-root", type=Path, default=DEFAULT_RESULT_ROOT)
    parser.add_argument("--universe-root", type=Path, default=DEFAULT_UNIVERSE_ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--write", action="store_true", help="write summary.json and report.md")
    args = parser.parse_args(argv)
    evidence = run_diagnostic(
        manifest_path=args.manifest,
        lambda_reference_path=args.lambda_reference,
        pair_root=args.pair_root,
        result_root=args.result_root,
        universe_root=args.universe_root,
    )
    if args.write:
        _write_json(args.output, evidence)
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(render_report(evidence), encoding="utf-8")
    print(json.dumps({
        "decision": evidence["decision"],
        "misspecification_dimension": evidence["misspecification_dimension"],
        "fixed_cohort": evidence["fixed_cohort"],
        "integrity": evidence["integrity"],
    }, ensure_ascii=False, sort_keys=True))
    return 0 if evidence["decision"] != "FAIL_CLOSED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
