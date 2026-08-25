import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import automation_cycle  # noqa: E402
from refresh_durability_gate import classify  # noqa: E402


DATE = "2026-08-25"


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def cycle_payload(*, site_status: str, generation_status: dict[str, str] | None = None) -> dict:
    statuses = {
        "universe": "SUCCESS",
        "base_jobs": "SUCCESS",
        "base_prediction": "SUCCESS",
        "dashboard": "SUCCESS",
    }
    statuses.update(generation_status or {})
    steps = {name: {"status": status} for name, status in statuses.items()}
    steps["site"] = {"status": site_status}
    return {"business_date": DATE, "steps": steps}


def write_generated_artifacts(tmp_path: Path) -> Path:
    data_root = tmp_path / "data"
    write_json(data_root / "prediction_universe" / f"{DATE}.json", {"business_date": DATE, "status": "READY"})
    write_json(data_root / "base_prediction_jobs" / f"{DATE}.json", {"business_date": DATE, "status": "READY"})
    write_json(data_root / "prediction_dashboard" / "latest.json", {"business_date": DATE})
    dashboard_html = data_root / "prediction_dashboard" / "latest.html"
    dashboard_html.parent.mkdir(parents=True, exist_ok=True)
    dashboard_html.write_text("dashboard", encoding="utf-8")
    return data_root


def test_gate_accepts_site_failure_after_complete_generation(tmp_path):
    data_root = write_generated_artifacts(tmp_path)

    result = classify(cycle_payload(site_status="FAILED"), data_root=data_root, cycle_outcome="failure")

    assert result == {
        "ready": True,
        "reason": "SITE_FAILURE_AFTER_COMPLETE_GENERATION",
        "business_date": DATE,
    }


def test_gate_rejects_upstream_failure_even_when_site_fails(tmp_path):
    data_root = write_generated_artifacts(tmp_path)

    result = classify(
        cycle_payload(site_status="FAILED", generation_status={"base_prediction": "DEGRADED"}),
        data_root=data_root,
        cycle_outcome="failure",
    )

    assert result == {"ready": False, "reason": "UPSTREAM_GENERATION_NOT_COMPLETE"}


def test_gate_rejects_next_prematch_refresh_failure(tmp_path):
    data_root = write_generated_artifacts(tmp_path)

    result = classify(
        cycle_payload(
            site_status="SUCCESS",
            generation_status={"next_universe": "DEGRADED", "next_base_jobs": "SUCCESS", "next_base_prediction": "SUCCESS"},
        ),
        data_root=data_root,
        cycle_outcome="success",
    )

    assert result == {"ready": False, "reason": "NEXT_PREMATCH_GENERATION_NOT_COMPLETE"}


def test_gate_accepts_next_prematch_generation_when_universe_succeeds(tmp_path):
    data_root = write_generated_artifacts(tmp_path)

    result = classify(
        cycle_payload(
            site_status="SUCCESS",
            generation_status={
                "next_universe": "SUCCESS",
                "next_base_jobs": "SUCCESS",
                "next_base_prediction": "SUCCESS",
            },
        ),
        data_root=data_root,
        cycle_outcome="success",
    )

    assert result == {"ready": True, "reason": "COMPLETE_GENERATION", "business_date": DATE}

def test_gate_rejects_missing_or_stale_generated_artifact(tmp_path):
    data_root = write_generated_artifacts(tmp_path)
    write_json(data_root / "prediction_dashboard" / "latest.json", {"business_date": "2026-08-24"})

    result = classify(cycle_payload(site_status="FAILED"), data_root=data_root, cycle_outcome="failure")

    assert result == {"ready": False, "reason": "GENERATED_ARTIFACT_MISSING_OR_STALE"}


def test_gate_accepts_normal_complete_cycle(tmp_path):
    data_root = write_generated_artifacts(tmp_path)

    result = classify(cycle_payload(site_status="SUCCESS"), data_root=data_root, cycle_outcome="success")

    assert result == {"ready": True, "reason": "COMPLETE_GENERATION", "business_date": DATE}


def test_gate_reads_automation_cycle_runtime_contract(tmp_path):
    data_root = write_generated_artifacts(tmp_path)
    runtime_path = tmp_path / "product_runtime" / "latest_cycle.json"
    steps = {
        "universe": {"status": "SUCCESS"},
        "base_jobs": {"status": "SUCCESS"},
        "base_prediction": {"status": "SUCCESS"},
        "dashboard": {"status": "SUCCESS"},
        "site": {"status": "FAILED"},
    }
    automation_cycle._write_runtime(
        runtime_path,
        business_date=DATE,
        started_at="2026-08-25T10:00:00+08:00",
        finished_at="2026-08-25T10:01:00+08:00",
        steps=steps,
    )

    result = classify(json.loads(runtime_path.read_text(encoding="utf-8")), data_root=data_root, cycle_outcome="failure")

    assert result["ready"] is True
