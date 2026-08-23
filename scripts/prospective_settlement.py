"""Settle immutable predictions into the formal prospective ledger."""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Callable, Iterable

from prediction_exclusions import (
    DEFAULT_EXCLUSION_ROOT,
    excluded_prediction_ids,
    exclusion_for,
)
from postmatch_queue import parse_datetime
from postmatch_result import (
    RESULT_ROOT as POSTMATCH_RESULT_ROOT,
    fetch_espn_result,
    fetch_nowscore_result,
    resolve_nowscore_id,
    safe_key,
)


BASE_DIR = Path(__file__).resolve().parents[1]
PREDICTION_ROOT = BASE_DIR / "data" / "model_governance" / "predictions"
UNIVERSE_ROOT = BASE_DIR / "data" / "prediction_universe"
PROSPECTIVE_ROOT = BASE_DIR / "data" / "prospective"
LEDGER_NAME = "ledger.jsonl"
SUMMARY_NAME = "summary.json"
EXPLORATORY_NAME = "exploratory_settlements.jsonl"
SHANGHAI = timezone(timedelta(hours=8))
BASE_PREDICTION_POLICY = "base_prediction_minimum.v1"
EPSILON = 1e-15
FROZEN_STATUSES = {"formal", "frozen", "FROZEN"}


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _prediction_created_and_frozen(record: dict[str, Any]) -> bool:
    created = parse_datetime(record.get("prediction_created_at"))
    freeze = parse_datetime(record.get("freeze_created_at"))
    kickoff = parse_datetime(record.get("kickoff_at"))
    source = parse_datetime(record.get("source_cutoff_at"))
    return bool(
        source
        and created
        and freeze
        and kickoff
        and source < created <= freeze < kickoff
    )


def _report_type(record: dict[str, Any]) -> str:
    return str(
        record.get("report_type")
        or (record.get("analysis_output") or {}).get("report_type")
        or ""
    ).strip()


def is_formally_eligible(record: dict[str, Any]) -> bool:
    """Apply the frozen record's BASE or DEEP formal policy.

    BASE C-grade records are eligible only through their explicit minimum
    policy.  The generic A/B rule remains the DEEP rule.
    """
    if not isinstance(record, dict) or record.get("prediction_status") not in FROZEN_STATUSES:
        return False
    if record.get("model_role") != "champion":
        return False
    if record.get("prediction_variant") != "model_only":
        return False
    if record.get("manual_override") not in (False, None):
        return False
    if not record.get("model_input_snapshot_ref") or not record.get("input_sha256"):
        return False
    if not record.get("model_source_fingerprint"):
        return False
    identity = record.get("match_identity") or {}
    if not (record.get("match_key") or identity.get("match_key")):
        return False
    if not identity.get("home") or not identity.get("away"):
        return False
    if not record.get("kickoff_at"):
        return False
    if not _prediction_created_and_frozen(record):
        return False
    if record.get("critical_missing_fields") or record.get("missing_critical_fields"):
        return False

    if _report_type(record) == "base_prediction_minimal":
        return bool(
            record.get("formal_eligibility_policy") == BASE_PREDICTION_POLICY
            and record.get("formal_eligible") is True
            and record.get("model_formal_eligible") is True
            and record.get("base_input_quality") == "VERIFIED_MINIMUM"
            and _has_minimum_prediction_output(record)
        )

    return bool(
        record.get("formal_eligible") is True
        and record.get("model_formal_eligible") is True
        and str(record.get("data_grade") or "").upper() in {"A", "B"}
    )


def _score_pair(value: Any) -> tuple[int, int] | None:
    if isinstance(value, (tuple, list)) and len(value) == 2:
        left, right = value
    elif isinstance(value, dict):
        left, right = value.get("home_score"), value.get("away_score")
    else:
        text = str(value or "").strip()
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


def _outcome(home: int, away: int) -> str:
    if home > away:
        return "HOME"
    if home < away:
        return "AWAY"
    return "DRAW"


