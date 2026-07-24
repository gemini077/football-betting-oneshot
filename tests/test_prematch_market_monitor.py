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
    assert [row["id"] for row in due] == ["1", "1", "1"]
    assert [row["_monitor_stage"] for row in due] == ["T-8H", "T-6H", "T-4H"]


def test_each_checkpoint_runs_once_and_all_stale_checkpoints_are_backfilled():
    workspace = {"matches": [analyzed_match()]}
    due = due_matches(workspace, datetime.fromisoformat("2026-07-16 01:30"), state={})
    assert [row["_monitor_stage"] for row in due] == ["T-8H", "T-6H", "T-4H", "T-2H", "T-90M"]
    done = {"1": {stage: {"status": "captured"} for stage in ("T-8H", "T-6H", "T-4H", "T-2H", "T-90M")}}
    assert due_matches(workspace, datetime.fromisoformat("2026-07-16 01:30"), state=done) == []
    assert [row["_monitor_stage"] for row in due_matches(workspace, datetime.fromisoformat("2026-07-16 02:30"), state=done)] == ["T-60M", "T-30M"]
    done["1"].update({stage: {"status": "captured"} for stage in ("T-60M", "T-30M")})
    assert due_matches(workspace, datetime.fromisoformat("2026-07-16 02:50"), state=done)[0]["_monitor_stage"] == "T-10M"
    done["1"]["T-10M"] = {"status": "captured", "captured_at": "2026-07-16T02:50:00"}
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
        assert due_matches(workspace, datetime.fromisoformat(current), state={})[-1]["_monitor_stage"] == expected


def test_checkpoint_meta_records_actual_lateness_instead_of_claiming_exact():
    meta = checkpoint_meta(analyzed_match(), datetime.fromisoformat("2026-07-16 01:33"), "T-90M")
    assert meta["target_minutes_before"] == 90
    assert meta["actual_minutes_before"] == 87
    assert meta["lateness_minutes"] == 3
    assert meta["exact"] is False


def test_failed_nearest_checkpoint_remains_retryable_and_is_labeled_recovery():
    workspace = {"matches": [analyzed_match()]}
    failed = {"1": {
        **{stage: {"status": "captured"} for stage in ("T-8H", "T-6H", "T-4H", "T-2H")},
        "T-90M": {"status": "failed", "error": "temporary"},
    }}
    due = due_matches(workspace, datetime.fromisoformat("2026-07-16 01:35"), state=failed)
    assert due[0]["_monitor_stage"] == "T-90M"
    meta = checkpoint_meta(analyzed_match(), datetime.fromisoformat("2026-07-16 01:58"), "T-90M")
    assert meta["capture_quality"] == "pending_recovery"


def test_github_utc_clock_is_compared_against_beijing_kickoff():
    utc_now = datetime.fromisoformat("2026-07-15T17:00:00+00:00")
    due = due_matches({"matches": [analyzed_match()]}, utc_now, state={})
    assert due[-1]["_monitor_stage"] == "T-2H"


def test_partial_refresh_errors_do_not_block_successful_publication(tmp_path, monkeypatch):
    workspace = tmp_path / "latest.json"
    workspace.write_text('{"target_date":"2026-07-16","matches":[]}', encoding="utf-8")
    state = tmp_path / "state.json"
    monkeypatch.setattr(monitor, "WORKSPACE", workspace)
    monkeypatch.setattr(monitor, "STATE_PATH", state)
    monkeypatch.setattr(monitor, "ROOT", tmp_path)
    monkeypatch.setattr(monitor, "load_registry", lambda: {"tasks": {
        "ok": {"checkpoints": {"T-2H": {"status": "pending"}}},
        "bad": {"checkpoints": {"T-2H": {"status": "pending"}}},
    }})
    monkeypatch.setattr(monitor, "due_events", lambda *_args: [
        {"id": "ok", "home": "A", "away": "B", "_monitor_stage": "T-2H", "_canonical_match_id": "ok"},
        {"id": "bad", "home": "C", "away": "D", "_monitor_stage": "T-2H", "_canonical_match_id": "bad"},
    ])
    monkeypatch.setattr(monitor, "update_checkpoint", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(monitor, "save_registry", lambda *_args, **_kwargs: None)
    def refresh(match, stage, _now):
        if match["id"] == "bad":
            raise RuntimeError("broken feed")
        return {"status": "report_updated", "stage": stage, "checkpoint": {"captured_at": "now"}}
    monkeypatch.setattr(monitor, "refresh_match", refresh)
    monkeypatch.setattr(monitor, "run_json", lambda *_args: {})
    monkeypatch.setattr(monitor.subprocess, "run", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(sys, "argv", [
        "prematch_market_monitor.py", "--now", "2026-07-16T00:00:00+08:00", "--max-events", "2",
    ])
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


def test_checkpoint_capture_uses_identity_directly_and_prefers_nowscore(tmp_path, monkeypatch):
    monkeypatch.setattr(monitor, "ROOT", tmp_path)
    monkeypatch.setattr(monitor, "fetch_nowscore_markets", lambda *args: {
        "status": "OK",
        "ouzhi": {"bookmakers": [{"cid": 1}]},
        "yazhi": {"companies": []},
        "daxiao": {"companies": []},
    })
    monkeypatch.setattr(
        monitor,
        "fetch_and_parse",
        lambda *args: (_ for _ in ()).throw(AssertionError("500 fallback should not run")),
    )
    manifest_path = monitor.capture_market_snapshot(
        {
            "id": "500-77",
            "home": "A",
            "away": "B",
            "kickoff": "2026-07-20 03:00",
            "business_date": "2026-07-19",
        },
        "T-2H",
        datetime.fromisoformat("2026-07-20T01:00:00+08:00"),
    )
    manifest = monitor.load_json(manifest_path)
    assert manifest["sources"]["nowscore"]["success"] is True
    assert "500_deep" not in manifest["sources"]


def test_checkpoint_capture_falls_back_to_500_when_nowscore_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(monitor, "ROOT", tmp_path)
    monkeypatch.setattr(
        monitor,
        "fetch_nowscore_markets",
        lambda *args: {"status": "FETCH_ERROR", "error": "temporary"},
    )
    monkeypatch.setattr(monitor, "fetch_and_parse", lambda *args: {
        "shuju_id": 77,
        "ouzhi": {"bookmakers": [{"cid": 1}]},
        "yazhi": {"companies": []},
        "daxiao": {"companies": []},
    })
    manifest_path = monitor.capture_market_snapshot(
        {
            "id": "500-77",
            "home": "A",
            "away": "B",
            "kickoff": "2026-07-20 03:00",
            "business_date": "2026-07-19",
        },
        "T-2H",
        datetime.fromisoformat("2026-07-20T01:00:00+08:00"),
    )
    manifest = monitor.load_json(manifest_path)
    assert manifest["sources"]["nowscore"]["success"] is False
    assert manifest["sources"]["500_deep"]["success"] is True
