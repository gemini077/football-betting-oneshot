import hashlib
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from football_state_memory import (  # noqa: E402
    COMPETITION_CLASS_CLUB_FRIENDLY,
    COMPETITION_CLASS_FORMAL,
    COMPETITION_CLASS_UNKNOWN,
    STATE_MEMORY_CONTRACT_VERSION,
    build_football_evidence_sidecar,
    build_state_memory,
    normalize_competition_label,
)
from model_governance import build_deterministic_model_input_projection  # noqa: E402
from nowscore_markets import (  # noqa: E402
    parse_analysis_data,
    parse_panlu_page,
    parse_three_in_one,
)


def _analysis_row(source_date, home_id, home_name, away_id, away_name, *, fixture_id):
    return [
        source_date, 22, "", "#666", home_id, home_name, away_id, away_name,
        2, 1, "2-1", 0, 0, 0, 0, 0, 0, 0, 0, 0, fixture_id,
    ]


def _source_snapshot(*, include_panlu=True):
    home_row = _analysis_row("26-08-01", 101, "Source Home", 301, "Opponent A", fixture_id=9001)
    away_row = _analysis_row("26-07-28", 302, "Opponent B", 202, "Source Away", fixture_id=9002)
    snapshot = {
        "nowscore_id": 8001,
        "fetched_at": "2026-08-12T12:30:00+08:00",
        "state_memory_identity": {
            "source_fixture_id": 8001,
            "home_team_id": 101,
            "away_team_id": 202,
            "home_team_name": "Source Home",
            "away_team_name": "Source Away",
            "kickoff_at": "2026-08-13 03:00",
        },
        "shuju": {
            "recent_form": {"home_overall": {"matches": 1}},
            "recent_matches": {
                "home_team": [dict(
                    source_date="26-08-01", match_date="2026-08-01",
                    home_team_id=101, home_team_name="Source Home",
                    away_team_id=301, away_team_name="Opponent A",
                    home_goals=2, away_goals=1, source_fixture_id=9001,
                )],
                "away_team": [dict(
                    source_date="26-07-28", match_date="2026-07-28",
                    home_team_id=302, home_team_name="Opponent B",
                    away_team_id=202, away_team_name="Source Away",
                    home_goals=1, away_goals=0, source_fixture_id=9002,
                )],
            },
            "team_ids": {"home": 101, "away": 202},
        },
    }
    if include_panlu:
        snapshot["context"] = {
            "panlu": {
                "matches": [
                    {
                        "match_id": 9001,
                        "competition": "球會友誼",
                        "kickoff": "2026-08-01 18:00",
                        "home_team": "Different display name",
                        "away_team": "Different opponent name",
                        "home_team_id": 101,
                        "away_team_id": 301,
                        "full_time": {"home": 2, "away": 1},
                    },
                    {
                        "match_id": 9002,
                        "competition": "意甲",
                        "kickoff": "2026-07-28 20:00",
                        "home_team": "Opponent B",
                        "away_team": "Source Away",
                        "home_team_id": 302,
                        "away_team_id": 202,
                        "full_time": {"home": 1, "away": 0},
                    },
                ],
            }
        }
    return snapshot


def _source(snapshot=None):
    return {
        "nowscore": {
            "snapshots": [snapshot or _source_snapshot()],
            "source_reference": "data/source_cache/nowscore/raw/8001_analysis.js",
        }
    }


def _record():
    return {
        "prediction_id": "FBOS-PRED-STATE-001",
        "match_id": "M001",
        "business_date": "2026-08-12",
        "home": "Source Home",
        "away": "Source Away",
        "kickoff_at": "2026-08-13T03:00:00+08:00",
        "prediction_created_at": "2026-08-12T12:31:00+08:00",
        "freeze_created_at": "2026-08-12T12:32:00+08:00",
        "source_cutoff_at": "2026-08-12T12:30:00+08:00",
        "match_identity": {
            "home": "Source Home",
            "away": "Source Away",
            "kickoff_at": "2026-08-13T03:00:00+08:00",
        },
    }


