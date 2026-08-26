import json
from pathlib import Path

from scripts.production_health_watch import evaluate_exact_score_health, evaluate_health


def _write_json(path: Path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _base_cycle(overall_status="HEALTHY", *, business_date="2026-08-12"):
    return {
        "schema_version": "1.0",
        "started_at": "2026-08-12T10:00:00+08:00",
        "finished_at": "2026-08-12T10:01:00+08:00",
        "business_date": business_date,
        "carryover_business_dates": [],
        "steps": {
            "universe": {"status": "SUCCESS", "returncode": 0},
            "base_jobs": {"status": "SUCCESS", "returncode": 0},
            "base_prediction": {"status": "SUCCESS", "returncode": 0},
            "prospective": {"status": "SUCCESS", "returncode": 0},
        },
        "overall_status": overall_status,
        "failed_steps": [],
    }


def _healthy_tree(tmp_path, *, universe_status="READY", fixture_count=1, jobs=None):
    data = tmp_path / "data"
    fixture = {
        "matchId": "M-1",
        "matchNum": "001",
        "matchDate": "2026-08-12",
        "matchTime": "23:00",
        "homeTeam": "Home",
        "awayTeam": "Away",
    }
    jobs = jobs if jobs is not None else [{
        "job_id": "BASE-2026-08-12-M-1",
        "business_date": "2026-08-12",
        "match_id": "M-1",
        "match_num": "001",
        "home": "Home",
        "away": "Away",
        "kickoff": "2026-08-12T23:00:00+08:00",
        "status": "PENDING",
    }]
    _write_json(data / "product_runtime" / "latest_cycle.json", _base_cycle())
    _write_json(data / "match_workspace" / "latest.json", {
        "schema_version": "1.0",
        "target_date": "2026-08-12",
        "generated_at": "2026-08-12T10:01:00+08:00",
        "matches": [fixture],
        "completed": [],
    })
    _write_json(data / "prediction_universe" / "2026-08-12.json", {
        "schema_version": "1.0",
        "business_date": "2026-08-12",
        "status": universe_status,
        "fixture_count": fixture_count,
        "fixtures": [] if universe_status == "EMPTY_CONFIRMED" else [fixture] * fixture_count,
    })
    _write_json(data / "base_prediction_jobs" / "2026-08-12.json", {
        "schema_version": "1.0",
        "business_date": "2026-08-12",
        "status": "READY",
        "fixture_count": len(jobs),
        "job_count": len(jobs),
        "jobs": jobs,
    })
    for directory in (
        "model_governance/predictions",
        "model_governance/input_snapshots",
        "model_governance/prediction_exclusions",
        "postmatch_automation/results",
    ):
        (data / directory).mkdir(parents=True, exist_ok=True)
    prospective = data / "prospective"
    prospective.mkdir(parents=True, exist_ok=True)
    (prospective / "ledger.jsonl").write_text("", encoding="utf-8")
    _write_json(prospective / "summary.json", {
        "schema_version": "1.0",
        "formal_sample_count_total": 0,
        "samples_added_this_run": 0,
        "pending_results": 0,
        "excluded_prediction_count": 0,
        "pilot_excluded_settled": 0,
        "result_failures": 0,
    })
    return tmp_path


def _cycle(tmp_path, status):
    _write_json(tmp_path / "data" / "product_runtime" / "latest_cycle.json", _base_cycle(status))


def _formal_champion_base_record(
    prediction_id,
    score,
    *,
    lambda_home=1.0,
    lambda_away=1.0,
    model_role="champion",
    prediction_variant="model_only",
):
    return {
        "prediction_id": prediction_id,
        "business_date": "2026-08-12",
        "prediction_status": "formal",
        "model_role": model_role,
        "prediction_variant": prediction_variant,
        "manual_override": False,
        "model_input_snapshot_ref": f"data/model_governance/input_snapshots/{prediction_id}.json",
        "input_sha256": f"input-{prediction_id}",
        "model_source_fingerprint": "champion-fingerprint",
        "match_key": f"MATCH-{prediction_id}",
        "match_identity": {
            "match_key": f"MATCH-{prediction_id}",
            "home": "Home",
            "away": "Away",
        },
        "kickoff_at": "2026-08-12T23:00:00+08:00",
        "source_cutoff_at": "2026-08-12T09:59:00+08:00",
        "prediction_created_at": "2026-08-12T10:00:00+08:00",
        "freeze_created_at": "2026-08-12T10:01:00+08:00",
        "critical_missing_fields": [],
        "missing_critical_fields": [],
        "formal_eligibility_policy": "base_prediction_minimum.v1",
        "formal_eligible": True,
        "model_formal_eligible": True,
        "base_input_quality": "VERIFIED_MINIMUM",
        "analysis_output": {"report_type": "base_prediction_minimal"},
        "probabilities": {"home": 0.4, "draw": 0.3, "away": 0.3},
        "lambda_home": lambda_home,
        "lambda_away": lambda_away,
        "btts": {"yes": 0.4, "no": 0.6},
        "unique_score": score,
        "score_top3": [score, "0-0", "2-1"],
    }


def test_evaluate_health_alerts_on_current_score_and_lambda_collapse(tmp_path):
    root = _healthy_tree(tmp_path)
    records = [
        _formal_champion_base_record(
            f"P-{index}",
            "1-1" if index < 8 else "2-1",
            lambda_home=1.0,
            lambda_away=1.2 if index < 7 else 2.0,
        )
        for index in range(9)
    ]
    for record in records:
        _write_json(
            root / "data" / "model_governance" / "predictions" / f"{record['prediction_id']}.json",
            record,
        )

    result = evaluate_health(root=root)
    health = result["details"]["production_exact_score_health"]

    assert result["status"] == "ALERT"
    assert result["notify"] is True
    assert "SCORE_SELECTOR_COLLAPSE" in result["reasons"]
    assert "LAMBDA_COMPRESSION" in result["reasons"]
    assert health["sample_count"] == 9
    assert health["dominant_score"] == "1-1"
    assert health["dominant_count"] == 8
    assert health["compressed_count"] == 7
    assert health["dominant_share"] == round(8 / 9, 6)
    assert health["compressed_share"] == round(7 / 9, 6)
    assert health["gap_threshold"] == 0.5


def test_exact_score_health_alerts_only_selector_collapse():
    result = evaluate_exact_score_health([
        _formal_champion_base_record(
            f"SELECTOR-{index}",
            "1-1" if index < 7 else "2-1",
            lambda_home=1.0,
            lambda_away=1.2 if index < 6 else 2.0,
        )
        for index in range(8)
    ])

    assert result["status"] == "ALERT"
    assert result["reasons"] == ["SCORE_SELECTOR_COLLAPSE"]
    assert result["dominant_count"] == 7
    assert result["dominant_share"] == 0.875
    assert result["compressed_count"] == 6
    assert result["compressed_share"] == 0.75


def test_exact_score_health_alerts_only_lambda_compression():
    result = evaluate_exact_score_health([
        _formal_champion_base_record(
            f"LAMBDA-{index}",
            f"{index}-{index + 1}",
            lambda_home=1.0,
            lambda_away=1.2 if index < 7 else 2.0,
        )
        for index in range(8)
    ])

    assert result["status"] == "ALERT"
    assert result["reasons"] == ["LAMBDA_COMPRESSION"]
    assert result["dominant_count"] == 1
    assert result["dominant_share"] == 0.125
    assert result["compressed_count"] == 7
    assert result["compressed_share"] == 0.875

    boundary = evaluate_exact_score_health([
        _formal_champion_base_record(
            f"LAMBDA-BOUNDARY-{index}",
            f"{index}-{index + 1}",
            lambda_home=1.0,
            lambda_away=1.2 if index < 7 else 2.0,
        )
        for index in range(10)
    ])

    assert boundary["compressed_count"] == 7
    assert boundary["compressed_share"] == 0.7
    assert boundary["reasons"] == []
    assert boundary["status"] == "HEALTHY"


def test_exact_score_health_ignores_small_samples_and_research_records():
    records = [
        _formal_champion_base_record(
            f"SMALL-{index}",
            "1-1",
            lambda_home=1.0,
            lambda_away=1.2,
        )
        for index in range(4)
    ]
    records.extend([
        _formal_champion_base_record("RESEARCH-1", "1-1", lambda_away=1.1, model_role="research"),
        _formal_champion_base_record("INFO-1", "1-1", lambda_away=1.1, prediction_variant="informational"),
    ])

    result = evaluate_exact_score_health(records)

    assert result["status"] == "INSUFFICIENT_SAMPLE"
    assert result["reasons"] == []
    assert result["eligible_record_count"] == 4
    assert result["sample_count"] == 4
    assert result["dominant_count"] == 4
    assert result["compressed_count"] == 4


def test_healthy_cycle_is_silent(tmp_path):
    result = evaluate_health(root=_healthy_tree(tmp_path))

    assert result["status"] == "HEALTHY"
    assert result["notify"] is False
    assert result["reasons"] == []


def test_current_workspace_has_no_freshness_reason(tmp_path):
    result = evaluate_health(root=_healthy_tree(tmp_path))

    assert "MATCH_WORKSPACE_STALE" not in result["reasons"]
    assert "MATCH_WORKSPACE_INVALID" not in result["reasons"]


def test_stale_workspace_is_detected(tmp_path):
    root = _healthy_tree(tmp_path)
    _write_json(root / "data" / "match_workspace" / "latest.json", {
        "schema_version": "1.0",
        "target_date": "2026-08-11",
        "generated_at": "2026-08-11T10:01:00+08:00",
        "matches": [],
        "completed": [],
    })

    result = evaluate_health(root=root)

    assert result["status"] == "ALERT"
    assert result["notify"] is True
    assert "MATCH_WORKSPACE_STALE" in result["reasons"]


def test_missing_workspace_is_not_healthy(tmp_path):
    root = _healthy_tree(tmp_path)
    (root / "data" / "match_workspace" / "latest.json").unlink()

    result = evaluate_health(root=root)

    assert result["status"] == "ALERT"
    assert result["notify"] is True
    assert "MATCH_WORKSPACE_INVALID" in result["reasons"]


def test_normal_business_states_do_not_alert(tmp_path):
    jobs = [{
        "job_id": "BASE-2026-08-12-M-1",
        "business_date": "2026-08-12",
        "match_id": "M-1",
        "match_num": "001",
        "kickoff": "2026-08-12T23:00:00+08:00",
        "status": "INSUFFICIENT_DATA",
        "last_error": "MISSING_RECENT_FORM",
    }]
    root = _healthy_tree(tmp_path, jobs=jobs)
    assert evaluate_health(root=root)["status"] == "HEALTHY"

    pending_cycle = _base_cycle()
    pending_cycle["steps"]["prospective"] = {
        "status": "SUCCESS", "returncode": 0,
        "summary": {"pending_results": 1},
    }
    _write_json(root / "data" / "product_runtime" / "latest_cycle.json", pending_cycle)
    assert evaluate_health(root=root)["status"] == "HEALTHY"

    _write_json(root / "data" / "prediction_universe" / "2026-08-12.json", {
        "schema_version": "1.0", "business_date": "2026-08-12",
        "status": "EMPTY_CONFIRMED", "fixture_count": 0, "fixtures": [],
    })
    _write_json(root / "data" / "base_prediction_jobs" / "2026-08-12.json", {
        "schema_version": "1.0", "business_date": "2026-08-12",
        "status": "EMPTY_CONFIRMED", "fixture_count": 0, "job_count": 0, "jobs": [],
    })
    assert evaluate_health(root=root)["status"] == "HEALTHY"


def test_fetch_failed_requires_two_cycles(tmp_path):
    root = _healthy_tree(tmp_path, universe_status="FETCH_FAILED", fixture_count=0, jobs=[])

    first = evaluate_health(root=root)
    second = evaluate_health(root=root)

    assert first["status"] == "WATCH"
    assert first["notify"] is False
    assert second["status"] == "ALERT"
    assert second["notify"] is True
    assert "UNIVERSE_FETCH_FAILED" in second["reasons"]


def test_engineering_degraded_requires_two_cycles_and_recovers(tmp_path):
    root = _healthy_tree(tmp_path)
    _cycle(root, "DEGRADED")

    first = evaluate_health(root=root)
    second = evaluate_health(root=root)
    assert first["status"] == "WATCH"
    assert second["status"] == "ALERT"
    assert second["notify"] is True

    _cycle(root, "HEALTHY")
    recovered = evaluate_health(root=root)
    assert recovered["status"] == "HEALTHY"
    assert recovered["notify"] is False
    assert recovered["consecutive_problem_cycles"] == 0


def test_silent_missing_fixture_is_immediate_alert(tmp_path):
    root = _healthy_tree(tmp_path, fixture_count=2)

    result = evaluate_health(root=root)

    assert result["status"] == "ALERT"
    assert result["notify"] is True
    assert "SILENT_MISSING_FIXTURES" in result["reasons"]


def test_prediction_after_kickoff_is_immediate_alert(tmp_path):
    root = _healthy_tree(tmp_path)
    _write_json(root / "data" / "model_governance" / "predictions" / "P-1.json", {
        "prediction_id": "P-1",
        "prediction_status": "formal",
        "job_id": "BASE-2026-08-12-M-1",
        "match_key": "MATCH-1",
        "kickoff_at": "2026-08-12T20:00:00+08:00",
        "prediction_created_at": "2026-08-12T20:01:00+08:00",
        "freeze_created_at": "2026-08-12T20:02:00+08:00",
    })

    result = evaluate_health(root=root)

    assert result["status"] == "ALERT"
    assert "PREDICTION_AFTER_KICKOFF" in result["reasons"]


def test_duplicate_formal_prospective_is_immediate_alert(tmp_path):
    root = _healthy_tree(tmp_path)
    ledger = root / "data" / "prospective" / "ledger.jsonl"
    ledger.write_text(
        '{"prediction_id":"P-1"}\n{"prediction_id":"P-1"}\n',
        encoding="utf-8",
    )

    result = evaluate_health(root=root)

    assert result["status"] == "ALERT"
    assert "DUPLICATE_FORMAL_PROSPECTIVE" in result["reasons"]


def test_duplicate_frozen_prediction_is_immediate_alert(tmp_path):
    root = _healthy_tree(tmp_path)
    common = {
        "prediction_status": "formal",
        "job_id": "BASE-2026-08-12-M-1",
        "match_key": "MATCH-1",
        "kickoff_at": "2026-08-12T23:00:00+08:00",
        "prediction_created_at": "2026-08-12T10:00:00+08:00",
        "freeze_created_at": "2026-08-12T10:01:00+08:00",
    }
    _write_json(root / "data" / "model_governance" / "predictions" / "P-1.json", {
        "prediction_id": "P-1", **common,
    })
    _write_json(root / "data" / "model_governance" / "predictions" / "P-2.json", {
        "prediction_id": "P-2", **common,
    })

    result = evaluate_health(root=root)

    assert result["status"] == "ALERT"
    assert "DUPLICATE_FROZEN_PREDICTION" in result["reasons"]


def test_formal_ledger_orphan_is_immediate_alert(tmp_path):
    root = _healthy_tree(tmp_path)
    (root / "data" / "prospective" / "ledger.jsonl").write_text(
        '{"prediction_id":"MISSING-PREDICTION"}\n', encoding="utf-8"
    )

    result = evaluate_health(root=root)

    assert result["status"] == "ALERT"
    assert "PROSPECTIVE_ORPHAN" in result["reasons"]


def test_malformed_durable_artifact_reaches_alert_after_two_cycles(tmp_path):
    root = _healthy_tree(tmp_path)
    (root / "data" / "prospective" / "ledger.jsonl").write_text(
        '{not-json}\n', encoding="utf-8"
    )

    first = evaluate_health(root=root)
    second = evaluate_health(root=root)

    assert first["status"] == "WATCH"
    assert second["status"] == "ALERT"
    assert "DURABLE_ARTIFACT_INVALID" in second["reasons"]


def test_excluded_pilot_in_formal_ledger_is_immediate_alert(tmp_path):
    root = _healthy_tree(tmp_path)
    _write_json(root / "data" / "model_governance" / "prediction_exclusions" / "pilot.json", {
        "prediction_ids": ["PILOT-1"],
        "reason_code": "BASE_QUALITY_GATE_BYPASS",
    })
    (root / "data" / "prospective" / "ledger.jsonl").write_text(
        '{"prediction_id":"PILOT-1"}\n', encoding="utf-8"
    )

    result = evaluate_health(root=root)

    assert result["status"] == "ALERT"
    assert "PILOT_EXCLUSION_VIOLATION" in result["reasons"]


def test_settlement_stuck_alerts_on_second_cycle(tmp_path):
    root = _healthy_tree(tmp_path)
    record = {
        "prediction_id": "P-VALID",
        "business_date": "2026-08-12",
        "prediction_status": "formal",
        "model_role": "champion",
        "prediction_variant": "model_only",
        "manual_override": None,
        "model_input_snapshot_ref": "data/model_governance/input_snapshots/I.json",
        "input_sha256": "hash",
        "model_source_fingerprint": "fingerprint",
        "match_key": "MATCH-VALID",
        "match_identity": {"match_key": "MATCH-VALID", "home": "Home", "away": "Away"},
        "kickoff_at": "2026-08-12T23:00:00+08:00",
        "prediction_created_at": "2026-08-12T10:00:00+08:00",
        "freeze_created_at": "2026-08-12T10:01:00+08:00",
        "source_cutoff_at": "2026-08-12T09:59:00+08:00",
        "critical_missing_fields": [],
        "missing_critical_fields": [],
        "formal_eligibility_policy": "base_prediction_minimum.v1",
        "formal_eligible": True,
        "model_formal_eligible": True,
        "base_input_quality": "VERIFIED_MINIMUM",
        "analysis_output": {"report_type": "base_prediction_minimal"},
        "probabilities": {"home": 0.4, "draw": 0.3, "away": 0.3},
        "lambda_home": 1.0,
        "lambda_away": 1.0,
        "btts": {"yes": 0.4, "no": 0.6},
        "unique_score": "1-0",
        "score_top3": ["1-0", "0-0", "1-1"],
    }
    _write_json(root / "data" / "model_governance" / "predictions" / "P-VALID.json", record)
    _write_json(root / "data" / "postmatch_automation" / "results" / "MATCH-VALID.json", {
        "match_key": "MATCH-VALID",
        "scope": "regulation_90m_plus_stoppage",
        "verified_at": "2026-08-13T01:00:00+08:00",
        "result_90m": "1-0",
    })

    first = evaluate_health(root=root)
    second = evaluate_health(root=root)

    assert first["status"] == "WATCH"
    assert "PROSPECTIVE_SETTLEMENT_STUCK" in first["reasons"]
    assert second["status"] == "ALERT"
    assert second["notify"] is True


def test_no_eligible_settlement_is_healthy(tmp_path):
    root = _healthy_tree(tmp_path)

    result = evaluate_health(root=root)

    assert result["status"] == "HEALTHY"


def test_corrupt_health_state_is_safe_alert(tmp_path):
    root = _healthy_tree(tmp_path)
    state = root / "data" / "product_runtime" / "health_watch.json"
    state.write_text("{not-json", encoding="utf-8")

    result = evaluate_health(root=root)

    assert result["status"] == "ALERT"
    assert result["notify"] is True
    assert "HEALTH_STATE_CORRUPTED" in result["reasons"]


def test_result_conflict_is_immediate_alert(tmp_path):
    root = _healthy_tree(tmp_path)
    cycle = _base_cycle()
    cycle["steps"]["prospective"] = {
        "status": "SUCCESS", "returncode": 0,
        "summary": {"result_conflicts": 1, "failure_reasons": {"RESULT_CONFLICT": 1}},
    }
    _write_json(root / "data" / "product_runtime" / "latest_cycle.json", cycle)

    result = evaluate_health(root=root)

    assert result["status"] == "ALERT"
    assert "RESULT_CONFLICT" in result["reasons"]
