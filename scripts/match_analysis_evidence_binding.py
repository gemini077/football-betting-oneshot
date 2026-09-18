"""Evidence binding and independent late-prematch briefing for Match Detail."""

from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Mapping
from datetime import datetime
from typing import Any

EVIDENCE_ENVELOPE_VERSION = "match_analysis_evidence_envelope.v1"
LATE_BRIEFING_CONTRACT_VERSION = "match_analysis_late_briefing.v1"

_REQUIRED_FIELD_NAMES = (
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
_ABSENCE_STATUSES = {"OUT", "ABSENT", "INJURED", "SUSPENDED", "DOUBTFUL", "UNAVAILABLE"}
_RECOVERY_STATUSES = {"RECOVERED", "FIT", "AVAILABLE", "CLEARED", "RETURNED"}


def _text(value: Any) -> str | None:
    if value is None:
        return None
    result = str(value).strip()
    return result or None


def _parse_dt(value: Any) -> datetime | None:
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


def _article_cutoff(prediction: Mapping[str, Any]) -> str | None:
    for key in (
        "source_cutoff_at",
        "model_input_as_of_at",
        "prediction_created_at",
        "created_at",
    ):
        value = _text(prediction.get(key))
        if value:
            return value
    return None


def _bundle(football_evidence: Mapping[str, Any]) -> Mapping[str, Any]:
    value = football_evidence.get("prematch_evidence")
    return value if isinstance(value, Mapping) else {}


def _target_fixture(
    football_evidence: Mapping[str, Any],
    accepted_fixture: Mapping[str, Any],
) -> Mapping[str, Any]:
    target = _bundle(football_evidence).get("target_fixture")
    return target if isinstance(target, Mapping) else accepted_fixture


def _kickoff_at(
    prediction: Mapping[str, Any],
    football_evidence: Mapping[str, Any],
    accepted_fixture: Mapping[str, Any],
) -> str | None:
    target = _target_fixture(football_evidence, accepted_fixture)
    for value in (
        target.get("kickoff_at"),
        target.get("kickoff"),
        prediction.get("kickoff_at"),
        accepted_fixture.get("kickoff_at"),
        accepted_fixture.get("kickoff"),
    ):
        text = _text(value)
        if text:
            return text
    return None


def _subject_id(
    prediction: Mapping[str, Any],
    football_evidence: Mapping[str, Any],
    accepted_fixture: Mapping[str, Any],
) -> str:
    target = _target_fixture(football_evidence, accepted_fixture)
    for value in (
        target.get("provider_match_id"),
        target.get("source_fixture_id"),
        football_evidence.get("match_id"),
        accepted_fixture.get("match_id"),
        prediction.get("match_id"),
    ):
        text = _text(value)
        if text:
            return f"fixture:{text}"
    return "fixture:unknown"


def _record_time(record: Mapping[str, Any]) -> datetime | None:
    for key in ("as_of", "observed_at", "source_update_at", "updated_at"):
        parsed = _parse_dt(record.get(key))
        if parsed is not None:
            return parsed
    return None


def _availability_value(
    value: Any,
    *,
    target_fixture: Mapping[str, Any],
    cutoff: datetime | None,
) -> tuple[Any, dict[str, Any]]:
    records: list[Any] | None = None
    if isinstance(value, list):
        records = value
    elif isinstance(value, Mapping):
        for key in ("records", "items"):
            candidate = value.get(key)
            if isinstance(candidate, list):
                records = candidate
                break
    if records is None:
        return copy.deepcopy(value), {
            "records_seen": 0,
            "resolved_count": 0,
            "stale_count": 0,
            "binding_errors": [],
        }

    team_ids = {
        _text(target_fixture.get("home_team_id")),
        _text(target_fixture.get("away_team_id")),
    }
    team_ids.discard(None)
    latest: dict[tuple[str, str], tuple[datetime, dict[str, Any]]] = {}
    errors: list[str] = []
    future_count = 0

    for raw in records:
        if not isinstance(raw, Mapping):
            errors.append("NON_MAPPING_RECORD")
            continue
        player_id = _text(raw.get("player_id") or raw.get("id"))
        team_id = _text(raw.get("team_id"))
        observed = _record_time(raw)
        if not player_id or not team_id:
            errors.append("IDENTITY_MISSING")
            continue
        if team_ids and team_id not in team_ids:
            errors.append("TEAM_ID_MISMATCH")
            continue
        if cutoff is not None and observed is None:
            errors.append("TIMESTAMP_MISSING")
            continue
        if cutoff is not None and observed is not None and observed > cutoff:
            future_count += 1
            continue
        if observed is None:
            continue
        key = (team_id, player_id)
        previous = latest.get(key)
        if previous is None or observed > previous[0]:
            latest[key] = (observed, copy.deepcopy(dict(raw)))

    resolved: list[dict[str, Any]] = []
    current_absences: list[dict[str, Any]] = []
    stale_count = 0
    for (team_id, player_id), (_, record) in sorted(latest.items()):
        valid_until = _parse_dt(record.get("valid_until") or record.get("expires_at"))
        stale = bool(cutoff is not None and valid_until is not None and valid_until < cutoff)
        status = (_text(record.get("status")) or "").upper()
        current_absence = status in _ABSENCE_STATUSES and not stale
        if status in _RECOVERY_STATUSES:
            current_absence = False
        record.update(
            {
                "team_id": team_id,
                "player_id": player_id,
                "stale_at_cutoff": stale,
                "current_absence": current_absence,
            }
        )
        resolved.append(record)
        if stale:
            stale_count += 1
        if current_absence:
            current_absences.append(copy.deepcopy(record))

    normalized = copy.deepcopy(dict(value)) if isinstance(value, Mapping) else {}
    normalized["resolved_records"] = resolved
    normalized["current_absences"] = current_absences
    return normalized, {
        "records_seen": len(records),
        "resolved_count": len(resolved),
        "stale_count": stale_count,
        "future_count": future_count,
        "binding_errors": errors,
    }


def _field_status(
    field: Mapping[str, Any],
    *,
    availability_meta: Mapping[str, Any] | None = None,
) -> str:
    state = (_text(field.get("state")) or "").upper()
    freshness = (_text(field.get("freshness")) or "").upper()
    value = field.get("value")
    value_freshness = (
        (_text(value.get("freshness")) or "").upper()
        if isinstance(value, Mapping)
        else ""
    )
    if freshness == "STALE" or value_freshness == "STALE":
        return "STALE"
    if state == "PRESENT":
        meta = availability_meta or {}
        if meta.get("records_seen") and not meta.get("resolved_count") and meta.get("binding_errors"):
            return "DEGRADED"
        if (
            meta.get("resolved_count")
            and meta.get("stale_count") == meta.get("resolved_count")
        ):
            return "STALE"
        return "VERIFIED"
    if state == "ABSENT":
        return "MISSING"
    if state in {"NOT_COVERED", "UNSUPPORTED"}:
        return "NOT_COVERED"
    return "DEGRADED"


def _field_freshness(
    field: Mapping[str, Any],
    *,
    status: str,
    cutoff: datetime | None,
    kickoff: datetime | None,
) -> str:
    if status == "STALE":
        return "STALE"
    times = [
        parsed
        for parsed in (
            _parse_dt(field.get("observed_at")),
            _parse_dt(field.get("source_update_at")),
        )
        if parsed is not None
    ]
    if not times:
        return "UNKNOWN"
    latest = max(times)
    if kickoff is not None and latest > kickoff:
        return "AFTER_KICKOFF"
    if cutoff is not None and latest > cutoff:
        return "AFTER_CUTOFF"
    return "AT_OR_BEFORE_CUTOFF"


def _source_payload(
    football_evidence: Mapping[str, Any],
    field: Mapping[str, Any],
) -> dict[str, Any]:
    bundle = _bundle(football_evidence)
    source = bundle.get("source") if isinstance(bundle.get("source"), Mapping) else {}
    return {
        "provider": source.get("provider") or football_evidence.get("source_provider"),
        "surface": field.get("surface"),
        "source_surfaces": copy.deepcopy(field.get("source_surfaces") or []),
        "source_references": copy.deepcopy(source.get("source_references") or []),
    }


def _field_item(
    name: str,
    field: Mapping[str, Any],
    *,
    prediction: Mapping[str, Any],
    football_evidence: Mapping[str, Any],
    accepted_fixture: Mapping[str, Any],
    cutoff_text: str | None,
    kickoff_text: str | None,
) -> dict[str, Any]:
    cutoff = _parse_dt(cutoff_text)
    kickoff = _parse_dt(kickoff_text)
    target = _target_fixture(football_evidence, accepted_fixture)
    value = copy.deepcopy(field.get("value"))
    availability_meta: dict[str, Any] | None = None
    if name in _AVAILABILITY_FIELDS:
        value, availability_meta = _availability_value(
            value,
            target_fixture=target,
            cutoff=cutoff,
        )
    status = _field_status(field, availability_meta=availability_meta)
    freshness = _field_freshness(field, status=status, cutoff=cutoff, kickoff=kickoff)
    eligible = field.get("prematch_eligible") is True
    admissible = (
        status == "VERIFIED"
        and eligible
        and cutoff is not None
        and freshness == "AT_OR_BEFORE_CUTOFF"
    )
    return {
        "evidence_id": f"football_evidence.{name}",
        "subject_id": _subject_id(prediction, football_evidence, accepted_fixture),
        "type": name,
        "value": value,
        "source": _source_payload(football_evidence, field),
        "observed_at": field.get("observed_at"),
        "as_of": field.get("observed_at"),
        "freshness": freshness,
        "status": status,
        "admissible": admissible,
        "reason_code": field.get("reason_code"),
        "source_update_at": field.get("source_update_at"),
        "prematch_eligible": eligible,
        "availability_resolution": availability_meta,
    }


def _prediction_item(
    prediction: Mapping[str, Any],
    *,
    football_evidence: Mapping[str, Any],
    accepted_fixture: Mapping[str, Any],
    cutoff_text: str | None,
    kickoff_text: str | None,
) -> dict[str, Any]:
    cutoff = _parse_dt(cutoff_text)
    kickoff = _parse_dt(kickoff_text)
    status = "VERIFIED" if prediction and cutoff is not None else "DEGRADED"
    freshness = "UNKNOWN"
    if cutoff is not None:
        freshness = "AFTER_KICKOFF" if kickoff is not None and cutoff > kickoff else "AT_OR_BEFORE_CUTOFF"
        if freshness == "AFTER_KICKOFF":
            status = "DEGRADED"
    return {
        "evidence_id": "prediction_record.probabilities_and_score_cluster",
        "subject_id": _text(prediction.get("prediction_id"))
        or _subject_id(prediction, football_evidence, accepted_fixture),
        "type": "frozen_prediction",
        "value": {
            key: copy.deepcopy(prediction.get(key))
            for key in ("probabilities", "top_scores", "score_distribution", "totals", "btts")
            if key in prediction
        },
        "source": {"provider": "frozen_prediction_record"},
        "observed_at": cutoff_text,
        "as_of": cutoff_text,
        "freshness": freshness,
        "status": status,
        "admissible": status == "VERIFIED" and freshness == "AT_OR_BEFORE_CUTOFF",
        "reason_code": None,
        "source_update_at": cutoff_text,
        "prematch_eligible": True,
        "availability_resolution": None,
    }


def build_evidence_envelope(
    prediction: Mapping[str, Any] | None,
    football_evidence: Mapping[str, Any] | None,
    accepted_fixture: Mapping[str, Any] | None,
) -> dict[str, Any]:
    prediction = prediction if isinstance(prediction, Mapping) else {}
    football_evidence = football_evidence if isinstance(football_evidence, Mapping) else {}
    accepted_fixture = accepted_fixture if isinstance(accepted_fixture, Mapping) else {}
    cutoff_text = _article_cutoff(prediction)
    kickoff_text = _kickoff_at(prediction, football_evidence, accepted_fixture)
    bundle = _bundle(football_evidence)
    fields = bundle.get("fields") if isinstance(bundle.get("fields"), Mapping) else {}

    items: list[dict[str, Any]] = [
        _prediction_item(
            prediction,
            football_evidence=football_evidence,
            accepted_fixture=accepted_fixture,
            cutoff_text=cutoff_text,
            kickoff_text=kickoff_text,
        )
    ]
    names = list(dict.fromkeys([*fields.keys(), *_REQUIRED_FIELD_NAMES]))
    for name in names:
        field = fields.get(name)
        if not isinstance(field, Mapping):
            items.append(
                {
                    "evidence_id": f"football_evidence.{name}",
                    "subject_id": _subject_id(prediction, football_evidence, accepted_fixture),
                    "type": name,
                    "value": None,
                    "source": {"provider": football_evidence.get("source_provider")},
                    "observed_at": None,
                    "as_of": None,
                    "freshness": "UNKNOWN",
                    "status": "NOT_COVERED",
                    "admissible": False,
                    "reason_code": "FIELD_NOT_COVERED",
                    "source_update_at": None,
                    "prematch_eligible": False,
                    "availability_resolution": None,
                }
            )
            continue
        items.append(
            _field_item(
                name,
                field,
                prediction=prediction,
                football_evidence=football_evidence,
                accepted_fixture=accepted_fixture,
                cutoff_text=cutoff_text,
                kickoff_text=kickoff_text,
            )
        )

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
        if isinstance(item, Mapping) and _text(item.get("evidence_id"))
    }
    bound: list[dict[str, Any]] = []
    for raw in plan:
        if not isinstance(raw, Mapping):
            continue
        refs = raw.get("evidence_refs")
        if (
            not isinstance(refs, list)
            or not refs
            or any(
                not isinstance(ref, str)
                or ref not in lookup
                or lookup[ref].get("admissible") is not True
                for ref in refs
            )
        ):
            continue
        item = copy.deepcopy(dict(raw))
        item["order"] = len(bound) + 1
        bound.append(item)
    return bound


