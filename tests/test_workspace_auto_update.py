import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

# Several legacy scripts intentionally support direct ``python scripts/...py``
# execution.  Mirror that script-local import path for focused package tests.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from scripts import automation_cycle, core_auto_reports, match_workspace, prediction_dashboard


def _has_script(command, script_name):
    return any(str(part).endswith(script_name) for part in command)


def _command_date(command):
    command = list(command)
    if "--date" not in command:
        return None
    return command[command.index("--date") + 1]


def test_production_cycle_refreshes_current_workspace_before_dashboard_and_site(tmp_path, monkeypatch):
    monkeypatch.setattr(automation_cycle, "PREDICTION_UNIVERSE_DIR", tmp_path / "universe", raising=False)
    monkeypatch.setattr(automation_cycle, "BASE_JOBS_DIR", tmp_path / "jobs", raising=False)
    calls = []

    def fake_run(command, *, optional=False):
        calls.append(list(command))
        if _has_script(command, "match_workspace.py"):
            return {
                "returncode": 0,
                "status": "SUCCESS",
                "target_date": "2026-08-15",
                "match_count": 16,
                "completed_count": 0,
                "published_as_latest": True,
            }
        return {"returncode": 0, "status": "SUCCESS"}

    monkeypatch.setattr(automation_cycle, "run", fake_run)
    runtime_path = tmp_path / "product_runtime" / "latest_cycle.json"

    payload = automation_cycle.production_cycle(
        now=datetime.fromisoformat("2026-08-15T00:30:00+08:00"),
        runtime_path=runtime_path,
    )

    workspace_calls = [command for command in calls if _has_script(command, "match_workspace.py")]
    assert len(workspace_calls) == 1
    assert _command_date(workspace_calls[0]) == "2026-08-15"
    assert "--latest-only" in workspace_calls[0]
    workspace_index = calls.index(workspace_calls[0])
    dashboard_index = next(index for index, command in enumerate(calls) if _has_script(command, "prediction_dashboard.py"))
    site_index = next(index for index, command in enumerate(calls) if _has_script(command, "build_public_site.py"))
    assert workspace_index < dashboard_index < site_index
    assert payload["steps"]["workspace"]["status"] == "SUCCESS"
    assert payload["steps"]["workspace"]["summary"]["target_date"] == "2026-08-15"
    assert payload["steps"]["workspace"]["summary"]["match_count"] == 16
    saved = json.loads(runtime_path.read_text(encoding="utf-8"))
    assert saved["steps"]["workspace"]["summary"]["target_date"] == "2026-08-15"


def test_workspace_failure_is_recorded_without_blocking_dashboard_or_site(tmp_path, monkeypatch):
    monkeypatch.setattr(automation_cycle, "PREDICTION_UNIVERSE_DIR", tmp_path / "universe", raising=False)
    monkeypatch.setattr(automation_cycle, "BASE_JOBS_DIR", tmp_path / "jobs", raising=False)
    calls = []

    def fake_run(command, *, optional=False):
        calls.append(list(command))
        if _has_script(command, "match_workspace.py"):
            return {"returncode": 1, "status": "FAILED", "error": "workspace build failed"}
        return {"returncode": 0, "status": "SUCCESS"}

    monkeypatch.setattr(automation_cycle, "run", fake_run)
    payload = automation_cycle.production_cycle(
        now=datetime.fromisoformat("2026-08-15T00:30:00+08:00"),
        runtime_path=tmp_path / "runtime.json",
    )

    assert payload["steps"]["workspace"]["status"] == "DEGRADED"
    assert payload["overall_status"] == "DEGRADED"
    assert any(_has_script(command, "prediction_dashboard.py") for command in calls)
    assert any(_has_script(command, "build_public_site.py") for command in calls)


def test_latest_only_workspace_writes_only_latest_projection(tmp_path, monkeypatch):
    fixed_now = datetime.fromisoformat("2026-08-15T00:30:00+08:00")
    source = match_workspace.ROOT / "data" / "prediction_universe" / "2026-08-15.json"
    monkeypatch.setattr(match_workspace, "workspace_now", lambda: fixed_now)
    monkeypatch.setattr(
        match_workspace,
        "latest_schedule",
        lambda business_date: (source, {"matches": [], "fetch_time": None}),
    )
    monkeypatch.setattr(match_workspace, "latest_reports", lambda: {})
    monkeypatch.setattr(match_workspace, "review_rows", lambda runtime: [])
    monkeypatch.setattr(match_workspace, "verified_result_map", lambda: {})
    monkeypatch.setattr(match_workspace, "result_schedule_map", lambda: {})
    monkeypatch.setattr(match_workspace, "all_reports", lambda: [])
    monkeypatch.setattr(match_workspace, "load_real_bets", lambda: [])

    def unexpected_price_write(*args, **kwargs):
        raise AssertionError("latest-only build must not write paper price overrides")

    monkeypatch.setattr(match_workspace, "sync_channel_price_overrides", unexpected_price_write)
    output = tmp_path / "match_workspace"
    paper_latest = match_workspace.DATA / "paper_ledger" / "latest.json"
    frozen = match_workspace.DATA / "paper_ledger" / "frozen.json"
    paper_before = paper_latest.read_bytes() if paper_latest.exists() else None
    frozen_before = frozen.read_bytes() if frozen.exists() else None

    index, latest = match_workspace.build(
        "2026-08-15",
        output,
        persist_runtime_data=False,
        latest_only=True,
    )

    assert index == output / "latest.html"
    assert latest == output / "latest.html"
    assert (output / "latest.json").is_file()
    assert sorted(path.name for path in output.iterdir()) == ["latest.html", "latest.json"]
    assert not list(output.glob("20*"))
    assert json.loads((output / "latest.json").read_text(encoding="utf-8"))["published_as_latest"] is True
    assert (paper_latest.read_bytes() if paper_latest.exists() else None) == paper_before
    assert (frozen.read_bytes() if frozen.exists() else None) == frozen_before


