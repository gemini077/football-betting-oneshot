from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from scripts.football_data.providers.football_data_org import (
    CredentialMissingError,
    FootballDataOrgClient,
    FootballDataOrgRecentFormRoute,
    RequestAccounting,
    bridge_fixture,
    build_provider_recent_form,
    normalize_team_matches,
)
from scripts.recent_form_cache import load_football_data_org_recent_form


ROOT = Path(__file__).resolve().parents[1]
SAMPLE_PATH = ROOT / "data" / "football_data" / "pred_avail_2" / "fixture_contract_samples.json"


def _provider_match(
    match_id: int,
    kickoff: str,
    *,
    home_id: int = 101,
    away_id: int = 202,
    status: str = "FINISHED",
    home_goals: int | None = 2,
    away_goals: int | None = 1,
    last_updated: str = "2026-08-29T10:00:00Z",
) -> dict:
    return {
        "id": match_id,
        "utcDate": kickoff,
        "status": status,
        "lastUpdated": last_updated,
        "competition": {"id": 2021, "code": "PL", "name": "Premier League"},
        "homeTeam": {"id": home_id, "name": f"Provider Home {home_id}"},
        "awayTeam": {"id": away_id, "name": f"Provider Away {away_id}"},
        "score": {"fullTime": {"home": home_goals, "away": away_goals}},
    }


def _target(kickoff: str = "2026-08-30T14:00:00+00:00") -> dict:
    return {
        "match_id": "500-sample-1",
        "competition_id": "competition:england-premier-league",
        "competition": "Premier League",
        "home": "本地展示主队",
        "away": "本地展示客队",
        "kickoff": kickoff,
    }


def _coverage_manifest() -> dict:
    return {
        "contract_version": "football_data_org_coverage.v1",
        "competitions": [
            {
                "competition_key": "england-premier-league",
                "canonical_competition_id": "competition:england-premier-league",
                "canonical_name": "Premier League",
                "aliases": ["Premier League", "英格兰超级联赛"],
                "provider_competition_code": "PL",
                "provider_competition_name": "Premier League",
                "free_tier": True,
            },
        ],
    }


def _history_payload() -> dict:
    rows = []
    for index in range(1, 7):
        date = f"2026-08-{index + 10:02d}T12:00:00Z"
        rows.append(_provider_match(index, date, home_id=101, away_id=300 + index))
        rows.append(_provider_match(100 + index, date, home_id=400 + index, away_id=202))
    rows.extend(
        [
            _provider_match(999, "2026-08-30T15:00:00Z", home_id=101, away_id=303),
            _provider_match(1000, "2026-08-20T12:00:00Z", home_id=101, away_id=304, status="SCHEDULED"),
            _provider_match(1001, "2026-08-19T12:00:00Z", home_id=101, away_id=305, home_goals=None),
            _provider_match(1002, "2026-08-18T12:00:00Z", home_id=999, away_id=888),
        ]
    )
    return {"matches": rows}


def test_missing_token_never_calls_transport(monkeypatch):
    monkeypatch.delenv("FOOTBALL_DATA_ORG_TOKEN", raising=False)
    calls: list[str] = []

    def transport(url: str, headers: dict[str, str]):
        calls.append(url)
        raise AssertionError("network transport must not run without a token")

    accounting = RequestAccounting()
    client = FootballDataOrgClient(
        token=None,
        transport=transport,
        accounting=accounting,
    )

    with pytest.raises(CredentialMissingError):
        client.get_json("/competitions/PL/matches", {"dateFrom": "2026-08-30", "dateTo": "2026-08-30"})

    assert calls == []
    assert accounting.requests == 0
    assert accounting.cache_misses == 1
    assert accounting.credential_blocks == 1


