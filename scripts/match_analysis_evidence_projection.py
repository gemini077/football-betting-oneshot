"""Deterministic analysis-evidence projection from frozen FBOS truth.

This module deliberately has no network, parser, model, serving, or UI
dependencies.  It reads already-frozen prediction, input-snapshot, and
football-evidence objects and returns a new machine-readable projection.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import date, datetime, timedelta, timezone
from statistics import median
from typing import Any


CONTRACT_VERSION = "match_analysis_evidence_projection.v1"
OUTCOMES = ("home", "draw", "away")
SIDES = ("home", "away")
WINDOWS = (5, 10)
LOCAL_TZ = timezone(timedelta(hours=8))
PLACEHOLDER_NAME_RE = re.compile(r"^\{[^{}]+\}\$\d+$", re.IGNORECASE)


def _first(value: Mapping[str, Any] | None, *keys: str) -> Any:
    if not isinstance(value, Mapping):
        return None
    for key in keys:
        candidate = value.get(key)
        if candidate not in (None, ""):
            return candidate
    return None


def _text(value: Any) -> str | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    return text or None


def _canonical_id(value: Any) -> int | str | None:
    if value in (None, "") or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, float):
        if not math.isfinite(value) or value <= 0:
            return None
        return int(value) if value.is_integer() else str(value)
    text = str(value).strip()
    if not text:
        return None
    if text.isdigit():
        number = int(text)
        return number if number > 0 else None
    return text


def _id_key(value: Any) -> str | None:
    canonical = _canonical_id(value)
    return str(canonical) if canonical is not None else None


def _all_ids(value: Mapping[str, Any] | None, *keys: str) -> list[int | str]:
    result: list[int | str] = []
    seen: set[str] = set()
    for key in keys:
        identifier = _canonical_id(value.get(key)) if isinstance(value, Mapping) else None
        key_value = _id_key(identifier)
        if identifier is not None and key_value not in seen:
            result.append(identifier)
            seen.add(key_value or "")
    return result


def _number(value: Any) -> float | None:
    if value in (None, "") or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _nonnegative_integer(value: Any) -> int | None:
    number = _number(value)
    if number is None or number < 0 or not number.is_integer():
        return None
    return int(number)


def _round(value: float | None) -> float | None:
    return round(value, 6) if value is not None else None


def _parse_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = _text(value)
    if not text:
        return None
    if re.match(r"^\d{2}-\d{2}-\d{2}(?:\s|$)", text):
        year, month, day = (int(part) for part in text[:8].split("-"))
        try:
            return date(2000 + year, month, day)
        except ValueError:
            return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%d-%m-%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(text[:10], fmt).date()
        except ValueError:
            continue
    return None


def _parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    else:
        text = _text(value)
        if not text:
            return None
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            parsed = None
        if parsed is None:
            for fmt in ("%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M"):
                try:
                    parsed = datetime.strptime(text, fmt)
                    break
                except ValueError:
                    continue
        if parsed is None:
            return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=LOCAL_TZ)
    return parsed


def _date_from_row(row: Mapping[str, Any]) -> date | None:
    return _parse_date(_first(row, "match_date", "source_date", "date", "kickoff"))


def _substantive_name(value: Any) -> str | None:
    text = _text(value)
    if not text or PLACEHOLDER_NAME_RE.fullmatch(text):
        return None
    if text in {"?", "-", "--", "N/A", "未知", "待定"}:
        return None
    if not any(character.isalnum() or "\u4e00" <= character <= "\u9fff" for character in text):
        return None
    return text


def _fixture_id(row: Mapping[str, Any]) -> int | str | None:
    return _canonical_id(
        _first(
            row,
            "source_fixture_id",
            "provider_match_id",
            "source_match_id",
            "match_id",
            "matchId",
            "fixture_id",
        )
    )


def _team_id(row: Mapping[str, Any], side: str) -> int | str | None:
    return _canonical_id(
        _first(row, f"{side}_team_id", f"{side}_id", f"{side}TeamId")
    )


def _team_name(row: Mapping[str, Any], side: str) -> str | None:
    return _substantive_name(
        _first(row, f"{side}_team_name", f"{side}_team", f"{side}Team")
    )


def _score(row: Mapping[str, Any]) -> tuple[int | None, int | None]:
    return (
        _nonnegative_integer(
            _first(row, "home_goals_90m", "home_score_90m", "home_goals")
        ),
        _nonnegative_integer(
            _first(row, "away_goals_90m", "away_score_90m", "away_goals")
        ),
    )


def _target_kickoff(
    prediction: Mapping[str, Any],
    target: Mapping[str, Any],
    fixture: Mapping[str, Any],
) -> datetime | None:
    value = _first(prediction, "kickoff_at", "kickoff", "match_datetime")
    value = value or _first(target, "kickoff_at", "kickoff")
    if value is None:
        match_date = _first(fixture, "matchDate", "match_date", "date")
        match_time = _first(fixture, "matchTime", "match_time", "time")
        if match_date and match_time:
            value = f"{match_date}T{match_time}:00+08:00"
    return _parse_datetime(value)


def _source_snapshot(input_snapshot: Mapping[str, Any]) -> Mapping[str, Any] | None:
    input_value = input_snapshot.get("input")
    input_mapping = input_value if isinstance(input_value, Mapping) else input_snapshot
    sources = input_mapping.get("source_snapshots")
    if not isinstance(sources, Mapping):
        return None
    nowscore = sources.get("nowscore")
    if not isinstance(nowscore, Mapping):
        return None
    snapshots = nowscore.get("snapshots")
    if not isinstance(snapshots, Sequence) or isinstance(snapshots, (str, bytes)):
        return None
    return next((item for item in snapshots if isinstance(item, Mapping)), None)


def _panlu_matches(
    input_snapshot: Mapping[str, Any], football_evidence: Mapping[str, Any]
) -> list[Mapping[str, Any]]:
    snapshot = _source_snapshot(input_snapshot)
    context = snapshot.get("nowscore_context") if isinstance(snapshot, Mapping) else None
    if not isinstance(context, Mapping):
        context = snapshot.get("context") if isinstance(snapshot, Mapping) else None
    panlu = context.get("panlu") if isinstance(context, Mapping) else None
    matches = panlu.get("matches") if isinstance(panlu, Mapping) else None
    if isinstance(matches, list):
        return [item for item in matches if isinstance(item, Mapping)]

    evidence = football_evidence.get("prematch_evidence")
    fields = evidence.get("fields") if isinstance(evidence, Mapping) else None
    panlu_field = fields.get("panlu") if isinstance(fields, Mapping) else None
    value = panlu_field.get("value") if isinstance(panlu_field, Mapping) else None
    matches = value.get("matches") if isinstance(value, Mapping) else None
    return [item for item in matches if isinstance(item, Mapping)] if isinstance(matches, list) else []


def _market_context(
    input_snapshot: Mapping[str, Any], football_evidence: Mapping[str, Any]
) -> Mapping[str, Any] | None:
    evidence = football_evidence.get("prematch_evidence")
    fields = evidence.get("fields") if isinstance(evidence, Mapping) else None
    market_field = fields.get("market_context") if isinstance(fields, Mapping) else None
    if isinstance(market_field, Mapping) and market_field.get("state") == "PRESENT":
        value = market_field.get("value")
        if isinstance(value, Mapping):
            return value

    snapshot = _source_snapshot(input_snapshot)
    if isinstance(snapshot, Mapping):
        value = snapshot.get("market_context")
        if isinstance(value, Mapping):
            return value
    return None


def _market_quote(bookmaker: Mapping[str, Any], phase: str) -> Mapping[str, Any] | None:
    keys = ("spf_open", "open") if phase == "open" else ("spf_current", "current")
    value = _first(bookmaker, *keys)
    return value if isinstance(value, Mapping) else None


def _de_vig(quote: Mapping[str, Any] | None) -> tuple[dict[str, float] | None, str | None]:
    if not isinstance(quote, Mapping):
        return None, "MISSING_ODDS"
    odds: dict[str, float] = {}
    for outcome in OUTCOMES:
        value = _number(quote.get(outcome))
        if value is None or value <= 1.0:
            return None, f"INVALID_{outcome.upper()}_ODDS"
        odds[outcome] = value
    implied = {outcome: 1.0 / odds[outcome] for outcome in OUTCOMES}
    total = sum(implied.values())
    if not math.isfinite(total) or total <= 0:
        return None, "INVALID_IMPLIED_SUM"
    return {outcome: implied[outcome] / total for outcome in OUTCOMES}, None


def _quartiles(values: Sequence[float]) -> tuple[float, float, float]:
    ordered = sorted(values)
    if not ordered:
        raise ValueError("quartiles require values")

    def percentile(fraction: float) -> float:
        if len(ordered) == 1:
            return ordered[0]
        position = (len(ordered) - 1) * fraction
        lower = math.floor(position)
        upper = math.ceil(position)
        if lower == upper:
            return ordered[lower]
        weight = position - lower
        return ordered[lower] + (ordered[upper] - ordered[lower]) * weight

    q1, q3 = percentile(0.25), percentile(0.75)
    return _round(q1) or 0.0, _round(q3) or 0.0, _round(q3 - q1) or 0.0


def build_market_1x2_chronology(market_context: Mapping[str, Any] | None) -> dict[str, Any]:
    """Return neutral open/current 1X2 chronology and deterministic dispersion."""

    bookmakers = market_context.get("bookmakers") if isinstance(market_context, Mapping) else None
    rows = [item for item in bookmakers if isinstance(item, Mapping)] if isinstance(bookmakers, list) else []
    valid: list[dict[str, Any]] = []
    opening_values: dict[str, list[float]] = {outcome: [] for outcome in OUTCOMES}
    current_values: dict[str, list[float]] = {outcome: [] for outcome in OUTCOMES}
    rejected: list[dict[str, Any]] = []
    open_count = 0
    current_count = 0
    for index, bookmaker in enumerate(rows):
        opening, opening_reason = _de_vig(_market_quote(bookmaker, "open"))
        current, current_reason = _de_vig(_market_quote(bookmaker, "current"))
        if opening is not None:
            open_count += 1
        if current is not None:
            current_count += 1
        if opening is None or current is None:
            reasons = []
            if opening_reason:
                reasons.append(f"OPEN_{opening_reason}" if not opening_reason.startswith("OPEN_") else opening_reason)
            if current_reason:
                reasons.append(f"CURRENT_{current_reason}" if not current_reason.startswith("CURRENT_") else current_reason)
            rejected.append(
                {
                    "index": index,
                    "name": _text(_first(bookmaker, "name", "bookmaker")),
                    "reasons": reasons,
                }
            )
            continue
        delta = {outcome: current[outcome] - opening[outcome] for outcome in OUTCOMES}
        for outcome in OUTCOMES:
            opening_values[outcome].append(opening[outcome])
            current_values[outcome].append(current[outcome])
        valid.append(
            {
                "index": index,
                "name": _text(_first(bookmaker, "name", "bookmaker")),
                "cid": _canonical_id(_first(bookmaker, "cid")),
                "source_company_id": _canonical_id(_first(bookmaker, "source_company_id")),
                "opening_de_vig_probability": {outcome: _round(opening[outcome]) for outcome in OUTCOMES},
                "current_de_vig_probability": {outcome: _round(current[outcome]) for outcome in OUTCOMES},
                "delta_probability_points": {
                    outcome: _round(delta[outcome] * 100.0) for outcome in OUTCOMES
                },
                "movement_direction": {
                    outcome: "UP" if delta[outcome] > 0 else "DOWN" if delta[outcome] < 0 else "FLAT"
                    for outcome in OUTCOMES
                },
            }
        )

    result: dict[str, Any] = {
        "status": "AVAILABLE" if valid else "OMITTED",
        "reason": "VALID_OPEN_CURRENT_1X2_PAIRS" if valid else "NO_VALID_OPEN_CURRENT_1X2_PAIRS",
        "bookmaker_count": len(rows),
        "valid_open_bookmaker_count": open_count,
        "valid_current_bookmaker_count": current_count,
        "valid_book_count": len(valid),
        "rejected_bookmaker_count": len(rejected),
        "rejected_bookmakers": rejected,
        "bookmakers": valid,
        "median_opening_probability": None,
        "median_current_probability": None,
        "delta_probability_points": None,
        "movement_direction_counts": None,
        "dispersion_iqr": None,
    }
    if not valid:
        return result

    opening_medians = {
        outcome: _round(
            float(median(opening_values[outcome]))
        )
        for outcome in OUTCOMES
    }
    current_medians = {
        outcome: _round(
            float(median(current_values[outcome]))
        )
        for outcome in OUTCOMES
    }
    directions: dict[str, dict[str, int | float]] = {}
    dispersion: dict[str, dict[str, float]] = {}
    for outcome in OUTCOMES:
        counts = Counter(row["movement_direction"][outcome] for row in valid)
        total = len(valid)
        directions[outcome] = {
            "up_count": counts.get("UP", 0),
            "down_count": counts.get("DOWN", 0),
            "flat_count": counts.get("FLAT", 0),
            "up_share": _round(counts.get("UP", 0) / total),
            "down_share": _round(counts.get("DOWN", 0) / total),
            "flat_share": _round(counts.get("FLAT", 0) / total),
        }
        open_q1, open_q3, open_iqr = _quartiles(
            opening_values[outcome]
        )
        current_q1, current_q3, current_iqr = _quartiles(
            current_values[outcome]
        )
        dispersion[outcome] = {
            "opening_q1": open_q1,
            "opening_q3": open_q3,
            "opening_iqr": open_iqr,
            "current_q1": current_q1,
            "current_q3": current_q3,
            "current_iqr": current_iqr,
        }
    result.update(
        {
            "median_opening_probability": opening_medians,
            "median_current_probability": current_medians,
            "delta_probability_points": {
                outcome: _round((current_medians[outcome] - opening_medians[outcome]) * 100.0)
                for outcome in OUTCOMES
            },
            "movement_direction_counts": directions,
            "dispersion_iqr": dispersion,
        }
    )
    return result


def _exact_opponent_name(
    row: Mapping[str, Any], panlu: Sequence[Mapping[str, Any]], target_team_id: Any
) -> tuple[str | None, str, dict[str, bool]]:
    row_fixture = _fixture_id(row)
    row_home, row_away = _team_id(row, "home"), _team_id(row, "away")
    row_date = _date_from_row(row)
    checks = {"fixture_id": False, "team_ids": False, "match_date": False, "orientation": False}
    if row_fixture is None:
        return None, "MISSING_SOURCE_FIXTURE_ID", checks
    if row_home is None or row_away is None:
        return None, "MISSING_HISTORY_TEAM_ID", checks
    if row_date is None:
        return None, "MISSING_HISTORY_MATCH_DATE", checks

    fixture_matches = [candidate for candidate in panlu if _id_key(_fixture_id(candidate)) == _id_key(row_fixture)]
    if len(fixture_matches) == 0:
        return None, "PANLU_FIXTURE_ID_NOT_FOUND", checks
    if len(fixture_matches) > 1:
        return None, "AMBIGUOUS_PANLU_FIXTURE_ID", checks
    candidate = fixture_matches[0]
    checks["fixture_id"] = True
    panlu_home, panlu_away = _team_id(candidate, "home"), _team_id(candidate, "away")
    if panlu_home is None or panlu_away is None:
        return None, "MISSING_PANLU_TEAM_ID", checks
    if _id_key(row_home) != _id_key(panlu_home) or _id_key(row_away) != _id_key(panlu_away):
        if _id_key(row_home) == _id_key(panlu_away) and _id_key(row_away) == _id_key(panlu_home):
            return None, "ORIENTATION_MISMATCH", checks
        return None, "TEAM_ID_MISMATCH", checks
    checks["team_ids"] = True
    panlu_date = _date_from_row(candidate)
    if panlu_date is None:
        kickoff = _first(candidate, "kickoff", "kickoff_at", "date")
        panlu_date = _parse_date(kickoff)
    if panlu_date is None:
        return None, "MISSING_PANLU_MATCH_DATE", checks
    if panlu_date != row_date:
        return None, "DATE_MISMATCH", checks
    checks["match_date"] = True
    target_id = _id_key(target_team_id)
    if target_id == _id_key(panlu_home):
        opponent_name = _team_name(candidate, "away")
    elif target_id == _id_key(panlu_away):
        opponent_name = _team_name(candidate, "home")
    else:
        return None, "ORIENTATION_MISMATCH", checks
    checks["orientation"] = True
    if opponent_name is None:
        raw_name = _first(candidate, "away_team", "away_team_name", "awayTeam") if target_id == _id_key(panlu_home) else _first(candidate, "home_team", "home_team_name", "homeTeam")
        if PLACEHOLDER_NAME_RE.fullmatch(str(raw_name or "").strip()):
            return None, "PANLU_OPPONENT_NAME_PLACEHOLDER", checks
        return None, "PANLU_OPPONENT_NAME_NOT_SUBSTANTIVE", checks
    return opponent_name, "EXACT_CORROBORATION", checks


def _history_row_projection(
    row: Mapping[str, Any],
    *,
    target_team_id: Any,
    panlu: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, Any] | None, str | None]:
    subject_id = _canonical_id(_first(row, "subject_team_id"))
    if subject_id is None or _id_key(subject_id) != _id_key(target_team_id):
        return None, "SUBJECT_IDENTITY_MISMATCH"
    if _text(row.get("subject_identity_status")) not in {None, "RESOLVED"}:
        return None, "SUBJECT_IDENTITY_NOT_RESOLVED"
    match_date = _date_from_row(row)
    home_score, away_score = _score(row)
    if match_date is None:
        return None, "MISSING_HISTORY_MATCH_DATE"
    if home_score is None or away_score is None:
        return None, "MISSING_90M_SCORE"
    venue = _text(row.get("subject_venue"))
    if venue not in {"home", "away"}:
        return None, "MISSING_SUBJECT_VENUE"
    opponent_name, opponent_status, checks = _exact_opponent_name(row, panlu, target_team_id)
    subject_score = home_score if venue == "home" else away_score
    opponent_score = away_score if venue == "home" else home_score
    projected = {
        "source_fixture_id": _fixture_id(row),
        "provider_match_id": _fixture_id(row),
        "subject_team_id": subject_id,
        "opponent_team_id": _canonical_id(_first(row, "opponent_team_id")),
        "subject_venue": venue,
        "match_date": match_date.isoformat(),
        "score_90m": {"home": home_score, "away": away_score},
        "subject_score_90m": subject_score,
        "opponent_score_90m": opponent_score,
        "subject_result": "W" if subject_score > opponent_score else "D" if subject_score == opponent_score else "L",
        "competition": {
            "raw_label": _text(_first(row, "raw_competition_label", "competition", "league")),
            "normalized_label": _text(row.get("normalized_competition_label")),
            "class": _text(row.get("normalized_competition_class")),
            "resolution_status": _text(row.get("competition_resolution_status")),
        },
        "opponent_display_name": opponent_name,
        "opponent_name_resolution": {
            "status": "RESOLVED" if opponent_name else "REJECTED",
            "reason": opponent_status,
            "exact_checks": checks,
        },
        "provenance": {
            "source_provider": _text(row.get("source_provider")),
            "source_reference": _text(_first(row, "source_reference", "source_record_ref")),
            "source_cutoff_at": _text(row.get("source_cutoff_at")),
            "score_semantics": _text(row.get("score_semantics")) or "SOURCE_HISTORICAL_90M_EVIDENCE",
        },
    }
    return projected, None


def _history_stats(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {"status": "OMITTED", "reason": "NO_ACCEPTED_HISTORY_ROWS", "sample_size": 0}
    sample_size = len(rows)
    wins = sum(row["subject_result"] == "W" for row in rows)
    draws = sum(row["subject_result"] == "D" for row in rows)
    losses = sum(row["subject_result"] == "L" for row in rows)
    gf = sum(int(row["subject_score_90m"]) for row in rows)
    ga = sum(int(row["opponent_score_90m"]) for row in rows)
    scored = sum(row["subject_score_90m"] > 0 for row in rows)
    conceded = sum(row["opponent_score_90m"] > 0 for row in rows)
    clean_sheets = sum(row["opponent_score_90m"] == 0 for row in rows)
    btts = sum(row["subject_score_90m"] > 0 and row["opponent_score_90m"] > 0 for row in rows)
    over_25 = sum(row["subject_score_90m"] + row["opponent_score_90m"] > 2.5 for row in rows)
    over_35 = sum(row["subject_score_90m"] + row["opponent_score_90m"] > 3.5 for row in rows)
    return {
        "status": "AVAILABLE",
        "sample_size": sample_size,
        "wdl": {"wins": wins, "draws": draws, "losses": losses},
        "goals_for": gf,
        "goals_against": ga,
        "scored_count": scored,
        "scored_rate": _round(scored / sample_size),
        "conceded_count": conceded,
        "conceded_rate": _round(conceded / sample_size),
        "clean_sheet_count": clean_sheets,
        "clean_sheet_rate": _round(clean_sheets / sample_size),
        "btts_count": btts,
        "btts_rate": _round(btts / sample_size),
        "over_2_5_count": over_25,
        "over_2_5_rate": _round(over_25 / sample_size),
        "over_3_5_count": over_35,
        "over_3_5_rate": _round(over_35 / sample_size),
        "average_total_goals": _round((gf + ga) / sample_size),
    }


def _recent_side_projection(
    rows: Sequence[Mapping[str, Any]],
    *,
    target_kickoff: datetime | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    ordered = list(rows)
    windows = {f"last{size}": _history_stats(ordered[:size]) for size in WINDOWS}
    venue_split = {
        venue: _history_stats([row for row in ordered if row["subject_venue"] == venue])
        for venue in SIDES
    }
    competition_labels = Counter(
        row["competition"]["normalized_label"]
        for row in ordered
        if row["competition"].get("resolution_status") == "RESOLVED"
        and row["competition"].get("normalized_label")
    )
    competition_classes = Counter(
        row["competition"]["class"]
        for row in ordered
        if row["competition"].get("resolution_status") == "RESOLVED"
        and row["competition"].get("class")
    )
    recent_date = _parse_date(ordered[0]["match_date"]) if ordered else None
    days_since = (target_kickoff.date() - recent_date).days if target_kickoff and recent_date else None
    density = {"matches_last_7_days": None, "matches_last_14_days": None}
    if target_kickoff:
        ages = [(target_kickoff.date() - _parse_date(row["match_date"])).days for row in ordered]
        density = {
            "matches_last_7_days": sum(0 < age <= 7 for age in ages),
            "matches_last_14_days": sum(0 < age <= 14 for age in ages),
        }
    coverage = {
        "accepted_history_row_count": len(ordered),
        "source_fixture_id_count": sum(row.get("source_fixture_id") is not None for row in ordered),
        "team_id_count": sum(row.get("subject_team_id") is not None and row.get("opponent_team_id") is not None for row in ordered),
        "subject_identity_resolved_count": len(ordered),
        "competition_resolved_count": sum(row["competition"].get("resolution_status") == "RESOLVED" for row in ordered),
        "opponent_name_candidate_count": len(ordered),
        "opponent_name_resolved_count": sum(bool(row.get("opponent_display_name")) for row in ordered),
        "opponent_name_reject_counts": dict(
            sorted(
                Counter(
                    row["opponent_name_resolution"]["reason"]
                    for row in ordered
                    if not row.get("opponent_display_name")
                ).items()
            )
        ),
    }
    return (
        {
            "history_row_count": len(ordered),
            "windows": windows,
            "venue_split": venue_split,
            "days_since_previous_match": days_since,
            "schedule_density": density,
            "competition_mix": {
                "resolved_label_counts": dict(sorted(competition_labels.items())),
                "resolved_class_counts": dict(sorted(competition_classes.items())),
                "resolved_row_count": coverage["competition_resolved_count"],
                "unresolved_row_count": len(ordered) - coverage["competition_resolved_count"],
            },
            "sequence": ordered[:10],
        },
        coverage,
    )


def _history_projection(
    state_memory: Mapping[str, Any],
    *,
    target: Mapping[str, Any],
    target_kickoff: datetime | None,
    panlu: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
    history = state_memory.get("history")
    if not isinstance(history, Mapping):
        empty = {side: {"history_row_count": 0} for side in SIDES}
        return empty, {side: {"raw_row_count": 0, "accepted_history_row_count": 0} for side in SIDES}, ["recent_state"]

    result: dict[str, Any] = {}
    coverage: dict[str, Any] = {}
    omitted: list[str] = []
    for side in SIDES:
        rows = history.get(f"{side}_team")
        rows = rows if isinstance(rows, list) else []
        target_team_id = _first(target, f"{side}_team_id", f"{side}_id")
        accepted: list[dict[str, Any]] = []
        rejects = Counter()
        for row in rows:
            if not isinstance(row, Mapping):
                rejects["INVALID_HISTORY_ROW"] += 1
                continue
            row_kickoff = _parse_datetime(_first(row, "kickoff_at", "kickoff"))
            row_date = _date_from_row(row)
            if target_kickoff and row_date:
                if row_kickoff is not None:
                    if row_kickoff >= target_kickoff:
                        rejects["HISTORY_NOT_PREMATCH"] += 1
                        continue
                elif row_date >= target_kickoff.date():
                    rejects["HISTORY_DATE_NOT_PREMATCH"] += 1
                    continue
            projected, reason = _history_row_projection(
                row, target_team_id=target_team_id, panlu=panlu
            )
            if projected is None:
                rejects[reason or "HISTORY_ROW_REJECTED"] += 1
            else:
                projected["_sort_date"] = row_date.toordinal() if row_date else 0
                projected["_sort_kickoff"] = row_kickoff.timestamp() if row_kickoff else 0.0
                accepted.append(projected)
        accepted.sort(
            key=lambda row: (
                -int(row.get("_sort_date", 0)),
                -float(row.get("_sort_kickoff", 0.0)),
                str(row.get("source_fixture_id") or ""),
            )
        )
        for row in accepted:
            row.pop("_sort_date", None)
            row.pop("_sort_kickoff", None)
        side_projection, side_coverage = _recent_side_projection(
            accepted, target_kickoff=target_kickoff
        )
        side_coverage["raw_row_count"] = len(rows)
        side_coverage["rejected_row_count"] = sum(rejects.values())
        side_coverage["reject_counts"] = dict(sorted(rejects.items()))
        result[side] = side_projection
        coverage[side] = side_coverage
        if not accepted:
            omitted.append(f"recent_state.{side}")
    if not any(coverage[side].get("accepted_history_row_count", 0) for side in SIDES):
        omitted.insert(0, "recent_state")
    return result, coverage, omitted


def _model_probabilities(prediction: Mapping[str, Any]) -> tuple[dict[str, float] | None, str | None]:
    value = prediction.get("probabilities")
    if not isinstance(value, Mapping):
        output = prediction.get("prediction_output")
        value = output.get("probabilities") if isinstance(output, Mapping) else None
    if not isinstance(value, Mapping):
        return None, "MODEL_PROBABILITIES_MISSING"
    probabilities: dict[str, float] = {}
    for outcome in OUTCOMES:
        probability = _number(value.get(outcome))
        if probability is None or not 0 <= probability <= 1:
            return None, "MODEL_PROBABILITY_INVALID"
        probabilities[outcome] = probability
    if abs(sum(probabilities.values()) - 1.0) > 0.001:
        return None, "MODEL_PROBABILITIES_NOT_NORMALIZED"
    return probabilities, None


def _preferred_outcome(probabilities: Mapping[str, float]) -> str:
    return max(OUTCOMES, key=lambda outcome: (probabilities[outcome], -OUTCOMES.index(outcome)))


def _model_market_alignment(
    prediction: Mapping[str, Any], market: Mapping[str, Any]
) -> tuple[dict[str, Any], str | None]:
    model, model_reason = _model_probabilities(prediction)
    current = market.get("median_current_probability") if isinstance(market, Mapping) else None
    if model is None:
        return {"status": "OMITTED", "reason": model_reason}, model_reason
    if not isinstance(current, Mapping) or any(_number(current.get(outcome)) is None for outcome in OUTCOMES):
        reason = "CURRENT_MARKET_MEDIAN_MISSING"
        return {"status": "OMITTED", "reason": reason, "model_probabilities": model}, reason
    current_probabilities = {outcome: float(current[outcome]) for outcome in OUTCOMES}
    model_preferred = _preferred_outcome(model)
    market_preferred = _preferred_outcome(current_probabilities)
    return (
        {
            "status": "AVAILABLE",
            "reason": "FROZEN_MODEL_AND_CURRENT_MARKET_MEDIAN",
            "model_probabilities": {outcome: _round(model[outcome]) for outcome in OUTCOMES},
            "current_market_median_probabilities": {
                outcome: _round(current_probabilities[outcome]) for outcome in OUTCOMES
            },
            "gap_probability_points": {
                outcome: _round((model[outcome] - current_probabilities[outcome]) * 100.0)
                for outcome in OUTCOMES
            },
            "model_preferred_outcome": model_preferred,
            "market_preferred_outcome": market_preferred,
            "direction": "ALIGNED" if model_preferred == market_preferred else "CONFLICT",
        },
        None,
    )


def _field_value(
    football_evidence: Mapping[str, Any], field_name: str
) -> tuple[str | None, Any, Mapping[str, Any] | None]:
    prematch = football_evidence.get("prematch_evidence")
    fields = prematch.get("fields") if isinstance(prematch, Mapping) else None
    field = fields.get(field_name) if isinstance(fields, Mapping) else None
    if not isinstance(field, Mapping):
        return None, None, None
    return _text(field.get("state")), field.get("value"), field


def _context_projection(
    football_evidence: Mapping[str, Any], state_memory: Mapping[str, Any], fixture: Mapping[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    target = state_memory.get("target_fixture")
    target = target if isinstance(target, Mapping) else {}
    competition_label = _text(target.get("normalized_competition_label"))
    if not competition_label:
        competition_label = _text(_first(fixture, "league", "competition", "competition_name"))
    competition = {
        "label": competition_label,
        "class": _text(target.get("normalized_competition_class")),
        "resolution_status": _text(target.get("competition_resolution_status")) or ("RESOLVED" if competition_label else "OMITTED"),
        "source": "state_memory.target_fixture" if target.get("normalized_competition_label") else "accepted_fixture",
    }

    coach_state, coach_value, coach_field = _field_value(football_evidence, "coach")
    coach: dict[str, Any] | None = None
    if coach_state == "PRESENT" and isinstance(coach_value, Mapping):
        coach = {
            side: _substantive_name(
                (coach_value.get(side) or {}).get("name")
                if isinstance(coach_value.get(side), Mapping)
                else coach_value.get(side)
            )
            for side in SIDES
        }
        if not any(coach.values()):
            coach = None
    referee_state, referee_value, _ = _field_value(football_evidence, "referee")
    referee = _substantive_name(referee_value.get("name") if isinstance(referee_value, Mapping) else referee_value) if referee_state == "PRESENT" else None

    atoms = {
        "current_competition": {
            "status": "AVAILABLE" if competition_label else "OMITTED",
            "reason": "ACCEPTED_COMPETITION_LABEL" if competition_label else "COMPETITION_LABEL_MISSING",
        },
        "coach": {
            "status": "AVAILABLE" if coach else "OMITTED",
            "reason": "ACCEPTED_SUBSTANTIVE_COACH_NAME" if coach else "COACH_NOT_ACCEPTED_OR_NOT_SUBSTANTIVE",
        },
        "referee": {
            "status": "AVAILABLE" if referee else "OMITTED",
            "reason": "ACCEPTED_SUBSTANTIVE_REFEREE_NAME" if referee else "REFEREE_NOT_ACCEPTED_OR_NOT_SUBSTANTIVE",
        },
    }
    context: dict[str, Any] = {"competition": competition}
    if coach:
        context["coach"] = coach
    if referee:
        context["referee"] = referee
    return context, atoms


def _identity_projection(
    prediction: Mapping[str, Any],
    state_memory: Mapping[str, Any],
    fixture: Mapping[str, Any],
    target_kickoff: datetime | None,
) -> tuple[dict[str, Any], list[str]]:
    target = state_memory.get("target_fixture")
    target = target if isinstance(target, Mapping) else {}
    fixture_ids = _all_ids(fixture, "nowscore_id", "nowscoreId", "match_id", "matchId")
    prediction_ids = _all_ids(prediction, "match_id", "nowscore_id", "nowscoreId")
    state_ids = _all_ids(target, "source_fixture_id", "provider_match_id", "nowscore_id", "match_id")
    reasons: list[str] = []
    ids = fixture_ids + prediction_ids + state_ids
    if ids and any(_id_key(value) != _id_key(ids[0]) for value in ids[1:]):
        reasons.append("CURRENT_FIXTURE_ID_CONFLICT")
    fixture_home_id = _canonical_id(_first(fixture, "home_team_id", "home_id"))
    fixture_away_id = _canonical_id(_first(fixture, "away_team_id", "away_id"))
    home_id = _canonical_id(_first(target, "home_team_id", "home_id"))
    away_id = _canonical_id(_first(target, "away_team_id", "away_id"))
    if home_id is None or away_id is None:
        reasons.append("CURRENT_FIXTURE_TEAM_ID_MISSING")
    elif (
        fixture_home_id is not None
        and fixture_away_id is not None
        and (
            _id_key(fixture_home_id) != _id_key(home_id)
            or _id_key(fixture_away_id) != _id_key(away_id)
        )
    ):
        reasons.append("CURRENT_FIXTURE_TEAM_ID_CONFLICT")
    fixture_kickoff = _target_kickoff({}, {}, fixture)
    prediction_kickoff = _parse_datetime(_first(prediction, "kickoff_at", "kickoff", "match_datetime"))
    target_fixture_kickoff = _parse_datetime(_first(target, "kickoff_at", "kickoff"))
    for candidate in (fixture_kickoff, target_fixture_kickoff):
        if candidate is not None and target_kickoff is not None and candidate != target_kickoff:
            reasons.append("CURRENT_FIXTURE_KICKOFF_CONFLICT")
            break
    if prediction_kickoff is not None and target_fixture_kickoff is not None and prediction_kickoff != target_fixture_kickoff:
        reasons.append("PREDICTION_STATE_KICKOFF_CONFLICT")
    identity = {
        "provider_match_id": ids[0] if ids else None,
        "home_team_id": home_id,
        "away_team_id": away_id,
        "home_team_name": _substantive_name(_first(fixture, "homeTeam", "home_team", "home")) or _substantive_name(target.get("home_team_name")),
        "away_team_name": _substantive_name(_first(fixture, "awayTeam", "away_team", "away")) or _substantive_name(target.get("away_team_name")),
        "kickoff_at": target_kickoff.isoformat(timespec="seconds") if target_kickoff else None,
    }
    return identity, reasons


def project_match_analysis_evidence(
    prediction: Mapping[str, Any],
    input_snapshot: Mapping[str, Any],
    football_evidence: Mapping[str, Any],
    accepted_fixture: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Project one frozen match without mutating any input mapping."""

    prediction = prediction if isinstance(prediction, Mapping) else {}
    input_snapshot = input_snapshot if isinstance(input_snapshot, Mapping) else {}
    football_evidence = football_evidence if isinstance(football_evidence, Mapping) else {}
    fixture = accepted_fixture if isinstance(accepted_fixture, Mapping) else {}
    state_memory = football_evidence.get("state_memory")
    state_memory = state_memory if isinstance(state_memory, Mapping) else {}
    target = state_memory.get("target_fixture")
    target = target if isinstance(target, Mapping) else {}
    target_kickoff = _target_kickoff(prediction, target, fixture)
    identity, identity_reasons = _identity_projection(prediction, state_memory, fixture, target_kickoff)
    base: dict[str, Any] = {
        "contract_version": CONTRACT_VERSION,
        "projection_status": "REJECTED" if identity_reasons else "PROJECTED",
        "projection_success": not identity_reasons,
        "projection_reject_reasons": identity_reasons,
        "prediction_id": _text(prediction.get("prediction_id")),
        "match_key": _text(prediction.get("match_key")),
        "identity": identity,
        "provenance": {
            "prediction_id": _text(prediction.get("prediction_id")),
            "prediction_sha256": _text(prediction.get("prediction_sha256")),
            "input_snapshot_id": _text(input_snapshot.get("snapshot_id")),
            "input_snapshot_ref": _text(input_snapshot.get("snapshot_ref")),
            "football_evidence_contract_version": _text(football_evidence.get("contract_version")),
            "state_memory_contract_version": _text(football_evidence.get("state_memory_contract_version")) or _text(state_memory.get("contract_version")),
        },
    }

    panlu = _panlu_matches(input_snapshot, football_evidence)
    recent_state, history_coverage, history_omitted = _history_projection(
        state_memory,
        target=target,
        target_kickoff=target_kickoff,
        panlu=panlu,
    )
    market = build_market_1x2_chronology(_market_context(input_snapshot, football_evidence))
    alignment, alignment_reason = _model_market_alignment(prediction, market)
    context, context_atoms = _context_projection(football_evidence, state_memory, fixture)

    opponent_candidates = sum(item.get("opponent_name_candidate_count", 0) for item in history_coverage.values())
    opponent_resolved = sum(item.get("opponent_name_resolved_count", 0) for item in history_coverage.values())
    opponent_rejects = Counter()
    for item in history_coverage.values():
        opponent_rejects.update(item.get("opponent_name_reject_counts") or {})
    history_rows = sum(item.get("accepted_history_row_count", 0) for item in history_coverage.values())
    market_status = market.get("status")
    coverage_atoms: dict[str, Any] = {
        "recent_state": {
            "status": "AVAILABLE" if history_rows else "OMITTED",
            "reason": "ACCEPTED_STATE_MEMORY_ROWS" if history_rows else "NO_ACCEPTED_STATE_MEMORY_ROWS",
            "history": history_coverage,
        },
        "opponent_names": {
            "status": "AVAILABLE" if opponent_resolved == opponent_candidates and opponent_candidates else "PARTIAL" if opponent_resolved else "OMITTED",
            "reason": "EXACT_PANLU_CORROBORATION" if opponent_resolved else "EXACT_PANLU_CORROBORATION_REJECTED",
            "candidate_count": opponent_candidates,
            "resolved_count": opponent_resolved,
            "rejected_count": opponent_candidates - opponent_resolved,
            "reject_counts": dict(sorted(opponent_rejects.items())),
        },
        "market_1x2_chronology": {
            "status": market_status,
            "reason": market.get("reason"),
            "bookmaker_count": market.get("bookmaker_count", 0),
            "valid_book_count": market.get("valid_book_count", 0),
            "rejected_bookmaker_count": market.get("rejected_bookmaker_count", 0),
        },
        "model_market_alignment": {
            "status": alignment.get("status"),
            "reason": alignment.get("reason") or alignment_reason,
        },
        **context_atoms,
    }
    omitted_atoms = list(history_omitted)
    for atom, value in coverage_atoms.items():
        if value.get("status") == "OMITTED" and atom not in omitted_atoms:
            omitted_atoms.append(atom)
    base.update(
        {
            "recent_state": recent_state,
            "market_1x2_chronology": market,
            "model_market_alignment": alignment,
            "context": context,
            "coverage": {
                "atoms": coverage_atoms,
                "omitted_atoms": sorted(set(omitted_atoms)),
                "panlu_match_count": len(panlu),
            },
            "rights": {
                "raw_bodies_persisted": False,
                "raw_html_js_persisted": False,
                "input_mutated": False,
            },
        }
    )
    return base


__all__ = [
    "CONTRACT_VERSION",
    "build_market_1x2_chronology",
    "project_match_analysis_evidence",
]
