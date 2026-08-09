import hashlib
import json
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from automatic_model_core import build_automatic_model
from model_governance import (
    PredictionConflictError,
    build_deterministic_model_input_snapshot,
    build_current_metrics,
    build_prediction_record,
    can_update_parameters,
    evaluate_promotion,
    freeze_prediction,
    hash_files,
    load_input_snapshot,
    load_config,
    model_source_fingerprint,
    prediction_content_hash,
    replay_deterministic_model_from_snapshot,
    validate_postmatch_review_link,
)


MODEL_FAMILY = "recent_form_market_calibrated_poisson_v2"
RELEASE_VERSION = "v0.19.0"


def prediction_payload(
    grade="B",
    *,
    model_family=MODEL_FAMILY,
    odds=None,
    match_id="FBOS-test-001",
    release_version=RELEASE_VERSION,
    manual_override=None,
    lineup_status=None,
):
    candidate = [] if odds is None else [{"odds": odds, "price_source": "real-executable"}]
    payload = {
        "report": {
            "model_version": release_version,
            "analysis_timestamp": "2026-08-05T00:00:00+08:00",
            "snapshot_timestamp": "2026-08-04T23:59:00+08:00",
            "market_checkpoint": {"captured_at": "2026-08-04T23:59:00+08:00"},
        },
        "match": {
            "canonical_match_id": match_id,
            "home": "Home FC",
            "away": "Away FC",
            "kickoff_local": "2026-08-05T02:00:00+08:00",
        },
        "data_quality": {"missing": []},
        "model": {
            "method": model_family,
            "lambda_home": 1.2,
            "lambda_away": 0.9,
            "rho": 0.0,
            "probabilities": {"home": 0.45, "draw": 0.3, "away": 0.25},
            "score_probabilities": [
                {"score": "1-0", "probability": 0.15},
                {"score": "1-1", "probability": 0.13},
                {"score": "0-0", "probability": 0.10},
                {"score": "2-0", "probability": 0.09},
                {"score": "2-1", "probability": 0.08},
            ],
            "dimension_predictions": {
                "1x2": {"selection": "home", "model_probability": 0.45}
            },
        },
        "decisions": {
            "data_grade": grade,
            "prediction_tier": "formal" if grade in {"A", "B"} else "research",
            "unique_primary_dimension": "胜平负：主胜",
            "unique_score": "1-0",
        },
        "betting": {"candidates": candidate},
        "automation": {"provider": "fixed-python-core"},
    }
    if manual_override is not None:
        payload["manual_override"] = manual_override
    if lineup_status is not None:
        payload["data_quality"]["lineup_status"] = lineup_status
    return attach_snapshot(payload)


def deterministic_context():
    deep = {
        "fetched_at": "2026-08-04T23:58:00+08:00",
        "source_provenance": {"form_primary": "nowscore_analysis"},
        "shuju": {"recent_form": {
            "home_overall": {"matches": 10, "goals_for": 12, "goals_against": 13},
            "away_overall": {"matches": 10, "goals_for": 22, "goals_against": 9},
            "home_home": {"matches": 10, "goals_for": 19, "goals_against": 11},
            "away_away": {"matches": 10, "goals_for": 16, "goals_against": 13},
        }},
        "ouzhi": {"bookmakers": [
            {"spf_current": {"home": 4.5, "draw": 4.0, "away": 1.7}},
            {"spf_current": {"home": 4.2, "draw": 3.8, "away": 1.72}},
        ]},
        "daxiao": {"companies": [
            {"name": "A", "current_line": 2.75, "current_over_water": 0.92, "current_under_water": 0.94},
            {"name": "B", "current_line": 2.5, "current_over_water": 0.90, "current_under_water": 0.96},
        ]},
        "yazhi": {"companies": [
            {"name": "A", "current_handicap": 0.0, "current_water_home": 0.90, "current_water_away": 0.94},
            {"name": "B", "current_handicap": 0.0, "current_water_home": 0.92, "current_water_away": 0.92},
        ]},
        "nowscore_context": {
            "coach": {"home": {}, "away": {}},
            "referee": {},
            "panlu": {},
            "source_urls": {},
        },
    }
    return {
        "request": {"match_id": "2040514"},
        "selected_workspace_match": {"id": "2040514", "home": "主队", "away": "客队"},
        "source_snapshots": {"500_deep": {"snapshots": [deep]}},
        "checkpoint_features": {
            "snapshot_count": 1,
            "state": "single_snapshot",
            "latest_captured_at": "2026-08-04T23:58:30+08:00",
            "first_captured_at": "2026-08-04T23:58:30+08:00",
            "leader_reversals": 0,
            "probability_delta": {"home": 0.0, "draw": 0.0, "away": 0.0},
            "points": [],
        },
        "official_market_baseline": {
            "fair_probabilities": {"home": 0.4, "draw": 0.3, "away": 0.3},
        },
        "model_calibration": {"active": False, "model_family": MODEL_FAMILY},
        "hard_rules": {"bankroll_state_changed": False},
    }