def normalize_result(result: dict[str, Any]) -> dict[str, Any]:
    """Normalize an existing postmatch artifact/provider result to 90m."""
    if not isinstance(result, dict):
        raise ValueError("result must be an object")
    status = str(result.get("status") or "").strip().lower()
    if status in {"live", "in_progress", "scheduled", "pending", "result_pending"}:
        raise ValueError("result is not final")
    if status and status not in {"result_verified", "verified", "reviewed"}:
        raise ValueError("result verification status is not final")
    scope = str(result.get("scope") or "regulation_90m_plus_stoppage").strip()
    if scope not in {"regulation_90m_plus_stoppage", "90m", "regulation_90m"}:
        raise ValueError("result scope is not regulation-only")
    score = result.get("score_90m") or result.get("result_90m")
    if score is None:
        score = (result.get("home_score_90m"), result.get("away_score_90m"))
    if score in (None, (None, None), [None, None]):
        score = (result.get("home_score"), result.get("away_score"))
    pair = _score_pair(score)
    if pair is None:
        raise ValueError("result has no valid 90-minute score")
    home, away = pair
    return {
        **result,
        "home_score_90m": home,
        "away_score_90m": away,
        "actual_outcome": _outcome(home, away),
        "total_goals": home + away,
        "btts_actual": home > 0 and away > 0,
        "scope": scope,
        "result_verified_at": result.get("result_verified_at") or result.get("verified_at"),
    }


def _is_verified_result_artifact(result: dict[str, Any]) -> bool:
    """Require a provider-verified final artifact before settlement."""
    if not isinstance(result, dict):
        return False
    status = str(result.get("status") or "").strip().lower()
    if status in {"live", "in_progress", "scheduled", "pending", "result_pending"}:
        return False
    if status and status not in {"result_verified", "verified", "reviewed"}:
        return False
    scope = str(result.get("scope") or "").strip()
    if scope not in {"regulation_90m_plus_stoppage", "90m", "regulation_90m"}:
        return False
    verified_at = result.get("result_verified_at") or result.get("verified_at")
    if not verified_at:
        return False
    return any(
        result.get(field) not in (None, "")
        for field in ("score_90m", "result_90m", "home_score_90m", "home_score")
    )


def _probabilities(record: dict[str, Any]) -> dict[str, float] | None:
    output = record.get("prediction_output") or {}
    values = record.get("probabilities") or output.get("probabilities")
    if not isinstance(values, dict):
        return None
    result = {key: _number(values.get(key)) for key in ("home", "draw", "away")}
    if any(value is None or value < 0 for value in result.values()):
        return None
    return {key: float(value) for key, value in result.items()}


def _score_rows(record: dict[str, Any]) -> list[dict[str, Any]]:
    output = record.get("prediction_output") or {}
    for candidate in (
        record.get("score_distribution"),
        record.get("score_matrix"),
        record.get("score_probabilities"),
        record.get("top_scores"),
        output.get("score_matrix"),
        output.get("score_probabilities"),
    ):
        if not isinstance(candidate, list):
            continue
        rows = [
            row for row in candidate
            if isinstance(row, dict) and _number(row.get("probability")) is not None
        ]
        if rows:
            if any(row.get("rank") is not None for row in rows):
                return sorted(rows, key=lambda row: (int(row.get("rank") or 999999), str(row.get("score") or "")))
            return sorted(rows, key=lambda row: (-float(row["probability"]), str(row.get("score") or "")))
    return []


def _btts(record: dict[str, Any]) -> dict[str, float] | None:
    output = record.get("prediction_output") or {}
    value = record.get("btts") or output.get("btts")
    if not isinstance(value, dict):
        return None
    yes, no = _number(value.get("yes")), _number(value.get("no"))
    if yes is None or no is None:
        return None
    return {"yes": yes, "no": no}


def _market_baseline(record: dict[str, Any]) -> dict[str, float] | None:
    value = record.get("market_only_baseline")
    if not isinstance(value, dict):
        return None
    result = {key: _number(value.get(key)) for key in ("home", "draw", "away")}
    if any(value is None or value < 0 for value in result.values()):
        return None
    return {key: float(value) for key, value in result.items()}


def _has_minimum_prediction_output(record: dict[str, Any]) -> bool:
    probabilities = _probabilities(record)
    if probabilities is None:
        return False
    if _number(record.get("lambda_home")) is None or _number(record.get("lambda_away")) is None:
        return False
    if _btts(record) is None:
        return False
    output = record.get("prediction_output") or {}
    unique_score = record.get("unique_score") or output.get("unique_score") or record.get("score_top1")
    return bool(unique_score and (_score_rows(record) or record.get("score_top3") or record.get("score_top5")))


