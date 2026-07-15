#!/usr/bin/env python3
"""Publish analysis-owned EV profiles for the browser overlay.

Profiles are read-only analysis inputs. Publishing one never submits an order,
changes bankroll/exposure, or changes lock state. A stale active profile is
replaced with an explicit inactive profile when the current report contains no
usable candidate for a known live match id.
"""

from __future__ import annotations

import json
import math
import re
from datetime import datetime
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_ROOT = PROJECT_ROOT / "data" / "live_ev_profiles"
MODEL_NAME = "Football Betting OneShot"
MODEL_VERSION = "v0.14.0"
MATCH_ID = re.compile(r"^[0-9]{1,30}$")
SUPPORTED_CONTRACT_TYPES = {"binary_no_push", "three_way_selection"}


class LiveEvProfileError(ValueError):
    """Raised when a profile could map the wrong probability to a contract."""


def _text(value: Any) -> str:
    return str(value or "").strip()


def _probability(value: Any, field: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise LiveEvProfileError(f"{field} must be a number") from exc
    if not math.isfinite(number) or not 0 < number < 1:
        raise LiveEvProfileError(f"{field} must be between 0 and 1")
    return number


def _nonnegative(value: Any, field: str, default: float = 0.0) -> float:
    try:
        number = float(default if value is None else value)
    except (TypeError, ValueError) as exc:
        raise LiveEvProfileError(f"{field} must be a number") from exc
    if not math.isfinite(number) or number < 0:
        raise LiveEvProfileError(f"{field} must be non-negative")
    return number


def _validated_match_id(value: Any) -> str:
    match_id = _text(value)
    if not MATCH_ID.fullmatch(match_id):
        raise LiveEvProfileError("contract.match_id must contain digits only")
    return match_id


def normalize_active_profile(raw: dict, *, report: dict, match: dict) -> dict:
    """Validate an active candidate and return the public overlay profile."""

    if raw.get("active") is not True:
        raise LiveEvProfileError("live_ev_profile.active must be true")
    contract = raw.get("contract") or {}
    probability = raw.get("probability") or {}
    execution = raw.get("execution") or {}
    price = raw.get("price") or {}

    match_id = _validated_match_id(contract.get("match_id"))
    market_code = _text(contract.get("market_code"))
    market_name = _text(contract.get("market_name"))
    selection_code = _text(contract.get("selection_code"))
    selection_name = _text(contract.get("selection_name"))
    contract_type = _text(contract.get("contract_type"))
    if not (market_code or market_name):
        raise LiveEvProfileError("contract requires market_code or market_name")
    if not (selection_code or selection_name):
        raise LiveEvProfileError("contract requires selection_code or selection_name")
    if contract_type not in SUPPORTED_CONTRACT_TYPES:
        raise LiveEvProfileError("contract.contract_type is not supported by simple EV")

    point = _probability(probability.get("point"), "probability.point")
    conservative = _probability(probability.get("conservative"), "probability.conservative")
    if conservative > point:
        raise LiveEvProfileError("probability.conservative cannot exceed probability.point")
    if probability.get("confirmed_model_output") is not True:
        raise LiveEvProfileError("probability must be confirmed model output")
    source = _text(probability.get("source"))
    calibration_status = _text(probability.get("calibration_status"))
    if not source or not calibration_status:
        raise LiveEvProfileError("probability source and calibration_status are required")

    max_quote_age_ms = int(price.get("max_quote_age_ms", 15000))
    if max_quote_age_ms < 1000:
        raise LiveEvProfileError("price.max_quote_age_ms must be at least 1000")

    return {
        "schema_version": "1.0",
        "profile_id": "",
        "active": True,
        "inactive_reason": None,
        "model_name": report.get("model_name") or MODEL_NAME,
        "model_version": report.get("model_version") or MODEL_VERSION,
        "analysis_timestamp": report.get("analysis_timestamp"),
        "published_at": None,
        "match": {
            "match_id": match_id,
            "home": match.get("home"),
            "away": match.get("away"),
            "competition": match.get("competition"),
            "kickoff_local": match.get("kickoff_local"),
        },
        "contract": {
            "match_id": match_id,
            "market_code": market_code or None,
            "market_name": market_name or None,
            "child_market_code": _text(contract.get("child_market_code")) or None,
            "market_id": _text(contract.get("market_id")) or None,
            "handicap_line": _text(contract.get("handicap_line")),
            "selection_code": selection_code or None,
            "selection_name": selection_name or None,
            "contract_type": contract_type,
        },
        "probability": {
            "point": point,
            "conservative": conservative,
            "confirmed_model_output": True,
            "source": source,
            "calibration_status": calibration_status,
        },
        "price": {
            "source": "bridge",
            "max_quote_age_ms": max_quote_age_ms,
        },
        "execution": {
            "minimum_conservative_ev": _nonnegative(
                execution.get("minimum_conservative_ev"),
                "execution.minimum_conservative_ev",
            ),
        },
        "analysis_input_only": True,
        "execution_authorized": False,
        "explicit_lock_required": True,
        "lock_state_changed": False,
        "bankroll_state_changed": False,
    }


def inactive_profile(match_id: str, *, report: dict, match: dict, reason: str) -> dict:
    match_id = _validated_match_id(match_id)
    return {
        "schema_version": "1.0",
        "profile_id": "",
        "active": False,
        "inactive_reason": reason,
        "model_name": report.get("model_name") or MODEL_NAME,
        "model_version": report.get("model_version") or MODEL_VERSION,
        "analysis_timestamp": report.get("analysis_timestamp"),
        "published_at": None,
        "match": {
            "match_id": match_id,
            "home": match.get("home"),
            "away": match.get("away"),
            "competition": match.get("competition"),
            "kickoff_local": match.get("kickoff_local"),
        },
        "contract": None,
        "probability": None,
        "price": None,
        "execution": None,
        "analysis_input_only": True,
        "execution_authorized": False,
        "explicit_lock_required": True,
        "lock_state_changed": False,
        "bankroll_state_changed": False,
    }


def _atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def _history_dir(root: Path, stamp: str) -> Path:
    candidate = root / "history" / stamp
    suffix = 1
    while candidate.exists():
        candidate = root / "history" / f"{stamp}_{suffix:02d}"
        suffix += 1
    candidate.mkdir(parents=True, exist_ok=False)
    return candidate


def rebuild_current_profile_index(
    output_root: Path | str = DEFAULT_OUTPUT_ROOT,
    *,
    now: datetime | None = None,
) -> Path:
    """Rebuild the public current-profile index used by the browser extension."""

    current_dir = Path(output_root) / "current"
    current_dir.mkdir(parents=True, exist_ok=True)
    indexed_profiles = []
    for profile_path in sorted(current_dir.glob("*.json")):
        if profile_path.name == "index.json":
            continue
        try:
            indexed = json.loads(profile_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(indexed, dict) and isinstance(indexed.get("match"), dict):
            indexed_profiles.append(indexed)
    instant = now or datetime.now().astimezone()
    index_path = current_dir / "index.json"
    _atomic_json(index_path, {
        "schema_version": "1.0",
        "generated_at": instant.isoformat(),
        "profiles": indexed_profiles,
        "analysis_input_only": True,
        "execution_authorized": False,
    })
    return index_path


def publish_live_ev_profiles(
    payload: dict,
    *,
    output_root: Path | str = DEFAULT_OUTPUT_ROOT,
    report_payload_path: Path | str | None = None,
    now: datetime | None = None,
) -> dict:
    """Publish one unambiguous current overlay profile per live match id."""

    root = Path(output_root)
    instant = now or datetime.now().astimezone()
    stamp = instant.strftime("%Y%m%d_%H%M%S")
    report = payload.get("report") or {}
    match = payload.get("match") or {}
    candidates = (payload.get("betting") or {}).get("candidates") or []
    candidate_profiles = [
        candidate.get("live_ev_profile")
        for candidate in candidates
        if isinstance(candidate, dict) and isinstance(candidate.get("live_ev_profile"), dict)
    ]
    # 概率赋值与“当前是否已有正 EV 候选”是两件不同的事。赛前分析可以
    # 先把主维度概率发布给悬浮窗，悬浮窗再用用户渠道的实时价格判断 EV；
    # 这不会创建候选注单，更不会改变锁单或资金状态。
    analysis_profiles = payload.get("live_ev_profiles") or []
    if isinstance(analysis_profiles, dict):
        analysis_profiles = [analysis_profiles]
    raw_profiles = [
        profile for profile in analysis_profiles if isinstance(profile, dict)
    ] or candidate_profiles
    skipped: list[dict] = []
    valid: list[tuple[dict, bool]] = []
    for index, raw in enumerate(raw_profiles):
        try:
            valid.append((normalize_active_profile(raw, report=report, match=match), bool(raw.get("overlay_primary"))))
        except LiveEvProfileError as exc:
            skipped.append({"profile_index": index, "reason": str(exc)})

    by_match: dict[str, list[tuple[dict, bool]]] = {}
    for profile, primary in valid:
        by_match.setdefault(profile["match"]["match_id"], []).append((profile, primary))

    known_match_id = _text(match.get("live_match_id") or match.get("match_id"))
    if known_match_id and MATCH_ID.fullmatch(known_match_id) and known_match_id not in by_match:
        reason = "no_complete_live_ev_profile"
        if skipped:
            reason = "invalid_live_ev_candidate"
        by_match[known_match_id] = [(inactive_profile(known_match_id, report=report, match=match, reason=reason), True)]

    selected: list[dict] = []
    for match_id, rows in by_match.items():
        if len(rows) == 1:
            selected.append(rows[0][0])
            continue
        primaries = [profile for profile, primary in rows if primary]
        if len(primaries) == 1:
            selected.append(primaries[0])
            continue
        selected.append(inactive_profile(
            match_id,
            report=report,
            match=match,
            reason="ambiguous_multiple_live_ev_candidates",
        ))
        skipped.append({"match_id": match_id, "reason": "exactly one overlay_primary candidate is required"})

    if not selected:
        return {
            "status": "not_published",
            "published": [],
            "skipped": skipped,
            "reason": "no_live_match_id_or_live_ev_profile",
        }

    history_dir = _history_dir(root, stamp)
    published = []
    for index, profile in enumerate(selected, start=1):
        match_id = profile["match"]["match_id"]
        profile["published_at"] = instant.isoformat()
        profile["profile_id"] = f"{stamp}-{match_id}-{index}"
        profile["report_payload_path"] = str(report_payload_path) if report_payload_path else None
        history_path = history_dir / f"{stamp}_{match_id}_live_ev_profile.json"
        current_path = root / "current" / f"{match_id}.json"
        _atomic_json(history_path, profile)
        _atomic_json(current_path, profile)
        published.append({
            "match_id": match_id,
            "active": profile["active"],
            "profile_id": profile["profile_id"],
            "current_path": str(current_path),
            "history_path": str(history_path),
        })

    rebuild_current_profile_index(root, now=instant)

    return {
        "status": "published",
        "published": published,
        "skipped": skipped,
        "analysis_input_only": True,
        "execution_authorized": False,
        "lock_state_changed": False,
        "bankroll_state_changed": False,
    }

