from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from scripts.football_context_identity_feasibility_audit import (
    ApiFootballClient,
    bind_api_fixture_strict,
    build_audit_report,
    extract_nowscore_competition_bridge,
    read_api_league_coverage,
)


SOURCE_FIXTURE = {
    "nowscore_id": 123,
    "kickoff": "2026-09-11T18:00:00+08:00",
}
ALIASES = {"aliases": {"home": ("Home FC",), "away": ("Away FC",)}}


def _api_row(
    *,
    fixture_id: int = 456,
    kickoff: str = "2026-09-11T10:00:00+00:00",
    home: str = "Home FC",
    away: str = "Away FC",
    league_id: int | None = 39,
    season: int | None = 2026,
) -> dict:
    return {
        "fixture": {"id": fixture_id, "date": kickoff},
        "teams": {
            "home": {"id": 1, "name": home},
            "away": {"id": 2, "name": away},
        },
        "league": {
            "id": league_id,
            "name": "League A",
            "type": "League",
            "season": season,
        },
    }


def test_nowscore_direct_identifier_is_explicit_and_generic_text_is_ignored():
    direct = extract_nowscore_competition_bridge(
        '<script>var sclassID = 25;</script><div>积分排名 CUP_A</div>'
    )
    assert direct["status"] == "BOUND"
    assert direct["competition_id"] == 25
    assert direct["evidence_location"] == "analysis_page:inline_script:sclassID_assignment"

    link = extract_nowscore_competition_bridge(
        '<a href="/SubLeague.aspx?SclassID=25">积分排名</a>'
    )
    assert link["status"] == "BOUND"
    assert link["competition_id"] == 25

    missing = extract_nowscore_competition_bridge("<h2>积分排名</h2><p>LEAGUE_A</p>")
    assert missing["status"] == "UNBOUND"
    assert missing["reason_code"] == "DIRECT_COMPETITION_ID_MISSING"


def test_nowscore_ambiguous_direct_ids_fail_closed():
    result = extract_nowscore_competition_bridge(
        "<script>var sclassID=25; var sclassID=26;</script>"
    )
    assert result["status"] == "AMBIGUOUS"
    assert result["reason_code"] == "DIRECT_COMPETITION_ID_AMBIGUOUS"
    assert "competition_id" not in result


def test_api_fixture_requires_exact_kickoff_orientation_and_aliases():
    bound = bind_api_fixture_strict(SOURCE_FIXTURE, ALIASES, [_api_row()])
    assert bound["status"] == "BOUND"
    assert bound["api_fixture_id"] == 456
    assert bound["league_id"] == 39
    assert bound["season"] == 2026

    swapped = bind_api_fixture_strict(
        SOURCE_FIXTURE,
        ALIASES,
        [_api_row(home="Away FC", away="Home FC")],
    )
    assert swapped["status"] == "UNBOUND"
    assert swapped["reason_code"] == "ORIENTATION_MISMATCH"

    kickoff_only = bind_api_fixture_strict(
        SOURCE_FIXTURE,
        ALIASES,
        [_api_row(kickoff="2026-09-11T11:00:00+00:00")],
    )
    assert kickoff_only["status"] == "UNBOUND"
    assert kickoff_only["reason_code"] == "KICKOFF_MISMATCH"

    fuzzy = bind_api_fixture_strict(
        SOURCE_FIXTURE,
        {"aliases": {"home": ("Home FC",), "away": ("Away FC",)}},
        [_api_row(home="Home", away="Away FC")],
    )
    assert fuzzy["status"] == "UNBOUND"
    assert fuzzy["reason_code"] == "TEAM_IDENTITY_UNPROVEN"

    ambiguous = bind_api_fixture_strict(
        SOURCE_FIXTURE,
        ALIASES,
        [_api_row(fixture_id=456), _api_row(fixture_id=457)],
    )
    assert ambiguous["status"] == "AMBIGUOUS"
    assert ambiguous["reason_code"] == "MULTIPLE_EXACT_API_FIXTURES"


def test_api_coverage_reads_only_league_season_flags():
    result = read_api_league_coverage(
        {
            "ok": True,
            "payload": {
                "response": [{
                    "league": {
                        "id": 39,
                        "name": "League A",
                        "type": "League",
                        "coverage": {"standings": True, "injuries": False},
                    }
                }]
            },
        },
        league_id=39,
        season=2026,
    )
    assert result["status"] == "READ"
    assert result["coverage"] == {"standings": True, "injuries": False}


