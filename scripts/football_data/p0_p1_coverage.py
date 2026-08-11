"""Retrospective P0/P1 availability and scope diagnostics.

The functions here inspect normalized historical results only. They never
create predictions, benchmark rows, or model inputs.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

from .historical_results import deduplicate_historical_results
from .team_strength import TeamStrengthBuilder


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def classify_recent_form_scope(
    *,
    observed_match_types: Iterable[str],
    intended_match_types: Iterable[str],
    evidence_known: bool = True,
) -> str:
    """Classify whether the observed result scope covers the intended scope."""

    if not evidence_known:
        return "UNKNOWN"
    observed = {str(value) for value in observed_match_types if value}
    intended = {str(value) for value in intended_match_types if value}
    if not observed or not intended:
        return "UNKNOWN"
    return "COMPLETE" if intended.issubset(observed) else "PARTIAL"


def _team_rows(records: Iterable[Mapping[str, Any]], team_id: str, target_kickoff: str, entity_type: str) -> list[Mapping[str, Any]]:
    target = _parse_time(target_kickoff)
    rows: list[Mapping[str, Any]] = []
    for record in records:
        if record.get("eligible_for_team_strength") is not True:
            continue
        if record.get("entity_type", "club") != entity_type:
            continue
        if team_id not in {record.get("home_team_id"), record.get("away_team_id")}:
            continue
        kickoff = _parse_time(record.get("kickoff_at"))
        if kickoff is None or target is None or kickoff >= target:
            continue
        rows.append(record)
    return sorted(rows, key=lambda row: str(row.get("kickoff_at") or ""))


def _scope_for_team(
    rows: Iterable[Mapping[str, Any]],
    *,
    intended_match_types: Iterable[str],
    target_competition_type: str,
) -> tuple[str, bool, bool]:
    rows = list(rows)
    observed = {str(row.get("match_type") or "unknown") for row in rows}
    scope = classify_recent_form_scope(
        observed_match_types=observed,
        intended_match_types=intended_match_types,
        evidence_known=bool(rows),
    )
    league_ready = bool(rows) and sum(row.get("match_type") == "league" for row in rows) >= 5
    all_ready = scope == "COMPLETE" and len(rows) >= 5
    # For a domestic league target, the intended all-competition scope is
    # explicitly supplied as just league by the caller. For UEFA targets the
    # caller supplies league/cup/continental and this remains PARTIAL when
    # domestic history is absent.
    if target_competition_type == "international_club" and "continental_club" not in observed:
        all_ready = False
    return scope, league_ready, all_ready


def _snapshot_details(snapshot: Mapping[str, Any] | None, rows: list[Mapping[str, Any]], *, scope: str, league_ready: bool, all_ready: bool) -> dict[str, Any]:
    snapshot = snapshot or {}
    return {
        "history_matches": int(snapshot.get("matches") or 0),
        "history_available": bool(snapshot.get("matches", 0) >= 5),
        "current_strength_ready": bool(snapshot.get("current_strength_ready")),
        "history_recency_status": snapshot.get("history_recency_status", "unknown"),
        "bridge_status": snapshot.get("bridge_status", "not_applicable"),
        "history_age_days": snapshot.get("history_age_days"),
        "latest_historical_match_at": snapshot.get("latest_historical_match_at"),
        "source_match_ids": list(snapshot.get("source_match_ids") or []),
        "recent_form_scope": scope,
        "league_form_ready": league_ready,
        "all_competition_form_ready": all_ready,
        "history_scope_incomplete": scope != "COMPLETE",
        "sources": sorted({str(row.get("provider")) for row in rows if row.get("provider")}),
    }


def audit_retrospective_availability(
    target_matches: Iterable[Mapping[str, Any]],
    historical_records: Iterable[Mapping[str, Any]],
    *,
    captured_at: str | None = None,
    min_history_matches: int = 5,
) -> list[dict[str, Any]]:
    """Audit whether each target could have had pre-match strength data.

    ``TeamStrengthBuilder`` performs the strict ``kickoff < target`` filter;
    this layer only adds demand status, scope, and weighted-gate semantics.
    """

    del captured_at  # provenance remains in snapshots; audit is retrospective
    records = list(historical_records)
    deduplication = deduplicate_historical_results(records)
    builder = TeamStrengthBuilder(records)
    output: list[dict[str, Any]] = []
    for target in target_matches:
        target_id = target.get("canonical_match_id") or target.get("id") or target.get("target_match_id")
        kickoff = str(target.get("kickoff_at") or target.get("kickoff") or "")
        entity_type = str(target.get("entity_type") or "club")
        competition_id = target.get("competition_id")
        season_id = target.get("season_id")
        competition_type = str(target.get("competition_type") or "league")
        intended = set(target.get("intended_match_types") or ({"league", "domestic_cup", "continental_club"} if competition_type == "international_club" else {"league"}))
        home_id = target.get("home_team_id")
        away_id = target.get("away_team_id")
        base: dict[str, Any] = {
            "target_match_id": target_id,
            "competition_key": target.get("competition_key"),
            "competition_id": competition_id,
            "kickoff": kickoff,
            "target_kickoff": kickoff,
            "home": target.get("home"),
            "away": target.get("away"),
            "weight": int(target.get("weight") or 1),
            "home_identity_ready": bool(home_id),
            "away_identity_ready": bool(away_id),
            "home_history_matches": 0,
            "away_history_matches": 0,
            "home_recency": "unknown",
            "away_recency": "unknown",
            "home_current_strength_ready": False,
            "away_current_strength_ready": False,
            "strength_ready": False,
            "strict_ready": False,
            "bridge_only": False,
            "status": "IDENTITY_MISSING" if not home_id or not away_id else "SOURCE_MISSING" if not records else "INSUFFICIENT_HISTORY",
            "reason": [],
            "deduplication_conflicts": deduplication.conflicts,
        }
        if not home_id or not away_id:
            base["reason"] = ["identity_missing"]
            output.append(base)
            continue
        if not kickoff or _parse_time(kickoff) is None:
            base["reason"] = ["target_kickoff_missing"]
            base["status"] = "IDENTITY_MISSING"
            output.append(base)
            continue
        bridge_context = target.get("bridge_context")
        snapshots: dict[str, dict[str, Any] | None] = {"home": None, "away": None}
        details: dict[str, dict[str, Any]] = {}
        for side, team_id in (("home", home_id), ("away", away_id)):
            team_rows = _team_rows(records, str(team_id), kickoff, entity_type)
            scope, league_ready, all_ready = _scope_for_team(
                team_rows,
                intended_match_types=intended,
                target_competition_type=competition_type,
            )
            try:
                snapshots[side] = builder.build(
                    str(team_id),
                    target_kickoff=kickoff,
                    window_type="last_5",
                    competition_id=competition_id,
                    season_id=season_id,
                    target_match_id=str(target_id) if target_id else None,
                    entity_type=entity_type,
                    bridge_context=bridge_context,
                )
            except (TypeError, ValueError):
                snapshots[side] = None
            details[side] = _snapshot_details(snapshots[side], team_rows, scope=scope, league_ready=league_ready, all_ready=all_ready)
            base[f"{side}_history_matches"] = len(team_rows)
            base[f"{side}_recency"] = details[side]["history_recency_status"]
            base[f"{side}_current_strength_ready"] = details[side]["current_strength_ready"]
        home = details["home"]
        away = details["away"]
        base["home_details"] = home
        base["away_details"] = away
        base["home_source_match_ids"] = home["source_match_ids"]
        base["away_source_match_ids"] = away["source_match_ids"]
        base["home_history_available"] = home["history_available"]
        base["away_history_available"] = away["history_available"]
        base["home_identity_ready"] = True
        base["away_identity_ready"] = True
        base["history_available"] = bool(home["history_available"] and away["history_available"])
        base["league_form_ready"] = bool(home["league_form_ready"] and away["league_form_ready"])
        base["all_competition_form_ready"] = bool(home["all_competition_form_ready"] and away["all_competition_form_ready"])
        strict = bool(
            base["history_available"]
            and home["current_strength_ready"]
            and away["current_strength_ready"]
            and base["all_competition_form_ready"]
        )
        bridge = bool(
            base["history_available"]
            and home["history_recency_status"] == "offseason_bridge"
            and away["history_recency_status"] == "offseason_bridge"
            and home["bridge_status"] == "verified"
            and away["bridge_status"] == "verified"
        )
        base["strict_ready"] = strict
        base["strength_ready"] = strict
        base["bridge_only"] = bridge and not strict
        if strict:
            base["status"] = "STRICT_READY"
            base["reason"] = []
        elif bridge:
            base["status"] = "VERIFIED_BRIDGE"
            base["reason"] = ["offseason_bridge"]
        elif not base["history_available"]:
            base["status"] = "INSUFFICIENT_HISTORY"
            base["reason"] = ["minimum_history_not_met"]
        elif "stale" in {home["history_recency_status"], away["history_recency_status"]}:
            base["status"] = "STALE"
            base["reason"] = ["stale_history"]
        elif base["all_competition_form_ready"] is False:
            base["status"] = "SCOPE_PARTIAL"
            base["reason"] = ["recent_form_scope_partial"]
        else:
            base["status"] = "NOT_READY"
            base["reason"] = ["current_strength_not_ready"]
        output.append(base)
    return output


def weighted_ready_coverage(audits: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Aggregate demand-weighted readiness without dropping failure buckets."""

    counts = Counter()
    demand_weight = 0
    for audit in audits:
        weight = int(audit.get("weight") or 1)
        demand_weight += weight
        status = str(audit.get("status") or "NOT_READY")
        counts[status] += weight
    strict = counts["STRICT_READY"]
    bridge = counts["VERIFIED_BRIDGE"]
    return {
        "demand_weight": demand_weight,
        "strict_ready_weight": strict,
        "verified_bridge_weight": bridge,
        "source_missing_weight": counts["SOURCE_MISSING"],
        "identity_missing_weight": counts["IDENTITY_MISSING"],
        "stale_weight": counts["STALE"],
        "insufficient_history_weight": counts["INSUFFICIENT_HISTORY"],
        "scope_partial_weight": counts["SCOPE_PARTIAL"],
        "strict_ready_rate": strict / demand_weight if demand_weight else 0.0,
        "ready_plus_bridge_rate": (strict + bridge) / demand_weight if demand_weight else 0.0,
        "status_weights": dict(sorted(counts.items())),
    }


