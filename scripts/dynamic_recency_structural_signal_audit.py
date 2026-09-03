#!/usr/bin/env python3
"""Run the pre-registered snapshot-local dynamic-recency signal probe.

This is a research-only offline challenger.  It reads immutable prospective
evidence, frozen Champion predictions, and authoritative 90-minute results.
It never changes model, provider, production, or frozen-history data.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import re
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from statistics import fmean, median
from typing import Any, Iterable, Mapping


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_ROOT = Path(__file__).resolve().parent
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from risk_engine import dixon_coles_score_matrix  # noqa: E402


MILESTONE = "DYNAMIC-RECENCY-STRUCTURAL-SIGNAL-OFFLINE-1"
CHAMPION_MODEL_FAMILY = "recent_form_market_calibrated_poisson_v2"
RESULT_SCOPE = "regulation_90m_plus_stoppage"
BOOTSTRAP_SEED = 20260903
DEFAULT_BOOTSTRAP_REPLICATES = 4000
MIN_EVALUABLE_UNIQUE_MATCHES = 50
MIN_UNIVERSE_SAMPLE = 20
HALF_LIVES = (60, 120, 240)
VARIANTS = ("E60", "E120", "E240")
SCORE_RE = re.compile(r"^\s*(\d+)\s*-\s*(\d+)\s*$")

DEFAULT_EVIDENCE_ROOT = PROJECT_ROOT / "data" / "prospective" / "football_evidence"
DEFAULT_RESULT_ROOT = PROJECT_ROOT / "data" / "postmatch_automation" / "results"
DEFAULT_PREDICTION_ROOT = PROJECT_ROOT / "data" / "model_governance" / "predictions"
DEFAULT_JOBS_ROOT = PROJECT_ROOT / "data" / "base_prediction_jobs"

UNIVERSES = (
    "CLUB_BIG5_TOP_LEAGUE",
    "CLUB_OTHER_TOP_LEAGUE",
    "CLUB_LOWER_DIVISION",
    "CLUB_DOMESTIC_CUP",
    "CLUB_CONTINENTAL",
    "NATIONAL_TEAM",
    "UNKNOWN_OR_MIXED",
)

METRICS = (
    "exact_score_nll",
    "actual_score_mean_probability",
    "top1_accuracy",
    "top3_accuracy",
    "top5_accuracy",
    "one_x_two_brier",
    "one_x_two_log_loss",
    "ou_2_5_brier",
    "btts_brier",
    "home_goal_mae",
    "home_goal_bias",
    "away_goal_mae",
    "away_goal_bias",
    "total_goal_mae",
    "total_goal_bias",
    "top1_score_concentration_mean_probability",
    "top1_score_1_1_share",
    "score_1_1_probability_mean",
)

BIG5_TOP_LEAGUE_NAMES = frozenset(
    {
        "\u897f\u73ed\u7259\u7532\u7ea7\u8054\u8d5b",
        "\u82f1\u683c\u5170\u8d85\u7ea7\u8054\u8d5b",
        "\u610f\u5927\u5229\u7532\u7ea7\u8054\u8d5b",
        "\u5fb7\u56fd\u7532\u7ea7\u8054\u8d5b",
        "\u6cd5\u56fd\u7532\u7ea7\u8054\u8d5b",
    }
)
OTHER_TOP_LEAGUE_NAMES = frozenset(
    {
        "\u8377\u5170\u7532\u7ea7\u8054\u8d5b",
        "\u97e9\u56fd\u804c\u4e1a\u8054\u8d5b",
        "\u745e\u5178\u8d85\u7ea7\u8054\u8d5b",
        "\u65e5\u672c\u804c\u4e1a\u8054\u8d5b",
        "\u8461\u8404\u7259\u8d85\u7ea7\u8054\u8d5b",
        "\u632a\u5a01\u8d85\u7ea7\u8054\u8d5b",
        "\u5df4\u897f\u7532\u7ea7\u8054\u8d5b",
        "\u82ac\u5170\u7532\u7ea7\u8054\u8d5b",
        "\u6c99\u7279\u804c\u4e1a\u8054\u8d5b",
        "\u7f8e\u56fd\u804c\u4e1a\u5927\u8054\u76df",
    }
)
LOWER_DIVISION_NAMES = frozenset(
    {
        "\u82f1\u683c\u5170\u51a0\u519b\u8054\u8d5b",
        "\u5fb7\u56fd\u4e59\u7ea7\u8054\u8d5b",
        "\u65e5\u672c\u4e59\u7ea7\u8054\u8d5b",
        "\u6cd5\u56fd\u4e59\u7ea7\u8054\u8d5b",
        "\u8377\u5170\u4e59\u7ea7\u8054\u8d5b",
    }
)
DOMESTIC_CUP_NAMES = frozenset(
    {
        "\u5df4\u897f\u676f",
        "\u5fb7\u56fd\u8d85\u7ea7\u676f",
        "\u97e9\u56fd\u676f",
        "\u82f1\u683c\u5170\u8054\u8d5b\u676f",
        "\u82f1\u683c\u5170\u793e\u533a\u76fe\u676f",
    }
)
CONTINENTAL_NAMES = frozenset(
    {
        "\u6b27\u7f57\u5df4\u8054\u8d5b",
        "\u6b27\u6d32\u51a0\u519b\u8054\u8d5b",
        "\u5357\u7f8e\u89e3\u653e\u8005\u676f",
    }
)
NATIONAL_TEAM_NAMES = frozenset(
    {
        "\u56fd\u9645\u53cb\u8c0a\u8d5b",
        "\u4e16\u754c\u676f",
        "\u4e16\u754c\u676f\u9884\u9009\u8d5b",
        "\u6b27\u6d32\u676f",
        "\u4e9a\u6d32\u676f",
        "\u7f8e\u6d32\u676f",
        "\u975e\u6d32\u676f",
        "\u6b27\u6d32\u56fd\u5bb6\u8054\u8d5b",
    }
)


def _text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _display_path(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(PROJECT_ROOT.resolve()).as_posix()
    except ValueError:
        return resolved.as_posix()


def _parse_datetime(value: Any) -> datetime | None:
    raw = _text(value)
    if not raw:
        return None
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _parse_date(value: Any) -> date | None:
    raw = _text(value)
    if not raw:
        return None
    try:
        return date.fromisoformat(raw[:10])
    except ValueError:
        return None


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _nonnegative_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, str) and re.fullmatch(r"\s*\d+\s*", value):
        return int(value.strip())
    return None


def _parse_score(value: Any) -> tuple[int, int] | None:
    if value is None:
        return None
    match = SCORE_RE.fullmatch(str(value).strip())
    if match is None:
        return None
    return int(match.group(1)), int(match.group(2))


def _is_after(later: datetime | None, earlier: datetime | None) -> bool:
    if later is None or earlier is None:
        return False
    try:
        return later > earlier
    except TypeError:
        return False


def _stable_seed(seed: int, label: str) -> int:
    digest = hashlib.sha256(label.encode("utf-8")).hexdigest()
    return int(seed) + int(digest[:8], 16)


def _infer_subject_team_id(rows: Iterable[dict[str, Any]]) -> tuple[str | None, float]:
    counts: Counter[str] = Counter()
    valid_rows = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        valid_rows += 1
        for key in ("home_team_id", "away_team_id"):
            value = _text(row.get(key))
            if value:
                counts[value] += 1
    if not counts or valid_rows <= 0:
        return None, 0.0
    subject, count = counts.most_common(1)[0]
    return subject, count / valid_rows


def _valid_history_row(row: Any, kickoff: datetime | None) -> bool:
    if not isinstance(row, dict):
        return False
    row_date = _parse_date(row.get("match_date"))
    if row_date is None or kickoff is None or row_date >= kickoff.date():
        return False
    home_goals = _nonnegative_int(row.get("home_goals"))
    away_goals = _nonnegative_int(row.get("away_goals"))
    return (
        home_goals is not None
        and away_goals is not None
        and bool(_text(row.get("home_team_id")))
        and bool(_text(row.get("away_team_id")))
    )


def _evidence_integrity(payload: dict[str, Any]) -> dict[str, Any]:
    kickoff = _parse_datetime(payload.get("kickoff_at"))
    captured = _parse_datetime(payload.get("evidence_captured_at"))
    cutoff = _parse_datetime(payload.get("source_cutoff_at"))
    reasons: list[str] = []
    if kickoff is None:
        reasons.append("INVALID_KICKOFF")
    if captured is None:
        reasons.append("INVALID_EVIDENCE_CAPTURE_TIME")
    elif kickoff is not None and captured >= kickoff:
        reasons.append("EVIDENCE_NOT_PREMATCH")
    if cutoff is None:
        reasons.append("INVALID_SOURCE_CUTOFF")
    elif kickoff is not None and cutoff >= kickoff:
        reasons.append("SOURCE_CUTOFF_NOT_PREMATCH")
    if not _text(payload.get("match_key")):
        reasons.append("MISSING_MATCH_KEY")

    recent = payload.get("recent_matches")
    recent = recent if isinstance(recent, dict) else {}
    home_rows = recent.get("home_team") if isinstance(recent.get("home_team"), list) else []
    away_rows = recent.get("away_team") if isinstance(recent.get("away_team"), list) else []
    home_valid = [row for row in home_rows if _valid_history_row(row, kickoff)]
    away_valid = [row for row in away_rows if _valid_history_row(row, kickoff)]
    if len(home_valid) < 10:
        reasons.append("HOME_HISTORY_TOO_SHORT")
    if len(away_valid) < 10:
        reasons.append("AWAY_HISTORY_TOO_SHORT")
    home_id, home_share = _infer_subject_team_id(home_valid)
    away_id, away_share = _infer_subject_team_id(away_valid)
    if home_id is None or home_share < 0.8:
        reasons.append("HOME_TEAM_IDENTITY_UNSTABLE")
    if away_id is None or away_share < 0.8:
        reasons.append("AWAY_TEAM_IDENTITY_UNSTABLE")
    if home_id and away_id and home_id == away_id:
        reasons.append("HOME_AWAY_IDENTITY_COLLISION")
    return {
        "usable": not reasons,
        "reasons": reasons,
        "kickoff": kickoff,
        "captured": captured,
        "home_rows": home_valid,
        "away_rows": away_valid,
        "home_subject_team_id": home_id,
        "away_subject_team_id": away_id,
        "home_identity_share": home_share,
        "away_identity_share": away_share,
    }


def _authoritative_result_status(payload: dict[str, Any]) -> dict[str, Any]:
    match_key = _text(payload.get("match_key"))
    scope = _text(payload.get("scope"))
    kickoff_raw = payload.get("kickoff_at") or payload.get("kickoff_local")
    kickoff = _parse_datetime(kickoff_raw)
    verified_raw = payload.get("verified_at")
    verified = _parse_datetime(verified_raw)
    score = _parse_score(payload.get("result_90m"))
    reasons: list[str] = []
    if not match_key:
        reasons.append("RESULT_MISSING_MATCH_KEY")
    if scope != RESULT_SCOPE:
        reasons.append("RESULT_SCOPE_NOT_REGULATION_90M")
    if score is None:
        reasons.append("RESULT_90M_UNPARSEABLE")
    if verified is None:
        reasons.append("INVALID_RESULT_VERIFIED_AT")
    if kickoff is None:
        reasons.append("INVALID_RESULT_KICKOFF")
    elif verified is not None and not _is_after(verified, kickoff):
        reasons.append("VERIFIED_AT_NOT_AFTER_KICKOFF")
    home_score = _nonnegative_int(payload.get("home_score"))
    away_score = _nonnegative_int(payload.get("away_score"))
    if score is not None and (home_score is not None or away_score is not None):
        if (home_score, away_score) != score:
            reasons.append("RESULT_SCORE_FIELD_CONFLICT")
    return {
        "valid": not reasons,
        "reasons": reasons,
        "match_key": match_key,
        "kickoff": kickoff,
        "kickoff_raw": kickoff_raw,
        "verified": verified,
        "verified_raw": verified_raw,
        "score": score,
        "scope": scope,
    }


def _load_authoritative_results(
    result_root: Path,
) -> tuple[dict[str, dict[str, Any]], int, Counter[str], list[dict[str, Any]]]:
    results: dict[str, dict[str, Any]] = {}
    failures: Counter[str] = Counter()
    rejected: list[dict[str, Any]] = []
    paths = sorted(result_root.glob("*.json"))
    for path in paths:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            failures["INVALID_RESULT_JSON"] += 1
            rejected.append({"path": _display_path(path), "reasons": ["INVALID_RESULT_JSON"]})
            continue
        if not isinstance(payload, dict):
            failures["INVALID_RESULT_OBJECT"] += 1
            rejected.append({"path": _display_path(path), "reasons": ["INVALID_RESULT_OBJECT"]})
            continue
        status = _authoritative_result_status(payload)
        for reason in status["reasons"]:
            failures[reason] += 1
        if not status["valid"]:
            rejected.append(
                {
                    "path": _display_path(path),
                    "match_key": status["match_key"] or None,
                    "scope": payload.get("scope"),
                    "result_90m": payload.get("result_90m"),
                    "reasons": sorted(set(status["reasons"])),
                }
            )
            continue
        if status["match_key"] in results:
            failures["DUPLICATE_RESULT_MATCH_KEY"] += 1
            rejected.append(
                {
                    "path": _display_path(path),
                    "match_key": status["match_key"],
                    "scope": payload.get("scope"),
                    "result_90m": payload.get("result_90m"),
                    "reasons": ["DUPLICATE_RESULT_MATCH_KEY"],
                }
            )
            continue
        results[status["match_key"]] = {
            "path": _display_path(path),
            "payload": payload,
            **status,
        }
    return results, len(paths), failures, rejected


def _load_evidence(
    evidence_root: Path,
) -> tuple[dict[str, dict[str, Any]], int, Counter[str]]:
    records: dict[str, dict[str, Any]] = {}
    failures: Counter[str] = Counter()
    paths = sorted(evidence_root.glob("*.json"))
    for path in paths:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            failures["INVALID_EVIDENCE_JSON"] += 1
            continue
        if not isinstance(payload, dict):
            failures["INVALID_EVIDENCE_OBJECT"] += 1
            continue
        prediction_id = _text(payload.get("prediction_id"))
        if not prediction_id:
            failures["MISSING_PREDICTION_ID"] += 1
            continue
        if prediction_id in records:
            failures["DUPLICATE_PREDICTION_ID"] += 1
            continue
        status = _evidence_integrity(payload)
        for reason in status["reasons"]:
            failures[reason] += 1
        records[prediction_id] = {
            "path": _display_path(path),
            "payload": payload,
            "prediction_id": prediction_id,
            "match_key": _text(payload.get("match_key")),
            "match_id": _text(payload.get("match_id")),
            "kickoff_raw": payload.get("kickoff_at"),
            "kickoff": status["kickoff"],
            "captured_raw": payload.get("evidence_captured_at"),
            "captured": status["captured"],
            "usable": status["usable"],
            **status,
        }
    return records, len(paths), failures


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None


def _load_competition_metadata(
    jobs_root: Path,
    match_ids: set[str],
) -> dict[str, dict[str, Any]]:
    candidates: dict[str, set[str]] = defaultdict(set)
    for path in sorted(jobs_root.glob("*.json")):
        payload = _load_json(path)
        if not isinstance(payload, dict):
            continue
        for section in ("jobs", "removed_jobs"):
            rows = payload.get(section)
            if not isinstance(rows, list):
                continue
            for row in rows:
                if not isinstance(row, dict):
                    continue
                match_id = _text(row.get("match_id"))
                if match_id not in match_ids:
                    continue
                competition = _text(row.get("league") or row.get("competition"))
                if competition:
                    candidates[match_id].add(competition)
    metadata: dict[str, dict[str, Any]] = {}
    for match_id in sorted(match_ids):
        values = sorted(candidates.get(match_id, set()))
        metadata[match_id] = {
            "competition": values[0] if len(values) == 1 else None,
            "candidates": values,
            "metadata_status": (
                "MATCHED" if len(values) == 1 else "AMBIGUOUS" if values else "MISSING"
            ),
        }
    return metadata


def classify_competition(competition: str | None) -> str:
    name = _text(competition)
    if not name:
        return "UNKNOWN_OR_MIXED"
    if name in NATIONAL_TEAM_NAMES:
        return "NATIONAL_TEAM"
    if name in CONTINENTAL_NAMES:
        return "CLUB_CONTINENTAL"
    if name in BIG5_TOP_LEAGUE_NAMES:
        return "CLUB_BIG5_TOP_LEAGUE"
    if name in OTHER_TOP_LEAGUE_NAMES:
        return "CLUB_OTHER_TOP_LEAGUE"
    if name in LOWER_DIVISION_NAMES:
        return "CLUB_LOWER_DIVISION"
    if name in DOMESTIC_CUP_NAMES:
        return "CLUB_DOMESTIC_CUP"
    return "UNKNOWN_OR_MIXED"


def _subject_history(
    rows: list[dict[str, Any]],
    *,
    subject_id: str | None,
    target_kickoff: datetime,
    side_label: str,
) -> list[dict[str, Any]]:
    if not subject_id:
        raise ValueError(f"{side_label} subject team ID is unavailable")
    output: list[dict[str, Any]] = []
    for row in rows:
        home_id = _text(row.get("home_team_id"))
        away_id = _text(row.get("away_team_id"))
        if subject_id not in {home_id, away_id}:
            raise ValueError(f"{side_label} history contains a non-subject row")
        if home_id == subject_id and away_id == subject_id:
            raise ValueError(f"{side_label} history has subject identity collision")
        row_date = _parse_date(row.get("match_date"))
        home_goals = _nonnegative_int(row.get("home_goals"))
        away_goals = _nonnegative_int(row.get("away_goals"))
        if row_date is None or home_goals is None or away_goals is None:
            raise ValueError(f"{side_label} history contains an invalid score/date row")
        days = (target_kickoff.date() - row_date).days
        if days <= 0:
            raise ValueError(f"{side_label} history contains a non-prior date")
        subject_is_home = home_id == subject_id
        output.append(
            {
                "match_date": row_date.isoformat(),
                "goals_for": home_goals if subject_is_home else away_goals,
                "goals_against": away_goals if subject_is_home else home_goals,
                "subject_is_home": subject_is_home,
                "days_before_target_kickoff": days,
            }
        )
    if not output:
        raise ValueError(f"{side_label} history cannot be constructed")
    return output


def _mean_or_none(values: Iterable[float | None]) -> float | None:
    clean = [float(value) for value in values if value is not None and math.isfinite(float(value))]
    return fmean(clean) if clean else None


def _weighted_mean(
    rows: list[dict[str, Any]],
    field: str,
    half_life_days: int | None,
) -> float | None:
    if not rows:
        return None
    weighted_sum = 0.0
    weight_sum = 0.0
    for row in rows:
        value = _finite(row.get(field))
        days = _finite(row.get("days_before_target_kickoff"))
        if value is None or days is None or days < 0:
            return None
        weight = 1.0 if half_life_days is None else math.exp(-math.log(2.0) * days / half_life_days)
        if not math.isfinite(weight) or weight <= 0:
            return None
        weighted_sum += weight * value
        weight_sum += weight
    if weight_sum <= 0 or not math.isfinite(weight_sum):
        return None
    result = weighted_sum / weight_sum
    return result if math.isfinite(result) else None


def _form_proxy(
    home_history: list[dict[str, Any]],
    away_history: list[dict[str, Any]],
    half_life_days: int | None,
) -> dict[str, float | int | None]:
    home_overall = home_history
    away_overall = away_history
    home_home = [row for row in home_history if row["subject_is_home"]]
    away_away = [row for row in away_history if not row["subject_is_home"]]
    effective_home_home = home_home or home_overall
    effective_away_away = away_away or away_overall

    home_venue = _mean_or_none(
        [
            _weighted_mean(effective_home_home, "goals_for", half_life_days),
            _weighted_mean(effective_away_away, "goals_against", half_life_days),
        ]
    )
    away_venue = _mean_or_none(
        [
            _weighted_mean(effective_away_away, "goals_for", half_life_days),
            _weighted_mean(effective_home_home, "goals_against", half_life_days),
        ]
    )
    home_general = _mean_or_none(
        [
            _weighted_mean(home_overall, "goals_for", half_life_days),
            _weighted_mean(away_overall, "goals_against", half_life_days),
        ]
    )
    away_general = _mean_or_none(
        [
            _weighted_mean(away_overall, "goals_for", half_life_days),
            _weighted_mean(home_overall, "goals_against", half_life_days),
        ]
    )
    home_proxy = _mean_or_none([home_venue, home_venue, home_general])
    away_proxy = _mean_or_none([away_venue, away_venue, away_general])
    return {
        "home_overall": _weighted_mean(home_overall, "goals_for", half_life_days),
        "away_overall": _weighted_mean(away_overall, "goals_for", half_life_days),
        "home_venue": home_venue,
        "away_venue": away_venue,
        "home_general": home_general,
        "away_general": away_general,
        "home_form_proxy": home_proxy,
        "away_form_proxy": away_proxy,
        "form_total": (
            home_proxy + away_proxy
            if home_proxy is not None and away_proxy is not None
            else None
        ),
        "home_history_n": len(home_history),
        "away_history_n": len(away_history),
        "home_home_n": len(home_home),
        "away_away_n": len(away_away),
    }


def _ratio(value: Any, denominator: Any, label: str) -> float:
    numerator = _finite(value)
    base = _finite(denominator)
    if base is None or base <= 0:
        raise ValueError(f"{label} denominator is non-positive or non-finite")
    if numerator is None:
        raise ValueError(f"{label} numerator is non-finite")
    result = numerator / base
    if not math.isfinite(result):
        raise ValueError(f"{label} ratio is non-finite")
    return result


def _load_frozen_prediction(
    prediction_root: Path,
    prediction_id: str,
    match_key: str,
    evidence_kickoff: datetime,
) -> dict[str, Any]:
    path = prediction_root / f"{prediction_id}.json"
    payload = _load_json(path)
    if not isinstance(payload, dict):
        raise ValueError(f"missing or invalid frozen prediction: {prediction_id}")
    if _text(payload.get("prediction_id")) != prediction_id:
        raise ValueError(f"frozen prediction ID mismatch: {prediction_id}")
    if _text(payload.get("match_key")) != match_key:
        raise ValueError(f"frozen prediction match_key mismatch: {prediction_id}")
    if payload.get("model_role") != "champion":
        raise ValueError(f"prediction is not Champion: {prediction_id}")
    if payload.get("model_family") != CHAMPION_MODEL_FAMILY:
        raise ValueError(f"unexpected model family: {prediction_id}")
    if payload.get("model_core_version") != CHAMPION_MODEL_FAMILY:
        raise ValueError(f"unexpected model core version: {prediction_id}")
    if payload.get("prediction_status") != "formal":
        raise ValueError(f"prediction is not formal: {prediction_id}")
    if payload.get("formal_eligible") is not True or payload.get("model_formal_eligible") is not True:
        raise ValueError(f"prediction is not formal eligible: {prediction_id}")

    prediction_kickoff = _parse_datetime(payload.get("kickoff_at"))
    if prediction_kickoff is not None and prediction_kickoff != evidence_kickoff:
        raise ValueError(f"frozen prediction kickoff mismatch: {prediction_id}")
    lambda_home = _finite(payload.get("lambda_home"))
    lambda_away = _finite(payload.get("lambda_away"))
    rho = _finite(payload.get("rho"))
    if lambda_home is None or lambda_away is None or lambda_home <= 0 or lambda_away <= 0:
        raise ValueError(f"frozen prediction lambdas are invalid: {prediction_id}")
    if rho is None:
        raise ValueError(f"frozen prediction rho is invalid: {prediction_id}")
    return {
        "path": _display_path(path),
        "prediction_id": prediction_id,
        "match_key": match_key,
        "lambda_home": lambda_home,
        "lambda_away": lambda_away,
        "lambda_total": lambda_home + lambda_away,
        "rho": rho,
        "model_family": payload.get("model_family"),
        "model_role": payload.get("model_role"),
        "prediction_status": payload.get("prediction_status"),
        "formal_eligible": payload.get("formal_eligible"),
    }


def _outcome_probabilities(matrix: Mapping[tuple[int, int], float]) -> dict[str, float]:
    output = {"home": 0.0, "draw": 0.0, "away": 0.0}
    for (home, away), probability in matrix.items():
        key = "home" if home > away else "draw" if home == away else "away"
        output[key] += probability
    return output


def _variant_observation(
    *,
    actual_home: int,
    actual_away: int,
    lambda_home: float,
    lambda_away: float,
    rho: float,
) -> dict[str, Any]:
    matrix = dixon_coles_score_matrix(
        {"lambda_home": lambda_home, "lambda_away": lambda_away, "rho": rho}
    )
    actual_score = (actual_home, actual_away)
    if not matrix or actual_score not in matrix:
        raise ValueError("score matrix is unavailable for the actual score")
    probabilities = _outcome_probabilities(matrix)
    actual_outcome = "home" if actual_home > actual_away else "draw" if actual_home == actual_away else "away"
    ordered = sorted(matrix.items(), key=lambda item: (-item[1], item[0][0], item[0][1]))
    top_scores = [score for score, _ in ordered]
    total_probability = sum(
        probability for (home, away), probability in matrix.items() if home + away >= 3
    )
    btts_probability = sum(
        probability for (home, away), probability in matrix.items() if home > 0 and away > 0
    )
    actual_probability = matrix[actual_score]
    return {
        "lambda_home": lambda_home,
        "lambda_away": lambda_away,
        "lambda_total": lambda_home + lambda_away,
        "rho": rho,
        "exact_score_nll": -math.log(max(actual_probability, 1e-15)),
        "actual_score_mean_probability": actual_probability,
        "top1_accuracy": float(actual_score == top_scores[0]),
        "top3_accuracy": float(actual_score in set(top_scores[:3])),
        "top5_accuracy": float(actual_score in set(top_scores[:5])),
        "one_x_two_brier": sum(
            (probabilities[key] - float(key == actual_outcome)) ** 2
            for key in ("home", "draw", "away")
        )
        / 3.0,
        "one_x_two_log_loss": -math.log(max(probabilities[actual_outcome], 1e-15)),
        "ou_2_5_brier": (total_probability - float(actual_home + actual_away >= 3)) ** 2,
        "btts_brier": (btts_probability - float(actual_home > 0 and actual_away > 0)) ** 2,
        "home_goal_mae": abs(lambda_home - actual_home),
        "home_goal_bias": lambda_home - actual_home,
        "away_goal_mae": abs(lambda_away - actual_away),
        "away_goal_bias": lambda_away - actual_away,
        "total_goal_mae": abs(lambda_home + lambda_away - actual_home - actual_away),
        "total_goal_bias": lambda_home + lambda_away - actual_home - actual_away,
        "top1_score_concentration_mean_probability": ordered[0][1],
        "top1_score_1_1_share": float(top_scores[0] == (1, 1)),
        "score_1_1_probability_mean": matrix.get((1, 1), 0.0),
        "top1_score": f"{top_scores[0][0]}-{top_scores[0][1]}",
        "actual_score_probability": actual_probability,
        "one_x_two_probabilities": probabilities,
        "over_2_5_probability": total_probability,
        "btts_probability": btts_probability,
    }


def _aggregate_metrics(rows: list[dict[str, Any]], variant: str) -> dict[str, float | None]:
    if not rows:
        return {metric: None for metric in METRICS}
    values = [row["variants"][variant] for row in rows]
    return {
        metric: round(fmean(float(value[metric]) for value in values), 9)
        for metric in METRICS
    }


def _quantile(values: list[float], probability: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = int(math.floor(position))
    upper = min(len(ordered) - 1, lower + 1)
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def _paired_bootstrap(
    rows: list[dict[str, Any]],
    variant: str,
    *,
    seed: int,
    replicates: int,
) -> dict[str, dict[str, Any]]:
    if not rows:
        return {
            metric: {
                "point_estimate_variant_minus_champion": None,
                "bootstrap_ci_95": [None, None],
                "seed": seed,
                "replicates": replicates,
            }
            for metric in METRICS
        }
    if replicates < 1:
        raise ValueError("bootstrap replicates must be positive")
    differences = {
        metric: [
            float(row["variants"][variant][metric])
            - float(row["variants"]["CHAMPION"][metric])
            for row in rows
        ]
        for metric in METRICS
    }
    points = {metric: fmean(values) for metric, values in differences.items()}
    rng = random.Random(seed)
    bootstrap_values = {metric: [] for metric in METRICS}
    sample_size = len(rows)
    for _ in range(replicates):
        indices = [rng.randrange(sample_size) for _ in range(sample_size)]
        for metric in METRICS:
            bootstrap_values[metric].append(
                fmean(differences[metric][index] for index in indices)
            )
    return {
        metric: {
            "point_estimate_variant_minus_champion": round(points[metric], 9),
            "bootstrap_ci_95": [
                round(_quantile(bootstrap_values[metric], 0.025), 9),
                round(_quantile(bootstrap_values[metric], 0.975), 9),
            ],
            "seed": seed,
            "replicates": replicates,
            "sample_n": sample_size,
            "method": "paired_nonparametric_bootstrap_resampling_unique_matches",
        }
        for metric in METRICS
    }


def _distribution(values: Iterable[float]) -> dict[str, float | int | None]:
    clean = [float(value) for value in values if math.isfinite(float(value))]
    if not clean:
        return {
            "count": 0,
            "mean": None,
            "min": None,
            "p25": None,
            "median": None,
            "p75": None,
            "max": None,
        }
    return {
        "count": len(clean),
        "mean": round(fmean(clean), 9),
        "min": round(min(clean), 9),
        "p25": round(_quantile(clean, 0.25), 9),
        "median": round(median(clean), 9),
        "p75": round(_quantile(clean, 0.75), 9),
        "max": round(max(clean), 9),
    }


def _direction(delta: float | None, *, lower_is_better: bool) -> str:
    if delta is None:
        return "UNAVAILABLE"
    if abs(delta) <= 1e-12:
        return "NO_CHANGE"
    if lower_is_better:
        return "IMPROVES" if delta < 0 else "WORSENS"
    return "IMPROVES" if delta > 0 else "WORSENS"


def _scope_summary(
    rows: list[dict[str, Any]],
    name: str,
    global_e120_delta: float | None,
) -> dict[str, Any]:
    variants = {
        variant: {
            "metrics": _aggregate_metrics(rows, variant),
        }
        for variant in ("CHAMPION", *VARIANTS)
    }
    champion_metrics = variants["CHAMPION"]["metrics"]
    for variant in VARIANTS:
        metric_deltas = {
            metric: (
                variants[variant]["metrics"][metric] - champion_metrics[metric]
                if variants[variant]["metrics"][metric] is not None
                and champion_metrics[metric] is not None
                else None
            )
            for metric in METRICS
        }
        variants[variant]["metric_deltas_vs_champion"] = metric_deltas
        variants[variant]["exact_score_nll_direction"] = _direction(
            metric_deltas["exact_score_nll"], lower_is_better=True
        )
    e120_delta = (
        variants["E120"]["metric_deltas_vs_champion"]["exact_score_nll"]
        if rows
        else None
    )
    if e120_delta is None or global_e120_delta is None:
        relative_direction = "UNAVAILABLE"
    elif abs(e120_delta) <= 1e-12 or abs(global_e120_delta) <= 1e-12:
        relative_direction = "NO_CHANGE"
    elif (e120_delta < 0) == (global_e120_delta < 0):
        relative_direction = "SAME_DIRECTION"
    else:
        relative_direction = "OPPOSITE_DIRECTION"
    n = len(rows)
    return {
        "scope": name,
        "n": n,
        "sample_status": "SUFFICIENT" if n >= MIN_UNIVERSE_SAMPLE else "DESCRIPTIVE_ONLY_INSUFFICIENT_SAMPLE",
        "strong_conclusion_allowed": n >= MIN_UNIVERSE_SAMPLE,
        "variants": variants,
        "directional_guardrail": {
            "reference_variant": "E120",
            "metric": "exact_score_nll",
            "global_variant_minus_champion": global_e120_delta,
            "scope_variant_minus_champion": e120_delta,
            "relative_to_global": relative_direction,
        },
    }


def _chronology_thirds(rows: list[dict[str, Any]], global_e120_delta: float | None) -> list[dict[str, Any]]:
    ordered = sorted(rows, key=lambda row: (row["kickoff"], row["match_key"]))
    n = len(ordered)
    base, remainder = divmod(n, 3)
    sizes = [base + (1 if index < remainder else 0) for index in range(3)]
    output: list[dict[str, Any]] = []
    cursor = 0
    for label, size in zip(("earliest_third", "middle_third", "latest_third"), sizes):
        subset = ordered[cursor : cursor + size]
        cursor += size
        scope = _scope_summary(subset, label, global_e120_delta)
        scope["actual_total_mean"] = (
            round(fmean(row["actual_total"] for row in subset), 9) if subset else None
        )
        scope["champion_lambda_total_mean"] = (
            round(fmean(row["variants"]["CHAMPION"]["lambda_total"] for row in subset), 9)
            if subset
            else None
        )
        scope["form_total_e0_mean"] = (
            round(fmean(row["form_proxy_e0_total"] for row in subset), 9) if subset else None
        )
        scope["e120_lambda_total_mean"] = (
            round(fmean(row["variants"]["E120"]["lambda_total"] for row in subset), 9)
            if subset
            else None
        )
        scope["observed_minus_champion_lambda_total_mean"] = (
            round(scope["actual_total_mean"] - scope["champion_lambda_total_mean"], 9)
            if scope["actual_total_mean"] is not None and scope["champion_lambda_total_mean"] is not None
            else None
        )
        scope["observed_minus_e120_lambda_total_mean"] = (
            round(scope["actual_total_mean"] - scope["e120_lambda_total_mean"], 9)
            if scope["actual_total_mean"] is not None and scope["e120_lambda_total_mean"] is not None
            else None
        )
        scope["match_keys"] = [row["match_key"] for row in subset]
        output.append(scope)
    return output


def _json_safe_observation(row: dict[str, Any]) -> dict[str, Any]:
    output = dict(row)
    output.pop("kickoff", None)
    output["kickoff"] = row["kickoff"].isoformat()
    if isinstance(row.get("evidence_captured_at"), datetime):
        output["evidence_captured_at"] = row["evidence_captured_at"].isoformat()
    return output


def run(
    *,
    evidence_root: Path = DEFAULT_EVIDENCE_ROOT,
    result_root: Path = DEFAULT_RESULT_ROOT,
    prediction_root: Path = DEFAULT_PREDICTION_ROOT,
    jobs_root: Path = DEFAULT_JOBS_ROOT,
    bootstrap_replicates: int = DEFAULT_BOOTSTRAP_REPLICATES,
) -> dict[str, Any]:
    failures: list[dict[str, Any]] = []
    result_map, result_file_count, result_failures, rejected_results = _load_authoritative_results(
        result_root
    )
    evidence_records, evidence_file_count, evidence_failures = _load_evidence(evidence_root)

    strict_settled_ids: set[str] = set()
    settlement_rejection_reasons: Counter[str] = Counter()
    for prediction_id, evidence in evidence_records.items():
        if not evidence["usable"]:
            continue
        result = result_map.get(evidence["match_key"])
        if result is None:
            settlement_rejection_reasons["NO_STRICT_AUTHORITATIVE_RESULT"] += 1
            continue
        if not _is_after(result["verified"], evidence["kickoff"]):
            settlement_rejection_reasons["RESULT_NOT_AFTER_EVIDENCE_KICKOFF"] += 1
            continue
        strict_settled_ids.add(prediction_id)

    by_match_key: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for prediction_id in strict_settled_ids:
        by_match_key[evidence_records[prediction_id]["match_key"]].append(
            evidence_records[prediction_id]
        )
    selected_evidence: list[dict[str, Any]] = []
    for match_key, records in by_match_key.items():
        legal = [record for record in records if record["captured"] is not None]
        if not legal:
            failures.append(
                {
                    "kind": "COHORT_SNAPSHOT_SELECTION",
                    "match_key": match_key,
                    "reason": "NO_LEGAL_CAPTURE_TIMESTAMP",
                }
            )
            continue
        selected_evidence.append(
            max(legal, key=lambda record: (record["captured"], record["prediction_id"]))
        )
    selected_evidence.sort(key=lambda record: (record["kickoff"], record["match_key"]))

    competition_metadata = _load_competition_metadata(
        jobs_root,
        {record["match_id"] for record in selected_evidence if record["match_id"]},
    )
    observations: list[dict[str, Any]] = []
    prediction_failures: list[dict[str, Any]] = []
    for evidence in selected_evidence:
        match_key = evidence["match_key"]
        result = result_map.get(match_key)
        if result is None or result["score"] is None:
            failure = {
                "kind": "COHORT_RESULT",
                "prediction_id": evidence["prediction_id"],
                "match_key": match_key,
                "reason": "STRICT_RESULT_UNAVAILABLE",
            }
            failures.append(failure)
            prediction_failures.append(failure)
            continue
        try:
            frozen = _load_frozen_prediction(
                prediction_root,
                evidence["prediction_id"],
                match_key,
                evidence["kickoff"],
            )
            home_history = _subject_history(
                evidence["home_rows"],
                subject_id=evidence["home_subject_team_id"],
                target_kickoff=evidence["kickoff"],
                side_label="home",
            )
            away_history = _subject_history(
                evidence["away_rows"],
                subject_id=evidence["away_subject_team_id"],
                target_kickoff=evidence["kickoff"],
                side_label="away",
            )
            form_proxies = {
                "E0": _form_proxy(home_history, away_history, None),
                **{
                    f"E{half_life}": _form_proxy(
                        home_history, away_history, half_life
                    )
                    for half_life in HALF_LIVES
                },
            }
            base = form_proxies["E0"]
            home_form_e0 = _finite(base["home_form_proxy"])
            away_form_e0 = _finite(base["away_form_proxy"])
            if home_form_e0 is None or home_form_e0 <= 0:
                raise ValueError("home E0 form proxy denominator is non-positive or non-finite")
            if away_form_e0 is None or away_form_e0 <= 0:
                raise ValueError("away E0 form proxy denominator is non-positive or non-finite")

            ratios: dict[str, dict[str, float]] = {}
            variant_models: dict[str, tuple[float, float, float]] = {
                "CHAMPION": (
                    frozen["lambda_home"],
                    frozen["lambda_away"],
                    frozen["rho"],
                )
            }
            for variant in VARIANTS:
                home_ratio = _ratio(
                    form_proxies[variant]["home_form_proxy"],
                    home_form_e0,
                    f"{variant} home",
                )
                away_ratio = _ratio(
                    form_proxies[variant]["away_form_proxy"],
                    away_form_e0,
                    f"{variant} away",
                )
                ratios[variant] = {"home_ratio": home_ratio, "away_ratio": away_ratio}
                lambda_home = frozen["lambda_home"] * home_ratio
                lambda_away = frozen["lambda_away"] * away_ratio
                if not math.isfinite(lambda_home) or not math.isfinite(lambda_away):
                    raise ValueError(f"{variant} challenger lambda is non-finite")
                if lambda_home <= 0 or lambda_away <= 0:
                    raise ValueError(f"{variant} challenger lambda is non-positive")
                variant_models[variant] = (lambda_home, lambda_away, frozen["rho"])

            actual_home, actual_away = result["score"]
            variant_outputs = {
                variant: _variant_observation(
                    actual_home=actual_home,
                    actual_away=actual_away,
                    lambda_home=model[0],
                    lambda_away=model[1],
                    rho=model[2],
                )
                for variant, model in variant_models.items()
            }
            metadata = competition_metadata.get(evidence["match_id"], {})
            competition = metadata.get("competition")
            observation = {
                "match_key": match_key,
                "prediction_id": evidence["prediction_id"],
                "match_id": evidence["match_id"],
                "kickoff": evidence["kickoff"],
                "evidence_captured_at": evidence["captured"],
                "actual_home": actual_home,
                "actual_away": actual_away,
                "actual_total": actual_home + actual_away,
                "competition": competition,
                "competition_candidates": metadata.get("candidates") or [],
                "competition_metadata_status": metadata.get("metadata_status", "MISSING"),
                "universe": classify_competition(competition),
                "home_subject_team_id": evidence["home_subject_team_id"],
                "away_subject_team_id": evidence["away_subject_team_id"],
                "home_identity_share": evidence["home_identity_share"],
                "away_identity_share": evidence["away_identity_share"],
                "home_history_n": len(home_history),
                "away_history_n": len(away_history),
                "form_proxy_e0_home": home_form_e0,
                "form_proxy_e0_away": away_form_e0,
                "form_proxy_e0_total": home_form_e0 + away_form_e0,
                "form_proxies": form_proxies,
                "ratios": ratios,
                "frozen_champion": frozen,
                "variants": variant_outputs,
            }
            observations.append(observation)
        except (ValueError, KeyError, TypeError) as exc:
            failure = {
                "kind": "COHORT_OBSERVATION",
                "prediction_id": evidence["prediction_id"],
                "match_key": match_key,
                "reason": str(exc),
            }
            failures.append(failure)
            prediction_failures.append(failure)

    observations.sort(key=lambda row: (row["kickoff"], row["match_key"]))
    evaluated_match_keys = {row["match_key"] for row in observations}
    global_e120_delta = None
    if observations:
        champion_metrics = _aggregate_metrics(observations, "CHAMPION")
        e120_metrics = _aggregate_metrics(observations, "E120")
        if champion_metrics["exact_score_nll"] is not None and e120_metrics["exact_score_nll"] is not None:
            global_e120_delta = e120_metrics["exact_score_nll"] - champion_metrics["exact_score_nll"]

    variant_summaries: dict[str, dict[str, Any]] = {}
    for variant in ("CHAMPION", *VARIANTS):
        summary = {
            "metrics": _aggregate_metrics(observations, variant),
        }
        if variant != "CHAMPION":
            champion_metrics = _aggregate_metrics(observations, "CHAMPION")
            metric_deltas = {
                metric: (
                    summary["metrics"][metric] - champion_metrics[metric]
                    if summary["metrics"][metric] is not None and champion_metrics[metric] is not None
                    else None
                )
                for metric in METRICS
            }
            summary["metric_deltas_vs_champion"] = metric_deltas
            bootstrap_seed = _stable_seed(BOOTSTRAP_SEED, variant)
            summary["paired_bootstrap"] = _paired_bootstrap(
                observations,
                variant,
                seed=bootstrap_seed,
                replicates=bootstrap_replicates,
            )
            summary["ratio_distribution"] = {
                "home_ratio": _distribution(
                    row["ratios"][variant]["home_ratio"] for row in observations
                ),
                "away_ratio": _distribution(
                    row["ratios"][variant]["away_ratio"] for row in observations
                ),
            }
        variant_summaries[variant] = summary

    universe_rows = {
        universe: [row for row in observations if row["universe"] == universe]
        for universe in UNIVERSES
    }
    universe_summaries = [
        _scope_summary(universe_rows[universe], universe, global_e120_delta)
        for universe in UNIVERSES
    ]
    chronology_summaries = _chronology_thirds(observations, global_e120_delta)

    e120_metrics = variant_summaries["E120"]["metrics"]
    champion_metrics = variant_summaries["CHAMPION"]["metrics"]
    e120_deltas = variant_summaries["E120"].get("metric_deltas_vs_champion", {})
    sensitivity_nll = {
        variant: (
            variant_summaries[variant]["metrics"]["exact_score_nll"]
            < champion_metrics["exact_score_nll"]
            if variant_summaries[variant]["metrics"]["exact_score_nll"] is not None
            and champion_metrics["exact_score_nll"] is not None
            else False
        )
        for variant in ("E60", "E240")
    }
    secondary_brier_metrics = ("one_x_two_brier", "ou_2_5_brier", "btts_brier")
    secondary_non_worse_count = sum(
        1
        for metric in secondary_brier_metrics
        if e120_metrics[metric] is not None
        and champion_metrics[metric] is not None
        and e120_metrics[metric] <= champion_metrics[metric] + 1e-12
    )
    primary_bootstrap = (
        variant_summaries["E120"].get("paired_bootstrap", {}).get("exact_score_nll")
    )
    ci = (primary_bootstrap or {}).get("bootstrap_ci_95") or [None, None]
    ci_entirely_below_zero = ci[1] is not None and ci[1] < 0
    primary_nll_improved = bool(
        e120_metrics["exact_score_nll"] is not None
        and champion_metrics["exact_score_nll"] is not None
        and e120_metrics["exact_score_nll"] < champion_metrics["exact_score_nll"]
    )
    actual_probability_non_lower = bool(
        e120_metrics["actual_score_mean_probability"] is not None
        and champion_metrics["actual_score_mean_probability"] is not None
        and e120_metrics["actual_score_mean_probability"]
        >= champion_metrics["actual_score_mean_probability"] - 1e-12
    )
    top3_non_lower = bool(
        e120_metrics["top3_accuracy"] is not None
        and champion_metrics["top3_accuracy"] is not None
        and e120_metrics["top3_accuracy"] >= champion_metrics["top3_accuracy"] - 1e-12
    )
    sensitivity_support = any(sensitivity_nll.values())
    secondary_gate = secondary_non_worse_count >= 2
    evaluated_n = len(evaluated_match_keys)
    threshold_passed = evaluated_n >= MIN_EVALUABLE_UNIQUE_MATCHES
    critical_failure = bool(failures)

    if critical_failure:
        decision = "FAIL_CLOSED"
        status = "FAIL_CLOSED"
    elif not threshold_passed:
        decision = "SAMPLE_INSUFFICIENT"
        status = "SAMPLE_INSUFFICIENT"
    elif not primary_nll_improved or not actual_probability_non_lower or not top3_non_lower or not sensitivity_support:
        decision = "REJECTED"
        status = "DECIDED"
    elif secondary_gate and ci_entirely_below_zero:
        decision = "STRONG_OFFLINE_SURVIVOR"
        status = "DECIDED"
    elif secondary_gate:
        decision = "OFFLINE_SURVIVOR"
        status = "DECIDED"
    else:
        decision = "INCONCLUSIVE"
        status = "DECIDED"

    decision_evidence = {
        "evaluated_unique_matches": evaluated_n,
        "minimum_evaluable_unique_matches": MIN_EVALUABLE_UNIQUE_MATCHES,
        "threshold_passed": threshold_passed,
        "E120_exact_score_nll_improved": primary_nll_improved,
        "E120_actual_score_mean_probability_non_lower": actual_probability_non_lower,
        "E120_top3_non_lower": top3_non_lower,
        "secondary_non_worse_count": secondary_non_worse_count,
        "secondary_non_worse_required": 2,
        "secondary_brier_metrics": list(secondary_brier_metrics),
        "E60_or_E240_exact_score_nll_improved": sensitivity_support,
        "sensitivity_nll": sensitivity_nll,
        "E120_paired_nll_bootstrap_ci_95": ci,
        "E120_paired_nll_ci_entirely_below_zero": ci_entirely_below_zero,
        "paired_delta_sign_convention": "variant_minus_champion; lower exact-score NLL is better",
    }

    reconciliation = {
        "one_match_one_observation": len(evaluated_match_keys) == len(observations),
        "strict_settled_prediction_snapshots": len(strict_settled_ids),
        "strict_settled_unique_matches": len(by_match_key),
        "selected_latest_legal_unique_matches": len(selected_evidence),
        "evaluated_unique_matches": evaluated_n,
        "selected_prediction_ids": [row["prediction_id"] for row in selected_evidence],
        "selected_match_keys": [row["match_key"] for row in selected_evidence],
        "selection_rule": "latest evidence_captured_at among legal prematch snapshots per match_key; tie-break prediction_id",
        "result_selection_not_used_for_snapshot_choice": True,
    }

    summary = {
        "schema_version": "dynamic_recency_structural_signal_audit.v1",
        "milestone": MILESTONE,
        "status": status,
        "decision": decision,
        "source": {
            "accepted_cohort_reference": {
                "pull_request": 158,
                "accepted_head": "b0511d035bbfa02ab7c8bf10441aecba7252bb6a",
                "settlement_contract": "strict prematch evidence joined to authoritative 90m result by match_key",
            },
            "champion_model_family": CHAMPION_MODEL_FAMILY,
            "champion_prediction_root": _display_path(prediction_root),
            "prospective_evidence_root": _display_path(evidence_root),
            "authoritative_result_root": _display_path(result_root),
            "competition_metadata_root": _display_path(jobs_root),
            "settlement_scope": RESULT_SCOPE,
            "settlement_truth": "authoritative result.match_key joined to evidence.match_key",
            "postmatch_reviews_used": False,
            "provider_added": False,
        },
        "settlement_gate": {
            "evidence_files": evidence_file_count,
            "usable_prematch_evidence_snapshots": sum(
                1 for record in evidence_records.values() if record["usable"]
            ),
            "authoritative_result_files": result_file_count,
            "strict_valid_authoritative_results": len(result_map),
            "strict_settled_usable_prediction_snapshots": len(strict_settled_ids),
            "strict_settled_usable_unique_matches": len(by_match_key),
            "scope_required": RESULT_SCOPE,
            "result_90m_required": True,
            "verified_at_required_after_kickoff": True,
            "failure_reasons": dict(sorted(result_failures.items())),
            "settlement_rejection_reasons": dict(sorted(settlement_rejection_reasons.items())),
            "rejected_authoritative_records": rejected_results,
        },
        "cohort": {
            **reconciliation,
            "latest_legal_snapshot_prediction_count": len(selected_evidence),
            "latest_legal_snapshot_unique_match_count": len(selected_evidence),
            "match_keys": sorted(evaluated_match_keys),
            "one_match_equals_one_observation": len(evaluated_match_keys) == len(observations),
            "integrity_gate": "same PR #158 structural evidence integrity: prematch capture/cutoff, >=10 valid rows per team, >=80% subject identity, no identity collision",
        },
        "frozen_prediction_integrity": {
            "validated_count": len(observations),
            "failed_count": len(prediction_failures),
            "failures": prediction_failures,
            "rho_values": sorted({round(row["frozen_champion"]["rho"], 12) for row in observations}),
            "baseline_source": "frozen lambda_home/lambda_away/rho from data/model_governance/predictions/{prediction_id}.json",
        },
        "recency": {
            "E0": "equal-weight form proxy; scale denominator only",
            "half_lives_days": {f"E{half_life}": half_life for half_life in HALF_LIVES},
            "weight_formula": "exp(-ln(2) * days_before_target_kickoff / half_life_days)",
            "days_definition": "target kickoff calendar date minus historical match_date; evidence has date-only history rows",
            "clipping_or_ratio_tuning": False,
            "actual_used_to_choose_half_life": False,
        },
        "variants": variant_summaries,
        "paired_deltas": {
            variant: variant_summaries[variant].get("paired_bootstrap", {}) for variant in VARIANTS
        },
        "primary_paired_bootstrap": {
            "variant": "E120",
            "metric": "exact_score_nll",
            **(primary_bootstrap or {}),
        },
        "ratio_distribution": {
            variant: variant_summaries[variant].get("ratio_distribution", {}) for variant in VARIANTS
        },
        "competition_universe": universe_summaries,
        "chronology_thirds": chronology_summaries,
        "per_match_observations": [_json_safe_observation(row) for row in observations],
        "decision_evidence": decision_evidence,
        "prematch_evidence_failure_reasons": dict(sorted(evidence_failures.items())),
        "pre_registered_decision_rules": {
            "STRONG_OFFLINE_SURVIVOR": [
                "E120 Exact Score NLL < Champion",
                "E120 actual-score mean probability >= Champion",
                "E120 Top3 >= Champion",
                "at least 2 of 1X2 Brier, O/U2.5 Brier, BTTS Brier non-worse",
                "E60 or E240 Exact Score NLL < Champion",
                "E120 paired bootstrap 95% CI for NLL delta entirely < 0",
            ],
            "OFFLINE_SURVIVOR": "all STRONG conditions except the CI condition",
            "INCONCLUSIVE": "E120 NLL improves but robustness or secondary gate is incomplete",
            "REJECTED": "E120 NLL does not improve, actual-score probability declines, Top3 declines, or both sensitivity NLL variants fail",
            "SAMPLE_INSUFFICIENT": f"evaluated unique matches < {MIN_EVALUABLE_UNIQUE_MATCHES}",
        },
        "failures": failures,
        "stop_state": "STOP_AFTER_PREREGISTERED_OFFLINE_DECISION",
        "production_changes": "NO",
        "model_changes": "NO",
        "market_changes": "NO",
        "selector_changes": "NO",
        "rho_changes": "NO",
        "calibration_changes": "NO",
        "provider_changes": "NO",
        "serving_changes": "NO",
        "promotion": "NO",
    }
    return summary


def _fmt(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.6f}"
    return str(value)


def build_report(summary: Mapping[str, Any]) -> str:
    settlement = summary.get("settlement_gate") or {}
    cohort = summary.get("cohort") or {}
    decision_evidence = summary.get("decision_evidence") or {}
    variants = summary.get("variants") or {}
    lines = [
        f"# {summary.get('milestone')}",
        "",
        f"- status: `{summary.get('status')}`",
        f"- final decision: `{summary.get('decision')}`",
        "- research-only offline challenger; no production or model change.",
        "",
        "## Cohort identity",
        "",
        "The cohort is recovered from the accepted strict settlement contract, not from postmatch reviews. Each match contributes one latest legal prematch snapshot.",
        f"- accepted cohort reference: PR #{((summary.get('source') or {}).get('accepted_cohort_reference') or {}).get('pull_request')} at `{((summary.get('source') or {}).get('accepted_cohort_reference') or {}).get('accepted_head')}`",
        f"- strict settled usable snapshots: `{settlement.get('strict_settled_usable_prediction_snapshots')}`",
        f"- strict settled usable unique matches: `{settlement.get('strict_settled_usable_unique_matches')}`",
        f"- latest legal selected unique matches: `{cohort.get('selected_latest_legal_unique_matches')}`",
        f"- evaluated unique matches: `{cohort.get('evaluated_unique_matches')}`",
        f"- one match = one observation: `{cohort.get('one_match_one_observation')}`",
        f"- selection rule: `{cohort.get('selection_rule')}`",
        "",
        "### Selected match keys",
        "",
        ", ".join(f"`{key}`" for key in cohort.get("match_keys", [])) or "-",
        "",
        "## Settlement and frozen baseline gates",
        "",
        f"- evidence files: `{settlement.get('evidence_files')}`",
        f"- usable prematch evidence snapshots: `{settlement.get('usable_prematch_evidence_snapshots')}`",
        f"- authoritative result files: `{settlement.get('authoritative_result_files')}`",
        f"- strict valid authoritative results: `{settlement.get('strict_valid_authoritative_results')}`",
        f"- result scope: `{settlement.get('scope_required')}`",
        f"- postmatch reviews used: `{(summary.get('source') or {}).get('postmatch_reviews_used')}`",
        f"- result failure reasons: `{json.dumps(settlement.get('failure_reasons', {}), ensure_ascii=False, sort_keys=True)}`",
        f"- prematch evidence integrity failure reasons: `{json.dumps(summary.get('prematch_evidence_failure_reasons', {}), ensure_ascii=False, sort_keys=True)}`",
        f"- frozen baseline: `{(summary.get('frozen_prediction_integrity') or {}).get('baseline_source')}`",
        "",
        "## Pre-registered variants",
        "",
        "E0 is an equal-weight form scale denominator only. E60/E120/E240 use the fixed exponential half-lives; no clipping, actual-driven tuning, market change, selector change, or rho change is applied.",
        "",
        "| variant | Exact Score NLL | actual-score mean probability | Top1 | Top3 | Top5 | 1X2 Brier | O/U2.5 Brier | BTTS Brier | total-goal bias | top1 concentration | 1-1 top1 share | mean 1-1 probability |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for variant in ("CHAMPION", "E60", "E120", "E240"):
        metrics = (variants.get(variant) or {}).get("metrics") or {}
        lines.append(
            "| `{}` | {} | {} | {} | {} | {} | {} | {} | {} | {} | {} | {} | {} |".format(
                variant,
                _fmt(metrics.get("exact_score_nll")),
                _fmt(metrics.get("actual_score_mean_probability")),
                _fmt(metrics.get("top1_accuracy")),
                _fmt(metrics.get("top3_accuracy")),
                _fmt(metrics.get("top5_accuracy")),
                _fmt(metrics.get("one_x_two_brier")),
                _fmt(metrics.get("ou_2_5_brier")),
                _fmt(metrics.get("btts_brier")),
                _fmt(metrics.get("total_goal_bias")),
                _fmt(metrics.get("top1_score_concentration_mean_probability")),
                _fmt(metrics.get("top1_score_1_1_share")),
                _fmt(metrics.get("score_1_1_probability_mean")),
            )
        )

    lines.extend(
        [
            "",
            "## Paired differences and bootstrap",
            "",
            "Sign convention: variant minus Champion; lower Exact Score NLL is better. Bootstrap resamples unique match observations with replacement using fixed base seed `20260903`.",
            "",
            "| variant | NLL delta | NLL bootstrap 95% CI | actual-score probability delta | Top3 delta | 1X2/O-U2.5/BTTS non-worse count |",
            "|---|---:|---|---:|---:|---:|",
        ]
    )
    champion_metrics = (variants.get("CHAMPION") or {}).get("metrics") or {}
    for variant in VARIANTS:
        payload = variants.get(variant) or {}
        deltas = payload.get("metric_deltas_vs_champion") or {}
        bootstrap = payload.get("paired_bootstrap") or {}
        nll_bootstrap = bootstrap.get("exact_score_nll") or {}
        non_worse = sum(
            1
            for metric in ("one_x_two_brier", "ou_2_5_brier", "btts_brier")
            if deltas.get(metric) is not None and deltas.get(metric) <= 1e-12
        )
        lines.append(
            f"| `{variant}` | {_fmt(deltas.get('exact_score_nll'))} | {_fmt((nll_bootstrap.get('bootstrap_ci_95') or [None, None])[0])} to {_fmt((nll_bootstrap.get('bootstrap_ci_95') or [None, None])[1])} | {_fmt(deltas.get('actual_score_mean_probability'))} | {_fmt(deltas.get('top3_accuracy'))} | {non_worse} |"
        )
    lines.extend(
        [
            "",
            "### Ratio distributions",
            "",
            "| variant | side | n | mean | p25 | median | p75 | min | max |",
            "|---|---|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    ratio_distribution = summary.get("ratio_distribution") or {}
    for variant in VARIANTS:
        for side in ("home_ratio", "away_ratio"):
            dist = (ratio_distribution.get(variant) or {}).get(side) or {}
            lines.append(
                f"| `{variant}` | `{side}` | {dist.get('count', 0)} | {_fmt(dist.get('mean'))} | {_fmt(dist.get('p25'))} | {_fmt(dist.get('median'))} | {_fmt(dist.get('p75'))} | {_fmt(dist.get('min'))} | {_fmt(dist.get('max'))} |"
            )

    lines.extend(
        [
            "",
            "## Competition-universe guardrail",
            "",
            "Taxonomy is reused without team-name or country inference. `n<20` is descriptive only and does not support a strong conclusion; no universe-specific parameter is fitted.",
            "",
            "| universe | n | status | E120 NLL delta | direction vs global | E120 actual-prob delta | E120 Top3 delta |",
            "|---|---:|---|---:|---|---:|---:|",
        ]
    )
    for scope in summary.get("competition_universe", []) or []:
        e120 = (scope.get("variants", {}).get("E120") or {})
        deltas = e120.get("metric_deltas_vs_champion") or {}
        lines.append(
            f"| `{scope.get('scope')}` | {scope.get('n')} | `{scope.get('sample_status')}` | {_fmt(deltas.get('exact_score_nll'))} | `{(scope.get('directional_guardrail') or {}).get('relative_to_global')}` | {_fmt(deltas.get('actual_score_mean_probability'))} | {_fmt(deltas.get('top3_accuracy'))} |"
        )

    lines.extend(
        [
            "",
            "## Chronological thirds",
            "",
            f"The {cohort.get('evaluated_unique_matches')} match chronology is deterministically sorted by kickoff and split as evenly as possible into earliest/middle/latest thirds.",
            "",
            "| segment | n | actual total mean | E0 form total mean | Champion lambda total mean | E120 lambda total mean | actual-Champion | actual-E120 | E120 NLL delta |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for scope in summary.get("chronology_thirds", []) or []:
        e120_deltas_scope = (scope.get("variants", {}).get("E120") or {}).get("metric_deltas_vs_champion") or {}
        lines.append(
            f"| `{scope.get('scope')}` | {scope.get('n')} | {_fmt(scope.get('actual_total_mean'))} | {_fmt(scope.get('form_total_e0_mean'))} | {_fmt(scope.get('champion_lambda_total_mean'))} | {_fmt(scope.get('e120_lambda_total_mean'))} | {_fmt(scope.get('observed_minus_champion_lambda_total_mean'))} | {_fmt(scope.get('observed_minus_e120_lambda_total_mean'))} | {_fmt(e120_deltas_scope.get('exact_score_nll'))} |"
        )

    lines.extend(
        [
            "",
            "## Pre-registered decision",
            "",
            f"- E120 Exact Score NLL improved: `{decision_evidence.get('E120_exact_score_nll_improved')}`",
            f"- E120 actual-score mean probability non-lower: `{decision_evidence.get('E120_actual_score_mean_probability_non_lower')}`",
            f"- E120 Top3 non-lower: `{decision_evidence.get('E120_top3_non_lower')}`",
            f"- secondary non-worse count: `{decision_evidence.get('secondary_non_worse_count')}` / 3",
            f"- E60/E240 sensitivity NLL support: `{decision_evidence.get('E60_or_E240_exact_score_nll_improved')}`",
            f"- E120 paired NLL CI: `{json.dumps(decision_evidence.get('E120_paired_nll_bootstrap_ci_95'), ensure_ascii=False)}`",
            f"- final decision: `{summary.get('decision')}`",
            "",
            "## Stop state and controls",
            "",
            f"- failures: `{json.dumps(summary.get('failures', []), ensure_ascii=False, sort_keys=True)}`",
            f"- stop_state: `{summary.get('stop_state')}`",
            f"- production_changes: `{summary.get('production_changes')}`",
            f"- model_changes: `{summary.get('model_changes')}`",
            f"- market_changes: `{summary.get('market_changes')}`",
            f"- selector_changes: `{summary.get('selector_changes')}`",
            f"- rho_changes: `{summary.get('rho_changes')}`",
            f"- calibration_changes: `{summary.get('calibration_changes')}`",
            f"- provider_changes: `{summary.get('provider_changes')}`",
            f"- serving_changes: `{summary.get('serving_changes')}`",
            f"- promotion: `{summary.get('promotion')}`",
            "No dynamic attack/defence implementation follows this bounded probe.",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("audit-artifact"),
        help="directory for summary.json and report.md",
    )
    parser.add_argument(
        "--bootstrap-replicates",
        type=int,
        default=DEFAULT_BOOTSTRAP_REPLICATES,
    )
    args = parser.parse_args()
    summary = run(bootstrap_replicates=args.bootstrap_replicates)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (args.output_dir / "report.md").write_text(build_report(summary), encoding="utf-8")
    print(json.dumps({"decision": summary["decision"], "status": summary["status"], "cohort": summary["cohort"]}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
