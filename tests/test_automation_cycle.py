import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from scripts import automation_cycle  # noqa: E402


def test_cycle_calls_base_runner_and_prospective_settlement_and_writes_health(tmp_path, monkeypatch):
    calls = []

    def fake_run(command, *, optional=False, timeout=None):
        calls.append(command)
        if _has_script(command, "base_prediction_runner.py"):
            return {
                "returncode": 0,
                "status": "READY",
                "input_provenance_failure_stages": {"SOURCE_FETCH_FAILED": 1},
            }
        if _has_script(command, "market_side_shadow_refresh.py"):
            return {
                "returncode": 0,
                "status": "SUCCESS",
                "market_side_shadow_status": "REFRESHED",
                "paired_count": 1,
                "challenger_abstain_count": 0,
                "promotion_eligible_pairs": 1,
                "excluded_non_promotion_pair_count": 0,
                "verified_paired_count": 1,
                "checkpoint_status": "NOT_REACHED",
                "early_stop_status": "NOT_TRIGGERED",
                "auto_promote": False,
            }
        return {"returncode": 0, "status": "READY"}

    monkeypatch.setattr(automation_cycle, "run", fake_run)
    runtime_path = tmp_path / "product_runtime" / "latest_cycle.json"

    payload = automation_cycle.cycle("2026-08-12", runtime_path=runtime_path)

    assert any("base_prediction_runner.py" in part for command in calls for part in command)
    assert any("prospective_settlement.py" in part for command in calls for part in command)
    shadow_index = next(
        index for index, command in enumerate(calls)
        if _has_script(command, "market_side_shadow_refresh.py")
    )
    prospective_index = next(
        index for index, command in enumerate(calls)
        if _has_script(command, "prospective_settlement.py")
    )
    assert prospective_index < shadow_index
    assert payload["overall_status"] == "HEALTHY"
    assert payload["steps"]["base_prediction"]["status"] == "SUCCESS"
    assert payload["steps"]["base_prediction"]["summary"]["input_provenance_failure_stages"] == {"SOURCE_FETCH_FAILED": 1}
    assert payload["steps"]["prospective"]["status"] == "SUCCESS"
    assert payload["steps"]["market_side_shadow_evaluation"]["status"] == "SUCCESS"
    assert payload["steps"]["market_side_shadow_evaluation"]["summary"]["verified_paired_count"] == 1
    assert payload["steps"]["market_side_shadow_evaluation"]["summary"]["promotion_eligible_pairs"] == 1
    assert payload["steps"]["market_side_shadow_evaluation"]["summary"]["excluded_non_promotion_pair_count"] == 0
    assert payload["steps"]["market_side_shadow_evaluation"]["summary"]["checkpoint_status"] == "NOT_REACHED"
    saved = json.loads(runtime_path.read_text(encoding="utf-8"))
    assert saved["business_date"] == "2026-08-12"
    assert saved["carryover_business_dates"] == []
    assert saved["finished_at"]


def test_optional_step_failure_makes_cycle_degraded_but_keeps_health_artifact(tmp_path, monkeypatch):
    def fake_run(command, *, optional=False, timeout=None):
        if any("daily_schedule_workspace.py" in part for part in command):
            return {"returncode": 1, "status": "FETCH_FAILED"}
        return {"returncode": 0, "status": "READY"}

    monkeypatch.setattr(automation_cycle, "run", fake_run)
    runtime_path = tmp_path / "product_runtime" / "latest_cycle.json"

    payload = automation_cycle.cycle("2026-08-12", runtime_path=runtime_path)

    assert payload["overall_status"] == "DEGRADED"
    assert payload["steps"]["universe"]["status"] == "DEGRADED"
    assert runtime_path.exists()


def test_market_side_shadow_evaluation_failure_is_explicitly_degraded(tmp_path, monkeypatch):
    def fake_run(command, *, optional=False, timeout=None):
        if _has_script(command, "market_side_shadow_refresh.py"):
            return {"returncode": 1, "error": "RESULT_SOURCE_UNREADABLE"}
        return {"returncode": 0, "status": "READY"}

    monkeypatch.setattr(automation_cycle, "run", fake_run)
    payload = automation_cycle.cycle("2026-08-12", runtime_path=tmp_path / "runtime.json")

    step = payload["steps"]["market_side_shadow_evaluation"]
    assert payload["overall_status"] == "DEGRADED"
    assert step["status"] == "DEGRADED"
    assert step["summary"]["error"] == "RESULT_SOURCE_UNREADABLE"


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

    def fake_run(command, *, optional=False, timeout=None):
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


