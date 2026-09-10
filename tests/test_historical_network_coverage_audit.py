from __future__ import annotations

from scripts.football_data.audit_historical_network_coverage import (
    build_competition_registry_lookup,
    build_current_fixture_coverage,
    competition_network_coverage,
    historical_identity_diagnostics,
    normalize_name,
)


def historical_row(
    match_id: str,
    home: str,
    away: str,
    *,
    competition: str = "competition:test",
    season: str = "season:test:2026",
    kickoff: str = "2026-01-01T12:00:00Z",
) -> dict:
    return {
        "canonical_match_id": match_id,
        "competition_id": competition,
        "season_id": season,
        "home_team_id": home,
        "away_team_id": away,
        "kickoff_at": kickoff,
        "home_goals": 1,
        "away_goals": 0,
        "eligible_for_team_strength": True,
        "source_conflict": False,
        "duplicate_status": "unique",
        "entity_type": "club",
        "match_type": "league",
    }


def test_connected_coverage_reports_largest_component_and_edge_coverage() -> None:
    rows = [
        historical_row("m1", "team:a", "team:b"),
        historical_row("m2", "team:b", "team:c"),
        historical_row("m3", "team:d", "team:e"),
    ]

    coverage = competition_network_coverage(rows)["competition:test"]

    assert coverage["match_count"] == 3
    assert coverage["team_count"] == 5
    assert coverage["component_count"] == 2
    assert coverage["largest_component_team_count"] == 3
    assert coverage["largest_component_match_count"] == 2
    assert coverage["connected_team_coverage"] == 0.6
    assert coverage["connected_match_coverage"] == 2 / 3


def test_identity_blocker_is_not_counted_as_history_blocker() -> None:
    rows = [
        historical_row("m1", "team:home", "team:opponent"),
        historical_row("m2", "team:opponent", "team:away"),
    ]
    fixtures = [
        {
            "matchId": "500-target",
            "homeTeam": "Unmapped Home",
            "awayTeam": "Unmapped Away",
            "league": "Test League",
            "matchDate": "2026-02-01",
            "matchTime": "12:00",
        }
    ]

    result = build_current_fixture_coverage(
        fixtures,
        rows,
        crosswalk_mappings=[],
        identity_matches=[],
        competition_registry={"Test League": {"competition:test"}},
    )

    assert result["fixture_count"] == 1
    assert result["both_teams_enter_network"] == 0
    assert result["blocker_counts"] == {"identity": 1, "history": 0, "ready": 0}
    assert result["fixtures"][0]["status"] == "identity_blocker"


def test_competition_registry_lookup_reads_main_competitions_table() -> None:
    registry = {
        "competitions": [
            {
                "competition_key": "england-premier-league",
                "canonical_competition_id": None,
                "name": "Premier League",
                "observed_raw_names": ["\u82f1\u683c\u5170\u8d85\u7ea7\u8054\u8d5b"],
            }
        ]
    }

    lookup = build_competition_registry_lookup(registry)

    assert lookup[normalize_name("Premier League")] == {"competition:england-premier-league"}
    assert lookup[normalize_name("\u82f1\u683c\u5170\u8d85\u7ea7\u8054\u8d5b")] == {
        "competition:england-premier-league"
    }


def test_competition_status_separates_four_history_attribution_states() -> None:
    rows = [historical_row("m1", "team:home", "team:away", competition="competition:authoritative")]
    fixtures = [
        {
            "matchId": "500-authoritative",
            "homeTeam": "Unmapped Home",
            "awayTeam": "Unmapped Away",
            "league": "Authoritative League",
            "matchDate": "2026-02-01",
            "matchTime": "12:00",
        },
        {
            "matchId": "500-external",
            "homeTeam": "Unmapped Home",
            "awayTeam": "Unmapped Away",
            "league": "External Source League",
            "matchDate": "2026-02-01",
            "matchTime": "12:00",
        },
        {
            "matchId": "500-known",
            "homeTeam": "Unmapped Home",
            "awayTeam": "Unmapped Away",
            "league": "Known League",
            "matchDate": "2026-02-01",
            "matchTime": "12:00",
        },
        {
            "matchId": "500-unresolved",
            "homeTeam": "Unmapped Home",
            "awayTeam": "Unmapped Away",
            "league": "Unregistered League",
            "matchDate": "2026-02-01",
            "matchTime": "12:00",
        },
    ]
    registry = {
        "competitions": [
            {"competition_key": "authoritative", "name": "Authoritative League"},
            {
                "competition_key": "external",
                "name": "External Source League",
                "historical_result_sources": ["reviewed-source"],
                "source_record_count": 12,
            },
            {"competition_key": "known", "name": "Known League"},
        ]
    }

    result = build_current_fixture_coverage(
        fixtures,
        rows,
        crosswalk_mappings=[],
        identity_matches=[],
        competition_registry=registry,
    )

    assert [item["competition_status"] for item in result["fixtures"]] == [
        "authoritative_history_available",
        "historical_source_known_outside_authoritative_store",
        "competition_known_but_authoritative_history_unavailable",
        "competition_alias_or_context_unresolved",
    ]
    assert result["competition_history_gate"] == {
        "authoritative_history_available": 1,
        "competition_alias_or_context_unresolved": 1,
        "competition_known_but_authoritative_history_unavailable": 1,
        "historical_source_known_outside_authoritative_store": 1,
        "authoritative_history_competitions": {"competition:authoritative": 1},
        "known_but_authoritative_history_unavailable_competitions": {"competition:known": 1},
        "historical_source_known_outside_authoritative_store_competitions": {"competition:external": 1},
        "unresolved_competition_labels": {"Unregistered League": 1},
        "fixture_ids_by_competition_status": {
            "authoritative_history_available": ["500-authoritative"],
            "competition_alias_or_context_unresolved": ["500-unresolved"],
            "competition_known_but_authoritative_history_unavailable": ["500-known"],
            "historical_source_known_outside_authoritative_store": ["500-external"],
        },
    }


