#!/usr/bin/env python3
"""Build a read-only, accountable Prediction Day product surface."""

from __future__ import annotations

import argparse
import html
import json
import math
import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

try:
    from prematch_versioning import select_latest_legal_prematch
except ImportError:  # package import used by tests
    from scripts.prematch_versioning import select_latest_legal_prematch

try:
    from production_health_watch import evaluate_exact_score_health, select_current_serving_predictions
except ImportError:  # package import used by tests
    from scripts.production_health_watch import evaluate_exact_score_health, select_current_serving_predictions

try:
    from current_serving_state import resolve_current_job_for_match
except ImportError:  # package import used by tests
    from scripts.current_serving_state import resolve_current_job_for_match

try:
    from exact_score_serving_policy import exact_score_serving_presentation
except ImportError:  # package import used by tests
    from scripts.exact_score_serving_policy import exact_score_serving_presentation

try:
    from closed_beta_copy import render_closed_beta_notice
except ImportError:  # package import used by tests
    from scripts.closed_beta_copy import render_closed_beta_notice

try:
    from public_ui_shared import render_beginner_help, render_public_document, render_team_badge
except ImportError:  # package import used by tests
    from scripts.public_ui_shared import render_beginner_help, render_public_document, render_team_badge

try:
    from match_identity import canonical_match_id
except ImportError:
    from scripts.match_identity import canonical_match_id

try:
    from formal_market_projection import (
        project_frozen_formal_markets,
        summarize_formal_markets,
    )
except ImportError:  # package import used by tests
    from scripts.formal_market_projection import (
        project_frozen_formal_markets,
        summarize_formal_markets,
    )


BASE_DIR = Path(__file__).resolve().parents[1]
UNIVERSE_ROOT = BASE_DIR / "data" / "prediction_universe"
JOBS_ROOT = BASE_DIR / "data" / "base_prediction_jobs"
PREDICTION_ROOT = BASE_DIR / "data" / "model_governance" / "predictions"
EXCLUSION_ROOT = BASE_DIR / "data" / "model_governance" / "prediction_exclusions"
RESULT_ROOT = BASE_DIR / "data" / "postmatch_automation" / "results"
SCHEDULE_ROOT = BASE_DIR / "data" / "postmatch_automation" / "schedules"
PROSPECTIVE_ROOT = BASE_DIR / "data" / "prospective"
RUNTIME_PATH = BASE_DIR / "data" / "product_runtime" / "latest_cycle.json"
HEALTH_WATCH_PATH = BASE_DIR / "data" / "product_runtime" / "health_watch.json"
DASHBOARD_ROOT = BASE_DIR / "data" / "prediction_dashboard"
WORKSPACE_LATEST = BASE_DIR / "data" / "match_workspace" / "latest.json"
SHANGHAI = timezone(timedelta(hours=8))

STATUS_LABELS = {
    "CURRENT_JOB_STATE_CONFLICT": "本场状态待确认",
    "FROZEN": "已形成预测",
    "PENDING": "预测尚未形成",
    "INSUFFICIENT_DATA": "数据不足，暂不预测",
    "PREDICTION_FAILED": "本场未形成有效预测",
    "MISSED_PREMATCH_WINDOW": "未形成合法赛前预测",
    "REMOVED_FROM_CURRENT_UNIVERSE": "暂不在当前赛程",
}
REASON_LABELS = {
    "DUPLICATE_CURRENT_JOB_STATE": "本场状态待确认，暂不形成预测",
    "MULTIPLE_CURRENT_MATCH_GROUPS": "比赛身份待确认，暂不形成预测",
    "MISSING_RECENT_FORM": "近期比赛数据不足",
    "MISSING_MARKET_INTELLIGENCE": "市场信息不足",
    "INPUT_TIMESTAMP_UNVERIFIED": "赛前数据时间无法验证",
    "SOURCE_FETCH_FAILED": "赛前数据源获取失败",
    "CACHE_PROVENANCE_INVALID": "近期数据来源无法验证",
    "INPUT_SNAPSHOT_CONSTRUCTION_FAILED": "赛前输入快照构建失败",
    "INPUT_PROVENANCE_UNVERIFIED": "赛前输入来源无法验证",
    "IDENTITY_UNRESOLVED": "比赛身份无法可靠匹配",
    "PREDICTION_FAILED": "模型运行失败",
    "MISSED_PREMATCH_WINDOW": "未形成合法赛前预测",
    "BASE_JOB_MISSING": "预测任务尚未生成",
    "PREDICTION_ARTIFACT_MISSING": "预测任务已锁定，但正式记录缺失",
}


_CURRENT_FORMAL_STATUSES = {"formal", "frozen", "FROZEN"}
_QUALITY_STATUS_LABELS = {
    "HEALTHY": "正常",
    "ALERT": "异常",
    "INSUFFICIENT_SAMPLE": "样本不足",
    "WATCH": "观察",
    "UNKNOWN": "待确认",
}
_QUALITY_ALERT_COPY = "当前预测质量降级，仅供观察。"



def _read_json(path: Path, errors: list[str], label: str, default: Any) -> Any:
    if not path.is_file():
        errors.append(f"{label}:MISSING")
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        errors.append(f"{label}:INVALID")
        return default


def _read_optional_json(path: Path, errors: list[str], label: str, default: Any) -> Any:
    if not path.is_file():
        return default
    return _read_json(path, errors, label, default)


def _previous_business_day_results(
    business_date: str, universe_root: Path, schedule_root: Path, result_root: Path,
) -> dict[str, Any] | None:
    try:
        previous_date = (datetime.fromisoformat(business_date).date() - timedelta(days=1)).isoformat()
    except ValueError:
        return None
    path = Path(universe_root) / f"{previous_date}.json"
    try:
        universe = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    fixtures = universe.get("fixtures") if isinstance(universe, dict) else None
    if not isinstance(fixtures, list) or not fixtures:
        return None
    entries = []
    for fixture in [row for row in fixtures if isinstance(row, dict)][:100]:
        home, away = fixture.get("homeTeam"), fixture.get("awayTeam")
        try:
            kickoff = datetime.fromisoformat(f"{fixture['matchDate']}T{str(fixture['matchTime'])[:5]}:00+08:00")
            if kickoff.tzinfo is None:
                continue
        except (KeyError, TypeError, ValueError):
            continue
        key = canonical_match_id({"home": home, "away": away, "kickoff_local": kickoff.isoformat()}) if home and away else None
        schedule_path = Path(schedule_root) / f"{key}.json" if key else None
        result_path = Path(result_root) / f"{key}.json" if key else None
        schedule = result = {}
        if schedule_path and schedule_path.is_file():
            try: schedule = json.loads(schedule_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError): pass
        if result_path and result_path.is_file():
            try: result = json.loads(result_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError): pass
        source = result.get("source") if isinstance(result, dict) else None
        source_url = result.get("source_url") if isinstance(result, dict) else None
        score = result.get("result_90m") if isinstance(result, dict) else None
        provenance = next((item for item in (schedule.get("result_sources") or {}).values()
                           if isinstance(item, dict) and item.get("name") == source
                           and item.get("status") == "verified"), {}) if isinstance(schedule, dict) else {}
        verified = bool(
            isinstance(schedule, dict) and isinstance(result, dict)
            and schedule.get("status") == "result_verified"
            and schedule.get("canonical_match_id") == key and schedule.get("match_key") == key
            and result.get("match_key") == key
            and schedule.get("home") == home == result.get("home")
            and schedule.get("away") == away == result.get("away")
            and _strict_kickoff_utc_key(schedule.get("kickoff_local")) == kickoff.astimezone(timezone.utc).isoformat(timespec="seconds")
            and _strict_kickoff_utc_key(result.get("kickoff_local")) == kickoff.astimezone(timezone.utc).isoformat(timespec="seconds")
            and isinstance(score, str) and re.fullmatch(r"\d{1,2}-\d{1,2}", score)
            and schedule.get("result_90m") == score
            and schedule.get("result_source") == source and bool(source)
            and provenance.get("source_url") == source_url and bool(source_url)
        )
        entries.append({
            "match_num": fixture.get("matchNum"), "home": home, "away": away,
            "status": "VERIFIED" if verified else "PENDING",
            "90m_score": score if verified else None, "source_url": source_url if verified else None,
        })
    if not entries:
        return None
    verified_count = sum(entry["status"] == "VERIFIED" for entry in entries)
    return {"business_date": previous_date, "fixture_count": len(entries), "verified_count": verified_count,
            "pending_count": len(entries) - verified_count, "entries": entries}

def _read_jsonl(path: Path, errors: list[str], label: str) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    try:
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            value = json.loads(line)
            if isinstance(value, dict):
                rows.append(value)
            else:
                errors.append(f"{label}:LINE_{line_number}_NOT_OBJECT")
    except (OSError, json.JSONDecodeError):
        errors.append(f"{label}:INVALID")
    return rows


def _text(value: Any, fallback: str = "—") -> str:
    if value in (None, ""):
        return fallback
    if isinstance(value, float):
        if not math.isfinite(value):
            return fallback
        return f"{value:.3f}".rstrip("0").rstrip(".")
    return str(value)


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _iso_sort(value: Any) -> str:
    return str(value or "9999-12-31T23:59:59+08:00")


