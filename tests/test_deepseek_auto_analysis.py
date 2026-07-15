import json
import sys
from types import SimpleNamespace
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from deepseek_auto_analysis import (  # noqa: E402
    attach_workspace_evidence,
    devig_three_way,
    fetch_date_for_request,
    has_minimum_analysis_evidence,
    normalize_analysis,
    report_manifest,
    request_from_event,
    run_json_command,
    validate_request,
)


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
    assert result["model"]["btts"]["judgement"] == "数据不足，暂不判断"


def test_normalizer_filters_nested_non_object_rows():
    result = normalize_analysis(
        {
            "model": {
                "probabilities": {"home": 0.4, "draw": 0.3, "away": 0.3},
                "btts": None,
                "score_probabilities": ["1-0", {"score": "1-0", "probability": 0.1}],
                "total_goals_buckets": [None, {"bucket": "0-2", "probability": 0.5}],
            },
            "fundamentals": {"items": ["伤停未知", {"label": "伤停", "value": "未知"}]},
            "evidence_chain": ["市场", {"title": "市场", "items": []}],
        },
        {"business_date": "2026-07-15", "match_id": "2040513", "match": "主队 vs 客队"},
        "deepseek-v4-pro",
    )
    assert len(result["model"]["score_probabilities"]) == 1
    assert len(result["model"]["total_goals_buckets"]) == 1
    assert len(result["fundamentals"]["items"]) == 1
    assert len(result["evidence_chain"]) == 1


def test_normalizer_replaces_provider_sentinel_values():
    result = normalize_analysis(
        {
            "decisions": {
                "unique_primary_dimension": "NONE",
                "unique_score": -999,
                "mathematical_first": "NO_DATA",
                "market_first": "INSUFFICIENT_DATA",
                "value_judgement": None,
                "maximum_error_points": [{"type": "NO_DATA", "value": 1.0}],
            }
        },
        {"business_date": "2026-07-15", "match_id": "2040514", "match": "苏捷斯卡 vs 阿拉木图"},
        "deepseek-v4-pro",
    )
    assert result["decisions"]["unique_primary_dimension"] == "数据不足，暂不形成结论"
    assert result["decisions"]["unique_score"] == "数据不足，暂不形成结论"
    assert result["decisions"]["maximum_error_points"] == ["输入数据不足，无法形成模型结论"]


def test_normalizer_rejects_non_score_numeric_value():
    result = normalize_analysis(
        {"decisions": {"unique_score": 0.1}},
        {"business_date": "2026-07-15", "match_id": "2040513", "match": "比森 vs 克拉克斯"},
        "deepseek-v4-pro",
    )
    assert result["decisions"]["unique_score"] == "数据不足，暂不形成结论"


def test_workspace_official_odds_create_market_baseline_without_model_probability():
    workspace = {
        "id": "2040514", "home": "苏捷斯卡", "away": "阿拉木图", "league": "欧冠",
        "kickoff": "2026-07-16 03:00", "business_date": "2026-07-15",
        "spf": {"home": 4.35, "draw": 3.7, "away": 1.59},
        "rqspf": {"handicap": 1, "home": 2.07, "draw": 3.34, "away": 2.88},
    }
    baseline = devig_three_way(workspace["spf"])
    context = {"selected_workspace_match": workspace, "official_market_baseline": baseline, "source_snapshots": {}}
    analysis = normalize_analysis({}, {"business_date": "2026-07-15", "match_id": "2040514", "match": "苏捷斯卡 vs 阿拉木图"}, "deepseek-v4-pro")
    enriched = attach_workspace_evidence(analysis, context)
    assert enriched["market"]["official_spf"]["away"] == 1.59
    assert enriched["model"]["probabilities"] is None
    assert "客胜" in enriched["decisions"]["market_first"]
    assert has_minimum_analysis_evidence(context)


def test_empty_context_is_not_publishable():
    assert not has_minimum_analysis_evidence({"official_market_baseline": None, "source_snapshots": {}})


def test_fetch_uses_kickoff_date_for_after_midnight_match(monkeypatch):
    monkeypatch.setattr(
        "deepseek_auto_analysis.selected_workspace_match",
        lambda request: {"kickoff": "2026-07-16 03:00"},
    )
    assert fetch_date_for_request({"business_date": "2026-07-15"}) == "2026-07-15"


def test_analysis_workflow_does_not_try_to_push_workflow_files():
    workflow = (ROOT / ".github" / "workflows" / "analyze-selected.yml").read_text(encoding="utf-8")
    save_step = workflow.split("git add", 1)[1].split("\n", 1)[0]
    assert ".github/workflows" not in save_step


def test_json_command_accepts_progress_before_final_envelope(monkeypatch):
    monkeypatch.setattr(
        "deepseek_auto_analysis.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout='[FETCH] source\n{"manifest":"ok.json"}\n', stderr=""),
    )
    assert run_json_command(["python", "fetch.py"])["manifest"] == "ok.json"


def test_report_manifest_uses_same_fallback_as_model(tmp_path):
    source = tmp_path / "manifest.json"
    source.write_text(json.dumps({"sources": {"500_deep": {"matches": [{"shuju_id": 1, "file": "empty.json"}]}}}), encoding="utf-8")
    context = {"source_snapshots": {"500_deep": {"metadata": {"fallback_file": "data/source_cache/deep_fallback/1.json"}}}}
    output = report_manifest(source, context)
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["sources"]["500_deep"]["status"] == "VERIFIED_LOCAL_FALLBACK"
    assert payload["sources"]["500_deep"]["matches"][0]["file"].endswith("1.json")