def test_fixture_bridge_uses_exact_utc_kickoff_and_preserves_provider_identity():
    result = bridge_fixture(
        _target("2026-08-30T22:00:00+08:00"),
        [_provider_match(7001, "2026-08-30T14:00:00Z", status="TIMED", last_updated="2026-08-29T12:00:00Z")],
        provider_competition_code="PL",
        now="2026-08-29T16:00:00Z",
    )

    assert result["status"] == "BRIDGED"
    assert result["provider_fixture_id"] == "7001"
    assert result["provider_home_team_id"] == "101"
    assert result["provider_away_team_id"] == "202"
    assert result["identity_scope"] == "provider_scoped"
    assert result["canonical_home_team_id"] is None
    assert result["source_fixture_state"]["status"] == "TIMED"
    assert result["source_refs"] == ["https://api.football-data.org/v4/matches/7001"]


def test_fixture_bridge_fails_closed_on_ambiguous_exact_candidates():
    candidates = [
        _provider_match(7001, "2026-08-30T14:00:00Z", status="TIMED", last_updated="2026-08-29T12:00:00Z"),
        _provider_match(7002, "2026-08-30T14:00:00Z", status="TIMED", last_updated="2026-08-29T12:00:00Z"),
    ]
    result = bridge_fixture(_target(), candidates, provider_competition_code="PL", now="2026-08-29T16:00:00Z")

    assert result["status"] == "BLOCKED"
    assert result["reason_code"] == "AMBIGUOUS_FIXTURE"
    assert result["provider_fixture_id"] is None
    assert result["candidate_provider_fixture_ids"] == ["7001", "7002"]


def test_provider_history_filters_future_non_finished_incomplete_and_other_teams():
    normalized = normalize_team_matches(
        _history_payload(),
        provider_team_id="101",
        cutoff_at="2026-08-30T14:00:00Z",
        fetched_at="2026-08-29T16:00:00Z",
        provider_competition_code="PL",
        source_url="https://api.football-data.org/v4/teams/101/matches",
    )

    assert len(normalized) == 6
    assert all(row["provider_team_id"] == "101" for row in normalized)
    assert all(row["kickoff_at"] < "2026-08-30T14:00:00Z" for row in normalized)
    assert all(row["provider_competition_code"] == "PL" for row in normalized)
    assert all(row["canonical_team_id"] is None for row in normalized)

    home_records = [row for row in normalized]
    away_records = [
        {
            **row,
            "provider_team_id": "202",
            "team_id": "football-data.org:team:202",
            "venue": "away" if row["venue"] == "home" else "home",
        }
        for row in normalized
    ]
    form = build_provider_recent_form(
        home_records,
        away_records,
        home_provider_team_id="101",
        away_provider_team_id="202",
        cutoff_at="2026-08-30T14:00:00Z",
        captured_at="2026-08-29T16:00:00Z",
        fixture_bridge={
            "provider_fixture_id": "7001",
            "provider_competition_code": "PL",
            "provider_home_team_id": "101",
            "provider_away_team_id": "202",
            "source_refs": ["https://api.football-data.org/v4/matches/7001"],
        },
    )

    assert form["status"] == "FULL"
    assert all(form["recent_form"][key]["matches"] > 0 for key in ("home_overall", "home_home", "away_overall", "away_away"))
    assert form["provenance"]["identity_scope"] == "provider_scoped"
    assert form["provenance"]["canonical_historical_identity"] is None
    assert all(row["kickoff_at"] < "2026-08-30T14:00:00Z" for row in form["records"])


