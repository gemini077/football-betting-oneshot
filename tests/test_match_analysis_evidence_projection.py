from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from scripts.match_analysis_evidence_audit import run_natural_cohort_audit
from scripts.match_analysis_evidence_projection import (
    build_market_1x2_chronology,
    project_match_analysis_evidence,
)


def _prediction() -> dict:
    return {
        "prediction_id": "FBOS-PRED-TEST-001",
        "prediction_sha256": "prediction-digest",
        "match_id": "9000",
        "match_key": "FBOS-TEST-9000",
        "kickoff_at": "2026-09-10T18:00:00+08:00",
        "prediction_status": "formal",
        "formal_eligible": True,
        "probabilities": {"home": 0.5, "draw": 0.25, "away": 0.25},
        "input_snapshot": {"snapshot_id": "FBOS-SNAPSHOT-TEST-001"},
    }


def _history_row(
    match_id: int,
    match_date: str,
    home_id: int,
    away_id: int,
    home_goals: int,
    away_goals: int,
    subject_id: int,
    venue: str,
) -> dict:
    return {
        "source_fixture_id": match_id,
        "provider_match_id": match_id,
        "home_team_id": home_id,
        "home_team_name": "{h}$8",
        "away_team_id": away_id,
        "away_team_name": "{g}$15",
        "match_date": match_date,
        "home_goals_90m": home_goals,
        "away_goals_90m": away_goals,
        "score_semantics": "SOURCE_HISTORICAL_90M_EVIDENCE",
        "raw_competition_label": "League A",
        "normalized_competition_label": "League A",
        "normalized_competition_class": "FORMAL_COMPETITION",
        "competition_resolution_status": "RESOLVED",
        "subject_team_id": subject_id,
        "opponent_team_id": away_id if subject_id == home_id else home_id,
        "subject_venue": venue,
        "subject_identity_status": "RESOLVED",
        "source_provider": "nowscore",
        "source_reference": "frozen://history",
        "source_cutoff_at": "2026-09-09T12:00:00+08:00",
    }


def _panlu_row(
    match_id: int,
    match_date: str,
    home_id: int,
    away_id: int,
    home_name: str,
    away_name: str,
) -> dict:
    return {
        "match_id": match_id,
        "kickoff": f"{match_date} 12:00",
        "home_team": home_name,
        "away_team": away_name,
        "home_team_id": home_id,
        "away_team_id": away_id,
        "full_time": {"home": 0, "away": 0},
    }


def _market_context() -> dict:
    return {
        "bookmakers": [
            {
                "name": "Book A",
                "cid": 1,
                "source_company_id": 10,
                "spf_open": {"home": 2.0, "draw": 4.0, "away": 4.0},
                "spf_current": {"home": 2.5, "draw": 3.333333333333, "away": 5.0},
            },
            {
                "name": "Book B",
                "cid": 2,
                "source_company_id": 11,
                "spf_open": {"home": 2.5, "draw": 3.333333333333, "away": 5.0},
                "spf_current": {"home": 2.0, "draw": 4.0, "away": 4.0},
            },
            {
                "name": "Book invalid",
                "cid": 3,
                "spf_open": {"home": 2.0, "draw": 4.0, "away": 4.0},
                "spf_current": {"home": 1.0, "draw": 4.0, "away": 4.0},
            },
        ]
    }


def _inputs() -> tuple[dict, dict, dict, dict]:
    prediction = _prediction()
    history_home = [
        _history_row(101, "2026-09-01", 10, 30, 2, 0, 10, "home"),
        _history_row(102, "2026-09-03", 40, 10, 1, 1, 10, "away"),
        _history_row(103, "2026-09-08", 10, 50, 0, 3, 10, "home"),
    ]
    history_away = [
        _history_row(201, "2026-09-02", 20, 60, 2, 1, 20, "home"),
        _history_row(202, "2026-09-06", 70, 20, 0, 2, 20, "away"),
    ]
    panlu = [
        _panlu_row(101, "2026-09-01", 10, 30, "Team A", "Team C"),
        _panlu_row(102, "2026-09-03", 40, 10, "Team D", "Team A"),
        _panlu_row(103, "2026-09-08", 10, 50, "Team A", "Team E"),
        _panlu_row(201, "2026-09-02", 20, 60, "Team B", "Team F"),
        _panlu_row(202, "2026-09-06", 70, 20, "Team G", "Team B"),
    ]
    snapshot = {
        "snapshot_id": "FBOS-SNAPSHOT-TEST-001",
        "snapshot_ref": "data/model_governance/input_snapshots/test.json",
        "input": {
            "source_snapshots": {
                "nowscore": {
                    "snapshots": [
                        {"nowscore_context": {"panlu": {"matches": panlu}}}
                    ]
                }
            }
        },
    }
    evidence = {
        "contract_version": "prospective_football_evidence.v1",
        "state_memory_contract_version": "football_state_memory.v1",
        "state_memory": {
            "contract_version": "football_state_memory.v1",
            "target_fixture": {
                "source_fixture_id": 9000,
                "provider_match_id": 9000,
                "home_team_id": 10,
                "away_team_id": 20,
                "home_team_name": "Team A",
                "away_team_name": "Team B",
                "kickoff_at": "2026-09-10T18:00:00+08:00",
                "normalized_competition_label": "League A",
                "normalized_competition_class": "FORMAL_COMPETITION",
                "competition_resolution_status": "RESOLVED",
            },
            "history": {"home_team": history_home, "away_team": history_away},
        },
        "prematch_evidence": {
            "fields": {
                "market_context": {"state": "PRESENT", "value": _market_context()},
                "coach": {
                    "state": "PRESENT",
                    "value": {"home": {"name": "Coach A"}, "away": {"name": "Coach B"}},
                },
                "referee": {"state": "PARSE_UNCERTAIN", "value": None},
            }
        },
    }
    fixture = {
        "nowscoreId": 9000,
        "matchId": "9000",
        "matchDate": "2026-09-10",
        "matchTime": "18:00",
        "homeTeam": "Team A",
        "awayTeam": "Team B",
    }
    return prediction, snapshot, evidence, fixture


