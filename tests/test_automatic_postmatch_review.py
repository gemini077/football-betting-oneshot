from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import automatic_postmatch_review as review_module
from automatic_postmatch_review import _primary_settlement, _rich_market_timeline, _rich_root_cause


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
