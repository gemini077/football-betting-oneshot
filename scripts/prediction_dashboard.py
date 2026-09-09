#!/usr/bin/env python3
"""Build a read-only, accountable Prediction Day product surface."""

from __future__ import annotations

import argparse
import html
import json
import math
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
    from public_ui_shared import render_public_document, render_team_badge
except ImportError:  # package import used by tests
    from scripts.public_ui_shared import render_public_document, render_team_badge

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


def _direction_probabilities_from_cells(cells: Any) -> dict[str, float] | None:
    if not isinstance(cells, list):
        return None
    totals = {"home": 0.0, "draw": 0.0, "away": 0.0}
    total_probability = 0.0
    for item in cells:
        if not isinstance(item, dict):
            continue
        pair = _score_pair(item)
        probability = _number(item.get("probability"))
        if pair is None or probability is None or not 0 <= probability <= 1:
            continue
        direction = "home" if pair[0] > pair[1] else "draw" if pair[0] == pair[1] else "away"
        totals[direction] += probability
        total_probability += probability
    if total_probability <= 0:
        return None
    return {
        key: value / total_probability
        for key, value in totals.items()
    }


def _exact_direction_probabilities(prediction: dict[str, Any]) -> dict[str, float] | None:
    provided = _normalise_probability_map(prediction.get("exact_direction_probabilities"))
    if provided is not None:
        return provided
    contract = prediction.get("exact_score_distribution")
    if isinstance(contract, dict):
        derived = _direction_probabilities_from_cells(contract.get("cells"))
        if derived is not None:
            return derived
    formal = prediction.get("formal_markets")
    markets = formal.get("markets") if isinstance(formal, dict) else None
    exact = markets.get("exact_score") if isinstance(markets, dict) else None
    if isinstance(exact, dict):
        derived = _direction_probabilities_from_cells(exact.get("cells"))
        if derived is not None:
            return derived
    return _direction_probabilities_from_cells(prediction.get("score_distribution"))


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


def _recommendation_empty() -> dict[str, Any]:
    return {
        "status": "ABSTAIN",
        "direction": None,
        "label": "\u6682\u65e0\u660e\u786e\u9996\u9009\u65b9\u5411",
        "lane": None,
        "probability": None,
        "reason": "\u5f53\u524d\u6ca1\u6709\u53ef\u7528\u7684\u6b63\u5f0f\u9884\u6d4b\u65b9\u5411",
        "eligible_lanes": [],
    }


