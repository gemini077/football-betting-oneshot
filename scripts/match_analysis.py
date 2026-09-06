#!/usr/bin/env python3
"""Assemble read-only product analysis contracts from canonical project data.

This module is deliberately a projection layer.  It never runs the model,
changes a governance record, or derives a new market/model judgement.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import html
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

try:  # Keep direct ``python scripts/match_analysis.py`` execution working.
    from .legacy_analysis_mapper import LegacyStructuredAnalysisMapper
except ImportError:  # pragma: no cover - exercised by the direct CLI path.
    from legacy_analysis_mapper import LegacyStructuredAnalysisMapper

try:
    from .formal_market_projection import project_frozen_formal_markets
except ImportError:  # pragma: no cover - exercised by the direct CLI path.
    from formal_market_projection import project_frozen_formal_markets

try:
    from .current_serving_state import resolve_current_job_for_match
except ImportError:  # pragma: no cover - exercised by the direct CLI path.
    from current_serving_state import resolve_current_job_for_match


ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = ROOT / "data"
UNIVERSE_ROOT = DATA_ROOT / "prediction_universe"
JOBS_ROOT = DATA_ROOT / "base_prediction_jobs"
PREDICTION_ROOT = DATA_ROOT / "model_governance" / "predictions"
SNAPSHOT_ROOT = DATA_ROOT / "model_governance" / "input_snapshots"
EXCLUSION_ROOT = DATA_ROOT / "model_governance" / "prediction_exclusions"
PROSPECTIVE_ROOT = DATA_ROOT / "prospective"
RESULT_ROOT = DATA_ROOT / "postmatch_automation" / "results"
MATCH_ANALYSIS_ROOT = DATA_ROOT / "match_analysis"
LEGACY_WORKSPACE_ROOT = DATA_ROOT / "match_workspace"
LEGACY_ANALYSIS_ROOT = DATA_ROOT / "analysis_reports"
LEGACY_POSTMATCH_ROOT = DATA_ROOT / "postmatch_reports"

ANALYSIS_CONTRACT_VERSION = "1.0"
SHANGHAI = timezone(timedelta(hours=8))

STATUS_LABELS = {
    "CURRENT_JOB_STATE_CONFLICT": "\u5f53\u524d\u6bd4\u8d5b\u72b6\u6001\u51b2\u7a81",
    "FROZEN": "已预测",
    "PENDING": "预测尚未冻结",
    "INSUFFICIENT_DATA": "数据不足",
    "PREDICTION_FAILED": "预测失败",
    "MISSED_PREMATCH_WINDOW": "错过赛前窗口",
    "EMPTY_CONFIRMED": "暂无比赛",
}

STATUS_REASON_LABELS = {
    "DUPLICATE_CURRENT_JOB_STATE": "\u5f53\u524d\u6bd4\u8d5b\u72b6\u6001\u51b2\u7a81\uff0c\u6682\u4e0d\u5f62\u6210\u9884\u6d4b",
    "MULTIPLE_CURRENT_MATCH_GROUPS": "\u5f53\u524d\u6bd4\u8d5b\u8eab\u4efd\u5b58\u5728\u51b2\u7a81\uff0c\u6682\u4e0d\u5f62\u6210\u9884\u6d4b",
    "MISSING_RECENT_FORM": "近期比赛数据不足",
    "MISSING_MARKET_INTELLIGENCE": "缺少最低市场情报",
    "INPUT_TIMESTAMP_UNVERIFIED": "赛前数据时间无法验证",
    "IDENTITY_UNRESOLVED": "比赛身份无法可靠匹配",
    "MODEL_RETURNED_NO_PREDICTION": "模型未返回预测",
    "PREDICTION_FAILED": "模型运行失败",
}

SECTION_TITLES = (
    ("strength", "强弱与主动权"),
    ("tempo", "节奏与进球环境"),
    ("scoring", "得分路径"),
    ("fork", "关键分叉 / 最大不确定性"),
    ("convergence", "最终收敛"),
)

_LEGACY_MAPPER = LegacyStructuredAnalysisMapper()


def match_url(match_id: Any) -> str:
    """Return the stable static route for a canonical fixture identity."""
    value = _string(match_id).strip()
    if not value or not re.fullmatch(r"[A-Za-z0-9._~-]+", value):
        raise ValueError("invalid match identity for static route")
    return f"/matches/{value}/"


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _first(payload: dict[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        value = payload.get(key)
        if value is not None and value != "":
            return value
    return default


def _string(value: Any, default: str = "") -> str:
    if value is None:
        return default
    return str(value)


def _safe_number(value: Any) -> float | int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    if not isinstance(value, str):
        return None
    match = re.search(r"-?\d+(?:\.\d+)?", value)
    if not match:
        return None
    number = float(match.group(0))
    return int(number) if number.is_integer() else number


def _unique(values: Iterable[Any]) -> list[Any]:
    result: list[Any] = []
    seen: set[str] = set()
    for value in values:
        if value is None or value == "":
            continue
        marker = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
        if marker not in seen:
            seen.add(marker)
            result.append(value)
    return result


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    text = _string(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=SHANGHAI)
    return parsed


def _iso(value: Any) -> str | None:
    parsed = _parse_dt(value)
    return parsed.isoformat() if parsed else (_string(value) if value else None)


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _fixture_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("fixtures", "matches", "items", "data"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []


def _fixture_id(fixture: dict[str, Any]) -> str:
    return _string(_first(fixture, "match_id", "matchId", "matchID", "id"))


def _fixture_projection(fixture: dict[str, Any], business_date: str) -> dict[str, Any]:
    match_id = _fixture_id(fixture)
    kickoff = _first(fixture, "kickoff_at", "kickoff", "kickoffAt")
    if not kickoff:
        match_date = _string(_first(fixture, "matchDate", "match_date", default=business_date))
        match_time = _string(_first(fixture, "matchTime", "match_time", default="00:00:00"))
        kickoff = f"{match_date}T{match_time}"
    kickoff_iso = _iso(kickoff) or _string(kickoff)
    return {
        "match_id": match_id,
        "match_num": _string(_first(fixture, "match_num", "matchNum", "number")) or None,
        "business_date": business_date,
        "competition": _string(_first(fixture, "competition", "league", "leagueName")) or None,
        "home": _string(_first(fixture, "home", "homeTeam", "home_team")) or None,
        "away": _string(_first(fixture, "away", "awayTeam", "away_team")) or None,
        "kickoff_at": kickoff_iso,
        "nowscore_id": _first(fixture, "nowscore_id", "nowscoreId", "nowscoreID"),
        "shuju_id": _first(fixture, "shuju_id", "shujuId", "shujuID"),
        "match_key": _first(fixture, "match_key", "matchKey"),
        "source_fixture": copy.deepcopy(fixture),
    }


def _load_universe(universe_root: Path, business_date: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    payload = _read_json(universe_root / f"{business_date}.json") or {
        "business_date": business_date,
        "status": "MISSING",
        "fixtures": [],
    }
    return payload, [_fixture_projection(item, business_date) for item in _fixture_items(payload)]


def _job_items(jobs_root: Path, business_date: str) -> list[dict[str, Any]]:
    payload = _read_json(jobs_root / f"{business_date}.json") or {}
    values = payload.get("jobs") or payload.get("items") or []
    return [
        item
        for item in values
        if isinstance(item, dict)
        and (
            not _string(_first(item, "business_date", "businessDate"))
            or _string(_first(item, "business_date", "businessDate")) == business_date
        )
    ]


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


def _conflict_job(
    match_id: str,
    match_key: str | None,
    resolution: dict[str, Any],
    fixture_identity: dict[str, Any] | None = None,
) -> dict[str, Any]:
    identity = fixture_identity or {}
    conflict_reason = str(resolution.get("conflict_reason") or "DUPLICATE_CURRENT_JOB_STATE")
    return {
        "job_id": None,
        "match_id": match_id,
        "match_key": match_key,
        "home": _first(identity, "home", "homeTeam", "home_team"),
        "away": _first(identity, "away", "awayTeam", "away_team"),
        "kickoff": _first(identity, "kickoff_at", "kickoff", "kickoff_local"),
        "status": "CURRENT_JOB_STATE_CONFLICT",
        "last_error": conflict_reason,
        "prediction_id": None,
        "current_job_resolution": _public_job_resolution(resolution),
    }


def _job_for_fixture(
    jobs: list[dict[str, Any]],
    match_id: str,
    match_key: str | None,
    *,
    fixture_identity: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    identity = fixture_identity or {
        "match_id": match_id,
        "match_key": match_key,
    }
    resolution = resolve_current_job_for_match(jobs, identity)
    if resolution["status"] == "UNIQUE":
        return resolution.get("selected_job")
    if resolution["status"] == "CONFLICT":
        return _conflict_job(match_id, match_key, resolution, fixture_identity)
    identity = fixture_identity or {}
    return {
        "job_id": None,
        "match_id": match_id,
        "match_key": match_key,
        "home": _first(identity, "home", "homeTeam", "home_team"),
        "away": _first(identity, "away", "awayTeam", "away_team"),
        "kickoff": _first(identity, "kickoff_at", "kickoff", "kickoff_local"),
        "status": "PENDING",
        "last_error": "BASE_JOB_MISSING",
        "prediction_id": None,
        "current_job_resolution": _public_job_resolution(resolution),
    }


def _prediction_files(prediction_root: Path) -> list[Path]:
    if not prediction_root.exists():
        return []
    return sorted(prediction_root.glob("*.json"))


def _find_prediction(
    prediction_root: Path,
    fixture: dict[str, Any],
    job: dict[str, Any] | None,
) -> dict[str, Any] | None:
    prediction_id = _string(_first(job or {}, "prediction_id", "predictionId"))
    candidates: list[Path] = []
    if prediction_id:
        candidates.append(prediction_root / f"{prediction_id}.json")
    for path in candidates:
        payload = _read_json(path)
        if payload:
            return payload
    match_id = fixture["match_id"]
    match_key = _string(fixture.get("match_key"))
    for path in _prediction_files(prediction_root):
        payload = _read_json(path)
        if not payload:
            continue
        if _string(_first(payload, "match_id", "matchId")) == match_id:
            return payload
        identity = payload.get("match_identity") or {}
        if match_key and _string(_first(payload, "match_key", "matchKey")) == match_key:
            return payload
        if match_key and _string(identity.get("match_key")) == match_key:
            return payload
    return None


def _load_excluded_ids(exclusion_root: Path) -> set[str]:
    ids: set[str] = set()
    if not exclusion_root.exists():
        return ids
    for path in exclusion_root.glob("*.json"):
        payload = _read_json(path)
        if not payload:
            continue
        for value in payload.get("prediction_ids") or payload.get("predictionIds") or []:
            ids.add(_string(value))
    return ids


def _find_snapshot(snapshot_root: Path, reference: Any) -> tuple[dict[str, Any] | None, Path | None]:
    if not reference:
        return None, None
    ref = Path(_string(reference))
    candidates = [ref]
    if not ref.is_absolute():
        candidates.extend([ROOT / ref, snapshot_root / ref, snapshot_root / ref.name])
    for candidate in candidates:
        payload = _read_json(candidate)
        if payload is not None:
            return payload, candidate
    return None, None


def _snapshot_input(snapshot: dict[str, Any] | None) -> dict[str, Any]:
    if not snapshot:
        return {}
    value = snapshot.get("input")
    return value if isinstance(value, dict) else snapshot


def _latest_source_snapshot(snapshot_input: dict[str, Any]) -> dict[str, Any]:
    sources = snapshot_input.get("source_snapshots") or {}
    nowscore = sources.get("nowscore") if isinstance(sources, dict) else None
    snapshots = nowscore.get("snapshots") if isinstance(nowscore, dict) else None
    if isinstance(snapshots, list) and snapshots and isinstance(snapshots[0], dict):
        return snapshots[0]
    return {}


def _recent_form(snapshot_input: dict[str, Any]) -> tuple[dict[str, Any], str | None, str | None]:
    fundamentals = snapshot_input.get("prematch_fundamentals") or {}
    recent = fundamentals.get("recent_form") if isinstance(fundamentals, dict) else None
    source = fundamentals.get("form_source") if isinstance(fundamentals, dict) else None
    captured = fundamentals.get("captured_at") if isinstance(fundamentals, dict) else None
    if not isinstance(recent, dict):
        source_snapshot = _latest_source_snapshot(snapshot_input)
        shuju = source_snapshot.get("shuju") or {}
        recent = shuju.get("recent_form") if isinstance(shuju, dict) else None
        source = source or "nowscore"
        captured = captured or source_snapshot.get("fetched_at")
    return (copy.deepcopy(recent) if isinstance(recent, dict) else {}, _iso(captured), _string(source) or None)


def _market_facts(snapshot_input: dict[str, Any], prediction: dict[str, Any]) -> dict[str, Any]:
    source_snapshot = _latest_source_snapshot(snapshot_input)
    ouzhi = source_snapshot.get("ouzhi") or {}
    yazhi = source_snapshot.get("yazhi") or {}
    daxiao = source_snapshot.get("daxiao") or {}
    bookmakers = ouzhi.get("bookmakers") if isinstance(ouzhi, dict) else []
    ah_companies = yazhi.get("companies") if isinstance(yazhi, dict) else []
    totals_companies = daxiao.get("companies") if isinstance(daxiao, dict) else []
    bookmakers = [item for item in _as_list(bookmakers) if isinstance(item, dict)]
    ah_companies = [item for item in _as_list(ah_companies) if isinstance(item, dict)]
    totals_companies = [item for item in _as_list(totals_companies) if isinstance(item, dict)]

    bookmaker_names = _unique(_first(item, "name", "bookmaker", "company") for item in bookmakers)
    ah_lines = _unique(
        _safe_number(_first(item, "current_handicap", "handicap", "line"))
        for item in ah_companies
    )
    total_lines = _unique(
        _safe_number(_first(item, "current_line", "line", "total"))
        for item in totals_companies
    )
    record_sources = prediction.get("market_source_references") or prediction.get("source_references") or []
    snapshot_sources = snapshot_input.get("source_refs") or []
    if not snapshot_sources:
        snapshot_sources = []
        raw_snapshot = snapshot_input.get("source_snapshots") or {}
        nowscore = raw_snapshot.get("nowscore") if isinstance(raw_snapshot, dict) else None
        if isinstance(nowscore, dict):
            snapshot_sources.extend(nowscore.get("source_refs") or [])
    probabilities = _prediction_model(prediction).get("probabilities") or {}
    fair = snapshot_input.get("official_market_baseline") or {}
    fair_probabilities = fair.get("fair_probabilities") if isinstance(fair, dict) else {}
    fair_probabilities = fair_probabilities if isinstance(fair_probabilities, dict) else {}
    model_comparison = {
        "market_home_probability": fair_probabilities.get("home"),
        "model_home_probability": probabilities.get("home"),
        "classification": None,
        "interpretation": None,
        "source_refs": ["official_market_baseline", "prediction_record"],
    }
    return {
        "facts": {
            "provider": "nowscore" if source_snapshot else None,
            "fetched_at": _iso(source_snapshot.get("fetched_at")),
            "bookmaker_count": len(bookmakers),
            "bookmakers": bookmaker_names,
            "asian_handicap_company_count": len(ah_companies),
            "totals_company_count": len(totals_companies),
        },
        "interpretation": None,
        "model_comparison": model_comparison,
        "observed_1x2_bookmakers": bookmaker_names,
        "observed_ah_lines": ah_lines,
        "observed_totals_lines": total_lines,
        "timeline": [],
        "source_refs": _unique([*_as_list(record_sources), *_as_list(snapshot_sources)]),
    }


def _prediction_model(prediction: dict[str, Any]) -> dict[str, Any]:
    output = prediction.get("prediction_output") or {}
    probabilities = _first(prediction, "probabilities", "fusion_1X2", default=output.get("probabilities"))
    probabilities = copy.deepcopy(probabilities) if isinstance(probabilities, dict) else {}
    btts = _first(prediction, "btts", default=output.get("btts"))
    btts = copy.deepcopy(btts) if isinstance(btts, dict) else {}
    totals = _first(prediction, "totals", default=output.get("totals"))
    totals = copy.deepcopy(totals) if isinstance(totals, list) else []
    raw_scores = _first(prediction, "top_scores", "score_distribution", default=output.get("score_matrix"))
    scores = []
    for item in _as_list(raw_scores):
        if isinstance(item, str):
            scores.append({"score": item})
        elif isinstance(item, dict) and _first(item, "score", "value") is not None:
            score = {"score": _string(_first(item, "score", "value"))}
            for key in ("probability", "rank", "fair_odds"):
                if item.get(key) is not None:
                    score[key] = item[key]
            scores.append(score)
    primary = _first(prediction, "unique_score", "score_top1", default=output.get("unique_score"))
    if isinstance(primary, dict):
        primary = _first(primary, "score", "value")
    if primary is None and scores:
        primary = scores[0].get("score")
    lambda_home = _first(prediction, "lambda_home", default=output.get("lambda_home"))
    lambda_away = _first(prediction, "lambda_away", default=output.get("lambda_away"))
    uncertainty = prediction.get("uncertainty") or {}
    return {
        "lambda_home": lambda_home,
        "lambda_away": lambda_away,
        "probabilities": probabilities,
        "btts": btts,
        "totals": totals,
        "top_scores": scores,
        "unique_score": _string(primary) if primary is not None else None,
        "uncertainty": copy.deepcopy(uncertainty) if isinstance(uncertainty, dict) else {},
        "model_family": _first(prediction, "model_family", "model_core_version"),
        "release_version": _first(prediction, "release_version", "release"),
    }


def _source_refs(prediction: dict[str, Any], snapshot: dict[str, Any] | None) -> list[Any]:
    refs: list[Any] = []
    refs.extend(_as_list(prediction.get("source_references")))
    refs.extend(_as_list(prediction.get("market_source_references")))
    if snapshot:
        refs.extend(_as_list(snapshot.get("source_refs")))
    return _unique(refs)


def _find_verified_result(result_root: Path, fixture: dict[str, Any], prediction: dict[str, Any] | None) -> dict[str, Any] | None:
    """Read only an already verified regulation-time result artifact."""
    if not result_root.exists():
        return None
    match_key = fixture.get("match_key") or _first(prediction or {}, "match_key", "matchKey")
    match_id = fixture.get("match_id")
    for path in sorted(result_root.glob("*.json")):
        payload = _read_json(path)
        if not payload:
            continue
        if match_key and _string(payload.get("match_key")) != _string(match_key):
            continue
        if not match_key and _string(_first(payload, "match_id", "matchId")) != _string(match_id):
            continue
        scope = _string(payload.get("scope"))
        verified_at = _first(payload, "verified_at", "result_verified_at")
        score = _first(payload, "result_90m", "score_90m")
        if scope != "regulation_90m_plus_stoppage" or not verified_at or not score:
            continue
        return {
            "score_90m": _string(score),
            "home_score": payload.get("home_score"),
            "away_score": payload.get("away_score"),
            "scope": scope,
            "source": payload.get("source"),
            "verified_at": _iso(verified_at),
            "source_ref": path.as_posix(),
        }
    return None


def _reason_code(job: dict[str, Any] | None, prediction: dict[str, Any] | None) -> str | None:
    for payload in (job or {}, prediction or {}):
        value = _first(payload, "last_error", "reason", "reason_code", "failure_reason")
        if value:
            return _string(value)
        data_quality = payload.get("data_quality")
        if isinstance(data_quality, dict):
            missing = data_quality.get("missing")
            if isinstance(missing, list) and missing:
                return _string(missing[0])
    return None


def _status(job: dict[str, Any] | None, prediction: dict[str, Any] | None) -> str:
    raw = _string(_first(job or {}, "status", "job_status"))
    if raw in STATUS_LABELS:
        return raw
    if prediction:
        value = _string(_first(prediction, "prediction_status", "status"))
        if value.upper() in {"FORMAL", "FROZEN", "PREDICTED"}:
            return "FROZEN"
    return "PENDING"


def _formal_eligible(prediction: dict[str, Any] | None, excluded: bool) -> bool:
    if not prediction or excluded:
        return False
    return bool(
        prediction.get("formal_eligibility_policy") == "base_prediction_minimum.v1"
        and prediction.get("formal_eligible") is True
        and prediction.get("model_formal_eligible") is True
        and prediction.get("base_input_quality") == "VERIFIED_MINIMUM"
    )


def _format_percent(value: Any) -> str | None:
    number = _safe_number(value)
    if number is None:
        return None
    return f"{float(number) * 100:.1f}%"


def _form_sentence(label: str, form: dict[str, Any]) -> str:
    matches = form.get("matches")
    wins = form.get("wins")
    draws = form.get("draws")
    losses = form.get("losses")
    gf = form.get("goals_for")
    ga = form.get("goals_against")
    parts = []
    if matches is not None:
        parts.append(f"{label}记录{matches}场")
    if wins is not None and draws is not None and losses is not None:
        parts.append(f"{wins}胜{draws}平{losses}负")
    if gf is not None and ga is not None:
        parts.append(f"进球{gf}、失球{ga}")
    return "，".join(parts) if parts else f"{label}近期数据字段不完整"


def _normalise_identity_text(value: Any) -> str:
    return re.sub(r"\s+", "", _string(value)).casefold()


def _legacy_candidate_paths(root: Path, fixture: dict[str, Any], *, kind: str) -> list[Path]:
    """Return a bounded set of old-analysis candidates from one known asset root.

    The production repository contains many historical workspace snapshots.  This
    deliberately does not crawl arbitrary repository paths: analysis reports are
    limited to their JSON sidecars, workspace is limited to known aggregate/current
    snapshots and the target business-date snapshots, and postmatch reports are
    considered only when their filename carries the stable fixture identity.
    """
    if not root.exists():
        return []
    match_id = _string(fixture.get("match_id"))
    match_key = _string(fixture.get("match_key"))
    nowscore_id = _string(fixture.get("nowscore_id"))
    shuju_id = _string(fixture.get("shuju_id"))
    tokens = {value.casefold() for value in (match_id, match_key, nowscore_id, shuju_id) if value}
    paths: set[Path] = set()

    if kind == "analysis_reports":
        paths.update(root.rglob("*.json"))
        paths.update(root.rglob("*.html"))
    elif kind == "workspace":
        for name in ("latest.json", "latest.html"):
            candidate = root / name
            if candidate.exists():
                paths.add(candidate)
        current = root / "current"
        if current.exists():
            paths.update(path for path in current.iterdir() if path.is_file() and path.suffix.lower() in {".json", ".html"})
        compact_date = _string(fixture.get("business_date")).replace("-", "")
        for child in root.iterdir():
            if not child.is_dir():
                continue
            if compact_date and child.name.startswith(compact_date):
                paths.update(
                    path for path in child.iterdir()
                    if path.is_file() and path.name in {"workspace.json", "index.json", "index.html"}
                )
            if tokens and any(token in child.name.casefold() for token in tokens):
                paths.update(path for path in child.iterdir() if path.is_file() and path.suffix.lower() in {".json", ".html"})
    elif kind == "postmatch_reports":
        for path in root.iterdir():
            if path.is_file() and path.suffix.lower() in {".json", ".html"}:
                if tokens and any(token in path.name.casefold() for token in tokens):
                    paths.add(path)
    return sorted(paths)


def _legacy_records(payload: dict[str, Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for key in ("match", "fixture", "identity"):
        if isinstance(payload.get(key), dict):
            records.append(payload)
            break
    for key in ("matches", "fixtures", "items"):
        values = payload.get(key)
        if isinstance(values, list):
            for value in values:
                if isinstance(value, dict):
                    records.append({**payload, "match": value})
    if not records and any(key in payload for key in ("match_id", "matchId", "home", "home_team")):
        records.append(payload)
    return records


def _read_legacy_payload(path: Path) -> dict[str, Any] | None:
    """Read only structured JSON sidecars or explicit JSON script payloads."""
    if path.suffix.lower() == ".json":
        return _read_json(path)
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return None
    for match in re.finditer(
        r"<script[^>]*type=[\"']application/json[\"'][^>]*>(.*?)</script>",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    ):
        try:
            payload = json.loads(html.unescape(match.group(1).strip()))
        except (TypeError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict):
            return payload
    return None


def _legacy_identity(record: dict[str, Any]) -> dict[str, Any]:
    identity = record.get("match") or record.get("fixture") or record.get("identity") or record
    if not isinstance(identity, dict):
        identity = record
    kickoff = _first(identity, "kickoff_at", "kickoff", "kickoff_local", "kickoffAt")
    return {
        "match_id": _first(identity, "match_id", "matchId", "matchID", "id"),
        "match_key": _first(identity, "match_key", "matchKey"),
        "business_date": _first(identity, "business_date", "businessDate"),
        "competition": _first(identity, "competition", "league", "leagueName"),
        "home": _first(identity, "home", "homeTeam", "home_team"),
        "away": _first(identity, "away", "awayTeam", "away_team"),
        "kickoff_at": kickoff,
    }


def _legacy_identity_matches(target: dict[str, Any], candidate: dict[str, Any]) -> tuple[bool, str | None]:
    for key in ("match_id", "match_key", "nowscore_id", "shuju_id"):
        candidate_value = candidate.get(key)
        target_value = target.get(key)
        if candidate_value not in (None, "") and target_value not in (None, ""):
            if _normalise_identity_text(candidate_value) != _normalise_identity_text(target_value):
                return False, f"{key}_mismatch"
    for key in ("home", "away"):
        if candidate.get(key) not in (None, "") and target.get(key) not in (None, ""):
            if _normalise_identity_text(candidate[key]) != _normalise_identity_text(target[key]):
                return False, f"{key}_mismatch"
    if candidate.get("business_date") not in (None, "") and target.get("business_date") not in (None, ""):
        if _normalise_identity_text(candidate["business_date"]) != _normalise_identity_text(target["business_date"]):
            return False, "business_date_mismatch"
    if candidate.get("competition") not in (None, "") and target.get("competition") not in (None, ""):
        if _normalise_identity_text(candidate["competition"]) != _normalise_identity_text(target["competition"]):
            return False, "competition_mismatch"
    target_kickoff = _parse_dt(target.get("kickoff_at"))
    candidate_kickoff = _parse_dt(candidate.get("kickoff_at"))
    if candidate_kickoff and target_kickoff and abs((candidate_kickoff - target_kickoff).total_seconds()) > 60:
        return False, "kickoff_mismatch"
    if not candidate.get("home") or not candidate.get("away") or not candidate_kickoff:
        return False, "identity_incomplete"
    return True, None


def _legacy_score(value: Any) -> str | None:
    if isinstance(value, dict):
        value = _first(value, "score", "value")
    text = _string(value)
    match = re.search(r"(?<!\d)(\d+)\s*[-:：]\s*(\d+)(?!\d)", text)
    return f"{match.group(1)}-{match.group(2)}" if match else None


def _legacy_explicit_sections(record: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, str], list[dict[str, Any]]]:
    """Extract existing interpretations only from explicit structured fields."""
    material = record.get("analysis_material")
    if not isinstance(material, dict):
        material = record.get("analysis") if isinstance(record.get("analysis"), dict) else {}
    sections_value = material.get("sections")
    if isinstance(sections_value, dict):
        sections_value = [dict(value, id=key) for key, value in sections_value.items() if isinstance(value, dict)]
    sections: list[dict[str, Any]] = []
    interpretations: list[dict[str, Any]] = []
    for value in _as_list(sections_value):
        if not isinstance(value, dict):
            continue
        section_id = _string(_first(value, "id", "section_id", "key"))
        if not section_id:
            continue
        supports = [item for item in _as_list(value.get("supports")) if isinstance(item, dict) and item.get("text")]
        conflicts = [item for item in _as_list(value.get("conflicts")) if isinstance(item, dict) and item.get("text")]
        section = {
            "id": section_id,
            "title": _first(value, "title", "heading"),
            "conclusion": _first(value, "conclusion", "judgement", "interpretation"),
            "supports": copy.deepcopy(supports),
            "conflicts": copy.deepcopy(conflicts),
            "explanation": _first(value, "explanation", "reason"),
            "score_impact": value.get("score_impact"),
        }
        if any(section.get(key) or section[key] for key in ("conclusion", "supports", "conflicts", "explanation", "score_impact")):
            sections.append(section)
        for relation, values in (("support", supports), ("conflict", conflicts)):
            for item in values:
                interpretations.append({
                    "section_id": section_id,
                    "relation": relation,
                    "type": item.get("type") or "分析",
                    "text": item.get("text"),
                    "source_ref": item.get("source_ref") or "legacy_analysis_material",
                })
    explicit = material.get("interpretations")
    for item in _as_list(explicit):
        if not isinstance(item, dict) or not item.get("text"):
            continue
        relation = _string(_first(item, "relation", "kind", "role")).lower()
        if relation not in {"support", "conflict", "neutral"}:
            relation = "neutral"
        interpretations.append({
            "section_id": _first(item, "section_id", "section"),
            "relation": relation,
            "type": item.get("type") or "分析",
            "text": item.get("text"),
            "source_ref": item.get("source_ref") or "legacy_analysis_material",
        })

    # Older reports have explicit decisions and risk points.  These are
    # analytical interpretations; fundamentals.items and evidence_chain remain
    # raw/neutral evidence and are intentionally not promoted to support.
    decisions = record.get("decisions") if isinstance(record.get("decisions"), dict) else {}
    primary_dimension = _string(decisions.get("unique_primary_dimension"))
    if primary_dimension and primary_dimension not in {"待完整模型", "未形成候选"}:
        sections.append({
            "id": "strength",
            "title": None,
            "conclusion": primary_dimension,
            "supports": [],
            "conflicts": [],
            "explanation": "该判断来自旧赛前报告的明确决策字段。",
            "score_impact": None,
        })
    for point in _as_list(decisions.get("maximum_error_points")):
        if point:
            interpretations.append({
                "section_id": "fork",
                "relation": "conflict",
                "type": "分析",
                "text": _string(point),
                "source_ref": "legacy_report.decisions.maximum_error_points",
            })
    candidate_labels = material.get("candidate_scores") if isinstance(material, dict) else None
    candidate_labels = candidate_labels if isinstance(candidate_labels, dict) else {}
    return sections, {str(key): _string(value.get("script_label")) for key, value in candidate_labels.items() if isinstance(value, dict) and value.get("script_label")}, interpretations


def _legacy_record_material(
    path: Path,
    record: dict[str, Any],
    target: dict[str, Any],
    frozen_prediction: dict[str, Any] | None,
    *,
    kind: str,
) -> dict[str, Any] | None:
    return _LEGACY_MAPPER.map_record(path, record, target, frozen_prediction, kind=kind)


def discover_legacy_analysis_material(
    business_date: str,
    fixture: dict[str, Any],
    *,
    frozen_prediction: dict[str, Any] | None = None,
    workspace_root: Path = LEGACY_WORKSPACE_ROOT,
    analysis_reports_root: Path = LEGACY_ANALYSIS_ROOT,
    postmatch_reports_root: Path = LEGACY_POSTMATCH_ROOT,
) -> dict[str, Any]:
    target = _fixture_projection(fixture, business_date) if fixture.get("business_date") != business_date or "match_id" not in fixture else copy.deepcopy(fixture)
    if not target.get("match_id"):
        target = _fixture_projection(fixture, business_date)
    checked_paths = [
        "data/match_workspace",
        "data/analysis_reports",
        "data/postmatch_reports",
    ]
    found: list[dict[str, Any]] = []
    candidate_files_checked = 0
    for kind, root in (
        ("workspace", Path(workspace_root)),
        ("analysis_reports", Path(analysis_reports_root)),
        ("postmatch_reports", Path(postmatch_reports_root)),
    ):
        for path in _legacy_candidate_paths(root, target, kind=kind):
            candidate_files_checked += 1
            payload = _read_legacy_payload(path)
            if not payload:
                continue
            for record in _legacy_records(payload):
                material = _legacy_record_material(path, record, target, frozen_prediction, kind=kind)
                if material and material.get("status") != "FIXTURE_MISMATCH":
                    found.append(material)
    usable = [item for item in found if item["status"] in {"USABLE", "PARTIALLY_USABLE"}]
    if usable:
        best_status = "USABLE" if any(item["status"] == "USABLE" for item in usable) else "PARTIALLY_USABLE"
        selected = sorted(usable, key=lambda item: (item["status"] != "USABLE", item["path"]))[0]
        return {
            "status": best_status,
            "consistency_checked": True,
            "candidate_files_checked": candidate_files_checked,
            "checked_paths": checked_paths,
            "items": found,
            "interpretations": selected.get("interpretations", []),
            "sections": selected.get("sections", []),
            "candidate_labels": selected.get("candidate_labels", {}),
            "candidate_reasoning": selected.get("candidate_reasoning", {}),
            "hero_script": selected.get("hero_script"),
            "biggest_failure_point": selected.get("biggest_failure_point"),
            "attention_tag": selected.get("attention_tag"),
            "market_interpretation": selected.get("market_interpretation"),
            "risk_evidence": selected.get("risk_evidence", []),
            "decision_evolution": selected.get("decision_evolution"),
            "analysis_origin": selected.get("analysis_origin"),
            "lineage": selected.get("lineage", []),
            "source_keys": selected.get("source_keys", []),
            "trace_coverage": selected.get("trace_coverage", 0),
            "convergence_complete": selected.get("convergence_complete", False),
            "source_refs": selected.get("source_refs", []),
        }
    blocked = [item for item in found if item.get("status") not in {"NOT_FOUND", "FIXTURE_MISMATCH"}]
    if blocked:
        priority = ("PREDICTION_MISMATCH", "TIME_UNVERIFIED", "CONFLICTED")
        blocked_status = next((status for status in priority if any(item.get("status") == status for item in blocked)), blocked[0].get("status", "CONFLICTED"))
        selected = next(item for item in blocked if item.get("status") == blocked_status)
        return {
            "status": blocked_status,
            "consistency_checked": True,
            "candidate_files_checked": candidate_files_checked,
            "checked_paths": checked_paths,
            "items": found,
            "reasons": selected.get("reasons", []),
            "interpretations": [],
            "sections": [],
            "candidate_labels": {},
            "candidate_reasoning": {},
            "analysis_origin": selected.get("analysis_origin"),
            "lineage": selected.get("lineage", []),
            "source_refs": [],
        }
    return {
        "status": "NOT_FOUND",
        "consistency_checked": True,
        "candidate_files_checked": candidate_files_checked,
        "checked_paths": checked_paths,
        "items": [],
        "interpretations": [],
        "sections": [],
        "candidate_labels": {},
        "candidate_reasoning": {},
        "lineage": [],
        "source_refs": [],
    }


def _supports_and_conflicts(
    fixture: dict[str, Any],
    model: dict[str, Any],
    market: dict[str, Any],
    recent_form: dict[str, Any],
    snapshot_input: dict[str, Any],
    analysis_material: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    del fixture, model, market, recent_form, snapshot_input
    supports: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = []
    for item in (analysis_material or {}).get("interpretations", []):
        if not isinstance(item, dict) or not item.get("text"):
            continue
        relation = _string(item.get("relation")).lower()
        projected = {
            "type": item.get("type") or "分析",
            "text": item.get("text"),
            "source_ref": item.get("source_ref") or "legacy_analysis_material",
            "lineage": copy.deepcopy(item.get("lineage") or []),
        }
        if relation == "support":
            supports.append(projected)
        elif relation == "conflict":
            conflicts.append(projected)
    return supports[:3], conflicts[:2]


def _section_payloads(
    fixture: dict[str, Any],
    model: dict[str, Any],
    market: dict[str, Any],
    recent_form: dict[str, Any],
    supports: list[dict[str, Any]],
    conflicts: list[dict[str, Any]],
    analysis_material: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    del market, recent_form, supports, conflicts
    primary = model.get("unique_score")
    scores = model.get("top_scores") or []
    if not primary:
        return [
            {
                "id": section_id,
                "title": title,
                "conclusion": "当前证据不足，暂不扩展判断。",
                "supports": [],
                "conflicts": [],
                "explanation": "当前比赛没有合法冻结预测可供详情页展开。",
                "score_impact": None,
            }
            for section_id, title in SECTION_TITLES
        ]
    empty_conclusion = "当前证据可以核查，但没有可追溯的正式分析结论，暂不扩展判断。"
    material = analysis_material or {}
    source_sections = {
        _string(section.get("id")): section
        for section in material.get("sections", [])
        if isinstance(section, dict) and section.get("id")
    }
    if material.get("status") not in {"USABLE", "PARTIALLY_USABLE"} or not source_sections:
        return [
            {
                "id": section_id,
                "title": title,
                "conclusion": (
                    "当前没有足够可追溯的分析素材解释 rank 之外的比分收敛。"
                    if section_id == "convergence" else empty_conclusion
                ),
                "supports": [],
                "conflicts": [],
                "explanation": "原始基本面、市场和模型字段保留在证据审计层；没有对应的现成解释，不把字段复述成分析判断。",
                "score_impact": None,
            }
            for section_id, title in SECTION_TITLES
        ]
    sections: list[dict[str, Any]] = []
    for section_id, title in SECTION_TITLES:
        source = source_sections.get(section_id) or {}
        sections.append({
            "id": section_id,
            "title": source.get("title") or title,
            "conclusion": source.get("conclusion") or empty_conclusion,
            "supports": [item for item in _as_list(source.get("supports")) if isinstance(item, dict) and item.get("text")],
            "conflicts": [item for item in _as_list(source.get("conflicts")) if isinstance(item, dict) and item.get("text")],
            "explanation": source.get("explanation") or "该段没有足够的现成解释素材，暂不扩展判断。",
            "score_impact": source.get("score_impact") or None,
            "lineage": copy.deepcopy(source.get("lineage") or []),
        })
    return sections


def assemble_match_analysis(
    business_date: str,
    match_id: str,
    *,
    universe_root: Path = UNIVERSE_ROOT,
    jobs_root: Path = JOBS_ROOT,
    prediction_root: Path = PREDICTION_ROOT,
    snapshot_root: Path = SNAPSHOT_ROOT,
    exclusion_root: Path = EXCLUSION_ROOT,
    prospective_root: Path = PROSPECTIVE_ROOT,
    result_root: Path = RESULT_ROOT,
    workspace_root: Path = LEGACY_WORKSPACE_ROOT,
    analysis_reports_root: Path = LEGACY_ANALYSIS_ROOT,
    postmatch_reports_root: Path = LEGACY_POSTMATCH_ROOT,
    **_: Any,
) -> dict[str, Any]:
    del prospective_root
    universe_payload, fixtures = _load_universe(Path(universe_root), business_date)
    fixture = next((item for item in fixtures if item["match_id"] == _string(match_id)), None)
    if fixture is None:
        fixture = {
            "match_id": _string(match_id),
            "match_num": None,
            "business_date": business_date,
            "competition": None,
            "home": None,
            "away": None,
            "kickoff_at": None,
            "nowscore_id": None,
            "shuju_id": None,
            "match_key": None,
            "source_fixture": {},
        }
    jobs = _job_items(Path(jobs_root), business_date)
    job = _job_for_fixture(
        jobs,
        fixture["match_id"],
        fixture.get("match_key"),
        fixture_identity=fixture,
    )
    audit_prediction = _find_prediction(Path(prediction_root), fixture, job)
    if not fixture.get("match_key"):
        fixture["match_key"] = _first(job or {}, "match_key", "matchKey") or _first(audit_prediction or {}, "match_key", "matchKey")
    if not fixture.get("home") and audit_prediction:
        identity = audit_prediction.get("match_identity") or {}
        fixture["home"] = _first(identity, "home", "home_team")
        fixture["away"] = _first(identity, "away", "away_team")
    status = _status(job, audit_prediction)
    serving_prediction = audit_prediction if status == "FROZEN" else None
    excluded_ids = _load_excluded_ids(Path(exclusion_root))
    prediction_id = _string(_first(audit_prediction or {}, "prediction_id", "predictionId")) or None
    pilot_excluded = bool(prediction_id and prediction_id in excluded_ids)
    if pilot_excluded and serving_prediction:
        status_label = "试运行预测"
    else:
        status_label = STATUS_LABELS.get(status, status)
    snapshot_ref = _first(serving_prediction or {}, "input_snapshot_ref", "model_input_snapshot_ref")
    snapshot, snapshot_path = _find_snapshot(Path(snapshot_root), snapshot_ref)
    snapshot_input = _snapshot_input(snapshot)
    recent_form, form_captured_at, form_source = _recent_form(snapshot_input)
    if not serving_prediction:
        recent_form, form_captured_at, form_source = {}, None, None
    model = _prediction_model(serving_prediction or {})
    formal_markets = (
        project_frozen_formal_markets(serving_prediction)
        if serving_prediction
        else None
    )
    market = _market_facts(snapshot_input, serving_prediction or {})
    if not serving_prediction:
        market["model_comparison"]["source_refs"] = []
    result = _find_verified_result(Path(result_root), fixture, audit_prediction)
    if serving_prediction:
        legacy_report_material = discover_legacy_analysis_material(
            business_date,
            fixture,
            frozen_prediction=serving_prediction,
            workspace_root=Path(workspace_root),
            analysis_reports_root=Path(analysis_reports_root),
            postmatch_reports_root=Path(postmatch_reports_root),
        )
    else:
        legacy_report_material = {
            "status": "NOT_PROJECTED_NON_SERVING",
            "consistency_checked": True,
            "candidate_files_checked": 0,
            "checked_paths": [],
            "items": [],
            "interpretations": [],
            "sections": [],
            "candidate_labels": {},
            "candidate_reasoning": {},
            "hero_script": None,
            "biggest_failure_point": None,
            "attention_tag": None,
            "market_interpretation": None,
            "risk_evidence": [],
            "decision_evolution": None,
            "analysis_origin": None,
            "lineage": [],
            "source_keys": [],
            "trace_coverage": 0,
            "convergence_complete": False,
            "source_refs": [],
        }
    analysis_material = {
        "status": legacy_report_material.get("status"),
        "consistency_checked": legacy_report_material.get("consistency_checked"),
        "candidate_files_checked": legacy_report_material.get("candidate_files_checked", 0),
        "checked_paths": copy.deepcopy(legacy_report_material.get("checked_paths") or []),
        "items": copy.deepcopy(legacy_report_material.get("items") or []),
        "sections": copy.deepcopy(legacy_report_material.get("sections") or []),
        "interpretations": copy.deepcopy(legacy_report_material.get("interpretations") or []),
        "candidate_labels": copy.deepcopy(legacy_report_material.get("candidate_labels") or {}),
        "candidate_reasoning": copy.deepcopy(legacy_report_material.get("candidate_reasoning") or {}),
        "biggest_failure_point": legacy_report_material.get("biggest_failure_point"),
        "market_interpretation": copy.deepcopy(legacy_report_material.get("market_interpretation")),
        "risk_evidence": copy.deepcopy(legacy_report_material.get("risk_evidence") or []),
        "decision_evolution": copy.deepcopy(legacy_report_material.get("decision_evolution")),
        "analysis_origin": copy.deepcopy(legacy_report_material.get("analysis_origin")),
        "lineage": copy.deepcopy(legacy_report_material.get("lineage") or []),
        "source_keys": copy.deepcopy(legacy_report_material.get("source_keys") or []),
        "trace_coverage": legacy_report_material.get("trace_coverage", 0),
        "convergence_complete": legacy_report_material.get("convergence_complete", False),
        "source_refs": copy.deepcopy(legacy_report_material.get("source_refs") or []),
    }
    candidate_labels = analysis_material.get("candidate_labels") or {}
    for item in model.get("top_scores", []):
        label = candidate_labels.get(_string(item.get("score")))
        if label:
            item["script_label"] = label
    supports, conflicts = _supports_and_conflicts(fixture, model, market, recent_form, snapshot_input, analysis_material)
    sections = _section_payloads(fixture, model, market, recent_form, supports, conflicts, analysis_material)
    sources = _source_refs(serving_prediction or {}, snapshot)
    reason_code = _reason_code(job, audit_prediction)
    formal_eligible = _formal_eligible(serving_prediction, pilot_excluded)
    freeze_at = _iso(_first(serving_prediction or {}, "freeze_created_at", "freeze_at"))
    prediction_created_at = _iso(_first(serving_prediction or {}, "prediction_created_at", "created_at"))
    source_cutoff_at = _iso(_first(serving_prediction or {}, "source_cutoff_at", "model_input_as_of_at"))
    evidence_updated_at = _iso(
        _first(
            snapshot or {},
            "captured_at",
            "source_cutoff_at",
            default=market.get("facts", {}).get("fetched_at") or form_captured_at,
        )
    )
    if snapshot is None:
        evidence_updated_at = None
    missing_evidence = []
    if not serving_prediction:
        missing_evidence.append(reason_code or "NO_FROZEN_PREDICTION")
    if serving_prediction and not snapshot:
        missing_evidence.append("INPUT_SNAPSHOT_UNAVAILABLE")
    if serving_prediction and not recent_form:
        missing_evidence.append("RECENT_FORM_UNAVAILABLE")
    source_quality = {
        "data_grade": serving_prediction.get("data_grade") if serving_prediction else None,
        "base_input_quality": serving_prediction.get("base_input_quality") if serving_prediction else None,
        "market_intelligence_quality": serving_prediction.get("market_intelligence_quality") if serving_prediction else None,
        "missing": _unique([*missing_evidence, *(_as_list((serving_prediction or {}).get("missing_fields")))]) ,
        "source_references": sources,
        "input_snapshot_ref": snapshot_ref or (snapshot_path.as_posix() if snapshot_path else None),
        "recent_form_source": form_source,
        "recent_form_captured_at": form_captured_at,
        "note": None,
    }
    hero_summary = (
        f"冻结前证据已整理；首推 {model['unique_score']}，邻近候选为 {', '.join(item['score'] for item in model['top_scores'][1:3]) or '无'}。"
        if model.get("unique_score")
        else ("预测尚未冻结，当前只展示可追溯的比赛身份与状态。" if status == "PENDING" else "当前证据不足，暂不扩展判断。")
    )
    contract = {
        "analysis_contract_version": ANALYSIS_CONTRACT_VERSION,
        "identity": {
            key: fixture.get(key)
            for key in (
                "match_id",
                "match_key",
                "business_date",
                "competition",
                "home",
                "away",
                "kickoff_at",
                "match_num",
                "nowscore_id",
                "shuju_id",
            )
        },
        "status": {
            "code": status,
            "label": status_label,
            "reason_code": reason_code,
            "reason_text": STATUS_REASON_LABELS.get(reason_code or "", reason_code),
        },
        "current_job_resolution": _public_job_resolution((job or {}).get("current_job_resolution")),
        "timestamps": {
            "prediction_created_at": prediction_created_at,
            "prediction_frozen_at": freeze_at,
            "source_cutoff_at": source_cutoff_at,
            "evidence_updated_at": evidence_updated_at,
        },
        "hero": {
            "primary_score": model.get("unique_score"),
            "neighbor_scores": [item.get("score") for item in model.get("top_scores", [])[1:3]],
            "summary": hero_summary,
            "script": (serving_prediction or {}).get("short_match_script") or legacy_report_material.get("hero_script"),
            "attention_tag": (serving_prediction or {}).get("attention_tag") or legacy_report_material.get("attention_tag"),
            "supports": supports,
            "conflicts": conflicts,
            "biggest_failure_point": legacy_report_material.get("biggest_failure_point") or model.get("uncertainty", {}).get("main_risk"),
            "probabilities": copy.deepcopy(model.get("probabilities") or {}),
        },
        "candidate_scores": copy.deepcopy(model.get("top_scores", [])[:3]),
        "analysis_sections": sections,
        "evidence": {
            "fundamentals": {
                "recent_form": recent_form,
                "captured_at": form_captured_at,
                "source": form_source,
            },
            "market": market,
            "model": model,
            "source_quality": source_quality,
            "legacy_report_material": copy.deepcopy(legacy_report_material),
        },
        "analysis_material": analysis_material,
        "market": market,
        "model": model,
        "post_freeze_updates": {
            "status": "NONE_RECORDED",
            "items": [],
        },
        "result": result,
        "formal_markets": formal_markets,
        "governance": {
            "prediction_id": prediction_id,
            "pilot_excluded": pilot_excluded,
            "formal_prospective_eligible": formal_eligible,
            "formal_eligibility_policy": (audit_prediction or {}).get("formal_eligibility_policy"),
            "data_grade": (audit_prediction or {}).get("data_grade"),
            "base_input_quality": (audit_prediction or {}).get("base_input_quality"),
            "prediction_variant": (audit_prediction or {}).get("prediction_variant"),
            "model_role": (audit_prediction or {}).get("model_role"),
            "product_role": (audit_prediction or {}).get("product_role"),
            "prediction_record_ref": prediction_id,
            "input_snapshot_ref": snapshot_ref,
        },
        "source_quality": source_quality,
        "canonical_sources": {
            "universe": f"data/prediction_universe/{business_date}.json",
            "job_ledger": f"data/base_prediction_jobs/{business_date}.json",
            "prediction_record": f"data/model_governance/predictions/{prediction_id}.json" if prediction_id else None,
            "input_snapshot": snapshot_ref,
        },
        "universe_status": universe_payload.get("status"),
    }
    return contract


def _dates_in_universe(universe_root: Path) -> list[str]:
    if not universe_root.exists():
        return []
    return sorted(path.stem for path in universe_root.glob("*.json") if re.fullmatch(r"\d{4}-\d{2}-\d{2}", path.stem))


def select_best_real_match(
    business_date: str | None = None,
    *,
    universe_root: Path = UNIVERSE_ROOT,
    jobs_root: Path = JOBS_ROOT,
    prediction_root: Path = PREDICTION_ROOT,
    snapshot_root: Path = SNAPSHOT_ROOT,
    exclusion_root: Path = EXCLUSION_ROOT,
    prospective_root: Path = PROSPECTIVE_ROOT,
    result_root: Path = RESULT_ROOT,
    workspace_root: Path = LEGACY_WORKSPACE_ROOT,
    analysis_reports_root: Path = LEGACY_ANALYSIS_ROOT,
    postmatch_reports_root: Path = LEGACY_POSTMATCH_ROOT,
    **_: Any,
) -> dict[str, Any]:
    dates = [business_date] if business_date else _dates_in_universe(Path(universe_root))
    candidates: list[dict[str, Any]] = []
    excluded_ids = _load_excluded_ids(Path(exclusion_root))
    for date in dates:
        _, fixtures = _load_universe(Path(universe_root), date)
        jobs = _job_items(Path(jobs_root), date)
        for fixture in fixtures:
            job = _job_for_fixture(jobs, fixture["match_id"], fixture.get("match_key"))
            prediction = _find_prediction(Path(prediction_root), fixture, job)
            if not prediction or _status(job, prediction) != "FROZEN":
                continue
            snapshot_ref = _first(prediction, "input_snapshot_ref", "model_input_snapshot_ref")
            snapshot, _ = _find_snapshot(Path(snapshot_root), snapshot_ref)
            snapshot_input = _snapshot_input(snapshot)
            recent, _, _ = _recent_form(snapshot_input)
            market = _market_facts(snapshot_input, prediction)
            model = _prediction_model(prediction)
            legacy_report_material = discover_legacy_analysis_material(
                date,
                fixture,
                frozen_prediction=prediction,
                workspace_root=Path(workspace_root),
                analysis_reports_root=Path(analysis_reports_root),
                postmatch_reports_root=Path(postmatch_reports_root),
            )
            score = 0
            score += 5 if fixture.get("match_id") else 0
            score += 5 if model.get("unique_score") else 0
            score += min(5, len(model.get("top_scores") or []))
            score += 3 if len(model.get("probabilities") or {}) >= 3 else 0
            score += 3 if recent else 0
            score += 3 if market.get("facts", {}).get("bookmaker_count") else 0
            score += min(3, len(_source_refs(prediction, snapshot)))
            score += {"USABLE": 12, "PARTIALLY_USABLE": 6}.get(legacy_report_material.get("status"), 0)
            score += min(10, int(legacy_report_material.get("trace_coverage", 0) or 0) * 2)
            score += 4 if legacy_report_material.get("convergence_complete") else 0
            score -= 10 if legacy_report_material.get("status") in {"CONFLICTED", "PREDICTION_MISMATCH", "TIME_UNVERIFIED"} else 0
            pilot_excluded = _string(prediction.get("prediction_id")) in excluded_ids
            score -= 1 if pilot_excluded else 0
            candidates.append({
                "match_id": fixture["match_id"],
                "prediction_id": prediction.get("prediction_id"),
                "business_date": date,
                "competition": fixture.get("competition"),
                "home": fixture.get("home"),
                "away": fixture.get("away"),
                "evidence_score": score,
                "pilot_excluded": pilot_excluded,
                "legacy_report_material_status": legacy_report_material.get("status"),
                "legacy_report_material_checked": legacy_report_material.get("consistency_checked") is True,
                "legacy_trace_coverage": legacy_report_material.get("trace_coverage", 0),
                "legacy_convergence_complete": legacy_report_material.get("convergence_complete", False),
            })
    if not candidates:
        raise LookupError("No frozen prediction with a stable universe identity was found")
    return sorted(candidates, key=lambda item: (-item["evidence_score"], item["business_date"], item["match_id"]))[0]


def _substantive_payload(contract: dict[str, Any]) -> dict[str, Any]:
    payload = copy.deepcopy(contract)
    for key in ("generated_at", "content_hash", "revision_id", "revision_ref"):
        payload.pop(key, None)
    return payload


def _content_hash(contract: dict[str, Any]) -> str:
    encoded = json.dumps(_substantive_payload(contract), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def write_analysis_contract(
    contract: dict[str, Any],
    *,
    output_root: Path = MATCH_ANALYSIS_ROOT,
    generated_at: str | None = None,
) -> dict[str, Any]:
    payload = copy.deepcopy(contract)
    identity = payload.get("identity") or {}
    business_date = _string(identity.get("business_date"))
    match_id = _string(identity.get("match_id"))
    if not business_date or not match_id:
        raise ValueError("analysis contract requires business_date and match_id")
    digest = _content_hash(payload)
    report_dir = Path(output_root) / business_date / match_id
    revision_name = f"revision-{digest[:16]}.json"
    revision_path = report_dir / revision_name
    if not revision_path.exists():
        revision_payload = copy.deepcopy(payload)
        revision_payload.update({
            "revision_id": revision_name.removesuffix(".json"),
            "content_hash": digest,
        })
        _write_json(revision_path, revision_payload)
    latest_payload = copy.deepcopy(payload)
    latest_payload.update({
        "generated_at": generated_at or _now_iso(),
        "content_hash": digest,
        "revision_id": revision_name.removesuffix(".json"),
        "revision_ref": revision_name,
    })
    _write_json(report_dir / "latest.json", latest_payload)
    return latest_payload


def build_match_contracts(
    *,
    business_dates: Iterable[str] | None = None,
    output_root: Path = MATCH_ANALYSIS_ROOT,
    **roots: Any,
) -> list[dict[str, Any]]:
    universe_root = Path(roots.pop("universe_root", UNIVERSE_ROOT))
    dates = list(business_dates) if business_dates is not None else _dates_in_universe(universe_root)
    contracts: list[dict[str, Any]] = []
    for date in dates:
        _, fixtures = _load_universe(universe_root, date)
        for fixture in fixtures:
            contract = assemble_match_analysis(date, fixture["match_id"], universe_root=universe_root, **roots)
            contracts.append(write_analysis_contract(contract, output_root=output_root))
    return contracts


def _main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", help="business date to assemble")
    parser.add_argument("--all", action="store_true", help="assemble every saved Universe date")
    parser.add_argument("--select", action="store_true", help="print the evidence-rich real sample")
    args = parser.parse_args()
    if args.select:
        print(json.dumps(select_best_real_match(args.date), ensure_ascii=False, indent=2))
    dates = [args.date] if args.date else None
    if args.all or args.date:
        built = build_match_contracts(business_dates=dates)
        print(json.dumps({"contracts_written": len(built)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
