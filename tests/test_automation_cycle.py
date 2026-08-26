import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from scripts import automation_cycle  # noqa: E402


def test_cycle_calls_base_runner_and_prospective_settlement_and_writes_health(tmp_path, monkeypatch):
    calls = []

    def fake_run(command, *, optional=False):
        calls.append(command)
        return {"returncode": 0, "status": "READY"}

    monkeypatch.setattr(automation_cycle, "run", fake_run)
    runtime_path = tmp_path / "product_runtime" / "latest_cycle.json"

    payload = automation_cycle.cycle("2026-08-12", runtime_path=runtime_path)

    assert any("base_prediction_runner.py" in part for command in calls for part in command)
    assert any("prospective_settlement.py" in part for command in calls for part in command)
    assert payload["overall_status"] == "HEALTHY"
    assert payload["steps"]["base_prediction"]["status"] == "SUCCESS"
    assert payload["steps"]["prospective"]["status"] == "SUCCESS"
    saved = json.loads(runtime_path.read_text(encoding="utf-8"))
    assert saved["business_date"] == "2026-08-12"
    assert saved["carryover_business_dates"] == []
    assert saved["finished_at"]


def test_optional_step_failure_makes_cycle_degraded_but_keeps_health_artifact(tmp_path, monkeypatch):
    def fake_run(command, *, optional=False):
        if any("daily_schedule_workspace.py" in part for part in command):
            return {"returncode": 1, "status": "FETCH_FAILED"}
        return {"returncode": 0, "status": "READY"}

    monkeypatch.setattr(automation_cycle, "run", fake_run)
    runtime_path = tmp_path / "product_runtime" / "latest_cycle.json"

    payload = automation_cycle.cycle("2026-08-12", runtime_path=runtime_path)

    assert payload["overall_status"] == "DEGRADED"
    assert payload["steps"]["universe"]["status"] == "DEGRADED"
    assert runtime_path.exists()


def _write_carryover_state(tmp_path, business_date="2026-08-12"):
    universe_dir = tmp_path / "prediction_universe"
    jobs_dir = tmp_path / "base_prediction_jobs"
    universe_dir.mkdir()
    jobs_dir.mkdir()
    (universe_dir / f"{business_date}.json").write_text(
        json.dumps({"status": "READY", "fixture_count": 1}), encoding="utf-8"
    )
    (jobs_dir / f"{business_date}.json").write_text(
        json.dumps({"status": "READY", "job_count": 1, "jobs": [{"status": "PENDING"}]}),
        encoding="utf-8",
    )
    return universe_dir, jobs_dir


def _command_date(command):
    command = list(command)
    if "--date" not in command:
        return None
    return command[command.index("--date") + 1]


def _has_script(command, script_name):
    return any(str(part).endswith(script_name) for part in command)


