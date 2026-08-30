import copy
import hashlib
import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from market_side_shadow import (  # noqa: E402
    CANDIDATE_NAMESPACE,
    MIN_PAIRED_VERIFIED,
    PROMOTION_REVIEW_MINIMUM,
    ShadowCaptureConflictError,
    build_challenger_c_output,
    build_shadow_document,
    capture_pair,
    evaluate_paired_cohort,
    persist_pair,
    checkpoint_status,
)


def context():
    deep = {
        "shuju": {"recent_form": {
            "home_overall": {"matches": 10, "goals_for": 15, "goals_against": 10},
            "home_home": {"matches": 10, "goals_for": 19, "goals_against": 8},
            "away_overall": {"matches": 10, "goals_for": 11, "goals_against": 14},
            "away_away": {"matches": 10, "goals_for": 9, "goals_against": 16},
        }},
        "ouzhi": {"bookmakers": [
            {"spf_current": {"home": 1.8, "draw": 3.5, "away": 4.5}},
            {"spf_current": {"home": 1.9, "draw": 3.4, "away": 4.4}},
        ]},
        "daxiao": {"companies": [{"current_line": 2.5}]},
    }
    return {
        "request": {"match_id": "fixture-001"},
        "selected_workspace_match": {"id": "fixture-001", "home": "Home", "away": "Away"},
        "source_snapshots": {"500_deep": {"snapshots": [deep]}},
    }


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def frozen_record(tmp_path, *, usable=True):
    model_context = context() if usable else {"request": {"match_id": "fixture-001"}}
    input_digest = hashlib.sha256(_canonical(model_context)).hexdigest()
    snapshot = {
        "snapshot_id": "FBOS-SNAPSHOT-fixture-001",
        "source_cutoff_at": "2026-08-30T10:00:00+08:00",
        "model_input_as_of_at": "2026-08-30T10:00:00+08:00",
        "market_snapshot_at": "2026-08-30T10:00:00+08:00",
        "captured_at": "2026-08-30T10:00:01+08:00",
        "canonical_input_sha256": input_digest,
        "canonical_model_input_sha256": input_digest,
        "input": model_context,
    }
    snapshot_path = tmp_path / "snapshots" / "fixture-001.json"
    snapshot_path.parent.mkdir(parents=True)
    snapshot_path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    record = {
        "prediction_id": "FBOS-PRED-fixture-001",
        "prediction_sha256": "champion-record-sha",
        "prediction_status": "formal",
        "prediction_variant": "model_only",
        "model_role": "champion",
        "formal_eligible": True,
        "model_formal_eligible": True,
        "formal_eligibility_policy": "base_prediction_minimum.v1",
        "model_family": "recent_form_market_calibrated_poisson_v2",
        "model_core_version": "recent_form_market_calibrated_poisson_v2",
        "match_id": "fixture-001",
        "match_key": "FBOS-fixture-001",
        "kickoff_at": "2026-08-30T12:00:00+08:00",
        "source_cutoff_at": "2026-08-30T10:00:00+08:00",
        "freeze_created_at": "2026-08-30T10:01:00+08:00",
        "input_snapshot_ref": "snapshots/fixture-001.json",
        "model_input_snapshot_ref": "snapshots/fixture-001.json",
        "input_sha256": input_digest,
        "canonical_model_input_sha256": input_digest,
        "input_snapshot": {
            "snapshot_id": snapshot["snapshot_id"],
            "canonical_input_sha256": input_digest,
            "canonical_model_input_sha256": input_digest,
            "source_cutoff_at": snapshot["source_cutoff_at"],
        },
    }
    return record


def test_challenger_c_keeps_champion_total_and_emits_full_distribution():
    output = build_challenger_c_output(context())

    assert output["candidate_id"] == "market_side_only_hybrid"
    assert output["formula"]["total"] == "champion_total_0.60_form_0.40_market"
    assert output["formula"]["share"] == "market_share_only"
    assert output["rho"] == 0.0
    assert len(output["exact_score_distribution"]) == 169
    assert output["score_top1"] == output["exact_score_distribution"][0]["score"]
    assert output["score_top3"] == [row["score"] for row in output["exact_score_distribution"][:3]]
    assert sum(row["probability"] for row in output["exact_score_distribution"]) == pytest.approx(1.0, abs=1e-9)
    assert set(output["tail_probabilities"]) == {"total_ge_4", "total_ge_5", "total_ge_6"}