def _kickoff_timestamp(value: Any) -> str | None:
    """Return a timezone-qualified ISO timestamp suitable for browser comparison."""

    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _pick(row: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return value
    return None


def _fixture_projection(fixture: dict[str, Any]) -> dict[str, Any]:
    kickoff = _pick(fixture, "kickoff", "kickoff_local")
    if not kickoff:
        match_date = str(_pick(fixture, "matchDate", "businessDate") or "")[:10]
        match_time = str(_pick(fixture, "matchTime") or "")[:8]
        if match_date and match_time:
            kickoff = f"{match_date}T{match_time}+08:00"
    return {
        "match_id": str(_pick(fixture, "matchId", "match_id", "id") or ""),
        "match_num": _pick(fixture, "matchNum", "match_num"),
        "competition": _pick(fixture, "league", "competition"),
        "business_date": _pick(fixture, "businessDate", "business_date"),
        "home": _pick(fixture, "homeTeam", "home_team", "home"),
        "away": _pick(fixture, "awayTeam", "away_team", "away"),
        "home_crest": _pick(fixture, "homeCrest", "home_crest", "homeLogo", "home_logo"),
        "away_crest": _pick(fixture, "awayCrest", "away_crest", "awayLogo", "away_logo"),
        "kickoff": kickoff,
        "kickoff_timestamp": _kickoff_timestamp(kickoff),
    }


def _score_focus(record: dict[str, Any]) -> tuple[str | None, list[str], str | None]:
    primary = str(record.get("unique_score") or record.get("score_top1") or "").strip() or None
    source = record.get("score_top3") or record.get("top_scores") or record.get("score_distribution") or []
    names: list[str] = []
    if isinstance(source, list):
        for row in source:
            if isinstance(row, dict):
                score = str(row.get("score") or "").strip()
            else:
                score = str(row).strip()
            if score and score not in names:
                names.append(score)
    if not primary and names:
        primary = names[0]
    neighbors = [score for score in names if score != primary][:2]
    canonical_concentration = record.get("score_concentration")
    concentration = str(canonical_concentration).strip() if canonical_concentration not in (None, "") else None
    return primary, neighbors, concentration


def _one_x_two_direction(probabilities: dict[str, Any]) -> str | None:
    values = {key: _number(probabilities.get(key)) for key in ("home", "draw", "away")}
    if any(value is None for value in values.values()):
        return None
    direction = max(values, key=lambda key: values[key] or 0)
    return {"home": "主胜倾向", "draw": "平局倾向", "away": "客胜倾向"}[direction]


_RECOMMENDATION_DIRECTION_LABELS = {
    "home": "\u4e3b\u80dc",
    "draw": "\u5e73\u5c40",
    "away": "\u5ba2\u80dc",
}
_RECOMMENDATION_BLOCKED_STATES = {
    "ABSTAIN",
    "DEGRADED",
    "UNAVAILABLE",
    "UNVERIFIED",
}
_RECOMMENDATION_BLOCKED_AUTHORITY = {
    "ABSTAIN",
    "DEGRADED",
    "INELIGIBLE",
    "OBSERVE",
    "OBSERVE_ONLY",
    "UNAVAILABLE",
}
_RECOMMENDATION_LANE_LABELS = {
    "FT_1X2": "\u80dc / \u5e73 / \u8d1f\u6982\u7387",
    "EXACT_SCORE": "\u6700\u53ef\u80fd\u6bd4\u5206",
}


def _normalise_probability_map(values: Any) -> dict[str, float] | None:
    if not isinstance(values, dict):
        return None
    parsed: dict[str, float] = {}
    for key in ("home", "draw", "away"):
        value = _number(values.get(key))
        if value is None or not 0 <= value <= 1:
            return None
        parsed[key] = value
    total = sum(parsed.values())
    if total <= 0:
        return None
    return {key: value / total for key, value in parsed.items()}


def _score_pair(value: Any) -> tuple[int, int] | None:
    if isinstance(value, dict):
        home = value.get("home_goals", value.get("home_score"))
        away = value.get("away_goals", value.get("away_score"))
        try:
            pair = (int(home), int(away))
        except (TypeError, ValueError):
            return None
        return pair if min(pair) >= 0 else None
    text = str(value or "").strip()
    if "-" not in text:
        return None
    home_text, away_text = text.split("-", 1)
    try:
        pair = (int(home_text.strip()), int(away_text.strip()))
    except ValueError:
        return None
    return pair if min(pair) >= 0 else None


def _recommendation_authority_eligible(prediction: dict[str, Any]) -> bool:
    if prediction.get("pilot_excluded") is True or prediction.get("prediction_kind") == "pilot":
        return False
    if prediction.get("formal_eligible") is False or prediction.get("model_formal_eligible") is False:
        return False
    if str(prediction.get("prediction_status") or "").strip().lower() not in {"", "formal", "frozen"}:
        return False
    if str(prediction.get("model_role") or "").strip().lower() not in {"", "champion"}:
        return False
    if str(prediction.get("prediction_variant") or "").strip().lower() not in {"", "model_only"}:
        return False
    return prediction.get("manual_override") is not True


def _formal_market_status(prediction: dict[str, Any], market_name: str) -> str:
    formal = prediction.get("formal_markets")
    markets = formal.get("markets") if isinstance(formal, dict) else None
    market = markets.get(market_name) if isinstance(markets, dict) else None
    return str(market.get("status") or "").strip().upper() if isinstance(market, dict) else ""


def _normalise_recommendation_candidate(candidate: Any) -> dict[str, Any] | None:
    if not isinstance(candidate, dict):
        return None
    lane = str(candidate.get("lane") or candidate.get("market") or "").strip()
    market = str(candidate.get("market") or lane).strip()
    selection = candidate.get("selection")
    if isinstance(selection, str):
        selection = {"kind": "generic", "key": selection, "label": selection}
    elif isinstance(selection, dict):
        selection = dict(selection)
    else:
        return None
    key = selection.get("key")
    if key in (None, ""):
        key = selection.get("value")
    if key in (None, ""):
        return None
    selection["key"] = str(key)
    selection["kind"] = str(selection.get("kind") or "generic")
    selection["label"] = str(selection.get("label") or selection["key"])
    if not lane or not market:
        return None
    normalized = dict(candidate)
    normalized["market"] = market
    normalized["lane"] = lane
    normalized["selection"] = selection
    normalized["state"] = str(candidate.get("state") or "UNVERIFIED").strip().upper()
    normalized["reason"] = str(candidate.get("reason") or selection["label"]).strip()
    if "authority" not in normalized:
        normalized["authority"] = {"eligible": False, "class": "UNDECLARED"}
    return normalized


def _recommendation_candidate_eligible(candidate: dict[str, Any]) -> bool:
    state = str(candidate.get("state") or "UNVERIFIED").strip().upper()
    if state in _RECOMMENDATION_BLOCKED_STATES:
        return False
    if candidate.get("eligible") is False or candidate.get("authority_eligible") is False:
        return False
    authority = candidate.get("authority")
    if isinstance(authority, dict):
        if authority.get("eligible") is False:
            return False
        authority_state = str(
            authority.get("state")
            or authority.get("status")
            or authority.get("class")
            or ""
        ).strip().upper()
        if authority_state in _RECOMMENDATION_BLOCKED_AUTHORITY:
            return False
    elif isinstance(authority, bool):
        if not authority:
            return False
    elif str(authority or "").strip().upper() in _RECOMMENDATION_BLOCKED_AUTHORITY:
        return False
    selection = candidate.get("selection")
    return (
        isinstance(selection, dict)
        and str(candidate.get("lane") or "").strip() != ""
        and str(candidate.get("market") or "").strip() != ""
        and str(selection.get("key") or "").strip() != ""
    )


def _recommendation_comparison_key(candidate: dict[str, Any]) -> str | None:
    selection = candidate.get("selection")
    if not isinstance(selection, dict):
        return None
    value = selection.get("comparison_key") or candidate.get("comparison_key")
    return str(value).strip() if value not in (None, "") else None


def _recommendation_lane_label(candidate: dict[str, Any]) -> str:
    lane = str(candidate.get("lane") or "").strip()
    return str(
        candidate.get("lane_label")
        or _RECOMMENDATION_LANE_LABELS.get(lane)
        or candidate.get("market")
        or lane
    )


def _score_probability(prediction: dict[str, Any], score: str) -> float | None:
    rows = prediction.get("score_distribution")
    if not isinstance(rows, list):
        return None
    for row in rows:
        if not isinstance(row, dict):
            continue
        row_score = _score_label(row.get("score") or row.get("value"))
        probability = _number(row.get("probability"))
        if row_score == score and probability is not None and 0 <= probability <= 1:
            return probability
    return None


def _exact_selection(prediction: dict[str, Any]) -> dict[str, Any] | None:
    raw_score = prediction.get("primary_score") or prediction.get("unique_score")
    if raw_score in (None, ""):
        top_scores = prediction.get("score_top3")
        if isinstance(top_scores, list) and top_scores:
            raw_score = top_scores[0].get("score") if isinstance(top_scores[0], dict) else top_scores[0]
    score = _score_label(raw_score)
    if not score:
        return None
    selection: dict[str, Any] = {
        "kind": "exact_score",
        "key": score,
        "label": f"\u6bd4\u5206 {score}",
        "score": score,
    }
    pair = _score_pair(score)
    if pair is not None:
        direction = "home" if pair[0] > pair[1] else "draw" if pair[0] == pair[1] else "away"
        selection["support_direction"] = direction
        selection["comparison_key"] = f"result:{direction}"
    return selection


def _implemented_recommendation_candidates(
    prediction: dict[str, Any],
    *,
    exact_score_serving: dict[str, Any] | str | None,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    one_x_two_state = str(prediction.get("one_x_two_serving_state") or "NORMAL").strip().upper()
    one_x_two = _normalise_probability_map(prediction.get("probabilities"))
    if one_x_two_state not in _RECOMMENDATION_BLOCKED_STATES and one_x_two is not None:
        direction = max(
            one_x_two,
            key=lambda key: (one_x_two[key], {"home": 2, "draw": 1, "away": 0}[key]),
        )
        selection = {
            "kind": "result",
            "key": direction,
            "label": _RECOMMENDATION_DIRECTION_LABELS[direction],
            "direction": direction,
            "comparison_key": f"result:{direction}",
        }
        candidates.append({
            "market": "FT_1X2",
            "lane": "FT_1X2",
            "selection": selection,
            "authority": {"eligible": True, "class": "FORMAL"},
            "state": one_x_two_state,
            "reason": f'{_RECOMMENDATION_DIRECTION_LABELS[direction]}\u6982\u7387\u6700\u9ad8\uff08{one_x_two[direction] * 100:.1f}%\uff09',
            "evidence": {"probability": one_x_two[direction]},
        })

    serving_state = (
        exact_score_serving.get("state")
        if isinstance(exact_score_serving, dict)
        else exact_score_serving
    ) or prediction.get("exact_score_serving_state")
    exact_state = str(serving_state or "UNVERIFIED").strip().upper()
    exact_selection = _exact_selection(prediction)
    if (
        _formal_market_status(prediction, "exact_score") == "AVAILABLE"
        and exact_state not in _RECOMMENDATION_BLOCKED_STATES
        and exact_selection is not None
    ):
        score = str(exact_selection["score"])
        score_probability = _score_probability(prediction, score)
        probability_note = (
            f'\uff08{score_probability * 100:.1f}%\uff09'
            if score_probability is not None
            else ""
        )
        candidates.append({
            "market": "EXACT_SCORE",
            "lane": "EXACT_SCORE",
            "selection": exact_selection,
            "authority": {"eligible": True, "class": "FORMAL"},
            "state": exact_state,
            "reason": f'\u6700\u53ef\u80fd\u6bd4\u5206\u4e3a {score}{probability_note}',
            **({"evidence": {"probability": score_probability}} if score_probability is not None else {}),
        })
    return candidates


def _recommendation_empty(
    *,
    basis: str = "NO_ELIGIBLE_LANE",
    reason: str = "\u5f53\u524d\u6ca1\u6709\u53ef\u7528\u7684\u6b63\u5f0f\u9884\u6d4b\u65b9\u5411",
    candidates: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    candidates = candidates or []
    return {
        "status": "ABSTAIN",
        "basis": basis,
        "market": None,
        "lane": None,
        "selection": None,
        "authority": {"eligible": False, "class": "NONE"},
        "state": "CONFLICT" if basis == "CONFLICT" else "ABSTAIN",
        "label": "\u6682\u65e0\u660e\u786e\u9996\u9009\u65b9\u5411",
        "reason": reason,
        "candidates": candidates,
        "eligible_lanes": [str(candidate["lane"]) for candidate in candidates],
    }


def select_primary_recommendation(
    prediction: dict[str, Any] | None,
    *,
    exact_score_serving: dict[str, Any] | str | None = None,
    prediction_allowed: bool = True,
) -> dict[str, Any]:
    """Return one generic recommendation or fail closed on lane disagreement."""

    if not isinstance(prediction, dict) or not prediction_allowed or not _recommendation_authority_eligible(prediction):
        return _recommendation_empty()

    raw_candidates = prediction.get("recommendation_candidates")
    candidates = (
        [_normalise_recommendation_candidate(item) for item in raw_candidates]
        if isinstance(raw_candidates, list)
        else _implemented_recommendation_candidates(
            prediction,
            exact_score_serving=exact_score_serving,
        )
    )
    candidates = [
        candidate
        for candidate in candidates
        if candidate is not None and _recommendation_candidate_eligible(candidate)
    ]
    if not candidates:
        return _recommendation_empty()
    if len(candidates) == 1:
        candidate = candidates[0]
        selection = dict(candidate["selection"])
        return {
            "status": "SELECTED",
            "basis": "SINGLE_LANE",
            "market": candidate["market"],
            "lane": candidate["lane"],
            "selection": selection,
            "authority": candidate["authority"],
            "state": candidate["state"],
            "label": selection["label"],
            "reason": f'\u4ec5\u57fa\u4e8e{_recommendation_lane_label(candidate)}\uff1a{candidate["reason"]}',
            "candidates": candidates,
            "eligible_lanes": [str(candidate["lane"])],
        }

    comparison_keys = [_recommendation_comparison_key(candidate) for candidate in candidates]
    if any(key is None for key in comparison_keys) or len(set(comparison_keys)) != 1:
        return _recommendation_empty(
            basis="CONFLICT",
            reason="\u73a9\u6cd5\u7ed3\u8bba\u4e0d\u4e00\u81f4",
            candidates=candidates,
        )

    comparison_key = comparison_keys[0]
    direction = (
        comparison_key.split(":", 1)[1]
        if comparison_key and comparison_key.startswith("result:")
        else None
    )
    label = _RECOMMENDATION_DIRECTION_LABELS.get(direction or "")
    if not label:
        label = str(candidates[0]["selection"]["label"])
    supporting_selections = [dict(candidate["selection"]) for candidate in candidates]
    selection = {
        "kind": "agreement",
        "key": comparison_key,
        "label": label,
        "comparison_key": comparison_key,
        "supporting_selections": supporting_selections,
        "supporting_lanes": [str(candidate["lane"]) for candidate in candidates],
    }
    if direction:
        selection["direction"] = direction
    lane_summary = "\uff1b".join(
        f'{_recommendation_lane_label(candidate)}\uff08{candidate["selection"]["label"]}\uff09'
        for candidate in candidates
    )
    return {
        "status": "SELECTED",
        "basis": "AGREEMENT",
        "market": "MULTI_LANE",
        "lane": "AGREEMENT",
        "selection": selection,
        "authority": {"eligible": True, "class": "SYNTHESIZED"},
        "state": "NORMAL",
        "label": label,
        "reason": f'\u53ef\u7528\u73a9\u6cd5\u4e00\u81f4\u652f\u6301{label}\uff1a{lane_summary}',
        "candidates": candidates,
        "eligible_lanes": [str(candidate["lane"]) for candidate in candidates],
    }


def _prediction_projection(
    record: dict[str, Any],
) -> dict[str, Any]:
    probabilities = record.get("fusion_1X2") or record.get("probabilities") or {}
    probabilities = probabilities if isinstance(probabilities, dict) else {}
    btts = record.get("btts") or {}
    primary, neighbors, concentration = _score_focus(record)
    canonical_market = record.get("market_summary") or record.get("canonical_market_summary") or {}
    if not isinstance(canonical_market, dict):
        canonical_market = {}
    canonical_direction = record.get("one_x_two_direction")
    if canonical_direction in (None, ""):
        prediction_output = record.get("prediction_output")
        if isinstance(prediction_output, dict):
            canonical_direction = prediction_output.get("one_x_two_direction")
    formal_markets = summarize_formal_markets(project_frozen_formal_markets(record))
    return {
        "product_role": record.get("product_role"),
        "model_family": record.get("model_family"),
        "release_version": record.get("release_version"),
        "lambda_home": record.get("lambda_home"),
        "lambda_away": record.get("lambda_away"),
        "probabilities": probabilities,
        "one_x_two_direction": canonical_direction or _one_x_two_direction(probabilities),
        "btts": btts if isinstance(btts, dict) else {},
        "totals": record.get("totals") if isinstance(record.get("totals"), list) else [],
        "unique_score": primary,
        "primary_score": primary,
        "score_top3": record.get("score_top3") or [],
        "neighbor_scores": neighbors,
        "score_concentration": concentration,
        "score_distribution": record.get("score_distribution") if isinstance(record.get("score_distribution"), list) else [],
        "market_summary": canonical_market,
        "market_intelligence_quality": record.get("market_intelligence_quality"),
        "market_data_providers": record.get("market_data_providers") or record.get("market_sources") or [],
        "market_bookmakers": record.get("market_bookmakers") or [],
        "market_families": record.get("market_families") or [],
        "data_grade": record.get("data_grade"),
        "base_input_quality": record.get("base_input_quality"),
        "minutes_to_kickoff_at_freeze": record.get("minutes_to_kickoff_at_freeze"),
        "prediction_created_at": record.get("prediction_created_at") or record.get("created_at"),
        "freeze_created_at": record.get("freeze_created_at") or record.get("freeze_at"),
        "source_cutoff_at": record.get("source_cutoff_at") or record.get("model_input_as_of_at"),
        "input_snapshot_ref": record.get("input_snapshot_ref") or record.get("model_input_snapshot_ref"),
        "source_references": record.get("source_references") or [],
        # Dashboard receives only the compact status/probability summary.  The
        # 169-cell matrix remains a Match Detail concern.
        "formal_markets": formal_markets,
    }


def _strict_kickoff_utc_key(value: Any) -> str | None:
    """Canonicalize an aware instant; never infer timezone for naive values."""
    try:
        moment = datetime.fromisoformat(str(value).strip())
    except (TypeError, ValueError):
        return None
    if moment.tzinfo is None or moment.utcoffset() is None:
        return None
    return moment.astimezone(timezone.utc).isoformat(timespec="seconds")

def _result_keys(result: dict[str, Any]) -> set[str]:
    keys: set[str] = set()
    for field in ("match_key", "match_id", "provider_match_id"):
        value = result.get(field)
        if value not in (None, ""):
            keys.add(f"value:{value}")
    home = result.get("home")
    away = result.get("away")
    kickoff = result.get("kickoff_local") or result.get("kickoff_at")
    if home and away and kickoff:
        keys.add(f"teams:{home}|{away}|{kickoff}")
    return keys


def _result_index(result_root: Path, errors: list[str]) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    if not result_root.is_dir():
        return index
    for path in sorted(result_root.glob("*.json")):
        value = _read_optional_json(path, errors, f"result:{path.name}", {})
        if not isinstance(value, dict):
            continue
        value.setdefault("result_file", str(path.relative_to(BASE_DIR)).replace("\\", "/") if path.is_relative_to(BASE_DIR) else path.name)
        for key in _result_keys(value):
            index.setdefault(key, value)
    return index


def _workspace_history(workspace_path: Path, errors: list[str]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Project the published workspace's immutable completed/history rows."""

    if not workspace_path.is_file():
        return [], []
    workspace = _read_json(workspace_path, errors, "workspace", {})
    if not isinstance(workspace, dict):
        return [], []
    history = [row for row in workspace.get("history") or [] if isinstance(row, dict)]
    completed = [row for row in workspace.get("completed") or [] if isinstance(row, dict)]
    if not completed:
        completed = [
            row for row in history
            if row.get("review_available") is True and row.get("result_90m")
        ]
    return completed, history


def _exclusion_index(exclusion_root: Path, errors: list[str]) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    if not exclusion_root.is_dir():
        return index
    for path in sorted(exclusion_root.glob("*.json")):
        value = _read_optional_json(path, errors, f"exclusion:{path.name}", {})
        if not isinstance(value, dict):
            continue
        ids = value.get("prediction_ids") or []
        if value.get("prediction_id"):
            ids = [*ids, value["prediction_id"]]
        for prediction_id in ids:
            index[str(prediction_id)] = {
                "reason_code": value.get("reason_code"),
                "reason": value.get("reason"),
            }
    return index


def _find_result(
    card: dict[str, Any],
    record: dict[str, Any] | None,
    result_index: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    keys: list[str] = []
    if record:
        for field in ("match_key", "match_id"):
            if record.get(field):
                keys.append(f"value:{record[field]}")
        identity = record.get("match_identity") or {}
        home = identity.get("home") or record.get("home")
        away = identity.get("away") or record.get("away")
        kickoff = record.get("kickoff_at") or identity.get("kickoff_at")
        if home and away and kickoff:
            keys.append(f"teams:{home}|{away}|{kickoff}")
    for field in ("match_id",):
        if card.get(field):
            keys.append(f"value:{card[field]}")
    for key in keys:
        if key in result_index:
            return result_index[key]
    return None


def _read_records(prediction_root: Path, errors: list[str]) -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    if not prediction_root.is_dir():
        errors.append("predictions:MISSING")
        return records
    for path in sorted(prediction_root.glob("*.json")):
        value = _read_optional_json(path, errors, f"prediction:{path.name}", {})
        if isinstance(value, dict) and value.get("prediction_id"):
            records[str(value["prediction_id"])] = value
    return records


def _status_reason(status: str, job: dict[str, Any] | None, record: dict[str, Any] | None) -> tuple[str | None, str | None]:
    raw = str((job or {}).get("last_error") or "").strip()
    if raw:
        return raw, REASON_LABELS.get(raw, raw)
    if status == "FROZEN" and record is None:
        return "PREDICTION_ARTIFACT_MISSING", REASON_LABELS["PREDICTION_ARTIFACT_MISSING"]
    if job is None:
        return "BASE_JOB_MISSING", REASON_LABELS["BASE_JOB_MISSING"]
    return None, None


def _prematch_identity(fixture: dict[str, Any], job: dict[str, Any] | None) -> dict[str, Any]:
    projected = _fixture_projection(fixture)
    job = job or {}
    return {
        "job_id": job.get("job_id"),
        "match_id": job.get("match_id") or projected.get("match_id"),
        "match_key": job.get("match_key") or job.get("canonical_match_id") or _pick(fixture, "match_key", "matchKey"),
        "home": job.get("home") or projected.get("home"),
        "away": job.get("away") or projected.get("away"),
        "kickoff_at": job.get("kickoff") or projected.get("kickoff"),
    }


def _public_job_resolution(resolution: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(resolution, dict):
        return None
    return {
        key: resolution.get(key)
        for key in (
            "status",
            "row_count",
            "job_ids",
            "statuses",
            "match_key",
            "conflict_reason",
        )
    }


def _conflict_job(fixture: dict[str, Any], resolution: dict[str, Any]) -> dict[str, Any]:
    projected = _fixture_projection(fixture)
    conflict_reason = str(resolution.get("conflict_reason") or "DUPLICATE_CURRENT_JOB_STATE")
    return {
        "job_id": None,
        "match_id": projected.get("match_id"),
        "match_key": _pick(fixture, "match_key", "matchKey"),
        "home": projected.get("home"),
        "away": projected.get("away"),
        "kickoff": projected.get("kickoff"),
        "status": "CURRENT_JOB_STATE_CONFLICT",
        "prediction_id": None,
        "last_error": conflict_reason,
        "current_job_resolution": _public_job_resolution(resolution),
    }


def _card(
    fixture: dict[str, Any],
    job: dict[str, Any] | None,
    record: dict[str, Any] | None,
    result_index: dict[str, dict[str, Any]],
    exclusions: dict[str, dict[str, Any]],
    formal_samples: dict[str, dict[str, Any]],
    exploratory_samples: dict[str, dict[str, Any]],
    prematch_selection: dict[str, Any] | None = None,
    current_job_resolution: dict[str, Any] | None = None,
) -> dict[str, Any]:
    resolution_status = (current_job_resolution or {}).get("status")
    if resolution_status == "CONFLICT":
        job = _conflict_job(fixture, current_job_resolution or {})
    elif resolution_status == "MISSING":
        job = None
    card = _fixture_projection(fixture)
    status = str((job or {}).get("status") or "PENDING")
    selection = prematch_selection or {}
    current_selection = status == "FROZEN" and prematch_selection is not None
    is_conflict = status == "CURRENT_JOB_STATE_CONFLICT"
    if current_selection:
        record = selection.get("selected_record")
        prediction_id = str(selection.get("selected_prediction_id") or "") or None
    elif is_conflict:
        record = None
        prediction_id = None
    elif status != "FROZEN":
        # A retained prediction pointer is audit identity only until the
        # current base job is FROZEN; never project it as a live recommendation.
        record = None
        prediction_id = str((job or {}).get("prediction_id") or "") or None
    else:
        prediction_id = str((job or {}).get("prediction_id") or "") or None
    if current_selection:
        serving_selection_status = selection.get("status")
        serving_selection_reason = selection.get("reason")
    elif is_conflict:
        serving_selection_status = "CONFLICT"
        serving_selection_reason = (current_job_resolution or {}).get("conflict_reason") or "DUPLICATE_CURRENT_JOB_STATE"
    elif status != "FROZEN":
        serving_selection_status = "NOT_SERVING"
        serving_selection_reason = "CURRENT_JOB_NOT_FROZEN"
    else:
        serving_selection_status = "LEGACY_POINTER"
        serving_selection_reason = "JOB_POINTER"
    reason_code, reason_text = _status_reason(status, job, record)
    result = _find_result(card, record, result_index)
    sample = formal_samples.get(prediction_id or "") or exploratory_samples.get(prediction_id or "")
    pilot_excluded = bool(prediction_id and prediction_id in exclusions)
    formal_prospective = bool(prediction_id and prediction_id in formal_samples)
    card.update({
        "status": status,
        "status_label": "试运行预测" if pilot_excluded and record else STATUS_LABELS.get(status, status),
        "reason_code": reason_code,
        "reason_text": reason_text,
        "job_id": (job or {}).get("job_id"),
        "prediction_id": prediction_id,
        "selected_prediction_id": selection.get("selected_prediction_id") if current_selection else None,
        "current_prediction_id": selection.get("selected_prediction_id") if current_selection else None,
        "final_prematch_prediction_id": selection.get("selected_prediction_id") if current_selection else None,
        "selected_freeze_created_at": selection.get("selected_freeze_created_at") if current_selection else None,
        "selected_source_cutoff_at": selection.get("selected_source_cutoff_at") if current_selection else None,
        "superseded_count": int(selection.get("superseded_count") or 0) if current_selection else 0,
        "prematch_selection": {
            "status": serving_selection_status,
            "reason": serving_selection_reason,
            "candidate_count": int(selection.get("candidate_count") or 0) if current_selection else 0,
            "selected_prediction_id": selection.get("selected_prediction_id") if current_selection else None,
            "selected_freeze_created_at": selection.get("selected_freeze_created_at") if current_selection else None,
            "selected_source_cutoff_at": selection.get("selected_source_cutoff_at") if current_selection else None,
            "superseded_count": int(selection.get("superseded_count") or 0) if current_selection else 0,
        },
        "prediction": _prediction_projection(record) if record else None,
        "result": {
            "score_90m": (result or {}).get("result_90m") or (result or {}).get("score_90m"),
            "verified_at": (result or {}).get("result_verified_at") or (result or {}).get("verified_at"),
            "source": (result or {}).get("source"),
        } if result else None,
        "pilot_excluded": pilot_excluded,
        "formal_prospective": formal_prospective,
        "evaluation": {
            "kind": "formal" if formal_prospective else "pilot_excluded" if prediction_id in exploratory_samples else None,
            "metrics": sample.get("metrics") if isinstance(sample, dict) else {},
        } if sample else None,
        "current_job_resolution": _public_job_resolution(current_job_resolution),
    })
    return card


def _esc(value: Any, fallback: str = "\u2014") -> str:
    return html.escape(_text(value, fallback))


MODERN_CSS = r"""
.dashboard-page { min-height: 100%; }
.dashboard-page .content { min-width: 0; }
.matches-head { display: flex; align-items: end; justify-content: space-between; gap: 18px; padding: 9px 2px 10px; }
.matches-head h1 { margin: 0; font-size: var(--type-display); letter-spacing: -.045em; }
.matches-head p { margin: 5px 0 0; color: var(--muted); font-size: var(--type-support); }
.chips { display: flex; gap: 6px; }
.chip, .filter { padding: 8px 12px; border: 1px solid var(--line); border-radius: 8px; background: #FFF; color: var(--ink); font-size: var(--type-support); }
.chip.active, .filter[aria-pressed="true"] { border-color: #FFAD7A; background: var(--orange-soft); color: var(--orange); }
.filter { min-height: 36px; cursor: pointer; }
.filter:hover { border-color: #FFAD7A; color: var(--orange); }
.filters { display: flex; flex-wrap: wrap; gap: 6px; }
.quality-warning, .runtime-warning, .data-warning { display: flex; flex-wrap: wrap; align-items: baseline; gap: 5px 10px; margin: 0 0 10px; padding: 10px 14px; border-left: 3px solid var(--orange); background: var(--orange-soft); color: var(--muted); font-size: var(--type-support); }
.quality-warning strong, .runtime-warning strong, .data-warning strong { color: var(--ink); font-weight: 700; }
.runtime-warning { border-left-color: var(--danger); background: var(--danger-soft); }
.runtime-warning strong { color: var(--danger); }
.data-warning { border-left-color: var(--warning); background: var(--warning-soft); color: var(--warning); }
.fixture-table { min-width: 0; }
.recent-results { margin: 24px 0; padding: 18px 20px; border: 1px solid var(--line); border-radius: 12px; background: var(--card); }
.recent-results-head h2 { margin: 0; color: var(--ink); font-size: 18px; }
.recent-results-head p, .recent-results-note { color: var(--muted); font-size: 12px; }
.recent-result-row { display: grid; grid-template-columns: 64px minmax(0,1fr) 54px 54px; align-items: center; gap: 10px; padding: 10px 0; border-top: 1px solid var(--line); font-size: 13px; }
.recent-result-row strong { overflow-wrap: anywhere; }
.recent-result-row strong i { color: var(--muted); font-style: normal; }
.recent-result-row b { color: var(--verified); text-align: center; }
.recent-result-row small { color: var(--muted); text-align: right; }
@media (max-width: 520px) { .recent-results { padding: 14px; } .recent-result-row { grid-template-columns: 42px minmax(0,1fr) 42px; gap: 7px; } .recent-result-row small { grid-column: 2 / 4; text-align: left; } }

.league-group { margin-top: 10px; overflow: hidden; border: 1px solid var(--line); border-radius: 12px; background: #FFF; }
.league-title { display: flex; align-items: center; justify-content: space-between; padding: 9px 14px; border-bottom: 1px solid var(--line); background: #FBFBFC; }
.league-title strong { font-size: var(--type-support); }
.league-title span { color: var(--muted); font-size: var(--type-meta); }
.fixture-row.match-card { position: relative; display: grid; grid-template-columns: 126px minmax(340px,1.35fr) minmax(250px,1fr) minmax(180px,.9fr); gap: 16px; align-items: center; min-height: 94px; padding: 13px 16px; border-bottom: 1px solid var(--line); }
.fixture-row.match-card:last-child { border-bottom: 0; }
.fixture-row.match-card:hover { background: #FFFDFC; box-shadow: inset 3px 0 0 var(--orange); }
.fixture-row > * { min-width: 0; }
.fixture-row > *:not(.fixture-row-target) { position: relative; z-index: 1; pointer-events: none; }
.fixture-row-target { position: absolute; inset: 0; z-index: 2; border-radius: inherit; }
.fixture-row-target:focus-visible { outline: 2px solid var(--orange); outline-offset: -3px; }
.match-id strong, .match-id span { display: block; }
.match-id strong { color: var(--ink); font-size: var(--type-meta); font-weight: 700; font-variant-numeric: tabular-nums; }
.match-id span { margin-top: 3px; overflow: hidden; color: var(--muted); font-size: var(--type-meta); text-overflow: ellipsis; white-space: nowrap; }
.teams-line { display: grid; grid-template-columns: minmax(0,1fr) 36px minmax(0,1fr); gap: 10px; align-items: center; }
.matchup-side { display: flex; align-items: center; gap: 10px; }
.matchup-side.matchup-home { justify-content: flex-end; text-align: right; }
.matchup-side.matchup-away { justify-content: flex-start; text-align: left; }
.matchup-name { font-size: var(--type-body); font-weight: 760; line-height: 1.3; }
.teams-status { grid-column: 1 / -1; margin-top: -2px; color: var(--muted); font-size: var(--type-meta); line-height: 1.35; text-align: center; }
.mini-crest { display: inline-grid; flex: 0 0 36px; place-items: center; width: 36px; height: 36px; border: 0; border-radius: 0; background: transparent; color: var(--blue); font-size: var(--type-meta); font-weight: 800; }
.mini-crest.team-badge { flex-basis: 36px; }
.mini-crest[data-crest-kind="fallback"], .mini-crest.team-badge-fallback { flex-basis: 32px; width: 32px; height: 32px; border: 1px solid var(--line-2); border-radius: 7px; background: #F4F5F6; }
.mini-crest img { object-fit: contain; }
.compact-prob { display: grid; gap: 9px; min-width: 0; }
.compact-prob-label { color: var(--muted); font-size: var(--type-meta); }
.compact-prob-values { display: grid; grid-template-columns: repeat(3,1fr); font-size: 13px; font-weight: 760; font-variant-numeric: tabular-nums; }
.compact-prob-values span:nth-child(1) { color: var(--blue); }
.compact-prob-values span:nth-child(2) { color: var(--ink); text-align: center; }
.compact-prob-values span:nth-child(3) { color: var(--red); text-align: right; }
.compact-prob .probbar { margin: 0; height: 8px; }
.probability-cell-group { display: grid; gap: 9px; min-width: 0; }
.compact-score { min-width: 0; color: #3F464E; font-size: var(--type-support); font-variant-numeric: tabular-nums; }
.score-caption { display: block; margin-bottom: 3px; color: var(--muted); font-size: var(--type-meta); }
.compact-score-lines { display: grid; grid-template-columns: repeat(3,minmax(0,1fr)); gap: 7px; }
.compact-score-item { display: grid; min-width: 0; gap: 3px; white-space: normal; }
.score-value { color: var(--ink); font-size: calc(15px * var(--ui-text-scale)); font-weight: 760; line-height: 1.1; }
.score-probability { color: var(--muted); font-size: var(--type-meta); font-weight: 520; line-height: 1.1; }
.compact-score-item:first-child .score-value { font-weight: 800; }
.score-serving-note { margin-top: 5px; color: var(--warning); font-size: var(--type-meta); }
.context-mini { color: #606870; font-size: var(--type-meta); }
.context-mini strong { display: block; color: #111820; font-size: var(--type-body); }
.context-mini .warn { margin-top: 3px; color: var(--warning); }
.context-mini .exception-note { color: var(--warning); }
.context-mini .exception-note.failed, .context-mini .exception-note.missed { color: var(--danger); }
.context-label { display: block; color: var(--orange); font-size: var(--type-meta); }
.recommendation-context { padding-left: 10px; border-left: 2px solid var(--orange); }
.recommendation-context strong { margin-top: 4px; font-size: var(--type-body); }
.recommendation-context.is-abstain strong { color: var(--warning); font-size: var(--type-support); }
.recommendation-reason { display: block; margin-top: 4px; color: var(--muted); font-size: var(--type-meta); line-height: 1.45; }
.reason-detail { display: block; margin-top: 3px; color: var(--muted); font-size: var(--type-meta); line-height: 1.45; }
.fixture-row .matchup-vs { color: var(--orange); font-size: var(--type-meta); }
.prediction-unavailable, .score-unavailable { color: var(--muted); font-size: var(--type-support); }
.filter-empty { padding: 42px 20px; color: var(--muted); text-align: center; }
.history { margin-top: 18px; padding-top: 1px; border-top: 1px solid var(--line); }
.history-heading { display: flex; align-items: baseline; justify-content: space-between; gap: 12px; padding: 17px 0 10px; }
.history-heading h2 { margin: 0; font-size: var(--type-section); letter-spacing: -.02em; }
.history-heading span { color: var(--muted); font-size: var(--type-meta); }
.history-row { display: grid; grid-template-columns: 128px minmax(190px,1fr) minmax(310px,1.25fr) minmax(170px,auto); gap: 16px; align-items: center; min-height: 92px; padding: 12px 0; border-bottom: 1px solid var(--line); font-size: var(--type-body); }
.history-meta { color: var(--muted); font-size: var(--type-meta); }
.history-teams { min-width: 0; overflow-wrap: anywhere; font-weight: 650; }
.history-teams span { color: var(--muted); font-weight: 400; }
.history-result span { display: block; color: var(--muted); font-size: var(--type-meta); }
.history-score { display: block; margin-top: 2px; color: var(--verified); font-size: 20px; font-variant-numeric: tabular-nums; }
.history-links { display: flex; flex-wrap: wrap; gap: 8px; color: var(--muted); font-size: var(--type-meta); }
.history-links a { text-decoration: none; }
.history-links a:hover { color: var(--orange); text-decoration: underline; }
.history-match { min-width: 0; }
.history-context { display: grid; gap: 7px; min-width: 0; }
.history-context > div { min-width: 0; }
.history-context span, .history-context strong { display: block; }
.history-context span { color: var(--muted); font-size: var(--type-meta); }
.history-context strong { margin-top: 2px; color: var(--ink); font-size: var(--type-support); font-weight: 650; overflow-wrap: anywhere; }
.history-context-missing strong { color: var(--warning); }
.history-empty { padding: 22px 0; color: var(--muted); font-size: var(--type-support); }
.trust-history { margin-top: 18px; scroll-margin-top: 16px; }
.trust-history-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; }
.trust-history-head h2 { margin: 0; font-size: var(--type-section); }
.trust-history-head p { max-width: 720px; margin: 6px 0 0; color: var(--muted); font-size: var(--type-support); }
.trust-status { flex: none; padding: 5px 9px; border: 1px solid var(--line-2); border-radius: 99px; color: var(--muted); font-size: var(--type-meta); }
.trust-status.available { border-color: #A7D6B9; background: #EFFAF2; color: var(--verified); }
.trust-status.degraded { border-color: #F2CB9E; background: var(--warning-soft); color: var(--warning); }
.trust-status.unavailable { border-color: #E3B5B0; background: var(--danger-soft); color: var(--danger); }
.trust-metric-grid { display: grid; grid-template-columns: repeat(3, minmax(0,1fr)); gap: 8px; margin-top: 13px; }
.trust-metric { min-width: 0; padding: 11px 12px; border: 1px solid var(--line); border-radius: 9px; background: var(--card-soft); }
.trust-metric span, .trust-metric strong, .trust-metric small { display: block; }
.trust-metric span { color: var(--muted); font-size: var(--type-meta); }
.trust-metric strong { margin-top: 5px; color: var(--ink); font-size: calc(18px * var(--ui-text-scale)); font-variant-numeric: tabular-nums; }
.trust-metric small { margin-top: 4px; color: var(--muted); font-size: var(--type-meta); line-height: 1.4; }
.trust-comparator { margin-top: 10px; padding: 11px 12px; border-top: 1px solid var(--line); color: var(--muted); font-size: var(--type-support); }
.trust-comparator strong { color: var(--ink); }
.trust-comparator-grid { display: flex; flex-wrap: wrap; gap: 8px 18px; margin-top: 6px; }
.trust-comparator-grid span { color: var(--muted); }
.trust-control-values { display: grid; gap: 4px; margin-top: 8px; }
.trust-control-values strong { color: var(--ink); }
.trust-calibration { margin-top: 12px; overflow-x: hidden; }
.trust-calibration > strong, .trust-calibration-note { display: block; }
.trust-calibration-note { margin-top: 4px; color: var(--muted); font-size: var(--type-meta); }
.trust-calibration table { width: 100%; margin-top: 7px; border-collapse: collapse; table-layout: fixed; font-size: var(--type-meta); }
.trust-calibration th, .trust-calibration td { padding: 7px 6px; border-bottom: 1px solid var(--line); text-align: left; vertical-align: top; overflow-wrap: anywhere; }
.trust-calibration th { color: var(--muted); font-weight: 650; }
.trust-calibration td span { display: block; line-height: 1.45; }
.trust-history-list { margin-top: 10px; border-top: 1px solid var(--line); }
.trust-history-row { display: grid; grid-template-columns: minmax(180px,1.2fr) 130px 130px minmax(180px,1fr) 100px; gap: 12px; align-items: center; min-height: 62px; padding: 10px 0; border-bottom: 1px solid var(--line); }
.trust-history-row > * { min-width: 0; }
.trust-history-row span, .trust-history-row strong { display: block; }
.trust-history-row span { color: var(--muted); font-size: var(--type-meta); }
.trust-history-row strong { margin-top: 3px; color: var(--ink); font-size: var(--type-support); overflow-wrap: anywhere; }
.trust-history-row .trust-hit { color: var(--verified); }
.trust-history-row .trust-miss { color: var(--danger); }
.trust-history-row .trust-pending { color: var(--warning); }
.trust-history-note { margin-top: 9px; color: var(--muted); font-size: var(--type-meta); }
.dashboard-trust { padding: 8px 0 0; }
.dashboard-trust strong, .dashboard-trust span { display: block; margin-top: 3px; }
.dashboard-data-method { scroll-margin-top: 16px; }
.page-footer { display: flex; justify-content: space-between; gap: 18px; margin-top: 10px; padding: 10px 14px 14px; border-top: 1px solid var(--line); color: var(--quiet); font-size: var(--type-meta); }
.page-footer span:last-child { max-width: 52%; text-align: right; }
.sr-only { position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px; overflow: hidden; clip: rect(0,0,0,0); white-space: nowrap; border: 0; }

@media (max-width: 980px) {
  .fixture-row.match-card { grid-template-columns: 110px minmax(250px,1.2fr) minmax(200px,1fr) minmax(160px,.9fr); gap: 12px; padding-left: 14px; padding-right: 14px; }
}
@media (max-width: 820px) {
  .dashboard-page .content { padding-bottom: 71px; }
  .matches-head { display: block; padding: 12px 0 7px; }
  .matches-head h1 { font-size: var(--type-section); }
  .matches-head p { display: none; }
  .chips { margin-top: 10px; }
  .chip { flex: 1; padding: 8px 4px; text-align: center; font-size: var(--type-meta); }
  .filters { gap: 5px; }
  .filter { min-width: 58px; min-height: 44px; padding: 8px 10px; }
  .fixture-table { margin: 0 -14px; }
  .league-group { margin: 0; border: 0; border-radius: 0; }
  .league-title { padding: 9px 14px; }
  .fixture-row.match-card { display: block; min-height: 0; padding: 15px 14px; }
  .fixture-row.match-card > * { margin-top: 9px; }
  .fixture-row.match-card > .fixture-row-target { margin-top: 0; }
  .match-id { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
  .match-id span { margin: 0; }
  .teams-line { margin-top: 12px; grid-template-columns: minmax(0,1fr) 34px minmax(0,1fr); gap: 8px; }
  .matchup-side { gap: 8px; }
  .matchup-name { font-size: var(--type-body); }
  .teams-status { margin-top: 0; font-size: var(--type-meta); }
  .mini-crest { flex-basis: 34px; width: 34px; height: 34px; }
  .mini-crest.team-badge { flex-basis: 34px; }
  .compact-prob { margin-top: 12px; }
  .compact-prob-label { font-size: var(--type-meta); }
  .compact-prob-values { font-size: var(--type-body); }
  .compact-score { margin-top: 12px; padding-top: 9px; border-top: 1px solid var(--line); font-size: var(--type-support); }
  .score-caption { font-size: var(--type-meta); }
  .compact-score-lines { gap: 5px; }
  .context-mini { display: block; margin-top: 10px; }
  .recommendation-context strong { font-size: var(--type-body); }
  .history { margin-top: 25px; }
  .history-row { display: block; min-height: 0; padding: 14px 0; }
  .history-row > * { margin-top: 10px; }
  .history-row > .history-result { margin-top: 0; }
  .history-match { margin-top: 10px; }
  .history-context { margin-top: 10px; }
  .history-links { margin-top: 10px; }
  .history-meta, .history-links { grid-column: 1 / -1; }
  .trust-history { margin-top: 25px; }
  .trust-history-head { display: block; }
  .trust-status { display: inline-block; margin-top: 9px; }
  .trust-metric-grid { grid-template-columns: repeat(2,minmax(0,1fr)); }
  .trust-history-row { display: block; min-height: 0; padding: 12px 0; }
  .trust-history-row > * { margin-top: 8px; }
  .trust-history-row > :first-child { margin-top: 0; }
  .trust-comparator-grid { display: grid; gap: 5px; }
  .trust-calibration th, .trust-calibration td { padding: 6px 3px; font-size: 11px; }
  .page-footer { display: block; }
  .page-footer span { display: block; }
  .page-footer span:last-child { max-width: none; margin-top: 6px; text-align: left; }
  .dashboard-data-method { display: grid; grid-template-columns: repeat(2,minmax(0,1fr)); margin-top: 14px; }
  .dashboard-data-method .trust-item { min-width: 0; border-right: 0; border-bottom: 1px solid var(--line); padding: 12px 10px; }
  .dashboard-data-method .trust-item:nth-child(odd) { border-right: 1px solid var(--line); }
  .dashboard-data-method .trust-item:nth-last-child(-n+2) { border-bottom: 0; }
}
@media (max-width: 360px) {
  .dashboard-page .content { padding-left: 12px; padding-right: 12px; }
  .fixture-table { margin-left: -12px; margin-right: -12px; }
  .fixture-row.match-card { padding-left: 12px; padding-right: 12px; }
  .matchup-name { font-size: var(--type-body); }
  .mini-crest { flex-basis: 32px; width: 32px; height: 32px; }
  .mini-crest.team-badge { flex-basis: 32px; }
  .compact-score-lines { gap: 4px; }
  .page-footer { padding-left: 12px; padding-right: 12px; }
}
"""



def _format_kickoff(value: Any) -> str:
    text = str(value or "").replace("T", " ")
    if "+08:00" in text:
        text = text.replace("+08:00", "")
    return text[:16] if text else "时间待补"


def _format_updated_at(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return "时间待补"
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo:
            parsed = parsed.astimezone(SHANGHAI)
        return parsed.strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return text[:16].replace("T", " ")


def _health_watch_quality_for_cycle(
    health_watch: dict[str, Any],
    runtime: dict[str, Any],
    business_date: str,
) -> tuple[dict[str, Any] | None, str]:
    persisted = health_watch.get("prediction_quality_health")
    if not isinstance(persisted, dict):
        return None, "UNAVAILABLE"
    runtime_business_date = str(runtime.get("business_date") or "").strip()
    runtime_finished_at = str(runtime.get("finished_at") or "").strip()
    persisted_date = str(persisted.get("business_date") or "").strip()
    persisted_cycle = str(persisted.get("runtime_cycle_finished_at") or "").strip()
    top_level_date = str(health_watch.get("business_date") or "").strip()
    top_level_cycle = str(health_watch.get("last_cycle_generated_at") or "").strip()
    if (
        not business_date
        or runtime_business_date != business_date
        or not runtime_finished_at
        or persisted.get("scope") != "current_serving"
        or persisted_date != business_date
        or persisted_cycle != runtime_finished_at
        or (top_level_date and top_level_date != business_date)
        or (top_level_cycle and top_level_cycle != runtime_finished_at)
    ):
        return None, "MISMATCHED"
    return persisted, "MATCHED"


def _current_prediction_quality_health(
    records: dict[str, dict[str, Any]],
    exclusions: dict[str, dict[str, Any]],
    jobs: list[dict[str, Any]],
    runtime: dict[str, Any],
    health_watch: dict[str, Any],
    business_date: str,
) -> dict[str, Any]:
    runtime_finished_at = str(runtime.get("finished_at") or "").strip() or None
    persisted, provenance_status = _health_watch_quality_for_cycle(
        health_watch,
        runtime,
        business_date,
    )
    base: dict[str, Any] = {
        "schema_version": "prediction_quality_health.v1",
        "status": "UNKNOWN",
        "overall_status": "UNKNOWN",
        "scope": "current_serving",
        "business_date": business_date or None,
        "runtime_cycle_finished_at": runtime_finished_at,
        "reasons": [],
        "available": False,
        "provenance_status": provenance_status,
        "source": "unavailable",
        "display_status": _QUALITY_STATUS_LABELS["UNKNOWN"],
    }
    if (
        not business_date
        or str(runtime.get("business_date") or "").strip() != business_date
        or not runtime_finished_at
    ):
        return base

    formal_records = [
        record
        for record in records.values()
        if str(record.get("prediction_status") or "").strip() in _CURRENT_FORMAL_STATUSES
    ]
    try:
        selection = select_current_serving_predictions(
            formal_records,
            business_date=business_date,
            current_jobs=jobs,
            excluded_ids=set(exclusions),
        )
        evaluated = evaluate_exact_score_health(selection["selected_records"])
    except (KeyError, TypeError, ValueError):
        return base

    quality = {
        **evaluated,
        "scope": "current_serving",
        "business_date": business_date,
        "runtime_cycle_finished_at": runtime_finished_at,
        "current_job_count": selection.get("current_job_count", 0),
        "unique_current_match_count": selection.get("unique_current_match_count", 0),
        "current_frozen_job_count": selection.get("current_frozen_job_count", 0),
        "duplicate_current_job_count": selection.get("duplicate_current_job_count", 0),
        "duplicate_current_job_keys": selection.get("duplicate_current_job_keys", []),
        "conflicted_current_match_count": selection.get("conflicted_current_match_count", 0),
        "conflicted_current_match_keys": selection.get("conflicted_current_match_keys", []),
        "selected_record_count": selection.get("selected_record_count", 0),
        "selected_job_ids": selection.get("selected_job_ids", []),
        "selected_prediction_ids": selection.get("selected_prediction_ids", []),
        "available": True,
        "provenance_status": provenance_status,
        "source": "current_serving_projection",
    }
    quality["overall_status"] = quality["status"]
    quality["display_status"] = _QUALITY_STATUS_LABELS.get(
        quality["status"],
        quality["status"],
    )
    if persisted is not None:
        if (
            str(persisted.get("status") or "") != quality["status"]
            or list(persisted.get("reasons") or []) != list(quality.get("reasons") or [])
        ):
            quality["provenance_status"] = "MISMATCHED"
    return quality


def _score_label(value: Any) -> str:
    return str(value or "").strip()


def _format_percent(value: Any) -> str | None:
    number = _number(value)
    if number is None or number < 0 or number > 1:
        return None
    return f"{number * 100:.1f}%"


def _score_rows(prediction: dict[str, Any], limit: int = 5) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    by_score: dict[str, dict[str, Any]] = {}
    sources = (
        prediction.get("score_distribution"),
        prediction.get("top_scores"),
        prediction.get("score_top3"),
    )
    for distribution in sources:
        if not isinstance(distribution, list):
            continue
        for item in distribution:
            if isinstance(item, dict):
                score = _score_label(item.get("score") or item.get("value"))
                probability = _number(item.get("probability"))
            else:
                score = _score_label(item)
                probability = None
            if not score:
                continue
            current = by_score.get(score)
            if current is None:
                current = {"score": score, "probability": probability}
                by_score[score] = current
                rows.append(current)
            elif current.get("probability") is None and probability is not None:
                current["probability"] = probability
    primary = _score_label(prediction.get("primary_score") or prediction.get("unique_score"))
    if primary and primary not in by_score:
        rows.insert(0, {"score": primary, "probability": None})
    return rows[:limit]


def _score_accessibility_label(score: str) -> str:
    pair = _score_pair(score)
    if pair is not None:
        return f"\u6bd4\u5206 {pair[0]}\u6bd4{pair[1]}"
    return f"\u6bd4\u5206 {score}"


def _one_x_two_html(prediction: dict[str, Any]) -> str:
    probabilities = prediction.get("probabilities") or {}
    if not isinstance(probabilities, dict):
        return ""
    values = {
        "home": _number(probabilities.get("home")),
        "draw": _number(probabilities.get("draw")),
        "away": _number(probabilities.get("away")),
    }
    fallback = "\u2014"
    unavailable = "\u80dc\u5e73\u8d1f\u6982\u7387\u6682\u4e0d\u53ef\u7528"
    if not all(value is not None and 0 <= value <= 1 for value in values.values()):
        return f'<div class="prediction-unavailable" role="status">{unavailable}</div>'
    total = sum(values.values())
    if total <= 0:
        return f'<div class="prediction-unavailable" role="status">{unavailable}</div>'
    labels = {"home": "\u4e3b\u80dc", "draw": "\u5e73", "away": "\u5ba2\u80dc"}
    segments = "".join(
        f'<span class="probability-segment {key}" style="width:{values[key] / total * 100:.3f}%" aria-hidden="true"></span>'
        for key in ("home", "draw", "away")
    )
    label = "\uff1b".join(f"{labels[key]} {_format_percent(values[key])}" for key in ("home", "draw", "away"))
    value_html = "".join(
        f'<span class="{key}-t" aria-label="{labels[key]} {_format_percent(values[key])}">'
        f'{html.escape(_format_percent(values[key]) or fallback)}</span>'
        for key in ("home", "draw", "away")
    )
    return (
        f'<div class="compact-prob" aria-label="\u80dc / \u5e73 / \u8d1f\u6982\u7387\uff1a{html.escape(label, quote=True)}">'
        '<div class="compact-prob-label">\u80dc / \u5e73 / \u8d1f\u6982\u7387</div>'
        f'<div class="compact-prob-values">{value_html}</div>'
        f'<div class="probbar probability-strip" role="img" aria-label="\u80dc / \u5e73 / \u8d1f\u6982\u7387\u5206\u5e03">{segments}</div></div>'
    )



def _prediction_exact_available(prediction: dict[str, Any]) -> bool:
    formal = prediction.get("formal_markets")
    markets = formal.get("markets") if isinstance(formal, dict) else None
    exact = markets.get("exact_score") if isinstance(markets, dict) else None
    return isinstance(exact, dict) and str(exact.get("status") or "").upper() == "AVAILABLE"


def _total_goal_summary(prediction: dict[str, Any]) -> dict[str, Any] | None:
    totals = prediction.get("totals")
    if not isinstance(totals, list):
        return None
    buckets: dict[str, float] = {}
    for item in totals:
        if not isinstance(item, dict):
            continue
        probability = _number(item.get("probability"))
        if probability is None or not 0 <= probability <= 1:
            continue
        raw_goals = str(item.get("goals") or item.get("total") or "").strip()
        if raw_goals.endswith("+"):
            try:
                bucket = "4+" if int(raw_goals[:-1]) >= 4 else raw_goals
            except ValueError:
                continue
        elif raw_goals.isdigit():
            bucket = raw_goals if int(raw_goals) <= 3 else "4+"
        else:
            continue
        buckets[bucket] = buckets.get(bucket, 0.0) + probability
    if not buckets:
        return None
    top_bucket, top_probability = max(buckets.items(), key=lambda item: item[1])
    return {"bucket": top_bucket, "probability": top_probability, "buckets": buckets}


def _score_summary_html(
    prediction: dict[str, Any],
    *,
    exact_score_serving: dict[str, Any] | None = None,
) -> str:
    serving_state = str((exact_score_serving or {}).get("state") or "UNVERIFIED")
    if not _prediction_exact_available(prediction):
        return (
            '<div class="queue-score score-unavailable" data-score-serving-state="UNAVAILABLE">'
            '<span class="score-caption">\u6bd4\u5206\u6982\u7387</span><strong>\u6682\u4e0d\u53ef\u7528</strong></div>'
        )
    rows = [row for row in _score_rows(prediction, limit=3) if row.get("probability") is not None]
    rendered_rows = []
    for rank, row in enumerate(rows, start=1):
        probability = _format_percent(row.get("probability"))
        if not probability:
            continue
        score = str(row["score"])
        accessibility_label = f'{_score_accessibility_label(score)}\uff0c\u6982\u7387 {probability}'
        rendered_rows.append(
            f'<span class="compact-score-item" data-score-rank="{rank}" '
            f'aria-label="{html.escape(accessibility_label, quote=True)}">'
            f'<strong class="score-value">{html.escape(score)}</strong>'
            f'<span class="score-probability">{html.escape(probability)}</span></span>'
        )
    if not rendered_rows:
        return ""
    local_context = ""
    if serving_state != "NORMAL":
        local_context = '<div class="score-serving-note">\u6bd4\u5206\u6982\u7387\u4ec5\u4f9b\u89c2\u5bdf</div>'
    state_class = " score-unverified" if serving_state != "NORMAL" else ""
    return (
        f'<div class="queue-score score-cell{state_class}" data-score-serving-state="{html.escape(serving_state, quote=True)}">'
        '<div class="score-caption">\u6700\u53ef\u80fd\u6bd4\u5206\uff08\u524d3\uff09</div>'
        f'<div class="compact-score-lines">{"".join(rendered_rows)}</div>'
        f'{local_context}</div>'
    )


def _market_divergence_html(prediction: dict[str, Any]) -> str:
    market = prediction.get("market_summary")
    if not isinstance(market, dict):
        return ""
    comparison = market.get("model_comparison")
    if not isinstance(comparison, dict):
        comparison = market
    model_probability = _number(
        comparison.get("model_home_probability") or comparison.get("model_home")
    )
    market_probability = _number(
        comparison.get("market_home_probability") or comparison.get("market_home")
    )
    if (
        model_probability is None
        or market_probability is None
        or not (0 <= model_probability <= 1 and 0 <= market_probability <= 1)
    ):
        return ""
    difference = model_probability - market_probability
    sign = "+" if difference >= 0 else ""
    difference_text = f"{sign}{difference * 100:.1f} \u4e2a\u767e\u5206\u70b9"
    return (
        '<div class="context-item"><span class="context-label">市场对照</span>'
        f'<span class="context-value">主胜 {_format_percent(model_probability)} · 市场 {_format_percent(market_probability)}</span>'
        f'<small class="context-note">差异 {html.escape(difference_text)}</small></div>'
    )


def _queue_context_html(prediction: dict[str, Any]) -> str:
    # The default Today queue has one launch hierarchy: FT 1X2 plus Exact
    # Score Top3. Totals and market context remain detail-level supporting views.
    return ""


def _card_status_copy(card: dict[str, Any]) -> str:
    if card.get("result"):
        return "\u5df2\u7ed3\u675f"
    if str(card.get("status") or "").upper() == "FROZEN" and isinstance(card.get("prediction"), dict):
        return ""
    return {
        "CURRENT_JOB_STATE_CONFLICT": "\u672c\u573a\u72b6\u6001\u5f85\u786e\u8ba4\uff0c\u6682\u4e0d\u9884\u6d4b",
        "PENDING": "\u9884\u6d4b\u5c1a\u672a\u5f62\u6210",
        "INSUFFICIENT_DATA": "\u6570\u636e\u4e0d\u8db3\uff0c\u6682\u4e0d\u9884\u6d4b",
        "PREDICTION_FAILED": "\u672c\u573a\u672a\u5f62\u6210\u6709\u6548\u9884\u6d4b",
        "MISSED_PREMATCH_WINDOW": "\u672a\u5f62\u6210\u5408\u6cd5\u8d5b\u524d\u9884\u6d4b",
    }.get(str(card.get("status") or "PENDING"), "\u5f53\u524d\u6682\u4e0d\u9884\u6d4b")


def _modern_card_html(
    card: dict[str, Any],
    *,
    exact_score_serving: dict[str, str] | None = None,
) -> str:
    status = str(card.get("status") or "PENDING")
    match_id = str(card.get("match_id") or "")
    prediction = card.get("prediction") if status == "FROZEN" else None
    prediction = prediction if isinstance(prediction, dict) else None
    result = card.get("result") if isinstance(card.get("result"), dict) else None
    has_result = bool(result and result.get("score_90m"))
    prediction_kind = "pilot" if card.get("pilot_excluded") and prediction else "formal" if prediction else "none"
    status_class = html.escape(status.lower(), quote=True)
    home_value = card.get("home") or "\u4e3b\u961f\u5f85\u5b9a"
    away_value = card.get("away") or "\u5ba2\u961f\u5f85\u5b9a"
    home_text = html.escape(str(home_value))
    away_text = html.escape(str(away_value))
    status_line = _card_status_copy(card)
    if has_result:
        status_line = f'90\u5206\u949f\u8d5b\u679c {result.get("score_90m")}'
    status_html = (
        f'<span class="teams-status">{html.escape(status_line)}</span>'
        if status_line
        else ""
    )
    teams_html = (
        '<div class="matchup-side matchup-home">'
        f'{render_team_badge(home_value, card.get("home_crest"), side="home", variant="mini-crest")}'
        f'<strong class="matchup-name">{home_text}</strong></div>'
        '<span class="matchup-vs" aria-hidden="true">VS</span>'
        '<div class="matchup-side matchup-away">'
        f'<strong class="matchup-name">{away_text}</strong>'
        f'{render_team_badge(away_value, card.get("away_crest"), side="away", variant="mini-crest")}</div>'
        f'{status_html}'
    )
    probability_html = _one_x_two_html(prediction) if prediction else '<div class="prediction-unavailable">\u2014</div>'
    score_html = (
        _score_summary_html(prediction, exact_score_serving=exact_score_serving)
        if prediction
        else '<div class="queue-score score-unavailable" data-score-serving-state="UNAVAILABLE"><span class="score-caption">\u6bd4\u5206\u6982\u7387</span><strong>\u6682\u4e0d\u53ef\u7528</strong></div>'
    )
    if prediction:
        recommendation = select_primary_recommendation(
            prediction,
            exact_score_serving=exact_score_serving,
            prediction_allowed=not bool(card.get("pilot_excluded")),
        )
        if recommendation["status"] == "SELECTED":
            context_html = (
                '<div class="context-mini recommendation-context" data-recommendation-status="SELECTED">'
                '<span class="context-label">\u9996\u9009\u65b9\u5411</span>'
                f'<strong>{html.escape(str(recommendation["label"]))}</strong>'
                f'<span class="recommendation-reason">{html.escape(str(recommendation["reason"]))}</span>'
                '</div>'
            )
        else:
            pilot_warning = (
                '<span class="recommendation-warning">\u6bd4\u5206\u6982\u7387\u4ec5\u4f9b\u89c2\u5bdf</span>'
                if card.get("pilot_excluded")
                else ""
            )
            context_html = (
                '<div class="context-mini recommendation-context is-abstain" data-recommendation-status="ABSTAIN">'
                '<span class="context-label">\u9996\u9009\u65b9\u5411</span>'
                f'<strong class="exception-note">{html.escape(str(recommendation["label"]))}</strong>'
                f'<span class="recommendation-reason">{html.escape(str(recommendation["reason"]))}</span>'
                f'{pilot_warning}'
                '</div>'
            )
    else:
        note_class = " failed" if status == "PREDICTION_FAILED" else " missed" if status == "MISSED_PREMATCH_WINDOW" else ""
        reason_text = str(card.get("reason_text") or "").strip()
        reason_html = (
            f'<span class="reason-detail">{html.escape(reason_text)}</span>'
            if reason_text and reason_text != status_line
            else ""
        )
        context_html = (
            f'<div class="context-mini recommendation-context is-abstain" data-recommendation-status="ABSTAIN">'
            f'<span class="context-label">\u9996\u9009\u65b9\u5411</span>'
            f'<strong class="exception-note{note_class}">\u6682\u65e0\u660e\u786e\u9996\u9009\u65b9\u5411</strong>'
            f'<span class="recommendation-reason">{html.escape(status_line)}</span>'
            f'{reason_html}</div>'
        )
    match_number_text = _esc(card.get("match_num"), "\u2014")
    competition_text = _esc(card.get("competition"), "\u8d5b\u4e8b\u5f85\u5b9a")
    kickoff_text = html.escape(_format_kickoff(card.get("kickoff")))
    kickoff_timestamp = html.escape(str(card.get("kickoff_timestamp") or _kickoff_timestamp(card.get("kickoff")) or ""), quote=True)
    detail_target = ""
    if match_id:
        match_id_html = html.escape(match_id, quote=True)
        detail_home = _text(card.get("home"), "\u4e3b\u961f\u5f85\u5b9a")
        detail_away = _text(card.get("away"), "\u5ba2\u961f\u5f85\u5b9a")
        detail_label = html.escape(f'{detail_home} \u5bf9\u9635 {detail_away} \u00b7 \u67e5\u770b\u8be6\u60c5', quote=True)
        detail_target = (
            f'<a class="fixture-row-target" href="../matches/{match_id_html}/" '
            f'aria-label="{detail_label}"></a>'
        )
    return (
        f'<article class="fixture-row match-card status-{status_class} prediction-{prediction_kind}" '
        f'data-status="{html.escape(status, quote=True)}" '
        f'data-result="{"yes" if has_result else "no"}" '
        f'data-kickoff="{kickoff_timestamp}" '
        f'data-prediction-kind="{prediction_kind}" '
        'data-one-x-two-serving-state="CAUTION">'
        f'{detail_target}'
        '<div class="match-id">'
        f'<strong class="match-number">{match_number_text}</strong>'
        f'<span>{competition_text} \u00b7 {kickoff_text}</span>'
        '</div>'
        f'<div class="teams-line" data-matchup="true" aria-label="{home_text} VS {away_text}">{teams_html}</div>'
        f'<div class="probability-cell-group">{probability_html}{score_html}</div>'
        f'{context_html}'
        '</article>'
    )


def _league_groups_html(
    cards: list[dict[str, Any]],
    *,
    exact_score_serving: dict[str, str] | None = None,
    default_business_date: str | None = None,
) -> str:
    """Group by exact business day and competition, preserving card order."""

    groups: dict[tuple[str | None, str], list[dict[str, Any]]] = {}
    for card in cards:
        if not isinstance(card, dict):
            continue
        raw_date = card.get("business_date")
        business_date = str(raw_date) if raw_date not in (None, "") else default_business_date
        label = _text(card.get("competition"), "\u8d5b\u4e8b\u5f85\u5b9a")
        groups.setdefault((business_date, label), []).append(card)
    sections = []
    for (business_date, competition), group in groups.items():
        cards_html = "".join(
            _modern_card_html(card, exact_score_serving=exact_score_serving)
            for card in group
        )
        date_label = ""
        if business_date:
            match = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", business_date)
            if match:
                month, day = int(match.group(2)), int(match.group(3))
                date_label = f"\u7ade\u5f69\u65e5 {month}\u6708{day}\u65e5 \u00b7 "
            else:
                date_label = f"\u7ade\u5f69\u65e5 {html.escape(business_date)} \u00b7 "
        heading = f"{date_label}{html.escape(competition)}"
        sections.append(
            f'<section class="league-group" data-business-date="{html.escape(business_date or "", quote=True)}" data-league="{html.escape(competition, quote=True)}">'
            f'<div class="league-title"><strong>{heading}</strong>'
            f'<span>{len(group)} \u573a \u203a</span></div>{cards_html}</section>'
        )
    return "".join(sections)


def _history_prematch_context(
    row: dict[str, Any],
    records: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    """Project only an already-linked immutable prematch record for history."""

    supplied = row.get("prematch_context") or row.get("_prematch_context")
    if isinstance(supplied, dict):
        return supplied or None
    review = row.get("review") if isinstance(row.get("review"), dict) else {}
    prediction_id = str(
        row.get("prediction_id")
        or review.get("prediction_id")
        or ""
    ).strip()
    if not prediction_id or row.get("prediction_frozen") is False:
        return None
    record = (records or {}).get(prediction_id)
    if not isinstance(record, dict):
        return None
    raw_probabilities = record.get("fusion_1X2") or record.get("probabilities")
    probabilities: dict[str, float] = {}
    if isinstance(raw_probabilities, dict):
        for key in ("home", "draw", "away"):
            number = _number(raw_probabilities.get(key))
            if number is not None and 0 <= number <= 1:
                probabilities[key] = number
    raw_scores = record.get("score_top3") or record.get("top_scores") or []
    scores: list[str] = []
    if isinstance(raw_scores, list):
        for item in raw_scores:
            value = item.get("score") if isinstance(item, dict) else item
            value = str(value or "").strip()
            if value and value not in scores:
                scores.append(value)
    if not probabilities and not scores:
        return None
    return {
        "ft_probabilities": probabilities,
        "exact_top_scores": scores[:3],
    }


def _attach_history_prematch_context(
    rows: list[dict[str, Any]],
    records: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    enriched: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        item = dict(row)
        context = _history_prematch_context(item, records)
        if context is not None:
            item["prematch_context"] = context
        enriched.append(item)
    return enriched


def _history_context_html(row: dict[str, Any], result: str) -> str:
    context = _history_prematch_context(row)
    if not context:
        return (
            '<div class="history-context history-context-missing" data-prematch-record="missing">'
            '<div><span>\u8d5b\u524d\u9884\u6d4b\u6458\u8981</span><strong>\u5f53\u65f6\u672a\u6b63\u5f0f\u8bb0\u5f55</strong></div>'
            '</div>'
        )
    probabilities = context.get("ft_probabilities")
    if isinstance(probabilities, dict) and all(key in probabilities for key in ("home", "draw", "away")):
        ft_text = " \u00b7 ".join(
            f"{label} {_format_percent(probabilities[key])}"
            for key, label in (("home", "\u4e3b\u80dc"), ("draw", "\u5e73"), ("away", "\u5ba2\u80dc"))
        )
    else:
        ft_text = "\u5f53\u65f6\u672a\u6b63\u5f0f\u8bb0\u5f55"
    scores = [
        str(score).strip()
        for score in context.get("exact_top_scores") or []
        if str(score).strip()
    ][:3]
    if scores:
        exact_text = " \u00b7 ".join(scores)
        if result:
            exact_text += " \u00b7 " + ("\u5df2\u547d\u4e2d" if result in scores else "\u672a\u547d\u4e2d")
    else:
        exact_text = "\u5f53\u65f6\u672a\u6b63\u5f0f\u8bb0\u5f55"
    return (
        '<div class="history-context" data-prematch-record="available">'
        f'<div><span>\u8d5b\u524d\u80dc / \u5e73 / \u8d1f\u6982\u7387</span><strong>{html.escape(ft_text)}</strong></div>'
        f'<div><span>\u8d5b\u524d\u6700\u53ef\u80fd\u6bd4\u5206\uff08\u524d3\uff09</span><strong>{html.escape(exact_text)}</strong></div>'
        '</div>'
    )


def _historical_results_html(rows: list[dict[str, Any]]) -> str:
    cards = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        result = row.get("result_90m")
        if not result:
            continue
        kickoff_text = _esc(row.get("kickoff"), "\u65f6\u95f4\u5f85\u5b9a")
        home_text = _esc(row.get("home"), "\u4e3b\u961f\u5f85\u5b9a")
        away_text = _esc(row.get("away"), "\u5ba2\u961f\u5f85\u5b9a")
        links = []
        if row.get("prematch_report_url"):
            links.append(
                f'<a href="{html.escape(str(row["prematch_report_url"]), quote=True)}">\u8d5b\u524d\u5feb\u7167</a>'
            )
        if row.get("postmatch_report_url"):
            links.append(
                f'<a href="{html.escape(str(row["postmatch_report_url"]), quote=True)}">\u8d5b\u540e\u590d\u76d8</a>'
            )
        link_text = " \u00b7 ".join(links) or '<span>\u6682\u65e0\u53ef\u7528\u590d\u76d8\u94fe\u63a5</span>'
        cards.append(
            '<article class="history-row" data-result="yes">'
            f'<div class="history-result"><span>90\u5206\u949f\u8d5b\u679c</span><strong class="history-score">{html.escape(str(result))}</strong></div>'
            f'<div class="history-match"><div class="history-teams">{home_text}<span> vs </span>{away_text}</div>'
            f'<div class="history-meta">{kickoff_text}</div></div>'
            f'{_history_context_html(row, str(result))}'
            f'<div class="history-links">{link_text}</div>'
            '</article>'
        )
    return (
        '<section id="historical-results" class="history" aria-labelledby="history-title">'
        '<div class="history-heading"><h2 id="history-title">\u5386\u53f2\u9a8c\u8bc1</h2>'
        f'<span>{len(cards)} \u573a\u5df2\u6838\u9a8c\u8bb0\u5f55 \u00b7 \u7ed3\u679c\u4f18\u5148</span></div>'
        + ("".join(cards) if cards else '<div class="history-empty" data-history-empty="true">\u6682\u65e0\u5df2\u5b8c\u6210\u5e76\u6838\u9a8c\u7684\u6bd4\u8d5b\u3002</div>')
        + '</section>'
    )


def _previous_business_day_html(data: dict[str, Any] | None) -> str:
    if not isinstance(data, dict):
        return ""
    rows = []
    for entry in data.get("entries", []):
        state = "已核验" if entry.get("status") == "VERIFIED" else "待核验"
        score = entry.get("90m_score") or "—"
        rows.append(
            f'<div class="recent-result-row"><span>{_esc(entry.get("match_num"))}</span>'
            f'<strong>{_esc(entry.get("home"))} <i>vs</i> {_esc(entry.get("away"))}</strong>'
            f'<b>{_esc(score)}</b><small>{state}</small></div>'
        )
    return (
        '<section class="recent-results" id="previous-business-day-results">'
        f'<div class="recent-results-head"><div><h2>前一竞彩日赛果</h2>'
        f'<p>{html.escape(str(data.get("business_date")))} · '
        f'{data.get("verified_count", 0)}/{data.get("fixture_count", 0)} 场已核验</p></div></div>'
        + "".join(rows)
        + '<p class="recent-results-note">MISSED_PREMATCH_WINDOW 比赛仅展示赛果，不计入预测命中率。</p></section>'
    )

def _trust_metric_text(value: Any, *, percent: bool = False) -> str:
    number = _number(value)
    if number is None:
        return "—"
    return f"{number * 100:.1f}%" if percent else f"{number:.3f}"


def _trust_signed_percent(value: Any) -> str:
    number = _number(value)
    return "—" if number is None else f"{number * 100:+.1f}%"


def _trust_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _trust_hit_text(value: Any) -> tuple[str, str]:
    if value is True or value == 1:
        return "命中", "trust-hit"
    if value is False or value == 0:
        return "未命中", "trust-miss"
    return "—", ""


def _trust_pending_result_label(
    row: dict[str, Any], generated_at: datetime | None
) -> str:
    text = str(row.get("kickoff_at") or "").strip()
    try:
        kickoff = datetime.fromisoformat(text.replace("Z", "+00:00")) if text else None
    except ValueError:
        kickoff = None
    if (
        kickoff is None
        or kickoff.tzinfo is None
        or generated_at is None
        or generated_at.tzinfo is None
    ):
        return "赛果待核验"
    kickoff = kickoff.astimezone(timezone.utc)
    generated_at = generated_at.astimezone(timezone.utc)
    if generated_at < kickoff:
        return "未开赛"
    if generated_at < kickoff + timedelta(hours=3):
        return "等待完赛"
    return "赛果待核验"


def _trust_history_html(trust: dict[str, Any] | None) -> str:
    trust = trust if isinstance(trust, dict) else {}
    status = str(trust.get("status") or "UNAVAILABLE").upper()
    status_class = status.lower() if status in {"AVAILABLE", "DEGRADED", "UNAVAILABLE"} else "unavailable"
    status_label = str(trust.get("status_label") or {
        "AVAILABLE": "持续更新中",
        "DEGRADED": "证据正在补齐",
        "UNAVAILABLE": "暂时无法形成可信记录",
    }.get(status, "暂待确认"))
    model = trust.get("model") if isinstance(trust.get("model"), dict) else {}
    cohort = trust.get("cohort") if isinstance(trust.get("cohort"), dict) else {}
    metrics = trust.get("metrics") if isinstance(trust.get("metrics"), dict) else {}
    ft = metrics.get("ft_1x2") if isinstance(metrics.get("ft_1x2"), dict) else {}
    ft_top1 = ft.get("top1_accuracy") if isinstance(ft.get("top1_accuracy"), dict) else {}
    ft_log_loss = ft.get("log_loss") if isinstance(ft.get("log_loss"), dict) else {}
    ft_brier = ft.get("brier") if isinstance(ft.get("brier"), dict) else {}
    exact = metrics.get("exact_score") if isinstance(metrics.get("exact_score"), dict) else {}
    exact_top1 = exact.get("top1") if isinstance(exact.get("top1"), dict) else {}
    exact_top3 = exact.get("top3") if isinstance(exact.get("top3"), dict) else {}
    exact_top5 = exact.get("top5") if isinstance(exact.get("top5"), dict) else {}
    exact_nll = exact.get("formal_nll") if isinstance(exact.get("formal_nll"), dict) else {}
    freshness = trust.get("freshness") if isinstance(trust.get("freshness"), dict) else {}
    calibration = trust.get("calibration") if isinstance(trust.get("calibration"), dict) else {}
    comparator = trust.get("comparator") if isinstance(trust.get("comparator"), dict) else {}
    diagnostics = trust.get("collapse_diagnostics") if isinstance(trust.get("collapse_diagnostics"), dict) else {}
    one_one = diagnostics.get("one_one_top1") if isinstance(diagnostics.get("one_one_top1"), dict) else {}
    locked = _trust_int(cohort.get("locked_unique_match_count"))
    settled = _trust_int(cohort.get("settled_unique_match_count"))
    pending = _trust_int(cohort.get("pending_unique_match_count"))
    unresolved = _trust_int(cohort.get("unresolved_unique_match_count"))
    history = [row for row in trust.get("history") or [] if isinstance(row, dict)]
    generated_text = str(trust.get("generated_at") or "").strip()
    try:
        trust_generated_at = datetime.fromisoformat(generated_text.replace("Z", "+00:00")) if generated_text else None
    except ValueError:
        trust_generated_at = None
    pending_labels = [
        _trust_pending_result_label(row, trust_generated_at)
        for row in history
        if str(row.get("status") or "").upper() == "PENDING"
    ]
    pending_not_started = pending_labels.count("未开赛")
    pending_waiting_finish = pending_labels.count("等待完赛")
    pending_result_verification = pending_labels.count("赛果待核验")
    model_version = str(model.get("release_version") or "").strip()
    model_copy = (
        f'当前正式模型{(" · " + html.escape(model_version)) if model_version else ""}'
        if status != "UNAVAILABLE"
        else "当前正式模型记录"
    )
    calibration_labels = (("home", "主胜"), ("draw", "平局"), ("away", "客胜"))
    calibration_bands = {
        key: calibration.get(key) if isinstance(calibration.get(key), list) else []
        for key, _ in calibration_labels
    }
    band_count = max((len(value) for value in calibration_bands.values()), default=0)
    calibration_rows: list[str] = []
    for index in range(band_count):
        bands = [calibration_bands[key] for key, _ in calibration_labels]
        first_band = bands[0][index] if index < len(bands[0]) and isinstance(bands[0][index], dict) else {}
        lower = _trust_metric_text(first_band.get("lower_bound"), percent=True)
        upper = _trust_metric_text(first_band.get("upper_bound"), percent=True)
        bound = f"[{lower}–{upper}{']' if upper == '100.0%' else ')'}"
        cells = []
        for band in bands:
            value = band[index] if index < len(band) and isinstance(band[index], dict) else {}
            n = value.get("n")
            n_text = f"n={_trust_int(n)}" if n is not None else "n=—"
            cells.append(
                f'<td><span>预测 {_trust_metric_text(value.get("mean_predicted"), percent=True)}</span>'
                f'<span>实际 {_trust_metric_text(value.get("observed_frequency"), percent=True)}</span>'
                f'<span>{n_text} · 差 {_trust_signed_percent(value.get("gap"))}</span></td>'
            )
        calibration_rows.append(f'<tr><th scope="row">{bound}</th>{"".join(cells)}</tr>')
    calibration_html = (
        '<div class="trust-calibration" data-trust-calibration="available">'
        '<strong>校准实际值</strong>'
        '<span class="trust-calibration-note">预测概率 → 实际频率；差值为实际−预测；每档保留样本 n。</span>'
        '<table><thead><tr><th scope="col">概率档</th><th scope="col">主胜</th><th scope="col">平局</th><th scope="col">客胜</th></tr></thead>'
        f'<tbody>{"".join(calibration_rows)}</tbody></table></div>'
        if calibration_rows
        else '<div class="trust-calibration" data-trust-calibration="unavailable"><strong>校准实际值</strong><span class="trust-calibration-note">当前暂无可用的分档样本。</span></div>'
    )
    comparator_html = ""
    if str(comparator.get("status") or "").upper() == "AVAILABLE":
        decision = comparator.get("decision") if isinstance(comparator.get("decision"), dict) else {}
        verdict = str(decision.get("verdict") or "").upper()
        verdict_label = (
            "样本仍在积累"
            if verdict == "INSUFFICIENT_SAMPLE_CONTINUE_ACCUMULATING"
            else "结果方向可见，但不确定性仍大"
            if verdict == "DIRECTION_AND_UNCERTAINTY_ONLY_NO_AUTOMATIC_PROMOTION"
            else "样本较充足，继续作为对照"
            if verdict == "MATURE_FOR_SEPARATE_INDEPENDENT_PROMOTION_REGATE"
            else "暂待更多数据"
        )
        champion_unpaired = comparator.get("champion_unpaired_unique_match_count")
        champion_unpaired_html = (
            f'<span>正式模型未配对 {_trust_int(champion_unpaired)} 场</span>'
            if champion_unpaired is not None
            else ""
        )
        comparator_html = (
            '<div class="trust-comparator" data-trust-comparator="available">'
            '<strong>同场市场对照</strong><span>同一赛前时间窗口；差值按市场−当前模型计算。</span>'
            f'<div class="trust-comparator-grid"><span>有效配对 {_trust_int(comparator.get("paired_unique_match_count"))} 场</span>'
            f'<span>市场未配对 {_trust_int(comparator.get("unpaired_unique_match_count"))} 场</span>'
            f'{champion_unpaired_html}'
            f'<span>{html.escape(verdict_label)}</span></div>'
            '</div>'
        )
        deltas = ((comparator.get("metrics") or {}).get("deltas") or {})
        control_rows = []
        for key, label in (("ft_1x2_log_loss", "胜平负平均损失"), ("exact_nll", "准确比分平均损失")):
            delta = deltas.get(key)
            if not isinstance(delta, dict):
                continue
            control_rows.append(
                f'<span>{label}：市场−当前模型 {_trust_metric_text(delta.get("mean"))} · '
                f'95%区间 {_trust_metric_text(delta.get("ci95_low"))} 至 {_trust_metric_text(delta.get("ci95_high"))} · '
                f'n={_trust_int(delta.get("n"))}</span>'
            )
        comparator_html += '<div class="trust-control-values"><strong>市场对照差值</strong>' + "".join(control_rows) + '</div>'
    history.sort(key=lambda row: str(row.get("kickoff_at") or ""), reverse=True)
    history_rows: list[str] = []
    for row in history:
        row_status = str(row.get("status") or "UNRESOLVED").upper()
        if row_status == "SETTLED":
            result = html.escape(str(row.get("actual_score") or "结果待定"))
            ft_text, ft_class = _trust_hit_text(row.get("ft_1x2_hit"))
            exact_text, exact_class = _trust_hit_text(row.get("exact_top1_hit"))
            exact_detail = (
                f'{exact_text} · 前3 {_trust_hit_text(row.get("exact_top3_hit"))[0]} · 前5 {_trust_hit_text(row.get("exact_top5_hit"))[0]}'
            )
            paired_text = "已配对" if row.get("paired") is True else "未配对" if row.get("paired") is False else "—"
        elif row_status == "PENDING":
            result = _trust_pending_result_label(row, trust_generated_at)
            ft_text, exact_detail, paired_text = "—", "—", "—"
            ft_class = exact_class = "trust-pending"
        else:
            result, ft_text, exact_detail, paired_text = "待确认", "—", "—", "—"
            ft_class = exact_class = "trust-pending"
        row_class = "trust-pending" if row_status != "SETTLED" else ""
        history_rows.append(
            f'<div class="trust-history-row {row_class}" data-trust-history-row="true" data-trust-status="{html.escape(row_status, quote=True)}">'
            f'<div><strong>{html.escape(str(row.get("home") or "主队待定"))} <span>vs</span> {html.escape(str(row.get("away") or "客队待定"))}</strong><span>{html.escape(_format_kickoff(row.get("kickoff_at")))}</span></div>'
            f'<div><span>90分钟结果</span><strong>{result}</strong></div>'
            f'<div><span>胜平负首选</span><strong class="{ft_class}">{ft_text}</strong></div>'
            f'<div><span>准确比分</span><strong class="{exact_class}">{exact_detail}</strong></div>'
            f'<div><span>同场对照</span><strong>{html.escape(paired_text)}</strong></div>'
            '</div>'
        )
    history_html = "".join(history_rows) or '<div class="trust-history-note">当前没有可展示的核验记录。</div>'
    collapse_note = (
        f'比分集中诊断：1-1 首选占 {_trust_metric_text(one_one.get("share"), percent=True)}（{_trust_int(one_one.get("n"))} 场）；仅作描述，不改变赛前输出。'
        if _trust_int(one_one.get("n"))
        else "比分集中诊断：当前没有可用的首选比分样本；仅作描述，不改变赛前输出。"
    )
    return (
        f'<section id="trust-history" class="panel trust-history" data-trust-status="{html.escape(status, quote=True)}" aria-labelledby="trust-history-title">'
        '<div class="trust-history-head">'
        '<div><h2 id="trust-history-title">历史信任记录</h2>'
        f'<p>{html.escape(str(trust.get("message") or "命中与失误均保留，结果按90分钟及伤停补时核验。"))}</p></div>'
        f'<span class="trust-status {status_class}">{html.escape(status_label)}</span>'
        '</div>'
        f'<div class="trust-metric-grid">'
        f'<div class="trust-metric"><span>锁定比赛</span><strong>{locked}</strong><small>已核验 {settled} 场 · 未开赛 {pending_not_started} 场 · 等待完赛 {pending_waiting_finish} 场 · 赛果待核验 {pending_result_verification} 场</small></div>'
        f'<div class="trust-metric"><span>胜平负首选命中</span><strong>{_trust_metric_text(ft_top1.get("rate"), percent=True)}</strong><small>有效样本 {_trust_int(ft_top1.get("n"))} 场</small></div>'
        f'<div class="trust-metric"><span>胜平负平均损失</span><strong>{_trust_metric_text(ft_log_loss.get("mean"))}</strong><small>数值越低越好 · 样本 {_trust_int(ft_log_loss.get("n"))}</small></div>'
        f'<div class="trust-metric"><span>准确比分首选</span><strong>{_trust_metric_text(exact_top1.get("rate"), percent=True)}</strong><small>样本 {_trust_int(exact_top1.get("n"))} 场</small></div>'
        f'<div class="trust-metric"><span>准确比分前3覆盖</span><strong>{_trust_metric_text(exact_top3.get("rate"), percent=True)}</strong><small>前5覆盖 {_trust_metric_text(exact_top5.get("rate"), percent=True)}</small></div>'
        f'<div class="trust-metric"><span>正式比分损失</span><strong>{_trust_metric_text(exact_nll.get("mean"))}</strong><small>正式样本 {_trust_int(exact_nll.get("n"))} 场</small></div>'
        '</div>'
        f'<div class="trust-history-note">{html.escape(model_copy)} · 最近核验 {html.escape(_format_updated_at(freshness.get("settled_through")))}</div>'
        f'<div class="trust-history-note">{html.escape(collapse_note)}</div>'
        f'{calibration_html}'
        f'{comparator_html}'
        f'<div class="trust-history-list" aria-label="历史核验记录">{history_html}</div>'
        f'<div class="trust-history-note">共保留 {len(history)} 条记录；命中、未命中、未开赛、等待完赛、赛果待核验与未配对记录不互相覆盖。</div>'
        '</section>'
    )


def _runtime_warning_html(system_health: dict[str, Any], errors: list[Any]) -> str:
    overall = str(system_health.get("overall_status") or system_health.get("status") or "UNKNOWN").upper()
    if overall in {"HEALTHY", "SUCCESS"}:
        return ""
    if overall in {"FAILED", "ALERT"}:
        return (
            '<div class="runtime-warning" role="status">'
            '<strong>\u5f53\u524d\u6570\u636e\u66f4\u65b0\u5f02\u5e38</strong>'
            '<span>\u90e8\u5206\u6bd4\u8d5b\u4fe1\u606f\u53ef\u80fd\u6682\u65f6\u4e0d\u53ef\u7528\uff0c\u8bf7\u4ee5\u9875\u9762\u5b9e\u9645\u5185\u5bb9\u4e3a\u51c6\u3002</span>'
            '</div>'
        )
    if overall in {"UNKNOWN", "RUNNING"} or errors:
        return (
            '<div class="runtime-warning" role="status">'
            '<strong>\u5f53\u524d\u6570\u636e\u72b6\u6001\u5f85\u786e\u8ba4</strong>'
            '<span>\u9875\u9762\u53ea\u5c55\u793a\u5df2\u786e\u8ba4\u7684\u6bd4\u8d5b\u4fe1\u606f\u3002</span>'
            '</div>'
        )
    return ""


def _quality_warning_html(quality_health: dict[str, Any]) -> str:
    exact_score_serving = exact_score_serving_presentation(quality_health)
    state = exact_score_serving["state"]
    if state == "NORMAL":
        return ""
    label = "比分概率仅供观察" if state == "DEGRADED" else "比分概率质量待确认"
    note = (
        "保留原始比分概率，暂不展开解读。"
        if state == "DEGRADED"
        else "先保留已记录的概率，质量确认前暂不展开解读。"
    )
    return (
        '<div class="quality-warning" role="status">'
        f'<strong>{label}</strong><span>{note}</span>'
        '</div>'
    )


STATIC_REFRESH_SCRIPT = """<script>
(() => {
  const latestJson = "./latest.json";
  const pageVersion = __PAGE_VERSION__;
  let currentVersion = pageVersion;
  const versionOf = payload => `${payload?.business_date || payload?.target_date || ""}|${payload?.generated_at || ""}`;
  async function checkForUpdate() {
    if (document.visibilityState !== "visible") return;
    try {
      const response = await fetch(`${latestJson}?t=${Date.now()}`, { cache: "no-store" });
      if (!response.ok) return;
      const version = versionOf(await response.json());
      if (version === "|") return;
      if (version !== currentVersion) {
        const url = new URL(window.location.href);
        url.searchParams.set("v", version);
        window.location.replace(url.toString());
      }
    } catch (_) {}
  }
  window.setInterval(checkForUpdate, 60000);
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") checkForUpdate();
  });
  window.addEventListener("focus", checkForUpdate);
  checkForUpdate();
})();
</script>"""


def summarize_frozen_exact_score_review(payload: dict[str, Any]) -> dict[str, int] | None:
    """Summarize only unique, formally evaluated, verified frozen fixtures."""
    rows, seen = [], set()
    try:
        for f in payload.get("fixtures") or []:
            if not isinstance(f, dict) or f.get("status") != "FROZEN" or f.get("formal_prospective") is not True or f.get("pilot_excluded") is True:
                continue
            date, mid = f.get("business_date"), f.get("match_id")
            if not date or not mid: continue
            key = (date, mid)
            if key in seen: return None
            seen.add(key)
            ev, result = f.get("evaluation") or {}, f.get("result") or {}
            metrics = ev.get("metrics") or {}
            ko = datetime.fromisoformat(f["kickoff_timestamp"].replace("Z", "+00:00"))
            freeze = datetime.fromisoformat(f["selected_freeze_created_at"].replace("Z", "+00:00"))
            cutoff = datetime.fromisoformat(f["selected_source_cutoff_at"].replace("Z", "+00:00"))
            score = result.get("score_90m")
            if (ev.get("kind") != "formal" or metrics.get("exact_score_authority_status") != "FROZEN_PREDICTION_TIME" or
                any(type(metrics.get(k)) is not bool for k in ("exact_score_top1", "exact_score_top3", "exact_score_top5")) or
                not isinstance(score, str) or not re.fullmatch(r"\d{1,2}-\d{1,2}", score) or not freeze < ko or not cutoff < ko):
                continue
            rows.append((f, metrics, score))
    except (KeyError, TypeError, ValueError):
        return None
    if not rows: return None
    return {"count": len(rows), "top1": sum(m["exact_score_top1"] for _,m,_ in rows),
            "top3": sum(m["exact_score_top3"] for _,m,_ in rows), "top5": sum(m["exact_score_top5"] for _,m,_ in rows),
            "predicted_11": sum((f.get("prediction") or {}).get("primary_score") == "1-1" for f,_,_ in rows),
            "actual_11": sum(score == "1-1" for _,_,score in rows),
            "c_count": sum((f.get("prediction") or {}).get("data_grade") == "C" for f,_,_ in rows), "business_days": len({f["business_date"] for f,_,_ in rows})}


def render_frozen_exact_score_review(payload: dict[str, Any]) -> str:
    s = summarize_frozen_exact_score_review(payload)
    if not s: return ""
    return (f'<section class="trust-strip dashboard-trust-strip" aria-label="赛前冻结样本复核">'
            f'<div class="trust-item"><div><strong>Top1 / Top3 / Top5</strong><span>{s["top1"]} / {s["top3"]} / {s["top5"]}（{s["count"]}场）</span></div></div>'
            f'<div class="trust-item"><div><strong>1-1 比分</strong><span>预测 {s["predicted_11"]} 场 · 实际 {s["actual_11"]} 场</span></div></div>'
            f'<div class="trust-item"><div><strong>数据质量</strong><span>C级 {s["c_count"]}/{s["count"]} 场 · {s["business_days"]} 个竞彩日</span></div></div>'
            f'<div class="trust-item"><span>本期已核验赛前冻结样本；小样本仅展示事实，不代表长期命中率</span></div></section>')


def render_dashboard(payload: dict[str, Any]) -> str:
    summary = payload.get("summary") or {}
    system_health = payload.get("system_runtime_health") or payload.get("health") or {}
    quality_health = payload.get("prediction_quality_health") or {}
    date_value = str(payload.get("business_date") or "")
    date_parts = date_value.split("-")
    date_label = (
        f"{int(date_parts[1])}\u6708{int(date_parts[2])}\u65e5"
        if len(date_parts) == 3 and date_parts[1].isdigit() and date_parts[2].isdigit()
        else date_value or "\u6bd4\u8d5b\u65e5"
    )
    business_date_label = f"\u7ade\u5f69\u65e5 {date_label}"
    if int(summary.get("next_business_date_fixture_count") or 0) > 0:
        business_date_label += " \u00b7 \u542b\u4e0b\u4e00\u7ade\u5f69\u65e5"
    fixture_count = int(summary.get("fixture_count") or len(payload.get("fixtures") or []))
    verified_results = int(summary.get("verified_results") or 0)
    exact_score_serving = exact_score_serving_presentation(quality_health)
    cards = [card for card in payload.get("fixtures") or [] if isinstance(card, dict)]
    cards_html = _league_groups_html(
        cards,
        exact_score_serving=exact_score_serving,
        default_business_date=date_value or None,
    )
    dashboard_title = "\u672c\u671f\u6bd4\u8d5b" if int(summary.get("next_business_date_fixture_count") or 0) > 0 else "\u4eca\u65e5\u6bd4\u8d5b"
    overall_empty_html = (
        '<div class="filter-empty" data-filter-empty="ALL">\u4eca\u5929\u6ca1\u6709\u53ef\u5c55\u793a\u7684\u6bd4\u8d5b\u3002</div>'
        if fixture_count == 0
        else ""
    )
    filter_empty_html = (
        f"{overall_empty_html}"
        '<div class="filter-empty" data-filter-empty="UPCOMING" hidden>\u5f53\u524d\u7ade\u5f69\u65e5\u6682\u65e0\u672a\u5f00\u8d5b\u6bd4\u8d5b</div>'
        '<div class="filter-empty" data-filter-empty="RESULT" hidden>\u5f53\u524d\u7ade\u5f69\u65e5\u6682\u65e0\u5df2\u7ed3\u675f\u5e76\u6838\u9a8c\u7684\u6bd4\u8d5b</div>'
    )
    runtime_warning = _runtime_warning_html(system_health, payload.get("data_errors") or [])
    frozen_review_html = render_frozen_exact_score_review(payload)
    # Exact-state caution is rendered once inside the affected score lane.
    quality_warning = ""
    trust_history_html = _trust_history_html(payload.get("prediction_quality_trust"))
    historical_html = _historical_results_html(payload.get("completed") or [])
    previous_html = _previous_business_day_html(payload.get("previous_business_day_results"))
    beginner_help = render_beginner_help()
    dashboard_trust = render_closed_beta_notice("dashboard-trust")
    data_warning = ""
    if summary.get("silent_missing_fixture"):
        data_warning = (
            '<div class="data-warning">\u90e8\u5206\u6bd4\u8d5b\u4fe1\u606f\u672a\u80fd\u5b8c\u6574\u5448\u73b0\uff0c\u9875\u9762\u53ea\u5c55\u793a\u5df2\u786e\u8ba4\u5185\u5bb9\u3002</div>'
        )
    page_version = "|".join(str(payload.get(key) or "") for key in ("business_date", "generated_at"))
    content_html = f"""
<section class="page dashboard-page">
<header class="topbar">
  <div class="crumbs"><strong>{dashboard_title}</strong><span>\u00b7</span><span>{html.escape(business_date_label)}</span></div>
</header>
<div class="content">
<section class="matches-head"><div><h1>{dashboard_title}</h1><p>\u5148\u770b\u8c01\u548c\u8c01\u6bd4\u8d5b\uff0c\u518d\u770b\u80dc / \u5e73 / \u8d1f\u6982\u7387\u4e0e\u6700\u53ef\u80fd\u6bd4\u5206\u3002\u5f02\u5e38\u53ea\u5728\u771f\u6b63\u6539\u53d8\u5224\u65ad\u65f6\u51fa\u73b0\u3002 \u6d4b\u8bd5\u9636\u6bb5 \u00b7 \u4ec5\u4f9b\u8d5b\u524d\u5206\u6790</p></div><div class="chips" aria-label="\u6bd4\u8d5b\u7b5b\u9009"><button class="chip filter" type="button" data-filter="ALL" aria-pressed="true">\u5168\u90e8</button><button class="chip filter" type="button" data-filter="UPCOMING" aria-pressed="false">\u672a\u5f00\u8d5b</button><button class="chip filter" type="button" data-filter="RESULT" data-result-count="{verified_results}" aria-pressed="false">\u5df2\u7ed3\u675f</button></div></section>
{runtime_warning}{quality_warning}{data_warning}{frozen_review_html}
<section class="fixture-table" id="fixture-list" aria-label="\u7ade\u5f69\u65e5\u6bd4\u8d5b\u5217\u8868">
  {cards_html}
  {filter_empty_html}
</section>
{trust_history_html}
{historical_html}
{previous_html}
{beginner_help}
<section class="trust-strip dashboard-trust-strip dashboard-data-method" id="data-method"><div class="trust-item"><span class="trust-ico">\u26bd</span><div><strong>\u4eca\u65e5\u961f\u5217</strong><span>\u9ed8\u8ba4\u53ea\u7a81\u51fa\u80dc / \u5e73 / \u8d1f\u6982\u7387\u4e0e\u6700\u53ef\u80fd\u6bd4\u5206\u3002</span></div></div><div class="trust-item"><span class="trust-ico">!</span><div><strong>\u5f02\u5e38\u63d0\u793a</strong><span>\u53ea\u6709\u771f\u6b63\u6539\u53d8\u5224\u65ad\u65f6\u624d\u51fa\u73b0\u3002</span></div></div><div class="trust-item"><span class="trust-ico">\u25c7</span><div><strong>\u8d5b\u524d\u8bb0\u5f55</strong><span>\u6bd4\u8d5b\u5f00\u59cb\u524d\u5f62\u6210\u5e76\u4fdd\u7559\u3002</span></div></div><div class="trust-item"><span class="trust-ico">\u2713</span><div><strong>\u5386\u53f2\u9a8c\u8bc1</strong><span>\u6210\u529f\u548c\u5931\u8d25\u540c\u53e3\u5f84\u8bb0\u5f55\u3002</span></div></div><div class="trust-item"><span class="trust-ico">i</span><div><strong>\u65b9\u6cd5\u8bf4\u660e</strong><span>\u6280\u672f\u7ec6\u8282\u4e0b\u6c89\uff0c\u4e0d\u62a2\u9996\u5c4f\u3002</span></div></div></section>
{dashboard_trust}
</div>
<section class="footer-principles"><div class="principle-title">OneShot Principles</div><div class="principles"><div class="principle"><span class="principle-icon">\u2606</span><div><strong>\u6e05\u6670\u4f18\u5148</strong><span>\u5148\u770b\u771f\u6b63\u6539\u53d8\u5224\u65ad\u7684\u5185\u5bb9\u3002</span></div></div><div class="principle"><span class="principle-icon">\u25c9</span><div><strong>\u6982\u7387\u8bda\u5b9e</strong><span>\u201c\u6700\u9ad8\u201d\u4e0d\u7b49\u4e8e\u201c\u786e\u5b9a\u201d\u3002</span></div></div><div class="principle"><span class="principle-icon">\u25c7</span><div><strong>\u72ec\u7acb\u5224\u65ad</strong><span>\u6a21\u578b\u548c\u5e02\u573a\u5e76\u5217\u6bd4\u8f83\u3002</span></div></div><div class="principle"><span class="principle-icon">\u2713</span><div><strong>\u4e00\u81f4\u9a8c\u8bc1</strong><span>\u8d5b\u524d\u8bb0\u5f55\u8d5b\u540e\u4e0d\u4fee\u6539\u3002</span></div></div><div class="principle"><span class="principle-icon">\u25a3</span><div><strong>\u6709\u4e0a\u4e0b\u6587\u7684\u6570\u636e</strong><span>\u6570\u5b57\u5fc5\u987b\u80fd\u89e3\u91ca\u3002</span></div></div></div></section><div class="copyright"><span>\u00a9 2026 OneShot</span><span>Closed Beta</span><span>\u4ec5\u4f9b\u6bd4\u8d5b\u5206\u6790\u4e0e\u7814\u7a76\u53c2\u8003</span></div>
</section>
"""
    interaction_script = """<script>
const buttons = Array.from(document.querySelectorAll('[data-filter]'));
const cards = Array.from(document.querySelectorAll('.fixture-row'));
const leagueGroups = Array.from(document.querySelectorAll('.league-group'));
const historicalResults = document.querySelector('#historical-results');
const emptyStates = Array.from(document.querySelectorAll('[data-filter-empty]'));
buttons.forEach(button => button.addEventListener('click', () => {
  const filter = button.dataset.filter;
  buttons.forEach(item => item.setAttribute('aria-pressed', String(item === button)));
  cards.forEach(card => {
    const kickoffTimestamp = Date.parse(card.dataset.kickoff || '');
    const isUpcoming = Number.isFinite(kickoffTimestamp) && Date.now() < kickoffTimestamp;
    const match = filter === 'ALL'
      || (filter === 'UPCOMING' && isUpcoming)
      || (filter === 'RESULT' && card.dataset.result === 'yes');
    card.hidden = !match;
  });
  leagueGroups.forEach(group => {
    group.hidden = !Array.from(group.querySelectorAll('.fixture-row')).some(card => !card.hidden);
  });
  const visibleCount = cards.filter(card => !card.hidden).length;
  emptyStates.forEach(empty => {
    empty.hidden = empty.dataset.filterEmpty !== filter || visibleCount !== 0;
  });
  if (historicalResults) historicalResults.hidden = filter !== 'ALL';
}));
</script>"""
    body_suffix = interaction_script + STATIC_REFRESH_SCRIPT.replace("__PAGE_VERSION__", json.dumps(page_version, ensure_ascii=False))
    return render_public_document(
        title="\u4eca\u65e5\u6bd4\u8d5b \u00b7 FBOS",
        css=MODERN_CSS,
        content_html=content_html,
        dashboard_href="./latest.html",
        history_href="#trust-history",
        sources_href="#data-method",
        help_href="#beginner-help",
        mobile_label="\u6bd4\u8d5b",
        body_suffix=body_suffix,
    )


def build_dashboard(
    business_date: str,
    *,
    universe_root: Path = UNIVERSE_ROOT,
    jobs_root: Path = JOBS_ROOT,
    prediction_root: Path = PREDICTION_ROOT,
    exclusion_root: Path = EXCLUSION_ROOT,
    result_root: Path = RESULT_ROOT,
    schedule_root: Path = SCHEDULE_ROOT,
    prospective_root: Path = PROSPECTIVE_ROOT,
    runtime_path: Path = RUNTIME_PATH,
    health_watch_path: Path = HEALTH_WATCH_PATH,
    workspace_path: Path = WORKSPACE_LATEST,
    trust_path: Path | None = None,
    output_root: Path = DASHBOARD_ROOT,
    now: datetime | None = None,
) -> dict[str, Any]:
    errors: list[str] = []
    universe_path = Path(universe_root) / f"{business_date}.json"
    jobs_path = Path(jobs_root) / f"{business_date}.json"
    universe = _read_json(universe_path, errors, "universe", {})
    jobs_payload = _read_json(jobs_path, errors, "base_jobs", {})
    if not isinstance(universe, dict):
        universe = {}
    if not isinstance(jobs_payload, dict):
        jobs_payload = {}
    # Display the active JC sales day alongside its next day when the latter
    # has independently stored, matching-day universe and job artifacts.
    # Never infer or synthesize next-day forecasts from current-day jobs.
    display_dates = [business_date]
    try:
        next_date = (datetime.fromisoformat(business_date).date() + timedelta(days=1)).isoformat()
    except ValueError:
        next_date = None
    jobs_by_date: dict[str, list[dict[str, Any]]] = {}
    universes_by_date: dict[str, dict[str, Any]] = {business_date: universe}
    fixtures: list[dict[str, Any]] = []
    if next_date:
        next_universe = _read_optional_json(
            Path(universe_root) / f"{next_date}.json", [], f"universe:{next_date}", {}
        )
        next_jobs_payload = _read_optional_json(
            Path(jobs_root) / f"{next_date}.json", [], f"base_jobs:{next_date}", {}
        )
        if (isinstance(next_universe, dict)
                and isinstance(next_jobs_payload, dict)
                and next_universe.get("business_date") == next_date
                and next_jobs_payload.get("business_date") == next_date
                and next_universe.get("status") == "READY"
                and next_jobs_payload.get("status") == "READY"):
            display_dates.append(next_date)
            universes_by_date[next_date] = next_universe
            jobs_by_date[next_date] = [
                row for row in (next_jobs_payload.get("jobs") or [])
                if isinstance(row, dict)
                and str(_pick(row, "business_date", "businessDate") or "") == next_date
            ]
    jobs_by_date[business_date] = [
        row for row in (jobs_payload.get("jobs") or [])
        if isinstance(row, dict)
        and (not str(_pick(row, "business_date", "businessDate") or "").strip()
             or str(_pick(row, "business_date", "businessDate") or "").strip() == business_date)
    ]
    for day in display_dates:
        day_universe = universes_by_date[day]
        fixtures.extend([
            fixture for fixture in (day_universe.get("fixtures") or [])
            if isinstance(fixture, dict)
            and str(_pick(fixture, "businessDate", "business_date") or day) == day
        ])
    jobs = jobs_by_date[business_date]
    records = _read_records(Path(prediction_root), errors)
    exclusions = _exclusion_index(Path(exclusion_root), errors)
    result_index = _result_index(Path(result_root), errors)
    formal_rows = _read_jsonl(Path(prospective_root) / "ledger.jsonl", errors, "prospective:ledger")
    exploratory_rows = _read_jsonl(Path(prospective_root) / "exploratory_settlements.jsonl", errors, "prospective:exploratory")
    formal_samples = {str(row.get("prediction_id")): row for row in formal_rows if row.get("prediction_id")}
    exploratory_samples = {str(row.get("prediction_id")): row for row in exploratory_rows if row.get("prediction_id")}
    summary_payload = _read_optional_json(Path(prospective_root) / "summary.json", errors, "prospective:summary", {})
    if not isinstance(summary_payload, dict):
        summary_payload = {}
    runtime = _read_optional_json(Path(runtime_path), errors, "runtime", {})
    if not isinstance(runtime, dict):
        runtime = {}
    health_watch = _read_optional_json(Path(health_watch_path), [], "health_watch", {})
    if not isinstance(health_watch, dict):
        health_watch = {}
    resolved_trust_path = (
        Path(trust_path)
        if trust_path is not None
        else Path(prospective_root).parent / "prediction_quality" / "current_champion_trust.json"
    )
    trust_payload = _read_optional_json(resolved_trust_path, [], "prediction_quality_trust", {})
    public_trust = trust_payload.get("public") if isinstance(trust_payload, dict) else None
    if not isinstance(public_trust, dict):
        public_trust = {"status": "UNAVAILABLE", "status_label": "暂时无法形成可信记录"}
    completed, history = _workspace_history(Path(workspace_path), errors)
    completed = _attach_history_prematch_context(completed, records)
    cards: list[dict[str, Any]] = []
    for fixture in fixtures:
        fixture_date = str(_pick(fixture, "businessDate", "business_date") or business_date)
        fixture_jobs = jobs_by_date.get(fixture_date, [])
        current_job_resolution = resolve_current_job_for_match(
            fixture_jobs,
            _prematch_identity(fixture, None),
        )
        if current_job_resolution["status"] == "UNIQUE":
            job = current_job_resolution.get("selected_job")
        elif current_job_resolution["status"] == "CONFLICT":
            job = _conflict_job(fixture, current_job_resolution)
        else:
            job = None
        selection = None
        record = None
        if (
            current_job_resolution["status"] == "UNIQUE"
            and str((job or {}).get("status") or "PENDING") == "FROZEN"
        ):
            selection = select_latest_legal_prematch(
                records.values(),
                identity=_prematch_identity(fixture, job),
            )
            record = selection.get("selected_record")
        card = _card(
            fixture,
            job,
            record,
            result_index,
            exclusions,
            formal_samples,
            exploratory_samples,
            selection,
            current_job_resolution,
        )
        card["business_date"] = fixture_date
        cards.append(card)
    cards.sort(key=lambda item: (_iso_sort(item.get("kickoff")), _text(item.get("match_num"))))
    counts = Counter(card.get("status") for card in cards)
    verified_results = sum(
        1
        for card in cards
        if isinstance(card.get("result"), dict) and card["result"].get("score_90m")
    )
    formal_total = summary_payload.get("formal_sample_count_total")
    if formal_total is None:
        formal_total = len(formal_rows)
    samples_added = summary_payload.get("samples_added_this_run")
    if samples_added is None:
        samples_added = 0
    excluded_count = summary_payload.get("excluded_prediction_count")
    if excluded_count is None:
        excluded_count = len(exclusions)
    health_overall = str(runtime.get("overall_status") or "UNKNOWN")
    display_status = {"HEALTHY": "正常", "DEGRADED": "部分异常", "FAILED": "失败", "RUNNING": "运行中", "UNKNOWN": "尚未运行"}.get(health_overall, health_overall)
    css_class = {"HEALTHY": "normal", "DEGRADED": "degraded", "FAILED": "failed", "RUNNING": "degraded"}.get(health_overall, "unknown")
    failed_steps = [name for name, value in (runtime.get("steps") or {}).items() if isinstance(value, dict) and value.get("status") not in {"SUCCESS", "SKIPPED"}]
    system_runtime_health = {
        "status": health_overall,
        "overall_status": health_overall,
        "display_status": display_status,
        "css_class": css_class,
        "updated_at": runtime.get("finished_at") or runtime.get("started_at"),
        "failed_steps": failed_steps,
    }
    prediction_quality_health = _current_prediction_quality_health(
        records,
        exclusions,
        jobs,
        runtime,
        health_watch,
        business_date,
    )
    previous_results = _previous_business_day_results(
        business_date, Path(universe_root), Path(schedule_root), Path(result_root)
    )
    payload = {
        "schema_version": "1.0",
        "generated_at": (now or datetime.now(SHANGHAI)).isoformat(),
        "business_date": business_date,
        "system_runtime_health": system_runtime_health,
        "prediction_quality_health": prediction_quality_health,
        "prediction_quality_trust": public_trust,
        "health": system_runtime_health,
        "universe": {
            "status": universe.get("status") or "UNAVAILABLE",
            "source": universe.get("source"),
            "fetched_at": universe.get("fetched_at"),
            "fixture_count": len(fixtures),
            "business_dates": display_dates,
        },
        "summary": {
            "fixture_count": len(fixtures),
            "current_business_date_fixture_count": len(universe.get("fixtures") or []),
            "next_business_date_fixture_count": max(0, len(fixtures) - len(universe.get("fixtures") or [])),
            "card_count": len(cards),
            "frozen": counts.get("FROZEN", 0),
            "pending": counts.get("PENDING", 0),
            "insufficient_data": counts.get("INSUFFICIENT_DATA", 0),
            "prediction_failed": counts.get("PREDICTION_FAILED", 0),
            "missed": counts.get("MISSED_PREMATCH_WINDOW", 0),
            "verified_results": verified_results,
            # This count powers the current business-day RESULT filter.  The
            # workspace's cross-date rows remain an independent history view.
            "completed_count": verified_results,
            "historical_validation_count": len(completed),
            "history_count": len(history),
            "formal_prospective_total": int(formal_total or 0),
            "samples_added_today": int(samples_added or 0),
            "pilot_excluded_count": int(excluded_count or 0),
            "silent_missing_fixture": max(0, len(fixtures) - len(cards)),
        },
        "data_errors": errors,
        "fixtures": cards,
        "completed": completed,
        "history": history,
    }
    if previous_results is not None:
        payload["previous_business_day_results"] = previous_results
    output_root = Path(output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "latest.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output_root / "latest.html").write_text(render_dashboard(payload), encoding="utf-8")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the read-only Prediction Day product surface")
    parser.add_argument("--date", help="Business date YYYY-MM-DD")
    args = parser.parse_args()
    business_date = args.date or datetime.now(SHANGHAI).date().isoformat()
    payload = build_dashboard(business_date)
    print(json.dumps({
        "business_date": business_date,
        "dashboard_json": str(DASHBOARD_ROOT / "latest.json"),
        "dashboard_html": str(DASHBOARD_ROOT / "latest.html"),
        "fixture_count": payload["summary"]["fixture_count"],
        "card_count": payload["summary"]["card_count"],
        "frozen": payload["summary"]["frozen"],
        "pending": payload["summary"]["pending"],
        "insufficient_data": payload["summary"]["insufficient_data"],
        "verified_results": payload["summary"]["verified_results"],
        "formal_prospective_total": payload["summary"]["formal_prospective_total"],
        "silent_missing_fixture": payload["summary"]["silent_missing_fixture"],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
