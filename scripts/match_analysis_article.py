"""Build a deterministic connected Match Detail article from accepted evidence."""

from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Mapping
from typing import Any, TypedDict

try:  # Keep direct script imports and package imports working.
    from .match_analysis_evidence_projection import (
        OUTCOMES,
        SIDES,
        _first,
        _number,
        _parse_datetime,
        _round,
        _text,
        project_match_analysis_evidence,
    )
except ImportError:  # pragma: no cover - direct CLI compatibility.
    from match_analysis_evidence_projection import (
        OUTCOMES,
        SIDES,
        _first,
        _number,
        _parse_datetime,
        _round,
        _text,
        project_match_analysis_evidence,
    )


CONTRACT_VERSION = "match_analysis_article.v2"
EVIDENCE_ENVELOPE_VERSION = "match_analysis_evidence_envelope.v1"
LATE_BRIEFING_CONTRACT_VERSION = "match_analysis_late_briefing.v1"
PROCESS_METRICS = ("shots_faced", "corners", "possession")
_EVIDENCE_STATUSES = {"VERIFIED", "MISSING", "STALE", "DEGRADED", "NOT_COVERED"}
_PREMATCH_EVIDENCE_FIELDS = (
    "recent_form",
    "recent_process_context",
    "future_schedule_rest",
    "market_context",
    "lineup_state",
    "injuries",
    "suspensions",
    "availability_summary",
    "coach",
    "referee",
    "h2h",
    "competition_standings_stage",
    "standings_context",
    "technical_stats",
    "panlu",
)
OUTCOME_LABELS = {"home": "主胜", "draw": "平局", "away": "客胜"}
SIDE_LABELS = {"home": "主队", "away": "客队"}


class ArticlePlanItem(TypedDict):
    role: str
    subject: str
    direction: str
    strength: str
    evidence_refs: list[str]
    order: int
    text: str


ArticlePlan = list[ArticlePlanItem]

_ARTICLE_PLAN_ROLES = {"thesis", "recent_process", "counterevidence", "evidence_conflict", "market", "forecast"}
_ARTICLE_PLAN_DIRECTIONS = set(OUTCOMES) | {"mixed", "neutral"}
_ARTICLE_PLAN_STRENGTHS = {"strong", "moderate", "weak"}


def _stable_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _iso_datetime(value: Any) -> str | None:
    parsed = _parse_datetime(value)
    return parsed.isoformat() if parsed else None


def _latest_datetime(*values: Any) -> tuple[Any, str | None]:
    candidates = []
    for value in values:
        parsed = _parse_datetime(value)
        if parsed:
            candidates.append((parsed, parsed.isoformat()))
    return max(candidates, key=lambda item: item[0]) if candidates else (None, None)


def _article_temporal_context(
    prediction: Mapping[str, Any],
    input_snapshot: Mapping[str, Any],
    football_evidence: Mapping[str, Any],
    accepted_fixture: Mapping[str, Any],
) -> tuple[str | None, str | None]:
    source = football_evidence.get("source") if isinstance(football_evidence.get("source"), Mapping) else {}
    nested_input = input_snapshot.get("input") if isinstance(input_snapshot.get("input"), Mapping) else {}
    cutoff = None
    for mapping in (prediction, source, football_evidence, input_snapshot, nested_input):
        for key in ("freeze_created_at", "prediction_frozen_at", "frozen_at", "source_cutoff_at", "captured_at", "prediction_created_at"):
            candidate = mapping.get(key) if isinstance(mapping, Mapping) else None
            if _parse_datetime(candidate):
                cutoff = candidate
                break
        if cutoff:
            break
    kickoff = _first(prediction, "kickoff_at", "kickoff", "match_datetime")
    kickoff = kickoff or _first(accepted_fixture, "kickoff_at", "kickoff", "matchDate")
    return _iso_datetime(cutoff), _iso_datetime(kickoff)


def _subject_id(
    prediction: Mapping[str, Any],
    football_evidence: Mapping[str, Any],
    accepted_fixture: Mapping[str, Any],
    projection: Mapping[str, Any],
) -> str:
    identity = projection.get("identity") if isinstance(projection.get("identity"), Mapping) else {}
    target = football_evidence.get("state_memory", {}).get("target_fixture") if isinstance(football_evidence.get("state_memory"), Mapping) else {}
    for value in (
        identity.get("provider_match_id"),
        _first(target, "source_fixture_id", "provider_match_id", "match_id"),
        _first(accepted_fixture, "nowscoreId", "matchId", "match_id"),
        _first(prediction, "match_id", "match_key"),
    ):
        text = _text(value)
        if text:
            return f"match:{text}"
    return "match:unresolved"


def _field_source(field: Mapping[str, Any], provider: Any = "nowscore") -> str:
    surface = _text(field.get("surface")) or _text(field.get("source"))
    return f"{provider}:{surface}" if surface else str(provider)


def _field_as_of(field: Mapping[str, Any], source: Mapping[str, Any]) -> str | None:
    _, latest = _latest_datetime(
        field.get("as_of"),
        field.get("source_update_at"),
        field.get("observed_at"),
        source.get("source_update_at"),
        source.get("observed_at"),
    )
    return latest


def _field_status(
    field: Mapping[str, Any] | None,
    *,
    cutoff_at: str | None,
    kickoff_at: str | None,
) -> tuple[str, bool, str]:
    if not isinstance(field, Mapping):
        return "NOT_COVERED", False, "FIELD_NOT_COVERED"
    explicit = _text(field.get("status") or field.get("freshness"))
    explicit = explicit.upper() if explicit else None
    state = (_text(field.get("state")) or "").upper()
    if explicit in _EVIDENCE_STATUSES and explicit != "VERIFIED":
        return explicit, False, f"EXPLICIT_{explicit}"
    if state in {"ABSENT", "SECTION_PRESENT_EMPTY"}:
        return "MISSING", False, state
    if state in {"ACCESS_GATED", "PARSE_UNCERTAIN", "CONFLICT"}:
        return "DEGRADED", False, "DEGRADED_EVIDENCE"
    if state not in {"PRESENT", ""} and explicit != "VERIFIED":
        return "NOT_COVERED", False, "UNKNOWN_FIELD_STATE"
    if field.get("value") is None:
        return "MISSING", False, "VALUE_MISSING"
    if (_text(field.get("semantic_state")) or "").upper() == "UNLABELLED":
        return "DEGRADED", False, "SEMANTICS_UNLABELLED"
    observed = _parse_datetime(field.get("observed_at"))
    source_update = _parse_datetime(field.get("source_update_at"))
    cutoff = _parse_datetime(cutoff_at)
    kickoff = _parse_datetime(kickoff_at)
    for timestamp, reason in ((observed, "OBSERVED_AFTER_CUTOFF"), (source_update, "SOURCE_UPDATED_AFTER_CUTOFF")):
        if timestamp and cutoff and timestamp > cutoff:
            return "STALE", False, reason
        if timestamp and kickoff and timestamp >= kickoff:
            return "STALE", False, "POST_KICKOFF_EVIDENCE"
    if field.get("prematch_eligible") is False:
        return "STALE", False, "PREMATCH_INELIGIBLE"
    value = field.get("value")
    rows = []
    if isinstance(value, Mapping):
        for key in ("records", "items", "players"):
            if isinstance(value.get(key), list):
                rows.extend(row for row in value[key] if isinstance(row, Mapping))
                break
    for row in rows:
        row_freshness = (_text(row.get("freshness")) or "").upper()
        if row_freshness in {"STALE", "DEGRADED"}:
            return "STALE" if row_freshness == "STALE" else "DEGRADED", False, f"ROW_{row_freshness}"
        timestamp = _parse_datetime(_first(row, "as_of", "observed_at", "source_update_at"))
        if timestamp and cutoff and timestamp > cutoff:
            return "STALE", False, "ROW_AFTER_CUTOFF"
        if timestamp and kickoff and timestamp >= kickoff:
            return "STALE", False, "ROW_POST_KICKOFF"
    if field.get("prematch_eligible") is None and not (observed or source_update):
        return "DEGRADED", False, "TEMPORAL_METADATA_MISSING"
    return "VERIFIED", True, "ADMISSIBLE_PREMATCH_EVIDENCE"


