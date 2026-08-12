import json
import sys
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