def attach_snapshot(payload, context=None):
    context = context or deterministic_context()
    snapshot = build_deterministic_model_input_snapshot(context, manifest_ref="data/fetch_runs/test/manifest.json")
    payload["automation"]["model_input_snapshot"] = snapshot
    return payload


def test_champion_configuration_loads_and_matches_actual_model():
    config = load_config()
    assert config["champion"]["model_core_version"] == MODEL_FAMILY
    assert config["champion"]["model_family"] == MODEL_FAMILY
    assert config["champion"]["release_version"] == RELEASE_VERSION
    assert config["champion"]["rho"] == 0.0
    assert config["challengers"] == []


def test_governance_version_fields_are_complete():
    config = load_config()
    versions = config["versions"]
    assert all(versions.get(key) for key in (
        "feature_version",
        "data_pipeline_version",
        "report_schema_version",
        "postmatch_schema_version",
        "prompt_version",
    ))
    assert prediction_payload()["automation"]["provider"] == "fixed-python-core"


def test_governance_schemas_declare_conditional_identity_contracts():
    analysis_schema = json.loads((ROOT / "schemas" / "analysis_report.schema.json").read_text(encoding="utf-8"))
    analysis_branch = next(
        branch for branch in analysis_schema["allOf"]
        if branch.get("if", {}).get("properties", {}).get("schema_version", {}).get("const") == "1.1"
    )
    assert {
        "analysis_output",
        "prediction_output",
        "betting_reference_output",
        "model_governance",
    } <= set(analysis_branch["then"]["required"])
    assert "model_input_snapshot_ref" in analysis_branch["then"]["properties"]["model_governance"]["required"]

    postmatch_schema = json.loads((ROOT / "schemas" / "postmatch_review.schema.json").read_text(encoding="utf-8"))
    postmatch_branch = postmatch_schema["allOf"][0]
    assert "prediction_id" in postmatch_branch["then"]["required"]
    assert "model_source_fingerprint" in postmatch_branch["then"]["required"]
    assert "canonical_model_input_sha256" in postmatch_branch["then"]["required"]


def test_same_input_freeze_is_idempotent(tmp_path):
    record = build_prediction_record(prediction_payload(), commit_sha="baseline-sha")
    first = freeze_prediction(record, tmp_path)
    second = freeze_prediction(record, tmp_path)
    assert first["status"] == "created"
    assert second["status"] == "existing"
    assert first["path"] == second["path"]


def test_same_prediction_id_with_different_content_is_a_conflict(tmp_path):
    record = build_prediction_record(prediction_payload(), commit_sha="baseline-sha")
    freeze_prediction(record, tmp_path)
    changed = dict(record)
    changed["lambda_home"] = 9.9
    changed["prediction_sha256"] = prediction_content_hash(changed)
    with pytest.raises(PredictionConflictError):
        freeze_prediction(changed, tmp_path)


def test_frozen_prediction_rejects_postmatch_fields():
    payload = prediction_payload()
    payload["result"] = {"score_90m": "1-0"}
    with pytest.raises(ValueError, match="postmatch"):
        build_prediction_record(payload, commit_sha="baseline-sha")


def test_frozen_prediction_rejects_nested_postmatch_fields(tmp_path):
    record = build_prediction_record(prediction_payload(), commit_sha="baseline-sha")
    record["prediction_output"]["result"] = {"score_90m": "1-0"}
    with pytest.raises(ValueError, match="postmatch"):
        freeze_prediction(record, tmp_path)


@pytest.mark.parametrize("grade, formal", [("A", True), ("B", True), ("C", False), ("D", False)])
def test_quality_grade_controls_formal_eligibility(grade, formal):
    record = build_prediction_record(prediction_payload(grade), commit_sha="baseline-sha")
    assert record["formal_eligible"] is formal
    assert record["prediction_output"]["status"] == ("formal" if formal else "research_only")


