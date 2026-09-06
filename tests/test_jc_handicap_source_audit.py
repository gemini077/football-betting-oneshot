from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from fetch_sporttery import parse_api_matches  # noqa: E402
from official_jc_handicap import build_official_jc_handicap_state  # noqa: E402
from official_jc_handicap_source_audit import (  # noqa: E402
    _binding_funnel,
    _delivery_decision,
    resolve_current_business_date,
)


FIXTURE = ROOT / "tests" / "fixtures" / "jc_handicap" / "official_source_audit.json"


def load_fixture() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_current_official_source_fixture_proves_request_and_hhad_parser_contract():
    payload = load_fixture()
    audit = payload["audit"]
    assert audit["current_source_status"] == "AVAILABLE"
    assert audit["market_identity"] == "JC_HANDICAP_1X2"
    assert audit["request_contract"]["params"] == {
        "channel": "c",
        "poolCode": "had,hhad,crs,ttg,hafu",
    }
    assert audit["official_calculator_probe"]["http_status"] == 200
    assert len(audit["official_calculator_probe"]["response_sha256"]) == 64
    assert audit["official_rows_returned"] == 24
    assert audit["hhad_line_available"] == 24
    assert audit["hhad_three_prices_available"] == 24
    assert audit["delivery_decision"] == "JC_HANDICAP_FORMAL_TRUTH_READY"
    assert audit["binding_funnel"]["exact_bound"] == 24
    assert audit["binding_funnel"]["ambiguous"] == 0
    assert audit["binding_funnel"]["unmatched"] == 0
    row = audit["evidence_rows"][0]
    parsed = parse_api_matches([{
        "businessDate": audit["target_business_date"],
        "subMatchList": [row["raw_row"]],
    }])[0]
    assert parsed["rqspf"] == row["parsed"]["rqspf"]
    assert audit["parser_contract"]["source_field"] == "hhad.goalLine"


def test_current_official_source_fixture_binds_formal_line_with_raw_hash():
    payload = load_fixture()
    audit = payload["audit"]
    source_probe = audit["official_calculator_probe"]
    parsed_rows = [row["parsed"] for row in audit["evidence_rows"]]
    source_document = {
        "source": audit["source"],
        "url": audit["request_contract"]["url"],
        "business_date": audit["target_business_date"],
        "fetch_time": "2026-09-05T19:19:52+00:00",
        "success": True,
        "payload_success": True,
        "http_status": source_probe["http_status"],
        "raw_response_sha256": source_probe["response_sha256"],
        "request_contract": audit["request_contract"],
        "matches": parsed_rows,
    }
    target = {
        "sporttery_match_id": parsed_rows[0]["matchId"],
        "business_date": audit["target_business_date"],
        "home": parsed_rows[0]["homeTeam"],
        "away": parsed_rows[0]["awayTeam"],
        "kickoff_local": "2026-09-06T17:00:00+08:00",
    }
    state = build_official_jc_handicap_state(
        source_document,
        target,
        source_ref="tests/fixtures/jc_handicap/official_source_audit.json",
    )
    assert state["status"] == "AVAILABLE"
    assert state["handicap_line"] == -1
    assert state["match_binding"]["status"] == "EXACT"
    assert state["raw_response_sha256"] == source_probe["response_sha256"]


def test_parser_preserves_line_without_prices_and_rejects_fractional_line():
    payload = load_fixture()
    raw_row = deepcopy(payload["audit"]["evidence_rows"][0]["raw_row"])
    raw_row["hhad"].pop("a")
    parsed = parse_api_matches([{
        "businessDate": payload["audit"]["target_business_date"],
        "subMatchList": [raw_row],
    }])[0]
    assert parsed["rqspf"] == {"handicap": -1, "home": 3.22, "draw": 3.4}

    fractional = deepcopy(raw_row)
    fractional["hhad"]["goalLine"] = "-1.5"
    rejected = parse_api_matches([{
        "businessDate": payload["audit"]["target_business_date"],
        "subMatchList": [fractional],
    }])[0]
    assert rejected["rqspf"] is None


def test_binding_funnel_reports_exact_line_and_price_stages():
    payload = load_fixture()
    row = payload["audit"]["evidence_rows"][0]["parsed"]
    fixture = {
        "matchNum": row["matchNum"],
        "businessDate": row["businessDate"],
        "homeTeam": row["homeTeam"],
        "awayTeam": row["awayTeam"],
        "matchDate": row["matchDate"],
        "matchTime": row["matchTime"],
    }
    funnel = _binding_funnel(
        [row],
        {"fixtures": [fixture]},
        universe_path="tests/fixtures/jc_handicap/universe.json",
    )
    assert funnel["status"] == "AVAILABLE"
    assert funnel["jc_fixtures"] == 1
    assert funnel["official_rows"] == 1
    assert funnel["exact_bound"] == 1
    assert funnel["ambiguous"] == 0
    assert funnel["unmatched"] == 0
    assert funnel["line_available"] == 1
    assert funnel["odds_available"] == 1

    assert _delivery_decision(
        source_available=True,
        page_probe={"http_status": 200},
        calculator_probe={"http_status": 200, "payload_success": True},
        binding_funnel={**funnel, "duplicates": 1, "conflicts": 0},
    ) == "JC_HANDICAP_SOURCE_AUTHORITY_PARTIAL"


def test_live_lane_resolves_latest_authoritative_ready_universe(tmp_path):
    for business_date, status, fixtures in (
        ("2026-09-06", "READY", [{"matchId": "1"}]),
        ("2026-09-07", "READY", [{"matchId": "2"}]),
        ("2026-09-08", "NOT_YET_PUBLISHED", []),
    ):
        (tmp_path / f"{business_date}.json").write_text(
            json.dumps({
                "business_date": business_date,
                "status": status,
                "fixtures": fixtures,
            }),
            encoding="utf-8",
        )
    assert resolve_current_business_date(tmp_path) == "2026-09-07"


def test_live_delivery_decision_maps_blocked_partial_and_conflict_fail_closed():
    funnel = {
        "status": "AVAILABLE",
        "jc_fixtures": 1,
        "official_rows": 1,
        "exact_bound": 1,
        "ambiguous": 0,
        "unmatched": 0,
        "duplicates": 0,
        "conflicts": 0,
        "line_available": 1,
    }
    assert _delivery_decision(
        source_available=False,
        page_probe={"http_status": 200},
        calculator_probe={"http_status": 567, "payload_success": None},
        binding_funnel=funnel,
    ) == "OFFICIAL_SOURCE_NOT_EXECUTABLE"
    assert _delivery_decision(
        source_available=False,
        page_probe={"http_status": 200},
        calculator_probe={"http_status": 200, "payload_success": True},
        binding_funnel=funnel,
    ) == "JC_HANDICAP_SOURCE_AUTHORITY_PARTIAL"
    assert _delivery_decision(
        source_available=True,
        page_probe={"http_status": 200},
        calculator_probe={"http_status": 200, "payload_success": True},
        binding_funnel={**funnel, "conflicts": 1},
    ) == "FAIL_CLOSED"
