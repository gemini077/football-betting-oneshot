from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from scripts.football_context_identity_feasibility_audit import (
    ApiFootballClient as LegacyApiFootballClient,
    _backing_schedule_expected_dates,
    _backing_schedule_urls,
    _fetch_nowscore_alias_rows,
    build_nowscore_alias_index,
    nowscore_alias_evidence,
)
from scripts.football_data.multi_source_evidence_spine import (
    ApiFootballSharedClient,
    EntityRegistry,
    bind_fixture_identity,
    build_enrichment_snapshot,
    read_league_coverage,
    run_enrichment_cohort,
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
SC1_URL = "https://live.nowscore.com/data/sc1.js"


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


def test_enrichment_uses_persisted_identity_before_alias_surface_backfill(tmp_path: Path):
    fixture = {
        "nowscore_id": 123,
        "matchId": "123",
        "matchDate": "2026-09-13",
        "matchTime": "03:00",
        "nowscore_source_identity": {
            "status": "EXACT",
            "nowscore_id": 123,
            "home_team_id": 101,
            "away_team_id": 202,
            "home_team_en": "Home FC",
            "away_team_en": "Away FC",
            "kickoff_local": "2026-09-13T03:00:00+08:00",
            "calendar_date": "2026-09-13",
            "source_surface": "https://live.nowscore.com/schedule.aspx?f=sc1",
            "backing_data_url": "https://live.nowscore.com/data/sc1.js",
        },
    }
    cohort_path = tmp_path / "cohort.json"
    cohort_path.write_text(
        json.dumps({
            "status": "READY",
            "source": "nowscore_public_jc",
            "business_date": "2026-09-12",
            "fixtures": [fixture],
        }),
        encoding="utf-8",
    )

    with patch(
        "scripts.football_context_identity_feasibility_audit._fetch_nowscore_alias_rows",
        side_effect=AssertionError("persisted identity must avoid refetch"),
    ), patch(
        "scripts.nowscore_prematch_evidence.NowscorePublicClient.fetch",
        return_value=SimpleNamespace(body=""),
    ):
        report = run_enrichment_cohort(
            cohort_path=cohort_path,
            as_of="2026-09-12T12:00:00+08:00",
            registry_path=tmp_path / "registry.json",
        )

    assert report["nowscore"] == {
        "persisted_identity_count": 1,
        "strict_backfill_fixture_count": 0,
        "alias_surface_request_count": 0,
    }
    assert report["snapshots"][0]["identity"]["nowscore_home_team_id"] == "101"


def test_next_day_sc1_alias_surface_uses_exact_row_and_source_kickoff():
    cohort_fixture = {
        "matchDate": "2026-09-12",
        "matchTime": "00:30",
        "a32_corroboration": {"backing_data_url": SC1_URL, "calendar_date": "2026-09-12"},
    }
    assert _backing_schedule_urls((cohort_fixture,)) == (SC1_URL,)
    assert _backing_schedule_expected_dates((cohort_fixture,)) == {SC1_URL: "2026-09-12"}
    values = [
        7001, 1, 101, 202, "主队", 0, "Source Home FC", "客队", 0, "Source Away FC",
        "00:30", "09-12", 0, 0, 0, None, None, None, 0, 0, 0, 0,
        "", "", "", 0, "", "", "", 0, 0, 0, 1,
    ]
    schedule_js = "A[0]=[" + ",".join("" if value is None else repr(value) for value in values) + "];"
    fetched = []

    def fake_fetch(url):
        fetched.append(url)
        return schedule_js.encode("utf-8")

    with patch("scripts.football_context_identity_feasibility_audit._fetch_bytes", side_effect=fake_fetch):
        rows, error = _fetch_nowscore_alias_rows(
            schedule_urls=(SC1_URL,),
            expected_dates={SC1_URL: "2026-09-12"},
        )

    assert error is None
    assert len(fetched) == 1
    assert fetched[0].startswith(f"{SC1_URL}?")
    index = build_nowscore_alias_index(rows)
    evidence = nowscore_alias_evidence(
        {"nowscore_id": 7001, "kickoff": "2026-09-12T00:30:00+08:00"},
        index,
    )
    assert evidence["status"] == "BOUND"
    assert evidence["aliases"] == {"home": ("Source Home FC",), "away": ("Source Away FC",)}
    assert evidence["nowscore_home_team_id"] == 101
    assert evidence["nowscore_away_team_id"] == 202
    assert evidence["nowscore_schedule_kickoff"] == "2026-09-12T00:30+08:00"
    assert evidence["source_surface"] == "nowscore_schedule_sc1"
    assert evidence["backing_data_url"] == SC1_URL


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


def test_empty_registry_bootstrap_requires_counterpart_and_competition_context():
    registry = EntityRegistry()
    name_only = bind_fixture_identity(SOURCE, ALIASES, [_api_row()], registry=registry)
    assert name_only["reason_code"] == "NAME_CANDIDATE_ONLY"

    bound = bind_fixture_identity(
        SOURCE,
        ALIASES,
        [_api_row()],
        registry=registry,
        allow_bootstrap=True,
    )
    assert bound["status"] == "BOUND"
    assert bound["evidence"]["counterpart_pair"] is True
    assert bound["evidence"]["competition_context"] is True
    assert bound["evidence"]["country_context"] is True

    registry.accept_team("NS-H", bound["api_home_team_id"], aliases=("Home FC",), evidence=("bootstrap",))
    registry.accept_team("NS-A", bound["api_away_team_id"], aliases=("Away FC",), evidence=("bootstrap",))
    registry.accept_competition(25, bound["api_league_id"], bound["season"], country="England", evidence=("bootstrap",))
    registry.accept_fixture(
        123,
        bound["api_fixture_id"],
        nowscore_home_team_id="NS-H",
        nowscore_away_team_id="NS-A",
        api_home_team_id=bound["api_home_team_id"],
        api_away_team_id=bound["api_away_team_id"],
        nowscore_sclass_id=25,
        api_league_id=bound["api_league_id"],
        season=bound["season"],
        kickoff=bound["kickoff"],
        evidence=("bootstrap",),
    )
    reused = bind_fixture_identity(SOURCE, {}, [_api_row()], registry=registry)
    assert reused["reason_code"] == "PERSISTED_ACCEPTED_MAPPING"

    weak_row = _api_row()
    weak_row["league"].pop("country")
    weak = bind_fixture_identity(
        SOURCE,
        ALIASES,
        [weak_row],
        registry=EntityRegistry(),
        allow_bootstrap=True,
    )
    assert weak["status"] == "UNBOUND"
    assert weak["reason_code"] == "NAME_CANDIDATE_ONLY"


class _Response:
    def __init__(self, payload, *, headers=None, status=None):
        self.payload = payload
        self.headers = headers or {}
        self.status = status

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
            return _Response(
                {"errors": {"token": "invalid"}, "response": []},
                headers={"X-RateLimit-Requests-Remaining": "0"},
                status=429,
            )
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

    client = ApiFootballSharedClient("SECRET_TOKEN", opener=opener, max_requests=100, min_request_interval=0)
    provider_error = client.get("/leagues", {"id": 500, "season": 2026})
    assert provider_error["reason_code"] == "API_PROVIDER_ERROR"
    assert provider_error["response_state"] == "PROVIDER_ERROR"
    assert provider_error["http_status"] == 429
    assert provider_error["rate_limit"] == {"x-ratelimit-requests-remaining": "0"}
    assert "SECRET_TOKEN" not in json.dumps(provider_error)

    no_coverage = read_league_coverage(
        client.get("/leagues", {"id": 501, "season": 2026}), league_id=501, season=2026
    )
    assert no_coverage["reason_code"] == "API_LEAGUE_SEASON_NO_COVERAGE"
    provider_coverage = read_league_coverage(provider_error, league_id=500, season=2026)
    assert provider_coverage["provenance"]["http_status"] == 429
    assert provider_coverage["provenance"]["provider_error_keys"] == ["token"]

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

    client = ApiFootballSharedClient("SECRET_TOKEN", opener=opener, min_request_interval=0)
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
    assert snapshot["fields"]["injuries"]["value"]["players"][0]["player_name"] == "Player Secret"
    serialized = json.dumps(snapshot, ensure_ascii=False)
    assert "Player Secret" in serialized
    assert "SECRET_TOKEN" not in serialized
    assert "<html" not in serialized.casefold()


def test_prematch_stats_use_team_history_and_sidelined_keeps_player_evidence():
    paths = []

    def opener(request, timeout):
        parsed = urlparse(request.full_url)
        paths.append(parsed.path)
        query = parse_qs(parsed.query)
        if parsed.path == "/standings":
            payload = {"errors": [], "response": []}
        elif parsed.path == "/injuries":
            payload = {"errors": [], "response": [
                {"player": {"id": 11, "name": "Player A", "position": "F"}, "team": {"id": 1, "name": "Home FC"}, "fixture": {"id": 456}, "type": "Missing", "reason": "Hamstring"},
                {"player": {"id": 12, "name": "Player B", "position": "D"}, "team": {"id": 2, "name": "Away FC"}, "fixture": {"id": 456}, "type": "Suspension", "reason": "Red card"},
            ]}
        elif parsed.path == "/sidelined":
            player_id = int(query["player"][0])
            payload = {"errors": [], "response": [{
                "player": {"id": player_id, "name": "Player A" if player_id == 11 else "Player B"},
                "sidelined": [{"type": "Injury", "reason": "Hamstring", "start": "2026-08-01", "end": "2026-08-10"}],
            }]}
        elif parsed.path == "/coachs":
            payload = {"errors": [], "response": [{"coach": {"id": 7, "name": "Coach A", "career": []}}]}
        elif parsed.path == "/fixtures/lineups":
            payload = {"errors": [], "response": []}
        elif parsed.path == "/teams/statistics":
            payload = {"errors": [], "response": [{
                "team": {"id": int(query["team"][0]), "name": "Home FC"},
                "league": {"id": 39, "season": 2026},
                "fixtures": {"played": {"total": 4}, "wins": {"total": 3}},
                "goals": {"for": {"total": 8}, "against": {"total": 2}},
            }]}
        else:
            raise AssertionError(f"unexpected endpoint: {parsed.path}")
        return _Response(payload)

    client = ApiFootballSharedClient("SECRET_TOKEN", opener=opener, min_request_interval=0)
    binding = {
        "status": "BOUND",
        "api_fixture_id": 456,
        "api_home_team_id": 1,
        "api_away_team_id": 2,
        "api_league_id": 39,
        "season": 2026,
    }
    coverage = {
        "status": "UNAVAILABLE",
        "coverage": {"standings": None, "injuries": None, "lineups": None, "statistics": None},
    }
    snapshot = build_enrichment_snapshot(
        SOURCE,
        binding,
        client,
        coverage=coverage,
        as_of=datetime.fromisoformat("2026-09-11T08:00:00+08:00"),
    )

    assert "/fixtures/statistics" not in paths
    assert {"/standings", "/injuries", "/sidelined", "/coachs", "/fixtures/lineups", "/teams/statistics"} <= set(paths)
    assert paths.count("/teams/statistics") == 2
    assert snapshot["fields"]["standings"]["state"] == "EMPTY"
    assert snapshot["fields"]["stats"]["state"] == "PRESENT"
    assert snapshot["fields"]["stats"]["value"][0]["fixtures"]["played"]["total"] == 4
    assert snapshot["fields"]["injuries"]["value"]["players"][0] == {
        "player_id": 11,
        "player_name": "Player A",
        "position": "F",
        "team_id": 1,
        "team_name": "Home FC",
        "type": "Missing",
        "reason": "Hamstring",
        "fixture_id": 456,
    }
    assert snapshot["fields"]["suspensions"]["value"]["players"][0]["player_id"] == 12
    assert snapshot["fields"]["sidelined"]["state"] == "PRESENT"
    assert snapshot["fields"]["sidelined"]["value"][0]["player_id"] == 11


def test_rate_limit_backoff_and_minute_pacing_use_stdlib_clock():
    now = [0.0]
    sleeps = []
    calls = []

    def sleep(seconds):
        sleeps.append(seconds)
        now[0] += seconds

    def opener(request, timeout):
        calls.append(request.full_url)
        if len(calls) == 1:
            return _Response(
                {"errors": {"rateLimit": "slow down"}, "response": []},
                headers={"Retry-After": "9"},
                status=200,
            )
        return _Response({"errors": [], "response": []}, status=200)

    client = ApiFootballSharedClient(
        "SECRET_TOKEN",
        opener=opener,
        min_request_interval=6,
        sleep=sleep,
        clock=lambda: now[0],
    )

    assert client.get("/leagues", {"id": 1, "season": 2026})["reason_code"] == "API_PROVIDER_ERROR"
    assert client.get("/leagues", {"id": 2, "season": 2026})["ok"] is True
    assert sleeps == [9]
    assert client.rate_limit_backoff_count == 1
    assert client.rate_limit_wait_count == 1
    assert client.rate_limit_wait_seconds == 9