def test_b_grade_minor_lineup_gap_can_remain_formal_when_unavailable_by_time():
    payload = prediction_payload("B")
    payload["data_quality"] = {
        "missing": ["lineup confirmation"],
        "lineup_status": "unavailable_by_time",
    }
    record = build_prediction_record(payload, commit_sha="baseline-sha")
    assert record["formal_eligible"] is True
    assert record["critical_missing_fields"] == []
    assert record["noncritical_missing_fields"] == ["lineup confirmation"]
    assert record["lineup_status"] == "unavailable_by_time"


def test_critical_missing_field_forces_research_only():
    payload = prediction_payload("B")
    snapshot = payload["automation"]["model_input_snapshot"]
    snapshot["source_cutoff_at"] = None
    snapshot["market_snapshot_at"] = None
    snapshot["odds_snapshot_at"] = None
    record = build_prediction_record(payload, commit_sha="baseline-sha")
    assert record["formal_eligible"] is False
    assert record["prediction_status"] == "research_only"
    assert "source_cutoff_at" in record["critical_missing_fields"]
    assert "odds_snapshot_at" in record["critical_missing_fields"]


@pytest.mark.parametrize(
    "lineup_status, formal",
    [
        ("unavailable_by_time", True),
        ("projected", True),
        ("confirmed", True),
        ("missing_unexpectedly", False),
    ],
)
def test_lineup_status_controls_formal_eligibility(lineup_status, formal):
    payload = prediction_payload("B", lineup_status=lineup_status)
    payload["data_quality"]["missing"] = ["lineup confirmation"] if lineup_status != "confirmed" else []
    record = build_prediction_record(payload, commit_sha="baseline-sha")
    assert record["formal_eligible"] is formal
    assert record["lineup_status"] == lineup_status


def test_projected_lineup_policy_is_explicit():
    config = load_config()
    config["quality_policy"] = dict(config["quality_policy"])
    config["quality_policy"]["projected_lineup_formal_allowed"] = False
    payload = prediction_payload("B", lineup_status="projected")
    payload["data_quality"]["missing"] = ["lineup confirmation"]
    record = build_prediction_record(payload, config=config, commit_sha="baseline-sha")
    assert record["formal_eligible"] is False
    assert record["critical_missing_fields"] == ["lineup confirmation"]


def test_manual_override_isolated_from_model_metrics():
    record = build_prediction_record(
        prediction_payload("A", manual_override=True),
        commit_sha="baseline-sha",
    )
    assert record["formal_eligible"] is False
    assert record["model_formal_eligible"] is False
    assert record["prediction_variant"] == "human_assisted"
    assert record["prediction_status"] == "human_assisted"


def test_legacy_and_champion_records_are_separated():
    champion = build_prediction_record(prediction_payload(), commit_sha="baseline-sha")
    legacy = build_prediction_record(
        prediction_payload(model_family="legacy_poisson_v1"), commit_sha="baseline-sha"
    )
    assert champion["model_role"] == "champion"
    assert legacy["model_role"] == "legacy"
    assert legacy["formal_eligible"] is False


def test_previous_release_is_not_current_champion():
    legacy = build_prediction_record(
        {**prediction_payload(), "report": {**prediction_payload()["report"], "model_version": "v0.18.2"}},
        commit_sha="baseline-sha",
    )
    assert legacy["model_role"] == "legacy"
    assert legacy["formal_eligible"] is False


def test_prediction_identity_is_split_into_match_snapshot_and_model_run_layers():
    record = build_prediction_record(attach_snapshot(prediction_payload()), commit_sha="baseline-sha")
    assert record["match_identity"]["match_key"] == record["match_key"]
    assert record["snapshot_identity"]["snapshot_id"] == record["input_snapshot"]["snapshot_id"]
    assert record["model_run_identity"]["release_version"] == RELEASE_VERSION
    assert "repository_commit_sha" not in record["model_run_identity"]
    assert record["model_source_fingerprint"]
    assert record["model_run_fingerprint"]
    assert record["prediction_id"].startswith("FBOS-PRED-")


def test_unrelated_repository_commit_does_not_change_model_identity():
    first = build_prediction_record(attach_snapshot(prediction_payload()), commit_sha="data-commit-a")
    second = build_prediction_record(attach_snapshot(prediction_payload()), commit_sha="data-commit-b")
    assert first["model_source_fingerprint"] == second["model_source_fingerprint"]
    assert first["model_run_fingerprint"] == second["model_run_fingerprint"]
    assert first["prediction_id"] == second["prediction_id"]
    assert first["prediction_sha256"] == second["prediction_sha256"]