def evaluate_prediction(record: dict[str, Any], actual: dict[str, Any]) -> dict[str, Any]:
    """Evaluate only values literally present in the immutable record."""
    normalized = normalize_result(actual)
    home, away = normalized["home_score_90m"], normalized["away_score_90m"]
    outcome = normalized["actual_outcome"]
    metrics: dict[str, Any] = {
        "actual_outcome": outcome,
        "top1_predicted_outcome": None,
        "top1_accuracy_1x2": None,
        "brier_score_1x2": None,
        "log_loss_1x2": None,
        "home_goal_absolute_error": None,
        "away_goal_absolute_error": None,
        "total_goal_absolute_error": None,
        "btts_brier": None,
        "btts_metric_status": None,
        "exact_score_top1": None,
        "exact_score_top3": None,
        "exact_score_top5": None,
        "exact_score_top10": None,
        "actual_score_probability": None,
        "actual_score_nll": None,
        "actual_score_nll_status": None,
        "market_only_1x2_brier": None,
        "market_only_1x2_logloss": None,
        "market_only_metric_status": None,
    }
    probabilities = _probabilities(record)
    if probabilities is not None:
        top = max(probabilities, key=probabilities.get).upper()
        actual_key = outcome.lower()
        one_hot = {key: float(key == actual_key) for key in probabilities}
        metrics.update({
            "top1_predicted_outcome": top,
            "top1_accuracy_1x2": int(top == outcome),
            "brier_score_1x2": sum((probabilities[key] - one_hot[key]) ** 2 for key in probabilities),
            "log_loss_1x2": -math.log(max(probabilities[actual_key], EPSILON)),
        })

    lambdas = (_number(record.get("lambda_home")), _number(record.get("lambda_away")))
    if all(value is not None for value in lambdas):
        metrics.update({
            "home_goal_absolute_error": abs(home - lambdas[0]),
            "away_goal_absolute_error": abs(away - lambdas[1]),
            "total_goal_absolute_error": abs(home + away - sum(lambdas)),
        })

    btts = _btts(record)
    if btts is not None:
        metrics["btts_brier"] = (btts["yes"] - float(normalized["btts_actual"])) ** 2
    else:
        metrics["btts_metric_status"] = "UNAVAILABLE_IN_FROZEN_RECORD"

    rows = _score_rows(record)
    actual_pair = (home, away)
    if rows:
        for index, row in enumerate(rows):
            if _score_pair(row.get("score")) == actual_pair:
                metrics["actual_score_probability"] = float(row["probability"])
                metrics["actual_score_nll"] = -math.log(max(float(row["probability"]), EPSILON))
                break
        metrics.update({
            "exact_score_top1": any(_score_pair(row.get("score")) == actual_pair for row in rows[:1]),
            "exact_score_top3": any(_score_pair(row.get("score")) == actual_pair for row in rows[:3]),
            "exact_score_top5": any(_score_pair(row.get("score")) == actual_pair for row in rows[:5]),
            "exact_score_top10": (
                any(_score_pair(row.get("score")) == actual_pair for row in rows[:10])
                if len(rows) >= 10
                else None
            ),
        })
        if metrics["actual_score_nll"] is None:
            metrics["actual_score_nll_status"] = "UNAVAILABLE_IN_FROZEN_RECORD"
    else:
        metrics["actual_score_nll_status"] = "UNAVAILABLE_IN_FROZEN_RECORD"

    if not rows:
        top1 = _score_pair(record.get("score_top1"))
        top3 = [_score_pair(value) for value in record.get("score_top3") or []]
        top5 = [_score_pair(value) for value in record.get("score_top5") or []]
        metrics.update({
            "exact_score_top1": top1 == actual_pair if top1 else None,
            "exact_score_top3": actual_pair in {value for value in top3 if value},
            "exact_score_top5": actual_pair in {value for value in top5 if value},
        })

    market = _market_baseline(record)
    if market is not None:
        actual_key = outcome.lower()
        one_hot = {key: float(key == actual_key) for key in market}
        metrics["market_only_1x2_brier"] = sum((market[key] - one_hot[key]) ** 2 for key in market)
        metrics["market_only_1x2_logloss"] = -math.log(max(market[actual_key], EPSILON))
    else:
        metrics["market_only_metric_status"] = "UNAVAILABLE_IN_FROZEN_RECORD"
    return metrics