def test_production_cycle_skips_future_jobs_when_next_universe_is_not_yet_published(
    tmp_path, monkeypatch
):
    universe_dir, jobs_dir = _write_carryover_state(tmp_path)
    monkeypatch.setattr(automation_cycle, "PREDICTION_UNIVERSE_DIR", universe_dir, raising=False)
    monkeypatch.setattr(automation_cycle, "BASE_JOBS_DIR", jobs_dir, raising=False)
    calls = []

    def fake_run(command, *, optional=False, timeout=None):
        calls.append(list(command))
        if _has_script(command, "daily_schedule_workspace.py") and _command_date(command) == "2026-08-14":
            return {
                "returncode": 0,
                "status": "NOT_YET_PUBLISHED",
                "refresh_status": "not_yet_published",
                "business_dates": ["2026-08-14", "2026-08-15"],
                "source_states": [
                    {"business_date": "2026-08-14", "status": "NOT_YET_PUBLISHED"},
                    {"business_date": "2026-08-15", "status": "NOT_YET_PUBLISHED"},
                ],
            }
        return {"returncode": 0, "status": "SUCCESS"}

    monkeypatch.setattr(automation_cycle, "run", fake_run)
    payload = automation_cycle.production_cycle(
        now=datetime.fromisoformat("2026-08-13T00:30:00+08:00"),
        runtime_path=tmp_path / "runtime.json",
    )

    assert payload["steps"]["next_universe"]["status"] == "SKIPPED"
    assert payload["steps"]["next_universe"]["summary"]["status"] == "NOT_YET_PUBLISHED"
    assert payload["steps"]["next_universe"]["summary"]["refresh_status"] == "not_yet_published"
    assert payload["steps"]["next_universe"]["summary"]["business_dates"] == [
        "2026-08-14", "2026-08-15"
    ]
    assert payload["steps"]["next_universe"]["summary"]["source_states"][0]["status"] == "NOT_YET_PUBLISHED"
    assert payload["steps"]["next_universe"]["summary"]["reason"] == "NOT_YET_PUBLISHED"
    assert payload["steps"]["next_base_jobs"]["status"] == "SKIPPED"
    assert payload["steps"]["next_base_jobs"]["summary"]["reason"] == "NEXT_UNIVERSE_NOT_YET_PUBLISHED"
    assert payload["steps"]["next_base_prediction"]["status"] == "SKIPPED"
    assert payload["steps"]["next_base_prediction"]["summary"]["reason"] == "NEXT_UNIVERSE_NOT_YET_PUBLISHED"
    assert payload["overall_status"] == "HEALTHY"
    assert not any(
        _has_script(command, script)
        and _command_date(command) == "2026-08-14"
        for command in calls
        for script in ("base_prediction_jobs.py", "base_prediction_runner.py")
    )


