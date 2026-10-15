import json
from datetime import datetime
from types import SimpleNamespace

from scripts import core_auto_reports


def _workspace_status(target, generated, now):
    return core_auto_reports.validate_workspace(
        {"target_date": target, "generated_at": generated}, now=datetime.fromisoformat(now)
    )


def _future_kickoff():
    from datetime import timedelta

    return (datetime.now(core_auto_reports.SHANGHAI) + timedelta(hours=2)).isoformat()


def test_valid_next_jc_date_after_11am():
    result = _workspace_status("2026-10-16", "2026-10-15T18:10:19+08:00", "2026-10-15T18:12:00+08:00")
    assert result["status"] == "CURRENT"


def test_next_date_remains_valid_before_11am_rollover():
    result = _workspace_status("2026-10-16", "2026-10-16T07:30:00+08:00", "2026-10-16T08:00:00+08:00")
    assert result["status"] == "CURRENT"
    assert result["current_business_date"] == "2026-10-15"


def test_target_two_days_after_jc_date_is_stale():
    result = _workspace_status("2026-10-17", "2026-10-15T18:10:19+08:00", "2026-10-15T18:12:00+08:00")
    assert result["status"] == "STALE_WORKSPACE"
    assert result["reason"] == "WORKSPACE_BUSINESS_DATE_STALE"


def test_source_older_than_twelve_hours_is_stale():
    result = _workspace_status("2026-10-16", "2026-10-15T05:00:00+08:00", "2026-10-15T18:12:00+08:00")
    assert result["status"] == "STALE_WORKSPACE"
    assert result["reason"] == "WORKSPACE_SOURCE_TIMESTAMP_STALE"


def test_source_more_than_two_minutes_in_future_is_stale():
    result = _workspace_status("2026-10-16", "2026-10-15T18:15:00+08:00", "2026-10-15T18:12:00+08:00")
    assert result["status"] == "STALE_WORKSPACE"
    assert result["reason"] == "WORKSPACE_SOURCE_TIMESTAMP_STALE"


def test_recent_current_jc_date_workspace_remains_valid():
    result = _workspace_status("2026-10-15", "2026-10-15T18:00:00+08:00", "2026-10-15T18:12:00+08:00")
    assert result["status"] == "CURRENT"


def test_malformed_source_timestamp_is_invalid():
    result = core_auto_reports.validate_workspace(
        {"target_date": "2026-10-16", "generated_at": "not-a-timestamp"},
        now=datetime.fromisoformat("2026-10-15T18:12:00+08:00"),
    )
    assert result["status"] == "INVALID_WORKSPACE"


def test_kickoff_filter_keeps_future_fixture_in_original_order():
    now = datetime.fromisoformat("2026-10-15T18:00:00+08:00")
    rows = [
        {"id": "future", "kickoff": "2026-10-15T18:30:00+08:00"},
        {"id": "past", "kickoff": "2026-10-15T17:59:00+08:00"},
    ]
    assert core_auto_reports.filter_pre_kickoff(rows, now=now) == [rows[0]]


def test_kickoff_filter_rejects_started_and_within_fifteen_minutes():
    now = datetime.fromisoformat("2026-10-15T18:00:00+08:00")
    rows = [
        {"kickoff": "2026-10-15T17:59:59+08:00"},
        {"kickoff": "2026-10-15T18:14:59+08:00"},
    ]
    assert core_auto_reports.filter_pre_kickoff(rows, now=now) == []


def test_kickoff_filter_rejects_missing_and_malformed_times():
    rows = [{"id": "missing"}, {"kickoff": "not-a-kickoff"}, {"kickoff": None}]
    assert core_auto_reports.filter_pre_kickoff(rows, now=datetime.fromisoformat("2026-10-15T18:00:00+08:00")) == []


def test_kickoff_filter_normalizes_offset_across_shanghai_business_rollover():
    now = datetime.fromisoformat("2026-10-16T08:00:00+08:00")
    rows = [
        {"id": "eligible", "kickoff": "2026-10-16T09:15:00+09:00"},
        {"id": "too-close", "kickoff": "2026-10-16T09:14:00+09:00"},
    ]
    assert core_auto_reports.filter_pre_kickoff(rows, now=now) == [rows[0]]


def _run(monkeypatch, tmp_path, *, chosen, previous=None, result=None):
    state_path = tmp_path / "state.json"
    state_path.write_text(json.dumps({"schema_version": "1.0", "jobs": previous or {}}), encoding="utf-8")
    monkeypatch.setattr(core_auto_reports, "ROOT", tmp_path)
    monkeypatch.setattr(core_auto_reports, "STATE_PATH", state_path)
    monkeypatch.setattr(core_auto_reports, "WORKSPACE", tmp_path / "workspace.json")
    monkeypatch.setattr(core_auto_reports, "load", lambda path, default: {"matches": [{}]} if path == core_auto_reports.WORKSPACE else json.loads(state_path.read_text(encoding="utf-8")))
    monkeypatch.setattr(core_auto_reports, "validate_workspace", lambda workspace: {"status": "CURRENT"})
    monkeypatch.setattr(core_auto_reports, "select", lambda matches: chosen)
    if result is not None:
        monkeypatch.setattr(core_auto_reports.subprocess, "run", lambda *args, **kwargs: result)
    monkeypatch.setattr("sys.argv", ["core_auto_reports.py"])
    output = []
    monkeypatch.setattr("builtins.print", lambda value: output.append(json.loads(value)))
    code = core_auto_reports.main()
    return code, json.loads(state_path.read_text(encoding="utf-8")), output[0]


def test_partial_failure_is_persisted_and_reported_without_nonzero_exit(monkeypatch, tmp_path):
    rows = [
        {"business_date": "2026-10-15", "id": "m1", "home": "A", "away": "B", "kickoff": _future_kickoff()},
        {"business_date": "2026-10-15", "id": "m2", "home": "C", "away": "D", "kickoff": _future_kickoff()},
    ]
    outcomes = iter([SimpleNamespace(returncode=0, stdout="", stderr=""), SimpleNamespace(returncode=1, stdout="", stderr="failed")])
    monkeypatch.setattr(core_auto_reports.subprocess, "run", lambda *args, **kwargs: next(outcomes))
    code, state, summary = _run(monkeypatch, tmp_path, chosen=rows, result=None)
    assert code == 0
    assert state["last_status"] == "PARTIAL_FAILURE"
    assert summary["status"] == "PARTIAL_FAILURE"
    assert summary["completed"] == 1
    assert summary["failed"] == 1
    assert summary["attempted"] == 2


def test_selected_but_no_pending_jobs(monkeypatch, tmp_path):
    rows = [{"business_date": "2026-10-15", "id": "m1", "home": "A", "away": "B", "kickoff": _future_kickoff()}]
    previous = {"2026-10-15:m1": {"status": "completed", "attempts": 1}}
    code, state, summary = _run(monkeypatch, tmp_path, chosen=rows, previous=previous)
    assert code == 0
    assert state["last_status"] == "NO_PENDING_CORE_JOB"
    assert summary["status"] == "NO_PENDING_CORE_JOB"
    assert summary["attempted"] == summary["completed"] == summary["failed"] == 0