def test_production_cycle_processes_today_and_yesterday_without_refetching_yesterday(tmp_path, monkeypatch):
    universe_dir, jobs_dir = _write_carryover_state(tmp_path)
    monkeypatch.setattr(automation_cycle, "PREDICTION_UNIVERSE_DIR", universe_dir, raising=False)
    monkeypatch.setattr(automation_cycle, "BASE_JOBS_DIR", jobs_dir, raising=False)
    calls = []

    def fake_run(command, *, optional=False):
        calls.append(list(command))
        if _has_script(command, "prospective_settlement.py"):
            return {"returncode": 0, "status": "RESULT_PENDING", "pending_results": 1}
        return {"returncode": 0, "status": "SUCCESS"}

    monkeypatch.setattr(automation_cycle, "run", fake_run)
    runtime_path = tmp_path / "product_runtime" / "latest_cycle.json"

    payload = automation_cycle.production_cycle(
        now=datetime.fromisoformat("2026-08-13T00:30:00+08:00"),
        runtime_path=runtime_path,
    )

    assert automation_cycle.active_business_dates(
        datetime.fromisoformat("2026-08-13T00:30:00+08:00")
    ) == ("2026-08-13", ["2026-08-12"])
    assert payload["business_date"] == "2026-08-13"
    assert payload["carryover_business_dates"] == ["2026-08-12"]
    assert payload["steps"]["carryover_base_prediction"]["status"] == "SUCCESS"
    assert payload["steps"]["carryover_prospective"]["status"] == "SUCCESS"
    assert any(
        _has_script(command, "base_prediction_runner.py")
        and _command_date(command) == "2026-08-12"
        for command in calls
    )
    assert payload["steps"]["next_base_jobs"]["status"] == "SUCCESS"
    assert payload["steps"]["next_base_prediction"]["status"] == "SUCCESS"
    assert payload["steps"]["next_universe"]["status"] == "SUCCESS"
    next_universe_index = next(
        index for index, command in enumerate(calls)
        if _has_script(command, "daily_schedule_workspace.py")
        and _command_date(command) == "2026-08-14"
    )
    next_jobs_index = next(
        index for index, command in enumerate(calls)
        if _has_script(command, "base_prediction_jobs.py")
        and _command_date(command) == "2026-08-14"
    )
    next_prediction_index = next(
        index for index, command in enumerate(calls)
        if _has_script(command, "base_prediction_runner.py")
        and _command_date(command) == "2026-08-14"
    )
    assert next_universe_index < next_jobs_index < next_prediction_index
    assert any(
        _has_script(command, "base_prediction_jobs.py")
        and _command_date(command) == "2026-08-14"
        for command in calls
    )
    assert any(
        _has_script(command, "base_prediction_runner.py")
        and _command_date(command) == "2026-08-14"
        for command in calls
    )
    assert {
        _command_date(command)
        for command in calls
        if _has_script(command, "prospective_settlement.py")
    } == {"2026-08-12", "2026-08-13"}
    assert not any(
        _has_script(command, "daily_schedule_workspace.py")
        and _command_date(command) == "2026-08-12"
        for command in calls
    )
    dashboard_dates = {
        _command_date(command)
        for command in calls
        if _has_script(command, "prediction_dashboard.py")
    }
    assert dashboard_dates == {"2026-08-13"}
    assert sum(_has_script(command, "prediction_dashboard.py") for command in calls) == 1
    assert sum(_has_script(command, "build_public_site.py") for command in calls) == 1
    assert payload["overall_status"] == "HEALTHY"


def test_missing_carryover_state_is_skipped_without_degrading_cycle(tmp_path, monkeypatch):
    monkeypatch.setattr(automation_cycle, "PREDICTION_UNIVERSE_DIR", tmp_path / "universe", raising=False)
    monkeypatch.setattr(automation_cycle, "BASE_JOBS_DIR", tmp_path / "jobs", raising=False)
    monkeypatch.setattr(
        automation_cycle,
        "run",
        lambda command, *, optional=False: {"returncode": 0, "status": "SUCCESS"},
    )

    payload = automation_cycle.production_cycle(
        now=datetime.fromisoformat("2026-08-13T00:30:00+08:00"),
        runtime_path=tmp_path / "runtime.json",
    )

    assert payload["steps"]["carryover_base_prediction"]["status"] == "SKIPPED"
    assert payload["steps"]["carryover_prospective"]["status"] == "SKIPPED"
    assert payload["overall_status"] == "HEALTHY"


def test_explicit_date_mode_does_not_add_yesterday(tmp_path, monkeypatch, capsys):
    seen = []

    def fake_cycle(business_date, **kwargs):
        seen.append(business_date)
        return {"overall_status": "HEALTHY"}

    monkeypatch.setattr(automation_cycle, "cycle", fake_cycle)
    monkeypatch.setattr(sys, "argv", ["automation_cycle.py", "--date", "2026-08-12"])

    assert automation_cycle.main() == 0
    assert seen == ["2026-08-12"]
    capsys.readouterr()