def _current_source_fixture():
    return json.loads(
        (ROOT / "tests" / "fixtures" / "nowscore_state_memory" / "current_source_sample.json")
        .read_text(encoding="utf-8")
    )


def _current_source_snapshot():
    fixture = _current_source_fixture()
    parsed = parse_analysis_data(fixture["analysis_js"])
    return fixture, parsed, {
        "nowscore_id": fixture["source_match_id"],
        "fetched_at": "2026-08-12T15:37:42+08:00",
        "state_memory_identity": fixture["target_identity"],
        "shuju": parsed,
        "context": {"panlu": parse_panlu_page(fixture["panlu_html"])},
        "source_record_ref": "tests/fixtures/nowscore_state_memory/current_source_sample.json",
    }


def test_competition_normalization_is_exact_and_unknown_is_explicit():
    friendly = normalize_competition_label("球會友誼")
    formal = normalize_competition_label("意甲")
    unknown = normalize_competition_label("friendly")
    missing = normalize_competition_label(None)

    assert friendly["normalized_competition_class"] == COMPETITION_CLASS_CLUB_FRIENDLY
    assert friendly["is_club_friendly"] is True
    assert formal["normalized_competition_class"] == COMPETITION_CLASS_FORMAL
    assert formal["is_club_friendly"] is False
    assert unknown["normalized_competition_class"] == COMPETITION_CLASS_UNKNOWN
    assert unknown["is_club_friendly"] is None
    assert missing["competition_resolution_status"] == "UNKNOWN"
    assert missing["raw_competition_label"] is None


def test_analysis_parser_keeps_legacy_rows_and_captures_source_fixture_identity():
    home_rows = [
        _analysis_row("26-08-01", 101, "Source Home", 301, "Opponent A", fixture_id=9001),
        _analysis_row("26-07-25", 101, "Source Home", 302, "Opponent B", fixture_id=9003),
        _analysis_row("26-07-18", 101, "Source Home", 303, "Opponent C", fixture_id=9004),
    ]
    away_rows = [
        _analysis_row("26-07-28", 302, "Opponent B", 202, "Source Away", fixture_id=9002),
        _analysis_row("26-07-21", 304, "Opponent D", 202, "Source Away", fixture_id=9005),
        _analysis_row("26-07-14", 305, "Opponent E", 202, "Source Away", fixture_id=9006),
    ]
    text = (
        "var h_data = ["
        + ",".join(repr(row) for row in home_rows)
        + "]; var a_data = ["
        + ",".join(repr(row) for row in away_rows)
        + "];"
    )
    result = parse_analysis_data(text)

    assert "source_fixture_id" not in result["recent_matches"]["home_team"][0]
    assert result["state_memory_matches"]["home_team"][0]["source_fixture_id_candidate"] == 9001
    assert "source_competition_id" not in result["state_memory_matches"]["away_team"][0]


def test_state_memory_uses_source_ids_and_panlu_not_display_names():
    state = build_state_memory(_record(), _source())

    assert state["contract_version"] == STATE_MEMORY_CONTRACT_VERSION
    assert state["capture_status"] == "READY"
    home = state["history"]["home_team"][0]
    away = state["history"]["away_team"][0]
    assert home["source_fixture_id"] == 9001
    assert home["raw_competition_label"] == "球會友誼"
    assert home["is_club_friendly"] is True
    assert home["subject_team_id"] == 101
    assert home["opponent_team_id"] == 301
    assert home["subject_venue"] == "home"
    assert away["subject_team_id"] == 202
    assert away["opponent_team_id"] == 302
    assert away["subject_venue"] == "away"
    assert state["source"]["prematch_verified"] is True
    assert home["score_semantics"] == "SOURCE_HISTORICAL_90M_EVIDENCE"
    assert not {"actual", "result", "settlement", "verified_result"}.intersection(home)


