import json

from review_metrics import build_metrics


def _review(match_id, hit, grade="C"):
    return {
        "MatchID": match_id,
        "match": {"home": "主队", "away": "客队", "kickoff_local": "2026-07-20T03:00:00+08:00"},
        "result": {"score_90m": "1-0"},
        "settlement": {
            "primary": {"hit": hit, "actual": "平局" if not hit else "主胜"},
            "exact_score": {"hit": False}, "total_goals_mode": {"hit": True}, "btts": {"hit": True},
        },
        "data_grade": grade,
        "calibration_weight": 1.0 if grade == "A" else 0.4,
    }


def test_metrics_deduplicate_and_weight(tmp_path):
    (tmp_path / "FBOS-1.json").write_text(json.dumps(_review("FBOS-1", True)), encoding="utf-8")
    (tmp_path / "fixture-1.json").write_text(json.dumps(_review("fixture-1", False)), encoding="utf-8")
    result = build_metrics(tmp_path, tmp_path / "status.json")
    assert result["scope"]["deduplicated_matches"] == 2
    assert result["metrics"]["primary"]["settled"] == 2
    assert result["error_tags"]["score_selector_error"] == 2