def test_unrelated_repository_commit_remains_idempotent_when_frozen(tmp_path):
    first = build_prediction_record(attach_snapshot(prediction_payload()), commit_sha="data-commit-a")
    second = build_prediction_record(attach_snapshot(prediction_payload()), commit_sha="data-commit-b")
    assert freeze_prediction(first, tmp_path)["status"] == "created"
    assert freeze_prediction(second, tmp_path)["status"] == "existing"


def test_prompt_metadata_does_not_change_deterministic_champion_identity():
    first_payload = attach_snapshot(prediction_payload())
    second_payload = attach_snapshot(prediction_payload())
    first_payload["automation"]["prompt_version"] = "narrative-a"
    second_payload["automation"]["prompt_version"] = "narrative-b"
    first = build_prediction_record(first_payload, commit_sha="data-commit")
    second = build_prediction_record(second_payload, commit_sha="data-commit")
    assert first["model_run_fingerprint"] == second["model_run_fingerprint"]
    assert first["prediction_id"] == second["prediction_id"]


def test_model_source_fingerprint_changes_when_a_model_component_changes(tmp_path):
    component = tmp_path / "core.py"
    component.write_text("lambda_home = 1\n", encoding="utf-8")
    first = model_source_fingerprint(tmp_path, components=("core.py",))
    component.write_text("lambda_home = 2\n", encoding="utf-8")
    second = model_source_fingerprint(tmp_path, components=("core.py",))
    assert first["fingerprint"] != second["fingerprint"]


def test_data_only_repository_file_does_not_change_model_source_fingerprint(tmp_path):
    core = tmp_path / "core.py"
    report = tmp_path / "data" / "report.json"
    core.write_text("lambda_home = 1\n", encoding="utf-8")
    report.parent.mkdir()
    report.write_text('{"version": 1}\n', encoding="utf-8")
    first = model_source_fingerprint(tmp_path, components=("core.py",))
    report.write_text('{"version": 2}\n', encoding="utf-8")
    second = model_source_fingerprint(tmp_path, components=("core.py",))
    assert first["fingerprint"] == second["fingerprint"]


def test_changed_model_source_identity_changes_prediction_id(monkeypatch):
    first_fingerprint = {"fingerprint": "source-a", "components": {"fixture": "a"}, "algorithm": "sha256"}
    second_fingerprint = {"fingerprint": "source-b", "components": {"fixture": "b"}, "algorithm": "sha256"}
    monkeypatch.setattr("model_governance.model_source_fingerprint", lambda root: first_fingerprint)
    first = build_prediction_record(attach_snapshot(prediction_payload()), commit_sha="same-commit")
    monkeypatch.setattr("model_governance.model_source_fingerprint", lambda root: second_fingerprint)
    second = build_prediction_record(attach_snapshot(prediction_payload()), commit_sha="same-commit")
    assert first["model_run_fingerprint"] != second["model_run_fingerprint"]
    assert first["prediction_id"] != second["prediction_id"]


def test_model_input_snapshot_replays_champion_output_field_by_field():
    context = deterministic_context()
    original = build_automatic_model(context)
    snapshot = build_deterministic_model_input_snapshot(context)
    replayed = replay_deterministic_model_from_snapshot({"input": snapshot["projection"]})
    for key in ("lambda_home", "lambda_away", "expected_goals", "probabilities", "btts", "total_goals_buckets", "score_probabilities"):
        assert replayed["model"][key] == original["model"][key]
    assert replayed["decisions"]["unique_score"] == original["decisions"]["unique_score"]
    assert replayed["decisions"]["primary_contract"] == original["decisions"]["primary_contract"]


def test_persisted_model_input_snapshot_replays_champion(tmp_path):
    context = deterministic_context()
    original = build_automatic_model(context)
    payload = prediction_payload("A")
    payload["model"] = original["model"]
    payload["decisions"] = original["decisions"]
    payload = attach_snapshot(payload, context)
    record = build_prediction_record(payload, commit_sha="snapshot-commit")
    freeze_prediction(
        record,
        tmp_path / "predictions",
        input_snapshot_root=tmp_path / "input_snapshots",
    )
    persisted = load_input_snapshot(record, tmp_path / "input_snapshots")
    replayed = replay_deterministic_model_from_snapshot(persisted)
    assert replayed["model"]["probabilities"] == original["model"]["probabilities"]
    assert replayed["model"]["lambda_home"] == original["model"]["lambda_home"]
    assert replayed["model"]["lambda_away"] == original["model"]["lambda_away"]
    assert replayed["decisions"]["unique_score"] == original["decisions"]["unique_score"]