def _identity_matches(record: dict[str, Any], result: dict[str, Any]) -> bool:
    expected_key = str(record.get("match_key") or (record.get("match_identity") or {}).get("match_key") or "")
    candidate_key = str(result.get("match_key") or result.get("canonical_match_id") or "")
    if expected_key and candidate_key and expected_key != candidate_key:
        return False
    expected_id = str(record.get("match_id") or (record.get("match_identity") or {}).get("match_id") or "")
    candidate_ids = {
        str(result.get(field)) for field in ("prediction_match_id", "match_id", "provider_match_id", "sporttery_match_id")
        if result.get(field) not in (None, "")
    }
    if expected_id and candidate_ids and expected_id not in candidate_ids:
        return False
    if expected_key and candidate_key == expected_key:
        return True
    if expected_id and expected_id in candidate_ids:
        return True
    return False


def _universe_fixture(record: dict[str, Any], universe_root: Path) -> dict[str, Any]:
    date = str(record.get("business_date") or "")
    path = universe_root / f"{date}.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    wanted = str(record.get("match_id") or "")
    for fixture in payload.get("fixtures") or []:
        if str(fixture.get("matchId") or fixture.get("match_id") or "") == wanted:
            return fixture
    return {}


def _provider_schedule(record: dict[str, Any], universe_root: Path) -> dict[str, Any]:
    identity = record.get("match_identity") or {}
    fixture = _universe_fixture(record, universe_root)
    return {
        "match_key": record.get("match_key") or identity.get("match_key"),
        "canonical_match_id": record.get("match_key") or identity.get("match_key"),
        "provider_match_id": record.get("match_id"),
        "match_id": record.get("match_id"),
        "nowscore_id": fixture.get("nowscoreId") or record.get("nowscore_id"),
        "home": fixture.get("homeTeam") or identity.get("home"),
        "away": fixture.get("awayTeam") or identity.get("away"),
        "kickoff_local": record.get("kickoff_at") or identity.get("kickoff_at"),
        "business_date": record.get("business_date"),
    }