def test_identical_inputs_produce_identical_projection_and_do_not_mutate_inputs():
    prediction, snapshot, evidence, fixture = _inputs()
    before = copy.deepcopy((prediction, snapshot, evidence, fixture))

    first = project_match_analysis_evidence(prediction, snapshot, evidence, fixture)
    second = project_match_analysis_evidence(prediction, snapshot, evidence, fixture)

    assert first == second
    assert (prediction, snapshot, evidence, fixture) == before


def test_recent_state_aggregates_rest_btts_total_and_exact_opponent_names():
    prediction, snapshot, evidence, fixture = _inputs()
    result = project_match_analysis_evidence(prediction, snapshot, evidence, fixture)
    home = result["recent_state"]["home"]
    stats = home["windows"]["last5"]

    assert stats["sample_size"] == 3
    assert stats["wdl"] == {"wins": 1, "draws": 1, "losses": 1}
    assert stats["goals_for"] == 3
    assert stats["goals_against"] == 4
    assert stats["clean_sheet_count"] == 1
    assert stats["btts_count"] == 1
    assert stats["over_2_5_count"] == 1
    assert stats["over_3_5_count"] == 0
    assert stats["average_total_goals"] == pytest.approx(7 / 3, abs=1e-6)
    assert home["days_since_previous_match"] == 2
    assert home["schedule_density"] == {"matches_last_7_days": 2, "matches_last_14_days": 3}
    assert [row["opponent_display_name"] for row in home["sequence"]] == [
        "Team E",
        "Team D",
        "Team C",
    ]
    assert result["coverage"]["atoms"]["opponent_names"]["resolved_count"] == 5


def test_placeholder_analysis_names_never_leak_into_projection():
    prediction, snapshot, evidence, fixture = _inputs()
    result = project_match_analysis_evidence(prediction, snapshot, evidence, fixture)

    serialized = json.dumps(result, ensure_ascii=False)
    assert "{h}$8" not in serialized
    assert "{g}$15" not in serialized


@pytest.mark.parametrize(
    ("change", "expected_reason"),
    [
        (lambda row: row.update(match_id=999), "PANLU_FIXTURE_ID_NOT_FOUND"),
        (lambda row: row.update(away_team_id=999), "TEAM_ID_MISMATCH"),
        (lambda row: row.update(kickoff="2026-09-02 12:00"), "DATE_MISMATCH"),
        (lambda row: (row.update(home_team_id=30), row.update(away_team_id=10)), "ORIENTATION_MISMATCH"),
    ],
)
def test_mismatched_fixture_team_date_or_orientation_fails_closed(change, expected_reason):
    prediction, snapshot, evidence, fixture = _inputs()
    change(snapshot["input"]["source_snapshots"]["nowscore"]["snapshots"][0]["nowscore_context"]["panlu"]["matches"][0])

    result = project_match_analysis_evidence(prediction, snapshot, evidence, fixture)
    row = result["recent_state"]["home"]["sequence"][-1]

    assert row["opponent_display_name"] is None
    assert row["opponent_name_resolution"]["reason"] == expected_reason


def test_current_fixture_identity_conflict_fails_closed():
    prediction, snapshot, evidence, fixture = _inputs()
    fixture["matchId"] = "9999"

    result = project_match_analysis_evidence(prediction, snapshot, evidence, fixture)

    assert result["projection_success"] is False
    assert result["projection_reject_reasons"] == ["CURRENT_FIXTURE_ID_CONFLICT"]