def test_unrelated_state_narrative_and_polymarket_do_not_change_model_snapshot():
    first_context = deterministic_context()
    second_context = deterministic_context()
    second_context["hard_rules"] = {"bankroll_state_changed": True, "open_bets": ["unrelated"]}
    second_context["analysis"] = {"narrative": "different wording"}
    second_context["polymarket"] = {"prices": {"home": 0.99}}
    first = build_deterministic_model_input_snapshot(first_context)
    second = build_deterministic_model_input_snapshot(second_context)
    assert first["canonical_model_input_sha256"] == second["canonical_model_input_sha256"]
    assert first["snapshot_id"] == second["snapshot_id"]


def test_real_model_input_changes_change_model_snapshot():
    first_context = deterministic_context()
    second_context = deterministic_context()
    second_context["source_snapshots"]["500_deep"]["snapshots"][0]["ouzhi"]["bookmakers"][0]["spf_current"]["home"] = 2.2
    second_context["source_snapshots"]["500_deep"]["snapshots"][0]["shuju"]["recent_form"]["home_overall"]["goals_for"] = 20
    first = build_deterministic_model_input_snapshot(first_context)
    second = build_deterministic_model_input_snapshot(second_context)
    assert first["canonical_model_input_sha256"] != second["canonical_model_input_sha256"]
    assert first["snapshot_id"] != second["snapshot_id"]


def test_generic_fetch_time_cannot_be_used_as_real_source_or_market_timestamp():
    context = deterministic_context()
    context["manifest"] = {"fetch_time": "2026-08-04T23:59:59+08:00"}
    context["source_snapshots"]["500_deep"]["snapshots"][0].pop("fetched_at")
    context["checkpoint_features"].pop("latest_captured_at")
    context["checkpoint_features"].pop("first_captured_at")
    snapshot = build_deterministic_model_input_snapshot(context)
    assert snapshot["source_cutoff_at"] is None
    assert snapshot["market_snapshot_at"] is None


def test_official_market_fallback_without_capture_time_is_not_formal_snapshot():
    context = deterministic_context()
    context["source_snapshots"]["500_deep"]["snapshots"][0]["ouzhi"]["bookmakers"] = []
    snapshot = build_deterministic_model_input_snapshot(context)
    assert snapshot["source_cutoff_at"] is None
    assert snapshot["market_snapshot_at"] is None


def test_external_form_fallback_without_capture_time_is_not_formal_snapshot():
    context = deterministic_context()
    deep = context["source_snapshots"]["500_deep"]["snapshots"][0]
    deep["shuju"].pop("recent_form")
    context["prematch_fundamentals"] = {
        "recent_form": {
            "home_overall": {"matches": 5, "goals_for": 6, "goals_against": 4},
            "away_overall": {"matches": 5, "goals_for": 5, "goals_against": 5},
        }
    }
    snapshot = build_deterministic_model_input_snapshot(context)
    assert snapshot["source_cutoff_at"] is None
    assert snapshot["market_snapshot_at"] is None


def test_new_release_and_challenger_do_not_reuse_prediction_id():
    champion = build_prediction_record(prediction_payload(), commit_sha="baseline-sha")
    release_config = load_config()
    release_config["champion"] = dict(release_config["champion"])
    release_config["champion"]["release_version"] = "v0.19.1"
    new_release = build_prediction_record(
        prediction_payload(release_version="v0.19.1"),
        config=release_config,
        commit_sha="baseline-sha",
    )
    challenger_config = load_config()
    challenger_config["challengers"] = [{
        "id": "shadow-001",
        "model_core_version": "shadow_poisson_v1",
        "model_family": "shadow_poisson_v1",
        "release_version": RELEASE_VERSION,
    }]
    challenger = build_prediction_record(
        prediction_payload(model_family="shadow_poisson_v1"),
        config=challenger_config,
        commit_sha="baseline-sha",
    )
    assert new_release["model_role"] == "champion"
    assert challenger["model_role"] == "challenger"
    assert len({champion["prediction_id"], new_release["prediction_id"], challenger["prediction_id"]}) == 3


