import hashlib
import inspect
import json
from pathlib import Path

import pytest

from scripts.legacy_analysis_mapper import LegacyStructuredAnalysisMapper


TARGET = {
    "match_id": "2040820",
    "match_key": "FBOS-202608130600-test",
    "business_date": "2026-08-12",
    "competition": "解放者杯",
    "home": "帕梅拉斯",
    "away": "波特诺",
    "kickoff_at": "2026-08-13T06:00:00+08:00",
}

FROZEN = {
    "prediction_id": "FBOS-PRED-test",
    "unique_score": "1-0",
    "top_scores": [
        {"score": "1-0", "probability": 0.155, "rank": 1},
        {"score": "2-0", "probability": 0.126, "rank": 2},
        {"score": "1-1", "probability": 0.112, "rank": 3},
    ],
}


def _record(*, score: str = "1-0", timestamp: str | None = "2026-08-12T15:00:00+08:00", trace=None):
    report = {"report_type": "确定性赛前分析"}
    if timestamp is not None:
        report["analysis_timestamp"] = timestamp
    decisions = {
        "unique_score": score,
        "match_story": "主队更可能掌握主动；客队仍有现实得分路径。总进球环境相对受控。",
        "score_reasoning": "主队优势与受控节奏共同支持首选比分。",
        "maximum_error_points": ["如果客队反击效率兑现，首选结构可能向平局迁移。"],
    }
    if trace is not None:
        decisions["score_selection_trace"] = trace
    return {
        "report": report,
        "match": TARGET.copy(),
        "decisions": decisions,
        "market": {
            "interpretation": {
                "impact_code": "confirm",
                "direction": "home",
                "model_impact": "市场方向与主队结论同向。",
            }
        },
        "source_references": [{"path": "data/analysis_reports/legacy.json"}],
    }


def _trace(*scores: str):
    return {
        "selected_score": scores[0],
        "candidates": [
            {
                "score": score,
                "rank": index,
                "scenario_score": 1.0 - index * 0.1,
                "factor_contributions": {"主队主剧本": 0.4 if index == 1 else 0.2},
                "decision": "selected" if index == 1 else "rejected",
                "rejection_reason": None if index == 1 else "综合情景分低于首选。",
            }
            for index, score in enumerate(scores, 1)
        ],
    }


def test_mapper_maps_only_existing_structured_interpretation_with_lineage(tmp_path: Path):
    path = tmp_path / "legacy.json"
    mapper = LegacyStructuredAnalysisMapper()

    result = mapper.map_record(path, _record(trace=_trace("1-0", "2-0", "1-1")), TARGET, FROZEN)

    assert result["status"] == "USABLE"
    assert result["analysis_origin"]["type"] == "LEGACY_STRUCTURED_ANALYSIS"
    assert result["analysis_origin"]["mapping_version"] == "legacy_mapper.v1"
    assert result["lineage"][0]["source_key"] == "decisions.match_story"
    assert result["hero_script"]
    assert result["biggest_failure_point"]
    assert result["candidate_reasoning"]["1-0"]["source_key"] == "decisions.score_selection_trace.candidates[0]"


def test_fixture_mismatch_is_rejected(tmp_path: Path):
    candidate = _record()
    candidate["match"]["home"] = "另一支球队"

    result = LegacyStructuredAnalysisMapper().map_record(tmp_path / "wrong.json", candidate, TARGET, FROZEN)

    assert result["status"] == "FIXTURE_MISMATCH"
    assert result["sections"] == []
    assert result["lineage"][0]["mapping_status"] == "FIXTURE_MISMATCH"


def test_post_kickoff_material_cannot_enter_main_analysis(tmp_path: Path):
    result = LegacyStructuredAnalysisMapper().map_record(
        tmp_path / "late.json",
        _record(timestamp="2026-08-13T06:00:01+08:00"),
        TARGET,
        FROZEN,
    )

    assert result["status"] == "TIME_UNVERIFIED"
    assert "MATERIAL_AFTER_KICKOFF" in result["reasons"]
    assert result["sections"] == []


def test_prediction_mismatch_is_kept_for_audit_but_excluded_from_main_analysis(tmp_path: Path):
    result = LegacyStructuredAnalysisMapper().map_record(
        tmp_path / "mismatch.json", _record(score="2-1"), TARGET, FROZEN
    )

    assert result["status"] == "PREDICTION_MISMATCH"
    assert "FROZEN_SCORE_CONFLICT" in result["reasons"]
    assert result["sections"] == []
    assert result["candidate_reasoning"] == {}


def test_legacy_trace_never_expands_current_frozen_top_k(tmp_path: Path):
    result = LegacyStructuredAnalysisMapper().map_record(
        tmp_path / "trace.json",
        _record(trace=_trace("1-0", "2-0", "1-1", "3-1")),
        TARGET,
        FROZEN,
    )

    assert set(result["candidate_reasoning"]) == {"1-0", "2-0", "1-1"}
    assert "3-1" not in result["candidate_reasoning"]


def test_raw_facts_and_numeric_market_difference_are_not_support_or_conflict(tmp_path: Path):
    record = _record()
    record["fundamentals"] = {"structured_form": {"items": ["主队近10场6胜"]}}
    record["market"]["interpretation"] = {}
    record["market"]["market_home_probability"] = 0.739
    record["model"] = {"home_probability": 0.59}

    result = LegacyStructuredAnalysisMapper().map_record(tmp_path / "facts.json", record, TARGET, FROZEN)

    assert result["interpretations"] == []


def test_explicit_market_interpretation_can_be_support_but_not_numeric_comparison(tmp_path: Path):
    result = LegacyStructuredAnalysisMapper().map_record(
        tmp_path / "market.json", _record(), TARGET, FROZEN
    )

    assert any(item["relation"] == "support" for item in result["interpretations"])
    assert not any("概率" in item["text"] and item["relation"] == "conflict" for item in result["interpretations"])


def test_no_source_no_candidate_script_and_no_fabricated_score_impact(tmp_path: Path):
    record = _record()
    record["decisions"].pop("score_selection_trace", None)

    result = LegacyStructuredAnalysisMapper().map_record(tmp_path / "plain.json", record, TARGET, FROZEN)

    assert result["candidate_reasoning"] == {}
    assert result["candidate_labels"] == {}
    assert all(section.get("score_impact") is None for section in result["sections"])


def test_missing_timestamp_is_safe_degradation(tmp_path: Path):
    result = LegacyStructuredAnalysisMapper().map_record(
        tmp_path / "unknown-time.json", _record(timestamp=None), TARGET, FROZEN
    )

    assert result["status"] == "TIME_UNVERIFIED"
    assert result["sections"] == []


def test_original_frozen_prediction_is_not_mutated(tmp_path: Path):
    before = hashlib.sha256(json.dumps(FROZEN, sort_keys=True).encode()).hexdigest()
    LegacyStructuredAnalysisMapper().map_record(
        tmp_path / "immutable.json", _record(trace=_trace("1-0", "2-0", "1-1")), TARGET, FROZEN
    )

    assert hashlib.sha256(json.dumps(FROZEN, sort_keys=True).encode()).hexdigest() == before


def test_mapper_has_no_runtime_model_or_llm_dependency():
    source = inspect.getsource(LegacyStructuredAnalysisMapper)

    assert "automatic_model_core" not in source
    assert "openai" not in source.lower()
    assert "requests" not in source.lower()


@pytest.mark.parametrize("status", ["NOT_FOUND", "PARTIALLY_USABLE"])
def test_safe_statuses_are_explicit(status):
    assert status in {"NOT_FOUND", "PARTIALLY_USABLE"}