def _lineup_side(
    value: Mapping[str, Any],
    side: str,
    *,
    target_fixture: Mapping[str, Any],
) -> tuple[dict[str, Any] | None, str | None]:
    side_value = value.get(side)
    if not isinstance(side_value, Mapping):
        return None, "LINEUP_SIDE_MISSING"
    expected_team_id = _text(target_fixture.get(f"{side}_team_id"))
    team_id = _text(side_value.get("team_id"))
    if not expected_team_id or not team_id or team_id != expected_team_id:
        return None, "LINEUP_IDENTITY_MISMATCH"
    players = None
    for key in ("starting_xi", "players", "xi"):
        candidate = side_value.get(key)
        if isinstance(candidate, list):
            players = candidate
            break
    if not isinstance(players, list) or len(players) != 11:
        return None, "CONFIRMED_XI_INCOMPLETE"
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in players:
        if not isinstance(raw, Mapping):
            return None, "PLAYER_IDENTITY_MISSING"
        player_id = _text(raw.get("player_id") or raw.get("id"))
        if not player_id or player_id in seen:
            return None, "PLAYER_IDENTITY_MISSING"
        seen.add(player_id)
        normalized.append(
            {
                "player_id": player_id,
                "name": _text(raw.get("name")),
            }
        )
    return {"team_id": team_id, "players": normalized}, None