def evaluate_k_league_source_decision(discovery_rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Keep K League in the denominator unless a reviewed source is proven."""

    accepted = [row for row in discovery_rows if str(row.get("status") or "").upper() in {"SUPPORTED", "ADOPT", "ADAPTED"} and row.get("license_clear") is True]
    return {
        "K_LEAGUE_SOURCE_GAP": not bool(accepted),
        "status": "SUPPORTED" if accepted else "SOURCE_MISSING",
        "demand_remains_in_denominator": True,
        "accepted_candidates": accepted,
    }


def verified_season_bridge_context(
    *,
    bridge_from_season: str,
    bridge_to_season: str,
    season_stage: str,
    evidence: Iterable[str],
    bridge_reason: str,
) -> dict[str, Any]:
    """Build bridge evidence only from explicit season-opening metadata."""

    evidence = [str(value) for value in evidence if str(value).strip()]
    verified = season_stage in {"opening", "very_early"} and bool(evidence)
    return {
        "bridge_status": "verified" if verified else "unverified",
        "bridge_from_season": bridge_from_season,
        "bridge_to_season": bridge_to_season,
        "season_stage": season_stage,
        "bridge_reason": bridge_reason,
        "bridge_verification_evidence": evidence,
    }


__all__ = [
    "audit_retrospective_availability",
    "classify_recent_form_scope",
    "evaluate_k_league_source_decision",
    "verified_season_bridge_context",
    "weighted_ready_coverage",
]
