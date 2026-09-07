#!/usr/bin/env python3
"""Train and run the shadow-only solution-first goal-intensity challenger.

The implementation is intentionally dependency-free at the production boundary.
It uses two deterministic Poisson gradient-boosted stump models, one for each
goal count, with ``log(lambda_market_side)`` as the immutable offset.  The
external training lane is explicitly labelled ``EXTERNAL_PRETRAIN_ONLY`` /
``HORIZON_TRANSFER``; it is never treated as FBOS same-horizon promotion
evidence.  The live sidecar reads only frozen prematch snapshots and writes a
separate namespace.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path
import statistics
import sys
from typing import Any, Iterable, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from market_contracts import split_quarter_line  # noqa: E402
from market_side_shadow import _actual_for_pair, load_persisted_pairs  # noqa: E402
from market_side_shadow_refresh import (  # noqa: E402
    build_identity_safe_result_map,
    discover_verified_results,
)
from risk_engine import dixon_coles_score_matrix  # noqa: E402


MILESTONE = "SOLUTION-FIRST-GOAL-INTENSITY-CHALLENGER-1"
SCHEMA_VERSION = "solution_first_goal_intensity_shadow_1.v1"
MODEL_FAMILY = "market_offset_goal_intensity_boosted_poisson_v1"
MODEL_BACKEND = "stdlib_poisson_stump_booster_v1"
FEATURE_SCHEMA = "prematch_venue_overall_goal_rates_v1"
TRAINING_AUTHORITY = "EXTERNAL_PRETRAIN_ONLY/HORIZON_TRANSFER"
EXTERNAL_SOURCE = "Football-Data.co.uk"
EXTERNAL_ROOT = ROOT / "artifacts" / "solution-first-goal-intensity-1" / "external"
OUTPUT_ROOT = ROOT / "data" / "prediction_quality" / "solution_first_goal_intensity_shadow_1"
DEFAULT_SUMMARY = OUTPUT_ROOT / "summary.json"
DEFAULT_REPORT = OUTPUT_ROOT / "report.md"
DEFAULT_MODEL = OUTPUT_ROOT / "model.json"
DEFAULT_SHADOW_OUTPUT = OUTPUT_ROOT / "latest.json"
DEFAULT_PAIR_ROOT = ROOT / "data" / "prediction_quality" / "market_side_shadow_1" / "pairs"
DEFAULT_EVAL_CUTOFF = datetime(2026, 8, 30, 19, 30, tzinfo=timezone(timedelta(hours=8)))
DEFAULT_PROSPECTIVE_AFTER = None

MARKET_MAX_GOALS = 20
SCORE_MAX_GOALS = 12
MARKET_EPSILON = 1e-12
MARKET_OU_LOWER = 0.001
MARKET_OU_UPPER = 20.0
MARKET_OU_ITERATIONS = 90
MARKET_SHARE_LOWER = 0.01
MARKET_SHARE_UPPER = 0.99
MARKET_SHARE_ITERATIONS = 70
ROLLING_WINDOW = 10
MIN_FORM_MATCHES = 3
MIN_EXTERNAL_ROWS = 200
TRAIN_FRACTION = 0.70
VALIDATION_FRACTION = 0.15
TIME_DECAY_HALF_LIFE_DAYS = 365.0
BOOSTER_ESTIMATORS = 24
BOOSTER_LEARNING_RATE = 0.05
BOOSTER_L2 = 5.0
BOOSTER_MIN_SAMPLES_LEAF = 25
BOOSTER_MAX_THRESHOLDS = 10
BOOSTER_MAX_LEAF_VALUE = 0.35
BOOSTER_EARLY_STOPPING_ROUNDS = 6
OUTPUT_LAMBDA_MIN = 0.05
OUTPUT_LAMBDA_MAX = 8.0
OUTCOMES = ("home", "draw", "away")
FEATURE_NAMES = (
    "home_attack_venue_rate",
    "home_defence_venue_rate",
    "away_attack_venue_rate",
    "away_defence_venue_rate",
    "home_attack_overall_rate",
    "home_defence_overall_rate",
    "away_attack_overall_rate",
    "away_defence_overall_rate",
    "home_venue_matches_norm",
    "away_venue_matches_norm",
    "home_overall_matches_norm",
    "away_overall_matches_norm",
)
FEATURE_SCHEMA_DEFINITION = {
    "version": FEATURE_SCHEMA,
    "window": ROLLING_WINDOW,
    "fields": list(FEATURE_NAMES),
    "source": "frozen nowscore.shuju.recent_form in live FBOS; rolling historical FTHG/FTAG state in external pretraining",
    "missingness": "venue block requires 3 prior matches; otherwise same-team overall block is used; rows without 3 overall matches are excluded",
    "result_leakage_guard": "features are read before source_cutoff in live and before current kickoff in external chronological construction",
}
LEAGUE_CODES = ("E0", "E1", "D1", "I1", "SP1", "F1")
SEASON_CODES = ("2223", "2324", "2425", "2526")


class MarketAuditError(ValueError):
    """Raised when the same-time market baseline is not identifiable."""


class TrainingAuthorityBlocked(RuntimeError):
    """Raised when no legal, reproducible training contract exists."""


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _parse_datetime(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _write_json(path: Path, value: Any) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _repo_relative(path: Path) -> str:
    try:
        return str(Path(path).resolve().relative_to(ROOT.resolve())).replace("\\", "/")
    except ValueError:
        return str(path)


def _mean(values: Iterable[float]) -> float | None:
    values = [float(value) for value in values if _number(value) is not None]
    return statistics.fmean(values) if values else None


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(float(lower), min(float(upper), float(value)))


def _safe_exp(value: float) -> float:
    return math.exp(_clamp(float(value), -20.0, 20.0))


def _score_text(score: tuple[int, int]) -> str:
    return f"{score[0]}-{score[1]}"


def _actual_outcome(score: tuple[int, int]) -> str:
    return "home" if score[0] > score[1] else "draw" if score[0] == score[1] else "away"


# ---------------------------------------------------------------------------
# Accepted same-time Market lambda adapter
# ---------------------------------------------------------------------------


def _devig(decimal_odds: Iterable[Any]) -> list[float]:
    values = []
    for value in decimal_odds:
        number = _number(value)
        if number is None or number <= 1.0:
            raise MarketAuditError("INVALID_DECIMAL_ODDS")
        values.append(number)
    inverse = [1.0 / value for value in values]
    total = sum(inverse)
    if total <= 0.0 or not math.isfinite(total):
        raise MarketAuditError("INVALID_DEVIG_SUM")
    return [value / total for value in inverse]


def _water_to_decimal(value: Any) -> float:
    number = _number(value)
    if number is None or number <= 0.0:
        raise MarketAuditError("INVALID_HK_WATER")
    return 1.0 + number


def _quote_key(row: Mapping[str, Any]) -> str:
    for key in ("cid", "source_company_id", "company_id", "name"):
        value = str(row.get(key) or "").strip()
        if value:
            return value.casefold()
    return ""


def _valid_quarter_line(value: Any) -> float | None:
    number = _number(value)
    if number is None or number < 0.0:
        return None
    rounded = round(number * 4.0) / 4.0
    return rounded if abs(number - rounded) <= 1e-8 else None


def _snapshot_rows(snapshot: Mapping[str, Any], family: str) -> list[dict[str, Any]]:
    market = snapshot.get(family)
    if not isinstance(market, Mapping):
        return []
    key = "bookmakers" if family == "ouzhi" else "companies"
    rows = market.get(key)
    return [dict(row) for row in rows if isinstance(row, Mapping)] if isinstance(rows, list) else []


def _live_market_quotes(snapshot: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    one_x2_rows = []
    seen_one_x2: set[str] = set()
    for row in _snapshot_rows(snapshot, "ouzhi"):
        key = _quote_key(row)
        odds = row.get("spf_current")
        if not key or key in seen_one_x2 or not isinstance(odds, Mapping):
            continue
        values = [_number(odds.get(outcome)) for outcome in OUTCOMES]
        if any(value is None or value <= 1.0 for value in values):
            continue
        seen_one_x2.add(key)
        fair = _devig(values)
        one_x2_rows.append({"key": key, "fair": dict(zip(OUTCOMES, fair))})
    if not one_x2_rows:
        raise MarketAuditError("NO_VALID_SAME_TIME_1X2")
    consensus = {
        outcome: statistics.fmean(row["fair"][outcome] for row in one_x2_rows)
        for outcome in OUTCOMES
    }
    total = sum(consensus.values())
    one_x2 = {outcome: value / total for outcome, value in consensus.items()}

    ou_rows = []
    seen_ou: set[str] = set()
    for row in _snapshot_rows(snapshot, "daxiao"):
        key = _quote_key(row)
        line = _valid_quarter_line(row.get("current_line"))
        if not key or key in seen_ou or line is None:
            continue
        try:
            over, under = _devig((_water_to_decimal(row.get("current_over_water")), _water_to_decimal(row.get("current_under_water"))))
        except MarketAuditError:
            continue
        seen_ou.add(key)
        ou_rows.append({"key": key, "line": line, "over": over, "under": under})
    if not ou_rows:
        raise MarketAuditError("NO_VALID_SAME_TIME_TOTAL")
    return {"consensus": one_x2, "valid_count": len(one_x2_rows)}, {"quotes": ou_rows}


def _poisson_pmf(lam: float, goals: int) -> float:
    return math.exp(-lam) * lam**goals / math.factorial(goals)


def _raw_score_matrix(lambda_home: float, lambda_away: float, max_goals: int) -> tuple[dict[tuple[int, int], float], float]:
    home = [_poisson_pmf(lambda_home, goal) for goal in range(max_goals + 1)]
    away = [_poisson_pmf(lambda_away, goal) for goal in range(max_goals + 1)]
    raw = {(home_goal, away_goal): home[home_goal] * away[away_goal] for home_goal in range(max_goals + 1) for away_goal in range(max_goals + 1)}
    represented = sum(raw.values())
    if represented <= 0.0 or not math.isfinite(represented):
        raise MarketAuditError("INVALID_SCORE_MATRIX_MASS")
    return {score: value / represented for score, value in raw.items()}, max(0.0, 1.0 - represented)


def _market_outcomes(lambda_home: float, lambda_away: float) -> dict[str, float]:
    home = [_poisson_pmf(lambda_home, goal) for goal in range(MARKET_MAX_GOALS + 1)]
    away = [_poisson_pmf(lambda_away, goal) for goal in range(MARKET_MAX_GOALS + 1)]
    cumulative_away: list[float] = []
    running = 0.0
    for probability in away:
        cumulative_away.append(running)
        running += probability
    home_win = sum(home[goal] * cumulative_away[goal] for goal in range(len(home)))
    draw = sum(home[goal] * away[goal] for goal in range(len(home)))
    away_win = max(0.0, 1.0 - home_win - draw)
    total = home_win + draw + away_win
    if total <= 0.0 or not math.isfinite(total):
        raise MarketAuditError("INVALID_MARKET_OUTCOMES")
    return {"home": home_win / total, "draw": draw / total, "away": away_win / total}


def _market_solve_total(line: float, target_over: float) -> float:
    if _valid_quarter_line(line) is None or not 0.0 < target_over < 1.0:
        raise MarketAuditError("INVALID_TOTAL_SOLVE_DOMAIN")

    def probability(lam: float) -> float:
        if abs(float(line) - 2.5) <= 1e-8:
            return 1.0 - sum(_poisson_pmf(lam, goal) for goal in range(3))
        matrix, _ = _raw_score_matrix(lam, 0.0, MARKET_MAX_GOALS)
        return sum(value for (home, away), value in matrix.items() if home + away > line)

    lower, upper = MARKET_OU_LOWER, MARKET_OU_UPPER
    if target_over < probability(lower) - 1e-10 or target_over > probability(upper) + 1e-10:
        raise MarketAuditError("TOTAL_SOLVE_NOT_IDENTIFIABLE")
    for _ in range(MARKET_OU_ITERATIONS):
        middle = (lower + upper) / 2.0
        if probability(middle) < target_over:
            lower = middle
        else:
            upper = middle
    return (lower + upper) / 2.0


def _market_solve_share(lambda_total: float, target: Mapping[str, float]) -> tuple[float, float]:
    target = {key: float(target[key]) for key in OUTCOMES}

    def loss(share: float) -> float:
        model = _market_outcomes(lambda_total * share, lambda_total * (1.0 - share))
        return sum((model[key] - target[key]) ** 2 for key in OUTCOMES)

    left, right = MARKET_SHARE_LOWER, MARKET_SHARE_UPPER
    golden = (math.sqrt(5.0) - 1.0) / 2.0
    x1 = right - golden * (right - left)
    x2 = left + golden * (right - left)
    f1, f2 = loss(x1), loss(x2)
    for _ in range(MARKET_SHARE_ITERATIONS):
        if f1 > f2:
            left, x1, f1 = x1, x2, f2
            x2 = left + golden * (right - left)
            f2 = loss(x2)
        else:
            right, x2, f2 = x2, x1, f1
            x1 = right - golden * (right - left)
            f1 = loss(x1)
    share = (left + right) / 2.0
    return lambda_total * share, lambda_total * (1.0 - share)


def _market_lambdas(one_x2: Mapping[str, Any], total_quotes: Mapping[str, Any]) -> dict[str, Any]:
    solved = []
    for quote in total_quotes["quotes"]:
        try:
            total_lambda = _market_solve_total(float(quote["line"]), float(quote["over"]))
        except MarketAuditError:
            continue
        solved.append({**quote, "lambda_total": total_lambda})
    if not solved:
        raise MarketAuditError("NO_VALID_TOTAL_LAMBDA")
    lambda_total = statistics.median(row["lambda_total"] for row in solved)
    lambda_home, lambda_away = _market_solve_share(lambda_total, one_x2["consensus"])
    return {
        "lambda_home": lambda_home,
        "lambda_away": lambda_away,
        "lambda_total": lambda_total,
        "one_x2_consensus": dict(one_x2["consensus"]),
        "one_x2_quote_count": int(one_x2["valid_count"]),
        "total_quote_count": len(solved),
        "total_lambda_quotes": [{"line": row["line"], "lambda_total": row["lambda_total"], "key": row["key"]} for row in solved],
        "contract": "accepted_same_time_market_lambda_v1",
    }


def _external_market_lambdas(row: Mapping[str, Any]) -> dict[str, Any] | None:
    def pick(*keys: str) -> float | None:
        for key in keys:
            value = _number(row.get(key))
            if value is not None and value > 1.0:
                return value
        return None

    one = [pick("AvgH", "B365H"), pick("AvgD", "B365D"), pick("AvgA", "B365A")]
    over = pick("Avg>2.5", "B365>2.5")
    under = pick("Avg<2.5", "B365<2.5")
    if any(value is None for value in one) or over is None or under is None:
        return None
    try:
        fair = _devig(one)
        target = dict(zip(OUTCOMES, fair))
        fair_over = _devig((over, under))[0]
        lambda_total = _market_solve_total(2.5, fair_over)
        lambda_home, lambda_away = _market_solve_share(lambda_total, target)
    except (MarketAuditError, ValueError):
        return None
    return {
        "lambda_home": lambda_home,
        "lambda_away": lambda_away,
        "lambda_total": lambda_total,
        "one_x2_consensus": target,
        "one_x2_quote_count": 1,
        "total_quote_count": 1,
        "contract": "football_data_external_1x2_avg_plus_ou_2_5_v1",
        "odds_semantics": "source_published_historical_odds; timing_not_equal_to_FBOS_horizon",
    }


# ---------------------------------------------------------------------------
# Train/live-symmetric feature construction
# ---------------------------------------------------------------------------


def _aggregate(records: Sequence[tuple[datetime, float, float, str]], venue: str | None = None) -> dict[str, Any] | None:
    selected = [record for record in records if venue is None or record[3] == venue][-ROLLING_WINDOW:]
    if not selected:
        return None
    return {
        "matches": len(selected),
        "goals_for": sum(record[1] for record in selected),
        "goals_against": sum(record[2] for record in selected),
    }


def _valid_block(value: Any) -> dict[str, float] | None:
    if not isinstance(value, Mapping):
        return None
    matches = _number(value.get("matches"))
    goals_for = _number(value.get("goals_for"))
    goals_against = _number(value.get("goals_against"))
    if matches is None or matches <= 0.0 or goals_for is None or goals_against is None:
        return None
    return {
        "matches": float(matches),
        "attack": float(goals_for) / matches,
        "defence": float(goals_against) / matches,
    }


def _build_features(form: Mapping[str, Any]) -> dict[str, Any] | None:
    home_overall = _valid_block(form.get("home_overall")) or _valid_block(form.get("home_home"))
    away_overall = _valid_block(form.get("away_overall")) or _valid_block(form.get("away_away"))
    if home_overall is None or away_overall is None or home_overall["matches"] < MIN_FORM_MATCHES or away_overall["matches"] < MIN_FORM_MATCHES:
        return None
    home_venue_raw = _valid_block(form.get("home_home"))
    away_venue_raw = _valid_block(form.get("away_away"))
    home_venue = home_venue_raw if home_venue_raw and home_venue_raw["matches"] >= MIN_FORM_MATCHES else home_overall
    away_venue = away_venue_raw if away_venue_raw and away_venue_raw["matches"] >= MIN_FORM_MATCHES else away_overall
    named = {
        "home_attack_venue_rate": home_venue["attack"],
        "home_defence_venue_rate": home_venue["defence"],
        "away_attack_venue_rate": away_venue["attack"],
        "away_defence_venue_rate": away_venue["defence"],
        "home_attack_overall_rate": home_overall["attack"],
        "home_defence_overall_rate": home_overall["defence"],
        "away_attack_overall_rate": away_overall["attack"],
        "away_defence_overall_rate": away_overall["defence"],
        "home_venue_matches_norm": min(home_venue["matches"], ROLLING_WINDOW) / ROLLING_WINDOW,
        "away_venue_matches_norm": min(away_venue["matches"], ROLLING_WINDOW) / ROLLING_WINDOW,
        "home_overall_matches_norm": min(home_overall["matches"], ROLLING_WINDOW) / ROLLING_WINDOW,
        "away_overall_matches_norm": min(away_overall["matches"], ROLLING_WINDOW) / ROLLING_WINDOW,
    }
    home_venue_rate = statistics.fmean((named["home_attack_venue_rate"], named["away_defence_venue_rate"]))
    away_venue_rate = statistics.fmean((named["away_attack_venue_rate"], named["home_defence_venue_rate"]))
    home_general_rate = statistics.fmean((named["home_attack_overall_rate"], named["away_defence_overall_rate"]))
    away_general_rate = statistics.fmean((named["away_attack_overall_rate"], named["home_defence_overall_rate"]))
    named["form_home"] = statistics.fmean((home_venue_rate, home_venue_rate, home_general_rate))
    named["form_away"] = statistics.fmean((away_venue_rate, away_venue_rate, away_general_rate))
    return {"names": named, "values": [named[name] for name in FEATURE_NAMES], "fallback_home_venue": home_venue_raw is None or home_venue_raw["matches"] < MIN_FORM_MATCHES, "fallback_away_venue": away_venue_raw is None or away_venue_raw["matches"] < MIN_FORM_MATCHES}


def _external_date(date_value: Any, time_value: Any) -> datetime | None:
    date_text = str(date_value or "").strip()
    time_text = str(time_value or "12:00").strip() or "12:00"
    for fmt in ("%d/%m/%Y %H:%M", "%d/%m/%y %H:%M", "%d/%m/%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(f"{date_text} {time_text}" if "%H" in fmt else date_text, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _clean_csv_key(value: Any) -> str:
    return str(value or "").replace("\ufeff", "").replace("ï»¿", "").strip()


def _load_external_rows(root: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    raw_matches: list[dict[str, Any]] = []
    file_manifest: list[dict[str, Any]] = []
    skipped = Counter()
    for path in sorted(Path(root).glob("*.csv")):
        stem = path.stem
        parts = stem.split("-", 1)
        if len(parts) != 2:
            continue
        season, league = parts
        file_manifest.append({"file": _repo_relative(path), "sha256": _sha256_file(path), "bytes": path.stat().st_size, "season": season, "league": league, "url": f"https://football-data.co.uk/mmz4281/{season}/{league}.csv"})
        try:
            handle = path.open("r", encoding="utf-8-sig", newline="")
        except OSError:
            skipped["file_open"] += 1
            continue
        with handle:
            reader = csv.DictReader(handle)
            for row_number, raw in enumerate(reader, start=2):
                row = {_clean_csv_key(key): value for key, value in raw.items()}
                kickoff = _external_date(row.get("Date"), row.get("Time"))
                home = str(row.get("HomeTeam") or "").strip()
                away = str(row.get("AwayTeam") or "").strip()
                home_goals = _number(row.get("FTHG"))
                away_goals = _number(row.get("FTAG"))
                if kickoff is None or not home or not away or home_goals is None or away_goals is None:
                    skipped["invalid_match_row"] += 1
                    continue
                raw_matches.append({"kickoff": kickoff, "home": home, "away": away, "home_goals": int(home_goals), "away_goals": int(away_goals), "league": league, "season": season, "file": path.name, "row_number": row_number, "odds": row})
    raw_matches.sort(key=lambda row: (row["kickoff"], row["file"], row["row_number"]))
    history: dict[tuple[str, str], list[tuple[datetime, float, float, str]]] = defaultdict(list)
    output: list[dict[str, Any]] = []
    for raw in raw_matches:
        league = raw["league"]
        home_history = history[(league, raw["home"])]
        away_history = history[(league, raw["away"])]
        form = {
            "home_overall": _aggregate(home_history),
            "home_home": _aggregate(home_history, "home"),
            "away_overall": _aggregate(away_history),
            "away_away": _aggregate(away_history, "away"),
        }
        features = _build_features(form)
        market = _external_market_lambdas(raw["odds"])
        if features is not None and market is not None and raw["kickoff"] < DEFAULT_EVAL_CUTOFF:
            row_key = f"{raw['file']}|{raw['row_number']}|{raw['kickoff'].isoformat()}|{raw['home']}|{raw['away']}"
            output.append({"row_id": _sha256_bytes(row_key.encode("utf-8")), "kickoff": raw["kickoff"], "home": raw["home"], "away": raw["away"], "league": league, "season": raw["season"], "features": features, "market": market, "home_goals": raw["home_goals"], "away_goals": raw["away_goals"], "source_file": raw["file"], "source_row": raw["row_number"]})
        history[(league, raw["home"])].append((raw["kickoff"], float(raw["home_goals"]), float(raw["away_goals"]), "home"))
        history[(league, raw["away"])].append((raw["kickoff"], float(raw["away_goals"]), float(raw["home_goals"]), "away"))
    return output, {"source": EXTERNAL_SOURCE, "files": file_manifest, "raw_match_rows": len(raw_matches), "eligible_rows": len(output), "skipped": dict(sorted(skipped.items())), "odds_semantics": "Avg 1X2 plus Avg O/U2.5 where available, B365 fallback; source timing is preserved as historical timing and is not relabeled as an FBOS horizon.", "training_cutoff": DEFAULT_EVAL_CUTOFF.isoformat()}


# ---------------------------------------------------------------------------
# Deterministic Poisson gradient-boosted stump backend
# ---------------------------------------------------------------------------


class PoissonStumpBooster:
    def __init__(self, feature_names: Sequence[str]) -> None:
        self.feature_names = list(feature_names)
        self.trees: list[dict[str, Any]] = []
        self.best_iteration = 0
        self.validation_nll = None

    @staticmethod
    def _tree_value(tree: Mapping[str, Any], features: Sequence[float]) -> float:
        feature = tree.get("feature")
        if feature is None:
            return float(tree["value"])
        return float(tree["left"] if float(features[int(feature)]) <= float(tree["threshold"]) else tree["right"])

    def correction(self, features: Sequence[float]) -> float:
        return sum(BOOSTER_LEARNING_RATE * self._tree_value(tree, features) for tree in self.trees)

    def predict_lambda(self, features: Sequence[float], offset: float) -> float:
        return _clamp(_safe_exp(float(offset) + self.correction(features)), OUTPUT_LAMBDA_MIN, OUTPUT_LAMBDA_MAX)

    @staticmethod
    def _threshold_positions(values: Sequence[float]) -> set[int]:
        n = len(values)
        if n < 2:
            return set()
        return {max(1, min(n - 1, int(round(n * step / (BOOSTER_MAX_THRESHOLDS + 1))))) for step in range(1, BOOSTER_MAX_THRESHOLDS + 1)}

    def fit(self, features: Sequence[Sequence[float]], targets: Sequence[float], offsets: Sequence[float], weights: Sequence[float], validation: tuple[Sequence[Sequence[float]], Sequence[float], Sequence[float]] | None = None) -> "PoissonStumpBooster":
        n = len(features)
        if not (n and len(targets) == n and len(offsets) == n and len(weights) == n):
            raise TrainingAuthorityBlocked("invalid_booster_training_contract")
        corrections = [0.0] * n
        best_trees: list[dict[str, Any]] = []
        best_score = float("inf")
        no_improve = 0
        for _iteration in range(BOOSTER_ESTIMATORS):
            gradients: list[float] = []
            hessians: list[float] = []
            for index in range(n):
                lam = _clamp(_safe_exp(float(offsets[index]) + corrections[index]), OUTPUT_LAMBDA_MIN, OUTPUT_LAMBDA_MAX)
                weight = float(weights[index])
                gradients.append((lam - float(targets[index])) * weight)
                hessians.append(max(lam * weight, 1e-9))
            total_gradient = sum(gradients)
            total_hessian = sum(hessians)
            total_gain = total_gradient * total_gradient / (total_hessian + BOOSTER_L2)
            best: tuple[float, int | None, float | None, float, float] | None = None
            for feature_index in range(len(self.feature_names)):
                order = sorted(range(n), key=lambda index: (float(features[index][feature_index]), index))
                positions = self._threshold_positions(order)
                left_gradient = 0.0
                left_hessian = 0.0
                left_count = 0
                for position, index in enumerate(order[:-1], start=1):
                    left_gradient += gradients[index]
                    left_hessian += hessians[index]
                    left_count += 1
                    if position not in positions or float(features[index][feature_index]) == float(features[order[position]][feature_index]):
                        continue
                    right_count = n - left_count
                    if left_count < BOOSTER_MIN_SAMPLES_LEAF or right_count < BOOSTER_MIN_SAMPLES_LEAF:
                        continue
                    right_gradient = total_gradient - left_gradient
                    right_hessian = total_hessian - left_hessian
                    gain = left_gradient * left_gradient / (left_hessian + BOOSTER_L2) + right_gradient * right_gradient / (right_hessian + BOOSTER_L2) - total_gain
                    threshold = (float(features[index][feature_index]) + float(features[order[position]][feature_index])) / 2.0
                    candidate = (gain, feature_index, threshold, -left_gradient / (left_hessian + BOOSTER_L2), -right_gradient / (right_hessian + BOOSTER_L2))
                    if best is None or candidate[0] > best[0] + 1e-12:
                        best = candidate
            if best is None or best[0] <= 0.0:
                root = _clamp(-total_gradient / (total_hessian + BOOSTER_L2), -BOOSTER_MAX_LEAF_VALUE, BOOSTER_MAX_LEAF_VALUE)
                tree = {"feature": None, "value": root}
                for index in range(n):
                    corrections[index] += BOOSTER_LEARNING_RATE * root
            else:
                _, feature_index, threshold, left_value, right_value = best
                left_value = _clamp(left_value, -BOOSTER_MAX_LEAF_VALUE, BOOSTER_MAX_LEAF_VALUE)
                right_value = _clamp(right_value, -BOOSTER_MAX_LEAF_VALUE, BOOSTER_MAX_LEAF_VALUE)
                tree = {"feature": feature_index, "threshold": threshold, "left": left_value, "right": right_value}
                for index in range(n):
                    corrections[index] += BOOSTER_LEARNING_RATE * (left_value if float(features[index][feature_index]) <= threshold else right_value)
            self.trees.append(tree)
            if validation is None:
                continue
            validation_features, validation_targets, validation_offsets = validation
            score = _poisson_nll_values(self, validation_features, validation_targets, validation_offsets)
            if score < best_score - 1e-9:
                best_score = score
                best_trees = list(self.trees)
                no_improve = 0
            else:
                no_improve += 1
                if no_improve >= BOOSTER_EARLY_STOPPING_ROUNDS:
                    break
        if validation is not None and best_trees:
            self.trees = best_trees
            self.best_iteration = len(best_trees)
            self.validation_nll = best_score
        else:
            self.best_iteration = len(self.trees)
        return self

    def to_dict(self) -> dict[str, Any]:
        return {"backend": MODEL_BACKEND, "feature_names": self.feature_names, "trees": self.trees, "best_iteration": self.best_iteration, "validation_nll": self.validation_nll, "hyperparameters": {"estimators": BOOSTER_ESTIMATORS, "learning_rate": BOOSTER_LEARNING_RATE, "l2": BOOSTER_L2, "min_samples_leaf": BOOSTER_MIN_SAMPLES_LEAF, "max_leaf_value": BOOSTER_MAX_LEAF_VALUE, "early_stopping_rounds": BOOSTER_EARLY_STOPPING_ROUNDS}}


def _poisson_nll_values(model: PoissonStumpBooster, features: Sequence[Sequence[float]], targets: Sequence[float], offsets: Sequence[float]) -> float:
    if not features:
        return float("nan")
    values = []
    for feature, target, offset in zip(features, targets, offsets):
        lam = model.predict_lambda(feature, offset)
        values.append(lam - float(target) * math.log(lam) + math.lgamma(float(target) + 1.0))
    return statistics.fmean(values)


def _fit_models(rows: Sequence[Mapping[str, Any]]) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    count = len(rows)
    train_end = max(1, int(count * TRAIN_FRACTION))
    validation_end = max(train_end + 1, int(count * (TRAIN_FRACTION + VALIDATION_FRACTION)))
    validation_end = min(validation_end, count - 1)
    train_rows = list(rows[:train_end])
    validation_rows = list(rows[train_end:validation_end])
    test_rows = list(rows[validation_end:])
    if not train_rows or not validation_rows or not test_rows:
        raise TrainingAuthorityBlocked("chronological_split_empty")
    latest_train = train_rows[-1]["kickoff"]
    weights = [math.exp(-max(0.0, (latest_train - row["kickoff"]).total_seconds() / 86400.0) / TIME_DECAY_HALF_LIFE_DAYS) for row in train_rows]
    x_train = [row["features"]["values"] for row in train_rows]
    x_validation = [row["features"]["values"] for row in validation_rows]
    x_test = [row["features"]["values"] for row in test_rows]
    home_targets = [float(row["home_goals"]) for row in train_rows]
    away_targets = [float(row["away_goals"]) for row in train_rows]
    home_offsets = [math.log(float(row["market"]["lambda_home"])) for row in train_rows]
    away_offsets = [math.log(float(row["market"]["lambda_away"])) for row in train_rows]
    validation_home_offsets = [math.log(float(row["market"]["lambda_home"])) for row in validation_rows]
    validation_away_offsets = [math.log(float(row["market"]["lambda_away"])) for row in validation_rows]
    home_model = PoissonStumpBooster(FEATURE_NAMES).fit(x_train, home_targets, home_offsets, weights, (x_validation, [float(row["home_goals"]) for row in validation_rows], validation_home_offsets))
    away_model = PoissonStumpBooster(FEATURE_NAMES).fit(x_train, away_targets, away_offsets, weights, (x_validation, [float(row["away_goals"]) for row in validation_rows], validation_away_offsets))
    artifact = {
        "model_family": MODEL_FAMILY,
        "backend": MODEL_BACKEND,
        "feature_schema": FEATURE_SCHEMA,
        "feature_schema_definition": FEATURE_SCHEMA_DEFINITION,
        "feature_names": list(FEATURE_NAMES),
        "market_offset": {"home": "log(lambda_market_home)", "away": "log(lambda_market_away)", "contract": "accepted_same_time_market_lambda_v1"},
        "score_distribution": {"family": "independent_poisson", "rho": 0.0, "max_goals": SCORE_MAX_GOALS, "tail_semantics": "finite_0_to_12_grid_renormalized_with_omitted_poisson_tail_recorded"},
        "training": {"authority": TRAINING_AUTHORITY, "source": EXTERNAL_SOURCE, "chronological_split": {"train_fraction": TRAIN_FRACTION, "validation_fraction": VALIDATION_FRACTION, "test_fraction": 1.0 - TRAIN_FRACTION - VALIDATION_FRACTION}, "time_decay_half_life_days": TIME_DECAY_HALF_LIFE_DAYS, "train_n": len(train_rows), "validation_n": len(validation_rows), "test_n": len(test_rows), "train_first": train_rows[0]["kickoff"].isoformat(), "train_last": train_rows[-1]["kickoff"].isoformat(), "validation_first": validation_rows[0]["kickoff"].isoformat(), "validation_last": validation_rows[-1]["kickoff"].isoformat(), "test_first": test_rows[0]["kickoff"].isoformat(), "test_last": test_rows[-1]["kickoff"].isoformat(), "fixed_107_outcomes_used": False},
        "home_model": home_model.to_dict(),
        "away_model": away_model.to_dict(),
    }
    return artifact, train_rows, validation_rows, test_rows


def _load_model(artifact: Mapping[str, Any]) -> tuple[PoissonStumpBooster, PoissonStumpBooster]:
    def from_dict(value: Mapping[str, Any]) -> PoissonStumpBooster:
        model = PoissonStumpBooster(value.get("feature_names") or FEATURE_NAMES)
        model.trees = [dict(tree) for tree in value.get("trees") or []]
        model.best_iteration = int(value.get("best_iteration") or len(model.trees))
        model.validation_nll = value.get("validation_nll")
        return model
    return from_dict(artifact["home_model"]), from_dict(artifact["away_model"])


# ---------------------------------------------------------------------------
# Unified score matrix and controls
# ---------------------------------------------------------------------------


def _score_output(lambda_home: float, lambda_away: float) -> dict[str, Any]:
    lambda_home = _clamp(lambda_home, OUTPUT_LAMBDA_MIN, OUTPUT_LAMBDA_MAX)
    lambda_away = _clamp(lambda_away, OUTPUT_LAMBDA_MIN, OUTPUT_LAMBDA_MAX)
    matrix = dixon_coles_score_matrix({"lambda_home": lambda_home, "lambda_away": lambda_away, "rho": 0.0}, max_goals=SCORE_MAX_GOALS)
    raw_matrix, raw_mass = _raw_score_matrix(lambda_home, lambda_away, SCORE_MAX_GOALS)
    rows = [{"rank": rank, "score": _score_text(score), "home_goals": score[0], "away_goals": score[1], "probability": round(float(probability), 12)} for rank, (score, probability) in enumerate(sorted(matrix.items(), key=lambda item: (-item[1], item[0][0], item[0][1])), start=1)]
    probabilities = {outcome: 0.0 for outcome in OUTCOMES}
    total_distribution: dict[str, float] = defaultdict(float)
    btts_yes = 0.0
    for (home, away), probability in matrix.items():
        probabilities[_actual_outcome((home, away))] += probability
        total_distribution[str(home + away)] += probability
        if home > 0 and away > 0:
            btts_yes += probability

    handicap: dict[str, Any] = {}
    for line in (-1.0, -0.5, 0.0, 0.5, 1.0):
        parts = split_quarter_line(line)
        home_win = home_push = home_loss = 0.0
        away_win = away_push = away_loss = 0.0
        for (home, away), probability in matrix.items():
            home_units = []
            away_units = []
            for component in parts:
                home_delta = home - away + component
                away_delta = -home_delta
                home_units.append(1.0 if home_delta > 0 else 0.0 if home_delta == 0 else -1.0)
                away_units.append(1.0 if away_delta > 0 else 0.0 if away_delta == 0 else -1.0)
            home_average = sum(home_units) / len(home_units)
            away_average = sum(away_units) / len(away_units)
            home_win += probability * (1.0 if home_average > 0 else 0.0)
            home_push += probability * (1.0 if home_average == 0 else 0.0)
            home_loss += probability * (1.0 if home_average < 0 else 0.0)
            away_win += probability * (1.0 if away_average > 0 else 0.0)
            away_push += probability * (1.0 if away_average == 0 else 0.0)
            away_loss += probability * (1.0 if away_average < 0 else 0.0)
        handicap[str(line)] = {"home": {"win": home_win, "push": home_push, "loss": home_loss}, "away": {"win": away_win, "push": away_push, "loss": away_loss}}
    return {
        "lambda_home": round(lambda_home, 12),
        "lambda_away": round(lambda_away, 12),
        "lambda_total": round(lambda_home + lambda_away, 12),
        "rho": 0.0,
        "score_matrix": rows,
        "score_matrix_tail_probability": max(0.0, 1.0 - raw_mass),
        "score_matrix_normalization": {"finite_grid_raw_mass": 1.0 - max(0.0, raw_mass), "represented_probability_sum": sum(matrix.values()), "max_goals": SCORE_MAX_GOALS},
        "exact_top1": rows[0]["score"],
        "exact_top3": [row["score"] for row in rows[:3]],
        "exact_top5": [row["score"] for row in rows[:5]],
        "derived_markets": {
            "1x2": {key: round(value, 12) for key, value in probabilities.items()},
            "totals": {"exact": {key: round(value, 12) for key, value in sorted(total_distribution.items(), key=lambda item: int(item[0]))}, "over_2_5": round(sum(value for (home, away), value in matrix.items() if home + away > 2), 12), "under_2_5": round(sum(value for (home, away), value in matrix.items() if home + away <= 2), 12), "tail_ge_4": round(sum(value for (home, away), value in matrix.items() if home + away >= 4), 12), "tail_ge_5": round(sum(value for (home, away), value in matrix.items() if home + away >= 5), 12), "tail_ge_6": round(sum(value for (home, away), value in matrix.items() if home + away >= 6), 12), "out_of_support_tail": max(0.0, 1.0 - raw_mass)},
            "btts": {"yes": round(btts_yes, 12), "no": round(1.0 - btts_yes, 12)},
            "handicap": handicap,
        },
    }


def _control_lambdas(market: Mapping[str, Any], features: Mapping[str, Any]) -> dict[str, dict[str, float]]:
    market_home = float(market["lambda_home"])
    market_away = float(market["lambda_away"])
    market_total = market_home + market_away
    market_share = market_home / market_total
    form_home = float(features["names"]["form_home"])
    form_away = float(features["names"]["form_away"])
    form_total = _clamp(form_home + form_away, 1.2, 4.2)
    form_share = _clamp(form_home / max(form_total, MARKET_EPSILON), 0.01, 0.99)
    champion_total = _clamp(0.60 * form_total + 0.40 * market_total, 1.0, 4.8)
    champion_share = 0.65 * form_share + 0.35 * market_share
    c_total = champion_total
    c_share = market_share
    return {
        "market": {"lambda_home": market_home, "lambda_away": market_away},
        "champion": {"lambda_home": champion_total * champion_share, "lambda_away": champion_total * (1.0 - champion_share)},
        "challenger_c": {"lambda_home": c_total * c_share, "lambda_away": c_total * (1.0 - c_share)},
    }


def _model_prediction(row: Mapping[str, Any], home_model: PoissonStumpBooster, away_model: PoissonStumpBooster) -> dict[str, Any]:
    features = row["features"]
    market = row["market"]
    feature_values = features["values"]
    market_home = float(market["lambda_home"])
    market_away = float(market["lambda_away"])
    home_offset = math.log(market_home)
    away_offset = math.log(market_away)
    lambda_home = home_model.predict_lambda(feature_values, home_offset)
    lambda_away = away_model.predict_lambda(feature_values, away_offset)
    controls = _control_lambdas(market, features)
    return {
        "model": _score_output(lambda_home, lambda_away),
        "market": _score_output(controls["market"]["lambda_home"], controls["market"]["lambda_away"]),
        "champion": _score_output(controls["champion"]["lambda_home"], controls["champion"]["lambda_away"]),
        "challenger_c": _score_output(controls["challenger_c"]["lambda_home"], controls["challenger_c"]["lambda_away"]),
        "offsets": {"base_margin_home": home_offset, "base_margin_away": away_offset, "market_lambda_home": market_home, "market_lambda_away": market_away, "correction_home": home_model.correction(feature_values), "correction_away": away_model.correction(feature_values)},
    }


def _metric_summary(rows: Sequence[Mapping[str, Any]], home_model: PoissonStumpBooster, away_model: PoissonStumpBooster, variant: str = "model") -> dict[str, Any]:
    records = []
    for row in rows:
        prediction = _model_prediction(row, home_model, away_model)
        actual = (int(row["home_goals"]), int(row["away_goals"]))
        model_matrix = {(cell["home_goals"], cell["away_goals"]): float(cell["probability"]) for cell in prediction[variant]["score_matrix"]}
        ranked = sorted(model_matrix.items(), key=lambda item: (-item[1], item[0][0], item[0][1]))
        actual_probability = max(MARKET_EPSILON, model_matrix.get(actual, MARKET_EPSILON))
        model_one_x2 = prediction[variant]["derived_markets"]["1x2"]
        target = _actual_outcome(actual)
        brier_1x2 = sum((float(model_one_x2[key]) - (1.0 if key == target else 0.0)) ** 2 for key in OUTCOMES)
        model_total = prediction[variant]["derived_markets"]["totals"]
        total_actual_over = actual[0] + actual[1] > 2
        brier_total = (float(model_total["over_2_5"]) - float(total_actual_over)) ** 2
        btts_actual = actual[0] > 0 and actual[1] > 0
        brier_btts = (float(prediction[variant]["derived_markets"]["btts"]["yes"]) - float(btts_actual)) ** 2
        records.append({"exact_nll": -math.log(actual_probability), "actual_probability": actual_probability, "top1": actual == ranked[0][0], "top3": actual in {score for score, _ in ranked[:3]}, "top5": actual in {score for score, _ in ranked[:5]}, "actual_one_one": actual == (1, 1), "top_score_one_one": ranked[0][0] == (1, 1), "home_actual": actual[0], "away_actual": actual[1], "total_actual": actual[0] + actual[1], "home_lambda": prediction[variant]["lambda_home"], "away_lambda": prediction[variant]["lambda_away"], "total_lambda": prediction[variant]["lambda_total"], "brier_1x2": brier_1x2, "brier_total_over_2_5": brier_total, "brier_btts": brier_btts})
    if not records:
        return {"n": 0}

    def rate(key: str) -> float:
        return statistics.fmean(float(record[key]) for record in records)

    def calibration(actual_key: str, lambda_key: str) -> dict[str, float]:
        actual = [float(record[actual_key]) for record in records]
        predicted = [float(record[lambda_key]) for record in records]
        return {"observed_mean": statistics.fmean(actual), "predicted_mean": statistics.fmean(predicted), "bias_observed_minus_predicted": statistics.fmean(a - p for a, p in zip(actual, predicted)), "mae": statistics.fmean(abs(a - p) for a, p in zip(actual, predicted))}

    return {
        "n": len(records),
        "exact_nll": rate("exact_nll"),
        "mean_actual_score_probability": rate("actual_probability"),
        "exact_top1": rate("top1"),
        "exact_top3": rate("top3"),
        "exact_top5": rate("top5"),
        "one_one_actual_rate": rate("actual_one_one"),
        "one_one_top_score_share": rate("top_score_one_one"),
        "lambda_calibration": {"home": calibration("home_actual", "home_lambda"), "away": calibration("away_actual", "away_lambda"), "total": calibration("total_actual", "total_lambda")},
        "1x2_brier": rate("brier_1x2"),
        "total_over_2_5_brier": rate("brier_total_over_2_5"),
        "btts_brier": rate("brier_btts"),
    }


# ---------------------------------------------------------------------------
# Frozen prematch shadow integration
# ---------------------------------------------------------------------------


def _load_legal_snapshot(pair: Mapping[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    reference = str(pair.get("input_snapshot_ref") or "")
    path = Path(reference)
    if not path.is_absolute():
        path = ROOT / path
    if not path.is_file():
        return None, "missing_input_snapshot"
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None, "invalid_input_snapshot"
    cutoff = _parse_datetime(pair.get("source_cutoff"))
    kickoff = _parse_datetime(pair.get("kickoff_at"))
    if cutoff is None or kickoff is None or cutoff >= kickoff:
        return None, "unsafe_pair_chronology"
    sources = ((document.get("input") or {}).get("source_snapshots") or {})
    candidates = []
    for source_name, source in sources.items():
        for snapshot in (source.get("snapshots") or []) if isinstance(source, Mapping) else []:
            captured = _parse_datetime(snapshot.get("fetched_at") or snapshot.get("captured_at")) if isinstance(snapshot, Mapping) else None
            if captured is not None and captured <= cutoff and captured < kickoff:
                candidates.append((captured, str(source_name), dict(snapshot)))
    if not candidates:
        return None, "no_legal_prematch_snapshot"
    _, source_name, snapshot = max(candidates, key=lambda item: (item[0], item[1]))
    snapshot["_source_name"] = source_name
    return snapshot, None


def _live_features(snapshot: Mapping[str, Any], input_document: Mapping[str, Any]) -> dict[str, Any] | None:
    shuju = snapshot.get("shuju") or {}
    form = shuju.get("recent_form") or ((input_document.get("prematch_fundamentals") or {}).get("recent_form") or {})
    return _build_features(form)


def _build_live_shadow_rows(pair_root: Path, home_model: PoissonStumpBooster, away_model: PoissonStumpBooster, model_digest: str, prospective_after: datetime) -> tuple[list[dict[str, Any]], dict[str, int]]:
    pairs = load_persisted_pairs(pair_root)
    output = []
    skipped = Counter()
    for pair in pairs:
        kickoff = _parse_datetime(pair.get("kickoff_at"))
        if pair.get("pair_status") != "PAIRED" or pair.get("post_match_input_used_for_generation") is not False:
            skipped["pair_contract"] += 1
            continue
        if kickoff is None or kickoff <= prospective_after:
            skipped["not_future_prospective"] += 1
            continue
        snapshot, reason = _load_legal_snapshot(pair)
        if snapshot is None:
            skipped[reason or "snapshot"] += 1
            continue
        reference = Path(str(pair.get("input_snapshot_ref") or ""))
        if not reference.is_absolute():
            reference = ROOT / reference
        try:
            document = json.loads(reference.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            skipped["invalid_input_document"] += 1
            continue
        features = _live_features(snapshot, document)
        if features is None:
            skipped["missing_reproducible_features"] += 1
            continue
        try:
            one_x2, total = _live_market_quotes(snapshot)
            market = _market_lambdas(one_x2, total)
        except MarketAuditError as error:
            skipped[str(error)] += 1
            continue
        base_row = {"features": features, "market": market}
        prediction = _model_prediction(base_row, home_model, away_model)
        prediction_id = "SFGI-" + _sha256_bytes((str(pair.get("pair_id")) + "|" + model_digest).encode("utf-8"))[:24]
        shadow_record = {"pair_id": pair.get("pair_id"), "match_id": pair.get("match_id"), "match_key": pair.get("match_key"), "kickoff_at": pair.get("kickoff_at"), "source_cutoff": pair.get("source_cutoff"), "input_snapshot_ref": pair.get("input_snapshot_ref"), "frozen_input_digest": pair.get("frozen_input_digest"), "source_snapshot": snapshot.get("_source_name"), "prediction_id": prediction_id, "model_family": MODEL_FAMILY, "model_version": f"{MODEL_FAMILY}:{model_digest[:12]}", "model_digest": model_digest, "feature_schema": FEATURE_SCHEMA, "feature_values": features["names"], "feature_missingness": {"home_venue_fallback_to_overall": features["fallback_home_venue"], "away_venue_fallback_to_overall": features["fallback_away_venue"]}, "market_baseline": market, "prediction": prediction["model"], "controls": {"market": prediction["market"], "champion": prediction["champion"], "challenger_c": prediction["challenger_c"]}, "offset_and_correction": prediction["offsets"], "namespace": "solution_first_goal_intensity_shadow_1", "production_enabled": False, "user_visible": False, "post_match_input_used_for_generation": False, "settlement_adapter": {"actual_score_source": "existing_verified_postmatch_result", "uses_frozen_score_matrix": True, "derived_markets_from_same_matrix": True}}
        shadow_record["prediction_sha256"] = _sha256_bytes(_canonical_json(shadow_record).encode("utf-8"))
        output.append(shadow_record)
    return output, dict(sorted(skipped.items()))


def _native_history_audit(pair_root: Path) -> dict[str, Any]:
    pairs = load_persisted_pairs(pair_root)
    catalog, discovery = discover_verified_results(ROOT / "data" / "postmatch_automation" / "results")
    result_map, matching = build_identity_safe_result_map(pairs, catalog)
    legal = 0
    for pair in pairs:
        kickoff = _parse_datetime(pair.get("kickoff_at"))
        if kickoff is None or kickoff >= DEFAULT_EVAL_CUTOFF or str(pair.get("match_id") or "") not in result_map:
            continue
        snapshot, _ = _load_legal_snapshot(pair)
        if snapshot is None:
            continue
        reference = Path(str(pair.get("input_snapshot_ref") or ""))
        if not reference.is_absolute():
            reference = ROOT / reference
        try:
            document = json.loads(reference.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if _live_features(snapshot, document) is None:
            continue
        try:
            one_x2, total = _live_market_quotes(snapshot)
            _market_lambdas(one_x2, total)
        except MarketAuditError:
            continue
        if _actual_for_pair(pair, result_map) is not None:
            legal += 1
    return {"eligible_count": legal, "evaluation_cutoff": DEFAULT_EVAL_CUTOFF.isoformat(), "source_catalog": discovery, "result_matching": matching, "decision": "NATIVE_HISTORY_INSUFFICIENT_USE_EXTERNAL" if legal < MIN_EXTERNAL_ROWS else "NATIVE_HISTORY_AVAILABLE"}


def _build_report(summary: Mapping[str, Any]) -> str:
    metrics = summary.get("test_metrics") or {}
    controls = summary.get("control_test_metrics") or {}
    calibration = metrics.get("lambda_calibration") or {}
    return "\n".join([
        f"# {MILESTONE}",
        "",
        f"- Decision: `{summary.get('decision')}`",
        f"- Training authority: `{summary.get('training_authority')}`",
        f"- Model family: `{summary.get('model_family')}`; backend `{summary.get('backend')}`",
        f"- Feature schema: `{summary.get('feature_schema')}`",
        f"- Train/validation/test: `{summary.get('training_n')}/{summary.get('validation_n')}/{summary.get('test_n')}`",
        f"- Shadow output rows: `{summary.get('shadow_output_count')}`",
        "",
        "## External test sanity evidence",
        f"- Exact NLL `{metrics.get('exact_nll')}`; Top1 `{metrics.get('exact_top1')}`; Top3 `{metrics.get('exact_top3')}`; Top5 `{metrics.get('exact_top5')}`",
        f"- 1-1 actual rate `{metrics.get('one_one_actual_rate')}`; 1-1 top-score share `{metrics.get('one_one_top_score_share')}`",
        f"- Lambda calibration: `{json.dumps(calibration, sort_keys=True)}`",
        f"- 1X2 Brier `{metrics.get('1x2_brier')}`; O/U2.5 Brier `{metrics.get('total_over_2_5_brier')}`; BTTS Brier `{metrics.get('btts_brier')}`",
        f"- Controls retained — Market NLL `{(controls.get('market') or {}).get('exact_nll')}`, Champion NLL `{(controls.get('champion') or {}).get('exact_nll')}`, C NLL `{(controls.get('challenger_c') or {}).get('exact_nll')}`",
        "",
        "## Integrity",
        "- External odds are retained with source timing semantics and labelled HORIZON_TRANSFER; no closing odds are relabeled as FBOS earlier horizons.",
        "- Fixed 107 outcomes are excluded from fitting, validation selection, and test construction.",
        "- Champion serving, C, selector, UI and history are unchanged; the namespace is shadow-only and not user-visible.",
        "- No anti-1-1 rule, manual lambda scale, result-aware score selection, Dixon-Coles/NB/CMP expansion or automatic promotion.",
    ]) + "\n"


def run_shadow(*, external_root: Path = EXTERNAL_ROOT, pair_root: Path = DEFAULT_PAIR_ROOT, prospective_after: datetime | None = DEFAULT_PROSPECTIVE_AFTER) -> dict[str, Any]:
    native_audit = _native_history_audit(pair_root)
    if native_audit["eligible_count"] >= MIN_EXTERNAL_ROWS:
        raise TrainingAuthorityBlocked("native_history_route_not_implemented_for_this_milestone")
    external_rows, external_manifest = _load_external_rows(external_root)
    if len(external_rows) < MIN_EXTERNAL_ROWS:
        raise TrainingAuthorityBlocked(f"external_training_rows_below_minimum:{len(external_rows)}")
    artifact, train_rows, validation_rows, test_rows = _fit_models(external_rows)
    model_content = _canonical_json(artifact).encode("utf-8")
    model_digest = _sha256_bytes(model_content)
    home_model, away_model = _load_model(artifact)
    test_metrics = _metric_summary(test_rows, home_model, away_model, "model")
    validation_metrics = _metric_summary(validation_rows, home_model, away_model, "model")
    control_test_metrics = {
        "market": _metric_summary(test_rows, home_model, away_model, "market"),
        "champion": _metric_summary(test_rows, home_model, away_model, "champion"),
        "challenger_c": _metric_summary(test_rows, home_model, away_model, "challenger_c"),
    }
    if prospective_after is None:
        prospective_after = datetime.now(timezone.utc)
    shadow_rows, shadow_skips = _build_live_shadow_rows(pair_root, home_model, away_model, model_digest, prospective_after)
    now = datetime.now(timezone.utc).isoformat()
    summary = {
        "schema_version": SCHEMA_VERSION,
        "milestone": MILESTONE,
        "decision": "SHADOW_CHALLENGER_WIRED" if shadow_rows else "FAIL_CLOSED",
        "reviewed_at": now,
        "training_authority": TRAINING_AUTHORITY,
        "native_history_audit": native_audit,
        "external_source_manifest": external_manifest,
        "training_n": len(train_rows),
        "validation_n": len(validation_rows),
        "test_n": len(test_rows),
        "model_family": MODEL_FAMILY,
        "backend": MODEL_BACKEND,
        "feature_schema": FEATURE_SCHEMA,
        "feature_schema_definition": FEATURE_SCHEMA_DEFINITION,
        "feature_names": list(FEATURE_NAMES),
        "market_offset": artifact["market_offset"],
        "model_digest": model_digest,
        "validation_metrics": validation_metrics,
        "test_metrics": test_metrics,
        "control_test_metrics": control_test_metrics,
        "shadow_output_count": len(shadow_rows),
        "shadow_output_skipped": shadow_skips,
        "fixed_107_outcomes_used_for_fit": False,
        "current_serving_changed": False,
        "controls_retained": ["Market", "Champion", "Challenger C"],
        "integrity": {
            "status": "PASS" if shadow_rows else "FAIL_CLOSED",
            "source": EXTERNAL_SOURCE,
            "same_time_market_lambda_for_live": True,
            "external_odds_horizon_transfer_only": True,
            "fixed_107_excluded": True,
            "result_leakage": False,
            "closing_odds_relabelled_as_FBOS_horizon": False,
            "manual_lambda_scaling": False,
            "anti_1_1": False,
            "result_aware_score_selection": False,
            "production_enabled": False,
            "user_visible": False,
            "champion_serving_changed": False,
            "history_rewritten": False,
            "automatic_promotion": False,
        },
        "source": {"external_root": _repo_relative(external_root), "pair_root": _repo_relative(pair_root), "shadow_namespace": "solution_first_goal_intensity_shadow_1"},
        "implementation_provenance": [
            {"source": "cnemri/world-cup-2026-predictor", "license": "MIT", "use": "separate home/away Poisson count-booster pattern only; no code, World-Cup features or hyperparameters copied"},
            {"source": "JetQiao/football-prediction-skill", "license": "MIT", "use": "event-time, reference/target/benchmark and fail-closed lifecycle pattern only; no code copied"},
            {"source": "eScored Engine 2.0", "license": "architecture evidence only", "use": "market-anchored intensity architecture; no proprietary code copied"},
        ],
    }
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    artifact["model_digest"] = model_digest
    _write_json(DEFAULT_MODEL, artifact)
    _write_json(DEFAULT_SHADOW_OUTPUT, {"schema_version": SCHEMA_VERSION, "milestone": MILESTONE, "namespace": "solution_first_goal_intensity_shadow_1", "model_family": MODEL_FAMILY, "model_digest": model_digest, "feature_schema": FEATURE_SCHEMA, "market_offset": artifact["market_offset"], "generated_at": now, "prospective_after": prospective_after.isoformat(), "row_count": len(shadow_rows), "rows": shadow_rows, "controls": ["market", "champion", "challenger_c"], "production_enabled": False, "user_visible": False})
    _write_json(DEFAULT_SUMMARY, summary)
    DEFAULT_REPORT.write_text(_build_report(summary), encoding="utf-8")
    return summary


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--external-root", type=Path, default=EXTERNAL_ROOT)
    parser.add_argument("--pair-root", type=Path, default=DEFAULT_PAIR_ROOT)
    parser.add_argument("--prospective-after", type=str, default=None, help="ISO timestamp; default is current UTC time")
    args = parser.parse_args(argv)
    prospective_after = _parse_datetime(args.prospective_after) if args.prospective_after else None
    try:
        summary = run_shadow(external_root=args.external_root, pair_root=args.pair_root, prospective_after=prospective_after)
    except TrainingAuthorityBlocked as error:
        summary = {"schema_version": SCHEMA_VERSION, "milestone": MILESTONE, "decision": "TRAINING_AUTHORITY_BLOCKED", "training_authority": TRAINING_AUTHORITY, "blocker": str(error), "current_serving_changed": False}
        _write_json(DEFAULT_SUMMARY, summary)
        print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
        return 2
    print(json.dumps({"decision": summary["decision"], "training_authority": summary["training_authority"], "training_n": summary["training_n"], "validation_n": summary["validation_n"], "test_n": summary["test_n"], "shadow_output_count": summary["shadow_output_count"], "model_digest": summary["model_digest"], "current_serving_changed": summary["current_serving_changed"]}, ensure_ascii=False, sort_keys=True))
    return 0 if summary["decision"] == "SHADOW_CHALLENGER_WIRED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
