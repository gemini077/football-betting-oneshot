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


def test_score_error_taxonomy_distinguishes_selector_override_from_matrix_tail(tmp_path):
    override = _review("FBOS-override", True)
    override["settlement"]["exact_score"]["hit"] = False
    override["model_diagnostics"] = {"actual_score_rank": 3}
    override["score_selection_audit"] = {"selected_score": "2-1", "mathematical_first_score": "1-1"}
    tail = _review("FBOS-tail", True)
    tail["settlement"]["exact_score"]["hit"] = False
    tail["model_diagnostics"] = {"actual_score_rank": 12}
    (tmp_path / "override.json").write_text(json.dumps(override), encoding="utf-8")
    (tmp_path / "tail.json").write_text(json.dumps(tail), encoding="utf-8")

    result = build_metrics(tmp_path, tmp_path / "status.json")

    assert result["error_tags"]["selector_override_error"] == 1
    assert result["error_tags"]["score_matrix_tail_error"] == 1
    assert "score_selector_error" not in result["error_tags"]


def test_metrics_expose_recent_windows_and_score_coverage(tmp_path):
    for index in range(6):
        payload = _review(f"FBOS-{index}", index >= 3)
        payload["match"]["kickoff_local"] = f"2026-07-{index + 10:02d}T03:00:00+08:00"
        payload["model_version"] = "v-test"
        payload["model_diagnostics"] = {"actual_score_rank": index + 1}
        (tmp_path / f"{index}.json").write_text(json.dumps(payload), encoding="utf-8")

    result = build_metrics(tmp_path, tmp_path / "status.json")

    assert result["rolling"]["5"]["primary"]["hit_rate"] == 0.6
    assert result["metrics"]["score_coverage"]["top3"] == 0.5
    assert result["metrics"]["score_coverage"]["top5"] == 0.833333
    assert result["by_model_version"]["v-test"]["primary"]["settled"] == 6