def select_primary_recommendation(
    prediction: dict[str, Any] | None,
    *,
    exact_score_serving: dict[str, Any] | None = None,
    prediction_allowed: bool = True,
) -> dict[str, Any]:
    """Select one plain-language direction from current authority-eligible lanes."""

    if not isinstance(prediction, dict) or not prediction_allowed or not _recommendation_authority_eligible(prediction):
        return _recommendation_empty()

    candidates: list[dict[str, Any]] = []
    one_x_two_state = str(prediction.get("one_x_two_serving_state") or "NORMAL").strip().upper()
    one_x_two = _normalise_probability_map(prediction.get("probabilities"))
    if one_x_two_state not in _RECOMMENDATION_BLOCKED_STATES and one_x_two is not None:
        direction = max(one_x_two, key=lambda key: (one_x_two[key], {"home": 2, "draw": 1, "away": 0}[key]))
        candidates.append({
            "lane": "FT_1X2",
            "direction": direction,
            "label": _RECOMMENDATION_DIRECTION_LABELS[direction],
            "probability": one_x_two[direction],
            "reason": f'{_RECOMMENDATION_DIRECTION_LABELS[direction]}\u6982\u7387\u6700\u9ad8\uff08{one_x_two[direction] * 100:.1f}%\uff09',
        })

    serving_state = (
        exact_score_serving.get("state")
        if isinstance(exact_score_serving, dict)
        else exact_score_serving
    ) or prediction.get("exact_score_serving_state")
    exact_state = str(serving_state or "UNVERIFIED").strip().upper()
    exact_direction = _exact_direction_probabilities(prediction)
    if (
        _formal_market_status(prediction, "exact_score") == "AVAILABLE"
        and exact_state not in _RECOMMENDATION_BLOCKED_STATES
        and exact_direction is not None
    ):
        direction = max(exact_direction, key=lambda key: (exact_direction[key], {"home": 2, "draw": 1, "away": 0}[key]))
        primary_score = _score_label(prediction.get("primary_score") or prediction.get("unique_score"))
        score_reason = f'\uff0c\u6700\u53ef\u80fd\u6bd4\u5206 {primary_score}' if primary_score else ""
        candidates.append({
            "lane": "EXACT_SCORE",
            "direction": direction,
            "label": _RECOMMENDATION_DIRECTION_LABELS[direction],
            "probability": exact_direction[direction],
            "reason": f'\u6bd4\u5206\u65b9\u5411\u504f\u5411{_RECOMMENDATION_DIRECTION_LABELS[direction]}\uff08{exact_direction[direction] * 100:.1f}%\uff09{score_reason}',
        })

    if not candidates:
        return _recommendation_empty()
    selected = max(
        candidates,
        key=lambda candidate: (
            float(candidate["probability"]),
            1 if candidate["lane"] == "FT_1X2" else 0,
        ),
    )
    return {
        "status": "SELECTED",
        "direction": selected["direction"],
        "label": selected["label"],
        "lane": selected["lane"],
        "probability": selected["probability"],
        "reason": selected["reason"],
        "eligible_lanes": [candidate["lane"] for candidate in candidates],
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
    formal_projection = project_frozen_formal_markets(record)
    formal_markets = summarize_formal_markets(formal_projection)
    exact_entry = (formal_projection.get("markets") or {}).get("exact_score")
    exact_contract = exact_entry.get("contract") if isinstance(exact_entry, dict) else None
    exact_direction_probabilities = _direction_probabilities_from_cells(
        exact_contract.get("cells") if isinstance(exact_contract, dict) else None
    )
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
        "exact_direction_probabilities": exact_direction_probabilities,
    }


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
.matches-head h1 { margin: 0; font-size: 24px; letter-spacing: -.045em; }
.matches-head p { margin: 5px 0 0; color: var(--muted); font-size: 9px; }
.chips { display: flex; gap: 6px; }
.chip, .filter { padding: 6px 12px; border: 1px solid var(--line); border-radius: 8px; background: #FFF; color: var(--ink); font-size: 9px; }
.chip.active, .filter[aria-pressed="true"] { border-color: #FFAD7A; background: var(--orange-soft); color: var(--orange); }
.filter { min-height: 36px; cursor: pointer; }
.filter:hover { border-color: #FFAD7A; color: var(--orange); }
.filters { display: flex; flex-wrap: wrap; gap: 6px; }
.quality-warning, .runtime-warning, .data-warning { display: flex; flex-wrap: wrap; align-items: baseline; gap: 5px 10px; margin: 0 0 10px; padding: 10px 14px; border-left: 3px solid var(--orange); background: var(--orange-soft); color: var(--muted); font-size: 11px; }
.quality-warning strong, .runtime-warning strong, .data-warning strong { color: var(--ink); font-weight: 700; }
.runtime-warning { border-left-color: var(--danger); background: var(--danger-soft); }
.runtime-warning strong { color: var(--danger); }
.data-warning { border-left-color: var(--warning); background: var(--warning-soft); color: var(--warning); }
.fixture-table { min-width: 0; }
.league-group { margin-top: 10px; overflow: hidden; border: 1px solid var(--line); border-radius: 12px; background: #FFF; }
.league-title { display: flex; align-items: center; justify-content: space-between; padding: 9px 14px; border-bottom: 1px solid var(--line); background: #FBFBFC; }
.league-title strong { font-size: 10px; }
.league-title span { color: var(--muted); font-size: 9px; }
.fixture-row.match-card { position: relative; display: grid; grid-template-columns: 126px minmax(340px,1.35fr) minmax(250px,1fr) minmax(180px,.9fr); gap: 16px; align-items: center; min-height: 94px; padding: 13px 16px; border-bottom: 1px solid var(--line); }
.fixture-row.match-card:last-child { border-bottom: 0; }
.fixture-row.match-card:hover { background: #FFFDFC; box-shadow: inset 3px 0 0 var(--orange); }
.fixture-row > * { min-width: 0; }
.fixture-row > *:not(.fixture-row-target) { position: relative; z-index: 1; pointer-events: none; }
.fixture-row-target { position: absolute; inset: 0; z-index: 2; border-radius: inherit; }
.fixture-row-target:focus-visible { outline: 2px solid var(--orange); outline-offset: -3px; }
.match-id strong, .match-id span { display: block; }
.match-id strong { color: var(--ink); font-size: 10px; font-weight: 700; font-variant-numeric: tabular-nums; }
.match-id span { margin-top: 3px; overflow: hidden; color: var(--muted); font-size: 9px; text-overflow: ellipsis; white-space: nowrap; }
.teams-line { display: grid; grid-template-columns: minmax(0,1fr) 36px minmax(0,1fr); gap: 10px; align-items: center; }
.matchup-side { display: flex; align-items: center; gap: 10px; }
.matchup-side.matchup-home { justify-content: flex-end; text-align: right; }
.matchup-side.matchup-away { justify-content: flex-start; text-align: left; }
.matchup-name { font-size: 14px; font-weight: 760; line-height: 1.2; }
.teams-status { grid-column: 1 / -1; margin-top: -2px; color: var(--muted); font-size: 9px; line-height: 1.25; text-align: center; }
.mini-crest { display: inline-grid; flex: 0 0 36px; place-items: center; width: 36px; height: 36px; border: 0; border-radius: 0; background: transparent; color: var(--blue); font-size: 7px; font-weight: 800; }
.mini-crest.team-badge { flex-basis: 36px; }
.mini-crest[data-crest-kind="fallback"], .mini-crest.team-badge-fallback { flex-basis: 32px; width: 32px; height: 32px; border: 1px solid var(--line-2); border-radius: 7px; background: #F4F5F6; }
.mini-crest img { object-fit: contain; }
.compact-prob { display: grid; gap: 9px; min-width: 0; }
.compact-prob-label { color: var(--muted); font-size: 9px; }
.compact-prob-values { display: grid; grid-template-columns: repeat(3,1fr); font-size: 13px; font-weight: 760; font-variant-numeric: tabular-nums; }
.compact-prob-values span:nth-child(1) { color: var(--blue); }
.compact-prob-values span:nth-child(2) { color: var(--ink); text-align: center; }
.compact-prob-values span:nth-child(3) { color: var(--red); text-align: right; }
.compact-prob .probbar { margin: 0; height: 8px; }
.probability-cell-group { display: grid; gap: 9px; min-width: 0; }
.compact-score { min-width: 0; color: #3F464E; font-size: 9px; font-variant-numeric: tabular-nums; }
.score-caption { display: block; margin-bottom: 3px; color: var(--muted); font-size: 9px; }
.compact-score-lines { display: flex; flex-wrap: wrap; gap: 3px 8px; }
.compact-score-item { white-space: nowrap; }
.compact-score-item strong { color: var(--ink); font-weight: 760; }
.score-serving-note { margin-top: 3px; color: var(--warning); font-size: 8px; }
.context-mini { color: #606870; font-size: 9px; }
.context-mini strong { display: block; color: #111820; font-size: 11px; }
.context-mini .warn { margin-top: 3px; color: var(--warning); }
.context-mini .exception-note { color: var(--warning); }
.context-mini .exception-note.failed, .context-mini .exception-note.missed { color: var(--danger); }
.context-label { display: block; color: var(--orange); font-size: 9px; }
.recommendation-context { padding-left: 10px; border-left: 2px solid var(--orange); }
.recommendation-context strong { margin-top: 4px; font-size: 13px; }
.recommendation-context.is-abstain strong { color: var(--warning); font-size: 11px; }
.recommendation-reason { display: block; margin-top: 4px; color: var(--muted); font-size: 9px; line-height: 1.35; }
.reason-detail { display: block; margin-top: 3px; color: var(--muted); font-size: 8px; line-height: 1.35; }
.fixture-row .matchup-vs { color: var(--orange); font-size: 10px; }
.prediction-unavailable, .score-unavailable { color: var(--muted); font-size: 11px; }
.filter-empty { padding: 42px 20px; color: var(--muted); text-align: center; }
.history { margin-top: 18px; padding-top: 1px; border-top: 1px solid var(--line); }
.history-heading { display: flex; align-items: baseline; justify-content: space-between; gap: 12px; padding: 17px 0 10px; }
.history-heading h2 { margin: 0; font-size: 16px; letter-spacing: -.02em; }
.history-heading span { color: var(--muted); font-size: 11px; }
.history-row { display: grid; grid-template-columns: 100px minmax(220px,1fr) 116px minmax(170px,auto); gap: 16px; align-items: center; min-height: 60px; border-bottom: 1px solid var(--line); font-size: 12px; }
.history-meta { color: var(--muted); font-size: 11px; }
.history-teams { min-width: 0; overflow-wrap: anywhere; font-weight: 650; }
.history-teams span { color: var(--muted); font-weight: 400; }
.history-result span { display: block; color: var(--muted); font-size: 10px; }
.history-score { display: block; margin-top: 2px; color: var(--verified); font-size: 17px; font-variant-numeric: tabular-nums; }
.history-links { display: flex; flex-wrap: wrap; gap: 8px; color: var(--muted); font-size: 11px; }
.history-links a { text-decoration: none; }
.history-links a:hover { color: var(--orange); text-decoration: underline; }
.dashboard-trust { padding: 8px 0 0; }
.dashboard-trust strong, .dashboard-trust span { display: block; margin-top: 3px; }
.page-footer { display: flex; justify-content: space-between; gap: 18px; margin-top: 10px; padding: 10px 14px 14px; border-top: 1px solid var(--line); color: var(--quiet); font-size: 9px; }
.page-footer span:last-child { max-width: 52%; text-align: right; }
.sr-only { position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px; overflow: hidden; clip: rect(0,0,0,0); white-space: nowrap; border: 0; }

@media (max-width: 980px) {
  .fixture-row.match-card { grid-template-columns: 110px minmax(250px,1.2fr) minmax(200px,1fr) minmax(160px,.9fr); gap: 12px; padding-left: 14px; padding-right: 14px; }
}
@media (max-width: 820px) {
  .dashboard-page .content { padding-bottom: 71px; }
  .matches-head { display: block; padding: 12px 0 7px; }
  .matches-head h1 { font-size: 17px; }
  .matches-head p { display: none; }
  .chips { margin-top: 10px; }
  .chip { flex: 1; padding: 6px 4px; text-align: center; font-size: 8px; }
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
  .matchup-name { font-size: 13px; }
  .teams-status { margin-top: 0; font-size: 8px; }
  .mini-crest { flex-basis: 34px; width: 34px; height: 34px; }
  .mini-crest.team-badge { flex-basis: 34px; }
  .compact-prob { margin-top: 12px; }
  .compact-prob-label { font-size: 9px; }
  .compact-prob-values { font-size: 13px; }
  .compact-score { margin-top: 12px; padding-top: 9px; border-top: 1px solid var(--line); font-size: 9px; }
  .score-caption { font-size: 9px; }
  .compact-score-lines { gap: 3px 9px; }
  .context-mini { display: block; margin-top: 10px; }
  .recommendation-context strong { font-size: 12px; }
  .history { margin-top: 25px; }
  .history-row { grid-template-columns: minmax(0,1fr) auto; gap: 5px 12px; padding: 11px 0; }
  .history-meta, .history-links { grid-column: 1 / -1; }
  .page-footer { display: block; }
  .page-footer span { display: block; }
  .page-footer span:last-child { max-width: none; margin-top: 6px; text-align: left; }
}
@media (max-width: 360px) {
  .dashboard-page .content { padding-left: 12px; padding-right: 12px; }
  .fixture-table { margin-left: -12px; margin-right: -12px; }
  .fixture-row.match-card { padding-left: 12px; padding-right: 12px; }
  .matchup-name { font-size: 12px; }
  .mini-crest { flex-basis: 32px; width: 32px; height: 32px; }
  .mini-crest.team-badge { flex-basis: 32px; }
  .compact-score-lines { gap: 3px 6px; }
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
        rendered_rows.append(
            f'<span class="compact-score-item" data-score-rank="{rank}">'
            f'<strong>{html.escape(str(row["score"]))}</strong> {html.escape(probability)}</span>'
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
    teams_html = (
        '<div class="matchup-side matchup-home">'
        f'{render_team_badge(home_value, card.get("home_crest"), side="home", variant="mini-crest")}'
        f'<strong class="matchup-name">{home_text}</strong></div>'
        '<span class="matchup-vs" aria-hidden="true">VS</span>'
        '<div class="matchup-side matchup-away">'
        f'<strong class="matchup-name">{away_text}</strong>'
        f'{render_team_badge(away_value, card.get("away_crest"), side="away", variant="mini-crest")}</div>'
        f'<span class="teams-status">{html.escape(status_line)}</span>'
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
) -> str:
    """Keep the R4 editorial league grouping while preserving fixture order."""

    groups: dict[str, list[dict[str, Any]]] = {}
    for card in cards:
        if not isinstance(card, dict):
            continue
        label = _text(card.get("competition"), "\u8d5b\u4e8b\u5f85\u5b9a")
        groups.setdefault(label, []).append(card)
    sections = []
    for competition, group in groups.items():
        cards_html = "".join(
            _modern_card_html(card, exact_score_serving=exact_score_serving)
            for card in group
        )
        sections.append(
            f'<section class="league-group" data-league="{html.escape(competition, quote=True)}">'
            f'<div class="league-title"><strong>{html.escape(competition)}</strong>'
            f'<span>{len(group)} \u573a \u203a</span></div>{cards_html}</section>'
        )
    return "".join(sections)


def _historical_results_html(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return ""
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
        link_text = " \u00b7 ".join(links)
        cards.append(
            '<article class="history-row" data-result="yes">'
            f'<div class="history-meta">{kickoff_text}</div>'
            f'<div class="history-teams">{home_text}<span> vs </span>{away_text}</div>'
            f'<div class="history-result"><span>90分钟结果</span><strong class="history-score">{html.escape(str(result))}</strong></div>'
            f'<div class="history-links">{link_text}</div>'
            '</article>'
        )
    if not cards:
        return ""
    return (
        '<section id="historical-results" class="history" aria-labelledby="history-title">'
        '<div class="history-heading"><h2 id="history-title">历史验证</h2>'
        f'<span>{len(cards)} 场独立记录 · 结果优先</span></div>'
        f'{"".join(cards)}</section>'
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
    fixture_count = int(summary.get("fixture_count") or len(payload.get("fixtures") or []))
    verified_results = int(summary.get("verified_results") or 0)
    exact_score_serving = exact_score_serving_presentation(quality_health)
    cards = [card for card in payload.get("fixtures") or [] if isinstance(card, dict)]
    cards_html = _league_groups_html(cards, exact_score_serving=exact_score_serving)
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
    quality_warning = _quality_warning_html(quality_health)
    historical_html = _historical_results_html(payload.get("completed") or [])
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
  <div class="crumbs"><strong>\u4eca\u65e5\u6bd4\u8d5b</strong><span>\u00b7</span><span>{html.escape(business_date_label)}</span></div>
  <div class="utility"><button class="icon-btn" type="button" aria-label="\u600e\u4e48\u770b"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><circle cx="12" cy="12" r="9"/><path d="M9.8 9a2.3 2.3 0 014.4.9c0 1.7-2.2 2-2.2 3.6M12 17h.01"/></svg></button><strong>\u600e\u4e48\u770b</strong><button class="icon-btn" type="button" aria-label="\u641c\u7d22"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><circle cx="11" cy="11" r="7"/><path d="M16 16l5 5"/></svg></button></div>
</header>
<div class="content">
<section class="matches-head"><div><h1>\u4eca\u65e5\u6bd4\u8d5b</h1><p>\u5148\u770b\u8c01\u548c\u8c01\u6bd4\u8d5b\uff0c\u518d\u770b\u80dc / \u5e73 / \u8d1f\u6982\u7387\u4e0e\u6700\u53ef\u80fd\u6bd4\u5206\u3002\u5f02\u5e38\u53ea\u5728\u771f\u6b63\u6539\u53d8\u5224\u65ad\u65f6\u51fa\u73b0\u3002 \u6d4b\u8bd5\u9636\u6bb5 \u00b7 \u4ec5\u4f9b\u8d5b\u524d\u5206\u6790</p></div><div class="chips" aria-label="\u6bd4\u8d5b\u7b5b\u9009"><button class="chip filter" type="button" data-filter="ALL" aria-pressed="true">\u5168\u90e8</button><button class="chip filter" type="button" data-filter="UPCOMING" aria-pressed="false">\u672a\u5f00\u8d5b</button><button class="chip filter" type="button" data-filter="RESULT" data-result-count="{verified_results}" aria-pressed="false">\u5df2\u7ed3\u675f</button></div></section>
{runtime_warning}{quality_warning}{data_warning}
<section class="fixture-table" id="fixture-list" aria-label="\u7ade\u5f69\u65e5\u6bd4\u8d5b\u5217\u8868">
  {cards_html}
  {filter_empty_html}
</section>
{historical_html}
<section class="trust-strip dashboard-trust-strip" id="dashboard-trust"><div class="trust-item"><span class="trust-ico">\u26bd</span><div><strong>\u4eca\u65e5\u961f\u5217</strong><span>\u9ed8\u8ba4\u53ea\u7a81\u51fa\u80dc / \u5e73 / \u8d1f\u6982\u7387\u4e0e\u6700\u53ef\u80fd\u6bd4\u5206\u3002</span></div></div><div class="trust-item"><span class="trust-ico">!</span><div><strong>\u5f02\u5e38\u63d0\u793a</strong><span>\u53ea\u6709\u771f\u6b63\u6539\u53d8\u5224\u65ad\u65f6\u624d\u51fa\u73b0\u3002</span></div></div><div class="trust-item"><span class="trust-ico">\u25c7</span><div><strong>\u8d5b\u524d\u8bb0\u5f55</strong><span>\u6bd4\u8d5b\u5f00\u59cb\u524d\u5f62\u6210\u5e76\u4fdd\u7559\u3002</span></div></div><div class="trust-item"><span class="trust-ico">\u2713</span><div><strong>\u5386\u53f2\u9a8c\u8bc1</strong><span>\u6210\u529f\u548c\u5931\u8d25\u540c\u53e3\u5f84\u8bb0\u5f55\u3002</span></div></div><div class="trust-item"><span class="trust-ico">i</span><div><strong>\u65b9\u6cd5\u8bf4\u660e</strong><span>\u6280\u672f\u7ec6\u8282\u4e0b\u6c89\uff0c\u4e0d\u62a2\u9996\u5c4f\u3002</span></div></div></section>
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
        history_href="#historical-results" if historical_html else None,
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
    prospective_root: Path = PROSPECTIVE_ROOT,
    runtime_path: Path = RUNTIME_PATH,
    health_watch_path: Path = HEALTH_WATCH_PATH,
    workspace_path: Path = WORKSPACE_LATEST,
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
    fixtures = [row for row in (universe.get("fixtures") or []) if isinstance(row, dict)]
    jobs = [
        row
        for row in (jobs_payload.get("jobs") or [])
        if isinstance(row, dict)
        and (
            not str(_pick(row, "business_date", "businessDate") or "").strip()
            or str(_pick(row, "business_date", "businessDate") or "").strip() == business_date
        )
    ]
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
    completed, history = _workspace_history(Path(workspace_path), errors)
    cards: list[dict[str, Any]] = []
    for fixture in fixtures:
        current_job_resolution = resolve_current_job_for_match(
            jobs,
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
        cards.append(_card(
            fixture,
            job,
            record,
            result_index,
            exclusions,
            formal_samples,
            exploratory_samples,
            selection,
            current_job_resolution,
        ))
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
    payload = {
        "schema_version": "1.0",
        "generated_at": (now or datetime.now(SHANGHAI)).isoformat(),
        "business_date": business_date,
        "system_runtime_health": system_runtime_health,
        "prediction_quality_health": prediction_quality_health,
        "health": system_runtime_health,
        "universe": {
            "status": universe.get("status") or "UNAVAILABLE",
            "source": universe.get("source"),
            "fetched_at": universe.get("fetched_at"),
            "fixture_count": universe.get("fixture_count", len(fixtures)),
        },
        "summary": {
            "fixture_count": int(universe.get("fixture_count") or len(fixtures)),
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
            "silent_missing_fixture": max(0, int(universe.get("fixture_count") or len(fixtures)) - len(cards)),
        },
        "data_errors": errors,
        "fixtures": cards,
        "completed": completed,
        "history": history,
    }
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
