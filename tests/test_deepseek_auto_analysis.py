import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from deepseek_auto_analysis import normalize_analysis, request_from_event, validate_request  # noqa: E402


def test_issue_request_is_parsed_and_validated(tmp_path):
    event = {
        "issue": {
            "body": "match_id: 2040508\nbusiness_date: 2026-07-15\nmatch: 英格兰 vs 阿根廷\n"
        }
    }
    path = tmp_path / "event.json"
    path.write_text(json.dumps(event, ensure_ascii=False), encoding="utf-8")
    assert request_from_event(path) == {
        "match_id": "2040508", "business_date": "2026-07-15", "match": "英格兰 vs 阿根廷"
    }


def test_invalid_request_is_rejected():
    try:
        validate_request({"business_date": "today", "match": "甲 vs 乙", "match_id": "1"})
    except ValueError as error:
        assert "YYYY-MM-DD" in str(error)
    else:
        raise AssertionError("invalid date was accepted")


def test_normalizer_cannot_create_execution_or_locked_bets():
    raw = {
        "model": {"probabilities": {"home": 0.9, "draw": 0.4, "away": 0.2}},
        "decisions": {"unique_primary_dimension": "主胜", "unique_score": "2-0", "value_judgement": "候选"},
        "betting": {"candidates": [{"status": "已锁单"}], "open_bets": [{"id": "bad"}], "state": "已锁单"},
    }
    result = normalize_analysis(
        raw,
        {"business_date": "2026-07-15", "match_id": "1", "match": "甲 vs 乙"},
        "deepseek-v4-pro",
    )
    assert result["model"]["probabilities"] is None
    assert result["betting"]["candidates"] == []
    assert "open_bets" not in result["betting"]
    assert result["betting"]["execution_authorized"] is False
    assert result["betting"]["lock_state_changed"] is False
    assert result["decisions"]["final_state"].endswith("未锁单")


def test_normalizer_accepts_string_sections_from_provider():
    result = normalize_analysis(
        {
            "report": "辅助摘要",
            "match": "主队 vs 客队",
            "decisions": "方向不明",
            "model": "数据不足",
            "betting": "不投注",
            "data_quality": "缺数据",
            "fundamentals": [],
            "evidence_chain": "无",
        },
        {"business_date": "2026-07-15", "match_id": "2040513", "match": "主队 vs 客队"},
        "deepseek-v4-pro",
    )
    assert result["report"]["ai_summary"] == "辅助摘要"
    assert result["match"]["home"] == "主队"
    assert result["betting"]["candidates"] == []
    assert result["betting"]["execution_authorized"] is False
    assert isinstance(result["data_quality"], dict)
    assert isinstance(result["evidence_chain"], list)
