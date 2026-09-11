import json
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import nowscore_prematch_evidence as evidence  # noqa: E402
import nowscore_prematch_adapters as adapters  # noqa: E402
import nowscore_markets  # noqa: E402
from football_state_memory import build_football_evidence_audit, build_football_evidence_sidecar  # noqa: E402
from model_governance import build_deterministic_model_input_projection  # noqa: E402


FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "nowscore_prematch_evidence"
SOURCE = "nowscore_public_jc_sales"
SALES_URL = "https://cp.nowscore.com/buy/jingcai.aspx?typeID=101&oddstype=2&date=2099-01-01"
KICKOFF = "2099-01-02T12:00:00+08:00"


def trusted_fixture(*, home="Alpha", away="Beta", match_id=12345, kickoff=KICKOFF):
    match_number = "M-1"
    sales_row_id = "sales-row-1"
    return {
        "nowscoreId": match_id,
        "homeTeam": home,
        "awayTeam": away,
        "home_team_id": 100,
        "away_team_id": 200,
        "kickoff": kickoff,
        "businessDate": "2099-01-01",
        "jc_membership": "VERIFIED",
        "jc_membership_source": SOURCE,
        "nowscoreMatchStatus": "EXACT_MATCH",
        "nowscoreMatchConfidence": 1.0,
        "source_surface": SALES_URL,
        "source_url": SALES_URL,
        "business_date_source": SOURCE,
        "business_date_source_url": SALES_URL,
        "fetched_at": "2098-12-31T10:00:00+08:00",
        "matchNum": match_number,
        "match_number_source": SOURCE,
        "sales_row_id": sales_row_id,
        "jc_membership_evidence": {
            "source": SOURCE,
            "source_surface": SALES_URL,
            "nowscore_id": match_id,
            "business_date": "2099-01-01",
            "selected_date": "2099-01-01",
            "sales_window": "11:00--次日11:00",
            "match_number": match_number,
            "sales_row_id": sales_row_id,
        },
        "date_provenance": {
            "business_date": "2099-01-01",
            "expected_business_date": "2099-01-01",
            "business_date_source": SOURCE,
            "business_date_source_url": SALES_URL,
            "sales_window": "11:00--次日11:00",
            "sales_row_id": sales_row_id,
            "match_number": match_number,
        },
    }


def read_fixture(surface):
    suffix = "js" if surface == "analysis_data" else "html"
    return (FIXTURE_ROOT / f"{surface}.{suffix}").read_text(encoding="utf-8")


class FixtureClient:
    def __init__(self, *, bodies=None, observed_at="2098-12-31T12:00:00+08:00", source_update_at="2098-12-30T12:00:00+08:00", error_surfaces=None):
        self.bodies = bodies or {surface: read_fixture(surface) for surface in evidence.SURFACES}
        self.observed_at = observed_at
        self.source_update_at = source_update_at
        self.error_surfaces = error_surfaces or {}
        self.calls = []

    def fetch(self, surface, url):
        self.calls.append(surface)
        error = self.error_surfaces.get(surface)
        if error:
            return evidence.SurfacePayload(
                surface,
                url,
                None,
                {
                    "surface": surface,
                    "url": url,
                    "observed_at": self.observed_at,
                    "request_started_at": self.observed_at,
                    "source_update_at": None,
                    "source_update_basis": None,
                    "http_status": error.get("http_status"),
                    "content_sha256": None,
                    "content_length": None,
                    "error_code": error.get("error_code"),
                    "error_detail": None,
                },
            )
        body = self.bodies.get(surface, "")
        return evidence.SurfacePayload(
            surface,
            url,
            body,
            {
                "surface": surface,
                "url": url,
                "observed_at": self.observed_at,
                "request_started_at": self.observed_at,
                "source_update_at": self.source_update_at,
                "source_update_basis": "fixture_last_modified",
                "http_status": 200,
                "content_sha256": evidence._content_hash(body),
                "content_length": len(body.encode("utf-8")),
                "error_code": None,
                "error_detail": None,
            },
        )


def crawl(client=None, *, fixture=None, home="Alpha", away="Beta", kickoff=KICKOFF):
    return evidence.fetch_nowscore_prematch_evidence(
        home,
        away,
        kickoff,
        explicit_id=12345,
        fixture=fixture or trusted_fixture(),
        client=client or FixtureClient(),
    )