def _envelope_item(
    evidence_id: str,
    subject_id: str,
    evidence_type: str,
    field: Mapping[str, Any] | None,
    *,
    source: Mapping[str, Any],
    cutoff_at: str | None,
    kickoff_at: str | None,
    fallback_value: Any = None,
    fallback_source: str | None = None,
) -> dict[str, Any]:
    status, admissible, reason = _field_status(field, cutoff_at=cutoff_at, kickoff_at=kickoff_at)
    value = field.get("value") if isinstance(field, Mapping) else fallback_value
    if field is None and fallback_value is not None:
        status, admissible, reason = "VERIFIED", True, "PROJECTED_PREMATCH_EVIDENCE"
    as_of = _field_as_of(field or {}, source)
    if status == "VERIFIED" and as_of is None and fallback_value is None:
        status, admissible, reason = "DEGRADED", False, "TEMPORAL_METADATA_MISSING"
    if status != "VERIFIED":
        value = None
    if as_of is None and fallback_value is not None:
        as_of = cutoff_at
    freshness = {
        "VERIFIED": "fresh",
        "STALE": "stale",
        "DEGRADED": "degraded",
        "MISSING": "missing",
        "NOT_COVERED": "not_covered",
    }[status]
    return {
        "evidence_id": evidence_id,
        "subject_id": subject_id,
        "type": evidence_type,
        "value": copy.deepcopy(value),
        "source": fallback_source or _field_source(field or {}, source.get("provider") or "nowscore"),
        "observed_at": _text((field or {}).get("observed_at")) or _text(source.get("observed_at")),
        "as_of": as_of,
        "freshness": freshness,
        "status": status,
        "admissible": admissible,
        "reason": reason,
    }


def _prediction_envelope_item(
    prediction: Mapping[str, Any],
    *,
    subject_id: str,
    cutoff_at: str | None,
    kickoff_at: str | None,
) -> dict[str, Any]:
    probabilities = prediction.get("probabilities")
    if not isinstance(probabilities, Mapping):
        output = prediction.get("prediction_output")
        probabilities = output.get("probabilities") if isinstance(output, Mapping) else None
    valid = isinstance(probabilities, Mapping) and all(
        _number(probabilities.get(outcome)) is not None for outcome in OUTCOMES
    )
    prediction_field = {
        "state": "PRESENT" if valid else "ABSENT",
        "value": {
            "probabilities": copy.deepcopy(probabilities),
            "top_scores": copy.deepcopy(prediction.get("top_scores") or []),
        } if valid else None,
        "observed_at": _first(prediction, "freeze_created_at", "prediction_frozen_at", "prediction_created_at"),
        "source_update_at": None,
        "prematch_eligible": True if valid else False,
    }
    item = _envelope_item(
        "prediction_record.probabilities_and_score_cluster",
        subject_id,
        "frozen_prediction",
        prediction_field,
        source={"provider": "prediction_record"},
        cutoff_at=cutoff_at,
        kickoff_at=kickoff_at,
        fallback_source="prediction_record",
    )
    item["prediction_id"] = _text(prediction.get("prediction_id"))
    item["prediction_sha256"] = _text(prediction.get("prediction_sha256"))
    return item


def _recent_state_fallback_field(
    football_evidence: Mapping[str, Any],
    value: Any,
    cutoff_at: str | None,
    kickoff_at: str | None,
) -> dict[str, Any] | None:
    state_memory = football_evidence.get("state_memory")
    history = state_memory.get("history") if isinstance(state_memory, Mapping) else None
    if not isinstance(history, Mapping) or not isinstance(value, Mapping):
        return None
    timestamps = []
    for side in SIDES:
        rows = history.get(f"{side}_team")
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            timestamp = _parse_datetime(_first(row, "source_cutoff_at", "source_update_at", "captured_at"))
            if not timestamp:
                return None
            cutoff = _parse_datetime(cutoff_at)
            kickoff = _parse_datetime(kickoff_at)
            if (cutoff and timestamp > cutoff) or (kickoff and timestamp >= kickoff):
                return None
            timestamps.append(timestamp)
    if not timestamps:
        return None
    return {
        "state": "PRESENT",
        "value": value,
        "surface": "state_memory",
        "observed_at": max(timestamps).isoformat(timespec="seconds"),
        "source_update_at": None,
        "prematch_eligible": True,
    }


def _current_availability_value(value: Any) -> Any:
    if not isinstance(value, Mapping):
        return value
    for key in ("records", "items", "players"):
        rows = value.get(key)
        if not isinstance(rows, list):
            continue
        latest: dict[str, tuple[Any, int, Mapping[str, Any]]] = {}
        for index, row in enumerate(rows):
            if not isinstance(row, Mapping):
                continue
            subject = _text(_first(row, "player_id", "canonical_player_id", "player_name", "name"))
            if not subject:
                continue
            timestamp = _parse_datetime(_first(row, "as_of", "observed_at", "source_update_at"))
            key_value = subject.casefold()
            previous = latest.get(key_value)
            if previous is None or (timestamp or _parse_datetime("1970-01-01"), index) >= (previous[0] or _parse_datetime("1970-01-01"), previous[1]):
                latest[key_value] = (timestamp, index, row)
        if not latest:
            return value
        current_rows = [row for _, _, row in sorted(latest.values(), key=lambda item: item[1])]
        return {**value, key: copy.deepcopy(current_rows)}
    return value