def test_narrative_only_input_change_does_not_change_deterministic_input_hash():
    first_input = {
        "manifest": {"data_run_id": "run-1"},
        "deep": {"recent_form": {"home": 1.2}},
        "analysis": {"narrative": "first wording"},
    }
    second_input = {**first_input, "analysis": {"narrative": "different wording"}}
    first = build_prediction_record(
        prediction_payload(), input_payload=first_input, commit_sha="baseline-sha"
    )
    second = build_prediction_record(
        prediction_payload(), input_payload=second_input, commit_sha="baseline-sha"
    )
    assert first["input_sha256"] == second["input_sha256"]
    assert first["input_snapshot"]["canonical_input_sha256"] == second["input_sha256"]
    assert first["prediction_id"] == second["prediction_id"]


def test_input_snapshot_can_be_reloaded_and_tampering_is_detected(tmp_path):
    record = build_prediction_record(
        prediction_payload(),
        input_payload={"manifest": {"data_run_id": "run-2"}, "deep": {"value": 1}},
        commit_sha="baseline-sha",
    )
    snapshot_root = tmp_path / "input_snapshots"
    freeze_prediction(record, tmp_path / "predictions", input_snapshot_root=snapshot_root)
    snapshot = load_input_snapshot(record, snapshot_root)
    assert snapshot["canonical_input_sha256"] == record["input_sha256"]
    snapshot["input"]["deep"]["value"] = 99
    snapshot_path = snapshot_root / f"{record['input_snapshot']['canonical_input_sha256']}.json"
    snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")
    with pytest.raises(ValueError, match="snapshot"):
        load_input_snapshot(record, snapshot_root)


def test_promotion_requires_at_least_fifty_holdout_samples():
    result = evaluate_promotion({"sample_count": 50, "unique_match_count": 2, "same_snapshot": True, "out_of_sample": True})
    assert result["eligible_for_human_review"] is False
    assert "minimum_holdout_unique_matches" in result["blocking_reasons"]


def test_fifty_unique_matches_can_pass_sample_gate_but_still_need_all_metrics():
    result = evaluate_promotion({
        "sample_count": 50,
        "unique_match_count": 50,
        "same_snapshot": True,
        "out_of_sample": True,
        "reproducible_inputs": True,
        "champion": {"brier_score": 0.20, "log_loss": 0.50},
        "challenger": {"brier_score": 0.19, "log_loss": 0.49},
        "market_baseline": {"brier_score": 0.22, "log_loss": 0.52},
        "simple_baseline": {"brier_score": 0.25, "log_loss": 0.60},
    })
    assert result["eligible_for_human_review"] is True
    assert result["automatic_promotion"] is False
    assert result["requires_human_approval"] is True
    assert result["blocking_reasons"] == []


def test_promotion_missing_metrics_is_blocked_even_with_fifty_unique_matches():
    result = evaluate_promotion({
        "sample_count": 50,
        "unique_match_count": 50,
        "same_snapshot": True,
        "out_of_sample": True,
        "reproducible_inputs": True,
        "champion": {},
        "challenger": {},
        "market_baseline": {"brier_score": 0.22, "log_loss": 0.52},
        "simple_baseline": {"brier_score": 0.25, "log_loss": 0.60},
    })
    assert result["eligible_for_human_review"] is False
    assert "champion_brier_missing" in result["blocking_reasons"]
    assert "challenger_log_loss_missing" in result["blocking_reasons"]


def test_promotion_rejects_brier_score_without_improvement():
    result = evaluate_promotion({
        "sample_count": 50,
        "same_snapshot": True,
        "out_of_sample": True,
        "reproducible_inputs": True,
        "champion": {"brier_score": 0.20, "log_loss": 0.50},
        "challenger": {"brier_score": 0.20, "log_loss": 0.40},
        "market_baseline": {"brier_score": 0.22, "log_loss": 0.52},
        "simple_baseline": {"brier_score": 0.25, "log_loss": 0.60},
    })
    assert result["eligible_for_human_review"] is False
    assert "brier_not_improved" in result["blocking_reasons"]


def test_promotion_rejects_log_loss_deterioration():
    result = evaluate_promotion({
        "sample_count": 50,
        "same_snapshot": True,
        "out_of_sample": True,
        "reproducible_inputs": True,
        "champion": {"brier_score": 0.20, "log_loss": 0.50},
        "challenger": {"brier_score": 0.19, "log_loss": 0.60},
        "market_baseline": {"brier_score": 0.22, "log_loss": 0.52},
        "simple_baseline": {"brier_score": 0.25, "log_loss": 0.60},
    })
    assert result["eligible_for_human_review"] is False
    assert "log_loss_deteriorated" in result["blocking_reasons"]