def test_verified_same_id_bundle_covers_all_fields_without_raw_bodies():
    client = FixtureClient()
    result = crawl(client)

    assert result["status"] == "OK"
    assert result["nowscore_id"] == 12345
    assert client.calls == list(evidence.SURFACES)
    bundle = result["prematch_evidence"]
    assert set(bundle["fields"]) == set(evidence.FIELD_NAMES)
    assert bundle["source"]["prematch_status"] == "VERIFIED"
    assert bundle["fields"]["market_context"]["state"] == "PRESENT"
    assert bundle["fields"]["recent_form"]["state"] == "PRESENT"
    assert bundle["fields"]["h2h"]["state"] == "PRESENT"
    # The legacy fixture has only a prose heading and a date/opponent table;
    # Issue #284 requires the field-specific future schedule shape.
    assert bundle["fields"]["future_schedule_rest"]["state"] == "ABSENT"
    assert bundle["fields"]["injuries"]["state"] == "SECTION_PRESENT_EMPTY"
    assert bundle["fields"]["suspensions"]["state"] == "SECTION_PRESENT_EMPTY"
    assert bundle["fields"]["lineup_state"]["semantic_state"] == "PREDICTED"
    assert bundle["fields"]["technical_stats"]["state"] == "PRESENT"
    assert bundle["fields"]["coach"]["state"] == "PRESENT"
    assert bundle["fields"]["referee"]["state"] == "PRESENT"
    assert bundle["fields"]["panlu"]["state"] == "PRESENT"
    serialized = json.dumps(result, ensure_ascii=False)
    assert "<html>" not in serialized
    assert "var h_data" not in serialized
    assert "raw_bodies_persisted" in serialized
    assert bundle["rights"]["raw_html_js_persisted"] is False


def test_existing_same_id_identity_accepts_abbreviation_full_name_regression():
    result = crawl(fixture=trusted_fixture(home="Alpha", away="Beta"), home="Alpha", away="Beta")
    assert result["identity_verification"]["trusted"] is True
    assert result["identity_verification"]["display_name_mismatch"] is False
    assert result["prematch_evidence"]["target_fixture"]["home_team"] == "Alpha FC"


def test_identity_contradiction_stops_after_market_surface():
    body = read_fixture("market_context").replace('value="12345"', 'value="99999"')
    client = FixtureClient(bodies={"market_context": body})
    result = crawl(client)

    assert result["status"] == "IDENTITY_MISMATCH"
    assert client.calls == ["market_context"]
    assert result["identity_verification"]["trusted"] is False
    assert "PROVIDER_ID_MISMATCH" in result["identity_verification"]["reasons"]
    assert result["prematch_evidence"]["fields"]["market_context"]["state"] == "CONFLICT"


def test_orientation_and_kickoff_contradictions_fail_closed():
    reversed_body = read_fixture("market_context").replace("Alpha FC", "TEMP FC", 1).replace("Beta FC", "Alpha FC", 1).replace("TEMP FC", "Beta FC", 1)
    reversed_client = FixtureClient(bodies={"market_context": reversed_body})
    reversed_result = crawl(reversed_client)
    assert reversed_result["status"] == "IDENTITY_MISMATCH"
    assert reversed_client.calls == ["market_context"]
    assert "ORIENTATION_CONFLICT" in reversed_result["identity_verification"]["reasons"]

    mismatched_fixture = trusted_fixture(kickoff="2099-01-03T12:00:00+08:00")
    kickoff_client = FixtureClient()
    kickoff_result = crawl(kickoff_client, fixture=mismatched_fixture)
    assert kickoff_result["status"] == "IDENTITY_MISMATCH"
    assert kickoff_client.calls == ["market_context"]
    assert "KICKOFF_MISMATCH" in kickoff_result["identity_verification"]["reasons"]


def test_access_gated_surface_is_explicit_and_never_bypassed():
    client = FixtureClient(error_surfaces={"market_context": {"http_status": 403, "error_code": "ACCESS_GATED"}})
    result = crawl(client)

    assert result["status"] == "IDENTITY_MISMATCH"
    assert client.calls == ["market_context"]
    assert result["prematch_evidence"]["fields"]["market_context"]["state"] == "ACCESS_GATED"
    assert result["prematch_evidence"]["parser_health"]["surface_health"][0]["status"] == "ACCESS_GATED"
    assert result["prematch_evidence"]["rights"]["auth_or_bypass_used"] is False


