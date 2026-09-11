from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from scripts.football_context_identity_feasibility_audit import ApiFootballClient as LegacyApiFootballClient
from scripts.football_data.multi_source_evidence_spine import (
    ApiFootballSharedClient,
    EntityRegistry,
    bind_fixture_identity,
    build_enrichment_snapshot,
    read_league_coverage,
)


SOURCE = {
    "nowscore_id": 123,
    "kickoff": "2026-09-11T18:00:00+08:00",
    "nowscore_home_team_id": "NS-H",
    "nowscore_away_team_id": "NS-A",
    "nowscore_sclass_id": 25,
    "season": 2026,
}
ALIASES = {"home": ("Home FC",), "away": ("Away FC",)}


def _api_row(*, home="Home FC", away="Away FC", fixture_id=456):
    return {
        "fixture": {
            "id": fixture_id,
            "date": "2026-09-11T10:00:00+00:00",
            "status": {"short": "NS"},
        },
        "teams": {
            "home": {"id": 1, "name": home},
            "away": {"id": 2, "name": away},
        },
        "league": {
            "id": 39,
            "name": "League A",
            "country": "England",
            "type": "League",
            "season": 2026,
            "round": "Regular Season - 1",
        },
    }


def _proven_registry() -> EntityRegistry:
    registry = EntityRegistry()
    registry.accept_team("NS-H", 1, aliases=("Home FC",), evidence=("reviewed_pair",))
    registry.accept_team("NS-A", 2, aliases=("Away FC",), evidence=("reviewed_pair",))
    registry.accept_competition(25, 39, 2026, country="England", evidence=("reviewed_competition",))
    return registry


def test_name_candidate_alone_never_binds_and_reviewed_ids_bind(tmp_path: Path):
    rejected = bind_fixture_identity(SOURCE, ALIASES, [_api_row()], registry=EntityRegistry())
    assert rejected["status"] == "UNBOUND"
    assert rejected["reason_code"] == "NAME_CANDIDATE_ONLY"

    registry = _proven_registry()
    bound = bind_fixture_identity(SOURCE, ALIASES, [_api_row()], registry=registry)
    assert bound["status"] == "BOUND"
    assert bound["api_fixture_id"] == 456
    assert bound["api_home_team_id"] == 1
    assert bound["api_away_team_id"] == 2
    assert bound["api_league_id"] == 39
    assert bound["season"] == 2026

    path = tmp_path / "entity-registry.json"
    registry.save(path)
    reloaded = EntityRegistry.load(path)
    assert reloaded.lookup_team("NS-H")["api_team_id"] == 1
    assert reloaded.lookup_competition(25, 2026)["api_league_id"] == 39


def test_orientation_and_season_mismatch_fail_closed():
    registry = _proven_registry()
    swapped = bind_fixture_identity(
        SOURCE,
        ALIASES,
        [_api_row(home="Away FC", away="Home FC")],
        registry=registry,
    )
    assert swapped["status"] == "UNBOUND"
    assert swapped["reason_code"] == "ORIENTATION_MISMATCH"

    wrong_season = _api_row()
    wrong_season["league"]["season"] = 2025
    result = bind_fixture_identity(SOURCE, ALIASES, [wrong_season], registry=registry)
    assert result["status"] == "UNBOUND"
    assert result["reason_code"] == "SEASON_MISMATCH"


class _Response:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


def test_leagues_response_error_is_not_reported_as_no_coverage_and_cache_is_shared():
    requests = []

    def opener(request, timeout):
        requests.append(request)
        query = parse_qs(urlparse(request.full_url).query)
        if query.get("id") == ["500"]:
            return _Response({"errors": {"token": "invalid"}, "response": []})
        if query.get("id") == ["501"]:
            return _Response({"errors": [], "response": []})
        return _Response({
            "errors": [],
            "response": [{
                "league": {
                    "id": 39,
                    "name": "League A",
                    "country": "England",
                    "season": 2026,
                    "coverage": {
                        "standings": True,
                        "injuries": False,
                        "fixtures": {"lineups": True, "statistics": True},
                    },
                }
            }],
        })

    client = ApiFootballSharedClient("SECRET_TOKEN", opener=opener, max_requests=100)
    provider_error = client.get("/leagues", {"id": 500, "season": 2026})
    assert provider_error["reason_code"] == "API_PROVIDER_ERROR"
    assert provider_error["response_state"] == "PROVIDER_ERROR"
    assert "SECRET_TOKEN" not in json.dumps(provider_error)

    no_coverage = read_league_coverage(
        client.get("/leagues", {"id": 501, "season": 2026}), league_id=501, season=2026
    )
    assert no_coverage["reason_code"] == "API_LEAGUE_SEASON_NO_COVERAGE"

    result = client.get("/leagues", {"id": 39, "season": 2026})
    assert read_league_coverage(result, league_id=39, season=2026)["coverage"] == {
        "standings": True,
        "injuries": False,
        "lineups": True,
        "statistics": True,
    }
    nested = read_league_coverage(
        {
            "ok": True,
            "payload": {
                "response": [{
                    "league": {"id": 39, "name": "League A", "type": "League"},
                    "country": {"name": "England"},
                    "seasons": [{
                        "year": 2026,
                        "coverage": {"standings": True, "injuries": False, "fixtures": {"lineups": True, "statistics": True}},
                    }],
                }],
            },
        },
        league_id=39,
        season=2026,
    )
    assert nested["status"] == "READ"
    client.get("/leagues", {"id": 39, "season": 2026})
    assert len(requests) == 3
    assert client.cache_hits == 1
    assert client.endpoint_counts["/leagues"] == 3


