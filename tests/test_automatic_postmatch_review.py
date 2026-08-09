from pathlib import Path
import sys
import json
from datetime import datetime
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import automatic_postmatch_review as review_module
from automatic_postmatch_review import _primary_settlement, _rich_market_timeline, _rich_root_cause, build_review
from model_governance import build_prediction_record, freeze_prediction


def test_new_review_carries_exact_frozen_prediction_join(tmp_path, monkeypatch):
    payload = {
        "report": {
            "model_version": "v0.19.0",
            "analysis_timestamp": "2026-08-05T00:00:00+08:00",
            "snapshot_timestamp": "2026-08-04T23:59:00+08:00",
            "market_checkpoint": {"captured_at": "2026-08-04T23:59:00+08:00"},
        },
        "match": {
            "canonical_match_id": "FBOS-review-001",
            "home": "Home FC",
            "away": "Away FC",
            "kickoff_local": "2026-08-05T02:00:00+08:00",
        },
        "data_quality": {"missing": []},
        "model": {
            "method": "recent_form_market_calibrated_poisson_v2",
            "lambda_home": 1.2,
            "lambda_away": 0.9,
            "rho": 0.0,
            "probabilities": {"home": 0.45, "draw": 0.3, "away": 0.25},
            "score_probabilities": [{"score": "1-0", "probability": 0.15}],
            "dimension_predictions": {},
        },
        "decisions": {
            "data_grade": "A",
            "unique_primary_dimension": "home",
            "unique_score": "1-0",
        },
        "betting": {"candidates": []},
        "automation": {"prompt_version": "fixed-python-core.none"},
    }
    record_root = tmp_path / "predictions"
    record = build_prediction_record(payload, commit_sha="review-sha")
    freeze_prediction(record, record_root, input_snapshot_root=tmp_path / "snapshots")
    payload["model_governance"] = {
        key: record[key]
        for key in (
            "prediction_id", "prediction_sha256", "model_run_fingerprint", "source_cutoff_at",
            "odds_snapshot_at", "repository_commit_sha",
        )
    }
    monkeypatch.setattr(review_module, "DEFAULT_RECORD_ROOT", record_root)
    monkeypatch.setattr(review_module, "_checkpoint_rows", lambda report: [
        {"captured_at": "2026-08-04T22:00:00+08:00", "decision": {}},
        {"captured_at": "2026-08-04T23:59:00+08:00", "decision": {}},
    ])
    monkeypatch.setattr(review_module, "fetch_postmatch_evidence", lambda report, schedule: {
        "status": "verified",
        "score_90m": "1-0",
        "source_url": "https://example.com/result-a",
        "sources": ["https://example.com/result-a", "https://example.com/result-b"],
    })
    review = build_review(
        {"match_key": "FBOS-review-001", "home": "Home FC", "away": "Away FC", "result_90m": "1-0"},
        payload,
        datetime(2026, 8, 5, 12, tzinfo=ZoneInfo("Asia/Shanghai")),
    )
    assert review["prediction_id"] == record["prediction_id"]
    assert review["prediction_sha256"] == record["prediction_sha256"]
    assert review["model_run_fingerprint"] == record["model_run_fingerprint"]
    assert review["prediction_link_status"] == "verified"


def test_generate_does_not_rewrite_existing_reviewed_schedule(tmp_path, monkeypatch):
    schedule_root = tmp_path / "schedules"
    review_root = tmp_path / "reviews"
    schedule_root.mkdir()
    reviewed = schedule_root / "already-reviewed.json"
    original = {
        "match_key": "already-reviewed",
        "status": "reviewed",
        "result_90m": "1-0",
        "reviewed_at": "2026-07-23T12:00:00+08:00",
    }
    reviewed.write_text(json.dumps(original), encoding="utf-8")

    monkeypatch.setattr(
        review_module,
        "build_review",
        lambda schedule, report, now: (_ for _ in ()).throw(AssertionError("must not rebuild")),
    )

    outcomes = review_module.generate(
        schedule_root,
        review_root,
        datetime(2026, 7, 24, 12, tzinfo=ZoneInfo("Asia/Shanghai")),
    )

    assert outcomes == []
    assert json.loads(reviewed.read_text(encoding="utf-8")) == original


def test_total_goals_primary_dimension_is_strictly_settled():
    pick, actual, hit, market = _primary_settlement("小2.5（方向保留）", 1, 1)
    assert market == "大小球"
    assert pick == "小2.5"
    assert actual == "总进球2"
    assert hit is True


def test_wdl_primary_dimension_remains_supported():
    pick, actual, hit, market = _primary_settlement("胜平负：客胜（模型45.3%）", 0, 2)
    assert market == "胜平负"
    assert pick == "客胜"
    assert actual == "客胜"
    assert hit is True


def test_stable_checkpoint_sequence_is_never_described_as_reversal(monkeypatch):
    rows = [
        {"captured_at": "2026-07-18T16:00:00+08:00", "decision": {"probabilities": {"home": 0.413, "draw": 0.233, "away": 0.354}, "primary_dimension": "胜平负：主胜", "unique_score": "2-1"}},
        {"captured_at": "2026-07-18T20:00:00+08:00", "decision": {"probabilities": {"home": 0.423, "draw": 0.233, "away": 0.344}, "primary_dimension": "胜平负：主胜", "unique_score": "2-1"}},
    ]
    monkeypatch.setattr(review_module, "_checkpoint_rows", lambda report: rows)
    timeline = _rich_market_timeline({"market": {"consensus": {"open": {"home": 1.86, "draw": 3.6, "away": 3.72}, "current": {"home": 1.75, "draw": 3.8, "away": 4.16}}}})
    assert "从未反转" in timeline["判断是否反转"]
    assert "最大变化支持：主胜" in timeline["盘口客观方向"]

    root = _rich_root_cause(
        {"decisions": {"unique_score": "2-1"}, "market": {"consensus": {}}},
        "客胜",
        "4-6",
        ["胜平负首推主胜，实际客胜"],
        "主维度错误",
        {
            "actual_outcome_probability": 0.344,
            "brier_score_1x2": 0.7,
            "log_loss_1x2": 1.067,
            "actual_score_probability": 0.0001,
            "actual_score_rank": 40,
            "lambda_home_residual": 2.3,
            "lambda_away_residual": 4.5,
            "total_goals_residual": 6.8,
        },
        {"status": "verified", "score_half_time": "0-4", "key_events": [], "statistics": {}},
    )
    assert "非临场反转" in root["最可能根因"]
    assert "方向与主维度全程稳定" in root["市场层根因"]