def test_post_kickoff_observation_is_not_prematch_eligible():
    client = FixtureClient(observed_at="2099-01-02T12:01:00+08:00", source_update_at=None)
    result = crawl(client)
    market = result["prematch_evidence"]["fields"]["market_context"]

    assert result["prematch_evidence"]["source"]["prematch_verified"] is False
    assert market["prematch_eligible"] is False
    assert market["state"] == "CONFLICT"


def test_parser_drift_is_reported_without_fabricating_facts():
    bodies = {surface: read_fixture(surface) for surface in evidence.SURFACES}
    bodies["analysis_page"] = "<html><body><div>layout changed</div></body></html>"
    result = crawl(FixtureClient(bodies=bodies))
    bundle = result["prematch_evidence"]

    assert bundle["parser_health"]["overall_status"] == "DRIFT_SUSPECTED"
    assert any(signal["surface"] == "analysis_page" for signal in bundle["parser_health"]["drift_signals"])
    assert bundle["fields"]["h2h"]["state"] == "ABSENT"
    assert bundle["fields"]["future_schedule_rest"]["state"] == "ABSENT"


def test_unlabelled_lineup_is_uncertain_not_a_factual_starting_eleven():
    payload = evidence.SurfacePayload(
        "time_page",
        "https://example.invalid/time",
        "<h2>Lineup</h2><table><tr><td>GK</td><td>1</td><td>1</td></tr></table>",
        {"observed_at": "2098-12-31T12:00:00+08:00", "source_update_at": None, "http_status": 200},
    )
    parsed = evidence._markup_adapter(payload, {})
    assert parsed["fields"]["lineup_state"]["state"] == "PARSE_UNCERTAIN"
    assert parsed["fields"]["lineup_state"]["semantic_state"] == "UNLABELLED"


def test_h2h_without_real_meeting_records_is_not_present():
    payload = evidence.SurfacePayload(
        "analysis_page",
        "https://example.invalid/analysis",
        "<h2>Head to head</h2><table><tr><th>Home</th><th>Away</th><th>Result</th></tr><tr><td>Alpha</td><td>Beta</td><td>--</td></tr></table>",
        {"observed_at": "2098-12-31T12:00:00+08:00", "source_update_at": None, "http_status": 200},
    )
    parsed = evidence._markup_adapter(payload, {})
    field = parsed["fields"]["h2h"]
    assert field["state"] == "PARSE_UNCERTAIN"
    assert field["state"] != "PRESENT"
    assert field["record_count"] == 0


def test_h2h_with_a_real_date_and_score_record_is_present():
    payload = evidence.SurfacePayload(
        "analysis_page",
        "https://example.invalid/analysis",
        "<h2>Head to head</h2><table><tr><th>Date</th><th>Score</th></tr><tr><td>2098-12-20</td><td>2-1</td></tr></table>",
        {"observed_at": "2098-12-31T12:00:00+08:00", "source_update_at": None, "http_status": 200},
    )
    parsed = evidence._markup_adapter(payload, {})
    field = parsed["fields"]["h2h"]
    assert field["state"] == "PRESENT"
    assert field["record_count"] == 1
    assert field["value"]["records"] == [{"date": "2098-12-20", "score": "2-1"}]


def test_market_line_rows_cannot_be_technical_stats():
    payload = evidence.SurfacePayload(
        "time_page",
        "https://example.invalid/time",
        "<h2>Technical statistics</h2><table><tr><th>Type</th><th>Home</th><th>Line</th><th>Away</th></tr><tr><td>初</td><td>0.95</td><td>-2.5</td><td>0.85</td></tr><tr><td>盘口</td><td>0.95</td><td>-2.0</td><td>0.85</td></tr></table>",
        {"observed_at": "2098-12-31T12:00:00+08:00", "source_update_at": None, "http_status": 200},
    )
    parsed = evidence._markup_adapter(payload, {})
    field = parsed["fields"]["technical_stats"]
    assert field["state"] == "PARSE_UNCERTAIN"
    assert field["state"] != "PRESENT"
    assert field["record_count"] == 0


def test_football_technical_labels_are_required_for_present_stats():
    payload = evidence.SurfacePayload(
        "time_page",
        "https://example.invalid/time",
        "<h2>Technical statistics</h2><table><tr><th>Metric</th><th>Home</th><th>Away</th></tr><tr><td>Possession</td><td>55%</td><td>45%</td></tr><tr><td>Shots on target</td><td>6</td><td>3</td></tr></table>",
        {"observed_at": "2098-12-31T12:00:00+08:00", "source_update_at": None, "http_status": 200},
    )
    parsed = evidence._markup_adapter(payload, {})
    field = parsed["fields"]["technical_stats"]
    assert field["state"] == "PRESENT"
    assert field["record_count"] == 2
    assert [item["label"] for item in field["value"]["stats"]] == ["Possession", "Shots on target"]