def test_latest_publish_decision_is_independent_of_host_timezone():
    instant_utc = datetime(2026, 8, 14, 16, 30, tzinfo=timezone.utc)
    instant_shanghai = datetime.fromisoformat("2026-08-15T00:30:00+08:00")

    assert match_workspace.should_publish_latest("2026-08-15", instant_utc)
    assert match_workspace.should_publish_latest("2026-08-15", instant_shanghai)
    assert not match_workspace.should_publish_latest("2026-08-14", instant_utc)
    assert not match_workspace.should_publish_latest("2026-08-14", instant_shanghai)


def _write_workspace(path: Path, target_date: str, generated_at: str, matches=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "target_date": target_date,
        "generated_at": generated_at,
        "matches": matches or [],
    }), encoding="utf-8")


def _run_core(monkeypatch, workspace_path, state_path):
    monkeypatch.setattr(core_auto_reports, "WORKSPACE", workspace_path)
    monkeypatch.setattr(core_auto_reports, "STATE_PATH", state_path)
    monkeypatch.setattr(sys, "argv", ["core_auto_reports.py", "--max-jobs", "2"])
    return core_auto_reports.main()


def test_core_current_workspace_with_no_match_is_explicit_no_eligible(tmp_path, monkeypatch, capsys):
    now = datetime.now(core_auto_reports.SHANGHAI)
    workspace = tmp_path / "latest.json"
    state = tmp_path / "state.json"
    _write_workspace(workspace, now.date().isoformat(), now.isoformat())

    monkeypatch.setattr(core_auto_reports, "select", lambda rows: [])
    code = _run_core(monkeypatch, workspace, state)

    output = json.loads(capsys.readouterr().out)
    assert code == 0
    assert output["status"] == "NO_ELIGIBLE_CORE_MATCH"
    assert output["selected"] == 0


def test_core_stale_workspace_fails_closed(tmp_path, monkeypatch, capsys):
    now = datetime.now(core_auto_reports.SHANGHAI)
    workspace = tmp_path / "latest.json"
    state = tmp_path / "state.json"
    _write_workspace(workspace, (now.date()).isoformat(), now.isoformat())
    payload = json.loads(workspace.read_text(encoding="utf-8"))
    payload["target_date"] = (now.date() - timedelta(days=1)).isoformat()
    workspace.write_text(json.dumps(payload), encoding="utf-8")

    monkeypatch.setattr(core_auto_reports, "select", lambda rows: pytest.fail("stale workspace must not select matches"))
    code = _run_core(monkeypatch, workspace, state)

    output = json.loads(capsys.readouterr().out)
    saved = json.loads(state.read_text(encoding="utf-8"))
    assert code == 1
    assert output["status"] == "STALE_WORKSPACE"
    assert saved["selected_today"] == []


def test_core_current_workspace_selector_still_runs(tmp_path, monkeypatch, capsys):
    now = datetime.now(core_auto_reports.SHANGHAI)
    workspace = tmp_path / "latest.json"
    state = tmp_path / "state.json"
    row = {"business_date": now.date().isoformat(), "id": "M-1", "home": "Home", "away": "Away"}
    _write_workspace(workspace, now.date().isoformat(), now.isoformat(), [row])
    monkeypatch.setattr(core_auto_reports, "select", lambda rows: rows)
    monkeypatch.setattr(
        core_auto_reports.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="", stderr=""),
    )

    code = _run_core(monkeypatch, workspace, state)

    output = json.loads(capsys.readouterr().out)
    assert code == 0
    assert output["status"] == "SUCCESS"
    assert output["selected"] == 1


def test_dashboard_and_legacy_workspace_contain_safe_static_refresh_logic():
    dashboard = prediction_dashboard.render_dashboard({
        "business_date": "2026-08-15",
        "generated_at": "2026-08-15T00:30:00+08:00",
        "summary": {"fixture_count": 0, "card_count": 0},
        "health": {"overall_status": "HEALTHY"},
        "fixtures": [],
    })
    workspace = match_workspace.render("{}")

    for page in (dashboard, workspace):
        assert "./latest.json" in page
        assert "cache: \"no-store\"" in page
        assert "visibilityState" in page
        assert "visibilitychange" in page
        assert "addEventListener(\"focus\"" in page
        assert "60000" in page
        assert "currentVersion" in page
        assert "window.location.replace" in page
