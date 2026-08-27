import sys
from datetime import timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from prematch_information_root_cause_audit import (  # noqa: E402
    extract_prematch_evidence,
    parse_aware,
    run_audit,
    select_latest_legal_formal,
)


def _prediction(
    prediction_id,
    match_key="M-1",
    created="2026-08-13T10:00:00+00:00",
    snapshot_ref="data/model_governance/input_snapshots/s1.json",
):
    return {
        "prediction_id": prediction_id,
        "match_key": match_key,
        "prediction_status": "formal",
        "formal_eligible": True,
        "prediction_created_at": created,
        "model_input_snapshot_ref": snapshot_ref,
        "lambda_home": 1.2,
        "lambda_away": 1.4,
        "prediction_output": {
            "expected_goals": 2.6,
            "lambda_home": 1.2,
            "lambda_away": 1.4,
            "probabilities": {"home": 0.4, "draw": 0.3, "away": 0.3},
            "unique_score": "1-1",
        },
    }


def _snapshot():
    form = {
        "home_overall": {"matches": 10, "goals_for": 12, "goals_against": 10},
        "home_home": {"matches": 10, "goals_for": 20, "goals_against": 9},
        "away_overall": {"matches": 10, "goals_for": 23, "goals_against": 11},
        "away_away": {"matches": 10, "goals_for": 25, "goals_against": 10},
    }
    return {
        "snapshot_ref": "s1",
        "input": {
            "source_snapshots": {
                "nowscore": {
                    "snapshots": [
                        {
                            "shuju": {"recent_form": form},
                            "daxiao": {
                                "companies": [
                                    {"current_line": 3.0, "open_line": 2.5, "current_over_water": 0.9, "current_under_water": 0.9},
                                    {"current_line": 3.5, "open_line": 3.0, "current_over_water": 1.0, "current_under_water": 0.8},
                                    {"current_line": 3.0, "open_line": 3.0, "current_over_water": 0.95, "current_under_water": 0.85},
                                ]
                            },
                            "yazhi": {"companies": [{"current_handicap": -1.0}, {"current_handicap": -1.5}]},
                            "ouzhi": {
                                "bookmakers": [
                                    {"spf_current": {"home": 1.8, "draw": 3.6, "away": 4.5}},
                                    {"spf_current": {"home": 1.9, "draw": 3.5, "away": 4.2}},
                                ]
                            },
                            "nowscore_context": {"coach": {}, "referee": {}, "panlu": {}},
                        }
                    ]
                }
            }
        },
    }


def test_parse_aware_requires_explicit_timezone():
    assert parse_aware("2026-08-13T10:00:00+00:00").tzinfo == timezone.utc
    assert parse_aware("2026-08-13 18:00") is None


def test_latest_legal_is_strict_prematch_and_deterministic():
    results = [{"match_key": "M-1", "kickoff_local": "2026-08-13T12:00:00+00:00"}]
    rows = [
        _prediction("late", created="2026-08-13T11:00:00+00:00"),
        _prediction("after", created="2026-08-13T12:00:00+00:00"),
        _prediction("naive", created="2026-08-13 11:30:00"),
    ]
    selected, audit = select_latest_legal_formal(rows, results)
    assert selected["M-1"]["prediction_id"] == "late"
    assert audit["raw_formal_rows"] == 3
    assert audit["legal_formal_rows"] == 1
    assert audit["excluded_rows"] == 2


def test_feature_extraction_reproduces_total_formula_and_market_roles():
    evidence = extract_prematch_evidence(_prediction("p1"), _snapshot())
    assert evidence["form"]["home"] == 1.383333
    assert evidence["form"]["away"] == 1.683333
    assert evidence["form"]["total"] == 3.066667
    assert evidence["market_total"]["median"] == 3.0
    assert evidence["preblend_total"] == 3.04
    assert evidence["market_handicap"]["median"] == -1.25
    assert evidence["market_total"]["water_semantics"] == "asian_water_not_decimal_probability"
    assert evidence["usage"]["market_total_in_lambda"] is True
    assert evidence["usage"]["market_total_weight"] == 0.4
    assert evidence["usage"]["asian_handicap_in_lambda"] is False


def test_extraction_does_not_use_postmatch_fields():
    snapshot = _snapshot()
    snapshot["actual_score"] = "9-9"
    evidence = extract_prematch_evidence(_prediction("p1"), snapshot)
    assert "actual_score" not in evidence
    assert "result" not in evidence


def test_audit_reports_mismatch_and_no_environment_hypothesis():
    pred = _prediction("p1")
    pred["lambda_home"] = 1.2
    pred["lambda_away"] = 1.4
    pred["prediction_output"]["expected_goals"] = 2.6
    result = {
        "match_key": "M-1",
        "kickoff_local": "2026-08-13T12:00:00+00:00",
        "home": "Home",
        "away": "Away",
        "home_score": 3,
        "away_score": 2,
    }
    report = run_audit([pred], [result], {"s1.json": _snapshot()}, source_commit="TEST")
    assert report["sample_selection"]["unique_latest_legal_matches"] == 1
    assert report["aggregates"]["mismatch_cohort_a"]["count"] == 1
    assert report["decision"]["model_decision"] == "NO_MODEL_CHANGE"
    assert "dynamic_total_goals_regime_v1" not in str(report)


def test_missing_snapshot_is_reported_not_filled():
    row = _prediction("p1", snapshot_ref="data/model_governance/input_snapshots/missing.json")
    result = {"match_key": "M-1", "kickoff_local": "2026-08-13T12:00:00+00:00", "home_score": 0, "away_score": 0}
    report = run_audit([row], [result], {}, source_commit="TEST")
    assert report["aggregates"]["snapshot_join"]["missing_snapshot"] == 1
    assert report["sample_selection"]["unique_latest_legal_matches"] == 1


def test_result_categories_use_locked_close_win_margin_two():
    pred = _prediction("p1")
    result = {"match_key": "M-1", "kickoff_local": "2026-08-13T12:00:00+00:00", "home_score": 3, "away_score": 1}
    report = run_audit([pred], [result], {"s1.json": _snapshot()}, source_commit="TEST")
    assert report["case_categories"]["high_scoring_close_win"] == 1
    assert report["policy"]["close_win_margin"] == 2