def test_availability_keywords_and_generic_rows_are_not_present():
    payload = evidence.SurfacePayload(
        "time_page",
        "https://example.invalid/time",
        "<h2>Injuries</h2><p>injury information</p><table><tr><th>Status</th><th>Count</th></tr><tr><td>Out</td><td>3</td></tr></table>"
        "<h2>Suspensions</h2><p>suspension information</p><table><tr><th>Status</th><th>Count</th></tr><tr><td>Suspended</td><td>3</td></tr></table>",
        {"observed_at": "2098-12-31T12:00:00+08:00", "source_update_at": None, "http_status": 200},
    )
    parsed = evidence._markup_adapter(payload, {})
    assert parsed["fields"]["injuries"]["state"] == "PARSE_UNCERTAIN"
    assert parsed["fields"]["suspensions"]["state"] == "PARSE_UNCERTAIN"


def test_competition_row_count_without_rank_points_or_stage_is_uncertain():
    payload = evidence.SurfacePayload(
        "analysis_page",
        "https://example.invalid/analysis",
        "<h2>Standings</h2><table><tr><th>Home</th><th>Away</th></tr><tr><td>Alpha</td><td>Beta</td></tr></table>",
        {"observed_at": "2098-12-31T12:00:00+08:00", "source_update_at": None, "http_status": 200},
    )
    parsed = evidence._markup_adapter(payload, {})
    field = parsed["fields"]["competition_standings_stage"]
    assert field["state"] == "PARSE_UNCERTAIN"
    assert field["record_count"] == 0


def test_competition_rank_and_points_facts_are_present():
    payload = evidence.SurfacePayload(
        "analysis_page",
        "https://example.invalid/analysis",
        "<h2>Standings</h2><table><tr><th>Rank</th><th>Points</th><th>Team</th></tr><tr><td>1</td><td>10</td><td>Alpha</td></tr></table>",
        {"observed_at": "2098-12-31T12:00:00+08:00", "source_update_at": None, "http_status": 200},
    )
    parsed = evidence._markup_adapter(payload, {})
    field = parsed["fields"]["competition_standings_stage"]
    assert field["state"] == "PRESENT"
    assert field["value"]["rank_fact_count"] == 1
    assert field["value"]["points_fact_count"] == 1


def test_empty_coach_profiles_are_not_present(monkeypatch):
    monkeypatch.setattr(
        adapters,
        "parse_coach_page",
        lambda _body: {
            "home": {"name": None, "coach_records": [], "team_records": []},
            "away": {"name": "", "coach_records": [], "team_records": []},
        },
    )
    payload = evidence.SurfacePayload(
        "coach",
        "https://example.invalid/coach",
        "<h1>coach</h1>",
        {"observed_at": "2098-12-31T12:00:00+08:00", "source_update_at": None, "http_status": 200},
    )
    parsed = adapters._adapter("coach", payload, {})
    field = parsed["fields"]["coach"]
    assert field["state"] == "PARSE_UNCERTAIN"
    assert field["reason_code"] == "COACH_SECTION_UNCERTAIN"
    assert parsed["health"]["status"] == "DRIFT_SUSPECTED"


def test_present_invariant_requires_domain_specific_facts_for_every_present_field():
    result = crawl()
    present_fields = {
        field: item
        for field, item in result["prematch_evidence"]["fields"].items()
        if item["state"] == "PRESENT"
    }
    assert present_fields
    assert all(adapters._has_domain_fact(field, item) for field, item in present_fields.items())

    generic_coach = {
        "fields": {
            "coach": {
                "state": "PRESENT",
                "value": {"home": {}, "away": {}},
                "record_count": 0,
            }
        }
    }
    adapters._enforce_present_invariant(generic_coach)
    assert generic_coach["fields"]["coach"]["state"] == "PARSE_UNCERTAIN"
    assert generic_coach["fields"]["coach"]["reason_code"] == "PRESENT_INVARIANT_NO_DOMAIN_FACT"