def test_promotion_requires_same_snapshot_and_two_baselines():
    result = evaluate_promotion({
        "sample_count": 50,
        "same_snapshot": False,
        "out_of_sample": True,
        "reproducible_inputs": True,
        "champion": {"brier_score": 0.20, "log_loss": 0.50},
        "challenger": {"brier_score": 0.19, "log_loss": 0.49},
    })
    assert result["eligible_for_human_review"] is False
    assert "same_match_same_snapshot" in result["blocking_reasons"]
    assert "market_baseline_comparison_missing" in result["blocking_reasons"]
    assert "simple_baseline_comparison_missing" in result["blocking_reasons"]


def test_single_match_cannot_update_parameters():
    assert can_update_parameters(sample_count=1, match_count=1) is False
    assert can_update_parameters(sample_count=50, match_count=1) is False
    assert can_update_parameters(sample_count=50, match_count=50) is True
    assert can_update_parameters(sample_count=50, unique_match_count=2) is False
    assert can_update_parameters(sample_count=50, unique_match_count=50) is True


def test_roi_and_clv_are_null_without_real_executable_odds():
    record = build_prediction_record(prediction_payload(odds=None), commit_sha="baseline-sha")
    assert record["betting_reference_output"]["status"] == "not_evaluable"
    assert record["betting_reference_output"]["roi"] is None
    assert record["betting_reference_output"]["clv"] is None


def test_real_executable_odds_are_explicitly_marked():
    payload = prediction_payload(odds=2.1)
    payload["betting"]["candidates"][0]["price_executable"] = True
    record = build_prediction_record(payload, commit_sha="baseline-sha")
    assert record["betting_reference_output"]["status"] == "evaluable"


def test_file_hashes_detect_core_file_changes(tmp_path):
    path = tmp_path / "core.py"
    path.write_text("version = 1\n", encoding="utf-8")
    first = hash_files([path], root=tmp_path)
    path.write_text("version = 2\n", encoding="utf-8")
    second = hash_files([path], root=tmp_path)
    assert first["files"]["core.py"] != second["files"]["core.py"]


