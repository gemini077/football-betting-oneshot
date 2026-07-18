import json
from datetime import datetime, timedelta, timezone

from sync_result_schedules import sync_date


SHANGHAI = timezone(timedelta(hours=8))


def test_every_sold_fixture_gets_a_result_task(tmp_path):
    updates = tmp_path / "updates" / "run"
    updates.mkdir(parents=True)
    (updates / "run_sporttery_2026-07-18.json").write_text(json.dumps({
        "success": True,
        "matches": [{
            "matchId": "500-123", "matchNum": "周六101",
            "homeTeam": "主队", "awayTeam": "客队", "league": "测试联赛",
            "businessDate": "2026-07-18", "matchDate": "2026-07-18", "matchTime": "18:30",
            "shujuId": 123, "nowscoreId": 456,
        }],
    }, ensure_ascii=False), encoding="utf-8")
    schedules = tmp_path / "schedules"

    outcome = sync_date("2026-07-18", datetime(2026, 7, 18, 12, tzinfo=SHANGHAI), schedules, tmp_path / "updates")
    saved = json.loads(next(schedules.glob("*.json")).read_text(encoding="utf-8"))

    assert outcome == {"fixtures": 1, "created": 1, "updated": 0}
    assert saved["nowscore_id"] == 456
    assert saved["analysis_available"] is False
    assert saved["review_due_at"] == "2026-07-18T20:45:00+08:00"


def test_sync_preserves_frozen_report_and_resets_old_pre_kickoff_attempt(tmp_path):
    updates = tmp_path / "updates" / "run"
    updates.mkdir(parents=True)
    payload = {
        "success": True,
        "matches": [{
            "matchId": "500-123", "homeTeam": "主队", "awayTeam": "客队",
            "businessDate": "2026-07-18", "matchDate": "2026-07-18", "matchTime": "18:30",
            "shujuId": 123, "nowscoreId": 456,
        }],
    }
    (updates / "run_sporttery_2026-07-18.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    schedules = tmp_path / "schedules"
    sync_date("2026-07-18", datetime(2026, 7, 18, 10, tzinfo=SHANGHAI), schedules, tmp_path / "updates")
    path = next(schedules.glob("*.json"))
    current = json.loads(path.read_text(encoding="utf-8"))
    current.update({
        "source_report": "data/analysis_reports/report.json",
        "status": "blocked_result_not_final",
        "verification_attempts": 2,
        "last_checked_at": "2026-07-18T12:00:00+08:00",
        "last_error": "result_not_final",
    })
    path.write_text(json.dumps(current), encoding="utf-8")

    sync_date("2026-07-18", datetime(2026, 7, 18, 13, tzinfo=SHANGHAI), schedules, tmp_path / "updates")
    saved = json.loads(path.read_text(encoding="utf-8"))

    assert saved["source_report"] == "data/analysis_reports/report.json"
    assert saved["analysis_available"] is True
    assert saved["status"] == "scheduled"
    assert saved["verification_attempts"] == 0
    assert "last_checked_at" not in saved


def test_sync_resets_future_blocked_state_even_without_last_checked_at(tmp_path):
    updates = tmp_path / "updates" / "run"
    updates.mkdir(parents=True)
    payload = {"success": True, "matches": [{
        "matchId": "500-123", "homeTeam": "主队", "awayTeam": "客队",
        "businessDate": "2026-07-18", "matchDate": "2026-07-19", "matchTime": "05:00",
        "shujuId": 123, "nowscoreId": 456,
    }]}
    (updates / "run_sporttery_2026-07-18.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    schedules = tmp_path / "schedules"
    sync_date("2026-07-18", datetime(2026, 7, 18, 10, tzinfo=SHANGHAI), schedules, tmp_path / "updates")
    path = next(schedules.glob("*.json"))
    current = json.loads(path.read_text(encoding="utf-8"))
    current.update({"status": "blocked_result_not_final", "verification_attempts": 7})
    path.write_text(json.dumps(current), encoding="utf-8")

    sync_date("2026-07-18", datetime(2026, 7, 18, 23, tzinfo=SHANGHAI), schedules, tmp_path / "updates")
    saved = json.loads(path.read_text(encoding="utf-8"))

    assert saved["status"] == "scheduled"
    assert saved["verification_attempts"] == 0