def build_evidence_envelope(
    prediction: Mapping[str, Any] | None,
    input_snapshot: Mapping[str, Any] | None,
    football_evidence: Mapping[str, Any] | None,
    accepted_fixture: Mapping[str, Any] | None,
    *,
    projection: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Bind article references to admissible, immutable prematch evidence."""

    prediction = prediction if isinstance(prediction, Mapping) else {}
    input_snapshot = input_snapshot if isinstance(input_snapshot, Mapping) else {}
    football_evidence = football_evidence if isinstance(football_evidence, Mapping) else {}
    accepted_fixture = accepted_fixture if isinstance(accepted_fixture, Mapping) else {}
    projection = projection if isinstance(projection, Mapping) else {}
    source = football_evidence.get("source") if isinstance(football_evidence.get("source"), Mapping) else {}
    fields = football_evidence.get("prematch_evidence", {}).get("fields") if isinstance(football_evidence.get("prematch_evidence"), Mapping) else {}
    fields = fields if isinstance(fields, Mapping) else {}
    cutoff_at, kickoff_at = _article_temporal_context(prediction, input_snapshot, football_evidence, accepted_fixture)
    subject_id = _subject_id(prediction, football_evidence, accepted_fixture, projection)
    items = [_prediction_envelope_item(prediction, subject_id=subject_id, cutoff_at=cutoff_at, kickoff_at=kickoff_at)]
    for field_name in _PREMATCH_EVIDENCE_FIELDS:
        fallback = None
        field = fields.get(field_name)
        if field_name == "recent_form" and not isinstance(field, Mapping):
            coverage = projection.get("coverage", {}).get("atoms", {}).get("recent_state") if isinstance(projection.get("coverage"), Mapping) else {}
            recent_state = projection.get("recent_state")
            if isinstance(coverage, Mapping) and coverage.get("status") == "AVAILABLE" and isinstance(recent_state, Mapping):
                field = _recent_state_fallback_field(football_evidence, recent_state, cutoff_at, kickoff_at)
                fallback = recent_state if field is not None else None
        if isinstance(field, Mapping) and field_name in {"injuries", "suspensions", "availability_summary"} and field.get("state") == "PRESENT":
            field = {**field, "value": _current_availability_value(field.get("value"))}
        items.append(
            _envelope_item(
                f"football_evidence.{field_name}",
                subject_id,
                field_name,
                field if isinstance(field, Mapping) else None,
                source=source,
                cutoff_at=cutoff_at,
                kickoff_at=kickoff_at,
                fallback_value=fallback,
                fallback_source="state_memory" if fallback is not None else None,
            )
        )
    return {
        "contract_version": EVIDENCE_ENVELOPE_VERSION,
        "subject_id": subject_id,
        "article_cutoff": cutoff_at,
        "article_cutoff_at": cutoff_at,
        "kickoff_at": kickoff_at,
        "items": items,
    }


def _envelope_by_id(envelope: Mapping[str, Any] | None) -> dict[str, Mapping[str, Any]]:
    items = envelope.get("items") if isinstance(envelope, Mapping) else None
    return {
        str(item.get("evidence_id")): item
        for item in items or []
        if isinstance(item, Mapping) and _text(item.get("evidence_id"))
    }


def _bind_article_plan(plan: ArticlePlan, envelope: Mapping[str, Any]) -> ArticlePlan:
    by_id = _envelope_by_id(envelope)
    bound: ArticlePlan = []
    for item in plan:
        refs = item.get("evidence_refs") or []
        if not refs or any(not isinstance(ref, str) or not by_id.get(ref, {}).get("admissible") for ref in refs):
            continue
        bound_item = copy.deepcopy(item)
        bound_item["order"] = len(bound) + 1
        bound.append(bound_item)
    return bound


def render_article_plan(plan: Any, evidence_envelope: Mapping[str, Any] | None = None) -> ArticlePlan:
    """Validate and normalize the article plan at the article-to-HTML boundary."""

    if not isinstance(plan, list) or not all(isinstance(item, Mapping) for item in plan):
        return []
    envelope_by_id = _envelope_by_id(evidence_envelope) if evidence_envelope is not None else None
    rendered: ArticlePlan = []
    for item in sorted(plan, key=lambda value: value.get("order", 0)):
        role = _text(item.get("role"))
        subject = _text(item.get("subject"))
        direction = _text(item.get("direction"))
        strength = _text(item.get("strength"))
        text = _text(item.get("text"))
        refs = item.get("evidence_refs")
        order = item.get("order")
        if (
            role not in _ARTICLE_PLAN_ROLES
            or not subject
            or direction not in _ARTICLE_PLAN_DIRECTIONS
            or strength not in _ARTICLE_PLAN_STRENGTHS
            or not text
            or not isinstance(refs, list)
            or not refs
            or not all(isinstance(ref, str) and ref.strip() for ref in refs)
            or not isinstance(order, int)
            or order != len(rendered) + 1
            or envelope_by_id is not None
            and any(not envelope_by_id.get(ref, {}).get("admissible") for ref in refs)
        ):
            return []
        if role in {"thesis", "recent_process"} and direction in SIDES and subject not in text:
            return []
        if role == "recent_process" and direction == "mixed" and "\u8fc7\u7a0b\u65b9\u5411\u504f\u5411" in text:
            return []
        rendered.append(
            {
                "role": role,
                "subject": subject,
                "direction": direction,
                "strength": strength,
                "evidence_refs": list(refs),
                "order": order,
                "text": text,
            }
        )
    return rendered


def _accepted_field(evidence: Mapping[str, Any], name: str) -> Any:
    bundle = evidence.get("prematch_evidence")
    fields = bundle.get("fields") if isinstance(bundle, Mapping) else None
    field = fields.get(name) if isinstance(fields, Mapping) else None
    if (
        not isinstance(field, Mapping)
        or (_text(field.get("state")) or "").upper() != "PRESENT"
        or field.get("prematch_eligible") is not True
    ):
        return None
    return field.get("value")


def _stats_from_summary(value: Any) -> dict[str, dict[str, Any]]:
    summary = value.get("summary") if isinstance(value, Mapping) else None
    if not isinstance(summary, Mapping):
        return {}
    result: dict[str, dict[str, Any]] = {}
    for side, key in (("home", "home_home"), ("away", "away_away")):
        row = summary.get(key)
        if not isinstance(row, Mapping):
            continue
        sample = _number(row.get("matches"))
        values = {
            "status": "AVAILABLE",
            "sample_size": int(sample) if sample is not None and sample.is_integer() else sample,
            "wdl": {
                "wins": row.get("wins"),
                "draws": row.get("draws"),
                "losses": row.get("losses"),
            },
            "goals_for": row.get("goals_for"),
            "goals_against": row.get("goals_against"),
        }
        if sample and sample > 0:
            values.update(
                {
                    "scored_rate": _round(_number(row.get("goals_for")) / sample) if _number(row.get("goals_for")) is not None else None,
                    "conceded_rate": _round(_number(row.get("goals_against")) / sample) if _number(row.get("goals_against")) is not None else None,
                }
            )
        result[side] = values
    return result


def _recent_state(projection: Mapping[str, Any], evidence: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    current = projection.get("recent_state")
    if isinstance(current, Mapping) and all(
        isinstance(current.get(side), Mapping)
        and isinstance(current[side].get("windows"), Mapping)
        and isinstance(current[side]["windows"].get("last5"), Mapping)
        for side in SIDES
    ):
        return {side: current[side] for side in SIDES}
    return _stats_from_summary(_accepted_field(evidence, "recent_form"))


def _last5(stats: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(stats, Mapping):
        return {}
    windows = stats.get("windows")
    value = windows.get("last5") if isinstance(windows, Mapping) else None
    return value if isinstance(value, Mapping) else stats


def _result_direction(recent: Mapping[str, Any]) -> str | None:
    values: dict[str, float] = {}
    for side in SIDES:
        stats = _last5(recent.get(side))
        wdl = stats.get("wdl") if isinstance(stats, Mapping) else None
        if not isinstance(wdl, Mapping):
            return None
        wins, losses = _number(wdl.get("wins")), _number(wdl.get("losses"))
        if wins is None or losses is None:
            return None
        values[side] = wins - losses
    if values["home"] == values["away"]:
        return "draw"
    return "home" if values["home"] > values["away"] else "away"


def _process_projection(evidence: Mapping[str, Any]) -> dict[str, Any] | None:
    value = _accepted_field(evidence, "recent_process_context")
    if not isinstance(value, Mapping):
        return None
    raw_metrics = value.get("metrics")
    metrics = [metric for metric in PROCESS_METRICS if isinstance(raw_metrics, list) and metric in raw_metrics]
    teams = value.get("teams")
    if not metrics or not isinstance(teams, Mapping):
        return None
    projected: dict[str, Any] = {"metrics": metrics, "teams": {}}
    for side in SIDES:
        source = teams.get(side)
        if not isinstance(source, Mapping):
            return None
        side_values: dict[str, Any] = {}
        for metric in metrics:
            row = source.get(metric)
            if not isinstance(row, Mapping):
                continue
            near3, near10 = _number(row.get("near3")), _number(row.get("near10"))
            if near3 is None and near10 is None:
                continue
            side_values[metric] = {
                "near3": _round(near3),
                "near10": _round(near10),
                "unit": _text(row.get("unit")) or None,
            }
        projected["teams"][side] = side_values
    if not all(projected["teams"].get(side) for side in SIDES):
        return None
    cross_checks: dict[str, Any] = {}
    source_cross_checks = value.get("source_cross_checks")
    if isinstance(source_cross_checks, Mapping):
        for name in ("goals", "goals_conceded"):
            source = source_cross_checks.get(name)
            if not isinstance(source, Mapping):
                continue
            rows: dict[str, Any] = {}
            for side in SIDES:
                row = source.get(side)
                if not isinstance(row, Mapping):
                    continue
                near3, near10 = _number(row.get("near3")), _number(row.get("near10"))
                if near3 is not None or near10 is not None:
                    rows[side] = {"near3": _round(near3), "near10": _round(near10)}
            if len(rows) == 2:
                cross_checks[name] = rows
    if cross_checks:
        projected["goal_cross_checks"] = cross_checks
    return projected


def _process_direction(process: Mapping[str, Any] | None) -> tuple[str | None, list[dict[str, Any]]]:
    if not isinstance(process, Mapping):
        return None, []
    teams = process.get("teams")
    if not isinstance(teams, Mapping):
        return None, []
    votes: list[dict[str, Any]] = []

    def compare(metric: str, *, higher_is_home: bool) -> None:
        home = teams.get("home", {}).get(metric, {}) if isinstance(teams.get("home"), Mapping) else {}
        away = teams.get("away", {}).get(metric, {}) if isinstance(teams.get("away"), Mapping) else {}
        home_value = _number(_first(home, "near3", "near10"))
        away_value = _number(_first(away, "near3", "near10"))
        if home_value is None or away_value is None or abs(home_value - away_value) < 0.1:
            return
        home_preferred = home_value > away_value if higher_is_home else home_value < away_value
        votes.append({"signal": metric, "direction": "home" if home_preferred else "away"})

    compare("shots_faced", higher_is_home=False)
    compare("corners", higher_is_home=True)
    compare("possession", higher_is_home=True)
    cross_checks = process.get("goal_cross_checks")
    if isinstance(cross_checks, Mapping):
        goals = cross_checks.get("goals") or {}
        conceded = cross_checks.get("goals_conceded") or {}
        home_goals = _number((goals.get("home") or {}).get("near3")) if isinstance(goals.get("home"), Mapping) else None
        away_goals = _number((goals.get("away") or {}).get("near3")) if isinstance(goals.get("away"), Mapping) else None
        home_conceded = _number((conceded.get("home") or {}).get("near3")) if isinstance(conceded.get("home"), Mapping) else None
        away_conceded = _number((conceded.get("away") or {}).get("near3")) if isinstance(conceded.get("away"), Mapping) else None
        if None not in (home_goals, away_goals, home_conceded, away_conceded):
            home_net, away_net = home_goals - home_conceded, away_goals - away_conceded
            if abs(home_net - away_net) >= 0.1:
                votes.append({"signal": "recent_goal_balance", "direction": "home" if home_net > away_net else "away"})
    counts = {side: sum(vote["direction"] == side for vote in votes) for side in SIDES}
    if not votes or counts["home"] == counts["away"]:
        return None, votes
    direction = "home" if counts["home"] > counts["away"] else "away"
    return direction, votes


def _alignment(result_direction: str | None, process_direction: str | None) -> str:
    if result_direction and process_direction and result_direction == process_direction:
        return "supportive"
    if result_direction and process_direction and result_direction != process_direction and result_direction != "draw":
        return "contradictory"
    return "mixed"


def _goal_shape(recent: Mapping[str, Any], process: Mapping[str, Any] | None) -> dict[str, Any]:
    scoring: dict[str, Any] = {}
    conceding: dict[str, Any] = {}
    btts: dict[str, Any] = {}
    clean_sheet: dict[str, Any] = {}
    over25: dict[str, Any] = {}
    over35: dict[str, Any] = {}
    for side in SIDES:
        stats = _last5(recent.get(side))
        sample = _number(stats.get("sample_size")) if isinstance(stats, Mapping) else None
        gf = _number(stats.get("goals_for")) if isinstance(stats, Mapping) else None
        ga = _number(stats.get("goals_against")) if isinstance(stats, Mapping) else None
        if sample is None or sample <= 0 or gf is None or ga is None:
            continue
        scoring[side] = {"average": _round(gf / sample), "scored_rate": _round(_number(stats.get("scored_rate")))}
        conceding[side] = {"average": _round(ga / sample), "conceded_rate": _round(_number(stats.get("conceded_rate")))}
        btts[side] = _round(_number(stats.get("btts_rate")))
        clean_sheet[side] = _round(_number(stats.get("clean_sheet_rate")))
        over25[side] = _round(_number(stats.get("over_2_5_rate")))
        over35[side] = _round(_number(stats.get("over_3_5_rate")))
    result: dict[str, Any] = {
        "status": "AVAILABLE" if len(scoring) == 2 else "OMITTED",
        "scoring": scoring,
        "conceding": conceding,
        "btts_rate": btts,
        "clean_sheet_rate": clean_sheet,
        "high_total_rate": {"over_2_5": over25, "over_3_5": over35},
    }
    if isinstance(process, Mapping) and isinstance(process.get("goal_cross_checks"), Mapping):
        result["near3_goal_cross_checks"] = process["goal_cross_checks"]
    return result


def _outlier_concentration(recent: Mapping[str, Any]) -> dict[str, Any]:
    candidates: list[dict[str, Any]] = []
    for side in SIDES:
        side_projection = recent.get(side)
        rows = side_projection.get("sequence", [])[:5] if isinstance(side_projection, Mapping) else []
        if not isinstance(rows, list):
            continue
        for dimension, value_key in (("goals_for", "subject_score_90m"), ("goals_against", "opponent_score_90m")):
            values = [_number(row.get(value_key)) for row in rows if isinstance(row, Mapping)]
            values = [value for value in values if value is not None and value >= 0]
            if len(values) < 5:
                continue
            maximum = max(values)
            if values.count(maximum) != 1 or maximum < 4:
                continue
            total = sum(values)
            share = maximum / total if total else 0.0
            remainder_average = (total - maximum) / (len(values) - 1)
            if share < 0.5 and maximum < remainder_average * 2 + 1:
                continue
            row = next(row for row in rows if isinstance(row, Mapping) and _number(row.get(value_key)) == maximum)
            candidates.append(
                {
                    "status": "PRESENT",
                    "side": side,
                    "dimension": dimension,
                    "value": int(maximum) if maximum.is_integer() else maximum,
                    "share": _round(share),
                    "window_total": int(total) if total.is_integer() else _round(total),
                    "match_date": _text(row.get("match_date")) or None,
                    "discount_raw_totals": True,
                }
            )
    if not candidates:
        return {"status": "NONE", "discount_raw_totals": False}
    return sorted(candidates, key=lambda item: (-float(item["share"]), item["side"], item["dimension"]))[0]


def _future_schedule_rest(evidence: Mapping[str, Any]) -> dict[str, Any]:
    value = _accepted_field(evidence, "future_schedule_rest")
    fixtures = value.get("fixtures") if isinstance(value, Mapping) else None
    if not isinstance(fixtures, list):
        return {"status": "OMITTED", "home": {}, "away": {}}
    grouped: dict[str, list[dict[str, Any]]] = {side: [] for side in SIDES}
    for fixture in fixtures:
        if not isinstance(fixture, Mapping):
            continue
        side = _text(fixture.get("target_orientation"))
        interval = _number(fixture.get("interval_days"))
        if side not in SIDES or interval is None or interval < 0:
            continue
        grouped[side].append(
            {
                "date": _text(fixture.get("date")) or None,
                "interval_days": int(interval) if interval.is_integer() else _round(interval),
            }
        )
    result: dict[str, Any] = {"status": "AVAILABLE" if any(grouped.values()) else "OMITTED"}
    for side in SIDES:
        rows = sorted(grouped[side], key=lambda row: (row["date"] or "9999-99-99", row["interval_days"]))
        result[side] = {
            "fixture_count": len(rows),
            "next_fixture_date": rows[0]["date"] if rows else None,
            "next_interval_days": rows[0]["interval_days"] if rows else None,
            "short_rest": bool(rows and rows[0]["interval_days"] <= 5),
        }
    return result


def _preferred(probabilities: Mapping[str, Any] | None) -> str | None:
    values = {outcome: _number(probabilities.get(outcome)) for outcome in OUTCOMES} if isinstance(probabilities, Mapping) else {}
    if any(value is None for value in values.values()):
        return None
    return max(OUTCOMES, key=lambda outcome: (values[outcome], -OUTCOMES.index(outcome)))


def _scores(prediction: Mapping[str, Any]) -> list[dict[str, Any]]:
    values = prediction.get("top_scores")
    if not isinstance(values, list):
        values = prediction.get("score_distribution")
    result: list[dict[str, Any]] = []
    for item in values if isinstance(values, list) else []:
        if isinstance(item, Mapping):
            score = _text(item.get("score") or item.get("value"))
            probability = _number(item.get("probability"))
        else:
            score, probability = _text(item), None
        if score:
            result.append({"score": score, "probability": _round(probability)})
    return result[:5]


def _score_concentration(scores: list[dict[str, Any]]) -> dict[str, Any]:
    probabilities = [_number(item.get("probability")) for item in scores]
    probabilities = [value for value in probabilities if value is not None]
    top1 = probabilities[0] if probabilities else None
    top2 = probabilities[1] if len(probabilities) > 1 else None
    gap = top1 - top2 if top1 is not None and top2 is not None else None
    if top1 is None:
        level = "LOW"
    elif top1 >= 0.085 and gap is not None and gap >= 0.01:
        level = "HIGH"
    elif top1 >= 0.075 and gap is not None and gap >= 0.004:
        level = "MEDIUM"
    else:
        level = "LOW"
    return {
        "level": level,
        "top1_probability": _round(top1),
        "top1_gap_points": _round(gap * 100 if gap is not None else None),
    }


def _identifiability(
    result_process_alignment: str,
    market_relationship: str,
    concentration: Mapping[str, Any],
    *,
    recent_available: bool,
    process_available: bool,
) -> str:
    evidence_score = {
        "supportive": 2,
        "mixed": 1,
        "contradictory": 0,
    }.get(result_process_alignment, 0) + {
        "aligned": 2,
        "neutral": 1,
        "conflicting": 0,
    }.get(market_relationship, 0)
    level = (_text(concentration.get("level")) or "").upper()
    if level == "LOW" or not recent_available:
        return "LOW"
    if evidence_score >= 3 and level == "HIGH" and process_available:
        return "HIGH"
    if evidence_score >= 2 and level in {"HIGH", "MEDIUM"}:
        return "MEDIUM"
    return "LOW"


def _format_number(value: Any) -> str:
    number = _number(value)
    if number is None:
        return "未知"
    return str(int(number)) if number.is_integer() else f"{number:.1f}"


def _format_percent(value: Any) -> str:
    number = _number(value)
    return "未知" if number is None else f"{number * 100:.0f}%"


def _team_name(identity: Mapping[str, Any], side: str) -> str:
    return _text(identity.get(side)) or SIDE_LABELS[side]


def _recent_text(recent: Mapping[str, Any], identity: Mapping[str, Any]) -> str | None:
    parts: list[str] = []
    for side in SIDES:
        stats = _last5(recent.get(side))
        wdl = stats.get("wdl") if isinstance(stats, Mapping) else None
        if not isinstance(wdl, Mapping):
            continue
        parts.append(
            f"{_team_name(identity, side)}近5场{_format_number(wdl.get('wins'))}胜{_format_number(wdl.get('draws'))}平{_format_number(wdl.get('losses'))}负，进{_format_number(stats.get('goals_for'))}球、失{_format_number(stats.get('goals_against'))}球"
        )
    return "；".join(parts) + "。" if parts else None


def _process_text(
    process: Mapping[str, Any] | None,
    identity: Mapping[str, Any],
    alignment: str,
    process_direction: str | None,
) -> str | None:
    if not isinstance(process, Mapping):
        return None
    facts: list[str] = []
    teams = process.get("teams")
    for metric, label in (("shots_faced", "被射门"), ("corners", "角球"), ("possession", "控球")):
        values = []
        for side in SIDES:
            row = teams.get(side, {}).get(metric, {}) if isinstance(teams, Mapping) and isinstance(teams.get(side), Mapping) else {}
            value = _number(_first(row, "near3", "near10")) if isinstance(row, Mapping) else None
            values.append(value)
        if all(value is not None for value in values):
            suffix = "%" if metric == "possession" else ""
            facts.append(f"{label}{_team_name(identity, 'home')} {values[0]:.1f}{suffix}/{_team_name(identity, 'away')} {values[1]:.1f}{suffix}")
    if not facts:
        return None
    relation = {
        "supportive": "与近期结果同向",
        "contradictory": "与近期结果相反",
        "mixed": "没有形成单边同向",
    }[alignment]
    if process_direction in SIDES:
        subject = _team_name(identity, process_direction)
        direction_text = f"；这些记录{relation}，过程方向偏向{subject}。"
    else:
        direction_text = "；这些记录没有形成单边方向。"
    return "近3场的" + "、".join(facts) + direction_text


def _market_details(projection: Mapping[str, Any], prediction: Mapping[str, Any]) -> tuple[str | None, dict[str, Any]]:
    market = projection.get("market_1x2_chronology") if isinstance(projection, Mapping) else None
    alignment = projection.get("model_market_alignment") if isinstance(projection, Mapping) else None
    relationship = "neutral"
    if isinstance(alignment, Mapping):
        relationship = {"ALIGNED": "aligned", "CONFLICT": "conflicting"}.get(_text(alignment.get("direction")), "neutral")
    details: dict[str, Any] = {"status": "OMITTED", "relationship": relationship}
    if not isinstance(market, Mapping) or market.get("status") != "AVAILABLE":
        return None, details
    opening = market.get("median_opening_probability")
    current = market.get("median_current_probability")
    current_preferred = _preferred(current)
    model_preferred = _preferred(prediction.get("probabilities"))
    delta = market.get("delta_probability_points")
    details.update(
        {
            "status": "AVAILABLE",
            "opening_preferred_outcome": _preferred(opening),
            "current_preferred_outcome": current_preferred,
            "model_preferred_outcome": model_preferred,
            "opening_probability": opening,
            "current_probability": current,
            "delta_probability_points": delta,
            "valid_book_count": market.get("valid_book_count"),
        }
    )
    delta_values = {key: _number(value) for key, value in (delta.items() if isinstance(delta, Mapping) else [])}
    moved = max(delta_values, key=lambda key: abs(delta_values[key])) if delta_values and all(value is not None for value in delta_values.values()) else None
    movement = "开盘到当前的中位变化较小"
    if moved is not None and abs(delta_values[moved]) >= 0.5:
        movement = f"开盘到当前，{OUTCOME_LABELS.get(moved, moved)}中位概率变动{delta_values[moved]:+.1f}个百分点"
    current_text = OUTCOME_LABELS.get(current_preferred, "方向未定")
    relation_text = {
        "aligned": "与当前方向同向",
        "conflicting": "与当前方向冲突",
        "neutral": "暂不构成方向关系",
    }[relationship]
    return f"1X2从开盘到当前的去水中位概率仍以{current_text}为首位，{movement}；市场信号{relation_text}。", details


def _future_text(future: Mapping[str, Any], identity: Mapping[str, Any]) -> str | None:
    if _text(future.get("status")) != "AVAILABLE":
        return None
    short = [side for side in SIDES if (future.get(side) or {}).get("short_rest")]
    if short:
        detail = "、".join(
            f"{_team_name(identity, side)}下一段间隔{_format_number((future.get(side) or {}).get('next_interval_days'))}天"
            for side in short
        )
        return f"后续赛程显示{detail}；短间隔会压低对近期强度直接外推的把握，因此只保留已有方向，不追加阵容或战术推断。"
    return None


def _counter_text(
    outlier: Mapping[str, Any],
    result_direction: str | None,
    process_direction: str | None,
    market_relationship: str,
    market_details: Mapping[str, Any],
    identity: Mapping[str, Any],
    identifiability: str,
) -> str | None:
    parts: list[str] = []
    if _text(outlier.get("status")) == "PRESENT":
        side = _text(outlier.get("side"))
        dimension = "进球" if outlier.get("dimension") == "goals_for" else "失球"
        parts.append(
            f"{_team_name(identity, side)}近5场有一场{dimension}达到{_format_number(outlier.get('value'))}，占该窗口该项合计{_format_percent(outlier.get('share'))}，原始合计因此只作背景，不直接外推本场。"
        )
    if result_direction and process_direction and result_direction != process_direction and result_direction != "draw":
        parts.append(
            f"近期结果方向偏向{OUTCOME_LABELS.get(result_direction, result_direction)}，过程方向却偏向{OUTCOME_LABELS.get(process_direction, process_direction)}，这是最需要保留的证据冲突。"
        )
    if market_relationship == "conflicting":
        parts.append(
            f"市场当前首位为{OUTCOME_LABELS.get(_text(market_details.get('current_preferred_outcome')), '方向未定')}，而当前胜平负分布首位为{OUTCOME_LABELS.get(_text(market_details.get('model_preferred_outcome')), '方向未定')}，两者没有合并成确定性。"
        )
    if identifiability == "LOW":
        parts.append("因此本场只保留弱方向，不把单一比分写成唯一答案。")
    return "".join(parts) or None


def _forecast_text(
    prediction: Mapping[str, Any],
    goal_shape: Mapping[str, Any],
    scores: list[dict[str, Any]],
    identifiability: str,
) -> tuple[str, dict[str, Any]]:
    probabilities = prediction.get("probabilities") if isinstance(prediction.get("probabilities"), Mapping) else {}
    preferred = _preferred(probabilities)
    totals = prediction.get("totals") if isinstance(prediction.get("totals"), list) else []
    over25 = sum(
        _number(item.get("probability")) or 0
        for item in totals
        if isinstance(item, Mapping) and (_text(item.get("goals")) == "6+" or (_number(item.get("goals")) is not None and _number(item.get("goals")) > 2))
    )
    btts_value = prediction.get("btts") if isinstance(prediction.get("btts"), Mapping) else {}
    btts_yes = _number(btts_value.get("yes"))
    primary = scores[0]["score"] if scores and identifiability != "LOW" else None
    cluster = [item["score"] for item in scores]
    exact_text = (
        f"Exact比分当前第一候选为{primary}，但仍和{', '.join(cluster[1:3]) or '邻近候选'}一起读取"
        if primary
        else f"Exact比分只保留候选簇{', '.join(cluster[:3]) or '暂无'}，不设唯一首选"
    )
    shape_btts = goal_shape.get("btts_rate") if isinstance(goal_shape, Mapping) else {}
    shape_clean = goal_shape.get("clean_sheet_rate") if isinstance(goal_shape, Mapping) else {}
    home_btts = shape_btts.get("home") if isinstance(shape_btts, Mapping) else None
    away_btts = shape_btts.get("away") if isinstance(shape_btts, Mapping) else None
    home_clean = shape_clean.get("home") if isinstance(shape_clean, Mapping) else None
    away_clean = shape_clean.get("away") if isinstance(shape_clean, Mapping) else None
    forecast = {
        "ft_result": {"preferred_outcome": preferred, "probabilities": {key: _round(_number(probabilities.get(key))) for key in OUTCOMES}},
        "goal_environment": {"over_2_5_probability": _round(over25), "btts_yes_probability": _round(btts_yes)},
        "btts_clean_sheet": {"recent_btts_rate": {"home": home_btts, "away": away_btts}, "recent_clean_sheet_rate": {"home": home_clean, "away": away_clean}},
        "margin_tail": {"score_candidates": cluster, "identifiability": identifiability},
        "exact_score_cluster": {"primary_score": primary, "candidates": cluster, "unique_score_allowed": primary is not None},
    }
    text = (
        f"落到预测层，先看{OUTCOME_LABELS.get(preferred, '胜平负方向未定')}；再看总进球大于2.5的分布约{_format_percent(over25)}、双方进球约{_format_percent(btts_yes)}，近况双方进球率为{_format_percent(home_btts)}和{_format_percent(away_btts)}，零封率为{_format_percent(home_clean)}和{_format_percent(away_clean)}；最后看{exact_text}。"
    )
    return text, forecast


def _join_text(*parts: str | None) -> str | None:
    return "".join(filter(None, parts)) or None


def _build_article_plan(
    *,
    prediction: Mapping[str, Any],
    identity: Mapping[str, Any],
    recent: Mapping[str, Any],
    process: Mapping[str, Any] | None,
    result_direction: str | None,
    process_direction: str | None,
    result_process_alignment: str,
    future: Mapping[str, Any],
    market_text: str | None,
    market_details: Mapping[str, Any],
    market_relationship: str,
    outlier: Mapping[str, Any],
    identifiability: str,
    forecast_text: str,
) -> ArticlePlan:
    model_preferred = _preferred(prediction.get("probabilities"))
    home, away = _team_name(identity, "home"), _team_name(identity, "away")
    aligned_direction = result_direction or process_direction or model_preferred or "mixed"
    model_subject = _team_name(identity, model_preferred) if model_preferred in SIDES else "胜平负分布"
    result_subject = _team_name(identity, result_direction) if result_direction in SIDES else "两队"

    if identifiability == "HIGH" and result_process_alignment == "supportive" and market_relationship == "aligned":
        thesis = f"{_team_name(identity, aligned_direction)}的近期结果、过程记录与1X2方向同向，{home}对{away}的主线清晰；但比分仍按候选簇理解，不把方向优势写成确定赛果。"
        thesis_direction = aligned_direction
    elif identifiability == "LOW":
        thesis = f"{home}对{away}的核心不是单边结论：{model_subject}只保留弱倾向，近期结果、过程和市场没有形成足够一致的证据，比分需以分散候选簇读取。"
        thesis_direction = model_preferred or "mixed"
    elif market_relationship == "conflicting":
        thesis = f"{model_subject}在当前胜平负分布中占优，但市场与近期证据保留反向信息；{home}对{away}更适合写成有条件的方向，而不是单一路径。"
        thesis_direction = model_preferred or "mixed"
    elif result_process_alignment == "contradictory":
        thesis = f"{result_subject}的近期结果占优，但过程记录把注意力推向另一侧；{home}对{away}的预测主线因此需要保留反证与进球尾部。"
        thesis_direction = result_direction or "mixed"
    else:
        thesis = f"{home}对{away}的方向信号存在层次差异：近期结果提供{OUTCOME_LABELS.get(result_direction, '有限')}起点，过程与市场只作交叉确认，比分不作单点承诺。"
        thesis_direction = result_direction or process_direction or "mixed"

    recent_text = _recent_text(recent, identity)
    process_text = _process_text(process, identity, result_process_alignment, process_direction)
    future_text = _future_text(future, identity)
    recent_process_text = _join_text(recent_text, process_text, future_text)
    counter_text = _counter_text(
        outlier,
        result_direction,
        process_direction,
        market_relationship,
        market_details,
        identity,
        identifiability,
    )

    recent_refs = ["football_evidence.recent_form"] if recent_text else []
    if process_text:
        recent_refs.append("football_evidence.recent_process_context")
    if future_text:
        recent_refs.append("football_evidence.future_schedule_rest")
    counter_refs: list[str] = []
    if _text(outlier.get("status")) == "PRESENT":
        counter_refs.append("football_evidence.recent_form")
    if result_direction and process_direction and result_direction != process_direction and result_direction != "draw":
        counter_refs.append("football_evidence.recent_process_context")
    if market_relationship == "conflicting":
        counter_refs.append("football_evidence.market_context")
    forecast_refs = ["prediction_record.probabilities_and_score_cluster", "football_evidence.recent_form"]
    thesis_refs = ["prediction_record.probabilities_and_score_cluster"]
    if recent_text:
        thesis_refs.insert(0, "football_evidence.recent_form")
    if process_text:
        thesis_refs.append("football_evidence.recent_process_context")
    if market_text:
        thesis_refs.append("football_evidence.market_context")

    plan: ArticlePlan = []

    def add(role: str, subject: str, direction: str, refs: list[str], text: str | None) -> None:
        if not text:
            return
        plan.append({
            "role": role,
            "subject": subject,
            "direction": direction,
            "strength": {"HIGH": "strong", "MEDIUM": "moderate", "LOW": "weak"}.get(identifiability, "weak"),
            "evidence_refs": list(dict.fromkeys(refs)),
            "order": len(plan) + 1,
            "text": text,
        })

    add(
        "thesis",
        _team_name(identity, thesis_direction) if thesis_direction in SIDES else "两队",
        thesis_direction,
        thesis_refs,
        thesis,
    )
    if identifiability == "LOW":
        add(
            "evidence_conflict",
            "两队",
            "mixed",
            recent_refs + counter_refs,
            _join_text(recent_process_text, counter_text),
        )
    else:
        process_subject = _team_name(identity, process_direction) if process_direction in SIDES else "两队"
        add("recent_process", process_subject, process_direction or result_direction or "mixed", recent_refs, recent_process_text)
        add("counterevidence", "两队", "mixed", counter_refs, counter_text)
    add("market", "market", _text(market_details.get("current_preferred_outcome")) or "neutral", ["football_evidence.market_context"], market_text)
    add("forecast", "prediction", model_preferred or "mixed", forecast_refs, forecast_text)
    return plan


def build_match_analysis_article(
    prediction: Mapping[str, Any] | None,
    input_snapshot: Mapping[str, Any] | None,
    football_evidence: Mapping[str, Any] | None,
    accepted_fixture: Mapping[str, Any] | None,
    identity: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a public-safe article without mutating frozen inputs."""

    prediction = prediction if isinstance(prediction, Mapping) else {}
    input_snapshot = input_snapshot if isinstance(input_snapshot, Mapping) else {}
    football_evidence = football_evidence if isinstance(football_evidence, Mapping) else {}
    identity = identity if isinstance(identity, Mapping) else {}
    empty = {
        "contract_version": CONTRACT_VERSION,
        "status": "OMITTED",
        "article_plan": [],
        "paragraphs": [],
        "source_refs": [],
        "evidence_envelope": build_evidence_envelope(prediction, input_snapshot, football_evidence, accepted_fixture),
    }
    if not prediction or not football_evidence:
        return empty
    try:
        projection = project_match_analysis_evidence(prediction, input_snapshot, football_evidence, accepted_fixture or {})
    except (AttributeError, KeyError, TypeError, ValueError):
        return empty
    if projection.get("projection_success") is not True:
        return empty
    if not isinstance(_accepted_field(football_evidence, "market_context"), Mapping):
        projection = {
            **projection,
            "market_1x2_chronology": {"status": "OMITTED"},
            "model_market_alignment": {"status": "OMITTED"},
        }

    recent = _recent_state(projection, football_evidence)
    process = _process_projection(football_evidence)
    result_direction = _result_direction(recent)
    process_direction, process_votes = _process_direction(process)
    result_process_alignment = _alignment(result_direction, process_direction)
    goal_shape = _goal_shape(recent, process)
    outlier = _outlier_concentration(recent)
    market_text, market_details = _market_details(projection, prediction)
    market_relationship = _text(market_details.get("relationship")) or "neutral"
    scores = _scores(prediction)
    concentration = _score_concentration(scores)
    identifiability = _identifiability(
        result_process_alignment,
        market_relationship,
        concentration,
        recent_available=len(recent) == 2 and all(_last5(recent.get(side)) for side in SIDES),
        process_available=process_direction is not None,
    )
    future = _future_schedule_rest(football_evidence)
    forecast_text, forecast = _forecast_text(prediction, goal_shape, scores, identifiability)
    article_plan = _build_article_plan(
        prediction=prediction,
        identity=identity,
        recent=recent,
        process=process,
        result_direction=result_direction,
        process_direction=process_direction,
        result_process_alignment=result_process_alignment,
        future=future,
        market_text=market_text,
        market_details=market_details,
        market_relationship=market_relationship,
        outlier=outlier,
        identifiability=identifiability,
        forecast_text=forecast_text,
    )
    evidence_envelope = build_evidence_envelope(
        prediction,
        input_snapshot,
        football_evidence,
        accepted_fixture,
        projection=projection,
    )
    article_plan = _bind_article_plan(article_plan, evidence_envelope)
    source_refs: list[str] = []
    for item in article_plan:
        for ref in item["evidence_refs"]:
            if ref not in source_refs:
                source_refs.append(ref)
    headline = article_plan[0]["text"] if article_plan else ""
    return {
        "contract_version": CONTRACT_VERSION,
        "status": "AVAILABLE" if article_plan else "OMITTED",
        "headline": headline,
        "article_plan": article_plan,
        "paragraphs": article_plan,
        "result_process_alignment": result_process_alignment,
        "market_relationship": market_relationship,
        "goal_shape": goal_shape,
        "outlier_concentration": outlier,
        "identifiability": identifiability,
        "process_signals": {"result_direction": result_direction, "process_direction": process_direction, "votes": process_votes},
        "score_distribution_concentration": concentration,
        "market_evidence": market_details,
        "future_schedule_rest": future,
        "forecast": forecast,
        "source_refs": source_refs,
        "evidence_envelope": evidence_envelope,
    }


def _lineup_field(football_evidence: Mapping[str, Any]) -> Mapping[str, Any] | None:
    prematch = football_evidence.get("prematch_evidence")
    fields = prematch.get("fields") if isinstance(prematch, Mapping) else None
    field = fields.get("lineup_state") if isinstance(fields, Mapping) else None
    return field if isinstance(field, Mapping) else None


def _lineup_groups(value: Any) -> dict[str, dict[str, Any]]:
    groups: dict[str, dict[str, Any]] = {}
    if isinstance(value, Mapping):
        for side in SIDES:
            raw = value.get(side) or value.get(f"{side}_lineup") or value.get(f"{side}_team")
            if isinstance(raw, Mapping):
                groups[side] = {
                    "team_id": _first(raw, "team_id", "id", "canonical_team_id"),
                    "team_name": _first(raw, "team_name", "name"),
                    "players": raw.get("players") if isinstance(raw.get("players"), list) else raw.get("lineup"),
                    "player_count": _first(raw, "player_count", "count"),
                }
            elif isinstance(raw, list):
                groups[side] = {"team_id": None, "team_name": None, "players": raw, "player_count": len(raw)}
        rows = value.get("teams") or value.get("lineups")
        if isinstance(rows, list):
            for row in rows:
                if not isinstance(row, Mapping):
                    continue
                side = _text(row.get("side")).lower()
                if side not in SIDES or side in groups and groups[side].get("players"):
                    continue
                groups[side] = {
                    "team_id": _first(row, "team_id", "id", "canonical_team_id"),
                    "team_name": _first(row, "team_name", "name"),
                    "players": row.get("players") if isinstance(row.get("players"), list) else row.get("lineup"),
                    "player_count": _first(row, "player_count", "count"),
                }
        players = value.get("players")
        if isinstance(players, list):
            for player in players:
                if not isinstance(player, Mapping):
                    continue
                side = _text(player.get("side")).lower()
                if side not in SIDES:
                    continue
                groups.setdefault(side, {"team_id": None, "team_name": None, "players": [], "player_count": None})
                groups[side]["players"].append(player)
    elif isinstance(value, list):
        for player in value:
            if not isinstance(player, Mapping):
                continue
            side = _text(player.get("side")).lower()
            if side not in SIDES:
                continue
            groups.setdefault(side, {"team_id": None, "team_name": None, "players": [], "player_count": None})
            groups[side]["players"].append(player)
    return groups


def _confirmed_lineup(
    value: Any,
    identity: Mapping[str, Any],
) -> list[dict[str, Any]] | None:
    groups = _lineup_groups(value)
    result: list[dict[str, Any]] = []
    for side in SIDES:
        expected_id = _text(identity.get(f"{side}_team_id"))
        expected_name = _text(identity.get(f"{side}_team_name"))
        group = groups.get(side) or {}
        supplied_id = _text(group.get("team_id"))
        supplied_name = _text(group.get("team_name"))
        if supplied_id and expected_id and supplied_id != expected_id:
            return None
        if supplied_name and expected_name and supplied_name.casefold() != expected_name.casefold():
            return None
        players: list[dict[str, Any]] = []
        seen: set[str] = set()
        raw_players = group.get("players")
        if raw_players is not None and not isinstance(raw_players, list):
            return None
        for player in raw_players or []:
            if not isinstance(player, Mapping):
                return None
            player_side = _text(player.get("side"))
            if player_side and player_side.casefold() != side:
                return None
            player_team_id = _text(_first(player, "team_id", "canonical_team_id"))
            if player_team_id and expected_id and player_team_id != expected_id:
                return None
            if player.get("starter") is False or player.get("is_starter") is False or player.get("bench") is True:
                continue
            player_id = _text(_first(player, "player_id", "id", "canonical_player_id"))
            player_name = _text(_first(player, "player_name", "name", "display_name"))
            if not player_id and not player_name:
                return None
            key = f"id:{player_id}" if player_id else f"name:{player_name.casefold()}"
            if key in seen:
                return None
            seen.add(key)
            players.append(
                {
                    "player_id": player_id,
                    "player_name": player_name,
                    "side": side,
                }
            )
        count = len(players)
        if not players:
            count = _first(group, "player_count", "count")
            if count in (None, ""):
                return None
            try:
                count = int(count)
            except (TypeError, ValueError):
                return None
            if count <= 0:
                return None
        result.append(
            {
                "side": side,
                "team_id": supplied_id or expected_id,
                "team_name": supplied_name or expected_name,
                "player_count": count,
                "players": players,
            }
        )
    return result if len(result) == 2 else None


def build_late_briefing(
    base_article: Mapping[str, Any] | None,
    prediction: Mapping[str, Any] | None,
    input_snapshot: Mapping[str, Any] | None,
    football_evidence: Mapping[str, Any] | None,
    accepted_fixture: Mapping[str, Any] | None,
    identity: Mapping[str, Any] | None = None,
    *,
    evidence_envelope: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build an independent confirmed-lineup brief without touching frozen inputs."""

    base_article = base_article if isinstance(base_article, Mapping) else {}
    prediction = prediction if isinstance(prediction, Mapping) else {}
    input_snapshot = input_snapshot if isinstance(input_snapshot, Mapping) else {}
    football_evidence = football_evidence if isinstance(football_evidence, Mapping) else {}
    accepted_fixture = accepted_fixture if isinstance(accepted_fixture, Mapping) else {}
    identity = identity if isinstance(identity, Mapping) else {}
    envelope = evidence_envelope if isinstance(evidence_envelope, Mapping) else base_article.get("evidence_envelope")
    if not isinstance(envelope, Mapping):
        envelope = build_evidence_envelope(prediction, input_snapshot, football_evidence, accepted_fixture)
    base_hash = _stable_hash(base_article)
    prediction_hash = _text(prediction.get("prediction_sha256")) or _stable_hash(prediction)
    prediction_ref = _text(prediction.get("prediction_id")) or f"prediction:{prediction_hash}"
    common = {
        "contract_version": LATE_BRIEFING_CONTRACT_VERSION,
        "kind": "LateBriefing",
        "base_article_ref": f"match_analysis_article:{base_hash}",
        "base_article_sha256": base_hash,
        "formal_prediction_ref": prediction_ref,
        "formal_prediction_sha256": prediction_hash,
        "evidence_refs": ["football_evidence.lineup_state"],
    }
    omitted = {**common, "status": "OMITTED", "reason": "CONFIRMED_LINEUP_UNAVAILABLE"}
    if base_article.get("status") != "AVAILABLE":
        omitted["reason"] = "BASE_ARTICLE_UNAVAILABLE"
        return omitted
    by_id = _envelope_by_id(envelope)
    lineup_item = by_id.get("football_evidence.lineup_state")
    field = _lineup_field(football_evidence)
    semantic = (_text((field or {}).get("semantic_state")) or "").upper()
    value = field.get("value") if isinstance(field, Mapping) else None
    value_semantic = ""
    if semantic != "CONFIRMED" and isinstance(value, Mapping):
        semantic = (_text(value.get("semantic_state")) or _text(value.get("status")) or "").upper()
    elif isinstance(value, Mapping):
        value_semantic = (_text(value.get("semantic_state")) or _text(value.get("status")) or "").upper()
    if not lineup_item or lineup_item.get("status") != "VERIFIED" or not lineup_item.get("admissible") or semantic != "CONFIRMED" or value_semantic in {"PREDICTED", "EXPECTED", "PROBABLE"}:
        omitted["reason"] = "LINEUP_NOT_CONFIRMED" if semantic in {"PREDICTED", "EXPECTED", "PROBABLE", "UNLABELLED"} else omitted["reason"]
        return omitted
    confirmed = _confirmed_lineup(value, identity)
    if confirmed is None:
        omitted["reason"] = "LINEUP_IDENTITY_AMBIGUOUS"
        return omitted
    claims = [
        {
            "type": "confirmed_starting_xi",
            "subject_id": f"{envelope.get('subject_id', 'match:unresolved')}:team:{team.get('team_id') or team.get('side')}",
            "status": "VERIFIED",
            "value": team,
            "evidence_refs": ["football_evidence.lineup_state"],
        }
        for team in confirmed
    ]
    updates = []
    raw_updates = None
    if isinstance(value, Mapping):
        raw_updates = value.get("assumption_updates") or value.get("changes") or value.get("material_changes")
    if isinstance(raw_updates, list):
        for update in raw_updates:
            if not isinstance(update, Mapping):
                continue
            status = (_text(update.get("status")) or "").upper()
            status = "MATERIALLY_CHANGED" if status in {"CHANGED", "MATERIAL_CHANGE"} else status
            if status not in {"SUPPORTED", "MATERIALLY_CHANGED"}:
                continue
            updates.append(
                {
                    "status": status,
                    "subject_id": _text(update.get("subject_id")) or envelope.get("subject_id"),
                    "text": _text(update.get("text")) or status,
                    "evidence_refs": ["football_evidence.lineup_state"],
                }
            )
    if not updates:
        updates = [
            {
                "status": "SUPPORTED",
                "subject_id": envelope.get("subject_id"),
                "text": "Confirmed lineup evidence is available; the frozen base article remains unchanged.",
                "evidence_refs": ["football_evidence.lineup_state"],
            }
        ]
    return {
        **common,
        "status": "AVAILABLE",
        "lineup_status": "CONFIRMED",
        "confirmed_lineup": confirmed,
        "claims": claims,
        "assumption_updates": updates,
    }


__all__ = [
    "CONTRACT_VERSION",
    "EVIDENCE_ENVELOPE_VERSION",
    "LATE_BRIEFING_CONTRACT_VERSION",
    "build_evidence_envelope",
    "build_late_briefing",
    "build_match_analysis_article",
    "render_article_plan",
]