def test_report_keeps_all_bound_ids_without_team_or_raw_payloads():
    report = build_audit_report(
        cohort={"business_date": "2026-09-11"},
        cohort_path=Path("data/prediction_universe/2026-09-11.json"),
        cutoff=datetime.fromisoformat("2026-09-11T17:00:00+08:00"),
        records=[{
            "nowscore_id": 123,
            "kickoff": SOURCE_FIXTURE["kickoff"],
            "nowscore_competition": {
                "status": "BOUND",
                "competition_id": 25,
                "source_surface": "analysis_page",
                "evidence_location": "analysis_page:inline_script:sclassID_assignment",
            },
            "nowscore_aliases": {
                "status": "BOUND",
                "field_presence": {"home_team_en": True, "away_team_en": True},
            },
            "api_fixture": {
                "status": "BOUND",
                "api_fixture_id": 456,
                "league_id": 39,
                "league_name": "League A",
                "league_type": "League",
                "season": 2026,
            },
            "api_coverage": {
                "status": "READ",
                "reason_code": "SEASON_SPECIFIC_COVERAGE_READ",
                "league_id": 39,
                "season": 2026,
                "coverage": {"standings": True, "injuries": False},
            },
        }],
        nowscore_analysis_requests=1,
        nowscore_alias_request_count=1,
        api_client=None,
        api_key_present=False,
        exact_head="EXACT_HEAD",
    )
    assert report["nowscore"]["direct_competition_bindings"] == [{
        "nowscore_id": 123,
        "competition_id": 25,
        "source_surface": "analysis_page",
        "evidence_location": "analysis_page:inline_script:sclassID_assignment",
    }]
    assert report["api_football"]["exact_fixture_bindings"][0]["api_fixture_id"] == 456
    assert report["api_football"]["league_season_coverage_pairs"][0]["coverage"] == {
        "standings": True,
        "injuries": False,
    }
    serialized = json.dumps(report, ensure_ascii=False)
    assert "Home FC" not in serialized
    assert "<script>" not in serialized


class _Response:
    def __init__(self, payload: dict):
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps(self._payload).encode("utf-8")


def test_api_request_cap_and_audit_secret_redaction():
    requests = []

    def opener(request, timeout):
        requests.append((request, timeout))
        return _Response({"response": []})

    client = ApiFootballClient("SECRET_TOKEN", opener=opener, max_requests=2)
    guarded = ApiFootballClient("SECRET_TOKEN", opener=opener, max_requests=2)
    assert guarded.get("/standings", {"league": 39, "season": 2026})["reason_code"] == "API_ENDPOINT_NOT_ALLOWED"
    assert guarded.request_count == 0
    assert client.get("/fixtures", {"date": "2026-09-11"})["ok"] is True
    assert client.get("/leagues", {"id": 39, "season": 2026})["ok"] is True
    assert client.get("/fixtures", {"date": "2026-09-12"})["reason_code"] == "API_REQUEST_CAP_REACHED"
    assert client.request_count == 2
    assert client.blocked_request_count == 1
    assert all("SECRET_TOKEN" not in request.full_url for request, _ in requests)

    report = build_audit_report(
        cohort={},
        cohort_path=Path("data/prediction_universe/2026-09-11.json"),
        cutoff=datetime.fromisoformat("2026-09-11T17:00:00+08:00"),
        records=[],
        nowscore_analysis_requests=0,
        nowscore_alias_request_count=0,
        api_client=client,
        api_key_present=True,
        api_secret_for_check="SECRET_TOKEN",
        exact_head="EXACT_HEAD",
    )
    serialized = json.dumps(report, ensure_ascii=False)
    assert "SECRET_TOKEN" not in serialized
    assert report["boundary_proof"]["secret_leakage_count"] == 0
    assert report["boundary_proof"]["raw_body_output_marker_count"] == 0
    assert report["api_football"]["endpoint_counts"] == {"/fixtures": 1, "/leagues": 1}
    assert report["api_football"]["forbidden_endpoint_counts"] == {
        "/standings": 0,
        "/injuries": 0,
    }