def test_capture_pair_has_same_identity_and_write_once_persistence(tmp_path):
    record = frozen_record(tmp_path)
    pair = capture_pair(record, snapshot_root=tmp_path)

    assert pair["pair_status"] == "PAIRED"
    assert pair["match_id"] == "fixture-001"
    assert pair["source_cutoff"] == "2026-08-30T10:00:00+08:00"
    assert pair["frozen_input_digest"]
    assert pair["champion"]["frozen_input_digest"] == pair["challenger"]["frozen_input_digest"]
    assert pair["champion"]["freeze_eligibility"] == pair["challenger"]["freeze_eligibility"]
    assert pair["champion"]["namespace"] != pair["challenger"]["namespace"]
    assert pair["challenger"]["namespace"] == CANDIDATE_NAMESPACE
    assert len(pair["challenger"]["exact_score_distribution"]) == 169

    root = tmp_path / "pairs"
    first = persist_pair(pair, root)
    second = persist_pair(pair, root)
    assert first["status"] == "created"
    assert second["status"] == "existing"

    changed = copy.deepcopy(pair)
    changed["challenger"]["lambda_home"] += 0.01
    with pytest.raises(ShadowCaptureConflictError):
        persist_pair(changed, root)


def test_challenger_abstain_keeps_champion_side_of_pair(tmp_path):
    record = frozen_record(tmp_path, usable=False)
    pair = capture_pair(record, snapshot_root=tmp_path)

    assert pair["pair_status"] == "CHALLENGER_ABSTAIN"
    assert pair["champion"]["prediction_id"] == record["prediction_id"]
    assert pair["challenger"] is None
    assert pair["challenger_abstain_reason"]
    assert pair["champion_preserved"] is True


def test_evaluator_consumes_pairs_and_keeps_reliability_bins(tmp_path):
    pair = capture_pair(frozen_record(tmp_path), snapshot_root=tmp_path)
    evaluation = evaluate_paired_cohort(
        [pair],
        {"fixture-001": {"actual_score": "2-1"}},
    )

    assert evaluation["verified_paired_count"] == 1
    assert evaluation["post_match_input_used_for_generation"] is False
    for candidate_id in ("champion", "challenger"):
        metrics = evaluation["candidates"][candidate_id]
        assert metrics["one_x_two"]["sample_count"] == 1
        assert metrics["exact_score"]["nll"] >= 0
        assert len(metrics["btts"]["reliability_bins"]) == 5
        assert sum(item["count"] for item in metrics["btts"]["reliability_bins"]) == 1
        assert set(metrics["btts"]["reliability_bins"][0]) >= {
            "count", "mean_predicted_probability", "observed_frequency"
        }
        assert set(metrics["right_tail"]) == {"total_ge_4", "total_ge_5", "total_ge_6"}


def test_checkpoints_are_automatic_and_never_promote():
    assert checkpoint_status(49)["status"] == "NOT_REACHED"
    assert checkpoint_status(MIN_PAIRED_VERIFIED)["status"] == "CHECKPOINT"
    assert checkpoint_status(PROMOTION_REVIEW_MINIMUM)["status"] == "PROMOTION_REVIEW_READY"
    assert checkpoint_status(PROMOTION_REVIEW_MINIMUM)["auto_promote"] is False


def test_shadow_document_contains_contract_without_postmatch_capture_fields(tmp_path):
    pair = capture_pair(frozen_record(tmp_path), snapshot_root=tmp_path)
    document = build_shadow_document([pair])

    assert document["milestone"] == "MARKET-SIDE-SHADOW-1"
    assert document["namespace"] == "market_side_shadow_1"
    assert document["capture_contract"]["champion_unchanged"] is True
    assert document["capture_contract"]["production_enabled"] is False
    assert document["checkpoint"]["status"] == "NOT_REACHED"
    assert "actual_result" not in pair
    assert "settlement" not in pair
    assert "metrics" not in pair


def test_base_runner_shadow_hook_persists_c_without_touching_champion(tmp_path):
    from base_prediction_runner import _capture_market_side_shadow

    record = frozen_record(tmp_path)
    result = _capture_market_side_shadow(
        record,
        input_snapshot_root=tmp_path,
        shadow_pair_root=tmp_path / "pairs",
    )

    assert result["status"] == "created"
    assert result["pair_status"] == "PAIRED"
    assert result["path"].endswith(".json")
    assert list((tmp_path / "pairs").glob("*.json"))
    assert record["prediction_id"] == "FBOS-PRED-fixture-001"
