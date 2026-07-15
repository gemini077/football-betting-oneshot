import json
from datetime import datetime
from pathlib import Path

from automatic_postmatch_review import build_review, generate
from postmatch_queue import SHANGHAI


def report():
    return {
        "match": {"home": "甲队", "away": "乙队", "kickoff_local": "2026-07-15 20:00"},
        "model": {
            "probabilities": {"home": 0.51, "draw": 0.26, "away": 0.23},
            "score_probabilities": [{"score": "2-1", "probability": 0.12}],
            "total_goals_buckets": [{"goals": "2", "probability": 0.27}, {"goals": "3", "probability": 0.25}],
            "btts": {"yes": 0.56, "no": 0.44},
        },
        "decisions": {
            "unique_primary_dimension": "胜平负：主胜（模型51.0%）",
            "unique_score": "2-1",
            "mathematical_first": "主胜51%",
            "maximum_error_points": ["主队终结效率回落"],
        },
        "data_quality": {"status": "完整"},
    }


def test_adjacent_score_is_strictly_not_a_hit():
    schedule = {"match_key": "fixture:test", "home": "甲队", "away": "乙队", "result_90m": "1-0"}
    review = build_review(schedule, report(), datetime(2026, 7, 15, tzinfo=SHANGHAI))
    assert review["settlement"]["primary"]["hit"] is True
    assert review["settlement"]["exact_score"]["hit"] is False
    assert review["比分是否命中"] == "未命中"
    assert "相邻比分不计命中" in "；".join(review["errors"])


def test_generate_updates_schedule_and_writes_flat_review(tmp_path: Path):
    schedules = tmp_path / "schedules"
    reviews = tmp_path / "reviews"
    reports = tmp_path / "reports"
    schedules.mkdir(); reports.mkdir()
    source = reports / "report.json"
    source.write_text(json.dumps(report(), ensure_ascii=False), encoding="utf-8")
    schedule = {
        "match_key": "fixture:test", "home": "甲队", "away": "乙队", "status": "result_verified",
        "result_90m": "1-0", "source_report": str(source),
    }
    path = schedules / "fixture_test.json"
    path.write_text(json.dumps(schedule, ensure_ascii=False), encoding="utf-8")
    rows = generate(schedules, reviews, datetime(2026, 7, 15, tzinfo=SHANGHAI))
    assert rows[0]["status"] == "reviewed"
    assert json.loads(path.read_text(encoding="utf-8"))["status"] == "reviewed"
    saved = json.loads(next(reviews.glob("*.json")).read_text(encoding="utf-8"))
    assert saved["result"]["scope"].startswith("90分钟")
