from pathlib import Path
import json

import pytest

from scripts.scoring_regime_audit import (
    bootstrap_proportion_difference,
    build_report,
    classify_score,
    dedupe_results,
    load_verified_results,
    select_latest_legal_formal,
    summarize_window,
)


def result(tmp_path, name, **overrides):
    row = {
        "match_key": "M-1",
        "kickoff_local": "2026-07-29T12:00:00+08:00",
        "result_90m": "3-2",
        "home_score": 3,
        "away_score": 2,
        "scope": "regulation_90m_plus_stoppage",
        "verification_quality": "authoritative_primary",
    }
    row.update(overrides)
    path = tmp_path / name
    path.write_text(json.dumps(row), encoding="utf-8")
    return path


def test_classification_definitions_are_locked():
    assert classify_score(4, 0)["high_total"] is True
    assert classify_score(4, 0)["big_margin_win"] is True
    assert classify_score(2, 2)["high_scoring_draw"] is True
    assert classify_score(3, 2)["high_scoring_close_win"] is True
    assert classify_score(1, 0)["high_total"] is False
    assert classify_score(1, 0)["high_scoring_close_win"] is False


def test_verified_results_require_aware_time_and_dedupe_same_match(tmp_path):
    result(tmp_path, "a.json")
    result(tmp_path, "b.json", verified_at="2026-07-29T13:00:00+08:00")
    result(tmp_path, "naive.json", match_key="M-2", kickoff_local="2026-07-29T12:00:00")
    loaded = load_verified_results(tmp_path)
    assert loaded["raw_file_count"] == 3
    assert len(loaded["rows"]) == 2
    unique = dedupe_results(loaded["rows"])
    assert len(unique["rows"]) == 1
    assert unique["duplicate_rows"] == 1


def test_conflicting_result_identity_is_fail_closed(tmp_path):
    result(tmp_path, "a.json")
    result(tmp_path, "b.json", home_score=4, away_score=1, result_90m="4-1")
    loaded = load_verified_results(tmp_path)
    unique = dedupe_results(loaded["rows"])
    assert unique["rows"] == []
    assert unique["conflict_match_count"] == 1


def test_latest_legal_formal_is_timezone_aware_and_deterministic():
    records = [
        {
            "prediction_id": "old",
            "match_key": "M-1",
            "formal_eligible": True,
            "model_role": "champion",
            "kickoff_at": "2026-08-01T12:00:00+08:00",
            "freeze_created_at": "2026-08-01T03:00:00+00:00",
            "actual": {"home_score": 9},
        },
        {
            "prediction_id": "new",
            "match_key": "M-1",
            "formal_eligible": True,
            "model_role": "champion",
            "kickoff_at": "2026-08-01T12:00:00+08:00",
            "freeze_created_at": "2026-08-01T03:30:00+00:00",
            "actual": {"home_score": 0},
        },
        {
            "prediction_id": "after",
            "match_key": "M-1",
            "formal_eligible": True,
            "model_role": "champion",
            "kickoff_at": "2026-08-01T12:00:00+08:00",
            "freeze_created_at": "2026-08-01T13:00:00+00:00",
        },
        {
            "prediction_id": "missing-id",
            "formal_eligible": True,
            "model_role": "champion",
            "kickoff_at": "2026-08-01T12:00:00+08:00",
            "freeze_created_at": "2026-08-01T03:45:00+00:00",
        },
    ]
    selected = select_latest_legal_formal(records)
    assert selected["records"]["M-1"]["prediction_id"] == "new"
    assert selected["raw_formal_eligible_count"] == 4
    assert selected["legal_record_count"] == 2
    assert selected["unique_match_count"] == 1
    assert selected["superseded_record_count"] == 1


def test_missing_or_naive_formal_identity_is_not_a_match():
    selected = select_latest_legal_formal(
        [
            {
                "prediction_id": "missing-match",
                "formal_eligible": True,
                "model_role": "champion",
                "kickoff_at": "2026-08-01T12:00:00+08:00",
                "freeze_created_at": "2026-08-01T10:00:00+00:00",
            },
            {
                "prediction_id": "naive-time",
                "match_key": "M-2",
                "formal_eligible": True,
                "model_role": "champion",
                "kickoff_at": "2026-08-01T12:00:00",
                "freeze_created_at": "2026-08-01T10:00:00",
            },
        ]
    )
    assert selected["records"] == {}
    assert selected["invalid_record_count"] == 2


def test_window_summary_and_bins():
    rows = [
        {"date": "2026-08-01", "home_score": 1, "away_score": 1, "match_key": "a"},
        {"date": "2026-08-02", "home_score": 4, "away_score": 0, "match_key": "b"},
        {"date": "2026-08-03", "home_score": 3, "away_score": 2, "match_key": "c"},
    ]
    summary = summarize_window(rows, "test", "2026-08-01", "2026-08-03")
    assert summary["n"] == 3
    assert summary["counts"]["high_total"] == 2
    assert summary["total_bins"]["0-2"]["count"] == 1
    assert summary["total_bins"]["5+"]["count"] == 1


def test_bootstrap_is_deterministic_and_reports_recent_minus_prior():
    recent = [True, True, False, True]
    prior = [False, False, True, False]
    one = bootstrap_proportion_difference(recent, prior, seed=20260827, resamples=500)
    two = bootstrap_proportion_difference(recent, prior, seed=20260827, resamples=500)
    assert one == two
    assert one["point_difference"] == pytest.approx(0.5)
    assert one["comparison_label"] == "recent_minus_prior"
    assert len(one["ci95"]) == 2


def test_report_has_explicit_no_change_decision_and_temporal_comparison(tmp_path):
    result(tmp_path, "only.json")
    report = build_report(tmp_path, source_commit="SOURCE")
    assert report["model_decision"] == "NO_MODEL_CHANGE"
    assert "underweighted prematch information" in report["decision_reason"]
    assert "future_hypothesis" not in report
    assert set(report["complete_recent_late_minus_early_bootstrap"]) == {
        "high_total",
        "big_margin_win",
        "high_scoring_draw",
        "high_scoring_close_win",
    }