def test_route_reuses_same_day_competition_and_team_responses(tmp_path):
    target_a = _target("2026-08-30T14:00:00Z")
    target_a["match_id"] = "fixture-a"
    target_b = _target("2026-08-30T16:00:00Z")
    target_b["match_id"] = "fixture-b"
    target_b["home"] = "本地展示主队 B"
    target_b["away"] = "本地展示客队 B"
    competition_matches = [
        _provider_match(7001, "2026-08-30T14:00:00Z", status="TIMED", last_updated="2026-08-29T12:00:00Z"),
        _provider_match(7002, "2026-08-30T16:00:00Z", status="TIMED", last_updated="2026-08-29T12:00:00Z"),
    ]
    team_payload = _history_payload()
    team_payload_away = {
        "matches": [
            _provider_match(row["id"], row["utcDate"], home_id=404 + row["id"], away_id=202)
            for row in team_payload["matches"]
            if row["status"] == "FINISHED" and row["score"]["fullTime"]["home"] is not None
        ]
    }

    def transport(url: str, headers: dict[str, str]):
        parsed = urlparse(url)
        if parsed.path == "/v4/competitions/PL/matches":
            return {"matches": competition_matches}
        if parsed.path == "/v4/teams/101/matches":
            return team_payload
        if parsed.path == "/v4/teams/202/matches":
            return team_payload_away
        raise AssertionError(url)

    route = FootballDataOrgRecentFormRoute(
        coverage_manifest=_coverage_manifest(),
        token="TOKEN",
        transport=transport,
        cache_root=tmp_path,
    )
    result_a = route.get_recent_form(target_a, target_a, now="2026-08-29T16:00:00Z")
    result_b = route.get_recent_form(target_b, target_b, now="2026-08-29T16:00:00Z")

    assert result_a["status"] == "FULL"
    assert result_b["status"] == "FULL"
    assert result_a["provider_fixture_id"] == "7001"
    assert result_b["provider_fixture_id"] == "7002"
    assert route.accounting.requests == 3
    assert route.accounting.cache_hits == 3
    assert route.accounting.endpoint_counts == {
        "competitions/PL/matches": 1,
        "teams/101/matches": 1,
        "teams/202/matches": 1,
    }


def test_route_reports_credential_block_without_network(tmp_path):
    calls: list[str] = []

    def transport(url: str, headers: dict[str, str]):
        calls.append(url)
        raise AssertionError("live transport must not run")

    route = FootballDataOrgRecentFormRoute(
        coverage_manifest=_coverage_manifest(),
        token=None,
        transport=transport,
        cache_root=tmp_path,
    )
    result = route.get_recent_form(_target(), _target(), now="2026-08-29T16:00:00Z")

    assert result["status"] == "SOURCE_UNAVAILABLE"
    assert "LIVE_VALIDATION_BLOCKED_BY_CREDENTIAL" in result["reason_codes"]
    assert result["final_prediction_eligible"] is False
    assert calls == []
    assert route.accounting.requests == 0


def test_existing_recent_form_loader_projects_provider_route_contract(tmp_path):
    history = _history_payload()

    def transport(url: str, headers: dict[str, str]):
        parsed = urlparse(url)
        if parsed.path == "/v4/competitions/PL/matches":
            return {
                "matches": [
                    _provider_match(7001, "2026-08-30T14:00:00Z", status="TIMED", last_updated="2026-08-29T12:00:00Z")
                ]
            }
        if parsed.path == "/v4/teams/101/matches":
            return history
        if parsed.path == "/v4/teams/202/matches":
            return {
                "matches": [
                    _provider_match(row["id"], row["utcDate"], home_id=500 + row["id"], away_id=202)
                    for row in history["matches"]
                    if row["status"] == "FINISHED" and row["score"]["fullTime"]["home"] is not None
                ]
            }
        raise AssertionError(url)

    route = FootballDataOrgRecentFormRoute(
        coverage_manifest=_coverage_manifest(),
        token="TOKEN",
        transport=transport,
        cache_root=tmp_path,
    )
    loaded = load_football_data_org_recent_form(
        _target(),
        _target(),
        "2026-08-30T14:00:00Z",
        "2026-08-29T16:00:00Z",
        route=route,
    )

    assert loaded is not None
    assert loaded["source"] == "football_data_org_recent_form"
    assert loaded["recent_form"]["home_overall"]["matches"] > 0
    assert loaded["provenance"]["canonical_historical_identity"] is None


def test_contract_fixture_sample_is_explicitly_non_production():
    payload = json.loads(SAMPLE_PATH.read_text(encoding="utf-8"))
    assert payload["fixture_sample_role"] == "offline_contract_only"
    assert payload["not_production_evidence"] is True
