"""Background health diagnostics for the shadow team-strength pipeline."""

from __future__ import annotations

from typing import Any, Iterable, Mapping

from .historical_results import deduplicate_historical_results
from .team_strength import TeamStrengthBuilder
from .providers.base import utc_now


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
        "neither": 0,
        "identity_unresolved": 0,
        "insufficient_history": 0,
        "duplicate_conflict": deduplication.conflicts,
        "source_missing": 0,
    }
    coverage: list[dict[str, Any]] = []
    for match in current_matches:
        counts["current_matches"] += 1
        kickoff = match.get("kickoff_at") or match.get("kickoff") or match.get("kickoff_local")
        home_id = match.get("home_team_id")
        away_id = match.get("away_team_id")
        row = {
            "match_id": match.get("canonical_match_id") or match.get("id") or match.get("match_id"),
            "home": match.get("home") or match.get("home_team"),
            "away": match.get("away") or match.get("away_team"),
            "kickoff_at": kickoff,
            "competition_id": match.get("competition_id"),
            "season_id": match.get("season_id"),
            "home_team_id": home_id,
            "away_team_id": away_id,
        }
        if not home_id or not away_id or not kickoff:
            counts["identity_unresolved"] += 1
            counts["neither"] += 1
            counts["source_missing"] += 1 if not records else 0
            row.update({"status": "neither", "reasons": ["identity_unresolved"]})
            coverage.append(row)
            continue
        try:
            built = builder.build_pre_match_snapshots({
                "canonical_match_id": row["match_id"],
                "kickoff_at": kickoff,
                "home_team_id": home_id,
                "away_team_id": away_id,
                "competition_id": row["competition_id"],
                "season_id": row["season_id"],
            }, windows=("last_5",))
            home_snapshot = built["home"].get("last_5")
            away_snapshot = built["away"].get("last_5")
        except (TypeError, ValueError):
            home_snapshot = away_snapshot = None
        home_ok = bool(home_snapshot and home_snapshot.get("matches", 0) > 0 and home_snapshot.get("quality") in {"A", "B"})
        away_ok = bool(away_snapshot and away_snapshot.get("matches", 0) > 0 and away_snapshot.get("quality") in {"A", "B"})
        if home_ok and away_ok:
            status = "both_teams_evaluable"
            counts["both_teams_evaluable"] += 1
        elif home_ok:
            status = "home_only"
            counts["home_only"] += 1
        elif away_ok:
            status = "away_only"
            counts["away_only"] += 1
        else:
            status = "neither"
            counts["neither"] += 1
        if not home_ok or not away_ok:
            counts["insufficient_history"] += 1
        if not records:
            counts["source_missing"] += 1
        row.update({
            "status": status,
            "reasons": [] if status == "both_teams_evaluable" else ["insufficient_history"],
            "home_snapshot_id": home_snapshot.get("snapshot_id") if home_snapshot else None,
            "away_snapshot_id": away_snapshot.get("snapshot_id") if away_snapshot else None,
        })
        coverage.append(row)
    return {
        **counts,
        "coverage_by_match": coverage,
        "data_layer_only": True,
        "validated_for_model": False,
        "last_updated_at": captured_at or utc_now(),
    }
