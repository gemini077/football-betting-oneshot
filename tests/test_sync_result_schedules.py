import json
from datetime import datetime, timedelta, timezone

import sync_result_schedules
from sync_result_schedules import recover_overdue_schedules, sync_date


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

    outcome = sync_date("2026-07-18", datetime(2026, 7, 18, 12, tzinfo=SHANGHAI), schedules, tmp_path / "updates", tmp_path / "universe")
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
    sync_date("2026-07-18", datetime(2026, 7, 18, 10, tzinfo=SHANGHAI), schedules, tmp_path / "updates", tmp_path / "universe")
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

    sync_date("2026-07-18", datetime(2026, 7, 18, 13, tzinfo=SHANGHAI), schedules, tmp_path / "updates", tmp_path / "universe")
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
    sync_date("2026-07-18", datetime(2026, 7, 18, 10, tzinfo=SHANGHAI), schedules, tmp_path / "updates", tmp_path / "universe")
    path = next(schedules.glob("*.json"))
    current = json.loads(path.read_text(encoding="utf-8"))
    current.update({"status": "blocked_result_not_final", "verification_attempts": 7})
    path.write_text(json.dumps(current), encoding="utf-8")

    sync_date("2026-07-18", datetime(2026, 7, 18, 23, tzinfo=SHANGHAI), schedules, tmp_path / "updates", tmp_path / "universe")
    saved = json.loads(path.read_text(encoding="utf-8"))

    assert saved["status"] == "scheduled"
    assert saved["verification_attempts"] == 0


def test_selected_match_queue_recovers_result_task_without_full_schedule(tmp_path, monkeypatch):
    updates = tmp_path / "updates"
    updates.mkdir()
    queue_path = tmp_path / "queue.json"
    queue_path.write_text(json.dumps({"pending": [{
        "home": "主队", "away": "客队", "kickoff_local": "2026-07-18T18:30:00+08:00",
        "shuju_id": 789, "source_report": "data/analysis_reports/current/report.json",
    }]}), encoding="utf-8")
    monkeypatch.setattr(sync_result_schedules, "POSTMATCH_QUEUE_PATH", queue_path)
    schedules = tmp_path / "schedules"

    outcome = sync_date("2026-07-18", datetime(2026, 7, 18, 20, tzinfo=SHANGHAI), schedules, updates, tmp_path / "universe")
    saved = json.loads(next(schedules.glob("*.json")).read_text(encoding="utf-8"))

    assert outcome["fixtures"] == 0
    assert outcome["created"] == 1
    assert saved["nowscore_id"] == 789
    assert saved["analysis_available"] is True

def test_canonical_prediction_universe_is_primary_result_schedule_authority(tmp_path):
    universe = tmp_path / "universe"
    universe.mkdir()
    (universe / "2026-09-12.json").write_text(json.dumps({
        "schema_version": "1.0",
        "business_date": "2026-09-12",
        "status": "READY",
        "source": "nowscore_public_jc",
        "fixtures": [{
            "matchId": "3003885",
            "matchNum": "周六016",
            "businessDate": "2026-09-12",
            "matchDate": "2026-09-12",
            "matchTime": "22:00",
            "league": "英超",
            "homeTeam": "利物浦",
            "awayTeam": "富勒姆",
            "nowscoreId": 3003885,
        }],
    }, ensure_ascii=False), encoding="utf-8")
    updates = tmp_path / "updates"
    updates.mkdir()
    schedules = tmp_path / "schedules"

    outcome = sync_date(
        "2026-09-12",
        datetime(2026, 9, 12, 14, 31, tzinfo=SHANGHAI),
        schedules,
        updates,
        universe,
    )
    saved = json.loads(next(schedules.glob("*.json")).read_text(encoding="utf-8"))

    assert outcome == {"fixtures": 1, "created": 1, "updated": 0}
    assert saved["home"] == "利物浦"
    assert saved["away"] == "富勒姆"
    assert saved["nowscore_id"] == 3003885
    assert saved["match_num"] == "周六016"
    assert saved["kickoff_local"] == "2026-09-12T22:00:00+08:00"

def test_overdue_recovery_backfills_missing_schedule_and_rearms_result_not_final_once(tmp_path):
    now = datetime(2026, 9, 18, 20, tzinfo=SHANGHAI)
    universe = tmp_path / "universe"
    universe.mkdir()
    (universe / "2026-09-12.json").write_text(json.dumps({
        "business_date": "2026-09-12",
        "status": "READY",
        "fixtures": [{
            "matchId": "3003885",
            "matchNum": "周六016",
            "businessDate": "2026-09-12",
            "matchDate": "2026-09-12",
            "matchTime": "22:00",
            "homeTeam": "利物浦",
            "awayTeam": "富勒姆",
            "nowscoreId": 3003885,
        }],
    }, ensure_ascii=False), encoding="utf-8")
    predictions = tmp_path / "predictions"
    predictions.mkdir()
    (predictions / "FBOS-PRED-OLD.json").write_text(json.dumps({
        "prediction_id": "FBOS-PRED-OLD",
        "business_date": "2026-09-12",
        "match_key": "FBOS-202609122200-test",
    }), encoding="utf-8")
    trust = tmp_path / "trust.json"
    trust.write_text(json.dumps({
        "history": [{
            "status": "PENDING",
            "prediction_id": "FBOS-PRED-OLD",
            "match_key": "FBOS-202609122200-test",
            "kickoff_at": "2026-09-12T14:00:00Z",
        }]
    }), encoding="utf-8")
    schedules = tmp_path / "schedules"
    updates = tmp_path / "updates"
    updates.mkdir()

    first = recover_overdue_schedules(
        now, schedules, updates, universe, trust, predictions
    )
    path = next(schedules.glob("*.json"))
    saved = json.loads(path.read_text(encoding="utf-8"))
    saved.update({
        "status": "expired_unresolved",
        "verification_issue": "result_not_final",
        "last_error": "espn_fetch_failed:HTTPError",
        "terminal_reason": "result_not_final_after_bounded_retry",
    })
    path.write_text(json.dumps(saved), encoding="utf-8")

    second = recover_overdue_schedules(
        now, schedules, updates, universe, trust, predictions
    )
    rearmed = json.loads(path.read_text(encoding="utf-8"))
    third = recover_overdue_schedules(
        now, schedules, updates, universe, trust, predictions
    )

    assert first["created"] == 1
    assert first["recovery_dates"] == ["2026-09-12"]
    assert second["rearmed_terminal_count"] == 1
    assert rearmed["status"] == "scheduled"
    assert rearmed["overdue_recovery_count"] == 1
    assert "terminal_reason" not in rearmed
    assert third["rearmed_terminal_count"] == 0
