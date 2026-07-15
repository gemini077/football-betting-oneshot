import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from postmatch_result import parse_header_score, verify_schedule
from sync_postmatch_workflow import active_due_times, render


SHANGHAI = timezone(timedelta(hours=8))


def write_schedule(path: Path, **overrides) -> Path:
    payload = {
        "match_key": "shuju:123",
        "home": "主队",
        "away": "客队",
        "kickoff_local": "2026-07-15T18:00:00+08:00",
        "shuju_id": 123,
        "review_due_at": "2026-07-15T20:15:00+08:00",
        "status": "scheduled",
        "verification_attempts": 0,
        "retry_policy": {"maximum_retries": 1, "retry_after_minutes": 45},
    }
    payload.update(overrides)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def test_parse_500_header_score():
    page = '<p class="odds_hd_bf"><strong>2:1</strong></p>'
    assert parse_header_score(page) == (2, 1)


def test_due_schedule_verifies_once(tmp_path):
    schedule = write_schedule(tmp_path / "schedule.json")
    result_root = tmp_path / "results"
    now = datetime(2026, 7, 15, 20, 20, tzinfo=SHANGHAI)
    with patch("postmatch_result.fetch_page", return_value='<p class="odds_hd_bf"><strong>2：0</strong></p>'):
        outcome = verify_schedule(schedule, now, result_root)
    saved = json.loads(schedule.read_text(encoding="utf-8"))
    assert outcome["status"] == "result_verified"
    assert saved["result_90m"] == "2-0"
    assert len(list(result_root.glob("*.json"))) == 1


def test_missing_result_gets_only_one_retry(tmp_path):
    schedule = write_schedule(tmp_path / "schedule.json")
    first = datetime(2026, 7, 15, 20, 20, tzinfo=SHANGHAI)
    with patch("postmatch_result.fetch_page", return_value="not final"):
        first_outcome = verify_schedule(schedule, first, tmp_path / "results")
        second_outcome = verify_schedule(schedule, first + timedelta(minutes=46), tmp_path / "results")
    saved = json.loads(schedule.read_text(encoding="utf-8"))
    assert first_outcome["status"] == "retry_scheduled"
    assert second_outcome["status"] == "blocked_result_not_final"
    assert saved["verification_attempts"] == 2


def test_generated_cron_contains_only_future_active_schedule(tmp_path):
    write_schedule(tmp_path / "active.json", review_due_at="2026-07-16T06:15:00+08:00")
    write_schedule(
        tmp_path / "finished.json",
        match_key="shuju:999",
        review_due_at="2026-07-16T07:00:00+08:00",
        status="result_verified",
    )
    now = datetime(2026, 7, 15, 12, 0, tzinfo=SHANGHAI)
    due_times = active_due_times(now, tmp_path)
    workflow = render(due_times)
    assert len(due_times) == 1
    assert 'cron: "15 22 15 7 *"' in workflow
    assert "football-betting-oneshot-write" in workflow