def test_issue_286_client_separates_provider_error_from_empty_league_response():
    def opener(request, timeout):
        return _Response({"errors": {"rateLimit": "quota"}, "response": []})

    client = LegacyApiFootballClient("SECRET_TOKEN", opener=opener)
    result = client.get("/leagues", {"id": 39, "season": 2026})
    assert result["reason_code"] == "API_PROVIDER_ERROR"
    assert result["response_state"] == "PROVIDER_ERROR"


def test_snapshot_has_field_provenance_without_raw_provider_body():
    def opener(request, timeout):
        path = urlparse(request.full_url).path
        if path == "/standings":
            payload = {
                "errors": [],
                "response": [{
                    "league": {
                        "standings": [[{
                            "rank": 1,
                            "team": {"id": 1, "name": "Home FC"},
                            "points": 10,
                            "all": {"played": 4, "win": 3, "draw": 1, "lose": 0,
                                    "goals": {"for": 8, "against": 2}},
                            "goalsDiff": 6,
                        }]]
                    }
                }],
            }
        elif path == "/injuries":
            payload = {"errors": [], "response": [
                {"player": {"id": 11, "name": "Player Secret"}, "team": {"id": 1, "name": "Home FC"}, "type": "Missing", "reason": "Injury"},
                {"player": {"id": 12, "name": "Player Secret 2"}, "team": {"id": 2, "name": "Away FC"}, "type": "Suspended", "reason": "Red card"},
            ]}
        elif path == "/coachs":
            payload = {"errors": [], "response": [{"coach": {"id": 7, "name": "Coach A", "career": [{"team": {"id": 1, "name": "Home FC"}, "start": "2024-01-01"}]}}]}
        elif path == "/fixtures/lineups":
            payload = {"errors": [], "response": [{"team": {"id": 1, "name": "Home FC"}, "startXI": [{"player": {"id": 1}}], "substitutes": []}]}
        else:
            payload = {"errors": [], "response": [{"team": {"id": 1, "name": "Home FC"}, "statistics": [{"type": "Shots on Goal", "value": 3}]}]}
        return _Response(payload)

    client = ApiFootballSharedClient("SECRET_TOKEN", opener=opener)
    binding = {
        "status": "BOUND",
        "api_fixture_id": 456,
        "api_home_team_id": 1,
        "api_away_team_id": 2,
        "api_league_id": 39,
        "season": 2026,
    }
    coverage = {
        "status": "READ",
        "coverage": {"standings": True, "injuries": True, "lineups": True, "statistics": True},
    }
    source_before = dict(SOURCE)
    snapshot = build_enrichment_snapshot(SOURCE, binding, client, coverage=coverage)

    assert SOURCE == source_before
    assert snapshot["fields"]["standings"]["state"] == "PRESENT"
    assert snapshot["fields"]["injuries"]["value"]["injury_count"] == 1
    assert snapshot["fields"]["injuries"]["value"]["suspension_count"] == 1
    assert snapshot["fields"]["coach"]["state"] == "PRESENT"
    assert snapshot["fields"]["lineup"]["state"] == "PRESENT"
    assert snapshot["fields"]["stats"]["state"] == "PRESENT"
    serialized = json.dumps(snapshot, ensure_ascii=False)
    assert "Player Secret" not in serialized
    assert "SECRET_TOKEN" not in serialized
    assert "<html" not in serialized.casefold()