def test_verified_exact_pair_requires_one_shared_competition_context() -> None:
    rows = [
        historical_row("m1", "team:home", "team:opponent"),
        historical_row("m2", "team:opponent", "team:away"),
    ]
    fixtures = [
        {
            "matchId": "500-target",
            "homeTeam": "Home Alias",
            "awayTeam": "Away Alias",
            "league": "Test League",
            "matchDate": "2026-02-01",
            "matchTime": "12:00",
        }
    ]
    mappings = [
        {
            "provider": "500",
            "provider_team_name": "Home Alias",
            "canonical_team_id": "team:home",
            "competition": "competition:test",
            "verified": True,
        },
        {
            "provider": "500",
            "provider_team_name": "Away Alias",
            "canonical_team_id": "team:away",
            "competition": "competition:test",
            "verified": True,
        },
    ]

    result = build_current_fixture_coverage(
        fixtures,
        rows,
        crosswalk_mappings=mappings,
        identity_matches=[],
        competition_registry={"Test League": {"competition:test"}},
    )

    assert result["both_teams_enter_network"] == 1
    assert result["blocker_counts"] == {"identity": 0, "history": 0, "ready": 1}
    assert result["fixtures"][0]["status"] == "ready"


def test_verified_exact_pair_is_identity_blocked_when_competition_context_differs() -> None:
    rows = [
        historical_row("m1", "team:home", "team:opponent"),
        historical_row("m2", "team:opponent", "team:away"),
    ]
    fixture = {
        "matchId": "500-target",
        "homeTeam": "Home Alias",
        "awayTeam": "Away Alias",
        "league": "Other League",
        "matchDate": "2026-02-01",
        "matchTime": "12:00",
    }
    mappings = [
        {
            "provider": "500",
            "provider_team_name": "Home Alias",
            "canonical_team_id": "team:home",
            "competition": "competition:test",
            "verified": True,
        },
        {
            "provider": "500",
            "provider_team_name": "Away Alias",
            "canonical_team_id": "team:away",
            "competition": "competition:test",
            "verified": True,
        },
    ]

    result = build_current_fixture_coverage(
        [fixture],
        rows,
        crosswalk_mappings=mappings,
        identity_matches=[],
        competition_registry={"Other League": {"competition:other"}},
    )

    assert result["both_teams_enter_network"] == 0
    assert result["blocker_counts"] == {"identity": 1, "history": 0, "ready": 0}
    assert result["fixtures"][0]["status"] == "identity_blocker"


def test_historical_identity_diagnostics_surfaces_crosswalk_fragmentation() -> None:
    rows = [
        {
            **historical_row("m1", "team:alpha", "team:opponent"),
            "raw_home_team": "Alpha FC",
        },
        {
            **historical_row("m2", "team:alpha-variant", "team:opponent"),
            "raw_home_team": "Alpha",
        },
    ]
    cross_source_crosswalk = [
        {
            "provider": "openfootball",
            "provider_team_name": "Alpha FC",
            "canonical_team_id": "team:alpha",
            "competition": "competition:test",
            "verified": True,
        },
        {
            "provider": "openfootball",
            "provider_team_name": "Alpha",
            "canonical_team_id": "team:alpha",
            "competition": "competition:test",
            "verified": True,
        },
    ]

    result = historical_identity_diagnostics(rows, cross_source_crosswalk)

    assert result["fragmented_canonical_entity_count"] == 1
    assert result["fragmented_historical_team_id_count"] == 2
    assert result["fragmented_competitions"] == ["competition:test"]
    assert result["direct_conflict_mapping_count"] == 1
    assert result["historical_team_id_count"] == 3


def test_current_fixture_coverage_excludes_post_kickoff_history() -> None:
    rows = [
        historical_row(
            "prior",
            "team:home",
            "team:bridge",
            kickoff="2026-01-01T12:00:00Z",
        ),
        historical_row(
            "future",
            "team:bridge",
            "team:away",
            kickoff="2026-03-01T12:00:00Z",
        ),
    ]
    fixture = {
        "matchId": "500-target",
        "homeTeam": "Home Alias",
        "awayTeam": "Away Alias",
        "league": "Test League",
        "matchDate": "2026-02-01",
        "matchTime": "12:00",
    }
    mappings = [
        {
            "provider": "500",
            "provider_team_name": "Home Alias",
            "canonical_team_id": "team:home",
            "competition": "competition:test",
            "verified": True,
        },
        {
            "provider": "500",
            "provider_team_name": "Away Alias",
            "canonical_team_id": "team:away",
            "competition": "competition:test",
            "verified": True,
        },
    ]

    result = build_current_fixture_coverage(
        [fixture],
        rows,
        crosswalk_mappings=mappings,
        identity_matches=[],
        competition_registry={"Test League": {"competition:test"}},
    )

    assert result["blocker_counts"] == {"identity": 0, "history": 1, "ready": 0}
    assert result["fixtures"][0]["blocker_reason"] == "history_team_missing"