def fetch_result_for_record(
    record: dict[str, Any],
    now: datetime,
    *,
    universe_root: Path = UNIVERSE_ROOT,
    result_root: Path = POSTMATCH_RESULT_ROOT,
) -> dict[str, Any]:
    """Reuse the existing Nowscore/ESPN result functions for one frozen match."""
    kickoff = parse_datetime(record.get("kickoff_at"))
    if kickoff is None or now < kickoff:
        return {"status": "RESULT_PENDING", "reason": "PRE_KICKOFF"}
    result_path = result_root / f"{safe_key(record.get('match_key'))}.json"
    if result_path.is_file():
        try:
            return json.loads(result_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass

    schedule = _provider_schedule(record, universe_root)
    if not schedule.get("nowscore_id"):
        try:
            schedule["nowscore_id"] = resolve_nowscore_id(schedule)
        except Exception:
            schedule["nowscore_id"] = None
    raw = None
    source = None
    source_url = None
    errors: list[str] = []
    if schedule.get("nowscore_id"):
        raw, source_url, error = fetch_nowscore_result(int(schedule["nowscore_id"]))
        if raw is not None:
            source = "nowscore_match_detail"
        elif error:
            errors.append(error)
    if raw is None:
        raw, source_url, error = fetch_espn_result(schedule)
        if raw is not None:
            source = "espn_scoreboard"
        elif error:
            errors.append(error)
    if raw is None:
        return {"status": "RESULT_PENDING", "reason": errors[-1] if errors else "RESULT_NOT_FINAL"}
    enriched = dict(raw)
    enriched.update({
        "status": "result_verified",
        "match_key": record.get("match_key"),
        "prediction_match_id": record.get("match_id"),
        "home": (record.get("match_identity") or {}).get("home"),
        "away": (record.get("match_identity") or {}).get("away"),
        "kickoff_local": record.get("kickoff_at"),
        "source": source or enriched.get("source"),
        "source_url": source_url or enriched.get("source_url"),
        "verified_at": enriched.get("verified_at") or now.isoformat(),
    })
    result_root.mkdir(parents=True, exist_ok=True)
    result_path.write_text(json.dumps(enriched, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    try:
        enriched["result_file"] = result_path.relative_to(BASE_DIR).as_posix()
    except ValueError:
        enriched["result_file"] = str(result_path)
    return enriched


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            rows.append(value)
    return rows


def _append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def _sample(record: dict[str, Any], actual: dict[str, Any], metrics: dict[str, Any], *, result_path: str | None, settled_at: str) -> dict[str, Any]:
    identity = dict(record.get("match_identity") or {})
    if record.get("match_id") is not None:
        identity["match_id"] = record.get("match_id")
    return {
        "schema_version": "1.0",
        "prediction_id": record.get("prediction_id"),
        "prediction_record_ref": f"data/model_governance/predictions/{record.get('prediction_id')}.json",
        "prediction_sha256": record.get("prediction_sha256"),
        "match_identity": identity,
        "business_date": record.get("business_date"),
        "kickoff_at": record.get("kickoff_at"),
        "prediction_created_at": record.get("prediction_created_at"),
        "freeze_at": record.get("freeze_created_at"),
        "minutes_to_kickoff": record.get("minutes_to_kickoff_at_freeze"),
        "product_role": record.get("product_role"),
        "model_family": record.get("model_family"),
        "release_version": record.get("release_version"),
        "formal_eligibility_policy": record.get("formal_eligibility_policy"),
        "data_grade": record.get("data_grade"),
        "base_input_quality": record.get("base_input_quality"),
        "market_intelligence_quality": record.get("market_intelligence_quality"),
        "market_data_providers": record.get("market_data_providers") or record.get("market_sources") or [],
        "market_bookmakers": record.get("market_bookmakers") or [],
        "market_families": record.get("market_families") or [],
        "prediction": {
            "probabilities": record.get("probabilities") or (record.get("prediction_output") or {}).get("probabilities"),
            "lambda_home": record.get("lambda_home"),
            "lambda_away": record.get("lambda_away"),
            "btts": record.get("btts") or (record.get("prediction_output") or {}).get("btts"),
            "score_top1": record.get("score_top1"),
            "score_top3": record.get("score_top3"),
            "score_top5": record.get("score_top5"),
            "score_distribution": record.get("score_distribution") or (record.get("prediction_output") or {}).get("score_matrix"),
            "market_only_baseline": record.get("market_only_baseline"),
        },
        "actual": {
            "home_score": actual["home_score_90m"],
            "away_score": actual["away_score_90m"],
            "outcome": actual["actual_outcome"],
            "total_goals": actual["total_goals"],
            "btts": actual["btts_actual"],
        },
        "metrics": metrics,
        "result_source": actual.get("source"),
        "result_verified_at": actual.get("result_verified_at") or actual.get("verified_at"),
        "result_ref": result_path,
        "settled_at": settled_at,
    }


def _write_summary(
    prospective_root: Path,
    *,
    date: str | None,
    result: dict[str, Any],
    formal_rows: list[dict[str, Any]],
    exploratory_rows: list[dict[str, Any]],
    exclusion_root: Path,
) -> None:
    by_role = Counter(str(row.get("product_role") or "UNKNOWN") for row in formal_rows)
    by_market = Counter(str(row.get("market_intelligence_quality") or "UNKNOWN") for row in formal_rows)
    summary = {
        "schema_version": "1.0",
        "updated_at": datetime.now(SHANGHAI).isoformat(),
        "last_run": {"business_date": date, "settled_at": result.get("settled_at")},
        "formal_sample_count_total": len(formal_rows),
        "samples_added_this_run": result.get("formal_samples_added", 0),
        "pending_results": result.get("pending_results", 0),
        "settled_total": len(formal_rows),
        "settled_this_run": result.get("settled_this_run", 0),
        "result_unresolved_this_run": result.get("result_unresolved_this_run", 0),
        "future_scheduled_formal_this_run": result.get("future_scheduled_formal_this_run", 0),
        "result_exception_reasons": result.get("result_exception_reasons", {}),
        "excluded_prediction_count": len(excluded_prediction_ids(exclusion_root)),
        "pilot_excluded_settled": len(exploratory_rows),
        "result_failures": result.get("result_failures", 0),
        "by_product_role": dict(by_role),
        "by_market_intelligence_quality": dict(by_market),
    }
    prospective_root.mkdir(parents=True, exist_ok=True)
    (prospective_root / SUMMARY_NAME).write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def settle_records(
    records: Iterable[dict[str, Any]],
    *,
    now: datetime,
    result_fetcher: Callable[[dict[str, Any], datetime], dict[str, Any]] | None = None,
    prospective_root: Path = PROSPECTIVE_ROOT,
    exclusion_root: Path = DEFAULT_EXCLUSION_ROOT,
    result_root: Path = POSTMATCH_RESULT_ROOT,
    universe_root: Path = UNIVERSE_ROOT,
    date: str | None = None,
) -> dict[str, Any]:
    prospective_root = prospective_root if prospective_root.is_absolute() else BASE_DIR / prospective_root
    exclusion_root = exclusion_root if exclusion_root.is_absolute() else BASE_DIR / exclusion_root
    ledger_path = prospective_root / LEDGER_NAME
    exploratory_path = prospective_root / EXPLORATORY_NAME
    formal_rows = _read_jsonl(ledger_path)
    exploratory_rows = _read_jsonl(exploratory_path)
    prospective_root.mkdir(parents=True, exist_ok=True)
    ledger_path.touch(exist_ok=True)
    formal_by_id = {str(row.get("prediction_id")): row for row in formal_rows if row.get("prediction_id")}
    exploratory_by_id = {str(row.get("prediction_id")): row for row in exploratory_rows if row.get("prediction_id")}
    result = {
        "business_date": date,
        "frozen_predictions": 0,
        "results_found": 0,
        "pending_results": 0,
        "future_scheduled_formal_this_run": 0,
        "result_unresolved_this_run": 0,
        "settled_this_run": 0,
        "pilot_excluded_settled": 0,
        "formal_samples_added": 0,
        "result_failures": 0,
        "result_conflicts": 0,
        "duplicate_prospective_samples": max(0, len(formal_rows) - len(formal_by_id)),
        "failure_reasons": {},
        "result_exception_reasons": {},
        "settled_at": now.isoformat(),
    }
    fetch = result_fetcher or (
        lambda record, current: fetch_result_for_record(
            record, current, universe_root=universe_root, result_root=result_root
        )
    )
    def mark_unresolved(reason: str, *, formal_candidate: bool) -> None:
        if not formal_candidate:
            return
        result["result_unresolved_this_run"] += 1
        result["result_exception_reasons"][reason] = (
            result["result_exception_reasons"].get(reason, 0) + 1
        )

    for record in records:
        prediction_id = str(record.get("prediction_id") or "").strip()
        if not prediction_id or record.get("prediction_status") not in FROZEN_STATUSES:
            continue
        result["frozen_predictions"] += 1
        excluded = exclusion_for(prediction_id, exclusion_root)
        formal_candidate = excluded is None
        if formal_candidate and not is_formally_eligible(record):
            continue
        kickoff = parse_datetime(record.get("kickoff_at"))
        if kickoff is not None and now < kickoff:
            if formal_candidate:
                result["future_scheduled_formal_this_run"] += 1
            result["pending_results"] += 1
            continue
        fetched = fetch(record, now)
        if str(fetched.get("status") or "").upper() in {"RESULT_PENDING", "PENDING", "RETRY_SCHEDULED"}:
            result["pending_results"] += 1
            mark_unresolved(str(fetched.get("reason") or "RESULT_PENDING"), formal_candidate=formal_candidate)
            continue
        if not _is_verified_result_artifact(fetched):
            result["result_failures"] += 1
            result["failure_reasons"]["RESULT_NOT_FINAL"] = result["failure_reasons"].get("RESULT_NOT_FINAL", 0) + 1
            mark_unresolved("RESULT_NOT_FINAL", formal_candidate=formal_candidate)
            continue
        try:
            actual = normalize_result(fetched)
        except ValueError:
            result["result_failures"] += 1
            result["failure_reasons"]["RESULT_NOT_FINAL"] = result["failure_reasons"].get("RESULT_NOT_FINAL", 0) + 1
            mark_unresolved("RESULT_NOT_FINAL", formal_candidate=formal_candidate)
            continue
        verified_at = parse_datetime(actual.get("result_verified_at"))
        if kickoff is not None and verified_at is not None and verified_at < kickoff:
            result["result_failures"] += 1
            result["failure_reasons"]["RESULT_TIME_UNVERIFIED"] = result["failure_reasons"].get("RESULT_TIME_UNVERIFIED", 0) + 1
            mark_unresolved("RESULT_TIME_UNVERIFIED", formal_candidate=formal_candidate)
            continue
        if not _identity_matches(record, actual):
            result["result_failures"] += 1
            result["failure_reasons"]["RESULT_IDENTITY_UNRESOLVED"] = result["failure_reasons"].get("RESULT_IDENTITY_UNRESOLVED", 0) + 1
            mark_unresolved("RESULT_IDENTITY_UNRESOLVED", formal_candidate=formal_candidate)
            continue
        result["results_found"] += 1
        existing = exploratory_by_id.get(prediction_id) if excluded is not None else formal_by_id.get(prediction_id)
        if existing is not None:
            old_actual = existing.get("actual") or {}
            if (old_actual.get("home_score"), old_actual.get("away_score")) != (
                actual["home_score_90m"], actual["away_score_90m"]
            ):
                result["result_conflicts"] += 1
                result["failure_reasons"]["RESULT_CONFLICT"] = result["failure_reasons"].get("RESULT_CONFLICT", 0) + 1
            continue
        metrics = evaluate_prediction(record, actual)
        sample = _sample(
            record,
            actual,
            metrics,
            result_path=actual.get("result_file") or actual.get("result_ref"),
            settled_at=now.isoformat(),
        )
        if excluded is not None:
            sample.update({
                "formal_prospective_eligible": False,
                "exclusion_reason_code": excluded.get("reason_code"),
            })
            _append_jsonl(exploratory_path, sample)
            exploratory_by_id[prediction_id] = sample
            exploratory_rows.append(sample)
            result["pilot_excluded_settled"] += 1
        else:
            sample["formal_prospective_eligible"] = True
            _append_jsonl(ledger_path, sample)
            formal_by_id[prediction_id] = sample
            formal_rows.append(sample)
            result["formal_samples_added"] += 1
            result["settled_this_run"] += 1
    result["settled_total"] = len(formal_by_id)
    _write_summary(
        prospective_root,
        date=date,
        result=result,
        formal_rows=formal_rows,
        exploratory_rows=exploratory_rows,
        exclusion_root=exclusion_root,
    )
    result["formal_prospective_total"] = len(formal_rows)
    return result


def load_frozen_records(
    business_date: str,
    *,
    prediction_root: Path = PREDICTION_ROOT,
    prediction_id: str | None = None,
) -> list[dict[str, Any]]:
    from model_governance import load_frozen_prediction

    root = prediction_root if prediction_root.is_absolute() else BASE_DIR / prediction_root
    paths = [root / f"{prediction_id}.json"] if prediction_id else sorted(root.glob("*.json"))
    records: list[dict[str, Any]] = []
    for path in paths:
        if not path.is_file():
            continue
        try:
            candidate = load_frozen_prediction(path.stem, root)
        except Exception:
            candidate = None
        if not isinstance(candidate, dict):
            continue
        if str(candidate.get("business_date") or "") != business_date:
            continue
        records.append(candidate)
    return records


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", required=True, help="Business date in YYYY-MM-DD")
    parser.add_argument("--prediction-id", help="Process one frozen prediction for debugging")
    parser.add_argument("--now", help="Deterministic current time for verification/tests")
    args = parser.parse_args()
    now = parse_datetime(args.now) if args.now else datetime.now(SHANGHAI)
    if now is None:
        raise SystemExit("--now must be an ISO timestamp")
    records = load_frozen_records(args.date, prediction_id=args.prediction_id)
    outcome = settle_records(records, now=now, date=args.date)
    print(json.dumps(outcome, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
