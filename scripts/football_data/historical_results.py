"""Versioned historical match results and conservative immutable deduplication.

This module is deliberately a shadow data-layer component.  It accepts only
already captured evidence, preserves unresolved raw observations, and never
feeds the formal Champion.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from .contracts import validate_record
from .quality import finalize_record_quality
from .storage import SnapshotStore
from .providers.base import provenance, utc_now


def _nonempty(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _append_missing(missing: list[str], reason: str) -> None:
    if reason not in missing:
        missing.append(reason)


def _captured_datetime(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def make_historical_match_result(
    *,
    canonical_match_id: str | None,
    competition_id: str | None,
    season_id: str | None,
    home_team_id: str | None,
    away_team_id: str | None,
    kickoff_at: str | None,
    home_goals: int | None,
    away_goals: int | None,
    provider: str,
    provider_match_id: str | None,
    source_as_of_at: str | None,
    captured_at: str | None = None,
    source_record_ref: str | None = None,
    source: str | None = None,
    source_url: str | None = None,
    source_reliable: bool | None = None,
    raw_home_team: str | None = None,
    raw_away_team: str | None = None,
    raw_competition: str | None = None,
    raw_season: str | None = None,
    resolution_status: str | None = None,
    resolution_method: str = "unresolved",
    synthetic: bool = False,
    observation_origin: str = "provider_observation",
    data_license: str | None = None,
    attribution_required: bool = False,
    commercial_use_review: str = "not_required",
    parser_version: str | None = None,
    raw_sha256: str | None = None,
    raw_redistribution: bool | None = None,
    internal_analysis_only: bool | None = None,
    repository: str | None = None,
    commit_sha: str | None = None,
    source_file: str | None = None,
    entity_type: str = "club",
    match_type: str = "unknown",
    source_conflict: bool = False,
    conflict_reasons: list[str] | None = None,
    source_confirmations: list[Mapping[str, Any]] | None = None,
    verification_evidence: list[Any] | None = None,
) -> dict[str, Any]:
    """Build and centrally grade one immutable result observation.

    Canonical IDs and the resolution method are caller-supplied evidence from
    the reviewed identity layer.  This function never turns a provider name
    or provider ID into a canonical identity by itself.
    """

    provider_text = _nonempty(provider) or "unknown_provider"
    source_text = _nonempty(source) or provider_text
    captured = captured_at or utc_now()
    source_ref = _nonempty(source_record_ref) or f"{provider_text}:{provider_match_id or 'unidentified'}"
    resolved = resolution_status or (
        "resolved"
        if canonical_match_id and home_team_id and away_team_id and resolution_method != "unresolved"
        else "unresolved"
    )
    canonical_entity_id = _nonempty(canonical_match_id) if resolved == "resolved" else None
    missing: list[str] = []
    if resolved != "resolved" or not home_team_id or not away_team_id or not canonical_entity_id:
        _append_missing(missing, "identity_unresolved")
    if not competition_id:
        _append_missing(missing, "competition_unresolved")
    if not season_id:
        _append_missing(missing, "season_unresolved")
    if kickoff_at in (None, ""):
        _append_missing(missing, "kickoff_missing")
    if home_goals is None or away_goals is None:
        _append_missing(missing, "result_missing")
    if source_as_of_at in (None, ""):
        _append_missing(missing, "source_fact_time_missing")
    if source_reliable is not True:
        _append_missing(missing, "source_unreliable_or_unreviewed")
    if source_conflict:
        _append_missing(missing, "source_conflict")

    record: dict[str, Any] = {
        "contract_version": "historical_match_result.v1",
        "source": source_text,
        "source_entity_id": _nonempty(provider_match_id),
        "canonical_entity_id": canonical_entity_id,
        "captured_at": captured,
        "source_as_of_at": source_as_of_at,
        "competition": competition_id,
        "season": season_id,
        "home_away_context": "neutral",
        "sample_size": {"matches": 1, "minutes": None},
        "value": None,
        "unit": "goals",
        "quality": "C",
        "freshness": {"state": "unknown", "age_seconds": None, "ttl_seconds": None},
        "missing_reason": missing,
        "provenance": provenance(
            provider=provider_text,
            source=source_text,
            source_record_ref=source_ref,
            captured_at=captured,
            source_as_of_at=source_as_of_at,
            source_reliable=source_reliable,
            source_url=source_url,
            data_license=data_license,
            attribution_required=attribution_required,
            commercial_use_review=commercial_use_review,
            parser_version=parser_version,
            synthetic=synthetic,
            observation_origin=observation_origin,
            raw_sha256=raw_sha256,
            raw_redistribution=raw_redistribution,
            internal_analysis_only=internal_analysis_only,
            repository=repository,
            commit_sha=commit_sha,
            source_file=source_file,
        ),
        "provider": provider_text,
        "provider_match_id": _nonempty(provider_match_id),
        "canonical_match_id": _nonempty(canonical_match_id),
        "competition_id": _nonempty(competition_id),
        "season_id": _nonempty(season_id),
        "home_team_id": _nonempty(home_team_id),
        "away_team_id": _nonempty(away_team_id),
        "raw_home_team": _nonempty(raw_home_team),
        "raw_away_team": _nonempty(raw_away_team),
        "raw_competition": _nonempty(raw_competition),
        "raw_season": _nonempty(raw_season),
        "kickoff_at": kickoff_at,
        "home_goals": home_goals,
        "away_goals": away_goals,
        "resolution_status": resolved,
        "resolution_method": resolution_method if resolved == "resolved" else "unresolved",
        "eligible_for_team_strength": False,
        "duplicate_status": "unique",
        "entity_type": entity_type,
        "match_type": match_type,
        "source_conflict": bool(source_conflict),
        "conflict_reasons": list(conflict_reasons or []),
        "source_confirmations": list(source_confirmations or [{
            "provider": provider_text,
            "provider_match_id": _nonempty(provider_match_id),
            "source_record_ref": source_ref,
        }]),
        "verification_evidence": list(verification_evidence or []),
    }
    finalize_record_quality(record, data_class="historical_immutable", record_type="historical_match_result", now=_captured_datetime(captured))
    record["eligible_for_team_strength"] = bool(
        record["resolution_status"] == "resolved"
        and record["canonical_match_id"]
        and record["competition_id"]
        and record["season_id"]
        and record["home_team_id"]
        and record["away_team_id"]
        and record["kickoff_at"]
        and record["home_goals"] is not None
        and record["away_goals"] is not None
        and record["source_as_of_at"]
        and record["quality"] in {"A", "B"}
        and record["provenance"].get("source_reliable") is True
        and not record["provenance"].get("synthetic", False)
        and not record.get("source_conflict", False)
    )
    if not record["eligible_for_team_strength"] and "quality_gate" not in record["missing_reason"] and record["quality"] not in {"A", "B"}:
        _append_missing(record["missing_reason"], "quality_gate")
    validate_record("historical_match_result", record)
    return record


@dataclass(frozen=True)
class DeduplicationReport:
    records: list[dict[str, Any]]
    duplicates_collapsed: int
    possible_duplicates: int
    conflicts: int


def _identity_key(record: Mapping[str, Any]) -> tuple[Any, ...] | None:
    canonical_match_id = _nonempty(record.get("canonical_match_id"))
    if canonical_match_id:
        return ("canonical_match_id", canonical_match_id)
    canonical_fields = (
        record.get("home_team_id"),
        record.get("away_team_id"),
        record.get("kickoff_at"),
        record.get("competition_id"),
    )
    if all(value not in (None, "") for value in canonical_fields):
        return ("conservative_tuple", *canonical_fields)
    return None


def _raw_signature(record: Mapping[str, Any]) -> tuple[Any, ...] | None:
    fields = (
        record.get("raw_home_team"),
        record.get("raw_away_team"),
        record.get("kickoff_at"),
        record.get("raw_competition") or record.get("competition_id"),
        record.get("home_goals"),
        record.get("away_goals"),
    )
    return tuple(str(value).strip().casefold() if isinstance(value, str) else value for value in fields) if any(value not in (None, "") for value in fields) else None


def _score_and_teams(record: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        record.get("competition_id"),
        record.get("season_id"),
        record.get("home_team_id"),
        record.get("away_team_id"),
        record.get("home_goals"),
        record.get("away_goals"),
    )


def _match_facts(record: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        *_score_and_teams(record),
        record.get("kickoff_at"),
        record.get("entity_type"),
        record.get("match_type"),
    )


def _confirmation(record: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "provider": record.get("provider"),
        "provider_match_id": record.get("provider_match_id"),
        "source_record_ref": record.get("provenance", {}).get("source_record_ref") or record.get("provider_match_id"),
        "kickoff_at": record.get("kickoff_at"),
        "home_goals": record.get("home_goals"),
        "away_goals": record.get("away_goals"),
    }


def _mark(record: Mapping[str, Any], status: str) -> dict[str, Any]:
    updated = dict(record)
    updated["duplicate_status"] = status
    if status == "duplicate_conflict":
        updated["source_conflict"] = True
        reasons = list(updated.get("conflict_reasons") or [])
        _append_missing(reasons, "source_records_disagree")
        updated["conflict_reasons"] = reasons
    updated["eligible_for_team_strength"] = False if status in {"possible_duplicate", "duplicate_conflict"} else bool(record.get("eligible_for_team_strength"))
    missing = list(updated.get("missing_reason") or [])
    if status != "unique":
        _append_missing(missing, status)
    updated["missing_reason"] = missing
    if status == "duplicate_conflict":
        finalize_record_quality(updated, data_class="historical_immutable", record_type="historical_match_result")
    validate_record("historical_match_result", updated)
    return updated


def deduplicate_historical_results(records: Iterable[Mapping[str, Any]]) -> DeduplicationReport:
    """Collapse only proven duplicates; preserve uncertain matches explicitly."""

    materialized = [dict(record) for record in records]
    for record in materialized:
        validate_record("historical_match_result", record)
    groups: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
    unkeyed: list[dict[str, Any]] = []
    for record in materialized:
        key = _identity_key(record)
        if key is None:
            unkeyed.append(record)
        else:
            groups.setdefault(key, []).append(record)

    output: list[dict[str, Any]] = []
    collapsed = 0
    possible = 0
    conflicts = 0
    for group in groups.values():
        if len(group) == 1:
            output.append(_mark(group[0], "unique"))
            continue
        if len({_match_facts(item) for item in group}) != 1:
            conflicts += 1
            output.extend(_mark(item, "duplicate_conflict") for item in group)
            continue
        chosen = sorted(
            group,
            key=lambda item: (
                {"A": 0, "B": 1, "C": 2, "D": 3}.get(str(item.get("quality")), 9),
                str(item.get("provider") or ""),
                str(item.get("provider_match_id") or ""),
            ),
        )[0]
        retained = _mark(chosen, "unique")
        retained["duplicate_source_refs"] = sorted(
            str(item.get("provenance", {}).get("source_record_ref") or item.get("provider_match_id") or "")
            for item in group
            if item is not chosen
        )
        retained["source_confirmations"] = [
            confirmation
            for item in group
            for confirmation in (item.get("source_confirmations") or [_confirmation(item)])
        ]
        output.append(retained)
        collapsed += len(group) - 1

    raw_groups: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
    for record in unkeyed:
        signature = _raw_signature(record)
        if signature is None:
            output.append(_mark(record, "unique"))
        else:
            raw_groups.setdefault(signature, []).append(record)
    for group in raw_groups.values():
        if len(group) == 1:
            output.append(_mark(group[0], "unique"))
        else:
            possible += 1
            output.extend(_mark(item, "possible_duplicate") for item in group)

    return DeduplicationReport(output, collapsed, possible, conflicts)


class HistoricalResultLedger:
    """Content-addressed result store; existing result bytes are never replaced."""

    def __init__(self, root: str | Path) -> None:
        self.store = SnapshotStore(root)

    def append(self, record: Mapping[str, Any]) -> str:
        validate_record("historical_match_result", record)
        digest, _ = self.store.put(record)
        return digest

    def records(self) -> list[dict[str, Any]]:
        if not self.store.root.exists():
            return []
        output: list[dict[str, Any]] = []
        for path in sorted(self.store.root.glob("*.json")):
            digest = path.stem
            try:
                output.append(self.store.get(digest))
            except (OSError, ValueError, json.JSONDecodeError):
                continue
        return output
