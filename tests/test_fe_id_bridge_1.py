from __future__ import annotations

import json
from pathlib import Path

from scripts.football_data.audit_historical_network_coverage import build_current_fixture_coverage
from scripts.football_data.project_identity import ProjectProviderIdentityResolver


ROOT = Path(__file__).resolve().parents[1]
TARGET_MATCH_ID = "500-1362754"
TARGET_PREDICTION_ID = "FBOS-PRED-a4787da3359e9462042cb287"
HOME_PROVIDER_ID = "417"
AWAY_PROVIDER_ID = "2088"
HOME_CANONICAL_ID = "team:sweden:if-elfsborg"
AWAY_CANONICAL_ID = "team:sweden:degerfors-if"
COMPETITION_ID = "competition:sweden-allsvenskan"


def _read(relative_path: str) -> dict:
    return json.loads((ROOT / relative_path).read_text(encoding="utf-8"))


def _target_fixture() -> dict:
    universe = _read("data/prediction_universe/2026-08-29.json")
    return next(item for item in universe["fixtures"] if item["matchId"] == TARGET_MATCH_ID)


def test_target_has_exact_nowscore_ids_and_verified_canonical_crosswalk() -> None:
    fixture = _target_fixture()
    identity = _read("data/football_data/current_match_identity_evidence.json")
    target_identity = next(item for item in identity["matches"] if item.get("id") == TARGET_MATCH_ID)
    mappings = _read("data/football_data/verified_project_provider_crosswalk.json")["mappings"]
    target_mappings = [
        item
        for item in mappings
        if item.get("provider") == "nowscore"
        and str(item.get("provider_team_id")) in {HOME_PROVIDER_ID, AWAY_PROVIDER_ID}
    ]

    assert fixture["nowscoreId"] == 2912253
    assert target_identity["verified"] is True
    assert target_identity["provider"] == "sporttery"
    assert target_identity["provider_match_id"] == TARGET_MATCH_ID
    assert target_identity["nowscore_match_id"] == "2912253"
    assert target_identity["provider_team_ids"] == {"home": HOME_PROVIDER_ID, "away": AWAY_PROVIDER_ID}
    assert target_identity["home_team_id"] == HOME_CANONICAL_ID
    assert target_identity["away_team_id"] == AWAY_CANONICAL_ID
    assert len(target_mappings) == 2
    assert {str(item["provider_team_id"]) for item in target_mappings} == {HOME_PROVIDER_ID, AWAY_PROVIDER_ID}
    assert {item["canonical_team_id"] for item in target_mappings} == {HOME_CANONICAL_ID, AWAY_CANONICAL_ID}

    resolver = ProjectProviderIdentityResolver(mappings)
    home = resolver.resolve_team(
        "nowscore",
        fixture["homeTeam"],
        HOME_PROVIDER_ID,
        competition_id=COMPETITION_ID,
        country="Sweden",
    )
    away = resolver.resolve_team(
        "nowscore",
        fixture["awayTeam"],
        AWAY_PROVIDER_ID,
        competition_id=COMPETITION_ID,
        country="Sweden",
    )
    assert home.canonical_team_id == HOME_CANONICAL_ID
    assert away.canonical_team_id == AWAY_CANONICAL_ID
    assert home.resolution_method == "provider_id_exact"
    assert away.resolution_method == "provider_id_exact"


def test_provider_evidence_binds_each_id_to_the_target_side_before_kickoff() -> None:
    evidence = _read(
        f"data/prospective/football_evidence/{TARGET_PREDICTION_ID}.json"
    )
    assert evidence["match_id"] == TARGET_MATCH_ID
    assert evidence["nowscore_id"] == 2912253
    assert evidence["source_provider"] == "nowscore"
    assert evidence["source_cutoff_at"] < evidence["kickoff_at"]
    home_rows = evidence["recent_matches"]["home_team"]
    away_rows = evidence["recent_matches"]["away_team"]
    assert len(home_rows) == 30
    assert len(away_rows) == 30
    assert all(
        HOME_PROVIDER_ID in {str(row["home_team_id"]), str(row["away_team_id"])}
        for row in home_rows
    )
    assert all(
        AWAY_PROVIDER_ID in {str(row["home_team_id"]), str(row["away_team_id"])}
        for row in away_rows
    )


def test_target_bridge_enters_the_pre_kickoff_allsvenskan_network() -> None:
    fixture = _target_fixture()
    identity = _read("data/football_data/current_match_identity_evidence.json")
    mappings = _read("data/football_data/verified_project_provider_crosswalk.json")["mappings"]
    registry = _read("data/football_data/competition_coverage_registry.json")
    direct_historical_meeting = {
        "canonical_match_id": (
            "match:competition:sweden-allsvenskan:2026-04-17:"
            "team:sweden:degerfors-if:team:sweden:if-elfsborg"
        ),
        "competition_id": COMPETITION_ID,
        "home_team_id": AWAY_CANONICAL_ID,
        "away_team_id": HOME_CANONICAL_ID,
        "kickoff_at": "2026-04-17T18:00:00Z",
    }

    result = build_current_fixture_coverage(
        [fixture],
        [direct_historical_meeting],
        crosswalk_mappings=mappings,
        identity_matches=identity["matches"],
        competition_registry=registry,
    )
    target = result["fixtures"][0]

    assert target["identity_status"] == "resolved"
    assert target["home_team_id"] == HOME_CANONICAL_ID
    assert target["away_team_id"] == AWAY_CANONICAL_ID
    assert target["history_match_counts"] == {"home": 1, "away": 1}
    assert target["competition_status"] == "authoritative_history_available"
    assert target["status"] == "ready"
    assert result["both_teams_enter_network"] == 1


def test_committed_target_audit_evidence_reports_the_actual_history_counts() -> None:
    evidence = _read("data/football_data/fe_id_bridge1_evidence.json")

    assert evidence["task"] == "FE-ID-BRIDGE-1"
    assert evidence["status"] == "READY_FOR_ACCEPTANCE"
    assert evidence["scope"]["fixture_count"] == 1
    assert evidence["scope"]["fixture_id"] == TARGET_MATCH_ID
    assert evidence["historical_validation"]["home"]["usable_match_count"] == 16
    assert evidence["historical_validation"]["away"]["usable_match_count"] == 16
    assert evidence["historical_validation"]["same_network"] is True
    assert evidence["historical_validation"]["post_kickoff_rows_used"] == 0
    assert all(evidence["checks"].values())