def test_state_memory_sidecar_keeps_evidence_beside_model_projection():
    result = crawl()
    snapshot = {
        **{key: result.get(key) for key in ("nowscore_id", "fetched_at", "state_memory_identity", "source_url", "analysis_source_url")},
        "shuju": result["shuju"],
        "context": result["context"],
        "prematch_evidence": result["prematch_evidence"],
    }
    source_snapshots = {"nowscore": {"snapshots": [snapshot], "references": list(result["source_urls"].values())}}
    record = {
        "prediction_id": "P-272",
        "match_id": "M-272",
        "home": "Alpha",
        "away": "Beta",
        "kickoff_at": KICKOFF,
        "match_identity": {"match_id": "M-272", "home": "Alpha", "away": "Beta"},
    }

    sidecar = build_football_evidence_sidecar(record, source_snapshots)
    assert sidecar["prematch_evidence"]["contract_version"] == evidence.CONTRACT_VERSION
    projection = build_deterministic_model_input_projection({
        "request": {"match_id": "M-272"},
        "selected_workspace_match": {"id": "M-272", "home": "Alpha", "away": "Beta"},
        "source_snapshots": source_snapshots,
    })
    projected = projection["source_snapshots"]["nowscore"]["snapshots"][0]
    assert "prematch_evidence" not in projected


def test_structured_bundle_survives_when_legacy_recent_rows_are_missing():
    result = crawl()
    snapshot = {"prematch_evidence": result["prematch_evidence"], "shuju": {}}
    audit = build_football_evidence_audit({"nowscore": {"snapshots": [snapshot]}})
    assert audit["prematch_evidence"]["contract_version"] == evidence.CONTRACT_VERSION
    assert audit["recent_matches"] == {"home_team": [], "away_team": []}

    hostile = {"prematch_evidence": {**result["prematch_evidence"], "source": {"body": "raw"}}}
    hostile_projected = build_football_evidence_audit({"nowscore": {"snapshots": [hostile]}})
    assert "body" not in json.dumps(hostile_projected, ensure_ascii=False)


def test_schema_states_are_the_issue_contract():
    assert evidence.STATE_NAMES == (
        "PRESENT",
        "SECTION_PRESENT_EMPTY",
        "ABSENT",
        "ACCESS_GATED",
        "PARSE_UNCERTAIN",
        "CONFLICT",
    )


def test_public_client_records_headers_and_never_writes_a_cache():
    seen = {}

    class Response:
        headers = {"Last-Modified": "Wed, 31 Dec 2098 04:00:00 GMT"}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def getcode(self):
            return 200

        def read(self):
            return b"structured body"

    def opener(request, timeout):
        seen["headers"] = dict(request.headers)
        seen["timeout"] = timeout
        return Response()

    client = evidence.NowscorePublicClient(opener=opener, clock=lambda: datetime(2098, 12, 31, 12, tzinfo=timezone.utc))
    payload = client.fetch("analysis_page", "https://example.invalid/page")
    assert payload.body == "structured body"
    assert payload.observation["source_update_at"] != payload.observation["observed_at"]
    assert payload.observation["source_update_basis"] == "http_last_modified"
    assert seen["headers"]["Cache-control"] == "no-cache"
    assert seen["headers"]["Accept-encoding"] == "identity"
    assert client.request_count == 1


def test_legacy_nowscore_fetch_helper_does_not_write_raw_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(nowscore_markets, "_fetch_bytes", lambda _url: b"body")
    target = tmp_path / "would-have-been-raw.html"
    assert nowscore_markets._fetch_cached_page("https://example.invalid/page", target, False) == b"body"
    assert not target.exists()


def test_natural_cohort_report_is_structured_and_bounded(tmp_path):
    cohort_path = tmp_path / "2099-01-01.json"
    cohort_path.write_text(json.dumps({
        "business_date": "2099-01-01",
        "status": "READY",
        "source": "nowscore_public_jc",
        "fixtures": [trusted_fixture()],
    }), encoding="utf-8")
    report = evidence.run_natural_cohort(
        cohort_path=cohort_path,
        as_of="2098-12-31T12:00:00+08:00",
        max_matches=1,
        client_factory=FixtureClient,
    )
    assert report["run"]["execution"] == "github_actions_live"
    assert report["cohort"]["selected_fixture_count"] == 1
    assert report["coverage"]["match_count"] == 1
    assert report["matches"][0]["prematch_evidence"]["contract_version"] == evidence.CONTRACT_VERSION
    assert report["rights"]["raw_html_js_persisted"] is False
    assert report["change_boundary"]["model_math_changed"] is False
