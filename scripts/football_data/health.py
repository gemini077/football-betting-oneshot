"""Background health diagnostics for the shadow team-strength pipeline."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

from .historical_results import deduplicate_historical_results
from .team_strength import TeamStrengthBuilder
from .providers.base import utc_now


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _team_details(
    snapshots: Mapping[str, Mapping[str, Any]],
    *,
    team_id: str | None,
    records: Iterable[Mapping[str, Any]],
    target_kickoff: str | None,
    entity_type: str,
) -> dict[str, Any]:
    if not team_id:
        return {
            "canonical_team_id": None,
            "last5_available": 0,
            "last10_available": 0,
            "last20_available": 0,
            "season_to_date_available": 0,
            "historical_match_count": 0,
            "latest_historical_match_date": None,
            "oldest_used_match_date": None,
            "sources": [],
        }
    target = _parse_time(target_kickoff)
    eligible = []
    for record in records:
        if record.get("eligible_for_team_strength") is not True or record.get("entity_type", "club") != entity_type:
            continue
        if team_id not in {record.get("home_team_id"), record.get("away_team_id")}:
            continue
        kickoff = _parse_time(record.get("kickoff_at"))
        if target is not None and (kickoff is None or kickoff >= target):
            continue
        eligible.append(record)
    eligible.sort(key=lambda row: str(row.get("kickoff_at") or ""))
    last20 = snapshots.get("last_20") or {}
    return {
        "canonical_team_id": team_id,
        "last5_available": int((snapshots.get("last_5") or {}).get("matches") or 0),
        "last10_available": int((snapshots.get("last_10") or {}).get("matches") or 0),
        "last20_available": int((snapshots.get("last_20") or {}).get("matches") or 0),
        "season_to_date_available": int((snapshots.get("season_to_date") or {}).get("matches") or 0),
        "historical_match_count": len(eligible),
        "latest_historical_match_date": eligible[-1].get("kickoff_at") if eligible else None,
        "oldest_used_match_date": last20.get("oldest_used_match_at"),
        "sources": sorted({str(record.get("provider")) for record in eligible if record.get("provider")}),
    }


def build_team_strength_health(
    current_matches: Iterable[Mapping[str, Any]],
    historical_records: Iterable[Mapping[str, Any]],
    *,
    captured_at: str | None = None,
) -> dict[str, Any]:
    records = list(historical_records)
    deduplication = deduplicate_historical_results(records)
    builder = TeamStrengthBuilder(records, captured_at=captured_at)
    counts = {
        "current_matches": 0,
        "both_teams_evaluable": 0,
        "home_only": 0,
        "away_only": 0,
        "one_team_evaluable": 0,
        "neither": 0,
        "neither_evaluable": 0,
        "identity_unresolved": 0,
        "insufficient_history": 0,
        "history_missing": 0,
        "duplicate_conflict": deduplication.conflicts,
        "source_conflict": deduplication.conflicts,
        "source_missing": 0,
    }
    coverage: list[dict[str, Any]] = []
    coverage_by_competition: dict[str, dict[str, Any]] = {}
    for match in current_matches:
        counts["current_matches"] += 1
        kickoff = match.get("kickoff_at") or match.get("kickoff") or match.get("kickoff_local")
        home_id = match.get("home_team_id")
        away_id = match.get("away_team_id")
        entity_type = str(match.get("entity_type") or "club")
        competition_id = match.get("competition_id")
        season_id = match.get("season_id")
        competition_key = str(competition_id or match.get("league") or "unresolved")
        competition_row = coverage_by_competition.setdefault(
            competition_key,
            {"current_matches": 0, "both_teams_evaluable": 0, "one_team_evaluable": 0, "neither_evaluable": 0},
        )
        competition_row["current_matches"] += 1
        row = {
            "match_id": match.get("canonical_match_id") or match.get("id") or match.get("match_id"),
            "home": match.get("home") or match.get("home_team"),
            "away": match.get("away") or match.get("away_team"),
            "kickoff_at": kickoff,
            "competition_id": competition_id,
            "season_id": season_id,
            "entity_type": entity_type,
            "home_team_id": home_id,
            "away_team_id": away_id,
        }
        if not home_id or not away_id or not kickoff:
            counts["identity_unresolved"] += 1
            counts["neither"] += 1
            counts["neither_evaluable"] += 1
            counts["history_missing"] += 1
            counts["source_missing"] += 1 if not records else 0
            competition_row["neither_evaluable"] += 1
            row.update({"status": "neither", "reasons": ["identity_unresolved"], "team_details": {"home": _team_details({}, team_id=home_id, records=records, target_kickoff=kickoff, entity_type=entity_type), "away": _team_details({}, team_id=away_id, records=records, target_kickoff=kickoff, entity_type=entity_type)}})
            coverage.append(row)
            continue
        snapshots: dict[str, dict[str, Any]] = {"home": {}, "away": {}}
        for side, team_id in (("home", home_id), ("away", away_id)):
            for window in ("last_5", "last_10", "last_20", "season_to_date"):
                try:
                    snapshots[side][window] = builder.build(
                        str(team_id),
                        target_kickoff=str(kickoff),
                        window_type=window,
                        competition_id=competition_id,
                        season_id=season_id,
                        target_match_id=str(row["match_id"]),
                        entity_type=entity_type,
                    )
                except (TypeError, ValueError):
                    snapshots[side][window] = None
        home_last5 = snapshots["home"].get("last_5")
        away_last5 = snapshots["away"].get("last_5")
        home_ok = bool(home_last5 and home_last5.get("matches", 0) > 0 and home_last5.get("quality") in {"A", "B"})
        away_ok = bool(away_last5 and away_last5.get("matches", 0) > 0 and away_last5.get("quality") in {"A", "B"})
        if home_ok and away_ok:
            status = "both_teams_evaluable"
            counts["both_teams_evaluable"] += 1
            competition_row["both_teams_evaluable"] += 1
        elif home_ok:
            status = "home_only"
            counts["home_only"] += 1
            counts["one_team_evaluable"] += 1
            competition_row["one_team_evaluable"] += 1
        elif away_ok:
            status = "away_only"
            counts["away_only"] += 1
            counts["one_team_evaluable"] += 1
            competition_row["one_team_evaluable"] += 1
        else:
            status = "neither"
            counts["neither"] += 1
            counts["neither_evaluable"] += 1
            competition_row["neither_evaluable"] += 1
        if not home_ok or not away_ok:
            counts["insufficient_history"] += 1
            counts["history_missing"] += 1
        if not records:
            counts["source_missing"] += 1
        reasons = [] if status == "both_teams_evaluable" else ["insufficient_history"]
        row.update(
            {
                "status": status,
                "reasons": reasons,
                "home_snapshot_id": home_last5.get("snapshot_id") if home_last5 else None,
                "away_snapshot_id": away_last5.get("snapshot_id") if away_last5 else None,
                "team_details": {
                    "home": _team_details(snapshots["home"], team_id=str(home_id), records=builder.records, target_kickoff=str(kickoff), entity_type=entity_type),
                    "away": _team_details(snapshots["away"], team_id=str(away_id), records=builder.records, target_kickoff=str(kickoff), entity_type=entity_type),
                },
            }
        )
        coverage.append(row)
    return {
        **counts,
        "coverage_by_match": coverage,
        "coverage_by_competition": coverage_by_competition,
        "data_layer_only": True,
        "validated_for_model": False,
        "last_updated_at": captured_at or utc_now(),
    }