def test_state_memory_can_exactly_join_team_ids_and_date_when_fixture_id_is_missing():
    snapshot = _source_snapshot()
    snapshot["shuju"]["recent_matches"]["home_team"][0].pop("source_fixture_id")
    state = build_state_memory(_record(), _source(snapshot))

    home = state["history"]["home_team"][0]
    assert home["source_fixture_id"] == 9001
    assert home["raw_competition_label"] == "球會友誼"


def test_legacy_sidecar_is_additive_and_model_projection_does_not_consume_state_memory():
    sidecar = build_football_evidence_sidecar(_record(), _source())
    assert sidecar["contract_version"] == "prospective_football_evidence.v1"
    assert sidecar["state_memory_contract_version"] == STATE_MEMORY_CONTRACT_VERSION
    assert sidecar["state_memory"]["history"]["home_team"][0]["source_fixture_id"] == 9001
    assert sidecar["recent_matches"]["home_team"][0]["home_goals"] == 2

    context = {
        "selected_workspace_match": {"id": "M001", "home": "Source Home", "away": "Source Away"},
        "request": {"match_id": "M001"},
        "source_snapshots": _source(),
        "prematch_fundamentals": {"recent_form": {"ready": True}},
    }
    projection = build_deterministic_model_input_projection(context)
    projected = projection["source_snapshots"]["nowscore"]["snapshots"][0]
    assert "state_memory_identity" not in projected
    assert "recent_matches" not in projected["shuju"]


def test_500_fallback_without_per_fixture_rows_is_explicitly_unavailable():
    source = {
        "500_deep": {
            "snapshots": [{
                "fetched_at": "2026-08-12T12:30:00+08:00",
                "shuju": {"recent_form": {"home_overall": {"matches": 10}}},
            }]
        }
    }
    assert build_state_memory(_record(), source) is None


def test_current_nowscore_source_fixture_is_an_immutable_parser_contract():
    fixture, parsed, snapshot = _current_source_snapshot()
    panlu_ids = {
        str(row["match_id"])
        for row in parse_panlu_page(fixture["panlu_html"])["matches"]
    }
    candidates = [
        row["source_fixture_id_candidate"]
        for group in ("home_team", "away_team")
        for row in parsed["state_memory_matches"][group]
    ]

    assert fixture["fixture_contract_version"] == "current_nowscore_state_memory_source_sample.v1"
    assert all(len(value) == 64 for value in fixture["source_sha256"].values())
    assert fixture["fixture_payload_sha256"]["analysis"] == hashlib.sha256(
        fixture["analysis_js"].encode("utf-8")
    ).hexdigest()
    assert fixture["fixture_payload_sha256"]["panlu"] == hashlib.sha256(
        fixture["panlu_html"].encode("utf-8")
    ).hexdigest()
    assert fixture["fixture_payload_sha256"]["three_in_one"] == hashlib.sha256(
        fixture["three_in_one_html"].encode("utf-8")
    ).hexdigest()
    assert parsed["team_ids"] == {
        "home": fixture["target_identity"]["home_team_id"],
        "away": fixture["target_identity"]["away_team_id"],
    }
    assert len(candidates) == fixture["selection"]["analysis_rows"]
    assert sum(str(candidate) in panlu_ids for candidate in candidates) == 6
    assert "source_fixture_id" not in parsed["state_memory_matches"]["home_team"][0]
    assert all(
        "source_competition_id" not in row
        for group in ("home_team", "away_team")
        for row in parsed["state_memory_matches"][group]
    )
    assert snapshot["context"]["panlu"]["count"] == fixture["selection"]["panlu_rows"]