def test_fixed_fixture_math_snapshot_matches_pre_change_baseline():
    deep = {
        "shuju": {"recent_form": {
            "home_overall": {"matches": 10, "goals_for": 12, "goals_against": 13},
            "away_overall": {"matches": 10, "goals_for": 22, "goals_against": 9},
            "home_home": {"matches": 10, "goals_for": 19, "goals_against": 11},
            "away_away": {"matches": 10, "goals_for": 16, "goals_against": 13},
        }},
        "ouzhi": {"bookmakers": [
            {"spf_current": {"home": 4.5, "draw": 4.0, "away": 1.7}},
            {"spf_current": {"home": 4.2, "draw": 3.8, "away": 1.72}},
        ]},
        "daxiao": {"companies": [{"current_line": 2.75}, {"current_line": 2.5}]},
    }
    result = build_automatic_model({
        "request": {"match_id": "2040514"},
        "selected_workspace_match": {"id": "2040514", "home": "主队", "away": "客队"},
        "source_snapshots": {"500_deep": {"snapshots": [deep]}},
    })
    snapshot = {
        "probabilities": result["model"]["probabilities"],
        "lambda_home": result["model"]["lambda_home"],
        "lambda_away": result["model"]["lambda_away"],
        "score_probabilities": result["model"]["score_probabilities"],
        "unique_score": result["decisions"]["unique_score"],
        "primary_contract": result["decisions"]["primary_contract"],
        "dimension_predictions": result["model"]["dimension_predictions"],
    }
    digest = hashlib.sha256(json.dumps(
        snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()).hexdigest()
    assert digest == "b104c0f81c2a5c457967d9047b41e389209b99bd3cfc1613d9fb13fb0c2175df"


def test_current_metrics_do_not_mix_legacy_with_champion(tmp_path):
    reports = tmp_path / "reports"
    reviews = tmp_path / "reviews"
    reports.mkdir()
    reviews.mkdir()
    for index, version in enumerate((RELEASE_VERSION, "v0.18.2")):
        payload = prediction_payload()
        payload["report"]["model_version"] = version
        (reports / f"{index}.json").write_text(json.dumps(payload), encoding="utf-8")
    result = build_current_metrics(reports, reviews)
    assert result["scope"]["report_record_count"] == 2
    assert result["scope"]["historical_report_inventory"] == 2
    assert result["scope"]["true_governance_frozen_predictions"] == 0
    assert result["scope"]["legacy_records_excluded"] == 2
    assert result["scope"]["formal_prediction_count"] == 0


def test_current_metrics_compute_formal_review_dimensions(tmp_path):
    reports = tmp_path / "reports"
    reviews = tmp_path / "reviews"
    frozen = tmp_path / "frozen"
    snapshots = tmp_path / "snapshots"
    reports.mkdir()
    reviews.mkdir()
    report = prediction_payload("A")
    record = build_prediction_record(report, commit_sha="baseline-sha")
    freeze_prediction(record, frozen, input_snapshot_root=snapshots)
    report["model_governance"] = {
        "prediction_id": record["prediction_id"],
        "prediction_sha256": record["prediction_sha256"],
        "model_run_fingerprint": record["model_run_fingerprint"],
        "model_source_fingerprint": record["model_source_fingerprint"],
        "canonical_model_input_sha256": record["canonical_model_input_sha256"],
        "model_role": record["model_role"],
        "data_grade": record["data_grade"],
        "formal_eligible": record["formal_eligible"],
        "prediction_status": record["prediction_status"],
        "prediction_variant": record["prediction_variant"],
    }
    (reports / "report.json").write_text(json.dumps(report), encoding="utf-8")
    (reports / "current").mkdir()
    (reports / "current" / "report.json").write_text(json.dumps(report), encoding="utf-8")
    review = {
        "prediction_id": record["prediction_id"],
        "prediction_sha256": record["prediction_sha256"],
        "model_run_fingerprint": record["model_run_fingerprint"],
        "model_source_fingerprint": record["model_source_fingerprint"],
        "canonical_model_input_sha256": record["canonical_model_input_sha256"],
        "source_cutoff_at": record["source_cutoff_at"],
        "market_snapshot_at": record["market_snapshot_at"],
        "odds_snapshot_at": record["odds_snapshot_at"],
        "repository_commit_sha": record["repository_commit_sha"],
        "prediction_layer": {"formal_pick_eligible": True},
        "model_diagnostics": {"brier_score_1x2": 0.2, "log_loss_1x2": 0.4, "actual_score_rank": 1},
        "settlement": {
            "model_1x2": {"hit": True},
            "total_goals_mode": {"hit": False},
            "btts": {"hit": True},
        },
    }
    (reviews / "review.json").write_text(json.dumps(review), encoding="utf-8")
    result = build_current_metrics(reports, reviews, frozen_root=frozen)
    assert result["metrics"]["brier_score"] == 0.2
    assert result["metrics"]["log_loss"] == 0.4
    assert result["metrics"]["score_top1"] == 1.0
    assert result["metrics"]["win_draw_loss"]["hit_rate"] == 1.0
    assert result["metrics"]["over_under"]["hit_rate"] == 0.0
    assert result["metrics"]["btts"]["hit_rate"] == 1.0
    assert result["scope"]["report_record_count"] == 1
    assert result["scope"]["unique_prediction_count"] == 1
    assert result["scope"]["true_governance_frozen_predictions"] == 1
    assert result["scope"]["settled_prediction_count"] == 1
    assert result["scope"]["formal_unique_match_count"] == 1
    assert result["scope"]["settled_unique_match_count"] == 1


def test_postmatch_exact_prediction_join_rejects_hash_mismatch(tmp_path):
    record_root = tmp_path / "predictions"
    snapshot_root = tmp_path / "snapshots"
    record = build_prediction_record(prediction_payload("A"), commit_sha="baseline-sha")
    freeze_prediction(record, record_root, input_snapshot_root=snapshot_root)
    review = {
        "prediction_id": record["prediction_id"],
        "prediction_sha256": "wrong",
        "model_run_fingerprint": record["model_run_fingerprint"],
        "model_source_fingerprint": record["model_source_fingerprint"],
        "canonical_model_input_sha256": record["canonical_model_input_sha256"],
        "source_cutoff_at": record["source_cutoff_at"],
        "market_snapshot_at": record["market_snapshot_at"],
        "odds_snapshot_at": record["odds_snapshot_at"],
        "repository_commit_sha": record["repository_commit_sha"],
        "prediction_layer": {"formal_pick_eligible": True},
    }
    link = validate_postmatch_review_link(review, record_root)
    assert link["status"] == "hash_mismatch"
    assert link["formal_eligible"] is False