def test_candidate_only_history_fixture_id_does_not_unlock_name_resolution():
    prediction, snapshot, evidence, fixture = _inputs()
    row = snapshot["input"]["source_snapshots"]["nowscore"]["snapshots"][0]["nowscore_context"]["panlu"]["matches"][0]
    row.pop("match_id")
    history_row = evidence["state_memory"]["history"]["home_team"][0]
    history_row.pop("source_fixture_id")
    history_row.pop("provider_match_id")
    history_row["source_fixture_id_candidate"] = 101

    result = project_match_analysis_evidence(prediction, snapshot, evidence, fixture)
    projected = result["recent_state"]["home"]["sequence"][-1]

    assert projected["opponent_display_name"] is None
    assert projected["opponent_name_resolution"]["reason"] == "MISSING_SOURCE_FIXTURE_ID"


def test_market_de_vig_median_delta_iqr_is_deterministic_and_rejects_invalid_odds():
    first = build_market_1x2_chronology(_market_context())
    second = build_market_1x2_chronology(_market_context())

    assert first == second
    assert first["valid_open_bookmaker_count"] == 3
    assert first["valid_current_bookmaker_count"] == 2
    assert first["valid_book_count"] == 2
    assert first["rejected_bookmaker_count"] == 1
    assert first["median_opening_probability"]["home"] == pytest.approx(0.472222, abs=1e-6)
    assert first["median_current_probability"]["home"] == pytest.approx(0.472222, abs=1e-6)
    assert first["delta_probability_points"] == {"home": 0.0, "draw": 0.0, "away": 0.0}
    assert first["movement_direction_counts"]["home"]["up_count"] == 1
    assert first["movement_direction_counts"]["home"]["down_count"] == 1
    assert first["dispersion_iqr"]["home"]["current_iqr"] == pytest.approx(0.027778, abs=1e-6)
    serialized = json.dumps(first, ensure_ascii=False).lower()
    for forbidden in ("intent", "sharp", "trap", "value"):
        assert forbidden not in serialized


def test_model_market_alignment_is_numeric_and_direction_only():
    prediction, snapshot, evidence, fixture = _inputs()
    result = project_match_analysis_evidence(prediction, snapshot, evidence, fixture)
    alignment = result["model_market_alignment"]

    assert alignment["status"] == "AVAILABLE"
    assert alignment["direction"] == "ALIGNED"
    assert alignment["model_preferred_outcome"] == "home"
    assert alignment["market_preferred_outcome"] == "home"
    assert set(alignment["gap_probability_points"]) == {"home", "draw", "away"}


def test_natural_cohort_audit_is_local_and_reports_coverage_and_reject_counts(tmp_path: Path):
    prediction, snapshot, evidence, fixture = _inputs()
    cohort_path = tmp_path / "cohort.json"
    prediction_root = tmp_path / "predictions"
    input_root = tmp_path / "input_snapshots"
    evidence_root = tmp_path / "football_evidence"
    prediction_root.mkdir()
    input_root.mkdir()
    evidence_root.mkdir()
    snapshot_path = input_root / "snapshot.json"
    prediction_path = prediction_root / f"{prediction['prediction_id']}.json"
    evidence_path = evidence_root / f"{prediction['prediction_id']}.json"
    snapshot["snapshot_ref"] = str(snapshot_path)
    prediction["input_snapshot"] = {"snapshot_ref": str(snapshot_path)}
    prediction.update(
        {
            "created_at": "2026-09-09T12:00:00+08:00",
            "freeze_created_at": "2026-09-09T12:00:01+08:00",
        }
    )
    cohort_path.write_text(
        json.dumps({"status": "READY", "source": "nowscore_public_jc", "business_date": "2026-09-10", "fixtures": [fixture]}),
        encoding="utf-8",
    )
    prediction_path.write_text(json.dumps(prediction), encoding="utf-8")
    snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")
    evidence_path.write_text(json.dumps(evidence), encoding="utf-8")
    before = {path: path.read_bytes() for path in (prediction_path, snapshot_path, evidence_path)}

    report = run_natural_cohort_audit(
        cohort_path=cohort_path,
        as_of="2026-09-10T12:00:00+08:00",
        prediction_root=prediction_root,
        input_snapshot_root=input_root,
        evidence_root=evidence_root,
    )

    assert report["cohort"]["actual_fixture_count"] == 1
    assert report["coverage"]["projection_success_count"] == 1
    assert report["coverage"]["projection_reject_count"] == 0
    assert report["coverage"]["opponent_names"]["resolved_count"] == 5
    assert report["coverage"]["opponent_names"]["rejected_count"] == 0
    assert report["coverage"]["market_1x2"]["valid_book_count"] == 2
    assert report["coverage"]["model_market_alignment"]["available_count"] == 1
    assert report["rights"]["network_used"] is False
    assert {path: path.read_bytes() for path in before} == before