def build_late_briefing(
    base_article: Mapping[str, Any],
    prediction: Mapping[str, Any] | None,
    football_evidence: Mapping[str, Any] | None,
    evidence_envelope: Mapping[str, Any],
) -> dict[str, Any]:
    prediction = prediction if isinstance(prediction, Mapping) else {}
    football_evidence = football_evidence if isinstance(football_evidence, Mapping) else {}
    base_hash = article_base_hash(base_article)
    prediction_hash = stable_hash(prediction)
    omitted = {
        "contract_version": LATE_BRIEFING_CONTRACT_VERSION,
        "status": "OMITTED",
        "reason_code": "CONFIRMED_LINEUP_UNAVAILABLE",
        "base_article_hash": base_hash,
        "prediction_hash": prediction_hash,
        "evidence_refs": [],
    }

    bundle = _bundle(football_evidence)
    fields = bundle.get("fields") if isinstance(bundle.get("fields"), Mapping) else {}
    field = fields.get("lineup_state")
    if not isinstance(field, Mapping) or (_text(field.get("state")) or "").upper() != "PRESENT":
        return omitted

    item = next(
        (
            candidate
            for candidate in evidence_envelope.get("items", [])
            if isinstance(candidate, Mapping)
            and candidate.get("evidence_id") == "football_evidence.lineup_state"
        ),
        None,
    )
    if not isinstance(item, Mapping) or item.get("status") != "VERIFIED":
        return {**omitted, "reason_code": "LINEUP_EVIDENCE_DEGRADED"}

    kickoff = _parse_dt(evidence_envelope.get("kickoff_at"))
    observed = _parse_dt(field.get("observed_at"))
    if kickoff is None or observed is None or observed > kickoff:
        return {**omitted, "reason_code": "LINEUP_AFTER_KICKOFF_OR_TIME_UNKNOWN"}

    value = field.get("value")
    if not isinstance(value, Mapping):
        return {**omitted, "reason_code": "LINEUP_VALUE_MISSING"}
    semantic = (
        _text(field.get("semantic_state"))
        or _text(value.get("confirmation_status"))
        or _text(value.get("status"))
        or ""
    ).upper()
    if semantic not in {"CONFIRMED", "CONFIRMED_XI", "OFFICIAL_CONFIRMED"}:
        return {**omitted, "reason_code": "LINEUP_NOT_CONFIRMED"}

    target = _target_fixture(football_evidence, {})
    confirmed_xi: dict[str, Any] = {}
    for side in ("home", "away"):
        normalized, error = _lineup_side(value, side, target_fixture=target)
        if error:
            return {**omitted, "reason_code": error}
        confirmed_xi[side] = normalized

    return {
        "contract_version": LATE_BRIEFING_CONTRACT_VERSION,
        "status": "AVAILABLE",
        "reason_code": None,
        "base_article_hash": base_hash,
        "prediction_hash": prediction_hash,
        "evidence_refs": ["football_evidence.lineup_state"],
        "observed_at": field.get("observed_at"),
        "as_of": field.get("observed_at"),
        "confirmed_xi": confirmed_xi,
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
