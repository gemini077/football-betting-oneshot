import json
from types import SimpleNamespace

from scripts import core_auto_reports


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
        {"business_date": "2026-10-15", "id": "m1", "home": "A", "away": "B"},
        {"business_date": "2026-10-15", "id": "m2", "home": "C", "away": "D"},
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
    rows = [{"business_date": "2026-10-15", "id": "m1", "home": "A", "away": "B"}]
    previous = {"2026-10-15:m1": {"status": "completed", "attempts": 1}}
    code, state, summary = _run(monkeypatch, tmp_path, chosen=rows, previous=previous)
    assert code == 0
    assert state["last_status"] == "NO_PENDING_CORE_JOB"
    assert summary["status"] == "NO_PENDING_CORE_JOB"
    assert summary["attempted"] == summary["completed"] == summary["failed"] == 0
