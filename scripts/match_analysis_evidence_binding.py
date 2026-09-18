"""Thin evidence/provenance binding for Match Detail and late confirmed XI."""

from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Mapping
from datetime import datetime
from typing import Any

EVIDENCE_ENVELOPE_VERSION = "match_analysis_evidence_envelope.v1"
LATE_BRIEFING_CONTRACT_VERSION = "match_analysis_late_briefing.v1"

_REQUIRED_FIELDS = (
    "recent_form",
    "recent_process_context",
    "market_context",
    "future_schedule_rest",
    "injuries",
    "suspensions",
    "availability_summary",
    "lineup_state",
)
_AVAILABILITY_FIELDS = {"injuries", "suspensions", "availability_summary"}
_ABSENCE = {"OUT", "ABSENT", "INJURED", "SUSPENDED", "DOUBTFUL", "UNAVAILABLE"}
_RECOVERED = {"RECOVERED", "FIT", "AVAILABLE", "CLEARED", "RETURNED"}


def _text(value: Any) -> str | None:
    value = str(value).strip() if value is not None else ""
    return value or None


def _dt(value: Any) -> datetime | None:
    text = _text(value)
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def stable_hash(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def article_base_hash(article: Mapping[str, Any]) -> str:
    payload = copy.deepcopy(dict(article))
    payload.pop("late_briefing", None)
    payload.pop("base_article_hash", None)
    return stable_hash(payload)


def _cutoff(prediction: Mapping[str, Any]) -> str | None:
    for key in ("source_cutoff_at", "model_input_as_of_at", "prediction_created_at", "created_at"):
        value = _text(prediction.get(key))
        if value:
            return value
    return None


def _bundle(evidence: Mapping[str, Any]) -> Mapping[str, Any]:
    bundle = evidence.get("prematch_evidence")
    return bundle if isinstance(bundle, Mapping) else {}


def _target(evidence: Mapping[str, Any], fixture: Mapping[str, Any]) -> Mapping[str, Any]:
    target = _bundle(evidence).get("target_fixture")
    return target if isinstance(target, Mapping) else fixture


def _kickoff(
    prediction: Mapping[str, Any],
    evidence: Mapping[str, Any],
    fixture: Mapping[str, Any],
) -> str | None:
    target = _target(evidence, fixture)
    for value in (target.get("kickoff_at"), prediction.get("kickoff_at"), fixture.get("kickoff_at")):
        text = _text(value)
        if text:
            return text
    return None


def _subject(
    prediction: Mapping[str, Any],
    evidence: Mapping[str, Any],
    fixture: Mapping[str, Any],
) -> str:
    target = _target(evidence, fixture)
    for value in (
        target.get("provider_match_id"),
        target.get("source_fixture_id"),
        evidence.get("match_id"),
        fixture.get("match_id"),
        prediction.get("match_id"),
    ):
        text = _text(value)
        if text:
            return f"fixture:{text}"
    return "fixture:unknown"


def _resolve_availability(
    value: Any,
    *,
    target: Mapping[str, Any],
    cutoff: datetime | None,
) -> tuple[Any, dict[str, Any] | None]:
    records = value.get("records") if isinstance(value, Mapping) else None
    if not isinstance(records, list):
        return copy.deepcopy(value), None

    allowed_teams = {
        _text(target.get("home_team_id")),
        _text(target.get("away_team_id")),
    } - {None}
    latest: dict[tuple[str, str], tuple[datetime, dict[str, Any]]] = {}
    errors: list[str] = []

    for raw in records:
        if not isinstance(raw, Mapping):
            errors.append("NON_MAPPING_RECORD")
            continue
        player_id = _text(raw.get("player_id"))
        team_id = _text(raw.get("team_id"))
        as_of = _dt(raw.get("as_of"))
        if not player_id or not team_id or as_of is None:
            errors.append("IDENTITY_OR_TIME_MISSING")
            continue
        if allowed_teams and team_id not in allowed_teams:
            errors.append("TEAM_ID_MISMATCH")
            continue
        if cutoff is not None and as_of > cutoff:
            continue
        key = (team_id, player_id)
        if key not in latest or as_of > latest[key][0]:
            latest[key] = (as_of, copy.deepcopy(dict(raw)))

    resolved: list[dict[str, Any]] = []
    current_absences: list[dict[str, Any]] = []
    stale_count = 0
    for (team_id, player_id), (_, record) in sorted(latest.items()):
        expires = _dt(record.get("valid_until"))
        stale = bool(cutoff is not None and expires is not None and expires < cutoff)
        status = (_text(record.get("status")) or "").upper()
        current_absence = status in _ABSENCE and not stale
        if status in _RECOVERED:
            current_absence = False
        record.update(
            team_id=team_id,
            player_id=player_id,
            stale_at_cutoff=stale,
            current_absence=current_absence,
        )
        resolved.append(record)
        stale_count += int(stale)
        if current_absence:
            current_absences.append(copy.deepcopy(record))

    normalized = copy.deepcopy(dict(value))
    normalized["resolved_records"] = resolved
    normalized["current_absences"] = current_absences
    return normalized, {
        "records_seen": len(records),
        "resolved_count": len(resolved),
        "stale_count": stale_count,
        "binding_errors": errors,
    }


def _field_status(field: Mapping[str, Any], availability: Mapping[str, Any] | None) -> str:
    state = (_text(field.get("state")) or "").upper()
    if state == "ABSENT":
        return "MISSING"
    if state in {"NOT_COVERED", "UNSUPPORTED"}:
        return "NOT_COVERED"
    if state != "PRESENT":
        return "DEGRADED"
    if (_text(field.get("freshness")) or "").upper() == "STALE":
        return "STALE"
    if availability:
        if availability["resolved_count"] and availability["stale_count"] == availability["resolved_count"]:
            return "STALE"
        if availability["records_seen"] and not availability["resolved_count"] and availability["binding_errors"]:
            return "DEGRADED"
    return "VERIFIED"


def build_evidence_envelope(
    prediction: Mapping[str, Any] | None,
    football_evidence: Mapping[str, Any] | None,
    accepted_fixture: Mapping[str, Any] | None,
) -> dict[str, Any]:
    prediction = prediction if isinstance(prediction, Mapping) else {}
    evidence = football_evidence if isinstance(football_evidence, Mapping) else {}
    fixture = accepted_fixture if isinstance(accepted_fixture, Mapping) else {}
    cutoff_text = _cutoff(prediction)
    kickoff_text = _kickoff(prediction, evidence, fixture)
    cutoff = _dt(cutoff_text)
    kickoff = _dt(kickoff_text)
    target = _target(evidence, fixture)
    bundle = _bundle(evidence)
    fields = bundle.get("fields") if isinstance(bundle.get("fields"), Mapping) else {}

    prediction_status = "VERIFIED" if prediction and cutoff is not None else "DEGRADED"
    if cutoff is not None and kickoff is not None and cutoff > kickoff:
        prediction_status = "DEGRADED"
    items: list[dict[str, Any]] = [{
        "evidence_id": "prediction_record.probabilities_and_score_cluster",
        "subject_id": _text(prediction.get("prediction_id")) or _subject(prediction, evidence, fixture),
        "type": "frozen_prediction",
        "value": {
            key: copy.deepcopy(prediction.get(key))
            for key in ("probabilities", "top_scores", "score_distribution", "totals", "btts")
            if key in prediction
        },
        "source": {"provider": "frozen_prediction_record"},
        "observed_at": cutoff_text,
        "as_of": cutoff_text,
        "freshness": "AT_OR_BEFORE_CUTOFF" if prediction_status == "VERIFIED" else "UNKNOWN",
        "status": prediction_status,
        "admissible": prediction_status == "VERIFIED",
    }]

    names = list(dict.fromkeys([*fields.keys(), *_REQUIRED_FIELDS]))
    source = bundle.get("source") if isinstance(bundle.get("source"), Mapping) else {}
    for name in names:
        field = fields.get(name)
        if not isinstance(field, Mapping):
            items.append({
                "evidence_id": f"football_evidence.{name}",
                "subject_id": _subject(prediction, evidence, fixture),
                "type": name,
                "value": None,
                "source": {"provider": evidence.get("source_provider")},
                "observed_at": None,
                "as_of": None,
                "freshness": "UNKNOWN",
                "status": "NOT_COVERED",
                "admissible": False,
            })
            continue

        value = copy.deepcopy(field.get("value"))
        availability = None
        if name in _AVAILABILITY_FIELDS:
            value, availability = _resolve_availability(value, target=target, cutoff=cutoff)
        status = _field_status(field, availability)
        timestamps = [
            parsed
            for parsed in (_dt(field.get("observed_at")), _dt(field.get("source_update_at")))
            if parsed is not None
        ]
        latest = max(timestamps) if timestamps else None
        if status == "STALE":
            freshness = "STALE"
        elif latest is None:
            freshness = "UNKNOWN"
        elif kickoff is not None and latest > kickoff:
            freshness = "AFTER_KICKOFF"
        elif cutoff is not None and latest > cutoff:
            freshness = "AFTER_CUTOFF"
        else:
            freshness = "AT_OR_BEFORE_CUTOFF"
        admissible = (
            status == "VERIFIED"
            and field.get("prematch_eligible") is True
            and cutoff is not None
            and freshness == "AT_OR_BEFORE_CUTOFF"
        )
        items.append({
            "evidence_id": f"football_evidence.{name}",
            "subject_id": _subject(prediction, evidence, fixture),
            "type": name,
            "value": value,
            "source": {
                "provider": source.get("provider") or evidence.get("source_provider"),
                "surface": field.get("surface"),
                "source_references": copy.deepcopy(source.get("source_references") or []),
            },
            "observed_at": field.get("observed_at"),
            "as_of": field.get("observed_at"),
            "freshness": freshness,
            "status": status,
            "admissible": admissible,
            "reason_code": field.get("reason_code"),
            "source_update_at": field.get("source_update_at"),
            "availability_resolution": availability,
        })

    payload = {
        "contract_version": EVIDENCE_ENVELOPE_VERSION,
        "article_cutoff": cutoff_text,
        "kickoff_at": kickoff_text,
        "items": items,
    }
    return {**payload, "content_hash": stable_hash(payload)}


def bind_article_plan(plan: Any, envelope: Mapping[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(plan, list):
        return []
    lookup = {
        item.get("evidence_id"): item
        for item in envelope.get("items", [])
        if isinstance(item, Mapping)
    }
    bound: list[dict[str, Any]] = []
    for raw in plan:
        refs = raw.get("evidence_refs") if isinstance(raw, Mapping) else None
        if not isinstance(refs, list) or not refs:
            continue
        if any(ref not in lookup or lookup[ref].get("admissible") is not True for ref in refs):
            continue
        item = copy.deepcopy(dict(raw))
        item["order"] = len(bound) + 1
        bound.append(item)
    return bound


def _confirmed_side(
    value: Mapping[str, Any],
    side: str,
    target: Mapping[str, Any],
) -> tuple[dict[str, Any] | None, str | None]:
    payload = value.get(side)
    if not isinstance(payload, Mapping):
        return None, "LINEUP_SIDE_MISSING"
    team_id = _text(payload.get("team_id"))
    if not team_id or team_id != _text(target.get(f"{side}_team_id")):
        return None, "LINEUP_IDENTITY_MISMATCH"
    players = payload.get("starting_xi")
    if not isinstance(players, list) or len(players) != 11:
        return None, "CONFIRMED_XI_INCOMPLETE"
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for player in players:
        player_id = _text(player.get("player_id")) if isinstance(player, Mapping) else None
        if not player_id or player_id in seen:
            return None, "PLAYER_IDENTITY_MISSING"
        seen.add(player_id)
        normalized.append({"player_id": player_id, "name": _text(player.get("name"))})
    return {"team_id": team_id, "players": normalized}, None


def build_late_briefing(
    base_article: Mapping[str, Any],
    prediction: Mapping[str, Any] | None,
    football_evidence: Mapping[str, Any] | None,
    evidence_envelope: Mapping[str, Any],
) -> dict[str, Any]:
    prediction = prediction if isinstance(prediction, Mapping) else {}
    evidence = football_evidence if isinstance(football_evidence, Mapping) else {}
    omitted = {
        "contract_version": LATE_BRIEFING_CONTRACT_VERSION,
        "status": "OMITTED",
        "reason_code": "CONFIRMED_LINEUP_UNAVAILABLE",
        "base_article_hash": article_base_hash(base_article),
        "prediction_hash": stable_hash(prediction),
        "evidence_refs": [],
    }
    fields = _bundle(evidence).get("fields")
    field = fields.get("lineup_state") if isinstance(fields, Mapping) else None
    if not isinstance(field, Mapping) or (_text(field.get("state")) or "").upper() != "PRESENT":
        return omitted

    item = next(
        (
            candidate for candidate in evidence_envelope.get("items", [])
            if isinstance(candidate, Mapping)
            and candidate.get("evidence_id") == "football_evidence.lineup_state"
        ),
        None,
    )
    if not isinstance(item, Mapping) or item.get("status") != "VERIFIED":
        return {**omitted, "reason_code": "LINEUP_EVIDENCE_DEGRADED"}

    observed = _dt(field.get("observed_at"))
    kickoff = _dt(evidence_envelope.get("kickoff_at"))
    if observed is None or kickoff is None or observed > kickoff:
        return {**omitted, "reason_code": "LINEUP_AFTER_KICKOFF_OR_TIME_UNKNOWN"}

    value = field.get("value")
    if not isinstance(value, Mapping):
        return {**omitted, "reason_code": "LINEUP_VALUE_MISSING"}
    semantic = (
        _text(field.get("semantic_state"))
        or _text(value.get("confirmation_status"))
        or ""
    ).upper()
    if semantic not in {"CONFIRMED", "CONFIRMED_XI", "OFFICIAL_CONFIRMED"}:
        return {**omitted, "reason_code": "LINEUP_NOT_CONFIRMED"}

    target = _target(evidence, {})
    confirmed: dict[str, Any] = {}
    for side in ("home", "away"):
        normalized, error = _confirmed_side(value, side, target)
        if error:
            return {**omitted, "reason_code": error}
        confirmed[side] = normalized

    return {
        "contract_version": LATE_BRIEFING_CONTRACT_VERSION,
        "status": "AVAILABLE",
        "reason_code": None,
        "base_article_hash": omitted["base_article_hash"],
        "prediction_hash": omitted["prediction_hash"],
        "evidence_refs": ["football_evidence.lineup_state"],
        "observed_at": field.get("observed_at"),
        "as_of": field.get("observed_at"),
        "confirmed_xi": confirmed,
        "assumption_changes": [],
        "summary": "确认首发已补充；基础分析与正式预测保持冻结，不生成新的正式概率。",
    }


__all__ = [
    "EVIDENCE_ENVELOPE_VERSION",
    "LATE_BRIEFING_CONTRACT_VERSION",
    "article_base_hash",
    "bind_article_plan",
    "build_evidence_envelope",
    "build_late_briefing",
    "stable_hash",
]