def test_production_cycle_keeps_real_next_universe_fetch_failure_degraded(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(automation_cycle, "PREDICTION_UNIVERSE_DIR", tmp_path / "universe", raising=False)
    monkeypatch.setattr(automation_cycle, "BASE_JOBS_DIR", tmp_path / "jobs", raising=False)

    def fake_run(command, *, optional=False, timeout=None):
        if _has_script(command, "daily_schedule_workspace.py") and _command_date(command) == "2026-08-14":
            return {"returncode": 1, "status": "FETCH_FAILED"}
        return {"returncode": 0, "status": "SUCCESS"}

    monkeypatch.setattr(automation_cycle, "run", fake_run)
    payload = automation_cycle.production_cycle(
        now=datetime.fromisoformat("2026-08-13T00:30:00+08:00"),
        runtime_path=tmp_path / "runtime.json",
    )

    assert payload["steps"]["next_universe"]["status"] == "DEGRADED"
    assert payload["overall_status"] == "DEGRADED"


def test_current_universe_not_yet_published_remains_degraded(tmp_path, monkeypatch):
    def fake_run(command, *, optional=False, timeout=None):
        if _has_script(command, "daily_schedule_workspace.py"):
            return {
                "returncode": 0,
                "status": "NOT_YET_PUBLISHED",
                "refresh_status": "not_yet_published",
            }
        return {"returncode": 0, "status": "SUCCESS"}

    monkeypatch.setattr(automation_cycle, "run", fake_run)
    payload = automation_cycle.cycle(
        "2026-08-13", runtime_path=tmp_path / "runtime.json"
    )

    assert payload["steps"]["universe"]["status"] == "DEGRADED"
    assert payload["steps"]["universe"]["summary"]["status"] == "NOT_YET_PUBLISHED"
    assert payload["overall_status"] == "DEGRADED"


def test_missing_carryover_state_is_skipped_without_degrading_cycle(tmp_path, monkeypatch):
    monkeypatch.setattr(automation_cycle, "PREDICTION_UNIVERSE_DIR", tmp_path / "universe", raising=False)
    monkeypatch.setattr(automation_cycle, "BASE_JOBS_DIR", tmp_path / "jobs", raising=False)
    monkeypatch.setattr(
        automation_cycle,
        "run",
        lambda command, *, optional=False, timeout=None: {"returncode": 0, "status": "SUCCESS"},
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


def test_run_keeps_360_second_default_and_forwards_explicit_timeout(monkeypatch):
    calls = []

    class Completed:
        returncode = 0
        stdout = '{"status": "SUCCESS"}'
        stderr = ""

    def fake_subprocess_run(command, **kwargs):
        calls.append((list(command), kwargs))
        return Completed()

    monkeypatch.setattr(automation_cycle.subprocess, "run", fake_subprocess_run)

    automation_cycle.run(["python", "step.py"])
    automation_cycle.run(["python", "base_prediction_runner.py"], timeout=600)

    assert calls[0][1]["timeout"] == 360
    assert calls[1][1]["timeout"] == 600


def test_step_and_group_only_forward_timeout_when_explicitly_requested():
    calls = []

    def executor(command, **kwargs):
        calls.append((list(command), kwargs))
        return {"returncode": 0, "status": "SUCCESS"}

    automation_cycle._step("default", ["default"], optional=True, executor=executor)
    automation_cycle._step(
        "base", ["base"], optional=True, executor=executor, timeout=600
    )
    automation_cycle._group(
        "group", [["one"], ["two"]], optional=True, executor=executor, timeout=600
    )

    assert calls[0][1] == {"optional": True}
    assert calls[1][1] == {"optional": True, "timeout": 600}
    assert calls[2][1] == {"optional": True, "timeout": 600}
    assert calls[3][1] == {"optional": True, "timeout": 600}


def test_production_cycle_uses_600_seconds_only_for_carryover_current_and_next_base(
    tmp_path, monkeypatch
):
    universe_dir, jobs_dir = _write_carryover_state(tmp_path)
    monkeypatch.setattr(automation_cycle, "PREDICTION_UNIVERSE_DIR", universe_dir, raising=False)
    monkeypatch.setattr(automation_cycle, "BASE_JOBS_DIR", jobs_dir, raising=False)
    calls = []

    def fake_run(
        command,
        *,
        optional=False,
        timeout=automation_cycle.DEFAULT_SUBPROCESS_TIMEOUT,
    ):
        calls.append((list(command), timeout))
        return {"returncode": 0, "status": "SUCCESS"}

    monkeypatch.setattr(automation_cycle, "run", fake_run)

    automation_cycle.production_cycle(
        now=datetime.fromisoformat("2026-08-13T00:30:00+08:00"),
        runtime_path=tmp_path / "runtime.json",
    )

    base_timeouts = [
        timeout
        for command, timeout in calls
        if _has_script(command, "base_prediction_runner.py")
    ]
    non_base_timeouts = [
        timeout
        for command, timeout in calls
        if not _has_script(command, "base_prediction_runner.py")
    ]
    assert base_timeouts == [600, 600, 600]
    assert set(non_base_timeouts) == {360}


def test_base_timeout_preserves_existing_fail_closed_degraded_step_semantics():
    seen = []

    def timeout_executor(command, *, optional=False, timeout=360):
        seen.append(timeout)
        raise automation_cycle.subprocess.TimeoutExpired(command, timeout)

    result = automation_cycle._step(
        "base_prediction",
        ["base_prediction_runner.py"],
        optional=True,
        executor=timeout_executor,
        timeout=600,
    )

    assert seen == [600]
    assert result["status"] == "DEGRADED"
    assert result["returncode"] == 1
    assert result["summary"]["error"].startswith("TimeoutExpired:")