def test_current_source_capture_fail_closes_unpaired_row20_and_resolves_subject_opponent():
    fixture, _parsed, snapshot = _current_source_snapshot()
    source = {"nowscore": {"snapshots": [snapshot], "source_reference": "fixture"}}
    record = {
        **_record(),
        "source_cutoff_at": "2026-08-12T15:37:42+08:00",
    }
    state = build_state_memory(record, source)
    assert state["target_fixture"]["source_fixture_id"] == fixture["source_match_id"]
    assert state["target_fixture"]["home_team_id"] == fixture["target_identity"]["home_team_id"]
    assert state["target_fixture"]["away_team_id"] == fixture["target_identity"]["away_team_id"]
    rows = [
        row
        for group in ("home_team", "away_team")
        for row in state["history"][group]
    ]
    assert state["coverage"]["source_fixture_id_count"] == 6
    assert state["coverage"]["subject_identity_resolved_count"] == len(rows)
    assert any(row["source_fixture_id"] is None for row in rows)
    assert all(row["subject_identity_status"] == "RESOLVED" for row in rows)
    assert all(row["subject_team_id"] in {465, 1040} for row in rows)
    assert all(row["opponent_team_id"] not in {465, 1040} for row in rows)


def test_current_source_fixture_fail_closes_row20_id_with_wrong_team_date_pair():
    _fixture, _parsed, snapshot = _current_source_snapshot()
    snapshot["shuju"]["state_memory_matches"]["home_team"][0][
        "source_fixture_id_candidate"
    ] = 3055809
    state = build_state_memory(
        _record(),
        {"nowscore": {"snapshots": [snapshot]}},
    )
    row = state["history"]["home_team"][0]
    assert row["source_fixture_id"] is None
    assert row["competition_resolution_status"] == "UNKNOWN"


def test_current_source_fixture_proves_target_identity_parser_path():
    fixture = _current_source_fixture()
    identity = parse_three_in_one(fixture["three_in_one_html"])["identity"]
    assert identity["nowscore_id"] == fixture["target_identity"]["source_fixture_id"]
    assert identity["home_team_id"] == fixture["target_identity"]["home_team_id"]
    assert identity["away_team_id"] == fixture["target_identity"]["away_team_id"]
    assert identity["home_team"] == fixture["target_identity"]["home_team_name"]
    assert identity["away_team"] == fixture["target_identity"]["away_team_name"]


def test_current_source_audit_is_offline_and_uses_only_existing_providers():
    import football_state_memory_readiness_audit as audit

    result = audit._audit(limit=2)

    assert result["network_used"] is False
    assert result["readiness_decision"] in {
        "PROSPECTIVE_STATE_MEMORY_READY",
        "PROSPECTIVE_STATE_MEMORY_PARTIAL",
        "FAIL_CLOSED",
    }
    assert set(result["sources"]["providers"]) <= {"nowscore", "500.com"}
    assert "LEGACY_RECONSTRUCTION_COVERAGE" in result
    assert "PROSPECTIVE_CAPTURE_CAPABILITY" in result
    capability = result["PROSPECTIVE_CAPTURE_CAPABILITY"]
    row20 = capability["source_truth"]["row_20_source_fixture_id"]
    assert row20["exact_panlu_match_count"] > 0
    assert row20["promotion_policy"] == "PROMOTE_ONLY_EXACT_PANLU_MATCH; OTHERWISE_NULL"
    assert capability["source_truth"]["row_1_source_competition_id"]["retained"] is False
    assert capability["capture"]["target_team_identity"][
        "verified_by_source_identity_and_analysis_ids"
    ] is True
    assert capability["capture"]["subject_opponent_identity"]["resolved_count"] > 0
    assert "latest_sample_observed_usage" in capability["500.com"]
    assert "KNOWN_FALLBACK_CAPABILITY_GAP" in capability["500.com"]


def test_schema_declares_versioned_state_memory_contract():
    schema = json.loads((ROOT / "schemas" / "football_state_memory.schema.json").read_text(encoding="utf-8"))
    assert schema["$id"].endswith("football_state_memory.v1.schema.json")
    assert schema["properties"]["contract_version"]["const"] == STATE_MEMORY_CONTRACT_VERSION
    assert "history" in schema["required"]
    row_required = schema["$defs"]["historyRow"]["allOf"][0]["required"]
    assert {"source_fixture_id", "home_team_id", "away_team_id", "score_semantics"} <= set(row_required)
