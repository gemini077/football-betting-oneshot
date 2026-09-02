import json
from pathlib import Path

from scripts.production_health_watch import (
    classify_frozen_prediction_duplicates,
    evaluate_exact_score_health,
    evaluate_health,
    select_current_serving_predictions,
)


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


def _versioned_prediction(
    prediction_id,
    *,
    match_id="M-1",
    job_id="JOB-1",
    match_key="MATCH-1",
    score="1-1",
    source="2026-08-12T09:59:00+08:00",
    created="2026-08-12T10:00:00+08:00",
    freeze="2026-08-12T10:01:00+08:00",
):
    record = _formal_champion_base_record(prediction_id, score)
    record.update({
        "job_id": job_id,
        "match_id": match_id,
        "match_key": match_key,
        "source_cutoff_at": source,
        "prediction_created_at": created,
        "freeze_created_at": freeze,
    })
    record["match_identity"] = {
        "match_key": match_key,
        "match_id": match_id,
        "home": "Home",
        "away": "Away",
        "kickoff_at": record["kickoff_at"],
    }
    return record


def _current_job(record, *, status="FROZEN", last_error=None):
    return {
        "job_id": record.get("job_id"),
        "business_date": "2026-08-12",
        "match_id": record.get("match_id"),
        "match_key": record.get("match_key"),
        "home": "Home",
        "away": "Away",
        "kickoff": record.get("kickoff_at"),
        "status": status,
        "prediction_id": record.get("prediction_id"),
        "last_error": last_error,
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
    jobs_path = root / "data" / "base_prediction_jobs" / "2026-08-12.json"
    jobs_payload = json.loads(jobs_path.read_text(encoding="utf-8"))
    jobs_payload["jobs"].extend([
        {
            "job_id": f"HEALTH-JOB-{index}",
            "business_date": "2026-08-12",
            "match_id": f"HEALTH-M-{index}",
            "match_key": record["match_key"],
            "home": "Home",
            "away": "Away",
            "kickoff": record["kickoff_at"],
            "status": "FROZEN",
            "prediction_id": record["prediction_id"],
        }
        for index, record in enumerate(records)
    ])
    jobs_payload["job_count"] = len(jobs_payload["jobs"])
    _write_json(jobs_path, jobs_payload)
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
    assert result["prediction_quality_health"]["status"] == "ALERT"
    assert result["prediction_quality_health"]["scope"] == "current_serving"
    assert result["prediction_quality_health"]["business_date"] == "2026-08-12"
    assert result["prediction_quality_health"]["runtime_cycle_finished_at"] == "2026-08-12T10:01:00+08:00"
    state = json.loads((root / "data" / "product_runtime" / "health_watch.json").read_text(encoding="utf-8"))
    assert state["business_date"] == "2026-08-12"
    assert state["prediction_quality_health"] == result["prediction_quality_health"]


def test_current_serving_selector_uses_latest_legal_version_once_per_match():
    records = []
    latest_ids = []
    for index in range(10):
        match_id = f"SERVING-M-{index}"
        match_key = f"SERVING-MATCH-{index}"
        records.append(_versioned_prediction(
            f"OLD-{index}",
            match_id=match_id,
            job_id=f"SERVING-JOB-{index}",
            match_key=match_key,
            score="0-0",
            source="2026-08-12T09:00:00+08:00",
            created="2026-08-12T09:01:00+08:00",
            freeze="2026-08-12T09:02:00+08:00",
        ))
        latest_id = f"LATEST-{index}"
        latest_ids.append(latest_id)
        records.append(_versioned_prediction(
            latest_id,
            match_id=match_id,
            job_id=f"SERVING-JOB-{index}",
            match_key=match_key,
            score="1-1" if index < 9 else "2-1",
            source="2026-08-12T09:59:00+08:00",
            created="2026-08-12T10:00:00+08:00",
            freeze="2026-08-12T10:01:00+08:00",
        ))

    pilot = _versioned_prediction(
        "PILOT-1",
        match_id="PILOT-MATCH",
        job_id="PILOT-JOB",
        match_key="PILOT-MATCH-KEY",
    )
    records.append(pilot)
    post_kickoff = _versioned_prediction(
        "POST-KICKOFF-1",
        match_id="POST-KICKOFF-MATCH",
        job_id="POST-KICKOFF-JOB",
        match_key="POST-KICKOFF-MATCH-KEY",
    )
    post_kickoff["prediction_created_at"] = "2026-08-13T00:01:00+08:00"
    post_kickoff["freeze_created_at"] = "2026-08-13T00:02:00+08:00"
    records.append(post_kickoff)
    integrity_invalid = _versioned_prediction(
        "INVALID-1",
        match_id="INVALID-MATCH",
        job_id="INVALID-JOB",
        match_key="INVALID-MATCH-KEY",
    )
    integrity_invalid["prediction_conflicts"] = ["immutable final conflict"]
    records.append(integrity_invalid)
    other_date = _versioned_prediction(
        "OTHER-DATE-1",
        match_id="OTHER-DATE-MATCH",
        job_id="OTHER-DATE-JOB",
        match_key="OTHER-DATE-MATCH-KEY",
    )
    other_date["business_date"] = "2026-08-11"
    records.append(other_date)

    selection = select_current_serving_predictions(
        records,
        business_date="2026-08-12",
        current_jobs=[
            _current_job(
                _versioned_prediction(
                    f"JOB-SEED-{index}",
                    match_id=f"SERVING-M-{index}",
                    job_id=f"SERVING-JOB-{index}",
                    match_key=f"SERVING-MATCH-{index}",
                )
            )
            for index in range(10)
        ],
        excluded_ids={"PILOT-1"},
    )

    selected = selection["selected_records"]
    assert len(selected) == 10
    assert {record["prediction_id"] for record in selected} == set(latest_ids)
    assert len({record["match_id"] for record in selected}) == 10
    assert selection["current_business_date"] == "2026-08-12"


def test_current_serving_selector_fails_closed_without_current_job_state():
    record = _versioned_prediction("NO-JOB-RECORD")

    selection = select_current_serving_predictions(
        [record],
        business_date="2026-08-12",
    )

    assert selection["current_job_count"] == 0
    assert selection["current_frozen_job_count"] == 0
    assert selection["selected_record_count"] == 0
    assert selection["selected_prediction_ids"] == []


def test_current_serving_selector_uses_only_frozen_current_jobs_with_retained_predictions():
    records = []
    current_jobs = []
    frozen_ids = []
    frozen_job_ids = []
    for index in range(13):
        match_id = f"CURRENT-M-{index}"
        job_id = f"CURRENT-JOB-{index}"
        prediction_id = f"CURRENT-PRED-{index}"
        record = _versioned_prediction(
            prediction_id,
            match_id=match_id,
            job_id=job_id,
            match_key=f"CURRENT-MATCH-{index}",
        )
        status = "FROZEN" if index < 8 else "INSUFFICIENT_DATA"
        records.append(record)
        current_jobs.append(_current_job(record, status=status, last_error="SOURCE_FETCH_FAILED" if index >= 8 else None))
        if status == "FROZEN":
            frozen_ids.append(prediction_id)
            frozen_job_ids.append(job_id)

    selection = select_current_serving_predictions(
        records,
        business_date="2026-08-12",
        current_jobs=current_jobs,
    )

    assert selection["current_job_count"] == 13
    assert selection["current_frozen_job_count"] == 8
    assert selection["selected_record_count"] == 8
    assert selection["selected_prediction_ids"] == sorted(frozen_ids)
    assert selection["selected_job_ids"] == sorted(frozen_job_ids)


def test_current_serving_health_alerts_on_served_collapse_without_nonserved_dilution(tmp_path):
    root = _healthy_tree(tmp_path)
    jobs_path = root / "data" / "base_prediction_jobs" / "2026-08-12.json"
    jobs_payload = json.loads(jobs_path.read_text(encoding="utf-8"))
    records = []
    current_jobs = []
    for index in range(13):
        match_id = f"COHORT-M-{index}"
        record = _versioned_prediction(
            f"COHORT-PRED-{index}",
            match_id=match_id,
            job_id=f"COHORT-JOB-{index}",
            match_key=f"COHORT-MATCH-{index}",
            score="1-1" if index < 8 else f"{index % 3}-{(index + 1) % 4}",
        )
        record["lambda_away"] = 1.2 if index < 8 else 2.0
        records.append(record)
        current_jobs.append(_current_job(
            record,
            status="FROZEN" if index < 8 else "INSUFFICIENT_DATA",
            last_error="SOURCE_FETCH_FAILED" if index >= 8 else None,
        ))
        _write_json(
            root / "data" / "model_governance" / "predictions" / f"{record['prediction_id']}.json",
            record,
        )
    jobs_payload["jobs"].extend(current_jobs)
    jobs_payload["job_count"] = len(jobs_payload["jobs"])
    _write_json(jobs_path, jobs_payload)

    result = evaluate_health(root=root)
    selection = result["details"]["production_current_serving_selection"]
    health = result["details"]["production_exact_score_health"]

    assert selection["selected_record_count"] == 8
    assert health["sample_count"] == 8
    assert health["dominant_score"] == "1-1"
    assert health["dominant_count"] == 8
    assert health["status"] == "ALERT"
    assert "SCORE_SELECTOR_COLLAPSE" in health["reasons"]
    assert result["prediction_quality_health"]["status"] == "ALERT"


def test_evaluate_health_gates_on_current_serving_and_keeps_historical_audit(tmp_path):
    root = _healthy_tree(tmp_path)
    current_jobs = []
    for index in range(10):
        match_id = f"AUDIT-M-{index}"
        match_key = f"AUDIT-MATCH-{index}"
        for prediction_id, score, source, created, freeze in (
            (
                f"AUDIT-OLD-{index}",
                "0-0",
                "2026-08-12T09:00:00+08:00",
                "2026-08-12T09:01:00+08:00",
                "2026-08-12T09:02:00+08:00",
            ),
            (
                f"AUDIT-LATEST-{index}",
                "1-1" if index < 9 else "2-1",
                "2026-08-12T09:59:00+08:00",
                "2026-08-12T10:00:00+08:00",
                "2026-08-12T10:01:00+08:00",
            ),
        ):
            record = _versioned_prediction(
                prediction_id,
                match_id=match_id,
                job_id=f"AUDIT-JOB-{index}",
                match_key=match_key,
                score=score,
                source=source,
                created=created,
                freeze=freeze,
            )
            record["lambda_away"] = 2.0
            if prediction_id.startswith("AUDIT-LATEST"):
                current_jobs.append(_current_job(record))
            _write_json(
                root / "data" / "model_governance" / "predictions" / f"{prediction_id}.json",
                record,
            )
    jobs_path = root / "data" / "base_prediction_jobs" / "2026-08-12.json"
    jobs_payload = json.loads(jobs_path.read_text(encoding="utf-8"))
    jobs_payload["jobs"].extend(current_jobs)
    jobs_payload["job_count"] = len(jobs_payload["jobs"])
    _write_json(jobs_path, jobs_payload)

    result = evaluate_health(root=root)
    current = result["details"]["production_exact_score_health"]
    audit = result["details"]["production_exact_score_health_historical_audit"]

    assert result["status"] == "ALERT"
    assert "SCORE_SELECTOR_COLLAPSE" in result["reasons"]
    assert current["sample_count"] == 10
    assert current["dominant_score"] == "1-1"
    assert current["dominant_count"] == 9
    assert current["dominant_share"] == 0.9
    assert audit["sample_count"] == 20
    assert audit["status"] == "HEALTHY"
    assert result["details"]["production_exact_score_health_scopes"]["current_serving"] == current
    assert result["details"]["production_exact_score_health_scopes"]["historical_audit"] == audit


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
    first = _versioned_prediction("P-1", score="1-0")
    second = _versioned_prediction("P-2", score="0-1")
    _write_json(root / "data" / "model_governance" / "predictions" / "P-1.json", first)
    _write_json(root / "data" / "model_governance" / "predictions" / "P-2.json", second)

    result = evaluate_health(root=root)

    assert result["status"] == "ALERT"
    assert "DUPLICATE_FROZEN_PREDICTION" in result["reasons"]
    duplicate = result["details"]["production_duplicate_health"]
    assert duplicate["actual_duplicate_final_group_count"] == 1
    assert duplicate["identity_collision_group_count"] == 0


def test_legitimate_immutable_version_history_does_not_alert(tmp_path):
    records = [
        _versioned_prediction(
            "V1",
            source="2026-08-12T09:59:00+08:00",
            created="2026-08-12T10:00:00+08:00",
            freeze="2026-08-12T10:01:00+08:00",
        ),
        _versioned_prediction(
            "V2",
            source="2026-08-12T12:59:00+08:00",
            created="2026-08-12T13:00:00+08:00",
            freeze="2026-08-12T13:01:00+08:00",
        ),
        _versioned_prediction(
            "V3",
            source="2026-08-12T15:59:00+08:00",
            created="2026-08-12T16:00:00+08:00",
            freeze="2026-08-12T16:01:00+08:00",
        ),
    ]

    duplicate = classify_frozen_prediction_duplicates(records)

    assert duplicate["raw_frozen_record_count"] == 3
    assert duplicate["unique_match_count"] == 1
    assert duplicate["version_history_group_count"] == 1
    assert duplicate["actual_duplicate_final_group_count"] == 0
    assert duplicate["identity_collision_group_count"] == 0
    assert duplicate["duplicate_alert"] is False
    assert duplicate["groups"][0]["category"] == "A"
    assert duplicate["groups"][0]["selected_prediction_id"] == "V3"


def test_identity_collision_remains_an_immediate_alert(tmp_path):
    root = _healthy_tree(tmp_path)
    first = _versioned_prediction("C-1", match_id="M-1", match_key="MATCH-1")
    second = _versioned_prediction("C-2", match_id="M-2", match_key="MATCH-2")
    _write_json(root / "data" / "model_governance" / "predictions" / "C-1.json", first)
    _write_json(root / "data" / "model_governance" / "predictions" / "C-2.json", second)

    result = evaluate_health(root=root)

    assert result["status"] == "ALERT"
    assert "DUPLICATE_FROZEN_PREDICTION" in result["reasons"]
    duplicate = result["details"]["production_duplicate_health"]
    assert duplicate["actual_duplicate_final_group_count"] == 0
    assert duplicate["identity_collision_group_count"] == 1


def test_single_legal_prediction_is_healthy_on_duplicate_dimension(tmp_path):
    root = _healthy_tree(tmp_path)
    record = _versioned_prediction("SINGLE")
    _write_json(root / "data" / "model_governance" / "predictions" / "SINGLE.json", record)

    result = evaluate_health(root=root)

    assert "DUPLICATE_FROZEN_PREDICTION" not in result["reasons"]
    duplicate = result["details"]["production_duplicate_health"]
    assert duplicate["unique_match_count"] == 1
    assert duplicate["version_history_group_count"] == 0
    assert duplicate["actual_duplicate_final_group_count"] == 0
    assert duplicate["identity_collision_group_count"] == 0


def test_other_health_reason_is_not_swallowed_by_duplicate_fix(tmp_path):
    root = _healthy_tree(tmp_path)
    for record in (
        _versioned_prediction("E-1", source="2026-08-12T09:59:00+08:00"),
        _versioned_prediction(
            "E-2",
            source="2026-08-12T12:59:00+08:00",
            created="2026-08-12T13:00:00+08:00",
            freeze="2026-08-12T13:01:00+08:00",
        ),
    ):
        _write_json(root / "data" / "model_governance" / "predictions" / f"{record['prediction_id']}.json", record)
    _write_json(root / "data" / "match_workspace" / "latest.json", {
        "schema_version": "1.0",
        "target_date": "2026-08-11",
        "generated_at": "2026-08-11T10:01:00+08:00",
        "matches": [],
        "completed": [],
    })

    result = evaluate_health(root=root)

    assert result["status"] == "ALERT"
    assert "MATCH_WORKSPACE_STALE" in result["reasons"]
    assert "DUPLICATE_FROZEN_PREDICTION" not in result["reasons"]


def test_frozen_integrity_violation_remains_an_immediate_alert(tmp_path):
    root = _healthy_tree(tmp_path)
    record = _versioned_prediction("INTEGRITY")
    record["prediction_conflicts"] = ["immutable final conflict"]
    _write_json(root / "data" / "model_governance" / "predictions" / "INTEGRITY.json", record)

    result = evaluate_health(root=root)

    assert result["status"] == "ALERT"
    assert "IMMUTABLE_PREDICTION_CONFLICT" in result["reasons"]


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


def test_runtime_snapshot_ready_is_exposed_as_internal_health(tmp_path):
    root = _healthy_tree(tmp_path)
    health_path = tmp_path / "runtime_snapshot_health.json"
    _write_json(health_path, {
        "status": "READY",
        "snapshot_version": "snapshot-20260830T010203Z-" + "1" * 64,
        "dataset_sha256": "2" * 64,
        "record_count": 1778,
        "bootstrap_at": "2026-08-30T01:02:03Z",
    })

    result = evaluate_health(root=root, runtime_snapshot_path=health_path)

    assert result["status"] == "HEALTHY"
    assert result["runtime_data_snapshot"]["status"] == "READY"
    assert result["details"]["runtime_data_snapshot"]["record_count"] == 1778


def test_runtime_snapshot_fallback_is_not_reported_as_healthy(tmp_path):
    root = _healthy_tree(tmp_path)
    health_path = tmp_path / "runtime_snapshot_health.json"
    _write_json(health_path, {
        "status": "DEGRADED_LAST_KNOWN_GOOD",
        "snapshot_version": "snapshot-20260830T010203Z-" + "1" * 64,
        "dataset_sha256": "2" * 64,
        "record_count": 1778,
        "bootstrap_at": "2026-08-30T01:02:03Z",
    })

    result = evaluate_health(root=root, runtime_snapshot_path=health_path)

    assert result["status"] == "WATCH"
    assert result["runtime_data_snapshot"]["status"] == "DEGRADED_LAST_KNOWN_GOOD"
    assert "DEGRADED_DATA_SNAPSHOT" in result["reasons"]


def test_runtime_snapshot_failure_is_immediate_alert(tmp_path):
    root = _healthy_tree(tmp_path)
    health_path = tmp_path / "runtime_snapshot_health.json"
    _write_json(health_path, {
        "status": "FAILED",
        "snapshot_version": None,
        "dataset_sha256": None,
        "record_count": None,
        "bootstrap_at": "2026-08-30T01:02:03Z",
    })

    result = evaluate_health(root=root, runtime_snapshot_path=health_path)

    assert result["status"] == "ALERT"
    assert result["runtime_data_snapshot"]["status"] == "FAILED"
    assert "RUNTIME_DATA_SNAPSHOT_FAILED" in result["reasons"]


def test_runtime_snapshot_ready_with_missing_runtime_database_is_not_healthy(tmp_path, monkeypatch):
    root = _healthy_tree(tmp_path)
    health_path = tmp_path / "runtime_snapshot_health.json"
    _write_json(health_path, {
        "status": "READY",
        "snapshot_version": "snapshot-20260830T010203Z-" + "1" * 64,
        "dataset_sha256": "2" * 64,
        "record_count": 1778,
        "bootstrap_at": "2026-08-30T01:02:03Z",
    })
    monkeypatch.setenv("FOOTBALL_DATA_HOME", str(tmp_path / "missing-runtime-home"))

    result = evaluate_health(root=root, runtime_snapshot_path=health_path)

    assert result["status"] == "ALERT"
    assert result["runtime_data_snapshot"]["status"] == "FAILED"
    assert result["runtime_data_snapshot"]["error"] == "RUNTIME_DATASET_PARITY_FAILED"
    assert "RUNTIME_DATA_SNAPSHOT_FAILED" in result["reasons"]


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
