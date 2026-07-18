from datetime import datetime
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import prematch_market_monitor as monitor
from prematch_market_monitor import checkpoint_meta, due_matches


def analyzed_match():
    return {"id": "1", "report_state": "已分析", "kickoff": "2026-07-16 03:00"}


def test_due_matches_only_returns_analyzed_at_real_checkpoint():
    workspace = {"matches": [
        analyzed_match(),
        {"id": "2", "report_state": "未分析", "kickoff": "2026-07-16 03:00"},
        {"id": "3", "report_state": "已分析", "kickoff": "2026-07-17 03:00"},
    ]}
    due = due_matches(workspace, datetime.fromisoformat("2026-07-15 23:00"))
    assert [row["id"] for row in due] == ["1"]
    assert due[0]["_monitor_stage"] == "T-4H"


def test_each_checkpoint_runs_once_and_stale_checkpoints_are_not_backfilled():
    workspace = {"matches": [analyzed_match()]}
    assert due_matches(workspace, datetime.fromisoformat("2026-07-16 01:30"), state={})[0]["_monitor_stage"] == "T-90M"
    done = {"1": {"T-90M": {"captured_at": "2026-07-16T01:30:00"}}}
    assert due_matches(workspace, datetime.fromisoformat("2026-07-16 01:30"), state=done) == []
    assert due_matches(workspace, datetime.fromisoformat("2026-07-16 02:30"), state=done)[0]["_monitor_stage"] == "T-30M"
    assert due_matches(workspace, datetime.fromisoformat("2026-07-16 02:50"), state=done)[0]["_monitor_stage"] == "T-10M"
    done["1"]["T-10M"] = {"captured_at": "2026-07-16T02:50:00"}
    assert due_matches(workspace, datetime.fromisoformat("2026-07-16 02:52"), state=done) == []


def test_all_eight_checkpoints_are_addressable():
    workspace = {"matches": [analyzed_match()]}
    checks = {
        "2026-07-15 19:00": "T-8H", "2026-07-15 21:00": "T-6H",
        "2026-07-15 23:00": "T-4H", "2026-07-16 01:00": "T-2H",
        "2026-07-16 01:30": "T-90M", "2026-07-16 02:00": "T-60M",
        "2026-07-16 02:30": "T-30M", "2026-07-16 02:50": "T-10M",
    }
    for current, expected in checks.items():
        assert due_matches(workspace, datetime.fromisoformat(current), state={})[0]["_monitor_stage"] == expected


def test_checkpoint_meta_records_actual_lateness_instead_of_claiming_exact():
    meta = checkpoint_meta(analyzed_match(), datetime.fromisoformat("2026-07-16 01:33"), "T-90M")
    assert meta["target_minutes_before"] == 90
    assert meta["actual_minutes_before"] == 87
    assert meta["lateness_minutes"] == 3
    assert meta["exact"] is False


def test_failed_nearest_checkpoint_remains_retryable_and_is_labeled_recovery():
    workspace = {"matches": [analyzed_match()]}
    failed = {"1": {"T-90M": {"status": "failed", "error": "temporary"}}}
    due = due_matches(workspace, datetime.fromisoformat("2026-07-16 01:35"), state=failed)
    assert due[0]["_monitor_stage"] == "T-90M"
    meta = checkpoint_meta(analyzed_match(), datetime.fromisoformat("2026-07-16 01:58"), "T-90M")
    assert meta["capture_quality"] == "late_recovery"


def test_github_utc_clock_is_compared_against_beijing_kickoff():
    utc_now = datetime.fromisoformat("2026-07-15T17:00:00+00:00")
    due = due_matches({"matches": [analyzed_match()]}, utc_now, state={})
    assert due[0]["_monitor_stage"] == "T-2H"


def test_partial_refresh_errors_do_not_block_successful_publication(tmp_path, monkeypatch):
    workspace = tmp_path / "latest.json"
    workspace.write_text('{"target_date":"2026-07-16","matches":[]}', encoding="utf-8")
    state = tmp_path / "state.json"
    monkeypatch.setattr(monitor, "WORKSPACE", workspace)
    monkeypatch.setattr(monitor, "STATE_PATH", state)
    monkeypatch.setattr(monitor, "ROOT", tmp_path)
    monkeypatch.setattr(monitor, "due_matches", lambda *_args: [
        {"id": "ok", "home": "A", "away": "B", "_monitor_stage": "T-2H"},
        {"id": "bad", "home": "C", "away": "D", "_monitor_stage": "T-2H"},
    ])
    def refresh(match, stage, _now):
        if match["id"] == "bad":
            raise RuntimeError("broken feed")
        return {"status": "refreshed", "stage": stage, "checkpoint": {"captured_at": "now"}}
    monkeypatch.setattr(monitor, "refresh_match", refresh)
    monkeypatch.setattr(monitor, "run_json", lambda *_args: {})
    monkeypatch.setattr(monitor.subprocess, "run", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(sys, "argv", ["prematch_market_monitor.py", "--now", "2026-07-16T00:00:00+08:00"])
    assert monitor.main() == 0
    assert state.exists()
    assert list((tmp_path / "data" / "market_history" / "errors").glob("*_monitor_errors.json"))


def test_refresh_fundamentals_preserves_form_and_updates_time_sensitive_facts(tmp_path, monkeypatch):
    analysis = tmp_path / "analysis.json"
    analysis.write_text('{"fundamentals":{"items":[{"label":"近期状态","value":"保留"}]}}', encoding="utf-8")
    monkeypatch.setattr(monitor, "collect_prematch_fundamentals", lambda match, deep: {
        "status": "已重查",
        "items": [{"label": "首发名单", "value": "尚未公布"}],
        "sources": [{"label": "官方比赛页", "url": "https://example.com"}],
    })
    assert monitor.refresh_fundamentals(analysis, {"home": "主队", "away": "客队"}) == "已重查"
    payload = monitor.load_json(analysis)
    assert [item["label"] for item in payload["fundamentals"]["items"]] == ["近期状态", "首发名单"]
    assert payload["fundamentals"]["sources"][0]["url"] == "https://example.com"
